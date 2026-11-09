"""The partners' parts of every sale, and the balance with each of them, either way: who sold and took the money,
Manuel or a partner from their own account, and who paid the purchases more than their share.

Through the app's HTTP routes, on a real PostgreSQL.
"""

from tests.pages import buttons, checkboxes, links, sections, table_rows, text
from tests.test_bulk_selling import bulk_of_two_lots
from tests.test_purchase_loading import BOXES, add_partner
from tests.test_sale_cancellation import _cancel


# Three boxes of 104,00 €, half Luca's, paid all by Luca: Manuel owes him 52,00 €. One sold on Vinted at 60,00 €, which
# keeps nothing, and the money went to Manuel: half of it is Luca's, and Manuel owes him 30,00 € more.
def test_a_box_of_a_purchase_paid_by_luca_sold_by_manuel_leaves_its_margin_and_manuel_owing_luca(signed_in_client):
    luca = add_partner(signed_in_client, "Luca")
    shared = {**BOXES, "partner": ["", luca], "percent": ["50", "50"], "paid": ["0", "104,00"]}
    item_page = signed_in_client.post("/items", data=shared).url.path

    sold = sell(signed_in_client, item_page, channel="Vinted", collected_by="Manuel", quantity="1", price="60")

    assert "Costo 34,67 € Margine 25,33 €" in text(sections(sold.text)["Vendita"])
    parts = sections(sold.text)["Parti"]
    assert "Ha incassato Manuel." in text(parts)
    assert table_rows(parts) == [["Manuel", "30,00 €"], ["Luca", "30,00 €"]]
    assert table_rows(signed_in_client.get("/partners").text) == [["Luca", "Gli devi 82,00 €"]]


# The box comes back: the 60,00 € went back to the buyer, and Manuel owes Luca the 52,00 € of the purchase alone.
def test_a_sale_cancelled_takes_its_part_out_of_the_balance(signed_in_client):
    luca = add_partner(signed_in_client, "Luca")
    shared = {**BOXES, "partner": ["", luca], "percent": ["50", "50"], "paid": ["0", "104,00"]}
    item_page = signed_in_client.post("/items", data=shared).url.path
    sold = sell(signed_in_client, item_page, channel="Vinted", collected_by="Manuel", quantity="1", price="60")

    _cancel(signed_in_client, sold.text, "Reso")

    assert table_rows(signed_in_client.get("/partners").text) == [["Luca", "Gli devi 52,00 €"]]
    assert "Parti" not in sections(signed_in_client.get(sold.url.path).text)


# Luca sold a box from his own account at 60,00 €, the purchase paid half each: 30,00 € of his money are Manuel's.
def test_a_sale_whose_money_luca_took_leaves_him_owing_manuel_his_part(signed_in_client):
    luca = add_partner(signed_in_client, "Luca")
    shared = {**BOXES, "partner": ["", luca], "percent": ["50", "50"], "paid": ["52,00", "52,00"]}
    item_page = signed_in_client.post("/items", data=shared).url.path

    sold = sell(signed_in_client, item_page, channel="Vinted", collected_by="Luca", quantity="1", price="60")

    assert "Ha incassato Luca." in text(sections(sold.text)["Parti"])
    assert table_rows(signed_in_client.get("/partners").text) == [["Luca", "Ti deve 30,00 €"]]


# Five cards of the bulk sold for 10,00 €: 2 from the lot half Luca's, 3 from the lot all Manuel's. Each card is
# 2,00 €, and Luca has half of two: 2,00 €.
def test_a_sale_of_the_bulk_across_two_lots_splits_each_card_by_the_shares_of_its_own_lot(signed_in_client):
    bulk = bulk_of_two_lots(signed_in_client)

    sold = sell(signed_in_client, bulk, channel="Vinted", collected_by="Manuel", quantity="5", price="10")

    assert table_rows(sections(sold.text)["Parti"]) == [["Manuel", "8,00 €"], ["Luca", "2,00 €"]]


# Bought by Manuel alone, sold by Manuel: nobody else has a part of it, and the page says nothing of parts. Without
# partners, it does not ask who took the money either.
def test_a_sale_all_manuels_shows_no_parts(signed_in_client):
    item_page = signed_in_client.post("/items", data=BOXES).url.path
    form = signed_in_client.get(links(signed_in_client.get(item_page).text)["Vendi"]).text
    assert checkboxes(form, "collected_by") == {}
    add_partner(signed_in_client, "Luca")

    sold = sell(signed_in_client, item_page, channel="Vinted", collected_by="Manuel", quantity="1", price="60")

    assert "Parti" not in sections(sold.text)


def sell(client, item_page: str, channel: str, collected_by: str, **fields: str):
    """The page of a sale recorded from the item's page, with who took the money and what Manuel types in the form."""
    form = client.get(links(client.get(item_page).text)["Vendi"])
    record, _ = buttons(form.text)["Registra la vendita"]
    chosen = {
        "channel": checkboxes(form.text, "channel")[channel],
        "collected_by": checkboxes(form.text, "collected_by")[collected_by],
    }
    return client.post(record, data={**chosen, **fields})
