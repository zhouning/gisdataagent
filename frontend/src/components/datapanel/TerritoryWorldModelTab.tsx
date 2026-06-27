import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Eye,
  EyeOff,
  FileCheck2,
  GitBranch,
  Layers3,
  Loader2,
  MapPin,
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

type TwmMapStage = 'locate' | 'risk' | 'plan';
type TwmSubTab = 'overview' | 'data' | 'operate' | 'payload';

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
  generated_at?: string;
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
    file_count?: number;
    total_count?: number;
    synthetic_count?: number;
    not_for_production_count?: number;
    spatial_layer_catalog?: TwmDataFoundationMapPreviewLayer[];
    map_overlay_readiness?: TwmDataFoundationMapPreview['map_overlay_readiness'];
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
    production_policy_allowed_count?: number;
    production_policy_blocked_count?: number;
    structural_fixture?: { row_count?: number; pair_count?: number; structural_status?: string; default_status?: string };
    synthetic_experiment?: {
      row_count?: number;
      pair_count?: number;
      region_count?: number;
      period_count?: number;
      split_counts?: Record<string, number>;
      action_mask_allowed_count?: number;
      action_mask_blocked_count?: number;
      structural_status?: string;
      default_status?: string;
    };
    local_observed_history?: { status?: string; missing?: string[]; relation_neighbor_edge_count?: number };
    project_review_context?: { project_count?: number; rule_eval_count?: number; review_task_count?: number };
    external_support?: { paper7_caliper_matched_status?: string; paper7_caliper_matched_pair_count?: number; boundary?: string };
  };
  supported_problems?: Array<{ problem: string; support?: string }>;
  unsupported_claims?: Array<{ claim: string; reason?: string }>;
  problem_data_fit?: Array<{
    business_problem: string;
    current_fit?: string;
    why?: string;
    safe_output?: string;
    unsafe_output?: string;
  }>;
  required_next_data?: Array<{ priority?: string; data: string; minimum?: string; unlocks?: string }>;
  mentor_answer?: { short_answer?: string; research_judgment?: string };
  source_reports?: Record<string, string>;
}

interface TwmDataFoundationCrsDiagnostic {
  status?: string;
  coordinate_space?: string;
  map_overlay_ready?: boolean;
  warning_code?: string | null;
  suggested_action?: string;
  message?: string;
}

interface TwmDataFoundationPropertyField {
  name: string;
  value_type?: string;
  observed_count?: number;
}

interface TwmDataFoundationMapPreviewLayer {
  name?: string;
  path?: string;
  label?: string;
  delivery_mode?: string;
  source_feature_count?: number;
  feature_count?: number;
  preview_feature_count?: number;
  property_field_count?: number;
  property_fields?: TwmDataFoundationPropertyField[];
  sample_properties?: Record<string, any>;
  bbox?: number[] | null;
  crs_diagnostic?: TwmDataFoundationCrsDiagnostic;
  geojson?: any;
}

interface TwmDataFoundationMapPreview {
  dataset_id?: string;
  delivery_mode?: string;
  total_source_feature_count?: number;
  total_preview_feature_count?: number;
  bbox?: number[] | null;
  center?: number[] | null;
  map_overlay_readiness?: {
    status?: string;
    ready_layer_count?: number;
    blocked_layer_count?: number;
    warning_codes?: string[];
    suggested_action?: string;
    message?: string;
  };
  layers?: TwmDataFoundationMapPreviewLayer[];
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
  research_question: '面向治理的国土空间世界模型，能否把分层 GIS 状态、政策约束、证据来源和行动条件预测放进同一条可审计决策链路，从而改进国土空间规划审查？',
  core_technology: [
    {
      name: '分层 GIS 对象-关系-规则-证据状态',
      claim: '把图斑、项目、管控边界、规划分区、审批证据和规则作为同一个可追溯状态，而不是扁平图层集合。',
    },
    {
      name: '行动条件国土空间动态预测',
      claim: '围绕复核、保护、转换、恢复等治理动作预测约束风险、规划效用、不确定性和可行动作。',
    },
    {
      name: '证据门控与因果校准主张阶梯',
      claim: '证据不足或因果不可识别时降级为人工复核，不把合成数据结果包装成生产结论。',
    },
  ],
  unmet_need_hypotheses: [
    '空间叠加、政策核查、审批证据和方案比选仍常分散在不同工具链中。',
    '传统土地利用模拟更关注格局转移，业务审查更需要动作后果、规则有效性和审计边界。',
  ],
  falsification_conditions: [
    '如果真实业务访谈显示这些决策已被现有工具很好解决，TWM 应收窄或停止。',
    '如果不能优于单纯规则或人工基线，创新主张不成立。',
  ],
  claim_boundary: '当前 TWM 是严谨的原型和复核脚手架；生产级预测主张必须依赖真实观察历史、明确基线对比和外部验证。',
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
    key_blockers: ['生产可用观察历史行数为 0', '生产政策动作历史未提供', '关键治理记录为合成或非生产数据'],
  },
  datasets: [
    {
      id: 'twm_bishan_demo',
      label: '璧山演示工程样例',
      positioning: '工程原型与回归测试主数据包；含真实 Sentinel-2 影像，但关键治理对象为合成或非生产数据。',
      not_for_production: true,
      file_count: 11,
      total_count: 5642,
      synthetic_count: 733,
      not_for_production_count: 5638,
      files: [
        { path: 'parcel_current.geojson', unit: 'feature', count: 4900, synthetic_count: 0, not_for_production_count: 4900 },
        { path: 'synthetic_projects.geojson', unit: 'feature', count: 60, synthetic_count: 60, not_for_production_count: 60 },
        { path: 'synthetic_pbf.geojson', unit: 'feature', count: 14, synthetic_count: 14, not_for_production_count: 14 },
        { path: 'synthetic_eco_redline.geojson', unit: 'feature', count: 10, synthetic_count: 10, not_for_production_count: 10 },
        { path: 'synthetic_planning_zones.geojson', unit: 'feature', count: 5, synthetic_count: 5, not_for_production_count: 5 },
        { path: 'synthetic_annual_change.geojson', unit: 'feature', count: 78, synthetic_count: 78, not_for_production_count: 78 },
        { path: 'tables/approval_records.csv', unit: 'row', count: 60, synthetic_count: 60, not_for_production_count: 60 },
        { path: 'tables/review_tasks.csv', unit: 'row', count: 92, synthetic_count: 92, not_for_production_count: 92 },
        { path: 'tables/rule_evaluation.csv', unit: 'row', count: 240, synthetic_count: 240, not_for_production_count: 240 },
        { path: 'tables/state_snapshots.csv', unit: 'row', count: 10, synthetic_count: 5, not_for_production_count: 10 },
        { path: 'tables/multimodal_evidence_index.csv', unit: 'row', count: 173, synthetic_count: 169, not_for_production_count: 169 },
      ],
    },
    {
      id: 'twm_bishan_multi_admin_eval',
      label: '璧山多行政单元评估样例',
      positioning: '多行政单元压力测试与数据基础体检主对象；关键业务历史仍为合成或非生产数据。',
      not_for_production: true,
      file_count: 11,
      total_count: 22401,
      synthetic_count: 1174,
      not_for_production_count: 22397,
      files: [
        { path: 'parcel_current.geojson', unit: 'feature', count: 21218, synthetic_count: 0, not_for_production_count: 21218 },
        { path: 'synthetic_projects.geojson', unit: 'feature', count: 90, synthetic_count: 90, not_for_production_count: 90 },
        { path: 'synthetic_pbf.geojson', unit: 'feature', count: 14, synthetic_count: 14, not_for_production_count: 14 },
        { path: 'synthetic_eco_redline.geojson', unit: 'feature', count: 10, synthetic_count: 10, not_for_production_count: 10 },
        { path: 'synthetic_planning_zones.geojson', unit: 'feature', count: 5, synthetic_count: 5, not_for_production_count: 5 },
        { path: 'synthetic_annual_change.geojson', unit: 'feature', count: 266, synthetic_count: 266, not_for_production_count: 266 },
        { path: 'tables/approval_records.csv', unit: 'row', count: 90, synthetic_count: 90, not_for_production_count: 90 },
        { path: 'tables/review_tasks.csv', unit: 'row', count: 114, synthetic_count: 114, not_for_production_count: 114 },
        { path: 'tables/rule_evaluation.csv', unit: 'row', count: 360, synthetic_count: 360, not_for_production_count: 360 },
        { path: 'tables/state_snapshots.csv', unit: 'row', count: 10, synthetic_count: 5, not_for_production_count: 10 },
        { path: 'tables/multimodal_evidence_index.csv', unit: 'row', count: 224, synthetic_count: 220, not_for_production_count: 220 },
      ],
    },
    {
      id: 'twm_one_map_village_standard_sample',
      label: '一张图村庄规划标准样例',
      positioning: '验证自然资源一张图村规划样例能否按 TWM 角色契约接入；所有数据均为非生产数据。',
      not_for_production: true,
      file_count: 12,
      total_count: 5671,
      synthetic_count: 530,
      not_for_production_count: 5671,
      files: [
        { path: 'parcel_current.geojson', unit: 'feature', count: 2217, synthetic_count: 0, not_for_production_count: 2217 },
        { path: 'synthetic_projects.geojson', unit: 'feature', count: 36, synthetic_count: 36, not_for_production_count: 36 },
        { path: 'synthetic_pbf.geojson', unit: 'feature', count: 274, synthetic_count: 274, not_for_production_count: 274 },
        { path: 'synthetic_eco_redline.geojson', unit: 'feature', count: 1, synthetic_count: 0, not_for_production_count: 1 },
        { path: 'synthetic_planning_zones.geojson', unit: 'feature', count: 2457, synthetic_count: 0, not_for_production_count: 2457 },
        { path: 'synthetic_annual_change.geojson', unit: 'feature', count: 260, synthetic_count: 0, not_for_production_count: 260 },
        { path: 'synthetic_urban_boundary.geojson', unit: 'feature', count: 194, synthetic_count: 0, not_for_production_count: 194 },
        { path: 'tables/approval_records.csv', unit: 'row', count: 36, synthetic_count: 36, not_for_production_count: 36 },
        { path: 'tables/review_tasks.csv', unit: 'row', count: 24, synthetic_count: 24, not_for_production_count: 24 },
        { path: 'tables/rule_evaluation.csv', unit: 'row', count: 108, synthetic_count: 108, not_for_production_count: 108 },
        { path: 'tables/state_snapshots.csv', unit: 'row', count: 11, synthetic_count: 0, not_for_production_count: 11 },
        { path: 'tables/multimodal_evidence_index.csv', unit: 'row', count: 53, synthetic_count: 52, not_for_production_count: 53 },
      ],
    },
  ],
  validation_snapshot: {
    production_ready_observed_history_rows: 0,
    production_policy_history_status: 'not_provided',
    production_policy_history_row_count: 0,
    production_policy_allowed_count: 0,
    production_policy_blocked_count: 0,
    structural_fixture: { row_count: 48, pair_count: 24, structural_status: 'pass', default_status: 'review' },
    synthetic_experiment: {
      row_count: 256,
      pair_count: 128,
      region_count: 4,
      period_count: 8,
      split_counts: { train: 160, validation: 48, test: 48 },
      action_mask_allowed_count: 64,
      action_mask_blocked_count: 64,
      structural_status: 'pass',
      default_status: 'review',
    },
    local_observed_history: {
      status: 'missing_required_columns',
      missing: ['真实审批结论', '真实复核记录', '真实政策动作标签'],
      relation_neighbor_edge_count: 0,
    },
    project_review_context: {
      project_count: 0,
      rule_eval_count: 0,
      review_task_count: 0,
    },
    external_support: {
      paper7_caliper_matched_status: 'external_reference_only',
      paper7_caliper_matched_pair_count: 0,
      boundary: '外部因果校准材料只能作为方法参考，不能替代 TWM 生产审批历史验证。',
    },
  },
  supported_problems: [
    { problem: '工程 MVP 与回归测试', support: '验证状态构建、角色绑定、规则评价、证据链、审计报告和 TWM 前端工作流。' },
    { problem: '业务审查脚手架', support: '模拟耕地保护、生态红线、用途管制、审批一致性和复核任务风险暴露。' },
    { problem: '优化/规划消费者链路', support: '测试候选方案载入、硬约束过滤、beam ranking 和 action-mask 安全头。' },
  ],
  unsupported_claims: [
    { claim: '生产级审批结论', reason: '审批、复核、执法和规则命中记录主要为合成或非生产数据。' },
    { claim: '真实治理效果预测或因果改进', reason: '尚无非合成生产观察历史、真实 treated/control 样本和政策动作标签。' },
  ],
  problem_data_fit: [
    {
      business_problem: '耕地保护与占补平衡审查',
      current_fit: 'partial',
      why: '图斑、永久基本农田、生态红线、项目、规则命中和证据链结构齐备，但关键边界和审批记录仍非生产数据。',
      safe_output: '风险暴露、证据缺口、人工复核任务和候选方案审计。',
      unsafe_output: '自动审批通过/不通过或真实政策效果承诺。',
    },
    {
      business_problem: '建设项目用地合规预审',
      current_fit: 'partial',
      why: '可模拟项目-分区-边界-复核任务关系，但缺真实项目流转、补正、处置和监管闭环历史。',
      safe_output: '合规预审工作流原型和审查清单。',
      unsafe_output: '生产级项目合规结论。',
    },
    {
      business_problem: '国土空间用途调整推演',
      current_fit: 'experimental',
      why: '合成多期样本可测动作条件动态和 planner consumer，但缺真实跨期状态和政策动作标签。',
      safe_output: '反事实推演管线、动作可行性掩码和方案比选方法验证。',
      unsafe_output: '真实区域规划效果预测。',
    },
  ],
  required_next_data: [
    { priority: 'P0', data: '真实或脱敏的项目审批/复核/补正/执法历史', unlocks: '生产观察历史、业务效果评估和真实基线对比。' },
    { priority: 'P0', data: '权威管控边界与规划约束版本', unlocks: '真实硬约束冲突判断和规则条款追溯。' },
  ],
  mentor_answer: {
    short_answer: '目前 TWM 靠谱的部分是工程和研究假设验证，不是生产落地证明。',
    research_judgment: '下一阶段应把研究问题收敛到真实未满足需求，并用真实或脱敏业务样本与 manual/rule-only/simulator/optimizer baseline 对比。',
  },
  source_reports: {
    health_markdown: 'docs/reports/twm_data_foundation_health.md',
    validation_json: 'docs/reports/twm_data_foundation_validation.json',
  },
};

