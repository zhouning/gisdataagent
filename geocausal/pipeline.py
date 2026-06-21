from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm

from data_agent.scca.context import build_context_features
from data_agent.scca.design import select_design
from data_agent.scca.diagnostics import audit_effects
from data_agent.scca.evidence_rules import assess_scca_evidence_grade
from data_agent.scca.estimators import estimate_effects
from data_agent.scca.profiling import profile_table
from data_agent.scca.reporting import (
    collect_report_files,
    collect_result_summary,
    write_report,
    write_result_summary_markdown,
)
from data_agent.scca.robustness import (
    ROBUSTNESS_FILES,
    make_quantile_grid_groups,
    run_context_ablation,
    run_group_bootstrap,
    run_placebo_tests,
    summarize_erf_stability,
    write_robustness_outputs,
)
from data_agent.scca.spatial_diagnostics import (
    append_spatial_adjusted_estimate,
    append_spatial_lag_adjusted_estimate,
    build_spatial_graph,
    run_spatial_block_bootstrap,
    run_spatial_diagnostics,
)
from data_agent.scca.specs import SCCAPaths

from . import __version__
from .config import GeoCausalConfig, validate_config
from .errors import GeoCausalConfigError, GeoCausalPipelineError
from .io import LoadedDataset, load_dataset


def _json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    try:
        import numpy as np

        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, (np.floating, float)):
            numeric = float(value)
            return numeric if np.isfinite(numeric) else None
    except Exception:
        pass
    return value


def _ensure_output_writable(output_dir: Path) -> bool:
    output_dir.mkdir(parents=True, exist_ok=True)
    probe = output_dir / ".geocausal_write_probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    return True


def diagnose_config(config: GeoCausalConfig) -> dict[str, Any]:
    loaded = load_dataset(config)
    warnings = [*loaded.warnings, *validate_config(config, loaded.columns)]
    output_directory = config.resolve_output_dir()
    output_writable = _ensure_output_writable(output_directory)
    return {
        "case_name": config.case_name,
        "input_path": str(loaded.path),
        "input_format": loaded.format,
        "input_rows": int(len(loaded.frame)),
        "input_columns": int(len(loaded.frame.columns)),
        "preprocessing": loaded.preprocessing,
        "geometry_available": loaded.geometry_available,
        "output_directory": str(output_directory),
        "output_writable": output_writable,
        "warnings": warnings,
        "errors": [],
    }


def _main_effect(effect_estimates_path: Path) -> float:
    if not effect_estimates_path.exists():
        return float("nan")
    estimates = pd.read_csv(effect_estimates_path)
    if estimates.empty:
        return float("nan")
    baseline = estimates.loc[estimates["estimator"] == "baseline_adjusted_ols"]
    row = baseline.iloc[0] if not baseline.empty else estimates.iloc[0]
    return float(pd.to_numeric(pd.Series([row.get("coef")]), errors="coerce").iloc[0])


def _bootstrap_group(
    config: GeoCausalConfig,
    features: pd.DataFrame,
    loaded_frame: pd.DataFrame,
) -> tuple[pd.DataFrame, str]:
    group_column = config.robustness.bootstrap.group_column
    if group_column:
        if group_column not in features.columns:
            raise GeoCausalConfigError(
                f"robustness.bootstrap.group_column is missing from the analysis frame: {group_column}"
            )
        return features, group_column

    spec = config.to_study_spec()
    if spec.coordinate_columns and all(column in loaded_frame.columns for column in spec.coordinate_columns):
        x_col, y_col = spec.coordinate_columns
        grouped = features.copy()
        grouped[x_col] = loaded_frame.loc[grouped.index, x_col]
        grouped[y_col] = loaded_frame.loc[grouped.index, y_col]
        grouped["_gc_grid_group"] = make_quantile_grid_groups(grouped, x_col, y_col, bins=4)
        return grouped, "_gc_grid_group"

    geometry_series = None
    if hasattr(loaded_frame, "geometry"):
        geometry_series = getattr(loaded_frame, "geometry")
    elif "geometry" in loaded_frame.columns:
        geometry_series = loaded_frame["geometry"]

    if geometry_series is not None:
        grouped = features.copy()
        x_values: list[float] = []
        y_values: list[float] = []
        valid_points = 0
        for geometry in geometry_series.loc[grouped.index]:
            point = None
            if geometry is not None and not getattr(geometry, "is_empty", True):
                representative = getattr(geometry, "representative_point", None)
                if callable(representative):
                    point = representative()
                else:
                    centroid = getattr(geometry, "centroid", None)
                    if centroid is not None:
                        point = centroid
            x = getattr(point, "x", float("nan")) if point is not None else float("nan")
            y = getattr(point, "y", float("nan")) if point is not None else float("nan")
            if math.isfinite(x) and math.isfinite(y):
                valid_points += 1
            x_values.append(x)
            y_values.append(y)

        if valid_points == 0:
            raise GeoCausalConfigError(
                "robustness.bootstrap.group_column is required when coordinate columns are unavailable "
                "and geometry does not yield finite representative coordinates."
            )

        grouped["_gc_geometry_x"] = x_values
        grouped["_gc_geometry_y"] = y_values
        grouped["_gc_grid_group"] = make_quantile_grid_groups(
            grouped, "_gc_geometry_x", "_gc_geometry_y", bins=4
        )
        return grouped, "_gc_grid_group"

    raise GeoCausalConfigError(
        "robustness.bootstrap.group_column is required when coordinate columns are unavailable."
    )


