from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .specs import SCCAPaths, StudySpec


def _numeric(df: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(df[column], errors="coerce")


def _center(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values - values.mean()


def build_context_features(
    df: pd.DataFrame,
    spec: StudySpec,
    paths: SCCAPaths,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build observed spatial/context features for a study."""

    paths.ensure()
    features = pd.DataFrame(index=df.index)
    features[spec.unit_id] = df[spec.unit_id].astype(str)
    features[spec.exposure] = _numeric(df, spec.exposure)
    features[spec.outcome] = _numeric(df, spec.outcome)

    used_columns: list[str] = [spec.exposure, spec.outcome]
    generated: list[str] = []

    if spec.baseline_outcome and spec.baseline_outcome in df.columns:
        features[spec.baseline_outcome] = _numeric(df, spec.baseline_outcome)
        features["outcome_change"] = features[spec.outcome] - features[spec.baseline_outcome]
        features[f"{spec.baseline_outcome}_centered"] = _center(df[spec.baseline_outcome])
        used_columns.append(spec.baseline_outcome)
        generated.extend(["outcome_change", f"{spec.baseline_outcome}_centered"])

    for col in spec.confounders:
        if col not in df.columns or col == spec.baseline_outcome:
            continue
        values = _numeric(df, col)
        features[col] = values
        features[f"{col}_centered"] = values - values.mean()
        used_columns.append(col)
        generated.append(f"{col}_centered")

    for col in spec.context_columns:
        if col not in df.columns:
            continue
        values = _numeric(df, col)
        features[col] = values
        features[f"{col}_centered"] = values - values.mean()
        used_columns.append(col)
        generated.append(f"{col}_centered")

    if spec.population and spec.population in df.columns:
        population = _numeric(df, spec.population).replace(0, np.nan)
        features[spec.population] = population
        features["log_population"] = np.log(population)
        used_columns.append(spec.population)
        generated.append("log_population")

    if spec.subgroup_column and spec.subgroup_column in df.columns:
        features[spec.subgroup_column] = df[spec.subgroup_column].astype(str)
        used_columns.append(spec.subgroup_column)

    numeric_cols = features.select_dtypes(include=[np.number]).columns
    features[numeric_cols] = features[numeric_cols].replace([np.inf, -np.inf], np.nan)
    protected_cols = {spec.exposure, spec.outcome, "outcome_change"}
    if spec.baseline_outcome:
        protected_cols.add(spec.baseline_outcome)
    fill_cols = [col for col in numeric_cols if col not in protected_cols]
    features[fill_cols] = features[fill_cols].fillna(features[fill_cols].median())

    manifest = {
        "study": spec.name,
        "n_rows": int(len(features)),
        "n_features": int(len(features.columns)),
        "source_columns": used_columns,
        "generated_columns": generated,
    }
    features.to_csv(paths.context_features, index=False)
    paths.context_manifest.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return features, manifest
