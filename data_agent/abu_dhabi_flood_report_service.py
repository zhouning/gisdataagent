"""Decision-support reports for every Abu Dhabi flood simulation type.

Reports are derived from the same public contracts used by the map.  Source
files (customer DTM, GDB and native SWMM assets) are never linked or copied
into the response.  The report explicitly distinguishes customer,
public/proxy and model-derived evidence and turns result metrics into an
action card with a verification path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any


REPORT_TYPES = {
    "data_admission",
    "design_storm",
    "swmm_scenario",
    "citywide_2d",
    "gwm_rollout",
    "historical_replay",
}


def _source(
    name: str,
    source_class: str,
    authority: str,
    resolution_m: Any,
    evidence_class: str,
    replacement_rule: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "source_class": source_class,
        "authority": authority,
        "resolution_m": resolution_m,
        "evidence_class": evidence_class,
        "replacement_rule": replacement_rule,
    }


def data_source_matrix() -> list[dict[str, Any]]:
    """Stable, customer-readable source register shared by all reports."""

    return [
        _source("客户雨水管线、节点和设施 GDB", "customer_authoritative", "客户提供", "矢量", "已接入主输入", "客户修订后重建拓扑并重跑 SWMM"),
        _source("客户 dtm_5M.tif", "customer_authoritative", "客户提供", 5, "局部诊断/历史重演已接入", "覆盖和基准验收后重跑 ANUGA 全市二维"),
        _source("客户 AUH_DTM_5m_Z40", "customer_authoritative", "客户提供", 5, "全市多年一遇与历史重演已接入", "客户修订高程、覆盖或垂直基准后按同一 SWMM→ANUGA 链路重跑"),
        _source("Zone B DDF 设计暴雨", "public_reference", "公开设计资料", "时序", "原型强迫", "替换为客户 IDF/雨型后重跑 SWMM"),
        _source("Open-Meteo / NCEI 降雨约束", "public_reference", "公开气象服务", "站点/时序", "原型强迫", "替换为客户雷达/QPE或雨量站后重跑 SWMM"),
        _source("Copernicus DEM GLO-30", "public_proxy", "ESA 公开产品", 30, "客户结果缺失时的二维回退", "仅在对应客户 5 m DTM 结果缺失时使用；客户结果到达后按同一契约重跑 ANUGA"),
        _source("ESA WorldCover 陆海掩膜", "public_reference", "ESA 公开产品", 10, "水域排除与覆盖保护", "替换为客户海岸线/水域边界后重跑二维"),
        _source("SWMM / ANUGA / GWM 派生结果", "model_derived", "本系统运行回执", "计算网格", "依赖上游证据", "上游输入变化时按链路重新运行"),
    ]


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if result == result else default
    except (TypeError, ValueError):
        return default


def _action(
    problem: str,
    evidence: list[str],
    action: str,
    priority: str,
    expected: str,
    rerun: str,
    evidence_status: str,
) -> dict[str, Any]:
    return {
        "problem": problem,
        "evidence": evidence,
        "recommended_action": action,
        "priority": priority,
        "expected_effect": expected,
        "verification_run": rerun,
        "evidence_status": evidence_status,
    }


def _decision_support(report_type: str, results: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    if results.get("result_status") == "asset_pending":
        reason = str(results.get("reason") or "result asset is not available")
        action = _action(
            "结果资产尚未就绪",
            [reason],
            "完成对应模型作业后重新打开本报告；报告结构和页面入口无需改变。",
            "高",
            "生成可审计的模型结果、质量门和空间图层。",
            "完成当前情景的 SWMM / ANUGA 作业",
            "待模型作业完成",
        )
        return {"priority_actions": [action], "hotspots": [], "alternatives": [], "recommended_next_runs": [action["verification_run"]]}
    max_depth = _number(results.get("maximum_depth_m", results.get("max_depth_m")))
    affected = _number(results.get("inundated_area_ge_0_01m2", results.get("affected_area_m2_proxy")))
    depth_text = f"最大深度 {max_depth:.2f} m"
    if report_type == "gwm_rollout":
        baseline = _number(results.get("baseline_max_depth_m"))
        intervention = _number(results.get("intervention_max_depth_m"))
        delta = baseline - intervention
        action = _action(
            "需要从候选干预中筛选优先方案",
            [f"基线 {baseline:.2f} m", f"干预 {intervention:.2f} m", f"最大绝对变化 {_number(results.get('maximum_absolute_delta_m')):.2f} m"],
            "将改善最大的候选方案提交 SWMM + ANUGA 物理复核，再安排工程成本和施工约束评估。",
            "高" if delta > 0.05 else "中",
            f"快速筛选显示峰值深度预计下降 {max(0.0, delta):.2f} m；面积和蓄水量仅作网格代理指标。",
            "重新运行 SWMM → ANUGA（同一降雨、边界和管网参数）",
            "原型筛选；GWM 不是管网级重新求解",
        )
        return {"priority_actions": [action], "hotspots": [], "alternatives": ["保持基线", "采用当前干预参数"], "recommended_next_runs": [action["verification_run"]]}
    action = _action(
        "存在需要优先核查的地表积水或排水能力风险",
        [depth_text] + ([f"影响面积指标 {affected:,.0f} m²"] if affected else []),
        "先核查高深度网格对应的雨水口、节点溢流和管段容量率；对确认的瓶颈安排清淤、雨水口维护或泵站/出水边界方案比选。",
        "高" if max_depth >= 0.5 else "中" if max_depth >= 0.1 else "低",
        "通过降低节点溢流和增加有效排水能力，目标是减少最大深度、影响面积并缩短退水时间；具体数值须由复核运行给出。",
        "重新运行 SWMM + ANUGA，并叠加道路/关键设施影响",
        "原型筛选" if metadata.get("surface_evidence_class") in {"public_proxy_not_authoritative", "proxy"} else "待观测对比",
    )
    return {"priority_actions": [action], "hotspots": [], "alternatives": ["不采取措施（基线）", "维护/清淤", "泵站或管线能力方案"], "recommended_next_runs": [action["verification_run"]]}


def _english_actions(report_type: str, results: dict[str, Any]) -> list[dict[str, Any]]:
    """Render the same decision logic in English; never leak Chinese prose."""

    if report_type == "data_admission":
        return [{
            "problem": "Authoritative data admission is the next decision",
            "evidence": ["Customer receipt and field coverage are pending"],
            "recommended_action": "Complete DTM, rainfall, tide/pump and observation receipts, then rerun the same contract.",
            "priority": "HIGH",
            "expected_effect": "Improves traceability and engineering admission level.",
            "verification_run": "Data preflight → SWMM → ANUGA",
            "evidence_status": "Awaiting customer receipt",
        }]
    if results.get("result_status") == "asset_pending":
        return [{
            "problem": "The result asset is not ready",
            "evidence": [str(results.get("reason") or "Result asset is unavailable")],
            "recommended_action": "Complete the corresponding model job and reopen this report; the page and report contract remain unchanged.",
            "priority": "HIGH",
            "expected_effect": "Produces an auditable model result, quality gate and map layer.",
            "verification_run": "Complete the current SWMM / ANUGA job",
            "evidence_status": "Waiting for model job",
        }]
    if report_type == "gwm_rollout":
        baseline = _number(results.get("baseline_max_depth_m")); intervention = _number(results.get("intervention_max_depth_m"))
        return [{
            "problem": "Select the intervention candidates that warrant physical-model review",
            "evidence": [f"Baseline {baseline:.2f} m", f"Intervention {intervention:.2f} m", f"Maximum absolute delta {_number(results.get('maximum_absolute_delta_m')):.2f} m"],
            "recommended_action": "Submit the largest-improvement candidate to SWMM + ANUGA review, then assess cost and construction constraints.",
            "priority": "HIGH" if baseline - intervention > 0.05 else "MEDIUM",
            "expected_effect": f"Screening indicates a peak-depth reduction of {max(0.0, baseline - intervention):.2f} m; area and storage are grid proxies.",
            "verification_run": "Rerun SWMM → ANUGA with the same rainfall, boundary and network parameters",
            "evidence_status": "Prototype screening; GWM is not a pipe-level re-solve",
        }]
    max_depth = _number(results.get("maximum_depth_m", results.get("max_depth_m")))
    affected = _number(results.get("inundated_area_ge_0_01m2", results.get("affected_area_m2_proxy")))
    return [{
        "problem": "Surface-water depth or drainage-capacity risk needs prioritised inspection",
        "evidence": [f"Maximum depth {max_depth:.2f} m"] + ([f"Affected-area indicator {affected:,.0f} m²"] if affected else []),
        "recommended_action": "Check inlets, surcharge nodes and pipe capacity first; compare cleaning, pump/outfall and pipe-capacity options for confirmed bottlenecks.",
        "priority": "HIGH" if max_depth >= 0.5 else "MEDIUM" if max_depth >= 0.1 else "LOW",
        "expected_effect": "Target lower peak depth and affected area and shorter recession time; the rerun supplies the numeric effect.",
        "verification_run": "Rerun SWMM + ANUGA and overlay roads and critical facilities",
        "evidence_status": "Prototype screening" if report_type == "citywide_2d" else "Awaiting observation comparison",
    }]


def _pending_report_results(report_type: str, reason: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Keep report generation available while an asset is being prepared."""

    titles = {
        "design_storm": "Abu Dhabi design-storm simulation report",
        "swmm_scenario": "Abu Dhabi EPA SWMM scenario report",
        "citywide_2d": "Abu Dhabi citywide 2D simulation report",
    }
    return ({"result_status": "asset_pending", "reason": reason}, {"surface_evidence_class": "pending", "forcing_source": "pending"}, titles[report_type])


