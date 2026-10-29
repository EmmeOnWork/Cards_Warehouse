"""Prices: only arithmetic, no database. Amounts are whole cents, percentages are exact decimals."""

import math
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction


@dataclass(frozen=True)
class FeeRule:
    """What a channel keeps of a price: a percentage of it, plus a fixed part."""

    percent: Decimal
    fixed_cents: int


@dataclass(frozen=True)
class Margin:
    """What a price leaves once the fee and the cost are paid: in cents, and as a percentage of the cost."""

    cents: int
    percent: Decimal


class MarginWarning(StrEnum):
    BELOW_TARGET = "below_target"
    # Less is left than the copy cost.
    LOSS = "loss"


def target_net(cost_cents: int, margin_percent: Decimal) -> int:
    """What must be left of a price, once the channel has kept its fee, for the target margin on the cost."""
    # Rounded up, so the margin never ends below the target.
    return math.ceil(cost_cents * (1 + Fraction(margin_percent) / 100))


def channel_price(net_cents: int, rule: FeeRule) -> int:
    """The price on a channel that leaves the net, once the channel has kept its fee."""
    # As fractions the division is exact: rounded up to the cent, never short of it by a float's error.
    return math.ceil((net_cents + rule.fixed_cents) / (1 - Fraction(rule.percent) / 100))


def fee(price_cents: int, rule: FeeRule) -> int:
    """What the channel keeps of a price."""
    # Rounded up, as the platform may round it: the margin shown is never more than the one left.
    return math.ceil(price_cents * Fraction(rule.percent) / 100) + rule.fixed_cents


def margin(price_cents: int, fee_cents: int, cost_cents: int, shipping_cents: int = 0) -> Margin:
    """The margin a price leaves, once the channel has kept its fee and the shipping left on Manuel is paid, on the
    cost of the copies."""
    cents = price_cents - fee_cents - shipping_cents - cost_cents
    # In hundredths of a point, rounded down: never shown above the margin left, and so never on the target when it
    # is a hair below it. A loss is rounded away from zero.
    hundredths = cents * 100 * 100 // cost_cents
    return Margin(cents, Decimal(hundredths) / 100)


def warning(left: Margin, target_percent: Decimal) -> MarginWarning | None:
    """What a margin warns of, so that nothing is sold below the cost, or below the target, by mistake."""
    if left.cents < 0:
        return MarginWarning.LOSS
    if left.percent < target_percent:
        return MarginWarning.BELOW_TARGET
    return None
