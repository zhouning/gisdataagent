import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, Archive, CheckCircle2, CircleDot, Clock3, Diff, FilePlus2,
  GitBranch, Info, Link2, ListFilter, Pencil, Plus, Redo2, RefreshCw,
  Save, Send, ShieldCheck, Undo2, X,
} from 'lucide-react';

type Row = Record<string, any>;
type EntityType = 'concept' | 'property' | 'relation';

interface DraftSummary {
  draft_id: string;
  base_version_id?: string;
  base_semantic_version?: string;
  base_content_sha256?: string;
  active_semantic_version?: string;
  active_content_sha256?: string;
  base_is_active?: boolean;
  title: string;
  description?: string;
  status: string;
  revision: number;
  created_by?: string;
  updated_at?: string;
  change_count?: number;
}

interface DraftModel {
  draft_id: string;
  revision: number;
  base_content_sha256: string;
  model_sha256?: string;
  concepts: Row[];
  properties: Row[];
  relations: Row[];
  summary: Record<string, number>;
}

interface ChangeResult {
  change_id?: string;
  revision: number;
  operation: string;
  entity_type: EntityType;
  entity_id: string;
  before?: Row | null;
  after?: Row | null;
  replayed?: boolean;
}

interface ValidationReport {
  conforms: boolean;
  issue_count: number;
  severity_counts?: Record<string, number>;
  issues?: Row[];
  quality_gates_pending?: string[];
}

interface DiffReport {
  summary: { total: number; added: number; modified: number; deprecated: number; removed: number };
  impact?: {
    changed_concept_count: number;
    changed_property_count: number;
    changed_relation_count: number;
    impacted_concept_count: number;
    impacted_property_count: number;
    impacted_relation_count: number;
    concept_ids?: string[];
  };
  items: Row[];
}

type DraftRequest = <T>(path: string, init?: RequestInit) => Promise<T>;

export interface OntologyModelingPanelProps {
  apiBase: string;
  userRole?: string;
  selectedConcept?: Row | null;
  domainOptions?: Array<{ domain_id: string; label: string }>;
  ontologyTitle?: string;
  onDraftChanged?: () => void;
  requestApi?: DraftRequest;
  initialDraftId?: string;
}

const CORE_KINDS = [
  ['DomainClass', '实体类'], ['ProcessClass', '过程类'], ['StateClass', '状态类'],
  ['RoleClass', '角色类'], ['InformationClass', '信息类'], ['ObservationClass', '观测类'],
] as const;
const DOMAIN_OPTIONS = Array.from({ length: 10 }, (_, index) => {
  const id = String(index + 1).padStart(2, '0');
  return [id, id] as const;
});
const DATATYPES = [
  'xsd:string', 'xsd:boolean', 'xsd:date', 'xsd:dateTime', 'xsd:decimal',
  'xsd:double', 'xsd:integer', 'xsd:long', 'xsd:anyURI', 'geo:wktLiteral',
];
const GEOMETRIES = ['', 'Point', 'MultiPoint', 'LineString', 'MultiLineString', 'Polygon', 'MultiPolygon', 'Geometry'];
const STATUS_LABELS: Record<string, string> = {
  draft: '编辑中', in_review: '审阅中', rejected: '已退回', abandoned: '已放弃',
};
const KIND_LABELS: Record<string, string> = Object.fromEntries(CORE_KINDS);

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: 'include', ...init });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('json') ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === 'object' && payload?.error ? payload.error : `请求失败 (${response.status})`;
    const error = new Error(String(message)) as Error & { status?: number; currentRevision?: number };
    error.status = response.status;
    if (typeof payload === 'object' && typeof payload?.current_revision === 'number') error.currentRevision = payload.current_revision;
    throw error;
  }
  return payload as T;
}

function freshConcept(selected?: Row | null, defaultDomain = '02'): Row {
  return {
    code: selected?.code || '', pref_label: selected?.pref_label || '', definition: selected?.definition || '',
    alt_labels: selected?.alt_labels || [], kind: selected?.kind || 'DomainClass',
    domain_id: selected?.domain_id || defaultDomain, geometry_type: selected?.geometry_type || '',
  };
}

function freshProperty(owner?: string): Row {
  return { code: '', pref_label: '', owner_concept_id: owner || '', datatype: 'xsd:string', min_count: 0, max_count: 1, ordinal: 0, value_domain: null };
}

function freshRelation(source?: string, target?: string): Row {
  return { relation_type: 'subClassOf', source_concept_id: source || '', target_concept_id: target || '', pref_label: '', direction: 'directed', transitive: true, symmetric: false };
}

