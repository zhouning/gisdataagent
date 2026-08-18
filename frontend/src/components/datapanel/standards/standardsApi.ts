import { getLocaleHeaders } from "../../../i18n";

export interface StdDocumentSummary {
  id: string; doc_code: string; title: string;
  source_type: string; status: string; owner_user_id: string;
}
export interface StdClause { id: string; ordinal_path: string; heading?: string;
  clause_no?: string; kind: string; body_md?: string; }
export interface StdDataElement { id: string; code: string; name_zh: string;
  datatype?: string; obligation: string; }

const fetch = (input: RequestInfo | URL, init: RequestInit = {}) => {
  const headers = new Headers(init.headers);
  Object.entries(getLocaleHeaders()).forEach(([key, value]) => headers.set(key, value));
  return globalThis.fetch(input, {...init, headers});
};

const j = async <T>(r: Response): Promise<T> => {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
};

export const listDocuments = (params: {owner?: string; status?: string} = {}) => {
  const q = new URLSearchParams(params as Record<string,string>).toString();
  return fetch(`/api/std/documents?${q}`).then(j<{documents: StdDocumentSummary[]}>);
};

export const uploadDocument = (file: File, sourceType: string,
                                sourceUrl?: string) => {
  const fd = new FormData(); fd.append("file", file);
  fd.append("source_type", sourceType);
  if (sourceUrl) fd.append("source_url", sourceUrl);
  return fetch("/api/std/documents", {method: "POST", body: fd})
    .then(j<{document_id: string; version_id: string}>);
};

export const getVersionClauses = (versionId: string) =>
  fetch(`/api/std/versions/${versionId}/clauses`).then(j<{clauses: StdClause[]}>);

export const getVersionDataElements = (versionId: string) =>
  fetch(`/api/std/versions/${versionId}/data-elements`)
    .then(j<{data_elements: StdDataElement[]}>);

export const getVersionTerms = (versionId: string) =>
  fetch(`/api/std/versions/${versionId}/terms`).then(j<{terms: any[]}>);

export const getSimilar = (versionId: string) =>
  fetch(`/api/std/versions/${versionId}/similar`).then(j<{hits: any[]}>);

export interface ImpactGraphNode {
  id: string;
  kind: string;
  label?: string;
  document_id?: string;
  version_id?: string;
  metadata?: Record<string, any>;
}

export type ImpactGraphEdgeType =
  "derives" | "references" | "similar_clause" | (string & {});

export interface ImpactGraphEdge {
  id: string;
  edge_type: ImpactGraphEdgeType;
  source: string;
  target: string;
  label?: string;
  status?: string | null;
  score?: number;
  metadata?: Record<string, any>;
}

export interface ImpactGraphSummary {
  node_count: number;
  edge_count: number;
  by_edge_type: Record<string, number>;
  cross_version_edge_count: number;
}

export interface ImpactGraphResult {
  version_id: string;
  nodes: ImpactGraphNode[];
  edges: ImpactGraphEdge[];
  summary: ImpactGraphSummary;
}

export const getVersionImpactGraph = (
  versionId: string,
  params: {include_similar?: boolean; min_similarity?: number; top_k?: number} = {},
) => {
  const filtered: Record<string,string> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null) filtered[k] = String(v);
  }
  const q = new URLSearchParams(filtered).toString();
  return fetch(`/api/std/impact/versions/${versionId}${q ? `?${q}` : ""}`)
    .then(j<ImpactGraphResult>);
};

export const listVersions = (docId: string) =>
  fetch(`/api/std/documents/${docId}/versions`).then(j<{versions: {id: string; version_label: string; status: string}[]}>);

export interface StdClauseDetail extends StdClause {
  body_html?: string | null;
  checksum: string;
}

export interface AcquireLockResponse {
  body_md: string;
  body_html: string | null;
  checksum: string;
  lock_expires_at: string;     // ISO
  lock_token: string;
}

export interface LockedError {
  holder: string | null;
  expires_at: string | null;
}

export interface ConflictDetail {
  server_checksum: string;
  server_body_md: string;
}

