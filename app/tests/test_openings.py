"""The openings module: a copy of a lot opened into new lots, which take its cost and its shares whole.

On a real PostgreSQL, through the module's functions.
"""

from datetime import date

import pytest

from cards_warehouse import items, openings, partners, purchases, stock
from cards_warehouse.items import Item, Kind
from cards_warehouse.openings import Counterpart
from cards_warehouse.purchases import Purchase, Share
from cards_warehouse.stock import Cause, NotEnoughStock

# The packs of a box, from the smallest to the usual 36, and costs from a cent a pack to the largest a lot takes:
# exact, one cent over, a cent short of two each, and some real ones.
PACKS = (1, 2, 3, 6, 10, 18, 24, 36)


def box_costs(packs: int) -> tuple[int, ...]:
    return packs, packs + 1, 2 * packs - 1, 8990, 10400, 999_999_999


# Not a cent lost, and none made up: the packs of a box cost, all together, what the box cost.
def test_an_opening_takes_a_copy_of_the_box_and_its_packs_cost_together_what_it_cost(connection):
    for packs in PACKS:
        for box_cost in box_costs(packs):
            box_item = a_sealed(connection, "Booster box")
            box = stock.load(connection, box_item, quantity=2, unit_cost_cents=box_cost)
            packs_item = a_sealed(connection, "Busta")

            openings.into_packs(connection, box, packs_item, packs)

            lots = stock.lots(connection, packs_item)
            assert stock.available(connection, box_item) == 1, (box_cost, packs)
            assert sum(lot.available for lot in lots) == packs, (box_cost, packs)
            assert sum(lot.unit_cost_cents * lot.available for lot in lots) == box_cost, (box_cost, packs)


# The packs are the box's, in the same shares: a sale of a pack will split its net as a sale of the box would.
# A box of 34,67 € makes two lots of packs, and both carry them.
@pytest.mark.parametrize(
    "shares",
    [
        {"Manuel": 100},
        {"Manuel": 50, "Luca": 50},
        {"Manuel": 34, "Luca": 33, "Giulia": 33},
        {"Luca": 100},
    ],
)
def test_the_packs_of_a_box_carry_the_shares_of_the_box(connection, shares):
    people = {name: None if name == "Manuel" else partners.add(connection, name) for name in shares}
    # Each one paid their share of the 104,00 €.
    shared = Purchase(
        total_cost_cents=10400,
        shipping_cents=0,
        purchased_on=date(2026, 10, 20),
        shares=tuple(Share(people[name], percent, 104 * percent) for name, percent in shares.items()),
    )
    box_item = a_sealed(connection, "Booster box")
    purchases.record(connection, shared, box_item, quantity=3)
    box = stock.lots(connection, box_item)[0].id
    packs_item = a_sealed(connection, "Busta")

    openings.into_packs(connection, box, packs_item, 36)

    lots = stock.lots(connection, packs_item)
    assert len(lots) == 2
    assert [purchases.shares_of_lot(connection, lot.id) for lot in lots] == [
        {people[name]: percent for name, percent in shares.items()}
    ] * 2


# Not free, which would make their margin infinite: the packs of a box whose cost is not known are not known either.
def test_a_box_whose_cost_is_not_known_makes_packs_whose_cost_is_not_known(connection):
    box = stock.load(connection, a_sealed(connection, "Booster box"), quantity=1, unit_cost_cents=None)
    packs_item = a_sealed(connection, "Busta")

    openings.into_packs(connection, box, packs_item, 36)

    assert [(lot.available, lot.unit_cost_cents) for lot in stock.lots(connection, packs_item)] == [(36, None)]


# The two sides of an opening are linked, and each names the other: the box the packs it went into, and how many,
# and each lot of packs the box it came out of.
def test_each_side_of_an_opening_names_the_item_on_the_other(connection):
    box_item = a_sealed(connection, "Booster box")
    box = stock.load(connection, box_item, quantity=2, unit_cost_cents=8990)
    packs_item = a_sealed(connection, "Busta")

    openings.into_packs(connection, box, packs_item, 36)

    of_box = openings.counterparts(connection, box_item)
    assert [(m.cause, m.change, of_box.get(m.id)) for m in stock.history(connection, box_item)] == [
        (Cause.LOAD, 2, None),
        (Cause.OPENING, -1, Counterpart(packs_item, "Busta", 36)),
    ]
    of_packs = openings.counterparts(connection, packs_item)
    assert [(m.cause, m.change, of_packs.get(m.id)) for m in stock.history(connection, packs_item)] == [
        (Cause.OPENING, 26, Counterpart(box_item, "Booster box", 1)),
        (Cause.OPENING, 10, Counterpart(box_item, "Booster box", 1)),
    ]


# The last box already opened: there is nothing left to open, and no packs come out of nothing.
def test_a_box_lot_without_copies_cannot_be_opened_and_makes_no_packs(connection):
    box = stock.load(connection, a_sealed(connection, "Booster box"), quantity=1, unit_cost_cents=8990)
    packs_item = a_sealed(connection, "Busta")
    openings.into_packs(connection, box, packs_item, 36)

    with pytest.raises(NotEnoughStock):
        openings.into_packs(connection, box, packs_item, 36)

    assert stock.available(connection, packs_item) == 36


# 0,20 € cannot give a cent to each of 36 packs, and a box opened into no packs would just vanish: refused before
# anything changes, and the box stays closed.
@pytest.mark.parametrize(("box_cost", "packs"), [(20, 36), (8990, 0), (None, 0)])
def test_an_opening_that_cannot_be_split_is_refused_and_the_box_stays_closed(connection, box_cost, packs):
    box_item = a_sealed(connection, "Booster box")
    box = stock.load(connection, box_item, quantity=1, unit_cost_cents=box_cost)
    packs_item = a_sealed(connection, "Busta")

    with pytest.raises(ValueError):
        openings.into_packs(connection, box, packs_item, packs)

    assert stock.available(connection, box_item) == 1
    assert stock.lots(connection, packs_item) == []


def a_sealed(connection, name: str) -> int:
    return items.add(connection, Item(kind=Kind.SEALED, game="Pokémon", name=name, language="it"))
