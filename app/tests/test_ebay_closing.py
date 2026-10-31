"""eBay lowered or closed by the app the moment a sale elsewhere leaves it offering too much: the double sale that
happens most often, a piece sold on Vinted or Tilt and bought again on eBay.

Through the app's HTTP routes, on a real PostgreSQL, with a fake eBay that answers as the sandbox does.
"""

from datetime import UTC, datetime, timedelta

import pytest

from cards_warehouse import worker
from cards_warehouse.database import create_database_engine
from tests.fake_ebay import FakeEbay
from tests.fake_photos import FakePhotoStore
from tests.pages import buttons, checkboxes, links, sections, table_rows, text
from tests.test_ebay_publishing import publish_through_the_api, signed_in_selling_on_ebay
from tests.test_putting_on_sale import BOOSTER_BOX, FRONT

# The login reads the password from the database: every test has one.
pytestmark = pytest.mark.usefixtures("database")


# One of five boxes sold on Vinted: eBay offers the four left at once, and leaves Manuel nothing to do there.
def test_a_sale_on_vinted_lowers_the_ebay_listing_by_itself_to_the_copies_left(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, BOOSTER_BOX, "Vinted", "eBay")

    sold = _sold(client, item_page, channel="Vinted", copies="1", price="120")

    [on_ebay] = fake_ebay.listings
    assert on_ebay.quantity == 4
    assert list(links(sections(sold.text)["Da fare"])) == ["Pubblica su Vinted"]
    assert table_rows(sections(client.get(item_page).text)["Annunci"])[-1] == [
        "eBay",
        "attivo",
        "120,00 €",
        "4",
        f"https://sandbox.ebay.com/itm/{on_ebay.listing_id}",
    ]


# The only box, sold on Tilt: the eBay listing ends at once, and no one can buy it there anymore.
def test_the_last_copy_sold_on_tilt_ends_the_ebay_listing_by_itself(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, {**BOOSTER_BOX, "quantity": "1", "total_cost": "100"}, "Tilt", "eBay")

    sold = _sold(client, item_page, channel="Tilt", copies="1", price="130")

    [on_ebay] = fake_ebay.listings
    assert on_ebay.ended
    assert text(sections(sold.text)["Da fare"]) == "Da fare Niente da fare: ogni annuncio offre solo le copie rimaste."
    assert "Non è in vendita su nessun canale." in text(client.get(item_page).text)


# eBay does not answer when the box is sold on Vinted: the pages say the app will try again, and the worker brings
# eBay to the four boxes left once it answers.
def test_an_operation_ebay_does_not_answer_waits_in_sight_and_the_worker_does_it_once_ebay_answers(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, BOOSTER_BOX, "Vinted", "eBay")
    fake_ebay.fail("unreachable")

    _sold(client, item_page, channel="Vinted", copies="1", price="120")

    listings = sections(client.get(item_page).text)["Annunci"]
    assert table_rows(listings)[-1][:4] == ["eBay", "da aggiornare", "120,00 €", "4"]
    assert "eBay non risponde: l'app ci riprova da sola, in attesa di nuovo tentativo." in text(listings)
    actions = sections(client.get("/actions").text)
    assert list(links(actions["In attesa di nuovo tentativo"])) == ["Aggiorna su eBay Booster box Evoluzioni a Paldea"]
    assert "eBay" not in actions
    assert "1 operazione su eBay in attesa di nuovo tentativo." in text(client.get("/").text)

    fake_ebay.fail(None)
    _worker_round(fake_ebay, photos, after=timedelta(minutes=1))

    [on_ebay] = fake_ebay.listings
    assert on_ebay.quantity == 4
    listings = sections(client.get(item_page).text)["Annunci"]
    assert table_rows(listings)[-1][:4] == ["eBay", "attivo", "120,00 €", "4"]
    assert "tentativo" not in text(listings)
    assert "In attesa di nuovo tentativo" not in sections(client.get("/actions").text)
    assert "tentativo" not in text(client.get("/").text)


