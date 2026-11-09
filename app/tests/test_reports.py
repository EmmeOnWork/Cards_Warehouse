"""The reports module: the margin of a period, as much as its sales really made, and the capital idle in the
warehouse.

On a real PostgreSQL, through the module's functions, with every channel a manual one.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from cards_warehouse import manual_channels, reports, sales, stock
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.items import Kind
from cards_warehouse.pricing import Margin
from cards_warehouse.reports import Capital
from cards_warehouse.sales import Cancellation, Sale
from tests.test_exposure import a_sealed, channel_ids
from tests.test_extractions import bulk_lot
from tests.test_sales import a_card


# A card of 100,00 sold with 10% (10,00) and one of 1,00 with 100% (1,00): 11,00 on 101,00, 10,89%, rounded down as the
# margin of a sale. The mean of the two percentages would be 55%, which is not what came in.
def test_the_margin_of_a_period_is_the_margin_of_its_sales_on_the_cost_of_the_copies_sold(connection):
    sell(connection, a_card(connection, copies=1, unit_cost_cents=10000), price_cents=11000)
    sell(connection, a_card(connection, copies=1, unit_cost_cents=100), price_cents=200)
    today = datetime.now(LOCAL_TIME).date()

    period = reports.margin(connection, today, today)

    assert period == reports.PeriodMargin(today, today, sales=2, cost_unknown=0, margin=Margin(1100, Decimal("10.89")))


# The card of 1,00 came back: only the one of 100,00 is left in the margin, with its 10%.
def test_a_sale_cancelled_is_left_out_of_the_margin(connection):
    sell(connection, a_card(connection, copies=1, unit_cost_cents=10000), price_cents=11000)
    returned = sell(connection, a_card(connection, copies=1, unit_cost_cents=100), price_cents=200)
    sales.cancel(connection, returned, Cancellation.RETURN)
    today = datetime.now(LOCAL_TIME).date()

    period = reports.margin(connection, today, today)

    assert period == reports.PeriodMargin(today, today, sales=1, cost_unknown=0, margin=Margin(1000, Decimal("10")))


# A card of a cost not known, sold at 50,00, may have made anything: the margin is the 10% of the other alone, and
# the sale left out is told apart.
def test_a_sale_of_a_cost_not_known_is_left_out_of_the_margin_and_counted_apart(connection):
    sell(connection, a_card(connection, copies=1, unit_cost_cents=10000), price_cents=11000)
    sell(connection, a_card(connection, copies=1, unit_cost_cents=None), price_cents=5000)
    today = datetime.now(LOCAL_TIME).date()

    period = reports.margin(connection, today, today)

    assert period == reports.PeriodMargin(today, today, sales=1, cost_unknown=1, margin=Margin(1000, Decimal("10")))


# A sale this month, seen two months on: the month then and the one before have no sale, but show all the same, down
# to the month of the first sale.
def test_the_months_go_from_the_one_of_today_back_to_the_one_of_the_first_sale(connection):
    sell(connection, a_card(connection, copies=1, unit_cost_cents=10000), price_cents=11000)
    this_month = datetime.now(LOCAL_TIME).date().replace(day=1)
    next_month = (this_month + timedelta(days=31)).replace(day=1)
    two_months_on = this_month + timedelta(days=62)

    months = reports.monthly_margins(connection, two_months_on)

    assert [(month.first_day, month.sales) for month in months] == [
        (two_months_on.replace(day=1), 0),
        (next_month, 0),
        (this_month, 1),
    ]


# Of two copies of Mew ex at 30,00, one sold: the other is left, and a copy of a second lot of a cost not known, told
# apart. Three booster boxes of 100,00. A pack of 6,00 opened all into 9 cards of bulk: the cards hold its cost, the
# pack is gone.
def test_the_capital_idle_is_what_the_copies_available_cost_of_each_kind_and_all_together(connection):
    mew = a_card(connection, copies=2, unit_cost_cents=3000)
    sell(connection, mew, price_cents=4000)
    stock.load(connection, mew, quantity=1, unit_cost_cents=None)
    a_sealed(connection, copies=3)
    bulk_lot(connection, cards=9, cost_cents=600)

    idle = reports.capital(connection)

    assert idle == reports.IdleCapital(
        by_kind={
            Kind.SINGLE_CARD: Capital(copies=1, cost_cents=3000, cost_unknown=1),
            Kind.SEALED: Capital(copies=3, cost_cents=30000, cost_unknown=0),
            Kind.BULK: Capital(copies=9, cost_cents=600, cost_unknown=0),
        },
        total=Capital(copies=13, cost_cents=33600, cost_unknown=1),
    )


def sell(connection, item_id: int, price_cents: int) -> int:
    """One copy of the item sold on eBay, which keeps nothing, with no shipping on Manuel."""
    [ebay] = channel_ids(connection, "eBay")
    return sales.record(connection, Sale(item_id, ebay, 1, price_cents), manual_channels.MANUAL)
