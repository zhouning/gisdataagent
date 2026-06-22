#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.territory_world_model import (  # noqa: E402
    TerritoryWorldModelAction,
    TerritoryWorldModelService,
    TwmEvidenceItem,
    TwmRepository,
    TwmReviewTask,
    TwmRuleHit,
    TwmStateObject,
    TwmStateRelation,
    TwmStateVersion,
    evidence_checksum,
)
from data_agent.territory_world_model.utils import safe_float  # noqa: E402
from scripts.run_twm_synthetic_experiment import (  # noqa: E402
    candidate_report_with_rollout_aliases,
    dataset_summary,
    summarize_backend_report,
    summarize_evaluation_report,
    summarize_fit_report,
    summarize_objective_report,
    summarize_report,
)

DEFAULT_INPUT = Path("/Users/zhouning/Downloads/1TutorialData_DongGuan_80m.zip")
DEFAULT_OUTPUT = REPO_ROOT / "docs/reports/twm_dongguan_geosos_validation_2026-06-22.json"

CLAIM_BOUNDARY = "geosos_dongguan_tutorial_benchmark_not_production_twm"
DYNAMICS_LOSS_CONTRACT = {
    "transition_loss": "targets.future_latent_state.observed_next",
    "constraint_loss": "targets.constraint_violation_probability",
    "planning_ranking_loss": "labels.ranking_score",
    "calibration_loss": "targets.calibration.observed_transition_proxy",
    "uncertainty_calibration_loss": "targets.uncertainty.confidence",
    "evidence_consistency_loss": "evidence_gate.status",
    "action_mask_loss": "targets.action_mask.allowed",
}
READINESS_THRESHOLDS = {
    "min_total_examples": 6,
    "min_usable_examples": 6,
    "min_observed_temporal_examples": 4,
    "min_holdout_examples": 2,
    "max_scaffold_ratio": 0.0,
    "max_review_ratio": 0.0,
    "require_geofm_pass": False,
    "require_causal_pass": False,
}
EVALUATION_THRESHOLDS = {
    "min_ground_truth_examples": 2,
    "max_mean_transition_error": 0.35,
    "max_mean_constraint_error": 0.35,
    "max_mean_utility_error": 0.35,
    "min_ranking_correlation_proxy": -1.0,
}
GEOFM_NOT_REQUIRED = {
    "gate_status": "not_required",
    "decision": "not_required_for_geosos_tutorial_benchmark",
}
CAUSAL_NOT_REQUIRED = {
    "status": "not_required",
    "method": "not_required_for_geosos_tutorial_benchmark",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TWM comparison validation on the GeoSOS DongGuan 80m tutorial zip.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-stride", type=int, default=24)
    parser.add_argument("--max-examples-per-transition", type=int, default=96)
    args = parser.parse_args()

    report = run_dongguan_geosos_validation(
        args.input,
        sample_stride=max(1, args.sample_stride),
        max_examples_per_transition=max(1, args.max_examples_per_transition),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output)}, ensure_ascii=False))


