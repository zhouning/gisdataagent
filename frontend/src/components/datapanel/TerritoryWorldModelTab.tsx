import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
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
import TwmExecutiveDemoPanel from './TwmExecutiveDemoPanel';
import i18n, { formatNumber, getLocale, getLocaleHeaders } from '../../i18n';

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
  | 'roadmapStatus'
  | 'pilotReadiness'
  | 'ruleFixtureCoverage'
  | 'layerDetail'
  | 'lineage'
  | 'crsRemediation'
  | 'authoritativeTemplates'
  | 'baselineCards'
  | 'projects'
  | 'create'
  | 'states'
  | 'stateGraph'
  | 'build'
  | 'evaluate'
  | 'forecast'
  | 'validation'
  | 'audit'
  | 'candidates'
  | 'beam';

type TwmMapStage = 'locate' | 'risk' | 'plan';
type TwmSubTab = 'briefing' | 'overview' | 'data' | 'operate' | 'graph' | 'payload';

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

interface TwmStateGraphNode {
  id: string;
  kind?: string;
  role?: string;
  label?: string;
  severity?: string;
  status?: string;
  bbox?: number[] | null;
  map_stage?: TwmMapStage | 'none';
  summary?: Record<string, any> | string;
  [key: string]: any;
}

interface TwmStateGraphEdge {
  id: string;
  source: string;
  target: string;
  kind?: string;
  label?: string;
  [key: string]: any;
}

interface TwmStateGraphReport {
  schema?: string;
  state_version_id?: string;
  graph_store?: {
    backend?: string;
    full_graph_persisted?: boolean;
    production_policy?: string;
  };
  full_graph_counts?: {
    state_object_count?: number;
    state_relation_count?: number;
    rule_hit_count?: number;
    support_material_count?: number;
    review_task_count?: number;
    total_node_count?: number;
    total_edge_count?: number;
  };
  object_counts_by_role?: Record<string, number>;
  relation_counts_by_type?: Record<string, number>;
  support_material_counts_by_type?: Record<string, number>;
  visual_graph?: {
    nodes?: TwmStateGraphNode[];
    edges?: TwmStateGraphEdge[];
    render_policy?: {
      rendered_node_count?: number;
      rendered_edge_count?: number;
      full_graph_node_count?: number;
      full_graph_edge_count?: number;
      visual_subset_only?: boolean;
      full_graph_counts_available?: boolean;
      focus_node_id?: string;
    };
  };
  full_graph?: {
    included?: boolean;
    nodes?: TwmStateGraphNode[];
    edges?: TwmStateGraphEdge[];
  };
  terminology?: Record<string, string>;
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

interface TwmDataFoundationLayerDetail {
  schema?: string;
  dataset_id?: string;
  dataset_label?: string;
  layer_path?: string;
  label?: string;
  unit?: string;
  not_for_production?: boolean;
  feature_count?: number;
  bbox?: number[] | null;
  crs_diagnostic?: TwmDataFoundationCrsDiagnostic;
  property_field_count?: number;
  property_fields?: TwmDataFoundationPropertyField[];
  sample_record_count?: number;
  sample_records?: Array<{ feature_index?: number; properties?: Record<string, any> }>;
  delivery_mode?: string;
  claim_boundary?: string;
}

interface TwmDataFoundationLineageReport {
  schema?: string;
  dataset_id?: string;
  dataset_label?: string;
  dataset_root?: string;
  source_nature?: string;
  positioning?: string;
  not_for_production?: boolean;
  file_count?: number;
  spatial_layer_count?: number;
  table_count?: number;
  total_record_count?: number;
  synthetic_record_count?: number;
  not_for_production_record_count?: number;
  lineage_coverage?: {
    status?: string;
    file_count?: number;
    existing_file_count?: number;
    missing_file_count?: number;
    authoritative_source_count?: number;
    review_only_source_count?: number;
  };
  map_overlay_readiness?: TwmDataFoundationMapPreview['map_overlay_readiness'];
  readiness_gates?: Array<{ id: string; status?: string; current_value?: any; required_value?: any }>;
  files?: Array<{
    path: string;
    unit?: string;
    source_role?: string;
    exists?: boolean;
    count?: number;
    synthetic_count?: number;
    not_for_production_count?: number;
    lineage_status?: string;
    source_nature?: string;
    crs_diagnostic?: TwmDataFoundationCrsDiagnostic;
    property_field_count?: number;
  }>;
  required_next_data?: Array<{ priority?: string; data: string; minimum?: string; unlocks?: string }>;
  claim_boundary?: string;
}

interface TwmDataFoundationCrsRemediationPlan {
  schema?: string;
  dataset_id?: string;
  dataset_label?: string;
  dataset_root?: string;
  source_nature?: string;
  positioning?: string;
  target_crs?: string;
  status?: string;
  layer_count?: number;
  ready_layer_count?: number;
  blocked_layer_count?: number;
  map_overlay_readiness?: TwmDataFoundationMapPreview['map_overlay_readiness'];
  layers?: Array<{
    path: string;
    label?: string;
    status?: string;
    feature_count?: number;
    bbox?: number[] | null;
    source_crs_assumption?: string;
    target_crs?: string;
    crs_diagnostic?: TwmDataFoundationCrsDiagnostic;
    suggested_action?: string;
    conversion_steps?: Array<{ action: string; status?: string; target_crs?: string; method?: string; acceptance?: string; output_suffix?: string }>;
    output_policy?: { write_new_file?: boolean; suffix?: string; target_crs?: string; overwrite_source?: boolean; lineage_fields?: string[] };
    not_for_production?: boolean;
  }>;
  execution_policy?: Record<string, any>;
  acceptance_criteria?: string[];
  claim_boundary?: string;
}

interface TwmDataFoundationAuthoritativeTemplates {
  schema?: string;
  generated_at?: string;
  status?: string;
  production_deployment_supported?: boolean;
  template_count?: number;
  templates?: Array<{
    template_id: string;
    label?: string;
    role?: string;
    unit?: string;
    accepted_formats?: string[];
    required_fields?: string[];
    recommended_fields?: string[];
    minimum_quality_gates?: string[];
    production_use?: string;
  }>;
  shared_lineage_fields?: string[];
  readiness_gates?: Array<{ id: string; status?: string; current_value?: any; required_value?: any }>;
  onboarding_steps?: string[];
  claim_boundary_notes?: string[];
  claim_boundary?: string;
}

interface TwmRoadmapStatusReport {
  schema?: string;
  generated_at?: string;
  overall_status?: string;
  claim_boundary?: string;
  data_gate?: {
    status?: string;
    production_ready_observed_history_rows?: number;
    production_policy_history_row_count?: number;
    predictive_or_causal_claim_supported?: boolean;
  };
  phases?: Array<{
    id: string;
    label?: string;
    status?: string;
    completion_ratio?: number;
    evidence?: string[];
    remaining?: string[];
  }>;
  blockers?: Array<{
    id: string;
    priority?: string;
    status?: string;
    current_value?: any;
    required_value?: any;
  }>;
  next_actions?: Array<{
    priority?: string;
    action: string;
    roadmap_phase?: string;
  }>;
}

interface TwmPilotReadinessMatrix {
  schema?: string;
  generated_at?: string;
  overall_status?: string;
  dimensions?: Array<{
    id: string;
    label?: string;
    status?: string;
    score?: number;
    evidence?: string[];
    missing?: string[];
    test_data_work?: string[];
  }>;
  claim_boundary?: Record<string, string>;
  strict_policy?: Record<string, boolean>;
  test_data_plan?: { status?: string; items?: Array<{ priority?: string; dimension?: string; action?: string; why?: string }> };
}

interface TwmRuleFixtureCoverageMatrix {
  schema?: string;
  generated_at?: string;
  overall_status?: string;
  summary?: {
    hard_rule_count?: number;
    rules_with_boundary_gap?: number;
    production_ready_fixture_count?: number;
    rule_eval_row_count?: number;
    scenario_constraint_row_count?: number;
  };
  coverage_policy?: Record<string, any>;
  rules?: Array<{
    rule_code: string;
    rule_name_zh?: string;
    status?: string;
    missing_categories?: string[];
    production_ready_fixture_count?: number;
    categories?: Record<string, { covered?: boolean; fixture_count?: number }>;
    test_data_work?: string[];
  }>;
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
    minimum_data?: string[];
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
  baselines?: Array<{
    baseline_id: string;
    label: string;
    tests?: string;
    minimum_output?: string[];
    why_needed?: string;
  }>;
  next_experiments?: Array<{
    priority?: string;
    experiment: string;
    question?: string;
    required_data?: string[];
    decision?: string;
  }>;
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
  export_spec?: { export_type?: string; baseline_id?: string; label?: string; expected_source?: string };
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
  export_spec?: { export_type?: string; baseline_id?: string; label?: string; expected_source?: string };
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
    label: 'Farmland protection and balance review',
    decision_question: 'Does the proposal conflict with farmland protection constraints?',
    operator_goal: 'Surface compliance risks, evidence gaps, and spatial alternatives before review.',
    primary_roles: ['project', 'parcel', 'permanent_basic_farmland', 'eco_redline', 'planning_zone'],
    required_evidence: ['Project boundary', 'Current land parcels', 'Permanent basic farmland', 'Ecological redline', 'Approval records'],
    default_action_type: 'protect',
    default_target_role: 'project',
    default_scenario: 'farmland_protection_review',
    default_evidence_coverage: 0.78,
    default_horizon: 3,
    decision_outputs: ['Prioritized risk hits', 'Evidence review package', 'Legally feasible alternatives'],
    guardrails: ['A hard-constraint hit cannot receive an automatic approval recommendation', 'Synthetic data is limited to demos and regression evidence'],
  },
  {
    id: 'construction_project_compliance',
    label: 'Construction project compliance screening',
    decision_question: 'Is the project consistent with planning, approval, and control boundaries?',
    operator_goal: 'Surface land conflicts, correction items, and approval consistency risks before implementation.',
    primary_roles: ['project', 'parcel', 'planning_zone', 'urban_boundary', 'review_task'],
    required_evidence: ['Project boundary', 'Land-use control zones', 'Urban development boundary', 'Review opinions', 'Approval history'],
    default_action_type: 'inspect',
    default_target_role: 'project',
    default_scenario: 'construction_project_compliance',
    default_evidence_coverage: 0.72,
    default_horizon: 2,
    decision_outputs: ['Approval consistency risks', 'Correction evidence checklist', 'Human review tasks'],
    guardrails: ['Missing approval records allow review recommendations only', 'Construction outside the boundary always requires human review'],
  },
  {
    id: 'territorial_plan_adjustment',
    label: 'Territorial land-use adjustment simulation',
    decision_question: 'How do adjustment options affect constraints, planning utility, and oversight pressure?',
    operator_goal: 'Compare benefits, constraint risks, and explainable evidence instead of returning only an optimum.',
    primary_roles: ['scenario', 'parcel', 'planning_zone', 'project', 'control_boundary'],
    required_evidence: ['Current spatial pattern', 'Planning zones', 'Hard-constraint boundaries', 'Candidate adjustments', 'Historical oversight samples'],
    default_action_type: 'convert',
    default_target_role: 'scenario',
    default_scenario: 'territorial_plan_adjustment',
    default_evidence_coverage: 0.68,
    default_horizon: 5,
    decision_outputs: ['Option utility and risk ranking', 'Counterfactual simulation summary', 'Reasons for excluding options'],
    guardrails: ['Options that violate hard constraints cannot be recommended', 'Forecasts must include evidence completeness and uncertainty'],
  },
];

const FALLBACK_RESEARCH_POSITIONING: TwmResearchPositioning = {
  research_question: 'Can a governance-oriented geospatial world model improve territorial planning decisions by coupling hierarchical GIS state, policy constraints, evidence provenance and action-conditioned forecast in one auditable loop?',
  core_technology: [
    {
      name: 'Hierarchical GIS object-relation-rule-evidence state',
      claim: 'TWM represents parcels, projects, control boundaries, planning zones, approvals, evidence and rules as a linked state rather than as a flat feature table.',
    },
    {
      name: 'Action-conditioned multi-head territorial dynamics',
      claim: 'TWM forecasts a multi-dimensional hierarchical future-state latent, constraint-risk, planning utility, uncertainty and action-mask feasibility conditional on review/protect/convert/restore actions; the latent is decoded into state summaries and does not generate full parcel geometry.',
    },
    {
      name: 'Evidence-gated and causally calibrated claim ladder',
      claim: 'TWM separates deterministic rule evidence, observational causal calibration and validation gates before upgrading any operational claim.',
    },
  ],
  innovation_hypotheses: [
    {
      hypothesis: 'The novelty is architectural integration, not that GIS simulation itself is new.',
      test: 'Compare against land-use simulators, GIS rule engines and optimization tools on whether they jointly expose action-conditioned forecast, policy evidence and audit-ready claim boundaries.',
    },
    {
      hypothesis: 'Object-relation-rule-evidence state reduces missed compliance conflicts compared with layer-by-layer manual review.',
      test: 'Measure hard-constraint conflict recall and false review burden on held-out real approval/review cases.',
    },
    {
      hypothesis: 'Evidence-gated forecasts improve decision defensibility compared with black-box planning scores.',
      test: 'Audit whether every recommended or rejected option carries source evidence, rule clause, uncertainty and human-review reason.',
    },
  ],
  unmet_need_hypotheses: [
    'Planning and land-use review workflows still fragment spatial overlays, policy checks, approval evidence and scenario comparison across separate tools.',
    'Existing land-use simulators emphasize spatial pattern transition, while operational review needs action consequences, rule validity and audit boundaries.',
    'Optimization tools can rank candidates, but often do not preserve why a candidate is illegal, under-evidenced or only reviewable rather than approvable.',
  ],
  falsification_conditions: [
    'If real workflow interviews show the target decisions are already well solved by existing tools, TWM should be narrowed or stopped.',
    'If TWM does not improve hard-constraint conflict recall, evidence completeness or audit-trail quality over baselines, the claimed contribution is not supported.',
    'If action-conditioned dynamics cannot be validated beyond synthetic fixtures, TWM must remain a review scaffold rather than a production decision model.',
  ],
  claim_boundary: 'Current TWM is a rigorous prototype and review scaffold. Its defensible near-term claim is auditable decision support for territorial governance workflows; production-grade predictive claims require real observed histories, baseline comparisons and external validation.',
};

const FALLBACK_DATA_FOUNDATION: TwmDataFoundationAssessment = {
  status: 'review',
  landing_readiness: {
    status: 'review',
    verdict: '当前数据基础足以支撑 TWM 工程原型、规则/依据/审计链路和合成实验验证；不足以支撑生产级审批结论、真实预测效果或真实因果改进声明。',
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
    { problem: '工程 MVP 与回归测试', support: '验证状态构建、角色绑定、规则评价、依据链、审计报告和 TWM 前端工作流。' },
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
      why: '图斑、永久基本农田、生态红线、项目、规则命中和依据链结构齐备，但关键边界和审批记录仍非生产数据。',
      safe_output: '风险暴露、依据缺口、人工复核任务和候选方案审计。',
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
  claim_boundary: '每一项 TWM 研究主张都必须说明未满足业务需求、可对比的简单基线、最低真实数据依据、评价指标和可证伪条件，之后才可能从原型状态升级。',
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
      current_evidence: 'Synthetic fixtures verify pipeline behavior, but real conflict recall remains unvalidated.',
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
      claim: 'Action-conditioned dynamics improves plan-option triage compared with land-use simulators or optimization-only candidate ranking.',
      baseline: 'land_use_simulator_or_optimization_only_ranking',
      current_status: 'experimental_synthetic_only',
      gate: { status: 'review', claim_level: 'prototype_scaffold', missing: ['production_observed_history', 'production_policy_action_labels'] },
      metrics: [{ name: 'legal_feasible_topk_precision', minimum_pass: 0.8 }],
    },
  ],
  baselines: [
    {
      baseline_id: 'manual_gis_overlay_checklist',
      label: 'Manual GIS overlay plus checklist review',
      tests: 'Whether the current workflow can already detect hard-constraint conflicts reliably through manual overlay and checklist review.',
      minimum_output: ['Manual hit list', 'Evidence screenshot or layer record', 'Review opinion', 'Final disposition'],
      why_needed: 'If the manual workflow already has high recall and a complete audit trail, TWM must show incremental value in efficiency, evidence completeness, or review burden.',
    },
    {
      baseline_id: 'rule_only_spatial_compliance_engine',
      label: 'Rule-only spatial compliance engine',
      tests: 'Whether rule overlay alone already detects the risks, and whether TWM adds evidence gates and explicit audit boundaries.',
      minimum_output: ['Rule hits', 'Severity', 'Spatial relation', 'Clause citation'],
      why_needed: 'Prevents capabilities already solved by a rule engine from being presented as world-model innovation.',
    },
    {
      baseline_id: 'land_use_simulator_or_optimization_only_ranking',
      label: 'Land-use simulator or optimization-only ranking',
      tests: 'Whether conventional simulation or optimization can already rank plans, and whether TWM better explains illegal, under-evidenced, and review-only options.',
      minimum_output: ['Candidate ranking', 'Spatial-change forecast or optimization score', 'Constraint-hit results'],
      why_needed: 'Prevents existing land-use simulation or optimization capabilities from being reimplemented and claimed as a new method.',
    },
    {
      baseline_id: 'ad_hoc_layer_mapping',
      label: 'Ad hoc layer and field mapping',
      tests: 'Whether role contracts genuinely reduce onboarding errors instead of only adding configuration complexity.',
      minimum_output: ['Field-mapping table', 'Value-domain check results', 'Manual correction log'],
      why_needed: 'Validates the practical data-onboarding benefit of the TWM state contract.',
    },
  ],
  next_experiments: [
    {
      priority: 'P0',
      experiment: 'Retrospective approval replay',
      question: 'Does TWM miss fewer hard-constraint conflicts and produce a more complete evidence chain than manual or rule-only baselines on real or sanitized historical projects?',
      decision: 'C1/C2 can move from scaffold to retrospective evidence only after this passes.',
    },
    {
      priority: 'P0',
      experiment: 'Operator workflow interview and task timing',
      question: 'Is there a real unmet need, and does TWM reduce evidence-gathering time or review rework?',
      decision: 'If existing tools already solve the need well, narrow or stop the corresponding scenario.',
    },
    {
      priority: 'P1',
      experiment: 'Plan-option triage benchmark',
      question: 'Does TWM explain illegal, under-evidenced, and review-only outcomes better than optimization-only ranking on real candidate plans?',
      decision: 'The C3 action-conditioned dynamics claim can be upgraded only after this passes.',
    },
    {
      priority: 'P1',
      experiment: 'Cross-region standard ingestion audit',
      question: 'Do role contracts reduce onboarding errors and rework across regions and standard samples?',
      decision: 'The C4 standard-adaptation claim can be upgraded only after this passes.',
    },
  ],
  mentor_answer: 'TWM novelty must be tied to a real business problem, a simpler baseline, data gates, and falsifiable metrics.',
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

const DEFAULT_DEMO_BUNDLE = DEMO_BUNDLES[1];

const TWM_DEMO_MAP_CENTER: [number, number] = [29.7771813765, 106.2598609625];

const TWM_SUB_TABS: TwmSubTab[] = ['briefing', 'overview', 'data', 'operate', 'graph', 'payload'];

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
      _twm_data_nature: i18n.t('territoryWorldModelDynamicMapExtras.dataNatureDemo'),
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

function twmMapFeatures() {
  const text = (key: string) => i18n.t(`territoryWorldModelDynamicMapExtras.${key}`);
  return {
    reviewArea: twmMapFeature(
      'twm_review_area',
      text('reviewAreaName'),
      text('reviewAreaRole'),
      bboxRing(106.152182211, 29.667518609, 106.367539714, 29.886844144),
      { _twm_description: text('reviewAreaDescription') },
    ),
    project: twmMapFeature(
      'project_demo_01',
      text('projectName'),
      text('projectRole'),
      bboxRing(106.215, 29.745, 106.245, 29.775),
      { _twm_description: text('projectDescription') },
    ),
    pbf: twmMapFeature(
      'pbf_demo_01',
      text('pbfName'),
      text('hardConstraintRole'),
      bboxRing(106.205, 29.728, 106.250, 29.800),
      { _twm_rule: text('pbfRule') },
    ),
    eco: twmMapFeature(
      'eco_demo_01',
      text('ecoName'),
      text('hardConstraintRole'),
      bboxRing(106.250, 29.748, 106.310, 29.825),
      { _twm_rule: text('ecoRule') },
    ),
    hardConflict: twmMapFeature(
      'risk_hit_hard_01',
      text('hardConflictName'),
      text('ruleHitRole'),
      bboxRing(106.220, 29.752, 106.238, 29.770),
      {
        _twm_risk_level: i18n.t('territoryWorldModel.status.high'),
        _twm_matched_rule: text('hardConflictRule'),
        _twm_suggested_action: text('actionProtectReview'),
      },
    ),
    evidenceGap: twmMapFeature(
      'risk_hit_evidence_01',
      text('evidenceGapName'),
      text('ruleHitRole'),
      bboxRing(106.245, 29.760, 106.262, 29.780),
      {
        _twm_risk_level: i18n.t('territoryWorldModel.status.medium'),
        _twm_matched_rule: text('evidenceGapRule'),
        _twm_suggested_action: text('actionSupplementMaterials'),
      },
    ),
    recommended: twmMapFeature(
      'candidate_recommended_01',
      text('recommendedName'),
      text('recommendedRole'),
      bboxRing(106.180, 29.695, 106.205, 29.720),
      {
        _twm_planning_benefit: text('planningBenefitHigh'),
        _twm_constraint_risk: text('constraintRiskLow'),
        _twm_description: text('recommendedDescription'),
      },
    ),
    blocked: twmMapFeature(
      'candidate_blocked_01',
      text('blockedName'),
      text('blockedRole'),
      bboxRing(106.232, 29.758, 106.255, 29.782),
      {
        _twm_block_reason: text('blockedReason'),
        _twm_description: text('blockedDescription'),
      },
    ),
  };
}

