"""The image built from app/ starts, answers its probes and reports the version it was built with.

Runs inside the dev container (make test), which drives the PC's Docker through its socket.
"""

import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.acceptance

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
def running_container(image: str) -> Iterator[httpx.Client]:
    # Join this test container's network namespace, like two containers in one Pod:
    # the app is then on our localhost, with no port published on the PC.
    test_container = socket.gethostname()
    container_id = _docker("run", "--detach", "--network", f"container:{test_container}", image)
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


def test_container_is_healthy_and_reports_the_version_passed_at_build():
    with built_image(app_version="test-123") as image, running_container(image) as client:
        assert client.get("/livez").status_code == 200
        assert client.get("/readyz").status_code == 200
        assert client.get("/version").json() == {"version": "test-123"}


def test_container_built_without_a_version_reports_dev():
    with built_image() as image, running_container(image) as client:
        assert client.get("/version").json() == {"version": "dev"}
