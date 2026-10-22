from fastapi.testclient import TestClient

from cards_warehouse.main import create_app


def test_liveness_probe_answers_ok(client):
    response = client.get("/livez")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_probe_answers_ok_when_the_database_answers(empty_database, client):
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# While readiness fails the pod gets no traffic, but liveness stays ok: a restart would not bring the database back.
def test_readiness_probe_fails_while_the_database_is_unreachable(monkeypatch):
    # Nothing listens on port 1: the connection is refused at once.
    monkeypatch.setenv("PGHOST", "127.0.0.1")
    monkeypatch.setenv("PGPORT", "1")
    client = TestClient(create_app())

    assert client.get("/readyz").status_code == 503
    assert client.get("/livez").status_code == 200


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
