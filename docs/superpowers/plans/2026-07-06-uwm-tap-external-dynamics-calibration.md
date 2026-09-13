# UWM TAP External Dynamics Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a TAP real-data external dynamics holdout that tests whether UWM spatial-message state dynamics improve PM2.5 next-state prediction beyond traditional static and non-spatial dynamic baselines.

**Architecture:** Add a focused external dynamics module beside the existing TAP proxy and temporal benchmark modules. It streams local TAP zip files, constructs deterministic sampled grid-time series, builds no-leakage spatial message features, compares static/non-spatial/spatial models, and emits claim-guarded JSON artifacts plus report updates. It does not modify the planner or claim observed policy outcome superiority.

**Tech Stack:** Python standard library (`csv`, `zipfile`, `json`, `pathlib`, `statistics`, `math`), optional `numpy` already used by UWM world-model modules, pytest via `uv run`.

---

## File Structure

- Create `data_agent/uwm/tap_external_dynamics.py`
  - TAP zip streaming, sampled grid series assembly, spatial neighbor feature construction, ridge/closed-form model fitting, baseline comparison, negative controls, validation.
- Create `data_agent/test_uwm_tap_external_dynamics.py`
  - Fixture zip tests for spatial advantage, claim downgrade, leakage guard, and policy claim guard.
- Create `scripts/build_uwm_tap_external_dynamics.py`
  - Runs the external dynamics benchmark against `/Users/zhouning/Downloads/tap_uwm`; writes JSON artifacts.
- Modify reports after artifact generation:
  - `docs/reports/uwm_data_foundation_manifest.csv`
  - `docs/reports/uwm_data_foundation_manifest.md`
  - `docs/reports/uwm_data_foundation_coverage_audit.md`
  - `docs/reports/uwm_data_foundation_summary_2026-07-05.md`
  - `docs/reports/uwm_track2_research_log.md`

Do not commit raw TAP zip files from `/Users/zhouning/Downloads/tap_uwm`.

---

### Task 1: External Dynamics Contract and Fixture Tests

**Files:**
- Create: `data_agent/test_uwm_tap_external_dynamics.py`

- [ ] **Step 1: Write the failing tests**

Create `data_agent/test_uwm_tap_external_dynamics.py` with:

