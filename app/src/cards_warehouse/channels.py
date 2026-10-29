"""Channels: the places where items are sold, each with the fee it keeps of a price. And the target margin the
prices are made from."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Boolean, Column, Connection, Integer, Numeric, Table, Text, func, select, update
from sqlalchemy.dialects import postgresql

from cards_warehouse import items, pricing, stock
from cards_warehouse.database import metadata
from cards_warehouse.pricing import FeeRule, Margin, MarginWarning


@dataclass(frozen=True)
class Channel:
    id: int
    name: str
    fee: FeeRule
    # Whether a listing there offers several copies, or one copy and closes when it is sold.
    multi_copy_listings: bool
    # How many characters a title can have there. None when the channel sets no limit.
    title_limit: int | None = None
    # The app publishes there by itself, through the channel's API, instead of leaving actions to Manuel.
    publishes_through_api: bool = False


@dataclass(frozen=True)
class ChannelPrice:
    channel: str
    price_cents: int
    # None when the cost is not known: no margin can be told, and none warned of.
    margin: Margin | None
    warning: MarginWarning | None
    # Manuel forced it on this channel, over the price of the others.
    forced: bool = False


@dataclass(frozen=True)
class Proposal:
    """The price of an item on each channel, what it is made from, and the margin it leaves."""

    # None when not known, and the target net with it: the price is the one Manuel fixed.
    cost_cents: int | None
    margin_percent: Decimal
    net_cents: int | None
    # The price Manuel fixed, in place of the one made from the target. None when he fixed none.
    fixed_price_cents: int | None
    per_channel: list[ChannelPrice]

    @property
    def prices(self) -> list[tuple[str, int]]:
        """The price on each channel, by its name."""
        return [(row.channel, row.price_cents) for row in self.per_channel]


channels = Table(
    "channels",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text),
    Column("fee_percent", Numeric),
    Column("fee_fixed_cents", Integer),
    Column("multi_copy_listings", Boolean),
    Column("title_limit", Integer),
    Column("publishes_through_api", Boolean),
)

settings = Table(
    "settings", metadata, Column("id", Integer, primary_key=True), Column("target_margin_percent", Numeric)
)

forced_prices = Table(
    "forced_prices",
    metadata,
    Column("item_id", Integer, primary_key=True),
    Column("channel_id", Integer, primary_key=True),
    Column("price_cents", Integer),
)


def every(connection: Connection) -> list[Channel]:
    """Every channel, in the order they were added."""
    return [_channel(row) for row in connection.execute(select(channels).order_by(channels.c.id))]


def one(connection: Connection, channel_id: int) -> Channel | None:
    row = connection.execute(select(channels).where(channels.c.id == channel_id)).one_or_none()
    return None if row is None else _channel(row)


def add(
    connection: Connection, name: str, fee: FeeRule, multi_copy_listings: bool, title_limit: int | None = None
) -> int | None:
    """A manual channel: the app says what to publish there, and Manuel does it. None when the name is taken."""
    return connection.execute(
        postgresql.insert(channels)
        .values(
            name=name,
            fee_percent=fee.percent,
            fee_fixed_cents=fee.fixed_cents,
            multi_copy_listings=multi_copy_listings,
            title_limit=title_limit,
        )
        .on_conflict_do_nothing(index_elements=[channels.c.name])
        .returning(channels.c.id)
    ).scalar_one_or_none()


def named(connection: Connection, name: str) -> Channel:
    return _channel(connection.execute(select(channels).where(channels.c.name == name)).one())


def publish_through_api(connection: Connection, channel_id: int, on: bool) -> None:
    """The app publishes on the channel by itself, or leaves it to Manuel again."""
    connection.execute(update(channels).where(channels.c.id == channel_id).values(publishes_through_api=on))


def change_fee(connection: Connection, channel_id: int, fee: FeeRule) -> None:
    connection.execute(
        update(channels)
        .where(channels.c.id == channel_id)
        .values(fee_percent=fee.percent, fee_fixed_cents=fee.fixed_cents)
    )


def title_limit(connection: Connection) -> int | None:
    """The characters of the tightest title among the channels: the same title is on all of them. None when no
    channel sets a limit."""
    return connection.execute(select(func.min(channels.c.title_limit))).scalar_one()


def target_margin(connection: Connection) -> Decimal:
    """The margin on the cost every price is made to leave: one setting for all the channels."""
    return connection.execute(select(settings.c.target_margin_percent)).scalar_one()


def change_target_margin(connection: Connection, percent: Decimal) -> None:
    connection.execute(update(settings).values(target_margin_percent=percent))


def force_price(connection: Connection, item_id: int, channel_id: int, cents: int | None) -> None:
    """The price of the item on that channel only, over the one fixed and the one made from the target, such as for a
    promotion there. None takes it away."""
    connection.execute(
        forced_prices.delete().where(forced_prices.c.item_id == item_id, forced_prices.c.channel_id == channel_id)
    )
    if cents is not None:
        connection.execute(forced_prices.insert().values(item_id=item_id, channel_id=channel_id, price_cents=cents))


def proposal(connection: Connection, item_id: int) -> Proposal | None:
    """The price on each channel: the one Manuel forced there, or else the one he fixed on the item, or else the one
    that leaves the target net. None when he fixed none and the cost is not known: with no cost there is no target
    net, and any price would be a guess."""
    cost = stock.cost_to_cover(connection, item_id)
    fixed = items.fixed_price(connection, item_id)
    if cost is None and fixed is None:
        return None
    forced = dict(
        connection.execute(
            select(forced_prices.c.channel_id, forced_prices.c.price_cents).where(forced_prices.c.item_id == item_id)
        ).all()
    )
    margin = target_margin(connection)
    net = None if cost is None else pricing.target_net(cost, margin)
    per_channel = [_priced(channel, forced.get(channel.id), fixed, cost, net, margin) for channel in every(connection)]
    return Proposal(cost, margin, net, fixed, per_channel)


def _priced(
    channel: Channel, forced: int | None, fixed: int | None, cost: int | None, net: int | None, target: Decimal
) -> ChannelPrice:
    """The price on the channel, the one forced there, or fixed, or else the one that leaves the net, and the margin it
    leaves of the cost, if known."""
    price = forced or fixed or pricing.channel_price(net, channel.fee)
    if cost is None:
        return ChannelPrice(channel.name, price, None, None, forced is not None)
    left = pricing.margin(price, pricing.fee(price, channel.fee), cost)
    return ChannelPrice(channel.name, price, left, pricing.warning(left, target), forced is not None)


def _channel(row) -> Channel:
    return Channel(
        row.id,
        row.name,
        FeeRule(row.fee_percent, row.fee_fixed_cents),
        row.multi_copy_listings,
        row.title_limit,
        row.publishes_through_api,
    )
