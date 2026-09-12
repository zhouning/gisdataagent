from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_agent.governed_virtual_nl2sql import (
    _match_metric_contract,
    _validate_metric_contracts,
    _validate_semantic_answerability_contracts,
    resolve_semantic_answerability_contract,
)

ARTIFACT_ROOT = Path(__file__).resolve().parents[1] / "docs/customer/abu_dhabi_liveability_site_validation"
SEMANTIC_PATH = ARTIFACT_ROOT / (
    "liveability_data_20260730_semantic_layer_v45_plot_detail_audited_relationships_20260912.json"
)
ONTOLOGY_PATH = ARTIFACT_ROOT / (
    "liveability_data_20260730_ontology_v44_plot_detail_audited_relationships_20260912.json"
)
SOURCE_AUDIT_PATH = ARTIFACT_ROOT / "liveability_v45_plot_relationship_source_audit_20260912.json"


if not all(path.exists() for path in (SEMANTIC_PATH, ONTOLOGY_PATH, SOURCE_AUDIT_PATH)):
    pytest.skip(
        "v45 customer artifacts are deployment fixtures and are not part of the public checkout",
        allow_module_level=True,
    )


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_v45_artifact_identity_relationships_and_contract_parity() -> None:
    semantic = _load(SEMANTIC_PATH)
    ontology = _load(ONTOLOGY_PATH)

    assert semantic["semantic_version"] == (
        "abu-dhabi-liveability_data_20260730-v45-plot-detail-audited-relationships-20260912"
    )
    assert ontology["ontology_enrichment_version"] == (
        "abu-dhabi-liveability-ontology-v44-plot-detail-audited-relationships-20260912"
    )
    assert semantic["artifact_bundle_id"] == ontology["artifact_bundle_id"]
    assert semantic["source_binding"] == {
        "source_id": 12,
        "database_name": "liveability_data_20260730",
        "allowed_schemas": ["public"],
        "discovery_fingerprint": "bd64208ca6a70391525d13f9f0e12204d4722e3f94fa8247e3e9a1e411708e44",
        "profile_fingerprint": "6dfebc1a7f87404357a6c87065158c1db34c963291f30364046c16631b9cbe86",
        "execution_mode": "registered_governed_virtual_read_only",
    }

    expected_tables = {
        "public.dim_parks_calc_plots",
        "public.dim_udm_plots",
    }
    bindings = {
        str(item["physical_table"]): item
        for item in semantic["table_bindings"]
        if item.get("physical_table") in expected_tables
    }
    assert set(bindings) == expected_tables
    for table, binding in bindings.items():
        assert binding["primary_key"] == ["id"]
        assert binding["foreign_keys"] == [
            {
                "name": f"{table.rsplit('.', 1)[-1]}_liv_district_id_fkey",
                "columns": ["liv_district_id"],
                "referred_schema": "public",
                "referred_table": "dim_districts",
                "referred_columns": ["district_id"],
            }
        ]

    relationship_pairs = {
        (item["left"], item["right"])
        for item in semantic["relationships"]
        if item.get("right") == "public.dim_districts.district_id"
    }
    assert {
        (f"{table}.liv_district_id", "public.dim_districts.district_id")
        for table in expected_tables
    } <= relationship_pairs
    assert ontology["runtime_answerability_contracts"] == semantic[
        "semantic_answerability_contracts"
    ]
    assert ontology["semantic_answerability_contracts"] == semantic[
        "semantic_answerability_contracts"
    ]
    assert ontology["runtime_metric_contracts"] == semantic["metric_contracts"]
    _validate_metric_contracts(semantic)
    _validate_semantic_answerability_contracts(semantic)


