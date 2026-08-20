"""Fail-closed LISFLOOD-FP BMI diagnostic adapter for Abu Dhabi flood work."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from .traditional_solver import (
    TraditionalSolverExecutionError,
    TraditionalSolverRunRequest,
    artifact_descriptor,
    build_traditional_solver_run_contract,
)

LISFLOOD_EXECUTION_RECEIPT_SCHEMA = (
    "gwm.abu_dhabi_flood.lisflood_fp_execution_receipt.v1"
)
LISFLOOD_OUTPUT_INSPECTION_SCHEMA = (
    "gwm.abu_dhabi_flood.lisflood_fp_output_inspection.v1"
)
LISFLOOD_QUALITY_POLICY_SCHEMA = "gwm.abu_dhabi_flood.lisflood_fp_quality_policy.v1"
_MAXIMUM_INPUT_BYTES = 128 * 1024 * 1024
_MAXIMUM_OUTPUT_BYTES = 1024 * 1024 * 1024
_MAXIMUM_STDIO_BYTES = 8 * 1024 * 1024
_GIT_TIMEOUT_SECONDS = 20.0
_PARAMETER_KEYS = {
    "DEMfile",
    "resroot",
    "fpfric",
    "sim_time",
    "initial_tstep",
    "massint",
    "saveint",
    "rainfall",
    "qoutput",
}
_VALUE_PARAMETER_KEYS = _PARAMETER_KEYS - {"qoutput"}
_FILE_PARAMETER_KEYS = {"DEMfile", "rainfall"}
_MASS_COLUMNS = (
    "Time",
    "Tstep",
    "MinTstep",
    "NumTsteps",
    "Area",
    "Vol",
    "Qin",
    "Hds",
    "Qout",
    "Qerror",
    "Verror",
    "Rain-Inf+Evap",
)
_GRID_HEADER_KEYS = (
    "ncols",
    "nrows",
    "xllcorner",
    "yllcorner",
    "cellsize",
    "NODATA_value",
)


@dataclass(frozen=True)
class LisfloodQualityPolicy:
    """Structural and numerical gates for a fixed LISFLOOD-FP diagnostic."""

    expected_ncols: int
    expected_nrows: int
    expected_final_time_seconds: float
    expected_final_volume_m3: float
    maximum_absolute_final_volume_difference_m3: float = 1.0e-6
    maximum_absolute_qerror: float = 1.0e-10
    maximum_absolute_verror: float = 1.0e-10
    minimum_allowed_depth_m: float = -1.0e-9
    maximum_rainfall_ledger_difference_m3: float = 1.0e-5
    require_strictly_increasing_mass_time: bool = True
    require_positive_wet_depth: bool = True

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in (self.expected_ncols, self.expected_nrows)
        ):
            raise ValueError("lisflood_quality_expected_dimensions_invalid")
        numeric_values = (
            self.expected_final_time_seconds,
            self.expected_final_volume_m3,
            self.maximum_absolute_final_volume_difference_m3,
            self.maximum_absolute_qerror,
            self.maximum_absolute_verror,
            self.minimum_allowed_depth_m,
            self.maximum_rainfall_ledger_difference_m3,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in numeric_values
        ):
            raise ValueError("lisflood_quality_numeric_threshold_invalid")
        if (
            self.expected_final_time_seconds <= 0.0
            or self.expected_final_volume_m3 < 0.0
            or self.maximum_absolute_final_volume_difference_m3 < 0.0
            or self.maximum_absolute_qerror < 0.0
            or self.maximum_absolute_verror < 0.0
            or self.maximum_rainfall_ledger_difference_m3 < 0.0
        ):
            raise ValueError("lisflood_quality_numeric_threshold_invalid")
        if (
            not isinstance(self.require_strictly_increasing_mass_time, bool)
            or not isinstance(self.require_positive_wet_depth, bool)
        ):
            raise ValueError("lisflood_quality_flag_invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": LISFLOOD_QUALITY_POLICY_SCHEMA,
            "expected_ncols": self.expected_ncols,
            "expected_nrows": self.expected_nrows,
            "expected_final_time_seconds": float(self.expected_final_time_seconds),
            "expected_final_volume_m3": float(self.expected_final_volume_m3),
            "maximum_absolute_final_volume_difference_m3": float(
                self.maximum_absolute_final_volume_difference_m3
            ),
            "maximum_absolute_qerror": float(self.maximum_absolute_qerror),
            "maximum_absolute_verror": float(self.maximum_absolute_verror),
            "minimum_allowed_depth_m": float(self.minimum_allowed_depth_m),
            "maximum_rainfall_ledger_difference_m3": float(
                self.maximum_rainfall_ledger_difference_m3
            ),
            "require_strictly_increasing_mass_time": (
                self.require_strictly_increasing_mass_time
            ),
            "require_positive_wet_depth": self.require_positive_wet_depth,
        }


def parse_lisflood_parameters(text: str) -> dict[str, object]:
    """Parse the intentionally narrow, self-contained v1 parameter profile."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("lisflood_parameter_text_required")
    parameters: dict[str, object] = {}
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        key = parts[0]
        if key not in _PARAMETER_KEYS:
            raise ValueError(f"lisflood_parameter_not_allowed:{key}")
        if key in parameters:
            raise ValueError(f"lisflood_parameter_duplicate:{key}")
        if key == "qoutput":
            if len(parts) != 1:
                raise ValueError("lisflood_parameter_qoutput_invalid")
            parameters[key] = True
        else:
            if len(parts) != 2:
                raise ValueError(f"lisflood_parameter_value_invalid:{key}")
            parameters[key] = parts[1]
    if set(parameters) != _PARAMETER_KEYS:
        missing = ",".join(sorted(_PARAMETER_KEYS - set(parameters)))
        raise ValueError(f"lisflood_required_parameters_missing:{missing}")
    for key in _FILE_PARAMETER_KEYS:
        value = parameters[key]
        if not isinstance(value, str) or not _safe_basename(value):
            raise ValueError(f"lisflood_input_path_invalid:{key}")
    resroot = parameters["resroot"]
    if (
        not isinstance(resroot, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", resroot) is None
    ):
        raise ValueError("lisflood_resroot_invalid")
    for key in ("fpfric", "sim_time", "initial_tstep", "massint", "saveint"):
        try:
            value = float(str(parameters[key]))
        except ValueError as error:
            raise ValueError(f"lisflood_numeric_parameter_invalid:{key}") from error
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"lisflood_numeric_parameter_invalid:{key}")
        parameters[key] = value
    if parameters["massint"] > parameters["sim_time"]:
        raise ValueError("lisflood_mass_interval_exceeds_simulation")
    if parameters["saveint"] > parameters["sim_time"]:
        raise ValueError("lisflood_save_interval_exceeds_simulation")
    return parameters


