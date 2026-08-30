"""Pure tests for version-bound intelligent standard mapping proposals."""
from __future__ import annotations

import pytest

from data_agent.standards_platform.application.contracts import (
    DatasetColumnProfile,
    SourceFieldProfile,
    StandardDataElement,
    evaluate_dataset_quality_preflight,
    evaluate_mapping_quality_gate,
    mapping_publication_status,
    propose_standard_mapping,
)

VERSION_ID = "00000000-0000-0000-0000-000000000001"


def _element(
    element_id: str,
    code: str,
    name: str,
    *,
    bound_column: str = "",
    datatype: str = "VARCHAR",
    representation_class: str = "code",
    bound_table: str = "",
    aliases: tuple[str, ...] = (),
) -> StandardDataElement:
    return StandardDataElement(
        id=element_id,
        document_version_id=VERSION_ID,
        code=code,
        name_zh=name,
        bound_column=bound_column,
        datatype=datatype,
        representation_class=representation_class,
        bound_table=bound_table,
        aliases=aliases,
    )


def test_exact_standard_code_is_recommended_with_element_identity():
    proposal = propose_standard_mapping(
        source_fields=[SourceFieldProfile("DLBM", "object", ("0101",))],
        standard_version_id=VERSION_ID,
        elements=[_element("e1", "DLBM", "地类编码", bound_column="dlbm")],
    )

    assert proposal["mapping"] == {"DLBM": "dlbm"}
    item = proposal["proposals"][0]
    assert item["disposition"] == "recommended"
    assert item["candidates"][0]["target_data_element_id"] == "e1"
    assert item["candidates"][0]["evidence"]["matched_on"] == "DLBM"
    assert proposal["execution_policy"]["automatic_authoritative_write"] is False