_SOURCE_EN = {
    "客户雨水管线、节点和设施 GDB": ("Customer stormwater pipes, nodes and facilities GDB", "Customer-provided", "Vector", "Loaded as primary input", "Rebuild topology and rerun SWMM after customer revision"),
    "客户 dtm_5M.tif": ("Customer dtm_5M.tif", "Customer-provided", "5", "Local diagnostic / historical replay", "Rerun citywide ANUGA after coverage and datum admission"),
    "客户 AUH_DTM_5m_Z40": ("Customer AUH_DTM_5m_Z40", "Customer-provided", "5", "Citywide return-period and historical replay", "Rerun the same SWMM → ANUGA chain after customer elevation, coverage or vertical-datum revision"),
    "Zone B DDF 设计暴雨": ("Zone B DDF design storm", "Public design reference", "time series", "Prototype forcing", "Replace with customer IDF/hyetograph and rerun SWMM"),
    "Open-Meteo / NCEI 降雨约束": ("Open-Meteo / NCEI rainfall constraint", "Public weather reference", "station / time series", "Prototype forcing", "Replace with customer radar/QPE or gauges and rerun SWMM"),
    "Copernicus DEM GLO-30": ("Copernicus DEM GLO-30", "ESA public product", "30", "2D fallback when customer result is unavailable", "Use only when the selected customer 5 m DTM result is missing; rerun ANUGA from the customer result when available"),
    "ESA WorldCover 陆海掩膜": ("ESA WorldCover land/water mask", "ESA public product", "10", "Water exclusion and coverage protection", "Replace with customer coastline/water boundary and rerun 2D"),
    "SWMM / ANUGA / GWM 派生结果": ("SWMM / ANUGA / GWM derived results", "System execution receipt", "model grid", "Dependent on upstream evidence", "Rerun the chain when upstream inputs change"),
}

