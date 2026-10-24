"""Only the password opens the app built from app/, and logging out closes it again.

Runs inside the dev container (make test), which drives the PC's Docker through its socket.
"""

import pytest

from tests.acceptance.containers import built_image, running_container

pytestmark = pytest.mark.acceptance


# The container gets the hash of the tests' password, as the pod gets the one in Infisical, and a database at the
# last migration, where it looks for a password changed from the app.
def test_the_built_app_opens_only_with_its_password_and_closes_on_logout(password, database):
    with built_image() as image, running_container(image, environment=database) as client:
        assert client.get("/").headers["location"] == "/login"
        assert client.get("/api/anything").status_code == 401

        assert client.post("/login", data={"password": "a-wrong-password"}).status_code == 401
        assert client.get("/").status_code == 303

        assert client.post("/login", data={"password": password}).headers["location"] == "/"
        assert client.get("/").status_code == 200

        client.post("/logout")
        assert client.get("/").headers["location"] == "/login"
