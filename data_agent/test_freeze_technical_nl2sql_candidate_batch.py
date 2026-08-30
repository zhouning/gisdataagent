from __future__ import annotations

import importlib.util
import json
from argparse import Namespace
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/freeze_technical_nl2sql_candidate_batch.py"


def _module():
    spec = importlib.util.spec_from_file_location("freeze_technical_batch", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _candidate(operation: str, field: str | None = None) -> dict:
    return {
        "candidate_id": f"TECH_{operation}_{field or 'table'}",
        "status": "pending_gold_freeze",
        "technical_only": True,
        "source": {
            "source_id": 12,
            "database_name": "liveability_data_20260730",
            "schema": "public",
            "physical_table": "public.dim_districts",
            "physical_field": field,
        },
        "operation": operation,
    }


def test_verification_sql_is_schema_qualified_and_read_only():
    module = _module()
    assert module._verification_sql(_candidate("table_row_count")) == (
        'SELECT COUNT(*) AS row_count FROM "public"."dim_districts"'
    )
    sql = module._verification_sql(_candidate("field_null_profile", "name"))
    assert '"public"."dim_districts"' in sql
    assert '"name"' in sql
    assert "FILTER" in sql


def test_verification_sql_rejects_unqualified_or_injected_identifiers():
    module = _module()
    candidate = _candidate("table_row_count")
    candidate["source"]["physical_table"] = "public.dim_districts; DROP TABLE users"
    try:
        module._verification_sql(candidate)
    except ValueError as exc:
        assert str(exc) == "invalid_table"
    else:
        raise AssertionError("injected table identifier was accepted")


def test_batch_freeze_stores_contracts_without_source_rows(tmp_path, monkeypatch):
    module = _module()
    benchmark_path = tmp_path / "candidates.json"
    benchmark = {
        "schema": "gda.technical-nl2sql-benchmark-candidates.v1",
        "source": {
            "source_id": 12,
            "database_name": "liveability_data_20260730",
            "allowed_schemas": ["public"],
            "discovery_fingerprint": "d" * 64,
            "profile_fingerprint": "p" * 64,
        },
        "candidates": [_candidate("table_row_count")],
    }
    benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")
    monkeypatch.setattr(
        module,
        "get_virtual_source",
        lambda source_id, owner: {
            "id": source_id,
            "enabled": True,
            "discovery_fingerprint": "d" * 64,
            "profile_fingerprint": "p" * 64,
        },
    )

    async def fake_query(*args, **kwargs):
        return pd.DataFrame([{"row_count": 216}])

    monkeypatch.setattr(module, "query_virtual_source", fake_query)
    args = Namespace(
        benchmark=benchmark_path,
        output=tmp_path / "out.json",
        offset=0,
        limit=10,
        limit_rows=1000,
        owner="abu-dhabi-site-operator",
    )
    payload = module.asyncio.run(module._run(args))
    assert payload["metrics"] == {
        "selected_count": 1,
        "frozen_count": 1,
        "failed_count": 0,
        "freeze_rate": 1.0,
    }
    assert payload["claim_boundary"]["source_rows_persisted"] is False
    assert "rows" not in payload["contracts"][0]["result_contract"]