_ACTIVE_EN = {
    "客户 AUH_DTM_5m_Z40（客户 5 m DTM）": "Customer AUH_DTM_5m_Z40 (customer 5 m DTM)",
    "ESA WorldCover 陆海掩膜": "ESA WorldCover land/water mask",
    "Copernicus DEM GLO-30": "Copernicus DEM GLO-30",
    "客户 dtm_5M.tif（若运行局部/历史二维链路）": "Customer dtm_5M.tif (when using the local/historical 2D chain)",
    "2024 年 4 月事件雨型/公开证据约束": "April 2024 event forcing / public evidence constraint",
    "SWMM → ANUGA 模型派生结果": "SWMM → ANUGA derived results",
    "所选阶段 3 二维结果（继承其客户 DTM 或公共 DEM 来源）": "Selected phase-3 2D result (inherits customer DTM or public DEM source)",
    "GWM rollout 派生状态": "GWM rollout derived state",
    "SWMM / ANUGA 派生交换量": "SWMM / ANUGA derived exchange volume",
    "Zone B DDF 设计暴雨 / Open-Meteo / NCEI（按情景选择）": "Zone B DDF / Open-Meteo / NCEI (selected by scenario)",
}


def _historical_payload() -> dict[str, Any]:
    from .abu_dhabi_flood_validation_service import historical_replay_report_payload

    payload = historical_replay_report_payload()
    payload["data_sources"] = data_source_matrix()
    payload["active_data_sources"] = [
        "客户雨水管线、节点和设施 GDB",
        "客户 dtm_5M.tif",
        "2024 年 4 月事件雨型/公开证据约束",
        "SWMM → ANUGA 模型派生结果",
    ]
    payload["decision_support"] = _decision_support("historical_replay", payload.get("results") or {}, payload.get("surface_product") and {"surface_evidence_class": "customer_authoritative"} or {})
    return payload


