export interface StdDocumentSummary {
  id: string; doc_code: string; title: string;
  source_type: string; status: string; owner_user_id: string;
}
export interface StdClause { id: string; ordinal_path: string; heading?: string;
  clause_no?: string; kind: string; body_md?: string; }
export interface StdDataElement { id: string; code: string; name_zh: string;
  datatype?: string; obligation: string; }

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
