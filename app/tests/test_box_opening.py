"""The opening of a box into packs, as Manuel does it from the phone.

Through the app's HTTP routes, on a real PostgreSQL.
"""

from datetime import datetime

from cards_warehouse.backups import LOCAL_TIME
from tests.pages import links, select_options, table_rows

# Five boxes at 89,90 € each.
BOXES = {
    "kind": "sealed",
    "game": "Pokémon",
    "name": "Booster box Evoluzioni a Paldea",
    "language": "it",
    "product_type": "Booster box",
    "set_name": "Evoluzioni a Paldea",
    "quantity": "5",
    "total_cost": "449,50",
}


# A box opened into 36 packs of a new item, then a second box into the same item. Each box leaves its lot with an
# opening, and its 89,90 € go whole to its packs: 26 at 2,50 € and 10 at 2,49 €. Each history says where the
# copies went, or where they came from.
def test_boxes_opened_into_packs_hand_their_whole_cost_to_the_packs(signed_in_client):
    box_page = signed_in_client.post("/items", data=BOXES).url.path
    opening = links(signed_in_client.get(box_page).text)["Apri in buste"]

    new_packs = {"lot": "1", "packs": "36", "pack": "", "pack_name": "Busta Evoluzioni a Paldea"}
    packs_page = signed_in_client.post(opening, data=new_packs).url.path
    packs_id = packs_page.removeprefix("/items/")
    signed_in_client.post(opening, data={"lot": "1", "packs": "36", "pack": packs_id})

    today = f"{datetime.now(LOCAL_TIME):%d/%m/%Y}"
    box_movements = links(signed_in_client.get(box_page).text)["Movimenti e rettifiche"]
    assert table_rows(signed_in_client.get(box_movements).text) == [
        [today, "Carico", "1", "+5"],
        [today, "Apertura In 36 buste: Busta Evoluzioni a Paldea", "1", "-1"],
        [today, "Apertura In 36 buste: Busta Evoluzioni a Paldea", "1", "-1"],
    ]
    packs_movements = signed_in_client.get(links(signed_in_client.get(packs_page).text)["Movimenti e rettifiche"])
    assert table_rows(packs_movements.text) == [
        [today, "Apertura Da Booster box Evoluzioni a Paldea", "1", "+26"],
        [today, "Apertura Da Booster box Evoluzioni a Paldea", "2", "+10"],
        [today, "Apertura Da Booster box Evoluzioni a Paldea", "3", "+26"],
        [today, "Apertura Da Booster box Evoluzioni a Paldea", "4", "+10"],
    ]
    assert select_options(packs_movements.text, "lot") == [
        "Lotto 1 · 26 copie · 2,50 €",
        "Lotto 2 · 10 copie · 2,49 €",
        "Lotto 3 · 26 copie · 2,50 €",
        "Lotto 4 · 10 copie · 2,49 €",
    ]
