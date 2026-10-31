"""The capital idle in the bulk: of each bulk with cards, what they cost and since when its oldest lot with cards
stands, for Manuel to tell when it is worth selling it off."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, Integer, case, func, select

from cards_warehouse.items import Kind, items
from cards_warehouse.stock import stock_lots, stock_movements


@dataclass(frozen=True)
class Idle:
    item_id: int
    name: str
    cards: int
    cost_cents: int | None
    # When the oldest lot with cards left came in: it stands since then.
    since: datetime


def idle(connection: Connection) -> list[Idle]:
    """Every bulk with cards left, the one standing the longest first."""
    per_lot = (
        select(
            stock_lots.c.item_id,
            func.sum(stock_movements.c.change).label("cards"),
            # The cost moved with the cards of a lot of the bulk.
            func.sum(stock_movements.c.cost_cents).label("cost"),
            func.min(stock_movements.c.created_at).label("came"),
        )
        .join_from(stock_lots, stock_movements, stock_movements.c.lot_id == stock_lots.c.id)
        .group_by(stock_lots.c.id)
        .having(func.sum(stock_movements.c.change) > 0)
        .subquery()
    )
    # Not known when a lot's is not: those cards may have cost anything.
    cost = case((func.bool_or(per_lot.c.cost.is_(None)), None), else_=func.sum(per_lot.c.cost))
    rows = connection.execute(
        select(
            items.c.id,
            items.c.name,
            func.sum(per_lot.c.cards).cast(Integer),
            cost.cast(Integer),
            func.min(per_lot.c.came),
        )
        .join_from(items, per_lot, per_lot.c.item_id == items.c.id)
        .where(items.c.kind == Kind.BULK)
        .group_by(items.c.id)
        .order_by(func.min(per_lot.c.came))
    )
    return [Idle(*row) for row in rows]
