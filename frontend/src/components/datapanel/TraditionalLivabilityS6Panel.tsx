import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, MapPin, RefreshCw, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;
const rows = (value: unknown): Row[] => Array.isArray(value) ? value : [];
const record = (value: unknown): Row => value && typeof value === 'object' && !Array.isArray(value) ? value as Row : {};
const text = (value: unknown) => value === null || value === undefined || value === '' ? '-' : String(value);

const candidateAuditFields = [
  'standard_class_id', 'standard_class_label', 'authority_level', 'match_method',
  'confidence', 'dictionary_version', 'rule_version', 'human_confirmation_required',
  'human_confirmed', 'evidence',
] as const;

function replayCandidateAudit(candidate: Row): Row {
  return Object.fromEntries(candidateAuditFields.map(field => [field, candidate[field]]));
}

function buildHumanSelectedCandidate(classRecord: Row, dictionaryVersion: string, reviewerReason: string): Row {
  return {
    standard_class_id: classRecord.class_id,
    standard_class_label: classRecord.label,
    authority_level: 'human_confirmation',
    match_method: 'human_selected',
    confidence: 'human_confirmed',
    dictionary_version: dictionaryVersion,
    rule_version: null,
    human_confirmation_required: false,
    human_confirmed: true,
    evidence: [{ evidence_type: 'reviewer_reason', reason: reviewerReason }],
  };
}

function buildS6Confirmation(candidate: Row, semantic: Row, reviewerReason: string): Row {
  const selectedCandidateAudit = candidate.match_method === 'human_selected'
    ? candidate
    : replayCandidateAudit(candidate);
  return {
    actor_id: 'frontend_reviewer',
    confirmed_at: new Date().toISOString(),
    selected_standard_class_id: candidate.standard_class_id,
    original_input_digest: semantic.original_input_digest,
    dictionary_version: candidate.dictionary_version,
    selected_candidate: selectedCandidateAudit,
  };
}

function unresolvedFeatureCollection(geojson: Row, labels: { planningResource: string; currentFacility: string }): Row {
  const taggedFeatures = (collection: unknown, kind: 'planning_resource' | 'current_facility', label: string) =>
    rows(record(collection).features).map(feature => ({
      ...feature,
      properties: {
        ...record(feature.properties),
        unresolved_object_kind: kind,
        unresolved_object_label: label,
      },
    }));
  return {
    type: 'FeatureCollection',
    features: [
      ...taggedFeatures(geojson.unresolved_planning_resources, 'planning_resource', labels.planningResource),
      ...taggedFeatures(geojson.unresolved_current_facilities, 'current_facility', labels.currentFacility),
    ],
  };
}

declare global {
  interface Window {
    __handleMapUpdate?: (payload: any) => void;
  }
}

