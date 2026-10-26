import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import Connection

from cards_warehouse.database import create_database_engine
from cards_warehouse.main import create_app
from cards_warehouse.migrate import migrate
from tests.acceptance.containers import TEST_PASSWORD, TEST_PASSWORD_HASH, conninfo, running_postgres
from tests.fake_photos import FakePhotoStore


# The app refuses to start without a session key: every test gets one, and the tests about it set their own.
@pytest.fixture(autouse=True)
def session_secret(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-session-key")


# Likewise for the hash of the password, which in the cluster comes from Infisical.
@pytest.fixture(autouse=True)
def password_hash(monkeypatch):
    monkeypatch.setenv("PASSWORD_HASH", TEST_PASSWORD_HASH)


# Likewise for the photos bucket, which the chart names. A test that builds its own app gets the real one,
# which asks AWS nothing until a photo is added or shown.
@pytest.fixture(autouse=True)
def photos_bucket(monkeypatch):
    monkeypatch.setenv("PHOTOS_BUCKET", "test-photos")
    monkeypatch.setenv("PHOTOS_REGION", "eu-north-1")


@pytest.fixture
def password() -> str:
    return TEST_PASSWORD


# The photos bucket, in memory: no test calls AWS.
@pytest.fixture
def photos() -> FakePhotoStore:
    return FakePhotoStore()


@pytest.fixture
def client(photos) -> TestClient:
    return TestClient(create_app(photo_store=photos))


# One real PostgreSQL for the whole run, as in the cluster: never a fake. It starts with the first test that needs it.
@pytest.fixture(scope="session")
def postgres() -> Iterator[dict[str, str]]:
    with running_postgres() as environment:
        yield environment


# A new database with nothing in it. The code under test reaches it through the libpq variables, as in the cluster.
# Dropped after the test with the connections left open to it: every engine keeps its own in a pool, and a run of
# a few hundred tests would hold more than the 100 that PostgreSQL accepts.
@pytest.fixture
def empty_database(postgres, monkeypatch) -> Iterator[dict[str, str]]:
    name = f"test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(conninfo(postgres), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    environment = {**postgres, "PGDATABASE": name}
    for variable, value in environment.items():
        monkeypatch.setenv(variable, value)
    yield environment
    with psycopg.connect(conninfo(postgres), autocommit=True) as connection:
        connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


# A new database at the last migration, as a release leaves it.
@pytest.fixture
def database(empty_database) -> dict[str, str]:
    migrate()
    return empty_database


# A connection to that database, for the tests of a module. Nothing is committed: the database goes with the test.
@pytest.fixture
def connection(database) -> Iterator[Connection]:
    with create_database_engine().connect() as connection:
        yield connection


# Manuel, logged in, on a database of his own.
@pytest.fixture
def signed_in_client(database, client, password) -> TestClient:
    client.post("/login", data={"password": password})
    return client
