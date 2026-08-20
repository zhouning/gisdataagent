"""Fail-closed EPA SWMM diagnostic adapter for Abu Dhabi flood-model work."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from time import monotonic
from typing import Any

from .traditional_solver import (
    TraditionalSolverExecutionError,
    TraditionalSolverQualityPolicy,
    TraditionalSolverRunRequest,
    artifact_descriptor,
    build_traditional_solver_run_contract,
)

SWMM_EXECUTION_RECEIPT_SCHEMA = "gwm.abu_dhabi_flood.swmm_execution_receipt.v1"
SWMM_REPORT_PARSE_SCHEMA = "gwm.abu_dhabi_flood.swmm_report_parse.v1"
_MAXIMUM_REPORT_BYTES = 32 * 1024 * 1024
_MAXIMUM_BINARY_OUTPUT_BYTES = 512 * 1024 * 1024
_FLOAT = r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][-+]?[0-9]+)?"
_SWMM_ERROR_PATTERN = re.compile(
    r"(?im)^\s*(?:\*+\s*)?ERROR(?:\s+\d+)?\s*:",
)
_SWMM_WARNING_PATTERN = re.compile(
    r"(?im)^\s*(?:\*+\s*)?WARNING(?:\s+\d+)?\s*:",
)


def parse_swmm_report(report_text: str) -> dict[str, Any]:
    """Parse the numerical and structural evidence used by SWMM quality gates."""

    if not isinstance(report_text, str) or not report_text.strip():
        raise ValueError("swmm_report_text_required")
    version_match = _required_search(
        r"EPA STORM WATER MANAGEMENT MODEL - VERSION\s+"
        r"(?P<series>[0-9.]+)\s+\(Build\s+(?P<build>[0-9.]+)\)",
        report_text,
        "version",
    )
    element_counts = {
        key: _required_integer(
            rf"Number of {label}\s*\.{{2,}}\s*(?P<value>[0-9]+)",
            report_text,
            key,
        )
        for key, label in (
            ("rain_gages", "rain gages"),
            ("subcatchments", "subcatchments"),
            ("nodes", "nodes"),
            ("links", "links"),
            ("pollutants", "pollutants"),
            ("land_uses", "land uses"),
        )
    }
    flow_units = _required_value(
        r"Flow Units\s*\.{2,}\s*(?P<value>[A-Za-z0-9_/.-]+)",
        report_text,
        "flow_units",
    )
    routing_method = _required_value(
        r"Flow Routing Method\s*\.{2,}\s*(?P<value>[A-Za-z0-9_-]+)",
        report_text,
        "routing_method",
    )
    runoff_section = _between(
        report_text,
        "Runoff Quantity Continuity",
        "Flow Routing Continuity",
        "runoff_continuity",
    )
    routing_section = _between(
        report_text,
        "Flow Routing Continuity",
        "Highest Flow Instability Indexes",
        "flow_routing_continuity",
    )
    runoff = {
        "total_precipitation": _quantity_pair(runoff_section, "Total Precipitation"),
        "infiltration_loss": _quantity_pair(runoff_section, "Infiltration Loss"),
        "surface_runoff": _quantity_pair(runoff_section, "Surface Runoff"),
        "continuity_error_percent": _single_number(
            runoff_section,
            "Continuity Error (%)",
            "runoff_continuity_error",
        ),
        "quantity_units": {
            "first": "hectare-m",
            "second": "mm",
        },
    }
    routing = {
        "wet_weather_inflow": _quantity_pair(routing_section, "Wet Weather Inflow"),
        "external_outflow": _quantity_pair(routing_section, "External Outflow"),
        "flooding_loss": _quantity_pair(routing_section, "Flooding Loss"),
        "continuity_error_percent": _single_number(
            routing_section,
            "Continuity Error (%)",
            "routing_continuity_error",
        ),
        "quantity_units": {
            "first": "hectare-m",
            "second": "10^6_ltr",
        },
    }
    links_stable = re.search(r"\bAll links are stable\.\s*", report_text) is not None
    nonconverging_steps = float(
        _required_search(
            rf"% of Steps Not Converging\s*:\s*(?P<value>{_FLOAT})",
            report_text,
            "nonconverging_steps",
        ).group("value")
    )
    flooding_summary_present = "Node Flooding Summary" in report_text
    if not flooding_summary_present:
        raise ValueError("swmm_report_required_field_missing:node_flooding_summary")
    no_nodes_flooded = re.search(
        r"\bNo nodes were flooded\.\s*", report_text, flags=re.IGNORECASE
    ) is not None
    return {
        "schema": SWMM_REPORT_PARSE_SCHEMA,
        "solver": {
            "name": "EPA SWMM",
            "version_series": version_match.group("series"),
            "version": version_match.group("build"),
        },
        "element_counts": element_counts,
        "analysis_options": {
            "flow_units": flow_units,
            "flow_routing_method": routing_method,
        },
        "runoff_quantity_continuity": runoff,
        "flow_routing_continuity": routing,
        "stability": {"all_links_stable": links_stable},
        "convergence": {"steps_not_converging_percent": nonconverging_steps},
        "node_flooding": {
            "summary_present": True,
            "detected": not no_nodes_flooded,
            "no_nodes_flooded": no_nodes_flooded,
        },
        "reported_messages": {
            "error_count": len(_SWMM_ERROR_PATTERN.findall(report_text)),
            "warning_count": len(_SWMM_WARNING_PATTERN.findall(report_text)),
        },
    }


def evaluate_swmm_quality(
    parsed_report: dict[str, Any],
    policy: TraditionalSolverQualityPolicy,
) -> dict[str, Any]:
    """Return named fail-closed checks without changing model admission status."""

    runoff_error = float(
        parsed_report["runoff_quantity_continuity"]["continuity_error_percent"]
    )
    routing_error = float(
        parsed_report["flow_routing_continuity"]["continuity_error_percent"]
    )
    nonconverging = float(
        parsed_report["convergence"]["steps_not_converging_percent"]
    )
    checks = [
        _check(
            "report_contains_no_swmm_errors",
            not policy.reject_reported_errors
            or parsed_report["reported_messages"]["error_count"] == 0,
            parsed_report["reported_messages"]["error_count"],
            0,
        ),
        _check(
            "all_links_stable",
            not policy.require_stable_links
            or parsed_report["stability"]["all_links_stable"] is True,
            parsed_report["stability"]["all_links_stable"],
            True,
        ),
        _check(
            "runoff_continuity_within_threshold",
            abs(runoff_error)
            <= policy.maximum_absolute_runoff_continuity_error_percent,
            runoff_error,
            policy.maximum_absolute_runoff_continuity_error_percent,
        ),
        _check(
            "routing_continuity_within_threshold",
            abs(routing_error)
            <= policy.maximum_absolute_routing_continuity_error_percent,
            routing_error,
            policy.maximum_absolute_routing_continuity_error_percent,
        ),
        _check(
            "nonconverging_steps_within_threshold",
            nonconverging <= policy.maximum_nonconverging_steps_percent,
            nonconverging,
            policy.maximum_nonconverging_steps_percent,
        ),
    ]
    failed_checks = [str(check["check_id"]) for check in checks if not check["passed"]]
    return {
        "passed": not failed_checks,
        "checks": checks,
        "failed_checks": failed_checks,
        "admission_effect": "none_diagnostic_quality_only",
    }


def execute_swmm(
    request: TraditionalSolverRunRequest,
    *,
    quality_policy: TraditionalSolverQualityPolicy | None = None,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Execute SWMM without a shell in an isolated, disposable directory."""

    if not isinstance(request, TraditionalSolverRunRequest):
        raise ValueError("swmm_run_request_invalid")
    if request.solver_id != "epa_swmm":
        raise ValueError("swmm_run_request_solver_invalid")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0.0
    ):
        raise ValueError("swmm_timeout_invalid")
    policy = quality_policy or TraditionalSolverQualityPolicy()
    if not isinstance(policy, TraditionalSolverQualityPolicy):
        raise ValueError("swmm_quality_policy_invalid")
    executable = Path(request.executable_path).expanduser().resolve()
    model_input = Path(request.model_input_path).expanduser().resolve()
    _validate_runtime_paths(executable, model_input)
    _validate_self_contained_input(model_input)
    executable_hash = _sha256_file(executable)
    input_hash = _sha256_file(model_input)
    runtime_dependencies = _discover_runtime_dependencies(executable)
    runtime_dependency_artifacts = [
        artifact_descriptor(
            dependency,
            sha256=_sha256_file(dependency),
            path_label=f"runtime-relative:../lib/{dependency.name}",
        )
        for dependency in runtime_dependencies
    ]
    executable_artifact = artifact_descriptor(
        executable,
        sha256=executable_hash,
        path_label=str(request.executable_path),
    )
    input_artifact = artifact_descriptor(
        model_input,
        sha256=input_hash,
        path_label=str(request.model_input_path),
    )
    run_contract = build_traditional_solver_run_contract(
        request,
        executable_artifact=executable_artifact,
        input_artifact=input_artifact,
        quality_policy=policy,
        runtime_dependency_artifacts=runtime_dependency_artifacts,
    )

    with tempfile.TemporaryDirectory(prefix="gwm-abu-dhabi-swmm-") as temporary_root:
        root = Path(temporary_root)
        bin_directory = root / "bin"
        lib_directory = root / "lib"
        bin_directory.mkdir()
        lib_directory.mkdir()
        isolated_executable = bin_directory / "runswmm"
        isolated_input = root / "model.inp"
        report_path = root / "model.rpt"
        binary_output_path = root / "model.out"
        shutil.copyfile(executable, isolated_executable)
        for dependency, dependency_artifact in zip(
            runtime_dependencies, runtime_dependency_artifacts, strict=True
        ):
            isolated_dependency = lib_directory / dependency.name
            shutil.copyfile(dependency, isolated_dependency)
            isolated_dependency.chmod(0o400)
            if _sha256_file(isolated_dependency) != dependency_artifact["sha256"]:
                raise TraditionalSolverExecutionError(
                    "swmm_runtime_dependency_copy_hash_mismatch"
                )
        shutil.copyfile(model_input, isolated_input)
        isolated_executable.chmod(0o500)
        isolated_input.chmod(0o400)
        if _sha256_file(isolated_executable) != executable_hash:
            raise TraditionalSolverExecutionError("swmm_executable_copy_hash_mismatch")
        if _sha256_file(isolated_input) != input_hash:
            raise TraditionalSolverExecutionError("swmm_input_copy_hash_mismatch")
        command = [
            str(isolated_executable),
            isolated_input.name,
            report_path.name,
            binary_output_path.name,
        ]
        started = monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                check=False,
                capture_output=True,
                shell=False,
                timeout=float(timeout_seconds),
                env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin", "TZ": "UTC"},
            )
        except subprocess.TimeoutExpired as error:
            raise TraditionalSolverExecutionError("swmm_execution_timeout") from error
        except OSError as error:
            raise TraditionalSolverExecutionError("swmm_execution_failed_to_start") from error
        elapsed_seconds = monotonic() - started
        if completed.returncode != 0:
            raise TraditionalSolverExecutionError(
                "swmm_execution_nonzero_exit",
                details={
                    "returncode": completed.returncode,
                    "stdout_sha256": _sha256_bytes(completed.stdout),
                    "stderr_sha256": _sha256_bytes(completed.stderr),
                },
            )
        _validate_output_artifact(report_path, _MAXIMUM_REPORT_BYTES, "report")
        _validate_output_artifact(
            binary_output_path,
            _MAXIMUM_BINARY_OUTPUT_BYTES,
            "binary_output",
        )
        try:
            report_text = report_path.read_text(encoding="utf-8")
            parsed_report = parse_swmm_report(report_text)
        except (UnicodeDecodeError, ValueError) as error:
            raise TraditionalSolverExecutionError("swmm_report_parse_failed") from error
        if parsed_report["solver"]["version"] != request.expected_solver_version:
            raise TraditionalSolverExecutionError(
                "swmm_solver_version_mismatch",
                details={
                    "expected": request.expected_solver_version,
                    "observed": parsed_report["solver"]["version"],
                },
            )
        quality = evaluate_swmm_quality(parsed_report, policy)
        if not quality["passed"]:
            raise TraditionalSolverExecutionError(
                "swmm_numerical_quality_gate_failed",
                details={"quality_gates": quality, "parsed_report": parsed_report},
            )
        output_artifacts = {
            "report": artifact_descriptor(
                report_path,
                sha256=_sha256_file(report_path),
                path_label="isolated:model.rpt",
            ),
            "binary_output": artifact_descriptor(
                binary_output_path,
                sha256=_sha256_file(binary_output_path),
                path_label="isolated:model.out",
            ),
        }

    receipt: dict[str, Any] = {
        "schema": SWMM_EXECUTION_RECEIPT_SCHEMA,
        "status": "completed_numerical_quality_passed_not_admitted",
        "run_contract": run_contract,
        "parsed_report": parsed_report,
        "quality_gates": quality,
        "execution": {
            "shell_used": False,
            "fixed_argument_order": ["executable", "model.inp", "model.rpt", "model.out"],
            "isolated_temporary_working_directory": True,
            "temporary_working_directory_retained": False,
            "executable_copied_and_hash_verified": True,
            "runtime_dependencies_copied_and_hash_verified": len(runtime_dependencies),
            "input_copied_into_isolated_directory": True,
            "input_copy_hash_verified": True,
            "external_input_files_allowed": False,
            "returncode": completed.returncode,
            "elapsed_seconds": round(elapsed_seconds, 6),
            "timeout_seconds": float(timeout_seconds),
            "stdout_sha256": _sha256_bytes(completed.stdout),
            "stderr_sha256": _sha256_bytes(completed.stderr),
            "output_artifacts": output_artifacts,
        },
        "admission": request.claim_boundary(),
    }
    receipt["receipt_sha256"] = _sha256_json(receipt)
    return receipt


