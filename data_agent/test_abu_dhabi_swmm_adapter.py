from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from data_agent.uwm.abu_dhabi_flood import (
    TraditionalSolverExecutionError,
    TraditionalSolverQualityPolicy,
    TraditionalSolverRunRequest,
    evaluate_swmm_quality,
    execute_swmm,
    parse_swmm_report,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SWMM_ROOT = REPOSITORY_ROOT / "external_models/swmm-5.2.4"
SWMM_EXECUTABLE = SWMM_ROOT / "build-local/bin/runswmm"
SWMM_INPUT = SWMM_ROOT / "validation/abu_dhabi_synthetic_storm.inp"
SWMM_REPORT = SWMM_ROOT / "validation/abu_dhabi_synthetic_storm.rpt"


def _report_text() -> str:
    if not SWMM_REPORT.is_file():
        pytest.skip("external SWMM validation report is not present in this checkout")
    return SWMM_REPORT.read_text(encoding="utf-8")


def _request(*, executable: Path = SWMM_EXECUTABLE) -> TraditionalSolverRunRequest:
    if not SWMM_INPUT.is_file():
        pytest.skip("external SWMM validation input is not present in this checkout")
    return TraditionalSolverRunRequest(
        run_id="abu-dhabi-swmm-5.2.4-synthetic-diagnostic",
        solver_id="epa_swmm",
        executable_path=executable,
        model_input_path=SWMM_INPUT,
        expected_solver_version="5.2.4",
        evidence_class="synthetic_fixture",
        calibration_status="not_calibrated",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def test_parse_swmm_report_extracts_required_hydraulic_evidence():
    parsed = parse_swmm_report(_report_text())

    assert parsed["solver"] == {
        "name": "EPA SWMM",
        "version_series": "5.2",
        "version": "5.2.4",
    }
    assert parsed["element_counts"] == {
        "rain_gages": 1,
        "subcatchments": 1,
        "nodes": 2,
        "links": 1,
        "pollutants": 0,
        "land_uses": 0,
    }
    assert parsed["analysis_options"] == {
        "flow_units": "CMS",
        "flow_routing_method": "KINWAVE",
    }
    assert parsed["runoff_quantity_continuity"]["total_precipitation"][
        "second"
    ] == pytest.approx(22.5)
    assert parsed["runoff_quantity_continuity"]["infiltration_loss"][
        "second"
    ] == pytest.approx(4.08)
    assert parsed["runoff_quantity_continuity"]["surface_runoff"][
        "second"
    ] == pytest.approx(18.194)
    assert parsed["runoff_quantity_continuity"][
        "continuity_error_percent"
    ] == pytest.approx(-0.067)
    assert parsed["flow_routing_continuity"][
        "continuity_error_percent"
    ] == pytest.approx(-0.039)
    assert parsed["stability"]["all_links_stable"] is True
    assert parsed["convergence"]["steps_not_converging_percent"] == 0.0
    assert parsed["node_flooding"]["detected"] is False


@pytest.mark.parametrize(
    ("mutated_report", "failed_check"),
    [
        (
            lambda text: text + "\n  ERROR 101: synthetic parser test\n",
            "report_contains_no_swmm_errors",
        ),
        (
            lambda text: text.replace("All links are stable.", "Link C1 is unstable."),
            "all_links_stable",
        ),
        (
            lambda text: text.replace(
                "Continuity Error (%) .....        -0.067",
                "Continuity Error (%) .....         5.000",
                1,
            ),
            "runoff_continuity_within_threshold",
        ),
    ],
)
def test_swmm_quality_gate_rejects_report_errors_instability_and_mass_error(
    mutated_report,
    failed_check: str,
):
    parsed = parse_swmm_report(mutated_report(_report_text()))
    quality = evaluate_swmm_quality(parsed, TraditionalSolverQualityPolicy())

    assert quality["passed"] is False
    assert failed_check in quality["failed_checks"]
    assert quality["admission_effect"] == "none_diagnostic_quality_only"


def test_synthetic_or_proxy_request_cannot_claim_calibration_or_admission():
    with pytest.raises(
        ValueError, match="proxy_or_synthetic_solver_input_cannot_be_calibrated"
    ):
        TraditionalSolverRunRequest(
            run_id="invalid-calibrated-fixture",
            solver_id="epa_swmm",
            executable_path=SWMM_EXECUTABLE,
            model_input_path=SWMM_INPUT,
            expected_solver_version="5.2.4",
            evidence_class="synthetic_fixture",
            calibration_status="independently_validated",
        )

    with pytest.raises(ValueError, match="traditional_solver_adapter_cannot_grant_admission"):
        TraditionalSolverRunRequest(
            run_id="invalid-training-admission",
            solver_id="epa_swmm",
            executable_path=SWMM_EXECUTABLE,
            model_input_path=SWMM_INPUT,
            expected_solver_version="5.2.4",
            training_admitted=True,
        )


def test_swmm_nonzero_exit_fails_closed():
    false_executable = Path("/usr/bin/false")
    if not false_executable.exists():
        pytest.skip("POSIX false executable is unavailable")

    with pytest.raises(
        TraditionalSolverExecutionError, match="swmm_execution_nonzero_exit"
    ):
        execute_swmm(_request(executable=false_executable))


@pytest.mark.skipif(
    not SWMM_EXECUTABLE.is_file(),
    reason="the source-built SWMM 5.2.4 validation executable is unavailable",
)
def test_real_swmm_execution_can_opt_in_to_native_output_archive(tmp_path: Path):
    archive = tmp_path / "swmm-archive"
    receipt = execute_swmm(_request(), retain_output_directory=archive)

    retained = receipt["execution"]["retained_output_artifacts"]
    report = archive / f"{_request().run_id}.rpt"
    binary_output = archive / f"{_request().run_id}.out"
    assert receipt["execution"]["temporary_working_directory_retained"] is False
    assert receipt["execution"]["retained_output_directory_provided"] is True
    assert report.is_file()
    assert binary_output.is_file()
    assert retained["report"]["sha256"] == _sha256(report)
    assert retained["binary_output"]["sha256"] == _sha256(binary_output)
    assert retained["report"]["path"] == f"retained:{report.name}"
    assert retained["binary_output"]["path"] == f"retained:{binary_output.name}"


def test_swmm_rejects_unhashed_external_input_dependencies(tmp_path: Path):
    if not SWMM_INPUT.is_file():
        pytest.skip("external SWMM validation input is not present in this checkout")
    input_with_external_file = tmp_path / "external-rain.inp"
    input_with_external_file.write_text(
        SWMM_INPUT.read_text(encoding="utf-8")
        + "\n[TIMESERIES]\nTS_EXTERNAL FILE rainfall.dat\n",
        encoding="utf-8",
    )
    request = TraditionalSolverRunRequest(
        run_id="external-input-must-fail-closed",
        solver_id="epa_swmm",
        executable_path=SWMM_EXECUTABLE,
        model_input_path=input_with_external_file,
        expected_solver_version="5.2.4",
    )

    with pytest.raises(ValueError, match="swmm_external_input_files_not_supported"):
        execute_swmm(request)


@pytest.mark.skipif(
    not SWMM_EXECUTABLE.is_file(),
    reason="the source-built SWMM 5.2.4 validation executable is unavailable",
)
def test_real_swmm_execution_is_hashed_isolated_and_remains_diagnostic_only():
    source_input_hash = _sha256(SWMM_INPUT)
    receipt = execute_swmm(_request())

    assert receipt["status"] == "completed_numerical_quality_passed_not_admitted"
    assert receipt["quality_gates"]["passed"] is True
    assert receipt["parsed_report"]["solver"]["version"] == "5.2.4"
    assert receipt["execution"]["shell_used"] is False
    assert receipt["execution"]["isolated_temporary_working_directory"] is True
    assert receipt["execution"]["temporary_working_directory_retained"] is False
    assert receipt["execution"]["executable_copied_and_hash_verified"] is True
    assert receipt["execution"]["runtime_dependencies_copied_and_hash_verified"] >= 0
    assert receipt["execution"]["input_copy_hash_verified"] is True
    assert receipt["execution"]["external_input_files_allowed"] is False
    assert receipt["run_contract"]["runtime_artifact"]["sha256"] == _sha256(
        SWMM_EXECUTABLE
    )
    assert receipt["run_contract"]["model_input_artifact"]["sha256"] == source_input_hash
    for artifact in receipt["run_contract"]["runtime_dependency_artifacts"]:
        assert len(artifact["sha256"]) == 64
        assert artifact["size_bytes"] > 0
    assert _sha256(SWMM_INPUT) == source_input_hash
    for artifact in receipt["execution"]["output_artifacts"].values():
        assert len(artifact["sha256"]) == 64
        assert artifact["size_bytes"] > 0
    assert receipt["admission"] == receipt["run_contract"]["claim_boundary"]
    assert receipt["admission"]["diagnostic_only"] is True
    assert receipt["admission"]["traditional_model_admitted"] is False
    assert receipt["admission"]["gwm_training_admitted"] is False
    assert receipt["admission"]["production_admitted"] is False
    assert receipt["admission"]["city_scale_prediction_claim_allowed"] is False

    receipt_hash = receipt.pop("receipt_sha256")
    assert receipt_hash == _canonical_sha256(receipt)
