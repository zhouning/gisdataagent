#!/usr/bin/env python3
"""Run the frozen TWM/DAM-GK candidate on the V3 geographic lockbox inputs."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from torch.nn import functional as functional

from prediction_runtime import (
    BUNDLE_MANIFEST_PATH,
    BUNDLE_ROOT,
    DRAFT_ROOT,
    KEY_COLUMNS,
    PROBABILITY_COLUMNS,
    PROTOCOL_PATH,
    REPO_ROOT,
    SUBMISSION_CONTRACT_PATH,
    artifact,
    enforce_label_firewall,
    fingerprint,
    load_json,
    load_prediction_contract,
    peak_memory_bytes,
    prediction_summary,
    runtime_environment,
    sha256_file,
    utc_now,
    validate_submission,
    write_json_atomic,
    write_parquet_atomic,
)


if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.gwm_bench_foundation_v0_1.run_twm_multiregion_posthoc_v2 import (
    _rate_capped_update,
    _recursive_batch,
)
from benchmarks.gwm_bench_foundation_v0_1.run_twm_observed_scenario import (
    _build_region_sequence,
    _neighbor_indices,
)
from data_agent.uwm.dam_geospatial_kernel.twm_sequence_benchmark import (
    _kernel_config,
)
from data_agent.uwm.dam_geospatial_kernel.twm_transition_head import (
    TWMLandTransitionModel,
)


CLASS_COUNT = 9
HISTORY_YEARS = (2017, 2018, 2019, 2020, 2021, 2022)
TARGET_YEARS = (2023, 2024, 2025)
TRAINING_SEEDS = (31, 47, 73)
FOLD_INDEXES = (0, 1, 2, 3, 4)
V0_ROOT = REPO_ROOT / "benchmarks/gwm_bench_foundation_v0_1"
PRECOMMIT_PATH = (
    V0_ROOT
    / "development/multiregion_temporal_holdout/twm_v2_frozen_2026/precommit_protocol.json"
)
DEFAULT_OUTPUT_ROOT = DRAFT_ROOT / "predictions/twm_dam_gk_candidate"
SOURCE_DEPENDENCIES = (
    V0_ROOT / "run_twm_multiregion_posthoc_v2.py",
    V0_ROOT / "run_twm_observed_scenario.py",
    REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/twm_adapter.py",
    REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/twm_sequence_adapter.py",
    REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/model.py",
    REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/contracts.py",
    REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/twm_transition_head.py",
    REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/twm_sequence_benchmark.py",
)


@dataclass(frozen=True)
class PreparedRegion:
    region_id: str
    frame: pd.DataFrame
    sequence: Any
    neighbors: list[list[int]]
    observed_probability_by_year: dict[int, torch.Tensor]


def _resolve_precommit_artifact(row: dict[str, Any]) -> Path:
    if row.get("path_scope") == "benchmark_relative":
        path = V0_ROOT / row["path"]
    else:
        path = REPO_ROOT / row["path"]
    if (
        not path.is_file()
        or path.stat().st_size != int(row["size_bytes"])
        or sha256_file(path) != row["sha256"]
    ):
        raise ValueError(f"frozen_twm_artifact_mismatch:{path}")
    return path


def _verify_precommit(precommit: dict[str, Any]) -> None:
    if precommit["status"] != "candidate_and_predictions_sealed_before_2026_labels":
        raise ValueError("twm_precommit_status_is_not_sealed")
    if precommit["candidate"]["labels_2021_2025_used_for_training_or_selection"]:
        raise ValueError("frozen_twm_candidate_used_post_training_labels")
    if sorted(int(row["seed"]) for row in precommit["members"]) != list(
        TRAINING_SEEDS
    ):
        raise ValueError("frozen_twm_seed_set_mismatch")
    for row in precommit["artifacts"]["source"]:
        _resolve_precommit_artifact(row)
    for member in precommit["members"]:
        if sorted(int(row["fold_index"]) for row in member["folds"]) != list(
            FOLD_INDEXES
        ):
            raise ValueError("frozen_twm_fold_set_mismatch")
        for fold in member["folds"]:
            _resolve_precommit_artifact(fold["weights"])
            _resolve_precommit_artifact(fold["selection_trials"])


def _adapt_frame(region: pd.DataFrame) -> pd.DataFrame:
    """Construct the frozen model's static graph state at the 2022 origin.

    The trained sequence builder names its four static history slots 2017-2020.
    V3 maps the latest four observed years 2019-2022 into those slots solely to
    build the origin graph and descriptor. Recursive temporal context still uses
    the full real 2017-2022 probability history and real 2022-2024 clock years.
    """

    frame = region.sort_values("node_id", kind="mergesort").reset_index(drop=True)
    adapted = frame.copy()
    for pseudo_year, actual_year in zip(
        (2017, 2018, 2019, 2020), (2019, 2020, 2021, 2022)
    ):
        adapted[f"land_class_{pseudo_year}"] = frame[
            f"land_class_{actual_year}"
        ]
    nightlight = frame["viirs_nightlight_mean_2017_2022"].to_numpy(
        dtype=np.float32
    )
    for year in range(2016, 2021):
        adapted[f"viirs_nightlight_{year}"] = nightlight
    return adapted


def _prepare_regions(inputs: pd.DataFrame, edges: pd.DataFrame) -> list[PreparedRegion]:
    prepared = []
    for region_id, region in inputs.groupby("region_id", sort=True):
        frame = _adapt_frame(region)
        region_edges = edges[edges["region_id"] == region_id]
        sequence = _build_region_sequence(
            frame=frame,
            region_edges=region_edges,
            initial_year=2020,
            target_years=(2021,),
            future_class_by_year=None,
        )
        neighbors = _neighbor_indices(
            node_ids=frame["node_id"].tolist(), region_edges=region_edges
        )
        original = region.sort_values("node_id", kind="mergesort").reset_index(
            drop=True
        )
        probability_by_year = {
            year: functional.one_hot(
                torch.tensor(
                    original[f"land_class_{year}"].to_numpy(dtype=np.int64),
                    dtype=torch.long,
                ),
                num_classes=CLASS_COUNT,
            ).float()
            for year in HISTORY_YEARS
        }
        prepared.append(
            PreparedRegion(
                region_id=region_id,
                frame=frame,
                sequence=sequence,
                neighbors=neighbors,
                observed_probability_by_year=probability_by_year,
            )
        )
    return prepared


def _roll_region(
    *,
    model: TWMLandTransitionModel,
    prepared: PreparedRegion,
    logit_offset: float,
    cap_rate: float,
) -> np.ndarray:
    probability_by_year = {
        year: probability.clone()
        for year, probability in prepared.observed_probability_by_year.items()
    }
    outputs = []
    model.eval()
    with torch.no_grad():
        for target_year in TARGET_YEARS:
            feature_year = target_year - 1
            batch = _recursive_batch(
                sequence=prepared.sequence,
                frame=prepared.frame,
                probability_by_year=probability_by_year,
                neighbors=prepared.neighbors,
                feature_year=feature_year,
            )
            result = model(batch)
            fine_count = int(prepared.sequence.metadata["fine_node_count"])
            updated = _rate_capped_update(
                current_probability=probability_by_year[feature_year],
                change_logit=result.change_logit[:fine_count],
                destination_logits=result.destination_logits[:fine_count],
                logit_offset=logit_offset,
                cap_rate=cap_rate,
                group_sizes=[fine_count],
            )
            probability_by_year[target_year] = updated
            outputs.append(updated)
    return torch.stack(outputs, dim=1).cpu().numpy().astype(np.float64)


def _prediction_frame(
    prepared_regions: list[PreparedRegion], probabilities: list[np.ndarray]
) -> pd.DataFrame:
    rows = []
    for prepared, region_probability in zip(prepared_regions, probabilities):
        node_ids = prepared.frame["node_id"].tolist()
        if region_probability.shape != (
            len(node_ids),
            len(TARGET_YEARS),
            CLASS_COUNT,
        ):
            raise ValueError("twm_v3_region_probability_shape_mismatch")
        for node_index, node_id in enumerate(node_ids):
            for year_index, target_year in enumerate(TARGET_YEARS):
                row = {
                    "region_id": prepared.region_id,
                    "node_id": node_id,
                    "target_year": target_year,
                }
                row.update(
                    {
                        column: float(region_probability[node_index, year_index, index])
                        for index, column in enumerate(PROBABILITY_COLUMNS)
                    }
                )
                rows.append(row)
    return pd.DataFrame(rows, columns=KEY_COLUMNS + PROBABILITY_COLUMNS)


def _predict_fold(
    *,
    prepared_regions: list[PreparedRegion],
    fold: dict[str, Any],
) -> pd.DataFrame:
    weights_path = _resolve_precommit_artifact(fold["weights"])
    model = TWMLandTransitionModel(
        _kernel_config(
            state_writeback_mode="categorical_mixture",
            context_dim=12,
            horizon=1,
        )
    )
    model.load_state_dict(
        torch.load(weights_path, map_location="cpu", weights_only=True)
    )
    probabilities = [
        _roll_region(
            model=model,
            prepared=prepared,
            logit_offset=float(fold["selected_logit_offset"]),
            cap_rate=float(fold["selected_cap_rate"]),
        )
        for prepared in prepared_regions
    ]
    return _prediction_frame(prepared_regions, probabilities)


def _mean_predictions(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        raise ValueError("at_least_one_twm_prediction_required")
    keys = frames[0][KEY_COLUMNS].reset_index(drop=True)
    if any(not frame[KEY_COLUMNS].reset_index(drop=True).equals(keys) for frame in frames[1:]):
        raise ValueError("twm_member_prediction_keys_mismatch")
    result = keys.copy()
    result[PROBABILITY_COLUMNS] = np.mean(
        np.stack(
            [
                frame[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
                for frame in frames
            ]
        ),
        axis=0,
    )
    return result


def _recorded_artifact(row: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_precommit_artifact(row)
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def run(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    started = time.perf_counter()
    protocol = load_json(PROTOCOL_PATH)
    firewall_before = enforce_label_firewall(protocol)
    bundle_manifest = load_json(BUNDLE_MANIFEST_PATH)
    contract, expected_keys = load_prediction_contract()
    inputs = pd.read_parquet(BUNDLE_ROOT / "observed_inputs.parquet")
    edges = pd.read_parquet(BUNDLE_ROOT / "observed_edges.parquet")
    precommit = load_json(PRECOMMIT_PATH)
    _verify_precommit(precommit)

    torch.set_num_threads(1)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    torch.use_deterministic_algorithms(True)

    output_root.mkdir(parents=True, exist_ok=True)
    environment_path = output_root / "runtime_environment.json"
    write_json_atomic(runtime_environment(), environment_path)
    prepared_regions = _prepare_regions(inputs, edges)

    member_frames = []
    member_artifacts = []
    model_members = []
    for member in sorted(precommit["members"], key=lambda row: int(row["seed"])):
        seed = int(member["seed"])
        fold_frames = []
        for fold in sorted(member["folds"], key=lambda row: int(row["fold_index"])):
            fold_frames.append(
                validate_submission(
                    _predict_fold(
                        prepared_regions=prepared_regions,
                        fold=fold,
                    ),
                    contract=contract,
                    expected_keys=expected_keys,
                )
            )
            print(
                f"twm seed={seed} fold={int(fold['fold_index'])} complete",
                flush=True,
            )
        member_frame = validate_submission(
            _mean_predictions(fold_frames),
            contract=contract,
            expected_keys=expected_keys,
        )
        member_path = output_root / "members" / f"seed_{seed}" / "prediction.parquet"
        write_parquet_atomic(member_frame, member_path)
        member_frames.append(member_frame)
        member_artifact = artifact(
            member_path, role="twm_seed_equal_fold_ensemble_prediction"
        )
        member_artifacts.append({"seed": seed, "prediction": member_artifact})
        model_members.append(
            {
                "seed": seed,
                "fold_ensemble_weight": 1.0 / len(FOLD_INDEXES),
                "folds": [
                    {
                        "fold_index": int(fold["fold_index"]),
                        "weights": _recorded_artifact(fold["weights"]),
                        "selection_trials": _recorded_artifact(
                            fold["selection_trials"]
                        ),
                        "selected_logit_offset": float(
                            fold["selected_logit_offset"]
                        ),
                        "selected_cap_rate": float(
                            fold["selected_cap_rate"]
                        ),
                    }
                    for fold in sorted(
                        member["folds"], key=lambda row: int(row["fold_index"])
                    )
                ],
            }
        )
        print(
            f"twm seed={seed} member sha256={member_artifact['sha256']}",
            flush=True,
        )

    ensemble = validate_submission(
        _mean_predictions(member_frames),
        contract=contract,
        expected_keys=expected_keys,
    )
    prediction_path = output_root / "prediction.parquet"
    write_parquet_atomic(ensemble, prediction_path)

    source_dependencies = [
        artifact(path, role="frozen_twm_runtime_dependency")
        for path in SOURCE_DEPENDENCIES
    ]
    adapter_source = artifact(
        Path(__file__), role="v3_twm_runtime_r2_adapter_source"
    )
    model_spec = {
        "schema": "gwm_bench.v3_twm_dam_gk_candidate.v1",
        "model_id": "twm_dam_gk_candidate",
        "candidate_name": precommit["candidate"]["name"],
        "v2_candidate_fingerprint": precommit["candidate_fingerprint"],
        "v2_precommit_protocol_sha256": sha256_file(PRECOMMIT_PATH),
        "training": precommit["candidate"],
        "forecast_origin_year": 2022,
        "target_years": list(TARGET_YEARS),
        "rollout": "three_step_open_loop_with_predicted_probability_writeback",
        "geographic_transfer_ensemble": {
            "reason": "new V3 regions have no natural development fold assignment",
            "seed_weight": 1.0 / len(TRAINING_SEEDS),
            "fold_weight_within_seed": 1.0 / len(FOLD_INDEXES),
            "member_count": len(TRAINING_SEEDS) * len(FOLD_INDEXES),
            "selection_on_v3_targets": False,
        },
        "v3_adapter": {
            "full_observed_land_history_for_dynamic_context": list(HISTORY_YEARS),
            "origin_static_state_year": 2022,
            "origin_static_history_slots": {
                "trained_slot_2017": 2019,
                "trained_slot_2018": 2020,
                "trained_slot_2019": 2021,
                "trained_slot_2020": 2022,
            },
            "nightlight_policy": "repeat the Phase A 2017-2022 mean as a fixed level; lag change equals zero",
            "clock_policy": "use real feature years 2022, 2023 and 2024",
            "weights_retrained": False,
            "thresholds_or_caps_reselected": False,
            "target_pixels_read": False,
        },
        "members": model_members,
        "implementation_sources": [adapter_source, *source_dependencies],
    }
    model_spec_path = output_root / "model_spec.json"
    write_json_atomic(model_spec, model_spec_path)

    firewall_after = enforce_label_firewall(protocol)
    prediction_artifact = artifact(
        prediction_path, role="sealed_v3_twm_probability_prediction"
    )
    model_spec_artifact = artifact(
        model_spec_path, role="frozen_v3_twm_model_and_adapter_spec"
    )
    environment_artifact = artifact(
        environment_path, role="runtime_environment_descriptor"
    )
    report = {
        "schema": "gwm_bench.runtime_r2_prediction_run.v1",
        "suite_id": protocol["suite_id"],
        "model_group": "twm_dam_gk_candidate",
        "status": "PREDICTION_COMPLETE_LABEL_FIREWALL_INTACT_REPLAY_PENDING",
        "created_at": utc_now(),
        "lifecycle": {
            "prepare": "complete",
            "predict": "complete",
            "writeback": "predicted_probability_state_only",
            "audit": "complete",
        },
        "label_firewall": {
            "before": firewall_before,
            "after": firewall_after,
            "target_pixels_read": False,
        },
        "contract": {
            "submission_contract_sha256": sha256_file(
                SUBMISSION_CONTRACT_PATH
            ),
            "protocol_sha256": sha256_file(PROTOCOL_PATH),
            "phase_a_bundle_fingerprint": bundle_manifest[
                "bundle_fingerprint"
            ],
            "submission_keys_sha256": bundle_manifest["artifacts"][
                "submission_keys.parquet"
            ]["sha256"],
        },
        "hashes": {
            "protocol": sha256_file(PROTOCOL_PATH),
            "phase_a_bundle": bundle_manifest["bundle_fingerprint"],
            "runtime_environment": environment_artifact["sha256"],
            "adapter_source": adapter_source["sha256"],
            "model_or_binary": model_spec_artifact["sha256"],
            "random_seed_or_seed_set": fingerprint(
                {
                    "training_seeds": list(TRAINING_SEEDS),
                    "fold_indexes": list(FOLD_INDEXES),
                    "ensemble": "equal_seed_equal_fold",
                }
            ),
            "prediction": prediction_artifact["sha256"],
        },
        "artifacts": {
            "prediction": prediction_artifact,
            "member_predictions": member_artifacts,
            "model_spec": model_spec_artifact,
            "adapter_source": adapter_source,
            "runtime_environment": environment_artifact,
            "frozen_v2_precommit": artifact(
                PRECOMMIT_PATH, role="frozen_twm_v2_candidate_precommit"
            ),
        },
        "prediction_summary": prediction_summary(ensemble, inputs),
        "resource_usage": {
            "wall_time_seconds": time.perf_counter() - started,
            "peak_memory_bytes": peak_memory_bytes(),
            "temporary_bytes": sum(
                row["prediction"]["size_bytes"] for row in member_artifacts
            ),
            "exit_status": 0,
        },
        "replay": {
            "stochastic_training_member_count": len(TRAINING_SEEDS),
            "all_seed_members_materialized": True,
            "required": True,
            "verified": False,
        },
        "claim_boundary": {
            "real_action_effect_supported": False,
            "operational_forecast_supported": False,
            "cross_domain_transfer_supported": False,
            "quality_claimed_before_labels": False,
        },
    }
    report_path = output_root / "run_report.json"
    write_json_atomic(report, report_path)
    print(
        f"twm ensemble: rows={len(ensemble)} sha256={prediction_artifact['sha256']}",
        flush=True,
    )
    print(f"report: {report_path}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    run(args.output_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
