import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from cards_warehouse.main import create_app
from tests.acceptance.containers import conninfo, running_postgres


# The app refuses to start without a session key: every test gets one, and the tests about it set their own.
@pytest.fixture(autouse=True)
def session_secret(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-session-key")


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


# One real PostgreSQL for the whole run, as in the cluster: never a fake. It starts with the first test that needs it.
@pytest.fixture(scope="session")
def postgres() -> Iterator[dict[str, str]]:
    with running_postgres() as environment:
        yield environment


# A new database with nothing in it. The code under test reaches it through the libpq variables, as in the cluster.
@pytest.fixture
def empty_database(postgres, monkeypatch) -> dict[str, str]:
    name = f"test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(conninfo(postgres), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    environment = {**postgres, "PGDATABASE": name}
    for variable, value in environment.items():
        monkeypatch.setenv(variable, value)
    return environment
