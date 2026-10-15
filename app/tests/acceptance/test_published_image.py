"""The image the pipeline published for a commit is public and reports that commit as its version.

Runs as the last job of the pipeline after a push on main, or by hand:
    make verify-published SHA=<commit>
"""

import os

import pytest

from tests.acceptance.containers import pulled_without_credentials, running_container

pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.skipif("PUBLISHED_SHA" not in os.environ, reason="needs PUBLISHED_SHA, the commit to verify"),
]

REPOSITORY = "ghcr.io/emmeonwork/cards-warehouse"


def test_image_published_for_a_commit_is_public_and_reports_that_commit():
    sha = os.environ["PUBLISHED_SHA"]

    with pulled_without_credentials(f"{REPOSITORY}:{sha}") as image, running_container(image) as client:
        assert client.get("/version").json() == {"version": sha}
