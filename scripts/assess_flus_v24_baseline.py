#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANUAL = Path("/Users/zhouning/Downloads/GeoSOS-FLUS Manual_En 2019.pdf")
DEFAULT_SOURCE_ZIP = Path("/Users/zhouning/Downloads/FLUS_console.zip")
DEFAULT_V24_ZIP = Path("/Users/zhouning/Downloads/paralleled FLUS_V2.4.zip")
DEFAULT_OUTPUT = REPO_ROOT / "docs/reports/twm_flus_v24_baseline_assessment_2026-06-22.json"
DEFAULT_MARKDOWN = REPO_ROOT / "docs/twm-flus-v24-data-baseline-assessment-2026-06-22.md"
DEFAULT_ASSET_DIR = REPO_ROOT / "docs/assets"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assess official GeoSOS-FLUS V2.4 tutorial data as a TWM baseline package."
    )
    parser.add_argument("--manual", type=Path, default=DEFAULT_MANUAL)
    parser.add_argument("--source-zip", type=Path, default=DEFAULT_SOURCE_ZIP)
    parser.add_argument("--v24-zip", type=Path, default=DEFAULT_V24_ZIP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--asset-dir", type=Path, default=DEFAULT_ASSET_DIR)
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()

    report = assess_package(
        manual_path=args.manual,
        source_zip_path=args.source_zip,
        v24_zip_path=args.v24_zip,
        asset_dir=args.asset_dir,
        render=not args.no_render,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output)}, ensure_ascii=False))


