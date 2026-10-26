from decimal import Decimal

import pytest

from cards_warehouse.money import format_euros, format_percent, parse_euros, parse_percent


# 19.99 as a float is 1998.99999… cents: through a float, the cent is lost. The phone's keyboard gives a comma.
@pytest.mark.parametrize(
    ("text", "cents"),
    [("19,99", 1999), ("19.99", 1999), ("0,01", 1), ("0,5", 50), ("12", 1200), (" 89,90 ", 8990), ("0", 0)],
)
def test_an_amount_in_euros_is_read_as_exact_cents(text, cents):
    assert parse_euros(text) == cents


# A third decimal is not a cent: it is refused, never rounded. Ten million euros is a typo, not a cost.
@pytest.mark.parametrize("text", ["", "abc", "-1", "1,005", "1,2,3", "12 50", "1e3", "10000000"])
def test_what_is_not_an_amount_in_euros_is_refused(text):
    with pytest.raises(ValueError):
        parse_euros(text)


# As a person reads it, and as parse_euros reads it back: a comma, always two decimals, no thousands separator.
@pytest.mark.parametrize(("cents", "text"), [(13334, "133,34"), (12000, "120,00"), (5, "0,05"), (123456, "1234,56")])
def test_an_amount_is_written_in_euros_with_a_comma_and_two_decimals(cents, text):
    assert format_euros(cents) == text


# A fee or a margin, typed on the phone: exact to the hundredth, never a float.
@pytest.mark.parametrize(
    ("text", "percent"), [("10", Decimal(10)), ("2,5", Decimal("2.5")), (" 12.25 ", Decimal("12.25"))]
)
def test_a_percentage_is_read_as_an_exact_decimal(text, percent):
    assert parse_percent(text) == percent


@pytest.mark.parametrize("text", ["", "abc", "-1", "1,005", "1000", "10%"])
def test_what_is_not_a_percentage_is_refused(text):
    with pytest.raises(ValueError):
        parse_percent(text)


# Without the zeros the database keeps: 2,50% is written 2,5, and parse_percent reads it back.
@pytest.mark.parametrize(("percent", "text"), [(Decimal("2.50"), "2,5"), (Decimal("20.00"), "20"), (Decimal("0"), "0")])
def test_a_percentage_is_written_with_a_comma_and_no_trailing_zeros(percent, text):
    assert format_percent(percent) == text
