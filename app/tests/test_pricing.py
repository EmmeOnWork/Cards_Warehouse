import math
from decimal import Decimal
from fractions import Fraction

from hypothesis import given
from hypothesis import strategies as st

from cards_warehouse.pricing import FeeRule, channel_price, target_net

# Any cost up to the largest amount the app takes, any target margin, any fee rule a channel can have.
costs = st.integers(min_value=1, max_value=999_999_999)
margins = st.decimals(min_value=0, max_value=Decimal("999.99"), places=2)
fee_rules = st.builds(
    FeeRule,
    percent=st.decimals(min_value=0, max_value=Decimal("99.99"), places=2),
    fixed_cents=st.integers(min_value=0, max_value=100_000),
)


# Vinted takes nothing from the seller: what the buyer pays for the item is what is left.
def test_on_a_channel_without_a_fee_the_price_is_the_net():
    assert channel_price(12000, FeeRule(percent=Decimal(0), fixed_cents=0)) == 12000


# The fee is a share of the final price, so the net is divided by 0.90, not multiplied by 1.10, which gives 132,00
# and leaves 118,80. 133,333… is rounded up: at 133,33 the platform would leave 119,997.
def test_a_fee_of_10_percent_turns_a_net_of_120_into_a_price_of_133_34():
    assert channel_price(12000, FeeRule(percent=Decimal(10), fixed_cents=0)) == 13334


# Tilt keeps 2% plus 0,50 per sale: the fixed part is added to the net before dividing. 120,50 / 0,98 is 122,959…
def test_the_fixed_part_of_a_fee_is_covered_by_the_price_as_well():
    assert channel_price(12000, FeeRule(percent=Decimal(2), fixed_cents=50)) == 12296


# The margin is on the cost: 20% of 100 is 20, so 120 must be left once the channel has kept its fee.
def test_the_target_net_is_the_cost_plus_the_target_margin():
    assert target_net(10000, margin_percent=Decimal(20)) == 12000


# 0,012 is not an amount: rounded down to 0,01 the margin would be zero, so it goes up to 0,02.
def test_a_target_net_between_two_cents_is_rounded_up():
    assert target_net(1, margin_percent=Decimal(20)) == 2


# The platform keeps whole cents. Even when it rounds its fee up, what is left is the cost plus the target margin.
@given(costs, margins, fee_rules)
def test_the_net_left_by_the_price_is_never_below_the_target(cost, margin, rule):
    price = channel_price(target_net(cost, margin), rule)

    fee = math.ceil(price * Fraction(rule.percent) / 100) + rule.fixed_cents
    assert price - fee >= cost * (1 + Fraction(margin) / 100)


# Rounded up to the cent, and no further: one cent less would leave less than the target net.
@given(costs, margins, fee_rules)
def test_the_price_is_the_lowest_that_leaves_the_target_net(cost, margin, rule):
    net = target_net(cost, margin)
    price = channel_price(net, rule)

    cheaper = price - 1
    assert cheaper - cheaper * Fraction(rule.percent) / 100 - rule.fixed_cents < net