const FALLBACK_CLAIM_MATRIX: TwmResearchClaimMatrix = {
  status: 'review',
  claim_boundary: '每一项 TWM 研究主张都必须说明未满足业务需求、可对比的简单基线、最低真实数据证据、评价指标和可证伪条件，之后才可能从原型状态升级。',
  current_data_gate: {
    production_ready_observed_history_rows: 0,
    production_policy_history_row_count: 0,
    production_deployment_supported: false,
    predictive_or_causal_claim_supported: false,
  },
  claims: [
    {
      claim_id: 'C1_state_conflict_recall',
      claim: '对象-关系-规则-证据状态相比逐图层人工 GIS 审查，能够减少硬约束冲突漏检。',
      baseline: 'manual_gis_overlay_checklist',
      current_status: 'engineering_supported_production_unvalidated',
      current_evidence: '合成样例验证了链路行为；真实冲突召回率尚未验证。',
      gate: { status: 'review', claim_level: 'prototype_scaffold', missing: ['production_observed_history', 'named_real_workflow_baseline'] },
      metrics: [{ name: 'hard_constraint_conflict_recall', minimum_pass: 0.95 }],
    },
    {
      claim_id: 'C2_audit_defensibility',
      claim: '证据门控复核相比单纯空间合规规则引擎，能够提升审计可辩护性。',
      baseline: 'rule_only_spatial_compliance_engine',
      current_status: 'scaffold_supported_real_audit_unvalidated',
      gate: { status: 'review', claim_level: 'prototype_scaffold', missing: ['production_observed_history', 'named_real_workflow_baseline'] },
      metrics: [{ name: 'audit_trail_completeness', minimum_pass: 0.9 }],
    },
    {
      claim_id: 'C3_action_conditioned_triage',
      claim: '行动条件动态推演相比模拟器或单纯优化排序，能够改进方案预筛和解释。',
      baseline: 'land_use_simulator_or_optimization_only_ranking',
      current_status: 'experimental_synthetic_only',
      gate: { status: 'review', claim_level: 'prototype_scaffold', missing: ['production_observed_history', 'production_policy_action_labels'] },
      metrics: [{ name: 'legal_feasible_topk_precision', minimum_pass: 0.8 }],
    },
  ],
  next_experiments: [
    { priority: 'P0', experiment: '历史审批回放', question: '在真实历史项目上是否优于人工或单纯规则基线？' },
    { priority: 'P0', experiment: '操作员流程访谈与耗时测量', question: '目标业务是否真有未满足需求？' },
  ],
  mentor_answer: 'TWM 的创新性不能靠列举模型组件来证明，必须绑定真实业务问题、简单基线、数据门槛和可证伪指标。',
};

const DEMO_BUNDLES = [
  {
    key: 'bishan',
    label: '璧山演示',
    bundleDir: 'data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion',
    optimizationDir: 'data_agent/test_data/twm_bishan_demo/optimization',
    regionCode: '500227',
  },
  {
    key: 'multi_admin',
    label: '璧山多行政单元',
    bundleDir: 'data_agent/test_data/twm_bishan_multi_admin_eval',
    optimizationDir: 'data_agent/test_data/twm_bishan_multi_admin_eval/optimization',
    regionCode: '500227',
  },
  {
    key: 'one_map',
    label: '一张图村庄',
    bundleDir: 'data_agent/test_data/twm_one_map_village_standard_sample',
    optimizationDir: 'data_agent/test_data/twm_one_map_village_standard_sample/optimization',
    regionCode: '500227',
  },
];

const TWM_DEMO_MAP_CENTER: [number, number] = [29.7771813765, 106.2598609625];

const TWM_MAP_STAGE_LABELS: Record<TwmMapStage | 'none', string> = {
  none: '未联动',
  locate: '审查区定位',
  risk: '风险命中',
  plan: '推荐方案',
};

const TWM_SUB_TABS: Array<{ id: TwmSubTab; label: string; summary: string }> = [
  { id: 'overview', label: '总览地图', summary: '先看范围和空间联动' },
  { id: 'data', label: '数据证据', summary: '主张、数据和基线' },
  { id: 'operate', label: '操作推演', summary: '规则、预测和方案' },
  { id: 'payload', label: '技术载荷', summary: '给技术人员复核' },
];

function bboxRing(minLng: number, minLat: number, maxLng: number, maxLat: number) {
  return [[
    [minLng, minLat],
    [maxLng, minLat],
    [maxLng, maxLat],
    [minLng, maxLat],
    [minLng, minLat],
  ]];
}

function twmMapFeature(id: string, name: string, role: string, coordinates: number[][][], extra: Record<string, any> = {}) {
  return {
    type: 'Feature',
    properties: {
      id,
      name,
      role,
      数据性质: '演示/非生产',
      ...extra,
    },
    geometry: {
      type: 'Polygon',
      coordinates,
    },
  };
}

function featureCollection(features: any[]) {
  return { type: 'FeatureCollection', features };
}

const TWM_MAP_FEATURES = {
  reviewArea: twmMapFeature(
    'twm_review_area',
    '璧山多行政单元审查区',
    '审查范围',
    bboxRing(106.152182211, 29.667518609, 106.367539714, 29.886844144),
    { 说明: '对应璧山多行政单元评估样例的空间范围，用于演示 TWM 如何把项目、图斑、管控边界和规则放进同一审查范围。' },
  ),
  project: twmMapFeature(
    'project_demo_01',
    '拟建项目范围',
    '项目',
    bboxRing(106.215, 29.745, 106.245, 29.775),
    { 说明: '演示项目范围，用于触发耕地保护与管控边界审查。' },
  ),
  pbf: twmMapFeature(
    'pbf_demo_01',
    '永久基本农田保护边界',
    '硬约束边界',
    bboxRing(106.205, 29.728, 106.250, 29.800),
    { 规则: '永久基本农田占用需严格审查' },
  ),
  eco: twmMapFeature(
    'eco_demo_01',
    '生态保护红线演示区',
    '硬约束边界',
    bboxRing(106.250, 29.748, 106.310, 29.825),
    { 规则: '生态保护红线内建设活动需重点复核' },
  ),
  hardConflict: twmMapFeature(
    'risk_hit_hard_01',
    '硬约束冲突',
    '规则命中',
    bboxRing(106.220, 29.752, 106.238, 29.770),
    { 风险等级: '高', 命中规则: '永久基本农田占用风险', 建议动作: '保护/复核' },
  ),
  evidenceGap: twmMapFeature(
    'risk_hit_evidence_01',
    '证据不足复核区',
    '规则命中',
    bboxRing(106.245, 29.760, 106.262, 29.780),
    { 风险等级: '中', 命中规则: '证据覆盖不足', 建议动作: '补正材料' },
  ),
  recommended: twmMapFeature(
    'candidate_recommended_01',
    '推荐调整方案',
    '推荐方案',
    bboxRing(106.180, 29.695, 106.205, 29.720),
    { 规划收益: '较高', 约束风险: '较低', 说明: '避开硬约束边界，进入推荐集。' },
  ),
  blocked: twmMapFeature(
    'candidate_blocked_01',
    '阻断候选方案',
    '阻断方案',
    bboxRing(106.232, 29.758, 106.255, 29.782),
    { 阻断原因: '触碰永久基本农田/生态红线复核区', 说明: '硬约束未通过，不能进入推荐集。' },
  ),
};

function twmMapLayers(stage: TwmMapStage) {
  const layers: any[] = [
    {
      name: 'TWM 审查范围',
      type: 'polygon',
      geojsonData: featureCollection([TWM_MAP_FEATURES.reviewArea]),
      style: { color: '#38bdf8', fillColor: '#38bdf8', fillOpacity: 0.08, weight: 2 },
    },
    {
      name: '拟建项目范围',
      type: 'polygon',
      geojsonData: featureCollection([TWM_MAP_FEATURES.project]),
      style: { color: '#f59e0b', fillColor: '#f59e0b', fillOpacity: 0.25, weight: 2 },
    },
    {
      name: '硬约束边界',
      type: 'polygon',
      geojsonData: featureCollection([TWM_MAP_FEATURES.pbf, TWM_MAP_FEATURES.eco]),
      style: { color: '#22c55e', fillColor: '#22c55e', fillOpacity: 0.12, weight: 2 },
    },
  ];

  if (stage === 'risk' || stage === 'plan') {
    layers.push({
      name: '规则命中风险',
      type: 'polygon',
      geojsonData: featureCollection([TWM_MAP_FEATURES.hardConflict, TWM_MAP_FEATURES.evidenceGap]),
      style: { color: '#ef4444', fillColor: '#ef4444', fillOpacity: 0.38, weight: 2 },
    });
  }

  if (stage === 'plan') {
    layers.push(
      {
        name: '推荐方案',
        type: 'polygon',
        geojsonData: featureCollection([TWM_MAP_FEATURES.recommended]),
        style: { color: '#0ea5e9', fillColor: '#22c55e', fillOpacity: 0.36, weight: 3 },
      },
      {
        name: '阻断方案',
        type: 'polygon',
        geojsonData: featureCollection([TWM_MAP_FEATURES.blocked]),
        style: { color: '#dc2626', fillColor: '#dc2626', fillOpacity: 0.18, weight: 3 },
      },
    );
  }

  return layers;
}

function dataFoundationLayerStyle(name: string) {
  const text = name.toLowerCase();
  if (text.includes('project')) {
    return { color: '#f97316', fillColor: '#f97316', weight: 2.2, opacity: 0.95, fillOpacity: 0.48 };
  }
  if (text.includes('pbf')) {
    return { color: '#22c55e', fillColor: '#22c55e', weight: 2, opacity: 0.95, fillOpacity: 0.34 };
  }
  if (text.includes('eco')) {
    return { color: '#a855f7', fillColor: '#a855f7', weight: 2, opacity: 0.95, fillOpacity: 0.32 };
  }
  if (text.includes('planning')) {
    return { color: '#eab308', fillColor: '#eab308', weight: 1.7, opacity: 0.9, fillOpacity: 0.26 };
  }
  if (text.includes('annual') || text.includes('change')) {
    return { color: '#ef4444', fillColor: '#ef4444', weight: 1.8, opacity: 0.92, fillOpacity: 0.36 };
  }
  if (text.includes('urban')) {
    return { color: '#06b6d4', fillColor: '#06b6d4', weight: 1.8, opacity: 0.9, fillOpacity: 0.28 };
  }
  return { color: '#38bdf8', fillColor: '#38bdf8', weight: 1.2, opacity: 0.85, fillOpacity: 0.18 };
}

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

