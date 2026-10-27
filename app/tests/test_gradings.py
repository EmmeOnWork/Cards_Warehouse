"""The gradings module: a copy sent to a grader leaves its lot, and comes back as an item of its own.

On a real PostgreSQL, through the module's functions.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from cards_warehouse import gradings, items, partners, purchases, stock
from cards_warehouse.gradings import AlreadyBack, Sending
from cards_warehouse.items import Card, Condition, Grading, Item, Kind
from cards_warehouse.purchases import Purchase, Share
from cards_warehouse.stock import Cause

TO_PSA = Sending(sent_on=date(2026, 10, 27), grader="PSA", cost_cents=1500, paid_by=None)
BACK = date(2027, 1, 15)
CHARIZARD = Item(
    Kind.SINGLE_CARD,
    "Pokémon",
    "Charizard ex",
    "it",
    details=Card(Condition.NEAR_MINT, "Ossidiana Infuocata", "223/197"),
)


# At the grader for months: not in the stock, so not for sale.
def test_a_copy_sent_for_grading_leaves_its_lot(connection):
    card = a_charizard(connection)
    (lot, *_) = stock.lots(connection, card)

    gradings.send(connection, lot.id, TO_PSA)

    assert stock.available(connection, card) == 2
    assert [(m.cause, m.change) for m in stock.history(connection, card)][-1] == (Cause.SENT_FOR_GRADING, -1)


# A graded card is not one of the copies it was taken from: it is sold as what it is, at a price of its own.
def test_a_copy_back_from_grading_is_an_item_of_its_own_with_its_grade_and_the_grading_in_its_cost(connection):
    luca = partners.add(connection, "Luca")
    card = a_charizard(connection, shares=(Share(None, 50, 0), Share(luca, 50, 10400)))
    (lot, *_) = stock.lots(connection, card)

    graded = gradings.receive(connection, gradings.send(connection, lot.id, TO_PSA), BACK, grade=Decimal(9))

    assert items.get(connection, graded) == replace(
        CHARIZARD, details=Card(Grading("PSA", Decimal(9)), "Ossidiana Infuocata", "223/197")
    )
    (graded_lot,) = stock.lots(connection, graded)
    assert (graded_lot.available, graded_lot.unit_cost_cents) == (1, 3467 + 1500)
    assert purchases.shares_of_lot(connection, graded_lot.id) == {None: 50, luca: 50}
    assert [(m.cause, m.change) for m in stock.history(connection, graded)] == [(Cause.GRADED, 1)]


# Not known plus 15,00 € is not known: the copy may have cost anything.
def test_a_copy_whose_cost_was_not_known_comes_back_with_a_cost_not_known(connection):
    card = items.add(connection, CHARIZARD)
    lot = stock.load(connection, card, 1, unit_cost_cents=None)

    graded = gradings.receive(connection, gradings.send(connection, lot, TO_PSA), BACK, grade=Decimal(9))

    assert [lot.unit_cost_cents for lot in stock.lots(connection, graded)] == [None]


# A second tap on the phone, or the page sent again: one card came back, so one item.
def test_a_card_back_from_grading_cannot_come_back_again(connection):
    card = a_charizard(connection)
    (lot, *_) = stock.lots(connection, card)
    grading = gradings.send(connection, lot.id, TO_PSA)
    gradings.receive(connection, grading, BACK, grade=Decimal(9))

    with pytest.raises(AlreadyBack):
        gradings.receive(connection, grading, BACK, grade=Decimal(9))

    assert len(items.listing(connection)) == 2


def a_charizard(connection, shares: tuple[Share, ...] = ()) -> int:
    """Three copies of a card, bought for 104,00 € with the shipping: lots of 2 at 34,67 € and 1 at 34,66 €."""
    item_id = items.add(connection, CHARIZARD)
    purchases.record(connection, Purchase(10000, 400, date(2026, 10, 20), shares=shares), item_id, quantity=3)
    return item_id
