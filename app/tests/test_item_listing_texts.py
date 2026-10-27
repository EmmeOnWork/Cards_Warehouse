"""The texts of an item's listings: made from its fields, the same on every channel, and edited by Manuel.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import html

from tests.pages import buttons, form_fields, links, table_rows

GRADED_CARD = {
    "kind": "single_card",
    "game": "Pokémon",
    "name": "Mew ex",
    "language": "it",
    "quantity": "1",
    "total_cost": "100",
    "set_name": "151",
    "number": "205/165",
    "variant": "Hyper Rare",
    "graded": "on",
    "grader": "PSA",
    "grade": "10",
}


# The grade takes the place of the condition, as on the card's slab. Language and grade in the title as buyers
# search them; in the description in full.
def test_a_card_loaded_gets_a_title_and_a_description_made_from_its_fields(signed_in_client):
    item_page = signed_in_client.post("/items", data=GRADED_CARD)

    texts = form_fields(item_page.text)
    assert texts["listing_title"] == ["Mew ex 205/165 151 Hyper Rare ITA PSA 10 Pokémon"]
    assert texts["listing_description"] == [
        "Mew ex\n"
        "\n"
        "Gioco: Pokémon\n"
        "Set: 151\n"
        "Numero: 205/165\n"
        "Variante: Hyper Rare\n"
        "Lingua: Italiano\n"
        "Gradazione: PSA 10"
    ]


# The same title on every channel, so it fits the tightest: a channel added from the app with 30 characters makes
# game and variant go. Each channel says its limit; eBay's is 80 characters.
def test_the_title_fits_the_tightest_limit_among_the_channels(signed_in_client):
    cardmarket = {"name": "Cardmarket", "fee_percent": "5", "fee_fixed": "0", "title_limit": "30"}
    signed_in_client.post("/channels", data=cardmarket)

    item_page = signed_in_client.post("/items", data=GRADED_CARD)

    assert form_fields(item_page.text)["listing_title"] == ["Mew ex 205/165 151 ITA PSA 10"]
    limits = {row[0]: row[3] for row in table_rows(signed_in_client.get("/channels").text)}
    assert limits["eBay"] == "80"
    assert limits["Cardmarket"] == "30"


# A detail the fields do not have, such as the centring: the texts stay as Manuel wrote them, even when a field
# changes afterwards. The page says they no longer follow the fields.
def test_the_texts_edited_by_manuel_stay_when_the_fields_change(signed_in_client):
    item_page = signed_in_client.post("/items", data=GRADED_CARD)
    save_texts, _ = buttons(item_page.text)["Salva i testi"]
    edited = {
        "listing_title": "Mew ex 205/165 Hyper Rare ITA PSA 10 centratura perfetta",
        "listing_description": "Mew ex gradata PSA 10.\n\nCentratura perfetta, spedita in scatola rigida.",
    }

    signed_in_client.post(save_texts, data=edited)
    edit = links(item_page.text)["Modifica"]
    signed_in_client.post(edit, data={**GRADED_CARD, "variant": "Gold"})

    page = signed_in_client.get(item_page.url.path).text
    texts = form_fields(page)
    assert texts["listing_title"] == [edited["listing_title"]]
    assert texts["listing_description"] == [edited["listing_description"]]
    assert "Modificati a mano: non seguono più i campi dell'articolo." in html.unescape(page)


# Only on Manuel's command, and from the fields as they are now: then the texts follow them again.
def test_regenerating_makes_the_texts_again_from_the_fields_as_they_are_now(signed_in_client):
    item_page = signed_in_client.post("/items", data=GRADED_CARD)
    save_texts, _ = buttons(item_page.text)["Salva i testi"]
    signed_in_client.post(save_texts, data={"listing_title": "Mew ex", "listing_description": "Mew ex."})
    signed_in_client.post(links(item_page.text)["Modifica"], data={**GRADED_CARD, "variant": "Gold"})

    regenerate, sent = buttons(signed_in_client.get(item_page.url.path).text)["Rigenera dai campi"]
    page = signed_in_client.post(regenerate, data=sent).text

    assert form_fields(page)["listing_title"] == ["Mew ex 205/165 151 Gold ITA PSA 10 Pokémon"]
    assert "Variante: Gold\n" in form_fields(page)["listing_description"][0]
    assert "Modificati a mano" not in page


# eBay would refuse it, or cut it where it likes. The page comes back with what was typed, to shorten it there.
def test_an_edited_title_longer_than_the_tightest_limit_is_refused(signed_in_client):
    item_page = signed_in_client.post("/items", data=GRADED_CARD)
    save_texts, _ = buttons(item_page.text)["Salva i testi"]
    too_long = {"listing_title": "Mew ex " + "x" * 74, "listing_description": "Mew ex."}

    response = signed_in_client.post(save_texts, data=too_long)

    assert response.status_code == 422
    assert "Il titolo ha 81 caratteri: su tutti i canali ne entrano al massimo 80." in html.unescape(response.text)
    assert form_fields(response.text)["listing_title"] == [too_long["listing_title"]]
    page = signed_in_client.get(item_page.url.path).text
    assert form_fields(page)["listing_title"] == ["Mew ex 205/165 151 Hyper Rare ITA PSA 10 Pokémon"]


# Manuel adds a line to the description only: the title, sent back as it was made, keeps following the fields. A
# browser ends the lines of a text box with \r\n.
def test_a_text_saved_as_it_was_made_keeps_following_the_fields(signed_in_client):
    item_page = signed_in_client.post("/items", data=GRADED_CARD)
    save_texts, _ = buttons(item_page.text)["Salva i testi"]
    shown = form_fields(item_page.text)
    description = shown["listing_description"][0] + "\n\nCentratura perfetta."
    typed = {"listing_title": shown["listing_title"][0], "listing_description": description.replace("\n", "\r\n")}

    signed_in_client.post(save_texts, data=typed)
    signed_in_client.post(links(item_page.text)["Modifica"], data={**GRADED_CARD, "variant": "Gold"})

    texts = form_fields(signed_in_client.get(item_page.url.path).text)
    assert texts["listing_title"] == ["Mew ex 205/165 151 Gold ITA PSA 10 Pokémon"]
    assert texts["listing_description"] == [description]
