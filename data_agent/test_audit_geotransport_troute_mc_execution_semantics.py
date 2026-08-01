from __future__ import annotations

import hashlib
import json

import pytest

from data_agent.uwm.geospatial_kernel_v2 import TrouteMuskingumCungeAdapter
from data_agent.test_geospatial_kernel_v2 import (
    _EquationConsistentMcKernel,
    _troute_mc_parameters,
)
from scripts.acquire_geotransport_troute_mc_execution_source import compile_plan
from scripts.audit_geotransport_troute_mc_execution_semantics import (
    DEFAULT_EXECUTION_MANIFEST,
    EXPECTED_EXECUTION_HASHES,
    T_ROUTE_COMMIT,
    compile_audit,
)


def test_execution_source_plan_is_fixed_bounded_and_outcome_free() -> None:
    plan = compile_plan()

    assert plan["mode"] == "plan"
    assert plan["commit"] == T_ROUTE_COMMIT
    assert len(plan["requests"]) == 3
    assert plan["request_boundary"]["planned_maximum_bytes"] <= plan[
        "request_boundary"
    ]["maximum_total_bytes"]
    assert plan["data_isolation"]["source_code_only"] is True
    assert plan["claim_boundary"]["execution_semantics_audited"] is False


def test_execution_source_manifest_freezes_exact_artifact_identity() -> None:
    manifest = json.loads(
        DEFAULT_EXECUTION_MANIFEST.read_text(encoding="utf-8")
    )

    assert manifest["commit"] == T_ROUTE_COMMIT
    assert {item["output_name"]: item["sha256"] for item in manifest["artifacts"]} == (
        EXPECTED_EXECUTION_HASHES
    )


def test_execution_semantics_audit_matches_adapter_and_stays_fail_closed() -> None:
    report = compile_audit()

    assert report["status"] == "fixed_commit_execution_semantics_audited"
    assert all(item["verified"] for item in report["findings"])
    assert report["adapter_conformance"] == {
        "open_loop_serial_chain_default_upstream_recursion_matches": True,
        "open_loop_serial_chain_short_ts_recursion_matches": True,
        "fortran_abi_matches": True,
        "lateral_flow_rate_semantics_match": True,
        "global_timestep_semantics_match": True,
        "float32_fortran_call_boundary_matches": True,
        "missing_full_python_driver_explains_response_matrix_failure": False,
    }
    assert report["non_equivalence_boundary"][
        "full_network_application_reproduced"
    ] is False
    assert report["numerical_initialization_audit"] == {
        "output_read_before_assignment_found": True,
        "stateless_call_order_invariance_required": True,
        "fixed_commit_kernel_numerically_well_defined": False,
        "generic_muskingum_cunge_method_impugned": False,
    }
    assert report["claim_boundary"][
        "fixed_commit_kernel_initialization_gate_passed"
    ] is False
    assert report["claim_boundary"]["t_route_mc_promotion_gate_passed"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False


def test_execution_semantics_report_freezes_source_findings() -> None:
    path = compile_audit.__globals__["DEFAULT_REPORT"]
    body = path.read_bytes()
    report = json.loads(body)

    assert hashlib.sha256(body).hexdigest() == (
        "d5858ca8e0ce1eafee04dc009f24f43003b584ab069b8a822f0dfd70efcc151d"
    )
    assert report["claim_boundary"]["adapter_default_chain_semantics_match"]
    assert not report["claim_boundary"][
        "fixed_commit_kernel_initialization_gate_passed"
    ]


def test_adapter_assume_short_timestep_matches_official_call_trace() -> None:
    kernel = _EquationConsistentMcKernel()
    adapter = TrouteMuskingumCungeAdapter(
        _troute_mc_parameters(),
        kernel,
        timestep_seconds=300.0,
        assume_short_timestep=True,
    )
    result = adapter.step(
        adapter.zero_state(provenance_id="short-ts:cold"),
        boundary_previous_m3s=5.0,
        boundary_current_m3s=10.0,
        lateral_inflow_m3s=(0.0, 0.0),
        provenance_id="short-ts:step",
    )

    assert kernel.calls[0]["qup"] == kernel.calls[0]["quc"] == 5.0
    assert kernel.calls[1]["qup"] == kernel.calls[1]["quc"] == 0.0
    assert result.next_state.discharge_m3s == pytest.approx((4.0, 0.0))
    assert result.assume_short_timestep is True
    assert result.as_dict()["assume_short_timestep"] is True


def test_adapter_rejects_non_boolean_short_timestep_switch() -> None:
    with pytest.raises(
        ValueError, match="t_route_mc_assume_short_timestep_must_be_boolean"
    ):
        TrouteMuskingumCungeAdapter(
            _troute_mc_parameters(),
            _EquationConsistentMcKernel(),
            timestep_seconds=300.0,
            assume_short_timestep=1,  # type: ignore[arg-type]
        )
