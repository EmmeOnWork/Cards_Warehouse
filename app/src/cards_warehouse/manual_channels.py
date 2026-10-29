"""The manual channels, such as Vinted and Tilt: they have no API the app can use, so the app acts on them through
Manuel. What it would do there becomes an action for him, with what he needs to do it."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Column, Connection, DateTime, Integer, Table, Text, delete, func, insert, select, update

from cards_warehouse import channels, exposure
from cards_warehouse.database import metadata
from cards_warehouse.exposure import Listing, Status


class ActionKind(StrEnum):
    PUBLISH = "publish"
    # To bring the listing on the channel to the price and the copies it has now.
    UPDATE = "update"
    # To take the listing off the channel.
    CLOSE = "close"


@dataclass(frozen=True)
class Action:
    id: int
    kind: ActionKind
    listing: Listing
    # When the app left it to Manuel.
    created_at: datetime


pending_actions = Table(
    "pending_actions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("listing_id", Integer),
    Column("kind", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("done_at", DateTime(timezone=True)),
)


class ManualChannel:
    """The operations of a channel, done by Manuel."""

    def publish(self, connection: Connection, listing: Listing) -> None:
        """An action to publish the listing: the link comes when Manuel has done it."""
        connection.execute(insert(pending_actions).values(listing_id=listing.id, kind=ActionKind.PUBLISH))

    def update(self, connection: Connection, listing: Listing) -> bool:
        """An action to bring the listing to its price and copies: it is done when Manuel has done it."""
        _leave(connection, listing, ActionKind.UPDATE)
        return False

    def close(self, connection: Connection, listing: Listing) -> bool:
        """An action to take the listing off the channel: it is closed when Manuel has done it. A listing he has not
        published yet is closed at once: its action to publish goes, with nothing left to publish."""
        if listing.status == Status.TO_PUBLISH:
            connection.execute(
                delete(pending_actions).where(
                    pending_actions.c.listing_id == listing.id, pending_actions.c.done_at.is_(None)
                )
            )
            return True
        _leave(connection, listing, ActionKind.CLOSE)
        return False


MANUAL = ManualChannel()


def _leave(connection: Connection, listing: Listing, kind: ActionKind) -> None:
    """The action left to do on the listing, one at most: a change before Manuel did the one there turns it into this,
    and he does only what is left. The listing shows the price and the copies of the last change."""
    turned = connection.execute(
        update(pending_actions)
        .where(pending_actions.c.listing_id == listing.id, pending_actions.c.done_at.is_(None))
        .values(kind=kind)
        .returning(pending_actions.c.id)
    ).first()
    if turned is None:
        connection.execute(insert(pending_actions).values(listing_id=listing.id, kind=kind))


def done(connection: Connection, action_id: int, link: str | None = None) -> None:
    """Manuel did the action: it leaves the list. Done to publish, the listing is active at the link he pasted; done
    to update, it is active as it is; done to close, it is off its channel."""
    listing_id, kind = connection.execute(
        update(pending_actions)
        .where(pending_actions.c.id == action_id)
        .values(done_at=func.now())
        .returning(pending_actions.c.listing_id, pending_actions.c.kind)
    ).one()
    if kind == ActionKind.PUBLISH:
        exposure.activate(connection, listing_id, link)
    elif kind == ActionKind.UPDATE:
        exposure.updated(connection, listing_id)
    else:
        exposure.closed(connection, listing_id)


def pending(connection: Connection) -> dict[str, list[Action]]:
    """The actions left to do, by channel in the channels' order, the oldest first."""
    actions = _read(connection)
    by_channel = {}
    for channel in channels.every(connection):
        if on_channel := [action for action in actions if action.listing.channel == channel.name]:
            by_channel[channel.name] = on_channel
    return by_channel


def of_item(connection: Connection, item_id: int) -> list[Action]:
    """The actions left to do on the listings of the item, in the channels' order."""
    return [
        action for actions in pending(connection).values() for action in actions if action.listing.item_id == item_id
    ]


def action(connection: Connection, action_id: int) -> Action | None:
    """The action, while it is left to do."""
    return next(iter(_read(connection, pending_actions.c.id == action_id)), None)


def _read(connection: Connection, *where) -> list[Action]:
    """The actions left to do. Not one on a listing its channel closed by itself, as with its last copy sold there:
    there is nothing left to do on it."""
    rows = connection.execute(
        select(pending_actions.c.id, pending_actions.c.kind, pending_actions.c.listing_id, pending_actions.c.created_at)
        .join_from(pending_actions, exposure.listings, exposure.listings.c.id == pending_actions.c.listing_id)
        .where(pending_actions.c.done_at.is_(None), exposure.listings.c.status != Status.CLOSED, *where)
        .order_by(pending_actions.c.id)
    )
    return [
        Action(id, ActionKind(kind), exposure.one(connection, listing_id), created_at)
        for id, kind, listing_id, created_at in rows
    ]
