"""A card taken out of the bulk to be sold on its own, as Manuel does it from the phone.

Through the app's HTTP routes, on a real PostgreSQL.
"""

from tests.pages import links, select_options, table_rows, text
from tests.test_cards_opening import OWN_PACK, SHARED_PACKS, add_partner


# A pack of 6,00 €, half Luca's, opened all into 2 cards of bulk; then a pack of 6,00 €, all Manuel's, into 9. The
# first two cards out take 3,00 € each from the first lot, the oldest, which ends; the third takes a ninth of 6,00 €
# from the second, rounded to 0,67 €. Bulk and cards cost together what the packs cost.
def test_cards_extracted_from_the_bulk_take_their_cost_from_its_oldest_lot(signed_in_client):
    luca = add_partner(signed_in_client, "Luca")
    shared = {**SHARED_PACKS, "partner": ["", luca], "percent": ["50", "50"], "paid": ["30,00", "30,00"]}
    bulk = None
    for packs, bulk_cards in ((shared, "2"), (OWN_PACK, "9")):
        packs_page = signed_in_client.post("/items", data=packs).url.path
        opening = links(signed_in_client.get(packs_page).text)["Apri in carte"]
        all_bulk = {"lot": "1", "copies": "1", "bulk_cards": bulk_cards, "bulk_value": "1,00"}
        bulk = links(signed_in_client.post(opening, data=all_bulk).text)["Bulk Pokémon Italiano"]

    extraction = links(signed_in_client.get(bulk).text)["Estrai una carta"]
    charizard = {"name": "Charizard ex", "set_name": "Evoluzioni a Paldea", "number": "199/193"}
    charizard_page = signed_in_client.post(extraction, data=charizard)
    assert "Charizard ex" in text(charizard_page.text)
    charizard_id = charizard_page.url.path.removeprefix("/items/")
    signed_in_client.post(extraction, data={"card": charizard_id})
    pikachu_page = signed_in_client.post(extraction, data={"name": "Pikachu", "number": "025/193"}).url.path

    def lots_of(item_page):
        page = signed_in_client.get(links(signed_in_client.get(item_page).text)["Movimenti e rettifiche"]).text
        return select_options(page, "lot")

    assert lots_of(charizard_page.url.path) == ["Lotto 1 · 1 copia · 3,00 €", "Lotto 2 · 1 copia · 3,00 €"]
    assert lots_of(pikachu_page) == ["Lotto 1 · 1 copia · 0,67 €"]
    bulk_page = signed_in_client.get(bulk).text
    assert "Carte 8 Costo 5,33 €" in text(bulk_page)
    assert table_rows(bulk_page) == [["2", "8", "5,33 €", "Manuel 100 %"]]
    history = signed_in_client.get(links(bulk_page)["Movimenti e rettifiche"]).text
    assert [row[1:] for row in table_rows(history)][2:] == [
        ["Estrazione In 1 carta: Charizard ex", "1", "-1"],
        ["Estrazione In 1 carta: Charizard ex", "1", "-1"],
        ["Estrazione In 1 carta: Pikachu", "2", "-1"],
    ]


# The bulk never goes below no cards: once its last card is out, the page says so, keeps what was typed, and the new
# card goes away with the extraction refused.
def test_a_bulk_without_cards_refuses_an_extraction_and_makes_no_card(signed_in_client):
    packs_page = signed_in_client.post("/items", data=OWN_PACK).url.path
    opening = links(signed_in_client.get(packs_page).text)["Apri in carte"]
    all_bulk = {"lot": "1", "copies": "1", "bulk_cards": "1", "bulk_value": "1,00"}
    bulk = links(signed_in_client.post(opening, data=all_bulk).text)["Bulk Pokémon Italiano"]
    extraction = links(signed_in_client.get(bulk).text)["Estrai una carta"]
    signed_in_client.post(extraction, data={"name": "Charizard ex"})

    response = signed_in_client.post(extraction, data={"name": "Pikachu"})

    assert response.status_code == 422
    assert "Il bulk non ha più carte da estrarre." in text(response.text)
    assert 'value="Pikachu"' in response.text
    names = [row[0] for row in table_rows(signed_in_client.get("/items").text)]
    assert any("Charizard ex" in name for name in names)
    assert not any("Pikachu" in name for name in names)
