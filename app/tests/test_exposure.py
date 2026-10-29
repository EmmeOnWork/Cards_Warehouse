"""The exposure module: the listings of the items on the channels, and what putting an item on sale, or a change of
its price or its stock, leaves to do.

On a real PostgreSQL, through the module's functions, with every channel a manual one.
"""

from decimal import Decimal

import pytest

from cards_warehouse import channels, exposure, items, manual_channels, stock
from cards_warehouse.exposure import NoPrice, NothingToSell, Status
from cards_warehouse.items import Item, Kind
from cards_warehouse.manual_channels import ActionKind
from cards_warehouse.stock import Cause


# At a cost of 100 and the target of 20%: 120 on Vinted and eBay, which keep nothing; Tilt keeps 2% + 0,50.
def test_putting_an_item_on_sale_on_three_channels_leaves_a_listing_and_an_action_to_publish_on_each(connection):
    item = a_sealed(connection, copies=1)

    exposure.put_on_sale(connection, item, channel_ids(connection, "Vinted", "Tilt", "eBay"), manual_channels.MANUAL)

    assert _listings(connection, item) == [
        ("Vinted", Status.TO_PUBLISH, 12000, 1),
        ("Tilt", Status.TO_PUBLISH, 12296, 1),
        ("eBay", Status.TO_PUBLISH, 12000, 1),
    ]
    assert _actions(connection) == [
        ("Vinted", ActionKind.PUBLISH, item, 12000, 1),
        ("Tilt", ActionKind.PUBLISH, item, 12296, 1),
        ("eBay", ActionKind.PUBLISH, item, 12000, 1),
    ]


# A listing on Vinted is one copy, and closes when it is sold: another is published for the next copy (task 22).
def test_on_a_channel_where_a_listing_is_one_copy_it_offers_one_of_five_and_elsewhere_all_five(connection):
    item = a_sealed(connection, copies=5)

    exposure.put_on_sale(connection, item, channel_ids(connection, "Vinted", "Tilt", "eBay"), manual_channels.MANUAL)

    assert [(channel, quantity) for channel, _, _, quantity in _listings(connection, item)] == [
        ("Vinted", 1),
        ("Tilt", 5),
        ("eBay", 5),
    ]


# Manuel published it on Vinted and pasted the link: the app knows where the item is offered.
def test_an_action_to_publish_done_with_its_link_makes_the_listing_active_there_and_leaves_the_list(connection):
    item = a_sealed(connection, copies=1)
    exposure.put_on_sale(connection, item, channel_ids(connection, "Vinted", "Tilt"), manual_channels.MANUAL)
    on_vinted = manual_channels.pending(connection)["Vinted"][0]

    manual_channels.done(connection, on_vinted.id, link=VINTED_LINK)

    assert [(listing.channel, listing.status, listing.link) for listing in exposure.of_item(connection, item)] == [
        ("Vinted", Status.ACTIVE, VINTED_LINK),
        ("Tilt", Status.TO_PUBLISH, None),
    ]
    assert [channel for channel, *_ in _actions(connection)] == ["Tilt"]


# Sent twice, as from a page reloaded: the item is on Vinted already, and nothing more is offered there.
def test_a_channel_where_the_item_is_listed_already_gets_no_second_listing_nor_action(connection):
    item = a_sealed(connection, copies=1)
    exposure.put_on_sale(connection, item, channel_ids(connection, "Vinted"), manual_channels.MANUAL)

    exposure.put_on_sale(connection, item, channel_ids(connection, "Vinted", "Tilt"), manual_channels.MANUAL)

    assert [channel for channel, *_ in _listings(connection, item)] == ["Vinted", "Tilt"]
    assert [channel for channel, *_ in _actions(connection)] == ["Vinted", "Tilt"]


