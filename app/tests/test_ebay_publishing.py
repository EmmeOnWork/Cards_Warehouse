"""Putting an item on sale on eBay once the channel publishes through eBay's API: the app publishes the listing by
itself, with the price, the texts and the photos, and leaves nothing for Manuel to do.

Through the app's HTTP routes, on a real PostgreSQL, with a fake eBay that answers as the sandbox does.
"""

import pytest
from fastapi.testclient import TestClient

from cards_warehouse.main import create_app
from tests.acceptance.containers import TEST_PASSWORD
from tests.fake_ebay import FULFILLMENT_POLICY_ID, LOCATION_KEY, PAYMENT_POLICY_ID, RETURN_POLICY_ID, FakeEbay
from tests.fake_photos import FakePhotoStore
from tests.pages import buttons, checkboxes, links, sections, table_rows, text
from tests.test_ebay import connect_account
from tests.test_putting_on_sale import BOOSTER_BOX, FRONT

# The login reads the password from the database: every test has one.
pytestmark = pytest.mark.usefixtures("database")


def test_an_item_put_on_sale_on_ebay_is_published_there_by_the_app_and_leaves_manuel_nothing_to_do(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = _signed_in(monkeypatch, fake_ebay, photos)
    _publish_through_the_api(client, "eBay")

    item_page = client.post("/items", data=BOOSTER_BOX).url.path
    client.post(f"{item_page}/photos", files=[("photos", ("IMG_1.JPG", FRONT, "image/jpeg"))])
    page = client.get(item_page).text
    put_on_sale, _ = buttons(page)["Metti in vendita"]
    client.post(put_on_sale, data={"channel": checkboxes(page, "channel")["eBay"]})

    [published] = fake_ebay.listings
    assert table_rows(sections(client.get(item_page).text)["Annunci"]) == [
        ["eBay", "attivo", "120,00 €", "5", f"https://sandbox.ebay.com/itm/{published.listing_id}"]
    ]
    assert "eBay" not in sections(client.get("/actions").text)
    assert (published.title, published.description, published.price, published.quantity, published.photos) == (
        "Booster box Evoluzioni a Paldea ITA Pokémon",
        "Booster box Evoluzioni a Paldea\n\nGioco: Pokémon\nLingua: Italiano",
        ("120.00", "EUR"),
        5,
        [FRONT],
    )


# eBay refuses a listing without a photo: the item's page says so on the listing, and once the photo is there one
# tap publishes it.
def test_a_listing_ebay_refuses_stays_to_publish_with_the_reason_and_is_published_once_fixed(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = _signed_in(monkeypatch, fake_ebay, photos)
    _publish_through_the_api(client, "eBay")
    item_page = client.post("/items", data=BOOSTER_BOX).url.path
    put_on_sale, _ = buttons(client.get(item_page).text)["Metti in vendita"]
    client.post(put_on_sale, data={"channel": checkboxes(client.get(item_page).text, "channel")["eBay"]})

    listings = sections(client.get(item_page).text)["Annunci"]
    assert table_rows(listings) == [["eBay", "da pubblicare", "120,00 €", "5", ""]]
    assert "eBay vuole almeno una foto: aggiungila, poi riprova." in text(listings)

    client.post(f"{item_page}/photos", files=[("photos", ("IMG_1.JPG", FRONT, "image/jpeg"))])
    again, _ = buttons(client.get(item_page).text)["Riprova su eBay"]
    client.post(again)

    [published] = fake_ebay.listings
    listings = sections(client.get(item_page).text)["Annunci"]
    assert table_rows(listings) == [
        ["eBay", "attivo", "120,00 €", "5", f"https://sandbox.ebay.com/itm/{published.listing_id}"]
    ]
    assert "riprova" not in text(listings)


# What make ebay-setup prints, for Infisical: the seller's policies on eBay Italy and where the goods leave from.
def set_up_selling(monkeypatch) -> None:
    monkeypatch.setenv("EBAY_FULFILLMENT_POLICY_ID", FULFILLMENT_POLICY_ID)
    monkeypatch.setenv("EBAY_PAYMENT_POLICY_ID", PAYMENT_POLICY_ID)
    monkeypatch.setenv("EBAY_RETURN_POLICY_ID", RETURN_POLICY_ID)
    monkeypatch.setenv("EBAY_LOCATION_KEY", LOCATION_KEY)


def _signed_in(monkeypatch, fake_ebay: FakeEbay, photos: FakePhotoStore) -> TestClient:
    connect_account(monkeypatch)
    set_up_selling(monkeypatch)
    client = TestClient(create_app(ebay_http=fake_ebay.http(), photo_store=photos))
    client.post("/login", data={"password": TEST_PASSWORD})
    return client


def _publish_through_the_api(client: TestClient, channel: str) -> None:
    """From the channel's page, the setting that makes the app publish there by itself."""
    channel_page = client.get(links(client.get("/channels").text)[channel]).text
    switch, fields = buttons(channel_page)["Pubblica da sola con l'API"]
    client.post(switch, data=fields)
