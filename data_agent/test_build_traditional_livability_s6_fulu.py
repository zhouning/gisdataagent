from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

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


@pytest.mark.parametrize(
    "facility_product",
    [
        [],
        {},
        {**_facility_product(), "schema": "wrong.schema"},
        {**_facility_product(), "facilities": {}},
        {**_facility_product(), "facilities": [None]},
        {**_facility_product(), "source_manifest": []},
        {
            **_facility_product(),
            "source_manifest": {
                **_facility_product()["source_manifest"],
                "schema": "wrong.manifest.schema",
            },
        },
        {
            **_facility_product(),
            "source_manifest": {
                **_facility_product()["source_manifest"],
                "sources": {},
            },
        },
        {
            **_facility_product(),
            "source_manifest": {
                **_facility_product()["source_manifest"],
                "sources": [None],
            },
        },
        {
            **_facility_product(),
            "source_manifest": {
                **_facility_product()["source_manifest"],
                "complete_inventory": "false",
            },
        },
    ],
)
def test_builder_rejects_malformed_required_facility_products(
    tmp_path, facility_product
):
    result = MODULE.build_s6_fulu(
        source_root=tmp_path,
        facility_product=facility_product,
        output_dir=tmp_path / "out",
    )

    assert result == {
        "ready": False,
        "exit_code": 2,
        "blockers": ["facility_product_invalid"],
    }
    assert not (tmp_path / "out").exists()


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


@pytest.mark.parametrize(
    ("keyword", "blocker", "snapshot"),
    [
        (
            "facility_dictionary",
            "facility_dictionary_invalid",
            "uwm_traditional_livability_s6_dictionary.json",
        ),
        (
            "compatibility_matrix",
            "compatibility_matrix_invalid",
            "uwm_traditional_livability_s6_compatibility.json",
        ),
    ],
)
def test_builder_rejects_explicit_schema_invalid_authority_payloads(
    tmp_path, monkeypatch, keyword, blocker, snapshot
):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    monkeypatch.setattr(MODULE.s6_adapter, "ASSET_SPECS", _specs())
    source_root = _planning_fixture_root(tmp_path / "sources")
    output = tmp_path / "out"

    result = MODULE.build_s6_fulu(
        source_root=source_root,
        facility_product=_facility_product(),
        output_dir=output,
        **{keyword: {}},
    )

    assert result["ready"] is False
    assert result["exit_code"] == 2
    assert result["blockers"] == [blocker]
    payload = json.loads((output / snapshot).read_text(encoding="utf-8"))
    assert payload["ready"] is False


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_builder_rejects_non_finite_snapshot_values_without_partial_files(
    tmp_path, monkeypatch, non_finite
):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    monkeypatch.setattr(MODULE.s6_adapter, "ASSET_SPECS", _specs())
    source_root = _planning_fixture_root(tmp_path / "sources")
    facility_product = _facility_product()
    facility_product["source_manifest"]["non_finite_fixture"] = non_finite
    output = tmp_path / "out"

    result = MODULE.build_s6_fulu(
        source_root=source_root,
        facility_product=facility_product,
        output_dir=output,
    )

    assert result == {
        "ready": False,
        "exit_code": 2,
        "blockers": ["snapshot_serialization_failed"],
    }
    assert not output.exists() or not list(output.iterdir())


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


