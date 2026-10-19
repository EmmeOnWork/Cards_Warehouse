import pytest
from fastapi.testclient import TestClient

from cards_warehouse.main import create_app


# The app refuses to start without a session key: every test gets one, and the tests about it set their own.
@pytest.fixture(autouse=True)
def session_secret(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-session-key")


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())
