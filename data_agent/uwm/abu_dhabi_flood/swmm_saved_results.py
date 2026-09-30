"""Read selected EPA SWMM saved states through the official solver API."""

from __future__ import annotations

import ctypes
import hashlib
import math
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

SWMM_SAVED_RESULT_SCHEMA = "gwm.abu_dhabi_flood.swmm_saved_results.v1"

SWMM_NODE = 2
SWMM_LINK = 3
SWMM_START_DATE = 0
SWMM_CURRENT_DATE = 1
SWMM_TOTAL_STEPS = 6
SWMM_FLOW_UNITS = 8
SWMM_NODE_PROPERTIES = (
    ("water_depth_m", 303),
    ("hydraulic_head_m", 304),
    ("stored_volume_m3", 305),
    ("lateral_inflow_m3s", 306),
    ("total_inflow_m3s", 307),
    ("overflow_or_flooding_m3s", 308),
)
SWMM_LINK_PROPERTIES = (
    ("flow_m3s", 410),
    ("water_depth_m", 411),
    ("velocity_ms", 412),
    ("capacity_fraction", 407),
)
_EXPECTED_VERSION = 52004
_API_LOCK = threading.Lock()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_library(path: Path) -> Any:
    library = ctypes.CDLL(str(path))
    library.swmm_open.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
    library.swmm_open.restype = ctypes.c_int
    library.swmm_start.argtypes = [ctypes.c_int]
    library.swmm_start.restype = ctypes.c_int
    library.swmm_step.argtypes = [ctypes.POINTER(ctypes.c_double)]
    library.swmm_step.restype = ctypes.c_int
    library.swmm_end.argtypes = []
    library.swmm_end.restype = ctypes.c_int
    library.swmm_report.argtypes = []
    library.swmm_report.restype = ctypes.c_int
    library.swmm_close.argtypes = []
    library.swmm_close.restype = ctypes.c_int
    library.swmm_getVersion.argtypes = []
    library.swmm_getVersion.restype = ctypes.c_int
    library.swmm_getError.argtypes = [ctypes.c_char_p, ctypes.c_int]
    library.swmm_getError.restype = ctypes.c_int
    library.swmm_getCount.argtypes = [ctypes.c_int]
    library.swmm_getCount.restype = ctypes.c_int
    library.swmm_getIndex.argtypes = [ctypes.c_int, ctypes.c_char_p]
    library.swmm_getIndex.restype = ctypes.c_int
    library.swmm_getValue.argtypes = [ctypes.c_int, ctypes.c_int]
    library.swmm_getValue.restype = ctypes.c_double
    library.swmm_getSavedValue.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    library.swmm_getSavedValue.restype = ctypes.c_double
    return library


def _error_message(library: Any, code: int) -> str:
    buffer = ctypes.create_string_buffer(1024)
    library.swmm_getError(buffer, len(buffer))
    message = buffer.value.decode("utf-8", errors="replace").strip()
    return message or f"EPA SWMM error {code}"


def _check(code: int, library: Any, operation: str) -> None:
    if code != 0:
        raise RuntimeError(f"swmm_saved_results_{operation}_failed:{_error_message(library, code)}")


def _indices(library: Any, object_type: int, names: tuple[str, ...]) -> list[int]:
    indexes = []
    for name in names:
        if not isinstance(name, str) or not name or not name.isascii():
            raise ValueError("swmm_saved_results_ascii_element_name_required")
        index = int(library.swmm_getIndex(object_type, name.encode("ascii")))
        if index < 0:
            raise ValueError("swmm_saved_results_requested_element_missing")
        indexes.append(index)
    if len(set(indexes)) != len(indexes):
        raise ValueError("swmm_saved_results_requested_element_not_unique")
    return indexes


