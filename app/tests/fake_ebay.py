"""eBay's OAuth as the app and make ebay-connect see it, with no network: it checks what the real one checks."""

import base64
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

# Plainly fake, so no secret scanner mistakes them for real ones. Code and refresh token keep the ^ and # of eBay's:
# they arrive percent-encoded in the address, and sent unencoded they would break the form.
CLIENT_ID = "Manuel-cardswar-SBX-test"
CLIENT_SECRET = "test-client-secret"
RUNAME = "Manuel_Monastero-Manuel-cardsw-test"
AUTHORIZATION_CODE = "v^1.1#i^1#f^0#test-authorization-code"
REFRESH_TOKEN = "v^1.1#i^1#test-refresh-token"
# What a new keyset may ask for, as the developer portal lists it: more than the app asks.
KEYSET_SCOPES = {
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.marketing",
    "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
}
# What eBay answers with the refresh token: about 18 months.
REFRESH_TOKEN_SECONDS = 47_304_000


class FakeEbay:
    def __init__(self, host: str = "api.sandbox.ebay.com") -> None:
        self.host = host
        self._issued = 0
        self._revoked = False
        self._outage: str | None = None

    def http(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._answer))

    def consent(self, link: str) -> str:
        """Manuel opens the link, signs in and agrees: the address of eBay's page where the browser lands."""
        address = urlsplit(link)
        query = {name: values[0] for name, values in parse_qs(address.query).items()}
        assert f"https://{address.netloc}{address.path}" == f"https://{self._auth_host()}/oauth2/authorize"
        assert query["client_id"] == CLIENT_ID
        assert query["redirect_uri"] == RUNAME
        assert query["response_type"] == "code"
        assert set(query["scope"].split()) <= KEYSET_SCOPES
        landing = urlencode({"isAuthSuccessful": "true", "code": AUTHORIZATION_CODE, "expires_in": 299})
        return f"https://{self._auth_host()}/oauth2/ThirdPartyAuthSucessFailure?{landing}"

    # What happens when Manuel removes the app from the eBay account, or changes the account's password.
    def revoke(self) -> None:
        self._revoked = True

    # "unreachable": no answer at all, as with no network. "broken": eBay answers, with an error page of its own.
    def fail(self, outage: str) -> None:
        self._outage = outage

    def _answer(self, request: httpx.Request) -> httpx.Response:
        if self._outage == "unreachable":
            raise httpx.ConnectError("[Errno -3] Temporary failure in name resolution", request=request)
        if self._outage == "broken":
            return httpx.Response(503, text="<html>Service Unavailable</html>")
        if request.method != "POST" or request.url != f"https://{self.host}/identity/v1/oauth2/token":
            return httpx.Response(404)
        keys = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        if request.headers.get("authorization") != f"Basic {keys}":
            return _error(401, "invalid_client", "client authentication failed")
        form = {name: values[0] for name, values in parse_qs(request.content.decode()).items()}
        if form.get("grant_type") == "authorization_code":
            return self._grant(form)
        if form.get("grant_type") == "refresh_token":
            return self._renewal(form)
        return _error(400, "unsupported_grant_type", "the grant type is not supported")

    # The code of the consent, for the durable credential. eBay's code is single use and lasts 299 s: the fake
    # checks only that it is the one it gave, sent back with the same RuName.
    def _grant(self, form: dict[str, str]) -> httpx.Response:
        if form.get("code") != AUTHORIZATION_CODE or form.get("redirect_uri") != RUNAME:
            return _error(400, "invalid_grant", "the provided authorization grant code is invalid")
        self._issued += 1
        return httpx.Response(
            200,
            json={
                "access_token": f"access-token-{self._issued}",
                "expires_in": 7200,
                "refresh_token": REFRESH_TOKEN,
                "refresh_token_expires_in": REFRESH_TOKEN_SECONDS,
                "token_type": "User Access Token",
            },
        )

    # The durable credential, for a short-lived token. The scopes are required, within those of the consent.
    def _renewal(self, form: dict[str, str]) -> httpx.Response:
        if not form.get("scope") or not set(form["scope"].split()) <= KEYSET_SCOPES:
            return _error(400, "invalid_scope", "the requested scope is invalid")
        if form.get("refresh_token") != REFRESH_TOKEN or self._revoked:
            return _error(400, "invalid_grant", "the provided authorization refresh token is invalid")
        self._issued += 1
        return httpx.Response(
            200,
            json={
                "access_token": f"access-token-{self._issued}",
                "expires_in": 7200,
                "token_type": "User Access Token",
            },
        )

    def _auth_host(self) -> str:
        return self.host.replace("api.", "auth.", 1)


def _error(status: int, error: str, description: str) -> httpx.Response:
    return httpx.Response(status, json={"error": error, "error_description": description})