```python
import zipfile
from pathlib import Path

from data_agent.uwm.tap_external_dynamics import (
    TAP_EXTERNAL_DYNAMICS_SCHEMA,
    build_tap_external_dynamics_report,
    validate_tap_external_dynamics_report,
)


def test_spatial_message_model_beats_static_and_non_spatial_baselines(tmp_path):
    tap_root = _write_spatial_diffusion_fixture(tmp_path)

    report = build_tap_external_dynamics_report(
        tap_root=tap_root,
        model_id="tap-external-dynamics-fixture",
        created_at="2026-07-06T02:00:00Z",
        train_days=3,
        max_grid_series_per_period=4,
        neighbor_count=2,
        ridge=0.001,
    )

    validation = validate_tap_external_dynamics_report(report)
    assert validation["valid"], validation["errors"]
    assert report["schema"] == TAP_EXTERNAL_DYNAMICS_SCHEMA
    assert report["model_id"] == "tap-external-dynamics-fixture"
    assert report["sampling_config"]["neighbor_mode"] == "lonlat_nearest_neighbors_v1"
    assert report["training_summary"]["series_count"] == 4
    assert report["training_summary"]["holdout_count"] == 12

    overall = report["overall_results"]
    assert overall["best_spatial_method"] == "spatial_message_ridge"
    assert overall["best_spatial_mae"] < overall["best_traditional_static_mae"]
    assert overall["best_spatial_mae"] < overall["best_non_spatial_dynamic_mae"]
    assert overall["paired_win_rate_vs_best_non_spatial_dynamic"] > 0.5
    assert report["negative_control_results"]["neighbor_shuffle_control"]["mae"] > overall["best_spatial_mae"]
    assert report["supported_claim"] == (
        "tap_external_spatiotemporal_dynamics_advantage_over_static_and_non_spatial_baselines"
    )
    assert report["claim_boundary"]["max_claim_level"] == "bounded_support"


def test_spatial_claim_downgrades_when_neighbors_do_not_help(tmp_path):
    tap_root = _write_no_spatial_signal_fixture(tmp_path)

    report = build_tap_external_dynamics_report(
        tap_root=tap_root,
        model_id="tap-external-dynamics-no-spatial-fixture",
        created_at="2026-07-06T02:00:00Z",
        train_days=3,
        max_grid_series_per_period=4,
        neighbor_count=2,
        ridge=0.001,
    )

    assert report["supported_claim"] in {
        "tap_external_temporal_dynamics_advantage_without_spatial_claim",
        "no_tap_external_dynamics_advantage_claim_supported",
    }
    assert report["overall_results"]["spatial_negative_control_passed"] is False


def test_external_dynamics_keeps_policy_outcome_claims_false(tmp_path):
    tap_root = _write_spatial_diffusion_fixture(tmp_path)

    report = build_tap_external_dynamics_report(
        tap_root=tap_root,
        model_id="tap-external-dynamics-fixture",
        created_at="2026-07-06T02:00:00Z",
        train_days=3,
        max_grid_series_per_period=4,
        neighbor_count=2,
    )

    assert report["empirical_superiority_claim"] is False
    assert report["observed_policy_outcome_superiority_claim"] is False
    assert "not_policy_intervention_outcome" in report["limitations"]
    assert "tap_gridded_product_not_station_observation" in report["limitations"]


def test_external_dynamics_feature_rows_do_not_use_current_or_future_labels(tmp_path):
    tap_root = _write_spatial_diffusion_fixture(tmp_path)

    report = build_tap_external_dynamics_report(
        tap_root=tap_root,
        model_id="tap-external-dynamics-fixture",
        created_at="2026-07-06T02:00:00Z",
        train_days=3,
        max_grid_series_per_period=4,
        neighbor_count=2,
        include_feature_audit=True,
    )

    leakage = report["negative_control_results"]["future_label_leakage_guard"]
    assert leakage["passed"] is True
    assert leakage["audited_feature_rows"] > 0
    assert leakage["feature_time_rule"] == "features_for_day_t_use_only_values_strictly_before_day_t"
    for row in report["feature_audit_sample"]:
        assert int(row["max_feature_doy"]) < int(row["target_doy"])


def _write_spatial_diffusion_fixture(tmp_path: Path) -> Path:
    return _write_fixture(
        tmp_path,
        values_by_doy={
            "183": ["10", "30", "30", "10"],
            "184": ["10", "30", "30", "10"],
            "185": ["10", "30", "30", "10"],
            "186": ["20", "20", "20", "20"],
            "187": ["20", "20", "20", "20"],
            "188": ["20", "20", "20", "20"],
        },
    )


def _write_no_spatial_signal_fixture(tmp_path: Path) -> Path:
    return _write_fixture(
        tmp_path,
        values_by_doy={
            "183": ["10", "20", "30", "40"],
            "184": ["11", "21", "31", "41"],
            "185": ["12", "22", "32", "42"],
            "186": ["13", "23", "33", "43"],
            "187": ["14", "24", "34", "44"],
            "188": ["15", "25", "35", "45"],
        },
    )


def _write_fixture(tmp_path: Path, values_by_doy: dict[str, list[str]]) -> Path:
    tap_root = tmp_path / "tap_uwm"
    downloaded = tap_root / "chongqing_pm25_2024_07_01_07" / "downloaded"
    downloaded.mkdir(parents=True)
    _write_csv_zip(
        downloaded / "Tile_074_lonlat.csv.zip",
        "Tile_074_lonlat.csv",
        ["Longitude", "Latitude", "GridID", "TileID"],
        [
            ["103.0", "29.0", "1", "74"],
            ["103.1", "29.0", "2", "74"],
            ["103.0", "29.1", "3", "74"],
            ["103.1", "29.1", "4", "74"],
        ],
    )
    for doy, values in values_by_doy.items():
        _write_csv_zip(
            downloaded / f"China_PM25_1km_2024_{doy}_074.csv.zip",
            f"China_PM25_1km_2024_{doy}_074.csv",
            ["GridID", "PM2.5"],
            [["1", values[0]], ["2", values[1]], ["3", values[2]], ["4", values[3]]],
        )
    return tap_root


def _write_csv_zip(path: Path, inner_name: str, fieldnames: list[str], rows: list[list[str]]) -> None:
    lines = [",".join(fieldnames)]
    lines.extend(",".join(row) for row in rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr(inner_name, "\n".join(lines) + "\n")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run python -m pytest data_agent/test_uwm_tap_external_dynamics.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'data_agent.uwm.tap_external_dynamics'`.