def run_dongguan_geosos_validation(
    zip_path: Path,
    *,
    sample_stride: int = 24,
    max_examples_per_transition: int = 96,
) -> dict[str, Any]:
    zip_path = Path(zip_path).expanduser()
    if not zip_path.exists():
        raise FileNotFoundError(str(zip_path))
    with tempfile.TemporaryDirectory(prefix="twm_dongguan_geosos_") as tmp:
        root = extract_zip(zip_path, Path(tmp))
        landuse_info = parse_landuse_info(root / "Config Files" / "DefaultLanduseInfo.xml")
        suitability = parse_suitability_matrix(root / "Config Files" / "SuitableMatrix.xml", landuse_info)
        rasters = load_landuse_rasters(root)
        transitions = build_transition_summaries(rasters, landuse_info)
        dataset_rows = sample_transition_rows(
            rasters,
            transitions,
            landuse_info,
            suitability,
            sample_stride=sample_stride,
            max_examples_per_transition=max_examples_per_transition,
        )
        svc = TerritoryWorldModelService(repository=TwmRepository(engine=None, persist_to_db=False))
        state_id = create_geosos_state(
            svc,
            zip_path=zip_path,
            landuse_info=landuse_info,
            transitions=transitions,
            dataset_rows=dataset_rows,
            raster_profile=raster_profile(rasters),
        )
        state = svc.repository.get_state_version(state_id)
        if state is None:
            raise LookupError(f"state not found: {state_id}")
        dataset = rows_to_dynamics_dataset(
            dataset_rows,
            state_id=state_id,
            project_id=state.project_id,
            source_path=zip_path,
            transitions=transitions,
            raster_profile=raster_profile(rasters),
        )
        payload = {
            "dataset": dataset,
            "thresholds": dict(READINESS_THRESHOLDS),
            "evaluation_thresholds": dict(EVALUATION_THRESHOLDS),
            "geofm_gate_report": dict(GEOFM_NOT_REQUIRED),
            "causal_calibration_report": dict(CAUSAL_NOT_REQUIRED),
            "candidate": {
                "model_name": "geosos_transition_group_baseline",
                "model_version": "dongguan_80m_v1",
                "model_family": "action_conditioned_landuse_transition_baseline",
                "uses_geofm": False,
                "uses_causal_calibration": False,
                "metadata": {"claim_boundary": CLAIM_BOUNDARY},
            },
        }
        readiness = svc.dynamics_readiness_report(state_id, payload)
        fit_report = svc.fit_dynamics_candidate(state_id, payload)
        fit_report_for_consumers = candidate_report_with_rollout_aliases(fit_report, dataset, horizon=2)
        evaluation = svc.dynamics_evaluation_report(
            state_id,
            {
                **payload,
                "candidate": fit_report.get("candidate") or {},
                "predictions": fit_report.get("predictions") or {},
            },
        )
        backend = svc.dynamics_backend_report(
            state_id,
            {
                **payload,
                "backend": {
                    "backend_id": "geosos_transition_group_baseline",
                    "backend_type": "transparent_benchmark_baseline",
                    "model_name": "geosos_transition_group_baseline",
                    "model_version": "dongguan_80m_v1",
                    "model_family": "landuse_transition_group_means",
                    "trainable": False,
                    "action_conditioned": True,
                    "uses_geofm": False,
                    "uses_causal_calibration": False,
                    "is_scaffold_baseline": False,
                    "metadata": {"claim_boundary": CLAIM_BOUNDARY},
                },
                "candidate_report": fit_report_for_consumers,
            },
        )
        objective = svc.training_objective_report(
            state_id,
            {
                **payload,
                "dynamics_backend_report": backend,
                "predictions": fit_report.get("predictions") or {},
            },
        )
        status = report_status(readiness, fit_report, evaluation, backend)
        return {
            "schema": "territory_world_model.dongguan_geosos_validation_report.v1",
            "status": status,
            "claim_boundary": CLAIM_BOUNDARY,
            "source": {
                "zip_path": str(zip_path),
                "dataset": "GeoSOS DongGuan 80m tutorial data",
                "task": "land-use transition benchmark adapter for TWM comparison validation",
            },
            "data_profile": {
                "raster_profile": raster_profile(rasters),
                "landuse_types": landuse_info,
                "suitability_matrix": suitability,
                "transition_summaries": transitions,
                "sample_stride": sample_stride,
                "max_examples_per_transition": max_examples_per_transition,
            },
            "state": {
                "state_version_id": state_id,
                "project_id": state.project_id,
                "object_count": state.object_count,
                "relation_count": state.relation_count,
                "summary": state.summary,
            },
            "dataset_summary": dataset_summary(dataset),
            "readiness": summarize_report(readiness),
            "fit": summarize_fit_report(fit_report),
            "evaluation": summarize_evaluation_report(evaluation),
            "backend": summarize_backend_report(backend),
            "objective": summarize_objective_report(objective),
            "comparison_interpretation": {
                "what_this_validates": [
                    "GeoSOS tutorial zip can be ingested into a TWM action-conditioned multi-head dynamics contract.",
                    "2000->2005 and 2005->2006 observed land-use transitions can be represented as ground-truth temporal examples.",
                    "The transparent transition-group baseline is now available as a named comparison baseline inside the TWM report chain.",
                ],
                "what_this_does_not_validate": [
                    "It does not prove TWM beats GeoSOS/FLUS pixel-level simulation.",
                    "It does not provide real approval actions, policy interventions, human review outcomes or causal treatment labels.",
                    "It does not upgrade TWM to production readiness for natural-resource governance.",
                ],
                "next_tasks": [
                    "Add a pixel/grid holdout metric against an actual GeoSOS/FLUS output map if such output is available.",
                    "Add a land-use CA or FLUS-compatible baseline runner for same-case comparison.",
                    "Attach real planning boundaries, approval records and review outcomes before making governance-action claims.",
                ],
            },
        }


