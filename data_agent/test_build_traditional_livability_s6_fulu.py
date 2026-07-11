from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

from data_agent.test_traditional_livability_facility_dictionary import (
    dictionary_fixture,
    matrix_fixture,
)
from data_agent.test_traditional_livability_s6_fulu_adapter import (
    _facility_product,
    _planning_fixture_root,
    _specs,
)
from data_agent.uwm import traditional_livability_s6_fulu_adapter as adapter


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_traditional_livability_s6_fulu.py"
SPEC = importlib.util.spec_from_file_location("build_traditional_livability_s6_fulu", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


OUTPUT_FILES = {
    "uwm_traditional_livability_s6_resources.json",
    "uwm_traditional_livability_s6_dictionary.json",
    "uwm_traditional_livability_s6_compatibility.json",
    "uwm_traditional_livability_s6_build_manifest.json",
}


def test_builder_fails_closed_without_required_planning_sources(tmp_path):
    output = tmp_path / "out"

    result = MODULE.build_s6_fulu(
        source_root=tmp_path,
        facility_product=_facility_product(),
        output_dir=output,
    )

    assert result["ready"] is False
    assert result["exit_code"] == 2
    assert any(blocker.startswith("missing_required_source:") for blocker in result["blockers"])
    assert not output.exists()


def test_builder_fails_closed_without_required_facility_product(tmp_path):
    result = MODULE.build_s6_fulu(
        source_root=tmp_path,
        facility_product=None,
        output_dir=tmp_path / "out",
    )

    assert result == {
        "ready": False,
        "exit_code": 2,
        "blockers": ["facility_product_missing"],
    }


def test_builder_writes_atomic_public_snapshots_with_unavailable_authority(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    monkeypatch.setattr(MODULE.s6_adapter, "ASSET_SPECS", _specs())
    source_root = _planning_fixture_root(tmp_path / "sources")
    facility_product = _facility_product()
    facility_product["source_manifest"]["source_root"] = str(source_root)
    facility_product["source_manifest"]["sources"][0]["absolute_path"] = str(
        source_root / "poi" / "gaode.gpkg"
    )
    output = tmp_path / "out"
    replacements = []
    real_replace = os.replace

    def recording_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(MODULE.os, "replace", recording_replace)

    result = MODULE.build_s6_fulu(
        source_root=source_root,
        facility_product=facility_product,
        output_dir=output,
    )

    assert result["ready"] is True
    assert result["exit_code"] == 0
    assert {path.name for path in output.iterdir()} == OUTPUT_FILES
    assert {destination.name for _, destination in replacements} == OUTPUT_FILES
    assert all(source.name.endswith(".tmp") for source, _ in replacements)
    assert not list(output.glob("*.tmp"))

    payloads = {
        filename: json.loads((output / filename).read_text(encoding="utf-8"))
        for filename in OUTPUT_FILES
    }
    serialized = json.dumps(payloads, ensure_ascii=False)
    assert str(source_root) not in serialized

    resources = payloads["uwm_traditional_livability_s6_resources.json"]
    assert resources["scope"] == "fulu_heping_and_banzhu_planning_samples_only"
    assert resources["facility_inventory"]["complete_inventory"] is False

    dictionary = payloads["uwm_traditional_livability_s6_dictionary.json"]
    compatibility = payloads["uwm_traditional_livability_s6_compatibility.json"]
    assert dictionary["status"] == "dictionary_unavailable"
    assert dictionary["ready"] is False
    assert compatibility["status"] == "compatibility_matrix_unavailable"
    assert compatibility["ready"] is False

    manifest = payloads["uwm_traditional_livability_s6_build_manifest.json"]
    assert manifest["scope"] == "fulu_heping_and_banzhu_planning_samples_only"
    assert manifest["spatial_screening_ready"] is True
    assert manifest["facility_inventory_complete"] is False
    assert manifest["planning_resource_count"] == len(resources["planning_resources"])
    assert manifest["planning_resource_unresolved_count"] == 2
    assert manifest["current_facility_count"] == len(resources["current_facilities"])
    assert manifest["current_facility_unresolved_count"] == 1
    assert manifest["planning_area_count"] == 2
    assert {row["planning_area_id"] for row in manifest["planning_coverage"]} == {
        "fulu_heping",
        "fulu_banzhu",
    }
    assert all(row["distance_crs"] for row in manifest["planning_coverage"])


def test_builder_validates_optional_dictionary_and_matrix(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    monkeypatch.setattr(MODULE.s6_adapter, "ASSET_SPECS", _specs())
    source_root = _planning_fixture_root(tmp_path / "sources")
    output = tmp_path / "out"

    result = MODULE.build_s6_fulu(
        source_root=source_root,
        facility_product=_facility_product(),
        output_dir=output,
        facility_dictionary=dictionary_fixture(),
        compatibility_matrix=matrix_fixture(),
    )

    assert result["ready"] is True
    dictionary = json.loads(
        (output / "uwm_traditional_livability_s6_dictionary.json").read_text(
            encoding="utf-8"
        )
    )
    compatibility = json.loads(
        (output / "uwm_traditional_livability_s6_compatibility.json").read_text(
            encoding="utf-8"
        )
    )
    assert dictionary["ready"] is True
    assert dictionary["class_count"] == 43
    assert compatibility["ready"] is True
    assert compatibility["rules"][0]["rule_id"] == "fixture-rule-001"


def test_cli_returns_exit_2_for_missing_required_facility_product(tmp_path, capsys):
    exit_code = MODULE.main(
        [
            "--source-root",
            str(tmp_path),
            "--facility-product",
            str(tmp_path / "missing.json"),
            "--output",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["blockers"] == ["facility_product_missing"]


def test_builder_help_runs_from_repository_checkout():
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=SCRIPT.parents[1],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--facility-dictionary" in completed.stdout
    assert "--compatibility-matrix" in completed.stdout
