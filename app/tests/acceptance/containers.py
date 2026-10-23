"""Build, pull and run images with the PC's Docker, from inside the dev container (make test)."""

import socket
import subprocess
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import psycopg
import pytest

from cards_warehouse.password import hash_password

APP_DIR = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_SECONDS = 30
# The PostgreSQL of the cluster (chart/values.yaml): the tests run against the same version.
POSTGRES_IMAGE = "postgres:18.6-trixie"
# The password of the tests. Its hash is computed when they run, as Manuel does with make password-hash:
# no hash is ever written in Git.
TEST_PASSWORD = "a-long-test-password"
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


@contextmanager
def built_image(app_version: str | None = None) -> Iterator[str]:
    tag = f"cards-warehouse:acceptance-{uuid.uuid4().hex[:8]}"
    command = ["docker", "build", "--tag", tag]
    if app_version is not None:
        command += ["--build-arg", f"APP_VERSION={app_version}"]
    subprocess.run([*command, str(APP_DIR)], check=True)
    try:
        yield tag
    finally:
        subprocess.run(["docker", "image", "rm", "--force", tag], check=False)


@contextmanager
def pulled_without_credentials(reference: str) -> Iterator[str]:
    # An empty client config holds no login: the registry sees an anonymous pull.
    with tempfile.TemporaryDirectory() as empty_config:
        subprocess.run(["docker", "--config", empty_config, "pull", reference], check=True)
    try:
        yield reference
    finally:
        subprocess.run(["docker", "image", "rm", "--force", reference], check=False)


@contextmanager
def running_container(
    image: str, session_secret: str = "test-session-key", environment: dict[str, str] | None = None
) -> Iterator[httpx.Client]:
    # The app refuses to start without a session key and a password hash, as in the cluster without its Secret.
    environment = {"SESSION_SECRET": session_secret, "PASSWORD_HASH": TEST_PASSWORD_HASH, **(environment or {})}
    container_id = _docker("run", "--detach", *_in_this_pod(), *_env_flags(environment), image)
    try:
        with httpx.Client(base_url="http://127.0.0.1:8000") as client:
            _wait_until_live(client)
            yield client
    finally:
        print(_docker("logs", container_id))
        subprocess.run(["docker", "rm", "--force", container_id], check=False)


def run_once(image: str, command: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess:
    """Run a command of the image to its end, as an init container does."""
    result = subprocess.run(
        ["docker", "run", "--rm", *_in_this_pod(), *_env_flags(environment), image, *command],
        capture_output=True,
        text=True,
    )
    print(result.stdout, result.stderr)
    return result


@contextmanager
def running_postgres() -> Iterator[dict[str, str]]:
    """A real PostgreSQL on our localhost, its data in memory. Yields the libpq variables that reach it."""
    environment = {
        "PGHOST": "127.0.0.1",
        "PGPORT": "5432",
        "PGUSER": "cards_warehouse",
        "PGPASSWORD": "test-database-password",
        "PGDATABASE": "cards_warehouse",
    }
    server = {
        "POSTGRES_USER": environment["PGUSER"],
        "POSTGRES_PASSWORD": environment["PGPASSWORD"],
        "POSTGRES_DB": environment["PGDATABASE"],
    }
    # As in the cluster (chart/templates/postgres.yaml): the image's postgres user, a read-only root
    # filesystem, and writable only the data, the server's socket and /tmp. Here all three in memory.
    restricted = ["--user", "999:999", "--read-only"]
    for writable in ("/var/lib/postgresql", "/var/run/postgresql", "/tmp"):
        restricted += ["--tmpfs", writable]
    container_id = _docker("run", "--detach", *_in_this_pod(), *restricted, *_env_flags(server), POSTGRES_IMAGE)
    try:
        _wait_until_accepting_connections(environment)
        yield environment
    finally:
        subprocess.run(["docker", "rm", "--force", container_id], check=False)


def conninfo(environment: dict[str, str]) -> str:
    """The connection string of the libpq variables, for a test that queries the database itself."""
    return psycopg.conninfo.make_conninfo(
        host=environment["PGHOST"],
        port=environment["PGPORT"],
        user=environment["PGUSER"],
        password=environment["PGPASSWORD"],
        dbname=environment["PGDATABASE"],
    )


def _in_this_pod() -> list[str]:
    # Join this test container's network namespace, like two containers in one Pod:
    # the container is then on our localhost, with no port published on the PC.
    return ["--network", f"container:{socket.gethostname()}"]


def _env_flags(environment: dict[str, str]) -> list[str]:
    return [flag for name, value in environment.items() for flag in ("--env", f"{name}={value}")]


def _docker(*args: str) -> str:
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout.strip()


def _wait_until_accepting_connections(environment: dict[str, str]) -> None:
    # The image first starts a server on its Unix socket only, to create the database, then restarts it on TCP.
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            psycopg.connect(conninfo(environment), connect_timeout=1).close()
            return
        except psycopg.OperationalError:
            time.sleep(0.5)
    pytest.fail(f"PostgreSQL not accepting connections after {STARTUP_TIMEOUT_SECONDS}s")


def _wait_until_live(client: httpx.Client) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            if client.get("/livez").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.5)
    pytest.fail(f"container not live after {STARTUP_TIMEOUT_SECONDS}s")