- [ ] **Step 3: Commit the failing tests only if local workflow requires it**

Do not commit red tests unless the execution environment requires checkpointing. Normal path is to proceed directly to Task 2.

---

### Task 2: Implement TAP External Dynamics Module

**Files:**
- Create: `data_agent/uwm/tap_external_dynamics.py`
- Test: `data_agent/test_uwm_tap_external_dynamics.py`

- [ ] **Step 1: Implement the module**

Create `data_agent/uwm/tap_external_dynamics.py` with these public functions and constants:

```python
"""TAP external spatiotemporal dynamics holdout for UWM."""

from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from statistics import fmean, median
from typing import Any

import numpy as np


TAP_EXTERNAL_DYNAMICS_SCHEMA = "uwm.tap_external_spatiotemporal_dynamics_report.v1"
TAP_EXTERNAL_DATASET_ID = "tap_pm25_observed_gridded_chongqing_2018_2024"
STATIC_BASELINES = [
    "static_train_mean",
    "static_last_train_observation",
    "period_static_mean",
    "tile_static_mean",
]
NON_SPATIAL_DYNAMIC_BASELINES = [
    "online_persistence_state_update",
    "adaptive_online_state_update",
]
SPATIAL_METHODS = ["spatial_message_ridge"]
FEATURE_NAMES = [
    "bias",
    "target_previous_pm25",
    "target_train_mean",
    "tile_train_mean",
    "neighbor_previous_mean",
    "neighbor_previous_median",
    "target_neighbor_previous_contrast",
    "tile_previous_anomaly",
    "day_index_norm",
]


def build_tap_external_dynamics_report(
    *,
    tap_root: str | Path,
    model_id: str,
    created_at: str,
    train_days: int = 3,
    max_grid_series_per_period: int = 5000,
    neighbor_count: int = 4,
    ridge: float = 0.001,
    include_feature_audit: bool = False,
) -> dict[str, Any]:
    root = Path(tap_root)
    if not root.exists():
        raise FileNotFoundError(f"TAP root not found: {root}")
    period_reports = [
        _build_period_report(
            period_dir,
            train_days=train_days,
            max_series=max_grid_series_per_period,
            neighbor_count=neighbor_count,
            ridge=ridge,
            include_feature_audit=include_feature_audit,
        )
        for period_dir in _period_dirs(root)
    ]
    period_reports = [report for report in period_reports if report["training_summary"]["series_count"] > 0]
    if not period_reports:
        raise ValueError("no TAP periods with enough external dynamics series")
    overall = _combine_overall(period_reports)
    supported_claim = _supported_claim(overall)
    payload = {
        "schema": TAP_EXTERNAL_DYNAMICS_SCHEMA,
        "version": "0.1",
        "model_id": model_id,
        "created_at": created_at,
        "source_dataset_ids": [TAP_EXTERNAL_DATASET_ID],
        "sampling_config": {
            "train_days": train_days,
            "max_grid_series_per_period": max_grid_series_per_period,
            "neighbor_count": neighbor_count,
            "neighbor_mode": "lonlat_nearest_neighbors_v1",
            "ridge": ridge,
        },
        "feature_schema": {
            "feature_names": FEATURE_NAMES,
            "target": "next_day_pm25_ugm3",
            "feature_time_rule": "features_for_day_t_use_only_values_strictly_before_day_t",
        },
        "training_summary": overall["training_summary"],
        "baseline_results": overall["baseline_results"],
        "spatial_world_model_results": overall["spatial_world_model_results"],
        "negative_control_results": overall["negative_control_results"],
        "period_results": period_reports,
        "overall_results": overall["overall_results"],
        "supported_claim": supported_claim,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if supported_claim != "no_tap_external_dynamics_advantage_claim_supported" else "not_for_claim",
            "reason": (
                "TAP gridded PM2.5 supports external state-dynamics validation. "
                "It is not station-observed policy intervention outcome evidence."
            ),
        },
        "limitations": [
            "tap_gridded_product_not_station_observation",
            "not_policy_intervention_outcome",
            "action_free_exogenous_air_pollution_dynamics_only",
            "short_daily_holdout_window",
            "sampled_grid_series_for_runtime_control",
        ],
        "empirical_superiority_claim": False,
        "observed_policy_outcome_superiority_claim": False,
    }
    if include_feature_audit:
        payload["feature_audit_sample"] = [
            row
            for report in period_reports
            for row in report.get("feature_audit_sample", [])
        ][:50]
    return payload


def validate_tap_external_dynamics_report(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != TAP_EXTERNAL_DYNAMICS_SCHEMA:
        errors.append(f"schema must be {TAP_EXTERNAL_DYNAMICS_SCHEMA}")
    for key in [
        "model_id",
        "sampling_config",
        "feature_schema",
        "training_summary",
        "baseline_results",
        "spatial_world_model_results",
        "negative_control_results",
        "overall_results",
        "claim_boundary",
        "limitations",
    ]:
        if key not in payload:
            errors.append(f"{key} is required")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must stay false")
    if payload.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim must stay false")
    if "not_policy_intervention_outcome" not in (payload.get("limitations") or []):
        errors.append("limitations must include not_policy_intervention_outcome")
    leakage = (payload.get("negative_control_results") or {}).get("future_label_leakage_guard") or {}
    if leakage.get("passed") is not True:
        errors.append("future label leakage guard must pass")
    return {"valid": not errors, "errors": errors}
```

