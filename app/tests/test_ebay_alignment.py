"""eBay kept in line with its item by the app: a price or a stock that changes reaches the eBay listing by itself,
through the same queue as a sale elsewhere, and leaves Manuel nothing to do there.

Through the app's HTTP routes, on a real PostgreSQL, with a fake eBay that answers as the sandbox does.
"""

from datetime import timedelta

import pytest

from tests.fake_ebay import FakeEbay
from tests.fake_photos import FakePhotoStore
from tests.pages import buttons, checkboxes, choices, links, sections, table_rows, text
from tests.test_ebay_closing import _on_sale, _worker_round
from tests.test_ebay_publishing import publish_through_the_api, signed_in_selling_on_ebay
from tests.test_putting_on_sale import BOOSTER_BOX, FRONT

# The login reads the password from the database: every test has one.
pytestmark = pytest.mark.usefixtures("database")


# eBay keeps nothing of a price: the listing goes from the 120,00 € of the target to the 130,00 € fixed, at once.
def test_a_price_fixed_brings_the_ebay_listing_to_it_by_itself(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, BOOSTER_BOX, "eBay")
    fix, _ = buttons(client.get(item_page).text)["Fissa il prezzo"]

    client.post(fix, data={"fixed_price": "130,00"})

    [on_ebay] = fake_ebay.listings
    assert on_ebay.price == ("130.00", "EUR")
    assert _ebay_listing(client, item_page) == ["eBay", "attivo", "130,00 €", "5"]
    assert "eBay" not in sections(client.get("/actions").text)


# A promotion on eBay at 99,00 €, then over: the listing goes to it and back to the 120,00 € of the target, at once.
def test_a_price_forced_on_ebay_and_taken_away_brings_the_ebay_listing_to_it_and_back_by_itself(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, BOOSTER_BOX, "eBay")
    page = client.get(item_page).text
    force, _ = buttons(page)["Forza il prezzo"]

    client.post(force, data={"channel": choices(page, "channel")["eBay"], "forced_price": "99,00"})

    [on_ebay] = fake_ebay.listings
    assert on_ebay.price == ("99.00", "EUR")
    take_away, sent = buttons(client.get(item_page).text)["Togli il prezzo forzato su eBay"]
    client.post(take_away, data=sent)
    [on_ebay] = fake_ebay.listings
    assert on_ebay.price == ("120.00", "EUR")
    assert _ebay_listing(client, item_page) == ["eBay", "attivo", "120,00 €", "5"]
    assert "eBay" not in sections(client.get("/actions").text)


# eBay keeps 5% + 0,50 € now: 126,85 € leaves the 120,00 € of the target, and the listing is there at once.
def test_a_fee_of_ebay_changed_brings_the_ebay_listing_to_its_new_price_by_itself(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, BOOSTER_BOX, "eBay")
    ebay = links(client.get("/channels").text)["eBay"]

    client.post(ebay, data={"fee_percent": "5", "fee_fixed": "0,50"})

    [on_ebay] = fake_ebay.listings
    assert on_ebay.price == ("126.85", "EUR")
    assert _ebay_listing(client, item_page) == ["eBay", "attivo", "126,85 €", "5"]
    assert "eBay" not in sections(client.get("/actions").text)


# Two of five lost: eBay offers the three left at once. The other three lost: the eBay listing ends.
def test_adjustments_bring_the_ebay_listing_to_the_copies_left_and_end_it_once_none_is(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, BOOSTER_BOX, "eBay")
    movements = links(client.get(item_page).text)["Movimenti e rettifiche"]

    client.post(movements, data={"lot": "1", "cause": "lost", "quantity": "2"})

    [on_ebay] = fake_ebay.listings
    assert (on_ebay.quantity, on_ebay.ended) == (3, False)
    assert _ebay_listing(client, item_page) == ["eBay", "attivo", "120,00 €", "3"]
    client.post(movements, data={"lot": "1", "cause": "lost", "quantity": "3"})
    [on_ebay] = fake_ebay.listings
    assert on_ebay.ended
    assert "Non è in vendita su nessun canale." in text(client.get(item_page).text)
    assert "eBay" not in sections(client.get("/actions").text)