def execute_swmm_saved_results(
    *,
    library_path: Path,
    model_input_path: Path,
    node_names: tuple[str, ...],
    link_names: tuple[str, ...],
    timeout_step_limit: int = 10_000_000,
) -> dict[str, Any]:
    """Execute one isolated model and return selected, ordered state arrays."""

    import numpy as np

    library_source = library_path.expanduser().resolve()
    input_source = model_input_path.expanduser().resolve()
    if not library_source.is_file():
        raise ValueError("swmm_saved_results_library_missing")
    if not input_source.is_file():
        raise ValueError("swmm_saved_results_input_missing")
    if (
        isinstance(timeout_step_limit, bool)
        or not isinstance(timeout_step_limit, int)
        or timeout_step_limit < 1
    ):
        raise ValueError("swmm_saved_results_step_limit_invalid")
    with _API_LOCK, tempfile.TemporaryDirectory(prefix="gwm-swmm-saved-") as temporary:
        workspace = Path(temporary)
        library_copy = workspace / library_source.name
        input_copy = workspace / "model.inp"
        report_path = workspace / "model.rpt"
        output_path = workspace / "model.out"
        shutil.copyfile(library_source, library_copy)
        shutil.copyfile(input_source, input_copy)
        if _sha256_file(library_copy) != _sha256_file(library_source):
            raise RuntimeError("swmm_saved_results_library_copy_hash_mismatch")
        if _sha256_file(input_copy) != _sha256_file(input_source):
            raise RuntimeError("swmm_saved_results_input_copy_hash_mismatch")
        library = _load_library(library_copy)
        opened = False
        started = False
        try:
            version = int(library.swmm_getVersion())
            if version != _EXPECTED_VERSION:
                raise ValueError("swmm_saved_results_version_mismatch")
            _check(
                library.swmm_open(
                    str(input_copy).encode(),
                    str(report_path).encode(),
                    str(output_path).encode(),
                ),
                library,
                "open",
            )
            opened = True
            if int(library.swmm_getValue(SWMM_FLOW_UNITS, 0)) != 3:
                raise ValueError("swmm_saved_results_flow_units_must_be_cms")
            start_date = float(library.swmm_getValue(SWMM_START_DATE, 0))
            if not math.isfinite(start_date):
                raise RuntimeError("swmm_saved_results_start_date_invalid")
            node_indexes = _indices(library, SWMM_NODE, node_names)
            link_indexes = _indices(library, SWMM_LINK, link_names)
            _check(library.swmm_start(1), library, "start")
            started = True
            elapsed = ctypes.c_double(0.0)
            step_count = 0
            while True:
                _check(library.swmm_step(ctypes.byref(elapsed)), library, "step")
                step_count += 1
                if not math.isfinite(elapsed.value) or elapsed.value < 0.0:
                    raise RuntimeError("swmm_saved_results_elapsed_time_invalid")
                if elapsed.value <= 0.0:
                    break
                if step_count >= timeout_step_limit:
                    raise TimeoutError("swmm_saved_results_step_limit_exceeded")
            _check(library.swmm_end(), library, "end")
            started = False
            _check(library.swmm_report(), library, "report")
            period_count = int(library.swmm_getValue(SWMM_TOTAL_STEPS, 0))
            if period_count < 1:
                raise RuntimeError("swmm_saved_results_no_reporting_periods")
            timestamps = np.asarray(
                [
                    library.swmm_getSavedValue(SWMM_CURRENT_DATE, 0, period)
                    for period in range(1, period_count + 1)
                ],
                dtype="float64",
            )
            if not np.isfinite(timestamps).all() or np.any(np.diff(timestamps) <= 0.0):
                raise RuntimeError("swmm_saved_results_timestamps_invalid")
            timestamp_seconds = np.rint((timestamps - start_date) * 86400.0).astype(
                "int64"
            )
            if timestamp_seconds[0] <= 0 or np.any(np.diff(timestamp_seconds) <= 0):
                raise RuntimeError("swmm_saved_results_elapsed_timestamps_invalid")
            node_state = np.empty(
                (period_count, len(node_indexes), len(SWMM_NODE_PROPERTIES)),
                dtype="float32",
            )
            link_state = np.empty(
                (period_count, len(link_indexes), len(SWMM_LINK_PROPERTIES)),
                dtype="float32",
            )
            for period_position, period in enumerate(range(1, period_count + 1)):
                for element_position, index in enumerate(node_indexes):
                    for channel_position, (_, property_code) in enumerate(
                        SWMM_NODE_PROPERTIES
                    ):
                        node_state[period_position, element_position, channel_position] = (
                            library.swmm_getSavedValue(property_code, index, period)
                        )
                for element_position, index in enumerate(link_indexes):
                    for channel_position, (_, property_code) in enumerate(
                        SWMM_LINK_PROPERTIES
                    ):
                        link_state[period_position, element_position, channel_position] = (
                            library.swmm_getSavedValue(property_code, index, period)
                        )
            if not np.isfinite(node_state).all() or not np.isfinite(link_state).all():
                raise RuntimeError("swmm_saved_results_nonfinite_state")
            report_text = report_path.read_text(encoding="utf-8", errors="replace")
            return {
                "schema": SWMM_SAVED_RESULT_SCHEMA,
                "solver_version": "5.2.4",
                "runtime_sha256": _sha256_file(library_source),
                "model_input_sha256": _sha256_file(input_source),
                "step_count": step_count,
                "period_count": period_count,
                "timestamp_seconds_since_model_start": timestamp_seconds,
                "node_state": node_state,
                "link_state": link_state,
                "node_channel_names": [name for name, _ in SWMM_NODE_PROPERTIES],
                "link_channel_names": [name for name, _ in SWMM_LINK_PROPERTIES],
                "report_text": report_text,
                "execution": {
                    "isolated_temporary_working_directory": True,
                    "temporary_working_directory_retained": False,
                    "input_copy_hash_verified": True,
                    "library_copy_hash_verified": True,
                    "shell_used": False,
                    "absolute_paths_persisted": False,
                },
            }
        finally:
            if started:
                library.swmm_end()
            if opened:
                library.swmm_close()