Then implement private helpers in the same file:

- `_period_dirs(root)`
- `_build_period_report(...)`
- `_load_period_series_with_lonlat(period_dir)`
- `_nearest_neighbors(selected_series, neighbor_count)`
- `_feature_rows_for_period(...)`
- `_fit_ridge(x, y, ridge)`
- `_predict_baselines(...)`
- `_evaluate_predictions(...)`
- `_neighbor_shuffle_rows(rows)`
- `_temporal_order_rotation_control(...)`
- `_combine_overall(period_reports)`
- `_supported_claim(overall)`
- CSV/zip parsing helpers copied in style from `tap_pm25_proxy.py` and `tap_temporal_benchmark.py`.

The private implementation must follow this concrete algorithm:

```python
def _feature_rows_for_period(series_by_key, neighbors_by_key, train_days):
    rows = []
    sorted_days = sorted(all_doys)
    for key, series in selected_series.items():
        for day_index in range(1, len(sorted_days)):
            target_doy = sorted_days[day_index]
            previous_doy = sorted_days[day_index - 1]
            if target_doy not in series or previous_doy not in series:
                continue
            neighbor_previous_values = [
                series_by_key[neighbor][previous_doy]
                for neighbor in neighbors_by_key[key]
                if previous_doy in series_by_key[neighbor]
            ]
            if not neighbor_previous_values:
                continue
            rows.append({
                "key": key,
                "target_doy": target_doy,
                "target_value": series[target_doy],
                "is_holdout": day_index >= train_days,
                "features": [
                    1.0,
                    series[previous_doy],
                    mean(first train_days values for key),
                    mean(first train_days values for tile),
                    mean(neighbor_previous_values),
                    median(neighbor_previous_values),
                    series[previous_doy] - mean(neighbor_previous_values),
                    mean(tile values at previous_doy) - mean(first train_days values for tile),
                    day_index / max(1, len(sorted_days) - 1),
                ],
                "max_feature_doy": previous_doy,
            })
    return rows
```

The model training/evaluation split must be:

```text
train rows: feature rows with is_holdout = false
holdout rows: feature rows with is_holdout = true
```

If there are fewer than 2 train rows, use the deterministic spatial average fallback for holdout predictions. Otherwise:

```python
coefficients = inv(X_train.T @ X_train + ridge * I) @ X_train.T @ y_train
spatial_prediction = X_holdout @ coefficients
```

The non-spatial dynamic predictions for each holdout row must use:

```python
online_persistence_state_update = target_previous_pm25
adaptive_online_state_update = 0.7 * target_previous_pm25 + 0.3 * target_train_mean
```

The neighbor shuffle control must use the same trained coefficients but replace `neighbor_previous_mean`, `neighbor_previous_median`, and contrast features with deterministic mismatched neighbor values before prediction.

The returned report dictionaries must include these exact nested keys:

