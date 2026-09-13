"""Claim-safe UWM causal policy diagnostic evidence from Paper6 artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


UWM_CAUSAL_POLICY_EVIDENCE_GATE_SCHEMA = "uwm.causal_policy_evidence_gate.v1"


def build_uwm_causal_policy_evidence_gate(
    *,
    paper6_results_root: str | Path,
    gate_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Build a causal diagnostic evidence gate from actual Paper6 result files."""

    root = Path(paper6_results_root)
    arcgis_dir = root / "arcgis_sci_plus_county"
    arcgis_report_path = arcgis_dir / "arcgis_sci_plus_report.json"
    arcgis_parity_path = arcgis_dir / "arcgis_native_parity_metrics.json"
    provenance_path = arcgis_dir / "county_variable_provenance.csv"
    effect_estimates_path = arcgis_dir / "effect_estimates.csv"
    erf_curve_path = arcgis_dir / "erf_curve.csv"
    arcgis_documented_erf_curve_path = arcgis_dir / "arcgis_documented_erf_curve.csv"
    scca_path = root / "scca_county_social_capital/credibility_report.json"
    chongqing_manifest_path = root / "chongqing_uhi_analysis_manifest.json"

    arcgis_report = _read_json_if_exists(arcgis_report_path)
    arcgis_parity = _read_json_if_exists(arcgis_parity_path)
    provenance_rows = _read_csv_rows_if_exists(provenance_path)
    effect_rows = _read_csv_rows_if_exists(effect_estimates_path)
    erf_rows = _read_csv_rows_if_exists(erf_curve_path)
    documented_erf_rows = _read_csv_rows_if_exists(arcgis_documented_erf_curve_path)
    scca_report = _read_json_if_exists(scca_path)
    chongqing_manifest = _read_json_if_exists(chongqing_manifest_path)

    arcgis_slice = _arcgis_sci_plus_county_slice(
        arcgis_report=arcgis_report,
        arcgis_parity=arcgis_parity,
        provenance_rows=provenance_rows,
        effect_rows=effect_rows,
        erf_rows=erf_rows,
        documented_erf_rows=documented_erf_rows,
        source_artifact_exists=arcgis_report_path.exists()
        and arcgis_parity_path.exists()
        and provenance_path.exists()
        and effect_estimates_path.exists()
        and erf_curve_path.exists()
        and arcgis_documented_erf_curve_path.exists(),
    )
    scca_slice = _scca_county_social_capital_slice(
        scca_report,
        source_artifact_exists=scca_path.exists(),
    )
    chongqing_slice = _chongqing_uhi_analysis_slice(
        chongqing_manifest,
        source_artifact_exists=chongqing_manifest_path.exists(),
    )
    diagnostic_ready = (
        bool(arcgis_slice.get("arcgis_native_parity_ready"))
        and bool(scca_slice.get("credibility_ready"))
        and bool(chongqing_slice.get("causal_case_anchor_ready"))
    )

    limitations = [
        "not_observed_intervention_outcome",
        "third_party_county_demo_data_not_chongqing_policy_outcome",
        "provided_chongqing_analysis_sample_not_policy_intervention",
        "arcgis_plus_parity_limited_to_tested_continuous_regression_matching_mode",
        "spatial_bias_bound_unavailable_for_county_demo_without_geometry",
    ]
    gate = {
        "schema": UWM_CAUSAL_POLICY_EVIDENCE_GATE_SCHEMA,
        "gate_id": gate_id,
        "created_at": created_at,
        "source_results_root": str(root),
        "source_artifacts": {
            "arcgis_sci_plus_report": str(arcgis_report_path),
            "arcgis_native_parity_metrics": str(arcgis_parity_path),
            "county_variable_provenance": str(provenance_path),
            "effect_estimates": str(effect_estimates_path),
            "erf_curve": str(erf_curve_path),
            "arcgis_documented_erf_curve": str(arcgis_documented_erf_curve_path),
            "scca_county_social_capital_credibility": str(scca_path),
            "chongqing_uhi_analysis_manifest": str(chongqing_manifest_path),
        },
        "evidence_slices": {
            "arcgis_sci_plus_county": arcgis_slice,
            "scca_county_social_capital": scca_slice,
            "chongqing_uhi_analysis": chongqing_slice,
        },
        "algorithmic_causal_diagnostic_ready": diagnostic_ready,
        "observed_local_policy_outcome_ready": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "supported_claims": _supported_claims(diagnostic_ready),
        "claim_boundary": {
            "max_claim_level": "bounded_support" if diagnostic_ready else "not_for_claim",
            "policy_outcome_claim": False,
            "rule": (
                "Paper6 real artifacts can support causal diagnostic capability for UWM policy "
                "effect validation, but they are not observed outcomes from an implemented UWM "
                "policy intervention."
            ),
        },
        "limitations": limitations,
        "remaining_gates": [
            "observed_policy_outcome_required",
            "local_policy_intervention_holdout_required",
            "scene_aligned_station_calibrated_air_quality_holdout_required",
        ],
    }
    return gate


