"""Causal World Model — Angle C: interventional prediction via world model.

Bridges statistical causal inference (Angle A) and the AlphaEarth World Model
(Plan D) to enable interventional, counterfactual, and calibrated LULC
change predictions.

Four tools:
1. intervention_predict     — spatially heterogeneous scenario simulation
2. counterfactual_comparison — side-by-side dual-scenario comparison
3. embedding_treatment_effect — causal impact measured in embedding space
4. integrate_statistical_prior — calibrate world model with ATT estimate
"""

from __future__ import annotations

import json
import logging
import time

import matplotlib
matplotlib.use("Agg")

import numpy as np

from .gis_processors import _generate_output_path
from .utils import _configure_fonts

logger = logging.getLogger(__name__)


# ====================================================================
#  Internal helpers
# ====================================================================

def _parse_bbox(bbox_str: str) -> list[float]:
    """Parse 'minx,miny,maxx,maxy' string to list of 4 floats."""
    parts = [float(x.strip()) for x in bbox_str.split(",")]
    if len(parts) != 4:
        raise ValueError(f"bbox must have 4 values, got {len(parts)}")
    return parts


def _create_spatial_mask(
    bbox: list[float],
    sub_bbox: list[float],
    grid_shape: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    """Map sub_bbox to pixel row/col indices within the full bbox grid.

    Returns:
        (row_indices, col_indices) — 1-D arrays usable for advanced indexing.
    """
    h, w = grid_shape
    minx, miny, maxx, maxy = bbox
    dx = (maxx - minx) / w if w > 0 else 1.0
    dy = (maxy - miny) / h if h > 0 else 1.0

    # sub_bbox pixel bounds
    c0 = max(0, int((sub_bbox[0] - minx) / dx))
    c1 = min(w, int(np.ceil((sub_bbox[2] - minx) / dx)))
    r0 = max(0, int((maxy - sub_bbox[3]) / dy))
    r1 = min(h, int(np.ceil((maxy - sub_bbox[1]) / dy)))

    rows = np.arange(r0, r1)
    cols = np.arange(c0, c1)
    # Meshgrid for advanced indexing into [B, C, H, W]
    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    return rr.ravel(), cc.ravel()


def _lulc_name_to_id(name: str) -> int | None:
    """Map Chinese LULC class name to integer class ID.

    Supports both exact match and substring match for robustness.
    """
    from .world_model import LULC_CLASSES

    # Exact match
    for cls_id, cls_name in LULC_CLASSES.items():
        if cls_name == name:
            return cls_id
    # Substring match
    for cls_id, cls_name in LULC_CLASSES.items():
        if name in cls_name or cls_name in name:
            return cls_id
    return None


def _render_diff_map(
    lulc_a: np.ndarray,
    lulc_b: np.ndarray,
    bbox: list[float],
    title: str,
) -> str:
    """Render a spatial diff map between two LULC grids, save as PNG.

    Pixels that changed class are colored red; unchanged are grey.
    Returns the output file path.
    """
    import matplotlib.pyplot as plt
    _configure_fonts()

    diff = (lulc_a != lulc_b).astype(np.uint8)
    fig, ax = plt.subplots(1, 1, figsize=(8, 6))
    cmap = plt.cm.colors.ListedColormap(["#D3D3D3", "#DC143C"])
    extent = [bbox[0], bbox[2], bbox[1], bbox[3]]
    ax.imshow(diff, cmap=cmap, extent=extent, interpolation="nearest",
              vmin=0, vmax=1)
    ax.set_title(title, fontsize=12)
    ax.set_xlabel("经度")
    ax.set_ylabel("纬度")

    # Legend
    import matplotlib.patches as mpatches
    legend_items = [
        mpatches.Patch(color="#D3D3D3", label="未变化"),
        mpatches.Patch(color="#DC143C", label="变化"),
    ]
    ax.legend(handles=legend_items, loc="lower right", fontsize=9)

    out_path = _generate_output_path("diff_map", "png")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def _render_comparison_plot(
    distributions_a: dict[str, dict],
    distributions_b: dict[str, dict],
    years: list[int],
    labels: tuple[str, str],
) -> str:
    """Render area distribution comparison line chart for selected classes.

    Each scenario's dominant classes are plotted as lines over time.
    Returns the output file path.
    """
    import matplotlib.pyplot as plt
    from .world_model import LULC_COLORS
    _configure_fonts()

    # Collect all class names across both scenarios
    all_classes: set[str] = set()
    for yr in years:
        yr_key = str(yr)
        for dist in (distributions_a, distributions_b):
            if yr_key in dist:
                all_classes.update(dist[yr_key].keys())

    # Filter to classes with meaningful presence (> 1% in any year)
    plot_classes = set()
    for cls in all_classes:
        for yr in years:
            yr_key = str(yr)
            for dist in (distributions_a, distributions_b):
                entry = dist.get(yr_key, {}).get(cls, {})
                if isinstance(entry, dict) and entry.get("percentage", 0) > 1.0:
                    plot_classes.add(cls)

    if not plot_classes:
        plot_classes = all_classes

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    year_strs = [str(y) for y in years]

    for ax, dist, label in zip(axes, [distributions_a, distributions_b], labels):
        for cls in sorted(plot_classes):
            pcts = []
            for yr_key in year_strs:
                entry = dist.get(yr_key, {}).get(cls, {})
                pcts.append(entry.get("percentage", 0) if isinstance(entry, dict) else 0)
            color = LULC_COLORS.get(cls, "#808080")
            ax.plot(years, pcts, marker="o", label=cls, color=color, linewidth=2)
        ax.set_title(label, fontsize=12)
        ax.set_xlabel("年份")
        ax.set_ylabel("占比 (%)")
        ax.legend(fontsize=8, loc="best")
        ax.grid(True, alpha=0.3)

    fig.suptitle("情景对比：面积分布变化", fontsize=14)
    out_path = _generate_output_path("scenario_compare", "png")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def _render_effect_heatmap(
    distance_grid: np.ndarray,
    bbox: list[float],
    title: str,
    metric_label: str,
) -> str:
    """Render a spatial heatmap of per-pixel embedding distances."""
    import matplotlib.pyplot as plt
    _configure_fonts()

    fig, ax = plt.subplots(1, 1, figsize=(8, 6))
    extent = [bbox[0], bbox[2], bbox[1], bbox[3]]
    im = ax.imshow(distance_grid, cmap="hot", extent=extent,
                   interpolation="nearest")
    ax.set_title(title, fontsize=12)
    ax.set_xlabel("经度")
    ax.set_ylabel("纬度")
    cbar = fig.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label(metric_label)

    out_path = _generate_output_path("effect_heatmap", "png")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


# ====================================================================
#  Tool 1: Intervention Predict
# ====================================================================

def intervention_predict(
    bbox: str,
    intervention_sub_bbox: str,
    intervention_type: str,
    baseline_scenario: str = "baseline",
    start_year: str = "2023",
    n_years: str = "5",
) -> str:
    """空间介入预测 — 对子区域施加不同情景，观测土地利用因果效应和溢出效应。

    在指定大区域内对一个子区域施加干预情景（如城市扩张），其余区域保持基线情景，
    通过空间动力学模型模拟干预传导和溢出效应。

    Args:
        bbox: 研究区域边界框 "minx,miny,maxx,maxy" (WGS84)
        intervention_sub_bbox: 干预子区域边界框 "minx,miny,maxx,maxy" (WGS84)，
                               必须在 bbox 范围内
        intervention_type: 干预情景名称 (urban_sprawl/ecological_restoration/
                          agricultural_intensification/climate_adaptation/baseline)
        baseline_scenario: 基线情景名称，默认 baseline
        start_year: 起始年份 (2017-2024)
        n_years: 向前预测年数 (1-20)

    Returns:
        JSON 包含 baseline/intervention 面积分布、因果效应地图(GeoJSON)、溢出分析、差异图
    """
    import torch
    import torch.nn.functional as F

    t0 = time.time()
    try:
        from .world_model import (
            extract_embeddings,
            extract_terrain_context,
            predict_sequence,
            encode_scenario,
            _load_model,
            _load_decoder,
            _embeddings_to_lulc,
            _compute_area_distribution,
            _lulc_grid_to_geojson,
            SCENARIOS,
        )

        # Parse parameters
        bbox_list = _parse_bbox(bbox)
        sub_bbox_list = _parse_bbox(intervention_sub_bbox)
        year = int(start_year)
        steps = min(int(n_years), 20)

        # Validate scenarios
        for sc in (baseline_scenario, intervention_type):
            if sc not in SCENARIOS:
                return json.dumps(
                    {"status": "error",
                     "error": f"未知情景 '{sc}'，可选: {list(SCENARIOS.keys())}"},
                    ensure_ascii=False,
                )

        # Validate sub_bbox within bbox
        if (sub_bbox_list[0] < bbox_list[0] or sub_bbox_list[1] < bbox_list[1]
                or sub_bbox_list[2] > bbox_list[2] or sub_bbox_list[3] > bbox_list[3]):
            return json.dumps(
                {"status": "error",
                 "error": "intervention_sub_bbox 必须在 bbox 范围内"},
                ensure_ascii=False,
            )

        # Extract starting embeddings
        emb = None
        try:
            from .embedding_store import load_grid_embeddings
            emb = load_grid_embeddings(bbox_list, year)
        except Exception:
            pass
        if emb is None:
            emb = extract_embeddings(bbox_list, year)
        if emb is None:
            return json.dumps(
                {"status": "error", "error": "无法提取嵌入数据，请检查 GEE 连接和 bbox"},
                ensure_ascii=False,
            )

        h, w, c = emb.shape
        logger.info("Intervention predict: grid=%dx%d, steps=%d", h, w, steps)

        # Create spatial mask for intervention zone
        mask_rows, mask_cols = _create_spatial_mask(bbox_list, sub_bbox_list, (h, w))
        if len(mask_rows) == 0:
            return json.dumps(
                {"status": "error", "error": "干预子区域未覆盖任何像素，请检查 bbox"},
                ensure_ascii=False,
            )

        # Load model, decoder, terrain
        model = _load_model()
        decoder = _load_decoder()
        ctx_np = extract_terrain_context(bbox_list, target_shape=(h, w))
        ctx = None
        if ctx_np is not None:
            ctx = torch.tensor(ctx_np).unsqueeze(0).float()

        # Scenario encodings
        s_base = encode_scenario(baseline_scenario)
        s_inter = encode_scenario(intervention_type)

        # Starting state
        z = torch.tensor(emb.transpose(2, 0, 1)).unsqueeze(0).float()
        z_np_start = z.squeeze(0).numpy()
        lulc_start = _embeddings_to_lulc(z_np_start, decoder)

        # --- Blended intervention loop ---
        z_blended = z.clone()
        intervention_lulc_grids = {}
        intervention_area_dist = {}
        intervention_area_dist[str(year)] = _compute_area_distribution(lulc_start)

        with torch.no_grad():
            for step in range(steps):
                z_base_next = model(z_blended, s_base, context=ctx)
                z_base_next = F.normalize(z_base_next, p=2, dim=1)
                z_inter_next = model(z_blended, s_inter, context=ctx)
                z_inter_next = F.normalize(z_inter_next, p=2, dim=1)

                # Blend: baseline everywhere, intervention in sub-zone
                z_next = z_base_next.clone()
                z_next[:, :, mask_rows, mask_cols] = z_inter_next[:, :, mask_rows, mask_cols]

                yr = year + step + 1
                lulc_step = _embeddings_to_lulc(z_next.squeeze(0).numpy(), decoder)
                intervention_lulc_grids[yr] = lulc_step
                intervention_area_dist[str(yr)] = _compute_area_distribution(lulc_step)
                z_blended = z_next

        # --- Pure baseline for comparison ---
        baseline_result = predict_sequence(bbox_list, baseline_scenario, year, steps)
        baseline_area_dist = baseline_result.get("area_distribution", {})

        # Final LULC grids
        final_intervention = intervention_lulc_grids[year + steps]
        final_year_key = str(year + steps)

        # Reconstruct pure-baseline final LULC from baseline result
        # Decode from scratch to get pixel-level comparison
        z_pure = z.clone()
        with torch.no_grad():
            for step in range(steps):
                z_pure = model(z_pure, s_base, context=ctx)
                z_pure = F.normalize(z_pure, p=2, dim=1)
        lulc_pure_baseline = _embeddings_to_lulc(z_pure.squeeze(0).numpy(), decoder)

        # --- Spillover analysis ---
        # Pixels OUTSIDE intervention zone where LULC differs from pure baseline
        all_rows = np.arange(h)
        all_cols = np.arange(w)
        full_rr, full_cc = np.meshgrid(all_rows, all_cols, indexing="ij")
        full_rr, full_cc = full_rr.ravel(), full_cc.ravel()

        # Create a boolean mask of the intervention zone
        zone_mask = np.zeros((h, w), dtype=bool)
        zone_mask[mask_rows, mask_cols] = True
        outside_mask = ~zone_mask

        diff_outside = (final_intervention != lulc_pure_baseline) & outside_mask
        total_outside = int(outside_mask.sum())
        changed_outside = int(diff_outside.sum())
        spillover_pct = round(100.0 * changed_outside / max(total_outside, 1), 2)

        # Causal effect GeoJSON: pixels where intervention result differs from baseline
        diff_all = final_intervention != lulc_pure_baseline
        causal_geojson = _lulc_grid_to_geojson(
            (diff_all.astype(np.int32) * 8),  # Mark changed pixels as class 8 (建设用地 color)
            bbox_list, year + steps,
        )
        causal_geojson["properties"]["type"] = "causal_effect_map"

        # Diff visualization
        diff_plot_path = _render_diff_map(
            lulc_pure_baseline, final_intervention, bbox_list,
            f"干预效应: {SCENARIOS[intervention_type].name_zh} ({year}→{year + steps})",
        )

        elapsed = time.time() - t0
        summary = (
            f"空间干预预测完成。干预情景: {SCENARIOS[intervention_type].name_zh}，"
            f"基线情景: {SCENARIOS[baseline_scenario].name_zh}。"
            f"区域: {bbox_list}，干预子区域: {sub_bbox_list}。"
            f"周期: {year}→{year + steps} ({steps}年)。"
            f"网格: {h}x{w}像素，干预区域: {len(mask_rows)}像素。"
            f"溢出效应: 干预区外 {spillover_pct}% 像素发生变化。"
            f"耗时: {elapsed:.1f}s。"
        )

        return json.dumps({
            "status": "ok",
            "baseline_result": baseline_area_dist,
            "intervention_result": intervention_area_dist,
            "causal_effect_map": causal_geojson,
            "spillover_analysis": {
                "total_outside_pixels": total_outside,
                "changed_outside_pixels": changed_outside,
                "spillover_percentage": spillover_pct,
                "intervention_zone_pixels": int(len(mask_rows)),
            },
            "diff_plot_path": diff_plot_path,
            "summary": summary,
            "elapsed_seconds": round(elapsed, 2),
        }, ensure_ascii=False, default=str)

    except Exception as e:
        logger.exception("intervention_predict failed")
        return json.dumps({"status": "error", "error": str(e)},
                          ensure_ascii=False)


# ====================================================================
#  Tool 2: Counterfactual Comparison
# ====================================================================

def counterfactual_comparison(
    bbox: str,
    scenario_a: str,
    scenario_b: str,
    start_year: str = "2023",
    n_years: str = "5",
) -> str:
    """反事实对比 — 同一区域在两个不同情景下的土地利用变化对比分析。

    运行两个完整的世界模型预测序列，逐年比较 LULC 差异、转移矩阵差异，
    生成并排对比图和差异 GeoJSON。

    Args:
        bbox: 研究区域边界框 "minx,miny,maxx,maxy" (WGS84)
        scenario_a: 第一个情景名称
        scenario_b: 第二个情景名称
        start_year: 起始年份 (2017-2024)
        n_years: 预测年数 (1-20)

    Returns:
        JSON 包含两个情景的结果、逐年效应、聚合效应、转移差异矩阵、对比图、差异GeoJSON
    """
    t0 = time.time()
    try:
        from .world_model import (
            predict_sequence,
            _compute_transition_matrix,
            _lulc_grid_to_geojson,
            _load_model,
            _load_decoder,
            _embeddings_to_lulc,
            extract_embeddings,
            extract_terrain_context,
            encode_scenario,
            SCENARIOS,
        )
        import torch
        import torch.nn.functional as F

        bbox_list = _parse_bbox(bbox)
        year = int(start_year)
        steps = min(int(n_years), 20)

        for sc in (scenario_a, scenario_b):
            if sc not in SCENARIOS:
                return json.dumps(
                    {"status": "error",
                     "error": f"未知情景 '{sc}'，可选: {list(SCENARIOS.keys())}"},
                    ensure_ascii=False,
                )

        # Run both predictions
        result_a = predict_sequence(bbox_list, scenario_a, year, steps)
        result_b = predict_sequence(bbox_list, scenario_b, year, steps)

        if result_a.get("status") == "error":
            return json.dumps(result_a, ensure_ascii=False)
        if result_b.get("status") == "error":
            return json.dumps(result_b, ensure_ascii=False)

        # Per-year effects: compute pixel-level differences
        # We need raw LULC grids — re-run to get them
        emb = None
        try:
            from .embedding_store import load_grid_embeddings
            emb = load_grid_embeddings(bbox_list, year)
        except Exception:
            pass
        if emb is None:
            emb = extract_embeddings(bbox_list, year)

        per_year_effects = {}
        geojson_diffs = {}

        if emb is not None:
            h, w, c = emb.shape
            model = _load_model()
            decoder = _load_decoder()
            ctx_np = extract_terrain_context(bbox_list, target_shape=(h, w))
            ctx = None
            if ctx_np is not None:
                ctx = torch.tensor(ctx_np).unsqueeze(0).float()

            s_a = encode_scenario(scenario_a)
            s_b = encode_scenario(scenario_b)
            z_a = torch.tensor(emb.transpose(2, 0, 1)).unsqueeze(0).float()
            z_b = z_a.clone()

            lulc_start = _embeddings_to_lulc(z_a.squeeze(0).numpy(), decoder)

            with torch.no_grad():
                for step in range(steps):
                    z_a = model(z_a, s_a, context=ctx)
                    z_a = F.normalize(z_a, p=2, dim=1)
                    z_b = model(z_b, s_b, context=ctx)
                    z_b = F.normalize(z_b, p=2, dim=1)

                    yr = year + step + 1
                    lulc_a = _embeddings_to_lulc(z_a.squeeze(0).numpy(), decoder)
                    lulc_b = _embeddings_to_lulc(z_b.squeeze(0).numpy(), decoder)

                    diff_mask = lulc_a != lulc_b
                    total_pixels = lulc_a.size
                    changed = int(diff_mask.sum())

                    # Per-class differences
                    from .world_model import LULC_CLASSES
                    class_diffs = {}
                    for cls_id, cls_name in LULC_CLASSES.items():
                        pct_a = 100.0 * np.sum(lulc_a == cls_id) / total_pixels
                        pct_b = 100.0 * np.sum(lulc_b == cls_id) / total_pixels
                        class_diffs[cls_name] = {
                            f"{scenario_a}_pct": round(pct_a, 2),
                            f"{scenario_b}_pct": round(pct_b, 2),
                            "diff_pct": round(pct_b - pct_a, 2),
                        }

                    per_year_effects[str(yr)] = {
                        "changed_pixels": changed,
                        "changed_percentage": round(100.0 * changed / total_pixels, 2),
                        "class_differences": class_diffs,
                    }

                    # GeoJSON of changed pixels for final year
                    if step == steps - 1:
                        diff_grid = np.where(diff_mask, lulc_b, 0).astype(np.int32)
                        geojson_diffs["final"] = _lulc_grid_to_geojson(
                            diff_grid, bbox_list, yr,
                        )

            # Transition difference matrix
            lulc_a_final = _embeddings_to_lulc(z_a.squeeze(0).numpy(), decoder)
            lulc_b_final = _embeddings_to_lulc(z_b.squeeze(0).numpy(), decoder)
            trans_a = _compute_transition_matrix(lulc_start, lulc_a_final)
            trans_b = _compute_transition_matrix(lulc_start, lulc_b_final)

            # Compute difference: trans_b - trans_a
            transition_diff = {}
            all_from = set(list(trans_a.keys()) + list(trans_b.keys()))
            for from_cls in all_from:
                all_to = set(
                    list(trans_a.get(from_cls, {}).keys())
                    + list(trans_b.get(from_cls, {}).keys())
                )
                diffs = {}
                for to_cls in all_to:
                    va = trans_a.get(from_cls, {}).get(to_cls, 0)
                    vb = trans_b.get(from_cls, {}).get(to_cls, 0)
                    if vb - va != 0:
                        diffs[to_cls] = vb - va
                if diffs:
                    transition_diff[from_cls] = diffs
        else:
            transition_diff = {}

        # Aggregate effects
        total_years = len(per_year_effects)
        if total_years > 0:
            final_effects = list(per_year_effects.values())[-1]
            aggregate_effects = {
                "total_changed_percentage": final_effects.get("changed_percentage", 0),
                "n_years": total_years,
                "class_summary": final_effects.get("class_differences", {}),
            }
        else:
            aggregate_effects = {}

        # Comparison plot
        dist_a = result_a.get("area_distribution", {})
        dist_b = result_b.get("area_distribution", {})
        years_list = result_a.get("years", list(range(year, year + steps + 1)))

        diff_plot_path = _render_comparison_plot(
            dist_a, dist_b, years_list,
            (SCENARIOS[scenario_a].name_zh, SCENARIOS[scenario_b].name_zh),
        )

        # Save diff GeoJSON
        geojson_path = ""
        if "final" in geojson_diffs:
            geojson_path = _generate_output_path("counterfactual_diff", "geojson")
            with open(geojson_path, "w", encoding="utf-8") as f:
                json.dump(geojson_diffs["final"], f, ensure_ascii=False)

        elapsed = time.time() - t0
        summary = (
            f"反事实对比完成。情景A: {SCENARIOS[scenario_a].name_zh}，"
            f"情景B: {SCENARIOS[scenario_b].name_zh}。"
            f"区域: {bbox_list}，周期: {year}→{year + steps}。"
            f"最终年差异像素比例: "
            f"{aggregate_effects.get('total_changed_percentage', 'N/A')}%。"
            f"耗时: {elapsed:.1f}s。"
        )

        result = {
            "status": "ok",
            "scenario_a_result": {
                k: v for k, v in result_a.items()
                if k not in ("geojson_layers",)
            },
            "scenario_b_result": {
                k: v for k, v in result_b.items()
                if k not in ("geojson_layers",)
            },
            "per_year_effects": per_year_effects,
            "aggregate_effects": aggregate_effects,
            "transition_diff_matrix": transition_diff,
            "diff_plot_path": diff_plot_path,
            "summary": summary,
            "elapsed_seconds": round(elapsed, 2),
        }
        if geojson_path:
            result["geojson_diff_path"] = geojson_path

        return json.dumps(result, ensure_ascii=False, default=str)

    except Exception as e:
        logger.exception("counterfactual_comparison failed")
        return json.dumps({"status": "error", "error": str(e)},
                          ensure_ascii=False)


# ====================================================================
#  Tool 3: Embedding Treatment Effect
# ====================================================================

def embedding_treatment_effect(
    bbox: str,
    scenario_a: str,
    scenario_b: str,
    start_year: str = "2023",
    n_years: str = "5",
    metric: str = "cosine",
) -> str:
    """嵌入空间处理效应 — 在潜空间中度量两个情景的因果影响差异。

    不同于 LULC 类别对比，在 64 维嵌入空间中计算逐像素距离，
    能捕捉类内渐变（如城市密度渐变）等微妙效应。支持余弦/欧氏/曼哈顿距离。

    Args:
        bbox: 研究区域边界框 "minx,miny,maxx,maxy" (WGS84)
        scenario_a: 第一个情景名称（参考情景）
        scenario_b: 第二个情景名称（处理情景）
        start_year: 起始年份 (2017-2024)
        n_years: 预测年数 (1-20)
        metric: 距离度量 cosine/euclidean/manhattan

    Returns:
        JSON 包含逐年距离统计、热点像素信息、效应热力图路径
    """
    import torch
    import torch.nn.functional as F

    t0 = time.time()
    try:
        from .world_model import (
            extract_embeddings,
            extract_terrain_context,
            encode_scenario,
            _load_model,
            SCENARIOS,
        )

        bbox_list = _parse_bbox(bbox)
        year = int(start_year)
        steps = min(int(n_years), 20)

        if metric not in ("cosine", "euclidean", "manhattan"):
            return json.dumps(
                {"status": "error",
                 "error": f"不支持的距离度量 '{metric}'，可选: cosine/euclidean/manhattan"},
                ensure_ascii=False,
            )

        for sc in (scenario_a, scenario_b):
            if sc not in SCENARIOS:
                return json.dumps(
                    {"status": "error",
                     "error": f"未知情景 '{sc}'，可选: {list(SCENARIOS.keys())}"},
                    ensure_ascii=False,
                )

        # Extract starting embeddings
        emb = None
        try:
            from .embedding_store import load_grid_embeddings
            emb = load_grid_embeddings(bbox_list, year)
        except Exception:
            pass
        if emb is None:
            emb = extract_embeddings(bbox_list, year)
        if emb is None:
            return json.dumps(
                {"status": "error", "error": "无法提取嵌入数据"},
                ensure_ascii=False,
            )

        h, w, c = emb.shape
        model = _load_model()

        ctx_np = extract_terrain_context(bbox_list, target_shape=(h, w))
        ctx = None
        if ctx_np is not None:
            ctx = torch.tensor(ctx_np).unsqueeze(0).float()

        s_a = encode_scenario(scenario_a)
        s_b = encode_scenario(scenario_b)
        z_a = torch.tensor(emb.transpose(2, 0, 1)).unsqueeze(0).float()
        z_b = z_a.clone()

        per_year_distances = {}
        last_distance_grid = None

        with torch.no_grad():
            for step in range(steps):
                z_a = model(z_a, s_a, context=ctx)
                z_a = F.normalize(z_a, p=2, dim=1)
                z_b = model(z_b, s_b, context=ctx)
                z_b = F.normalize(z_b, p=2, dim=1)

                yr = year + step + 1

                # Per-pixel distance: z_a and z_b are [1, 64, H, W]
                za_np = z_a.squeeze(0).numpy()  # [64, H, W]
                zb_np = z_b.squeeze(0).numpy()

                if metric == "cosine":
                    # 1 - cos_sim per pixel
                    dot = np.sum(za_np * zb_np, axis=0)
                    norm_a = np.linalg.norm(za_np, axis=0) + 1e-8
                    norm_b = np.linalg.norm(zb_np, axis=0) + 1e-8
                    cos_sim = dot / (norm_a * norm_b)
                    dist_grid = 1.0 - cos_sim  # [H, W]
                elif metric == "euclidean":
                    dist_grid = np.linalg.norm(za_np - zb_np, axis=0)
                else:  # manhattan
                    dist_grid = np.sum(np.abs(za_np - zb_np), axis=0)

                last_distance_grid = dist_grid
                flat = dist_grid.ravel()
                per_year_distances[str(yr)] = {
                    "mean": round(float(np.mean(flat)), 6),
                    "max": round(float(np.max(flat)), 6),
                    "p95": round(float(np.percentile(flat, 95)), 6),
                    "p50": round(float(np.median(flat)), 6),
                    "std": round(float(np.std(flat)), 6),
                }

        # Hotspot analysis: top 10% distance pixels
        if last_distance_grid is not None:
            threshold = np.percentile(last_distance_grid.ravel(), 90)
            hotspot_mask = last_distance_grid >= threshold
            hotspot_count = int(hotspot_mask.sum())
            hotspot_pct = round(100.0 * hotspot_count / last_distance_grid.size, 2)

            effect_heatmap_path = _render_effect_heatmap(
                last_distance_grid, bbox_list,
                f"嵌入空间效应: {SCENARIOS[scenario_a].name_zh} vs {SCENARIOS[scenario_b].name_zh}",
                f"{metric} 距离",
            )
        else:
            hotspot_count = 0
            hotspot_pct = 0.0
            effect_heatmap_path = ""

        elapsed = time.time() - t0
        summary = (
            f"嵌入空间处理效应分析完成。"
            f"情景A: {SCENARIOS[scenario_a].name_zh}，"
            f"情景B: {SCENARIOS[scenario_b].name_zh}。"
            f"度量: {metric}，网格: {h}x{w}。"
            f"最终年均值距离: {per_year_distances.get(str(year + steps), {}).get('mean', 'N/A')}。"
            f"热点像素: {hotspot_count}({hotspot_pct}%)。"
            f"耗时: {elapsed:.1f}s。"
        )

        return json.dumps({
            "status": "ok",
            "per_year_distances": per_year_distances,
            "hotspot_count": hotspot_count,
            "hotspot_percentage": hotspot_pct,
            "effect_heatmap_path": effect_heatmap_path,
            "metric": metric,
            "grid_shape": [h, w],
            "summary": summary,
            "elapsed_seconds": round(elapsed, 2),
        }, ensure_ascii=False, default=str)

    except Exception as e:
        logger.exception("embedding_treatment_effect failed")
        return json.dumps({"status": "error", "error": str(e)},
                          ensure_ascii=False)


# ====================================================================
#  Tool 4: Integrate Statistical Prior
# ====================================================================

def integrate_statistical_prior(
    bbox: str,
    att_estimate: str,
    att_se: str,
    treatment_variable: str,
    outcome_variable: str,
    scenario: str = "baseline",
    start_year: str = "2023",
    n_years: str = "5",
) -> str:
    """统计先验校准 — 用因果推断 ATT 估计值校准世界模型预测。

    将 Angle A（统计因果推断）的处理效应估计量注入世界模型情景编码，
    通过校准因子缩放情景向量，使模型预测与经验因果估计对齐。

    Args:
        bbox: 研究区域边界框 "minx,miny,maxx,maxy" (WGS84)
        att_estimate: ATT 点估计值（处理组平均处理效应）
        att_se: ATT 标准误
        treatment_variable: 处理变量对应的 LULC 类别名（如 "建设用地"、"耕地"）
        outcome_variable: 结果变量对应的 LULC 类别名（如 "树木"、"草地"）
        scenario: 用于预测的情景名称
        start_year: 起始年份 (2017-2024)
        n_years: 预测年数 (1-20)

    Returns:
        JSON 包含未校准/校准后的预测结果、校准因子、ATT 先验、对比图
    """
    import torch
    import torch.nn.functional as F

    t0 = time.time()
    try:
        from .world_model import (
            extract_embeddings,
            extract_terrain_context,
            predict_sequence,
            encode_scenario,
            _load_model,
            _load_decoder,
            _embeddings_to_lulc,
            _compute_area_distribution,
            SCENARIOS,
        )

        bbox_list = _parse_bbox(bbox)
        att = float(att_estimate)
        se = float(att_se)
        year = int(start_year)
        steps = min(int(n_years), 20)

        if scenario not in SCENARIOS:
            return json.dumps(
                {"status": "error",
                 "error": f"未知情景 '{scenario}'，可选: {list(SCENARIOS.keys())}"},
                ensure_ascii=False,
            )

        # Map LULC class names to IDs
        outcome_id = _lulc_name_to_id(outcome_variable)
        if outcome_id is None:
            return json.dumps(
                {"status": "error",
                 "error": f"无法识别结果变量 '{outcome_variable}'，"
                          f"请使用中文 LULC 类别名"},
                ensure_ascii=False,
            )

        # Run uncalibrated prediction
        uncalib_result = predict_sequence(bbox_list, scenario, year, steps)
        if uncalib_result.get("status") == "error":
            return json.dumps(uncalib_result, ensure_ascii=False)

        uncalib_dist = uncalib_result.get("area_distribution", {})

        # Compute predicted effect: change in outcome class percentage
        start_dist = uncalib_dist.get(str(year), {})
        end_dist = uncalib_dist.get(str(year + steps), {})
        start_pct = start_dist.get(outcome_variable, {}).get("percentage", 0)
        end_pct = end_dist.get(outcome_variable, {}).get("percentage", 0)
        predicted_effect = end_pct - start_pct

        if abs(predicted_effect) < 0.01:
            return json.dumps({
                "status": "warning",
                "message": (
                    f"世界模型预测的 {outcome_variable} 变化量接近 0 "
                    f"(Δ={predicted_effect:.4f}%)，无法计算校准因子。"
                    f"这可能表明所选情景对目标类别影响微弱。"
                ),
                "uncalibrated_prediction": uncalib_dist,
                "att_prior": {"estimate": att, "se": se},
            }, ensure_ascii=False, default=str)

        # Calibration factor: scale scenario encoding
        calibration_factor = att / predicted_effect
        calibration_factor = float(np.clip(calibration_factor, 0.1, 5.0))
        logger.info(
            "Calibration: ATT=%.4f, predicted=%.4f, factor=%.4f",
            att, predicted_effect, calibration_factor,
        )

        # Re-run with calibrated scenario encoding
        emb = None
        try:
            from .embedding_store import load_grid_embeddings
            emb = load_grid_embeddings(bbox_list, year)
        except Exception:
            pass
        if emb is None:
            emb = extract_embeddings(bbox_list, year)
        if emb is None:
            return json.dumps(
                {"status": "error", "error": "无法提取嵌入数据"},
                ensure_ascii=False,
            )

        h, w, c = emb.shape
        model = _load_model()
        decoder = _load_decoder()
        ctx_np = extract_terrain_context(bbox_list, target_shape=(h, w))
        ctx = None
        if ctx_np is not None:
            ctx = torch.tensor(ctx_np).unsqueeze(0).float()

        s_original = encode_scenario(scenario)
        s_calibrated = s_original * calibration_factor

        z = torch.tensor(emb.transpose(2, 0, 1)).unsqueeze(0).float()
        z_np_start = z.squeeze(0).numpy()
        lulc_start = _embeddings_to_lulc(z_np_start, decoder)

        calibrated_dist = {}
        calibrated_dist[str(year)] = _compute_area_distribution(lulc_start)

        with torch.no_grad():
            for step in range(steps):
                z = model(z, s_calibrated, context=ctx)
                z = F.normalize(z, p=2, dim=1)
                yr = year + step + 1
                lulc_step = _embeddings_to_lulc(z.squeeze(0).numpy(), decoder)
                calibrated_dist[str(yr)] = _compute_area_distribution(lulc_step)

        # Comparison plot: uncalibrated vs calibrated for outcome variable
        import matplotlib.pyplot as plt
        _configure_fonts()

        years_list = list(range(year, year + steps + 1))
        uncalib_pcts = []
        calib_pcts = []
        for yr in years_list:
            yr_key = str(yr)
            u_entry = uncalib_dist.get(yr_key, {}).get(outcome_variable, {})
            c_entry = calibrated_dist.get(yr_key, {}).get(outcome_variable, {})
            uncalib_pcts.append(u_entry.get("percentage", 0) if isinstance(u_entry, dict) else 0)
            calib_pcts.append(c_entry.get("percentage", 0) if isinstance(c_entry, dict) else 0)

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(years_list, uncalib_pcts, "b-o", label="未校准预测", linewidth=2)
        ax.plot(years_list, calib_pcts, "r-s", label="ATT校准预测", linewidth=2)
        ax.axhline(y=start_pct, color="gray", linestyle="--", alpha=0.5,
                   label=f"起始值 ({start_pct:.1f}%)")
        ax.axhline(y=start_pct + att, color="green", linestyle="--", alpha=0.5,
                   label=f"ATT目标 ({start_pct + att:.1f}%)")
        ax.fill_between(years_list, calib_pcts,
                        [p + 1.96 * se for p in calib_pcts],
                        alpha=0.1, color="red")
        ax.fill_between(years_list, calib_pcts,
                        [p - 1.96 * se for p in calib_pcts],
                        alpha=0.1, color="red")
        ax.set_title(
            f"统计先验校准: {outcome_variable} ({SCENARIOS[scenario].name_zh})",
            fontsize=13,
        )
        ax.set_xlabel("年份")
        ax.set_ylabel(f"{outcome_variable} 占比 (%)")
        ax.legend(fontsize=10)
        ax.grid(True, alpha=0.3)

        plot_path = _generate_output_path("calibration_compare", "png")
        fig.tight_layout()
        fig.savefig(plot_path, dpi=150)
        plt.close(fig)

        elapsed = time.time() - t0
        # Final calibrated outcome
        final_calib_pct = calib_pcts[-1] if calib_pcts else 0
        summary = (
            f"统计先验校准完成。情景: {SCENARIOS[scenario].name_zh}。"
            f"ATT先验: {att:.4f} ± {se:.4f}。"
            f"世界模型预测效应: {predicted_effect:.4f}%。"
            f"校准因子: {calibration_factor:.4f}。"
            f"{outcome_variable} 校准后: {start_pct:.1f}% → {final_calib_pct:.1f}%。"
            f"耗时: {elapsed:.1f}s。"
        )

        return json.dumps({
            "status": "ok",
            "uncalibrated_prediction": uncalib_dist,
            "calibrated_prediction": calibrated_dist,
            "calibration_factor": round(calibration_factor, 4),
            "predicted_effect_pct": round(predicted_effect, 4),
            "att_prior": {"estimate": att, "se": se},
            "outcome_variable": outcome_variable,
            "comparison_plot_path": plot_path,
            "summary": summary,
            "elapsed_seconds": round(elapsed, 2),
        }, ensure_ascii=False, default=str)

    except Exception as e:
        logger.exception("integrate_statistical_prior failed")
        return json.dumps({"status": "error", "error": str(e)},
                          ensure_ascii=False)
