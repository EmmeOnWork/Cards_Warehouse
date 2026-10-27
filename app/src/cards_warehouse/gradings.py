"""Gradings: a card sent to a grader, such as PSA, that comes back sealed in a slab with its grade.

The copy leaves its lot when it is sent, and comes back as an item of its own: a graded card is not one of the
copies it was taken from. Its cost is the copy's plus the grading, and it keeps the shares of the copy's lot.
"""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from sqlalchemy import Column, Connection, Date, Integer, Table, Text, func, insert, select, update

from cards_warehouse import items, purchases, stock
from cards_warehouse.database import metadata
from cards_warehouse.items import Grading
from cards_warehouse.partners import partners
from cards_warehouse.stock import Cause

gradings = Table(
    "gradings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("from_lot_id", Integer),
    Column("sent_on", Date),
    Column("grader", Text),
    Column("cost_cents", Integer),
    Column("paid_by_partner_id", Integer),
    Column("returned_on", Date),
    Column("lot_id", Integer),
)


class AlreadyBack(Exception):
    """A grading whose card came back already: it came back once, as one item, the item_id."""

    def __init__(self, grading_id: int, item_id: int) -> None:
        super().__init__(f"grading {grading_id} came back as item {item_id}")
        self.item_id = item_id


@dataclass(frozen=True)
class Sending:
    sent_on: date
    grader: str
    cost_cents: int
    # Who paid the grading, all of it: a partner, or None for Manuel.
    paid_by: int | None


def send(connection: Connection, lot_id: int, sending: Sending) -> int:
    """One copy of the lot sent for grading: it leaves the lot, and is not for sale until it comes back."""
    stock.unload(connection, lot_id, 1, Cause.SENT_FOR_GRADING)
    return connection.execute(
        insert(gradings)
        .values(
            from_lot_id=lot_id,
            sent_on=sending.sent_on,
            grader=sending.grader,
            cost_cents=sending.cost_cents,
            paid_by_partner_id=sending.paid_by,
        )
        .returning(gradings.c.id)
    ).scalar_one()


def receive(connection: Connection, grading_id: int, returned_on: date, grade: Decimal) -> int:
    """The card back from its grading: a new item, the card it was with the grade in place of its condition, and
    a lot of its one copy. The item's id."""
    lots = stock.stock_lots
    # The grading is locked until the transaction ends: the same page sent twice at once waits here, then finds
    # the card back.
    sent = connection.execute(
        select(
            gradings.c.returned_on,
            gradings.c.grader,
            gradings.c.cost_cents,
            lots.c.item_id,
            lots.c.unit_cost_cents,
            lots.c.purchase_id,
        )
        .join_from(gradings, lots, lots.c.id == gradings.c.from_lot_id)
        .where(gradings.c.id == grading_id)
        .with_for_update(of=gradings)
    ).one()
    if sent.returned_on is not None:
        raise AlreadyBack(grading_id, _item_back(connection, grading_id))
    card = items.get(connection, sent.item_id)
    grading = Grading(sent.grader, grade)
    graded = replace(card, details=replace(card.details, state=grading))
    item_id = items.add(connection, graded)
    # A cost not known stays so, with the grading added: the copy may have cost anything.
    cost = None if sent.unit_cost_cents is None else sent.unit_cost_cents + sent.cost_cents
    # The copy keeps its purchase, so its shares: the grading is part of its cost, shared as the rest of it.
    lot_id = stock.load(connection, item_id, 1, cost, purchase_id=sent.purchase_id, cause=Cause.GRADED)
    connection.execute(
        update(gradings).where(gradings.c.id == grading_id).values(returned_on=returned_on, lot_id=lot_id)
    )
    return item_id


def _item_back(connection: Connection, grading_id: int) -> int:
    lots = stock.stock_lots
    return connection.execute(
        select(lots.c.item_id)
        .join_from(gradings, lots, lots.c.id == gradings.c.lot_id)
        .where(gradings.c.id == grading_id)
    ).scalar_one()


@dataclass(frozen=True)
class AtGrader:
    """A card sent for grading and not back yet."""

    id: int
    item_id: int
    name: str
    sent_on: date
    grader: str
    cost_cents: int
    # Manuel, or the partner's name.
    paid_by: str


@dataclass(frozen=True)
class Back:
    """The grading a graded card came back from: what it cost, who paid it, and the shares the card has."""

    sent_on: date
    returned_on: date
    cost_cents: int
    paid_by: str
    shares: list[tuple[str, int]]


def _sent():
    """The gradings with the card sent and who paid, for a query to narrow."""
    lots = stock.stock_lots
    return (
        select(
            gradings.c.id,
            lots.c.item_id,
            items.items.c.name,
            gradings.c.sent_on,
            gradings.c.grader,
            gradings.c.cost_cents,
            func.coalesce(partners.c.name, purchases.MANUEL),
        )
        .join_from(gradings, lots, lots.c.id == gradings.c.from_lot_id)
        .join(items.items, items.items.c.id == lots.c.item_id)
        .outerjoin(partners, partners.c.id == gradings.c.paid_by_partner_id)
    )


def at_grader(connection: Connection, item_id: int) -> list[AtGrader]:
    """The copies of the item sent for grading and not back yet, the first sent first."""
    lots = stock.stock_lots
    rows = connection.execute(
        _sent().where(lots.c.item_id == item_id, gradings.c.returned_on.is_(None)).order_by(gradings.c.id)
    )
    return [AtGrader(*row) for row in rows]


def one(connection: Connection, grading_id: int) -> AtGrader | None:
    """The grading, while its card is at the grader: None once it is back."""
    row = connection.execute(_sent().where(gradings.c.id == grading_id, gradings.c.returned_on.is_(None))).one_or_none()
    return None if row is None else AtGrader(*row)


def back(connection: Connection, item_id: int) -> Back | None:
    """The grading the item came back from: None for an item that did not come from a grading."""
    lots = stock.stock_lots
    row = connection.execute(
        select(
            gradings.c.sent_on,
            gradings.c.returned_on,
            gradings.c.cost_cents,
            func.coalesce(partners.c.name, purchases.MANUEL),
            gradings.c.lot_id,
        )
        .join_from(gradings, lots, lots.c.id == gradings.c.lot_id)
        .outerjoin(partners, partners.c.id == gradings.c.paid_by_partner_id)
        .where(lots.c.item_id == item_id)
    ).one_or_none()
    if row is None:
        return None
    sent_on, returned_on, cost, paid_by, lot_id = row
    return Back(sent_on, returned_on, cost, paid_by, purchases.people_of_lot(connection, lot_id))