def _analysis_covariates(config: GeoCausalConfig, features: pd.DataFrame) -> list[str]:
    candidates = [
        *config.variables.confounders,
        *config.context.columns,
    ]
    return list(dict.fromkeys(column for column in candidates if column in features.columns))


def _interpolate_erf_response(erf_curve: pd.DataFrame, exposure_value: float) -> float:
    if not np.isfinite(exposure_value) or erf_curve.empty:
        return np.nan
    exposure_grid = pd.to_numeric(erf_curve.get("exposure"), errors="coerce")
    response_grid = pd.to_numeric(erf_curve.get("response"), errors="coerce")
    valid = exposure_grid.notna() & response_grid.notna()
    if valid.sum() < 2:
        return np.nan
    ordered = pd.DataFrame(
        {"exposure": exposure_grid[valid], "response": response_grid[valid]}
    ).sort_values("exposure")
    return float(
        np.interp(
            exposure_value,
            ordered["exposure"].to_numpy(dtype=float),
            ordered["response"].to_numpy(dtype=float),
        )
    )


def _invert_erf_response(erf_curve: pd.DataFrame, response_value: float) -> tuple[float, str, str]:
    if not np.isfinite(response_value) or erf_curve.empty:
        return np.nan, "skipped", "ERF inversion requires finite response values."
    exposure_grid = pd.to_numeric(erf_curve.get("exposure"), errors="coerce")
    response_grid = pd.to_numeric(erf_curve.get("response"), errors="coerce")
    valid = exposure_grid.notna() & response_grid.notna()
    if valid.sum() < 2:
        return np.nan, "skipped", "ERF inversion requires at least two finite grid points."
    ordered = pd.DataFrame(
        {"exposure": exposure_grid[valid], "response": response_grid[valid]}
    ).sort_values("response")
    response_values = ordered["response"].to_numpy(dtype=float)
    exposure_values = ordered["exposure"].to_numpy(dtype=float)
    support_min = float(response_values.min())
    support_max = float(response_values.max())
    if response_value < support_min or response_value > support_max:
        return (
            float(np.interp(response_value, response_values, exposure_values)),
            "outside_erf_support",
            "Target response is outside the ERF response support.",
        )
    return float(np.interp(response_value, response_values, exposure_values)), "ok", ""


def _target_row(
    *,
    unit_id: object,
    method: str,
    target_name: str,
    target_outcome: float,
    current_outcome: float,
    predicted_outcome: float,
    current_exposure: float,
    required_exposure: float,
    exposure_change: float,
    model_exposure_coef: float,
    status: str,
    warning: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "unit_id": str(unit_id),
        "method": method,
        "target_name": target_name,
        "target_outcome": target_outcome,
        "current_outcome": current_outcome if np.isfinite(current_outcome) else np.nan,
        "predicted_outcome": predicted_outcome if np.isfinite(predicted_outcome) else np.nan,
        "current_exposure": current_exposure if np.isfinite(current_exposure) else np.nan,
        "required_exposure": required_exposure if np.isfinite(required_exposure) else np.nan,
        "exposure_change": exposure_change if np.isfinite(exposure_change) else np.nan,
        "model_exposure_coef": model_exposure_coef if np.isfinite(model_exposure_coef) else np.nan,
        "status": status,
        "warning": warning,
    }
    if extra:
        row.update(extra)
    return row


