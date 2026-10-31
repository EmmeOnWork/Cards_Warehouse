"""Live inventories: the items Manuel shows in a live on Tilt. And the presets he saves them as, to start the next
live from: a copy of the items, so that changing the inventory or the preset leaves the other as it is. At the end of
the live, the copies he sold in it, which become sales on Tilt."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Column, Connection, DateTime, Integer, Table, Text, delete, func, insert, literal, select, update
from sqlalchemy.dialects import postgresql

from cards_warehouse import channels, items, pricing, sales
from cards_warehouse.database import metadata
from cards_warehouse.exposure import ChannelOperations
from cards_warehouse.pricing import Margin
from cards_warehouse.sales import Sale

# The channel of the lives. Found by its name, which the app does not change.
TILT = "Tilt"

live_inventories = Table(
    "live_inventories",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("created_at", DateTime(timezone=True)),
)

live_inventory_items = Table(
    "live_inventory_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("inventory_id", Integer),
    Column("item_id", Integer),
)

live_sales = Table(
    "live_sales",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("inventory_id", Integer),
    Column("item_id", Integer),
    Column("quantity", Integer),
    Column("unit_price_cents", Integer),
    Column("sale_id", Integer),
)

live_presets = Table("live_presets", metadata, Column("id", Integer, primary_key=True), Column("name", Text))

live_preset_items = Table(
    "live_preset_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("preset_id", Integer),
    Column("item_id", Integer),
)


class NotEnoughCopies(Exception):
    """A row sells more copies than its item has left: until the double sales, no row is sold."""

    def __init__(self, name: str, available: int, quantity: int) -> None:
        super().__init__(f"{name}: {available} copies left, {quantity} sold")
        self.name = name
        self.available = available
        self.quantity = quantity


@dataclass(frozen=True)
class Inventory:
    id: int
    created_at: datetime
    items: int


@dataclass(frozen=True)
class Preset:
    id: int
    name: str


@dataclass(frozen=True)
class Row:
    """An item of an inventory, as it stands when the inventory is shown."""

    item_id: int
    name: str
    available: int
    # The price proposed on Tilt: a fee or a target margin changed since shows at once. None when the item's cost
    # is not known, as on the item's page.
    tilt_price_cents: int | None


@dataclass(frozen=True)
class Entered:
    """A row of copies sold in the live, as Manuel entered it."""

    id: int
    name: str
    quantity: int
    unit_price_cents: int
    # None until the row is confirmed.
    sale_id: int | None


@dataclass(frozen=True)
class SoldItem:
    name: str
    copies: int
    takings_cents: int


@dataclass(frozen=True)
class Report:
    """What a live left: the sales its rows became."""

    takings_cents: int
    fees_cents: int
    # Of the sales whose cost is known: None when no sale has one.
    margin: Margin | None
    # The sales left out of the margin.
    cost_not_known: int
    # In the order they were first entered.
    sold: list[SoldItem]


def start(connection: Connection, preset_id: int | None = None) -> int:
    """A new inventory: with the preset's items, in their order, or with none."""
    inventory_id = connection.execute(insert(live_inventories).returning(live_inventories.c.id)).scalar_one()
    if preset_id is not None:
        connection.execute(
            insert(live_inventory_items).from_select(
                ["inventory_id", "item_id"],
                select(literal(inventory_id), live_preset_items.c.item_id)
                .where(live_preset_items.c.preset_id == preset_id)
                .order_by(live_preset_items.c.id),
            )
        )
    return inventory_id


def add(connection: Connection, inventory_id: int, item_id: int) -> None:
    """The item in the inventory. One already there stays as it is: an item is shown once."""
    connection.execute(
        postgresql.insert(live_inventory_items)
        .values(inventory_id=inventory_id, item_id=item_id)
        .on_conflict_do_nothing(index_elements=[live_inventory_items.c.inventory_id, live_inventory_items.c.item_id])
    )


def remove(connection: Connection, inventory_id: int, item_id: int) -> None:
    connection.execute(
        delete(live_inventory_items).where(
            live_inventory_items.c.inventory_id == inventory_id, live_inventory_items.c.item_id == item_id
        )
    )


def rows(connection: Connection, inventory_id: int) -> list[Row]:
    """The items of the inventory, in the order they were added."""
    chosen = (
        select(live_inventory_items.c.item_id)
        .where(live_inventory_items.c.inventory_id == inventory_id)
        .order_by(live_inventory_items.c.id)
    )
    return [_row(connection, item_id) for item_id in connection.execute(chosen).scalars()]


def inventories(connection: Connection) -> list[Inventory]:
    """Every inventory, the newest first, with how many items it has."""
    rows = connection.execute(
        select(live_inventories.c.id, live_inventories.c.created_at, func.count(live_inventory_items.c.id))
        .outerjoin(live_inventory_items, live_inventory_items.c.inventory_id == live_inventories.c.id)
        .group_by(live_inventories.c.id)
        .order_by(live_inventories.c.id.desc())
    )
    return [Inventory(*row) for row in rows]


