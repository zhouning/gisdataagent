#!/usr/bin/env python3
"""Score the sealed GWM-Bench V2.0 candidates after 2026 labels exist."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.gwm_bench_foundation_v0_1.observed_evaluator import (  # noqa: E402
    KEY_COLUMNS,
    PROBABILITY_COLUMNS,
)
from benchmarks.gwm_bench_foundation_v0_1.score_twm_v2_2026_hidden import (  # noqa: E402
    DEFAULT_LABEL_MANIFEST,
    _acceptance,
    _read_labels,
    _score_prediction,
    _validate_prediction,
    _verify_label_manifest,
)


RELEASE_ROOT = Path(__file__).resolve().parent
DEFAULT_PROTOCOL = RELEASE_ROOT / "suite_protocol.json"
DEFAULT_OUTPUT = RELEASE_ROOT / "hidden_2026_evaluation.json"
BOOTSTRAP_DRAWS = 20_000
BOOTSTRAP_SEED = 20260723


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_path(artifact: dict[str, Any]) -> Path:
    path = Path(artifact["path"])
    if artifact.get("path_scope", "repository_relative") == "repository_relative":
        path = REPO_ROOT / path
    path = path.resolve()
    if (
        not path.is_file()
        or path.stat().st_size != int(artifact["size_bytes"])
        or _sha256(path) != artifact["sha256"]
    ):
        raise ValueError(f"v2_2026_artifact_mismatch:{path}")
    return path


def _expected_keys(inputs: pd.DataFrame, years: tuple[int, ...]) -> pd.DataFrame:
    test = inputs[inputs["split"] == "test"]
    rows = []
    for row in test.itertuples(index=False):
        rows.extend(
            {
                "fold_index": int(row.fold_index),
                "region_id": row.region_id,
                "node_id": row.node_id,
                "target_year": year,
            }
            for year in years
        )
    return pd.DataFrame(rows, columns=KEY_COLUMNS)


def _paired_region_bootstrap(
    *, left: dict[str, Any], right: dict[str, Any]
) -> dict[str, Any]:
    left_by_region = {
        row["region_id"]: float(row["change_f1"])
        for row in left["metrics_by_region"]
    }
    right_by_region = {
        row["region_id"]: float(row["change_f1"])
        for row in right["metrics_by_region"]
    }
    if left_by_region.keys() != right_by_region.keys():
        raise ValueError("v2_2026_bootstrap_region_mismatch")
    regions = sorted(left_by_region)
    differences = np.asarray(
        [left_by_region[region] - right_by_region[region] for region in regions],
        dtype=np.float64,
    )
    generator = np.random.default_rng(BOOTSTRAP_SEED)
    draws = generator.integers(
        0, len(regions), size=(BOOTSTRAP_DRAWS, len(regions))
    )
    bootstrap = differences[draws].mean(axis=1)
    return {
        "unit": "region",
        "region_count": len(regions),
        "mean_primary_difference": float(differences.mean()),
        "bootstrap_95_percent_interval": [
            float(np.quantile(bootstrap, 0.025)),
            float(np.quantile(bootstrap, 0.975)),
        ],
        "bootstrap_probability_difference_above_zero": float(
            np.mean(bootstrap > 0.0)
        ),
        "region_wins": int(np.sum(differences > 0.0)),
        "region_ties": int(np.sum(differences == 0.0)),
        "region_losses": int(np.sum(differences < 0.0)),
        "bootstrap_draw_count": BOOTSTRAP_DRAWS,
        "seed": BOOTSTRAP_SEED,
    }


def readiness(
    *, protocol_path: Path, label_manifest_path: Path
) -> dict[str, Any]:
    if not protocol_path.is_file():
        return {"status": "v2_rc1_protocol_missing"}
    protocol = _load_json(protocol_path)
    scorer = protocol["artifacts"]["scorer"]
    if _artifact_path(scorer) != Path(__file__).resolve():
        raise ValueError("v2_2026_scorer_identity_mismatch")
    if not label_manifest_path.is_file():
        return {
            "status": "rc1_ready_labels_pending",
            "earliest_valid_export_date": protocol["hidden_labels"][
                "earliest_valid_export_date"
            ],
            "label_manifest": str(label_manifest_path),
            "twm_prediction_sha256": protocol["artifacts"]["twm_prediction"][
                "sha256"
            ],
            "flus_prediction_sha256": protocol["artifacts"]["flus_prediction"][
                "sha256"
            ],
        }
    return {
        "status": "hidden_label_manifest_present_scoring_required",
        "label_manifest": str(label_manifest_path),
    }


def score_v2_hidden(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    label_manifest_path: Path = DEFAULT_LABEL_MANIFEST,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    protocol = _load_json(protocol_path)
    scorer = protocol["artifacts"]["scorer"]
    if _artifact_path(scorer) != Path(__file__).resolve():
        raise ValueError("v2_2026_scorer_changed_after_rc1_freeze")
    if not label_manifest_path.is_file():
        raise RuntimeError("full_calendar_2026_labels_not_registered")

    twm_protocol_path = _artifact_path(protocol["artifacts"]["twm_protocol"])
    twm_protocol = _load_json(twm_protocol_path)
    manifest = _verify_label_manifest(
        manifest_path=label_manifest_path, protocol=twm_protocol
    )
    inputs_path = REPO_ROOT / (
        "benchmarks/gwm_bench_foundation_v0_1/development/observed_inputs.parquet"
    )
    inputs = pd.read_parquet(inputs_path)
    labels = _read_labels(manifest=manifest, sampled_inputs=inputs[inputs["split"] == "test"])
    expected = _expected_keys(inputs, tuple(range(2021, 2027)))

    artifact_by_name = {
        "twm_v2": protocol["artifacts"]["twm_prediction"],
        "flus": protocol["artifacts"]["flus_prediction"],
        "persistence": protocol["artifacts"]["persistence_prediction"],
        "fixed_adjacency": protocol["artifacts"]["fixed_adjacency_prediction"],
    }
    predictions = {}
    evaluations = {}
    for name, artifact in artifact_by_name.items():
        path = _artifact_path(artifact)
        prediction = pd.read_parquet(path)
        _validate_prediction(prediction=prediction, expected_keys=expected)
        predictions[name] = prediction
        evaluations[name] = _score_prediction(prediction=prediction, labels=labels)

    internal_acceptance = _acceptance(evaluations=evaluations, labels=labels)
    twm_vs_flus = _paired_region_bootstrap(
        left=evaluations["twm_v2"], right=evaluations["flus"]
    )
    sufficient = internal_acceptance["data_sufficiency"]["passed"]
    report = {
        "schema": "gwm_bench.foundation_v2_2026_evaluation.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "v2_final_scored" if sufficient else "v2_final_scored_inconclusive"
        ),
        "evaluations": evaluations,
        "twm_internal_acceptance": internal_acceptance,
        "twm_vs_flus": {
            **twm_vs_flus,
            "twm_primary_strictly_exceeds_flus": evaluations["twm_v2"][
                "primary_metric"
            ]["value"]
            > evaluations["flus"]["primary_metric"]["value"],
            "paired_interval_strictly_above_zero": twm_vs_flus[
                "bootstrap_95_percent_interval"
            ][0]
            > 0.0,
        },
        "benchmark_completion": {
            "dataset_and_protocol_completed": True,
            "model_win_required_for_benchmark_completion": False,
            "negative_or_inconclusive_model_result_is_publishable": True,
        },
        "integrity": {
            "suite_protocol_sha256": _sha256(protocol_path),
            "label_manifest_sha256": _sha256(label_manifest_path),
            "prediction_sha256": {
                name: artifact["sha256"]
                for name, artifact in artifact_by_name.items()
            },
        },
        "claim_boundary": protocol["claim_boundary"],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": report["status"], "output": str(output_path)}, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--label-manifest", type=Path, default=DEFAULT_LABEL_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check-readiness", action="store_true")
    args = parser.parse_args()
    if args.check_readiness:
        print(
            json.dumps(
                readiness(
                    protocol_path=args.protocol.resolve(),
                    label_manifest_path=args.label_manifest.resolve(),
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    score_v2_hidden(
        protocol_path=args.protocol.resolve(),
        label_manifest_path=args.label_manifest.resolve(),
        output_path=args.output.resolve(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
