"""The manual channels, such as Vinted and Tilt: they have no API the app can use, so the app acts on them through
Manuel. What it would do there becomes an action for him, with what he needs to do it."""

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Column, Connection, DateTime, Integer, Table, Text, func, insert, select, update

from cards_warehouse import channels, exposure
from cards_warehouse.database import metadata
from cards_warehouse.exposure import Listing


class ActionKind(StrEnum):
    PUBLISH = "publish"


@dataclass(frozen=True)
class Action:
    id: int
    kind: ActionKind
    listing: Listing


pending_actions = Table(
    "pending_actions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("listing_id", Integer),
    Column("kind", Text),
    Column("done_at", DateTime(timezone=True)),
)


class ManualChannel:
    """The operations of a channel, done by Manuel."""

    def publish(self, connection: Connection, listing: Listing) -> None:
        """An action to publish the listing: the link comes when Manuel has done it."""
        connection.execute(insert(pending_actions).values(listing_id=listing.id, kind=ActionKind.PUBLISH))


MANUAL = ManualChannel()


def done(connection: Connection, action_id: int, link: str) -> None:
    """Manuel did the action: it leaves the list. Done to publish, the listing is active at the link he pasted."""
    listing_id = connection.execute(
        update(pending_actions)
        .where(pending_actions.c.id == action_id)
        .values(done_at=func.now())
        .returning(pending_actions.c.listing_id)
    ).scalar_one()
    exposure.activate(connection, listing_id, link)


def pending(connection: Connection) -> dict[str, list[Action]]:
    """The actions left to do, by channel in the channels' order, the oldest first."""
    actions = _read(connection)
    by_channel = {}
    for channel in channels.every(connection):
        if on_channel := [action for action in actions if action.listing.channel == channel.name]:
            by_channel[channel.name] = on_channel
    return by_channel


def action(connection: Connection, action_id: int) -> Action | None:
    """The action, while it is left to do."""
    return next(iter(_read(connection, pending_actions.c.id == action_id)), None)


def _read(connection: Connection, *where) -> list[Action]:
    rows = connection.execute(
        select(pending_actions.c.id, pending_actions.c.kind, pending_actions.c.listing_id)
        .where(pending_actions.c.done_at.is_(None), *where)
        .order_by(pending_actions.c.id)
    )
    return [Action(id, ActionKind(kind), exposure.one(connection, listing_id)) for id, kind, listing_id in rows]
