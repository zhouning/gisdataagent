"""Tests for the TWM validation-bundle smoke entrypoint."""

import subprocess
from pathlib import Path


SCRIPT = Path("scripts/smoke_twm_validation_bundle.sh")


def test_twm_validation_bundle_smoke_script_is_valid_bash():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_twm_validation_bundle_smoke_script_exposes_inner_network_controls():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "TWM_PRODUCTION_OBSERVED_HISTORY" in text
    assert "TWM_PRODUCTION_SCALE_PROFILE" in text
    assert "TWM_REQUIRE_PRODUCTION_READINESS" in text
    assert "TWM_FAIL_ON_BLOCKED" in text
    assert "TWM_REQUIRE_SCCA_PASS" in text
    assert "--production-observed-history" in text
    assert "--production-scale-profile" in text
    assert "--require-production-readiness" in text
    assert "--fail-on-blocked" in text
    assert ".venv/bin/python" in text
