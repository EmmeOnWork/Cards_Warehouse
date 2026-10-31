"""The operations of every channel behind one object: the pages hand it to the exposure for any channel, and it
asks each channel's own. Through the channel's API when the channel is set to it and the app has an adapter for that
API, such as eBay's; through Manuel otherwise. An update or a close the API did not answer waits in the queue, which
the worker asks again (channel_queue)."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from sqlalchemy import Connection

from cards_warehouse import channel_queue, channels, manual_channels
from cards_warehouse.exposure import ChannelOperations, Listing
from cards_warehouse.manual_channels import ActionKind


class ByChannel:
    def __init__(
        self, adapters: Mapping[str, ChannelOperations], now: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        # By the name of the channel whose API each one uses.
        self._adapters = adapters
        # When an operation the API did not answer starts to wait.
        self._now = now

    def has_api(self, channel_name: str) -> bool:
        """Whether the channel can be set to publish through its API."""
        return channel_name in self._adapters

    def publish(self, connection: Connection, listing: Listing) -> str | None:
        return self._of(connection, listing, "publish").publish(connection, listing)

    def update(self, connection: Connection, listing: Listing) -> bool:
        return self._done(connection, listing, ActionKind.UPDATE)

    def close(self, connection: Connection, listing: Listing) -> bool:
        return self._done(connection, listing, ActionKind.CLOSE)

    def _done(self, connection: Connection, listing: Listing, kind: ActionKind) -> bool:
        operations = self._of(connection, listing, kind)
        if operations is manual_channels.MANUAL:
            return getattr(operations, kind)(connection, listing)
        return channel_queue.attempt(connection, listing, kind, operations, self._now())

    # What an adapter cannot do is left to Manuel, as on a manual channel.
    def _of(self, connection: Connection, listing: Listing, operation: str) -> ChannelOperations:
        channel = channels.named(connection, listing.channel)
        adapter = self._adapters.get(channel.name)
        if channel.publishes_through_api and hasattr(adapter, operation):
            return adapter
        return manual_channels.MANUAL
