#!/usr/bin/env python3
"""Build label-independent baselines and deterministic negative-control inputs."""

from __future__ import annotations

import argparse
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

from benchmarks.gwm_bench_foundation_v0_1.controlled_evaluator import (
    EDGE_KEYS,
    EDGE_PREDICTIONS,
    NODE_KEYS,
    NODE_PREDICTIONS,
    evaluate_controlled_submission,
)
from benchmarks.gwm_bench_foundation_v0_1.observed_evaluator import (
    KEY_COLUMNS,
    PROBABILITY_COLUMNS,
    evaluate_observed_submission,
)
from benchmarks.gwm_bench_foundation_v0_1.readiness import sha256_file


BENCHMARK_ROOT = Path(__file__).resolve().parent
DEVELOPMENT_ROOT = BENCHMARK_ROOT / "development"
DEFAULT_BASELINE_ROOT = DEVELOPMENT_ROOT / "baselines"
DEFAULT_CONTROL_ROOT = DEVELOPMENT_ROOT / "controls"
BUILDER_PATH = Path(__file__).resolve()
TARGET_YEARS = (2021, 2022, 2023)
CLASS_COUNT = 9


def _write_parquet(frame: pd.DataFrame, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)
    return {
        "path": str(path.relative_to(BENCHMARK_ROOT)),
        "row_count": int(len(frame)),
        "sha256": sha256_file(path),
    }


