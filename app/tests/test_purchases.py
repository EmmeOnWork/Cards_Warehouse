"""The purchases module: the lots a purchase makes, and the shares they carry.

On a real PostgreSQL, through the module's functions.
"""

from dataclasses import replace
from datetime import date

import pytest

from cards_warehouse import items, partners, purchases, stock
from cards_warehouse.items import Item, Kind
from cards_warehouse.purchases import PaymentsNotTotal, Piece, Purchase, Share, SharesNotWhole

BOXES = Purchase(total_cost_cents=10000, shipping_cents=400, purchased_on=date(2026, 10, 20))


# A lot is copies at one unit cost: 104,00 € in three makes a lot of two at 34,67 € and a lot of one at 34,66 €.
def test_a_purchase_whose_cost_leaves_cents_over_makes_two_lots_that_add_up_to_it(connection):
    purchases.record(connection, BOXES, a_sealed(connection), quantity=3)

    (purchase,) = purchases.listing(connection)

    assert [(lot.unit_cost_cents, lot.copies) for lot in purchase.lots] == [(3467, 2), (3466, 1)]
    assert sum(lot.unit_cost_cents * lot.copies for lot in purchase.lots) == 10400


def test_a_purchase_whose_cost_divides_exactly_makes_one_lot(connection):
    purchases.record(connection, replace(BOXES, total_cost_cents=10100), a_sealed(connection), quantity=3)

    (purchase,) = purchases.listing(connection)

    assert [(lot.unit_cost_cents, lot.copies) for lot in purchase.lots] == [(3500, 3)]


# Manuel first, then each partner: what each has of the purchase, and what each paid of it.
def test_a_purchase_keeps_the_shares_and_what_each_one_paid(connection):
    luca = partners.add(connection, "Luca")
    shared = replace(BOXES, shares=(Share(None, 50, 0), Share(luca, 50, 10400)))

    purchases.record(connection, shared, a_sealed(connection), quantity=3)

    (purchase,) = purchases.listing(connection)
    assert purchase.shares == (("Manuel", 50, 0), ("Luca", 50, 10400))


def test_a_purchase_without_shares_is_all_manuels_who_paid_it_all(connection):
    purchases.record(connection, BOXES, a_sealed(connection), quantity=3)

    (purchase,) = purchases.listing(connection)

    assert purchase.shares == (("Manuel", 100, 10400),)


# 90% would leave a tenth of every sale to nobody, and 110% would give away more than there is.
@pytest.mark.parametrize("luca_percent", [40, 60])
def test_shares_that_do_not_add_up_to_100_percent_are_refused_and_nothing_is_loaded(connection, luca_percent):
    luca = partners.add(connection, "Luca")
    item = a_sealed(connection)
    uneven = replace(BOXES, shares=(Share(None, 50, 10400), Share(luca, luca_percent, 0)))

    with pytest.raises(SharesNotWhole):
        purchases.record(connection, uneven, item, quantity=3)

    assert purchases.listing(connection) == []
    assert stock.available(connection, item) == 0


# The seller was paid the cost and the shipping, no more and no less: 100,00 € alone leaves the shipping unpaid.
@pytest.mark.parametrize("luca_paid", [10000, 10500])
def test_payments_that_are_not_the_cost_plus_the_shipping_are_refused_and_nothing_is_loaded(connection, luca_paid):
    luca = partners.add(connection, "Luca")
    item = a_sealed(connection)
    unpaid = replace(BOXES, shares=(Share(None, 50, 0), Share(luca, 50, luca_paid)))

    with pytest.raises(PaymentsNotTotal):
        purchases.record(connection, unpaid, item, quantity=3)

    assert purchases.listing(connection) == []
    assert stock.available(connection, item) == 0


# A sale from either lot will split its net by these shares (task 41), and an opening will hand them on (task 45).
def test_every_lot_of_a_purchase_carries_its_shares(connection):
    luca = partners.add(connection, "Luca")
    item = a_sealed(connection)
    shared = replace(BOXES, shares=(Share(None, 50, 0), Share(luca, 50, 10400)))

    purchases.record(connection, shared, item, quantity=3)

    lots = stock.lots(connection, item)
    assert [purchases.shares_of_lot(connection, lot.id) for lot in lots] == [{None: 50, luca: 50}] * 2


# Loaded with the cost typed by hand before purchases existed, or with a cost not known: nobody shares it.
@pytest.mark.parametrize("unit_cost_cents", [8990, None])
def test_a_lot_without_a_purchase_is_all_manuels(connection, unit_cost_cents):
    lot = stock.load(connection, a_sealed(connection), quantity=2, unit_cost_cents=unit_cost_cents)

    assert purchases.shares_of_lot(connection, lot) == {None: 100}


CARDS = Purchase(total_cost_cents=10000, shipping_cents=0, purchased_on=date(2026, 10, 20))


# Three Charizard estimated 200 € each and a Pikachu estimated 2 €, for 100 €: 33,22… € a Charizard and 0,33 € the
# Pikachu. A Charizard takes the cent left over, in a lot of its own, and the lots add up to 100 € again.
def test_a_mixed_purchase_splits_its_cost_by_the_estimated_values_in_lots_that_add_up_to_it(connection):
    charizard, pikachu = a_card(connection, "Charizard ex"), a_card(connection, "Pikachu")

    purchases.record_mixed(connection, CARDS, [Piece(charizard, 3, 20000), Piece(pikachu, 1, 200)])

    (purchase,) = purchases.listing(connection)
    assert [(lot.item, lot.unit_cost_cents, lot.copies) for lot in purchase.lots] == [
        ("Charizard ex", 3323, 1),
        ("Charizard ex", 3322, 2),
        ("Pikachu", 33, 1),
    ]
    assert sum(lot.unit_cost_cents * lot.copies for lot in purchase.lots) == 10000


def test_every_lot_of_a_mixed_purchase_carries_its_shares(connection):
    luca = partners.add(connection, "Luca")
    charizard, pikachu = a_card(connection, "Charizard ex"), a_card(connection, "Pikachu")
    shared = replace(CARDS, shares=(Share(None, 50, 10000), Share(luca, 50, 0)))

    purchases.record_mixed(connection, shared, [Piece(charizard, 3, 20000), Piece(pikachu, 1, 200)])

    lots = stock.lots(connection, charizard) + stock.lots(connection, pikachu)
    assert [purchases.shares_of_lot(connection, lot.id) for lot in lots] == [{None: 50, luca: 50}] * 3


# A piece estimated at nothing would cost nothing, and its margin in percent could not be worked out.
@pytest.mark.parametrize("estimated_value_cents", [0, -100])
def test_a_piece_estimated_below_a_cent_is_refused_and_nothing_is_loaded(connection, estimated_value_cents):
    charizard, pikachu = a_card(connection, "Charizard ex"), a_card(connection, "Pikachu")

    with pytest.raises(ValueError, match="estimated"):
        purchases.record_mixed(
            connection, CARDS, [Piece(charizard, 1, 20000), Piece(pikachu, 1, estimated_value_cents)]
        )

    assert purchases.listing(connection) == []
    assert stock.available(connection, charizard) == stock.available(connection, pikachu) == 0


def a_card(connection, name: str) -> int:
    return items.add(connection, Item(kind=Kind.SINGLE_CARD, game="Pokémon", name=name, language="it"))


def a_sealed(connection) -> int:
    return items.add(connection, Item(kind=Kind.SEALED, game="Pokémon", name="Booster box", language="it"))
