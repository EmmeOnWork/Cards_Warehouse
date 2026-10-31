"""A channel the app acts on through an API, in memory: it publishes a listing at once, with a link of its own.
It stands for the automatic channels, such as eBay from task 33, in the tests."""

from sqlalchemy import Connection

from cards_warehouse.exposure import ChannelUnavailable, Listing, OperationRefused


class InMemoryChannel:
    def __init__(self) -> None:
        self.published: list[Listing] = []
        self.updated: list[Listing] = []
        self.closed: list[Listing] = []
        # False: it does not answer, as eBay in an outage, until a test sets it back.
        self.answering = True
        # Why it refuses every update and close, as eBay with the authorization revoked. None: it refuses nothing.
        self.refusal: str | None = None

    def publish(self, connection: Connection, listing: Listing) -> str:
        self.published.append(listing)
        return f"https://channel.test/listings/{len(self.published)}"

    def update(self, connection: Connection, listing: Listing) -> bool:
        self._answer()
        self.updated.append(listing)
        return True

    def close(self, connection: Connection, listing: Listing) -> bool:
        self._answer()
        self.closed.append(listing)
        return True

    def _answer(self) -> None:
        if not self.answering:
            raise ChannelUnavailable
        if self.refusal is not None:
            raise OperationRefused(self.refusal)
