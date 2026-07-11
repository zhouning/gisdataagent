import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Map, Plus, RefreshCw, Trash2 } from 'lucide-react';

type Row = Record<string, any>;
type UseRow = {
  clientKey: string;
  useId: string;
  useName: string;
  rawUseType: string;
  useDescription: string;
  gfa: string;
  confirmedClassId: string;
};

const rows = (value: unknown): Row[] => Array.isArray(value) ? value : [];
const record = (value: unknown): Row => value && typeof value === 'object' && !Array.isArray(value) ? value as Row : {};
const text = (value: unknown): string => value === null || value === undefined || value === '' ? '-' : String(value);
const makeClientKey = (): string => crypto.randomUUID();
const newUse = (): UseRow => ({ clientKey: makeClientKey(), useId: '', useName: '', rawUseType: '', useDescription: '', gfa: '', confirmedClassId: '' });

const statusLabels: Record<string, string> = {
  demand_supported: '需求有权威证据支持',
  not_assessed: '需求未评估',
  provisionally_supported: '初步支持',
  preliminary_alignment_evidence: '初步对齐分析，需人工复核',
  human_review_required: '初步对齐分析，需人工复核',
  unresolved_review_required: '语义未解析，需人工复核',
  mixed_evidence_review_required: '证据混合，需人工复核',
};

function featureLayer(name: string, geojsonData: unknown): Row | null {
  if (!geojsonData || typeof geojsonData !== 'object') return null;
  return { name, type: 'geojson', geojsonData };
}

