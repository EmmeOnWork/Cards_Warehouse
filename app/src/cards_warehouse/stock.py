"""Stock: the lots of each item, and the movements of their copies.

A lot is the copies of an item with the same origin and unit cost. Every change of quantity is a movement
with its cause, and the quantity available is the sum of the movements: it never goes below zero.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from itertools import groupby

from sqlalchemy import Column, Connection, DateTime, Integer, Subquery, Table, Text, func, insert, select

from cards_warehouse import cost_split
from cards_warehouse.database import metadata


class Cause(StrEnum):
    LOAD = "load"
    SALE = "sale"
    # A sale undone: a return, or an order cancelled.
    CANCELLATION = "cancellation"
    # The adjustments: copies that leave without a sale, or a count that was wrong, either way.
    LOST = "lost"
    DAMAGED = "damaged"
    GIVEN_AWAY = "given_away"
    MISCOUNT = "miscount"
    # A copy opened, such as a box into packs: it leaves its lot, and what was inside comes in as new lots.
    OPENING = "opening"
    # A card sent to a grader, such as PSA: it leaves its lot for the months the grading takes.
    SENT_FOR_GRADING = "sent_for_grading"
    # Back from the grader with its grade: a lot of its own, in an item graded.
    GRADED = "graded"
    # A card of the bulk taken out to be sold on its own: it leaves its lot of the bulk, for a lot of its own.
    EXTRACTION = "extraction"


class NotEnoughStock(Exception):
    """A movement that takes more copies than its lot has: the quantity would go below zero."""


stock_lots = Table(
    "stock_lots",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("item_id", Integer),
    Column("unit_cost_cents", Integer),
    Column("purchase_id", Integer),
)

stock_movements = Table(
    "stock_movements",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("lot_id", Integer),
    Column("change", Integer),
    Column("cause", Text),
    Column("note", Text),
    Column("created_at", DateTime(timezone=True)),
    # On the copies that came out of an opening: the movement that took the copy opened. On a card extracted from the
    # bulk: the movement that took it out of the bulk.
    Column("opening_id", Integer),
    # On a lot of the bulk, which has no unit cost: the cost that came or went with the cards.
    Column("cost_cents", Integer),
    # On the copies sold: the sale that took them.
    Column("sale_id", Integer),
)

# The quantity of whatever movements a query picks.
_quantity = func.coalesce(func.sum(stock_movements.c.change), 0)
# What the copies of a lot cost, all together, from its movements: by its unit cost, or by the cost moved with the
# cards on a lot of the bulk. None when not known.
_cost = func.coalesce(stock_lots.c.unit_cost_cents * _quantity, func.sum(stock_movements.c.cost_cents))


def load(
    connection: Connection,
    item_id: int,
    quantity: int,
    unit_cost_cents: int | None,
    purchase_id: int | None = None,
    opening_id: int | None = None,
    cause: Cause | None = None,
) -> int:
    """A new lot of the item, with its copies loaded. A unit cost of None is a cost not known.

    The purchase the lot comes from, if any, directly or through the openings that made it: a lot without one is
    all Manuel's. The movement of the opening the copies came out of, if any: theirs is then an opening too.
    The cause of their movement, when it is neither a load nor an opening: a card back from its grading, or one
    extracted from the bulk."""
    _check_quantity(quantity)
    _check_cost(unit_cost_cents)
    lot_id = connection.execute(
        insert(stock_lots)
        .values(item_id=item_id, unit_cost_cents=unit_cost_cents, purchase_id=purchase_id)
        .returning(stock_lots.c.id)
    ).scalar_one()
    if cause is None:
        cause = Cause.LOAD if opening_id is None else Cause.OPENING
    connection.execute(
        insert(stock_movements).values(lot_id=lot_id, change=quantity, cause=cause, opening_id=opening_id)
    )
    return lot_id


def load_bulk(
    connection: Connection, item_id: int, cards: int, cost_cents: int | None, purchase_id: int | None, opening_id: int
) -> int:
    """A new lot of the bulk, its cards counted roughly, out of an opening. Its cost is whole, not one for each card,
    since a cent does not divide among them: it moves with the cards, on their movements. None is a cost not known."""
    _check_quantity(cards)
    _check_cost(cost_cents)
    lot_id = connection.execute(
        insert(stock_lots).values(item_id=item_id, purchase_id=purchase_id).returning(stock_lots.c.id)
    ).scalar_one()
    connection.execute(
        insert(stock_movements).values(
            lot_id=lot_id, change=cards, cause=Cause.OPENING, opening_id=opening_id, cost_cents=cost_cents
        )
    )
    return lot_id


def load_split(
    connection: Connection,
    item_id: int,
    unit_costs: list[int | None],
    purchase_id: int | None = None,
    opening_id: int | None = None,
) -> None:
    """Copies whose costs come from a split, one for each, in a lot for each unit cost: a lot, or two when the
    split left cents over. In the order of the split, the dearer first: the first lot is the one a sale takes from
    when Manuel does not choose. Costs all None, not known, make one lot."""
    for unit_cost, copies in groupby(unit_costs):
        load(connection, item_id, len(list(copies)), unit_cost, purchase_id=purchase_id, opening_id=opening_id)


@dataclass(frozen=True)
class Taken:
    """A card taken out of a lot of the bulk: the movement that took it, its share of the cost of the lot, and the
    purchase the lot came from, if any."""

    movement_id: int
    cost_cents: int | None
    purchase_id: int | None


def take_from_bulk(connection: Connection, item_id: int) -> Taken:
    """A card out of the bulk, from its oldest lot with cards left, with its share of what the cards of that lot
    cost: the lot loses the card and the share, with one movement."""
    # Every lot of the bulk is locked until the transaction ends: a second extraction waits here, then finds the
    # lot this one left, or the next when this one took its last card.
    connection.execute(select(stock_lots.c.id).where(stock_lots.c.item_id == item_id).with_for_update())
    oldest = connection.execute(
        select(stock_lots.c.id, stock_lots.c.purchase_id)
        .join_from(stock_lots, stock_movements, stock_movements.c.lot_id == stock_lots.c.id)
        .where(stock_lots.c.item_id == item_id)
        .group_by(stock_lots.c.id)
        .having(_quantity > 0)
        .order_by(stock_lots.c.id)
    ).first()
    if oldest is None:
        raise NotEnoughStock(f"the bulk {item_id} has no cards")
    lot_id, purchase_id = oldest
    cards, cost = connection.execute(
        select(_quantity, func.sum(stock_movements.c.cost_cents)).where(stock_movements.c.lot_id == lot_id)
    ).one()
    # A lot of fewer cents than cards runs out of them before its cards: the cards after cost nothing, and no margin is
    # worked out on nothing, so theirs is not known, as it is out of a lot whose cost is not known.
    share = cost_split.one_part(cost, cards) if cost else None
    movement = _move(connection, lot_id, -1, Cause.EXTRACTION, cost_cents=None if share is None else -share)
    return Taken(movement, share, purchase_id)


def unload(connection: Connection, lot_id: int, quantity: int, cause: Cause, sale_id: int | None = None) -> int:
    """Copies that leave the lot. The sale that took them, if they were sold."""
    _check_quantity(quantity)
    return _move(connection, lot_id, -quantity, cause, sale_id=sale_id)


def adjust(connection: Connection, lot_id: int, change: int, cause: Cause, note: str = "") -> int:
    """A change of the lot that is not a sale: copies lost, damaged or given away, or a count that was wrong.
    Positive when copies are found, negative when they leave."""
    return _move(connection, lot_id, change, cause, note)


@dataclass(frozen=True)
class Movement:
    id: int
    at: datetime
    cause: Cause
    # The lot's number within its item, in the order the lots came: 1, 2… rather than an id of the database.
    lot: int
    change: int
    note: str


def history(connection: Connection, item_id: int) -> list[Movement]:
    """The movements of the item's lots, the oldest first: their changes add up to the quantity available."""
    numbered = _numbered_lots(item_id)
    rows = connection.execute(
        select(
            stock_movements.c.id,
            stock_movements.c.created_at,
            stock_movements.c.cause,
            numbered.c.number,
            stock_movements.c.change,
            stock_movements.c.note,
        )
        .join_from(stock_movements, numbered, stock_movements.c.lot_id == numbered.c.id)
        .order_by(stock_movements.c.id)
    )
    return [Movement(id, at, Cause(cause), number, change, note) for id, at, cause, number, change, note in rows]