const STATUS_LABELS: Record<string, string> = {
  ready: '就绪',
  loading: '加载中',
  unknown: '未知',
  review: '需复核',
  warning: '需关注',
  draft: '草稿',
  open: '待处理',
  pending: '待处理',
  pass: '通过',
  ok: '正常',
  success: '成功',
  completed: '完成',
  built: '已构建',
  legal_feasible: '合法可行',
  blocked: '阻断',
  error: '错误',
  failed: '失败',
  failure: '失败',
  proposed: '待验证',
  none: '无',
  high: '高',
  critical: '严重',
  medium: '中',
  low: '低',
  info: '提示',
  blocking: '阻断',
  prototype_scaffold: '原型脚手架',
};

const ACTION_LABELS: Record<string, string> = {
  inspect: '检查',
  protect: '保护',
  allocate: '配置',
  convert: '转换',
  restore: '恢复',
};

const ROLE_LABELS: Record<string, string> = {
  project: '项目',
  parcel: '图斑',
  scenario: '方案',
};

const DISPLAY_LABELS: Record<string, string> = {
  'Can a governance-oriented geospatial world model improve territorial planning decisions by coupling hierarchical GIS state, policy constraints, evidence provenance and action-conditioned forecast in one auditable loop?':
    '面向治理的国土空间世界模型，能否把分层 GIS 状态、政策约束、证据来源和行动条件预测放进同一条可审计决策链路，从而改进国土空间规划审查？',
  'Hierarchical GIS object-relation-rule-evidence state': '分层 GIS 对象-关系-规则-证据状态',
  'Action-conditioned multi-head territorial dynamics': '行动条件国土空间动态预测',
  'Evidence-gated and causally calibrated claim ladder': '证据门控与因果校准主张阶梯',
  'TWM represents parcels, projects, control boundaries, planning zones, approvals, evidence and rules as a linked state rather than as a flat feature table.':
    'TWM 把图斑、项目、管控边界、规划分区、审批、证据和规则组织成可追溯的关联状态，而不是扁平要素表。',
  'TWM forecasts future latent state, constraint-risk, planning utility, uncertainty and action-mask feasibility conditional on review/protect/convert/restore actions.':
    'TWM 围绕复核、保护、转换、恢复等治理动作预测潜在状态、约束风险、规划效用、不确定性和动作可行性。',
  'TWM separates deterministic rule evidence, observational causal calibration and validation gates before upgrading any operational claim.':
    'TWM 在升级任何业务主张前，先区分确定性规则证据、观察性因果校准和验证门槛。',
  'The novelty is architectural integration, not that GIS simulation itself is new.':
    '创新点是面向业务决策的架构集成，而不是声称 GIS 模拟本身是新问题。',
  'Compare against land-use simulators, GIS rule engines and optimization tools on whether they jointly expose action-conditioned forecast, policy evidence and audit-ready claim boundaries.':
    '与土地利用模拟、GIS 规则引擎和优化工具对比，看其是否同时给出行动条件预测、政策证据和可审计主张边界。',
  'Object-relation-rule-evidence state reduces missed compliance conflicts compared with layer-by-layer manual review.':
    '对象-关系-规则-证据状态相比逐图层人工审查，减少合规冲突漏检。',
  'Measure hard-constraint conflict recall and false review burden on held-out real approval/review cases.':
    '在留出的真实审批/复核案例上度量硬约束冲突召回和误复核负担。',
  'Evidence-gated forecasts improve decision defensibility compared with black-box planning scores.':
    '证据门控预测相比黑箱规划分数，提升决策可辩护性。',
  'Audit whether every recommended or rejected option carries source evidence, rule clause, uncertainty and human-review reason.':
    '审计每个推荐或拒绝方案是否带有来源证据、规则条款、不确定性和人工复核原因。',
  'Planning and land-use review workflows still fragment spatial overlays, policy checks, approval evidence and scenario comparison across separate tools.':
    '规划和用地审查中，空间叠加、政策核查、审批证据和方案比较仍常分散在不同工具中。',
  'Existing land-use simulators emphasize spatial pattern transition, while operational review needs action consequences, rule validity and audit boundaries.':
    '现有土地利用模拟更强调空间格局转移，而业务审查需要动作后果、规则有效性和审计边界。',
  'Optimization tools can rank candidates, but often do not preserve why a candidate is illegal, under-evidenced or only reviewable rather than approvable.':
    '优化工具可以排序候选方案，但往往不能保留“为什么违法、证据不足或只能复核不能审批”的理由。',
  'Manual GIS overlay plus checklist review': '人工 GIS 叠加加清单审查',
  'Rule-only spatial compliance engine': '单纯空间合规规则引擎',
  'Land-use simulation models such as FLUS/PLUS/CLUE-S/CA-Markov for pattern transition':
    '用于格局转移的 FLUS/PLUS/CLUE-S/CA-Markov 等土地利用模拟模型',
  'Optimization-only farmland or planning candidate ranking without evidence-gated claim validation':
    '不带证据门控主张验证的耕地或规划候选方案优化排序',
  'If real workflow interviews show the target decisions are already well solved by existing tools, TWM should be narrowed or stopped.':
    '如果真实业务访谈显示目标决策已被现有工具很好解决，TWM 应收窄或停止。',
  'If TWM does not improve hard-constraint conflict recall, evidence completeness or audit-trail quality over baselines, the claimed contribution is not supported.':
    '如果 TWM 相比基线不能提升硬约束冲突召回、证据完整性或审计链质量，则贡献主张不成立。',
  'If action-conditioned dynamics cannot be validated beyond synthetic fixtures, TWM must remain a review scaffold rather than a production decision model.':
    '如果行动条件动态只能在合成样例上验证，TWM 必须保持复核脚手架定位，而不能作为生产决策模型。',
  'Collect real or sanitized approval/review histories with project geometry, rule outcomes, evidence links and final decisions.':
    '收集带项目几何、规则结果、证据链接和最终决策的真实或脱敏审批/复核历史。',
  'Benchmark against manual overlay, rule-only engine and at least one land-use simulation or optimization baseline where appropriate.':
    '按场景与人工叠加、单纯规则引擎，以及至少一种土地利用模拟或优化基线对比。',
  'Report missed hard-constraint conflicts, review-task precision, evidence completeness, candidate rejection reason coverage and audit-trail completeness.':
    '报告硬约束漏检、复核任务精度、证据完整性、候选方案拒绝原因覆盖和审计链完整性。',
  'Keep synthetic fixtures for regression only; do not use them as production-effect evidence.':
    '合成样例只用于回归测试，不作为生产效果证据。',
  'Current TWM is a rigorous prototype and review scaffold. Its defensible near-term claim is auditable decision support for territorial governance workflows; production-grade predictive claims require real observed histories, baseline comparisons and external validation.':
    '当前 TWM 是严谨的原型和复核脚手架；近期可辩护主张是为国土治理流程提供可审计决策支持，生产级预测主张仍需真实观察历史、基线对比和外部验证。',
  'Object-relation-rule-evidence state reduces missed hard-constraint conflicts compared with layer-by-layer manual GIS review.':
    '对象-关系-规则-证据状态相比逐图层人工 GIS 审查，能够减少硬约束冲突漏检。',
  'Evidence-gated review improves audit defensibility compared with rule-only spatial compliance engines.':
    '证据门控复核相比单纯空间合规规则引擎，能够提升审计可辩护性。',
  'Action-conditioned dynamics improves plan-option triage compared with land-use simulators or optimization-only candidate ranking.':
    '行动条件动态推演相比土地利用模拟或单纯优化排序，能够改进方案预筛和解释。',
  'Synthetic fixtures verify the pipeline and rule/evidence object model, but do not validate real conflict recall.':
    '合成样例验证了流程和规则/证据对象模型，但尚未验证真实冲突召回率。',
  'Current rule hits, evidence items and review tasks are synthetic/not-for-production; useful for regression, not for audit quality proof.':
    '当前规则命中、证据项和复核任务为合成或非生产数据，可用于回归测试，不能证明真实审计质量。',
  'Synthetic experiment foundation supports action-mask and beam-plan plumbing; no real action-conditioned dynamics validation yet.':
    '合成实验基础支撑动作可行性掩码和方案比选链路，但尚未完成真实行动条件动态验证。',
  'Every TWM research claim must name the unmet business need, a simpler baseline, minimum real-data evidence, metrics and falsification conditions before it can be upgraded beyond prototype status.':
    '每一项 TWM 研究主张都必须说明未满足业务需求、可对比的简单基线、最低真实数据证据、评价指标和可证伪条件，之后才可能从原型状态升级。',
  'This report can compare metrics against a named baseline, but it does not upgrade TWM claims unless real-data gates and metric thresholds both pass.':
    '该报告可以与明确基线做指标对比；只有真实数据门槛和指标阈值同时通过，才允许升级 TWM 主张。',
  manual_gis_overlay_checklist: '人工 GIS 叠加清单',
  rule_only_spatial_compliance_engine: '单纯空间合规规则引擎',
  land_use_simulator_or_optimization_only_ranking: '土地利用模拟或单纯优化排序',
  ad_hoc_layer_mapping: '临时图层和字段映射',
  farmland_protection_review: '耕地保护与占补平衡审查',
  construction_project_compliance: '建设项目合规初审',
  territorial_plan_adjustment: '国土空间用途调整推演',
  C1_state_conflict_recall: 'C1 硬约束冲突召回',
  C2_audit_defensibility: 'C2 审计可辩护性',
  C3_action_conditioned_triage: 'C3 行动条件方案预筛',
  C4_standard_contract_ingestion: 'C4 标准数据契约接入',
  'C1 same-case hard-constraint conflict recall export': 'C1 同案硬约束冲突召回导出',
  'C2 same-case audit defensibility export': 'C2 同案审计可辩护性导出',
  'C3 same-case plan-option triage export': 'C3 同案方案预筛导出',
  'Manual GIS overlay plus checklist export': '人工 GIS 叠加清单导出',
  'Rule-only spatial compliance engine export': '单纯空间合规规则引擎导出',
  'Land-use simulator or optimization-only ranking export': '土地利用模拟或单纯优化排序导出',
  'Bishan demo engineering fixture': '璧山演示工程样例',
  'Bishan multi-admin evaluation fixture': '璧山多行政单元评估样例',
  'One Map village standard sample': '一张图村庄规划标准样例',
  mixed_real_imagery_plus_synthetic_governance_fixture: '真实影像加合成治理样例',
  synthetic_multi_admin_governance_fixture: '合成多行政单元治理样例',
  standard_structure_sample_with_synthetic_substitutes: '含合成替代数据的标准结构样例',
  production_observed_history: '生产观察历史',
  named_real_workflow_baseline: '明确的真实工作流基线',
  production_policy_action_labels: '生产政策动作标签',
  baseline_metrics: '基线指标',
  twm_metrics: 'TWM 指标',
  comparable_metrics: '可比指标',
  synthetic_records: '合成记录',
  not_for_production_records: '非生产记录',
  not_for_production: '非生产数据',
  not_provided: '未提供',
  load_on_map: '可加载到地图',
  fix_crs_before_map_overlay: '先做 CRS 转换',
  add_spatial_layers: '补充空间图层',
  ready_for_map_overlay: '可直接叠加',
  convert_to_wgs84_before_map_overlay: '转换为 WGS84 后叠加',
  inspect_geometry_before_map_overlay: '先检查几何范围',
  payload: '请求载荷',
  none: '无',
  hard_constraint_conflict_recall: '硬约束冲突召回率',
  missed_blocking_conflict_rate: '阻断性冲突漏检率',
  evidence_link_completeness: '证据链接完整性',
  audit_trail_completeness: '审计链完整性',
  unsupported_recommendation_rate: '无证据建议率',
  review_task_precision: '复核任务精度',
  candidate_rejection_reason_coverage: '候选方案拒绝原因覆盖率',
  legal_feasible_topk_precision: '合法可行 Top-K 精度',
  planner_regret_against_human_oracle: '相对人工专家的规划后悔值',
  role_binding_accuracy: '角色绑定准确率',
  value_domain_violation_detection_recall: '值域违规检测召回率',
  onboarding_rework_rate: '接入返工率',
  engineering_supported_production_unvalidated: '工程链路已验证，生产效果未验证',
  scaffold_supported_real_audit_unvalidated: '复核脚手架已验证，真实审计效果未验证',
  experimental_synthetic_only: '仅合成实验',
  standard_structure_supported_cross_region_unvalidated: '标准结构已验证，跨区域生产效果未验证',
  remain_prototype_scaffold: '保持原型脚手架',
  baseline_evidence_not_provided: '基线证据未提供',
  eligible_for_retrospective_evidence: '可进入历史回放验证',
  metrics_pass_but_data_gate_blocks_upgrade: '指标通过但真实数据门槛阻止升级',
  no_metric_lift_over_baseline: '相对基线没有指标增益',
  baseline_comparison: '基线对比',
  baseline_export_validation: '基线导出校验',
  baseline_export_validation_run_card: '基线导出校验运行卡片',
  baseline_comparison_run_card: '基线对比运行卡片',
  review_required: '需要复核',
  claim_supported: '主张有证据支撑',
  hard_blocked: '硬约束阻断',
  eligible: '可进入后续流程',
  export_validation: '导出校验',
  comparison_completed: '对比已完成',
  same_case_join_key: '同案关联键',
  missing_required_columns: '缺少必填字段',
  coverage_below_minimum: '重叠覆盖不足',
  no_overlap: '没有同案重叠',
  parser_metric_missing: '解析指标缺失',
  'package case-level evidence and baseline outputs for external review': '打包案例级证据和基线输出，供外部复核',
  'repeat on a held-out region/time split before pilot claim': '在留出的区域/时间切分上重复验证后，再提出试点主张',
  'collect real or sanitized production history required by the claim gate': '收集主张门槛要求的真实或脱敏生产历史',
  'inspect failed metrics and simplify the TWM claim': '检查未通过指标，并收窄 TWM 主张',
  'do not add new model backends until the baseline gap is understood': '在理解基线差距前，不新增模型后端',
  'provide both TWM metrics and named baseline metrics for the same cases': '为同一批案例同时提供 TWM 指标和明确基线指标',
  'keep the claim at prototype scaffold level': '将主张保持在原型脚手架级别',
};

