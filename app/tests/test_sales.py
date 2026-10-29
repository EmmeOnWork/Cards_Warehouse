"""The sales module: a sale takes its copies from the stock, and leaves a real margin.

On a real PostgreSQL, through the module's functions, with every channel a manual one.
"""

from datetime import date
from decimal import Decimal

import pytest

from cards_warehouse import gradings, items, manual_channels, sales, stock
from cards_warehouse.items import Card, Condition, Item, Kind
from cards_warehouse.pricing import Margin
from cards_warehouse.sales import NotEnoughCopies, Sale
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


# Until the double sales (task 24): the stock would go below zero.
def test_a_sale_of_more_copies_than_are_left_is_refused_and_takes_nothing(connection):
    card = a_card(connection, copies=2, unit_cost_cents=3000)

    with pytest.raises(NotEnoughCopies) as refused:
        sales.record(connection, Sale(card, tilt(connection), 3, 9000), manual_channels.MANUAL)

    assert refused.value.available == 2
    assert stock.available(connection, card) == 2


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
