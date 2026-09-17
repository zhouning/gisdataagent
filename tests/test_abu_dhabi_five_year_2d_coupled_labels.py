from __future__ import annotations

import sys
from datetime import datetime

import pytest

from scripts.run_abu_dhabi_five_year_2d_coupled_labels import (
    DEFAULT_IMPLEMENTATION_ROOT,
    REPOSITORY_ROOT,
    _normalize_swmm_elapsed_seconds,
    _render_event_input,
    _resolve_module_artifact,
)


def test_default_implementation_root_is_current_repository() -> None:
    assert DEFAULT_IMPLEMENTATION_ROOT == REPOSITORY_ROOT


def test_module_artifact_prefers_source(tmp_path) -> None:
    source = tmp_path / "module.py"
    bytecode = tmp_path / "__pycache__" / f"module.{sys.implementation.cache_tag}.pyc"
    bytecode.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    bytecode.write_bytes(b"cached")

    path, artifact_type = _resolve_module_artifact(tmp_path, "module")

    assert path == source
    assert artifact_type == "source"


def test_module_artifact_accepts_compatible_sourceless_bytecode(tmp_path) -> None:
    bytecode = tmp_path / "__pycache__" / f"module.{sys.implementation.cache_tag}.pyc"
    bytecode.parent.mkdir()
    bytecode.write_bytes(b"cached")

    path, artifact_type = _resolve_module_artifact(tmp_path, "module")

    assert path == bytecode
    assert artifact_type == "bytecode"


def test_render_event_input_uses_actual_event_start_time(tmp_path) -> None:
    base_input = tmp_path / "base.inp"
    base_input.write_text(
        "[OPTIONS]\nold\n[RAINGAGES]\nold\n[TIMESERIES]\nold\n[REPORT]\nold\n",
        encoding="ascii",
    )

    rendered, _ = _render_event_input(
        base_input,
        {
            "start_utc": datetime(2024, 3, 4, 18, 0),
            "hourly_precipitation_mm": (1.0, 2.0),
        },
    )

    assert "START_TIME  18:00:00" in rendered
    assert "REPORT_START_TIME  18:00:00" in rendered
    assert "END_TIME  20:00:00" in rendered
    assert "TS_ERA5  03/04/2024  18:00  1.00000000" in rendered


def test_swmm_elapsed_accepts_absolute_intermediate_time() -> None:
    elapsed, mode = _normalize_swmm_elapsed_seconds(
        300.0005,
        expected_end_seconds=300.0,
        duration_seconds=600.0,
    )

    assert elapsed == 300.0
    assert mode == "absolute_elapsed"


def test_swmm_elapsed_accepts_zero_only_as_terminal_sentinel() -> None:
    elapsed, mode = _normalize_swmm_elapsed_seconds(
        0.0,
        expected_end_seconds=600.0,
        duration_seconds=600.0,
    )

    assert elapsed == 600.0
    assert mode == "terminal_zero_sentinel"


def test_swmm_elapsed_rejects_early_zero() -> None:
    with pytest.raises(RuntimeError, match="five_year_2d_swmm_window_alignment_failed"):
        _normalize_swmm_elapsed_seconds(
            0.0,
            expected_end_seconds=300.0,
            duration_seconds=600.0,
        )


def test_swmm_elapsed_rejects_nonterminal_mismatch_with_diagnostics() -> None:
    with pytest.raises(RuntimeError, match="raw_elapsed_seconds=299.900000000"):
        _normalize_swmm_elapsed_seconds(
            299.9,
            expected_end_seconds=300.0,
            duration_seconds=600.0,
        )