# Sold out, or lost: a listing would offer what is not there. Even on Vinted, where a listing is one copy.
def test_an_item_with_no_copies_left_is_refused_and_nothing_is_offered(connection):
    item = a_sealed(connection, copies=1)
    [lot] = stock.lots(connection, item)
    stock.unload(connection, lot.id, quantity=1, cause=Cause.LOST)

    with pytest.raises(NothingToSell):
        exposure.put_on_sale(connection, item, channel_ids(connection, "Vinted", "Tilt"), manual_channels.MANUAL)

    assert _listings(connection, item) == []
    assert _actions(connection) == []


# A cost not known and no price fixed: any price would be a guess. With a price fixed, it goes on sale at that.
def test_an_item_with_no_price_is_refused_and_nothing_is_offered(connection):
    item = a_sealed(connection, copies=1, unit_cost_cents=None)

    with pytest.raises(NoPrice):
        exposure.put_on_sale(connection, item, channel_ids(connection, "Vinted", "Tilt"), manual_channels.MANUAL)

    assert _listings(connection, item) == []
    assert _actions(connection) == []


# Two of five sold on eBay, which took them off its listing by itself: three are left there, with nothing to do. Tilt
# offers five, more than are left: an action to update it to three. Vinted offers one copy, which is still there.
def test_a_sale_on_a_channel_of_several_copies_lowers_its_listing_there_and_updates_those_offering_too_many(
    connection,
):
    item = a_sealed(connection, copies=5)
    _published(connection, item, "Vinted", "Tilt", "eBay")

    _sell(connection, item, "eBay", copies=2)

    assert _listings(connection, item) == [
        ("Vinted", Status.ACTIVE, 12000, 1),
        ("Tilt", Status.TO_UPDATE, 12296, 3),
        ("eBay", Status.ACTIVE, 12000, 3),
    ]
    assert _actions(connection) == [("Tilt", ActionKind.UPDATE, item, 12296, 3)]


# The only copy sold on Tilt, which closed its listing by itself. Vinted and eBay offer it still: to close.
def test_the_last_copy_sold_closes_the_listing_where_it_sold_and_leaves_an_action_to_close_each_other(connection):
    item = a_sealed(connection, copies=1)
    _published(connection, item, "Vinted", "Tilt", "eBay")

    _sell(connection, item, "Tilt", copies=1)

    assert _listings(connection, item) == [
        ("Vinted", Status.TO_CLOSE, 12000, 1),
        ("eBay", Status.TO_CLOSE, 12000, 1),
    ]
    assert _actions(connection) == [
        ("Vinted", ActionKind.CLOSE, item, 12000, 1),
        ("eBay", ActionKind.CLOSE, item, 12000, 1),
    ]


# One of five sold on Vinted, where a listing is one copy and closes once sold. Four are left: a new listing to publish
# there, for the next copy. Tilt and eBay offer five: to update to four.
def test_a_sale_on_vinted_with_copies_left_leaves_a_new_listing_to_publish_there_for_the_next_copy(connection):
    item = a_sealed(connection, copies=5)
    _published(connection, item, "Vinted", "Tilt", "eBay")

    _sell(connection, item, "Vinted", copies=1)

    assert _listings(connection, item) == [
        ("Vinted", Status.TO_PUBLISH, 12000, 1),
        ("Tilt", Status.TO_UPDATE, 12296, 4),
        ("eBay", Status.TO_UPDATE, 12000, 4),
    ]
    assert _actions(connection) == [
        ("Vinted", ActionKind.PUBLISH, item, 12000, 1),
        ("Tilt", ActionKind.UPDATE, item, 12296, 4),
        ("eBay", ActionKind.UPDATE, item, 12000, 4),
    ]


# The last copy sold on Vinted: no new listing, and the others are to close.
def test_the_last_copy_sold_on_vinted_leaves_no_new_listing_there(connection):
    item = a_sealed(connection, copies=1)
    _published(connection, item, "Vinted", "eBay")

    _sell(connection, item, "Vinted", copies=1)

    assert _listings(connection, item) == [("eBay", Status.TO_CLOSE, 12000, 1)]
    assert _actions(connection) == [("eBay", ActionKind.CLOSE, item, 12000, 1)]