def _write_target_exposures(
    config: GeoCausalConfig,
    features: pd.DataFrame,
    output_dir: Path,
) -> Path | None:
    if not config.targets.outcome_values:
        return None
    exposure = config.variables.exposure
    outcome = config.variables.outcome
    unit_id = config.variables.unit_id
    covariates = _analysis_covariates(config, features)
    required_columns = [unit_id, exposure, outcome, *covariates]
    available_columns = [column for column in required_columns if column in features.columns]
    frame = features[available_columns].copy()
    numeric_columns = [exposure, outcome, *covariates]
    for column in numeric_columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    complete = frame.dropna(subset=[exposure, outcome, *covariates])
    erf_path = output_dir / "erf_curve.csv"
    erf_curve = pd.read_csv(erf_path) if erf_path.exists() else pd.DataFrame()

    rows: list[dict[str, Any]] = []
    status = "ok"
    warning = ""
    beta = np.nan
    predictions = pd.Series(np.nan, index=features.index, dtype=float)
    if len(complete) < max(3, len(covariates) + 2):
        status = "skipped"
        warning = "Fewer complete rows than required for target exposure model."
    elif complete[exposure].nunique() < 2:
        status = "skipped"
        warning = "Exposure has no variation for target exposure model."
    else:
        try:
            x = sm.add_constant(complete[[exposure, *covariates]], has_constant="add").astype(float)
            y = complete[outcome].astype(float)
            model = sm.OLS(y, x, missing="drop").fit()
            beta = float(model.params.get(exposure, np.nan))
            prediction_frame = features[[exposure, *covariates]].copy()
            for column in prediction_frame.columns:
                prediction_frame[column] = pd.to_numeric(prediction_frame[column], errors="coerce")
            prediction_frame = sm.add_constant(prediction_frame, has_constant="add").astype(float)
            predictions = pd.Series(model.predict(prediction_frame), index=features.index, dtype=float)
            if not np.isfinite(beta) or beta == 0:
                status = "skipped"
                warning = "Target exposure model has zero or non-finite exposure coefficient."
        except Exception as exc:
            status = "skipped"
            warning = f"Target exposure model failed: {exc}"

    for target in config.targets.outcome_values:
        for index, row in features.iterrows():
            current_exposure = pd.to_numeric(pd.Series([row.get(exposure)]), errors="coerce").iloc[0]
            current_outcome = pd.to_numeric(pd.Series([row.get(outcome)]), errors="coerce").iloc[0]
            predicted_outcome = predictions.loc[index] if index in predictions.index else np.nan
            if status == "ok":
                required_exposure = float(current_exposure + (target.value - predicted_outcome) / beta)
                exposure_change = float(required_exposure - current_exposure)
            else:
                required_exposure = np.nan
                exposure_change = np.nan
            rows.append(
                _target_row(
                    unit_id=row.get(unit_id, index),
                    method="adjusted_ols_prediction",
                    target_name=target.name,
                    target_outcome=target.value,
                    current_outcome=float(current_outcome) if np.isfinite(current_outcome) else np.nan,
                    predicted_outcome=float(predicted_outcome)
                    if np.isfinite(predicted_outcome)
                    else np.nan,
                    current_exposure=float(current_exposure)
                    if np.isfinite(current_exposure)
                    else np.nan,
                    required_exposure=required_exposure,
                    exposure_change=exposure_change,
                    model_exposure_coef=beta,
                    status=status,
                    warning=warning,
                )
            )

            erf_current = _interpolate_erf_response(
                erf_curve,
                float(current_exposure) if np.isfinite(current_exposure) else np.nan,
            )
            desired_erf_response = (
                target.value - float(current_outcome) + erf_current
                if np.isfinite(current_outcome) and np.isfinite(erf_current)
                else np.nan
            )
            erf_required, erf_status, erf_warning = _invert_erf_response(
                erf_curve,
                desired_erf_response,
            )
            erf_change = (
                float(erf_required - current_exposure)
                if np.isfinite(erf_required) and np.isfinite(current_exposure)
                else np.nan
            )
            rows.append(
                _target_row(
                    unit_id=row.get(unit_id, index),
                    method="erf_delta_anchor",
                    target_name=target.name,
                    target_outcome=target.value,
                    current_outcome=float(current_outcome) if np.isfinite(current_outcome) else np.nan,
                    predicted_outcome=target.value if erf_status == "ok" else np.nan,
                    current_exposure=float(current_exposure)
                    if np.isfinite(current_exposure)
                    else np.nan,
                    required_exposure=erf_required,
                    exposure_change=erf_change,
                    model_exposure_coef=np.nan,
                    status=erf_status,
                    warning=erf_warning,
                    extra={
                        "erf_current_response": erf_current,
                        "erf_target_response": desired_erf_response,
                    },
                )
            )

    output_path = output_dir / "target_exposures.csv"
    pd.DataFrame(rows).to_csv(output_path, index=False)
    return output_path


