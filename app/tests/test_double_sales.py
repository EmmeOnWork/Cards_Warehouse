"""Double sales: a sale that came for copies sold already elsewhere. It takes nothing from the stock, which never goes
below zero, and stays known and counted, on a list of its own.

Through the app's HTTP routes, on a real PostgreSQL.
"""

from datetime import datetime

from cards_warehouse.backups import LOCAL_TIME
from tests.pages import links, sections, table_rows, text
from tests.test_sale_cancellation import _cancel
from tests.test_selling import MEW, sell


# Mew ex, the only copy, sold on Vinted and bought on eBay too, before Manuel took it off there: the eBay sale finds no
# copy left. It is a double sale, which moves nothing, and it is on the list of the double sales.
def test_a_sale_of_copies_sold_out_is_recorded_as_a_double_sale(signed_in_client):
    item_page = signed_in_client.post("/items", data=MEW).url.path
    sell(signed_in_client, item_page, channel="Vinted", quantity="1", price="60")

    double = sell(signed_in_client, item_page, channel="eBay", quantity="1", price="60")

    assert text(sections(double.text)["Doppia vendita"]) == (
        "Doppia vendita 1 copia era già venduta altrove: nessuna è uscita dal magazzino."
    )
    item = signed_in_client.get(item_page).text
    assert "Copie disponibili 0" in text(item)
    assert [row[1:] for row in table_rows(signed_in_client.get(links(item)["Movimenti e rettifiche"]).text)] == [
        ["Carico", "1", "+1"],
        ["Vendita", "1", "-1"],
    ]
    today = f"{datetime.now(LOCAL_TIME):%d/%m/%Y}"
    assert table_rows(signed_in_client.get(links(item)["Doppie vendite"]).text) == [[today, "eBay", "Mew ex", "1"]]


# The eBay order of the copy sold already is cancelled, from the list, as a double sale: it is still one on the list.
def test_a_double_sale_cancelled_as_a_double_sale_is_counted_once(signed_in_client):
    item_page = signed_in_client.post("/items", data=MEW).url.path
    sell(signed_in_client, item_page, channel="Vinted", quantity="1", price="60")
    sell(signed_in_client, item_page, channel="eBay", quantity="1", price="60")
    listed = signed_in_client.get("/double-sales").text

    cancelled = _cancel(signed_in_client, signed_in_client.get(links(listed)["Mew ex"]).text, cause="Doppia vendita")

    assert "Causa Doppia vendita" in text(sections(cancelled.text)["Annullamento"])
    assert [row[1:] for row in table_rows(signed_in_client.get("/double-sales").text)] == [["eBay", "Mew ex", "1"]]