# Sold on Vinted before Manuel published it on eBay: there is nothing left to publish, and the action goes.
def test_a_listing_still_to_publish_when_the_last_copy_sells_is_closed_and_its_action_to_publish_goes(connection):
    item = a_sealed(connection, copies=1)
    exposure.put_on_sale(connection, item, channel_ids(connection, "Vinted", "eBay"), manual_channels.MANUAL)
    manual_channels.done(connection, manual_channels.pending(connection)["Vinted"][0].id, link=VINTED_LINK)

    _sell(connection, item, "Vinted", copies=1)

    assert _listings(connection, item) == []
    assert _actions(connection) == []


# Sold on Vinted before Manuel published it on Tilt: Tilt's listing offers the two copies left, and he publishes those.
def test_a_listing_still_to_publish_offers_only_the_copies_left_with_no_action_to_update(connection):
    item = a_sealed(connection, copies=3)
    exposure.put_on_sale(connection, item, channel_ids(connection, "Vinted", "Tilt"), manual_channels.MANUAL)
    manual_channels.done(connection, manual_channels.pending(connection)["Vinted"][0].id, link=VINTED_LINK)

    _sell(connection, item, "Vinted", copies=1)

    assert _listings(connection, item) == [
        ("Vinted", Status.TO_PUBLISH, 12000, 1),
        ("Tilt", Status.TO_PUBLISH, 12296, 2),
    ]
    assert _actions(connection) == [
        ("Vinted", ActionKind.PUBLISH, item, 12000, 1),
        ("Tilt", ActionKind.PUBLISH, item, 12296, 2),
    ]


# Manuel brought Tilt down to the copy left, then took it off Tilt once that sold too.
def test_an_action_to_update_done_leaves_the_listing_active_and_one_to_close_leaves_it_off_its_channel(connection):
    item = a_sealed(connection, copies=2)
    _published(connection, item, "Tilt", "eBay")
    _sell(connection, item, "eBay", copies=1)

    _do_what_is_left(connection)

    assert _listings(connection, item) == [("Tilt", Status.ACTIVE, 12296, 1), ("eBay", Status.ACTIVE, 12000, 1)]
    _sell(connection, item, "eBay", copies=1)
    _do_what_is_left(connection)
    assert _listings(connection, item) == []
    assert _actions(connection) == []


# Sold on Vinted, as agreed in a chat, before Manuel published the listing there: Vinted took nothing off it. With
# two copies left the listing stays to publish, as it was, with its one action.
def test_a_sale_on_a_channel_where_the_listing_is_still_to_publish_leaves_it_to_publish_with_one_action(connection):
    item = a_sealed(connection, copies=3)
    exposure.put_on_sale(connection, item, channel_ids(connection, "Vinted"), manual_channels.MANUAL)

    _sell(connection, item, "Vinted", copies=1)

    assert _listings(connection, item) == [("Vinted", Status.TO_PUBLISH, 12000, 1)]
    assert _actions(connection) == [("Vinted", ActionKind.PUBLISH, item, 12000, 1)]


# Vinted and eBay keep nothing of a price, and were at 120,00 € already: only Tilt's listing, at 122,96 €, changes.
def test_a_price_fixed_leaves_an_action_to_update_each_active_listing_whose_price_changes_and_no_other(connection):
    item = a_sealed(connection, copies=5)
    _published(connection, item, "Vinted", "Tilt", "eBay")
    items.fix_price(connection, item, 12000)

    exposure.align(connection, item, manual_channels.MANUAL)

    assert _listings(connection, item) == [
        ("Vinted", Status.ACTIVE, 12000, 1),
        ("Tilt", Status.TO_UPDATE, 12000, 5),
        ("eBay", Status.ACTIVE, 12000, 5),
    ]
    assert _actions(connection) == [("Tilt", ActionKind.UPDATE, item, 12000, 5)]


