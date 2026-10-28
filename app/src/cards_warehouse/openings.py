"""Openings: copies of a lot opened, such as a box into its packs, or packs into cards and the bulk. The copies
leave their lot, and what was inside comes in as new lots that take their cost whole. The movements of those point
to the one of the copies opened.
"""

from dataclasses import dataclass

from sqlalchemy import Connection, func, select, union_all

from cards_warehouse import cost_split, items, stock
from cards_warehouse.items import Item, Kind
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
class Pulled:
    """Copies of a card that came out of an opening worth a listing, and what one of them is estimated to be worth."""

    item_id: int
    copies: int
    estimated_value_cents: int


@dataclass(frozen=True)
class Rest:
    """The cards of an opening not worth a listing: counted roughly, and estimated all together."""

    cards: int
    estimated_value_cents: int


def into_cards(connection: Connection, lot_id: int, copies: int, cards: list[Pulled], rest: Rest) -> None:
    """Copies of the lot, packs or boxes, opened into cards worth a listing, and the rest into the bulk of their game
    and language. Their cost goes to the cards and to the bulk in proportion to what they are estimated to be worth,
    each copy of a card on its own and the rest as one."""
    lots = stock.stock_lots
    unit_cost, purchase_id, item_id = connection.execute(
        select(lots.c.unit_cost_cents, lots.c.purchase_id, lots.c.item_id).where(lots.c.id == lot_id)
    ).one()
    values = [card.estimated_value_cents for card in cards for _ in range(card.copies)] + [rest.estimated_value_cents]
    # Checked even when the cost is not known: the same opening is refused whatever its cost.
    if min(values) < 1:
        raise ValueError("every card and the bulk are estimated at a cent at least: one at nothing would cost nothing")
    if rest.cards < 1:
        raise ValueError(f"the rest of an opening is 1 card at least, not {rest.cards}")
    if unit_cost is None:
        # Not free: what comes out of copies whose cost is not known is not known either.
        parts = iter([None] * len(values))
    else:
        parts = iter(cost_split.in_proportion(copies * unit_cost, values))
    opening = stock.unload(connection, lot_id, copies, Cause.OPENING)
    # What came out comes from the purchase of what was opened, through the opening: it carries its shares.
    for card in cards:
        # The dearer first, as in a purchase; costs not known are all alike.
        unit_costs = sorted((next(parts) for _ in range(card.copies)), key=lambda cost: cost or 0, reverse=True)
        stock.load_split(connection, card.item_id, unit_costs, purchase_id=purchase_id, opening_id=opening)
    stock.load_bulk(connection, _bulk(connection, item_id), rest.cards, next(parts), purchase_id, opening)


def _bulk(connection: Connection, opened_item_id: int) -> int:
    """The bulk of the game and the language of the item opened: born the first time it is needed."""
    opened = items.get(connection, opened_item_id)
    bulk = connection.execute(
        select(items.items.c.id)
        .join_from(items.items, items.games, items.games.c.id == items.items.c.game_id)
        .where(
            items.items.c.kind == Kind.BULK,
            items.games.c.name == opened.game,
            items.items.c.language == opened.language,
        )
    ).scalar_one_or_none()
    if bulk is not None:
        return bulk
    name = f"Bulk {opened.game} {items.LANGUAGES[opened.language]}"
    return items.add(connection, Item(Kind.BULK, opened.game, name, opened.language))


@dataclass(frozen=True)
class Counterpart:
    """An item on the other side of a movement of an opening. For the copies opened, an item that came out of them and
    how many copies; for those copies, the item opened and how many copies were taken from it."""

    item_id: int
    name: str
    kind: Kind
    copies: int


def counterparts(connection: Connection, item_id: int) -> dict[int, list[Counterpart]]:
    """The other side of each movement of an opening among the item's, by the id of the movement: the items in the
    order they came out."""
    own, own_lots = stock.stock_movements.alias("own"), stock.stock_lots.alias("own_lots")
    other, other_lots = stock.stock_movements.alias("other"), stock.stock_lots.alias("other_lots")

    def linked(link, copies, came):
        """The item's movements linked to another by `link`, with the item of that other, `copies`, and when it
        `came`, to keep the order."""
        return (
            select(
                own.c.id.label("movement_id"),
                items.items.c.id.label("item_id"),
                items.items.c.name,
                items.items.c.kind,
                copies.label("copies"),
                came.label("came"),
            )
            .join_from(own, own_lots, own_lots.c.id == own.c.lot_id)
            .join(other, link)
            .join(other_lots, other_lots.c.id == other.c.lot_id)
            .join(items.items, items.items.c.id == other_lots.c.item_id)
            .where(own_lots.c.item_id == item_id)
        )

    # The copies opened: what came out of them points to them, each item in one lot or two.
    went_into = linked(other.c.opening_id == own.c.id, func.sum(other.c.change), func.min(other.c.id)).group_by(
        own.c.id, items.items.c.id
    )
    # The copies that came out: they point to the copies opened.
    came_from = linked(other.c.id == own.c.opening_id, -other.c.change, other.c.id)
    both = union_all(went_into, came_from).subquery()
    by_movement: dict[int, list[Counterpart]] = {}
    for row in connection.execute(select(both).order_by(both.c.came)):
        by_movement.setdefault(row.movement_id, []).append(
            Counterpart(row.item_id, row.name, Kind(row.kind), row.copies)
        )
    return by_movement
