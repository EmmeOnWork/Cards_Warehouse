"""The history of an item's movements, and the adjustments that change a lot without a sale.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import html
from datetime import datetime

from cards_warehouse.backups import LOCAL_TIME
from tests.pages import links, select_options, table_rows

SEALED_BOX = {
    "kind": "sealed",
    "game": "Pokémon",
    "name": "Booster box Evoluzioni a Paldea",
    "language": "it",
    "quantity": "5",
    "total_cost": "89,90",
}


# Five boxes loaded, one lost behind the furniture, two more found counting again: the history tells how the
# quantity got to 6, and adds up to it.
def test_a_load_and_two_adjustments_leave_a_history_that_adds_up_to_the_quantity_available(signed_in_client):
    movements = movements_of_a_box(signed_in_client)
    lost = {"lot": "1", "cause": "lost", "quantity": "1", "note": "Caduto dietro il mobile"}
    signed_in_client.post(movements, data=lost)
    signed_in_client.post(movements, data={"lot": "1", "cause": "count_more", "quantity": "2"})

    history = table_rows(signed_in_client.get(movements).text)

    today = f"{datetime.now(LOCAL_TIME):%d/%m/%Y}"
    assert history == [
        [today, "Carico", "1", "+5"],
        [today, "Smarrito Caduto dietro il mobile", "1", "-1"],
        [today, "Errore di conteggio", "1", "+2"],
    ]
    assert sum(int(change) for *_, change in history) == 6
    assert table_rows(signed_in_client.get("/items").text)[0][3] == "6"


# The cause is what the history will tell: chosen from a list, and never left out.
def test_an_adjustment_needs_a_cause_chosen_from_a_list(signed_in_client):
    movements = movements_of_a_box(signed_in_client)
    assert select_options(signed_in_client.get(movements).text, "cause") == [
        "Scegli la causa",
        "Smarrito",
        "Danneggiato",
        "Regalato",
        "Errore di conteggio: ne ho in meno",
        "Errore di conteggio: ne ho in più",
    ]

    response = signed_in_client.post(movements, data={"lot": "1", "cause": "", "quantity": "1"})

    assert response.status_code == 422
    assert "Scegli la causa della rettifica." in html.unescape(response.text)
    assert len(table_rows(signed_in_client.get(movements).text)) == 1


# Five boxes, and six lost: a slip of the finger on the phone. The page says what the lot has, and keeps the form.
def test_an_adjustment_below_zero_is_refused_saying_how_many_copies_the_lot_has(signed_in_client):
    movements = movements_of_a_box(signed_in_client)

    response = signed_in_client.post(movements, data={"lot": "1", "cause": "lost", "quantity": "6", "note": "Mai"})

    assert response.status_code == 422
    page = html.unescape(response.text)
    assert "Il lotto 1 ha 5 copie: non puoi toglierne 6." in page
    assert 'value="Mai"' in page
    assert len(table_rows(signed_in_client.get(movements).text)) == 1


def movements_of_a_box(client) -> str:
    """Where the movements of a box just loaded are, reached from its page as Manuel reaches them."""
    item_page = client.post("/items", data=SEALED_BOX).url.path
    return links(client.get(item_page).text)["Movimenti e rettifiche"]
