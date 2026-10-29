"""Sets up Manuel's eBay account for the listings the app publishes, from the PC: make ebay-setup.

A listing needs the seller's policies for shipping, payment and returns on eBay Italy, and the place the goods leave
from. The shipping policy Manuel makes on eBay's page of the policies, where he picks the shipping service: the code
of a service comes only from an older API of eBay. The rest is made here, when eBay does not have it already. What
comes out is printed once, for Infisical, as with make ebay-connect.
"""

import getpass
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from cards_warehouse.ebay import ENVIRONMENT_NAMES, Account, AuthorizationRefused, EbayUnavailable, RequestRefused
from cards_warehouse.ebay_channel import MARKETPLACE

# The place the goods leave from, by the name the offers give it.
LOCATION_KEY = "magazzino"
# Every category but vehicles: the policies hold for any item.
CATEGORY_TYPES = [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}]
# Made only when the account has none of their kind. A private seller need not accept returns.
NEW_POLICIES = {
    "payment": {"name": "Pagamento (app)", "immediatePay": True},
    "return": {"name": "Nessun reso (app)", "returnsAccepted": False},
}


class SetupFailed(Exception):
    """The values could not be made: the message says why, and what to do."""


def values_for_infisical(
    account: Account, *, postal_code: str, city: str, choose: Callable[[list[tuple[str, str]]], str]
) -> dict[str, str]:
    """The seller's policies on eBay Italy and the place the goods leave from. `choose` picks the shipping policy
    among several, given each one's id and name."""
    try:
        _opt_in(account)
        shipping = _policies(account, "fulfillment")
        if not shipping:
            raise SetupFailed(
                "The account has no shipping policy on eBay Italy: make one on eBay's page of the business policies, "
                "then run make ebay-setup again."
            )
        values = {
            "EBAY_FULFILLMENT_POLICY_ID": shipping[0][0] if len(shipping) == 1 else choose(shipping),
            "EBAY_PAYMENT_POLICY_ID": _policy(account, "payment"),
            "EBAY_RETURN_POLICY_ID": _policy(account, "return"),
            "EBAY_LOCATION_KEY": _location(account, postal_code, city),
        }
    except AuthorizationRefused:
        raise SetupFailed("eBay no longer accepts the authorization: run make ebay-connect first.") from None
    except EbayUnavailable:
        raise SetupFailed("eBay does not answer: try again later.") from None
    except RequestRefused as refusal:
        raise SetupFailed(f"eBay refused the keys ({refusal}): check the client ID and secret.") from None
    return values


# The business policies are a program the seller joins once.
def _opt_in(account: Account) -> None:
    joined = _checked(account.request("GET", account.api("/sell/account/v1/program/get_opted_in_programs")))
    if not any(program["programType"] == "SELLING_POLICY_MANAGEMENT" for program in joined.json()["programs"]):
        _checked(
            account.request(
                "POST",
                account.api("/sell/account/v1/program/opt_in"),
                json={"programType": "SELLING_POLICY_MANAGEMENT"},
            )
        )


def _policies(account: Account, kind: str) -> list[tuple[str, str]]:
    """The id and name of each policy of the kind the account has on eBay Italy."""
    answer = _checked(
        account.request("GET", account.api(f"/sell/account/v1/{kind}_policy"), params={"marketplace_id": MARKETPLACE})
    ).json()
    return [(policy[f"{kind}PolicyId"], policy["name"]) for policy in answer.get(f"{kind}Policies", [])]


def _policy(account: Account, kind: str) -> str:
    """The first policy of the kind the account has, or a new one."""
    if existing := _policies(account, kind):
        return existing[0][0]
    made = account.request(
        "POST",
        account.api(f"/sell/account/v1/{kind}_policy"),
        json={**NEW_POLICIES[kind], "marketplaceId": MARKETPLACE, "categoryTypes": CATEGORY_TYPES},
    )
    return _checked(made).json()[f"{kind}PolicyId"]


def _location(account: Account, postal_code: str, city: str) -> str:
    """Made once: eBay answers 409 when the account has it already."""
    made = account.request(
        "POST",
        account.api(f"/sell/inventory/v1/location/{LOCATION_KEY}"),
        json={
            "location": {"address": {"postalCode": postal_code, "city": city, "country": "IT"}},
            "locationTypes": ["WAREHOUSE"],
            "name": "Magazzino",
            "merchantLocationStatus": "ENABLED",
        },
    )
    if made.status_code != 409:
        _checked(made)
    return LOCATION_KEY


def _checked(response: httpx.Response) -> httpx.Response:
    if response.is_error:
        reasons = " ".join(error.get("message", "") for error in response.json().get("errors", []))
        raise SetupFailed(f"eBay refused the request ({response.status_code}): {reasons}")
    return response


def _choose_on_screen(policies: list[tuple[str, str]]) -> str:
    print("\nThe account has several shipping policies on eBay Italy. The one for the app's listings:")
    for number, (_, name) in enumerate(policies, start=1):
        print(f"  {number}. {name}")
    while True:
        answer = input(f"Number, 1 to {len(policies)}: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(policies):
            return policies[int(answer) - 1][0]


if __name__ == "__main__":
    environment = input("Environment, sandbox or production [sandbox]: ").strip() or "sandbox"
    if environment not in ENVIRONMENT_NAMES:
        sys.exit("The environment is sandbox or production.")
    # The values of Infisical, /app: the same make ebay-connect printed, or the keys of the portal. Not echoed.
    client_id = input("Client ID (EBAY_CLIENT_ID): ").strip()
    client_secret = getpass.getpass("Client secret (EBAY_CLIENT_SECRET): ").strip()
    refresh_token = getpass.getpass("Durable credential (EBAY_REFRESH_TOKEN): ").strip()
    # Shown to buyers as where the item ships from: the city and its postal code, not the street.
    postal_code = input("Postal code the goods leave from: ").strip()
    city = input("City: ").strip()
    with httpx.Client(timeout=30) as http:
        account = Account(
            environment=environment,
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            # Not shown here: the app's page shows it.
            authorization_expires=datetime.now(UTC),
            http=http,
            clock=time.monotonic,
        )
        try:
            values = values_for_infisical(account, postal_code=postal_code, city=city, choose=_choose_on_screen)
        except SetupFailed as failure:
            sys.exit(str(failure))
    print("\nPut these in Infisical, project cards-warehouse, environment prod, folder /app:\n")
    for name, value in values.items():
        print(f"{name}={value}")
