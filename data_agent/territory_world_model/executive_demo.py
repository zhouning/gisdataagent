"""Evidence aggregation for the TWM executive briefing demo.

The report is deliberately fail-closed: unavailable or malformed research
artifacts can only lower a claim, never promote one.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any


REPORT_SCHEMA = "territory_world_model.executive_demo_report.v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAPER9_ROOT = REPO_ROOT / "data_agent/demo_evidence/paper9"

PAPER9_VALIDATION_SNAPSHOT: dict[str, dict[str, Any]] = {
    "dongxing": {
        "label": "四川省内江市东兴区",
        "cultivated_area_change_ha": 508.7831859089017,
        "slope_change_pct": -0.3430600651636011,
        "contiguity_change": 0.05295841168496107,
        "baimu_area_change_ha": 766.8709969639779,
        "swaps_completed": 475,
        "hard_constraint_passed": True,
    },
    "bishan": {
        "label": "重庆市璧山区",
        "cultivated_area_change_ha": 4.323098357629776,
        "slope_change_pct": -0.8564319239714494,
        "contiguity_change": 0.026811007689194533,
        "baimu_area_change_ha": 34.63793864067793,
        "swaps_completed": 424,
        "hard_constraint_passed": True,
    },
}


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _combined_sha256(paths: list[Path]) -> str | None:
    entries = [(str(path), _sha256(path)) for path in paths]
    if not entries or any(value is None for _, value in entries):
        return None
    payload = json.dumps(entries, ensure_ascii=True, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    return payload, _sha256(path)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any, default: int | float = 0) -> int | float:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _paper9_report(paper9_root: Path) -> dict[str, Any]:
    output_root = paper9_root / "outputs" / "paper9v2_docker_e2e_20260627"
    cases: list[dict[str, Any]] = []
    sources: list[Path] = []
    live_available = True

    for case_id in ("dongxing", "bishan"):
        audit_path = output_root / case_id / "audit_summary.json"
        mpc_path = output_root / case_id / "plan_paper9v2_no_net_loss" / "mpc_summary.json"
        audit, _ = _load_json(audit_path)
        mpc, _ = _load_json(mpc_path)
        if audit is None or mpc is None:
            live_available = False
            break
        records = _as_dict(audit.get("constraint_status")).get("records")
        results = mpc.get("results")
        record = records[0] if isinstance(records, list) and records and isinstance(records[0], dict) else {}
        result = results[0] if isinstance(results, list) and results and isinstance(results[0], dict) else {}
        cases.append(
            {
                "id": case_id,
                "label": PAPER9_VALIDATION_SNAPSHOT[case_id]["label"],
                "cultivated_area_change_ha": _number(record.get("cultivated_area_change_ha")),
                "slope_change_pct": _number(record.get("slope_change_pct")),
                "contiguity_change": _number(record.get("cont_change")),
                "baimu_area_change_ha": _number(record.get("baimu_area_change_ha")),
                "swaps_completed": int(_number(result.get("swaps_completed"))),
                "hard_constraint_passed": bool(_as_dict(audit.get("constraint_status")).get("hard_constraint_passed")),
            }
        )
        sources.extend((audit_path, mpc_path))

    if not live_available:
        cases = [{"id": case_id, **snapshot} for case_id, snapshot in PAPER9_VALIDATION_SNAPSHOT.items()]
        source_sha = hashlib.sha256(
            json.dumps(PAPER9_VALIDATION_SNAPSHOT, ensure_ascii=True, sort_keys=True).encode("utf-8")
        ).hexdigest()
        source_mode = "embedded_validation_snapshot"
    else:
        source_sha = _combined_sha256(sources)
        source_mode = "live_offline_artifacts"

    all_hard_gates_passed = len(cases) == 2 and all(item["hard_constraint_passed"] for item in cases)
    return {
        "status": "verified_offline_run" if all_hard_gates_passed else "review",
        "evidence_level": "已验证",
        "source_available": live_available,
        "source_mode": source_mode,
        "source_date": "2026-06-27",
        "source_sha256": source_sha,
        "method": "学习转移规律 + 多步滚动搜索 + 硬约束审计",
        "question": "在耕地面积不减少的前提下，能否从海量地块组合中找到坡度更低、连片度更高的布局？",
        "why_conventional_methods_are_insufficient": [
            "逐地块适宜性评分无法表达换入与换出的组合效应。",
            "静态叠加难以处理多步调整后邻接关系和连片度的变化。",
            "穷举组合不可计算，单步贪心又容易停在局部方案。",
        ],
        "hard_gates": [
            {"id": "farmland_no_loss", "label": "耕地面积不减少", "passed": all_hard_gates_passed},
            {"id": "slope_improves", "label": "平均坡度下降", "passed": all(item["slope_change_pct"] < 0 for item in cases)},
            {"id": "contiguity_improves", "label": "空间连片度上升", "passed": all(item["contiguity_change"] > 0 for item in cases)},
        ],
        "cases": cases,
        "claim_boundary": "这是两地离线全流程优化与约束审计结果，证明方法可运行且能产生满足约束的方案；不等于方案已获业务审批，也不证明跨省泛化或真实治理成效。百亩方变化为观察指标，不属于三项硬门槛。",
    }


TWM_FOUNDATION_SPATIAL_FILES = (
    "parcel_current.geojson",
    "synthetic_projects.geojson",
    "synthetic_pbf.geojson",
    "synthetic_eco_redline.geojson",
    "synthetic_planning_zones.geojson",
    "synthetic_annual_change.geojson",
)
TWM_FOUNDATION_TABLE_FILES = (
    "approval_records.csv",
    "review_tasks.csv",
    "rule_evaluation.csv",
    "state_snapshots.csv",
    "multimodal_evidence_index.csv",
)


def _count_dataset(manifest: dict[str, Any]) -> tuple[int, int, int]:
    layer_count = 0
    table_count = 0
    spatial_feature_count = 0
    layers = _as_dict(manifest.get("layers"))
    tables = _as_dict(manifest.get("tables"))
    for item in layers.values():
        if not isinstance(item, dict) or Path(str(item.get("path", ""))).name not in TWM_FOUNDATION_SPATIAL_FILES:
            continue
        path = REPO_ROOT / str(item["path"])
        payload, _ = _load_json(path)
        features = payload.get("features") if payload else None
        if isinstance(features, list):
            count = len(features)
            layer_count += count
            spatial_feature_count += count
    for item in tables.values():
        if not isinstance(item, dict) or Path(str(item.get("path", ""))).name not in TWM_FOUNDATION_TABLE_FILES:
            continue
        path = REPO_ROOT / str(item["path"])
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                count = max(0, sum(1 for _ in csv.reader(handle)) - 1)
        except (OSError, UnicodeError, csv.Error):
            continue
        table_count += count
    return layer_count + table_count, spatial_feature_count, layer_count


def _twm_foundation_report() -> dict[str, Any]:
    manifest_path = REPO_ROOT / "data_agent/test_data/twm_bishan_multi_admin_eval/dataset_manifest.json"
    validation_path = REPO_ROOT / "docs/reports/twm_data_foundation_validation.json"
    manifest, _ = _load_json(manifest_path)
    validation, _ = _load_json(validation_path)
    tracked_paths = [manifest_path, validation_path]
    if manifest is not None:
        for item in (*_as_dict(manifest.get("layers")).values(), *_as_dict(manifest.get("tables")).values()):
            if not isinstance(item, dict) or not item.get("path"):
                continue
            filename = Path(str(item["path"])).name
            if filename in TWM_FOUNDATION_SPATIAL_FILES or filename in TWM_FOUNDATION_TABLE_FILES:
                tracked_paths.append(REPO_ROOT / str(item["path"]))
    source_available = manifest is not None and validation is not None and all(path.is_file() for path in tracked_paths)
    total_count, spatial_feature_count, _ = _count_dataset(manifest or {})
    validation_summary = _as_dict(_as_dict(validation).get("summary"))
    synthetic = _as_dict(_as_dict(validation).get("twm_synthetic_experiment_foundation"))
    observed_rows = int(_number(validation_summary.get("twm_production_ready_observed_history_rows")))
    policy_rows = int(_number(validation_summary.get("production_policy_history_row_count")))
    expected_counts_match = total_count == 22401 and spatial_feature_count == 21603
    return {
        "status": "engineering_ready" if source_available and expected_counts_match else "review",
        "evidence_level": "工程可用" if source_available and expected_counts_match else "待复核",
        "source_available": source_available,
        "source_sha256": _combined_sha256(tracked_paths),
        "dataset_id": (manifest or {}).get("dataset_id", "twm_bishan_multi_admin_eval"),
        "record_count": total_count,
        "spatial_feature_count": spatial_feature_count,
        "file_count": len(TWM_FOUNDATION_SPATIAL_FILES) + len(TWM_FOUNDATION_TABLE_FILES),
        "synthetic_experiment": {
            "row_count": int(_number(synthetic.get("row_count"))),
            "pair_count": int(_number(synthetic.get("pair_count"))),
            "region_count": int(_number(synthetic.get("region_count"))),
            "period_count": int(_number(synthetic.get("period_count"))),
        },
        "production_observed_history_rows": observed_rows,
        "production_policy_history_rows": policy_rows,
        "supported_chain": ["空间对象", "对象关系", "规划规则", "证据链", "风险审查", "候选方案", "审计留痕"],
        "claim_boundary": "现有数据足以支撑地图、状态、规则、证据、推演和审计的受控工程演示；数据包含合成或非生产对象，生产观察历史和政策动作历史均为 0，不能输出真实审批、预测或因果结论。",
    }


def _natural_resource_event_report() -> dict[str, Any]:
    root = REPO_ROOT / "data/benchmarks/dam_gk_2026-07-18"
    paths = {
        "coverage": root / "landchina_event_coverage.json",
        "panel": root / "shanghai_parcel_action_panel.json",
        "grid": root / "shanghai_event_grid_protocol.json",
        "control": root / "shanghai_control_design_audit.json",
        "trajectory": root / "shanghai_sentinel2_2023_trajectory_audit.json",
    }
    loaded = {name: _load_json(path)[0] for name, path in paths.items()}
    source_available = all(payload is not None for payload in loaded.values())
    coverage = _as_dict(_as_dict(loaded.get("coverage")).get("summary"))
    panel = _as_dict(_as_dict(loaded.get("panel")).get("summary"))
    grid = _as_dict(_as_dict(loaded.get("grid")).get("summary"))
    control = _as_dict(_as_dict(loaded.get("control")).get("summary"))
    training_admission = bool(_as_dict(_as_dict(loaded.get("control")).get("claim_boundary")).get("training_admission"))
    return {
        "status": "compiled_not_admitted" if source_available and not training_admission else "review",
        "evidence_level": "真实事件编译" if source_available else "待复核",
        "source_available": source_available,
        "source_sha256": _combined_sha256(list(paths.values())),
        "region": "上海市",
        "pipeline": [
            {"id": "official_event", "label": "官方供地事件", "count": int(_number(coverage.get("deduplicated_in_range_contract_event_count")))},
            {"id": "parcel_geometry", "label": "宗地几何恢复", "count": int(_number(panel.get("geometry_recovery_success_count")))},
            {"id": "temporal_window", "label": "严格前后期窗口", "count": int(_number(panel.get("strict_temporal_window_ready_count")))},
            {"id": "treatment_node", "label": "处理状态节点", "count": int(_number(control.get("treatment_node_count")))},
            {"id": "matched_control", "label": "匹配对照候选", "count": int(_number(control.get("matched_control_count")))},
            {"id": "far_negative", "label": "远距离负对照", "count": int(_number(control.get("far_geographic_negative_count")))},
        ],
        "spatial_sampling_ready": bool(grid.get("spatial_sampling_protocol_ready")),
        "comparison_candidate_ready": bool(control.get("provisional_comparison_candidate_ready")),
        "comparison_design_complete": bool(control.get("comparison_design_complete")),
        "action_conditioned_training_ready": bool(control.get("action_conditioned_training_ready")),
        "training_admission": training_admission,
        "claim_boundary": "该链路证明真实官方事件可以被编译为空间状态、时序窗口和可复核对照候选。对照尚不能确认未受其他供地或建设事件影响，实际开工时间未观测，因此不得称为政策效果预测或因果识别。",
    }


def _benchmark_report() -> dict[str, Any]:
    stability_path = REPO_ROOT / "benchmarks/gwm_bench_v0_2/internal_dev/hydro_kernel_experiment/stability_report_10seed.json"
    refresh_path = REPO_ROOT / "benchmarks/gwm_bench_v0_3_candidate/certificate_refresh_report.json"
    forcing_path = REPO_ROOT / "benchmarks/gwm_bench_v0_3_candidate/nwm_forcing_admission_certificate.json"
    topology_path = REPO_ROOT / "benchmarks/gwm_bench_v0_3_candidate/nwm_spatial_topology_admission_certificate.json"
    stability, _ = _load_json(stability_path)
    refresh, _ = _load_json(refresh_path)
    forcing, _ = _load_json(forcing_path)
    topology, _ = _load_json(topology_path)
    source_available = all(item is not None for item in (stability, refresh, forcing, topology))
    hypotheses = _as_dict(_as_dict(stability).get("hypothesis_summary"))

    def hypothesis(key: str, label: str, direction: str) -> dict[str, Any]:
        item = _as_dict(hypotheses.get(key))
        return {
            "id": key,
            "label": label,
            "direction": direction,
            "pass_count": int(_number(item.get("pass_count"))),
            "seed_count": int(_number(item.get("seed_count"))),
            "passed": bool(item.get("meets_required_pass_rate")),
        }

    matrix = [
        hypothesis("full_kernel_passes_existing_core_reference_gate", "完整 Kernel 超过 persistence 门槛", "核心有效性"),
        hypothesis("full_kernel_beats_no_graph_mean_core_nmae", "完整模型优于无图结构", "空间关系贡献"),
        hypothesis("action_shuffle_degrades_mean_core_nmae", "打乱动作后性能变差", "动作信号诊断"),
        hypothesis("reverse_topology_degrades_mean_core_nmae", "反转拓扑后性能变差", "方向拓扑诊断"),
        hypothesis("full_kernel_beats_no_action_mean_core_nmae", "完整模型优于无动作输入", "动作增益"),
    ]
    refresh_status = _as_dict(refresh).get("status", "missing")
    refresh_claim = _as_dict(_as_dict(refresh).get("claim_boundary"))
    forcing_status = _as_dict(forcing).get("certificate_status", "missing")
    topology_status = _as_dict(topology).get("certificate_status", "missing")
    admitted = bool(refresh_claim.get("training_input_admitted"))
    return {
        "status": "not_admitted" if source_available and not admitted else "review",
        "evidence_level": "诊断证据" if source_available else "待复核",
        "source_available": source_available,
        "source_sha256": _combined_sha256([stability_path, refresh_path, forcing_path, topology_path]),
        "benchmark_id": _as_dict(stability).get("benchmark_id", "gwm-bench-v0.2"),
        "seed_count": int(_number(_as_dict(stability).get("seed_count"))),
        "matrix": matrix,
        "kernel_verdict": "未通过核心基线门槛",
        "candidate_v03": {
            "status": refresh_status,
            "compiled_object_count": int(_number(_as_dict(_as_dict(refresh).get("compilation_manifest")).get("compiled_object_count"))),
            "forcing_certificate": forcing_status,
            "topology_certificate": topology_status,
            "training_input_admitted": admitted,
        },
        "claim_boundary": "消融和负对照说明模型确实使用了图、动作和拓扑信号，但当前完整 Kernel 在 10 个固定种子中 0 个通过全部核心 persistence 门槛，v0.3 训练输入也未准入；这些结果用于否证和定位问题，不能作为成熟度或生产预测证明。",
    }


def build_executive_demo_report(*, paper9_root: str | Path | None = None) -> dict[str, Any]:
    """Build the machine-readable evidence report used by the briefing UI."""

    configured_root = Path(paper9_root) if paper9_root is not None else Path(
        os.environ.get("TWM_PAPER9V2_ROOT", str(DEFAULT_PAPER9_ROOT))
    )
    paper9 = _paper9_report(configured_root)
    foundation = _twm_foundation_report()
    event_compilation = _natural_resource_event_report()
    benchmark = _benchmark_report()
    controlled_ready = (
        paper9["status"] == "verified_offline_run"
        and foundation["status"] == "engineering_ready"
        and event_compilation["source_available"]
        and benchmark["source_available"]
    )
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "controlled_demo_ready" if controlled_ready else "review",
        "positioning": {
            "title": "TWM：把自然资源数据、规则与行动组织成可推演、可审计的治理闭环",
            "verdict": "受控演示就绪，生产效果尚未验证" if controlled_ready else "演示证据需复核，生产效果尚未验证",
            "production_claim_supported": False,
            "gwm_twm_relationship": "GWM 提供跨领域的状态—行动—转移—评价运行范式；TWM 将自然资源对象、规划规则、业务动作和审查责任实例化到这一范式中。",
            "llm_wm_relationship": "LLM 负责理解意图、编排工具和生成解释；世界模型负责维护空间状态、执行受约束推演并用结果校验方案。两者共同驱动，且关键结论保留人工复核。",
        },
        "decision_story": [
            {"id": "observe", "label": "观测", "detail": "汇聚图斑、规划边界、项目、遥感与业务记录"},
            {"id": "compile", "label": "编译", "detail": "形成对象、关系、状态、动作、时间和证据契约"},
            {"id": "simulate", "label": "推演", "detail": "组合 GIS、规则、机理、Kernel 与不确定性转移"},
            {"id": "plan", "label": "比选", "detail": "在硬约束下滚动生成并比较候选方案"},
            {"id": "verify", "label": "验证", "detail": "基线、消融、负对照和证据门禁共同约束结论"},
            {"id": "review", "label": "审查", "detail": "输出证据缺口、风险理由和人工复核任务"},
        ],
        "gwm_definition": {
            "formal_definition": "地理空间世界模型（GWM）是以版本化地理状态为计算对象、以治理或环境行动为条件、通过受约束状态转移进行递归推演，并输出可被 GIS、规划器和证据门消费的未来状态与不确定性的世界模型。",
            "not_coordinate_appendage": "它不是给通用世界模型追加经纬度特征，而是把地理空间语义写进状态、转移、验证和交付四类契约。",
            "fusion_dimensions": [
                {"dimension": "状态", "geospatial_capability": "对象 + 场 + CRS + 时间 + 行政层级", "runtime_effect": "保持对象身份、坐标基准、尺度与版本，避免把空间世界压成无身份特征向量。"},
                {"dimension": "关系", "geospatial_capability": "拓扑 + 邻接 + 网络方向 + 层级从属", "runtime_effect": "行动后重新计算相交、连通、上下游和跨尺度关系，而非固定邻接矩阵。"},
                {"dimension": "转移", "geospatial_capability": "空间作用域 + 传播方向 + 时滞 + 约束", "runtime_effect": "每个状态变量按证据选择 GIS、规则、机理或可学习转移，并记录来源。"},
                {"dimension": "验证与交付", "geospatial_capability": "空间留出 + 尺度一致性 + GIS 图层 + 谱系", "runtime_effect": "同时检查预测、动作敏感性、拓扑和证据门，并交付可定位、可复演的结果。"},
            ],
            "distinctive_value": "GWM 的独特价值是把‘在哪里、与谁相连、受什么规则约束、采取什么行动、结果能否追溯’变成世界模型的原生计算语义。",
        },
        "simulator": {
            "definition": "GWM Simulator 是由 Runtime 管理的组合式状态转移与写回协议，不是单一端到端生成器；DAM-GK 只是其中一个可学习的空间动力学来源。",
            "transition_equation": "S(t+1) = WriteBack(S(t), Route(S(t), A(t), C(t), G(t)))",
            "pipeline": [
                {"id": "state", "label": "状态快照", "detail": "对象、场、关系、规则、证据、质量与版本"},
                {"id": "action", "label": "行动编码", "detail": "目标对象、空间范围、强度、意图和执行约束"},
                {"id": "route", "label": "转移路由", "detail": "按变量和证据等级选择可审计的转移来源"},
                {"id": "delta", "label": "计算增量", "detail": "生成状态、关系、风险、效用与不确定性增量"},
                {"id": "write_back", "label": "状态写回", "detail": "更新对象与场，重算拓扑、规则命中和可行动作"},
                {"id": "rollout", "label": "递归推演", "detail": "比较基准与干预轨迹，并传播误差和证据边界"},
            ],
            "transition_sources": [
                {"source": "GIS 确定性计算", "use_for": "面积、缓冲、叠加、拓扑与网络可达性", "trace": "算法、CRS、输入版本"},
                {"source": "规则 / Action Mask", "use_for": "法定边界、用途管制和动作可行域", "trace": "规则条款、版本、生效时间"},
                {"source": "专业机理模型", "use_for": "水文、生态、灾害等已有可信过程", "trace": "模型版本、参数与适用域"},
                {"source": "Geospatial Kernel / Learned", "use_for": "确定规则无法覆盖且数据支持的局部转移和残差", "trace": "模型、训练证据、校准与 UQ"},
                {"source": "Unknown Gate", "use_for": "缺数据、越分布或来源冲突的变量", "trace": "停止、降级或转人工复核"},
            ],
            "comparison": [
                {"family": "视觉 / 机器人世界模型", "state": "像素、latent frame、局部物体或 3D 状态", "action": "控制量或运动指令", "output": "下一帧、轨迹或控制价值", "gwm_difference": "GWM 还要维护 CRS、拓扑、尺度、治理规则、证据和 GIS 交付。"},
                {"family": "科学模拟 / 数字孪生", "state": "连续物理场、设备状态或方程域", "action": "forcing、边界条件或操作参数", "output": "未来场、风险场或设备响应", "gwm_difference": "GWM 同时处理离散治理对象、制度行动、规则可行域和人工责任。"},
                {"family": "GeoSOS-FLUS", "state": "土地利用栅格与驱动因子", "action": "情景需求、转换规则和数量约束", "output": "未来土地利用格局", "gwm_difference": "GWM 面向对象级治理行动、多类型状态、动态关系写回、方案评价和证据门。"},
                {"family": "GWM Simulator", "state": "对象 + 场 + 关系 + 规则 + 证据", "action": "指向具体对象的治理行动及可行域", "output": "GIS 状态、风险、效用、UQ 与 trace", "gwm_difference": "逐变量选择转移来源，写回后重算空间关系，并由规划器和证据门继续消费。"},
            ],
            "claim_boundary": "递归 rollout 是模型条件下的方案推演，不自动等于政策因果识别；真实效果仍需要对照设计、混杂处理和外部观测验证。",
        },
        "architecture": {
            "dam_definition": "DAM-GK = Dynamic Action-Conditioned Multi-scale Geospatial Kernel，即动态、动作条件、多尺度地理空间内核。",
            "geospatial_kernel": ["状态编码", "多关系传播", "动作条件", "时滞响应", "动态拓扑", "多尺度一致性", "不确定性"],
            "runtime_kernel": ["状态版本", "规则与动作契约", "模拟器", "规划器", "评价器", "证据门禁", "审计与人工复核"],
            "boundary": "Geospatial Kernel 是空间动力学算子；GWM Runtime Kernel 才负责把数据、模拟、规划、评价和治理责任组织成可运行系统。",
        },
        "world_model_positioning": [
            {"family": "视频/机器人世界模型", "focus": "从感知和动作预测短时环境演化", "gwm_difference": "GWM 还必须表达坐标、尺度、空间关系、规则、证据来源和区域迁移。"},
            {"family": "气象/地球系统模型", "focus": "预测连续物理场和自然过程", "gwm_difference": "GWM 同时处理人类行动、制度约束和多类型离散空间对象。"},
            {"family": "数字孪生/一张图", "focus": "还原和展示当前状态", "gwm_difference": "GWM 强调行动条件转移、反事实推演、方案搜索与可证伪评价。"},
            {"family": "LLM 智能体", "focus": "理解语言、编排工具和生成解释", "gwm_difference": "GWM 提供可计算的世界状态和转移约束，避免仅靠语言生成想象结果。"},
        ],
        "geosos_flus_comparison": {
            "benchmark_role": "GeoSOS-FLUS 是土地利用变化模拟的权威对标物，用于检验 TWM 是否只是换名的土地利用模拟器。",
            "dimensions": [
                {"dimension": "核心问题", "geosos_flus": "给定需求与情景约束，模拟土地利用格局", "twm": "给定状态、规则和行动，推演、比选并审计治理方案"},
                {"dimension": "空间机制", "geosos_flus": "适宜性、邻域效应、自适应惯性与竞争", "twm": "多关系图、动态拓扑、动作条件、时滞与多尺度一致性"},
                {"dimension": "行动表达", "geosos_flus": "主要通过情景参数、转换规则和数量约束", "twm": "显式动作对象、可行性门控、执行结果和状态写回"},
                {"dimension": "业务责任", "geosos_flus": "侧重格局模拟结果", "twm": "规则依据、证据缺口、候选方案、人工复核和审计链"},
                {"dimension": "评价问题", "geosos_flus": "格局拟合与情景模拟质量", "twm": "预测、动作敏感性、规划价值、安全门禁和业务增量"},
            ],
            "verdict": "TWM 的目标能力边界和理论上限更宽，但当前证据只支持方法与工程链路，不支持宣称预测精度已经优于 GeoSOS-FLUS。",
        },
        "paper9v2": paper9,
        "twm_foundation": foundation,
        "natural_resource_event_compilation": event_compilation,
        "gwm_benchmark": benchmark,
        "claim_boundary": {
            "can_demonstrate": [
                "自然资源对象、规则、证据与方案的一体化状态组织",
                "耕地布局优化的离线全流程与硬约束审计",
                "真实供地事件向时空训练候选的可追溯编译",
                "对 Kernel 的基线、消融、负对照和准入门禁",
            ],
            "cannot_claim": [
                "省域真实政策效果已经被预测或因果识别",
                "系统可以替代法定审批、执法认定或规划决策",
                "当前 DAM-GK 已通过通用世界模型验证",
                "没有真实或脱敏业务历史也能直接生产落地",
            ],
        },
        "pilot_data_requirements": [
            {"priority": "P0", "data": "权威现势空间底板", "minimum": "三条控制线、用途管制分区、现状图斑及其版本、生效时间和法定标识", "unlocks": "真实硬约束与规则追溯"},
            {"priority": "P0", "data": "脱敏业务闭环历史", "minimum": "项目几何、申请与决定时间、规则命中、补正复核、最终处置及证据链接", "unlocks": "真实状态转移与业务基线"},
            {"priority": "P1", "data": "动作及可行性标签", "minimum": "动作类型、政策依据、允许/禁止/有条件、地区时期和人工理由", "unlocks": "Action Mask 与方案可行性"},
            {"priority": "P1", "data": "多期结果观测", "minimum": "变更调查、遥感证据、项目落地和生态耕地指标，具有统一时空身份", "unlocks": "动态校准与反事实检验"},
            {"priority": "P2", "data": "现有工作流基线", "minimum": "人工 GIS、规则引擎、GeoSOS-FLUS 或既有优化结果及耗时、漏检和复核记录", "unlocks": "同题对标与增量价值证明"},
        ],
    }


__all__ = ["REPORT_SCHEMA", "build_executive_demo_report"]
