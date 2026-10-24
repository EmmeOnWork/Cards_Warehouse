import html

import pytest
from fastapi.testclient import TestClient

from cards_warehouse.main import create_app
from tests.test_access import FakeClock, login

NEW_PASSWORD = "a-new-test-password"


# Kept in the database: a new pod, which starts with the same hash from Infisical, still opens only with the new one.
def test_after_a_change_only_the_new_password_opens_the_app_even_after_a_restart(signed_in_client, password):
    page = change(signed_in_client, current=password, new=NEW_PASSWORD, again=NEW_PASSWORD)

    assert "Password cambiata" in page
    restarted = TestClient(create_app())
    assert login(restarted, password).status_code == 401
    assert login(restarted, NEW_PASSWORD).status_code == 303


# Someone with a phone left signed in cannot take the app: the change asks for the password it replaces.
def test_without_the_current_password_the_password_does_not_change(signed_in_client, password):
    page = change(signed_in_client, current="a-wrong-password", new=NEW_PASSWORD, again=NEW_PASSWORD)

    assert "La password attuale è sbagliata." in page
    assert login(TestClient(create_app()), password).status_code == 303


# Typed unseen: a slip in one of the two would lock Manuel out with a password nobody knows.
def test_two_different_new_passwords_change_nothing(signed_in_client, password):
    page = change(signed_in_client, current=password, new=NEW_PASSWORD, again="a-new-test-pasword")

    assert "Le due password nuove sono diverse." in page
    assert login(TestClient(create_app()), password).status_code == 303


# At least 8 characters, the floor NIST sets. The page asks the same, but a browser can be told to skip it.
def test_a_new_password_shorter_than_8_characters_changes_nothing(signed_in_client, password):
    page = change(signed_in_client, current=password, new="1234567", again="1234567")

    assert "La nuova password ha almeno 8 caratteri." in page
    assert login(TestClient(create_app()), password).status_code == 303


# One count for both pages: guessing here is as slow as at the login, and locks the login too.
@pytest.mark.usefixtures("database")
def test_five_wrong_current_passwords_lock_the_change_and_the_login_for_15_minutes(password):
    clock = FakeClock()
    client = TestClient(create_app(clock=clock))
    login(client, password)
    for _ in range(5):
        change(client, current="a-wrong-password", new=NEW_PASSWORD, again=NEW_PASSWORD)

    assert "Troppi tentativi sbagliati" in change(client, current=password, new=NEW_PASSWORD, again=NEW_PASSWORD)
    assert login(client, password).status_code == 429
    clock.now += 15 * 60
    assert login(client, password).status_code == 303


def change(client: TestClient, *, current: str, new: str, again: str) -> str:
    response = client.post("/password", data={"current": current, "new": new, "again": again})
    return html.unescape(response.text)
