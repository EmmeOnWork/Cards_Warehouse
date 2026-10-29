"""eBay as a channel the app acts on by itself, through eBay's APIs for sellers: the same operations as a manual
channel, done by the app.

A listing is published in four steps. Each photo goes to eBay's own servers (Media API): eBay downloads it at once
from the bucket's link, which lasts minutes, and the listing shows eBay's copy. Then the item (Inventory API), with
the texts, the condition and the photos; the offer, with the price, the copies and the seller's policies; and the
offer is published, which makes it a listing.
"""

import os
from dataclasses import dataclass
from decimal import Decimal

import httpx
from sqlalchemy import Connection

from cards_warehouse import items, listing_texts, photos
from cards_warehouse.ebay import Account, AuthorizationRefused, EbayUnavailable, RequestRefused
from cards_warehouse.exposure import Listing, PublishRefused
from cards_warehouse.items import Card, Condition, Item, Kind

MARKETPLACE = "EBAY_IT"
# The texts are in Italian: eBay refuses an item or an offer that does not say their language.
TEXTS_LANGUAGE = {"Content-Language": "it-IT"}
# eBay's leaf categories: CCG Individual Cards, and CCG Sealed Boxes for every sealed product, since its type is
# free text and the app cannot tell a box from a pack.
SINGLE_CARD_CATEGORY = "183454"
SEALED_CATEGORY = "261044"
# The descriptors of a single card, and their values, by eBay's numbers (getItemConditionPolicies of the Metadata
# API). Not graded: the state of the card, on eBay's four steps for card games, from Cardmarket's seven.
CARD_CONDITION = "40001"
CARD_CONDITIONS = {
    Condition.MINT: "400010",
    Condition.NEAR_MINT: "400010",
    # Lightly played (Excellent).
    Condition.EXCELLENT: "400015",
    Condition.GOOD: "400015",
    # Moderately played (Very good).
    Condition.LIGHT_PLAYED: "400016",
    Condition.PLAYED: "400016",
    # Heavily played (Poor).
    Condition.POOR: "400017",
}
# Graded: the grader, Other for one eBay does not list, and the grade, from 10 down in half points.
GRADER = "27501"
GRADERS = {
    "PSA": "275010",
    "BCCG": "275011",
    "BVG": "275012",
    "BGS": "275013",
    "CSG": "275014",
    "CGC": "275015",
    "SGC": "275016",
    "KSA": "275017",
    "GMA": "275018",
    "HGA": "275019",
    "ISA": "2750110",
    "PCA": "2750111",
    "GSG": "2750112",
    "PGS": "2750113",
    "MNT": "2750114",
    "TAG": "2750115",
    "RARE EDITION": "2750116",
    "RCG": "2750117",
    "PCG": "2750118",
    "ACE": "2750119",
    "CGA": "2750120",
    "TCG": "2750121",
    "ARK": "2750122",
}
OTHER_GRADER = "2750123"
GRADE = "27502"


@dataclass(frozen=True)
class SellerSetup:
    """What a listing needs of the seller's account: the policies for shipping, payment and returns on eBay Italy,
    and the place the goods leave from. make ebay-setup creates them, and prints the values for Infisical."""

    fulfillment_policy_id: str
    payment_policy_id: str
    return_policy_id: str
    location_key: str

    @classmethod
    def from_environment(cls) -> "SellerSetup | None":
        """None before make ebay-setup."""
        if "EBAY_LOCATION_KEY" not in os.environ:
            return None
        return cls(
            fulfillment_policy_id=os.environ["EBAY_FULFILLMENT_POLICY_ID"],
            payment_policy_id=os.environ["EBAY_PAYMENT_POLICY_ID"],
            return_policy_id=os.environ["EBAY_RETURN_POLICY_ID"],
            location_key=os.environ["EBAY_LOCATION_KEY"],
        )


