from __future__ import annotations

import hashlib
import json

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    CtypesInitializedDiagnosticTrouteMuskingumCungeKernel,
)
from scripts.build_geotransport_troute_mc_initialized_diagnostic_runtime import (
    DEFAULT_OUTPUT as INITIALIZED_OUTPUT,
    EXPECTED_CORE_SOURCE_SHA256,
    derive_initialized_source,
)
from scripts.build_geotransport_troute_mc_runtime import DEFAULT_OUTPUT


def test_initialized_diagnostic_derivation_is_exact_and_leaves_official_source() -> None:
    source_path = (
        DEFAULT_OUTPUT.parent
        / "t_route_mc_source_audit/raw/MCsingleSegStime_f2py_NOLOOP.f90"
    )
    body = source_path.read_bytes()
    derived, changes = derive_initialized_source(body.decode("utf-8"))

    assert hashlib.sha256(body).hexdigest() == EXPECTED_CORE_SOURCE_SHA256
    assert len(changes) == 2
    assert "qdc = 0.0_prec" in derived
    assert "Qj_0 = 0.0_prec" in derived
    assert "intent(inout) :: Qj, C1, C2, C3, C4" in derived
    assert "intent(out) :: Qj, C1, C2, C3, C4, X" not in derived


def test_initialized_diagnostic_loader_rejects_official_manifest() -> None:
    with pytest.raises(
        ValueError, match="t_route_mc_initialized_diagnostic_manifest_invalid"
    ):
        CtypesInitializedDiagnosticTrouteMuskingumCungeKernel(
            DEFAULT_OUTPUT / "build_manifest.json"
        )


def test_initialized_diagnostic_runtime_artifacts_are_frozen_and_nonofficial() -> None:
    manifest_path = INITIALIZED_OUTPUT / "build_manifest.json"
    body = manifest_path.read_bytes()
    manifest = json.loads(body)

    assert hashlib.sha256(body).hexdigest() == (
        "5dc6cba8e1260db25499791e8dc5282f5705c72b0500f3e32aec8ec7c9988c9f"
    )
    assert manifest["official_core_source"]["sha256"] == (
        EXPECTED_CORE_SOURCE_SHA256
    )
    assert manifest["derived_core_source"]["sha256"] == (
        "90a7fd29088916174ba4198c00a88d171906676562245a6f2e95fb2236606e80"
    )
    assert manifest["library_artifact"]["sha256"] == (
        "42589a475030bada760648385fcf7d2afcb23bef19046756ce9c89c57a516052"
    )
    assert manifest["official_source_unmodified"] is False
    assert manifest["derived_diagnostic_only"] is True
    assert manifest["claim_boundary"]["professional_baseline_eligible"] is False


def test_initialized_diagnostic_matrix_separates_invariance_from_response_failure() -> None:
    path = (
        INITIALIZED_OUTPUT.parents[2]
        / "benchmarks/geotransport_v0_1/"
        "t_route_mc_initialized_diagnostic_response_matrix.json"
    )
    body = path.read_bytes()
    report = json.loads(body)

    assert hashlib.sha256(body).hexdigest() == (
        "83d5ebeaada13505d1d51902903d8d79203e3f3dc243b366b3563b0930781447"
    )
    assert len(report["cases"]) == 27
    assert report["cold_process_trace_invariance"]["passed"] is True
    assert set(
        report["cold_process_trace_invariance"][
            "metric_differences_mc_only_minus_interleaved"
        ].values()
    ) == {0.0}
    assert report["matrix_summary"]["outlet_negative_lobe_case_count"] == 24
    assert report["matrix_summary"]["timestep_stability"]["passed_count"] == 26
    assert report["gates"]["all_diagnostic_gates_passed"] is False
    assert report["claim_boundary"]["official_runtime_replaced"] is False
