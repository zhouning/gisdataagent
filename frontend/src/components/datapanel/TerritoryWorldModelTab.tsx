import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  FileCheck2,
  GitBranch,
  Layers3,
  Loader2,
  Play,
  RefreshCw,
  Route,
  ShieldCheck,
  SlidersHorizontal,
} from 'lucide-react';

type RunKey =
  | 'status'
  | 'scenarios'
  | 'positioning'
  | 'claimMatrix'
  | 'baselineImport'
  | 'baselineTemplates'
  | 'baselineExport'
  | 'baselinePipeline'
  | 'baselineCompare'
  | 'dataFoundation'
  | 'baselineCards'
  | 'projects'
  | 'create'
  | 'states'
  | 'build'
  | 'evaluate'
  | 'forecast'
  | 'validation'
  | 'audit'
  | 'candidates'
  | 'beam';

interface TwmProject {
  id: string;
  name?: string;
  region_code?: string;
  business_scenario?: string;
  status?: string;
  owner_username?: string;
  created_at?: string;
}

interface TwmStateVersion {
  id: string;
  project_id: string;
  label?: string;
  object_count?: number;
  relation_count?: number;
  build_status?: string;
  quality_summary?: Record<string, any>;
  summary?: Record<string, any>;
  created_at?: string;
}

interface TwmStatus {
  status: string;
  version: string;
  repository?: Record<string, any>;
  capabilities?: Record<string, boolean>;
  updated_at?: string;
}

interface TwmHit {
  id: string;
  rule_id?: string;
  severity?: string;
  hit_status?: string;
  risk_score?: number;
  explanation?: string;
  subject_object_id?: string;
  target_object_id?: string;
}

interface TwmBusinessScenario {
  id: string;
  label: string;
  decision_question?: string;
  operator_goal?: string;
  primary_roles?: string[];
  required_evidence?: string[];
  default_action_type?: string;
  default_target_role?: string;
  default_scenario?: string;
  default_evidence_coverage?: number;
  default_horizon?: number;
  decision_outputs?: string[];
  guardrails?: string[];
}

interface TwmResearchPositioning {
  research_question?: string;
  core_technology?: Array<{ name: string; claim?: string; why_it_matters?: string }>;
  innovation_hypotheses?: Array<{ hypothesis: string; test?: string }>;
  unmet_need_hypotheses?: string[];
  baselines_to_beat?: string[];
  falsification_conditions?: string[];
  minimum_evaluation_plan?: string[];
  claim_boundary?: string;
}

interface TwmDataFoundationAssessment {
  schema?: string;
  status?: string;
  landing_readiness?: {
    status?: string;
    verdict?: string;
    production_deployment_supported?: boolean;
    engineering_mvp_supported?: boolean;
    business_review_scaffold_supported?: boolean;
    predictive_or_causal_claim_supported?: boolean;
    key_blockers?: string[];
  };
  datasets?: Array<{
    id: string;
    label: string;
    path?: string;
    nature?: string;
    positioning?: string;
    not_for_production?: boolean;
    total_count?: number;
    synthetic_count?: number;
    not_for_production_count?: number;
    files?: Array<{
      path: string;
      count?: number;
      synthetic_count?: number;
      not_for_production_count?: number;
      unit?: string;
    }>;
  }>;
  validation_snapshot?: {
    production_ready_observed_history_rows?: number;
    production_policy_history_status?: string;
    production_policy_history_row_count?: number;
    structural_fixture?: { row_count?: number; pair_count?: number; structural_status?: string; default_status?: string };
    synthetic_experiment?: {
      row_count?: number;
      pair_count?: number;
      region_count?: number;
      period_count?: number;
      action_mask_allowed_count?: number;
      action_mask_blocked_count?: number;
      structural_status?: string;
      default_status?: string;
    };
  };
  supported_problems?: Array<{ problem: string; support?: string }>;
  unsupported_claims?: Array<{ claim: string; reason?: string }>;
  required_next_data?: Array<{ priority?: string; data: string; minimum?: string; unlocks?: string }>;
  mentor_answer?: { short_answer?: string; research_judgment?: string };
}

interface TwmResearchClaimMatrix {
  schema?: string;
  status?: string;
  claim_boundary?: string;
  current_data_gate?: {
    production_ready_observed_history_rows?: number;
    production_policy_history_row_count?: number;
    production_deployment_supported?: boolean;
    predictive_or_causal_claim_supported?: boolean;
  };
  claims?: Array<{
    claim_id: string;
    claim: string;
    business_need?: string;
    core_technology?: string;
    baseline?: string;
    current_status?: string;
    current_evidence?: string;
    falsification?: string;
    gate?: {
      status?: string;
      claim_level?: string;
      missing?: string[];
    };
    metrics?: Array<{ name: string; direction?: string; minimum_pass?: number; maximum_pass?: number }>;
  }>;
  baselines?: Array<{ baseline_id: string; label: string; why_needed?: string }>;
  next_experiments?: Array<{ priority?: string; experiment: string; question?: string; decision?: string }>;
  mentor_answer?: string;
}

interface TwmBaselineComparisonReport {
  schema?: string;
  status?: string;
  upgrade_decision?: string;
  claim?: { claim_id?: string; claim?: string };
  baseline?: { baseline_id?: string; label?: string };
  inputs?: {
    provided_metric_count?: number;
    passed_metric_count?: number;
    twm_metric_count?: number;
    baseline_metric_count?: number;
    twm_metrics_source?: string;
    baseline_metrics_source?: string;
    twm_case_source?: string;
    baseline_case_source?: string;
    twm_case_count?: number;
    baseline_case_count?: number;
    metric_source_errors?: Record<string, string | null | undefined>;
  };
  metric_comparisons?: Array<{
    name: string;
    status?: string;
    twm_value?: number;
    baseline_value?: number;
    delta?: number;
  }>;
  evidence_gate?: { status?: string; missing?: string[]; metrics_pass?: boolean; claim_gate_clear?: boolean };
  next_actions?: string[];
  scenario_card?: { scenario_id?: string; scenario_type?: string; status?: string; metadata_kind?: string };
}

interface TwmBaselineExportValidationReport {
  schema?: string;
  status?: string;
  claim?: { claim_id?: string; baseline_id?: string };
  export_spec?: { export_type?: string; baseline_id?: string; label?: string };
  sources?: {
    twm?: { source?: string; row_count?: number; error?: string | null };
    baseline?: { source?: string; row_count?: number; error?: string | null };
  };
  column_inventory?: {
    join_key?: string;
    twm?: { row_count?: number; unique_join_id_count?: number; duplicate_join_ids?: string[]; not_for_production_rows?: number; synthetic_rows?: number };
    baseline?: { row_count?: number; unique_join_id_count?: number; duplicate_join_ids?: string[]; not_for_production_rows?: number; synthetic_rows?: number };
    missing_required?: { twm?: string[]; baseline?: string[]; claim_parser?: string[] };
  };
  coverage?: {
    overlap_count?: number;
    twm_unique_case_count?: number;
    baseline_unique_case_count?: number;
    coverage_ratio?: number;
    twm_only_count?: number;
    baseline_only_count?: number;
  };
  parser_compatibility?: {
    status?: string;
    comparable_metrics?: string[];
    twm_recovered_metrics?: string[];
    baseline_recovered_metrics?: string[];
  };
  blocking_errors?: string[];
  warnings?: string[];
  next_actions?: string[];
  claim_boundary?: string;
}

interface TwmBaselineExportImport {
  schema?: string;
  status?: string;
  path?: string;
  filename?: string;
  source_role?: string;
  row_count?: number;
  columns?: string[];
  preview_metrics?: Record<string, number>;
  next_actions?: string[];
}

interface TwmBaselineExportTemplates {
  schema?: string;
  purpose?: string;
  templates?: TwmBaselineExportTemplate[];
  global_sanitization_rules?: string[];
  validation_flow?: string[];
  claim_boundary?: string;
}

interface TwmBaselineExportTemplate {
  claim_id: string;
  baseline_id?: string;
  export_type?: string;
  label?: string;
  business_question?: string;
  same_case_join_key?: string;
  twm_filename?: string;
  baseline_filename?: string;
  required_columns?: string[];
  recommended_columns?: string[];
  headers?: { twm?: string[]; baseline?: string[] };
  csv_header?: { twm?: string; baseline?: string };
  sample_rows?: { twm?: Record<string, any>[]; baseline?: Record<string, any>[] };
  field_descriptions?: Array<{
    name: string;
    required?: boolean;
    description?: string;
    metric_use?: string;
    sanitization?: string;
  }>;
  metric_column_map?: Array<{ metric: string; columns?: string[]; supports_claim_when?: string }>;
  collection_steps?: string[];
  production_collection?: { sampling_unit?: string; minimum_real_rows?: number; minimum_overlap_ratio?: number; notes?: string };
  minimum_real_data_gate?: { same_case_join_key?: string; minimum_overlap_ratio?: number; minimum_real_rows?: number; claim_gate_missing?: string[] };
  validation_payload_template?: Record<string, any>;
  not_for_production?: boolean;
}

interface TwmBaselineEvidencePipelineReport {
  schema?: string;
  status?: string;
  pipeline_decision?: string;
  claim_id?: string;
  baseline_id?: string;
  steps?: {
    export_validation?: {
      status?: string;
      blocking_errors?: string[];
      warnings?: string[];
      scenario_card?: { scenario_id?: string; scenario_type?: string; status?: string; metadata_kind?: string };
    };
    baseline_comparison?: {
      status?: string;
      upgrade_decision?: string;
      skipped_reason?: string;
      scenario_card?: { scenario_id?: string; scenario_type?: string; status?: string; metadata_kind?: string };
    };
  };
  export_validation?: TwmBaselineExportValidationReport;
  baseline_comparison?: TwmBaselineComparisonReport | null;
  next_actions?: string[];
  claim_boundary?: string;
}

