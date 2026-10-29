"""eBay as the app and make ebay-connect see it, with no network: its OAuth, and the APIs that publish a listing.
It checks what the real one checks."""

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
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
# The seller's policies on eBay Italy, and the place the goods leave from, as make ebay-setup prints them.
FULFILLMENT_POLICY_ID = "6200000001"
PAYMENT_POLICY_ID = "6200000002"
RETURN_POLICY_ID = "6200000003"
LOCATION_KEY = "magazzino"
# The conditions each category takes, with the descriptors each one requires. A single card is graded (LIKE_NEW,
# eBay's 2750) with its grader and grade, or not graded (USED_VERY_GOOD, 4000) with the state of the card.
CATEGORY_CONDITIONS = {
    "183454": {"LIKE_NEW": {"27501", "27502"}, "USED_VERY_GOOD": {"40001"}},
    "261044": {"NEW": set()},
}
TITLE_LIMIT = 80


@dataclass(frozen=True)
class PublishedListing:
    """A listing live on the fake eBay, as a buyer would see it."""

    listing_id: str
    category_id: str
    title: str
    description: str
    # The value as eBay writes it, and the currency.
    price: tuple[str, str]
    quantity: int
    # What eBay downloaded for each image of the listing, in its order.
    photos: list[bytes]
    condition: str
    # The values of each descriptor, by its name.
    condition_descriptors: dict[str, list[str]]


POLICY_KINDS = ("fulfillment", "payment", "return")


