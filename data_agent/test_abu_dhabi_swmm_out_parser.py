from __future__ import annotations

import struct
from datetime import datetime
from pathlib import Path

import pytest

from data_agent.uwm.abu_dhabi_flood.swmm_out_parser import (
    read_node_period,
    read_swmm_out_header,
    timeline_from_header,
)


def _write_fixture(path: Path) -> None:
    n_subcatch, n_nodes, n_links, n_polluts = 1, 2, 1, 0
    subcatch_vars, node_vars, link_vars, system_vars = 1, 6, 5, 15
    names = [b"s1", b"n1", b"n2", b"l1"]
    header = struct.pack("<7i", 516114522, 52004, 3, n_subcatch, n_nodes, n_links, n_polluts)
    id_pos = len(header)
    ids = b"".join(struct.pack("<i", len(name)) + name for name in names)
    object_prop_pos = id_pos + len(ids)
    property_words = (n_subcatch + 2) + (3 * n_nodes + 4) + (5 * n_links + 6)
    variables = struct.pack("<i", subcatch_vars) + struct.pack("<i", 0)
    variables += struct.pack("<i", node_vars) + struct.pack("<6i", *range(6))
    variables += struct.pack("<i", link_vars) + struct.pack("<5i", *range(5))
    variables += struct.pack("<i", system_vars) + struct.pack("<15i", *range(15))
    results_pos = object_prop_pos + property_words * 4 + len(variables) + 12
    start_date = (datetime(1899, 12, 30), datetime(2024, 4, 16))
    start_value = (start_date[1] - start_date[0]).total_seconds() / 86400
    period_count = 2
    period_bytes = 8 + 4 * (n_subcatch * subcatch_vars + n_nodes * node_vars + n_links * link_vars + system_vars)
    results = bytearray()
    for period in range(period_count):
        results.extend(struct.pack("<d", start_value + (period + 1) * 300 / 86400))
        values = [0.0] * (n_subcatch * subcatch_vars + n_nodes * node_vars + n_links * link_vars + system_vars)
        values[1] = 0.1 + period * 0.2  # n1 depth
        values[1 + 5] = 0.02 * period  # n1 flooding losses
        values[7] = 0.3 + period * 0.1  # n2 depth
        results.extend(struct.pack(f"<{len(values)}f", *values))
    epilogue = struct.pack("<6i", id_pos, object_prop_pos, results_pos, period_count, 0, 516114522)
    path.write_bytes(header + ids + (b"\0" * property_words * 4) + variables + struct.pack("<di", start_value, 300) + results + epilogue)
    assert results_pos + period_count * period_bytes + 24 == path.stat().st_size


def test_native_swmm_out_header_and_period_are_read(tmp_path: Path):
    path = tmp_path / "fixture.out"
    _write_fixture(path)
    header = read_swmm_out_header(path)
    assert header["version"] == 52004
    assert header["node_names"] == ["n1", "n2"]
    assert header["period_count"] == 2
    assert header["report_step_seconds"] == 300
    period = read_node_period(path, header, 1)
    assert period["timestamp"] == "2024-04-16T00:10:00"
    assert period["elapsed_minutes"] == 10.0
    assert period["nodes"][0][0] == pytest.approx(0.3)
    assert period["nodes"][0][5] == pytest.approx(0.02)
    timeline = timeline_from_header(header)
    assert timeline["time_values"] == ["2024-04-16T00:05:00", "2024-04-16T00:10:00"]
