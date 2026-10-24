from datetime import UTC, datetime

import pytest

from cards_warehouse import ebay_connect
from tests.fake_ebay import CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, RUNAME, FakeEbay
from tests.test_ebay import ebay_page, signed_in

NOW = datetime(2026, 10, 23, 15, 30, tzinfo=UTC)


# Manuel opens the link, agrees on eBay, and pastes the address of the page where the browser lands.
# What comes back is what goes into Infisical: the durable credential, and the day it ends.
def test_connecting_the_account_gives_the_values_to_put_in_infisical():
    values = connect(FakeEbay())

    assert values == {
        "EBAY_ENVIRONMENT": "sandbox",
        "EBAY_REFRESH_TOKEN": REFRESH_TOKEN,
        # 47,304,000 s after the grant, as eBay answered.
        "EBAY_AUTHORIZATION_EXPIRES": "2028-04-23T03:30:00Z",
    }


# Pasted into Infisical as they are, next to the keys of the developer portal, they connect the app.
@pytest.mark.usefixtures("database")
def test_the_values_put_in_infisical_connect_the_app(monkeypatch):
    fake_ebay = FakeEbay()
    for name, value in connect(fake_ebay).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("EBAY_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("EBAY_CLIENT_SECRET", CLIENT_SECRET)

    page = ebay_page(signed_in(fake_ebay))

    assert "Collegato." in page
    assert "Prova (sandbox)" in page
    assert "23/04/2028" in page


# Consent declined, or the wrong address pasted: no code to trade.
def test_an_address_without_a_code_is_refused_with_what_to_do():
    declined = "https://auth.sandbox.ebay.com/oauth2/ThirdPartyAuthSucessFailure?isAuthSuccessful=false"

    with pytest.raises(ebay_connect.ConnectFailed, match="no code.*open the link again"):
        connect(FakeEbay(), accepted_address=declined)


# eBay's code lasts 299 s and works once: pasted late, or twice, eBay refuses it.
def test_a_code_ebay_refuses_is_reported_with_what_to_do():
    fake_ebay = FakeEbay()
    late = fake_ebay.consent(ebay_connect.consent_url("sandbox", CLIENT_ID, RUNAME)).replace("code=", "code=old")

    with pytest.raises(ebay_connect.ConnectFailed, match="invalid_grant.*open the link again"):
        connect(fake_ebay, accepted_address=late)


def connect(fake_ebay: FakeEbay, accepted_address: str | None = None) -> dict[str, str]:
    if accepted_address is None:
        accepted_address = fake_ebay.consent(ebay_connect.consent_url("sandbox", CLIENT_ID, RUNAME))
    return ebay_connect.values_for_infisical(
        fake_ebay.http(),
        environment="sandbox",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        runame=RUNAME,
        accepted_address=accepted_address,
        now=NOW,
    )