# Two of five lost: Tilt and eBay offer five, more than are left. Vinted offers one copy, which is still there.
def test_an_adjustment_below_the_copies_offered_leaves_an_action_to_lower_each_listing_offering_too_many(connection):
    item = a_sealed(connection, copies=5)
    _published(connection, item, "Vinted", "Tilt", "eBay")
    [lot] = stock.lots(connection, item)
    stock.adjust(connection, lot.id, -2, Cause.LOST)

    exposure.align(connection, item, manual_channels.MANUAL)

    assert _listings(connection, item) == [
        ("Vinted", Status.ACTIVE, 12000, 1),
        ("Tilt", Status.TO_UPDATE, 12296, 3),
        ("eBay", Status.TO_UPDATE, 12000, 3),
    ]
    assert _actions(connection) == [
        ("Tilt", ActionKind.UPDATE, item, 12296, 3),
        ("eBay", ActionKind.UPDATE, item, 12000, 3),
    ]


# The only copy damaged: every listing offers what is gone, Vinted's too.
def test_an_adjustment_to_no_copy_left_leaves_an_action_to_close_each_listing(connection):
    item = a_sealed(connection, copies=1)
    _published(connection, item, "Vinted", "Tilt")
    [lot] = stock.lots(connection, item)
    stock.adjust(connection, lot.id, -1, Cause.DAMAGED)

    exposure.align(connection, item, manual_channels.MANUAL)

    assert _listings(connection, item) == [("Vinted", Status.TO_CLOSE, 12000, 1), ("Tilt", Status.TO_CLOSE, 12296, 1)]
    assert _actions(connection) == [
        ("Vinted", ActionKind.CLOSE, item, 12000, 1),
        ("Tilt", ActionKind.CLOSE, item, 12296, 1),
    ]


# Three more bought at the same cost: Tilt and eBay offer all eight. A listing on Vinted is one copy still.
def test_a_new_lot_leaves_an_action_to_offer_its_copies_where_a_listing_has_several_and_none_on_vinted(connection):
    item = a_sealed(connection, copies=5)
    _published(connection, item, "Vinted", "Tilt", "eBay")
    stock.load(connection, item, quantity=3, unit_cost_cents=10000)

    exposure.align(connection, item, manual_channels.MANUAL)

    assert _listings(connection, item) == [
        ("Vinted", Status.ACTIVE, 12000, 1),
        ("Tilt", Status.TO_UPDATE, 12296, 8),
        ("eBay", Status.TO_UPDATE, 12000, 8),
    ]
    assert _actions(connection) == [
        ("Tilt", ActionKind.UPDATE, item, 12296, 8),
        ("eBay", ActionKind.UPDATE, item, 12000, 8),
    ]


# A price fixed, then two copies lost before Manuel updated Tilt: one action, to bring it to both.
def test_a_change_on_a_listing_with_an_action_to_update_left_changes_that_action_instead_of_adding_one(connection):
    item = a_sealed(connection, copies=5)
    _published(connection, item, "Tilt")
    items.fix_price(connection, item, 11000)
    exposure.align(connection, item, manual_channels.MANUAL)
    [lot] = stock.lots(connection, item)
    stock.adjust(connection, lot.id, -2, Cause.LOST)

    exposure.align(connection, item, manual_channels.MANUAL)

    assert _listings(connection, item) == [("Tilt", Status.TO_UPDATE, 11000, 3)]
    assert _actions(connection) == [("Tilt", ActionKind.UPDATE, item, 11000, 3)]