function labelFor(value: any, labels: Record<string, string>, fallback = '-') {
  const text = String(value || '').trim();
  if (!text) return fallback;
  return labels[text.toLowerCase()] || text;
}

function statusText(value: any, fallback = '-') {
  return labelFor(value, STATUS_LABELS, fallback);
}

function yesNo(value: any) {
  return value ? '是' : '否';
}

function mapOverlayReadinessText(value?: string) {
  const normalized = String(value || '').toLowerCase();
  if (normalized === 'ready') return '可直接叠加';
  if (normalized === 'blocked') return '需 CRS 转换';
  if (normalized === 'empty') return '无空间图层';
  return statusText(value, '未检测');
}

function crsDiagnosticText(value?: string) {
  const normalized = String(value || '').toLowerCase();
  if (normalized === 'wgs84_lonlat') return 'WGS84 经纬度';
  if (normalized === 'projected_or_non_wgs84') return '需 CRS 转换';
  if (normalized === 'lonlat_degrees') return '经纬度';
  if (normalized === 'projected_or_large_numeric') return '投影/大数坐标';
  return statusText(value, '未检测');
}

function displayText(value: any, fallback = '-') {
  const text = String(value || '').trim();
  if (!text) return fallback;
  const mapped = DISPLAY_LABELS[text] || STATUS_LABELS[text.toLowerCase()] || text;
  return mapped
    .replace(/synthetic\/not-for-production/g, '合成或非生产数据')
    .replace(/not-for-production/g, '非生产数据')
    .replace(/rule-only/g, '单纯规则')
    .replace(/manual GIS overlay/g, '人工 GIS 叠加')
    .replace(/optimization-only/g, '单纯优化')
    .replace(/beam ranking/g, '方案比选排序')
    .replace(/action-mask/g, '动作可行性掩码');
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

function compactList(values: any[] | undefined, fallback = '无') {
  const rows = (values || []).filter(Boolean).map(String);
  return rows.length ? rows.slice(0, 4).join(', ') : fallback;
}

function compactDisplayList(values: any[] | undefined, fallback = '无') {
  const rows = (values || []).filter(Boolean).map(item => displayText(item));
  return rows.length ? rows.slice(0, 4).join(', ') : fallback;
}

function compactBbox(value: any, fallback = '无范围') {
  if (!Array.isArray(value) || value.length !== 4) return fallback;
  return value.map(item => {
    const num = Number(item);
    if (!Number.isFinite(num)) return '-';
    return Math.abs(num) > 1000 ? num.toFixed(0) : num.toFixed(3);
  }).join(', ');
}

const TWM_PROPERTY_FIELD_PRIORITY = [
  'XMMC',
  'project_name',
  'YDMJ',
  'approval_status',
  'risk_scenario',
  'SZXZQMC',
  'TDYTMC',
  'DLMC',
  'zone_type',
  'change_type',
];

function compactSamplePropertyValue(value: any) {
  if (value === null || value === undefined || value === '') return '空';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') return Number.isInteger(value) ? fmt(value, 0) : String(Number(value.toFixed(3)));
  const text = String(value);
  return text.length > 18 ? `${text.slice(0, 18)}...` : text;
}

function compactPropertyFieldNames(fields?: TwmDataFoundationPropertyField[], totalCount?: number) {
  const names = (fields || []).map(field => field.name).filter(Boolean);
  if (!names.length) return '无字段';
  const priority = TWM_PROPERTY_FIELD_PRIORITY.filter(name => names.includes(name));
  const ranked = [...priority, ...names.filter(name => !priority.includes(name))].slice(0, 5);
  const count = Number(totalCount || names.length);
  return `${fmt(count, 0)} 个：${ranked.join('、')}${count > ranked.length ? ' 等' : ''}`;
}

function compactSampleProperties(sample?: Record<string, any>) {
  const source = sample || {};
  const entries = Object.entries(source);
  if (!entries.length) return '无样例属性';
  const priorityEntries = TWM_PROPERTY_FIELD_PRIORITY
    .filter(name => Object.prototype.hasOwnProperty.call(source, name))
    .map(name => [name, source[name]] as [string, any]);
  const ranked = [
    ...priorityEntries,
    ...entries.filter(([name]) => !priorityEntries.some(([priorityName]) => priorityName === name)),
  ].slice(0, 2);
  return ranked.map(([name, value]) => `${name}=${compactSamplePropertyValue(value)}`).join('；');
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
  const [mapStage, setMapStage] = useState<TwmMapStage | 'none'>('none');
  const [activeSubTab, setActiveSubTab] = useState<TwmSubTab>('overview');
  const [selectedDataPackageId, setSelectedDataPackageId] = useState('twm_bishan_multi_admin_eval');
  const [dataMapPreviewLoading, setDataMapPreviewLoading] = useState(false);
  const [dataMapPreviewSummary, setDataMapPreviewSummary] = useState('');
  const [dataMapPreview, setDataMapPreview] = useState<TwmDataFoundationMapPreview | null>(null);
  const [visibleDataMapLayerNames, setVisibleDataMapLayerNames] = useState<string[]>([]);

  const [projectName, setProjectName] = useState('TWM 璧山演示工作空间');
  const [regionCode, setRegionCode] = useState('500227');
  const [bundleDir, setBundleDir] = useState(DEMO_BUNDLES[0].bundleDir);
  const [optimizationDir, setOptimizationDir] = useState(DEMO_BUNDLES[0].optimizationDir);
  const [stateLabel, setStateLabel] = useState('璧山 MMFE TWM 状态');
  const [includeAuxiliary, setIncludeAuxiliary] = useState(true);
  const [actionType, setActionType] = useState('protect');
  const [targetRole, setTargetRole] = useState('project');
  const [scenario, setScenario] = useState(FALLBACK_BUSINESS_SCENARIOS[0].label);
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
  const dataPackages = dataFoundation.datasets || FALLBACK_DATA_FOUNDATION.datasets || [];
  const selectedDataPackage = (
    dataPackages.find(item => item.id === selectedDataPackageId) || dataPackages[0] || null
  );
  const selectedSpatialLayerCatalog = selectedDataPackage?.spatial_layer_catalog || [];
  const claimDataGate = claimMatrix.current_data_gate || FALLBACK_CLAIM_MATRIX.current_data_gate || {};
  const readiness = useMemo(() => {
    const repository = status?.repository || {};
    return [
      { label: '项目', value: repository.project_count ?? projects.length },
      { label: '状态', value: repository.state_version_count ?? states.length },
      { label: '规则', value: repository.policy_rule_count ?? '-' },
      { label: '命中', value: repository.rule_hit_count ?? hits.length },
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
    setProjectName(`TWM ${preset.label}工作空间`);
  };

  const applyBusinessScenario = (scenarioId: string) => {
    const item = businessScenarios.find(entry => entry.id === scenarioId) || FALLBACK_BUSINESS_SCENARIOS[0];
    setSelectedBusinessScenarioId(item.id);
    setProjectName(`TWM ${item.label}`);
    setActionType(item.default_action_type || 'inspect');
    setTargetRole(item.default_target_role || 'project');
    setScenario(item.label || item.default_scenario || item.id);
    setEvidenceCoverage(clampRatio(item.default_evidence_coverage, 0.72));
    setHorizon(Math.max(1, Math.min(12, Number(item.default_horizon || 3))));
  };

  const selectDataPackage = (datasetId: string) => {
    setSelectedDataPackageId(datasetId);
    setDataMapPreview(null);
    setVisibleDataMapLayerNames([]);
    setDataMapPreviewSummary('');
  };

  const syncTwmMap = (stage: TwmMapStage) => {
    setMapStage(stage);
    const handler = (window as any).__handleMapUpdate;
    if (typeof handler === 'function') {
      handler({
        center: TWM_DEMO_MAP_CENTER,
        zoom: stage === 'locate' ? 11 : 12,
        layers: twmMapLayers(stage),
      });
    }
  };

  const dataFoundationLayerKey = (layer: TwmDataFoundationMapPreviewLayer) => String(layer.name || layer.path || '').trim();

  const buildDataFoundationMapLayers = (data: TwmDataFoundationMapPreview, visibleLayerNames: string[]) => {
    const visible = new Set(visibleLayerNames);
    return (data.layers || [])
      .filter((layer: TwmDataFoundationMapPreviewLayer) => visible.has(dataFoundationLayerKey(layer)))
      .map((layer: TwmDataFoundationMapPreviewLayer) => ({
        name: `数据基础 · ${displayText(layer.name || layer.path)}`,
        type: 'polygon',
        geojsonData: layer.geojson,
        style: dataFoundationLayerStyle(layer.name || layer.path || ''),
        tooltip_fields: ['_twm_source_file', '_twm_dataset_id'],
        tooltip_labels: {
          _twm_source_file: '来源文件',
          _twm_dataset_id: '数据包',
        },
      }));
  };

  const pushDataFoundationPreviewToMap = (data: TwmDataFoundationMapPreview, visibleLayerNames: string[]) => {
    const mapLayers = buildDataFoundationMapLayers(data, visibleLayerNames);
    const handler = (window as any).__handleMapUpdate;
    if (typeof handler === 'function') {
      const bbox = Array.isArray(data.bbox) ? data.bbox.map(Number) : [];
      const span = bbox.length === 4 ? Math.max(Math.abs(bbox[2] - bbox[0]), Math.abs(bbox[3] - bbox[1])) : 0;
      handler({
        center: Array.isArray(data.center) ? data.center : TWM_DEMO_MAP_CENTER,
        zoom: span > 0.24 ? 10 : span > 0.12 ? 11 : 12,
        layers: mapLayers,
      });
    }
    return mapLayers;
  };

  const applyDataFoundationMapPreview = (data: TwmDataFoundationMapPreview, summaryMode: 'full' | 'layer', layerPath = '') => {
    setDataMapPreview(data);
    const readiness = data.map_overlay_readiness || null;
    const canOverlay = !readiness || (readiness.status === 'ready' && Number(readiness.blocked_layer_count || 0) === 0);
    if (!canOverlay) {
      setVisibleDataMapLayerNames([]);
      setDataMapPreviewSummary(`未联动：${readiness?.message || '空间图层坐标不是经纬度范围，直接叠加前需要 CRS 识别和转换。'}`);
      return;
    }
    const layerNames = (data.layers || []).map(dataFoundationLayerKey).filter(Boolean);
    setVisibleDataMapLayerNames(layerNames);
    const mapLayers = pushDataFoundationPreviewToMap(data, layerNames);
    const loadedCount = data.total_preview_feature_count ?? mapLayers.reduce((sum: number, layer: any) => {
      const features = layer.geojsonData?.features;
      return sum + (Array.isArray(features) ? features.length : 0);
    }, 0);
    const readinessText = mapOverlayReadinessText(readiness?.status);
    if (summaryMode === 'layer') {
      setDataMapPreviewSummary(`已联动图层 ${layerPath}，${fmt(loadedCount, 0)} 个空间要素；坐标诊断：${readinessText}；源数据仍为演示/非生产。`);
      return;
    }
    setDataMapPreviewSummary(`已全量联动 ${mapLayers.length} 个空间图层、${fmt(loadedCount, 0)} 个空间要素；坐标诊断：${readinessText}；源数据仍为演示/非生产。`);
  };

  const toggleDataFoundationMapLayer = (layerName: string) => {
    if (!dataMapPreview) return;
    const allLayerNames = (dataMapPreview.layers || []).map(dataFoundationLayerKey).filter(Boolean);
    if (!allLayerNames.includes(layerName)) return;
    const current = visibleDataMapLayerNames.length ? visibleDataMapLayerNames : allLayerNames;
    let next = current.includes(layerName)
      ? current.filter(name => name !== layerName)
      : [...current, layerName];
    if (!next.length) {
      next = [layerName];
    }
    setVisibleDataMapLayerNames(next);
    pushDataFoundationPreviewToMap(dataMapPreview, next);
    setDataMapPreviewSummary(`当前显示 ${next.length}/${allLayerNames.length} 个空间图层；可继续用图层开关聚焦查看。`);
  };

  const syncDataFoundationMapPreview = async () => {
    if (!selectedDataPackage) {
      setError('没有可预览的数据包');
      return;
    }
    setDataMapPreviewLoading(true);
    setError('');
    try {
      const data = await api(`/api/twm/data-foundation-map-preview/${encodeURIComponent(selectedDataPackage.id)}?max_features_per_layer=all`);
      applyDataFoundationMapPreview(data, 'full');
    } catch (e: any) {
      setError(e?.message || '空间数据预览失败');
    } finally {
      setDataMapPreviewLoading(false);
    }
  };

  const syncDataFoundationLayerMapPreview = async (layerPath: string) => {
    if (!selectedDataPackage) {
      setError('没有可预览的数据包');
      return;
    }
    const normalizedLayerPath = String(layerPath || '').trim();
    if (!normalizedLayerPath) {
      setError('没有可预览的空间图层');
      return;
    }
    setDataMapPreviewLoading(true);
    setError('');
    try {
      const data = await api(
        `/api/twm/data-foundation-map-preview/${encodeURIComponent(selectedDataPackage.id)}?max_features_per_layer=all&layer=${encodeURIComponent(normalizedLayerPath)}`
      );
      applyDataFoundationMapPreview(data, 'layer', normalizedLayerPath);
    } catch (e: any) {
      setError(e?.message || '空间图层预览失败');
    } finally {
      setDataMapPreviewLoading(false);
    }
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
      syncTwmMap('locate');
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
      syncTwmMap('risk');
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
      syncTwmMap('plan');
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
            <strong>国土空间世界模型（TWM）</strong>
            <span>围绕国土业务决策组织规则证据、预测验证和方案比选</span>
          </div>
        </div>
        <button type="button" className="twm-icon-button" onClick={refreshAll} disabled={busy} title="刷新 TWM 状态">
          <RefreshCw size={13} />
          刷新
        </button>
        <span className={`status-badge ${statusClass(status?.status)}`}>
          {running === 'status' ? '检测中' : statusText(status?.status, '未知')}
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

      <div className="twm-subtabs" role="tablist" aria-label="TWM 功能分区">
        {TWM_SUB_TABS.map(item => {
          const active = activeSubTab === item.id;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              id={`twm-subtab-control-${item.id}`}
              aria-label={item.label}
              aria-selected={active}
              aria-controls={`twm-subtab-${item.id}`}
              className={`twm-subtab ${active ? 'active' : ''}`}
              onClick={() => setActiveSubTab(item.id)}
            >
              <strong>{item.label}</strong>
              <span>{item.summary}</span>
            </button>
          );
        })}
      </div>

      {activeSubTab === 'overview' && (
        <div
          className="twm-subtab-panel"
          role="tabpanel"
          id="twm-subtab-overview"
          aria-labelledby="twm-subtab-control-overview"
        >
      <section className="twm-section twm-map-story">
        <div className="twm-section-head">
          <MapPin size={14} />
          <h4>地图联动</h4>
          <span className={`status-badge ${mapStage === 'none' ? 'proposed' : 'success'}`}>
            {mapStage === 'none' ? '未联动' : `已联动：${TWM_MAP_STAGE_LABELS[mapStage]}`}
          </span>
        </div>
        <p className="twm-map-story-copy">
          先在中间地图看位置，再回到右侧看规则、证据和方案。当前图层为演示空间图层，用于说明 TWM 如何把“看图、查规则、推演、比选”串成一条业务链。
        </p>
        <div className="twm-map-story-actions">
          <button type="button" className="twm-secondary-action" onClick={() => syncTwmMap('locate')} disabled={busy}>
            <MapPin size={13} />
            定位审查区
          </button>
          <button type="button" className="twm-secondary-action" onClick={() => syncTwmMap('risk')} disabled={busy}>
            <AlertTriangle size={13} />
            展示风险命中
          </button>
          <button type="button" className="twm-secondary-action" onClick={() => syncTwmMap('plan')} disabled={busy}>
            <Route size={13} />
            展示推荐方案
          </button>
        </div>
        <div className="twm-map-story-legend">
          <span><i className="review" />审查范围/项目</span>
          <span><i className="constraint" />硬约束边界</span>
          <span><i className="risk" />风险命中</span>
          <span><i className="plan" />推荐/阻断方案</span>
        </div>
      </section>

      <section className="twm-section twm-business-section">
        <div className="twm-section-head">
          <ShieldCheck size={14} />
          <h4>业务任务</h4>
          <span className="status-badge proposed">{running === 'scenarios' ? '加载中' : selectedBusinessScenario.label}</span>
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
        </div>
      )}

      {activeSubTab === 'data' && (
        <div
          className="twm-subtab-panel"
          role="tabpanel"
          id="twm-subtab-data"
          aria-labelledby="twm-subtab-control-data"
        >
      <section className="twm-section twm-data-browser-panel">
        <div className="twm-section-head">
          <FileCheck2 size={14} />
          <h4>数据基础浏览器</h4>
          <span className={`status-badge ${statusClass(dataReadiness.status || dataFoundation.status)}`}>
            {statusText(dataReadiness.status || dataFoundation.status, '需复核')}
          </span>
        </div>
        <div className="twm-data-browser-verdict">
          <strong>当前结论</strong>
          <p>{displayText(dataReadiness.verdict)}</p>
        </div>
        <div className="twm-data-package-switcher">
          {dataPackages.map(dataset => (
            <button
              type="button"
              key={dataset.id}
              aria-label={`浏览 ${displayText(dataset.label)}`}
              className={selectedDataPackage?.id === dataset.id ? 'active' : ''}
              onClick={() => selectDataPackage(dataset.id)}
            >
              <strong>{displayText(dataset.label)}</strong>
              <span>{fmt(dataset.total_count, 0)} 条 · {dataset.not_for_production ? '演示/非生产' : '生产候选'}</span>
            </button>
          ))}
        </div>
        <div className="twm-data-browser-actions">
          <button type="button" className="twm-secondary-action" onClick={syncDataFoundationMapPreview} disabled={dataMapPreviewLoading || !selectedDataPackage}>
            {dataMapPreviewLoading ? <Loader2 size={13} className="twm-spin" /> : <MapPin size={13} />}
            全量加载空间数据
          </button>
          <span>{dataMapPreviewSummary || '将选中数据包的 GeoJSON 空间图层全量联动到中间地图；大图层由 3D 渲染路径承载。'}</span>
        </div>
        {dataMapPreview && (
          <div className="twm-crs-diagnostic-panel">
            <div className="twm-crs-diagnostic-head">
              <div>
                <strong>坐标诊断</strong>
                <span>{dataMapPreview.map_overlay_readiness?.message || '已读取空间图层坐标范围。'}</span>
              </div>
              <span className={`status-badge ${statusClass(dataMapPreview.map_overlay_readiness?.status)}`}>
                {mapOverlayReadinessText(dataMapPreview.map_overlay_readiness?.status)}
              </span>
            </div>
            <div className="twm-crs-diagnostic-kpis">
              <div><span>可叠加图层</span><strong>{fmt(dataMapPreview.map_overlay_readiness?.ready_layer_count, 0)}</strong></div>
              <div><span>需处理图层</span><strong>{fmt(dataMapPreview.map_overlay_readiness?.blocked_layer_count, 0)}</strong></div>
              <div><span>空间要素</span><strong>{fmt(dataMapPreview.total_preview_feature_count, 0)}</strong></div>
              <div><span>处理建议</span><strong>{displayText(dataMapPreview.map_overlay_readiness?.suggested_action)}</strong></div>
            </div>
            <div className="twm-crs-layer-list">
              {(dataMapPreview.layers || []).slice(0, 8).map(layer => {
                const layerName = dataFoundationLayerKey(layer);
                const visible = visibleDataMapLayerNames.includes(layerName);
                return (
                  <div key={`crs-${layer.name}`}>
                    <code>{layer.name}</code>
                    <span className={`status-badge ${layer.crs_diagnostic?.map_overlay_ready ? 'success' : 'error'}`}>
                      {crsDiagnosticText(layer.crs_diagnostic?.status)}
                    </span>
                    <span>{fmt(layer.preview_feature_count, 0)} / {fmt(layer.source_feature_count, 0)} 要素</span>
                    <button
                      type="button"
                      className={`twm-layer-visibility-toggle ${visible ? 'active' : ''}`}
                      onClick={() => toggleDataFoundationMapLayer(layerName)}
                      disabled={!layerName}
                      aria-label={`${visible ? '隐藏' : '显示'}图层 ${layerName}`}
                      title={visible ? '从地图隐藏该图层' : '在地图显示该图层'}
                    >
                      {visible ? <Eye size={12} /> : <EyeOff size={12} />}
                      <span>{visible ? '隐藏' : '显示'}</span>
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}
        {selectedDataPackage ? (
          <div className="twm-data-browser-body">
            <div className="twm-data-browser-summary">
              <div>
                <span>数据包 ID</span>
                <strong>{selectedDataPackage.id}</strong>
              </div>
              <div>
                <span>总量</span>
                <strong>{fmt(selectedDataPackage.total_count, 0)}</strong>
              </div>
              <div>
                <span>文件</span>
                <strong>{fmt(selectedDataPackage.file_count || selectedDataPackage.files?.length, 0)}</strong>
              </div>
              <div>
                <span>非生产</span>
                <strong>{fmt(selectedDataPackage.not_for_production_count, 0)}</strong>
              </div>
            </div>
            <p className="twm-data-browser-positioning">
              {displayText(selectedDataPackage.positioning || selectedDataPackage.nature)}
            </p>
            {selectedSpatialLayerCatalog.length > 0 && (
              <div className="twm-spatial-catalog-panel">
                <div className="twm-spatial-catalog-head">
                  <div>
                    <strong>空间图层目录</strong>
                    <span>不加载完整几何，也能先核查每个空间图层的范围和坐标状态。</span>
                  </div>
                  <span className={`status-badge ${statusClass(selectedDataPackage.map_overlay_readiness?.status)}`}>
                    {mapOverlayReadinessText(selectedDataPackage.map_overlay_readiness?.status)}
                  </span>
                </div>
                <div className="twm-spatial-catalog-list">
                  {selectedSpatialLayerCatalog.slice(0, 8).map(layer => {
                    const layerPath = layer.name || layer.path || '';
                    return (
                      <div key={`spatial-catalog-${selectedDataPackage.id}-${layerPath}`}>
                        <button
                          type="button"
                          className="twm-spatial-catalog-action"
                          onClick={() => syncDataFoundationLayerMapPreview(layerPath)}
                          disabled={dataMapPreviewLoading || !layerPath}
                          aria-label={`上图 ${layerPath}`}
                          title="加载该图层到地图"
                        >
                          <MapPin size={12} />
                          <span>上图</span>
                        </button>
                        <div className="twm-spatial-catalog-main">
                          <code>{layerPath}</code>
                          <span>{fmt(layer.source_feature_count ?? layer.feature_count, 0)} 要素</span>
                          <span>{compactBbox(layer.bbox)}</span>
                          <span className={`status-badge ${layer.crs_diagnostic?.map_overlay_ready ? 'success' : 'error'}`}>
                            {crsDiagnosticText(layer.crs_diagnostic?.status)}
                          </span>
                          <div className="twm-spatial-catalog-attributes">
                            <span>字段 {compactPropertyFieldNames(layer.property_fields, layer.property_field_count)}</span>
                            <span>样例 {compactSampleProperties(layer.sample_properties)}</span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            <div className="twm-data-browser-table" role="table" aria-label="数据基础文件清单">
              <div role="row" className="head">
                <span role="columnheader">文件</span>
                <span role="columnheader">数量</span>
                <span role="columnheader">合成</span>
                <span role="columnheader">非生产</span>
              </div>
              {(selectedDataPackage.files || []).map(file => (
                <div role="row" key={`${selectedDataPackage.id}-browser-${file.path}`}>
                  <code role="cell">{file.path}</code>
                  <span role="cell">{fmt(file.count, 0)} {file.unit || '条'}</span>
                  <span role="cell">{fmt(file.synthetic_count, 0)}</span>
                  <span role="cell">{fmt(file.not_for_production_count, 0)}</span>
                </div>
              ))}
            </div>
            <div className="twm-data-browser-columns">
              <article>
                <strong>能支撑</strong>
                {(dataFoundation.supported_problems || []).slice(0, 4).map(item => (
                  <p key={`browser-support-${item.problem}`}>{displayText(item.problem)}：{displayText(item.support)}</p>
                ))}
              </article>
              <article>
                <strong>不能承诺</strong>
                {(dataFoundation.unsupported_claims || []).slice(0, 4).map(item => (
                  <p key={`browser-unsupported-${item.claim}`}>{displayText(item.claim)}：{displayText(item.reason)}</p>
                ))}
              </article>
              <article>
                <strong>下一步权威数据</strong>
                {(dataFoundation.required_next_data || []).slice(0, 4).map(item => (
                  <p key={`browser-next-${item.data}`}>{item.priority ? `${item.priority} · ` : ''}{displayText(item.data)}：{displayText(item.unlocks || item.minimum)}</p>
                ))}
              </article>
            </div>
          </div>
        ) : (
          <div className="twm-empty">暂无可浏览的数据包</div>
        )}
      </section>

      <details className="twm-section twm-research-panel" open>
        <summary>
          <span>研究边界</span>
          <code>{running === 'positioning' ? '加载中' : '原型验证主张'}</code>
        </summary>
        <div className="twm-research-question">{displayText(researchPositioning.research_question)}</div>
        <div className="twm-research-grid">
          <div>
            <span>核心技术</span>
            {(researchPositioning.core_technology || []).slice(0, 3).map(item => (
              <article key={item.name}>
                <strong>{displayText(item.name)}</strong>
                <p>{displayText(item.claim || item.why_it_matters)}</p>
              </article>
            ))}
          </div>
          <div>
            <span>待验证主张</span>
            {(researchPositioning.innovation_hypotheses || []).slice(0, 3).map(item => (
              <article key={item.hypothesis}>
                <strong>{displayText(item.hypothesis)}</strong>
                <p>{displayText(item.test)}</p>
              </article>
            ))}
            {!(researchPositioning.innovation_hypotheses || []).length && (
              <article>
                <strong>创新性必须经基线方法验证</strong>
                <p>{displayText(researchPositioning.claim_boundary)}</p>
              </article>
            )}
          </div>
          <div>
            <span>未满足需求假设</span>
            <ul>{(researchPositioning.unmet_need_hypotheses || []).slice(0, 4).map(item => <li key={item}>{displayText(item)}</li>)}</ul>
          </div>
          <div>
            <span>反证条件</span>
            <ul>{(researchPositioning.falsification_conditions || []).slice(0, 4).map(item => <li key={item}>{displayText(item)}</li>)}</ul>
          </div>
        </div>
      </details>

      <section className="twm-section twm-claim-matrix-panel">
        <div className="twm-section-head">
          <GitBranch size={14} />
          <h4>主张矩阵</h4>
          <span className={`status-badge ${statusClass(claimMatrix.status)}`}>
            {running === 'claimMatrix' ? '加载中' : statusText(claimMatrix.status, '需复核')}
          </span>
        </div>
        <div className="twm-claim-boundary">{displayText(claimMatrix.claim_boundary)}</div>
        <div className="twm-data-kpis">
          <div><span>真实历史</span><strong>{fmt(claimDataGate.production_ready_observed_history_rows, 0)}</strong></div>
          <div><span>动作标签</span><strong>{fmt(claimDataGate.production_policy_history_row_count, 0)}</strong></div>
          <div><span>生产声明</span><strong>{yesNo(claimDataGate.production_deployment_supported)}</strong></div>
          <div><span>预测/因果</span><strong>{yesNo(claimDataGate.predictive_or_causal_claim_supported)}</strong></div>
        </div>
        <div className="twm-claim-grid">
          {(claimMatrix.claims || []).slice(0, 4).map(item => (
            <article className="twm-claim-card" key={item.claim_id}>
              <div>
                <strong>{displayText(item.claim_id)}</strong>
                <span className={`status-badge ${statusClass(item.gate?.status)}`}>{statusText(item.gate?.claim_level || item.gate?.status, '需复核')}</span>
              </div>
              <p>{displayText(item.claim)}</p>
              <div className="twm-claim-tags">
                <code>{displayText(item.baseline)}</code>
                {(item.gate?.missing || []).slice(0, 3).map(missing => <code key={`${item.claim_id}-${missing}`}>{displayText(missing)}</code>)}
              </div>
              <span>{displayText(item.metrics?.[0]?.name || item.current_status)}</span>
            </article>
          ))}
        </div>
        <div className="twm-claim-experiments">
          {(claimMatrix.next_experiments || []).slice(0, 3).map(item => (
            <article key={item.experiment}>
              <strong>{item.priority ? `${item.priority} · ${displayText(item.experiment)}` : displayText(item.experiment)}</strong>
              <p>{displayText(item.question || item.decision)}</p>
            </article>
          ))}
        </div>
        <div className="twm-baseline-inputs">
          <label>
            <span>研究主张</span>
            <select value={selectedClaimId} onChange={e => applyClaimFixture(e.target.value)} disabled={busy}>
              {(claimMatrix.claims || []).map(item => (
                <option key={item.claim_id} value={item.claim_id}>{displayText(item.claim_id)}</option>
              ))}
            </select>
          </label>
          <label>
            <span>TWM 指标文件</span>
            <input value={twmMetricsPath} onChange={e => setTwmMetricsPath(e.target.value)} disabled={busy} />
          </label>
          <label>
            <span>基线指标文件</span>
            <input value={baselineMetricsPath} onChange={e => setBaselineMetricsPath(e.target.value)} disabled={busy} />
          </label>
          <label>
            <span>TWM 样本输出</span>
            <input value={twmCaseOutputPath} onChange={e => setTwmCaseOutputPath(e.target.value)} disabled={busy} />
          </label>
          <label>
            <span>基线样本输出</span>
            <input value={baselineCaseOutputPath} onChange={e => setBaselineCaseOutputPath(e.target.value)} disabled={busy} />
          </label>
        </div>
        <div className="twm-baseline-template-panel">
          <div className="twm-baseline-template-head">
            <div>
              <strong>脱敏导出模板</strong>
              <span>{displayText(selectedBaselineTemplate?.label || selectedClaimId, '无模板')}</span>
            </div>
            <span className={`status-badge ${selectedBaselineTemplate ? 'warning' : 'proposed'}`}>
              {running === 'baselineTemplates' ? '加载中' : selectedBaselineTemplate?.same_case_join_key ? `关联 ${selectedBaselineTemplate.same_case_join_key}` : '模板'}
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
                  <span>基线 CSV</span>
                  <code>{selectedBaselineTemplate.csv_header?.baseline || (selectedBaselineTemplate.headers?.baseline || []).join(',')}</code>
                </article>
                <article>
                  <span>必填字段</span>
                  <p>{compactList(selectedBaselineTemplate.required_columns)}</p>
                </article>
                <article>
                  <span>真实数据门槛</span>
                  <p>
                    {fmt(selectedBaselineTemplate.minimum_real_data_gate?.minimum_real_rows ?? selectedBaselineTemplate.production_collection?.minimum_real_rows, 0)} 行 · 重叠率 {fmt(selectedBaselineTemplate.minimum_real_data_gate?.minimum_overlap_ratio ?? 0.8, 2)}
                  </p>
                </article>
              </div>
              <div className="twm-baseline-template-metrics">
                {(selectedBaselineTemplate.metric_column_map || []).slice(0, 3).map(item => (
                  <article key={`${selectedBaselineTemplate.claim_id}-${item.metric}`}>
                    <strong>{displayText(item.metric)}</strong>
                    <p>{compactList(item.columns, '无字段')}</p>
                  </article>
                ))}
              </div>
              <details className="twm-baseline-template-details">
                <summary>字段与脱敏约束</summary>
                <div>
                  {(selectedBaselineTemplate.field_descriptions || []).slice(0, 5).map(field => (
                    <article key={`${selectedBaselineTemplate.claim_id}-${field.name}`}>
                      <span>{field.required ? '必填' : '可选'}</span>
                      <strong>{field.name}</strong>
                      <p>{displayText(field.metric_use || field.description)}</p>
                    </article>
                  ))}
                </div>
                <p>{(baselineTemplates?.global_sanitization_rules || []).slice(0, 2).join(' · ') || selectedBaselineTemplate.production_collection?.notes || '-'}</p>
              </details>
            </>
          ) : (
            <div className="twm-empty">当前研究主张尚未加载导出模板</div>
          )}
        </div>
        <div className="twm-baseline-imports">
          <label className="twm-file-upload">
            <span>导入 TWM CSV</span>
            <input
              type="file"
              accept=".csv,text/csv"
              disabled={busy}
              onChange={e => {
                importBaselineExportFile('twm', e.target.files?.[0]);
                e.currentTarget.value = '';
              }}
            />
            <strong><FileCheck2 size={13} />选择 CSV 文件</strong>
          </label>
          <label className="twm-file-upload">
            <span>导入基线 CSV</span>
            <input
              type="file"
              accept=".csv,text/csv"
              disabled={busy}
              onChange={e => {
                importBaselineExportFile('baseline', e.target.files?.[0]);
                e.currentTarget.value = '';
              }}
            />
            <strong><FileCheck2 size={13} />选择 CSV 文件</strong>
          </label>
          {baselineImport && (
            <div className="twm-baseline-import-summary">
              <span className={`status-badge ${statusClass(baselineImport.status)}`}>{statusText(baselineImport.source_role || baselineImport.status, '导入')}</span>
              <strong>{baselineImport.filename || baselineImport.path || '-'}</strong>
              <p>{fmt(baselineImport.row_count, 0)} 行 · {(baselineImport.columns || []).slice(0, 4).join(', ') || '无字段'}</p>
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
              <span className={`status-badge ${statusClass(baselinePipeline.status)}`}>{statusText(baselinePipeline.status, '需复核')}</span>
              <strong>{displayText(baselinePipeline.pipeline_decision)}</strong>
              <p>{displayText(baselinePipeline.claim_id)} 对比 {displayText(baselinePipeline.baseline_id)}</p>
            </div>
            <div className="twm-baseline-export-gates">
              <article>
                <span>导出校验</span>
                <p>{statusText(baselinePipeline.steps?.export_validation?.status)}</p>
              </article>
              <article>
                <span>基线对比</span>
                <p>{displayText(baselinePipeline.steps?.baseline_comparison?.status || baselinePipeline.steps?.baseline_comparison?.skipped_reason)}</p>
              </article>
              <article>
                <span>运行卡片</span>
                <p>
                  {[
                    baselinePipeline.steps?.export_validation?.scenario_card?.scenario_id ? '校验' : '',
                    baselinePipeline.steps?.baseline_comparison?.scenario_card?.scenario_id ? '对比' : '',
                  ].filter(Boolean).join(', ') || '无'}
                </p>
              </article>
            </div>
            <p>{compactDisplayList(baselinePipeline.next_actions, displayText(baselinePipeline.claim_boundary))}</p>
          </div>
        )}
        {baselineExportValidation && (
          <div className="twm-baseline-report twm-baseline-export-report">
            <div>
              <span className={`status-badge ${statusClass(baselineExportValidation.status)}`}>{statusText(baselineExportValidation.status, '需复核')}</span>
              <strong>{displayText(baselineExportValidation.export_spec?.label || baselineExportValidation.export_spec?.export_type, '基线导出')}</strong>
              <p>{displayText(baselineExportValidation.claim?.claim_id)} · 关联键 {baselineExportValidation.column_inventory?.join_key || '-'}</p>
            </div>
            <div className="twm-baseline-sources">
              <article>
                <span>重叠样本</span>
                <strong>{fmt(baselineExportValidation.coverage?.overlap_count, 0)}</strong>
                <p>覆盖率 {fmt(baselineExportValidation.coverage?.coverage_ratio, 3)}</p>
              </article>
              <article>
                <span>TWM 行数</span>
                <strong>{fmt(baselineExportValidation.column_inventory?.twm?.row_count, 0)}</strong>
                <p>{fmt(baselineExportValidation.column_inventory?.twm?.unique_join_id_count, 0)} 个唯一键</p>
              </article>
              <article>
                <span>基线行数</span>
                <strong>{fmt(baselineExportValidation.column_inventory?.baseline?.row_count, 0)}</strong>
                <p>{fmt(baselineExportValidation.column_inventory?.baseline?.unique_join_id_count, 0)} 个唯一键</p>
              </article>
              <article>
                <span>可比指标</span>
                <strong>{fmt(baselineExportValidation.parser_compatibility?.comparable_metrics?.length, 0)}</strong>
                <p>{compactDisplayList((baselineExportValidation.parser_compatibility?.comparable_metrics || []).slice(0, 2))}</p>
              </article>
            </div>
            <div className="twm-baseline-export-gates">
              <article>
                <span>阻断项</span>
                <p>{compactDisplayList((baselineExportValidation.blocking_errors || []).slice(0, 4))}</p>
              </article>
              <article>
                <span>缺失字段</span>
                <p>
                  {[...(baselineExportValidation.column_inventory?.missing_required?.twm || []), ...(baselineExportValidation.column_inventory?.missing_required?.baseline || [])]
                    .slice(0, 6)
                    .map(item => displayText(item))
                    .join(', ') || '无'}
                </p>
              </article>
              <article>
                <span>提醒</span>
                <p>{compactDisplayList((baselineExportValidation.warnings || []).slice(0, 4))}</p>
              </article>
            </div>
            <p>{compactDisplayList(baselineExportValidation.next_actions, displayText(baselineExportValidation.claim_boundary))}</p>
          </div>
        )}
        {baselineComparison && (
          <div className="twm-baseline-report">
            <div>
              <span className={`status-badge ${statusClass(baselineComparison.status)}`}>{statusText(baselineComparison.status, '需复核')}</span>
              <strong>{displayText(baselineComparison.upgrade_decision)}</strong>
              <p>{displayText(baselineComparison.claim?.claim_id)} 对比 {displayText(baselineComparison.baseline?.baseline_id)}</p>
            </div>
            <div className="twm-baseline-metrics">
              {(baselineComparison.metric_comparisons || []).slice(0, 4).map(metric => (
                <article key={metric.name}>
                  <span className={`status-badge ${statusClass(metric.status)}`}>{statusText(metric.status)}</span>
                  <strong>{displayText(metric.name)}</strong>
                  <p>TWM {fmt(metric.twm_value, 3)} · 基线 {fmt(metric.baseline_value, 3)} · 差值 {fmt(metric.delta, 3)}</p>
                </article>
              ))}
            </div>
            <div className="twm-baseline-sources">
              <article>
                <span>TWM 指标</span>
                <strong>{displayText(baselineComparison.inputs?.twm_metrics_source, '无')}</strong>
                <p>{fmt(baselineComparison.inputs?.twm_metric_count, 0)} 个指标</p>
              </article>
              <article>
                <span>基线指标</span>
                <strong>{displayText(baselineComparison.inputs?.baseline_metrics_source, '无')}</strong>
                <p>{fmt(baselineComparison.inputs?.baseline_metric_count, 0)} 个指标</p>
              </article>
              <article>
                <span>TWM 样本</span>
                <strong>{displayText(baselineComparison.inputs?.twm_case_source, '无')}</strong>
                <p>{fmt(baselineComparison.inputs?.twm_case_count, 0)} 行</p>
              </article>
              <article>
                <span>基线样本</span>
                <strong>{displayText(baselineComparison.inputs?.baseline_case_source, '无')}</strong>
                <p>{fmt(baselineComparison.inputs?.baseline_case_count, 0)} 行</p>
              </article>
            </div>
            {Object.entries(baselineComparison.inputs?.metric_source_errors || {}).some(([, value]) => Boolean(value)) && (
              <p>
                解析错误：{Object.entries(baselineComparison.inputs?.metric_source_errors || {})
                  .filter(([, value]) => Boolean(value))
                  .map(([key, value]) => `${displayText(key)}=${displayText(value)}`)
                  .join(', ')}
              </p>
            )}
            {baselineComparison.scenario_card?.scenario_id && (
              <p>运行卡片：{baselineComparison.scenario_card.scenario_id} · {statusText(baselineComparison.scenario_card.status, '需复核')}</p>
            )}
            <p>{compactDisplayList((baselineComparison.evidence_gate?.missing || []).slice(0, 4), '无证据门槛缺口')}</p>
          </div>
        )}
        <div className="twm-baseline-cards">
          <div className="twm-baseline-cards-head">
            <div>
              <strong>已保存运行卡片</strong>
              <span>{running === 'baselineCards' ? '加载中' : `${filteredBaselineCards.length}/${baselineCards.length}`}</span>
            </div>
            <select value={baselineCardFilter} onChange={e => setBaselineCardFilter(e.target.value)} disabled={busy || !baselineCards.length}>
              <option value="all">全部主张</option>
              {(claimMatrix.claims || []).map(item => (
                <option key={`card-filter-${item.claim_id}`} value={item.claim_id}>{displayText(item.claim_id)}</option>
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
                    <span className={`status-badge ${statusClass(card.status || meta.upgrade_decision)}`}>{displayText(card.status || meta.upgrade_decision, '需复核')}</span>
                    <strong>{displayText(claimId)}</strong>
                    <button
                      type="button"
                      className="twm-card-detail-toggle"
                      onClick={() => setExpandedBaselineCardId(expanded ? '' : card.id)}
                    >
                      {expanded ? '收起' : '详情'}
                    </button>
                  </div>
                  <p>{displayText(baselineId)}</p>
                  <div className="twm-baseline-card-kpis">
                    <span>TWM {fmt(sources.twm_case_count ?? validationSources.twm?.row_count, 0)}</span>
                    <span>基线 {fmt(sources.baseline_case_count ?? validationSources.baseline?.row_count, 0)}</span>
                    <span>{isExportValidation ? `重叠 ${fmt(meta.coverage?.overlap_count, 0)}` : errors.length ? `${errors.length} 个解析错误` : '解析正常'}</span>
                  </div>
                  <p>{isExportValidation ? `关联 ${meta.column_inventory?.join_key || '-'} · ${fmt(meta.coverage?.coverage_ratio, 3)}` : compactDisplayList((meta.evidence_gate?.missing || []).slice(0, 3), '无证据门槛缺口')}</p>
                  {expanded && (
                    <div className="twm-baseline-card-detail">
                      {isExportValidation ? (
                        <>
                          <div>
                            <span>覆盖</span>
                            <strong>{fmt(meta.coverage?.overlap_count, 0)} · {fmt(meta.coverage?.coverage_ratio, 3)}</strong>
                          </div>
                          <div>
                            <span>缺失字段</span>
                            <p>{compactDisplayList([...(meta.column_inventory?.missing_required?.twm || []), ...(meta.column_inventory?.missing_required?.baseline || []), ...(meta.column_inventory?.missing_required?.claim_parser || [])])}</p>
                          </div>
                          <div>
                            <span>可比指标</span>
                            <p>{compactDisplayList(meta.parser_compatibility?.comparable_metrics)}</p>
                          </div>
                          <div>
                            <span>阻断/提醒</span>
                            <p>{compactDisplayList([...(meta.blocking_errors || []), ...(meta.warnings || [])])}</p>
                          </div>
                        </>
                      ) : (
                        <>
                          {(meta.metric_comparisons || []).slice(0, 3).map(metric => (
                            <div key={`${card.id}-${metric.name}`}>
                              <span>{displayText(metric.name)}</span>
                              <strong>{statusText(metric.status)}</strong>
                              <p>TWM {fmt(metric.twm_value, 3)} · 基线 {fmt(metric.baseline_value, 3)} · 差值 {fmt(metric.delta, 3)}</p>
                            </div>
                          ))}
                          <div>
                            <span>证据门槛</span>
                            <p>{compactDisplayList(meta.evidence_gate?.missing, '无证据门槛缺口')}</p>
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
            {!filteredBaselineCards.length && (
              <div className="twm-empty">{selectedProjectId ? '暂无已保存运行卡片' : '请选择项目后加载运行卡片'}</div>
            )}
          </div>
        </div>
      </section>

      <section className="twm-section twm-data-foundation-panel">
        <div className="twm-section-head">
          <FileCheck2 size={14} />
          <h4>数据基础</h4>
          <span className={`status-badge ${statusClass(dataReadiness.status || dataFoundation.status)}`}>
            {running === 'dataFoundation' ? '加载中' : statusText(dataReadiness.status || dataFoundation.status, '需复核')}
          </span>
        </div>
        <div className="twm-data-verdict">{displayText(dataReadiness.verdict)}</div>
        <div className="twm-data-kpis">
          <div><span>生产观察历史</span><strong>{fmt(validationSnapshot.production_ready_observed_history_rows, 0)}</strong></div>
          <div><span>政策动作历史</span><strong>{fmt(validationSnapshot.production_policy_history_row_count, 0)}</strong></div>
          <div><span>结构样例</span><strong>{fmt(validationSnapshot.structural_fixture?.row_count, 0)}</strong></div>
          <div><span>合成实验</span><strong>{fmt(validationSnapshot.synthetic_experiment?.row_count, 0)}</strong></div>
        </div>
        <div className="twm-data-layout">
          <div className="twm-data-card">
            <span>测试数据包</span>
            {(dataFoundation.datasets || []).map(dataset => (
              <article key={dataset.id}>
                <strong>{displayText(dataset.label)}</strong>
                <p>{displayText(dataset.positioning || dataset.nature)}</p>
                <div>
                  <code>{dataset.not_for_production ? '演示/回归数据' : '生产候选数据'}</code>
                  {(dataset.files || []).map(file => (
                    <code key={`${dataset.id}-${file.path}`}>{file.path}: {fmt(file.count, 0)}</code>
                  ))}
                </div>
              </article>
            ))}
          </div>
          <div className="twm-data-card">
            <span>能支撑的问题</span>
            {(dataFoundation.supported_problems || []).map(item => (
              <article key={item.problem}>
                <strong>{displayText(item.problem)}</strong>
                <p>{displayText(item.support)}</p>
              </article>
            ))}
          </div>
          <div className="twm-data-card">
            <span>不能支撑的落地声明</span>
            {(dataFoundation.unsupported_claims || []).map(item => (
              <article key={item.claim}>
                <strong>{displayText(item.claim)}</strong>
                <p>{displayText(item.reason)}</p>
              </article>
            ))}
          </div>
          <div className="twm-data-card">
            <span>下一步真实数据</span>
            {(dataFoundation.required_next_data || []).map(item => (
              <article key={item.data}>
                <strong>{item.priority ? `${item.priority} · ${displayText(item.data)}` : displayText(item.data)}</strong>
                <p>{displayText(item.unlocks || item.minimum)}</p>
              </article>
            ))}
          </div>
        </div>
        <div className="twm-data-detail-section">
          <div className="twm-data-detail-head">
            <strong>关键阻断项</strong>
            <span>为什么当前只能演示原型，不能声明生产结论</span>
          </div>
          <div className="twm-data-blocker-list">
            {(dataReadiness.key_blockers || []).map(item => (
              <article key={item}>
                <AlertTriangle size={12} />
                <span>{displayText(item)}</span>
              </article>
            ))}
            {!(dataReadiness.key_blockers || []).length && <div className="twm-empty">暂无阻断项</div>}
          </div>
        </div>
        <div className="twm-data-detail-section">
          <div className="twm-data-detail-head">
            <strong>完整数据清单</strong>
            <span>{fmt((dataFoundation.datasets || []).length, 0)} 个数据包，逐项展示文件和计数</span>
          </div>
          <div className="twm-data-dataset-list">
            {(dataFoundation.datasets || []).map(dataset => (
              <article key={`detail-${dataset.id}`} className="twm-data-dataset-detail">
                <div className="twm-data-dataset-head">
                  <div>
                    <strong>{displayText(dataset.label)}</strong>
                    <code>{dataset.id}</code>
                  </div>
                  <span className={`status-badge ${dataset.not_for_production ? 'warning' : 'success'}`}>
                    {dataset.not_for_production ? '演示/非生产' : '生产候选'}
                  </span>
                </div>
                <p>{displayText(dataset.positioning || dataset.nature || dataset.path)}</p>
                <div className="twm-data-dataset-kpis">
                  <span>总量 {fmt(dataset.total_count, 0)}</span>
                  <span>合成 {fmt(dataset.synthetic_count, 0)}</span>
                  <span>非生产 {fmt(dataset.not_for_production_count, 0)}</span>
                  {dataset.path && <span>{dataset.path}</span>}
                </div>
                <div className="twm-data-file-grid">
                  {(dataset.files || []).map(file => (
                    <div key={`${dataset.id}-detail-${file.path}`}>
                      <code>{file.path}</code>
                      <span>
                        {fmt(file.count, 0)} {file.unit || '条'} · 合成 {fmt(file.synthetic_count, 0)} · 非生产 {fmt(file.not_for_production_count, 0)}
                      </span>
                    </div>
                  ))}
                  {!(dataset.files || []).length && <div className="twm-empty">暂无文件明细</div>}
                </div>
              </article>
            ))}
          </div>
        </div>
        <div className="twm-data-detail-section">
          <div className="twm-data-detail-head">
            <strong>完整验证快照</strong>
            <span>把生产历史、结构样例、合成实验和外部支持分开说明</span>
          </div>
          <div className="twm-data-evidence-grid">
            <article>
              <span>生产观察历史</span>
              <strong>{fmt(validationSnapshot.production_ready_observed_history_rows, 0)}</strong>
              <p>{statusText(validationSnapshot.production_policy_history_status, '未提供')} · 政策动作 {fmt(validationSnapshot.production_policy_history_row_count, 0)}</p>
            </article>
            <article>
              <span>政策动作掩码</span>
              <strong>{fmt(validationSnapshot.production_policy_allowed_count, 0)} / {fmt(validationSnapshot.production_policy_blocked_count, 0)}</strong>
              <p>允许 / 阻断</p>
            </article>
            <article>
              <span>结构样例</span>
              <strong>{fmt(validationSnapshot.structural_fixture?.row_count, 0)}</strong>
              <p>{fmt(validationSnapshot.structural_fixture?.pair_count, 0)} 对 · {statusText(validationSnapshot.structural_fixture?.structural_status)}</p>
            </article>
            <article>
              <span>合成实验</span>
              <strong>{fmt(validationSnapshot.synthetic_experiment?.row_count, 0)}</strong>
              <p>{fmt(validationSnapshot.synthetic_experiment?.region_count, 0)} 区域 · {fmt(validationSnapshot.synthetic_experiment?.period_count, 0)} 期</p>
            </article>
            <article>
              <span>本地观察历史</span>
              <strong>{statusText(validationSnapshot.local_observed_history?.status, '未提供')}</strong>
              <p>{compactDisplayList(validationSnapshot.local_observed_history?.missing, '无缺失项')} · 邻接边 {fmt(validationSnapshot.local_observed_history?.relation_neighbor_edge_count, 0)}</p>
            </article>
            <article>
              <span>项目审查上下文</span>
              <strong>{fmt(validationSnapshot.project_review_context?.project_count, 0)} 项目</strong>
              <p>规则 {fmt(validationSnapshot.project_review_context?.rule_eval_count, 0)} · 复核任务 {fmt(validationSnapshot.project_review_context?.review_task_count, 0)}</p>
            </article>
            <article>
              <span>外部支持</span>
              <strong>{statusText(validationSnapshot.external_support?.paper7_caliper_matched_status, '参考')}</strong>
              <p>{fmt(validationSnapshot.external_support?.paper7_caliper_matched_pair_count, 0)} 对 · {displayText(validationSnapshot.external_support?.boundary)}</p>
            </article>
            <article>
              <span>合成实验划分</span>
              <strong>{Object.entries(validationSnapshot.synthetic_experiment?.split_counts || {}).map(([key, value]) => `${displayText(key)} ${fmt(value, 0)}`).join(' · ') || '无'}</strong>
              <p>动作允许 {fmt(validationSnapshot.synthetic_experiment?.action_mask_allowed_count, 0)} · 阻断 {fmt(validationSnapshot.synthetic_experiment?.action_mask_blocked_count, 0)}</p>
            </article>
          </div>
        </div>
        <div className="twm-data-detail-section">
          <div className="twm-data-detail-head">
            <strong>问题-数据适配</strong>
            <span>哪些问题可以安全演示，哪些输出不能越界</span>
          </div>
          <div className="twm-data-fit-list">
            {(dataFoundation.problem_data_fit || []).map(item => (
              <article key={item.business_problem}>
                <div>
                  <strong>{displayText(item.business_problem)}</strong>
                  <span className="status-badge proposed">{displayText(item.current_fit, '待评估')}</span>
                </div>
                <p>{displayText(item.why)}</p>
                <div>
                  <span>安全输出：{displayText(item.safe_output)}</span>
                  <span>不能承诺：{displayText(item.unsafe_output)}</span>
                </div>
              </article>
            ))}
          </div>
        </div>
        <div className="twm-data-detail-section">
          <div className="twm-data-detail-head">
            <strong>来源报告</strong>
            <span>演示数据基础的可追溯文件</span>
          </div>
          <div className="twm-data-source-list">
            {Object.entries(dataFoundation.source_reports || {}).map(([key, value]) => (
              <article key={key}>
                <span>{displayText(key)}</span>
                <code>{value}</code>
              </article>
            ))}
            {!Object.keys(dataFoundation.source_reports || {}).length && <div className="twm-empty">暂无来源报告</div>}
          </div>
        </div>
        {(dataFoundation.mentor_answer?.short_answer || dataFoundation.mentor_answer?.research_judgment) && (
          <div className="twm-data-mentor-note">
            <strong>数据基础判断</strong>
            <p>{displayText(dataFoundation.mentor_answer?.short_answer)}</p>
            <p>{displayText(dataFoundation.mentor_answer?.research_judgment)}</p>
          </div>
        )}
      </section>
        </div>
      )}

      {activeSubTab === 'operate' && (
        <div
          className="twm-subtab-panel"
          role="tabpanel"
          id="twm-subtab-operate"
          aria-labelledby="twm-subtab-control-operate"
        >
      <div className="twm-main-grid">
        <section className="twm-section">
          <div className="twm-section-head">
            <Layers3 size={14} />
            <h4>工作空间</h4>
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
              <span>{displayText(selectedProject.business_scenario)}</span>
              <span>{statusText(selectedProject.status)}</span>
            </div>
          )}

          <label className="twm-field">
            <span>MMFE / TWM 数据包</span>
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
                  {state.label || state.id} · {fmt(state.object_count, 0)} 个对象
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
              <span>状态</span>
              <strong>{selectedState?.label || selectedStateId || '-'}</strong>
            </div>
            <div>
              <span>对象</span>
              <strong>{fmt(selectedState?.object_count ?? stateDetail?.state_version?.object_count, 0)}</strong>
            </div>
            <div>
              <span>关系</span>
              <strong>{fmt(selectedState?.relation_count ?? stateDetail?.state_version?.relation_count, 0)}</strong>
            </div>
          </div>

          <button type="button" className="twm-secondary-action" onClick={evaluateRules} disabled={busy || !selectedStateId}>
            {running === 'evaluate' ? <Loader2 size={13} className="twm-spin" /> : <ShieldCheck size={13} />}
            检查业务规则
          </button>

          <div className="twm-result-strip">
            <div><span>命中</span><strong>{fmt(summary.hit_count ?? hits.length, 0)}</strong></div>
            <div><span>证据</span><strong>{fmt(summary.evidence_item_count ?? auditResult?.evidence_gate_summary?.evidence_item_count, 0)}</strong></div>
            <div><span>数据风险</span><strong>{fmt(summary.data_quality_hit_count, 0)}</strong></div>
            <div><span>审批风险</span><strong>{fmt(summary.approval_consistency_hit_count, 0)}</strong></div>
          </div>

          <div className="twm-form-grid">
            <label>
              <span>动作</span>
              <select value={actionType} onChange={e => setActionType(e.target.value)} disabled={busy}>
                <option value="inspect">{ACTION_LABELS.inspect}</option>
                <option value="protect">{ACTION_LABELS.protect}</option>
                <option value="allocate">{ACTION_LABELS.allocate}</option>
                <option value="convert">{ACTION_LABELS.convert}</option>
                <option value="restore">{ACTION_LABELS.restore}</option>
              </select>
            </label>
            <label>
              <span>目标角色</span>
              <select value={targetRole} onChange={e => setTargetRole(e.target.value)} disabled={busy}>
                <option value="project">{ROLE_LABELS.project}</option>
                <option value="parcel">{ROLE_LABELS.parcel}</option>
                <option value="scenario">{ROLE_LABELS.scenario}</option>
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
            <span>优化数据包</span>
            <input value={optimizationDir} onChange={e => setOptimizationDir(e.target.value)} disabled={busy} />
          </label>
          <div className="twm-action-grid">
            <button type="button" className="twm-secondary-action" onClick={loadCandidates} disabled={busy || !selectedStateId || !optimizationDir.trim()}>
              {running === 'candidates' ? <Loader2 size={13} className="twm-spin" /> : <BarChart3 size={13} />}
              载入候选
            </button>
            <button type="button" className="twm-primary-action" onClick={runBeam} disabled={busy || !selectedStateId || !optimizationDir.trim()}>
              {running === 'beam' ? <Loader2 size={13} className="twm-spin" /> : <Route size={13} />}
              方案比选
            </button>
          </div>
        </section>
      </div>

      <div className="twm-main-grid twm-results-grid">
        <section className="twm-section">
          <div className="twm-section-head">
            <AlertTriangle size={14} />
            <h4>规则命中</h4>
            <span className={`status-badge ${hits.length ? 'warning' : 'success'}`}>{hits.length ? `${hits.length} 条待处理` : '无'}</span>
          </div>
          <div className="twm-hit-list">
            {topHits(hits).map(hit => (
              <div className="twm-hit-row" key={hit.id}>
                <span className={`status-badge ${statusClass(hit.severity)}`}>{statusText(hit.severity)}</span>
                <div>
                  <strong>{hit.rule_id || hit.id}</strong>
                  <span>{hit.explanation || hit.subject_object_id || '-'}</span>
                </div>
                <code>{fmt(hit.risk_score, 3)}</code>
              </div>
            ))}
            {!hits.length && <div className="twm-empty">尚未加载规则命中</div>}
          </div>
        </section>

        <section className="twm-section">
          <div className="twm-section-head">
            <CheckCircle2 size={14} />
            <h4>主张与方案</h4>
            <span className={`status-badge ${statusClass(validationResult?.overall_status || beamResult?.status)}`}>
              {statusText(validationResult?.overall_status || beamResult?.status, '未运行')}
            </span>
          </div>

          <div className="twm-result-strip">
            <div><span>主张等级</span><strong>{statusText(claim.current_level)}</strong></div>
            <div><span>规划收益</span><strong>{fmt(forecast.planning_utility_delta ?? beamSelected.utility, 3)}</strong></div>
            <div><span>约束风险</span><strong>{fmt(forecast.constraint_violation_probability ?? beamSelected.risk, 3)}</strong></div>
            <div><span>可信度</span><strong>{fmt(forecast.uncertainty?.confidence ?? beamSelected.confidence, 3)}</strong></div>
          </div>

          {validationResult?.stages && (
            <div className="twm-stage-list">
              {validationResult.stages.map((stage: any) => (
                <div className="twm-stage-row" key={stage.stage_code}>
                  <span className={`status-badge ${statusClass(stage.status)}`}>{statusText(stage.status)}</span>
                  <strong>{stage.stage_code}</strong>
                  <span>{stage.gaps?.[0] || stage.summary || '-'}</span>
                </div>
              ))}
            </div>
          )}

          <div className="twm-result-strip">
            <div><span>候选方案</span><strong>{fmt(candidateSummary.candidate_count, 0)}</strong></div>
            <div><span>合法可行</span><strong>{fmt(candidateSummary.legal_feasible_count, 0)}</strong></div>
            <div><span>阻断方案</span><strong>{fmt(candidateSummary.blocked_count, 0)}</strong></div>
            <div><span>推荐方案</span><strong>{beamSelected.candidate_id || '-'}</strong></div>
          </div>
        </section>
      </div>
        </div>
      )}

      {activeSubTab === 'payload' && (
        <div
          className="twm-subtab-panel"
          role="tabpanel"
          id="twm-subtab-payload"
          aria-labelledby="twm-subtab-control-payload"
        >
      <details className="twm-json-panel">
        <summary>最新技术载荷</summary>
        <pre>{JSON.stringify(latestResult || status || {}, null, 2)}</pre>
      </details>
        </div>
      )}
    </div>
  );
}