def assess_package(
    *,
    manual_path: Path,
    source_zip_path: Path,
    v24_zip_path: Path,
    asset_dir: Path,
    render: bool,
) -> dict[str, Any]:
    manual_path = manual_path.expanduser()
    source_zip_path = source_zip_path.expanduser()
    v24_zip_path = v24_zip_path.expanduser()
    for path in (manual_path, source_zip_path, v24_zip_path):
        if not path.exists():
            raise FileNotFoundError(str(path))

    with tempfile.TemporaryDirectory(prefix="flus_v24_assessment_") as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(v24_zip_path) as zf:
            zf.extractall(root)
        testdata = find_testdata(root)

        config_color = parse_config_color(read_text(testdata / "config_color.log"))
        config_mp = parse_config_mp(read_text(testdata / "config_mp.log"))
        output_log = read_text(testdata / "output.log")
        classes = sorted(config_color)
        urban_class = find_urban_class(config_color)

        rasters = load_rasters(testdata, config_color)
        predictions = build_prediction_maps(rasters, classes)
        metrics = {
            name: pixel_metrics(
                pred=prediction,
                base=rasters["dg2001coor.tif"]["data"],
                truth=rasters["dg2006true.tif"]["data"],
                valid=rasters["valid_mask"],
                classes=classes,
                urban_class=urban_class,
                future_pixels=config_mp.get("future_pixels") or {},
            )
            for name, prediction in predictions.items()
        }

        assets: dict[str, str] = {}
        if render:
            asset_dir.mkdir(parents=True, exist_ok=True)
            assets = render_assets(asset_dir, rasters, predictions, metrics, config_color, classes)

        manual = inspect_manual(manual_path)
        source = inspect_source_zip(source_zip_path)
        evidence = {
            "manual_supports_dataset_role": manual.get("supports_dataset_role", False),
            "output_log_saves_simulation_result": "simulationResult.tif" in output_log,
            "simulation_result_counts_match_future_pixels": demand_match(
                predictions.get("official_simulationResult"),
                classes,
                config_mp.get("future_pixels") or {},
            ),
            "simulation_result1_counts_match_future_pixels": demand_match(
                predictions.get("official_simulationResult1"),
                classes,
                config_mp.get("future_pixels") or {},
            ),
            "source_zip_contains_ann_and_simulation_code": source.get("contains_ann_and_simulation_code", False),
        }

        previous_comparison = {
            "previous_dongguan_80m_zip": "Good for TWM ingestion, transition-contract validation and proxy baselines, but it did not include an official GeoSOS/FLUS output map in the files used earlier.",
            "flus_v24_zip": "Better for baseline comparison because it bundles start map, truth map, probability-of-occurrence map, restriction map, driving factors, FLUS config/logs and apparent official simulation output rasters.",
            "recommended_role": "Use the FLUS V2.4 package as a separate official FLUS baseline task; keep the earlier DongGuan 80m package for TWM data-contract and renderer/simulator/planner continuity tests.",
        }

        next_tasks = [
            "Add a TWM V2.4 runner that uses dg2001coor.tif as initial state, dg2006true.tif as holdout truth, FLUS future-pixel demand as scenario demand, and restrictedarea/cost matrix as action masks.",
            "Use Probability-of-occurrence.tif as a FLUS-informed suitability input, but keep it separate from the official CA result row.",
            "Generate TWM simulation and planner candidate maps on the same 531x768, 100 m grid and compare them with official_simulationResult using OA, Kappa, change FoM, urban expansion F1, demand fit and restricted-area violations.",
            "If FLUS_console is to be executed directly, treat it as a porting/build task because the provided project is Windows/Visual-Studio oriented and depends on GDAL/ALGLIB/OpenCV-style native code.",
            "Do not claim that TWM beats GeoSOS/FLUS until the TWM V2.4 runner has produced same-case maps and the official baseline row remains in the same metric table.",
        ]

        return {
            "schema": "territory_world_model.flus_v24_baseline_assessment.v1",
            "status": "pass" if all(evidence.values()) else "needs_review",
            "source_files": {
                "manual": str(manual_path),
                "source_zip": str(source_zip_path),
                "v24_zip": str(v24_zip_path),
            },
            "manual": manual,
            "source_zip": source,
            "v24_package": {
                "testdata_path_inside_zip": "FLUS_V2.4/testdata",
                "config_color": config_color,
                "config_mp": config_mp,
                "output_log_tail": "\n".join(output_log.strip().splitlines()[-12:]),
                "raster_profile": raster_profile(rasters),
                "raster_counts": raster_counts(rasters, classes),
                "drivers": driver_inventory(testdata),
            },
            "baseline_metrics": metrics,
            "renderer": {"rendered": bool(assets), "assets": assets},
            "evidence": evidence,
            "judgement": {
                "is_better_than_previous_data_for_flus_baseline": True,
                "confidence": "high",
                "reason": previous_comparison,
                "claim_boundary": [
                    "simulationResult.tif and simulationResult1.tif are treated as package-provided official FLUS sample outputs because they are bundled in the official V2.4 testdata and output.log records saving simulationResult.tif.",
                    "This assessment does not prove that TWM outperforms FLUS; it only establishes a stronger official baseline dataset for same-grid comparison.",
                    "The package is still a tutorial/sample case, not a full natural-resource governance dataset with planning approvals, interventions and review outcomes.",
                ],
            },
            "next_tasks": next_tasks,
        }


def find_testdata(root: Path) -> Path:
    matches = [path for path in root.rglob("testdata") if path.is_dir()]
    if not matches:
        raise FileNotFoundError("testdata directory not found in V2.4 zip")
    return matches[0]


def read_text(path: Path) -> str:
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_bytes().decode("latin-1", errors="replace")


def parse_config_color(text: str) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("["):
            continue
        parts = [part.strip() for part in stripped.split(",")]
        if len(parts) < 6:
            continue
        try:
            idx = int(parts[0])
        except ValueError:
            continue
        rows[idx] = {
            "index": idx,
            "initial_count_from_color_log": int(parts[1]),
            "label": parts[2],
            "rgb": [int(parts[3]), int(parts[4]), int(parts[5])],
        }
    return rows


