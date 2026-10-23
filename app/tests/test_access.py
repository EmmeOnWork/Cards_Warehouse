import pytest
from fastapi.testclient import TestClient
from httpx import Response

from cards_warehouse.main import create_app


def test_a_page_without_a_session_sends_to_the_login(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


# A program cannot follow a login page: it gets a plain refusal. Any path counts, not only the existing ones.
def test_an_api_without_a_session_answers_unauthorized(client):
    response = client.get("/api/anything")

    assert response.status_code == 401


def test_the_login_page_asks_for_the_password_without_a_session(client):
    response = client.get("/login")

    assert response.status_code == 200
    assert 'name="password"' in response.text


def test_the_right_password_opens_the_app(client, password):
    response = client.post("/login", data={"password": password}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert client.get("/").status_code == 200


def test_a_wrong_password_keeps_the_app_closed(client):
    response = client.post("/login", data={"password": "a-wrong-password"})

    assert response.status_code == 401
    assert 'name="password"' in response.text
    assert client.get("/", follow_redirects=False).status_code == 303


# Guessing slows down to 5 tries every 15 minutes: while locked, not even the right password is checked.
def test_five_wrong_passwords_in_a_row_lock_the_login_for_15_minutes(password):
    clock = FakeClock()
    client = TestClient(create_app(clock=clock))
    for _ in range(5):
        client.post("/login", data={"password": "a-wrong-password"})

    assert login(client, password).status_code == 429
    clock.now += 15 * 60 - 1
    assert login(client, password).status_code == 429
    clock.now += 1
    assert login(client, password).status_code == 303


# Typos spread over weeks never add up to a lock.
def test_the_right_password_clears_the_count_of_wrong_ones(client, password):
    for _ in range(4):
        login(client, "a-wrong-password")
    login(client, password)
    for _ in range(4):
        login(client, "a-wrong-password")

    assert login(client, password).status_code == 303


# HttpOnly: a script on the page cannot read the cookie. Lax: another site cannot post with it.
# After 30 days the browser drops it, and the app refuses it even if someone kept a copy.
def test_the_session_cookie_is_hidden_from_scripts_and_lasts_30_days(client, password):
    cookie = login(client, password).headers["set-cookie"].lower()

    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert f"max-age={30 * 24 * 60 * 60}" in cookie


def test_logging_out_closes_the_session(client, password):
    login(client, password)

    response = client.post("/logout", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert client.get("/", follow_redirects=False).status_code == 303


# Fail at start, as for the session key: Kubernetes then shows the error in the pod.
def test_app_refuses_to_start_without_the_password_hash(monkeypatch):
    monkeypatch.delenv("PASSWORD_HASH", raising=False)

    with pytest.raises(KeyError, match="PASSWORD_HASH"):
        create_app()


# The password itself pasted into Infisical, instead of the output of make password-hash.
def test_app_refuses_to_start_when_the_password_hash_is_not_a_hash(monkeypatch, password):
    monkeypatch.setenv("PASSWORD_HASH", password)

    with pytest.raises(ValueError, match="make password-hash"):
        create_app()


class FakeClock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def login(client: TestClient, password: str) -> Response:
    return client.post("/login", data={"password": password}, follow_redirects=False)
