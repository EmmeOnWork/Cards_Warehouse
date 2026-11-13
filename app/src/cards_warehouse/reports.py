"""Reports: the margin of a period, as much as its sales really made, for Manuel to tell whether he keeps to his
target. The sales of a period one by one, with each person's part of them, for the accountant. And the capital idle in
the warehouse, for him to tell where his money is."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import ColumnElement, Connection, Integer, Row, and_, func, select

from cards_warehouse import balances, pricing, stock
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.balances import SaleParts
from cards_warehouse.channels import channels
from cards_warehouse.items import Kind, items
from cards_warehouse.pricing import Margin
from cards_warehouse.sales import Cancellation, sales


@dataclass(frozen=True)
class PeriodMargin:
    """The margin of the sales of a period on the cost of the copies they sold, and how many sales it counts."""

    # Both in, in days of Italy.
    first_day: date
    last_day: date
    sales: int
    # The sales left out of the margin: a copy they sold has a cost not known.
    cost_unknown: int
    # None when no sale is counted.
    margin: Margin | None


def margin(connection: Connection, first_day: date, last_day: date) -> PeriodMargin:
    """The margin of the sales from the first day to the last, both in, in days of Italy. A sale cancelled is out, and
    so is a double sale: no copy left the stock."""
    # A sale whose cost is not known has no margin either: the sums leave it out.
    counted, every, left, cost = connection.execute(
        select(
            func.count(sales.c.cost_cents),
            func.count(),
            func.sum(sales.c.price_cents - sales.c.fee_cents - sales.c.shipping_cents - sales.c.cost_cents),
            func.sum(sales.c.cost_cents),
        ).where(_made(first_day, last_day), sales.c.cancelled_at.is_(None), sales.c.double_sale.is_(False))
    ).one()
    return PeriodMargin(first_day, last_day, counted, every - counted, pricing.on_cost(left, cost) if counted else None)


def _made(first_day: date, last_day: date) -> ColumnElement[bool]:
    """The sales from the first day to the last, both in, in days of Italy."""
    start = datetime.combine(first_day, time(), LOCAL_TIME)
    end = datetime.combine(last_day + timedelta(days=1), time(), LOCAL_TIME)
    return and_(sales.c.created_at >= start, sales.c.created_at < end)


def monthly_margins(connection: Connection, today: date) -> list[PeriodMargin]:
    """The margin of each month, from the one of today back to the one of the first sale: a month with no sale too."""
    first_sale = connection.execute(select(func.min(sales.c.created_at))).scalar()
    oldest = (today if first_sale is None else first_sale.astimezone(LOCAL_TIME).date()).replace(day=1)
    months, month = [], today.replace(day=1)
    while month >= oldest:
        months.append(margin(connection, *month_of(month)))
        month = (month - timedelta(days=1)).replace(day=1)
    return months


def month_of(day: date) -> tuple[date, date]:
    """The first day and the last of the month of the day."""
    first = day.replace(day=1)
    return first, (first + timedelta(days=31)).replace(day=1) - timedelta(days=1)


@dataclass(frozen=True)
class Sold:
    """A sale of a period, with what it left and each person's part of it: a line of the file for the accountant."""

    at: datetime
    item: str
    channel: str
    quantity: int
    price_cents: int
    fee_cents: int
    shipping_cents: int
    # None when a copy sold has a cost not known, and then the margin too.
    cost_cents: int | None
    margin: Margin | None
    parts: SaleParts


def sold(connection: Connection, first_day: date, last_day: date) -> list[Sold]:
    """The sales from the first day to the last, both in, in days of Italy, the oldest first. A sale cancelled is out,
    and so is a double sale: no copy left the stock."""
    rows = connection.execute(
        select(sales, items.c.name.label("item"), channels.c.name.label("channel"))
        .join_from(sales, items, items.c.id == sales.c.item_id)
        .join(channels, channels.c.id == sales.c.channel_id)
        .where(_made(first_day, last_day), sales.c.cancelled_at.is_(None), sales.c.double_sale.is_(False))
        .order_by(sales.c.created_at, sales.c.id)
    )
    return [
        Sold(
            row.created_at,
            row.item,
            row.channel,
            row.quantity,
            row.price_cents,
            row.fee_cents,
            row.shipping_cents,
            row.cost_cents,
            _margin(row),
            balances.of_sale(connection, row.id),
        )
        for row in rows
    ]


