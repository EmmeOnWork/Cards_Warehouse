"""The queue of the channels the app acts on through their API: an update or a close the channel did not answer
waits here, and the worker asks it again once its wait is over.

One operation at most waits on a listing: a new one replaces it, and one done at once takes it away. Only the last
one asked is ever sent, so an old update never reaches the channel after a close."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Column, Connection, DateTime, Integer, Table, Text, delete, select
from sqlalchemy.dialects import postgresql

from cards_warehouse import exposure, manual_channels
from cards_warehouse.database import metadata
from cards_warehouse.exposure import ChannelOperations, ChannelUnavailable, Listing, OperationRefused, listings
from cards_warehouse.manual_channels import ActionKind

# How long an operation waits after the channel did not answer, try after try: 1, 2, 4, 8, 16 and 32 minutes, an
# hour in all, decided with Manuel. An outage of eBay rarely lasts longer, and a double sale should not wait more.
WAITS = [timedelta(minutes=2**each) for each in range(6)]


@dataclass(frozen=True)
class Waiting:
    """An operation waiting for its channel to answer."""

    kind: ActionKind
    listing: Listing
    retry_at: datetime


@dataclass(frozen=True)
class Line:
    """What the home says of the operations on the channels with an API."""

    text: str
    # Something left to Manuel: the home shows it in red.
    alarm: bool


queued_operations = Table(
    "queued_operations",
    metadata,
    Column("listing_id", Integer, primary_key=True),
    Column("kind", Text),
    Column("tries", Integer),
    Column("retry_at", DateTime(timezone=True)),
)


def attempt(
    connection: Connection, listing: Listing, kind: ActionKind, adapter: ChannelOperations, now: datetime
) -> bool:
    """The operation asked of the channel at once: True when it is done. When the channel does not answer, it waits in
    the queue, in place of the one waiting on the listing. When it refuses, it is Manuel's at once."""
    # Waits for the worker, when it is asking the channel about this listing now: this operation goes after.
    connection.execute(select(listings.c.id).where(listings.c.id == listing.id).with_for_update())
    try:
        done = _ask(adapter, kind, connection, listing)
    except ChannelUnavailable:
        _wait(connection, listing.id, kind, tries=1, now=now)
        return False
    except OperationRefused as refusal:
        return _leave_to_manuel(connection, listing, kind, _refused(listing, refusal))
    _forget(connection, listing.id)
    return done


def retry_next(connection: Connection, adapters: Mapping[str, ChannelOperations], now: datetime) -> bool:
    """The operation whose wait ended first, asked again of its channel: False when none is due. Not one the app is
    asking about now: it is left to the next time."""
    due = connection.execute(
        select(queued_operations.c.listing_id, queued_operations.c.kind, queued_operations.c.tries)
        .join_from(queued_operations, listings, listings.c.id == queued_operations.c.listing_id)
        .where(queued_operations.c.retry_at <= now)
        .order_by(queued_operations.c.retry_at)
        .limit(1)
        .with_for_update(of=listings, skip_locked=True)
    ).first()
    if due is None:
        return False
    listing, kind = exposure.one(connection, due.listing_id), ActionKind(due.kind)
    try:
        _ask(adapters[listing.channel], kind, connection, listing)
    except ChannelUnavailable:
        if due.tries == len(WAITS):
            _leave_to_manuel(connection, listing, kind, _silent(listing))
        else:
            _wait(connection, listing.id, kind, tries=due.tries + 1, now=now)
        return True
    except OperationRefused as refusal:
        _leave_to_manuel(connection, listing, kind, _refused(listing, refusal))
        return True
    _forget(connection, listing.id)
    if kind == ActionKind.UPDATE:
        exposure.updated(connection, listing.id)
    else:
        exposure.closed(connection, listing.id)
    return True


def summary(connection: Connection) -> Line | None:
    """The line of the home: in red, the operations left to Manuel on each channel since its API did not do them; then
    those waiting for the channel to answer. None when there are neither."""
    left = Counter(
        action.listing.channel
        for actions in manual_channels.pending(connection).values()
        for action in actions
        if action.listing.problem
    )
    waiting = Counter(operation.listing.channel for operation in pending(connection))
    said = [
        f"{_operations(count)} su {channel} non {'è riuscita' if count == 1 else 'sono riuscite'}, da fare a mano: "
        f"{'la' if count == 1 else 'le'} trovi in Da fare."
        for channel, count in left.items()
    ]
    said += [f"{_operations(count)} su {channel} in attesa di nuovo tentativo." for channel, count in waiting.items()]
    if not said:
        return None
    if left:
        return Line(f"Attenzione: {' '.join(said)}", alarm=True)
    return Line(" ".join(said), alarm=False)


def pending(connection: Connection) -> list[Waiting]:
    """Every operation waiting for its channel to answer."""
    return _read(connection)


def of_item(connection: Connection, item_id: int) -> list[Waiting]:
    """The operations waiting on the listings of the item."""
    return _read(connection, listings.c.item_id == item_id)


def _read(connection: Connection, *where) -> list[Waiting]:
    rows = connection.execute(
        select(queued_operations.c.listing_id, queued_operations.c.kind, queued_operations.c.retry_at)
        .join_from(queued_operations, listings, listings.c.id == queued_operations.c.listing_id)
        .where(*where)
        .order_by(listings.c.id)
    )
    return [Waiting(ActionKind(kind), exposure.one(connection, listing_id), at) for listing_id, kind, at in rows]


def _ask(adapter: ChannelOperations, kind: ActionKind, connection: Connection, listing: Listing) -> bool:
    if kind == ActionKind.UPDATE:
        return adapter.update(connection, listing)
    return adapter.close(connection, listing)


def _wait(connection: Connection, listing_id: int, kind: ActionKind, tries: int, now: datetime) -> None:
    values = {"kind": kind, "tries": tries, "retry_at": now + WAITS[tries - 1]}
    connection.execute(
        postgresql.insert(queued_operations)
        .values(listing_id=listing_id, **values)
        .on_conflict_do_update(index_elements=[queued_operations.c.listing_id], set_=values)
    )


def _leave_to_manuel(connection: Connection, listing: Listing, kind: ActionKind, problem: str) -> bool:
    """The operation out of the queue, and an action for Manuel, as on a manual channel, with why on the listing."""
    _forget(connection, listing.id)
    exposure.report_problem(connection, listing.id, problem)
    return _ask(manual_channels.MANUAL, kind, connection, listing)


def _silent(listing: Listing) -> str:
    return (
        f"{listing.channel} non ha risposto per un'ora: fallo a mano dall'app di {listing.channel}, "
        "poi spuntalo in Da fare."
    )


def _refused(listing: Listing, refusal: OperationRefused) -> str:
    return f"{refusal} Intanto fallo a mano dall'app di {listing.channel}, poi spuntalo in Da fare."


def _operations(count: int) -> str:
    return "1 operazione" if count == 1 else f"{count} operazioni"


def _forget(connection: Connection, listing_id: int) -> None:
    connection.execute(delete(queued_operations).where(queued_operations.c.listing_id == listing_id))
