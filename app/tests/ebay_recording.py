"""eBay's answers, recorded once on the sandbox and replayed by the tests with no network: make ebay-record.

The same scenario runs both times. The seller is set up as make ebay-setup does it; a sealed box, a card not graded
and a graded card are published; the box is asked again, as Riprova does with a listing eBay has already; and eBay
lists the conditions of single cards, which tells whether the descriptors the app sends are eBay's. Recorded, it runs
on the sandbox, on a PostgreSQL of its own, with the photos at a public address. Replayed, it runs on the test's
database, and each request must be the one recorded at its place.

The answers of the token are not kept, nor any request: no credential, no link of the bucket reaches the file.
"""

import getpass
import io
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy import Connection

from cards_warehouse import channels, ebay_setup, exposure, items, photos, stock
from cards_warehouse.ebay import Account
from cards_warehouse.ebay_channel import EbayChannel, SellerSetup
from cards_warehouse.exposure import Listing, PublishRefused
from cards_warehouse.items import Card, Condition, Grading, Item, Kind, Sealed

RECORDING = Path(__file__).parent / "ebay_responses" / "sandbox.json"
TOKEN_PATH = "/identity/v1/oauth2/token"
CONDITIONS_PATH = "/sell/metadata/v1/marketplace/EBAY_IT/get_item_condition_policies"
# A picture that eBay can download over HTTPS, with no key: the bucket is private.
PUBLIC_PHOTO = "https://ir.ebaystatic.com/cr/v/c1/ebay-logo-1-1200x630-margin.png"
ITEMS = [
    Item(
        Kind.SEALED,
        "Pokémon",
        "Booster box Evoluzioni a Paldea",
        "it",
        details=Sealed("Booster box", "Evoluzioni a Paldea"),
    ),
    Item(Kind.SINGLE_CARD, "Pokémon", "Mew ex", "it", details=Card(Condition.NEAR_MINT, "151", "151/165")),
    Item(
        Kind.SINGLE_CARD, "Pokémon", "Charizard ex", "it", details=Card(Grading("PSA", Decimal(10)), "151", "199/165")
    ),
]


@dataclass(frozen=True)
class Outcome:
    setup: dict[str, str]
    # The box, the card and the graded card, as the app has them after publishing.
    listings: list[Listing]
    # The box asked again: its link, or why eBay refused.
    again: str
    # What eBay answered on the conditions of single cards.
    conditions: dict


class PublicPhotos:
    """A bucket where every photo opens at one public address."""

    def __init__(self, link: str) -> None:
        self._link = link

    def put(self, key, photo, content_type) -> None: ...

    def delete(self, key) -> None: ...

    def link(self, key: str) -> str:
        return self._link


def scenario(connection: Connection, account: Account, store, *, choose, postal_code: str, city: str) -> Outcome:
    values = ebay_setup.values_for_infisical(account, postal_code=postal_code, city=city, choose=choose)
    setup = SellerSetup(
        values["EBAY_FULFILLMENT_POLICY_ID"],
        values["EBAY_PAYMENT_POLICY_ID"],
        values["EBAY_RETURN_POLICY_ID"],
        values["EBAY_LOCATION_KEY"],
    )
    channel = EbayChannel(account, setup, store)
    on_ebay = [channels.named(connection, "eBay").id]
    published = []
    for item in ITEMS:
        item_id = items.add(connection, item)
        stock.load(connection, item_id, quantity=2, unit_cost_cents=1000)
        photos.attach(connection, store, item_id, io.BytesIO(b"photo"), "image/jpeg")
        exposure.put_on_sale(connection, item_id, on_ebay, channel)
        [listing] = exposure.of_item(connection, item_id)
        published.append(listing)
    try:
        again = channel.publish(connection, published[0])
    except PublishRefused as refusal:
        again = str(refusal)
    conditions = account.request("GET", account.api(CONDITIONS_PATH), params={"filter": "categoryIds:{183454}"}).json()
    return Outcome(values, published, again, conditions)


