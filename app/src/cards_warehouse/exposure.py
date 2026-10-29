"""Exposure: where each item is offered, at what price and with how many copies. It owns the listings and their
state, and tells each channel what to do with them through the channel's operations."""

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from sqlalchemy import Column, Connection, Integer, Table, Text, select, text, update
from sqlalchemy.dialects import postgresql

from cards_warehouse import channels, stock
from cards_warehouse.channels import channels as channel_rows
from cards_warehouse.database import metadata


class Status(StrEnum):
    # Not on the channel yet.
    TO_PUBLISH = "to_publish"
    # On the channel, at its link.
    ACTIVE = "active"
    # On the channel, which still shows a price or copies the listing no longer has.
    TO_UPDATE = "to_update"
    # On the channel, which still offers what is no longer there.
    TO_CLOSE = "to_close"
    # Off the channel: it offers nothing anymore.
    CLOSED = "closed"


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
    # Why the channel refused it the last time it was asked, for Manuel to read. None when it did not.
    problem: str | None = None


class NothingToSell(Exception):
    """The item has no copies left: a listing would offer what is not there."""


class NoPrice(Exception):
    """The item's cost is not known and no price is fixed on it: any price would be a guess."""


class PublishRefused(Exception):
    """The channel did not take the listing. The message says why, for Manuel, and what to do about it."""


class ChannelOperations(Protocol):
    """What the app asks of a channel: the same of a manual one, which leaves it to Manuel, and of one the app
    acts on through its API. The rest of the app does not know which one it asks."""

    def publish(self, connection: Connection, listing: Listing) -> str | None:
        """Offers the listing on its channel: its link when it is there at once, None when the link comes later.
        PublishRefused when the channel does not take it."""

    def update(self, connection: Connection, listing: Listing) -> bool:
        """Brings the listing on its channel to its price and copies: True when it is done at once, False when
        later."""

    def close(self, connection: Connection, listing: Listing) -> bool:
        """Takes the listing off its channel: True when it is done at once, False when later."""


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
    Column("problem", Text),
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
        if channel.id in channel_ids:
            quantity = _offered(channel, available)
            _list(connection, item_id, channel.id, prices[channel.name], quantity, operations)


def _offered(channel: channels.Channel, left: int) -> int:
    """The copies a listing offers on the channel: those left where it has several, one where it is one copy, as on
    Vinted."""
    return left if channel.multi_copy_listings else 1


def _list(
    connection: Connection,
    item_id: int,
    channel_id: int,
    price_cents: int,
    quantity: int,
    operations: ChannelOperations,
) -> None:
    """A new listing of the item on the channel, published through `operations`. Unless the item is listed there
    already: a second listing would offer its copies twice."""
    listing_id = connection.execute(
        postgresql.insert(listings)
        .values(
            item_id=item_id, channel_id=channel_id, status=Status.TO_PUBLISH, price_cents=price_cents, quantity=quantity
        )
        .on_conflict_do_nothing(
            index_elements=[listings.c.item_id, listings.c.channel_id], index_where=text("status <> 'closed'")
        )
        .returning(listings.c.id)
    ).scalar_one_or_none()
    if listing_id is not None:
        _publish(connection, listing_id, operations)


def publish_again(connection: Connection, listing_id: int, operations: ChannelOperations) -> None:
    """The channel asked again for a listing it refused. A listing already on its channel is left as it is."""
    listing = one(connection, listing_id)
    if listing is not None and listing.status == Status.TO_PUBLISH:
        _publish(connection, listing_id, operations)


def _publish(connection: Connection, listing_id: int, operations: ChannelOperations) -> None:
    """A refusal stays on the listing, still to publish: it does not undo the listings on the other channels."""
    try:
        link = operations.publish(connection, one(connection, listing_id))
    except PublishRefused as refusal:
        connection.execute(update(listings).where(listings.c.id == listing_id).values(problem=str(refusal)))
        return
    if link is not None:
        activate(connection, listing_id, link)


def sold(connection: Connection, item_id: int, channel_id: int, quantity: int, operations: ChannelOperations) -> None:
    """Copies of the item sold on a channel, after they left the stock. That channel took them off its listing by
    itself, if the listing was there. Elsewhere no listing offers more copies than are left."""
    left = stock.available(connection, item_id)
    sold_on = channels.one(connection, channel_id)
    for listing in of_item(connection, item_id):
        if listing.channel != sold_on.name or listing.status == Status.TO_PUBLISH:
            if listing.quantity > left:
                _cut(connection, listing, left, operations)
        elif listing.quantity > quantity:
            _set(connection, listing.id, quantity=listing.quantity - quantity)
        else:
            _set(connection, listing.id, status=Status.CLOSED)
            # Where a listing is one copy, as on Vinted, the next copy needs a listing of its own.
            if not sold_on.multi_copy_listings and left:
                _list(connection, item_id, channel_id, listing.price_cents, 1, operations)