```python
baseline_results = {
    "traditional_static": {"static_train_mean": {"mae": ...}, ...},
    "non_spatial_dynamic": {"online_persistence_state_update": {"mae": ...}, ...},
}
spatial_world_model_results = {
    "spatial_message_ridge": {
        "mae": ...,
        "paired_win_count_vs_best_non_spatial_dynamic": ...,
        "paired_win_rate_vs_best_non_spatial_dynamic": ...,
    }
}
negative_control_results = {
    "neighbor_shuffle_control": {"mae": ..., "real_spatial_advantage": ...},
    "temporal_order_rotation_control": {"mae": ..., "ordered_advantage": ...},
    "future_label_leakage_guard": {"passed": True, ...},
}
overall_results = {
    "best_spatial_method": "spatial_message_ridge",
    "best_spatial_mae": ...,
    "best_traditional_static_mae": ...,
    "best_non_spatial_dynamic_mae": ...,
    "paired_win_rate_vs_best_non_spatial_dynamic": ...,
    "spatial_negative_control_passed": ...,
}
```

Implementation requirements:

- Use lon/lat tile files for neighbor selection.
- Select deterministic series by sorted `(tile_id, grid_id)`.
- For target day `d`, features may use only days before `d`.
- Train ridge on pre-holdout feature rows and evaluate only on holdout rows.
- If rows are too few for ridge, fall back to a deterministic spatial average predictor:

```python
prediction = 0.5 * target_previous_pm25 + 0.5 * neighbor_previous_mean
```

- Always compute all baseline method MAEs.
- Always compute neighbor shuffle and future-label leakage guard.

- [ ] **Step 2: Run fixture tests**

Run:

```bash
uv run python -m pytest data_agent/test_uwm_tap_external_dynamics.py -q
```

Expected: `4 passed`.

- [ ] **Step 3: Commit module and tests**

Run:

```bash
git add data_agent/test_uwm_tap_external_dynamics.py data_agent/uwm/tap_external_dynamics.py
git commit -m "feat: add tap external dynamics holdout"
```

Expected: commit includes only the new test and module files.

---

### Task 3: Builder Script and Real TAP Artifact

**Files:**
- Create: `scripts/build_uwm_tap_external_dynamics.py`
- Create generated artifacts under: `data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06/`

- [ ] **Step 1: Run builder smoke red test**

Run:

```bash
uv run python scripts/build_uwm_tap_external_dynamics.py --tap-root /Users/zhouning/Downloads/tap_uwm --output-dir data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06 --max-grid-series-per-period 250
```

Expected: fails because `scripts/build_uwm_tap_external_dynamics.py` does not exist.

- [ ] **Step 2: Create builder script**

Create `scripts/build_uwm_tap_external_dynamics.py`:

