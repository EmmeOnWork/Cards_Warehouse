"""The daily check: what it finds out of line between the stock, the listings and the actions, and the outcome it
leaves for the app to show.

On a real PostgreSQL, through the module's functions, with the clock fixed: each check is told the time it runs at.
"""

import subprocess
import sys
from datetime import UTC, datetime, timedelta

from cards_warehouse import channels, daily_check, exposure, items, manual_channels, stock
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.daily_check import OpenOnSoldOut, OverOffered, StaleAction, Thresholds, UnsoldItem
from cards_warehouse.database import create_database_engine
from cards_warehouse.exposure import Status
from cards_warehouse.items import Item, Kind
from cards_warehouse.manual_channels import ActionKind
from cards_warehouse.stock import Cause

NOW = datetime(2026, 10, 29, 7, 0, tzinfo=UTC)


# Tilt offered all five, then three were lost. Vinted offers one copy, and two are left: nothing wrong there.
def test_a_listing_offering_more_copies_than_are_left_is_found_with_both_counts(connection):
    item = a_sealed(connection, copies=5)
    exposure.put_on_sale(connection, item, channel_ids(connection, "Vinted", "Tilt"), manual_channels.MANUAL)
    [lot] = stock.lots(connection, item)
    stock.unload(connection, lot.id, quantity=3, cause=Cause.LOST)

    outcome = daily_check.run(connection, NOW)

    assert outcome.over_offered == [OverOffered(item, "Booster box", "Tilt", offered=5, available=2)]


# Sold out, with a listing active on Vinted and one still to publish on Tilt: both must close before anyone buys.
# Said once, as sold out, and not again as a listing offering more copies than are left.
def test_the_listings_still_open_on_an_item_sold_out_are_found_once_as_such(connection):
    item = a_sealed(connection, copies=1)
    exposure.put_on_sale(connection, item, channel_ids(connection, "Vinted", "Tilt"), manual_channels.MANUAL)
    manual_channels.done(connection, manual_channels.pending(connection)["Vinted"][0].id, link=VINTED_LINK)
    [lot] = stock.lots(connection, item)
    stock.unload(connection, lot.id, quantity=1, cause=Cause.SALE)

    outcome = daily_check.run(connection, NOW)

    assert outcome.open_on_sold_out == [
        OpenOnSoldOut(item, "Booster box", "Vinted", Status.ACTIVE),
        OpenOnSoldOut(item, "Booster box", "Tilt", Status.TO_PUBLISH),
    ]
    assert outcome.over_offered == []


# Three days is the threshold until Manuel changes it: an action left that long is still in time, a second more and
# it is forgotten. One done is not left at all. The actions of one put on sale are all made at the same time.
def test_an_action_left_to_do_for_longer_than_the_threshold_is_found_with_when_it_was_made(connection):
    item = a_sealed(connection, copies=1)
    exposure.put_on_sale(connection, item, channel_ids(connection, "Vinted", "Tilt"), manual_channels.MANUAL)
    on_vinted, on_tilt = (actions[0] for actions in manual_channels.pending(connection).values())
    manual_channels.done(connection, on_tilt.id, link=TILT_LINK)
    made = on_vinted.created_at

    on_time = daily_check.run(connection, made + timedelta(days=3))
    late = daily_check.run(connection, made + timedelta(days=3, seconds=1))

    assert on_time.stale_actions == []
    assert late.stale_actions == [StaleAction(on_vinted.id, ActionKind.PUBLISH, item, "Booster box", "Vinted", made)]


# Sixty days is the threshold until Manuel changes it. Never sold, the box stands since it came in; the prices of its
# listings are those to review.
def test_an_item_never_sold_for_longer_than_the_threshold_is_found_with_the_prices_of_its_listings(connection):
    item = a_sealed(connection, copies=2)
    exposure.put_on_sale(connection, item, channel_ids(connection, "Vinted", "Tilt"), manual_channels.MANUAL)
    [came_in] = stock.history(connection, item)

    on_time = daily_check.run(connection, came_in.at + timedelta(days=60))
    late = daily_check.run(connection, came_in.at + timedelta(days=60, seconds=1))

    assert on_time.unsold_items == []
    assert late.unsold_items == [UnsoldItem(item, "Booster box", came_in.at, [("Vinted", 12000), ("Tilt", 12296)])]


