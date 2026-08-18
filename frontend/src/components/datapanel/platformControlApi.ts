import i18n, { getLocaleHeaders } from '../../i18n';

export interface ResourceVersion {
  tenant_id: string;
  resource_urn: string;
  resource_version_id: string;
  version_key: string;
  predecessor_version_id: string | null;
  content_sha256: string;
  authority_version_ref: Record<string, unknown>;
  created_by: string;
  created_at: string;
}

export interface ResourceVersionPage {
  items: ResourceVersion[];
  count: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface SchemaVersionRecord {
  schema_version_id: string;
  schema_format: string;
  authority_system: string;
  authority_namespace: string;
  authority_object_id: string;
  authority_version_ref: string;
  schema_sha256: string;
  created_by: string;
  created_at: string;
}

export interface DataContractVersionRecord {
  data_contract_version_id: string;
  contract_kind: string;
  enforcement_mode: string;
  authority_system: string;
  authority_namespace: string;
  authority_object_id: string;
  authority_version_ref: string;
  contract_sha256: string;
  created_by: string;
  created_at: string;
}

export interface PhysicalLocationRecord {
  physical_location_id: string;
  location_kind: string;
  provider_system: string;
  provider_namespace: string;
  provider_locator: string;
  snapshot_ref: string | null;
  revision_ref: string | null;
  checksum_algorithm: string;
  content_checksum: string;
  location_sha256: string;
  created_by: string;
  created_at: string;
}

export interface ArchitectureBinding {
  schema_version_id: string;
  data_contract_version_id: string;
  physical_location_id: string;
  binding_sha256: string;
  bound_by: string;
  bound_at: string;
}

export interface ResourceVersionArchitecture {
  schema_version: string;
  tenant_id: string;
  resource_version_id: string;
  architecture_ready: boolean;
  missing_components: string[];
  schema_version_record: SchemaVersionRecord | null;
  data_contract_version_record: DataContractVersionRecord | null;
  physical_location: PhysicalLocationRecord | null;
  binding: ArchitectureBinding | null;
}

export interface ArchitectureProviderObservation {
  observation_id: string;
  provider_system: string;
  provider_namespace: string;
  provider_object_id: string;
  object_state: string;
  source_revision: string | null;
  observed_at: string;
  fresh_until: string;
  observed_by: string;
  recorded_at: string;
}

export interface ArchitectureReconciliation {
  schema_version: string;
  tenant_id: string;
  resource_version_id: string;
  status: string;
  architecture: ResourceVersionArchitecture;
  latest_observation: ArchitectureProviderObservation | null;
  schema_matches: boolean | null;
  location_matches: boolean | null;
  evaluated_at: string;
  required_actions: string[];
}

export interface ArchitectureChangeReview {
  tenant_id: string;
  target_resource_urn: string;
  resource_version_id: string;
  observation_id: string;
  observation_sha256: string;
  binding_sha256: string;
  reconciliation_status: string;
  candidate_schema_sha256: string | null;
  candidate_location_sha256: string | null;
  required_actions: string[];
  review_sha256: string;
}

export interface ApprovalCase {
  tenant_id: string;
  approval_case_ref: string;
  target_resource_urn: string;
  target_fingerprint: string;
  action: string;
  requester_subject: string;
  request_reason: string;
  request_context: Record<string, unknown>;
  status: 'pending' | 'approved' | 'rejected' | 'cancelled';
  state_version: number;
  requested_at: string;
  expires_at: string;
  decided_by: string | null;
  decision_reason: string | null;
  decided_at: string | null;
}

export interface ApprovalCasePage {
  items: ApprovalCase[];
  count: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface ApprovalCaseEvent {
  tenant_id: string;
  approval_event_id: string;
  approval_case_ref: string;
  sequence_no: number;
  from_status: ApprovalCase['status'] | null;
  to_status: ApprovalCase['status'];
  actor_subject: string;
  reason: string;
  details: Record<string, unknown>;
  occurred_at: string;
}

export interface ApprovalCaseAssignment {
  tenant_id: string;
  approval_case_ref: string;
  assignment_version: number;
  status: 'assigned' | 'released' | 'closed';
  assignee_subject: string | null;
  last_actor_subject: string;
  last_reason: string;
  delegation_depth: number;
  assigned_at: string;
  updated_at: string;
  closed_at: string | null;
}

export interface ApprovalCaseAssignmentEvent {
  tenant_id: string;
  assignment_event_id: string;
  approval_case_ref: string;
  assignment_version: number;
  action: 'assigned' | 'reassigned' | 'delegated' | 'released' | 'closed';
  from_assignee_subject: string | null;
  to_assignee_subject: string | null;
  actor_subject: string;
  reason: string;
  delegation_depth: number;
  occurred_at: string;
}

export interface ApprovalCaseAssignmentView {
  current: ApprovalCaseAssignment | null;
  events: ApprovalCaseAssignmentEvent[];
  event_count: number;
  actor_access: ApprovalAssignmentActorAccess | null;
}

export interface ApprovalAssignmentActorAccess {
  actor_subject: string;
  can_decide: boolean;
  can_delegate: boolean;
  access_reason: string;
}

export interface ApprovalPrincipal {
  tenant_id: string;
  principal_subject: string;
  principal_type: 'human' | 'team';
  display_name: string;
  directory_version: number;
  status: 'active' | 'inactive';
  approval_eligible: boolean;
  availability_status: 'available' | 'unavailable';
  valid_from: string;
  valid_until: string | null;
  last_actor_subject: string;
  last_reason: string;
  updated_at: string;
  eligible_now: boolean;
  eligibility_reason: string;
}

export interface ApprovalPrincipalList {
  items: ApprovalPrincipal[];
  count: number;
}

export interface ApprovalCaseNotification {
  tenant_id: string;
  notification_id: string;
  approval_case_ref: string;
  approval_event_sequence_no: number | null;
  notification_kind: 'requested' | 'expired' | 'decided';
  channel: 'alertmanager';
  destination_ref: string;
  delivery_order: number;
  status: 'pending' | 'in_flight' | 'done' | 'failed' | 'suppressed';
  attempt_count: number;
  max_attempts: number;
  available_at: string;
  claimed_by: string | null;
  claimed_until: string | null;
  last_error: string | null;
  created_at: string;
  completed_at: string | null;
  recovery_count: number;
  last_recovered_by: string | null;
  last_recovery_reason: string | null;
  last_recovered_at: string | null;
}

export interface ApprovalCaseNotificationRecoveryEvent {
  tenant_id: string;
  recovery_event_id: string;
  notification_id: string;
  approval_case_ref: string;
  recovery_no: number;
  actor_subject: string;
  reason: string;
  previous_attempt_count: number;
  previous_last_error: string | null;
  occurred_at: string;
}

interface ApprovalCaseEventList {
  items: ApprovalCaseEvent[];
  count: number;
}

export interface ApprovalCaseNotificationList {
  items: ApprovalCaseNotification[];
  count: number;
  recoveries: ApprovalCaseNotificationRecoveryEvent[];
  recovery_count: number;
}

export interface ArchitectureChangeReviewResponse {
  reconciliation: ArchitectureReconciliation;
  review: ArchitectureChangeReview;
  approval_case: ApprovalCase;
}

interface PlatformErrorBody {
  code?: string;
  message?: string;
}

interface PlatformEnvelope<T> {
  data: T | null;
  error: PlatformErrorBody | string | null;
  request_id?: string;
}

export class PlatformControlApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = 'PlatformControlApiError';
  }
}