def _cut(connection: Connection, listing: Listing, left: int, operations: ChannelOperations) -> None:
    """The listing down to the copies left on its channel, or off it when none is."""
    if left == 0:
        _close(connection, listing, operations)
    else:
        _change(connection, listing, operations, quantity=left)


def withdraw(connection: Connection, listing_id: int, operations: ChannelOperations) -> None:
    """The item off the listing's channel, by Manuel's choice: its listings on the other channels stay as they are."""
    _close(connection, one(connection, listing_id), operations)


def _close(connection: Connection, listing: Listing, operations: ChannelOperations) -> None:
    closed = operations.close(connection, listing)
    _set(connection, listing.id, status=Status.CLOSED if closed else Status.TO_CLOSE)


def align(connection: Connection, item_id: int, operations: ChannelOperations) -> None:
    """The listings of the item follow its prices and its stock: each one whose price changed is brought to the new
    one. Where a listing offers several copies it offers those left, more or fewer; where it is one copy, as on
    Vinted, it stays one. With none left, each is closed. One to close already, sold out or withdrawn, stays so.
    With no price left to make, the cost not known and none fixed, each keeps its own."""
    proposal = channels.proposal(connection, item_id)
    prices = {} if proposal is None else dict(proposal.prices)
    by_name = {channel.name: channel for channel in channels.every(connection)}
    left = stock.available(connection, item_id)
    for listing in of_item(connection, item_id):
        if listing.status == Status.TO_CLOSE:
            continue
        if left == 0:
            _close(connection, listing, operations)
            continue
        changed = {}
        price = prices.get(listing.channel, listing.price_cents)
        if price != listing.price_cents:
            changed["price_cents"] = price
        quantity = _offered(by_name[listing.channel], left)
        if quantity != listing.quantity:
            changed["quantity"] = quantity
        if changed:
            _change(connection, listing, operations, **changed)


def align_every(connection: Connection, operations: ChannelOperations) -> None:
    """The listings of every item on sale follow its prices: after a change made for all of them, such as the target
    margin or a channel's fee."""
    on_sale = (
        select(listings.c.item_id).where(listings.c.status != Status.CLOSED).distinct().order_by(listings.c.item_id)
    )
    for item_id in connection.execute(on_sale).scalars().all():
        align(connection, item_id, operations)


def _change(connection: Connection, listing: Listing, operations: ChannelOperations, **values) -> None:
    """The listing at its new price or copies, and its channel asked to show them. One not on its channel yet will be
    published with them."""
    if listing.status == Status.TO_PUBLISH:
        _set(connection, listing.id, **values)
        return
    _set(connection, listing.id, status=Status.TO_UPDATE, **values)
    if operations.update(connection, one(connection, listing.id)):
        _set(connection, listing.id, status=Status.ACTIVE)


def _set(connection: Connection, listing_id: int, **values) -> None:
    connection.execute(update(listings).where(listings.c.id == listing_id).values(**values))


def activate(connection: Connection, listing_id: int, link: str) -> None:
    """The listing is on its channel, at that link."""
    connection.execute(
        update(listings).where(listings.c.id == listing_id).values(status=Status.ACTIVE, link=link, problem=None)
    )


def updated(connection: Connection, listing_id: int) -> None:
    """The listing on its channel has its price and copies: it is active as it is."""
    _set(connection, listing_id, status=Status.ACTIVE)


def closed(connection: Connection, listing_id: int) -> None:
    """The listing is off its channel."""
    _set(connection, listing_id, status=Status.CLOSED)


def one(connection: Connection, listing_id: int) -> Listing | None:
    return next(iter(_read(connection, listings.c.id == listing_id)), None)


def of_item(connection: Connection, item_id: int) -> list[Listing]:
    """The listings of the item, in the order of their channels. Those closed are left out: they offer nothing."""
    return _read(connection, listings.c.item_id == item_id, listings.c.status != Status.CLOSED)


def _read(connection: Connection, *where) -> list[Listing]:
    rows = connection.execute(
        select(listings, channel_rows.c.name.label("channel"))
        .join_from(listings, channel_rows, channel_rows.c.id == listings.c.channel_id)
        .where(*where)
        .order_by(channel_rows.c.id)
    )
    return [
        Listing(
            row.id, row.item_id, row.channel, Status(row.status), row.price_cents, row.quantity, row.link, row.problem
        )
        for row in rows
    ]
