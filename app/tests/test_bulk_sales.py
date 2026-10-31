"""The sales of the bulk: cards counted roughly, taken from its oldest lots, each lot losing its cards and their part
of the cost of its cards.

On a real PostgreSQL, through the module's functions, with every channel a manual one.
"""

from cards_warehouse import manual_channels, openings, sales, stock
from cards_warehouse.sales import Sale
from tests.test_exposure import channel_ids
from tests.test_extractions import LOTS, bulk_lot
from tests.test_openings import a_card, bulk_of


# 3 of 9 cards of 6,00 € sold: they cost a third of it, 2,00 €, and the lot keeps 6 cards and 4,00 €.
def test_cards_of_the_bulk_sold_cost_their_part_of_the_cost_of_their_lot(connection):
    bulk_lot(connection, cards=9, cost_cents=600)

    sale = sales.record(connection, Sale(bulk_of(connection), vinted(connection), 3, 500), manual_channels.MANUAL)

    assert sales.one(connection, sale).cost_cents == 200
    assert [(lot.available, lot.cost_cents) for lot in stock.lots(connection, bulk_of(connection))] == [(6, 400)]


# 2 cards of 6,00 € and 9 of 6,00 €, all sold together: the sale costs 12,00 €, and both lots end at no cards and 0 €.
def test_all_the_bulk_sold_leaves_its_lots_with_no_cards_and_no_cost(connection):
    bulk_lot(connection, cards=2, cost_cents=600)
    bulk_lot(connection, cards=9, cost_cents=600)

    sale = sales.record(connection, Sale(bulk_of(connection), vinted(connection), 11, 2000), manual_channels.MANUAL)

    assert sales.one(connection, sale).cost_cents == 1200
    assert [(lot.available, lot.cost_cents) for lot in stock.lots(connection, bulk_of(connection))] == [(0, 0), (0, 0)]


# Not a cent lost, and none made up: each lot of the extractions' sold in sales of 1, 2, 3… cards, and at each the
# bulk and the sales cost together what the lot cost. A sale costs a cent at least while its lot has cents left; once
# they are gone, its cost is not known, and the lot ends at no cards and 0 €.
def test_the_bulk_and_its_sales_cost_together_what_its_lot_cost(connection):
    for cards, cost in LOTS:
        bulk_lot(connection, cards, cost)
        bulk = bulk_of(connection)
        sold_cost, size = 0, 1
        while (left := stock.lots(connection, bulk)[-1]).available:
            had = left
            size = min(size, left.available)

            sale = sales.record(connection, Sale(bulk, vinted(connection), size, 100), manual_channels.MANUAL)

            case = (cards, cost, size)
            left = stock.lots(connection, bulk)[-1]
            assert left.available == had.available - size, case
            sale_cost = sales.one(connection, sale).cost_cents
            if had.cost_cents:
                assert sale_cost >= 1, case
            else:
                assert sale_cost is None, case
            sold_cost += sale_cost or 0
            assert sold_cost + left.cost_cents == cost, case
            size += 1
        assert (left.available, left.cost_cents) == (0, 0), (cards, cost)


# 18 cards for a cent: the card extracted took it, and the 17 left cost nothing. Their sale has no margin to tell.
def test_cards_of_a_lot_that_has_no_cents_left_are_sold_at_a_cost_not_known(connection):
    bulk_lot(connection, cards=18, cost_cents=1)
    openings.extract(connection, bulk_of(connection), a_card(connection, "Charizard ex"))

    sale = sales.record(connection, Sale(bulk_of(connection), vinted(connection), 5, 500), manual_channels.MANUAL)

    recorded = sales.one(connection, sale)
    assert (recorded.cost_cents, recorded.margin) == (None, None)
    assert [lot.available for lot in stock.lots(connection, bulk_of(connection))] == [12]


def vinted(connection) -> int:
    [channel] = channel_ids(connection, "Vinted")
    return channel