async function platformRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  Object.entries(getLocaleHeaders()).forEach(([name, value]) => headers.set(name, value));
  const response = await fetch(path, { ...init, credentials: 'include', headers });
  let envelope: PlatformEnvelope<T> | null = null;
  try {
    envelope = await response.json() as PlatformEnvelope<T>;
  } catch {
    throw new PlatformControlApiError(
      i18n.t('platformControl.errors.invalidResponse'),
      response.status,
      'invalid_platform_response',
    );
  }
  if (!response.ok || envelope.data === null) {
    const error = envelope.error;
    const message = typeof error === 'string'
      ? error
      : error?.message || i18n.t('platformControl.errors.requestFailed');
    const code = typeof error === 'string'
      ? 'platform_request_failed'
      : error?.code || 'platform_request_failed';
    throw new PlatformControlApiError(message, response.status, code, envelope.request_id);
  }
  return envelope.data;
}

export function listResourceVersions(
  limit: number,
  offset: number,
  signal?: AbortSignal,
): Promise<ResourceVersionPage> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return platformRequest(`/api/platform/v1/resource-versions?${query}`, { signal });
}

export function listApprovalCases(
  options: {
    status?: ApprovalCase['status'];
    action?: string;
    limit: number;
    offset: number;
  },
  signal?: AbortSignal,
): Promise<ApprovalCasePage> {
  const query = new URLSearchParams({
    limit: String(options.limit),
    offset: String(options.offset),
  });
  if (options.status) query.set('status', options.status);
  if (options.action) query.set('action', options.action);
  return platformRequest(`/api/platform/v1/approval-cases?${query}`, { signal });
}

function approvalCaseId(approvalCaseRef: string): string {
  const caseId = approvalCaseRef.split('/').pop();
  if (!caseId) throw new Error(i18n.t('platformControl.errors.invalidApprovalCase'));
  return caseId;
}

