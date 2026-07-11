import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, MapPin, RefreshCw, Search } from 'lucide-react';

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

function unresolvedFeatureCollection(geojson: Row): Row {
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
      ...taggedFeatures(geojson.unresolved_planning_resources, 'planning_resource', '语义未解析规划资源'),
      ...taggedFeatures(geojson.unresolved_current_facilities, 'current_facility', '语义未解析现状设施'),
    ],
  };
}

declare global {
  interface Window {
    __handleMapUpdate?: (payload: any) => void;
  }
}

export default function TraditionalLivabilityS6Panel() {
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

  useEffect(() => {
    let stale = false;
    setResourcesSettled(false);
    setResourcesError('');
    fetch('/api/uwm/traditional-livability/s6/resources', { credentials: 'include' })
      .then(async response => ({ response, payload: await response.json() }))
      .then(({ response, payload }) => {
        if (stale) return;
        if (!response.ok) throw new Error(payload.detail || payload.error || 'S6 资源加载失败');
        setResources(payload);
        const areas = rows(payload.planning_areas);
        setAreaId(current => current || String(areas[0]?.planning_area_id || ''));
      })
      .catch(loadError => { if (!stale) setResourcesError(loadError instanceof Error ? loadError.message : 'S6 资源加载失败'); })
      .finally(() => { if (!stale) setResourcesSettled(true); });
    return () => { stale = true; };
  }, [reloadToken]);

  useEffect(() => {
    let stale = false;
    setAuthoritySettled(false);
    setAuthorityError('');
    fetch('/api/uwm/traditional-livability/s6/dictionary', { credentials: 'include' })
      .then(async response => ({ response, payload: await response.json() }))
      .then(({ response, payload }) => {
        if (stale) return;
        if (!response.ok) throw new Error(payload.detail || payload.error || 'S6 权威状态加载失败');
        setAuthority(payload);
      })
      .catch(loadError => { if (!stale) setAuthorityError(loadError instanceof Error ? loadError.message : 'S6 权威状态加载失败'); })
      .finally(() => { if (!stale) setAuthoritySettled(true); });
    return () => { stale = true; };
  }, [reloadToken]);
  useEffect(() => {
    const selected = (event: Event) => {
      const detail = (event as CustomEvent<{ longitude: number; latitude: number }>).detail;
      setLongitude(detail.longitude);
      setLatitude(detail.latitude);
      setSelectingPoint(false);
      setSelectionMessage('地图点选完成。');
    };
    const cancelled = (event: Event) => {
      const reason = (event as CustomEvent<{ reason?: string }>).detail?.reason || 'unknown';
      setSelectingPoint(false);
      setSelectionMessage(`地图点选已取消：${reason}`);
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
    setSelectionMessage('请在地图上选择下一个点。');
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
      const response = await fetch('/api/uwm/traditional-livability/s6/analyze', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const payload = await response.json();
      setResult(payload);
      if (!response.ok) setError(rows(payload.validation_blockers).join(' / ') || payload.detail || 'S6 分析失败');
      setSelectedCandidateId('');
      setConfirmationReason('');
    } catch (analysisError) {
      setError(analysisError instanceof Error ? analysisError.message : 'S6 分析失败');
    } finally {
      setLoading(false);
    }
  };

  const sendMap = () => {
    const geojson = record(result?.geojson);
    const unresolvedGeojson = unresolvedFeatureCollection(geojson);
    window.__handleMapUpdate?.({ schema: 'map_update.v1', summary: { title: 'S6 超范围设施评估' }, layers: [
      ['拟建设施位置或目标地块', geojson.proposed_geometry],
      ['150 米空间初筛范围', geojson.screening_buffer],
      ['命中规划资源地块', geojson.planning_resource_hits],
      ['命中现状设施', geojson.current_facility_hits],
      ['语义未解析设施', unresolvedGeojson],
    ].filter(([, data]) => data).map(([name, geojsonData]) => ({ name, type: 'geojson', geojsonData })) });
  };

  const requiredReady = Boolean(areaId && facilityName.trim() && rawType.trim() && useDescription.trim() && (inputMode === 'point' ? longitude !== null && latitude !== null : parcelId));
  const statusLabel = result?.status === 'potential_conflict_review_required' ? '潜在冲突、需人工复核' : text(result?.status);

  return <div className="traditional-panel">
    <div className="traditional-panel-title"><Search size={15} /><strong>S6 超范围设施评估</strong></div>
    <p>仅执行 150 米投影平面空间初筛；语义候选必须由人员显式确认，空间接近本身不构成许可或监管结论。</p>
    <button className="secondary-button" onClick={() => setReloadToken(token => token + 1)}><RefreshCw size={14} />刷新资源与权威状态</button>
    {!resourcesSettled && <p>规划资源加载中…</p>}
    {resourcesError && <div className="traditional-message error"><AlertTriangle size={15} />规划资源不可用：{resourcesError}</div>}
    {!authoritySettled && <p>权威状态加载中…</p>}
    {(!authorityReady || authorityError) && <div className="traditional-message error"><AlertTriangle size={15} />权威字典或规则不可用：{authorityError || '空间初筛仍可执行，分类与兼容性结论受限。'}</div>}
    {error && <div className="traditional-message error"><AlertTriangle size={15} />{error}</div>}
    <div className="traditional-two-col">
      <div className="traditional-panel">
        <h4>输入与语义复核</h4>
        <label>规划范围<select value={areaId} onChange={event => { setAreaId(event.target.value); setParcelId(''); }}><option value="">请选择</option>{rows(resources.planning_areas).map(area => <option key={area.planning_area_id} value={area.planning_area_id}>{area.planning_area_name || area.planning_area_id}</option>)}</select></label>
        <div><button className={inputMode === 'point' ? 'primary-button' : 'secondary-button'} onClick={() => setInputMode('point')}>地图点选</button> <button className={inputMode === 'parcel' ? 'primary-button' : 'secondary-button'} onClick={() => setInputMode('parcel')}>规划地块</button></div>
        {inputMode === 'point' ? <div><button className="secondary-button" onClick={requestPoint} disabled={selectingPoint}><MapPin size={14} />{selectingPoint ? '等待地图点击' : '选择下一个地图点'}</button><p>坐标：{longitude ?? '-'}, {latitude ?? '-'}</p><p>{selectionMessage}</p></div> : <label>规划地块<select value={parcelId} onChange={event => setParcelId(event.target.value)}><option value="">请选择</option>{selectableParcels.map(parcel => <option key={parcel.resource_id} value={parcel.resource_id}>{parcel.raw_land_use_name || parcel.resource_id}</option>)}</select></label>}
        <label>设施名称<input value={facilityName} onChange={event => setFacilityName(event.target.value)} required /></label>
        <label>原始类型<input value={rawType} onChange={event => setRawType(event.target.value)} required /></label>
        <label>用途说明<textarea value={useDescription} onChange={event => setUseDescription(event.target.value)} required /></label>
        <button className="primary-button" onClick={analyze} disabled={!requiredReady || loading}>{loading ? '分析中…' : 'POST analyze'}</button>
        <h4>语义候选与人工确认</h4>
        {candidates.length === 0 ? <p>先执行分析以加载语义候选；不会静默自动确认。</p> : candidates.map(candidate => <label key={candidate.standard_class_id}><input type="radio" name="s6-candidate" checked={selectedCandidateId === candidate.standard_class_id} onChange={() => setSelectedCandidateId(candidate.standard_class_id)} /> {candidate.standard_class_label || candidate.standard_class_id} · {candidate.match_method}</label>)}
        {semantic.resolution_status === 'unresolved' && dictionaryClasses.length > 0 && <label>人工选择字典类别<select value={selectedCandidateId} onChange={event => setSelectedCandidateId(event.target.value)}><option value="">请选择</option>{dictionaryClasses.map(classRecord => <option key={classRecord.class_id} value={classRecord.class_id}>{classRecord.label || classRecord.class_id}</option>)}</select></label>}
        {selectedCandidateId && <label>人工确认理由<textarea value={confirmationReason} onChange={event => setConfirmationReason(event.target.value)} placeholder="说明本次请求的确认依据" /></label>}
      </div>
      <div className="traditional-panel">
        <h4>证据边界结果</h4>
        <div className="traditional-boundary-grid"><div><span>状态</span><strong>{statusLabel}</strong></div><div><span>max_claim_level</span><strong>{text(result?.max_claim_level)}</strong></div><div><span>采样库存</span><strong>{rows(result?.completeness_warnings).some(item => String(item).includes('sampled')) ? '不完整，仅支持已加载快照命中' : '按资源清单展示'}</strong></div><div><span>规则 ID</span><strong>{rows(result?.applied_rule_ids).join(' / ') || '-'}</strong></div></div>
        <ResultTable title="规划资源命中" data={rows(result?.planning_resource_hits)} idKey="resource_id" />
        <ResultTable title="现状设施命中" data={rows(result?.current_facility_hits)} idKey="facility_id" />
        <ResultTable title="语义未解析对象" data={[...rows(unresolved.planning_resources), ...rows(unresolved.current_facilities), ...rows(unresolved.association_records)]} idKey="resource_id" />
        <h4>production_blockers</h4><p>{rows(result?.production_blockers).join(' / ') || '-'}</p>
        <h4>来源证据与完整性</h4><p>{rows(result?.completeness_warnings).join(' / ') || text(result?.claim_boundary)}</p>
        <button className="secondary-button" onClick={sendMap} disabled={!result?.geojson}><CheckCircle2 size={14} />发送引擎 GeoJSON 到地图</button>
      </div>
    </div>
  </div>;
}

function ResultTable({ title, data, idKey }: { title: string; data: Row[]; idKey: string }) {
  return <><h4>{title}</h4><div className="traditional-table-wrap"><table className="traditional-table"><thead><tr><th>对象</th><th>距离(m)</th><th>状态/类别</th><th>来源证据</th></tr></thead><tbody>{data.length ? data.map((row, index) => <tr key={row[idKey] || row.facility_id || index}><td>{text(row[idKey] || row.facility_id)}</td><td>{text(row.nearest_distance_m)}</td><td>{text(row.planning_status || row.mapping_status || row.compatibility_object_class_id)}</td><td>{text(row.source_record_id || row.interpretation_evidence || row.source_dataset_id)}</td></tr>) : <tr><td colSpan={4}>-</td></tr>}</tbody></table></div></>;
}
