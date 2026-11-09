"""The sales module: a sale takes its copies from the stock, and leaves a real margin.

On a real PostgreSQL, through the module's functions, with every channel a manual one.
"""

from datetime import date
from decimal import Decimal

import pytest

from cards_warehouse import gradings, items, manual_channels, sales, stock
from cards_warehouse.items import Card, Condition, Item, Kind
from cards_warehouse.pricing import Margin
from cards_warehouse.sales import AlreadyCancelled, Cancellation, NotEnoughCopies, Sale
from cards_warehouse.stock import Cause
from tests.test_exposure import channel_ids


# Tilt keeps 2% + 0,50: 1,70 of 60,00. With 3,00 of shipping on Manuel and a cost of 50,00, 5,30 are left: 10,6%.
def test_the_real_margin_is_the_price_less_the_fee_the_shipping_and_the_cost_of_the_copies_sold(connection):
    card = a_card(connection, copies=1, unit_cost_cents=5000)

    sale = sales.record(connection, Sale(card, tilt(connection), 1, 6000, shipping_cents=300), manual_channels.MANUAL)

    recorded = sales.one(connection, sale)
    assert (recorded.fee_cents, recorded.cost_cents, recorded.margin) == (170, 5000, Margin(530, Decimal("10.6")))


# Tilt kept 1,50 instead of the 1,70 of its rule, as its app says: the margin is the real one, with 1,50.
def test_a_fee_corrected_by_manuel_is_the_one_kept_in_place_of_the_channels_rule(connection):
    card = a_card(connection, copies=1, unit_cost_cents=5000)

    sale = sales.record(connection, Sale(card, tilt(connection), 1, 6000, fee_cents=150), manual_channels.MANUAL)

    recorded = sales.one(connection, sale)
    assert (recorded.fee_cents, recorded.margin) == (150, Margin(850, Decimal("17")))


# The first lot has one copy left at 30,00, the second three at 40,00: two copies sold cost 70,00.
def test_without_a_choice_a_sale_takes_the_oldest_lot_first_and_goes_on_to_the_next(connection):
    card = a_card(connection, copies=1, unit_cost_cents=3000)
    stock.load(connection, card, quantity=3, unit_cost_cents=4000)

    sale = sales.record(connection, Sale(card, tilt(connection), 2, 10000), manual_channels.MANUAL)

    assert sales.one(connection, sale).cost_cents == 7000
    assert [lot.available for lot in stock.lots(connection, card)] == [0, 2]


# Manuel sold the copy of the second lot, at 40,00: the older one at 30,00 stays as it was.
def test_a_sale_takes_its_copies_from_the_lot_manuel_chose(connection):
    card = a_card(connection, copies=3, unit_cost_cents=3000)
    stock.load(connection, card, quantity=1, unit_cost_cents=4000)
    second = stock.lots(connection, card)[1]

    sale = sales.record(connection, Sale(card, tilt(connection), 1, 6000, lot_id=second.id), manual_channels.MANUAL)

    assert sales.one(connection, sale).cost_cents == 4000
    assert [lot.available for lot in stock.lots(connection, card)] == [3, 0]


# A cost not known is not zero: the margin would look as large as the price.
def test_a_sale_of_a_copy_whose_cost_is_not_known_has_no_margin(connection):
    card = a_card(connection, copies=1, unit_cost_cents=None)

    sale = sales.record(connection, Sale(card, tilt(connection), 1, 6000), manual_channels.MANUAL)

    recorded = sales.one(connection, sale)
    assert (recorded.cost_cents, recorded.margin) == (None, None)


# The only copy went on Vinted, and was bought on Tilt too: that sale takes nothing, and the stock stays at zero.
def test_a_sale_of_copies_sold_out_is_a_double_sale_that_takes_nothing(connection):
    card = a_card(connection, copies=1, unit_cost_cents=5000)
    vinted, tilt = channel_ids(connection, "Vinted", "Tilt")
    sales.record(connection, Sale(card, vinted, 1, 6000), manual_channels.MANUAL)

    double = sales.record(connection, Sale(card, tilt, 1, 6000), manual_channels.MANUAL)

    recorded = sales.one(connection, double)
    assert (recorded.double, recorded.cost_cents, recorded.margin) == (True, None, None)
    assert stock.available(connection, card) == 0
    assert [movement.cause for movement in stock.history(connection, card)] == [Cause.LOAD, Cause.SALE]


