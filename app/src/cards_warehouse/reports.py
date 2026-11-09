"""Reports: the margin of a period, as much as its sales really made, for Manuel to tell whether he keeps to his
target. And the capital idle in the warehouse, for him to tell where his money is."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import Connection, Integer, func, select

from cards_warehouse import pricing, stock
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.items import Kind, items
from cards_warehouse.pricing import Margin
from cards_warehouse.sales import sales


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
    """The margin of the sales from the first day to the last, both in, in days of Italy. A sale cancelled is out."""
    start = datetime.combine(first_day, time(), LOCAL_TIME)
    end = datetime.combine(last_day + timedelta(days=1), time(), LOCAL_TIME)
    # A sale whose cost is not known has no margin either: the sums leave it out.
    counted, every, left, cost = connection.execute(
        select(
            func.count(sales.c.cost_cents),
            func.count(),
            func.sum(sales.c.price_cents - sales.c.fee_cents - sales.c.shipping_cents - sales.c.cost_cents),
            func.sum(sales.c.cost_cents),
        ).where(sales.c.created_at >= start, sales.c.created_at < end, sales.c.cancelled_at.is_(None))
    ).one()
    return PeriodMargin(first_day, last_day, counted, every - counted, pricing.on_cost(left, cost) if counted else None)


def monthly_margins(connection: Connection, today: date) -> list[PeriodMargin]:
    """The margin of each month, from the one of today back to the one of the first sale: a month with no sale too."""
    first_sale = connection.execute(select(func.min(sales.c.created_at))).scalar()
    oldest = (today if first_sale is None else first_sale.astimezone(LOCAL_TIME).date()).replace(day=1)
    months, month = [], today.replace(day=1)
    while month >= oldest:
        next_month = (month + timedelta(days=31)).replace(day=1)
        months.append(margin(connection, month, next_month - timedelta(days=1)))
        month = (month - timedelta(days=1)).replace(day=1)
    return months


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
