"""Sales: copies of an item sold on a channel at a real price. A sale takes its copies from the stock, tells the
exposure what that leaves to do on the channels, and keeps the real margin it left."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Column,
    Connection,
    DateTime,
    Integer,
    Table,
    Text,
    and_,
    func,
    insert,
    or_,
    select,
    update,
)

from cards_warehouse import channels, exposure, items, pricing, stock
from cards_warehouse.channels import channels as channel_rows
from cards_warehouse.database import metadata
from cards_warehouse.exposure import ChannelOperations
from cards_warehouse.pricing import Margin
from cards_warehouse.stock import Cause


class NotEnoughCopies(Exception):
    """More copies sold than the lot chosen has, or than the item has where they cannot be a double sale."""

    def __init__(self, available: int) -> None:
        super().__init__(f"{available} copies left")
        self.available = available


class AlreadyCancelled(Exception):
    """The sale was undone before: its copies went back already."""


class Cancellation(StrEnum):
    """Why a sale was undone."""

    RETURN = "return"
    ORDER_CANCELLED = "order_cancelled"
    # The copies were sold already elsewhere: the order could not be sent.
    DOUBLE_SALE = "double_sale"


@dataclass(frozen=True)
class Sale:
    """A sale as Manuel records it."""

    item_id: int
    channel_id: int
    quantity: int
    # What the buyer paid for all the copies, shipping apart.
    price_cents: int
    # What the channel kept, as Manuel corrected it from its app. None: the fee of the channel's rule.
    fee_cents: int | None = None
    # The shipping left on Manuel.
    shipping_cents: int = 0
    # The lot the copies came from, as Manuel chose it. None: the oldest first.
    lot_id: int | None = None
    note: str = ""
    # Who sold it and took the money: a partner, from their own account, or None for Manuel.
    collected_by: int | None = None
    # False where copies short cannot have been sold already elsewhere: at a live, where Manuel had them in his hands,
    # and of the bulk, whose cards are counted by eye. Fewer left is then a count to fix: NotEnoughCopies.
    may_be_double: bool = True
    # The line of the channel's order it came from, when the app read it from the channel: None when Manuel records it.
    order_line: str | None = None
    # When the buyer bought it, as the channel's order says. None: as it is recorded.
    at: datetime | None = None


@dataclass(frozen=True)
class Cancelled:
    """A sale undone: why, when, and what Manuel noted on it."""

    cause: Cancellation
    at: datetime
    note: str


@dataclass(frozen=True)
class Recorded:
    """A sale recorded, with what it left."""

    id: int
    item_id: int
    channel: str
    quantity: int
    price_cents: int
    fee_cents: int
    shipping_cents: int
    # None when a copy sold has a cost not known: no margin can be told.
    cost_cents: int | None
    margin: Margin | None
    note: str
    # None while the sale stands.
    cancelled: Cancelled | None = None
    # A double sale: its copies were sold already elsewhere, and none left the stock.
    double: bool = False
    # Of a sale of more copies than were left: the double sale of those that were not, in the same order.
    double_part: int | None = None


sales = Table(
    "sales",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("item_id", Integer),
    Column("channel_id", Integer),
    Column("quantity", Integer),
    Column("price_cents", Integer),
    Column("fee_cents", Integer),
    Column("shipping_cents", Integer),
    Column("cost_cents", Integer),
    Column("note", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("cancellation_cause", Text),
    Column("cancellation_note", Text),
    Column("cancelled_at", DateTime(timezone=True)),
    Column("collected_by_partner_id", Integer),
    Column("double_sale", Boolean),
    Column("double_part_id", Integer),
    Column("order_line", Text),
)


def record(connection: Connection, sale: Sale, operations: ChannelOperations) -> int:
    """The sale, with its copies taken from the stock and what it leaves to do on the listings of the item, done
    through `operations`. The copies the item no longer has, sold already elsewhere, are a double sale, which takes
    nothing: all of them, or those over the copies left, apart from the sale of the others. The sale of the copies
    there were, or else the double sale. NotEnoughCopies when the lot chosen has fewer, or the item when the sale
    cannot be double: nothing is taken."""
    channel = channels.one(connection, sale.channel_id)
    fee = pricing.fee(sale.price_cents, channel.fee) if sale.fee_cents is None else sale.fee_cents
    whole = replace(sale, fee_cents=fee)
    taken = _taken(connection, sale)
    there = sum(copies for _, copies in taken)
    # Of the price and of the fee, the part of the copies there were: the rest is the double sale's.
    sold = replace(
        whole,
        quantity=there,
        price_cents=_part(sale.price_cents, there, sale.quantity),
        fee_cents=_part(fee, there, sale.quantity),
    )
    sale_id = double_id = None
    if there < sale.quantity:
        double = replace(
            whole,
            quantity=sale.quantity - there,
            price_cents=sale.price_cents - sold.price_cents,
            fee_cents=fee - sold.fee_cents,
            # The shipping is of the copies sent: the double sale's only when there was none to send.
            shipping_cents=0 if there else sale.shipping_cents,
        )
        sale_id = double_id = _insert(connection, double, double_sale=True)
    if there:
        sale_id = _insert(connection, sold, double_part_id=double_id)
        # The cost of the copies, lot by lot: with the grading in it, for a graded card; of the bulk, the part of each
        # lot its cards take. Not known if one is not, nor when the cards come from lots of the bulk with no cents
        # left: no margin is worked out on nothing.
        costs = [
            stock.take(connection, lot.id, copies, Cause.SALE, sale_id=sale_id).cost_cents for lot, copies in taken
        ]
        cost = None if None in costs else sum(costs) or None
        connection.execute(update(sales).where(sales.c.id == sale_id).values(cost_cents=cost))
    exposure.sold(connection, sale.item_id, sale.channel_id, sale.quantity, operations)
    return sale_id


def order_recorded(connection: Connection, channel_id: int, order_line: str) -> bool:
    """Whether the line of the channel's order is a sale already."""
    return connection.execute(
        select(select(sales.c.id).where(sales.c.channel_id == channel_id, sales.c.order_line == order_line).exists())
    ).scalar_one()