# Two copies lost, then the other three before Manuel updated Tilt: there is nothing to update anymore, only to close.
def test_no_copy_left_on_a_listing_with_an_action_to_update_left_turns_that_action_into_one_to_close(connection):
    item = a_sealed(connection, copies=5)
    _published(connection, item, "Tilt")
    [lot] = stock.lots(connection, item)
    stock.adjust(connection, lot.id, -2, Cause.LOST)
    exposure.align(connection, item, manual_channels.MANUAL)
    [update] = manual_channels.pending(connection)["Tilt"]
    stock.adjust(connection, lot.id, -3, Cause.LOST)

    exposure.align(connection, item, manual_channels.MANUAL)

    assert _listings(connection, item) == [("Tilt", Status.TO_CLOSE, 12296, 3)]
    assert [(action.id, action.kind) for action in manual_channels.pending(connection)["Tilt"]] == [
        (update.id, ActionKind.CLOSE)
    ]


# Off Vinted, while Tilt goes on offering it.
def test_an_item_withdrawn_from_a_channel_leaves_an_action_to_close_there_only_and_is_closed_once_it_is_done(
    connection,
):
    item = a_sealed(connection, copies=5)
    _published(connection, item, "Vinted", "Tilt")
    on_vinted, _ = exposure.of_item(connection, item)

    exposure.withdraw(connection, on_vinted.id, manual_channels.MANUAL)

    assert _listings(connection, item) == [("Vinted", Status.TO_CLOSE, 12000, 1), ("Tilt", Status.ACTIVE, 12296, 5)]
    assert _actions(connection) == [("Vinted", ActionKind.CLOSE, item, 12000, 1)]
    _do_what_is_left(connection)
    assert exposure.one(connection, on_vinted.id).status == Status.CLOSED
    assert _listings(connection, item) == [("Tilt", Status.ACTIVE, 12296, 5)]


# Withdrawn from Tilt, then a price fixed before Manuel closed it there: Tilt's listing is to close still, as he chose.
def test_a_listing_to_close_stays_to_close_whatever_changes_after(connection):
    item = a_sealed(connection, copies=5)
    _published(connection, item, "Tilt")
    [on_tilt] = exposure.of_item(connection, item)
    exposure.withdraw(connection, on_tilt.id, manual_channels.MANUAL)
    items.fix_price(connection, item, 11000)

    exposure.align(connection, item, manual_channels.MANUAL)

    assert _listings(connection, item) == [("Tilt", Status.TO_CLOSE, 12296, 5)]
    assert _actions(connection) == [("Tilt", ActionKind.CLOSE, item, 12296, 5)]


# A promotion on Tilt only, at 99,00 € in place of 122,96 €. A price fixed after, 120,00 € on every channel, changes
# nothing on Tilt, nor on Vinted, at 120,00 € already. The promotion over, Tilt has the price fixed.
def test_a_price_forced_on_a_channel_wins_over_the_one_made_and_the_one_fixed_until_it_is_taken_away(connection):
    item = a_sealed(connection, copies=5)
    _published(connection, item, "Vinted", "Tilt")
    [tilt] = channel_ids(connection, "Tilt")

    channels.force_price(connection, item, tilt, 9900)
    exposure.align(connection, item, manual_channels.MANUAL)
    _do_what_is_left(connection)
    items.fix_price(connection, item, 12000)
    exposure.align(connection, item, manual_channels.MANUAL)

    assert _listings(connection, item) == [("Vinted", Status.ACTIVE, 12000, 1), ("Tilt", Status.ACTIVE, 9900, 5)]
    assert _actions(connection) == []
    channels.force_price(connection, item, tilt, None)
    exposure.align(connection, item, manual_channels.MANUAL)
    assert _actions(connection) == [("Tilt", ActionKind.UPDATE, item, 12000, 5)]


# The target from 20% to 30%: every item on sale gets its prices again. On Vinted, which keeps nothing, 130,00 € for
# a cost of 100,00 €, and 65,00 € for one of 50,00 €.
def test_a_target_margin_changed_leaves_an_action_to_update_the_listings_of_every_item_on_sale(connection):
    box = a_sealed(connection, copies=1)
    other_box = a_sealed(connection, copies=1, unit_cost_cents=5000)
    _published(connection, box, "Vinted")
    _published(connection, other_box, "Vinted")
    channels.change_target_margin(connection, Decimal("30"))

    exposure.align_every(connection, manual_channels.MANUAL)

    assert _actions(connection) == [
        ("Vinted", ActionKind.UPDATE, box, 13000, 1),
        ("Vinted", ActionKind.UPDATE, other_box, 6500, 1),
    ]


