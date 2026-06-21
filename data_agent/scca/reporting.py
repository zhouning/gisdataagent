from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from .specs import SCCAPaths, StudySpec


def _json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if np.isfinite(numeric) else None
    return value


def _read_json(path: object) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))  # type: ignore[attr-defined]
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _finite_float(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _format_float(value: object, *, digits: int = 3) -> str:
    numeric = _finite_float(value)
    if numeric is None:
        return "not estimable"
    if numeric != 0 and abs(numeric) < 0.001:
        return f"{numeric:.2e}"
    return f"{numeric:.{digits}f}"


def _format_p(value: object) -> str:
    numeric = _finite_float(value)
    if numeric is None:
        return "not estimable"
    if numeric < 0.001:
        return "<0.001"
    return f"{numeric:.3f}"


def _estimator_row(estimates: pd.DataFrame, estimator: str) -> dict[str, Any]:
    if estimates.empty or "estimator" not in estimates.columns:
        return {}
    rows = estimates.loc[estimates["estimator"].astype(str) == estimator]
    if rows.empty:
        return {}
    return rows.iloc[0].to_dict()


def _read_effect_estimates(paths: SCCAPaths) -> pd.DataFrame:
    if not paths.effect_estimates.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(paths.effect_estimates)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame()


def collect_result_summary(paths: SCCAPaths) -> dict[str, Any]:
    estimates = _read_effect_estimates(paths)
    baseline = _estimator_row(estimates, "baseline_adjusted_ols")
    spatial = _estimator_row(estimates, "spatial_neighbor_adjusted_ols")
    spatial_lag = _estimator_row(estimates, "spatial_lag_adjusted_ols")
    spatial_diagnostics = _read_json(paths.spatial_diagnostics)
    spatial_bootstrap = _read_json(paths.spatial_bootstrap_summary)
    graph_sensitivity = _read_json(paths.spatial_graph_sensitivity_summary)
    spatial_slx = _read_json(paths.spatial_slx_summary)
    spillover = _read_json(paths.spatial_spillover_summary)
    exposure_mapping = _read_json(paths.spatial_exposure_mapping_summary)

    summary: dict[str, Any] = {}
    baseline_coef = _finite_float(baseline.get("coef")) if baseline else None
    if baseline:
        summary["baseline_adjusted_ols"] = {
            "status": baseline.get("status"),
            "coef": baseline_coef,
            "p_value": _finite_float(baseline.get("p_value")),
            "ci_lower": _finite_float(baseline.get("ci_lower")),
            "ci_upper": _finite_float(baseline.get("ci_upper")),
            "n": _finite_float(baseline.get("n")),
        }

    if spatial:
        summary["spatial_neighbor_adjusted_ols"] = {
            "status": spatial.get("status"),
            "coef": _finite_float(spatial.get("coef")),
            "neighbor_exposure_coef": _finite_float(spatial.get("neighbor_exposure_coef")),
            "neighbor_exposure_p_value": _finite_float(spatial.get("neighbor_exposure_p_value")),
            "coef_delta": _finite_float(spatial.get("coef_delta")),
            "relative_change": _finite_float(spatial.get("relative_change")),
            "sign_stable": spatial.get("sign_stable"),
            "n": _finite_float(spatial.get("n")),
        }

    if spatial_lag:
        summary["spatial_lag_adjusted_ols"] = {
            "status": spatial_lag.get("status"),
            "coef": _finite_float(spatial_lag.get("coef")),
            "neighbor_exposure_coef": _finite_float(spatial_lag.get("neighbor_exposure_coef")),
            "neighbor_exposure_p_value": _finite_float(spatial_lag.get("neighbor_exposure_p_value")),
            "coef_delta": _finite_float(spatial_lag.get("coef_delta")),
            "relative_change": _finite_float(spatial_lag.get("relative_change")),
            "sign_stable": spatial_lag.get("sign_stable"),
            "lag_covariate_count": _finite_float(spatial_lag.get("lag_covariate_count")),
            "lag_covariates_significant": _finite_float(spatial_lag.get("lag_covariates_significant")),
            "n": _finite_float(spatial_lag.get("n")),
        }

    if spatial_slx:
        summary["spatial_slx_model"] = {
            "status": spatial_slx.get("status"),
            "model": spatial_slx.get("model"),
            "direct_effect": _finite_float(spatial_slx.get("direct_effect")),
            "direct_p_value": _finite_float(spatial_slx.get("direct_p_value")),
            "indirect_effect": _finite_float(spatial_slx.get("indirect_effect")),
            "indirect_p_value": _finite_float(spatial_slx.get("indirect_p_value")),
            "total_effect": _finite_float(spatial_slx.get("total_effect")),
            "total_se": _finite_float(spatial_slx.get("total_se")),
            "total_p_value": _finite_float(spatial_slx.get("total_p_value")),
            "total_ci_lower": _finite_float(spatial_slx.get("total_ci_lower")),
            "total_ci_upper": _finite_float(spatial_slx.get("total_ci_upper")),
            "r_squared": _finite_float(spatial_slx.get("r_squared")),
            "lag_covariate_count": _finite_float(spatial_slx.get("lag_covariate_count")),
            "lag_covariates_significant": _finite_float(spatial_slx.get("lag_covariates_significant")),
            "coefficient_count": _finite_float(spatial_slx.get("coefficient_count")),
            "n": _finite_float(spatial_slx.get("n")),
            "interpretation": spatial_slx.get("interpretation"),
        }

    if spatial_diagnostics:
        residual = spatial_diagnostics.get("residual_moran", {})
        exposure = spatial_diagnostics.get("exposure_moran", {})
        graph = spatial_diagnostics.get("graph", {})
        summary["spatial_diagnostics"] = {
            "graph_method": graph.get("method") if isinstance(graph, dict) else None,
            "edge_count": graph.get("edge_count") if isinstance(graph, dict) else None,
            "exposure_moran_i": _finite_float(exposure.get("moran_i")) if isinstance(exposure, dict) else None,
            "exposure_moran_p_value": _finite_float(exposure.get("permutation_p_value"))
            if isinstance(exposure, dict)
            else None,
            "residual_moran_i": _finite_float(residual.get("moran_i")) if isinstance(residual, dict) else None,
            "residual_moran_p_value": _finite_float(residual.get("permutation_p_value"))
            if isinstance(residual, dict)
            else None,
            "interpretation": spatial_diagnostics.get("interpretation"),
        }

    if spatial_bootstrap:
        summary["spatial_block_bootstrap"] = spatial_bootstrap
    if graph_sensitivity:
        summary["spatial_graph_sensitivity"] = graph_sensitivity
    if spillover:
        summary["spatial_spillover_decomposition"] = spillover
    if exposure_mapping:
        summary["spatial_exposure_mapping"] = exposure_mapping
    return summary


def _summary_lines(summary: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    baseline = summary.get("baseline_adjusted_ols")
    if isinstance(baseline, dict):
        lines.append(
            "Baseline adjusted OLS estimates the main exposure coefficient at "
            f"{_format_float(baseline.get('coef'))} "
            f"(95% CI {_format_float(baseline.get('ci_lower'))} to "
            f"{_format_float(baseline.get('ci_upper'))}, p={_format_p(baseline.get('p_value'))})."
        )

    spatial = summary.get("spatial_neighbor_adjusted_ols")
    if isinstance(spatial, dict):
        lines.append(
            "After adding neighboring exposure, the main coefficient is "
            f"{_format_float(spatial.get('coef'))}; the neighbor-exposure coefficient is "
            f"{_format_float(spatial.get('neighbor_exposure_coef'))} "
            f"(p={_format_p(spatial.get('neighbor_exposure_p_value'))})."
        )
        relative_change = _finite_float(spatial.get("relative_change"))
        if relative_change is not None:
            lines.append(
                "The spatial adjustment changes the main coefficient by "
                f"{relative_change * 100:.1f}% and sign stability is "
                f"{spatial.get('sign_stable')}."
            )

    spatial_lag = summary.get("spatial_lag_adjusted_ols")
    if isinstance(spatial_lag, dict):
        lines.append(
            "After additionally adjusting neighboring covariates/context, the main coefficient is "
            f"{_format_float(spatial_lag.get('coef'))}; the neighbor-exposure coefficient is "
            f"{_format_float(spatial_lag.get('neighbor_exposure_coef'))} "
            f"(p={_format_p(spatial_lag.get('neighbor_exposure_p_value'))})."
        )
        lag_count = _finite_float(spatial_lag.get("lag_covariate_count"))
        if lag_count is not None:
            lines.append(
                "The richer spatial lag model includes "
                f"{int(lag_count)} neighboring covariate/context lags, with "
                f"{int(_finite_float(spatial_lag.get('lag_covariates_significant')) or 0)} significant at p<=0.05."
            )

    spatial_slx = summary.get("spatial_slx_model")
    if isinstance(spatial_slx, dict):
        lines.append(
            "Formal SLX output gives direct effect "
            f"{_format_float(spatial_slx.get('direct_effect'))} and indirect effect "
            f"{_format_float(spatial_slx.get('indirect_effect'))} "
            f"(p={_format_p(spatial_slx.get('indirect_p_value'))}), for total effect "
            f"{_format_float(spatial_slx.get('total_effect'))} "
            f"(95% CI {_format_float(spatial_slx.get('total_ci_lower'))} to "
            f"{_format_float(spatial_slx.get('total_ci_upper'))}, "
            f"p={_format_p(spatial_slx.get('total_p_value'))})."
        )
        lag_count = _finite_float(spatial_slx.get("lag_covariate_count"))
        coef_count = _finite_float(spatial_slx.get("coefficient_count"))
        if lag_count is not None and coef_count is not None:
            lines.append(
                "The SLX coefficient table contains "
                f"{int(coef_count)} terms, including {int(lag_count)} neighboring covariate/context lags."
            )

    diagnostics = summary.get("spatial_diagnostics")
    if isinstance(diagnostics, dict):
        lines.append(
            "Spatial diagnostics use "
            f"{diagnostics.get('graph_method') or 'an unavailable graph'} with "
            f"{diagnostics.get('edge_count') if diagnostics.get('edge_count') is not None else 'unknown'} edges; "
            f"exposure Moran's I is {_format_float(diagnostics.get('exposure_moran_i'))} "
            f"(p={_format_p(diagnostics.get('exposure_moran_p_value'))}) and residual Moran's I is "
            f"{_format_float(diagnostics.get('residual_moran_i'))} "
            f"(p={_format_p(diagnostics.get('residual_moran_p_value'))})."
        )

    bootstrap = summary.get("spatial_block_bootstrap")
    if isinstance(bootstrap, dict):
        if bootstrap.get("status") == "ok":
            lines.append(
                "Spatial block bootstrap validates the neighbor-adjusted coefficient with "
                f"{bootstrap.get('n_replicates_valid')} valid replicates: median "
                f"{_format_float(bootstrap.get('coef_median'))}, 95% interval "
                f"{_format_float(bootstrap.get('ci_lower_2_5'))} to "
                f"{_format_float(bootstrap.get('ci_upper_97_5'))}, sign stability "
                f"{_format_float(bootstrap.get('sign_stability'))}."
            )
        else:
            warning = bootstrap.get("warning") or "no finite bootstrap estimates were produced"
            lines.append(f"Spatial block bootstrap is not estimable: {warning}.")

    graph_sensitivity = summary.get("spatial_graph_sensitivity")
    if isinstance(graph_sensitivity, dict):
        if graph_sensitivity.get("status") == "ok":
            lines.append(
                "Spatial graph sensitivity across "
                f"{graph_sensitivity.get('n_graphs_valid')} coordinate-kNN specifications gives "
                f"neighbor-adjusted coefficient range "
                f"{_format_float(graph_sensitivity.get('neighbor_adjusted_coef_min'))} to "
                f"{_format_float(graph_sensitivity.get('neighbor_adjusted_coef_max'))}, "
                f"with sign stability {graph_sensitivity.get('neighbor_adjusted_sign_stability')}."
            )
            if graph_sensitivity.get("spatial_lag_adjusted_coef_min") is not None:
                lines.append(
                    "For the richer spatial-lag model, the coefficient range across graph specifications is "
                    f"{_format_float(graph_sensitivity.get('spatial_lag_adjusted_coef_min'))} to "
                    f"{_format_float(graph_sensitivity.get('spatial_lag_adjusted_coef_max'))}."
                )
        else:
            warning = graph_sensitivity.get("warning") or "graph sensitivity analysis was not estimable"
            lines.append(f"Spatial graph sensitivity is not estimable: {warning}.")

    spillover = summary.get("spatial_spillover_decomposition")
    if isinstance(spillover, dict):
        if spillover.get("status") == "ok":
            lines.append(
                "Spatial spillover decomposition treats the neighbor-adjusted coefficient as a direct-effect proxy "
                f"({_format_float(spillover.get('direct_effect_proxy_main'))}) and the neighbor-exposure coefficient "
                f"as a spillover proxy ({_format_float(spillover.get('spillover_effect_proxy_main'))}); "
                f"the absolute spillover share is {_format_float(spillover.get('spillover_share_abs_main'))}."
            )
        else:
            lines.append("Spatial spillover decomposition is not estimable.")

    exposure_mapping = summary.get("spatial_exposure_mapping")
    if isinstance(exposure_mapping, dict):
        if exposure_mapping.get("status") == "ok":
            lines.append(
                "Exposure mapping based on the fitted spatial model gives mean indirect effect "
                f"{_format_float(exposure_mapping.get('mean_indirect_effect'))} "
                f"and mean total effect {_format_float(exposure_mapping.get('mean_total_effect'))}; "
                f"the indirect effect 10th to 90th percentile range is "
                f"{_format_float(exposure_mapping.get('indirect_effect_p10'))} to "
                f"{_format_float(exposure_mapping.get('indirect_effect_p90'))}."
            )
        else:
            lines.append("Spatial exposure mapping is not estimable.")

    return lines


def write_result_summary_markdown(
    paths: SCCAPaths,
    *,
    title: str,
    manifest: dict[str, Any] | None = None,
) -> Path:
    """Write a compact, user-facing numeric result summary."""

    result_summary = (
        manifest.get("result_summary", {}) if isinstance(manifest, dict) else collect_result_summary(paths)
    )
    if not isinstance(result_summary, dict):
        result_summary = {}
    lines = _summary_lines(result_summary)
    summary_text = "\n".join(f"- {line}" for line in lines)
    if not summary_text:
        summary_text = "- No numeric result summary is available yet."

    decision_lines: list[str] = []
    if isinstance(manifest, dict):
        decision_lines = [
            "",
            "## Decision",
            f"- Credibility decision: {manifest.get('credibility_decision') or manifest.get('decision')}",
            f"- Robustness interpretation: {manifest.get('robustness_interpretation') or 'not available'}",
        ]
        if manifest.get("evidence_grade"):
            decision_lines.extend(
                [
                    f"- Evidence grade: {manifest.get('evidence_grade')}",
                    f"- Evidence grade rules: {', '.join(manifest.get('evidence_grade_rule_ids') or []) or 'none'}",
                ]
            )
    spatial_lines = [
        "",
        "## Spatial Outputs",
        "- GeoPackage/GeoJSON layers include target-exposure fields when target outcomes are configured.",
        "- When spatial exposure mapping is estimable, spatial layers include `gc_spatial_direct_effect`, `gc_spatial_indirect_effect`, `gc_spatial_total_effect`, and graph-weight fields.",
        "- QGIS styles are written under `spatial_outputs/qgis_styles/` when spatial output generation is run.",
    ]
    document = "\n".join(
        [
            f"# {title} Result Summary",
            "",
            "## Numeric Summary",
            summary_text,
            *decision_lines,
            *spatial_lines,
            "",
        ]
    )
    paths.result_summary_markdown.write_text(document, encoding="utf-8")
    return paths.result_summary_markdown


def collect_report_files(paths: SCCAPaths) -> dict[str, str]:
    files = {
        "data_profile": paths.data_profile.name,
        "variable_candidates": paths.variable_candidates.name,
        "context_features": paths.context_features.name,
        "context_manifest": paths.context_manifest.name,
        "design_plan": paths.design_plan.name,
        "effect_estimates": paths.effect_estimates.name,
        "erf_curve": paths.erf_curve.name,
        "model_diagnostics": paths.model_diagnostics.name,
        "balance_summary": paths.balance_summary.name,
        "overlap_summary": paths.overlap_summary.name,
        "spatial_robustness": paths.spatial_robustness.name,
        "credibility_report": paths.credibility_report.name,
        "analysis_report": paths.analysis_report.name,
        "manifest": paths.manifest.name,
    }
    optional_files = {
        "spatial_diagnostics": paths.spatial_diagnostics,
        "spatial_bootstrap_robustness": paths.spatial_bootstrap_robustness,
        "spatial_bootstrap_summary": paths.spatial_bootstrap_summary,
        "spatial_graph_sensitivity": paths.spatial_graph_sensitivity,
        "spatial_graph_sensitivity_summary": paths.spatial_graph_sensitivity_summary,
        "spatial_slx_estimates": paths.spatial_slx_estimates,
        "spatial_slx_summary": paths.spatial_slx_summary,
        "spatial_spillover_decomposition": paths.spatial_spillover_decomposition,
        "spatial_spillover_summary": paths.spatial_spillover_summary,
        "spatial_exposure_mapping": paths.spatial_exposure_mapping,
        "spatial_exposure_mapping_summary": paths.spatial_exposure_mapping_summary,
        "result_summary_markdown": paths.result_summary_markdown,
    }
    for key, path in optional_files.items():
        if path.exists():
            files[key] = path.name
    return files


def write_report(
    spec: StudySpec,
    paths: SCCAPaths,
    credibility: dict[str, object],
    metadata: dict[str, object] | None = None,
) -> None:
    """Write a compact human-readable report and output manifest."""

    paths.ensure()
    reasons = credibility.get("reasons", [])
    reason_lines = "\n".join(f"- {reason}" for reason in reasons)
    files = collect_report_files(paths)
    file_lines = "\n".join(
        f"- {key.replace('_', ' ').title()}: `{file_name}`"
        for key, file_name in files.items()
    )
    result_summary = collect_result_summary(paths)
    summary_text = "\n".join(f"- {line}" for line in _summary_lines(result_summary))
    if not summary_text:
        summary_text = "- No numeric result summary is available yet."
    report = f"""# SCCA Analysis Report

## Study

- Name: `{spec.name}`
- Exposure: `{spec.exposure}`
- Outcome: `{spec.outcome}`
- Baseline outcome: `{spec.baseline_outcome}`

## Result Summary

{summary_text}

## Credibility Decision

`{credibility.get("decision")}`

## Evidence Grade

`{credibility.get("evidence_grade", "not available")}`

## Reasons

{reason_lines}

## Output Files

{file_lines}
"""
    paths.analysis_report.write_text(report, encoding="utf-8")
    manifest = {
        "study": spec.name,
        "decision": credibility.get("decision"),
        "evidence_grade": credibility.get("evidence_grade"),
        "evidence_grade_rule_ids": credibility.get("evidence_grade_rule_ids", []),
        "evidence_grade_reasons": credibility.get("evidence_grade_reasons", []),
        "rule_version": credibility.get("rule_version"),
        "metadata": metadata or {},
        "result_summary": result_summary,
        "files": files,
    }
    paths.manifest.write_text(
        json.dumps(_json_ready(manifest), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
