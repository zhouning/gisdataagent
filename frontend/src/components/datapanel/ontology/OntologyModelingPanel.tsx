import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle, Archive, CheckCircle2, CircleDot, Clock3, Diff, FilePlus2,
  GitBranch, Info, Link2, ListFilter, Pencil, Plus, Redo2, RefreshCw,
  Save, Send, ShieldCheck, Undo2, X,
} from 'lucide-react';
import { formatDate, formatNumber, getLocaleHeaders } from '../../../i18n';

type Row = Record<string, any>;
type EntityType = 'concept' | 'property' | 'relation';

interface DraftSummary {
  draft_id: string;
  base_semantic_version?: string;
  base_content_sha256?: string;
  active_semantic_version?: string;
  base_is_active?: boolean;
  title: string;
  description?: string;
  status: string;
  revision: number;
  updated_at?: string;
  change_count?: number;
}

interface DraftModel {
  draft_id: string;
  revision: number;
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
  issues?: Row[];
}

interface DiffReport {
  summary: { total: number; added: number; modified: number; deprecated: number; removed: number };
  impact?: {
    impacted_concept_count: number;
    impacted_property_count: number;
    impacted_relation_count: number;
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

const CORE_KINDS = ['DomainClass', 'ProcessClass', 'StateClass', 'RoleClass', 'InformationClass', 'ObservationClass'];
const DOMAIN_OPTIONS = Array.from({ length: 10 }, (_, index) => {
  const id = String(index + 1).padStart(2, '0');
  return [id, id] as const;
});
const DATATYPES = ['xsd:string', 'xsd:boolean', 'xsd:date', 'xsd:dateTime', 'xsd:decimal', 'xsd:double', 'xsd:integer', 'xsd:long', 'xsd:anyURI', 'geo:wktLiteral'];
const GEOMETRIES = ['', 'Point', 'MultiPoint', 'LineString', 'MultiLineString', 'Polygon', 'MultiPolygon', 'Geometry'];

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'include',
    ...init,
    headers: { ...getLocaleHeaders(), ...(init?.headers || {}) },
  });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('json') ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === 'object' && payload?.error ? payload.error : `Request failed (${response.status})`;
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

function shortId(value?: string) {
  if (!value) return '-';
  return value.length > 34 ? `${value.slice(0, 18)}…${value.slice(-10)}` : value;
}

