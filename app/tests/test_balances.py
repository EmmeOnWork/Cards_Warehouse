"""The balances module: what Manuel owes each partner, or each partner owes him, from the purchases each paid more or
less than their share, and from the sales each took the money of.

On a real PostgreSQL, through the module's functions.
"""

from dataclasses import replace
from datetime import date

import pytest

from cards_warehouse import balances, gradings, manual_channels, partners, purchases, sales, stock
from cards_warehouse.sales import Cancellation, Sale
from tests.test_exposure import channel_ids
from tests.test_purchases import BOXES, a_sealed


# 104,00 € half and half, all paid by Luca: 52,00 € of it were Manuel's to pay.
def test_a_purchase_paid_all_by_the_partner_leaves_manuel_owing_him_the_share_manuel_did_not_pay(connection):
    luca = partners.add(connection, "Luca")
    shared = replace(BOXES, shares=(purchases.Share(None, 50, 0), purchases.Share(luca, 50, 10400)))

    purchases.record(connection, shared, a_sealed(connection), quantity=3)

    assert owed_by_manuel(connection) == {"Luca": 5200}


def test_a_purchase_paid_all_by_manuel_leaves_the_partner_owing_him_his_share(connection):
    luca = partners.add(connection, "Luca")
    shared = replace(BOXES, shares=(purchases.Share(None, 50, 10400), purchases.Share(luca, 50, 0)))

    purchases.record(connection, shared, a_sealed(connection), quantity=3)

    assert owed_by_manuel(connection) == {"Luca": -5200}


# 100,01 € in 34, 33 and 33 % is 34,01 € to Manuel, who takes the cent left over, and 33,00 € each to Luca and Marco.
# Luca paid 50,01 €, 17,01 € more than his part; Marco paid nothing, and owes his 33,00 €.
def test_payments_unlike_the_shares_leave_each_partner_owed_or_owing_what_he_paid_beyond_or_short_of_his_part(
    connection,
):
    luca, marco = partners.add(connection, "Luca"), partners.add(connection, "Marco")
    shares = (purchases.Share(None, 34, 5000), purchases.Share(luca, 33, 5001), purchases.Share(marco, 33, 0))

    purchases.record(connection, replace(BOXES, total_cost_cents=9601, shares=shares), a_sealed(connection), 3)

    assert owed_by_manuel(connection) == {"Luca": 1701, "Marco": -3300}


def test_a_partner_who_shares_nothing_is_even(connection):
    partners.add(connection, "Luca")

    purchases.record(connection, BOXES, a_sealed(connection), quantity=3)

    assert owed_by_manuel(connection) == {"Luca": 0}


# A box half Luca's, its purchase paid half each, sold on Vinted at 60,00 € with 5,00 € of shipping on Manuel: of the
# 55,00 € he took, 27,50 € are Luca's.
def test_a_sale_whose_money_manuel_took_leaves_him_owing_the_partner_his_part_of_the_net(connection):
    box, _ = a_shared_box(connection)

    sales.record(connection, Sale(box, vinted(connection), 1, 6000, shipping_cents=500), manual_channels.MANUAL)

    assert owed_by_manuel(connection) == {"Luca": 2750}


# The same sale from Luca's own account: the 55,00 € went to him, and 27,50 € of them are Manuel's.
def test_a_sale_whose_money_the_partner_took_leaves_him_owing_manuel_his_part_of_the_net(connection):
    box, luca = a_shared_box(connection)

    sale = Sale(box, vinted(connection), 1, 6000, shipping_cents=500, collected_by=luca)
    sales.record(connection, sale, manual_channels.MANUAL)

    assert owed_by_manuel(connection) == {"Luca": -2750}


# Luca sold for Manuel a box all Manuel's: none of the money is Luca's.
def test_a_sale_of_a_lot_all_manuels_whose_money_the_partner_took_leaves_him_owing_manuel_all_the_net(connection):
    luca = partners.add(connection, "Luca")
    box = a_sealed(connection)
    purchases.record(connection, BOXES, box, quantity=3)

    sale = Sale(box, vinted(connection), 1, 6000, shipping_cents=500, collected_by=luca)
    sales.record(connection, sale, manual_channels.MANUAL)

    assert owed_by_manuel(connection) == {"Luca": -5500}


# Four boxes sold together for 200,00 €: three from the purchase half Luca's, one from a lot all Manuel's. Each box is
# 50,00 €, and Luca has half of three of them: 75,00 €.
def test_a_sale_across_lots_with_different_shares_splits_each_box_by_the_shares_of_its_own_lot(connection):
    box, _ = a_shared_box(connection)
    stock.load(connection, box, quantity=1, unit_cost_cents=5000)

    sales.record(connection, Sale(box, vinted(connection), 4, 20000), manual_channels.MANUAL)

    assert owed_by_manuel(connection) == {"Luca": 7500}


# A return: the money went back to the buyer, and nobody owes anybody anything for it.
def test_a_sale_cancelled_leaves_the_balance_as_it_was_before_it(connection):
    box, luca = a_shared_box(connection)
    sale = Sale(box, vinted(connection), 1, 6000, collected_by=luca)
    sale_id = sales.record(connection, sale, manual_channels.MANUAL)

    sales.cancel(connection, sale_id, Cancellation.RETURN)

    assert owed_by_manuel(connection) == {"Luca": 0}


# A copy half Luca's sent to PSA, 15,00 € paid by one of them: half of it was the other's to pay. It counts from the
# day the card left, before it is back: the grading is paid already.
@pytest.mark.parametrize(("paid_by_luca", "owed"), [(True, 750), (False, -750)])
def test_a_grading_paid_by_one_alone_leaves_the_other_owing_his_share_of_it(connection, paid_by_luca, owed):
    box, luca = a_shared_box(connection)
    [lot, _] = stock.lots(connection, box)

    sending = gradings.Sending(date(2026, 10, 30), "PSA", cost_cents=1500, paid_by=luca if paid_by_luca else None)
    gradings.send(connection, lot.id, sending)

    assert owed_by_manuel(connection) == {"Luca": owed}


# The four boxes sold by Luca for 200,01 €: 125,00 € and a bit to Manuel, who takes the cent left over, 75,00 € and a
# bit to Luca. The parts are the net, to the cent.
def test_the_parts_of_a_sale_say_who_took_the_money_and_each_persons_part_of_the_net(connection):
    box, luca = a_shared_box(connection)
    stock.load(connection, box, quantity=1, unit_cost_cents=5000)

    sale = sales.record(connection, Sale(box, vinted(connection), 4, 20001, collected_by=luca), manual_channels.MANUAL)

    assert balances.of_sale(connection, sale) == balances.SaleParts("Luca", [("Manuel", 12501), ("Luca", 7500)])


def a_shared_box(connection) -> tuple[int, int]:
    """A box of three bought for 104,00 €, half Luca's, each paying his half; and Luca."""
    luca = partners.add(connection, "Luca")
    shared = replace(BOXES, shares=(purchases.Share(None, 50, 5200), purchases.Share(luca, 50, 5200)))
    box = a_sealed(connection)
    purchases.record(connection, shared, box, quantity=3)
    return box, luca


def vinted(connection) -> int:
    [channel] = channel_ids(connection, "Vinted")
    return channel


def owed_by_manuel(connection) -> dict[str, int]:
    """What Manuel owes each partner, by name: below zero, what the partner owes him."""
    return {balance.name: balance.cents for balance in balances.every(connection)}
