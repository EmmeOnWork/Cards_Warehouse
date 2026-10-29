"""Setting up the seller's account for the listings the app publishes, from the PC: make ebay-setup. It takes the
shipping policy Manuel made on eBay's page, makes the others and the place the goods leave from, and gives the values
to put in Infisical.

Against the fake eBay, with no network.
"""

import pytest

from cards_warehouse import ebay, ebay_setup, exposure
from cards_warehouse.ebay_channel import EbayChannel, SellerSetup
from tests.fake_ebay import FakeEbay
from tests.test_access import FakeClock
from tests.test_ebay import connect_account
from tests.test_ebay_channel import BOX, a_photographed
from tests.test_exposure import channel_ids


def test_setting_up_the_seller_gives_the_values_to_put_in_infisical(monkeypatch):
    fake_ebay = FakeEbay(seller_set_up=False)
    shipping = fake_ebay.create_shipping_policy("Piego di libri tracciato")

    values = set_up(monkeypatch, fake_ebay)

    assert set(values) == {
        "EBAY_FULFILLMENT_POLICY_ID",
        "EBAY_PAYMENT_POLICY_ID",
        "EBAY_RETURN_POLICY_ID",
        "EBAY_LOCATION_KEY",
    }
    assert values["EBAY_FULFILLMENT_POLICY_ID"] == shipping
    assert fake_ebay.location(values["EBAY_LOCATION_KEY"]) == {"postalCode": "20121", "city": "Milano", "country": "IT"}


# Put in Infisical as they are, next to those of make ebay-connect, they let the app publish.
def test_the_values_put_in_infisical_let_the_app_publish_on_ebay(connection, photos, monkeypatch):
    fake_ebay = FakeEbay(seller_set_up=False, photos=photos.open)
    fake_ebay.create_shipping_policy("Piego di libri tracciato")
    for name, value in set_up(monkeypatch, fake_ebay).items():
        monkeypatch.setenv(name, value)
    channel = EbayChannel(
        ebay.account_from_environment(fake_ebay.http(), FakeClock()), SellerSetup.from_environment(), photos
    )
    box = a_photographed(connection, photos, BOX)

    exposure.put_on_sale(connection, box, channel_ids(connection, "eBay"), channel)

    assert len(fake_ebay.listings) == 1


# Run again, as with the real account in task 37 or after a value pasted wrong: what eBay has already is taken.
def test_setting_up_again_takes_what_ebay_has_and_makes_nothing_twice(monkeypatch):
    fake_ebay = FakeEbay(seller_set_up=False)
    fake_ebay.create_shipping_policy("Piego di libri tracciato")

    first = set_up(monkeypatch, fake_ebay)

    assert set_up(monkeypatch, fake_ebay) == first
    assert fake_ebay.policies == {"fulfillment": 1, "payment": 1, "return": 1}


# The shipping policy needs the code of a shipping service that only an older API of eBay lists: Manuel makes it on
# eBay's page of the policies, where he picks the service.
def test_without_a_shipping_policy_on_ebay_it_says_to_make_one_there_first(monkeypatch):
    with pytest.raises(ebay_setup.SetupFailed, match="no shipping policy.*make one"):
        set_up(monkeypatch, FakeEbay(seller_set_up=False))


def test_with_several_shipping_policies_manuel_chooses_the_one_for_the_app(monkeypatch):
    fake_ebay = FakeEbay(seller_set_up=False)
    fake_ebay.create_shipping_policy("Lettera")
    parcel = fake_ebay.create_shipping_policy("Pacco tracciato")
    offered = []

    def choose(policies: list[tuple[str, str]]) -> str:
        offered.extend(name for _, name in policies)
        return dict((name, policy_id) for policy_id, name in policies)["Pacco tracciato"]

    values = set_up(monkeypatch, fake_ebay, choose=choose)

    assert offered == ["Lettera", "Pacco tracciato"]
    assert values["EBAY_FULFILLMENT_POLICY_ID"] == parcel


def set_up(monkeypatch, fake_ebay: FakeEbay, choose=None) -> dict[str, str]:
    connect_account(monkeypatch)
    account = ebay.account_from_environment(fake_ebay.http(), FakeClock())
    return ebay_setup.values_for_infisical(account, postal_code="20121", city="Milano", choose=choose or _unasked)


def _unasked(policies: list[tuple[str, str]]) -> str:
    raise AssertionError(f"asked to choose among {policies}")
