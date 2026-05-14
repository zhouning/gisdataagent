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