export const acquireLock = async (clauseId: string)
    : Promise<AcquireLockResponse | { status: 423, body: LockedError }> => {
  const r = await fetch(`/api/std/clauses/${clauseId}/lock`, {method: "POST"});
  if (r.status === 423) return {status: 423, body: await r.json()};
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export const heartbeat = async (clauseId: string)
    : Promise<{lock_expires_at: string} | {status: 410}> => {
  const r = await fetch(`/api/std/clauses/${clauseId}/heartbeat`, {method: "POST"});
  if (r.status === 410) return {status: 410};
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export const releaseLock = async (clauseId: string): Promise<void> => {
  await fetch(`/api/std/clauses/${clauseId}/lock/release`, {method: "POST"});
};

export const saveClause = async (clauseId: string, ifMatch: string,
                                  bodyMd: string, bodyHtml: string)
    : Promise<{checksum: string, updated_at: string}
              | {status: 409, body: ConflictDetail}
              | {status: 410}> => {
  const r = await fetch(`/api/std/clauses/${clauseId}`, {
    method: "PUT",
    headers: {"Content-Type": "application/json", "If-Match": ifMatch},
    body: JSON.stringify({body_md: bodyMd, body_html: bodyHtml}),
  });
  if (r.status === 409) return {status: 409, body: await r.json()};
  if (r.status === 410) return {status: 410};
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export const breakLock = async (clauseId: string)
    : Promise<{previous_holder: string | null}> => {
  const r = await fetch(`/api/std/clauses/${clauseId}/lock/break`,
                        {method: "POST"});
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export const getClauseElements = (clauseId: string) =>
  fetch(`/api/std/clauses/${clauseId}/elements`)
    .then(j<{data_elements: StdDataElement[]}>);

export interface CitationCandidate {
  kind: string;
  target_id: string | null;
  target_url: string | null;
  snippet: string;
  base_score: number;
  extra: Record<string, any>;
}

export const citationSearch = (clauseId: string, query: string,
                                sources?: string[]) =>
  fetch("/api/std/citation/search", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({clause_id: clauseId, query, sources}),
  }).then(j<{candidates: CitationCandidate[]}>);

export const citationInsert = (clauseId: string,
                                candidate: CitationCandidate) =>
  fetch("/api/std/citation/insert", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({clause_id: clauseId, candidate}),
  }).then(j<{ref_id: string; citation_text: string}>);

// ===========================================================================
// Wave 4: Review stage SDK
// ===========================================================================

export type ReviewRound = {
  id: string;
  document_version_id: string;
  reviewer_user_id: string;
  initiated_by: string;
  initiated_at: string | null;
  closed_at: string | null;
  status: 'open' | 'closed';
  outcome: 'approved' | 'rejected' | null;
};

export type ReviewComment = {
  id: string;
  round_id: string;
  clause_id: string;
  parent_comment_id: string | null;
  author_user_id: string;
  body_md: string;
  resolution: 'open' | 'accepted' | 'rejected' | 'duplicate';
  created_at: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
};

export type GatingPrecheck = {
  pending_refs: number;
  open_comments: number;
  blocking: boolean;
};

export type ReviewTemplateStepStatus =
  'done' | 'active' | 'blocked' | 'pending';

export type ReviewTemplateStep = {
  id: string;
  label: string;
  role: string;
  status: ReviewTemplateStepStatus;
  description: string;
  metrics: Record<string, any>;
};

export type ReviewTemplateEdge = {
  source: string;
  target: string;
  label: string;
};

export type ReviewTemplateSummary = {
  open_round_id: string | null;
  latest_round_id: string | null;
  latest_round_status: string | null;
  latest_round_outcome: string | null;
  reviewer_user_id: string | null;
  pending_refs: number;
  approved_refs: number;
  rejected_refs: number;
  total_refs: number;
  open_comments: number;
  resolved_comments: number;
  total_comments: number;
  blocking: boolean;
};

export type ReviewTemplate = {
  template_id: string;
  version_id: string;
  version_status: string;
  steps: ReviewTemplateStep[];
  edges: ReviewTemplateEdge[];
  summary: ReviewTemplateSummary;
};

export const getReviewTemplate = (versionId: string) =>
  fetch(`/api/std/reviews/template/${versionId}`).then(j<ReviewTemplate>);

export const startReviewRound = (versionId: string, reviewerUserId: string) =>
  fetch("/api/std/reviews/rounds", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({document_version_id: versionId,
                          reviewer_user_id: reviewerUserId}),
  }).then(j<{round_id: string}>);

export const listReviewRounds = (params: {version_id?: string;
                                            reviewer_user_id?: string;
                                            status?: string} = {}) => {
  const q = new URLSearchParams(params as Record<string,string>).toString();
  return fetch(`/api/std/reviews/rounds?${q}`)
    .then(j<{rounds: ReviewRound[]}>);
};

export const closeReviewPrecheck = (roundId: string) =>
  fetch(`/api/std/reviews/rounds/${roundId}/close-precheck`)
    .then(j<GatingPrecheck>);

export const closeReviewRound = (roundId: string,
                                 outcome: 'approved' | 'rejected') =>
  fetch(`/api/std/reviews/rounds/${roundId}/close`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({outcome}),
  }).then(j<{round_id: string; status: string;
              outcome: string; version_status: string}>);

