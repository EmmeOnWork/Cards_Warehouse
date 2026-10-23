"""The stock module: loads, unloads and restores, and the rule that a quantity never goes below zero.

On a real PostgreSQL, through the module's functions.
"""

import threading

import pytest

from cards_warehouse import items, stock
from cards_warehouse.database import create_database_engine
from cards_warehouse.items import Item, Kind
from cards_warehouse.stock import Cause, NotEnoughStock


def test_a_load_makes_its_copies_available(connection):
    item = a_sealed(connection)

    stock.load(connection, item, quantity=5, unit_cost_cents=8990)

    assert stock.available(connection, item) == 5


def test_an_unload_takes_its_copies_away(connection):
    item = a_sealed(connection)
    lot = stock.load(connection, item, quantity=5, unit_cost_cents=8990)

    stock.unload(connection, lot, quantity=2, cause=Cause.SALE)

    assert stock.available(connection, item) == 3


# The rule of the module: whoever asks, a quantity never goes below zero.
def test_an_unload_of_more_copies_than_available_is_refused_and_changes_nothing(connection):
    item = a_sealed(connection)
    lot = stock.load(connection, item, quantity=2, unit_cost_cents=8990)

    with pytest.raises(NotEnoughStock):
        stock.unload(connection, lot, quantity=3, cause=Cause.SALE)

    assert stock.available(connection, item) == 2


# The same boxes bought twice at two costs: a sale of the cheaper ones cannot eat into the dearer lot.
def test_an_unload_cannot_take_copies_from_another_lot_of_the_item(connection):
    item = a_sealed(connection)
    cheap = stock.load(connection, item, quantity=1, unit_cost_cents=8000)
    stock.load(connection, item, quantity=5, unit_cost_cents=9500)

    with pytest.raises(NotEnoughStock):
        stock.unload(connection, cheap, quantity=2, cause=Cause.SALE)

    assert stock.available(connection, item) == 6


# A sale cancelled: the copies go back to the lot they left, at its cost.
def test_an_unload_then_its_restore_bring_the_stock_back_to_where_it_was(connection):
    item = a_sealed(connection)
    lot = stock.load(connection, item, quantity=3, unit_cost_cents=8990)
    sale = stock.unload(connection, lot, quantity=2, cause=Cause.SALE)

    stock.restore(connection, sale)

    assert stock.available(connection, item) == 3
    # All three are in that same lot again: unloading them raises nothing.
    stock.unload(connection, lot, quantity=3, cause=Cause.SALE)


# Zero is not how a cost not known is said: that is None, which the margins will leave out.
def test_a_known_cost_of_zero_is_refused(connection):
    item = a_sealed(connection)

    with pytest.raises(ValueError, match="not known"):
        stock.load(connection, item, quantity=1, unit_cost_cents=0)


# A load of -3 is an unload by another name, and an unload of -3 a load: both would go round the rule.
@pytest.mark.parametrize("quantity", [0, -3])
def test_a_quantity_below_one_is_refused_for_loads_and_unloads(connection, quantity):
    item = a_sealed(connection)
    lot = stock.load(connection, item, quantity=2, unit_cost_cents=8990)

    with pytest.raises(ValueError, match="at least 1"):
        stock.load(connection, item, quantity=quantity, unit_cost_cents=8990)
    with pytest.raises(ValueError, match="at least 1"):
        stock.unload(connection, lot, quantity=quantity, cause=Cause.SALE)

    assert stock.available(connection, item) == 2


# Two sales of the last copy at once, as Manuel's and the eBay worker's will be: one takes it, the other finds
# the lot empty. Each runs in its own transaction, and neither sees what the other has not committed yet.
def test_two_unloads_of_the_last_copy_at_once_take_it_only_once(database):
    engine = create_database_engine()
    with engine.begin() as connection:
        item = a_sealed(connection)
        lot = stock.load(connection, item, quantity=1, unit_cost_cents=8990)
    outcome = []

    with engine.connect() as first, engine.connect() as second:
        stock.unload(first, lot, quantity=1, cause=Cause.SALE)

        def second_sale():
            try:
                stock.unload(second, lot, quantity=1, cause=Cause.SALE)
                second.commit()
                outcome.append("sold")
            except NotEnoughStock:
                outcome.append("refused")

        thread = threading.Thread(target=second_sale)
        thread.start()
        # Time for the second sale to reach the lot while the first one is still open.
        thread.join(timeout=0.5)
        first.commit()
        thread.join()

    assert outcome == ["refused"]
    with engine.connect() as connection:
        assert stock.available(connection, item) == 0


def a_sealed(connection) -> int:
    return items.add(connection, Item(kind=Kind.SEALED, game="Pokémon", name="Booster box", language="it"))
