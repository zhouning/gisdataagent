from __future__ import annotations

import json

import pytest

from scripts import (
    acquire_geotransport_stage34_temporal_semantics_evidence as acquire,
)


def test_stage34_plan_freezes_operator_and_process_semantic_boundary():
    plan = acquire.compile_plan()

    assert plan["frozen_operator_artifact"]["sha256"] == (
        "8632158a2ecfe194f6419fc6ceab5f7eca7ef958cc694a8719742b97ffd90bdd"
    )
    assert plan["predeclared_semantic_boundary"][
        "same_time_dimension_is_sufficient_for_substitution"
    ] is False
    assert plan["predeclared_semantic_boundary"][
        "runtime_promotion_allowed"
    ] is False


def test_stage34_plan_is_one_public_document_request_without_outcomes():
    plan = acquire.compile_plan(values_mode=True)

    assert len(plan["sources"]) == 1
    assert plan["sources"][0]["source"] == (
        "usace_cwms_data_api_repository"
    )
    assert acquire.DOCUMENT_COMMIT in plan["sources"][0]["url"]
    assert plan["request_boundary"]["maximum_request_count"] == 1
    assert plan["request_boundary"][
        "release_or_downstream_outcome_values_requested"
    ] is False
    assert plan["request_boundary"]["workspace_or_private_data_sent"] is False


def test_stage34_document_validation_is_casefolded_and_bounded():
    body = (
        "Parameter TYPE Duration Interval Version\n" + "x" * 1_000
    ).encode()

    assert acquire._validate_document(body).startswith("Parameter")
    with pytest.raises(ValueError, match="markers_missing"):
        acquire._validate_document(b"x" * 1_100)


def test_stage34_rejects_unapproved_or_unpinned_document_urls():
    with pytest.raises(ValueError, match="url_outside_allowlist"):
        acquire._validate_url("https://example.com/timeseries.rst")
    with pytest.raises(ValueError, match="url_outside_allowlist"):
        acquire._validate_url(
            "https://raw.githubusercontent.com/USACE/cwms-data-api/main/"
            "docs/source/data/timeseries.rst"
        )


def test_stage34_requires_exact_frozen_plan(tmp_path):
    path = tmp_path / "acquisition_plan.json"
    with pytest.raises(ValueError, match="plan_must_be_frozen"):
        acquire._load_exact_plan(path, acquire.compile_plan())
    path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen_plan_mismatch"):
        acquire._load_exact_plan(path, acquire.compile_plan())
