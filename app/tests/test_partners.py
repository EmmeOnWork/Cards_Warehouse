"""The partners, edited from the app, and offered by the load page to share a purchase.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import html

import pytest

from tests.pages import links, table_rows


# Manuel is in every purchase without being a partner: the load page offers him first, then the partners.
def test_a_partner_added_from_the_app_is_offered_at_once_to_share_a_purchase(signed_in_client):
    signed_in_client.post("/partners", data={"name": "Luca"})

    assert table_rows(signed_in_client.get("/partners").text) == [["Luca"]]
    assert [row[0] for row in table_rows(signed_in_client.get("/items/new").text)] == ["Manuel", "Luca"]


# A partner in a purchase cannot go away, but a name typed wrong is fixed.
def test_a_partner_is_renamed_from_the_app(signed_in_client):
    signed_in_client.post("/partners", data={"name": "Lucca"})
    lucca = links(signed_in_client.get("/partners").text)["Lucca"]

    signed_in_client.post(lucca, data={"name": "Luca"})

    assert table_rows(signed_in_client.get("/partners").text) == [["Luca"]]


# Two partners with one name could not be told apart on a purchase.
@pytest.mark.parametrize(("name", "reason"), [("Luca", "Luca c'è già."), ("  ", "Scrivi il nome del collaboratore.")])
def test_a_name_taken_or_empty_is_refused_when_adding_or_renaming(signed_in_client, name, reason):
    signed_in_client.post("/partners", data={"name": "Luca"})
    signed_in_client.post("/partners", data={"name": "Marco"})
    marco = links(signed_in_client.get("/partners").text)["Marco"]

    for refused in (
        signed_in_client.post("/partners", data={"name": name}),
        signed_in_client.post(marco, data={"name": name}),
    ):
        assert refused.status_code == 422
        assert reason in html.unescape(refused.text)

    assert table_rows(signed_in_client.get("/partners").text) == [["Luca"], ["Marco"]]
