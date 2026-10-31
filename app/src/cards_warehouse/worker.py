"""The worker: a second component from the app's image, which asks the channels with an API again what they did not
answer. A Deployment of its own runs it (chart/templates/worker.yaml)."""

import time
from collections.abc import Mapping
from datetime import UTC, datetime

import httpx
from sqlalchemy import Engine

from cards_warehouse import channel_queue, ebay, photos
from cards_warehouse.database import create_database_engine
from cards_warehouse.ebay_channel import EbayChannel, SellerSetup
from cards_warehouse.exposure import ChannelOperations

# How often it looks for an operation whose wait is over: the shortest wait is a minute.
ROUND_SECONDS = 30


def channels_through_api(http: httpx.Client, store: photos.Store) -> dict[str, ChannelOperations]:
    """The adapter of each channel the app acts on through its API, with the values from Infisical: eBay's."""
    account = ebay.account_from_environment(http, time.monotonic)
    return {"eBay": EbayChannel(account, SellerSetup.from_environment(), store)}


def run_round(engine: Engine, adapters: Mapping[str, ChannelOperations], now: datetime) -> None:
    """Every operation whose wait is over, asked again. Each in a transaction of its own: a sale recorded meanwhile
    waits only for the one the worker is asking about, when it is on the same listing."""
    while True:
        with engine.begin() as connection:
            if not channel_queue.retry_next(connection, adapters, now):
                return


if __name__ == "__main__":
    # What the worker's pod runs. A database that does not answer stops it, and Kubernetes starts it again.
    engine = create_database_engine()
    adapters = channels_through_api(httpx.Client(timeout=10), photos.S3Store.from_environment())
    print(f"The worker looks for operations to ask again every {ROUND_SECONDS} s.", flush=True)
    while True:
        run_round(engine, adapters, datetime.now(UTC))
        time.sleep(ROUND_SECONDS)
