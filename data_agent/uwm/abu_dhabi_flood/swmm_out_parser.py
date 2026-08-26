"""Read native EPA SWMM 5.x binary output files.

The interactive map uses this reader for time slices.  It intentionally reads
the native ``.out`` file produced by SWMM rather than rebuilding a time series
from the RPT maxima or interpolating values in the browser.
"""

from __future__ import annotations

import struct
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_INT = struct.Struct("<i")
_HEADER = struct.Struct("<7i")
_EPILOGUE = struct.Struct("<6i")
_PERIOD_DATE = struct.Struct("<d")
_SWMM_EPOCH = datetime(1899, 12, 30)


def _read_int(handle: Any) -> int:
    value = handle.read(4)
    if len(value) != 4:
        raise ValueError("swmm_out_truncated_integer")
    return _INT.unpack(value)[0]


def _timestamp(value: float) -> datetime:
    if not value == value or abs(value) == float("inf"):
        raise ValueError("swmm_out_timestamp_invalid")
    return _SWMM_EPOCH + timedelta(days=float(value))


def read_swmm_out_header(path: Path) -> dict[str, Any]:
    """Read the SWMM output header and object names without loading results."""

    source = path.expanduser().resolve()
    if not source.is_file():
        raise ValueError("swmm_out_missing")
    file_size = source.stat().st_size
    if file_size < 24 + 28:
        raise ValueError("swmm_out_too_small")
    with source.open("rb") as handle:
        handle.seek(-24, 2)
        id_pos, object_prop_pos, results_pos, periods, error_code, magic_end = _EPILOGUE.unpack(
            handle.read(24)
        )
        handle.seek(0)
        magic, version, flow_units, n_subcatch, n_nodes, n_links, n_polluts = _HEADER.unpack(
            handle.read(28)
        )
        if magic != magic_end:
            raise ValueError("swmm_out_magic_mismatch")
        if periods <= 0:
            raise ValueError("swmm_out_no_periods")
        if error_code != 0:
            # The binary remains readable, but callers should see that SWMM
            # recorded an execution error in its output epilogue.
            warning = f"swmm_error_code_{error_code}"
        else:
            warning = None

        variable_offset = object_prop_pos + 4 * (
            (n_subcatch + 2) + (3 * n_nodes + 4) + (5 * n_links + 6)
        )
        handle.seek(variable_offset)
        n_subcatch_vars = _read_int(handle)
        handle.seek(4 * n_subcatch_vars, 1)
        n_node_vars = _read_int(handle)
        handle.seek(4 * n_node_vars, 1)
        n_link_vars = _read_int(handle)
        handle.seek(4 * n_link_vars, 1)
        n_system_vars = _read_int(handle)

        handle.seek(results_pos - 12)
        start_date_value = _PERIOD_DATE.unpack(handle.read(8))[0]
        report_step_seconds = _read_int(handle)
        start_date = _timestamp(start_date_value)

        bytes_per_period = 8 + 4 * (
            n_subcatch * n_subcatch_vars
            + n_nodes * n_node_vars
            + n_links * n_link_vars
            + n_system_vars
        )
        expected_end = results_pos + periods * bytes_per_period + 24
        if expected_end != file_size:
            raise ValueError("swmm_out_size_mismatch")

        handle.seek(id_pos)
        names: list[str] = []
        for _ in range(n_subcatch + n_nodes + n_links + n_polluts):
            length = _read_int(handle)
            if length < 0 or length > 4096:
                raise ValueError("swmm_out_element_name_invalid")
            raw = handle.read(length)
            if len(raw) != length:
                raise ValueError("swmm_out_truncated_element_name")
            names.append(raw.decode("utf-8", errors="replace"))

    node_names = names[n_subcatch:n_subcatch + n_nodes]
    return {
        "path": str(source),
        "version": version,
        "flow_units": flow_units,
        "n_subcatchments": n_subcatch,
        "n_nodes": n_nodes,
        "n_links": n_links,
        "n_pollutants": n_polluts,
        "n_subcatch_vars": n_subcatch_vars,
        "n_node_vars": n_node_vars,
        "n_link_vars": n_link_vars,
        "n_system_vars": n_system_vars,
        "period_count": periods,
        "report_step_seconds": report_step_seconds,
        "start_time": start_date.isoformat(timespec="seconds"),
        "node_names": node_names,
        "results_pos": results_pos,
        "bytes_per_period": bytes_per_period,
        "warning": warning,
    }


def read_node_period(path: Path, header: dict[str, Any], time_index: int) -> dict[str, Any]:
    """Read one native SWMM reporting period of node results.

    SWMM node attributes are ordered as depth, hydraulic head, stored volume,
    lateral inflow, total inflow, and flooding losses for this model output.
    """

    if isinstance(time_index, bool) or not isinstance(time_index, int):
        raise ValueError("swmm_out_time_index_invalid")
    period_count = int(header["period_count"])
    if time_index < 0 or time_index >= period_count:
        raise ValueError("swmm_out_time_index_out_of_range")
    n_subcatch = int(header["n_subcatchments"])
    n_subcatch_vars = int(header["n_subcatch_vars"])
    n_nodes = int(header["n_nodes"])
    n_node_vars = int(header["n_node_vars"])
    offset = int(header["results_pos"]) + time_index * int(header["bytes_per_period"])
    node_offset = 8 + n_subcatch * n_subcatch_vars * 4
    node_bytes = n_nodes * n_node_vars * 4
    with Path(header["path"]).open("rb") as handle:
        handle.seek(offset)
        date_bytes = handle.read(8)
        if len(date_bytes) != 8:
            raise ValueError("swmm_out_period_timestamp_missing")
        date_value = _PERIOD_DATE.unpack(date_bytes)[0]
        handle.seek(offset + node_offset)
        raw = handle.read(node_bytes)
        if len(raw) != node_bytes:
            raise ValueError("swmm_out_node_period_truncated")
    values = struct.unpack(f"<{n_nodes * n_node_vars}f", raw)
    timestamp = _timestamp(date_value)
    model_start = datetime.fromisoformat(str(header["start_time"]))
    nodes = [
        values[position * n_node_vars:(position + 1) * n_node_vars]
        for position in range(n_nodes)
    ]
    return {
        "time_index": time_index,
        "timestamp": timestamp.isoformat(timespec="seconds"),
        "elapsed_minutes": round((timestamp - model_start).total_seconds() / 60.0, 3),
        "nodes": nodes,
    }


def timeline_from_header(header: dict[str, Any]) -> dict[str, Any]:
    """Return JSON-safe timeline metadata from a parsed header."""

    start = datetime.fromisoformat(str(header["start_time"]))
    step = int(header["report_step_seconds"])
    values = [
        start + timedelta(seconds=step * (index + 1))
        for index in range(int(header["period_count"]))
    ]
    start_time = values[0].isoformat(timespec="seconds") if values else start.isoformat(
        timespec="seconds"
    )
    end_time = values[-1].isoformat(timespec="seconds") if values else start.isoformat(
        timespec="seconds"
    )
    return {
        "available": True,
        "source": "native SWMM OUT binary reporting periods",
        "start_time": start_time,
        "end_time": end_time,
        "step_minutes": step / 60.0,
        "period_count": int(header["period_count"]),
        "time_values": [value.isoformat(timespec="seconds") for value in values],
        "elapsed_minutes": [round((value - start).total_seconds() / 60.0, 3) for value in values],
    }
