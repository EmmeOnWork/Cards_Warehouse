"""The daily check: what is out of line between the stock, the listings and the actions, found once a day and left
for the app to show. A CronJob of Kubernetes runs it from the app's image (chart/templates/daily-check.yaml)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import TypeAdapter
from sqlalchemy import Column, Connection, DateTime, Integer, Table, func, insert, select, update
from sqlalchemy.dialects import postgresql

from cards_warehouse import exposure, items, manual_channels, stock
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.channels import channels as channel_rows
from cards_warehouse.database import create_database_engine, metadata
from cards_warehouse.exposure import Status, listings
from cards_warehouse.items import Kind
from cards_warehouse.items import items as item_rows
from cards_warehouse.manual_channels import ActionKind
from cards_warehouse.stock import Cause, stock_lots, stock_movements


@dataclass(frozen=True)
class OverOffered:
    """A listing offering more copies than are left: a buyer could pay for one that is not there."""

    item_id: int
    item: str
    channel: str
    offered: int
    available: int


@dataclass(frozen=True)
class OpenOnSoldOut:
    """A listing still open on an item with no copy left: active, a buyer could pay for nothing; to publish, Manuel
    would offer it."""

    item_id: int
    item: str
    channel: str
    status: Status


@dataclass(frozen=True)
class StaleAction:
    """An action left to Manuel for longer than the threshold: forgotten, most likely."""

    action_id: int
    kind: ActionKind
    item_id: int
    item: str
    channel: str
    since: datetime


@dataclass(frozen=True)
class UnsoldItem:
    """An item with no sale for longer than the threshold: its price is to review."""

    item_id: int
    item: str
    since: datetime
    # The price of each listing, by its channel: none when the item is on sale nowhere.
    prices: list[tuple[str, int]]


@dataclass(frozen=True)
class Outcome:
    ran_at: datetime
    over_offered: list[OverOffered]
    open_on_sold_out: list[OpenOnSoldOut]
    stale_actions: list[StaleAction]
    unsold_items: list[UnsoldItem]


@dataclass(frozen=True)
class Thresholds:
    """How long, in whole days, before the check finds something standing still."""

    stale_action_days: int
    unsold_item_days: int


# The thresholds are settings of the app, kept with the target margin (channels.py).
_settings = Table(
    "settings",
    metadata,
    Column("stale_action_days", Integer),
    Column("unsold_item_days", Integer),
    extend_existing=True,
)

daily_checks = Table(
    "daily_checks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("ran_at", DateTime(timezone=True)),
    Column("outcome", postgresql.JSONB),
)

# An outcome as JSON, and back: its dates, enums and tuples as they were.
_as_json = TypeAdapter(Outcome)

# The listings that are, or are about to be, on their channel.
_OPEN = (Status.TO_PUBLISH, Status.ACTIVE)

# The CronJob runs once a day: an older last check means a day went by without one.
MAX_AGE = timedelta(days=1)


def thresholds(connection: Connection) -> Thresholds:
    return Thresholds(*connection.execute(select(_settings.c.stale_action_days, _settings.c.unsold_item_days)).one())


def change_thresholds(connection: Connection, days: Thresholds) -> None:
    connection.execute(
        update(_settings).values(stale_action_days=days.stale_action_days, unsold_item_days=days.unsold_item_days)
    )


def run(connection: Connection, now: datetime) -> Outcome:
    """What is out of line at `now`, kept as the last outcome."""
    over_offered, open_on_sold_out = [], []
    for item_id, item, channel, status, offered, available in _open_listings(connection):
        if available == 0:
            open_on_sold_out.append(OpenOnSoldOut(item_id, item, channel, Status(status)))
        elif offered > available:
            # A sum of sums: PostgreSQL gives it as a numeric.
            over_offered.append(OverOffered(item_id, item, channel, offered, int(available)))
    days = thresholds(connection)
    outcome = Outcome(
        now,
        over_offered,
        open_on_sold_out,
        _stale_actions(connection, now - timedelta(days=days.stale_action_days)),
        _unsold_items(connection, now - timedelta(days=days.unsold_item_days)),
    )
    connection.execute(insert(daily_checks).values(ran_at=now, outcome=_as_json.dump_python(outcome, mode="json")))
    return outcome


@dataclass(frozen=True)
class Line:
    """What a page says of the check."""

    text: str
    # Something to look at: the page shows it in red.
    alarm: bool = True


def freshness(last: Outcome | None, now: datetime) -> Line:
    """Whether the last check is recent, as its page says it."""
    if last is None:
        return Line("Attenzione: nessun controllo finora.")
    if now - last.ran_at > MAX_AGE:
        return Line(f"Attenzione: nessun controllo da più di un giorno. L'ultimo è del {_when(last)}.")
    return Line(f"Ultimo controllo: {_when(last)}.", alarm=False)


def summary(last: Outcome | None, now: datetime) -> Line:
    """The last check in a line, as the home says it: missing, or what it found."""
    fresh = freshness(last, now)
    if fresh.alarm:
        return fresh
    found = sum(len(each) for each in (last.over_offered, last.open_on_sold_out, last.stale_actions, last.unsold_items))
    if found:
        things = "1 cosa" if found == 1 else f"{found} cose"
        return Line(f"Attenzione: il controllo del {_when(last)} ha trovato {things} da guardare.")
    return Line(f"Controllo del {_when(last)}: tutto in ordine.", alarm=False)


def _when(last: Outcome) -> str:
    return f"{last.ran_at.astimezone(LOCAL_TIME):%d/%m alle %H:%M}"


def last(connection: Connection) -> Outcome | None:
    """The outcome of the last check, as it was. None before the first."""
    kept = connection.execute(
        select(daily_checks.c.outcome).order_by(daily_checks.c.ran_at.desc(), daily_checks.c.id.desc()).limit(1)
    ).scalar_one_or_none()
    return None if kept is None else _as_json.validate_python(kept)


def _stale_actions(connection: Connection, made_before: datetime) -> list[StaleAction]:
    """The actions left to do, made before that time, as the list of actions orders them."""
    return [
        StaleAction(
            action.id,
            action.kind,
            action.listing.item_id,
            items.get(connection, action.listing.item_id).name,
            action.listing.channel,
            action.created_at,
        )
        for actions in manual_channels.pending(connection).values()
        for action in actions
        if action.created_at < made_before
    ]


def _unsold_items(connection: Connection, standing_before: datetime) -> list[UnsoldItem]:
    """The items with copies left that stand since before that time, the longest first: since their last sale, or
    else since they came in. Not the bulk, which waits for a sale in lots."""
    last_sale = func.max(stock_movements.c.created_at).filter(stock_movements.c.cause == Cause.SALE)
    since = func.coalesce(last_sale, func.min(stock_movements.c.created_at))
    rows = connection.execute(
        select(item_rows.c.id, item_rows.c.name, since)
        .join_from(item_rows, stock_lots, stock_lots.c.item_id == item_rows.c.id)
        .join(stock_movements, stock_movements.c.lot_id == stock_lots.c.id)
        .where(item_rows.c.kind != Kind.BULK)
        .group_by(item_rows.c.id)
        .having(func.sum(stock_movements.c.change) > 0, since < standing_before)
        .order_by(since, item_rows.c.id)
    )
    return [
        UnsoldItem(
            item_id,
            item,
            standing_since,
            [
                (listing.channel, listing.price_cents)
                for listing in exposure.of_item(connection, item_id)
                if listing.status in _OPEN
            ],
        )
        for item_id, item, standing_since in rows
    ]


def _open_listings(connection: Connection):
    """Each listing to publish or active, with its item's name and the copies it has left: by item, in the order of
    the channels."""
    stock_of = stock.of_items()
    return connection.execute(
        select(
            listings.c.item_id,
            item_rows.c.name,
            channel_rows.c.name,
            listings.c.status,
            listings.c.quantity,
            stock_of.c.available,
        )
        .join_from(listings, item_rows, item_rows.c.id == listings.c.item_id)
        .join(channel_rows, channel_rows.c.id == listings.c.channel_id)
        .join(stock_of, stock_of.c.item_id == listings.c.item_id)
        .where(listings.c.status.in_(_OPEN))
        .order_by(listings.c.item_id, channel_rows.c.id)
    )


if __name__ == "__main__":
    # What the CronJob runs. Something found is not a failure: the Job succeeds, and its log says the home's line.
    # A database that does not answer fails it, and Kubernetes tries again.
    with create_database_engine().begin() as connection:
        found = run(connection, datetime.now(UTC))
    print(summary(found, found.ran_at).text)
