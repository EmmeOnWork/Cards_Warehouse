"""Balances: what Manuel owes each partner, or each partner owes him. With the purchases, the module of purchases and
balances.

Every account passes through Manuel, who keeps them: each partner has a balance with him, and none with another
partner. Each person has a part of every cost and of every sale, by their shares: who paid a cost more than their
part has that much to get back, and who took the money of a sale has to give back what is not theirs of it.
"""

from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from itertools import groupby
from operator import itemgetter

from sqlalchemy import ColumnElement, Connection, select

from cards_warehouse import cost_split, partners
from cards_warehouse.gradings import gradings
from cards_warehouse.purchases import MANUEL, purchase_shares, purchases
from cards_warehouse.sales import sales
from cards_warehouse.stock import stock_lots, stock_movements


@dataclass(frozen=True)
class Balance:
    partner_id: int
    name: str
    # What Manuel owes the partner: below zero, what the partner owes Manuel.
    cents: int


@dataclass(frozen=True)
class SaleParts:
    """Who took the money of a sale, and each person's part of its net."""

    # Manuel, or the partner's name.
    collected_by: str
    # The name and the part of each person, Manuel first, then the partners by name: they add up to the net.
    parts: list[tuple[str, int]]

    @property
    def with_partners(self) -> bool:
        """A partner has a part of it, or took the money: it is not all Manuel's."""
        return self.collected_by != MANUEL or len(self.parts) > 1


def of_sale(connection: Connection, sale_id: int) -> SaleParts | None:
    """The parts of the sale, standing or cancelled. None for a sale that took no copies from the stock: no lot has
    shares in it."""
    sold = next(_sold(connection, sales.c.id == sale_id), None)
    if sold is None:
        return None
    collected_by, _, parts = sold
    names: dict[int | None, str] = {partner.id: partner.name for partner in partners.every(connection)}
    names[None] = MANUEL
    people = sorted(parts, key=lambda person: (person is not None, names[person]))
    return SaleParts(names[collected_by], [(names[person], parts[person]) for person in people])


def every(connection: Connection) -> list[Balance]:
    """The balance with each partner, in alphabetical order: nothing, with one who shares nothing."""
    owed: Counter[int | None] = Counter()
    _add_purchases(connection, owed)
    _add_gradings(connection, owed)
    _add_sales(connection, owed)
    return [Balance(partner.id, partner.name, owed[partner.id]) for partner in partners.every(connection)]


def _add_purchases(connection: Connection, owed: Counter[int | None]) -> None:
    """What each person paid of every purchase, shipping included, beyond their part of it."""
    rows = connection.execute(
        select(
            purchases.c.id,
            purchases.c.total_cost_cents + purchases.c.shipping_cents,
            purchase_shares.c.partner_id,
            purchase_shares.c.percent,
            purchase_shares.c.paid_cents,
        )
        .join_from(purchases, purchase_shares, purchase_shares.c.purchase_id == purchases.c.id)
        .order_by(purchases.c.id)
    )
    for _, shares in groupby(rows, key=itemgetter(0)):
        shares = list(shares)
        owed.subtract(_parts(shares[0][1], {partner_id: percent for _, _, partner_id, percent, _ in shares}))
        owed.update({partner_id: paid for _, _, partner_id, _, paid in shares})


def _add_gradings(connection: Connection, owed: Counter[int | None]) -> None:
    """What the one who paid each grading, all of it, paid beyond their part of it: by the shares of the copy sent.
    From the day it was sent, the grading paid."""
    rows = connection.execute(
        select(
            gradings.c.id,
            gradings.c.cost_cents,
            gradings.c.paid_by_partner_id,
            purchase_shares.c.partner_id,
            purchase_shares.c.percent,
        )
        .join_from(gradings, stock_lots, stock_lots.c.id == gradings.c.from_lot_id)
        # A lot without a purchase has no shares: it is all Manuel's.
        .outerjoin(purchase_shares, purchase_shares.c.purchase_id == stock_lots.c.purchase_id)
        .order_by(gradings.c.id)
    )
    for _, shares in groupby(rows, key=itemgetter(0)):
        shares = list(shares)
        _, cost, paid_by, *_ = shares[0]
        owed.subtract(_parts(cost, {partner_id: _percent(percent) for _, _, _, partner_id, percent in shares}))
        owed[paid_by] += cost


def _add_sales(connection: Connection, owed: Counter[int | None]) -> None:
    """Each person's part of the net of every sale that stands, less all of it for the one who took the money."""
    for collected_by, net_cents, parts in _sold(connection, sales.c.cancelled_at.is_(None)):
        owed.update(parts)
        owed[collected_by] -= net_cents


def _sold(
    connection: Connection, condition: ColumnElement[bool]
) -> Iterator[tuple[int | None, int, dict[int | None, int]]]:
    """Each sale the condition picks, of copies taken from the stock: who took the money, the net, and each person's
    part of it."""
    net = sales.c.price_cents - sales.c.fee_cents - sales.c.shipping_cents
    rows = connection.execute(
        select(
            sales.c.id,
            net,
            sales.c.collected_by_partner_id,
            -stock_movements.c.change,
            purchase_shares.c.partner_id,
            purchase_shares.c.percent,
        )
        .join_from(sales, stock_movements, stock_movements.c.sale_id == sales.c.id)
        .join(stock_lots, stock_lots.c.id == stock_movements.c.lot_id)
        .outerjoin(purchase_shares, purchase_shares.c.purchase_id == stock_lots.c.purchase_id)
        .where(condition)
        .order_by(sales.c.id)
    )
    for _, lots in groupby(rows, key=itemgetter(0)):
        lots = list(lots)
        _, net_cents, collected_by, *_ = lots[0]
        # Each copy sold is worth the same: each person weighs their percent of its lot, for every copy of it.
        weights: Counter[int | None] = Counter()
        for _, _, _, copies, partner_id, percent in lots:
            weights[partner_id] += copies * _percent(percent)
        yield collected_by, net_cents, _parts(net_cents, weights)


def _parts(amount_cents: int, weights: Mapping[int | None, int]) -> dict[int | None, int]:
    """The amount split among the people as their weights: Manuel first, whose is the cent left over on a tie, then
    the partners in the order they were added."""
    people = sorted(weights, key=lambda partner_id: (partner_id is not None, partner_id or 0))
    parts = cost_split.by_shares(amount_cents, [weights[person] for person in people])
    return dict(zip(people, parts, strict=True))


def _percent(percent: int | None) -> int:
    """The share of a lot: of one without a purchase, which has no shares, all Manuel's."""
    return 100 if percent is None else percent
