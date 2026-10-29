"""A channel the app acts on through an API, in memory: it publishes a listing at once, with a link of its own.
It stands for the automatic channels, such as eBay from task 33, in the tests."""

from sqlalchemy import Connection

from cards_warehouse.exposure import Listing


class InMemoryChannel:
    def __init__(self) -> None:
        self.published: list[Listing] = []
        self.updated: list[Listing] = []
        self.closed: list[Listing] = []

    def publish(self, connection: Connection, listing: Listing) -> str:
        self.published.append(listing)
        return f"https://channel.test/listings/{len(self.published)}"

    def update(self, connection: Connection, listing: Listing) -> bool:
        self.updated.append(listing)
        return True

    def close(self, connection: Connection, listing: Listing) -> bool:
        self.closed.append(listing)
        return True
