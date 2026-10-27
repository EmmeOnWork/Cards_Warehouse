"""The split of a cost: in equal parts, or in proportion to estimated values, exact to the cent.

In equal parts, every amount up to 20 € in every number of parts up to 50, and the largest amount an euro field
takes. In proportion, any amount and any values such a field takes.
"""

import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

from cards_warehouse.cost_split import TooSmallToSplit, equal_parts, in_proportion

LARGEST = 999_999_999


@st.composite
def splits(draw) -> tuple[int, list[int]]:
    """Up to 50 pieces, each estimated at a cent or more, and a cost that gives each a cent at least: as large as
    a total cost plus a shipping can be. Small ones too, where a piece's exact share falls below a cent."""
    value = st.one_of(st.integers(min_value=1, max_value=1000), st.integers(min_value=1, max_value=LARGEST))
    values = draw(st.lists(value, min_size=1, max_size=50))
    smallest = len(values)
    amount = st.one_of(
        st.integers(min_value=smallest, max_value=smallest + 1000),
        st.integers(min_value=smallest, max_value=2 * LARGEST),
    )
    return draw(amount), values


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


# A card estimated 200 € and one estimated 2 €, bought together for 101 €: 100 € and 1 €, not 50,50 € each.
def test_101_euros_for_pieces_estimated_200_and_2_euros_are_100_and_1():
    assert in_proportion(10100, [20000, 200]) == [10000, 100]


# Its exact share of 100 € is half a cent: it costs a cent, taken from the other piece, so that its margin in
# percent can be worked out.
def test_a_piece_estimated_a_cent_next_to_one_estimated_200_euros_still_costs_a_cent():
    assert in_proportion(10000, [20000, 1]) == [9999, 1]


# A card estimated more than another never costs less than it, even when the other is raised to a cent. 12 cents
# for 6,20 €, 5,70 € and 0,01 € give 6, 6 and 0 before the cent: it is not taken from the dearer card.
@given(splits())
@example(split=(12, [620, 570, 1]))
def test_a_piece_estimated_more_never_costs_less(split):
    amount, values = split
    parts = in_proportion(amount, values)

    by_value = sorted(zip(values, parts, strict=True))
    assert [part for _, part in by_value] == sorted(parts)


# Not a cent lost, and none made up, whatever the pieces are worth.
@given(splits())
def test_the_parts_in_proportion_always_add_up_to_the_amount(split):
    amount, values = split
    assert sum(in_proportion(amount, values)) == amount


@given(splits())
def test_no_part_in_proportion_is_below_a_cent(split):
    amount, values = split
    assert min(in_proportion(amount, values)) >= 1


# When no piece needs raising to a cent, the split is the proportion itself, off by less than a cent each.
@given(splits())
def test_when_every_exact_share_is_a_cent_or_more_each_part_is_it_rounded_down_or_up(split):
    amount, values = split
    total = sum(values)
    assume(amount * min(values) >= total)
    for value, part in zip(values, in_proportion(amount, values), strict=True):
        assert amount * value // total <= part <= -(-amount * value // total)


# Copies of the same card are pieces of the same value: split as equal parts, the cents left over to the first.
@given(st.integers(min_value=1, max_value=50), st.integers(min_value=1, max_value=LARGEST), st.data())
def test_pieces_of_the_same_value_are_split_in_equal_parts(parts, value, data):
    amount = data.draw(st.integers(min_value=parts, max_value=2 * LARGEST))
    assert in_proportion(amount, [value] * parts) == equal_parts(amount, parts)


# 2 cents for three pieces would leave one at zero, however they are estimated: refused, not rounded.
@pytest.mark.parametrize(("amount", "values"), [(2, [100, 100, 100]), (2, [20000, 1, 1]), (0, [100]), (-5, [1, 1])])
def test_an_amount_too_small_to_give_a_cent_to_each_piece_is_refused(amount, values):
    with pytest.raises(TooSmallToSplit):
        in_proportion(amount, values)


# A piece estimated at nothing would cost nothing: the page asks at least a cent for it.
@pytest.mark.parametrize("values", [[20000, 0], [20000, -100]])
def test_a_piece_estimated_below_a_cent_is_refused(values):
    with pytest.raises(ValueError, match="estimated"):
        in_proportion(10000, values)