def _validate_runtime_paths(executable: Path, model_input: Path) -> None:
    if (
        not executable.is_file()
        or not os.access(executable, os.X_OK)
        or executable.stat().st_size <= 0
    ):
        raise ValueError("swmm_executable_invalid")
    if (
        not model_input.is_file()
        or model_input.suffix.lower() != ".inp"
        or model_input.stat().st_size <= 0
    ):
        raise ValueError("swmm_model_input_invalid")


def _validate_self_contained_input(model_input: Path) -> None:
    try:
        text = model_input.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("swmm_model_input_encoding_invalid") from error
    active_lines = []
    for line in text.splitlines():
        active = line.split(";;", 1)[0].strip()
        if active:
            active_lines.append(active)
    active_text = "\n".join(active_lines)
    if re.search(r"(?im)^\[FILES\]\s*$", active_text) is not None or re.search(
        r"(?i)(?:^|\s)FILE(?:\s|$)", active_text
    ) is not None:
        raise ValueError("swmm_external_input_files_not_supported")


def _discover_runtime_dependencies(executable: Path) -> tuple[Path, ...]:
    library_directory = executable.parent.parent / "lib"
    if not library_directory.is_dir():
        return ()
    dependencies = tuple(
        sorted(
            path.resolve()
            for path in library_directory.glob("libswmm5.*")
            if path.is_file() and path.stat().st_size > 0
        )
    )
    if len(dependencies) > 4 or any(
        path.stat().st_size > 128 * 1024 * 1024 for path in dependencies
    ):
        raise ValueError("swmm_runtime_dependency_bundle_invalid")
    return dependencies