def parse_lisflood_stdout(text: str) -> dict[str, object]:
    """Extract the runtime banner and completion evidence."""

    version = re.search(r"LISFLOOD-FP version\s+([0-9]+(?:\.[0-9]+){2})", text)
    base = re.search(r"modified version\s+([0-9]+(?:\.[0-9]+)?)", text)
    if version is None or base is None:
        raise ValueError("lisflood_runtime_banner_missing")
    return {
        "name": "LISFLOOD-FP BMI",
        "runtime_version": version.group(1),
        "base_model_version": base.group(1),
        "bmi_interface_version": "1.0",
        "finished": "Finished." in text,
    }


def parse_lisflood_mass(text: str) -> dict[str, object]:
    """Parse the LISFLOOD-FP mass ledger into finite named rows."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or tuple(lines[0].split()) != _MASS_COLUMNS:
        raise ValueError("lisflood_mass_header_invalid")
    rows: list[dict[str, float]] = []
    for line in lines[1:]:
        values = line.split()
        if len(values) != len(_MASS_COLUMNS):
            raise ValueError("lisflood_mass_row_invalid")
        try:
            parsed = [float(value) for value in values]
        except ValueError as error:
            raise ValueError("lisflood_mass_row_invalid") from error
        if not all(math.isfinite(value) for value in parsed):
            raise ValueError("lisflood_mass_nonfinite")
        rows.append(dict(zip(_MASS_COLUMNS, parsed, strict=True)))
    if not rows:
        raise ValueError("lisflood_mass_rows_missing")
    times = [row["Time"] for row in rows]
    return {
        "row_count": len(rows),
        "time_strictly_increasing": all(
            later > earlier for earlier, later in zip(times, times[1:], strict=False)
        ),
        "maximum_absolute_qerror": max(abs(row["Qerror"]) for row in rows),
        "maximum_absolute_verror": max(abs(row["Verror"]) for row in rows),
        "final": rows[-1],
    }


def parse_lisflood_ascii_grid(text: str) -> dict[str, object]:
    """Parse one ESRI ASCII-style output grid without external GIS packages."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 7:
        raise ValueError("lisflood_grid_too_short")
    header: dict[str, float] = {}
    for index, expected_key in enumerate(_GRID_HEADER_KEYS):
        parts = lines[index].split()
        if len(parts) != 2 or parts[0] != expected_key:
            raise ValueError("lisflood_grid_header_invalid")
        try:
            value = float(parts[1])
        except ValueError as error:
            raise ValueError("lisflood_grid_header_invalid") from error
        if not math.isfinite(value):
            raise ValueError("lisflood_grid_header_invalid")
        header[expected_key] = value
    ncols = int(header["ncols"])
    nrows = int(header["nrows"])
    if (
        header["ncols"] != ncols
        or header["nrows"] != nrows
        or ncols <= 0
        or nrows <= 0
        or ncols * nrows > 100_000_000
        or header["cellsize"] <= 0.0
    ):
        raise ValueError("lisflood_grid_dimensions_invalid")
    data_lines = lines[6:]
    if len(data_lines) != nrows:
        raise ValueError("lisflood_grid_row_count_invalid")
    values: list[float] = []
    for line in data_lines:
        parts = line.split()
        if len(parts) != ncols:
            raise ValueError("lisflood_grid_column_count_invalid")
        try:
            row = [float(value) for value in parts]
        except ValueError as error:
            raise ValueError("lisflood_grid_value_invalid") from error
        if not all(math.isfinite(value) for value in row):
            raise ValueError("lisflood_grid_nonfinite")
        values.extend(row)
    nodata = header["NODATA_value"]
    valid_values = [value for value in values if value != nodata]
    if not valid_values:
        raise ValueError("lisflood_grid_has_no_valid_cells")
    return {
        "ncols": ncols,
        "nrows": nrows,
        "xllcorner": header["xllcorner"],
        "yllcorner": header["yllcorner"],
        "cellsize": header["cellsize"],
        "nodata_value": nodata,
        "valid_cell_count": len(valid_values),
        "all_values_finite": True,
        "minimum": min(valid_values),
        "maximum": max(valid_values),
        "values": valid_values,
    }


