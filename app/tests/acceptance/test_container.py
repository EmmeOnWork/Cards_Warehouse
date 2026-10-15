"""The image built from app/ starts, answers its probes and reports the version it was built with.

Runs inside the dev container (make test), which drives the PC's Docker through its socket.
"""

import pytest

from tests.acceptance.containers import built_image, running_container

pytestmark = pytest.mark.acceptance


def test_container_is_healthy_and_reports_the_version_passed_at_build():
    with built_image(app_version="test-123") as image, running_container(image) as client:
        assert client.get("/livez").status_code == 200
        assert client.get("/readyz").status_code == 200
        assert client.get("/version").json() == {"version": "test-123"}


def test_container_built_without_a_version_reports_dev():
    with built_image() as image, running_container(image) as client:
        assert client.get("/version").json() == {"version": "dev"}
