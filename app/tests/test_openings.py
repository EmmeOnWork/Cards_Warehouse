"""The openings module: a copy of a lot opened into new lots, which take its cost and its shares whole.

On a real PostgreSQL, through the module's functions.
"""

from datetime import date

import pytest

from cards_warehouse import items, openings, partners, purchases, stock
from cards_warehouse.items import Card, Condition, Item, Kind
from cards_warehouse.openings import Counterpart, Pulled, Rest
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
        (Cause.OPENING, -1, [Counterpart(packs_item, "Busta", Kind.SEALED, 36)]),
    ]
    of_packs = openings.counterparts(connection, packs_item)
    assert [(m.cause, m.change, of_packs.get(m.id)) for m in stock.history(connection, packs_item)] == [
        (Cause.OPENING, 26, [Counterpart(box_item, "Booster box", Kind.SEALED, 1)]),
        (Cause.OPENING, 10, [Counterpart(box_item, "Booster box", Kind.SEALED, 1)]),
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


# A pack of 6,00 € opened into a card estimated 50 € and 10 cards of bulk estimated 10 €: 5,00 € and 1,00 €. The bulk
# of the pack's game and language is born with them, with its cards counted roughly and its cost whole.
def test_a_pack_opened_into_a_card_and_the_bulk_splits_its_cost_by_their_estimated_values(connection):
    pack_item = a_sealed(connection, "Busta")
    pack = stock.load(connection, pack_item, quantity=3, unit_cost_cents=600)
    card = a_card(connection, "Charizard ex")

    openings.into_cards(connection, pack, 1, [Pulled(card, 1, 5000)], Rest(cards=10, estimated_value_cents=1000))

    assert stock.available(connection, pack_item) == 2
    assert [(lot.available, lot.cost_cents) for lot in stock.lots(connection, card)] == [(1, 500)]
    [bulk] = items.listing(connection, items.items.c.kind == Kind.BULK)
    assert (bulk.name, bulk.game) == ("Bulk Pokémon Italiano", "Pokémon")
    assert [(lot.available, lot.cost_cents) for lot in stock.lots(connection, bulk.id)] == [(10, 100)]


# What came out of an opening, as (copies, estimated value of one) for each card, and the estimated value of the
# bulk: a card of 200 € beside ones of a cent, a bulk worth far more than the card or a cent, copies of one card,
# everything at a cent, and nothing worth a listing.
CARDS_AND_BULK = (
    ([(1, 20000)], 1),
    ([(1, 1)], 20000),
    ([(1, 20000), (1, 1), (1, 1)], 500),
    ([(3, 1500), (1, 7)], 333),
    ([(10, 1)], 1),
    ([], 100),
)


def unit_costs(parts: int, copies: int) -> tuple[int, ...]:
    """From the least that gives a cent to each part, and one more, to some real ones and the largest a lot takes."""
    least = -(-parts // copies)
    return least, least + 1, 600, 8990, 99_999_999


# Not a cent lost, and none made up: the cards and the new lot of bulk cost, all together, what was opened.
def test_cards_and_bulk_out_of_an_opening_cost_together_what_was_opened(connection):
    for pulled, bulk_value in CARDS_AND_BULK:
        parts = sum(copies for copies, _ in pulled) + 1
        for copies in (1, 3, 10):
            for unit_cost in unit_costs(parts, copies):
                case = (pulled, bulk_value, copies, unit_cost)
                pack = stock.load(connection, a_sealed(connection, "Busta"), quantity=10, unit_cost_cents=unit_cost)
                cards = [Pulled(a_card(connection, "Carta"), n, value) for n, value in pulled]

                openings.into_cards(connection, pack, copies, cards, Rest(cards=50, estimated_value_cents=bulk_value))

                card_lots = [lot for card in cards for lot in stock.lots(connection, card.item_id)]
                assert sum(lot.available for lot in card_lots) == parts - 1, case
                bulk_lot = stock.lots(connection, bulk_of(connection))[-1]
                assert (bulk_lot.available, bulk_lot.cost_cents >= 1) == (50, True), case
                assert sum(lot.cost_cents for lot in card_lots) + bulk_lot.cost_cents == copies * unit_cost, case


# The cards and the new lot of bulk are the packs', in the same shares: a sale of any of them will split its net as a
# sale of a pack would. Cards of 200 € and of 5 €, with copies that take a cent more, so that a card has two lots.
@pytest.mark.parametrize(
    "shares",
    [
        {"Manuel": 100},
        {"Manuel": 50, "Luca": 50},
        {"Manuel": 34, "Luca": 33, "Giulia": 33},
        {"Luca": 100},
    ],
)
def test_the_cards_and_the_bulk_of_an_opening_carry_the_shares_of_what_was_opened(connection, shares):
    people = {name: None if name == "Manuel" else partners.add(connection, name) for name in shares}
    shared = Purchase(
        total_cost_cents=6000,
        shipping_cents=0,
        purchased_on=date(2026, 10, 20),
        shares=tuple(Share(people[name], percent, 60 * percent) for name, percent in shares.items()),
    )
    packs_item = a_sealed(connection, "Busta")
    purchases.record(connection, shared, packs_item, quantity=10)
    packs = stock.lots(connection, packs_item)[0].id
    cards = [Pulled(a_card(connection, "Charizard ex"), 1, 20000), Pulled(a_card(connection, "Pikachu"), 3, 500)]

    openings.into_cards(connection, packs, 3, cards, Rest(cards=100, estimated_value_cents=250))

    lots = [lot for card in cards for lot in stock.lots(connection, card.item_id)]
    lots += stock.lots(connection, bulk_of(connection))
    assert len(lots) == 4
    assert [purchases.shares_of_lot(connection, lot.id) for lot in lots] == [
        {people[name]: percent for name, percent in shares.items()}
    ] * 4


# The bulk of a game and a language is born at its first opening, and each opening after adds a lot to it. Japanese
# cards and One Piece cards go to bulks of their own.
def test_each_game_and_language_has_one_bulk_which_takes_a_lot_from_each_opening(connection):
    def opened(game: str, language: str, rest: int) -> None:
        packs_item = items.add(connection, Item(kind=Kind.SEALED, game=game, name="Busta", language=language))
        packs = stock.load(connection, packs_item, quantity=1, unit_cost_cents=600)
        openings.into_cards(connection, packs, 1, [], Rest(cards=rest, estimated_value_cents=100))

    opened("Pokémon", "it", 10)
    opened("Pokémon", "it", 20)
    opened("Pokémon", "ja", 30)
    opened("One Piece", "it", 40)

    bulks = items.listing(connection, items.items.c.kind == Kind.BULK)
    assert sorted((bulk.name, [lot.available for lot in stock.lots(connection, bulk.id)]) for bulk in bulks) == [
        ("Bulk One Piece Italiano", [40]),
        ("Bulk Pokémon Giapponese", [30]),
        ("Bulk Pokémon Italiano", [10, 20]),
    ]


# Not free, which would make their margin infinite: what comes out of packs whose cost is not known is not known.
def test_packs_whose_cost_is_not_known_make_cards_and_bulk_whose_cost_is_not_known(connection):
    packs = stock.load(connection, a_sealed(connection, "Busta"), quantity=3, unit_cost_cents=None)
    card = a_card(connection, "Charizard ex")

    openings.into_cards(connection, packs, 2, [Pulled(card, 2, 5000)], Rest(cards=30, estimated_value_cents=300))

    assert [(lot.available, lot.cost_cents) for lot in stock.lots(connection, card)] == [(2, None)]
    assert [(lot.available, lot.cost_cents) for lot in stock.lots(connection, bulk_of(connection))] == [(30, None)]


# A value of nothing gives nothing to split by, even when the cost is not known; 0,03 € cannot give a cent to three
# copies of a card and the bulk; no packs, or a bulk of no cards, would make something out of nothing. Refused before
# anything changes: the packs stay closed, and no bulk is born.
@pytest.mark.parametrize(
    ("unit_cost", "copies", "card_value", "rest"),
    [
        (600, 1, 0, Rest(cards=50, estimated_value_cents=100)),
        (600, 1, 5000, Rest(cards=50, estimated_value_cents=0)),
        (None, 1, 0, Rest(cards=50, estimated_value_cents=100)),
        (None, 1, 5000, Rest(cards=50, estimated_value_cents=0)),
        (3, 1, 5000, Rest(cards=50, estimated_value_cents=100)),
        (600, 0, 5000, Rest(cards=50, estimated_value_cents=100)),
        (600, 1, 5000, Rest(cards=0, estimated_value_cents=100)),
    ],
)
def test_an_opening_that_cannot_be_split_is_refused_and_the_packs_stay_closed(
    connection, unit_cost, copies, card_value, rest
):
    packs_item = a_sealed(connection, "Busta")
    packs = stock.load(connection, packs_item, quantity=3, unit_cost_cents=unit_cost)
    card = a_card(connection, "Charizard ex")

    with pytest.raises(ValueError):
        openings.into_cards(connection, packs, copies, [Pulled(card, 3, card_value)], rest)

    assert stock.available(connection, packs_item) == 3
    assert stock.lots(connection, card) == []
    assert items.listing(connection, items.items.c.kind == Kind.BULK) == []


# The lots of the bulk have no unit cost, yet theirs is known: the list does not call it a cost not known. Out of
# packs whose cost is not known, it is.
@pytest.mark.parametrize(("unit_cost", "cost_unknown"), [(600, False), (None, True)])
def test_the_bulk_has_a_cost_not_known_only_when_what_was_opened_had(connection, unit_cost, cost_unknown):
    packs = stock.load(connection, a_sealed(connection, "Busta"), quantity=1, unit_cost_cents=unit_cost)

    openings.into_cards(connection, packs, 1, [], Rest(cards=50, estimated_value_cents=100))

    [bulk] = items.listing(connection, items.items.c.kind == Kind.BULK)
    assert bulk.cost_unknown == cost_unknown


# The packs opened name every item that came out of them, in the order they came, with its copies: the cards, a card
# in two lots once, and the bulk. Each of those names the packs, and how many were opened.
def test_packs_opened_into_cards_name_every_item_that_came_out_of_them(connection):
    packs_item = a_sealed(connection, "Busta")
    packs = stock.load(connection, packs_item, quantity=10, unit_cost_cents=600)
    charizard, pikachu = a_card(connection, "Charizard ex"), a_card(connection, "Pikachu")
    cards = [Pulled(charizard, 1, 5000), Pulled(pikachu, 3, 500)]

    openings.into_cards(connection, packs, 2, cards, Rest(cards=18, estimated_value_cents=500))

    bulk = bulk_of(connection)
    of_packs = openings.counterparts(connection, packs_item)
    assert [(m.change, of_packs.get(m.id)) for m in stock.history(connection, packs_item)] == [
        (10, None),
        (
            -2,
            [
                Counterpart(charizard, "Charizard ex", Kind.SINGLE_CARD, 1),
                Counterpart(pikachu, "Pikachu", Kind.SINGLE_CARD, 3),
                Counterpart(bulk, "Bulk Pokémon Italiano", Kind.BULK, 18),
            ],
        ),
    ]
    came_from = [Counterpart(packs_item, "Busta", Kind.SEALED, 2)]
    for item_id in (charizard, pikachu, bulk):
        of_item = openings.counterparts(connection, item_id)
        assert [of_item.get(m.id) for m in stock.history(connection, item_id)] == [came_from] * len(
            stock.lots(connection, item_id)
        )


# Mixed openings, as (packs in the box, its cost, packs left closed), whose opened packs fit in the first lot of packs,
# where the two steps open them from: the first lot at a cent over, all of it, a box split evenly, a pack the only
# one opened or the only one in the box, and a cost not known.
SAME_AS_TWO_STEPS = (
    (36, 8990, 26),
    (36, 8990, 10),
    (36, 8964, 0),
    (3, 10400, 1),
    (24, 6000, 23),
    (1, 600, 0),
    (18, None, 9),
)


# One step or two, the same: a mixed opening makes the packs, the cards and the bulk that the box opened into packs,
# and then the opened packs into cards, would make, at the same costs.
@pytest.mark.parametrize(("packs", "box_cost", "closed"), SAME_AS_TWO_STEPS)
def test_a_mixed_opening_makes_what_the_box_into_packs_and_then_the_packs_into_cards_would(
    connection, packs, box_cost, closed
):
    def made(mixed: bool):
        box = stock.load(connection, a_sealed(connection, "Booster box"), quantity=1, unit_cost_cents=box_cost)
        packs_item = a_sealed(connection, "Busta")
        cards = [Pulled(a_card(connection, "Charizard ex"), 1, 4000), Pulled(a_card(connection, "Pikachu"), 2, 500)]
        rest = Rest(cards=18, estimated_value_cents=500)
        if mixed:
            openings.into_packs_and_cards(connection, box, packs_item, packs, closed, cards, rest)
        else:
            openings.into_packs(connection, box, packs_item, packs)
            openings.into_cards(connection, stock.lots(connection, packs_item)[0].id, packs - closed, cards, rest)
        lots = [
            [(lot.available, lot.cost_cents) for lot in stock.lots(connection, item_id) if lot.available]
            for item_id in (packs_item, *(card.item_id for card in cards))
        ]
        bulk_lot = stock.lots(connection, bulk_of(connection))[-1]
        return lots, (bulk_lot.available, bulk_lot.cost_cents)

    assert made(mixed=True) == made(mixed=False)


def least_box_cost(packs: int, opened: int, parts: int) -> int:
    """The least a box costs that gives a cent to each pack, and to each part of what comes out of the opened ones:
    these take the first equal parts, a cent over the others."""
    box_cost = packs
    while opened * (box_cost // packs) + min(opened, box_cost % packs) < parts:
        box_cost += 1
    return box_cost


# Not a cent lost, and none made up: the packs left closed, the cards and the new lot of bulk cost, all together, what
# the box cost. Also when the packs opened take parts with a cent over and parts without, as 35 of 36 packs out of
# 89,90 €, which the two steps could not open together.
def test_packs_left_closed_cards_and_bulk_out_of_a_mixed_opening_cost_together_what_the_box_cost(connection):
    for pulled, bulk_value in (([(1, 20000), (1, 1), (1, 1)], 500), ([], 100)):
        parts = sum(copies for copies, _ in pulled) + 1
        for packs in PACKS:
            for closed in sorted({0, 1, packs // 2, packs - 1} - {packs}):
                least = least_box_cost(packs, packs - closed, parts)
                for box_cost in (least, least + 1, 8990, 10400, 999_999_999):
                    case = (pulled, packs, closed, box_cost)
                    box_item = a_sealed(connection, "Booster box")
                    box = stock.load(connection, box_item, quantity=1, unit_cost_cents=box_cost)
                    packs_item = a_sealed(connection, "Busta")
                    cards = [Pulled(a_card(connection, "Carta"), n, value) for n, value in pulled]
                    rest = Rest(cards=50, estimated_value_cents=bulk_value)

                    openings.into_packs_and_cards(connection, box, packs_item, packs, closed, cards, rest)

                    pack_lots = stock.lots(connection, packs_item)
                    card_lots = [lot for card in cards for lot in stock.lots(connection, card.item_id)]
                    bulk_lot = stock.lots(connection, bulk_of(connection))[-1]
                    assert sum(lot.available for lot in pack_lots) == closed, case
                    assert sum(lot.available for lot in card_lots) == parts - 1, case
                    assert bulk_lot.available == 50, case
                    made = pack_lots + card_lots + [bulk_lot]
                    assert sum(lot.cost_cents for lot in made) == box_cost, case


# The packs left closed, the cards and the new lot of bulk are the box's, in the same shares: a sale of any of them
# will split its net as a sale of the box would. 104,00 € in 36 packs makes two lots of the closed ones, and a card
# has two lots.
@pytest.mark.parametrize(
    "shares",
    [
        {"Manuel": 100},
        {"Manuel": 50, "Luca": 50},
        {"Manuel": 34, "Luca": 33, "Giulia": 33},
        {"Luca": 100},
    ],
)
def test_all_that_comes_out_of_a_mixed_opening_carries_the_shares_of_the_box(connection, shares):
    people = {name: None if name == "Manuel" else partners.add(connection, name) for name in shares}
    shared = Purchase(
        total_cost_cents=10400,
        shipping_cents=0,
        purchased_on=date(2026, 10, 20),
        shares=tuple(Share(people[name], percent, 104 * percent) for name, percent in shares.items()),
    )
    box_item = a_sealed(connection, "Booster box")
    purchases.record(connection, shared, box_item, quantity=1)
    box = stock.lots(connection, box_item)[0].id
    packs_item = a_sealed(connection, "Busta")
    cards = [Pulled(a_card(connection, "Charizard ex"), 1, 20000), Pulled(a_card(connection, "Pikachu"), 3, 500)]
    rest = Rest(cards=100, estimated_value_cents=250)

    openings.into_packs_and_cards(connection, box, packs_item, 36, 26, cards, rest)

    lots = stock.lots(connection, packs_item)
    lots += [lot for card in cards for lot in stock.lots(connection, card.item_id)]
    lots += stock.lots(connection, bulk_of(connection))
    assert len(lots) == 6
    assert [purchases.shares_of_lot(connection, lot.id) for lot in lots] == [
        {people[name]: percent for name, percent in shares.items()}
    ] * 6


# Not free, which would make their margin infinite: a box whose cost is not known, opened mixed, makes packs, cards
# and bulk whose cost is not known.
def test_a_box_whose_cost_is_not_known_opened_mixed_makes_all_whose_cost_is_not_known(connection):
    box = stock.load(connection, a_sealed(connection, "Booster box"), quantity=1, unit_cost_cents=None)
    packs_item = a_sealed(connection, "Busta")
    card = a_card(connection, "Charizard ex")

    openings.into_packs_and_cards(
        connection, box, packs_item, 36, 26, [Pulled(card, 2, 5000)], Rest(cards=30, estimated_value_cents=300)
    )

    made = (packs_item, card, bulk_of(connection))
    assert [[(lot.available, lot.cost_cents) for lot in stock.lots(connection, item_id)] for item_id in made] == [
        [(26, None)],
        [(2, None)],
        [(30, None)],
    ]


# All packs left closed is an opening into packs, and cards would come out of nothing, even when the cost is not
# known; more packs closed than the box has, or fewer than none, or a box of no packs, make no sense. 0,20 € cannot
# give a cent to each of 36 packs, nor 0,01 € of the one pack opened to the card and the bulk. A value of nothing gives
# nothing to split by, and a bulk of no cards would be made out of nothing. Refused before anything changes: the box
# stays closed, and no packs, cards or bulk come out.
@pytest.mark.parametrize(
    ("box_cost", "packs", "closed", "card_value", "rest"),
    [
        (8990, 36, 36, 5000, Rest(cards=50, estimated_value_cents=100)),
        (None, 36, 36, 5000, Rest(cards=50, estimated_value_cents=100)),
        (8990, 36, 37, 5000, Rest(cards=50, estimated_value_cents=100)),
        (8990, 36, -1, 5000, Rest(cards=50, estimated_value_cents=100)),
        (8990, 0, 0, 5000, Rest(cards=50, estimated_value_cents=100)),
        (20, 36, 26, 5000, Rest(cards=50, estimated_value_cents=100)),
        (36, 36, 35, 5000, Rest(cards=50, estimated_value_cents=100)),
        (8990, 36, 26, 0, Rest(cards=50, estimated_value_cents=100)),
        (None, 36, 26, 5000, Rest(cards=50, estimated_value_cents=0)),
        (8990, 36, 26, 5000, Rest(cards=0, estimated_value_cents=100)),
    ],
)
def test_a_mixed_opening_that_cannot_be_split_is_refused_and_the_box_stays_closed(
    connection, box_cost, packs, closed, card_value, rest
):
    box_item = a_sealed(connection, "Booster box")
    box = stock.load(connection, box_item, quantity=1, unit_cost_cents=box_cost)
    packs_item = a_sealed(connection, "Busta")
    card = a_card(connection, "Charizard ex")

    with pytest.raises(ValueError):
        openings.into_packs_and_cards(connection, box, packs_item, packs, closed, [Pulled(card, 1, card_value)], rest)

    assert stock.available(connection, box_item) == 1
    assert stock.lots(connection, packs_item) == []
    assert stock.lots(connection, card) == []
    assert items.listing(connection, items.items.c.kind == Kind.BULK) == []


def bulk_of(connection) -> int:
    """The one bulk of the tests, Pokémon in Italian."""
    [bulk] = items.listing(connection, items.items.c.kind == Kind.BULK)
    return bulk.id


def a_sealed(connection, name: str) -> int:
    return items.add(connection, Item(kind=Kind.SEALED, game="Pokémon", name=name, language="it"))


def a_card(connection, name: str) -> int:
    card = Card(Condition.NEAR_MINT)
    return items.add(connection, Item(kind=Kind.SINGLE_CARD, game="Pokémon", name=name, language="it", details=card))