interface TwmScenarioCard {
  id: string;
  project_id?: string;
  base_state_version_id?: string;
  name?: string;
  scenario_type?: string;
  status?: string;
  source_model?: string;
  created_at?: string;
  input_changes?: Record<string, any>;
  metadata?: {
    kind?: string;
    claim?: { claim_id?: string };
    baseline?: { baseline_id?: string };
    baseline_sources?: {
      twm_case_count?: number;
      baseline_case_count?: number;
      twm_case_source?: string;
      baseline_case_source?: string;
      metric_source_errors?: Record<string, string | null | undefined>;
    };
    sources?: {
      twm?: { source?: string; row_count?: number; error?: string | null };
      baseline?: { source?: string; row_count?: number; error?: string | null };
    };
    coverage?: { overlap_count?: number; coverage_ratio?: number };
    column_inventory?: {
      join_key?: string;
      missing_required?: { twm?: string[]; baseline?: string[]; claim_parser?: string[] };
      twm?: { row_count?: number; unique_join_id_count?: number; synthetic_rows?: number; not_for_production_rows?: number };
      baseline?: { row_count?: number; unique_join_id_count?: number; synthetic_rows?: number; not_for_production_rows?: number };
    };
    parser_compatibility?: { comparable_metrics?: string[]; twm_recovered_metrics?: string[]; baseline_recovered_metrics?: string[] };
    blocking_errors?: string[];
    warnings?: string[];
    metric_comparisons?: TwmBaselineComparisonReport['metric_comparisons'];
    evidence_gate?: { missing?: string[]; metrics_pass?: boolean; claim_gate_clear?: boolean };
    upgrade_decision?: string;
  };
}

const FALLBACK_BUSINESS_SCENARIOS: TwmBusinessScenario[] = [
  {
    id: 'farmland_protection_review',
    label: '耕地保护与占补平衡审查',
    decision_question: '拟建或调整项目是否触碰永久基本农田、生态红线，或造成耕地保护目标风险？',
    operator_goal: '在审查前暴露项目合规风险、证据缺口和可替代空间方案。',
    primary_roles: ['project', 'parcel', 'permanent_basic_farmland', 'eco_redline', 'planning_zone'],
    required_evidence: ['项目范围', '现状地类图斑', '永久基本农田', '生态保护红线', '审批/补正记录'],
    default_action_type: 'protect',
    default_target_role: 'project',
    default_scenario: 'farmland_protection_review',
    default_evidence_coverage: 0.78,
    default_horizon: 3,
    decision_outputs: ['风险命中优先级', '证据审计包', '合法可行备选方案'],
    guardrails: ['硬约束命中不直接给通过建议', '合成数据只能作为演示和回归证据'],
  },
  {
    id: 'construction_project_compliance',
    label: '建设项目用地合规预审',
    decision_question: '项目选址、规模和审批状态是否与用途管制分区、城镇开发边界和已有审查意见一致？',
    operator_goal: '把项目落地前的用地冲突、补正事项和审批一致性风险前置给业务人员。',
    primary_roles: ['project', 'parcel', 'planning_zone', 'urban_boundary', 'review_task'],
    required_evidence: ['建设项目范围', '用途管制分区', '城镇开发边界', '审查意见', '历史审批状态'],
    default_action_type: 'inspect',
    default_target_role: 'project',
    default_scenario: 'construction_project_compliance',
    default_evidence_coverage: 0.72,
    default_horizon: 2,
    decision_outputs: ['审批一致性风险', '补正证据清单', '人工复核任务'],
    guardrails: ['缺少审批记录时只给复核建议', '边界外建设风险必须保留人工审查'],
  },
  {
    id: 'territorial_plan_adjustment',
    label: '国土空间用途调整推演',
    decision_question: '用途调整或空间优化方案会怎样影响保护约束、规划效用和后续监管压力？',
    operator_goal: '在方案比选阶段比较调整收益、约束风险和可解释证据，而不是只输出最优数值。',
    primary_roles: ['scenario', 'parcel', 'planning_zone', 'project', 'control_boundary'],
    required_evidence: ['现状空间格局', '规划分区', '硬约束边界', '候选调整方案', '历史监管样本'],
    default_action_type: 'convert',
    default_target_role: 'scenario',
    default_scenario: 'territorial_plan_adjustment',
    default_evidence_coverage: 0.68,
    default_horizon: 5,
    decision_outputs: ['方案效用/风险排序', '反事实推演摘要', '不可推荐方案原因'],
    guardrails: ['硬约束方案不得进入推荐集', '预测结论必须带证据覆盖和不确定性'],
  },
];

const FALLBACK_RESEARCH_POSITIONING: TwmResearchPositioning = {
  research_question: 'Can a governance-oriented geospatial world model improve territorial planning decisions with hierarchical GIS state, policy constraints, evidence provenance and action-conditioned forecast?',
  core_technology: [
    {
      name: 'Hierarchical GIS object-relation-rule-evidence state',
      claim: '把图斑、项目、管控边界、规划分区、审批证据和规则作为同一个可追溯状态，而不是扁平图层集合。',
    },
    {
      name: 'Action-conditioned multi-head territorial dynamics',
      claim: '围绕 review/protect/convert/restore 等治理动作预测约束风险、规划效用、不确定性和可行动作。',
    },
    {
      name: 'Evidence-gated and causally calibrated claim ladder',
      claim: '证据不足或因果不可识别时降级为 review，不把合成数据结果包装成生产结论。',
    },
  ],
  unmet_need_hypotheses: [
    '空间叠加、政策核查、审批证据和方案比选仍常分散在不同工具链中。',
    '传统土地利用模拟更关注格局转移，业务审查更需要动作后果、规则有效性和审计边界。',
  ],
  falsification_conditions: [
    '如果真实业务访谈显示这些决策已被现有工具很好解决，TWM 应收窄或停止。',
    '如果不能优于 rule-only/manual baseline，创新主张不成立。',
  ],
  claim_boundary: 'Current TWM is a rigorous prototype and review scaffold; production predictive claims require real observed histories and baseline comparisons.',
};

const FALLBACK_DATA_FOUNDATION: TwmDataFoundationAssessment = {
  status: 'review',
  landing_readiness: {
    status: 'review',
    verdict: '当前数据基础足以支撑 TWM 工程原型、规则/证据/审计链路和合成实验验证；不足以支撑生产级审批结论、真实预测效果或真实因果改进声明。',
    production_deployment_supported: false,
    engineering_mvp_supported: true,
    business_review_scaffold_supported: true,
    predictive_or_causal_claim_supported: false,
    key_blockers: ['生产可用观察历史行数为 0', '生产政策动作历史未提供', '关键治理记录为 synthetic/not-for-production'],
  },
  datasets: [
    {
      id: 'twm_bishan_demo',
      label: 'Bishan demo engineering fixture',
      positioning: '工程 MVP 与回归测试主数据包；含真实 Sentinel-2 影像，但关键治理对象为合成或 not-for-production。',
      not_for_production: true,
      files: [
        { path: 'parcel_current.geojson', count: 4900 },
        { path: 'synthetic_projects.geojson', count: 60 },
        { path: 'tables/approval_records.csv', count: 60, synthetic_count: 60, not_for_production_count: 60 },
      ],
    },
    {
      id: 'twm_bishan_multi_admin_eval',
      label: 'Bishan multi-admin evaluation fixture',
      positioning: '多行政单元压力测试与数据基础体检主对象；关键业务历史仍为 synthetic/not-for-production。',
      not_for_production: true,
      files: [
        { path: 'parcel_current.geojson', count: 21218 },
        { path: 'synthetic_projects.geojson', count: 90 },
        { path: 'tables/rule_evaluation.csv', count: 360, synthetic_count: 360, not_for_production_count: 360 },
      ],
    },
    {
      id: 'twm_one_map_village_standard_sample',
      label: 'One Map village standard sample',
      positioning: '验证自然资源一张图村规划样例能否按 TWM 角色契约接入；所有数据均 not-for-production。',
      not_for_production: true,
      files: [
        { path: 'parcel_current.geojson', count: 2217 },
        { path: 'synthetic_planning_zones.geojson', count: 2457 },
        { path: 'tables/approval_records.csv', count: 36 },
      ],
    },
  ],
  validation_snapshot: {
    production_ready_observed_history_rows: 0,
    production_policy_history_status: 'not_provided',
    production_policy_history_row_count: 0,
    structural_fixture: { row_count: 48, pair_count: 24, structural_status: 'pass', default_status: 'review' },
    synthetic_experiment: {
      row_count: 256,
      pair_count: 128,
      region_count: 4,
      period_count: 8,
      action_mask_allowed_count: 64,
      action_mask_blocked_count: 64,
      structural_status: 'pass',
      default_status: 'review',
    },
  },
  supported_problems: [
    { problem: '工程 MVP 与回归测试', support: '验证状态构建、角色绑定、规则评价、证据链、审计报告和 TWM 前端工作流。' },
    { problem: '业务审查脚手架', support: '模拟耕地保护、生态红线、用途管制、审批一致性和复核任务风险暴露。' },
    { problem: '优化/规划消费者链路', support: '测试候选方案载入、硬约束过滤、beam ranking 和 action-mask 安全头。' },
  ],
  unsupported_claims: [
    { claim: '生产级审批结论', reason: '审批、复核、执法和规则命中记录主要为 synthetic/not-for-production。' },
    { claim: '真实治理效果预测或因果改进', reason: '尚无非合成生产观察历史、真实 treated/control 样本和政策动作标签。' },
  ],
  required_next_data: [
    { priority: 'P0', data: '真实或脱敏的项目审批/复核/补正/执法历史', unlocks: '生产观察历史、业务效果评估和真实基线对比。' },
    { priority: 'P0', data: '权威管控边界与规划约束版本', unlocks: '真实硬约束冲突判断和规则条款追溯。' },
  ],
  mentor_answer: {
    short_answer: '目前 TWM 靠谱的部分是工程和研究假设验证，不是生产落地证明。',
  },
};