# Two copies left, three sold on Tilt at 90,00, which keeps 2,30, with 3,00 of shipping: the two there are a sale of
# 60,00 with 1,53 of the fee and all the shipping, the third a double sale of the rest, in the same order.
def test_a_sale_of_more_copies_than_are_left_sells_those_there_are_and_the_rest_is_a_double_sale(connection):
    card = a_card(connection, copies=2, unit_cost_cents=3000)

    sale = sales.record(connection, Sale(card, tilt(connection), 3, 9000, shipping_cents=300), manual_channels.MANUAL)

    sold = sales.one(connection, sale)
    double = sales.one(connection, sold.double_part)
    assert (sold.double, sold.quantity, sold.price_cents, sold.fee_cents, sold.shipping_cents, sold.cost_cents) == (
        False,
        2,
        6000,
        153,
        300,
        6000,
    )
    assert (double.double, double.quantity, double.price_cents, double.fee_cents, double.shipping_cents) == (
        True,
        1,
        3000,
        77,
        0,
    )
    assert stock.available(connection, card) == 0


# The lot chosen has one copy, the item three: two copies cannot come from that lot.
def test_a_sale_of_more_copies_than_the_lot_chosen_has_is_refused_and_takes_nothing(connection):
    card = a_card(connection, copies=2, unit_cost_cents=3000)
    stock.load(connection, card, quantity=1, unit_cost_cents=4000)
    second = stock.lots(connection, card)[1]

    with pytest.raises(NotEnoughCopies) as refused:
        sales.record(connection, Sale(card, tilt(connection), 2, 9000, lot_id=second.id), manual_channels.MANUAL)

    assert refused.value.available == 1
    assert [lot.available for lot in stock.lots(connection, card)] == [2, 1]


def test_a_sale_keeps_the_note_manuel_wrote_on_it(connection):
    card = a_card(connection, copies=1, unit_cost_cents=5000)
    note = "Prezzo di favore a Luca, cliente fisso"

    sale = sales.record(connection, Sale(card, tilt(connection), 1, 5500, note=note), manual_channels.MANUAL)

    assert sales.one(connection, sale).note == note


# The card cost 34,67 and its grading 15,00: the graded card's lot costs 49,67 (task 40), and so does its sale.
def test_a_graded_card_sold_costs_the_card_and_its_grading(connection):
    card = a_card(connection, copies=1, unit_cost_cents=3467)
    [lot] = stock.lots(connection, card)
    sending = gradings.Sending(sent_on=date(2026, 7, 1), grader="PSA", cost_cents=1500, paid_by=None)
    graded = gradings.receive(connection, gradings.send(connection, lot.id, sending), date(2026, 10, 1), Decimal(10))

    sale = sales.record(connection, Sale(graded, tilt(connection), 1, 7000), manual_channels.MANUAL)

    assert sales.one(connection, sale).cost_cents == 4967


# Two copies sold together from two lots, at 30,00 and 40,00, and sent back: each goes back to its own lot, at its cost.
def test_a_sale_cancelled_puts_each_copy_back_in_the_lot_it_came_from(connection):
    card = a_card(connection, copies=1, unit_cost_cents=3000)
    stock.load(connection, card, quantity=1, unit_cost_cents=4000)
    before = stock.lots(connection, card)
    sale = sales.record(connection, Sale(card, tilt(connection), 2, 10000), manual_channels.MANUAL)

    sales.cancel(connection, sale, Cancellation.RETURN)

    assert stock.lots(connection, card) == before


# The buyer cancelled the order: the sale stays, known as cancelled and why.
def test_a_sale_cancelled_stays_with_the_cause_and_the_note_of_its_cancellation(connection):
    card = a_card(connection, copies=1, unit_cost_cents=5000)
    sale = sales.record(connection, Sale(card, tilt(connection), 1, 6000), manual_channels.MANUAL)

    sales.cancel(connection, sale, Cancellation.ORDER_CANCELLED, note="Ha cambiato idea")

    cancelled = sales.one(connection, sale).cancelled
    assert (cancelled.cause, cancelled.note) == (Cancellation.ORDER_CANCELLED, "Ha cambiato idea")


