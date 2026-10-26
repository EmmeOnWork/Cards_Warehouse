"""The split of a cost: in equal parts, exact to the cent.

Every amount up to 20 € in every number of parts up to 50, and the largest amount an euro field takes.
"""

import pytest

from cards_warehouse.cost_split import TooSmallToSplit, equal_parts

LARGEST = 999_999_999


def every_case():
    for parts in range(1, 51):
        for amount in [*range(parts, 2001), LARGEST]:
            yield amount, parts


# Not a cent lost, and none made up: the costs of the copies always add up to what the purchase cost.
def test_the_parts_always_add_up_to_the_amount():
    for amount, parts in every_case():
        assert sum(equal_parts(amount, parts)) == amount, (amount, parts)


# Equal to the cent, and the cents left over always go to the first parts: the same purchase, split twice,
# gives the same costs to the same lots. No copy costs less than a cent, which would make its margin infinite.
def test_the_cents_left_over_go_one_each_to_the_first_parts_and_no_part_is_below_a_cent():
    for amount, parts in every_case():
        split = equal_parts(amount, parts)
        assert len(split) == parts, (amount, parts)
        assert split == sorted(split, reverse=True), (amount, parts)
        assert split[0] - split[-1] <= 1, (amount, parts)
        assert split[-1] >= 1, (amount, parts)


def test_104_euros_in_3_copies_are_34_67_twice_and_34_66():
    assert equal_parts(10400, 3) == [3467, 3467, 3466]


# 2 cents in 3 copies would leave one at zero: refused, not rounded.
@pytest.mark.parametrize(("amount", "parts"), [(2, 3), (0, 1), (49, 50), (-5, 2)])
def test_an_amount_too_small_to_give_a_cent_to_each_part_is_refused(amount, parts):
    with pytest.raises(TooSmallToSplit):
        equal_parts(amount, parts)
