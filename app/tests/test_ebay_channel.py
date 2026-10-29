"""eBay's adapter on its own: what eBay gets for each kind of item, and what the listing says when eBay refuses it.

Against the fake eBay, on a real PostgreSQL, through the exposure module.
"""

import io
from decimal import Decimal

import pytest

from cards_warehouse import ebay, exposure, items, photos, stock
from cards_warehouse.ebay_channel import EbayChannel, SellerSetup
from cards_warehouse.exposure import Status
from cards_warehouse.items import Card, Condition, Grading, Item, Kind
from tests.fake_ebay import LOCATION_KEY, PAYMENT_POLICY_ID, RETURN_POLICY_ID, FakeEbay
from tests.test_access import FakeClock
from tests.test_ebay import connect_account
from tests.test_ebay_publishing import set_up_selling
from tests.test_exposure import channel_ids
from tests.test_putting_on_sale import FRONT

BOX = Item(Kind.SEALED, "Pokémon", "Booster box Evoluzioni a Paldea", "it")


# Since 2023 eBay wants a single card graded or not graded, each with its descriptors: not graded, the state of the
# card on eBay's four steps; graded, the grader (Other for one eBay does not list) and the grade.
@pytest.mark.parametrize(
    ("state", "condition", "descriptors"),
    [
        (Condition.NEAR_MINT, "USED_VERY_GOOD", {"40001": ["400010"]}),
        (Condition.GOOD, "USED_VERY_GOOD", {"40001": ["400015"]}),
        (Condition.PLAYED, "USED_VERY_GOOD", {"40001": ["400016"]}),
        (Condition.POOR, "USED_VERY_GOOD", {"40001": ["400017"]}),
        (Grading("PSA", Decimal("9.5")), "LIKE_NEW", {"27501": ["275010"], "27502": ["275021"]}),
        (Grading("Ente di quartiere", Decimal(8)), "LIKE_NEW", {"27501": ["2750123"], "27502": ["275024"]}),
    ],
    ids=["near mint", "good", "played", "poor", "PSA 9,5", "unknown grader 8"],
)
def test_a_single_card_goes_among_the_single_cards_graded_or_not_with_its_state(
    connection, photos, monkeypatch, state, condition, descriptors
):
    fake_ebay = FakeEbay(photos=photos.open)
    card = a_photographed(connection, photos, Item(Kind.SINGLE_CARD, "Pokémon", "Mew ex", "it", details=Card(state)))

    exposure.put_on_sale(
        connection, card, channel_ids(connection, "eBay"), ebay_channel(monkeypatch, fake_ebay, photos)
    )

    [published] = fake_ebay.listings
    assert (published.category_id, published.condition, published.condition_descriptors) == (
        "183454",
        condition,
        descriptors,
    )


# Said before eBay is asked anything: no item is left half made on eBay.
def test_without_a_photo_the_listing_stays_to_publish_with_the_reason_and_ebay_gets_nothing(
    connection, photos, monkeypatch
):
    fake_ebay = FakeEbay(photos=photos.open)
    box = items.add(connection, BOX)
    stock.load(connection, box, quantity=1, unit_cost_cents=10000)

    exposure.put_on_sale(connection, box, channel_ids(connection, "eBay"), ebay_channel(monkeypatch, fake_ebay, photos))

    [listing] = exposure.of_item(connection, box)
    assert (listing.status, listing.problem) == (
        Status.TO_PUBLISH,
        "eBay vuole almeno una foto: aggiungila, poi riprova.",
    )
    assert fake_ebay.requests_to_sell == 0


def test_a_refused_listing_asked_again_once_the_reason_is_gone_is_published(connection, photos, monkeypatch):
    fake_ebay = FakeEbay(photos=photos.open)
    channel = ebay_channel(monkeypatch, fake_ebay, photos)
    box = items.add(connection, BOX)
    stock.load(connection, box, quantity=1, unit_cost_cents=10000)
    exposure.put_on_sale(connection, box, channel_ids(connection, "eBay"), channel)
    add_photo(connection, photos, box)
    [refused] = exposure.of_item(connection, box)

    exposure.publish_again(connection, refused.id, channel)

    [listing] = exposure.of_item(connection, box)
    [published] = fake_ebay.listings
    assert (listing.status, listing.link, listing.problem) == (
        Status.ACTIVE,
        f"https://sandbox.ebay.com/itm/{published.listing_id}",
        None,
    )


# Refused at the last step, the offer stays on eBay: asked again, after the policy is fixed in Infisical and the pod
# started with it, the app takes up that offer with the new values instead of making a second one.
def test_a_listing_refused_at_the_last_step_is_published_on_a_retry_with_the_offer_ebay_kept(
    connection, photos, monkeypatch
):
    fake_ebay = FakeEbay(photos=photos.open)
    connect_account(monkeypatch)
    wrong_policy = EbayChannel(
        ebay.account_from_environment(fake_ebay.http(), FakeClock()),
        SellerSetup(*_policies_with("6299999999")),
        photos,
    )
    box = a_photographed(connection, photos, BOX)
    exposure.put_on_sale(connection, box, channel_ids(connection, "eBay"), wrong_policy)
    [refused] = exposure.of_item(connection, box)

    exposure.publish_again(connection, refused.id, ebay_channel(monkeypatch, fake_ebay, photos))

    [listing] = exposure.of_item(connection, box)
    assert listing.status == Status.ACTIVE
    assert len(fake_ebay.listings) == 1
    assert fake_ebay.offers == 1