def extract_zip(zip_path: Path, output_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(output_dir)
    candidates = [path for path in output_dir.iterdir() if path.is_dir()]
    if len(candidates) == 1:
        return candidates[0]
    return output_dir


def parse_landuse_info(path: Path) -> dict[str, Any]:
    tree = ElementTree.parse(path)
    root = tree.getroot()
    all_types: dict[int, dict[str, Any]] = {}
    for item in root.findall(".//AllTypes/StructLanduseInfo"):
        value = int(text_of(item, "LanduseTypeValue", "0"))
        all_types[value] = {
            "value": value,
            "zh": text_of(item, "LanduseTypeChsName", ""),
            "en": text_of(item, "LanduseTypeEnName", ""),
        }
    convert_values = {
        int(text_of(item, "LanduseTypeValue", "0"))
        for item in root.findall(".//ConvertValues/StructLanduseInfo")
    }
    urban_values = {
        int(text_of(item, "LanduseTypeValue", "0"))
        for item in root.findall(".//UrbanValues/StructLanduseInfo")
    }
    not_to_convert_values = {
        int(text_of(item, "LanduseTypeValue", "0"))
        for item in root.findall(".//NotToConvertValues/StructLanduseInfo")
    }
    null_value = int(text_of(root.find(".//NullValue") or root, "LanduseTypeValue", "-9999"))
    return {
        "schema": "territory_world_model.geosos_landuse_info.v1",
        "types": {str(key): value for key, value in sorted(all_types.items())},
        "convert_values": sorted(convert_values),
        "urban_values": sorted(urban_values),
        "not_to_convert_values": sorted(not_to_convert_values),
        "null_value": null_value,
    }


def parse_suitability_matrix(path: Path, landuse_info: dict[str, Any]) -> dict[str, Any]:
    type_names = [payload["zh"] for _, payload in sorted((int(k), v) for k, v in landuse_info["types"].items())]
    tree = ElementTree.parse(path)
    rows = []
    for source_idx, item in enumerate(tree.getroot().findall(".//Table1"), start=1):
        source_type = str(source_idx)
        allowed_targets: dict[str, bool] = {}
        for target_idx, name in enumerate(type_names, start=1):
            raw = text_of(item, name, "0")
            allowed_targets[str(target_idx)] = str(raw).strip() == "1"
        rows.append({"source_type": source_type, "allowed_targets": allowed_targets})
    return {
        "schema": "territory_world_model.geosos_suitability_matrix.v1",
        "rows": rows,
    }


def load_landuse_rasters(root: Path) -> dict[int, dict[str, Any]]:
    import numpy as np
    import rasterio

    rasters: dict[int, dict[str, Any]] = {}
    for year in (2000, 2005, 2006):
        path = root / "Landuse Data" / f"landuse{year}.tif"
        with rasterio.open(path) as src:
            data = src.read(1)
            rasters[year] = {
                "path": str(path),
                "data": np.asarray(data),
                "shape": tuple(data.shape),
                "crs": str(src.crs) if src.crs else "",
                "transform": tuple(src.transform),
                "nodata": src.nodata,
                "resolution": tuple(src.res),
                "bounds": tuple(src.bounds),
            }
    return rasters


def raster_profile(rasters: dict[int, dict[str, Any]]) -> dict[str, Any]:
    first = rasters[min(rasters)]
    res = tuple(first.get("resolution") or (80.0, 80.0))
    cell_area_m2 = abs(float(res[0]) * float(res[1]))
    return {
        "schema": "territory_world_model.geosos_raster_profile.v1",
        "years": sorted(rasters),
        "shape": list(first["shape"]),
        "crs": first.get("crs", ""),
        "resolution": list(res),
        "cell_area_m2": cell_area_m2,
        "cell_area_ha": round(cell_area_m2 / 10000.0, 6),
        "nodata": first.get("nodata"),
    }


def build_transition_summaries(rasters: dict[int, dict[str, Any]], landuse_info: dict[str, Any]) -> list[dict[str, Any]]:
    transitions = []
    for start, end in ((2000, 2005), (2005, 2006)):
        transitions.append(transition_summary(start, end, rasters[start], rasters[end], landuse_info))
    return transitions


def transition_summary(
    start_year: int,
    end_year: int,
    start_raster: dict[str, Any],
    end_raster: dict[str, Any],
    landuse_info: dict[str, Any],
) -> dict[str, Any]:
    import numpy as np

    start = start_raster["data"]
    end = end_raster["data"]
    nodata_values = {safe_int(start_raster.get("nodata")), safe_int(end_raster.get("nodata")), int(landuse_info.get("null_value", -9999))}
    valid = np.ones(start.shape, dtype=bool)
    for value in nodata_values:
        if value is not None:
            valid &= start != value
            valid &= end != value
    changed = valid & (start != end)
    cell_area_ha = raster_cell_area_ha(start_raster)
    pair_counts: Counter[tuple[int, int]] = Counter()
    for source, target in zip(start[changed].astype(int).tolist(), end[changed].astype(int).tolist()):
        pair_counts[(source, target)] += 1
    top_changes = [
        {
            "from": source,
            "to": target,
            "from_label": landuse_label(landuse_info, source),
            "to_label": landuse_label(landuse_info, target),
            "cell_count": count,
            "area_ha": round(count * cell_area_ha, 4),
        }
        for (source, target), count in pair_counts.most_common(12)
    ]
    return {
        "schema": "territory_world_model.geosos_transition_summary.v1",
        "start_year": start_year,
        "end_year": end_year,
        "valid_cell_count": int(valid.sum()),
        "changed_cell_count": int(changed.sum()),
        "unchanged_cell_count": int((valid & (start == end)).sum()),
        "changed_ratio": round(float(changed.sum()) / max(1, int(valid.sum())), 6),
        "changed_area_ha": round(float(changed.sum()) * cell_area_ha, 4),
        "top_changes": top_changes,
    }


def sample_transition_rows(
    rasters: dict[int, dict[str, Any]],
    transitions: list[dict[str, Any]],
    landuse_info: dict[str, Any],
    suitability: dict[str, Any],
    *,
    sample_stride: int,
    max_examples_per_transition: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for transition in transitions:
        start_year = int(transition["start_year"])
        end_year = int(transition["end_year"])
        start = rasters[start_year]["data"]
        end = rasters[end_year]["data"]
        nodata = safe_int(rasters[start_year].get("nodata"))
        samples = []
        for row_idx in range(0, start.shape[0], sample_stride):
            for col_idx in range(0, start.shape[1], sample_stride):
                source = int(start[row_idx, col_idx])
                target = int(end[row_idx, col_idx])
                if nodata is not None and (source == nodata or target == nodata):
                    continue
                if source == int(landuse_info.get("null_value", -9999)) or target == int(landuse_info.get("null_value", -9999)):
                    continue
                changed = source != target
                if not changed and len(samples) % 3 != 0:
                    continue
                samples.append((row_idx, col_idx, source, target, changed))
        changed_samples = [item for item in samples if item[4]]
        unchanged_samples = [item for item in samples if not item[4]]
        selected = (changed_samples[: max_examples_per_transition // 2] + unchanged_samples[: max_examples_per_transition // 2])
        if len(selected) < max_examples_per_transition:
            selected.extend(samples[: max_examples_per_transition - len(selected)])
        selected = selected[:max_examples_per_transition]
        for idx, (row_idx, col_idx, source, target, changed) in enumerate(selected):
            rows.append(
                transition_sample_row(
                    transition,
                    row_idx=row_idx,
                    col_idx=col_idx,
                    source=source,
                    target=target,
                    changed=changed,
                    idx=idx,
                    landuse_info=landuse_info,
                    suitability=suitability,
                )
            )
    return rows


def transition_sample_row(
    transition: dict[str, Any],
    *,
    row_idx: int,
    col_idx: int,
    source: int,
    target: int,
    changed: bool,
    idx: int,
    landuse_info: dict[str, Any],
    suitability: dict[str, Any],
) -> dict[str, Any]:
    start_year = int(transition["start_year"])
    end_year = int(transition["end_year"])
    split = "candidate" if end_year <= 2005 else "holdout"
    allowed = transition_allowed(suitability, source, target)
    urban_values = {int(value) for value in landuse_info.get("urban_values") or []}
    not_to_convert = {int(value) for value in landuse_info.get("not_to_convert_values") or []}
    if target in urban_values and source != target:
        action_type = "urban_expand"
    elif source in not_to_convert and source != target:
        action_type = "restricted_change"
    elif changed:
        action_type = "landuse_convert"
    else:
        action_type = "maintain"
    transition_share = 1.0 if changed else 0.0
    risk = 0.1
    if changed and not allowed:
        risk = 0.78
    elif changed and source in not_to_convert:
        risk = 0.62
    elif target in urban_values and changed:
        risk = 0.42
    elif changed:
        risk = 0.28
    utility = 0.25 if changed and target in urban_values else 0.12 if changed else 0.03
    if not allowed:
        utility -= 0.18
    confidence = 0.82 if changed else 0.74
    return {
        "id": f"dongguan:{start_year}:{end_year}:{idx}:{row_idx}:{col_idx}",
        "unit_id": f"cell-{row_idx}-{col_idx}",
        "project_id": f"DG-{start_year}-{end_year}-{row_idx}-{col_idx}",
        "split": split,
        "start_year": start_year,
        "end_year": end_year,
        "time_index": 0 if end_year <= 2005 else 1,
        "row": row_idx,
        "col": col_idx,
        "source_landuse": source,
        "target_landuse": target,
        "source_label": landuse_label(landuse_info, source),
        "target_label": landuse_label(landuse_info, target),
        "changed": changed,
        "action_type": action_type,
        "transition_allowed": allowed,
        "constraint_probability": round(risk, 6),
        "planning_utility_delta": round(utility, 6),
        "confidence": round(confidence, 6),
        "transition_share": transition_share,
        "ranking_score": round(utility - risk + confidence * 0.1, 6),
        "region_code": "DONGGUAN",
        "period": f"{start_year}-{end_year}",
    }


def rows_to_dynamics_dataset(
    rows: list[dict[str, Any]],
    *,
    state_id: str,
    project_id: str,
    source_path: Path,
    transitions: list[dict[str, Any]],
    raster_profile: dict[str, Any],
) -> dict[str, Any]:
    examples = [
        row_to_training_example(
            row,
            idx=idx,
            state_id=state_id,
            project_id=project_id,
            source_path=source_path,
            raster_profile=raster_profile,
        )
        for idx, row in enumerate(rows)
    ]
    examples.sort(key=lambda item: (item["split"], item["id"]))
    return {
        "schema": "territory_world_model.dynamics_training_dataset.v1",
        "state_version_id": state_id,
        "project_id": project_id,
        "examples": examples,
        "summary": dataset_summary_from_examples(examples, source_path=source_path, transitions=transitions),
    }


def row_to_training_example(
    row: dict[str, Any],
    *,
    idx: int,
    state_id: str,
    project_id: str,
    source_path: Path,
    raster_profile: dict[str, Any],
) -> dict[str, Any]:
    allowed = bool(row["transition_allowed"])
    confidence = float(row["confidence"])
    hard_blocks = [] if allowed else ["geosos_suitability_matrix_blocks_transition"]
    reviews = ["urban_expansion_review"] if row["action_type"] == "urban_expand" else []
    if row["action_type"] == "restricted_change":
        reviews.append("restricted_landuse_change_review")
    evidence_gate = {
        "passed": True,
        "status": "pass",
        "required": ["landuse_raster_pair", "default_landuse_info", "suitable_matrix"],
        "missing": [],
        "coverage": 1.0,
        "action_mask": {
            "allowed": allowed,
            "hard_blocks": hard_blocks,
            "required_reviews": reviews,
            "confidence": confidence,
            "target_object_count": 1,
            "related_rule_hit_count": 1 if not allowed or reviews else 0,
            "missing_evidence_hit_count": 0,
        },
    }
    observed_next = {
        "schema": "territory_world_model.geosos_observed_cell_transition.v1",
        "total_area_m2": float(raster_profile["cell_area_m2"]),
        "cell_area_m2": float(raster_profile["cell_area_m2"]),
        "source_landuse": int(row["source_landuse"]),
        "target_landuse": int(row["target_landuse"]),
        "changed": bool(row["changed"]),
        "transition_share": float(row["transition_share"]),
        "projected_risk_pressure": float(row["constraint_probability"]),
        "projected_utility_delta": float(row["planning_utility_delta"]),
    }
    return {
        "id": row["id"],
        "state_version_id": state_id,
        "project_id": project_id,
        "split": row["split"],
        "sample_type": "temporal_state_transition",
        "current_state_summary": {
            "schema": "territory_world_model.geosos_current_cell_state.v1",
            "region_code": row["region_code"],
            "period": row["period"],
            "time_index": row["time_index"],
            "cell": {"row": row["row"], "col": row["col"]},
            "source_landuse": row["source_landuse"],
            "source_label": row["source_label"],
            "raster_profile": raster_profile,
        },
        "action": TerritoryWorldModelAction(
            action_type=row["action_type"],
            target_role="landuse_cell",
            target_objects=[row["unit_id"]],
            spatial_scope={"grid": "dongguan_80m", "row": row["row"], "col": row["col"]},
            magnitude=1.0 if row["changed"] else 0.1,
            scenario="geosos_landuse_transition_benchmark",
            description=f"{row['start_year']}->{row['end_year']} {row['source_label']} to {row['target_label']}",
            legal_intent="landuse_transition_benchmark_not_policy_action",
            execution_mask=evidence_gate["action_mask"],
            parameters={
                "source_landuse": row["source_landuse"],
                "target_landuse": row["target_landuse"],
                "transition_allowed": row["transition_allowed"],
            },
            treatment="observed_landuse_transition",
        ).to_dict(),
        "scenario_context": {
            "scenario_id": "geosos_dongguan_80m",
            "region_code": row["region_code"],
            "period": row["period"],
            "time_index": row["time_index"],
            "start_year": row["start_year"],
            "end_year": row["end_year"],
            "claim_boundary": CLAIM_BOUNDARY,
        },
        "targets": {
            "future_latent_state": {"schema": "territory_world_model.geosos_future_latent_state.v1", "observed_next": observed_next},
            "constraint_violation_probability": row["constraint_probability"],
            "planning_utility_delta": row["planning_utility_delta"],
            "uncertainty": {"confidence": row["confidence"], "source": "observed_landuse_raster_pair"},
            "calibration": {
                "observed_transition_proxy": row["transition_share"],
                "calibrated_utility_delta": row["planning_utility_delta"],
                "source": "geosos_landuse_change",
            },
            "action_mask": evidence_gate["action_mask"],
        },
        "labels": {
            "constraint_label": "blocked_by_suitability" if not allowed else "allowed_by_suitability",
            "utility_label": "changed" if row["changed"] else "unchanged",
            "ranking_score": row["ranking_score"],
            "evidence_supported": True,
            "supervision_source": "state_snapshots",
            "ground_truth_grade": "geosos_tutorial_observed_landuse",
        },
        "losses": dict(DYNAMICS_LOSS_CONTRACT),
        "evidence_gate": evidence_gate,
        "provenance": {
            "state_version_id": state_id,
            "source_table": str(source_path),
            "source_path": str(source_path),
            "sample_index": idx,
            "sample_family": "geosos_dongguan_80m",
            "ground_truth": True,
            "synthetic": False,
            "not_for_production": True,
            "claim_boundary": CLAIM_BOUNDARY,
        },
        "not_for_training_reasons": [],
    }


def dataset_summary_from_examples(
    examples: list[dict[str, Any]],
    *,
    source_path: Path,
    transitions: list[dict[str, Any]],
) -> dict[str, Any]:
    split_counts = Counter(str(item.get("split") or "") for item in examples)
    action_counts = Counter(str((item.get("action") or {}).get("action_type") or "") for item in examples)
    blocked_count = sum(1 for item in examples if not ((item.get("targets") or {}).get("action_mask") or {}).get("allowed", True))
    return {
        "schema": "territory_world_model.geosos_dongguan_dynamics_dataset_summary.v1",
        "source_path": str(source_path),
        "example_count": len(examples),
        "candidate_example_count": split_counts.get("candidate", 0),
        "holdout_example_count": split_counts.get("holdout", 0),
        "observed_temporal_example_count": len(examples),
        "usable_example_count": len(examples),
        "synthetic_example_count": 0,
        "not_for_production_example_count": len(examples),
        "split_counts": dict(sorted(split_counts.items())),
        "action_counts": dict(sorted(action_counts.items())),
        "action_mask_blocked_count": blocked_count,
        "transition_summary_count": len(transitions),
        "loss_contract": dict(DYNAMICS_LOSS_CONTRACT),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def create_geosos_state(
    svc: TerritoryWorldModelService,
    *,
    zip_path: Path,
    landuse_info: dict[str, Any],
    transitions: list[dict[str, Any]],
    dataset_rows: list[dict[str, Any]],
    raster_profile: dict[str, Any],
) -> str:
    project = svc.create_project(
        {
            "name": "TWM GeoSOS DongGuan 80m Benchmark",
            "region_code": "DONGGUAN",
            "business_scenario": "landuse_transition_benchmark",
            "metadata": {"claim_boundary": CLAIM_BOUNDARY, "not_for_production": True},
        },
        username="geosos-runner",
    )
    object_counts = {
        "county": 1,
        "township": 1,
        "block": 4,
        "landuse_class": len(landuse_info.get("types") or {}),
        "transition_period": len(transitions),
        "parcel": len(dataset_rows),
    }
    relation_counts = {
        "county_contains_township": 1,
        "township_contains_block": 4,
        "county_contains_cell_sample": len(dataset_rows),
        "cell_sample_has_landuse_class": len(dataset_rows),
        "transition_period_observes_cell_sample": len(dataset_rows),
        "project_overlaps_planning_zone": len(dataset_rows),
        "annual_change_of_parcel": len(dataset_rows),
    }
    state = TwmStateVersion(
        project_id=project["id"],
        label="GeoSOS DongGuan 80m tutorial benchmark state",
        source_manifest={"geosos_zip": str(zip_path), "claim_boundary": CLAIM_BOUNDARY},
        object_count=sum(object_counts.values()),
        relation_count=sum(relation_counts.values()),
        quality_summary={
            "object_count": sum(object_counts.values()),
            "relation_count": sum(relation_counts.values()),
            "evidence_coverage": 1.0,
            "source_row_count": len(dataset_rows),
            "transition_count": len(transitions),
            "not_for_production": True,
            "claim_boundary": CLAIM_BOUNDARY,
        },
        build_status="ready",
        summary={
            "object_counts_by_role": object_counts,
            "relation_counts_by_type": relation_counts,
            "metric_crs": raster_profile.get("crs", ""),
            "raster_profile": raster_profile,
            "claim_boundary": CLAIM_BOUNDARY,
        },
        created_by="geosos-runner",
    )
    svc.repository.save_state_version(state)
    objects = build_state_objects(state.id, landuse_info, transitions, dataset_rows, zip_path)
    relations = build_state_relations(state.id, objects, dataset_rows)
    svc.repository.save_state_objects(objects)
    svc.repository.save_state_relations(relations)
    first_cell = next((obj for obj in objects if obj.canonical_role == "landuse_cell"), objects[0])
    hit = svc.repository.save_rule_hit(
        TwmRuleHit(
            state_version_id=state.id,
            rule_id="TWM-GEOSOS-DG-001",
            subject_object_id=first_cell.id,
            hit_status="reviewed_confirmed",
            severity="info",
            risk_score=0.1,
            metrics={"transition_count": len(transitions), "sample_count": len(dataset_rows)},
            explanation="GeoSOS DongGuan tutorial data adapted as a TWM comparison benchmark.",
        )
    )
    evidence_payload = {
        "state_version_id": state.id,
        "source_path": str(zip_path),
        "landuse_type_count": len(landuse_info.get("types") or {}),
        "transition_count": len(transitions),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    svc.repository.save_evidence_item(
        TwmEvidenceItem(
            rule_hit_id=hit.id,
            evidence_type="geosos_tutorial_source",
            source_system="GeoSOS tutorial zip",
            source_ref=str(zip_path),
            payload=evidence_payload,
            checksum=evidence_checksum(evidence_payload),
        )
    )
    svc.repository.save_review_task(
        TwmReviewTask(
            rule_hit_id=hit.id,
            assignee="geosos-runner",
            status="closed",
            decision="benchmark_only",
            comment="This data supports land-use transition benchmark validation, not production governance claims.",
        )
    )
    return state.id


def build_state_objects(
    state_id: str,
    landuse_info: dict[str, Any],
    transitions: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    zip_path: Path,
) -> list[TwmStateObject]:
    objects: list[TwmStateObject] = [
        TwmStateObject(
            state_version_id=state_id,
            object_type="admin_city",
            object_code="DONGGUAN",
            source_role="county",
            canonical_role="county",
            source_path=str(zip_path),
            attributes={"region_code": "DONGGUAN", "claim_boundary": CLAIM_BOUNDARY},
            semantic_tags=["geosos", "dongguan", "admin_boundary"],
            quality_score=1.0,
            synthetic=False,
            not_for_production=True,
        )
    ]
    objects.append(
        TwmStateObject(
            state_version_id=state_id,
            object_type="admin_township_proxy",
            object_code="DONGGUAN-TOWNSHIP-PROXY",
            source_role="township",
            canonical_role="township",
            source_path=str(zip_path),
            attributes={"region_code": "DONGGUAN", "proxy": "geosos_tutorial_grid_partition"},
            semantic_tags=["geosos", "dongguan", "township_proxy"],
            quality_score=0.7,
            synthetic=False,
            not_for_production=True,
        )
    )
    for block_idx in range(4):
        objects.append(
            TwmStateObject(
                state_version_id=state_id,
                object_type="grid_block_proxy",
                object_code=f"DONGGUAN-BLOCK-{block_idx}",
                source_role="block",
                canonical_role="block",
                source_path=str(zip_path),
                attributes={"region_code": "DONGGUAN", "block_index": block_idx, "proxy": "geosos_tutorial_grid_partition"},
                semantic_tags=["geosos", "dongguan", "block_proxy"],
                quality_score=0.7,
                synthetic=False,
                not_for_production=True,
            )
        )
    for key, payload in sorted((int(k), v) for k, v in landuse_info.get("types", {}).items()):
        objects.append(
            TwmStateObject(
                state_version_id=state_id,
                object_type="landuse_class",
                object_code=f"LU-{key}",
                source_role="landuse_class",
                canonical_role="landuse_class",
                source_path=str(zip_path),
                attributes=payload,
                semantic_tags=["geosos", "landuse_class"],
                quality_score=1.0,
                synthetic=False,
                not_for_production=True,
            )
        )
    for transition in transitions:
        objects.append(
            TwmStateObject(
                state_version_id=state_id,
                object_type="transition_period",
                object_code=f"TR-{transition['start_year']}-{transition['end_year']}",
                source_role="transition_period",
                canonical_role="transition_period",
                source_path=str(zip_path),
                attributes=transition,
                semantic_tags=["geosos", "transition_period"],
                quality_score=1.0,
                synthetic=False,
                not_for_production=True,
            )
        )
    for row in rows:
        objects.append(
            TwmStateObject(
                state_version_id=state_id,
                object_type="landuse_cell_sample",
                object_code=row["id"],
                source_role="parcel",
                source_feature_id=row["unit_id"],
                canonical_role="parcel",
                source_path=str(zip_path),
                attributes=row,
                semantic_tags=["geosos", "landuse_cell_sample", "parcel_proxy", row["action_type"]],
                quality_score=row["confidence"],
                synthetic=False,
                not_for_production=True,
            )
        )
    return objects


def build_state_relations(
    state_id: str,
    objects: list[TwmStateObject],
    rows: list[dict[str, Any]],
) -> list[TwmStateRelation]:
    by_code = {obj.object_code: obj for obj in objects}
    county = by_code["DONGGUAN"]
    township = by_code["DONGGUAN-TOWNSHIP-PROXY"]
    relations: list[TwmStateRelation] = []
    relations.append(
        TwmStateRelation(
            state_version_id=state_id,
            subject_object_id=county.id,
            predicate="contains",
            object_object_id=township.id,
            relation_type="county_contains_township",
            metrics={"proxy": "geosos_tutorial_grid_partition"},
            confidence=0.7,
            synthetic=False,
            not_for_production=True,
        )
    )
    for block_idx in range(4):
        block = by_code[f"DONGGUAN-BLOCK-{block_idx}"]
        relations.append(
            TwmStateRelation(
                state_version_id=state_id,
                subject_object_id=township.id,
                predicate="contains",
                object_object_id=block.id,
                relation_type="township_contains_block",
                metrics={"block_index": block_idx},
                confidence=0.7,
                synthetic=False,
                not_for_production=True,
            )
        )
    for row in rows:
        cell = by_code.get(row["id"])
        landuse = by_code.get(f"LU-{row['source_landuse']}")
        period = by_code.get(f"TR-{row['start_year']}-{row['end_year']}")
        block = by_code.get(f"DONGGUAN-BLOCK-{int(row['row']) % 4}")
        if cell:
            relations.append(
                TwmStateRelation(
                    state_version_id=state_id,
                    subject_object_id=county.id,
                    predicate="contains",
                    object_object_id=cell.id,
                    relation_type="county_contains_cell_sample",
                    metrics={"row": row["row"], "col": row["col"]},
                    confidence=1.0,
                    synthetic=False,
                    not_for_production=True,
                )
            )
        if cell and block:
            relations.append(
                TwmStateRelation(
                    state_version_id=state_id,
                    subject_object_id=cell.id,
                    predicate="overlaps",
                    object_object_id=block.id,
                    relation_type="project_overlaps_planning_zone",
                    metrics={"row": row["row"], "col": row["col"], "block_proxy": True},
                    confidence=0.7,
                    synthetic=False,
                    not_for_production=True,
                )
            )
        if cell and landuse:
            relations.append(
                TwmStateRelation(
                    state_version_id=state_id,
                    subject_object_id=cell.id,
                    predicate="has_source_landuse",
                    object_object_id=landuse.id,
                    relation_type="cell_sample_has_landuse_class",
                    metrics={"source_landuse": row["source_landuse"], "target_landuse": row["target_landuse"]},
                    confidence=1.0,
                    synthetic=False,
                    not_for_production=True,
                )
            )
        if period and cell:
            relations.append(
                TwmStateRelation(
                    state_version_id=state_id,
                    subject_object_id=period.id,
                    predicate="observes",
                    object_object_id=cell.id,
                    relation_type="transition_period_observes_cell_sample",
                    metrics={"changed": row["changed"], "transition_allowed": row["transition_allowed"]},
                    confidence=1.0,
                    synthetic=False,
                    not_for_production=True,
                )
            )
            relations.append(
                TwmStateRelation(
                    state_version_id=state_id,
                    subject_object_id=cell.id,
                    predicate="changes_in",
                    object_object_id=period.id,
                    relation_type="annual_change_of_parcel",
                    metrics={
                        "start_year": row["start_year"],
                        "end_year": row["end_year"],
                        "changed": row["changed"],
                        "source_landuse": row["source_landuse"],
                        "target_landuse": row["target_landuse"],
                    },
                    confidence=1.0,
                    synthetic=False,
                    not_for_production=True,
                )
            )
    return relations


def report_status(
    readiness: dict[str, Any],
    fit_report: dict[str, Any],
    evaluation: dict[str, Any],
    backend: dict[str, Any],
) -> str:
    if any(report.get("status") == "blocked" for report in (readiness, fit_report, evaluation, backend)):
        return "blocked"
    if readiness.get("status") == "pass" and evaluation.get("status") == "pass":
        return "pass"
    return "review"


def transition_allowed(suitability: dict[str, Any], source: int, target: int) -> bool:
    rows = suitability.get("rows") or []
    for row in rows:
        if str(row.get("source_type")) == str(source):
            return bool((row.get("allowed_targets") or {}).get(str(target), False))
    return source == target


def landuse_label(landuse_info: dict[str, Any], value: int) -> str:
    payload = (landuse_info.get("types") or {}).get(str(value)) or {}
    return str(payload.get("zh") or payload.get("en") or value)


def raster_cell_area_ha(raster: dict[str, Any]) -> float:
    res = tuple(raster.get("resolution") or (80.0, 80.0))
    return abs(float(res[0]) * float(res[1])) / 10000.0


def safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        return int(value)
    except Exception:
        return None


def text_of(node: ElementTree.Element | None, child: str, default: str) -> str:
    if node is None:
        return default
    found = node.find(child)
    if found is None or found.text is None:
        return default
    return found.text.strip()


if __name__ == "__main__":
    main()
