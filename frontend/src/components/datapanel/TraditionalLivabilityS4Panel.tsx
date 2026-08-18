import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Map, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;
type UseRow = { clientKey: string; useId: string; useName: string; rawUseType: string; useDescription: string; gfa: string };
type ConfirmationDraft = { selectedCandidateId: string; reviewerReason: string; humanSelected: boolean };

const rows = (value: unknown): Row[] => Array.isArray(value) ? value : [];
const record = (value: unknown): Row => value && typeof value === 'object' && !Array.isArray(value) ? value as Row : {};
const text = (value: unknown): string => value === null || value === undefined || value === '' ? '-' : String(value);
const statusText = (value: unknown, t: (key: string, options?: Record<string, unknown>) => string): string => {
  const raw = text(value);
  return raw === '-' ? raw : t(`traditionalLivability.s4.statuses.${raw}`, { defaultValue: raw });
};
const makeId = (): string => crypto.randomUUID();
const newUse = (): UseRow => ({ clientKey: makeId(), useId: `use-${makeId()}`, useName: '', rawUseType: '', useDescription: '', gfa: '' });
const candidateAuditFields = ['standard_class_id', 'standard_class_label', 'authority_level', 'match_method', 'confidence', 'dictionary_version', 'rule_version', 'human_confirmation_required', 'human_confirmed', 'evidence'] as const;

function replayCandidateAudit(candidate: Row): Row {
  return Object.fromEntries(candidateAuditFields.map(field => [field, candidate[field]]));
}

function buildHumanSelectedCandidate(classRecord: Row, dictionaryVersion: string, reviewerReason: string): Row {
  return {
    standard_class_id: classRecord.class_id, standard_class_label: classRecord.label,
    authority_level: 'human_confirmation', match_method: 'human_selected', confidence: 'human_confirmed',
    dictionary_version: dictionaryVersion, rule_version: null, human_confirmation_required: false,
    human_confirmed: true, evidence: [{ evidence_type: 'reviewer_reason', reason: reviewerReason }],
  };
}

function buildS4Confirmation(candidate: Row, semantic: Row, reviewerReason: string): Row {
  const selectedCandidateAudit = candidate.match_method === 'human_selected' ? candidate : replayCandidateAudit(candidate);
  return {
    confirmed_at: new Date().toISOString(), selected_standard_class_id: candidate.standard_class_id,
    original_input_digest: semantic.original_input_digest, dictionary_version: candidate.dictionary_version,
    selected_candidate: selectedCandidateAudit,
  };
}

function errorMessages(payload: Row, fallback: string): string[] {
  const messages = [payload.detail, payload.error, ...rows(payload.validation_errors), ...rows(payload.validation_blockers)]
    .flatMap(value => typeof value === 'string' ? [value] : value ? [JSON.stringify(value)] : []);
  return messages.length ? messages : [fallback];
}

function EvidenceTable({ title, data }: { title: string; data: Row[] }) {
  const { t } = useTranslation();
  return <details><summary>{t('traditionalLivability.s4.table.summary', { title, count: data.length })}</summary><div className="traditional-table-wrap"><table className="traditional-table"><thead><tr><th>{t('traditionalLivability.s4.table.object')}</th><th>{t('traditionalLivability.s4.table.statusClass')}</th><th>{t('traditionalLivability.s4.table.distance')}</th><th>{t('traditionalLivability.s4.table.ruleSource')}</th></tr></thead><tbody>{data.length ? data.map((item, index) => <tr key={item.resource_id || item.facility_id || item.rule_id || index}><td>{text(item.resource_id || item.facility_id || item.rule_id || item.standard_class_id)}</td><td>{statusText(item.status || item.planning_status || item.mapping_status || item.relationship || item.standard_class_label, t)}</td><td>{text(item.nearest_distance_m)}</td><td>{text(item.source_record_id || item.source_dataset_id || item.interpretation_evidence || item.reason)}</td></tr>) : <tr><td colSpan={4}>-</td></tr>}</tbody></table></div></details>;
}

