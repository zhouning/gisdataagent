from __future__ import annotations

import argparse
import json

from scripts.preflight_windows_ingest import run_preflight


def test_preflight_accepts_nx_baseline_in_production(tmp_path, monkeypatch):
    lake = tmp_path / "lake"
    inbox = tmp_path / "inbox"
    contract = tmp_path / "candidate.json"
    contract.write_text(
        json.dumps(
            {
                "schema_version": "gda.standard-contract-catalog.v2",
                "authority": "nx_workbook_baseline",
                "runtime_baseline_ready": True,
                "contracts": {},
            }
        ),
        encoding="utf-8",
    )
    ontology = tmp_path / "ontology.json"
    ontology.write_text("{}", encoding="utf-8")
    for variable in ("GDA_OGRINFO_PATH", "GDA_OGR2OGR_PATH", "GDA_GDAL_TRANSLATE_PATH"):
        tool = tmp_path / variable
        tool.write_text("tool", encoding="ascii")
        monkeypatch.setenv(variable, str(tool))
    common = dict(
        lake=lake,
        inbox=inbox,
        contracts=contract,
        ontology=ontology,
        create_directories=True,
        min_free_gb=0.01,
    )
    development = run_preflight(argparse.Namespace(mode="development", **common))
    production = run_preflight(argparse.Namespace(mode="production", **common))
    assert development["status"] != "blocked"
    assert production["status"] != "blocked"
    contract_check = next(
        item for item in production["checks"] if item["name"] == "standard_contract"
    )
    assert contract_check["status"] == "pass"
    assert production["contract"]["validation_policy"] == "per_dataset_schema_quality_gate"