def sold(connection: Connection, inventory_id: int, item_id: int, quantity: int, unit_price_cents: int) -> None:
    """A row of copies of the item sold in the live, at a price for each: kept until confirmed."""
    connection.execute(
        insert(live_sales).values(
            inventory_id=inventory_id, item_id=item_id, quantity=quantity, unit_price_cents=unit_price_cents
        )
    )


def unsold(connection: Connection, inventory_id: int, row_id: int) -> None:
    """The row taken off, if not yet confirmed: one confirmed is a sale."""
    connection.execute(
        delete(live_sales).where(
            live_sales.c.id == row_id, live_sales.c.inventory_id == inventory_id, live_sales.c.sale_id.is_(None)
        )
    )


def entered(connection: Connection, inventory_id: int) -> list[Entered]:
    """The rows of copies sold in the live, in the order they were entered."""
    rows = connection.execute(
        select(
            live_sales.c.id,
            items.items.c.name,
            live_sales.c.quantity,
            live_sales.c.unit_price_cents,
            live_sales.c.sale_id,
        )
        .join_from(live_sales, items.items, items.items.c.id == live_sales.c.item_id)
        .where(live_sales.c.inventory_id == inventory_id)
        .order_by(live_sales.c.id)
    )
    return [Entered(*row) for row in rows]


def confirm(connection: Connection, inventory_id: int, operations: ChannelOperations) -> list[int]:
    """A sale on Tilt for each row not yet confirmed, in their order, with what it leaves to do on the listings done
    through `operations`. The sales made. NotEnoughCopies when a row sells more than its item has left: the caller
    keeps none."""
    tilt = channels.named(connection, TILT)
    to_sell = connection.execute(
        select(live_sales)
        .where(live_sales.c.inventory_id == inventory_id, live_sales.c.sale_id.is_(None))
        .order_by(live_sales.c.id)
    ).all()
    made = []
    for row in to_sell:
        # Each copy is a Tilt order of its own, and Tilt keeps the fixed part of its fee on each.
        fee = row.quantity * pricing.fee(row.unit_price_cents, tilt.fee)
        sale = Sale(row.item_id, tilt.id, row.quantity, row.quantity * row.unit_price_cents, fee_cents=fee)
        try:
            sale_id = sales.record(connection, sale, operations)
        except sales.NotEnoughCopies as refusal:
            raise NotEnoughCopies(items.get(connection, row.item_id).name, refusal.available, row.quantity) from None
        connection.execute(update(live_sales).where(live_sales.c.id == row.id).values(sale_id=sale_id))
        made.append(sale_id)
    return made


def report(connection: Connection, inventory_id: int) -> Report:
    made = connection.execute(
        select(sales.sales)
        .join_from(live_sales, sales.sales, sales.sales.c.id == live_sales.c.sale_id)
        .where(live_sales.c.inventory_id == inventory_id)
    ).all()
    known = [sale for sale in made if sale.cost_cents is not None]
    margin = None
    if known:
        margin = pricing.margin(
            sum(sale.price_cents for sale in known),
            sum(sale.fee_cents for sale in known),
            sum(sale.cost_cents for sale in known),
            sum(sale.shipping_cents for sale in known),
        )
    sold = connection.execute(
        select(items.items.c.name, func.sum(sales.sales.c.quantity), func.sum(sales.sales.c.price_cents))
        .join_from(live_sales, sales.sales, sales.sales.c.id == live_sales.c.sale_id)
        .join(items.items, items.items.c.id == live_sales.c.item_id)
        .where(live_sales.c.inventory_id == inventory_id)
        .group_by(items.items.c.id)
        .order_by(func.min(live_sales.c.id))
    )
    return Report(
        sum(sale.price_cents for sale in made),
        sum(sale.fee_cents for sale in made),
        margin,
        len(made) - len(known),
        [SoldItem(*row) for row in sold],
    )


def save_as_preset(connection: Connection, inventory_id: int, name: str) -> int | None:
    """A preset with the inventory's items, in their order. None when the name is taken."""
    preset_id = connection.execute(
        postgresql.insert(live_presets)
        .values(name=name)
        .on_conflict_do_nothing(index_elements=[live_presets.c.name])
        .returning(live_presets.c.id)
    ).scalar_one_or_none()
    if preset_id is None:
        return None
    connection.execute(
        insert(live_preset_items).from_select(
            ["preset_id", "item_id"],
            select(literal(preset_id), live_inventory_items.c.item_id)
            .where(live_inventory_items.c.inventory_id == inventory_id)
            .order_by(live_inventory_items.c.id),
        )
    )
    return preset_id


def presets(connection: Connection) -> list[Preset]:
    """Every preset, by name."""
    return [Preset(*row) for row in connection.execute(select(live_presets).order_by(live_presets.c.name))]


def _row(connection: Connection, item_id: int) -> Row:
    item = items.find(connection, item_id)
    proposal = channels.proposal(connection, item_id)
    price = None if proposal is None else dict(proposal.prices)[TILT]
    return Row(item.id, item.name, item.available, price)
