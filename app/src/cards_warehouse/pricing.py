"""Prices: only arithmetic, no database. Amounts are whole cents, percentages are exact decimals."""

import math
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction


@dataclass(frozen=True)
class FeeRule:
    """What a channel keeps of a price: a percentage of it, plus a fixed part."""

    percent: Decimal
    fixed_cents: int


def target_net(cost_cents: int, margin_percent: Decimal) -> int:
    """What must be left of a price, once the channel has kept its fee, for the target margin on the cost."""
    # Rounded up, so the margin never ends below the target.
    return math.ceil(cost_cents * (1 + Fraction(margin_percent) / 100))


def channel_price(net_cents: int, rule: FeeRule) -> int:
    """The price on a channel that leaves the net, once the channel has kept its fee."""
    # As fractions the division is exact: rounded up to the cent, never short of it by a float's error.
    return math.ceil((net_cents + rule.fixed_cents) / (1 - Fraction(rule.percent) / 100))