class FakeEbay:
    def __init__(
        self,
        host: str = "api.sandbox.ebay.com",
        photos: Callable[[str], bytes] | None = None,
        seller_set_up: bool = True,
    ) -> None:
        self.host = host
        # What eBay gets when it downloads an image from a link: the photo, while the link opens it.
        self._download = photos or _nothing_at
        self._issued = 0
        self._revoked = False
        self._outage: str | None = None
        # The seller's account: opted in to the business policies, with one of each, and the place the goods leave
        # from, as after make ebay-setup. Or new, with nothing.
        self._opted_in = seller_set_up
        self._policies: dict[str, dict[str, str]] = {kind: {} for kind in POLICY_KINDS}
        self._locations: dict[str, dict] = {}
        if seller_set_up:
            self._policies = {
                "fulfillment": {FULFILLMENT_POLICY_ID: "Spedizione"},
                "payment": {PAYMENT_POLICY_ID: "Pagamento"},
                "return": {RETURN_POLICY_ID: "Reso"},
            }
            self._locations[LOCATION_KEY] = {"postalCode": "20121", "city": "Milano", "country": "IT"}
        self._images: dict[str, bytes] = {}
        self._inventory: dict[str, dict] = {}
        self._offers: dict[str, dict] = {}
        self.listings: list[PublishedListing] = []
        # Every call to the APIs of a seller, answered or refused.
        self.requests_to_sell = 0

    def http(self) -> httpx.Client:
        return httpx.Client(transport=self.transport())

    def transport(self) -> httpx.BaseTransport:
        return httpx.MockTransport(self._answer)

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

    # Made by Manuel on eBay's page of the policies, where he picks the shipping service: the app does not make it.
    def create_shipping_policy(self, name: str) -> str:
        policy_id = self._new_policy_id()
        self._policies["fulfillment"][policy_id] = name
        return policy_id

    @property
    def policies(self) -> dict[str, int]:
        """How many policies of each kind the seller has."""
        return {kind: len(made) for kind, made in self._policies.items()}

    def location(self, key: str) -> dict:
        return self._locations[key]

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
        if request.url.host == self._media_host() or request.url.path.startswith("/sell/"):
            return self._sell(request)
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

    def _media_host(self) -> str:
        return self.host.replace("api.", "apim.", 1)

    # The APIs of a seller: with a short-lived token the fake gave, as the real ones want it.
    def _sell(self, request: httpx.Request) -> httpx.Response:
        self.requests_to_sell += 1
        tokens = {f"Bearer access-token-{issued}" for issued in range(1, self._issued + 1)}
        if request.headers.get("authorization") not in tokens:
            return _refusal(401, 1001, "Invalid access token")
        path, method = request.url.path, request.method
        if request.url.host == self._media_host() and (method, path) == (
            "POST",
            "/commerce/media/v1_beta/image/create_image_from_url",
        ):
            return self._image_from_url(json.loads(request.content))
        if request.url.host != self.host:
            return _refusal(404, 2002, "Resource not found.")
        if path.startswith("/sell/account/v1/"):
            return self._account_api(method, path.removeprefix("/sell/account/v1/"), request)
        if method == "POST" and path.startswith("/sell/inventory/v1/location/"):
            return self._new_location(path.rsplit("/", 1)[1], json.loads(request.content))
        # The language of the texts sent: eBay refuses an inventory item or an offer without it.
        if method in ("PUT", "POST") and request.headers.get("content-language") != "it-IT":
            return _refusal(400, 25709, "Invalid value for header Content-Language.")
        if method == "PUT" and path.startswith("/sell/inventory/v1/inventory_item/"):
            self._inventory[path.rsplit("/", 1)[1]] = json.loads(request.content)
            return httpx.Response(204)
        if (method, path) == ("POST", "/sell/inventory/v1/offer"):
            return self._new_offer(json.loads(request.content))
        if method == "POST" and path.startswith("/sell/inventory/v1/offer/") and path.endswith("/publish"):
            return self._publish(path.split("/")[-2])
        if method == "PUT" and path.startswith("/sell/inventory/v1/offer/"):
            return self._update_offer(path.rsplit("/", 1)[1], json.loads(request.content))
        return _refusal(404, 2002, "Resource not found.")

    # The business policies: opting in, listing those of a marketplace, making a payment or a return policy.
    def _account_api(self, method: str, path: str, request: httpx.Request) -> httpx.Response:
        if (method, path) == ("GET", "program/get_opted_in_programs"):
            programs = [{"programType": "SELLING_POLICY_MANAGEMENT"}] if self._opted_in else []
            return httpx.Response(200, json={"programs": programs})
        if (method, path) == ("POST", "program/opt_in"):
            if json.loads(request.content).get("programType") != "SELLING_POLICY_MANAGEMENT":
                return _refusal(400, 20401, "Invalid program type.", domain="API_ACCOUNT")
            self._opted_in = True
            return httpx.Response(200, json={})
        kind = path.removesuffix("_policy")
        if kind not in POLICY_KINDS:
            return _refusal(404, 2002, "Resource not found.")
        if not self._opted_in:
            return _refusal(400, 20403, "User is not eligible for Business Policy.", domain="API_ACCOUNT")
        if method == "GET":
            if request.url.params.get("marketplace_id") != "EBAY_IT":
                return _refusal(400, 20401, "Invalid marketplace_id.", domain="API_ACCOUNT")
            policies = [
                {f"{kind}PolicyId": policy_id, "name": name, "marketplaceId": "EBAY_IT"}
                for policy_id, name in self._policies[kind].items()
            ]
            return httpx.Response(200, json={"total": len(policies), f"{kind}Policies": policies})
        if method == "POST" and kind in ("payment", "return"):
            policy = json.loads(request.content)
            if policy.get("marketplaceId") != "EBAY_IT" or not policy.get("name") or not policy.get("categoryTypes"):
                return _refusal(400, 20401, "Missing field marketplaceId, name or categoryTypes.", domain="API_ACCOUNT")
            policy_id = self._new_policy_id()
            self._policies[kind][policy_id] = policy["name"]
            return httpx.Response(201, json={f"{kind}PolicyId": policy_id, **policy})
        return _refusal(404, 2002, "Resource not found.")

    def _new_policy_id(self) -> str:
        return f"{6_100_000_000 + sum(len(made) for made in self._policies.values()) + 1}"

    def _new_location(self, key: str, body: dict) -> httpx.Response:
        if key in self._locations:
            return _refusal(409, 25803, "Location already exists.")
        address = body.get("location", {}).get("address", {})
        if address.get("country") != "IT" or not address.get("postalCode"):
            return _refusal(400, 25802, "Input error: country and postalCode are required.")
        self._locations[key] = address
        return httpx.Response(204)

    # eBay downloads the image at once, over HTTPS, into its own servers: the listing shows that copy.
    def _image_from_url(self, body: dict) -> httpx.Response:
        link = body.get("imageUrl", "")
        try:
            if not link.startswith("https://"):
                raise KeyError(link)
            photo = self._download(link)
        except KeyError:
            return _refusal(400, 190204, "The image could not be downloaded from the URL, or the URL is not HTTPS.")
        image_id = f"fake{len(self._images) + 1:04d}"
        hosted = f"https://i.ebayimg.sandbox.ebay.com/images/g/{image_id}/s-l1600.jpg"
        self._images[hosted] = photo
        return httpx.Response(
            201,
            headers={"location": f"https://{self._media_host()}/commerce/media/v1_beta/image/{image_id}"},
            json={"imageUrl": hosted, "expirationDate": "2026-11-29T10:00:00.000Z"},
        )

    @property
    def offers(self) -> int:
        """The offers eBay keeps, published or not."""
        return len(self._offers)

    # One offer per item and marketplace: eBay refuses a second, and says which one it has.
    def _new_offer(self, offer: dict) -> httpx.Response:
        if offer.get("sku") not in self._inventory:
            return _refusal(400, 25702, f"SKU {offer.get('sku')} is not available in the system.")
        for offer_id, kept in self._offers.items():
            if (kept["sku"], kept["marketplaceId"]) == (offer["sku"], offer.get("marketplaceId")):
                return _refusal(
                    400,
                    25002,
                    "A user error has occurred. Offer entity already exists.",
                    parameters=[{"name": "offerId", "value": offer_id}],
                )
        offer_id = f"{9_000_000_000 + len(self._offers) + 1}"
        self._offers[offer_id] = offer
        return httpx.Response(201, json={"offerId": offer_id})

    # Everything but the item, the marketplace and the format, which an offer keeps from its start.
    def _update_offer(self, offer_id: str, values: dict) -> httpx.Response:
        if offer_id not in self._offers:
            return _refusal(404, 25713, "This Offer is not available.")
        self._offers[offer_id] = {**self._offers[offer_id], **values}
        return httpx.Response(204)

    # What eBay checks before the listing goes live: the seller's policies and location, the category's
    # condition, at least one image of its own, and a title that fits.
    def _publish(self, offer_id: str) -> httpx.Response:
        offer = self._offers.get(offer_id)
        if offer is None:
            return _refusal(404, 25713, "This Offer is not available.")
        item = self._inventory[offer["sku"]]
        product = item.get("product", {})
        policies = offer.get("listingPolicies", {})
        if not self._opted_in or any(
            policies.get(f"{kind}PolicyId") not in self._policies[kind] for kind in POLICY_KINDS
        ):
            return _refusal(400, 25007, "Please add at least one valid shipping service option to your listing.")
        if offer.get("merchantLocationKey") not in self._locations:
            return _refusal(400, 25002, "A user error has occurred. No Item.Country exists or Item.Country is invalid.")
        if (offer.get("marketplaceId"), offer.get("format")) != ("EBAY_IT", "FIXED_PRICE"):
            return _refusal(400, 25002, "A user error has occurred. The marketplace or the format is not valid.")
        conditions = CATEGORY_CONDITIONS.get(offer.get("categoryId"))
        if conditions is None:
            return _refusal(400, 25005, "The category is not valid: choose a leaf category.")
        descriptors = {d["name"]: d.get("values", []) for d in item.get("conditionDescriptors", [])}
        if item.get("condition") not in conditions or not conditions[item["condition"]] <= set(descriptors):
            return _refusal(400, 25021, "The item condition is not valid for the category.")
        images = product.get("imageUrls", [])
        if not images or any(image not in self._images for image in images):
            return _refusal(400, 25002, "A user error has occurred. At least 1 picture is required.")
        if not product.get("title") or len(product["title"]) > TITLE_LIMIT:
            return _refusal(400, 25002, "A user error has occurred. The title is missing or too long.")
        price = offer["pricingSummary"]["price"]
        listing_id = f"{110_000_000_000 + len(self.listings) + 1}"
        self.listings.append(
            PublishedListing(
                listing_id=listing_id,
                category_id=offer["categoryId"],
                title=product["title"],
                description=offer.get("listingDescription") or product.get("description", ""),
                price=(price["value"], price["currency"]),
                quantity=offer["availableQuantity"],
                photos=[self._images[image] for image in images],
                condition=item["condition"],
                condition_descriptors=descriptors,
            )
        )
        return httpx.Response(200, json={"listingId": listing_id, "warnings": []})


def _nothing_at(link: str) -> bytes:
    raise KeyError(link)


def _error(status: int, error: str, description: str) -> httpx.Response:
    return httpx.Response(status, json={"error": error, "error_description": description})


# How the APIs of a seller refuse a request: a list of errors, each with its number, its message, and the values it
# is about.
def _refusal(
    status: int, error_id: int, message: str, parameters: list[dict] | None = None, domain: str = "API_INVENTORY"
) -> httpx.Response:
    error = {"errorId": error_id, "domain": domain, "category": "REQUEST", "message": message}
    return httpx.Response(status, json={"errors": [{**error, "parameters": parameters or []}]})