def _validate_output_artifact(path: Path, maximum_bytes: int, label: str) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise TraditionalSolverExecutionError(f"swmm_{label}_missing_or_empty")
    if path.stat().st_size > maximum_bytes:
        raise TraditionalSolverExecutionError(f"swmm_{label}_exceeds_size_limit")


def _required_search(pattern: str, text: str, field: str) -> re.Match[str]:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match is None:
        raise ValueError(f"swmm_report_required_field_missing:{field}")
    return match


def _required_value(pattern: str, text: str, field: str) -> str:
    return _required_search(pattern, text, field).group("value")


def _required_integer(pattern: str, text: str, field: str) -> int:
    return int(_required_value(pattern, text, field))


def _between(text: str, start: str, end: str, field: str) -> str:
    start_index = text.find(start)
    end_index = text.find(end, start_index + len(start))
    if start_index < 0 or end_index < 0:
        raise ValueError(f"swmm_report_required_section_missing:{field}")
    return text[start_index:end_index]


def _quantity_pair(section: str, label: str) -> dict[str, float]:
    match = _required_search(
        rf"{re.escape(label)}\s*\.{{2,}}\s*(?P<first>{_FLOAT})\s+(?P<second>{_FLOAT})",
        section,
        label.lower().replace(" ", "_"),
    )
    return {"first": float(match.group("first")), "second": float(match.group("second"))}


def _single_number(section: str, label: str, field: str) -> float:
    return float(
        _required_search(
            rf"{re.escape(label)}\s*\.{{2,}}\s*(?P<value>{_FLOAT})",
            section,
            field,
        ).group("value")
    )


def _check(check_id: str, passed: bool, observed: object, threshold: object) -> dict[str, object]:
    return {
        "check_id": check_id,
        "passed": bool(passed),
        "observed": observed,
        "threshold_or_required": threshold,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()