def evaluate_lisflood_quality(
    inspection: dict[str, Any],
    policy: LisfloodQualityPolicy,
) -> dict[str, Any]:
    """Evaluate the 2D grid and mass ledger without changing admission."""

    if inspection.get("schema") != LISFLOOD_OUTPUT_INSPECTION_SCHEMA:
        raise ValueError("lisflood_output_inspection_schema_invalid")
    mass = inspection["mass_ledger"]
    final = mass["final"]
    maximum_grid = inspection["maximum_depth_grid"]
    final_grid = inspection["final_depth_grid"]
    checks = [
        _check("runtime_finished", inspection["solver"]["finished"] is True,
               inspection["solver"]["finished"], True),
        _check("grid_columns_match", maximum_grid["ncols"] == policy.expected_ncols,
               maximum_grid["ncols"], policy.expected_ncols),
        _check("grid_rows_match", maximum_grid["nrows"] == policy.expected_nrows,
               maximum_grid["nrows"], policy.expected_nrows),
        _check("final_grid_dimensions_match_maximum_grid",
               final_grid["ncols"] == maximum_grid["ncols"]
               and final_grid["nrows"] == maximum_grid["nrows"],
               [final_grid["ncols"], final_grid["nrows"]],
               [maximum_grid["ncols"], maximum_grid["nrows"]]),
        _check("mass_time_strictly_increasing",
               not policy.require_strictly_increasing_mass_time
               or mass["time_strictly_increasing"] is True,
               mass["time_strictly_increasing"], True),
        _check("final_time_matches",
               _close(final["Time"], policy.expected_final_time_seconds),
               final["Time"], policy.expected_final_time_seconds),
        _check("final_volume_matches",
               abs(final["Vol"] - policy.expected_final_volume_m3)
               <= policy.maximum_absolute_final_volume_difference_m3,
               final["Vol"], policy.expected_final_volume_m3),
        _check("qerror_within_threshold",
               mass["maximum_absolute_qerror"] <= policy.maximum_absolute_qerror,
               mass["maximum_absolute_qerror"], policy.maximum_absolute_qerror),
        _check("verror_within_threshold",
               mass["maximum_absolute_verror"] <= policy.maximum_absolute_verror,
               mass["maximum_absolute_verror"], policy.maximum_absolute_verror),
        _check("maximum_depth_nonnegative",
               maximum_grid["minimum"] >= policy.minimum_allowed_depth_m,
               maximum_grid["minimum"], policy.minimum_allowed_depth_m),
        _check("final_depth_nonnegative",
               final_grid["minimum"] >= policy.minimum_allowed_depth_m,
               final_grid["minimum"], policy.minimum_allowed_depth_m),
        _check("positive_wet_depth_present",
               not policy.require_positive_wet_depth or maximum_grid["maximum"] > 0.0,
               maximum_grid["maximum"], ">0"),
        _check("rainfall_ledger_matches_input",
               abs(inspection["rainfall"]["expected_volume_m3"]
                   - final["Rain-Inf+Evap"])
               <= policy.maximum_rainfall_ledger_difference_m3,
               final["Rain-Inf+Evap"], inspection["rainfall"]["expected_volume_m3"]),
    ]
    failed = [str(check["check_id"]) for check in checks if not check["passed"]]
    return {
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "admission_effect": "none_diagnostic_quality_only",
    }


