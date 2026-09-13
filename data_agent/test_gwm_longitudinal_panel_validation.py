from copy import deepcopy

from data_agent.test_gwm_longitudinal_panel_source_contract import (
    _contract as _source_contract,
)
from data_agent.test_gwm_spatiotemporal_causal_design_contract import (
    _design_contract as _spatiotemporal_design_fixture,
)
from data_agent.uwm.geospatial_kernel import (
    LONGITUDINAL_DESIGN_GATES,
    LONGITUDINAL_ESTIMATION_GATES,
    build_longitudinal_panel_validation_contract,
    build_spatiotemporal_causal_design_contract,
    seed_spatiotemporal_gate_evidence_from_panel_validation,
    validate_longitudinal_panel_validation_contract,
    validate_spatiotemporal_causal_design_contract,
)


PERIODS = (
    ("2026-01-01T00:00:00Z", "2026-01"),
    ("2026-02-01T00:00:00Z", "2026-02"),
    ("2026-03-01T00:00:00Z", "2026-03"),
    ("2026-04-01T00:00:00Z", "2026-04"),
)


def _field_mapping() -> dict:
    return {
        "unit_id_field": "unit_id",
        "panel_time_field": "panel_time",
        "treatment_field": "treatment",
        "treatment_time_field": "treatment_time",
        "outcome_field": "outcome",
        "outcome_time_field": "outcome_time",
        "baseline_confounder_fields": ["baseline_state"],
        "time_varying_confounder_fields": ["confounder_t"],
        "confounder_time_field": "confounder_time",
        "feature_available_at_field": "feature_available_at",
        "censoring_indicator_field": "censored",
        "network_mapping_version_field": "network_version",
        "source_id_fields": {
            "treatment_events": "treatment_source_id",
            "observed_outcomes": "outcome_source_id",
            "time_varying_confounders": "confounder_source_id",
            "spatial_units": "unit_source_id",
        },
    }


def _network_field_mapping() -> dict:
    return {
        "from_unit_id_field": "from_unit_id",
        "to_unit_id_field": "to_unit_id",
        "valid_from_field": "valid_from",
        "valid_to_field": "valid_to",
        "source_id_field": "network_source_id",
        "mapping_version_field": "network_version",
    }


def _panel_rows() -> list[dict]:
    rows = []
    for unit_id in ("u1", "u2"):
        for period_start, version in PERIODS:
            rows.append(
                {
                    "unit_id": unit_id,
                    "panel_time": period_start,
                    "treatment": int(
                        unit_id == "u1" and period_start >= "2026-03"
                    ),
                    "treatment_time": period_start.replace(
                        "00:00:00", "12:00:00"
                    ),
                    "outcome": 10.0,
                    "outcome_time": {
                        "2026-01": "2026-02-01T00:00:00Z",
                        "2026-02": "2026-03-01T00:00:00Z",
                        "2026-03": "2026-04-01T00:00:00Z",
                        "2026-04": "2026-05-01T00:00:00Z",
                    }[version],
                    "baseline_state": 1,
                    "confounder_t": 2.0,
                    "confounder_time": period_start.replace(
                        "00:00:00", "08:00:00"
                    ),
                    "feature_available_at": period_start.replace(
                        "00:00:00", "09:00:00"
                    ),
                    "censored": 0,
                    "network_version": version,
                    "treatment_source_id": "source-treatment_events",
                    "outcome_source_id": "source-observed_outcomes",
                    "confounder_source_id": "source-time_varying_confounders",
                    "unit_source_id": "source-spatial_units",
                }
            )
    return rows


def _network_rows() -> list[dict]:
    rows = []
    for period_start, version in PERIODS:
        month = int(period_start[5:7])
        valid_to = (
            f"2026-{month + 1:02d}-01T00:00:00Z"
            if month < 12
            else "2027-01-01T00:00:00Z"
        )
        rows.append(
            {
                "from_unit_id": "u1",
                "to_unit_id": "u2",
                "valid_from": period_start,
                "valid_to": valid_to,
                "network_source_id": "source-interference_network",
                "network_version": version,
            }
        )
    return rows


def _provenance(source_contract: dict) -> dict:
    return {
        "validator_version": "gwm-longitudinal-panel-validator-v1",
        "generated_at": "2026-07-23T00:00:00Z",
        "source_artifact_hashes": {
            source["source_id"]: str(index + 1) * 64
            for index, source in enumerate(source_contract["sources"])
        },
    }


