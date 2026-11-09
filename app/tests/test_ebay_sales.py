"""The sales made on eBay, read by the worker from eBay's orders and recorded by themselves within minutes: the other
channels are left what a sale recorded by hand leaves them.

Through the app's HTTP routes, on a real PostgreSQL, with a fake eBay that answers as the sandbox does.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text as sql_text

from cards_warehouse import worker
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.database import create_database_engine
from tests.fake_ebay import BUYER, FakeEbay
from tests.fake_photos import FakePhotoStore
from tests.pages import links, sections, table_rows, text
from tests.test_ebay_closing import _on_sale, _sold, _worker_round
from tests.test_ebay_publishing import signed_in_selling_on_ebay
from tests.test_putting_on_sale import BOOSTER_BOX

# The login reads the password from the database: every test has one.
pytestmark = pytest.mark.usefixtures("database")


# The only box, on sale on Vinted, Tilt and eBay, bought on eBay: a round of the worker later it is a sale on eBay,
# at the price paid, with the number of its order. Manuel is left to close the box on Vinted and Tilt.
def test_the_last_copy_bought_on_ebay_is_a_sale_by_itself_and_leaves_vinted_and_tilt_to_close(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, {**BOOSTER_BOX, "quantity": "1", "total_cost": "100"}, "Vinted", "Tilt", "eBay")
    [on_ebay] = fake_ebay.listings

    order = fake_ebay.buy(on_ebay.listing_id, quantity=1)
    _worker_round(fake_ebay, photos, after=timedelta(seconds=30))

    movements = client.get(links(client.get(item_page).text)["Movimenti e rettifiche"]).text
    sale = client.get(links(movements)["Vendita"]).text
    recorded = text(sections(sale)["Vendita"])
    assert "Canale eBay Copie 1 Prezzo " + on_ebay.price[0].replace(".", ",") + " €" in recorded
    assert recorded.endswith(f"Nota Ordine eBay {order}")
    assert list(links(sections(sale)["Da fare"])) == ["Chiudi su Vinted", "Chiudi su Tilt"]


# A listing Manuel made on eBay's own pages is of no item of the app: its order stays his to deal with, and the order of
# the app's listing, in the same read, is a sale all the same.
def test_an_order_of_a_listing_the_app_did_not_publish_is_left_out(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, BOOSTER_BOX, "eBay")
    [on_ebay] = fake_ebay.listings
    fake_ebay.buy_listed_by_hand("Lotto di 100 carte comuni", price="15.00")
    fake_ebay.buy(on_ebay.listing_id, quantity=1)

    _worker_round(fake_ebay, photos, after=timedelta(seconds=30))

    movements = client.get(links(client.get(item_page).text)["Movimenti e rettifiche"]).text
    assert [row[1:] for row in table_rows(movements)] == [["Carico", "1", "+5"], ["Vendita", "1", "-1"]]
    assert "ordini" not in text(client.get("/").text)


# The only box sold on Tilt while eBay did not answer, so the eBay listing stayed open, and bought there meanwhile: the
# eBay order is a double sale, which takes nothing from the stock. The close waiting for eBay has nothing left to do,
# since eBay ended the listing with its last copy: it is not left to Manuel.
def test_an_ebay_order_of_copies_sold_out_is_a_double_sale(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, {**BOOSTER_BOX, "quantity": "1", "total_cost": "100"}, "Tilt", "eBay")
    [on_ebay] = fake_ebay.listings
    fake_ebay.fail("unreachable")
    _sold(client, item_page, channel="Tilt", copies="1", price="130")
    fake_ebay.fail(None)
    fake_ebay.buy(on_ebay.listing_id, quantity=1)

    _worker_round(fake_ebay, photos, after=timedelta(seconds=30))
    _worker_round(fake_ebay, photos, after=timedelta(hours=2))

    today = f"{datetime.now(LOCAL_TIME):%d/%m/%Y}"
    assert table_rows(client.get("/double-sales").text) == [[today, "eBay", "Booster box Evoluzioni a Paldea", "1"]]
    assert "Copie disponibili 0" in text(client.get(item_page).text)
    actions = sections(client.get("/actions").text)
    assert "eBay" not in actions
    assert "In attesa di nuovo tentativo" not in actions
    assert "non è riuscita" not in text(client.get("/").text)


# The box bought on eBay late last night, while eBay did not answer the app, and sold again on Tilt this morning: the
# eBay order, read once eBay answers, is a double sale of last night, the day the buyer bought it.
def test_an_order_read_late_keeps_the_day_it_was_made(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, {**BOOSTER_BOX, "quantity": "1", "total_cost": "100"}, "Tilt", "eBay")
    [on_ebay] = fake_ebay.listings
    last_night = datetime.now(LOCAL_TIME).replace(hour=23, minute=55) - timedelta(days=1)
    fake_ebay.buy(on_ebay.listing_id, quantity=1, at=last_night)
    fake_ebay.fail("unreachable")
    _sold(client, item_page, channel="Tilt", copies="1", price="130")
    fake_ebay.fail(None)

    _worker_round(fake_ebay, photos, after=timedelta(seconds=30))

    [[day, channel, _, _]] = table_rows(client.get("/double-sales").text)
    assert (day, channel) == (f"{last_night:%d/%m/%Y}", "eBay")


# Of the order the database has the number, and nothing of who bought: name, username, address, phone and email stay
# on eBay, in every table.
def test_nothing_of_the_buyer_reaches_the_database(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    _on_sale(client, BOOSTER_BOX, "eBay")
    [on_ebay] = fake_ebay.listings

    order = fake_ebay.buy(on_ebay.listing_id, quantity=1)
    _worker_round(fake_ebay, photos, after=timedelta(seconds=30))

    with create_database_engine().connect() as connection:
        tables = connection.execute(
            sql_text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        ).scalars()
        rows = " ".join(
            row
            for table in tables.all()
            for row in connection.execute(sql_text(f'SELECT row_to_json(t)::text FROM "{table}" t')).scalars()
        )
    assert order in rows
    assert [value for value in BUYER.values() if value in rows] == []


# Two boxes of five bought in one order: eBay gives it at every read for a while, and it is one sale all the same.
def test_an_order_read_again_is_still_one_sale(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, BOOSTER_BOX, "eBay")
    [on_ebay] = fake_ebay.listings
    fake_ebay.buy(on_ebay.listing_id, quantity=2)

    _worker_round(fake_ebay, photos, after=timedelta(seconds=30))
    _worker_round(fake_ebay, photos, after=timedelta(seconds=60))

    movements = client.get(links(client.get(item_page).text)["Movimenti e rettifiche"]).text
    assert [row[1:] for row in table_rows(movements)] == [["Carico", "1", "+5"], ["Vendita", "1", "-2"]]
    assert "Copie disponibili: 3" in text(movements)
    assert table_rows(client.get("/double-sales").text) == []


# eBay does not answer while a box is bought there: the home says it in red, from when. The read after, once eBay
# answers, finds the order all the same, and the home has nothing more to say.
def test_a_read_that_fails_shows_in_red_on_the_home_and_the_next_one_finds_the_order(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    item_page = _on_sale(client, BOOSTER_BOX, "eBay")
    [on_ebay] = fake_ebay.listings
    _worker_round(fake_ebay, photos, after=timedelta(seconds=30))
    fake_ebay.fail("unreachable")
    fake_ebay.buy(on_ebay.listing_id, quantity=1)

    failed_at = datetime.now(LOCAL_TIME) + timedelta(seconds=60)
    _worker_round(fake_ebay, photos, after=timedelta(seconds=60))

    home = client.get("/").text
    assert (
        f"Attenzione: l'app non legge gli ordini di eBay dalle {failed_at:%H:%M} del {failed_at:%d/%m}. "
        "eBay non risponde: le vendite fatte lì arrivano da sole appena risponde."
    ) in text(home)

    fake_ebay.fail(None)
    _worker_round(fake_ebay, photos, after=timedelta(seconds=90))

    movements = client.get(links(client.get(item_page).text)["Movimenti e rettifiche"]).text
    assert [row[1:] for row in table_rows(movements)] == [["Carico", "1", "+5"], ["Vendita", "1", "-1"]]
    assert "ordini" not in text(client.get("/").text)


# Not the orders of the last 90 days at every read, eBay's when it is not told: those made since the last read that
# worked, and a quarter of an hour before, for an order eBay shows late. One that failed does not count.
def test_each_read_asks_ebay_for_the_orders_since_the_last_one_that_worked(monkeypatch):
    photos = FakePhotoStore()
    fake_ebay = FakeEbay(photos=photos.open)
    client = signed_in_selling_on_ebay(monkeypatch, fake_ebay, photos)
    _on_sale(client, BOOSTER_BOX, "eBay")
    adapters = worker.channels_through_api(fake_ebay.http(), photos)
    first = datetime.now(UTC).replace(microsecond=0)

    worker.run_round(create_database_engine(), adapters, first)
    fake_ebay.fail("unreachable")
    worker.run_round(create_database_engine(), adapters, first + timedelta(seconds=30))
    fake_ebay.fail(None)
    worker.run_round(create_database_engine(), adapters, first + timedelta(seconds=60))
    worker.run_round(create_database_engine(), adapters, first + timedelta(seconds=90))

    assert fake_ebay.orders_asked_since == [
        None,
        first - timedelta(minutes=15),
        first + timedelta(seconds=60) - timedelta(minutes=15),
    ]
