"""The opening of packs into cards, with the rest in the bulk, as Manuel does it from the phone.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import html

import pytest

from tests.pages import buttons, form_fields, links, select_options, table_rows, text

# Ten packs at 6,00 € each, half Luca's.
SHARED_PACKS = {
    "kind": "sealed",
    "game": "Pokémon",
    "name": "Busta Evoluzioni a Paldea",
    "language": "it",
    "product_type": "Busta",
    "set_name": "Evoluzioni a Paldea",
    "quantity": "10",
    "total_cost": "60,00",
    "purchased_on": "2026-10-20",
}

# One more pack, all Manuel's.
OWN_PACK = {**SHARED_PACKS, "name": "Busta Scarlatto e Violetto", "quantity": "1", "total_cost": "6,00"}


# Two packs opened together, 12,00 €: Charizard estimated 50 €, Pikachu 5 € and 18 cards of bulk 5 € take 10,00 €,
# 1,00 € and 1,00 €. A pack of another purchase, 6,00 €: Pikachu again at 5 € and 9 cards of bulk at 1 € take
# 5,00 € and 1,00 €. The bulk is born at the first opening and takes a lot from each, with the shares of each pack.
def test_packs_opened_into_cards_hand_their_whole_cost_to_the_cards_and_the_bulk(signed_in_client):
    luca = add_partner(signed_in_client, "Luca")
    shared = {**SHARED_PACKS, "partner": ["", luca], "percent": ["50", "50"], "paid": ["30,00", "30,00"]}
    shared_page = signed_in_client.post("/items", data=shared).url.path
    own_page = signed_in_client.post("/items", data=OWN_PACK).url.path

    opening = links(signed_in_client.get(shared_page).text)["Apri in carte"]
    charizard = {"name": "Charizard ex", "number": "199/193", "estimated_value": "50,00"}
    with_charizard = added_card(signed_in_client, opening, charizard)
    pikachu = {"name": "Pikachu", "number": "025/193", "estimated_value": "5,00"}
    bulk = {"bulk_cards": "18", "bulk_value": "5,00"}
    movements = signed_in_client.post(opening, data={**form_fields(with_charizard), "copies": "2", **pikachu, **bulk})

    assert movements.url.path == links(signed_in_client.get(shared_page).text)["Movimenti e rettifiche"]
    assert [row[1:] for row in table_rows(movements.text)] == [
        ["Carico", "1", "+10"],
        ["Apertura In 1 carta: Charizard ex · 1 carta: Pikachu · 18 carte: Bulk Pokémon Italiano", "1", "-2"],
    ]
    came_out = links(movements.text)

    opening = links(signed_in_client.get(own_page).text)["Apri in carte"]
    pikachu_again = {"card": came_out["Pikachu"].removeprefix("/items/"), "estimated_value": "5,00"}
    signed_in_client.post(
        opening, data={"lot": "1", "copies": "1", **pikachu_again, "bulk_cards": "9", "bulk_value": "1,00"}
    )

    def lots_of(item_page):
        page = signed_in_client.get(links(signed_in_client.get(item_page).text)["Movimenti e rettifiche"]).text
        return select_options(page, "lot")

    assert lots_of(came_out["Charizard ex"]) == ["Lotto 1 · 1 copia · 10,00 €"]
    assert lots_of(came_out["Pikachu"]) == ["Lotto 1 · 1 copia · 1,00 €", "Lotto 2 · 1 copia · 5,00 €"]
    bulk_page = signed_in_client.get(came_out["Bulk Pokémon Italiano"]).text
    assert "Carte 27 Costo 2,00 €" in text(bulk_page)
    assert table_rows(bulk_page) == [
        ["1", "18", "1,00 €", "Manuel 50 % · Luca 50 %"],
        ["2", "9", "1,00 €", "Manuel 100 %"],
    ]
    assert lots_of(came_out["Bulk Pokémon Italiano"]) == [
        "Lotto 1 · 18 copie · 1,00 € in tutto",
        "Lotto 2 · 9 copie · 1,00 € in tutto",
    ]


# Without a value the cost cannot be split: the page says which, and keeps the cards added and what was typed, so on
# the phone Manuel fixes one field. Nothing is opened, and no card is made.
@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"estimated_value": "", "bulk_value": "5,00"}, "Scrivi quanto vale una copia di «Pikachu», almeno 0,01 €"),
        ({"estimated_value": "5,00", "bulk_value": "0,00"}, "Scrivi quanto vale il bulk, almeno 0,01 €"),
    ],
)
def test_an_opening_with_a_value_missing_is_refused_and_keeps_what_was_typed(signed_in_client, fields, reason):
    packs_page = signed_in_client.post("/items", data=OWN_PACK).url.path
    opening = links(signed_in_client.get(packs_page).text)["Apri in carte"]
    with_charizard = added_card(signed_in_client, opening, {"name": "Charizard ex", "estimated_value": "50,00"})

    pikachu = {"name": "Pikachu", "bulk_cards": "18", **fields}
    response = signed_in_client.post(opening, data={**form_fields(with_charizard), **pikachu})

    assert response.status_code == 422
    page = html.unescape(response.text)
    assert reason in page
    assert "Charizard ex × 1 · stimata 50,00 €" in text(page)
    assert 'value="Pikachu"' in page
    assert "Copie disponibili 1" in text(signed_in_client.get(packs_page).text)
    assert len(table_rows(signed_in_client.get("/items").text)) == 1


def added_card(client, opening: str, fields: dict) -> str:
    """The opening page once a card is added to it, as the phone shows it to type the next."""
    page = client.get(opening).text
    _, add_card = buttons(page)["Aggiungi un'altra carta"]
    return client.post(opening, data={**form_fields(page), **fields, **add_card}).text


def add_partner(client, name: str) -> str:
    """The partner added from the app, and the id the load page sends for that partner."""
    client.post("/partners", data={"name": name})
    return links(client.get("/partners").text)[name].removeprefix("/partners/")