# eBay down for over an hour after the only box sold on Tilt: the worker asks again after 1, 2, 4, 8, 16 and 32 minutes,
# never before. Then the close is Manuel's, in red in Da fare and on the home, with eBay's listing still open.
def test_an_operation_ebay_does_not_answer_for_an_hour_is_left_to_manuel_in_red(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, {**BOOSTER_BOX, "quantity": "1", "total_cost": "100"}, "Tilt", "eBay")
    fake_ebay.fail("unreachable")
    _sold(client, item_page, channel="Tilt", copies="1", price="130")

    elapsed = timedelta()
    for wait in [timedelta(minutes=minutes) for minutes in (1, 2, 4, 8, 16, 32)]:
        asked = fake_ebay.unanswered
        _worker_round(fake_ebay, photos, after=elapsed + wait - timedelta(seconds=30))
        assert fake_ebay.unanswered == asked
        elapsed += wait
        _worker_round(fake_ebay, photos, after=elapsed)
        assert fake_ebay.unanswered == asked + 1

    reason = "eBay non ha risposto per un'ora: fallo a mano dall'app di eBay, poi spuntalo in Da fare."
    actions = sections(client.get("/actions").text)
    assert "In attesa di nuovo tentativo" not in actions
    assert list(links(actions["eBay"])) == ["Chiudi Booster box Evoluzioni a Paldea"]
    assert reason in text(actions["eBay"])
    listings = sections(client.get(item_page).text)["Annunci"]
    assert reason in text(listings)
    assert "Riprova su eBay" not in buttons(listings)
    assert "Attenzione: 1 operazione su eBay non è riuscita, da fare a mano: la trovi in Da fare." in text(
        client.get("/").text
    )
    [on_ebay] = fake_ebay.listings
    assert not on_ebay.ended


# Two boxes sold on Tilt, one at a time. eBay did not answer to the first sale, so the update to one box waits; it
# answers to the second, and the listing ends. The update waiting is not sent after: the listing stays ended.
def test_an_update_waiting_on_a_listing_is_never_sent_after_its_close(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, {**BOOSTER_BOX, "quantity": "2", "total_cost": "200"}, "Tilt", "eBay")
    fake_ebay.fail("unreachable")
    _sold(client, item_page, channel="Tilt", copies="1", price="130")
    fake_ebay.fail(None)

    _sold(client, item_page, channel="Tilt", copies="1", price="130")
    _worker_round(fake_ebay, photos, after=timedelta(hours=2))

    [on_ebay] = fake_ebay.listings
    assert (on_ebay.ended, on_ebay.quantity) == (True, 2)
    assert "Non è in vendita su nessun canale." in text(client.get(item_page).text)
    assert "In attesa di nuovo tentativo" not in sections(client.get("/actions").text)


def _on_sale(client, item: dict, *channels: str) -> str:
    """The page of an item with a photo, put on sale on those channels: eBay publishes it by itself, Manuel publishes
    it on the others and pastes the link."""
    item_page = client.post("/items", data=item).url.path
    client.post(f"{item_page}/photos", files=[("photos", ("IMG_1.JPG", FRONT, "image/jpeg"))])
    page = client.get(item_page).text
    put_on_sale, _ = buttons(page)["Metti in vendita"]
    offered = checkboxes(page, "channel")
    publish_through_the_api(client, "eBay")
    client.post(put_on_sale, data={"channel": [offered[channel] for channel in channels]})
    for channel in channels:
        if channel != "eBay":
            action = client.get(links(sections(client.get("/actions").text)[channel])[f"Pubblica {item['name']}"])
            published, _ = buttons(action.text)["Pubblicato"]
            client.post(published, data={"link": f"https://{channel.lower()}.test/listing"})
    return item_page


def _worker_round(fake_ebay: FakeEbay, photos: FakePhotoStore, after: timedelta) -> None:
    """A round of the worker that long after now, on the database of the test."""
    adapters = worker.channels_through_api(fake_ebay.http(), photos)
    worker.run_round(create_database_engine(), adapters, datetime.now(UTC) + after)


def _sold(client, item_page: str, channel: str, copies: str, price: str):
    """The page of a sale Manuel recorded from the item's page."""
    form = client.get(links(client.get(item_page).text)["Vendi"])
    record, _ = buttons(form.text)["Registra la vendita"]
    sold_on = checkboxes(form.text, "channel")[channel]
    return client.post(record, data={"channel": sold_on, "quantity": copies, "price": price})
