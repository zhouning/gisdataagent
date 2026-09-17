"""Localized phase-5 delivery report for the Abu Dhabi flood workbench."""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from typing import Any

from .uwm.abu_dhabi_flood.hotspot_inventory import hotspot_catalog_payload


def phase5_report_payload() -> dict[str, Any]:
    catalog = hotspot_catalog_payload()
    inventory = catalog.get("inventory") or {}
    concordance = catalog.get("spatial_concordance") or {}
    periods = concordance.get("return_periods") or {}
    return {
        "schema": "gwm.abu_dhabi_flood.phase5_delivery_report.v1",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "hotspot_inventory": inventory,
        "network_candidate_join": catalog.get("network_candidate_join") or {},
        "intervention_catalog": catalog.get("intervention_catalog") or {},
        "spatial_concordance": {
            "five_year": periods.get("5") or {},
            "hundred_year": periods.get("100") or {},
            "validation_gate": concordance.get("validation_gate") or {},
        },
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


def phase5_report_html(language: str | None = None) -> str:
    """Render a printable report; English is the safe/default demo language."""

    report = phase5_report_payload()
    zh = str(language or "en").lower().startswith("zh")
    inventory = report["hotspot_inventory"]
    five = report["spatial_concordance"]["five_year"]
    hundred = report["spatial_concordance"]["hundred_year"]
    node_join = report["network_candidate_join"]
    interventions = report["intervention_catalog"]
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
            "pending": "仍待完成的观测验证",
            "pending_items": "事件水深、积水范围、发生时间和退水时间",
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
            "pending": "Observation validation still pending",
            "pending_items": "Event depth, flood extent, occurrence time and recession time",
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
<h2>{escape(labels["pending"])}</h2><p>{escape(labels["pending_items"])}</p>
<h2>{escape(labels["action"])}</h2><p>{escape(labels["action_text"])}</p>
<h2>{escape(labels["boundary"])}</h2><div class="notice">{boundary}</div>
</main></body>
</html>"""
