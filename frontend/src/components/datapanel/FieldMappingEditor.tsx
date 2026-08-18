import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { getLocaleHeaders } from '../../i18n';
import {
  AlertTriangle, Check, CheckCircle2, ChevronRight, Database,
  FileCheck2, ShieldCheck, X, XCircle,
} from 'lucide-react';

interface FieldMappingEditorProps {
  sourceId: number;
  sourceName: string;
  existingMapping: Record<string, string>;
  onClose: () => void;
  onSave: (mapping: Record<string, string>) => void;
}

interface ColumnInfo {
  name: string;
  dtype: string;
  samples: string[];
}

interface ReleasedStandard {
  version_id: string;
  doc_code: string;
  title: string;
  version_label: string;
  asset_counts: { data_elements: number };
}

interface StandardElement {
  target_data_element_id: string;
  target_field: string;
  code: string;
  name_zh: string;
  datatype: string;
  unit: string;
  obligation: string;
  bound_table: string;
}

interface MappingCandidate extends StandardElement {
  confidence: number;
  evidence: Record<string, unknown>;
  match_method: string;
}

interface MappingProposal {
  source_field: string;
  source_dtype: string;
  confidence_margin: number;
  disposition: 'recommended' | 'review_required' | 'unmatched' | 'conflict';
  candidates: MappingCandidate[];
}

type ReviewDecision = 'pending' | 'approved' | 'rejected';

interface AcceptanceCase {
  case_id: string;
  label: string;
  split: 'golden' | 'holdout';
  feature_count: number;
  geometry_type: string;
  precision: number;
  recall: number;
  unexpected_recommendations: number;
  passed: boolean;
}

interface AcceptanceSummary {
  technical_status: 'passed' | 'blocked';
  promotion_ready: boolean;
  metrics: {
    micro_precision: number;
    micro_recall: number;
    unexpected_recommendations: number;
  };
  cases: AcceptanceCase[];
  governance_blockers: string[];
}

interface SourceOnboardingSummary {
  source: {
    label: string;
    feature_count: number;
    crs: string;
    full_dataset_scanned: boolean;
  };
  control_plane: {
    source_registered: boolean;
    evidence_registered: boolean;
    quality_result_recorded: false;
    data_product_version_created: false;
  };
  quality: {
    verdict: 'passed' | 'failed' | 'blocked';
    summary: { passed: number; failed: number; blocked: number; not_applicable: number };
    findings: {
      primary_key_field: string;
      primary_key_duplicate_rows: number;
      numeric_violations: Record<string, number>;
      area_outside_tolerance: number;
      invalid_geometries: number;
    };
  };
  standardization: {
    status: 'ready' | 'blocked';
    missing_target_fields: string[];
    pending_derived_fields: string[];
  };
  promotion: { ready: false; blockers: string[] };
}

interface ConfirmationResult {
  contract_id: string;
  status: string;
  mapping_count: number;
  quality_gate: {
    status: 'passed' | 'blocked' | 'not_evaluated';
    summary: {
      approved?: number;
      rejected?: number;
      mandatory_elements?: number;
      mandatory_mapped?: number;
    };
    missing_mandatory_elements: Array<{
      target_field: string;
      name_zh: string;
    }>;
  };
  publication: {
    status: 'not_published';
    ready: boolean;
    blockers: string[];
  };
}

interface QualityPreflight {
  verdict: 'passed' | 'failed' | 'blocked';
  preflight_sha256: string;
  scope: {
    mode: 'sample';
    requested_limit: number;
    observed_records: number;
    full_dataset_validated: false;
    authoritative_quality_assessment: false;
  };
  checks: Array<{
    id: string;
    status: 'passed' | 'failed' | 'blocked' | 'not_applicable';
    severity: string;
    metrics: Record<string, unknown>;
  }>;
  summary: {
    passed: number;
    failed: number;
    blocked: number;
    not_applicable: number;
  };
  release_candidate: {
    status: 'blocked';
    data_product_version_created: false;
    blockers: string[];
  };
}

const CANONICAL_FIELDS = [
  'geometry', 'name', 'id', 'area', 'perimeter', 'population',
  'land_use', 'land_type', 'elevation', 'slope', 'ndvi',
  'temperature', 'precipitation', 'district', 'province', 'city',
  'county', 'address', 'latitude', 'longitude', 'date', 'year',
  'source', 'category', 'description', 'status', 'owner', 'code',
  'value', 'unit', 'building_area', 'road_name', 'water_body',
  'soil_type', 'vegetation',
];

