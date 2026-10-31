"""Cancelling a sale: a return or an order cancelled puts its copies back in the lots they came from, keeps the sale as
cancelled, and proposes to put the item back on sale where it was offered.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import html
from datetime import datetime

from cards_warehouse import stock
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.database import create_database_engine
from tests.pages import buttons, checkboxes, form_fields, links, sections, select_options, table_rows, text
from tests.test_selling import MEW, published, sell


# Two copies of Mew ex from two lots, at 50,00 and 40,00, sold together on Tilt and sent back by the buyer: each goes
# back to its lot, at its cost, and the stock is as it was before the sale. The sale is reached from the history.
def test_a_sale_cancelled_for_a_return_puts_each_copy_back_in_the_lot_it_came_from(signed_in_client):
    item_page = signed_in_client.post("/items", data=MEW).url.path
    with create_database_engine().begin() as connection:
        stock.load(connection, int(item_page.rsplit("/", 1)[1]), quantity=1, unit_cost_cents=4000)
    movements = links(signed_in_client.get(item_page).text)["Movimenti e rettifiche"]
    before = select_options(signed_in_client.get(movements).text, "lot")
    sell(signed_in_client, item_page, channel="Tilt", quantity="2", price="120")

    sale = signed_in_client.get(links(signed_in_client.get(movements).text)["Vendita"])
    cancelled = _cancel(signed_in_client, sale.text, cause="Reso", note="Arrivata piegata")

    today = f"{datetime.now(LOCAL_TIME):%d/%m/%Y}"
    assert (
        text(sections(cancelled.text)["Annullamento"]) == f"Annullamento Causa Reso Data {today} Nota Arrivata piegata"
    )
    assert "Annulla la vendita" not in buttons(cancelled.text)
    history = signed_in_client.get(movements).text
    assert [row[1:] for row in table_rows(history)] == [
        ["Carico", "1", "+1"],
        ["Carico", "2", "+1"],
        ["Vendita", "1", "-1"],
        ["Vendita", "2", "-1"],
        ["Annullamento", "1", "+1"],
        ["Annullamento", "2", "+1"],
    ]
    assert select_options(history, "lot") == before


# Mew ex, the only copy, on Vinted, Tilt and eBay, sold on Tilt, which closed its listing by itself: Manuel took it off
# Vinted, not yet off eBay. The order is cancelled, and the page proposes the three channels it was on. Accepted, Tilt
# and Vinted get a listing to publish; on eBay, where it is still up, the action to close it becomes one to update it.
def test_once_a_sale_is_cancelled_manuel_can_put_the_item_back_on_sale_where_it_was_offered(signed_in_client):
    item_page = published(signed_in_client, MEW, "Vinted", "Tilt", "eBay")
    sold = sell(signed_in_client, item_page, channel="Tilt", quantity="1", price="60")
    to_close = signed_in_client.get(links(sections(sold.text)["Da fare"])["Chiudi su Vinted"])
    closed, _ = buttons(to_close.text)["Chiuso"]
    signed_in_client.post(closed)

    cancelled = _cancel(signed_in_client, sold.text, cause="Ordine cancellato")
    proposal = sections(cancelled.text)["Rimetti in vendita"]
    offered = checkboxes(proposal, "channel")
    put_back, _ = buttons(proposal)["Rimetti in vendita"]
    accepted = signed_in_client.post(put_back, data={"channel": form_fields(proposal)["channel"]})

    assert list(offered) == ["Vinted", "Tilt", "eBay"]
    assert form_fields(proposal)["channel"] == list(offered.values())
    shown = sections(accepted.text)
    assert list(links(shown["Da fare"])) == ["Pubblica su Vinted", "Pubblica su Tilt", "Aggiorna su eBay"]
    assert "Rimetti in vendita" not in shown
    assert [row[:2] for row in table_rows(sections(signed_in_client.get(item_page).text)["Annunci"])] == [
        ["Vinted", "da pubblicare"],
        ["Tilt", "da pubblicare"],
        ["eBay", "da aggiornare"],
    ]


# Without its cause the page comes back with the note he wrote, and the copy stays sold.
def test_a_cancellation_without_its_cause_is_refused_with_the_note_manuel_wrote(signed_in_client):
    item_page = signed_in_client.post("/items", data=MEW).url.path
    sold = sell(signed_in_client, item_page, channel="Tilt", quantity="1", price="60")

    response = _cancel(signed_in_client, sold.text, cause=None, note="Arrivata piegata")

    assert response.status_code == 422
    assert "Scegli la causa dell'annullamento." in html.unescape(response.text)
    assert form_fields(sections(response.text)["Annulla la vendita"])["note"] == ["Arrivata piegata"]
    assert "Copie disponibili 0" in text(signed_in_client.get(item_page).text)


# Tapped twice, as on a phone slow to answer: the copy goes back once.
def test_a_sale_cancelled_twice_gives_its_copy_back_once(signed_in_client):
    item_page = signed_in_client.post("/items", data=MEW).url.path
    sold = sell(signed_in_client, item_page, channel="Tilt", quantity="1", price="60")
    _cancel(signed_in_client, sold.text, cause="Reso")

    again = _cancel(signed_in_client, sold.text, cause="Reso")

    assert again.status_code == 200
    assert "Copie disponibili 1" in text(signed_in_client.get(item_page).text)


def _cancel(client, sale_page: str, cause: str | None, note: str = ""):
    """The page of the sale once Manuel asked to cancel it, with the cause he chose, if any, and his note."""
    address, _ = buttons(sale_page)["Annulla la vendita"]
    chosen = {} if cause is None else {"cause": checkboxes(sale_page, "cause")[cause]}
    return client.post(address, data={**chosen, "note": note})