# A box whose cost is not known, on sale at the price fixed on it, which Manuel then takes away: no price is left to
# make, and any would be a guess. The listing keeps its own, and its copies still follow the stock.
def test_an_item_left_with_no_price_keeps_the_price_of_its_listings_while_their_copies_follow_its_stock(connection):
    item = a_sealed(connection, copies=5, unit_cost_cents=None)
    items.fix_price(connection, item, 12000)
    _published(connection, item, "Tilt")
    items.fix_price(connection, item, None)
    [lot] = stock.lots(connection, item)
    stock.adjust(connection, lot.id, -1, Cause.LOST)

    exposure.align(connection, item, manual_channels.MANUAL)

    assert _listings(connection, item) == [("Tilt", Status.TO_UPDATE, 12000, 4)]


# A price fixed left Tilt to update, then the last copy sold there, and Tilt closed the listing by itself: nothing is
# left to do on it, and the listing stays closed.
def test_an_action_left_on_a_listing_its_channel_closed_by_itself_leaves_the_list(connection):
    item = a_sealed(connection, copies=1)
    _published(connection, item, "Tilt")
    [on_tilt] = exposure.of_item(connection, item)
    items.fix_price(connection, item, 11000)
    exposure.align(connection, item, manual_channels.MANUAL)

    _sell(connection, item, "Tilt", copies=1)

    assert _actions(connection) == []
    assert exposure.one(connection, on_tilt.id).status == Status.CLOSED


VINTED_LINK = "https://www.vinted.it/items/5123456789-booster-box"


def a_sealed(connection, copies: int, unit_cost_cents: int | None = 10000) -> int:
    item = items.add(connection, Item(kind=Kind.SEALED, game="Pokémon", name="Booster box", language="it"))
    stock.load(connection, item, quantity=copies, unit_cost_cents=unit_cost_cents)
    return item


def channel_ids(connection, *names: str) -> list[int]:
    by_name = {channel.name: channel.id for channel in channels.every(connection)}
    return [by_name[name] for name in names]


def _published(connection, item: int, *names: str) -> None:
    """The item put on sale on those channels, and published on each by Manuel, with its link."""
    exposure.put_on_sale(connection, item, channel_ids(connection, *names), manual_channels.MANUAL)
    _do_what_is_left(connection)


def _do_what_is_left(connection) -> None:
    """Manuel does every action left, and pastes the link of each listing he publishes."""
    for actions in manual_channels.pending(connection).values():
        for action in actions:
            link = f"https://manual.test/{action.listing.id}" if action.kind == ActionKind.PUBLISH else None
            manual_channels.done(connection, action.id, link=link)


def _sell(connection, item: int, channel: str, copies: int) -> None:
    """Copies of the item sold on the channel: they leave its lot, then the exposure hears of the sale."""
    [lot] = stock.lots(connection, item)
    stock.unload(connection, lot.id, copies, Cause.SALE)
    [channel_id] = channel_ids(connection, channel)
    exposure.sold(connection, item, channel_id, copies, manual_channels.MANUAL)


def _listings(connection, item: int) -> list[tuple]:
    """Each listing of the item: its channel, its state, its price and the copies it offers."""
    return [
        (listing.channel, listing.status, listing.price_cents, listing.quantity)
        for listing in exposure.of_item(connection, item)
    ]


def _actions(connection) -> list[tuple]:
    """Each action left to do, channel after channel: what to do, and the item, price and copies of its listing."""
    return [
        (channel, action.kind, action.listing.item_id, action.listing.price_cents, action.listing.quantity)
        for channel, actions in manual_channels.pending(connection).items()
        for action in actions
    ]
