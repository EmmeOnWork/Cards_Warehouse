"""The exposure module: the listings of the items on the channels, and what putting an item on sale leaves to do.

On a real PostgreSQL, through the module's functions, with every channel a manual one.
"""

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


VINTED_LINK = "https://www.vinted.it/items/5123456789-booster-box"


def a_sealed(connection, copies: int, unit_cost_cents: int | None = 10000) -> int:
    item = items.add(connection, Item(kind=Kind.SEALED, game="Pokémon", name="Booster box", language="it"))
    stock.load(connection, item, quantity=copies, unit_cost_cents=unit_cost_cents)
    return item


def channel_ids(connection, *names: str) -> list[int]:
    by_name = {channel.name: channel.id for channel in channels.every(connection)}
    return [by_name[name] for name in names]


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
