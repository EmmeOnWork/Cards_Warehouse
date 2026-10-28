"""Putting an item on sale on the manual channels: for each channel chosen a listing to publish and an action for
Manuel, the actions grouped by channel, and the listing active once he publishes it and pastes its link.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import html

import pytest

from tests.pages import buttons, checkboxes, copies, images, links, sections, table_rows, text

BOOSTER_BOX = {
    "kind": "sealed",
    "game": "Pokémon",
    "name": "Booster box Evoluzioni a Paldea",
    "language": "it",
    "quantity": "5",
    "total_cost": "500",
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
VINTED_LINK = "https://www.vinted.it/items/5123456789-booster-box-evoluzioni-a-paldea"
# What the phone sends is not read by the app: any bytes stand for a photo.
FRONT = b"\xff\xd8 the front of the box \xff\xd9"


# On Vinted a listing is one copy, even with five in stock; on Tilt and eBay it offers all five. eBay is a manual
# channel like the others until the app publishes there by itself (task 33).
def test_an_item_put_on_sale_on_three_channels_is_active_with_its_link_where_manuel_published_it(signed_in_client):
    item_page = signed_in_client.post("/items", data=BOOSTER_BOX)
    put_on_sale, _ = buttons(item_page.text)["Metti in vendita"]
    channel = checkboxes(item_page.text, "channel")
    signed_in_client.post(put_on_sale, data={"channel": [channel["Vinted"], channel["Tilt"], channel["eBay"]]})

    on_vinted = sections(signed_in_client.get("/actions").text)["Vinted"]
    action = signed_in_client.get(links(on_vinted)[f"Pubblica {BOOSTER_BOX['name']}"])
    published, _ = buttons(action.text)["Pubblicato"]
    signed_in_client.post(published, data={"link": VINTED_LINK})

    listings = sections(signed_in_client.get(item_page.url.path).text)["Annunci"]
    assert table_rows(listings) == [
        ["Vinted", "attivo", "120,00 €", "1", VINTED_LINK],
        ["Tilt", "da pubblicare", "122,96 €", "5", ""],
        ["eBay", "da pubblicare", "120,00 €", "5", ""],
    ]


# All those of one app done in one go, and how many are left of each. A channel with nothing to do is not there.
def test_the_actions_are_grouped_by_channel_each_saying_how_many_are_left(signed_in_client):
    box_page = _on_sale(signed_in_client, BOOSTER_BOX, "Vinted", "Tilt")
    _on_sale(signed_in_client, MEW, "Vinted")

    by_channel = sections(signed_in_client.get("/actions").text)

    assert list(by_channel) == ["Vinted", "Tilt"]
    assert text(by_channel["Vinted"]) == f"Vinted 2 da fare Pubblica {BOOSTER_BOX['name']} Pubblica {MEW['name']}"
    assert text(by_channel["Tilt"]) == f"Tilt 1 da fare Pubblica {BOOSTER_BOX['name']}"
    assert list(checkboxes(signed_in_client.get(box_page).text, "channel")) == ["eBay"]


# From the phone: a tap copies each text, to paste in Vinted's app; the price as its field takes it, without the
# euro sign. The photos to save in the camera roll are there too.
def test_an_action_to_publish_offers_the_title_the_description_and_the_price_to_copy_and_the_photos(
    signed_in_client, photos
):
    item_page = _on_sale(signed_in_client, BOOSTER_BOX, "Vinted")
    signed_in_client.post(f"{item_page}/photos", files=[("photos", ("IMG_1.JPG", FRONT, "image/jpeg"))])

    action = _action(signed_in_client, "Vinted", BOOSTER_BOX["name"])

    assert copies(action.text) == {
        "Copia il titolo": "Booster box Evoluzioni a Paldea ITA Pokémon",
        "Copia la descrizione": "Booster box Evoluzioni a Paldea\n\nGioco: Pokémon\nLingua: Italiano",
        "Copia il prezzo": "120,00",
    }
    assert [photos.open(link) for link in images(action.text)] == [FRONT]


# Ticked without a link, or with something that is not one: the app would not know where the listing is.
@pytest.mark.parametrize("link", ["", "vinted booster box"])
def test_an_action_to_publish_ticked_without_a_link_is_refused_and_stays_to_do(signed_in_client, link):
    item_page = _on_sale(signed_in_client, BOOSTER_BOX, "Vinted")
    published, _ = buttons(_action(signed_in_client, "Vinted", BOOSTER_BOX["name"]).text)["Pubblicato"]

    response = signed_in_client.post(published, data={"link": link})

    assert response.status_code == 422
    assert "Incolla il link dell'annuncio pubblicato: comincia con https://" in html.unescape(response.text)
    assert "Vinted" in sections(signed_in_client.get("/actions").text)
    assert table_rows(sections(signed_in_client.get(item_page).text)["Annunci"])[0][1] == "da pubblicare"


# A cost not known and no price fixed: the page says what to do first, and the item is offered nowhere.
def test_an_item_with_no_price_is_not_put_on_sale_and_the_page_says_why(signed_in_client):
    item_page = signed_in_client.post("/items", data={**BOOSTER_BOX, "total_cost": "", "unknown_cost": "on"})
    put_on_sale, _ = buttons(item_page.text)["Metti in vendita"]

    response = signed_in_client.post(put_on_sale, data={"channel": checkboxes(item_page.text, "channel")["Vinted"]})

    assert response.status_code == 422
    reason = "Il costo è sconosciuto e non c'è un prezzo fissato: fissa il prezzo, poi mettilo in vendita."
    assert reason in html.unescape(response.text)
    assert "Non è in vendita su nessun canale." in html.unescape(signed_in_client.get(item_page.url.path).text)


def _on_sale(client, item: dict, *channels: str) -> str:
    """The page of an item loaded and put on sale on those channels."""
    item_page = client.post("/items", data=item)
    put_on_sale, _ = buttons(item_page.text)["Metti in vendita"]
    offered = checkboxes(item_page.text, "channel")
    client.post(put_on_sale, data={"channel": [offered[channel] for channel in channels]})
    return item_page.url.path


def _action(client, channel: str, item_name: str):
    """The page of the action to publish the item on the channel, opened from the list of the actions."""
    return client.get(links(sections(client.get("/actions").text)[channel])[f"Pubblica {item_name}"])
