"""Static regression coverage for the v51 technical schema-drift release."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/promote_liveability_v51_schema_drift_rebind_20260915.py"
SEMANTIC = ROOT / (
    "docs/customer/abu_dhabi_liveability_site_validation/"
    "liveability_data_20260730_semantic_layer_v50_metric_composition_audit_boundary_20260915.json"
)
ONTOLOGY = ROOT / (
    "docs/customer/abu_dhabi_liveability_site_validation/"
    "liveability_data_20260730_ontology_v49_metric_composition_audit_boundary_20260915.json"
)
CATALOG = ROOT / (
    "docs/customer/abu_dhabi_liveability_site_validation/"
    "liveability_data_20260730_technical_semantic_catalog_v6_discovery_rebind_20260913.json"
)

spec = importlib.util.spec_from_file_location("liveability_v51_rebind", SCRIPT)
assert spec and spec.loader
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def _snapshot() -> dict:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    resources = []
    for resource in catalog["resources"]:
        item = {
            "qualified_name": resource["physical_table"],
            "resource_type": resource["resource_type"],
            "columns": [
                {"name": field["physical_field"], "type": field["data_type"], "nullable": field["nullable"]}
                for field in resource["fields"]
            ],
            "foreign_keys": copy.deepcopy(resource.get("foreign_keys") or []),
            "primary_key": copy.deepcopy(resource.get("primary_key") or []),
            "indexes": copy.deepcopy(resource.get("indexes") or []),
            "estimated_record_count": resource.get("estimated_record_count"),
        }
        if item["qualified_name"] == publisher.DRIFT_TABLE:
            item["columns"].append({"name": publisher.DRIFT_FIELD, "type": "BOOLEAN", "nullable": False})
        resources.append(item)
    return {"resources": resources}


def test_v51_permits_only_the_declared_technical_field_addition() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    drift = publisher._assert_only_allowed_drift(catalog, _snapshot())
    assert drift["table"] == publisher.DRIFT_TABLE
    assert drift["field"] == publisher.DRIFT_FIELD
    assert drift["business_definition_status"] == "pending_customer_governance"
    assert drift["gold_sql_used"] is False


def test_v51_rejects_any_other_field_change() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    snapshot = _snapshot()
    next(item for item in snapshot["resources"] if item["qualified_name"] == "public.fact_ic_scores")["columns"].append(
        {"name": "unreviewed_field", "type": "TEXT", "nullable": True}
    )
    with pytest.raises(RuntimeError, match="field_change_requires_review"):
        publisher._assert_only_allowed_drift(catalog, snapshot)


def test_v51_field_is_technical_only_in_all_runtime_projections() -> None:
    semantic = json.loads(SEMANTIC.read_text(encoding="utf-8"))
    ontology = json.loads(ONTOLOGY.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    publisher._apply_technical_field(semantic, ontology, catalog)
    for fields in (
        next(item for item in semantic["table_bindings"] if item["physical_table"] == publisher.DRIFT_TABLE)["fields"],
        next(item for item in semantic["semantic_assets"] if publisher.DRIFT_TABLE in item["physical_tables"])["fields"],
        next(item for item in ontology["concepts"] if item["physical_binding"] == publisher.DRIFT_TABLE)["fields"],
    ):
        field = next(item for item in fields if item["physical_field"] == publisher.DRIFT_FIELD)
        assert field["semantic_status"] == "technical_metadata_only"
        assert field["inference"]["review_required"] is True
        assert "business_table_card_evidence" not in field
    resource = next(item for item in catalog["resources"] if item["physical_table"] == publisher.DRIFT_TABLE)
    assert any(item["physical_field"] == publisher.DRIFT_FIELD for item in resource["fields"])


def test_v51_publisher_has_no_evaluation_inputs() -> None:
    source = SCRIPT.read_text(encoding="utf-8").casefold()
    assert "benchmark_path" not in source
    assert "private_gold" not in source
    assert '"gold_sql_used": false' in source
