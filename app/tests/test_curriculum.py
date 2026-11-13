"""The curriculum module: the numbers of the app's first line in the curriculum, counted from the database for a period.

On a real PostgreSQL, through the module's functions, with every channel a manual one.
"""

from datetime import datetime, timedelta

from cards_warehouse import curriculum, manual_channels, sales
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.sales import Cancellation, Sale
from tests.test_exposure import channel_ids
from tests.test_sales import a_card


# Four cards of one copy. The first sold; the second sold and sent back; the third sold, then bought again elsewhere, a
# double sale; of the fourth two copies sold, one of them a double sale: three sales, the fourth's in one.
def test_the_sales_leave_out_those_cancelled_and_the_double_sales(connection):
    sell(connection, a_card(connection, copies=1, unit_cost_cents=1000))
    returned = sell(connection, a_card(connection, copies=1, unit_cost_cents=1000))
    sales.cancel(connection, returned, Cancellation.RETURN)
    sold_twice = a_card(connection, copies=1, unit_cost_cents=1000)
    sell(connection, sold_twice)
    sell(connection, sold_twice)
    sell(connection, a_card(connection, copies=1, unit_cost_cents=1000), copies=2)
    today = datetime.now(LOCAL_TIME).date()

    numbers = curriculum.numbers(connection, today, today)

    assert numbers.sales == 3


# A card sold on Vinted and bought on eBay too, today: the eBay order, cancelled as a double sale, is still one. Another
# sold twice yesterday is a double sale of yesterday, whenever it is cancelled.
def test_the_double_sales_are_those_of_the_period_each_once_even_when_cancelled(connection):
    sold_today = a_card(connection, copies=1, unit_cost_cents=1000)
    sell(connection, sold_today)
    double = sell(connection, sold_today, channel="eBay")
    sales.cancel(connection, double, Cancellation.DOUBLE_SALE)
    sold_yesterday = a_card(connection, copies=1, unit_cost_cents=1000)
    yesterday = datetime.now(LOCAL_TIME) - timedelta(days=1)
    sell(connection, sold_yesterday, at=yesterday)
    sell(connection, sold_yesterday, channel="eBay", at=yesterday)
    today = datetime.now(LOCAL_TIME).date()

    numbers = curriculum.numbers(connection, today, today)

    assert numbers.doubles == 1


# A card sold on Tilt by hand. One sold on Vinted, sent back: Vinted had no sale. One sold on eBay, read by the app from
# eBay's orders: eBay is through the API, and Tilt in the order they were added comes first.
def test_the_channels_are_those_with_a_sale_and_through_the_api_those_with_a_sale_read_from_the_api(connection):
    sell(connection, a_card(connection, copies=1, unit_cost_cents=1000), channel="Tilt")
    returned = sell(connection, a_card(connection, copies=1, unit_cost_cents=1000), channel="Vinted")
    sales.cancel(connection, returned, Cancellation.RETURN)
    sell(connection, a_card(connection, copies=1, unit_cost_cents=1000), channel="eBay", order_line="10-1")
    today = datetime.now(LOCAL_TIME).date()

    numbers = curriculum.numbers(connection, today, today)

    assert (numbers.channels, numbers.through_api) == (["Tilt", "eBay"], ["eBay"])


# Two cards loaded today: of one, a copy of two sold, of the other its only copy. Today both were in the warehouse;
# yesterday neither had come; tomorrow only the first has copies left.
def test_the_items_are_those_with_a_copy_in_the_warehouse_at_some_time_of_the_period(connection):
    sell(connection, a_card(connection, copies=2, unit_cost_cents=1000))
    sell(connection, a_card(connection, copies=1, unit_cost_cents=1000))
    today = datetime.now(LOCAL_TIME).date()
    yesterday, tomorrow = today - timedelta(days=1), today + timedelta(days=1)

    assert curriculum.numbers(connection, today, today).items == 2
    assert curriculum.numbers(connection, yesterday, yesterday).items == 0
    assert curriculum.numbers(connection, tomorrow, tomorrow).items == 1


def sell(
    connection,
    item_id: int,
    channel: str = "Vinted",
    copies: int = 1,
    at: datetime | None = None,
    order_line: str | None = None,
) -> int:
    """Copies of the item, one unless told, sold at 20,00 each: now, or else at that time. By hand, or else read from
    the channel's order with that line."""
    [sold_on] = channel_ids(connection, channel)
    sale = Sale(item_id, sold_on, copies, 2000 * copies, at=at, order_line=order_line)
    return sales.record(connection, sale, manual_channels.MANUAL)