function twmMapLayers(stage: TwmMapStage) {
  const features = twmMapFeatures();
  const text = (key: string) => i18n.t(`territoryWorldModelDynamicMapExtras.${key}`);
  const tooltipLabels = {
    name: text('tooltipName'),
    role: text('tooltipRole'),
    _twm_data_nature: text('tooltipDataNature'),
    _twm_description: text('tooltipDescription'),
    _twm_rule: text('tooltipRule'),
    _twm_risk_level: text('tooltipRiskLevel'),
    _twm_matched_rule: text('tooltipMatchedRule'),
    _twm_suggested_action: text('tooltipSuggestedAction'),
    _twm_planning_benefit: text('tooltipPlanningBenefit'),
    _twm_constraint_risk: text('tooltipConstraintRisk'),
    _twm_block_reason: text('tooltipBlockReason'),
  };
  const layers: any[] = [
    {
      name: text('reviewAreaLayer'),
      type: 'polygon',
      geojsonData: featureCollection([features.reviewArea]),
      style: { color: '#38bdf8', fillColor: '#38bdf8', fillOpacity: 0.08, weight: 2 },
      tooltip_fields: ['name', 'role', '_twm_data_nature', '_twm_description'],
      tooltip_labels: tooltipLabels,
    },
    {
      name: text('projectLayer'),
      type: 'polygon',
      geojsonData: featureCollection([features.project]),
      style: { color: '#f59e0b', fillColor: '#f59e0b', fillOpacity: 0.25, weight: 2 },
      tooltip_fields: ['name', 'role', '_twm_data_nature', '_twm_description'],
      tooltip_labels: tooltipLabels,
    },
    {
      name: text('constraintsLayer'),
      type: 'polygon',
      geojsonData: featureCollection([features.pbf, features.eco]),
      style: { color: '#22c55e', fillColor: '#22c55e', fillOpacity: 0.12, weight: 2 },
      tooltip_fields: ['name', 'role', '_twm_data_nature', '_twm_rule'],
      tooltip_labels: tooltipLabels,
    },
  ];

  if (stage === 'risk' || stage === 'plan') {
    layers.push({
      name: text('riskLayer'),
      type: 'polygon',
      geojsonData: featureCollection([features.hardConflict, features.evidenceGap]),
      style: { color: '#ef4444', fillColor: '#ef4444', fillOpacity: 0.38, weight: 2 },
      tooltip_fields: ['name', 'role', '_twm_data_nature', '_twm_risk_level', '_twm_matched_rule', '_twm_suggested_action'],
      tooltip_labels: tooltipLabels,
    });
  }

  if (stage === 'plan') {
    layers.push(
      {
        name: text('recommendedLayer'),
        type: 'polygon',
        geojsonData: featureCollection([features.recommended]),
        style: { color: '#0ea5e9', fillColor: '#22c55e', fillOpacity: 0.36, weight: 3 },
        tooltip_fields: ['name', 'role', '_twm_data_nature', '_twm_planning_benefit', '_twm_constraint_risk', '_twm_description'],
        tooltip_labels: tooltipLabels,
      },
      {
        name: text('blockedLayer'),
        type: 'polygon',
        geojsonData: featureCollection([features.blocked]),
        style: { color: '#dc2626', fillColor: '#dc2626', fillOpacity: 0.18, weight: 3 },
        tooltip_fields: ['name', 'role', '_twm_data_nature', '_twm_block_reason', '_twm_description'],
        tooltip_labels: tooltipLabels,
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
    return formatNumber(value, {
      minimumFractionDigits: Math.abs(value) >= 1000 ? 0 : digits,
      maximumFractionDigits: digits,
    });
  }
  return String(value);
}

function statusClass(status?: string) {
  const normalized = String(status || '').toLowerCase();
  if (['pass', 'ready', 'ok', 'success', 'complete', 'completed', 'legal_feasible', 'built'].includes(normalized)) return 'success';
  if (['blocked', 'error', 'failed', 'failure'].includes(normalized)) return 'error';
  if (['review', 'warning', 'draft', 'open', 'pending', 'partial', 'action_required', 'requires_conversion', 'required'].includes(normalized)) return 'warning';
  return 'proposed';
}

const DISPLAY_LABELS: Record<string, string> = {
  'Can a governance-oriented geospatial world model improve territorial planning decisions by coupling hierarchical GIS state, policy constraints, evidence provenance and action-conditioned forecast in one auditable loop?':
    '面向治理的国土空间世界模型，能否把分层 GIS 状态、政策约束、依据来源和行动条件预测放进同一条可审计决策链路，从而改进国土空间规划审查？',
  'Hierarchical GIS object-relation-rule-evidence state': '分层 GIS 对象-关系-规则-依据状态',
  'Action-conditioned multi-head territorial dynamics': '行动条件国土空间动态预测',
  'Evidence-gated and causally calibrated claim ladder': '依据门控与因果校准主张阶梯',
  'TWM represents parcels, projects, control boundaries, planning zones, approvals, evidence and rules as a linked state rather than as a flat feature table.':
    'TWM 把图斑、项目、管控边界、规划分区、审批、依据和规则组织成可追溯的关联状态，而不是扁平要素表。',
  'TWM forecasts future area/key indicators, constraint-risk, planning utility, uncertainty and action-mask feasibility conditional on review/protect/convert/restore actions; future_latent_state remains a compatibility field, not a full parcel-geometry latent.':
    'TWM 围绕复核、保护、转换、恢复等治理动作预测未来面积/关键指标、约束风险、规划效用、不确定性和动作可行性；future_latent_state 仅保留为兼容字段，不声称完整图斑几何潜在状态。',
  'TWM separates deterministic rule evidence, observational causal calibration and validation gates before upgrading any operational claim.':
    'TWM 在升级任何业务主张前，先区分确定性规则依据、观察性因果校准和验证门槛。',
  'The novelty is architectural integration, not that GIS simulation itself is new.':
    '创新点是面向业务决策的架构集成，而不是声称 GIS 模拟本身是新问题。',
  'Compare against land-use simulators, GIS rule engines and optimization tools on whether they jointly expose action-conditioned forecast, policy evidence and audit-ready claim boundaries.':
    '与土地利用模拟、GIS 规则引擎和优化工具对比，看其是否同时给出行动条件预测、政策依据和可审计主张边界。',
  'Object-relation-rule-evidence state reduces missed compliance conflicts compared with layer-by-layer manual review.':
    '对象-关系-规则-依据状态相比逐图层人工审查，减少合规冲突漏检。',
  'Measure hard-constraint conflict recall and false review burden on held-out real approval/review cases.':
    '在留出的真实审批/复核案例上度量硬约束冲突召回和误复核负担。',
  'Evidence-gated forecasts improve decision defensibility compared with black-box planning scores.':
    '依据门控预测相比黑箱规划分数，提升决策可辩护性。',
  'Audit whether every recommended or rejected option carries source evidence, rule clause, uncertainty and human-review reason.':
    '审计每个推荐或拒绝方案是否带有来源依据、规则条款、不确定性和人工复核原因。',
  'Planning and land-use review workflows still fragment spatial overlays, policy checks, approval evidence and scenario comparison across separate tools.':
    '规划和用地审查中，空间叠加、政策核查、审批材料和方案比较仍常分散在不同工具中。',
  'Existing land-use simulators emphasize spatial pattern transition, while operational review needs action consequences, rule validity and audit boundaries.':
    '现有土地利用模拟更强调空间格局转移，而业务审查需要动作后果、规则有效性和审计边界。',
  'Optimization tools can rank candidates, but often do not preserve why a candidate is illegal, under-evidenced or only reviewable rather than approvable.':
    '优化工具可以排序候选方案，但往往不能保留“为什么违法、依据不足或只能复核不能审批”的理由。',
  'Manual GIS overlay plus checklist review': '人工 GIS 叠加加清单审查',
  'Rule-only spatial compliance engine': '单纯空间合规规则引擎',
  'Land-use simulation models such as FLUS/PLUS/CLUE-S/CA-Markov for pattern transition':
    '用于格局转移的 FLUS/PLUS/CLUE-S/CA-Markov 等土地利用模拟模型',
  'Optimization-only farmland or planning candidate ranking without evidence-gated claim validation':
    '不带依据门控主张验证的耕地或规划候选方案优化排序',
  'If real workflow interviews show the target decisions are already well solved by existing tools, TWM should be narrowed or stopped.':
    '如果真实业务访谈显示目标决策已被现有工具很好解决，TWM 应收窄或停止。',
  'If TWM does not improve hard-constraint conflict recall, evidence completeness or audit-trail quality over baselines, the claimed contribution is not supported.':
    '如果 TWM 相比基线不能提升硬约束冲突召回、依据完整性或审计链质量，则贡献主张不成立。',
  'If action-conditioned dynamics cannot be validated beyond synthetic fixtures, TWM must remain a review scaffold rather than a production decision model.':
    '如果行动条件动态只能在合成样例上验证，TWM 必须保持复核脚手架定位，而不能作为生产决策模型。',
  'Collect real or sanitized approval/review histories with project geometry, rule outcomes, evidence links and final decisions.':
    '收集带项目几何、规则结果、依据链接和最终决策的真实或脱敏审批/复核历史。',
  'Benchmark against manual overlay, rule-only engine and at least one land-use simulation or optimization baseline where appropriate.':
    '按场景与人工叠加、单纯规则引擎，以及至少一种土地利用模拟或优化基线对比。',
  'Report missed hard-constraint conflicts, review-task precision, evidence completeness, candidate rejection reason coverage and audit-trail completeness.':
    '报告硬约束漏检、复核任务精度、依据完整性、候选方案拒绝原因覆盖和审计链完整性。',
  'Keep synthetic fixtures for regression only; do not use them as production-effect evidence.':
    '合成样例只用于回归测试，不作为生产效果依据。',
  'Current TWM is a rigorous prototype and review scaffold. Its defensible near-term claim is auditable decision support for territorial governance workflows; production-grade predictive claims require real observed histories, baseline comparisons and external validation.':
    '当前 TWM 是严谨的原型和复核脚手架；近期可辩护主张是为国土治理流程提供可审计决策支持，生产级预测主张仍需真实观察历史、基线对比和外部验证。',
  'Object-relation-rule-evidence state reduces missed hard-constraint conflicts compared with layer-by-layer manual GIS review.':
    '对象-关系-规则-依据状态相比逐图层人工 GIS 审查，能够减少硬约束冲突漏检。',
  'Evidence-gated review improves audit defensibility compared with rule-only spatial compliance engines.':
    '依据门控复核相比单纯空间合规规则引擎，能够提升审计可辩护性。',
  'Action-conditioned dynamics improves plan-option triage compared with land-use simulators or optimization-only candidate ranking.':
    '行动条件动态推演相比土地利用模拟或单纯优化排序，能够改进方案预筛和解释。',
  'Synthetic fixtures verify the pipeline and rule/evidence object model, but do not validate real conflict recall.':
    '合成样例验证了流程和规则/依据对象模型，但尚未验证真实冲突召回率。',
  'Current rule hits, evidence items and review tasks are synthetic/not-for-production; useful for regression, not for audit quality proof.':
    '当前规则命中、依据项和复核任务为合成或非生产数据，可用于回归测试，不能证明真实审计质量。',
  'Synthetic experiment foundation supports action-mask and beam-plan plumbing; no real action-conditioned dynamics validation yet.':
    '合成实验基础支撑动作可行性掩码和方案比选链路，但尚未完成真实行动条件动态验证。',
  'Every TWM research claim must name the unmet business need, a simpler baseline, minimum real-data evidence, metrics and falsification conditions before it can be upgraded beyond prototype status.':
    '每一项 TWM 研究主张都必须说明未满足业务需求、可对比的简单基线、最低真实数据依据、评价指标和可证伪条件，之后才可能从原型状态升级。',
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
  'Natural resources demo closure': '自然资源演示闭环',
  'Auditable TWM engineering scaffold': '可审计 TWM 工程脚手架',
  'Data foundation productization': '数据基础产品化',
  'Trusted pilot validation': '可信试点验证',
  'Production and air-gapped deployment': '生产与离线部署',
  'Chinese-first TWM frontend tabs are implemented': '中文优先 TWM 前端分区已实现',
  'data foundation map preview and bbox-aligned overview map are implemented': '数据基础地图预览和 bbox 对齐总览地图已实现',
  'automated E2E evidence exists for the demo workflow': '演示工作流已有自动化端到端依据',
  'manual acceptance and demo freeze before external presentation': '外部汇报前还需人工验收和演示冻结',
  'state/rule/evidence/audit pipeline': '状态、规则、依据、审计管线',
  'forecast, counterfactual rollout, validation ladder and beam planning consumer': '预测、反事实 rollout、验证阶梯和 beam 方案消费者',
  'trainable dynamics candidates and observational causal calibration reports': '可训练动态候选和观察性因果校准报告',
  'dynamics model registry release gate report is implemented': '动态模型注册发布门禁报告已实现',
  'service decomposition': '服务拆分',
  'model registry/version rollback': '模型注册和版本回滚',
  'persistent model registry/version rollback': '持久化模型注册和版本回滚',
  'production-scale storage/index review': '生产规模存储和索引复核',
  'demo dataset catalog, CRS diagnostics and map overlay readiness are exposed': '演示数据目录、CRS 诊断和地图叠加 readiness 已暴露',
  'full GeoJSON preview is available for the current demo scale': '当前演示规模支持完整 GeoJSON 预览',
  'lineage and field drilldown reports are exposed through API, tools and frontend': 'lineage 和字段 drilldown 报告已通过 API、工具和前端暴露',
  'CRS remediation plan is exposed through API, tools and frontend': 'CRS 修复方案已通过 API、工具和前端暴露',
  'authoritative production data templates are exposed through API, tools and frontend': '权威生产数据模板已通过 API、工具和前端暴露',
  'authoritative data templates': '权威数据模板',
  'lineage browser': 'lineage 浏览器',
  'vector tiles or server-side chunking': '矢量瓦片或服务端分块',
  'CRS conversion workflow': 'CRS 转换流程',
  'production CRS conversion ETL': '生产级 CRS 转换 ETL',
  'production lineage ingestion templates': '生产 lineage 接入模板',
  custodian_signoff: '数据责任方签核',
  not_for_production_flag_clearance: '非生产标记清除',
  same_case_join_keys: '同案关联键',
  crs_and_geometry_acceptance: 'CRS 和几何验收',
  parcel_current_authoritative: '权威现状图斑',
  planning_zone_authoritative: '权威规划分区',
  approval_records_authoritative: '权威审批历史',
  policy_action_history_authoritative: '权威政策动作历史',
  evidence_index_authoritative: '权威依据索引',
  rule_evaluation_authoritative: '权威规则评价',
  'public Dynamic World and GeoSOS/FLUS benchmark evidence exists': '已有公开 Dynamic World 与 GeoSOS/FLUS 基准依据',
  'claim ladder and baseline comparison contracts exist': '主张阶梯和基线对比契约已存在',
  'real observed approval/review history': '真实观察审批/复核历史',
  'policy/action feasibility labels': '政策/动作可行性标签',
  'same-case baseline and holdout evaluation': '同案基线和留出集评估',
  'air-gapped deployment strategy exists': '已有离线部署策略',
  'offline deployment package': '离线部署包',
  'permissioned audit trail': '权限化审计链',
  'model/rule/version comparison': '模型、规则和版本对比',
  'sanitized diagnostic export': '脱敏诊断导出',
  mixed_real_imagery_plus_synthetic_governance_fixture: '真实影像加合成治理样例',
  synthetic_multi_admin_governance_fixture: '合成多行政单元治理样例',
  standard_structure_sample_with_synthetic_substitutes: '含合成替代数据的标准结构样例',
  production_observed_history: '生产观察历史',
  named_real_workflow_baseline: '明确的真实工作流基线',
  production_policy_action_labels: '生产政策动作标签',
  policy_action_history: '政策动作历史',
  service_decomposition: '服务拆分',
  full_flus_and_holdout_baselines: '完整 FLUS 与留出基线',
  review_not_for_production: '非生产复核',
  candidate_authoritative: '候选权威来源',
  authoritative_source_lineage: '权威来源 lineage',
  map_overlay_crs: '地图叠加 CRS',
  spatial_layer: '空间图层',
  auxiliary_table: '辅助表格',
  supporting_file: '支撑文件',
  'one pilot region with multi-year observed approval/review history': '一个试点区域的多年观察审批/复核历史',
  'authoritative policy/action feasibility labels': '权威政策/动作可行性标签',
  'large facade service': '大型 facade 服务',
  'state, dynamics, calibration, planner, evidence/audit and readiness services': '状态、动态、校准、规划器、依据/审计和 readiness 服务',
  'public benchmark and simplified/direct adapters': '公开基准和简化/直接适配器',
  'same-case full FLUS/GeoSOS baseline plus cross-region/cross-year holdout': '同案完整 FLUS/GeoSOS 基线加跨区域/跨年份留出验证',
  'secure real or sanitized observed history and policy/action labels for one pilot region': '为一个试点区域获取真实或脱敏观察历史与政策/动作标签',
  'freeze and manually accept the current natural-resources demo workflow': '冻结并人工验收当前自然资源演示工作流',
  'split the TWM facade service along state/dynamics/calibration/planner/evidence boundaries': '按状态、动态、校准、规划器和依据边界拆分 TWM facade 服务',
  'productize data foundation browsing with lineage, field drilldown and CRS conversion workflow': '产品化数据基础浏览，补齐 lineage、字段 drilldown 和 CRS 转换流程',
  'finish authoritative data templates, vector tiles or chunked preview, and CRS conversion workflow': '完成权威数据模板、矢量瓦片或分块预览，以及 CRS 转换流程',
  'finish authoritative data templates, vector tiles or chunked preview, and production CRS conversion ETL': '完成权威数据模板、矢量瓦片或分块预览，以及生产级 CRS 转换 ETL',
  'finish vector tiles or chunked preview, production CRS conversion ETL, and production lineage ingestion templates': '完成矢量瓦片或分块预览、生产级 CRS 转换 ETL 和生产 lineage 接入模板',
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
  no_conversion_required: '无需转换',
  identify_source_crs: '识别源 CRS',
  reproject_to_target_crs: '重投影到目标 CRS',
  validate_bbox_and_geometry: '校验范围和几何',
  write_lineage_preserving_output: '写出带 lineage 的结果',
  verify_declared_crs: '核验声明 CRS',
  preserve_source_layer: '保留源图层',
  unknown_projected_or_non_wgs84: '未知投影或非 WGS84',
  payload: '请求载荷',
  none: '无',
  hard_constraint_conflict_recall: '硬约束冲突召回率',
  missed_blocking_conflict_rate: '阻断性冲突漏检率',
  evidence_link_completeness: '依据链接完整性',
  audit_trail_completeness: '审计链完整性',
  unsupported_recommendation_rate: '无依据建议率',
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
  baseline_evidence_not_provided: '基线依据未提供',
  eligible_for_retrospective_evidence: '可进入历史回放验证',
  metrics_pass_but_data_gate_blocks_upgrade: '指标通过但真实数据门槛阻止升级',
  no_metric_lift_over_baseline: '相对基线没有指标增益',
  baseline_comparison: '基线对比',
  baseline_export_validation: '基线导出校验',
  baseline_export_validation_run_card: '基线导出校验运行卡片',
  baseline_comparison_run_card: '基线对比运行卡片',
  review_required: '需要复核',
  claim_supported: '主张有依据支撑',
  hard_blocked: '硬约束阻断',
  eligible: '可进入后续流程',
  export_validation: '导出校验',
  comparison_completed: '对比已完成',
  same_case_join_key: '同案关联键',
  missing_required_columns: '缺少必填字段',
  coverage_below_minimum: '重叠覆盖不足',
  no_overlap: '没有同案重叠',
  parser_metric_missing: '解析指标缺失',
  'package case-level evidence and baseline outputs for external review': '打包案例级依据和基线输出，供外部复核',
  'repeat on a held-out region/time split before pilot claim': '在留出的区域/时间切分上重复验证后，再提出试点主张',
  'collect real or sanitized production history required by the claim gate': '收集主张门槛要求的真实或脱敏生产历史',
  'inspect failed metrics and simplify the TWM claim': '检查未通过指标，并收窄 TWM 主张',
  'do not add new model backends until the baseline gap is understood': '在理解基线差距前，不新增模型后端',
  'provide both TWM metrics and named baseline metrics for the same cases': '为同一批案例同时提供 TWM 指标和明确基线指标',
  'keep the claim at prototype scaffold level': '将主张保持在原型脚手架级别',
};

const SOURCE_DISPLAY_LABELS = Object.fromEntries(
  Object.entries(DISPLAY_LABELS).map(([source, chinese]) => [chinese, source]),
) as Record<string, string>;

const DYNAMIC_LABEL_KEYS: Record<string, string> = {
  'Can a governance-oriented geospatial world model improve territorial planning decisions by coupling hierarchical GIS state, policy constraints, evidence provenance and action-conditioned forecast in one auditable loop?': 'question',
  'Hierarchical GIS object-relation-rule-evidence state': 'coreStateName',
  'TWM represents parcels, projects, control boundaries, planning zones, approvals, evidence and rules as a linked state rather than as a flat feature table.': 'coreStateClaim',
  'Action-conditioned multi-head territorial dynamics': 'coreDynamicsName',
  'TWM forecasts a multi-dimensional hierarchical future-state latent, constraint-risk, planning utility, uncertainty and action-mask feasibility conditional on review/protect/convert/restore actions; the latent is decoded into state summaries and does not generate full parcel geometry.': 'coreDynamicsClaim',
  'Evidence-gated and causally calibrated claim ladder': 'coreEvidenceName',
  'TWM separates deterministic rule evidence, observational causal calibration and validation gates before upgrading any operational claim.': 'coreEvidenceClaim',
  'The novelty is architectural integration, not that GIS simulation itself is new.': 'innovationArchitecture',
  'Compare against land-use simulators, GIS rule engines and optimization tools on whether they jointly expose action-conditioned forecast, policy evidence and audit-ready claim boundaries.': 'innovationArchitectureTest',
  'Object-relation-rule-evidence state reduces missed compliance conflicts compared with layer-by-layer manual review.': 'innovationConflict',
  'Measure hard-constraint conflict recall and false review burden on held-out real approval/review cases.': 'innovationConflictTest',
  'Evidence-gated forecasts improve decision defensibility compared with black-box planning scores.': 'innovationDefensibility',
  'Audit whether every recommended or rejected option carries source evidence, rule clause, uncertainty and human-review reason.': 'innovationDefensibilityTest',
  'Planning and land-use review workflows still fragment spatial overlays, policy checks, approval evidence and scenario comparison across separate tools.': 'unmetFragmented',
  'Existing land-use simulators emphasize spatial pattern transition, while operational review needs action consequences, rule validity and audit boundaries.': 'unmetSimulation',
  'Optimization tools can rank candidates, but often do not preserve why a candidate is illegal, under-evidenced or only reviewable rather than approvable.': 'unmetOptimization',
  'If real workflow interviews show the target decisions are already well solved by existing tools, TWM should be narrowed or stopped.': 'falsificationSolved',
  'If TWM does not improve hard-constraint conflict recall, evidence completeness or audit-trail quality over baselines, the claimed contribution is not supported.': 'falsificationNoLift',
  'If action-conditioned dynamics cannot be validated beyond synthetic fixtures, TWM must remain a review scaffold rather than a production decision model.': 'falsificationSynthetic',
  'Current TWM is a rigorous prototype and review scaffold. Its defensible near-term claim is auditable decision support for territorial governance workflows; production-grade predictive claims require real observed histories, baseline comparisons and external validation.': 'claimBoundary',
  'Retrospective approval replay': 'experimentRetrospective',
  '历史审批回放': 'experimentRetrospective',
  'Does TWM miss fewer hard-constraint conflicts and produce a more complete evidence chain than manual or rule-only baselines on real or sanitized historical projects?': 'experimentRetrospectiveQuestion',
  '在真实或脱敏历史项目上，TWM 是否比 manual/rule-only baseline 少漏掉硬约束冲突，并生成更完整证据链？': 'experimentRetrospectiveQuestion',
  '在真实历史项目上是否优于人工或单纯规则基线？': 'experimentRetrospectiveQuestion',
  'Operator workflow interview and task timing': 'experimentOperator',
  '操作员流程访谈与耗时测量': 'experimentOperator',
  'Is there a real unmet need, and does TWM reduce evidence-gathering time or review rework?': 'experimentOperatorQuestion',
  '目标业务是否真有未满足需求，TWM 是否减少查证时间或复核返工？': 'experimentOperatorQuestion',
  '目标业务是否真有未满足需求？': 'experimentOperatorQuestion',
  'Plan-option triage benchmark': 'experimentPlanTriage',
  'Does TWM explain illegal, under-evidenced, and review-only outcomes better than optimization-only ranking on real candidate plans?': 'experimentPlanTriageQuestion',
  '在真实候选方案上，TWM 是否比优化-only ranking 更能解释非法、证据不足和 review-only 原因？': 'experimentPlanTriageQuestion',
  'Cross-region standard ingestion audit': 'experimentCrossRegion',
  '角色契约在多个地区/标准样例上是否减少接入错误和返工？': 'experimentCrossRegionQuestion',
  'Do role contracts reduce onboarding errors and rework across regions and standard samples?': 'experimentCrossRegionQuestion',
  '通过后才能把 C1/C2 从 scaffold 提升到 retrospective evidence。': 'experimentDecisionC12',
  'C1/C2 can move from scaffold to retrospective evidence only after this passes.': 'experimentDecisionC12',
  '如果需求已被现有工具很好解决，应收窄或停止对应场景。': 'experimentDecisionOperator',
  'If existing tools already solve the need well, narrow or stop the corresponding scenario.': 'experimentDecisionOperator',
  '通过后才允许升级 C3 的 action-conditioned dynamics claim。': 'experimentDecisionC3',
  'The C3 action-conditioned dynamics claim can be upgraded only after this passes.': 'experimentDecisionC3',
  '通过后才允许升级 C4 的标准适配 claim。': 'experimentDecisionC4',
  'The C4 standard-adaptation claim can be upgraded only after this passes.': 'experimentDecisionC4',
};

const DYNAMIC_DATA_FOUNDATION_KEYS: Record<string, string> = {
  '当前数据基础足以支撑 TWM 工程化原型、规则/证据/审计链路和合成实验验证；不足以支撑生产级审批结论、真实预测效果或真实因果改进声明。': 'verdict',
  '当前数据基础足以支撑 TWM 工程原型、规则/依据/审计链路和合成实验验证；不足以支撑生产级审批结论、真实预测效果或真实因果改进声明。': 'verdict',
  '生产可用观察历史行数为 0': 'blockerObservedHistory',
  '生产政策动作历史未提供': 'blockerPolicyHistory',
  '关键审批、复核、规则评价和项目样本主要为 synthetic/not-for-production': 'blockerSyntheticRecords',
  '关键治理记录为合成或非生产数据': 'blockerSyntheticRecords',
  '尚缺真实 workflow baseline 对比来证明未满足需求与改进幅度': 'blockerWorkflowBaseline',
  'Bishan demo engineering fixture': 'datasetDemo',
  '璧山演示工程样例': 'datasetDemo',
  'Bishan multi-admin evaluation fixture': 'datasetMultiAdmin',
  '璧山多行政单元评估样例': 'datasetMultiAdmin',
  'One Map village standard sample': 'datasetOneMap',
  '一张图村庄规划标准样例': 'datasetOneMap',
  '工程 MVP 与回归测试主数据包；含真实 Sentinel-2 影像，但项目、PBF、生态红线、审批/复核等治理对象为合成或 not-for-production。': 'datasetDemoPositioning',
  '工程原型与回归测试主数据包；含真实 Sentinel-2 影像，但关键治理对象为合成或非生产数据。': 'datasetDemoPositioning',
  '多行政单元压力测试与数据基础体检主对象；结构覆盖更宽，但关键业务历史仍为 synthetic/not-for-production。': 'datasetMultiAdminPositioning',
  '多行政单元压力测试与数据基础体检主对象；关键业务历史仍为合成或非生产数据。': 'datasetMultiAdminPositioning',
  '用于验证自然资源一张图村规划样例能否按 TWM 角色契约接入；所有数据均 not-for-production。': 'datasetOneMapPositioning',
  '验证自然资源一张图村规划样例能否按 TWM 角色契约接入；所有数据均为非生产数据。': 'datasetOneMapPositioning',
  '工程 MVP 与回归测试': 'supportEngineering',
  '可验证项目创建、状态构建、角色绑定、规则评价、证据链、审计报告、前端 TWM 工作流是否跑通。': 'supportEngineeringDetail',
  '验证状态构建、角色绑定、规则评价、依据链、审计报告和 TWM 前端工作流。': 'supportEngineeringDetail',
  '业务审查脚手架': 'supportReview',
  '可模拟耕地保护、生态红线、用途管制、审批一致性、复核任务等对象之间的关系和风险暴露逻辑。': 'supportReviewDetail',
  '模拟耕地保护、生态红线、用途管制、审批一致性和复核任务风险暴露。': 'supportReviewDetail',
  '优化/规划消费者链路': 'supportPlanning',
  '可测试候选方案载入、硬约束过滤、beam ranking、action-mask 安全头和验证口径是否按证据门控降级。': 'supportPlanningDetail',
  '测试候选方案载入、硬约束过滤、beam ranking 和 action-mask 安全头。': 'supportPlanningDetail',
  '一张图标准适配': 'supportOneMap',
  '可检查字段别名、角色契约、值域、图斑/分区/管控边界等标准结构能否被 TWM 状态模型消费。': 'supportOneMapDetail',
  '目前 TWM 靠谱的部分是工程和研究假设验证，不是生产落地证明。数据基础能说明 TWM 的对象-关系-规则-证据框架可跑通，也能暴露哪些业务问题需要真实数据继续验证；但在真实审批历史和政策动作标签缺失前，不能声称它已经解决真实国土治理决策。': 'mentorShort',
  '目前 TWM 靠谱的部分是工程和研究假设验证，不是生产落地证明。': 'mentorShort',
  '下一阶段应把研究问题收敛到真实未满足需求：跨图层规则审查、证据链完整性、审查任务优先级和方案不可行原因解释。这些问题需要用真实或脱敏业务样本与 manual/rule-only/simulator/optimizer baseline 对比。': 'mentorJudgment',
  '下一阶段应把研究问题收敛到真实未满足需求，并用真实或脱敏业务样本与 manual/rule-only/simulator/optimizer baseline 对比。': 'mentorJudgment',
  '生产级审批结论': 'unsupportedApproval',
  '当前审批、复核、执法、规则命中和项目样本主要为 synthetic/not-for-production，不能替代真实业务责任链。': 'unsupportedApprovalReason',
  '审批、复核、执法和规则命中记录主要为合成或非生产数据。': 'unsupportedApprovalReason',
  '真实治理效果预测或因果改进': 'unsupportedGovernance',
  '尚无非合成的生产观察历史、真实 treated/control 样本、真实政策动作可行性标签和跨期审批结果。': 'unsupportedGovernanceReason',
  '尚无非合成生产观察历史、真实 treated/control 样本和政策动作标签。': 'unsupportedGovernanceReason',
  '行动条件动态模型已被真实数据验证': 'unsupportedDynamics',
  '结构性和合成实验门通过的是管线与诊断能力，默认证据门仍为 review，不能升级为生产准确性证明。': 'unsupportedDynamicsReason',
  'TWM 已证明优于现有业务工具': 'unsupportedOutperforms',
  '仍缺真实工作流基线对比，如 manual GIS overlay、rule-only engine、土地利用模拟或优化工具的同题评测。': 'unsupportedOutperformsReason',
  '真实或脱敏的项目审批/复核/补正/执法历史': 'nextApprovalHistory',
  '生产观察历史、业务效果评估、人工审查负担和漏检风险基线。': 'nextApprovalHistoryUnlocks',
  '生产观察历史、业务效果评估和真实基线对比。': 'nextApprovalHistoryUnlocks',
  '权威管控边界与规划约束版本': 'nextAuthoritativeConstraints',
  '真实硬约束冲突判断、规则条款追溯、跨版本政策动作可行性验证。': 'nextAuthoritativeConstraintsUnlocks',
  '真实硬约束冲突判断和规则条款追溯。': 'nextAuthoritativeConstraintsUnlocks',
  '真实 action-mask/政策可行性标签': 'nextActionLabels',
  '动作可行性安全头、未见地区/政策泛化、方案推荐边界。': 'nextActionLabelsUnlocks',
  '真实时序状态快照与遥感/变更证据': 'nextTemporalEvidence',
  '行动条件动态、反事实推演、预测不确定性和证据覆盖校准。': 'nextTemporalEvidenceUnlocks',
  '耕地保护与占补平衡审查': 'fitFarmland',
  '图斑、PBF、生态红线、项目、规则命中和证据链结构齐备，但关键边界和审批记录仍非生产数据。': 'fitFarmlandWhy',
  '图斑、永久基本农田、生态红线、项目、规则命中和依据链结构齐备，但关键边界和审批记录仍非生产数据。': 'fitFarmlandWhy',
  '风险暴露、证据缺口、人工复核任务和候选方案审计。': 'fitFarmlandSafe',
  '风险暴露、依据缺口、人工复核任务和候选方案审计。': 'fitFarmlandSafe',
  '自动审批通过/不通过或真实政策效果承诺。': 'fitFarmlandUnsafe',
  '建设项目用地合规预审': 'fitConstruction',
  '可模拟项目-分区-边界-复核任务关系，但缺真实项目流转、补正、处置和监管闭环历史。': 'fitConstructionWhy',
  '合规预审工作流原型和审查清单。': 'fitConstructionSafe',
  '生产级项目合规结论。': 'fitConstructionUnsafe',
  '国土空间用途调整推演': 'fitAdjustment',
  '合成多期样本可测动作条件动态和 planner consumer，但缺真实跨期状态和政策动作标签。': 'fitAdjustmentWhy',
  '反事实推演管线、action-mask 和 beam-plan 方法验证。': 'fitAdjustmentSafe',
  '反事实推演管线、动作可行性掩码和方案比选方法验证。': 'fitAdjustmentSafe',
  '真实区域规划效果预测。': 'fitAdjustmentUnsafe',
  experimental: 'fitExperimental',
};

const DYNAMIC_DATA_FOUNDATION_DETAIL_KEYS: Record<string, string> = {
  '真实审批结论': 'missingApprovalOutcome',
  '真实复核记录': 'missingReviewRecords',
  '真实政策动作标签': 'missingPolicyActionLabels',
  '外部因果校准材料只能作为方法参考，不能替代 TWM 生产审批历史验证。': 'externalSupportBoundary',
  'Paper7 可作为因果校准分支外部支持，但不能替代 TWM 生产审批历史验证。': 'paper7SupportBoundary',
};

const DYNAMIC_DATA_GOVERNANCE_KEYS: Record<string, string> = {
  '可用于字段、空间范围和链路回归核查；not_for_production 数据不得作为生产治理结论。': 'reviewOnlyReadiness',
  '缺失文件需先补齐后才能进入数据基础核查。': 'missingFileReadiness',
  '候选权威来源仍需人工验收数据版本、来源证明和权限边界。': 'candidateAuthorityReadiness',
  '每个待处理空间图层必须先确认 source CRS，不能仅凭 bbox 猜测直接转换。': 'confirmSourceCrs',
  '转换后 bbox 必须落入 EPSG:4326 经纬度范围，且要素数量与源文件一致。': 'validateConvertedBbox',
  '输出文件必须保留源文件、源 CRS、目标 CRS、转换时间和工具版本 lineage。': 'preserveConversionLineage',
  'not-for-production 数据仅可用于演示和回归；CRS 转换不会提升其生产权威性。': 'conversionDoesNotUpgradeAuthority',
};

const DYNAMIC_AUTHORITATIVE_TEMPLATE_KEYS: Record<string, string> = {
  parcel_current_authoritative: 'templateParcel',
  'Current land parcel authoritative layer': 'templateParcel',
  planning_zone_authoritative: 'templatePlanningZone',
  'Territorial planning zone authoritative layer': 'templatePlanningZone',
  approval_records_authoritative: 'templateApprovalHistory',
  'Approval and review history authoritative table': 'templateApprovalHistory',
  policy_action_history_authoritative: 'templatePolicyAction',
  'Policy action feasibility authoritative table': 'templatePolicyAction',
  evidence_index_authoritative: 'templateEvidenceIndex',
  'Evidence document and media index authoritative table': 'templateEvidenceIndex',
  rule_evaluation_authoritative: 'templateRuleEvaluation',
  'Rule evaluation authoritative table': 'templateRuleEvaluation',
  feature: 'unitFeature',
  row: 'unitRow',
  parcel: 'roleParcel',
  planning_zone: 'rolePlanningZone',
  approval_record: 'roleApprovalRecord',
  policy_action_history: 'rolePolicyActionHistory',
  evidence_item: 'roleEvidenceItem',
  rule_evaluation: 'roleRuleEvaluation',
  'GeoPackage layer': 'formatGeoPackage',
  'GeoJSON after approved CRS conversion': 'formatGeoJson',
  'PostGIS table': 'formatPostGis',
  CSV: 'formatCsv',
  Parquet: 'formatParquet',
  'database view': 'formatDatabaseView',
  state_object_build_and_rule_overlay: 'useStateRuleOverlay',
  policy_constraint_and_action_mask: 'usePolicyActionMask',
  claim_gate_observed_history_and_same_case_baseline: 'useClaimObservedBaseline',
  action_conditioned_dynamics_validation_and_planner_evaluation: 'useDynamicsPlanner',
  audit_trail_and_evidence_gate: 'useAuditEvidence',
  hard_constraint_recall_and_audit_defensibility_metrics: 'useConflictAuditMetrics',
  custodian_signoff: 'gateCustodianSignoff',
  not_for_production_flag_clearance: 'gateProductionFlag',
  same_case_join_keys: 'gateSameCaseKeys',
  crs_and_geometry_acceptance: 'gateCrsGeometry',
  'each authoritative source has named custodian, sign-off id, source version and permission scope': 'custodianRequired',
  'templates defined; no production custodian sign-off loaded': 'custodianCurrent',
  'production datasets must explicitly set not_for_production=false after governance approval': 'productionFlagRequired',
  'demo fixtures remain not-for-production': 'productionFlagCurrent',
  'case_id/project_id/action_id keys join across approval, action, evidence and rule tables': 'joinKeysRequired',
  'template contract only': 'joinKeysCurrent',
  'known CRS, validated geometry and EPSG:4326 map-overlay derivative where needed': 'crsGeometryRequired',
  'CRS remediation plan exists; production ETL not implemented': 'crsGeometryCurrent',
  known_crs: 'qualityKnownCrs',
  valid_geometry: 'qualityValidGeometry',
  unique_parcel_id: 'qualityUniqueParcel',
  area_positive: 'qualityPositiveArea',
  zone_type_domain_check: 'qualityZoneDomain',
  unique_case_id: 'qualityUniqueCase',
  final_decision_domain_check: 'qualityDecisionDomain',
  decision_time_order: 'qualityDecisionOrder',
  case_action_key_unique: 'qualityUniqueCaseAction',
  action_allowed_boolean: 'qualityActionBoolean',
  blocking_rule_traceable: 'qualityBlockingTrace',
  content_hash_present: 'qualityContentHash',
  permission_scope_present: 'qualityPermissionScope',
  case_link_valid: 'qualityCaseLink',
  rule_code_versioned: 'qualityVersionedRule',
  severity_domain_check: 'qualitySeverityDomain',
  hit_status_domain_check: 'qualityHitStatusDomain',
  'Authoritative templates support production data onboarding planning and review. They do not by themselves certify authority, data rights, model performance or production deployment readiness.': 'claimBoundary',
};

const DYNAMIC_CRS_WORKFLOW_KEYS: Record<string, string> = {
  verify_declared_crs: 'verifyDeclaredCrs',
  preserve_source_layer: 'preserveSourceLayer',
  identify_source_crs: 'identifySourceCrs',
  reproject_to_target_crs: 'reprojectTargetCrs',
  validate_bbox_and_geometry: 'validateBboxGeometry',
  write_lineage_preserving_output: 'writeLineageOutput',
  no_conversion_required: 'noConversionRequired',
  convert_to_wgs84_before_map_overlay: 'convertWgs84',
  unknown_projected_or_non_wgs84: 'unknownProjectedCrs',
  load_on_map: 'loadOnMap',
  fix_crs_before_map_overlay: 'fixCrsFirst',
  add_spatial_layers: 'addSpatialLayers',
  ready_for_map_overlay: 'readyForOverlay',
  inspect_geometry_before_map_overlay: 'inspectGeometryFirst',
  '空间范围缺失，不能确认是否可直接叠加到经纬度底图。': 'messageMissingExtent',
  '坐标范围符合经纬度范围，可直接用于当前演示地图叠加。': 'messageReady',
  '坐标范围超出经纬度范围，直接叠加到当前地图前需要做 CRS 识别和转换。': 'messageConversionRequired',
  '全部空间图层可直接叠加到当前地图。': 'messageAllReady',
  '部分或全部空间图层不是经纬度坐标，直接叠加前需要 CRS 转换。': 'messagePartiallyBlocked',
  '未发现可预览空间图层。': 'messageNoLayers',
  'This CRS remediation plan is an onboarding and map-overlay readiness artifact. It does not transform geometries in the API response, certify source authority, or support production decision claims.': 'claimBoundary',
};

const DYNAMIC_LINEAGE_KEYS: Record<string, string> = {
  authoritative_source_lineage: 'gateAuthoritativeLineage',
  production_observed_history: 'gateObservedHistory',
  production_policy_action_labels: 'gatePolicyLabels',
  map_overlay_crs: 'gateMapCrs',
  spatial_layer: 'roleSpatialLayer',
  auxiliary_table: 'roleAuxiliaryTable',
  supporting_file: 'roleSupportingFile',
  'source authority, data version, update time, permission boundary and custodian sign-off for each production layer/table': 'requiredAuthority',
  'real or sanitized approval/review/remediation/enforcement history with final outcomes': 'requiredObservedHistory',
  'authoritative policy/action feasibility labels for TWM action-conditioned validation': 'requiredPolicyLabels',
  'all spatial layers have known CRS and can be converted to the map display CRS': 'requiredMapCrs',
  'Lineage report supports source review, field mapping, CRS readiness and production onboarding planning; it does not upgrade not-for-production datasets into authoritative evidence.': 'claimBoundary',
};

const DYNAMIC_TWM_STATUS_KEYS: Record<string, string> = {
  review_not_for_production: 'reviewNotForProduction',
  candidate_authoritative: 'candidateAuthoritative',
  external_reference_only: 'externalReferenceOnly',
  not_provided: 'notProvided',
  missing_required_columns: 'missingRequiredColumns',
  ready_for_pilot_validation: 'readyForPilotValidation',
  missing: 'missing',
};

const DYNAMIC_CLAIM_KEYS: Record<string, string> = {
  C1_state_conflict_recall: 'c1Title',
  C2_audit_defensibility: 'c2Title',
  C3_action_conditioned_triage: 'c3Title',
  C4_standard_contract_ingestion: 'c4Title',
  'Object-relation-rule-evidence state reduces missed hard-constraint conflicts compared with layer-by-layer manual GIS review.': 'c1Claim',
  'Evidence-gated review improves audit defensibility compared with rule-only spatial compliance engines.': 'c2Claim',
  'Action-conditioned dynamics improves plan-option triage compared with land-use simulators or optimization-only candidate ranking.': 'c3Claim',
  'Role-contract based ingestion reduces standard-data onboarding errors compared with ad hoc layer mapping.': 'c4Claim',
  manual_gis_overlay_checklist: 'baselineManual',
  rule_only_spatial_compliance_engine: 'baselineRuleOnly',
  land_use_simulator_or_optimization_only_ranking: 'baselineSimulation',
  ad_hoc_layer_mapping: 'baselineAdHoc',
  production_observed_history: 'missingObservedHistory',
  named_real_workflow_baseline: 'missingWorkflowBaseline',
  production_policy_action_labels: 'missingPolicyLabels',
  hard_constraint_conflict_recall: 'metricConflictRecall',
  audit_trail_completeness: 'metricAuditCompleteness',
  candidate_rejection_reason_coverage: 'metricRejectionCoverage',
  legal_feasible_topk_precision: 'metricLegalTopK',
  role_binding_accuracy: 'metricRoleBinding',
};

const DYNAMIC_RESEARCH_DATA_KEYS: Record<string, string> = {
  '项目几何、申请/决定日期、审批结果、复核任务、规则命中、证据链接、最终处置结果。': 'nextApprovalMinimum',
  '永久基本农田、生态保护红线、城镇开发边界、用途管制分区、规划版本与生效时间。': 'nextBoundaryMinimum',
  'action_type、policy_code、allowed/blocked/conditional 标签、region、period、人工复核原因。': 'nextActionLabelMinimum',
  '多期图斑、年度变更、项目落地结果、遥感证据索引和证据质量标注。': 'nextTemporalMinimum',
  '现有工具链基线结果': 'nextBaselineData',
  '人工叠加清单、rule-only 输出、土地利用模拟/优化工具输出、耗时和错误记录。': 'nextBaselineMinimum',
  '证明 TWM 是否真正解决未满足需求，而不是技术堆砌。': 'nextBaselineUnlocks',
  '项目用地预审需要同时看项目范围、现状图斑、PBF、生态红线、用途分区、审批证据和规则条款；分散叠加容易漏掉冲突或证据缺口。': 'c1BusinessNeed',
  '真实或脱敏项目几何': 'c1ProjectGeometry',
  '权威 PBF/生态红线/用途管制边界版本': 'c1BoundaryVersions',
  '人工审查清单或历史规则命中': 'c1ReviewBaseline',
  '业务人员不仅要知道命中了哪条规则，还要知道证据来源、缺口、人工复核原因和为什么不能自动给审批结论。': 'c2BusinessNeed',
  '真实规则条款和版本': 'c2RuleVersions',
  '规则命中证据链接': 'c2EvidenceLinks',
  '复核任务与补正记录': 'c2ReviewCorrections',
  '审计抽查结论': 'c2AuditConclusion',
  '方案比选要解释候选方案为什么非法、证据不足、只能复核或可继续推进，而不只是给空间格局转移或单一优化分数。': 'c3BusinessNeed',
  '多期真实状态快照': 'c3TemporalSnapshots',
  '候选方案与实际处置结果': 'c3CandidatesOutcome',
  'action_type 与政策可行性标签': 'c3PolicyLabels',
  '方案审查意见和后续监管结果': 'c3ReviewOutcome',
  '自然资源一张图、村规划样例和地方业务字段常存在别名、值域和角色差异，手工映射容易造成语义错配。': 'c4BusinessNeed',
  '多个地区的一张图/村规划样例': 'c4RegionalSamples',
  '字段别名与值域标准': 'c4FieldStandards',
  '人工验收记录': 'c4AcceptanceRecords',
  '映射错误和修复日志': 'c4FixLogs',
  '最终处置结果': 'finalDispositionOutcome',
  '项目几何': 'experimentProjectGeometry',
  '权威边界版本': 'experimentBoundaryVersions',
  '候选方案': 'experimentCandidatePlan',
  'action feasibility labels': 'experimentActionFeasibilityLabels',
  '审查意见': 'experimentReviewOpinion',
  '字段别名': 'experimentFieldAliases',
  '审批/复核结果': 'experimentApprovalOutcomes',
  '人工基线输出': 'experimentManualBaseline',
  '操作员流程记录': 'experimentOperatorRecords',
  '任务耗时': 'experimentTaskTime',
  '补正/返工原因': 'experimentReworkReasons',
  '现有工具输出': 'experimentToolOutputs',
  '监管结果': 'experimentOversightOutcomes',
  '多地区一张图样例': 'experimentRegionalSamples',
  '值域标准': 'experimentValueStandards',
  '验收记录': 'experimentAcceptanceRecords',
};

const DYNAMIC_TWM_RUNTIME_KEYS: Record<string, string> = {
  '临界': 'boundaryThreshold',
  '贴边': 'boundaryContact',
  'TWM 的创新性不能靠列举模型组件来证明。当前应把每个主张绑定到真实业务问题、简单基线、数据门槛和可证伪指标；在生产历史和 baseline 对比缺失前，TWM 只能主张工程原型和审查脚手架，不能主张生产级 world model。': 'mentorAnswer',
  '该数据包用于测试和适配验证；not_for_production=true 时不得作为真实治理结论依据。': 'dataPackageBoundary',
  '触发规则判断': 'edgeTriggersRule',
  '涉及管控对象': 'edgeControlledObject',
  '支撑判断': 'edgeSupportsDecision',
  '形成复核任务': 'edgeCreatesReviewTask',
  '界面和汇报中使用“支撑材料/判断依据”，后端兼容字段仍可能叫 evidence。': 'supportMaterialTerminology',
  '状态 + 动作 -> 下一状态摘要、约束风险、收益和可信度。': 'simulatorTerminology',
  '在模拟器评价的动作或候选方案中，按约束、收益、风险和支撑材料完整度选择下一步。': 'plannerTerminology',
  '规则判断': 'ruleDecision',
  '支撑材料': 'supportMaterial',
};

const DYNAMIC_BASELINE_DETAIL_KEYS: Record<string, string> = {
  '脱敏后的稳定同案 ID，TWM 与 baseline 必须一致。': 'c1CaseIdDescription',
  '用不可逆匿名 ID 替代真实项目编号。': 'c1CaseIdSanitization',
  '由最终处置、复核结论或专家复标确认的硬约束冲突真值。': 'c1TruthDescription',
  '仅保留布尔标签，不导出敏感原文。': 'c1TruthSanitization',
  'TWM 或人工叠加清单是否在审查阶段发现该冲突。': 'c1DetectedDescription',
  '仅保留布尔标签。': 'booleanLabelOnly',
  '是否能追溯到图层版本、规则条款、截图或审查证据。': 'c1EvidenceDescription',
  '证据链接应指向内部脱敏索引，不导出原始文件路径。': 'c1EvidenceSanitization',
  '系统是否在证据不足或硬约束未解时仍给出推进性建议。': 'c1UnsupportedDescription',
  '仅保留布尔标签和脱敏原因。': 'c1UnsupportedSanitization',
  'TWM 在同案数据上召回率高于人工 baseline，并达到 claim threshold。': 'c1RecallSupports',
  'TWM 漏检率低于人工 baseline，并低于允许上限。': 'c1MissedSupports',
  'TWM 给出的风险能稳定连接到证据和规则版本。': 'c1EvidenceSupports',
  '从同一批历史项目抽取项目几何、权威边界版本、最终处置和人工叠加清单结果。': 'c1CollectSource',
  '先由业务或复核人员确定 ground_truth_conflict，再分别导出 TWM 和人工 baseline 检出结果。': 'c1CollectTruth',
  '保持 case_id 在两份 CSV 中一致；不一致的项目不得进入 baseline comparison。': 'c1CollectJoin',
  '先调用 baseline_export_validation_report，通过后再调用 baseline_evidence_pipeline_report。': 'c1CollectValidate',
  '脱敏后的稳定审查案件 ID。': 'c2CaseIdDescription',
  '不可逆匿名化；同一案件在两份 CSV 中保持一致。': 'c2CaseIdSanitization',
  '规则命中是否可追溯到证据包、图层版本和条款。': 'c2EvidenceDescription',
  '仅导出 evidence_uri 或证据索引，不导出原始涉密附件。': 'c2EvidenceSanitization',
  '是否在缺少证据、存在硬约束或需要人工复核时仍输出通过/推进建议。': 'c2UnsupportedDescription',
  '仅导出布尔值和脱敏处置类别。': 'c2UnsupportedSanitization',
  '系统是否创建或建议人工复核任务。': 'c2ReviewTaskDescription',
  '仅导出布尔标签。': 'c2BooleanLabelOnly',
  '复核任务是否被业务人员确认必要。': 'c2ReviewConfirmedDescription',
  '只导出确认结果，不导出人员姓名。': 'c2ReviewConfirmedSanitization',
  'TWM 证据链完整率高于 rule-only baseline。': 'c2AuditSupports',
  'TWM 更少在证据不足时给出推进性建议。': 'c2SafetySupports',
  'TWM 触发的复核任务更接近业务人员确认的必要复核。': 'c2ReviewPrecisionSupports',
  '锁定同一批审查案件和同一套规则版本，分别运行 TWM evidence gate 与 rule-only baseline。': 'c2CollectRun',
  '由业务复核人员确认 review_task_true_positive 和 audit_reviewer_disposition。': 'c2CollectConfirm',
  '确保 evidence_uri 指向可审计但已脱敏的证据索引。': 'c2CollectEvidence',
  '先通过 export validation，再把完整指标提交给 baseline comparison。': 'c2CollectValidate',
  '脱敏后的候选方案 ID，TWM 与 baseline 必须一致。': 'c3CandidateIdDescription',
  '不可逆匿名化；保留同一候选方案跨系统一致性。': 'c3CandidateIdSanitization',
  '候选方案排序，数值越小优先级越高。': 'c3RankDescription',
  '不包含真实地块或主体名称。': 'c3RankSanitization',
  '该候选方案是否进入推荐或 top-k 集合。': 'c3SelectedDescription',
  '候选方案在当前硬约束和证据条件下是否合法可行。': 'c3LegalDescription',
  '仅导出布尔标签和脱敏原因。': 'c3LegalSanitization',
  '相对人工/专家 oracle 的效用损失。': 'c3RegretDescription',
  '导出归一化差值，不导出敏感收益测算细节。': 'c3RegretSanitization',
  '非法、证据不足或 review-only 的脱敏原因。': 'c3RejectionDescription',
  '使用标准原因枚举，不导出原始审查意见全文。': 'c3RejectionSanitization',
  'TWM 对被阻断或只能复核的候选方案提供更完整原因。': 'c3RejectionSupports',
  'TWM 推荐集中的合法可行比例高于优化-only baseline。': 'c3LegalSupports',
  'TWM 相对人工 oracle 的平均 regret 更低。': 'c3RegretSupports',
  '为同一批候选方案保留稳定 candidate_id，并记录 action_type、排序、推荐集和人工/专家 oracle。': 'c3CollectCandidates',
  '用同一规则版本和同一证据截面分别运行 TWM action-conditioned triage 与模拟/优化-only baseline。': 'c3CollectRun',
  '把非法、证据不足和 review-only 原因归一到标准枚举，避免导出原始敏感审查文本。': 'c3CollectNormalize',
  '先确认 candidate_id overlap，再比较 top-k precision、reason coverage 和 regret。': 'c3CollectValidate',
};

const DYNAMIC_BASELINE_KEYS: Record<string, string> = {
  'Manual GIS overlay plus checklist review': 'manualLabel',
  '当前业务是否已能通过人工叠加和清单审查稳定解决硬约束冲突发现。': 'manualTests',
  'Whether the current workflow can already detect hard-constraint conflicts reliably through manual overlay and checklist review.': 'manualTests',
  '人工命中清单': 'manualHitList',
  'Manual hit list': 'manualHitList',
  '证据截图或图层记录': 'evidenceRecord',
  'Evidence screenshot or layer record': 'evidenceRecord',
  '复核意见': 'reviewOpinion',
  'Review opinion': 'reviewOpinion',
  '最终处置': 'finalDisposition',
  'Final disposition': 'finalDisposition',
  '如果人工流程已经高召回且审计完整，TWM 的增量价值必须体现在效率、证据完整性或复核负担上。': 'manualWhy',
  'If the manual workflow already has high recall and a complete audit trail, TWM must show incremental value in efficiency, evidence completeness, or review burden.': 'manualWhy',
  'Rule-only spatial compliance engine': 'ruleOnlyLabel',
  '规则叠加本身是否已经足以发现风险；TWM 是否额外提供证据门控和审计边界。': 'ruleOnlyTests',
  'Whether rule overlay alone already detects the risks, and whether TWM adds evidence gates and explicit audit boundaries.': 'ruleOnlyTests',
  '规则命中': 'ruleHits',
  'Rule hits': 'ruleHits',
  '严重级别': 'severity',
  Severity: 'severity',
  '空间关系': 'spatialRelation',
  'Spatial relation': 'spatialRelation',
  '条款引用': 'clauseCitation',
  'Clause citation': 'clauseCitation',
  '防止把 rule engine 能解决的问题包装成 world model 创新。': 'ruleOnlyWhy',
  'Prevents capabilities already solved by a rule engine from being presented as world-model innovation.': 'ruleOnlyWhy',
  'Land-use simulator or optimization-only ranking': 'simulationLabel',
  '传统模拟/优化能否完成方案排序；TWM 是否更好解释非法、证据不足和 review-only 方案。': 'simulationTests',
  'Whether conventional simulation or optimization can already rank plans, and whether TWM better explains illegal, under-evidenced, and review-only options.': 'simulationTests',
  '候选方案排序': 'candidateRanking',
  'Candidate ranking': 'candidateRanking',
  '空间变化预测或优化分数': 'spatialForecastScore',
  'Spatial-change forecast or optimization score': 'spatialForecastScore',
  '约束命中结果': 'constraintHitResults',
  'Constraint-hit results': 'constraintHitResults',
  '防止把已有土地利用模拟或优化能力重复实现为新方法。': 'simulationWhy',
  'Prevents existing land-use simulation or optimization capabilities from being reimplemented and claimed as a new method.': 'simulationWhy',
  'Ad hoc layer and field mapping': 'adHocLabel',
  '角色契约是否真正减少接入错误，而不是只增加配置复杂度。': 'adHocTests',
  'Whether role contracts genuinely reduce onboarding errors instead of only adding configuration complexity.': 'adHocTests',
  '字段映射表': 'fieldMappingTable',
  'Field-mapping table': 'fieldMappingTable',
  '值域检查结果': 'valueDomainChecks',
  'Value-domain check results': 'valueDomainChecks',
  '人工修复记录': 'manualCorrectionLog',
  'Manual correction log': 'manualCorrectionLog',
  '验证 TWM 状态契约对数据落地的实际收益。': 'adHocWhy',
  'Validates the practical data-onboarding benefit of the TWM state contract.': 'adHocWhy',
  '人工叠加清单、审查记录、证据截图/图层版本和最终处置结果的脱敏同案导出。': 'expectedManualSource',
  '规则引擎在同一批项目/图斑上的规则命中、空间关系、严重级别和条款引用导出。': 'expectedRuleSource',
  '同一批候选方案的模拟/优化排序、可行性、被拒原因和人工/专家排序结果。': 'expectedSimulationSource',
  'Manual GIS overlay plus checklist export': 'exportManualLabel',
  'Rule-only spatial compliance engine export': 'exportRuleOnlyLabel',
  'Land-use simulator or optimization-only ranking export': 'exportSimulationLabel',
  'C1 same-case hard-constraint conflict recall export': 'templateC1Label',
  'C2 evidence-gated audit defensibility export': 'templateC2Label',
  'C3 action-conditioned plan-option triage export': 'templateC3Label',
  '同一批历史项目中，TWM 是否比人工叠加清单更少漏掉永久基本农田、生态红线、用途管制等硬约束冲突？': 'questionC1',
  '同一批审查案件中，TWM 是否比 rule-only 空间合规引擎提供更完整、可复核、不过度承诺的审计证据？': 'questionC2',
  '同一批候选方案中，TWM 是否比模拟/优化-only 排序更能把合法可行、非法、证据不足和 review-only 方案区分清楚？': 'questionC3',
  '用于 same-case overlap；没有它不能证明两边比较的是同一批项目。': 'metricCaseOverlap',
  '作为 hard_constraint_conflict_recall 和 missed_blocking_conflict_rate 的分母。': 'metricTruthDenominator',
  '与 ground_truth_conflict 组合计算召回和漏检率。': 'metricRecall',
  '计算 evidence_link_completeness，防止只报风险不报依据。': 'metricEvidenceCompleteness',
  '作为证据门控的安全反例；C1/C2 都需要压低该值。': 'metricUnsupportedSafety',
  '用于 same-case audit comparison。': 'metricAuditOverlap',
  '计算 audit_trail_completeness。': 'metricAuditCompleteness',
  '计算 unsupported_recommendation_rate。': 'metricUnsupportedRate',
  '与 review_task_true_positive 组合计算 review_task_precision。': 'metricReviewPrecision',
  '为 review_task_precision 提供人工确认标签。': 'metricReviewLabel',
  'C3 same-case comparison 的主 join key。': 'metricCandidateJoin',
  '用于确定 top-k 方案集合。': 'metricTopKSet',
  '与 legal_feasible 组合计算 legal_feasible_topk_precision。': 'metricLegalPrecision',
  '判断推荐集是否包含非法或只能复核的方案。': 'metricIllegalReviewOnly',
  '越低说明排序越接近人工可接受方案。': 'metricOracleRegret',
  '计算 candidate_rejection_reason_coverage。': 'metricReasonCoverage',
  '100 行只是早期回放门槛；论文或试点结论还需要按地区、时间和冲突类型做 power/sensitivity analysis。': 'noteC1',
  '必须包含真实或脱敏复核结论；只有规则命中日志不足以证明审计可辩护性。': 'noteC2',
  'C3 必须有真实或脱敏 action feasibility labels 和人工/专家排序；只有优化分数不足以验证 action-conditioned dynamics。': 'noteC3',
  'Replace real project, parcel, candidate, organization and person identifiers with stable anonymous IDs.': 'sanitizeIds',
  'Keep the same anonymous join key across TWM and baseline exports; otherwise the comparison is invalid.': 'sanitizeJoinKey',
  'Use evidence_uri as an internal sanitized evidence index instead of raw file paths or sensitive text.': 'sanitizeEvidenceUri',
  'Set not_for_production=true unless the export has passed internal data-governance release review.': 'sanitizeProductionFlag',
  'Preserve rule_version, boundary_version and source_system because metric results are not interpretable without lineage.': 'sanitizeLineage',
};

const DYNAMIC_ROADMAP_KEYS: Record<string, string> = {
  'Current TWM is a rigorous prototype: demo-complete and engineering-reviewable, but production, prediction and causal claims remain review-only until real observed history, policy labels and same-case baselines pass.': 'claimBoundary',
  'Natural resources demo closure': 'phaseDemo',
  'Auditable TWM engineering scaffold': 'phaseEngineering',
  'Data foundation productization': 'phaseData',
  'Trusted pilot validation': 'phasePilot',
  'Production and air-gapped deployment': 'phaseProduction',
  production_observed_history: 'blockerObservedHistory',
  policy_action_history: 'blockerPolicyHistory',
  service_decomposition: 'blockerServiceDecomposition',
  full_flus_and_holdout_baselines: 'blockerBaselines',
  'one pilot region with multi-year observed approval/review history': 'targetObservedHistory',
  'authoritative policy/action feasibility labels': 'targetPolicyLabels',
  'large facade service': 'currentFacade',
  'state, dynamics, calibration, planner, evidence/audit and readiness services': 'targetServices',
  'public benchmark and simplified/direct adapters': 'currentBaselines',
  'same-case full FLUS/GeoSOS baseline plus cross-region/cross-year holdout': 'targetBaselines',
  'secure real or sanitized observed history and policy/action labels for one pilot region': 'actionSecureHistory',
  'freeze and manually accept the current natural-resources demo workflow': 'actionFreezeDemo',
  'split the TWM facade service along state/dynamics/calibration/planner/evidence boundaries': 'actionSplitService',
  'finish vector tiles or chunked preview, production CRS conversion ETL, and production lineage ingestion templates': 'actionFinishData',
};

const DYNAMIC_ROADMAP_DETAIL_KEYS: Record<string, string> = {
  'Chinese-first TWM frontend tabs are implemented': 'frontendImplemented',
  'data foundation map preview and bbox-aligned overview map are implemented': 'mapPreviewImplemented',
  'automated E2E evidence exists for the demo workflow': 'e2eEvidence',
  'manual acceptance and demo freeze before external presentation': 'manualAcceptance',
  'state/rule/evidence/audit pipeline': 'auditPipeline',
  'forecast, counterfactual rollout, validation ladder and beam planning consumer': 'forecastConsumer',
  'trainable dynamics candidates and observational causal calibration reports': 'dynamicsReports',
  'dynamics model registry release gate report is implemented': 'registryGate',
  'persistent model registry/version rollback is implemented in service, repository, API and Agent tools': 'persistentRegistry',
  'state snapshot lakehouse manifest maps TWM state, rule, evidence and registry layers to Iceberg/GeoParquet/Parquet storage': 'lakehouseManifest',
  'state snapshot lakehouse materializer writes local Parquet/GeoParquet-compatible artifacts through service, API and Agent tools': 'lakehouseMaterializer',
  'Iceberg/Sedona publish plan generates table DDL, artifact publish specs and geohash spatial index jobs': 'icebergPublishPlan',
  'Spark executor contract validates Iceberg snapshot ids, row counts and Sedona spatial index job results': 'sparkExecutorContract',
  'spark-submit execution bundle writes a production Spark/Sedona/Iceberg plan file and command package': 'sparkExecutionBundle',
  'service decomposition': 'serviceDecomposition',
  'credentialed production Spark run and external Iceberg audit acceptance': 'sparkAuditAcceptance',
  'demo dataset catalog, CRS diagnostics and map overlay readiness are exposed': 'catalogExposed',
  'full GeoJSON preview is available for the current demo scale': 'geojsonPreview',
  'lineage and field drilldown reports are exposed through API, tools and frontend': 'lineageExposed',
  'CRS remediation plan is exposed through API, tools and frontend': 'crsPlanExposed',
  'authoritative production data templates are exposed through API, tools and frontend': 'templatesExposed',
  'vector tiles or server-side chunking': 'vectorTiles',
  'production CRS conversion ETL': 'productionCrs',
  'production lineage ingestion templates': 'lineageTemplates',
  'public Dynamic World and GeoSOS/FLUS benchmark evidence exists': 'benchmarkEvidence',
  'claim ladder and baseline comparison contracts exist': 'claimContracts',
  'real observed approval/review history': 'realHistory',
  'policy/action feasibility labels': 'policyLabels',
  'same-case baseline and holdout evaluation': 'sameCaseEvaluation',
  'air-gapped deployment strategy exists': 'airGapStrategy',
  'offline deployment package': 'offlinePackage',
  'permissioned audit trail': 'permissionedAudit',
  'model/rule/version comparison': 'versionComparison',
  'sanitized diagnostic export': 'diagnosticExport',
};

const DYNAMIC_PILOT_KEYS: Record<string, string> = {
  'Data foundation': 'dimensionData',
  'Policy rules': 'dimensionPolicy',
  Simulator: 'dimensionSimulator',
  Planner: 'dimensionPlanner',
  'Evidence and audit': 'dimensionAudit',
  'keep demo and synthetic fixtures explicitly marked not-for-production': 'dataKeepMarked',
  'add boundary-case fixture rows for CRS, geometry validity and layer role binding': 'dataBoundaryCases',
  'authoritative rule clause to executable rule acceptance records': 'policyAcceptanceMissing',
  'positive, negative and boundary fixtures for each production rule code': 'policyFixturesMissing',
  'add one pass, one violation and one boundary-touching feature set per hard-constraint rule': 'policyAddCases',
  'add stale/re-derived spatial-policy-rule fixtures linked to standard versions': 'policyAddVersionedFixtures',
  'real temporal holdout from observed approval/review history': 'simulatorTemporalMissing',
  'policy/action feasibility labels for action-mask validation': 'simulatorLabelsMissing',
  'same-case full FLUS/GeoSOS or manual baseline evidence': 'simulatorBaselineMissing',
  'extend synthetic false-allow and false-block cases without changing production gate status': 'simulatorStressCases',
  'add same-case baseline export fixtures with train/holdout split metadata': 'simulatorAddBaselineFixtures',
  'real candidate-plan source and human review outcomes': 'plannerCandidatesMissing',
  'planner regret and legal-feasible top-k metrics against same-case baselines': 'plannerMetricsMissing',
  'add candidate bundles where the highest utility candidate is infeasible and must be blocked': 'plannerAddBlockedBundle',
  'add baseline replay fixtures for manual GIS, rule-only and optimizer outputs': 'plannerAddReplayFixtures',
  'production human-review completion evidence': 'auditCompletionMissing',
  'row-level evidence material lineage from authoritative systems': 'auditLineageMissing',
  'add evidence-component fixtures for missing-document, conflicting-source and resolved-review cases': 'auditAddEvidenceFixtures',
  'add audit export fixtures that prove raw geometries remain excluded from sanitized bundles': 'auditAddExportFixtures',
  same_case_baseline_holdout_evidence: 'productionBaselineMissing',
  'prepare authoritative observed-history intake template for custodian-provided rows': 'productionPrepareHistory',
  'prepare authoritative policy/action feasibility template with allowed and blocked examples': 'productionPrepareLabels',
};

const DYNAMIC_RULE_COVERAGE_KEYS: Record<string, string> = {
  '永久基本农田占用审查': 'farmlandRule',
  '生态保护红线触碰审查': 'ecoRule',
  '用途管制分区一致性审查': 'planningRule',
  '城镇开发边界内外审查': 'urbanRule',
  positive_violation: 'positiveViolation',
  negative_pass: 'negativePass',
  boundary_case: 'boundaryCase',
};

function statusText(value: any, fallback = '-') {
  const text = String(value || '').trim();
  if (!text) return fallback;
  const key = text.toLowerCase();
  const translationKey = `territoryWorldModel.status.${key}`;
  if (key === 'monitor') return i18n.t('territoryWorldModelDynamicPilotExtras.statusMonitor');
  if (DYNAMIC_TWM_STATUS_KEYS[key]) return i18n.t(`territoryWorldModelDynamicStatusExtras.${DYNAMIC_TWM_STATUS_KEYS[key]}`);
  return i18n.exists(translationKey) ? i18n.t(translationKey) : text;
}

function yesNo(value: any) {
  return i18n.t(`territoryWorldModel.common.${value ? 'yes' : 'no'}`);
}

function mapOverlayReadinessText(value?: string) {
  const normalized = String(value || '').toLowerCase();
  if (normalized === 'ready') return i18n.t('territoryWorldModel.dataBrowser.overlayReady');
  if (normalized === 'blocked') return i18n.t('territoryWorldModel.dataBrowser.crsConversionRequired');
  if (normalized === 'empty') return i18n.t('territoryWorldModel.status.no_spatial_layers');
  return statusText(value, i18n.t('territoryWorldModel.dataBrowser.notChecked'));
}

function crsDiagnosticText(value?: string) {
  const normalized = String(value || '').toLowerCase();
  if (normalized === 'wgs84_lonlat') return i18n.t('territoryWorldModel.dataBrowser.wgs84Coordinates');
  if (normalized === 'projected_or_non_wgs84') return i18n.t('territoryWorldModel.dataBrowser.crsConversionRequired');
  if (normalized === 'lonlat_degrees') return i18n.t('territoryWorldModel.dataBrowser.lonLatCoordinates');
  if (normalized === 'projected_or_large_numeric') return i18n.t('territoryWorldModel.dataBrowser.projectedCoordinates');
  return statusText(value, i18n.t('territoryWorldModel.dataBrowser.notChecked'));
}

function displayText(value: any, fallback = '-') {
  const text = String(value || '').trim();
  if (!text) return fallback;
  const observedHistoryShortfall = text.match(/^生产可用观察历史行数仍不足：(\d+)$/);
  if (observedHistoryShortfall) {
    return i18n.t('territoryWorldModelDynamicDataGovernanceExtras.observedHistoryShortfall', { count: Number(observedHistoryShortfall[1]) });
  }
  const policyHistoryShortfall = text.match(/^生产政策动作历史仍不足：(\d+)$/);
  if (policyHistoryShortfall) {
    return i18n.t('territoryWorldModelDynamicDataGovernanceExtras.policyHistoryShortfall', { count: Number(policyHistoryShortfall[1]) });
  }
  const lineageCounts = text.match(/^(\d+) not-for-production records; (\d+) synthetic records$/);
  if (lineageCounts) {
    return i18n.t('territoryWorldModelDynamicLineageExtras.recordCounts', {
      nonProduction: Number(lineageCounts[1]),
      synthetic: Number(lineageCounts[2]),
    });
  }
  const pilotRows = text.match(/^(production_observed_history_rows|production_policy_history_rows)=(\d+)$/);
  if (pilotRows) {
    const key = pilotRows[1] === 'production_observed_history_rows' ? 'observedRows' : 'policyRows';
    return i18n.t(`territoryWorldModelDynamicPilotExtras.${key}`, { count: Number(pilotRows[2]) });
  }
  const statusKey = `territoryWorldModel.status.${text.toLowerCase()}`;
  if (i18n.exists(statusKey)) return i18n.t(statusKey);
  const sourceText = SOURCE_DISPLAY_LABELS[text] || text;
  const dynamicKey = DYNAMIC_LABEL_KEYS[sourceText];
  if (dynamicKey) {
    const namespace = /^(experimentCrossRegion|experimentDecision)/.test(dynamicKey)
      ? 'territoryWorldModelDynamicResearchExperimentDetails'
      : dynamicKey.startsWith('experiment')
        ? 'territoryWorldModelDynamicResearchExtras'
        : 'territoryWorldModel.dynamicResearch';
    return i18n.t(`${namespace}.${dynamicKey}`);
  }
  const dataFoundationKey = DYNAMIC_DATA_FOUNDATION_KEYS[text] || DYNAMIC_DATA_FOUNDATION_KEYS[sourceText];
  if (dataFoundationKey) {
    const namespace = dataFoundationKey.startsWith('fit')
      ? 'territoryWorldModelDynamicDataFoundationExtras'
      : 'territoryWorldModel.dynamicDataFoundation';
    return i18n.t(`${namespace}.${dataFoundationKey}`);
  }
  const dataFoundationDetailKey = DYNAMIC_DATA_FOUNDATION_DETAIL_KEYS[text] || DYNAMIC_DATA_FOUNDATION_DETAIL_KEYS[sourceText];
  if (dataFoundationDetailKey) return i18n.t(`territoryWorldModelDynamicDataFoundationDetails.${dataFoundationDetailKey}`);
  const dataGovernanceKey = DYNAMIC_DATA_GOVERNANCE_KEYS[text] || DYNAMIC_DATA_GOVERNANCE_KEYS[sourceText];
  if (dataGovernanceKey) return i18n.t(`territoryWorldModelDynamicDataGovernanceExtras.${dataGovernanceKey}`);
  const authoritativeTemplateKey = DYNAMIC_AUTHORITATIVE_TEMPLATE_KEYS[text] || DYNAMIC_AUTHORITATIVE_TEMPLATE_KEYS[sourceText];
  if (authoritativeTemplateKey) return i18n.t(`territoryWorldModelDynamicAuthoritativeTemplateExtras.${authoritativeTemplateKey}`);
  const crsWorkflowKey = DYNAMIC_CRS_WORKFLOW_KEYS[text] || DYNAMIC_CRS_WORKFLOW_KEYS[sourceText];
  if (crsWorkflowKey) {
    const namespace = crsWorkflowKey === 'claimBoundary'
      ? 'territoryWorldModelDynamicCrsBoundaryExtras'
      : 'territoryWorldModelDynamicCrsWorkflowExtras';
    return i18n.t(`${namespace}.${crsWorkflowKey}`);
  }
  const lineageKey = DYNAMIC_LINEAGE_KEYS[text] || DYNAMIC_LINEAGE_KEYS[sourceText];
  if (lineageKey) return i18n.t(`territoryWorldModelDynamicLineageExtras.${lineageKey}`);
  const roadmapKey = DYNAMIC_ROADMAP_KEYS[sourceText];
  if (roadmapKey) return i18n.t(`territoryWorldModelDynamicRoadmapExtras.${roadmapKey}`);
  const roadmapDetailKey = DYNAMIC_ROADMAP_DETAIL_KEYS[sourceText];
  if (roadmapDetailKey) return i18n.t(`territoryWorldModelDynamicRoadmapDetails.${roadmapDetailKey}`);
  const pilotKey = DYNAMIC_PILOT_KEYS[sourceText];
  if (pilotKey) return i18n.t(`territoryWorldModelDynamicPilotExtras.${pilotKey}`);
  const ruleCoverageKey = DYNAMIC_RULE_COVERAGE_KEYS[text] || DYNAMIC_RULE_COVERAGE_KEYS[sourceText];
  if (ruleCoverageKey) return i18n.t(`territoryWorldModelDynamicRuleCoverageExtras.${ruleCoverageKey}`);
  const claimKey = DYNAMIC_CLAIM_KEYS[sourceText];
  if (claimKey) return i18n.t(`territoryWorldModelDynamicClaimExtras.${claimKey}`);
  const researchDataKey = DYNAMIC_RESEARCH_DATA_KEYS[text] || DYNAMIC_RESEARCH_DATA_KEYS[sourceText];
  if (researchDataKey) return i18n.t(`territoryWorldModelDynamicResearchDataExtras.${researchDataKey}`);
  const runtimeKey = DYNAMIC_TWM_RUNTIME_KEYS[text] || DYNAMIC_TWM_RUNTIME_KEYS[sourceText];
  if (runtimeKey) return i18n.t(`territoryWorldModelDynamicRuntimeExtras.${runtimeKey}`);
  const baselineDetailKey = DYNAMIC_BASELINE_DETAIL_KEYS[text] || DYNAMIC_BASELINE_DETAIL_KEYS[sourceText];
  if (baselineDetailKey) return i18n.t(`territoryWorldModelDynamicBaselineDetailExtras.${baselineDetailKey}`);
  const baselineKey = DYNAMIC_BASELINE_KEYS[text] || DYNAMIC_BASELINE_KEYS[sourceText];
  if (baselineKey) {
    const namespace = /^(template|export)/.test(baselineKey)
      ? 'territoryWorldModelDynamicBaselineLabelExtras'
      : /^(question|metric|note|sanitize)/.test(baselineKey)
        ? 'territoryWorldModelDynamicBaselineTemplateExtras'
        : 'territoryWorldModelDynamicBaselineExtras';
    return i18n.t(`${namespace}.${baselineKey}`);
  }
  const localized = getLocale() === 'zh-CN' ? (DISPLAY_LABELS[sourceText] || sourceText) : sourceText;
  return localized
    .replace(/synthetic\/not-for-production/g, i18n.t('territoryWorldModel.runtime.replacements.syntheticNonProduction'))
    .replace(/not-for-production/g, i18n.t('territoryWorldModel.runtime.replacements.nonProduction'))
    .replace(/rule-only/g, i18n.t('territoryWorldModel.runtime.replacements.ruleOnly'))
    .replace(/manual GIS overlay/g, i18n.t('territoryWorldModel.runtime.replacements.manualGisOverlay'))
    .replace(/optimization-only/g, i18n.t('territoryWorldModel.runtime.replacements.optimizationOnly'))
    .replace(/beam ranking/g, i18n.t('territoryWorldModel.runtime.replacements.beamRanking'))
    .replace(/action-mask/g, i18n.t('territoryWorldModel.runtime.replacements.actionMask'));
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

function compactList(values: any[] | undefined, fallback = i18n.t('territoryWorldModel.common.none')) {
  const rows = (values || []).filter(Boolean).map(String);
  return rows.length ? rows.slice(0, 4).join(', ') : fallback;
}

function compactDisplayList(values: any[] | undefined, fallback = i18n.t('territoryWorldModel.common.none')) {
  const rows = (values || []).filter(Boolean).map(item => displayText(item));
  return rows.length ? rows.slice(0, 4).join(', ') : fallback;
}

function compactBbox(value: any, fallback = i18n.t('territoryWorldModel.dataBrowser.noExtent')) {
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
  if (value === null || value === undefined || value === '') return i18n.t('territoryWorldModel.dataBrowser.emptyValue');
  if (typeof value === 'boolean') return yesNo(value);
  if (typeof value === 'number') return Number.isInteger(value) ? fmt(value, 0) : String(Number(value.toFixed(3)));
  const text = String(value);
  return text.length > 18 ? `${text.slice(0, 18)}...` : text;
}

function compactPropertyFieldNames(fields?: TwmDataFoundationPropertyField[], totalCount?: number) {
  const names = (fields || []).map(field => field.name).filter(Boolean);
  if (!names.length) return i18n.t('territoryWorldModel.dataBrowser.noFields');
  const priority = TWM_PROPERTY_FIELD_PRIORITY.filter(name => names.includes(name));
  const ranked = [...priority, ...names.filter(name => !priority.includes(name))].slice(0, 5);
  const count = Number(totalCount || names.length);
  return i18n.t('territoryWorldModel.dataBrowser.fieldSummary', {
    count: fmt(count, 0),
    fields: ranked.join(', '),
    more: count > ranked.length ? i18n.t('territoryWorldModel.dataBrowser.andMore') : '',
  });
}

function compactSampleProperties(sample?: Record<string, any>) {
  const source = sample || {};
  const entries = Object.entries(source);
  if (!entries.length) return i18n.t('territoryWorldModel.dataBrowser.noSampleProperties');
  const priorityEntries = TWM_PROPERTY_FIELD_PRIORITY
    .filter(name => Object.prototype.hasOwnProperty.call(source, name))
    .map(name => [name, source[name]] as [string, any]);
  const ranked = [
    ...priorityEntries,
    ...entries.filter(([name]) => !priorityEntries.some(([priorityName]) => priorityName === name)),
  ].slice(0, 2);
  return ranked.map(([name, value]) => `${name}=${compactSamplePropertyValue(value)}`).join('；');
}

function stateGraphNodeLabel(node: TwmStateGraphNode) {
  return displayText(node.label || node.role || node.kind || node.id);
}

function stateGraphNodeClass(node: TwmStateGraphNode) {
  const kind = String(node.kind || '');
  const role = String(node.role || '');
  if (kind === 'rule_hit') return 'risk';
  if (kind === 'support_material') return 'support';
  if (kind === 'review_task') return 'review';
  if (role.includes('farmland') || role.includes('eco') || role.includes('constraint')) return 'constraint';
  if (role.includes('project')) return 'project';
  if (role.includes('candidate') || role.includes('scenario')) return 'plan';
  return 'object';
}

function stateGraphSummaryText(node: TwmStateGraphNode) {
  const summary = node.summary;
  if (!summary) return displayText(node.role || node.kind || i18n.t('territoryWorldModel.runtime.node'));
  if (typeof summary === 'string') return displayText(summary);
  const entries = Object.entries(summary).slice(0, 3);
  if (!entries.length) return displayText(node.role || node.kind || i18n.t('territoryWorldModel.runtime.node'));
  return entries.map(([key, value]) => `${displayText(key)}=${compactSamplePropertyValue(value)}`).join(i18n.t('territoryWorldModel.common.listSeparator'));
}

function stateGraphLayout(nodes: TwmStateGraphNode[], edges: TwmStateGraphEdge[]) {
  const width = 720;
  const columns = [
    ['project', 'parcel', 'permanent_basic_farmland', 'ecological', 'planning'],
    ['rule_hit'],
    ['support_material', 'review_task'],
    ['candidate', 'scenario'],
  ];
  const byColumn = columns.map(() => [] as TwmStateGraphNode[]);
  const fallback: TwmStateGraphNode[] = [];
  nodes.forEach(node => {
    const role = String(node.role || node.kind || '').toLowerCase();
    const idx = columns.findIndex(group => group.some(item => role.includes(item)));
    if (idx >= 0) byColumn[idx].push(node);
    else fallback.push(node);
  });
  fallback.forEach((node, idx) => byColumn[idx % Math.max(1, byColumn.length)].push(node));
  const maxColumnCount = Math.max(1, ...byColumn.map(items => items.length));
  const height = Math.max(300, 96 + maxColumnCount * 52);
  const positioned = new Map<string, TwmStateGraphNode & { x: number; y: number }>();
  byColumn.forEach((items, columnIdx) => {
    const x = 78 + columnIdx * ((width - 156) / Math.max(1, byColumn.length - 1));
    const step = height / (items.length + 1);
    items.forEach((node, idx) => positioned.set(node.id, { ...node, x, y: step * (idx + 1) }));
  });
  return {
    width,
    height,
    nodes: Array.from(positioned.values()),
    edges: edges
      .map(edge => ({ ...edge, sourceNode: positioned.get(edge.source), targetNode: positioned.get(edge.target) }))
      .filter(edge => edge.sourceNode && edge.targetNode),
  };
}

export default function TerritoryWorldModelTab() {
  const { t, i18n: i18nInstance } = useTranslation();
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
  const [activeSubTab, setActiveSubTab] = useState<TwmSubTab>('briefing');
  const [selectedDataPackageId, setSelectedDataPackageId] = useState('twm_bishan_multi_admin_eval');
  const [dataMapPreviewLoading, setDataMapPreviewLoading] = useState(false);
  const [dataMapPreviewSummary, setDataMapPreviewSummary] = useState('');
  const [dataMapPreview, setDataMapPreview] = useState<TwmDataFoundationMapPreview | null>(null);
  const [visibleDataMapLayerNames, setVisibleDataMapLayerNames] = useState<string[]>([]);
  const [roadmapStatus, setRoadmapStatus] = useState<TwmRoadmapStatusReport | null>(null);
  const [pilotReadinessMatrix, setPilotReadinessMatrix] = useState<TwmPilotReadinessMatrix | null>(null);
  const [ruleFixtureCoverageMatrix, setRuleFixtureCoverageMatrix] = useState<TwmRuleFixtureCoverageMatrix | null>(null);
  const [selectedLayerDetail, setSelectedLayerDetail] = useState<TwmDataFoundationLayerDetail | null>(null);
  const [selectedLayerDetailPath, setSelectedLayerDetailPath] = useState('');
  const [dataLineage, setDataLineage] = useState<TwmDataFoundationLineageReport | null>(null);
  const [crsRemediationPlan, setCrsRemediationPlan] = useState<TwmDataFoundationCrsRemediationPlan | null>(null);
  const [authoritativeTemplates, setAuthoritativeTemplates] = useState<TwmDataFoundationAuthoritativeTemplates | null>(null);

  const [projectName, setProjectName] = useState(() => t('territoryWorldModel.workspace.defaultProjectName'));
  const [regionCode, setRegionCode] = useState(DEFAULT_DEMO_BUNDLE.regionCode);
  const [bundleDir, setBundleDir] = useState(DEFAULT_DEMO_BUNDLE.bundleDir);
  const [optimizationDir, setOptimizationDir] = useState(DEFAULT_DEMO_BUNDLE.optimizationDir);
  const [stateLabel, setStateLabel] = useState(() => t(`territoryWorldModel.workspace.presets.${DEFAULT_DEMO_BUNDLE.key}`));
  const [includeAuxiliary, setIncludeAuxiliary] = useState(true);
  const [actionType, setActionType] = useState('protect');
  const [targetRole, setTargetRole] = useState('project');
  const [scenario, setScenario] = useState(FALLBACK_BUSINESS_SCENARIOS[0].default_scenario || FALLBACK_BUSINESS_SCENARIOS[0].id);
  const [evidenceCoverage, setEvidenceCoverage] = useState(FALLBACK_BUSINESS_SCENARIOS[0].default_evidence_coverage || 0.78);
  const [horizon, setHorizon] = useState(FALLBACK_BUSINESS_SCENARIOS[0].default_horizon || 3);

  const [stateDetail, setStateDetail] = useState<any | null>(null);
  const [stateGraph, setStateGraph] = useState<TwmStateGraphReport | null>(null);
  const [stateGraphFocusNodeId, setStateGraphFocusNodeId] = useState('');
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
  const businessScenarioText = (item: TwmBusinessScenario, field: 'label' | 'decisionQuestion' | 'operatorGoal') => {
    const translationKey = `territoryWorldModel.businessScenarios.${item.id}.${field}`;
    const fallback = field === 'label' ? item.label : field === 'decisionQuestion' ? item.decision_question : item.operator_goal;
    return i18nInstance.exists(translationKey) ? t(translationKey) : (fallback || '-');
  };
  const businessScenarioList = (item: TwmBusinessScenario, field: 'requiredEvidence' | 'outputs' | 'guardrails') => {
    const translationKey = `territoryWorldModel.businessScenarios.${item.id}.${field}`;
    const translated = i18nInstance.exists(translationKey) ? t(translationKey, { returnObjects: true }) : null;
    const fallback = field === 'requiredEvidence' ? item.required_evidence : field === 'outputs' ? item.decision_outputs : item.guardrails;
    return Array.isArray(translated) ? translated.map(String) : (fallback || []);
  };
  const selectedProject = projects.find(item => item.id === selectedProjectId) || null;
  const selectedState = states.find(item => item.id === selectedStateId) || null;
  const latestResult = stateGraph || beamResult || validationResult || forecastResult || auditResult || ruleResult || stateDetail;
  const dataReadiness = dataFoundation.landing_readiness || FALLBACK_DATA_FOUNDATION.landing_readiness || {};
  const validationSnapshot = dataFoundation.validation_snapshot || FALLBACK_DATA_FOUNDATION.validation_snapshot || {};
  const dataPackages = dataFoundation.datasets || FALLBACK_DATA_FOUNDATION.datasets || [];
  const selectedDataPackage = (
    dataPackages.find(item => item.id === selectedDataPackageId) || dataPackages[0] || null
  );
  const selectedSpatialLayerCatalog = selectedDataPackage?.spatial_layer_catalog || [];
  const roadmapPhases = roadmapStatus?.phases || [];
  const pilotReadinessDimensions = pilotReadinessMatrix?.dimensions || [];
  const ruleFixtureRows = ruleFixtureCoverageMatrix?.rules || [];
  const roadmapCompletion = roadmapPhases.length
    ? roadmapPhases.reduce((sum, phase) => sum + clampRatio(phase.completion_ratio, 0), 0) / roadmapPhases.length
    : 0;
  const roadmapCompleteCount = roadmapPhases.filter(phase => ['complete', 'completed'].includes(String(phase.status || '').toLowerCase())).length;
  const roadmapProgressCount = roadmapPhases.filter(phase => ['partial', 'candidate', 'open'].includes(String(phase.status || '').toLowerCase())).length;
  const roadmapBlockedCount = roadmapPhases.filter(phase => String(phase.status || '').toLowerCase() === 'blocked').length;
  const visibleLayerDetail = (
    selectedLayerDetail?.dataset_id && selectedLayerDetail.dataset_id === selectedDataPackage?.id
      ? selectedLayerDetail
      : null
  );
  const visibleDataLineage = (
    dataLineage?.dataset_id && dataLineage.dataset_id === selectedDataPackage?.id
      ? dataLineage
      : null
  );
  const visibleCrsRemediationPlan = (
    crsRemediationPlan?.dataset_id && crsRemediationPlan.dataset_id === selectedDataPackage?.id
      ? crsRemediationPlan
      : null
  );
  const claimDataGate = claimMatrix.current_data_gate || FALLBACK_CLAIM_MATRIX.current_data_gate || {};
  const readiness = useMemo(() => {
    const repository = status?.repository || {};
    return [
      { id: 'projects', label: t('territoryWorldModel.kpi.projects'), value: repository.project_count ?? projects.length },
      { id: 'states', label: t('territoryWorldModel.kpi.states'), value: repository.state_version_count ?? states.length },
      { id: 'rules', label: t('territoryWorldModel.kpi.rules'), value: repository.policy_rule_count ?? '-' },
      { id: 'hits', label: t('territoryWorldModel.kpi.hits'), value: repository.rule_hit_count ?? hits.length },
    ];
  }, [status, projects.length, states.length, hits.length, t, i18nInstance.language]);

  const withRun = async <T,>(key: RunKey, task: () => Promise<T>): Promise<T | null> => {
    setRunning(key);
    setError('');
    try {
      return await task();
    } catch (e: any) {
      setError(e?.message || t('territoryWorldModel.errors.requestFailed'));
      return null;
    } finally {
      setRunning(null);
    }
  };

  const api = async (url: string, init?: RequestInit) => {
    const headers = {
      Accept: 'application/json',
      ...getLocaleHeaders(),
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
        ? t('territoryWorldModel.errors.htmlResponse')
        : t('territoryWorldModel.errors.nonJsonResponse', { detail: previewText(text) || contentType || 'empty response' });
      throw new Error(t('territoryWorldModel.errors.invalidApiResponse', { url, detail }));
    }
    let data: any = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch (e: any) {
      throw new Error(t('territoryWorldModel.errors.jsonParseFailed', { url, message: e?.message || 'invalid JSON' }));
    }
    if (!resp.ok || data.error) throw new Error(parseError(data, t('territoryWorldModel.errors.requestUrlFailed', { url })));
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

  const loadRoadmapStatus = async () => {
    await withRun('roadmapStatus', async () => {
      const data = await api('/api/twm/roadmap-status');
      if (data?.phases) setRoadmapStatus(data);
      return data;
    });
  };

  const loadPilotReadinessMatrix = async () => {
    await withRun('pilotReadiness', async () => {
      const data = await api('/api/twm/pilot-readiness-matrix');
      if (data?.dimensions) setPilotReadinessMatrix(data);
      return data;
    });
  };

  const loadRuleFixtureCoverageMatrix = async () => {
    await withRun('ruleFixtureCoverage', async () => {
      const data = await api('/api/twm/rule-fixture-coverage-matrix');
      if (data?.rules) setRuleFixtureCoverageMatrix(data);
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
      setSelectedStateId((current: string) => {
        if (current && rows.some(item => item.id === current)) return current;
        return rows[0]?.id || '';
      });
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
    await loadRoadmapStatus();
    await loadPilotReadinessMatrix();
    await loadRuleFixtureCoverageMatrix();
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
    if (!selectedStateId) {
      setStateDetail(null);
      setHits([]);
      setStateGraph(null);
      setStateGraphFocusNodeId('');
      return;
    }
    const stateSummary = states.find(item => item.id === selectedStateId);
    if (stateSummary) {
      setStateDetail((current: any | null) => (
        current?.state_version?.id === selectedStateId
          ? current
          : { state_version: stateSummary, hits: [], evidence_items: [], review_tasks: [] }
      ));
      setHits([]);
      setStateGraph(null);
      setStateGraphFocusNodeId('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedStateId, states]);

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
    setStateLabel(t(`territoryWorldModel.workspace.presets.${preset.key}`));
    setProjectName(t('territoryWorldModel.workspace.projectNameFromPreset', { name: t(`territoryWorldModel.workspace.presets.${preset.key}`) }));
  };

  const applyBusinessScenario = (scenarioId: string) => {
    const item = businessScenarios.find(entry => entry.id === scenarioId) || FALLBACK_BUSINESS_SCENARIOS[0];
    setSelectedBusinessScenarioId(item.id);
    setProjectName(t('territoryWorldModel.workspace.projectNameFromScenario', { name: businessScenarioText(item, 'label') }));
    setActionType(item.default_action_type || 'inspect');
    setTargetRole(item.default_target_role || 'project');
    setScenario(item.default_scenario || item.id);
    setEvidenceCoverage(clampRatio(item.default_evidence_coverage, 0.72));
    setHorizon(Math.max(1, Math.min(12, Number(item.default_horizon || 3))));
  };

  const selectDataPackage = (datasetId: string) => {
    setSelectedDataPackageId(datasetId);
    setDataMapPreview(null);
    setVisibleDataMapLayerNames([]);
    setDataMapPreviewSummary('');
    setSelectedLayerDetail(null);
    setSelectedLayerDetailPath('');
    setDataLineage(null);
    setCrsRemediationPlan(null);
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

  const syncStateGraphNodeToMap = (node: TwmStateGraphNode) => {
    const stage = (node.map_stage && node.map_stage !== 'none' ? node.map_stage : 'locate') as TwmMapStage;
    const bbox = Array.isArray(node.bbox) ? node.bbox.map(Number) : [];
    if (bbox.length === 4 && bbox.every(Number.isFinite)) {
      setMapStage(stage);
      const [minLng, minLat, maxLng, maxLat] = bbox;
      const handler = (window as any).__handleMapUpdate;
      if (typeof handler === 'function') {
        handler({
          center: [(minLat + maxLat) / 2, (minLng + maxLng) / 2],
          zoom: 13,
          layers: [
            ...twmMapLayers(stage),
            {
              name: t('territoryWorldModel.runtime.stateGraphLayer', { name: stateGraphNodeLabel(node) }),
              type: 'polygon',
              geojsonData: featureCollection([
                twmMapFeature(
                  `state_graph_${node.id}`,
                  stateGraphNodeLabel(node),
                  displayText(node.role || node.kind),
                  bboxRing(minLng, minLat, maxLng, maxLat),
                  { _twm_description: stateGraphSummaryText(node) },
                ),
              ]),
              style: { color: '#0f766e', fillColor: '#14b8a6', fillOpacity: 0.28, weight: 3 },
              tooltip_fields: ['_twm_description'],
              tooltip_labels: { _twm_description: t('territoryWorldModel.runtime.description') },
            },
          ],
        });
      }
      return;
    }
    syncTwmMap(stage);
  };

  const loadStateGraph = async (focusNodeId = stateGraphFocusNodeId) => {
    if (!selectedStateId) return setError(t('territoryWorldModel.runtime.selectOrBuildState'));
    await withRun('stateGraph', async () => {
      const params = new URLSearchParams({
        include_full_graph: 'false',
        visual_node_limit: '48',
      });
      if (focusNodeId) {
        params.set('focus_node_id', focusNodeId);
        params.set('focus_object_id', focusNodeId);
      }
      const data = await api(`/api/twm/states/${encodeURIComponent(selectedStateId)}/state-graph?${params.toString()}`);
      setStateGraph(data);
      return data;
    });
  };

  const focusStateGraphNode = async (node: TwmStateGraphNode) => {
    setStateGraphFocusNodeId(node.id);
    syncStateGraphNodeToMap(node);
    await loadStateGraph(node.id);
  };

  const dataFoundationLayerKey = (layer: TwmDataFoundationMapPreviewLayer) => String(layer.name || layer.path || '').trim();

  const buildDataFoundationMapLayers = (data: TwmDataFoundationMapPreview, visibleLayerNames: string[]) => {
    const visible = new Set(visibleLayerNames);
    return (data.layers || [])
      .filter((layer: TwmDataFoundationMapPreviewLayer) => visible.has(dataFoundationLayerKey(layer)))
      .map((layer: TwmDataFoundationMapPreviewLayer) => ({
        name: t('territoryWorldModel.runtime.dataFoundationLayer', { name: displayText(layer.name || layer.path) }),
        type: 'polygon',
        geojsonData: layer.geojson,
        style: dataFoundationLayerStyle(layer.name || layer.path || ''),
        tooltip_fields: ['_twm_source_file', '_twm_dataset_id'],
        tooltip_labels: {
          _twm_source_file: t('territoryWorldModel.runtime.sourceFile'),
          _twm_dataset_id: t('territoryWorldModel.runtime.dataset'),
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
      setDataMapPreviewSummary(t('territoryWorldModel.runtime.mapNotLinked', { message: displayText(readiness?.message, t('territoryWorldModel.runtime.coordinateConversionRequired')) }));
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
      setDataMapPreviewSummary(t('territoryWorldModel.runtime.layerLinked', { layer: layerPath, count: fmt(loadedCount, 0), readiness: readinessText }));
      return;
    }
    setDataMapPreviewSummary(t('territoryWorldModel.runtime.allLayersLinked', { layers: fmt(mapLayers.length, 0), count: fmt(loadedCount, 0), readiness: readinessText }));
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
    setDataMapPreviewSummary(t('territoryWorldModel.runtime.visibleLayers', { visible: fmt(next.length, 0), total: fmt(allLayerNames.length, 0) }));
  };

  const syncDataFoundationMapPreview = async () => {
    if (!selectedDataPackage) {
      setError(t('territoryWorldModel.runtime.noDatasetToPreview'));
      return;
    }
    setDataMapPreviewLoading(true);
    setError('');
    try {
      const data = await api(`/api/twm/data-foundation-map-preview/${encodeURIComponent(selectedDataPackage.id)}?max_features_per_layer=all`);
      applyDataFoundationMapPreview(data, 'full');
    } catch (e: any) {
      setError(e?.message || t('territoryWorldModel.runtime.spatialPreviewFailed'));
    } finally {
      setDataMapPreviewLoading(false);
    }
  };

  const syncDataFoundationLayerMapPreview = async (layerPath: string) => {
    if (!selectedDataPackage) {
      setError(t('territoryWorldModel.runtime.noDatasetToPreview'));
      return;
    }
    const normalizedLayerPath = String(layerPath || '').trim();
    if (!normalizedLayerPath) {
      setError(t('territoryWorldModel.runtime.noSpatialLayerToPreview'));
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
      setError(e?.message || t('territoryWorldModel.runtime.layerPreviewFailed'));
    } finally {
      setDataMapPreviewLoading(false);
    }
  };

  const loadDataFoundationLayerDetail = async (layerPath: string) => {
    if (!selectedDataPackage) {
      setError(t('territoryWorldModel.runtime.noDatasetToView'));
      return;
    }
    const normalizedLayerPath = String(layerPath || '').trim();
    if (!normalizedLayerPath) {
      setError(t('territoryWorldModel.runtime.noSpatialLayerToView'));
      return;
    }
    setSelectedLayerDetailPath(normalizedLayerPath);
    await withRun('layerDetail', async () => {
      const data = await api(
        `/api/twm/data-foundation-layer-detail/${encodeURIComponent(selectedDataPackage.id)}?layer=${encodeURIComponent(normalizedLayerPath)}&sample_limit=5`
      );
      setSelectedLayerDetail(data);
      return data;
    });
  };

  const loadDataFoundationLineage = async () => {
    if (!selectedDataPackage) {
      setError(t('territoryWorldModel.runtime.noDatasetForLineage'));
      return;
    }
    await withRun('lineage', async () => {
      const data = await api(`/api/twm/data-foundation-lineage/${encodeURIComponent(selectedDataPackage.id)}`);
      setDataLineage(data);
      return data;
    });
  };

  const loadDataFoundationCrsRemediation = async () => {
    if (!selectedDataPackage) {
      setError(t('territoryWorldModel.runtime.noDatasetForCrs'));
      return;
    }
    await withRun('crsRemediation', async () => {
      const data = await api(`/api/twm/data-foundation-crs-remediation/${encodeURIComponent(selectedDataPackage.id)}`);
      setCrsRemediationPlan(data);
      return data;
    });
  };

  const loadDataFoundationAuthoritativeTemplates = async () => {
    await withRun('authoritativeTemplates', async () => {
      const data = await api('/api/twm/data-foundation-authoritative-templates');
      setAuthoritativeTemplates(data);
      return data;
    });
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
          description: businessScenarioText(selectedBusinessScenario, 'decisionQuestion'),
          metadata: {
            decision_question: businessScenarioText(selectedBusinessScenario, 'decisionQuestion'),
            operator_goal: businessScenarioText(selectedBusinessScenario, 'operatorGoal'),
            required_evidence: businessScenarioList(selectedBusinessScenario, 'requiredEvidence'),
            decision_outputs: businessScenarioList(selectedBusinessScenario, 'outputs'),
          },
        }),
      });
      await loadProjects();
      setSelectedProjectId(project.id);
      return project;
    });
  };

  const buildState = async () => {
    if (!selectedProjectId) return setError(t('territoryWorldModel.runtime.selectOrCreateProject'));
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
    if (!selectedStateId) return setError(t('territoryWorldModel.runtime.selectOrBuildState'));
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
    if (!selectedStateId) return setError(t('territoryWorldModel.runtime.selectOrBuildState'));
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
          scenario_context: businessScenarioText(selectedBusinessScenario, 'decisionQuestion'),
        }),
      });
      setForecastResult(data);
      return data;
    });
  };

  const runValidation = async () => {
    if (!selectedStateId) return setError(t('territoryWorldModel.runtime.selectOrBuildState'));
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
          scenario_context: businessScenarioText(selectedBusinessScenario, 'decisionQuestion'),
        }),
      });
      setValidationResult(data);
      return data;
    });
  };

  const runAudit = async () => {
    if (!selectedStateId) return setError(t('territoryWorldModel.runtime.selectOrBuildState'));
    await withRun('audit', async () => {
      const data = await api(`/api/twm/states/${encodeURIComponent(selectedStateId)}/audit-report`);
      setAuditResult(data);
      return data;
    });
  };

  const loadCandidates = async () => {
    if (!selectedStateId) return setError(t('territoryWorldModel.runtime.selectOrBuildState'));
    await withRun('candidates', async () => {
      const data = await api(`/api/twm/states/${encodeURIComponent(selectedStateId)}/farmland-layout-candidates`, {
        method: 'POST',
        body: JSON.stringify({ optimization_dir: optimizationDir, horizon }),
      });
      setCandidateResult(data);
      return data;
    });
  };

  const runBeam = async () => {
    if (!selectedStateId) return setError(t('territoryWorldModel.runtime.selectOrBuildState'));
    await withRun('beam', async () => {
      const data = await api(`/api/twm/states/${encodeURIComponent(selectedStateId)}/farmland-layout-optimization-beam-plan`, {
        method: 'POST',
        body: JSON.stringify({
          optimization_dir: optimizationDir,
          evidence_coverage: evidenceCoverage,
          horizon,
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
  const multiHorizonComparison = beamResult?.multi_horizon_comparison || {};
  const multiHorizonTrajectories = multiHorizonComparison?.candidate_trajectories || [];
  const executionAccounting = multiHorizonComparison?.execution_accounting || {};
  const spatialSimulatorBackend = multiHorizonTrajectories[0]?.simulator_trace?.backend || {};
  const filteredBaselineCards = baselineCards.filter(card => {
    if (baselineCardFilter === 'all') return true;
    const claimId = card.metadata?.claim?.claim_id || card.input_changes?.claim_id || '';
    return claimId === baselineCardFilter;
  });
  const selectedBaselineTemplate = (baselineTemplates?.templates || []).find(item => item.claim_id === selectedClaimId) || null;
  const stateGraphCounts = stateGraph?.full_graph_counts || {};
  const stateGraphVisual = stateGraph?.visual_graph || {};
  const stateGraphNodes = stateGraphVisual.nodes || [];
  const stateGraphEdges = stateGraphVisual.edges || [];
  const stateGraphRenderPolicy = stateGraphVisual.render_policy || {};
  const stateGraphPositioned = stateGraphLayout(stateGraphNodes, stateGraphEdges);
  const stateGraphFullLoaded = Boolean(stateGraph?.full_graph?.included);

  const runBaselineExportValidation = async () => {
    const claims = claimMatrix.claims || [];
    const selectedClaim = claims.find(item => item.claim_id === selectedClaimId) || claims[0];
    if (!selectedClaim) return setError(t('territoryWorldModel.runtime.noClaimToValidate'));
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
    if (!selectedClaim) return setError(t('territoryWorldModel.runtime.noClaimToImport'));
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
    if (!selectedClaim) return setError(t('territoryWorldModel.runtime.noClaimToRun'));
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
    if (!selectedClaim) return setError(t('territoryWorldModel.runtime.noClaimToCompare'));
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
            <strong>{t('territoryWorldModel.title')}</strong>
            <span>{t('territoryWorldModel.subtitle')}</span>
          </div>
        </div>
        <button type="button" className="twm-icon-button" onClick={refreshAll} disabled={busy} title={t('territoryWorldModel.actions.refreshTitle')}>
          <RefreshCw size={13} />
          {t('territoryWorldModel.actions.refresh')}
        </button>
        <span className={`status-badge ${statusClass(status?.status)}`}>
          {running === 'status' ? t('territoryWorldModel.common.checking') : statusText(status?.status, t('territoryWorldModel.common.unknown'))}
        </span>
      </div>

      {error && <div className="twm-alert error">{error}</div>}

      <div className="twm-kpi-grid">
        {readiness.map(item => (
          <div className="twm-kpi" key={item.id}>
            <span>{item.label}</span>
            <strong>{fmt(item.value, 0)}</strong>
          </div>
        ))}
      </div>

      <div className="twm-subtabs" role="tablist" aria-label={t('territoryWorldModel.tabs.ariaLabel')}>
        {TWM_SUB_TABS.map(tabId => {
          const active = activeSubTab === tabId;
          return (
            <button
              key={tabId}
              type="button"
              role="tab"
              id={`twm-subtab-control-${tabId}`}
              aria-label={t(`territoryWorldModel.tabs.${tabId}.label`)}
              aria-selected={active}
              aria-controls={`twm-subtab-${tabId}`}
              className={`twm-subtab ${active ? 'active' : ''}`}
              onClick={() => setActiveSubTab(tabId)}
            >
              <strong>{t(`territoryWorldModel.tabs.${tabId}.label`)}</strong>
              <span>{t(`territoryWorldModel.tabs.${tabId}.summary`)}</span>
            </button>
          );
        })}
      </div>

      {activeSubTab === 'briefing' && (
        <div
          className="twm-subtab-panel"
          role="tabpanel"
          id="twm-subtab-briefing"
          aria-labelledby="twm-subtab-control-briefing"
        >
          <TwmExecutiveDemoPanel onNavigate={setActiveSubTab} onMapStage={syncTwmMap} />
        </div>
      )}

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
          <h4>{t('territoryWorldModel.map.title')}</h4>
          <span className={`status-badge ${mapStage === 'none' ? 'proposed' : 'success'}`}>
            {mapStage === 'none'
              ? t('territoryWorldModel.map.notLinked')
              : t('territoryWorldModel.map.linked', { stage: t(`territoryWorldModel.map.stages.${mapStage}`) })}
          </span>
        </div>
        <p className="twm-map-story-copy">
          {t('territoryWorldModel.map.description')}
        </p>
        <div className="twm-map-story-actions">
          <button type="button" className="twm-secondary-action" onClick={() => syncTwmMap('locate')} disabled={busy}>
            <MapPin size={13} />
            {t('territoryWorldModel.map.actions.locate')}
          </button>
          <button type="button" className="twm-secondary-action" onClick={() => syncTwmMap('risk')} disabled={busy}>
            <AlertTriangle size={13} />
            {t('territoryWorldModel.map.actions.risk')}
          </button>
          <button type="button" className="twm-secondary-action" onClick={() => syncTwmMap('plan')} disabled={busy}>
            <Route size={13} />
            {t('territoryWorldModel.map.actions.plan')}
          </button>
        </div>
        <div className="twm-map-story-legend">
          <span><i className="review" />{t('territoryWorldModel.map.legend.review')}</span>
          <span><i className="constraint" />{t('territoryWorldModel.map.legend.constraint')}</span>
          <span><i className="risk" />{t('territoryWorldModel.map.legend.risk')}</span>
          <span><i className="plan" />{t('territoryWorldModel.map.legend.plan')}</span>
        </div>
      </section>

      <section className="twm-section twm-business-section">
        <div className="twm-section-head">
          <ShieldCheck size={14} />
          <h4>{t('territoryWorldModel.businessTask.title')}</h4>
          <span className="status-badge proposed">{running === 'scenarios' ? t('territoryWorldModel.status.loading') : businessScenarioText(selectedBusinessScenario, 'label')}</span>
        </div>
        <div className="twm-business-grid">
          <label className="twm-field">
            <span>{t('territoryWorldModel.businessTask.scenario')}</span>
            <select value={selectedBusinessScenario.id} onChange={e => applyBusinessScenario(e.target.value)} disabled={busy}>
              {businessScenarios.map(item => (
                <option value={item.id} key={item.id}>{businessScenarioText(item, 'label')}</option>
              ))}
            </select>
          </label>
          <div className="twm-business-question">
            <span>{t('territoryWorldModel.businessTask.decisionQuestion')}</span>
            <strong>{businessScenarioText(selectedBusinessScenario, 'decisionQuestion')}</strong>
          </div>
        </div>
        <div className="twm-business-grid">
          <div className="twm-business-list">
            <span>{t('territoryWorldModel.businessTask.requiredEvidence')}</span>
            <div>{businessScenarioList(selectedBusinessScenario, 'requiredEvidence').map(item => <code key={item}>{item}</code>)}</div>
          </div>
          <div className="twm-business-list">
            <span>{t('territoryWorldModel.businessTask.outputs')}</span>
            <div>{businessScenarioList(selectedBusinessScenario, 'outputs').map(item => <code key={item}>{item}</code>)}</div>
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
      <section className="twm-section twm-roadmap-status-panel">
        <div className="twm-section-head">
          <GitBranch size={14} />
          <h4>{t('territoryWorldModel.roadmap.title')}</h4>
          <span className={`status-badge ${statusClass(roadmapStatus?.overall_status)}`}>
            {running === 'roadmapStatus' ? t('territoryWorldModel.status.loading') : statusText(roadmapStatus?.overall_status, t('territoryWorldModel.common.pendingLoad'))}
          </span>
        </div>
        <div className="twm-roadmap-boundary">
          <strong>{t('territoryWorldModel.roadmap.currentProgress')}</strong>
          <p>{roadmapStatus?.claim_boundary ? displayText(roadmapStatus.claim_boundary) : t('territoryWorldModel.roadmap.defaultBoundary')}</p>
        </div>
        <div className="twm-roadmap-kpis">
          <div><span>{t('territoryWorldModel.roadmap.averageCompletion')}</span><strong>{fmt(roadmapCompletion * 100, 0)}%</strong></div>
          <div><span>{t('territoryWorldModel.roadmap.completedPhases')}</span><strong>{fmt(roadmapCompleteCount, 0)}</strong></div>
          <div><span>{t('territoryWorldModel.roadmap.inProgress')}</span><strong>{fmt(roadmapProgressCount, 0)}</strong></div>
          <div><span>{t('territoryWorldModel.roadmap.blockedPhases')}</span><strong>{fmt(roadmapBlockedCount, 0)}</strong></div>
        </div>
        <div className="twm-roadmap-phase-list">
          {roadmapPhases.map(phase => (
            <article key={phase.id}>
              <div>
                <span className={`status-badge ${statusClass(phase.status)}`}>{statusText(phase.status, t('territoryWorldModel.status.review'))}</span>
                <strong>{displayText(phase.label || phase.id)}</strong>
                <em>{fmt(clampRatio(phase.completion_ratio, 0) * 100, 0)}%</em>
              </div>
              <p>{t('territoryWorldModel.roadmap.available', { items: compactDisplayList(phase.evidence, t('territoryWorldModel.roadmap.noEvidence')) })}</p>
              <p>{t('territoryWorldModel.roadmap.remaining', { items: compactDisplayList(phase.remaining, t('territoryWorldModel.roadmap.nothingRemaining')) })}</p>
            </article>
          ))}
          {!roadmapPhases.length && <div className="twm-empty">{t('territoryWorldModel.roadmap.empty')}</div>}
        </div>
        <div className="twm-roadmap-bottom">
          <article>
            <strong>{t('territoryWorldModel.roadmap.keyBlockers')}</strong>
            {(roadmapStatus?.blockers || []).slice(0, 4).map(item => (
              <p key={`roadmap-blocker-${item.id}`}>
                {t('territoryWorldModel.roadmap.blockerSummary', { priority: item.priority ? `${item.priority} · ` : '', id: displayText(item.id), status: statusText(item.status, t('territoryWorldModel.status.pending')), current: typeof item.current_value === 'number' ? fmt(item.current_value, 0) : displayText(item.current_value), target: displayText(item.required_value) })}
              </p>
            ))}
            {!(roadmapStatus?.blockers || []).length && <p>{t('territoryWorldModel.roadmap.noBlockers')}</p>}
          </article>
          <article>
            <strong>{t('territoryWorldModel.roadmap.nextActions')}</strong>
            {(roadmapStatus?.next_actions || []).slice(0, 4).map(item => (
              <p key={`roadmap-action-${item.priority}-${item.action}`}>
                {item.priority ? `${item.priority} · ` : ''}{displayText(item.action)}
              </p>
            ))}
            {!(roadmapStatus?.next_actions || []).length && <p>{t('territoryWorldModel.roadmap.noNextActions')}</p>}
          </article>
        </div>
      </section>

      <section className="twm-section twm-data-browser-panel">
        <div className="twm-section-head">
          <FileCheck2 size={14} />
          <h4>{t('territoryWorldModel.dataBrowser.title')}</h4>
          <span className={`status-badge ${statusClass(dataReadiness.status || dataFoundation.status)}`}>
            {statusText(dataReadiness.status || dataFoundation.status, t('territoryWorldModel.status.review'))}
          </span>
        </div>
        <div className="twm-data-browser-verdict">
          <strong>{t('territoryWorldModel.dataBrowser.currentVerdict')}</strong>
          <p>{displayText(dataReadiness.verdict)}</p>
        </div>
        <div className="twm-data-package-switcher">
          {dataPackages.map(dataset => (
            <button
              type="button"
              key={dataset.id}
              aria-label={t('territoryWorldModel.dataBrowser.browseDataset', { name: displayText(dataset.label) })}
              className={selectedDataPackage?.id === dataset.id ? 'active' : ''}
              onClick={() => selectDataPackage(dataset.id)}
            >
              <strong>{displayText(dataset.label)}</strong>
              <span>{t('territoryWorldModel.dataBrowser.datasetSummary', { count: fmt(dataset.total_count, 0), status: dataset.not_for_production ? t('territoryWorldModel.dataBrowser.demoNonProduction') : t('territoryWorldModel.dataBrowser.productionCandidate') })}</span>
            </button>
          ))}
        </div>
        <div className="twm-data-browser-actions">
          <button type="button" className="twm-secondary-action" onClick={syncDataFoundationMapPreview} disabled={dataMapPreviewLoading || !selectedDataPackage}>
            {dataMapPreviewLoading ? <Loader2 size={13} className="twm-spin" /> : <MapPin size={13} />}
            {t('territoryWorldModel.dataBrowser.loadSpatialData')}
          </button>
          <button type="button" className="twm-secondary-action" onClick={loadDataFoundationLineage} disabled={busy || !selectedDataPackage}>
            {running === 'lineage' ? <Loader2 size={13} className="twm-spin" /> : <GitBranch size={13} />}
            {t('territoryWorldModel.dataBrowser.lineageReport')}
          </button>
          <button type="button" className="twm-secondary-action" onClick={loadDataFoundationCrsRemediation} disabled={busy || !selectedDataPackage}>
            {running === 'crsRemediation' ? <Loader2 size={13} className="twm-spin" /> : <RefreshCw size={13} />}
            {t('territoryWorldModel.dataBrowser.crsPlan')}
          </button>
          <button type="button" className="twm-secondary-action" onClick={loadDataFoundationAuthoritativeTemplates} disabled={busy}>
            {running === 'authoritativeTemplates' ? <Loader2 size={13} className="twm-spin" /> : <ShieldCheck size={13} />}
            {t('territoryWorldModel.dataBrowser.authoritativeTemplates')}
          </button>
          <span>{dataMapPreviewSummary || t('territoryWorldModel.dataBrowser.mapPreviewHint')}</span>
        </div>
        {visibleDataLineage && (
          <div className="twm-lineage-panel">
            <div className="twm-lineage-head">
              <div>
                <strong>{t('territoryWorldModel.dataBrowser.lineageReport')}</strong>
                <span>{displayText(visibleDataLineage.dataset_label)} · <code>{visibleDataLineage.dataset_root}</code></span>
              </div>
              <span className={`status-badge ${statusClass(visibleDataLineage.lineage_coverage?.status)}`}>
                {statusText(visibleDataLineage.lineage_coverage?.status, t('territoryWorldModel.status.review'))}
              </span>
            </div>
            <div className="twm-lineage-kpis">
              <div><span>{t('territoryWorldModel.dataBrowser.files')}</span><strong>{fmt(visibleDataLineage.file_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.dataBrowser.spatialLayers')}</span><strong>{fmt(visibleDataLineage.spatial_layer_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.dataBrowser.tables')}</span><strong>{fmt(visibleDataLineage.table_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.dataBrowser.nonProductionRecords')}</span><strong>{fmt(visibleDataLineage.not_for_production_record_count, 0)}</strong></div>
            </div>
            <div className="twm-lineage-gates">
              {(visibleDataLineage.readiness_gates || []).slice(0, 4).map(gate => (
                <article key={`lineage-gate-${gate.id}`}>
                  <span className={`status-badge ${statusClass(gate.status)}`}>{statusText(gate.status, t('territoryWorldModel.status.pending'))}</span>
                  <strong>{displayText(gate.id)}</strong>
                  <p>{t('territoryWorldModel.dataBrowser.currentTarget', { current: typeof gate.current_value === 'number' ? fmt(gate.current_value, 0) : displayText(gate.current_value), target: displayText(gate.required_value) })}</p>
                </article>
              ))}
            </div>
            <div className="twm-lineage-file-list">
              {(visibleDataLineage.files || []).slice(0, 10).map(file => (
                <article key={`lineage-file-${file.path}`}>
                  <div>
                    <code>{file.path}</code>
                    <span className={`status-badge ${statusClass(file.lineage_status)}`}>{statusText(file.lineage_status, t('territoryWorldModel.status.review'))}</span>
                  </div>
                  <p>{t('territoryWorldModel.dataBrowser.fileSummary', { role: displayText(file.source_role), count: fmt(file.count, 0), unit: displayText(file.unit, t('territoryWorldModel.dataBrowser.rows')), synthetic: fmt(file.synthetic_count, 0), nonProduction: fmt(file.not_for_production_count, 0) })}</p>
                  {file.crs_diagnostic && <p>{t('territoryWorldModel.dataBrowser.crsFieldSummary', { crs: crsDiagnosticText(file.crs_diagnostic.status), fields: fmt(file.property_field_count, 0) })}</p>}
                </article>
              ))}
            </div>
            <p className="twm-lineage-boundary">{displayText(visibleDataLineage.claim_boundary)}</p>
          </div>
        )}
        {visibleCrsRemediationPlan && (
          <div className="twm-crs-remediation-panel">
            <div className="twm-crs-remediation-head">
              <div>
                <strong>{t('territoryWorldModel.dataBrowser.crsPlan')}</strong>
                <span>{t('territoryWorldModel.dataBrowser.targetCrs', { dataset: displayText(visibleCrsRemediationPlan.dataset_label), crs: visibleCrsRemediationPlan.target_crs || 'EPSG:4326' })}</span>
              </div>
              <span className={`status-badge ${statusClass(visibleCrsRemediationPlan.status)}`}>
                {statusText(visibleCrsRemediationPlan.status, t('territoryWorldModel.status.review'))}
              </span>
            </div>
            <div className="twm-crs-remediation-kpis">
              <div><span>{t('territoryWorldModel.dataBrowser.layers')}</span><strong>{fmt(visibleCrsRemediationPlan.layer_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.dataBrowser.overlayReady')}</span><strong>{fmt(visibleCrsRemediationPlan.ready_layer_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.dataBrowser.needsConversion')}</span><strong>{fmt(visibleCrsRemediationPlan.blocked_layer_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.dataBrowser.outputPolicy')}</span><strong>{visibleCrsRemediationPlan.execution_policy?.default_output_suffix || '_wgs84.geojson'}</strong></div>
            </div>
            <div className="twm-crs-remediation-layer-list">
              {(visibleCrsRemediationPlan.layers || []).slice(0, 8).map(layer => (
                <article key={`crs-plan-${layer.path}`}>
                  <div>
                    <code>{layer.path}</code>
                    <span className={`status-badge ${statusClass(layer.status)}`}>
                      {statusText(layer.status, t('territoryWorldModel.status.review'))}
                    </span>
                  </div>
                  <p>
                    {t('territoryWorldModel.dataBrowser.layerCrsSummary', { source: displayText(layer.source_crs_assumption), target: layer.target_crs || visibleCrsRemediationPlan.target_crs || 'EPSG:4326', count: fmt(layer.feature_count, 0) })}
                  </p>
                  <p>
                    {t('territoryWorldModel.dataBrowser.output')}: {layer.output_policy?.write_new_file
                      ? `${layer.path.replace(/\.geojson$/i, '')}${layer.output_policy?.suffix || '_wgs84.geojson'}`
                      : t('territoryWorldModel.dataBrowser.sourceOverlayReady')}
                  </p>
                  <div>
                    {(layer.conversion_steps || []).slice(0, 4).map((step, idx) => (
                      <span key={`crs-step-${layer.path}-${step.action}-${idx}`}>
                        {idx + 1}. {displayText(step.action)} · {statusText(step.status, t('territoryWorldModel.status.pending'))}
                      </span>
                    ))}
                  </div>
                </article>
              ))}
              {!(visibleCrsRemediationPlan.layers || []).length && <div className="twm-empty">{t('territoryWorldModel.dataBrowser.noLayersToProcess')}</div>}
            </div>
            <div className="twm-crs-remediation-criteria">
              {(visibleCrsRemediationPlan.acceptance_criteria || []).slice(0, 4).map(item => (
                <p key={`crs-criteria-${item}`}>{displayText(item)}</p>
              ))}
            </div>
            <p className="twm-crs-remediation-boundary">{displayText(visibleCrsRemediationPlan.claim_boundary)}</p>
          </div>
        )}
        {authoritativeTemplates && (
          <div className="twm-authoritative-template-panel">
            <div className="twm-authoritative-template-head">
              <div>
                <strong>{t('territoryWorldModel.dataBrowser.authoritativeTemplates')}</strong>
                <span>{t('territoryWorldModel.dataBrowser.templateDescription')}</span>
              </div>
              <span className={`status-badge ${statusClass(authoritativeTemplates.status)}`}>
                {statusText(authoritativeTemplates.status, t('territoryWorldModel.status.review'))}
              </span>
            </div>
            <div className="twm-authoritative-template-kpis">
              <div><span>{t('territoryWorldModel.dataBrowser.templates')}</span><strong>{fmt(authoritativeTemplates.template_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.dataBrowser.productionDeployment')}</span><strong>{yesNo(authoritativeTemplates.production_deployment_supported)}</strong></div>
              <div><span>{t('territoryWorldModel.dataBrowser.lineageFields')}</span><strong>{fmt(authoritativeTemplates.shared_lineage_fields?.length, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.dataBrowser.gates')}</span><strong>{fmt(authoritativeTemplates.readiness_gates?.length, 0)}</strong></div>
            </div>
            <div className="twm-authoritative-gates">
              {(authoritativeTemplates.readiness_gates || []).slice(0, 4).map(gate => (
                <article key={`authoritative-gate-${gate.id}`}>
                  <span className={`status-badge ${statusClass(gate.status)}`}>{statusText(gate.status, t('territoryWorldModel.status.pending'))}</span>
                  <strong>{displayText(gate.id)}</strong>
                  <p>{t('territoryWorldModel.dataBrowser.currentTarget', { current: displayText(gate.current_value), target: displayText(gate.required_value) })}</p>
                </article>
              ))}
            </div>
            <div className="twm-authoritative-template-list">
              {(authoritativeTemplates.templates || []).slice(0, 6).map(template => (
                <article key={`authoritative-template-${template.template_id}`}>
                  <div>
                    <strong>{displayText(template.label || template.template_id)}</strong>
                    <code>{displayText(template.role)}</code>
                  </div>
                  <p>{displayText(template.production_use)} · {displayText(template.unit)} · {compactDisplayList(template.accepted_formats, t('territoryWorldModel.dataBrowser.anyFormat'))}</p>
                  <p>{t('territoryWorldModel.dataBrowser.requiredFields', { fields: compactDisplayList((template.required_fields || []).slice(0, 8), t('territoryWorldModel.common.none')) })}</p>
                  <p>{t('territoryWorldModel.dataBrowser.qualityGates', { gates: compactDisplayList((template.minimum_quality_gates || []).slice(0, 4), t('territoryWorldModel.common.none')) })}</p>
                </article>
              ))}
            </div>
            <div className="twm-authoritative-lineage">
              {(authoritativeTemplates.shared_lineage_fields || []).slice(0, 12).map(field => (
                <code key={`authoritative-lineage-${field}`}>{field}</code>
              ))}
            </div>
            <p className="twm-authoritative-boundary">{displayText(authoritativeTemplates.claim_boundary)}</p>
          </div>
        )}
        {dataMapPreview && (
          <div className="twm-crs-diagnostic-panel">
            <div className="twm-crs-diagnostic-head">
              <div>
                <strong>{t('territoryWorldModel.dataBrowser.coordinateDiagnostics')}</strong>
                <span>{displayText(dataMapPreview.map_overlay_readiness?.message, t('territoryWorldModel.dataBrowser.extentRead'))}</span>
              </div>
              <span className={`status-badge ${statusClass(dataMapPreview.map_overlay_readiness?.status)}`}>
                {mapOverlayReadinessText(dataMapPreview.map_overlay_readiness?.status)}
              </span>
            </div>
            <div className="twm-crs-diagnostic-kpis">
              <div><span>{t('territoryWorldModel.dataBrowser.overlayLayers')}</span><strong>{fmt(dataMapPreview.map_overlay_readiness?.ready_layer_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.dataBrowser.layersToProcess')}</span><strong>{fmt(dataMapPreview.map_overlay_readiness?.blocked_layer_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.dataBrowser.spatialFeatures')}</span><strong>{fmt(dataMapPreview.total_preview_feature_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.dataBrowser.suggestedAction')}</span><strong>{displayText(dataMapPreview.map_overlay_readiness?.suggested_action)}</strong></div>
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
                    <span>{t('territoryWorldModel.dataBrowser.featureRatio', { preview: fmt(layer.preview_feature_count, 0), source: fmt(layer.source_feature_count, 0) })}</span>
                    <button
                      type="button"
                      className={`twm-layer-visibility-toggle ${visible ? 'active' : ''}`}
                      onClick={() => toggleDataFoundationMapLayer(layerName)}
                      disabled={!layerName}
                      aria-label={visible ? t('territoryWorldModel.dataBrowser.hideLayerAria', { name: layerName }) : t('territoryWorldModel.dataBrowser.showLayerAria', { name: layerName })}
                      title={visible ? t('territoryWorldModel.dataBrowser.hideLayerTitle') : t('territoryWorldModel.dataBrowser.showLayerTitle')}
                    >
                      {visible ? <Eye size={12} /> : <EyeOff size={12} />}
                      <span>{visible ? t('territoryWorldModel.dataBrowser.hide') : t('territoryWorldModel.dataBrowser.show')}</span>
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
                <span>{t('territoryWorldModel.dataBrowser.datasetId')}</span>
                <strong>{selectedDataPackage.id}</strong>
              </div>
              <div>
                <span>{t('territoryWorldModel.dataBrowser.total')}</span>
                <strong>{fmt(selectedDataPackage.total_count, 0)}</strong>
              </div>
              <div>
                <span>{t('territoryWorldModel.dataBrowser.files')}</span>
                <strong>{fmt(selectedDataPackage.file_count || selectedDataPackage.files?.length, 0)}</strong>
              </div>
              <div>
                <span>{t('territoryWorldModel.dataBrowser.nonProduction')}</span>
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
                    <strong>{t('territoryWorldModel.dataBrowser.spatialCatalog')}</strong>
                    <span>{t('territoryWorldModel.dataBrowser.spatialCatalogDescription')}</span>
                  </div>
                  <span className={`status-badge ${statusClass(selectedDataPackage.map_overlay_readiness?.status)}`}>
                    {mapOverlayReadinessText(selectedDataPackage.map_overlay_readiness?.status)}
                  </span>
                </div>
                <div className="twm-spatial-catalog-list">
                  {selectedSpatialLayerCatalog.slice(0, 8).map(layer => {
                    const layerPath = layer.name || layer.path || '';
                    const detailLoading = running === 'layerDetail' && selectedLayerDetailPath === layerPath;
                    return (
                      <div key={`spatial-catalog-${selectedDataPackage.id}-${layerPath}`}>
                        <div className="twm-spatial-catalog-actions">
                          <button
                            type="button"
                            className="twm-spatial-catalog-action"
                            onClick={() => syncDataFoundationLayerMapPreview(layerPath)}
                            disabled={dataMapPreviewLoading || !layerPath}
                            aria-label={t('territoryWorldModel.dataBrowser.addToMapAria', { name: layerPath })}
                            title={t('territoryWorldModel.dataBrowser.addToMapTitle')}
                          >
                            <MapPin size={12} />
                            <span>{t('territoryWorldModel.dataBrowser.addToMap')}</span>
                          </button>
                          <button
                            type="button"
                            className="twm-spatial-catalog-action secondary"
                            onClick={() => loadDataFoundationLayerDetail(layerPath)}
                            disabled={busy || !layerPath}
                            aria-label={t('territoryWorldModel.dataBrowser.fieldDetailsAria', { name: layerPath })}
                            title={t('territoryWorldModel.dataBrowser.fieldDetailsTitle')}
                          >
                            {detailLoading ? <Loader2 size={12} className="twm-spin" /> : <FileCheck2 size={12} />}
                            <span>{t('territoryWorldModel.dataBrowser.fieldDetails')}</span>
                          </button>
                        </div>
                        <div className="twm-spatial-catalog-main">
                          <code>{layerPath}</code>
                          <span>{t('territoryWorldModel.dataBrowser.featureCount', { count: fmt(layer.source_feature_count ?? layer.feature_count, 0) })}</span>
                          <span>{compactBbox(layer.bbox)}</span>
                          <span className={`status-badge ${layer.crs_diagnostic?.map_overlay_ready ? 'success' : 'error'}`}>
                            {crsDiagnosticText(layer.crs_diagnostic?.status)}
                          </span>
                          <div className="twm-spatial-catalog-attributes">
                            <span>{t('territoryWorldModel.dataBrowser.fieldsInline', { fields: compactPropertyFieldNames(layer.property_fields, layer.property_field_count) })}</span>
                            <span>{t('territoryWorldModel.dataBrowser.sampleInline', { sample: compactSampleProperties(layer.sample_properties) })}</span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
                {visibleLayerDetail && (
                  <div className="twm-layer-detail-panel">
                    <div className="twm-layer-detail-head">
                      <div>
                        <strong>{t('territoryWorldModel.dataBrowser.fieldDetails')}</strong>
                        <span>{displayText(visibleLayerDetail.dataset_label)} · <code>{visibleLayerDetail.layer_path}</code></span>
                      </div>
                      <span className={`status-badge ${visibleLayerDetail.not_for_production ? 'warning' : 'success'}`}>
                        {visibleLayerDetail.not_for_production ? t('territoryWorldModel.dataBrowser.demoNonProduction') : t('territoryWorldModel.dataBrowser.productionCandidate')}
                      </span>
                    </div>
                    <div className="twm-layer-detail-kpis">
                      <div><span>{t('territoryWorldModel.dataBrowser.featureCountLabel')}</span><strong>{fmt(visibleLayerDetail.feature_count, 0)}</strong></div>
                      <div><span>{t('territoryWorldModel.dataBrowser.fieldCount')}</span><strong>{fmt(visibleLayerDetail.property_field_count, 0)}</strong></div>
                      <div><span>{t('territoryWorldModel.dataBrowser.sampleRecords')}</span><strong>{fmt(visibleLayerDetail.sample_record_count, 0)}</strong></div>
                      <div><span>{t('territoryWorldModel.dataBrowser.coordinates')}</span><strong>{crsDiagnosticText(visibleLayerDetail.crs_diagnostic?.status)}</strong></div>
                    </div>
                    <div className="twm-layer-detail-fields">
                      {(visibleLayerDetail.property_fields || []).slice(0, 14).map(field => (
                        <span key={`layer-field-${visibleLayerDetail.layer_path}-${field.name}`}>
                          <code>{field.name}</code>
                          {displayText(field.value_type, 'unknown')} · {fmt(field.observed_count, 0)}
                        </span>
                      ))}
                      {!(visibleLayerDetail.property_fields || []).length && <div className="twm-empty">{t('territoryWorldModel.dataBrowser.noFieldDetails')}</div>}
                    </div>
                    <div className="twm-layer-detail-records">
                      {(visibleLayerDetail.sample_records || []).slice(0, 5).map(record => (
                        <article key={`sample-record-${visibleLayerDetail.layer_path}-${record.feature_index}`}>
                          <strong>#{fmt(record.feature_index, 0)}</strong>
                          <p>{compactSampleProperties(record.properties)}</p>
                        </article>
                      ))}
                      {!(visibleLayerDetail.sample_records || []).length && <div className="twm-empty">{t('territoryWorldModel.dataBrowser.noSampleRecords')}</div>}
                    </div>
                    <p className="twm-layer-detail-boundary">{displayText(visibleLayerDetail.claim_boundary)}</p>
                  </div>
                )}
              </div>
            )}
            <div className="twm-data-browser-table" role="table" aria-label={t('territoryWorldModel.dataBrowser.fileListAria')}>
              <div role="row" className="head">
                <span role="columnheader">{t('territoryWorldModel.dataBrowser.files')}</span>
                <span role="columnheader">{t('territoryWorldModel.dataBrowser.quantity')}</span>
                <span role="columnheader">{t('territoryWorldModel.dataBrowser.synthetic')}</span>
                <span role="columnheader">{t('territoryWorldModel.dataBrowser.nonProduction')}</span>
              </div>
              {(selectedDataPackage.files || []).map(file => (
                <div role="row" key={`${selectedDataPackage.id}-browser-${file.path}`}>
                  <code role="cell">{file.path}</code>
                  <span role="cell">{fmt(file.count, 0)} {displayText(file.unit, t('territoryWorldModel.dataBrowser.rows'))}</span>
                  <span role="cell">{fmt(file.synthetic_count, 0)}</span>
                  <span role="cell">{fmt(file.not_for_production_count, 0)}</span>
                </div>
              ))}
            </div>
            <div className="twm-data-browser-columns">
              <article>
                <strong>{t('territoryWorldModel.dataBrowser.supports')}</strong>
                {(dataFoundation.supported_problems || []).slice(0, 4).map(item => (
                  <p key={`browser-support-${item.problem}`}>{displayText(item.problem)}{t('territoryWorldModel.common.keyValueSeparator')}{displayText(item.support)}</p>
                ))}
              </article>
              <article>
                <strong>{t('territoryWorldModel.dataBrowser.cannotClaim')}</strong>
                {(dataFoundation.unsupported_claims || []).slice(0, 4).map(item => (
                  <p key={`browser-unsupported-${item.claim}`}>{displayText(item.claim)}{t('territoryWorldModel.common.keyValueSeparator')}{displayText(item.reason)}</p>
                ))}
              </article>
              <article>
                <strong>{t('territoryWorldModel.dataBrowser.nextAuthoritativeData')}</strong>
                {(dataFoundation.required_next_data || []).slice(0, 4).map(item => (
                  <p key={`browser-next-${item.data}`}>{item.priority ? `${item.priority} · ` : ''}{displayText(item.data)}{t('territoryWorldModel.common.keyValueSeparator')}{displayText(item.unlocks || item.minimum)}</p>
                ))}
              </article>
            </div>
          </div>
        ) : (
          <div className="twm-empty">{t('territoryWorldModel.dataBrowser.noDatasets')}</div>
        )}
      </section>

      <details className="twm-section twm-research-panel" open>
        <summary>
          <span>{t('territoryWorldModel.research.boundary')}</span>
          <code>{running === 'positioning' ? t('territoryWorldModel.status.loading') : t('territoryWorldModel.research.prototypeClaim')}</code>
        </summary>
        <div className="twm-research-question">{displayText(researchPositioning.research_question)}</div>
        <div className="twm-research-grid">
          <div>
            <span>{t('territoryWorldModel.research.coreTechnology')}</span>
            {(researchPositioning.core_technology || []).slice(0, 3).map(item => (
              <article key={item.name}>
                <strong>{displayText(item.name)}</strong>
                <p>{displayText(item.claim || item.why_it_matters)}</p>
              </article>
            ))}
          </div>
          <div>
            <span>{t('territoryWorldModel.research.claimsToValidate')}</span>
            {(researchPositioning.innovation_hypotheses || []).slice(0, 3).map(item => (
              <article key={item.hypothesis}>
                <strong>{displayText(item.hypothesis)}</strong>
                <p>{displayText(item.test)}</p>
              </article>
            ))}
            {!(researchPositioning.innovation_hypotheses || []).length && (
              <article>
                <strong>{t('territoryWorldModel.research.baselineRequired')}</strong>
                <p>{displayText(researchPositioning.claim_boundary)}</p>
              </article>
            )}
          </div>
          <div>
            <span>{t('territoryWorldModel.research.unmetNeeds')}</span>
            <ul>{(researchPositioning.unmet_need_hypotheses || []).slice(0, 4).map(item => <li key={item}>{displayText(item)}</li>)}</ul>
          </div>
          <div>
            <span>{t('territoryWorldModel.research.falsification')}</span>
            <ul>{(researchPositioning.falsification_conditions || []).slice(0, 4).map(item => <li key={item}>{displayText(item)}</li>)}</ul>
          </div>
        </div>
      </details>

      <section className="twm-section twm-claim-matrix-panel">
        <div className="twm-section-head">
          <GitBranch size={14} />
          <h4>{t('territoryWorldModel.research.claimMatrix')}</h4>
          <span className={`status-badge ${statusClass(claimMatrix.status)}`}>
            {running === 'claimMatrix' ? t('territoryWorldModel.status.loading') : statusText(claimMatrix.status, t('territoryWorldModel.status.review'))}
          </span>
        </div>
        <div className="twm-claim-boundary">{displayText(claimMatrix.claim_boundary)}</div>
        <div className="twm-data-kpis">
          <div><span>{t('territoryWorldModel.research.realHistory')}</span><strong>{fmt(claimDataGate.production_ready_observed_history_rows, 0)}</strong></div>
          <div><span>{t('territoryWorldModel.research.actionLabels')}</span><strong>{fmt(claimDataGate.production_policy_history_row_count, 0)}</strong></div>
          <div><span>{t('territoryWorldModel.research.productionClaim')}</span><strong>{yesNo(claimDataGate.production_deployment_supported)}</strong></div>
          <div><span>{t('territoryWorldModel.research.predictiveCausal')}</span><strong>{yesNo(claimDataGate.predictive_or_causal_claim_supported)}</strong></div>
        </div>
        <div className="twm-claim-grid">
          {(claimMatrix.claims || []).slice(0, 4).map(item => (
            <article className="twm-claim-card" key={item.claim_id}>
              <div>
                <strong>{displayText(item.claim_id)}</strong>
                <span className={`status-badge ${statusClass(item.gate?.status)}`}>{statusText(item.gate?.claim_level || item.gate?.status, t('territoryWorldModel.status.review'))}</span>
              </div>
              <p>{displayText(item.claim)}</p>
              {item.business_need && (
                <p><span className="twm-research-detail-label">{t('territoryWorldModelDynamicResearchDataExtras.businessNeedLabel')}</span>{displayText(item.business_need)}</p>
              )}
              {!!item.minimum_data?.length && (
                <p><span className="twm-research-detail-label">{t('territoryWorldModelDynamicResearchDataExtras.minimumDataLabel')}</span>{compactDisplayList(item.minimum_data)}</p>
              )}
              <div className="twm-claim-tags">
                <code>{displayText(item.baseline)}</code>
                {(item.gate?.missing || []).slice(0, 3).map(missing => <code key={`${item.claim_id}-${missing}`}>{displayText(missing)}</code>)}
              </div>
              <span>{displayText(item.metrics?.[0]?.name || item.current_status)}</span>
            </article>
          ))}
        </div>
        {!!(claimMatrix.baselines || []).length && (
          <div className="twm-baseline-methods">
            <span className="twm-baseline-methods-title">{t('territoryWorldModelDynamicBaselineExtras.sectionTitle')}</span>
            <div>
              {(claimMatrix.baselines || []).slice(0, 4).map(item => (
                <article key={item.baseline_id}>
                  <strong>{displayText(item.label || item.baseline_id)}</strong>
                  <p><span>{t('territoryWorldModelDynamicBaselineExtras.testsLabel')}</span>{displayText(item.tests)}</p>
                  <p><span>{t('territoryWorldModelDynamicBaselineExtras.minimumOutputLabel')}</span>{compactDisplayList(item.minimum_output)}</p>
                  <p><span>{t('territoryWorldModelDynamicBaselineExtras.whyNeededLabel')}</span>{displayText(item.why_needed)}</p>
                </article>
              ))}
            </div>
          </div>
        )}
        <div className="twm-claim-experiments">
          {(claimMatrix.next_experiments || []).slice(0, 4).map(item => (
            <article key={item.experiment}>
              <strong>{item.priority ? `${item.priority} · ${displayText(item.experiment)}` : displayText(item.experiment)}</strong>
              <p>{displayText(item.question || item.decision)}</p>
              {!!item.required_data?.length && (
                <p><span className="twm-research-detail-label">{t('territoryWorldModelDynamicResearchDataExtras.requiredDataLabel')}</span>{compactDisplayList(item.required_data)}</p>
              )}
              {item.question && item.decision && <span>{displayText(item.decision)}</span>}
            </article>
          ))}
        </div>
        <div className="twm-baseline-inputs">
          <label>
            <span>{t('territoryWorldModel.baseline.researchClaim')}</span>
            <select value={selectedClaimId} onChange={e => applyClaimFixture(e.target.value)} disabled={busy}>
              {(claimMatrix.claims || []).map(item => (
                <option key={item.claim_id} value={item.claim_id}>{displayText(item.claim_id)}</option>
              ))}
            </select>
          </label>
          <label>
            <span>{t('territoryWorldModel.baseline.twmMetricsFile')}</span>
            <input value={twmMetricsPath} onChange={e => setTwmMetricsPath(e.target.value)} disabled={busy} />
          </label>
          <label>
            <span>{t('territoryWorldModel.baseline.baselineMetricsFile')}</span>
            <input value={baselineMetricsPath} onChange={e => setBaselineMetricsPath(e.target.value)} disabled={busy} />
          </label>
          <label>
            <span>{t('territoryWorldModel.baseline.twmCaseOutput')}</span>
            <input value={twmCaseOutputPath} onChange={e => setTwmCaseOutputPath(e.target.value)} disabled={busy} />
          </label>
          <label>
            <span>{t('territoryWorldModel.baseline.baselineCaseOutput')}</span>
            <input value={baselineCaseOutputPath} onChange={e => setBaselineCaseOutputPath(e.target.value)} disabled={busy} />
          </label>
        </div>
        <div className="twm-baseline-template-panel">
          <div className="twm-baseline-template-head">
            <div>
              <strong>{t('territoryWorldModel.baseline.sanitizedTemplate')}</strong>
              <span>{displayText(selectedBaselineTemplate?.label || selectedClaimId, t('territoryWorldModel.baseline.noTemplate'))}</span>
            </div>
            <span className={`status-badge ${selectedBaselineTemplate ? 'warning' : 'proposed'}`}>
              {running === 'baselineTemplates' ? t('territoryWorldModel.status.loading') : selectedBaselineTemplate?.same_case_join_key ? t('territoryWorldModel.baseline.joinKey', { key: selectedBaselineTemplate.same_case_join_key }) : t('territoryWorldModel.baseline.template')}
            </span>
            <button type="button" className="twm-card-detail-toggle" onClick={loadBaselineTemplates} disabled={busy}>
              {t('territoryWorldModel.actions.refresh')}
            </button>
          </div>
          {selectedBaselineTemplate ? (
            <>
              <div className="twm-baseline-template-question">{displayText(selectedBaselineTemplate.business_question)}</div>
              <div className="twm-baseline-template-grid">
                <article>
                  <span>TWM CSV</span>
                  <code>{selectedBaselineTemplate.csv_header?.twm || (selectedBaselineTemplate.headers?.twm || []).join(',')}</code>
                </article>
                <article>
                  <span>{t('territoryWorldModel.baseline.baselineCsv')}</span>
                  <code>{selectedBaselineTemplate.csv_header?.baseline || (selectedBaselineTemplate.headers?.baseline || []).join(',')}</code>
                </article>
                <article>
                  <span>{t('territoryWorldModel.baseline.requiredColumns')}</span>
                  <p>{compactList(selectedBaselineTemplate.required_columns)}</p>
                </article>
                <article>
                  <span>{t('territoryWorldModel.baseline.realDataGate')}</span>
                  <p>
                    {t('territoryWorldModel.baseline.realDataSummary', { rows: fmt(selectedBaselineTemplate.minimum_real_data_gate?.minimum_real_rows ?? selectedBaselineTemplate.production_collection?.minimum_real_rows, 0), ratio: fmt(selectedBaselineTemplate.minimum_real_data_gate?.minimum_overlap_ratio ?? 0.8, 2) })}
                  </p>
                </article>
                {selectedBaselineTemplate.export_spec?.expected_source && (
                  <article>
                    <span>{t('territoryWorldModelDynamicBaselineExtras.expectedSourceLabel')}</span>
                    <p>{displayText(selectedBaselineTemplate.export_spec.expected_source)}</p>
                  </article>
                )}
              </div>
              <div className="twm-baseline-template-metrics">
                {(selectedBaselineTemplate.metric_column_map || []).slice(0, 3).map(item => (
                  <article key={`${selectedBaselineTemplate.claim_id}-${item.metric}`}>
                    <strong>{displayText(item.metric)}</strong>
                    <p>{compactList(item.columns, t('territoryWorldModel.dataBrowser.noFields'))}</p>
                    {item.supports_claim_when && (
                      <p><span className="twm-research-detail-label">{t('territoryWorldModelDynamicBaselineDetailExtras.supportsClaimLabel')}</span>{displayText(item.supports_claim_when)}</p>
                    )}
                  </article>
                ))}
              </div>
              <details className="twm-baseline-template-details">
                <summary>{t('territoryWorldModel.baseline.fieldConstraints')}</summary>
                <div>
                  {(selectedBaselineTemplate.field_descriptions || []).slice(0, 5).map(field => (
                    <article key={`${selectedBaselineTemplate.claim_id}-${field.name}`}>
                      <span>{field.required ? t('territoryWorldModel.baseline.required') : t('territoryWorldModel.baseline.optional')}</span>
                      <strong>{field.name}</strong>
                      {field.description && (
                        <p><span className="twm-research-detail-label">{t('territoryWorldModelDynamicBaselineDetailExtras.descriptionLabel')}</span>{displayText(field.description)}</p>
                      )}
                      {field.metric_use && (
                        <p><span className="twm-research-detail-label">{t('territoryWorldModelDynamicBaselineDetailExtras.metricUseLabel')}</span>{displayText(field.metric_use)}</p>
                      )}
                      {field.sanitization && (
                        <p><span className="twm-research-detail-label">{t('territoryWorldModelDynamicBaselineDetailExtras.sanitizationLabel')}</span>{displayText(field.sanitization)}</p>
                      )}
                    </article>
                  ))}
                </div>
                {!!selectedBaselineTemplate.collection_steps?.length && (
                  <p><span className="twm-research-detail-label">{t('territoryWorldModelDynamicBaselineDetailExtras.collectionStepsLabel')}</span>{compactDisplayList(selectedBaselineTemplate.collection_steps)}</p>
                )}
                <p>{compactDisplayList(
                  (baselineTemplates?.global_sanitization_rules || []).slice(0, 2),
                  displayText(selectedBaselineTemplate.production_collection?.notes),
                )}</p>
              </details>
            </>
          ) : (
            <div className="twm-empty">{t('territoryWorldModel.baseline.templateEmpty')}</div>
          )}
        </div>
        <div className="twm-baseline-imports">
          <label className="twm-file-upload">
            <span>{t('territoryWorldModel.baseline.importTwmCsv')}</span>
            <input
              type="file"
              accept=".csv,text/csv"
              disabled={busy}
              onChange={e => {
                importBaselineExportFile('twm', e.target.files?.[0]);
                e.currentTarget.value = '';
              }}
            />
            <strong><FileCheck2 size={13} />{t('territoryWorldModel.baseline.selectCsv')}</strong>
          </label>
          <label className="twm-file-upload">
            <span>{t('territoryWorldModel.baseline.importBaselineCsv')}</span>
            <input
              type="file"
              accept=".csv,text/csv"
              disabled={busy}
              onChange={e => {
                importBaselineExportFile('baseline', e.target.files?.[0]);
                e.currentTarget.value = '';
              }}
            />
            <strong><FileCheck2 size={13} />{t('territoryWorldModel.baseline.selectCsv')}</strong>
          </label>
          {baselineImport && (
            <div className="twm-baseline-import-summary">
              <span className={`status-badge ${statusClass(baselineImport.status)}`}>{statusText(baselineImport.source_role || baselineImport.status, t('territoryWorldModel.baseline.import'))}</span>
              <strong>{baselineImport.filename || baselineImport.path || '-'}</strong>
              <p>{t('territoryWorldModel.baseline.importSummary', { rows: fmt(baselineImport.row_count, 0), columns: (baselineImport.columns || []).slice(0, 4).join(', ') || t('territoryWorldModel.dataBrowser.noFields') })}</p>
            </div>
          )}
        </div>
        <div className="twm-baseline-actions">
          <button type="button" className="twm-secondary-action" onClick={runBaselineExportValidation} disabled={busy}>
            {running === 'baselineExport' || running === 'baselineImport' ? <Loader2 size={13} className="twm-spin" /> : <FileCheck2 size={13} />}
            {t('territoryWorldModel.baseline.exportValidation')}
          </button>
          <button type="button" className="twm-secondary-action" onClick={runBaselinePipeline} disabled={busy}>
            {running === 'baselinePipeline' ? <Loader2 size={13} className="twm-spin" /> : <Route size={13} />}
            {t('territoryWorldModel.baseline.evidencePipeline')}
          </button>
          <button type="button" className="twm-secondary-action" onClick={runBaselineComparison} disabled={busy}>
            {running === 'baselineCompare' ? <Loader2 size={13} className="twm-spin" /> : <BarChart3 size={13} />}
            {t('territoryWorldModel.baseline.comparison')}
          </button>
        </div>
        {baselinePipeline && (
          <div className="twm-baseline-report twm-baseline-pipeline-report">
            <div>
              <span className={`status-badge ${statusClass(baselinePipeline.status)}`}>{statusText(baselinePipeline.status, t('territoryWorldModel.status.review'))}</span>
              <strong>{displayText(baselinePipeline.pipeline_decision)}</strong>
              <p>{t('territoryWorldModel.baseline.compares', { claim: displayText(baselinePipeline.claim_id), baseline: displayText(baselinePipeline.baseline_id) })}</p>
            </div>
            <div className="twm-baseline-export-gates">
              <article>
                <span>{t('territoryWorldModel.baseline.exportValidation')}</span>
                <p>{statusText(baselinePipeline.steps?.export_validation?.status)}</p>
              </article>
              <article>
                <span>{t('territoryWorldModel.baseline.comparison')}</span>
                <p>{displayText(baselinePipeline.steps?.baseline_comparison?.status || baselinePipeline.steps?.baseline_comparison?.skipped_reason)}</p>
              </article>
              <article>
                <span>{t('territoryWorldModel.baseline.runCards')}</span>
                <p>
                  {[
                    baselinePipeline.steps?.export_validation?.scenario_card?.scenario_id ? t('territoryWorldModel.baseline.validation') : '',
                    baselinePipeline.steps?.baseline_comparison?.scenario_card?.scenario_id ? t('territoryWorldModel.baseline.comparisonShort') : '',
                  ].filter(Boolean).join(', ') || t('territoryWorldModel.common.none')}
                </p>
              </article>
            </div>
            <p>{compactDisplayList(baselinePipeline.next_actions, displayText(baselinePipeline.claim_boundary))}</p>
          </div>
        )}
        {baselineExportValidation && (
          <div className="twm-baseline-report twm-baseline-export-report">
            <div>
              <span className={`status-badge ${statusClass(baselineExportValidation.status)}`}>{statusText(baselineExportValidation.status, t('territoryWorldModel.status.review'))}</span>
              <strong>{displayText(baselineExportValidation.export_spec?.label || baselineExportValidation.export_spec?.export_type, t('territoryWorldModel.baseline.baselineExport'))}</strong>
              <p>{t('territoryWorldModel.baseline.claimJoinKey', { claim: displayText(baselineExportValidation.claim?.claim_id), key: baselineExportValidation.column_inventory?.join_key || '-' })}</p>
            </div>
            <div className="twm-baseline-sources">
              <article>
                <span>{t('territoryWorldModel.baseline.overlapSamples')}</span>
                <strong>{fmt(baselineExportValidation.coverage?.overlap_count, 0)}</strong>
                <p>{t('territoryWorldModel.baseline.coverageRatio', { ratio: fmt(baselineExportValidation.coverage?.coverage_ratio, 3) })}</p>
              </article>
              <article>
                <span>{t('territoryWorldModel.baseline.twmRows')}</span>
                <strong>{fmt(baselineExportValidation.column_inventory?.twm?.row_count, 0)}</strong>
                <p>{t('territoryWorldModel.baseline.uniqueKeys', { count: fmt(baselineExportValidation.column_inventory?.twm?.unique_join_id_count, 0) })}</p>
              </article>
              <article>
                <span>{t('territoryWorldModel.baseline.baselineRows')}</span>
                <strong>{fmt(baselineExportValidation.column_inventory?.baseline?.row_count, 0)}</strong>
                <p>{t('territoryWorldModel.baseline.uniqueKeys', { count: fmt(baselineExportValidation.column_inventory?.baseline?.unique_join_id_count, 0) })}</p>
              </article>
              <article>
                <span>{t('territoryWorldModel.baseline.comparableMetrics')}</span>
                <strong>{fmt(baselineExportValidation.parser_compatibility?.comparable_metrics?.length, 0)}</strong>
                <p>{compactDisplayList((baselineExportValidation.parser_compatibility?.comparable_metrics || []).slice(0, 2))}</p>
              </article>
            </div>
            <div className="twm-baseline-export-gates">
              <article>
                <span>{t('territoryWorldModel.baseline.blockers')}</span>
                <p>{compactDisplayList((baselineExportValidation.blocking_errors || []).slice(0, 4))}</p>
              </article>
              <article>
                <span>{t('territoryWorldModel.baseline.missingFields')}</span>
                <p>
                  {[...(baselineExportValidation.column_inventory?.missing_required?.twm || []), ...(baselineExportValidation.column_inventory?.missing_required?.baseline || [])]
                    .slice(0, 6)
                    .map(item => displayText(item))
                    .join(', ') || t('territoryWorldModel.common.none')}
                </p>
              </article>
              <article>
                <span>{t('territoryWorldModel.baseline.warnings')}</span>
                <p>{compactDisplayList((baselineExportValidation.warnings || []).slice(0, 4))}</p>
              </article>
            </div>
            <p>{compactDisplayList(baselineExportValidation.next_actions, displayText(baselineExportValidation.claim_boundary))}</p>
          </div>
        )}
        {baselineComparison && (
          <div className="twm-baseline-report">
            <div>
              <span className={`status-badge ${statusClass(baselineComparison.status)}`}>{statusText(baselineComparison.status, t('territoryWorldModel.status.review'))}</span>
              <strong>{displayText(baselineComparison.upgrade_decision)}</strong>
              <p>{t('territoryWorldModel.baseline.compares', { claim: displayText(baselineComparison.claim?.claim_id), baseline: displayText(baselineComparison.baseline?.baseline_id) })}</p>
            </div>
            <div className="twm-baseline-metrics">
              {(baselineComparison.metric_comparisons || []).slice(0, 4).map(metric => (
                <article key={metric.name}>
                  <span className={`status-badge ${statusClass(metric.status)}`}>{statusText(metric.status)}</span>
                  <strong>{displayText(metric.name)}</strong>
                  <p>{t('territoryWorldModel.baseline.metricValues', { twm: fmt(metric.twm_value, 3), baseline: fmt(metric.baseline_value, 3), delta: fmt(metric.delta, 3) })}</p>
                </article>
              ))}
            </div>
            <div className="twm-baseline-sources">
              <article>
                <span>{t('territoryWorldModel.baseline.twmMetrics')}</span>
                <strong>{displayText(baselineComparison.inputs?.twm_metrics_source, t('territoryWorldModel.common.none'))}</strong>
                <p>{t('territoryWorldModel.baseline.metricCount', { count: fmt(baselineComparison.inputs?.twm_metric_count, 0) })}</p>
              </article>
              <article>
                <span>{t('territoryWorldModel.baseline.baselineMetrics')}</span>
                <strong>{displayText(baselineComparison.inputs?.baseline_metrics_source, t('territoryWorldModel.common.none'))}</strong>
                <p>{t('territoryWorldModel.baseline.metricCount', { count: fmt(baselineComparison.inputs?.baseline_metric_count, 0) })}</p>
              </article>
              <article>
                <span>{t('territoryWorldModel.baseline.twmCases')}</span>
                <strong>{displayText(baselineComparison.inputs?.twm_case_source, t('territoryWorldModel.common.none'))}</strong>
                <p>{t('territoryWorldModel.baseline.rowCount', { count: fmt(baselineComparison.inputs?.twm_case_count, 0) })}</p>
              </article>
              <article>
                <span>{t('territoryWorldModel.baseline.baselineCases')}</span>
                <strong>{displayText(baselineComparison.inputs?.baseline_case_source, t('territoryWorldModel.common.none'))}</strong>
                <p>{t('territoryWorldModel.baseline.rowCount', { count: fmt(baselineComparison.inputs?.baseline_case_count, 0) })}</p>
              </article>
            </div>
            {Object.entries(baselineComparison.inputs?.metric_source_errors || {}).some(([, value]) => Boolean(value)) && (
              <p>
                {t('territoryWorldModel.baseline.parseErrors')}: {Object.entries(baselineComparison.inputs?.metric_source_errors || {})
                  .filter(([, value]) => Boolean(value))
                  .map(([key, value]) => `${displayText(key)}=${displayText(value)}`)
                  .join(', ')}
              </p>
            )}
            {baselineComparison.scenario_card?.scenario_id && (
              <p>{t('territoryWorldModel.baseline.runCardSummary', { id: baselineComparison.scenario_card.scenario_id, status: statusText(baselineComparison.scenario_card.status, t('territoryWorldModel.status.review')) })}</p>
            )}
            <p>{compactDisplayList((baselineComparison.evidence_gate?.missing || []).slice(0, 4), t('territoryWorldModel.baseline.noEvidenceGaps'))}</p>
          </div>
        )}
        <div className="twm-baseline-cards">
          <div className="twm-baseline-cards-head">
            <div>
              <strong>{t('territoryWorldModel.baseline.savedRunCards')}</strong>
              <span>{running === 'baselineCards' ? t('territoryWorldModel.status.loading') : `${fmt(filteredBaselineCards.length, 0)}/${fmt(baselineCards.length, 0)}`}</span>
            </div>
            <select value={baselineCardFilter} onChange={e => setBaselineCardFilter(e.target.value)} disabled={busy || !baselineCards.length}>
              <option value="all">{t('territoryWorldModel.baseline.allClaims')}</option>
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
                    <span className={`status-badge ${statusClass(card.status || meta.upgrade_decision)}`}>{displayText(card.status || meta.upgrade_decision, t('territoryWorldModel.status.review'))}</span>
                    <strong>{displayText(claimId)}</strong>
                    <button
                      type="button"
                      className="twm-card-detail-toggle"
                      onClick={() => setExpandedBaselineCardId(expanded ? '' : card.id)}
                    >
                      {expanded ? t('territoryWorldModel.baseline.collapse') : t('territoryWorldModel.baseline.details')}
                    </button>
                  </div>
                  <p>{displayText(baselineId)}</p>
                  <div className="twm-baseline-card-kpis">
                    <span>TWM {fmt(sources.twm_case_count ?? validationSources.twm?.row_count, 0)}</span>
                    <span>{t('territoryWorldModel.baseline.baselineCount', { count: fmt(sources.baseline_case_count ?? validationSources.baseline?.row_count, 0) })}</span>
                    <span>{isExportValidation ? t('territoryWorldModel.baseline.overlapCount', { count: fmt(meta.coverage?.overlap_count, 0) }) : errors.length ? t('territoryWorldModel.baseline.parseErrorCount', { count: fmt(errors.length, 0) }) : t('territoryWorldModel.baseline.parseOk')}</span>
                  </div>
                  <p>{isExportValidation ? t('territoryWorldModel.baseline.joinCoverage', { key: meta.column_inventory?.join_key || '-', ratio: fmt(meta.coverage?.coverage_ratio, 3) }) : compactDisplayList((meta.evidence_gate?.missing || []).slice(0, 3), t('territoryWorldModel.baseline.noEvidenceGaps'))}</p>
                  {expanded && (
                    <div className="twm-baseline-card-detail">
                      {isExportValidation ? (
                        <>
                          <div>
                            <span>{t('territoryWorldModel.baseline.coverage')}</span>
                            <strong>{fmt(meta.coverage?.overlap_count, 0)} · {fmt(meta.coverage?.coverage_ratio, 3)}</strong>
                          </div>
                          <div>
                            <span>{t('territoryWorldModel.baseline.missingFields')}</span>
                            <p>{compactDisplayList([...(meta.column_inventory?.missing_required?.twm || []), ...(meta.column_inventory?.missing_required?.baseline || []), ...(meta.column_inventory?.missing_required?.claim_parser || [])])}</p>
                          </div>
                          <div>
                            <span>{t('territoryWorldModel.baseline.comparableMetrics')}</span>
                            <p>{compactDisplayList(meta.parser_compatibility?.comparable_metrics)}</p>
                          </div>
                          <div>
                            <span>{t('territoryWorldModel.baseline.blockersWarnings')}</span>
                            <p>{compactDisplayList([...(meta.blocking_errors || []), ...(meta.warnings || [])])}</p>
                          </div>
                        </>
                      ) : (
                        <>
                          {(meta.metric_comparisons || []).slice(0, 3).map(metric => (
                            <div key={`${card.id}-${metric.name}`}>
                              <span>{displayText(metric.name)}</span>
                              <strong>{statusText(metric.status)}</strong>
                              <p>{t('territoryWorldModel.baseline.metricValues', { twm: fmt(metric.twm_value, 3), baseline: fmt(metric.baseline_value, 3), delta: fmt(metric.delta, 3) })}</p>
                            </div>
                          ))}
                          <div>
                            <span>{t('territoryWorldModel.baseline.evidenceRequirements')}</span>
                            <p>{compactDisplayList(meta.evidence_gate?.missing, t('territoryWorldModel.baseline.noEvidenceGaps'))}</p>
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
            {!filteredBaselineCards.length && (
              <div className="twm-empty">{selectedProjectId ? t('territoryWorldModel.baseline.noSavedCards') : t('territoryWorldModel.baseline.selectProjectForCards')}</div>
            )}
          </div>
        </div>
      </section>

      <section className="twm-section twm-data-foundation-panel">
        <div className="twm-section-head">
          <FileCheck2 size={14} />
          <h4>{t('territoryWorldModel.dataFoundation.title')}</h4>
          <span className={`status-badge ${statusClass(dataReadiness.status || dataFoundation.status)}`}>
            {running === 'dataFoundation' ? t('territoryWorldModel.status.loading') : statusText(dataReadiness.status || dataFoundation.status, t('territoryWorldModel.status.review'))}
          </span>
        </div>
        <div className="twm-data-verdict">{displayText(dataReadiness.verdict)}</div>
        <div className="twm-data-kpis">
          <div><span>{t('territoryWorldModel.dataFoundation.productionHistory')}</span><strong>{fmt(validationSnapshot.production_ready_observed_history_rows, 0)}</strong></div>
          <div><span>{t('territoryWorldModel.dataFoundation.policyHistory')}</span><strong>{fmt(validationSnapshot.production_policy_history_row_count, 0)}</strong></div>
          <div><span>{t('territoryWorldModel.dataFoundation.structuralFixture')}</span><strong>{fmt(validationSnapshot.structural_fixture?.row_count, 0)}</strong></div>
          <div><span>{t('territoryWorldModel.dataFoundation.syntheticExperiment')}</span><strong>{fmt(validationSnapshot.synthetic_experiment?.row_count, 0)}</strong></div>
        </div>
        <div className="twm-data-layout">
          <div className="twm-data-card">
            <span>{t('territoryWorldModel.dataFoundation.testDatasets')}</span>
            {(dataFoundation.datasets || []).map(dataset => (
              <article key={dataset.id}>
                <strong>{displayText(dataset.label)}</strong>
                <p>{displayText(dataset.positioning || dataset.nature)}</p>
                <div>
                  <code>{dataset.not_for_production ? t('territoryWorldModel.dataFoundation.demoRegressionData') : t('territoryWorldModel.dataFoundation.productionCandidateData')}</code>
                  {(dataset.files || []).map(file => (
                    <code key={`${dataset.id}-${file.path}`}>{file.path}: {fmt(file.count, 0)}</code>
                  ))}
                </div>
              </article>
            ))}
          </div>
          <div className="twm-data-card">
            <span>{t('territoryWorldModel.dataFoundation.supportedProblems')}</span>
            {(dataFoundation.supported_problems || []).map(item => (
              <article key={item.problem}>
                <strong>{displayText(item.problem)}</strong>
                <p>{displayText(item.support)}</p>
              </article>
            ))}
          </div>
          <div className="twm-data-card">
            <span>{t('territoryWorldModel.dataFoundation.unsupportedClaims')}</span>
            {(dataFoundation.unsupported_claims || []).map(item => (
              <article key={item.claim}>
                <strong>{displayText(item.claim)}</strong>
                <p>{displayText(item.reason)}</p>
              </article>
            ))}
          </div>
          <div className="twm-data-card">
            <span>{t('territoryWorldModel.dataFoundation.nextRealData')}</span>
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
            <strong>{t('territoryWorldModel.dataFoundation.keyBlockers')}</strong>
            <span>{t('territoryWorldModel.dataFoundation.blockersDescription')}</span>
          </div>
          <div className="twm-data-blocker-list">
            {(dataReadiness.key_blockers || []).map(item => (
              <article key={item}>
                <AlertTriangle size={12} />
                <span>{displayText(item)}</span>
              </article>
            ))}
            {!(dataReadiness.key_blockers || []).length && <div className="twm-empty">{t('territoryWorldModel.roadmap.noBlockers')}</div>}
          </div>
        </div>
        <div className="twm-data-detail-section">
          <div className="twm-data-detail-head">
            <strong>{t('territoryWorldModel.dataFoundation.fullInventory')}</strong>
            <span>{t('territoryWorldModel.dataFoundation.inventorySummary', { count: fmt((dataFoundation.datasets || []).length, 0) })}</span>
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
                    {dataset.not_for_production ? t('territoryWorldModel.dataBrowser.demoNonProduction') : t('territoryWorldModel.dataBrowser.productionCandidate')}
                  </span>
                </div>
                <p>{displayText(dataset.positioning || dataset.nature || dataset.path)}</p>
                <div className="twm-data-dataset-kpis">
                  <span>{t('territoryWorldModel.dataFoundation.totalCount', { count: fmt(dataset.total_count, 0) })}</span>
                  <span>{t('territoryWorldModel.dataFoundation.syntheticCount', { count: fmt(dataset.synthetic_count, 0) })}</span>
                  <span>{t('territoryWorldModel.dataFoundation.nonProductionCount', { count: fmt(dataset.not_for_production_count, 0) })}</span>
                  {dataset.path && <span>{dataset.path}</span>}
                </div>
                <div className="twm-data-file-grid">
                  {(dataset.files || []).map(file => (
                    <div key={`${dataset.id}-detail-${file.path}`}>
                      <code>{file.path}</code>
                      <span>
                        {t('territoryWorldModel.dataFoundation.fileCounts', { count: fmt(file.count, 0), unit: displayText(file.unit, t('territoryWorldModel.dataBrowser.rows')), synthetic: fmt(file.synthetic_count, 0), nonProduction: fmt(file.not_for_production_count, 0) })}
                      </span>
                    </div>
                  ))}
                  {!(dataset.files || []).length && <div className="twm-empty">{t('territoryWorldModel.dataFoundation.noFileDetails')}</div>}
                </div>
              </article>
            ))}
          </div>
        </div>
        <div className="twm-data-detail-section">
          <div className="twm-data-detail-head">
            <strong>{t('territoryWorldModel.dataFoundation.validationSnapshot')}</strong>
            <span>{t('territoryWorldModel.dataFoundation.validationDescription')}</span>
          </div>
          <div className="twm-data-evidence-grid">
            <article>
              <span>{t('territoryWorldModel.dataFoundation.productionHistory')}</span>
              <strong>{fmt(validationSnapshot.production_ready_observed_history_rows, 0)}</strong>
              <p>{t('territoryWorldModel.dataFoundation.policyActionsSummary', { status: statusText(validationSnapshot.production_policy_history_status, t('territoryWorldModel.dataFoundation.notProvided')), count: fmt(validationSnapshot.production_policy_history_row_count, 0) })}</p>
            </article>
            <article>
              <span>{t('territoryWorldModel.dataFoundation.policyActionMask')}</span>
              <strong>{fmt(validationSnapshot.production_policy_allowed_count, 0)} / {fmt(validationSnapshot.production_policy_blocked_count, 0)}</strong>
              <p>{t('territoryWorldModel.dataFoundation.allowedBlocked')}</p>
            </article>
            <article>
              <span>{t('territoryWorldModel.dataFoundation.structuralFixture')}</span>
              <strong>{fmt(validationSnapshot.structural_fixture?.row_count, 0)}</strong>
              <p>{t('territoryWorldModel.dataFoundation.pairStatus', { count: fmt(validationSnapshot.structural_fixture?.pair_count, 0), status: statusText(validationSnapshot.structural_fixture?.structural_status) })}</p>
            </article>
            <article>
              <span>{t('territoryWorldModel.dataFoundation.syntheticExperiment')}</span>
              <strong>{fmt(validationSnapshot.synthetic_experiment?.row_count, 0)}</strong>
              <p>{t('territoryWorldModel.dataFoundation.regionPeriods', { regions: fmt(validationSnapshot.synthetic_experiment?.region_count, 0), periods: fmt(validationSnapshot.synthetic_experiment?.period_count, 0) })}</p>
            </article>
            <article>
              <span>{t('territoryWorldModel.dataFoundation.localHistory')}</span>
              <strong>{statusText(validationSnapshot.local_observed_history?.status, t('territoryWorldModel.dataFoundation.notProvided'))}</strong>
              <p>{t('territoryWorldModel.dataFoundation.localHistorySummary', { missing: compactDisplayList(validationSnapshot.local_observed_history?.missing, t('territoryWorldModel.dataFoundation.noMissingItems')), edges: fmt(validationSnapshot.local_observed_history?.relation_neighbor_edge_count, 0) })}</p>
            </article>
            <article>
              <span>{t('territoryWorldModel.dataFoundation.reviewContext')}</span>
              <strong>{t('territoryWorldModel.dataFoundation.projectCount', { count: fmt(validationSnapshot.project_review_context?.project_count, 0) })}</strong>
              <p>{t('territoryWorldModel.dataFoundation.reviewSummary', { rules: fmt(validationSnapshot.project_review_context?.rule_eval_count, 0), tasks: fmt(validationSnapshot.project_review_context?.review_task_count, 0) })}</p>
            </article>
            <article>
              <span>{t('territoryWorldModel.dataFoundation.externalSupport')}</span>
              <strong>{statusText(validationSnapshot.external_support?.paper7_caliper_matched_status, t('territoryWorldModel.dataFoundation.reference'))}</strong>
              <p>{t('territoryWorldModel.dataFoundation.pairBoundary', { count: fmt(validationSnapshot.external_support?.paper7_caliper_matched_pair_count, 0), boundary: displayText(validationSnapshot.external_support?.boundary) })}</p>
            </article>
            <article>
              <span>{t('territoryWorldModel.dataFoundation.syntheticSplit')}</span>
              <strong>{Object.entries(validationSnapshot.synthetic_experiment?.split_counts || {}).map(([key, value]) => `${displayText(key)} ${fmt(value, 0)}`).join(' · ') || t('territoryWorldModel.common.none')}</strong>
              <p>{t('territoryWorldModel.dataFoundation.actionMaskSummary', { allowed: fmt(validationSnapshot.synthetic_experiment?.action_mask_allowed_count, 0), blocked: fmt(validationSnapshot.synthetic_experiment?.action_mask_blocked_count, 0) })}</p>
            </article>
          </div>
        </div>
        <div className="twm-data-detail-section">
          <div className="twm-data-detail-head">
            <strong>{t('territoryWorldModel.dataFoundation.problemDataFit')}</strong>
            <span>{t('territoryWorldModel.dataFoundation.fitDescription')}</span>
          </div>
          <div className="twm-data-fit-list">
            {(dataFoundation.problem_data_fit || []).map(item => (
              <article key={item.business_problem}>
                <div>
                  <strong>{displayText(item.business_problem)}</strong>
                  <span className="status-badge proposed">{displayText(item.current_fit, t('territoryWorldModel.dataFoundation.pendingAssessment'))}</span>
                </div>
                <p>{displayText(item.why)}</p>
                <div>
                  <span>{t('territoryWorldModel.dataFoundation.safeOutput', { output: displayText(item.safe_output) })}</span>
                  <span>{t('territoryWorldModel.dataFoundation.unsafeOutput', { output: displayText(item.unsafe_output) })}</span>
                </div>
              </article>
            ))}
          </div>
        </div>
        <div className="twm-data-detail-section">
          <div className="twm-data-detail-head">
            <strong>{t('territoryWorldModel.dataFoundation.sourceReports')}</strong>
            <span>{t('territoryWorldModel.dataFoundation.sourceDescription')}</span>
          </div>
          <div className="twm-data-source-list">
            {Object.entries(dataFoundation.source_reports || {}).map(([key, value]) => (
              <article key={key}>
                <span>{displayText(key)}</span>
                <code>{value}</code>
              </article>
            ))}
            {!Object.keys(dataFoundation.source_reports || {}).length && <div className="twm-empty">{t('territoryWorldModel.dataFoundation.noSourceReports')}</div>}
          </div>
        </div>
        {(dataFoundation.mentor_answer?.short_answer || dataFoundation.mentor_answer?.research_judgment) && (
          <div className="twm-data-mentor-note">
            <strong>{t('territoryWorldModel.dataFoundation.judgment')}</strong>
            <p>{displayText(dataFoundation.mentor_answer?.short_answer)}</p>
            <p>{displayText(dataFoundation.mentor_answer?.research_judgment)}</p>
          </div>
        )}
      </section>

      <section className="twm-section twm-pilot-readiness-panel">
        <div className="twm-section-head">
          <CheckCircle2 size={14} />
          <h4>{t('territoryWorldModel.pilot.title')}</h4>
          <span className={`status-badge ${statusClass(pilotReadinessMatrix?.overall_status)}`}>
            {running === 'pilotReadiness' ? t('territoryWorldModel.status.loading') : statusText(pilotReadinessMatrix?.overall_status, t('territoryWorldModel.common.pendingLoad'))}
          </span>
        </div>
        <div className="twm-data-kpis">
          <div>
            <span>{t('territoryWorldModel.pilot.dimensions')}</span>
            <strong>{fmt(pilotReadinessDimensions.length, 0)}</strong>
          </div>
          <div>
            <span>{t('territoryWorldModel.pilot.productionGate')}</span>
            <strong>{statusText(pilotReadinessDimensions.find(item => item.id === 'production_gate')?.status, t('territoryWorldModel.common.pendingLoad'))}</strong>
          </div>
          <div>
            <span>{t('territoryWorldModel.pilot.syntheticSubstitution')}</span>
            <strong>{yesNo(pilotReadinessMatrix?.strict_policy?.synthetic_data_can_satisfy_production_gate)}</strong>
          </div>
          <div>
            <span>{t('territoryWorldModel.pilot.testDataPlan')}</span>
            <strong>{statusText(pilotReadinessMatrix?.test_data_plan?.status, t('territoryWorldModel.common.pendingLoad'))}</strong>
          </div>
        </div>
        <div className="twm-data-fit-list">
          {pilotReadinessDimensions.map(item => (
            <article key={`pilot-readiness-${item.id}`}>
              <div>
                <strong>{item.id === 'production_gate' ? t('territoryWorldModel.pilot.productionGate') : displayText(item.label || item.id)}</strong>
                <span className={`status-badge ${statusClass(item.status)}`}>{statusText(item.status, t('territoryWorldModel.status.review'))}</span>
              </div>
              <p>{t('territoryWorldModel.pilot.scoreSummary', { score: fmt(item.score, 2), gaps: compactDisplayList((item.missing || []).slice(0, 3), t('territoryWorldModel.pilot.noGaps')) })}</p>
              <div>
                {(item.test_data_work || []).slice(0, 2).map(work => (
                  <span key={`pilot-readiness-${item.id}-${work}`}>{displayText(work)}</span>
                ))}
              </div>
            </article>
          ))}
          {!pilotReadinessDimensions.length && <div className="twm-empty">{t('territoryWorldModel.pilot.empty')}</div>}
        </div>
      </section>

      <section className="twm-section twm-rule-fixture-panel">
        <div className="twm-section-head">
          <ShieldCheck size={14} />
          <h4>{t('territoryWorldModel.ruleCoverage.title')}</h4>
          <span className={`status-badge ${statusClass(ruleFixtureCoverageMatrix?.overall_status)}`}>
            {running === 'ruleFixtureCoverage' ? t('territoryWorldModel.status.loading') : statusText(ruleFixtureCoverageMatrix?.overall_status, t('territoryWorldModel.common.pendingLoad'))}
          </span>
        </div>
        <div className="twm-data-kpis">
          <div>
            <span>{t('territoryWorldModel.ruleCoverage.hardRules')}</span>
            <strong>{fmt(ruleFixtureCoverageMatrix?.summary?.hard_rule_count, 0)}</strong>
          </div>
          <div>
            <span>{t('territoryWorldModel.ruleCoverage.boundaryGaps')}</span>
            <strong>{fmt(ruleFixtureCoverageMatrix?.summary?.rules_with_boundary_gap, 0)}</strong>
          </div>
          <div>
            <span>{t('territoryWorldModel.ruleCoverage.productionFixtures')}</span>
            <strong>{fmt(ruleFixtureCoverageMatrix?.summary?.production_ready_fixture_count, 0)}</strong>
          </div>
          <div>
            <span>{t('territoryWorldModel.ruleCoverage.syntheticAccepted')}</span>
            <strong>{yesNo(ruleFixtureCoverageMatrix?.coverage_policy?.synthetic_fixture_can_satisfy_production_acceptance)}</strong>
          </div>
        </div>
        <div className="twm-data-file-grid">
          {ruleFixtureRows.map(rule => {
            const categories = Object.entries(rule.categories || {});
            return (
              <div key={`rule-fixture-${rule.rule_code}`}>
                <code>{rule.rule_code}</code>
                <span>{t('territoryWorldModel.ruleCoverage.ruleGaps', { rule: displayText(rule.rule_name_zh || rule.status), gaps: compactDisplayList(rule.missing_categories, t('territoryWorldModel.common.none')) })}</span>
                <span>{categories.map(([name, item]) => `${displayText(name)}=${item.covered ? fmt(item.fixture_count, 0) : t('territoryWorldModel.ruleCoverage.missing')}`).join(' · ')}</span>
              </div>
            );
          })}
          {!ruleFixtureRows.length && <div className="twm-empty">{t('territoryWorldModel.ruleCoverage.empty')}</div>}
        </div>
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
            <h4>{t('territoryWorldModel.workspace.title')}</h4>
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
                {t(`territoryWorldModel.workspace.presets.${item.key}`, { defaultValue: item.label })}
              </button>
            ))}
          </div>

          <div className="twm-form-grid">
            <label>
              <span>{t('territoryWorldModel.workspace.projectName')}</span>
              <input value={projectName} onChange={e => setProjectName(e.target.value)} disabled={busy} />
            </label>
            <label>
              <span>{t('territoryWorldModel.workspace.regionCode')}</span>
              <input value={regionCode} onChange={e => setRegionCode(e.target.value)} disabled={busy} />
            </label>
          </div>

          <button type="button" className="twm-primary-action" onClick={createProject} disabled={busy || !projectName.trim()}>
            {running === 'create' ? <Loader2 size={13} className="twm-spin" /> : <FileCheck2 size={13} />}
            {t('territoryWorldModel.workspace.createProject')}
          </button>

          <label className="twm-field">
            <span>{t('territoryWorldModel.workspace.selectProject')}</span>
            <select value={selectedProjectId} onChange={e => setSelectedProjectId(e.target.value)} disabled={busy || !projects.length}>
              <option value="">{t('territoryWorldModel.common.notSelected')}</option>
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
            <span>{t('territoryWorldModel.workspace.bundle')}</span>
            <input value={bundleDir} onChange={e => setBundleDir(e.target.value)} disabled={busy} />
          </label>
          <label className="twm-field">
            <span>{t('territoryWorldModel.workspace.stateLabel')}</span>
            <input value={stateLabel} onChange={e => setStateLabel(e.target.value)} disabled={busy} />
          </label>
          <label className="twm-check">
            <input type="checkbox" checked={includeAuxiliary} onChange={e => setIncludeAuxiliary(e.target.checked)} disabled={busy} />
            {t('territoryWorldModel.workspace.includeAuxiliary')}
          </label>

          <button type="button" className="twm-primary-action" onClick={buildState} disabled={busy || !selectedProjectId || !bundleDir.trim()}>
            {running === 'build' ? <Loader2 size={13} className="twm-spin" /> : <Play size={13} />}
            {t('territoryWorldModel.workspace.buildState')}
          </button>

          <label className="twm-field">
            <span>{t('territoryWorldModel.workspace.selectState')}</span>
            <select value={selectedStateId} onChange={e => setSelectedStateId(e.target.value)} disabled={busy || !states.length}>
              <option value="">{t('territoryWorldModel.common.notSelected')}</option>
              {states.map(state => (
                <option value={state.id} key={state.id}>
                  {t('territoryWorldModel.workspace.stateOption', { label: state.label || state.id, count: fmt(state.object_count, 0) })}
                </option>
              ))}
            </select>
          </label>
        </section>

        <section className="twm-section">
          <div className="twm-section-head">
            <SlidersHorizontal size={14} />
            <h4>{t('territoryWorldModel.simulation.title')}</h4>
          </div>

          <div className="twm-state-summary">
            <div>
              <span>{t('territoryWorldModel.simulation.state')}</span>
              <strong>{selectedState?.label || selectedStateId || '-'}</strong>
            </div>
            <div>
              <span>{t('territoryWorldModel.simulation.objects')}</span>
              <strong>{fmt(selectedState?.object_count ?? stateDetail?.state_version?.object_count, 0)}</strong>
            </div>
            <div>
              <span>{t('territoryWorldModel.simulation.relations')}</span>
              <strong>{fmt(selectedState?.relation_count ?? stateDetail?.state_version?.relation_count, 0)}</strong>
            </div>
          </div>

          <button type="button" className="twm-secondary-action" onClick={evaluateRules} disabled={busy || !selectedStateId}>
            {running === 'evaluate' ? <Loader2 size={13} className="twm-spin" /> : <ShieldCheck size={13} />}
            {t('territoryWorldModel.simulation.checkRules')}
          </button>

          <div className="twm-result-strip">
            <div><span>{t('territoryWorldModel.simulation.hits')}</span><strong>{fmt(summary.hit_count ?? hits.length, 0)}</strong></div>
            <div><span>{t('territoryWorldModel.simulation.evidence')}</span><strong>{fmt(summary.evidence_item_count ?? auditResult?.evidence_gate_summary?.evidence_item_count, 0)}</strong></div>
            <div><span>{t('territoryWorldModel.simulation.dataRisk')}</span><strong>{fmt(summary.data_quality_hit_count, 0)}</strong></div>
            <div><span>{t('territoryWorldModel.simulation.approvalRisk')}</span><strong>{fmt(summary.approval_consistency_hit_count, 0)}</strong></div>
          </div>

          <div className="twm-form-grid">
            <label>
              <span>{t('territoryWorldModel.simulation.action')}</span>
              <select value={actionType} onChange={e => setActionType(e.target.value)} disabled={busy}>
                <option value="inspect">{t('territoryWorldModel.actions.types.inspect')}</option>
                <option value="protect">{t('territoryWorldModel.actions.types.protect')}</option>
                <option value="allocate">{t('territoryWorldModel.actions.types.allocate')}</option>
                <option value="convert">{t('territoryWorldModel.actions.types.convert')}</option>
                <option value="restore">{t('territoryWorldModel.actions.types.restore')}</option>
              </select>
            </label>
            <label>
              <span>{t('territoryWorldModel.simulation.targetRole')}</span>
              <select value={targetRole} onChange={e => setTargetRole(e.target.value)} disabled={busy}>
                <option value="project">{t('territoryWorldModel.roles.project')}</option>
                <option value="parcel">{t('territoryWorldModel.roles.parcel')}</option>
                <option value="scenario">{t('territoryWorldModel.roles.scenario')}</option>
              </select>
            </label>
            <label>
              <span>{t('territoryWorldModel.simulation.evidenceCoverage')}</span>
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
              <span>{t('territoryWorldModel.simulation.horizon')}</span>
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
            <span>{t('territoryWorldModel.simulation.scenario')}</span>
            <input value={scenario} onChange={e => setScenario(e.target.value)} disabled={busy} />
          </label>

          <div className="twm-action-grid">
            <button type="button" className="twm-secondary-action" onClick={runForecast} disabled={busy || !selectedStateId}>
              {running === 'forecast' ? <Loader2 size={13} className="twm-spin" /> : <GitBranch size={13} />}
              {t('territoryWorldModel.simulation.forecast')}
            </button>
            <button type="button" className="twm-secondary-action" onClick={runValidation} disabled={busy || !selectedStateId}>
              {running === 'validation' ? <Loader2 size={13} className="twm-spin" /> : <CheckCircle2 size={13} />}
              {t('territoryWorldModel.simulation.validate')}
            </button>
            <button type="button" className="twm-secondary-action" onClick={runAudit} disabled={busy || !selectedStateId}>
              {running === 'audit' ? <Loader2 size={13} className="twm-spin" /> : <FileCheck2 size={13} />}
              {t('territoryWorldModel.simulation.audit')}
            </button>
          </div>

          <label className="twm-field">
            <span>{t('territoryWorldModel.simulation.optimizationBundle')}</span>
            <input value={optimizationDir} onChange={e => setOptimizationDir(e.target.value)} disabled={busy} />
          </label>
          <div className="twm-action-grid">
            <button type="button" className="twm-secondary-action" onClick={loadCandidates} disabled={busy || !selectedStateId || !optimizationDir.trim()}>
              {running === 'candidates' ? <Loader2 size={13} className="twm-spin" /> : <BarChart3 size={13} />}
              {t('territoryWorldModel.simulation.loadCandidates')}
            </button>
            <button type="button" className="twm-primary-action" onClick={runBeam} disabled={busy || !selectedStateId || !optimizationDir.trim()}>
              {running === 'beam' ? <Loader2 size={13} className="twm-spin" /> : <Route size={13} />}
              {t('territoryWorldModel.simulation.comparePlans')}
            </button>
          </div>

          {multiHorizonTrajectories.length > 0 && (
            <div className="twm-multi-horizon-comparison" data-testid="twm-multi-horizon-comparison">
              <div className="twm-multi-horizon-summary">
                <strong>{t('territoryWorldModel.simulation.multiHorizon.title')}</strong>
                <span>{t('territoryWorldModel.simulation.multiHorizon.planPeriods', { plans: fmt(multiHorizonComparison.legal_candidate_count, 0), periods: fmt(multiHorizonComparison.horizon, 0) })}</span>
                <span>{t('territoryWorldModel.simulation.multiHorizon.transitionCalls', { count: fmt(executionAccounting.simulator_call_count, 0) })}</span>
                <span>{t('territoryWorldModel.simulation.multiHorizon.constraintRecomputations', { count: fmt(executionAccounting.hard_constraint_recomputation_count, 0) })}</span>
                <span>{spatialSimulatorBackend.learned_dynamics ? t('territoryWorldModel.simulation.multiHorizon.learnedDynamics') : t('territoryWorldModel.simulation.multiHorizon.ruleBackend')}</span>
                <span>
                  {spatialSimulatorBackend.execution_mode === 'online_recursive_transition_loop'
                    && spatialSimulatorBackend.precomputed_period_states_consumed === false
                    ? t('territoryWorldModel.simulation.multiHorizon.onlineExecution')
                    : t('territoryWorldModel.simulation.multiHorizon.executionReview')}
                </span>
              </div>
              <div className="twm-multi-horizon-boundary">
                {t('territoryWorldModel.simulation.multiHorizon.boundary')}
              </div>
              <div className="twm-multi-horizon-table-wrap">
                <table className="twm-multi-horizon-table">
                  <thead>
                    <tr>
                      <th>{t('territoryWorldModel.simulation.multiHorizon.rank')}</th>
                      <th>{t('territoryWorldModel.simulation.multiHorizon.candidate')}</th>
                      <th>{t('territoryWorldModel.simulation.multiHorizon.periodStates')}</th>
                      <th>{t('territoryWorldModel.simulation.multiHorizon.utility')}</th>
                      <th>{t('territoryWorldModel.simulation.multiHorizon.risk')}</th>
                      <th>{t('territoryWorldModel.simulation.multiHorizon.confidence')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {multiHorizonTrajectories.map((trajectory: any) => (
                      <tr key={trajectory.candidate_id}>
                        <td><strong>{fmt(trajectory.rank, 0)}</strong></td>
                        <td>
                          <strong>{trajectory.scenario_name || trajectory.candidate_id}</strong>
                          <code>{trajectory.candidate_id}</code>
                        </td>
                        <td>
                          <div className="twm-period-track">
                            {(trajectory.periods || []).map((period: any) => (
                              <span
                                key={`${trajectory.candidate_id}-${period.period}`}
                                className={(period.constraint_recheck || {}).passed ? 'pass' : 'blocked'}
                                title={t('territoryWorldModel.simulation.multiHorizon.periodTitle', { parent: (period.state_writeback || {}).from_state_sha256 || '-', current: period.state_sha256 || '-', geometry: period.geometry_sha256 || '-' })}
                              >
                                {t('territoryWorldModel.simulation.multiHorizon.period', { period: fmt(period.period, 0) })}<br />
                                {t('territoryWorldModel.simulation.multiHorizon.actions', { count: fmt(period.action_count, 0) })}<br />
                                {t('territoryWorldModel.simulation.multiHorizon.objective', { value: fmt((period.outcome_metrics || {}).spatial_objective_score, 3) })}<br />
                                {(period.constraint_recheck || {}).passed ? t('territoryWorldModel.simulation.multiHorizon.constraintPassed') : t('territoryWorldModel.simulation.multiHorizon.constraintBlocked')}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td>{fmt(trajectory.discounted_cumulative_utility, 3)}</td>
                        <td>{fmt(trajectory.max_constraint_risk, 3)}</td>
                        <td>{fmt(trajectory.minimum_confidence, 3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      </div>

      <div className="twm-main-grid twm-results-grid">
        <section className="twm-section">
          <div className="twm-section-head">
            <AlertTriangle size={14} />
            <h4>{t('territoryWorldModel.results.ruleHits')}</h4>
            <span className={`status-badge ${hits.length ? 'warning' : 'success'}`}>{hits.length ? t('territoryWorldModel.results.pendingHits', { count: fmt(hits.length, 0) }) : t('territoryWorldModel.common.none')}</span>
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
            {!hits.length && <div className="twm-empty">{t('territoryWorldModel.results.noRuleHits')}</div>}
          </div>
        </section>

        <section className="twm-section">
          <div className="twm-section-head">
            <CheckCircle2 size={14} />
            <h4>{t('territoryWorldModel.results.claimsAndPlans')}</h4>
            <span className={`status-badge ${statusClass(validationResult?.overall_status || beamResult?.status)}`}>
              {statusText(validationResult?.overall_status || beamResult?.status, t('territoryWorldModel.common.notRun'))}
            </span>
          </div>

          <div className="twm-result-strip">
            <div><span>{t('territoryWorldModel.results.claimLevel')}</span><strong>{statusText(claim.current_level)}</strong></div>
            <div><span>{t('territoryWorldModel.results.planningBenefit')}</span><strong>{fmt(forecast.planning_utility_delta ?? beamSelected.utility, 3)}</strong></div>
            <div><span>{t('territoryWorldModel.results.constraintRisk')}</span><strong>{fmt(forecast.constraint_violation_probability ?? beamSelected.risk, 3)}</strong></div>
            <div><span>{t('territoryWorldModel.results.confidence')}</span><strong>{fmt(forecast.uncertainty?.confidence ?? beamSelected.confidence, 3)}</strong></div>
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
            <div><span>{t('territoryWorldModel.results.candidates')}</span><strong>{fmt(candidateSummary.candidate_count, 0)}</strong></div>
            <div><span>{t('territoryWorldModel.results.legalFeasible')}</span><strong>{fmt(candidateSummary.legal_feasible_count, 0)}</strong></div>
            <div><span>{t('territoryWorldModel.results.blockedPlans')}</span><strong>{fmt(candidateSummary.blocked_count, 0)}</strong></div>
            <div><span>{t('territoryWorldModel.results.recommendedPlan')}</span><strong>{beamSelected.candidate_id || '-'}</strong></div>
          </div>
        </section>
      </div>
        </div>
      )}

      {activeSubTab === 'graph' && (
        <div
          className="twm-subtab-panel"
          role="tabpanel"
          id="twm-subtab-graph"
          aria-labelledby="twm-subtab-control-graph"
        >
          <section className="twm-section twm-state-graph-panel">
            <div className="twm-section-head">
              <GitBranch size={14} />
              <h4>{t('territoryWorldModel.graph.title')}</h4>
              <span className={`status-badge ${stateGraph?.graph_store?.full_graph_persisted ? 'success' : 'proposed'}`}>
                {stateGraph?.graph_store?.full_graph_persisted ? t('territoryWorldModel.graph.persisted') : t('territoryWorldModel.common.pendingLoad')}
              </span>
            </div>
            <div className="twm-state-graph-actions">
              <button type="button" className="twm-primary-action" onClick={() => loadStateGraph('')} disabled={busy || !selectedStateId}>
                {running === 'stateGraph' ? <Loader2 size={13} className="twm-spin" /> : <GitBranch size={13} />}
                {t('territoryWorldModel.graph.loadFull')}
              </button>
              <span>
                {t('territoryWorldModel.graph.description')}
              </span>
            </div>

            <div className="twm-state-graph-kpis">
              <div><span>{t('territoryWorldModel.graph.fullNodes')}</span><strong>{fmt(stateGraphCounts.total_node_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.graph.fullEdges')}</span><strong>{fmt(stateGraphCounts.total_edge_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.graph.stateObjects')}</span><strong>{fmt(stateGraphCounts.state_object_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.graph.stateRelations')}</span><strong>{fmt(stateGraphCounts.state_relation_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.graph.ruleDecisions')}</span><strong>{fmt(stateGraphCounts.rule_hit_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.graph.supportMaterials')}</span><strong>{fmt(stateGraphCounts.support_material_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.graph.reviewTasks')}</span><strong>{fmt(stateGraphCounts.review_task_count, 0)}</strong></div>
              <div><span>{t('territoryWorldModel.graph.browserPayload')}</span><strong>{stateGraphFullLoaded ? t('territoryWorldModel.graph.fullPayload') : t('territoryWorldModel.graph.focusedSubgraph')}</strong></div>
            </div>

            {stateGraph && (
              <div className="twm-state-graph-layout">
                <div className="twm-state-graph-canvas">
                  <div className="twm-state-graph-canvas-head">
                    <strong>{t('territoryWorldModel.graph.linkedView')}</strong>
                    <span>
                      {t('territoryWorldModel.graph.renderedSummary', {
                        renderedNodes: fmt(stateGraphRenderPolicy.rendered_node_count, 0),
                        fullNodes: fmt(stateGraphRenderPolicy.full_graph_node_count, 0),
                        renderedEdges: fmt(stateGraphRenderPolicy.rendered_edge_count, 0),
                        fullEdges: fmt(stateGraphRenderPolicy.full_graph_edge_count, 0),
                      })}
                    </span>
                  </div>
                  <svg
                    className="twm-state-graph-svg"
                    viewBox={`0 0 ${stateGraphPositioned.width} ${stateGraphPositioned.height}`}
                    height={stateGraphPositioned.height}
                    role="img"
                    aria-label={t('territoryWorldModel.graph.ariaLabel')}
                  >
                    {stateGraphPositioned.edges.map((edge: any) => (
                      <g key={edge.id || `${edge.source}-${edge.target}`}>
                        <line
                          x1={edge.sourceNode.x}
                          y1={edge.sourceNode.y}
                          x2={edge.targetNode.x}
                          y2={edge.targetNode.y}
                          className={`twm-state-graph-edge ${edge.kind || ''}`}
                        />
                        <text
                          x={(edge.sourceNode.x + edge.targetNode.x) / 2}
                          y={(edge.sourceNode.y + edge.targetNode.y) / 2 - 3}
                          className="twm-state-graph-edge-label"
                        >
                          {displayText(edge.label || edge.kind)}
                        </text>
                      </g>
                    ))}
                    {stateGraphPositioned.nodes.map(node => (
                      <g
                        key={node.id}
                        className={`twm-state-graph-node ${stateGraphNodeClass(node)} ${stateGraphFocusNodeId === node.id ? 'active' : ''}`}
                        role="button"
                        tabIndex={0}
                        onClick={() => focusStateGraphNode(node)}
                        onKeyDown={event => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            focusStateGraphNode(node);
                          }
                        }}
                      >
                        <rect
                          className="twm-state-graph-hitbox"
                          x={node.x - 18}
                          y={node.y - 18}
                          width={168}
                          height={36}
                          rx={6}
                        />
                        <circle cx={node.x} cy={node.y} r={15} />
                        <text x={node.x} y={node.y + 3} textAnchor="middle">{stateGraphNodeLabel(node).slice(0, 2)}</text>
                        <text x={node.x + 21} y={node.y - 4} className="node-title">{stateGraphNodeLabel(node).slice(0, 18)}</text>
                        <text x={node.x + 21} y={node.y + 10} className="node-meta">{displayText(node.role || node.kind)}</text>
                      </g>
                    ))}
                  </svg>
                  <div className="twm-state-graph-legend">
                    <span><i className="project" />{t('territoryWorldModel.graph.legend.project')}</span>
                    <span><i className="constraint" />{t('territoryWorldModel.graph.legend.constraint')}</span>
                    <span><i className="risk" />{t('territoryWorldModel.graph.legend.risk')}</span>
                    <span><i className="support" />{t('territoryWorldModel.graph.legend.support')}</span>
                    <span><i className="review" />{t('territoryWorldModel.graph.legend.review')}</span>
                  </div>
                </div>

                <div className="twm-state-graph-side">
                  <article>
                    <strong>{t('territoryWorldModel.graph.databasePolicy')}</strong>
                    <p>{stateGraph.graph_store?.production_policy
                      ? displayText(stateGraph.graph_store.production_policy)
                      : t('territoryWorldModel.graph.defaultPolicy')}</p>
                    <code>{stateGraph.graph_store?.backend || 'twm_repository_state_graph'}</code>
                  </article>
                  <article>
                    <strong>{t('territoryWorldModel.graph.objectRoles')}</strong>
                    {Object.entries(stateGraph.object_counts_by_role || {}).slice(0, 8).map(([role, count]) => (
                      <p key={`graph-role-${role}`}><span>{displayText(role)}</span><em>{fmt(count, 0)}</em></p>
                    ))}
                  </article>
                  <article>
                    <strong>{t('territoryWorldModel.graph.relationTypes')}</strong>
                    {Object.entries(stateGraph.relation_counts_by_type || {}).slice(0, 8).map(([relation, count]) => (
                      <p key={`graph-relation-${relation}`}><span>{displayText(relation)}</span><em>{fmt(count, 0)}</em></p>
                    ))}
                  </article>
                  <article>
                    <strong>{t('territoryWorldModel.graph.supportTypes')}</strong>
                    {Object.entries(stateGraph.support_material_counts_by_type || {}).slice(0, 6).map(([kind, count]) => (
                      <p key={`graph-support-${kind}`}><span>{displayText(kind)}</span><em>{fmt(count, 0)}</em></p>
                    ))}
                    {!Object.keys(stateGraph.support_material_counts_by_type || {}).length && <p><span>{t('territoryWorldModel.graph.noSupportMaterials')}</span><em>0</em></p>}
                  </article>
                </div>
              </div>
            )}

            {!stateGraph && (
              <div className="twm-empty">{t('territoryWorldModel.graph.empty')}</div>
            )}
          </section>
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
        <summary>{t('territoryWorldModel.payload.latest')}</summary>
        <pre>{JSON.stringify(latestResult || status || {}, null, 2)}</pre>
      </details>
        </div>
      )}
    </div>
  );
}