def _write_geocausal_manifest(
    config: GeoCausalConfig,
    loaded: LoadedDataset,
    paths: SCCAPaths,
    credibility: dict[str, Any],
    robustness_manifest: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    files = collect_report_files(paths)
    files.update(
        {
            "context_ablation": ROBUSTNESS_FILES["context_ablation"],
            "placebo_tests": ROBUSTNESS_FILES["placebo_tests"],
            "bootstrap_robustness": ROBUSTNESS_FILES["bootstrap_robustness"],
            "bootstrap_summary": ROBUSTNESS_FILES["bootstrap_summary"],
            "erf_stability": ROBUSTNESS_FILES["erf_stability"],
            "robustness_report": ROBUSTNESS_FILES["robustness_report"],
            "robustness_manifest": ROBUSTNESS_FILES["robustness_manifest"],
        }
    )
    target_exposures = paths.output_dir / "target_exposures.csv"
    if target_exposures.exists():
        files["target_exposures"] = target_exposures.name
    result_summary = collect_result_summary(paths)
    spatial = result_summary.get("spatial_diagnostics", {})
    spatial_neighbor = result_summary.get("spatial_neighbor_adjusted_ols", {})
    spatial_lag = result_summary.get("spatial_lag_adjusted_ols", {})
    graph = result_summary.get("spatial_graph_sensitivity", {})
    evidence_assessment = assess_scca_evidence_grade(
        credibility_decision=str(credibility.get("decision")),
        robustness_interpretation=str(robustness_manifest.get("robustness_interpretation")),
        spatial_summary={
            "residual_moran_i": spatial.get("residual_moran_i") if isinstance(spatial, dict) else None,
            "residual_moran_p_value": spatial.get("residual_moran_p_value") if isinstance(spatial, dict) else None,
            "neighbor_exposure_p_value": spatial_lag.get("neighbor_exposure_p_value")
            if isinstance(spatial_lag, dict)
            else spatial_neighbor.get("neighbor_exposure_p_value")
            if isinstance(spatial_neighbor, dict)
            else None,
            "neighbor_adjusted_relative_change": spatial_neighbor.get("relative_change")
            if isinstance(spatial_neighbor, dict)
            else None,
            "spatial_lag_relative_change": spatial_lag.get("relative_change")
            if isinstance(spatial_lag, dict)
            else None,
            "neighbor_adjusted_relative_change_max": graph.get("neighbor_adjusted_relative_change_max")
            if isinstance(graph, dict)
            else None,
            "spatial_lag_relative_change_max": graph.get("spatial_lag_relative_change_max")
            if isinstance(graph, dict)
            else None,
            "neighbor_adjusted_sign_stability": graph.get("neighbor_adjusted_sign_stability")
            if isinstance(graph, dict)
            else None,
            "spatial_lag_sign_stability": graph.get("spatial_lag_sign_stability")
            if isinstance(graph, dict)
            else None,
        },
    )
    manifest = {
        "geocausal_version": __version__,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "case_name": config.case_name,
        "study": config.case_name,
        "config_path": str(config.config_path),
        "input_path": str(loaded.path),
        "input_format": loaded.format,
        "row_count": int(len(loaded.frame)),
        "column_count": int(len(loaded.frame.columns)),
        "preprocessing": loaded.preprocessing,
        "exposure": config.variables.exposure,
        "outcome": config.variables.outcome,
        "unit_id": config.variables.unit_id,
        "baseline_outcome": config.variables.baseline_outcome,
        "confounders": list(config.variables.confounders),
        "context_columns": list(config.context.columns),
        "targets": {
            "outcome_values": [
                {"name": target.name, "value": target.value}
                for target in config.targets.outcome_values
            ]
        },
        "credibility_decision": credibility.get("decision"),
        "robustness_interpretation": robustness_manifest.get("robustness_interpretation"),
        "evidence_grade": evidence_assessment.get("evidence_grade"),
        "evidence_grade_rule_ids": evidence_assessment.get("triggered_rules"),
        "evidence_grade_reasons": evidence_assessment.get("reasons"),
        "rule_version": evidence_assessment.get("rule_version"),
        "result_summary": result_summary,
        "warnings": warnings,
        "files": files,
    }
    write_result_summary_markdown(
        paths,
        title=str(config.case_name),
        manifest=manifest,
    )
    files["result_summary_markdown"] = paths.result_summary_markdown.name
    manifest["files"] = files
    paths.manifest.write_text(
        json.dumps(_json_ready(manifest), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def run_analysis(config: GeoCausalConfig) -> dict[str, Any]:
    try:
        diagnosis = diagnose_config(config)
        warnings = list(dict.fromkeys(diagnosis["warnings"]))
        loaded = load_dataset(config)
        spec = config.to_study_spec()
        paths = SCCAPaths(output_dir=config.resolve_output_dir())
        paths.ensure()

        profile_table(loaded.frame, spec, paths)
        features, _ = build_context_features(loaded.frame, spec, paths)
        select_design(features, spec, paths)
        effects = estimate_effects(features, spec, paths)
        baseline_effect = effects.get("baseline_adjusted_ols", {})
        baseline_coef = (
            baseline_effect.get("coef") if isinstance(baseline_effect, dict) else None
        )
        spatial_diagnostics = run_spatial_diagnostics(
            features,
            spec,
            paths,
            source_frame=loaded.frame,
            baseline_exposure_coef=float(baseline_coef)
            if isinstance(baseline_coef, (int, float)) and np.isfinite(float(baseline_coef))
            else None,
        )
        append_spatial_adjusted_estimate(paths, spatial_diagnostics)
        append_spatial_lag_adjusted_estimate(paths, spatial_diagnostics)
        spatial_graph = build_spatial_graph(features, spec, loaded.frame)
        spatial_bootstrap_rows, spatial_bootstrap_summary = run_spatial_block_bootstrap(
            features,
            spec,
            spatial_graph,
            source_frame=loaded.frame,
            baseline_exposure_coef=float(baseline_coef)
            if isinstance(baseline_coef, (int, float)) and np.isfinite(float(baseline_coef))
            else None,
            n_replicates=max(10, min(config.robustness.bootstrap.n_replicates, 100)),
        )
        spatial_bootstrap_rows.to_csv(paths.spatial_bootstrap_robustness, index=False)
        paths.spatial_bootstrap_summary.write_text(
            json.dumps(_json_ready(spatial_bootstrap_summary), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _write_target_exposures(config, features, paths.output_dir)
        credibility = audit_effects(features, spec, paths)
        write_report(
            spec,
            paths,
            credibility,
            metadata={
                "source_path": str(loaded.path),
                "config_path": str(config.config_path),
                "geocausal_version": __version__,
            },
        )
        main_coef = _main_effect(paths.effect_estimates)
        ablation = run_context_ablation(features, spec, config.case_name)
        placebo = run_placebo_tests(
            features,
            spec,
            config.case_name,
            [item.to_robustness_test() for item in config.robustness.placebo_exposures],
        )
        bootstrap_features, group_column = _bootstrap_group(config, features, loaded.frame)
        bootstrap_rows, bootstrap_summary = run_group_bootstrap(
            bootstrap_features,
            spec,
            config.case_name,
            group_column=group_column,
            n_replicates=config.robustness.bootstrap.n_replicates,
        )
        erf_curve = pd.read_csv(paths.erf_curve)
        erf_summary = summarize_erf_stability(erf_curve, config.case_name)
        main_limitation = "; ".join(str(reason) for reason in credibility.get("reasons", []))
        robustness_manifest = write_robustness_outputs(
            output_dir=paths.output_dir,
            case_name=config.case_name,
            original_decision=str(credibility.get("decision", "unknown")),
            main_coef=main_coef,
            main_limitation=main_limitation,
            ablation=ablation,
            placebo=placebo,
            bootstrap_rows=bootstrap_rows,
            bootstrap_summary=bootstrap_summary,
            erf_summary=erf_summary,
        )
        return _write_geocausal_manifest(config, loaded, paths, credibility, robustness_manifest, warnings)
    except GeoCausalConfigError:
        raise
    except Exception as exc:
        raise GeoCausalPipelineError(f"GeoCausal analysis failed: {exc}") from exc


def rebuild_report(output_dir: str | Path) -> dict[str, Any]:
    target = Path(output_dir)
    manifest_path = target / "manifest.json"
    if not manifest_path.exists():
        raise GeoCausalPipelineError(f"manifest.json is missing in {target}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report = f"""# GeoCausal Analysis Report

## Case

`{manifest.get("case_name") or manifest.get("study")}`

## Interpretation

`{manifest.get("robustness_interpretation")}`

## Files

{chr(10).join(f"- {key}: `{value}`" for key, value in manifest.get("files", {}).items())}
"""
    (target / "geocausal_report.md").write_text(report, encoding="utf-8")
    return manifest
