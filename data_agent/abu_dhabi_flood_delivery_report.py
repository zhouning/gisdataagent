"""Localized phase-5 delivery report for the Abu Dhabi flood workbench."""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from typing import Any

from .uwm.abu_dhabi_flood.external_validation import external_validation_payload
from .uwm.abu_dhabi_flood.hotspot_inventory import hotspot_catalog_payload


def phase5_report_payload() -> dict[str, Any]:
    catalog = hotspot_catalog_payload()
    inventory = catalog.get("inventory") or {}
    concordance = catalog.get("spatial_concordance") or {}
    periods = concordance.get("return_periods") or {}
    return {
        "schema": "gwm.abu_dhabi_flood.phase5_delivery_report.v3",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "hotspot_inventory": inventory,
        "network_candidate_join": catalog.get("network_candidate_join") or {},
        "intervention_catalog": catalog.get("intervention_catalog") or {},
        "gwm_static_prior": catalog.get("gwm_static_prior") or {},
        "spatial_concordance": {
            "five_year": periods.get("5") or {},
            "hundred_year": periods.get("100") or {},
            "validation_gate": concordance.get("validation_gate") or {},
        },
        "external_validation": external_validation_payload(),
        "claim_boundary": (
            "Origen hotspot points are static weak spatial evidence. They are not event-specific "
            "observed depth, flood-extent, timing, or recession ground truth, and "
            "intervention text "
            "does not establish a modeled hydraulic benefit."
        ),
    }


