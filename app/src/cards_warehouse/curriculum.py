"""The numbers of the app's line in Manuel's curriculum, counted from the database for a period: measured, never
guessed, for him to tell at an interview how each was counted."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import Connection, func, or_, select

from cards_warehouse import sales, stock
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.channels import channels


@dataclass(frozen=True)
class Numbers:
    # Both in, in days of Italy.
    first_day: date
    last_day: date
    items: int
    sales: int
    # Names, in the order the channels were added.
    channels: list[str]
    through_api: list[str]
    doubles: int


def numbers(connection: Connection, first_day: date, last_day: date) -> Numbers:
    """The numbers from the first day to the last, both in, in days of Italy."""
    start = datetime.combine(first_day, time(), LOCAL_TIME)
    end = datetime.combine(last_day + timedelta(days=1), time(), LOCAL_TIME)
    by_channel = _sales_by_channel(connection, start, end)
    # By the day of the sale, not of its cancellation: an order cancelled is still the one double sale it was.
    doubles = sum(1 for double in sales.doubles(connection) if start <= double.at < end)
    return Numbers(
        first_day,
        last_day,
        _items(connection, start, end),
        sum(count for _, count, _ in by_channel),
        [name for name, _, _ in by_channel],
        [name for name, _, read in by_channel if read],
        doubles,
    )


def first_day(connection: Connection) -> date | None:
    """The day of Italy the app was first used, the day of its first movement: None when it has none yet."""
    first = connection.execute(select(func.min(stock.stock_movements.c.created_at))).scalar()
    return None if first is None else first.astimezone(LOCAL_TIME).date()


def _items(connection: Connection, start: datetime, end: datetime) -> int:
    """The items with a copy in the warehouse at some time from the start to the end: with copies at the start, or a
    movement after it, since copies came, or left, which they had to be in to do."""
    moves, lots = stock.stock_movements, stock.stock_lots
    handled = (
        select(lots.c.item_id)
        .join_from(moves, lots, lots.c.id == moves.c.lot_id)
        .where(moves.c.created_at < end)
        .group_by(lots.c.item_id)
        .having(
            or_(
                func.coalesce(func.sum(moves.c.change).filter(moves.c.created_at < start), 0) > 0,
                func.count().filter(moves.c.created_at >= start) > 0,
            )
        )
        .subquery()
    )
    return connection.execute(select(func.count()).select_from(handled)).scalar_one()


def _sales_by_channel(connection: Connection, start: datetime, end: datetime) -> list[tuple[str, int, bool]]:
    """Each channel with a sale from the start to the end: its name, its sales, and whether the app read one from the
    channel's API, with the line of its order. A sale cancelled was undone, and a double sale sold no copy: of a sale
    with a double part, the part of the copies there were."""
    sold = sales.sales
    return [
        tuple(row)
        for row in connection.execute(
            select(channels.c.name, func.count(), func.bool_or(sold.c.order_line.is_not(None)))
            .join_from(sold, channels, channels.c.id == sold.c.channel_id)
            .where(
                sold.c.created_at >= start,
                sold.c.created_at < end,
                sold.c.cancelled_at.is_(None),
                sold.c.double_sale.is_(False),
            )
            .group_by(channels.c.id)
            .order_by(channels.c.id)
        )
    ]
