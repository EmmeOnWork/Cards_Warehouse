"""Connects Manuel's eBay account to the app, from the PC: make ebay-connect.

Nothing on the PC has to answer eBay. eBay sends the browser back to a page of its own, with a code in the address;
Manuel pastes the address here, and the code becomes the durable credential, printed once for Infisical.
"""

import getpass
import sys
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from cards_warehouse.ebay import SCOPES, TOKEN_URLS

CONSENT_URLS = {
    "sandbox": "https://auth.sandbox.ebay.com/oauth2/authorize",
    "production": "https://auth.ebay.com/oauth2/authorize",
}
AGAIN = "open the link again, agree, and paste the new address within 5 minutes"


class ConnectFailed(Exception):
    """No durable credential: the message says why, and what to do."""


def consent_url(environment: str, client_id: str, runame: str) -> str:
    """The page where Manuel signs in to eBay and lets the app act on the account."""
    query = {"client_id": client_id, "redirect_uri": runame, "response_type": "code", "scope": " ".join(SCOPES)}
    return f"{CONSENT_URLS[environment]}?{urlencode(query)}"


def values_for_infisical(
    http: httpx.Client,
    *,
    environment: str,
    client_id: str,
    client_secret: str,
    runame: str,
    accepted_address: str,
    now: datetime,
) -> dict[str, str]:
    """Trades the code in the address of eBay's page for the durable credential."""
    # Read from the address as the browser shows it, percent-encoded: parse_qs decodes it, once.
    codes = parse_qs(urlsplit(accepted_address.strip()).query).get("code")
    if not codes:
        raise ConnectFailed(f"The address holds no code: consent declined, or another address pasted. {AGAIN}.")
    response = http.post(
        TOKEN_URLS[environment],
        auth=(client_id, client_secret),
        data={"grant_type": "authorization_code", "code": codes[0], "redirect_uri": runame},
    )
    answer = response.json()
    if response.is_error:
        # invalid_grant: the code came late or twice. invalid_client: a key typed wrong at the questions above.
        raise ConnectFailed(
            f"eBay refused the request ({answer.get('error', response.status_code)}): "
            f"check the keys and the RuName, then {AGAIN}."
        )
    expires = now + timedelta(seconds=answer["refresh_token_expires_in"])
    return {
        "EBAY_ENVIRONMENT": environment,
        "EBAY_REFRESH_TOKEN": answer["refresh_token"],
        "EBAY_AUTHORIZATION_EXPIRES": f"{expires:%Y-%m-%dT%H:%M:%SZ}",
    }


if __name__ == "__main__":
    # The keys from the developer portal: Application Keys for the first two, User Tokens for the RuName.
    environment = input("Environment, sandbox or production [sandbox]: ").strip() or "sandbox"
    if environment not in CONSENT_URLS:
        sys.exit("The environment is sandbox or production.")
    client_id = input("Client ID (App ID): ").strip()
    # Not echoed, as for the password of the app.
    client_secret = getpass.getpass("Client secret (Cert ID): ").strip()
    runame = input("RuName: ").strip()
    # A private window: no eBay session already open signs in a different account in its place.
    print("\nOpen this link in a private window of the browser, sign in with the eBay account, and agree:\n")
    print(consent_url(environment, client_id, runame))
    accepted_address = input("\nThen paste here the address of the page where eBay leaves you: ")
    try:
        with httpx.Client(timeout=30) as http:
            values = values_for_infisical(
                http,
                environment=environment,
                client_id=client_id,
                client_secret=client_secret,
                runame=runame,
                accepted_address=accepted_address,
                now=datetime.now(UTC),
            )
    except ConnectFailed as failure:
        sys.exit(str(failure))
    # Shown once, here, and nowhere else: no file, no log. The pod gets them from Infisical within a minute.
    print("\nPut these in Infisical, project cards-warehouse, environment prod, folder /app,")
    print("next to EBAY_CLIENT_ID and EBAY_CLIENT_SECRET:\n")
    for name, value in values.items():
        print(f"{name}={value}")
