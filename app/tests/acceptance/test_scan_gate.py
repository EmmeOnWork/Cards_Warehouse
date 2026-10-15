"""The scan gate the pipeline runs before publishing: `trivy image <image>` from app/.

The policy (which severities block, and when) lives in app/trivy.yaml.
"""

import subprocess

import pytest

from tests.acceptance.containers import APP_DIR

pytestmark = pytest.mark.acceptance

# Python 3.12.0 on Debian bookworm, October 2023: fixes for its serious flaws have long been out.
OLD_BASE = "python:3.12.0-slim-bookworm"


def test_scan_gate_rejects_an_image_on_an_old_base():
    result = subprocess.run(["trivy", "image", OLD_BASE], cwd=APP_DIR, capture_output=True, text=True)
    print(result.stdout, result.stderr)

    assert result.returncode != 0
    assert "CRITICAL" in result.stdout