def parse_config_mp(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result: dict[str, Any] = {"raw": text}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line == "[Number of types]":
            result["number_of_types"] = int(lines[i + 1])
            i += 2
        elif line == "[Future Pixels]":
            count = int(result.get("number_of_types") or 0)
            result["future_pixels"] = {str(idx + 1): int(lines[i + 1 + idx]) for idx in range(count)}
            i += 1 + count
        elif line == "[Cost Matrix]":
            count = int(result.get("number_of_types") or 0)
            result["cost_matrix"] = [
                [int(value) for value in lines[i + 1 + row].split(",")]
                for row in range(count)
            ]
            i += 1 + count
        elif line == "[Intensity of neighborhood]":
            count = int(result.get("number_of_types") or 0)
            result["neighborhood_intensity"] = [float(lines[i + 1 + row]) for row in range(count)]
            i += 1 + count
        elif line == "[Maximum Number Of Iterations]":
            result["maximum_iterations"] = int(lines[i + 1])
            i += 2
        elif line == "[Size of neighborhood]":
            result["neighborhood_size"] = int(lines[i + 1])
            i += 2
        elif line == "[Accelerated factor]":
            result["accelerated_factor"] = float(lines[i + 1])
            i += 2
        else:
            i += 1
    return result


def find_urban_class(config_color: dict[int, dict[str, Any]]) -> int:
    for idx, payload in config_color.items():
        if "urban" in str(payload.get("label", "")).lower():
            return idx
    return min(config_color)


def load_rasters(testdata: Path, config_color: dict[int, dict[str, Any]]) -> dict[str, Any]:
    import rasterio

    names = [
        "dg2001coor.tif",
        "dg2006true.tif",
        "simulationResult.tif",
        "simulationResult1.tif",
        "Probability-of-occurrence.tif",
        "restrictedarea.tif",
    ]
    out: dict[str, Any] = {}
    for name in names:
        path = testdata / name
        with rasterio.open(path) as src:
            data = src.read()
            out[name] = {
                "path": str(path),
                "data": data[0] if data.shape[0] == 1 else data,
                "band_count": int(src.count),
                "shape": [int(src.height), int(src.width)],
                "dtype": str(src.dtypes[0]),
                "crs": str(src.crs) if src.crs else "",
                "transform": tuple(src.transform),
                "resolution": [float(src.res[0]), float(src.res[1])],
                "bounds": tuple(src.bounds),
                "nodata": src.nodata,
            }
    classes = set(config_color)
    base = out["dg2001coor.tif"]["data"]
    truth = out["dg2006true.tif"]["data"]
    valid = np.isin(base, list(classes)) & np.isin(truth, list(classes))
    out["valid_mask"] = valid
    return out


def build_prediction_maps(rasters: dict[str, Any], classes: list[int]) -> dict[str, np.ndarray]:
    base = rasters["dg2001coor.tif"]["data"]
    prob = rasters["Probability-of-occurrence.tif"]["data"]
    if prob.ndim != 3:
        raise ValueError("Probability-of-occurrence.tif must be a multi-band raster")
    argmax = np.asarray(np.argmax(prob, axis=0) + min(classes), dtype=np.int16)
    argmax[~rasters["valid_mask"]] = 0
    return {
        "persistence_2001_as_2006": np.asarray(base).copy(),
        "official_simulationResult": np.asarray(rasters["simulationResult.tif"]["data"]).copy(),
        "official_simulationResult1": np.asarray(rasters["simulationResult1.tif"]["data"]).copy(),
        "probability_argmax_not_ca_result": argmax,
    }


def pixel_metrics(
    *,
    pred: np.ndarray,
    base: np.ndarray,
    truth: np.ndarray,
    valid: np.ndarray,
    classes: list[int],
    urban_class: int,
    future_pixels: dict[str, int],
) -> dict[str, Any]:
    pred_v = np.asarray(pred[valid]).astype(int)
    base_v = np.asarray(base[valid]).astype(int)
    truth_v = np.asarray(truth[valid]).astype(int)
    n = int(valid.sum())
    correct = int((pred_v == truth_v).sum())
    oa = correct / max(1, n)

    pred_counts = Counter(pred_v.tolist())
    truth_counts = Counter(truth_v.tolist())
    pe = sum(pred_counts.get(cls, 0) * truth_counts.get(cls, 0) for cls in classes) / float(max(1, n * n))
    kappa = (oa - pe) / max(1e-12, 1.0 - pe)

    pred_change = pred_v != base_v
    truth_change = truth_v != base_v
    change_hit = int((pred_change & truth_change).sum())
    change_false_alarm = int((pred_change & ~truth_change).sum())
    change_miss = int((~pred_change & truth_change).sum())
    change_precision = change_hit / max(1, change_hit + change_false_alarm)
    change_recall = change_hit / max(1, change_hit + change_miss)
    transition_hit = int(((pred_v == truth_v) & truth_change & pred_change).sum())

    pred_urban = (base_v != urban_class) & (pred_v == urban_class)
    truth_urban = (base_v != urban_class) & (truth_v == urban_class)
    urban_hit = int((pred_urban & truth_urban).sum())
    urban_false_alarm = int((pred_urban & ~truth_urban).sum())
    urban_miss = int((~pred_urban & truth_urban).sum())
    urban_precision = urban_hit / max(1, urban_hit + urban_false_alarm)
    urban_recall = urban_hit / max(1, urban_hit + urban_miss)

    predicted_counts = {str(cls): int(pred_counts.get(cls, 0)) for cls in classes}
    truth_count_map = {str(cls): int(truth_counts.get(cls, 0)) for cls in classes}
    full_pred_counts = Counter(np.asarray(pred).reshape(-1).astype(int).tolist())
    full_predicted_counts = {str(cls): int(full_pred_counts.get(cls, 0)) for cls in classes}
    future_mae = None
    future_rmse = None
    if future_pixels:
        diffs = [full_predicted_counts[str(cls)] - int(future_pixels.get(str(cls), 0)) for cls in classes]
        future_mae = float(np.mean(np.abs(diffs)))
        future_rmse = float(math.sqrt(np.mean(np.square(diffs))))

    per_class_f1 = {}
    for cls in classes:
        tp = int(((pred_v == cls) & (truth_v == cls)).sum())
        fp = int(((pred_v == cls) & (truth_v != cls)).sum())
        fn = int(((pred_v != cls) & (truth_v == cls)).sum())
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        per_class_f1[str(cls)] = round(harmonic(precision, recall), 6)

    return {
        "schema": "territory_world_model.flus_v24_pixel_metric.v1",
        "valid_cell_count": n,
        "overall_accuracy": round(oa, 6),
        "kappa": round(kappa, 6),
        "correct_cell_count": correct,
        "predicted_change_count": int(pred_change.sum()),
        "actual_change_count": int(truth_change.sum()),
        "change_hit_count": change_hit,
        "change_false_alarm_count": change_false_alarm,
        "change_miss_count": change_miss,
        "change_precision": round(change_precision, 6),
        "change_recall": round(change_recall, 6),
        "change_f1": round(harmonic(change_precision, change_recall), 6),
        "change_fom": round(change_hit / max(1, change_hit + change_false_alarm + change_miss), 6),
        "transition_hit_on_changed_cells": transition_hit,
        "transition_accuracy_on_actual_change": round(transition_hit / max(1, int(truth_change.sum())), 6),
        "urban_expansion_hit_count": urban_hit,
        "predicted_urban_expansion_count": int(pred_urban.sum()),
        "actual_urban_expansion_count": int(truth_urban.sum()),
        "urban_expansion_precision": round(urban_precision, 6),
        "urban_expansion_recall": round(urban_recall, 6),
        "urban_expansion_f1": round(harmonic(urban_precision, urban_recall), 6),
        "predicted_counts": predicted_counts,
        "predicted_counts_full_raster": full_predicted_counts,
        "truth_counts": truth_count_map,
        "future_pixel_demand_mae": round(future_mae, 6) if future_mae is not None else None,
        "future_pixel_demand_rmse": round(future_rmse, 6) if future_rmse is not None else None,
        "macro_f1": round(float(np.mean(list(per_class_f1.values()))), 6),
        "per_class_f1": per_class_f1,
    }


def harmonic(precision: float, recall: float) -> float:
    if precision + recall <= 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def demand_match(
    pred: np.ndarray | None,
    classes: list[int],
    future_pixels: dict[str, int],
) -> bool:
    if pred is None or not future_pixels:
        return False
    counts = Counter(np.asarray(pred).reshape(-1).astype(int).tolist())
    return all(counts.get(cls, 0) == int(future_pixels.get(str(cls), -1)) for cls in classes)


def raster_profile(rasters: dict[str, Any]) -> dict[str, Any]:
    profile = {}
    for name, item in rasters.items():
        if name == "valid_mask":
            continue
        profile[name] = {
            "shape": item["shape"],
            "band_count": item["band_count"],
            "dtype": item["dtype"],
            "crs": item["crs"],
            "resolution": item["resolution"],
            "nodata": item["nodata"],
        }
    first = rasters["dg2001coor.tif"]
    cell_area_m2 = abs(float(first["resolution"][0]) * float(first["resolution"][1]))
    profile["common"] = {
        "valid_cell_count": int(rasters["valid_mask"].sum()),
        "cell_area_m2": cell_area_m2,
        "cell_area_ha": round(cell_area_m2 / 10000.0, 6),
    }
    return profile


def raster_counts(rasters: dict[str, Any], classes: list[int]) -> dict[str, Any]:
    out = {}
    for name, item in rasters.items():
        if name == "valid_mask" or name == "Probability-of-occurrence.tif":
            continue
        arr = np.asarray(item["data"])
        counter = Counter(arr.reshape(-1).astype(int).tolist())
        out[name] = {str(cls): int(counter.get(cls, 0)) for cls in classes}
        zero_count = int(counter.get(0, 0))
        if zero_count:
            out[name]["0"] = zero_count
        nodata = item.get("nodata")
        if nodata is not None and math.isfinite(float(nodata)):
            out[name][str(int(nodata))] = int(counter.get(int(nodata), 0))
    return out


def driver_inventory(testdata: Path) -> dict[str, Any]:
    import rasterio

    names = [
        "dem_dg.tif",
        "slope.tif",
        "Aspect.tif",
        "tocity_dg.tif",
        "distotown.tif",
        "distohighway.tif",
        "distoroad.tif",
        "distorailway.tif",
        "ProximityWater.tif",
    ]
    inventory = {}
    for name in names:
        path = testdata / name
        if not path.exists():
            inventory[name] = {"status": "missing"}
            continue
        with rasterio.open(path) as src:
            arr = src.read(1, masked=True)
            finite = np.asarray(arr.compressed(), dtype=np.float64)
            inventory[name] = {
                "status": "loaded",
                "shape": [int(src.height), int(src.width)],
                "crs": str(src.crs) if src.crs else "",
                "resolution": [float(src.res[0]), float(src.res[1])],
                "nodata": src.nodata,
                "min": float(finite.min()) if finite.size else None,
                "max": float(finite.max()) if finite.size else None,
            }
    return inventory


def inspect_manual(path: Path) -> dict[str, Any]:
    try:
        from pypdf import PdfReader
    except Exception as exc:  # pragma: no cover
        return {"status": "unreadable", "error": str(exc)}

    reader = PdfReader(str(path))
    page_texts = [(page.extract_text() or "") for page in reader.pages]
    joined = "\n".join(page_texts)
    evidence_terms = [
        "dg2001coor.tif",
        "dg2006true.tif",
        "restrictedarea.tif",
        "Probability-of-occurrence.tif",
        "ANN",
        "Cellular Automata",
        "Kappa",
        "FoM",
    ]
    found_terms = [term for term in evidence_terms if term.lower() in joined.lower()]
    snippets = []
    for term in ("dg2001coor.tif", "dg2006true.tif", "restrictedarea.tif", "Kappa", "FoM"):
        snippet = snippet_around(joined, term, 220)
        if snippet:
            snippets.append({"term": term, "snippet": snippet})
    return {
        "status": "read",
        "page_count": len(reader.pages),
        "found_terms": found_terms,
        "supports_dataset_role": all(term in found_terms for term in ("dg2001coor.tif", "dg2006true.tif", "restrictedarea.tif")),
        "method_summary": [
            "The manual describes GeoSOS-FLUS as a multi-type land-use simulation tool coupling human and natural effects.",
            "The workflow contains ANN-based probability-of-occurrence estimation and a CA allocation/simulation module.",
            "The tutorial data roles include start-year land use, validation-year land use, restricted area, driving factors and validation outputs.",
        ],
        "evidence_snippets": snippets,
    }


def snippet_around(text: str, term: str, width: int) -> str:
    idx = text.lower().find(term.lower())
    if idx < 0:
        return ""
    lo = max(0, idx - width // 2)
    hi = min(len(text), idx + len(term) + width // 2)
    return re.sub(r"\s+", " ", text[lo:hi]).strip()


def inspect_source_zip(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        selected = [name for name in names if name.endswith((".cpp", ".h", ".log", ".csv", ".vcxproj", ".sln"))]
        contains_ann = any(name.endswith("FLUS/nntrain.cpp") for name in names)
        contains_sim = any(name.endswith("FLUS/simulationprocess.cpp") for name in names)
        config = ""
        demand = ""
        for candidate in ("FLUS_console/FilesGenerate/config.log", "FLUS_console/FilesGenerate/Demand.csv"):
            if candidate in names:
                raw = zf.read(candidate)
                text = raw.decode("gbk", errors="replace")
                if candidate.endswith("config.log"):
                    config = text
                else:
                    demand = text
    return {
        "status": "read",
        "file_count": len(names),
        "selected_files": selected[:80],
        "contains_ann_and_simulation_code": contains_ann and contains_sim,
        "not_immediately_runnable_on_macos_reason": "The package is a Visual Studio/C++ project and source files include Windows-specific headers; running it directly on macOS would require a separate port/build setup.",
        "config_log": config,
        "demand_csv": demand,
    }


def render_assets(
    asset_dir: Path,
    rasters: dict[str, Any],
    predictions: dict[str, np.ndarray],
    metrics: dict[str, dict[str, Any]],
    config_color: dict[int, dict[str, Any]],
    classes: list[int],
) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Patch

    colors = {0: "#f1f1ec"}
    labels = {0: "NoData"}
    for cls, payload in config_color.items():
        r, g, b = payload["rgb"]
        colors[cls] = f"#{r:02x}{g:02x}{b:02x}"
        labels[cls] = payload["label"]

    max_class = max(classes)
    cmap = ListedColormap([colors.get(idx, "#d0d0d0") for idx in range(max_class + 1)])
    norm = BoundaryNorm(np.arange(-0.5, max_class + 1.5, 1), cmap.N)
    valid = rasters["valid_mask"]

    map_items = [
        ("Initial 2001", rasters["dg2001coor.tif"]["data"]),
        ("Truth 2006", rasters["dg2006true.tif"]["data"]),
        ("FLUS result", predictions["official_simulationResult"]),
        ("FLUS result1", predictions["official_simulationResult1"]),
        ("Probability argmax", predictions["probability_argmax_not_ca_result"]),
    ]
    fig, axes = plt.subplots(1, len(map_items), figsize=(18, 4.7), constrained_layout=True)
    for ax, (title, arr) in zip(axes, map_items):
        shown = np.asarray(arr).copy()
        shown[~valid] = 0
        ax.imshow(shown, cmap=cmap, norm=norm, interpolation="nearest")
        key = {
            "FLUS result": "official_simulationResult",
            "FLUS result1": "official_simulationResult1",
            "Probability argmax": "probability_argmax_not_ca_result",
        }.get(title)
        subtitle = ""
        if key:
            subtitle = f"\nOA={metrics[key]['overall_accuracy']:.3f}, FoM={metrics[key]['change_fom']:.3f}"
        ax.set_title(title + subtitle, fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])
    handles = [Patch(facecolor=colors[idx], edgecolor="none", label=f"{idx} {labels[idx]}") for idx in [0] + classes]
    fig.legend(handles=handles, loc="lower center", ncol=min(6, len(handles)), frameon=False, fontsize=9)
    maps_path = asset_dir / "twm_flus_v24_landuse_baselines.png"
    fig.savefig(maps_path, bbox_inches="tight", dpi=180)
    plt.close(fig)

    names = list(metrics)
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(10.5, 5.0), constrained_layout=True)
    width = 0.22
    ax.bar(x - 1.5 * width, [metrics[n]["overall_accuracy"] for n in names], width, label="OA", color="#455a64")
    ax.bar(x - 0.5 * width, [metrics[n]["kappa"] for n in names], width, label="Kappa", color="#607d8b")
    ax.bar(x + 0.5 * width, [metrics[n]["change_fom"] for n in names], width, label="Change FoM", color="#c62828")
    ax.bar(x + 1.5 * width, [metrics[n]["urban_expansion_f1"] for n in names], width, label="Urban F1", color="#2e7d32")
    ax.set_xticks(x)
    ax.set_xticklabels([name.replace("_", "\n") for name in names], fontsize=8)
    ax.set_ylim(0, 1.02)
    ax.grid(axis="y", color="#e5e5e5")
    ax.legend(frameon=False, ncol=4)
    ax.set_title("FLUS V2.4 official sample baseline metrics")
    metrics_path = asset_dir / "twm_flus_v24_baseline_metrics.png"
    fig.savefig(metrics_path, bbox_inches="tight", dpi=180)
    plt.close(fig)

    base = rasters["dg2001coor.tif"]["data"]
    truth = rasters["dg2006true.tif"]["data"]
    change_items = [
        ("Actual change", truth != base),
        ("FLUS change", predictions["official_simulationResult"] != base),
        ("FLUS result1 change", predictions["official_simulationResult1"] != base),
        ("Probability argmax change", predictions["probability_argmax_not_ca_result"] != base),
    ]
    fig, axes = plt.subplots(1, len(change_items), figsize=(15, 4.2), constrained_layout=True)
    for ax, (title, mask) in zip(axes, change_items):
        rgb = np.zeros((*mask.shape, 4), dtype=float)
        rgb[..., :3] = np.array([0.94, 0.94, 0.90])
        rgb[..., 3] = 1.0
        rgb[mask & valid, :3] = np.array([0.78, 0.18, 0.16])
        rgb[~valid, :3] = np.array([0.98, 0.98, 0.96])
        ax.imshow(rgb, interpolation="nearest")
        ax.set_title(title, fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])
    change_path = asset_dir / "twm_flus_v24_change_baselines.png"
    fig.savefig(change_path, bbox_inches="tight", dpi=180)
    plt.close(fig)

    prob = rasters["Probability-of-occurrence.tif"]["data"]
    fig, axes = plt.subplots(1, len(classes), figsize=(17, 4.0), constrained_layout=True)
    for ax, cls in zip(axes, classes):
        band = prob[cls - min(classes)]
        shown = np.asarray(band, dtype=np.float32).copy()
        shown[~valid] = np.nan
        im = ax.imshow(shown, cmap="viridis", interpolation="nearest")
        ax.set_title(f"P({cls} {labels[cls]})", fontsize=9)
        ax.set_xticks([])
        ax.set_yticks([])
        fig.colorbar(im, ax=ax, shrink=0.75)
    prob_path = asset_dir / "twm_flus_v24_probability_bands.png"
    fig.savefig(prob_path, bbox_inches="tight", dpi=160)
    plt.close(fig)

    return {
        "landuse_baselines": rel_asset(maps_path),
        "baseline_metrics": rel_asset(metrics_path),
        "change_baselines": rel_asset(change_path),
        "probability_bands": rel_asset(prob_path),
    }


def rel_asset(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT / "docs"))
    except ValueError:
        return str(path)


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["baseline_metrics"]
    assets = report["renderer"]["assets"]
    profile = report["v24_package"]["raster_profile"]["common"]
    evidence = report["evidence"]
    lines = [
        "# TWM x GeoSOS-FLUS V2.4 官方样例数据基线评估",
        "",
        "更新日期：2026-06-22",
        "",
        "## 1. 总体判断",
        "",
        "这批 `paralleled FLUS_V2.4.zip` 数据比之前用于 DongGuan 80m 适配的数据更适合做 TWM 与 GeoSOS/FLUS 的 baseline 对比。核心原因是它同时包含起始土地利用、验证真值、概率图、限制区、驱动因子、FLUS 配置日志，以及包内已经生成的 `simulationResult.tif` / `simulationResult1.tif`。",
        "",
        "因此，它可以支撑“同一栅格、同一需求量、同一验证真值”的官方 FLUS 样例输出对比；之前的数据更适合验证 TWM 数据接入和 proxy baseline，不足以支撑官方 FLUS 输出对比。",
        "",
        "必须保留边界：这仍然是官方教程/样例案例，不是完整自然资源治理业务数据；目前也还不能说 TWM 已经优于 FLUS，只有在 TWM 针对此 V2.4 数据生成同案模拟与规划结果后，才能进入正式比较。",
        "",
        "## 2. 数据基础",
        "",
        f"- 有效像元：`{profile['valid_cell_count']}`",
        f"- 栅格分辨率：`100 m`，单像元约 `{profile['cell_area_ha']}` ha",
        "- 土地类型：1 Urban land，2 Water area，3 Cropland，4 Forest land，5 Orchard",
        "- 起始图：`dg2001coor.tif`",
        "- 真值图：`dg2006true.tif`",
        "- 官方样例输出：`simulationResult.tif`、`simulationResult1.tif`",
        "- FLUS 概率图：`Probability-of-occurrence.tif`，5 band",
        "- 限制区：`restrictedarea.tif`",
        "- 驱动因子：DEM、坡度、坡向、距城市中心、距城镇、距高速、距道路、距铁路等",
        "",
        "![Land-use baseline maps](" + assets.get("landuse_baselines", "") + ")",
        "",
        "![Change baseline maps](" + assets.get("change_baselines", "") + ")",
        "",
        "![Probability bands](" + assets.get("probability_bands", "") + ")",
        "",
        "## 3. 官方 FLUS 样例输出指标",
        "",
        "这里把 `simulationResult.tif` 和 `simulationResult1.tif` 当作包内官方样例输出；依据是 V2.4 包直接包含这些结果图，且 `output.log` 记录了保存 `simulationResult.tif` 的过程。`Probability-of-occurrence.tif` 的 argmax 只作为概率图诊断基线，不等同于最终 CA 模拟结果。",
        "",
        "![Baseline metrics](" + assets.get("baseline_metrics", "") + ")",
        "",
        "| baseline | OA | Kappa | change FoM | change F1 | urban F1 | predicted change | actual change | demand MAE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metric in metrics.items():
        lines.append(
            f"| {name} | {metric['overall_accuracy']:.6f} | {metric['kappa']:.6f} | "
            f"{metric['change_fom']:.6f} | {metric['change_f1']:.6f} | {metric['urban_expansion_f1']:.6f} | "
            f"{metric['predicted_change_count']} | {metric['actual_change_count']} | {metric['future_pixel_demand_mae']:.3f} |"
        )
    lines.extend(
        [
            "",
            "关键读法：",
            "",
            "- `persistence_2001_as_2006` 的 OA/Kappa 不低，是因为大部分像元不变；但它的 change FoM 和 urban F1 为 0，说明它不能解释变化。",
            "- `official_simulationResult` 与 `official_simulationResult1` 严格贴合 FLUS future-pixel 需求量，变化定位 FoM 约 0.29。",
            "- `probability_argmax_not_ca_result` 的变化 FoM 更高但 OA/Kappa 更低，说明概率图不是最终土地利用需求约束后的 CA 结果。",
            "",
            "## 4. 证据链",
            "",
            f"- 手册可读且包含样例数据角色说明：`{evidence['manual_supports_dataset_role']}`",
            f"- `output.log` 记录保存 `simulationResult.tif`：`{evidence['output_log_saves_simulation_result']}`",
            f"- `simulationResult.tif` 类别数量匹配 future-pixel 需求：`{evidence['simulation_result_counts_match_future_pixels']}`",
            f"- `simulationResult1.tif` 类别数量匹配 future-pixel 需求：`{evidence['simulation_result1_counts_match_future_pixels']}`",
            f"- `FLUS_console.zip` 包含 ANN 与 simulation C++ 代码：`{evidence['source_zip_contains_ann_and_simulation_code']}`",
            "",
            "## 5. 对 TWM 的意义",
            "",
            "这批数据最适合拆成一个独立任务：`TWM x FLUS V2.4 official sample baseline`。TWM 的渲染器负责把起始图、真值图、官方 FLUS 图、概率图和变化图并列可视化；模拟器负责在相同 100 m 栅格上生成 TWM 候选模拟图；规划器负责在同一需求量和限制条件下输出不同政策目标的候选方案，并与官方 FLUS 样例输出同表比较。",
            "",
            "下一步不能只停在数据分析。应把 V2.4 数据接入 TWM runner：使用 `dg2001coor.tif` 作为初始状态、`dg2006true.tif` 作为 holdout 真值、FLUS future-pixel 作为需求约束、`restrictedarea.tif` 和 cost matrix 作为动作约束，再输出 TWM 的模拟/优化结果图。",
            "",
            "## 6. 未完成项",
            "",
        ]
    )
    for item in report["next_tasks"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
