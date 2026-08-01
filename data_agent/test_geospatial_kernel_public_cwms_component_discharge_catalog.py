from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_cwms_component_discharge_catalog as evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _ledger() -> evidence.PublicCWMSComponentDischargeCatalogLedger:
    return evidence.compile_public_cwms_component_discharge_catalog()


def test_stage38_binds_the_approved_catalog_response_exactly():
    ledger = _ledger()

    assert ledger.raw_catalog_artifact == {
        "path": evidence.RAW_CATALOG_PATH,
        "sha256": evidence.EXPECTED_RAW_SHA256,
        "size_bytes": 62_337,
    }
    assert len(ledger.acquisition_manifest_artifact["sha256"]) == 64


def test_stage38_acquisition_manifest_preserves_the_approved_boundary():
    manifest = json.loads((REPO_ROOT / evidence.ACQUISITION_MANIFEST_PATH).read_bytes())

    assert manifest["actual_request_count"] == 1
    assert manifest["actual_attempt_count"] == 1
    assert manifest["actual_download_bytes"] == 62_337
    assert manifest["approved_request_boundary"]["exact_url"] == (evidence.CATALOG_URL)
    assert manifest["approved_request_boundary"]["timeseries_values_requested"] is False
    assert manifest["approved_request_boundary"]["workspace_or_private_data_sent"] is False


def test_stage38_reproduces_and_binds_stage37_negative_evidence():
    ledger = _ledger()

    assert ledger.stage37_ledger_artifact["sha256"] == (evidence.EXPECTED_STAGE37_LEDGER_SHA256)
    assert ledger.stage37_gates_artifact["sha256"] == (evidence.EXPECTED_STAGE37_GATES_SHA256)
    assert ledger.as_dict()["decision"]["stage37_negative_result_preserved"] is True


def test_stage38_admits_only_four_component_source_identities():
    report = _ledger().as_dict()
    decision = report["decision"]

    assert decision["catalog_checkpoint_admitted"] is True
    assert decision["component_discharge_source_identity_count"] == 4
    assert decision["component_discharge_source_identities_admitted"] is True
    assert decision["component_values_acquisition_admitted"] is False
    assert decision["coverage_continuity_admitted"] is False


def test_stage38_rejects_command_action_causal_and_runtime_promotion():
    decision = _ledger().as_dict()["decision"]

    assert decision["gate_commands_admitted"] is False
    assert decision["human_actions_admitted"] is False
    assert decision["causal_interventions_admitted"] is False
    assert decision["runtime_operators_admitted"] is False
    assert decision["separate_bounded_value_acquisition_plan_required"] is True


def test_stage38_public_typed_refusals_fail_closed():
    ledger = _ledger()
    calls = (
        (ledger.require_historical_values, "historical_values"),
        (ledger.require_continuous_coverage, "continuous_coverage"),
        (ledger.require_gate_command, "gate_command"),
        (ledger.require_human_action, "human_action"),
        (ledger.require_causal_intervention, "causal_intervention"),
        (ledger.promote_to_runtime_operator, "runtime_operator_unadmitted"),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()


def test_stage38_provenance_is_content_addressed():
    ledger = _ledger()

    assert ledger.provenance_id.startswith("center-hill-cwms-component-discharge-catalog:")
    assert len(ledger.provenance_id.rsplit(":", 1)[1]) == 64


def test_compiled_stage38_report_passes_with_identity_only_admission():
    from scripts import (
        compile_geotransport_stage38_cwms_component_discharge_catalog_gates as gates,
    )

    report = gates.compile_report(ledger=_ledger())

    assert report["status"] == gates.STATUS
    assert len(report["gates"]) == 34
    assert sum(report["gates"].values()) == 34
    assert report["all_gates_passed"] is True
    assert report["decision"]["component_discharge_source_identities_admitted"] is True
    assert report["decision"]["component_values_acquisition_admitted"] is False
