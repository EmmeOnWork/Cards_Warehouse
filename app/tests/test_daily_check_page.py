"""The daily check in the app: what it found out of line between the stock, the listings and the actions, shown in
its page with the time it ran, and run by hand from there.

Through the app's HTTP routes, on a real PostgreSQL, with the app's clock fixed. What the check finds out of line
cannot come from the pages, which keep the listings in line with the stock: it is written straight to the database, as
a fault would leave it.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from cards_warehouse import manual_channels, stock
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.database import create_database_engine
from cards_warehouse.main import create_app
from cards_warehouse.stock import Cause
from tests.acceptance.containers import TEST_PASSWORD
from tests.fake_photos import FakePhotoStore
from tests.pages import buttons, checkboxes, form_fields, links, sections, table_rows, text

# 08:00 in Italy, on winter time since the 25th.
NOW = datetime(2026, 10, 29, 7, 0, tzinfo=UTC)

BOOSTER_BOX = {
    "kind": "sealed",
    "game": "Pokémon",
    "name": "Booster box Evoluzioni a Paldea",
    "language": "it",
    "quantity": "5",
    "total_cost": "500",
}
ETB = {
    "kind": "sealed",
    "game": "Pokémon",
    "name": "Elite Trainer Box Scarlatto e Violetto",
    "language": "it",
    "quantity": "1",
    "total_cost": "60",
}
MEW = {
    "kind": "single_card",
    "game": "Pokémon",
    "name": "Mew ex",
    "language": "it",
    "quantity": "1",
    "total_cost": "50",
    "set_name": "151",
    "number": "151/165",
    "condition": "near_mint",
}
VINTED_LINK = "https://www.vinted.it/items/5123456789-elite-trainer-box"


@pytest.fixture
def client(database) -> TestClient:
    return signed_in(now=NOW)


# Tilt offered all five, then three were lost and the listing did not follow: the check finds it.
def test_a_listing_offering_more_copies_than_are_left_is_found_by_a_check_run_by_hand(client):
    item_page = _on_sale(client, BOOSTER_BOX, "Tilt")
    _lost_unseen(item_page, copies=3)

    run, _ = buttons(client.get("/check").text)["Controlla adesso"]
    page = client.post(run)

    assert "Ultimo controllo: 29/10 alle 08:00." in text(page.text)
    found = sections(page.text)["Annunci con più copie di quelle rimaste"]
    assert table_rows(found) == [[BOOSTER_BOX["name"], "Tilt", "5", "2"]]


# The CronJob runs every day: a last check older than a day means one did not run. A day exactly is still on time.
# Silence would look like nothing to worry about: no check at all is said too.
def test_the_page_warns_when_no_check_ran_for_more_than_a_day(client):
    nothing_yet = text(client.get("/check").text)
    client.post("/check")

    on_time = text(signed_in(now=NOW + timedelta(days=1)).get("/check").text)
    late = text(signed_in(now=NOW + timedelta(days=1, seconds=1)).get("/check").text)

    assert "Attenzione: nessun controllo finora." in nothing_yet
    assert "Ultimo controllo: 29/10 alle 08:00." in on_time
    assert "Attenzione: nessun controllo da più di un giorno. L'ultimo è del 29/10 alle 08:00." in late


# Each kind of thing found in its own section, with what Manuel needs to fix it and a link to where he fixes it.
# Sixty-one days after the box was put on sale on Tilt: past the thresholds, of three days and sixty.
def test_the_page_shows_what_the_check_found_of_each_kind_with_links_to_fix_it(database):
    first_day = signed_in(now=NOW)
    box_page = _on_sale(first_day, BOOSTER_BOX, "Tilt")
    _lost_unseen(box_page, copies=3)
    etb_page = _on_sale(first_day, ETB, "Vinted")
    published, _ = buttons(_action(first_day, "Vinted", ETB["name"]).text)["Pubblicato"]
    first_day.post(published, data={"link": VINTED_LINK})
    _lost_unseen(etb_page, copies=1)
    mew_page = first_day.post("/items", data=MEW).url.path
    with create_database_engine().connect() as connection:
        [to_publish] = manual_channels.pending(connection)["Tilt"]
    to_do = links(sections(first_day.get("/actions").text)["Tilt"])[f"Pubblica {BOOSTER_BOX['name']}"]
    made = f"{to_publish.created_at.astimezone(LOCAL_TIME):%d/%m/%Y}"
    later = signed_in(now=to_publish.created_at + timedelta(days=61))

    page = later.post("/check").text

    found = sections(page)
    assert table_rows(found["Annunci con più copie di quelle rimaste"]) == [[BOOSTER_BOX["name"], "Tilt", "5", "2"]]
    assert table_rows(found["Annunci aperti su articoli esauriti"]) == [[ETB["name"], "Vinted", "attivo"]]
    assert table_rows(found["Azioni in sospeso da troppo tempo"]) == [[f"Pubblica {BOOSTER_BOX['name']}", "Tilt", made]]
    assert table_rows(found["Articoli senza vendite da troppo tempo"]) == [
        [BOOSTER_BOX["name"], made, "Tilt 122,96 €"],
        [MEW["name"], made, "Non in vendita"],
    ]
    shown = links(page)
    assert [shown[name] for name in (BOOSTER_BOX["name"], ETB["name"], MEW["name"])] == [box_page, etb_page, mew_page]
    assert shown[f"Pubblica {BOOSTER_BOX['name']}"] == to_do


# Sooner for the actions, later for the items. The form shows the thresholds in force: three days and sixty at first.
def test_the_thresholds_are_changed_from_the_page(client):
    page = client.get("/check").text
    in_force = form_fields(page)
    save, _ = buttons(page)["Salva le soglie"]

    client.post(save, data={"stale_action_days": "1", "unsold_item_days": "90"})

    assert in_force == {"stale_action_days": ["3"], "unsold_item_days": ["60"]}
    assert form_fields(client.get("/check").text) == {"stale_action_days": ["1"], "unsold_item_days": ["90"]}


# Typed back into the form, to fix; the thresholds in force stay as they were.
@pytest.mark.parametrize("typed", ["0", "tre", "1,5", ""])
def test_a_threshold_that_is_not_a_whole_number_of_days_is_refused(client, typed):
    response = client.post("/check/thresholds", data={"stale_action_days": typed, "unsold_item_days": "90"})

    assert response.status_code == 422
    assert "Le soglie sono giorni interi, almeno 1." in text(response.text)
    assert form_fields(response.text) == {"stale_action_days": [typed], "unsold_item_days": ["90"]}
    assert form_fields(client.get("/check").text) == {"stale_action_days": ["3"], "unsold_item_days": ["60"]}


# Opened the app, Manuel sees at once whether there is something to look at, under the backup's line, and the menu
# leads to the page of the check.
def test_the_home_says_what_the_last_check_found(client):
    nothing_yet = client.get("/").text
    client.post("/check")
    all_fine = text(client.get("/").text)
    item_page = _on_sale(client, BOOSTER_BOX, "Tilt")
    _lost_unseen(item_page, copies=3)
    client.post("/check")
    to_look_at = text(client.get("/").text)
    late = text(signed_in(now=NOW + timedelta(days=2)).get("/").text)

    assert "Attenzione: nessun controllo finora." in text(nothing_yet)
    assert "Controllo del 29/10 alle 08:00: tutto in ordine." in all_fine
    assert "Attenzione: il controllo del 29/10 alle 08:00 ha trovato 1 cosa da guardare." in to_look_at
    assert "Attenzione: nessun controllo da più di un giorno. L'ultimo è del 29/10 alle 08:00." in late
    assert links(nothing_yet)["Controllo"] == "/check"


def signed_in(now: datetime) -> TestClient:
    """Manuel, logged in, in an app whose clock says `now`."""
    client = TestClient(create_app(now=lambda: now, photo_store=FakePhotoStore()))
    client.post("/login", data={"password": TEST_PASSWORD})
    return client


def _lost_unseen(item_page: str, copies: int) -> None:
    """Copies of the item's lot lost with its listings left as they were: the pages would bring them in line, a fault
    would not."""
    item_id = int(item_page.removeprefix("/items/"))
    with create_database_engine().begin() as connection:
        [lot] = stock.lots(connection, item_id)
        stock.adjust(connection, lot.id, -copies, Cause.LOST)


def _on_sale(client: TestClient, item: dict, *channels: str) -> str:
    """The page of an item loaded and put on sale on those channels."""
    item_page = client.post("/items", data=item)
    put_on_sale, _ = buttons(item_page.text)["Metti in vendita"]
    offered = checkboxes(item_page.text, "channel")
    client.post(put_on_sale, data={"channel": [offered[channel] for channel in channels]})
    return item_page.url.path


def _action(client: TestClient, channel: str, item_name: str):
    """The page of the action to publish the item on the channel, opened from the list of the actions."""
    return client.get(links(sections(client.get("/actions").text)[channel])[f"Pubblica {item_name}"])
