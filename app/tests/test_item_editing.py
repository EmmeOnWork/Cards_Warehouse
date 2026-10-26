"""Editing an item already loaded: its data change, its stock does not.

Through the app's HTTP routes, on a real PostgreSQL.
"""

from tests.pages import links, table_rows

SEALED_BOX = {
    "kind": "sealed",
    "game": "Pokémon",
    "name": "Box Evoluzioni a Paldea",
    "language": "it",
    "quantity": "5",
    "total_cost": "89,90",
    "product_type": "Booster box",
    "set_name": "Evoluzioni a Paldea",
}


# A box of One Piece loaded as one of Pokémon: the edit starts from what was typed, and fixes it. The copies
# change only through movements, so a number of copies sent with the edit is not read.
def test_editing_an_item_changes_its_data_and_not_its_stock(signed_in_client):
    item_page = signed_in_client.post("/items", data=SEALED_BOX).url.path
    edit = links(signed_in_client.get(item_page).text)["Modifica"]
    edit_page = signed_in_client.get(edit).text
    assert 'value="Box Evoluzioni a Paldea"' in edit_page
    assert 'value="Evoluzioni a Paldea"' in edit_page

    fixed = {"game": "One Piece", "name": "Box Romance Dawn", "set_name": "Romance Dawn", "quantity": "9"}
    signed_in_client.post(edit, data={**SEALED_BOX, **fixed})

    rows = table_rows(signed_in_client.get("/items").text)
    assert rows == [["Box Romance Dawn Booster box · Romance Dawn", "Sealed", "One Piece", "5"]]
