"""The numbers of the curriculum: how many items and sales the app handles, on how many channels, how many of them
through the API, and how many double sales it recorded, counted from the database for a period, each told how.

Through the app's HTTP routes, on a real PostgreSQL, with a fake eBay that answers as the sandbox does.
"""

from datetime import datetime, timedelta

import pytest

from cards_warehouse.backups import LOCAL_TIME
from tests.fake_ebay import FakeEbay
from tests.fake_photos import FakePhotoStore
from tests.pages import buttons, form_fields, links, sections, table_rows, text
from tests.test_ebay_closing import _on_sale, _worker_round
from tests.test_ebay_publishing import signed_in_selling_on_ebay
from tests.test_putting_on_sale import BOOSTER_BOX
from tests.test_sale_cancellation import _cancel
from tests.test_selling import MEW, sell

# The login reads the password from the database: every test has one.
pytestmark = pytest.mark.usefixtures("database")


# The only box, on sale on eBay, bought there: the worker reads the order through the API. Mew ex sold on Vinted, then
# bought on eBay too: a double sale, which is not a sale. A Pikachu sold on Tilt, a Charizard sold on Tilt and sent
# back: the return is not a sale, but Charizard was in the warehouse all the same. Four items, three sales, on three
# channels, eBay through the API, and one double sale.
def test_the_numbers_of_the_curriculum_are_counted_from_the_first_day_of_use_and_told_how(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    _on_sale(client, {**BOOSTER_BOX, "quantity": "1", "total_cost": "100"}, "eBay")
    [on_ebay] = fake_ebay.listings
    fake_ebay.buy(on_ebay.listing_id, quantity=1)
    _worker_round(fake_ebay, photos, after=timedelta(seconds=30))
    mew = client.post("/items", data=MEW).url.path
    sell(client, mew, channel="Vinted", quantity="1", price="60")
    sell(client, mew, channel="eBay", quantity="1", price="60")
    pikachu = client.post("/items", data={**MEW, "name": "Pikachu"}).url.path
    sell(client, pikachu, channel="Tilt", quantity="1", price="30")
    charizard = client.post("/items", data={**MEW, "name": "Charizard"}).url.path
    _cancel(client, sell(client, charizard, channel="Tilt", quantity="1", price="90").text, cause="Reso")

    page = client.get(links(client.get("/reports").text)["Numeri del curriculum"])

    numbers = sections(page.text)["Numeri del curriculum"]
    assert table_rows(numbers) == [
        ["Articoli gestiti", "4"],
        ["Vendite", "3"],
        ["Canali con almeno una vendita", "3 Vinted, Tilt, eBay"],
        ["Canali sincronizzati via API", "1 eBay"],
        ["Doppie vendite", "1"],
    ]
    told = text(sections(page.text)["Come si contano"])
    assert "Articoli gestiti Gli articoli con almeno una copia in magazzino in qualche momento del periodo" in told
    assert "Doppie vendite Gli ordini arrivati su copie già vendute altrove" in told


# Mew ex sold on Vinted today: the file to record in the repository has the numbers of the period, when they were
# counted, by which version of the app, and how each is counted, as the page tells it.
def test_the_numbers_download_in_a_file_with_the_day_they_were_counted_and_how(signed_in_client):
    sell(signed_in_client, signed_in_client.post("/items", data=MEW).url.path, channel="Vinted", price="60")
    page = signed_in_client.get("/reports/numbers").text
    today = datetime.now(LOCAL_TIME).date()

    download = signed_in_client.get(links(page)["Scarica in JSON"])

    assert download.headers["content-disposition"] == f'attachment; filename="numeri-{today}-{today}.json"'
    recorded = download.json()
    assert datetime.fromisoformat(recorded.pop("counted_at")).astimezone(LOCAL_TIME).date() == today
    how = recorded.pop("how")
    assert recorded == {
        "first_day": f"{today}",
        "last_day": f"{today}",
        "version": "dev",
        "items": 1,
        "sales": 1,
        "channels": ["Vinted"],
        "through_api": [],
        "doubles": 0,
    }
    assert list(how) == ["items", "sales", "channels", "through_api", "doubles"]
    assert how["items"].startswith("Gli articoli con almeno una copia in magazzino")


# Mew ex loaded and sold today: a period of yesterday alone has none of it. The days stay in the form, and the file to
# download is of them.
def test_the_numbers_of_a_period_chosen_are_counted_from_its_first_day_to_its_last(signed_in_client):
    sell(signed_in_client, signed_in_client.post("/items", data=MEW).url.path, channel="Vinted", price="60")
    show, _ = buttons(signed_in_client.get("/reports/numbers").text)["Mostra"]
    yesterday = f"{datetime.now(LOCAL_TIME).date() - timedelta(days=1)}"

    page = signed_in_client.get(show, params={"first_day": yesterday, "last_day": yesterday}).text

    numbers = sections(page)["Numeri del curriculum"]
    assert table_rows(numbers) == [
        ["Articoli gestiti", "0"],
        ["Vendite", "0"],
        ["Canali con almeno una vendita", "0"],
        ["Canali sincronizzati via API", "0"],
        ["Doppie vendite", "0"],
    ]
    assert form_fields(numbers) == {"first_day": [yesterday], "last_day": [yesterday]}
    assert signed_in_client.get(links(numbers)["Scarica in JSON"]).json()["first_day"] == yesterday


# The days come back in the form, for Manuel to fix the one he got wrong.
def test_a_period_whose_first_day_comes_after_its_last_is_refused_with_the_days_typed(signed_in_client):
    refused = signed_in_client.get("/reports/numbers", params={"first_day": "2026-10-31", "last_day": "2026-10-01"})

    assert refused.status_code == 422
    numbers = sections(refused.text)["Numeri del curriculum"]
    assert "Il primo giorno viene dopo l'ultimo." in text(numbers)
    assert form_fields(numbers) == {"first_day": ["2026-10-31"], "last_day": ["2026-10-01"]}
    assert table_rows(numbers) == []
