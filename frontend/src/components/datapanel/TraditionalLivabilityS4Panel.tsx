import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Map, Plus, RefreshCw, Trash2 } from 'lucide-react';

type Row = Record<string, any>;
type UseRow = { clientKey: string; useId: string; useName: string; rawUseType: string; useDescription: string; gfa: string };
type ConfirmationDraft = { selectedCandidateId: string; reviewerReason: string; humanSelected: boolean };

const rows = (value: unknown): Row[] => Array.isArray(value) ? value : [];
const record = (value: unknown): Row => value && typeof value === 'object' && !Array.isArray(value) ? value as Row : {};
const text = (value: unknown): string => value === null || value === undefined || value === '' ? '-' : String(value);
const makeId = (): string => crypto.randomUUID();
const newUse = (): UseRow => ({ clientKey: makeId(), useId: `use-${makeId()}`, useName: '', rawUseType: '', useDescription: '', gfa: '' });
const evidenceLabels = { not_assessed: '需求未评估', preliminary: '初步对齐分析，需人工复核' };
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
  return <details><summary>{title}（{data.length}）</summary><div className="traditional-table-wrap"><table className="traditional-table"><thead><tr><th>对象</th><th>状态/类别</th><th>距离</th><th>规则/来源</th></tr></thead><tbody>{data.length ? data.map((item, index) => <tr key={item.resource_id || item.facility_id || item.rule_id || index}><td>{text(item.resource_id || item.facility_id || item.rule_id || item.standard_class_id)}</td><td>{text(item.status || item.planning_status || item.mapping_status || item.relationship || item.standard_class_label)}</td><td>{text(item.nearest_distance_m)}</td><td>{text(item.source_record_id || item.source_dataset_id || item.interpretation_evidence || item.reason)}</td></tr>) : <tr><td colSpan={4}>-</td></tr>}</tbody></table></div></details>;
}

