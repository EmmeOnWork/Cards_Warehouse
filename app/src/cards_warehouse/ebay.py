"""The connection to Manuel's eBay account, through OAuth: the app never knows the account's password.

Manuel grants it once, from the PC, with make ebay-connect. eBay gives back a durable credential, the refresh token,
which lives in Infisical. With it the app asks eBay for the short-lived tokens its calls need.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx

from cards_warehouse.backups import LOCAL_TIME

TOKEN_URLS = {
    "sandbox": "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
    "production": "https://api.ebay.com/identity/v1/oauth2/token",
}
# Where the APIs of a seller answer: most on api, the images (Media API) on apim.
API_URLS = {"sandbox": "https://api.sandbox.ebay.com", "production": "https://api.ebay.com"}
MEDIA_URLS = {"sandbox": "https://apim.sandbox.ebay.com", "production": "https://apim.ebay.com"}
# Where a buyer sees a listing, by its number. The sandbox shows every listing on its .com site.
LISTING_PAGES = {"sandbox": "https://sandbox.ebay.com/itm/", "production": "https://www.ebay.it/itm/"}
# What the app may do on the account, asked when Manuel grants it: publishing and closing listings (inventory),
# the seller's policies (account), reading the orders (fulfillment). A renewal asks for the same.
SCOPES = (
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
)
# A token is replaced this long before eBay's end, so a call sent just before it never arrives with a stale one.
RENEW_BEFORE_SECONDS = 5 * 60
ENVIRONMENT_NAMES = {"sandbox": "Prova (sandbox)", "production": "Reale"}


class AuthorizationRefused(Exception):
    """eBay no longer accepts the durable credential: revoked, or expired. Only make ebay-connect brings it back."""


class EbayUnavailable(Exception):
    """eBay does not answer, or answers with an error of its own: it passes without doing anything."""


class RequestRefused(Exception):
    """eBay refuses what the app sends, most likely a key mistyped in Infisical. Carries eBay's reason."""


@dataclass(frozen=True)
class Status:
    """What the eBay page shows."""

    text: str
    # Something to look at: the page shows it in red.
    alarm: bool = False
    environment: str = ""
    # The day the durable credential ends: Manuel connects the account again before it.
    expires: str = ""


class Account:
    def __init__(
        self,
        *,
        environment: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        authorization_expires: datetime,
        http: httpx.Client,
        clock: Callable[[], float],
    ) -> None:
        self._environment = environment
        self._authorization_expires = authorization_expires
        self._token_url = TOKEN_URLS[environment]
        self._keys = (client_id, client_secret)
        self._refresh_token = refresh_token
        self._http = http
        self._clock = clock
        self._access_token = ""
        self._renew_at = 0.0

    def access_token(self) -> str:
        if self._clock() >= self._renew_at:
            # From when it was asked: the time on the way to eBay and back counts against it.
            started = self._clock()
            answer = self._new_token()
            self._access_token = answer["access_token"]
            self._renew_at = started + answer["expires_in"] - RENEW_BEFORE_SECONDS
        return self._access_token

    def api(self, path: str) -> str:
        return f"{API_URLS[self._environment]}{path}"

    def media(self, path: str) -> str:
        return f"{MEDIA_URLS[self._environment]}{path}"

    def listing_page(self, listing_id: str) -> str:
        return f"{LISTING_PAGES[self._environment]}{listing_id}"

    def request(self, method: str, url: str, **options) -> httpx.Response:
        """A call to one of eBay's APIs on the account, with a short-lived token. EbayUnavailable when eBay does not
        answer, or answers with an error of its own: what eBay refuses comes back as it is, for the caller to read."""
        headers = {"Authorization": f"Bearer {self.access_token()}", **options.pop("headers", {})}
        try:
            response = self._http.request(method, url, headers=headers, **options)
        except httpx.HTTPError as error:
            raise EbayUnavailable from error
        if response.is_server_error:
            raise EbayUnavailable
        return response

    def _new_token(self) -> dict:
        try:
            response = self._http.post(
                self._token_url,
                auth=self._keys,
                data={"grant_type": "refresh_token", "refresh_token": self._refresh_token, "scope": " ".join(SCOPES)},
            )
        except httpx.HTTPError as error:
            raise EbayUnavailable from error
        if response.is_server_error:
            raise EbayUnavailable
        answer = response.json()
        if answer.get("error") == "invalid_grant":
            raise AuthorizationRefused
        if response.is_error:
            raise RequestRefused(answer.get("error", response.status_code))
        return answer

    # Connected only once eBay has given a token for the account: a stored credential alone proves nothing.
    def status(self) -> Status:
        try:
            self.access_token()
        except AuthorizationRefused:
            return self._status(
                "Attenzione: eBay non accetta più l'autorizzazione: revocata, oppure scaduta. "
                "Ricollega l'account dal PC con make ebay-connect.",
                alarm=True,
            )
        except EbayUnavailable:
            return self._status("Attenzione: eBay non risponde, riprova più tardi.", alarm=True)
        except RequestRefused as refusal:
            return self._status(
                f"Attenzione: eBay rifiuta la richiesta ({refusal}). "
                "Controlla EBAY_CLIENT_ID e EBAY_CLIENT_SECRET in Infisical.",
                alarm=True,
            )
        return self._status("Collegato.")

    def _status(self, text: str, alarm: bool = False) -> Status:
        return Status(
            text,
            alarm=alarm,
            environment=ENVIRONMENT_NAMES[self._environment],
            expires=f"{self._authorization_expires.astimezone(LOCAL_TIME):%d/%m/%Y}",
        )


def status(account: Account | None) -> Status:
    if account is None:
        return Status("Non collegato. Per collegarlo, dal PC: make ebay-connect.")
    return account.status()


def account_from_environment(http: httpx.Client, clock: Callable[[], float]) -> Account | None:
    """The account whose values Manuel put in Infisical, or None before the first make ebay-connect."""
    if "EBAY_REFRESH_TOKEN" not in os.environ:
        return None
    return Account(
        environment=os.environ["EBAY_ENVIRONMENT"],
        client_id=os.environ["EBAY_CLIENT_ID"],
        client_secret=os.environ["EBAY_CLIENT_SECRET"],
        refresh_token=os.environ["EBAY_REFRESH_TOKEN"],
        authorization_expires=datetime.fromisoformat(os.environ["EBAY_AUTHORIZATION_EXPIRES"]),
        http=http,
        clock=clock,
    )
