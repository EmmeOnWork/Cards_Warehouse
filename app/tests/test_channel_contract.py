"""What the operations of every channel do, as the rest of the app sees them. The same tests run on the manual
channel, which leaves the work to Manuel, on the one in memory that stands for a channel with an API, and on eBay's,
against a fake eBay.

On a real PostgreSQL, through the exposure module.
"""

import io

import pytest

from cards_warehouse import ebay, exposure, manual_channels, photos, stock
from cards_warehouse.ebay_channel import EbayChannel, SellerSetup
from cards_warehouse.exposure import Status
from cards_warehouse.stock import Cause
from tests.fake_channel import InMemoryChannel
from tests.fake_ebay import FakeEbay
from tests.test_access import FakeClock
from tests.test_ebay import connect_account
from tests.test_ebay_publishing import set_up_selling
from tests.test_exposure import a_sealed, channel_ids
from tests.test_putting_on_sale import FRONT


class _Manual:
    def __init__(self, monkeypatch, store) -> None:
        self.operations = manual_channels.MANUAL

    @staticmethod
    def do_what_is_left(connection) -> None:
        """Manuel does every action, and pastes the link of each listing he published."""
        for actions in manual_channels.pending(connection).values():
            for action in actions:
                manual_channels.done(connection, action.id, link=f"https://manual.test/{action.listing.id}")


class _InMemory:
    def __init__(self, monkeypatch, store) -> None:
        self.operations = InMemoryChannel()

    @staticmethod
    def do_what_is_left(connection) -> None:
        """Nothing: the channel did it all when asked."""


class _Ebay:
    """eBay's API, on a fake eBay that downloads the photos from the bucket's links."""

    def __init__(self, monkeypatch, store) -> None:
        connect_account(monkeypatch)
        set_up_selling(monkeypatch)
        account = ebay.account_from_environment(FakeEbay(photos=store.open).http(), FakeClock())
        self.operations = EbayChannel(account, SellerSetup.from_environment(), store)

    @staticmethod
    def do_what_is_left(connection) -> None:
        """Nothing: eBay has the listing live when the app asks."""


@pytest.fixture(params=[_Manual, _InMemory, _Ebay], ids=["manual", "in memory", "eBay"])
def channel(request, monkeypatch, photos):
    return request.param(monkeypatch, photos)


def test_a_listing_put_on_sale_is_active_at_its_link_once_what_the_channel_leaves_to_do_is_done(
    connection, channel, photos
):
    item = a_photographed_sealed(connection, photos, copies=2)

    exposure.put_on_sale(connection, item, channel_ids(connection, "eBay"), channel.operations)
    channel.do_what_is_left(connection)

    [listing] = exposure.of_item(connection, item)
    assert listing.status == Status.ACTIVE
    assert listing.link.startswith("https://")


# Lowering and closing a listing: eBay's API joins with task 34, until then its listings are lowered and closed by
# Manuel, through the actions.
@pytest.fixture(params=[_Manual, _InMemory], ids=["manual", "in memory"])
def lowering_channel(request, monkeypatch, photos):
    return request.param(monkeypatch, photos)


# One of two copies sold where the item is not listed, such as to a friend: Tilt's listing offers the one left.
def test_a_listing_offering_more_copies_than_are_left_offers_those_left_once_what_the_channel_leaves_to_do_is_done(
    connection, lowering_channel
):
    item = _listed_on_tilt(connection, lowering_channel, copies=2)

    _sold_on_vinted(connection, item, lowering_channel, copies=1)
    lowering_channel.do_what_is_left(connection)

    [listing] = exposure.of_item(connection, item)
    assert (listing.status, listing.quantity) == (Status.ACTIVE, 1)


def test_a_listing_whose_copies_are_all_sold_is_off_its_channel_once_what_the_channel_leaves_to_do_is_done(
    connection, lowering_channel
):
    item = _listed_on_tilt(connection, lowering_channel, copies=2)

    _sold_on_vinted(connection, item, lowering_channel, copies=2)
    lowering_channel.do_what_is_left(connection)

    assert exposure.of_item(connection, item) == []


def _listed_on_tilt(connection, channel, copies: int) -> int:
    item = a_sealed(connection, copies)
    exposure.put_on_sale(connection, item, channel_ids(connection, "Tilt"), channel.operations)
    channel.do_what_is_left(connection)
    return item


def _sold_on_vinted(connection, item: int, channel, copies: int) -> None:
    [lot] = stock.lots(connection, item)
    stock.unload(connection, lot.id, copies, Cause.SALE)
    exposure.sold(connection, item, *channel_ids(connection, "Vinted"), copies, channel.operations)


# A channel's listing shows the item: eBay refuses one without a photo.
def a_photographed_sealed(connection, store, copies: int) -> int:
    item = a_sealed(connection, copies)
    photos.attach(connection, store, item, io.BytesIO(FRONT), "image/jpeg")
    return item