def validate_uwm_causal_policy_evidence_gate(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate claim-safety invariants for a UWM causal policy evidence gate."""

    errors = []
    if payload.get("schema") != UWM_CAUSAL_POLICY_EVIDENCE_GATE_SCHEMA:
        errors.append("schema_mismatch")
    if payload.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim_must_be_false")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim_must_be_false")
    if payload.get("observed_local_policy_outcome_ready") is not False:
        errors.append("observed_local_policy_outcome_ready_must_be_false")
    if payload.get("algorithmic_causal_diagnostic_ready"):
        slices = payload.get("evidence_slices") or {}
        if not (slices.get("arcgis_sci_plus_county") or {}).get("arcgis_native_parity_ready"):
            errors.append("arcgis_native_parity_required")
        if not (slices.get("scca_county_social_capital") or {}).get("credibility_ready"):
            errors.append("scca_credibility_required")
        if not (slices.get("chongqing_uhi_analysis") or {}).get("causal_case_anchor_ready"):
            errors.append("chongqing_uhi_anchor_required")
    for claim in payload.get("supported_claims") or []:
        if claim.get("policy_outcome_claim") is not False:
            errors.append("supported_claim_policy_outcome_must_be_false")
    return {"valid": not errors, "errors": errors}


def _arcgis_sci_plus_county_slice(
    *,
    arcgis_report: dict[str, Any],
    arcgis_parity: dict[str, Any],
    provenance_rows: list[dict[str, str]],
    effect_rows: list[dict[str, str]],
    erf_rows: list[dict[str, str]],
    documented_erf_rows: list[dict[str, str]],
    source_artifact_exists: bool,
) -> dict[str, Any]:
    report_parity = arcgis_report.get("arcgis_sci_parity") or {}
    algorithm = report_parity.get("algorithm") or {}
    matching = algorithm.get("matching") or {}
    balance = algorithm.get("balance") or {}
    erf = algorithm.get("erf") or {}
    data_provenance = arcgis_report.get("data_provenance") or {}
    geo_extensions = arcgis_report.get("geo_causal_extensions") or {}
    spatial_risk = geo_extensions.get("spatial_risk") or {}
    sample_parity = arcgis_parity.get("sample_parity") or {}
    parameter_parity = arcgis_parity.get("parameter_parity") or {}
    balance_parity = arcgis_parity.get("balance_parity") or {}
    erf_response_parity = arcgis_parity.get("erf_response_parity") or {}
    effect_statuses = sorted(
        {
            str(row.get("status") or "")
            for row in effect_rows
            if str(row.get("status") or "")
        }
    )
    arcgis_native_parity_ready = (
        source_artifact_exists
        and report_parity.get("status") == "ok"
        and _safe_int(sample_parity.get("arcgis_original_n")) == _safe_int(sample_parity.get("open_original_n"))
        and _safe_int(sample_parity.get("arcgis_final_n")) == _safe_int(sample_parity.get("open_final_n"))
        and _safe_int(parameter_parity.get("arcgis_selected_num_bins"))
        == _safe_int(parameter_parity.get("open_selected_num_bins"))
        and _safe_int(parameter_parity.get("arcgis_n_grid"))
        == _safe_int(parameter_parity.get("open_n_grid"))
        and balance_parity.get("open_passes_threshold") is True
        and _safe_float(erf_response_parity.get("mae"), default=1.0) <= 0.05
        and _safe_int(data_provenance.get("field_count")) >= 10
        and set(effect_statuses) == {"ok"}
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "scope": "arcgis_sci_plus_algorithmic_causal_diagnostic_not_policy_outcome",
        "study": arcgis_report.get("study"),
        "claim": arcgis_report.get("claim"),
        "input_rows": _safe_int(report_parity.get("input_rows")),
        "trimmed_rows": _safe_int(report_parity.get("trimmed_rows")),
        "removed_rows": _safe_int(report_parity.get("removed_rows")),
        "erf_grid_count": _safe_int(erf.get("n_grid")) or max(len(erf_rows), 1) - 1,
        "documented_erf_grid_count": max(len(documented_erf_rows), 1) - 1,
        "effective_sample_size": _safe_float(erf.get("effective_sample_size")),
        "selected_passes_balance_threshold": matching.get("selected_passes_threshold") is True,
        "selected_mean_abs_weighted_correlation": _safe_float(
            matching.get("selected_mean_abs_weighted_correlation")
        ),
        "max_abs_weighted_correlation": _safe_float(balance.get("max_abs_weighted_correlation")),
        "sample_parity": sample_parity,
        "parameter_parity": parameter_parity,
        "balance_parity": balance_parity,
        "arcgis_version": arcgis_parity.get("arcgis_version"),
        "tested_mode": arcgis_parity.get("tested_mode"),
        "arcgis_erf_response_mae": _safe_float(erf_response_parity.get("mae")),
        "arcgis_erf_response_rmse": _safe_float(erf_response_parity.get("rmse")),
        "arcgis_erf_response_max_absolute_difference": _safe_float(
            erf_response_parity.get("max_absolute_difference")
        ),
        "provenance_field_count": _safe_int(data_provenance.get("field_count")) or len(provenance_rows),
        "source_groups": data_provenance.get("source_groups") or [],
        "unresolved_fields": data_provenance.get("unresolved_fields") or [],
        "effect_estimator_statuses": effect_statuses,
        "spatial_risk_status": spatial_risk.get("status"),
        "spatial_risk_reason": spatial_risk.get("reason"),
        "arcgis_native_parity_ready": arcgis_native_parity_ready,
        "policy_outcome_claim": False,
        "claim_level": "bounded_support" if arcgis_native_parity_ready else "not_for_claim",
    }


def _scca_county_social_capital_slice(
    report: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    estimator_statuses = report.get("estimator_statuses") or {}
    credibility_ready = (
        source_artifact_exists
        and report.get("decision") == "strong_support"
        and report.get("leave_group_sign_stable") is True
        and estimator_statuses.get("baseline_adjusted_ols") == "ok"
        and estimator_statuses.get("generalized_propensity_erf") == "ok"
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "scope": "scca_causal_credibility_diagnostic_not_policy_outcome",
        "decision": report.get("decision"),
        "reasons": report.get("reasons") or [],
        "max_balance_corr": _safe_float(report.get("max_balance_corr")),
        "overlap_boundary_mass": _safe_float(report.get("overlap_boundary_mass")),
        "leave_group_sign_stable": report.get("leave_group_sign_stable") is True,
        "estimator_statuses": estimator_statuses,
        "credibility_ready": credibility_ready,
        "policy_outcome_claim": False,
        "claim_level": "bounded_support" if credibility_ready else "not_for_claim",
    }


def _chongqing_uhi_analysis_slice(
    manifest: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    metadata = manifest.get("metadata") or {}
    causal_case_anchor_ready = (
        source_artifact_exists
        and _safe_int(metadata.get("sample_size")) >= 1000
        and metadata.get("balance_interpretation") == "credible_balance"
        and str(metadata.get("study") or "").startswith("Building density -> UHI in Chongqing")
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "scope": "chongqing_real_case_causal_analysis_anchor_not_policy_intervention",
        "study": metadata.get("study"),
        "sample_size": _safe_int(metadata.get("sample_size")),
        "buildings_total": _safe_int(metadata.get("buildings_total")),
        "treatment_threshold": _safe_float(metadata.get("treatment_threshold")),
        "n_bootstrap": _safe_int(metadata.get("n_bootstrap")),
        "n_spatial_bootstrap": _safe_int(metadata.get("n_spatial_bootstrap")),
        "data_source": metadata.get("data_source"),
        "outcome_product": metadata.get("outcome_product"),
        "balance_interpretation": metadata.get("balance_interpretation"),
        "causal_case_anchor_ready": causal_case_anchor_ready,
        "policy_outcome_claim": False,
        "claim_level": "bounded_support" if causal_case_anchor_ready else "not_for_claim",
    }


def _supported_claims(diagnostic_ready: bool) -> list[dict[str, Any]]:
    if not diagnostic_ready:
        return []
    return [
        {
            "claim": "paper6_arcgis_sci_plus_real_artifact_causal_diagnostic_ready",
            "scope": "algorithmic_causal_policy_effect_validation_diagnostic_not_observed_policy_outcome",
            "claim_level": "bounded_support",
            "policy_outcome_claim": False,
            "spatial_attribution_claim": False,
        }
    ]


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _read_csv_rows_if_exists(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _safe_int(value: Any, default: int = 0) -> int:
    if value in {None, ""}:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