const FALLBACK_CLAIM_MATRIX: TwmResearchClaimMatrix = {
  status: 'review',
  claim_boundary: 'Every TWM research claim must name the unmet business need, a simpler baseline, minimum real-data evidence, metrics and falsification conditions before it can be upgraded beyond prototype status.',
  current_data_gate: {
    production_ready_observed_history_rows: 0,
    production_policy_history_row_count: 0,
    production_deployment_supported: false,
    predictive_or_causal_claim_supported: false,
  },
  claims: [
    {
      claim_id: 'C1_state_conflict_recall',
      claim: 'Object-relation-rule-evidence state reduces missed hard-constraint conflicts compared with layer-by-layer manual GIS review.',
      baseline: 'manual_gis_overlay_checklist',
      current_status: 'engineering_supported_production_unvalidated',
      current_evidence: 'Synthetic fixtures verify pipeline behavior; real conflict recall is not validated.',
      gate: { status: 'review', claim_level: 'prototype_scaffold', missing: ['production_observed_history', 'named_real_workflow_baseline'] },
      metrics: [{ name: 'hard_constraint_conflict_recall', minimum_pass: 0.95 }],
    },
    {
      claim_id: 'C2_audit_defensibility',
      claim: 'Evidence-gated review improves audit defensibility compared with rule-only spatial compliance engines.',
      baseline: 'rule_only_spatial_compliance_engine',
      current_status: 'scaffold_supported_real_audit_unvalidated',
      gate: { status: 'review', claim_level: 'prototype_scaffold', missing: ['production_observed_history', 'named_real_workflow_baseline'] },
      metrics: [{ name: 'audit_trail_completeness', minimum_pass: 0.9 }],
    },
    {
      claim_id: 'C3_action_conditioned_triage',
      claim: 'Action-conditioned dynamics improves plan-option triage compared with simulators or optimization-only ranking.',
      baseline: 'land_use_simulator_or_optimization_only_ranking',
      current_status: 'experimental_synthetic_only',
      gate: { status: 'review', claim_level: 'prototype_scaffold', missing: ['production_observed_history', 'production_policy_action_labels'] },
      metrics: [{ name: 'legal_feasible_topk_precision', minimum_pass: 0.8 }],
    },
  ],
  next_experiments: [
    { priority: 'P0', experiment: 'Retrospective approval replay', question: '真实历史项目上是否优于 manual/rule-only baseline?' },
    { priority: 'P0', experiment: 'Operator workflow interview and task timing', question: '目标业务是否真有未满足需求?' },
  ],
  mentor_answer: 'TWM 的创新性不能靠列举模型组件来证明，必须绑定真实业务问题、简单基线、数据门槛和可证伪指标。',
};

const DEMO_BUNDLES = [
  {
    key: 'bishan',
    label: 'Bishan demo',
    bundleDir: 'data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion',
    optimizationDir: 'data_agent/test_data/twm_bishan_demo/optimization',
    regionCode: '500227',
  },
  {
    key: 'multi_admin',
    label: 'Bishan multi-admin',
    bundleDir: 'data_agent/test_data/twm_bishan_multi_admin_eval',
    optimizationDir: 'data_agent/test_data/twm_bishan_multi_admin_eval/optimization',
    regionCode: '500227',
  },
  {
    key: 'one_map',
    label: 'One Map village',
    bundleDir: 'data_agent/test_data/twm_one_map_village_standard_sample',
    optimizationDir: 'data_agent/test_data/twm_one_map_village_standard_sample/optimization',
    regionCode: '500227',
  },
];

const severityRank: Record<string, number> = {
  blocking: 5,
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
};

function fmt(value: any, digits = 2) {
  if (value === null || typeof value === 'undefined' || value === '') return '-';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '-';
    return Math.abs(value) >= 1000 ? value.toLocaleString() : value.toFixed(digits);
  }
  return String(value);
}

function statusClass(status?: string) {
  const normalized = String(status || '').toLowerCase();
  if (['pass', 'ready', 'ok', 'success', 'completed', 'legal_feasible', 'built'].includes(normalized)) return 'success';
  if (['blocked', 'error', 'failed', 'failure'].includes(normalized)) return 'error';
  if (['review', 'warning', 'draft', 'open', 'pending'].includes(normalized)) return 'warning';
  return 'proposed';
}

function parseError(data: any, fallback: string) {
  return data?.error || data?.detail || fallback;
}

function firstArray<T = any>(value: any, key: string): T[] {
  return Array.isArray(value?.[key]) ? value[key] : [];
}

function previewText(value: string, limit = 180) {
  return value.replace(/\s+/g, ' ').trim().slice(0, limit);
}

function topHits(hits: TwmHit[]) {
  return [...hits].sort((a, b) => {
    const sev = (severityRank[b.severity || ''] || 0) - (severityRank[a.severity || ''] || 0);
    if (sev !== 0) return sev;
    return Number(b.risk_score || 0) - Number(a.risk_score || 0);
  }).slice(0, 8);
}

function clampRatio(value: any, fallback = 0.72) {
  const num = Number(value);
  if (!Number.isFinite(num)) return fallback;
  return Math.max(0, Math.min(1, num));
}

function compactList(values: any[] | undefined, fallback = 'none') {
  const rows = (values || []).filter(Boolean).map(String);
  return rows.length ? rows.slice(0, 4).join(', ') : fallback;
}

