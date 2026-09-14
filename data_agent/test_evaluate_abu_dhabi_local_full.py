from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/evaluate_abu_dhabi_local_full.py"
SPEC = importlib.util.spec_from_file_location("evaluate_abu_dhabi_local_full", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_selected_sources_defaults_to_both_current_product_sources() -> None:
    assert MODULE.selected_sources(None) == (
        ("liveability", "benchmark"),
        ("makani", "customer_v4_benchmark"),
    )


def test_selected_sources_allows_an_independently_governed_source() -> None:
    assert MODULE.selected_sources(["liveability"]) == (("liveability", "benchmark"),)


def test_selected_sources_rejects_duplicate_or_unknown_scope() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        MODULE.selected_sources(["liveability", "liveability"])
    with pytest.raises(ValueError, match="unknown"):
        MODULE.selected_sources(["unknown"])


def test_selected_profiles_defaults_to_both_and_can_run_a_single_profile() -> None:
    assert MODULE.selected_profiles(None) == (
        "baseline_sql",
        "semantic_ir_experimental",
    )
    assert MODULE.selected_profiles(["semantic_ir_experimental"]) == (
        "semantic_ir_experimental",
    )


def test_selected_profiles_rejects_duplicate_or_unknown_scope() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        MODULE.selected_profiles(["baseline_sql", "baseline_sql"])
    with pytest.raises(ValueError, match="unknown"):
        MODULE.selected_profiles(["unknown"])
