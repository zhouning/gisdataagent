#!/usr/bin/env python3
"""Run the single formal V3 scoring event for all committed predictions."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from prediction_runtime import (
    DRAFT_ROOT,
    PROTOCOL_PATH,
    REPO_ROOT,
    artifact,
    fingerprint,
    load_json,
    sha256_file,
    utc_now,
    write_json_atomic,
)


if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.gwm_bench_foundation_v3_0_draft.observed_o3_evaluator import (
    evaluate,
)


PREDICTION_ROOT = DRAFT_ROOT / "predictions"
COMMITMENT_PATH = PREDICTION_ROOT / "prediction_commitment.json"
TARGET_REGISTRY_PATH = DRAFT_ROOT / "phase_c_targets/target_registry.json"
TARGET_REPORT_PATH = DRAFT_ROOT / "phase_c_targets/target_registration_report.json"
LABELS_PATH = DRAFT_ROOT / "phase_c_targets/observed_targets.parquet"
RUNTIME_SEAL_PATH = DRAFT_ROOT / "runtime_r2_evaluator_seal.json"
EVALUATOR_PATH = DRAFT_ROOT / "observed_o3_evaluator.py"
REGION_PATH = DRAFT_ROOT / "lockbox_regions.json"
OUTPUT_ROOT = DRAFT_ROOT / "final_results"
FINAL_RESULTS_PATH = OUTPUT_ROOT / "final_results.json"
FINAL_MARKDOWN_PATH = OUTPUT_ROOT / "FINAL_REPORT_ZH.md"
MODEL_ORDER = (
    "twm_dam_gk_candidate",
    "geosos_flus_three_seed_ensemble",
    "state_persistence",
    "nonspatial_history_only",
    "fixed_adjacency_spatial",
)
MODEL_NAMES = {
    "twm_dam_gk_candidate": "TWM / DAM-GK",
    "geosos_flus_three_seed_ensemble": "GeoSOS FLUS（三种子）",
    "state_persistence": "状态不变",
    "nonspatial_history_only": "非空间历史",
    "fixed_adjacency_spatial": "固定邻接空间",
}
BOOTSTRAP_DRAWS = 20000
BOOTSTRAP_SEED = 20260723


def _paired_region_bootstrap(
    twm: dict[str, Any], flus: dict[str, Any]
) -> dict[str, Any]:
    def region_scores(report: dict[str, Any]) -> pd.Series:
        frame = pd.DataFrame(report["metrics_by_region_horizon"])
        return frame.groupby("region_id", sort=True)["change_f1"].mean()

    twm_scores = region_scores(twm)
    flus_scores = region_scores(flus)
    if not twm_scores.index.equals(flus_scores.index) or len(twm_scores) != 20:
        raise ValueError("twm_flus_region_bootstrap_keys_mismatch")
    differences = (twm_scores - flus_scores).to_numpy(dtype=np.float64)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    samples = rng.integers(0, len(differences), size=(BOOTSTRAP_DRAWS, len(differences)))
    draws = differences[samples].mean(axis=1)
    lower, upper = np.quantile(draws, [0.025, 0.975])
    if lower > 0.0:
        conclusion = "TWM_HIGHER_CI_EXCLUDES_ZERO"
    elif upper < 0.0:
        conclusion = "FLUS_HIGHER_CI_EXCLUDES_ZERO"
    else:
        conclusion = "NO_CLEAR_DIFFERENCE_CI_INCLUDES_ZERO"
    return {
        "comparison": "TWM minus FLUS mean region-level horizon-averaged change F1",
        "region_count": len(differences),
        "draw_count": BOOTSTRAP_DRAWS,
        "seed": BOOTSTRAP_SEED,
        "point_difference": float(differences.mean()),
        "confidence_interval_95_percentile": [float(lower), float(upper)],
        "bootstrap_probability_twm_exceeds_flus": float(np.mean(draws > 0.0)),
        "bootstrap_probability_flus_exceeds_twm": float(np.mean(draws < 0.0)),
        "conclusion": conclusion,
        "region_differences": {
            region_id: float(value)
            for region_id, value in zip(twm_scores.index, differences)
        },
    }


def _stratum_metrics(
    reports: dict[str, dict[str, Any]], region_manifest: dict[str, Any]
) -> dict[str, Any]:
    stratum_by_region = {
        row["region_id"]: row["stratum_id"] for row in region_manifest["regions"]
    }
    output = {}
    for model_id, report in reports.items():
        frame = pd.DataFrame(report["metrics_by_region_horizon"])
        frame["stratum_id"] = frame["region_id"].map(stratum_by_region)
        if frame["stratum_id"].isna().any():
            raise ValueError("missing_geographic_stratum_for_scored_region")
        output[model_id] = [
            {
                "stratum_id": stratum_id,
                "region_horizon_count": len(group),
                "mean_change_f1": float(group["change_f1"].mean()),
                "mean_overall_class_macro_f1": float(
                    group["overall_class_macro_f1"].mean()
                ),
                "mean_multiclass_brier_score": float(
                    group["multiclass_brier_score"].mean()
                ),
            }
            for stratum_id, group in frame.groupby("stratum_id", sort=True)
        ]
    return output


def _summary_rows(reports: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for model_id in MODEL_ORDER:
        report = reports[model_id]
        secondary = report["overall_secondary_metrics"]
        rows.append(
            {
                "model_id": model_id,
                "model_name": MODEL_NAMES[model_id],
                "primary_change_f1": report["primary_metric"]["value"],
                "overall_change_f1": secondary["change_f1"],
                "changed_destination_macro_f1": secondary[
                    "changed_destination_macro_f1"
                ],
                "overall_class_macro_f1": secondary["overall_class_macro_f1"],
                "multiclass_brier_score": secondary["multiclass_brier_score"],
                "predicted_to_observed_change_ratio": secondary[
                    "predicted_to_observed_change_ratio"
                ],
                "predicted_changed_count": secondary["predicted_changed_count"],
                "observed_changed_count": secondary["observed_changed_count"],
            }
        )
    return rows


def _markdown(final: dict[str, Any]) -> str:
    rows = final["summary"]
    lines = [
        "# GWM Benchmark V3.0 最终结果",
        "",
        f"状态：`{final['status']}`",
        "",
        "## 结论",
        "",
        final["plain_language_conclusion"],
        "",
        "## 五模型最终对比",
        "",
        "| 模型 | 主指标：地区×年份变化F1 | 整体变化F1 | 类别Macro-F1 | Brier（越低越好） | 预测/真实变化比 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        ratio = row["predicted_to_observed_change_ratio"]
        lines.append(
            "| {model_name} | {primary_change_f1:.4f} | {overall_change_f1:.4f} | "
            "{overall_class_macro_f1:.4f} | {multiclass_brier_score:.4f} | {ratio} |".format(
                **row,
                ratio="—" if ratio is None else f"{ratio:.4f}",
            )
        )
    bootstrap = final["twm_vs_flus_paired_region_bootstrap"]
    lines.extend(
        [
            "",
            "## TWM 与 FLUS",
            "",
            f"- TWM减FLUS的主指标差：`{bootstrap['point_difference']:.4f}`；",
            f"- 95%配对bootstrap区间：`[{bootstrap['confidence_interval_95_percentile'][0]:.4f}, {bootstrap['confidence_interval_95_percentile'][1]:.4f}]`；",
            f"- 结论：`{bootstrap['conclusion']}`。",
            "",
            "## 数据充分性",
            "",
            f"- 三年逐步真实变化：{final['data_sufficiency']['total_observed_step_changes']} 个；",
            f"- 有真实变化的地区：{final['data_sufficiency']['regions_with_observed_change']} / 20；",
            f"- 模型比较是否充分：`{str(final['data_sufficiency']['comparison_is_sufficient']).lower()}`。",
            "",
            "## 证据边界",
            "",
            "该结果只支持 Dynamic World 土地状态任务上的流程封存新地域迁移评测，不证明真实政策因果效应、业务级预测、跨领域迁移或一般 GWM 有效性。",
            "",
        ]
    )
    return "\n".join(lines)


def score() -> dict[str, Any]:
    protocol = load_json(PROTOCOL_PATH)
    commitment = load_json(COMMITMENT_PATH)
    target_registry = load_json(TARGET_REGISTRY_PATH)
    target_report = load_json(TARGET_REPORT_PATH)
    runtime_seal = load_json(RUNTIME_SEAL_PATH)
    if target_report["status"] != "PASS_PHASE_C_TARGETS_REGISTERED_SCORING_ALLOWED":
        raise ValueError("phase_c_targets_not_registered_for_scoring")
    if target_registry["prediction_commitment_preceded_target_access"] is not True:
        raise ValueError("prediction_commitment_did_not_precede_target_access")
    if runtime_seal["artifacts"]["observed_o3_evaluator.py"]["sha256"] != sha256_file(
        EVALUATOR_PATH
    ):
        raise ValueError("sealed_evaluator_hash_mismatch")
    if commitment["commitment_fingerprint"] != target_registry[
        "registry_identity"
    ]["prediction_commitment_fingerprint"]:
        raise ValueError("target_registry_commitment_fingerprint_mismatch")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    reports = {}
    evaluation_artifacts = {}
    for model_id in MODEL_ORDER:
        prediction_path = REPO_ROOT / commitment["models"][model_id]["prediction"][
            "path"
        ]
        if sha256_file(prediction_path) != commitment["models"][model_id][
            "prediction"
        ]["sha256"]:
            raise ValueError(f"committed_prediction_changed_before_scoring:{model_id}")
        report = evaluate(
            submission_path=prediction_path,
            labels_path=LABELS_PATH,
        )
        report["model_id"] = model_id
        report["model_name"] = MODEL_NAMES[model_id]
        output_path = OUTPUT_ROOT / f"{model_id}_evaluation.json"
        write_json_atomic(report, output_path)
        reports[model_id] = report
        evaluation_artifacts[model_id] = artifact(
            output_path, role="sealed_observed_o3_model_evaluation"
        )

    summary = _summary_rows(reports)
    summary_sorted = sorted(
        summary, key=lambda row: row["primary_change_f1"], reverse=True
    )
    bootstrap = _paired_region_bootstrap(
        reports["twm_dam_gk_candidate"],
        reports["geosos_flus_three_seed_ensemble"],
    )
    target_counts = target_registry["counts"]
    sufficient = (
        target_counts["total_step_change_count"]
        >= protocol["benchmark_completion_rule"][
            "minimum_observed_change_count_for_model_comparison"
        ]
        and target_counts["regions_with_at_least_one_change"]
        >= protocol["benchmark_completion_rule"][
            "minimum_regions_with_observed_change_for_model_comparison"
        ]
    )
    status = (
        "V3_FINAL_COMPLETED_MODEL_COMPARISON_VALID"
        if sufficient
        else "V3_FINAL_COMPLETED_MODEL_COMPARISON_INCONCLUSIVE"
    )
    twm_primary = reports["twm_dam_gk_candidate"]["primary_metric"]["value"]
    flus_primary = reports["geosos_flus_three_seed_ensemble"]["primary_metric"][
        "value"
    ]
    if bootstrap["conclusion"] == "TWM_HIGHER_CI_EXCLUDES_ZERO":
        comparison_text = "TWM 的变化识别显著高于 FLUS。"
    elif bootstrap["conclusion"] == "FLUS_HIGHER_CI_EXCLUDES_ZERO":
        comparison_text = "FLUS 的变化识别显著高于 TWM。"
    else:
        comparison_text = "TWM 与 FLUS 的变化识别差异没有达到清晰的配对区间结论。"
    plain = (
        f"V3 已完成。TWM 主指标为 {twm_primary:.4f}，FLUS 为 {flus_primary:.4f}。"
        f"{comparison_text}最高主指标模型是 {summary_sorted[0]['model_name']}，但这不是综合总分，也不改变所有结果必须发布的规则。"
    )

    final_identity = {
        "suite_id": protocol["suite_id"],
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "prediction_commitment_fingerprint": commitment[
            "commitment_fingerprint"
        ],
        "target_dataset_fingerprint": target_registry[
            "target_dataset_fingerprint"
        ],
        "runtime_r2_evaluator_seal_fingerprint": runtime_seal[
            "seal_fingerprint"
        ],
        "evaluator_sha256": sha256_file(EVALUATOR_PATH),
        "evaluation_sha256": {
            model_id: row["sha256"]
            for model_id, row in evaluation_artifacts.items()
        },
        "summary": summary,
        "bootstrap": bootstrap,
    }
    final = {
        "schema": "gwm_bench.foundation_v3_final_results.v1",
        "suite_id": protocol["suite_id"],
        "status": status,
        "scored_at": utc_now(),
        "formal_scoring_event_count": 1,
        "final_identity": final_identity,
        "final_results_fingerprint": fingerprint(final_identity),
        "plain_language_conclusion": plain,
        "summary": summary,
        "ranking_by_primary_metric_only": [
            {
                "rank": rank,
                "model_id": row["model_id"],
                "model_name": row["model_name"],
                "primary_change_f1": row["primary_change_f1"],
            }
            for rank, row in enumerate(summary_sorted, start=1)
        ],
        "twm_vs_flus_paired_region_bootstrap": bootstrap,
        "metrics_by_geographic_stratum": _stratum_metrics(
            reports, load_json(REGION_PATH)
        ),
        "data_sufficiency": {
            "total_observed_step_changes": target_counts[
                "total_step_change_count"
            ],
            "minimum_required_step_changes": protocol[
                "benchmark_completion_rule"
            ]["minimum_observed_change_count_for_model_comparison"],
            "regions_with_observed_change": target_counts[
                "regions_with_at_least_one_change"
            ],
            "minimum_required_regions_with_change": protocol[
                "benchmark_completion_rule"
            ]["minimum_regions_with_observed_change_for_model_comparison"],
            "comparison_is_sufficient": sufficient,
        },
        "artifacts": {
            "prediction_commitment": artifact(
                COMMITMENT_PATH, role="pre_target_prediction_commitment"
            ),
            "target_registry": artifact(
                TARGET_REGISTRY_PATH, role="registered_phase_c_targets"
            ),
            "labels": artifact(LABELS_PATH, role="registered_observed_o3_labels"),
            "evaluator": artifact(EVALUATOR_PATH, role="sealed_reference_evaluator"),
            "model_evaluations": evaluation_artifacts,
        },
        "publication": {
            "all_five_models_published": True,
            "negative_results_retained": True,
            "single_composite_score": False,
            "model_win_required_for_benchmark_completion": False,
        },
        "claim_boundary": protocol["claim_boundary"],
    }
    write_json_atomic(final, FINAL_RESULTS_PATH)
    FINAL_MARKDOWN_PATH.write_text(_markdown(final), encoding="utf-8")
    print(status)
    print(plain)
    print(f"final_results_fingerprint: {final['final_results_fingerprint']}")
    print(f"results: {FINAL_RESULTS_PATH}")
    print(f"report: {FINAL_MARKDOWN_PATH}")
    return final


if __name__ == "__main__":
    score()
