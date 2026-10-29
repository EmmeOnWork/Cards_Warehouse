"""The listings kept in line with their item: a price or a stock that changes leaves an action to update or close
each listing it touches on a manual channel, and Manuel can force a price on one channel or withdraw the item from it.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import pytest

from tests.pages import buttons, checkboxes, choices, form_fields, links, sections, table_rows, text
from tests.test_putting_on_sale import BOOSTER_BOX, MEW, _on_sale

LINKS = {channel: f"https://{channel.lower()}.test/booster-box" for channel in ("Vinted", "Tilt", "eBay")}


# Vinted and eBay keep nothing of a price, and were at 120,00 € already: only on Tilt, which keeps 2% + 0,50 €, the
# price changes, from 122,96 €.
def test_a_price_fixed_leaves_an_action_to_update_only_where_an_active_listing_changes_price(signed_in_client):
    item_page = _published(signed_in_client, BOOSTER_BOX, "Vinted", "Tilt", "eBay")
    fix, _ = buttons(signed_in_client.get(item_page).text)["Fissa il prezzo"]

    signed_in_client.post(fix, data={"fixed_price": "120,00"})

    by_channel = sections(signed_in_client.get("/actions").text)
    assert list(by_channel) == ["Tilt"]
    assert text(by_channel["Tilt"]) == f"Tilt 1 da fare Aggiorna {BOOSTER_BOX['name']}"
    _do(signed_in_client, "Tilt", f"Aggiorna {BOOSTER_BOX['name']}", "Aggiornato")
    assert table_rows(sections(signed_in_client.get(item_page).text)["Annunci"]) == [
        ["Vinted", "attivo", "120,00 €", "1", LINKS["Vinted"]],
        ["Tilt", "attivo", "120,00 €", "5", LINKS["Tilt"]],
        ["eBay", "attivo", "120,00 €", "5", LINKS["eBay"]],
    ]


# Two of five lost: Tilt offers five, to bring down to three, and Vinted's one copy is still there. The other three
# lost before Manuel did it: Tilt's action is to close now, in place of the update, and so is Vinted's listing.
def test_adjustments_leave_an_action_to_lower_a_listing_offering_too_many_and_to_close_each_once_none_is_left(
    signed_in_client,
):
    item_page = _published(signed_in_client, BOOSTER_BOX, "Vinted", "Tilt")
    movements = links(signed_in_client.get(item_page).text)["Movimenti e rettifiche"]

    signed_in_client.post(movements, data={"lot": "1", "cause": "lost", "quantity": "2"})

    on_tilt = sections(signed_in_client.get("/actions").text)
    assert list(on_tilt) == ["Tilt"]
    update = signed_in_client.get(links(on_tilt["Tilt"])[f"Aggiorna {BOOSTER_BOX['name']}"])
    assert "Porta l'annuncio a 3 copie a 122,96 €." in text(update.text)
    signed_in_client.post(movements, data={"lot": "1", "cause": "lost", "quantity": "3"})
    by_channel = sections(signed_in_client.get("/actions").text)
    assert {channel: text(section) for channel, section in by_channel.items()} == {
        "Vinted": f"Vinted 1 da fare Chiudi {BOOSTER_BOX['name']}",
        "Tilt": f"Tilt 1 da fare Chiudi {BOOSTER_BOX['name']}",
    }


# A promotion on Tilt only, at 99,00 €: below the cost of 100,00 €, as its margin says. Tilt's listing is to update,
# Vinted's is not. The promotion over, Tilt is back at the price made from the target, and to update again.
def test_a_price_forced_on_one_channel_shows_its_margin_updates_that_listing_only_and_can_be_taken_away(
    signed_in_client,
):
    item_page = _published(signed_in_client, BOOSTER_BOX, "Vinted", "Tilt")
    page = signed_in_client.get(item_page).text
    force, _ = buttons(page)["Forza il prezzo"]

    signed_in_client.post(force, data={"channel": choices(page, "channel")["Tilt"], "forced_price": "99,00"})

    prices = sections(signed_in_client.get(item_page).text)["Prezzi per canale"]
    assert table_rows(prices)[1] == ["Tilt", "99,00 € forzato", "-3,48 €", "-3,48 % in perdita"]
    assert list(sections(signed_in_client.get("/actions").text)) == ["Tilt"]
    _do(signed_in_client, "Tilt", f"Aggiorna {BOOSTER_BOX['name']}", "Aggiornato")
    take_away, sent = buttons(signed_in_client.get(item_page).text)["Togli il prezzo forzato su Tilt"]
    signed_in_client.post(take_away, data=sent)
    assert table_rows(sections(signed_in_client.get(item_page).text)["Annunci"]) == [
        ["Vinted", "attivo", "120,00 €", "1", LINKS["Vinted"]],
        ["Tilt", "da aggiornare", "122,96 €", "5", LINKS["Tilt"]],
    ]


# The page says why, with the channel and the price typed, and Tilt's listing stays as it was.
def test_a_price_forced_below_one_cent_is_refused_with_its_reason(signed_in_client):
    item_page = _published(signed_in_client, BOOSTER_BOX, "Tilt")
    force, _ = buttons(signed_in_client.get(item_page).text)["Forza il prezzo"]

    response = signed_in_client.post(force, data={"channel": "Tilt", "forced_price": "0"})

    assert response.status_code == 422
    assert "Il prezzo forzato vale almeno 0,01 €." in text(response.text)
    assert form_fields(response.text) == {"channel": ["Tilt"], "forced_price": ["0"]}
    assert "Tilt" not in sections(signed_in_client.get("/actions").text)


# Off Vinted, while Tilt goes on offering it. Once closed there, Vinted is offered again to put it on sale.
def test_an_item_withdrawn_from_one_channel_is_closed_there_once_manuel_closes_it_and_stays_on_the_others(
    signed_in_client,
):
    item_page = _published(signed_in_client, BOOSTER_BOX, "Vinted", "Tilt")
    withdraw, sent = buttons(signed_in_client.get(item_page).text)["Ritira da Vinted"]

    signed_in_client.post(withdraw, data=sent)

    assert list(sections(signed_in_client.get("/actions").text)) == ["Vinted"]
    assert table_rows(sections(signed_in_client.get(item_page).text)["Annunci"])[0][:2] == ["Vinted", "da chiudere"]
    _do(signed_in_client, "Vinted", f"Chiudi {BOOSTER_BOX['name']}", "Chiuso")
    listings = sections(signed_in_client.get(item_page).text)["Annunci"]
    assert table_rows(listings) == [["Tilt", "attivo", "122,96 €", "5", LINKS["Tilt"]]]
    assert list(checkboxes(listings, "channel")) == ["Vinted", "eBay"]


# A box opened into packs, which go on sale on Vinted and Tilt; then a second box into the same packs, a new lot of
# theirs. On Tilt the box offers one copy fewer each time, with one action, and the packs 36 more. On Vinted a listing
# of the packs is one pack still: nothing to do there.
def test_boxes_opened_into_packs_on_sale_leave_actions_to_update_the_box_and_the_packs_where_they_offer_several(
    signed_in_client,
):
    box_page = _published(signed_in_client, BOOSTER_BOX, "Tilt")
    opening = links(signed_in_client.get(box_page).text)["Apri in buste"]
    packs = "Busta Evoluzioni a Paldea"
    packs_page = signed_in_client.post(
        opening, data={"lot": "1", "packs": "36", "pack": "", "pack_name": packs}
    ).url.path
    put_on_sale, _ = buttons(signed_in_client.get(packs_page).text)["Metti in vendita"]
    offered = checkboxes(signed_in_client.get(packs_page).text, "channel")
    signed_in_client.post(put_on_sale, data={"channel": [offered["Vinted"], offered["Tilt"]]})
    for channel in ("Vinted", "Tilt"):
        _do(signed_in_client, channel, f"Pubblica {packs}", "Pubblicato", link=f"https://{channel.lower()}.test/busta")

    signed_in_client.post(opening, data={"lot": "1", "packs": "36", "pack": packs_page.removeprefix("/items/")})

    by_channel = sections(signed_in_client.get("/actions").text)
    assert {channel: text(section) for channel, section in by_channel.items()} == {
        "Tilt": f"Tilt 2 da fare Aggiorna {BOOSTER_BOX['name']} Aggiorna {packs}"
    }
    assert _states_and_copies(signed_in_client, box_page) == [["Tilt", "da aggiornare", "3"]]
    assert _states_and_copies(signed_in_client, packs_page) == [
        ["Vinted", "attivo", "1"],
        ["Tilt", "da aggiornare", "72"],
    ]


# A box on sale on Tilt opened into cards, here all bulk, or into packs left closed but one: Tilt offers one fewer.
@pytest.mark.parametrize(
    ("opening", "fields"),
    [
        ("Apri in carte", {"copies": "1", "bulk_cards": "36", "bulk_value": "1,00"}),
        (
            "Apertura mista",
            {"packs": "36", "pack": "", "pack_name": "Busta", "closed": "35", "bulk_cards": "9", "bulk_value": "1,00"},
        ),
    ],
)
def test_a_box_on_sale_opened_into_cards_leaves_an_action_to_offer_one_fewer(signed_in_client, opening, fields):
    box_page = _published(signed_in_client, BOOSTER_BOX, "Tilt")

    signed_in_client.post(links(signed_in_client.get(box_page).text)[opening], data={"lot": "1", **fields})

    assert _states_and_copies(signed_in_client, box_page) == [["Tilt", "da aggiornare", "4"]]


# The only copy of Mew sent to PSA for months: it is no longer there to sell, on Vinted or on Tilt.
def test_the_only_copy_sent_for_grading_leaves_an_action_to_close_each_listing(signed_in_client):
    card_page = _published(signed_in_client, MEW, "Vinted", "Tilt")
    sending = links(signed_in_client.get(card_page).text)["Manda a gradare"]

    signed_in_client.post(sending, data={"lot": "1", "sent_on": "2026-10-29", "grader": "PSA", "cost": "15,00"})

    assert _states_and_copies(signed_in_client, card_page) == [
        ["Vinted", "da chiudere", "1"],
        ["Tilt", "da chiudere", "1"],
    ]


# A pack opened all into bulk, and a Charizard taken out of it, then put on sale on Tilt. A second one taken out into
# the same card is a new lot of it: Tilt offers both.
def test_a_card_taken_out_of_the_bulk_into_a_card_on_sale_leaves_an_action_to_offer_its_copies(signed_in_client):
    pack_page = signed_in_client.post("/items", data={**BOOSTER_BOX, "name": "Busta", "quantity": "1"}).url.path
    opening = links(signed_in_client.get(pack_page).text)["Apri in carte"]
    all_bulk = {"lot": "1", "copies": "1", "bulk_cards": "9", "bulk_value": "1,00"}
    bulk = links(signed_in_client.post(opening, data=all_bulk).text)["Bulk Pokémon Italiano"]
    extraction = links(signed_in_client.get(bulk).text)["Estrai una carta"]
    card_page = signed_in_client.post(extraction, data={"name": "Charizard ex", "number": "199/193"}).url.path
    put_on_sale, _ = buttons(signed_in_client.get(card_page).text)["Metti in vendita"]
    signed_in_client.post(
        put_on_sale, data={"channel": checkboxes(signed_in_client.get(card_page).text, "channel")["Tilt"]}
    )
    _do(signed_in_client, "Tilt", "Pubblica Charizard ex", "Pubblicato", link=LINKS["Tilt"])

    signed_in_client.post(extraction, data={"card": card_page.removeprefix("/items/")})

    assert _states_and_copies(signed_in_client, card_page) == [["Tilt", "da aggiornare", "2"]]


# The target from 20% to 30%, for every item: on Vinted 130,00 €, on Tilt 133,17 €, which keeps 2% + 0,50 € of it.
def test_a_target_margin_changed_leaves_an_action_to_update_every_listing_to_its_new_price(signed_in_client):
    item_page = _published(signed_in_client, BOOSTER_BOX, "Vinted", "Tilt")

    signed_in_client.post("/target-margin", data={"target_margin": "30"})

    assert _channels_and_prices(signed_in_client, item_page) == [
        ["Vinted", "da aggiornare", "130,00 €"],
        ["Tilt", "da aggiornare", "133,17 €"],
    ]


# Tilt keeps 5% + 0,50 € now: 126,85 € leaves the 120,00 € of the target. Vinted's price is as it was.
def test_a_fee_changed_leaves_an_action_to_update_the_listings_on_that_channel_only(signed_in_client):
    item_page = _published(signed_in_client, BOOSTER_BOX, "Vinted", "Tilt")
    tilt = links(signed_in_client.get("/channels").text)["Tilt"]

    signed_in_client.post(tilt, data={"fee_percent": "5", "fee_fixed": "0,50"})

    assert _channels_and_prices(signed_in_client, item_page) == [
        ["Vinted", "attivo", "120,00 €"],
        ["Tilt", "da aggiornare", "126,85 €"],
    ]


def _channels_and_prices(client, item_page: str) -> list[list[str]]:
    """The channel, the state and the price of each listing on the item's page."""
    return [row[:3] for row in table_rows(sections(client.get(item_page).text)["Annunci"])]


def _states_and_copies(client, item_page: str) -> list[list[str]]:
    """The channel, the state and the copies of each listing on the item's page."""
    rows = table_rows(sections(client.get(item_page).text)["Annunci"])
    return [[channel, state, copies] for channel, state, _, copies, _ in rows]


def _published(client, item: dict, *channels: str) -> str:
    """The page of an item loaded, put on sale on those channels and published on each, its link pasted."""
    item_page = _on_sale(client, item, *channels)
    for channel in channels:
        _do(client, channel, f"Pubblica {item['name']}", "Pubblicato", link=LINKS[channel])
    return item_page


def _do(client, channel: str, action: str, button: str, **fields) -> None:
    """Manuel opens the action from the list of those to do on the channel, and ticks it."""
    page = client.get(links(sections(client.get("/actions").text)[channel])[action])
    done, _ = buttons(page.text)[button]
    client.post(done, data=fields)
