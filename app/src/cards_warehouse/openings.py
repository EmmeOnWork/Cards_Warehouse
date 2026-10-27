"""Openings: a copy of a lot opened, such as a box into its packs. The copy leaves its lot, and what was inside
comes in as new lots that take its cost whole. The movements of those point to the one of the copy opened.
"""

from dataclasses import dataclass

from sqlalchemy import Connection, func, select, union_all

from cards_warehouse import cost_split, items, stock
from cards_warehouse.stock import Cause


def into_packs(connection: Connection, lot_id: int, packs_item_id: int, packs: int) -> None:
    """One copy of the lot, a box, opened into packs of the item: the cost of the box in equal parts.

    Refused before anything changes when the cost cannot give a cent to each pack, or there are no packs."""
    if packs < 1:
        raise ValueError(f"a box opens into 1 pack at least, not {packs}")
    lots = stock.stock_lots
    box_cost, purchase_id = connection.execute(
        select(lots.c.unit_cost_cents, lots.c.purchase_id).where(lots.c.id == lot_id)
    ).one()
    unit_costs = [None] * packs if box_cost is None else cost_split.equal_parts(box_cost, packs)
    opening = stock.unload(connection, lot_id, 1, Cause.OPENING)
    # The packs come from the box's purchase, through the opening: they carry its shares, as the box did.
    stock.load_split(connection, packs_item_id, unit_costs, purchase_id=purchase_id, opening_id=opening)


@dataclass(frozen=True)
class Counterpart:
    """The other side of a movement of an opening. For the copy opened, the item that came out of it and how many
    copies; for those copies, the item opened and the one copy taken from it."""

    item_id: int
    name: str
    copies: int


def counterparts(connection: Connection, item_id: int) -> dict[int, Counterpart]:
    """The other side of each movement of an opening among the item's, by the id of the movement."""
    own, own_lots = stock.stock_movements.alias("own"), stock.stock_lots.alias("own_lots")
    other, other_lots = stock.stock_movements.alias("other"), stock.stock_lots.alias("other_lots")

    def linked(link, copies):
        """The item's movements linked to another by `link`, with the item of that other and `copies`."""
        return (
            select(own.c.id, items.items.c.id, items.items.c.name, copies)
            .join_from(own, own_lots, own_lots.c.id == own.c.lot_id)
            .join(other, link)
            .join(other_lots, other_lots.c.id == other.c.lot_id)
            .join(items.items, items.items.c.id == other_lots.c.item_id)
            .where(own_lots.c.item_id == item_id)
        )

    # The copy opened: what came out of it points to it, in one lot or two.
    went_into = linked(other.c.opening_id == own.c.id, func.sum(other.c.change)).group_by(own.c.id, items.items.c.id)
    # The copies that came out: they point to the copy opened.
    came_from = linked(other.c.id == own.c.opening_id, -other.c.change)
    rows = connection.execute(union_all(went_into, came_from))
    return {movement_id: Counterpart(other_item, name, copies) for movement_id, other_item, name, copies in rows}
