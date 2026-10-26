"""Channels: the places where items are sold, each with the fee it keeps of a price. And the target margin the
prices are made from."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Boolean, Column, Connection, Integer, Numeric, Table, Text, select, update
from sqlalchemy.dialects import postgresql

from cards_warehouse import pricing, stock
from cards_warehouse.database import metadata
from cards_warehouse.pricing import FeeRule


@dataclass(frozen=True)
class Channel:
    id: int
    name: str
    fee: FeeRule
    # Whether a listing there offers several copies, or one copy and closes when it is sold.
    multi_copy_listings: bool


@dataclass(frozen=True)
class Proposal:
    """The price proposed on each channel for an item, and what it is made from."""

    cost_cents: int
    margin_percent: Decimal
    net_cents: int
    prices: list[tuple[str, int]]


channels = Table(
    "channels",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text),
    Column("fee_percent", Numeric),
    Column("fee_fixed_cents", Integer),
    Column("multi_copy_listings", Boolean),
)

settings = Table(
    "settings", metadata, Column("id", Integer, primary_key=True), Column("target_margin_percent", Numeric)
)


def every(connection: Connection) -> list[Channel]:
    """Every channel, in the order they were added."""
    return [_channel(row) for row in connection.execute(select(channels).order_by(channels.c.id))]


def one(connection: Connection, channel_id: int) -> Channel | None:
    row = connection.execute(select(channels).where(channels.c.id == channel_id)).one_or_none()
    return None if row is None else _channel(row)


def add(connection: Connection, name: str, fee: FeeRule, multi_copy_listings: bool) -> int | None:
    """A manual channel: the app says what to publish there, and Manuel does it. None when the name is taken."""
    return connection.execute(
        postgresql.insert(channels)
        .values(
            name=name,
            fee_percent=fee.percent,
            fee_fixed_cents=fee.fixed_cents,
            multi_copy_listings=multi_copy_listings,
        )
        .on_conflict_do_nothing(index_elements=[channels.c.name])
        .returning(channels.c.id)
    ).scalar_one_or_none()


def change_fee(connection: Connection, channel_id: int, fee: FeeRule) -> None:
    connection.execute(
        update(channels)
        .where(channels.c.id == channel_id)
        .values(fee_percent=fee.percent, fee_fixed_cents=fee.fixed_cents)
    )


def target_margin(connection: Connection) -> Decimal:
    """The margin on the cost every price is made to leave: one setting for all the channels."""
    return connection.execute(select(settings.c.target_margin_percent)).scalar_one()


def change_target_margin(connection: Connection, percent: Decimal) -> None:
    connection.execute(update(settings).values(target_margin_percent=percent))


def proposal(connection: Connection, item_id: int) -> Proposal | None:
    """The price that leaves the target net on each channel. None when the item's cost is not known: with no cost
    there is no target net, and any price would be a guess."""
    cost = stock.cost_to_cover(connection, item_id)
    if cost is None:
        return None
    margin = target_margin(connection)
    net = pricing.target_net(cost, margin)
    prices = [(channel.name, pricing.channel_price(net, channel.fee)) for channel in every(connection)]
    return Proposal(cost, margin, net, prices)


def _channel(row) -> Channel:
    return Channel(row.id, row.name, FeeRule(row.fee_percent, row.fee_fixed_cents), row.multi_copy_listings)