def _observed_submission_rows(
    inputs: pd.DataFrame, probability_by_key: dict[tuple, np.ndarray]
) -> pd.DataFrame:
    rows = []
    for input_row in inputs.itertuples(index=False):
        for target_year in TARGET_YEARS:
            key = (
                int(input_row.fold_index),
                input_row.region_id,
                input_row.node_id,
                target_year,
            )
            probability = np.asarray(probability_by_key[key], dtype=np.float64)
            if probability.shape != (CLASS_COUNT,):
                raise ValueError("baseline_probability_shape_mismatch")
            row = dict(zip(KEY_COLUMNS, key))
            row.update(
                {
                    column: float(probability[class_index])
                    for class_index, column in enumerate(PROBABILITY_COLUMNS)
                }
            )
            rows.append(row)
    frame = pd.DataFrame(rows, columns=KEY_COLUMNS + PROBABILITY_COLUMNS)
    if frame.duplicated(KEY_COLUMNS).any():
        raise ValueError("duplicate_observed_baseline_keys")
    values = frame[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
    if not np.isfinite(values).all() or not np.allclose(
        values.sum(axis=1), 1.0, atol=1e-12, rtol=0.0
    ):
        raise ValueError("invalid_observed_baseline_probabilities")
    return frame


def _persistence_probabilities(inputs: pd.DataFrame) -> dict[tuple, np.ndarray]:
    probabilities = {}
    for row in inputs.itertuples(index=False):
        probability = np.eye(CLASS_COUNT, dtype=np.float64)[row.land_class_2020]
        for target_year in TARGET_YEARS:
            probabilities[
                (row.fold_index, row.region_id, row.node_id, target_year)
            ] = probability
    return probabilities


def _history_only_probabilities(inputs: pd.DataFrame) -> dict[tuple, np.ndarray]:
    weights = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
    probabilities = {}
    for row in inputs.itertuples(index=False):
        classes = np.array(
            [
                row.land_class_2017,
                row.land_class_2018,
                row.land_class_2019,
                row.land_class_2020,
            ],
            dtype=np.int64,
        )
        probability = np.bincount(
            classes, weights=weights, minlength=CLASS_COUNT
        ).astype(np.float64)
        probability /= probability.sum()
        for target_year in TARGET_YEARS:
            probabilities[
                (row.fold_index, row.region_id, row.node_id, target_year)
            ] = probability
    return probabilities


def _transition_matrix(train: pd.DataFrame, fold_index: int) -> np.ndarray:
    fold = train[train["fold_index"] == fold_index].sort_values(
        ["region_id", "node_id", "year"], kind="mergesort"
    )
    counts = np.ones((CLASS_COUNT, CLASS_COUNT), dtype=np.float64)
    for _, group in fold.groupby(["region_id", "node_id"], sort=False):
        years = group["year"].to_numpy(dtype=np.int64)
        classes = group["land_class"].to_numpy(dtype=np.int64)
        if not np.array_equal(years, np.array([2017, 2018, 2019, 2020])):
            raise ValueError("training_node_must_have_exact_2017_2020_history")
        for source_class, target_class in zip(classes[:-1], classes[1:]):
            counts[source_class, target_class] += 1.0
    return counts / counts.sum(axis=1, keepdims=True)


def _one_step_probabilities(
    inputs: pd.DataFrame, train: pd.DataFrame
) -> dict[tuple, np.ndarray]:
    probabilities = {}
    for fold_index, fold_inputs in inputs.groupby("fold_index", sort=True):
        transition = _transition_matrix(train, int(fold_index))
        for row in fold_inputs.itertuples(index=False):
            state = np.eye(CLASS_COUNT, dtype=np.float64)[row.land_class_2020]
            for target_year in TARGET_YEARS:
                state = state @ transition
                probabilities[
                    (row.fold_index, row.region_id, row.node_id, target_year)
                ] = state.copy()
    return probabilities


def _fixed_adjacency_probabilities(
    inputs: pd.DataFrame, train: pd.DataFrame, edges: pd.DataFrame
) -> dict[tuple, np.ndarray]:
    probabilities = {}
    for (fold_index, region_id), region_inputs in inputs.groupby(
        ["fold_index", "region_id"], sort=True
    ):
        transition = _transition_matrix(train, int(fold_index))
        region_inputs = region_inputs.sort_values("node_id", kind="mergesort")
        node_ids = region_inputs["node_id"].tolist()
        node_index = {node_id: index for index, node_id in enumerate(node_ids)}
        state = np.eye(CLASS_COUNT, dtype=np.float64)[
            region_inputs["land_class_2020"].to_numpy(dtype=np.int64)
        ]
        neighbors: list[list[int]] = [[] for _ in node_ids]
        region_edges = edges[edges["region_id"] == region_id]
        for edge in region_edges.itertuples(index=False):
            if edge.source_node_id in node_index and edge.target_node_id in node_index:
                neighbors[node_index[edge.source_node_id]].append(
                    node_index[edge.target_node_id]
                )
        for target_year in TARGET_YEARS:
            neighbor_state = np.stack(
                [
                    state[indices].mean(axis=0) if indices else state[index]
                    for index, indices in enumerate(neighbors)
                ]
            )
            state = 0.5 * (state @ transition) + 0.5 * (
                neighbor_state @ transition
            )
            state /= state.sum(axis=1, keepdims=True)
            for index, node_id in enumerate(node_ids):
                probabilities[(fold_index, region_id, node_id, target_year)] = state[
                    index
                ].copy()
    return probabilities


def _controlled_zero_submissions(
    nodes: pd.DataFrame, edges: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    development_nodes = nodes[nodes["split"] == "development"]
    node_rows = []
    for row in development_nodes.itertuples(index=False):
        for horizon in (1, 2, 3):
            node_rows.append(
                {
                    "sample_id": row.sample_id,
                    "node_id": row.node_id,
                    "horizon": horizon,
                    "predicted_state_delta_0": 0.0,
                    "predicted_state_delta_1": 0.0,
                    "predicted_state_delta_2": 0.0,
                }
            )
    node = pd.DataFrame(node_rows, columns=NODE_KEYS + NODE_PREDICTIONS)
    development_edges = edges[edges["split"] == "development"]
    edge = development_edges[EDGE_KEYS].copy()
    edge["predicted_effective_action_gate"] = 0.0
    edge["predicted_topology_probability"] = 0.0
    edge["predicted_lag_horizon_1"] = 1.0 / 3.0
    edge["predicted_lag_horizon_2"] = 1.0 / 3.0
    edge["predicted_lag_horizon_3"] = 1.0 / 3.0
    return node, edge[EDGE_KEYS + EDGE_PREDICTIONS]


def _materialize_controls(
    *,
    controlled_nodes: pd.DataFrame,
    controlled_edges: pd.DataFrame,
    observed_inputs: pd.DataFrame,
    observed_edges: pd.DataFrame,
    output_root: Path,
) -> list[dict[str, Any]]:
    resources = []
    no_action = controlled_nodes.copy()
    action_columns = [
        "action_type_0",
        "action_type_1",
        "action_type_2",
        "action_intensity",
    ]
    no_action[action_columns] = 0.0
    resources.append(
        _write_parquet(no_action, output_root / "controlled_no_action_nodes.parquet")
    )

    action_shuffle = controlled_nodes.copy()
    for _, indices in action_shuffle.groupby("split", sort=True).indices.items():
        positions = np.asarray(indices, dtype=np.int64)
        action_shuffle.iloc[
            positions, action_shuffle.columns.get_indexer(action_columns)
        ] = np.roll(
            action_shuffle.iloc[positions][action_columns].to_numpy(), 7, axis=0
        )
    resources.append(
        _write_parquet(
            action_shuffle, output_root / "controlled_action_shuffle_nodes.parquet"
        )
    )

    single_relation = controlled_edges.copy()
    single_relation["relation_type"] = 0
    resources.append(
        _write_parquet(
            single_relation, output_root / "controlled_single_relation_edges.parquet"
        )
    )

    relation_shuffle = controlled_edges.copy()
    for _, indices in relation_shuffle.groupby("split", sort=True).indices.items():
        positions = np.asarray(indices, dtype=np.int64)
        relation_shuffle.iloc[
            positions, relation_shuffle.columns.get_loc("relation_type")
        ] = np.roll(
            relation_shuffle.iloc[positions]["relation_type"].to_numpy(), 11
        )
    resources.append(
        _write_parquet(
            relation_shuffle,
            output_root / "controlled_relation_shuffle_edges.parquet",
        )
    )

    controlled_rewire = controlled_edges.copy()
    for _, indices in controlled_rewire.groupby("split", sort=True).indices.items():
        positions = np.asarray(indices, dtype=np.int64)
        controlled_rewire.iloc[
            positions, controlled_rewire.columns.get_loc("target_node_id")
        ] = np.roll(
            controlled_rewire.iloc[positions]["target_node_id"].to_numpy(), 13
        )
    resources.append(
        _write_parquet(
            controlled_rewire,
            output_root / "controlled_spatial_rewire_edges.parquet",
        )
    )

    history_shuffle = observed_inputs.copy()
    history_columns = [f"land_class_{year}" for year in range(2017, 2021)]
    for _, indices in history_shuffle.groupby(
        ["fold_index", "split", "region_id"], sort=True
    ).indices.items():
        positions = np.asarray(indices, dtype=np.int64)
        history_shuffle.iloc[
            positions, history_shuffle.columns.get_indexer(history_columns)
        ] = np.roll(
            history_shuffle.iloc[positions][history_columns].to_numpy(), 7, axis=0
        )
    resources.append(
        _write_parquet(
            history_shuffle, output_root / "observed_history_shuffle_inputs.parquet"
        )
    )

    observed_rewire = observed_edges.copy()
    for _, indices in observed_rewire.groupby("region_id", sort=True).indices.items():
        positions = np.asarray(indices, dtype=np.int64)
        targets = observed_rewire.iloc[positions]["target_node_id"].to_numpy().copy()
        rewired = np.roll(targets, 13)
        sources = observed_rewire.iloc[positions]["source_node_id"].to_numpy()
        for index in range(len(rewired)):
            if rewired[index] == sources[index]:
                rewired[index] = targets[(index + 1) % len(targets)]
        observed_rewire.iloc[
            positions, observed_rewire.columns.get_loc("target_node_id")
        ] = rewired
    resources.append(
        _write_parquet(
            observed_rewire, output_root / "observed_spatial_rewire_edges.parquet"
        )
    )
    return resources


def build_baselines_and_controls(
    *,
    baseline_root: Path = DEFAULT_BASELINE_ROOT,
    control_root: Path = DEFAULT_CONTROL_ROOT,
) -> dict[str, Any]:
    controlled_nodes = pd.read_parquet(DEVELOPMENT_ROOT / "controlled_nodes.parquet")
    controlled_edges = pd.read_parquet(DEVELOPMENT_ROOT / "controlled_edges.parquet")
    observed_train = pd.read_parquet(DEVELOPMENT_ROOT / "observed_train.parquet")
    observed_inputs = pd.read_parquet(DEVELOPMENT_ROOT / "observed_inputs.parquet")
    observed_edges = pd.read_parquet(DEVELOPMENT_ROOT / "observed_edges.parquet")
    test_inputs = observed_inputs[observed_inputs["split"] == "test"].copy()

    controlled_node, controlled_edge = _controlled_zero_submissions(
        controlled_nodes, controlled_edges
    )
    baseline_frames = {
        "controlled_zero_node_submission.parquet": controlled_node,
        "controlled_zero_edge_submission.parquet": controlled_edge,
        "observed_persistence_submission.parquet": _observed_submission_rows(
            test_inputs, _persistence_probabilities(test_inputs)
        ),
        "observed_history_only_submission.parquet": _observed_submission_rows(
            test_inputs, _history_only_probabilities(test_inputs)
        ),
        "observed_independent_one_step_submission.parquet": _observed_submission_rows(
            test_inputs, _one_step_probabilities(test_inputs, observed_train)
        ),
        "observed_fixed_adjacency_submission.parquet": _observed_submission_rows(
            test_inputs,
            _fixed_adjacency_probabilities(
                test_inputs, observed_train, observed_edges
            ),
        ),
    }
    baseline_resources = [
        _write_parquet(frame, baseline_root / name)
        for name, frame in baseline_frames.items()
    ]
    committed_hashes = {
        row["path"]: row["sha256"] for row in baseline_resources
    }

    controlled_report = evaluate_controlled_submission(
        node_submission_path=baseline_root
        / "controlled_zero_node_submission.parquet",
        edge_submission_path=baseline_root
        / "controlled_zero_edge_submission.parquet",
    )
    observed_reports = {
        name.removeprefix("observed_").removesuffix("_submission.parquet"):
        evaluate_observed_submission(submission_path=baseline_root / name)
        for name in baseline_frames
        if name.startswith("observed_")
    }
    if committed_hashes != {
        row["path"]: sha256_file(BENCHMARK_ROOT / row["path"])
        for row in baseline_resources
    }:
        raise ValueError("baseline_changed_after_prediction_commit")

    control_resources = _materialize_controls(
        controlled_nodes=controlled_nodes,
        controlled_edges=controlled_edges,
        observed_inputs=observed_inputs,
        observed_edges=observed_edges,
        output_root=control_root,
    )
    control_manifest = {
        "schema": "gwm_bench.foundation_control_manifest.v1",
        "benchmark_id": "gwm-bench-foundation-v0.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "resources": control_resources,
        "transformations": {
            "controlled_no_action_conditioning": "set all four action columns to zero",
            "controlled_action_assignment_shuffle": "roll complete action rows by 7 within split",
            "controlled_single_relation": "set relation_type to zero",
            "controlled_relation_type_shuffle": "roll relation_type by 11 within split",
            "controlled_spatial_target_rewire": "roll target_node_id by 13 within split",
            "observed_temporal_history_shuffle": "roll 2017-2020 land histories by 7 within fold, split and region",
            "observed_spatial_target_rewire": "roll target_node_id by 13 within region and avoid self targets",
            "frozen_topology": "candidate-side ablation: prohibit learned edge additions, deletions or weights",
            "no_lag_structure": "candidate-side ablation: use a single immediate transition step",
        },
        "labels_read_to_build_controls": False,
    }
    control_manifest_path = control_root / "control_manifest.json"
    control_manifest_path.write_text(
        json.dumps(control_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = {
        "schema": "gwm_bench.foundation_baseline_report.v1",
        "benchmark_id": "gwm-bench-foundation-v0.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "baselines_and_controls_materialized",
        "protocol": {
            "predictions_committed_before_evaluator_label_access": True,
            "future_observed_inputs_used": False,
            "period_mean_viirs_used": False,
            "llm_judge_used": False,
            "baseline_score_is_benchmark_readiness_gate": False,
        },
        "baseline_resources": baseline_resources,
        "control_manifest": {
            "path": str(control_manifest_path.relative_to(BENCHMARK_ROOT)),
            "sha256": sha256_file(control_manifest_path),
            "resource_count": len(control_resources),
        },
        "controlled_zero_baseline": controlled_report,
        "observed_baselines": observed_reports,
        "source_artifacts": {
            "builder": {
                "path": str(BUILDER_PATH.relative_to(REPO_ROOT)),
                "sha256": sha256_file(BUILDER_PATH),
            },
            "controlled_evaluator": {
                "path": "benchmarks/gwm_bench_foundation_v0_1/controlled_evaluator.py",
                "sha256": sha256_file(BENCHMARK_ROOT / "controlled_evaluator.py"),
            },
            "observed_evaluator": {
                "path": "benchmarks/gwm_bench_foundation_v0_1/observed_evaluator.py",
                "sha256": sha256_file(BENCHMARK_ROOT / "observed_evaluator.py"),
            },
            "bundle_manifest": {
                "path": "benchmarks/gwm_bench_foundation_v0_1/development/bundle_manifest.json",
                "sha256": sha256_file(DEVELOPMENT_ROOT / "bundle_manifest.json"),
            },
        },
        "claim_boundary": {
            "baseline_outperformance_required_for_benchmark_validity": False,
            "candidate_model_validated": False,
            "general_gwm_supported": False,
        },
    }
    report_path = baseline_root / "baseline_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, default=DEFAULT_BASELINE_ROOT)
    parser.add_argument("--control-root", type=Path, default=DEFAULT_CONTROL_ROOT)
    args = parser.parse_args()
    report = build_baselines_and_controls(
        baseline_root=args.baseline_root, control_root=args.control_root
    )
    summary = {
        "status": report["status"],
        "controlled_primary": report["controlled_zero_baseline"]["metrics"][
            "affected_node_state_delta_mae"
        ],
        "observed_primary": {
            name: result["primary_metric"]["value"]
            for name, result in report["observed_baselines"].items()
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
