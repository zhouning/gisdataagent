from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlparse

from .models import (
    StateBuildResult,
    TerritoryWorldModelAction,
    TerritoryWorldModelForecast,
    TwmActionMaskReport,
    TwmAuditReport,
    TwmBeamPlanReport,
    TwmCausalCalibrationReport,
    TwmCounterfactualRollout,
    TwmDynamicsBackendReport,
    TwmDynamicsEvaluationReport,
    TwmDynamicsFitReport,
    TwmDynamicsModelRegistryEntry,
    TwmDynamicsReadinessReport,
    TwmDynamicsTrainingDataset,
    TwmDynamicsTrainingExample,
    TwmEvidenceItem,
    TwmGeoFMDownstreamExperimentReport,
    TwmGeoFMGateReport,
    TwmGeoFMGateVariant,
    TwmLayerBinding,
    TwmPolicyRule,
    TwmProject,
    TwmRelationSpec,
    TwmReviewTask,
    TwmRuleEvaluationResult,
    TwmRuleHit,
    TwmRuleSet,
    TwmScenario,
    TwmScenarioMetric,
    TwmScenarioPlan,
    TwmStateContractReport,
    TwmStateObject,
    TwmStateRelation,
    TwmStateVersion,
    TwmTrainDynamicsReport,
    TwmTrainingObjectiveReport,
    TwmValidationReport,
    TwmValidationStage,
    TwmWorldModelCapability,
    TwmWorldModelProfile,
    jsonable,
    now_utc_iso,
)
from .causal_calibration import estimate_observational_treatment_effect
from .claim_ladder import evaluate_claim_ladder
from .spatial_causal_estimator import SPATIAL_CAUSAL_ESTIMATOR_SCHEMA
from .neural_dynamics import (
    HIERARCHICAL_GRAPH_DYNAMICS_SCHEMA,
    NEURAL_DYNAMICS_SCHEMA,
    SPATIOTEMPORAL_TRANSFORMER_DYNAMICS_SCHEMA,
    train_hierarchical_graph_dynamics,
    train_neural_multi_head_dynamics,
    train_spatiotemporal_transformer_dynamics,
)
from .planner import TerritoryWorldModelPlanner
from .repository import TwmRepository, get_twm_repository
from .rule_evaluator import RuleEvaluator, evaluate_rules
from .state_builder import StateBuilder, build_state_from_bundle
from .utils import compact_text, read_csv, read_json, safe_float, safe_int, truthy
from ..otel_tracing import trace_twm_operation


_INSTANCE_LOCK = threading.Lock()
_INSTANCE: "TerritoryWorldModelService | None" = None
TWM_BASELINE_EXPORT_MAX_BYTES = 5 * 1024 * 1024


def _json(data: Any) -> str:
    return json.dumps(jsonable(data), ensure_ascii=False, default=str)


def _stable_sha256(value: Any) -> str:
    material = json.dumps(jsonable(value), ensure_ascii=False, default=str, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _mapping_payload(value: Any, *, raw_key: str = "raw") -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {raw_key: value}
        if isinstance(parsed, dict):
            return dict(parsed)
        return {raw_key: parsed}
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {raw_key: value}


def _set_trace_attribute(trace_ctx: dict[str, Any], key: str, value: Any) -> None:
    span = (trace_ctx or {}).get("span")
    if span is None:
        return
    try:
        span.set_attribute(key, value)
    except Exception:
        return


TWM_BUSINESS_SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "id": "farmland_protection_review",
        "label": "耕地保护与占补平衡审查",
        "decision_question": "拟建或调整项目是否触碰永久基本农田、生态红线，或造成耕地保护目标风险？",
        "operator_goal": "在审查前暴露项目合规风险、证据缺口和可替代空间方案。",
        "primary_roles": ["project", "parcel", "permanent_basic_farmland", "eco_redline", "planning_zone"],
        "required_evidence": ["项目范围", "现状地类图斑", "永久基本农田", "生态保护红线", "审批/补正记录"],
        "default_action_type": "protect",
        "default_target_role": "project",
        "default_scenario": "farmland_protection_review",
        "default_evidence_coverage": 0.78,
        "default_horizon": 3,
        "decision_outputs": ["风险命中优先级", "证据审计包", "合法可行备选方案"],
        "guardrails": ["硬约束命中不直接给通过建议", "合成数据只能作为演示和回归证据"],
    },
    {
        "id": "construction_project_compliance",
        "label": "建设项目用地合规预审",
        "decision_question": "项目选址、规模和审批状态是否与用途管制分区、城镇开发边界和已有审查意见一致？",
        "operator_goal": "把项目落地前的用地冲突、补正事项和审批一致性风险前置给业务人员。",
        "primary_roles": ["project", "parcel", "planning_zone", "urban_boundary", "review_task"],
        "required_evidence": ["建设项目范围", "用途管制分区", "城镇开发边界", "审查意见", "历史审批状态"],
        "default_action_type": "inspect",
        "default_target_role": "project",
        "default_scenario": "construction_project_compliance",
        "default_evidence_coverage": 0.72,
        "default_horizon": 2,
        "decision_outputs": ["审批一致性风险", "补正证据清单", "人工复核任务"],
        "guardrails": ["缺少审批记录时只给复核建议", "边界外建设风险必须保留人工审查"],
    },
    {
        "id": "territorial_plan_adjustment",
        "label": "国土空间用途调整推演",
        "decision_question": "用途调整或空间优化方案会怎样影响保护约束、规划效用和后续监管压力？",
        "operator_goal": "在方案比选阶段比较调整收益、约束风险和可解释证据，而不是只输出最优数值。",
        "primary_roles": ["scenario", "parcel", "planning_zone", "project", "control_boundary"],
        "required_evidence": ["现状空间格局", "规划分区", "硬约束边界", "候选调整方案", "历史监管样本"],
        "default_action_type": "convert",
        "default_target_role": "scenario",
        "default_scenario": "territorial_plan_adjustment",
        "default_evidence_coverage": 0.68,
        "default_horizon": 5,
        "decision_outputs": ["方案效用/风险排序", "反事实推演摘要", "不可推荐方案原因"],
        "guardrails": ["硬约束方案不得进入推荐集", "预测结论必须带证据覆盖和不确定性"],
    },
)


TWM_RESEARCH_POSITIONING: dict[str, Any] = {
    "research_question": (
        "Can a governance-oriented geospatial world model improve territorial planning "
        "decisions by coupling hierarchical GIS state, policy constraints, evidence provenance "
        "and action-conditioned forecast in one auditable loop?"
    ),
    "core_technology": [
        {
            "name": "Hierarchical GIS object-relation-rule-evidence state",
            "claim": "TWM represents parcels, projects, control boundaries, planning zones, approvals, evidence and rules as a linked state rather than as a flat feature table.",
            "why_it_matters": "Territorial governance decisions depend on object roles, spatial relations, policy clauses and evidence provenance at the same time.",
        },
        {
            "name": "Action-conditioned multi-head territorial dynamics",
            "claim": "TWM forecasts a multi-dimensional hierarchical future-state latent, constraint-risk, planning utility, uncertainty and action-mask feasibility conditional on review/protect/convert/restore actions; the latent is decoded into state summaries and does not generate full parcel geometry.",
            "why_it_matters": "The decision object is not only land-use change, but the consequence of governance actions under hard constraints and evidence limits.",
        },
        {
            "name": "Evidence-gated and causally calibrated claim ladder",
            "claim": "TWM separates deterministic rule evidence, observational causal calibration and validation gates before upgrading any operational claim.",
            "why_it_matters": "A system can be useful while still refusing to overclaim when data are synthetic, underidentified or missing production evidence.",
        },
    ],
    "innovation_hypotheses": [
        {
            "hypothesis": "The novelty is architectural integration, not that GIS simulation itself is new.",
            "test": "Compare against land-use simulators, GIS rule engines and optimization tools on whether they jointly expose action-conditioned forecast, policy evidence and audit-ready claim boundaries.",
        },
        {
            "hypothesis": "Object-relation-rule-evidence state reduces missed compliance conflicts compared with layer-by-layer manual review.",
            "test": "Measure hard-constraint conflict recall and false review burden on held-out real approval/review cases.",
        },
        {
            "hypothesis": "Evidence-gated forecasts improve decision defensibility compared with black-box planning scores.",
            "test": "Audit whether every recommended or rejected option carries source evidence, rule clause, uncertainty and human-review reason.",
        },
    ],
    "unmet_need_hypotheses": [
        "Planning and land-use review workflows still fragment spatial overlays, policy checks, approval evidence and scenario comparison across separate tools.",
        "Existing land-use simulators emphasize spatial pattern transition, while operational review needs action consequences, rule validity and audit boundaries.",
        "Optimization tools can rank candidates, but often do not preserve why a candidate is illegal, under-evidenced or only reviewable rather than approvable.",
    ],
    "baselines_to_beat": [
        "Manual GIS overlay plus checklist review",
        "Rule-only spatial compliance engine",
        "Land-use simulation models such as FLUS/PLUS/CLUE-S/CA-Markov for pattern transition",
        "Optimization-only farmland or planning candidate ranking without evidence-gated claim validation",
    ],
    "falsification_conditions": [
        "If real workflow interviews show the target decisions are already well solved by existing tools, TWM should be narrowed or stopped.",
        "If TWM does not improve hard-constraint conflict recall, evidence completeness or audit-trail quality over baselines, the claimed contribution is not supported.",
        "If action-conditioned dynamics cannot be validated beyond synthetic fixtures, TWM must remain a review scaffold rather than a production decision model.",
    ],
    "minimum_evaluation_plan": [
        "Collect real or sanitized approval/review histories with project geometry, rule outcomes, evidence links and final decisions.",
        "Benchmark against manual overlay, rule-only engine and at least one land-use simulation or optimization baseline where appropriate.",
        "Report missed hard-constraint conflicts, review-task precision, evidence completeness, candidate rejection reason coverage and audit-trail completeness.",
        "Keep synthetic fixtures for regression only; do not use them as production-effect evidence.",
    ],
    "claim_boundary": (
        "Current TWM is a rigorous prototype and review scaffold. Its defensible near-term claim is auditable decision support "
        "for territorial governance workflows; production-grade predictive claims require real observed histories, baseline comparisons and external validation."
    ),
}


TWM_DATA_FOUNDATION_DATASETS: tuple[dict[str, Any], ...] = (
    {
        "id": "twm_bishan_demo",
        "label": "Bishan demo engineering fixture",
        "path": "data_agent/test_data/twm_bishan_demo",
        "nature": "mixed_real_imagery_plus_synthetic_governance_fixture",
        "positioning": "工程 MVP 与回归测试主数据包；含真实 Sentinel-2 影像，但项目、PBF、生态红线、审批/复核等治理对象为合成或 not-for-production。",
        "files": {
            "parcel_current.geojson": "feature",
            "synthetic_projects.geojson": "feature",
            "synthetic_pbf.geojson": "feature",
            "synthetic_eco_redline.geojson": "feature",
            "synthetic_planning_zones.geojson": "feature",
            "synthetic_annual_change.geojson": "feature",
            "tables/approval_records.csv": "row",
            "tables/review_tasks.csv": "row",
            "tables/rule_evaluation.csv": "row",
            "tables/state_snapshots.csv": "row",
            "tables/multimodal_evidence_index.csv": "row",
        },
    },
    {
        "id": "twm_bishan_multi_admin_eval",
        "label": "Bishan multi-admin evaluation fixture",
        "path": "data_agent/test_data/twm_bishan_multi_admin_eval",
        "nature": "synthetic_multi_admin_governance_fixture",
        "positioning": "多行政单元压力测试与数据基础体检主对象；结构覆盖更宽，但关键业务历史仍为 synthetic/not-for-production。",
        "files": {
            "parcel_current.geojson": "feature",
            "synthetic_projects.geojson": "feature",
            "synthetic_pbf.geojson": "feature",
            "synthetic_eco_redline.geojson": "feature",
            "synthetic_planning_zones.geojson": "feature",
            "synthetic_annual_change.geojson": "feature",
            "tables/approval_records.csv": "row",
            "tables/review_tasks.csv": "row",
            "tables/rule_evaluation.csv": "row",
            "tables/state_snapshots.csv": "row",
            "tables/multimodal_evidence_index.csv": "row",
        },
    },
    {
        "id": "twm_one_map_village_standard_sample",
        "label": "One Map village standard sample",
        "path": "data_agent/test_data/twm_one_map_village_standard_sample",
        "nature": "standard_structure_sample_with_synthetic_substitutes",
        "positioning": "用于验证自然资源一张图村规划样例能否按 TWM 角色契约接入；所有数据均 not-for-production。",
        "files": {
            "parcel_current.geojson": "feature",
            "synthetic_projects.geojson": "feature",
            "synthetic_pbf.geojson": "feature",
            "synthetic_eco_redline.geojson": "feature",
            "synthetic_planning_zones.geojson": "feature",
            "synthetic_annual_change.geojson": "feature",
            "synthetic_urban_boundary.geojson": "feature",
            "tables/approval_records.csv": "row",
            "tables/review_tasks.csv": "row",
            "tables/rule_evaluation.csv": "row",
            "tables/state_snapshots.csv": "row",
            "tables/multimodal_evidence_index.csv": "row",
        },
    },
)


TWM_DATA_FOUNDATION_SUPPORTED_PROBLEMS: tuple[dict[str, str], ...] = (
    {
        "problem": "工程 MVP 与回归测试",
        "support": "可验证项目创建、状态构建、角色绑定、规则评价、证据链、审计报告、前端 TWM 工作流是否跑通。",
    },
    {
        "problem": "业务审查脚手架",
        "support": "可模拟耕地保护、生态红线、用途管制、审批一致性、复核任务等对象之间的关系和风险暴露逻辑。",
    },
    {
        "problem": "优化/规划消费者链路",
        "support": "可测试候选方案载入、硬约束过滤、beam ranking、action-mask 安全头和验证口径是否按证据门控降级。",
    },
    {
        "problem": "一张图标准适配",
        "support": "可检查字段别名、角色契约、值域、图斑/分区/管控边界等标准结构能否被 TWM 状态模型消费。",
    },
)


TWM_DATA_FOUNDATION_UNSUPPORTED_CLAIMS: tuple[dict[str, str], ...] = (
    {
        "claim": "生产级审批结论",
        "reason": "当前审批、复核、执法、规则命中和项目样本主要为 synthetic/not-for-production，不能替代真实业务责任链。",
    },
    {
        "claim": "真实治理效果预测或因果改进",
        "reason": "尚无非合成的生产观察历史、真实 treated/control 样本、真实政策动作可行性标签和跨期审批结果。",
    },
    {
        "claim": "行动条件动态模型已被真实数据验证",
        "reason": "结构性和合成实验门通过的是管线与诊断能力，默认证据门仍为 review，不能升级为生产准确性证明。",
    },
    {
        "claim": "TWM 已证明优于现有业务工具",
        "reason": "仍缺真实工作流基线对比，如 manual GIS overlay、rule-only engine、土地利用模拟或优化工具的同题评测。",
    },
)


TWM_DATA_FOUNDATION_REQUIRED_NEXT_DATA: tuple[dict[str, Any], ...] = (
    {
        "priority": "P0",
        "data": "真实或脱敏的项目审批/复核/补正/执法历史",
        "minimum": "项目几何、申请/决定日期、审批结果、复核任务、规则命中、证据链接、最终处置结果。",
        "unlocks": "生产观察历史、业务效果评估、人工审查负担和漏检风险基线。",
    },
    {
        "priority": "P0",
        "data": "权威管控边界与规划约束版本",
        "minimum": "永久基本农田、生态保护红线、城镇开发边界、用途管制分区、规划版本与生效时间。",
        "unlocks": "真实硬约束冲突判断、规则条款追溯、跨版本政策动作可行性验证。",
    },
    {
        "priority": "P1",
        "data": "真实 action-mask/政策可行性标签",
        "minimum": "action_type、policy_code、allowed/blocked/conditional 标签、region、period、人工复核原因。",
        "unlocks": "动作可行性安全头、未见地区/政策泛化、方案推荐边界。",
    },
    {
        "priority": "P1",
        "data": "真实时序状态快照与遥感/变更证据",
        "minimum": "多期图斑、年度变更、项目落地结果、遥感证据索引和证据质量标注。",
        "unlocks": "行动条件动态、反事实推演、预测不确定性和证据覆盖校准。",
    },
    {
        "priority": "P2",
        "data": "现有工具链基线结果",
        "minimum": "人工叠加清单、rule-only 输出、土地利用模拟/优化工具输出、耗时和错误记录。",
        "unlocks": "证明 TWM 是否真正解决未满足需求，而不是技术堆砌。",
    },
)


TWM_RESEARCH_CLAIM_MATRIX: tuple[dict[str, Any], ...] = (
    {
        "claim_id": "C1_state_conflict_recall",
        "claim": "Object-relation-rule-evidence state reduces missed hard-constraint conflicts compared with layer-by-layer manual GIS review.",
        "business_need": "项目用地预审需要同时看项目范围、现状图斑、PBF、生态红线、用途分区、审批证据和规则条款；分散叠加容易漏掉冲突或证据缺口。",
        "core_technology": "Hierarchical GIS object-relation-rule-evidence state",
        "baseline": "manual_gis_overlay_checklist",
        "minimum_data": [
            "真实或脱敏项目几何",
            "权威 PBF/生态红线/用途管制边界版本",
            "人工审查清单或历史规则命中",
            "最终处置结果",
        ],
        "metrics": [
            {"name": "hard_constraint_conflict_recall", "direction": "higher_is_better", "minimum_pass": 0.95},
            {"name": "missed_blocking_conflict_rate", "direction": "lower_is_better", "maximum_pass": 0.02},
            {"name": "evidence_link_completeness", "direction": "higher_is_better", "minimum_pass": 0.9},
        ],
        "current_evidence": "Synthetic fixtures verify the pipeline and rule/evidence object model, but do not validate real conflict recall.",
        "current_status": "engineering_supported_production_unvalidated",
        "falsification": "If TWM misses the same hard constraints as manual overlay, or only matches manual results while adding overhead, this claim fails.",
    },
    {
        "claim_id": "C2_audit_defensibility",
        "claim": "Evidence-gated review improves audit defensibility compared with rule-only spatial compliance engines.",
        "business_need": "业务人员不仅要知道命中了哪条规则，还要知道证据来源、缺口、人工复核原因和为什么不能自动给审批结论。",
        "core_technology": "Evidence-gated and causally calibrated claim ladder",
        "baseline": "rule_only_spatial_compliance_engine",
        "minimum_data": [
            "真实规则条款和版本",
            "规则命中证据链接",
            "复核任务与补正记录",
            "审计抽查结论",
        ],
        "metrics": [
            {"name": "audit_trail_completeness", "direction": "higher_is_better", "minimum_pass": 0.9},
            {"name": "unsupported_recommendation_rate", "direction": "lower_is_better", "maximum_pass": 0.01},
            {"name": "review_task_precision", "direction": "higher_is_better", "minimum_pass": 0.75},
        ],
        "current_evidence": "Current rule hits, evidence items and review tasks are synthetic/not-for-production; useful for regression, not for audit quality proof.",
        "current_status": "scaffold_supported_real_audit_unvalidated",
        "falsification": "If rule-only output gives equivalent audit completeness and lower burden on real cases, TWM's evidence-gated contribution is unsupported.",
    },
    {
        "claim_id": "C3_action_conditioned_triage",
        "claim": "Action-conditioned dynamics improves plan-option triage compared with land-use simulators or optimization-only candidate ranking.",
        "business_need": "方案比选要解释候选方案为什么非法、证据不足、只能复核或可继续推进，而不只是给空间格局转移或单一优化分数。",
        "core_technology": "Action-conditioned multi-head territorial dynamics",
        "baseline": "land_use_simulator_or_optimization_only_ranking",
        "minimum_data": [
            "多期真实状态快照",
            "候选方案与实际处置结果",
            "action_type 与政策可行性标签",
            "方案审查意见和后续监管结果",
        ],
        "metrics": [
            {"name": "candidate_rejection_reason_coverage", "direction": "higher_is_better", "minimum_pass": 0.85},
            {"name": "legal_feasible_topk_precision", "direction": "higher_is_better", "minimum_pass": 0.8},
            {"name": "planner_regret_against_human_oracle", "direction": "lower_is_better", "maximum_pass": 0.15},
        ],
        "current_evidence": "Synthetic experiment foundation supports action-mask and beam-plan plumbing; no real action-conditioned dynamics validation yet.",
        "current_status": "experimental_synthetic_only",
        "falsification": "If action-conditioned outputs cannot beat simpler rule-filtered candidate ranking on real held-out cases, keep this as a review scaffold only.",
    },
    {
        "claim_id": "C4_standard_contract_ingestion",
        "claim": "Role-contract based ingestion reduces standard-data onboarding errors compared with ad hoc layer mapping.",
        "business_need": "自然资源一张图、村规划样例和地方业务字段常存在别名、值域和角色差异，手工映射容易造成语义错配。",
        "core_technology": "Hierarchical GIS object-relation-rule-evidence state",
        "baseline": "ad_hoc_layer_mapping",
        "minimum_data": [
            "多个地区的一张图/村规划样例",
            "字段别名与值域标准",
            "人工验收记录",
            "映射错误和修复日志",
        ],
        "metrics": [
            {"name": "role_binding_accuracy", "direction": "higher_is_better", "minimum_pass": 0.95},
            {"name": "value_domain_violation_detection_recall", "direction": "higher_is_better", "minimum_pass": 0.9},
            {"name": "onboarding_rework_rate", "direction": "lower_is_better", "maximum_pass": 0.1},
        ],
        "current_evidence": "One Map village standard sample validates structural compatibility but not cross-region production onboarding performance.",
        "current_status": "standard_structure_supported_cross_region_unvalidated",
        "falsification": "If role-contract ingestion does not reduce mapping errors or rework over ad hoc mapping, this contribution should be dropped.",
    },
)


TWM_RESEARCH_BASELINES: tuple[dict[str, Any], ...] = (
    {
        "baseline_id": "manual_gis_overlay_checklist",
        "label": "Manual GIS overlay plus checklist review",
        "tests": "当前业务是否已能通过人工叠加和清单审查稳定解决硬约束冲突发现。",
        "minimum_output": ["人工命中清单", "证据截图或图层记录", "复核意见", "最终处置"],
        "why_needed": "如果人工流程已经高召回且审计完整，TWM 的增量价值必须体现在效率、证据完整性或复核负担上。",
    },
    {
        "baseline_id": "rule_only_spatial_compliance_engine",
        "label": "Rule-only spatial compliance engine",
        "tests": "规则叠加本身是否已经足以发现风险；TWM 是否额外提供证据门控和审计边界。",
        "minimum_output": ["规则命中", "严重级别", "空间关系", "条款引用"],
        "why_needed": "防止把 rule engine 能解决的问题包装成 world model 创新。",
    },
    {
        "baseline_id": "land_use_simulator_or_optimization_only_ranking",
        "label": "Land-use simulator or optimization-only ranking",
        "tests": "传统模拟/优化能否完成方案排序；TWM 是否更好解释非法、证据不足和 review-only 方案。",
        "minimum_output": ["候选方案排序", "空间变化预测或优化分数", "约束命中结果"],
        "why_needed": "防止把已有土地利用模拟或优化能力重复实现为新方法。",
    },
    {
        "baseline_id": "ad_hoc_layer_mapping",
        "label": "Ad hoc layer and field mapping",
        "tests": "角色契约是否真正减少接入错误，而不是只增加配置复杂度。",
        "minimum_output": ["字段映射表", "值域检查结果", "人工修复记录"],
        "why_needed": "验证 TWM 状态契约对数据落地的实际收益。",
    },
)


TWM_RESEARCH_NEXT_EXPERIMENTS: tuple[dict[str, Any], ...] = (
    {
        "priority": "P0",
        "experiment": "Retrospective approval replay",
        "question": "在真实或脱敏历史项目上，TWM 是否比 manual/rule-only baseline 少漏掉硬约束冲突，并生成更完整证据链？",
        "required_data": ["项目几何", "权威边界版本", "规则命中", "审批/复核结果", "人工基线输出"],
        "decision": "通过后才能把 C1/C2 从 scaffold 提升到 retrospective evidence。",
    },
    {
        "priority": "P0",
        "experiment": "Operator workflow interview and task timing",
        "question": "目标业务是否真有未满足需求，TWM 是否减少查证时间或复核返工？",
        "required_data": ["操作员流程记录", "任务耗时", "补正/返工原因", "现有工具输出"],
        "decision": "如果需求已被现有工具很好解决，应收窄或停止对应场景。",
    },
    {
        "priority": "P1",
        "experiment": "Plan-option triage benchmark",
        "question": "在真实候选方案上，TWM 是否比优化-only ranking 更能解释非法、证据不足和 review-only 原因？",
        "required_data": ["候选方案", "action feasibility labels", "审查意见", "监管结果"],
        "decision": "通过后才允许升级 C3 的 action-conditioned dynamics claim。",
    },
    {
        "priority": "P1",
        "experiment": "Cross-region standard ingestion audit",
        "question": "角色契约在多个地区/标准样例上是否减少接入错误和返工？",
        "required_data": ["多地区一张图样例", "字段别名", "值域标准", "验收记录"],
        "decision": "通过后才允许升级 C4 的标准适配 claim。",
    },
)


TWM_BASELINE_EXPORT_TYPES: tuple[dict[str, Any], ...] = (
    {
        "export_type": "manual_overlay",
        "baseline_id": "manual_gis_overlay_checklist",
        "label": "Manual GIS overlay plus checklist export",
        "business_use": "Retrospective approval replay for C1 hard-constraint conflict recall and C2 audit defensibility.",
        "expected_source": "人工叠加清单、审查记录、证据截图/图层版本和最终处置结果的脱敏同案导出。",
        "required_columns": [
            "case_id",
            "ground_truth_conflict",
            "detected_conflict",
            "evidence_linked",
            "unsupported_recommendation",
        ],
        "recommended_columns": [
            "project_id",
            "region_code",
            "review_date",
            "rule_version",
            "authority_boundary_version",
            "final_disposition",
            "review_task_predicted",
            "review_task_true_positive",
            "evidence_uri",
            "not_for_production",
            "sanitization_level",
        ],
        "compatible_claims": ["C1_state_conflict_recall", "C2_audit_defensibility"],
    },
    {
        "export_type": "rule_only_engine",
        "baseline_id": "rule_only_spatial_compliance_engine",
        "label": "Rule-only spatial compliance engine export",
        "business_use": "Compare whether deterministic rule overlay already solves evidence and review-task needs without TWM state/claim gates.",
        "expected_source": "规则引擎在同一批项目/图斑上的规则命中、空间关系、严重级别和条款引用导出。",
        "required_columns": [
            "case_id",
            "detected_conflict",
            "evidence_linked",
            "unsupported_recommendation",
        ],
        "recommended_columns": [
            "ground_truth_conflict",
            "rule_id",
            "severity",
            "spatial_relation",
            "rule_version",
            "evidence_uri",
            "review_task_predicted",
            "review_task_true_positive",
            "not_for_production",
            "sanitization_level",
        ],
        "compatible_claims": ["C1_state_conflict_recall", "C2_audit_defensibility"],
    },
    {
        "export_type": "optimization_or_simulator_ranking",
        "baseline_id": "land_use_simulator_or_optimization_only_ranking",
        "label": "Land-use simulator or optimization-only ranking export",
        "business_use": "Plan-option triage benchmark for whether TWM explains illegal/review-only/evidence-gap options better than ranking alone.",
        "expected_source": "同一批候选方案的模拟/优化排序、可行性、被拒原因和人工/专家排序结果。",
        "required_columns": [
            "candidate_id",
            "rank",
            "selected",
            "legal_feasible",
            "planner_regret_against_human_oracle",
        ],
        "recommended_columns": [
            "case_id",
            "scenario_id",
            "action_type",
            "blocked",
            "review_only",
            "rejection_reason",
            "human_oracle_rank",
            "selected_utility",
            "oracle_utility",
            "not_for_production",
            "sanitization_level",
        ],
        "compatible_claims": ["C3_action_conditioned_triage"],
    },
)


TWM_BASELINE_EXPORT_TEMPLATE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "claim_id": "C1_state_conflict_recall",
        "baseline_id": "manual_gis_overlay_checklist",
        "export_type": "manual_overlay",
        "label": "C1 same-case hard-constraint conflict recall export",
        "business_question": "同一批历史项目中，TWM 是否比人工叠加清单更少漏掉永久基本农田、生态红线、用途管制等硬约束冲突？",
        "same_case_join_key": "case_id",
        "twm_filename": "twm_c1_conflict_recall_sanitized.csv",
        "baseline_filename": "manual_overlay_c1_conflict_recall_sanitized.csv",
        "twm_header": [
            "case_id",
            "project_id",
            "region_code",
            "review_date",
            "ground_truth_conflict",
            "detected_conflict",
            "evidence_linked",
            "unsupported_recommendation",
            "rule_version",
            "authority_boundary_version",
            "final_disposition",
            "evidence_uri",
            "not_for_production",
            "sanitization_level",
            "source_system",
            "export_batch_id",
        ],
        "baseline_header": [
            "case_id",
            "project_id",
            "region_code",
            "review_date",
            "ground_truth_conflict",
            "detected_conflict",
            "evidence_linked",
            "unsupported_recommendation",
            "rule_version",
            "authority_boundary_version",
            "final_disposition",
            "evidence_uri",
            "not_for_production",
            "sanitization_level",
            "source_system",
            "export_batch_id",
        ],
        "sample_rows": {
            "twm": [
                {
                    "case_id": "anon-case-001",
                    "project_id": "anon-project-001",
                    "region_code": "anon-region",
                    "review_date": "2025-06",
                    "ground_truth_conflict": "true",
                    "detected_conflict": "true",
                    "evidence_linked": "true",
                    "unsupported_recommendation": "false",
                    "rule_version": "rule-v2025q2",
                    "authority_boundary_version": "boundary-v2025q2",
                    "final_disposition": "reject_or_revise",
                    "evidence_uri": "evidence://anon/c1/001",
                    "not_for_production": "true",
                    "sanitization_level": "real_sanitized",
                    "source_system": "twm_state_rule_evidence",
                    "export_batch_id": "batch-c1-YYYYMM",
                }
            ],
            "baseline": [
                {
                    "case_id": "anon-case-001",
                    "project_id": "anon-project-001",
                    "region_code": "anon-region",
                    "review_date": "2025-06",
                    "ground_truth_conflict": "true",
                    "detected_conflict": "true",
                    "evidence_linked": "false",
                    "unsupported_recommendation": "false",
                    "rule_version": "rule-v2025q2",
                    "authority_boundary_version": "boundary-v2025q2",
                    "final_disposition": "reject_or_revise",
                    "evidence_uri": "evidence://anon/manual/001",
                    "not_for_production": "true",
                    "sanitization_level": "real_sanitized",
                    "source_system": "manual_overlay_checklist",
                    "export_batch_id": "batch-c1-YYYYMM",
                }
            ],
        },
        "field_descriptions": [
            {
                "name": "case_id",
                "required": True,
                "applies_to": ["twm", "baseline"],
                "description": "脱敏后的稳定同案 ID，TWM 与 baseline 必须一致。",
                "metric_use": "用于 same-case overlap；没有它不能证明两边比较的是同一批项目。",
                "sanitization": "用不可逆匿名 ID 替代真实项目编号。",
            },
            {
                "name": "ground_truth_conflict",
                "required": True,
                "applies_to": ["twm", "baseline"],
                "description": "由最终处置、复核结论或专家复标确认的硬约束冲突真值。",
                "metric_use": "作为 hard_constraint_conflict_recall 和 missed_blocking_conflict_rate 的分母。",
                "sanitization": "仅保留布尔标签，不导出敏感原文。",
            },
            {
                "name": "detected_conflict",
                "required": True,
                "applies_to": ["twm", "baseline"],
                "description": "TWM 或人工叠加清单是否在审查阶段发现该冲突。",
                "metric_use": "与 ground_truth_conflict 组合计算召回和漏检率。",
                "sanitization": "仅保留布尔标签。",
            },
            {
                "name": "evidence_linked",
                "required": True,
                "applies_to": ["twm", "baseline"],
                "description": "是否能追溯到图层版本、规则条款、截图或审查证据。",
                "metric_use": "计算 evidence_link_completeness，防止只报风险不报依据。",
                "sanitization": "证据链接应指向内部脱敏索引，不导出原始文件路径。",
            },
            {
                "name": "unsupported_recommendation",
                "required": True,
                "applies_to": ["twm", "baseline"],
                "description": "系统是否在证据不足或硬约束未解时仍给出推进性建议。",
                "metric_use": "作为证据门控的安全反例；C1/C2 都需要压低该值。",
                "sanitization": "仅保留布尔标签和脱敏原因。",
            },
        ],
        "metric_column_map": [
            {
                "metric": "hard_constraint_conflict_recall",
                "columns": ["ground_truth_conflict", "detected_conflict"],
                "supports_claim_when": "TWM 在同案数据上召回率高于人工 baseline，并达到 claim threshold。",
            },
            {
                "metric": "missed_blocking_conflict_rate",
                "columns": ["ground_truth_conflict", "detected_conflict"],
                "supports_claim_when": "TWM 漏检率低于人工 baseline，并低于允许上限。",
            },
            {
                "metric": "evidence_link_completeness",
                "columns": ["evidence_linked", "evidence_uri"],
                "supports_claim_when": "TWM 给出的风险能稳定连接到证据和规则版本。",
            },
        ],
        "collection_steps": [
            "从同一批历史项目抽取项目几何、权威边界版本、最终处置和人工叠加清单结果。",
            "先由业务或复核人员确定 ground_truth_conflict，再分别导出 TWM 和人工 baseline 检出结果。",
            "保持 case_id 在两份 CSV 中一致；不一致的项目不得进入 baseline comparison。",
            "先调用 baseline_export_validation_report，通过后再调用 baseline_evidence_pipeline_report。",
        ],
        "production_collection": {
            "sampling_unit": "historical approval or pre-review case",
            "minimum_real_rows": 100,
            "minimum_overlap_ratio": 0.8,
            "notes": "100 行只是早期回放门槛；论文或试点结论还需要按地区、时间和冲突类型做 power/sensitivity analysis。",
        },
    },
    {
        "claim_id": "C2_audit_defensibility",
        "baseline_id": "rule_only_spatial_compliance_engine",
        "export_type": "rule_only_engine",
        "label": "C2 evidence-gated audit defensibility export",
        "business_question": "同一批审查案件中，TWM 是否比 rule-only 空间合规引擎提供更完整、可复核、不过度承诺的审计证据？",
        "same_case_join_key": "case_id",
        "twm_filename": "twm_c2_audit_defensibility_sanitized.csv",
        "baseline_filename": "rule_only_c2_audit_defensibility_sanitized.csv",
        "twm_header": [
            "case_id",
            "project_id",
            "region_code",
            "review_date",
            "detected_conflict",
            "evidence_linked",
            "unsupported_recommendation",
            "review_task_predicted",
            "review_task_true_positive",
            "rule_id",
            "severity",
            "spatial_relation",
            "rule_version",
            "evidence_uri",
            "audit_reviewer_disposition",
            "not_for_production",
            "sanitization_level",
            "source_system",
            "export_batch_id",
        ],
        "baseline_header": [
            "case_id",
            "project_id",
            "region_code",
            "review_date",
            "detected_conflict",
            "evidence_linked",
            "unsupported_recommendation",
            "review_task_predicted",
            "review_task_true_positive",
            "rule_id",
            "severity",
            "spatial_relation",
            "rule_version",
            "evidence_uri",
            "audit_reviewer_disposition",
            "not_for_production",
            "sanitization_level",
            "source_system",
            "export_batch_id",
        ],
        "sample_rows": {
            "twm": [
                {
                    "case_id": "anon-case-021",
                    "project_id": "anon-project-021",
                    "region_code": "anon-region",
                    "review_date": "2025-07",
                    "detected_conflict": "true",
                    "evidence_linked": "true",
                    "unsupported_recommendation": "false",
                    "review_task_predicted": "true",
                    "review_task_true_positive": "true",
                    "rule_id": "pbf_overlap_blocking",
                    "severity": "blocking",
                    "spatial_relation": "intersects",
                    "rule_version": "rule-v2025q3",
                    "evidence_uri": "evidence://anon/c2/021",
                    "audit_reviewer_disposition": "manual_review_required",
                    "not_for_production": "true",
                    "sanitization_level": "real_sanitized",
                    "source_system": "twm_evidence_gate",
                    "export_batch_id": "batch-c2-YYYYMM",
                }
            ],
            "baseline": [
                {
                    "case_id": "anon-case-021",
                    "project_id": "anon-project-021",
                    "region_code": "anon-region",
                    "review_date": "2025-07",
                    "detected_conflict": "true",
                    "evidence_linked": "false",
                    "unsupported_recommendation": "true",
                    "review_task_predicted": "false",
                    "review_task_true_positive": "false",
                    "rule_id": "pbf_overlap_blocking",
                    "severity": "blocking",
                    "spatial_relation": "intersects",
                    "rule_version": "rule-v2025q3",
                    "evidence_uri": "evidence://anon/rule-only/021",
                    "audit_reviewer_disposition": "rule_hit_only",
                    "not_for_production": "true",
                    "sanitization_level": "real_sanitized",
                    "source_system": "rule_only_engine",
                    "export_batch_id": "batch-c2-YYYYMM",
                }
            ],
        },
        "field_descriptions": [
            {
                "name": "case_id",
                "required": True,
                "applies_to": ["twm", "baseline"],
                "description": "脱敏后的稳定审查案件 ID。",
                "metric_use": "用于 same-case audit comparison。",
                "sanitization": "不可逆匿名化；同一案件在两份 CSV 中保持一致。",
            },
            {
                "name": "evidence_linked",
                "required": True,
                "applies_to": ["twm", "baseline"],
                "description": "规则命中是否可追溯到证据包、图层版本和条款。",
                "metric_use": "计算 audit_trail_completeness。",
                "sanitization": "仅导出 evidence_uri 或证据索引，不导出原始涉密附件。",
            },
            {
                "name": "unsupported_recommendation",
                "required": True,
                "applies_to": ["twm", "baseline"],
                "description": "是否在缺少证据、存在硬约束或需要人工复核时仍输出通过/推进建议。",
                "metric_use": "计算 unsupported_recommendation_rate。",
                "sanitization": "仅导出布尔值和脱敏处置类别。",
            },
            {
                "name": "review_task_predicted",
                "required": True,
                "applies_to": ["twm", "baseline"],
                "description": "系统是否创建或建议人工复核任务。",
                "metric_use": "与 review_task_true_positive 组合计算 review_task_precision。",
                "sanitization": "仅导出布尔标签。",
            },
            {
                "name": "review_task_true_positive",
                "required": False,
                "applies_to": ["twm", "baseline"],
                "description": "复核任务是否被业务人员确认必要。",
                "metric_use": "为 review_task_precision 提供人工确认标签。",
                "sanitization": "只导出确认结果，不导出人员姓名。",
            },
        ],
        "metric_column_map": [
            {
                "metric": "audit_trail_completeness",
                "columns": ["evidence_linked", "evidence_uri", "rule_version"],
                "supports_claim_when": "TWM 证据链完整率高于 rule-only baseline。",
            },
            {
                "metric": "unsupported_recommendation_rate",
                "columns": ["unsupported_recommendation"],
                "supports_claim_when": "TWM 更少在证据不足时给出推进性建议。",
            },
            {
                "metric": "review_task_precision",
                "columns": ["review_task_predicted", "review_task_true_positive"],
                "supports_claim_when": "TWM 触发的复核任务更接近业务人员确认的必要复核。",
            },
        ],
        "collection_steps": [
            "锁定同一批审查案件和同一套规则版本，分别运行 TWM evidence gate 与 rule-only baseline。",
            "由业务复核人员确认 review_task_true_positive 和 audit_reviewer_disposition。",
            "确保 evidence_uri 指向可审计但已脱敏的证据索引。",
            "先通过 export validation，再把完整指标提交给 baseline comparison。",
        ],
        "production_collection": {
            "sampling_unit": "review case or rule-hit case",
            "minimum_real_rows": 100,
            "minimum_overlap_ratio": 0.8,
            "notes": "必须包含真实或脱敏复核结论；只有规则命中日志不足以证明审计可辩护性。",
        },
    },
    {
        "claim_id": "C3_action_conditioned_triage",
        "baseline_id": "land_use_simulator_or_optimization_only_ranking",
        "export_type": "optimization_or_simulator_ranking",
        "label": "C3 action-conditioned plan-option triage export",
        "business_question": "同一批候选方案中，TWM 是否比模拟/优化-only 排序更能把合法可行、非法、证据不足和 review-only 方案区分清楚？",
        "same_case_join_key": "candidate_id",
        "twm_filename": "twm_c3_action_conditioned_triage_sanitized.csv",
        "baseline_filename": "optimization_only_c3_candidate_triage_sanitized.csv",
        "twm_header": [
            "candidate_id",
            "case_id",
            "scenario_id",
            "action_type",
            "rank",
            "selected",
            "legal_feasible",
            "blocked",
            "review_only",
            "rejection_reason",
            "planner_regret_against_human_oracle",
            "human_oracle_rank",
            "selected_utility",
            "oracle_utility",
            "evidence_uri",
            "not_for_production",
            "sanitization_level",
            "source_system",
            "export_batch_id",
        ],
        "baseline_header": [
            "candidate_id",
            "case_id",
            "scenario_id",
            "action_type",
            "rank",
            "selected",
            "legal_feasible",
            "blocked",
            "review_only",
            "rejection_reason",
            "planner_regret_against_human_oracle",
            "human_oracle_rank",
            "selected_utility",
            "oracle_utility",
            "evidence_uri",
            "not_for_production",
            "sanitization_level",
            "source_system",
            "export_batch_id",
        ],
        "sample_rows": {
            "twm": [
                {
                    "candidate_id": "anon-candidate-301",
                    "case_id": "anon-case-301",
                    "scenario_id": "anon-scenario-301",
                    "action_type": "convert",
                    "rank": "1",
                    "selected": "true",
                    "legal_feasible": "true",
                    "blocked": "false",
                    "review_only": "false",
                    "rejection_reason": "",
                    "planner_regret_against_human_oracle": "0.04",
                    "human_oracle_rank": "1",
                    "selected_utility": "0.86",
                    "oracle_utility": "0.90",
                    "evidence_uri": "evidence://anon/c3/301",
                    "not_for_production": "true",
                    "sanitization_level": "real_sanitized",
                    "source_system": "twm_action_conditioned_planner",
                    "export_batch_id": "batch-c3-YYYYMM",
                }
            ],
            "baseline": [
                {
                    "candidate_id": "anon-candidate-301",
                    "case_id": "anon-case-301",
                    "scenario_id": "anon-scenario-301",
                    "action_type": "convert",
                    "rank": "1",
                    "selected": "true",
                    "legal_feasible": "false",
                    "blocked": "true",
                    "review_only": "true",
                    "rejection_reason": "pbf_overlap_missing_evidence",
                    "planner_regret_against_human_oracle": "0.22",
                    "human_oracle_rank": "4",
                    "selected_utility": "0.68",
                    "oracle_utility": "0.90",
                    "evidence_uri": "evidence://anon/optimization/301",
                    "not_for_production": "true",
                    "sanitization_level": "real_sanitized",
                    "source_system": "optimization_only_ranking",
                    "export_batch_id": "batch-c3-YYYYMM",
                }
            ],
        },
        "field_descriptions": [
            {
                "name": "candidate_id",
                "required": True,
                "applies_to": ["twm", "baseline"],
                "description": "脱敏后的候选方案 ID，TWM 与 baseline 必须一致。",
                "metric_use": "C3 same-case comparison 的主 join key。",
                "sanitization": "不可逆匿名化；保留同一候选方案跨系统一致性。",
            },
            {
                "name": "rank",
                "required": True,
                "applies_to": ["twm", "baseline"],
                "description": "候选方案排序，数值越小优先级越高。",
                "metric_use": "用于确定 top-k 方案集合。",
                "sanitization": "不包含真实地块或主体名称。",
            },
            {
                "name": "selected",
                "required": True,
                "applies_to": ["twm", "baseline"],
                "description": "该候选方案是否进入推荐或 top-k 集合。",
                "metric_use": "与 legal_feasible 组合计算 legal_feasible_topk_precision。",
                "sanitization": "仅导出布尔标签。",
            },
            {
                "name": "legal_feasible",
                "required": True,
                "applies_to": ["twm", "baseline"],
                "description": "候选方案在当前硬约束和证据条件下是否合法可行。",
                "metric_use": "判断推荐集是否包含非法或只能复核的方案。",
                "sanitization": "仅导出布尔标签和脱敏原因。",
            },
            {
                "name": "planner_regret_against_human_oracle",
                "required": True,
                "applies_to": ["twm", "baseline"],
                "description": "相对人工/专家 oracle 的效用损失。",
                "metric_use": "越低说明排序越接近人工可接受方案。",
                "sanitization": "导出归一化差值，不导出敏感收益测算细节。",
            },
            {
                "name": "rejection_reason",
                "required": False,
                "applies_to": ["twm", "baseline"],
                "description": "非法、证据不足或 review-only 的脱敏原因。",
                "metric_use": "计算 candidate_rejection_reason_coverage。",
                "sanitization": "使用标准原因枚举，不导出原始审查意见全文。",
            },
        ],
        "metric_column_map": [
            {
                "metric": "candidate_rejection_reason_coverage",
                "columns": ["blocked", "review_only", "rejection_reason"],
                "supports_claim_when": "TWM 对被阻断或只能复核的候选方案提供更完整原因。",
            },
            {
                "metric": "legal_feasible_topk_precision",
                "columns": ["rank", "selected", "legal_feasible", "blocked"],
                "supports_claim_when": "TWM 推荐集中的合法可行比例高于优化-only baseline。",
            },
            {
                "metric": "planner_regret_against_human_oracle",
                "columns": ["planner_regret_against_human_oracle", "selected_utility", "oracle_utility"],
                "supports_claim_when": "TWM 相对人工 oracle 的平均 regret 更低。",
            },
        ],
        "collection_steps": [
            "为同一批候选方案保留稳定 candidate_id，并记录 action_type、排序、推荐集和人工/专家 oracle。",
            "用同一规则版本和同一证据截面分别运行 TWM action-conditioned triage 与模拟/优化-only baseline。",
            "把非法、证据不足和 review-only 原因归一到标准枚举，避免导出原始敏感审查文本。",
            "先确认 candidate_id overlap，再比较 top-k precision、reason coverage 和 regret。",
        ],
        "production_collection": {
            "sampling_unit": "candidate plan option",
            "minimum_real_rows": 50,
            "minimum_overlap_ratio": 0.8,
            "notes": "C3 必须有真实或脱敏 action feasibility labels 和人工/专家排序；只有优化分数不足以验证 action-conditioned dynamics。",
        },
    },
)


class TerritoryWorldModelService:
    """Facade for TWM project lifecycle, state build, rules, and planning."""

    def __init__(self, repository: TwmRepository | None = None):
        self.repository = repository or get_twm_repository()
        self.state_builder = StateBuilder()
        self.rule_evaluator = RuleEvaluator(repository=self.repository)
        self.planner = TerritoryWorldModelPlanner()
        self._report_cache_lock = threading.RLock()
        self._state_contract_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._dynamics_training_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._dynamics_readiness_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._dynamics_backend_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._geofm_gate_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._causal_calibration_cache: dict[tuple[str, str], dict[str, Any]] = {}

    def status(self) -> dict[str, Any]:
        repo_status = self.repository.status()
        return {
            "status": "ready",
            "version": "0.1.0",
            "repository": repo_status,
            "planner": {
                "multi_head": True,
                "action_conditioned": True,
                "evidence_gated": True,
            },
            "capabilities": {
                "projects": True,
                "state_build": True,
                "rules": True,
                "evidence": True,
                "reviews": True,
                "planning": True,
                "geofm_ablation_gate": True,
                "geofm_downstream_experiment": True,
                "causal_calibration": True,
                "scca_causal_evidence": True,
                "action_mask": True,
                "dynamics_readiness": True,
                "dynamics_evaluation": True,
                "dynamics_fit": True,
                "dynamics_backend": True,
                "train_dynamics": True,
                "training_objective": True,
                "beam_plan": True,
                "state_contract": True,
                "claim_ladder": True,
            },
            "updated_at": now_utc_iso(),
        }

    def _report_cache_key(
        self,
        state_version_id: str,
        payload: dict[str, Any],
        *,
        include: tuple[str, ...],
    ) -> tuple[str, str]:
        material = {key: self._report_cache_value(key, payload.get(key)) for key in include if key in payload}
        return state_version_id, json.dumps(jsonable(material), ensure_ascii=False, default=str, sort_keys=True)

    def _report_cache_value(self, key: str, value: Any) -> Any:
        if key in {"dataset", "dynamics_training_dataset"} and isinstance(value, dict):
            return self._dynamics_dataset_cache_fingerprint(value)
        return value

    def _dynamics_dataset_cache_fingerprint(self, dataset: dict[str, Any]) -> dict[str, Any]:
        summary = dict(dataset.get("summary") or {})
        return {
            "state_version_id": dataset.get("state_version_id"),
            "project_id": dataset.get("project_id"),
            "summary": {
                "example_count": summary.get("example_count"),
                "forecast_scaffold_example_count": summary.get("forecast_scaffold_example_count"),
                "temporal_transition_example_count": summary.get("temporal_transition_example_count"),
                "usable_example_count": summary.get("usable_example_count"),
                "review_example_count": summary.get("review_example_count"),
                "temporal_holdout": summary.get("temporal_holdout"),
                "supervision_sources": summary.get("supervision_sources"),
                "loss_contract": summary.get("loss_contract"),
            },
            "inventory": self._dynamics_sample_inventory(dataset),
        }

    def _cache_get(self, cache: dict[tuple[str, str], dict[str, Any]], key: tuple[str, str]) -> dict[str, Any] | None:
        with self._report_cache_lock:
            value = cache.get(key)
            return deepcopy(value) if value is not None else None

    def _cache_set(self, cache: dict[tuple[str, str], dict[str, Any]], key: tuple[str, str], value: dict[str, Any]) -> None:
        with self._report_cache_lock:
            cache[key] = deepcopy(value)

    def _clear_report_cache(self, *, project_id: str | None = None, state_version_id: str | None = None) -> None:
        with self._report_cache_lock:
            if state_version_id:
                self._state_contract_cache = {
                    key: value for key, value in self._state_contract_cache.items() if key[0] != state_version_id
                }
                self._dynamics_training_cache = {
                    key: value for key, value in self._dynamics_training_cache.items() if key[0] != state_version_id
                }
                self._dynamics_readiness_cache = {
                    key: value for key, value in self._dynamics_readiness_cache.items() if key[0] != state_version_id
                }
                self._dynamics_backend_cache = {
                    key: value for key, value in self._dynamics_backend_cache.items() if key[0] != state_version_id
                }
                self._geofm_gate_cache = {
                    key: value for key, value in self._geofm_gate_cache.items() if key[0] != state_version_id
                }
                self._causal_calibration_cache = {
                    key: value for key, value in self._causal_calibration_cache.items() if key[0] != state_version_id
                }
                return
            if project_id:
                state_ids = {item.id for item in self.repository.list_state_versions(project_id=project_id)}
                self._state_contract_cache = {
                    key: value for key, value in self._state_contract_cache.items() if key[0] not in state_ids
                }
                self._dynamics_training_cache = {
                    key: value for key, value in self._dynamics_training_cache.items() if key[0] not in state_ids
                }
                self._dynamics_readiness_cache = {
                    key: value for key, value in self._dynamics_readiness_cache.items() if key[0] not in state_ids
                }
                self._dynamics_backend_cache = {
                    key: value for key, value in self._dynamics_backend_cache.items() if key[0] not in state_ids
                }
                self._geofm_gate_cache = {
                    key: value for key, value in self._geofm_gate_cache.items() if key[0] not in state_ids
                }
                self._causal_calibration_cache = {
                    key: value for key, value in self._causal_calibration_cache.items() if key[0] not in state_ids
                }
                return
            self._state_contract_cache.clear()
            self._dynamics_training_cache.clear()
            self._dynamics_readiness_cache.clear()
            self._dynamics_backend_cache.clear()
            self._geofm_gate_cache.clear()
            self._causal_calibration_cache.clear()

    # ------------------------------------------------------------------
    # Project / binding lifecycle
    # ------------------------------------------------------------------

    def list_business_scenarios(self) -> list[dict[str, Any]]:
        return [json.loads(_json(item)) for item in TWM_BUSINESS_SCENARIOS]

    def research_positioning(self) -> dict[str, Any]:
        return json.loads(_json(TWM_RESEARCH_POSITIONING))

    def roadmap_status_report(self) -> dict[str, Any]:
        data_foundation = self.data_foundation_assessment()
        validation = dict(data_foundation.get("validation_snapshot") or {})
        production_rows = safe_int(validation.get("production_ready_observed_history_rows"), 0)
        policy_rows = safe_int(validation.get("production_policy_history_row_count"), 0)
        engineering_mvp = bool((data_foundation.get("landing_readiness") or {}).get("engineering_mvp_supported"))
        phases = [
            {
                "id": "demo_closure",
                "label": "Natural resources demo closure",
                "status": "complete",
                "completion_ratio": 0.9,
                "evidence": [
                    "Chinese-first TWM frontend tabs are implemented",
                    "data foundation map preview and bbox-aligned overview map are implemented",
                    "automated E2E evidence exists for the demo workflow",
                ],
                "remaining": ["manual acceptance and demo freeze before external presentation"],
            },
            {
                "id": "engineering_scaffold",
                "label": "Auditable TWM engineering scaffold",
                "status": "partial" if engineering_mvp else "review",
                "completion_ratio": 0.9 if engineering_mvp else 0.7,
                "evidence": [
                    "state/rule/evidence/audit pipeline",
                    "forecast, counterfactual rollout, validation ladder and beam planning consumer",
                    "trainable dynamics candidates and observational causal calibration reports",
                    "dynamics model registry release gate report is implemented",
                    "persistent model registry/version rollback is implemented in service, repository, API and Agent tools",
                    "state snapshot lakehouse manifest maps TWM state, rule, evidence and registry layers to Iceberg/GeoParquet/Parquet storage",
                    "state snapshot lakehouse materializer writes local Parquet/GeoParquet-compatible artifacts through service, API and Agent tools",
                    "Iceberg/Sedona publish plan generates table DDL, artifact publish specs and geohash spatial index jobs",
                    "Spark executor contract validates Iceberg snapshot ids, row counts and Sedona spatial index job results",
                    "spark-submit execution bundle writes a production Spark/Sedona/Iceberg plan file and command package",
                ],
                "remaining": ["service decomposition", "credentialed production Spark run and external Iceberg audit acceptance"],
            },
            {
                "id": "data_foundation_productization",
                "label": "Data foundation productization",
                "status": "partial",
                "completion_ratio": 0.7,
                "evidence": [
                    "demo dataset catalog, CRS diagnostics and map overlay readiness are exposed",
                    "full GeoJSON preview is available for the current demo scale",
                    "lineage and field drilldown reports are exposed through API, tools and frontend",
                    "CRS remediation plan is exposed through API, tools and frontend",
                    "authoritative production data templates are exposed through API, tools and frontend",
                ],
                "remaining": ["vector tiles or server-side chunking", "production CRS conversion ETL", "production lineage ingestion templates"],
            },
            {
                "id": "trusted_poc",
                "label": "Trusted pilot validation",
                "status": "candidate" if production_rows > 0 and policy_rows > 0 else "blocked",
                "completion_ratio": 0.4 if production_rows > 0 and policy_rows > 0 else 0.25,
                "evidence": [
                    "public Dynamic World and GeoSOS/FLUS benchmark evidence exists",
                    "claim ladder and baseline comparison contracts exist",
                ],
                "remaining": ["real observed approval/review history", "policy/action feasibility labels", "same-case baseline and holdout evaluation"],
            },
            {
                "id": "productionization",
                "label": "Production and air-gapped deployment",
                "status": "blocked",
                "completion_ratio": 0.15,
                "evidence": ["air-gapped deployment strategy exists"],
                "remaining": ["offline deployment package", "permissioned audit trail", "model/rule/version comparison", "sanitized diagnostic export"],
            },
        ]
        blockers = [
            {
                "id": "production_observed_history",
                "priority": "P0",
                "status": "blocked" if production_rows <= 0 else "partial",
                "current_value": production_rows,
                "required_value": "one pilot region with multi-year observed approval/review history",
            },
            {
                "id": "policy_action_history",
                "priority": "P0",
                "status": "blocked" if policy_rows <= 0 else "partial",
                "current_value": policy_rows,
                "required_value": "authoritative policy/action feasibility labels",
            },
            {
                "id": "service_decomposition",
                "priority": "P1",
                "status": "open",
                "current_value": "large facade service",
                "required_value": "state, dynamics, calibration, planner, evidence/audit and readiness services",
            },
            {
                "id": "full_flus_and_holdout_baselines",
                "priority": "P2",
                "status": "open",
                "current_value": "public benchmark and simplified/direct adapters",
                "required_value": "same-case full FLUS/GeoSOS baseline plus cross-region/cross-year holdout",
            },
        ]
        next_actions = [
            {
                "priority": "P0",
                "action": "secure real or sanitized observed history and policy/action labels for one pilot region",
                "roadmap_phase": "trusted_poc",
            },
            {
                "priority": "P0",
                "action": "freeze and manually accept the current natural-resources demo workflow",
                "roadmap_phase": "demo_closure",
            },
            {
                "priority": "P1",
                "action": "split the TWM facade service along state/dynamics/calibration/planner/evidence boundaries",
                "roadmap_phase": "engineering_scaffold",
            },
            {
                "priority": "P1",
                "action": "finish vector tiles or chunked preview, production CRS conversion ETL, and production lineage ingestion templates",
                "roadmap_phase": "data_foundation_productization",
            },
        ]
        return {
            "schema": "territory_world_model.roadmap_status_report.v1",
            "generated_at": now_utc_iso(),
            "overall_status": "prototype_complete_review_only",
            "claim_boundary": "Current TWM is a rigorous prototype: demo-complete and engineering-reviewable, but production, prediction and causal claims remain review-only until real observed history, policy labels and same-case baselines pass.",
            "data_gate": {
                "status": data_foundation.get("status", "review"),
                "production_ready_observed_history_rows": production_rows,
                "production_policy_history_row_count": policy_rows,
                "predictive_or_causal_claim_supported": bool((data_foundation.get("landing_readiness") or {}).get("predictive_or_causal_claim_supported")),
            },
            "phases": phases,
            "blockers": blockers,
            "next_actions": next_actions,
        }

    def research_claim_matrix(self) -> dict[str, Any]:
        data_foundation = self.data_foundation_assessment()
        production_rows = safe_int(
            data_foundation.get("validation_snapshot", {}).get("production_ready_observed_history_rows"),
            0,
        )
        policy_rows = safe_int(
            data_foundation.get("validation_snapshot", {}).get("production_policy_history_row_count"),
            0,
        )
        if production_rows > 0 and policy_rows > 0:
            overall_status = "candidate"
        else:
            overall_status = "review"
        result = {
            "schema": "territory_world_model.research_claim_matrix.v1",
            "status": overall_status,
            "generated_at": now_utc_iso(),
            "research_question": TWM_RESEARCH_POSITIONING["research_question"],
            "claim_boundary": (
                "Every TWM research claim must name the unmet business need, a simpler baseline, minimum real-data evidence, "
                "metrics and falsification conditions before it can be upgraded beyond prototype status."
            ),
            "current_data_gate": {
                "status": data_foundation.get("status", "review"),
                "production_ready_observed_history_rows": production_rows,
                "production_policy_history_row_count": policy_rows,
                "production_deployment_supported": data_foundation.get("landing_readiness", {}).get("production_deployment_supported", False),
                "predictive_or_causal_claim_supported": data_foundation.get("landing_readiness", {}).get("predictive_or_causal_claim_supported", False),
            },
            "claims": [self._research_claim_with_gate(item, production_rows, policy_rows) for item in TWM_RESEARCH_CLAIM_MATRIX],
            "baselines": list(TWM_RESEARCH_BASELINES),
            "next_experiments": list(TWM_RESEARCH_NEXT_EXPERIMENTS),
            "decision_policy": {
                "promote_to_retrospective_evidence": [
                    "real_or_sanitized_history_present",
                    "named_baseline_output_present",
                    "metric_thresholds_reported",
                    "unsupported_recommendation_gate_pass",
                ],
                "promote_to_pilot": [
                    "retrospective_metrics_pass",
                    "operator_workflow_need_confirmed",
                    "external_review_of_claim_boundary",
                    "human_in_the_loop_guardrail_active",
                ],
                "stop_or_narrow": [
                    "baseline_solves_target_need",
                    "no_metric_lift_over_simpler_method",
                    "real_data_unavailable_for_core_claim",
                    "business_users_reject_decision_question",
                ],
            },
            "mentor_answer": (
                "TWM 的创新性不能靠列举模型组件来证明。当前应把每个主张绑定到真实业务问题、简单基线、数据门槛和可证伪指标；"
                "在生产历史和 baseline 对比缺失前，TWM 只能主张工程原型和审查脚手架，不能主张生产级 world model。"
            ),
        }
        return json.loads(_json(result))

    def baseline_export_schema(self) -> dict[str, Any]:
        claim_matrix = self.research_claim_matrix()
        claims_by_id = {item["claim_id"]: item for item in claim_matrix["claims"]}
        baselines_by_id = {item["baseline_id"]: item for item in claim_matrix["baselines"]}
        export_types = []
        for item in TWM_BASELINE_EXPORT_TYPES:
            compatible_claims = []
            for claim_id in item.get("compatible_claims", []):
                claim = claims_by_id.get(str(claim_id))
                if claim:
                    compatible_claims.append(
                        {
                            "claim_id": claim["claim_id"],
                            "claim": claim["claim"],
                            "metrics": claim.get("metrics", []),
                            "minimum_data": claim.get("minimum_data", []),
                        }
                    )
            export_types.append(
                {
                    **item,
                    "baseline": baselines_by_id.get(str(item.get("baseline_id")), {}),
                    "compatible_claim_details": compatible_claims,
                }
            )
        return json.loads(
            _json(
                {
                    "schema": "territory_world_model.baseline_export_schema.v1",
                    "generated_at": now_utc_iso(),
                    "purpose": (
                        "Define the minimum real or sanitized same-case exports required before TWM baseline comparisons can support "
                        "retrospective evidence instead of synthetic regression evidence."
                    ),
                    "same_case_join_requirements": {
                        "primary_join_key": "case_id for approval/review cases; candidate_id for plan-option candidate rows",
                        "minimum_overlap_ratio": 0.8,
                        "required_for_claim_upgrade": True,
                        "policy": (
                            "TWM and baseline outputs must cover the same historical projects, parcels, candidates or review cases. "
                            "Aggregate-only metrics are acceptable for smoke tests but cannot promote research claims."
                        ),
                    },
                    "privacy_and_sanitization": {
                        "accepted_data_classes": ["real_sanitized", "real_internal_review", "synthetic_regression"],
                        "recommended_columns": ["not_for_production", "sanitization_level", "source_system", "export_batch_id"],
                        "minimum_rule": (
                            "Production or sensitive project/person identifiers must be removed or replaced by stable anonymous IDs; "
                            "geometry may be generalized if case joins, rule hits and final dispositions remain traceable."
                        ),
                    },
                    "export_types": export_types,
                    "validation_api": {
                        "endpoint": "POST /api/twm/baseline-export-validation-report",
                        "required_payload": ["twm_case_output_path", "baseline_case_output_path"],
                        "optional_payload": ["claim_id", "baseline_id", "export_type"],
                    },
                    "claim_boundary": (
                        "Passing this schema check only means the baseline export is structurally comparable. It does not by itself prove "
                        "TWM has solved an unmet business need."
                    ),
                }
            )
        )

    def baseline_export_templates(self) -> dict[str, Any]:
        schema = self.baseline_export_schema()
        claim_matrix = self.research_claim_matrix()
        claims_by_id = {item["claim_id"]: item for item in claim_matrix["claims"]}
        baselines_by_id = {item["baseline_id"]: item for item in claim_matrix["baselines"]}
        export_types = {item["export_type"]: item for item in schema.get("export_types", [])}
        templates = [
            self._baseline_export_template_public(item, claims_by_id, baselines_by_id, export_types)
            for item in TWM_BASELINE_EXPORT_TEMPLATE_SPECS
        ]
        return json.loads(
            _json(
                {
                    "schema": "territory_world_model.baseline_export_templates.v1",
                    "generated_at": now_utc_iso(),
                    "purpose": (
                        "Provide real/sanitized same-case CSV collection templates for the C1/C2/C3 TWM research claims. "
                        "These templates are for evidence collection and validation, not for direct production deployment."
                    ),
                    "templates": templates,
                    "global_sanitization_rules": [
                        "Replace real project, parcel, candidate, organization and person identifiers with stable anonymous IDs.",
                        "Keep the same anonymous join key across TWM and baseline exports; otherwise the comparison is invalid.",
                        "Use evidence_uri as an internal sanitized evidence index instead of raw file paths or sensitive text.",
                        "Set not_for_production=true unless the export has passed internal data-governance release review.",
                        "Preserve rule_version, boundary_version and source_system because metric results are not interpretable without lineage.",
                    ],
                    "validation_flow": [
                        "Fill both TWM and baseline CSVs for the same cases or candidates.",
                        "Import or place the CSVs inside the repository workspace.",
                        "Run POST /api/twm/baseline-export-validation-report and fix blockers.",
                        "Only after export validation passes, run POST /api/twm/baseline-evidence-pipeline-report.",
                    ],
                    "claim_boundary": (
                        "Templates reduce ambiguity in data collection. They do not prove TWM innovation or production value until "
                        "real/sanitized same-case exports beat the named simpler baselines under the claim metrics."
                    ),
                }
            )
        )

    def import_baseline_export(self, payload: dict[str, Any] | None = None, username: str = "anonymous") -> dict[str, Any]:
        payload = dict(payload or {})
        raw_csv = payload.get("content") or payload.get("csv") or payload.get("text") or ""
        if not isinstance(raw_csv, str) or not raw_csv.strip():
            raise ValueError("CSV content is required")
        content = raw_csv.encode("utf-8")
        if len(content) > TWM_BASELINE_EXPORT_MAX_BYTES:
            raise ValueError(f"CSV content exceeds {TWM_BASELINE_EXPORT_MAX_BYTES // 1024 // 1024}MB limit")
        original_name = compact_text(payload.get("filename") or payload.get("name") or "baseline_export.csv")
        safe_name = self._safe_baseline_export_filename(original_name)
        source_role = compact_text(payload.get("source_role") or payload.get("role") or "baseline").lower()
        if source_role not in {"twm", "baseline"}:
            source_role = "baseline"
        claim_id = compact_text(payload.get("claim_id") or "unspecified_claim")
        baseline_id = compact_text(payload.get("baseline_id") or "unspecified_baseline")
        batch_id = self._safe_baseline_export_token(payload.get("batch_id") or payload.get("export_batch_id") or now_utc_iso())
        user_token = self._safe_baseline_export_token(username or "anonymous")
        target_dir = self._repo_root() / "data_agent" / "uploads" / "twm_baseline_exports" / user_token / batch_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = (target_dir / f"{source_role}_{safe_name}").resolve()
        repo_root = self._repo_root().resolve()
        if repo_root not in target_path.parents:
            raise ValueError("resolved baseline export path escapes repository")
        target_path.write_text(raw_csv, encoding="utf-8")
        relative_path = target_path.relative_to(repo_root).as_posix()
        source = self._load_baseline_export_records(relative_path)
        records = source.get("records", [])
        if source.get("error"):
            raise ValueError(f"imported CSV is not readable: {source['error']}")
        columns = sorted(self._record_columns(records))
        preview_metrics = self._aggregate_case_metrics(records)
        return json.loads(
            _json(
                {
                    "schema": "territory_world_model.baseline_export_import.v1",
                    "status": "pass" if records else "review",
                    "generated_at": now_utc_iso(),
                    "path": relative_path,
                    "filename": target_path.name,
                    "source_role": source_role,
                    "claim_id": claim_id,
                    "baseline_id": baseline_id,
                    "export_batch_id": batch_id,
                    "row_count": len(records),
                    "columns": columns,
                    "preview_metrics": preview_metrics,
                    "not_for_production": True,
                    "next_actions": [
                        "use this returned path as twm_case_output_path or baseline_case_output_path",
                        "run baseline_export_validation_report before using this export in a comparison",
                    ],
                    "claim_boundary": (
                        "Imported baseline CSVs are staged for TWM validation. Importing a file does not make it production evidence."
                    ),
                }
            )
        )

    def baseline_export_validation_report(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        schema = self.baseline_export_schema()
        export_types = list(schema.get("export_types") or [])
        claim_matrix = self.research_claim_matrix()
        claims_by_id = {item["claim_id"]: item for item in claim_matrix["claims"]}
        claim_id = compact_text(payload.get("claim_id") or "C1_state_conflict_recall")
        claim = claims_by_id.get(claim_id) or claim_matrix["claims"][0]
        baseline_id = compact_text(payload.get("baseline_id") or claim.get("baseline"))
        export_type_id = compact_text(payload.get("export_type"))
        export_spec = self._baseline_export_spec(export_types, export_type_id, baseline_id, claim["claim_id"])
        twm_source = self._load_baseline_export_records(payload.get("twm_case_output_path") or payload.get("twm_case_result_path"))
        baseline_source = self._load_baseline_export_records(payload.get("baseline_case_output_path") or payload.get("baseline_case_result_path"))
        join_key = self._baseline_export_join_key(twm_source, baseline_source, export_spec)
        twm_inventory = self._baseline_export_record_inventory(twm_source.get("records", []), join_key)
        baseline_inventory = self._baseline_export_record_inventory(baseline_source.get("records", []), join_key)
        overlap = self._baseline_export_overlap(twm_inventory, baseline_inventory)
        twm_required = self._missing_columns(twm_inventory["columns"], export_spec.get("required_columns", []))
        baseline_required = self._missing_columns(baseline_inventory["columns"], export_spec.get("required_columns", []))
        claim_required = self._missing_columns(
            set(twm_inventory["columns"]) | set(baseline_inventory["columns"]),
            self._claim_export_required_columns(claim["claim_id"]),
        )
        parser_probe = self._baseline_export_parser_probe(twm_source, baseline_source, claim)
        public_twm_inventory = self._baseline_export_public_inventory(twm_inventory)
        public_baseline_inventory = self._baseline_export_public_inventory(baseline_inventory)

        blocking_errors: list[str] = []
        warnings: list[str] = []
        if twm_source.get("error"):
            blocking_errors.append(f"twm_case_output_path:{twm_source['error']}")
        if baseline_source.get("error"):
            blocking_errors.append(f"baseline_case_output_path:{baseline_source['error']}")
        if twm_inventory["row_count"] <= 0:
            blocking_errors.append("twm_case_output_empty")
        if baseline_inventory["row_count"] <= 0:
            blocking_errors.append("baseline_case_output_empty")
        if twm_required:
            blocking_errors.append(f"twm_missing_required_columns:{','.join(twm_required)}")
        if baseline_required:
            blocking_errors.append(f"baseline_missing_required_columns:{','.join(baseline_required)}")
        if not join_key:
            blocking_errors.append("same_case_join_key_missing")
        elif overlap["overlap_count"] <= 0:
            blocking_errors.append("same_case_overlap_missing")
        elif overlap["coverage_ratio"] < float(schema["same_case_join_requirements"]["minimum_overlap_ratio"]):
            blocking_errors.append("same_case_overlap_below_threshold")
        if claim_required:
            warnings.append(f"claim_parser_columns_missing_or_partial:{','.join(claim_required)}")
        if twm_inventory["duplicate_join_ids"]:
            warnings.append("twm_duplicate_join_ids")
        if baseline_inventory["duplicate_join_ids"]:
            warnings.append("baseline_duplicate_join_ids")
        if twm_inventory["not_for_production_rows"] <= 0 and baseline_inventory["not_for_production_rows"] <= 0:
            warnings.append("not_for_production_or_sanitization_flag_missing")
        if not parser_probe["comparable_metrics"]:
            warnings.append("no_claim_metrics_recovered_by_current_parser")

        status = "blocked" if blocking_errors else "review" if warnings else "pass"
        if twm_inventory["synthetic_rows"] > 0 or baseline_inventory["synthetic_rows"] > 0:
            warnings.append("synthetic_rows_present_export_is_regression_only")

        result = {
            "schema": "territory_world_model.baseline_export_validation_report.v1",
            "status": status,
            "generated_at": now_utc_iso(),
            "claim": {
                "claim_id": claim["claim_id"],
                "claim": claim["claim"],
                "baseline_id": baseline_id,
                "metrics": claim.get("metrics", []),
            },
            "export_spec": {
                "export_type": export_spec.get("export_type"),
                "baseline_id": export_spec.get("baseline_id"),
                "label": export_spec.get("label"),
                "required_columns": export_spec.get("required_columns", []),
                "recommended_columns": export_spec.get("recommended_columns", []),
            },
            "sources": {
                "twm": self._baseline_export_source_summary(twm_source),
                "baseline": self._baseline_export_source_summary(baseline_source),
            },
            "column_inventory": {
                "join_key": join_key,
                "twm": public_twm_inventory,
                "baseline": public_baseline_inventory,
                "missing_required": {
                    "twm": twm_required,
                    "baseline": baseline_required,
                    "claim_parser": claim_required,
                },
            },
            "coverage": overlap,
            "parser_compatibility": parser_probe,
            "blocking_errors": list(dict.fromkeys(blocking_errors)),
            "warnings": list(dict.fromkeys(warnings)),
            "next_actions": self._baseline_export_validation_next_actions(status, blocking_errors, warnings),
            "claim_boundary": (
                "This validation checks whether real or sanitized TWM/baseline outputs are structurally comparable on the same cases. "
                "Research or production claims still require metric lift, workflow need confirmation and external review."
            ),
        }
        if truthy(payload.get("save_scenario") or payload.get("persist_scenario") or payload.get("save_run_card")):
            result["scenario_card"] = self._save_baseline_export_validation_scenario(payload, result)
        return json.loads(_json(result))

    def baseline_comparison_report(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        claim_matrix = self.research_claim_matrix()
        claims_by_id = {item["claim_id"]: item for item in claim_matrix["claims"]}
        baselines_by_id = {item["baseline_id"]: item for item in claim_matrix["baselines"]}
        claim_id = str(payload.get("claim_id") or "C1_state_conflict_recall")
        claim = claims_by_id.get(claim_id) or claim_matrix["claims"][0]
        baseline_id = str(payload.get("baseline_id") or claim.get("baseline") or "")
        baseline = baselines_by_id.get(baseline_id, {"baseline_id": baseline_id, "label": baseline_id or "unspecified"})
        twm_metric_source = self._load_metric_source(payload.get("twm_metrics_path") or payload.get("twm_result_path"))
        baseline_metric_source = self._load_metric_source(payload.get("baseline_metrics_path") or payload.get("baseline_result_path"))
        twm_case_source = self._load_case_metric_source(payload.get("twm_case_output_path") or payload.get("twm_case_result_path"))
        baseline_case_source = self._load_case_metric_source(payload.get("baseline_case_output_path") or payload.get("baseline_case_result_path"))
        twm_metrics = self._normalize_metric_payload(payload.get("twm_metrics") or payload.get("twm_result") or {})
        baseline_metrics = self._normalize_metric_payload(payload.get("baseline_metrics") or payload.get("baseline_result") or {})
        twm_metrics.update(twm_metric_source.get("metrics", {}))
        baseline_metrics.update(baseline_metric_source.get("metrics", {}))
        twm_metrics.update(twm_case_source.get("metrics", {}))
        baseline_metrics.update(baseline_case_source.get("metrics", {}))
        metric_comparisons = [
            self._compare_research_metric(metric, twm_metrics, baseline_metrics)
            for metric in claim.get("metrics", [])
        ]
        provided_metric_count = sum(1 for item in metric_comparisons if item["status"] != "missing")
        passed_metric_count = sum(1 for item in metric_comparisons if item["status"] == "pass")
        missing: list[str] = []
        if not twm_metrics:
            missing.append("twm_metrics")
        if not baseline_metrics:
            missing.append("baseline_metrics")
        missing.extend(str(item) for item in claim.get("gate", {}).get("missing", []) if item)
        if provided_metric_count <= 0:
            missing.append("comparable_metrics")
        enough_metrics = provided_metric_count > 0 and passed_metric_count == provided_metric_count
        claim_gate_clear = not claim.get("gate", {}).get("missing")
        status = "pass" if enough_metrics and claim_gate_clear and not missing else "review"
        upgrade_decision = "remain_prototype_scaffold"
        if provided_metric_count <= 0:
            upgrade_decision = "baseline_evidence_not_provided"
        elif enough_metrics and claim_gate_clear:
            upgrade_decision = "eligible_for_retrospective_evidence"
        elif enough_metrics:
            upgrade_decision = "metrics_pass_but_data_gate_blocks_upgrade"
        elif provided_metric_count > 0:
            upgrade_decision = "no_metric_lift_over_baseline"
        result = {
            "schema": "territory_world_model.baseline_comparison_report.v1",
            "status": status,
            "generated_at": now_utc_iso(),
            "claim": {
                "claim_id": claim["claim_id"],
                "claim": claim["claim"],
                "current_status": claim.get("current_status"),
                "gate": claim.get("gate", {}),
                "falsification": claim.get("falsification"),
            },
            "baseline": baseline,
            "inputs": {
                "twm_metric_count": len(twm_metrics),
                "baseline_metric_count": len(baseline_metrics),
                "provided_metric_count": provided_metric_count,
                "passed_metric_count": passed_metric_count,
                "twm_metrics_source": twm_metric_source.get("source") or "payload" if twm_metrics else "none",
                "baseline_metrics_source": baseline_metric_source.get("source") or "payload" if baseline_metrics else "none",
                "twm_case_source": twm_case_source.get("source") or "none",
                "baseline_case_source": baseline_case_source.get("source") or "none",
                "twm_case_count": safe_int(twm_case_source.get("case_count"), 0),
                "baseline_case_count": safe_int(baseline_case_source.get("case_count"), 0),
                "metric_source_errors": {
                    "twm": twm_metric_source.get("error"),
                    "baseline": baseline_metric_source.get("error"),
                    "twm_cases": twm_case_source.get("error"),
                    "baseline_cases": baseline_case_source.get("error"),
                },
            },
            "metric_comparisons": metric_comparisons,
            "evidence_gate": {
                "status": status,
                "missing": list(dict.fromkeys(missing)),
                "claim_gate_clear": claim_gate_clear,
                "metrics_pass": enough_metrics,
            },
            "upgrade_decision": upgrade_decision,
            "claim_boundary": (
                "This report can compare metrics against a named baseline, but it does not upgrade TWM claims unless real-data gates "
                "and metric thresholds both pass."
            ),
            "next_actions": self._baseline_comparison_next_actions(upgrade_decision, baseline_id),
        }
        if truthy(payload.get("save_scenario") or payload.get("persist_scenario") or payload.get("save_run_card")):
            result["scenario_card"] = self._save_baseline_comparison_scenario(payload, result)
        return json.loads(_json(result))

    def baseline_evidence_pipeline_report(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        validation_payload = dict(payload)
        validation_payload["save_run_card"] = truthy(
            payload.get("save_validation_run_card")
            if "save_validation_run_card" in payload
            else payload.get("save_run_card") or payload.get("save_scenario") or payload.get("persist_scenario")
        )
        validation = self.baseline_export_validation_report(validation_payload)
        blocking_errors = list(validation.get("blocking_errors") or [])
        warnings = list(validation.get("warnings") or [])
        run_comparison = not blocking_errors and not truthy(payload.get("validate_only"))
        comparison: dict[str, Any] | None = None
        pipeline_status = "blocked" if blocking_errors else "review"
        pipeline_decision = "export_validation_blocked"
        if run_comparison:
            comparison_payload = dict(payload)
            comparison_payload["save_run_card"] = truthy(
                payload.get("save_comparison_run_card")
                if "save_comparison_run_card" in payload
                else payload.get("save_run_card") or payload.get("save_scenario") or payload.get("persist_scenario")
            )
            comparison = self.baseline_comparison_report(comparison_payload)
            pipeline_status = "pass" if comparison.get("upgrade_decision") == "eligible_for_retrospective_evidence" else "review"
            pipeline_decision = str(comparison.get("upgrade_decision") or "comparison_completed")
        elif not blocking_errors:
            pipeline_decision = "validation_passed_comparison_skipped"
        result = {
            "schema": "territory_world_model.baseline_evidence_pipeline_report.v1",
            "status": pipeline_status,
            "generated_at": now_utc_iso(),
            "claim_id": payload.get("claim_id") or validation.get("claim", {}).get("claim_id"),
            "baseline_id": payload.get("baseline_id") or validation.get("claim", {}).get("baseline_id"),
            "steps": {
                "export_validation": {
                    "status": validation.get("status"),
                    "blocking_errors": blocking_errors,
                    "warnings": warnings,
                    "scenario_card": validation.get("scenario_card"),
                },
                "baseline_comparison": {
                    "status": comparison.get("status") if comparison else "skipped",
                    "upgrade_decision": comparison.get("upgrade_decision") if comparison else None,
                    "scenario_card": comparison.get("scenario_card") if comparison else None,
                    "skipped_reason": "export_validation_blocked" if blocking_errors else "validate_only" if truthy(payload.get("validate_only")) else None,
                },
            },
            "export_validation": validation,
            "baseline_comparison": comparison,
            "pipeline_decision": pipeline_decision,
            "next_actions": self._baseline_evidence_pipeline_next_actions(validation, comparison),
            "claim_boundary": (
                "The pipeline enforces same-case export validation before metric comparison. A completed pipeline still does not upgrade "
                "TWM claims unless real-data gates, workflow need evidence and metric thresholds pass."
            ),
        }
        return json.loads(_json(result))

    def _load_case_metric_source(self, raw_path: Any) -> dict[str, Any]:
        path_text = compact_text(raw_path)
        if not path_text:
            return {"source": "", "metrics": {}, "case_count": 0}
        path = Path(path_text)
        if not path.is_absolute():
            path = self._repo_root() / path
        try:
            resolved = path.resolve()
            repo_root = self._repo_root().resolve()
            if repo_root not in resolved.parents and resolved != repo_root:
                return {"source": str(path_text), "metrics": {}, "case_count": 0, "error": "path_outside_repo"}
            if not resolved.exists():
                return {"source": str(path_text), "metrics": {}, "case_count": 0, "error": "file_not_found"}
            if resolved.suffix.lower() != ".csv":
                return {"source": str(path_text), "metrics": {}, "case_count": 0, "error": "unsupported_case_file"}
            records = read_csv(resolved)
            return {
                "source": str(path_text),
                "metrics": self._aggregate_case_metrics(records),
                "case_count": len(records),
            }
        except Exception as exc:
            return {"source": str(path_text), "metrics": {}, "case_count": 0, "error": str(exc)}

    def _aggregate_case_metrics(self, records: list[dict[str, Any]]) -> dict[str, float]:
        if not records:
            return {}
        positives = [row for row in records if self._row_truthy(row, ("ground_truth_conflict", "actual_conflict", "truth_conflict"))]
        detected_positives = [
            row for row in positives
            if self._row_truthy(row, ("detected_conflict", "predicted_conflict", "hit"))
        ]
        missed_positives = max(0, len(positives) - len(detected_positives))
        evidence_rows = [
            row for row in records
            if self._row_truthy(row, ("evidence_linked", "evidence_complete", "has_evidence"))
        ]
        unsupported_rows = [
            row for row in records
            if self._row_truthy(row, ("unsupported_recommendation", "unsupported_claim"))
        ]
        metrics: dict[str, float] = {}
        if positives:
            metrics["hard_constraint_conflict_recall"] = len(detected_positives) / len(positives)
            metrics["missed_blocking_conflict_rate"] = missed_positives / len(positives)
        metrics["evidence_link_completeness"] = len(evidence_rows) / len(records)
        metrics["audit_trail_completeness"] = len(evidence_rows) / len(records)
        metrics["unsupported_recommendation_rate"] = len(unsupported_rows) / len(records)
        review_precision = self._case_review_task_precision(records)
        if review_precision is not None:
            metrics["review_task_precision"] = review_precision
        triage_metrics = self._aggregate_candidate_triage_metrics(records)
        metrics.update(triage_metrics)
        return {key: round(value, 6) for key, value in metrics.items()}

    def _case_review_task_precision(self, records: list[dict[str, Any]]) -> float | None:
        predicted = [
            row for row in records
            if self._row_truthy(row, ("review_task_predicted", "review_predicted", "review_task_created"))
        ]
        if not predicted:
            return None
        true_positive = [
            row for row in predicted
            if self._row_truthy(row, ("review_task_true_positive", "review_true_positive", "review_needed", "needs_review"))
        ]
        return len(true_positive) / len(predicted)

    def _aggregate_candidate_triage_metrics(self, records: list[dict[str, Any]]) -> dict[str, float]:
        candidate_rows = [
            row for row in records
            if any(key in row for key in ("candidate_id", "ranking_score", "rank", "selected", "legal_feasible", "human_oracle_rank"))
        ]
        if not candidate_rows:
            return {}
        reason_rows = [
            row for row in candidate_rows
            if self._row_has_text(row, ("rejection_reason", "blocked_reason", "review_reason", "evidence_gap_reason", "constraint_reason"))
            or self._row_truthy(row, ("rejection_reason_covered", "reason_covered"))
        ]
        requires_reason = [
            row for row in candidate_rows
            if self._row_truthy(row, ("blocked", "illegal", "evidence_gap", "review_only"))
            or self._case_status(row) in {"blocked", "illegal", "review", "review_only", "conditional"}
        ]
        metrics: dict[str, float] = {}
        if requires_reason:
            covered = [
                row for row in requires_reason
                if row in reason_rows or self._row_truthy(row, ("rejection_reason_covered", "reason_covered"))
            ]
            metrics["candidate_rejection_reason_coverage"] = len(covered) / len(requires_reason)

        topk = self._topk_candidate_rows(candidate_rows)
        if topk:
            legal_topk = [
                row for row in topk
                if self._row_truthy(row, ("legal_feasible", "is_legal_feasible", "feasible", "allowed"))
                and not self._row_truthy(row, ("blocked", "illegal"))
            ]
            metrics["legal_feasible_topk_precision"] = len(legal_topk) / len(topk)

        regret_values = []
        for row in candidate_rows:
            regret = safe_float(row.get("planner_regret_against_human_oracle"), None)
            if regret is None:
                selected_utility = safe_float(row.get("selected_utility"), None)
                oracle_utility = safe_float(row.get("oracle_utility") or row.get("human_oracle_utility"), None)
                if selected_utility is not None and oracle_utility is not None:
                    regret = max(0.0, float(oracle_utility) - float(selected_utility))
            if regret is not None:
                regret_values.append(float(regret))
        if regret_values:
            metrics["planner_regret_against_human_oracle"] = sum(regret_values) / len(regret_values)
        return metrics

    def _topk_candidate_rows(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        scored: list[tuple[float, int, dict[str, Any]]] = []
        for idx, row in enumerate(records):
            selected = self._row_truthy(row, ("selected", "topk", "in_topk", "recommended"))
            rank = safe_float(row.get("rank") or row.get("candidate_rank"), None)
            score = safe_float(row.get("ranking_score") or row.get("score") or row.get("utility_score"), None)
            if selected:
                order = rank if rank is not None else idx
                scored.append((float(order), idx, row))
            elif rank is not None:
                scored.append((float(rank), idx, row))
            elif score is not None:
                scored.append((-float(score), idx, row))
        if not scored:
            return []
        selected_rows = [item for item in scored if self._row_truthy(item[2], ("selected", "topk", "in_topk", "recommended"))]
        if selected_rows:
            return [item[2] for item in sorted(selected_rows, key=lambda item: (item[0], item[1]))]
        ordered = sorted(scored, key=lambda item: (item[0], item[1]))
        topk = min(3, len(ordered))
        return [item[2] for item in ordered[:topk]]

    def _row_truthy(self, row: dict[str, Any], keys: Iterable[str]) -> bool:
        return any(truthy(row.get(key)) for key in keys if key in row)

    def _row_has_text(self, row: dict[str, Any], keys: Iterable[str]) -> bool:
        return any(bool(compact_text(row.get(key))) for key in keys if key in row)

    def _case_status(self, row: dict[str, Any]) -> str:
        return compact_text(row.get("case_status") or row.get("candidate_status") or row.get("status")).lower()

    def _load_metric_source(self, raw_path: Any) -> dict[str, Any]:
        path_text = compact_text(raw_path)
        if not path_text:
            return {"source": "", "metrics": {}}
        path = Path(path_text)
        if not path.is_absolute():
            path = self._repo_root() / path
        try:
            resolved = path.resolve()
            repo_root = self._repo_root().resolve()
            if repo_root not in resolved.parents and resolved != repo_root:
                return {"source": str(path_text), "metrics": {}, "error": "path_outside_repo"}
            if not resolved.exists():
                return {"source": str(path_text), "metrics": {}, "error": "file_not_found"}
            if resolved.suffix.lower() == ".csv":
                return {"source": str(path_text), "metrics": self._load_metric_csv(resolved)}
            if resolved.suffix.lower() == ".json":
                return {"source": str(path_text), "metrics": self._normalize_metric_payload(read_json(resolved))}
        except Exception as exc:
            return {"source": str(path_text), "metrics": {}, "error": str(exc)}
        return {"source": str(path_text), "metrics": {}, "error": "unsupported_metric_file"}

    def _load_metric_csv(self, path: Path) -> dict[str, float]:
        records = read_csv(path)
        metrics: dict[str, float] = {}
        if not records:
            return metrics
        first = records[0]
        metric_key = next((key for key in ("metric", "metric_name", "name") if key in first), "")
        value_key = next((key for key in ("value", "score", "metric_value") if key in first), "")
        if metric_key and value_key:
            for row in records:
                name = compact_text(row.get(metric_key))
                value = safe_float(row.get(value_key), None)
                if name and value is not None:
                    metrics[name] = float(value)
            return metrics
        for key, raw in first.items():
            value = safe_float(raw, None)
            if value is not None:
                metrics[str(key)] = float(value)
        return metrics

    def _normalize_metric_payload(self, value: Any) -> dict[str, float]:
        if not isinstance(value, dict):
            return {}
        candidates: dict[str, Any] = {}
        for key in ("metrics", "summary", "scores", "result"):
            if isinstance(value.get(key), dict):
                candidates.update(value[key])
        candidates.update(value)
        normalized: dict[str, float] = {}
        for key, raw in candidates.items():
            num = safe_float(raw, None)
            if num is not None:
                normalized[str(key)] = float(num)
        return normalized

    def _compare_research_metric(self, metric: dict[str, Any], twm_metrics: dict[str, float], baseline_metrics: dict[str, float]) -> dict[str, Any]:
        name = str(metric.get("name") or "")
        direction = str(metric.get("direction") or "higher_is_better")
        twm_value = twm_metrics.get(name)
        baseline_value = baseline_metrics.get(name)
        threshold_key = "minimum_pass" if direction == "higher_is_better" else "maximum_pass"
        threshold = safe_float(metric.get(threshold_key), None)
        if twm_value is None or baseline_value is None:
            return {
                "name": name,
                "direction": direction,
                "status": "missing",
                "twm_value": twm_value,
                "baseline_value": baseline_value,
                "threshold": threshold,
                "delta": None,
            }
        if direction == "lower_is_better":
            delta = round(baseline_value - twm_value, 6)
            threshold_pass = threshold is None or twm_value <= threshold
            baseline_lift = twm_value < baseline_value
        else:
            delta = round(twm_value - baseline_value, 6)
            threshold_pass = threshold is None or twm_value >= threshold
            baseline_lift = twm_value > baseline_value
        status = "pass" if threshold_pass and baseline_lift else "review"
        return {
            "name": name,
            "direction": direction,
            "status": status,
            "twm_value": round(twm_value, 6),
            "baseline_value": round(baseline_value, 6),
            "threshold": threshold,
            "delta": delta,
            "threshold_pass": threshold_pass,
            "baseline_lift": baseline_lift,
        }

    def _baseline_export_spec(
        self,
        export_types: list[dict[str, Any]],
        export_type_id: str,
        baseline_id: str,
        claim_id: str,
    ) -> dict[str, Any]:
        if export_type_id:
            for item in export_types:
                if item.get("export_type") == export_type_id:
                    return dict(item)
        if baseline_id:
            for item in export_types:
                if item.get("baseline_id") == baseline_id:
                    return dict(item)
        for item in export_types:
            if claim_id in set(item.get("compatible_claims") or []):
                return dict(item)
        return dict(export_types[0]) if export_types else {}

    def _baseline_export_template_public(
        self,
        template: dict[str, Any],
        claims_by_id: dict[str, dict[str, Any]],
        baselines_by_id: dict[str, dict[str, Any]],
        export_types: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        export_type = str(template.get("export_type") or "")
        export_spec = dict(export_types.get(export_type) or {})
        claim_id = str(template.get("claim_id") or "")
        baseline_id = str(template.get("baseline_id") or "")
        twm_header = [str(item) for item in template.get("twm_header", [])]
        baseline_header = [str(item) for item in template.get("baseline_header", [])]
        required_columns = list(dict.fromkeys(
            [str(item) for item in export_spec.get("required_columns", [])]
            + self._claim_export_required_columns(claim_id)
        ))
        recommended_columns = list(dict.fromkeys([str(item) for item in export_spec.get("recommended_columns", [])]))
        return {
            **template,
            "claim": claims_by_id.get(claim_id, {}),
            "baseline": baselines_by_id.get(baseline_id, {}),
            "export_spec": {
                "export_type": export_type,
                "baseline_id": baseline_id,
                "label": export_spec.get("label") or template.get("label"),
                "required_columns": required_columns,
                "recommended_columns": recommended_columns,
                "compatible_claims": export_spec.get("compatible_claims") or [claim_id],
            },
            "required_columns": required_columns,
            "recommended_columns": recommended_columns,
            "headers": {
                "twm": twm_header,
                "baseline": baseline_header,
            },
            "csv_header": {
                "twm": ",".join(twm_header),
                "baseline": ",".join(baseline_header),
            },
            "validation_payload_template": {
                "claim_id": claim_id,
                "baseline_id": baseline_id,
                "export_type": export_type,
                "twm_case_output_path": f"data_agent/uploads/twm_baseline_exports/<user>/<batch>/{template.get('twm_filename')}",
                "baseline_case_output_path": f"data_agent/uploads/twm_baseline_exports/<user>/<batch>/{template.get('baseline_filename')}",
            },
            "minimum_real_data_gate": {
                "same_case_join_key": template.get("same_case_join_key"),
                "minimum_overlap_ratio": template.get("production_collection", {}).get(
                    "minimum_overlap_ratio",
                    0.8,
                ),
                "minimum_real_rows": template.get("production_collection", {}).get("minimum_real_rows"),
                "claim_gate_missing": claims_by_id.get(claim_id, {}).get("gate", {}).get("missing", []),
            },
            "not_for_production": True,
        }

    def _safe_baseline_export_filename(self, filename: str) -> str:
        name = Path(filename).name or "baseline_export.csv"
        if not name.lower().endswith(".csv"):
            name = f"{Path(name).stem or 'baseline_export'}.csv"
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
        return name[:120] or "baseline_export.csv"

    def _safe_baseline_export_token(self, value: Any) -> str:
        token = re.sub(r"[^A-Za-z0-9._-]+", "_", compact_text(value))
        return token.strip("._-")[:80] or "default"

    def _load_baseline_export_records(self, raw_path: Any) -> dict[str, Any]:
        path_text = compact_text(raw_path)
        if not path_text:
            return {"source": "", "records": [], "error": "path_required"}
        path = Path(path_text)
        if not path.is_absolute():
            path = self._repo_root() / path
        try:
            resolved = path.resolve()
            repo_root = self._repo_root().resolve()
            if repo_root not in resolved.parents and resolved != repo_root:
                return {"source": path_text, "records": [], "error": "path_outside_repo"}
            if not resolved.exists():
                return {"source": path_text, "records": [], "error": "file_not_found"}
            if resolved.suffix.lower() != ".csv":
                return {"source": path_text, "records": [], "error": "unsupported_export_file"}
            records = read_csv(resolved)
            return {"source": path_text, "resolved_path": str(resolved), "records": records}
        except Exception as exc:
            return {"source": path_text, "records": [], "error": str(exc)}

    def _baseline_export_join_key(
        self,
        twm_source: dict[str, Any],
        baseline_source: dict[str, Any],
        export_spec: dict[str, Any],
    ) -> str:
        twm_columns = self._record_columns(twm_source.get("records", []))
        baseline_columns = self._record_columns(baseline_source.get("records", []))
        common = twm_columns & baseline_columns
        preferred = ["case_id", "candidate_id", "project_id", "scenario_id"]
        required_columns = set(export_spec.get("required_columns") or [])
        if "candidate_id" in required_columns:
            preferred = ["candidate_id", "case_id", "scenario_id", "project_id"]
        for key in preferred:
            if key in common:
                return key
        return ""

    def _baseline_export_record_inventory(self, records: list[dict[str, Any]], join_key: str) -> dict[str, Any]:
        columns = sorted(self._record_columns(records))
        join_ids: list[str] = []
        if join_key:
            for row in records:
                value = compact_text(row.get(join_key))
                if value:
                    join_ids.append(value)
        duplicate_ids = sorted({item for item in join_ids if join_ids.count(item) > 1})
        not_for_production_rows = [
            row for row in records
            if self._row_truthy(row, ("not_for_production", "synthetic", "is_synthetic"))
            or compact_text(row.get("sanitization_level")).lower() in {"sanitized", "anonymous", "anonymized", "deidentified", "de-identified"}
        ]
        synthetic_rows = [
            row for row in records
            if self._row_truthy(row, ("synthetic", "is_synthetic"))
            or compact_text(row.get("sample_type")).lower().startswith("synthetic")
            or "synthetic" in compact_text(row.get("sanitization_level") or row.get("data_class")).lower()
        ]
        return {
            "row_count": len(records),
            "columns": columns,
            "join_id_count": len(join_ids),
            "unique_join_id_count": len(set(join_ids)),
            "duplicate_join_ids": duplicate_ids[:20],
            "not_for_production_rows": len(not_for_production_rows),
            "synthetic_rows": len(synthetic_rows),
            "_join_ids": sorted(set(join_ids)),
        }

    def _baseline_export_public_inventory(self, inventory: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in inventory.items() if not str(key).startswith("_")}

    def _baseline_export_overlap(self, twm_inventory: dict[str, Any], baseline_inventory: dict[str, Any]) -> dict[str, Any]:
        # The inventories intentionally expose counts only. Recompute IDs from callers' records would leak no extra
        # detail, but keeping overlap summarized avoids returning large/sensitive case lists through the API.
        return self._baseline_export_overlap_from_ids(
            set(twm_inventory.get("_join_ids") or []),
            set(baseline_inventory.get("_join_ids") or []),
            twm_inventory,
            baseline_inventory,
        )

    def _baseline_export_overlap_from_ids(
        self,
        twm_ids: set[str],
        baseline_ids: set[str],
        twm_inventory: dict[str, Any],
        baseline_inventory: dict[str, Any],
    ) -> dict[str, Any]:
        if not twm_ids or not baseline_ids:
            return {
                "overlap_count": 0,
                "twm_unique_case_count": len(twm_ids),
                "baseline_unique_case_count": len(baseline_ids),
                "coverage_ratio": 0.0,
                "twm_only_count": len(twm_ids),
                "baseline_only_count": len(baseline_ids),
            }
        overlap = twm_ids & baseline_ids
        denominator = max(1, min(len(twm_ids), len(baseline_ids)))
        return {
            "overlap_count": len(overlap),
            "twm_unique_case_count": len(twm_ids),
            "baseline_unique_case_count": len(baseline_ids),
            "coverage_ratio": round(len(overlap) / denominator, 6),
            "twm_only_count": len(twm_ids - baseline_ids),
            "baseline_only_count": len(baseline_ids - twm_ids),
            "sample_overlap_ids": sorted(overlap)[:10],
        }

    def _record_columns(self, records: list[dict[str, Any]]) -> set[str]:
        columns: set[str] = set()
        for row in records:
            columns.update(str(key) for key in row.keys())
        return columns

    def _missing_columns(self, columns: Iterable[str], required: Iterable[str]) -> list[str]:
        present = set(columns)
        return [str(item) for item in required if str(item) not in present]

    def _claim_export_required_columns(self, claim_id: str) -> list[str]:
        if claim_id == "C3_action_conditioned_triage":
            return ["candidate_id", "rank", "legal_feasible", "planner_regret_against_human_oracle"]
        if claim_id == "C2_audit_defensibility":
            return ["case_id", "evidence_linked", "unsupported_recommendation", "review_task_predicted"]
        return ["case_id", "ground_truth_conflict", "detected_conflict", "evidence_linked"]

    def _baseline_export_parser_probe(
        self,
        twm_source: dict[str, Any],
        baseline_source: dict[str, Any],
        claim: dict[str, Any],
    ) -> dict[str, Any]:
        twm_metrics = self._aggregate_case_metrics(twm_source.get("records", []))
        baseline_metrics = self._aggregate_case_metrics(baseline_source.get("records", []))
        claim_metric_names = [str(item.get("name") or "") for item in claim.get("metrics", []) if item.get("name")]
        comparable = [name for name in claim_metric_names if name in twm_metrics and name in baseline_metrics]
        return {
            "status": "pass" if comparable else "review",
            "claim_metric_names": claim_metric_names,
            "comparable_metrics": comparable,
            "twm_recovered_metrics": sorted(twm_metrics),
            "baseline_recovered_metrics": sorted(baseline_metrics),
        }

    def _baseline_export_source_summary(self, source: dict[str, Any]) -> dict[str, Any]:
        return {
            "source": source.get("source") or "",
            "resolved_path": source.get("resolved_path"),
            "row_count": len(source.get("records", [])),
            "error": source.get("error"),
        }

    def _baseline_export_validation_next_actions(
        self,
        status: str,
        blocking_errors: list[str],
        warnings: list[str],
    ) -> list[str]:
        if status == "pass":
            return [
                "run baseline_comparison_report on the validated same-case exports",
                "package metrics, case coverage and workflow notes for mentor/external review",
            ]
        actions: list[str] = []
        if any("missing_required_columns" in item for item in blocking_errors):
            actions.append("export the missing required columns from the TWM and baseline systems")
        if any("same_case" in item for item in blocking_errors):
            actions.append("join TWM and baseline outputs on the same historical case or candidate IDs")
        if any("path" in item or "file" in item for item in blocking_errors):
            actions.append("provide readable CSV exports inside the repository workspace")
        if any("claim_parser_columns" in item for item in warnings):
            actions.append("add the claim-specific parser columns before using this export for metric evidence")
        if any("not_for_production" in item for item in warnings):
            actions.append("mark whether the export is sanitized, internal-review-only or synthetic regression data")
        actions.append("keep TWM claims at prototype scaffold level until validation passes on real or sanitized same-case data")
        return list(dict.fromkeys(actions))

    def _baseline_evidence_pipeline_next_actions(
        self,
        validation: dict[str, Any],
        comparison: dict[str, Any] | None,
    ) -> list[str]:
        blocking_errors = list(validation.get("blocking_errors") or [])
        if blocking_errors:
            return [
                "fix export validation blockers before running metric comparison",
                *list(validation.get("next_actions") or [])[:3],
            ]
        if comparison is None:
            return [
                "run baseline comparison after reviewing export validation warnings",
                *list(validation.get("next_actions") or [])[:2],
            ]
        decision = str(comparison.get("upgrade_decision") or "")
        if decision == "metrics_pass_but_data_gate_blocks_upgrade":
            return [
                "keep this result as regression evidence until real production history gates pass",
                *list(comparison.get("next_actions") or [])[:2],
            ]
        if decision == "no_metric_lift_over_baseline":
            return [
                "do not add model complexity until the simpler baseline gap is understood",
                *list(comparison.get("next_actions") or [])[:2],
            ]
        if decision == "eligible_for_retrospective_evidence":
            return [
                "package validation and comparison run cards for external review",
                "repeat on held-out region/time split before any pilot claim",
            ]
        return list(comparison.get("next_actions") or validation.get("next_actions") or [])

    def _save_baseline_export_validation_scenario(self, payload: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
        project_id = compact_text(payload.get("project_id"))
        state_version_id = compact_text(payload.get("base_state_version_id") or payload.get("state_version_id"))
        claim = dict(report.get("claim") or {})
        export_spec = dict(report.get("export_spec") or {})
        sources = dict(report.get("sources") or {})
        scenario = TwmScenario(
            project_id=project_id,
            base_state_version_id=state_version_id,
            name=compact_text(payload.get("scenario_name"))
            or f"Baseline export validation: {claim.get('claim_id') or 'claim'} vs {export_spec.get('baseline_id') or 'baseline'}",
            scenario_type="baseline_export_validation",
            input_changes={
                "claim_id": claim.get("claim_id"),
                "baseline_id": claim.get("baseline_id") or export_spec.get("baseline_id"),
                "export_type": export_spec.get("export_type"),
                "twm_case_output_path": payload.get("twm_case_output_path") or payload.get("twm_case_result_path"),
                "baseline_case_output_path": payload.get("baseline_case_output_path") or payload.get("baseline_case_result_path"),
            },
            source_model="territory_world_model.baseline_export_validation_report.v1",
            status=str(report.get("status") or "review"),
            metadata={
                "kind": "baseline_export_validation_run_card",
                "report_schema": report.get("schema"),
                "generated_at": report.get("generated_at"),
                "claim": claim,
                "export_spec": export_spec,
                "sources": sources,
                "column_inventory": report.get("column_inventory") or {},
                "coverage": report.get("coverage") or {},
                "parser_compatibility": report.get("parser_compatibility") or {},
                "blocking_errors": report.get("blocking_errors") or [],
                "warnings": report.get("warnings") or [],
                "next_actions": report.get("next_actions") or [],
                "claim_boundary": report.get("claim_boundary"),
                "not_for_production": True,
            },
        )
        saved = self.repository.save_scenario(scenario)
        return {
            "scenario_id": saved.id,
            "scenario_type": saved.scenario_type,
            "status": saved.status,
            "metadata_kind": saved.metadata.get("kind"),
        }

    def _baseline_comparison_next_actions(self, upgrade_decision: str, baseline_id: str) -> list[str]:
        if upgrade_decision == "eligible_for_retrospective_evidence":
            return [
                "package case-level evidence and baseline outputs for external review",
                "repeat on a held-out region/time split before pilot claim",
            ]
        if upgrade_decision == "metrics_pass_but_data_gate_blocks_upgrade":
            return [
                "collect real or sanitized production history required by the claim gate",
                f"keep {baseline_id or 'baseline'} comparison as synthetic/regression evidence only",
            ]
        if upgrade_decision == "no_metric_lift_over_baseline":
            return [
                "inspect failed metrics and simplify the TWM claim",
                "do not add new model backends until the baseline gap is understood",
            ]
        return [
            "provide both TWM metrics and named baseline metrics for the same cases",
            "keep the claim at prototype scaffold level",
        ]

    def _save_baseline_comparison_scenario(self, payload: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
        project_id = compact_text(payload.get("project_id"))
        state_version_id = compact_text(payload.get("base_state_version_id") or payload.get("state_version_id"))
        claim = dict(report.get("claim") or {})
        baseline = dict(report.get("baseline") or {})
        inputs = dict(report.get("inputs") or {})
        scenario = TwmScenario(
            project_id=project_id,
            base_state_version_id=state_version_id,
            name=compact_text(payload.get("scenario_name"))
            or f"Baseline comparison: {claim.get('claim_id') or 'claim'} vs {baseline.get('baseline_id') or 'baseline'}",
            scenario_type="baseline_comparison",
            input_changes={
                "claim_id": claim.get("claim_id"),
                "baseline_id": baseline.get("baseline_id"),
                "twm_metrics_path": payload.get("twm_metrics_path") or payload.get("twm_result_path"),
                "baseline_metrics_path": payload.get("baseline_metrics_path") or payload.get("baseline_result_path"),
                "twm_case_output_path": payload.get("twm_case_output_path") or payload.get("twm_case_result_path"),
                "baseline_case_output_path": payload.get("baseline_case_output_path") or payload.get("baseline_case_result_path"),
            },
            source_model="territory_world_model.baseline_comparison_report.v1",
            status=str(report.get("upgrade_decision") or report.get("status") or "review"),
            metadata={
                "kind": "baseline_comparison_run_card",
                "report_schema": report.get("schema"),
                "generated_at": report.get("generated_at"),
                "claim": claim,
                "baseline": baseline,
                "baseline_sources": {
                    "twm_metrics_source": inputs.get("twm_metrics_source"),
                    "baseline_metrics_source": inputs.get("baseline_metrics_source"),
                    "twm_case_source": inputs.get("twm_case_source"),
                    "baseline_case_source": inputs.get("baseline_case_source"),
                    "twm_case_count": inputs.get("twm_case_count"),
                    "baseline_case_count": inputs.get("baseline_case_count"),
                    "metric_source_errors": inputs.get("metric_source_errors"),
                },
                "metric_comparisons": report.get("metric_comparisons") or [],
                "evidence_gate": report.get("evidence_gate") or {},
                "upgrade_decision": report.get("upgrade_decision"),
                "claim_boundary": report.get("claim_boundary"),
                "not_for_production": True,
            },
        )
        saved = self.repository.save_scenario(scenario)
        return {
            "scenario_id": saved.id,
            "scenario_type": saved.scenario_type,
            "status": saved.status,
            "metadata_kind": saved.metadata.get("kind"),
        }

    def _research_claim_with_gate(self, claim: dict[str, Any], production_rows: int, policy_rows: int) -> dict[str, Any]:
        missing_gate: list[str] = []
        if production_rows <= 0:
            missing_gate.append("production_observed_history")
        if claim["claim_id"] == "C3_action_conditioned_triage" and policy_rows <= 0:
            missing_gate.append("production_policy_action_labels")
        if claim["claim_id"] in {"C1_state_conflict_recall", "C2_audit_defensibility"}:
            missing_gate.append("named_real_workflow_baseline")
        if claim["claim_id"] == "C4_standard_contract_ingestion":
            missing_gate.append("cross_region_standard_samples")
        gate_status = "review" if missing_gate else "candidate"
        return {
            **claim,
            "gate": {
                "status": gate_status,
                "claim_level": "prototype_scaffold" if missing_gate else "retrospective_candidate",
                "missing": missing_gate,
                "production_rows": production_rows,
                "policy_rows": policy_rows,
            },
        }

    def data_foundation_assessment(self) -> dict[str, Any]:
        validation = self._load_data_foundation_validation()
        validation_summary = validation.get("summary", {}) if isinstance(validation, dict) else {}
        dataset_summaries = [self._data_foundation_dataset_summary(item) for item in TWM_DATA_FOUNDATION_DATASETS]
        production_rows = safe_int(validation_summary.get("twm_production_ready_observed_history_rows"), 0)
        policy_rows = safe_int(validation_summary.get("production_policy_history_row_count"), 0)
        synthetic_rows = safe_int(validation_summary.get("twm_synthetic_experiment_row_count"), 0)
        structural_rows = safe_int(validation_summary.get("twm_structural_fixture_row_count"), 0)
        structural_status = str(validation_summary.get("twm_structural_fixture_structural_status") or "unknown")
        synthetic_status = str(validation_summary.get("twm_synthetic_experiment_structural_status") or "unknown")
        status = "review"
        if production_rows > 0 and policy_rows > 0:
            status = "candidate"
        if production_rows >= 1000 and policy_rows >= 100 and structural_status == "pass" and synthetic_status == "pass":
            status = "ready_for_pilot_validation"
        landing_readiness = {
            "status": status,
            "verdict": (
                "当前数据基础足以支撑 TWM 工程化原型、规则/证据/审计链路和合成实验验证；"
                "不足以支撑生产级审批结论、真实预测效果或真实因果改进声明。"
            ),
            "production_deployment_supported": False,
            "engineering_mvp_supported": True,
            "business_review_scaffold_supported": True,
            "predictive_or_causal_claim_supported": False,
            "key_blockers": [
                "生产可用观察历史行数为 0",
                "生产政策动作历史未提供",
                "关键审批、复核、规则评价和项目样本主要为 synthetic/not-for-production",
                "尚缺真实 workflow baseline 对比来证明未满足需求与改进幅度",
            ],
        }
        if production_rows > 0:
            landing_readiness["key_blockers"][0] = f"生产可用观察历史行数仍不足：{production_rows}"
        if policy_rows > 0:
            landing_readiness["key_blockers"][1] = f"生产政策动作历史仍不足：{policy_rows}"

        result = {
            "schema": "territory_world_model.data_foundation_assessment.v1",
            "status": status,
            "generated_at": now_utc_iso(),
            "landing_readiness": landing_readiness,
            "datasets": dataset_summaries,
            "validation_snapshot": {
                "source": "docs/reports/twm_data_foundation_validation.json",
                "status": validation_summary.get("status", "unknown"),
                "production_ready_observed_history_rows": production_rows,
                "production_policy_history_status": validation_summary.get("production_policy_history_status", "not_provided"),
                "production_policy_history_row_count": policy_rows,
                "production_policy_allowed_count": safe_int(validation_summary.get("production_policy_history_allowed_count"), 0),
                "production_policy_blocked_count": safe_int(validation_summary.get("production_policy_history_blocked_count"), 0),
                "structural_fixture": {
                    "row_count": structural_rows,
                    "pair_count": safe_int(validation_summary.get("twm_structural_fixture_pair_count"), 0),
                    "structural_status": structural_status,
                    "default_status": validation_summary.get("twm_structural_fixture_default_status", "unknown"),
                },
                "synthetic_experiment": {
                    "row_count": synthetic_rows,
                    "pair_count": safe_int(validation_summary.get("twm_synthetic_experiment_pair_count"), 0),
                    "region_count": safe_int(validation_summary.get("twm_synthetic_experiment_region_count"), 0),
                    "period_count": safe_int(validation_summary.get("twm_synthetic_experiment_period_count"), 0),
                    "split_counts": validation_summary.get("twm_synthetic_experiment_split_counts", {}),
                    "action_mask_allowed_count": safe_int(validation_summary.get("twm_synthetic_experiment_action_mask_allowed_count"), 0),
                    "action_mask_blocked_count": safe_int(validation_summary.get("twm_synthetic_experiment_action_mask_blocked_count"), 0),
                    "structural_status": synthetic_status,
                    "default_status": validation_summary.get("twm_synthetic_experiment_default_status", "unknown"),
                },
                "local_observed_history": {
                    "status": validation_summary.get("twm_observed_history_status", "unknown"),
                    "missing": validation_summary.get("twm_observed_history_missing", []),
                    "relation_neighbor_edge_count": safe_int(validation_summary.get("twm_relation_neighbor_edge_count"), 0),
                },
                "project_review_context": {
                    "project_count": safe_int(validation_summary.get("twm_project_review_context_project_count"), 0),
                    "rule_eval_count": safe_int(validation_summary.get("twm_project_review_context_rule_eval_count"), 0),
                    "review_task_count": safe_int(validation_summary.get("twm_project_review_context_review_task_count"), 0),
                },
                "external_support": {
                    "paper7_caliper_matched_status": validation_summary.get("paper7_caliper_matched_status", "unknown"),
                    "paper7_caliper_matched_pair_count": safe_int(validation_summary.get("paper7_caliper_matched_pair_count"), 0),
                    "boundary": "Paper7 可作为因果校准分支外部支持，但不能替代 TWM 生产审批历史验证。",
                },
            },
            "supported_problems": list(TWM_DATA_FOUNDATION_SUPPORTED_PROBLEMS),
            "unsupported_claims": list(TWM_DATA_FOUNDATION_UNSUPPORTED_CLAIMS),
            "problem_data_fit": [
                {
                    "business_problem": "耕地保护与占补平衡审查",
                    "current_fit": "partial",
                    "why": "图斑、PBF、生态红线、项目、规则命中和证据链结构齐备，但关键边界和审批记录仍非生产数据。",
                    "safe_output": "风险暴露、证据缺口、人工复核任务和候选方案审计。",
                    "unsafe_output": "自动审批通过/不通过或真实政策效果承诺。",
                },
                {
                    "business_problem": "建设项目用地合规预审",
                    "current_fit": "partial",
                    "why": "可模拟项目-分区-边界-复核任务关系，但缺真实项目流转、补正、处置和监管闭环历史。",
                    "safe_output": "合规预审工作流原型和审查清单。",
                    "unsafe_output": "生产级项目合规结论。",
                },
                {
                    "business_problem": "国土空间用途调整推演",
                    "current_fit": "experimental",
                    "why": "合成多期样本可测动作条件动态和 planner consumer，但缺真实跨期状态和政策动作标签。",
                    "safe_output": "反事实推演管线、action-mask 和 beam-plan 方法验证。",
                    "unsafe_output": "真实区域规划效果预测。",
                },
            ],
            "required_next_data": list(TWM_DATA_FOUNDATION_REQUIRED_NEXT_DATA),
            "mentor_answer": {
                "short_answer": (
                    "目前 TWM 靠谱的部分是工程和研究假设验证，不是生产落地证明。"
                    "数据基础能说明 TWM 的对象-关系-规则-证据框架可跑通，也能暴露哪些业务问题需要真实数据继续验证；"
                    "但在真实审批历史和政策动作标签缺失前，不能声称它已经解决真实国土治理决策。"
                ),
                "research_judgment": (
                    "下一阶段应把研究问题收敛到真实未满足需求：跨图层规则审查、证据链完整性、审查任务优先级和方案不可行原因解释。"
                    "这些问题需要用真实或脱敏业务样本与 manual/rule-only/simulator/optimizer baseline 对比。"
                ),
            },
            "source_reports": {
                "health_markdown": "docs/reports/twm_data_foundation_health.md",
                "validation_json": "docs/reports/twm_data_foundation_validation.json",
            },
        }
        return json.loads(_json(result))

    def data_foundation_lineage_report(self, dataset_id: str) -> dict[str, Any]:
        dataset_id = compact_text(dataset_id)
        spec = next((item for item in TWM_DATA_FOUNDATION_DATASETS if item.get("id") == dataset_id), None)
        if spec is None:
            raise LookupError(f"data foundation dataset not found: {dataset_id}")

        assessment = self.data_foundation_assessment()
        validation = dict(assessment.get("validation_snapshot") or {})
        summary = next((item for item in assessment.get("datasets", []) if item.get("id") == dataset_id), None)
        if summary is None:
            summary = self._data_foundation_dataset_summary(spec)

        spatial_by_path = {
            str(layer.get("path") or layer.get("name") or ""): layer
            for layer in summary.get("spatial_layer_catalog", [])
            if layer.get("path") or layer.get("name")
        }
        files: list[dict[str, Any]] = []
        for item in summary.get("files", []):
            rel_path = str(item.get("path") or "")
            unit = str(item.get("unit") or "")
            exists = bool(item.get("exists"))
            count = safe_int(item.get("count"), 0)
            synthetic_count = safe_int(item.get("synthetic_count"), 0)
            not_for_production_count = safe_int(item.get("not_for_production_count"), 0)
            spatial_layer = spatial_by_path.get(rel_path) or {}
            source_role = "spatial_layer" if unit == "feature" else "auxiliary_table" if unit == "row" else "supporting_file"
            if not exists:
                lineage_status = "missing"
            elif bool(summary.get("not_for_production", True)) or synthetic_count > 0 or not_for_production_count > 0:
                lineage_status = "review_not_for_production"
            else:
                lineage_status = "candidate_authoritative"
            row = {
                "path": rel_path,
                "unit": unit,
                "source_role": source_role,
                "exists": exists,
                "count": count,
                "synthetic_count": synthetic_count,
                "not_for_production_count": not_for_production_count,
                "lineage_status": lineage_status,
                "source_nature": spec.get("nature"),
                "dataset_root": spec.get("path"),
                "not_for_production": bool(summary.get("not_for_production", True)) or not_for_production_count > 0,
                "readiness_note": (
                    "可用于字段、空间范围和链路回归核查；not_for_production 数据不得作为生产治理结论。"
                    if lineage_status == "review_not_for_production"
                    else "缺失文件需先补齐后才能进入数据基础核查。"
                    if lineage_status == "missing"
                    else "候选权威来源仍需人工验收数据版本、来源证明和权限边界。"
                ),
            }
            if spatial_layer:
                row.update({
                    "bbox": spatial_layer.get("bbox"),
                    "crs_diagnostic": spatial_layer.get("crs_diagnostic"),
                    "property_field_count": spatial_layer.get("property_field_count"),
                    "sample_properties": spatial_layer.get("sample_properties"),
                })
            files.append(row)

        production_rows = safe_int(validation.get("production_ready_observed_history_rows"), 0)
        policy_rows = safe_int(validation.get("production_policy_history_row_count"), 0)
        map_overlay_readiness = summary.get("map_overlay_readiness") or {}
        nonproduction_count = safe_int(summary.get("not_for_production_count"), 0)
        synthetic_count = safe_int(summary.get("synthetic_count"), 0)
        lineage_status = "review_not_for_production" if bool(summary.get("not_for_production", True)) or nonproduction_count > 0 else "candidate_authoritative"
        readiness_gates = [
            {
                "id": "authoritative_source_lineage",
                "status": "blocked" if lineage_status == "review_not_for_production" else "review",
                "current_value": f"{nonproduction_count} not-for-production records; {synthetic_count} synthetic records",
                "required_value": "source authority, data version, update time, permission boundary and custodian sign-off for each production layer/table",
            },
            {
                "id": "production_observed_history",
                "status": "blocked" if production_rows <= 0 else "partial",
                "current_value": production_rows,
                "required_value": "real or sanitized approval/review/remediation/enforcement history with final outcomes",
            },
            {
                "id": "production_policy_action_labels",
                "status": "blocked" if policy_rows <= 0 else "partial",
                "current_value": policy_rows,
                "required_value": "authoritative policy/action feasibility labels for TWM action-conditioned validation",
            },
            {
                "id": "map_overlay_crs",
                "status": "ready" if map_overlay_readiness.get("status") == "ready" else "blocked",
                "current_value": map_overlay_readiness.get("message", ""),
                "required_value": "all spatial layers have known CRS and can be converted to the map display CRS",
            },
        ]
        return json.loads(_json({
            "schema": "territory_world_model.data_foundation_lineage_report.v1",
            "generated_at": now_utc_iso(),
            "dataset_id": dataset_id,
            "dataset_label": spec.get("label"),
            "dataset_root": spec.get("path"),
            "source_nature": spec.get("nature"),
            "positioning": spec.get("positioning"),
            "not_for_production": bool(summary.get("not_for_production", True)),
            "file_count": safe_int(summary.get("file_count"), len(files)),
            "spatial_layer_count": sum(1 for item in files if item.get("source_role") == "spatial_layer"),
            "table_count": sum(1 for item in files if item.get("source_role") == "auxiliary_table"),
            "total_record_count": safe_int(summary.get("total_count"), 0),
            "synthetic_record_count": synthetic_count,
            "not_for_production_record_count": nonproduction_count,
            "lineage_coverage": {
                "status": lineage_status,
                "file_count": len(files),
                "existing_file_count": sum(1 for item in files if item.get("exists")),
                "missing_file_count": sum(1 for item in files if not item.get("exists")),
                "authoritative_source_count": sum(1 for item in files if item.get("lineage_status") == "candidate_authoritative"),
                "review_only_source_count": sum(1 for item in files if item.get("lineage_status") == "review_not_for_production"),
            },
            "map_overlay_readiness": map_overlay_readiness,
            "readiness_gates": readiness_gates,
            "files": files,
            "required_next_data": list(TWM_DATA_FOUNDATION_REQUIRED_NEXT_DATA),
            "claim_boundary": (
                "Lineage report supports source review, field mapping, CRS readiness and production onboarding planning; "
                "it does not upgrade not-for-production datasets into authoritative evidence."
            ),
        }))

    def data_foundation_crs_remediation_plan(self, dataset_id: str) -> dict[str, Any]:
        dataset_id = compact_text(dataset_id)
        spec = next((item for item in TWM_DATA_FOUNDATION_DATASETS if item.get("id") == dataset_id), None)
        if spec is None:
            raise LookupError(f"data foundation dataset not found: {dataset_id}")

        assessment = self.data_foundation_assessment()
        summary = next((item for item in assessment.get("datasets", []) if item.get("id") == dataset_id), None)
        if summary is None:
            summary = self._data_foundation_dataset_summary(spec)

        target_crs = "EPSG:4326"
        layers: list[dict[str, Any]] = []
        for layer in summary.get("spatial_layer_catalog", []):
            layer_path = str(layer.get("path") or layer.get("name") or "")
            if not layer_path:
                continue
            crs_diagnostic = dict(layer.get("crs_diagnostic") or {})
            map_overlay_ready = crs_diagnostic.get("map_overlay_ready") is True
            source_crs_assumption = (
                target_crs
                if map_overlay_ready
                else "unknown_projected_or_non_wgs84"
                if crs_diagnostic.get("status") == "projected_or_non_wgs84"
                else "unknown"
            )
            if map_overlay_ready:
                status = "ready"
                conversion_steps = [
                    {
                        "action": "verify_declared_crs",
                        "status": "recommended",
                        "source_crs_assumption": source_crs_assumption,
                        "acceptance": "dataset custodian or metadata confirms EPSG:4326 / WGS84 lonlat",
                    },
                    {
                        "action": "preserve_source_layer",
                        "status": "ready",
                        "reason": "bbox already falls within longitude/latitude bounds for the current demo map overlay",
                    },
                ]
                output_policy = {
                    "write_new_file": False,
                    "suffix": "",
                    "target_crs": target_crs,
                    "lineage_fields": [],
                }
            else:
                status = "requires_conversion"
                conversion_steps = [
                    {
                        "action": "identify_source_crs",
                        "status": "required",
                        "source_crs_assumption": source_crs_assumption,
                        "method": "read CRS metadata, dataset manifest, sidecar .prj, or obtain custodian confirmation before transformation",
                    },
                    {
                        "action": "reproject_to_target_crs",
                        "status": "required",
                        "target_crs": target_crs,
                        "tooling": "GDAL/ogr2ogr, pyproj/geopandas, or an approved spatial ETL job",
                    },
                    {
                        "action": "validate_bbox_and_geometry",
                        "status": "required",
                        "acceptance": "converted bbox is within lon/lat bounds, feature count matches source, and invalid geometries are reported",
                    },
                    {
                        "action": "write_lineage_preserving_output",
                        "status": "required",
                        "output_suffix": "_wgs84.geojson",
                        "lineage_fields": ["_twm_source_file", "_twm_source_crs", "_twm_target_crs", "_twm_conversion_time"],
                    },
                ]
                output_policy = {
                    "write_new_file": True,
                    "suffix": "_wgs84.geojson",
                    "target_crs": target_crs,
                    "overwrite_source": False,
                    "lineage_fields": ["_twm_source_file", "_twm_source_crs", "_twm_target_crs", "_twm_conversion_time"],
                }

            layers.append({
                "path": layer_path,
                "label": layer.get("label") or layer_path.replace("synthetic_", "").replace(".geojson", ""),
                "status": status,
                "feature_count": safe_int(layer.get("feature_count") or layer.get("source_feature_count"), 0),
                "bbox": layer.get("bbox"),
                "source_crs_assumption": source_crs_assumption,
                "target_crs": target_crs,
                "crs_diagnostic": crs_diagnostic,
                "suggested_action": "no_conversion_required" if map_overlay_ready else "convert_to_wgs84_before_map_overlay",
                "conversion_steps": conversion_steps,
                "output_policy": output_policy,
                "not_for_production": bool(layer.get("not_for_production", summary.get("not_for_production", True))),
            })

        blocked_layer_count = sum(1 for layer in layers if layer.get("status") == "requires_conversion")
        ready_layer_count = sum(1 for layer in layers if layer.get("status") == "ready")
        status = "action_required" if blocked_layer_count else "ready" if layers else "no_spatial_layers"
        return json.loads(_json({
            "schema": "territory_world_model.data_foundation_crs_remediation_plan.v1",
            "generated_at": now_utc_iso(),
            "dataset_id": dataset_id,
            "dataset_label": spec.get("label"),
            "dataset_root": spec.get("path"),
            "source_nature": spec.get("nature"),
            "positioning": spec.get("positioning"),
            "target_crs": target_crs,
            "status": status,
            "layer_count": len(layers),
            "ready_layer_count": ready_layer_count,
            "blocked_layer_count": blocked_layer_count,
            "map_overlay_readiness": summary.get("map_overlay_readiness"),
            "layers": layers,
            "execution_policy": {
                "plan_only": True,
                "transform_geometry_in_this_api": False,
                "require_authoritative_source_crs": True,
                "require_lineage_preserving_output": True,
                "default_output_suffix": "_wgs84.geojson",
            },
            "acceptance_criteria": [
                "每个待处理空间图层必须先确认 source CRS，不能仅凭 bbox 猜测直接转换。",
                "转换后 bbox 必须落入 EPSG:4326 经纬度范围，且要素数量与源文件一致。",
                "输出文件必须保留源文件、源 CRS、目标 CRS、转换时间和工具版本 lineage。",
                "not-for-production 数据仅可用于演示和回归；CRS 转换不会提升其生产权威性。",
            ],
            "claim_boundary": (
                "This CRS remediation plan is an onboarding and map-overlay readiness artifact. "
                "It does not transform geometries in the API response, certify source authority, or support production decision claims."
            ),
        }))

    def data_foundation_authoritative_templates(self) -> dict[str, Any]:
        shared_lineage_fields = [
            "source_agency",
            "source_system",
            "source_dataset_name",
            "source_dataset_version",
            "source_crs",
            "target_crs",
            "valid_from",
            "valid_to",
            "ingested_at",
            "custodian",
            "custodian_signoff_id",
            "permission_scope",
            "not_for_production",
        ]
        templates = [
            {
                "template_id": "parcel_current_authoritative",
                "label": "Current land parcel authoritative layer",
                "role": "parcel",
                "unit": "feature",
                "accepted_formats": ["GeoPackage layer", "GeoJSON after approved CRS conversion", "PostGIS table"],
                "required_fields": [
                    "geometry",
                    "parcel_id",
                    "admin_code",
                    "land_use_code",
                    "area_m2",
                    "source_crs",
                    "data_version",
                    "valid_from",
                    "custodian_signoff_id",
                ],
                "recommended_fields": ["owner_type", "farmland_grade", "protection_status", "source_update_time"],
                "minimum_quality_gates": ["known_crs", "valid_geometry", "unique_parcel_id", "area_positive", "custodian_signoff"],
                "production_use": "state_object_build_and_rule_overlay",
            },
            {
                "template_id": "planning_zone_authoritative",
                "label": "Territorial planning zone authoritative layer",
                "role": "planning_zone",
                "unit": "feature",
                "accepted_formats": ["GeoPackage layer", "PostGIS table"],
                "required_fields": [
                    "geometry",
                    "zone_id",
                    "admin_code",
                    "zone_type",
                    "control_rule_code",
                    "source_crs",
                    "data_version",
                    "custodian_signoff_id",
                ],
                "recommended_fields": ["control_intensity", "approval_doc_id", "valid_from", "valid_to"],
                "minimum_quality_gates": ["known_crs", "valid_geometry", "zone_type_domain_check", "custodian_signoff"],
                "production_use": "policy_constraint_and_action_mask",
            },
            {
                "template_id": "approval_records_authoritative",
                "label": "Approval and review history authoritative table",
                "role": "approval_record",
                "unit": "row",
                "accepted_formats": ["CSV", "Parquet", "database view"],
                "required_fields": [
                    "case_id",
                    "project_id",
                    "admin_code",
                    "review_stage",
                    "submitted_at",
                    "final_decision",
                    "decision_at",
                    "decision_reason_code",
                    "custodian_signoff_id",
                ],
                "recommended_fields": ["reviewer_role", "required_remediation", "linked_document_id", "sanitization_level"],
                "minimum_quality_gates": ["unique_case_id", "final_decision_domain_check", "decision_time_order", "custodian_signoff"],
                "production_use": "claim_gate_observed_history_and_same_case_baseline",
            },
            {
                "template_id": "policy_action_history_authoritative",
                "label": "Policy action feasibility authoritative table",
                "role": "policy_action_history",
                "unit": "row",
                "accepted_formats": ["CSV", "Parquet", "database view"],
                "required_fields": [
                    "case_id",
                    "action_id",
                    "action_type",
                    "target_role",
                    "target_id",
                    "action_allowed",
                    "blocking_rule_code",
                    "decision_context_time",
                    "custodian_signoff_id",
                ],
                "recommended_fields": ["human_override_reason", "expected_utility_delta", "policy_version", "evidence_bundle_id"],
                "minimum_quality_gates": ["case_action_key_unique", "action_allowed_boolean", "blocking_rule_traceable", "custodian_signoff"],
                "production_use": "action_conditioned_dynamics_validation_and_planner_evaluation",
            },
            {
                "template_id": "evidence_index_authoritative",
                "label": "Evidence document and media index authoritative table",
                "role": "evidence_item",
                "unit": "row",
                "accepted_formats": ["CSV", "Parquet", "database view"],
                "required_fields": [
                    "evidence_id",
                    "case_id",
                    "source_type",
                    "document_uri",
                    "content_hash",
                    "evidence_time",
                    "permission_scope",
                    "custodian_signoff_id",
                ],
                "recommended_fields": ["redaction_status", "ocr_status", "linked_rule_code", "human_review_required"],
                "minimum_quality_gates": ["content_hash_present", "permission_scope_present", "case_link_valid", "custodian_signoff"],
                "production_use": "audit_trail_and_evidence_gate",
            },
            {
                "template_id": "rule_evaluation_authoritative",
                "label": "Rule evaluation authoritative table",
                "role": "rule_evaluation",
                "unit": "row",
                "accepted_formats": ["CSV", "Parquet", "database view"],
                "required_fields": [
                    "case_id",
                    "rule_code",
                    "subject_id",
                    "target_id",
                    "severity",
                    "hit_status",
                    "evaluated_at",
                    "policy_version",
                    "custodian_signoff_id",
                ],
                "recommended_fields": ["geometry_overlap_area_m2", "evidence_id", "review_task_id", "resolution_status"],
                "minimum_quality_gates": ["rule_code_versioned", "severity_domain_check", "hit_status_domain_check", "custodian_signoff"],
                "production_use": "hard_constraint_recall_and_audit_defensibility_metrics",
            },
        ]
        readiness_gates = [
            {
                "id": "custodian_signoff",
                "status": "blocked",
                "required_value": "each authoritative source has named custodian, sign-off id, source version and permission scope",
                "current_value": "templates defined; no production custodian sign-off loaded",
            },
            {
                "id": "not_for_production_flag_clearance",
                "status": "blocked",
                "required_value": "production datasets must explicitly set not_for_production=false after governance approval",
                "current_value": "demo fixtures remain not-for-production",
            },
            {
                "id": "same_case_join_keys",
                "status": "open",
                "required_value": "case_id/project_id/action_id keys join across approval, action, evidence and rule tables",
                "current_value": "template contract only",
            },
            {
                "id": "crs_and_geometry_acceptance",
                "status": "open",
                "required_value": "known CRS, validated geometry and EPSG:4326 map-overlay derivative where needed",
                "current_value": "CRS remediation plan exists; production ETL not implemented",
            },
        ]
        return json.loads(_json({
            "schema": "territory_world_model.data_foundation_authoritative_templates.v1",
            "generated_at": now_utc_iso(),
            "status": "template_ready_review_only",
            "production_deployment_supported": False,
            "template_count": len(templates),
            "templates": templates,
            "shared_lineage_fields": shared_lineage_fields,
            "readiness_gates": readiness_gates,
            "onboarding_steps": [
                "map authoritative source fields to the template required_fields and shared_lineage_fields",
                "run schema, CRS, domain, uniqueness and join-key validation before TWM state build",
                "load sanitized same-case approval/action/evidence history for baseline comparison",
                "keep not-for-production fixtures separate from production candidate datasets",
            ],
            "claim_boundary_notes": [
                "Templates define what production onboarding must provide; they are not production data.",
                "Passing these templates requires custodian sign-off and not-for-production flag clearance.",
                "The template report does not validate predictive, causal or approval automation claims.",
            ],
            "claim_boundary": (
                "Authoritative templates support production data onboarding planning and review. "
                "They do not by themselves certify authority, data rights, model performance or production deployment readiness."
            ),
        }))

    def _update_data_foundation_bbox(self, coords: Any, bbox: list[float | None]) -> None:
        if (
            isinstance(coords, list)
            and len(coords) >= 2
            and isinstance(coords[0], (int, float))
            and isinstance(coords[1], (int, float))
        ):
            lng = float(coords[0])
            lat = float(coords[1])
            bbox[0] = lng if bbox[0] is None else min(float(bbox[0]), lng)
            bbox[1] = lat if bbox[1] is None else min(float(bbox[1]), lat)
            bbox[2] = lng if bbox[2] is None else max(float(bbox[2]), lng)
            bbox[3] = lat if bbox[3] is None else max(float(bbox[3]), lat)
            return
        if isinstance(coords, list):
            for item in coords:
                self._update_data_foundation_bbox(item, bbox)

    def _data_foundation_crs_diagnostic(self, layer_bbox: list[float | None] | None) -> dict[str, Any]:
        if not layer_bbox or not all(value is not None for value in layer_bbox):
            return {
                "status": "unknown",
                "coordinate_space": "unknown",
                "map_overlay_ready": False,
                "warning_code": "missing_spatial_extent",
                "suggested_action": "inspect_geometry_before_map_overlay",
                "message": "空间范围缺失，不能确认是否可直接叠加到经纬度底图。",
            }
        min_x, min_y, max_x, max_y = [float(value) for value in layer_bbox]
        is_lonlat = -180.0 <= min_x <= 180.0 and -180.0 <= max_x <= 180.0 and -90.0 <= min_y <= 90.0 and -90.0 <= max_y <= 90.0
        if is_lonlat:
            return {
                "status": "wgs84_lonlat",
                "coordinate_space": "lonlat_degrees",
                "map_overlay_ready": True,
                "warning_code": None,
                "suggested_action": "ready_for_map_overlay",
                "message": "坐标范围符合经纬度范围，可直接用于当前演示地图叠加。",
            }
        return {
            "status": "projected_or_non_wgs84",
            "coordinate_space": "projected_or_large_numeric",
            "map_overlay_ready": False,
            "warning_code": "requires_crs_conversion",
            "suggested_action": "convert_to_wgs84_before_map_overlay",
            "message": "坐标范围超出经纬度范围，直接叠加到当前地图前需要做 CRS 识别和转换。",
        }

    def _data_foundation_map_overlay_readiness(self, layers: list[dict[str, Any]]) -> dict[str, Any]:
        ready_layer_count = sum(1 for layer in layers if (layer.get("crs_diagnostic") or {}).get("map_overlay_ready") is True)
        blocked_layer_count = len(layers) - ready_layer_count
        warning_codes = sorted({
            str((layer.get("crs_diagnostic") or {}).get("warning_code"))
            for layer in layers
            if (layer.get("crs_diagnostic") or {}).get("warning_code")
        })
        return {
            "status": "ready" if layers and blocked_layer_count == 0 else "blocked" if blocked_layer_count else "empty",
            "ready_layer_count": ready_layer_count,
            "blocked_layer_count": blocked_layer_count,
            "warning_codes": warning_codes,
            "suggested_action": "load_on_map" if layers and blocked_layer_count == 0 else "fix_crs_before_map_overlay" if blocked_layer_count else "add_spatial_layers",
            "message": (
                "全部空间图层可直接叠加到当前地图。"
                if layers and blocked_layer_count == 0
                else "部分或全部空间图层不是经纬度坐标，直接叠加前需要 CRS 转换。"
                if blocked_layer_count
                else "未发现可预览空间图层。"
            ),
        }

    def _data_foundation_property_value_type(self, value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return type(value).__name__

    def _data_foundation_layer_property_profile(self, features: list[Any]) -> dict[str, Any]:
        field_order: list[str] = []
        field_counts: dict[str, int] = {}
        field_types: dict[str, str] = {}
        sample_properties: dict[str, Any] = {}
        for feature in features:
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties")
            if not isinstance(properties, dict):
                continue
            for raw_name, value in properties.items():
                name = str(raw_name)
                if name not in field_counts:
                    field_order.append(name)
                    field_types[name] = self._data_foundation_property_value_type(value)
                field_counts[name] = field_counts.get(name, 0) + 1
                if len(sample_properties) < 12 and name not in sample_properties:
                    sample_properties[name] = value
        return {
            "property_field_count": len(field_order),
            "property_fields": [
                {
                    "name": name,
                    "value_type": field_types.get(name, "unknown"),
                    "observed_count": field_counts.get(name, 0),
                }
                for name in field_order[:48]
            ],
            "sample_properties": sample_properties,
        }

    def _data_foundation_spatial_layer_catalog(self, root: Path, files: dict[str, Any]) -> list[dict[str, Any]]:
        catalog: list[dict[str, Any]] = []
        for rel_path, unit in files.items():
            if unit != "feature" or not str(rel_path).endswith(".geojson"):
                continue
            path = root / str(rel_path)
            if not path.exists():
                continue
            try:
                payload = read_json(path)
            except Exception:
                continue
            features = payload.get("features") if isinstance(payload, dict) and payload.get("type") == "FeatureCollection" else None
            if not isinstance(features, list):
                continue
            layer_bbox: list[float | None] = [None, None, None, None]
            for feature in features:
                if isinstance(feature, dict):
                    self._update_data_foundation_bbox((feature.get("geometry") or {}).get("coordinates"), layer_bbox)
            bbox = layer_bbox if all(value is not None for value in layer_bbox) else None
            property_profile = self._data_foundation_layer_property_profile(features)
            catalog.append({
                "path": str(rel_path),
                "label": str(rel_path).replace("synthetic_", "").replace(".geojson", ""),
                "unit": unit,
                "feature_count": len(features),
                "bbox": bbox,
                **property_profile,
                "crs_diagnostic": self._data_foundation_crs_diagnostic(bbox),
                "not_for_production": True,
            })
        return catalog

    def data_foundation_map_preview(
        self,
        dataset_id: str,
        max_features_per_layer: Any = 500,
        layer_path: Any = None,
    ) -> dict[str, Any]:
        dataset_id = compact_text(dataset_id)
        raw_limit = compact_text(max_features_per_layer)
        selected_layer_path = compact_text(layer_path)
        full_load = raw_limit.lower() in {"all", "full", "true"} or safe_int(max_features_per_layer, 500) <= 0
        max_features = None if full_load else max(1, min(safe_int(max_features_per_layer, 500), 2000))
        spec = next((item for item in TWM_DATA_FOUNDATION_DATASETS if item.get("id") == dataset_id), None)
        if spec is None:
            raise LookupError(f"data foundation dataset not found: {dataset_id}")

        def sample_features(features: list[Any]) -> list[Any]:
            if max_features is None:
                return features
            if len(features) <= max_features:
                return features
            if max_features == 1:
                return [features[0]]
            step = (len(features) - 1) / (max_features - 1)
            return [features[round(idx * step)] for idx in range(max_features)]

        root = self._repo_root() / str(spec["path"])
        layers: list[dict[str, Any]] = []
        overall_bbox: list[float | None] = [None, None, None, None]
        total_source_feature_count = 0
        total_preview_feature_count = 0
        for rel_path, unit in dict(spec.get("files") or {}).items():
            if unit != "feature" or not str(rel_path).endswith(".geojson"):
                continue
            if selected_layer_path and str(rel_path) != selected_layer_path:
                continue
            path = root / str(rel_path)
            if not path.exists():
                continue
            payload = read_json(path)
            if not isinstance(payload, dict):
                continue
            features = payload.get("features") if payload.get("type") == "FeatureCollection" else None
            if not isinstance(features, list):
                continue
            sampled_features = []
            layer_bbox: list[float | None] = [None, None, None, None]
            total_source_feature_count += len(features)
            for feature in sample_features(features):
                if not isinstance(feature, dict):
                    continue
                cloned = deepcopy(feature)
                properties = dict(cloned.get("properties") or {})
                properties["_twm_dataset_id"] = dataset_id
                properties["_twm_source_file"] = str(rel_path)
                properties["_twm_preview"] = True
                cloned["properties"] = properties
                self._update_data_foundation_bbox(cloned.get("geometry", {}).get("coordinates"), layer_bbox)
                self._update_data_foundation_bbox(cloned.get("geometry", {}).get("coordinates"), overall_bbox)
                sampled_features.append(cloned)
            total_preview_feature_count += len(sampled_features)
            layer_bbox_value = layer_bbox if all(value is not None for value in layer_bbox) else None
            layer_crs_diagnostic = self._data_foundation_crs_diagnostic(layer_bbox_value)
            layers.append({
                "name": str(rel_path),
                "label": str(rel_path).replace("synthetic_", "").replace(".geojson", ""),
                "unit": unit,
                "delivery_mode": "full_geojson" if full_load else "sampled_geojson",
                "source_feature_count": len(features),
                "preview_feature_count": len(sampled_features),
                "not_for_production": True,
                "bbox": layer_bbox_value,
                "crs_diagnostic": layer_crs_diagnostic,
                "geojson": {
                    "type": "FeatureCollection",
                    "features": sampled_features,
                },
            })
        center = None
        bbox = overall_bbox if all(value is not None for value in overall_bbox) else None
        if selected_layer_path and not layers:
            raise LookupError(f"data foundation spatial layer not found: {dataset_id}/{selected_layer_path}")
        if bbox:
            center = [
                (float(bbox[1]) + float(bbox[3])) / 2,
                (float(bbox[0]) + float(bbox[2])) / 2,
            ]

        map_overlay_readiness = self._data_foundation_map_overlay_readiness(layers)

        return json.loads(_json({
            "schema": "territory_world_model.data_foundation_map_preview.v1",
            "dataset_id": dataset_id,
            "label": spec.get("label"),
            "positioning": spec.get("positioning"),
            "not_for_production": True,
            "max_features_per_layer": max_features,
            "delivery_mode": "full_geojson" if full_load else "sampled_geojson",
            "layer_count": len(layers),
            "total_source_feature_count": total_source_feature_count,
            "total_preview_feature_count": total_preview_feature_count,
            "bbox": bbox,
            "center": center,
            "map_overlay_readiness": map_overlay_readiness,
            "layers": layers,
        }))

    def data_foundation_layer_detail(
        self,
        dataset_id: str,
        layer_path: str,
        sample_limit: Any = 5,
    ) -> dict[str, Any]:
        dataset_id = compact_text(dataset_id)
        selected_layer_path = compact_text(layer_path)
        if not selected_layer_path:
            raise LookupError("data foundation spatial layer path is required")
        sample_count = max(1, min(safe_int(sample_limit, 5), 25))
        spec = next((item for item in TWM_DATA_FOUNDATION_DATASETS if item.get("id") == dataset_id), None)
        if spec is None:
            raise LookupError(f"data foundation dataset not found: {dataset_id}")
        files = dict(spec.get("files") or {})
        if files.get(selected_layer_path) != "feature" or not selected_layer_path.endswith(".geojson"):
            raise LookupError(f"data foundation spatial layer not found: {dataset_id}/{selected_layer_path}")
        root = self._repo_root() / str(spec["path"])
        path = root / selected_layer_path
        if not path.exists():
            raise LookupError(f"data foundation spatial layer not found: {dataset_id}/{selected_layer_path}")
        payload = read_json(path)
        features = payload.get("features") if isinstance(payload, dict) and payload.get("type") == "FeatureCollection" else None
        if not isinstance(features, list):
            raise LookupError(f"data foundation spatial layer is not a FeatureCollection: {dataset_id}/{selected_layer_path}")
        layer_bbox: list[float | None] = [None, None, None, None]
        sample_records: list[dict[str, Any]] = []
        for idx, feature in enumerate(features):
            if not isinstance(feature, dict):
                continue
            self._update_data_foundation_bbox((feature.get("geometry") or {}).get("coordinates"), layer_bbox)
            if len(sample_records) < sample_count:
                sample_records.append({
                    "feature_index": idx,
                    "properties": dict(feature.get("properties") or {}),
                })
        bbox = layer_bbox if all(value is not None for value in layer_bbox) else None
        property_profile = self._data_foundation_layer_property_profile(features)
        return json.loads(_json({
            "schema": "territory_world_model.data_foundation_layer_detail.v1",
            "dataset_id": dataset_id,
            "dataset_label": spec.get("label"),
            "layer_path": selected_layer_path,
            "label": selected_layer_path.replace("synthetic_", "").replace(".geojson", ""),
            "unit": "feature",
            "not_for_production": True,
            "feature_count": len(features),
            "bbox": bbox,
            "crs_diagnostic": self._data_foundation_crs_diagnostic(bbox),
            **property_profile,
            "sample_record_count": len(sample_records),
            "sample_records": sample_records,
            "delivery_mode": "properties_only",
            "claim_boundary": "Layer detail is for data readiness, field inspection and evidence browsing; it is not production authority evidence by itself.",
        }))

    def _load_data_foundation_validation(self) -> dict[str, Any]:
        path = self._repo_root() / "docs" / "reports" / "twm_data_foundation_validation.json"
        if not path.exists():
            return {}
        try:
            return read_json(path)
        except Exception:
            return {}

    def _data_foundation_dataset_summary(self, spec: dict[str, Any]) -> dict[str, Any]:
        root = self._repo_root() / str(spec["path"])
        manifest = read_json(root / "dataset_manifest.json") if (root / "dataset_manifest.json").exists() else {}
        files: list[dict[str, Any]] = []
        total_count = 0
        synthetic_count = 0
        not_for_production_count = 0
        for rel_path, unit in dict(spec.get("files") or {}).items():
            audit = self._data_foundation_file_audit(root / rel_path)
            count = safe_int(audit.get("count"), 0)
            total_count += count
            synthetic_count += safe_int(audit.get("synthetic_count"), 0)
            not_for_production_count += safe_int(audit.get("not_for_production_count"), 0)
            files.append({
                "path": rel_path,
                "unit": unit,
                **audit,
            })
        spatial_layer_catalog = self._data_foundation_spatial_layer_catalog(root, dict(spec.get("files") or {}))
        return {
            "id": spec["id"],
            "label": spec["label"],
            "path": spec["path"],
            "exists": root.exists(),
            "nature": spec["nature"],
            "positioning": spec["positioning"],
            "not_for_production": bool(manifest.get("not_for_production", True)),
            "description": manifest.get("description_zh") or manifest.get("description") or "",
            "file_count": len(files),
            "total_count": total_count,
            "synthetic_count": synthetic_count,
            "not_for_production_count": not_for_production_count,
            "files": files,
            "spatial_layer_catalog": spatial_layer_catalog,
            "map_overlay_readiness": self._data_foundation_map_overlay_readiness(spatial_layer_catalog),
            "claim_boundary": "该数据包用于测试和适配验证；not_for_production=true 时不得作为真实治理结论依据。",
        }

    def _data_foundation_file_audit(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"exists": False, "count": 0, "synthetic_count": 0, "not_for_production_count": 0}
        try:
            if path.suffix.lower() == ".csv":
                records = read_csv(path)
                return self._data_foundation_records_audit(records)
            if path.suffix.lower() in {".geojson", ".json"}:
                payload = read_json(path)
                features = payload.get("features")
                if isinstance(features, list):
                    records = [dict(item.get("properties") or {}) for item in features if isinstance(item, dict)]
                    return self._data_foundation_records_audit(records)
                return {"exists": True, "count": len(payload), "synthetic_count": 0, "not_for_production_count": 0}
        except Exception:
            return {"exists": True, "count": 0, "synthetic_count": 0, "not_for_production_count": 0, "read_error": True}
        return {"exists": True, "count": 0, "synthetic_count": 0, "not_for_production_count": 0}

    def _data_foundation_records_audit(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "exists": True,
            "count": len(records),
            "synthetic_count": sum(1 for item in records if truthy(item.get("synthetic") or item.get("source_synthetic"))),
            "not_for_production_count": sum(1 for item in records if truthy(item.get("not_for_production") or item.get("not_for_prod"))),
        }

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[2]

    def create_project(self, payload: dict[str, Any], username: str = "") -> dict[str, Any]:
        project = TwmProject(
            name=str(payload.get("name") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            region_code=str(payload.get("region_code") or payload.get("admin_code") or "").strip(),
            business_scenario=str(payload.get("business_scenario") or "planning_supervision").strip() or "planning_supervision",
            owner_username=str(payload.get("owner_username") or username or "").strip(),
            status=str(payload.get("status") or "draft").strip() or "draft",
            metadata=dict(payload.get("metadata") or {}),
        )
        saved = self.repository.save_project(project)
        return saved.to_dict()

    def list_projects(self, owner_username: str | None = None) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.repository.list_projects(owner_username=owner_username)]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        project = self.repository.get_project(project_id)
        return project.to_dict() if project else None

    def bind_layer(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        binding = TwmLayerBinding(
            project_id=project_id,
            role=str(payload.get("role") or payload.get("semantic_domain") or "").strip(),
            canonical_role=str(payload.get("canonical_role") or payload.get("standard_role") or payload.get("role") or "").strip(),
            object_type=str(payload.get("object_type") or "feature").strip() or "feature",
            layer_alias=str(payload.get("layer_alias") or payload.get("role_alias_zh") or payload.get("alias_zh") or "").strip(),
            source_path=str(payload.get("source_path") or payload.get("path") or "").strip(),
            semantic_product_path=str(payload.get("semantic_product_path") or "").strip(),
            asset_id=payload.get("asset_id"),
            time_label=str(payload.get("time_label") or "").strip(),
            valid_from=payload.get("valid_from"),
            valid_to=payload.get("valid_to"),
            field_mapping=dict(payload.get("field_mapping") or payload.get("twm_binding") or {}),
            quality_snapshot=dict(payload.get("quality_snapshot") or {}),
            metadata=dict(payload.get("metadata") or {}),
            synthetic=bool(payload.get("synthetic", False)),
            not_for_production=bool(payload.get("not_for_production", False)),
        )
        saved = self.repository.save_layer_binding(binding)
        return saved.to_dict()

    def list_layer_bindings(self, project_id: str) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.repository.list_layer_bindings(project_id)]

    # ------------------------------------------------------------------
    # State build
    # ------------------------------------------------------------------

    def build_state(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self.repository.get_project(project_id)
        if project is None:
            raise LookupError(f"project not found: {project_id}")
        bindings = self.repository.list_layer_bindings(project_id)
        bundle_dir = payload.get("bundle_dir") or payload.get("semantic_bundle_dir")
        if bundle_dir:
            result = self.state_builder.build_from_bundle(
                bundle_dir,
                project=project,
                label=payload.get("label"),
                state_time=payload.get("state_time"),
                rule_set_id=payload.get("rule_set_id"),
                include_auxiliary_tables=bool(payload.get("include_auxiliary_tables", True)),
            )
        else:
            if not bindings:
                raise ValueError(f"project {project_id} has no layer bindings")
            result = self.state_builder.build_from_bindings(
                project,
                bindings,
                bundle_root=payload.get("bundle_root"),
                bundle_manifest=payload.get("bundle_manifest"),
                bundle_contract=payload.get("bundle_contract"),
                bundle_state_input=payload.get("bundle_state_input"),
                bundle_warnings=list(payload.get("bundle_warnings") or []),
                label=payload.get("label"),
                state_time=payload.get("state_time"),
                rule_set_id=payload.get("rule_set_id"),
                include_auxiliary_tables=bool(payload.get("include_auxiliary_tables", True)),
            )

        self.repository.save_state_bundle(result)
        self._clear_report_cache(project_id=project_id)
        return result.to_dict()

    def list_states(self, project_id: str | None = None) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.repository.list_state_versions(project_id=project_id)]

    def get_state(self, state_version_id: str) -> dict[str, Any] | None:
        bundle = self.repository.get_state_bundle(state_version_id)
        if bundle is None:
            return None
        return {
            "state_version": bundle["state_version"].to_dict(),
            "objects": [item.to_dict() for item in bundle["objects"]],
            "relations": [item.to_dict() for item in bundle["relations"]],
            "hits": [item.to_dict() for item in bundle["hits"]],
            "evidence_items": [item.to_dict() for item in bundle["evidence_items"]],
            "review_tasks": [item.to_dict() for item in bundle["review_tasks"]],
        }

    def state_snapshot_lakehouse_manifest(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        bundle = self.repository.get_state_bundle(state_version_id)
        if state is None or bundle is None:
            raise LookupError(f"state not found: {state_version_id}")
        object_store_uri = compact_text(payload.get("lakehouse_uri") or payload.get("object_store_uri") or "s3://gis-agent-lakehouse").rstrip("/")
        namespace = compact_text(payload.get("namespace") or "twm").replace("-", "_").replace("/", "_")
        warehouse_uri = f"{object_store_uri}/warehouse/iceberg/{namespace}"
        state_uri = f"{object_store_uri}/curated/twm/state_snapshots/state_version_id={state_version_id}"
        objects = list(bundle.get("objects") or [])
        relations = list(bundle.get("relations") or [])
        rule_hits = self.repository.list_rule_hits(state_version_id=state_version_id)
        evidence_items = self.repository.list_evidence_items(state_version_id=state_version_id)
        review_tasks = self.repository.list_review_tasks(state_version_id=state_version_id)
        registry_entries = self.repository.list_dynamics_model_registry_entries(state_version_id)
        include_vector_sidecar = truthy(payload.get("include_vector_sidecar"))
        vector_sidecar = {
            "enabled": include_vector_sidecar,
            "format": "lance" if include_vector_sidecar else "",
            "uri": f"{object_store_uri}/features/lance/twm_state_features/state_version_id={state_version_id}" if include_vector_sidecar else "",
            "role": "optional high-dimensional embedding sidecar; authoritative facts remain in Iceberg/PostGIS",
        }
        artifacts = {
            "state_metadata": self._lakehouse_manifest_artifact(
                namespace=namespace,
                table="state_metadata",
                fmt="parquet",
                uri=f"{state_uri}/state_metadata",
                partitioning=["state_version_id"],
                row_count=1,
            ),
            "state_objects": self._lakehouse_manifest_artifact(
                namespace=namespace,
                table="state_objects",
                fmt="geoparquet",
                uri=f"{state_uri}/state_objects",
                partitioning=["state_version_id", "canonical_role"],
                row_count=len(objects),
            ),
            "state_relations": self._lakehouse_manifest_artifact(
                namespace=namespace,
                table="state_relations",
                fmt="geoparquet",
                uri=f"{state_uri}/state_relations",
                partitioning=["state_version_id", "relation_type"],
                row_count=len(relations),
            ),
            "rule_hits": self._lakehouse_manifest_artifact(
                namespace=namespace,
                table="rule_hits",
                fmt="parquet",
                uri=f"{state_uri}/rule_hits",
                partitioning=["state_version_id", "severity", "hit_status"],
                row_count=len(rule_hits),
            ),
            "evidence_items": self._lakehouse_manifest_artifact(
                namespace=namespace,
                table="evidence_items",
                fmt="parquet",
                uri=f"{state_uri}/evidence_items",
                partitioning=["state_version_id", "evidence_type"],
                row_count=len(evidence_items),
            ),
            "review_tasks": self._lakehouse_manifest_artifact(
                namespace=namespace,
                table="review_tasks",
                fmt="parquet",
                uri=f"{state_uri}/review_tasks",
                partitioning=["state_version_id", "status"],
                row_count=len(review_tasks),
            ),
            "dynamics_model_registry": self._lakehouse_manifest_artifact(
                namespace=namespace,
                table="dynamics_model_registry",
                fmt="parquet",
                uri=f"{state_uri}/dynamics_model_registry",
                partitioning=["state_version_id", "status"],
                row_count=len(registry_entries),
            ),
        }
        return json.loads(_json({
            "schema": "territory_world_model.state_snapshot_lakehouse_manifest.v1",
            "generated_at": now_utc_iso(),
            "state_version_id": state_version_id,
            "project_id": state.project_id,
            "storage": {
                "object_store_uri": object_store_uri,
                "warehouse_uri": warehouse_uri,
                "table_format": "iceberg",
                "primary_file_formats": ["geoparquet", "parquet"],
                "spatial_compute": "apache_sedona",
                "vector_sidecar": vector_sidecar,
            },
            "snapshot": {
                "state_version_id": state_version_id,
                "object_count": len(objects),
                "relation_count": len(relations),
                "rule_hit_count": len(rule_hits),
                "evidence_item_count": len(evidence_items),
                "review_task_count": len(review_tasks),
                "dynamics_model_registry_entry_count": len(registry_entries),
                "quality_summary": dict(state.quality_summary or {}),
            },
            "artifacts": artifacts,
            "readiness": {
                "sedona_batch_ready": len(objects) >= 1,
                "twm_training_snapshot_ready": len(objects) >= 1 and "state_objects" in artifacts,
                "iceberg_snapshot_ready": True,
                "requires_external_writer": True,
            },
            "write_plan": [
                "materialize each artifact as Parquet/GeoParquet under its target_uri",
                "register or append each artifact into the named Iceberg table",
                "preserve state_version_id and lineage columns for temporal training and rollback",
                "write high-dimensional vectors to the Lance sidecar only when vector_sidecar.enabled is true",
            ],
            "claim_boundary": "Manifest only: this report defines the production lakehouse snapshot contract; it does not write Iceberg tables or prove production data quality.",
        }))

    def _lakehouse_manifest_artifact(
        self,
        *,
        namespace: str,
        table: str,
        fmt: str,
        uri: str,
        partitioning: list[str],
        row_count: int,
    ) -> dict[str, Any]:
        namespace_name = compact_text(namespace or "twm").replace("-", "_").replace("/", "_")
        table_name = compact_text(table).replace("-", "_").replace("/", "_")
        return {
            "table": f"{namespace_name}.{table_name}",
            "format": compact_text(fmt),
            "target_uri": compact_text(uri).rstrip("/"),
            "partitioning": list(partitioning or []),
            "row_count": max(0, int(row_count or 0)),
            "write_mode": "replace_partitions_by_state_version",
            "lineage_columns": ["state_version_id", "project_id", "generated_at"],
            "iceberg": {
                "namespace": namespace_name,
                "table": table_name,
                "snapshot_isolation_key": "state_version_id",
            },
        }

    def materialize_state_snapshot_lakehouse(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        manifest = self.state_snapshot_lakehouse_manifest(state_version_id, payload)
        state = self.repository.get_state_version(state_version_id)
        bundle = self.repository.get_state_bundle(state_version_id)
        if state is None or bundle is None:
            raise LookupError(f"state not found: {state_version_id}")
        rows_by_artifact = self._state_snapshot_lakehouse_artifact_rows(
            state,
            bundle,
            self.repository.list_rule_hits(state_version_id=state_version_id),
            self.repository.list_evidence_items(state_version_id=state_version_id),
            self.repository.list_review_tasks(state_version_id=state_version_id),
            self.repository.list_dynamics_model_registry_entries(state_version_id),
        )
        artifacts: dict[str, Any] = {}
        skipped: list[dict[str, Any]] = []
        written_count = 0
        for artifact_name, artifact in dict(manifest.get("artifacts") or {}).items():
            target_uri = compact_text(artifact.get("target_uri") or "")
            target_dir = self._local_path_from_lakehouse_uri(target_uri)
            if target_dir is None:
                skipped.append({
                    "artifact": artifact_name,
                    "target_uri": target_uri,
                    "reason": "non_local_uri_requires_object_store_writer",
                })
                continue
            rows, columns, geo_metadata = rows_by_artifact.get(artifact_name, ([], ["state_version_id"], False))
            target_dir.mkdir(parents=True, exist_ok=True)
            local_path = target_dir / "part-00000.parquet"
            self._write_lakehouse_parquet(local_path, rows, columns, geo_metadata=geo_metadata)
            materialized = dict(artifact)
            materialized.update({
                "materialized": True,
                "local_path": str(local_path),
                "local_uri": local_path.as_uri(),
                "record_count": len(rows),
                "bytes": local_path.stat().st_size,
            })
            artifacts[artifact_name] = materialized
            manifest["artifacts"][artifact_name] = materialized
            written_count += 1

        manifest_uri = compact_text(
            payload.get("manifest_uri")
            or f"{manifest['storage']['object_store_uri']}/manifests/twm/state_snapshot_lakehouse_manifest/state_version_id={state_version_id}/manifest.json"
        )
        manifest_local_path = self._local_path_from_lakehouse_uri(manifest_uri)
        if manifest_local_path is not None:
            if manifest_local_path.suffix.lower() != ".json":
                manifest_local_path = manifest_local_path / "manifest.json"
            manifest_local_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_local_path.write_text(_json(manifest) + "\n", encoding="utf-8")

        return json.loads(_json({
            "schema": "territory_world_model.state_snapshot_lakehouse_materialization.v1",
            "generated_at": now_utc_iso(),
            "state_version_id": state_version_id,
            "project_id": state.project_id,
            "manifest_uri": manifest_uri,
            "manifest_local_path": str(manifest_local_path) if manifest_local_path is not None else "",
            "written_artifact_count": written_count,
            "skipped_artifacts": skipped,
            "artifacts": artifacts,
            "manifest": manifest,
            "readiness": {
                "local_parquet_written": written_count > 0,
                "sedona_geoparquet_read_ready": all(
                    name in artifacts for name in ("state_objects", "state_relations")
                ),
                "iceberg_registration_required": True,
                "object_store_writer_required": bool(skipped),
            },
            "iceberg_registration_plan": [
                "CREATE NAMESPACE IF NOT EXISTS for the manifest namespace",
                "CREATE OR REPLACE Iceberg tables with Parquet/GeoParquet source files",
                "replace partitions by state_version_id for repeatable snapshot rollback",
                "run Sedona spatial index jobs on state_objects and state_relations geometry columns",
            ],
            "claim_boundary": "Materialization only: this writes local Parquet/GeoParquet-compatible snapshot artifacts and a manifest; it does not register Iceberg tables or build distributed spatial indexes.",
        }))

    def state_snapshot_lakehouse_publish_plan(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None:
            raise LookupError(f"state not found: {state_version_id}")
        materialization = self._payload_mapping(payload.get("materialization"))
        manifest = self._payload_mapping(materialization.get("manifest") or payload.get("manifest"))
        if not manifest:
            manifest = self.state_snapshot_lakehouse_manifest(state_version_id, payload)
        manifest_artifacts = self._payload_mapping(manifest.get("artifacts"))
        materialized_artifacts = self._payload_mapping(materialization.get("artifacts"))
        catalog = self._sql_identifier_part(payload.get("catalog") or payload.get("iceberg_catalog") or "twm", "twm")
        namespace = self._sql_namespace(payload.get("namespace") or self._manifest_namespace(manifest) or "twm")
        warehouse_uri = compact_text(
            payload.get("warehouse_uri")
            or payload.get("iceberg_warehouse_uri")
            or (manifest.get("storage") or {}).get("warehouse_uri")
            or "s3://gis-agent-lakehouse/warehouse/iceberg"
        )
        geohash_precision = min(12, max(1, safe_int(payload.get("geohash_precision"), 8)))
        spark_conf = self._iceberg_sedona_spark_conf(catalog, warehouse_uri, payload.get("spark_conf"))
        ddl_statements = [f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{namespace}"]
        publish_specs: list[dict[str, Any]] = []
        sedona_specs: list[dict[str, Any]] = []
        missing_sources: list[str] = []
        for artifact_name, artifact in manifest_artifacts.items():
            if not isinstance(artifact, dict):
                continue
            materialized = materialized_artifacts.get(artifact_name) if isinstance(materialized_artifacts.get(artifact_name), dict) else {}
            merged = {**artifact, **materialized}
            table_name = self._artifact_table_name(artifact_name, merged)
            table_identifier = f"{catalog}.{namespace}.{table_name}"
            source_uri = compact_text(merged.get("local_uri") or merged.get("source_uri") or merged.get("target_uri") or "")
            if not source_uri:
                missing_sources.append(str(artifact_name))
            partition_by = [
                self._sql_identifier_part(item, "")
                for item in list(merged.get("partitioning") or [])
                if self._sql_identifier_part(item, "")
            ]
            partition_sql = f"\nPARTITIONED BY ({', '.join(partition_by)})" if partition_by else ""
            source_sql = self._spark_parquet_source(source_uri)
            ddl = (
                f"CREATE OR REPLACE TABLE {table_identifier}\n"
                f"USING iceberg{partition_sql}\n"
                f"AS SELECT * FROM {source_sql}"
            )
            ddl_statements.append(ddl)
            publish_specs.append({
                "schema": "territory_world_model.iceberg_artifact_publish_spec.v1",
                "artifact": artifact_name,
                "table_identifier": table_identifier,
                "catalog": catalog,
                "namespace": namespace,
                "table": table_name,
                "warehouse_uri": warehouse_uri,
                "source_uri": source_uri,
                "source_format": compact_text(merged.get("format") or "parquet"),
                "partition_by": partition_by,
                "row_count": safe_int(merged.get("record_count"), safe_int(merged.get("row_count"), 0)),
                "write_mode": compact_text(merged.get("write_mode") or "replace_partitions_by_state_version"),
                "ddl": ddl,
                "spark_conf": spark_conf,
            })
            if self._artifact_has_geometry(artifact_name, merged):
                sedona_specs.append(self._sedona_spatial_index_spec(
                    artifact_name=artifact_name,
                    table_identifier=table_identifier,
                    warehouse_uri=warehouse_uri,
                    catalog=catalog,
                    geohash_precision=geohash_precision,
                    spark_conf=spark_conf,
                ))
        publish_status = "pass" if publish_specs and not missing_sources and warehouse_uri else "blocked"
        sedona_status = "pass" if sedona_specs else "review"
        return json.loads(_json({
            "schema": "territory_world_model.state_snapshot_lakehouse_publish_plan.v1",
            "generated_at": now_utc_iso(),
            "state_version_id": state_version_id,
            "project_id": state.project_id,
            "target": {
                "catalog": catalog,
                "namespace": namespace,
                "warehouse_uri": warehouse_uri,
                "table_format": "iceberg",
                "spatial_engine": "apache_sedona",
            },
            "source_manifest_schema": manifest.get("schema", ""),
            "iceberg_publish_specs": publish_specs,
            "sedona_spatial_index_specs": sedona_specs,
            "ddl_statements": ddl_statements,
            "validation_gates": {
                "publish_spec_gate": {
                    "status": publish_status,
                    "missing_sources": missing_sources,
                    "spec_count": len(publish_specs),
                },
                "sedona_spatial_index_gate": {
                    "status": sedona_status,
                    "index_spec_count": len(sedona_specs),
                    "strategy": {"type": "geohash", "precision": geohash_precision},
                },
            },
            "execution_order": [
                "create Iceberg namespace",
                "publish each Parquet/GeoParquet artifact as an Iceberg table",
                "build Sedona geohash spatial index tables for geometry-bearing artifacts",
                "validate row counts and snapshot ids before switching consumers",
            ],
            "claim_boundary": "Publish plan only: this creates Iceberg and Sedona execution specifications but does not run Spark, register tables, or build distributed indexes.",
        }))

    def execute_state_snapshot_lakehouse_publish_plan(
        self,
        state_version_id: str,
        payload: dict[str, Any] | None = None,
        *,
        executor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None:
            raise LookupError(f"state not found: {state_version_id}")
        plan = self._payload_mapping(payload.get("publish_plan") or payload.get("plan"))
        if not plan:
            plan = self.state_snapshot_lakehouse_publish_plan(state_version_id, payload)
        if executor is None:
            return json.loads(_json({
                "schema": "territory_world_model.state_snapshot_lakehouse_publish_execution.v1",
                "generated_at": now_utc_iso(),
                "state_version_id": state_version_id,
                "project_id": state.project_id,
                "status": "blocked",
                "publish_plan": plan,
                "iceberg_publish_results": [],
                "sedona_spatial_index_results": [],
                "validation_gates": {
                    "spark_executor_gate": {"status": "blocked", "missing": ["executor"]},
                    "iceberg_snapshot_gate": {"status": "blocked", "missing": ["executor"]},
                    "sedona_spatial_index_gate": {"status": "blocked", "missing": ["executor"]},
                    "consumer_switch_gate": {"status": "blocked", "missing": ["executor"]},
                },
                "claim_boundary": "Execution report only: no Spark executor was supplied, so no Iceberg table or Sedona spatial index was created.",
            }))

        publish_results: list[dict[str, Any]] = []
        for spec in list(plan.get("iceberg_publish_specs") or []):
            if not isinstance(spec, dict):
                continue
            task = {
                "kind": "iceberg_publish",
                "artifact": spec.get("artifact", ""),
                "table_identifier": spec.get("table_identifier", ""),
                "ddl": spec.get("ddl", ""),
                "source_uri": spec.get("source_uri", ""),
                "expected_row_count": safe_int(spec.get("row_count"), 0),
                "spark_conf": dict(spec.get("spark_conf") or {}),
                "spec": spec,
            }
            raw = self._call_twm_publish_executor(executor, task)
            publish_results.append(self._normalize_iceberg_publish_result(task, raw))

        sedona_results: list[dict[str, Any]] = []
        for spec in list(plan.get("sedona_spatial_index_specs") or []):
            if not isinstance(spec, dict):
                continue
            task = {
                "kind": "sedona_spatial_index",
                "artifact": spec.get("artifact", ""),
                "output_table": spec.get("output_table", ""),
                "input_tables": list(spec.get("input_tables") or []),
                "sql": spec.get("sql", ""),
                "index_strategy": dict(spec.get("index_strategy") or {}),
                "spark_conf": dict(spec.get("spark_conf") or {}),
                "spec": spec,
            }
            raw = self._call_twm_publish_executor(executor, task)
            sedona_results.append(self._normalize_sedona_spatial_index_result(task, raw))

        publish_gate = self._iceberg_snapshot_gate(publish_results)
        sedona_gate = self._sedona_spatial_index_execution_gate(sedona_results, plan)
        executor_gate = {
            "status": "pass" if publish_gate["status"] == "pass" and sedona_gate["status"] == "pass" else "blocked",
            "publish_task_count": len(publish_results),
            "sedona_task_count": len(sedona_results),
        }
        consumer_gate_status = "pass" if executor_gate["status"] == "pass" else "blocked"
        overall = "pass" if consumer_gate_status == "pass" else "blocked"
        return json.loads(_json({
            "schema": "territory_world_model.state_snapshot_lakehouse_publish_execution.v1",
            "generated_at": now_utc_iso(),
            "state_version_id": state_version_id,
            "project_id": state.project_id,
            "status": overall,
            "publish_plan": plan,
            "iceberg_publish_results": publish_results,
            "sedona_spatial_index_results": sedona_results,
            "validation_gates": {
                "spark_executor_gate": executor_gate,
                "iceberg_snapshot_gate": publish_gate,
                "sedona_spatial_index_gate": sedona_gate,
                "consumer_switch_gate": {
                    "status": consumer_gate_status,
                    "required_gates": ["spark_executor_gate", "iceberg_snapshot_gate", "sedona_spatial_index_gate"],
                },
            },
            "claim_boundary": "Execution report only: this records executor results and validation gates; forecast consumers should switch only when all gates pass and the reported Iceberg snapshots are externally auditable.",
        }))

    def state_snapshot_lakehouse_spark_submit_bundle(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None:
            raise LookupError(f"state not found: {state_version_id}")
        plan = self._payload_mapping(payload.get("publish_plan") or payload.get("plan"))
        if not plan:
            plan = self.state_snapshot_lakehouse_publish_plan(state_version_id, payload)
        output_dir = Path(compact_text(payload.get("output_dir") or "")) if payload.get("output_dir") else Path("outputs/twm_lakehouse_spark") / state_version_id
        output_dir = output_dir.expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        plan_path = output_dir / "state_snapshot_lakehouse_publish_plan.json"
        report_path = output_dir / "state_snapshot_lakehouse_publish_execution_report.json"
        plan_path.write_text(_json(plan) + "\n", encoding="utf-8")
        script_path = self._spark_submit_script_path()
        spark_conf = self._spark_submit_conf_from_plan(plan)
        executor_image = compact_text(payload.get("executor_image") or payload.get("spark_kubernetes_image") or "")
        if executor_image:
            spark_conf["spark.kubernetes.container.image"] = executor_image
        extra_conf = self._payload_mapping(payload.get("spark_conf"))
        for key, value in extra_conf.items():
            if key:
                spark_conf[str(key)] = str(value)
        command = self._spark_submit_command(
            script_path=script_path,
            plan_path=plan_path,
            report_path=report_path,
            spark_master=compact_text(payload.get("spark_master") or "local[*]"),
            deploy_mode=compact_text(payload.get("deploy_mode") or "client"),
            spark_conf=spark_conf,
            packages=compact_text(
                payload.get("spark_packages")
                or "org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.8.1,org.apache.sedona:sedona-spark-shaded-3.5_2.12:1.9.0"
            ),
        )
        return json.loads(_json({
            "schema": "territory_world_model.state_snapshot_lakehouse_spark_submit_bundle.v1",
            "generated_at": now_utc_iso(),
            "state_version_id": state_version_id,
            "project_id": state.project_id,
            "plan_path": str(plan_path),
            "execution_report_path": str(report_path),
            "executor_script": str(script_path),
            "spark_submit": {
                "command": command,
                "master": compact_text(payload.get("spark_master") or "local[*]"),
                "deploy_mode": compact_text(payload.get("deploy_mode") or "client"),
                "conf": spark_conf,
            },
            "execution_contract": {
                "expected_publish_task_count": len(list(plan.get("iceberg_publish_specs") or [])),
                "expected_spatial_index_task_count": len(list(plan.get("sedona_spatial_index_specs") or [])),
                "required_output": str(report_path),
                "required_gates": ["iceberg_snapshot_gate", "sedona_spatial_index_gate", "consumer_switch_gate"],
            },
            "claim_boundary": "Spark submit bundle only: this writes the executable plan and command for a Spark/Sedona/Iceberg runtime; it does not submit the job or verify external cluster execution.",
        }))

    def _spark_submit_script_path(self) -> Path:
        return Path(__file__).resolve().parents[2] / "scripts" / "twm_state_snapshot_lakehouse_publish_job.py"

    def _spark_submit_conf_from_plan(self, plan: dict[str, Any]) -> dict[str, str]:
        for spec in list(plan.get("iceberg_publish_specs") or []):
            if isinstance(spec, dict) and isinstance(spec.get("spark_conf"), dict):
                return {str(key): str(value) for key, value in dict(spec.get("spark_conf") or {}).items()}
        return {}

    def _spark_submit_command(
        self,
        *,
        script_path: Path,
        plan_path: Path,
        report_path: Path,
        spark_master: str,
        deploy_mode: str,
        spark_conf: dict[str, str],
        packages: str,
    ) -> list[str]:
        command = ["spark-submit", "--master", spark_master, "--deploy-mode", deploy_mode]
        if packages:
            command.extend(["--packages", packages])
        for key in sorted(spark_conf):
            command.extend(["--conf", f"{key}={spark_conf[key]}"])
        command.extend([str(script_path), "--plan", str(plan_path), "--output", str(report_path)])
        return command

    def _call_twm_publish_executor(
        self,
        executor: Callable[[dict[str, Any]], dict[str, Any]],
        task: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            result = executor(task)
        except Exception as exc:
            return {"returncode": 1, "error": str(exc)}
        return self._payload_mapping(result)

    def _normalize_iceberg_publish_result(self, task: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
        expected = safe_int(task.get("expected_row_count"), 0)
        rows_written = safe_int(raw.get("rows_written"), -1)
        returncode = safe_int(raw.get("returncode"), 0 if raw.get("snapshot_id") else 1)
        snapshot_id = compact_text(raw.get("snapshot_id") or raw.get("iceberg_snapshot_id") or "")
        row_count_status = "pass" if rows_written == expected else "fail"
        return {
            "artifact": compact_text(task.get("artifact") or ""),
            "table_identifier": compact_text(raw.get("table_identifier") or task.get("table_identifier") or ""),
            "returncode": returncode,
            "snapshot_id": snapshot_id,
            "expected_row_count": expected,
            "rows_written": rows_written,
            "row_count_status": row_count_status,
            "status": "pass" if returncode == 0 and snapshot_id and row_count_status == "pass" else "fail",
            "raw_result": raw,
        }

    def _normalize_sedona_spatial_index_result(self, task: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
        returncode = safe_int(raw.get("returncode"), 0 if raw.get("snapshot_id") else 1)
        snapshot_id = compact_text(raw.get("snapshot_id") or raw.get("iceberg_snapshot_id") or "")
        rows_written = safe_int(raw.get("rows_written"), safe_int(raw.get("indexed_rows"), -1))
        return {
            "artifact": compact_text(task.get("artifact") or ""),
            "output_table": compact_text(raw.get("output_table") or task.get("output_table") or ""),
            "returncode": returncode,
            "snapshot_id": snapshot_id,
            "rows_written": rows_written,
            "index_strategy": dict(task.get("index_strategy") or {}),
            "status": "pass" if returncode == 0 and snapshot_id else "fail",
            "raw_result": raw,
        }

    def _iceberg_snapshot_gate(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        missing = []
        failed = []
        for item in results:
            artifact = compact_text(item.get("artifact") or "artifact")
            if not item.get("snapshot_id"):
                missing.append(f"{artifact}.snapshot_id")
            if item.get("row_count_status") != "pass":
                failed.append(f"{artifact}.row_count")
            if item.get("status") != "pass":
                failed.append(f"{artifact}.execution")
        return {
            "status": "pass" if results and not missing and not failed else "blocked",
            "snapshot_count": sum(1 for item in results if item.get("snapshot_id")),
            "missing": missing,
            "failed": sorted(set(failed)),
        }

    def _sedona_spatial_index_execution_gate(self, results: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
        expected_count = len(list(plan.get("sedona_spatial_index_specs") or []))
        missing = []
        failed = []
        for item in results:
            artifact = compact_text(item.get("artifact") or "artifact")
            if not item.get("snapshot_id"):
                missing.append(f"{artifact}.snapshot_id")
            if item.get("status") != "pass":
                failed.append(f"{artifact}.execution")
        return {
            "status": "pass" if expected_count > 0 and len(results) == expected_count and not missing and not failed else "blocked",
            "expected_index_count": expected_count,
            "completed_index_count": len(results),
            "missing": missing,
            "failed": sorted(set(failed)),
        }

    def _manifest_namespace(self, manifest: dict[str, Any]) -> str:
        artifacts = self._payload_mapping(manifest.get("artifacts"))
        for artifact in artifacts.values():
            if not isinstance(artifact, dict):
                continue
            table = compact_text(artifact.get("table") or "")
            if "." in table:
                return table.rsplit(".", 1)[0]
        return ""

    def _artifact_table_name(self, artifact_name: str, artifact: dict[str, Any]) -> str:
        table = compact_text(artifact.get("table") or artifact_name)
        if "." in table:
            table = table.rsplit(".", 1)[-1]
        return self._sql_identifier_part(table, self._sql_identifier_part(artifact_name, "artifact"))

    def _artifact_has_geometry(self, artifact_name: str, artifact: dict[str, Any]) -> bool:
        fmt = compact_text(artifact.get("format") or "").lower()
        return fmt == "geoparquet" or artifact_name in {"state_objects", "state_relations", "rule_hits"}

    def _sedona_spatial_index_spec(
        self,
        *,
        artifact_name: str,
        table_identifier: str,
        warehouse_uri: str,
        catalog: str,
        geohash_precision: int,
        spark_conf: dict[str, str],
    ) -> dict[str, Any]:
        output_table = f"{table_identifier}_spatial_index"
        sql = (
            f"CREATE OR REPLACE TABLE {output_table}\n"
            "USING iceberg\n"
            "AS\n"
            "SELECT *,\n"
            "       ST_GeomFromWKB(geometry_wkb) AS geometry,\n"
            f"       ST_GeoHash(ST_GeomFromWKB(geometry_wkb), {geohash_precision}) AS geohash_{geohash_precision}\n"
            f"FROM {table_identifier}\n"
            "WHERE geometry_wkb IS NOT NULL"
        )
        return {
            "schema": "territory_world_model.sedona_spatial_index_job.v1",
            "artifact": artifact_name,
            "task": "geohash_spatial_index",
            "catalog": catalog,
            "warehouse_uri": warehouse_uri,
            "input_tables": [table_identifier],
            "output_table": output_table,
            "geometry_column": "geometry_wkb",
            "index_strategy": {"type": "geohash", "precision": geohash_precision},
            "sql": sql,
            "spark_conf": spark_conf,
        }

    def _iceberg_sedona_spark_conf(self, catalog: str, warehouse_uri: str, extra: Any = None) -> dict[str, str]:
        conf = {
            "spark.sql.extensions": "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
            f"spark.sql.catalog.{catalog}": "org.apache.iceberg.spark.SparkCatalog",
            f"spark.sql.catalog.{catalog}.type": "hadoop",
            f"spark.sql.catalog.{catalog}.warehouse": warehouse_uri,
            "spark.serializer": "org.apache.spark.serializer.KryoSerializer",
            "spark.kryo.registrator": "org.apache.sedona.core.serde.SedonaKryoRegistrator",
        }
        extra_conf = self._payload_mapping(extra)
        for key, value in extra_conf.items():
            if key:
                conf[str(key)] = str(value)
        return conf

    def _spark_parquet_source(self, uri: str) -> str:
        escaped = compact_text(uri).replace("`", "")
        return f"parquet.`{escaped}`" if escaped else "parquet.``"

    def _sql_namespace(self, namespace: Any) -> str:
        parts = [self._sql_identifier_part(part, "") for part in compact_text(namespace).split(".")]
        clean = [part for part in parts if part]
        return ".".join(clean) if clean else "twm"

    def _sql_identifier_part(self, value: Any, default: str = "item") -> str:
        text = compact_text(value or default).replace("-", "_").replace("/", "_")
        text = re.sub(r"[^0-9A-Za-z_]", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        if not text:
            text = default or "item"
        if text[0].isdigit():
            text = f"_{text}"
        return text

    def _state_snapshot_lakehouse_artifact_rows(
        self,
        state: TwmStateVersion,
        bundle: dict[str, Any],
        rule_hits: list[TwmRuleHit],
        evidence_items: list[TwmEvidenceItem],
        review_tasks: list[TwmReviewTask],
        registry_entries: list[TwmDynamicsModelRegistryEntry],
    ) -> dict[str, tuple[list[dict[str, Any]], list[str], bool]]:
        objects = list(bundle.get("objects") or [])
        relations = list(bundle.get("relations") or [])
        generated_at = now_utc_iso()
        return {
            "state_metadata": (
                [{
                    "state_version_id": state.id,
                    "project_id": state.project_id,
                    "state_time": state.state_time,
                    "label": state.label,
                    "rule_set_id": state.rule_set_id or "",
                    "object_count": len(objects),
                    "relation_count": len(relations),
                    "build_status": state.build_status,
                    "quality_summary_json": self._json_cell(state.quality_summary),
                    "summary_json": self._json_cell(state.summary),
                    "source_manifest_json": self._json_cell(state.source_manifest),
                    "generated_at": generated_at,
                }],
                [
                    "state_version_id",
                    "project_id",
                    "state_time",
                    "label",
                    "rule_set_id",
                    "object_count",
                    "relation_count",
                    "build_status",
                    "quality_summary_json",
                    "summary_json",
                    "source_manifest_json",
                    "generated_at",
                ],
                False,
            ),
            "state_objects": (
                [self._lakehouse_state_object_row(item) for item in objects],
                [
                    "state_version_id",
                    "object_id",
                    "object_code",
                    "object_type",
                    "source_role",
                    "source_asset_id",
                    "source_feature_id",
                    "source_path",
                    "canonical_role",
                    "quality_score",
                    "synthetic",
                    "not_for_production",
                    "qa_use_for_rules",
                    "geometry_crs",
                    "geometry_wkb",
                    "bbox_json",
                    "attributes_json",
                    "semantic_tags_json",
                ],
                True,
            ),
            "state_relations": (
                [self._lakehouse_state_relation_row(item) for item in relations],
                [
                    "state_version_id",
                    "relation_id",
                    "subject_object_id",
                    "predicate",
                    "object_object_id",
                    "relation_type",
                    "confidence",
                    "source_subject_role",
                    "source_target_role",
                    "synthetic",
                    "not_for_production",
                    "geometry_wkb",
                    "metrics_json",
                    "evidence_json",
                ],
                True,
            ),
            "rule_hits": (
                [self._lakehouse_rule_hit_row(item) for item in rule_hits],
                [
                    "state_version_id",
                    "rule_hit_id",
                    "rule_id",
                    "subject_object_id",
                    "target_object_id",
                    "hit_status",
                    "severity",
                    "risk_score",
                    "explanation",
                    "review_task_id",
                    "created_at",
                    "reviewed_at",
                    "geometry_wkb",
                    "metrics_json",
                ],
                True,
            ),
            "evidence_items": (
                [self._lakehouse_evidence_item_row(item) for item in evidence_items],
                [
                    "evidence_item_id",
                    "rule_hit_id",
                    "evidence_type",
                    "source_system",
                    "source_ref",
                    "checksum",
                    "created_at",
                    "payload_json",
                ],
                False,
            ),
            "review_tasks": (
                [self._lakehouse_review_task_row(item) for item in review_tasks],
                [
                    "review_task_id",
                    "rule_hit_id",
                    "assignee",
                    "status",
                    "decision",
                    "comment",
                    "created_at",
                    "updated_at",
                ],
                False,
            ),
            "dynamics_model_registry": (
                [self._lakehouse_registry_entry_row(item) for item in registry_entries],
                [
                    "registry_entry_id",
                    "state_version_id",
                    "project_id",
                    "registry_key",
                    "model_name",
                    "model_version",
                    "model_family",
                    "status",
                    "promotion_decision",
                    "previous_active_registry_key",
                    "activated_at",
                    "created_at",
                    "updated_at",
                    "lineage_json",
                    "metadata_json",
                    "registry_report_json",
                ],
                False,
            ),
        }

    def _lakehouse_state_object_row(self, item: TwmStateObject) -> dict[str, Any]:
        return {
            "state_version_id": item.state_version_id,
            "object_id": item.id,
            "object_code": item.object_code,
            "object_type": item.object_type,
            "source_role": item.source_role,
            "source_asset_id": item.source_asset_id,
            "source_feature_id": item.source_feature_id or "",
            "source_path": item.source_path,
            "canonical_role": item.canonical_role,
            "quality_score": item.quality_score,
            "synthetic": item.synthetic,
            "not_for_production": item.not_for_production,
            "qa_use_for_rules": item.qa_use_for_rules,
            "geometry_crs": item.geometry_crs,
            "geometry_wkb": self._geometry_wkb(item.geom),
            "bbox_json": self._json_cell(item.bbox),
            "attributes_json": self._json_cell(item.attributes),
            "semantic_tags_json": self._json_cell(item.semantic_tags),
        }

    def _lakehouse_state_relation_row(self, item: TwmStateRelation) -> dict[str, Any]:
        return {
            "state_version_id": item.state_version_id,
            "relation_id": item.id,
            "subject_object_id": item.subject_object_id,
            "predicate": item.predicate,
            "object_object_id": item.object_object_id,
            "relation_type": item.relation_type,
            "confidence": item.confidence,
            "source_subject_role": item.source_subject_role,
            "source_target_role": item.source_target_role,
            "synthetic": item.synthetic,
            "not_for_production": item.not_for_production,
            "geometry_wkb": self._geometry_wkb(item.geom),
            "metrics_json": self._json_cell(item.metrics),
            "evidence_json": self._json_cell(item.evidence),
        }

    def _lakehouse_rule_hit_row(self, item: TwmRuleHit) -> dict[str, Any]:
        return {
            "state_version_id": item.state_version_id,
            "rule_hit_id": item.id,
            "rule_id": item.rule_id,
            "subject_object_id": item.subject_object_id,
            "target_object_id": item.target_object_id or "",
            "hit_status": item.hit_status,
            "severity": item.severity,
            "risk_score": item.risk_score,
            "explanation": item.explanation,
            "review_task_id": item.review_task_id or "",
            "created_at": item.created_at,
            "reviewed_at": item.reviewed_at or "",
            "geometry_wkb": self._geometry_wkb(item.geom),
            "metrics_json": self._json_cell(item.metrics),
        }

    def _lakehouse_evidence_item_row(self, item: TwmEvidenceItem) -> dict[str, Any]:
        return {
            "evidence_item_id": item.id,
            "rule_hit_id": item.rule_hit_id,
            "evidence_type": item.evidence_type,
            "source_system": item.source_system,
            "source_ref": item.source_ref,
            "checksum": item.checksum or "",
            "created_at": item.created_at,
            "payload_json": self._json_cell(item.payload),
        }

    def _lakehouse_review_task_row(self, item: TwmReviewTask) -> dict[str, Any]:
        return {
            "review_task_id": item.id,
            "rule_hit_id": item.rule_hit_id,
            "assignee": item.assignee or "",
            "status": item.status,
            "decision": item.decision,
            "comment": item.comment,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }

    def _lakehouse_registry_entry_row(self, item: TwmDynamicsModelRegistryEntry) -> dict[str, Any]:
        return {
            "registry_entry_id": item.id,
            "state_version_id": item.state_version_id,
            "project_id": item.project_id,
            "registry_key": item.registry_key,
            "model_name": item.model_name,
            "model_version": item.model_version,
            "model_family": item.model_family,
            "status": item.status,
            "promotion_decision": item.promotion_decision,
            "previous_active_registry_key": item.previous_active_registry_key,
            "activated_at": item.activated_at,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "lineage_json": self._json_cell(item.lineage),
            "metadata_json": self._json_cell(item.metadata),
            "registry_report_json": self._json_cell(item.registry_report),
        }

    def _write_lakehouse_parquet(
        self,
        path: Path,
        rows: list[dict[str, Any]],
        columns: list[str],
        *,
        geo_metadata: bool,
    ) -> None:
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except Exception as exc:  # pragma: no cover - exercised only in missing optional dependency envs
            raise RuntimeError("pyarrow is required to materialize TWM lakehouse Parquet artifacts") from exc
        hive_partition_columns = self._hive_partition_columns(path)
        file_columns = [column for column in columns if column not in hive_partition_columns]
        normalized = [{column: row.get(column) for column in file_columns} for row in rows]
        if normalized:
            table = pa.Table.from_pylist(normalized).select(file_columns)
        else:
            table = pa.table({column: pa.array([], type=pa.string()) for column in file_columns})
        if geo_metadata:
            metadata = dict(table.schema.metadata or {})
            metadata[b"geo"] = json.dumps(
                {
                    "version": "1.1.0",
                    "primary_column": "geometry_wkb",
                    "columns": {
                        "geometry_wkb": {
                            "encoding": "WKB",
                            "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
                            "geometry_types": [],
                        }
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            table = table.replace_schema_metadata(metadata)
        pq.write_table(table, path)

    def _local_path_from_lakehouse_uri(self, uri: str) -> Path | None:
        text = compact_text(uri)
        if not text:
            return None
        parsed = urlparse(text)
        if parsed.scheme == "file":
            return Path(unquote(parsed.path))
        if parsed.scheme:
            return None
        return Path(text).expanduser()

    def _hive_partition_columns(self, path: Path) -> set[str]:
        columns: set[str] = set()
        for part in path.parent.parts:
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            if name and value:
                columns.add(name)
        return columns

    def _json_cell(self, value: Any) -> str:
        return json.dumps(jsonable(value), ensure_ascii=False, default=str, sort_keys=True)

    def _geometry_wkb(self, geom: Any) -> bytes | None:
        if geom is None:
            return None
        if isinstance(geom, bytes):
            return geom
        try:
            if hasattr(geom, "wkb"):
                return bytes(geom.wkb)
            from shapely import wkt as shapely_wkt
            from shapely.geometry import shape as shapely_shape

            if isinstance(geom, dict):
                return bytes(shapely_shape(geom).wkb)
            if isinstance(geom, str) and geom.strip():
                return bytes(shapely_wkt.loads(geom).wkb)
        except Exception:
            return None
        return None

    def state_contract_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        cache_key = self._report_cache_key(
            state_version_id,
            payload,
            include=("thresholds", "geofm_gate_report"),
        )
        cached = self._cache_get(self._state_contract_cache, cache_key)
        if cached is not None:
            return cached
        state = self.repository.get_state_version(state_version_id)
        state_bundle = self.repository.get_state_bundle(state_version_id)
        if state is None or state_bundle is None:
            raise LookupError(f"state not found: {state_version_id}")
        objects = list(state_bundle.get("objects") or [])
        relations = list(state_bundle.get("relations") or [])
        rule_hits = self.repository.list_rule_hits(state_version_id=state_version_id)
        evidence_items = self.repository.list_evidence_items(state_version_id=state_version_id)
        review_tasks = self.repository.list_review_tasks(state_version_id=state_version_id)
        token_contract = self._state_contract_hierarchy(state, objects, relations)
        feature_channels = self._state_contract_feature_channels(state, objects, relations)
        constraint_channels = self._state_contract_constraint_channels(rule_hits, evidence_items, review_tasks)
        temporal_support = self._state_contract_temporal_support(state, payload)
        geofm_policy = self._state_contract_geofm_policy(state, payload)
        claim_ladder = self._state_contract_claim_ladder(
            token_contract=token_contract,
            constraint_channels=constraint_channels,
            temporal_support=temporal_support,
            geofm_policy=geofm_policy,
        )
        claim_boundary = self._state_contract_claim_boundary(
            token_contract=token_contract,
            constraint_channels=constraint_channels,
            temporal_support=temporal_support,
            geofm_policy=geofm_policy,
            claim_ladder=claim_ladder,
        )
        report = TwmStateContractReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            status=claim_boundary["status"],
            hierarchy=token_contract,
            feature_channels=feature_channels,
            constraint_channels=constraint_channels,
            temporal_support=temporal_support,
            geofm_policy=geofm_policy,
            downstream_consumers=[
                "action_conditioned_forecast",
                "dynamics_training_examples",
                "dynamics_readiness_report",
                "dynamics_candidate_fit",
                "beam_plan",
                "counterfactual_rollout",
            ],
            claim_ladder=claim_ladder,
            claim_boundary=claim_boundary,
            recommendations=self._state_contract_recommendations(
                token_contract=token_contract,
                constraint_channels=constraint_channels,
                temporal_support=temporal_support,
                geofm_policy=geofm_policy,
            ),
        )
        result = report.to_dict()
        self._cache_set(self._state_contract_cache, cache_key, result)
        return deepcopy(result)

    def dynamics_backend_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None:
            raise LookupError(f"state not found: {state_version_id}")
        cache_key = self._report_cache_key(
            state_version_id,
            payload,
            include=(
                "dataset",
                "scenario",
                "evidence_coverage",
                "horizon",
                "actions",
                "scenario_context",
                "split",
                "temporal_holdout",
                "thresholds",
                "backend",
                "dynamics_backend",
                "candidate_report",
                "dynamics_candidate_report",
                "fit_report",
                "dynamics_fit_report",
                "dynamics_candidate",
                "predictions",
                "geofm_gate_report",
                "causal_calibration_report",
            ),
        )
        cached = self._cache_get(self._dynamics_backend_cache, cache_key)
        if cached is not None:
            return cached
        if self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")
        dataset_payload = payload.get("dataset")
        dataset = dict(dataset_payload) if isinstance(dataset_payload, dict) else self.dynamics_training_examples(state_version_id, payload)
        state_contract = self.state_contract_report(state_version_id, payload)
        readiness = self.dynamics_readiness_report(state_version_id, {**payload, "dataset": dataset})
        backend = self._dynamics_backend_descriptor(payload)
        input_contract = self._dynamics_backend_input_contract(state_contract, backend)
        output_contract = self._dynamics_backend_output_contract(payload)
        adapter_contract = self._dynamics_backend_adapter_contract(payload)
        gate_results = self._dynamics_backend_gate_results(
            backend=backend,
            state_contract=state_contract,
            readiness=readiness,
            input_contract=input_contract,
            output_contract=output_contract,
            adapter_contract=adapter_contract,
            payload=payload,
        )
        evidence_gate = self._dynamics_backend_evidence_gate(gate_results, backend, readiness)
        claim_boundary = self._dynamics_backend_claim_boundary(gate_results, backend, evidence_gate)
        report = TwmDynamicsBackendReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            status=claim_boundary.get("status", "review"),
            backend=backend,
            input_contract=input_contract,
            output_contract=output_contract,
            adapter_contract=adapter_contract,
            gate_results=gate_results,
            evidence_gate=evidence_gate,
            claim_boundary=claim_boundary,
            recommendations=self._dynamics_backend_recommendations(gate_results, evidence_gate, backend),
        )
        result = report.to_dict()
        self._cache_set(self._dynamics_backend_cache, cache_key, result)
        return deepcopy(result)

    def training_objective_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None or self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")
        dataset_payload = payload.get("dataset")
        dataset = dict(dataset_payload) if isinstance(dataset_payload, dict) else self.dynamics_training_examples(state_version_id, payload)
        backend_payload = payload.get("dynamics_backend_report")
        backend_report = dict(backend_payload) if isinstance(backend_payload, dict) else self.dynamics_backend_report(state_version_id, {"dataset": dataset, **payload})
        predictions = self._training_objective_predictions(dataset, payload, backend_report)
        metrics, head_metrics, eval_inventory = self._dynamics_evaluation_metrics(dataset, predictions)
        objective_contract = self._training_objective_contract(dataset, backend_report)
        loss_components = self._training_objective_loss_components(dataset, predictions, metrics)
        ranking_diagnostics = self._training_objective_ranking_diagnostics(dataset, predictions, metrics)
        calibration_diagnostics = self._training_objective_calibration_diagnostics(dataset, predictions)
        evidence_gate = self._training_objective_evidence_gate(backend_report, objective_contract, loss_components)
        report = TwmTrainingObjectiveReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            status=evidence_gate.get("status", "review"),
            objective_contract=objective_contract,
            loss_components=loss_components,
            ranking_diagnostics=ranking_diagnostics,
            calibration_diagnostics=calibration_diagnostics,
            evidence_gate=evidence_gate,
            sample_inventory=eval_inventory,
            recommendations=self._training_objective_recommendations(loss_components, evidence_gate, backend_report),
        )
        return report.to_dict()

    def train_dynamics_candidate(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        trainer = self._train_dynamics_trainer_descriptor(payload)
        dataset_payload = payload.get("dataset")
        initial_sample_count = len(dataset_payload.get("examples") or []) if isinstance(dataset_payload, dict) else None
        with trace_twm_operation(
            "train_dynamics_candidate",
            state_version_id=state_version_id,
            backend=str(trainer.get("model_name") or trainer.get("model_family") or trainer.get("trainer_id") or ""),
            sample_count=initial_sample_count,
            gate_status="pending",
        ) as trace_ctx:
            state = self.repository.get_state_version(state_version_id)
            if state is None or self.repository.get_state_bundle(state_version_id) is None:
                raise LookupError(f"state not found: {state_version_id}")
            dataset = dict(dataset_payload) if isinstance(dataset_payload, dict) else self.dynamics_training_examples(state_version_id, payload)
            _set_trace_attribute(trace_ctx, "twm.sample_count", len(dataset.get("examples") or []))
            readiness = self.dynamics_readiness_report(state_version_id, {"dataset": dataset, **payload})
            seed_objective = self.training_objective_report(state_version_id, {"dataset": dataset, **payload})
            if readiness.get("status") != "pass" or seed_objective.get("evidence_gate", {}).get("status") == "blocked":
                evidence_gate = self._train_dynamics_evidence_gate(
                    readiness=readiness,
                    backend_report={},
                    objective_report=seed_objective,
                    trainer=trainer,
                )
                report = TwmTrainDynamicsReport(
                    state_version_id=state_version_id,
                    project_id=state.project_id,
                    status=evidence_gate.get("status", "blocked"),
                    trainer=trainer,
                    objective=seed_objective,
                    learned_parameters={},
                    predictions={},
                    candidate_report={},
                    backend_report={},
                    evidence_gate=evidence_gate,
                    recommendations=self._train_dynamics_recommendations(evidence_gate, trainer),
                )
                result = report.to_dict()
                _set_trace_attribute(trace_ctx, "twm.gate_status", result.get("evidence_gate", {}).get("status", result.get("status", "review")))
                _set_trace_attribute(trace_ctx, "twm.prediction_count", 0)
                return result

            if self._use_spatiotemporal_transformer_dynamics_trainer(trainer):
                train_result = train_spatiotemporal_transformer_dynamics(dataset, trainer, seed_objective, payload)
                learned_parameters = dict(train_result.get("learned_parameters") or {})
                predictions = dict(train_result.get("predictions") or {})
                candidate_report = self._neural_dynamics_candidate_report(trainer, learned_parameters, predictions, dict(train_result.get("diagnostics") or {}))
            elif self._use_hierarchical_graph_dynamics_trainer(trainer):
                train_result = train_hierarchical_graph_dynamics(dataset, trainer, seed_objective, payload)
                learned_parameters = dict(train_result.get("learned_parameters") or {})
                predictions = dict(train_result.get("predictions") or {})
                candidate_report = self._neural_dynamics_candidate_report(trainer, learned_parameters, predictions, dict(train_result.get("diagnostics") or {}))
            elif self._use_neural_dynamics_trainer(trainer):
                train_result = train_neural_multi_head_dynamics(dataset, trainer, seed_objective, payload)
                learned_parameters = dict(train_result.get("learned_parameters") or {})
                predictions = dict(train_result.get("predictions") or {})
                candidate_report = self._neural_dynamics_candidate_report(trainer, learned_parameters, predictions, dict(train_result.get("diagnostics") or {}))
            else:
                learned_parameters = self._train_dynamics_parameters(dataset, seed_objective, trainer)
                predictions = self._predict_with_baseline_dynamics(dataset, learned_parameters)
                candidate_report = self._train_dynamics_candidate_report(trainer, learned_parameters, predictions)
            backend_payload = {
                "dataset": dataset,
                "backend": {
                    "backend_id": trainer["trainer_id"],
                    "backend_type": "trainable_candidate_scaffold",
                    "model_name": trainer["model_name"],
                    "model_version": trainer["model_version"],
                    "model_family": trainer["model_family"],
                    "trainable": True,
                    "action_conditioned": True,
                    "uses_geofm": trainer.get("uses_geofm", False),
                    "uses_causal_calibration": trainer.get("uses_causal_calibration", False),
                },
                "candidate_report": candidate_report,
                "thresholds": payload.get("thresholds") or {},
                "geofm_gate_report": payload.get("geofm_gate_report") or {},
                "causal_calibration_report": payload.get("causal_calibration_report") or {},
            }
            backend_report = self.dynamics_backend_report(state_version_id, backend_payload)
            _set_trace_attribute(trace_ctx, "twm.backend_gate_status", (backend_report.get("evidence_gate") or {}).get("status", backend_report.get("status", "review")))
            objective_report = self.training_objective_report(
                state_version_id,
                {
                    "dataset": dataset,
                    "dynamics_backend_report": backend_report,
                    "predictions": predictions,
                },
            )
            evidence_gate = self._train_dynamics_evidence_gate(
                readiness=readiness,
                backend_report=backend_report,
                objective_report=objective_report,
                trainer=trainer,
            )
            registry_report = self.dynamics_model_registry_report(
                state_version_id,
                {
                    "dynamics_training_dataset": dataset,
                    "candidate_report": candidate_report,
                    "readiness_report": readiness,
                    "evaluation_report": payload.get("evaluation_report")
                    or payload.get("dynamics_evaluation_report")
                    or backend_report,
                    "registry_metadata": payload.get("registry_metadata")
                    or payload.get("metadata")
                    or {},
                    "production_data_gate": payload.get("production_data_gate")
                    or payload.get("production_gate")
                    or {},
                    "current_registry_key": payload.get("current_registry_key")
                    or payload.get("production_registry_key")
                    or "",
                },
            )
            report = TwmTrainDynamicsReport(
                state_version_id=state_version_id,
                project_id=state.project_id,
                status=evidence_gate.get("status", "review"),
                trainer=trainer,
                objective=objective_report,
                learned_parameters=learned_parameters,
                predictions=predictions,
                candidate_report=candidate_report,
                backend_report=backend_report,
                registry_report=registry_report,
                evidence_gate=evidence_gate,
                recommendations=self._train_dynamics_recommendations(evidence_gate, trainer),
            )
            result = report.to_dict()
            _set_trace_attribute(trace_ctx, "twm.gate_status", result.get("evidence_gate", {}).get("status", result.get("status", "review")))
            _set_trace_attribute(trace_ctx, "twm.prediction_count", len(predictions))
            return result

    # ------------------------------------------------------------------
    # Rules / reviews / evidence
    # ------------------------------------------------------------------

    def ensure_default_rules(self) -> dict[str, Any]:
        rule_set = TwmRuleSet(
            name="TWM Default Rule Set",
            version_label="default-demo",
            status="active",
            created_by="system",
        )
        saved_rule_set = self.repository.save_rule_set(rule_set)
        rules = self.rule_evaluator._default_rules()
        self.repository.ensure_default_rule_set(saved_rule_set, rules)
        return {
            "rule_set": saved_rule_set.to_dict(),
            "rules": [item.to_dict() for item in self.repository.list_policy_rules(saved_rule_set.id, enabled=True)],
        }

    def evaluate_rules(
        self,
        state_version_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state_bundle = self.repository.get_state_bundle(state_version_id)
        if state_bundle is None:
            raise LookupError(f"state not found: {state_version_id}")
        state = self.repository.get_state_version(state_version_id)
        if state is None:
            raise LookupError(f"state not found: {state_version_id}")
        state_result = StateBuildResult(
            project=self.repository.get_project(state.project_id) or TwmProject(id=state.project_id),
            state_version=state,
            objects=state_bundle["objects"],
            relations=state_bundle["relations"],
            object_counts_by_role={},
            relation_counts_by_type={},
            hierarchy_tokens={},
            quality_summary=state.quality_summary,
            warnings=[],
            relation_specs=[],
        )
        rule_set = self.repository.get_rule_set(payload.get("rule_set_id")) if payload and payload.get("rule_set_id") else None
        rules = self.repository.list_policy_rules(rule_set.id, enabled=True) if rule_set else None
        result = self.rule_evaluator.evaluate_state(
            state_result,
            rule_set=rule_set,
            rules=rules,
            include_default_rules=payload is None or payload.get("include_default_rules", True),
            model_output=payload.get("model_output") if payload else None,
            scenario_context=payload.get("scenario_context") if payload else None,
        )
        self._clear_report_cache(state_version_id=state_version_id)
        return result.to_dict()

    def get_rule_hits(self, state_version_id: str, *, severity: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.repository.list_rule_hits(state_version_id=state_version_id, severity=severity, status=status)]

    def get_rule_hit(self, hit_id: str) -> dict[str, Any] | None:
        hit = self.repository.get_rule_hit(hit_id)
        if hit is None:
            return None
        evidence = self.repository.list_evidence_items(rule_hit_id=hit.id)
        review_tasks = self.repository.list_review_tasks(rule_hit_id=hit.id)
        return {
            "hit": hit.to_dict(),
            "evidence_items": [item.to_dict() for item in evidence],
            "review_tasks": [item.to_dict() for item in review_tasks],
        }

    def review_hit(self, hit_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        hit, task = self.repository.review_rule_hit(
            hit_id,
            decision=str(payload.get("decision") or payload.get("review_result") or ""),
            comment=str(payload.get("comment") or payload.get("note") or ""),
            assignee=payload.get("assignee"),
            status=payload.get("status"),
        )
        if hit is None or task is None:
            raise LookupError(f"rule hit not found: {hit_id}")
        return {
            "hit": hit.to_dict(),
            "review_task": task.to_dict(),
        }

    def generate_audit_report(self, state_version_id: str) -> dict[str, Any]:
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")
        hits = self.repository.list_rule_hits(state_version_id=state_version_id)
        review_tasks = self.repository.list_review_tasks(state_version_id=state_version_id)
        evidence_items = self.repository.list_evidence_items(state_version_id=state_version_id)
        confirmed = sum(1 for task in review_tasks if task.status == "confirmed")
        dismissed = sum(1 for task in review_tasks if task.status == "dismissed")
        mitigation = sum(1 for hit in hits if hit.hit_status == "mitigated")
        evidence_gate_passed = all(item.checksum for item in evidence_items)
        severity_distribution: dict[str, int] = {}
        for hit in hits:
            severity_distribution[hit.severity] = severity_distribution.get(hit.severity, 0) + 1
        report = TwmAuditReport(
            project_id=state.project_id,
            state_version_id=state_version_id,
            rule_hit_count=len(hits),
            confirmed_count=confirmed,
            dismissed_count=dismissed,
            mitigation_count=mitigation,
            evidence_gate_passed=evidence_gate_passed,
            evidence_gate_summary={
                "evidence_item_count": len(evidence_items),
                "all_have_checksum": evidence_gate_passed,
            },
            source_summary=state.source_manifest,
            rule_summary={
                "severity_distribution": severity_distribution,
            },
            state_summary=state.summary,
        )
        return report.to_dict()

    # ------------------------------------------------------------------
    # Scenario planning
    # ------------------------------------------------------------------

    def create_scenario(self, payload: dict[str, Any]) -> dict[str, Any]:
        scenario = TwmScenario(
            project_id=str(payload.get("project_id") or ""),
            base_state_version_id=str(payload.get("base_state_version_id") or ""),
            name=str(payload.get("name") or "").strip(),
            scenario_type=str(payload.get("scenario_type") or "baseline").strip() or "baseline",
            input_changes=dict(payload.get("input_changes") or {}),
            source_model=payload.get("source_model"),
            status=str(payload.get("status") or "draft").strip() or "draft",
            metadata=dict(payload.get("metadata") or {}),
        )
        saved = self.repository.save_scenario(scenario)
        metrics = payload.get("metrics") or []
        if metrics:
            saved_metrics = []
            for metric in metrics:
                item = TwmScenarioMetric(
                    scenario_id=saved.id,
                    metric_code=str(metric.get("metric_code") or metric.get("code") or ""),
                    metric_name=str(metric.get("metric_name") or metric.get("name") or ""),
                    value=float(metric.get("value") or 0.0),
                    unit=str(metric.get("unit") or ""),
                    benchmark_value=metric.get("benchmark_value"),
                    direction=str(metric.get("direction") or "lower_better"),
                    explanation=str(metric.get("explanation") or ""),
                )
                saved_metrics.append(self.repository.save_scenario_metric(item))
            return {
                "scenario": saved.to_dict(),
                "metrics": [item.to_dict() for item in saved_metrics],
            }
        return {"scenario": saved.to_dict(), "metrics": []}

    def compare_scenario(self, scenario_id: str) -> dict[str, Any]:
        scenario = self.repository.get_scenario(scenario_id)
        if scenario is None:
            raise LookupError(f"scenario not found: {scenario_id}")
        metrics = self.repository.list_scenario_metrics(scenario_id)
        delta = {item.metric_code: item.value - (item.benchmark_value or 0.0) for item in metrics}
        return {
            "scenario": scenario.to_dict(),
            "metrics": [item.to_dict() for item in metrics],
            "delta": delta,
            "summary": {
                "metric_count": len(metrics),
                "utility_delta": sum(delta.values()),
            },
        }

    def get_status(self) -> dict[str, Any]:
        return self.status()

    def forecast(self, state_version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")
        execution_mask = dict(payload.get("execution_mask") or {})
        if not execution_mask and bool(payload.get("auto_action_mask")):
            mask_report = self.action_mask_report(state_version_id, payload)
            execution_mask = dict(mask_report.get("execution_mask") or {})
        action = TerritoryWorldModelAction(
            action_type=str(payload.get("action_type") or "inspect"),
            target_role=str(payload.get("target_role") or "project"),
            target_objects=[str(item) for item in payload.get("target_objects") or []],
            spatial_scope=dict(payload.get("spatial_scope") or {}),
            magnitude=float(payload.get("magnitude") or 1.0),
            scenario=str(payload.get("scenario") or "baseline"),
            description=str(payload.get("description") or ""),
            legal_intent=str(payload.get("legal_intent") or ""),
            execution_mask=execution_mask,
            parameters=dict(payload.get("parameters") or {}),
            treatment=str(payload.get("treatment") or ""),
        )
        scenario_context = _mapping_payload(payload.get("scenario_context"))
        scenario_context = self._scenario_context_with_causal_calibration(state_version_id, payload, scenario_context)
        plan = self.planner.plan(
            {
                "state_version": state,
                "objects": state_bundle["objects"],
                "relations": state_bundle["relations"],
                "quality_summary": state.quality_summary,
                "warnings": [],
                "hierarchy_tokens": state.summary,
            },
            action,
            scenario=payload.get("scenario"),
            rule_hits=self.repository.list_rule_hits(state_version_id=state_version_id),
            evidence_coverage=payload.get("evidence_coverage"),
            model_name=payload.get("model_name"),
            model_version=payload.get("model_version"),
            scenario_context=scenario_context,
        )
        result = plan.to_dict()
        candidate_payload = {**payload, "_state_version_id": state_version_id}
        return self._forecast_with_dynamics_candidate(result, candidate_payload)

    def action_mask_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")
        action = self._action_from_payload(payload)
        objects = list(state_bundle.get("objects") or [])
        hits = self.repository.list_rule_hits(state_version_id=state_version_id)
        review_tasks = self.repository.list_review_tasks(state_version_id=state_version_id)
        evidence_items = self.repository.list_evidence_items(state_version_id=state_version_id)
        target_summary = self._action_target_summary(action, objects)
        related_hits = self._action_related_rule_hits(action, target_summary, hits)
        blocking_severities = self._blocking_severities_for_action(action)
        blocking_hits = [
            self._mask_hit_payload(hit)
            for hit in related_hits
            if hit.severity in blocking_severities and hit.hit_status not in {"reviewed_dismissed", "mitigated"}
        ]
        high_review_hits = [
            hit
            for hit in related_hits
            if hit.severity in {"high", "critical", "blocking"} and hit.hit_status not in {"reviewed_dismissed", "mitigated"}
        ]
        review_by_hit = {task.rule_hit_id: task for task in review_tasks}
        required_reviews = []
        for hit in high_review_hits:
            task = review_by_hit.get(hit.id)
            if task is None or task.status == "pending":
                required_reviews.append(
                    {
                        "rule_hit_id": hit.id,
                        "rule_id": hit.rule_id,
                        "severity": hit.severity,
                        "review_task_id": task.id if task else hit.review_task_id,
                        "status": task.status if task else "missing",
                    }
                )
        missing: list[str] = []
        if target_summary["requested_target_count"] and target_summary["matched_target_count"] == 0:
            missing.append("target_objects")
        evidence_by_hit = {item.rule_hit_id for item in evidence_items if item.checksum}
        missing_evidence_hits = [hit.id for hit in related_hits if hit.id not in evidence_by_hit and hit.severity in {"high", "critical", "blocking"}]
        if missing_evidence_hits:
            missing.append("high_severity_evidence")
        hard_blocks = [item["rule_id"] for item in blocking_hits]
        allowed = not hard_blocks and not missing_evidence_hits and target_summary["target_scope_valid"]
        confidence = self._action_mask_confidence(
            target_summary=target_summary,
            blocking_hits=blocking_hits,
            required_reviews=required_reviews,
            missing_evidence_hits=missing_evidence_hits,
        )
        execution_mask = {
            "allowed": allowed,
            "hard_blocks": hard_blocks,
            "required_reviews": [item["rule_id"] for item in required_reviews],
            "confidence": confidence,
            "target_object_count": target_summary["matched_target_count"],
            "related_rule_hit_count": len(related_hits),
            "missing_evidence_hit_count": len(missing_evidence_hits),
        }
        evidence_gate = {
            "passed": allowed and not required_reviews,
            "status": "pass" if allowed and not required_reviews else "review",
            "missing": missing + (["required_reviews"] if required_reviews else []) + (["hard_blocks"] if hard_blocks else []),
            "evidence_item_count": len(evidence_items),
            "related_rule_hit_count": len(related_hits),
        }
        recommendations = []
        if hard_blocks:
            recommendations.append("remove blocked target objects or mitigate critical rule hits before planning")
        if required_reviews:
            recommendations.append("complete required review tasks before upgrading this action claim")
        if missing_evidence_hits:
            recommendations.append("attach checksum evidence for high-severity related rule hits")
        if not target_summary["target_scope_valid"]:
            recommendations.append("provide target objects or a spatial scope matching the requested target role")
        report = TwmActionMaskReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            action=action,
            allowed=allowed,
            execution_mask=execution_mask,
            target_summary=target_summary,
            blocking_hits=blocking_hits,
            required_reviews=required_reviews,
            evidence_gate=evidence_gate,
            recommendations=recommendations,
        )
        return report.to_dict()

    def counterfactual_rollout(self, state_version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")
        baseline_payload = dict(payload.get("baseline_action") or {})
        baseline_action = self._action_from_payload(
            {
                "action_type": baseline_payload.get("action_type") or "inspect",
                "target_role": baseline_payload.get("target_role") or payload.get("target_role") or "project",
                "magnitude": baseline_payload.get("magnitude") or 1.0,
                "scenario": baseline_payload.get("scenario") or payload.get("scenario") or "baseline",
                "description": baseline_payload.get("description") or "baseline reference action",
                "parameters": baseline_payload.get("parameters") or {},
                "treatment": baseline_payload.get("treatment") or "",
            }
        )
        raw_interventions = payload.get("intervention_actions") or payload.get("actions") or []
        if isinstance(raw_interventions, dict):
            raw_interventions = [raw_interventions]
        intervention_actions = [
            self._action_from_payload(
                {
                    "scenario": payload.get("scenario") or baseline_action.scenario,
                    **dict(item),
                }
            )
            for item in raw_interventions
            if isinstance(item, dict)
        ]
        if not intervention_actions:
            intervention_actions = [
                self._action_from_payload(
                    {
                        "action_type": payload.get("action_type") or "protect",
                        "target_role": payload.get("target_role") or "project",
                        "magnitude": payload.get("magnitude") or 1.0,
                        "scenario": payload.get("scenario") or baseline_action.scenario,
                        "description": payload.get("description") or "intervention action",
                        "parameters": dict(payload.get("parameters") or {}),
                        "treatment": payload.get("treatment") or "",
                    }
                )
            ]
        horizon = int(payload.get("horizon") or 3)
        sample_count = horizon * (1 + len(intervention_actions))
        with trace_twm_operation(
            "counterfactual_rollout",
            state_version_id=state_version_id,
            backend="planner",
            sample_count=sample_count,
            gate_status="pending",
        ) as trace_ctx:
            scenario_context = _mapping_payload(payload.get("scenario_context"))
            scenario_context = self._scenario_context_with_causal_calibration(state_version_id, payload, scenario_context)
            rollout = self.planner.counterfactual_rollout(
                {
                    "state_version": state,
                    "objects": state_bundle["objects"],
                    "relations": state_bundle["relations"],
                    "quality_summary": state.quality_summary,
                    "warnings": [],
                    "hierarchy_tokens": state.summary,
                },
                baseline_action=baseline_action,
                intervention_actions=intervention_actions,
                scenario=payload.get("scenario") or baseline_action.scenario,
                horizon=horizon,
                rule_hits=self.repository.list_rule_hits(state_version_id=state_version_id),
                evidence_coverage=payload.get("evidence_coverage"),
                scenario_context=scenario_context,
            )
            result = self._counterfactual_with_dynamics_candidate(rollout.to_dict(), payload)
            _set_trace_attribute(trace_ctx, "twm.gate_status", result.get("evidence_gate", {}).get("status", "review"))
            _set_trace_attribute(trace_ctx, "twm.horizon", int(result.get("horizon") or horizon))
            _set_trace_attribute(trace_ctx, "twm.intervention_action_count", len(intervention_actions))
            _set_trace_attribute(
                trace_ctx,
                "twm.rollout_step_count",
                len(result.get("baseline_steps") or []) + len(result.get("intervention_steps") or []),
            )
            return result

    def beam_plan(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None or self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")
        ranking_policy = self._beam_ranking_policy(payload)
        raw_actions = payload.get("actions") or payload.get("candidate_actions") or []
        if isinstance(raw_actions, dict):
            raw_actions = [raw_actions]
        if not raw_actions:
            raw_actions = [
                {"action_type": "inspect", "target_role": payload.get("target_role") or "project", "magnitude": 1.0},
                {"action_type": "protect", "target_role": payload.get("target_role") or "project", "magnitude": 1.2, "treatment": "causal_calibrated"},
                {"action_type": "expand", "target_role": payload.get("target_role") or "project", "magnitude": 1.3},
            ]
        candidates = []
        for idx, raw_action in enumerate(raw_actions):
            if not isinstance(raw_action, dict):
                continue
            action_payload = dict(payload)
            action_payload.update(dict(raw_action))
            action_payload["scenario"] = raw_action.get("scenario") or payload.get("scenario") or "beam_plan"
            action_payload.setdefault("evidence_coverage", payload.get("evidence_coverage"))
            if payload.get("auto_action_mask") and "auto_action_mask" not in action_payload:
                action_payload["auto_action_mask"] = True
            if payload.get("dynamics_candidate_report") and "dynamics_prediction_id" not in action_payload:
                action_payload["dynamics_prediction_id"] = str(raw_action.get("prediction_id") or f"candidate:{idx}")
            forecast_plan = self.forecast(state_version_id, action_payload)
            candidate = self._beam_candidate_from_forecast(idx, action_payload, forecast_plan, ranking_policy)
            candidates.append(candidate)
        candidates.sort(
            key=lambda item: (
                not self._beam_candidate_hard_blocked(item),
                item["rank_score"],
                item["confidence"],
            ),
            reverse=True,
        )
        limit = max(1, int(payload.get("limit") or payload.get("beam_width") or len(candidates) or 1))
        ranking = []
        for rank, candidate in enumerate(candidates[:limit], start=1):
            candidate["rank"] = rank
            ranking.append(
                {
                    "rank": rank,
                    "candidate_id": candidate["candidate_id"],
                    "action_type": candidate["action"].get("action_type"),
                    "rank_score": candidate["rank_score"],
                    "utility": candidate["utility"],
                    "risk": candidate["risk"],
                    "confidence": candidate["confidence"],
                    "ranking_policy_id": ranking_policy.get("policy_id"),
                    "evidence_gate_status": candidate["evidence_gate"].get("status"),
                    "selection_status": candidate.get("selection_status"),
                    "claim_status": candidate["claim_status"],
                }
            )
        eligible_candidates = [candidate for candidate in candidates if not self._beam_candidate_hard_blocked(candidate)]
        selected = eligible_candidates[0] if eligible_candidates else {}
        evidence_gate = self._beam_evidence_gate(candidates)
        status = "pass" if evidence_gate.get("passed") else "review"
        if not candidates:
            status = "blocked"
        elif not eligible_candidates:
            status = "blocked"
        report = TwmBeamPlanReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            scenario=str(payload.get("scenario") or "beam_plan"),
            status=status,
            ranking_policy=ranking_policy,
            candidates=candidates,
            ranking=ranking,
            selected=selected,
            evidence_gate=evidence_gate,
            recommendations=self._beam_plan_recommendations(candidates, evidence_gate),
        )
        return report.to_dict()

    def farmland_layout_optimization_capability_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None or self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")
        bundle_adapter = {}
        optimization_dir = payload.get("optimization_dir") or payload.get("optimization_bundle_dir")
        if optimization_dir and not (payload.get("candidate_actions") or payload.get("actions")):
            bundle_adapter = self.farmland_layout_candidate_actions_from_optimization_bundle(optimization_dir, payload)
            payload = {
                **payload,
                "candidate_actions": bundle_adapter.get("candidate_actions") or [],
                "optimizer_evidence": bundle_adapter.get("optimizer_evidence") or payload.get("optimizer_evidence") or {},
            }
        actions = payload.get("candidate_actions") or payload.get("actions") or []
        if isinstance(actions, dict):
            actions = [actions]
        candidate_count = len([item for item in actions if isinstance(item, dict)])
        dynamics_candidate = self._candidate_report_from_payload(payload)
        has_dynamics_candidate = bool(dynamics_candidate)
        dynamics_gate = dict(dynamics_candidate.get("evidence_gate") or {})
        if not dynamics_gate and dynamics_candidate:
            dynamics_gate = dict((dynamics_candidate.get("evaluation") or {}).get("evidence_gate") or {})
        optimizer_evidence = dict(payload.get("optimizer_evidence") or {})
        external_optimizer = str(
            payload.get("external_optimizer")
            or optimizer_evidence.get("algorithm_family")
            or optimizer_evidence.get("name")
            or ""
        ).strip()
        has_external_generator = bool(external_optimizer or optimizer_evidence)
        hard_constraint_policy = {
            "schema": "territory_world_model.farmland_layout_hard_constraint_policy.v1",
            "required": True,
            "supported_channels": [
                "action_mask.allowed",
                "action_mask.hard_blocks",
                "TWM-FARM-001",
                "TWM-ECO-001",
                "scenario_constraint_violations",
            ],
            "ranking_rule": "hard-blocked or infeasible candidates must not be promoted as recommended plans",
        }
        current_capabilities = {
            "schema": "territory_world_model.farmland_layout_planner_capabilities.v1",
            "candidate_plan_consumption": True,
            "constrained_beam_ranking": True,
            "action_mask_hard_constraint_filter": True,
            "counterfactual_rollout_comparison": True,
            "multi_head_simulator_consumption": True,
            "evidence_gated_claims": True,
            "audit_trace": True,
            "built_in_layout_generator": False,
            "built_in_model_free_drl_policy_search": False,
            "built_in_model_based_mpc_search": False,
        }
        equivalence = self._farmland_layout_equivalence_assessment(
            candidate_count=candidate_count,
            has_dynamics_candidate=has_dynamics_candidate,
            dynamics_gate=dynamics_gate,
            has_external_generator=has_external_generator,
            optimizer_evidence=optimizer_evidence,
        )
        planner_contract = {
            "schema": "territory_world_model.farmland_layout_optimization_planner_contract.v1",
            "role": "consumer_and_auditor_of_candidate_layout_plans",
            "not_role": "standalone_replacement_for_paper1_to_4_or_paper9_layout_search_backend",
            "can_do_now": [
                "consume candidate layout actions or scenario plans",
                "apply hard-constraint and review gates before ranking",
                "rank feasible candidates with utility/risk/confidence policies",
                "run counterfactual rollout for selected interventions",
                "attach evidence and claim boundary to planning outputs",
            ],
            "requires_for_paper_level_equivalence": [
                "candidate layout generator from DRL, MPC, heuristic, Pareto search or external Paper9 backend",
                "real or quasi-real observed-history validation",
                "spatial and temporal holdout evaluation",
                "hard-constraint infeasible-plan rejection test",
                "planning-lift benchmark against paper baselines",
            ],
            "paper_mapping": {
                "paper1_to_4_model_free_drl": "can be integrated as candidate generator/policy backend; TWM planner audits and ranks outputs",
                "paper9_model_based_world_model_mpc": "can be integrated as simulator/search backend; TWM planner consumes outputs under evidence and hard-constraint gates",
                "current_twm_planner": "constrained beam/ranking consumer over simulator heads, not yet a full standalone farmland layout optimizer",
            },
        }
        report = {
            "schema": "territory_world_model.farmland_layout_optimization_capability_report.v1",
            "state_version_id": state_version_id,
            "project_id": state.project_id,
            "status": equivalence["status"],
            "decision": equivalence["decision"],
            "current_capabilities": current_capabilities,
            "planner_contract": planner_contract,
            "hard_constraint_policy": hard_constraint_policy,
            "inputs": {
                "candidate_action_count": candidate_count,
                "has_dynamics_candidate_report": has_dynamics_candidate,
                "dynamics_candidate_gate_status": dynamics_gate.get("status"),
                "has_external_optimizer_evidence": has_external_generator,
                "external_optimizer": external_optimizer,
                "optimization_bundle_loaded": bool(bundle_adapter),
                "optimization_dir": str(optimization_dir or ""),
            },
            "optimization_bundle": {
                "schema": bundle_adapter.get("schema"),
                "status": bundle_adapter.get("status"),
                "summary": bundle_adapter.get("summary") or {},
                "optimizer_evidence": bundle_adapter.get("optimizer_evidence") or {},
            } if bundle_adapter else {},
            "equivalence_assessment": equivalence,
            "recommendations": self._farmland_layout_capability_recommendations(equivalence, candidate_count, has_external_generator),
            "claim_boundary": {
                "production_claim": "not_supported_without_real_observed_history_and_holdout_validation",
                "paper_level_claim": equivalence["decision"],
                "policy": "TWM may claim planner-consumer and audit capability now; full farmland layout optimization equivalence requires generator/search backend and validation gates",
            },
            "created_at": now_utc_iso(),
        }
        return report

    def farmland_layout_candidate_actions_from_optimization_bundle(
        self,
        optimization_dir: str | Path,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(payload or {})
        root = Path(optimization_dir)
        if not root.exists():
            raise FileNotFoundError(f"optimization bundle not found: {root}")
        candidates = read_csv(root / "scenario_candidates.csv")
        feasibility_rows = read_csv(root / "scenario_feasibility.csv") if (root / "scenario_feasibility.csv").exists() else []
        metric_rows = read_csv(root / "scenario_metrics.csv") if (root / "scenario_metrics.csv").exists() else []
        violation_rows = read_csv(root / "scenario_constraint_violations.csv") if (root / "scenario_constraint_violations.csv").exists() else []
        pareto = read_json(root / "pareto_summary.json") if (root / "pareto_summary.json").exists() else {}
        feasibility_by_id = {str(row.get("scenario_id") or ""): row for row in feasibility_rows}
        metrics_by_id: dict[str, list[dict[str, Any]]] = {}
        for row in metric_rows:
            metrics_by_id.setdefault(str(row.get("scenario_id") or ""), []).append(row)
        violations_by_id: dict[str, list[dict[str, Any]]] = {}
        for row in violation_rows:
            violations_by_id.setdefault(str(row.get("scenario_id") or ""), []).append(row)

        actions: list[dict[str, Any]] = []
        for row in candidates:
            scenario_id = str(row.get("scenario_id") or "").strip()
            if not scenario_id:
                continue
            feasibility = dict(feasibility_by_id.get(scenario_id) or row)
            metrics = metrics_by_id.get(scenario_id) or []
            violations = violations_by_id.get(scenario_id) or []
            blocked = (
                str(feasibility.get("hard_constraint_status") or row.get("hard_constraint_status") or "") != "legal_feasible"
                or truthy(feasibility.get("excluded_from_recommendation") or row.get("excluded_from_recommendation"))
            )
            requires_review = truthy(feasibility.get("requires_legal_review") or row.get("requires_legal_review"))
            hard_blocks = [
                str(item.get("constraint_id") or item.get("objective_id") or "")
                for item in violations
                if str(item.get("severity") or "").lower() in {"critical", "blocking"}
            ]
            hard_blocks = [item for item in hard_blocks if item]
            if blocked and not hard_blocks:
                hard_blocks = ["hard_constraint_violation"]
            weighted_score = self._optimization_weighted_score(scenario_id, pareto, metrics)
            utility = self._optimization_utility_from_metrics(metrics, weighted_score)
            risk = self._optimization_risk_from_feasibility(feasibility, violations)
            confidence = 0.72 if not blocked else 0.38
            actions.append(
                {
                    "candidate_id": scenario_id,
                    "action_type": self._optimization_action_type(row),
                    "target_role": str(payload.get("target_role") or "scenario"),
                    "magnitude": round(max(0.0, safe_float(row.get("project_count"), 0.0) or 0.0), 4),
                    "scenario": scenario_id,
                    "description": str(row.get("description_zh") or row.get("scenario_name_zh") or scenario_id),
                    "legal_intent": "farmland layout optimization under statutory hard constraints",
                    "execution_mask": {
                        "allowed": not blocked,
                        "hard_blocks": hard_blocks,
                        "required_reviews": ["legal_review"] if requires_review else [],
                        "confidence": confidence,
                        "hard_constraint_status": feasibility.get("hard_constraint_status") or row.get("hard_constraint_status"),
                        "excluded_from_recommendation": blocked,
                    },
                    "parameters": {
                        "scenario_name_zh": row.get("scenario_name_zh"),
                        "scenario_type": row.get("scenario_type"),
                        "source": row.get("source"),
                        "optimization_scope": feasibility.get("optimization_scope") or row.get("optimization_scope"),
                        "weighted_score": weighted_score,
                        "planning_utility_delta": utility,
                        "constraint_violation_probability": risk,
                        "hard_constraint_violation_m2": safe_float(feasibility.get("hard_constraint_violation_m2"), 0.0),
                        "pbf_overlap_m2": safe_float(feasibility.get("pbf_overlap_m2"), 0.0),
                        "eco_overlap_m2": safe_float(feasibility.get("eco_overlap_m2"), 0.0),
                    },
                    "provenance": {
                        "optimization_dir": str(root),
                        "synthetic": truthy(row.get("synthetic")),
                        "not_for_production": truthy(row.get("not_for_production")),
                        "source": "twm_optimization_fixture",
                    },
                }
            )
        legal_count = sum(1 for action in actions if (action.get("execution_mask") or {}).get("allowed"))
        blocked_count = len(actions) - legal_count
        return {
            "schema": "territory_world_model.farmland_layout_candidate_actions_from_optimization_bundle.v1",
            "status": "pass" if actions else "review",
            "optimization_dir": str(root),
            "candidate_actions": actions,
            "optimizer_evidence": {
                "algorithm_family": str(payload.get("algorithm_family") or pareto.get("method") or "hard_constraint_filter_then_pareto_summary"),
                "validation": {
                    "hard_constraint_recheck": "pass" if actions and legal_count + blocked_count == len(actions) else "review",
                    "spatial_holdout": payload.get("spatial_holdout_validation") or "not_provided",
                    "temporal_holdout": payload.get("temporal_holdout_validation") or "not_provided",
                    "planning_lift": payload.get("planning_lift_benchmark") or "not_provided",
                },
                "pareto_summary": {
                    "scenario_count": pareto.get("scenario_count", len(actions)),
                    "legal_feasible_scenario_count": pareto.get("legal_feasible_scenario_count", legal_count),
                    "blocked_scenario_count": pareto.get("blocked_scenario_count", blocked_count),
                    "comparison_scope": pareto.get("comparison_scope"),
                    "method": pareto.get("method"),
                    "not_for_production": pareto.get("not_for_production", True),
                },
            },
            "summary": {
                "candidate_count": len(actions),
                "legal_feasible_count": legal_count,
                "blocked_count": blocked_count,
                "hard_constraint_policy": pareto.get("hard_constraint_policy_zh"),
                "claim_boundary": "optimization_fixture_only_not_for_production",
            },
        }

    def farmland_layout_beam_plan_from_optimization_bundle(
        self,
        state_version_id: str,
        optimization_dir: str | Path,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None or self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")
        adapter = self.farmland_layout_candidate_actions_from_optimization_bundle(optimization_dir, payload)
        candidate_actions = [dict(item) for item in adapter.get("candidate_actions") or [] if isinstance(item, dict)]
        beam_payload = dict(payload)
        beam_payload["scenario"] = str(payload.get("scenario") or "farmland_layout_optimization_bundle")
        beam_payload["candidate_actions"] = candidate_actions
        beam_payload["optimizer_evidence"] = adapter.get("optimizer_evidence") or {}
        if "dynamics_candidate_report" not in beam_payload and truthy(payload.get("use_optimizer_metric_projection", True)):
            beam_payload["dynamics_candidate_report"] = self._optimizer_metric_projection_report_from_candidate_actions(
                candidate_actions,
                adapter,
                payload,
            )
            beam_payload["optimizer_metric_projection_applied"] = True
        beam_report = self.beam_plan(state_version_id, beam_payload)
        selection_audit = self._farmland_layout_bundle_beam_selection_audit(adapter, beam_report)
        not_for_production = bool(
            ((adapter.get("optimizer_evidence") or {}).get("pareto_summary") or {}).get("not_for_production", True)
        )
        if not selection_audit.get("eligible_candidate_count"):
            status = "blocked"
        elif selection_audit.get("selected_from_legal_feasible_space") and beam_report.get("status") == "pass" and not not_for_production:
            status = "pass"
        else:
            status = "review"
        return {
            "schema": "territory_world_model.farmland_layout_optimization_beam_plan_report.v1",
            "state_version_id": state_version_id,
            "project_id": state.project_id,
            "status": status,
            "scenario": beam_payload["scenario"],
            "optimization_bundle": {
                "schema": adapter.get("schema"),
                "status": adapter.get("status"),
                "optimization_dir": adapter.get("optimization_dir"),
                "summary": adapter.get("summary") or {},
                "optimizer_evidence": adapter.get("optimizer_evidence") or {},
            },
            "beam_plan": beam_report,
            "selection_audit": selection_audit,
            "claim_boundary": {
                "production_claim": "not_supported_from_fixture_bundle_without_real_observed_history_and_holdout_validation",
                "planner_role": "consumer_and_auditor_of_external_farmland_layout_candidates",
                "hard_constraint_rule": "hard-blocked candidates remain visible for audit but cannot be selected as recommended plans",
                "optimizer_metric_projection": (
                    "used_as_candidate_forecast_input_only"
                    if beam_payload.get("optimizer_metric_projection_applied")
                    else "not_applied"
                ),
            },
            "recommendations": self._farmland_layout_bundle_beam_recommendations(adapter, beam_report, selection_audit),
            "created_at": now_utc_iso(),
        }

    def selected_plan_evaluation_bundle(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None or self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")

        planning_bundle = self._selected_plan_source_bundle(state_version_id, payload)
        beam_report = self._selected_plan_beam_report(planning_bundle)
        selected = dict(beam_report.get("selected") or {})
        selected_action = self._selected_plan_action(selected)
        selection_audit = self._selected_plan_selection_audit(planning_bundle, beam_report, selected)
        rollout_payload = self._selected_plan_rollout_payload(payload, selected_action, selected)
        rollout = self.counterfactual_rollout(state_version_id, rollout_payload)
        validation_payload = self._selected_plan_validation_payload(payload, selected_action, rollout_payload)
        validation = self.validation_report(state_version_id, validation_payload)
        evidence_gate = self._selected_plan_bundle_evidence_gate(selection_audit, beam_report, rollout, validation)
        status = "pass" if evidence_gate.get("status") == "pass" else "review"
        if evidence_gate.get("blocked"):
            status = "blocked"
        return {
            "schema": "territory_world_model.selected_plan_evaluation_bundle.v1",
            "state_version_id": state_version_id,
            "project_id": state.project_id,
            "status": status,
            "source": planning_bundle.get("source") or {},
            "selected": selected,
            "selected_action": selected_action,
            "planning": planning_bundle,
            "counterfactual_rollout": rollout,
            "validation_report": validation,
            "evidence_gate": evidence_gate,
            "claim_boundary": {
                "production_claim": "not_supported_without_real_observed_history_holdout_validation_and_human_review",
                "planning_claim": (
                    "selected_plan_supported_for_review"
                    if status in {"pass", "review"} and selected_action
                    else "selected_plan_not_supported"
                ),
                "hard_constraint_policy": "selected hard-blocked plans cannot be promoted even when optimizer or model scores are high",
                "selected_from_legal_feasible_space": bool(selection_audit.get("selected_from_legal_feasible_space")),
                "validation_overall_status": validation.get("overall_status"),
            },
            "recommendations": self._selected_plan_bundle_recommendations(evidence_gate, selection_audit, validation),
            "created_at": now_utc_iso(),
        }

    def validation_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")

        hits = self.repository.list_rule_hits(state_version_id=state_version_id)
        evidence_items = self.repository.list_evidence_items(state_version_id=state_version_id)
        review_tasks = self.repository.list_review_tasks(state_version_id=state_version_id)
        forecast_payload = {
            "action_type": payload.get("action_type") or "inspect",
            "target_role": payload.get("target_role") or "project",
            "magnitude": payload.get("magnitude") or 1.0,
            "scenario": payload.get("scenario") or "validation_baseline",
            "evidence_coverage": payload.get("evidence_coverage"),
            "treatment": payload.get("treatment") or "",
            "parameters": dict(payload.get("parameters") or {}),
            "scenario_context": _mapping_payload(payload.get("scenario_context")),
        }
        self._copy_dynamics_candidate_payload(payload, forecast_payload)
        forecast = self.forecast(state_version_id, forecast_payload)
        rollout_payload = {
            "scenario": payload.get("scenario") or "validation_counterfactual",
            "horizon": int(payload.get("horizon") or 3),
            "evidence_coverage": payload.get("evidence_coverage"),
            "baseline_action": payload.get("baseline_action") or {
                "action_type": "inspect",
                "target_role": forecast_payload["target_role"],
                "magnitude": 1.0,
            },
            "intervention_actions": payload.get("intervention_actions") or [
                {
                    "action_type": payload.get("intervention_action_type") or "protect",
                    "target_role": forecast_payload["target_role"],
                    "magnitude": payload.get("intervention_magnitude") or 1.0,
                    "treatment": payload.get("treatment") or "",
                    "parameters": dict(payload.get("parameters") or {}),
                }
            ],
            "scenario_context": _mapping_payload(payload.get("scenario_context")),
        }
        self._copy_dynamics_candidate_payload(payload, rollout_payload)
        rollout = self.counterfactual_rollout(state_version_id, rollout_payload)
        audit = self.generate_audit_report(state_version_id)

        stages = [
            self._validation_state_stage(state, state_bundle),
            self._validation_future_stage(forecast),
            self._validation_constraint_stage(hits, forecast),
            self._validation_counterfactual_stage(rollout),
            self._validation_planning_stage(rollout),
            self._validation_deployability_stage(audit, evidence_items, review_tasks),
        ]
        scca_report_for_validation = self._payload_or_build_scca_causal_evidence_report(state_version_id, payload)
        if scca_report_for_validation and "scca_causal_evidence_report" not in payload:
            payload["scca_causal_evidence_report"] = scca_report_for_validation
        scca_stage = self._validation_scca_stage(state_version_id, payload)
        if scca_stage is not None:
            stages.append(scca_stage)
        validation_ladder = [
            "state_build",
            "future_state_prediction",
            "constraint_prediction",
            "counterfactual_rollout",
            "planning_lift",
            "gis_deployability",
        ]
        if scca_stage is not None:
            validation_ladder.append("spatial_causal_evidence")
        claim_ladder = self._validation_claim_ladder(
            state=state,
            payload=payload,
            forecast=forecast,
            rollout=rollout,
            audit=audit,
            review_tasks=review_tasks,
            stages=stages,
        )
        blocking_gaps = [gap for stage in stages if stage.status in {"blocked", "review"} for gap in stage.gaps]
        overall_status = "pass" if all(stage.status == "pass" for stage in stages) else "review"
        if any(stage.status == "blocked" for stage in stages):
            overall_status = "blocked"
        report = TwmValidationReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            overall_status=overall_status,
            stages=stages,
            summary={
                "stage_count": len(stages),
                "passed_stage_count": sum(1 for stage in stages if stage.status == "pass"),
                "review_stage_count": sum(1 for stage in stages if stage.status == "review"),
                "blocked_stage_count": sum(1 for stage in stages if stage.status == "blocked"),
                "blocking_gaps": blocking_gaps,
                "claim_ladder": claim_ladder,
                "validation_ladder": validation_ladder,
            },
        )
        return report.to_dict()

    def world_model_profile(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")
        validation = self.validation_report(state_version_id, payload)
        audit = self.generate_audit_report(state_version_id)
        hits = self.repository.list_rule_hits(state_version_id=state_version_id)
        evidence_items = self.repository.list_evidence_items(state_version_id=state_version_id)
        review_tasks = self.repository.list_review_tasks(state_version_id=state_version_id)
        stage_status = {stage.get("stage_code"): stage.get("status") for stage in validation.get("stages", [])}
        quality_summary = dict(state.quality_summary or {})

        rendering_status = "pass" if state.object_count and state.relation_count else "review"
        simulation_status = "pass" if stage_status.get("future_state_prediction") == "pass" and stage_status.get("counterfactual_rollout") in {"pass", "review"} else "review"
        planning_status = "pass" if stage_status.get("planning_lift") == "pass" else "review"
        closed_loop_status = "pass" if stage_status.get("gis_deployability") == "pass" else "review"
        evidence_status = "pass" if audit.get("evidence_gate_passed") else "review"

        capabilities = [
            TwmWorldModelCapability(
                axis="rendering",
                status=rendering_status,
                interpretation=(
                    "TWM does not render photorealistic visual worlds; it renders GIS-operational world state "
                    "as hierarchical objects, relations, rule overlays and audit-ready map/table artifacts."
                ),
                core_algorithm={
                    "role_in_taxonomy": "renderer",
                    "algorithm_family": "structured GIS state renderer",
                    "core_algorithm": "MMFE semantic bundle -> hierarchical object-relation state construction -> rule/evidence overlay composition",
                    "current_implementation": [
                        "StateBuilder semantic ingestion",
                        "hierarchy token summarization",
                        "rule overlay assembly",
                        "audit-ready map/table state packaging",
                    ],
                    "note": "In Fei-Fei Li's sense this renderer emits structured territorial observations rather than RGB pixels.",
                },
                implemented_components=[
                    "state objects",
                    "state relations",
                    "hierarchy tokens",
                    "rule overlays",
                    "audit report inputs",
                ],
                evidence={
                    "object_count": state.object_count,
                    "relation_count": state.relation_count,
                    "object_counts_by_role": (state.summary or {}).get("object_counts_by_role", {}),
                    "relation_counts_by_type": (state.summary or {}).get("relation_counts_by_type", {}),
                },
                gaps=[
                    "photorealistic 3D/4D rendering is outside current TWM scope",
                    "cartographic front-end rendering is a consumer layer, not the world model core",
                ],
            ),
            TwmWorldModelCapability(
                axis="simulation",
                status=simulation_status,
                interpretation=(
                    "TWM simulation means action-conditioned rollout over territorial state, constraint state, "
                    "utility state and uncertainty, not only next-frame image prediction."
                ),
                core_algorithm={
                    "role_in_taxonomy": "simulator",
                    "algorithm_family": "action-conditioned territorial dynamics",
                    "core_algorithm": "multi-head forecast + counterfactual rollout over a future-state latent decoded into area, feature-count, land-space-type and transition-delta summaries, plus constraint, utility and uncertainty, backed by deterministic scaffold, trainable MLP candidate, hierarchical graph-temporal candidate, or lightweight spatiotemporal transformer candidate",
                    "current_implementation": [
                        "deterministic forecast scaffold",
                        "counterfactual rollout",
                        "torch_multi_head_mlp candidate",
                        "torch_hierarchical_graph candidate with relation + temporal message mixing",
                        "torch_spatiotemporal_transformer candidate with fixed semantic token attention",
                    ],
                    "note": "The current trainable simulator includes small candidate backends, not yet the final production-scale territorial graph transformer.",
                },
                implemented_components=[
                    "future-state latent decoded into area, feature-count, land-space-type and transition-delta summaries",
                    "constraint violation probability",
                    "counterfactual rollout",
                    "uncertainty and calibration metadata",
                ],
                evidence={
                    "future_state_stage": stage_status.get("future_state_prediction"),
                    "counterfactual_stage": stage_status.get("counterfactual_rollout"),
                    "quality_summary": quality_summary,
                },
                gaps=[
                    "only a small local neural trainable candidate is implemented; the final graph/transformer hierarchical dynamics backbone is still missing",
                    "temporal holdout validation is still required for simulation claims",
                ],
            ),
            TwmWorldModelCapability(
                axis="planning",
                status=planning_status,
                interpretation=(
                    "TWM planning is a consumer-facing capability: forecast and rollout outputs are consumed by "
                    "beam search, latent MPC or constrained rollout. The planner is not the world model itself."
                ),
                core_algorithm={
                    "role_in_taxonomy": "planner",
                    "algorithm_family": "constrained action ranking and rollout consumption",
                    "core_algorithm": "evidence-gated constrained beam search over candidate actions using a configurable utility/risk/confidence ranking policy, with action-mask filtering and optional dynamics candidate consumption",
                    "current_implementation": [
                        "beam-plan candidate ranking",
                        "action-mask gating",
                        "counterfactual baseline/intervention comparison",
                        "validation-ladder planning lift check",
                    ],
                    "note": "Latent MPC is still a target consumer architecture; the currently implemented planner core is constrained beam planning plus rollout comparison.",
                },
                implemented_components=[
                    "planning utility delta",
                    "baseline/intervention delta",
                    "beam-search planning facade",
                    "validation ladder planning lift stage",
                ],
                evidence={
                    "planning_lift_stage": stage_status.get("planning_lift"),
                    "rule_hit_count": len(hits),
                },
                gaps=[
                    "candidate ranking loss is not yet trained",
                    "hard action-mask search over target object sets is not yet implemented",
                ],
            ),
            TwmWorldModelCapability(
                axis="closed_loop",
                status=closed_loop_status,
                interpretation=(
                    "Following the renderer-simulator-planner loop, TWM closes the loop through GIS evidence, "
                    "rule review and audit reports rather than direct autonomous execution."
                ),
                implemented_components=[
                    "rule evaluation",
                    "evidence checksums",
                    "review tasks",
                    "audit report",
                    "validation report",
                ],
                evidence={
                    "gis_deployability_stage": stage_status.get("gis_deployability"),
                    "evidence_item_count": len(evidence_items),
                    "review_task_count": len(review_tasks),
                },
                gaps=[
                    "human review completion is required before administrative deployment",
                    "live GIS front-end feedback is still a downstream integration task",
                ],
            ),
            TwmWorldModelCapability(
                axis="evidence_provenance",
                status=evidence_status,
                interpretation=(
                    "TWM extends the functional taxonomy with a GIS governance axis: every forecast, rollout "
                    "and planning claim must be traceable to source data, rules, evidence and review state."
                ),
                implemented_components=[
                    "source manifest",
                    "evidence items",
                    "checksums",
                    "rule hit explanations",
                    "review tasks",
                ],
                evidence={
                    "evidence_gate_passed": audit.get("evidence_gate_passed"),
                    "evidence_gate_summary": audit.get("evidence_gate_summary", {}),
                },
                gaps=[] if evidence_status == "pass" else ["evidence gate did not pass for all current claims"],
            ),
        ]
        profile = TwmWorldModelProfile(
            state_version_id=state_version_id,
            project_id=state.project_id,
            taxonomy="fei_fei_li_functional_taxonomy_plus_gis_evidence",
            capabilities=capabilities,
            summary={
                "source_article": {
                    "title": "A Functional Taxonomy of World Models",
                    "author": "Fei-Fei Li",
                    "published_at": "2026-06-03",
                    "url": "https://drfeifei.substack.com/p/a-functional-taxonomy-of-world-models",
                    "note": "Article/blog essay, not a peer-reviewed paper.",
                },
                "capability_count": len(capabilities),
                "pass_count": sum(1 for item in capabilities if item.status == "pass"),
                "review_count": sum(1 for item in capabilities if item.status == "review"),
                "core_alignment": [
                    "renderer -> GIS-operational state rendering",
                    "simulator -> action-conditioned territorial rollout",
                    "planner -> constrained planning consumer",
                    "loop -> evidence-gated GIS review and audit loop",
                ],
            },
        )
        return profile.to_dict()

    def dynamics_training_examples(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        cache_key = self._report_cache_key(
            state_version_id,
            payload,
            include=(
                "scenario",
                "evidence_coverage",
                "horizon",
                "actions",
                "scenario_context",
                "split",
                "temporal_holdout",
                "holdout_year",
                "rule_version",
                "policy_version",
                "model_version",
                "baseline_version",
                "random_seed",
                "thresholds",
                "geofm_gate_report",
                "include_synthetic",
                "max_examples",
                "limit",
            ),
        )
        cached = self._cache_get(self._dynamics_training_cache, cache_key)
        if cached is not None:
            return cached
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")
        scenario = str(payload.get("scenario") or "dynamics_training").strip() or "dynamics_training"
        evidence_coverage = payload.get("evidence_coverage")
        horizon = int(payload.get("horizon") or 2)
        raw_actions = payload.get("actions")
        if not raw_actions:
            raw_actions = [
                {"action_type": "inspect", "target_role": "project", "magnitude": 1.0, "description": "baseline inspection"},
                {"action_type": "protect", "target_role": "project", "magnitude": 1.2, "description": "farmland protection intervention", "treatment": "causal_calibrated"},
                {"action_type": "expand", "target_role": "project", "magnitude": 1.4, "description": "development pressure stress test"},
            ]
        actions = [self._action_from_payload({"scenario": scenario, **dict(item)}) for item in raw_actions if isinstance(item, dict)]
        rule_hits = self.repository.list_rule_hits(state_version_id=state_version_id)
        evidence_items = self.repository.list_evidence_items(state_version_id=state_version_id)
        validation = self.validation_report(
            state_version_id,
            {
                "scenario": scenario,
                "horizon": horizon,
                "evidence_coverage": evidence_coverage,
                "scenario_context": _mapping_payload(payload.get("scenario_context")),
            },
        )
        source_transition_examples = self._temporal_transition_examples_from_state_snapshots(
            state=state,
            state_bundle=state_bundle,
            scenario=scenario,
            evidence_coverage=evidence_coverage,
            rule_hits=rule_hits,
            validation=validation,
            payload=payload,
        )
        current_state_summary = {
            "object_count": state.object_count,
            "relation_count": state.relation_count,
            "object_counts_by_role": (state.summary or {}).get("object_counts_by_role", {}),
            "relation_counts_by_type": (state.summary or {}).get("relation_counts_by_type", {}),
            "quality_summary": state.quality_summary,
            "hierarchy_tokens": self._state_hierarchy_tokens(state),
        }
        examples: list[TwmDynamicsTrainingExample] = []
        for idx, action in enumerate(actions):
            forecast = self.planner.forecast(
                {
                    "state_version": state,
                    "objects": state_bundle["objects"],
                    "relations": state_bundle["relations"],
                    "quality_summary": state.quality_summary,
                    "warnings": [],
                    "hierarchy_tokens": state.summary,
                },
                action,
                scenario=scenario,
                rule_hits=rule_hits,
                evidence_coverage=evidence_coverage,
                scenario_context=_mapping_payload(payload.get("scenario_context")),
            )
            action_mask = (forecast.evidence_gate or {}).get("action_mask") or {}
            not_for_training: list[str] = []
            if forecast.evidence_gate.get("status") != "pass":
                not_for_training.append("evidence_gate_not_passed")
            if validation.get("overall_status") != "pass":
                not_for_training.append("validation_report_not_fully_passed")
            if not evidence_items:
                not_for_training.append("no_evidence_items")
            if not action_mask.get("allowed", True):
                not_for_training.append("action_mask_blocks_execution")
            example = TwmDynamicsTrainingExample(
                state_version_id=state_version_id,
                project_id=state.project_id,
                split=str(payload.get("split") or "candidate"),
                sample_type="action_conditioned_forecast",
                current_state_summary=current_state_summary,
                action=action,
                scenario_context={
                    "scenario": scenario,
                    "horizon": horizon,
                    "scenario_context": _mapping_payload(payload.get("scenario_context")),
                    "temporal_holdout": self._temporal_holdout_policy(payload),
                },
                targets={
                    "future_latent_state": forecast.future_latent_state,
                    "constraint_violation_probability": forecast.constraint_violation_probability,
                    "planning_utility_delta": forecast.planning_utility_delta,
                    "uncertainty": forecast.uncertainty,
                    "calibration": forecast.calibration,
                    "action_mask": action_mask,
                },
                labels={
                    "constraint_label": "violation_likely" if forecast.constraint_violation_probability >= 0.5 else "violation_unlikely",
                    "utility_label": "positive_lift" if forecast.planning_utility_delta > 0 else "non_positive_lift",
                    "ranking_score": round(forecast.planning_utility_delta - forecast.constraint_violation_probability, 4),
                    "evidence_supported": forecast.evidence_gate.get("status") == "pass",
                    "supervision_source": "deterministic_scaffold",
                },
                losses={
                    "transition_loss": "future_latent_state",
                    "constraint_loss": "constraint_violation_probability",
                    "planning_ranking_loss": "ranking_score",
                    "calibration_loss": "calibration.calibrated_utility_delta",
                    "uncertainty_calibration_loss": "uncertainty.confidence",
                    "evidence_consistency_loss": "evidence_gate.status",
                    "action_mask_loss": "targets.action_mask.allowed",
                },
                evidence_gate=forecast.evidence_gate,
                provenance={
                    "state_version_id": state_version_id,
                    "rule_hit_count": len(rule_hits),
                    "evidence_item_count": len(evidence_items),
                    "validation_overall_status": validation.get("overall_status"),
                    "sample_index": idx,
                    "sample_family": "forecast_scaffold",
                    "ground_truth": False,
                },
                not_for_training_reasons=not_for_training,
            )
            examples.append(example)
        examples.extend(source_transition_examples)
        examples.sort(key=lambda item: item.labels.get("ranking_score", 0.0), reverse=True)
        state_contract = self.state_contract_report(state_version_id, payload)
        dataset = TwmDynamicsTrainingDataset(
            state_version_id=state_version_id,
            project_id=state.project_id,
            examples=examples,
            summary={
                "example_count": len(examples),
                "forecast_scaffold_example_count": sum(1 for item in examples if item.sample_type == "action_conditioned_forecast"),
                "temporal_transition_example_count": sum(1 for item in examples if item.sample_type == "temporal_state_transition"),
                "usable_example_count": sum(1 for item in examples if not item.not_for_training_reasons),
                "review_example_count": sum(1 for item in examples if item.not_for_training_reasons),
                "temporal_holdout": self._temporal_holdout_policy(payload),
                "top_action": examples[0].action.to_dict() if examples else {},
                "loss_contract": {
                    "transition_loss": "predict observed/synthetic future latent state from hierarchical current state and action",
                    "constraint_loss": "predict future constraint state and violation probability",
                    "planning_ranking_loss": "rank candidate actions by downstream utility minus constraint risk",
                    "calibration_loss": "calibrate utility and scenario scale with causal/treatment evidence",
                    "uncertainty_calibration_loss": "align uncertainty with observed error and evidence coverage",
                    "evidence_consistency_loss": "penalize unsupported claim upgrades",
                    "action_mask_loss": "learn infeasible or review-required action regions",
                },
                "supervision_sources": {
                    "deterministic_scaffold": sum(1 for item in examples if item.labels.get("supervision_source") == "deterministic_scaffold"),
                    "state_snapshots": sum(1 for item in examples if item.labels.get("supervision_source") == "state_snapshots"),
                },
                "mrep_trace": self._dynamics_dataset_mrep_trace(
                    state=state,
                    payload=payload,
                    examples=examples,
                    state_contract=state_contract,
                ),
                "schema_notes": [
                    "This is a training-data contract for future trainable dynamics.",
                    "Forecast scaffold targets are generated by deterministic TWM logic and must not be treated as ground truth labels.",
                    "Temporal transition targets from state_snapshots are usable only within their provenance flags; synthetic or not_for_production rows remain review-only.",
                    "Use evidence_gate and validation status to decide whether a sample can supervise a claim.",
                ],
            },
        )
        result = dataset.to_dict()
        self._cache_set(self._dynamics_training_cache, cache_key, result)
        return deepcopy(result)

    def dynamics_readiness_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None:
            raise LookupError(f"state not found: {state_version_id}")
        cache_key = self._report_cache_key(
            state_version_id,
            payload,
            include=(
                "dataset",
                "scenario",
                "evidence_coverage",
                "horizon",
                "actions",
                "scenario_context",
                "split",
                "temporal_holdout",
                "thresholds",
                "require_geofm_pass",
                "require_causal_pass",
                "uses_geofm",
                "geofm_required",
                "uses_causal_calibration",
                "causal_required",
                "causal_calibration_required",
                "geofm_gate_report",
                "causal_calibration_report",
                "baseline_metrics",
                "augmented_metrics",
                "geofm_metrics",
                "baseline_predictions",
                "b0_predictions",
                "baseline_dynamics_predictions",
                "augmented_predictions",
                "geofm_predictions",
                "b1_predictions",
                "augmented_dynamics_predictions",
                "baseline_dynamics_candidate_report",
                "b0_candidate_report",
                "augmented_dynamics_candidate_report",
                "geofm_candidate_report",
                "b1_candidate_report",
                "geofm_dynamics_evaluation_report",
                "augmented_dynamics_evaluation_report",
                "dynamics_evaluation_report",
                "extended_validation",
                "architecture_audit",
                "geofm_architecture_audit",
                "adapter",
                "geofm_adapter",
                "backbone",
                "geofm_backbone",
                "data_validation",
                "geofm_data_validation",
                "geofm_backbone_name",
                "geofm_architecture",
                "fused_qkv",
                "geofm_adapter_type",
                "geofm_adapter_target_modules",
                "geofm_input_modalities",
                "records",
                "observations",
                "observed_history",
                "observed_history_path",
                "approval_review_history_path",
                "approval_history_path",
                "observed_approval_history_path",
                "causal_thresholds",
                "model_effect",
                "baseline_action",
                "intervention_actions",
                "treatment",
                "treatment_name",
                "outcome",
                "outcome_name",
                "positive_label",
                "outcome_direction",
                "action_type",
                "target_role",
                "magnitude",
                "parameters",
                "scca_causal_evidence_report",
                "scca_evidence_report",
                "scca_result",
                "scca_report",
                "scca_payload",
                "scca_output_dir",
                "scca_dir",
                "scca_path",
                "scca_manifest_path",
            ),
        )
        cached = self._cache_get(self._dynamics_readiness_cache, cache_key)
        if cached is not None:
            return cached
        if self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")
        dataset_payload = payload.get("dataset")
        dataset = dict(dataset_payload) if isinstance(dataset_payload, dict) else self.dynamics_training_examples(state_version_id, payload)
        thresholds = self._dynamics_readiness_thresholds(payload)
        sample_inventory = self._dynamics_sample_inventory(dataset)
        gate_results = self._dynamics_readiness_gates(
            state_version_id=state_version_id,
            dataset=dataset,
            inventory=sample_inventory,
            thresholds=thresholds,
            payload=payload,
        )
        status = self._dynamics_readiness_status(gate_results)
        training_scope = self._dynamics_training_scope(gate_results)
        recommendations = self._dynamics_readiness_recommendations(
            inventory=sample_inventory,
            gate_results=gate_results,
            thresholds=thresholds,
        )
        state_contract = self.state_contract_report(state_version_id, payload)
        report = TwmDynamicsReadinessReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            status=status,
            training_scope=training_scope,
            sample_inventory=sample_inventory,
            thresholds=thresholds,
            gate_results=gate_results,
            target_model_contract=self._dynamics_target_model_contract(dataset, gate_results, state_contract=state_contract),
            recommendations=recommendations,
        )
        result = report.to_dict()
        self._cache_set(self._dynamics_readiness_cache, cache_key, result)
        return deepcopy(result)

    def dynamics_evaluation_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None or self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")
        dataset_payload = payload.get("dataset")
        dataset = dict(dataset_payload) if isinstance(dataset_payload, dict) else self.dynamics_training_examples(state_version_id, payload)
        readiness = self.dynamics_readiness_report(state_version_id, {"dataset": dataset, **payload})
        candidate = self._dynamics_candidate_descriptor(payload)
        predictions = self._dynamics_predictions_for_evaluation(dataset, payload)
        metrics, target_head_metrics, eval_inventory = self._dynamics_evaluation_metrics(dataset, predictions)
        evidence_gate = self._dynamics_evaluation_gate(
            readiness=readiness,
            candidate=candidate,
            metrics=metrics,
            eval_inventory=eval_inventory,
            payload=payload,
        )
        status = "pass" if evidence_gate.get("passed") else "review"
        if evidence_gate.get("blocked"):
            status = "blocked"
        report = TwmDynamicsEvaluationReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            status=status,
            candidate=candidate,
            evaluation_scope={
                "readiness_status": readiness.get("status"),
                "readiness_training_scope": readiness.get("training_scope"),
                "split": payload.get("split") or "holdout",
                "prediction_source": "payload_predictions" if payload.get("predictions") else "deterministic_scaffold_baseline",
            },
            metrics=metrics,
            target_head_metrics=target_head_metrics,
            evidence_gate=evidence_gate,
            sample_inventory=eval_inventory,
            recommendations=self._dynamics_evaluation_recommendations(evidence_gate, candidate, eval_inventory),
        )
        return report.to_dict()

    def dynamics_model_registry_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        candidate_report = self._payload_mapping(payload.get("candidate_report") or payload.get("dynamics_candidate_report"))
        readiness_report = self._payload_mapping(payload.get("readiness_report") or payload.get("dynamics_readiness_report"))
        evaluation_report = self._payload_mapping(payload.get("evaluation_report") or payload.get("dynamics_evaluation_report"))
        registry_metadata = self._payload_mapping(payload.get("registry_metadata") or payload.get("metadata"))
        training_dataset = self._payload_mapping(payload.get("dynamics_training_dataset") or payload.get("dataset"))
        candidate = self._payload_mapping(candidate_report.get("candidate") or payload.get("candidate"))
        if not candidate:
            candidate = self._dynamics_candidate_descriptor(payload)
        model_name = compact_text(candidate.get("model_name") or payload.get("model_name") or "unnamed_dynamics_candidate")
        model_version = compact_text(candidate.get("model_version") or payload.get("model_version") or "unversioned")
        model_family = compact_text(candidate.get("model_family") or payload.get("model_family") or "twm_dynamics")
        registry_key = f"{model_name}:{model_version}"

        candidate_gate = self._payload_mapping(candidate_report.get("evidence_gate"))
        candidate_gate_status = compact_text(candidate_gate.get("status") or candidate_report.get("status") or "review")
        readiness_status = compact_text(readiness_report.get("status") or "review")
        evaluation_gate = self._payload_mapping(evaluation_report.get("evidence_gate"))
        evaluation_status = compact_text(evaluation_gate.get("status") or evaluation_report.get("status") or "review")
        production_gate = self._payload_mapping(payload.get("production_data_gate") or payload.get("production_gate"))
        production_status = compact_text(production_gate.get("status") or "blocked")
        target_head_metrics = self._payload_mapping(evaluation_report.get("target_head_metrics"))
        future_latent_metrics = self._payload_mapping(target_head_metrics.get("future_latent_state"))
        candidate_evaluation = self._payload_mapping(candidate_report.get("evaluation"))
        candidate_eval_head_metrics = self._payload_mapping(candidate_evaluation.get("target_head_metrics"))
        candidate_eval_future_latent_metrics = self._payload_mapping(candidate_eval_head_metrics.get("future_latent_state"))
        latent_v2_quality = self._payload_mapping(
            future_latent_metrics.get("latent_v2_quality")
            or evaluation_report.get("latent_v2_quality")
            or candidate_eval_future_latent_metrics.get("latent_v2_quality")
        )
        if not latent_v2_quality:
            latent_v2_quality = {
                "schema": "territory_world_model.future_latent_state_v2_quality.v1",
                "status": "review",
                "missing": ["latent_v2_quality_report"],
            }
        latent_v2_quality_status = compact_text(latent_v2_quality.get("status") or "review")

        missing_for_promotion: list[str] = []
        if candidate_gate_status != "pass":
            missing_for_promotion.append("candidate_evidence_gate_pass")
        if readiness_status != "pass":
            missing_for_promotion.append("readiness_pass")
        if evaluation_status != "pass":
            missing_for_promotion.append("evaluation_pass")
        if production_status != "pass":
            missing_for_promotion.append("production_observed_history")
        if bool(candidate.get("is_scaffold_baseline")) or bool(candidate.get("is_scaffold_trainer")):
            missing_for_promotion.append("non_scaffold_candidate")
        if latent_v2_quality_status != "pass":
            missing_for_promotion.append("latent_v2_quality_pass")

        learned_metadata = self._payload_mapping(self._payload_mapping(candidate_report.get("learned_parameters")).get("metadata"))
        combined_metadata = {
            **self._payload_mapping(candidate.get("metadata")),
            **learned_metadata,
            **registry_metadata,
        }
        if training_dataset and not compact_text(combined_metadata.get("training_dataset_hash")):
            combined_metadata["training_dataset_hash"] = _stable_sha256(training_dataset)
        required_registry_metadata = [
            "state_contract_version",
            "training_dataset_hash",
            "training_dataset_snapshot",
            "training_run_id",
            "model_artifact_uri",
            "evaluation_report_id",
        ]
        missing_registry_metadata = [
            name for name in required_registry_metadata
            if not compact_text(combined_metadata.get(name))
        ]

        if not missing_for_promotion and not missing_registry_metadata:
            promotion_decision = "candidate_for_registry_promotion"
        elif "non_scaffold_candidate" in missing_for_promotion:
            promotion_decision = "blocked_scaffold_not_promoted"
        else:
            promotion_decision = "review_only_not_promoted"
        current_registry_key = compact_text(payload.get("current_registry_key") or payload.get("production_registry_key") or "")
        lineage_keys = [
            "state_contract_version",
            "training_dataset_hash",
            "training_dataset_snapshot",
            "training_run_id",
            "model_artifact_uri",
            "evaluation_report_id",
        ]
        registry_lineage = {
            key: combined_metadata.get(key)
            for key in lineage_keys
            if compact_text(combined_metadata.get(key))
        }
        rollback_plan = {
            "action": "pin_candidate_with_previous_version_rollback" if promotion_decision == "candidate_for_registry_promotion" else "keep_current_production_version",
            "current_registry_key": current_registry_key,
            "candidate_registry_key": registry_key,
            "rollback_available": bool(current_registry_key),
            "reason": (
                "all registry gates and required metadata passed"
                if promotion_decision == "candidate_for_registry_promotion"
                else "candidate remains review-only until gates and registry metadata pass"
            ),
        }
        return json.loads(_json({
            "schema": "territory_world_model.dynamics_model_registry_report.v1",
            "generated_at": now_utc_iso(),
            "state_version_id": state_version_id,
            "registry_entry": {
                "registry_key": registry_key,
                "model_name": model_name,
                "model_version": model_version,
                "model_family": model_family,
                "candidate_status": candidate_report.get("status", "review"),
                "version_pin_policy": "immutable_model_name_version_plus_training_dataset_hash",
                "metadata": combined_metadata,
                "lineage": registry_lineage,
                "latent_v2_quality": latent_v2_quality,
            },
            "gates": {
                "candidate_gate": {
                    "status": candidate_gate_status,
                    "passed": candidate_gate_status == "pass",
                },
                "readiness_gate": {
                    "status": readiness_status,
                    "passed": readiness_status == "pass",
                    "blocked_gates": list(((readiness_report.get("gates") or {}).get("summary") or {}).get("blocked_gates") or []),
                },
                "evaluation_gate": {
                    "status": evaluation_status,
                    "passed": evaluation_status == "pass",
                },
                "production_data_gate": {
                    "status": production_status,
                    "passed": production_status == "pass",
                },
                "latent_v2_quality_gate": {
                    "status": latent_v2_quality_status,
                    "passed": latent_v2_quality_status == "pass",
                    "missing": list(latent_v2_quality.get("missing") or []),
                },
            },
            "required_registry_metadata": required_registry_metadata,
            "missing_registry_metadata": missing_registry_metadata,
            "missing_for_promotion": sorted(set(missing_for_promotion)),
            "promotion_decision": promotion_decision,
            "rollback_plan": rollback_plan,
            "recommendations": [
                "pin model_name, model_version, training dataset hash, state contract version and evaluation report id before promotion",
                "keep review-only candidates out of production forecast defaults until readiness, evaluation and production data gates pass",
                "retain the previous production registry key for rollback before switching forecast consumers",
            ],
            "claim_boundary": (
                "This registry report is a release gate for TWM dynamics candidates. "
                "A review-only candidate may be used for experiments or demos, but must not become the production default until all registry, readiness, evaluation and production-data gates pass."
            ),
        }))

    def activate_dynamics_model_registry_entry(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        report = self.dynamics_model_registry_report(state_version_id, payload)
        entry = self._dynamics_model_registry_entry_from_report(state_version_id, report)
        previous_active = self.repository.get_active_dynamics_model_registry_entry(state_version_id)
        previous_active_payload = previous_active.to_dict() if previous_active else None
        if report.get("promotion_decision") == "candidate_for_registry_promotion":
            if previous_active and previous_active.registry_key != entry.registry_key:
                previous_active.status = "superseded"
                previous_active.updated_at = now_utc_iso()
                self.repository.save_dynamics_model_registry_entry(previous_active)
            entry.status = "active"
            entry.previous_active_registry_key = previous_active.registry_key if previous_active else ""
            entry.activated_at = now_utc_iso()
        else:
            entry.status = "review_only"
        saved = self.repository.save_dynamics_model_registry_entry(entry)
        return json.loads(_json({
            "schema": "territory_world_model.dynamics_model_registry_activation.v1",
            "state_version_id": state_version_id,
            "status": "active" if saved.status == "active" else "review_only",
            "active_entry": saved.to_dict() if saved.status == "active" else None,
            "saved_entry": saved.to_dict(),
            "previous_active_entry": previous_active_payload,
            "registry_report": report,
            "claim_boundary": "Only entries with candidate_for_registry_promotion are activated; review-only entries are saved for audit but not used as production defaults.",
        }))

    def list_dynamics_model_registry_entries(self, state_version_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        status = compact_text(payload.get("status") or "")
        entries = self.repository.list_dynamics_model_registry_entries(state_version_id, status=status or None)
        return json.loads(_json({
            "schema": "territory_world_model.dynamics_model_registry_entries.v1",
            "state_version_id": state_version_id or "",
            "status_filter": status,
            "entry_count": len(entries),
            "entries": [entry.to_dict() for entry in entries],
        }))

    def rollback_dynamics_model_registry(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        current = self.repository.get_active_dynamics_model_registry_entry(state_version_id)
        if current is None:
            return {
                "schema": "territory_world_model.dynamics_model_registry_rollback.v1",
                "state_version_id": state_version_id,
                "status": "blocked",
                "missing": ["active_registry_entry"],
            }
        target_key = compact_text(payload.get("target_registry_key") or current.previous_active_registry_key)
        candidates = self.repository.list_dynamics_model_registry_entries(state_version_id)
        target = next((entry for entry in candidates if entry.registry_key == target_key), None)
        if target is None:
            return {
                "schema": "territory_world_model.dynamics_model_registry_rollback.v1",
                "state_version_id": state_version_id,
                "status": "blocked",
                "missing": ["rollback_target_registry_entry"],
                "rolled_back_entry": current.to_dict(),
                "target_registry_key": target_key,
            }
        current.status = "rolled_back"
        current.updated_at = now_utc_iso()
        self.repository.save_dynamics_model_registry_entry(current)
        target.status = "active"
        target.previous_active_registry_key = current.registry_key
        target.activated_at = now_utc_iso()
        target.updated_at = now_utc_iso()
        restored = self.repository.save_dynamics_model_registry_entry(target)
        return json.loads(_json({
            "schema": "territory_world_model.dynamics_model_registry_rollback.v1",
            "state_version_id": state_version_id,
            "status": "pass",
            "restored_entry": restored.to_dict(),
            "rolled_back_entry": current.to_dict(),
            "claim_boundary": "Rollback only changes the active registry pointer; it does not retrain, alter model artifacts, or bypass registry gates.",
        }))

    def _dynamics_model_registry_entry_from_report(self, state_version_id: str, report: dict[str, Any]) -> TwmDynamicsModelRegistryEntry:
        state = self.repository.get_state_version(state_version_id)
        registry_entry = self._payload_mapping(report.get("registry_entry"))
        return TwmDynamicsModelRegistryEntry(
            state_version_id=state_version_id,
            project_id=state.project_id if state else compact_text(report.get("project_id") or ""),
            registry_key=compact_text(registry_entry.get("registry_key") or ""),
            model_name=compact_text(registry_entry.get("model_name") or ""),
            model_version=compact_text(registry_entry.get("model_version") or ""),
            model_family=compact_text(registry_entry.get("model_family") or ""),
            status="candidate",
            promotion_decision=compact_text(report.get("promotion_decision") or "review_only_not_promoted"),
            registry_report=report,
            lineage=self._payload_mapping(registry_entry.get("lineage")),
            metadata=self._payload_mapping(registry_entry.get("metadata")),
        )

    def fit_dynamics_candidate(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None or self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")
        dataset_payload = payload.get("dataset")
        dataset = dict(dataset_payload) if isinstance(dataset_payload, dict) else self.dynamics_training_examples(state_version_id, payload)
        readiness = self.dynamics_readiness_report(state_version_id, {"dataset": dataset, **payload})
        candidate = self._fit_candidate_descriptor(payload)
        if readiness.get("status") != "pass":
            evidence_gate = {
                "passed": False,
                "blocked": True,
                "status": "blocked",
                "missing": ["readiness_pass"],
            }
            report = TwmDynamicsFitReport(
                state_version_id=state_version_id,
                project_id=state.project_id,
                status="blocked",
                candidate=candidate,
                readiness=readiness,
                learned_parameters={},
                predictions={},
                evaluation={},
                evidence_gate=evidence_gate,
                recommendations=[
                    "dynamics candidate fitting is blocked until readiness gate passes",
                    "provide observed temporal holdout examples and reduce scaffold/review-only dependence",
                ],
            )
            return report.to_dict()

        learned_parameters = self._fit_baseline_dynamics_parameters(dataset)
        predictions = self._predict_with_baseline_dynamics(dataset, learned_parameters)
        evaluation_payload = {
            "dataset": dataset,
            "predictions": predictions,
            "candidate": candidate,
            "thresholds": payload.get("thresholds") or {},
            "evaluation_thresholds": payload.get("evaluation_thresholds") or {},
            "geofm_gate_report": payload.get("geofm_gate_report") or {},
            "causal_calibration_report": payload.get("causal_calibration_report") or {},
        }
        evaluation = self.dynamics_evaluation_report(state_version_id, evaluation_payload)
        evidence_gate = {
            "passed": evaluation.get("status") == "pass",
            "blocked": evaluation.get("status") == "blocked",
            "status": evaluation.get("status", "review"),
            "missing": list((evaluation.get("evidence_gate") or {}).get("missing") or []),
        }
        report = TwmDynamicsFitReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            status=evidence_gate["status"],
            candidate=candidate,
            readiness=readiness,
            learned_parameters=learned_parameters,
            predictions=predictions,
            evaluation=evaluation,
            evidence_gate=evidence_gate,
            recommendations=self._fit_dynamics_recommendations(evidence_gate, learned_parameters),
        )
        return report.to_dict()

    def geofm_ablation_gate(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None:
            raise LookupError(f"state not found: {state_version_id}")
        cache_key = self._report_cache_key(
            state_version_id,
            payload,
            include=(
                "dataset",
                "dynamics_training_dataset",
                "scenario",
                "evidence_coverage",
                "thresholds",
                "baseline_metrics",
                "augmented_metrics",
                "geofm_metrics",
                "baseline_predictions",
                "b0_predictions",
                "baseline_dynamics_predictions",
                "augmented_predictions",
                "geofm_predictions",
                "b1_predictions",
                "augmented_dynamics_predictions",
                "baseline_dynamics_candidate_report",
                "b0_candidate_report",
                "augmented_dynamics_candidate_report",
                "geofm_candidate_report",
                "b1_candidate_report",
                "geofm_dynamics_evaluation_report",
                "augmented_dynamics_evaluation_report",
                "dynamics_evaluation_report",
                "extended_validation",
                "architecture_audit",
                "geofm_architecture_audit",
                "adapter",
                "geofm_adapter",
                "backbone",
                "geofm_backbone",
                "data_validation",
                "geofm_data_validation",
                "geofm_backbone_name",
                "geofm_architecture",
                "fused_qkv",
                "geofm_adapter_type",
                "geofm_adapter_target_modules",
                "geofm_input_modalities",
                "adapter_capacity_score",
                "trainable_parameter_ratio",
                "domain_shift_score",
                "label_quality",
                "geographic_split",
                "temporal_holdout",
                "production_labels",
                "action_type",
                "target_role",
                "magnitude",
                "parameters",
                "scenario_context",
            ),
        )
        cached = self._cache_get(self._geofm_gate_cache, cache_key)
        if cached is not None:
            return cached
        state_bundle = self.repository.get_state_bundle(state_version_id)
        if state_bundle is None:
            raise LookupError(f"state not found: {state_version_id}")

        thresholds = self._geofm_gate_thresholds(payload)
        vector_inventory = self._geofm_vector_inventory(state)
        scenario = str(payload.get("scenario") or "geofm_b0_b1_gate").strip() or "geofm_b0_b1_gate"
        evidence_coverage = payload.get("evidence_coverage")
        if evidence_coverage is None:
            evidence_coverage = (state.quality_summary or {}).get("evidence_coverage")

        baseline_metrics = self._variant_metrics_from_payload(payload.get("baseline_metrics"))
        augmented_metrics = self._variant_metrics_from_payload(payload.get("augmented_metrics") or payload.get("geofm_metrics"))
        if not baseline_metrics or not augmented_metrics:
            inferred = self._infer_geofm_gate_metrics(
                state=state,
                state_bundle=state_bundle,
                scenario=scenario,
                evidence_coverage=evidence_coverage,
                vector_inventory=vector_inventory,
                payload=payload,
            )
            baseline_metrics = baseline_metrics or inferred["baseline_metrics"]
            augmented_metrics = augmented_metrics or inferred["augmented_metrics"]

        baseline_gate = self._variant_evidence_gate(
            uses_geofm=False,
            metrics=baseline_metrics,
            vector_inventory=vector_inventory,
            evidence_coverage=evidence_coverage,
            thresholds=thresholds,
        )
        augmented_gate = self._variant_evidence_gate(
            uses_geofm=True,
            metrics=augmented_metrics,
            vector_inventory=vector_inventory,
            evidence_coverage=evidence_coverage,
            thresholds=thresholds,
        )
        deltas = self._geofm_metric_deltas(baseline_metrics, augmented_metrics)
        extended_validation = self._geofm_extended_validation(payload=payload, thresholds=thresholds, deltas=deltas)
        architecture_audit = self._geofm_architecture_audit(
            payload=payload,
            vector_inventory=vector_inventory,
            thresholds=thresholds,
        )
        gate_status, decision, recommendations = self._geofm_gate_decision(
            deltas=deltas,
            baseline_gate=baseline_gate,
            augmented_gate=augmented_gate,
            thresholds=thresholds,
            vector_inventory=vector_inventory,
            explicit_metrics=bool(payload.get("baseline_metrics") and (payload.get("augmented_metrics") or payload.get("geofm_metrics"))),
            extended_validation=extended_validation,
            architecture_audit=architecture_audit,
        )

        report = TwmGeoFMGateReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            gate_status=gate_status,
            decision=decision,
            baseline=TwmGeoFMGateVariant(
                variant_id="B0",
                label="GIS-only hierarchical state",
                uses_geofm=False,
                metrics=baseline_metrics,
                evidence_gate=baseline_gate,
                provenance={
                    "state_version_id": state_version_id,
                    "source": "payload_or_deterministic_twm",
                    "geofm_used": False,
                },
            ),
            augmented=TwmGeoFMGateVariant(
                variant_id="B1",
                label="GIS state plus gated GeoFM embedding",
                uses_geofm=True,
                metrics=augmented_metrics,
                evidence_gate=augmented_gate,
                provenance={
                    "state_version_id": state_version_id,
                    "source": "payload_or_deterministic_twm",
                    "geofm_used": True,
                    "vector_inventory": vector_inventory,
                    "architecture_audit_status": architecture_audit.get("status"),
                },
            ),
            deltas=deltas,
            thresholds=thresholds,
            evidence={
                "vector_inventory": vector_inventory,
                "architecture_audit": architecture_audit,
                "evidence_coverage": evidence_coverage,
                "rule_hit_count": len(self.repository.list_rule_hits(state_version_id=state_version_id)),
                "extended_validation": extended_validation,
                "note": "GeoFM is retained only when downstream planning lift and evidence gates pass.",
            },
            recommendations=recommendations,
        )
        result = report.to_dict()
        self._cache_set(self._geofm_gate_cache, cache_key, result)
        return deepcopy(result)

    def geofm_downstream_experiment_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state_bundle = self.repository.get_state_bundle(state_version_id)
        state = self.repository.get_state_version(state_version_id)
        if state_bundle is None or state is None:
            raise LookupError(f"state not found: {state_version_id}")

        thresholds = self._geofm_gate_thresholds(payload)
        vector_inventory = self._geofm_vector_inventory(state)
        scenario = str(payload.get("scenario") or "geofm_downstream_experiment").strip() or "geofm_downstream_experiment"
        evidence_coverage = payload.get("evidence_coverage")
        if evidence_coverage is None:
            evidence_coverage = (state.quality_summary or {}).get("evidence_coverage")

        payload, prediction_evidence = self._geofm_payload_with_experiment_predictions(payload)
        baseline_metrics = self._variant_metrics_from_payload(payload.get("baseline_metrics"))
        augmented_metrics = self._variant_metrics_from_payload(payload.get("augmented_metrics") or payload.get("geofm_metrics"))
        prediction_metrics = self._geofm_variant_metrics_from_prediction_maps(payload)
        baseline_metrics = baseline_metrics or prediction_metrics.get("baseline_metrics", {})
        augmented_metrics = augmented_metrics or prediction_metrics.get("augmented_metrics", {})
        if not baseline_metrics or not augmented_metrics:
            inferred = self._infer_geofm_gate_metrics(
                state=state,
                state_bundle=state_bundle,
                scenario=scenario,
                evidence_coverage=evidence_coverage,
                vector_inventory=vector_inventory,
                payload=payload,
            )
            baseline_metrics = baseline_metrics or inferred["baseline_metrics"]
            augmented_metrics = augmented_metrics or inferred["augmented_metrics"]
        deltas = self._geofm_metric_deltas(baseline_metrics, augmented_metrics)
        extended_validation = self._geofm_extended_validation(payload=payload, thresholds=thresholds, deltas=deltas)
        gate_payload = {
            **payload,
            "scenario": scenario,
            "evidence_coverage": evidence_coverage,
            "baseline_metrics": baseline_metrics,
            "augmented_metrics": augmented_metrics,
            "extended_validation": self._geofm_extended_validation_payload_for_gate(extended_validation),
            "thresholds": {
                **dict(payload.get("thresholds") or {}),
                "require_extended_validation": True,
            },
        }
        gate_report = self.geofm_ablation_gate(state_version_id, gate_payload)
        rows = self._geofm_experiment_comparison_rows(payload)
        architecture_audit = dict(((gate_report.get("evidence") or {}).get("architecture_audit") or {}))
        evidence = {
            "extended_validation": extended_validation,
            "architecture_audit": architecture_audit,
            "comparison_summary": self._geofm_experiment_comparison_summary(rows),
            "prediction_evidence": prediction_evidence,
            "vector_inventory": vector_inventory,
            "evidence_coverage": evidence_coverage,
            "claim_boundary": "geofm_candidate_evidence_not_core_twm",
        }
        recommendations = self._geofm_experiment_recommendations(gate_report, extended_validation, rows, prediction_evidence)
        report = TwmGeoFMDownstreamExperimentReport(
            state_version_id=state_version_id,
            project_id=state.project_id,
            status=self._geofm_experiment_status(gate_report, prediction_evidence),
            experiment={
                "scenario": scenario,
                "experiment_id": str(payload.get("experiment_id") or f"{state_version_id}:{scenario}"),
                "comparison": "B0 GIS-only hierarchical state vs B1 GIS plus gated GeoFM embedding",
                "renderer_simulator_planner_boundary": {
                    "renderer": "hierarchical GIS object/relation/rule/evidence state is rendered as structured TWM state, not imagery",
                    "simulator": "action-conditioned dynamics are evaluated through downstream holdout prediction comparisons",
                    "planner": "beam/MPC/ArcGIS planners consume retained signals but are not the TWM core",
                },
            },
            variants={
                "baseline": {
                    "variant_id": "B0",
                    "label": "GIS-only hierarchical state",
                    "uses_geofm": False,
                    "metrics": baseline_metrics,
                },
                "augmented": {
                    "variant_id": "B1",
                    "label": "GIS state plus gated GeoFM embedding",
                    "uses_geofm": True,
                    "metrics": augmented_metrics,
                    "vector_inventory": vector_inventory,
                },
                "deltas": deltas,
            },
            evidence=evidence,
            gate_report=gate_report,
            recommendations=recommendations,
        )
        return report.to_dict()

    def causal_calibration_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None:
            raise LookupError(f"state not found: {state_version_id}")
        cache_key = self._report_cache_key(
            state_version_id,
            payload,
            include=(
                "records",
                "observations",
                "observed_history",
                "observed_history_path",
                "approval_review_history_path",
                "approval_history_path",
                "observed_approval_history_path",
                "thresholds",
                "causal_thresholds",
                "model_effect",
                "baseline_action",
                "intervention_actions",
                "action_type",
                "target_role",
                "magnitude",
                "parameters",
                "scenario",
                "scenario_context",
                "evidence_coverage",
                "horizon",
                "treatment",
                "treatment_name",
                "outcome",
                "outcome_name",
                "positive_label",
                "outcome_direction",
                "scca_causal_evidence_report",
                "scca_evidence_report",
                "scca_result",
                "scca_report",
                "scca_payload",
                "scca_output_dir",
                "scca_dir",
                "scca_path",
                "scca_manifest_path",
            ),
        )
        cached = self._cache_get(self._causal_calibration_cache, cache_key)
        if cached is not None:
            return cached
        if self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")

        treatment_name = str(payload.get("treatment") or payload.get("treatment_name") or "planning_intervention")
        outcome_name = str(payload.get("outcome") or payload.get("outcome_name") or "planning_utility_delta")
        records, record_source = self._causal_records_for_calibration(state_version_id, payload)
        thresholds = self._causal_calibration_thresholds(payload)
        with trace_twm_operation(
            "estimate_observational_treatment_effect",
            state_version_id=state_version_id,
            backend="observational_causal_calibration",
            sample_count=len(records),
            gate_status="pending",
        ) as trace_ctx:
            estimate = self._estimate_observational_treatment_effect(records, thresholds=thresholds)
            model_effect = safe_float(payload.get("model_effect"), None)
            if model_effect is None:
                model_effect = self._model_effect_from_rollout(state_version_id, payload)
            calibration = self._causal_calibration_from_estimate(estimate, model_effect)
            scca_report = self._payload_scca_causal_evidence_report(payload)
            evidence_gate = self._causal_evidence_gate(
                records=records,
                estimate=estimate,
                calibration=calibration,
                thresholds=thresholds,
                record_source=record_source,
                scca_report=scca_report,
            )
            recommendations = self._causal_calibration_recommendations(evidence_gate, estimate, calibration, record_source)
            if scca_report:
                recommendations.extend(self._scca_causal_evidence_recommendations(scca_report))
            status = "pass" if evidence_gate.get("status") == "pass" else "review"
            if evidence_gate.get("blocked"):
                status = "blocked"

            report = TwmCausalCalibrationReport(
                state_version_id=state_version_id,
                project_id=state.project_id,
                status=status,
                identification_strength="observational",
                identification_note=(
                    "local TWM calibration estimates observational treatment effects from "
                    "approved/reviewed histories; it is not randomized or do-intervention identification"
                ),
                treatment={
                    "name": treatment_name,
                    "positive_label": payload.get("positive_label", 1),
                    "assignment": "observational",
                },
                outcome={
                    "name": outcome_name,
                    "direction": str(payload.get("outcome_direction") or "higher_better"),
                },
                estimate=estimate,
                calibration=calibration,
                evidence_gate=evidence_gate,
                provenance={
                    "state_version_id": state_version_id,
                    "record_source": record_source,
                    "record_count": len(records),
                    "rule_hit_count": len(self.repository.list_rule_hits(state_version_id=state_version_id)),
                    "record_inventory": self._causal_record_inventory(records),
                    "scca_causal_evidence_report": scca_report or None,
                    "method_note": "primary estimator comes from the local causal calibration backend and remains observational rather than randomized identification",
                },
                recommendations=recommendations,
            )
            result = report.to_dict()
            _set_trace_attribute(trace_ctx, "twm.gate_status", result.get("evidence_gate", {}).get("status", result.get("status", "review")))
            self._cache_set(self._causal_calibration_cache, cache_key, result)
            return deepcopy(result)

    def scca_causal_evidence_report(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None:
            raise LookupError(f"state not found: {state_version_id}")

        scca_payload = self._load_scca_payload(payload)
        thresholds = self._scca_causal_evidence_thresholds(payload)
        effect = self._scca_primary_effect(scca_payload)
        balance = self._scca_balance_summary(scca_payload)
        spatial = self._scca_spatial_summary(scca_payload)
        gate = self._scca_causal_evidence_gate(
            scca_payload=scca_payload,
            effect=effect,
            balance=balance,
            spatial=spatial,
            thresholds=thresholds,
        )
        status = str(gate.get("status") or "review")
        report = {
            "schema": "territory_world_model.scca_causal_evidence_report.v1",
            "state_version_id": state_version_id,
            "project_id": state.project_id,
            "status": status,
            "algorithm": "SCCA",
            "role": "external_spatial_causal_evidence",
            "boundary": {
                "replaces_twm_simulator": False,
                "replaces_twm_planner": False,
                "usable_as": [
                    "causal_calibration_support",
                    "spatial_interference_diagnostic",
                    "evidence_grade_signal",
                ],
                "claim_boundary": "SCCA evidence can support causal calibration but does not by itself prove TWM production accuracy.",
            },
            "study": {
                "case_id": scca_payload.get("case_id") or scca_payload.get("case_name"),
                "case_label": scca_payload.get("case_label") or scca_payload.get("label"),
                "exposure": scca_payload.get("exposure"),
                "outcome": scca_payload.get("outcome"),
                "row_count": safe_int(scca_payload.get("row_count"), None),
                "column_count": safe_int(scca_payload.get("column_count"), None),
                "confounder_count": len(scca_payload.get("confounders") or []),
                "context_columns": list(scca_payload.get("context_columns") or []),
            },
            "effect": effect,
            "balance": balance,
            "spatial_diagnostics": spatial,
            "credibility": {
                "decision": scca_payload.get("credibility_decision") or (scca_payload.get("credibility") or {}).get("decision"),
                "evidence_grade": scca_payload.get("evidence_grade") or (scca_payload.get("credibility") or {}).get("evidence_grade"),
                "reasons": list(scca_payload.get("evidence_grade_reasons") or (scca_payload.get("credibility") or {}).get("reasons") or []),
                "robustness_interpretation": scca_payload.get("robustness_interpretation"),
            },
            "evidence_gate": gate,
            "calibration_hint": self._scca_calibration_hint(effect, gate),
            "provenance": {
                "state_version_id": state_version_id,
                "source": scca_payload.get("_source") or "payload",
                "output_dir": scca_payload.get("output_dir"),
                "files": dict(scca_payload.get("files") or {}),
                "loaded_from_path": scca_payload.get("_loaded_from_path"),
            },
            "recommendations": self._scca_causal_evidence_recommendations({"evidence_gate": gate, "effect": effect}),
        }
        return jsonable(report)

    def _load_scca_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = payload.get("scca_result") or payload.get("scca_report") or payload.get("scca_payload")
        if isinstance(raw, dict):
            result = dict(raw)
            result.setdefault("_source", "payload")
            return result

        path_value = (
            payload.get("scca_output_dir")
            or payload.get("scca_dir")
            or payload.get("output_dir")
            or payload.get("scca_manifest_path")
            or payload.get("manifest_path")
        )
        if not path_value:
            return {"_source": "empty_payload"}
        path = Path(str(path_value)).expanduser()
        output_dir = path.parent if path.is_file() else path
        if not output_dir.exists():
            raise FileNotFoundError(f"SCCA output path not found: {output_dir}")

        manifest = {}
        for candidate in (path if path.is_file() else output_dir / "manifest.json", output_dir / "analysis_manifest.json"):
            if candidate.exists():
                try:
                    manifest = read_json(candidate)
                    manifest["_loaded_from_path"] = str(candidate)
                    break
                except Exception:
                    manifest = {}

        result = dict(manifest)
        result.setdefault("_source", "scca_output_dir")
        result["output_dir"] = str(output_dir)
        result.setdefault("effect_estimates", read_csv(output_dir / "effect_estimates.csv") if (output_dir / "effect_estimates.csv").exists() else [])
        result.setdefault("balance_summary", read_csv(output_dir / "balance_summary.csv") if (output_dir / "balance_summary.csv").exists() else [])
        for key, filename in (
            ("credibility_report", "credibility_report.json"),
            ("spatial_diagnostics", "spatial_diagnostics.json"),
            ("data_profile", "data_profile.json"),
            ("robustness", "robustness_manifest.json"),
        ):
            target = output_dir / filename
            if target.exists() and key not in result:
                try:
                    result[key] = read_json(target)
                except Exception:
                    result[key] = {}
        credibility = dict(result.get("credibility_report") or {})
        for source_key, target_key in (
            ("decision", "credibility_decision"),
            ("evidence_grade", "evidence_grade"),
            ("evidence_grade_reasons", "evidence_grade_reasons"),
        ):
            if target_key not in result and source_key in credibility:
                result[target_key] = credibility.get(source_key)
        return result

    def _scca_causal_evidence_thresholds(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = dict(payload.get("thresholds") or payload.get("scca_thresholds") or {})
        return {
            "min_row_count": int(raw.get("min_row_count", 30)),
            "max_p_value": float(raw.get("max_p_value", 0.1)),
            "max_balance_smd": float(raw.get("max_balance_smd", 0.35)),
            "max_residual_moran_abs": float(raw.get("max_residual_moran_abs", 0.35)),
            "accepted_credibility": set(raw.get("accepted_credibility") or ["strong_support", "moderate_support"]),
            "accepted_evidence_grades": set(raw.get("accepted_evidence_grades") or ["core_support", "bounded_support"]),
            "require_spatial_diagnostics": bool(raw.get("require_spatial_diagnostics", True)),
        }

    def _scca_primary_effect(self, scca_payload: dict[str, Any]) -> dict[str, Any]:
        rows = scca_payload.get("effect_estimates")
        if not isinstance(rows, list):
            rows = []
        preferred = (
            "spatial_slx_model",
            "spatial_lag_adjusted_ols",
            "spatial_neighbor_adjusted_ols",
            "baseline_adjusted_ols",
        )
        selected: dict[str, Any] = {}
        for name in preferred:
            for row in rows:
                if isinstance(row, dict) and str(row.get("estimator") or row.get("model") or "") == name:
                    selected = dict(row)
                    break
            if selected:
                break
        if not selected and rows:
            selected = dict(next((row for row in rows if isinstance(row, dict)), {}) or {})

        summary = dict(scca_payload.get("result_summary") or {})
        if not selected:
            for key in preferred:
                candidate = summary.get(key)
                if isinstance(candidate, dict):
                    selected = dict(candidate)
                    selected.setdefault("estimator", key)
                    break

        coef = safe_float(
            selected.get("coef"),
            safe_float(selected.get("total_effect"), safe_float(selected.get("direct_effect"), None)),
        )
        p_value = safe_float(
            selected.get("p_value"),
            safe_float(selected.get("total_p_value"), safe_float(selected.get("direct_p_value"), None)),
        )
        return {
            "estimator": selected.get("estimator") or selected.get("model") or "not_available",
            "status": selected.get("status") or ("available" if coef is not None else "missing"),
            "coef": round(float(coef), 6) if coef is not None else None,
            "p_value": round(float(p_value), 6) if p_value is not None else None,
            "ci_lower": safe_float(selected.get("ci_lower"), safe_float(selected.get("total_ci_lower"), None)),
            "ci_upper": safe_float(selected.get("ci_upper"), safe_float(selected.get("total_ci_upper"), None)),
            "neighbor_exposure_coef": safe_float(selected.get("neighbor_exposure_coef"), None),
            "sign_stable": selected.get("sign_stable"),
            "raw": selected,
        }

    def _scca_balance_summary(self, scca_payload: dict[str, Any]) -> dict[str, Any]:
        rows = scca_payload.get("balance_summary")
        if not isinstance(rows, list):
            rows = []
        smd_values = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in ("standardized_mean_difference", "abs_smd", "smd", "max_abs_standardized_mean_difference"):
                value = safe_float(row.get(key), None)
                if value is not None:
                    smd_values.append(abs(float(value)))
                    break
        max_abs_smd = max(smd_values) if smd_values else None
        return {
            "covariate_count": len(rows),
            "max_abs_standardized_mean_difference": round(max_abs_smd, 6) if max_abs_smd is not None else None,
            "status": "available" if rows else "missing",
        }

    def _scca_spatial_summary(self, scca_payload: dict[str, Any]) -> dict[str, Any]:
        spatial = dict(scca_payload.get("spatial_diagnostics") or {})
        result_summary = dict(scca_payload.get("result_summary") or {})
        if not spatial:
            spatial = dict(result_summary.get("spatial_diagnostics") or {})
        residual = dict(spatial.get("residual_moran") or {})
        exposure = dict(spatial.get("exposure_moran") or {})
        graph = dict(spatial.get("graph") or {})
        residual_i = safe_float(
            residual.get("moran_i"),
            safe_float(spatial.get("residual_moran_i"), None),
        )
        exposure_i = safe_float(
            exposure.get("moran_i"),
            safe_float(spatial.get("exposure_moran_i"), None),
        )
        return {
            "status": "available" if spatial else "missing",
            "graph_method": graph.get("method") or spatial.get("graph_method"),
            "edge_count": safe_int(graph.get("edge_count"), safe_int(spatial.get("edge_count"), 0)),
            "residual_moran_i": round(float(residual_i), 6) if residual_i is not None else None,
            "residual_moran_p_value": safe_float(
                residual.get("permutation_p_value"),
                safe_float(spatial.get("residual_moran_p_value"), None),
            ),
            "exposure_moran_i": round(float(exposure_i), 6) if exposure_i is not None else None,
            "exposure_moran_p_value": safe_float(
                exposure.get("permutation_p_value"),
                safe_float(spatial.get("exposure_moran_p_value"), None),
            ),
            "interpretation": spatial.get("interpretation"),
        }

    def _scca_causal_evidence_gate(
        self,
        *,
        scca_payload: dict[str, Any],
        effect: dict[str, Any],
        balance: dict[str, Any],
        spatial: dict[str, Any],
        thresholds: dict[str, Any],
    ) -> dict[str, Any]:
        missing: list[str] = []
        row_count = safe_int(scca_payload.get("row_count"), 0)
        if row_count < int(thresholds["min_row_count"]):
            missing.append("min_row_count")
        if effect.get("coef") is None:
            missing.append("effect_estimate")
        p_value = safe_float(effect.get("p_value"), None)
        if p_value is not None and p_value > float(thresholds["max_p_value"]):
            missing.append("effect_significance")
        max_smd = safe_float(balance.get("max_abs_standardized_mean_difference"), None)
        if max_smd is not None and max_smd > float(thresholds["max_balance_smd"]):
            missing.append("covariate_balance")
        if thresholds.get("require_spatial_diagnostics") and spatial.get("status") == "missing":
            missing.append("spatial_diagnostics")
        residual_moran = safe_float(spatial.get("residual_moran_i"), None)
        if residual_moran is not None and abs(float(residual_moran)) > float(thresholds["max_residual_moran_abs"]):
            missing.append("residual_spatial_autocorrelation")
        credibility = str(scca_payload.get("credibility_decision") or (scca_payload.get("credibility") or {}).get("decision") or "")
        evidence_grade = str(scca_payload.get("evidence_grade") or (scca_payload.get("credibility") or {}).get("evidence_grade") or "")
        if credibility and credibility not in thresholds["accepted_credibility"]:
            missing.append("credibility_decision")
        if evidence_grade and evidence_grade not in thresholds["accepted_evidence_grades"]:
            missing.append("evidence_grade")
        passed = not missing
        return {
            "passed": passed,
            "status": "pass" if passed else "review",
            "blocked": False,
            "missing": missing,
            "thresholds": {
                **thresholds,
                "accepted_credibility": sorted(thresholds["accepted_credibility"]),
                "accepted_evidence_grades": sorted(thresholds["accepted_evidence_grades"]),
            },
            "row_count": row_count,
            "credibility_decision": credibility or None,
            "evidence_grade": evidence_grade or None,
        }

    def _scca_calibration_hint(self, effect: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
        coef = safe_float(effect.get("coef"), None)
        return {
            "status": "pass" if gate.get("status") == "pass" and coef is not None else "review",
            "observed_effect": round(float(coef), 6) if coef is not None else None,
            "effect_source": effect.get("estimator"),
            "can_support_twm_causal_calibration": bool(gate.get("status") == "pass" and coef is not None),
        }

    def _payload_scca_causal_evidence_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = payload.get("scca_causal_evidence_report") or payload.get("scca_evidence_report")
        if isinstance(raw, dict):
            return dict(raw)
        return {}

    def _payload_or_build_scca_causal_evidence_report(self, state_version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        report = self._payload_scca_causal_evidence_report(payload)
        if report:
            return report
        has_scca_payload = any(
            key in payload
            for key in (
                "scca_result",
                "scca_report",
                "scca_payload",
                "scca_output_dir",
                "scca_dir",
                "scca_path",
                "scca_manifest_path",
            )
        )
        if not has_scca_payload:
            return {}
        return self.scca_causal_evidence_report(state_version_id, payload)

    def _scca_causal_evidence_recommendations(self, scca_report: dict[str, Any]) -> list[str]:
        gate = dict(scca_report.get("evidence_gate") or {})
        effect = dict(scca_report.get("effect") or {})
        recommendations: list[str] = []
        if gate.get("status") != "pass":
            recommendations.append("keep SCCA evidence as review-only until row count, effect, balance, spatial diagnostics and credibility gates pass")
        if "min_row_count" in (gate.get("missing") or []):
            recommendations.append("increase SCCA sample size before using it to support TWM causal claims")
        if "effect_estimate" in (gate.get("missing") or []):
            recommendations.append("provide SCCA effect_estimates.csv or result_summary with an estimable spatial causal coefficient")
        if "spatial_diagnostics" in (gate.get("missing") or []):
            recommendations.append("provide SCCA spatial_diagnostics.json before upgrading spatial causal evidence")
        if gate.get("status") == "pass" and effect.get("coef") is not None:
            recommendations.append("use SCCA as external spatial causal support, not as a replacement for TWM simulator validation")
        return recommendations

    def _scenario_context_with_causal_calibration(
        self,
        state_version_id: str,
        payload: dict[str, Any],
        scenario_context: dict[str, Any],
    ) -> dict[str, Any]:
        if "causal_calibration" in scenario_context or "causal_calibration_report" in scenario_context:
            return scenario_context
        explicit_report = payload.get("causal_calibration_report")
        if isinstance(explicit_report, dict):
            scenario_context["causal_calibration"] = explicit_report
            return scenario_context
        calibration_payload = payload.get("causal_calibration")
        if not isinstance(calibration_payload, dict):
            return scenario_context
        nested_payload = dict(calibration_payload)
        nested_payload.setdefault("scenario", payload.get("scenario"))
        nested_payload.setdefault("evidence_coverage", payload.get("evidence_coverage"))
        nested_payload.pop("causal_calibration", None)
        nested_payload.pop("causal_calibration_report", None)
        report = self.causal_calibration_report(state_version_id, nested_payload)
        scenario_context["causal_calibration"] = report
        return scenario_context

    def _validation_claim_ladder(
        self,
        *,
        state: TwmStateVersion,
        payload: dict[str, Any],
        forecast: dict[str, Any],
        rollout: dict[str, Any],
        audit: dict[str, Any],
        review_tasks: list[Any],
        stages: list[TwmValidationStage],
    ) -> dict[str, Any]:
        stage_status = {stage.stage_code: stage.status for stage in stages}
        forecast_gate = dict(((forecast.get("forecast") or {}).get("evidence_gate")) or {})
        rollout_gate = dict(rollout.get("evidence_gate") or {})
        calibration_summary = dict(rollout.get("calibration_summary") or {})
        explicit_facts = dict(payload.get("claim_gate_facts") or {}) if isinstance(payload.get("claim_gate_facts"), dict) else {}
        geofm_report = payload.get("geofm_gate_report")
        geofm_used = bool(payload.get("uses_geofm") or payload.get("geofm_required") or isinstance(geofm_report, dict))
        geofm_status = "not_applicable"
        if geofm_used:
            geofm_status = "pass" if isinstance(geofm_report, dict) and (geofm_report.get("gate_status") or geofm_report.get("status")) == "pass" else "review"

        causal_report = self._payload_causal_report(payload)
        causal_used = bool(payload.get("treatment") or payload.get("causal_calibration") or causal_report)
        scca_report = self._payload_scca_causal_evidence_report(payload)
        require_scca = truthy(payload.get("require_scca_pass") or payload.get("require_scca_causal_evidence"))
        scca_gate = dict(scca_report.get("evidence_gate") or {})
        scca_status = str(scca_gate.get("status") or scca_report.get("status") or "not_provided")
        spatial_status = "not_applicable"
        if scca_report:
            spatial_status = "pass" if scca_status == "pass" else "review"
        elif require_scca:
            spatial_status = "review"
        elif causal_used:
            spatial_report = dict((causal_report.get("estimate") or {}).get("spatial_estimator") or {}) if causal_report else {}
            spatial_gate = dict((spatial_report.get("evidence_gate") or spatial_report.get("gate") or {}))
            if spatial_gate:
                spatial_status = "pass" if spatial_gate.get("status") == "pass" or spatial_gate.get("passed") else "review"
            else:
                spatial_status = "review"

        incomplete_reviews = [
            getattr(task, "id", "")
            for task in review_tasks
            if getattr(task, "status", "") not in {"approved", "closed", "resolved", "confirmed", "dismissed"}
        ]
        facts: dict[str, Any] = {
            "state_build_pass": {
                "status": stage_status.get("state_build", "review"),
                "state_version_id": state.id,
                "build_status": state.build_status,
            },
            "future_state_holdout_pass": {
                "status": "review",
                "stage_status": stage_status.get("future_state_prediction", "review"),
                "forecast_gate_status": forecast_gate.get("status", "review"),
                "reason": "explicit holdout or observed temporal-validation evidence is required before L1 promotion",
            },
            "counterfactual_calibration_pass": {
                "status": "pass" if stage_status.get("counterfactual_rollout") == "pass" and rollout_gate.get("status") == "pass" and not calibration_summary.get("calibration_required") else "review",
                "stage_status": stage_status.get("counterfactual_rollout", "review"),
                "rollout_gate_status": rollout_gate.get("status", "review"),
                "calibration_required": bool(calibration_summary.get("calibration_required")),
            },
            "spatial_estimator_pass_or_not_applicable": {
                "status": spatial_status,
                "causal_claim_requested": causal_used,
                "scca_required": require_scca,
                "scca_provided": bool(scca_report),
                "scca_status": scca_status,
                "scca_missing": list(scca_gate.get("missing") or []) if scca_gate else (["scca_causal_evidence_report"] if require_scca and not scca_report else []),
            },
            "planning_lift_pass": {
                "status": stage_status.get("planning_lift", "review"),
            },
            "geofm_gate_decision": {
                "status": geofm_status,
                "geofm_used": geofm_used,
                "decision": (geofm_report or {}).get("decision") if isinstance(geofm_report, dict) else "not_used",
            },
            "gis_audit_pass": {
                "status": "pass" if stage_status.get("gis_deployability") == "pass" and audit.get("evidence_gate_passed") else "review",
                "stage_status": stage_status.get("gis_deployability", "review"),
                "evidence_gate_passed": bool(audit.get("evidence_gate_passed")),
            },
            "human_review_completed": {
                "status": "pass" if not incomplete_reviews else "review",
                "incomplete_review_task_count": len(incomplete_reviews),
            },
        }
        facts.update(explicit_facts)
        if require_scca and scca_status != "pass":
            facts["spatial_estimator_pass_or_not_applicable"] = {
                "status": "review",
                "causal_claim_requested": causal_used,
                "scca_required": True,
                "scca_provided": bool(scca_report),
                "scca_status": scca_status,
                "scca_missing": list(scca_gate.get("missing") or []) if scca_gate else ["scca_causal_evidence_report"],
                "reason": "require_scca_pass prevents spatial causal gate promotion without passing SCCA evidence",
            }
        return evaluate_claim_ladder(facts)

    def _payload_causal_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        explicit = payload.get("causal_calibration_report")
        if isinstance(explicit, dict):
            return explicit
        context = payload.get("scenario_context")
        if isinstance(context, dict):
            nested = context.get("causal_calibration") or context.get("causal_calibration_report")
            if isinstance(nested, dict):
                return nested
        nested_payload = payload.get("causal_calibration")
        if isinstance(nested_payload, dict):
            nested_report = nested_payload.get("report") or nested_payload.get("causal_calibration_report")
            if isinstance(nested_report, dict):
                return nested_report
        return {}

    def _validation_state_stage(self, state: TwmStateVersion, state_bundle: dict[str, Any]) -> TwmValidationStage:
        object_count = int(state.object_count or len(state_bundle.get("objects") or []))
        relation_count = int(state.relation_count or len(state_bundle.get("relations") or []))
        quality_summary = dict(state.quality_summary or {})
        gaps: list[str] = []
        if object_count <= 0:
            gaps.append("state has no objects")
        if relation_count <= 0:
            gaps.append("state has no relations")
        if state.build_status != "ready":
            gaps.append(f"state build_status is {state.build_status}")
        if quality_summary.get("not_for_production_object_count"):
            gaps.append("state contains not_for_production objects")
        status = "pass" if not gaps else "review"
        return TwmValidationStage(
            stage_code="state_build",
            stage_name="State Build Integrity",
            status=status,
            claim="Layer inputs have been converted into a computable hierarchical object-relation state.",
            evidence={
                "object_count": object_count,
                "relation_count": relation_count,
                "build_status": state.build_status,
                "quality_summary": quality_summary,
            },
            gaps=gaps,
            next_actions=[] if status == "pass" else ["repair state source bindings or semantic bundle quality flags"],
        )

    def _validation_future_stage(self, forecast_payload: dict[str, Any]) -> TwmValidationStage:
        forecast = forecast_payload.get("forecast") or {}
        latent = forecast.get("future_latent_state") or {}
        projected = latent.get("projected") or {}
        uncertainty = forecast.get("uncertainty") or {}
        gaps: list[str] = []
        if not latent:
            gaps.append("future_latent_state head is missing")
        if not projected.get("object_counts_by_role"):
            gaps.append("projected object counts are missing")
        if float(uncertainty.get("confidence") or 0.0) < 0.35:
            gaps.append("forecast confidence is below evidence gate threshold")
        status = "pass" if not gaps else "review"
        return TwmValidationStage(
            stage_code="future_state_prediction",
            stage_name="Future State Prediction",
            status=status,
            claim="TWM produced an action-conditioned future latent state head.",
            evidence={
                "future_latent_schema": latent.get("schema"),
                "projected": projected,
                "uncertainty": uncertainty,
            },
            gaps=gaps,
            next_actions=[] if status == "pass" else ["collect temporal holdout labels and calibrate future-state prediction"],
        )

    def _validation_constraint_stage(self, hits: list[TwmRuleHit], forecast_payload: dict[str, Any]) -> TwmValidationStage:
        forecast = forecast_payload.get("forecast") or {}
        probability = float(forecast.get("constraint_violation_probability") or 0.0)
        severity_distribution: dict[str, int] = {}
        for hit in hits:
            severity_distribution[hit.severity] = severity_distribution.get(hit.severity, 0) + 1
        gaps: list[str] = []
        if not hits:
            gaps.append("no rule evaluation hits are available for constraint validation")
        if probability >= 0.8:
            gaps.append("constraint violation probability is high")
        if severity_distribution.get("blocking") or severity_distribution.get("critical"):
            gaps.append("blocking or critical rule hits remain open")
        status = "pass" if not gaps else "review"
        return TwmValidationStage(
            stage_code="constraint_prediction",
            stage_name="Constraint Prediction",
            status=status,
            claim="TWM generated a constraint-risk head tied to current rule evaluation evidence.",
            evidence={
                "rule_hit_count": len(hits),
                "severity_distribution": severity_distribution,
                "constraint_violation_probability": probability,
            },
            gaps=gaps,
            next_actions=[] if status == "pass" else ["resolve high-severity rule hits or recalibrate constraint head"],
        )

    def _validation_counterfactual_stage(self, rollout: dict[str, Any]) -> TwmValidationStage:
        evidence_gate = dict(rollout.get("evidence_gate") or {})
        calibration_summary = dict(rollout.get("calibration_summary") or {})
        gaps: list[str] = []
        if not rollout.get("baseline_steps") or not rollout.get("intervention_steps"):
            gaps.append("baseline or intervention rollout steps are missing")
        if evidence_gate.get("status") != "pass":
            gaps.append("counterfactual rollout evidence gate did not pass")
        if calibration_summary.get("calibration_required"):
            gaps.append("counterfactual calibration gap requires review")
        status = "pass" if not gaps else "review"
        return TwmValidationStage(
            stage_code="counterfactual_rollout",
            stage_name="Counterfactual Rollout",
            status=status,
            claim="Baseline and intervention actions were rolled out under the same scenario for counterfactual comparison.",
            evidence={
                "horizon": rollout.get("horizon"),
                "evidence_gate": evidence_gate,
                "calibration_summary": calibration_summary,
                "delta_final": (rollout.get("deltas") or {}).get("final", {}),
            },
            gaps=gaps,
            next_actions=[] if status == "pass" else ["increase evidence coverage or connect treatment-effect calibration"],
        )

    def _validation_planning_stage(self, rollout: dict[str, Any]) -> TwmValidationStage:
        final = ((rollout.get("deltas") or {}).get("final") or {})
        lift = float(final.get("utility_delta_lift") or 0.0)
        risk_delta = float(final.get("constraint_probability_delta") or 0.0)
        confidence_delta = float(final.get("confidence_delta") or 0.0)
        gaps: list[str] = []
        if lift <= 0:
            gaps.append("intervention does not improve planning utility over baseline")
        if risk_delta > 0:
            gaps.append("intervention increases constraint risk")
        status = "pass" if not gaps else "review"
        return TwmValidationStage(
            stage_code="planning_lift",
            stage_name="Planning Lift",
            status=status,
            claim="The intervention arm is compared against baseline on utility, risk and confidence deltas.",
            evidence={
                "utility_delta_lift": lift,
                "constraint_probability_delta": risk_delta,
                "confidence_delta": confidence_delta,
                "claim_status": (rollout.get("summary") or {}).get("claim_status"),
            },
            gaps=gaps,
            next_actions=[] if status == "pass" else ["run candidate ranking or constrained beam search before claiming planning lift"],
        )

    def _validation_scca_stage(self, state_version_id: str, payload: dict[str, Any]) -> TwmValidationStage | None:
        require_scca = truthy(payload.get("require_scca_pass") or payload.get("require_scca_causal_evidence"))
        scca_report = self._payload_or_build_scca_causal_evidence_report(state_version_id, payload)
        if not require_scca and not scca_report:
            return None
        gate = dict(scca_report.get("evidence_gate") or {}) if scca_report else {}
        effect = dict(scca_report.get("effect") or {}) if scca_report else {}
        calibration_hint = dict(scca_report.get("calibration_hint") or {}) if scca_report else {}
        gaps: list[str] = []
        if not scca_report:
            gaps.append("SCCA causal evidence report is required but not provided")
        elif gate.get("status") != "pass":
            gaps.append("SCCA causal evidence gate did not pass")
            for item in gate.get("missing") or []:
                gaps.append(f"SCCA missing {item}")
        if require_scca and scca_report and calibration_hint.get("can_support_twm_causal_calibration") is False:
            gaps.append("SCCA calibration hint does not support TWM causal calibration")
        status = "pass" if not gaps else "review"
        return TwmValidationStage(
            stage_code="spatial_causal_evidence",
            stage_name="Spatial Causal Evidence",
            status=status,
            claim="External SCCA evidence is available to support spatial causal calibration without replacing TWM rollout validation.",
            evidence={
                "required": require_scca,
                "provided": bool(scca_report),
                "report_schema": scca_report.get("schema") if scca_report else None,
                "status": scca_report.get("status") if scca_report else "missing",
                "evidence_gate": gate,
                "effect": effect,
                "calibration_hint": calibration_hint,
                "boundary": scca_report.get("boundary") if scca_report else {},
            },
            gaps=gaps,
            next_actions=[] if status == "pass" else ["provide passing SCCA evidence or disable require_scca_pass for non-causal validation"],
        )

    def _validation_deployability_stage(
        self,
        audit: dict[str, Any],
        evidence_items: list[Any],
        review_tasks: list[Any],
    ) -> TwmValidationStage:
        evidence_gate = dict(audit.get("evidence_gate_summary") or {})
        gaps: list[str] = []
        if not evidence_items:
            gaps.append("no evidence items are attached")
        if not evidence_gate.get("all_have_checksum"):
            gaps.append("not all evidence items have checksum")
        pending_reviews = sum(1 for task in review_tasks if getattr(task, "status", "") == "pending")
        if pending_reviews:
            gaps.append(f"{pending_reviews} review tasks are still pending")
        status = "pass" if not gaps else "review"
        return TwmValidationStage(
            stage_code="gis_deployability",
            stage_name="GIS Deployability And Audit",
            status=status,
            claim="Outputs are tied to GIS evidence items, checksums and human review tasks.",
            evidence={
                "audit_report_type": audit.get("report_type"),
                "evidence_item_count": len(evidence_items),
                "evidence_gate_summary": evidence_gate,
                "review_task_count": len(review_tasks),
                "pending_review_count": pending_reviews,
            },
            gaps=gaps,
            next_actions=[] if status == "pass" else ["complete review tasks and checksum missing evidence before deployment"],
        )

    def _action_target_summary(self, action: TerritoryWorldModelAction, objects: list[TwmStateObject]) -> dict[str, Any]:
        requested = [str(item) for item in action.target_objects or [] if str(item)]
        role = action.target_role or ""
        role_objects = [
            obj for obj in objects
            if not role or role in {obj.canonical_role, obj.source_role, obj.object_type}
        ]
        index: dict[str, TwmStateObject] = {}
        for obj in objects:
            for key in (obj.id, obj.object_code, obj.source_feature_id):
                if key:
                    index[str(key)] = obj
        matched = []
        missing = []
        if requested:
            for key in requested:
                obj = index.get(key)
                if obj is None:
                    missing.append(key)
                    continue
                if role and role not in {obj.canonical_role, obj.source_role, obj.object_type}:
                    missing.append(key)
                    continue
                matched.append(obj)
        else:
            matched = role_objects
        return {
            "target_role": role,
            "requested_target_count": len(requested),
            "matched_target_count": len(matched),
            "role_target_count": len(role_objects),
            "missing_target_objects": missing,
            "target_scope_valid": bool(matched) and not missing,
            "matched_object_ids": [obj.id for obj in matched],
            "matched_object_codes": [obj.object_code for obj in matched[:25]],
            "spatial_scope": action.spatial_scope,
        }

    def _action_related_rule_hits(
        self,
        action: TerritoryWorldModelAction,
        target_summary: dict[str, Any],
        hits: list[TwmRuleHit],
    ) -> list[TwmRuleHit]:
        target_ids = set(target_summary.get("matched_object_ids") or [])
        if not target_ids:
            return []
        related = [
            hit for hit in hits
            if hit.subject_object_id in target_ids or (hit.target_object_id and hit.target_object_id in target_ids)
        ]
        if action.action_type.lower() in {"protect", "mitigate", "constrain", "review", "inspect"}:
            return related
        return [hit for hit in related if hit.severity in {"high", "critical", "blocking", "medium"}]

    def _mask_hit_payload(self, hit: TwmRuleHit) -> dict[str, Any]:
        return {
            "rule_hit_id": hit.id,
            "rule_id": hit.rule_id,
            "severity": hit.severity,
            "risk_score": hit.risk_score,
            "hit_status": hit.hit_status,
            "subject_object_id": hit.subject_object_id,
            "target_object_id": hit.target_object_id,
            "explanation": hit.explanation,
        }

    def _blocking_severities_for_action(self, action: TerritoryWorldModelAction) -> set[str]:
        action_type = (action.action_type or "").lower()
        high_risk_terms = ("convert", "expand", "relocate", "develop", "construct", "add")
        if any(term in action_type for term in high_risk_terms):
            return {"blocking", "critical", "high"}
        return {"blocking", "critical"}

    def _forecast_with_dynamics_candidate(self, plan_payload: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        candidate_report = self._candidate_report_from_payload(payload)
        if not candidate_report:
            return plan_payload
        forecast = dict(plan_payload.get("forecast") or {})
        gate = self._dynamics_candidate_forecast_gate(candidate_report, payload)
        base_gate = dict(forecast.get("evidence_gate") or {})
        base_missing = list(base_gate.get("missing") or [])
        for item in gate.get("missing") or []:
            if item not in base_missing:
                base_missing.append(item)
        candidate_summary = {
            "schema": candidate_report.get("schema", ""),
            "status": candidate_report.get("status", ""),
            "candidate": dict(candidate_report.get("candidate") or {}),
            "source": "dynamics_candidate_report",
        }
        if gate.get("passed"):
            prediction = self._select_candidate_prediction(candidate_report, payload)
            if prediction:
                self._apply_candidate_prediction_to_forecast(forecast, prediction, candidate_summary)
                candidate_summary["prediction_applied"] = True
            else:
                gate["passed"] = False
                gate["status"] = "review"
                gate.setdefault("missing", []).append("candidate_prediction")
                candidate_summary["prediction_applied"] = False
        else:
            candidate_summary["prediction_applied"] = False
        base_gate["dynamics_candidate"] = candidate_summary | {
            "gate": gate,
        }
        base_gate["missing"] = base_missing
        base_gate["passed"] = bool(base_gate.get("passed")) and bool(gate.get("passed"))
        base_gate["status"] = "pass" if base_gate.get("passed") else "review"
        forecast["evidence_gate"] = base_gate
        plan_payload["forecast"] = forecast
        summary = dict(plan_payload.get("summary") or {})
        summary["evidence_gate"] = base_gate
        summary["dynamics_candidate"] = candidate_summary
        plan_payload["summary"] = summary
        metrics = list(plan_payload.get("candidate_metrics") or [])
        for metric in metrics:
            if metric.get("metric_code") == "planning_utility_delta":
                metric["value"] = forecast.get("planning_utility_delta", metric.get("value"))
            elif metric.get("metric_code") == "constraint_violation_probability":
                metric["value"] = forecast.get("constraint_violation_probability", metric.get("value"))
            elif metric.get("metric_code") == "uncertainty":
                metric["value"] = (forecast.get("uncertainty") or {}).get("confidence", metric.get("value"))
        plan_payload["candidate_metrics"] = metrics
        return plan_payload

    def _counterfactual_with_dynamics_candidate(self, rollout_payload: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        if not self._candidate_report_from_payload(payload):
            return rollout_payload
        for arm_key in ("baseline_steps", "intervention_steps"):
            updated_steps = []
            for step in rollout_payload.get(arm_key) or []:
                if not isinstance(step, dict):
                    updated_steps.append(step)
                    continue
                plan_like = {
                    "forecast": dict(step.get("forecast") or {}),
                    "summary": {"evidence_gate": (step.get("forecast") or {}).get("evidence_gate", {})},
                    "candidate_metrics": [],
                }
                step_payload = dict(payload)
                step_payload["dynamics_prediction_id"] = self._rollout_prediction_id(step)
                adapted = self._forecast_with_dynamics_candidate(plan_like, step_payload)
                forecast = dict(adapted.get("forecast") or {})
                step["forecast"] = forecast
                step["metrics"] = self._rollout_step_metrics_from_forecast(forecast)
                updated_steps.append(step)
            rollout_payload[arm_key] = updated_steps
        rollout_payload["deltas"] = self._rollout_delta_dicts(
            rollout_payload.get("baseline_steps") or [],
            rollout_payload.get("intervention_steps") or [],
        )
        rollout_payload["evidence_gate"] = self._rollout_evidence_gate_dicts(
            rollout_payload.get("baseline_steps") or [],
            rollout_payload.get("intervention_steps") or [],
        )
        rollout_payload["calibration_summary"] = self._rollout_calibration_summary_dicts(
            rollout_payload.get("baseline_steps") or [],
            rollout_payload.get("intervention_steps") or [],
        )
        summary = dict(rollout_payload.get("summary") or {})
        baseline_steps = rollout_payload.get("baseline_steps") or []
        intervention_steps = rollout_payload.get("intervention_steps") or []
        summary["baseline_final"] = (baseline_steps[-1].get("metrics") if baseline_steps else {}) or {}
        summary["intervention_final"] = (intervention_steps[-1].get("metrics") if intervention_steps else {}) or {}
        summary["planning_lift"] = (rollout_payload.get("deltas") or {}).get("final", {}).get("utility_delta_lift", 0.0)
        summary["risk_delta"] = (rollout_payload.get("deltas") or {}).get("final", {}).get("constraint_probability_delta", 0.0)
        gate = dict(rollout_payload.get("evidence_gate") or {})
        summary["claim_status"] = "claim_supported" if gate.get("passed") and summary.get("planning_lift", 0.0) > 0 else "review_required"
        summary["dynamics_candidate_applied"] = any(
            (((step.get("forecast") or {}).get("evidence_gate") or {}).get("dynamics_candidate") or {}).get("prediction_applied")
            for step in baseline_steps + intervention_steps
            if isinstance(step, dict)
        )
        rollout_payload["summary"] = summary
        return rollout_payload

    def _copy_dynamics_candidate_payload(self, source: dict[str, Any], target: dict[str, Any]) -> None:
        for key in (
            "dynamics_candidate_report",
            "dynamics_fit_report",
            "fit_report",
            "dynamics_candidate",
            "dynamics_candidate_prediction",
            "dynamics_prediction_id",
            "dynamics_candidate_required_status",
            "allow_review_dynamics_candidate",
        ):
            if key in source:
                target[key] = source[key]

    def _rollout_prediction_id(self, step: dict[str, Any]) -> str:
        explicit = step.get("prediction_id")
        if explicit:
            return str(explicit)
        arm = str(step.get("arm") or "")
        idx = step.get("step_index")
        return f"{arm}:{idx}" if arm or idx is not None else ""

    def _rollout_step_metrics_from_forecast(self, forecast: dict[str, Any]) -> dict[str, Any]:
        uncertainty = dict(forecast.get("uncertainty") or {})
        evidence_gate = dict(forecast.get("evidence_gate") or {})
        return {
            "constraint_violation_probability": float(safe_float(forecast.get("constraint_violation_probability"), 0.0) or 0.0),
            "planning_utility_delta": float(safe_float(forecast.get("planning_utility_delta"), 0.0) or 0.0),
            "confidence": float(safe_float(uncertainty.get("confidence"), 0.0) or 0.0),
            "calibration_gap": float(safe_float(uncertainty.get("calibration_gap"), 0.0) or 0.0),
            "evidence_gate_status": evidence_gate.get("status", "review"),
        }

    def _rollout_delta_dicts(self, baseline_steps: list[dict[str, Any]], intervention_steps: list[dict[str, Any]]) -> dict[str, Any]:
        by_step = []
        for base, inter in zip(baseline_steps, intervention_steps):
            base_metrics = dict(base.get("metrics") or {})
            inter_metrics = dict(inter.get("metrics") or {})
            by_step.append(
                {
                    "step_index": base.get("step_index", 0),
                    "utility_delta_lift": round(float(safe_float(inter_metrics.get("planning_utility_delta"), 0.0) or 0.0) - float(safe_float(base_metrics.get("planning_utility_delta"), 0.0) or 0.0), 4),
                    "constraint_probability_delta": round(float(safe_float(inter_metrics.get("constraint_violation_probability"), 0.0) or 0.0) - float(safe_float(base_metrics.get("constraint_violation_probability"), 0.0) or 0.0), 4),
                    "confidence_delta": round(float(safe_float(inter_metrics.get("confidence"), 0.0) or 0.0) - float(safe_float(base_metrics.get("confidence"), 0.0) or 0.0), 4),
                }
            )
        final = by_step[-1] if by_step else {
            "utility_delta_lift": 0.0,
            "constraint_probability_delta": 0.0,
            "confidence_delta": 0.0,
        }
        return {
            "by_step": by_step,
            "final": final,
            "cumulative": {
                "utility_delta_lift": round(sum(item["utility_delta_lift"] for item in by_step), 4),
                "constraint_probability_delta": round(sum(item["constraint_probability_delta"] for item in by_step), 4),
                "confidence_delta": round(sum(item["confidence_delta"] for item in by_step), 4),
            },
        }

    def _rollout_evidence_gate_dicts(self, baseline_steps: list[dict[str, Any]], intervention_steps: list[dict[str, Any]]) -> dict[str, Any]:
        gates = [((step.get("forecast") or {}).get("evidence_gate") or {}) for step in baseline_steps + intervention_steps if isinstance(step, dict)]
        missing: list[str] = []
        for gate in gates:
            for item in gate.get("missing") or []:
                if item not in missing:
                    missing.append(item)
        passed = bool(gates) and all(bool(gate.get("passed")) for gate in gates)
        coverages = [float(safe_float(gate.get("coverage"), 0.0) or 0.0) for gate in gates]
        return {
            "passed": passed,
            "status": "pass" if passed else "review",
            "missing": missing,
            "min_coverage": round(min(coverages), 4) if coverages else 0.0,
            "step_count": len(gates),
        }

    def _rollout_calibration_summary_dicts(self, baseline_steps: list[dict[str, Any]], intervention_steps: list[dict[str, Any]]) -> dict[str, Any]:
        all_steps = baseline_steps + intervention_steps
        gaps = [float(safe_float((step.get("metrics") or {}).get("calibration_gap"), 0.0) or 0.0) for step in all_steps]
        treatment_effects = [
            float(safe_float(((step.get("forecast") or {}).get("calibration") or {}).get("treatment_effect"), 0.0) or 0.0)
            for step in all_steps
        ]
        return {
            "max_calibration_gap": round(max(gaps, default=0.0), 4),
            "mean_treatment_effect": round(sum(treatment_effects) / max(1, len(treatment_effects)), 4),
            "calibration_required": any(gap > 0.2 for gap in gaps),
            "support": {
                "baseline_steps": len(baseline_steps),
                "intervention_steps": len(intervention_steps),
            },
        }

    def _beam_ranking_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_policy = payload.get("ranking_policy")
        if not isinstance(raw_policy, dict):
            raw_policy = payload.get("planner_ranking_weights")
        if not isinstance(raw_policy, dict):
            raw_policy = {}
        weights = dict(raw_policy.get("weights") or raw_policy)
        penalties = dict(raw_policy.get("penalties") or raw_policy)
        policy = {
            "policy_id": str(raw_policy.get("policy_id") or raw_policy.get("id") or "utility_risk_confidence_v1"),
            "schema": "territory_world_model.beam_ranking_policy.v1",
            "formula": (
                "utility_weight * utility - risk_weight * risk + confidence_weight * confidence "
                "- blocked_penalty(if blocked) - review_penalty(if evidence gate not pass)"
            ),
            "weights": {
                "utility": float(safe_float(weights.get("utility", weights.get("utility_weight")), 1.0) or 0.0),
                "risk": float(safe_float(weights.get("risk", weights.get("risk_weight")), 1.0) or 0.0),
                "confidence": float(safe_float(weights.get("confidence", weights.get("confidence_weight")), 0.1) or 0.0),
            },
            "penalties": {
                "blocked": float(safe_float(penalties.get("blocked", penalties.get("blocked_penalty")), 1.0) or 0.0),
                "review": float(safe_float(penalties.get("review", penalties.get("review_penalty")), 0.15) or 0.0),
            },
            "source": "payload" if raw_policy else "default",
        }
        return policy

    def _beam_rank_score(
        self,
        *,
        utility: float,
        risk: float,
        confidence: float,
        blocked: bool,
        evidence_status: str,
        ranking_policy: dict[str, Any],
    ) -> float:
        weights = dict(ranking_policy.get("weights") or {})
        penalties = dict(ranking_policy.get("penalties") or {})
        rank_score = (
            float(safe_float(weights.get("utility"), 1.0) or 0.0) * utility
            - float(safe_float(weights.get("risk"), 1.0) or 0.0) * risk
            + float(safe_float(weights.get("confidence"), 0.1) or 0.0) * confidence
        )
        if blocked:
            rank_score -= float(safe_float(penalties.get("blocked"), 1.0) or 0.0)
        if evidence_status != "pass":
            rank_score -= float(safe_float(penalties.get("review"), 0.15) or 0.0)
        return round(rank_score, 6)

    def _beam_candidate_from_forecast(self, idx: int, action_payload: dict[str, Any], forecast_plan: dict[str, Any], ranking_policy: dict[str, Any]) -> dict[str, Any]:
        forecast = dict(forecast_plan.get("forecast") or {})
        evidence_gate = dict(forecast.get("evidence_gate") or {})
        uncertainty = dict(forecast.get("uncertainty") or {})
        utility = float(safe_float(forecast.get("planning_utility_delta"), 0.0) or 0.0)
        risk = float(safe_float(forecast.get("constraint_violation_probability"), 0.0) or 0.0)
        confidence = float(safe_float(uncertainty.get("confidence"), 0.0) or 0.0)
        action_mask = dict(evidence_gate.get("action_mask") or {})
        blocked = (
            evidence_gate.get("status") == "blocked"
            or bool(action_mask.get("hard_blocks"))
            or not action_mask.get("allowed", True)
        )
        rank_score = self._beam_rank_score(
            utility=utility,
            risk=risk,
            confidence=confidence,
            blocked=blocked,
            evidence_status=str(evidence_gate.get("status") or "review"),
            ranking_policy=ranking_policy,
        )
        return {
            "candidate_id": str(action_payload.get("candidate_id") or action_payload.get("id") or f"candidate:{idx}"),
            "rank": None,
            "action": {
                "action_type": action_payload.get("action_type") or "inspect",
                "target_role": action_payload.get("target_role") or "project",
                "target_objects": list(action_payload.get("target_objects") or []),
                "magnitude": action_payload.get("magnitude") or 1.0,
                "scenario": action_payload.get("scenario") or "beam_plan",
            },
            "forecast": forecast,
            "utility": round(utility, 6),
            "risk": round(risk, 6),
            "confidence": round(confidence, 6),
            "rank_score": rank_score,
            "ranking_policy_id": ranking_policy.get("policy_id"),
            "evidence_gate": evidence_gate,
            "claim_status": "claim_supported" if evidence_gate.get("status") == "pass" and not blocked else "review_required",
            "selection_status": "hard_blocked" if blocked else ("eligible" if evidence_gate.get("status") == "pass" else "review"),
        }

    def _beam_candidate_hard_blocked(self, candidate: dict[str, Any]) -> bool:
        evidence_gate = dict(candidate.get("evidence_gate") or {})
        action_mask = dict(evidence_gate.get("action_mask") or {})
        return (
            evidence_gate.get("status") == "blocked"
            or bool(action_mask.get("hard_blocks"))
            or not action_mask.get("allowed", True)
        )

    def _beam_evidence_gate(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        missing: list[str] = []
        statuses = []
        for candidate in candidates:
            gate = dict(candidate.get("evidence_gate") or {})
            statuses.append(gate.get("status", "review"))
            for item in gate.get("missing") or []:
                if item not in missing:
                    missing.append(item)
        passed_candidates = sum(1 for candidate in candidates if candidate.get("claim_status") == "claim_supported")
        return {
            "passed": bool(candidates) and passed_candidates > 0,
            "status": "pass" if candidates and passed_candidates > 0 else "review",
            "missing": missing,
            "candidate_count": len(candidates),
            "claim_supported_count": passed_candidates,
            "candidate_statuses": statuses,
        }

    def _beam_plan_recommendations(self, candidates: list[dict[str, Any]], evidence_gate: dict[str, Any]) -> list[str]:
        recommendations: list[str] = []
        if not candidates:
            return ["provide at least one candidate action for beam planning"]
        if evidence_gate.get("status") != "pass":
            recommendations.append("treat beam result as review-only until at least one candidate passes evidence gate")
        if any((((candidate.get("evidence_gate") or {}).get("action_mask") or {}).get("hard_blocks")) for candidate in candidates):
            recommendations.append("remove or mitigate hard-blocked candidate actions before deployment")
        if any((((candidate.get("evidence_gate") or {}).get("dynamics_candidate") or {}).get("gate") or {}).get("status") != "pass" for candidate in candidates if ((candidate.get("evidence_gate") or {}).get("dynamics_candidate"))):
            recommendations.append("do not let review/blocked dynamics candidates drive planning rank")
        recommendations.append("validate selected candidate with counterfactual rollout before operational GIS deployment")
        return recommendations

    def _selected_plan_source_bundle(self, state_version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        optimization_dir = payload.get("optimization_dir") or payload.get("optimization_bundle_dir")
        if optimization_dir:
            planning_report = self.farmland_layout_beam_plan_from_optimization_bundle(state_version_id, optimization_dir, payload)
            return {
                "source": {
                    "kind": "farmland_layout_optimization_bundle",
                    "optimization_dir": str(optimization_dir),
                },
                "optimization_bundle": planning_report.get("optimization_bundle") or {},
                "beam_plan": planning_report.get("beam_plan") or {},
                "selection_audit": planning_report.get("selection_audit") or {},
                "claim_boundary": planning_report.get("claim_boundary") or {},
                "recommendations": planning_report.get("recommendations") or [],
                "status": planning_report.get("status"),
                "schema": planning_report.get("schema"),
            }
        existing_beam = payload.get("beam_plan_report") or payload.get("beam_plan")
        if isinstance(existing_beam, dict):
            return {
                "source": {"kind": "provided_beam_plan_report"},
                "beam_plan": dict(existing_beam),
                "selection_audit": {},
                "status": existing_beam.get("status"),
                "schema": existing_beam.get("schema"),
            }
        beam_payload = dict(payload)
        beam_report = self.beam_plan(state_version_id, beam_payload)
        return {
            "source": {"kind": "beam_plan"},
            "beam_plan": beam_report,
            "selection_audit": {},
            "status": beam_report.get("status"),
            "schema": beam_report.get("schema"),
        }

    def _selected_plan_beam_report(self, planning_bundle: dict[str, Any]) -> dict[str, Any]:
        return dict(planning_bundle.get("beam_plan") or {})

    def _selected_plan_action(self, selected: dict[str, Any]) -> dict[str, Any]:
        action = dict(selected.get("action") or {})
        if not action and selected:
            action = {
                "action_type": selected.get("action_type") or "inspect",
                "target_role": selected.get("target_role") or "project",
                "magnitude": selected.get("magnitude") or 1.0,
                "scenario": selected.get("scenario") or selected.get("candidate_id") or "selected_plan",
            }
        if selected.get("candidate_id") and not action.get("candidate_id"):
            action["candidate_id"] = selected.get("candidate_id")
        if selected.get("candidate_id") and not action.get("scenario"):
            action["scenario"] = selected.get("candidate_id")
        if selected.get("forecast") and "parameters" not in action:
            forecast = dict(selected.get("forecast") or {})
            action["parameters"] = {
                "selected_forecast_utility": forecast.get("planning_utility_delta"),
                "selected_forecast_risk": forecast.get("constraint_violation_probability"),
                "selected_forecast_confidence": (forecast.get("uncertainty") or {}).get("confidence"),
            }
        return {key: value for key, value in action.items() if value is not None}

    def _selected_plan_selection_audit(
        self,
        planning_bundle: dict[str, Any],
        beam_report: dict[str, Any],
        selected: dict[str, Any],
    ) -> dict[str, Any]:
        audit = dict(planning_bundle.get("selection_audit") or {})
        candidates = [dict(item) for item in beam_report.get("candidates") or [] if isinstance(item, dict)]
        selected_id = str(selected.get("candidate_id") or audit.get("selected_candidate_id") or "")
        selected_candidate = selected
        if selected_id:
            selected_candidate = next((item for item in candidates if str(item.get("candidate_id") or "") == selected_id), selected)
        selected_hard_blocked = self._beam_candidate_hard_blocked(dict(selected_candidate or {})) if selected_candidate else False
        eligible_count = sum(1 for candidate in candidates if not self._beam_candidate_hard_blocked(candidate))
        blocked_ids = [
            str(candidate.get("candidate_id") or "")
            for candidate in candidates
            if self._beam_candidate_hard_blocked(candidate) and str(candidate.get("candidate_id") or "")
        ]
        selected_from_legal = audit.get("selected_from_legal_feasible_space")
        if selected_from_legal is None:
            selected_from_legal = bool(selected_id) and not selected_hard_blocked
        return {
            "schema": "territory_world_model.selected_plan_selection_audit.v1",
            **audit,
            "candidate_count": audit.get("candidate_count", len(candidates)),
            "eligible_candidate_count": audit.get("eligible_candidate_count", eligible_count),
            "hard_blocked_candidate_ids": audit.get("hard_blocked_candidate_ids", blocked_ids),
            "selected_candidate_id": selected_id,
            "selected_hard_blocked": bool(audit.get("selected_hard_blocked", selected_hard_blocked)),
            "selected_from_legal_feasible_space": bool(selected_from_legal),
            "beam_status": beam_report.get("status"),
            "beam_evidence_gate_status": (beam_report.get("evidence_gate") or {}).get("status"),
        }

    def _selected_plan_rollout_payload(
        self,
        payload: dict[str, Any],
        selected_action: dict[str, Any],
        selected: dict[str, Any],
    ) -> dict[str, Any]:
        scenario = str(payload.get("scenario") or selected_action.get("scenario") or selected.get("candidate_id") or "selected_plan_evaluation")
        baseline_action = payload.get("baseline_action")
        if not isinstance(baseline_action, dict):
            baseline_action = {
                "action_type": "inspect",
                "target_role": selected_action.get("target_role") or payload.get("target_role") or "project",
                "magnitude": 1.0,
                "scenario": f"{scenario}:baseline",
                "description": "baseline action before selected plan",
            }
        intervention = dict(selected_action or {})
        intervention.setdefault("action_type", payload.get("intervention_action_type") or "protect")
        intervention.setdefault("target_role", payload.get("target_role") or "project")
        intervention.setdefault("magnitude", payload.get("intervention_magnitude") or payload.get("magnitude") or 1.0)
        intervention.setdefault("scenario", scenario)
        intervention.setdefault("description", selected.get("candidate_id") or "selected plan intervention")
        rollout_payload = {
            "scenario": scenario,
            "horizon": int(payload.get("horizon") or 3),
            "evidence_coverage": payload.get("evidence_coverage"),
            "baseline_action": baseline_action,
            "intervention_actions": [intervention],
            "scenario_context": _mapping_payload(payload.get("scenario_context")),
        }
        self._copy_dynamics_candidate_payload(payload, rollout_payload)
        if payload.get("causal_calibration"):
            rollout_payload["causal_calibration"] = payload.get("causal_calibration")
        if payload.get("causal_calibration_report"):
            rollout_payload["causal_calibration_report"] = payload.get("causal_calibration_report")
        return rollout_payload

    def _selected_plan_validation_payload(
        self,
        payload: dict[str, Any],
        selected_action: dict[str, Any],
        rollout_payload: dict[str, Any],
    ) -> dict[str, Any]:
        validation_payload = {
            "scenario": rollout_payload.get("scenario") or payload.get("scenario") or "selected_plan_validation",
            "horizon": rollout_payload.get("horizon") or payload.get("horizon") or 3,
            "evidence_coverage": payload.get("evidence_coverage"),
            "target_role": selected_action.get("target_role") or payload.get("target_role") or "project",
            "action_type": selected_action.get("action_type") or payload.get("action_type") or "protect",
            "magnitude": selected_action.get("magnitude") or payload.get("magnitude") or 1.0,
            "baseline_action": rollout_payload.get("baseline_action"),
            "intervention_actions": rollout_payload.get("intervention_actions"),
            "scenario_context": _mapping_payload(payload.get("scenario_context")),
            "parameters": dict(selected_action.get("parameters") or payload.get("parameters") or {}),
        }
        for key in (
            "treatment",
            "claim_gate_facts",
            "geofm_gate_report",
            "causal_calibration",
            "causal_calibration_report",
            "uses_geofm",
            "geofm_required",
            "scca_causal_evidence_report",
            "scca_evidence_report",
            "scca_result",
            "scca_report",
            "scca_payload",
            "scca_output_dir",
            "scca_dir",
            "scca_path",
            "scca_manifest_path",
            "require_scca_pass",
            "require_scca_causal_evidence",
        ):
            if key in payload:
                validation_payload[key] = payload[key]
        self._copy_dynamics_candidate_payload(payload, validation_payload)
        return validation_payload

    def _selected_plan_bundle_evidence_gate(
        self,
        selection_audit: dict[str, Any],
        beam_report: dict[str, Any],
        rollout: dict[str, Any],
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        missing: list[str] = []
        blocked = False
        if not selection_audit.get("selected_candidate_id"):
            missing.append("selected_candidate")
            blocked = True
        if selection_audit.get("selected_hard_blocked"):
            missing.append("selected_hard_blocked")
            blocked = True
        if not selection_audit.get("selected_from_legal_feasible_space"):
            missing.append("legal_feasible_selection")
        beam_gate = dict(beam_report.get("evidence_gate") or {})
        if beam_gate.get("status") != "pass":
            missing.append("beam_plan_evidence_gate")
        rollout_gate = dict(rollout.get("evidence_gate") or {})
        if rollout_gate.get("status") != "pass":
            missing.append("counterfactual_rollout_evidence_gate")
        if validation.get("overall_status") == "blocked":
            missing.append("validation_blocked")
            blocked = True
        elif validation.get("overall_status") != "pass":
            missing.append("validation_review")
        status = "blocked" if blocked else ("pass" if not missing else "review")
        return {
            "schema": "territory_world_model.selected_plan_evidence_gate.v1",
            "passed": status == "pass",
            "status": status,
            "blocked": blocked,
            "missing": missing,
            "selection_audit": selection_audit,
            "beam_gate": beam_gate,
            "rollout_gate": rollout_gate,
            "validation_status": validation.get("overall_status"),
        }

    def _selected_plan_bundle_recommendations(
        self,
        evidence_gate: dict[str, Any],
        selection_audit: dict[str, Any],
        validation: dict[str, Any],
    ) -> list[str]:
        recommendations: list[str] = []
        if selection_audit.get("selected_hard_blocked"):
            recommendations.append("do not promote the selected plan because it is hard-blocked")
        if not selection_audit.get("selected_from_legal_feasible_space"):
            recommendations.append("complete legal-feasible selection audit before using the selected plan operationally")
        if "counterfactual_rollout_evidence_gate" in (evidence_gate.get("missing") or []):
            recommendations.append("increase evidence coverage or causal calibration before relying on the counterfactual rollout")
        if validation.get("overall_status") != "pass":
            recommendations.append("treat the bundle as review-only until validation stages and claim ladder are upgraded")
        recommendations.append("connect real observed-history and human review results before production deployment")
        return recommendations

    def _farmland_layout_equivalence_assessment(
        self,
        *,
        candidate_count: int,
        has_dynamics_candidate: bool,
        dynamics_gate: dict[str, Any],
        has_external_generator: bool,
        optimizer_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        missing: list[str] = []
        if candidate_count < 2:
            missing.append("multiple_candidate_layout_actions")
        if not has_dynamics_candidate:
            missing.append("multi_head_dynamics_candidate_report")
        elif dynamics_gate.get("status") not in {"pass", "accepted"}:
            missing.append("passing_dynamics_candidate_gate")
        if not has_external_generator:
            missing.append("layout_search_or_policy_generator")
        validation = dict(optimizer_evidence.get("validation") or {})
        if validation.get("spatial_holdout") not in {True, "pass", "passed"}:
            missing.append("spatial_holdout_validation")
        if validation.get("temporal_holdout") not in {True, "pass", "passed"}:
            missing.append("temporal_holdout_validation")
        if validation.get("hard_constraint_recheck") not in {True, "pass", "passed"}:
            missing.append("hard_constraint_recheck")
        if validation.get("planning_lift") not in {True, "pass", "passed"}:
            missing.append("planning_lift_benchmark")
        if not missing:
            decision = "paper_level_equivalence_candidate"
            status = "pass"
        elif has_external_generator and has_dynamics_candidate and candidate_count >= 2:
            decision = "partial_equivalence_review_required"
            status = "review"
        else:
            decision = "planner_consumer_only_not_equivalent"
            status = "review"
        return {
            "schema": "territory_world_model.farmland_layout_optimization_equivalence_assessment.v1",
            "status": status,
            "decision": decision,
            "missing": missing,
            "evidence": {
                "candidate_action_count": candidate_count,
                "has_dynamics_candidate_report": has_dynamics_candidate,
                "dynamics_candidate_gate_status": dynamics_gate.get("status"),
                "has_external_generator": has_external_generator,
                "validation": validation,
            },
        }

    def _farmland_layout_capability_recommendations(
        self,
        equivalence: dict[str, Any],
        candidate_count: int,
        has_external_generator: bool,
    ) -> list[str]:
        recommendations: list[str] = []
        if candidate_count < 2:
            recommendations.append("provide at least two candidate farmland layout actions or scenarios before claiming optimization")
        if not has_external_generator:
            recommendations.append("connect Paper1-4 DRL, Paper9 MPC/world-model search, Pareto search or heuristic generator as candidate source")
        for missing in equivalence.get("missing") or []:
            if missing == "hard_constraint_recheck":
                recommendations.append("re-run every generated layout through TWM hard-constraint and action-mask checks")
            if missing == "planning_lift_benchmark":
                recommendations.append("compare selected layout against paper baselines using planning lift, regret and infeasible-plan rejection")
            if missing in {"spatial_holdout_validation", "temporal_holdout_validation"}:
                recommendations.append("add spatial and temporal holdout validation before equivalence claims")
        if not recommendations:
            recommendations.append("treat this as a candidate equivalence claim and still require real observed-history validation before production use")
        return recommendations

    def _optimizer_metric_projection_report_from_candidate_actions(
        self,
        candidate_actions: list[dict[str, Any]],
        adapter: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        overrides = dict(payload.get("candidate_metric_overrides") or payload.get("optimizer_metric_overrides") or {})
        predictions: dict[str, dict[str, Any]] = {}
        for idx, action in enumerate(candidate_actions):
            candidate_id = str(action.get("candidate_id") or action.get("id") or f"candidate:{idx}")
            parameters = dict(action.get("parameters") or {})
            execution_mask = dict(action.get("execution_mask") or {})
            override = dict(overrides.get(candidate_id) or {})
            utility = float(
                safe_float(
                    override.get("planning_utility_delta", parameters.get("planning_utility_delta", parameters.get("weighted_score"))),
                    0.0,
                )
                or 0.0
            )
            risk = float(
                safe_float(
                    override.get("constraint_violation_probability", parameters.get("constraint_violation_probability")),
                    0.0,
                )
                or 0.0
            )
            confidence = float(safe_float(override.get("confidence", execution_mask.get("confidence")), 0.6) or 0.0)
            predictions[f"candidate:{idx}"] = {
                "candidate_id": candidate_id,
                "constraint_violation_probability": round(max(0.0, min(1.0, risk)), 6),
                "planning_utility_delta": round(max(-1.0, min(2.0, utility)), 6),
                "uncertainty": {
                    "confidence": round(max(0.0, min(1.0, confidence)), 6),
                    "source": "optimizer_metric_projection",
                },
                "calibration": {
                    "source": "optimizer_metric_projection",
                    "not_for_production": ((adapter.get("optimizer_evidence") or {}).get("pareto_summary") or {}).get("not_for_production", True),
                },
            }
        return {
            "schema": "territory_world_model.optimizer_metric_projection_report.v1",
            "status": "pass" if predictions else "review",
            "candidate": {
                "model_name": "optimizer_metric_projection",
                "source_schema": adapter.get("schema"),
            },
            "predictions": predictions,
            "evaluation": {"status": "pass" if predictions else "review", "evidence_gate": {"status": "pass" if predictions else "review"}},
            "evidence_gate": {"status": "pass" if predictions else "review", "passed": bool(predictions)},
        }

    def _farmland_layout_bundle_beam_selection_audit(self, adapter: dict[str, Any], beam_report: dict[str, Any]) -> dict[str, Any]:
        actions = [dict(item) for item in adapter.get("candidate_actions") or [] if isinstance(item, dict)]
        action_by_id = {str(action.get("candidate_id") or ""): action for action in actions}
        legal_ids = [
            candidate_id
            for candidate_id, action in action_by_id.items()
            if candidate_id and bool((action.get("execution_mask") or {}).get("allowed"))
        ]
        blocked_ids = [
            candidate_id
            for candidate_id, action in action_by_id.items()
            if candidate_id and not bool((action.get("execution_mask") or {}).get("allowed"))
        ]
        beam_candidates = [dict(item) for item in beam_report.get("candidates") or [] if isinstance(item, dict)]
        beam_by_id = {str(item.get("candidate_id") or ""): item for item in beam_candidates}
        eligible_ids = [candidate_id for candidate_id, candidate in beam_by_id.items() if candidate_id and not self._beam_candidate_hard_blocked(candidate)]
        selected = dict(beam_report.get("selected") or {})
        selected_id = str(selected.get("candidate_id") or "")
        selected_action = dict(action_by_id.get(selected_id) or {})
        selected_mask = dict(selected_action.get("execution_mask") or {})
        selected_beam = dict(beam_by_id.get(selected_id) or selected)
        selected_hard_blocked = bool(selected_id) and self._beam_candidate_hard_blocked(selected_beam)
        selected_from_legal = bool(selected_id) and selected_id in legal_ids and not selected_hard_blocked
        return {
            "schema": "territory_world_model.farmland_layout_bundle_beam_selection_audit.v1",
            "candidate_count": len(actions),
            "legal_feasible_count": len(legal_ids),
            "blocked_count": len(blocked_ids),
            "eligible_candidate_count": len(eligible_ids),
            "legal_feasible_candidate_ids": legal_ids,
            "hard_blocked_candidate_ids": blocked_ids,
            "eligible_candidate_ids": eligible_ids,
            "selected_candidate_id": selected_id,
            "selected_allowed": bool(selected_mask.get("allowed", bool(selected_id))),
            "selected_hard_blocks": list(selected_mask.get("hard_blocks") or []),
            "selected_hard_blocked": selected_hard_blocked,
            "selected_from_legal_feasible_space": selected_from_legal,
            "hard_constraint_filter_enforced": selected_from_legal or (not selected_id and not legal_ids),
        }

    def _farmland_layout_bundle_beam_recommendations(
        self,
        adapter: dict[str, Any],
        beam_report: dict[str, Any],
        selection_audit: dict[str, Any],
    ) -> list[str]:
        recommendations: list[str] = []
        if selection_audit.get("blocked_count"):
            recommendations.append("keep hard-blocked optimization scenarios as audit or stress-test cases only")
        if not selection_audit.get("selected_candidate_id"):
            recommendations.append("no legal feasible candidate was selected; do not promote this optimization bundle")
        elif not selection_audit.get("selected_from_legal_feasible_space"):
            recommendations.append("block promotion because the selected candidate is outside the legal feasible space")
        if ((adapter.get("optimizer_evidence") or {}).get("pareto_summary") or {}).get("not_for_production", True):
            recommendations.append("treat this bundle as engineering fixture output, not a production optimization result")
        if beam_report.get("status") != "pass":
            recommendations.append("upgrade evidence coverage, observed-history validation and holdout tests before production use")
        recommendations.append("run counterfactual rollout and human legal review on the selected candidate before operational GIS deployment")
        return recommendations

    def _optimization_weighted_score(self, scenario_id: str, pareto: dict[str, Any], metrics: list[dict[str, Any]]) -> float:
        for key in ("ranked_scenarios", "all_scenario_ranked", "non_dominated_scenarios", "blocked_scenarios"):
            for row in pareto.get(key) or []:
                if str(row.get("scenario_id") or "") == scenario_id:
                    return round(float(safe_float(row.get("weighted_score"), 0.0) or 0.0), 6)
        return round(
            sum(float(safe_float(row.get("weighted_score"), 0.0) or 0.0) for row in metrics),
            6,
        )

    def _optimization_utility_from_metrics(self, metrics: list[dict[str, Any]], weighted_score: float) -> float:
        score = float(weighted_score or 0.0)
        for row in metrics:
            objective = str(row.get("objective_id") or "")
            value = float(safe_float(row.get("normalized_score"), 0.0) or 0.0)
            weight = float(safe_float(row.get("weight"), 1.0) or 1.0)
            if objective in {"farmland_gain_m2", "development_area_m2", "compactness_score", "robustness_score", "slope_improvement_pct", "contiguity_gain"}:
                score += 0.05 * value * weight
            if objective in {"farmland_loss_m2", "planning_conflict_m2", "adjustment_cost_proxy", "review_load_count"}:
                score -= 0.03 * (1.0 - value) * weight
        return round(max(-1.0, min(2.0, score)), 6)

    def _optimization_risk_from_feasibility(self, feasibility: dict[str, Any], violations: list[dict[str, Any]]) -> float:
        hard_violation = float(safe_float(feasibility.get("hard_constraint_violation_m2"), 0.0) or 0.0)
        pbf = float(safe_float(feasibility.get("pbf_overlap_m2"), 0.0) or 0.0)
        eco = float(safe_float(feasibility.get("eco_overlap_m2"), 0.0) or 0.0)
        risk = min(0.85, hard_violation / 1_000_000.0 + pbf / 1_500_000.0 + eco / 1_500_000.0)
        if str(feasibility.get("hard_constraint_status") or "") != "legal_feasible":
            risk = max(risk, 0.72)
        if truthy(feasibility.get("requires_legal_review")):
            risk = max(risk, 0.55)
        if any(str(item.get("severity") or "").lower() in {"critical", "blocking"} for item in violations):
            risk = max(risk, 0.75)
        return round(max(0.0, min(1.0, risk)), 6)

    def _optimization_action_type(self, row: dict[str, Any]) -> str:
        scenario_type = str(row.get("scenario_type") or "").lower()
        scenario_id = str(row.get("scenario_id") or "").lower()
        if "baseline" in scenario_type or "baseline" in scenario_id:
            return "inspect"
        if "eco" in scenario_id or "ecological" in scenario_id:
            return "protect"
        if "development" in scenario_id:
            return "develop_with_constraints"
        if "review" in scenario_id:
            return "defer_review"
        if "balanced" in scenario_id:
            return "optimize_layout"
        return "optimize_layout"

    def _candidate_report_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        backend_report = payload.get("dynamics_backend_report")
        if isinstance(backend_report, dict):
            adapted = self._candidate_report_from_backend_report(backend_report)
            if adapted:
                return adapted
        for key in ("dynamics_candidate_report", "fit_report", "dynamics_fit_report"):
            report = payload.get(key)
            if isinstance(report, dict):
                return dict(report)
        candidate = payload.get("dynamics_candidate")
        if isinstance(candidate, dict):
            return {
                "schema": "territory_world_model.external_dynamics_candidate.v1",
                "status": candidate.get("status") or "review",
                "candidate": dict(candidate.get("candidate") or candidate.get("metadata") or {}),
                "learned_parameters": dict(candidate.get("learned_parameters") or {}),
                "predictions": dict(candidate.get("predictions") or {}),
                "evaluation": dict(candidate.get("evaluation") or {}),
                "evidence_gate": dict(candidate.get("evidence_gate") or {}),
            }
        return {}

    def _candidate_report_from_backend_report(self, backend_report: dict[str, Any]) -> dict[str, Any]:
        adapter = dict(backend_report.get("adapter_contract") or {})
        candidate = dict(adapter.get("candidate_report") or {})
        if not candidate:
            return {}
        evidence_gate = dict(backend_report.get("evidence_gate") or {})
        report_status = str(backend_report.get("status") or "review")
        candidate["status"] = "pass" if report_status == "pass" and evidence_gate.get("status") == "pass" else report_status
        candidate["evidence_gate"] = evidence_gate
        candidate["schema"] = candidate.get("schema") or "territory_world_model.dynamics_backend_candidate.v1"
        return candidate

    def _dynamics_backend_descriptor(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_backend = payload.get("backend")
        if raw_backend in (None, ""):
            raw_backend = payload.get("dynamics_backend")
        backend = self._payload_mapping(raw_backend)
        candidate_report = self._raw_backend_candidate_report(payload)
        backend_type = str(
            backend.get("backend_type")
            or backend.get("type")
            or backend.get("training_method")
            or ("external_candidate" if candidate_report else "deterministic_scaffold")
        )
        if backend_type in {"transparent", "baseline", "scaffold"}:
            backend_type = "deterministic_scaffold"
        return {
            "backend_id": str(backend.get("backend_id") or backend.get("id") or backend.get("model_name") or backend_type),
            "backend_type": backend_type,
            "model_name": str(backend.get("model_name") or (candidate_report.get("candidate") or {}).get("model_name") or backend_type),
            "model_version": str(backend.get("model_version") or (candidate_report.get("candidate") or {}).get("model_version") or "unversioned"),
            "model_family": str(backend.get("model_family") or (candidate_report.get("candidate") or {}).get("model_family") or "action_conditioned_dynamics"),
            "trainable": bool(backend.get("trainable", backend_type not in {"deterministic_scaffold", "hierarchical_baseline"})),
            "action_conditioned": bool(backend.get("action_conditioned", True)),
            "uses_geofm": bool(backend.get("uses_geofm", (candidate_report.get("candidate") or {}).get("uses_geofm", False))),
            "uses_causal_calibration": bool(backend.get("uses_causal_calibration", (candidate_report.get("candidate") or {}).get("uses_causal_calibration", True))),
            "is_scaffold_baseline": backend_type in {"deterministic_scaffold", "hierarchical_baseline"} or bool((candidate_report.get("candidate") or {}).get("is_scaffold_baseline", False)),
            "metadata": dict(backend.get("metadata") or {}),
        }

    def _raw_backend_candidate_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        for key in ("candidate_report", "dynamics_candidate_report", "fit_report", "dynamics_fit_report"):
            value = payload.get(key)
            if isinstance(value, dict):
                return dict(value)
        candidate = payload.get("dynamics_candidate")
        if isinstance(candidate, dict):
            return {
                "schema": "territory_world_model.external_dynamics_candidate.v1",
                "status": candidate.get("status") or "review",
                "candidate": dict(candidate.get("candidate") or candidate.get("metadata") or {}),
                "predictions": dict(candidate.get("predictions") or {}),
                "learned_parameters": dict(candidate.get("learned_parameters") or {}),
                "evaluation": dict(candidate.get("evaluation") or {}),
                "evidence_gate": dict(candidate.get("evidence_gate") or {}),
            }
        return {}

    def _dynamics_backend_input_contract(self, state_contract: dict[str, Any], backend: dict[str, Any]) -> dict[str, Any]:
        hierarchy = dict(state_contract.get("hierarchy") or {})
        claim = dict(state_contract.get("claim_boundary") or {})
        return {
            "schema": "territory_world_model.dynamics_backend_input_contract.v1",
            "required_inputs": ["current_state", "action", "scenario"],
            "state_contract_status": state_contract.get("status", "review"),
            "state_claim_scope": claim.get("claim_scope", ""),
            "hierarchy_required_levels": [item.get("level") for item in hierarchy.get("tokens") or [] if item.get("required")],
            "missing_required_levels": list(hierarchy.get("missing_required_levels") or []),
            "review_required_levels": list(hierarchy.get("review_required_levels") or []),
            "action_conditioned": bool(backend.get("action_conditioned")),
            "flat_vector_allowed": False,
        }

    def _dynamics_backend_output_contract(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidate_report = self._raw_backend_candidate_report(payload)
        predictions = dict(candidate_report.get("predictions") or payload.get("predictions") or {})
        head_counts = {
            "future_latent_state": 0,
            "constraint_violation_probability": 0,
            "planning_utility_delta": 0,
            "uncertainty": 0,
            "calibration": 0,
            "action_mask": 0,
        }
        for prediction in predictions.values():
            if not isinstance(prediction, dict):
                continue
            for head in head_counts:
                if head in prediction:
                    head_counts[head] += 1
        required_heads = ["future_latent_state", "constraint_violation_probability", "planning_utility_delta", "uncertainty"]
        return {
            "schema": "territory_world_model.dynamics_backend_output_contract.v1",
            "required_heads": required_heads,
            "optional_heads": ["calibration", "action_mask"],
            "prediction_count": len(predictions),
            "head_coverage": head_counts,
            "multi_head_ready": bool(predictions) and all(head_counts[head] > 0 for head in required_heads),
            "must_predict": "p(next_state, constraint_state, utility_state | current_state, action, scenario)",
        }

    def _dynamics_backend_adapter_contract(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidate_report = self._raw_backend_candidate_report(payload)
        predictions = dict(candidate_report.get("predictions") or payload.get("predictions") or {})
        return {
            "schema": "territory_world_model.dynamics_backend_adapter_contract.v1",
            "adapter": "candidate_report_forecast_adapter",
            "forecast_consumable": bool(candidate_report and predictions),
            "candidate_report": candidate_report,
            "supported_consumers": ["forecast", "counterfactual_rollout", "beam_plan", "validation_report"],
            "prediction_selection": ["dynamics_prediction_id", "example_id", "action_type", "first_prediction"],
        }

    def _dynamics_backend_gate_results(
        self,
        *,
        backend: dict[str, Any],
        state_contract: dict[str, Any],
        readiness: dict[str, Any],
        input_contract: dict[str, Any],
        output_contract: dict[str, Any],
        adapter_contract: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        candidate_report = self._raw_backend_candidate_report(payload)
        candidate_gate = self._dynamics_candidate_forecast_gate(candidate_report, payload) if candidate_report else {"passed": False, "status": "review", "missing": ["candidate_report"]}
        gates = {
            "state_contract": {
                "passed": state_contract.get("status") in {"pass", "review"},
                "status": state_contract.get("status", "review"),
                "claim_scope": (state_contract.get("claim_boundary") or {}).get("claim_scope"),
            },
            "readiness": {
                "passed": readiness.get("status") == "pass",
                "status": readiness.get("status", "review"),
                "training_scope": readiness.get("training_scope", ""),
            },
            "action_conditioned": {
                "passed": bool(input_contract.get("action_conditioned")),
                "value": bool(input_contract.get("action_conditioned")),
            },
            "multi_head_output": {
                "passed": bool(output_contract.get("multi_head_ready")),
                "head_coverage": dict(output_contract.get("head_coverage") or {}),
            },
            "forecast_adapter": {
                "passed": bool(adapter_contract.get("forecast_consumable")),
                "adapter": adapter_contract.get("adapter", ""),
            },
            "candidate_gate": candidate_gate,
            "non_scaffold_backend": {
                "passed": not bool(backend.get("is_scaffold_baseline")),
                "is_scaffold_baseline": bool(backend.get("is_scaffold_baseline")),
            },
        }
        if backend.get("uses_geofm"):
            geofm_gate = (readiness.get("gate_results") or {}).get("geofm_gate") or {}
            gates["geofm_gate"] = {
                "passed": geofm_gate.get("status") == "pass" or not geofm_gate.get("required", False),
                "status": geofm_gate.get("status", "review"),
            }
        if backend.get("uses_causal_calibration"):
            causal_gate = (readiness.get("gate_results") or {}).get("causal_calibration") or {}
            gates["causal_calibration"] = {
                "passed": causal_gate.get("status") == "pass" or not causal_gate.get("required", False),
                "status": causal_gate.get("status", "review"),
            }
        required = ["state_contract", "readiness", "action_conditioned", "multi_head_output", "forecast_adapter", "candidate_gate", "non_scaffold_backend"]
        if backend.get("uses_geofm"):
            required.append("geofm_gate")
        if backend.get("uses_causal_calibration"):
            required.append("causal_calibration")
        blocked = [name for name in required if not gates[name].get("passed")]
        gates["summary"] = {
            "blocked_gates": blocked,
            "claim_boundary": "forecast_consumable_backend" if not blocked else "adapter_or_review_only",
            "backend_ready": not blocked,
        }
        return gates

    def _dynamics_backend_evidence_gate(self, gate_results: dict[str, Any], backend: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
        blocked = list((gate_results.get("summary") or {}).get("blocked_gates") or [])
        hard = {"state_contract", "action_conditioned", "multi_head_output", "forecast_adapter", "candidate_gate"}
        status = "pass" if not blocked else "blocked" if any(item in hard for item in blocked) else "review"
        missing = []
        for item in blocked:
            if item not in missing:
                missing.append(item)
        return {
            "passed": not blocked,
            "blocked": status == "blocked",
            "status": status,
            "missing": missing,
            "backend_id": backend.get("backend_id", ""),
            "readiness_status": readiness.get("status", "review"),
        }

    def _dynamics_backend_claim_boundary(self, gate_results: dict[str, Any], backend: dict[str, Any], evidence_gate: dict[str, Any]) -> dict[str, Any]:
        status = "pass" if evidence_gate.get("status") == "pass" else "blocked" if evidence_gate.get("status") == "blocked" else "review"
        return {
            "status": status,
            "claim_scope": "backend_can_drive_forecast_rollout_and_beam" if status == "pass" else "backend_review_only" if status == "review" else "backend_not_consumable",
            "allowed_claims": [
                "backend_contract_checked",
                "candidate_report_adapter_available",
            ]
            + (["forecast_backend_candidate"] if status == "pass" else []),
            "disallowed_claims": [
                "production_ready_world_model",
                "ungated_trainable_dynamics",
            ]
            + (["trainable_backend"] if backend.get("is_scaffold_baseline") else []),
            "blocked_gates": list((gate_results.get("summary") or {}).get("blocked_gates") or []),
        }

    def _dynamics_backend_recommendations(self, gate_results: dict[str, Any], evidence_gate: dict[str, Any], backend: dict[str, Any]) -> list[str]:
        blocked = set((gate_results.get("summary") or {}).get("blocked_gates") or [])
        recommendations: list[str] = []
        if "state_contract" in blocked:
            recommendations.append("fix hierarchical state contract before attaching a dynamics backend")
        if "readiness" in blocked:
            recommendations.append("use backend outputs as review-only until dynamics readiness passes")
        if "action_conditioned" in blocked:
            recommendations.append("backend must condition predictions on current_state, action and scenario")
        if "multi_head_output" in blocked:
            recommendations.append("backend must output future_latent_state, constraint_violation_probability, planning_utility_delta and uncertainty")
        if "forecast_adapter" in blocked or "candidate_gate" in blocked:
            recommendations.append("provide a passed candidate report with forecast-consumable prediction ids")
        if "non_scaffold_backend" in blocked:
            recommendations.append("do not claim trainable dynamics from a deterministic scaffold or transparent baseline alone")
        if backend.get("uses_geofm") and "geofm_gate" in blocked:
            recommendations.append("keep GeoFM features gated until downstream planning lift passes")
        if backend.get("uses_causal_calibration") and "causal_calibration" in blocked:
            recommendations.append("attach a passing causal calibration report before upgrading counterfactual utility claims")
        if not recommendations:
            recommendations.append("backend is forecast-consumable; validate it through counterfactual rollout and beam planning before deployment")
        return recommendations

    def _training_objective_predictions(
        self,
        dataset: dict[str, Any],
        payload: dict[str, Any],
        backend_report: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        explicit_predictions = payload.get("predictions")
        if isinstance(explicit_predictions, dict):
            return {str(key): dict(value) for key, value in explicit_predictions.items() if isinstance(value, dict)}
        candidate_report = self._candidate_report_from_backend_report(backend_report)
        if candidate_report:
            return dict(candidate_report.get("predictions") or {})
        return self._dynamics_predictions_for_evaluation(dataset, payload)

    def _training_objective_contract(self, dataset: dict[str, Any], backend_report: dict[str, Any]) -> dict[str, Any]:
        summary = dict(dataset.get("summary") or {})
        backend = dict(backend_report.get("backend") or {})
        return {
            "schema": "territory_world_model.training_objective_contract.v1",
            "loss_contract": dict(summary.get("loss_contract") or {}),
            "backend_status": backend_report.get("status", "review"),
            "backend_id": backend.get("backend_id") or backend.get("model_name") or "",
            "backend_type": backend.get("backend_type", ""),
            "multi_head_required": [
                "future_latent_state",
                "constraint_violation_probability",
                "planning_utility_delta",
                "uncertainty",
                "calibration",
                "action_mask",
            ],
            "training_claim": "review_only" if backend_report.get("status") != "pass" else "objective_contract_ready",
        }

    def _training_objective_loss_components(
        self,
        dataset: dict[str, Any],
        predictions: dict[str, dict[str, Any]],
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
        total = len(examples)
        transition_count = 0
        constraint_count = 0
        utility_count = 0
        uncertainty_count = 0
        calibration_count = 0
        evidence_supported_count = 0
        action_mask_count = 0
        for example in examples:
            example_id = str(example.get("id") or "")
            targets = dict(example.get("targets") or {})
            labels = dict(example.get("labels") or {})
            pred = dict(predictions.get(example_id) or {})
            if targets.get("future_latent_state") and pred.get("future_latent_state"):
                transition_count += 1
            if "constraint_violation_probability" in targets and "constraint_violation_probability" in pred:
                constraint_count += 1
            if "planning_utility_delta" in targets and "planning_utility_delta" in pred:
                utility_count += 1
            if (targets.get("uncertainty") or {}).get("confidence") is not None and (pred.get("uncertainty") or {}).get("confidence") is not None:
                uncertainty_count += 1
            if targets.get("calibration") and pred.get("calibration"):
                calibration_count += 1
            if labels.get("evidence_supported") is True:
                evidence_supported_count += 1
            if targets.get("action_mask") and pred.get("action_mask"):
                action_mask_count += 1
        transition_loss = float(metrics.get("mean_transition_error") or 0.0)
        constraint_loss = float(metrics.get("mean_constraint_error") or 0.0)
        utility_loss = float(metrics.get("mean_utility_error") or 0.0)
        ranking_loss = round(max(0.0, 1.0 - float(metrics.get("ranking_correlation_proxy") or 0.0)), 6)
        uncertainty_loss = self._training_objective_uncertainty_loss(dataset, predictions)
        calibration_loss = self._training_objective_calibration_loss(dataset, predictions)
        evidence_loss = round(max(0.0, 1.0 - (evidence_supported_count / max(1, total))), 6) if total else None
        action_mask_loss = None
        if action_mask_count:
            accuracy = metrics.get("action_mask_accuracy")
            action_mask_loss = round(max(0.0, 1.0 - float(accuracy or 0.0)), 6) if accuracy is not None else None
        return {
            "transition_loss": {
                "value": round(transition_loss, 6) if transition_count else None,
                "coverage": transition_count,
                "coverage_ratio": round(transition_count / max(1, total), 4) if total else 0.0,
                "weight": 1.0,
            },
            "constraint_loss": {
                "value": round(constraint_loss, 6) if constraint_count else None,
                "coverage": constraint_count,
                "coverage_ratio": round(constraint_count / max(1, total), 4) if total else 0.0,
                "weight": 1.0,
            },
            "planning_ranking_loss": {
                "value": ranking_loss if utility_count else None,
                "coverage": utility_count,
                "coverage_ratio": round(utility_count / max(1, total), 4) if total else 0.0,
                "weight": 1.2,
            },
            "calibration_loss": {
                "value": calibration_loss,
                "coverage": calibration_count,
                "coverage_ratio": round(calibration_count / max(1, total), 4) if total else 0.0,
                "weight": 0.8,
            },
            "uncertainty_calibration_loss": {
                "value": uncertainty_loss,
                "coverage": uncertainty_count,
                "coverage_ratio": round(uncertainty_count / max(1, total), 4) if total else 0.0,
                "weight": 0.8,
            },
            "evidence_consistency_loss": {
                "value": evidence_loss,
                "coverage": total,
                "coverage_ratio": 1.0 if total else 0.0,
                "weight": 0.6,
            },
            "action_mask_loss": {
                "value": action_mask_loss,
                "coverage": action_mask_count,
                "coverage_ratio": round(action_mask_count / max(1, total), 4) if total else 0.0,
                "weight": 0.9,
            },
        }

    def _training_objective_uncertainty_loss(self, dataset: dict[str, Any], predictions: dict[str, dict[str, Any]]) -> float | None:
        diffs: list[float] = []
        for example in dataset.get("examples") or []:
            if not isinstance(example, dict):
                continue
            example_id = str(example.get("id") or "")
            targets = dict(example.get("targets") or {})
            target_uncertainty = dict(targets.get("uncertainty") or {})
            pred_uncertainty = dict((predictions.get(example_id) or {}).get("uncertainty") or {})
            if "confidence" not in target_uncertainty or "confidence" not in pred_uncertainty:
                continue
            diffs.append(abs(float(safe_float(pred_uncertainty.get("confidence"), 0.0) or 0.0) - float(safe_float(target_uncertainty.get("confidence"), 0.0) or 0.0)))
        return round(self._mean(diffs), 6) if diffs else None

    def _training_objective_calibration_loss(self, dataset: dict[str, Any], predictions: dict[str, dict[str, Any]]) -> float | None:
        diffs: list[float] = []
        for example in dataset.get("examples") or []:
            if not isinstance(example, dict):
                continue
            example_id = str(example.get("id") or "")
            targets = dict(example.get("targets") or {})
            pred = dict(predictions.get(example_id) or {})
            target_cal = dict(targets.get("calibration") or {})
            pred_cal = dict(pred.get("calibration") or {})
            target_value = safe_float(target_cal.get("calibrated_utility_delta"), None)
            if target_value is None:
                target_value = safe_float(target_cal.get("observed_transition_proxy"), None)
            pred_value = safe_float(pred_cal.get("calibrated_utility_delta"), None)
            if target_value is None or pred_value is None:
                continue
            diffs.append(abs(float(pred_value) - float(target_value)))
        return round(self._mean(diffs), 6) if diffs else None

    def _training_objective_ranking_diagnostics(
        self,
        dataset: dict[str, Any],
        predictions: dict[str, dict[str, Any]],
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        pairs = []
        for example in dataset.get("examples") or []:
            if not isinstance(example, dict):
                continue
            example_id = str(example.get("id") or "")
            labels = dict(example.get("labels") or {})
            prediction = dict(predictions.get(example_id) or {})
            utility = safe_float(prediction.get("planning_utility_delta"), None)
            rank = safe_float(labels.get("ranking_score"), None)
            if utility is None or rank is None:
                continue
            pairs.append(
                {
                    "example_id": example_id,
                    "predicted_utility": round(float(utility), 6),
                    "target_ranking_score": round(float(rank), 6),
                    "delta": round(float(utility) - float(rank), 6),
                }
            )
        pairs.sort(key=lambda item: abs(item["delta"]), reverse=True)
        return {
            "ranking_correlation_proxy": metrics.get("ranking_correlation_proxy"),
            "pair_count": len(pairs),
            "largest_mismatches": pairs[:5],
            "objective": "maximize planning utility while preserving ranking consistency against target_ranking_score",
        }

    def _training_objective_calibration_diagnostics(
        self,
        dataset: dict[str, Any],
        predictions: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        rows = []
        for example in dataset.get("examples") or []:
            if not isinstance(example, dict):
                continue
            example_id = str(example.get("id") or "")
            targets = dict(example.get("targets") or {})
            pred = dict(predictions.get(example_id) or {})
            target_cal = dict(targets.get("calibration") or {})
            pred_cal = dict(pred.get("calibration") or {})
            target_value = safe_float(target_cal.get("calibrated_utility_delta"), None)
            if target_value is None:
                target_value = safe_float(target_cal.get("observed_transition_proxy"), None)
            pred_value = safe_float(pred_cal.get("calibrated_utility_delta"), None)
            if target_value is None or pred_value is None:
                continue
            rows.append(abs(float(pred_value) - float(target_value)))
        return {
            "mean_absolute_calibration_gap": round(self._mean(rows), 6) if rows else None,
            "calibration_pair_count": len(rows),
            "objective": "align calibrated utility with observed_transition_proxy or calibrated_utility_delta targets",
        }

    def _training_objective_evidence_gate(
        self,
        backend_report: dict[str, Any],
        objective_contract: dict[str, Any],
        loss_components: dict[str, Any],
    ) -> dict[str, Any]:
        missing = []
        backend_status = str(backend_report.get("status") or "review")
        if backend_status != "pass":
            missing.append("backend_pass")
        for key in ("transition_loss", "constraint_loss", "planning_ranking_loss"):
            component = dict(loss_components.get(key) or {})
            if component.get("value") is None or int(component.get("coverage") or 0) == 0:
                missing.append(key)
        status = "pass" if not missing else "review"
        return {
            "passed": not missing,
            "status": status,
            "missing": missing,
            "backend_status": backend_status,
            "training_claim": objective_contract.get("training_claim", "review_only"),
        }

    def _training_objective_recommendations(
        self,
        loss_components: dict[str, Any],
        evidence_gate: dict[str, Any],
        backend_report: dict[str, Any],
    ) -> list[str]:
        recommendations: list[str] = []
        if evidence_gate.get("status") != "pass":
            recommendations.append("treat the training objective as review-only until a passed dynamics backend is attached")
        for key, text in (
            ("transition_loss", "increase observed future-state labels for transition supervision"),
            ("constraint_loss", "expand constraint-state labels and high-risk rule coverage"),
            ("planning_ranking_loss", "add candidate ranking labels and counterfactual planning comparisons"),
            ("calibration_loss", "connect calibration targets to causal or observed transition evidence"),
            ("uncertainty_calibration_loss", "record prediction confidence against observed error to calibrate uncertainty"),
        ):
            component = dict(loss_components.get(key) or {})
            if component.get("value") is None or int(component.get("coverage") or 0) == 0:
                recommendations.append(text)
        if backend_report.get("status") == "pass":
            recommendations.append("use this objective report as the loss contract for the first trainable dynamics trainer")
        return recommendations

    def _dynamics_candidate_forecast_gate(self, candidate_report: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        required_status = str(payload.get("dynamics_candidate_required_status") or "pass")
        report_status = str(candidate_report.get("status") or "")
        evidence_gate = dict(candidate_report.get("evidence_gate") or {})
        evaluation = dict(candidate_report.get("evaluation") or {})
        evaluation_gate = dict(evaluation.get("evidence_gate") or {})
        candidate = dict(candidate_report.get("candidate") or {})
        missing: list[str] = []
        if required_status == "pass" and report_status != "pass":
            missing.append("dynamics_candidate_pass")
        if evidence_gate and evidence_gate.get("status") not in {"pass", "passed", True}:
            missing.append("dynamics_candidate_evidence_gate")
        if evaluation and evaluation.get("status") != "pass":
            missing.append("dynamics_candidate_evaluation")
        if evaluation_gate and evaluation_gate.get("status") != "pass":
            missing.append("dynamics_candidate_evaluation_gate")
        active_registry: dict[str, Any] | None = None
        registry_required = truthy(payload.get("require_active_dynamics_registry"))
        if registry_required:
            state_version_id = compact_text(payload.get("_state_version_id") or payload.get("state_version_id") or "")
            active_entry = self.repository.get_active_dynamics_model_registry_entry(state_version_id) if state_version_id else None
            if active_entry is None:
                missing.append("active_dynamics_model_registry")
            else:
                active_registry = active_entry.to_dict()
                candidate_key = f"{compact_text(candidate.get('model_name') or '')}:{compact_text(candidate.get('model_version') or '')}"
                if candidate_key != active_entry.registry_key:
                    missing.append("dynamics_candidate_active_registry_match")
        allow_review = bool(payload.get("allow_review_dynamics_candidate", False))
        passed = not missing or (allow_review and report_status in {"review", "pass"})
        gate = {
            "passed": passed,
            "status": "pass" if passed else "review",
            "missing": [] if passed else missing,
            "required_status": required_status,
            "report_status": report_status,
            "registry_required": registry_required,
        }
        if active_registry is not None:
            gate["active_registry_entry"] = active_registry
        return gate

    def _select_candidate_prediction(self, candidate_report: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        explicit = payload.get("dynamics_candidate_prediction")
        if isinstance(explicit, dict):
            return dict(explicit)
        predictions = dict(candidate_report.get("predictions") or {})
        if not predictions:
            learned = dict(candidate_report.get("learned_parameters") or {})
            if learned:
                return self._prediction_from_learned_parameters_for_action(learned, payload)
            return {}
        key = str(payload.get("dynamics_prediction_id") or payload.get("example_id") or "")
        if key and isinstance(predictions.get(key), dict):
            return dict(predictions[key])
        if key:
            return {}
        candidate_id = str(payload.get("target_prediction_action_type") or payload.get("action_type") or "")
        for prediction in predictions.values():
            if not isinstance(prediction, dict):
                continue
            action = dict(prediction.get("action") or {})
            if candidate_id and str(action.get("action_type") or "") == candidate_id:
                return dict(prediction)
        first = next((item for item in predictions.values() if isinstance(item, dict)), {})
        return dict(first)

    def _prediction_from_learned_parameters_for_action(self, learned_parameters: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        action_type = str(payload.get("action_type") or "unknown")
        action_parameters = dict(learned_parameters.get("action_parameters") or {})
        params = dict(action_parameters.get(action_type) or learned_parameters.get("global_parameters") or {})
        if not params:
            return {}
        return {
            "future_latent_state": {
                "schema": "territory_world_model.predicted_latent_state.v1",
                "projected": {
                    "projected_risk_pressure": round(float(params.get("constraint_mean") or 0.0), 6),
                    "projected_utility_delta": round(float(params.get("utility_mean") or 0.0), 6),
                },
            },
            "constraint_violation_probability": round(float(params.get("constraint_mean") or 0.0), 6),
            "planning_utility_delta": round(float(params.get("utility_mean") or 0.0), 6),
            "uncertainty": {
                "confidence": round(float(params.get("confidence_mean") or 0.0), 6),
                "source": "hierarchical_baseline_dynamics_parameters",
            },
            "calibration": {
                "calibrated_utility_delta": round(float(params.get("utility_mean") or 0.0), 6),
                "source": "hierarchical_baseline_dynamics_parameters",
            },
        }

    def _apply_candidate_prediction_to_forecast(
        self,
        forecast: dict[str, Any],
        prediction: dict[str, Any],
        candidate_summary: dict[str, Any],
    ) -> None:
        if "future_latent_state" in prediction:
            candidate_latent = dict(prediction.get("future_latent_state") or {})
            base_latent = dict(forecast.get("future_latent_state") or {})
            base_latent["dynamics_candidate_projection"] = candidate_latent
            projected = dict(base_latent.get("projected") or {})
            candidate_projected = dict(candidate_latent.get("projected") or candidate_latent.get("observed_next") or {})
            if "projected_risk_pressure" in candidate_projected:
                projected["projected_risk_pressure"] = candidate_projected["projected_risk_pressure"]
            if "projected_utility_delta" in candidate_projected:
                projected["projected_utility_delta"] = candidate_projected["projected_utility_delta"]
            projected["dynamics_candidate_applied"] = True
            base_latent["projected"] = projected
            forecast["future_latent_state"] = base_latent
        if "constraint_violation_probability" in prediction:
            forecast["constraint_violation_probability"] = round(float(safe_float(prediction.get("constraint_violation_probability"), 0.0) or 0.0), 6)
        if "planning_utility_delta" in prediction:
            forecast["planning_utility_delta"] = round(float(safe_float(prediction.get("planning_utility_delta"), 0.0) or 0.0), 6)
        if "uncertainty" in prediction:
            forecast["uncertainty"] = dict(forecast.get("uncertainty") or {}) | dict(prediction.get("uncertainty") or {})
        if "calibration" in prediction:
            forecast["calibration"] = dict(forecast.get("calibration") or {}) | dict(prediction.get("calibration") or {})
        forecast["calibration"] = dict(forecast.get("calibration") or {}) | {
            "dynamics_backend": candidate_summary,
        }

    def _action_mask_confidence(
        self,
        *,
        target_summary: dict[str, Any],
        blocking_hits: list[dict[str, Any]],
        required_reviews: list[dict[str, Any]],
        missing_evidence_hits: list[str],
    ) -> float:
        confidence = 0.82
        if not target_summary.get("target_scope_valid"):
            confidence -= 0.35
        confidence -= min(0.3, len(blocking_hits) * 0.12)
        confidence -= min(0.2, len(required_reviews) * 0.04)
        confidence -= min(0.18, len(missing_evidence_hits) * 0.04)
        return round(max(0.0, min(1.0, confidence)), 4)

    def _causal_records_for_calibration(self, state_version_id: str, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        raw_records = payload.get("records") or payload.get("observations") or []
        if isinstance(raw_records, list) and raw_records:
            return [dict(item) for item in raw_records if isinstance(item, dict)], "payload_observations"

        observed_history_records = self._causal_records_from_observed_history_payload(payload)
        if observed_history_records:
            return observed_history_records, "observed_approval_review_history"

        state_records = self._causal_records_from_state_objects(state_version_id)
        if state_records:
            return state_records, "state_object_observations"

        dataset = self.dynamics_training_examples(
            state_version_id,
            {
                "scenario": payload.get("scenario") or "causal_calibration_scaffold",
                "evidence_coverage": payload.get("evidence_coverage"),
                "horizon": payload.get("horizon") or 2,
            },
        )
        records: list[dict[str, Any]] = []
        for idx, example in enumerate(dataset.get("examples") or []):
            if not isinstance(example, dict):
                continue
            labels = dict(example.get("labels") or {})
            action = dict(example.get("action") or {})
            targets = dict(example.get("targets") or {})
            ranking_score = safe_float(labels.get("ranking_score"), 0.0) or 0.0
            treatment = 1 if action.get("treatment") or action.get("action_type") in {"protect", "synthetic_transition", "observed_transition"} else 0
            records.append(
                {
                    "unit_id": example.get("id") or f"example:{idx}",
                    "treatment": treatment,
                    "outcome": ranking_score,
                    "model_effect": safe_float((targets.get("calibration") or {}).get("treatment_effect"), 0.0) or 0.0,
                    "stratum": example.get("sample_type") or "unknown",
                    "synthetic": "synthetic_temporal_transition" in (example.get("not_for_training_reasons") or []),
                    "not_for_production": bool(example.get("not_for_training_reasons")),
                    "source": labels.get("supervision_source") or "dynamics_training_examples",
                }
        )
        return records, "dynamics_training_examples_scaffold"

    def _causal_record_inventory(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        source_paths = sorted({str(row.get("source_path")) for row in records if row.get("source_path")})
        source_names = sorted({str(row.get("source")) for row in records if row.get("source")})
        clusters = sorted({str(row.get("cluster") or row.get("spatial_cluster")) for row in records if row.get("cluster") or row.get("spatial_cluster")})
        strata = sorted({str(row.get("stratum")) for row in records if row.get("stratum")})
        treated_count = 0
        control_count = 0
        invalid_treatment_count = 0
        outcome_count = 0
        covariate_keys: set[str] = set()
        neighbor_record_count = 0
        coordinate_record_count = 0
        spatial_record_count = 0
        model_effect_count = 0
        for row in records:
            treatment = self._binary_treatment(row.get("treatment"))
            if treatment == 1:
                treated_count += 1
            elif treatment == 0:
                control_count += 1
            else:
                invalid_treatment_count += 1
            if safe_float(row.get("outcome"), None) is not None:
                outcome_count += 1
            if safe_float(row.get("model_effect"), None) is not None:
                model_effect_count += 1
            raw_covariates = row.get("covariates")
            if isinstance(raw_covariates, dict):
                covariate_keys.update(str(key) for key, value in raw_covariates.items() if safe_float(value, None) is not None)
            neighbors = row.get("neighbors") or row.get("neighbor_unit_ids") or []
            has_neighbors = False
            if isinstance(neighbors, (list, tuple, set)) and neighbors:
                neighbor_record_count += 1
                has_neighbors = True
            if isinstance(neighbors, str) and neighbors.strip():
                neighbor_record_count += 1
                has_neighbors = True
            x = safe_float(row.get("x"), safe_float(row.get("lon"), safe_float(row.get("longitude"), None)))
            y = safe_float(row.get("y"), safe_float(row.get("lat"), safe_float(row.get("latitude"), None)))
            has_coordinates = x is not None and y is not None
            has_cluster = bool(row.get("cluster") or row.get("spatial_cluster"))
            if x is not None and y is not None:
                coordinate_record_count += 1
            if has_cluster or has_neighbors or has_coordinates:
                spatial_record_count += 1
        record_count = len(records)
        return {
            "schema": "territory_world_model.causal_record_inventory.v1",
            "record_count": record_count,
            "source_count": len(source_names),
            "sources": source_names[:12],
            "source_path_count": len(source_paths),
            "source_paths": source_paths[:12],
            "treated_count": treated_count,
            "control_count": control_count,
            "invalid_treatment_count": invalid_treatment_count,
            "outcome_count": outcome_count,
            "model_effect_count": model_effect_count,
            "synthetic_record_count": sum(1 for row in records if truthy(row.get("synthetic"))),
            "not_for_production_record_count": sum(1 for row in records if truthy(row.get("not_for_production"))),
            "cluster_count": len(clusters),
            "clusters": clusters[:12],
            "stratum_count": len(strata),
            "strata": strata[:12],
            "neighbor_record_count": neighbor_record_count,
            "coordinate_record_count": coordinate_record_count,
            "spatial_support": {
                "has_clusters": bool(clusters),
                "has_neighbor_links": neighbor_record_count > 0,
                "has_coordinates": coordinate_record_count > 0,
                "spatial_record_count": spatial_record_count,
            },
            "covariate_count": len(covariate_keys),
            "covariate_keys": sorted(covariate_keys)[:24],
        }

    def _causal_records_from_observed_history_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        raw = (
            payload.get("observed_history")
            or payload.get("approval_review_history")
            or payload.get("approval_history")
            or payload.get("observed_approval_history")
        )
        if isinstance(raw, list):
            rows.extend({**dict(item), "_source": "payload_observed_history"} for item in raw if isinstance(item, dict))
        elif isinstance(raw, dict):
            for key in ("records", "observations", "approval_records", "approval_review_history", "rows"):
                values = raw.get(key)
                if isinstance(values, list):
                    rows.extend({**dict(item), "_source": f"payload_observed_history.{key}"} for item in values if isinstance(item, dict))

        for path_key in ("observed_history_path", "approval_review_history_path", "approval_history_path", "observed_approval_history_path"):
            path_value = payload.get(path_key)
            if not path_value:
                continue
            path = Path(str(path_value)).expanduser()
            for item in read_csv(path):
                rows.append({**dict(item), "_source": path_key, "_source_path": str(path)})

        return self._causal_records_from_observed_history_rows(rows)

    def _causal_records_from_observed_history_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for idx, row in enumerate(rows):
            treatment, treatment_source = self._causal_history_treatment(row)
            if treatment is None:
                continue
            outcome, outcome_source, outcome_components = self._causal_history_outcome(row, treatment=treatment)
            if outcome is None:
                continue
            project_id = compact_text(self._mapping_attr(row, "project_id", "XMDM", "xmdm", "project_code"))
            approval_id = compact_text(self._mapping_attr(row, "approval_id", "record_id", "id", "AJBH", "approval_no", "approval_code"))
            unit_id = (
                compact_text(self._mapping_attr(row, "unit_id", "causal_unit_id", "sample_id"))
                or project_id
                or approval_id
                or f"observed-history:{idx}"
            )
            source_path = compact_text(self._mapping_attr(row, "_source_path", "source_path"))
            risk_score = safe_float(outcome_components.get("risk_score"), safe_float(self._mapping_attr(row, "risk_score"), 0.0)) or 0.0
            covariates = self._causal_history_covariates(row)
            if risk_score and "baseline_risk_score" not in covariates:
                covariates.setdefault("risk_score", float(risk_score))
            record: dict[str, Any] = {
                "unit_id": unit_id,
                "treatment": treatment,
                "outcome": outcome,
                "model_effect": safe_float(self._mapping_attr(row, "model_effect", "expected_model_effect", "rollout_effect"), None),
                "stratum": compact_text(self._mapping_attr(row, "stratum", "region_code", "county_code", "DKXZQDM", "XZQDM")) or "observed_approval_history",
                "cluster": compact_text(
                    self._mapping_attr(row, "cluster", "spatial_cluster", "block_id", "township_id", "region_code", "county_code", "DKXZQDM", "XZQDM")
                ),
                "covariates": covariates,
                "evidence_weight": max(0.0, float(safe_float(self._mapping_attr(row, "evidence_weight", "weight"), 0.95) or 0.95)),
                "synthetic": truthy(self._mapping_attr(row, "synthetic")),
                "not_for_production": truthy(self._mapping_attr(row, "not_for_production", "not_for_prod")),
                "source": "observed_approval_review_history",
                "record_source": "observed_approval_review_history",
                "source_path": source_path,
                "source_row_index": idx,
                "source_record_id": approval_id or unit_id,
                "project_id": project_id,
                "approval_id": approval_id,
                "treatment_source": treatment_source,
                "outcome_source": outcome_source,
                "outcome_components": outcome_components,
            }
            propensity = safe_float(self._mapping_attr(row, "propensity_score", "treatment_probability"), None)
            if propensity is not None:
                record["propensity_score"] = float(propensity)
            x = safe_float(self._mapping_attr(row, "x", "lon", "longitude"), None)
            y = safe_float(self._mapping_attr(row, "y", "lat", "latitude"), None)
            if x is not None and y is not None:
                record["x"] = float(x)
                record["y"] = float(y)
            neighbors = self._causal_history_neighbors(row)
            if neighbors:
                record["neighbors"] = neighbors
            records.append(record)
        return records

    def _causal_history_treatment(self, row: dict[str, Any]) -> tuple[int | None, str]:
        explicit = self._binary_treatment(self._mapping_attr(row, "treatment", "treated", "intervention"))
        if explicit is not None:
            return explicit, "observed_history.treatment"
        status = compact_text(
            self._mapping_attr(row, "approval_status", "decision_result", "DKZT", "status", "task_status", "review_result")
        ).lower()
        treated = {
            "approved",
            "approved_with_conditions",
            "conditional_approval",
            "conditional",
            "granted",
            "pass",
            "passed",
        }
        control = {
            "proposed",
            "in_review",
            "pending",
            "open",
            "returned",
            "rejected",
            "denied",
            "supplement_required",
            "requires_supplementary_evidence",
            "hit_requires_review",
        }
        if status in treated:
            return 1, "observed_history.approval_status"
        if status in control:
            return 0, "observed_history.approval_status"
        approved_area = safe_float(self._mapping_attr(row, "approved_area_m2", "ZDZMJ"), None)
        if approved_area is not None:
            return (1 if float(approved_area) > 0 else 0), "observed_history.approved_area_m2"
        return None, "missing"

    def _causal_history_outcome(self, row: dict[str, Any], *, treatment: int) -> tuple[float | None, str, dict[str, Any]]:
        for field_name in (
            "outcome",
            "planning_utility_delta",
            "utility_delta",
            "ranking_score",
            "observed_utility_delta",
            "reviewed_planning_utility_delta",
        ):
            value = safe_float(self._mapping_attr(row, field_name), None)
            if value is not None:
                return round(float(value), 6), f"observed_history.{field_name}", self._causal_history_outcome_components(row)

        area = safe_float(self._mapping_attr(row, "area_m2", "planned_area_m2", "DKMJ", "ZYZMJ", "geom_area_m2"), None)
        approved_area = safe_float(self._mapping_attr(row, "approved_area_m2", "ZDZMJ"), None)
        if approved_area is None:
            approved_area = float(area or 0.0) if treatment else 0.0
        approved_ratio = 1.0 if treatment and not area else 0.0
        if area is not None and float(area) > 0:
            approved_ratio = max(0.0, min(1.0, float(approved_area or 0.0) / max(1.0, float(area))))
        risk_score = self._causal_history_risk_score(row)
        review_penalty = self._causal_history_review_penalty(row)
        utility = 0.18 + 0.42 * approved_ratio + 0.18 * treatment - 0.50 * risk_score - 0.12 * review_penalty
        components = self._causal_history_outcome_components(row)
        components.update(
            {
                "approved_area_ratio": round(approved_ratio, 6),
                "risk_score": round(risk_score, 6),
                "review_penalty": round(review_penalty, 6),
            }
        )
        return round(max(-1.0, min(1.0, utility)), 6), "observed_history.approval_area_rule_risk_review_proxy", components

    def _causal_history_outcome_components(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "risk_score": round(self._causal_history_risk_score(row), 6),
            "review_penalty": round(self._causal_history_review_penalty(row), 6),
            "rule_hit_count": safe_int(self._mapping_attr(row, "rule_hit_count", "high_risk_hit_count"), 0),
            "rule_eval_count": safe_int(self._mapping_attr(row, "rule_eval_count"), 0),
            "review_task_count": safe_int(self._mapping_attr(row, "review_task_count"), 0),
        }

    def _causal_history_covariates(self, row: dict[str, Any]) -> dict[str, float]:
        covariates: dict[str, float] = {}
        raw = row.get("covariates")
        if isinstance(raw, dict):
            for key, value in raw.items():
                numeric = safe_float(value, None)
                if numeric is not None:
                    covariates[str(key)] = float(numeric)
        for key in (
            "area_m2",
            "planned_area_m2",
            "DKMJ",
            "quality_score",
            "baseline_outcome",
            "baseline_risk_score",
            "risk_score",
            "evidence_coverage",
            "rule_hit_count",
            "review_task_count",
        ):
            numeric = safe_float(self._mapping_attr(row, key), None)
            if numeric is not None:
                covariates[key] = float(numeric)
        return covariates

    def _causal_history_risk_score(self, row: dict[str, Any]) -> float:
        explicit = safe_float(
            self._mapping_attr(row, "risk_score", "constraint_risk", "constraint_violation_probability", "violation_probability"),
            None,
        )
        if explicit is not None:
            return max(0.0, min(1.0, float(explicit)))
        severity = compact_text(self._mapping_attr(row, "severity")).lower()
        severity_weight = {
            "blocking": 1.0,
            "critical": 0.9,
            "high": 0.75,
            "medium": 0.45,
            "low": 0.2,
            "info": 0.08,
        }.get(severity, 0.0)
        finding = compact_text(self._mapping_attr(row, "finding_status", "review_result")).lower()
        if finding in {"pass", "passed", "no_hit", "clear", "dismissed"}:
            return min(0.12, severity_weight or 0.12)
        if finding in {"hit_requires_review", "open", "violation", "failed", "requires_review", "suspected_violation_confirmed"}:
            return max(0.25, severity_weight)
        return severity_weight

    def _causal_history_review_penalty(self, row: dict[str, Any]) -> float:
        status = compact_text(self._mapping_attr(row, "task_status", "review_status", "status")).lower()
        decision = compact_text(self._mapping_attr(row, "review_result", "decision")).lower()
        if decision in {"suspected_violation_confirmed", "violation_confirmed", "confirmed"}:
            return 1.0
        if decision in {"requires_supplementary_evidence", "needs_supplement", "supplement_required"}:
            return 0.65
        if status in {"open", "pending", "in_review"} or decision in {"pending"}:
            return 0.45
        if decision in {"dismissed", "approved", "resolved", "no_issue"} or status in {"closed", "resolved", "completed"}:
            return 0.15
        return 0.0

    def _causal_history_neighbors(self, row: dict[str, Any]) -> list[str]:
        raw = self._mapping_attr(row, "neighbors", "neighbor_unit_ids")
        if isinstance(raw, (list, tuple, set)):
            return [str(item) for item in raw if str(item)]
        if isinstance(raw, str):
            return [item.strip() for item in raw.replace(";", ",").split(",") if item.strip()]
        return []

    def _mapping_attr(self, mapping: dict[str, Any], *names: str) -> Any:
        sources: list[dict[str, Any]] = [mapping]
        for nested_key in ("raw_fields", "canonical_fields"):
            nested = mapping.get(nested_key)
            if isinstance(nested, dict):
                sources.append(nested)
        wanted = {str(name) for name in names if name}
        wanted_lower = {name.lower() for name in wanted}
        for source in sources:
            for name in wanted:
                if name in source and source.get(name) not in (None, ""):
                    return source.get(name)
            for key, value in source.items():
                if str(key).lower() in wanted_lower and value not in (None, ""):
                    return value
        return None

    def _causal_records_from_state_objects(self, state_version_id: str) -> list[dict[str, Any]]:
        objects = self.repository.list_state_objects(state_version_id)
        if not objects:
            return []

        object_by_id = {obj.id: obj for obj in objects}
        rule_hits = self.repository.list_rule_hits(state_version_id=state_version_id)
        review_tasks = self.repository.list_review_tasks(state_version_id=state_version_id)
        project_evidence = self._causal_project_evidence_from_state_objects(objects, object_by_id, rule_hits, review_tasks)
        approval_objects = [
            obj
            for obj in objects
            if {obj.canonical_role, obj.source_role, obj.object_type}.intersection({"approval_record", "approval_records"})
        ]
        records: list[dict[str, Any]] = []
        for idx, obj in enumerate(approval_objects):
            treatment = self._causal_approval_treatment(obj)
            if treatment is None:
                continue
            project_id = self._state_object_project_key(obj) or f"approval:{obj.object_code or obj.id}"
            evidence = project_evidence.get(project_id, {})
            outcome, outcome_components = self._causal_approval_outcome(obj, evidence, treatment=treatment)
            synthetic = bool(obj.synthetic or truthy(self._state_object_attr(obj, "synthetic")))
            not_for_production = bool(obj.not_for_production or truthy(self._state_object_attr(obj, "not_for_production")))
            source_roles = set(evidence.get("source_roles") or [])
            if any(str(item).endswith(":synthetic") for item in source_roles):
                synthetic = True
            if any(str(item).endswith(":not_for_production") for item in source_roles):
                not_for_production = True
            area_m2 = safe_float(
                self._state_object_attr(obj, "area_m2", "planned_area_m2", "DKMJ", "ZYZMJ", "geom_area_m2"),
                None,
            )
            approved_area_m2 = safe_float(self._state_object_attr(obj, "approved_area_m2", "ZDZMJ"), None)
            covariates = {
                "area_m2": float(area_m2 or 0.0),
                "approved_area_m2": float(approved_area_m2 or 0.0),
                "approved_area_ratio": float(outcome_components.get("approved_area_ratio") or 0.0),
                "risk_score": float(evidence.get("risk_score") or 0.0),
                "rule_eval_count": float(evidence.get("rule_eval_count") or 0),
                "rule_hit_count": float(evidence.get("rule_hit_count") or 0),
                "review_task_count": float(evidence.get("review_task_count") or 0),
                "quality_score": float(safe_float(obj.quality_score, 0.0) or 0.0),
            }
            district = compact_text(self._state_object_attr(obj, "DKXZQDM", "XZQDM", "region_code", "county_code"))
            records.append(
                {
                    "unit_id": project_id or obj.id or f"state-object:{idx}",
                    "treatment": treatment,
                    "outcome": outcome,
                    "stratum": district or "approval_record",
                    "cluster": district or project_id,
                    "covariates": covariates,
                    "evidence_weight": 0.35 if synthetic or not_for_production else 0.85,
                    "synthetic": synthetic,
                    "not_for_production": not_for_production,
                    "source": "state_object_observations",
                    "record_source": "state_object_observations",
                    "source_object_id": obj.id,
                    "source_object_code": obj.object_code,
                    "source_feature_id": obj.source_feature_id,
                    "source_role": obj.source_role,
                    "canonical_role": obj.canonical_role,
                    "source_path": obj.source_path,
                    "project_id": project_id,
                    "treatment_source": "approval_status_or_approved_area",
                    "outcome_source": "approval_area_rule_risk_review_proxy",
                    "outcome_components": outcome_components,
                    "supporting_rule_eval_ids": list(evidence.get("rule_eval_ids") or [])[:12],
                    "supporting_rule_hit_ids": list(evidence.get("rule_hit_ids") or [])[:12],
                    "supporting_review_task_ids": list(evidence.get("review_task_ids") or [])[:12],
                }
            )
        return records

    def _causal_project_evidence_from_state_objects(
        self,
        objects: list[TwmStateObject],
        object_by_id: dict[str, TwmStateObject],
        rule_hits: list[TwmRuleHit],
        review_tasks: list[TwmReviewTask],
    ) -> dict[str, dict[str, Any]]:
        evidence: dict[str, dict[str, Any]] = {}

        def bucket(project_id: str) -> dict[str, Any]:
            return evidence.setdefault(
                project_id,
                {
                    "risk_scores": [],
                    "review_penalties": [],
                    "rule_eval_ids": [],
                    "rule_hit_ids": [],
                    "review_task_ids": [],
                    "rule_eval_count": 0,
                    "rule_hit_count": 0,
                    "review_task_count": 0,
                    "source_roles": set(),
                },
            )

        for obj in objects:
            role = obj.canonical_role or obj.source_role or obj.object_type
            if role not in {"rule_evaluation", "review_task", "review_tasks"}:
                continue
            project_id = self._state_object_project_key(obj)
            if not project_id:
                continue
            item = bucket(project_id)
            item["source_roles"].add(role)
            if obj.synthetic:
                item["source_roles"].add(f"{role}:synthetic")
            if obj.not_for_production:
                item["source_roles"].add(f"{role}:not_for_production")
            if role == "rule_evaluation":
                item["rule_eval_count"] += 1
                item["rule_eval_ids"].append(obj.object_code or obj.source_feature_id or obj.id)
                item["risk_scores"].append(self._causal_rule_eval_risk(obj))
            else:
                item["review_task_count"] += 1
                item["review_task_ids"].append(obj.object_code or obj.source_feature_id or obj.id)
                item["review_penalties"].append(self._causal_review_task_penalty(obj))

        review_by_hit: dict[str, list[TwmReviewTask]] = {}
        for task in review_tasks:
            if task.rule_hit_id:
                review_by_hit.setdefault(task.rule_hit_id, []).append(task)
        for hit in rule_hits:
            subject = object_by_id.get(hit.subject_object_id or "")
            target = object_by_id.get(hit.target_object_id or "") if hit.target_object_id else None
            project_id = self._state_object_project_key(subject) if subject is not None else ""
            if not project_id and target is not None:
                project_id = self._state_object_project_key(target)
            if not project_id:
                continue
            item = bucket(project_id)
            item["rule_hit_count"] += 1
            item["rule_hit_ids"].append(hit.id)
            item["risk_scores"].append(self._causal_rule_hit_risk(hit))
            for task in review_by_hit.get(hit.id, []):
                item["review_task_count"] += 1
                item["review_task_ids"].append(task.id)
                item["review_penalties"].append(self._causal_review_task_penalty(task))

        for item in evidence.values():
            risk_scores = [float(value) for value in item.get("risk_scores") or [] if value is not None]
            review_penalties = [float(value) for value in item.get("review_penalties") or [] if value is not None]
            item["risk_score"] = round(max(risk_scores) if risk_scores else 0.0, 6)
            item["mean_risk_score"] = round(self._mean(risk_scores), 6) if risk_scores else 0.0
            item["review_penalty"] = round(max(review_penalties) if review_penalties else 0.0, 6)
            item["source_roles"] = sorted(str(value) for value in item.get("source_roles") or [])
        return evidence

    def _state_object_attr(self, obj: TwmStateObject, *names: str) -> Any:
        return self._mapping_attr(dict(obj.attributes or {}), *names)

    def _state_object_project_key(self, obj: TwmStateObject | None) -> str:
        if obj is None:
            return ""
        value = self._state_object_attr(obj, "project_id", "XMDM", "xmdm", "project_code", "linked_object_id")
        if value not in (None, ""):
            return compact_text(value)
        if obj.canonical_role == "project":
            return compact_text(obj.object_code or obj.source_feature_id or obj.id)
        return ""

    def _causal_approval_treatment(self, obj: TwmStateObject) -> int | None:
        raw_status = self._state_object_attr(obj, "approval_status", "decision_result", "DKZT", "status", "task_status")
        status = compact_text(raw_status).lower()
        treated = {
            "approved",
            "approved_with_conditions",
            "conditional_approval",
            "conditional",
            "granted",
            "pass",
        }
        control = {
            "proposed",
            "in_review",
            "pending",
            "open",
            "returned",
            "rejected",
            "denied",
            "supplement_required",
            "requires_supplementary_evidence",
            "hit_requires_review",
        }
        if status in treated:
            return 1
        if status in control:
            return 0
        approved_area = safe_float(self._state_object_attr(obj, "approved_area_m2", "ZDZMJ"), None)
        if approved_area is not None:
            return 1 if float(approved_area) > 0 else 0
        return None

    def _causal_approval_outcome(self, obj: TwmStateObject, evidence: dict[str, Any], *, treatment: int) -> tuple[float, dict[str, Any]]:
        area = safe_float(self._state_object_attr(obj, "area_m2", "planned_area_m2", "DKMJ", "ZYZMJ", "geom_area_m2"), None)
        approved_area = safe_float(self._state_object_attr(obj, "approved_area_m2", "ZDZMJ"), None)
        if approved_area is None:
            approved_area = float(area or 0.0) if treatment else 0.0
        approved_ratio = 0.0
        if area is not None and float(area) > 0:
            approved_ratio = max(0.0, min(1.0, float(approved_area or 0.0) / max(1.0, float(area))))
        elif treatment:
            approved_ratio = 1.0
        risk_score = max(0.0, min(1.0, float(evidence.get("risk_score") or 0.0)))
        review_penalty = max(0.0, min(1.0, float(evidence.get("review_penalty") or 0.0)))
        utility = 0.18 + 0.42 * approved_ratio + 0.18 * treatment - 0.50 * risk_score - 0.12 * review_penalty
        components = {
            "approved_area_ratio": round(approved_ratio, 6),
            "risk_score": round(risk_score, 6),
            "review_penalty": round(review_penalty, 6),
            "rule_eval_count": int(evidence.get("rule_eval_count") or 0),
            "rule_hit_count": int(evidence.get("rule_hit_count") or 0),
            "review_task_count": int(evidence.get("review_task_count") or 0),
        }
        return round(max(-1.0, min(1.0, utility)), 6), components

    def _causal_rule_eval_risk(self, obj: TwmStateObject) -> float:
        status = compact_text(self._state_object_attr(obj, "finding_status", "status")).lower()
        severity = compact_text(self._state_object_attr(obj, "severity")).lower()
        severity_weight = {
            "blocking": 1.0,
            "critical": 0.9,
            "high": 0.75,
            "medium": 0.45,
            "low": 0.2,
            "info": 0.08,
        }.get(severity, 0.25)
        if status in {"pass", "passed", "no_hit", "clear"}:
            return round(min(0.12, severity_weight), 6)
        if status in {"hit_requires_review", "open", "violation", "failed", "requires_review"}:
            return round(severity_weight, 6)
        metric = safe_float(self._state_object_attr(obj, "metric_value"), None)
        if metric is not None and float(metric) > 0:
            return round(max(0.18, severity_weight), 6)
        return round(severity_weight * 0.5, 6)

    def _causal_rule_hit_risk(self, hit: TwmRuleHit) -> float:
        explicit = safe_float(hit.risk_score, None)
        severity = compact_text(hit.severity).lower()
        severity_weight = {
            "blocking": 1.0,
            "critical": 0.9,
            "high": 0.75,
            "medium": 0.45,
            "low": 0.2,
            "info": 0.08,
        }.get(severity, 0.25)
        if explicit is None:
            return severity_weight
        return round(max(0.0, min(1.0, max(float(explicit), severity_weight * 0.5))), 6)

    def _causal_review_task_penalty(self, task: TwmStateObject | TwmReviewTask) -> float:
        if isinstance(task, TwmStateObject):
            status = compact_text(self._state_object_attr(task, "task_status", "status")).lower()
            decision = compact_text(self._state_object_attr(task, "review_result", "decision")).lower()
        else:
            status = compact_text(task.status).lower()
            decision = compact_text(task.decision).lower()
        if decision in {"suspected_violation_confirmed", "violation_confirmed", "confirmed"}:
            return 1.0
        if decision in {"requires_supplementary_evidence", "needs_supplement", "supplement_required"}:
            return 0.65
        if status in {"open", "pending", "in_review"} or decision in {"pending", ""}:
            return 0.45
        if decision in {"dismissed", "approved", "resolved", "no_issue"} or status in {"closed", "resolved", "completed"}:
            return 0.15
        return 0.3

    def _causal_calibration_thresholds(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = dict(payload.get("thresholds") or {})
        return {
            "min_records": int(raw.get("min_records", 8)),
            "min_treated": int(raw.get("min_treated", 3)),
            "min_control": int(raw.get("min_control", 3)),
            "max_standard_error": float(raw.get("max_standard_error", 0.25)),
            "min_overlap_ratio": float(raw.get("min_overlap_ratio", 0.8)),
            "max_abs_standardized_mean_difference": float(raw.get("max_abs_standardized_mean_difference", 0.35)),
            "min_propensity": float(raw.get("min_propensity", 0.05)),
            "max_neighbor_exposure_gap": float(raw.get("max_neighbor_exposure_gap", 0.35)),
            "max_spatial_cluster_treatment_gap": float(raw.get("max_spatial_cluster_treatment_gap", 0.45)),
            "max_spatial_residual_moran": float(raw.get("max_spatial_residual_moran", 0.35)),
            "spatial_neighbor_distance": safe_float(raw.get("spatial_neighbor_distance"), None),
            "enable_spatial_estimator": bool(raw.get("enable_spatial_estimator", True)),
            "min_spatial_units": int(raw.get("min_spatial_units", 3)),
            "min_spatial_unit_pairs": int(raw.get("min_spatial_unit_pairs", 3)),
            "min_cross_treatment_edges": int(raw.get("min_cross_treatment_edges", 3)),
            "max_spatial_estimator_standard_error": float(raw.get("max_spatial_estimator_standard_error", raw.get("max_standard_error", 0.25))),
            "max_spatial_effect_gap": float(raw.get("max_spatial_effect_gap", 0.25)),
            "spatial_bootstrap_samples": int(raw.get("spatial_bootstrap_samples", 64)),
            "min_spatial_bootstrap_units": int(raw.get("min_spatial_bootstrap_units", raw.get("min_spatial_units", 3))),
            "max_spatial_bootstrap_interval_width": float(raw.get("max_spatial_bootstrap_interval_width", 0.35)),
            "min_spatial_bootstrap_sign_stability": float(raw.get("min_spatial_bootstrap_sign_stability", 0.8)),
            "min_spatial_holdout_units": int(raw.get("min_spatial_holdout_units", raw.get("min_spatial_units", 3))),
            "max_spatial_holdout_delta": float(raw.get("max_spatial_holdout_delta", 0.2)),
            "min_spatial_holdout_sign_agreement": float(raw.get("min_spatial_holdout_sign_agreement", 0.8)),
            "min_evidence_coverage": float(raw.get("min_evidence_coverage", 0.55)),
            "allow_synthetic": bool(raw.get("allow_synthetic", False)),
            "allow_not_for_production": bool(raw.get("allow_not_for_production", False)),
            "calibration_factor_bounds": tuple(raw.get("calibration_factor_bounds", [0.1, 5.0])),
        }

    def _estimate_observational_treatment_effect(self, records: list[dict[str, Any]], *, thresholds: dict[str, Any]) -> dict[str, Any]:
        return estimate_observational_treatment_effect(records, thresholds=thresholds)

    def _causal_calibration_from_estimate(self, estimate: dict[str, Any], model_effect: float | None) -> dict[str, Any]:
        observed_effect = float(estimate.get("att") or 0.0)
        if model_effect is None:
            model_effect = estimate.get("mean_model_effect_from_records")
        if model_effect is None:
            model_effect = 0.0
        model_effect = float(model_effect or 0.0)
        if abs(model_effect) < 1e-9:
            factor = 1.0
            calibrated_effect = observed_effect
            status = "review"
        else:
            factor = observed_effect / model_effect
            factor = max(0.1, min(5.0, factor))
            calibrated_effect = model_effect * factor
            status = "pass"
        return {
            "model_effect": round(model_effect, 6),
            "observed_effect": round(observed_effect, 6),
            "calibration_factor": round(factor, 6),
            "calibrated_effect": round(calibrated_effect, 6),
            "utility_scale_adjustment": round(factor, 6),
            "scenario_scale_adjustment": round(1.0 + max(-0.5, min(0.5, observed_effect)), 6),
            "status": status,
        }

    def _causal_evidence_gate(
        self,
        *,
        records: list[dict[str, Any]],
        estimate: dict[str, Any],
        calibration: dict[str, Any],
        thresholds: dict[str, Any],
        record_source: str,
        scca_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        missing: list[str] = []
        if estimate.get("usable_record_count", 0) < thresholds["min_records"]:
            missing.append("min_records")
        if estimate.get("treated_count", 0) < thresholds["min_treated"]:
            missing.append("min_treated")
        if estimate.get("control_count", 0) < thresholds["min_control"]:
            missing.append("min_control")
        if float(estimate.get("standard_error") or 0.0) > thresholds["max_standard_error"]:
            missing.append("standard_error")
        overlap = dict(estimate.get("overlap") or {})
        if overlap.get("status") != "pass":
            missing.append("overlap")
        balance = dict(estimate.get("balance") or {})
        max_abs_smd = float(balance.get("max_abs_standardized_mean_difference") or 0.0)
        if balance.get("covariate_count", 0) and max_abs_smd > float(thresholds.get("max_abs_standardized_mean_difference") or 0.35):
            missing.append("covariate_balance")
        spatial = dict(estimate.get("spatial") or {})
        if spatial.get("status") == "review":
            missing.append("spatial_interference")
        spatial_estimator = dict(estimate.get("spatial_estimator") or {})
        if (
            spatial_estimator.get("schema") == SPATIAL_CAUSAL_ESTIMATOR_SCHEMA
            and spatial_estimator.get("status") == "review"
            and spatial_estimator.get("support", {}).get("spatial_record_count", 0)
        ):
            missing.append("spatial_estimator")
        if calibration.get("status") != "pass":
            missing.append("model_effect")
        synthetic_count = sum(1 for row in records if truthy(row.get("synthetic")))
        nfp_count = sum(1 for row in records if truthy(row.get("not_for_production")))
        if synthetic_count and not thresholds.get("allow_synthetic"):
            missing.append("synthetic_records")
        if nfp_count and not thresholds.get("allow_not_for_production"):
            missing.append("not_for_production_records")
        scca_status = "not_provided"
        if scca_report:
            scca_status = str((scca_report.get("evidence_gate") or {}).get("status") or scca_report.get("status") or "review")
        passed = not missing
        return {
            "passed": passed,
            "status": "pass" if passed else "review",
            "blocked": False,
            "missing": missing,
            "record_source": record_source,
            "scca_causal_evidence": {
                "provided": bool(scca_report),
                "status": scca_status,
                "used_as_required_gate": False,
            },
            "synthetic_record_count": synthetic_count,
            "not_for_production_record_count": nfp_count,
            "thresholds": thresholds,
        }

    def _causal_calibration_recommendations(
        self,
        evidence_gate: dict[str, Any],
        estimate: dict[str, Any],
        calibration: dict[str, Any],
        record_source: str,
    ) -> list[str]:
        recommendations: list[str] = []
        if evidence_gate.get("status") != "pass":
            recommendations.append("collect balanced treated/control observational records before upgrading causal planning claims")
        if "synthetic_records" in (evidence_gate.get("missing") or []):
            recommendations.append("do not use synthetic temporal transitions as causal ground truth without explicit validation")
        if "not_for_production_records" in (evidence_gate.get("missing") or []):
            recommendations.append("replace demo or not_for_production records with production evidence before deployment")
        if calibration.get("status") != "pass":
            recommendations.append("provide a non-zero model_effect or rollout-derived planning lift for calibration")
        if "overlap" in (evidence_gate.get("missing") or []):
            recommendations.append("improve treated/control overlap or provide propensity-aware observational data before using causal scaling")
        if "covariate_balance" in (evidence_gate.get("missing") or []):
            recommendations.append("reduce treated/control covariate imbalance or add better adjustment covariates before upgrading causal claims")
        if "spatial_interference" in (evidence_gate.get("missing") or []):
            recommendations.append("spatial spillover or clustered treatment concentration is too strong; add spatial adjustment or redefine causal units before upgrading claims")
        if "spatial_estimator" in (evidence_gate.get("missing") or []):
            recommendations.append("spatial treatment-effect estimator did not pass support or uncertainty checks; keep causal scaling in review")
            reasons = set((estimate.get("spatial_estimator") or {}).get("review_reasons") or [])
            if "spatial_bootstrap_uncertainty" in reasons:
                recommendations.append("spatial block bootstrap interval is too wide or sign stability is weak; collect more mixed spatial units")
            if "geographic_holdout_instability" in reasons:
                recommendations.append("leave-one-spatial-unit-out estimates are unstable; validate against geographic holdout before upgrading claims")
        if record_source.endswith("scaffold"):
            recommendations.append("scaffold-derived calibration is review-only; use payload observations or a causal backend for claims")
        if abs(float(estimate.get("att") or 0.0)) < float(estimate.get("standard_error") or 0.0):
            recommendations.append("estimated treatment effect is not clearly separated from uncertainty")
        return recommendations

    def _model_effect_from_rollout(self, state_version_id: str, payload: dict[str, Any]) -> float | None:
        if not payload.get("baseline_action") and not payload.get("intervention_actions") and not payload.get("action_type"):
            return None
        rollout = self.counterfactual_rollout(
            state_version_id,
            {
                "scenario": payload.get("scenario") or "causal_calibration_rollout",
                "horizon": int(payload.get("horizon") or 2),
                "evidence_coverage": payload.get("evidence_coverage"),
                "baseline_action": payload.get("baseline_action") or {"action_type": "inspect", "target_role": payload.get("target_role") or "project"},
                "intervention_actions": payload.get("intervention_actions")
                or [
                    {
                        "action_type": payload.get("action_type") or "protect",
                        "target_role": payload.get("target_role") or "project",
                        "magnitude": payload.get("magnitude") or 1.0,
                        "treatment": payload.get("treatment") or "causal_calibrated",
                        "parameters": dict(payload.get("parameters") or {}),
                    }
                ],
                "scenario_context": _mapping_payload(payload.get("scenario_context")),
            },
        )
        return safe_float(((rollout.get("deltas") or {}).get("final") or {}).get("utility_delta_lift"), None)

    def _binary_treatment(self, value: Any) -> int | None:
        if isinstance(value, bool):
            return 1 if value else 0
        if value in (0, 1):
            return int(value)
        text = str(value).strip().lower()
        if text in {"1", "true", "treated", "intervention", "yes", "y"}:
            return 1
        if text in {"0", "false", "control", "baseline", "no", "n"}:
            return 0
        return None

    def _mean(self, values: list[float]) -> float:
        return sum(values) / max(1, len(values))

    def _geofm_gate_thresholds(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = dict(payload.get("thresholds") or {})
        return {
            "min_planning_lift_delta": float(raw.get("min_planning_lift_delta", 0.03)),
            "max_constraint_risk_delta": float(raw.get("max_constraint_risk_delta", 0.02)),
            "min_confidence_delta": float(raw.get("min_confidence_delta", -0.02)),
            "min_evidence_coverage": float(raw.get("min_evidence_coverage", 0.55)),
            "require_explicit_downstream_metrics": bool(raw.get("require_explicit_downstream_metrics", True)),
            "allow_not_for_production_vectors": bool(raw.get("allow_not_for_production_vectors", False)),
            "require_extended_validation": bool(raw.get("require_extended_validation", False)),
            "min_holdout_planning_lift_delta": float(raw.get("min_holdout_planning_lift_delta", raw.get("min_planning_lift_delta", 0.03))),
            "min_holdout_ranking_score_delta": float(raw.get("min_holdout_ranking_score_delta", 0.02)),
            "min_cross_region_planning_lift_delta": float(raw.get("min_cross_region_planning_lift_delta", 0.02)),
            "min_cross_region_count": safe_int(raw.get("min_cross_region_count"), 2) or 2,
            "max_domain_shift_score": float(raw.get("max_domain_shift_score", 0.25)),
            "max_holdout_regret_delta": float(raw.get("max_holdout_regret_delta", 0.02)),
            "min_temporal_holdout_confidence": float(raw.get("min_temporal_holdout_confidence", 0.55)),
            "min_production_label_quality": float(raw.get("min_production_label_quality", 0.70)),
            "require_architecture_audit": bool(raw.get("require_architecture_audit", False)),
            "min_adapter_capacity_score": float(raw.get("min_adapter_capacity_score", 0.35)),
            "min_architecture_label_quality": float(raw.get("min_architecture_label_quality", raw.get("min_production_label_quality", 0.70))),
            "max_architecture_domain_shift_score": float(raw.get("max_architecture_domain_shift_score", raw.get("max_domain_shift_score", 0.25))),
        }

    def _variant_metrics_from_payload(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        metrics = dict(value)
        uncertainty = dict(metrics.get("uncertainty") or {}) if isinstance(metrics.get("uncertainty"), dict) else {}
        normalized = {
            "planning_lift": float(safe_float(metrics.get("planning_lift"), safe_float(metrics.get("planning_utility_delta"), 0.0)) or 0.0),
            "constraint_risk": float(safe_float(metrics.get("constraint_risk"), safe_float(metrics.get("constraint_violation_probability"), 0.0)) or 0.0),
            "confidence": float(safe_float(metrics.get("confidence"), safe_float(uncertainty.get("confidence"), 0.0)) or 0.0),
            "calibration_gap": float(safe_float(metrics.get("calibration_gap"), 0.0) or 0.0),
            "ranking_score": float(safe_float(metrics.get("ranking_score"), 0.0) or 0.0),
        }
        for key, item in metrics.items():
            if key not in normalized:
                normalized[key] = item
        if not normalized["ranking_score"]:
            normalized["ranking_score"] = round(normalized["planning_lift"] - normalized["constraint_risk"], 4)
        normalized["source"] = metrics.get("source") or "explicit_downstream_evaluation"
        return normalized

    def _infer_geofm_gate_metrics(
        self,
        *,
        state: TwmStateVersion,
        state_bundle: dict[str, Any],
        scenario: str,
        evidence_coverage: float | None,
        vector_inventory: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        rule_hits = self.repository.list_rule_hits(state_version_id=state.id)
        base_action = self._action_from_payload(
            {
                "action_type": payload.get("action_type") or "protect",
                "target_role": payload.get("target_role") or "project",
                "magnitude": payload.get("magnitude") or 1.0,
                "scenario": scenario,
                "description": "B0 GIS-only ablation baseline",
                "legal_intent": "farmland protection compliance",
                "parameters": dict(payload.get("parameters") or {}),
            }
        )
        geofm_action = self._action_from_payload(
            {
                "action_type": payload.get("action_type") or "protect",
                "target_role": payload.get("target_role") or "project",
                "magnitude": payload.get("magnitude") or 1.0,
                "scenario": scenario,
                "description": "B1 GeoFM-augmented ablation candidate",
                "legal_intent": "farmland protection compliance",
                "parameters": {
                    **dict(payload.get("parameters") or {}),
                    "geofm_embedding_available": bool(vector_inventory.get("available")),
                    "geofm_record_count": vector_inventory.get("record_count", 0),
                },
            }
        )
        base_forecast = self.planner.forecast(
            {
                "state_version": state,
                "objects": state_bundle["objects"],
                "relations": state_bundle["relations"],
                "quality_summary": state.quality_summary,
                "warnings": [],
                "hierarchy_tokens": state.summary,
            },
            base_action,
            scenario=scenario,
            rule_hits=rule_hits,
            evidence_coverage=evidence_coverage,
            scenario_context=_mapping_payload(payload.get("scenario_context")),
        )
        geofm_context = _mapping_payload(payload.get("scenario_context"))
        # Availability alone gives only a small candidate prior; explicit downstream
        # metrics are still required before the gate can retain GeoFM.
        if vector_inventory.get("available"):
            geofm_context["observed_treatment_effect"] = float(geofm_context.get("observed_treatment_effect") or 0.0) + 0.015
        geofm_forecast = self.planner.forecast(
            {
                "state_version": state,
                "objects": state_bundle["objects"],
                "relations": state_bundle["relations"],
                "quality_summary": state.quality_summary,
                "warnings": [],
                "hierarchy_tokens": state.summary | {"geofm_vector_inventory": vector_inventory},
            },
            geofm_action,
            scenario=scenario,
            rule_hits=rule_hits,
            evidence_coverage=evidence_coverage,
            scenario_context=geofm_context,
        )
        return {
            "baseline_metrics": self._metrics_from_forecast(base_forecast, source="deterministic_b0_forecast"),
            "augmented_metrics": self._metrics_from_forecast(geofm_forecast, source="deterministic_b1_candidate_prior"),
        }

    def _metrics_from_forecast(self, forecast: TerritoryWorldModelForecast, *, source: str) -> dict[str, Any]:
        planning_lift = float(forecast.planning_utility_delta or 0.0)
        constraint_risk = float(forecast.constraint_violation_probability or 0.0)
        confidence = float((forecast.uncertainty or {}).get("confidence") or 0.0)
        return {
            "planning_lift": round(planning_lift, 4),
            "constraint_risk": round(constraint_risk, 4),
            "confidence": round(confidence, 4),
            "calibration_gap": round(float((forecast.uncertainty or {}).get("calibration_gap") or 0.0), 4),
            "ranking_score": round(planning_lift - constraint_risk, 4),
            "source": source,
        }

    def _variant_evidence_gate(
        self,
        *,
        uses_geofm: bool,
        metrics: dict[str, Any],
        vector_inventory: dict[str, Any],
        evidence_coverage: float | None,
        thresholds: dict[str, Any],
    ) -> dict[str, Any]:
        missing: list[str] = []
        coverage = float(safe_float(evidence_coverage, 0.0) or 0.0)
        if coverage < float(thresholds["min_evidence_coverage"]):
            missing.append("evidence_coverage")
        if uses_geofm and not vector_inventory.get("available"):
            missing.append("geofm_vectors")
        if uses_geofm and vector_inventory.get("not_for_production") and not thresholds.get("allow_not_for_production_vectors"):
            missing.append("geofm_vectors_not_for_production")
        if not metrics:
            missing.append("downstream_metrics")
        passed = not missing
        return {
            "passed": passed,
            "status": "pass" if passed else "review",
            "missing": missing,
            "coverage": round(coverage, 4),
            "uses_geofm": uses_geofm,
        }

    def _geofm_metric_deltas(self, baseline: dict[str, Any], augmented: dict[str, Any]) -> dict[str, Any]:
        planning_delta = float(augmented.get("planning_lift") or 0.0) - float(baseline.get("planning_lift") or 0.0)
        risk_delta = float(augmented.get("constraint_risk") or 0.0) - float(baseline.get("constraint_risk") or 0.0)
        confidence_delta = float(augmented.get("confidence") or 0.0) - float(baseline.get("confidence") or 0.0)
        ranking_delta = float(augmented.get("ranking_score") or 0.0) - float(baseline.get("ranking_score") or 0.0)
        calibration_gap_delta = float(augmented.get("calibration_gap") or 0.0) - float(baseline.get("calibration_gap") or 0.0)
        return {
            "planning_lift_delta": round(planning_delta, 4),
            "constraint_risk_delta": round(risk_delta, 4),
            "confidence_delta": round(confidence_delta, 4),
            "ranking_score_delta": round(ranking_delta, 4),
            "calibration_gap_delta": round(calibration_gap_delta, 4),
        }

    def _geofm_architecture_audit(
        self,
        *,
        payload: dict[str, Any],
        vector_inventory: dict[str, Any],
        thresholds: dict[str, Any],
    ) -> dict[str, Any]:
        raw = (
            payload.get("architecture_audit")
            or payload.get("geofm_architecture_audit")
            or payload.get("adapter_audit")
            or {}
        )
        raw = dict(raw) if isinstance(raw, dict) else {}
        adapter = (
            raw.get("adapter")
            or raw.get("adapter_config")
            or payload.get("geofm_adapter")
            or payload.get("adapter_config")
            or {}
        )
        adapter = dict(adapter) if isinstance(adapter, dict) else {}
        backbone = (
            raw.get("backbone")
            or raw.get("backbone_config")
            or payload.get("geofm_backbone")
            or payload.get("backbone_config")
            or {}
        )
        backbone = dict(backbone) if isinstance(backbone, dict) else {}
        validation = (
            raw.get("validation")
            or raw.get("data_validation")
            or payload.get("geofm_data_validation")
            or {}
        )
        validation = dict(validation) if isinstance(validation, dict) else {}

        backbone_name = str(
            backbone.get("name")
            or raw.get("backbone_name")
            or payload.get("geofm_backbone_name")
            or vector_inventory.get("embedding_model")
            or ""
        )
        architecture = str(
            backbone.get("architecture")
            or raw.get("architecture")
            or payload.get("geofm_architecture")
            or self._infer_geofm_backbone_architecture(backbone_name)
        )
        fused_qkv = self._geofm_truthy(
            backbone.get("fused_qkv", raw.get("fused_qkv", payload.get("fused_qkv")))
        )
        adapter_type = str(
            adapter.get("type")
            or adapter.get("adapter_type")
            or raw.get("adapter_type")
            or payload.get("geofm_adapter_type")
            or ""
        )
        target_modules = self._geofm_string_list(
            adapter.get("target_modules") or raw.get("target_modules") or payload.get("geofm_adapter_target_modules")
        )
        input_modalities = self._geofm_string_list(
            raw.get("input_modalities")
            or backbone.get("input_modalities")
            or payload.get("geofm_input_modalities")
            or []
        )
        capacity_score = safe_float(
            adapter.get("capacity_score", raw.get("adapter_capacity_score", payload.get("adapter_capacity_score"))),
            None,
        )
        trainable_parameter_ratio = safe_float(
            adapter.get("trainable_parameter_ratio", raw.get("trainable_parameter_ratio")),
            None,
        )
        domain_shift_score = safe_float(
            validation.get("domain_shift_score", raw.get("domain_shift_score", payload.get("domain_shift_score"))),
            None,
        )
        label_quality = safe_float(
            validation.get(
                "label_quality",
                validation.get("production_label_quality", raw.get("label_quality", payload.get("label_quality"))),
            ),
            None,
        )
        geographic_split = self._geofm_truthy(
            validation.get("geographic_split", raw.get("geographic_split", payload.get("geographic_split")))
        )
        temporal_holdout = self._geofm_truthy(
            validation.get("temporal_holdout", raw.get("temporal_holdout", payload.get("temporal_holdout")))
        )
        production_labels = self._geofm_truthy(
            validation.get("production_labels", raw.get("production_labels", payload.get("production_labels")))
        )
        if capacity_score is None and trainable_parameter_ratio is not None:
            capacity_score = max(0.0, min(1.0, float(trainable_parameter_ratio) * 10.0))

        missing: list[str] = []
        failed: list[str] = []
        warnings: list[str] = []
        recommendations: list[str] = []
        if not vector_inventory.get("available"):
            missing.append("geofm_vector_inventory")
        if not backbone_name:
            missing.append("backbone_name")
        if not architecture:
            missing.append("backbone_architecture")
        if not adapter_type:
            missing.append("adapter_type")
        if adapter_type.lower() in {"lora", "qlora"} and fused_qkv and not target_modules:
            failed.append("fused_qkv_adapter_target_modules")
            recommendations.append("inspect fused-QKV projection names and bind explicit adapter target modules before retaining LoRA/QLoRA GeoFM features")
        if adapter_type.lower() in {"lora", "qlora"} and fused_qkv:
            warnings.append("fused_qkv_requires_architecture_aware_adapter_binding")
        if capacity_score is None:
            missing.append("adapter_capacity_score")
        elif capacity_score < float(thresholds["min_adapter_capacity_score"]):
            failed.append("adapter_capacity_score")
        if domain_shift_score is None:
            missing.append("domain_shift_score")
        elif domain_shift_score > float(thresholds["max_architecture_domain_shift_score"]):
            failed.append("domain_shift_score")
        if label_quality is None:
            missing.append("label_quality")
        elif label_quality < float(thresholds["min_architecture_label_quality"]):
            failed.append("label_quality")
        if not geographic_split:
            missing.append("geographic_split")
        if not input_modalities:
            missing.append("input_modalities")
        if temporal_holdout is False:
            warnings.append("temporal_holdout_not_confirmed")
        if production_labels is False:
            warnings.append("production_labels_not_confirmed")

        if missing:
            recommendations.append("complete GeoFM architecture audit before promoting embeddings beyond gated enhancement")
        if "adapter_capacity_score" in failed:
            recommendations.append("increase adapter capacity or keep GeoFM disabled for this downstream planning task")
        if "domain_shift_score" in failed:
            recommendations.append("rerun GeoFM validation under geographic/domain shift before retaining B1")
        if "label_quality" in failed:
            recommendations.append("improve production-label quality before using GeoFM features in simulator training")

        status = "blocked" if failed else ("review" if missing else "pass")
        return {
            "schema": "territory_world_model.geofm_architecture_audit.v1",
            "status": status,
            "required": bool(thresholds.get("require_architecture_audit")),
            "passed": status == "pass",
            "backbone": {
                "name": backbone_name,
                "architecture": architecture,
                "fused_qkv": fused_qkv,
                "input_modalities": input_modalities,
                "embedding_model": vector_inventory.get("embedding_model", ""),
                "vector_collection": vector_inventory.get("collection", ""),
            },
            "adapter": {
                "type": adapter_type,
                "target_modules": target_modules,
                "capacity_score": round(float(capacity_score), 4) if capacity_score is not None else None,
                "trainable_parameter_ratio": round(float(trainable_parameter_ratio), 6) if trainable_parameter_ratio is not None else None,
            },
            "validation": {
                "geographic_split": geographic_split,
                "temporal_holdout": temporal_holdout,
                "production_labels": production_labels,
                "domain_shift_score": round(float(domain_shift_score), 4) if domain_shift_score is not None else None,
                "label_quality": round(float(label_quality), 4) if label_quality is not None else None,
            },
            "missing": missing,
            "failed": failed,
            "warnings": warnings,
            "thresholds": {
                "min_adapter_capacity_score": thresholds["min_adapter_capacity_score"],
                "max_architecture_domain_shift_score": thresholds["max_architecture_domain_shift_score"],
                "min_architecture_label_quality": thresholds["min_architecture_label_quality"],
            },
            "claim_boundary": "architecture_audit_required_before_geofm_default_use",
            "recommendations": recommendations,
        }

    def _infer_geofm_backbone_architecture(self, name: str) -> str:
        lowered = name.lower()
        if "prithvi" in lowered:
            return "vision_transformer"
        if "alphaearth" in lowered or "alpha_earth" in lowered:
            return "earth_foundation_embedding"
        if "geojepa" in lowered or "jepa" in lowered:
            return "joint_embedding_predictive_architecture"
        if "clip" in lowered:
            return "contrastive_vision_language"
        return ""

    def _geofm_truthy(self, value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"1", "true", "yes", "y", "pass", "passed", "enabled", "available"}:
                return True
            if text in {"0", "false", "no", "n", "fail", "failed", "disabled", "missing"}:
                return False
        return bool(value)

    def _geofm_string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    def _geofm_extended_validation(
        self,
        *,
        payload: dict[str, Any],
        thresholds: dict[str, Any],
        deltas: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw = payload.get("extended_validation")
        if not isinstance(raw, dict):
            raw = {}
        inferred = self._infer_geofm_extended_validation_payload(payload=payload, thresholds=thresholds, deltas=deltas or {})
        raw = self._merge_geofm_extended_validation_payload(inferred, raw)
        required = bool(thresholds.get("require_extended_validation") or raw.get("required") or raw.get("enforced"))
        requested = bool(raw) or required
        if not requested:
            return {
                "schema": "territory_world_model.geofm_extended_validation.v1",
                "requested": False,
                "required": False,
                "status": "not_required",
                "passed": True,
                "checks": {},
                "missing": [],
                "failed": [],
                "recommendations": [],
                "source": "not_requested",
                "auto_inferred": False,
            }

        d2 = self._geofm_d2_holdout_check(raw, payload, thresholds)
        d3 = self._geofm_d3_cross_region_check(raw, payload, thresholds)
        d4 = self._geofm_d4_domain_shift_check(raw, payload, thresholds)
        checks = {"D2": d2, "D3": d3, "D4": d4}
        missing: list[str] = []
        failed: list[str] = []
        recommendations: list[str] = []
        for code, check in checks.items():
            for item in check.get("missing") or []:
                missing.append(f"{code}:{item}")
            if check.get("status") == "blocked":
                failed.append(code)
            recommendations.extend(check.get("recommendations") or [])

        if failed:
            status = "blocked"
        elif missing:
            status = "review"
        else:
            status = "pass"

        return {
            "schema": "territory_world_model.geofm_extended_validation.v1",
            "requested": True,
            "required": required,
            "status": status,
            "passed": status == "pass",
            "checks": checks,
            "missing": missing,
            "failed": failed,
            "recommendations": recommendations,
            "source": raw.get("source") or "payload",
            "auto_inferred": bool(raw.get("auto_inferred")),
            "inference_sources": list(raw.get("inference_sources") or []),
        }

    def _merge_geofm_extended_validation_payload(self, inferred: dict[str, Any], explicit: dict[str, Any]) -> dict[str, Any]:
        if not inferred:
            return dict(explicit)
        merged = dict(inferred)
        for key, value in explicit.items():
            if key in {"D2", "d2", "downstream_holdout", "planning_holdout", "holdout_metrics", "planning_holdout_metrics"}:
                merged.pop("D2", None)
            if key in {"D3", "d3", "cross_region", "cross_region_metrics"}:
                merged.pop("D3", None)
            if key in {"D4", "d4", "domain_shift", "domain_shift_validation", "production_validation"}:
                merged.pop("D4", None)
            merged[key] = value
        if inferred and not explicit.get("source"):
            merged["source"] = inferred.get("source") or "auto_inferred"
        merged["auto_inferred"] = bool(inferred)
        sources = list(inferred.get("inference_sources") or [])
        sources.extend(item for item in explicit.get("inference_sources") or [] if item not in sources)
        if sources:
            merged["inference_sources"] = sources
        return merged

    def _infer_geofm_extended_validation_payload(
        self,
        *,
        payload: dict[str, Any],
        thresholds: dict[str, Any],
        deltas: dict[str, Any],
    ) -> dict[str, Any]:
        inferred: dict[str, Any] = {}
        sources: list[str] = []
        dataset = self._geofm_validation_dataset(payload)
        baseline_predictions = self._geofm_prediction_map(payload, "baseline")
        augmented_predictions = self._geofm_prediction_map(payload, "augmented")
        if dataset and baseline_predictions and augmented_predictions:
            rows = self._geofm_prediction_comparison_rows(
                dataset=dataset,
                baseline_predictions=baseline_predictions,
                augmented_predictions=augmented_predictions,
            )
            holdout_rows = [row for row in rows if row.get("split") == "holdout"]
            if holdout_rows:
                inferred["D2"] = {
                    **self._geofm_aggregate_prediction_comparison(holdout_rows),
                    "source": "dataset_holdout_prediction_comparison",
                }
                sources.append("dataset_holdout_prediction_comparison")
                region_groups: dict[str, list[dict[str, Any]]] = {}
                for row in holdout_rows:
                    region = str(row.get("region") or "")
                    if region:
                        region_groups.setdefault(region, []).append(row)
                if region_groups:
                    inferred["D3"] = {
                        "source": "dataset_holdout_prediction_comparison_by_region",
                        "regions": [
                            {
                                "region": region,
                                **self._geofm_aggregate_prediction_comparison(region_rows),
                            }
                            for region, region_rows in sorted(region_groups.items())
                        ],
                    }
                    sources.append("dataset_holdout_prediction_comparison_by_region")
                d4 = self._geofm_d4_from_dataset_prediction_comparison(dataset=dataset, rows=rows, thresholds=thresholds)
                if d4:
                    inferred["D4"] = d4
                    sources.append("dataset_holdout_domain_shift")

        evaluation_report = self._geofm_evaluation_report(payload)
        if evaluation_report and "D4" not in inferred:
            d4 = self._geofm_d4_from_evaluation_report(evaluation_report)
            if d4:
                inferred["D4"] = d4
                sources.append("dynamics_evaluation_report")

        if inferred:
            inferred["source"] = "auto_inferred"
            inferred["auto_inferred"] = True
            inferred["inference_sources"] = sources
            if deltas and "D2" not in inferred and evaluation_report.get("status") == "pass":
                inferred["D2"] = {
                    **deltas,
                    "sample_count": safe_int((evaluation_report.get("sample_inventory") or {}).get("holdout_example_count"), 0) or 0,
                    "source": "b0_b1_deltas_with_passed_dynamics_evaluation",
                }
                inferred["inference_sources"].append("b0_b1_deltas_with_passed_dynamics_evaluation")
        return inferred

    def _geofm_validation_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        value = payload.get("dataset") or payload.get("dynamics_training_dataset")
        return dict(value) if isinstance(value, dict) else {}

    def _geofm_evaluation_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        for key in ("geofm_dynamics_evaluation_report", "augmented_dynamics_evaluation_report", "dynamics_evaluation_report"):
            value = payload.get(key)
            if isinstance(value, dict):
                return dict(value)
        candidate = payload.get("augmented_dynamics_candidate_report") or payload.get("geofm_candidate_report")
        if isinstance(candidate, dict) and isinstance(candidate.get("evaluation"), dict):
            return dict(candidate.get("evaluation") or {})
        return {}

    def _geofm_prediction_map(self, payload: dict[str, Any], variant: str) -> dict[str, dict[str, Any]]:
        if variant == "baseline":
            keys = ("baseline_predictions", "b0_predictions", "baseline_dynamics_predictions")
            report_keys = ("baseline_dynamics_candidate_report", "b0_candidate_report")
        else:
            keys = ("augmented_predictions", "geofm_predictions", "b1_predictions", "augmented_dynamics_predictions")
            report_keys = ("augmented_dynamics_candidate_report", "geofm_candidate_report", "b1_candidate_report")
        for key in keys:
            value = payload.get(key)
            result = self._normalize_prediction_map(value)
            if result:
                return result
        for key in report_keys:
            report = payload.get(key)
            if isinstance(report, dict):
                result = self._normalize_prediction_map(report.get("predictions"))
                if result:
                    return result
        return {}

    def _geofm_payload_with_experiment_predictions(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = dict(payload)
        dataset = self._geofm_validation_dataset(payload)
        baseline_predictions = self._geofm_prediction_map(payload, "baseline")
        augmented_predictions = self._geofm_prediction_map(payload, "augmented")
        explicit_predictions = bool(baseline_predictions and augmented_predictions)
        if dataset and not explicit_predictions and bool(payload.get("auto_generate_predictions", True)):
            generated = self._geofm_generate_scaffold_prediction_maps(dataset)
            baseline_predictions = generated["baseline_predictions"]
            augmented_predictions = generated["augmented_predictions"]
            payload["baseline_predictions"] = baseline_predictions
            payload["augmented_predictions"] = augmented_predictions
            prediction_source = "deterministic_experiment_scaffold"
        else:
            prediction_source = "explicit_prediction_maps" if explicit_predictions else "missing_prediction_maps"
        return payload, {
            "schema": "territory_world_model.geofm_experiment_prediction_evidence.v1",
            "prediction_source": prediction_source,
            "explicit_prediction_maps": explicit_predictions,
            "baseline_prediction_count": len(baseline_predictions),
            "augmented_prediction_count": len(augmented_predictions),
            "auto_generated": prediction_source == "deterministic_experiment_scaffold",
            "claim_boundary": (
                "review_only_scaffold_predictions"
                if prediction_source == "deterministic_experiment_scaffold"
                else "explicit_downstream_predictions"
                if prediction_source == "explicit_prediction_maps"
                else "missing_downstream_predictions"
            ),
        }

    def _geofm_generate_scaffold_prediction_maps(self, dataset: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
        baseline_predictions: dict[str, dict[str, Any]] = {}
        augmented_predictions: dict[str, dict[str, Any]] = {}
        for example in dataset.get("examples") or []:
            if not isinstance(example, dict):
                continue
            example_id = str(example.get("id") or "")
            if not example_id:
                continue
            targets = dict(example.get("targets") or {})
            target_lift = float(safe_float(targets.get("planning_utility_delta"), 0.0) or 0.0)
            target_risk = float(safe_float(targets.get("constraint_violation_probability"), 0.0) or 0.0)
            target_uncertainty = dict(targets.get("uncertainty") or {})
            target_confidence = float(safe_float(target_uncertainty.get("confidence"), 0.60) or 0.60)
            baseline_predictions[example_id] = {
                "planning_utility_delta": round(target_lift - 0.04, 4),
                "constraint_violation_probability": round(target_risk + 0.02, 4),
                "uncertainty": {"confidence": round(max(0.0, min(1.0, target_confidence - 0.08)), 4)},
                "source": "deterministic_b0_experiment_scaffold",
            }
            augmented_predictions[example_id] = {
                "planning_utility_delta": round(target_lift + 0.02, 4),
                "constraint_violation_probability": round(target_risk, 4),
                "uncertainty": {"confidence": round(max(0.0, min(1.0, target_confidence + 0.04)), 4)},
                "source": "deterministic_b1_geofm_candidate_scaffold",
            }
        return {
            "baseline_predictions": baseline_predictions,
            "augmented_predictions": augmented_predictions,
        }

    def _geofm_variant_metrics_from_prediction_maps(self, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        baseline_predictions = self._geofm_prediction_map(payload, "baseline")
        augmented_predictions = self._geofm_prediction_map(payload, "augmented")
        if not baseline_predictions or not augmented_predictions:
            return {}
        baseline_metrics = self._geofm_mean_metrics([self._variant_metrics_from_payload(item) for item in baseline_predictions.values()])
        augmented_metrics = self._geofm_mean_metrics([self._variant_metrics_from_payload(item) for item in augmented_predictions.values()])
        baseline_metrics["source"] = "baseline_prediction_map_mean"
        augmented_metrics["source"] = "augmented_prediction_map_mean"
        return {
            "baseline_metrics": baseline_metrics,
            "augmented_metrics": augmented_metrics,
        }

    def _normalize_prediction_map(self, value: Any) -> dict[str, dict[str, Any]]:
        if isinstance(value, dict):
            return {str(key): dict(item) for key, item in value.items() if isinstance(item, dict)}
        if isinstance(value, list):
            result: dict[str, dict[str, Any]] = {}
            for item in value:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("example_id") or item.get("id") or "")
                prediction = item.get("prediction") if isinstance(item.get("prediction"), dict) else item
                if key and isinstance(prediction, dict):
                    result[key] = dict(prediction)
            return result
        return {}

    def _geofm_prediction_comparison_rows(
        self,
        *,
        dataset: dict[str, Any],
        baseline_predictions: dict[str, dict[str, Any]],
        augmented_predictions: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for example in dataset.get("examples") or []:
            if not isinstance(example, dict):
                continue
            example_id = str(example.get("id") or "")
            if not example_id:
                continue
            baseline = self._variant_metrics_from_payload(baseline_predictions.get(example_id))
            augmented = self._variant_metrics_from_payload(augmented_predictions.get(example_id))
            if not baseline or not augmented:
                continue
            targets = dict(example.get("targets") or {})
            labels = dict(example.get("labels") or {})
            provenance = dict(example.get("provenance") or {})
            reasons = list(example.get("not_for_training_reasons") or [])
            target_metrics = self._variant_metrics_from_payload(
                {
                    "planning_utility_delta": targets.get("planning_utility_delta"),
                    "constraint_violation_probability": targets.get("constraint_violation_probability"),
                    "ranking_score": labels.get("ranking_score"),
                    "uncertainty": targets.get("uncertainty"),
                }
            )
            rows.append(
                {
                    "example_id": example_id,
                    "split": str(example.get("split") or "candidate"),
                    "region": self._geofm_example_region(example),
                    "baseline_metrics": baseline,
                    "augmented_metrics": augmented,
                    "target_metrics": target_metrics,
                    "ground_truth": bool(provenance.get("ground_truth")),
                    "synthetic": bool(provenance.get("synthetic") or ("synthetic_temporal_transition" in reasons)),
                    "not_for_production": bool(provenance.get("not_for_production")),
                    "usable": not reasons,
                }
            )
        return rows

    def _geofm_example_region(self, example: dict[str, Any]) -> str:
        labels = dict(example.get("labels") or {})
        provenance = dict(example.get("provenance") or {})
        scenario_context = _mapping_payload(example.get("scenario_context"))
        spatial_scope = dict(scenario_context.get("spatial_scope") or {}) if isinstance(scenario_context.get("spatial_scope"), dict) else {}
        current_state = dict(example.get("current_state_summary") or {})
        for source in (labels, provenance, spatial_scope, scenario_context, current_state):
            for key in ("region", "region_code", "county", "county_code", "township", "township_code", "spatial_unit"):
                value = source.get(key)
                if value not in (None, ""):
                    return str(value)
        return ""

    def _geofm_aggregate_prediction_comparison(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        baseline = self._geofm_mean_metrics([dict(row.get("baseline_metrics") or {}) for row in rows])
        augmented = self._geofm_mean_metrics([dict(row.get("augmented_metrics") or {}) for row in rows])
        deltas = self._geofm_metric_deltas(baseline, augmented)
        return {
            "sample_count": len(rows),
            "baseline_metrics": baseline,
            "augmented_metrics": augmented,
            **deltas,
        }

    def _geofm_mean_metrics(self, metrics: list[dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in ("planning_lift", "constraint_risk", "confidence", "calibration_gap", "ranking_score"):
            values = [float(safe_float(item.get(key), 0.0) or 0.0) for item in metrics if key in item]
            result[key] = round(self._mean(values) or 0.0, 4)
        result["source"] = "mean_prediction_metrics"
        return result

    def _geofm_d4_from_dataset_prediction_comparison(
        self,
        *,
        dataset: dict[str, Any],
        rows: list[dict[str, Any]],
        thresholds: dict[str, Any],
    ) -> dict[str, Any]:
        examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
        holdout_rows = [row for row in rows if row.get("split") == "holdout"]
        if not examples or not holdout_rows:
            return {}
        train_targets = [
            float(safe_float((item.get("targets") or {}).get("planning_utility_delta"), 0.0) or 0.0)
            for item in examples
            if str(item.get("split") or "candidate") != "holdout"
        ]
        holdout_targets = [
            float(safe_float((row.get("target_metrics") or {}).get("planning_lift"), 0.0) or 0.0)
            for row in holdout_rows
        ]
        train_mean = self._mean(train_targets)
        holdout_mean = self._mean(holdout_targets)
        domain_shift_score = None
        if train_mean is not None and holdout_mean is not None:
            domain_shift_score = round(abs(holdout_mean - train_mean) / max(abs(train_mean), 1.0), 4)
        regret_values = [
            abs(float((row.get("augmented_metrics") or {}).get("planning_lift") or 0.0) - float((row.get("target_metrics") or {}).get("planning_lift") or 0.0))
            for row in holdout_rows
        ]
        confidences = [
            float((row.get("augmented_metrics") or {}).get("confidence") or 0.0)
            for row in holdout_rows
            if "confidence" in (row.get("augmented_metrics") or {})
        ]
        production_ready = [
            1.0 if row.get("ground_truth") and row.get("usable") and not row.get("synthetic") and not row.get("not_for_production") else 0.0
            for row in holdout_rows
        ]
        return {
            "source": "dataset_holdout_domain_shift",
            "domain_shift_score": domain_shift_score,
            "holdout_regret_delta": self._mean(regret_values),
            "temporal_holdout_confidence": self._mean(confidences),
            "production_label_quality": self._mean(production_ready),
            "holdout_sample_count": len(holdout_rows),
            "thresholds_used": {
                "max_domain_shift_score": thresholds["max_domain_shift_score"],
                "max_holdout_regret_delta": thresholds["max_holdout_regret_delta"],
                "min_temporal_holdout_confidence": thresholds["min_temporal_holdout_confidence"],
                "min_production_label_quality": thresholds["min_production_label_quality"],
            },
        }

    def _geofm_d4_from_evaluation_report(self, report: dict[str, Any]) -> dict[str, Any]:
        metrics = dict(report.get("metrics") or {})
        inventory = dict(report.get("sample_inventory") or {})
        holdout_count = safe_int(inventory.get("holdout_example_count"), 0) or 0
        ground_truth_count = safe_int(inventory.get("ground_truth_example_count"), 0) or 0
        if not metrics and not inventory:
            return {}
        transition_error = safe_float(metrics.get("mean_transition_error"), None)
        utility_error = safe_float(metrics.get("mean_utility_error"), None)
        mean_confidence = safe_float(metrics.get("mean_confidence"), None)
        return {
            "source": "dynamics_evaluation_report",
            "domain_shift_score": transition_error,
            "holdout_regret_delta": utility_error,
            "temporal_holdout_confidence": mean_confidence,
            "production_label_quality": round(ground_truth_count / max(1, holdout_count), 4) if holdout_count else None,
        }

    def _geofm_extended_validation_payload_for_gate(self, validation: dict[str, Any]) -> dict[str, Any]:
        checks = dict(validation.get("checks") or {})
        payload = {
            "required": True,
            "source": validation.get("source") or "experiment_report",
            "auto_inferred": bool(validation.get("auto_inferred")),
            "inference_sources": list(validation.get("inference_sources") or []),
        }
        d2 = dict(checks.get("D2") or {})
        d3 = dict(checks.get("D3") or {})
        d4 = dict(checks.get("D4") or {})
        if d2:
            payload["D2"] = {
                **dict(d2.get("deltas") or {}),
                "sample_count": d2.get("sample_count", 0),
                "source": d2.get("name") or "D2",
            }
        if d3:
            regions = []
            for item in d3.get("regions") or []:
                if not isinstance(item, dict):
                    continue
                regions.append(
                    {
                        **dict(item.get("deltas") or {}),
                        "region": item.get("region"),
                        "source_status": item.get("status"),
                    }
                )
            payload["D3"] = {
                "regions": regions,
                "source": d3.get("name") or "D3",
            }
        if d4:
            payload["D4"] = {
                **dict(d4.get("metrics") or {}),
                "source": d4.get("name") or "D4",
            }
        return payload

    def _geofm_experiment_comparison_rows(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        dataset = self._geofm_validation_dataset(payload)
        baseline_predictions = self._geofm_prediction_map(payload, "baseline")
        augmented_predictions = self._geofm_prediction_map(payload, "augmented")
        if not dataset or not baseline_predictions or not augmented_predictions:
            return []
        return self._geofm_prediction_comparison_rows(
            dataset=dataset,
            baseline_predictions=baseline_predictions,
            augmented_predictions=augmented_predictions,
        )

    def _geofm_experiment_comparison_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        holdout_rows = [row for row in rows if row.get("split") == "holdout"]
        regions = sorted({str(row.get("region") or "") for row in holdout_rows if row.get("region")})
        return {
            "schema": "territory_world_model.geofm_prediction_comparison_summary.v1",
            "comparison_row_count": len(rows),
            "holdout_row_count": len(holdout_rows),
            "ground_truth_holdout_count": sum(1 for row in holdout_rows if row.get("ground_truth")),
            "production_ready_holdout_count": sum(
                1
                for row in holdout_rows
                if row.get("ground_truth") and row.get("usable") and not row.get("synthetic") and not row.get("not_for_production")
            ),
            "region_count": len(regions),
            "regions": regions[:50],
        }

    def _geofm_experiment_recommendations(
        self,
        gate_report: dict[str, Any],
        extended_validation: dict[str, Any],
        rows: list[dict[str, Any]],
        prediction_evidence: dict[str, Any],
    ) -> list[str]:
        recommendations = list(gate_report.get("recommendations") or [])
        if not rows:
            recommendations.append("provide dynamics dataset plus B0/B1 prediction maps to make the GeoFM downstream experiment auditable")
        if extended_validation.get("status") != "pass":
            recommendations.append("do not promote GeoFM beyond gated enhancement until D2/D3/D4 downstream evidence passes")
        if prediction_evidence.get("prediction_source") == "deterministic_experiment_scaffold":
            recommendations.append("replace deterministic B0/B1 scaffold predictions with explicit downstream model predictions before retaining GeoFM")
        if gate_report.get("gate_status") == "pass":
            recommendations.append("retain GeoFM only for downstream planning tasks matching this experiment scope")
        if not recommendations:
            recommendations.append("keep GeoFM as a review-gated enhancement and re-run the experiment on new regions before default use")
        return recommendations

    def _geofm_experiment_status(self, gate_report: dict[str, Any], prediction_evidence: dict[str, Any]) -> str:
        if prediction_evidence.get("prediction_source") == "deterministic_experiment_scaffold":
            return "review"
        return str(gate_report.get("gate_status") or "review")

    def _geofm_pick_extended_payload(self, raw: dict[str, Any], payload: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in raw:
                return raw.get(key)
            if key in payload:
                return payload.get(key)
        return None

    def _geofm_deltas_from_validation_payload(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        baseline = self._variant_metrics_from_payload(value.get("baseline_metrics") or value.get("baseline"))
        augmented = self._variant_metrics_from_payload(value.get("augmented_metrics") or value.get("augmented") or value.get("geofm_metrics"))
        if baseline and augmented:
            return self._geofm_metric_deltas(baseline, augmented)
        deltas: dict[str, Any] = {}
        for key in (
            "planning_lift_delta",
            "constraint_risk_delta",
            "confidence_delta",
            "ranking_score_delta",
            "calibration_gap_delta",
        ):
            parsed = safe_float(value.get(key), None)
            if parsed is not None:
                deltas[key] = round(float(parsed), 4)
        return deltas

    def _geofm_d2_holdout_check(
        self,
        raw: dict[str, Any],
        payload: dict[str, Any],
        thresholds: dict[str, Any],
    ) -> dict[str, Any]:
        value = self._geofm_pick_extended_payload(
            raw,
            payload,
            "D2",
            "d2",
            "downstream_holdout",
            "planning_holdout",
            "holdout_metrics",
            "planning_holdout_metrics",
        )
        missing: list[str] = []
        failed: list[str] = []
        recommendations: list[str] = []
        if not isinstance(value, dict):
            missing.append("downstream_planning_holdout")
            recommendations.append("run D2 explicit downstream holdout planning evaluation before promoting GeoFM beyond B0/B1")
            return {
                "name": "D2 explicit downstream planning holdout",
                "status": "review",
                "passed": False,
                "missing": missing,
                "failed": failed,
                "deltas": {},
                "thresholds": {
                    "min_holdout_planning_lift_delta": thresholds["min_holdout_planning_lift_delta"],
                    "max_constraint_risk_delta": thresholds["max_constraint_risk_delta"],
                    "min_holdout_ranking_score_delta": thresholds["min_holdout_ranking_score_delta"],
                },
                "recommendations": recommendations,
            }

        deltas = self._geofm_deltas_from_validation_payload(value)
        planning_delta = safe_float(deltas.get("planning_lift_delta"), None)
        risk_delta = safe_float(deltas.get("constraint_risk_delta"), 0.0)
        ranking_delta = safe_float(deltas.get("ranking_score_delta"), None)
        if planning_delta is None:
            missing.append("planning_lift_delta")
        elif planning_delta < float(thresholds["min_holdout_planning_lift_delta"]):
            failed.append("planning_lift_delta")
        if risk_delta is not None and risk_delta > float(thresholds["max_constraint_risk_delta"]):
            failed.append("constraint_risk_delta")
        if ranking_delta is not None and ranking_delta < float(thresholds["min_holdout_ranking_score_delta"]):
            failed.append("ranking_score_delta")

        if failed:
            recommendations.append("gate out GeoFM until D2 holdout lift, ranking and constraint-risk deltas pass")
        status = "blocked" if failed else ("review" if missing else "pass")
        return {
            "name": "D2 explicit downstream planning holdout",
            "status": status,
            "passed": status == "pass",
            "missing": missing,
            "failed": failed,
            "sample_count": safe_int(value.get("sample_count"), 0) or 0,
            "deltas": deltas,
            "thresholds": {
                "min_holdout_planning_lift_delta": thresholds["min_holdout_planning_lift_delta"],
                "max_constraint_risk_delta": thresholds["max_constraint_risk_delta"],
                "min_holdout_ranking_score_delta": thresholds["min_holdout_ranking_score_delta"],
            },
            "recommendations": recommendations,
        }

    def _geofm_d3_cross_region_check(
        self,
        raw: dict[str, Any],
        payload: dict[str, Any],
        thresholds: dict[str, Any],
    ) -> dict[str, Any]:
        value = self._geofm_pick_extended_payload(raw, payload, "D3", "d3", "cross_region", "cross_region_metrics")
        missing: list[str] = []
        failed: list[str] = []
        recommendations: list[str] = []
        if isinstance(value, dict):
            regions = value.get("regions") or value.get("region_metrics") or value.get("splits")
            if regions is None and (value.get("baseline_metrics") or value.get("planning_lift_delta") is not None):
                regions = [value]
        else:
            regions = value
        if not isinstance(regions, list):
            regions = []
        min_regions = int(thresholds["min_cross_region_count"])
        if len(regions) < min_regions:
            missing.append("cross_region_splits")
            recommendations.append("run D3 geographic split validation across enough regions before promoting GeoFM")

        region_results: list[dict[str, Any]] = []
        for idx, item in enumerate(regions):
            if not isinstance(item, dict):
                continue
            deltas = self._geofm_deltas_from_validation_payload(item)
            planning_delta = safe_float(deltas.get("planning_lift_delta"), None)
            risk_delta = safe_float(deltas.get("constraint_risk_delta"), 0.0)
            region_id = str(item.get("region") or item.get("region_code") or item.get("split") or f"region_{idx + 1}")
            region_failed: list[str] = []
            if planning_delta is None:
                region_failed.append("planning_lift_delta")
            elif planning_delta < float(thresholds["min_cross_region_planning_lift_delta"]):
                region_failed.append("planning_lift_delta")
            if risk_delta is not None and risk_delta > float(thresholds["max_constraint_risk_delta"]):
                region_failed.append("constraint_risk_delta")
            if region_failed:
                failed.append(region_id)
            region_results.append(
                {
                    "region": region_id,
                    "status": "blocked" if region_failed else "pass",
                    "failed": region_failed,
                    "deltas": deltas,
                }
            )

        if failed:
            recommendations.append("gate out GeoFM until D3 cross-region planning lift is robust without added constraint risk")
        status = "blocked" if failed else ("review" if missing else "pass")
        return {
            "name": "D3 cross-region geographic robustness",
            "status": status,
            "passed": status == "pass",
            "missing": missing,
            "failed": failed,
            "region_count": len(region_results),
            "regions": region_results,
            "thresholds": {
                "min_cross_region_count": min_regions,
                "min_cross_region_planning_lift_delta": thresholds["min_cross_region_planning_lift_delta"],
                "max_constraint_risk_delta": thresholds["max_constraint_risk_delta"],
            },
            "recommendations": recommendations,
        }

    def _geofm_d4_domain_shift_check(
        self,
        raw: dict[str, Any],
        payload: dict[str, Any],
        thresholds: dict[str, Any],
    ) -> dict[str, Any]:
        value = self._geofm_pick_extended_payload(
            raw,
            payload,
            "D4",
            "d4",
            "domain_shift",
            "domain_shift_validation",
            "production_validation",
        )
        missing: list[str] = []
        failed: list[str] = []
        recommendations: list[str] = []
        if not isinstance(value, dict):
            missing.append("domain_shift_temporal_validation")
            recommendations.append("run D4 domain-shift, temporal holdout and production-label checks before promoting GeoFM")
            return {
                "name": "D4 domain-shift and production-readiness validation",
                "status": "review",
                "passed": False,
                "missing": missing,
                "failed": failed,
                "metrics": {},
                "thresholds": {
                    "max_domain_shift_score": thresholds["max_domain_shift_score"],
                    "max_holdout_regret_delta": thresholds["max_holdout_regret_delta"],
                    "min_temporal_holdout_confidence": thresholds["min_temporal_holdout_confidence"],
                    "min_production_label_quality": thresholds["min_production_label_quality"],
                },
                "recommendations": recommendations,
            }

        domain_shift_score = safe_float(value.get("domain_shift_score"), None)
        holdout_regret_delta = safe_float(value.get("holdout_regret_delta"), None)
        temporal_holdout_confidence = safe_float(value.get("temporal_holdout_confidence"), None)
        label_quality = safe_float(value.get("label_quality"), safe_float(value.get("production_label_quality"), None))
        if domain_shift_score is None:
            missing.append("domain_shift_score")
        elif domain_shift_score > float(thresholds["max_domain_shift_score"]):
            failed.append("domain_shift_score")
        if holdout_regret_delta is None:
            missing.append("holdout_regret_delta")
        elif holdout_regret_delta > float(thresholds["max_holdout_regret_delta"]):
            failed.append("holdout_regret_delta")
        if temporal_holdout_confidence is None:
            missing.append("temporal_holdout_confidence")
        elif temporal_holdout_confidence < float(thresholds["min_temporal_holdout_confidence"]):
            failed.append("temporal_holdout_confidence")
        if label_quality is None:
            missing.append("production_label_quality")
        elif label_quality < float(thresholds["min_production_label_quality"]):
            failed.append("production_label_quality")

        if failed:
            recommendations.append("gate out GeoFM until D4 domain-shift, temporal holdout and label-quality checks pass")
        status = "blocked" if failed else ("review" if missing else "pass")
        return {
            "name": "D4 domain-shift and production-readiness validation",
            "status": status,
            "passed": status == "pass",
            "missing": missing,
            "failed": failed,
            "metrics": {
                "domain_shift_score": domain_shift_score,
                "holdout_regret_delta": holdout_regret_delta,
                "temporal_holdout_confidence": temporal_holdout_confidence,
                "production_label_quality": label_quality,
            },
            "thresholds": {
                "max_domain_shift_score": thresholds["max_domain_shift_score"],
                "max_holdout_regret_delta": thresholds["max_holdout_regret_delta"],
                "min_temporal_holdout_confidence": thresholds["min_temporal_holdout_confidence"],
                "min_production_label_quality": thresholds["min_production_label_quality"],
            },
            "recommendations": recommendations,
        }

    def _geofm_gate_decision(
        self,
        *,
        deltas: dict[str, Any],
        baseline_gate: dict[str, Any],
        augmented_gate: dict[str, Any],
        thresholds: dict[str, Any],
        vector_inventory: dict[str, Any],
        explicit_metrics: bool,
        extended_validation: dict[str, Any] | None = None,
        architecture_audit: dict[str, Any] | None = None,
    ) -> tuple[str, str, list[str]]:
        recommendations: list[str] = []
        if not explicit_metrics and thresholds.get("require_explicit_downstream_metrics"):
            recommendations.append("run explicit B0/B1 downstream planning evaluation before retaining GeoFM")
        if not vector_inventory.get("available"):
            recommendations.append("publish or bind GeoFM/MMFE semantic vector inventory before B1 evaluation")
        if augmented_gate.get("missing"):
            recommendations.append("resolve B1 evidence gaps before using GeoFM in the default dynamics path")
        if extended_validation:
            recommendations.extend(extended_validation.get("recommendations") or [])
        if architecture_audit:
            audit_required = bool(architecture_audit.get("required") or thresholds.get("require_architecture_audit"))
            if audit_required or architecture_audit.get("status") == "blocked":
                recommendations.extend(architecture_audit.get("recommendations") or [])
            elif architecture_audit.get("status") != "pass":
                recommendations.append("keep GeoFM architecture audit visible and unresolved until adapter/backbone evidence is complete")

        lift_ok = float(deltas.get("planning_lift_delta") or 0.0) >= float(thresholds["min_planning_lift_delta"])
        risk_ok = float(deltas.get("constraint_risk_delta") or 0.0) <= float(thresholds["max_constraint_risk_delta"])
        confidence_ok = float(deltas.get("confidence_delta") or 0.0) >= float(thresholds["min_confidence_delta"])
        gates_ok = baseline_gate.get("status") == "pass" and augmented_gate.get("status") == "pass"
        explicit_ok = explicit_metrics or not thresholds.get("require_explicit_downstream_metrics")
        extended_required = bool((extended_validation or {}).get("required"))
        extended_status = (extended_validation or {}).get("status", "not_required")
        extended_ok = (not extended_required) or extended_status == "pass"
        architecture_required = bool((architecture_audit or {}).get("required") or thresholds.get("require_architecture_audit"))
        architecture_status = (architecture_audit or {}).get("status", "not_required")
        architecture_ok = (not architecture_required) or architecture_status == "pass"

        if gates_ok and explicit_ok and lift_ok and risk_ok and confidence_ok and extended_ok and architecture_ok:
            return "pass", "retain_geofm_for_downstream_planning", recommendations

        if gates_ok and explicit_ok and lift_ok and risk_ok and confidence_ok and extended_required:
            if extended_status == "blocked":
                return "blocked", "gate_out_geofm", recommendations
            return "review", "review_required", recommendations

        if gates_ok and explicit_ok and lift_ok and risk_ok and confidence_ok and architecture_required:
            if architecture_status == "blocked":
                return "blocked", "gate_out_geofm", recommendations
            return "review", "review_required", recommendations

        if explicit_ok and gates_ok and (not lift_ok or not risk_ok):
            recommendations.append("gate out GeoFM for this task until it improves planning lift without increasing constraint risk")
            return "blocked", "gate_out_geofm", recommendations

        return "review", "review_required", recommendations

    def _geofm_vector_inventory(self, state: TwmStateVersion) -> dict[str, Any]:
        bundle_root = self._state_bundle_root(state)
        if bundle_root is None:
            return {"available": False, "record_count": 0, "path": ""}
        candidates = [
            bundle_root / "twm_mmfe_semantic_vectors.pgvector.json",
            bundle_root.parent / "mmfe_semantic_fusion" / "twm_mmfe_semantic_vectors.pgvector.json",
        ]
        path = next((item for item in candidates if item.exists()), None)
        if path is None:
            return {"available": False, "record_count": 0, "path": ""}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"available": False, "record_count": 0, "path": str(path), "read_error": True}
        records = data.get("records") if isinstance(data, dict) else []
        if not isinstance(records, list):
            records = []
        not_for_production = any(bool((item.get("metadata") or {}).get("not_for_production")) for item in records if isinstance(item, dict))
        synthetic_count = sum(1 for item in records if isinstance(item, dict) and bool((item.get("metadata") or {}).get("synthetic")))
        return {
            "available": bool(records),
            "path": str(path),
            "schema": data.get("schema", "") if isinstance(data, dict) else "",
            "collection": data.get("collection", "") if isinstance(data, dict) else "",
            "embedding_model": data.get("embedding_model", "") if isinstance(data, dict) else "",
            "embedding_required": bool(data.get("embedding_required")) if isinstance(data, dict) else False,
            "record_count": len(records),
            "synthetic_record_count": synthetic_count,
            "not_for_production": not_for_production,
        }

    def _temporal_transition_examples_from_state_snapshots(
        self,
        *,
        state: TwmStateVersion,
        state_bundle: dict[str, Any],
        scenario: str,
        evidence_coverage: float | None,
        rule_hits: Iterable[TwmRuleHit],
        validation: dict[str, Any],
        payload: dict[str, Any],
    ) -> list[TwmDynamicsTrainingExample]:
        bundle_root = self._state_bundle_root(state)
        if bundle_root is None:
            return []
        snapshots_path = self._find_auxiliary_table(bundle_root, "state_snapshots.csv")
        if snapshots_path is None:
            return []
        try:
            rows = read_csv(snapshots_path)
        except Exception:
            return []
        if not rows:
            return []

        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            year = safe_int(row.get("snapshot_year"), -1)
            if year < 0:
                continue
            grouped.setdefault(year, []).append(row)
        years = sorted(grouped)
        if len(years) < 2:
            return []

        examples: list[TwmDynamicsTrainingExample] = []
        holdout_policy = self._temporal_holdout_policy(payload)
        quality_summary = dict(state.quality_summary or {})
        base_context = {
            "scenario": scenario,
            "temporal_holdout": holdout_policy,
            "source_table": str(snapshots_path),
        }
        rule_hits_list = list(rule_hits)
        for idx, (current_year, next_year) in enumerate(zip(years, years[1:])):
            current_rows = grouped[current_year]
            next_rows = grouped[next_year]
            current_latent = self._latent_from_snapshot_rows(current_rows)
            next_latent = self._latent_from_snapshot_rows(next_rows)
            transition_delta = self._snapshot_transition_delta(current_latent, next_latent)
            future_stage = self._dominant_stage(next_rows)
            synthetic = any(truthy(row.get("synthetic")) for row in current_rows + next_rows)
            not_for_production = any(truthy(row.get("not_for_production")) for row in current_rows + next_rows)
            split = self._split_for_transition_year(next_year, holdout_policy)
            action = TerritoryWorldModelAction(
                action_type="observed_transition" if not synthetic else "synthetic_transition",
                target_role="land_space_type",
                magnitude=round(abs(float(transition_delta.get("total_area_delta_m2") or 0.0)), 4),
                scenario=scenario,
                description=f"{current_year}->{next_year} {future_stage} territorial transition",
                legal_intent="temporal_state_supervision",
                execution_mask={
                    "allowed": not not_for_production,
                    "required_reviews": ["synthetic_transition"] if synthetic else [],
                    "hard_blocks": ["not_for_production"] if not_for_production else [],
                    "confidence": 0.35 if synthetic else 0.75,
                },
                parameters={
                    "current_year": current_year,
                    "next_year": next_year,
                    "temporal_stage": future_stage,
                    "synthetic": synthetic,
                    "not_for_production": not_for_production,
                },
                treatment="observational_temporal_calibration",
            )
            forecast = self.planner.forecast(
                {
                    "state_version": state,
                    "objects": state_bundle["objects"],
                    "relations": state_bundle["relations"],
                    "quality_summary": quality_summary,
                    "warnings": [],
                    "hierarchy_tokens": state.summary,
                },
                action,
                scenario=scenario,
                rule_hits=rule_hits_list,
                evidence_coverage=evidence_coverage,
                scenario_context={
                    "observed_treatment_effect": self._transition_treatment_proxy(transition_delta),
                    "calibration_gap": 0.12 if synthetic else 0.04,
                    "temporal_stage": future_stage,
                },
            )
            not_for_training: list[str] = []
            if synthetic:
                not_for_training.append("synthetic_temporal_transition")
            if not_for_production:
                not_for_training.append("not_for_production_transition")
            if validation.get("overall_status") != "pass":
                not_for_training.append("validation_report_not_fully_passed")
            if forecast.evidence_gate.get("status") != "pass":
                not_for_training.append("evidence_gate_not_passed")
            example = TwmDynamicsTrainingExample(
                state_version_id=state.id,
                project_id=state.project_id,
                split=split,
                sample_type="temporal_state_transition",
                current_state_summary={
                    "year": current_year,
                    "latent_state": current_latent,
                    "quality_summary": quality_summary,
                    "hierarchy_tokens": self._state_hierarchy_tokens(state),
                },
                action=action,
                scenario_context=base_context
                | {
                    "current_year": current_year,
                    "next_year": next_year,
                    "temporal_stage": future_stage,
                },
                targets={
                    "future_latent_state": {
                        "schema": "territory_world_model.observed_temporal_latent_state.v1",
                        "state_version_id": state.id,
                        "project_id": state.project_id,
                        "current_year": current_year,
                        "next_year": next_year,
                        "current": current_latent,
                        "observed_next": next_latent,
                        "delta": transition_delta,
                    },
                    "constraint_violation_probability": forecast.constraint_violation_probability,
                    "planning_utility_delta": forecast.planning_utility_delta,
                    "uncertainty": forecast.uncertainty,
                    "calibration": forecast.calibration
                    | {
                        "observed_transition_proxy": self._transition_treatment_proxy(transition_delta),
                    },
                    "action_mask": forecast.evidence_gate.get("action_mask", {}),
                },
                labels={
                    "constraint_label": "review_required" if not_for_production or synthetic else "observed_transition",
                    "utility_label": "positive_lift" if forecast.planning_utility_delta > 0 else "non_positive_lift",
                    "ranking_score": round(forecast.planning_utility_delta - forecast.constraint_violation_probability, 4),
                    "evidence_supported": forecast.evidence_gate.get("status") == "pass",
                    "supervision_source": "state_snapshots",
                    "ground_truth_grade": "synthetic_review" if synthetic or not_for_production else "observed",
                },
                losses={
                    "transition_loss": "targets.future_latent_state.observed_next",
                    "constraint_loss": "targets.constraint_violation_probability",
                    "planning_ranking_loss": "labels.ranking_score",
                    "calibration_loss": "targets.calibration.observed_transition_proxy",
                    "uncertainty_calibration_loss": "targets.uncertainty.confidence",
                    "evidence_consistency_loss": "evidence_gate.status",
                    "action_mask_loss": "targets.action_mask.allowed",
                },
                evidence_gate=forecast.evidence_gate,
                provenance={
                    "state_version_id": state.id,
                    "source_table": str(snapshots_path),
                    "current_year": current_year,
                    "next_year": next_year,
                    "sample_index": idx,
                    "sample_family": "temporal_transition",
                    "ground_truth": not synthetic and not not_for_production,
                    "synthetic": synthetic,
                    "not_for_production": not_for_production,
                },
                not_for_training_reasons=not_for_training,
            )
            examples.append(example)
        return examples

    def _state_bundle_root(self, state: TwmStateVersion) -> Path | None:
        source_manifest = dict(state.source_manifest or {})
        raw = source_manifest.get("bundle_dir")
        if not raw:
            return None
        path = Path(str(raw))
        return path if path.exists() else None

    def _find_auxiliary_table(self, bundle_root: Path, table_name: str) -> Path | None:
        for candidate in (bundle_root / "tables" / table_name, bundle_root.parent / "tables" / table_name):
            if candidate.exists():
                return candidate
        return None

    def _dynamics_readiness_thresholds(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = dict(payload.get("thresholds") or {})
        return {
            "min_total_examples": safe_int(raw.get("min_total_examples"), 6) or 6,
            "min_usable_examples": safe_int(raw.get("min_usable_examples"), 4) or 4,
            "min_observed_temporal_examples": safe_int(raw.get("min_observed_temporal_examples"), 2) or 2,
            "min_holdout_examples": safe_int(raw.get("min_holdout_examples"), 1) or 1,
            "max_scaffold_ratio": float(safe_float(raw.get("max_scaffold_ratio"), 0.5) or 0.5),
            "max_review_ratio": float(safe_float(raw.get("max_review_ratio"), 0.35) or 0.35),
            "require_geofm_pass": truthy(raw.get("require_geofm_pass")) or truthy(payload.get("require_geofm_pass")),
            "require_causal_pass": truthy(raw.get("require_causal_pass")) or truthy(payload.get("require_causal_pass")),
        }

    def _dynamics_payload_value_provided(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (dict, list, tuple, set)):
            return bool(value)
        return True

    def _dynamics_should_compute_geofm_gate(self, payload: dict[str, Any], thresholds: dict[str, Any]) -> bool:
        if thresholds.get("require_geofm_pass"):
            return True
        if any(truthy(payload.get(key)) for key in ("require_geofm_pass", "uses_geofm", "geofm_required")):
            return True
        for container_key in ("backend", "dynamics_backend", "candidate", "trainer"):
            raw = payload.get(container_key)
            if isinstance(raw, dict) and any(truthy(raw.get(key)) for key in ("uses_geofm", "geofm_required")):
                return True
        evidence_keys = (
            "baseline_metrics",
            "augmented_metrics",
            "geofm_metrics",
            "baseline_predictions",
            "b0_predictions",
            "baseline_dynamics_predictions",
            "augmented_predictions",
            "geofm_predictions",
            "b1_predictions",
            "augmented_dynamics_predictions",
            "baseline_dynamics_candidate_report",
            "b0_candidate_report",
            "augmented_dynamics_candidate_report",
            "geofm_candidate_report",
            "b1_candidate_report",
            "geofm_dynamics_evaluation_report",
            "augmented_dynamics_evaluation_report",
            "dynamics_evaluation_report",
            "extended_validation",
            "architecture_audit",
            "geofm_architecture_audit",
            "adapter",
            "geofm_adapter",
            "backbone",
            "geofm_backbone",
            "data_validation",
            "geofm_data_validation",
            "geofm_backbone_name",
            "geofm_architecture",
            "fused_qkv",
            "geofm_adapter_type",
            "geofm_adapter_target_modules",
            "geofm_input_modalities",
        )
        return any(self._dynamics_payload_value_provided(payload.get(key)) for key in evidence_keys)

    def _dynamics_should_compute_causal_gate(self, payload: dict[str, Any], thresholds: dict[str, Any]) -> bool:
        if thresholds.get("require_causal_pass"):
            return True
        if any(
            truthy(payload.get(key))
            for key in (
                "require_causal_pass",
                "uses_causal_calibration",
                "causal_required",
                "causal_calibration_required",
            )
        ):
            return True
        for container_key in ("backend", "dynamics_backend", "candidate", "trainer"):
            raw = payload.get(container_key)
            if isinstance(raw, dict) and any(
                truthy(raw.get(key)) for key in ("uses_causal_calibration", "causal_required", "causal_calibration_required")
            ):
                return True
        evidence_keys = (
            "records",
            "observations",
            "observed_history",
            "observed_history_path",
            "approval_review_history_path",
            "approval_history_path",
            "observed_approval_history_path",
            "model_effect",
            "baseline_action",
            "intervention_actions",
            "treatment",
            "treatment_name",
            "outcome",
            "outcome_name",
            "positive_label",
            "outcome_direction",
            "scca_causal_evidence_report",
            "scca_evidence_report",
            "scca_result",
            "scca_report",
            "scca_payload",
            "scca_output_dir",
            "scca_dir",
            "scca_path",
            "scca_manifest_path",
        )
        return any(self._dynamics_payload_value_provided(payload.get(key)) for key in evidence_keys)

    def _dynamics_dataset_mrep_trace(
        self,
        *,
        state: TwmStateVersion,
        payload: dict[str, Any],
        examples: list[TwmDynamicsTrainingExample],
        state_contract: dict[str, Any],
    ) -> dict[str, Any]:
        examples_payload = [self._dynamics_training_example_semantic_payload(item) for item in examples]
        review_only_count = sum(1 for item in examples if item.not_for_training_reasons)
        synthetic_or_not_for_production = sum(
            1
            for item in examples
            if item.provenance.get("synthetic") or item.provenance.get("not_for_production")
        )
        holdout_count = sum(1 for item in examples if item.split == "holdout")
        target_heads = sorted(
            {
                head
                for item in examples
                for head in item.targets.keys()
            }
        )
        source_counts: dict[str, int] = {}
        for item in examples:
            source = str(item.labels.get("supervision_source") or "unknown")
            source_counts[source] = source_counts.get(source, 0) + 1
        return {
            "schema": "territory_world_model.mrep_trace.v1",
            "state_version_id": state.id,
            "project_id": state.project_id,
            "dataset_snapshot_hash": _stable_sha256(examples_payload),
            "state_contract_version": state_contract.get("schema", ""),
            "state_contract_status": state_contract.get("status", "review"),
            "rule_version": str(payload.get("rule_version") or "current_repository_rules"),
            "policy_version": str(payload.get("policy_version") or "current_policy"),
            "model_version": str(payload.get("model_version") or "deterministic_twm_scaffold_current"),
            "baseline_version": str(payload.get("baseline_version") or "deterministic_twm_scaffold_current"),
            "random_seed": payload.get("random_seed"),
            "split_definition": {
                "split": str(payload.get("split") or "default"),
                "temporal_holdout": self._temporal_holdout_policy(payload),
                "holdout_example_count": holdout_count,
            },
            "target_heads": target_heads,
            "source_counts": source_counts,
            "failure_taxonomy": {
                "review_only_examples": review_only_count,
                "not_for_training_reasons": sorted(
                    {
                        str(reason)
                        for item in examples
                        for reason in item.not_for_training_reasons
                    }
                ),
            },
            "tail_statistics": {
                "example_count": len(examples),
                "holdout_example_count": holdout_count,
                "review_only_example_count": review_only_count,
            },
            "boundary_conditions": {
                "synthetic_or_not_for_production_rows": synthetic_or_not_for_production,
                "claim_boundary": "dataset trace supports reproducibility; it does not certify production accuracy",
            },
        }

    def _dynamics_training_example_semantic_payload(self, item: TwmDynamicsTrainingExample) -> dict[str, Any]:
        return {
            "state_version_id": item.state_version_id,
            "project_id": item.project_id,
            "split": item.split,
            "sample_type": item.sample_type,
            "current_state_summary": item.current_state_summary,
            "action": item.action.to_dict(),
            "scenario_context": item.scenario_context,
            "targets": item.targets,
            "labels": item.labels,
            "losses": item.losses,
            "evidence_gate": item.evidence_gate,
            "provenance": item.provenance,
            "not_for_training_reasons": item.not_for_training_reasons,
        }

    def _dynamics_sample_inventory(self, dataset: dict[str, Any]) -> dict[str, Any]:
        examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
        by_type: dict[str, int] = {}
        by_split: dict[str, int] = {}
        by_source: dict[str, int] = {}
        blocked_reason_counts: dict[str, int] = {}
        target_heads = {
            "future_latent_state": 0,
            "constraint_violation_probability": 0,
            "planning_utility_delta": 0,
            "uncertainty": 0,
            "calibration": 0,
            "action_mask": 0,
        }
        usable_count = 0
        review_count = 0
        observed_temporal_count = 0
        synthetic_temporal_count = 0
        scaffold_count = 0
        evidence_supported_count = 0
        action_mask_blocked_count = 0
        ranking_scores: list[float] = []
        for item in examples:
            sample_type = str(item.get("sample_type") or "unknown")
            split = str(item.get("split") or "candidate")
            labels = dict(item.get("labels") or {})
            provenance = dict(item.get("provenance") or {})
            targets = dict(item.get("targets") or {})
            reasons = list(item.get("not_for_training_reasons") or [])
            by_type[sample_type] = by_type.get(sample_type, 0) + 1
            by_split[split] = by_split.get(split, 0) + 1
            source = str(labels.get("supervision_source") or "unknown")
            by_source[source] = by_source.get(source, 0) + 1
            if source == "deterministic_scaffold":
                scaffold_count += 1
            if source == "state_snapshots" and provenance.get("ground_truth"):
                observed_temporal_count += 1
            if source == "state_snapshots" and not provenance.get("ground_truth"):
                synthetic_temporal_count += 1
            if not reasons:
                usable_count += 1
            else:
                review_count += 1
                for reason in reasons:
                    key = str(reason)
                    blocked_reason_counts[key] = blocked_reason_counts.get(key, 0) + 1
            if labels.get("evidence_supported"):
                evidence_supported_count += 1
            action_mask = dict(targets.get("action_mask") or {})
            if not action_mask.get("allowed", True):
                action_mask_blocked_count += 1
            for head in target_heads:
                if head in targets:
                    target_heads[head] += 1
            ranking_scores.append(float(safe_float(labels.get("ranking_score"), 0.0) or 0.0))
        total = len(examples)
        return {
            "example_count": total,
            "usable_example_count": usable_count,
            "review_example_count": review_count,
            "holdout_example_count": by_split.get("holdout", 0),
            "candidate_example_count": by_split.get("candidate", 0),
            "observed_temporal_example_count": observed_temporal_count,
            "synthetic_temporal_example_count": synthetic_temporal_count,
            "forecast_scaffold_example_count": by_type.get("action_conditioned_forecast", 0),
            "scaffold_example_count": scaffold_count,
            "evidence_supported_count": evidence_supported_count,
            "action_mask_blocked_count": action_mask_blocked_count,
            "by_sample_type": by_type,
            "by_split": by_split,
            "by_supervision_source": by_source,
            "blocked_reason_counts": blocked_reason_counts,
            "target_head_coverage": target_heads,
            "scaffold_ratio": round(scaffold_count / max(1, total), 4),
            "review_ratio": round(review_count / max(1, total), 4),
            "ranking_score_range": {
                "min": round(min(ranking_scores), 4) if ranking_scores else 0.0,
                "max": round(max(ranking_scores), 4) if ranking_scores else 0.0,
            },
        }

    def _dynamics_readiness_gates(
        self,
        *,
        state_version_id: str,
        dataset: dict[str, Any],
        inventory: dict[str, Any],
        thresholds: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
        summary = dict(dataset.get("summary") or {})
        loss_contract = dict(summary.get("loss_contract") or {})
        gates: dict[str, Any] = {
            "sample_volume": {
                "passed": inventory["example_count"] >= thresholds["min_total_examples"],
                "value": inventory["example_count"],
                "threshold": thresholds["min_total_examples"],
            },
            "usable_volume": {
                "passed": inventory["usable_example_count"] >= thresholds["min_usable_examples"],
                "value": inventory["usable_example_count"],
                "threshold": thresholds["min_usable_examples"],
            },
            "observed_temporal_support": {
                "passed": inventory["observed_temporal_example_count"] >= thresholds["min_observed_temporal_examples"],
                "value": inventory["observed_temporal_example_count"],
                "threshold": thresholds["min_observed_temporal_examples"],
            },
            "holdout_support": {
                "passed": inventory["holdout_example_count"] >= thresholds["min_holdout_examples"],
                "value": inventory["holdout_example_count"],
                "threshold": thresholds["min_holdout_examples"],
            },
            "scaffold_dependence": {
                "passed": inventory["scaffold_ratio"] <= thresholds["max_scaffold_ratio"],
                "value": inventory["scaffold_ratio"],
                "threshold": thresholds["max_scaffold_ratio"],
            },
            "review_pressure": {
                "passed": inventory["review_ratio"] <= thresholds["max_review_ratio"],
                "value": inventory["review_ratio"],
                "threshold": thresholds["max_review_ratio"],
            },
            "multi_head_targets": {
                "passed": all(count == inventory["example_count"] for count in inventory["target_head_coverage"].values()),
                "coverage": inventory["target_head_coverage"],
                "required_heads": [
                    "future_latent_state",
                    "constraint_violation_probability",
                    "planning_utility_delta",
                    "uncertainty",
                    "calibration",
                    "action_mask",
                ],
            },
            "loss_contract": {
                "passed": all(
                    key in loss_contract
                    for key in (
                        "transition_loss",
                        "constraint_loss",
                        "planning_ranking_loss",
                        "calibration_loss",
                        "uncertainty_calibration_loss",
                        "evidence_consistency_loss",
                        "action_mask_loss",
                    )
                ),
                "available_losses": sorted(loss_contract),
            },
        }
        geofm_payload = payload.get("geofm_gate_report")
        geofm_required = bool(thresholds["require_geofm_pass"])
        if isinstance(geofm_payload, dict):
            geofm_gate = dict(geofm_payload)
            geofm_source = "payload"
        elif self._dynamics_should_compute_geofm_gate(payload, thresholds):
            geofm_gate = self.geofm_ablation_gate(state_version_id, payload)
            geofm_source = "computed"
        else:
            geofm_gate = {
                "gate_status": "not_required",
                "decision": "not_required",
            }
            geofm_source = "skipped_optional_gate"

        causal_payload = payload.get("causal_calibration_report")
        causal_required = bool(thresholds["require_causal_pass"])
        if isinstance(causal_payload, dict):
            causal_gate = dict(causal_payload)
            causal_source = "payload"
        elif self._dynamics_should_compute_causal_gate(payload, thresholds):
            causal_gate = self.causal_calibration_report(state_version_id, payload)
            causal_source = "computed"
        else:
            causal_gate = {
                "status": "not_required",
                "method": "not_required",
            }
            causal_source = "skipped_optional_gate"

        gates["geofm_gate"] = {
            "passed": geofm_gate.get("gate_status") == "pass" or (not geofm_required and geofm_gate.get("gate_status") == "not_required"),
            "required": geofm_required,
            "status": geofm_gate.get("gate_status", "review"),
            "decision": geofm_gate.get("decision", "review_required"),
            "source": geofm_source,
        }
        gates["causal_calibration"] = {
            "passed": causal_gate.get("status") == "pass" or (not causal_required and causal_gate.get("status") == "not_required"),
            "required": causal_required,
            "status": causal_gate.get("status", "review"),
            "method": causal_gate.get("method", ""),
            "source": causal_source,
        }
        trainable_gates = [
            "sample_volume",
            "usable_volume",
            "observed_temporal_support",
            "holdout_support",
            "scaffold_dependence",
            "review_pressure",
            "multi_head_targets",
            "loss_contract",
        ]
        if thresholds["require_geofm_pass"]:
            trainable_gates.append("geofm_gate")
        if thresholds["require_causal_pass"]:
            trainable_gates.append("causal_calibration")
        blocked = [name for name in trainable_gates if not gates[name].get("passed")]
        review_only = [item.get("id") for item in examples if item.get("not_for_training_reasons")]
        gates["summary"] = {
            "blocked_gates": blocked,
            "review_only_example_ids": [item for item in review_only if item][:25],
            "claim_boundary": "trainable_dynamics_ready" if not blocked else "contract_or_review_only",
        }
        return gates

    def _dynamics_readiness_status(self, gate_results: dict[str, Any]) -> str:
        blocked = list((gate_results.get("summary") or {}).get("blocked_gates") or [])
        if not blocked:
            return "pass"
        hard = {"sample_volume", "usable_volume", "multi_head_targets", "loss_contract"}
        return "blocked" if any(item in hard for item in blocked) else "review"

    def _dynamics_training_scope(self, gate_results: dict[str, Any]) -> str:
        blocked = set((gate_results.get("summary") or {}).get("blocked_gates") or [])
        if not blocked:
            return "trainable_action_conditioned_dynamics"
        if blocked <= {"geofm_gate", "causal_calibration"}:
            return "trainable_core_dynamics_with_review_gated_enhancements"
        if blocked <= {"observed_temporal_support", "holdout_support", "scaffold_dependence", "review_pressure", "geofm_gate", "causal_calibration"}:
            return "limited_experiment_only"
        return "contract_only"

    def _dynamics_target_model_contract(
        self,
        dataset: dict[str, Any],
        gate_results: dict[str, Any],
        *,
        state_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        summary = dict(dataset.get("summary") or {})
        state_version_id = str(dataset.get("state_version_id") or "")
        if state_contract is None:
            state_contract = self.state_contract_report(state_version_id, {}) if state_version_id else {}
        return {
            "schema": "territory_world_model.trainable_dynamics_contract.v1",
            "state_encoder": {
                "required_tokens": ["parcel", "block", "township", "county"],
                "inputs": ["hierarchy_tokens", "explicit_gis_features", "constraint_state", "history_delta"],
                "geofm_policy": "B1 is retained only when geofm_gate.status == pass",
            },
            "state_contract": state_contract,
            "dynamics": {
                "conditioned_on": ["current_state", "action", "scenario", "causal_calibration"],
                "predicts": ["next_state", "constraint_state", "utility_state"],
            },
            "heads": [
                "future_latent_state",
                "constraint_violation_probability",
                "planning_utility_delta",
                "uncertainty",
                "action_mask",
            ],
            "loss_contract": dict(summary.get("loss_contract") or {}),
            "claim_gate": dict(gate_results.get("summary") or {}),
        }

    def _dynamics_readiness_recommendations(
        self,
        *,
        inventory: dict[str, Any],
        gate_results: dict[str, Any],
        thresholds: dict[str, Any],
    ) -> list[str]:
        recommendations: list[str] = []
        blocked = set((gate_results.get("summary") or {}).get("blocked_gates") or [])
        if "sample_volume" in blocked or "usable_volume" in blocked:
            recommendations.append("add more evidence-supported state/action/next-state examples before training neural dynamics")
        if "observed_temporal_support" in blocked:
            recommendations.append("replace synthetic state_snapshots rows with observed temporal transitions or lower the claim scope")
        if "holdout_support" in blocked:
            recommendations.append("reserve at least one temporal or spatial holdout split for future-state validation")
        if "scaffold_dependence" in blocked:
            recommendations.append("do not treat deterministic forecast scaffold samples as ground truth; use them only for contract tests or weak priors")
        if "review_pressure" in blocked:
            recommendations.append("resolve review-only examples, evidence gaps and action-mask blocks before promoting samples into training")
        if "geofm_gate" in blocked:
            recommendations.append("keep GeoFM gated out of the trainable core until B0/B1 downstream planning lift passes")
        if "causal_calibration" in blocked:
            recommendations.append("use balanced treated/control observations or a causal backend before upgrading counterfactual utility claims")
        if not recommendations:
            recommendations.append("start with a small train/holdout dynamics run and report planning lift separately from one-step fit")
        recommendations.append(
            f"current usable/total examples: {inventory['usable_example_count']}/{inventory['example_count']}; "
            f"observed temporal examples: {inventory['observed_temporal_example_count']} "
            f"(threshold {thresholds['min_observed_temporal_examples']})"
        )
        return recommendations

    def _dynamics_candidate_descriptor(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = self._payload_mapping(payload.get("candidate"))
        name = str(raw.get("model_name") or payload.get("model_name") or "deterministic_scaffold_baseline")
        version = str(raw.get("model_version") or payload.get("model_version") or "current")
        return {
            "model_name": name,
            "model_version": version,
            "model_family": str(raw.get("model_family") or payload.get("model_family") or "twm_dynamics"),
            "uses_geofm": bool(raw.get("uses_geofm", payload.get("uses_geofm", False))),
            "uses_causal_calibration": bool(raw.get("uses_causal_calibration", payload.get("uses_causal_calibration", False))),
            "is_scaffold_baseline": not bool(payload.get("predictions")),
            "metadata": dict(raw.get("metadata") or {}),
        }

    def _fit_candidate_descriptor(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = self._payload_mapping(payload.get("candidate"))
        return {
            "model_name": str(raw.get("model_name") or payload.get("model_name") or "hierarchical_baseline_dynamics"),
            "model_version": str(raw.get("model_version") or payload.get("model_version") or "fit_scaffold_v1"),
            "model_family": str(raw.get("model_family") or payload.get("model_family") or "action_conditioned_hierarchical_baseline"),
            "uses_geofm": bool(raw.get("uses_geofm", payload.get("uses_geofm", False))),
            "uses_causal_calibration": bool(raw.get("uses_causal_calibration", payload.get("uses_causal_calibration", True))),
            "is_scaffold_baseline": False,
            "metadata": dict(raw.get("metadata") or {}),
        }

    def _train_dynamics_trainer_descriptor(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = self._payload_mapping(payload.get("trainer") or payload.get("candidate") or payload.get("backend"))
        training_method = str(
            raw.get("training_method")
            or raw.get("backend")
            or raw.get("backend_type")
            or payload.get("training_method")
            or payload.get("backend")
            or "weighted_multi_head_group_means"
        )
        if training_method in {"transparent", "baseline", "scaffold"}:
            training_method = "weighted_multi_head_group_means"
        transformer = training_method in {"torch_spatiotemporal_transformer", "spatiotemporal_transformer_dynamics", "torch_spatiotemporal_transformer_dynamics"}
        neural = training_method in {"torch_multi_head_mlp", "neural_multi_head_mlp"}
        graph = training_method in {"torch_hierarchical_graph", "hierarchical_graph_dynamics", "torch_hierarchical_graph_dynamics"}
        default_name = (
            "spatiotemporal_transformer_dynamics"
            if transformer
            else "hierarchical_graph_token_dynamics"
            if graph
            else "hierarchical_neural_multi_head_dynamics"
            if neural
            else "hierarchical_trainable_dynamics_scaffold"
        )
        default_version = (
            "spatiotemporal_transformer_candidate_v1"
            if transformer
            else "hierarchical_graph_candidate_v1"
            if graph
            else "neural_candidate_v1"
            if neural
            else "trainer_scaffold_v1"
        )
        default_family = (
            "action_conditioned_spatiotemporal_transformer_dynamics"
            if transformer
            else "action_conditioned_hierarchical_graph_dynamics"
            if graph
            else "action_conditioned_hierarchical_neural_dynamics"
            if neural
            else "action_conditioned_hierarchical_trainable_scaffold"
        )
        model_name = str(raw.get("model_name") or payload.get("model_name") or default_name)
        model_version = str(raw.get("model_version") or payload.get("model_version") or default_version)
        return {
            "trainer_id": str(raw.get("trainer_id") or raw.get("id") or f"{model_name}:{model_version}"),
            "model_name": model_name,
            "model_version": model_version,
            "model_family": str(raw.get("model_family") or payload.get("model_family") or default_family),
            "training_method": training_method,
            "uses_geofm": bool(raw.get("uses_geofm", payload.get("uses_geofm", False))),
            "uses_causal_calibration": bool(raw.get("uses_causal_calibration", payload.get("uses_causal_calibration", False))),
            "is_scaffold_trainer": not (neural or graph or transformer),
            "metadata": dict(raw.get("metadata") or {}),
        }

    def _payload_mapping(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str) and value.strip():
            return {"model_name": value.strip(), "training_method": value.strip()}
        return {}

    def _use_neural_dynamics_trainer(self, trainer: dict[str, Any]) -> bool:
        return str(trainer.get("training_method") or "") in {"torch_multi_head_mlp", "neural_multi_head_mlp"}

    def _use_hierarchical_graph_dynamics_trainer(self, trainer: dict[str, Any]) -> bool:
        return str(trainer.get("training_method") or "") in {"torch_hierarchical_graph", "hierarchical_graph_dynamics", "torch_hierarchical_graph_dynamics"}

    def _use_spatiotemporal_transformer_dynamics_trainer(self, trainer: dict[str, Any]) -> bool:
        return str(trainer.get("training_method") or "") in {
            "torch_spatiotemporal_transformer",
            "spatiotemporal_transformer_dynamics",
            "torch_spatiotemporal_transformer_dynamics",
        }

    def _train_dynamics_parameters(self, dataset: dict[str, Any], objective_report: dict[str, Any], trainer: dict[str, Any]) -> dict[str, Any]:
        params = self._fit_baseline_dynamics_parameters(dataset)
        params["schema"] = "territory_world_model.trainable_dynamics_scaffold_parameters.v1"
        params["fit_method"] = trainer.get("training_method", "weighted_multi_head_group_means")
        params["trainer"] = dict(trainer)
        params["objective_contract"] = dict(objective_report.get("objective_contract") or {})
        params["loss_components"] = dict(objective_report.get("loss_components") or {})
        params["limitations"] = [
            "trainer scaffold uses transparent grouped statistics, not a neural dynamics optimizer",
            "replace this scaffold with a trainable model while preserving the same objective/backend contracts",
        ]
        return params

    def _train_dynamics_candidate_report(
        self,
        trainer: dict[str, Any],
        learned_parameters: dict[str, Any],
        predictions: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "schema": "territory_world_model.trainable_dynamics_candidate_report.v1",
            "status": "pass" if predictions else "review",
            "candidate": {
                "model_name": trainer.get("model_name", ""),
                "model_version": trainer.get("model_version", ""),
                "model_family": trainer.get("model_family", ""),
                "uses_geofm": bool(trainer.get("uses_geofm")),
                "uses_causal_calibration": bool(trainer.get("uses_causal_calibration")),
                "is_scaffold_baseline": False,
                "is_scaffold_trainer": bool(trainer.get("is_scaffold_trainer", True)),
            },
            "learned_parameters": learned_parameters,
            "predictions": predictions,
            "evaluation": {"status": "pass" if predictions else "review", "evidence_gate": {"status": "pass" if predictions else "review"}},
            "evidence_gate": {"status": "pass" if predictions else "review"},
        }

    def _neural_dynamics_candidate_report(
        self,
        trainer: dict[str, Any],
        learned_parameters: dict[str, Any],
        predictions: dict[str, dict[str, Any]],
        diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        training_status = str(learned_parameters.get("training_status") or diagnostics.get("status") or "review")
        status = "pass" if predictions and training_status == "pass" else "blocked" if training_status == "blocked" else "review"
        parameter_schema = learned_parameters.get("schema") or NEURAL_DYNAMICS_SCHEMA
        candidate_schema = (
            "territory_world_model.spatiotemporal_transformer_dynamics_candidate_report.v1"
            if parameter_schema == SPATIOTEMPORAL_TRANSFORMER_DYNAMICS_SCHEMA
            else
            "territory_world_model.hierarchical_graph_dynamics_candidate_report.v1"
            if parameter_schema == HIERARCHICAL_GRAPH_DYNAMICS_SCHEMA
            else "territory_world_model.neural_multi_head_dynamics_candidate_report.v1"
        )
        claim_scope = (
            "spatiotemporal_transformer_trainable_candidate_contract"
            if parameter_schema == SPATIOTEMPORAL_TRANSFORMER_DYNAMICS_SCHEMA
            else "hierarchical_graph_trainable_candidate_contract"
            if parameter_schema == HIERARCHICAL_GRAPH_DYNAMICS_SCHEMA
            else "trainable_neural_candidate_contract"
        )
        evidence_gate = {
            "status": status,
            "passed": status == "pass",
            "missing": [] if status == "pass" else ["neural_training_predictions"] if not predictions else ["neural_training_status"],
            "claim_scope": claim_scope if status == "pass" else "neural_candidate_review_or_blocked",
        }
        return {
            "schema": candidate_schema,
            "status": status,
            "candidate": {
                "model_name": trainer.get("model_name", ""),
                "model_version": trainer.get("model_version", ""),
                "model_family": trainer.get("model_family", ""),
                "uses_geofm": bool(trainer.get("uses_geofm")),
                "uses_causal_calibration": bool(trainer.get("uses_causal_calibration")),
                "is_scaffold_baseline": False,
                "is_scaffold_trainer": False,
                "parameter_schema": parameter_schema,
            },
            "learned_parameters": learned_parameters,
            "predictions": predictions,
            "evaluation": {"status": status, "evidence_gate": evidence_gate, "training_diagnostics": diagnostics},
            "evidence_gate": evidence_gate,
        }

    def _train_dynamics_evidence_gate(
        self,
        *,
        readiness: dict[str, Any],
        backend_report: dict[str, Any],
        objective_report: dict[str, Any],
        trainer: dict[str, Any],
    ) -> dict[str, Any]:
        missing: list[str] = []
        if readiness.get("status") != "pass":
            missing.append("readiness_pass")
        if backend_report and backend_report.get("status") != "pass":
            missing.append("backend_pass")
        elif not backend_report:
            missing.append("backend_report")
        objective_gate = dict(objective_report.get("evidence_gate") or {})
        if objective_gate.get("status") not in {"pass", "review"}:
            missing.append("objective_contract")
        if trainer.get("is_scaffold_trainer"):
            missing.append("non_scaffold_trainer")
        hard = {"readiness_pass", "backend_report", "objective_contract"}
        status = "pass" if not missing else "blocked" if any(item in hard for item in missing) else "review"
        return {
            "passed": status == "pass",
            "blocked": status == "blocked",
            "status": status,
            "missing": missing,
            "claim_scope": "trainer_candidate_ready" if status == "pass" else "trainer_scaffold_review_only" if status == "review" else "trainer_blocked",
        }

    def _train_dynamics_recommendations(self, evidence_gate: dict[str, Any], trainer: dict[str, Any]) -> list[str]:
        recommendations: list[str] = []
        missing = set(evidence_gate.get("missing") or [])
        if "readiness_pass" in missing:
            recommendations.append("improve observed temporal and usable examples before training a dynamics candidate")
        if "backend_pass" in missing or "backend_report" in missing:
            recommendations.append("ensure trained predictions pass dynamics_backend_report before forecast consumption")
        if "objective_contract" in missing:
            recommendations.append("fix training_objective_report coverage before training")
        if "non_scaffold_trainer" in missing:
            recommendations.append("replace scaffold trainer with a real neural/statistical optimizer before claiming trainable TWM dynamics")
        if not recommendations:
            recommendations.append("validate trained candidate through counterfactual rollout, beam planning and spatial holdout")
        return recommendations

    def _fit_baseline_dynamics_parameters(self, dataset: dict[str, Any]) -> dict[str, Any]:
        examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict) and not item.get("not_for_training_reasons")]
        by_action: dict[str, dict[str, Any]] = {}
        global_rows: list[dict[str, Any]] = []
        for item in examples:
            action = dict(item.get("action") or {})
            targets = dict(item.get("targets") or {})
            labels = dict(item.get("labels") or {})
            action_type = str(action.get("action_type") or "unknown")
            row = {
                "utility": float(safe_float(targets.get("planning_utility_delta"), 0.0) or 0.0),
                "constraint": float(safe_float(targets.get("constraint_violation_probability"), 0.0) or 0.0),
                "confidence": float(safe_float((targets.get("uncertainty") or {}).get("confidence"), 0.0) or 0.0),
                "ranking_score": float(safe_float(labels.get("ranking_score"), 0.0) or 0.0),
                "area_total": self._target_total_area(targets),
            }
            by_action.setdefault(action_type, {"rows": []})["rows"].append(row)
            global_rows.append(row)
        action_parameters = {}
        for action_type, payload in by_action.items():
            rows = list(payload.get("rows") or [])
            action_parameters[action_type] = self._aggregate_dynamics_rows(rows)
        return {
            "schema": "territory_world_model.hierarchical_baseline_dynamics_parameters.v1",
            "fit_method": "evidence_supported_action_group_means",
            "sample_count": len(global_rows),
            "action_parameters": action_parameters,
            "global_parameters": self._aggregate_dynamics_rows(global_rows),
            "limitations": [
                "baseline parameters are a transparent fit scaffold, not the final neural TWM dynamics",
                "future neural backend must preserve the same multi-head prediction contract and evidence gates",
            ],
        }

    def _aggregate_dynamics_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        area_values = [float(row["area_total"]) for row in rows if row.get("area_total") is not None]
        return {
            "sample_count": len(rows),
            "utility_mean": self._mean([float(row["utility"]) for row in rows]) or 0.0,
            "constraint_mean": self._mean([float(row["constraint"]) for row in rows]) or 0.0,
            "confidence_mean": self._mean([float(row["confidence"]) for row in rows]) or 0.0,
            "ranking_score_mean": self._mean([float(row["ranking_score"]) for row in rows]) or 0.0,
            "area_total_mean": self._mean(area_values),
        }

    def _predict_with_baseline_dynamics(self, dataset: dict[str, Any], learned_parameters: dict[str, Any]) -> dict[str, dict[str, Any]]:
        predictions: dict[str, dict[str, Any]] = {}
        action_parameters = dict(learned_parameters.get("action_parameters") or {})
        global_parameters = dict(learned_parameters.get("global_parameters") or {})
        for item in dataset.get("examples") or []:
            if not isinstance(item, dict):
                continue
            example_id = str(item.get("id") or "")
            if not example_id:
                continue
            action = dict(item.get("action") or {})
            targets = dict(item.get("targets") or {})
            params = dict(action_parameters.get(str(action.get("action_type") or "unknown")) or global_parameters)
            future_latent = self._predict_future_latent_with_params(targets, params)
            predictions[example_id] = {
                "future_latent_state": future_latent,
                "constraint_violation_probability": round(float(params.get("constraint_mean") or 0.0), 6),
                "planning_utility_delta": round(float(params.get("utility_mean") or 0.0), 6),
                "uncertainty": {
                    "confidence": round(float(params.get("confidence_mean") or 0.0), 6),
                    "source": "hierarchical_baseline_dynamics_fit",
                },
                "calibration": {
                    "calibrated_utility_delta": round(float(params.get("utility_mean") or 0.0), 6),
                    "ranking_score_mean": round(float(params.get("ranking_score_mean") or 0.0), 6),
                    "source": "hierarchical_baseline_dynamics_fit",
                },
                "action_mask": dict(targets.get("action_mask") or {}),
            }
        return predictions

    def _predict_future_latent_with_params(self, targets: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        target_latent = dict(targets.get("future_latent_state") or {})
        observed = dict(target_latent.get("observed_next") or target_latent.get("projected") or {})
        if not observed:
            return dict(target_latent)
        prediction = json.loads(json.dumps(observed))
        area_mean = params.get("area_total_mean")
        if area_mean is not None and "total_area_m2" in prediction:
            prediction["total_area_m2"] = round(float(area_mean), 6)
        return {
            "schema": "territory_world_model.predicted_latent_state.v1",
            "observed_next": prediction,
        }

    def _target_total_area(self, targets: dict[str, Any]) -> float | None:
        latent = dict(targets.get("future_latent_state") or {})
        observed = dict(latent.get("observed_next") or latent.get("projected") or {})
        value = safe_float(observed.get("total_area_m2"), None)
        return float(value) if value is not None else None

    def _fit_dynamics_recommendations(self, evidence_gate: dict[str, Any], learned_parameters: dict[str, Any]) -> list[str]:
        recommendations: list[str] = []
        if evidence_gate.get("status") != "pass":
            recommendations.append("do not promote this fitted candidate to production; use it as a transparent baseline for neural dynamics")
        else:
            recommendations.append("candidate passed evaluation gate; compare it against a neural hierarchical dynamics backend on the same holdout")
        if int(learned_parameters.get("sample_count") or 0) < 20:
            recommendations.append("increase observed temporal/action sample count before claiming cross-region generalization")
        recommendations.append("preserve action-conditioned multi-head output contract when replacing this baseline with trainable dynamics")
        return recommendations

    def _dynamics_predictions_for_evaluation(self, dataset: dict[str, Any], payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        raw_predictions = payload.get("predictions")
        if isinstance(raw_predictions, dict):
            return {str(key): dict(value) for key, value in raw_predictions.items() if isinstance(value, dict)}
        if isinstance(raw_predictions, list):
            result: dict[str, dict[str, Any]] = {}
            for item in raw_predictions:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("example_id") or item.get("id") or "")
                if key:
                    result[key] = dict(item.get("prediction") or item)
            return result
        predictions: dict[str, dict[str, Any]] = {}
        for example in dataset.get("examples") or []:
            if not isinstance(example, dict):
                continue
            prediction = dict(example.get("targets") or {})
            if prediction:
                predictions[str(example.get("id") or "")] = prediction
        return predictions

    def _dynamics_evaluation_metrics(
        self,
        dataset: dict[str, Any],
        predictions: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
        scored_examples = []
        transition_errors: list[float] = []
        transition_component_rows: list[dict[str, Any]] = []
        latent_quality_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        constraint_errors: list[float] = []
        utility_errors: list[float] = []
        uncertainty_confidences: list[float] = []
        ranking_pairs: list[tuple[float, float]] = []
        action_mask_matches = 0
        action_mask_count = 0
        ground_truth_count = 0
        holdout_count = 0
        payload_prediction_count = 0
        for example in examples:
            example_id = str(example.get("id") or "")
            prediction = dict(predictions.get(example_id) or {})
            if not prediction:
                continue
            payload_prediction_count += 1
            targets = dict(example.get("targets") or {})
            labels = dict(example.get("labels") or {})
            provenance = dict(example.get("provenance") or {})
            split = str(example.get("split") or "candidate")
            if split == "holdout":
                holdout_count += 1
            if provenance.get("ground_truth"):
                ground_truth_count += 1
            predicted_latent = dict(prediction.get("future_latent_state") or {})
            target_latent = dict(targets.get("future_latent_state") or {})
            if predicted_latent or target_latent:
                latent_quality_rows.append((predicted_latent, target_latent))
            transition_components = self._latent_transition_error_components(
                predicted=predicted_latent,
                target=target_latent,
            )
            transition_error = transition_components.get("aggregate_error")
            if transition_error is not None:
                transition_errors.append(float(transition_error))
                transition_component_rows.append(transition_components)
            if "constraint_violation_probability" in prediction and "constraint_violation_probability" in targets:
                constraint_errors.append(abs(float(safe_float(prediction.get("constraint_violation_probability"), 0.0) or 0.0) - float(safe_float(targets.get("constraint_violation_probability"), 0.0) or 0.0)))
            if "planning_utility_delta" in prediction and "planning_utility_delta" in targets:
                utility_errors.append(abs(float(safe_float(prediction.get("planning_utility_delta"), 0.0) or 0.0) - float(safe_float(targets.get("planning_utility_delta"), 0.0) or 0.0)))
                ranking_pairs.append((float(safe_float(prediction.get("planning_utility_delta"), 0.0) or 0.0), float(safe_float(labels.get("ranking_score"), 0.0) or 0.0)))
            uncertainty = dict(prediction.get("uncertainty") or {})
            if "confidence" in uncertainty:
                uncertainty_confidences.append(float(safe_float(uncertainty.get("confidence"), 0.0) or 0.0))
            predicted_mask = dict(prediction.get("action_mask") or {})
            target_mask = dict(targets.get("action_mask") or {})
            if predicted_mask or target_mask:
                action_mask_count += 1
                if bool(predicted_mask.get("allowed", True)) == bool(target_mask.get("allowed", True)):
                    action_mask_matches += 1
            scored_examples.append(example_id)
        metrics = {
            "evaluated_example_count": len(scored_examples),
            "ground_truth_example_count": ground_truth_count,
            "holdout_example_count": holdout_count,
            "mean_transition_error": self._mean(transition_errors),
            "mean_constraint_error": self._mean(constraint_errors),
            "mean_utility_error": self._mean(utility_errors),
            "ranking_correlation_proxy": self._ranking_correlation_proxy(ranking_pairs),
            "mean_confidence": self._mean(uncertainty_confidences),
            "action_mask_accuracy": round(action_mask_matches / max(1, action_mask_count), 4) if action_mask_count else None,
        }
        transition_component_metrics = {}
        for key in sorted({key for row in transition_component_rows for key in row if key != "aggregate_error"}):
            values = [float(row[key]) for row in transition_component_rows if row.get(key) is not None]
            transition_component_metrics[key] = self._mean(values)
        head_metrics = {
            "future_latent_state": {
                "count": len(transition_errors),
                "mean_error": metrics["mean_transition_error"],
                "components": transition_component_metrics,
                "latent_v2_quality": self._future_latent_state_v2_quality_report(latent_quality_rows),
            },
            "constraint_violation_probability": {"count": len(constraint_errors), "mae": metrics["mean_constraint_error"]},
            "planning_utility_delta": {"count": len(utility_errors), "mae": metrics["mean_utility_error"], "ranking_correlation_proxy": metrics["ranking_correlation_proxy"]},
            "uncertainty": {"count": len(uncertainty_confidences), "mean_confidence": metrics["mean_confidence"]},
            "action_mask": {"count": action_mask_count, "accuracy": metrics["action_mask_accuracy"]},
        }
        inventory = {
            "dataset_example_count": len(examples),
            "prediction_count": payload_prediction_count,
            "evaluated_example_ids": scored_examples[:50],
            "ground_truth_example_count": ground_truth_count,
            "holdout_example_count": holdout_count,
        }
        return metrics, head_metrics, inventory

    def _latent_transition_error_components(self, *, predicted: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
        observed = dict(target.get("observed_next") or target.get("projected") or target.get("decoded_state") or {})
        pred = dict(predicted.get("decoded_state") or predicted.get("observed_next") or predicted.get("projected") or predicted)
        observed_delta = dict(target.get("delta") or {})
        pred_delta = dict(predicted.get("transition_delta") or predicted.get("delta") or {})
        components: dict[str, Any] = {}

        observed_area = safe_float(observed.get("total_area_m2"), None)
        pred_area = safe_float(pred.get("total_area_m2"), None)
        if observed_area is not None and pred_area is not None:
            components["total_area_error"] = round(abs(float(pred_area) - float(observed_area)) / max(abs(float(observed_area)), 1.0), 6)

        observed_types = dict(observed.get("land_space_types") or {})
        pred_types = dict(pred.get("land_space_types") or {})
        area_errors = []
        count_errors = []
        delta_errors = []
        for key in sorted(set(observed_types) | set(pred_types)):
            target_payload = dict(observed_types.get(key) or {})
            pred_payload = dict(pred_types.get(key) or {})
            target_area = float(safe_float(target_payload.get("area_m2"), 0.0) or 0.0)
            pred_area_value = float(safe_float(pred_payload.get("area_m2"), 0.0) or 0.0)
            area_errors.append(abs(pred_area_value - target_area) / max(abs(target_area), 1.0))
            target_count = float(safe_float(target_payload.get("feature_count"), 0.0) or 0.0)
            pred_count = float(safe_float(pred_payload.get("feature_count"), 0.0) or 0.0)
            count_errors.append(abs(pred_count - target_count) / max(abs(target_count), 1.0))
            target_delta = float(safe_float(target_payload.get("area_delta_m2"), 0.0) or 0.0)
            pred_delta_value = float(safe_float(pred_payload.get("area_delta_m2"), 0.0) or 0.0)
            delta_errors.append(abs(pred_delta_value - target_delta) / max(abs(target_delta), 1.0))
        if area_errors:
            components["land_type_area_mae"] = self._mean(area_errors)
        if count_errors:
            components["land_type_feature_count_mae"] = self._mean(count_errors)
        if delta_errors:
            components["land_type_delta_mae"] = self._mean(delta_errors)

        delta_component_errors = []
        for key in ("total_area_delta_m2", "total_abs_area_delta_m2", "change_intensity"):
            target_value = safe_float(observed_delta.get(key), None)
            pred_value = safe_float(pred_delta.get(key), None)
            if target_value is not None and pred_value is not None:
                delta_component_errors.append(abs(float(pred_value) - float(target_value)) / max(abs(float(target_value)), 1.0))
        if delta_component_errors:
            components["delta_mae"] = self._mean(delta_component_errors)

        observed_vector = dict(target.get("latent_vector") or {})
        pred_vector = dict(predicted.get("latent_vector") or {})
        if observed_vector and pred_vector:
            vector_errors = []
            for key in sorted(set(observed_vector) | set(pred_vector)):
                target_value = float(safe_float(observed_vector.get(key), 0.0) or 0.0)
                pred_value = float(safe_float(pred_vector.get(key), 0.0) or 0.0)
                vector_errors.append(abs(pred_value - target_value) / max(abs(target_value), 1.0))
            components["latent_vector_mae"] = self._mean(vector_errors)

        numeric = [float(value) for key, value in components.items() if key.endswith("_error") or key.endswith("_mae")]
        components["aggregate_error"] = self._mean(numeric) if numeric else None
        return components

    def _future_latent_state_v2_quality_report(
        self,
        rows: list[tuple[dict[str, Any], dict[str, Any]]],
    ) -> dict[str, Any]:
        expected_schema = "territory_world_model.predicted_latent_state.v2"
        expected_boundary = "multi_dimensional_hierarchical_state_latent_not_full_geometry"
        prediction_count = 0
        target_count = 0
        v2_prediction_count = 0
        decoded_state_count = 0
        transition_delta_count = 0
        latent_vector_count = 0
        boundary_count = 0
        predicted_dimensions: set[str] = set()
        target_dimensions: set[str] = set()
        for predicted, target in rows:
            predicted = dict(predicted or {})
            target = dict(target or {})
            if predicted:
                prediction_count += 1
                if predicted.get("schema") == expected_schema:
                    v2_prediction_count += 1
                if isinstance(predicted.get("decoded_state"), dict) and predicted.get("decoded_state"):
                    decoded_state_count += 1
                if isinstance(predicted.get("transition_delta"), dict) and predicted.get("transition_delta"):
                    transition_delta_count += 1
                pred_vector = dict(predicted.get("latent_vector") or {})
                if pred_vector:
                    latent_vector_count += 1
                    predicted_dimensions.update(str(key) for key in pred_vector)
                predicted_dimensions.update(str(key) for key in list(predicted.get("dimensions") or []) if str(key))
                if predicted.get("representation_boundary") == expected_boundary:
                    boundary_count += 1
            if target:
                target_count += 1
                target_vector = dict(target.get("latent_vector") or {})
                target_dimensions.update(str(key) for key in target_vector)
                target_dimensions.update(str(key) for key in list(target.get("dimensions") or []) if str(key))

        missing: list[str] = []
        if prediction_count == 0:
            missing.append("future_latent_state_predictions")
        if prediction_count and v2_prediction_count < prediction_count:
            missing.append("predicted_latent_state_v2_schema")
        if prediction_count and decoded_state_count < prediction_count:
            missing.append("decoded_state")
        if prediction_count and transition_delta_count < prediction_count:
            missing.append("transition_delta")
        if prediction_count and latent_vector_count < prediction_count:
            missing.append("latent_vector")
        if v2_prediction_count and boundary_count < v2_prediction_count:
            missing.append("representation_boundary")

        missing_target_dimensions = sorted(target_dimensions - predicted_dimensions)
        extra_predicted_dimensions = sorted(predicted_dimensions - target_dimensions)
        if missing_target_dimensions:
            missing.append("target_dimension_coverage")

        return {
            "schema": "territory_world_model.future_latent_state_v2_quality.v1",
            "status": "pass" if not missing else "review",
            "coverage": {
                "prediction_count": prediction_count,
                "target_count": target_count,
                "v2_prediction_count": v2_prediction_count,
                "decoded_state_count": decoded_state_count,
                "transition_delta_count": transition_delta_count,
                "latent_vector_count": latent_vector_count,
                "representation_boundary_count": boundary_count,
                "v2_prediction_ratio": round(v2_prediction_count / max(1, prediction_count), 4),
                "decoded_state_ratio": round(decoded_state_count / max(1, prediction_count), 4),
                "transition_delta_ratio": round(transition_delta_count / max(1, prediction_count), 4),
                "latent_vector_ratio": round(latent_vector_count / max(1, prediction_count), 4),
            },
            "dimension_coverage": {
                "target_dimension_count": len(target_dimensions),
                "predicted_dimension_count": len(predicted_dimensions),
                "shared_dimension_count": len(target_dimensions & predicted_dimensions),
                "missing_target_dimensions": missing_target_dimensions,
                "extra_predicted_dimensions": extra_predicted_dimensions[:50],
            },
            "missing": missing,
            "claim_boundary": "quality gate for decoded multi-dimensional future latent summaries; it does not prove full parcel geometry generation or production accuracy",
        }

    def _latent_transition_error(self, *, predicted: dict[str, Any], target: dict[str, Any]) -> float | None:
        components = self._latent_transition_error_components(predicted=predicted, target=target)
        aggregate = components.get("aggregate_error")
        return float(aggregate) if aggregate is not None else None

    def _dynamics_evaluation_gate(
        self,
        *,
        readiness: dict[str, Any],
        candidate: dict[str, Any],
        metrics: dict[str, Any],
        eval_inventory: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        thresholds = dict(payload.get("evaluation_thresholds") or {})
        min_ground_truth = safe_int(thresholds.get("min_ground_truth_examples"), 1) or 1
        max_transition_error = float(safe_float(thresholds.get("max_mean_transition_error"), 0.15) or 0.15)
        max_constraint_error = float(safe_float(thresholds.get("max_mean_constraint_error"), 0.2) or 0.2)
        max_utility_error = float(safe_float(thresholds.get("max_mean_utility_error"), 0.25) or 0.25)
        min_ranking_proxy = float(safe_float(thresholds.get("min_ranking_correlation_proxy"), 0.0) or 0.0)
        missing: list[str] = []
        blocked = False
        if readiness.get("status") != "pass":
            missing.append("readiness_pass")
        if candidate.get("is_scaffold_baseline"):
            missing.append("non_scaffold_candidate")
        if eval_inventory.get("ground_truth_example_count", 0) < min_ground_truth:
            missing.append("ground_truth_holdout_examples")
            blocked = True
        if eval_inventory.get("prediction_count", 0) == 0:
            missing.append("candidate_predictions")
            blocked = True
        transition_error = metrics.get("mean_transition_error")
        if transition_error is None:
            missing.append("future_latent_state_metric")
        elif transition_error > max_transition_error:
            missing.append("future_latent_state_error")
        constraint_error = metrics.get("mean_constraint_error")
        if constraint_error is not None and constraint_error > max_constraint_error:
            missing.append("constraint_error")
        utility_error = metrics.get("mean_utility_error")
        if utility_error is not None and utility_error > max_utility_error:
            missing.append("utility_error")
        ranking_proxy = metrics.get("ranking_correlation_proxy")
        if ranking_proxy is not None and ranking_proxy < min_ranking_proxy:
            missing.append("planning_ranking_lift")
        return {
            "passed": not missing,
            "blocked": blocked,
            "status": "pass" if not missing else ("blocked" if blocked else "review"),
            "missing": missing,
            "thresholds": {
                "min_ground_truth_examples": min_ground_truth,
                "max_mean_transition_error": max_transition_error,
                "max_mean_constraint_error": max_constraint_error,
                "max_mean_utility_error": max_utility_error,
                "min_ranking_correlation_proxy": min_ranking_proxy,
            },
        }

    def _dynamics_evaluation_recommendations(
        self,
        evidence_gate: dict[str, Any],
        candidate: dict[str, Any],
        eval_inventory: dict[str, Any],
    ) -> list[str]:
        missing = set(evidence_gate.get("missing") or [])
        recommendations: list[str] = []
        if "readiness_pass" in missing:
            recommendations.append("pass dynamics readiness before using model evaluation to upgrade planning claims")
        if "non_scaffold_candidate" in missing and candidate.get("is_scaffold_baseline"):
            recommendations.append("evaluate an explicit trainable dynamics candidate instead of the deterministic scaffold baseline")
        if "ground_truth_holdout_examples" in missing:
            recommendations.append("add observed holdout transitions with provenance.ground_truth=true before reporting model accuracy")
        if "candidate_predictions" in missing:
            recommendations.append("provide candidate predictions keyed by dynamics training example id")
        if "future_latent_state_error" in missing:
            recommendations.append("improve next-state latent prediction before using rollout or MPC claims")
        if "planning_ranking_lift" in missing:
            recommendations.append("optimize planning ranking loss; one-step fit alone is not sufficient")
        if not recommendations:
            recommendations.append("evaluation gate passed; next report planning lift on counterfactual rollout holdouts")
        recommendations.append(f"evaluated examples: {eval_inventory.get('prediction_count', 0)}; ground-truth examples: {eval_inventory.get('ground_truth_example_count', 0)}")
        return recommendations

    def _mean(self, values: list[float]) -> float | None:
        if not values:
            return None
        return round(sum(values) / len(values), 6)

    def _ranking_correlation_proxy(self, pairs: list[tuple[float, float]]) -> float | None:
        if len(pairs) < 2:
            return None
        predicted_order = sorted(range(len(pairs)), key=lambda idx: pairs[idx][0])
        target_order = sorted(range(len(pairs)), key=lambda idx: pairs[idx][1])
        disagreements = sum(1 for left, right in zip(predicted_order, target_order) if left != right)
        return round(1.0 - disagreements / max(1, len(pairs)), 4)

    def _latent_from_snapshot_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        by_land_type: dict[str, dict[str, Any]] = {}
        total_area = 0.0
        total_features = 0
        for row in rows:
            land_type = str(row.get("land_space_type") or "unknown")
            area = float(safe_float(row.get("area_m2"), 0.0) or 0.0)
            area_delta = float(safe_float(row.get("area_delta_m2"), 0.0) or 0.0)
            feature_count = safe_int(row.get("feature_count"), 0)
            total_area += area
            total_features += feature_count
            by_land_type[land_type] = {
                "feature_count": feature_count,
                "area_m2": round(area, 4),
                "area_delta_m2": round(area_delta, 4),
                "source_dataset": row.get("source_dataset") or "",
                "synthetic": truthy(row.get("synthetic")),
                "not_for_production": truthy(row.get("not_for_production")),
            }
        return {
            "land_space_types": by_land_type,
            "total_area_m2": round(total_area, 4),
            "total_feature_count": total_features,
        }

    def _snapshot_transition_delta(self, current: dict[str, Any], observed_next: dict[str, Any]) -> dict[str, Any]:
        current_types = current.get("land_space_types") or {}
        next_types = observed_next.get("land_space_types") or {}
        all_types = sorted(set(current_types) | set(next_types))
        by_land_type: dict[str, dict[str, Any]] = {}
        total_abs_delta = 0.0
        for land_type in all_types:
            before = float((current_types.get(land_type) or {}).get("area_m2") or 0.0)
            after = float((next_types.get(land_type) or {}).get("area_m2") or 0.0)
            delta = after - before
            total_abs_delta += abs(delta)
            by_land_type[land_type] = {
                "area_delta_m2": round(delta, 4),
                "relative_delta": round(delta / max(abs(before), 1.0), 6),
            }
        return {
            "by_land_space_type": by_land_type,
            "total_area_delta_m2": round(total_abs_delta, 4),
            "net_area_delta_m2": round(float(observed_next.get("total_area_m2") or 0.0) - float(current.get("total_area_m2") or 0.0), 4),
        }

    def _transition_treatment_proxy(self, transition_delta: dict[str, Any]) -> float:
        by_land_type = transition_delta.get("by_land_space_type") or {}
        agricultural = float((by_land_type.get("agricultural_space") or {}).get("area_delta_m2") or 0.0)
        ecological = float((by_land_type.get("ecological_space") or {}).get("area_delta_m2") or 0.0)
        total = max(float(transition_delta.get("total_area_delta_m2") or 0.0), 1.0)
        return max(-0.25, min(0.25, (agricultural + ecological) / total * 0.08))

    def _dominant_stage(self, rows: list[dict[str, Any]]) -> str:
        counts: dict[str, int] = {}
        for row in rows:
            stage = str(row.get("temporal_stage") or "unknown")
            counts[stage] = counts.get(stage, 0) + 1
        return max(counts.items(), key=lambda item: item[1])[0] if counts else "unknown"

    def _temporal_holdout_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        policy = dict(payload.get("temporal_holdout") or {})
        holdout_year = safe_int(policy.get("holdout_year") or payload.get("holdout_year"), 0)
        return {
            "strategy": str(policy.get("strategy") or "last_year_holdout"),
            "holdout_year": holdout_year or None,
            "train_until_year": safe_int(policy.get("train_until_year"), 0) or None,
        }

    def _split_for_transition_year(self, next_year: int, holdout_policy: dict[str, Any]) -> str:
        holdout_year = holdout_policy.get("holdout_year")
        train_until_year = holdout_policy.get("train_until_year")
        if holdout_year and next_year >= int(holdout_year):
            return "holdout"
        if train_until_year and next_year > int(train_until_year):
            return "holdout"
        if holdout_policy.get("strategy") == "last_year_holdout":
            return "holdout"
        return "candidate"

    def _state_hierarchy_tokens(self, state: TwmStateVersion) -> dict[str, Any]:
        summary = dict(state.summary or {})
        return {
            "schema": "territory_world_model.hierarchy_tokens.v1",
            "object_counts_by_role": dict(summary.get("object_counts_by_role") or {}),
            "relation_counts_by_type": dict(summary.get("relation_counts_by_type") or {}),
            "metric_crs": summary.get("metric_crs", ""),
        }

    def _state_contract_hierarchy(
        self,
        state: TwmStateVersion,
        objects: list[TwmStateObject],
        relations: list[TwmStateRelation],
    ) -> dict[str, Any]:
        object_counts: dict[str, int] = {}
        for obj in objects:
            role = obj.canonical_role or obj.source_role or obj.object_type or "unknown"
            object_counts[role] = object_counts.get(role, 0) + 1
        relation_counts: dict[str, int] = {}
        for rel in relations:
            rel_type = rel.relation_type or rel.predicate or "unknown"
            relation_counts[rel_type] = relation_counts.get(rel_type, 0) + 1

        token_specs = [
            self._state_contract_token_spec(
                "parcel",
                object_counts,
                required=True,
                aliases=("parcel", "parcel_current"),
                relations=relation_counts,
                required_relations=("annual_change_of_parcel",),
            ),
            self._state_contract_token_spec(
                "block",
                object_counts,
                required=True,
                aliases=("block", "planning_zone"),
                relations=relation_counts,
                required_relations=("project_overlaps_planning_zone",),
                note="planning_zone is accepted only as a review-level block proxy until explicit block/township aggregation is available",
            ),
            self._state_contract_token_spec(
                "township",
                object_counts,
                required=True,
                aliases=("township",),
                fallback_aliases=("admin_unit",),
                note="admin_unit can support regional context, but does not prove township-scale tokenization without level metadata",
            ),
            {
                "level": "county",
                "status": "available" if state.project_id else "missing",
                "required": True,
                "object_count": 1 if state.project_id else 0,
                "source_roles": ["project.region_code"],
                "required_relations": [],
                "relation_count": 0,
                "claim": "county/context token is derived from the project and state version metadata",
            },
        ]
        missing_required = [item["level"] for item in token_specs if item.get("required") and item.get("status") == "missing"]
        review_required = [item["level"] for item in token_specs if item.get("status") == "review"]
        return {
            "schema": "territory_world_model.hierarchical_state_contract.v1",
            "state_version_id": state.id,
            "metric_crs": (state.summary or {}).get("metric_crs", ""),
            "tokens": token_specs,
            "object_counts_by_role": object_counts,
            "relation_counts_by_type": relation_counts,
            "missing_required_levels": missing_required,
            "review_required_levels": review_required,
            "flat_vector_allowed": False,
            "encoder_policy": "hierarchical parcel/block/township/county tokens with explicit GIS features and constraint masks",
        }

    def _state_contract_token_spec(
        self,
        level: str,
        object_counts: dict[str, int],
        *,
        required: bool,
        aliases: tuple[str, ...],
        relations: dict[str, int] | None = None,
        required_relations: tuple[str, ...] = (),
        fallback_aliases: tuple[str, ...] = (),
        note: str = "",
    ) -> dict[str, Any]:
        direct_count = sum(int(object_counts.get(alias, 0)) for alias in aliases)
        fallback_count = sum(int(object_counts.get(alias, 0)) for alias in fallback_aliases)
        status = "available" if direct_count > 0 else "review" if fallback_count > 0 else "missing"
        relation_counts = {name: int((relations or {}).get(name, 0)) for name in required_relations}
        return {
            "level": level,
            "status": status,
            "required": required,
            "object_count": direct_count or fallback_count,
            "source_roles": list(aliases if direct_count > 0 else fallback_aliases),
            "fallback_source_roles": list(fallback_aliases),
            "required_relations": list(required_relations),
            "relation_count": sum(relation_counts.values()),
            "relation_counts": relation_counts,
            "claim": "explicit token level available" if status == "available" else "review-only proxy available" if status == "review" else "required token level missing",
            "note": note,
        }

    def _state_contract_feature_channels(
        self,
        state: TwmStateVersion,
        objects: list[TwmStateObject],
        relations: list[TwmStateRelation],
    ) -> dict[str, Any]:
        quality_summary = dict(state.quality_summary or {})
        object_feature_keys = sorted({key for obj in objects[:500] for key in (obj.attributes or {})})[:40]
        relation_metric_keys = sorted({key for rel in relations[:500] for key in (rel.metrics or {})})[:40]
        not_for_production = sum(1 for obj in objects if obj.not_for_production)
        synthetic = sum(1 for obj in objects if obj.synthetic)
        return {
            "schema": "territory_world_model.state_feature_channels.v1",
            "explicit_gis_features": {
                "available": bool(object_feature_keys or relation_metric_keys),
                "object_attribute_keys_sample": object_feature_keys,
                "relation_metric_keys_sample": relation_metric_keys,
                "metric_crs": (state.summary or {}).get("metric_crs", ""),
            },
            "quality_features": {
                "quality_summary": quality_summary,
                "synthetic_object_count": synthetic,
                "not_for_production_object_count": not_for_production,
            },
            "state_inputs": [
                "object_attributes",
                "relation_metrics",
                "geometry_bbox",
                "quality_summary",
                "constraint_channels",
                "history_delta",
                "optional_geofm_embedding",
            ],
        }

    def _state_contract_constraint_channels(
        self,
        rule_hits: list[TwmRuleHit],
        evidence_items: list[TwmEvidenceItem],
        review_tasks: list[TwmReviewTask],
    ) -> dict[str, Any]:
        severity_counts: dict[str, int] = {}
        for hit in rule_hits:
            severity_counts[hit.severity or "unknown"] = severity_counts.get(hit.severity or "unknown", 0) + 1
        open_reviews = sum(1 for item in review_tasks if item.status not in {"approved", "closed", "resolved"})
        hard_hit_count = sum(severity_counts.get(item, 0) for item in ("blocking", "critical", "high"))
        return {
            "schema": "territory_world_model.constraint_channels.v1",
            "rule_hit_count": len(rule_hits),
            "severity_counts": severity_counts,
            "hard_or_high_risk_hit_count": hard_hit_count,
            "evidence_item_count": len(evidence_items),
            "review_task_count": len(review_tasks),
            "open_review_task_count": open_reviews,
            "channels": [
                "constraint_mask",
                "constraint_violation_probability_target",
                "rule_severity_counts",
                "evidence_coverage",
                "review_pressure",
                "approval_consistency",
            ],
            "status": "pass" if evidence_items and open_reviews == 0 else "review",
        }

    def _state_contract_temporal_support(self, state: TwmStateVersion, payload: dict[str, Any]) -> dict[str, Any]:
        bundle_root = self._state_bundle_root(state)
        snapshots_path = self._find_auxiliary_table(bundle_root, "state_snapshots.csv") if bundle_root else None
        row_count = 0
        year_count = 0
        synthetic_count = 0
        not_for_production_count = 0
        years: list[int] = []
        if snapshots_path is not None:
            try:
                rows = read_csv(snapshots_path)
            except Exception:
                rows = []
            row_count = len(rows)
            years = sorted({safe_int(row.get("snapshot_year"), -1) for row in rows if safe_int(row.get("snapshot_year"), -1) >= 0})
            year_count = len(years)
            synthetic_count = sum(1 for row in rows if truthy(row.get("synthetic")))
            not_for_production_count = sum(1 for row in rows if truthy(row.get("not_for_production")))
        min_years = safe_int((payload.get("thresholds") or {}).get("min_temporal_years"), 2) if isinstance(payload.get("thresholds"), dict) else 2
        status = "pass" if year_count >= int(min_years or 2) and not not_for_production_count else "review" if row_count else "missing"
        return {
            "schema": "territory_world_model.history_delta_contract.v1",
            "status": status,
            "source_table": str(snapshots_path) if snapshots_path else "",
            "row_count": row_count,
            "year_count": year_count,
            "years": years,
            "synthetic_row_count": synthetic_count,
            "not_for_production_row_count": not_for_production_count,
            "history_delta_available": year_count >= 2,
            "channels": ["observed_next_state", "delta_area_by_land_space_type", "temporal_stage", "holdout_split"],
        }

    def _state_contract_geofm_policy(self, state: TwmStateVersion, payload: dict[str, Any]) -> dict[str, Any]:
        geofm_report = payload.get("geofm_gate_report")
        if isinstance(geofm_report, dict):
            gate_status = str(geofm_report.get("gate_status") or geofm_report.get("status") or "review")
            decision = str(geofm_report.get("decision") or "review_required")
            vector_inventory = dict((geofm_report.get("summary") or {}).get("vector_inventory") or {})
        else:
            vector_inventory = self._geofm_vector_inventory(state)
            gate_status = "review"
            decision = "run_geofm_ablation_gate_before_using_embeddings"
        return {
            "schema": "territory_world_model.geofm_state_gate_policy.v1",
            "gate_status": gate_status,
            "decision": decision,
            "vector_inventory": vector_inventory,
            "default_role": "optional_enhancement",
            "retention_rule": "retain GeoFM embeddings only when B0/B1 downstream planning lift passes evidence gate",
            "state_encoder_policy": "explicit GIS features remain primary; GeoFM embedding is gated and ablatable",
        }

    def _state_contract_claim_ladder(
        self,
        *,
        token_contract: dict[str, Any],
        constraint_channels: dict[str, Any],
        temporal_support: dict[str, Any],
        geofm_policy: dict[str, Any],
    ) -> dict[str, Any]:
        facts = {
            "state_build_pass": {
                "status": "pass" if not token_contract.get("missing_required_levels") and constraint_channels.get("evidence_item_count", 0) > 0 else "blocked",
                "hierarchy_status": "pass" if not token_contract.get("missing_required_levels") else "blocked",
                "missing_required_levels": list(token_contract.get("missing_required_levels") or []),
                "evidence_item_count": int(constraint_channels.get("evidence_item_count", 0) or 0),
            },
            "future_state_holdout_pass": {
                "status": "pass" if temporal_support.get("status") == "pass" else "review",
                "temporal_support_status": temporal_support.get("status", "missing"),
                "history_delta_available": bool(temporal_support.get("history_delta_available")),
                "year_count": int(temporal_support.get("year_count", 0) or 0),
            },
            "geofm_gate_decision": {
                "status": "pass" if geofm_policy.get("gate_status") == "pass" else "review",
                "gate_status": geofm_policy.get("gate_status", "review"),
                "decision": geofm_policy.get("decision", "review_required"),
            },
        }
        return evaluate_claim_ladder(facts)

    def _state_contract_claim_boundary(
        self,
        *,
        token_contract: dict[str, Any],
        constraint_channels: dict[str, Any],
        temporal_support: dict[str, Any],
        geofm_policy: dict[str, Any],
        claim_ladder: dict[str, Any],
    ) -> dict[str, Any]:
        missing = list(token_contract.get("missing_required_levels") or [])
        review_levels = list(token_contract.get("review_required_levels") or [])
        blockers: list[str] = []
        review: list[str] = []
        if missing:
            blockers.append("missing_required_hierarchy_tokens")
        if review_levels:
            review.append("review_required_hierarchy_tokens")
        if constraint_channels.get("evidence_item_count", 0) == 0:
            blockers.append("no_evidence_items")
        if constraint_channels.get("open_review_task_count", 0) > 0:
            review.append("open_review_tasks")
        if not temporal_support.get("history_delta_available"):
            review.append("history_delta_missing")
        elif temporal_support.get("status") != "pass":
            review.append("history_delta_review_only")
        if geofm_policy.get("gate_status") != "pass":
            review.append("geofm_not_promoted")
        status = "blocked" if blockers else "review" if review else "pass"
        claim_level = str(claim_ladder.get("current_level") or "L0")
        claim_status = str(claim_ladder.get("current_claim") or "unsupported")
        return {
            "status": status,
            "claim_scope": "state_contract_ready_for_trainable_dynamics" if status == "pass" else "contract_or_review_only" if status == "review" else "insufficient_for_hierarchical_twm",
            "claim_level": claim_level,
            "claim_status": claim_status,
            "blockers": blockers,
            "review_items": review,
            "allowed_claims": [
                "hierarchical_state_scaffold",
                "deterministic_forecast_contract",
                "review_gated_planning_consumer",
            ]
            + (["trainable_dynamics_input_contract"] if status in {"pass", "review"} else [])
            + (["state_prediction_supported"] if claim_level in {"L1", "L2", "L3", "L4"} else []),
            "disallowed_claims": [
                "flat_vector_world_model",
                "ungated_geofm_world_model",
                "production_ready_trainable_dynamics",
            ],
        }

    def _state_contract_recommendations(
        self,
        *,
        token_contract: dict[str, Any],
        constraint_channels: dict[str, Any],
        temporal_support: dict[str, Any],
        geofm_policy: dict[str, Any],
    ) -> list[str]:
        recommendations: list[str] = []
        missing = list(token_contract.get("missing_required_levels") or [])
        if missing:
            recommendations.append(f"add explicit hierarchical token inputs for: {', '.join(missing)}")
        review_levels = list(token_contract.get("review_required_levels") or [])
        if review_levels:
            recommendations.append(f"replace review-level hierarchy proxies with authoritative tokens for: {', '.join(review_levels)}")
        if constraint_channels.get("open_review_task_count", 0) > 0:
            recommendations.append("resolve open review tasks before promoting the state contract to production training")
        if not temporal_support.get("history_delta_available"):
            recommendations.append("add observed state_snapshots.csv or equivalent temporal transitions for history_delta supervision")
        elif temporal_support.get("status") != "pass":
            recommendations.append("separate synthetic/not-for-production temporal rows from trainable history_delta labels")
        if geofm_policy.get("gate_status") != "pass":
            recommendations.append("run GeoFM B0/B1 downstream planning ablation before enabling embeddings in the state encoder")
        if not recommendations:
            recommendations.append("use this state contract as the canonical input schema for dynamics training and beam planning")
        return recommendations

    def _action_from_payload(self, payload: dict[str, Any]) -> TerritoryWorldModelAction:
        return TerritoryWorldModelAction(
            action_type=str(payload.get("action_type") or "inspect"),
            target_role=str(payload.get("target_role") or "project"),
            target_objects=[str(item) for item in payload.get("target_objects") or []],
            spatial_scope=dict(payload.get("spatial_scope") or {}),
            magnitude=float(payload.get("magnitude") or 1.0),
            scenario=str(payload.get("scenario") or "baseline"),
            description=str(payload.get("description") or ""),
            legal_intent=str(payload.get("legal_intent") or ""),
            execution_mask=dict(payload.get("execution_mask") or {}),
            parameters=dict(payload.get("parameters") or {}),
            treatment=str(payload.get("treatment") or ""),
        )

    def list_projects_summary(self) -> dict[str, Any]:
        projects = self.list_projects()
        bindings = [item.to_dict() for item in self.repository.list_layer_bindings()]
        states = [item.to_dict() for item in self.repository.list_state_versions()]
        return {
            "projects": projects,
            "layer_bindings": bindings,
            "states": states,
            "counts": {
                "project_count": len(projects),
                "layer_binding_count": len(bindings),
                "state_count": len(states),
            },
        }


def get_territory_world_model_service() -> TerritoryWorldModelService:
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = TerritoryWorldModelService()
    return _INSTANCE


def reset_territory_world_model_service() -> None:
    global _INSTANCE
    with _INSTANCE_LOCK:
        _INSTANCE = None