def _policies_with(fulfillment_policy_id: str) -> tuple[str, str, str, str]:
    return fulfillment_policy_id, PAYMENT_POLICY_ID, RETURN_POLICY_ID, LOCATION_KEY


# What goes wrong, set up on top of an account connected and a seller set up.
TROUBLES = {
    # A policy of another account, or deleted on eBay: eBay's own reason, as it gives it.
    "refused": lambda monkeypatch, fake_ebay: monkeypatch.setenv("EBAY_FULFILLMENT_POLICY_ID", "6299999999"),
    "unreachable": lambda monkeypatch, fake_ebay: fake_ebay.fail("unreachable"),
    "broken": lambda monkeypatch, fake_ebay: fake_ebay.fail("broken"),
    "revoked": lambda monkeypatch, fake_ebay: fake_ebay.revoke(),
    "wrong keys": lambda monkeypatch, fake_ebay: monkeypatch.setenv("EBAY_CLIENT_SECRET", "a-mistyped-secret"),
    "not connected": lambda monkeypatch, fake_ebay: monkeypatch.delenv("EBAY_REFRESH_TOKEN"),
    "not set up": lambda monkeypatch, fake_ebay: monkeypatch.delenv("EBAY_LOCATION_KEY"),
}


@pytest.mark.parametrize(
    ("trouble", "reason"),
    [
        ("refused", "eBay rifiuta l'annuncio: Please add at least one valid shipping service option to your listing."),
        ("unreachable", "eBay non risponde: riprova più tardi."),
        ("broken", "eBay non risponde: riprova più tardi."),
        (
            "revoked",
            "eBay non accetta più l'autorizzazione: ricollega l'account dal PC con make ebay-connect, poi riprova.",
        ),
        (
            "wrong keys",
            "eBay rifiuta le chiavi dell'app (invalid_client): "
            "controlla EBAY_CLIENT_ID e EBAY_CLIENT_SECRET in Infisical, poi riprova.",
        ),
        ("not connected", "eBay non è collegato: collegalo dal PC con make ebay-connect, poi riprova."),
        (
            "not set up",
            "Mancano le politiche di vendita su eBay: dal PC, make ebay-setup e i valori in Infisical, poi riprova.",
        ),
    ],
)
def test_when_ebay_cannot_publish_the_listing_says_why_and_what_to_do(connection, photos, monkeypatch, trouble, reason):
    fake_ebay = FakeEbay(photos=photos.open)
    connect_account(monkeypatch)
    set_up_selling(monkeypatch)
    TROUBLES[trouble](monkeypatch, fake_ebay)
    account = ebay.account_from_environment(fake_ebay.http(), FakeClock())
    channel = EbayChannel(account, SellerSetup.from_environment(), photos)
    box = a_photographed(connection, photos, BOX)

    exposure.put_on_sale(connection, box, channel_ids(connection, "eBay"), channel)

    [listing] = exposure.of_item(connection, box)
    assert (listing.status, listing.problem) == (Status.TO_PUBLISH, reason)


# Only single cards and sealed products go on eBay by themselves: a magazine, or the bulk, has no category nor
# condition of its own there yet. And a card loaded before its fields existed has no condition, which eBay wants.
@pytest.mark.parametrize(
    ("item", "reason"),
    [
        (
            Item(Kind.MAGAZINE, "Pokémon", "Pokémon Mania 12", "it"),
            "Su eBay l'app pubblica da sola solo carte singole e sealed.",
        ),
        (
            Item(Kind.SINGLE_CARD, "Pokémon", "Mew ex", "it"),
            "eBay vuole la condizione della carta: scrivila con Modifica, poi riprova.",
        ),
    ],
    ids=["magazine", "card without condition"],
)
def test_an_item_the_app_cannot_describe_to_ebay_is_not_published_and_the_listing_says_why(
    connection, photos, monkeypatch, item, reason
):
    fake_ebay = FakeEbay(photos=photos.open)
    item_id = a_photographed(connection, photos, item)

    exposure.put_on_sale(
        connection, item_id, channel_ids(connection, "eBay"), ebay_channel(monkeypatch, fake_ebay, photos)
    )

    [listing] = exposure.of_item(connection, item_id)
    assert listing.problem == reason
    assert fake_ebay.requests_to_sell == 0


def ebay_channel(monkeypatch, fake_ebay: FakeEbay, store) -> EbayChannel:
    """eBay's adapter with the account connected and the seller set up, as after make ebay-connect and ebay-setup."""
    connect_account(monkeypatch)
    set_up_selling(monkeypatch)
    account = ebay.account_from_environment(fake_ebay.http(), FakeClock())
    return EbayChannel(account, SellerSetup.from_environment(), store)


def a_photographed(connection, store, item: Item, copies: int = 1) -> int:
    """The item with one copy at 100,00 € and a photo: eBay refuses a listing without one."""
    item_id = items.add(connection, item)
    stock.load(connection, item_id, quantity=copies, unit_cost_cents=10000)
    add_photo(connection, store, item_id)
    return item_id


def add_photo(connection, store, item_id: int) -> None:
    photos.attach(connection, store, item_id, io.BytesIO(FRONT), "image/jpeg")