export const listReviewComments = (roundId: string, clauseId?: string) => {
  const q = clauseId ? `?clause_id=${clauseId}` : "";
  return fetch(`/api/std/reviews/rounds/${roundId}/comments${q}`)
    .then(j<{comments: ReviewComment[]}>);
};

export const postReviewComment = (roundId: string, clauseId: string,
                                   bodyMd: string,
                                   parentCommentId?: string) =>
  fetch(`/api/std/reviews/rounds/${roundId}/comments`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({clause_id: clauseId, body_md: bodyMd,
                          parent_comment_id: parentCommentId ?? null}),
  }).then(j<{comment_id: string}>);

export const resolveReviewComment = (commentId: string,
                                      resolution: 'accepted' | 'rejected' | 'duplicate') =>
  fetch(`/api/std/reviews/comments/${commentId}/resolve`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({resolution}),
  }).then(j<{comment_id: string; resolution: string}>);

export const patchReferenceStatus = (refId: string, roundId: string,
                                      status: 'approved' | 'rejected') =>
  fetch(`/api/std/reviews/references/${refId}/status`, {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({verification_status: status, round_id: roundId}),
  }).then(j<{ref_id: string; verification_status: string;
              verified_by: string; verified_at: string}>);


// ===========================================================================
// Wave 5: Publish + Derive SDK
// ===========================================================================

export type PublishedVersion = {
  id: string;
  document_id: string;
  version_label: string;
  released_at: string | null;
  released_by: string | null;
  supersedes_version_id: string | null;
};

export type VersionMeta = {
  id: string;
  document_id: string;
  version_label: string;
  status: 'draft' | 'review' | 'approved' | 'released' | 'retired';
  semver_major: number;
  semver_minor: number;
  semver_patch: number;
  released_at: string | null;
  supersedes_version_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  created_by: string | null;
  updated_by: string | null;
};

export type PublishEvent = {
  id: string;
  event_type: 'published' | 'forked';
  actor_user_id: string;
  occurred_at: string | null;
  notes: string | null;
};

export type Strategy = {
  name: string;
  status: 'active' | 'coming_soon';
  description: string;
};

export type DerivedLink = {
  id: string;
  source_kind: string;
  source_id: string;
  source_version_id: string;
  target_kind: string;
  target_table: string;
  target_id: string;
  derivation_strategy: string;
  status: 'pending' | 'active' | 'stale' | 'overridden' | 'superseded';
  stale_reason: string | null;
  generated_at: string | null;
};

export type DerivationStatusByStrategy = Record<
  string,
  {active: number; stale: number; failed: number;
   pending: number; overridden: number; superseded: number}
>;

export type RollbackByStrategy = Record<string, {
  links_marked: number;
  downstream_marked: number;
  target_tables: string[];
}>;

export interface RollbackVersionResult {
  version_id: string;
  by_strategy: RollbackByStrategy;
}

export interface BatchRollbackItem {
  version_id: string;
  status: "rolled_back" | "no_active_links";
  by_strategy: RollbackByStrategy;
}

export interface BatchRollbackSkipped {
  version_id: string;
  reason: string;
}

export interface BatchRollbackResult {
  rolled_back: BatchRollbackItem[];
  skipped: BatchRollbackSkipped[];
}

