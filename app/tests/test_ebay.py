import html
import logging

import pytest
from fastapi.testclient import TestClient

from cards_warehouse import ebay
from cards_warehouse.main import create_app
from tests.acceptance.containers import TEST_PASSWORD
from tests.fake_ebay import CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, FakeEbay
from tests.test_access import FakeClock


# "Collegato" only once eBay has given a short-lived token for the account: a stored credential alone proves nothing.
def test_the_ebay_page_shows_a_connected_sandbox_account_and_when_its_authorization_ends(monkeypatch):
    connect_account(monkeypatch)

    page = ebay_page(signed_in(FakeEbay()))

    assert "Collegato." in page
    assert "Prova (sandbox)" in page
    assert "23/04/2028" in page


# Task 37 swaps the values in Infisical: the app then asks the real eBay, never the sandbox, and says so.
def test_with_the_real_account_the_app_asks_the_real_ebay_and_the_page_says_so(monkeypatch):
    connect_account(monkeypatch, environment="production")

    page = ebay_page(signed_in(FakeEbay(host="api.ebay.com")))

    assert "Collegato." in page
    assert "Reale" in page


# Until Manuel connects the account, Infisical holds no eBay values: the app starts all the same, and says what to do.
def test_without_an_ebay_account_the_page_says_it_is_not_connected_and_how_to_connect_it():
    page = ebay_page(signed_in(FakeEbay()))

    assert "Non collegato. Per collegarlo, dal PC: make ebay-connect." in page


# The calls to eBay's APIs need a token of two hours: the account asks for one with its durable credential.
def test_a_connected_account_gets_a_short_lived_token_from_ebay(monkeypatch):
    connect_account(monkeypatch)
    account = ebay.account_from_environment(FakeEbay().http(), clock=FakeClock())

    assert account.access_token() == "access-token-1"


# Not a request to eBay for every call: the same token for two hours, less 5 minutes, so that a call
# sent just before the end never reaches eBay with a token gone stale on the way.
def test_the_short_lived_token_is_reused_until_5_minutes_before_it_expires(monkeypatch):
    connect_account(monkeypatch)
    clock = FakeClock()
    account = ebay.account_from_environment(FakeEbay().http(), clock=clock)

    assert account.access_token() == "access-token-1"
    clock.now += 2 * 60 * 60 - 5 * 60 - 1
    assert account.access_token() == "access-token-1"
    clock.now += 1
    assert account.access_token() == "access-token-2"


# Revoked by Manuel on eBay, by a new password of the account, or past its 18 months: the same answer from eBay.
def test_the_ebay_page_warns_when_ebay_no_longer_accepts_the_authorization(monkeypatch):
    connect_account(monkeypatch)
    fake_ebay = FakeEbay()
    fake_ebay.revoke()

    page = ebay_page(signed_in(fake_ebay))

    assert "Attenzione: eBay non accetta più l'autorizzazione" in page
    assert "make ebay-connect" in page


# Not the same as a refused authorization: nothing to reconnect, it passes on its own.
@pytest.mark.parametrize("outage", ["unreachable", "broken"])
def test_the_ebay_page_says_when_ebay_does_not_answer(monkeypatch, outage):
    connect_account(monkeypatch)
    fake_ebay = FakeEbay()
    fake_ebay.fail(outage)

    page = ebay_page(signed_in(fake_ebay))

    assert "Attenzione: eBay non risponde, riprova più tardi." in page


# A key pasted wrong into Infisical: eBay's reason on the page, and where to look.
def test_the_ebay_page_says_when_ebay_refuses_the_keys_of_the_app(monkeypatch):
    connect_account(monkeypatch)
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "a-mistyped-secret")

    page = ebay_page(signed_in(FakeEbay()))

    assert "Attenzione: eBay rifiuta la richiesta (invalid_client)" in page
    assert "EBAY_CLIENT_SECRET" in page


# The pod's log is read with kubectl by anyone with access to the cluster: no credential goes there, not even when
# something fails, nor on the page. Every logger at its most talkative, the HTTP client's included.
@pytest.mark.parametrize("trouble", [None, "revoked", "unreachable"])
def test_no_ebay_credential_reaches_the_log_or_the_page(monkeypatch, caplog, trouble):
    caplog.set_level(logging.DEBUG)
    connect_account(monkeypatch)
    fake_ebay = FakeEbay()
    if trouble == "revoked":
        fake_ebay.revoke()
    elif trouble == "unreachable":
        fake_ebay.fail(trouble)

    page = ebay_page(signed_in(fake_ebay))

    for credential in (REFRESH_TOKEN, CLIENT_SECRET, "access-token-1"):
        assert credential not in caplog.text
        assert credential not in page


# What Manuel puts in Infisical: the keys from the developer portal, and what make ebay-connect prints.
def connect_account(monkeypatch, environment: str = "sandbox") -> None:
    monkeypatch.setenv("EBAY_ENVIRONMENT", environment)
    monkeypatch.setenv("EBAY_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("EBAY_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("EBAY_REFRESH_TOKEN", REFRESH_TOKEN)
    monkeypatch.setenv("EBAY_AUTHORIZATION_EXPIRES", "2028-04-23T10:15:00Z")


def signed_in(fake_ebay: FakeEbay) -> TestClient:
    client = TestClient(create_app(ebay_http=fake_ebay.http()))
    client.post("/login", data={"password": TEST_PASSWORD})
    return client


# The text the page shows, as read on screen: the page escapes characters such as the apostrophe.
def ebay_page(client: TestClient) -> str:
    response = client.get("/ebay")
    assert response.status_code == 200
    return html.unescape(response.text)
