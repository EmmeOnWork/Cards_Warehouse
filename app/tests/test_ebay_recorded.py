"""eBay's adapter against the answers the sandbox gave, recorded with make ebay-record: no network.

What the fake eBay cannot tell: that the app reads eBay's real answers, and that the categories, the conditions and
the descriptors it sends are those eBay takes. Until the answers are recorded those tests are skipped; the recording
itself is tried on the fake eBay.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text

from cards_warehouse.ebay import Account
from cards_warehouse.ebay_channel import CARD_CONDITIONS, GRADERS, OTHER_GRADER, grade_value
from cards_warehouse.exposure import Status
from tests.ebay_recording import (
    PUBLIC_PHOTO,
    RECORDING,
    PublicPhotos,
    Recording,
    document,
    recorded,
    replayed,
    scenario,
)
from tests.fake_ebay import CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, FakeEbay
from tests.test_access import FakeClock

on_the_sandbox = pytest.mark.skipif(not RECORDING.exists(), reason="no answers recorded yet: make ebay-record")


@on_the_sandbox
def test_the_seller_set_up_on_the_sandbox_gives_every_value_for_infisical(connection):
    outcome = replayed(connection, recorded())

    assert all(outcome.setup.values())


# A sealed box, a card not graded and a graded card: each in its category, with its condition.
@on_the_sandbox
def test_the_listings_published_on_the_sandbox_are_active_at_their_links(connection):
    outcome = replayed(connection, recorded())

    assert [(listing.status, listing.problem) for listing in outcome.listings] == [(Status.ACTIVE, None)] * 3
    assert all(listing.link.startswith("https://sandbox.ebay.com/itm/") for listing in outcome.listings)


# As Riprova does with a listing eBay has already: the offer eBay kept is taken up, and the listing stays the same.
@on_the_sandbox
def test_a_listing_asked_again_takes_up_the_offer_ebay_kept(connection):
    outcome = replayed(connection, recorded())

    assert outcome.again == outcome.listings[0].link


@on_the_sandbox
def test_the_descriptors_sent_for_single_cards_are_among_those_ebay_lists(connection):
    outcome = replayed(connection, recorded())

    sent = {*CARD_CONDITIONS.values(), *GRADERS.values(), OTHER_GRADER}
    sent |= {grade_value(Decimal(half) / 2) for half in range(2, 21)}
    assert sent <= set(_values_listed(outcome.conditions))


# make ebay-record on the fake eBay, then the file it writes replayed on a database just as new: the same outcome.
def test_answers_recorded_from_an_ebay_replay_to_the_same_outcome(connection):
    fake_ebay = FakeEbay(seller_set_up=False, photos=lambda link: b"photo")
    fake_ebay.create_shipping_policy("Lettera")
    parcel = fake_ebay.create_shipping_policy("Pacco tracciato")
    recording = Recording(fake_ebay.transport())
    account = Account(
        environment="sandbox",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        refresh_token=REFRESH_TOKEN,
        authorization_expires=datetime.now(UTC),
        http=httpx.Client(transport=recording),
        clock=FakeClock(),
    )
    live = scenario(
        connection,
        account,
        PublicPhotos(PUBLIC_PHOTO),
        choose=lambda policies: parcel,
        postal_code="20121",
        city="Milano",
    )
    written = json.loads(document(recording, live, [parcel]))
    # The items and their listings gone, and their numbers from 1 again, as on the database of a test.
    connection.execute(text("TRUNCATE items RESTART IDENTITY CASCADE"))

    assert replayed(connection, written) == live
    assert "access-token" not in json.dumps(written)


def _values_listed(answer) -> list[str]:
    """Every descriptor value in eBay's answer, wherever it is."""
    if isinstance(answer, dict):
        found = [answer["conditionDescriptorValueId"]] if "conditionDescriptorValueId" in answer else []
        return found + [value for nested in answer.values() for value in _values_listed(nested)]
    if isinstance(answer, list):
        return [value for nested in answer for value in _values_listed(nested)]
    return []