```python
"""Build UWM TAP external spatiotemporal dynamics artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.tap_external_dynamics import build_tap_external_dynamics_report


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAP_ROOT = Path("/Users/zhouning/Downloads/tap_uwm")
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build UWM TAP external spatiotemporal dynamics artifacts.")
    parser.add_argument("--tap-root", default=str(DEFAULT_TAP_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-grid-series-per-period", type=int, default=5000)
    parser.add_argument("--neighbor-count", type=int, default=4)
    args = parser.parse_args()

    tap_root = Path(args.tap_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = build_tap_external_dynamics_report(
        tap_root=tap_root,
        model_id="uwm-tap-external-spatiotemporal-dynamics-chongqing-2018-2024",
        created_at="2026-07-06T02:00:00Z",
        train_days=3,
        max_grid_series_per_period=args.max_grid_series_per_period,
        neighbor_count=args.neighbor_count,
    )
    manifest = {
        "schema": "uwm.public_proxy_snapshot_manifest.v1",
        "dataset_id": "tap_pm25_external_spatiotemporal_dynamics_chongqing_2018_2024",
        "source_dataset_ids": report["source_dataset_ids"],
        "source_root": str(tap_root),
        "created_at": "2026-07-06T02:10:00Z",
        "files": {
            "tap_external_dynamics_report": "tap_external_dynamics_report.json",
        },
        "sampling_config": report["sampling_config"],
        "training_summary": report["training_summary"],
        "overall_results": report["overall_results"],
        "supported_claim": report["supported_claim"],
        "claim_boundary": report["claim_boundary"],
        "limitations": report["limitations"],
        "empirical_superiority_claim": False,
        "observed_policy_outcome_superiority_claim": False,
    }
    _write_json(output_dir / "tap_external_dynamics_report.json", report)
    _write_json(output_dir / "snapshot_manifest.json", manifest)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir.relative_to(REPO_ROOT) if output_dir.is_relative_to(REPO_ROOT) else output_dir),
                "training_summary": report["training_summary"],
                "overall_results": report["overall_results"],
                "supported_claim": report["supported_claim"],
                "claim_boundary": report["claim_boundary"],
                "empirical_superiority_claim": False,
                "observed_policy_outcome_superiority_claim": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run builder on real TAP smoke sample**

Run:

```bash
uv run python scripts/build_uwm_tap_external_dynamics.py --tap-root /Users/zhouning/Downloads/tap_uwm --output-dir data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06 --max-grid-series-per-period 250
```

Expected:

- exits 0;
- writes `tap_external_dynamics_report.json`;
- writes `snapshot_manifest.json`;
- stdout includes `empirical_superiority_claim: false`;
- supported claim is either a bounded advantage claim or an explicit no-claim/downgraded claim.

- [ ] **Step 4: Run targeted tests**

Run:

```bash
uv run python -m pytest data_agent/test_uwm_tap_external_dynamics.py data_agent/test_uwm_tap_pm25_proxy.py data_agent/test_uwm_tap_gridded_temporal_benchmark.py -q
```

Expected: all targeted TAP tests pass.

- [ ] **Step 5: Build final artifact**

Run:

```bash
uv run python scripts/build_uwm_tap_external_dynamics.py --tap-root /Users/zhouning/Downloads/tap_uwm --output-dir data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06 --max-grid-series-per-period 5000
```

Expected: exits 0 and prints final overall results.

- [ ] **Step 6: Commit script and artifacts**

Run:

```bash
git add scripts/build_uwm_tap_external_dynamics.py
git add -f data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06/tap_external_dynamics_report.json data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06/snapshot_manifest.json
git commit -m "feat: build tap external dynamics artifacts"
```

Expected: commit includes script and generated JSON artifacts, not raw TAP zips.

---

### Task 4: Report and Evidence-Gate Updates

**Files:**
- Modify: `docs/reports/uwm_data_foundation_manifest.csv`
- Modify: `docs/reports/uwm_data_foundation_manifest.md`
- Modify: `docs/reports/uwm_data_foundation_coverage_audit.md`
- Modify: `docs/reports/uwm_data_foundation_summary_2026-07-05.md`
- Modify: `docs/reports/uwm_track2_research_log.md`

- [ ] **Step 1: Inspect generated artifact values**

Run:

```bash
uv run python - <<'PY'
import json
from pathlib import Path
p = Path("data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06/tap_external_dynamics_report.json")
payload = json.loads(p.read_text(encoding="utf-8"))
print(payload["supported_claim"])
print(payload["claim_boundary"]["max_claim_level"])
print(payload["overall_results"])
print(payload["empirical_superiority_claim"])
print(payload["observed_policy_outcome_superiority_claim"])
PY
```

Expected:

- policy flags print `False`;
- claim boundary is `bounded_support` or `not_for_claim` depending on real results;
- no policy outcome claim appears.

- [ ] **Step 2: Add manifest row**

Append a row to `docs/reports/uwm_data_foundation_manifest.csv` using the actual supported claim from Step 1:

```csv
tap_pm25_external_spatiotemporal_dynamics_chongqing_2018_2024,TAP external spatiotemporal PM2.5 dynamics holdout for UWM,public,data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06/snapshot_manifest.json;source_root=/Users/zhouning/Downloads/tap_uwm,available,Chongqing municipality and surrounding TAP tile bbox,2018-10-17_to_2018-10-23;2024-07-01_to_2024-07-07,external_dynamics_holdout_json,EPSG:4326,TAP_noncommercial_terms_no_redistribution,local TAP package parsed and evaluated on 2026-07-06;external dynamics holdout compares static non-spatial dynamic and spatial-message UWM state models;raw TAP zips not redistributed,tap_gridded_external_dynamics_not_station_or_policy_outcome,public_proxy,air_pollution_exposure;state_dynamics_validation;external_holdout;evidence_gate,bounded_support
```

If the generated artifact has `claim_boundary.max_claim_level = not_for_claim`, set the last column to `not_for_claim` instead of `bounded_support`.

- [ ] **Step 3: Update markdown reports**

Add a concise update block to each markdown report:

```text
TAP external dynamics update on 2026-07-06: UWM now evaluates TAP PM2.5 as an
external gridded state-dynamics holdout, comparing traditional static baselines,
non-spatial online dynamic baselines, and the spatial-message UWM dynamics model.
This strengthens the overall UWM evidence chain at the state-transition layer, but
it remains action-free air-pollution dynamics evidence, not observed policy outcome
superiority.
```

Update manifest row counts from `65` to `66` where applicable.

In `docs/reports/uwm_track2_research_log.md`, add a new dated entry summarizing:

- artifact path;
- static baseline comparison;
- non-spatial dynamic comparison;
- spatial negative-control result;
- supported claim or downgrade;
- policy flags remain false.

- [ ] **Step 4: Verify manifest audit**

Run:

```bash
uv run python - <<'PY'
from data_agent.uwm.data_foundation import audit_uwm_data_foundation_manifest
audit = audit_uwm_data_foundation_manifest("docs/reports/uwm_data_foundation_manifest.csv")
print(audit.get("manifest_valid", audit.get("valid")))
print(audit.get("manifest_errors") or audit.get("errors"))
print(audit.get("manifest_row_count") or audit.get("row_count"))
PY
```

Expected:

```text
True
[]
66
```

- [ ] **Step 5: Run report-related tests**

Run:

```bash
uv run python -m pytest data_agent/test_uwm_data_foundation.py data_agent/test_uwm_manifest.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit report updates**