# One copy of two sold: the box stands since the sale. Each step in a transaction of its own, as from the pages:
# PostgreSQL gives every movement of one transaction the same time.
def test_an_item_sold_stands_since_its_last_sale(database):
    engine = create_database_engine()
    with engine.begin() as connection:
        item = a_sealed(connection, copies=2)
    with engine.begin() as connection:
        [lot] = stock.lots(connection, item)
        stock.unload(connection, lot.id, quantity=1, cause=Cause.SALE)
    with engine.connect() as connection:
        came_in, sold = stock.history(connection, item)
        on_time = daily_check.run(connection, sold.at + timedelta(days=60))
        late = daily_check.run(connection, sold.at + timedelta(days=60, seconds=1))

    assert came_in.at < sold.at
    assert on_time.unsold_items == []
    assert [unsold.since for unsold in late.unsold_items] == [sold.at]


# Sold out, or lost, there is nothing left to price; the bulk waits for a sale in lots (task 49). A year after they
# came in, neither is found.
def test_an_item_with_no_copy_left_and_the_bulk_are_never_found_unsold(connection):
    lost = a_sealed(connection, copies=1)
    [lot] = stock.lots(connection, lost)
    stock.unload(connection, lot.id, quantity=1, cause=Cause.LOST)
    bulk = items.add(connection, Item(kind=Kind.BULK, game="Pokémon", name="Bulk Pokémon", language="it"))
    stock.load(connection, bulk, quantity=300, unit_cost_cents=None)
    came_in, _ = stock.history(connection, lost)

    outcome = daily_check.run(connection, came_in.at + timedelta(days=365))

    assert outcome.unsold_items == []


# Two days after the box came in and its action was made: within three days and sixty, nothing; Manuel wants to know
# sooner, and the next check finds both.
def test_the_thresholds_changed_count_from_the_next_check(connection):
    item = a_sealed(connection, copies=1)
    exposure.put_on_sale(connection, item, channel_ids(connection, "Vinted"), manual_channels.MANUAL)
    [action] = manual_channels.pending(connection)["Vinted"]
    two_days_later = action.created_at + timedelta(days=2, seconds=1)
    before = daily_check.run(connection, two_days_later)

    daily_check.change_thresholds(connection, Thresholds(stale_action_days=1, unsold_item_days=2))
    after = daily_check.run(connection, two_days_later)

    assert (before.stale_actions, before.unsold_items) == ([], [])
    assert [stale.action_id for stale in after.stale_actions] == [action.id]
    assert [unsold.item_id for unsold in after.unsold_items] == [item]
    assert daily_check.thresholds(connection) == Thresholds(stale_action_days=1, unsold_item_days=2)


# What the app shows: nothing before the first check, then the last one, read back as it found things, of every kind.
def test_the_last_check_is_kept_for_the_app_as_it_found_things(connection):
    box = a_sealed(connection, copies=5)
    sold_out = a_sealed(connection, copies=1, name="Elite Trainer Box")
    exposure.put_on_sale(connection, box, channel_ids(connection, "Tilt"), manual_channels.MANUAL)
    exposure.put_on_sale(connection, sold_out, channel_ids(connection, "Vinted"), manual_channels.MANUAL)
    lose(connection, box, copies=3)
    lose(connection, sold_out, copies=1)
    made = manual_channels.pending(connection)["Tilt"][0].created_at
    nothing_yet = daily_check.last(connection)

    daily_check.run(connection, made + timedelta(days=60, seconds=1))
    later = daily_check.run(connection, made + timedelta(days=61))

    assert nothing_yet is None
    assert daily_check.last(connection) == later
    found = (later.over_offered, later.open_on_sold_out, later.stale_actions, later.unsold_items)
    assert [len(each) for each in found] == [1, 1, 2, 1]


# What the CronJob runs, in a process of its own as in its pod, on the clock of the machine: the check is kept, and
# its log says what it found.
def test_the_check_run_as_the_cronjob_runs_it_is_kept_and_logged(database):
    finished = subprocess.run(
        [sys.executable, "-m", "cards_warehouse.daily_check"], capture_output=True, text=True, check=True
    )

    with create_database_engine().connect() as connection:
        kept = daily_check.last(connection)
    assert finished.stdout == f"Controllo del {kept.ran_at.astimezone(LOCAL_TIME):%d/%m alle %H:%M}: tutto in ordine.\n"


VINTED_LINK = "https://www.vinted.it/items/5123456789-booster-box"
TILT_LINK = "https://tilt.app/listings/booster-box"


def a_sealed(connection, copies: int, name: str = "Booster box") -> int:
    item = items.add(connection, Item(kind=Kind.SEALED, game="Pokémon", name=name, language="it"))
    stock.load(connection, item, quantity=copies, unit_cost_cents=10000)
    return item


def lose(connection, item: int, copies: int) -> None:
    [lot] = stock.lots(connection, item)
    stock.unload(connection, lot.id, quantity=copies, cause=Cause.LOST)


def channel_ids(connection, *names: str) -> list[int]:
    by_name = {channel.name: channel.id for channel in channels.every(connection)}
    return [by_name[name] for name in names]
