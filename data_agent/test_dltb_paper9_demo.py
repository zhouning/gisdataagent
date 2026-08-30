from __future__ import annotations

import pytest

from scripts.run_dltb_paper9_demo import (
    _production_blockers,
    _profile,
    _reference_year_contract,
    _resolve_product,
    _sha256_path,
)


def test_smoke_profile_runs_all_training_stages_with_bounded_work():
    profile = _profile("smoke")
    assert profile["n_transition_episodes"] == 3
    assert profile["n_pairwise_states"] == 50
    assert profile["n_members"] == 1
    assert profile["epochs"] == 2
    assert profile["out_subdir"] == "tool3_smoke"


def test_directory_digest_includes_member_names_and_content(tmp_path):
    dataset = tmp_path / "DLTB.gdb"
    dataset.mkdir()
    (dataset / "a.gdbtable").write_bytes(b"one")
    first = _sha256_path(dataset)
    (dataset / "b.gdbtable").write_bytes(b"two")
    second = _sha256_path(dataset)
    assert first != second
    assert second == _sha256_path(dataset)


def test_resolve_product_verifies_governed_product_digest(tmp_path):
    product_path = tmp_path / "DLTB.parquet"
    product_path.write_bytes(b"governed")
    product = {
        "role": "dltb",
        "status": "succeeded",
        "path": str(product_path),
        "sha256": _sha256_path(product_path),
    }

    resolved, verified = _resolve_product(product, "dltb")

    assert resolved == product_path.resolve()
    assert verified["verified_sha256"] == product["sha256"]


def test_resolve_product_rejects_digest_mismatch(tmp_path):
    product_path = tmp_path / "DLTB.parquet"
    product_path.write_bytes(b"governed")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        _resolve_product(
            {
                "role": "dltb",
                "status": "succeeded",
                "path": str(product_path),
                "sha256": "0" * 64,
            },
            "dltb",
        )


def test_missing_optional_admin_product_is_distinct_from_failed_product():
    product = {"role": "administrative_units", "status": "missing"}

    with pytest.raises(ValueError, match="not succeeded: missing"):
        _resolve_product(product, "administrative_units")


def test_reference_year_contract_preserves_inferred_year_as_non_authoritative():
    contract = _reference_year_contract(
        None,
        {
            "reference_year": 2020,
            "reference_year_source": "path_inferred",
            "reference_year_authoritative": False,
        },
    )

    assert contract == {
        "year": 2020,
        "source": "path_inferred",
        "authoritative": False,
    }


def test_rehearsal_does_not_claim_production_gate():
    blockers = _production_blockers(
        mode="rehearsal",
        sample_input=True,
        status={"finals": {"version_compatible": False}},
        upstream=None,
        pipeline=None,
        audit=None,
        error="expected rehearsal error",
    )
    assert blockers == []


def test_production_requires_version_phase1_and_hard_constraint_evidence():
    blockers = _production_blockers(
        mode="production",
        sample_input=False,
        status={"finals": {"version_compatible": False}},
        upstream={
            "production_eligible": False,
            "quality_gate": {"production_gate_passed": False},
        },
        pipeline={"status": "ok"},
        audit={"hard_constraint_passed": False},
        error=None,
    )
    assert any(item.startswith("paper9_version:") for item in blockers)
    assert any(item.startswith("phase1_gate:") for item in blockers)
    assert any(item.startswith("phase1_quality:") for item in blockers)
    assert any(item.startswith("paper9_audit:") for item in blockers)


def test_production_blocks_when_audit_evidence_is_missing():
    blockers = _production_blockers(
        mode="production",
        sample_input=False,
        status={"finals": {"version_compatible": True}},
        upstream={
            "production_eligible": True,
            "quality_gate": {"production_gate_passed": True},
        },
        pipeline={"status": "ok"},
        audit=None,
        error=None,
    )
    assert "paper9_audit: audit evidence is missing" in blockers


def test_production_blocks_when_spatial_outputs_are_incomplete():
    blockers = _production_blockers(
        mode="production",
        sample_input=False,
        status={"finals": {"version_compatible": True}},
        upstream={
            "production_eligible": True,
            "quality_gate": {"production_gate_passed": True},
        },
        pipeline={"status": "ok"},
        audit={"hard_constraint_passed": True, "all_expected_outputs_exist": False},
        error=None,
    )
    assert "paper9_audit: expected spatial output artifacts are incomplete" in blockers


def test_production_blocks_when_joint_input_quality_does_not_pass():
    blockers = _production_blockers(
        mode="production",
        sample_input=False,
        status={"finals": {"version_compatible": True}},
        upstream={
            "production_eligible": True,
            "quality_gate": {"production_gate_passed": True},
        },
        pipeline={"status": "ok"},
        audit={"hard_constraint_passed": True, "all_expected_outputs_exist": True},
        error=None,
        input_mode="governed_lake_products",
        governed_roles={"dltb", "dem", "administrative_units"},
        input_quality={
            "production_gate_passed": False,
            "findings": ["DEM direct coverage is below the production threshold"],
        },
    )

    assert "paper9_input_quality: DEM direct coverage is below the production threshold" in blockers
