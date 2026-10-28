"""Exposure: where each item is offered, at what price and with how many copies. It owns the listings and their
state, and tells each channel what to do with them through the channel's operations."""

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from sqlalchemy import Column, Connection, Integer, Table, Text, select, update
from sqlalchemy.dialects import postgresql

from cards_warehouse import channels, stock
from cards_warehouse.channels import channels as channel_rows
from cards_warehouse.database import metadata


class Status(StrEnum):
    # Not on the channel yet.
    TO_PUBLISH = "to_publish"
    # On the channel, at its link.
    ACTIVE = "active"


@dataclass(frozen=True)
class Listing:
    id: int
    item_id: int
    channel: str
    status: Status
    price_cents: int
    quantity: int
    # Where the listing is on the channel: None until it is there.
    link: str | None


class NothingToSell(Exception):
    """The item has no copies left: a listing would offer what is not there."""


class NoPrice(Exception):
    """The item's cost is not known and no price is fixed on it: any price would be a guess."""


class ChannelOperations(Protocol):
    """What the app asks of a channel: the same of a manual one, which leaves it to Manuel, and of one the app
    acts on through its API. The rest of the app does not know which one it asks."""

    def publish(self, connection: Connection, listing: Listing) -> str | None:
        """Offers the listing on its channel: its link when it is there at once, None when the link comes later."""


listings = Table(
    "listings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("item_id", Integer),
    Column("channel_id", Integer),
    Column("status", Text),
    Column("price_cents", Integer),
    Column("quantity", Integer),
    Column("link", Text),
)


def put_on_sale(
    connection: Connection, item_id: int, channel_ids: Collection[int], operations: ChannelOperations
) -> None:
    """A listing of the item on each channel chosen, at the price proposed there, published through `operations`.
    A channel where the item is listed already is left as it is. NothingToSell when no copy is left, NoPrice when
    the item has no price: nothing is offered anywhere."""
    available = stock.available(connection, item_id)
    if available < 1:
        raise NothingToSell(item_id)
    proposal = channels.proposal(connection, item_id)
    if proposal is None:
        raise NoPrice(item_id)
    prices = dict(proposal.prices)
    for channel in channels.every(connection):
        if channel.id not in channel_ids:
            continue
        listing_id = connection.execute(
            postgresql.insert(listings)
            .values(
                item_id=item_id,
                channel_id=channel.id,
                status=Status.TO_PUBLISH,
                price_cents=prices[channel.name],
                quantity=available if channel.multi_copy_listings else 1,
            )
            .on_conflict_do_nothing(index_elements=[listings.c.item_id, listings.c.channel_id])
            .returning(listings.c.id)
        ).scalar_one_or_none()
        if listing_id is None:
            continue
        link = operations.publish(connection, one(connection, listing_id))
        if link is not None:
            activate(connection, listing_id, link)


def activate(connection: Connection, listing_id: int, link: str) -> None:
    """The listing is on its channel, at that link."""
    connection.execute(update(listings).where(listings.c.id == listing_id).values(status=Status.ACTIVE, link=link))


def one(connection: Connection, listing_id: int) -> Listing | None:
    return next(iter(_read(connection, listings.c.id == listing_id)), None)


def of_item(connection: Connection, item_id: int) -> list[Listing]:
    """The listings of the item, in the order of their channels."""
    return _read(connection, listings.c.item_id == item_id)


def _read(connection: Connection, *where) -> list[Listing]:
    rows = connection.execute(
        select(listings, channel_rows.c.name.label("channel"))
        .join_from(listings, channel_rows, channel_rows.c.id == listings.c.channel_id)
        .where(*where)
        .order_by(channel_rows.c.id)
    )
    return [
        Listing(row.id, row.item_id, row.channel, Status(row.status), row.price_cents, row.quantity, row.link)
        for row in rows
    ]