def _move(
    connection: Connection,
    lot_id: int,
    change: int,
    cause: Cause,
    note: str = "",
    cost_cents: int | None = None,
    sale_id: int | None = None,
) -> int:
    # The lot is locked until the transaction ends: a second movement of it waits here, then counts what this one
    # left. Without the lock both would count the same copies, and both would take the last one.
    connection.execute(select(stock_lots.c.id).where(stock_lots.c.id == lot_id).with_for_update())
    in_lot = connection.execute(select(_quantity).where(stock_movements.c.lot_id == lot_id)).scalar_one()
    if in_lot + change < 0:
        raise NotEnoughStock(f"lot {lot_id} has {in_lot} copies, {-change} asked")
    return connection.execute(
        insert(stock_movements)
        .values(lot_id=lot_id, change=change, cause=cause, note=note, cost_cents=cost_cents, sale_id=sale_id)
        .returning(stock_movements.c.id)
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


def cost_to_cover(connection: Connection, item_id: int) -> int | None:
    """The unit cost a price of the item must cover: the highest of its lots, so that every copy reaches the
    target margin. None when a lot's cost is not known, since those copies may have cost more."""
    unknown, highest = connection.execute(
        select(func.bool_or(stock_lots.c.unit_cost_cents.is_(None)), func.max(stock_lots.c.unit_cost_cents)).where(
            stock_lots.c.item_id == item_id
        )
    ).one()
    return None if unknown else highest


def of_items() -> Subquery:
    """The stock of each item with lots, for a query to join: `item_id`, the quantity `available`, and
    `cost_unknown` when a lot has a cost not known."""
    per_lot = (
        select(stock_lots.c.item_id, _quantity.label("available"), _cost.is_(None).label("cost_unknown"))
        .join_from(stock_lots, stock_movements, stock_movements.c.lot_id == stock_lots.c.id)
        .group_by(stock_lots.c.id)
        .subquery()
    )
    return (
        select(
            per_lot.c.item_id,
            func.sum(per_lot.c.available).label("available"),
            func.bool_or(per_lot.c.cost_unknown).label("cost_unknown"),
        )
        .group_by(per_lot.c.item_id)
        .subquery()
    )


def of_lots() -> Subquery:
    """Each lot as it was loaded, for a query to join: `lot_id`, `item_id`, `purchase_id`, `unit_cost_cents`, and
    the copies `loaded` into it, which no sale or adjustment changes."""
    return (
        select(
            stock_lots.c.id.label("lot_id"),
            stock_lots.c.item_id,
            stock_lots.c.purchase_id,
            stock_lots.c.unit_cost_cents,
            func.sum(stock_movements.c.change).label("loaded"),
        )
        .join_from(stock_lots, stock_movements, stock_movements.c.lot_id == stock_lots.c.id)
        .where(stock_movements.c.cause == Cause.LOAD)
        .group_by(stock_lots.c.id)
        .subquery()
    )


@dataclass(frozen=True)
class Lot:
    id: int
    # As in the history: 1, 2… in the order the lots of the item came.
    number: int
    available: int
    unit_cost_cents: int | None
    # What the copies it has now cost, all together: of a lot of the bulk, the cost moved with its cards.
    cost_cents: int | None


def lots(connection: Connection, item_id: int) -> list[Lot]:
    """The lots of the item, the oldest first, with the copies each has now and what they cost."""
    numbered = _numbered_lots(item_id)
    rows = connection.execute(
        select(numbered.c.id, numbered.c.number, _quantity, stock_lots.c.unit_cost_cents, _cost)
        .join_from(numbered, stock_lots, stock_lots.c.id == numbered.c.id)
        .join(stock_movements, stock_movements.c.lot_id == numbered.c.id)
        .group_by(numbered.c.id, numbered.c.number, stock_lots.c.unit_cost_cents)
        .order_by(numbered.c.number)
    )
    return [Lot(*row) for row in rows]


def _numbered_lots(item_id: int) -> Subquery:
    """The `id` of each lot of the item, and its `number` within the item."""
    return (
        select(stock_lots.c.id, func.row_number().over(order_by=stock_lots.c.id).label("number"))
        .where(stock_lots.c.item_id == item_id)
        .subquery()
    )


def _check_cost(cost_cents: int | None) -> None:
    if cost_cents is not None and cost_cents < 1:
        raise ValueError("a known cost is at least 1 cent: a cost not known is None, not zero")


def _check_quantity(quantity: int) -> None:
    if quantity < 1:
        raise ValueError(f"a quantity is at least 1, not {quantity}: the cause of a movement says its direction")
