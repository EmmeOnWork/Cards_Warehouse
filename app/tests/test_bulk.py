"""The capital idle in the bulk: of each bulk with cards, what they cost, and since when its oldest lot with cards
stands.

On a real PostgreSQL, through the module's functions. The lots come in transactions of their own, as from the pages,
so that each has its own time.
"""

from datetime import date

from cards_warehouse import bulk, items, manual_channels, openings, purchases, sales, stock
from cards_warehouse.bulk import Idle
from cards_warehouse.database import create_database_engine
from cards_warehouse.items import Item, Kind
from cards_warehouse.openings import Rest
from cards_warehouse.purchases import Purchase
from cards_warehouse.sales import Sale
from tests.test_bulk_sales import vinted
from tests.test_extractions import bulk_lot
from tests.test_openings import bulk_of


# 2 cards of 6,00 € and then 9 of 6,00 €; the 2 of the first lot sold. The 9 left stand, with their 6,00 €, since
# the second lot came: the first stands no longer.
def test_the_capital_idle_in_a_bulk_is_what_its_cards_left_cost_since_its_oldest_lot_with_cards(database):
    engine = create_database_engine()
    for cards in (2, 9):
        with engine.begin() as connection:
            bulk_lot(connection, cards=cards, cost_cents=600)
    with engine.begin() as connection:
        item = bulk_of(connection)
        sales.record(connection, Sale(item, vinted(connection), 2, 500), manual_channels.MANUAL)

    with engine.connect() as connection:
        idle = bulk.idle(connection)
        second_came = next(movement.at for movement in stock.history(connection, item) if movement.lot == 2)

    assert idle == [Idle(item, "Bulk Pokémon Italiano", 9, 600, second_came)]


# The Italian bulk was born first, but its first lot is sold and its second came after the Japanese one: the Japanese
# bulk stands the longest, and comes first.
def test_the_bulk_standing_the_longest_comes_first(database):
    engine = create_database_engine()
    with engine.begin() as connection:
        bulk_lot(connection, cards=2, cost_cents=600)
        italian = bulk_of(connection)
    with engine.begin() as connection:
        japanese = _japanese_bulk_lot(connection, cards=3, cost_cents=600)
    with engine.begin() as connection:
        sales.record(connection, Sale(italian, vinted(connection), 2, 500), manual_channels.MANUAL)
        bulk_lot(connection, cards=9, cost_cents=600)

    with engine.connect() as connection:
        assert [idle.item_id for idle in bulk.idle(connection)] == [japanese, italian]


# A lot out of a pack whose cost is not known, next to one of 6,00 €: the cards of the first may have cost anything, so
# the capital of the bulk is not known either, as on its page.
def test_a_bulk_with_a_lot_of_a_cost_not_known_has_a_capital_not_known(connection):
    bulk_lot(connection, cards=5, cost_cents=None)
    bulk_lot(connection, cards=9, cost_cents=600)

    [idle] = bulk.idle(connection)

    assert (idle.cards, idle.cost_cents) == (14, None)


def _japanese_bulk_lot(connection, cards: int, cost_cents: int) -> int:
    """A lot of the Japanese bulk, from a Japanese pack bought at that cost and opened all into the bulk: its bulk."""
    pack_item = items.add(connection, Item(kind=Kind.SEALED, game="Pokémon", name="Busta", language="ja"))
    purchase = Purchase(cost_cents, shipping_cents=0, purchased_on=date(2026, 10, 20))
    purchases.record(connection, purchase, pack_item, quantity=1)
    [pack] = stock.lots(connection, pack_item)
    openings.into_cards(connection, pack.id, 1, [], Rest(cards=cards, estimated_value_cents=100))
    [japanese] = items.listing(connection, items.items.c.kind == Kind.BULK, items.items.c.language == "ja")
    return japanese.id
