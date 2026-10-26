"""Purchases: the origin of the lots, with what they cost, who shares them and who paid what.

A purchase of identical copies splits its cost, shipping included, in equal parts among them. The parts differ by
a cent at most and a lot is copies at one unit cost, so the copies that take a cent more make a lot of their own.
The shares are set on the purchase, once: every lot it makes carries them.
"""

from dataclasses import dataclass
from datetime import date
from itertools import groupby
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


def record(connection: Connection, purchase: Purchase, item_id: int, quantity: int) -> int:
    """The purchase of identical copies of the item, loaded in the lots it makes. Without shares it is all
    Manuel's, and he paid it all."""
    due = purchase.total_cost_cents + purchase.shipping_cents
    shares = purchase.shares or (Share(None, 100, due),)
    if (percent := sum(share.percent for share in shares)) != 100:
        raise SharesNotWhole(percent)
    if (paid := sum(share.paid_cents for share in shares)) != due:
        raise PaymentsNotTotal(paid, due)
    unit_costs = cost_split.equal_parts(due, quantity)
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
    # The dearer copies first: the first lot is the one a sale takes from when Manuel does not choose.
    for unit_cost, copies in groupby(unit_costs):
        stock.load(connection, item_id, len(list(copies)), unit_cost, purchase_id=purchase_id)
    return purchase_id


def shares_of_lot(connection: Connection, lot_id: int) -> dict[int | None, int]:
    """The percent each person has of the lot, by partner: Manuel is None. The shares of the purchase it came from,
    or all Manuel's for a lot without one."""
    lots = stock.of_lots()
    rows = connection.execute(
        select(purchase_shares.c.partner_id, purchase_shares.c.percent)
        .join_from(lots, purchase_shares, purchase_shares.c.purchase_id == lots.c.purchase_id)
        .where(lots.c.lot_id == lot_id)
    )
    return {partner_id: percent for partner_id, percent in rows} or {None: 100}


@dataclass(frozen=True)
class PurchasedLot:
    item: str
    copies: int
    unit_cost_cents: int


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
        select(lots.c.purchase_id, items.items.c.name, lots.c.loaded, lots.c.unit_cost_cents)
        .join_from(lots, items.items, items.items.c.id == lots.c.item_id)
        .where(lots.c.purchase_id.is_not(None))
        .order_by(lots.c.lot_id)
    )
    lots_of: dict[int, list[PurchasedLot]] = {}
    for purchase_id, item, copies, unit_cost in lot_rows:
        lots_of.setdefault(purchase_id, []).append(PurchasedLot(item, copies, unit_cost))
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
