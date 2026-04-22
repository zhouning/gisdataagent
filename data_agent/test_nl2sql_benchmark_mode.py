"""Smoke tests for run_cq_eval.py enhanced mode helpers."""
import importlib.util
from pathlib import Path


def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_run_cq_eval_has_enhanced_mode_constant():
    mod = _load_module(
        str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_cq" / "run_cq_eval.py"),
        "run_cq_eval_mod",
    )
    assert hasattr(mod, "PROMPT_ENHANCED")