def test_v45_source_audit_contains_only_aggregate_probes() -> None:
    audit = _load(SOURCE_AUDIT_PATH)
    assert audit["status"] == "passed"
    assert audit["source"]["source_id"] == 12
    assert audit["source"]["owner"] == "abu-dhabi-site-operator"
    assert audit["claim_boundary"]["aggregate_probes_only"] is True
    assert audit["claim_boundary"]["source_rows_persisted"] is False
    expected_counts = {
        "dim_parks_calc_plots": 229862,
        "dim_udm_plots": 390613,
    }
    raw = SOURCE_AUDIT_PATH.read_text(encoding="utf-8")
    assert "SELECT " not in raw.upper()
    for table_key, row_count in expected_counts.items():
        probe = audit["relationships"][table_key]["probe"]
        assert set(probe) == {"table", "sql_sha256", "aggregate", "source_rows_persisted"}
        assert probe["aggregate"] == {
            "row_count": row_count,
            "fk_non_null_count": row_count,
            "matched_count": row_count,
            "orphan_count": 0,
            "fk_null_count": 0,
            "duplicate_id_count": 0,
        }
        assert probe["source_rows_persisted"] is False


def test_v45_representative_area_contract_has_explicit_scope_behaviors() -> None:
    semantic = _load(SEMANTIC_PATH)
    contract_id = "LIVEABILITY_REPRESENTATIVE_AREA_BASELINE_UNAVAILABLE_V1"

    generic = resolve_semantic_answerability_contract(
        "Which representative area is best for district ranking?", "en", semantic
    )
    assert generic["status"] == "matched"
    assert generic["contract_id"] == contract_id
    assert generic["missing_context_ids"] == ["representative_scope"]

    benchmark = resolve_semantic_answerability_contract(
        "After the Pipeline stage is completed, how much does Pedestrian Path IC "
        "completion improve in three representative districts. Show the result in "
        "a line chart.",
        "en",
        semantic,
    )
    assert benchmark["status"] == "matched"
    assert benchmark["contract_id"] == contract_id
    assert benchmark["missing_context_ids"] == ["representative_scope"]

    scoped = resolve_semantic_answerability_contract(
        "Which representative area in Abu Dhabi region is best for district ranking?",
        "en",
        semantic,
    )
    assert scoped["status"] == "none"

    baseline_rule = resolve_semantic_answerability_contract(
        "What baseline rule defined for district ranking should I use?", "en", semantic
    )
    assert baseline_rule["status"] == "none"

    unrelated = resolve_semantic_answerability_contract(
        "List district names and their IDs.", "en", semantic
    )
    assert unrelated["status"] == "none"


def test_v45_plot_identifier_context_accepts_single_character_values() -> None:
    semantic = _load(SEMANTIC_PATH)
    contract_id = "LIVEABILITY_PARCEL_IDENTIFIER_REQUIRED_V1"

    missing = resolve_semantic_answerability_contract(
        "Show plot details.", "en", semantic
    )
    assert missing["status"] == "matched"
    assert missing["contract_id"] == contract_id
    assert missing["missing_context_ids"] == ["parcel_identifier"]

    benchmark = resolve_semantic_answerability_contract(
        "Which attributes can be retrieved using a Parcel ID or Plot Number, "
        "including district, Land Use Type, land area, development status, and "
        "Urban, Suburban, or Rural settlement context?",
        "en",
        semantic,
    )
    assert benchmark["status"] == "matched"
    assert benchmark["contract_id"] == contract_id
    assert benchmark["missing_context_ids"] == ["parcel_identifier"]

    for question in (
        "Show parcel details for Parcel ID: A.",
        "Show plot details for Plot Number: A.",
        "查询地块详情，地块编号：A。",
    ):
        resolved = resolve_semantic_answerability_contract(question, "en" if question.startswith("Show") else "zh", semantic)
        assert resolved["status"] == "none", question


def test_v45_detail_ordered_contracts_are_table_scoped_and_metric_free() -> None:
    semantic = _load(SEMANTIC_PATH)
    expected = {
        "dim_parks_calc_plots": "LIVEABILITY_PLOT_DETAIL_DIM_PARKS_CALC_PLOTS_V1",
        "dim_udm_plots": "LIVEABILITY_PLOT_DETAIL_DIM_UDM_PLOTS_V1",
    }
    for table_key, contract_id in expected.items():
        table = f"public.{table_key}"
        contract = _match_metric_contract(
            f"List plot details from {table}.", "en", semantic, [table]
        )
        assert contract is not None
        assert contract["contract_id"] == contract_id
        assert contract["operation"] == "detail_ordered"
        assert contract["metrics"] == []
        assert contract["order_by"] == ["id"]
        assert {item["table"] for item in contract["dimensions"]} == {table}
