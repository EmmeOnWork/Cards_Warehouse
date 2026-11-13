"""The reports module: the margin of a period, as much as its sales really made, and the capital idle in the
warehouse.

On a real PostgreSQL, through the module's functions, with every channel a manual one.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from cards_warehouse import manual_channels, reports, sales, stock
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.balances import SaleParts
from cards_warehouse.items import Kind
from cards_warehouse.pricing import Margin
from cards_warehouse.reports import Capital, HistorySale
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


# Mew ex, its only copy sold at 110,00, sold a second time: the double sale took no copy, so it has no cost, and is no
# sale of a cost not known. The margin is the one of the first sale alone.
def test_a_double_sale_is_left_out_of_the_margin(connection):
    mew = a_card(connection, copies=1, unit_cost_cents=10000)
    sell(connection, mew, price_cents=11000)
    sell(connection, mew, price_cents=11000)
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


# A Mew ex of 100,00 sold yesterday, one sold today at 110,00: a period of today alone has the one of today, all
# Manuel's, with its 10%.
def test_the_sales_of_a_period_are_those_from_its_first_day_to_its_last_with_their_margin_and_parts(connection):
    now = datetime.now(LOCAL_TIME)
    sell(connection, a_card(connection, copies=1, unit_cost_cents=10000), price_cents=12000, at=now - timedelta(days=1))
    sell(connection, a_card(connection, copies=1, unit_cost_cents=10000), price_cents=11000, at=now)

    sold = reports.sold(connection, now.date(), now.date())

    assert sold == [
        reports.Sold(
            at=now,
            item="Mew ex",
            channel="eBay",
            quantity=1,
            price_cents=11000,
            fee_cents=0,
            shipping_cents=0,
            cost_cents=10000,
            margin=Margin(1000, Decimal("10")),
            parts=SaleParts(collected_by="Manuel", parts=[("Manuel", 11000)]),
        )
    ]


# Of three copies of Mew ex sold today, one came back, and one was a double sale, its copy sold already on the other
# channel: neither is in the period.
def test_the_sales_of_a_period_leave_out_those_cancelled_and_the_double_sales(connection):
    returned = sell(connection, a_card(connection, copies=1, unit_cost_cents=10000), price_cents=11000)
    sales.cancel(connection, returned, Cancellation.RETURN)
    mew = a_card(connection, copies=1, unit_cost_cents=10000)
    sell(connection, mew, price_cents=12000)
    sell(connection, mew, price_cents=13000)
    today = datetime.now(LOCAL_TIME).date()

    sold = reports.sold(connection, today, today)

    assert [sale.price_cents for sale in sold] == [12000]


# Copies of a card of 10,00 sold in the last minute of September, the first of October, the last of October and the
# first of November, in time of Italy: October has the two between, the newest first, each with the margin it left.
def test_the_history_of_a_period_lists_its_sales_from_its_first_day_to_its_last_the_newest_first(connection):
    card = a_card(connection, copies=4, unit_cost_cents=1000)
    sell(connection, card, price_cents=1500, at=italy(2026, 9, 30, 23, 59))
    first = sell(connection, card, price_cents=1500, at=italy(2026, 10, 1, 0, 0))
    last = sell(connection, card, price_cents=1200, at=italy(2026, 10, 31, 23, 59))
    sell(connection, card, price_cents=1500, at=italy(2026, 11, 1, 0, 0))

    history = reports.history(connection, date(2026, 10, 1), date(2026, 10, 31))

    assert history.sales == [
        HistorySale(last, italy(2026, 10, 31, 23, 59), "Mew ex", "eBay", 1, 1200, 0, 0, Margin(200, Decimal("20"))),
        HistorySale(first, italy(2026, 10, 1, 0, 0), "Mew ex", "eBay", 1, 1500, 0, 0, Margin(500, Decimal("50"))),
    ]


# A card of 10,00 sold on Tilt at 30,00, which keeps 1,10, with 4,00 of shipping on Manuel: 14,90 left. One of 20,00
# sold on eBay, which keeps nothing, at 25,00: 5,00 left. The day took in 55,00, paid 1,10 of fees and made 19,90.
def test_the_history_totals_what_its_sales_took_in_what_they_paid_in_fees_and_the_margin_they_left(connection):
    tilt, ebay = channel_ids(connection, "Tilt", "eBay")
    sales.record(
        connection, Sale(a_card(connection, 1, 1000), tilt, 1, 3000, shipping_cents=400), manual_channels.MANUAL
    )
    sales.record(connection, Sale(a_card(connection, 1, 2000), ebay, 1, 2500), manual_channels.MANUAL)
    today = datetime.now(LOCAL_TIME).date()

    history = reports.history(connection, today, today)

    assert (history.price_cents, history.fee_cents, history.margin_cents) == (5500, 110, 1990)


# The same two sales, of Tilt alone: its own, with its own totals.
def test_the_history_of_a_channel_lists_and_totals_its_sales_alone(connection):
    tilt, ebay = channel_ids(connection, "Tilt", "eBay")
    on_tilt = sales.record(
        connection, Sale(a_card(connection, 1, 1000), tilt, 1, 3000, shipping_cents=400), manual_channels.MANUAL
    )
    sales.record(connection, Sale(a_card(connection, 1, 2000), ebay, 1, 2500), manual_channels.MANUAL)
    today = datetime.now(LOCAL_TIME).date()

    history = reports.history(connection, today, today, channel_id=tilt)

    assert [sale.sale_id for sale in history.sales] == [on_tilt]
    assert (history.price_cents, history.fee_cents, history.margin_cents) == (3000, 110, 1490)


# Copies of a card of 10,00 sold today at 15,00: one came back; of another, the only one, sold a second time, the
# second sale is a double sale. Both are listed and told apart, and the totals are those of the third sale alone.
def test_the_history_tells_apart_sales_cancelled_and_double_sales_and_leaves_them_out_of_its_totals(connection):
    returned = sell(connection, a_card(connection, copies=1, unit_cost_cents=1000), price_cents=1500)
    sales.cancel(connection, returned, Cancellation.RETURN)
    mew = a_card(connection, copies=1, unit_cost_cents=1000)
    sold = sell(connection, mew, price_cents=1500)
    double = sell(connection, mew, price_cents=1500)
    today = datetime.now(LOCAL_TIME).date()

    history = reports.history(connection, today, today)

    assert [(sale.sale_id, sale.cancelled, sale.double) for sale in history.sales] == [
        (double, None, True),
        (sold, None, False),
        (returned, Cancellation.RETURN, False),
    ]
    assert (history.price_cents, history.fee_cents, history.margin_cents) == (1500, 0, 500)


# A card of 10,00 sold at 15,00 left 5,00. One of a cost not known, sold at 50,00, may have left anything: it took in
# its 50,00, but the margin is of the other alone, and it is counted apart.
def test_the_history_leaves_a_sale_of_a_cost_not_known_out_of_its_margin_and_counts_it_apart(connection):
    sell(connection, a_card(connection, copies=1, unit_cost_cents=1000), price_cents=1500)
    sell(connection, a_card(connection, copies=1, unit_cost_cents=None), price_cents=5000)
    today = datetime.now(LOCAL_TIME).date()

    history = reports.history(connection, today, today)

    assert (history.price_cents, history.margin_cents, history.cost_unknown) == (6500, 500, 1)


def italy(*moment: int) -> datetime:
    """A moment in time of Italy."""
    return datetime(*moment, tzinfo=LOCAL_TIME)


def sell(connection, item_id: int, price_cents: int, at: datetime | None = None) -> int:
    """One copy of the item sold on eBay, which keeps nothing, with no shipping on Manuel: now, or else at that time."""
    [ebay] = channel_ids(connection, "eBay")
    return sales.record(connection, Sale(item_id, ebay, 1, price_cents, at=at), manual_channels.MANUAL)
