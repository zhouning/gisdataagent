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