export default function TraditionalLivabilityS4Panel() {
  const [resources, setResources] = useState<Row>({});
  const [resourcesError, setResourcesError] = useState('');
  const [resourcesSettled, setResourcesSettled] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const [projectName, setProjectName] = useState('');
  const [projectDescription, setProjectDescription] = useState('');
  const [parcelId, setParcelId] = useState('');
  const [uses, setUses] = useState<UseRow[]>([newUse()]);
  const [result, setResult] = useState<Row | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let stale = false;
    setResourcesSettled(false);
    setResourcesError('');
    fetch('/api/uwm/traditional-livability/s4/resources', { credentials: 'include' })
      .then(async response => ({ response, payload: await response.json() }))
      .then(({ response, payload }) => {
        if (stale) return;
        if (!response.ok) throw new Error(payload.detail || payload.error || 'S4 资源加载失败');
        setResources(payload);
        const planningParcels = rows(payload.planning_parcels);
        setParcelId(current => current || String(planningParcels[0]?.planning_parcel_id || ''));
      })
      .catch(loadError => { if (!stale) setResourcesError(loadError instanceof Error ? loadError.message : 'S4 资源加载失败'); })
      .finally(() => { if (!stale) setResourcesSettled(true); });
    return () => { stale = true; };
  }, [reloadToken]);

  const planningParcels = rows(resources.planning_parcels);
  const facilityClasses = rows(resources.facility_classes);
  const selectedParcel = planningParcels.find(parcel => parcel.planning_parcel_id === parcelId);
  const validationError = useMemo(() => {
    if (!projectName.trim()) return '请输入项目名称';
    if (!selectedParcel) return '请选择规划地块';
    if (uses.length === 0) return '至少保留一个业态';
    for (const use of uses) {
      const gfa = Number(use.gfa);
      if (!use.useName.trim() || !use.rawUseType.trim() || !use.useDescription.trim()) return '请完整填写每个业态';
      if (!(Number.isFinite(gfa) && gfa > 0)) return 'GFA 必须为有限正数';
    }
    return '';
  }, [projectName, selectedParcel, uses]);

  const updateUse = (clientKey: string, patch: Partial<UseRow>) => {
    setUses(current => current.map(use => use.clientKey === clientKey ? { ...use, ...patch } : use));
  };

  const analyze = async () => {
    if (validationError || !selectedParcel) { setError(validationError); return; }
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/uwm/traditional-livability/s4/analyze', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          analysis_area_id: selectedParcel.analysis_area_id,
          planning_parcel_id: selectedParcel.planning_parcel_id,
          project_name: projectName.trim(),
          project_description: projectDescription.trim(),
          uses: uses.map((use, index) => ({
            use_id: use.useId.trim() || `use-${index + 1}`,
            use_name: use.useName.trim(),
            raw_use_type: use.rawUseType.trim(),
            use_description: use.useDescription.trim(),
            gfa_m2: Number(use.gfa),
            confirmed_standard_class_id: use.confirmedClassId || undefined,
            human_confirmation: null,
          })),
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || payload.error || 'S4 分析失败');
      setResult(payload);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'S4 分析失败');
    } finally {
      setLoading(false);
    }
  };

  const sendMap = () => {
    const geojson = record(result?.geojson);
    const layers = [
      featureLayer('S4 目标项目地块', geojson.proposed_geometry),
      featureLayer('S4 150 米空间初筛', geojson.screening_buffer),
      featureLayer('S4 地块及邻近规划资源', geojson.planning_resource_hits),
      featureLayer('S4 邻近现状设施', geojson.current_facility_hits),
      featureLayer('S4 语义未解析规划资源', geojson.unresolved_planning_resources),
      featureLayer('S4 语义未解析现状设施', geojson.unresolved_current_facilities),
    ].filter(Boolean);
    window.__handleMapUpdate?.({ schema: 'map_update.v1', summary: { title: 'S4 项目证据图层' }, layers });
  };

  const summary = record(result?.project_summary);
  const claimBoundary = record(result?.claim_boundary);
  const readiness = record(resources.readiness);

  return <div className="traditional-panel">
    <div className="traditional-panel-title"><Map size={15} /><strong>S4 项目宜居性评估</strong></div>
    <p>按项目多业态 GFA 计划汇总语义、地块、S1 与 S6 证据；输出仅为初步对齐分析，需人工复核。</p>
    <button className="secondary-button" onClick={() => setReloadToken(value => value + 1)}><RefreshCw size={14} />刷新 S4 资源</button>
    {resourcesSettled && resourcesError && <div className="traditional-message error"><AlertTriangle size={15} />{resourcesError}</div>}
    {error && <div className="traditional-message error"><AlertTriangle size={15} />{error}</div>}
    <div className="traditional-two-col">
      <div className="traditional-panel">
        <label>项目名称<input value={projectName} onChange={event => setProjectName(event.target.value)} /></label>
        <label>项目说明<textarea value={projectDescription} onChange={event => setProjectDescription(event.target.value)} /></label>
        <label>规划地块<select value={parcelId} onChange={event => setParcelId(event.target.value)}><option value="">请选择</option>{planningParcels.map(parcel => <option key={parcel.planning_parcel_id} value={parcel.planning_parcel_id}>{parcel.raw_land_use_name || parcel.planning_parcel_id} · {parcel.analysis_area_id}</option>)}</select></label>
        <h4>多业态计划</h4>
        {uses.map((use, index) => <div className="traditional-panel" key={use.clientKey}>
          <strong>业态 {index + 1}</strong>
          <label>业态名称<input value={use.useName} onChange={event => updateUse(use.clientKey, { useName: event.target.value })} /></label>
          <label>原始业态类型<input value={use.rawUseType} onChange={event => updateUse(use.clientKey, { rawUseType: event.target.value })} /></label>
          <label>用途说明<textarea value={use.useDescription} onChange={event => updateUse(use.clientKey, { useDescription: event.target.value })} /></label>
          <label>GFA (m²)<input type="number" min="0" step="any" value={use.gfa} onChange={event => updateUse(use.clientKey, { gfa: event.target.value })} /></label>
          <label>语义类别（可选）<select value={use.confirmedClassId} onChange={event => updateUse(use.clientKey, { confirmedClassId: event.target.value })}><option value="">由服务端解析</option>{facilityClasses.map(item => <option key={item.class_id} value={item.class_id}>{item.label || item.class_id}</option>)}</select></label>
          <button className="secondary-button" onClick={() => setUses(current => current.filter(item => item.clientKey !== use.clientKey))} disabled={uses.length === 1}><Trash2 size={14} />删除业态</button>
        </div>)}
        <button className="secondary-button" onClick={() => setUses(current => [...current, newUse()])}><Plus size={14} />新增业态</button>
        <button className="primary-button" onClick={analyze} disabled={loading || Boolean(validationError)}>{loading ? '分析中…' : '执行 S4 分析'}</button>
        {validationError && <p>{validationError}；客户端仅作有限正数等快速校验，服务端验证为准。</p>}
      </div>
      <div className="traditional-panel">
        <h4>初步状态</h4>
        <div className="traditional-boundary-grid"><div><span>状态</span><strong>{statusLabels[String(result?.status)] || text(result?.status)}</strong></div><div><span>max_claim</span><strong>{text(claimBoundary.max_claim)}</strong></div><div><span>总 GFA</span><strong>{text(summary.total_gfa_m2)} m²</strong></div><div><span>正式对齐开关</span><strong>{summary.formal_alignment_enabled ? '权威条件已满足，仍需复核' : '未启用'}</strong></div></div>
        <h4>GFA 证据构成</h4>
        <div className="traditional-table-wrap"><table className="traditional-table"><thead><tr><th>状态</th><th>GFA</th><th>占比</th></tr></thead><tbody>{rows(summary.gfa_by_status).map(item => <tr key={item.status}><td>{statusLabels[item.status] || item.status}</td><td>{text(item.gfa_m2)}</td><td>{Number.isFinite(Number(item.gfa_share)) ? `${Math.round(Number(item.gfa_share) * 100)}%` : '-'}</td></tr>)}</tbody></table></div>
        {rows(result?.use_assessments).map(use => <div className="traditional-panel" key={use.use_id}>
          <h4>{use.use_name} · {text(use.gfa_m2)} m²</h4>
          <div className="traditional-boundary-grid"><div><span>语义证据</span><strong>{text(record(use.semantic_evidence).resolution_status || use.confirmed_standard_class_id)}</strong></div><div><span>地块直接关系</span><strong>{text(record(use.parcel_direct_evidence).status)}</strong></div><div><span>S1 需求证据</span><strong>{statusLabels[String(record(use.demand_evidence).status)] || text(record(use.demand_evidence).status)}</strong></div><div><span>S6 空间证据</span><strong>{text(use.s6_status)}</strong></div><div><span>150 米空间初筛</span><strong>{text(record(use.neighborhood_evidence).status || use.status)}</strong></div><div><span>业态阻塞项</span><strong>{rows(use.blockers).join(' / ') || '-'}</strong></div></div>
        </div>)}
        <h4>project_blockers</h4><p>{rows(result?.project_blockers).join(' / ') || '-'}</p>
        <h4>资源就绪性</h4><p>{Object.entries(readiness).map(([key, value]) => `${key}:${record(value).ready ?? record(value).complete ?? '-'}`).join(' / ') || '-'}</p>
        <button className="secondary-button" onClick={sendMap} disabled={!result?.geojson}><Map size={14} />发送引擎 GeoJSON 图层</button>
      </div>
    </div>
  </div>;
}
