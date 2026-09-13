from copy import deepcopy
import hashlib
import json

from data_agent.test_gwm_longitudinal_panel_source_contract import (
    _contract as _source_contract,
)
from data_agent.test_gwm_spatiotemporal_causal_design_contract import (
    _design_contract as _spatiotemporal_design_fixture,
)
from data_agent.uwm.geospatial_kernel import (
    build_longitudinal_causal_diagnostic_contract,
    build_longitudinal_panel_validation_contract,
    build_spatiotemporal_causal_design_contract,
    seed_spatiotemporal_gate_evidence_from_longitudinal_diagnostics,
    validate_longitudinal_causal_diagnostic_contract,
    validate_spatiotemporal_causal_design_contract,
)


PERIODS = (
    ("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z", "2026-01"),
    ("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z", "2026-02"),
    ("2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z", "2026-03"),
    ("2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z", "2026-04"),
)


def _panel_field_mapping() -> dict:
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


def _diagnostic_field_mapping() -> dict:
    return {
        "unit_id_field": "unit_id",
        "time_field": "panel_time",
        "propensity_score_field": "propensity_score",
        "treatment_numerator_probability_field": "treatment_numerator_probability",
        "treatment_weight_field": "treatment_weight",
        "censoring_survival_probability_field": "censoring_survival_probability",
        "censoring_numerator_probability_field": "censoring_numerator_probability",
        "censoring_weight_field": "censoring_weight",
        "cross_fit_fold_field": "cross_fit_fold",
        "nuisance_training_cutoff_field": "nuisance_training_cutoff",
    }