export default function TraditionalLivabilityS6Panel() {
  const { t } = useTranslation();
  const [resources, setResources] = useState<Row>({});
  const [authority, setAuthority] = useState<Row>({});
  const [resourcesSettled, setResourcesSettled] = useState(false);
  const [authoritySettled, setAuthoritySettled] = useState(false);
  const [resourcesError, setResourcesError] = useState('');
  const [authorityError, setAuthorityError] = useState('');
  const [reloadToken, setReloadToken] = useState(0);
  const [result, setResult] = useState<Row | null>(null);
  const [areaId, setAreaId] = useState('');
  const [inputMode, setInputMode] = useState<'point' | 'parcel'>('point');
  const [parcelId, setParcelId] = useState('');
  const [longitude, setLongitude] = useState<number | null>(null);
  const [latitude, setLatitude] = useState<number | null>(null);
  const [facilityName, setFacilityName] = useState('');
  const [rawType, setRawType] = useState('');
  const [useDescription, setUseDescription] = useState('');
  const [selectedCandidateId, setSelectedCandidateId] = useState('');
  const [confirmationReason, setConfirmationReason] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectingPoint, setSelectingPoint] = useState(false);
  const [selectionMessage, setSelectionMessage] = useState('');
  const [profiles, setProfiles] = useState<Row>({});
  const [handoff, setHandoff] = useState<Row | null>(null);
  const [s1Result, setS1Result] = useState<Row | null>(null);
  const [handoffLoading, setHandoffLoading] = useState(false);

  const invalidateDownstream = () => {
    setHandoff(null);
    setS1Result(null);
  };

  useEffect(() => {
    let stale = false;
    setResourcesSettled(false);
    setResourcesError('');
    fetch('/api/uwm/traditional-livability/s6/resources', { credentials: 'include', headers: getLocaleHeaders() })
      .then(async response => ({ response, payload: await response.json() }))
      .then(({ response, payload }) => {
        if (stale) return;
        if (!response.ok) throw new Error(payload.detail || payload.error || t('traditionalLivability.s6.errors.resources'));
        setResources(payload);
        const areas = rows(payload.planning_areas);
        setAreaId(current => current || String(areas[0]?.planning_area_id || ''));
      })
      .catch(loadError => { if (!stale) setResourcesError(loadError instanceof Error ? loadError.message : t('traditionalLivability.s6.errors.resources')); })
      .finally(() => { if (!stale) setResourcesSettled(true); });
    return () => { stale = true; };
  }, [reloadToken]);
  useEffect(() => {
    fetch('/api/uwm/traditional-livability/s1/profiles', { credentials: 'include', headers: getLocaleHeaders() })
      .then(async response => ({ response, payload: await response.json() }))
      .then(({ payload }) => setProfiles(payload))
      .catch(() => setProfiles({ status: 'unavailable', profiles: [], blockers: ['s1_profiles_unavailable'] }));
  }, [reloadToken]);

  useEffect(() => {
    let stale = false;
    setAuthoritySettled(false);
    setAuthorityError('');
    fetch('/api/uwm/traditional-livability/s6/dictionary', { credentials: 'include', headers: getLocaleHeaders() })
      .then(async response => ({ response, payload: await response.json() }))
      .then(({ response, payload }) => {
        if (stale) return;
        if (!response.ok) throw new Error(payload.detail || payload.error || t('traditionalLivability.s6.errors.authority'));
        setAuthority(payload);
      })
      .catch(loadError => { if (!stale) setAuthorityError(loadError instanceof Error ? loadError.message : t('traditionalLivability.s6.errors.authority')); })
      .finally(() => { if (!stale) setAuthoritySettled(true); });
    return () => { stale = true; };
  }, [reloadToken]);
  useEffect(() => {
    const selected = (event: Event) => {
      const detail = (event as CustomEvent<{ longitude: number; latitude: number }>).detail;
      setLongitude(detail.longitude);
      setLatitude(detail.latitude);
      invalidateDownstream();
      setSelectingPoint(false);
      setSelectionMessage(t('traditionalLivability.s6.messages.pointSelected'));
    };
    const cancelled = (event: Event) => {
      const reason = (event as CustomEvent<{ reason?: string }>).detail?.reason || 'unknown';
      setSelectingPoint(false);
      setSelectionMessage(t('traditionalLivability.s6.messages.pointCancelled', { reason }));
    };
    window.addEventListener('traditional-livability-s6-point-selected', selected);
    window.addEventListener('traditional-livability-s6-point-selection-cancelled', cancelled);
    return () => {
      window.removeEventListener('traditional-livability-s6-point-selected', selected);
      window.removeEventListener('traditional-livability-s6-point-selection-cancelled', cancelled);
    };
  }, []);

  const areaResources = useMemo(() => rows(resources.planning_resources).filter(row => row.planning_area_id === areaId), [resources, areaId]);
  const selectableParcels = areaResources.filter(row => row.resource_id);
  const semantic = record(result?.semantic_resolution);
  const candidates = rows(semantic.candidates);
  const selectedCandidate = candidates.find(candidate => candidate.standard_class_id === selectedCandidateId);
  const dictionaryStatus = record(authority.facility_dictionary);
  const dictionaryClasses = rows(dictionaryStatus.classes);
  const manualClass = dictionaryClasses.find(classRecord => classRecord.class_id === selectedCandidateId);
  const unresolved = record(result?.unresolved_objects);
  const authorityReady = authority.ready === true;

  const requestPoint = () => {
    setSelectingPoint(true);
    setSelectionMessage(t('traditionalLivability.s6.messages.selectPoint'));
    window.dispatchEvent(new CustomEvent('traditional-livability-s6-request-point-selection'));
  };

  const analyze = async () => {
    setLoading(true);
    setError('');
    try {
      const reviewerReason = confirmationReason.trim();
      const humanSelectedCandidate = manualClass && reviewerReason
        ? buildHumanSelectedCandidate(manualClass, String(dictionaryStatus.version || ''), reviewerReason)
        : undefined;
      const confirmationCandidate = selectedCandidate || humanSelectedCandidate;
      const confirmation = confirmationCandidate && reviewerReason
        ? buildS6Confirmation(confirmationCandidate, semantic, reviewerReason)
        : undefined;
      const body = {
        input_mode: inputMode === 'parcel' ? 'planning_parcel' : 'point',
        analysis_area_id: areaId,
        facility_name: facilityName.trim(),
        raw_facility_type: rawType.trim(),
        use_description: useDescription.trim(),
        ...(inputMode === 'point' ? { longitude, latitude } : { parcel_id: parcelId }),
        confirmed_standard_class_id: selectedCandidateId || undefined,
        human_confirmation: confirmation,
      };
      const response = await fetch('/api/uwm/traditional-livability/s6/analyze', { method: 'POST', credentials: 'include', headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const payload = await response.json();
      setResult(payload);
      setHandoff(null);
      setS1Result(null);
      if (!response.ok) setError(rows(payload.validation_blockers).join(' / ') || payload.detail || t('traditionalLivability.s6.errors.analyze'));
      setSelectedCandidateId('');
      setConfirmationReason('');
    } catch (analysisError) {
      setError(analysisError instanceof Error ? analysisError.message : t('traditionalLivability.s6.errors.analyze'));
    } finally {
      setLoading(false);
    }
  };

  const createHandoff = async () => {
    if (!result) return;
    setHandoffLoading(true);
    setError('');
    try {
      const response = await fetch('/api/uwm/traditional-livability/s6/handoffs', {
        method: 'POST', credentials: 'include', headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ s6_analysis: result, created_at: new Date().toISOString() }),
      });
      const payload = await response.json();
      setHandoff(payload);
      setS1Result(null);
      if (!response.ok) setError(rows(payload.blockers).join(' / ') || payload.error || t('traditionalLivability.s6.errors.handoff'));
    } catch (handoffError) {
      setError(handoffError instanceof Error ? handoffError.message : t('traditionalLivability.s6.errors.handoff'));
    } finally {
      setHandoffLoading(false);
    }
  };

  const executeS1 = async () => {
    if (!handoff?.handoff_id) return;
    setHandoffLoading(true);
    setError('');
    try {
      const response = await fetch(`/api/uwm/traditional-livability/s6/handoffs/${handoff.handoff_id}/execute-s1`, {
        method: 'POST', credentials: 'include', headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' }, body: '{}',
      });
      const payload = await response.json();
      setS1Result(payload);
      if (!response.ok) setError(rows(payload.blockers).join(' / ') || payload.error || t('traditionalLivability.s6.errors.execute'));
    } catch (executionError) {
      setError(executionError instanceof Error ? executionError.message : t('traditionalLivability.s6.errors.execute'));
    } finally {
      setHandoffLoading(false);
    }
  };

  const sendMap = () => {
    const geojson = record(result?.geojson);
    const unresolvedGeojson = unresolvedFeatureCollection(geojson, { planningResource: t('traditionalLivability.s6.map.unresolvedPlanning'), currentFacility: t('traditionalLivability.s6.map.unresolvedCurrent') });
    window.__handleMapUpdate?.({ schema: 'map_update.v1', summary: { title: t('traditionalLivability.s6.map.title') }, layers: [
      [t('traditionalLivability.s6.map.proposed'), geojson.proposed_geometry],
      [t('traditionalLivability.s6.map.buffer'), geojson.screening_buffer],
      [t('traditionalLivability.s6.map.planningHits'), geojson.planning_resource_hits],
      [t('traditionalLivability.s6.map.currentHits'), geojson.current_facility_hits],
      [t('traditionalLivability.s6.map.unresolved'), unresolvedGeojson],
    ].filter(([, data]) => data).map(([name, geojsonData]) => ({ name, type: 'geojson', geojsonData })) });
  };

  const requiredReady = Boolean(areaId && facilityName.trim() && rawType.trim() && useDescription.trim() && (inputMode === 'point' ? longitude !== null && latitude !== null : parcelId));
  const statusLabel = result?.status === 'potential_conflict_review_required'
    ? t('traditionalLivability.s6.status.potentialConflict')
    : t(`statusLabels.${text(result?.status)}`, { defaultValue: text(result?.status) });

  return <div className="traditional-panel">
    <div className="traditional-panel-title"><Search size={15} /><strong>{t('traditionalLivability.s6.title')}</strong></div>
    <p>{t('traditionalLivability.s6.description')}</p>
    <button className="secondary-button" onClick={() => setReloadToken(token => token + 1)}><RefreshCw size={14} />{t('traditionalLivability.s6.actions.refresh')}</button>
    {!resourcesSettled && <p>{t('traditionalLivability.s6.loading.resources')}</p>}
    {resourcesError && <div className="traditional-message error"><AlertTriangle size={15} />{t('traditionalLivability.s6.messages.resourcesUnavailable')}：{resourcesError}</div>}
    {!authoritySettled && <p>{t('traditionalLivability.s6.loading.authority')}</p>}
    {(!authorityReady || authorityError) && <div className="traditional-message error"><AlertTriangle size={15} />{t('traditionalLivability.s6.messages.authorityUnavailable')}：{authorityError || t('traditionalLivability.s6.messages.limitedConclusion')}</div>}
    {error && <div className="traditional-message error"><AlertTriangle size={15} />{error}</div>}
    <div className="traditional-two-col">
      <div className="traditional-panel">
        <h4>{t('traditionalLivability.s6.sections.inputReview')}</h4>
        <label>{t('traditionalLivability.s6.controls.planningArea')}<select value={areaId} onChange={event => { setAreaId(event.target.value); setParcelId(''); invalidateDownstream(); }}><option value="">{t('traditionalLivability.s6.controls.select')}</option>{rows(resources.planning_areas).map(area => <option key={area.planning_area_id} value={area.planning_area_id}>{area.planning_area_name || area.planning_area_id}</option>)}</select></label>
        <div><button className={inputMode === 'point' ? 'primary-button' : 'secondary-button'} onClick={() => { setInputMode('point'); invalidateDownstream(); }}>{t('traditionalLivability.s6.controls.mapPoint')}</button> <button className={inputMode === 'parcel' ? 'primary-button' : 'secondary-button'} onClick={() => { setInputMode('parcel'); invalidateDownstream(); }}>{t('traditionalLivability.s6.controls.planningParcel')}</button></div>
        {inputMode === 'point' ? <div><button className="secondary-button" onClick={requestPoint} disabled={selectingPoint}><MapPin size={14} />{selectingPoint ? t('traditionalLivability.s6.controls.waitingMap') : t('traditionalLivability.s6.controls.selectPoint')}</button><p>{t('traditionalLivability.s6.controls.coordinates')}：{longitude ?? '-'}, {latitude ?? '-'}</p><p>{selectionMessage}</p></div> : <label>{t('traditionalLivability.s6.controls.planningParcel')}<select value={parcelId} onChange={event => { setParcelId(event.target.value); invalidateDownstream(); }}><option value="">{t('traditionalLivability.s6.controls.select')}</option>{selectableParcels.map(parcel => <option key={parcel.resource_id} value={parcel.resource_id}>{parcel.raw_land_use_name || parcel.resource_id}</option>)}</select></label>}
        <label>{t('traditionalLivability.s6.controls.facilityName')}<input value={facilityName} onChange={event => { setFacilityName(event.target.value); invalidateDownstream(); }} required /></label>
        <label>{t('traditionalLivability.s6.controls.rawType')}<input value={rawType} onChange={event => { setRawType(event.target.value); invalidateDownstream(); }} required /></label>
        <label>{t('traditionalLivability.s6.controls.description')}<textarea value={useDescription} onChange={event => { setUseDescription(event.target.value); invalidateDownstream(); }} required /></label>
        <button className="primary-button" onClick={analyze} disabled={!requiredReady || loading}>{loading ? t('traditionalLivability.s6.actions.analyzing') : t('traditionalLivability.s6.actions.analyze')}</button>
        <h4>{t('traditionalLivability.s6.sections.semanticConfirmation')}</h4>
        {candidates.length === 0 ? <p>{t('traditionalLivability.s6.messages.noCandidates')}</p> : candidates.map(candidate => <label key={candidate.standard_class_id}><input type="radio" name="s6-candidate" checked={selectedCandidateId === candidate.standard_class_id} onChange={() => { setSelectedCandidateId(candidate.standard_class_id); invalidateDownstream(); }} /> {candidate.standard_class_label || candidate.standard_class_id} · {candidate.match_method}</label>)}
        {semantic.resolution_status === 'unresolved' && dictionaryClasses.length > 0 && <label>{t('traditionalLivability.s6.controls.manualClass')}<select value={selectedCandidateId} onChange={event => { setSelectedCandidateId(event.target.value); invalidateDownstream(); }}><option value="">{t('traditionalLivability.s6.controls.select')}</option>{dictionaryClasses.map(classRecord => <option key={classRecord.class_id} value={classRecord.class_id}>{classRecord.label || classRecord.class_id}</option>)}</select></label>}
        {selectedCandidateId && <label>{t('traditionalLivability.s6.controls.confirmationReason')}<textarea value={confirmationReason} onChange={event => { setConfirmationReason(event.target.value); invalidateDownstream(); }} placeholder={t('traditionalLivability.s6.controls.reasonPlaceholder')} /></label>}
      </div>
      <div className="traditional-panel">
        <h4>{t('traditionalLivability.s6.sections.evidenceBoundary')}</h4>
        <div className="traditional-boundary-grid"><div><span>{t('traditionalLivability.s6.results.status')}</span><strong>{statusLabel}</strong></div><div><span>max_claim_level</span><strong>{text(result?.max_claim_level)}</strong></div><div><span>{t('traditionalLivability.s6.results.inventory')}</span><strong>{rows(result?.completeness_warnings).some(item => String(item).includes('sampled')) ? t('traditionalLivability.s6.results.sampled') : t('traditionalLivability.s6.results.catalog')}</strong></div><div><span>{t('traditionalLivability.s6.results.ruleIds')}</span><strong>{rows(result?.applied_rule_ids).join(' / ') || '-'}</strong></div></div>
        <ResultTable title={t('traditionalLivability.s6.results.planningHits')} data={rows(result?.planning_resource_hits)} idKey="resource_id" />
        <ResultTable title={t('traditionalLivability.s6.results.currentHits')} data={rows(result?.current_facility_hits)} idKey="facility_id" />
        <ResultTable title={t('traditionalLivability.s6.results.unresolved')} data={[...rows(unresolved.planning_resources), ...rows(unresolved.current_facilities), ...rows(unresolved.association_records)]} idKey="resource_id" />
        <h4>{t('traditionalLivability.s6.results.productionBlockers')}</h4><p>{rows(result?.production_blockers).join(' / ') || '-'}</p>
        <h4>{t('traditionalLivability.s6.results.evidenceCompleteness')}</h4><p>{rows(result?.completeness_warnings).join(' / ') || text(result?.claim_boundary)}</p>
        <button className="secondary-button" onClick={sendMap} disabled={!result?.geojson}><CheckCircle2 size={14} />{t('traditionalLivability.s6.actions.sendMap')}</button>
        <h4>{t('traditionalLivability.s6.sections.s1Readiness')}</h4>
        <p>{t('traditionalLivability.s6.results.staticAnalysis')}</p>
        <p>{t('traditionalLivability.s6.results.profileStatus')}：{text(profiles.status)}；{t('traditionalLivability.s6.results.applicableProfiles')}：{rows(handoff?.applicable_metric_profiles).map(row => row.profile_id).join(' / ') || '-'}</p>
        <p>{t('traditionalLivability.s6.results.blockers')}：{rows(handoff?.validation_blockers).join(' / ') || rows(profiles.blockers).join(' / ') || '-'}</p>
        <button className="secondary-button" onClick={createHandoff} disabled={!result?.s1_handoff?.ready || handoffLoading}>{t('traditionalLivability.s6.actions.createHandoff')}</button>
        <button className="primary-button" onClick={executeS1} disabled={!handoff?.ready_for_s1 || handoffLoading}>{t('traditionalLivability.s6.actions.executeS1')}</button>
        {s1Result && <div>
          <h4>{t('traditionalLivability.s6.results.snapshot')}</h4>
          <p>FP：{text(s1Result.baseline?.fp?.observed_value)} → {text(s1Result.proposal_snapshot?.fp?.observed_value)}</p>
          <p>FPP：{text(s1Result.baseline?.fpp?.observed_value)} → {text(s1Result.proposal_snapshot?.fpp?.observed_value)}</p>
          <p>{t('traditionalLivability.s6.results.synthesisStatus')}：{text(s1Result.baseline?.synthesis?.status)} → {text(s1Result.proposal_snapshot?.synthesis?.status)}</p>
          <p>{t('traditionalLivability.s6.results.unresolvedDimensions')}：{[...rows(s1Result.baseline?.fp?.blockers), ...rows(s1Result.baseline?.fpp?.blockers), ...rows(s1Result.proposal_snapshot?.fp?.blockers), ...rows(s1Result.proposal_snapshot?.fpp?.blockers)].join(' / ') || '-'}</p>
        </div>}
      </div>
    </div>
  </div>;
}

function ResultTable({ title, data, idKey }: { title: string; data: Row[]; idKey: string }) {
  const { t } = useTranslation();
  return <><h4>{title}</h4><div className="traditional-table-wrap"><table className="traditional-table"><thead><tr><th>{t('traditionalLivability.s6.table.object')}</th><th>{t('traditionalLivability.s6.table.distance')}</th><th>{t('traditionalLivability.s6.table.statusClass')}</th><th>{t('traditionalLivability.s6.table.evidence')}</th></tr></thead><tbody>{data.length ? data.map((row, index) => <tr key={row[idKey] || row.facility_id || index}><td>{text(row[idKey] || row.facility_id)}</td><td>{text(row.nearest_distance_m)}</td><td>{text(row.planning_status || row.mapping_status || row.compatibility_object_class_id)}</td><td>{text(row.source_record_id || row.interpretation_evidence || row.source_dataset_id)}</td></tr>) : <tr><td colSpan={4}>-</td></tr>}</tbody></table></div></>;
}