export const publishVersion = (versionId: string) =>
  fetch(`/api/std/publish/versions/${versionId}`, {method: "POST"})
    .then(j<{version_id: string; status: string; released_at: string;
              outbox_event_id: string}>);

export const forkVersion = (sourceVersionId: string, newLabel: string) =>
  fetch("/api/std/publish/fork", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({source_version_id: sourceVersionId,
                          new_label: newLabel}),
  }).then(j<{new_version_id: string; source_version_id: string;
              status: string}>);

export const listPublishedVersions = (documentId?: string) => {
  const q = documentId ? `?document_id=${documentId}` : "";
  return fetch(`/api/std/publish/versions${q}`)
    .then(j<{versions: PublishedVersion[]}>);
};

export const getPublishTimeline = (versionId: string) =>
  fetch(`/api/std/publish/timeline/${versionId}`)
    .then(j<{events: PublishEvent[]}>);

export const getVersion = (versionId: string) =>
  fetch(`/api/std/versions/${versionId}`).then(j<VersionMeta>);

export const listDeriveStrategies = () =>
  fetch("/api/std/derive/strategies")
    .then(j<{strategies: Strategy[]}>);

export const listDeriveLinks = (params: {version_id: string;
                                          strategy?: string;
                                          status?: string}) => {
  const filtered: Record<string,string> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null) filtered[k] = v;
  }
  const q = new URLSearchParams(filtered).toString();
  return fetch(`/api/std/derive/links?${q}`)
    .then(j<{links: DerivedLink[]}>);
};

export const rerunDerivation = (versionId: string, strategies?: string[]) =>
  fetch(`/api/std/derive/rerun/${versionId}`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({strategies: strategies ?? null}),
  }).then(j<{results: Record<string, {ok: boolean; new?: number;
                                       staled?: number; failed?: number;
                                       error?: string}>}>);

export const rollbackDerivations = (versionId: string, reason?: string) =>
  fetch(`/api/std/derive/rollback/${versionId}`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({reason: reason ?? null}),
  }).then(j<RollbackVersionResult>);

export const rollbackDerivationsBatch = (
  versionIds: string[],
  reason?: string,
) =>
  fetch("/api/std/derive/rollback", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({version_ids: versionIds, reason: reason ?? null}),
  }).then(j<BatchRollbackResult>);

export const getDeriveStatus = (versionId: string) =>
  fetch(`/api/std/derive/status/${versionId}`)
    .then(j<{strategies: DerivationStatusByStrategy}>);


// ---------- P4: outbox dead-letter operations ----------

export type OutboxStatus = "pending" | "in_flight" | "done" | "failed";

export interface OutboxEvent {
  id: string;
  event_type: string;
  payload: Record<string, any>;
  created_at: string | null;
  processed_at: string | null;
  attempts: number;
  last_error: string | null;
  next_attempt_at: string | null;
  status: OutboxStatus;
}

export type OutboxCounts = Record<OutboxStatus, number>;

export interface OutboxRetryResult {
  id: string;
  status: "retried" | "skipped";
  reason?: string;
}

export const listOutboxEvents = (
  params: {status?: OutboxStatus; event_type?: string;
           limit?: number; offset?: number} = {},
) => {
  const filtered: Record<string,string> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") filtered[k] = String(v);
  }
  const q = new URLSearchParams(filtered).toString();
  return fetch(`/api/std/outbox/events${q ? `?${q}` : ""}`)
    .then(j<{events: OutboxEvent[]; counts: OutboxCounts}>);
};

export const retryOutboxEvent = (eventId: string) =>
  fetch(`/api/std/outbox/events/${eventId}/retry`, {method: "POST"})
    .then(j<{result: OutboxRetryResult}>);

export const retryOutboxEvents = (eventIds: string[]) =>
  fetch("/api/std/outbox/events/retry", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({event_ids: eventIds}),
  }).then(j<{retried: OutboxRetryResult[]; skipped: OutboxRetryResult[]}>);


// ---------- Wave 8: data-model snapshot ----------

export interface DataModelStats {
  entity_count: number;
  attribute_count: number;
  constraint_count: number;
}

