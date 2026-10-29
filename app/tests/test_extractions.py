"""The extractions: a card of the bulk taken out to be sold on its own, with its share of the cost of the bulk's
oldest lot, and its shares.

On a real PostgreSQL, through the module's functions.
"""

from datetime import date

import pytest

from cards_warehouse import openings, partners, purchases, stock
from cards_warehouse.items import Kind
from cards_warehouse.openings import Counterpart, Rest
from cards_warehouse.purchases import Purchase, Share
from cards_warehouse.stock import Cause, NotEnoughStock
from tests.test_openings import a_card, a_sealed, bulk_of


# 6,00 € for 9 cards of bulk: the card out takes a ninth, 0,67 € rounded, and the lot keeps 8 cards and the 5,33 € left.
def test_a_card_extracted_from_the_bulk_takes_its_share_of_the_cost_of_the_lot(connection):
    bulk_lot(connection, cards=9, cost_cents=600)
    card = a_card(connection, "Charizard ex")

    openings.extract(connection, bulk_of(connection), card)

    assert [(lot.available, lot.unit_cost_cents) for lot in stock.lots(connection, card)] == [(1, 67)]
    assert [(lot.available, lot.cost_cents) for lot in stock.lots(connection, bulk_of(connection))] == [(8, 533)]


# The oldest lot first: 2 cards of 6,00 €, half Luca's, give 3,00 € each and end. The third card comes from the next
# lot, 9 cards of 6,00 € all Manuel's, and carries its shares, not the first lot's.
def test_once_a_lot_of_the_bulk_ends_the_cards_come_from_the_next_with_its_shares(connection):
    luca = partners.add(connection, "Luca")
    half_luca = (Share(None, 50, 300), Share(luca, 50, 300))
    bulk_lot(connection, cards=2, cost_cents=600, shares=half_luca)
    bulk_lot(connection, cards=9, cost_cents=600)
    cards = [a_card(connection, name) for name in ("Charizard ex", "Pikachu", "Mew")]

    for card in cards:
        openings.extract(connection, bulk_of(connection), card)

    [[first], [second], [third]] = [stock.lots(connection, card) for card in cards]
    assert [(lot.available, lot.unit_cost_cents) for lot in (first, second, third)] == [(1, 300), (1, 300), (1, 67)]
    assert [purchases.shares_of_lot(connection, lot.id) for lot in (first, second, third)] == [
        {None: 50, luca: 50},
        {None: 50, luca: 50},
        {None: 100},
    ]
    assert [(lot.available, lot.cost_cents) for lot in stock.lots(connection, bulk_of(connection))] == [
        (0, 0),
        (8, 533),
    ]


# Lots of the bulk, as (cards, cost): a card at a cent, a half cent rounded up, thirds, the ninths above, a cent a
# card, fewer cents than cards (as from an opening that gave the bulk a cent), a half cent a card, the 1,76 € of 300
# cards of the PRD, and the largest a lot takes.
LOTS = ((1, 1), (2, 3), (3, 100), (9, 600), (10, 10), (18, 1), (50, 25), (300, 176), (7, 99_999_999))


# Not a cent lost, and none made up: every card of each lot taken out, one at a time, and at each the bulk and the
# cards cost together what the lot cost. A card costs a cent at least, as copies do; once the lot has no cents left,
# the cards after cost what it has, nothing, which no margin can be worked out on: their cost is not known.
def test_bulk_and_the_cards_taken_out_of_it_cost_together_what_the_lot_cost(connection):
    for cards, cost in LOTS:
        bulk_lot(connection, cards, cost)
        bulk = bulk_of(connection)
        # The lots before are all taken out: the cards come from the newest.
        left = stock.lots(connection, bulk)[-1]
        taken_out = 0
        for card in range(cards):
            had = left
            taken = a_card(connection, "Carta")

            openings.extract(connection, bulk, taken)

            case = (cards, cost, card)
            [card_lot] = stock.lots(connection, taken)
            left = stock.lots(connection, bulk)[-1]
            assert left.available == had.available - 1, case
            if had.cost_cents == 0:
                assert card_lot.unit_cost_cents is None, case
            else:
                assert card_lot.unit_cost_cents >= 1, case
            taken_out += card_lot.unit_cost_cents or 0
            assert left.cost_cents >= 0, case
            assert left.cost_cents + taken_out == cost, case
        assert (left.available, left.cost_cents) == (0, 0), (cards, cost)


# The bulk never goes below no cards: with every lot taken out, there is nothing to extract, and no card comes out of
# nothing.
def test_a_bulk_without_cards_has_none_to_extract(connection):
    bulk_lot(connection, cards=1, cost_cents=600)
    bulk_lot(connection, cards=1, cost_cents=100)
    openings.extract(connection, bulk_of(connection), a_card(connection, "Charizard ex"))
    openings.extract(connection, bulk_of(connection), a_card(connection, "Pikachu"))
    card = a_card(connection, "Mew")

    with pytest.raises(NotEnoughStock):
        openings.extract(connection, bulk_of(connection), card)

    assert stock.lots(connection, card) == []
    assert stock.available(connection, bulk_of(connection)) == 0


# Not free, which would make its margin infinite: a card out of a bulk whose cost is not known is not known either.
def test_a_card_out_of_a_bulk_whose_cost_is_not_known_costs_what_is_not_known(connection):
    bulk_lot(connection, cards=30, cost_cents=None)
    card = a_card(connection, "Charizard ex")

    openings.extract(connection, bulk_of(connection), card)

    assert [(lot.available, lot.unit_cost_cents) for lot in stock.lots(connection, card)] == [(1, None)]
    assert [(lot.available, lot.cost_cents) for lot in stock.lots(connection, bulk_of(connection))] == [(29, None)]


# The two sides of an extraction are linked, and each names the other: the bulk the card it went into, the card the
# bulk it came from.
def test_each_side_of_an_extraction_names_the_item_on_the_other(connection):
    bulk_lot(connection, cards=9, cost_cents=600)
    bulk = bulk_of(connection)
    card = a_card(connection, "Charizard ex")

    openings.extract(connection, bulk, card)

    of_bulk = openings.counterparts(connection, bulk)
    assert [(m.cause, m.change, of_bulk.get(m.id)) for m in stock.history(connection, bulk)][1:] == [
        (Cause.EXTRACTION, -1, [Counterpart(card, "Charizard ex", Kind.SINGLE_CARD, 1)]),
    ]
    of_card = openings.counterparts(connection, card)
    assert [(m.cause, m.change, of_card.get(m.id)) for m in stock.history(connection, card)] == [
        (Cause.EXTRACTION, 1, [Counterpart(bulk, "Bulk Pokémon Italiano", Kind.BULK, 1)]),
    ]


def bulk_lot(connection, cards: int, cost_cents: int | None, shares: tuple[Share, ...] = ()) -> None:
    """A lot of the bulk with its cards, its cost and its shares: a pack bought at that cost, opened all into the
    bulk."""
    pack_item = a_sealed(connection, "Busta")
    if cost_cents is None:
        stock.load(connection, pack_item, quantity=1, unit_cost_cents=None)
    else:
        purchase = Purchase(cost_cents, shipping_cents=0, purchased_on=date(2026, 10, 20), shares=shares)
        purchases.record(connection, purchase, pack_item, quantity=1)
    [pack] = stock.lots(connection, pack_item)
    openings.into_cards(connection, pack.id, 1, [], Rest(cards=cards, estimated_value_cents=100))
