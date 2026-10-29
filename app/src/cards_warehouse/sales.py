"""Sales: copies of an item sold on a channel at a real price. A sale takes its copies from the stock, tells the
exposure what that leaves to do on the channels, and keeps the real margin it left."""

from dataclasses import dataclass

from sqlalchemy import Column, Connection, DateTime, Integer, Table, Text, insert, select

from cards_warehouse import channels, exposure, pricing, stock
from cards_warehouse.channels import channels as channel_rows
from cards_warehouse.database import metadata
from cards_warehouse.exposure import ChannelOperations
from cards_warehouse.pricing import Margin
from cards_warehouse.stock import Cause


class NotEnoughCopies(Exception):
    """More copies sold than the item has left, or than the lot chosen has: the stock would go below zero."""

    def __init__(self, available: int) -> None:
        super().__init__(f"{available} copies left")
        self.available = available


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
)


def record(connection: Connection, sale: Sale, operations: ChannelOperations) -> int:
    """The sale, with its copies taken from the stock and what it leaves to do on the listings of the item, done
    through `operations`. NotEnoughCopies when the item, or the lot chosen, has fewer: nothing is taken."""
    channel = channels.one(connection, sale.channel_id)
    fee = pricing.fee(sale.price_cents, channel.fee) if sale.fee_cents is None else sale.fee_cents
    taken = _taken(connection, sale)
    # The cost of the copies, lot by lot: with the grading in it, for a graded card. Not known if one is not.
    costs = [None if lot.unit_cost_cents is None else lot.unit_cost_cents * copies for lot, copies in taken]
    cost = None if None in costs else sum(costs)
    sale_id = connection.execute(
        insert(sales)
        .values(
            item_id=sale.item_id,
            channel_id=sale.channel_id,
            quantity=sale.quantity,
            price_cents=sale.price_cents,
            fee_cents=fee,
            shipping_cents=sale.shipping_cents,
            cost_cents=cost,
            note=sale.note,
        )
        .returning(sales.c.id)
    ).scalar_one()
    for lot, copies in taken:
        stock.unload(connection, lot.id, copies, Cause.SALE, sale_id=sale_id)
    exposure.sold(connection, sale.item_id, sale.channel_id, sale.quantity, operations)
    return sale_id


def _taken(connection: Connection, sale: Sale) -> list[tuple[stock.Lot, int]]:
    """The lots the copies sold come from, and how many from each: the one Manuel chose, or else the oldest first,
    until they are all taken."""
    lots = stock.lots(connection, sale.item_id)
    if sale.lot_id is not None:
        lots = [lot for lot in lots if lot.id == sale.lot_id]
    taken, left = [], sale.quantity
    for lot in lots:
        copies = min(lot.available, left)
        if copies:
            taken.append((lot, copies))
            left -= copies
    if left:
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
    )