export async function getApprovalCaseEvents(
  approvalCaseRef: string,
  signal?: AbortSignal,
): Promise<ApprovalCaseEvent[]> {
  const result = await platformRequest<ApprovalCaseEventList>(
    `/api/platform/v1/approval-cases/${encodeURIComponent(approvalCaseId(approvalCaseRef))}/events`,
    { signal },
  );
  return result.items;
}

export async function getApprovalCaseNotifications(
  approvalCaseRef: string,
  signal?: AbortSignal,
): Promise<ApprovalCaseNotificationList> {
  return platformRequest<ApprovalCaseNotificationList>(
    `/api/platform/v1/approval-cases/${encodeURIComponent(approvalCaseId(approvalCaseRef))}/notifications`,
    { signal },
  );
}

export function getApprovalCaseAssignment(
  approvalCaseRef: string,
  signal?: AbortSignal,
): Promise<ApprovalCaseAssignmentView> {
  return platformRequest(
    `/api/platform/v1/approval-cases/${encodeURIComponent(approvalCaseId(approvalCaseRef))}/assignment`,
    { signal },
  );
}

export function listApprovalPrincipals(
  eligibleOnly = true,
  signal?: AbortSignal,
): Promise<ApprovalPrincipalList> {
  return platformRequest(
    `/api/platform/v1/approval-principals?eligible_only=${eligibleOnly ? 'true' : 'false'}`,
    { signal },
  );
}

export function transitionApprovalCaseAssignment(
  approvalCaseRef: string,
  request: {
    expected_assignment_version: number;
    operation: 'assign' | 'reassign' | 'delegate' | 'release';
    assignee_subject?: string;
    reason: string;
  },
  signal?: AbortSignal,
): Promise<ApprovalCaseAssignment> {
  return platformRequest(
    `/api/platform/v1/approval-cases/${encodeURIComponent(approvalCaseId(approvalCaseRef))}/assignment`,
    {
      method: 'POST',
      signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
  );
}

export function retryApprovalCaseNotification(
  approvalCaseRef: string,
  notificationId: string,
  request: { expected_attempt_count: number; reason: string },
  signal?: AbortSignal,
): Promise<ApprovalCaseNotification> {
  return platformRequest(
    `/api/platform/v1/approval-cases/${encodeURIComponent(approvalCaseId(approvalCaseRef))}`
      + `/notifications/${encodeURIComponent(notificationId)}/retry`,
    {
      method: 'POST',
      signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
  );
}

export function decideApprovalCase(
  approvalCaseRef: string,
  request: {
    expected_state_version: number;
    verdict: Exclude<ApprovalCase['status'], 'pending'>;
    reason: string;
    details?: Record<string, unknown>;
  },
  signal?: AbortSignal,
): Promise<ApprovalCase> {
  return platformRequest(
    `/api/platform/v1/approval-cases/${encodeURIComponent(approvalCaseId(approvalCaseRef))}/decision`,
    {
      method: 'POST',
      signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...request, details: request.details || {} }),
    },
  );
}

export function getResourceVersionArchitecture(
  resourceVersionId: string,
  signal?: AbortSignal,
): Promise<ResourceVersionArchitecture> {
  return platformRequest(
    `/api/platform/v1/resource-versions/${encodeURIComponent(resourceVersionId)}/architecture`,
    { signal },
  );
}

export function getResourceVersionArchitectureReconciliation(
  resourceVersionId: string,
  signal?: AbortSignal,
): Promise<ArchitectureReconciliation> {
  return platformRequest(
    `/api/platform/v1/resource-versions/${encodeURIComponent(resourceVersionId)}/architecture/reconciliation`,
    { signal },
  );
}

function architectureChangeCaseId(observationId: string): string {
  return `architecture-change-${observationId.replace(/-/g, '')}`;
}

export async function getArchitectureChangeApprovalCase(
  observationId: string,
  signal?: AbortSignal,
): Promise<ApprovalCase | null> {
  const caseId = architectureChangeCaseId(observationId);
  try {
    return await platformRequest(
      `/api/platform/v1/approval-cases/${encodeURIComponent(caseId)}`,
      { signal },
    );
  } catch (error) {
    if (error instanceof PlatformControlApiError && error.status === 404) return null;
    throw error;
  }
}

export function createArchitectureChangeReview(
  resourceVersionId: string,
  requestReason: string,
  expiresInHours: number,
  signal?: AbortSignal,
): Promise<ArchitectureChangeReviewResponse> {
  return platformRequest(
    `/api/platform/v1/resource-versions/${encodeURIComponent(resourceVersionId)}/architecture/reconciliation/approval-cases`,
    {
      method: 'POST',
      signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        request_reason: requestReason,
        expires_in_hours: expiresInHours,
      }),
    },
  );
}