def _insert(connection: Connection, sale: Sale, **values) -> int:
    return connection.execute(
        insert(sales)
        .values(
            item_id=sale.item_id,
            channel_id=sale.channel_id,
            quantity=sale.quantity,
            price_cents=sale.price_cents,
            fee_cents=sale.fee_cents,
            shipping_cents=sale.shipping_cents,
            note=sale.note,
            collected_by_partner_id=sale.collected_by,
            order_line=sale.order_line,
            created_at=func.now() if sale.at is None else sale.at,
            **values,
        )
        .returning(sales.c.id)
    ).scalar_one()


def _part(cents: int, copies: int, of: int) -> int:
    """What so many of the copies of a sale come to, of an amount of them all: to the nearest cent."""
    return (2 * cents * copies + of) // (2 * of)


def cancel(connection: Connection, sale_id: int, cause: Cancellation, note: str = "") -> None:
    """The sale undone, for a return, an order cancelled or a double sale: its copies go back to the lots they came
    from, and a double sale, which took none, gives none back. AlreadyCancelled when it was undone before: they went
    back then."""
    # A second cancellation, even one at the same time, waits on the row and then finds it cancelled.
    cancelled = connection.execute(
        update(sales)
        .where(sales.c.id == sale_id, sales.c.cancelled_at.is_(None))
        .values(cancellation_cause=cause, cancellation_note=note, cancelled_at=func.now())
        .returning(sales.c.id)
    ).first()
    if cancelled is None:
        raise AlreadyCancelled(sale_id)
    stock.restore_sale(connection, sale_id)


def _taken(connection: Connection, sale: Sale) -> list[tuple[stock.Lot, int]]:
    """The lots the copies sold come from, and how many from each: the one Manuel chose, or else the oldest first,
    until they are all taken or none is left."""
    lots = stock.lots(connection, sale.item_id)
    if sale.lot_id is not None:
        lots = [lot for lot in lots if lot.id == sale.lot_id]
    taken, left = [], sale.quantity
    for lot in lots:
        copies = min(lot.available, left)
        if copies:
            taken.append((lot, copies))
            left -= copies
    if left and (sale.lot_id is not None or not sale.may_be_double):
        raise NotEnoughCopies(sum(lot.available for lot in lots))
    return taken


def one(connection: Connection, sale_id: int) -> Recorded | None:
    row = connection.execute(
        select(sales, channel_rows.c.name.label("channel"))
        .join_from(sales, channel_rows, channel_rows.c.id == sales.c.channel_id)
        .where(sales.c.id == sale_id)
    ).one_or_none()
    if row is None:
        return None
    if row.cost_cents is None:
        margin = None
    else:
        margin = pricing.margin(row.price_cents, row.fee_cents, row.cost_cents, row.shipping_cents)
    cancelled = None
    if row.cancelled_at is not None:
        cancelled = Cancelled(Cancellation(row.cancellation_cause), row.cancelled_at, row.cancellation_note)
    return Recorded(
        row.id,
        row.item_id,
        row.channel,
        row.quantity,
        row.price_cents,
        row.fee_cents,
        row.shipping_cents,
        row.cost_cents,
        margin,
        row.note,
        cancelled,
        row.double_sale,
        row.double_part_id,
    )


@dataclass(frozen=True)
class Double:
    """A double sale as the list shows it: when it came, on which channel, of which item, and how many copies."""

    sale_id: int
    at: datetime
    channel: str
    name: str
    quantity: int


def doubles(connection: Connection) -> list[Double]:
    """The double sales, the newest first: those recorded as such, and the sales cancelled because their copies were
    sold already elsewhere. One for each order, cancelled or not: of a sale of more copies than were left, its double
    part only."""
    rows = connection.execute(
        select(sales.c.id, sales.c.created_at, channel_rows.c.name, items.items.c.name, sales.c.quantity)
        .join_from(sales, channel_rows, channel_rows.c.id == sales.c.channel_id)
        .join(items.items, items.items.c.id == sales.c.item_id)
        .where(
            or_(
                sales.c.double_sale,
                and_(sales.c.cancellation_cause == Cancellation.DOUBLE_SALE, sales.c.double_part_id.is_(None)),
            )
        )
        .order_by(sales.c.id.desc())
    )
    return [Double(*row) for row in rows]
