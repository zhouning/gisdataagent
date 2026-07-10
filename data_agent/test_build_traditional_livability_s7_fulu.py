import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_traditional_livability_s7_fulu.py"
SPEC = importlib.util.spec_from_file_location("build_s7", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_builder_fails_closed_without_planning_sources(tmp_path):
    result = MODULE.build_s7_fulu(source_root=tmp_path, facility_product={"facilities": []}, output_dir=tmp_path / "out", coverage_distance_m=1500, max_sites=3)
    assert result["ready"] is False
    assert not (tmp_path / "out" / "uwm_traditional_livability_s7.json").exists()


def test_builder_help_runs_from_checkout():
    import subprocess, sys
    completed = subprocess.run([sys.executable, str(SCRIPT), "--help"], cwd=SCRIPT.parents[1], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert "--coverage-distance-m" in completed.stdout