class Recording(httpx.BaseTransport):
    """eBay, the real one unless another is given, with each answer but the token's kept in order."""

    def __init__(self, ebay: httpx.BaseTransport | None = None) -> None:
        self._real = ebay or httpx.HTTPTransport()
        self.exchanges: list[dict] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._real.handle_request(request)
        content = response.read()
        if request.url.path != TOKEN_PATH:
            self.exchanges.append(
                {
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "body": json.loads(content) if content else None,
                }
            )
        return response


class Replay(httpx.BaseTransport):
    """eBay as recorded: each request gets the answer recorded at its place, and must be the request made there."""

    def __init__(self, exchanges: list[dict]) -> None:
        self._left = list(exchanges)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == TOKEN_PATH:
            return httpx.Response(200, json={"access_token": "replayed", "expires_in": 7200})
        if not self._left:
            raise AssertionError(f"{request.method} {request.url.path} was not recorded")
        recorded = self._left.pop(0)
        assert (request.method, request.url.path) == (recorded["method"], recorded["path"]), recorded
        if recorded["body"] is None:
            return httpx.Response(recorded["status"])
        return httpx.Response(recorded["status"], json=recorded["body"])


def recorded() -> dict:
    return json.loads(RECORDING.read_text(encoding="utf-8"))


def replayed(connection: Connection, recording: dict) -> Outcome:
    """The scenario on the test's database, against the answers recorded."""
    account = Account(
        environment="sandbox",
        client_id="replayed",
        client_secret="replayed",
        refresh_token="replayed",
        authorization_expires=datetime.now(UTC),
        http=httpx.Client(transport=Replay(recording["exchanges"])),
        clock=lambda: 0.0,
    )
    outcome = scenario(
        connection,
        account,
        PublicPhotos(PUBLIC_PHOTO),
        choose=lambda policies: recording["shipping_policy"],
        postal_code="00000",
        city="replayed",
    )
    return outcome


def document(recording: Recording, outcome: Outcome, chosen: list[str]) -> str:
    """The file of the answers: when, the shipping policy chosen among several, and the answers in their order."""
    shipping = chosen[0] if chosen else outcome.setup["EBAY_FULFILLMENT_POLICY_ID"]
    kept = {"recorded_on": f"{date.today()}", "shipping_policy": shipping, "exchanges": recording.exchanges}
    return json.dumps(kept, indent=2, ensure_ascii=False) + "\n"


def _record() -> None:
    from cards_warehouse.database import create_database_engine
    from cards_warehouse.migrate import migrate
    from tests.acceptance.containers import running_postgres

    # Never the real account: the scenario publishes three listings.
    print("Records eBay's answers on the sandbox. The values of Infisical, /app, of the sandbox:")
    client_id = input("Client ID (EBAY_CLIENT_ID): ").strip()
    client_secret = getpass.getpass("Client secret (EBAY_CLIENT_SECRET): ").strip()
    refresh_token = getpass.getpass("Durable credential (EBAY_REFRESH_TOKEN): ").strip()
    postal_code = input("Postal code the goods leave from: ").strip()
    city = input("City: ").strip()
    chosen = []

    def choose(policies: list[tuple[str, str]]) -> str:
        chosen.append(ebay_setup._choose_on_screen(policies))
        return chosen[-1]

    recording = Recording()
    with running_postgres() as environment, httpx.Client(transport=recording, timeout=30) as http:
        os.environ.update(environment)
        migrate()
        account = Account(
            environment="sandbox",
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            authorization_expires=datetime.now(UTC),
            http=http,
            clock=time.monotonic,
        )
        with create_database_engine().begin() as connection:
            try:
                outcome = scenario(
                    connection, account, PublicPhotos(PUBLIC_PHOTO), choose=choose, postal_code=postal_code, city=city
                )
            except ebay_setup.SetupFailed as failure:
                sys.exit(str(failure))
    RECORDING.parent.mkdir(exist_ok=True)
    RECORDING.write_text(document(recording, outcome, chosen), encoding="utf-8")
    print(f"\nRecorded {len(recording.exchanges)} answers in {RECORDING.relative_to(Path.cwd())}.")
    for listing in outcome.listings:
        print(f"- {listing.status}: {listing.link or listing.problem}")
    print(f"- asked again: {outcome.again}")


if __name__ == "__main__":
    _record()
