"""The split of a cost: only arithmetic, no database. Used by purchases, openings and extractions from the bulk.

The parts always add up to the amount, to the cent, and none is below a cent: a copy that cost nothing would have
no margin in percent.
"""


class TooSmallToSplit(ValueError):
    """An amount that cannot give a cent to each part."""


def equal_parts(amount_cents: int, parts: int) -> list[int]:
    """The amount in parts that differ by a cent at most: the cents left over go one each to the first ones."""
    if amount_cents < parts:
        raise TooSmallToSplit(f"{amount_cents} cents cannot give a cent to each of {parts} parts")
    share, left_over = divmod(amount_cents, parts)
    return [share + 1] * left_over + [share] * (parts - left_over)


def one_part(amount_cents: int, parts: int) -> int:
    """One of the parts that share the amount equally, rounded to the nearest cent and a cent at least: what a card
    taken out of the bulk costs, of the cost of its lot's cards. The last part is what is left of the amount."""
    if amount_cents < 1:
        raise TooSmallToSplit(f"{amount_cents} cents cannot give a cent to a part")
    # Half a cent up, in integers: a float would lose cents.
    return max(1, (2 * amount_cents + parts) // (2 * parts))


def in_proportion(amount_cents: int, values: list[int]) -> list[int]:
    """The amount in parts as the values are to one another: 101 € for pieces worth 200 € and 2 € is 100 € and
    1 €. Each part is its exact share rounded down, and the cents left over go one each to the largest remainders.

    A piece whose exact share is below a cent costs a cent, and the rest of the amount is split among the others:
    a piece estimated more never costs less."""
    if min(values) < 1:
        raise ValueError("every piece is estimated at a cent at least: one at nothing would cost nothing")
    if amount_cents < len(values):
        raise TooSmallToSplit(f"{amount_cents} cents cannot give a cent to each of {len(values)} pieces")
    raised = _raised_to_a_cent(amount_cents, values)
    others = [index for index in range(len(values)) if index not in raised]
    rest = amount_cents - len(raised)
    total = sum(values[index] for index in others)
    # Each share as a whole number of cents and a remainder, in integers: a float would lose cents.
    shares = {index: divmod(rest * values[index], total) for index in others}
    parts = [shares[index][0] if index in shares else 1 for index in range(len(values))]
    # The first ones on a tie, as in equal parts: the same split, made twice, gives the same parts.
    largest_remainders = sorted(others, key=lambda index: shares[index][1], reverse=True)
    for index in largest_remainders[: amount_cents - sum(parts)]:
        parts[index] += 1
    return parts


def _raised_to_a_cent(amount_cents: int, values: list[int]) -> set[int]:
    """The pieces whose exact share is below a cent. A cent each leaves less to the others, so their shares are
    worked out again, until none is below: the dearest piece always keeps a cent or more."""
    raised: set[int] = set()
    while True:
        others = [index for index in range(len(values)) if index not in raised]
        total = sum(values[index] for index in others)
        below = {index for index in others if (amount_cents - len(raised)) * values[index] < total}
        if not below:
            return raised
        raised |= below
