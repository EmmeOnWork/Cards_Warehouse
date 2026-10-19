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
import pytest

APP_DIR = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_SECONDS = 30


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
def running_container(image: str, session_secret: str = "test-session-key") -> Iterator[httpx.Client]:
    # Join this test container's network namespace, like two containers in one Pod:
    # the app is then on our localhost, with no port published on the PC.
    test_container = socket.gethostname()
    # The app refuses to start without a session key, as in the cluster without its Secret.
    environment = ["--env", f"SESSION_SECRET={session_secret}"]
    container_id = _docker("run", "--detach", "--network", f"container:{test_container}", *environment, image)
    try:
        with httpx.Client(base_url="http://127.0.0.1:8000") as client:
            _wait_until_live(client)
            yield client
    finally:
        print(_docker("logs", container_id))
        subprocess.run(["docker", "rm", "--force", container_id], check=False)


def _docker(*args: str) -> str:
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout.strip()


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
