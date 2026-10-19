import pytest
from fastapi.testclient import TestClient

from cards_warehouse.main import create_app


# The first 16 hex digits of the SHA-256 of the key: what `sha256sum | cut -c1-16` prints.
def test_session_key_reports_the_fingerprint_of_the_key_given_at_start(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "a-session-key")
    client = TestClient(create_app())

    response = client.get("/session-key")

    assert response.status_code == 200
    assert response.json() == {"fingerprint": "049874913f0fec2a"}


# Fail at start rather than at the first login: Kubernetes then shows the error in the pod.
def test_app_refuses_to_start_without_a_session_key(monkeypatch):
    monkeypatch.delenv("SESSION_SECRET", raising=False)

    with pytest.raises(KeyError, match="SESSION_SECRET"):
        create_app()
