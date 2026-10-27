"""Purchases: the origin of the lots, with what they cost, who shares them and who paid what.

A purchase of identical copies splits its cost, shipping included, in equal parts among them. The parts differ by
a cent at most and a lot is copies at one unit cost, so the copies that take a cent more make a lot of their own.
A mixed purchase splits it in proportion to what each piece is estimated to be worth, and makes the lots of each
item the same way. The shares are set on the purchase, once: every lot it makes carries them.
"""

from dataclasses import dataclass
from datetime import date
from itertools import groupby
from operator import attrgetter
from typing import NamedTuple

from sqlalchemy import Column, Connection, Date, Integer, Table, Text, func, insert, select

from cards_warehouse import cost_split, items, stock
from cards_warehouse.database import metadata
from cards_warehouse.partners import partners

# The one user of the app, who is in every purchase without being a partner.
MANUEL = "Manuel"

purchases = Table(
    "purchases",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("total_cost_cents", Integer),
    Column("shipping_cents", Integer),
    Column("purchased_on", Date),
    Column("note", Text),
)


purchase_shares = Table(
    "purchase_shares",
    metadata,
    Column("purchase_id", Integer),
    Column("partner_id", Integer),
    Column("percent", Integer),
    Column("paid_cents", Integer),
)


class SharesNotWhole(ValueError):
    """Shares that do not add up to 100%."""

    def __init__(self, percent: int) -> None:
        super().__init__(f"the shares add up to {percent}%, not 100%")
        self.percent = percent


class PaymentsNotTotal(ValueError):
    """Payments that do not add up to what the purchase cost, shipping included."""

    def __init__(self, paid_cents: int, due_cents: int) -> None:
        super().__init__(f"the payments add up to {paid_cents} cents, not {due_cents}")
        self.paid_cents = paid_cents
        self.due_cents = due_cents


@dataclass(frozen=True)
class Share:
    """What a person has of a purchase, in whole percents, and what they paid of it. Manuel is the partner None."""

    partner_id: int | None
    percent: int
    paid_cents: int


@dataclass(frozen=True)
class Purchase:
    total_cost_cents: int
    # What the seller charged to send it: part of the cost of the copies.
    shipping_cents: int
    purchased_on: date
    note: str = ""
    shares: tuple[Share, ...] = ()


@dataclass(frozen=True)
class Piece:
    """Copies of an item in a mixed purchase, and what one of them is estimated to be worth: at least a cent."""

    item_id: int
    quantity: int
    estimated_value_cents: int


def record(connection: Connection, purchase: Purchase, item_id: int, quantity: int) -> int:
    """The purchase of identical copies of the item, loaded in the lots it makes. Without shares it is all
    Manuel's, and he paid it all."""
    # Copies of the same value: whatever it is, they split the cost in equal parts.
    return record_mixed(connection, purchase, [Piece(item_id, quantity, estimated_value_cents=1)])


def record_mixed(connection: Connection, purchase: Purchase, pieces: list[Piece]) -> int:
    """The purchase of pieces of different items, or of the same worth differently: each copy costs a part of it
    in proportion to what it is estimated to be worth, so a card of 200 € does not cost as much as one of 2 €."""
    due = purchase.total_cost_cents + purchase.shipping_cents
    shares = purchase.shares or (Share(None, 100, due),)
    if (percent := sum(share.percent for share in shares)) != 100:
        raise SharesNotWhole(percent)
    if (paid := sum(share.paid_cents for share in shares)) != due:
        raise PaymentsNotTotal(paid, due)
    copies = [piece.estimated_value_cents for piece in pieces for _ in range(piece.quantity)]
    unit_costs = iter(cost_split.in_proportion(due, copies))
    purchase_id = connection.execute(
        insert(purchases)
        .values(
            total_cost_cents=purchase.total_cost_cents,
            shipping_cents=purchase.shipping_cents,
            purchased_on=purchase.purchased_on,
            note=purchase.note,
        )
        .returning(purchases.c.id)
    ).scalar_one()
    connection.execute(
        insert(purchase_shares),
        [
            {"purchase_id": purchase_id, "partner_id": s.partner_id, "percent": s.percent, "paid_cents": s.paid_cents}
            for s in shares
        ],
    )
    for piece in pieces:
        costs = [next(unit_costs) for _ in range(piece.quantity)]
        stock.load_split(connection, piece.item_id, sorted(costs, reverse=True), purchase_id=purchase_id)
    return purchase_id