@pytest.mark.parametrize("facility_product", [{}, {"schema": "wrong.schema"}])
def test_cli_returns_exit_2_for_invalid_required_facility_product(
    tmp_path, capsys, facility_product
):
    facility_path = tmp_path / "facility.json"
    facility_path.write_text(json.dumps(facility_product), encoding="utf-8")

    exit_code = MODULE.main(
        [
            "--source-root",
            str(tmp_path),
            "--facility-product",
            str(facility_path),
            "--output",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["blockers"] == ["facility_product_invalid"]


def test_cli_returns_exit_2_for_malformed_required_facility_json(tmp_path, capsys):
    facility_path = tmp_path / "facility.json"
    facility_path.write_text("{not-json", encoding="utf-8")

    exit_code = MODULE.main(
        [
            "--source-root",
            str(tmp_path),
            "--facility-product",
            str(facility_path),
            "--output",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["blockers"] == ["facility_product_invalid"]


@pytest.mark.parametrize(
    ("option", "filename", "contents", "blocker", "snapshot", "status"),
    [
        (
            "--facility-dictionary",
            "missing-dictionary.json",
            None,
            "facility_dictionary_missing",
            "uwm_traditional_livability_s6_dictionary.json",
            "dictionary_input_missing",
        ),
        (
            "--compatibility-matrix",
            "missing-matrix.json",
            None,
            "compatibility_matrix_missing",
            "uwm_traditional_livability_s6_compatibility.json",
            "compatibility_matrix_input_missing",
        ),
        (
            "--facility-dictionary",
            "malformed-dictionary.json",
            "{not-json",
            "facility_dictionary_malformed_json",
            "uwm_traditional_livability_s6_dictionary.json",
            "dictionary_input_malformed_json",
        ),
        (
            "--compatibility-matrix",
            "malformed-matrix.json",
            "{not-json",
            "compatibility_matrix_malformed_json",
            "uwm_traditional_livability_s6_compatibility.json",
            "compatibility_matrix_input_malformed_json",
        ),
    ],
)
def test_cli_returns_structured_failure_for_invalid_optional_authority_files(
    tmp_path,
    monkeypatch,
    capsys,
    option,
    filename,
    contents,
    blocker,
    snapshot,
    status,
):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    monkeypatch.setattr(MODULE.s6_adapter, "ASSET_SPECS", _specs())
    source_root = _planning_fixture_root(tmp_path / "sources")
    facility_path = tmp_path / "facility.json"
    facility_path.write_text(json.dumps(_facility_product()), encoding="utf-8")
    authority_path = tmp_path / filename
    if contents is not None:
        authority_path.write_text(contents, encoding="utf-8")
    output = tmp_path / "out"

    exit_code = MODULE.main(
        [
            "--source-root",
            str(source_root),
            "--facility-product",
            str(facility_path),
            "--output",
            str(output),
            option,
            str(authority_path),
        ]
    )

    assert exit_code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["blockers"] == [blocker]
    payload = json.loads((output / snapshot).read_text(encoding="utf-8"))
    assert payload["ready"] is False
    assert payload["status"] == status


@pytest.mark.parametrize(
    ("option", "prefix", "blocker", "snapshot", "status"),
    [
        (
            "--facility-dictionary",
            "facility_dictionary",
            "facility_dictionary_unreadable",
            "uwm_traditional_livability_s6_dictionary.json",
            "dictionary_input_unreadable",
        ),
        (
            "--compatibility-matrix",
            "compatibility_matrix",
            "compatibility_matrix_unreadable",
            "uwm_traditional_livability_s6_compatibility.json",
            "compatibility_matrix_input_unreadable",
        ),
    ],
)
def test_cli_returns_structured_failure_for_unreadable_optional_authority_files(
    tmp_path, monkeypatch, capsys, option, prefix, blocker, snapshot, status
):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    monkeypatch.setattr(MODULE.s6_adapter, "ASSET_SPECS", _specs())
    source_root = _planning_fixture_root(tmp_path / "sources")
    facility_path = tmp_path / "facility.json"
    facility_path.write_text(json.dumps(_facility_product()), encoding="utf-8")
    authority_path = tmp_path / f"{prefix}.json"
    authority_path.write_text("{}", encoding="utf-8")
    real_load_json = MODULE._load_json

    def unreadable_load_json(path):
        if path == authority_path:
            raise OSError("fixture unreadable")
        return real_load_json(path)

    monkeypatch.setattr(MODULE, "_load_json", unreadable_load_json)
    output = tmp_path / "out"

    exit_code = MODULE.main(
        [
            "--source-root",
            str(source_root),
            "--facility-product",
            str(facility_path),
            "--output",
            str(output),
            option,
            str(authority_path),
        ]
    )

    assert exit_code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["blockers"] == [blocker]
    payload = json.loads((output / snapshot).read_text(encoding="utf-8"))
    assert payload["ready"] is False
    assert payload["status"] == status


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