# A box opened into 36 packs, which go on sale on eBay; then a second box into the same packs, a new lot of theirs:
# eBay offers all 72 at once.
def test_a_new_lot_brings_the_ebay_listing_to_its_copies_by_itself(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    box_page = client.post("/items", data=BOOSTER_BOX).url.path
    opening = links(client.get(box_page).text)["Apri in buste"]
    packs = {"lot": "1", "packs": "36", "pack": "", "pack_name": "Busta Evoluzioni a Paldea"}
    packs_page = client.post(opening, data=packs).url.path
    _on_ebay(client, packs_page)

    client.post(opening, data={"lot": "1", "packs": "36", "pack": packs_page.removeprefix("/items/")})

    [on_ebay] = fake_ebay.listings
    assert on_ebay.quantity == 72
    assert _ebay_listing(client, packs_page)[:2] == ["eBay", "attivo"]
    assert "eBay" not in sections(client.get("/actions").text)


# Off eBay, by Manuel's choice: the eBay listing ends at once, and eBay is offered again to put it on sale.
def test_an_item_withdrawn_from_ebay_ends_the_ebay_listing_by_itself(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, BOOSTER_BOX, "eBay")
    withdraw, sent = buttons(client.get(item_page).text)["Ritira da eBay"]

    client.post(withdraw, data=sent)

    [on_ebay] = fake_ebay.listings
    assert on_ebay.ended
    page = client.get(item_page).text
    assert "Non è in vendita su nessun canale." in text(page)
    assert "eBay" in checkboxes(page, "channel")
    assert "eBay" not in sections(client.get("/actions").text)


# eBay does not answer when the price is fixed: the update waits in sight, and the worker brings eBay to 130,00 € once
# it answers.
def test_a_price_ebay_does_not_answer_waits_in_the_queue_and_the_worker_brings_ebay_to_it(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, BOOSTER_BOX, "eBay")
    fix, _ = buttons(client.get(item_page).text)["Fissa il prezzo"]
    fake_ebay.fail("unreachable")

    client.post(fix, data={"fixed_price": "130,00"})

    assert _ebay_listing(client, item_page) == ["eBay", "da aggiornare", "130,00 €", "5"]
    actions = sections(client.get("/actions").text)
    assert list(links(actions["In attesa di nuovo tentativo"])) == ["Aggiorna su eBay Booster box Evoluzioni a Paldea"]
    assert "eBay" not in actions
    fake_ebay.fail(None)
    _worker_round(fake_ebay, photos, after=timedelta(minutes=1))
    [on_ebay] = fake_ebay.listings
    assert on_ebay.price == ("130.00", "EUR")
    assert _ebay_listing(client, item_page) == ["eBay", "attivo", "130,00 €", "5"]
    assert "In attesa di nuovo tentativo" not in sections(client.get("/actions").text)


# eBay down for hours when the price is fixed at 130,00 €: the update is Manuel's, in red. eBay back, a new price of
# 125,00 € reaches it at once, with the copies: there is nothing left for Manuel to do on eBay, and nothing in red.
def test_an_update_left_to_manuel_goes_once_ebay_takes_a_later_one_by_itself(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, BOOSTER_BOX, "eBay")
    fix, _ = buttons(client.get(item_page).text)["Fissa il prezzo"]
    fake_ebay.fail("unreachable")
    client.post(fix, data={"fixed_price": "130,00"})
    for hours in range(1, 7):
        _worker_round(fake_ebay, photos, after=timedelta(hours=hours))
    assert list(links(sections(client.get("/actions").text)["eBay"])) == ["Aggiorna Booster box Evoluzioni a Paldea"]
    fake_ebay.fail(None)

    client.post(fix, data={"fixed_price": "125,00"})

    [on_ebay] = fake_ebay.listings
    assert on_ebay.price == ("125.00", "EUR")
    listings = sections(client.get(item_page).text)["Annunci"]
    assert table_rows(listings)[0][:4] == ["eBay", "attivo", "125,00 €", "5"]
    assert "un'ora" not in text(listings)
    assert "eBay" not in sections(client.get("/actions").text)
    assert "su eBay non è riuscita" not in text(client.get("/").text)


# The same, with eBay still down at the new price of 125,00 €: the worker brings eBay to it once it answers, and there
# is nothing left for Manuel to do on eBay.
def test_an_update_left_to_manuel_goes_once_the_worker_brings_ebay_to_a_later_one(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, BOOSTER_BOX, "eBay")
    fix, _ = buttons(client.get(item_page).text)["Fissa il prezzo"]
    fake_ebay.fail("unreachable")
    client.post(fix, data={"fixed_price": "130,00"})
    for hours in range(1, 7):
        _worker_round(fake_ebay, photos, after=timedelta(hours=hours))

    client.post(fix, data={"fixed_price": "125,00"})
    fake_ebay.fail(None)
    _worker_round(fake_ebay, photos, after=timedelta(hours=7))

    [on_ebay] = fake_ebay.listings
    assert on_ebay.price == ("125.00", "EUR")
    listings = sections(client.get(item_page).text)["Annunci"]
    assert table_rows(listings)[0][:4] == ["eBay", "attivo", "125,00 €", "5"]
    assert "un'ora" not in text(listings)
    actions = sections(client.get("/actions").text)
    assert "eBay" not in actions
    assert "In attesa di nuovo tentativo" not in actions


def _on_ebay(client, item_page: str) -> None:
    """The item with a photo, put on sale on eBay, which publishes it by itself."""
    client.post(f"{item_page}/photos", files=[("photos", ("IMG_1.JPG", FRONT, "image/jpeg"))])
    put_on_sale, _ = buttons(client.get(item_page).text)["Metti in vendita"]
    publish_through_the_api(client, "eBay")
    client.post(put_on_sale, data={"channel": checkboxes(client.get(item_page).text, "channel")["eBay"]})


def _ebay_listing(client, item_page: str) -> list[str]:
    """The channel, the state, the price and the copies of the item's only listing, on eBay, on its page."""
    [row] = table_rows(sections(client.get(item_page).text)["Annunci"])
    return row[:4]