export default function TraditionalLivabilityS4Panel() {
  const { t } = useTranslation();
  const [resources, setResources] = useState<Row>({});
  const [resourcesError, setResourcesError] = useState<string[]>([]);
  const [reloadToken, setReloadToken] = useState(0);
  const [analysisAreaId, setAnalysisAreaId] = useState('');
  const [parcelId, setParcelId] = useState('');
  const [projectName, setProjectName] = useState('');
  const [projectDescription, setProjectDescription] = useState('');
  const [uses, setUses] = useState<UseRow[]>([newUse()]);
  const [confirmationsByUseId, setConfirmationsByUseId] = useState<Record<string, ConfirmationDraft>>({});
  const [result, setResult] = useState<Row | null>(null);
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const analyzeAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let stale = false;
    fetch('/api/uwm/traditional-livability/s4/resources', { credentials: 'include', headers: getLocaleHeaders() })
      .then(async response => ({ response, payload: await response.json() }))
      .then(({ response, payload }) => {
        if (stale) return;
        if (!response.ok) throw Object.assign(new Error(t('traditionalLivability.s4.errors.resources')), { payload });
        setResources(payload); setResourcesError([]);
        const firstArea = String(rows(payload.planning_parcels)[0]?.analysis_area_id || '');
        setAnalysisAreaId(current => current || firstArea);
      })
      .catch(loadError => { if (!stale) setResourcesError(errorMessages(record(loadError?.payload), loadError instanceof Error ? loadError.message : t('traditionalLivability.s4.errors.resources'))); });
    return () => { stale = true; };
  }, [reloadToken]);

  useEffect(() => () => { analyzeAbortRef.current?.abort(); }, []);

  const planningParcels = rows(resources.planning_parcels);
  const analysisAreas = [...new Set(planningParcels.map(parcel => String(parcel.analysis_area_id || '')).filter(Boolean))];
  const filteredParcels = planningParcels.filter(parcel => parcel.analysis_area_id === analysisAreaId);
  const selectedParcel = filteredParcels.find(parcel => parcel.planning_parcel_id === parcelId);
  const dictionaryReady = record(record(resources.readiness).dictionary).complete === true || record(record(resources.readiness).dictionary).ready === true;
  const facilityClasses = rows(resources.facility_classes);
  const assessmentsByUseId = useMemo(() => Object.fromEntries(rows(result?.use_assessments).map(item => [String(item.use_id), item])), [result]);

  const validationError = useMemo(() => {
    if (!projectName.trim()) return t('traditionalLivability.s4.validation.projectName');
    if (!analysisAreaId) return t('traditionalLivability.s4.validation.area');
    if (!selectedParcel) return t('traditionalLivability.s4.validation.parcel');
    for (const use of uses) {
      const gfa = Number(use.gfa);
      if (!use.useName.trim() || !use.rawUseType.trim() || !use.useDescription.trim()) return t('traditionalLivability.s4.validation.useFields');
      if (!(Number.isFinite(gfa) && gfa > 0)) return t('traditionalLivability.s4.validation.gfa');
    }
    return '';
  }, [analysisAreaId, projectName, selectedParcel, uses]);

  const analyze = async () => {
    if (validationError || !selectedParcel) { setErrors([validationError]); return; }
    analyzeAbortRef.current?.abort();
    const controller = new AbortController();
    analyzeAbortRef.current = controller;
    setLoading(true); setErrors([]);
    try {
      const payloadUses = uses.map(use => {
        const assessment = record(assessmentsByUseId[use.useId]);
        const semantic = record(assessment.semantic_evidence);
        const draft = confirmationsByUseId[use.useId];
        let confirmation: Row | undefined;
        if (draft?.selectedCandidateId && draft.reviewerReason.trim()) {
          const deterministic = rows(semantic.candidates).find(candidate => candidate.standard_class_id === draft.selectedCandidateId);
          const dictionaryClass = facilityClasses.find(item => item.class_id === draft.selectedCandidateId);
          const candidate = deterministic || (semantic.resolution_status === 'unresolved' && dictionaryReady && dictionaryClass
            ? buildHumanSelectedCandidate(dictionaryClass, String(semantic.dictionary_version || ''), draft.reviewerReason.trim()) : undefined);
          if (candidate) confirmation = buildS4Confirmation(candidate, semantic, draft.reviewerReason.trim());
        }
        return {
          use_id: use.useId, use_name: use.useName.trim(), raw_use_type: use.rawUseType.trim(),
          use_description: use.useDescription.trim(), gfa_m2: Number(use.gfa),
          confirmed_standard_class_id: confirmation?.selected_standard_class_id,
          human_confirmation: confirmation || undefined,
        };
      });
      const response = await fetch('/api/uwm/traditional-livability/s4/analyze', {
        method: 'POST', credentials: 'include', headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' }, signal: controller.signal,
        body: JSON.stringify({ analysis_area_id: analysisAreaId, planning_parcel_id: parcelId, project_name: projectName.trim(), project_description: projectDescription.trim(), uses: payloadUses }),
      });
      const payload = await response.json();
      if (controller.signal.aborted) return;
      if (!response.ok) { setErrors(errorMessages(payload, t('traditionalLivability.s4.errors.analyze'))); return; }
      setResult(payload);
    } catch (requestError) {
      if (controller.signal.aborted) return;
      setErrors([requestError instanceof Error ? requestError.message : t('traditionalLivability.s4.errors.analyze')]);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };

  const sendMap = () => {
    const geojson = record(result?.geojson);
    const layer = (name: string, geojsonData: unknown) => geojsonData && typeof geojsonData === 'object' ? { name, type: 'geojson', geojsonData } : null;
    window.__handleMapUpdate?.({ schema: 'map_update.v1', summary: { title: t('traditionalLivability.s4.map.title') }, layers: [
      layer(t('traditionalLivability.s4.map.proposed'), geojson.proposed_geometry), layer(t('traditionalLivability.s4.map.buffer'), geojson.screening_buffer),
      layer(t('traditionalLivability.s4.map.planningHits'), geojson.planning_resource_hits), layer(t('traditionalLivability.s4.map.currentHits'), geojson.current_facility_hits),
      layer(t('traditionalLivability.s4.map.unresolvedPlanning'), geojson.unresolved_planning_resources), layer(t('traditionalLivability.s4.map.unresolvedCurrent'), geojson.unresolved_current_facilities),
    ].filter(Boolean) });
  };

  const summary = record(result?.project_summary);
  return <div className="traditional-panel">
    <div className="traditional-panel-title"><Map size={15} /><strong>{t('traditionalLivability.s4.title')}</strong></div>
    <p>{t('traditionalLivability.s4.description', { preliminary: t('traditionalLivability.s4.evidence.preliminary'), notAssessed: t('traditionalLivability.s4.evidence.notAssessed') })}</p>
    <button className="secondary-button" onClick={() => setReloadToken(value => value + 1)}><RefreshCw size={14} />{t('traditionalLivability.s4.actions.refresh')}</button>
    {[...resourcesError, ...errors].map((message, index) => <div className="traditional-message error" key={`${message}-${index}`}><AlertTriangle size={15} />{message}</div>)}
    <div className="traditional-two-col"><div className="traditional-panel">
      <label>{t('traditionalLivability.s4.controls.projectName')}<input value={projectName} onChange={event => setProjectName(event.target.value)} /></label>
      <label>{t('traditionalLivability.s4.controls.projectDescription')}<textarea value={projectDescription} onChange={event => setProjectDescription(event.target.value)} /></label>
      <label>{t('traditionalLivability.s4.controls.area')}<select value={analysisAreaId} onChange={event => { setAnalysisAreaId(event.target.value); setParcelId(''); }}><option value="">{t('traditionalLivability.s4.controls.select')}</option>{analysisAreas.map(area => <option key={area} value={area}>{area}</option>)}</select></label>
      <label>{t('traditionalLivability.s4.controls.parcel')}<select value={parcelId} onChange={event => setParcelId(event.target.value)}><option value="">{t('traditionalLivability.s4.controls.select')}</option>{filteredParcels.map(parcel => <option key={parcel.planning_parcel_id} value={parcel.planning_parcel_id}>{parcel.raw_land_use_name || parcel.planning_parcel_id}</option>)}</select></label>
      {uses.map((use, index) => <div className="traditional-panel" key={use.clientKey}><strong>{t('traditionalLivability.s4.controls.use', { count: index + 1 })}</strong>
        <label>{t('traditionalLivability.s4.controls.useName')}<input value={use.useName} onChange={event => setUses(current => current.map(item => item.clientKey === use.clientKey ? { ...item, useName: event.target.value } : item))} /></label>
        <label>{t('traditionalLivability.s4.controls.rawUseType')}<input value={use.rawUseType} onChange={event => setUses(current => current.map(item => item.clientKey === use.clientKey ? { ...item, rawUseType: event.target.value } : item))} /></label>
        <label>{t('traditionalLivability.s4.controls.useDescription')}<textarea value={use.useDescription} onChange={event => setUses(current => current.map(item => item.clientKey === use.clientKey ? { ...item, useDescription: event.target.value } : item))} /></label>
        <label>GFA (m²)<input type="number" value={use.gfa} onChange={event => setUses(current => current.map(item => item.clientKey === use.clientKey ? { ...item, gfa: event.target.value } : item))} /></label>
        <button className="secondary-button" disabled={uses.length === 1} onClick={() => setUses(current => current.filter(item => item.clientKey !== use.clientKey))}><Trash2 size={14} />{t('traditionalLivability.s4.actions.removeUse')}</button>
      </div>)}
      <button className="secondary-button" onClick={() => setUses(current => [...current, newUse()])}><Plus size={14} />{t('traditionalLivability.s4.actions.addUse')}</button>
      <button className="primary-button" disabled={loading || Boolean(validationError)} onClick={analyze}>{loading ? t('traditionalLivability.s4.actions.analyzing') : t('traditionalLivability.s4.actions.analyze')}</button>
      {validationError && <p>{validationError}；{t('traditionalLivability.s4.validation.clientHint')}</p>}
    </div><div className="traditional-panel">
      <h4>{t('traditionalLivability.s4.results.title')}</h4><div className="traditional-boundary-grid"><div><span>{t('traditionalLivability.s4.results.status')}</span><strong>{statusText(result?.status, t)}</strong></div><div><span>max_claim</span><strong>{text(record(result?.claim_boundary).max_claim)}</strong></div><div><span>{t('traditionalLivability.s4.results.totalGfa')}</span><strong>{text(summary.total_gfa_m2)}</strong></div><div><span>project_blockers</span><strong>{rows(result?.project_blockers).join(' / ') || '-'}</strong></div></div>
      <EvidenceTable title={t('traditionalLivability.s4.results.gfaEvidence')} data={rows(summary.gfa_by_status)} />
      {rows(result?.use_assessments).map(use => {
        const semantic = record(use.semantic_evidence); const direct = record(use.parcel_direct_evidence); const neighborhood = record(use.neighborhood_evidence); const duplicate = record(use.duplicate_supply_evidence); const draft = confirmationsByUseId[use.use_id] || { selectedCandidateId: '', reviewerReason: '', humanSelected: false };
        const semanticCandidates = rows(semantic.candidates); const candidateChoices = semantic.resolution_status === 'unresolved' && dictionaryReady ? facilityClasses : semanticCandidates;
        return <details key={use.use_id} open><summary>{use.use_name} · {text(use.gfa_m2)} m² · {statusText(use.status, t)}</summary>
          <h4>{t('traditionalLivability.s4.results.semanticEvidence')}</h4><p>{statusText(semantic.resolution_status, t)} · {text(semantic.original_input_digest)}</p>
          {candidateChoices.map(candidate => <label key={candidate.standard_class_id || candidate.class_id}><input type="radio" name={`s4-${use.use_id}`} checked={draft.selectedCandidateId === (candidate.standard_class_id || candidate.class_id)} onChange={() => setConfirmationsByUseId(current => ({ ...current, [use.use_id]: { ...draft, selectedCandidateId: candidate.standard_class_id || candidate.class_id, humanSelected: !candidate.standard_class_id } }))} />{candidate.standard_class_label || candidate.label} · {candidate.match_method || t('traditionalLivability.s4.results.manualDictionary')}</label>)}
          {draft.selectedCandidateId && <label>{t('traditionalLivability.s4.results.reviewReason')}<textarea value={draft.reviewerReason} onChange={event => setConfirmationsByUseId(current => ({ ...current, [use.use_id]: { ...draft, reviewerReason: event.target.value } }))} /></label>}
          <h4>S1 {t('traditionalLivability.s4.results.demandEvidence')}</h4><pre>{JSON.stringify(record(use.demand_evidence), null, 2)}</pre>
          <h4>{t('traditionalLivability.s4.results.duplicateEvidence')}</h4><pre>{JSON.stringify(duplicate, null, 2)}</pre>
          <EvidenceTable title={t('traditionalLivability.s4.results.directPlanning')} data={rows(record(use.parcel_direct_evidence).planning_resources)} />
          <EvidenceTable title={t('traditionalLivability.s4.results.directCurrent')} data={rows(record(use.parcel_direct_evidence).current_facilities)} />
          <EvidenceTable title={t('traditionalLivability.s4.results.neighborhoodPlanning')} data={rows(record(use.neighborhood_evidence).planning_resources)} />
          <EvidenceTable title={t('traditionalLivability.s4.results.neighborhoodCurrent')} data={rows(record(use.neighborhood_evidence).current_facilities)} />
          <EvidenceTable title={t('traditionalLivability.s4.results.unresolvedPlanning')} data={rows(neighborhood.unresolved_planning_resources)} />
          <EvidenceTable title={t('traditionalLivability.s4.results.unresolvedCurrent')} data={rows(neighborhood.unresolved_current_facilities)} />
          <EvidenceTable title={t('traditionalLivability.s4.results.appliedRules')} data={[...rows(direct.applied_rules), ...rows(neighborhood.applied_rules), ...rows(duplicate.applied_rules)]} />
          <EvidenceTable title={t('traditionalLivability.s4.results.nonApplicable')} data={[...rows(direct.non_applicable_rules), ...rows(neighborhood.non_applicable_rules)]} />
          <p>validation_blockers：{rows(use.blockers).join(' / ') || '-'}</p><p>S6 {t('traditionalLivability.s4.results.spatialEvidence')}：{statusText(use.s6_status, t)}</p>
        </details>;
      })}
      <button className="secondary-button" disabled={!result?.geojson} onClick={sendMap}><Map size={14} />{t('traditionalLivability.s4.actions.sendMap')}</button>
    </div></div>
  </div>;
}
