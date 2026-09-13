"""Static contract checks for the v45 manual-acceptance entry points."""

import json
import subprocess
from pathlib import Path

import pytest

from scripts.abu_dhabi_v45_preflight import _walk_runtime_artifact


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_abu_dhabi_liveability_v45_demo.sh"
GUIDE = ROOT / (
    "docs/customer/abu_dhabi_liveability_site_validation/"
    "liveability_v45_manual_acceptance_script.md"
)
BUNDLE = ROOT / (
    "docs/customer/abu_dhabi_liveability_site_validation/abu_dhabi_current_artifact_bundle.json"
)


def test_v45_demo_script_and_guide_are_present_and_self_consistent() -> None:
    assert SCRIPT.is_file()
    assert GUIDE.is_file()
    assert "v45" in SCRIPT.read_text(encoding="utf-8")
    guide = GUIDE.read_text(encoding="utf-8")
    for marker in (
        "5443",
        "/ontology-model",
        "指标治理总览",
        "representative_scope",
        "source_rows_persisted",
        "release_gate=false",
    ):
        assert marker in guide


def test_v45_bundle_has_checksum_verified_runtime_roles() -> None:
    if not BUNDLE.is_file():
        pytest.skip("customer-bound v45 bundle is deployment-only and not in the public checkout")
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    assert bundle["status"] == "current_source_bound"
    assert bundle["source"]["source_id"] == 12
    assert bundle["source"]["allowed_schemas"] == ["public"]
    assert bundle["source"]["database_name"] == "liveability_data_20260730"
    for role in (
        "semantic",
        "ontology",
        "catalog",
        "plot_relationship_source_audit",
        "plot_detail_audited_relationships_publication_audit",
    ):
        descriptor = bundle["artifacts"][role]
        assert not Path(descriptor["path"]).is_absolute()
        assert len(descriptor["sha256"]) == 64


def test_v45_demo_script_passes_shell_syntax_check() -> None:
    completed = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_runtime_boundary_allows_negative_audit_markers_but_rejects_payloads() -> None:
    _walk_runtime_artifact(
        {
            "benchmark_inputs": {"gold_sql": False, "gold_result": None},
            "source_rows": [],
            "source_rows_persisted": False,
        }
    )
    try:
        _walk_runtime_artifact({"gold_sql": "SELECT 1"})
    except ValueError as exc:
        assert str(exc) == "runtime_artifact_contains_blocked_payload"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("runtime payload was not rejected")