def simulation_report_payload(report_type: str, run_id: str | None = None, return_period_years: int | None = None) -> dict[str, Any]:
    """Return a path-safe report payload for one of the five simulation types."""

    if report_type not in REPORT_TYPES:
        raise ValueError("report_type_invalid")
    if report_type == "historical_replay":
        return _historical_payload()
    if report_type == "data_admission":
        return {
            "schema": "gwm.abu_dhabi_flood.simulation_report.v1",
            "report_type": report_type,
            "title": "Abu Dhabi flood model data and admission report",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_sources": data_source_matrix(),
            "active_data_sources": ["客户雨水管线、节点和设施 GDB", "客户 dtm_5M.tif", "Zone B DDF 设计暴雨", "Open-Meteo / NCEI 降雨约束"],
            "model_chain": ["Data admission", "EPA SWMM", "ANUGA 2D", "GWM rollout", "Validation and delivery"],
            "results": {},
            "decision_support": {"priority_actions": [{"problem": "需要完成权威数据准入", "evidence": ["客户数据回执和字段覆盖待确认"], "recommended_action": "先完成 DTM、雨型、潮位/泵站和观测回执，再按同一结果契约重跑。", "priority": "高", "expected_effect": "提高模型可解释性和工程准入等级。", "verification_run": "数据预检 → SWMM → ANUGA", "evidence_status": "待客户回执"}], "hotspots": [], "alternatives": [], "recommended_next_runs": ["数据预检 → SWMM → ANUGA"]},
            "quality_and_evidence": {"status": "input_admission_pending"},
        }
    metadata: dict[str, Any] = {}
    results: dict[str, Any] = {}
    title = "Abu Dhabi flood simulation report"
    assets: list[dict[str, Any]] = []
    if report_type == "design_storm":
        try:
            from .abu_dhabi_flood_scenario_service import latest_zone_b_design_storm_batch
            batch = latest_zone_b_design_storm_batch()
            rows = batch.get("runs") or []
            depths = [_number((row.get("hydraulic_summary") or {}).get("max_node_depth_m"), _number((row.get("node_summary") or {}).get("max_depth_m"))) for row in rows if isinstance(row, dict)]
            results = {"scenario_count": len(rows), "maximum_depth_m": max(depths, default=0.0), "return_periods": [row.get("return_period_years") for row in rows]}
            metadata = {"surface_evidence_class": "customer_authoritative", "forcing_source": "Zone B DDF public_reference"}
            title = "Abu Dhabi design-storm simulation report"
            assets = [{"name": "design storm batch receipt", "kind": "model_derived"}]
        except (KeyError, ImportError, ModuleNotFoundError) as error:
            results, metadata, title = _pending_report_results(report_type, str(error))
    elif report_type == "swmm_scenario":
        try:
            from .abu_dhabi_flood_scenario_service import latest_completed_run, public_run
            run = public_run(run_id) if run_id else latest_completed_run()
            metadata = {"run_id": run.get("run_id"), "forcing_source": (run.get("scenario") or {}).get("rainfall_source"), "surface_evidence_class": "customer_authoritative"}
            summary = run.get("summary") or {}
            results = {**summary, "maximum_depth_m": _number(summary.get("max_node_depth_m"), _number(summary.get("maximum_depth_m"))), "node_flooding_partition_count": summary.get("node_flooding_partition_count")}
            title = "Abu Dhabi EPA SWMM scenario report"
        except (KeyError, ValueError, ImportError, ModuleNotFoundError) as error:
            results, metadata, title = _pending_report_results(report_type, str(error))
    elif report_type == "citywide_2d":
        try:
            from .abu_dhabi_flood_scenario_service import public_citywide_2d_bootstrap_payload
            payload = public_citywide_2d_bootstrap_payload(return_period_years)
            metadata = dict(payload.get("metadata") or {})
            results = {key: metadata.get(key) for key in ("maximum_depth_m", "inundated_area_ge_0_01m2", "inundated_area_ge_0_05m2")}
            surface_label = "customer 5 m DTM" if metadata.get("surface_source_class") == "customer_authoritative" else "Copernicus DEM GLO-30 public proxy"
            title = f"Abu Dhabi citywide 2D simulation report ({metadata.get('return_period_years', return_period_years or 100)}-year; {surface_label})"
        except (ValueError, ImportError, ModuleNotFoundError) as error:
            results, metadata, title = _pending_report_results(report_type, str(error))
    elif report_type == "gwm_rollout":
        if not run_id:
            raise ValueError("run_id_required")
        from .abu_dhabi_flood_gwm_service import public_run

        run = public_run(run_id)
        metadata = dict(run.get("metadata") or {})
        results = dict(run.get("metrics") or {})
        metadata["run_id"] = run.get("run_id")
        title = "Abu Dhabi GWM rapid rollout decision-screening report"
    # Report active sources must describe the selected result, rather than a
    # stale hard-coded public DEM.  The source register above remains a
    # complete catalogue; this list is the evidence actually used by this
    # report instance.
    citywide_metadata = metadata if report_type == "citywide_2d" else {}
    citywide_customer_dtm = citywide_metadata.get("surface_source_class") == "customer_authoritative"
    citywide_sources = (
        ["客户 AUH_DTM_5m_Z40（客户 5 m DTM）", "ESA WorldCover 陆海掩膜", "SWMM / ANUGA 派生交换量"]
        if citywide_customer_dtm
        else ["Copernicus DEM GLO-30", "ESA WorldCover 陆海掩膜", "SWMM / ANUGA 派生交换量"]
    )
    active_sources = {
        "design_storm": ["客户雨水管线、节点和设施 GDB", "Zone B DDF 设计暴雨"],
        "swmm_scenario": ["客户雨水管线、节点和设施 GDB", "Zone B DDF 设计暴雨 / Open-Meteo / NCEI（按情景选择）"],
        "citywide_2d": citywide_sources,
        "gwm_rollout": ["所选阶段 3 二维结果（继承其客户 DTM 或公共 DEM 来源）", "GWM rollout 派生状态"],
    }.get(report_type, [])
    payload = {
        "schema": "gwm.abu_dhabi_flood.simulation_report.v1",
        "report_type": report_type,
        "title": title,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": metadata.get("run_id") or run_id,
        "data_sources": data_source_matrix(),
        "active_data_sources": active_sources,
        "model_chain": ["Data admission", "EPA SWMM", "ANUGA 2D", "GWM rollout", "Validation and delivery"],
        "results": results,
        "decision_support": _decision_support(report_type, results, metadata),
        "quality_and_evidence": {"surface_evidence_class": metadata.get("surface_evidence_class", "model_derived"), "forcing_source": metadata.get("forcing_source"), "claim_boundary": "结论用于方案筛选；工程实施前必须用客户权威输入复核。"},
        "assets": assets,
    }
    return payload