def _panel_rows() -> list[dict]:
    rows = []
    for period_index, (period_start, outcome_time, version) in enumerate(PERIODS):
        for unit_index in range(8):
            confounder = float(unit_index // 2) + period_index / 10.0
            rows.append(
                {
                    "unit_id": f"u{unit_index}",
                    "panel_time": period_start,
                    "treatment": (unit_index + period_index) % 2,
                    "treatment_time": period_start.replace(
                        "00:00:00", "12:00:00"
                    ),
                    "outcome": 10.0 + unit_index,
                    "outcome_time": outcome_time,
                    "baseline_state": float(unit_index // 2),
                    "confounder_t": confounder,
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
    for period_start, valid_to, version in PERIODS:
        for unit_index in range(8):
            rows.append(
                {
                    "from_unit_id": f"u{unit_index}",
                    "to_unit_id": f"u{(unit_index + 1) % 8}",
                    "valid_from": period_start,
                    "valid_to": valid_to,
                    "network_source_id": "source-interference_network",
                    "network_version": version,
                }
            )
    return rows


def _diagnostic_rows(panel_rows: list[dict]) -> list[dict]:
    rows = []
    for panel in panel_rows:
        unit_index = int(panel["unit_id"][1:])
        rows.append(
            {
                "unit_id": panel["unit_id"],
                "panel_time": panel["panel_time"],
                "propensity_score": 0.5,
                "treatment_numerator_probability": 0.5,
                "treatment_weight": 1.0,
                "censoring_survival_probability": 0.95,
                "censoring_numerator_probability": 0.95
                if panel["censored"] == 0
                else 0.05,
                "censoring_weight": 1.0,
                "cross_fit_fold": f"fold-{unit_index % 2}",
                "nuisance_training_cutoff": "2025-12-31T00:00:00Z",
            }
        )
    return rows


def _panel_contract(
    *,
    evidence_class: str,
    panel_rows: list[dict],
) -> dict:
    source = _source_contract()
    materialization = {
        "evidence_class": "synthetic_fixture",
        "status": "synthetic_only",
        "authorization_ref": None,
        "materialized_at": None,
        "storage_ref": None,
    }
    if evidence_class == "materialized_empirical_panel":
        materialization = {
            "evidence_class": evidence_class,
            "status": "materialized",
            "authorization_ref": "authorization:diagnostic-fixture-v1",
            "materialized_at": "2026-07-23T00:00:00Z",
            "storage_ref": "sha256-bound:diagnostic-panel.parquet",
        }
    return build_longitudinal_panel_validation_contract(
        source_contract=source,
        panel_rows=panel_rows,
        network_rows=_network_rows(),
        field_mapping=_panel_field_mapping(),
        network_field_mapping=_network_field_mapping(),
        temporal_policy={
            "index_treatment_time": "2026-03-01T00:00:00Z",
            "minimum_pre_periods": 2,
            "minimum_post_periods": 2,
            "network_time_mode": "lagged_dynamic",
        },
        missingness_policy={
            "declared": True,
            "strategy": "time_specific_inverse_probability_weights",
            "allowed_missing_fields": ["outcome"],
            "censoring_indicator_field": "censored",
            "censoring_value_when_missing": 1,
        },
        materialization=materialization,
        provenance={
            "validator_version": "gwm-longitudinal-panel-validator-v1",
            "generated_at": "2026-07-23T00:00:00Z",
            "source_artifact_hashes": {
                source_row["source_id"]: str(index + 1) * 64
                for index, source_row in enumerate(source["sources"])
            },
        },
    )


def _thresholds() -> dict:
    return {
        "minimum_propensity": 0.05,
        "maximum_propensity": 0.95,
        "minimum_treated_per_time": 3,
        "minimum_control_per_time": 3,
        "maximum_absolute_standardized_mean_difference": 0.1,
        "maximum_treatment_weight": 10.0,
        "maximum_treatment_weight_cv": 2.0,
        "minimum_treatment_effective_sample_size_fraction": 0.25,
        "maximum_censoring_rate": 0.5,
        "minimum_censoring_survival_probability": 0.05,
        "maximum_censoring_weight": 10.0,
        "maximum_combined_weight": 20.0,
        "maximum_combined_weight_cv": 2.0,
        "minimum_combined_effective_sample_size_fraction": 0.2,
        "maximum_weight_formula_absolute_error": 0.000001,
    }


def _diagnostic_contract(
    *,
    evidence_class: str = "synthetic_fixture",
    panel_rows: list[dict] | None = None,
    diagnostic_rows: list[dict] | None = None,
) -> dict:
    panel = _panel_rows() if panel_rows is None else panel_rows
    diagnostics = (
        _diagnostic_rows(panel) if diagnostic_rows is None else diagnostic_rows
    )
    return build_longitudinal_causal_diagnostic_contract(
        panel_validation_contract=_panel_contract(
            evidence_class=evidence_class,
            panel_rows=panel,
        ),
        panel_rows=panel,
        diagnostic_rows=diagnostics,
        field_mapping=_diagnostic_field_mapping(),
        analysis={
            "weighting_estimand": "ate",
            "risk_set": "all_panel_rows",
            "weight_formula": (
                "stabilized_observed_action_and_status_probability_ratio"
            ),
            "balance_confounder_fields": [
                "baseline_state",
                "confounder_t",
            ],
            "observed_censoring_indicator_value": 0,
            "nuisance_estimation": {
                "strategy": "unit_grouped_forward_chaining_cross_fit",
                "cross_fitted": True,
                "fold_count": 2,
                "unit_grouped": True,
                "temporal_order_preserved": True,
            },
        },
        thresholds=_thresholds(),
        provenance={
            "diagnostic_runner_version": "gwm-longitudinal-diagnostics-v1",
            "generated_at": "2026-07-23T00:00:00Z",
            "propensity_model_ref": "synthetic:propensity-model",
            "propensity_model_sha256": "a" * 64,
            "censoring_model_ref": "synthetic:censoring-model",
            "censoring_model_sha256": "b" * 64,
        },
    )


def test_synthetic_diagnostics_execute_but_cannot_open_empirical_gates():
    contract = _diagnostic_contract()
    validation = validate_longitudinal_causal_diagnostic_contract(contract)
    gates = seed_spatiotemporal_gate_evidence_from_longitudinal_diagnostics(
        contract
    )

    assert validation["valid"] is True
    assert validation["diagnostic_execution_ready"] is True
    assert validation["empirical_diagnostic_evidence_ready"] is False
    assert validation["all_diagnostic_thresholds_passed"] is False
    assert gates["positivity_by_time_diagnosed"]["passed"] is False
    assert gates["sequential_balance_passed"]["passed"] is False
    assert gates["weight_stability_passed"]["passed"] is False
    assert validation["effect_application_admitted"] is False


def test_empirical_diagnostics_open_only_direct_diagnostic_gates():
    contract = _diagnostic_contract(
        evidence_class="materialized_empirical_panel"
    )
    validation = validate_longitudinal_causal_diagnostic_contract(contract)
    gates = seed_spatiotemporal_gate_evidence_from_longitudinal_diagnostics(
        contract
    )

    assert validation["valid"] is True
    assert validation["empirical_diagnostic_evidence_ready"] is True
    assert validation["all_diagnostic_thresholds_passed"] is True
    for gate in (
        "positivity_by_time_diagnosed",
        "censoring_and_missingness_diagnosed",
        "sequential_balance_passed",
        "weight_stability_passed",
    ):
        assert gates[gate]["passed"] is True
        assert gates[gate]["evidence_refs"]
    assert gates["treatment_confounder_feedback_declared"]["passed"] is False
    assert gates["longitudinal_estimator_executed"]["passed"] is False
    assert validation["causal_identification_ready"] is False
    assert validation["gwm_k0_validated"] is False


def test_diagnostics_leave_feedback_and_outcome_estimation_as_design_blockers():
    diagnostic_contract = _diagnostic_contract(
        evidence_class="materialized_empirical_panel"
    )
    gates = seed_spatiotemporal_gate_evidence_from_longitudinal_diagnostics(
        diagnostic_contract
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
        "treatment_confounder_feedback_declared"
    ]
    assert validation["longitudinal_design_ready"] is False
    assert validation["blocking_estimation_gates"] == [
        "longitudinal_estimator_executed",
        "pretrend_or_preperiod_stability_passed",
        "temporal_placebo_passed",
        "geographic_holdout_passed",
        "uncertainty_estimated",
    ]
    assert validation["estimator_execution_ready"] is False
    assert validation["effect_application_admitted"] is False


def test_extreme_propensity_is_recorded_as_threshold_failure():
    panel = _panel_rows()
    diagnostics = _diagnostic_rows(panel)
    diagnostics[0]["propensity_score"] = 0.99
    diagnostics[0]["treatment_weight"] = 50.0
    contract = _diagnostic_contract(
        evidence_class="materialized_empirical_panel",
        panel_rows=panel,
        diagnostic_rows=diagnostics,
    )
    validation = validate_longitudinal_causal_diagnostic_contract(contract)
    gates = seed_spatiotemporal_gate_evidence_from_longitudinal_diagnostics(
        contract
    )

    assert validation["valid"] is True
    assert validation["empirical_diagnostic_evidence_ready"] is True
    assert validation["positivity_by_time_ready"] is False
    assert "positivity_by_time_passed" in validation[
        "blocking_threshold_checks"
    ]
    assert gates["positivity_by_time_diagnosed"]["passed"] is False
    assert gates["positivity_by_time_diagnosed"]["evidence_refs"]


def test_sequential_imbalance_is_noncompensatory():
    panel = _panel_rows()
    for row in panel:
        unit_index = int(row["unit_id"][1:])
        row["confounder_t"] = (
            10.0 + unit_index if row["treatment"] == 1 else float(unit_index)
        )
    contract = _diagnostic_contract(
        evidence_class="materialized_empirical_panel",
        panel_rows=panel,
    )
    validation = validate_longitudinal_causal_diagnostic_contract(contract)

    assert validation["valid"] is True
    assert validation["sequential_balance_ready"] is False
    assert contract["checks"]["sequential_balance_passed"]["passed"] is False
    assert validation["all_diagnostic_thresholds_passed"] is False


def test_extreme_weights_close_treatment_and_combined_weight_gates():
    panel = _panel_rows()
    diagnostics = _diagnostic_rows(panel)
    diagnostics[0]["propensity_score"] = 0.99
    diagnostics[0]["treatment_numerator_probability"] = 0.5
    diagnostics[0]["treatment_weight"] = 50.0
    contract = _diagnostic_contract(
        evidence_class="materialized_empirical_panel",
        panel_rows=panel,
        diagnostic_rows=diagnostics,
    )
    validation = validate_longitudinal_causal_diagnostic_contract(contract)
    gates = seed_spatiotemporal_gate_evidence_from_longitudinal_diagnostics(
        contract
    )

    assert validation["valid"] is True
    assert validation["treatment_weight_stability_ready"] is False
    assert validation["combined_weight_stability_ready"] is False
    assert gates["weight_stability_passed"]["passed"] is False


def test_reported_weight_must_match_probability_formula():
    panel = _panel_rows()
    diagnostics = _diagnostic_rows(panel)
    diagnostics[0]["treatment_weight"] = 2.0
    contract = _diagnostic_contract(
        evidence_class="materialized_empirical_panel",
        panel_rows=panel,
        diagnostic_rows=diagnostics,
    )
    validation = validate_longitudinal_causal_diagnostic_contract(contract)

    assert validation["valid"] is True
    assert contract["checks"]["weight_formula_consistency_verified"][
        "passed"
    ] is False
    assert validation["diagnostic_execution_ready"] is False
    assert validation["empirical_diagnostic_evidence_ready"] is False


def test_censoring_probability_and_ipcw_are_a_separate_gate():
    panel = _panel_rows()
    panel[0]["outcome"] = None
    panel[0]["censored"] = 1
    diagnostics = _diagnostic_rows(panel)
    diagnostics[0]["censoring_survival_probability"] = 0.01
    diagnostics[0]["censoring_numerator_probability"] = 0.05
    diagnostics[0]["censoring_weight"] = 0.05 / 0.99
    contract = _diagnostic_contract(
        evidence_class="materialized_empirical_panel",
        panel_rows=panel,
        diagnostic_rows=diagnostics,
    )
    validation = validate_longitudinal_causal_diagnostic_contract(contract)
    gates = seed_spatiotemporal_gate_evidence_from_longitudinal_diagnostics(
        contract
    )

    assert validation["valid"] is True
    assert validation["censoring_diagnostic_ready"] is False
    assert gates["censoring_and_missingness_diagnosed"]["passed"] is False
    assert validation["effect_application_admitted"] is False


def test_missing_diagnostic_index_fails_execution_without_throwing():
    panel = _panel_rows()
    diagnostics = _diagnostic_rows(panel)[:-1]
    contract = _diagnostic_contract(
        evidence_class="materialized_empirical_panel",
        panel_rows=panel,
        diagnostic_rows=diagnostics,
    )
    validation = validate_longitudinal_causal_diagnostic_contract(contract)

    assert validation["valid"] is True
    assert validation["diagnostic_execution_ready"] is False
    assert validation["empirical_diagnostic_evidence_ready"] is False
    assert contract["checks"]["diagnostic_index_unique_complete"][
        "passed"
    ] is False


def test_future_nuisance_training_cutoff_fails_cross_fit_verification():
    panel = _panel_rows()
    diagnostics = _diagnostic_rows(panel)
    diagnostics[0]["nuisance_training_cutoff"] = diagnostics[0]["panel_time"]
    contract = _diagnostic_contract(
        evidence_class="materialized_empirical_panel",
        panel_rows=panel,
        diagnostic_rows=diagnostics,
    )
    validation = validate_longitudinal_causal_diagnostic_contract(contract)

    assert validation["valid"] is True
    assert validation["diagnostic_execution_ready"] is False
    assert "nuisance_cross_fitting_verified" in validation[
        "blocking_execution_checks"
    ]
    assert validation["empirical_diagnostic_evidence_ready"] is False


def test_manifest_evidence_and_contract_digest_are_tamper_evident():
    contract = _diagnostic_contract()
    contract["checks"]["positivity_by_time_passed"]["evidence_refs"] = [
        "diagnostic_rows_sha256:" + "f" * 64
    ]
    contract["contract_digest"] = _contract_digest(contract)
    validation = validate_longitudinal_causal_diagnostic_contract(contract)

    assert validation["valid"] is False
    assert (
        "checks_positivity_by_time_passed_evidence_ref_not_bound"
        in validation["errors"]
    )

    tampered = deepcopy(_diagnostic_contract())
    tampered["thresholds"]["maximum_propensity"] = 0.9
    validation = validate_longitudinal_causal_diagnostic_contract(tampered)
    assert validation["valid"] is False
    assert "contract_digest_mismatch" in validation["errors"]


def _contract_digest(contract: dict) -> str:
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
