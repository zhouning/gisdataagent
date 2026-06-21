from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .specs import SCCAPaths, StudySpec


def load_table(path: str | Path) -> pd.DataFrame:
    """Load a tabular file for SCCA profiling."""

    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(source, encoding="utf-8-sig")
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(source)
    raise ValueError(f"Unsupported SCCA table format: {source.suffix}")


def _role_for_column(column: str, spec: StudySpec) -> str:
    if column == spec.unit_id:
        return "unit_id"
    if column == spec.exposure:
        return "exposure"
    if column == spec.outcome:
        return "outcome"
    if column == spec.baseline_outcome:
        return "baseline_outcome"
    if column == spec.population:
        return "population"
    if column in spec.confounders:
        return "confounder"
    if column in spec.context_columns:
        return "context"
    if spec.subgroup_column and column == spec.subgroup_column:
        return "subgroup"
    if spec.coordinate_columns and column in spec.coordinate_columns:
        return "coordinate"
    return "available"


def _column_profile(series: pd.Series, role: str) -> dict[str, Any]:
    non_null = int(series.notna().sum())
    result: dict[str, Any] = {
        "role": role,
        "dtype": str(series.dtype),
        "missing": int(series.isna().sum()),
        "non_null": non_null,
        "unique": int(series.nunique(dropna=True)),
    }
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() > 0:
        result.update(
            {
                "min": float(numeric.min()),
                "max": float(numeric.max()),
                "mean": float(numeric.mean()),
            }
        )
    return result


def profile_table(df: pd.DataFrame, spec: StudySpec, paths: SCCAPaths) -> dict[str, Any]:
    """Write a data profile and variable candidate table."""

    paths.ensure()
    profile: dict[str, Any] = {
        "study": spec.name,
        "n_rows": int(len(df)),
        "n_columns": int(len(df.columns)),
        "columns": {},
    }
    rows = []
    for col in df.columns:
        role = _role_for_column(col, spec)
        col_profile = _column_profile(df[col], role)
        profile["columns"][col] = col_profile
        rows.append(
            {
                "column": col,
                "role": role,
                "dtype": col_profile["dtype"],
                "missing": col_profile["missing"],
                "unique": col_profile["unique"],
            }
        )

    paths.data_profile.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    pd.DataFrame(rows).to_csv(paths.variable_candidates, index=False)
    return profile
