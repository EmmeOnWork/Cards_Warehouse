"""Which operations a channel gets: those of a manual channel, unless it is set to publish through its API and the
app has an adapter for that API. The rest of the app asks the same object for every channel.

On a real PostgreSQL, through the exposure module.
"""

from cards_warehouse import channels, exposure, manual_channels
from cards_warehouse.channel_operations import ByChannel
from cards_warehouse.manual_channels import ActionKind
from tests.fake_channel import InMemoryChannel
from tests.test_exposure import a_sealed, channel_ids


def test_a_channel_set_to_publish_through_its_api_is_published_by_the_app_and_the_others_leave_actions(connection):
    item = a_sealed(connection, copies=1)
    [ebay] = channel_ids(connection, "eBay")
    channels.publish_through_api(connection, ebay, True)
    api = InMemoryChannel()

    exposure.put_on_sale(connection, item, channel_ids(connection, "Tilt", "eBay"), ByChannel({"eBay": api}))

    assert [listing.channel for listing in api.published] == ["eBay"]
    assert list(manual_channels.pending(connection)) == ["Tilt"]


# eBay's adapter publishes, and from tasks 34 and 35 it updates and closes too: until then those are left to Manuel.
def test_an_operation_the_adapter_cannot_do_yet_is_left_to_manuel_as_an_action(connection):
    item = a_sealed(connection, copies=1)
    [ebay] = channel_ids(connection, "eBay")
    channels.publish_through_api(connection, ebay, True)
    operations = ByChannel({"eBay": _PublishingOnly()})
    exposure.put_on_sale(connection, item, [ebay], operations)
    [listing] = exposure.of_item(connection, item)

    done_at_once = operations.close(connection, listing)

    assert done_at_once is False
    assert [action.kind for action in manual_channels.pending(connection)["eBay"]] == [ActionKind.CLOSE]


class _PublishingOnly:
    """An adapter as eBay's is in task 33: it publishes, and nothing else yet."""

    def publish(self, connection, listing) -> str:
        return f"https://channel.test/listings/{listing.id}"


# The adapter is there from the start: until Manuel switches the channel, eBay stays manual like the others.
def test_a_channel_with_an_adapter_but_not_set_to_use_it_stays_manual(connection):
    item = a_sealed(connection, copies=1)
    api = InMemoryChannel()

    exposure.put_on_sale(connection, item, channel_ids(connection, "eBay"), ByChannel({"eBay": api}))

    assert api.published == []
    assert list(manual_channels.pending(connection)) == ["eBay"]
