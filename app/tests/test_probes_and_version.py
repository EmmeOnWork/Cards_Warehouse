from fastapi.testclient import TestClient

from cards_warehouse.main import create_app


def test_liveness_probe_answers_ok(client):
    response = client.get("/livez")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_probe_answers_ok(client):
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version_reports_the_value_given_at_build(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "1a2b3c4")
    client = TestClient(create_app())

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {"version": "1a2b3c4"}


def test_version_is_dev_when_no_value_was_given(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    client = TestClient(create_app())

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {"version": "dev"}