function mutablePayload(entityType: EntityType, entity: Row): Row {
  if (entityType === 'concept') {
    return { code: entity.code, pref_label: entity.pref_label, definition: entity.definition || '', alt_labels: entity.alt_labels || [], kind: entity.kind, domain_id: entity.domain_id, geometry_type: entity.geometry_type || '', lifecycle_status: entity.lifecycle_status };
  }
  if (entityType === 'property') {
    return { code: entity.code, pref_label: entity.pref_label, owner_concept_id: entity.owner_concept_id, datatype: entity.datatype, length: entity.length, precision_value: entity.precision_value, scale_value: entity.scale_value, min_count: entity.min_count, max_count: entity.max_count, ordinal: entity.ordinal, value_domain: entity.value_domain, default_value: entity.default_value, lifecycle_status: entity.lifecycle_status };
  }
  return { relation_type: entity.relation_type, source_concept_id: entity.source_concept_id, target_concept_id: entity.target_concept_id, pref_label: entity.pref_label, direction: entity.direction, transitive: entity.transitive, symmetric: entity.symmetric, lifecycle_status: entity.lifecycle_status };
}

function idempotencyKey() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `gda-draft-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function formatDate(value?: string) {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}

function shortId(value?: string) {
  if (!value) return '-';
  return value.length > 34 ? `${value.slice(0, 18)}…${value.slice(-10)}` : value;
}

export default function OntologyModelingPanel({ apiBase, userRole, selectedConcept, domainOptions, ontologyTitle, onDraftChanged, requestApi, initialDraftId }: OntologyModelingPanelProps) {
  const root = apiBase.replace(/\/$/, '');
  const request: DraftRequest = requestApi || api;
  const resolvedDomainOptions = domainOptions?.length
    ? domainOptions.map(domain => [domain.domain_id, domain.label] as const)
    : DOMAIN_OPTIONS;
  const defaultDomain = resolvedDomainOptions[0]?.[0] || '02';
  const canEdit = ['admin', 'standard_editor'].includes(userRole || '');
  const [drafts, setDrafts] = useState<DraftSummary[]>([]);
  const [draft, setDraft] = useState<DraftSummary | null>(null);
  const [model, setModel] = useState<DraftModel | null>(null);
  const [draftTitle, setDraftTitle] = useState('');
  const [draftDescription, setDraftDescription] = useState('');
  const [editorTab, setEditorTab] = useState<EntityType>('concept');
  const [conceptForm, setConceptForm] = useState<Row>(() => freshConcept(selectedConcept, defaultDomain));
  const [propertyForm, setPropertyForm] = useState<Row>(() => freshProperty(selectedConcept?.concept_id));
  const [relationForm, setRelationForm] = useState<Row>(() => freshRelation(selectedConcept?.concept_id));
  const [selectedConceptId, setSelectedConceptId] = useState<string>(selectedConcept?.concept_id || '');
  const [editingConceptId, setEditingConceptId] = useState<string>(selectedConcept?.concept_id || '');
  const [editingPropertyId, setEditingPropertyId] = useState('');
  const [editingRelationId, setEditingRelationId] = useState('');
  const [modelQuery, setModelQuery] = useState('');
  const [history, setHistory] = useState<ChangeResult[]>([]);
  const [redoStack, setRedoStack] = useState<ChangeResult[]>([]);
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [diffReport, setDiffReport] = useState<DiffReport | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const concepts = model?.concepts || [];
  const properties = model?.properties || [];
  const relations = model?.relations || [];
  const activeConceptId = editingConceptId || selectedConceptId || concepts[0]?.concept_id || '';
  const activeConcept = concepts.find(item => item.concept_id === activeConceptId) || selectedConcept;
  const conceptProperties = useMemo(() => properties.filter(item => item.owner_concept_id === activeConceptId), [activeConceptId, properties]);
  const conceptRelations = useMemo(() => relations.filter(item => item.source_concept_id === activeConceptId || item.target_concept_id === activeConceptId), [activeConceptId, relations]);
  const visibleConcepts = useMemo(() => {
    const query = modelQuery.trim().toLowerCase();
    if (!query) return concepts;
    return concepts.filter(item => [item.pref_label, item.code, item.concept_id, item.definition].some(value => String(value || '').toLowerCase().includes(query)));
  }, [concepts, modelQuery]);
  const selectedDraftIsEditable = draft?.status === 'draft';
  const changedCount = draft?.revision || 0;

  const loadDrafts = useCallback(async () => {
    if (!canEdit) return;
    try {
      const data = await request<{ items: DraftSummary[] }>(`${root}/drafts`);
      setDrafts(data.items || []);
    } catch (error) { setMessage(error instanceof Error ? error.message : '草稿列表加载失败'); }
  }, [canEdit, request, root]);

  const loadModel = useCallback(async (draftId: string) => {
    const data = await request<DraftModel>(`${root}/drafts/${encodeURIComponent(draftId)}/model`);
    setModel(data);
    return data;
  }, [request, root]);

  const openDraft = useCallback(async (draftId: string) => {
    setBusy(true); setMessage(''); setValidation(null); setDiffReport(null); setHistory([]); setRedoStack([]);
    try {
      const [detail, nextModel] = await Promise.all([
        request<DraftSummary>(`${root}/drafts/${encodeURIComponent(draftId)}`),
        request<DraftModel>(`${root}/drafts/${encodeURIComponent(draftId)}/model`),
      ]);
      setDraft(detail); setModel(nextModel);
      setSelectedConceptId(current => current && nextModel.concepts.some(item => item.concept_id === current) ? current : nextModel.concepts[0]?.concept_id || '');
      setEditingConceptId(current => current && nextModel.concepts.some(item => item.concept_id === current) ? current : nextModel.concepts[0]?.concept_id || '');
    } catch (error) { setMessage(error instanceof Error ? error.message : '草稿加载失败'); }
    finally { setBusy(false); }
  }, [request, root]);

  useEffect(() => { void loadDrafts(); }, [loadDrafts]);
  useEffect(() => {
    if (!initialDraftId || draft || !drafts.some(item => item.draft_id === initialDraftId)) return;
    void openDraft(initialDraftId);
  }, [draft, drafts, initialDraftId, openDraft]);
  useEffect(() => {
    if (selectedConcept?.concept_id && !model) {
      setSelectedConceptId(selectedConcept.concept_id); setEditingConceptId(selectedConcept.concept_id);
    }
  }, [model, selectedConcept]);
  useEffect(() => {
    const item = concepts.find(concept => concept.concept_id === activeConceptId) || selectedConcept;
    setConceptForm(freshConcept(item, defaultDomain));
    setPropertyForm(freshProperty(activeConceptId));
    setRelationForm(freshRelation(activeConceptId, concepts.find(concept => concept.concept_id !== activeConceptId)?.concept_id));
    setEditingPropertyId(''); setEditingRelationId('');
  }, [activeConceptId]);

  const refreshCurrentDraft = async () => {
    if (!draft) return;
    await openDraft(draft.draft_id);
    await loadDrafts();
  };

  const createDraft = async () => {
    if (!draftTitle.trim()) { setMessage('请先填写草稿名称'); return; }
    setBusy(true); setMessage('');
    try {
      const created = await request<DraftSummary>(`${root}/drafts`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: draftTitle, description: draftDescription }) });
      setDraftTitle(''); setDraftDescription(''); setDrafts(items => [created, ...items]); await openDraft(created.draft_id);
    } catch (error) { setMessage(error instanceof Error ? error.message : '草稿创建失败'); }
    finally { setBusy(false); }
  };

  const submitChange = async (entityType: EntityType, payload: Row, entityId = '', operationOverride = '') => {
    if (!draft || !selectedDraftIsEditable || !model) return;
    setBusy(true); setMessage('');
    try {
      const operation = operationOverride || (entityType === 'concept' ? 'upsert_concept' : entityType === 'property' ? 'upsert_property' : 'upsert_relation');
      const result = await request<ChangeResult>(`${root}/drafts/${encodeURIComponent(draft.draft_id)}/changes`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: draft.revision, idempotency_key: idempotencyKey(), operation, entity_type: entityType, entity_id: entityId, payload }) });
      setDraft(current => current ? { ...current, revision: result.revision, change_count: result.revision } : current);
      if (entityType === 'concept') { setEditingConceptId(result.entity_id); setSelectedConceptId(result.entity_id); }
      if (entityType === 'property') setEditingPropertyId(result.entity_id);
      if (entityType === 'relation') setEditingRelationId(result.entity_id);
      setHistory(items => [...items, result].slice(-50)); setRedoStack([]); setValidation(null); setDiffReport(null);
      await loadModel(draft.draft_id); await loadDrafts(); onDraftChanged?.();
      setMessage(result.replayed ? '已复用相同命令' : '变更已保存到草稿');
    } catch (error) {
      const conflict = error as Error & { currentRevision?: number };
      if (conflict.currentRevision != null) {
        setMessage(`草稿版本已变化，正在加载 revision ${conflict.currentRevision}`);
        await refreshCurrentDraft();
      } else setMessage(error instanceof Error ? error.message : '变更保存失败');
    } finally { setBusy(false); }
  };

  const undo = async () => {
    if (!draft || !selectedDraftIsEditable || history.length === 0) return;
    const last = history[history.length - 1];
    const inverse = last.before ? { operation: last.operation, entity_type: last.entity_type, entity_id: last.entity_id, payload: mutablePayload(last.entity_type, last.before) } : { operation: 'deprecate_entity', entity_type: last.entity_type, entity_id: last.entity_id, payload: {} };
    setBusy(true); setMessage('');
    try {
      const result = await request<ChangeResult>(`${root}/drafts/${encodeURIComponent(draft.draft_id)}/changes`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: draft.revision, idempotency_key: idempotencyKey(), ...inverse }) });
      setDraft(current => current ? { ...current, revision: result.revision, change_count: result.revision } : current); setHistory(items => items.slice(0, -1)); setRedoStack(items => [...items, last]); setValidation(null); setDiffReport(null); await loadModel(draft.draft_id); await loadDrafts(); onDraftChanged?.(); setMessage('已追加撤销命令');
    } catch (error) { setMessage(error instanceof Error ? error.message : '撤销失败'); }
    finally { setBusy(false); }
  };

  const redo = async () => {
    if (!draft || !selectedDraftIsEditable || redoStack.length === 0) return;
    const next = redoStack[redoStack.length - 1];
    await submitChange(next.entity_type, mutablePayload(next.entity_type, next.after || {}), next.entity_id);
    setRedoStack(items => items.slice(0, -1));
  };

  const deprecate = async (entityType: EntityType, entityId: string) => {
    if (!entityId || !selectedDraftIsEditable) return;
    await submitChange(entityType, {}, entityId, 'deprecate_entity');
  };

  const runValidation = async () => {
    if (!draft) return;
    setBusy(true); setMessage('');
    try { setValidation(await request<ValidationReport>(`${root}/drafts/${encodeURIComponent(draft.draft_id)}/validate`, { method: 'POST' })); }
    catch (error) { setMessage(error instanceof Error ? error.message : '本体校验失败'); }
    finally { setBusy(false); }
  };

  const loadDiff = async () => {
    if (!draft) return;
    setBusy(true); setMessage('');
    try { setDiffReport(await request<DiffReport>(`${root}/drafts/${encodeURIComponent(draft.draft_id)}/diff`)); }
    catch (error) { setMessage(error instanceof Error ? error.message : '差异计算失败'); }
    finally { setBusy(false); }
  };

  const submitReview = async () => {
    if (!draft) return;
    setBusy(true); setMessage('');
    try {
      const result = await request<{ status: string }>(`${root}/drafts/${encodeURIComponent(draft.draft_id)}/submit`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: draft.revision }) });
      setDraft(current => current ? { ...current, status: result.status } : current); await loadDrafts(); setMessage('草稿已提交人工审阅，尚未发布生产包');
    } catch (error) { setMessage(error instanceof Error ? error.message : '提交审阅失败'); }
    finally { setBusy(false); }
  };

  const abandon = async () => {
    if (!draft || !selectedDraftIsEditable) return;
    if (typeof window !== 'undefined' && !window.confirm('放弃后草稿将只读，变更历史会保留。确定继续吗？')) return;
    setBusy(true); setMessage('');
    try {
      const result = await request<{ status: string }>(`${root}/drafts/${encodeURIComponent(draft.draft_id)}/abandon`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: draft.revision }) });
      setDraft(current => current ? { ...current, status: result.status } : current); await loadDrafts(); setMessage('草稿已放弃，历史记录仍然保留');
    } catch (error) { setMessage(error instanceof Error ? error.message : '放弃草稿失败'); }
    finally { setBusy(false); }
  };

  const selectConcept = (conceptId: string) => {
    setSelectedConceptId(conceptId); setEditingConceptId(conceptId); setEditorTab('concept');
  };
  const selectExistingProperty = (propertyId: string) => {
    const item = conceptProperties.find(property => property.property_id === propertyId);
    setEditingPropertyId(item?.property_id || ''); setPropertyForm(item ? { ...item } : freshProperty(activeConceptId));
  };
  const selectExistingRelation = (relationId: string) => {
    const item = conceptRelations.find(relation => relation.relation_id === relationId);
    setEditingRelationId(item?.relation_id || ''); setRelationForm(item ? { ...item } : freshRelation(activeConceptId, concepts.find(concept => concept.concept_id !== activeConceptId)?.concept_id));
  };

  const issueClick = (issue: Row) => {
    if (issue.entity_type === 'property') { setEditorTab('property'); selectExistingProperty(issue.entity_id); return; }
    if (issue.entity_type === 'relation') { setEditorTab('relation'); selectExistingRelation(issue.entity_id); return; }
    if (issue.entity_id) { setEditorTab('concept'); selectConcept(issue.entity_id); }
  };

  if (!canEdit) return <section className="ontology-modeling-panel ontology-modeling-empty"><ShieldCheck size={22} /><strong>草稿建模仅对本体编辑角色开放</strong><span>当前用户没有写入权限；只读图谱、映射和校验仍可使用。</span></section>;

  return <section className="ontology-modeling-panel" aria-label="本体草稿建模工作台">
    <header className="ontology-modeling-header">
      <div className="ontology-modeling-title"><span className="ontology-eyebrow">GOVERNED MODELING</span><strong><Pencil size={15} />策划领域本体草稿</strong><span>{draft ? `基于 v${draft.base_semantic_version || '-'} · revision ${draft.revision}` : '绑定活动版本后开始编辑'}</span></div>
      {draft && <div className="ontology-modeling-header-state"><span className={`ontology-draft-status ${draft.status}`}><Clock3 size={12} />{STATUS_LABELS[draft.status] || draft.status}</span><span className="ontology-header-revision">r{draft.revision}</span></div>}
    </header>

    {!draft ? <div className="ontology-draft-create ontology-draft-create-layout">
      <div className="ontology-create-column"><div className="ontology-modeling-callout"><GitBranch size={18} /><div><strong>基线锁定</strong><span>新草稿绑定当前活动本体版本；浏览器只提交命令，不直接修改生产包。</span></div></div><label>草稿名称<input value={draftTitle} maxLength={200} onChange={event => setDraftTitle(event.target.value)} placeholder="例如：耕地实体类补充" /></label><label>变更目的<textarea value={draftDescription} maxLength={4000} onChange={event => setDraftDescription(event.target.value)} placeholder="记录领域问题、数据来源和预期影响" /></label><button className="ontology-primary-action" disabled={busy || !draftTitle.trim()} onClick={() => void createDraft()}><FilePlus2 size={14} />建立版本锁定草稿</button></div>
      <div className="ontology-create-side"><div className="ontology-section-label"><Archive size={13} />我的草稿 <span>{drafts.length}</span></div>{drafts.length ? drafts.map(item => <button className="ontology-draft-row" key={item.draft_id} onClick={() => void openDraft(item.draft_id)}><span><strong>{item.title}</strong><small>v{item.base_semantic_version || '-'} · r{item.revision} · {formatDate(item.updated_at)}</small></span><em className={`is-${item.status}`}>{STATUS_LABELS[item.status] || item.status}</em></button>) : <div className="ontology-empty-list">还没有草稿</div>}</div>
    </div> : <>
      <div className="ontology-modeling-toolbar"><label className="ontology-draft-picker"><span>当前草稿</span><select value={draft.draft_id} onChange={event => void openDraft(event.target.value)}>{drafts.map(item => <option key={item.draft_id} value={item.draft_id}>{item.title} · r{item.revision}</option>)}</select></label><div className="ontology-modeling-actions"><button title="刷新当前草稿" aria-label="刷新当前草稿" disabled={busy} onClick={() => void refreshCurrentDraft()}><RefreshCw size={14} /></button><button title="撤销上一变更" aria-label="撤销上一变更" disabled={busy || history.length === 0 || !selectedDraftIsEditable} onClick={() => void undo()}><Undo2 size={14} /></button><button title="重做上一变更" aria-label="重做上一变更" disabled={busy || redoStack.length === 0 || !selectedDraftIsEditable} onClick={() => void redo()}><Redo2 size={14} /></button><button title="运行结构校验" aria-label="运行结构校验" disabled={busy} onClick={() => void runValidation()}><ShieldCheck size={14} /></button><button title="查看模型差异" aria-label="查看模型差异" disabled={busy} onClick={() => void loadDiff()}><Diff size={14} /></button><button className="ontology-secondary-action" disabled={busy || !selectedDraftIsEditable} onClick={() => void abandon()}><Archive size={13} />放弃</button><button className="ontology-submit-action" disabled={busy || !selectedDraftIsEditable || changedCount === 0} onClick={() => void submitReview()}><Send size={13} />提交审阅</button></div></div>
      {message && <div className="ontology-modeling-message" role="status" aria-live="polite"><AlertTriangle size={14} />{message}<button aria-label="关闭消息" title="关闭消息" onClick={() => setMessage('')}><X size={13} /></button></div>}
      <div className="ontology-draft-meta"><span>基线 <code>{shortId(draft.base_content_sha256)}</code></span><span>活动版本 <b>v{draft.active_semantic_version || '-'}</b></span><span>模型对象 <b>{(model?.summary?.concept_count || 0) + (model?.summary?.property_count || 0) + (model?.summary?.relation_count || 0)}</b></span><span>变更 <b>{changedCount}</b></span><span className={draft.base_is_active === false ? 'is-stale' : ''}>{draft.base_is_active === false ? '基线已过期' : '基线与活动版本一致'}</span></div>

      <div className="ontology-modeling-workspace">
        <aside className="ontology-modeling-navigator"><div className="ontology-navigator-head"><div><strong>模型对象</strong><span>{model?.summary?.concept_count || 0} 个实体类</span></div><CircleDot size={15} /></div><div className="ontology-model-search"><ListFilter size={13} /><input value={modelQuery} onChange={event => setModelQuery(event.target.value)} placeholder="筛选代码或名称" /></div><div className="ontology-model-counts"><span><b>{model?.summary?.concept_count || 0}</b>类</span><span><b>{model?.summary?.property_count || 0}</b>属性</span><span><b>{model?.summary?.relation_count || 0}</b>关系</span></div><div className="ontology-concept-list">{visibleConcepts.map(item => <button key={item.concept_id} className={activeConceptId === item.concept_id ? 'active' : ''} onClick={() => selectConcept(item.concept_id)}><span className="ontology-concept-dot" /><span><strong>{item.pref_label || item.code}</strong><small>{item.code} · {KIND_LABELS[item.kind] || item.kind}</small></span><em>{item.geometry_type || '非空间'}</em></button>)}{!visibleConcepts.length && <div className="ontology-empty-list">没有匹配对象</div>}</div></aside>

        <div className="ontology-modeling-editor"><div className="ontology-editor-context"><div><span>当前实体类</span><strong>{activeConcept?.pref_label || '新建实体类'}</strong><code>{activeConcept?.concept_id || '尚未生成稳定 ID'}</code></div><div className="ontology-context-kpis"><span>属性 <b>{conceptProperties.length}</b></span><span>关系 <b>{conceptRelations.length}</b></span></div></div><div className="ontology-editor-tabs" role="tablist" aria-label="本体建模对象类型"><button role="tab" aria-selected={editorTab === 'concept'} className={editorTab === 'concept' ? 'active' : ''} onClick={() => setEditorTab('concept')}><GitBranch size={13} />实体类</button><button role="tab" aria-selected={editorTab === 'property'} className={editorTab === 'property' ? 'active' : ''} onClick={() => setEditorTab('property')}><Plus size={13} />数据属性</button><button role="tab" aria-selected={editorTab === 'relation'} className={editorTab === 'relation' ? 'active' : ''} onClick={() => setEditorTab('relation')}><Link2 size={13} />对象关系</button></div>

          {editorTab === 'concept' && <div className="ontology-editor-form" role="tabpanel"><div className="ontology-form-heading"><div><strong>实体类定义</strong><span>代码、URI 和实体 ID 由后端稳定规则生成</span></div><button title="新建实体类" aria-label="新建实体类" onClick={() => { setEditingConceptId(''); setConceptForm(freshConcept(undefined, defaultDomain)); }}><Plus size={14} /></button></div><label>建模对象<select value={editingConceptId} onChange={event => { const item = concepts.find(concept => concept.concept_id === event.target.value); setEditingConceptId(item?.concept_id || ''); setSelectedConceptId(item?.concept_id || ''); setConceptForm(freshConcept(item, defaultDomain)); }}><option value="">新建实体类</option>{concepts.map(item => <option key={item.concept_id} value={item.concept_id}>{item.pref_label} · {item.code}</option>)}</select></label><div className="ontology-form-grid"><label>技术代码<input value={conceptForm.code || ''} onChange={event => setConceptForm((value: Row) => ({ ...value, code: event.target.value }))} placeholder="例如 AgriculturalParcel" /></label><label>类类型<select value={conceptForm.kind || 'DomainClass'} onChange={event => setConceptForm((value: Row) => ({ ...value, kind: event.target.value }))}>{CORE_KINDS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div><label>首选名称<input value={conceptForm.pref_label || ''} onChange={event => setConceptForm((value: Row) => ({ ...value, pref_label: event.target.value }))} placeholder="中文名称" /></label><label>定义<textarea value={conceptForm.definition || ''} onChange={event => setConceptForm((value: Row) => ({ ...value, definition: event.target.value }))} placeholder={`对象在${ontologyTitle || '当前行业'}中的可审计定义`} /></label><div className="ontology-form-grid"><label>所属领域<select value={conceptForm.domain_id || defaultDomain} onChange={event => setConceptForm((value: Row) => ({ ...value, domain_id: event.target.value }))}>{resolvedDomainOptions.map(([value, label]) => <option key={value} value={value}>{value} · {label}</option>)}</select></label><label>空间几何<select value={conceptForm.geometry_type || ''} onChange={event => setConceptForm((value: Row) => ({ ...value, geometry_type: event.target.value }))}>{GEOMETRIES.map(value => <option key={value} value={value}>{value || '非空间对象'}</option>)}</select></label></div><div className="ontology-entity-identity"><span>稳定 ID</span><code>{editingConceptId || '保存后生成'}</code><span>URI</span><code>{conceptForm.uri || '由服务生成'}</code></div><div className="ontology-form-actions"><button className="ontology-primary-action" disabled={busy || !selectedDraftIsEditable || !conceptForm.code || !conceptForm.pref_label} onClick={() => void submitChange('concept', conceptForm, editingConceptId)}><Save size={14} />保存实体类</button>{editingConceptId && <button className="ontology-danger-action" disabled={busy || !selectedDraftIsEditable} onClick={() => void deprecate('concept', editingConceptId)}><Archive size={13} />标记弃用</button>}</div></div>}

          {editorTab === 'property' && <div className="ontology-editor-form" role="tabpanel"><div className="ontology-form-heading"><div><strong>数据属性定义</strong><span>属性归属于当前实体类；继承属性应回到其来源类编辑</span></div><button title="新建数据属性" aria-label="新建数据属性" onClick={() => { setEditingPropertyId(''); setPropertyForm(freshProperty(activeConceptId)); }}><Plus size={14} /></button></div><label>已有属性<select value={editingPropertyId} onChange={event => selectExistingProperty(event.target.value)}><option value="">新建数据属性</option>{conceptProperties.map(item => <option key={item.property_id} value={item.property_id}>{item.pref_label} · {item.code}</option>)}</select></label><div className="ontology-form-grid"><label>属性代码<input value={propertyForm.code || ''} onChange={event => setPropertyForm((value: Row) => ({ ...value, code: event.target.value }))} placeholder="例如 cultivatedArea" /></label><label>数据类型<select value={propertyForm.datatype || 'xsd:string'} onChange={event => setPropertyForm((value: Row) => ({ ...value, datatype: event.target.value }))}>{DATATYPES.map(value => <option key={value} value={value}>{value}</option>)}</select></label></div><label>属性名称<input value={propertyForm.pref_label || ''} onChange={event => setPropertyForm((value: Row) => ({ ...value, pref_label: event.target.value }))} placeholder="中文名称" /></label><label>所属类<select value={propertyForm.owner_concept_id || activeConceptId} onChange={event => setPropertyForm((value: Row) => ({ ...value, owner_concept_id: event.target.value }))}>{concepts.map(item => <option key={item.concept_id} value={item.concept_id}>{item.pref_label} · {item.code}</option>)}</select></label><div className="ontology-form-grid"><label>最小基数<input type="number" min="0" value={propertyForm.min_count ?? 0} onChange={event => setPropertyForm((value: Row) => ({ ...value, min_count: Number(event.target.value) }))} /></label><label>最大基数<input type="number" min="0" value={propertyForm.max_count ?? 1} onChange={event => setPropertyForm((value: Row) => ({ ...value, max_count: event.target.value === '' ? null : Number(event.target.value) }))} /></label></div><div className="ontology-form-grid"><label>顺序<input type="number" min="0" value={propertyForm.ordinal ?? 0} onChange={event => setPropertyForm((value: Row) => ({ ...value, ordinal: Number(event.target.value) }))} /></label><label>长度 / 精度<input value={propertyForm.length ?? ''} onChange={event => setPropertyForm((value: Row) => ({ ...value, length: event.target.value === '' ? null : Number(event.target.value) }))} placeholder="可选" /></label></div><div className="ontology-form-actions"><button className="ontology-primary-action" disabled={busy || !selectedDraftIsEditable || !propertyForm.code || !propertyForm.pref_label || !(propertyForm.owner_concept_id || activeConceptId)} onClick={() => void submitChange('property', { ...propertyForm, owner_concept_id: propertyForm.owner_concept_id || activeConceptId }, editingPropertyId)}><Save size={14} />保存数据属性</button>{editingPropertyId && <button className="ontology-danger-action" disabled={busy || !selectedDraftIsEditable} onClick={() => void deprecate('property', editingPropertyId)}><Archive size={13} />标记弃用</button>}</div></div>}

          {editorTab === 'relation' && <div className="ontology-editor-form" role="tabpanel"><div className="ontology-form-heading"><div><strong>对象关系定义</strong><span>关系端点必须是模型中存在的实体类；继承关系参与无环校验</span></div><button title="新建对象关系" aria-label="新建对象关系" onClick={() => { setEditingRelationId(''); setRelationForm(freshRelation(activeConceptId, concepts.find(concept => concept.concept_id !== activeConceptId)?.concept_id)); }}><Plus size={14} /></button></div><label>已有关系<select value={editingRelationId} onChange={event => selectExistingRelation(event.target.value)}><option value="">新建对象关系</option>{conceptRelations.map(item => <option key={item.relation_id} value={item.relation_id}>{item.pref_label || item.relation_type} · {item.relation_type}</option>)}</select></label><div className="ontology-form-grid"><label>关系类型<input value={relationForm.relation_type || ''} onChange={event => setRelationForm((value: Row) => ({ ...value, relation_type: event.target.value }))} placeholder="subClassOf 或领域关系代码" /></label><label>关系名称<input value={relationForm.pref_label || ''} onChange={event => setRelationForm((value: Row) => ({ ...value, pref_label: event.target.value }))} placeholder="中文关系名称" /></label></div><label>起点类<select value={relationForm.source_concept_id || activeConceptId} onChange={event => setRelationForm((value: Row) => ({ ...value, source_concept_id: event.target.value }))}>{concepts.map(item => <option key={item.concept_id} value={item.concept_id}>{item.pref_label} · {item.code}</option>)}</select></label><label>终点类<select value={relationForm.target_concept_id || ''} onChange={event => setRelationForm((value: Row) => ({ ...value, target_concept_id: event.target.value }))}>{concepts.filter(item => item.concept_id !== (relationForm.source_concept_id || activeConceptId)).map(item => <option key={item.concept_id} value={item.concept_id}>{item.pref_label} · {item.code}</option>)}</select></label><div className="ontology-toggle-grid"><label><input type="checkbox" checked={Boolean(relationForm.transitive)} onChange={event => setRelationForm((value: Row) => ({ ...value, transitive: event.target.checked }))} />传递关系</label><label><input type="checkbox" checked={Boolean(relationForm.symmetric)} onChange={event => setRelationForm((value: Row) => ({ ...value, symmetric: event.target.checked }))} />对称关系</label></div><div className="ontology-form-actions"><button className="ontology-primary-action" disabled={busy || !selectedDraftIsEditable || !relationForm.relation_type || !relationForm.source_concept_id || !relationForm.target_concept_id} onClick={() => void submitChange('relation', relationForm, editingRelationId)}><Save size={14} />保存对象关系</button>{editingRelationId && <button className="ontology-danger-action" disabled={busy || !selectedDraftIsEditable} onClick={() => void deprecate('relation', editingRelationId)}><Archive size={13} />标记弃用</button>}</div></div>}
        </div>

        <aside className="ontology-modeling-inspector"><section className="ontology-inspector-section"><div className="ontology-inspector-heading"><strong><ShieldCheck size={14} />质量门</strong><button title="运行结构校验" aria-label="运行结构校验" disabled={busy} onClick={() => void runValidation()}><RefreshCw size={13} /></button></div>{validation ? <><div className={`ontology-inspector-status ${validation.conforms ? 'ok' : 'error'}`}><span>{validation.conforms ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />} {validation.conforms ? '结构校验通过' : '需要修正问题'}</span><b>{validation.issue_count}</b></div>{!validation.conforms && <div className="ontology-inspector-issues">{(validation.issues || []).slice(0, 8).map((issue, index) => <button key={`${issue.code}-${index}`} onClick={() => issueClick(issue)}><b>{issue.code}</b><span>{issue.message}</span></button>)}</div>}{validation.conforms && <div className="ontology-gates-note">提交后还需通过 SHACL、能力问题、OWL-RL 和溯源审查。</div>}</> : <div className="ontology-inspector-empty"><Info size={15} />尚未运行本次草稿校验</div>}</section><section className="ontology-inspector-section"><div className="ontology-inspector-heading"><strong><Diff size={14} />差异与影响</strong><button title="计算差异" aria-label="计算差异" disabled={busy} onClick={() => void loadDiff()}><RefreshCw size={13} /></button></div>{diffReport ? <><div className="ontology-diff-kpis"><span>新增 <b>{diffReport.summary.added}</b></span><span>修改 <b>{diffReport.summary.modified}</b></span><span>弃用 <b>{diffReport.summary.deprecated}</b></span></div>{diffReport.impact && <div className="ontology-impact-grid"><div><b>{diffReport.impact.impacted_concept_count}</b><span>受影响类</span></div><div><b>{diffReport.impact.impacted_property_count}</b><span>受影响属性</span></div><div><b>{diffReport.impact.impacted_relation_count}</b><span>受影响关系</span></div></div>}<div className="ontology-diff-list">{diffReport.items.slice(0, 12).map(item => <div key={`${item.entity_type}-${item.entity_id}`}><span className={`diff-${item.change_kind}`}>{item.change_kind}</span><code>{shortId(item.entity_id)}</code></div>)}</div></> : <div className="ontology-inspector-empty"><Info size={15} />计算差异以查看发布影响</div>}</section><section className="ontology-inspector-section ontology-selected-inspector"><div className="ontology-inspector-heading"><strong><CircleDot size={14} />对象检查</strong></div>{activeConcept ? <dl><dt>名称</dt><dd>{activeConcept.pref_label || '-'}</dd><dt>代码</dt><dd><code>{activeConcept.code || '-'}</code></dd><dt>稳定 ID</dt><dd><code>{shortId(activeConcept.concept_id)}</code></dd><dt>URI</dt><dd><code>{shortId(activeConcept.uri)}</code></dd><dt>生命周期</dt><dd>{activeConcept.lifecycle_status || 'active'}</dd></dl> : <div className="ontology-inspector-empty">请选择模型对象</div>}</section></aside>
      </div>
    </>}
  </section>;
}