# The copy sold on Tilt had gone on Vinted, not recorded yet: the Tilt order is cancelled as a double sale, not as a
# return nor as an order the buyer cancelled, and the copy goes back, for the Vinted sale to take.
def test_a_sale_cancelled_as_a_double_sale_puts_its_copy_back_and_keeps_that_cause(connection):
    card = a_card(connection, copies=1, unit_cost_cents=5000)
    sale = sales.record(connection, Sale(card, tilt(connection), 1, 6000), manual_channels.MANUAL)

    sales.cancel(connection, sale, Cancellation.DOUBLE_SALE)

    assert sales.one(connection, sale).cancelled.cause == Cancellation.DOUBLE_SALE
    assert stock.available(connection, card) == 1


# Three orders went wrong on Mew ex: one found it sold out, and was cancelled then as a double sale; one was recorded
# before the copy sold elsewhere was, and was cancelled as a double sale; one of three copies, with two left, was
# cancelled whole as a double sale, both its parts. Each is one double sale, the newest first. A return is none.
def test_each_order_that_found_its_copies_sold_already_is_one_double_sale_even_once_cancelled(connection):
    card = a_card(connection, copies=1, unit_cost_cents=5000)
    vinted, tilt = channel_ids(connection, "Vinted", "Tilt")
    sales.record(connection, Sale(card, vinted, 1, 6000), manual_channels.MANUAL)
    sold_out = sales.record(connection, Sale(card, tilt, 1, 6000), manual_channels.MANUAL)
    sales.cancel(connection, sold_out, Cancellation.DOUBLE_SALE)
    stock.load(connection, card, quantity=1, unit_cost_cents=5000)
    recorded_first = sales.record(connection, Sale(card, tilt, 1, 6000), manual_channels.MANUAL)
    sales.cancel(connection, recorded_first, Cancellation.DOUBLE_SALE)
    stock.load(connection, card, quantity=1, unit_cost_cents=5000)
    returned = sales.record(connection, Sale(card, vinted, 1, 6000), manual_channels.MANUAL)
    sales.cancel(connection, returned, Cancellation.RETURN)
    partial = sales.record(connection, Sale(card, tilt, 3, 18000), manual_channels.MANUAL)
    sales.cancel(connection, partial, Cancellation.DOUBLE_SALE)
    sales.cancel(connection, sales.one(connection, partial).double_part, Cancellation.DOUBLE_SALE)

    doubles = sales.doubles(connection)

    assert [(double.channel, double.name, double.quantity) for double in doubles] == [
        ("Tilt", "Mew ex", 1),
        ("Tilt", "Mew ex", 1),
        ("Tilt", "Mew ex", 1),
    ]
    assert [double.sale_id for double in doubles] == [
        sales.one(connection, partial).double_part,
        recorded_first,
        sold_out,
    ]


# Its copies went back once: a second cancellation would give them back again, and the stock would count them twice.
def test_a_sale_cancelled_already_cannot_be_cancelled_again(connection):
    card = a_card(connection, copies=1, unit_cost_cents=5000)
    sale = sales.record(connection, Sale(card, tilt(connection), 1, 6000), manual_channels.MANUAL)
    sales.cancel(connection, sale, Cancellation.RETURN)

    with pytest.raises(AlreadyCancelled):
        sales.cancel(connection, sale, Cancellation.ORDER_CANCELLED)

    assert stock.available(connection, card) == 1
    assert sales.one(connection, sale).cancelled.cause == Cancellation.RETURN


def a_card(connection, copies: int, unit_cost_cents: int | None) -> int:
    card = Card(set_name="151", number="151/165", state=Condition.NEAR_MINT)
    item = items.add(
        connection, Item(kind=Kind.SINGLE_CARD, game="Pokémon", name="Mew ex", language="it", details=card)
    )
    stock.load(connection, item, quantity=copies, unit_cost_cents=unit_cost_cents)
    return item


def tilt(connection) -> int:
    [channel] = channel_ids(connection, "Tilt")
    return channel