def _margin(sale: Row) -> Margin | None:
    """What a row of the sales left: None when a copy it sold has a cost not known."""
    if sale.cost_cents is None:
        return None
    return pricing.margin(sale.price_cents, sale.fee_cents, sale.cost_cents, sale.shipping_cents)


@dataclass(frozen=True)
class HistorySale:
    """A sale as the history lists it: when, of which item, on which channel, and what it left."""

    sale_id: int
    at: datetime
    item: str
    channel: str
    quantity: int
    price_cents: int
    fee_cents: int
    shipping_cents: int
    # None when a copy sold has a cost not known, and of a double sale, which took none.
    margin: Margin | None
    # Why it was undone: None while it stands.
    cancelled: Cancellation | None = None
    # A double sale: its copies were sold already elsewhere, and none left the stock.
    double: bool = False


@dataclass(frozen=True)
class History:
    """The sales of a period, the newest first, and what they took in, paid in fees and left all together: those that
    stand, double sales apart."""

    sales: list[HistorySale]
    price_cents: int
    fee_cents: int
    # Of the sales whose cost is known.
    margin_cents: int
    # The sales left out of the margin: a copy they sold has a cost not known.
    cost_unknown: int


def history(connection: Connection, first_day: date, last_day: date, channel_id: int | None = None) -> History:
    """The sales from the first day to the last, both in, in days of Italy: of one channel, or else of all."""
    query = (
        select(sales, items.c.name.label("item"), channels.c.name.label("channel"))
        .join_from(sales, items, items.c.id == sales.c.item_id)
        .join(channels, channels.c.id == sales.c.channel_id)
        .where(_made(first_day, last_day))
        .order_by(sales.c.created_at.desc(), sales.c.id.desc())
    )
    if channel_id is not None:
        query = query.where(sales.c.channel_id == channel_id)
    rows = connection.execute(query)
    listed = [
        HistorySale(
            row.id,
            row.created_at,
            row.item,
            row.channel,
            row.quantity,
            row.price_cents,
            row.fee_cents,
            row.shipping_cents,
            _margin(row),
            None if row.cancelled_at is None else Cancellation(row.cancellation_cause),
            row.double_sale,
        )
        for row in rows
    ]
    counted = [sale for sale in listed if sale.cancelled is None and not sale.double]
    margins = [sale.margin.cents for sale in counted if sale.margin is not None]
    return History(
        listed,
        sum(sale.price_cents for sale in counted),
        sum(sale.fee_cents for sale in counted),
        sum(margins),
        len(counted) - len(margins),
    )


@dataclass(frozen=True)
class Capital:
    """What copies available cost: those whose cost is known, and how many others there are, which may cost anything.
    Of the bulk, its cards."""

    copies: int
    cost_cents: int
    cost_unknown: int


@dataclass(frozen=True)
class IdleCapital:
    # The kinds with copies available, in the order of their kind.
    by_kind: dict[Kind, Capital]
    total: Capital


def capital(connection: Connection) -> IdleCapital:
    """The capital idle in the warehouse: what the copies available cost, of each kind and all together. A copy sold,
    opened or sent for grading is not available."""
    lots = stock.of_each_lot()
    known = lots.c.cost_cents.is_not(None)
    rows = connection.execute(
        select(
            items.c.kind,
            # Sums of sums, which PostgreSQL makes decimal: whole again.
            func.coalesce(func.sum(lots.c.available).filter(known), 0).cast(Integer),
            func.coalesce(func.sum(lots.c.cost_cents), 0).cast(Integer),
            func.coalesce(func.sum(lots.c.available).filter(~known), 0).cast(Integer),
        )
        .join_from(lots, items, items.c.id == lots.c.item_id)
        .where(lots.c.available > 0)
        .group_by(items.c.kind)
    )
    held = {Kind(kind): Capital(*capital) for kind, *capital in rows}
    by_kind = {kind: held[kind] for kind in Kind if kind in held}
    total = Capital(
        sum(each.copies for each in held.values()),
        sum(each.cost_cents for each in held.values()),
        sum(each.cost_unknown for each in held.values()),
    )
    return IdleCapital(by_kind, total)