def shares_of_lot(connection: Connection, lot_id: int) -> dict[int | None, int]:
    """The percent each person has of the lot, by partner: Manuel is None. The shares of the purchase it came from,
    or all Manuel's for a lot without one."""
    lots = stock.stock_lots
    rows = connection.execute(
        select(purchase_shares.c.partner_id, purchase_shares.c.percent)
        .join_from(lots, purchase_shares, purchase_shares.c.purchase_id == lots.c.purchase_id)
        .where(lots.c.id == lot_id)
    )
    return {partner_id: percent for partner_id, percent in rows} or {None: 100}


def people_of_lot(connection: Connection, lot_id: int) -> list[tuple[str, int]]:
    """The shares of the lot as a person reads them: the name and the percent, Manuel first, then the partners by
    name."""
    lots = stock.stock_lots
    rows = connection.execute(
        select(func.coalesce(partners.c.name, MANUEL), purchase_shares.c.percent)
        .join_from(lots, purchase_shares, purchase_shares.c.purchase_id == lots.c.purchase_id)
        .outerjoin(partners, partners.c.id == purchase_shares.c.partner_id)
        .where(lots.c.id == lot_id)
        .order_by(partners.c.name.nulls_first())
    )
    return [(person, percent) for person, percent in rows] or [(MANUEL, 100)]


@dataclass(frozen=True)
class PurchasedLot:
    item_id: int
    item: str
    copies: int
    unit_cost_cents: int


class PurchasedItem(NamedTuple):
    id: int
    name: str
    copies: int


class ListedShare(NamedTuple):
    person: str
    percent: int
    paid_cents: int


@dataclass(frozen=True)
class Listed:
    id: int
    purchased_on: date
    total_cost_cents: int
    shipping_cents: int
    note: str
    lots: tuple[PurchasedLot, ...]
    # Manuel first, then the partners by name.
    shares: tuple[ListedShare, ...]

    @property
    def items(self) -> list[PurchasedItem]:
        """The items bought, in the order they were loaded, with their copies: one, for identical copies."""
        bought = []
        for item_id, group in groupby(self.lots, key=attrgetter("item_id")):
            lots = list(group)
            bought.append(PurchasedItem(item_id, lots[0].item, sum(lot.copies for lot in lots)))
        return bought


def listing(connection: Connection) -> list[Listed]:
    """Every purchase with the lots it made and its shares, the last bought first."""
    share_rows = connection.execute(
        select(
            purchase_shares.c.purchase_id,
            func.coalesce(partners.c.name, MANUEL),
            purchase_shares.c.percent,
            purchase_shares.c.paid_cents,
        )
        .outerjoin_from(purchase_shares, partners, partners.c.id == purchase_shares.c.partner_id)
        .order_by(partners.c.name.nulls_first())
    )
    shares_of: dict[int, list[ListedShare]] = {}
    for purchase_id, person, percent, paid in share_rows:
        shares_of.setdefault(purchase_id, []).append(ListedShare(person, percent, paid))
    lots = stock.of_lots()
    lot_rows = connection.execute(
        select(lots.c.purchase_id, lots.c.item_id, items.items.c.name, lots.c.loaded, lots.c.unit_cost_cents)
        .join_from(lots, items.items, items.items.c.id == lots.c.item_id)
        .where(lots.c.purchase_id.is_not(None))
        .order_by(lots.c.lot_id)
    )
    lots_of: dict[int, list[PurchasedLot]] = {}
    for purchase_id, item_id, item, copies, unit_cost in lot_rows:
        lots_of.setdefault(purchase_id, []).append(PurchasedLot(item_id, item, copies, unit_cost))
    rows = connection.execute(select(purchases).order_by(purchases.c.purchased_on.desc(), purchases.c.id.desc()))
    return [
        Listed(
            row.id,
            row.purchased_on,
            row.total_cost_cents,
            row.shipping_cents,
            row.note,
            tuple(lots_of[row.id]),
            tuple(shares_of[row.id]),
        )
        for row in rows
    ]