export interface DataModelSnapshotMeta {
  snapshot_id: string;
  generated_at: string | null;
  generated_by: string;
  derived_status: "active" | "stale" | "manual";
  source_tag: string | null;
  std_derived_link_id: string | null;
  stats: DataModelStats;
}

export interface DataModelPayload {
  snapshot_id: string;
  version_id: string;
  generated_at: string | null;
  generated_by: string;
  derived_status: "active" | "stale" | "manual";
  source_tag: string | null;
  stats: DataModelStats;
  cdm: any;
  ldm: any;
  pdm: any;
  ddl_postgresql: string;
}

export const getDataModel = (versionId: string) =>
  fetch(`/api/std/data-model/${versionId}`).then(j<DataModelPayload>);

export const getDataModelLayer = (versionId: string,
                                  layer: "cdm" | "ldm" | "pdm" | "ddl") =>
  fetch(`/api/std/data-model/${versionId}?layer=${layer}`)
    .then(j<{layer: string; data: any}>);

// Plain-text DDL — Content-Type=text/plain, returns the raw text.
export const getDataModelDdlText = (versionId: string) =>
  fetch(`/api/std/data-model/${versionId}/ddl`).then(r => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.text();
  });

export const getDataModelDdlDownloadUrl = (versionId: string) =>
  `/api/std/data-model/${versionId}/ddl`;

export const getDataModelXmiDownloadUrl = (versionId: string) =>
  `/api/std/data-model/${versionId}/xmi`;

export const listDataModelSnapshots = (versionId: string) =>
  fetch(`/api/std/data-model/${versionId}/snapshots`)
    .then(j<{version_id: string; snapshots: DataModelSnapshotMeta[]}>);


// ---------- P5: standards market ----------

export interface MarketAssetCounts {
  clauses: number;
  data_elements: number;
  terms: number;
  value_domains: number;
}

export type MarketVisibilityScope = "public" | "organization" | "private";

export interface MarketStandardItem {
  version_id: string;
  document_id: string;
  doc_code: string;
  title: string;
  source_type: string;
  owner_user_id: string;
  tags: string[];
  version_label: string;
  released_at: string | null;
  released_by: string | null;
  supersedes_version_id: string | null;
  market_listing_id: string | null;
  market_status: MarketListingStatus | "legacy_approved";
  market_submitted_by: string | null;
  market_submitted_at: string | null;
  market_reviewed_by: string | null;
  market_reviewed_at: string | null;
  visibility_scope: MarketVisibilityScope;
  owner_org_id: string | null;
  allowed_org_ids: string[];
  asset_counts: MarketAssetCounts;
}

