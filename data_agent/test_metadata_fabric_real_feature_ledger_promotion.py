import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from data_agent import metadata_fabric_real_feature_ingestion as m322
from data_agent import metadata_fabric_real_feature_ledger_promotion as promotion
from data_agent.platform_contracts import quality_result_fingerprint


def _source() -> dict:
    return json.loads(
        promotion.DEFAULT_SOURCE_EVIDENCE_PATH.read_text(encoding="utf-8")
    )


def test_checked_m3_22_candidates_build_one_content_bound_promotion():
    source = _source()
    bundle = promotion.build_promotion(source)

    assert bundle.authority_resource.resource_kind == "data_product"
    assert bundle.authority_resource.authority_system == "gravitino"
    assert bundle.output_resource_version.resource_version_id == (
        promotion.OUTPUT_RESOURCE_VERSION_ID
    )
    assert bundle.output_resource_version.content_sha256 == (
        source["observation"]["plan"]["output_content_sha256"]
    )
    assert bundle.output_artifact.run_id == promotion.RUN_ID
    assert bundle.quality_result.evaluated_by == m322.QUALITY_EVALUATOR
    assert bundle.quality_result.evaluated_by != (
        bundle.output_resource_version.created_by
    )
    assert bundle.lineage_event.source_resource_version_id == (
        promotion.SOURCE_RESOURCE_VERSION_ID
    )
    assert bundle.lineage_event.target_resource_version_id == (
        promotion.OUTPUT_RESOURCE_VERSION_ID
    )


def test_promotion_prerequisites_correlate_without_fabricating_authorization():
    source = _source()
    bundle = promotion.build_promotion(source)
    prerequisites = promotion.build_prerequisites(source, bundle)

    assert prerequisites.run.status.value == "accepted"
    assert prerequisites.run.state_version == 0
    assert prerequisites.run.policy_refs is None
    assert prerequisites.run.config_fingerprint == (
        source["observation"]["authorization"]["authorization_sha256"]
    )
    assert prerequisites.run.input_bindings[0].resource_version_id == (
        promotion.SOURCE_RESOURCE_VERSION_ID
    )
    assert prerequisites.definition_registration.definition.output_contract[
        "platform_run_terminal_success"
    ] is False
    assert prerequisites.output_resource == bundle.authority_resource


def test_m3_22_evidence_tampering_is_rejected_before_promotion():
    source = deepcopy(_source())
    source["observation"]["output_contracts"]["output_resource_version"][
        "content_sha256"
    ] = "0" * 64

    with pytest.raises(
        promotion.RealFeatureLedgerPromotionError,
        match="M3-22 evidence is invalid",
    ):
        promotion.build_promotion(source)


def test_promotion_contract_rejects_quality_evaluator_impersonation():
    bundle = promotion.build_promotion(_source())
    values = bundle.model_dump(mode="python")
    quality_values = bundle.quality_result.model_dump(mode="python")
    quality_values["evaluated_by"] = bundle.output_resource_version.created_by
    quality_values["result_sha256"] = quality_result_fingerprint(
        **{
            key: value
            for key, value in quality_values.items()
            if key not in {"quality_result_id", "result_sha256"}
        }
    )
    values["quality_result"] = bundle.quality_result.__class__(**quality_values)

    with pytest.raises(ValidationError, match="quality evaluation must be independent"):
        promotion.RunOutputLedgerPromotion.model_validate(values)


def test_promotion_contract_rejects_lineage_manifest_drift():
    bundle = promotion.build_promotion(_source())
    values = bundle.model_dump(mode="python")
    lineage = bundle.lineage_event.model_copy(
        update={"facets": {**bundle.lineage_event.facets, "feature_count": 21}}
    )
    values["lineage_event"] = lineage

    with pytest.raises(ValidationError, match="lineage facets do not match"):
        promotion.RunOutputLedgerPromotion.model_validate(values)


def test_static_contract_is_source_bound_and_non_terminal():
    report = promotion.build_contract_report()

    assert report["status"] == "valid"
    assert report["errors"] == []
    assert report["source_evidence_sha256"] == promotion.SOURCE_EVIDENCE_SHA256
    assert report["source_contract_sha256"] == promotion.SOURCE_CONTRACT_SHA256
    assert report["atomic_write_order"] == [
        "resource_version",
        "output_artifact",
        "quality_evidence_artifact",
        "quality_result",
        "lineage_event",
    ]
    assert report["requires_preexisting_output_authority"] is True
    assert report["partial_preexisting_state_rejected"] is True
    assert report["platform_run_terminal_success"] is False
    assert report["writes_to_legacy"] is False
