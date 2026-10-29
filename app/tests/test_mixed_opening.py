"""The mixed opening of a box, as Manuel does it from the phone: some packs stay closed, the others are opened into
cards and the bulk, in one step.

Through the app's HTTP routes, on a real PostgreSQL.
"""

from tests.pages import form_fields, links, select_options, table_rows, text
from tests.test_cards_opening import add_partner, added_card

# A box at 89,90 €, half Luca's.
BOX = {
    "kind": "sealed",
    "game": "Pokémon",
    "name": "Booster box Evoluzioni a Paldea",
    "language": "it",
    "product_type": "Booster box",
    "set_name": "Evoluzioni a Paldea",
    "quantity": "1",
    "total_cost": "89,90",
    "purchased_on": "2026-10-20",
}


# A box of 36 packs, 89,90 €: 26 at 2,50 € and 10 at 2,49 €. 26 stay closed, and 10 at 2,50 €, 25,00 €, are opened:
# Charizard estimated 40 €, Pikachu 5 € and 18 cards of bulk 5 € take 20,00 €, 2,50 € and 2,50 €. The closed packs
# keep the rest, 16 at 2,50 € and 10 at 2,49 €. The box names all that came out of it, which carries its shares.
def test_a_box_opened_with_some_packs_left_closed_hands_its_whole_cost_to_the_packs_the_cards_and_the_bulk(
    signed_in_client,
):
    luca = add_partner(signed_in_client, "Luca")
    shared = {**BOX, "partner": ["", luca], "percent": ["50", "50"], "paid": ["44,95", "44,95"]}
    box_page = signed_in_client.post("/items", data=shared).url.path

    opening = links(signed_in_client.get(box_page).text)["Apertura mista"]
    packs = {"packs": "36", "pack": "", "pack_name": "Busta Evoluzioni a Paldea", "closed": "26"}
    charizard = {"name": "Charizard ex", "estimated_value": "40,00"}
    with_charizard = added_card(signed_in_client, opening, {**packs, **charizard})
    pikachu = {"name": "Pikachu", "estimated_value": "5,00"}
    bulk = {"bulk_cards": "18", "bulk_value": "5,00"}
    movements = signed_in_client.post(opening, data={**form_fields(with_charizard), **pikachu, **bulk})

    assert movements.url.path == links(signed_in_client.get(box_page).text)["Movimenti e rettifiche"]
    assert [row[1:] for row in table_rows(movements.text)] == [
        ["Carico", "1", "+1"],
        [
            "Apertura In 26 buste: Busta Evoluzioni a Paldea · 1 carta: Charizard ex · 1 carta: Pikachu"
            " · 18 carte: Bulk Pokémon Italiano",
            "1",
            "-1",
        ],
    ]
    came_out = links(movements.text)

    def lots_of(item_page):
        page = signed_in_client.get(links(signed_in_client.get(item_page).text)["Movimenti e rettifiche"]).text
        return select_options(page, "lot")

    assert lots_of(came_out["Busta Evoluzioni a Paldea"]) == [
        "Lotto 1 · 16 copie · 2,50 €",
        "Lotto 2 · 10 copie · 2,49 €",
    ]
    assert lots_of(came_out["Charizard ex"]) == ["Lotto 1 · 1 copia · 20,00 €"]
    assert lots_of(came_out["Pikachu"]) == ["Lotto 1 · 1 copia · 2,50 €"]
    bulk_page = signed_in_client.get(came_out["Bulk Pokémon Italiano"]).text
    assert "Carte 18 Costo 2,50 €" in text(bulk_page)
    assert table_rows(bulk_page) == [["1", "18", "2,50 €", "Manuel 50 % · Luca 50 %"]]