export interface MarketCatalogResponse {
  items: MarketStandardItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface MarketDiffAssetCounts {
  added: number;
  removed: number;
  changed: number;
  unchanged: number;
}

export interface MarketDiffSummary extends MarketDiffAssetCounts {
  by_asset_type: Record<string, MarketDiffAssetCounts>;
  field_changes?: number;
  changed_fields_by_asset_type?: Record<string, Record<string, number>>;
  review_hints?: MarketDiffReviewHint[];
}

export interface MarketDiffReviewHint {
  level: "review" | "high" | string;
  code: string;
  message: string;
  count: number;
}

export interface MarketDiffFieldChange {
  field: string;
  label: string;
  source_value: unknown;
  target_value: unknown;
}

export interface MarketDiffChange {
  asset_type: string;
  key: string;
  change_type: "added" | "removed" | "changed";
  source_label: string | null;
  target_label: string | null;
  field_changes?: MarketDiffFieldChange[];
  field_change_count?: number;
}

export interface MarketDiffVersionMeta {
  version_id: string;
  document_id: string;
  version_label: string;
  status: string;
  released_at: string | null;
  doc_code: string;
  title: string;
  source_type: string;
}

export interface MarketDiffResponse {
  source_version_id: string;
  target_version_id: string;
  source: MarketDiffVersionMeta;
  target: MarketDiffVersionMeta;
  summary: MarketDiffSummary;
  changes: MarketDiffChange[];
}

export interface MarketSubscription {
  id: string;
  subscriber_user_id: string;
  document_id: string;
  doc_code: string;
  title: string;
  source_version_id: string;
  source_version_label: string;
  last_seen_version_id: string | null;
  latest_version_id: string | null;
  latest_version_label: string | null;
  latest_released_at: string | null;
  has_update: boolean;
  status: "active" | "cancelled";
  notes: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export type MarketListingStatus =
  "submitted" | "approved" | "rejected" | "withdrawn";

export interface MarketListing {
  id: string;
  version_id: string;
  document_id: string;
  doc_code: string;
  title: string;
  source_type: string;
  owner_user_id: string;
  version_label: string;
  released_at: string | null;
  released_by: string | null;
  status: MarketListingStatus;
  visibility_scope: MarketVisibilityScope;
  owner_org_id: string | null;
  allowed_org_ids: string[];
  submitted_by: string;
  submitted_at: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  notes: string | null;
  review_notes: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MarketListingVisibilityInput {
  visibility_scope?: MarketVisibilityScope;
  owner_org_id?: string | null;
  allowed_org_ids?: string[];
  notes?: string | null;
}

export const listMarketStandards = (
  params: {query?: string; limit?: number; offset?: number} = {},
) => {
  const filtered: Record<string,string> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && String(v) !== "") {
      filtered[k] = String(v);
    }
  }
  const q = new URLSearchParams(filtered).toString();
  return fetch(`/api/std/market/standards${q ? `?${q}` : ""}`)
    .then(j<MarketCatalogResponse>);
};

export const getMarketDiff = (sourceVersionId: string,
                              targetVersionId: string) => {
  const q = new URLSearchParams({
    source_version_id: sourceVersionId,
    target_version_id: targetVersionId,
  }).toString();
  return fetch(`/api/std/market/diff?${q}`).then(j<MarketDiffResponse>);
};

export const listMarketSubscriptions = () =>
  fetch("/api/std/market/subscriptions")
    .then(j<{subscriptions: MarketSubscription[]}>);

export const subscribeMarketStandard = (versionId: string,
                                        notes?: string) =>
  fetch("/api/std/market/subscriptions", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({version_id: versionId, notes: notes ?? null}),
  }).then(j<MarketSubscription>);

export const unsubscribeMarketSubscription = (subscriptionId: string) =>
  fetch(`/api/std/market/subscriptions/${subscriptionId}`, {method: "DELETE"})
    .then(j<MarketSubscription>);

export const markMarketSubscriptionSeen = (subscriptionId: string) =>
  fetch(`/api/std/market/subscriptions/${subscriptionId}/mark-seen`,
        {method: "POST"})
    .then(j<MarketSubscription>);

export const listMarketListings = (
  params: {status?: MarketListingStatus; limit?: number; offset?: number} = {},
) => {
  const filtered: Record<string,string> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && String(v) !== "") {
      filtered[k] = String(v);
    }
  }
  const q = new URLSearchParams(filtered).toString();
  return fetch(`/api/std/market/listings${q ? `?${q}` : ""}`)
    .then(j<{items: MarketListing[]; total: number; limit: number; offset: number}>);
};

export const submitMarketListing = (
  versionId: string,
  options: string | MarketListingVisibilityInput = {},
) => {
  const payload: MarketListingVisibilityInput =
    typeof options === "string" ? {notes: options} : options;
  return (
  fetch("/api/std/market/listings", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      version_id: versionId,
      notes: payload.notes ?? null,
      visibility_scope: payload.visibility_scope ?? "public",
      owner_org_id: payload.owner_org_id ?? null,
      allowed_org_ids: payload.allowed_org_ids ?? [],
    }),
  }).then(j<MarketListing>)
  );
};

export const reviewMarketListing = (
  listingId: string,
  decision: "approved" | "rejected",
  reviewNotes?: string,
) =>
  fetch(`/api/std/market/listings/${listingId}/review`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({decision, review_notes: reviewNotes ?? null}),
  }).then(j<MarketListing>);

export const updateMarketListingVisibility = (
  listingId: string,
  visibility: MarketListingVisibilityInput,
) =>
  fetch(`/api/std/market/listings/${listingId}/visibility`, {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      visibility_scope: visibility.visibility_scope ?? "public",
      owner_org_id: visibility.owner_org_id ?? null,
      allowed_org_ids: visibility.allowed_org_ids ?? [],
    }),
  }).then(j<MarketListing>);
