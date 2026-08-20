"""Fail-closed ANUGA 2D diagnostic adapter for Abu Dhabi flood-model work."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
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

ANUGA_EXECUTION_RECEIPT_SCHEMA = "gwm.abu_dhabi_flood.anuga_execution_receipt.v1"
ANUGA_OUTPUT_INSPECTION_SCHEMA = "gwm.abu_dhabi_flood.anuga_output_inspection.v1"
ANUGA_QUALITY_POLICY_SCHEMA = "gwm.abu_dhabi_flood.anuga_quality_policy.v1"
_MAXIMUM_SCRIPT_BYTES = 2 * 1024 * 1024
_MAXIMUM_LOG_BYTES = 32 * 1024 * 1024
_MAXIMUM_METRICS_BYTES = 2 * 1024 * 1024
_MAXIMUM_SWW_BYTES = 1024 * 1024 * 1024
_GIT_TIMEOUT_SECONDS = 20.0
_RUNNER = r'''from __future__ import annotations

import contextlib
import io
import json
import math
import runpy
import sys
from pathlib import Path

import anuga
import numpy as np
from netCDF4 import Dataset

script_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
metrics_path = Path(sys.argv[3])
log_path = Path(sys.argv[4])
captured = io.StringIO()
try:
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        namespace = runpy.run_path(str(script_path), run_name="__main__")
finally:
    log_path.write_text(captured.getvalue(), encoding="utf-8")

domain = namespace.get("domain")
if domain is None:
    raise RuntimeError("anuga_diagnostic_domain_not_exported")
if not output_path.is_file():
    raise RuntimeError("anuga_diagnostic_sww_missing")

with Dataset(output_path, "r") as dataset:
    required = (
        "x", "y", "volumes", "elevation_c", "stage_c",
        "xmomentum_c", "ymomentum_c", "time",
    )
    missing = [name for name in required if name not in dataset.variables]
    if missing:
        raise RuntimeError("anuga_diagnostic_sww_variables_missing:" + ",".join(missing))
    x = np.asarray(dataset.variables["x"][:], dtype=np.float64)
    y = np.asarray(dataset.variables["y"][:], dtype=np.float64)
    volumes = np.asarray(dataset.variables["volumes"][:], dtype=np.int64)
    elevation = np.asarray(dataset.variables["elevation_c"][:], dtype=np.float64)
    stage = np.asarray(dataset.variables["stage_c"][:], dtype=np.float64)
    xmomentum = np.asarray(dataset.variables["xmomentum_c"][:], dtype=np.float64)
    ymomentum = np.asarray(dataset.variables["ymomentum_c"][:], dtype=np.float64)
    times = np.asarray(dataset.variables["time"][:], dtype=np.float64)
    arrays = (x, y, elevation, stage, xmomentum, ymomentum, times)
    all_required_values_finite = all(bool(np.isfinite(value).all()) for value in arrays)
    topology_indices_valid = bool(
        volumes.ndim == 2
        and volumes.shape[1] == 3
        and volumes.size > 0
        and volumes.min() >= 0
        and volumes.max() < len(x)
    )
    if not topology_indices_valid:
        raise RuntimeError("anuga_diagnostic_topology_invalid")
    cell_areas = np.abs(
        (x[volumes[:, 1]] - x[volumes[:, 0]])
        * (y[volumes[:, 2]] - y[volumes[:, 0]])
        - (x[volumes[:, 2]] - x[volumes[:, 0]])
        * (y[volumes[:, 1]] - y[volumes[:, 0]])
    ) / 2.0
    positive_finite_cell_areas = bool(
        np.isfinite(cell_areas).all() and np.all(cell_areas > 0.0)
    )
    depth = stage - elevation[None, :]
    volume_series = np.sum(depth * cell_areas[None, :], axis=1)
    maximum_depth_by_cell = np.max(depth, axis=0)
    cell_centroid_x = np.mean(x[volumes], axis=1)
    cell_centroid_y = np.mean(y[volumes], axis=1)
    maximum_depth_flat_index = int(np.argmax(depth))
    maximum_depth_time_index, maximum_depth_cell_index = np.unravel_index(
        maximum_depth_flat_index, depth.shape
    )
    inundation_thresholds = (0.05, 0.10, 0.30)
    inundation = {}
    for threshold in inundation_thresholds:
        wet_by_time = np.sum(
            (depth >= threshold) * cell_areas[None, :], axis=1
        )
        peak_wet_index = int(np.argmax(wet_by_time))
        inundation[f"{threshold:.2f}"] = {
            "threshold_depth_m": float(threshold),
            "maximum_wet_area_m2": float(wet_by_time[peak_wet_index]),
            "maximum_wet_area_time_seconds": float(times[peak_wet_index]),
            "final_wet_area_m2": float(wet_by_time[-1]),
            "maximum_depth_footprint_area_m2": float(
                np.sum(cell_areas[maximum_depth_by_cell >= threshold])
            ),
        }
    peak_volume_index = int(np.argmax(volume_series))
    time_strictly_increasing = bool(
        times.size > 0 and (times.size == 1 or np.all(np.diff(times) > 0.0))
    )
    attributes = {
        "anuga_version": str(getattr(dataset, "anuga_version", "")),
        "revision_number": str(getattr(dataset, "revision_number", "")),
        "units": str(getattr(dataset, "units", "")),
        "timezone": str(getattr(dataset, "timezone", "")),
    }

domain_volume = float(domain.get_water_volume())
boundary_flux_integral = float(domain.get_boundary_flux_integral())
fractional_step_volume_integral = float(domain.get_fractional_step_volume_integral())
initial_volume = float(volume_series[0])
mass_balance_residual = (
    domain_volume
    - initial_volume
    - boundary_flux_integral
    - fractional_step_volume_integral
)
mass_scale = max(
    abs(domain_volume - initial_volume),
    abs(boundary_flux_integral + fractional_step_volume_integral),
    1.0e-12,
)
payload = {
    "schema": "gwm.abu_dhabi_flood.anuga_output_inspection.v1",
    "solver": {
        "name": "ANUGA",
        "version": str(getattr(anuga, "__version__", "")),
    },
    "output_attributes": attributes,
    "mesh": {
        "cell_count": int(volumes.shape[0]),
        "point_count": int(x.size),
        "minimum_cell_area_m2": float(cell_areas.min()),
        "maximum_cell_area_m2": float(cell_areas.max()),
        "total_cell_area_m2": float(cell_areas.sum()),
        "topology_indices_valid": topology_indices_valid,
        "positive_finite_cell_areas": positive_finite_cell_areas,
    },
    "time_axis": {
        "step_count": int(times.size),
        "start_seconds": float(times[0]),
        "end_seconds": float(times[-1]),
        "minimum_interval_seconds": float(np.diff(times).min()) if times.size > 1 else 0.0,
        "maximum_interval_seconds": float(np.diff(times).max()) if times.size > 1 else 0.0,
        "strictly_increasing": time_strictly_increasing,
    },
    "state": {
        "all_required_values_finite": all_required_values_finite,
        "minimum_stage_m": float(stage.min()),
        "maximum_stage_m": float(stage.max()),
        "minimum_depth_m": float(depth.min()),
        "maximum_depth_m": float(depth.max()),
        "maximum_depth_time_seconds": float(times[maximum_depth_time_index]),
        "maximum_depth_cell_centroid": {
            "x": float(cell_centroid_x[maximum_depth_cell_index]),
            "y": float(cell_centroid_y[maximum_depth_cell_index]),
        },
        "maximum_absolute_momentum_m2s": float(
            max(np.abs(xmomentum).max(), np.abs(ymomentum).max())
        ),
        "inundation_area_by_depth_threshold": inundation,
    },
    "mass_balance": {
        "initial_volume_m3": initial_volume,
        "final_output_volume_m3": float(volume_series[-1]),
        "maximum_output_volume_m3": float(volume_series[peak_volume_index]),
        "maximum_output_volume_time_seconds": float(times[peak_volume_index]),
        "final_domain_volume_m3": domain_volume,
        "boundary_flux_integral_m3": boundary_flux_integral,
        "fractional_step_volume_integral_m3": fractional_step_volume_integral,
        "absolute_residual_m3": mass_balance_residual,
        "relative_residual_percent": 100.0 * mass_balance_residual / mass_scale,
        "output_domain_final_volume_difference_m3": float(volume_series[-1]) - domain_volume,
    },
}
metrics_path.write_text(
    json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False),
    encoding="ascii",
)
'''


@dataclass(frozen=True)
class AnugaQualityPolicy:
    """Numerical and structural gates for an ANUGA 2D diagnostic run."""

    expected_cell_count: int
    expected_step_count: int
    expected_start_seconds: float
    expected_end_seconds: float
    maximum_absolute_mass_balance_residual_m3: float = 1.0e-8
    maximum_absolute_relative_mass_balance_error_percent: float = 1.0e-8
    minimum_allowed_depth_m: float = -1.0e-7
    maximum_output_domain_volume_difference_m3: float = 1.0e-5
    require_strictly_increasing_time: bool = True
    require_finite_state: bool = True
    require_positive_cell_areas: bool = True

    def __post_init__(self) -> None:
        if (
            not isinstance(self.expected_cell_count, int)
            or isinstance(self.expected_cell_count, bool)
            or self.expected_cell_count <= 0
            or not isinstance(self.expected_step_count, int)
            or isinstance(self.expected_step_count, bool)
            or self.expected_step_count <= 0
        ):
            raise ValueError("anuga_quality_expected_dimensions_invalid")
        numeric_values = (
            self.expected_start_seconds,
            self.expected_end_seconds,
            self.maximum_absolute_mass_balance_residual_m3,
            self.maximum_absolute_relative_mass_balance_error_percent,
            self.minimum_allowed_depth_m,
            self.maximum_output_domain_volume_difference_m3,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in numeric_values
        ):
            raise ValueError("anuga_quality_numeric_threshold_invalid")
        if (
            self.expected_end_seconds < self.expected_start_seconds
            or self.maximum_absolute_mass_balance_residual_m3 < 0.0
            or self.maximum_absolute_relative_mass_balance_error_percent < 0.0
            or self.maximum_output_domain_volume_difference_m3 < 0.0
        ):
            raise ValueError("anuga_quality_numeric_threshold_invalid")
        if any(
            not isinstance(value, bool)
            for value in (
                self.require_strictly_increasing_time,
                self.require_finite_state,
                self.require_positive_cell_areas,
            )
        ):
            raise ValueError("anuga_quality_flag_invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": ANUGA_QUALITY_POLICY_SCHEMA,
            "expected_cell_count": self.expected_cell_count,
            "expected_step_count": self.expected_step_count,
            "expected_start_seconds": float(self.expected_start_seconds),
            "expected_end_seconds": float(self.expected_end_seconds),
            "maximum_absolute_mass_balance_residual_m3": float(
                self.maximum_absolute_mass_balance_residual_m3
            ),
            "maximum_absolute_relative_mass_balance_error_percent": float(
                self.maximum_absolute_relative_mass_balance_error_percent
            ),
            "minimum_allowed_depth_m": float(self.minimum_allowed_depth_m),
            "maximum_output_domain_volume_difference_m3": float(
                self.maximum_output_domain_volume_difference_m3
            ),
            "require_strictly_increasing_time": self.require_strictly_increasing_time,
            "require_finite_state": self.require_finite_state,
            "require_positive_cell_areas": self.require_positive_cell_areas,
        }


def evaluate_anuga_quality(
    inspection: dict[str, Any],
    policy: AnugaQualityPolicy,
) -> dict[str, Any]:
    """Evaluate ANUGA output evidence without granting engineering admission."""

    if inspection.get("schema") != ANUGA_OUTPUT_INSPECTION_SCHEMA:
        raise ValueError("anuga_output_inspection_schema_invalid")
    mesh = inspection["mesh"]
    time_axis = inspection["time_axis"]
    state = inspection["state"]
    mass = inspection["mass_balance"]
    checks = [
        _check(
            "output_version_matches_runtime",
            inspection["output_attributes"]["anuga_version"]
            == inspection["solver"]["version"],
            inspection["output_attributes"]["anuga_version"],
            inspection["solver"]["version"],
        ),
        _check(
            "output_units_are_metres",
            inspection["output_attributes"]["units"] == "m",
            inspection["output_attributes"]["units"],
            "m",
        ),
        _check("cell_count_matches", mesh["cell_count"] == policy.expected_cell_count,
               mesh["cell_count"], policy.expected_cell_count),
        _check("step_count_matches", time_axis["step_count"] == policy.expected_step_count,
               time_axis["step_count"], policy.expected_step_count),
        _check(
            "start_time_matches",
            _close(time_axis["start_seconds"], policy.expected_start_seconds),
            time_axis["start_seconds"],
            policy.expected_start_seconds,
        ),
        _check("end_time_matches", _close(time_axis["end_seconds"], policy.expected_end_seconds),
               time_axis["end_seconds"], policy.expected_end_seconds),
        _check("time_strictly_increasing", not policy.require_strictly_increasing_time
               or time_axis["strictly_increasing"] is True,
               time_axis["strictly_increasing"], True),
        _check("topology_indices_valid", mesh["topology_indices_valid"] is True,
               mesh["topology_indices_valid"], True),
        _check("positive_finite_cell_areas", not policy.require_positive_cell_areas
               or mesh["positive_finite_cell_areas"] is True,
               mesh["positive_finite_cell_areas"], True),
        _check("all_required_values_finite", not policy.require_finite_state
               or state["all_required_values_finite"] is True,
               state["all_required_values_finite"], True),
        _check("minimum_depth_within_tolerance",
               state["minimum_depth_m"] >= policy.minimum_allowed_depth_m,
               state["minimum_depth_m"], policy.minimum_allowed_depth_m),
        _check("absolute_mass_balance_within_threshold",
               abs(mass["absolute_residual_m3"])
               <= policy.maximum_absolute_mass_balance_residual_m3,
               mass["absolute_residual_m3"],
               policy.maximum_absolute_mass_balance_residual_m3),
        _check("relative_mass_balance_within_threshold",
               abs(mass["relative_residual_percent"])
               <= policy.maximum_absolute_relative_mass_balance_error_percent,
               mass["relative_residual_percent"],
               policy.maximum_absolute_relative_mass_balance_error_percent),
        _check("output_and_domain_volume_consistent",
               abs(mass["output_domain_final_volume_difference_m3"])
               <= policy.maximum_output_domain_volume_difference_m3,
               mass["output_domain_final_volume_difference_m3"],
               policy.maximum_output_domain_volume_difference_m3),
    ]
    failed = [str(check["check_id"]) for check in checks if not check["passed"]]
    return {
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "admission_effect": "none_diagnostic_quality_only",
    }


def execute_anuga(
    request: TraditionalSolverRunRequest,
    *,
    source_root: Path,
    expected_source_commit: str,
    expected_source_diff_sha256: str,
    expected_source_status_sha256: str,
    output_filename: str,
    quality_policy: AnugaQualityPolicy,
    timeout_seconds: float = 120.0,
    retained_sww_path: Path | None = None,
) -> dict[str, Any]:
    """Run one explicit ANUGA script and validate its SWW output fail closed."""

    _validate_execute_arguments(
        request=request,
        expected_source_commit=expected_source_commit,
        expected_source_diff_sha256=expected_source_diff_sha256,
        expected_source_status_sha256=expected_source_status_sha256,
        output_filename=output_filename,
        quality_policy=quality_policy,
        timeout_seconds=timeout_seconds,
        retained_sww_path=retained_sww_path,
    )
    source_label = str(source_root)
    python_path = Path(request.executable_path).expanduser().absolute()
    model_script = Path(request.model_input_path).expanduser().resolve()
    source = Path(source_root).expanduser().resolve()
    _validate_runtime_paths(python_path, model_script, source)
    _validate_model_script(model_script)
    source_identity = _source_identity(source, source_label)
    _validate_source_identity(
        source_identity,
        expected_source_commit=expected_source_commit,
        expected_source_diff_sha256=expected_source_diff_sha256,
        expected_source_status_sha256=expected_source_status_sha256,
    )
    runtime_hash = _sha256_file(python_path.resolve())
    script_hash = _sha256_file(model_script)
    package_root = _resolve_anuga_package_root(python_path)
    package_artifact = _tree_artifact(package_root, "python-environment:anuga-package")
    runtime_artifact = artifact_descriptor(
        python_path.resolve(),
        sha256=runtime_hash,
        path_label=str(request.executable_path),
    )
    input_artifact = artifact_descriptor(
        model_script,
        sha256=script_hash,
        path_label=str(request.model_input_path),
    )
    run_contract = build_traditional_solver_run_contract(
        request,
        executable_artifact=runtime_artifact,
        input_artifact=input_artifact,
        quality_policy=quality_policy,
        runtime_dependency_artifacts=(package_artifact,),
    )
    runner_bytes = _RUNNER.encode("ascii")

    retained_path: Path | None = None
    retained_temporary: Path | None = None
    with tempfile.TemporaryDirectory(prefix="gwm-abu-dhabi-anuga-") as temporary_root:
        root = Path(temporary_root)
        isolated_script = root / "model.py"
        runner_path = root / "diagnostic_runner.py"
        output_path = root / output_filename
        metrics_path = root / "inspection.json"
        log_path = root / "model.log"
        shutil.copyfile(model_script, isolated_script)
        isolated_script.chmod(0o400)
        runner_path.write_bytes(runner_bytes)
        runner_path.chmod(0o400)
        if _sha256_file(isolated_script) != script_hash:
            raise TraditionalSolverExecutionError("anuga_input_copy_hash_mismatch")
        command = [
            str(python_path),
            "-I",
            runner_path.name,
            isolated_script.name,
            output_path.name,
            metrics_path.name,
            log_path.name,
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
                env={
                    "LANG": "C",
                    "LC_ALL": "C",
                    "PATH": "/usr/bin:/bin",
                    "PYTHONHASHSEED": "0",
                    "PYTHONNOUSERSITE": "1",
                    "TZ": "UTC",
                },
            )
        except subprocess.TimeoutExpired as error:
            raise TraditionalSolverExecutionError("anuga_execution_timeout") from error
        except OSError as error:
            raise TraditionalSolverExecutionError("anuga_execution_failed_to_start") from error
        elapsed_seconds = monotonic() - started
        if completed.returncode != 0:
            raise TraditionalSolverExecutionError(
                "anuga_execution_nonzero_exit",
                details={
                    "returncode": completed.returncode,
                    "stdout_sha256": _sha256_bytes(completed.stdout),
                    "stderr_sha256": _sha256_bytes(completed.stderr),
                },
            )
        _validate_output(metrics_path, _MAXIMUM_METRICS_BYTES, "inspection")
        _validate_output(log_path, _MAXIMUM_LOG_BYTES, "log")
        _validate_output(output_path, _MAXIMUM_SWW_BYTES, "sww")
        try:
            inspection = json.loads(metrics_path.read_text(encoding="ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise TraditionalSolverExecutionError("anuga_inspection_parse_failed") from error
        if inspection.get("schema") != ANUGA_OUTPUT_INSPECTION_SCHEMA:
            raise TraditionalSolverExecutionError("anuga_inspection_schema_invalid")
        if inspection["solver"]["version"] != request.expected_solver_version:
            raise TraditionalSolverExecutionError(
                "anuga_solver_version_mismatch",
                details={
                    "expected": request.expected_solver_version,
                    "observed": inspection["solver"]["version"],
                },
            )
        if inspection["output_attributes"]["revision_number"] != expected_source_commit:
            raise TraditionalSolverExecutionError("anuga_output_revision_mismatch")
        quality = evaluate_anuga_quality(inspection, quality_policy)
        if not quality["passed"]:
            raise TraditionalSolverExecutionError(
                "anuga_numerical_quality_gate_failed",
                details={"quality_gates": quality, "inspection": inspection},
            )
        output_artifacts = {
            "sww": artifact_descriptor(
                output_path,
                sha256=_sha256_file(output_path),
                path_label=f"isolated:{output_filename}",
            ),
            "log": artifact_descriptor(
                log_path,
                sha256=_sha256_file(log_path),
                path_label="isolated:model.log",
            ),
            "inspection": artifact_descriptor(
                metrics_path,
                sha256=_sha256_file(metrics_path),
                path_label="isolated:inspection.json",
            ),
        }
        if retained_sww_path is not None:
            retained_path = Path(retained_sww_path).expanduser().absolute()
            retained_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=retained_path.parent,
                prefix=f".{retained_path.name}.",
                delete=False,
            ) as handle:
                retained_temporary = Path(handle.name)
                with output_path.open("rb") as source_handle:
                    shutil.copyfileobj(source_handle, handle)
            if _sha256_file(retained_temporary) != output_artifacts["sww"]["sha256"]:
                retained_temporary.unlink(missing_ok=True)
                raise TraditionalSolverExecutionError("anuga_retained_sww_copy_hash_mismatch")

    try:
        if _sha256_file(python_path.resolve()) != runtime_hash:
            raise TraditionalSolverExecutionError("anuga_runtime_hash_changed_during_execution")
        if _sha256_file(model_script) != script_hash:
            raise TraditionalSolverExecutionError("anuga_input_hash_changed_during_execution")
        if _tree_artifact(package_root, "python-environment:anuga-package") != package_artifact:
            raise TraditionalSolverExecutionError("anuga_package_tree_changed_during_execution")
        if _source_identity(source, source_label) != source_identity:
            raise TraditionalSolverExecutionError("anuga_source_identity_changed_during_execution")
    except Exception:
        if retained_temporary is not None:
            retained_temporary.unlink(missing_ok=True)
        raise
    retained_artifact = None
    if retained_path is not None and retained_temporary is not None:
        os.replace(retained_temporary, retained_path)
        retained_artifact = artifact_descriptor(
            retained_path,
            sha256=_sha256_file(retained_path),
            path_label=str(retained_sww_path),
        )
    receipt: dict[str, Any] = {
        "schema": ANUGA_EXECUTION_RECEIPT_SCHEMA,
        "status": "completed_numerical_quality_passed_not_admitted",
        "run_contract": run_contract,
        "source_identity": source_identity,
        "runner_artifact": {
            "path": "generated:diagnostic_runner.py",
            "sha256": _sha256_bytes(runner_bytes),
            "size_bytes": len(runner_bytes),
        },
        "inspection": inspection,
        "quality_gates": quality,
        "execution": {
            "shell_used": False,
            "python_isolated_mode": True,
            "isolated_temporary_working_directory": True,
            "temporary_working_directory_retained": False,
            "input_copy_hash_verified": True,
            "runtime_hash_verified_before_and_after": True,
            "package_tree_verified_before_and_after": True,
            "source_identity_verified_before_and_after": True,
            "operating_system_filesystem_sandboxed": False,
            "network_namespace_isolated": False,
            "returncode": completed.returncode,
            "elapsed_seconds": round(elapsed_seconds, 6),
            "timeout_seconds": float(timeout_seconds),
            "stdout_sha256": _sha256_bytes(completed.stdout),
            "stderr_sha256": _sha256_bytes(completed.stderr),
            "output_artifacts": output_artifacts,
            "retained_sww_artifact": retained_artifact,
        },
        "admission": request.claim_boundary(),
    }
    receipt["receipt_sha256"] = _sha256_json(receipt)
    return receipt


def _validate_execute_arguments(**values: object) -> None:
    request = values["request"]
    if not isinstance(request, TraditionalSolverRunRequest):
        raise ValueError("anuga_run_request_invalid")
    if request.solver_id != "anuga_2d":
        raise ValueError("anuga_run_request_solver_invalid")
    source_commit = values["expected_source_commit"]
    if (
        not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(character not in "0123456789abcdef" for character in source_commit)
    ):
        raise ValueError("anuga_expected_source_commit_invalid")
    for name in ("expected_source_diff_sha256", "expected_source_status_sha256"):
        value = values[name]
        if not isinstance(value, str) or not _is_sha256(value):
            raise ValueError(f"anuga_{name}_invalid")
    output_filename = values["output_filename"]
    if (
        not isinstance(output_filename, str)
        or Path(output_filename).name != output_filename
        or not output_filename.endswith(".sww")
    ):
        raise ValueError("anuga_output_filename_invalid")
    if not isinstance(values["quality_policy"], AnugaQualityPolicy):
        raise ValueError("anuga_quality_policy_invalid")
    timeout = values["timeout_seconds"]
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0.0
    ):
        raise ValueError("anuga_timeout_invalid")
    retained_sww_path = values["retained_sww_path"]
    if retained_sww_path is not None and (
        not isinstance(retained_sww_path, Path)
        or retained_sww_path.suffix.lower() != ".sww"
        or retained_sww_path.name in {"", ".", ".."}
    ):
        raise ValueError("anuga_retained_sww_path_invalid")


def _validate_runtime_paths(python_path: Path, model_script: Path, source_root: Path) -> None:
    if not python_path.is_file() or not os.access(python_path, os.X_OK):
        raise ValueError("anuga_python_runtime_invalid")
    if (
        not model_script.is_file()
        or model_script.suffix.lower() != ".py"
        or model_script.stat().st_size <= 0
        or model_script.stat().st_size > _MAXIMUM_SCRIPT_BYTES
    ):
        raise ValueError("anuga_model_script_invalid")
    if not (source_root / ".git").exists():
        raise ValueError("anuga_source_root_invalid")


def _validate_model_script(path: Path) -> None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, SyntaxError) as error:
        raise ValueError("anuga_model_script_parse_failed") from error
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                raise ValueError("anuga_model_script_relative_import_forbidden")
            imported_roots.add(node.module.split(".", 1)[0])
    if imported_roots - {"anuga"}:
        raise ValueError("anuga_model_script_external_import_forbidden")


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
        "dirty_build_explicitly_fingerprinted": bool(status),
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
            "anuga_source_identity_mismatch",
            details={"observed": identity},
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
        raise TraditionalSolverExecutionError("anuga_source_identity_read_failed") from error
    if completed.returncode != 0:
        raise TraditionalSolverExecutionError("anuga_source_identity_read_failed")
    return completed.stdout


def _tree_artifact(root: Path, path_label: str) -> dict[str, object]:
    if not root.is_dir():
        raise ValueError("anuga_package_root_invalid")
    digest = hashlib.sha256()
    file_count = 0
    size_bytes = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        file_count += 1
        size_bytes += len(content)
    if file_count == 0 or size_bytes <= 0:
        raise ValueError("anuga_package_tree_empty")
    return {
        "path": path_label,
        "sha256": digest.hexdigest(),
        "size_bytes": size_bytes,
        "file_count": file_count,
        "algorithm": "sha256_sorted_relative_path_and_content_v1",
    }


def _resolve_anuga_package_root(python_path: Path) -> Path:
    candidates = tuple(
        sorted((python_path.parent.parent / "lib").glob("python*/site-packages/anuga"))
    )
    if len(candidates) != 1 or not candidates[0].is_dir():
        raise ValueError("anuga_package_root_invalid")
    return candidates[0]


def _validate_output(path: Path, maximum_bytes: int, label: str) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise TraditionalSolverExecutionError(f"anuga_{label}_missing_or_empty")
    if path.stat().st_size > maximum_bytes:
        raise TraditionalSolverExecutionError(f"anuga_{label}_exceeds_size_limit")


def _check(check_id: str, passed: bool, observed: object, threshold: object) -> dict[str, object]:
    return {
        "check_id": check_id,
        "passed": bool(passed),
        "observed": observed,
        "threshold_or_required": threshold,
    }


def _close(observed: object, expected: float) -> bool:
    return isinstance(observed, (int, float)) and math.isclose(
        float(observed), float(expected), rel_tol=0.0, abs_tol=1.0e-9
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


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