def _validation_contract(
    *,
    evidence_class: str = "synthetic_fixture",
    source_contract: dict | None = None,
    panel_rows: list[dict] | None = None,
    network_rows: list[dict] | None = None,
) -> dict:
    source = source_contract or _source_contract()
    materialization = {
        "evidence_class": evidence_class,
        "status": "synthetic_only",
        "authorization_ref": None,
        "materialized_at": None,
        "storage_ref": None,
    }
    if evidence_class == "materialized_empirical_panel":
        materialization = {
            "evidence_class": evidence_class,
            "status": "materialized",
            "authorization_ref": "authorization:test-panel-v1",
            "materialized_at": "2026-07-23T00:00:00Z",
            "storage_ref": "sha256-bound:test-panel.parquet",
        }
    return build_longitudinal_panel_validation_contract(
        source_contract=source,
        panel_rows=_panel_rows() if panel_rows is None else panel_rows,
        network_rows=_network_rows() if network_rows is None else network_rows,
        field_mapping=_field_mapping(),
        network_field_mapping=_network_field_mapping(),
        temporal_policy={
            "index_treatment_time": "2026-03-01T00:00:00Z",
            "minimum_pre_periods": 2,
            "minimum_post_periods": 2,
            "network_time_mode": "lagged_dynamic",
        },
        missingness_policy={
            "declared": True,
            "strategy": "explicit_censoring_indicator",
            "allowed_missing_fields": ["outcome"],
            "censoring_indicator_field": "censored",
            "censoring_value_when_missing": 1,
        },
        materialization=materialization,
        provenance=_provenance(source),
    )


def test_synthetic_rows_validate_the_validator_but_never_open_empirical_gates():
    contract = _validation_contract()
    validation = validate_longitudinal_panel_validation_contract(contract)
    gates = seed_spatiotemporal_gate_evidence_from_panel_validation(contract)

    assert validation["valid"] is True
    assert validation["row_validation_ready"] is True
    assert validation["empirical_panel_evidence_ready"] is False
    assert all(
        gates[name]["passed"] is False
        for name in (*LONGITUDINAL_DESIGN_GATES, *LONGITUDINAL_ESTIMATION_GATES)
    )
    assert validation["causal_estimation_admitted"] is False
    assert validation["gwm_k0_validated"] is False


def test_hash_bound_empirical_panel_only_opens_directly_demonstrated_gates():
    contract = _validation_contract(
        evidence_class="materialized_empirical_panel"
    )
    validation = validate_longitudinal_panel_validation_contract(contract)
    gates = seed_spatiotemporal_gate_evidence_from_panel_validation(contract)

    assert validation["valid"] is True
    assert validation["empirical_panel_evidence_ready"] is True
    for gate in (
        "unit_time_index_unique",
        "temporal_order_verified",
        "treatment_precedes_outcome",
        "pre_treatment_covariates_verified",
        "time_varying_confounders_measured",
        "interference_exposure_mapping_versioned",
        "network_time_alignment_verified",
        "no_future_information_leakage",
        "observed_policy_outcome_available",
    ):
        assert gates[gate]["passed"] is True
        assert gates[gate]["evidence_refs"]
    assert gates["treatment_confounder_feedback_declared"]["passed"] is False
    assert gates["positivity_by_time_diagnosed"]["passed"] is False
    assert gates["censoring_and_missingness_diagnosed"]["passed"] is False
    assert gates["longitudinal_estimator_executed"]["passed"] is False
    assert validation["causal_identification_ready"] is False
    assert validation["effect_application_admitted"] is False


def test_empirical_panel_evidence_keeps_design_and_estimation_gaps_explicit():
    panel_contract = _validation_contract(
        evidence_class="materialized_empirical_panel"
    )
    gates = seed_spatiotemporal_gate_evidence_from_panel_validation(
        panel_contract
    )
    fixture = _spatiotemporal_design_fixture(
        design_ready=False, estimation_ready=False
    )
    design = build_spatiotemporal_causal_design_contract(
        study=fixture["study"],
        estimand=fixture["estimand"],
        panel_design=fixture["panel_design"],
        temporal_ordering=fixture["temporal_ordering"],
        interference_mapping=fixture["interference_mapping"],
        identification=fixture["identification"],
        gate_evidence=gates,
        provenance=fixture["provenance"],
    )
    validation = validate_spatiotemporal_causal_design_contract(design)

    assert validation["valid"] is True
    assert validation["blocking_design_gates"] == [
        "treatment_confounder_feedback_declared",
        "positivity_by_time_diagnosed",
        "censoring_and_missingness_diagnosed",
    ]
    assert validation["longitudinal_design_ready"] is False
    assert validation["observed_policy_outcome_ready"] is True
    assert validation["estimator_execution_ready"] is False
    assert validation["effect_application_admitted"] is False