export default function FieldMappingEditor({
  sourceId, sourceName, existingMapping, onClose, onSave,
}: FieldMappingEditorProps) {
  const { t } = useTranslation();
  const [columns, setColumns] = useState<ColumnInfo[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({ ...existingMapping });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [inferring, setInferring] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState('');
  const [autoFilled, setAutoFilled] = useState<Set<string>>(new Set());
  const [viewMode, setViewMode] = useState<'table' | 'dragdrop'>('table');
  const [draggedField, setDraggedField] = useState<string | null>(null);
  const [releasedStandards, setReleasedStandards] = useState<ReleasedStandard[]>([]);
  const [standardVersionId, setStandardVersionId] = useState('');
  const [standardElements, setStandardElements] = useState<StandardElement[]>([]);
  const [catalogElements, setCatalogElements] = useState<StandardElement[]>([]);
  const [targetTable, setTargetTable] = useState('');
  const [loadingStandard, setLoadingStandard] = useState(false);
  const [proposals, setProposals] = useState<Record<string, MappingProposal>>({});
  const [selectedElementIds, setSelectedElementIds] = useState<Record<string, string>>({});
  const [sourceProfileHash, setSourceProfileHash] = useState('');
  const [reviewDecisions, setReviewDecisions] = useState<Record<string, ReviewDecision>>({});
  const [acceptance, setAcceptance] = useState<AcceptanceSummary | null>(null);
  const [sourceOnboarding, setSourceOnboarding] = useState<SourceOnboardingSummary | null>(null);
  const [confirmation, setConfirmation] = useState<ConfirmationResult | null>(null);
  const [preflight, setPreflight] = useState<QualityPreflight | null>(null);
  const [preflighting, setPreflighting] = useState(false);

  useEffect(() => {
    fetchColumns();
    fetchReleasedStandards();
    fetchAcceptanceSummary();
    fetchSourceOnboardingSummary();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceId]);

  const fetchReleasedStandards = async () => {
    try {
      const r = await fetch('/api/std/market/standards?limit=50', {
        credentials: 'include', headers: getLocaleHeaders(),
      });
      if (!r.ok) return;
      const d = await r.json();
      setReleasedStandards(d.items || []);
    } catch {
      setReleasedStandards([]);
    }
  };

  const fetchAcceptanceSummary = async () => {
    try {
      const r = await fetch('/api/virtual-sources/standard-mapping-acceptance', {
        credentials: 'include', headers: getLocaleHeaders(),
      });
      if (r.ok) setAcceptance(await r.json());
    } catch {
      setAcceptance(null);
    }
  };

  const fetchSourceOnboardingSummary = async () => {
    try {
      const r = await fetch('/api/virtual-sources/chongqing-source-onboarding', {
        credentials: 'include', headers: getLocaleHeaders(),
      });
      if (r.ok) setSourceOnboarding(await r.json());
    } catch {
      setSourceOnboarding(null);
    }
  };

  const fetchStandardElements = async (versionId: string) => {
    if (!versionId) return;
    setLoadingStandard(true);
    try {
      const r = await fetch(`/api/std/versions/${versionId}/data-elements`, {
        credentials: 'include', headers: getLocaleHeaders(),
      });
      if (!r.ok) throw new Error(t('fieldMapping.errors.standardLoad'));
      const d = await r.json();
      const elements: StandardElement[] = (d.data_elements || []).map(
        (item: Record<string, string>) => ({
          target_data_element_id: item.id,
          target_field: item.bound_column || item.code,
          code: item.code,
          name_zh: item.name_zh,
          datatype: item.datatype || '',
          unit: item.unit || '',
          obligation: item.obligation || 'optional',
          bound_table: item.bound_table || '',
        }),
      );
      setCatalogElements(elements);
      const scopes = Array.from(new Set(
        elements.map(item => item.bound_table).filter(Boolean),
      )).sort();
      setTargetTable(scopes.includes('parcel_current') ? 'parcel_current' : scopes[0] || '');
    } catch (e) {
      setError(e instanceof Error ? e.message : t('fieldMapping.errors.standardLoad'));
      setCatalogElements([]);
      setTargetTable('');
    } finally {
      setLoadingStandard(false);
    }
  };

  const fetchColumns = async () => {
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`/api/virtual-sources/${sourceId}/preview-columns`, {
        method: 'POST', credentials: 'include', headers: getLocaleHeaders(),
      });
      if (!r.ok) { setError(t('fieldMapping.errors.columnsLoad')); return; }
      const d = await r.json();
      const cols: ColumnInfo[] = d.columns || [];
      setColumns(cols);
      // Initialize mapping entries for columns not already in existingMapping
      const init: Record<string, string> = { ...existingMapping };
      for (const c of cols) {
        if (!(c.name in init)) init[c.name] = '';
      }
      setMapping(init);
    } catch { setError(t('fieldMapping.errors.columnsNetwork')); }
    finally { setLoading(false); }
  };

  const handleInfer = async () => {
    const hasScopedElements = catalogElements.some(item => item.bound_table);
    if (standardVersionId && hasScopedElements && !targetTable) {
      setError(t('fieldMapping.errors.targetDomainRequired'));
      return;
    }
    setInferring(true);
    setError('');
    setConfirmation(null);
    setPreflight(null);
    try {
      const r = await fetch(`/api/virtual-sources/${sourceId}/infer-mapping`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify(standardVersionId
          ? { standard_version_id: standardVersionId, target_table: targetTable || undefined }
          : {}),
      });
      if (!r.ok) {
        const failure = await r.json().catch(() => ({}));
        setError(failure.error || t('fieldMapping.errors.inferFailed'));
        return;
      }
      const d = await r.json();
      const inferred: Record<string, string> = d.mapping || {};
      const filled = new Set<string>();
      const next = { ...mapping };
      if (standardVersionId) {
        const proposalList: MappingProposal[] = d.proposals || [];
        const bySource: Record<string, MappingProposal> = {};
        const selected: Record<string, string> = {};
        const decisions: Record<string, ReviewDecision> = {};
        for (const proposal of proposalList) {
          bySource[proposal.source_field] = proposal;
          const candidate = proposal.candidates?.[0];
          if (proposal.disposition === 'recommended' && candidate) {
            next[proposal.source_field] = candidate.target_field;
            selected[proposal.source_field] = candidate.target_data_element_id;
            filled.add(proposal.source_field);
          } else {
            next[proposal.source_field] = '';
          }
          decisions[proposal.source_field] = 'pending';
        }
        setProposals(bySource);
        setSelectedElementIds(selected);
        setStandardElements(d.standard_elements || []);
        setSourceProfileHash(d.source_profile_hash || '');
        setReviewDecisions(decisions);
      } else {
        for (const [remote, target] of Object.entries(inferred)) {
          if (target && CANONICAL_FIELDS.includes(target)) {
            next[remote] = target;
            filled.add(remote);
          }
        }
      }
      setMapping(next);
      setAutoFilled(filled);
    } catch { setError(t('fieldMapping.errors.inferNetwork')); }
    finally { setInferring(false); }
  };

  const handleClearAll = () => {
    const cleared: Record<string, string> = {};
    for (const key of Object.keys(mapping)) cleared[key] = '';
    setMapping(cleared);
    setAutoFilled(new Set());
    setSelectedElementIds({});
    setReviewDecisions(Object.fromEntries(
      columns.map(column => [column.name, 'pending' as ReviewDecision]),
    ));
    setConfirmation(null);
    setPreflight(null);
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    setSavedMsg('');
    // Build only non-empty entries
    const payload: Record<string, string> = {};
    let count = 0;
    for (const [remote, target] of Object.entries(mapping)) {
      if (target) { payload[remote] = target; count++; }
    }
    const requestBody: Record<string, unknown> = { schema_mapping: payload };
    if (standardVersionId) {
      const pending = columns.filter(
        column => (reviewDecisions[column.name] || 'pending') === 'pending',
      );
      if (pending.length) {
        setError(t('fieldMapping.errors.pendingApproval', { count: pending.length }));
        setSaving(false);
        return;
      }
      const fieldBindings = Object.entries(selectedElementIds)
        .filter(([remote]) => (
          Boolean(payload[remote]) && reviewDecisions[remote] === 'approved'
        ))
        .map(([remote, elementId]) => {
          const candidate = proposals[remote]?.candidates.find(
            item => item.target_data_element_id === elementId,
          );
          return {
            source_field: remote,
            target_data_element_id: elementId,
            confidence: candidate?.confidence || 0,
            match_method: candidate?.match_method || 'human_confirmed',
            evidence: candidate?.evidence || { manual_selection: true },
          };
        });
      if (!fieldBindings.length) {
        setError(t('fieldMapping.errors.selectElement'));
        setSaving(false);
        return;
      }
      requestBody.standard_version_id = standardVersionId;
      requestBody.source_profile_hash = sourceProfileHash;
      requestBody.field_bindings = fieldBindings;
      requestBody.source_fields = columns.map(column => column.name);
      requestBody.target_table = targetTable || undefined;
      requestBody.review_decisions = columns.map(column => {
        const decision = reviewDecisions[column.name];
        const selectedId = selectedElementIds[column.name];
        const recommendedId = proposals[column.name]?.candidates[0]?.target_data_element_id;
        return {
          source_field: column.name,
          decision,
          reason: decision === 'rejected'
            ? 'not_applicable'
            : selectedId === recommendedId
              ? 'recommendation_accepted'
              : 'manual_match',
        };
      });
    }
    try {
      const r = await fetch(`/api/virtual-sources/${sourceId}/schema-mapping`, {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify(requestBody),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setError(d.error || t('fieldMapping.errors.saveFailed'));
        return;
      }
      const saved = await r.json();
      setConfirmation(saved);
      setPreflight(null);
      setSavedMsg(saved.contract_id
        ? t('fieldMapping.saved.contract', { count })
        : t('fieldMapping.saved.mapping', { count }));
      onSave(payload);
    } catch { setError(t('fieldMapping.errors.saveNetwork')); }
    finally { setSaving(false); }
  };

  const handleQualityPreflight = async () => {
    if (!confirmation?.contract_id) return;
    setPreflighting(true);
    setError('');
    try {
      const r = await fetch(`/api/virtual-sources/${sourceId}/quality-preflight`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({ sample_limit: 200 }),
      });
      if (!r.ok) {
        const failure = await r.json().catch(() => ({}));
        setError(failure.error || t('fieldMapping.errors.preflightFailed'));
        return;
      }
      setPreflight(await r.json());
    } catch {
      setError(t('fieldMapping.errors.preflightNetwork'));
    } finally {
      setPreflighting(false);
    }
  };

  const setField = (remote: string, target: string) => {
    setMapping(prev => ({ ...prev, [remote]: target }));
    setAutoFilled(prev => { const n = new Set(prev); n.delete(remote); return n; });
  };

  const setStandardField = (remote: string, elementId: string) => {
    const element = standardElements.find(
      item => item.target_data_element_id === elementId,
    );
    setSelectedElementIds(prev => {
      const next = { ...prev };
      if (elementId) next[remote] = elementId;
      else delete next[remote];
      return next;
    });
    setField(remote, element?.target_field || '');
    setReviewDecisions(prev => ({ ...prev, [remote]: 'pending' }));
    setConfirmation(null);
    setPreflight(null);
  };

  const selectStandard = (versionId: string) => {
    setStandardVersionId(versionId);
    setStandardElements([]);
    setProposals({});
    setSelectedElementIds({});
    setSourceProfileHash('');
    setCatalogElements([]);
    setTargetTable('');
    setReviewDecisions({});
    setConfirmation(null);
    setPreflight(null);
    setAutoFilled(new Set());
    setViewMode('table');
    const reset: Record<string, string> = {};
    for (const column of columns) reset[column.name] = '';
    setMapping(reset);
    if (versionId) fetchStandardElements(versionId);
  };

  const approveField = (remote: string) => {
    if (!selectedElementIds[remote]) {
      setError(t('fieldMapping.errors.selectElementFor', { field: remote }));
      return;
    }
    setError('');
    setReviewDecisions(prev => ({ ...prev, [remote]: 'approved' }));
    setConfirmation(null);
    setPreflight(null);
  };

  const rejectField = (remote: string) => {
    setSelectedElementIds(prev => {
      const next = { ...prev };
      delete next[remote];
      return next;
    });
    setMapping(prev => ({ ...prev, [remote]: '' }));
    setAutoFilled(prev => {
      const next = new Set(prev);
      next.delete(remote);
      return next;
    });
    setReviewDecisions(prev => ({ ...prev, [remote]: 'rejected' }));
    setConfirmation(null);
    setPreflight(null);
  };

  const approveRecommendations = () => {
    const decisions = { ...reviewDecisions };
    for (const [sourceField, proposal] of Object.entries(proposals)) {
      if (proposal.disposition === 'recommended' && selectedElementIds[sourceField]) {
        decisions[sourceField] = 'approved';
      }
    }
    setReviewDecisions(decisions);
    setConfirmation(null);
    setPreflight(null);
  };

  const handleDragStart = (field: string) => {
    setDraggedField(field);
  };

  const handleDrop = (target: string) => {
    if (draggedField) {
      setField(draggedField, target);
      setDraggedField(null);
    }
  };

  const truncate = (s: string, max = 20) => s.length > max ? s.slice(0, max) + '...' : s;
  const targetTables = Array.from(new Set(
    catalogElements.map(item => item.bound_table).filter(Boolean),
  )).sort();
  const scopedElements = standardElements.length
    ? standardElements
    : catalogElements.filter(item => !targetTable || item.bound_table === targetTable);
  const mandatoryElements = scopedElements.filter(item => item.obligation === 'mandatory');
  const approvedTargetIds = new Set(
    Object.entries(selectedElementIds)
      .filter(([sourceField]) => reviewDecisions[sourceField] === 'approved')
      .map(([, targetId]) => targetId),
  );
  const missingMandatory = mandatoryElements.filter(
    item => !approvedTargetIds.has(item.target_data_element_id),
  );
  const approvedCount = Object.values(reviewDecisions).filter(
    decision => decision === 'approved',
  ).length;
  const rejectedCount = Object.values(reviewDecisions).filter(
    decision => decision === 'rejected',
  ).length;
  const pendingCount = standardVersionId
    ? columns.filter(
      column => (reviewDecisions[column.name] || 'pending') === 'pending',
    ).length
    : 0;
  const recommendationReady = Object.keys(proposals).length > 0;
  const mappingGatePassed = Boolean(
    sourceProfileHash
    && (targetTables.length === 0 || targetTable)
    && pendingCount === 0
    && approvedCount > 0
    && missingMandatory.length === 0,
  );
  const livePublicationBlockers = [
    ...(mappingGatePassed ? [] : ['standard_mapping_quality_gate_not_passed']),
    ...(preflight
      ? preflight.release_candidate.blockers
      : ['dataset_quality_validation_not_run', 'data_product_version_not_created']),
  ];

  const scoreText = (value: unknown) => (
    typeof value === 'number' ? `${(value * 100).toFixed(0)}%` : t('fieldMapping.common.unused')
  );
  const blockerLabel: Record<string, string> = {
    business_steward: 'businessSteward',
    license_status: 'licenseStatus',
    standard_mapping_quality_gate_not_passed: 'mappingGate',
    dataset_quality_validation_not_run: 'qualityValidation',
    dataset_sample_preflight_not_passed: 'samplePreflight',
    full_dataset_quality_assessment_not_recorded: 'fullQuality',
    data_product_version_not_created: 'dataProductVersion',
  };
  const preflightCheckLabel: Record<string, string> = {
    sample_available: 'sampleAvailable',
    mapped_source_fields_present: 'mappedFieldsPresent',
    mandatory_sample_values_complete: 'mandatoryValues',
    mapped_datatypes_compatible: 'datatypesCompatible',
    sample_geometries_valid: 'sampleGeometries',
  };

  // --- styles ---
  const overlay: React.CSSProperties = {
    position: 'fixed', inset: 0, zIndex: 9999,
    background: 'rgba(0,0,0,0.55)', display: 'flex',
    alignItems: 'center', justifyContent: 'center',
  };
  const modal: React.CSSProperties = {
    background: '#131620', border: '1px solid #2d3348', borderRadius: 8,
    width: 'calc(100% - 32px)', maxWidth: 1080, maxHeight: '90vh',
    display: 'flex', flexDirection: 'column', color: '#e0e0e0',
    boxShadow: '0 8px 32px rgba(0,0,0,0.45)',
  };
  const header: React.CSSProperties = {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '14px 20px', borderBottom: '1px solid #2d3348', flexShrink: 0,
  };
  const body: React.CSSProperties = {
    flex: 1, overflowY: 'auto', padding: '12px 20px',
  };
  const footer: React.CSSProperties = {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '12px 20px', borderTop: '1px solid #2d3348', flexShrink: 0, gap: 8,
  };
  const statusBand: React.CSSProperties = {
    border: '1px solid #2d3348', borderRadius: 6, padding: '10px 12px',
    background: '#10131b', marginBottom: 12,
  };
  const thStyle: React.CSSProperties = {
    textAlign: 'left', padding: '6px 8px', fontSize: 12,
    color: '#888', fontWeight: 600, borderBottom: '1px solid #2d3348',
  };
  const tdStyle: React.CSSProperties = {
    padding: '5px 8px', fontSize: 13, borderBottom: '1px solid #1e2233',
    verticalAlign: 'middle',
  };
  const badge: React.CSSProperties = {
    display: 'inline-block', fontSize: 10, padding: '1px 5px', borderRadius: 3,
    background: '#262d3d', color: '#8892a8', fontFamily: 'monospace',
  };
  const selectBase: React.CSSProperties = {
    background: '#0d1117', border: '1px solid #444', borderRadius: 4,
    padding: '3px 6px', color: '#e0e0e0', fontSize: 12, width: '100%',
  };
  const btnPrimary: React.CSSProperties = {
    fontSize: 12, padding: '5px 14px', borderRadius: 4, border: 'none',
    background: '#2563eb', color: '#fff', cursor: 'pointer', fontWeight: 600,
  };
  const btnSecondary: React.CSSProperties = {
    fontSize: 12, padding: '5px 14px', borderRadius: 4,
    background: 'transparent', border: '1px solid #444',
    color: '#aaa', cursor: 'pointer',
  };

  return (
    <div style={overlay} onClick={onClose}>
      <div className="field-mapping-modal" style={modal} onClick={event => event.stopPropagation()}>
        <div style={header}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, minWidth: 0 }}>
            <Database size={17} color="#60a5fa" />
            <span style={{ fontWeight: 700, fontSize: 15, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {t('fieldMapping.title')} · {sourceName}
            </span>
          </div>
          <button onClick={onClose} title={t('fieldMapping.actions.close')} aria-label={t('fieldMapping.actions.close')} style={{
            width: 30, height: 30, display: 'grid', placeItems: 'center',
            background: 'none', border: 'none', color: '#888', cursor: 'pointer',
          }}><X size={17} /></button>
        </div>

        <div style={body}>
          {acceptance && (
            <div style={statusBand}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <FileCheck2 size={15} color="#34d399" />
                  <strong style={{ fontSize: 12 }}>{t('fieldMapping.acceptance.title')}</strong>
                  <span style={{ fontSize: 11, color: '#34d399' }}>{t('fieldMapping.acceptance.technicalPassed')}</span>
                </div>
                <span style={{ fontSize: 11, color: '#fbbf24' }}>
                  {t('fieldMapping.acceptance.blockers', { count: acceptance.governance_blockers.length })}
                </span>
              </div>
              <div className="mapping-acceptance-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 10, marginTop: 8 }}>
                {acceptance.cases.map(item => (
                  <div key={item.case_id} style={{ borderTop: '1px solid #272d3e', paddingTop: 7, minWidth: 0 }}>
                    <div style={{ fontSize: 11, color: '#cbd5e1', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.label}</div>
                    <div style={{ fontSize: 10, color: '#7f8aa3', marginTop: 2 }}>
                      {t('fieldMapping.acceptance.metrics', { features: item.feature_count.toLocaleString(), precision: (item.precision * 100).toFixed(0), recall: (item.recall * 100).toFixed(0) })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {sourceOnboarding && (
            <div style={{ ...statusBand, borderColor: '#513b24' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <AlertTriangle size={15} color="#fbbf24" />
                  <strong style={{ fontSize: 12 }}>{t('fieldMapping.onboarding.title')}</strong>
                  <span style={{ fontSize: 11, color: '#fbbf24' }}>
                    {sourceOnboarding.quality.verdict === 'passed' ? t('fieldMapping.common.passed') : t('fieldMapping.common.failed')}
                  </span>
                </div>
                <span style={{ fontSize: 11, color: '#a8b0c2' }}>
                  {t('fieldMapping.onboarding.scanned', { count: sourceOnboarding.source.feature_count.toLocaleString(), crs: sourceOnboarding.source.crs })}
                </span>
              </div>
              <div className="mapping-source-audit-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 10, marginTop: 9 }}>
                {[
                  [t('fieldMapping.onboarding.controlLedger'), sourceOnboarding.control_plane.source_registered, sourceOnboarding.control_plane.source_registered ? t('fieldMapping.onboarding.sourceRegistered') : t('fieldMapping.onboarding.sourcePending')],
                  [t('fieldMapping.onboarding.qualityEvidence'), sourceOnboarding.control_plane.evidence_registered, sourceOnboarding.control_plane.evidence_registered ? t('fieldMapping.onboarding.evidenceRegistered') : t('fieldMapping.onboarding.evidencePending')],
                  [t('fieldMapping.onboarding.primaryKey'), sourceOnboarding.quality.findings.primary_key_duplicate_rows === 0, t('fieldMapping.onboarding.duplicates', { field: sourceOnboarding.quality.findings.primary_key_field, count: sourceOnboarding.quality.findings.primary_key_duplicate_rows.toLocaleString() })],
                  [t('fieldMapping.onboarding.areaRule'), (sourceOnboarding.quality.findings.numeric_violations.TBMJ || 0) === 0, t('fieldMapping.onboarding.nonPositive', { count: (sourceOnboarding.quality.findings.numeric_violations.TBMJ || 0).toLocaleString() })],
                  [t('fieldMapping.onboarding.standardFields'), sourceOnboarding.standardization.status === 'ready', sourceOnboarding.standardization.pending_derived_fields.length ? t('fieldMapping.onboarding.pendingDerived', { fields: sourceOnboarding.standardization.pending_derived_fields.join(', ') }) : t('fieldMapping.onboarding.covered')],
                ].map(([label, passed, detail]) => (
                  <div key={String(label)} style={{ borderTop: '1px solid #3c342d', paddingTop: 7, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, color: '#a8b0c2' }}>
                      {passed ? <CheckCircle2 size={13} color="#34d399" /> : <XCircle size={13} color="#fbbf24" />}
                      {label}
                    </div>
                    <div style={{ fontSize: 10, color: passed ? '#34d399' : '#fbbf24', marginTop: 3, overflowWrap: 'anywhere' }}>{detail}</div>
                  </div>
                ))}
              </div>
              <div style={{ fontSize: 10, color: '#8791a8', marginTop: 8 }}>
                {t('fieldMapping.onboarding.qualitySummary', { invalid: sourceOnboarding.quality.findings.invalid_geometries, area: sourceOnboarding.quality.findings.area_outside_tolerance, blockers: sourceOnboarding.promotion.blockers.length })}
              </div>
            </div>
          )}

          {standardVersionId && (
            <div className="mapping-workflow-grid" style={{ ...statusBand, display: 'grid', gridTemplateColumns: 'repeat(6, minmax(0, 1fr))', gap: 6 }}>
              {[
                [t('fieldMapping.workflow.profile'), columns.length > 0, t('fieldMapping.workflow.fields', { count: columns.length })],
                [t('fieldMapping.workflow.recommendation'), recommendationReady, recommendationReady ? t('fieldMapping.common.generated') : t('fieldMapping.common.pending')],
                [t('fieldMapping.workflow.review'), recommendationReady && pendingCount === 0, recommendationReady ? t('fieldMapping.workflow.pendingItems', { count: pendingCount }) : t('fieldMapping.common.notStarted')],
                [t('fieldMapping.workflow.gate'), confirmation ? confirmation.quality_gate.status === 'passed' : mappingGatePassed, confirmation?.quality_gate.status === 'passed' || mappingGatePassed ? t('fieldMapping.common.passed') : t('fieldMapping.common.blocked')],
                [t('fieldMapping.workflow.preflight'), preflight?.verdict === 'passed', preflight ? t('fieldMapping.workflow.sampled', { count: preflight.scope.observed_records }) : t('fieldMapping.common.notRun')],
                [t('fieldMapping.workflow.product'), false, t('fieldMapping.common.notCreated')],
              ].map(([label, passed, detail], index) => (
                <div key={String(label)} style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                  {passed ? <CheckCircle2 size={14} color="#34d399" /> : <XCircle size={14} color={index >= 4 ? '#fbbf24' : '#7f8aa3'} />}
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 10, color: '#a8b0c2' }}>{label}</div>
                    <div style={{ fontSize: 10, color: passed ? '#34d399' : '#7f8aa3' }}>{detail}</div>
                  </div>
                  {index < 5 && <ChevronRight size={12} color="#40485d" style={{ marginLeft: 'auto' }} />}
                </div>
              ))}
            </div>
          )}

          {loading && (
            <div style={{ textAlign: 'center', padding: 32, color: '#888' }}>
              <span style={{ display: 'inline-block', animation: 'spin 1s linear infinite', border: '2px solid #333', borderTop: '2px solid #2563eb', borderRadius: '50%', width: 20, height: 20 }} />
              <div style={{ marginTop: 8 }}>{t('fieldMapping.loading.columns')}</div>
            </div>
          )}

          {!loading && error && !columns.length && (
            <div style={{ color: '#ef4444', textAlign: 'center', padding: 24 }}>{error}</div>
          )}

          {!loading && !error && columns.length === 0 && (
            <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>{t('fieldMapping.errors.remoteColumns')}</div>
          )}

          {!loading && columns.length > 0 && (
            <>
              <div className="mapping-control-grid" style={{ display: 'grid', gridTemplateColumns: standardVersionId ? '110px minmax(220px, 1fr) 90px minmax(160px, .55fr)' : '110px minmax(0, 1fr)', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                <label htmlFor="mapping-standard" style={{ fontSize: 12, color: '#aaa' }}>{t('fieldMapping.controls.targetStandard')}</label>
                <select id="mapping-standard" value={standardVersionId} onChange={event => selectStandard(event.target.value)} style={selectBase}>
                  <option value="">{t('fieldMapping.controls.canonicalGis')}</option>
                  {releasedStandards.map(standard => (
                    <option key={standard.version_id} value={standard.version_id}>
                      {standard.doc_code} {standard.version_label} · {standard.title}
                    </option>
                  ))}
                </select>
                {standardVersionId && <label htmlFor="mapping-target-table" style={{ fontSize: 12, color: '#aaa' }}>{t('fieldMapping.controls.targetDomain')}</label>}
                {standardVersionId && (
                  <select id="mapping-target-table" value={targetTable} disabled={loadingStandard} onChange={event => {
                    setTargetTable(event.target.value);
                    setStandardElements([]);
                    setProposals({});
                    setSourceProfileHash('');
                    setReviewDecisions({});
                    setConfirmation(null);
                    setPreflight(null);
                  }} style={selectBase}>
                    <option value="">{t('fieldMapping.common.notSelected')}</option>
                    {targetTables.map(scope => <option key={scope} value={scope}>{scope}</option>)}
                  </select>
                )}
              </div>

              {!standardVersionId && (
                <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                  <button onClick={() => setViewMode('table')} style={{ ...btnSecondary, color: viewMode === 'table' ? '#fff' : '#aaa', borderColor: viewMode === 'table' ? '#2563eb' : '#444' }}>{t('fieldMapping.views.table')}</button>
                  <button onClick={() => setViewMode('dragdrop')} style={{ ...btnSecondary, color: viewMode === 'dragdrop' ? '#fff' : '#aaa', borderColor: viewMode === 'dragdrop' ? '#2563eb' : '#444' }}>{t('fieldMapping.views.dragDrop')}</button>
                </div>
              )}

              {viewMode === 'table' && (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', minWidth: standardVersionId ? 820 : undefined, borderCollapse: 'collapse', tableLayout: 'fixed' }}>
                    <thead>
                      <tr>
                        <th style={{ ...thStyle, width: standardVersionId ? '16%' : '20%' }}>{t('fieldMapping.table.sourceField')}</th>
                        <th style={{ ...thStyle, width: standardVersionId ? '13%' : '22%' }}>{t('fieldMapping.table.sampleValue')}</th>
                        <th style={{ ...thStyle, width: standardVersionId ? '32%' : '58%' }}>{t('fieldMapping.table.standardTarget')}</th>
                        {standardVersionId && <th style={{ ...thStyle, width: '25%' }}>{t('fieldMapping.table.recommendationBasis')}</th>}
                        {standardVersionId && <th style={{ ...thStyle, width: '14%', textAlign: 'center' }}>{t('fieldMapping.table.humanReview')}</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {columns.map(col => {
                        const sample = col.samples?.length ? col.samples[0] : '';
                        const isAuto = autoFilled.has(col.name);
                        const proposal = proposals[col.name];
                        const candidate = proposal?.candidates[0];
                        const decision = reviewDecisions[col.name] || 'pending';
                        return (
                          <tr key={col.name}>
                            <td style={tdStyle}>
                              <div style={{ fontFamily: 'monospace', fontSize: 12, overflowWrap: 'anywhere' }}>{col.name}</div>
                              <span style={badge}>{col.dtype}</span>
                            </td>
                            <td style={{ ...tdStyle, color: '#888', fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={sample}>
                              {truncate(sample, 18)}
                            </td>
                            <td style={tdStyle}>
                              <select value={standardVersionId ? selectedElementIds[col.name] || '' : mapping[col.name] || ''} onChange={event => standardVersionId ? setStandardField(col.name, event.target.value) : setField(col.name, event.target.value)} style={{ ...selectBase, minHeight: 30, ...(isAuto ? { borderColor: '#2563eb', color: '#93c5fd' } : {}) }}>
                                <option value="">{t('fieldMapping.common.unmapped')}</option>
                                {standardVersionId
                                  ? scopedElements.map(element => {
                                    const selectedElsewhere = Object.entries(selectedElementIds).some(([source, id]) => source !== col.name && id === element.target_data_element_id);
                                    return (
                                      <option key={element.target_data_element_id} value={element.target_data_element_id} disabled={selectedElsewhere}>
                                        {element.code} · {element.name_zh}{element.obligation === 'mandatory' ? ` · ${t('fieldMapping.common.required')}` : ''}
                                      </option>
                                    );
                                  })
                                  : CANONICAL_FIELDS.map(field => <option key={field} value={field}>{field}</option>)}
                              </select>
                            </td>
                            {standardVersionId && (
                              <td style={tdStyle}>
                                {proposal ? (
                                  <>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: proposal.disposition === 'recommended' ? '#60a5fa' : proposal.disposition === 'conflict' ? '#f87171' : '#fbbf24' }}>
                                      {t(`fieldMapping.disposition.${proposal.disposition}`)}
                                      {candidate && <strong>{(candidate.confidence * 100).toFixed(1)}%</strong>}
                                    </div>
                                    {candidate && (
                                      <details style={{ marginTop: 3, fontSize: 10, color: '#8791a8' }}>
                                        <summary style={{ cursor: 'pointer' }}>{t('fieldMapping.table.matchBasis')}</summary>
                                        <div style={{ marginTop: 4, lineHeight: 1.55 }}>
                                          {t('fieldMapping.table.matchedOn', { value: String(candidate.evidence.matched_on || candidate.code) })}<br />
                                          {t('fieldMapping.table.scores', { lexical: scoreText(candidate.evidence.lexical_score), semantic: scoreText(candidate.evidence.semantic_score), type: scoreText(candidate.evidence.type_score) })}
                                        </div>
                                      </details>
                                    )}
                                  </>
                                ) : <span style={{ fontSize: 10, color: '#687086' }}>{t('fieldMapping.common.pendingGeneration')}</span>}
                              </td>
                            )}
                            {standardVersionId && (
                              <td style={{ ...tdStyle, textAlign: 'center' }}>
                                <div style={{ display: 'flex', justifyContent: 'center', gap: 5 }}>
                                  <button type="button" title={t('fieldMapping.actions.approve')} aria-label={t('fieldMapping.actions.approveNamed', { field: col.name })} onClick={() => approveField(col.name)} disabled={!selectedElementIds[col.name]} style={{ width: 28, height: 28, display: 'grid', placeItems: 'center', borderRadius: 4, border: `1px solid ${decision === 'approved' ? '#10b981' : '#3b4254'}`, background: decision === 'approved' ? '#12382d' : 'transparent', color: decision === 'approved' ? '#34d399' : '#7f8aa3', cursor: selectedElementIds[col.name] ? 'pointer' : 'not-allowed' }}><Check size={14} /></button>
                                  <button type="button" title={t('fieldMapping.actions.reject')} aria-label={t('fieldMapping.actions.rejectNamed', { field: col.name })} onClick={() => rejectField(col.name)} style={{ width: 28, height: 28, display: 'grid', placeItems: 'center', borderRadius: 4, border: `1px solid ${decision === 'rejected' ? '#ef4444' : '#3b4254'}`, background: decision === 'rejected' ? '#3a1c24' : 'transparent', color: decision === 'rejected' ? '#f87171' : '#7f8aa3', cursor: 'pointer' }}><X size={14} /></button>
                                </div>
                                <div style={{ fontSize: 9, color: decision === 'approved' ? '#34d399' : decision === 'rejected' ? '#f87171' : '#7f8aa3', marginTop: 2 }}>
                                  {decision === 'approved' ? t('fieldMapping.decisions.approved') : decision === 'rejected' ? t('fieldMapping.decisions.rejected') : t('fieldMapping.decisions.pending')}
                                </div>
                              </td>
                            )}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {viewMode === 'dragdrop' && !standardVersionId && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, color: '#888' }}>{t('fieldMapping.table.sourceField')}</div>
                    {columns.map(col => (
                      <div key={col.name} draggable onDragStart={() => handleDragStart(col.name)} style={{ padding: 8, marginBottom: 4, background: '#1a1a1a', border: '1px solid #333', borderRadius: 4, cursor: 'grab', fontSize: 12 }}>{col.name} <span style={{ color: '#666', fontSize: 10 }}>({col.dtype})</span></div>
                    ))}
                  </div>
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, color: '#888' }}>{t('fieldMapping.table.standardField')}</div>
                    {CANONICAL_FIELDS.map(field => {
                      const mapped = Object.entries(mapping).find(([, value]) => value === field)?.[0];
                      return <div key={field} onDragOver={event => event.preventDefault()} onDrop={() => handleDrop(field)} style={{ padding: 8, marginBottom: 4, background: mapped ? '#15352b' : '#0d1117', border: `1px solid ${mapped ? '#10b981' : '#333'}`, borderRadius: 4, fontSize: 12 }}>{field} {mapped && <span style={{ color: '#10b981', fontSize: 10 }}>← {mapped}</span>}</div>;
                    })}
                  </div>
                </div>
              )}

              {standardVersionId && recommendationReady && (
                <div style={{ ...statusBand, marginTop: 12, marginBottom: 0 }}>
                  <div className="mapping-quality-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <ShieldCheck size={15} color={(confirmation?.quality_gate.status === 'passed' || mappingGatePassed) ? '#34d399' : '#fbbf24'} />
                        <strong style={{ fontSize: 12 }}>{t('fieldMapping.quality.mappingGate')}</strong>
                        <span style={{ fontSize: 11, color: (confirmation?.quality_gate.status === 'passed' || mappingGatePassed) ? '#34d399' : '#fbbf24' }}>
                          {(confirmation?.quality_gate.status === 'passed' || mappingGatePassed) ? t('fieldMapping.common.passed') : t('fieldMapping.common.blocked')}
                        </span>
                      </div>
                      <div style={{ fontSize: 10, color: '#8791a8', marginTop: 5 }}>
                        {t('fieldMapping.quality.decisionCounts', { approved: confirmation?.quality_gate.summary.approved ?? approvedCount, rejected: confirmation?.quality_gate.summary.rejected ?? rejectedCount, pending: pendingCount })}
                        <br />{t('fieldMapping.quality.mandatoryCounts', { mapped: confirmation?.quality_gate.summary.mandatory_mapped ?? (mandatoryElements.length - missingMandatory.length), total: confirmation?.quality_gate.summary.mandatory_elements ?? mandatoryElements.length })}
                      </div>
                      {missingMandatory.length > 0 && (
                        <div style={{ fontSize: 10, color: '#fbbf24', marginTop: 4, overflowWrap: 'anywhere' }}>
                          {t('fieldMapping.quality.missing', { fields: missingMandatory.slice(0, 8).map(item => item.target_field).join(', '), more: missingMandatory.length > 8 ? t('fieldMapping.quality.more', { count: missingMandatory.length }) : '' })}
                        </div>
                      )}
                    </div>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        {preflight?.verdict === 'passed'
                          ? <CheckCircle2 size={15} color="#34d399" />
                          : <AlertTriangle size={15} color="#fbbf24" />}
                        <strong style={{ fontSize: 12 }}>{t('fieldMapping.quality.preflight')}</strong>
                        <span style={{ fontSize: 11, color: preflight?.verdict === 'passed' ? '#34d399' : '#fbbf24' }}>
                          {preflight ? t(`fieldMapping.verdict.${preflight.verdict}`) : t('fieldMapping.common.notRun')}
                        </span>
                      </div>
                      {preflight ? (
                        <div style={{ fontSize: 10, color: '#8791a8', marginTop: 5, lineHeight: 1.55 }}>
                          {t('fieldMapping.quality.sampleSummary', { count: preflight.scope.observed_records, passed: preflight.summary.passed, failed: preflight.summary.failed })}
                          <br />{preflight.checks.map(check => `${t(`fieldMapping.checks.${preflightCheckLabel[check.id] || 'unknown'}`)}: ${t(`fieldMapping.verdict.${check.status}`)}`).join(' · ')}
                          <br />{t('fieldMapping.quality.fingerprint', { value: preflight.preflight_sha256.slice(0, 12) })}
                        </div>
                      ) : <div style={{ fontSize: 10, color: '#8791a8', marginTop: 5 }}>{t('fieldMapping.quality.preflightNotRun')}</div>}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 7, alignItems: 'flex-start', marginTop: 10, paddingTop: 9, borderTop: '1px solid #272d3e' }}>
                    <AlertTriangle size={15} color="#fbbf24" style={{ flex: '0 0 auto' }} />
                    <div>
                      <strong style={{ fontSize: 12 }}>{t('fieldMapping.quality.productNotCreated')}</strong>
                      <div style={{ fontSize: 10, color: '#8791a8', marginTop: 4, lineHeight: 1.55 }}>
                        {(preflight?.release_candidate.blockers || confirmation?.publication.blockers || livePublicationBlockers).map(code => t(`fieldMapping.blockers.${blockerLabel[code] || 'unknown'}`)).join(' · ')}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

          {error && columns.length > 0 && <div style={{ color: '#f87171', fontSize: 12, marginTop: 8 }}>{error}</div>}
          {savedMsg && <div style={{ color: '#34d399', fontSize: 12, marginTop: 8, fontWeight: 600 }}>{savedMsg}</div>}
        </div>

        <div className="field-mapping-footer" style={footer}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button style={btnSecondary} onClick={handleInfer} disabled={inferring || loading || loadingStandard}>
              {inferring ? t('fieldMapping.actions.generating') : standardVersionId ? t('fieldMapping.actions.generateCandidates') : t('fieldMapping.actions.autoInfer')}
            </button>
            {standardVersionId && recommendationReady && (
              <button style={btnSecondary} onClick={approveRecommendations}>{t('fieldMapping.actions.approveHighConfidence')}</button>
            )}
            {confirmation?.quality_gate.status === 'passed' && (
              <button
                style={{ ...btnSecondary, display: 'inline-flex', alignItems: 'center', gap: 5 }}
                onClick={handleQualityPreflight}
                disabled={preflighting}
              >
                <ShieldCheck size={13} />
                {preflighting ? t('fieldMapping.actions.preflighting') : preflight ? t('fieldMapping.actions.rerunPreflight') : t('fieldMapping.actions.runPreflight')}
              </button>
            )}
            <button style={btnSecondary} onClick={handleClearAll} disabled={loading}>{t('fieldMapping.actions.clear')}</button>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button style={btnSecondary} onClick={onClose}>{confirmation ? t('fieldMapping.actions.done') : t('fieldMapping.actions.cancel')}</button>
            <button style={{ ...btnPrimary, ...(saving ? { opacity: 0.7 } : {}) }} onClick={handleSave} disabled={saving || loading || (Boolean(standardVersionId) && (pendingCount > 0 || approvedCount === 0))}>
              {saving ? t('fieldMapping.actions.confirming') : confirmation ? t('fieldMapping.actions.reconfirm') : standardVersionId ? t('fieldMapping.actions.confirmContract') : t('fieldMapping.actions.saveMapping')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
