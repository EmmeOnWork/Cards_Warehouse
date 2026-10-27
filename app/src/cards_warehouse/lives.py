"""Live inventories: the items Manuel shows in a live on Tilt. And the presets he saves them as, to start the next
live from: a copy of the items, so that changing the inventory or the preset leaves the other as it is."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Column, Connection, DateTime, Integer, Table, Text, delete, func, insert, literal, select
from sqlalchemy.dialects import postgresql

from cards_warehouse import channels, items
from cards_warehouse.database import metadata

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

live_presets = Table("live_presets", metadata, Column("id", Integer, primary_key=True), Column("name", Text))

live_preset_items = Table(
    "live_preset_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("preset_id", Integer),
    Column("item_id", Integer),
)


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