def test_semantic_provider_failure_falls_back_to_deterministic_evidence():
    def unavailable(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding backend unavailable")

    proposal = propose_standard_mapping(
        source_fields=[SourceFieldProfile("road_type", "string")],
        standard_version_id=VERSION_ID,
        elements=[_element("e1", "ROAD_CLASS", "道路类型", aliases=("road_type",))],
        embedding_provider=unavailable,
    )

    candidate = proposal["proposals"][0]["candidates"][0]
    assert proposal["mapping"] == {"road_type": "ROAD_CLASS"}
    assert candidate["match_method"] == "lexical_type"
    assert candidate["evidence"]["semantic_score"] is None


def test_persisted_standard_embeddings_are_reused():
    calls: list[list[str]] = []

    def source_embedding(texts: list[str]) -> list[list[float]]:
        calls.append(texts)
        return [[1.0, 0.0] for _ in texts]

    element = _element("e1", "POP", "人口", datatype="integer",
                       representation_class="integer")
    element = StandardDataElement(**{
        **element.__dict__,
        "embedding": (1.0, 0.0),
    })
    proposal = propose_standard_mapping(
        source_fields=[SourceFieldProfile("population", "int64")],
        standard_version_id=VERSION_ID,
        elements=[element],
        embedding_provider=source_embedding,
    )

    assert calls == [["population int64"]]
    assert proposal["proposals"][0]["candidates"][0]["evidence"][
        "semantic_score"
    ] == 1.0


def test_ambiguous_candidates_are_never_auto_recommended():
    proposal = propose_standard_mapping(
        source_fields=[SourceFieldProfile("面积", "float64")],
        standard_version_id=VERSION_ID,
        elements=[
            _element("e1", "TBMJ", "面积", datatype="decimal", representation_class="decimal"),
            _element("e2", "JZMJ", "面积", datatype="decimal", representation_class="decimal"),
        ],
    )

    assert proposal["mapping"] == {}
    assert proposal["proposals"][0]["disposition"] == "review_required"
    assert proposal["proposals"][0]["confidence_margin"] == 0.0


def test_multiple_sources_for_one_element_are_explicit_conflicts():
    proposal = propose_standard_mapping(
        source_fields=[
            SourceFieldProfile("DLBM", "object"),
            SourceFieldProfile("dlbm", "object"),
        ],
        standard_version_id=VERSION_ID,
        elements=[_element("e1", "DLBM", "地类编码", bound_column="dlbm")],
    )

    assert proposal["mapping"] == {}
    assert proposal["summary"]["conflicts"] == 2
    assert {p["disposition"] for p in proposal["proposals"]} == {"conflict"}


def test_distinct_elements_with_same_physical_target_are_conflicts():
    proposal = propose_standard_mapping(
        source_fields=[
            SourceFieldProfile("FIELD_A", "object"),
            SourceFieldProfile("FIELD_B", "object"),
        ],
        standard_version_id=VERSION_ID,
        elements=[
            _element("e1", "FIELD_A", "字段甲", bound_column="shared_target"),
            _element("e2", "FIELD_B", "字段乙", bound_column="shared_target"),
        ],
    )

    assert proposal["mapping"] == {}
    assert proposal["summary"]["conflicts"] == 2


def test_profile_hash_is_stable_and_sensitive_to_samples():
    kwargs = {
        "standard_version_id": VERSION_ID,
        "elements": [_element("e1", "DLBM", "地类编码")],
    }
    first = propose_standard_mapping(
        source_fields=[SourceFieldProfile("DLBM", "object", ("0101",))],
        **kwargs,
    )
    repeated = propose_standard_mapping(
        source_fields=[SourceFieldProfile("DLBM", "object", ("0101",))],
        **kwargs,
    )
    changed = propose_standard_mapping(
        source_fields=[SourceFieldProfile("DLBM", "object", ("0201",))],
        **kwargs,
    )

    assert first["source_profile_hash"] == repeated["source_profile_hash"]
    assert first["source_profile_hash"] != changed["source_profile_hash"]


def test_empty_standard_keeps_every_source_field_unmatched():
    proposal = propose_standard_mapping(
        source_fields=[SourceFieldProfile("unknown", "object")],
        standard_version_id=VERSION_ID,
        elements=[],
    )

    assert proposal["mapping"] == {}
    assert proposal["summary"]["unmatched"] == 1
    assert proposal["proposals"][0]["candidates"] == []


def test_target_table_scope_resolves_repeated_cross_domain_codes():
    elements = [
        _element("parcel-bsm", "parcel_current.BSM", "标识码",
                 bound_table="parcel_current", bound_column="BSM"),
        _element("pbf-bsm", "pbf.BSM", "标识码",
                 bound_table="synthetic_pbf", bound_column="BSM"),
    ]
    unscoped = propose_standard_mapping(
        source_fields=[SourceFieldProfile("BSM", "int64")],
        standard_version_id=VERSION_ID,
        elements=elements,
    )
    scoped = propose_standard_mapping(
        source_fields=[SourceFieldProfile("BSM", "int64")],
        standard_version_id=VERSION_ID,
        elements=elements,
        target_table="parcel_current",
    )

    assert unscoped["mapping"] == {}
    assert unscoped["proposals"][0]["disposition"] == "review_required"
    assert scoped["mapping"] == {"BSM": "BSM"}
    assert scoped["target_scope"] == {
        "bound_table": "parcel_current",
        "candidate_elements": 1,
    }


def test_unknown_target_table_fails_closed():
    with pytest.raises(ValueError, match="has no standard elements"):
        propose_standard_mapping(
            source_fields=[SourceFieldProfile("BSM", "int64")],
            standard_version_id=VERSION_ID,
            elements=[_element(
                "parcel-bsm", "parcel_current.BSM", "标识码",
                bound_table="parcel_current", bound_column="BSM",
            )],
            target_table="missing_domain",
        )


def test_quality_gate_requires_explicit_review_and_mandatory_coverage():
    mandatory = [
        _element("e1", "parcel.BSM", "标识码", bound_column="BSM"),
        _element("e2", "parcel.DLBM", "地类编码", bound_column="DLBM"),
    ]
    gate = evaluate_mapping_quality_gate(
        source_fields=["BSM", "UNUSED"],
        field_bindings=[{
            "source_field": "BSM",
            "target_data_element_id": "e1",
        }],
        review_decisions=[
            {
                "source_field": "BSM",
                "decision": "approved",
                "reason": "recommendation_accepted",
            },
            {
                "source_field": "UNUSED",
                "decision": "rejected",
                "reason": "not_applicable",
            },
        ],
        mandatory_elements=mandatory,
        source_profile_hash="a" * 64,
        target_table="parcel_current",
    )

    assert gate["status"] == "blocked"
    assert gate["summary"] == {
        "source_fields": 2,
        "approved": 1,
        "rejected": 1,
        "pending": 0,
        "mandatory_elements": 2,
        "mandatory_mapped": 1,
    }
    assert gate["missing_mandatory_elements"][0]["target_field"] == "DLBM"
    publication = mapping_publication_status(gate)
    assert publication["ready"] is False
    assert publication["blockers"] == [
        "standard_mapping_quality_gate_not_passed",
        "dataset_quality_validation_not_run",
        "data_product_version_not_created",
    ]


def test_quality_gate_rejects_approval_without_matching_binding():
    with pytest.raises(
        ValueError, match="approved review decisions must match field bindings",
    ):
        evaluate_mapping_quality_gate(
            source_fields=["BSM"],
            field_bindings=[],
            review_decisions=[{
                "source_field": "BSM",
                "decision": "approved",
            }],
            mandatory_elements=[],
            source_profile_hash="a" * 64,
            target_table="parcel_current",
        )


def test_dataset_quality_preflight_passes_sample_without_claiming_release():
    result = evaluate_dataset_quality_preflight(
        mapping_contract_id="contract-1",
        mapping_hash="a" * 64,
        source_snapshot_hash="b" * 64,
        sample_fingerprint="c" * 64,
        requested_limit=200,
        observed_records=2,
        columns=[
            DatasetColumnProfile("DLBM", "object", 2),
            DatasetColumnProfile("TBMJ", "float64", 2),
            DatasetColumnProfile("geometry", "geometry", 2),
        ],
        field_bindings=[
            {
                "source_field": "DLBM",
                "target_field": "dlbm",
                "target_data_element_id": "e1",
                "datatype": "VARCHAR",
                "representation_class": "code",
                "obligation": "mandatory",
            },
            {
                "source_field": "TBMJ",
                "target_field": "tbmj",
                "target_data_element_id": "e2",
                "datatype": "DECIMAL",
                "representation_class": "decimal",
                "obligation": "mandatory",
            },
        ],
    )

    assert result["verdict"] == "passed"
    assert result["scope"] == {
        "mode": "sample",
        "requested_limit": 200,
        "observed_records": 2,
        "full_dataset_validated": False,
        "authoritative_quality_assessment": False,
    }
    assert result["release_candidate"] == {
        "status": "blocked",
        "data_product_version_created": False,
        "blockers": [
            "full_dataset_quality_assessment_not_recorded",
            "data_product_version_not_created",
        ],
    }
    assert len(result["preflight_sha256"]) == 64


def test_dataset_quality_preflight_reports_null_type_and_geometry_failures():
    result = evaluate_dataset_quality_preflight(
        mapping_contract_id="contract-1",
        mapping_hash="a" * 64,
        source_snapshot_hash=None,
        sample_fingerprint="c" * 64,
        requested_limit=10,
        observed_records=3,
        columns=[
            DatasetColumnProfile("DLBM", "float64", 3, null_count=1),
            DatasetColumnProfile(
                "geometry", "geometry", 3, invalid_geometry_count=1,
            ),
        ],
        field_bindings=[{
            "source_field": "DLBM",
            "target_field": "dlbm",
            "target_data_element_id": "e1",
            "datatype": "VARCHAR",
            "representation_class": "code",
            "obligation": "mandatory",
        }],
    )

    assert result["verdict"] == "failed"
    by_id = {item["id"]: item for item in result["checks"]}
    assert by_id["mandatory_sample_values_complete"]["status"] == "failed"
    assert by_id["mapped_datatypes_compatible"]["status"] == "failed"
    assert by_id["sample_geometries_valid"]["status"] == "failed"
    assert result["release_candidate"]["blockers"][0] == (
        "dataset_sample_preflight_not_passed"
    )


def test_dataset_quality_preflight_blocks_empty_sample():
    result = evaluate_dataset_quality_preflight(
        mapping_contract_id="contract-1",
        mapping_hash="a" * 64,
        source_snapshot_hash=None,
        sample_fingerprint="c" * 64,
        requested_limit=10,
        observed_records=0,
        columns=[DatasetColumnProfile("DLBM", "object", 0)],
        field_bindings=[{
            "source_field": "DLBM",
            "target_field": "dlbm",
            "target_data_element_id": "e1",
            "datatype": "VARCHAR",
            "representation_class": "code",
            "obligation": "mandatory",
        }],
    )

    assert result["verdict"] == "blocked"
    assert result["checks"][0]["status"] == "blocked"