export default function OntologyModelingPanel({
  apiBase, userRole, selectedConcept, domainOptions, ontologyTitle, onDraftChanged, requestApi, initialDraftId,
}: OntologyModelingPanelProps) {
  const { t, i18n } = useTranslation();
  const root = apiBase.replace(/\/$/, '');
  const request = useCallback<DraftRequest>((path, init) => (
    (requestApi || api)(path, { ...init, headers: { ...getLocaleHeaders(), ...(init?.headers || {}) } })
  ), [requestApi, i18n.resolvedLanguage]);
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
  const [selectedConceptId, setSelectedConceptId] = useState(selectedConcept?.concept_id || '');
  const [editingConceptId, setEditingConceptId] = useState(selectedConcept?.concept_id || '');
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
  const statusLabel = (status: string) => t(`ontologyModeling.status.${status}`, { defaultValue: status });
  const lifecycleLabel = (status: string) => t(`platform.enums.lifecycle.${status}`, { defaultValue: status });
  const kindLabel = (kind: string) => t(`ontologyModeling.kinds.${kind}`, { defaultValue: kind });
  const dateLabel = (value?: string) => value ? formatDate(value, { dateStyle: 'medium', timeStyle: 'short', hour12: false }) : '-';

  const loadDrafts = useCallback(async () => {
    if (!canEdit) return;
    try {
      const data = await request<{ items: DraftSummary[] }>(`${root}/drafts`);
      setDrafts(data.items || []);
    } catch (error) { setMessage(error instanceof Error ? error.message : t('ontologyModeling.errors.list')); }
  }, [canEdit, request, root, t]);

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
      setSelectedConceptId((current: string) => current && nextModel.concepts.some(item => item.concept_id === current) ? current : nextModel.concepts[0]?.concept_id || '');
      setEditingConceptId((current: string) => current && nextModel.concepts.some(item => item.concept_id === current) ? current : nextModel.concepts[0]?.concept_id || '');
    } catch (error) { setMessage(error instanceof Error ? error.message : t('ontologyModeling.errors.load')); }
    finally { setBusy(false); }
  }, [request, root, t]);

  useEffect(() => { void loadDrafts(); }, [loadDrafts, i18n.resolvedLanguage]);
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
    if (!draftTitle.trim()) { setMessage(t('ontologyModeling.errors.titleRequired')); return; }
    setBusy(true); setMessage('');
    try {
      const created = await request<DraftSummary>(`${root}/drafts`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: draftTitle, description: draftDescription }) });
      setDraftTitle(''); setDraftDescription(''); setDrafts(items => [created, ...items]); await openDraft(created.draft_id);
    } catch (error) { setMessage(error instanceof Error ? error.message : t('ontologyModeling.errors.create')); }
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
      setMessage(result.replayed ? t('ontologyModeling.messages.replayed') : t('ontologyModeling.messages.changeSaved'));
    } catch (error) {
      const conflict = error as Error & { currentRevision?: number };
      if (conflict.currentRevision != null) {
        setMessage(t('ontologyModeling.messages.revisionConflict', { revision: conflict.currentRevision }));
        await refreshCurrentDraft();
      } else setMessage(error instanceof Error ? error.message : t('ontologyModeling.errors.change'));
    } finally { setBusy(false); }
  };

  const undo = async () => {
    if (!draft || !selectedDraftIsEditable || history.length === 0) return;
    const last = history[history.length - 1];
    const inverse = last.before ? { operation: last.operation, entity_type: last.entity_type, entity_id: last.entity_id, payload: mutablePayload(last.entity_type, last.before) } : { operation: 'deprecate_entity', entity_type: last.entity_type, entity_id: last.entity_id, payload: {} };
    setBusy(true); setMessage('');
    try {
      const result = await request<ChangeResult>(`${root}/drafts/${encodeURIComponent(draft.draft_id)}/changes`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: draft.revision, idempotency_key: idempotencyKey(), ...inverse }) });
      setDraft(current => current ? { ...current, revision: result.revision, change_count: result.revision } : current); setHistory(items => items.slice(0, -1)); setRedoStack(items => [...items, last]); setValidation(null); setDiffReport(null); await loadModel(draft.draft_id); await loadDrafts(); onDraftChanged?.(); setMessage(t('ontologyModeling.messages.undoSaved'));
    } catch (error) { setMessage(error instanceof Error ? error.message : t('ontologyModeling.errors.undo')); }
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
    catch (error) { setMessage(error instanceof Error ? error.message : t('ontologyModeling.errors.validate')); }
    finally { setBusy(false); }
  };

  const loadDiff = async () => {
    if (!draft) return;
    setBusy(true); setMessage('');
    try { setDiffReport(await request<DiffReport>(`${root}/drafts/${encodeURIComponent(draft.draft_id)}/diff`)); }
    catch (error) { setMessage(error instanceof Error ? error.message : t('ontologyModeling.errors.diff')); }
    finally { setBusy(false); }
  };

  const submitReview = async () => {
    if (!draft) return;
    setBusy(true); setMessage('');
    try {
      const result = await request<{ status: string }>(`${root}/drafts/${encodeURIComponent(draft.draft_id)}/submit`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: draft.revision }) });
      setDraft(current => current ? { ...current, status: result.status } : current); await loadDrafts(); setMessage(t('ontologyModeling.messages.submitted'));
    } catch (error) { setMessage(error instanceof Error ? error.message : t('ontologyModeling.errors.submit')); }
    finally { setBusy(false); }
  };

  const abandon = async () => {
    if (!draft || !selectedDraftIsEditable) return;
    if (typeof window !== 'undefined' && !window.confirm(t('ontologyModeling.confirm.abandon'))) return;
    setBusy(true); setMessage('');
    try {
      const result = await request<{ status: string }>(`${root}/drafts/${encodeURIComponent(draft.draft_id)}/abandon`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: draft.revision }) });
      setDraft(current => current ? { ...current, status: result.status } : current); await loadDrafts(); setMessage(t('ontologyModeling.messages.abandoned'));
    } catch (error) { setMessage(error instanceof Error ? error.message : t('ontologyModeling.errors.abandon')); }
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

  if (!canEdit) return (
    <section className="ontology-modeling-panel ontology-modeling-empty">
      <ShieldCheck size={22} /><strong>{t('ontologyModeling.access.title')}</strong><span>{t('ontologyModeling.access.description')}</span>
    </section>
  );

  return (
    <section className="ontology-modeling-panel" aria-label={t('ontologyModeling.aria.workbench')}>
      <header className="ontology-modeling-header">
        <div className="ontology-modeling-title">
          <span className="ontology-eyebrow">{t('ontologyModeling.eyebrow')}</span>
          <strong><Pencil size={15} />{t('ontologyModeling.title')}</strong>
          <span>{draft ? t('ontologyModeling.header.revision', { version: draft.base_semantic_version || '-', revision: formatNumber(draft.revision) }) : t('ontologyModeling.header.bindVersion')}</span>
        </div>
        {draft && <div className="ontology-modeling-header-state"><span className={`ontology-draft-status ${draft.status}`}><Clock3 size={12} />{statusLabel(draft.status)}</span><span className="ontology-header-revision">r{formatNumber(draft.revision)}</span></div>}
      </header>

      {!draft ? (
        <div className="ontology-draft-create ontology-draft-create-layout">
          <div className="ontology-create-column">
            <div className="ontology-modeling-callout"><GitBranch size={18} /><div><strong>{t('ontologyModeling.create.baselineTitle')}</strong><span>{t('ontologyModeling.create.baselineDescription')}</span></div></div>
            <label>{t('ontologyModeling.form.title')}<input value={draftTitle} maxLength={200} onChange={event => setDraftTitle(event.target.value)} placeholder={t('ontologyModeling.form.titlePlaceholder')} /></label>
            <label>{t('ontologyModeling.form.description')}<textarea value={draftDescription} maxLength={4000} onChange={event => setDraftDescription(event.target.value)} placeholder={t('ontologyModeling.form.descriptionPlaceholder')} /></label>
            <button className="ontology-primary-action" disabled={busy || !draftTitle.trim()} onClick={() => void createDraft()}><FilePlus2 size={14} />{t('ontologyModeling.actions.create')}</button>
          </div>
          <div className="ontology-create-side">
            <div className="ontology-section-label"><Archive size={13} />{t('ontologyModeling.sections.myDrafts')} <span>{formatNumber(drafts.length)}</span></div>
            {drafts.length ? drafts.map(item => <button className="ontology-draft-row" key={item.draft_id} onClick={() => void openDraft(item.draft_id)}><span><strong>{item.title}</strong><small>v{item.base_semantic_version || '-'} · r{formatNumber(item.revision)} · {dateLabel(item.updated_at)}</small></span><em className={`is-${item.status}`}>{statusLabel(item.status)}</em></button>) : <div className="ontology-empty-list">{t('ontologyModeling.empty.drafts')}</div>}
          </div>
        </div>
      ) : (
        <>
          <div className="ontology-modeling-toolbar">
            <label className="ontology-draft-picker"><span>{t('ontologyModeling.sections.currentDraft')}</span><select value={draft.draft_id} onChange={event => void openDraft(event.target.value)}>{drafts.map(item => <option key={item.draft_id} value={item.draft_id}>{item.title} · r{item.revision}</option>)}</select></label>
            <div className="ontology-modeling-actions">
              <button title={t('ontologyModeling.actions.refresh')} aria-label={t('ontologyModeling.actions.refresh')} disabled={busy} onClick={() => void refreshCurrentDraft()}><RefreshCw size={14} /></button>
              <button title={t('ontologyModeling.actions.undo')} aria-label={t('ontologyModeling.actions.undo')} disabled={busy || history.length === 0 || !selectedDraftIsEditable} onClick={() => void undo()}><Undo2 size={14} /></button>
              <button title={t('ontologyModeling.actions.redo')} aria-label={t('ontologyModeling.actions.redo')} disabled={busy || redoStack.length === 0 || !selectedDraftIsEditable} onClick={() => void redo()}><Redo2 size={14} /></button>
              <button title={t('ontologyModeling.actions.validate')} aria-label={t('ontologyModeling.actions.validate')} disabled={busy} onClick={() => void runValidation()}><ShieldCheck size={14} /></button>
              <button title={t('ontologyModeling.actions.diff')} aria-label={t('ontologyModeling.actions.diff')} disabled={busy} onClick={() => void loadDiff()}><Diff size={14} /></button>
              <button className="ontology-secondary-action" disabled={busy || !selectedDraftIsEditable} onClick={() => void abandon()}><Archive size={13} />{t('ontologyModeling.actions.abandon')}</button>
              <button className="ontology-submit-action" disabled={busy || !selectedDraftIsEditable || changedCount === 0} onClick={() => void submitReview()}><Send size={13} />{t('ontologyModeling.actions.submit')}</button>
            </div>
          </div>
          {message && <div className="ontology-modeling-message" role="status" aria-live="polite"><AlertTriangle size={14} />{message}<button aria-label={t('ontologyModeling.actions.dismiss')} title={t('ontologyModeling.actions.dismiss')} onClick={() => setMessage('')}><X size={13} /></button></div>}
          <div className="ontology-draft-meta"><span>{t('ontologyModeling.meta.baseline')} <code>{shortId(draft.base_content_sha256)}</code></span><span>{t('ontologyModeling.meta.activeVersion')} <b>v{draft.active_semantic_version || '-'}</b></span><span>{t('ontologyModeling.meta.objects')} <b>{formatNumber((model?.summary?.concept_count || 0) + (model?.summary?.property_count || 0) + (model?.summary?.relation_count || 0))}</b></span><span>{t('ontologyModeling.meta.changes')} <b>{formatNumber(changedCount)}</b></span><span className={draft.base_is_active === false ? 'is-stale' : ''}>{draft.base_is_active === false ? t('ontologyModeling.meta.stale') : t('ontologyModeling.meta.current')}</span></div>

          <div className="ontology-modeling-workspace">
            <aside className="ontology-modeling-navigator">
              <div className="ontology-navigator-head"><div><strong>{t('ontologyModeling.navigator.objects')}</strong><span>{t('ontologyModeling.navigator.concepts', { count: formatNumber(model?.summary?.concept_count || 0) })}</span></div><CircleDot size={15} /></div>
              <div className="ontology-model-search"><ListFilter size={13} /><input value={modelQuery} onChange={event => setModelQuery(event.target.value)} placeholder={t('ontologyModeling.navigator.searchPlaceholder')} /></div>
              <div className="ontology-model-counts"><span><b>{formatNumber(model?.summary?.concept_count || 0)}</b>{t('ontologyModeling.navigator.classes')}</span><span><b>{formatNumber(model?.summary?.property_count || 0)}</b>{t('ontologyModeling.navigator.properties')}</span><span><b>{formatNumber(model?.summary?.relation_count || 0)}</b>{t('ontologyModeling.navigator.relations')}</span></div>
              <div className="ontology-concept-list">
                {visibleConcepts.map(item => <button key={item.concept_id} className={activeConceptId === item.concept_id ? 'active' : ''} onClick={() => selectConcept(item.concept_id)}><span className="ontology-concept-dot" /><span><strong>{item.pref_label || item.code}</strong><small>{item.code} · {kindLabel(item.kind)}</small></span><em>{item.geometry_type || t('ontologyModeling.geometry.nonSpatial')}</em></button>)}
                {!visibleConcepts.length && <div className="ontology-empty-list">{t('ontologyModeling.empty.matches')}</div>}
              </div>
            </aside>

            <div className="ontology-modeling-editor">
              <div className="ontology-editor-context"><div><span>{t('ontologyModeling.editor.currentConcept')}</span><strong>{activeConcept?.pref_label || t('ontologyModeling.editor.newConcept')}</strong><code>{activeConcept?.concept_id || t('ontologyModeling.editor.pendingId')}</code></div><div className="ontology-context-kpis"><span>{t('ontologyModeling.navigator.properties')} <b>{formatNumber(conceptProperties.length)}</b></span><span>{t('ontologyModeling.navigator.relations')} <b>{formatNumber(conceptRelations.length)}</b></span></div></div>
              <div className="ontology-editor-tabs" role="tablist" aria-label={t('ontologyModeling.aria.entityTypes')}>
                <button role="tab" aria-selected={editorTab === 'concept'} className={editorTab === 'concept' ? 'active' : ''} onClick={() => setEditorTab('concept')}><GitBranch size={13} />{t('ontologyModeling.tabs.concept')}</button>
                <button role="tab" aria-selected={editorTab === 'property'} className={editorTab === 'property' ? 'active' : ''} onClick={() => setEditorTab('property')}><Plus size={13} />{t('ontologyModeling.tabs.property')}</button>
                <button role="tab" aria-selected={editorTab === 'relation'} className={editorTab === 'relation' ? 'active' : ''} onClick={() => setEditorTab('relation')}><Link2 size={13} />{t('ontologyModeling.tabs.relation')}</button>
              </div>

              {editorTab === 'concept' && <div className="ontology-editor-form" role="tabpanel">
                <div className="ontology-form-heading"><div><strong>{t('ontologyModeling.concept.heading')}</strong><span>{t('ontologyModeling.concept.help')}</span></div><button title={t('ontologyModeling.actions.newConcept')} aria-label={t('ontologyModeling.actions.newConcept')} onClick={() => { setEditingConceptId(''); setConceptForm(freshConcept(undefined, defaultDomain)); }}><Plus size={14} /></button></div>
                <label>{t('ontologyModeling.form.modelObject')}<select value={editingConceptId} onChange={event => { const item = concepts.find(concept => concept.concept_id === event.target.value); setEditingConceptId(item?.concept_id || ''); setSelectedConceptId(item?.concept_id || ''); setConceptForm(freshConcept(item, defaultDomain)); }}><option value="">{t('ontologyModeling.editor.newConcept')}</option>{concepts.map(item => <option key={item.concept_id} value={item.concept_id}>{item.pref_label} · {item.code}</option>)}</select></label>
                <div className="ontology-form-grid"><label>{t('ontologyModeling.form.code')}<input value={conceptForm.code || ''} onChange={event => setConceptForm((value: Row) => ({ ...value, code: event.target.value }))} placeholder="AgriculturalParcel" /></label><label>{t('ontologyModeling.form.kind')}<select value={conceptForm.kind || 'DomainClass'} onChange={event => setConceptForm((value: Row) => ({ ...value, kind: event.target.value }))}>{CORE_KINDS.map(value => <option key={value} value={value}>{kindLabel(value)}</option>)}</select></label></div>
                <label>{t('ontologyModeling.form.preferredName')}<input value={conceptForm.pref_label || ''} onChange={event => setConceptForm((value: Row) => ({ ...value, pref_label: event.target.value }))} /></label>
                <label>{t('ontologyModeling.form.definition')}<textarea value={conceptForm.definition || ''} onChange={event => setConceptForm((value: Row) => ({ ...value, definition: event.target.value }))} placeholder={t('ontologyModeling.form.definitionPlaceholder', { domain: ontologyTitle || t('ontologyModeling.form.currentDomain') })} /></label>
                <div className="ontology-form-grid"><label>{t('ontologyModeling.form.domain')}<select value={conceptForm.domain_id || defaultDomain} onChange={event => setConceptForm((value: Row) => ({ ...value, domain_id: event.target.value }))}>{resolvedDomainOptions.map(([value, label]) => <option key={value} value={value}>{value} · {label}</option>)}</select></label><label>{t('ontologyModeling.form.geometry')}<select value={conceptForm.geometry_type || ''} onChange={event => setConceptForm((value: Row) => ({ ...value, geometry_type: event.target.value }))}>{GEOMETRIES.map(value => <option key={value} value={value}>{value || t('ontologyModeling.geometry.nonSpatial')}</option>)}</select></label></div>
                <div className="ontology-entity-identity"><span>{t('ontologyModeling.identity.stableId')}</span><code>{editingConceptId || t('ontologyModeling.identity.generatedOnSave')}</code><span>URI</span><code>{conceptForm.uri || t('ontologyModeling.identity.generatedByService')}</code></div>
                <div className="ontology-form-actions"><button className="ontology-primary-action" disabled={busy || !selectedDraftIsEditable || !conceptForm.code || !conceptForm.pref_label} onClick={() => void submitChange('concept', conceptForm, editingConceptId)}><Save size={14} />{t('ontologyModeling.actions.saveConcept')}</button>{editingConceptId && <button className="ontology-danger-action" disabled={busy || !selectedDraftIsEditable} onClick={() => void deprecate('concept', editingConceptId)}><Archive size={13} />{t('ontologyModeling.actions.deprecate')}</button>}</div>
              </div>}

              {editorTab === 'property' && <div className="ontology-editor-form" role="tabpanel">
                <div className="ontology-form-heading"><div><strong>{t('ontologyModeling.property.heading')}</strong><span>{t('ontologyModeling.property.help')}</span></div><button title={t('ontologyModeling.actions.newProperty')} aria-label={t('ontologyModeling.actions.newProperty')} onClick={() => { setEditingPropertyId(''); setPropertyForm(freshProperty(activeConceptId)); }}><Plus size={14} /></button></div>
                <label>{t('ontologyModeling.form.existingProperty')}<select value={editingPropertyId} onChange={event => selectExistingProperty(event.target.value)}><option value="">{t('ontologyModeling.editor.newProperty')}</option>{conceptProperties.map(item => <option key={item.property_id} value={item.property_id}>{item.pref_label} · {item.code}</option>)}</select></label>
                <div className="ontology-form-grid"><label>{t('ontologyModeling.form.code')}<input value={propertyForm.code || ''} onChange={event => setPropertyForm((value: Row) => ({ ...value, code: event.target.value }))} placeholder="cultivatedArea" /></label><label>{t('ontologyModeling.form.datatype')}<select value={propertyForm.datatype || 'xsd:string'} onChange={event => setPropertyForm((value: Row) => ({ ...value, datatype: event.target.value }))}>{DATATYPES.map(value => <option key={value} value={value}>{value}</option>)}</select></label></div>
                <label>{t('ontologyModeling.form.propertyName')}<input value={propertyForm.pref_label || ''} onChange={event => setPropertyForm((value: Row) => ({ ...value, pref_label: event.target.value }))} /></label>
                <label>{t('ontologyModeling.form.ownerClass')}<select value={propertyForm.owner_concept_id || activeConceptId} onChange={event => setPropertyForm((value: Row) => ({ ...value, owner_concept_id: event.target.value }))}>{concepts.map(item => <option key={item.concept_id} value={item.concept_id}>{item.pref_label} · {item.code}</option>)}</select></label>
                <div className="ontology-form-grid"><label>{t('ontologyModeling.form.minCount')}<input type="number" min="0" value={propertyForm.min_count ?? 0} onChange={event => setPropertyForm((value: Row) => ({ ...value, min_count: Number(event.target.value) }))} /></label><label>{t('ontologyModeling.form.maxCount')}<input type="number" min="0" value={propertyForm.max_count ?? 1} onChange={event => setPropertyForm((value: Row) => ({ ...value, max_count: event.target.value === '' ? null : Number(event.target.value) }))} /></label></div>
                <div className="ontology-form-grid"><label>{t('ontologyModeling.form.ordinal')}<input type="number" min="0" value={propertyForm.ordinal ?? 0} onChange={event => setPropertyForm((value: Row) => ({ ...value, ordinal: Number(event.target.value) }))} /></label><label>{t('ontologyModeling.form.lengthPrecision')}<input value={propertyForm.length ?? ''} onChange={event => setPropertyForm((value: Row) => ({ ...value, length: event.target.value === '' ? null : Number(event.target.value) }))} placeholder={t('ontologyModeling.form.optional')} /></label></div>
                <div className="ontology-form-actions"><button className="ontology-primary-action" disabled={busy || !selectedDraftIsEditable || !propertyForm.code || !propertyForm.pref_label || !(propertyForm.owner_concept_id || activeConceptId)} onClick={() => void submitChange('property', { ...propertyForm, owner_concept_id: propertyForm.owner_concept_id || activeConceptId }, editingPropertyId)}><Save size={14} />{t('ontologyModeling.actions.saveProperty')}</button>{editingPropertyId && <button className="ontology-danger-action" disabled={busy || !selectedDraftIsEditable} onClick={() => void deprecate('property', editingPropertyId)}><Archive size={13} />{t('ontologyModeling.actions.deprecate')}</button>}</div>
              </div>}

              {editorTab === 'relation' && <div className="ontology-editor-form" role="tabpanel">
                <div className="ontology-form-heading"><div><strong>{t('ontologyModeling.relation.heading')}</strong><span>{t('ontologyModeling.relation.help')}</span></div><button title={t('ontologyModeling.actions.newRelation')} aria-label={t('ontologyModeling.actions.newRelation')} onClick={() => { setEditingRelationId(''); setRelationForm(freshRelation(activeConceptId, concepts.find(concept => concept.concept_id !== activeConceptId)?.concept_id)); }}><Plus size={14} /></button></div>
                <label>{t('ontologyModeling.form.existingRelation')}<select value={editingRelationId} onChange={event => selectExistingRelation(event.target.value)}><option value="">{t('ontologyModeling.editor.newRelation')}</option>{conceptRelations.map(item => <option key={item.relation_id} value={item.relation_id}>{item.pref_label || item.relation_type} · {item.relation_type}</option>)}</select></label>
                <div className="ontology-form-grid"><label>{t('ontologyModeling.form.relationType')}<input value={relationForm.relation_type || ''} onChange={event => setRelationForm((value: Row) => ({ ...value, relation_type: event.target.value }))} placeholder="subClassOf" /></label><label>{t('ontologyModeling.form.relationName')}<input value={relationForm.pref_label || ''} onChange={event => setRelationForm((value: Row) => ({ ...value, pref_label: event.target.value }))} /></label></div>
                <label>{t('ontologyModeling.form.sourceClass')}<select value={relationForm.source_concept_id || activeConceptId} onChange={event => setRelationForm((value: Row) => ({ ...value, source_concept_id: event.target.value }))}>{concepts.map(item => <option key={item.concept_id} value={item.concept_id}>{item.pref_label} · {item.code}</option>)}</select></label>
                <label>{t('ontologyModeling.form.targetClass')}<select value={relationForm.target_concept_id || ''} onChange={event => setRelationForm((value: Row) => ({ ...value, target_concept_id: event.target.value }))}>{concepts.filter(item => item.concept_id !== (relationForm.source_concept_id || activeConceptId)).map(item => <option key={item.concept_id} value={item.concept_id}>{item.pref_label} · {item.code}</option>)}</select></label>
                <div className="ontology-toggle-grid"><label><input type="checkbox" checked={Boolean(relationForm.transitive)} onChange={event => setRelationForm((value: Row) => ({ ...value, transitive: event.target.checked }))} />{t('ontologyModeling.form.transitive')}</label><label><input type="checkbox" checked={Boolean(relationForm.symmetric)} onChange={event => setRelationForm((value: Row) => ({ ...value, symmetric: event.target.checked }))} />{t('ontologyModeling.form.symmetric')}</label></div>
                <div className="ontology-form-actions"><button className="ontology-primary-action" disabled={busy || !selectedDraftIsEditable || !relationForm.relation_type || !relationForm.source_concept_id || !relationForm.target_concept_id} onClick={() => void submitChange('relation', relationForm, editingRelationId)}><Save size={14} />{t('ontologyModeling.actions.saveRelation')}</button>{editingRelationId && <button className="ontology-danger-action" disabled={busy || !selectedDraftIsEditable} onClick={() => void deprecate('relation', editingRelationId)}><Archive size={13} />{t('ontologyModeling.actions.deprecate')}</button>}</div>
              </div>}
            </div>

            <aside className="ontology-modeling-inspector">
              <section className="ontology-inspector-section"><div className="ontology-inspector-heading"><strong><ShieldCheck size={14} />{t('ontologyModeling.inspector.qualityGate')}</strong><button title={t('ontologyModeling.actions.validate')} aria-label={t('ontologyModeling.actions.validate')} disabled={busy} onClick={() => void runValidation()}><RefreshCw size={13} /></button></div>
                {validation ? <><div className={`ontology-inspector-status ${validation.conforms ? 'ok' : 'error'}`}><span>{validation.conforms ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />} {validation.conforms ? t('ontologyModeling.validation.pass') : t('ontologyModeling.validation.needsFix')}</span><b>{formatNumber(validation.issue_count)}</b></div>{!validation.conforms && <div className="ontology-inspector-issues">{(validation.issues || []).slice(0, 8).map((issue, index) => <button key={`${issue.code}-${index}`} onClick={() => issueClick(issue)}><b>{issue.code}</b><span>{issue.message}</span></button>)}</div>}{validation.conforms && <div className="ontology-gates-note">{t('ontologyModeling.validation.gates')}</div>}</> : <div className="ontology-inspector-empty"><Info size={15} />{t('ontologyModeling.validation.notRun')}</div>}
              </section>
              <section className="ontology-inspector-section"><div className="ontology-inspector-heading"><strong><Diff size={14} />{t('ontologyModeling.inspector.diffImpact')}</strong><button title={t('ontologyModeling.actions.diff')} aria-label={t('ontologyModeling.actions.diff')} disabled={busy} onClick={() => void loadDiff()}><RefreshCw size={13} /></button></div>
                {diffReport ? <><div className="ontology-diff-kpis"><span>{t('ontologyModeling.diff.added')} <b>{formatNumber(diffReport.summary.added)}</b></span><span>{t('ontologyModeling.diff.modified')} <b>{formatNumber(diffReport.summary.modified)}</b></span><span>{t('ontologyModeling.diff.deprecated')} <b>{formatNumber(diffReport.summary.deprecated)}</b></span></div>{diffReport.impact && <div className="ontology-impact-grid"><div><b>{formatNumber(diffReport.impact.impacted_concept_count)}</b><span>{t('ontologyModeling.diff.impactedClasses')}</span></div><div><b>{formatNumber(diffReport.impact.impacted_property_count)}</b><span>{t('ontologyModeling.diff.impactedProperties')}</span></div><div><b>{formatNumber(diffReport.impact.impacted_relation_count)}</b><span>{t('ontologyModeling.diff.impactedRelations')}</span></div></div>}<div className="ontology-diff-list">{diffReport.items.slice(0, 12).map(item => <div key={`${item.entity_type}-${item.entity_id}`}><span className={`diff-${item.change_kind}`}>{item.change_kind}</span><code>{shortId(item.entity_id)}</code></div>)}</div></> : <div className="ontology-inspector-empty"><Info size={15} />{t('ontologyModeling.diff.notLoaded')}</div>}
              </section>
              <section className="ontology-inspector-section ontology-selected-inspector"><div className="ontology-inspector-heading"><strong><CircleDot size={14} />{t('ontologyModeling.inspector.object')}</strong></div>{activeConcept ? <dl><dt>{t('ontologyModeling.inspector.name')}</dt><dd>{activeConcept.pref_label || '-'}</dd><dt>{t('ontologyModeling.form.code')}</dt><dd><code>{activeConcept.code || '-'}</code></dd><dt>{t('ontologyModeling.identity.stableId')}</dt><dd><code>{shortId(activeConcept.concept_id)}</code></dd><dt>URI</dt><dd><code>{shortId(activeConcept.uri)}</code></dd><dt>{t('ontologyModeling.inspector.lifecycle')}</dt><dd>{lifecycleLabel(activeConcept.lifecycle_status || 'active')}</dd></dl> : <div className="ontology-inspector-empty">{t('ontologyModeling.empty.selectObject')}</div>}</section>
            </aside>
          </div>
        </>
      )}
    </section>
  );
}