def test_duplicate_unit_time_is_a_noncompensatory_row_blocker():
    rows = _panel_rows()
    rows.append(deepcopy(rows[0]))
    contract = _validation_contract(
        evidence_class="materialized_empirical_panel", panel_rows=rows
    )
    validation = validate_longitudinal_panel_validation_contract(contract)

    assert validation["valid"] is True
    assert contract["audit"]["unit_time_index_unique"]["passed"] is False
    assert validation["row_validation_ready"] is False
    assert validation["empirical_panel_evidence_ready"] is False
    assert "unit_time_index_unique" in validation["blocking_checks"]


def test_panel_without_an_observed_treatment_event_cannot_pass_crosswalk():
    rows = _panel_rows()
    for row in rows:
        row["treatment"] = 0
    contract = _validation_contract(
        evidence_class="materialized_empirical_panel", panel_rows=rows
    )
    validation = validate_longitudinal_panel_validation_contract(contract)

    assert validation["valid"] is True
    assert contract["audit"]["treatment_to_unit_crosswalk_integrity"][
        "passed"
    ] is False
    assert validation["empirical_panel_evidence_ready"] is False


def test_future_feature_availability_closes_leakage_gate():
    rows = _panel_rows()
    rows[0]["feature_available_at"] = rows[0]["outcome_time"]
    contract = _validation_contract(
        evidence_class="materialized_empirical_panel", panel_rows=rows
    )
    validation = validate_longitudinal_panel_validation_contract(contract)

    assert validation["valid"] is True
    assert contract["audit"]["no_future_information_leakage"]["passed"] is False
    assert validation["empirical_panel_evidence_ready"] is False


def test_dynamic_network_version_must_match_each_unit_time_row():
    rows = _panel_rows()
    rows[0]["network_version"] = "future-network"
    contract = _validation_contract(
        evidence_class="materialized_empirical_panel", panel_rows=rows
    )
    validation = validate_longitudinal_panel_validation_contract(contract)

    assert validation["valid"] is True
    assert contract["audit"]["network_vintage_alignment_verified"]["passed"] is False
    assert validation["empirical_panel_evidence_ready"] is False


def test_missing_outcome_requires_matching_censoring_declaration():
    rows = _panel_rows()
    rows[0]["outcome"] = None
    rows[0]["censored"] = 0
    contract = _validation_contract(
        evidence_class="materialized_empirical_panel", panel_rows=rows
    )
    validation = validate_longitudinal_panel_validation_contract(contract)

    assert validation["valid"] is True
    assert contract["audit"]["missingness_and_censoring_declared"]["passed"] is False
    assert validation["empirical_panel_evidence_ready"] is False


def test_source_readiness_cannot_be_replaced_by_clean_panel_rows():
    source = _source_contract(crosswalks_ready=False)
    contract = _validation_contract(
        evidence_class="materialized_empirical_panel", source_contract=source
    )
    validation = validate_longitudinal_panel_validation_contract(contract)

    assert validation["valid"] is True
    assert validation["row_validation_ready"] is True
    assert validation["source_panel_materialization_ready"] is False
    assert validation["empirical_panel_evidence_ready"] is False


def test_source_hash_coverage_and_contract_digest_are_enforced():
    contract = _validation_contract()
    missing_source = next(iter(contract["provenance"]["source_artifact_hashes"]))
    del contract["provenance"]["source_artifact_hashes"][missing_source]
    rebuilt = build_longitudinal_panel_validation_contract(
        source_contract=contract["source_contract"],
        panel_rows=_panel_rows(),
        network_rows=_network_rows(),
        field_mapping=contract["field_mapping"],
        network_field_mapping=contract["network_field_mapping"],
        temporal_policy=contract["temporal_policy"],
        missingness_policy=contract["missingness_policy"],
        materialization=contract["materialization"],
        provenance=contract["provenance"],
    )
    validation = validate_longitudinal_panel_validation_contract(rebuilt)
    assert validation["valid"] is True
    assert rebuilt["audit"]["source_hash_coverage_complete"]["passed"] is False
    assert validation["row_validation_ready"] is False

    tampered = deepcopy(_validation_contract())
    tampered["row_manifest"]["panel_row_count"] += 1
    validation = validate_longitudinal_panel_validation_contract(tampered)
    assert validation["valid"] is False
    assert "contract_digest_mismatch" in validation["errors"]


def test_audit_evidence_must_reference_current_row_manifest():
    contract = _validation_contract()
    contract["audit"]["temporal_order_verified"]["evidence_refs"] = [
        "panel_rows_sha256:" + "f" * 64
    ]
    contract["contract_digest"] = _contract_digest(contract)

    validation = validate_longitudinal_panel_validation_contract(contract)
    assert validation["valid"] is False
    assert (
        "audit_temporal_order_verified_evidence_ref_not_bound_to_manifest"
        in validation["errors"]
    )


def _contract_digest(contract: dict) -> str:
    import hashlib
    import json

    content = {
        key: value for key, value in contract.items() if key != "contract_digest"
    }
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
