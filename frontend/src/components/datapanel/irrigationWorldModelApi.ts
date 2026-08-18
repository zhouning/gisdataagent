import i18n, { getLocaleHeaders } from '../../i18n';

export type Mode = 'baseline' | 'candidateA' | 'candidateB';
export type Horizon = 6 | 12 | 24;
export type ProposalStatus = 'pending' | 'returned' | 'approved';

export interface Node {
  id: string;
  stable_id: string;
  label: string;
  type: string;
  role: string;
  state: string;
  value: string;
  capacity?: number;
  children?: string[];
}

export interface OntologyLink {
  subject: string;
  predicate: string;
  object: string;
  authority: string;
}

export interface ScenarioResult {
  mode: Mode;
  label: string;
  branchRatio: number;
  delivered: number;
  shortage: number;
  tailCoverage: number;
  fairnessCv: number;
  capacityViolations: number;
  residual: number;
  residualVolumeM3: number;
  westDelay: number;
  westEfficiency: number | null;
  fields: Record<string, { demand: number; delivered: number; coverage: number; demandVolumeM3: number; deliveredVolumeM3: number }>;
  nodeStates: Record<string, { value: number; unit: string; demand?: number }>;
  timeline: Array<{ hour: number; tailCoverage: number; shortage: number; status: string }>;
  numerical: {
    scheme: string;
    equations: string;
    timestep_count: number;
    state_count: number;
    runtime_ms: number;
    minimum_depth_m: number;
    maximum_depth_m: number;
    operator_admitted: false;
    diagnostic_only: true;
    assumed_delivery_efficiency: Record<string, number>;
    not_included: string[];
  };
  reaches: Array<{
    reach_id: string;
    scheme: string;
    equations: string;
    state_count: number;
    reach_length_m: number;
    manning_n: number;
    bed_slope: number;
    kinematic_celerity_mps: number;
    travel_time_seconds: number;
    timestep_count: number;
    minimum_depth_m: number;
    maximum_depth_m: number;
    maximum_discharge_m3s: number;
    capacity_m3s: number;
    capacity_exceeded: boolean;
    initial_storage_m3: number;
    final_storage_m3: number;
    storage_change_m3: number;
    boundary_inflow_volume_m3: number;
    boundary_outflow_volume_m3: number;
    numerical_volume_residual_m3: number;
  }>;
  waterBalance: {
    boundarySupply: number;
    trunkLoss: number;
    branchLoss: number;
    delivered: number;
    unallocated: number;
    storageChange: number;
    residual: number;
    boundaryVolumeM3: number;
    deliveredVolumeM3: number;
    junctionUnallocatedVolumeM3: number;
    tailSpillVolumeM3: number;
    conveyanceLossVolumeM3: number;
    storageChangeM3: number;
    residualVolumeM3: number;
  };
}

export interface AuditEvent {
  timestamp: string;
  time: string;
  step: string;
  status: '\u901a\u8fc7' | '\u8bb0\u5f55' | '\u5f85\u5ba1\u67e5';
  detail: string;
}

export interface ScenarioParameters {
  supply_drop_percent: number;
  west_shift_hours: number;
  candidate_east_ratio_percent: number;
  horizon_hours: Horizon;
}

export interface IrrigationProposal {
  proposal_id: string;
  version: number;
  candidate_mode: Mode;
  status: ProposalStatus;
  review_note: string;
  execution_allowed: false;
  actions: Array<{ order: number; action_type: string; target: string; summary: string }>;
  claim_boundary: ClaimBoundary;
}

export interface ClaimBoundary {
  data: string;
  claim: string;
  calibration: string;
  control: string;
  excluded_claims: string[];
}

export interface IrrigationRun {
  run_id: string;
  version: number;
  created_at: string;
  status: string;
  parameters: ScenarioParameters;
  model: {
    model_id: string;
    version: string;
    model_class: string;
    physics_scope: string;
    not_included: string[];
    numerical_evidence: ScenarioResult['numerical'];
  };
  planner?: {
    planner_id: string;
    version: string;
    selected_mode: Mode;
    ranking: Array<{ mode: Mode; feasible: boolean; objective: number; shortage_volume_m3: number; fairness_cv: number }>;
    global_optimum_claimed: false;
    evidence_origin?: 'persisted' | 'legacy_run_reconstruction';
  };
  state_snapshot: {
    snapshot_id: string;
    effective_at: string;
    quality_label: string;
    parameter_status: string;
  };
  pipeline: Array<{ index: number; key: string; label: string; status: string }>;
  results: ScenarioResult[];
  proposal: IrrigationProposal;
  audit_events: AuditEvent[];
  claim_boundary: ClaimBoundary;
}

export interface IrrigationBootstrap {
  schema: string;
  service: {
    mode: 'backend_authoritative';
    repository: string;
    durability: string;
  };
  ontology_profile: {
    profile_id: string;
    version: string;
    label: string;
    authority: string;
    semantic_contract: string[];
    package_id: string;
    content_sha256: string;
    ontology_api: string;
  };
  objects: Node[];
  links: OntologyLink[];
  state_snapshot: IrrigationRun['state_snapshot'];
  modes: Array<{ id: Mode; label: string; note: string }>;
  default_parameters: ScenarioParameters;
  claim_boundary: ClaimBoundary;
  run: IrrigationRun;
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { credentials: 'include', ...init, headers: { ...getLocaleHeaders(), ...(init?.headers || {}) } });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    // The status code below still provides a useful error when the body is not JSON.
  }
  if (!response.ok) {
    const message = payload && typeof payload === 'object' && 'error' in payload
      ? String((payload as { error: unknown }).error)
      : `${i18n.t('errors.requestFailed')} (HTTP ${response.status})`;
    throw new Error(message);
  }
  return payload as T;
}

export function fetchIrrigationBootstrap(signal?: AbortSignal) {
  return requestJson<IrrigationBootstrap>('/api/irrigation-world-model/bootstrap', { signal });
}

export async function runIrrigationScenario(parameters: ScenarioParameters) {
  const payload = await requestJson<{ run: IrrigationRun }>('/api/irrigation-world-model/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(parameters),
  });
  return payload.run;
}

export async function reviewIrrigationProposal(proposalId: string, decision: Exclude<ProposalStatus, 'pending'>, note: string) {
  const payload = await requestJson<{ run: IrrigationRun }>(`/api/irrigation-world-model/proposals/${encodeURIComponent(proposalId)}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, note }),
  });
  return payload.run;
}
