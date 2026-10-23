"""Stock: the lots of each item, and the movements of their copies.

A lot is the copies of an item with the same origin and unit cost. Every change of quantity is a movement
with its cause, and the quantity available is the sum of the movements: it never goes below zero.
"""

from enum import StrEnum

from sqlalchemy import Column, Connection, Integer, Subquery, Table, Text, func, insert, select

from cards_warehouse.database import metadata


class Cause(StrEnum):
    LOAD = "load"
    SALE = "sale"
    # A sale undone: a return, or an order cancelled.
    CANCELLATION = "cancellation"


class NotEnoughStock(Exception):
    """An unload of more copies than its lot has: the quantity would go below zero."""


stock_lots = Table(
    "stock_lots",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("item_id", Integer),
    Column("unit_cost_cents", Integer),
)

stock_movements = Table(
    "stock_movements",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("lot_id", Integer),
    Column("change", Integer),
    Column("cause", Text),
)

# The quantity of whatever movements a query picks.
_quantity = func.coalesce(func.sum(stock_movements.c.change), 0)


def load(connection: Connection, item_id: int, quantity: int, unit_cost_cents: int | None) -> int:
    """A new lot of the item, with its copies loaded. A unit cost of None is a cost not known."""
    _check_quantity(quantity)
    if unit_cost_cents is not None and unit_cost_cents < 1:
        raise ValueError("a known cost is at least 1 cent: a cost not known is None, not zero")
    lot_id = connection.execute(
        insert(stock_lots).values(item_id=item_id, unit_cost_cents=unit_cost_cents).returning(stock_lots.c.id)
    ).scalar_one()
    connection.execute(insert(stock_movements).values(lot_id=lot_id, change=quantity, cause=Cause.LOAD))
    return lot_id


def unload(connection: Connection, lot_id: int, quantity: int, cause: Cause) -> int:
    _check_quantity(quantity)
    # The lot is locked until the transaction ends: a second unload of it waits here, then counts what this one
    # left. Without the lock both would count the same copies, and both would take the last one.
    connection.execute(select(stock_lots.c.id).where(stock_lots.c.id == lot_id).with_for_update())
    in_lot = connection.execute(select(_quantity).where(stock_movements.c.lot_id == lot_id)).scalar_one()
    if quantity > in_lot:
        raise NotEnoughStock(f"lot {lot_id} has {in_lot} copies, {quantity} asked")
    return connection.execute(
        insert(stock_movements).values(lot_id=lot_id, change=-quantity, cause=cause).returning(stock_movements.c.id)
    ).scalar_one()


def restore(connection: Connection, unload_id: int) -> int:
    """Undo an unload: its copies go back to the lot they left, with a movement of their own."""
    lot_id, change = connection.execute(
        select(stock_movements.c.lot_id, stock_movements.c.change).where(stock_movements.c.id == unload_id)
    ).one()
    return connection.execute(
        insert(stock_movements)
        .values(lot_id=lot_id, change=-change, cause=Cause.CANCELLATION)
        .returning(stock_movements.c.id)
    ).scalar_one()


def available(connection: Connection, item_id: int) -> int:
    per_item = of_items()
    return connection.execute(select(per_item.c.available).where(per_item.c.item_id == item_id)).scalar() or 0


def of_items() -> Subquery:
    """The stock of each item with lots, for a query to join: `item_id`, the quantity `available`, and
    `cost_unknown` when a lot has a cost not known."""
    return (
        select(
            stock_lots.c.item_id,
            _quantity.label("available"),
            func.bool_or(stock_lots.c.unit_cost_cents.is_(None)).label("cost_unknown"),
        )
        .join_from(stock_lots, stock_movements, stock_movements.c.lot_id == stock_lots.c.id)
        .group_by(stock_lots.c.item_id)
        .subquery()
    )


def _check_quantity(quantity: int) -> None:
    if quantity < 1:
        raise ValueError(f"a quantity is at least 1, not {quantity}: the cause of a movement says its direction")
