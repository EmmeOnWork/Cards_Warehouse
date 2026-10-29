"""The operations of every channel behind one object: the pages hand it to the exposure for any channel, and it
asks each channel's own. Through the channel's API when the channel is set to it and the app has an adapter for that
API, such as eBay's; through Manuel otherwise."""

from collections.abc import Mapping

from sqlalchemy import Connection

from cards_warehouse import channels, manual_channels
from cards_warehouse.exposure import ChannelOperations, Listing


class ByChannel:
    def __init__(self, adapters: Mapping[str, ChannelOperations]) -> None:
        # By the name of the channel whose API each one uses.
        self._adapters = adapters

    def has_api(self, channel_name: str) -> bool:
        """Whether the channel can be set to publish through its API."""
        return channel_name in self._adapters

    def publish(self, connection: Connection, listing: Listing) -> str | None:
        return self._of(connection, listing, "publish").publish(connection, listing)

    def update(self, connection: Connection, listing: Listing) -> bool:
        return self._of(connection, listing, "update").update(connection, listing)

    def close(self, connection: Connection, listing: Listing) -> bool:
        return self._of(connection, listing, "close").close(connection, listing)

    # An adapter does one operation after another: eBay's publishes, and updates and closes from tasks 34 and 35.
    # What it cannot do yet is left to Manuel, as on a manual channel.
    def _of(self, connection: Connection, listing: Listing, operation: str) -> ChannelOperations:
        channel = channels.named(connection, listing.channel)
        adapter = self._adapters.get(channel.name)
        if channel.publishes_through_api and hasattr(adapter, operation):
            return adapter
        return manual_channels.MANUAL