def _metric(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def _score(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "—"


def phase5_report_html(language: str | None = None) -> str:
    """Render a printable report; English is the safe/default demo language."""

    report = phase5_report_payload()
    zh = str(language or "en").lower().startswith("zh")
    inventory = report["hotspot_inventory"]
    five = report["spatial_concordance"]["five_year"]
    hundred = report["spatial_concordance"]["hundred_year"]
    node_join = report["network_candidate_join"]
    interventions = report["intervention_catalog"]
    external = report["external_validation"]
    strict = external.get("strict_confirmatory") or {}
    supplementary = external.get("supplementary") or {}
    origen_ablation = external.get("origen_spatial_ablation") or {}
    origen_ablation_summary = origen_ablation.get("legacy_test_holdout_summary") or {}
    cross_cohort = external.get("cross_cohort") or {}
    engineering = external.get("engineering_admission") or {}
    physics_metrics = (strict.get("physics_emulation") or {}).get("gated_hybrid_gwm") or {}
    satellite_metrics = strict.get("sentinel2_observation") or {}
    satellite_physics = satellite_metrics.get("physics") or {}
    satellite_gwm = satellite_metrics.get("gated_hybrid_gwm") or {}
    strict_receipt = strict.get("receipt") or {}
    supplementary_receipt = supplementary.get("receipt") or {}
    origen_ablation_receipt = origen_ablation.get("receipt") or {}
    static_prior = report["gwm_static_prior"]
    static_prior_counts = static_prior.get("source_record_counts") or {}
    current_grid_count = _metric(
        static_prior_counts.get("current_contributing_within_cutoff")
    )
    current_inventory_count = _metric(static_prior_counts.get("current"))
    intervention_grid_count = _metric(
        static_prior_counts.get("intervention_contributing_within_cutoff")
    )
    intervention_inventory_count = _metric(
        static_prior_counts.get("intervention_recorded")
    )
    if zh:
        labels = {
            "lang": "zh-CN",
            "title": "阿布扎比城市暴雨内涝世界模型 · 阶段 5 交付报告",
            "eyebrow": "验证、行动和证据边界",
            "inventory": "Origen 热点清单",
            "current": "当前热点",
            "history": "ADM 历史热点（独立分层）",
            "nodes": "SWMM 候选节点绑定",
            "interventions": "带位置的干预记录",
            "concordance": "静态热点空间一致性",
            "five": "5 年一遇 ≥1 cm",
            "five5": "5 年一遇 ≥5 cm",
            "hundred": "100 年一遇 ≥1 cm",
            "miss": "100 年一遇域内未命中",
            "denominator": "域内热点",
            "external": "GWM 外部验证",
            "strict": "严格确认性覆盖",
            "small_n": "小样本；预声明目标未满足",
            "supplementary": "补充探索性覆盖",
            "underpowered": "样本不足；Landsat 与 Sentinel-1 分源评估",
            "independent": "跨队列独立事件",
            "disjoint": "两批事件无重叠",
            "physics_iou": "GWM 对物理仿真 IoU",
            "sentinel_iou": "Sentinel-2 宏观 IoU",
            "physics": "物理",
            "gwm": "GWM",
            "no_pool": (
                "严格确认性与补充探索性队列保持分层；Landsat、Sentinel-1 与 "
                "Sentinel-2 指标不得跨传感器合并。"
            ),
            "audit": "审计回执",
            "strict_hash": "严格确认性回执 SHA-256",
            "supplementary_hash": "补充验证回执 SHA-256",
            "origen_model": "Origen GWM 前瞻消融",
            "active_channels": "有效静态特征通道",
            "current_grid": "进入当前网格的热点",
            "intervention_grid": "进入当前网格的干预记录",
            "spatial_folds": "空间分块折数",
            "paired_models": "成对模型",
            "rmse_folds": "RMSE 改善折数",
            "iou_folds": "IoU 改善折数",
            "origen_result": "消融结论",
            "origen_mixed": "结果混合，暂无一致收益",
            "origen_consistent": "探索性空间折中一致改善",
            "origen_unavailable": "尚未完成",
            "origen_hash": "Origen 消融回执 SHA-256",
            "origen_boundary": (
                "Origen 消融仅使用物理仿真标签作探索性比较，未使用已有外部确认"
                "队列；新模型仍需未来独立事件验证。"
            ),
            "verified": "规范化内容哈希已校验",
            "admission": "工程准入",
            "not_admitted": "未准入",
            "admission_reason": (
                "严格确认性事件仅 4/5，且遥感水体掩膜不是实测水深；"
                "这些证据不能授权工程预测或运行替代。"
            ),
            "remaining": "剩余证据缺口",
            "remaining_items": (
                "补足第 5 个通过冻结覆盖门的严格确认事件，并取得独立实测"
                "水深、范围、时序与退水校准证据。"
            ),
            "action": "建议下一步",
            "action_text": (
                "优先复核 100 年一遇仍未命中的域内热点，并将已规划干预与正式工程"
                "参数绑定后重跑 SWMM–ANUGA；不得直接把文字措施换算为水深削减量。"
            ),
            "boundary": "证据边界",
        }
    else:
        labels = {
            "lang": "en",
            "title": "Abu Dhabi Urban Pluvial Flood World Model - Phase 5 Delivery Report",
            "eyebrow": "VALIDATION, ACTIONS AND EVIDENCE BOUNDARIES",
            "inventory": "Origen hotspot inventory",
            "current": "Current hotspots",
            "history": "ADM historical hotspots (separate inventory)",
            "nodes": "SWMM candidate-node links",
            "interventions": "Location-specific intervention records",
            "concordance": "Static hotspot spatial concordance",
            "five": "5-year result at or above 1 cm",
            "five5": "5-year result at or above 5 cm",
            "hundred": "100-year result at or above 1 cm",
            "miss": "100-year in-domain non-hits",
            "denominator": "in-domain hotspots",
            "external": "External GWM validation",
            "strict": "Strict confirmatory coverage",
            "small_n": "Small-n; preregistered target not reached",
            "supplementary": "Supplementary exploratory coverage",
            "underpowered": "Underpowered; Landsat and Sentinel-1 assessed separately",
            "independent": "Independent events across cohorts",
            "disjoint": "No event overlap between cohorts",
            "physics_iou": "GWM-to-physics IoU",
            "sentinel_iou": "Sentinel-2 macro IoU",
            "physics": "Physics",
            "gwm": "GWM",
            "no_pool": (
                "The strict confirmatory and supplementary exploratory cohorts remain "
                "separate. Landsat, Sentinel-1 and Sentinel-2 metrics are not pooled "
                "across sensors."
            ),
            "audit": "Audit receipts",
            "strict_hash": "Strict confirmatory receipt SHA-256",
            "supplementary_hash": "Supplementary receipt SHA-256",
            "origen_model": "Prospective Origen GWM ablation",
            "active_channels": "Active static feature channels",
            "current_grid": "Current hotspots influencing the grid",
            "intervention_grid": "Intervention records influencing the grid",
            "spatial_folds": "Spatial-block folds",
            "paired_models": "Paired models",
            "rmse_folds": "Folds with improved RMSE",
            "iou_folds": "Folds with improved IoU",
            "origen_result": "Ablation conclusion",
            "origen_mixed": "Mixed result; no consistent benefit",
            "origen_consistent": "Consistent improvement across exploratory spatial folds",
            "origen_unavailable": "Not completed",
            "origen_hash": "Origen ablation receipt SHA-256",
            "origen_boundary": (
                "The Origen ablation is exploratory and uses physics-simulation labels. "
                "It did not use the existing external confirmatory cohort; the new model "
                "still requires future independent-event validation."
            ),
            "verified": "Canonical content hash verified",
            "admission": "Engineering admission",
            "not_admitted": "NOT ADMITTED",
            "admission_reason": (
                "Only 4 of 5 strict confirmatory events passed the frozen coverage gate, "
                "and satellite water masks are not observed depth. This evidence cannot "
                "authorize engineering prediction or operational replacement."
            ),
            "remaining": "Remaining evidence gap",
            "remaining_items": (
                "Add a fifth strict event that passes the frozen coverage gate, plus "
                "independent observed depth, extent, timing and recession evidence for "
                "calibration."
            ),
            "action": "Recommended next step",
            "action_text": (
                "Review the in-domain hotspots not hit by the 100-year result first. "
                "Bind planned interventions to approved engineering parameters, then rerun "
                "SWMM–ANUGA; do not convert narrative measures directly into depth reductions."
            ),
            "boundary": "Evidence boundary",
        }
    title = escape(labels["title"])
    boundary = escape(
        report["claim_boundary"]
        if not zh
        else (
            "Origen 热点仅为静态位置弱证据，不是事件水深、范围、发生时间或退水真值；"
            "干预文字也不能证明水力改善量。"
        )
    )
    strict_hash = escape(str(strict_receipt.get("declared_sha256") or "unavailable"))
    supplementary_hash = escape(
        str(supplementary_receipt.get("declared_sha256") or "unavailable")
    )
    origen_hash = escape(
        str(origen_ablation_receipt.get("declared_sha256") or "unavailable")
    )
    receipts_verified = str(
        bool((external.get("audit") or {}).get("all_available_receipts_integrity_verified"))
    ).lower()
    origen_interpretation = {
        "mixed_no_consistent_benefit": labels["origen_mixed"],
        "consistent_exploratory_benefit": labels["origen_consistent"],
    }.get(str(origen_ablation.get("interpretation") or ""), labels["origen_unavailable"])
    admission_label = labels["not_admitted"] if not engineering.get("admitted") else "ADMITTED"
    return f"""<!doctype html>
<html lang="{labels["lang"]}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width">
<title>{title}</title>
<style>
body {{ margin: 0; background: #edf4f7; color: #17324a; font: 14px/1.55 Arial, sans-serif; }}
main {{ max-width: 1080px; margin: auto; background: #fff; padding: 36px; }}
h1 {{ font-size: 30px; line-height: 1.2; }}
h2 {{ margin-top: 28px; border-bottom: 2px solid #0f87a8; padding-bottom: 6px; }}
.eyebrow {{ color: #0f87a8; font-weight: 700; letter-spacing: .08em; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }}
.card {{ border: 1px solid #cddde5; border-left: 4px solid #0f87a8; padding: 13px; }}
.card strong {{ display: block; font-size: 24px; }}
.notice {{ padding: 14px; border-left: 4px solid #d97706; background: #fff8e6; }}
.notice.critical {{ border-left-color: #b91c1c; background: #fff1f2; }}
.meta {{ font-family: monospace; color: #607789; }}
</style>
</head>
<body><main>
<div class="eyebrow">{escape(labels["eyebrow"])}</div>
<h1>{title}</h1>
<div class="meta">{escape(report["generated_at_utc"])}</div>
<h2>{escape(labels["inventory"])}</h2>
<section class="grid">
<div class="card"><span>{escape(labels["current"])}</span>
<strong>{_metric(inventory.get("current_count"))}</strong></div>
<div class="card"><span>{escape(labels["history"])}</span>
<strong>{_metric(inventory.get("history_count"))}</strong></div>
<div class="card"><span>{escape(labels["nodes"])}</span>
<strong>{_metric(node_join.get("matched_count"))}</strong></div>
<div class="card"><span>{escape(labels["interventions"])}</span>
<strong>{_metric(interventions.get("item_count"))}</strong></div>
</section>
<h2>{escape(labels["concordance"])}</h2>
<section class="grid">
<div class="card"><span>{escape(labels["five"])}</span>
<strong>{_metric(five.get("hit_ge_0_01m_count"))} /
{_metric(five.get("inside_domain_count"))}</strong>
<small>{escape(labels["denominator"])}</small></div>
<div class="card"><span>{escape(labels["five5"])}</span>
<strong>{_metric(five.get("hit_ge_0_05m_count"))} /
{_metric(five.get("inside_domain_count"))}</strong>
<small>{escape(labels["denominator"])}</small></div>
<div class="card"><span>{escape(labels["hundred"])}</span>
<strong>{_metric(hundred.get("hit_ge_0_01m_count"))} /
{_metric(hundred.get("inside_domain_count"))}</strong>
<small>{escape(labels["denominator"])}</small></div>
<div class="card"><span>{escape(labels["miss"])}</span>
<strong>{_metric(hundred.get("miss_ge_0_01m_count"))}</strong></div>
</section>
<h2>{escape(labels["external"])}</h2>
<section class="grid">
<div class="card"><span>{escape(labels["strict"])}</span>
<strong>{_metric(strict.get("event_count"))} / {_metric(strict.get("target_event_count"))}</strong>
<small>{escape(labels["small_n"])}</small></div>
<div class="card"><span>{escape(labels["supplementary"])}</span>
<strong>{_metric(supplementary.get("event_count"))} /
{_metric(supplementary.get("target_event_count"))}</strong>
<small>{escape(labels["underpowered"])}</small></div>
<div class="card"><span>{escape(labels["independent"])}</span>
<strong>{_metric(cross_cohort.get("independent_event_count"))}</strong>
<small>{escape(labels["disjoint"])}</small></div>
<div class="card"><span>{escape(labels["physics_iou"])}</span>
<strong>{_score(physics_metrics.get("macro_physics_binary_iou"))}</strong>
<small>gated hybrid GWM</small></div>
<div class="card"><span>{escape(labels["sentinel_iou"])}</span>
<strong>{escape(labels["physics"])} {_score(satellite_physics.get("macro_iou"))}</strong>
<small>{escape(labels["gwm"])} {_score(satellite_gwm.get("macro_iou"))}</small></div>
</section>
<div class="notice">{escape(labels["no_pool"])}</div>
<h2>{escape(labels["origen_model"])}</h2>
<section class="grid">
<div class="card"><span>{escape(labels["active_channels"])}</span>
<strong>{_metric(static_prior.get("active_feature_count"))} /
{_metric(static_prior.get("feature_count"))}</strong></div>
<div class="card"><span>{escape(labels["current_grid"])}</span>
<strong>{current_grid_count} / {current_inventory_count}</strong></div>
<div class="card"><span>{escape(labels["intervention_grid"])}</span>
<strong>{intervention_grid_count} / {intervention_inventory_count}</strong></div>
<div class="card"><span>{escape(labels["spatial_folds"])}</span>
<strong>{_metric(origen_ablation.get("fold_count"))}</strong></div>
<div class="card"><span>{escape(labels["paired_models"])}</span>
<strong>{_metric(origen_ablation.get("paired_variant_count"))}</strong></div>
<div class="card"><span>{escape(labels["rmse_folds"])}</span>
<strong>{_metric(origen_ablation_summary.get("rmse_improved_fold_count"))} /
{_metric(origen_ablation.get("fold_count"))}</strong></div>
<div class="card"><span>{escape(labels["iou_folds"])}</span>
<strong>{_metric(origen_ablation_summary.get("iou_improved_fold_count"))} /
{_metric(origen_ablation.get("fold_count"))}</strong></div>
<div class="card"><span>{escape(labels["origen_result"])}</span>
<strong>{escape(origen_interpretation)}</strong></div>
</section>
<div class="notice">{escape(labels["origen_boundary"])}</div>
<h2>{escape(labels["audit"])}</h2>
<p class="meta">{escape(labels["strict_hash"])}: {strict_hash}<br>
{escape(labels["supplementary_hash"])}: {supplementary_hash}<br>
{escape(labels["origen_hash"])}: {origen_hash}<br>
{escape(labels["verified"])}: {receipts_verified}</p>
<h2>{escape(labels["admission"])}</h2>
<div class="notice critical"><strong>{escape(admission_label)}</strong><br>
{escape(labels["admission_reason"])}</div>
<h2>{escape(labels["remaining"])}</h2><p>{escape(labels["remaining_items"])}</p>
<h2>{escape(labels["action"])}</h2><p>{escape(labels["action_text"])}</p>
<h2>{escape(labels["boundary"])}</h2><div class="notice">{boundary}</div>
</main></body>
</html>"""
