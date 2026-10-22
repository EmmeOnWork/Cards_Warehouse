"""The image built from app/ migrates a database, starts, answers its probes and reports the version it was built with.

Runs inside the dev container (make test), which drives the PC's Docker through its socket.
"""

import pytest

from tests.acceptance.containers import built_image, run_once, running_container
from tests.schema import head_revision, schema_revision

pytestmark = pytest.mark.acceptance


# What a release does: the init container migrates the database, then the app starts from the same image.
def test_image_migrates_an_empty_database_then_the_app_answers_ready(empty_database):
    with built_image() as image:
        migration = run_once(image, ["python", "-m", "cards_warehouse.migrate"], empty_database)

        assert migration.returncode == 0
        assert schema_revision(empty_database) == head_revision()
        with running_container(image, environment=empty_database) as client:
            assert client.get("/readyz").status_code == 200


# Ready only with a database: the readiness probe asks it.
def test_container_is_healthy_and_reports_the_version_passed_at_build(empty_database):
    with built_image(app_version="test-123") as image, running_container(image, environment=empty_database) as client:
        assert client.get("/livez").status_code == 200
        assert client.get("/readyz").status_code == 200
        assert client.get("/version").json() == {"version": "test-123"}


def test_container_built_without_a_version_reports_dev():
    with built_image() as image, running_container(image) as client:
        assert client.get("/version").json() == {"version": "dev"}


def test_container_reads_the_session_key_from_its_environment():
    with built_image() as image, running_container(image, session_secret="a-session-key") as client:
        assert client.get("/session-key").json() == {"fingerprint": "049874913f0fec2a"}