def simulation_report_html(report_type: str, language: str | None = None, run_id: str | None = None, return_period_years: int | None = None) -> str:
    zh = (language or "en").lower().startswith("zh")
    report = simulation_report_payload(report_type, run_id, return_period_years)
    t = {
        "eyebrow": "城市暴雨内涝世界模型 / 决策支持报告" if zh else "URBAN PLUVIAL FLOOD WORLD MODEL / DECISION SUPPORT REPORT",
        "what": "关键结果" if zh else "Key results",
        "how": "怎么做：行动建议" if zh else "How to act: recommended actions",
        "sources": "数据来源与证据等级" if zh else "Data sources and evidence",
        "chain": "模型链路" if zh else "Model chain",
        "boundary": "解释边界" if zh else "Interpretation boundary",
        "priority": "优先级" if zh else "Priority",
        "evidence": "证据" if zh else "Evidence",
        "action": "建议动作" if zh else "Recommended action",
        "effect": "预期改善" if zh else "Expected effect",
        "rerun": "复核方式" if zh else "Verification run",
    }
    colon = "：" if zh else ": "
    result_rows = "".join(f"<tr><td>{escape(str(k))}</td><td>{escape(str(v))}</td></tr>" for k, v in (report.get("results") or {}).items() if v is not None)
    actions = report.get("decision_support", {}).get("priority_actions") or []
    if not zh:
        actions = _english_actions(report_type, report.get("results") or {})
    action_cards = "".join(
        f"<article class='action'><div class='priority'>{escape(str(a.get('priority', '—')))}</div><h3>{escape(str(a.get('problem', '')))}</h3><p><b>{escape(t['evidence'])}{colon}</b>{escape('; '.join(map(str, a.get('evidence', []))))}</p><p><b>{escape(t['action'])}{colon}</b>{escape(str(a.get('recommended_action', '')))}</p><p><b>{escape(t['effect'])}{colon}</b>{escape(str(a.get('expected_effect', '')))}</p><p><b>{escape(t['rerun'])}{colon}</b>{escape(str(a.get('verification_run', '')))}</p><small>{escape(str(a.get('evidence_status', '')))}</small></article>"
        for a in actions
    )
    def source_cell(source: dict[str, Any]) -> tuple[str, str, str, str, str]:
        if zh:
            return tuple(str(source.get(key, "")) for key in ("name", "source_class", "authority", "evidence_class", "replacement_rule"))
        translated = _SOURCE_EN.get(str(source.get("name")))
        if translated:
            return (translated[0], str(source.get("source_class", "")), translated[1], translated[3], translated[4])
        return tuple(str(source.get(key, "")) for key in ("name", "source_class", "authority", "evidence_class", "replacement_rule"))
    source_rows = "".join(f"<tr><td>{escape(cells[0])}</td><td>{escape(cells[1])}</td><td>{escape(cells[2])}</td><td>{escape(cells[3])}</td><td>{escape(cells[4])}</td></tr>" for source in report.get("data_sources", []) for cells in [source_cell(source)])
    active_sources = report.get("active_data_sources") or []
    if zh:
        active_text = "；".join(map(str, active_sources))
    else:
        active_text = "; ".join(_ACTIVE_EN.get(str(item), _SOURCE_EN.get(str(item), (str(item),))[0]) for item in active_sources)
    active_label = "本次报告实际使用的输入" if zh else "Inputs used by this report"
    font_stack = "Arial,'PingFang SC','Microsoft YaHei',sans-serif" if zh else "Arial,sans-serif"
    empty_result = "暂无数值结果；本报告用于数据准入和行动准备。" if zh else "No numeric result; this report records data admission and action preparation."
    no_action = "暂无行动卡。" if zh else "No action card is available."
    not_available = "暂无" if zh else "Not available"
    source_name = "名称" if zh else "Source"
    authority = "权威性" if zh else "Authority"
    evidence = "证据等级" if zh else "Evidence"
    replacement = "客户数据到达后的替换规则" if zh else "Replacement rule"
    boundary = "代理指标用于筛选，工程实施前需复核。" if zh else "Proxy indicators are for screening; engineering decisions require physical-model review."
    model_chain = report.get('model_chain', [])
    if not zh:
        model_chain = ['Data admission', 'EPA SWMM', 'ANUGA 2D', 'GWM rollout', 'Validation and delivery']
    report_boundary = str((report.get('quality_and_evidence') or {}).get('claim_boundary') or '')
    if not zh and any("\u3400" <= char <= "\u9fff" for char in report_boundary):
        report_boundary = boundary
    return f"""<!doctype html><html lang='{'zh-CN' if zh else 'en'}'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>{escape(str(report['title']))}</title><style>body{{margin:0;background:#eef4f7;color:#18324a;font:14px/1.55 {font_stack}}}main{{max-width:1120px;margin:auto;background:white;padding:38px}}h1{{font-size:30px;line-height:1.2;margin:8px 0 10px}}h2{{margin-top:30px;border-bottom:2px solid #0f87a8;padding-bottom:7px}}.eyebrow{{color:#0f87a8;font-weight:bold;letter-spacing:.08em;font-size:11px}}.meta{{color:#587083;font-family:monospace;font-size:12px}}table{{border-collapse:collapse;width:100%}}td,th{{padding:8px;border-bottom:1px solid #d9e4ea;text-align:left;vertical-align:top}}.actions{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}}.action{{border:1px solid #ccdce5;border-left:5px solid #0f87a8;padding:14px;background:#fbfdfe}}.priority{{font-weight:bold;color:#b45309}}.action small{{color:#587083}}.notice{{padding:14px;background:#fff8e6;border-left:4px solid #d97706}}.active{{padding:14px;background:#eff8fb;border:1px solid #abd6e3}}@media(max-width:700px){{main{{padding:20px}}td,th{{font-size:12px}}}}</style></head><body><main><div class='eyebrow'>{escape(t['eyebrow'])}</div><h1>{escape(str(report['title']))}</h1><div class='meta'>run_id: {escape(str(report.get('run_id') or 'catalog'))} · {escape(str(report.get('generated_at')))}</div><h2>{escape(t['what'])}</h2><table><tbody>{result_rows or f"<tr><td colspan='2'>{empty_result}</td></tr>"}</tbody></table><h2>{escape(active_label)}</h2><div class='active'>{escape(active_text or not_available)}</div><h2>{escape(t['how'])}</h2><section class='actions'>{action_cards or f"<p>{no_action}</p>"}</section><h2>{escape(t['chain'])}</h2><p>{escape(' → '.join(map(str, model_chain)))}</p><h2>{escape(t['sources'])}</h2><table><thead><tr><th>{source_name}</th><th>source_class</th><th>{authority}</th><th>{evidence}</th><th>{replacement}</th></tr></thead><tbody>{source_rows}</tbody></table><h2>{escape(t['boundary'])}</h2><div class='notice'>{escape(report_boundary or boundary)}</div></main></body></html>"""
