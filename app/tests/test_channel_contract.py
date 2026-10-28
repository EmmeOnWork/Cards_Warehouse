"""What the operations of every channel do, as the rest of the app sees them. The same tests run on the manual
channel, which leaves the work to Manuel, and on the one in memory that stands for a channel with an API; on eBay's
too, from task 33.

On a real PostgreSQL, through the exposure module.
"""

import pytest

from cards_warehouse import exposure, manual_channels
from cards_warehouse.exposure import Status
from tests.fake_channel import InMemoryChannel
from tests.test_exposure import a_sealed, channel_ids


class _Manual:
    operations = manual_channels.MANUAL

    @staticmethod
    def do_what_is_left(connection) -> None:
        """Manuel does every action, and pastes the link of each listing he published."""
        for actions in manual_channels.pending(connection).values():
            for action in actions:
                manual_channels.done(connection, action.id, link=f"https://manual.test/{action.listing.id}")


class _InMemory:
    def __init__(self) -> None:
        self.operations = InMemoryChannel()

    @staticmethod
    def do_what_is_left(connection) -> None:
        """Nothing: the channel did it all when asked."""


@pytest.fixture(params=[_Manual, _InMemory], ids=["manual", "in memory"])
def channel(request):
    return request.param()


def test_a_listing_put_on_sale_is_active_at_its_link_once_what_the_channel_leaves_to_do_is_done(connection, channel):
    item = a_sealed(connection, copies=2)

    exposure.put_on_sale(connection, item, channel_ids(connection, "Tilt"), channel.operations)
    channel.do_what_is_left(connection)

    [listing] = exposure.of_item(connection, item)
    assert listing.status == Status.ACTIVE
    assert listing.link.startswith("https://")
