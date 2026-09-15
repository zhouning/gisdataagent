"""Regression coverage for the v53 audited district-score stage correction."""

import importlib.util
import json
from pathlib import Path

from data_agent.governed_virtual_nl2sql import _validate_metric_contracts


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/promote_liveability_v53_district_score_stage_vocabulary_20260915.py"
SEMANTIC = ROOT / "docs/customer/abu_dhabi_liveability_site_validation/liveability_data_20260730_semantic_layer_v52_governed_parameterized_business_metrics_20260915.json"
ONTOLOGY = ROOT / "docs/customer/abu_dhabi_liveability_site_validation/liveability_data_20260730_ontology_v51_governed_parameterized_business_metrics_20260915.json"

spec = importlib.util.spec_from_file_location("liveability_v53_stage_vocabulary", SCRIPT)
assert spec and spec.loader
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def test_v53_rebinds_current_score_ranking_to_the_audited_stage_literal() -> None:
    semantic = json.loads(SEMANTIC.read_text(encoding="utf-8"))
    ontology = json.loads(ONTOLOGY.read_text(encoding="utf-8"))
    publisher._upsert_contracts(semantic, ontology)
    _validate_metric_contracts(semantic)

    contract = next(
        item
        for item in semantic["metric_contracts"]
        if item["contract_id"] == publisher.CONTRACT_ID
    )
    assert contract["filters"][0]["values"] == ["Existing"]
    assert "s.stage='Existing'" in contract["canonical_sql_template"]
    assert "s.stage='current'" not in contract["canonical_sql_template"]

    binding = next(
        item
        for item in semantic["table_bindings"]
        if item["physical_table"] == publisher.STAGE_TABLE
    )
    stage = next(item for item in binding["fields"] if item["physical_field"] == "stage")
    assert stage["observed_value_domain"] == ["Existing", "Pipeline", "AP50"]
    assert stage["definition_status"] == "source_bound_stage_vocabulary_audited"


def test_v53_publisher_has_no_benchmark_or_gold_dependency() -> None:
    source = SCRIPT.read_text(encoding="utf-8").casefold()
    assert "liveability_kb" not in source
    assert "gold_contract" not in source
    assert '"gold_sql_used": false' in source