Run:

```bash
git add docs/reports/uwm_data_foundation_manifest.csv docs/reports/uwm_data_foundation_manifest.md docs/reports/uwm_data_foundation_coverage_audit.md docs/reports/uwm_data_foundation_summary_2026-07-05.md docs/reports/uwm_track2_research_log.md
git commit -m "docs: register tap external dynamics evidence"
```

Expected: commit includes only report updates.

---

### Task 5: Final Verification

**Files:**
- No new files unless verification reveals a defect.

- [ ] **Step 1: Run all UWM tests**

Run:

```bash
uv run python -m pytest data_agent/test_uwm_*.py -q
```

Expected: all UWM tests pass.

- [ ] **Step 2: Inspect final claim guard**

Run:

```bash
uv run python - <<'PY'
import json
from pathlib import Path
p = Path("data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06/tap_external_dynamics_report.json")
payload = json.loads(p.read_text(encoding="utf-8"))
print(payload["supported_claim"])
print(payload["claim_boundary"]["max_claim_level"])
print(payload["empirical_superiority_claim"])
print(payload["observed_policy_outcome_superiority_claim"])
print(payload["overall_results"])
PY
```

Expected:

- claim is one of the three allowed strings;
- policy flags are `False`;
- overall results contain static, non-spatial dynamic, spatial, and negative-control metrics.

- [ ] **Step 3: Check raw TAP data was not added**

Run:

```bash
git status --short data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06
```

Expected: only repo JSON artifacts are tracked or modified. Raw TAP files remain outside the repo at `/Users/zhouning/Downloads/tap_uwm`.

- [ ] **Step 4: Final status check**

Run:

```bash
git status --short data_agent/test_uwm_tap_external_dynamics.py data_agent/uwm/tap_external_dynamics.py scripts/build_uwm_tap_external_dynamics.py docs/reports/uwm_data_foundation_manifest.csv docs/reports/uwm_data_foundation_manifest.md docs/reports/uwm_data_foundation_coverage_audit.md docs/reports/uwm_data_foundation_summary_2026-07-05.md docs/reports/uwm_track2_research_log.md data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06
```

Expected: no uncommitted changes for task-related paths.

---

## Self-Review

- Spec coverage: plan implements TAP external dynamics module, real artifact builder, claim guards, negative controls, report registration, and final verification.
- Overall UWM requirement: the plan treats this as a state-transition layer contribution to UWM's overall architecture, not a single-point or policy-outcome claim.
- Placeholder scan: no `TBD`, `TODO`, or vague implementation steps remain.
- Type consistency: schema, function names, file paths, artifact paths, and claim strings match the approved design.
- Scope check: admin zonal TAP aggregation, planner retraining, and observed policy outcome OPE remain out of scope.