export default function TraditionalLivabilityS4Panel() {
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
    fetch('/api/uwm/traditional-livability/s4/resources', { credentials: 'include' })
      .then(async response => ({ response, payload: await response.json() }))
      .then(({ response, payload }) => {
        if (stale) return;
        if (!response.ok) throw Object.assign(new Error('S4 资源加载失败'), { payload });
        setResources(payload); setResourcesError([]);
        const firstArea = String(rows(payload.planning_parcels)[0]?.analysis_area_id || '');
        setAnalysisAreaId(current => current || firstArea);
      })
      .catch(loadError => { if (!stale) setResourcesError(errorMessages(record(loadError?.payload), loadError instanceof Error ? loadError.message : 'S4 资源加载失败')); });
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
    if (!projectName.trim()) return '请输入项目名称';
    if (!analysisAreaId) return '请选择规划区域';
    if (!selectedParcel) return '请选择规划地块';
    for (const use of uses) {
      const gfa = Number(use.gfa);
      if (!use.useName.trim() || !use.rawUseType.trim() || !use.useDescription.trim()) return '请完整填写每个业态';
      if (!(Number.isFinite(gfa) && gfa > 0)) return 'GFA 必须为有限正数';
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
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
        body: JSON.stringify({ analysis_area_id: analysisAreaId, planning_parcel_id: parcelId, project_name: projectName.trim(), project_description: projectDescription.trim(), uses: payloadUses }),
      });
      const payload = await response.json();
      if (controller.signal.aborted) return;
      if (!response.ok) { setErrors(errorMessages(payload, 'S4 分析失败')); return; }
      setResult(payload);
    } catch (requestError) {
      if (controller.signal.aborted) return;
      setErrors([requestError instanceof Error ? requestError.message : 'S4 分析失败']);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };

  const sendMap = () => {
    const geojson = record(result?.geojson);
    const layer = (name: string, geojsonData: unknown) => geojsonData && typeof geojsonData === 'object' ? { name, type: 'geojson', geojsonData } : null;
    window.__handleMapUpdate?.({ schema: 'map_update.v1', summary: { title: 'S4 项目证据图层' }, layers: [
      layer('S4 目标项目地块', geojson.proposed_geometry), layer('S4 150 米空间初筛', geojson.screening_buffer),
      layer('S4 地块及邻近规划资源', geojson.planning_resource_hits), layer('S4 邻近现状设施', geojson.current_facility_hits),
      layer('S4 语义未解析规划资源', geojson.unresolved_planning_resources), layer('S4 语义未解析现状设施', geojson.unresolved_current_facilities),
    ].filter(Boolean) });
  };

  const summary = record(result?.project_summary);
  return <div className="traditional-panel">
    <div className="traditional-panel-title"><Map size={15} /><strong>S4 项目宜居性评估</strong></div>
    <p>初次分析不指定任意类别；根据服务端语义候选确认后再提交。结果为{evidenceLabels.preliminary}，S1 缺少权威标准时显示“{evidenceLabels.not_assessed}”。</p>
    <button className="secondary-button" onClick={() => setReloadToken(value => value + 1)}><RefreshCw size={14} />刷新 S4 资源</button>
    {[...resourcesError, ...errors].map((message, index) => <div className="traditional-message error" key={`${message}-${index}`}><AlertTriangle size={15} />{message}</div>)}
    <div className="traditional-two-col"><div className="traditional-panel">
      <label>项目名称<input value={projectName} onChange={event => setProjectName(event.target.value)} /></label>
      <label>项目说明<textarea value={projectDescription} onChange={event => setProjectDescription(event.target.value)} /></label>
      <label>规划区域<select value={analysisAreaId} onChange={event => { setAnalysisAreaId(event.target.value); setParcelId(''); }}><option value="">请选择</option>{analysisAreas.map(area => <option key={area} value={area}>{area}</option>)}</select></label>
      <label>规划地块<select value={parcelId} onChange={event => setParcelId(event.target.value)}><option value="">请选择</option>{filteredParcels.map(parcel => <option key={parcel.planning_parcel_id} value={parcel.planning_parcel_id}>{parcel.raw_land_use_name || parcel.planning_parcel_id}</option>)}</select></label>
      {uses.map((use, index) => <div className="traditional-panel" key={use.clientKey}><strong>业态 {index + 1}</strong>
        <label>业态名称<input value={use.useName} onChange={event => setUses(current => current.map(item => item.clientKey === use.clientKey ? { ...item, useName: event.target.value } : item))} /></label>
        <label>原始业态类型<input value={use.rawUseType} onChange={event => setUses(current => current.map(item => item.clientKey === use.clientKey ? { ...item, rawUseType: event.target.value } : item))} /></label>
        <label>用途说明<textarea value={use.useDescription} onChange={event => setUses(current => current.map(item => item.clientKey === use.clientKey ? { ...item, useDescription: event.target.value } : item))} /></label>
        <label>GFA (m²)<input type="number" value={use.gfa} onChange={event => setUses(current => current.map(item => item.clientKey === use.clientKey ? { ...item, gfa: event.target.value } : item))} /></label>
        <button className="secondary-button" disabled={uses.length === 1} onClick={() => setUses(current => current.filter(item => item.clientKey !== use.clientKey))}><Trash2 size={14} />删除业态</button>
      </div>)}
      <button className="secondary-button" onClick={() => setUses(current => [...current, newUse()])}><Plus size={14} />新增业态</button>
      <button className="primary-button" disabled={loading || Boolean(validationError)} onClick={analyze}>{loading ? '分析中…' : '执行 / 重新提交 S4 分析'}</button>
      {validationError && <p>{validationError}；客户端快速校验，服务端验证为准。</p>}
    </div><div className="traditional-panel">
      <h4>初步状态与 GFA 证据构成</h4><div className="traditional-boundary-grid"><div><span>状态</span><strong>{text(result?.status)}</strong></div><div><span>max_claim</span><strong>{text(record(result?.claim_boundary).max_claim)}</strong></div><div><span>总 GFA</span><strong>{text(summary.total_gfa_m2)}</strong></div><div><span>project_blockers</span><strong>{rows(result?.project_blockers).join(' / ') || '-'}</strong></div></div>
      <EvidenceTable title="GFA 证据构成" data={rows(summary.gfa_by_status)} />
      {rows(result?.use_assessments).map(use => {
        const semantic = record(use.semantic_evidence); const direct = record(use.parcel_direct_evidence); const neighborhood = record(use.neighborhood_evidence); const duplicate = record(use.duplicate_supply_evidence); const draft = confirmationsByUseId[use.use_id] || { selectedCandidateId: '', reviewerReason: '', humanSelected: false };
        const semanticCandidates = rows(semantic.candidates); const candidateChoices = semantic.resolution_status === 'unresolved' && dictionaryReady ? facilityClasses : semanticCandidates;
        return <details key={use.use_id} open><summary>{use.use_name} · {text(use.gfa_m2)} m² · {text(use.status)}</summary>
          <h4>语义证据与人工确认</h4><p>{text(semantic.resolution_status)} · {text(semantic.original_input_digest)}</p>
          {candidateChoices.map(candidate => <label key={candidate.standard_class_id || candidate.class_id}><input type="radio" name={`s4-${use.use_id}`} checked={draft.selectedCandidateId === (candidate.standard_class_id || candidate.class_id)} onChange={() => setConfirmationsByUseId(current => ({ ...current, [use.use_id]: { ...draft, selectedCandidateId: candidate.standard_class_id || candidate.class_id, humanSelected: !candidate.standard_class_id } }))} />{candidate.standard_class_label || candidate.label} · {candidate.match_method || '人工字典选择'}</label>)}
          {draft.selectedCandidateId && <label>审查理由<textarea value={draft.reviewerReason} onChange={event => setConfirmationsByUseId(current => ({ ...current, [use.use_id]: { ...draft, reviewerReason: event.target.value } }))} /></label>}
          <h4>S1 需求证据</h4><pre>{JSON.stringify(record(use.demand_evidence), null, 2)}</pre>
          <h4>重复供给证据</h4><pre>{JSON.stringify(duplicate, null, 2)}</pre>
          <EvidenceTable title="地块直接关系：规划资源" data={rows(record(use.parcel_direct_evidence).planning_resources)} />
          <EvidenceTable title="地块直接关系：现状设施" data={rows(record(use.parcel_direct_evidence).current_facilities)} />
          <EvidenceTable title="150 米空间初筛：规划资源" data={rows(record(use.neighborhood_evidence).planning_resources)} />
          <EvidenceTable title="150 米空间初筛：现状设施" data={rows(record(use.neighborhood_evidence).current_facilities)} />
          <EvidenceTable title="语义未解析规划资源" data={rows(neighborhood.unresolved_planning_resources)} />
          <EvidenceTable title="语义未解析现状设施" data={rows(neighborhood.unresolved_current_facilities)} />
          <EvidenceTable title="已应用规则 IDs" data={[...rows(direct.applied_rules), ...rows(neighborhood.applied_rules), ...rows(duplicate.applied_rules)]} />
          <EvidenceTable title="不适用规则 IDs / non_applicable" data={[...rows(direct.non_applicable_rules), ...rows(neighborhood.non_applicable_rules)]} />
          <p>validation_blockers：{rows(use.blockers).join(' / ') || '-'}</p><p>S6 空间证据：{text(use.s6_status)}</p>
        </details>;
      })}
      <button className="secondary-button" disabled={!result?.geojson} onClick={sendMap}><Map size={14} />发送引擎 GeoJSON 图层</button>
    </div></div>
  </div>;
}