class EbayChannel:
    def __init__(self, account: Account | None, setup: SellerSetup | None, store: photos.Store) -> None:
        self._account = account
        self._setup = setup
        self._store = store

    def publish(self, connection: Connection, listing: Listing) -> str:
        """The listing live on eBay: its link. PublishRefused, with why and what to do, when eBay cannot take it:
        what the app can tell before asking eBay is told before, so that no item is left half made there."""
        if self._account is None:
            raise PublishRefused("eBay non è collegato: collegalo dal PC con make ebay-connect, poi riprova.")
        if self._setup is None:
            raise PublishRefused(
                "Mancano le politiche di vendita su eBay: dal PC, make ebay-setup e i valori in Infisical, poi riprova."
            )
        category, condition = _category_and_condition(items.get(connection, listing.item_id))
        shown = photos.of_item(connection, self._store, listing.item_id)
        if not shown:
            raise PublishRefused("eBay vuole almeno una foto: aggiungila, poi riprova.")
        texts = listing_texts.of_item(connection, listing.item_id).texts
        try:
            return self._published(listing, texts, category, condition, [photo.link for photo in shown])
        except AuthorizationRefused:
            raise PublishRefused(
                "eBay non accetta più l'autorizzazione: ricollega l'account dal PC con make ebay-connect, poi riprova."
            ) from None
        except EbayUnavailable:
            raise PublishRefused("eBay non risponde: riprova più tardi.") from None
        except RequestRefused as refusal:
            raise PublishRefused(
                f"eBay rifiuta le chiavi dell'app ({refusal}): "
                "controlla EBAY_CLIENT_ID e EBAY_CLIENT_SECRET in Infisical, poi riprova."
            ) from None

    def _published(
        self, listing: Listing, texts: listing_texts.Texts, category: str, condition: dict, links: list[str]
    ) -> str:
        images = [self._hosted(link) for link in links]
        # One item on eBay for each listing of the app: a listing closed and opened again starts clean.
        sku = f"listing-{listing.id}"
        self._send(
            "PUT",
            self._account.api(f"/sell/inventory/v1/inventory_item/{sku}"),
            json={
                "availability": {"shipToLocationAvailability": {"quantity": listing.quantity}},
                **condition,
                "product": {"title": texts.title, "description": texts.description, "imageUrls": images},
            },
        )
        offer_id = self._offer(
            sku,
            {
                "categoryId": category,
                "availableQuantity": listing.quantity,
                "listingDescription": texts.description,
                "pricingSummary": {"price": {"value": _value(listing.price_cents), "currency": "EUR"}},
                "listingPolicies": {
                    "fulfillmentPolicyId": self._setup.fulfillment_policy_id,
                    "paymentPolicyId": self._setup.payment_policy_id,
                    "returnPolicyId": self._setup.return_policy_id,
                },
                "merchantLocationKey": self._setup.location_key,
            },
        )
        published = self._send("POST", self._account.api(f"/sell/inventory/v1/offer/{offer_id}/publish")).json()
        return self._account.listing_page(published["listingId"])

    def _offer(self, sku: str, offer: dict) -> str:
        """The item's offer, with these values: a new one, or the one eBay kept from an attempt it refused at the
        last step. eBay keeps one offer per item and marketplace, and refuses a second."""
        response = self._account.request(
            "POST",
            self._account.api("/sell/inventory/v1/offer"),
            headers=TEXTS_LANGUAGE,
            json={"sku": sku, "marketplaceId": MARKETPLACE, "format": "FIXED_PRICE", **offer},
        )
        kept = _kept_offer(response)
        if kept is None:
            return _checked(response).json()["offerId"]
        self._send("PUT", self._account.api(f"/sell/inventory/v1/offer/{kept}"), json=offer)
        return kept

    def _hosted(self, link: str) -> str:
        """eBay's copy of the photo at the link."""
        return self._send(
            "POST",
            self._account.media("/commerce/media/v1_beta/image/create_image_from_url"),
            json={"imageUrl": link},
        ).json()["imageUrl"]

    def _send(self, method: str, url: str, **options) -> httpx.Response:
        return _checked(self._account.request(method, url, headers=TEXTS_LANGUAGE, **options))


def _checked(response: httpx.Response) -> httpx.Response:
    if response.is_error:
        # eBay's own words, in English: they name what to fix, and no translation of the app could.
        reasons = " ".join(error["message"] for error in _errors(response))
        raise PublishRefused(f"eBay rifiuta l'annuncio: {reasons or response.status_code}")
    return response


def _kept_offer(response: httpx.Response) -> str | None:
    """The offer eBay already has for the item, when it refuses a new one for that."""
    if response.status_code != 400:
        return None
    for error in _errors(response):
        for parameter in error.get("parameters", []):
            if parameter["name"] == "offerId":
                return parameter["value"]
    return None


def _errors(response: httpx.Response) -> list[dict]:
    try:
        return response.json().get("errors", [])
    except ValueError:
        return []


def _category_and_condition(item: Item) -> tuple[str, dict]:
    """The category of the item on eBay, and its condition as the inventory item states it."""
    if item.kind == Kind.SEALED:
        return SEALED_CATEGORY, {"condition": "NEW"}
    if item.kind != Kind.SINGLE_CARD:
        raise PublishRefused("Su eBay l'app pubblica da sola solo carte singole e sealed.")
    # A card loaded before its fields existed has no condition: eBay wants one.
    if not isinstance(item.details, Card):
        raise PublishRefused("eBay vuole la condizione della carta: scrivila con Modifica, poi riprova.")
    state = item.details.state
    if isinstance(state, Condition):
        # USED_VERY_GOOD is how the Inventory API names eBay's condition 4000, not graded, for a single card.
        descriptors = [{"name": CARD_CONDITION, "values": [CARD_CONDITIONS[state]]}]
        return SINGLE_CARD_CATEGORY, {"condition": "USED_VERY_GOOD", "conditionDescriptors": descriptors}
    descriptors = [
        {"name": GRADER, "values": [GRADERS.get(state.grader.upper(), OTHER_GRADER)]},
        {"name": GRADE, "values": [grade_value(state.grade)]},
    ]
    # And LIKE_NEW is eBay's condition 2750, graded.
    return SINGLE_CARD_CATEGORY, {"condition": "LIKE_NEW", "conditionDescriptors": descriptors}


def grade_value(grade: Decimal) -> str:
    """The value of the grade descriptor: 10 is 275020, 9,5 is 275021, and so on down to 1, 2750218."""
    return f"27502{int((10 - grade) * 2)}"


def _value(cents: int) -> str:
    """A price as eBay writes it: 12000 is "120.00"."""
    return f"{cents // 100}.{cents % 100:02d}"