def execute_lisflood(
    request: TraditionalSolverRunRequest,
    *,
    runtime_library_path: Path,
    source_root: Path,
    expected_source_commit: str,
    expected_source_diff_sha256: str,
    expected_source_status_sha256: str,
    quality_policy: LisfloodQualityPolicy,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Run a self-contained LISFLOOD-FP input bundle in a disposable directory."""

    _validate_execute_arguments(
        request=request,
        expected_source_commit=expected_source_commit,
        expected_source_diff_sha256=expected_source_diff_sha256,
        expected_source_status_sha256=expected_source_status_sha256,
        quality_policy=quality_policy,
        timeout_seconds=timeout_seconds,
    )
    executable = Path(request.executable_path).expanduser().resolve()
    library = Path(runtime_library_path).expanduser().resolve()
    parameter_path = Path(request.model_input_path).expanduser().resolve()
    source_label = str(source_root)
    source = Path(source_root).expanduser().resolve()
    _validate_runtime_paths(executable, library, parameter_path, source)
    try:
        parameter_text = parameter_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("lisflood_parameter_encoding_invalid") from error
    parameters = parse_lisflood_parameters(parameter_text)
    input_paths = {
        key: (parameter_path.parent / str(parameters[key])).resolve()
        for key in sorted(_FILE_PARAMETER_KEYS)
    }
    for key, path in input_paths.items():
        if path.parent != parameter_path.parent or not path.is_file():
            raise ValueError(f"lisflood_input_dependency_invalid:{key}")
        if path.stat().st_size <= 0 or path.stat().st_size > _MAXIMUM_INPUT_BYTES:
            raise ValueError(f"lisflood_input_dependency_invalid:{key}")
    source_identity = _source_identity(source, source_label)
    _validate_source_identity(
        source_identity,
        expected_source_commit=expected_source_commit,
        expected_source_diff_sha256=expected_source_diff_sha256,
        expected_source_status_sha256=expected_source_status_sha256,
    )
    executable_hash = _sha256_file(executable)
    library_hash = _sha256_file(library)
    parameter_hash = _sha256_file(parameter_path)
    dependency_artifacts = [
        artifact_descriptor(
            path,
            sha256=_sha256_file(path),
            path_label=str(path.relative_to(parameter_path.parent)),
        )
        for path in input_paths.values()
    ]
    run_contract = build_traditional_solver_run_contract(
        request,
        executable_artifact=artifact_descriptor(
            executable,
            sha256=executable_hash,
            path_label=str(request.executable_path),
        ),
        input_artifact=artifact_descriptor(
            parameter_path,
            sha256=parameter_hash,
            path_label=str(request.model_input_path),
        ),
        quality_policy=quality_policy,
        runtime_dependency_artifacts=(
            artifact_descriptor(
                library,
                sha256=library_hash,
                path_label=str(runtime_library_path),
            ),
        ),
        model_input_dependency_artifacts=dependency_artifacts,
    )
    dem_grid = parse_lisflood_ascii_grid(input_paths["DEMfile"].read_text(encoding="utf-8"))
    rainfall = _parse_rainfall(
        input_paths["rainfall"],
        simulation_seconds=float(parameters["sim_time"]),
        valid_cell_count=int(dem_grid["valid_cell_count"]),
        cellsize=float(dem_grid["cellsize"]),
    )

    with tempfile.TemporaryDirectory(prefix="gwm-abu-dhabi-lisflood-") as temporary_root:
        root = Path(temporary_root)
        isolated_executable = root / "lisflood"
        isolated_library = root / library.name
        isolated_parameter = root / "model.par"
        shutil.copyfile(executable, isolated_executable)
        shutil.copyfile(library, isolated_library)
        shutil.copyfile(parameter_path, isolated_parameter)
        isolated_executable.chmod(0o500)
        isolated_library.chmod(0o400)
        isolated_parameter.chmod(0o400)
        for key, source_path in input_paths.items():
            destination = root / str(parameters[key])
            shutil.copyfile(source_path, destination)
            destination.chmod(0o400)
        if _sha256_file(isolated_executable) != executable_hash:
            raise TraditionalSolverExecutionError("lisflood_executable_copy_hash_mismatch")
        if _sha256_file(isolated_library) != library_hash:
            raise TraditionalSolverExecutionError("lisflood_library_copy_hash_mismatch")
        if _sha256_file(isolated_parameter) != parameter_hash:
            raise TraditionalSolverExecutionError("lisflood_parameter_copy_hash_mismatch")
        for artifact, key in zip(dependency_artifacts, input_paths, strict=True):
            if _sha256_file(root / str(parameters[key])) != artifact["sha256"]:
                raise TraditionalSolverExecutionError("lisflood_input_copy_hash_mismatch")
        loader_variable = (
            "DYLD_LIBRARY_PATH"
            if platform.system() == "Darwin"
            else "LD_LIBRARY_PATH"
        )
        started = monotonic()
        try:
            completed = subprocess.run(
                [str(isolated_executable), "-v", isolated_parameter.name],
                cwd=root,
                check=False,
                capture_output=True,
                shell=False,
                timeout=float(timeout_seconds),
                env={
                    "LANG": "C",
                    "LC_ALL": "C",
                    loader_variable: str(root),
                    "PATH": "/usr/bin:/bin",
                    "TZ": "UTC",
                },
            )
        except subprocess.TimeoutExpired as error:
            raise TraditionalSolverExecutionError("lisflood_execution_timeout") from error
        except OSError as error:
            raise TraditionalSolverExecutionError("lisflood_execution_failed_to_start") from error
        elapsed_seconds = monotonic() - started
        if completed.returncode != 0:
            raise TraditionalSolverExecutionError(
                "lisflood_execution_nonzero_exit",
                details={
                    "returncode": completed.returncode,
                    "stdout_sha256": _sha256_bytes(completed.stdout),
                    "stderr_sha256": _sha256_bytes(completed.stderr),
                },
            )
        if (
            len(completed.stdout) > _MAXIMUM_STDIO_BYTES
            or len(completed.stderr) > _MAXIMUM_STDIO_BYTES
        ):
            raise TraditionalSolverExecutionError("lisflood_stdio_exceeds_size_limit")
        try:
            stdout_text = completed.stdout.decode("utf-8")
            solver = parse_lisflood_stdout(stdout_text)
        except (UnicodeDecodeError, ValueError) as error:
            raise TraditionalSolverExecutionError("lisflood_stdout_parse_failed") from error
        if solver["runtime_version"] != request.expected_solver_version:
            raise TraditionalSolverExecutionError("lisflood_solver_version_mismatch")
        resroot = str(parameters["resroot"])
        snapshot_count = int(float(parameters["sim_time"]) / float(parameters["saveint"])) + 1
        output_paths = _expected_output_paths(root, resroot, snapshot_count)
        for path in output_paths:
            _validate_output(path)
        try:
            mass = parse_lisflood_mass((root / f"{resroot}.mass").read_text(encoding="utf-8"))
            maximum_grid = parse_lisflood_ascii_grid(
                (root / f"{resroot}.max").read_text(encoding="utf-8")
            )
            final_grid = parse_lisflood_ascii_grid(
                (root / f"{resroot}-{snapshot_count - 1:04d}.wd").read_text(encoding="utf-8")
            )
        except (UnicodeDecodeError, ValueError) as error:
            raise TraditionalSolverExecutionError("lisflood_output_parse_failed") from error
        inspection = {
            "schema": LISFLOOD_OUTPUT_INSPECTION_SCHEMA,
            "solver": solver,
            "parameters": parameters,
            "input_dem_grid": _without_values(dem_grid),
            "rainfall": rainfall,
            "mass_ledger": mass,
            "maximum_depth_grid": _without_values(maximum_grid),
            "final_depth_grid": _without_values(final_grid),
            "output_file_count": len(output_paths),
            "snapshot_count": snapshot_count,
        }
        quality = evaluate_lisflood_quality(inspection, quality_policy)
        if not quality["passed"]:
            raise TraditionalSolverExecutionError(
                "lisflood_numerical_quality_gate_failed",
                details={"quality_gates": quality, "inspection": inspection},
            )
        output_artifacts = {
            path.name: artifact_descriptor(
                path,
                sha256=_sha256_file(path),
                path_label=f"isolated:{path.name}",
            )
            for path in output_paths
        }

    if _sha256_file(executable) != executable_hash or _sha256_file(library) != library_hash:
        raise TraditionalSolverExecutionError("lisflood_runtime_hash_changed_during_execution")
    if _sha256_file(parameter_path) != parameter_hash:
        raise TraditionalSolverExecutionError("lisflood_parameter_hash_changed_during_execution")
    if any(
        _sha256_file(path) != artifact["sha256"]
        for path, artifact in zip(input_paths.values(), dependency_artifacts, strict=True)
    ):
        raise TraditionalSolverExecutionError("lisflood_input_hash_changed_during_execution")
    if _source_identity(source, source_label) != source_identity:
        raise TraditionalSolverExecutionError("lisflood_source_identity_changed_during_execution")
    receipt: dict[str, Any] = {
        "schema": LISFLOOD_EXECUTION_RECEIPT_SCHEMA,
        "status": "completed_numerical_quality_passed_not_admitted",
        "run_contract": run_contract,
        "source_identity": source_identity,
        "inspection": inspection,
        "quality_gates": quality,
        "license_boundary": {
            "solver_license": "GPL-3.0",
            "execution_boundary": "independent_process",
            "solver_code_embedded_in_gwm": False,
            "commercial_product_license_review_required": True,
            "legal_advice_provided": False,
        },
        "execution": {
            "shell_used": False,
            "fixed_argument_order": ["executable", "-v", "model.par"],
            "isolated_temporary_working_directory": True,
            "temporary_working_directory_retained": False,
            "input_bundle_copy_hash_verified": True,
            "runtime_hash_verified_before_and_after": True,
            "source_identity_verified_before_and_after": True,
            "dynamic_library_search_path_scoped_to_temporary_directory": True,
            "operating_system_filesystem_sandboxed": False,
            "network_namespace_isolated": False,
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


def _parse_rainfall(
    path: Path,
    *,
    simulation_seconds: float,
    valid_cell_count: int,
    cellsize: float,
) -> dict[str, object]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) < 3 or not lines[0].startswith("#"):
        raise ValueError("lisflood_rainfall_header_invalid")
    count_parts = lines[1].split()
    if len(count_parts) != 2 or count_parts[1] not in {"seconds", "hours", "days"}:
        raise ValueError("lisflood_rainfall_header_invalid")
    try:
        count = int(count_parts[0])
    except ValueError as error:
        raise ValueError("lisflood_rainfall_header_invalid") from error
    if count <= 1 or len(lines[2:]) != count:
        raise ValueError("lisflood_rainfall_row_count_invalid")
    multiplier = {"seconds": 1.0, "hours": 3600.0, "days": 86400.0}[count_parts[1]]
    points: list[tuple[float, float]] = []
    for line in lines[2:]:
        parts = line.split()
        if len(parts) != 2:
            raise ValueError("lisflood_rainfall_row_invalid")
        try:
            rate = float(parts[0])
            seconds = float(parts[1]) * multiplier
        except ValueError as error:
            raise ValueError("lisflood_rainfall_row_invalid") from error
        if not math.isfinite(rate) or not math.isfinite(seconds) or rate < 0.0:
            raise ValueError("lisflood_rainfall_row_invalid")
        points.append((seconds, rate))
    if points[0][0] != 0.0 or any(
        later[0] <= earlier[0]
        for earlier, later in zip(points, points[1:], strict=False)
    ) or points[-1][0] < simulation_seconds:
        raise ValueError("lisflood_rainfall_time_support_invalid")
    depth_mm = 0.0
    remaining = simulation_seconds
    for (start, start_rate), (end, end_rate) in zip(
        points, points[1:], strict=False
    ):
        if start >= simulation_seconds:
            break
        segment_end = min(end, simulation_seconds)
        duration = segment_end - start
        end_fraction = duration / (end - start)
        truncated_end_rate = start_rate + (end_rate - start_rate) * end_fraction
        depth_mm += 0.5 * (start_rate + truncated_end_rate) * duration / 3600.0
        remaining -= duration
        if segment_end >= simulation_seconds:
            break
    if remaining > 1.0e-6:
        raise ValueError("lisflood_rainfall_time_support_invalid")
    area_m2 = valid_cell_count * cellsize * cellsize
    return {
        "row_count": count,
        "time_units": count_parts[1],
        "simulation_depth_mm": depth_mm,
        "valid_domain_area_m2": area_m2,
        "expected_volume_m3": depth_mm / 1000.0 * area_m2,
    }


def _expected_output_paths(root: Path, resroot: str, snapshot_count: int) -> tuple[Path, ...]:
    paths = [
        root / f"{resroot}{suffix}"
        for suffix in (".mass", ".max", ".maxtm", ".inittm", ".totaltm", ".mxe")
    ]
    for index in range(snapshot_count):
        paths.extend(
            root / f"{resroot}-{index:04d}.{suffix}"
            for suffix in ("Qx", "Qy", "elev", "wd")
        )
    return tuple(paths)


def _validate_output(path: Path) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise TraditionalSolverExecutionError(f"lisflood_output_missing_or_empty:{path.name}")
    if path.stat().st_size > _MAXIMUM_OUTPUT_BYTES:
        raise TraditionalSolverExecutionError(f"lisflood_output_exceeds_size_limit:{path.name}")


def _validate_execute_arguments(**values: object) -> None:
    request = values["request"]
    if not isinstance(request, TraditionalSolverRunRequest):
        raise ValueError("lisflood_run_request_invalid")
    if request.solver_id != "lisflood_fp_2d":
        raise ValueError("lisflood_run_request_solver_invalid")
    commit = values["expected_source_commit"]
    if not isinstance(commit, str) or len(commit) != 40 or not _lower_hex(commit):
        raise ValueError("lisflood_expected_source_commit_invalid")
    for name in ("expected_source_diff_sha256", "expected_source_status_sha256"):
        value = values[name]
        if not isinstance(value, str) or len(value) != 64 or not _lower_hex(value):
            raise ValueError(f"lisflood_{name}_invalid")
    if not isinstance(values["quality_policy"], LisfloodQualityPolicy):
        raise ValueError("lisflood_quality_policy_invalid")
    timeout = values["timeout_seconds"]
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0.0
    ):
        raise ValueError("lisflood_timeout_invalid")


def _validate_runtime_paths(
    executable: Path, library: Path, parameter_path: Path, source_root: Path
) -> None:
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("lisflood_executable_invalid")
    if not library.is_file() or library.stat().st_size <= 0:
        raise ValueError("lisflood_runtime_library_invalid")
    if (
        not parameter_path.is_file()
        or parameter_path.suffix.lower() != ".par"
        or parameter_path.stat().st_size <= 0
        or parameter_path.stat().st_size > _MAXIMUM_INPUT_BYTES
    ):
        raise ValueError("lisflood_parameter_file_invalid")
    if not (source_root / ".git").exists():
        raise ValueError("lisflood_source_root_invalid")


def _source_identity(source_root: Path, path_label: str) -> dict[str, object]:
    commit = _git(source_root, "rev-parse", "HEAD").decode("ascii").strip()
    diff = _git(source_root, "diff", "--binary")
    status = _git(source_root, "status", "--porcelain=v1", "--untracked-files=all")
    return {
        "source_root": path_label,
        "git_commit": commit,
        "git_diff_sha256": _sha256_bytes(diff),
        "git_status_sha256": _sha256_bytes(status),
        "git_dirty": bool(status),
        "git_status_line_count": len(status.splitlines()),
        "untracked_build_and_fixture_files_explicitly_fingerprinted": bool(status),
    }


def _validate_source_identity(
    identity: dict[str, object],
    *,
    expected_source_commit: str,
    expected_source_diff_sha256: str,
    expected_source_status_sha256: str,
) -> None:
    if (
        identity["git_commit"] != expected_source_commit
        or identity["git_diff_sha256"] != expected_source_diff_sha256
        or identity["git_status_sha256"] != expected_source_status_sha256
    ):
        raise TraditionalSolverExecutionError(
            "lisflood_source_identity_mismatch", details={"observed": identity}
        )


def _git(source_root: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_root), *arguments],
            check=False,
            capture_output=True,
            shell=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise TraditionalSolverExecutionError("lisflood_source_identity_read_failed") from error
    if completed.returncode != 0:
        raise TraditionalSolverExecutionError("lisflood_source_identity_read_failed")
    return completed.stdout


def _without_values(grid: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in grid.items() if key != "values"}


def _safe_basename(value: str) -> bool:
    return Path(value).name == value and value not in {".", ".."} and "\x00" not in value


def _lower_hex(value: str) -> bool:
    return all(character in "0123456789abcdef" for character in value)


def _close(observed: object, expected: float) -> bool:
    return isinstance(observed, (int, float)) and math.isclose(
        float(observed), float(expected), rel_tol=0.0, abs_tol=1.0e-9
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
