import pytest

from cards_warehouse.money import parse_euros


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
