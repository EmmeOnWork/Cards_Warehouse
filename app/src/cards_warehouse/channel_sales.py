"""The sales made on a channel the app reads through its API, such as eBay: each line of an order is recorded as a sale
by itself, as one Manuel records by hand.

Of an order the app keeps only what a sale needs: who bought it, and where it goes, stay on the channel."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Column, Connection, DateTime, Integer, Table, Text, func, select
from sqlalchemy.dialects import postgresql

from cards_warehouse import channels, exposure, sales
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.channel_operations import ByChannel
from cards_warehouse.channel_queue import Line
from cards_warehouse.channels import channels as channel_rows
from cards_warehouse.database import metadata
from cards_warehouse.exposure import ChannelOperations, ChannelUnavailable, OperationRefused
from cards_warehouse.sales import Sale

# How late a channel may show an order after it was made: each read asks again for those of this long before the last.
LATE = timedelta(minutes=15)


@dataclass(frozen=True)
class Order:
    """A line of an order on a channel: copies of one of the app's listings, bought together."""

    # The order's number, as Manuel finds it in the channel's app.
    number: str
    # The line's own, which the channel never gives to another: one sale for each.
    line: str
    listing_id: int
    quantity: int
    # What the buyer paid for the copies, shipping apart.
    price_cents: int
    at: datetime


order_reads = Table(
    "order_reads",
    metadata,
    Column("channel_id", Integer, primary_key=True),
    Column("read_at", DateTime(timezone=True)),
    Column("failing_since", DateTime(timezone=True)),
    Column("problem", Text),
)


def read(connection: Connection, adapters: Mapping[str, ChannelOperations], now: datetime) -> None:
    """The orders of each channel set to act through its API, each a sale, with what it leaves to do on the other
    channels. Of the adapters, those that read orders: `orders(since)`, the lines of the orders made since then, or of
    all those the channel gives with no time. Each read asks for those made since the last one that worked, so the
    one after a read that failed finds what it missed. A read that fails is told on the home, until one works."""
    operations = ByChannel(adapters, now=lambda: now)
    for name, adapter in adapters.items():
        channel = channels.named(connection, name)
        if not channel.publishes_through_api or not hasattr(adapter, "orders"):
            continue
        try:
            orders = adapter.orders(since=_since(connection, channel.id))
        except ChannelUnavailable:
            silent = f"{name} non risponde: le vendite fatte lì arrivano da sole appena risponde."
            _failed(connection, channel.id, now, silent)
            continue
        except OperationRefused as refusal:
            _failed(connection, channel.id, now, str(refusal))
            continue
        for order in orders:
            # The channel gives an order again at the next reads: it is a sale already.
            if not sales.order_recorded(connection, channel.id, order.line):
                sales.record(connection, _sale(connection, channel, order), operations)
        _worked(connection, channel.id, now)


def summary(connection: Connection) -> Line | None:
    """The line of the home, in red: the channels whose orders the app cannot read, since when, and why. None when it
    reads them all."""
    failing = connection.execute(
        select(channel_rows.c.name, order_reads.c.failing_since, order_reads.c.problem)
        .join_from(order_reads, channel_rows, channel_rows.c.id == order_reads.c.channel_id)
        .where(order_reads.c.failing_since.is_not(None))
        .order_by(channel_rows.c.id)
    ).all()
    if not failing:
        return None
    said = [
        f"l'app non legge gli ordini di {name} dalle {since.astimezone(LOCAL_TIME):%H:%M del %d/%m}. {problem}"
        for name, since, problem in failing
    ]
    return Line(f"Attenzione: {' '.join(said)}", alarm=True)


def _since(connection: Connection, channel_id: int) -> datetime | None:
    """Since when to ask for the channel's orders: from the last read that worked, a little before. None before the
    first: all those the channel gives."""
    read_at = connection.execute(
        select(order_reads.c.read_at).where(order_reads.c.channel_id == channel_id)
    ).scalar_one_or_none()
    return None if read_at is None else read_at - LATE


def _sale(connection: Connection, channel: channels.Channel, order: Order) -> Sale:
    """The order's line as a sale: of the listing's item, on its channel, with the number of the order to find it."""
    return Sale(
        exposure.one(connection, order.listing_id).item_id,
        channel.id,
        order.quantity,
        order.price_cents,
        note=f"Ordine {channel.name} {order.number}",
        order_line=order.line,
        at=order.at,
    )


def _worked(connection: Connection, channel_id: int, now: datetime) -> None:
    """The read worked: the next starts from it, and nothing is wrong anymore."""
    worked = {"read_at": now, "failing_since": None, "problem": None}
    connection.execute(
        postgresql.insert(order_reads)
        .values(channel_id=channel_id, **worked)
        .on_conflict_do_update(index_elements=[order_reads.c.channel_id], set_=worked)
    )


def _failed(connection: Connection, channel_id: int, now: datetime, problem: str) -> None:
    """The read failed: since the first that did, with why the last one did."""
    connection.execute(
        postgresql.insert(order_reads)
        .values(channel_id=channel_id, failing_since=now, problem=problem)
        .on_conflict_do_update(
            index_elements=[order_reads.c.channel_id],
            set_={"failing_since": func.coalesce(order_reads.c.failing_since, now), "problem": problem},
        )
    )