export default function TerritoryWorldModelTab() {
  const [status, setStatus] = useState<TwmStatus | null>(null);
  const [businessScenarios, setBusinessScenarios] = useState<TwmBusinessScenario[]>(FALLBACK_BUSINESS_SCENARIOS);
  const [selectedBusinessScenarioId, setSelectedBusinessScenarioId] = useState(FALLBACK_BUSINESS_SCENARIOS[0].id);
  const [researchPositioning, setResearchPositioning] = useState<TwmResearchPositioning>(FALLBACK_RESEARCH_POSITIONING);
  const [claimMatrix, setClaimMatrix] = useState<TwmResearchClaimMatrix>(FALLBACK_CLAIM_MATRIX);
  const [dataFoundation, setDataFoundation] = useState<TwmDataFoundationAssessment>(FALLBACK_DATA_FOUNDATION);
  const [projects, setProjects] = useState<TwmProject[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [states, setStates] = useState<TwmStateVersion[]>([]);
  const [selectedStateId, setSelectedStateId] = useState('');
  const [hits, setHits] = useState<TwmHit[]>([]);
  const [error, setError] = useState('');
  const [running, setRunning] = useState<RunKey | null>(null);

  const [projectName, setProjectName] = useState('TWM Bishan Workspace');
  const [regionCode, setRegionCode] = useState('500227');
  const [bundleDir, setBundleDir] = useState(DEMO_BUNDLES[0].bundleDir);
  const [optimizationDir, setOptimizationDir] = useState(DEMO_BUNDLES[0].optimizationDir);
  const [stateLabel, setStateLabel] = useState('Bishan MMFE TWM state');
  const [includeAuxiliary, setIncludeAuxiliary] = useState(true);
  const [actionType, setActionType] = useState('protect');
  const [targetRole, setTargetRole] = useState('project');
  const [scenario, setScenario] = useState('twm_frontend_review');
  const [evidenceCoverage, setEvidenceCoverage] = useState(0.72);
  const [horizon, setHorizon] = useState(3);

  const [stateDetail, setStateDetail] = useState<any | null>(null);
  const [ruleResult, setRuleResult] = useState<any | null>(null);
  const [forecastResult, setForecastResult] = useState<any | null>(null);
  const [validationResult, setValidationResult] = useState<any | null>(null);
  const [auditResult, setAuditResult] = useState<any | null>(null);
  const [candidateResult, setCandidateResult] = useState<any | null>(null);
  const [beamResult, setBeamResult] = useState<any | null>(null);
  const [baselineTemplates, setBaselineTemplates] = useState<TwmBaselineExportTemplates | null>(null);
  const [baselineImport, setBaselineImport] = useState<TwmBaselineExportImport | null>(null);
  const [baselinePipeline, setBaselinePipeline] = useState<TwmBaselineEvidencePipelineReport | null>(null);
  const [baselineExportValidation, setBaselineExportValidation] = useState<TwmBaselineExportValidationReport | null>(null);
  const [baselineComparison, setBaselineComparison] = useState<TwmBaselineComparisonReport | null>(null);
  const [baselineCards, setBaselineCards] = useState<TwmScenarioCard[]>([]);
  const [baselineCardFilter, setBaselineCardFilter] = useState('all');
  const [expandedBaselineCardId, setExpandedBaselineCardId] = useState('');
  const [selectedClaimId, setSelectedClaimId] = useState(FALLBACK_CLAIM_MATRIX.claims?.[0]?.claim_id || '');
  const [twmMetricsPath, setTwmMetricsPath] = useState('data_agent/test_data/twm_baseline_metrics/twm_metrics.json');
  const [baselineMetricsPath, setBaselineMetricsPath] = useState('data_agent/test_data/twm_baseline_metrics/manual_overlay_metrics.csv');
  const [twmCaseOutputPath, setTwmCaseOutputPath] = useState('data_agent/test_data/twm_baseline_metrics/twm_case_outputs.csv');
  const [baselineCaseOutputPath, setBaselineCaseOutputPath] = useState('data_agent/test_data/twm_baseline_metrics/manual_overlay_case_outputs.csv');

  const selectedBusinessScenario = (
    businessScenarios.find(item => item.id === selectedBusinessScenarioId) || businessScenarios[0] || FALLBACK_BUSINESS_SCENARIOS[0]
  );
  const selectedProject = projects.find(item => item.id === selectedProjectId) || null;
  const selectedState = states.find(item => item.id === selectedStateId) || null;
  const latestResult = beamResult || validationResult || forecastResult || auditResult || ruleResult || stateDetail;
  const dataReadiness = dataFoundation.landing_readiness || FALLBACK_DATA_FOUNDATION.landing_readiness || {};
  const validationSnapshot = dataFoundation.validation_snapshot || FALLBACK_DATA_FOUNDATION.validation_snapshot || {};
  const claimDataGate = claimMatrix.current_data_gate || FALLBACK_CLAIM_MATRIX.current_data_gate || {};
  const readiness = useMemo(() => {
    const repository = status?.repository || {};
    return [
      { label: 'Projects', value: repository.project_count ?? projects.length },
      { label: 'States', value: repository.state_version_count ?? states.length },
      { label: 'Rules', value: repository.policy_rule_count ?? '-' },
      { label: 'Hits', value: repository.rule_hit_count ?? hits.length },
    ];
  }, [status, projects.length, states.length, hits.length]);

  const withRun = async <T,>(key: RunKey, task: () => Promise<T>): Promise<T | null> => {
    setRunning(key);
    setError('');
    try {
      return await task();
    } catch (e: any) {
      setError(e?.message || '请求失败');
      return null;
    } finally {
      setRunning(null);
    }
  };

  const api = async (url: string, init?: RequestInit) => {
    const headers = {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...(init?.headers || {}),
    };
    const resp = await fetch(url, {
      ...init,
      credentials: 'include',
      headers,
    });
    const text = await resp.text();
    const contentType = (resp.headers.get('content-type') || '').toLowerCase();
    const looksLikeJson = contentType.includes('application/json') || /^[\[{]/.test(text.trim());
    if (!looksLikeJson) {
      const isHtml = /<!doctype html/i.test(text) || /<html[\s>]/i.test(text);
      const detail = isHtml
        ? '当前后端返回了前端 HTML，通常表示 8000 端口运行的是旧后端、静态前端服务，或 TWM API 路由尚未挂载。请重启包含最新代码的 Chainlit/FastAPI 后端后再刷新。'
        : `返回内容不是 JSON: ${previewText(text) || contentType || 'empty response'}`;
      throw new Error(`TWM API 响应格式错误（${url}）。${detail}`);
    }
    let data: any = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch (e: any) {
      throw new Error(`TWM API JSON 解析失败（${url}）: ${e?.message || 'invalid JSON'}`);
    }
    if (!resp.ok || data.error) throw new Error(parseError(data, `请求失败: ${url}`));
    return data;
  };

  const loadStatus = async () => {
    await withRun('status', async () => {
      const data = await api('/api/twm/status');
      setStatus(data);
      return data;
    });
  };

  const loadBusinessScenarios = async () => {
    await withRun('scenarios', async () => {
      const data = await api('/api/twm/business-scenarios');
      const rows = firstArray<TwmBusinessScenario>(data, 'scenarios');
      if (rows.length) {
        setBusinessScenarios(rows);
        if (!rows.some(item => item.id === selectedBusinessScenarioId)) {
          setSelectedBusinessScenarioId(rows[0].id);
        }
      }
      return rows;
    });
  };

  const loadResearchPositioning = async () => {
    await withRun('positioning', async () => {
      const data = await api('/api/twm/research-positioning');
      if (data?.research_question) setResearchPositioning(data);
      return data;
    });
  };

  const loadClaimMatrix = async () => {
    await withRun('claimMatrix', async () => {
      const data = await api('/api/twm/research-claim-matrix');
      if (data?.claims) setClaimMatrix(data);
      return data;
    });
  };

  const loadBaselineTemplates = async () => {
    await withRun('baselineTemplates', async () => {
      const data = await api('/api/twm/baseline-export-templates');
      if (data?.templates) setBaselineTemplates(data);
      return data;
    });
  };

  const loadDataFoundation = async () => {
    await withRun('dataFoundation', async () => {
      const data = await api('/api/twm/data-foundation-assessment');
      if (data?.landing_readiness) setDataFoundation(data);
      return data;
    });
  };

  const loadProjects = async () => {
    await withRun('projects', async () => {
      const data = await api('/api/twm/projects');
      const rows = firstArray<TwmProject>(data, 'projects');
      setProjects(rows);
      if (!selectedProjectId && rows[0]?.id) setSelectedProjectId(rows[0].id);
      return rows;
    });
  };

  const loadBaselineCards = async (projectId = selectedProjectId) => {
    if (!projectId) {
      setBaselineCards([]);
      return [];
    }
    return await withRun('baselineCards', async () => {
      const data = await api(`/api/twm/scenarios?project_id=${encodeURIComponent(projectId)}`);
      const rows = firstArray<TwmScenarioCard>(data, 'scenarios')
        .filter(item => (
          item.scenario_type === 'baseline_comparison'
          || item.scenario_type === 'baseline_export_validation'
          || item.metadata?.kind === 'baseline_comparison_run_card'
          || item.metadata?.kind === 'baseline_export_validation_run_card'
        ));
      setBaselineCards(rows);
      return rows;
    });
  };

  const loadStates = async (projectId = selectedProjectId) => {
    if (!projectId) {
      setStates([]);
      setSelectedStateId('');
      return;
    }
    await withRun('states', async () => {
      const data = await api(`/api/twm/projects/${encodeURIComponent(projectId)}/states`);
      const rows = firstArray<TwmStateVersion>(data, 'states');
      setStates(rows);
      if (!selectedStateId && rows[0]?.id) setSelectedStateId(rows[0].id);
      return rows;
    });
  };

  const loadStateDetail = async (stateId = selectedStateId) => {
    if (!stateId) return null;
    const data = await api(`/api/twm/states/${encodeURIComponent(stateId)}`);
    setStateDetail(data);
    setHits(firstArray<TwmHit>(data, 'hits'));
    return data;
  };

  const refreshAll = async () => {
    await loadStatus();
    await loadBusinessScenarios();
    await loadResearchPositioning();
    await loadClaimMatrix();
    await loadBaselineTemplates();
    await loadDataFoundation();
    await loadProjects();
  };

  useEffect(() => {
    refreshAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selectedProjectId) {
      loadStates(selectedProjectId);
      loadBaselineCards(selectedProjectId);
    } else {
      setBaselineCards([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProjectId]);

  useEffect(() => {
    if (selectedStateId) {
      withRun('states', () => loadStateDetail(selectedStateId));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedStateId]);

  useEffect(() => {
    const claims = claimMatrix.claims || [];
    if (claims.length && !claims.some(item => item.claim_id === selectedClaimId)) {
      setSelectedClaimId(claims[0].claim_id);
    }
  }, [claimMatrix.claims, selectedClaimId]);

  const applyPreset = (key: string) => {
    const preset = DEMO_BUNDLES.find(item => item.key === key);
    if (!preset) return;
    setBundleDir(preset.bundleDir);
    setOptimizationDir(preset.optimizationDir);
    setRegionCode(preset.regionCode);
    setStateLabel(preset.label);
    setProjectName(`TWM ${preset.label}`);
  };

  const applyBusinessScenario = (scenarioId: string) => {
    const item = businessScenarios.find(entry => entry.id === scenarioId) || FALLBACK_BUSINESS_SCENARIOS[0];
    setSelectedBusinessScenarioId(item.id);
    setProjectName(`TWM ${item.label}`);
    setActionType(item.default_action_type || 'inspect');
    setTargetRole(item.default_target_role || 'project');
    setScenario(item.default_scenario || item.id);
    setEvidenceCoverage(clampRatio(item.default_evidence_coverage, 0.72));
    setHorizon(Math.max(1, Math.min(12, Number(item.default_horizon || 3))));
  };

  const applyClaimFixture = (claimId: string) => {
    setSelectedClaimId(claimId);
    setBaselineExportValidation(null);
    setBaselineComparison(null);
    if (claimId === 'C3_action_conditioned_triage') {
      setTwmMetricsPath('');
      setBaselineMetricsPath('');
      setTwmCaseOutputPath('data_agent/test_data/twm_baseline_metrics/twm_candidate_triage_same_case_outputs.csv');
      setBaselineCaseOutputPath('data_agent/test_data/twm_baseline_metrics/optimization_only_candidate_triage_same_case_outputs.csv');
      return;
    }
    setTwmMetricsPath('data_agent/test_data/twm_baseline_metrics/twm_metrics.json');
    setBaselineMetricsPath('data_agent/test_data/twm_baseline_metrics/manual_overlay_metrics.csv');
    setTwmCaseOutputPath('data_agent/test_data/twm_baseline_metrics/twm_case_outputs.csv');
    setBaselineCaseOutputPath('data_agent/test_data/twm_baseline_metrics/manual_overlay_case_outputs.csv');
  };

  const createProject = async () => {
    await withRun('create', async () => {
      const project = await api('/api/twm/projects', {
        method: 'POST',
        body: JSON.stringify({
          name: projectName,
          region_code: regionCode,
          business_scenario: selectedBusinessScenario.id,
          description: selectedBusinessScenario.decision_question || '',
          metadata: {
            decision_question: selectedBusinessScenario.decision_question,
            operator_goal: selectedBusinessScenario.operator_goal,
            required_evidence: selectedBusinessScenario.required_evidence || [],
            decision_outputs: selectedBusinessScenario.decision_outputs || [],
          },
        }),
      });
      await loadProjects();
      setSelectedProjectId(project.id);
      return project;
    });
  };

  const buildState = async () => {
    if (!selectedProjectId) return setError('请先创建或选择项目');
    await withRun('build', async () => {
      const data = await api(`/api/twm/projects/${encodeURIComponent(selectedProjectId)}/build-state`, {
        method: 'POST',
        body: JSON.stringify({
          bundle_dir: bundleDir,
          label: stateLabel,
          include_auxiliary_tables: includeAuxiliary,
        }),
      });
      setStateDetail(data);
      setSelectedStateId(data.state_version?.id || '');
      await loadStates(selectedProjectId);
      await loadStatus();
      return data;
    });
  };

  const evaluateRules = async () => {
    if (!selectedStateId) return setError('请先构建或选择状态');
    await withRun('evaluate', async () => {
      const data = await api(`/api/twm/states/${encodeURIComponent(selectedStateId)}/evaluate-rules`, {
        method: 'POST',
        body: JSON.stringify({ include_default_rules: true }),
      });
      setRuleResult(data);
      setHits(firstArray<TwmHit>(data, 'hits'));
      await loadStatus();
      return data;
    });
  };

  const runForecast = async () => {
    if (!selectedStateId) return setError('请先构建或选择状态');
    await withRun('forecast', async () => {
      const data = await api(`/api/twm/states/${encodeURIComponent(selectedStateId)}/forecast`, {
        method: 'POST',
        body: JSON.stringify({
          action_type: actionType,
          target_role: targetRole,
          scenario,
          magnitude: 1.0,
          evidence_coverage: evidenceCoverage,
          treatment: 'causal_calibrated',
          auto_action_mask: true,
          scenario_context: selectedBusinessScenario.decision_question || selectedBusinessScenario.label,
        }),
      });
      setForecastResult(data);
      return data;
    });
  };

  const runValidation = async () => {
    if (!selectedStateId) return setError('请先构建或选择状态');
    await withRun('validation', async () => {
      const data = await api(`/api/twm/states/${encodeURIComponent(selectedStateId)}/validation-report`, {
        method: 'POST',
        body: JSON.stringify({
          scenario,
          horizon,
          evidence_coverage: evidenceCoverage,
          treatment: 'causal_calibrated',
          action_type: actionType,
          target_role: targetRole,
          scenario_context: selectedBusinessScenario.decision_question || selectedBusinessScenario.label,
        }),
      });
      setValidationResult(data);
      return data;
    });
  };

  const runAudit = async () => {
    if (!selectedStateId) return setError('请先构建或选择状态');
    await withRun('audit', async () => {
      const data = await api(`/api/twm/states/${encodeURIComponent(selectedStateId)}/audit-report`);
      setAuditResult(data);
      return data;
    });
  };

  const loadCandidates = async () => {
    if (!selectedStateId) return setError('请先构建或选择状态');
    await withRun('candidates', async () => {
      const data = await api(`/api/twm/states/${encodeURIComponent(selectedStateId)}/farmland-layout-candidates`, {
        method: 'POST',
        body: JSON.stringify({ optimization_dir: optimizationDir }),
      });
      setCandidateResult(data);
      return data;
    });
  };

  const runBeam = async () => {
    if (!selectedStateId) return setError('请先构建或选择状态');
    await withRun('beam', async () => {
      const data = await api(`/api/twm/states/${encodeURIComponent(selectedStateId)}/farmland-layout-optimization-beam-plan`, {
        method: 'POST',
        body: JSON.stringify({
          optimization_dir: optimizationDir,
          evidence_coverage: evidenceCoverage,
          limit: 5,
          use_optimizer_metric_projection: true,
        }),
      });
      setBeamResult(data);
      return data;
    });
  };

  const busy = running !== null;
  const summary = ruleResult?.summary || {};
  const forecast = forecastResult?.forecast || forecastResult || {};
  const validationSummary = validationResult?.summary || {};
  const claim = validationSummary?.claim_ladder || {};
  const beamSelected = beamResult?.beam_plan?.selected || beamResult?.selected || {};
  const candidateSummary = candidateResult?.summary || beamResult?.optimization_bundle?.summary || {};
  const filteredBaselineCards = baselineCards.filter(card => {
    if (baselineCardFilter === 'all') return true;
    const claimId = card.metadata?.claim?.claim_id || card.input_changes?.claim_id || '';
    return claimId === baselineCardFilter;
  });
  const selectedBaselineTemplate = (baselineTemplates?.templates || []).find(item => item.claim_id === selectedClaimId) || null;

  const runBaselineExportValidation = async () => {
    const claims = claimMatrix.claims || [];
    const selectedClaim = claims.find(item => item.claim_id === selectedClaimId) || claims[0];
    if (!selectedClaim) return setError('没有可校验的研究主张');
    await withRun('baselineExport', async () => {
      const data = await api('/api/twm/baseline-export-validation-report', {
        method: 'POST',
        body: JSON.stringify({
          claim_id: selectedClaim.claim_id,
          baseline_id: selectedClaim.baseline,
          project_id: selectedProjectId || undefined,
          base_state_version_id: selectedStateId || undefined,
          save_run_card: Boolean(selectedProjectId || selectedStateId),
          twm_case_output_path: twmCaseOutputPath.trim() || undefined,
          baseline_case_output_path: baselineCaseOutputPath.trim() || undefined,
        }),
      });
      setBaselineExportValidation(data);
      await loadBaselineCards(selectedProjectId);
      return data;
    });
  };

  const importBaselineExportFile = async (role: 'twm' | 'baseline', file?: File | null) => {
    if (!file) return;
    const claims = claimMatrix.claims || [];
    const selectedClaim = claims.find(item => item.claim_id === selectedClaimId) || claims[0];
    if (!selectedClaim) return setError('没有可导入的研究主张');
    await withRun('baselineImport', async () => {
      const content = await file.text();
      const data = await api('/api/twm/baseline-export-import', {
        method: 'POST',
        body: JSON.stringify({
          filename: file.name,
          source_role: role,
          claim_id: selectedClaim.claim_id,
          baseline_id: selectedClaim.baseline,
          batch_id: `${selectedClaim.claim_id}-${Date.now()}`,
          content,
        }),
      });
      setBaselineImport(data);
      if (data?.path) {
        if (role === 'twm') setTwmCaseOutputPath(data.path);
        else setBaselineCaseOutputPath(data.path);
      }
      return data;
    });
  };

  const runBaselinePipeline = async () => {
    const claims = claimMatrix.claims || [];
    const selectedClaim = claims.find(item => item.claim_id === selectedClaimId) || claims[0];
    if (!selectedClaim) return setError('没有可运行的研究主张');
    await withRun('baselinePipeline', async () => {
      const data = await api('/api/twm/baseline-evidence-pipeline-report', {
        method: 'POST',
        body: JSON.stringify({
          claim_id: selectedClaim.claim_id,
          baseline_id: selectedClaim.baseline,
          project_id: selectedProjectId || undefined,
          base_state_version_id: selectedStateId || undefined,
          save_run_card: Boolean(selectedProjectId || selectedStateId),
          twm_metrics_path: twmMetricsPath.trim() || undefined,
          baseline_metrics_path: baselineMetricsPath.trim() || undefined,
          twm_case_output_path: twmCaseOutputPath.trim() || undefined,
          baseline_case_output_path: baselineCaseOutputPath.trim() || undefined,
        }),
      });
      setBaselinePipeline(data);
      if (data?.export_validation) setBaselineExportValidation(data.export_validation);
      if (data?.baseline_comparison) setBaselineComparison(data.baseline_comparison);
      await loadBaselineCards(selectedProjectId);
      return data;
    });
  };

  const runBaselineComparison = async () => {
    const claims = claimMatrix.claims || [];
    const selectedClaim = claims.find(item => item.claim_id === selectedClaimId) || claims[0];
    if (!selectedClaim) return setError('没有可对比的研究主张');
    const twmMetrics: Record<string, number> = {};
    const baselineMetrics: Record<string, number> = {};
    const useMetricFiles = twmMetricsPath.trim() || baselineMetricsPath.trim();
    if (!useMetricFiles) {
      (selectedClaim.metrics || []).forEach(metric => {
        const threshold = Number(metric.minimum_pass ?? metric.maximum_pass ?? 0.5);
        if (metric.direction === 'lower_is_better') {
          twmMetrics[metric.name] = Math.max(0, threshold * 0.8);
          baselineMetrics[metric.name] = Math.max(0, threshold * 1.8);
        } else {
          twmMetrics[metric.name] = Math.min(1, threshold + 0.02);
          baselineMetrics[metric.name] = Math.max(0, threshold - 0.08);
        }
      });
    }
    await withRun('baselineCompare', async () => {
      const data = await api('/api/twm/baseline-comparison-report', {
        method: 'POST',
        body: JSON.stringify({
          claim_id: selectedClaim.claim_id,
          baseline_id: selectedClaim.baseline,
          project_id: selectedProjectId || undefined,
          base_state_version_id: selectedStateId || undefined,
          save_run_card: Boolean(selectedProjectId || selectedStateId),
          twm_metrics_path: twmMetricsPath.trim() || undefined,
          baseline_metrics_path: baselineMetricsPath.trim() || undefined,
          twm_case_output_path: twmCaseOutputPath.trim() || undefined,
          baseline_case_output_path: baselineCaseOutputPath.trim() || undefined,
          twm_metrics: Object.keys(twmMetrics).length ? twmMetrics : undefined,
          baseline_metrics: Object.keys(baselineMetrics).length ? baselineMetrics : undefined,
        }),
      });
      setBaselineComparison(data);
      await loadBaselineCards(selectedProjectId);
      return data;
    });
  };

  return (
    <div className="twm-tab">
      <div className="twm-toolbar">
        <div className="twm-title">
          <ShieldCheck size={16} />
          <div>
            <strong>Territory World Model</strong>
            <span>围绕国土业务决策组织规则证据、预测验证和方案比选</span>
          </div>
        </div>
        <button type="button" className="twm-icon-button" onClick={refreshAll} disabled={busy} title="刷新 TWM 状态">
          <RefreshCw size={13} />
          刷新
        </button>
        <span className={`status-badge ${statusClass(status?.status)}`}>
          {running === 'status' ? '检测中' : status?.status || 'unknown'}
        </span>
      </div>

      {error && <div className="twm-alert error">{error}</div>}

      <div className="twm-kpi-grid">
        {readiness.map(item => (
          <div className="twm-kpi" key={item.label}>
            <span>{item.label}</span>
            <strong>{fmt(item.value, 0)}</strong>
          </div>
        ))}
      </div>

      <section className="twm-section twm-business-section">
        <div className="twm-section-head">
          <ShieldCheck size={14} />
          <h4>业务任务</h4>
          <span className="status-badge proposed">{running === 'scenarios' ? 'loading' : selectedBusinessScenario.id}</span>
        </div>
        <div className="twm-business-grid">
          <label className="twm-field">
            <span>业务场景</span>
            <select value={selectedBusinessScenario.id} onChange={e => applyBusinessScenario(e.target.value)} disabled={busy}>
              {businessScenarios.map(item => (
                <option value={item.id} key={item.id}>{item.label}</option>
              ))}
            </select>
          </label>
          <div className="twm-business-question">
            <span>决策问题</span>
            <strong>{selectedBusinessScenario.decision_question || '-'}</strong>
          </div>
        </div>
        <div className="twm-business-grid">
          <div className="twm-business-list">
            <span>关键证据</span>
            <div>{(selectedBusinessScenario.required_evidence || []).map(item => <code key={item}>{item}</code>)}</div>
          </div>
          <div className="twm-business-list">
            <span>交付结果</span>
            <div>{(selectedBusinessScenario.decision_outputs || []).map(item => <code key={item}>{item}</code>)}</div>
          </div>
        </div>
      </section>

      <details className="twm-section twm-research-panel" open>
        <summary>
          <span>研究边界</span>
          <code>{running === 'positioning' ? 'loading' : 'prototype claim'}</code>
        </summary>
        <div className="twm-research-question">{researchPositioning.research_question || '-'}</div>
        <div className="twm-research-grid">
          <div>
            <span>核心技术</span>
            {(researchPositioning.core_technology || []).slice(0, 3).map(item => (
              <article key={item.name}>
                <strong>{item.name}</strong>
                <p>{item.claim || item.why_it_matters || '-'}</p>
              </article>
            ))}
          </div>
          <div>
            <span>待验证主张</span>
            {(researchPositioning.innovation_hypotheses || []).slice(0, 3).map(item => (
              <article key={item.hypothesis}>
                <strong>{item.hypothesis}</strong>
                <p>{item.test || '-'}</p>
              </article>
            ))}
            {!(researchPositioning.innovation_hypotheses || []).length && (
              <article>
                <strong>创新性必须经 baseline 验证</strong>
                <p>{researchPositioning.claim_boundary || '-'}</p>
              </article>
            )}
          </div>
          <div>
            <span>未满足需求假设</span>
            <ul>{(researchPositioning.unmet_need_hypotheses || []).slice(0, 4).map(item => <li key={item}>{item}</li>)}</ul>
          </div>
          <div>
            <span>反证条件</span>
            <ul>{(researchPositioning.falsification_conditions || []).slice(0, 4).map(item => <li key={item}>{item}</li>)}</ul>
          </div>
        </div>
      </details>

      <section className="twm-section twm-claim-matrix-panel">
        <div className="twm-section-head">
          <GitBranch size={14} />
          <h4>主张矩阵</h4>
          <span className={`status-badge ${statusClass(claimMatrix.status)}`}>
            {running === 'claimMatrix' ? 'loading' : claimMatrix.status || 'review'}
          </span>
        </div>
        <div className="twm-claim-boundary">{claimMatrix.claim_boundary || '-'}</div>
        <div className="twm-data-kpis">
          <div><span>真实历史</span><strong>{fmt(claimDataGate.production_ready_observed_history_rows, 0)}</strong></div>
          <div><span>动作标签</span><strong>{fmt(claimDataGate.production_policy_history_row_count, 0)}</strong></div>
          <div><span>生产声明</span><strong>{claimDataGate.production_deployment_supported ? 'yes' : 'no'}</strong></div>
          <div><span>预测/因果</span><strong>{claimDataGate.predictive_or_causal_claim_supported ? 'yes' : 'no'}</strong></div>
        </div>
        <div className="twm-claim-grid">
          {(claimMatrix.claims || []).slice(0, 4).map(item => (
            <article className="twm-claim-card" key={item.claim_id}>
              <div>
                <strong>{item.claim_id}</strong>
                <span className={`status-badge ${statusClass(item.gate?.status)}`}>{item.gate?.claim_level || item.gate?.status || 'review'}</span>
              </div>
              <p>{item.claim}</p>
              <div className="twm-claim-tags">
                <code>{item.baseline || '-'}</code>
                {(item.gate?.missing || []).slice(0, 3).map(missing => <code key={`${item.claim_id}-${missing}`}>{missing}</code>)}
              </div>
              <span>{item.metrics?.[0]?.name || item.current_status || '-'}</span>
            </article>
          ))}
        </div>
        <div className="twm-claim-experiments">
          {(claimMatrix.next_experiments || []).slice(0, 3).map(item => (
            <article key={item.experiment}>
              <strong>{item.priority ? `${item.priority} · ${item.experiment}` : item.experiment}</strong>
              <p>{item.question || item.decision || '-'}</p>
            </article>
          ))}
        </div>
        <div className="twm-baseline-inputs">
          <label>
            <span>Research claim</span>
            <select value={selectedClaimId} onChange={e => applyClaimFixture(e.target.value)} disabled={busy}>
              {(claimMatrix.claims || []).map(item => (
                <option key={item.claim_id} value={item.claim_id}>{item.claim_id}</option>
              ))}
            </select>
          </label>
          <label>
            <span>TWM metrics file</span>
            <input value={twmMetricsPath} onChange={e => setTwmMetricsPath(e.target.value)} disabled={busy} />
          </label>
          <label>
            <span>Baseline metrics file</span>
            <input value={baselineMetricsPath} onChange={e => setBaselineMetricsPath(e.target.value)} disabled={busy} />
          </label>
          <label>
            <span>TWM case outputs</span>
            <input value={twmCaseOutputPath} onChange={e => setTwmCaseOutputPath(e.target.value)} disabled={busy} />
          </label>
          <label>
            <span>Baseline case outputs</span>
            <input value={baselineCaseOutputPath} onChange={e => setBaselineCaseOutputPath(e.target.value)} disabled={busy} />
          </label>
        </div>
        <div className="twm-baseline-template-panel">
          <div className="twm-baseline-template-head">
            <div>
              <strong>脱敏导出模板</strong>
              <span>{selectedBaselineTemplate?.label || selectedClaimId || 'no template'}</span>
            </div>
            <span className={`status-badge ${selectedBaselineTemplate ? 'warning' : 'proposed'}`}>
              {running === 'baselineTemplates' ? 'loading' : selectedBaselineTemplate?.same_case_join_key ? `join ${selectedBaselineTemplate.same_case_join_key}` : 'template'}
            </span>
            <button type="button" className="twm-card-detail-toggle" onClick={loadBaselineTemplates} disabled={busy}>
              刷新
            </button>
          </div>
          {selectedBaselineTemplate ? (
            <>
              <div className="twm-baseline-template-question">{selectedBaselineTemplate.business_question || '-'}</div>
              <div className="twm-baseline-template-grid">
                <article>
                  <span>TWM CSV</span>
                  <code>{selectedBaselineTemplate.csv_header?.twm || (selectedBaselineTemplate.headers?.twm || []).join(',')}</code>
                </article>
                <article>
                  <span>Baseline CSV</span>
                  <code>{selectedBaselineTemplate.csv_header?.baseline || (selectedBaselineTemplate.headers?.baseline || []).join(',')}</code>
                </article>
                <article>
                  <span>Required</span>
                  <p>{compactList(selectedBaselineTemplate.required_columns, 'none')}</p>
                </article>
                <article>
                  <span>Real-data gate</span>
                  <p>
                    {fmt(selectedBaselineTemplate.minimum_real_data_gate?.minimum_real_rows ?? selectedBaselineTemplate.production_collection?.minimum_real_rows, 0)} rows · {fmt(selectedBaselineTemplate.minimum_real_data_gate?.minimum_overlap_ratio ?? 0.8, 2)} overlap
                  </p>
                </article>
              </div>
              <div className="twm-baseline-template-metrics">
                {(selectedBaselineTemplate.metric_column_map || []).slice(0, 3).map(item => (
                  <article key={`${selectedBaselineTemplate.claim_id}-${item.metric}`}>
                    <strong>{item.metric}</strong>
                    <p>{compactList(item.columns, 'no columns')}</p>
                  </article>
                ))}
              </div>
              <details className="twm-baseline-template-details">
                <summary>字段与脱敏约束</summary>
                <div>
                  {(selectedBaselineTemplate.field_descriptions || []).slice(0, 5).map(field => (
                    <article key={`${selectedBaselineTemplate.claim_id}-${field.name}`}>
                      <span>{field.required ? 'required' : 'optional'}</span>
                      <strong>{field.name}</strong>
                      <p>{field.metric_use || field.description || '-'}</p>
                    </article>
                  ))}
                </div>
                <p>{(baselineTemplates?.global_sanitization_rules || []).slice(0, 2).join(' · ') || selectedBaselineTemplate.production_collection?.notes || '-'}</p>
              </details>
            </>
          ) : (
            <div className="twm-empty">No export template loaded for this claim</div>
          )}
        </div>
        <div className="twm-baseline-imports">
          <label>
            <span>Import TWM CSV</span>
            <input
              type="file"
              accept=".csv,text/csv"
              disabled={busy}
              onChange={e => {
                importBaselineExportFile('twm', e.target.files?.[0]);
                e.currentTarget.value = '';
              }}
            />
          </label>
          <label>
            <span>Import baseline CSV</span>
            <input
              type="file"
              accept=".csv,text/csv"
              disabled={busy}
              onChange={e => {
                importBaselineExportFile('baseline', e.target.files?.[0]);
                e.currentTarget.value = '';
              }}
            />
          </label>
          {baselineImport && (
            <div className="twm-baseline-import-summary">
              <span className={`status-badge ${statusClass(baselineImport.status)}`}>{baselineImport.source_role || 'import'}</span>
              <strong>{baselineImport.filename || baselineImport.path || '-'}</strong>
              <p>{fmt(baselineImport.row_count, 0)} rows · {(baselineImport.columns || []).slice(0, 4).join(', ') || 'no columns'}</p>
            </div>
          )}
        </div>
        <div className="twm-baseline-actions">
          <button type="button" className="twm-secondary-action" onClick={runBaselineExportValidation} disabled={busy}>
            {running === 'baselineExport' || running === 'baselineImport' ? <Loader2 size={13} className="twm-spin" /> : <FileCheck2 size={13} />}
            导出校验
          </button>
          <button type="button" className="twm-secondary-action" onClick={runBaselinePipeline} disabled={busy}>
            {running === 'baselinePipeline' ? <Loader2 size={13} className="twm-spin" /> : <Route size={13} />}
            证据流水线
          </button>
          <button type="button" className="twm-secondary-action" onClick={runBaselineComparison} disabled={busy}>
            {running === 'baselineCompare' ? <Loader2 size={13} className="twm-spin" /> : <BarChart3 size={13} />}
            基线对比
          </button>
        </div>
        {baselinePipeline && (
          <div className="twm-baseline-report twm-baseline-pipeline-report">
            <div>
              <span className={`status-badge ${statusClass(baselinePipeline.status)}`}>{baselinePipeline.status || 'review'}</span>
              <strong>{baselinePipeline.pipeline_decision || '-'}</strong>
              <p>{baselinePipeline.claim_id || '-'} vs {baselinePipeline.baseline_id || '-'}</p>
            </div>
            <div className="twm-baseline-export-gates">
              <article>
                <span>Export validation</span>
                <p>{baselinePipeline.steps?.export_validation?.status || '-'}</p>
              </article>
              <article>
                <span>Comparison</span>
                <p>{baselinePipeline.steps?.baseline_comparison?.status || baselinePipeline.steps?.baseline_comparison?.skipped_reason || '-'}</p>
              </article>
              <article>
                <span>Run cards</span>
                <p>
                  {[
                    baselinePipeline.steps?.export_validation?.scenario_card?.scenario_id ? 'validation' : '',
                    baselinePipeline.steps?.baseline_comparison?.scenario_card?.scenario_id ? 'comparison' : '',
                  ].filter(Boolean).join(', ') || 'none'}
                </p>
              </article>
            </div>
            <p>{(baselinePipeline.next_actions || []).slice(0, 2).join(' · ') || baselinePipeline.claim_boundary || '-'}</p>
          </div>
        )}
        {baselineExportValidation && (
          <div className="twm-baseline-report twm-baseline-export-report">
            <div>
              <span className={`status-badge ${statusClass(baselineExportValidation.status)}`}>{baselineExportValidation.status || 'review'}</span>
              <strong>{baselineExportValidation.export_spec?.label || baselineExportValidation.export_spec?.export_type || 'baseline export'}</strong>
              <p>{baselineExportValidation.claim?.claim_id || '-'} · join by {baselineExportValidation.column_inventory?.join_key || '-'}</p>
            </div>
            <div className="twm-baseline-sources">
              <article>
                <span>Overlap</span>
                <strong>{fmt(baselineExportValidation.coverage?.overlap_count, 0)}</strong>
                <p>{fmt(baselineExportValidation.coverage?.coverage_ratio, 3)} coverage</p>
              </article>
              <article>
                <span>TWM rows</span>
                <strong>{fmt(baselineExportValidation.column_inventory?.twm?.row_count, 0)}</strong>
                <p>{fmt(baselineExportValidation.column_inventory?.twm?.unique_join_id_count, 0)} unique</p>
              </article>
              <article>
                <span>Baseline rows</span>
                <strong>{fmt(baselineExportValidation.column_inventory?.baseline?.row_count, 0)}</strong>
                <p>{fmt(baselineExportValidation.column_inventory?.baseline?.unique_join_id_count, 0)} unique</p>
              </article>
              <article>
                <span>Parser metrics</span>
                <strong>{fmt(baselineExportValidation.parser_compatibility?.comparable_metrics?.length, 0)}</strong>
                <p>{(baselineExportValidation.parser_compatibility?.comparable_metrics || []).slice(0, 2).join(', ') || 'none'}</p>
              </article>
            </div>
            <div className="twm-baseline-export-gates">
              <article>
                <span>Blocking</span>
                <p>{(baselineExportValidation.blocking_errors || []).slice(0, 4).join(', ') || 'none'}</p>
              </article>
              <article>
                <span>Missing columns</span>
                <p>
                  {[...(baselineExportValidation.column_inventory?.missing_required?.twm || []), ...(baselineExportValidation.column_inventory?.missing_required?.baseline || [])]
                    .slice(0, 6)
                    .join(', ') || 'none'}
                </p>
              </article>
              <article>
                <span>Warnings</span>
                <p>{(baselineExportValidation.warnings || []).slice(0, 4).join(', ') || 'none'}</p>
              </article>
            </div>
            <p>{(baselineExportValidation.next_actions || []).slice(0, 2).join(' · ') || baselineExportValidation.claim_boundary || '-'}</p>
          </div>
        )}
        {baselineComparison && (
          <div className="twm-baseline-report">
            <div>
              <span className={`status-badge ${statusClass(baselineComparison.status)}`}>{baselineComparison.status || 'review'}</span>
              <strong>{baselineComparison.upgrade_decision || '-'}</strong>
              <p>{baselineComparison.claim?.claim_id || '-'} vs {baselineComparison.baseline?.baseline_id || '-'}</p>
            </div>
            <div className="twm-baseline-metrics">
              {(baselineComparison.metric_comparisons || []).slice(0, 4).map(metric => (
                <article key={metric.name}>
                  <span className={`status-badge ${statusClass(metric.status)}`}>{metric.status || '-'}</span>
                  <strong>{metric.name}</strong>
                  <p>TWM {fmt(metric.twm_value, 3)} · Baseline {fmt(metric.baseline_value, 3)} · Δ {fmt(metric.delta, 3)}</p>
                </article>
              ))}
            </div>
            <div className="twm-baseline-sources">
              <article>
                <span>TWM metrics</span>
                <strong>{baselineComparison.inputs?.twm_metrics_source || 'none'}</strong>
                <p>{fmt(baselineComparison.inputs?.twm_metric_count, 0)} metrics</p>
              </article>
              <article>
                <span>Baseline metrics</span>
                <strong>{baselineComparison.inputs?.baseline_metrics_source || 'none'}</strong>
                <p>{fmt(baselineComparison.inputs?.baseline_metric_count, 0)} metrics</p>
              </article>
              <article>
                <span>TWM cases</span>
                <strong>{baselineComparison.inputs?.twm_case_source || 'none'}</strong>
                <p>{fmt(baselineComparison.inputs?.twm_case_count, 0)} rows</p>
              </article>
              <article>
                <span>Baseline cases</span>
                <strong>{baselineComparison.inputs?.baseline_case_source || 'none'}</strong>
                <p>{fmt(baselineComparison.inputs?.baseline_case_count, 0)} rows</p>
              </article>
            </div>
            {Object.entries(baselineComparison.inputs?.metric_source_errors || {}).some(([, value]) => Boolean(value)) && (
              <p>
                Parser errors: {Object.entries(baselineComparison.inputs?.metric_source_errors || {})
                  .filter(([, value]) => Boolean(value))
                  .map(([key, value]) => `${key}=${value}`)
                  .join(', ')}
              </p>
            )}
            {baselineComparison.scenario_card?.scenario_id && (
              <p>Run card: {baselineComparison.scenario_card.scenario_id} · {baselineComparison.scenario_card.status || 'review'}</p>
            )}
            <p>{(baselineComparison.evidence_gate?.missing || []).slice(0, 4).join(', ') || 'no missing gates'}</p>
          </div>
        )}
        <div className="twm-baseline-cards">
          <div className="twm-baseline-cards-head">
            <div>
              <strong>Saved run cards</strong>
              <span>{running === 'baselineCards' ? 'loading' : `${filteredBaselineCards.length}/${baselineCards.length}`}</span>
            </div>
            <select value={baselineCardFilter} onChange={e => setBaselineCardFilter(e.target.value)} disabled={busy || !baselineCards.length}>
              <option value="all">All claims</option>
              {(claimMatrix.claims || []).map(item => (
                <option key={`card-filter-${item.claim_id}`} value={item.claim_id}>{item.claim_id}</option>
              ))}
            </select>
          </div>
          <div className="twm-baseline-card-list">
            {filteredBaselineCards.slice(0, 4).map(card => {
              const meta = card.metadata || {};
              const sources = meta.baseline_sources || {};
              const validationSources = meta.sources || {};
              const errors = Object.entries(sources.metric_source_errors || {}).filter(([, value]) => Boolean(value));
              const isExportValidation = card.scenario_type === 'baseline_export_validation' || meta.kind === 'baseline_export_validation_run_card';
              const claimId = meta.claim?.claim_id || card.input_changes?.claim_id || '-';
              const baselineId = meta.baseline?.baseline_id || card.input_changes?.baseline_id || '-';
              const expanded = expandedBaselineCardId === card.id;
              return (
                <article key={card.id}>
                  <div>
                    <span className={`status-badge ${statusClass(card.status || meta.upgrade_decision)}`}>{card.status || meta.upgrade_decision || 'review'}</span>
                    <strong>{claimId}</strong>
                    <button
                      type="button"
                      className="twm-card-detail-toggle"
                      onClick={() => setExpandedBaselineCardId(expanded ? '' : card.id)}
                    >
                      {expanded ? 'Hide' : 'Details'}
                    </button>
                  </div>
                  <p>{baselineId}</p>
                  <div className="twm-baseline-card-kpis">
                    <span>TWM {fmt(sources.twm_case_count ?? validationSources.twm?.row_count, 0)}</span>
                    <span>Baseline {fmt(sources.baseline_case_count ?? validationSources.baseline?.row_count, 0)}</span>
                    <span>{isExportValidation ? `overlap ${fmt(meta.coverage?.overlap_count, 0)}` : errors.length ? `${errors.length} parser errors` : 'parser ok'}</span>
                  </div>
                  <p>{isExportValidation ? `join ${meta.column_inventory?.join_key || '-'} · ${fmt(meta.coverage?.coverage_ratio, 3)}` : (meta.evidence_gate?.missing || []).slice(0, 3).join(', ') || 'no missing gates'}</p>
                  {expanded && (
                    <div className="twm-baseline-card-detail">
                      {isExportValidation ? (
                        <>
                          <div>
                            <span>Coverage</span>
                            <strong>{fmt(meta.coverage?.overlap_count, 0)} · {fmt(meta.coverage?.coverage_ratio, 3)}</strong>
                          </div>
                          <div>
                            <span>Missing</span>
                            <p>{compactList([...(meta.column_inventory?.missing_required?.twm || []), ...(meta.column_inventory?.missing_required?.baseline || []), ...(meta.column_inventory?.missing_required?.claim_parser || [])])}</p>
                          </div>
                          <div>
                            <span>Comparable metrics</span>
                            <p>{compactList(meta.parser_compatibility?.comparable_metrics)}</p>
                          </div>
                          <div>
                            <span>Blocking / warnings</span>
                            <p>{compactList([...(meta.blocking_errors || []), ...(meta.warnings || [])])}</p>
                          </div>
                        </>
                      ) : (
                        <>
                          {(meta.metric_comparisons || []).slice(0, 3).map(metric => (
                            <div key={`${card.id}-${metric.name}`}>
                              <span>{metric.name}</span>
                              <strong>{metric.status || '-'}</strong>
                              <p>TWM {fmt(metric.twm_value, 3)} · Baseline {fmt(metric.baseline_value, 3)} · Δ {fmt(metric.delta, 3)}</p>
                            </div>
                          ))}
                          <div>
                            <span>Evidence gate</span>
                            <p>{compactList(meta.evidence_gate?.missing, 'no missing gates')}</p>
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
            {!filteredBaselineCards.length && (
              <div className="twm-empty">{selectedProjectId ? 'No saved baseline run cards' : 'Select a project to load saved run cards'}</div>
            )}
          </div>
        </div>
      </section>

      <section className="twm-section twm-data-foundation-panel">
        <div className="twm-section-head">
          <FileCheck2 size={14} />
          <h4>数据基础</h4>
          <span className={`status-badge ${statusClass(dataReadiness.status || dataFoundation.status)}`}>
            {running === 'dataFoundation' ? 'loading' : dataReadiness.status || dataFoundation.status || 'review'}
          </span>
        </div>
        <div className="twm-data-verdict">{dataReadiness.verdict || '-'}</div>
        <div className="twm-data-kpis">
          <div><span>生产观察历史</span><strong>{fmt(validationSnapshot.production_ready_observed_history_rows, 0)}</strong></div>
          <div><span>政策动作历史</span><strong>{fmt(validationSnapshot.production_policy_history_row_count, 0)}</strong></div>
          <div><span>结构 fixture</span><strong>{fmt(validationSnapshot.structural_fixture?.row_count, 0)}</strong></div>
          <div><span>合成实验</span><strong>{fmt(validationSnapshot.synthetic_experiment?.row_count, 0)}</strong></div>
        </div>
        <div className="twm-data-layout">
          <div className="twm-data-card">
            <span>测试数据包</span>
            {(dataFoundation.datasets || []).slice(0, 3).map(dataset => (
              <article key={dataset.id}>
                <strong>{dataset.label}</strong>
                <p>{dataset.positioning || dataset.nature || '-'}</p>
                <div>
                  <code>{dataset.not_for_production ? 'not-for-production' : 'production candidate'}</code>
                  {(dataset.files || []).slice(0, 4).map(file => (
                    <code key={`${dataset.id}-${file.path}`}>{file.path}: {fmt(file.count, 0)}</code>
                  ))}
                </div>
              </article>
            ))}
          </div>
          <div className="twm-data-card">
            <span>能支撑的问题</span>
            {(dataFoundation.supported_problems || []).slice(0, 4).map(item => (
              <article key={item.problem}>
                <strong>{item.problem}</strong>
                <p>{item.support || '-'}</p>
              </article>
            ))}
          </div>
          <div className="twm-data-card">
            <span>不能支撑的落地声明</span>
            {(dataFoundation.unsupported_claims || []).slice(0, 4).map(item => (
              <article key={item.claim}>
                <strong>{item.claim}</strong>
                <p>{item.reason || '-'}</p>
              </article>
            ))}
          </div>
          <div className="twm-data-card">
            <span>下一步真实数据</span>
            {(dataFoundation.required_next_data || []).slice(0, 4).map(item => (
              <article key={item.data}>
                <strong>{item.priority ? `${item.priority} · ${item.data}` : item.data}</strong>
                <p>{item.unlocks || item.minimum || '-'}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <div className="twm-main-grid">
        <section className="twm-section">
          <div className="twm-section-head">
            <Layers3 size={14} />
            <h4>Workspace</h4>
          </div>

          <div className="twm-preset-row">
            {DEMO_BUNDLES.map(item => (
              <button
                key={item.key}
                type="button"
                onClick={() => applyPreset(item.key)}
                disabled={busy}
                className={bundleDir === item.bundleDir ? 'active' : ''}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="twm-form-grid">
            <label>
              <span>项目名</span>
              <input value={projectName} onChange={e => setProjectName(e.target.value)} disabled={busy} />
            </label>
            <label>
              <span>行政区代码</span>
              <input value={regionCode} onChange={e => setRegionCode(e.target.value)} disabled={busy} />
            </label>
          </div>

          <button type="button" className="twm-primary-action" onClick={createProject} disabled={busy || !projectName.trim()}>
            {running === 'create' ? <Loader2 size={13} className="twm-spin" /> : <FileCheck2 size={13} />}
            创建项目
          </button>

          <label className="twm-field">
            <span>选择项目</span>
            <select value={selectedProjectId} onChange={e => setSelectedProjectId(e.target.value)} disabled={busy || !projects.length}>
              <option value="">未选择</option>
              {projects.map(project => (
                <option value={project.id} key={project.id}>{project.name || project.id}</option>
              ))}
            </select>
          </label>

          {selectedProject && (
            <div className="twm-compact-meta">
              <span>{selectedProject.region_code || '-'}</span>
              <span>{selectedProject.business_scenario || '-'}</span>
              <span>{selectedProject.status || '-'}</span>
            </div>
          )}

          <label className="twm-field">
            <span>MMFE / TWM bundle</span>
            <input value={bundleDir} onChange={e => setBundleDir(e.target.value)} disabled={busy} />
          </label>
          <label className="twm-field">
            <span>状态标签</span>
            <input value={stateLabel} onChange={e => setStateLabel(e.target.value)} disabled={busy} />
          </label>
          <label className="twm-check">
            <input type="checkbox" checked={includeAuxiliary} onChange={e => setIncludeAuxiliary(e.target.checked)} disabled={busy} />
            包含辅助表
          </label>

          <button type="button" className="twm-primary-action" onClick={buildState} disabled={busy || !selectedProjectId || !bundleDir.trim()}>
            {running === 'build' ? <Loader2 size={13} className="twm-spin" /> : <Play size={13} />}
            构建状态
          </button>

          <label className="twm-field">
            <span>选择状态</span>
            <select value={selectedStateId} onChange={e => setSelectedStateId(e.target.value)} disabled={busy || !states.length}>
              <option value="">未选择</option>
              {states.map(state => (
                <option value={state.id} key={state.id}>
                  {state.label || state.id} · {fmt(state.object_count, 0)} objects
                </option>
              ))}
            </select>
          </label>
        </section>

        <section className="twm-section">
          <div className="twm-section-head">
            <SlidersHorizontal size={14} />
            <h4>业务推演</h4>
          </div>

          <div className="twm-state-summary">
            <div>
              <span>State</span>
              <strong>{selectedState?.label || selectedStateId || '-'}</strong>
            </div>
            <div>
              <span>Objects</span>
              <strong>{fmt(selectedState?.object_count ?? stateDetail?.state_version?.object_count, 0)}</strong>
            </div>
            <div>
              <span>Relations</span>
              <strong>{fmt(selectedState?.relation_count ?? stateDetail?.state_version?.relation_count, 0)}</strong>
            </div>
          </div>

          <button type="button" className="twm-secondary-action" onClick={evaluateRules} disabled={busy || !selectedStateId}>
            {running === 'evaluate' ? <Loader2 size={13} className="twm-spin" /> : <ShieldCheck size={13} />}
            检查业务规则
          </button>

          <div className="twm-result-strip">
            <div><span>Hits</span><strong>{fmt(summary.hit_count ?? hits.length, 0)}</strong></div>
            <div><span>Evidence</span><strong>{fmt(summary.evidence_item_count ?? auditResult?.evidence_gate_summary?.evidence_item_count, 0)}</strong></div>
            <div><span>数据风险</span><strong>{fmt(summary.data_quality_hit_count, 0)}</strong></div>
            <div><span>审批风险</span><strong>{fmt(summary.approval_consistency_hit_count, 0)}</strong></div>
          </div>

          <div className="twm-form-grid">
            <label>
              <span>动作</span>
              <select value={actionType} onChange={e => setActionType(e.target.value)} disabled={busy}>
                <option value="inspect">inspect</option>
                <option value="protect">protect</option>
                <option value="allocate">allocate</option>
                <option value="convert">convert</option>
                <option value="restore">restore</option>
              </select>
            </label>
            <label>
              <span>目标角色</span>
              <select value={targetRole} onChange={e => setTargetRole(e.target.value)} disabled={busy}>
                <option value="project">project</option>
                <option value="parcel">parcel</option>
                <option value="scenario">scenario</option>
              </select>
            </label>
            <label>
              <span>证据覆盖</span>
              <input
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={evidenceCoverage}
                onChange={e => setEvidenceCoverage(Math.max(0, Math.min(1, Number(e.target.value) || 0)))}
                disabled={busy}
              />
            </label>
            <label>
              <span>验证期数</span>
              <input
                type="number"
                min={1}
                max={12}
                value={horizon}
                onChange={e => setHorizon(Math.max(1, Math.min(12, Number(e.target.value) || 1)))}
                disabled={busy}
              />
            </label>
          </div>

          <label className="twm-field">
            <span>情景</span>
            <input value={scenario} onChange={e => setScenario(e.target.value)} disabled={busy} />
          </label>

          <div className="twm-action-grid">
            <button type="button" className="twm-secondary-action" onClick={runForecast} disabled={busy || !selectedStateId}>
              {running === 'forecast' ? <Loader2 size={13} className="twm-spin" /> : <GitBranch size={13} />}
              风险预测
            </button>
            <button type="button" className="twm-secondary-action" onClick={runValidation} disabled={busy || !selectedStateId}>
              {running === 'validation' ? <Loader2 size={13} className="twm-spin" /> : <CheckCircle2 size={13} />}
              验证口径
            </button>
            <button type="button" className="twm-secondary-action" onClick={runAudit} disabled={busy || !selectedStateId}>
              {running === 'audit' ? <Loader2 size={13} className="twm-spin" /> : <FileCheck2 size={13} />}
              证据审计
            </button>
          </div>

          <label className="twm-field">
            <span>优化 bundle</span>
            <input value={optimizationDir} onChange={e => setOptimizationDir(e.target.value)} disabled={busy} />
          </label>
          <div className="twm-action-grid">
            <button type="button" className="twm-secondary-action" onClick={loadCandidates} disabled={busy || !selectedStateId || !optimizationDir.trim()}>
              {running === 'candidates' ? <Loader2 size={13} className="twm-spin" /> : <BarChart3 size={13} />}
              载入候选
            </button>
            <button type="button" className="twm-primary-action" onClick={runBeam} disabled={busy || !selectedStateId || !optimizationDir.trim()}>
              {running === 'beam' ? <Loader2 size={13} className="twm-spin" /> : <Route size={13} />}
              Beam 比选
            </button>
          </div>
        </section>
      </div>

      <div className="twm-main-grid twm-results-grid">
        <section className="twm-section">
          <div className="twm-section-head">
            <AlertTriangle size={14} />
            <h4>Rule Hits</h4>
            <span className={`status-badge ${hits.length ? 'warning' : 'success'}`}>{hits.length ? `${hits.length} open` : 'none'}</span>
          </div>
          <div className="twm-hit-list">
            {topHits(hits).map(hit => (
              <div className="twm-hit-row" key={hit.id}>
                <span className={`status-badge ${statusClass(hit.severity)}`}>{hit.severity || '-'}</span>
                <div>
                  <strong>{hit.rule_id || hit.id}</strong>
                  <span>{hit.explanation || hit.subject_object_id || '-'}</span>
                </div>
                <code>{fmt(hit.risk_score, 3)}</code>
              </div>
            ))}
            {!hits.length && <div className="twm-empty">No rule hits loaded</div>}
          </div>
        </section>

        <section className="twm-section">
          <div className="twm-section-head">
            <CheckCircle2 size={14} />
            <h4>Claim & Planning</h4>
            <span className={`status-badge ${statusClass(validationResult?.overall_status || beamResult?.status)}`}>
              {validationResult?.overall_status || beamResult?.status || 'not run'}
            </span>
          </div>

          <div className="twm-result-strip">
            <div><span>Claim</span><strong>{claim.current_level || '-'}</strong></div>
            <div><span>Utility</span><strong>{fmt(forecast.planning_utility_delta ?? beamSelected.utility, 3)}</strong></div>
            <div><span>Risk</span><strong>{fmt(forecast.constraint_violation_probability ?? beamSelected.risk, 3)}</strong></div>
            <div><span>Confidence</span><strong>{fmt(forecast.uncertainty?.confidence ?? beamSelected.confidence, 3)}</strong></div>
          </div>

          {validationResult?.stages && (
            <div className="twm-stage-list">
              {validationResult.stages.map((stage: any) => (
                <div className="twm-stage-row" key={stage.stage_code}>
                  <span className={`status-badge ${statusClass(stage.status)}`}>{stage.status}</span>
                  <strong>{stage.stage_code}</strong>
                  <span>{stage.gaps?.[0] || stage.summary || '-'}</span>
                </div>
              ))}
            </div>
          )}

          <div className="twm-result-strip">
            <div><span>Candidates</span><strong>{fmt(candidateSummary.candidate_count, 0)}</strong></div>
            <div><span>Legal</span><strong>{fmt(candidateSummary.legal_feasible_count, 0)}</strong></div>
            <div><span>Blocked</span><strong>{fmt(candidateSummary.blocked_count, 0)}</strong></div>
            <div><span>Selected</span><strong>{beamSelected.candidate_id || '-'}</strong></div>
          </div>
        </section>
      </div>

      <details className="twm-json-panel">
        <summary>Latest payload</summary>
        <pre>{JSON.stringify(latestResult || status || {}, null, 2)}</pre>
      </details>
    </div>
  );
}
