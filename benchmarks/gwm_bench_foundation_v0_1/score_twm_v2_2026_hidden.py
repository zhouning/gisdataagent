#!/usr/bin/env python3
"""Score the precommitted 2026 forecast after full-year labels are registered."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.gwm_bench_foundation_v0_1.commit_twm_v2_2026_forecast import (
    DEFAULT_OUTPUT_ROOT as DEFAULT_PRECOMMIT_ROOT,
    SCORED_YEAR,
    _sha256,
)
from benchmarks.gwm_bench_foundation_v0_1.observed_evaluator import (
    KEY_COLUMNS,
    PROBABILITY_COLUMNS,
    _score_group,
)


BENCHMARK_ROOT = Path(__file__).resolve().parent
DEVELOPMENT_ROOT = BENCHMARK_ROOT / "development"
SOURCE_ROOT = REPO_ROOT / "data/twm_public_landcover/gee_dynamic_world"
DEFAULT_LABEL_MANIFEST = SOURCE_ROOT / "twm_v2_2026_hidden_label_registration.json"
DEFAULT_EVALUATOR_SEAL = (
    DEFAULT_PRECOMMIT_ROOT / "evaluator_implementation_seal.json"
)
DEFAULT_OUTPUT = DEFAULT_PRECOMMIT_ROOT / "hidden_2026_evaluation.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _repo_artifact_path(artifact: dict[str, Any]) -> Path:
    path = (REPO_ROOT / artifact["path"]).resolve()
    if (
        not path.is_file()
        or path.stat().st_size != int(artifact["size_bytes"])
        or _sha256(path) != artifact["sha256"]
    ):
        raise ValueError(f"twm_v2_2026_artifact_mismatch:{path}")
    return path


def _grid(path: Path) -> dict[str, Any]:
    with rasterio.open(path) as dataset:
        return {
            "width": dataset.width,
            "height": dataset.height,
            "count": dataset.count,
            "dtype": dataset.dtypes[0],
            "crs": dataset.crs.to_string() if dataset.crs else None,
            "transform": list(dataset.transform)[:6],
            "nodata": dataset.nodata,
        }


def hidden_label_readiness(label_manifest_path: Path) -> dict[str, Any]:
    if not label_manifest_path.is_file():
        return {
            "status": "pending_full_calendar_2026_labels",
            "manifest": str(label_manifest_path),
            "earliest_valid_export_date": "2027-01-01",
        }
    manifest = _load_json(label_manifest_path)
    return {
        "status": manifest.get("status", "invalid_unrecognized_manifest"),
        "manifest": str(label_manifest_path),
        "registered_at": manifest.get("registered_at"),
    }


def _verify_evaluator_seal(
    *, seal_path: Path, protocol_path: Path
) -> dict[str, Any]:
    seal = _load_json(seal_path)
    if seal["status"] != "evaluator_sealed_before_2026_labels":
        raise ValueError("twm_v2_2026_evaluator_is_not_sealed")
    if seal["protocol_sha256"] != _sha256(protocol_path):
        raise ValueError("twm_v2_2026_evaluator_protocol_hash_mismatch")
    if seal["scorer_sha256"] != _sha256(Path(__file__)):
        raise ValueError("twm_v2_2026_scorer_changed_after_seal")
    for artifact in seal["dependencies"]:
        _repo_artifact_path(artifact)
    return seal


def _verify_label_manifest(
    *, manifest_path: Path, protocol: dict[str, Any]
) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    if manifest.get("schema") != "gwm_bench.twm_v2_2026_hidden_labels.v1":
        raise ValueError("twm_v2_2026_hidden_label_schema_mismatch")
    if manifest.get("status") != "registered_after_full_calendar_2026":
        raise ValueError("twm_v2_2026_hidden_labels_are_not_registered")
    if manifest.get("protocol_id") != protocol["protocol_id"]:
        raise ValueError("twm_v2_2026_hidden_label_protocol_mismatch")
    if str(manifest.get("registered_at", ""))[:10] < "2027-01-01":
        raise ValueError("twm_v2_2026_labels_registered_before_full_year_complete")
    by_region = {row["region_id"]: row for row in manifest.get("regions", [])}
    if set(by_region) != set(protocol["scored_regions"]):
        raise ValueError("twm_v2_2026_hidden_label_region_set_mismatch")
    for region_id, region in by_region.items():
        by_year = {int(row["year"]): row for row in region.get("labels", [])}
        if set(by_year) != {2025, 2026}:
            raise ValueError(f"twm_v2_2026_label_year_set_mismatch:{region_id}")
        reference = (
            SOURCE_ROOT
            / region_id
            / f"{region_id}_dynamic_world_2020_100m.tif"
        )
        reference_grid = _grid(reference)
        for year, artifact in by_year.items():
            path = _repo_artifact_path(artifact)
            if _grid(path) != reference_grid:
                raise ValueError(
                    f"twm_v2_2026_hidden_label_grid_mismatch:{region_id}:{year}"
                )
    return manifest


def _read_labels(
    *, manifest: dict[str, Any], sampled_inputs: pd.DataFrame
) -> pd.DataFrame:
    path_by_key = {
        (region["region_id"], int(label["year"])): _repo_artifact_path(label)
        for region in manifest["regions"]
        for label in region["labels"]
    }
    arrays = {}
    for key, path in sorted(path_by_key.items()):
        with rasterio.open(path) as dataset:
            arrays[key] = (dataset.read(1), dataset.nodata)
    rows = []
    for input_row in sampled_inputs.itertuples(index=False):
        values = {}
        for year in (2025, 2026):
            array, nodata = arrays[(input_row.region_id, year)]
            value = array[int(input_row.raster_row), int(input_row.raster_column)]
            if (
                not np.isfinite(value)
                or (nodata is not None and value == nodata)
                or not float(value).is_integer()
                or not 0 <= int(value) < 9
            ):
                raise ValueError(
                    f"invalid_twm_v2_2026_label:{input_row.region_id}:"
                    f"{input_row.node_id}:{year}"
                )
            values[year] = int(value)
        rows.append(
            {
                "fold_index": int(input_row.fold_index),
                "region_id": input_row.region_id,
                "node_id": input_row.node_id,
                "target_year": SCORED_YEAR,
                "target_class": values[2026],
                "changed_from_previous_observed_year": values[2026] != values[2025],
            }
        )
    return pd.DataFrame(rows)


def _validate_prediction(
    *, prediction: pd.DataFrame, expected_keys: pd.DataFrame
) -> None:
    if list(prediction.columns) != KEY_COLUMNS + PROBABILITY_COLUMNS:
        raise ValueError("twm_v2_2026_prediction_columns_mismatch")
    keys = prediction[KEY_COLUMNS].sort_values(KEY_COLUMNS).reset_index(drop=True)
    expected = expected_keys.sort_values(KEY_COLUMNS).reset_index(drop=True)
    if prediction.duplicated(KEY_COLUMNS).any() or not keys.equals(expected):
        raise ValueError("twm_v2_2026_prediction_keys_mismatch")
    values = prediction[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
    if not np.isfinite(values).all() or np.any((values < 0.0) | (values > 1.0)):
        raise ValueError("invalid_twm_v2_2026_prediction_probability")
    if not np.allclose(values.sum(axis=1), 1.0, atol=1e-6, rtol=0.0):
        raise ValueError("twm_v2_2026_prediction_rows_do_not_sum_to_one")


def _score_prediction(
    *, prediction: pd.DataFrame, labels: pd.DataFrame
) -> dict[str, Any]:
    bridge = prediction[prediction["target_year"].isin((2025, 2026))].copy()
    bridge["predicted_class"] = np.argmax(
        bridge[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64), axis=1
    ).astype(np.int64)
    wide = bridge.pivot(
        index=["fold_index", "region_id", "node_id"],
        columns="target_year",
        values="predicted_class",
    )
    predicted_change = (wide[2026] != wide[2025]).rename("predicted_change")
    forecast = bridge[bridge["target_year"] == 2026]
    scored = labels.merge(
        forecast[[*KEY_COLUMNS, "predicted_class", *PROBABILITY_COLUMNS]],
        on=KEY_COLUMNS,
        validate="one_to_one",
        sort=True,
    )
    scored = scored.merge(
        predicted_change.reset_index(),
        on=["fold_index", "region_id", "node_id"],
        validate="one_to_one",
        sort=True,
    )
    by_region = [
        {"region_id": region_id, **_score_group(group)}
        for region_id, group in scored.groupby("region_id", sort=True)
    ]
    overall = _score_group(scored)
    observed = int(overall["observed_changed_count"])
    return {
        "primary_metric": {
            "name": "mean_region_2026_change_f1",
            "value": float(np.mean([row["change_f1"] for row in by_region])),
            "component_count": len(by_region),
            "aggregation": "unweighted_mean",
        },
        "overall_secondary_metrics": {
            **overall,
            "predicted_to_observed_change_ratio": (
                float(overall["predicted_changed_count"] / observed)
                if observed
                else None
            ),
        },
        "metrics_by_region": by_region,
    }


def _acceptance(
    *, evaluations: dict[str, dict[str, Any]], labels: pd.DataFrame
) -> dict[str, Any]:
    observed_by_region = labels.groupby("region_id")[
        "changed_from_previous_observed_year"
    ].sum()
    total_changes = int(observed_by_region.sum())
    changed_regions = int((observed_by_region > 0).sum())
    sufficient = total_changes >= 20 and changed_regions >= 10
    candidate = evaluations["twm_v2"]
    persistence = evaluations["persistence"]
    baselines = [persistence, evaluations["fixed_adjacency"]]
    primary = candidate["primary_metric"]["value"]
    overall = candidate["overall_secondary_metrics"]
    ratio = overall["predicted_to_observed_change_ratio"]
    gates = {
        "primary_exceeds_both_baselines": all(
            primary > row["primary_metric"]["value"] for row in baselines
        ),
        "overall_change_f1_exceeds_both_baselines": all(
            overall["change_f1"] > row["overall_secondary_metrics"]["change_f1"]
            for row in baselines
        ),
        "overall_change_f1_at_least_0_15": overall["change_f1"] >= 0.15,
        "class_macro_f1_at_least_persistence": (
            overall["overall_class_macro_f1"]
            >= persistence["overall_secondary_metrics"]["overall_class_macro_f1"]
        ),
        "brier_no_greater_than_persistence": (
            overall["multiclass_brier_score"]
            <= persistence["overall_secondary_metrics"]["multiclass_brier_score"]
        ),
        "change_ratio_between_0_5_and_1_75": (
            ratio is not None and 0.5 <= ratio <= 1.75
        ),
    }
    status = (
        "inconclusive_insufficient_observed_change"
        if not sufficient
        else "pass"
        if all(gates.values())
        else "fail"
    )
    return {
        "status": status,
        "data_sufficiency": {
            "pass": sufficient,
            "total_observed_changes": total_changes,
            "regions_with_observed_change": changed_regions,
            "minimum_total_observed_changes": 20,
            "minimum_regions_with_observed_change": 10,
        },
        "gates": gates,
        "all_required_gates_pass": all(gates.values()),
    }


def score_twm_v2_2026_hidden(
    *,
    precommit_root: Path = DEFAULT_PRECOMMIT_ROOT,
    label_manifest_path: Path = DEFAULT_LABEL_MANIFEST,
    evaluator_seal_path: Path = DEFAULT_EVALUATOR_SEAL,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    precommit_root = precommit_root.resolve()
    protocol_path = precommit_root / "precommit_protocol.json"
    protocol = _load_json(protocol_path)
    if protocol["status"] != "candidate_and_predictions_sealed_before_2026_labels":
        raise ValueError("twm_v2_2026_predictions_are_not_precommitted")
    _verify_evaluator_seal(
        seal_path=evaluator_seal_path.resolve(), protocol_path=protocol_path
    )

    artifacts = {
        "twm_v2": protocol["artifacts"]["prediction"],
        **protocol["artifacts"]["baselines"],
    }
    predictions = {
        name: pd.read_parquet(_repo_artifact_path(artifact))
        for name, artifact in artifacts.items()
    }
    inputs = pd.read_parquet(DEVELOPMENT_ROOT / "observed_inputs.parquet")
    test_inputs = inputs[inputs["split"] == "test"].copy()
    expected_keys = test_inputs[KEY_COLUMNS[:-1]].merge(
        pd.DataFrame({"target_year": protocol["prediction_years"]}), how="cross"
    )[KEY_COLUMNS]
    for prediction in predictions.values():
        _validate_prediction(prediction=prediction, expected_keys=expected_keys)

    # Hidden files are opened only after every sealed prediction hash and key passes.
    manifest = _verify_label_manifest(
        manifest_path=label_manifest_path.resolve(), protocol=protocol
    )
    labels = _read_labels(manifest=manifest, sampled_inputs=test_inputs)
    evaluations = {
        name: _score_prediction(prediction=prediction, labels=labels)
        for name, prediction in predictions.items()
    }
    acceptance = _acceptance(evaluations=evaluations, labels=labels)
    report = {
        "schema": "gwm_bench.twm_v2_2026_hidden_evaluation.v1",
        "protocol_id": protocol["protocol_id"],
        "candidate_fingerprint": protocol["candidate_fingerprint"],
        "status": acceptance["status"],
        "evaluations": evaluations,
        "acceptance": acceptance,
        "integrity": {
            "evaluator_seal_verified": True,
            "all_prediction_hashes_verified_before_label_access": True,
            "all_prediction_keys_verified_before_label_access": True,
            "hidden_label_hashes_and_grids_verified": True,
        },
        "claim_boundary": protocol["claim_boundary"],
    }
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--precommit-root", type=Path, default=DEFAULT_PRECOMMIT_ROOT)
    parser.add_argument("--label-manifest", type=Path, default=DEFAULT_LABEL_MANIFEST)
    parser.add_argument("--evaluator-seal", type=Path, default=DEFAULT_EVALUATOR_SEAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check-readiness", action="store_true")
    args = parser.parse_args()
    if args.check_readiness:
        print(
            json.dumps(
                hidden_label_readiness(args.label_manifest),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    score_twm_v2_2026_hidden(
        precommit_root=args.precommit_root,
        label_manifest_path=args.label_manifest,
        evaluator_seal_path=args.evaluator_seal,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
