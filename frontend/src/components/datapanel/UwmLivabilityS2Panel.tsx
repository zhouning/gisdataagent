import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, GitCompare, Map, Play, RefreshCw, ShieldCheck } from 'lucide-react';

type RecordValue = Record<string, any>;

declare global { interface Window { __handleMapUpdate?: (payload: any) => void; } }

const record = (value: unknown): RecordValue => value && typeof value === 'object' && !Array.isArray(value) ? value as RecordValue : {};
const rows = <T = RecordValue,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];
const label = (value: unknown) => String(value ?? '-');

export default function UwmLivabilityS2Panel() {
  const [catalog, setCatalog] = useState<RecordValue>({});
  const [parcels, setParcels] = useState<RecordValue[]>([]);
  const [parcelId, setParcelId] = useState('');
  const [targetClass, setTargetClass] = useState('');
  const [alternativeClass, setAlternativeClass] = useState('');
  const [rationale, setRationale] = useState('比较用途变更后的直接状态、邻域传播与无行动基线。');
  const [confirmed, setConfirmed] = useState(false);
  const [validation, setValidation] = useState<RecordValue | null>(null);
  const [run, setRun] = useState<RecordValue | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true); setError('');
    try {
      const [catalogResponse, parcelResponse] = await Promise.all([
        fetch('/api/uwm/livability/s2/catalog', { credentials: 'include' }),
        fetch('/api/uwm/livability/s2/parcels', { credentials: 'include' }),
      ]);
      const catalogPayload = await catalogResponse.json();
      const parcelPayload = await parcelResponse.json();
      if (!catalogResponse.ok || !parcelResponse.ok) throw new Error(catalogPayload.error || parcelPayload.error || 'S2 快照加载失败');
      setCatalog(catalogPayload); setParcels(rows(parcelPayload.features));
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'S2 快照加载失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const selected = useMemo(() => parcels.find(parcel => String(parcel.id) === parcelId), [parcels, parcelId]);
  const properties = record(selected?.properties);
  const villages = useMemo(() => Array.from(new Set(parcels.map(parcel => label(record(parcel.properties).planning_area_id)))), [parcels]);
  const actionBody = () => ({
    parcel_id: parcelId,
    from_land_use_class: properties.current_land_use_class,
    to_land_use_class: targetClass,
    snapshot_digest: catalog.snapshot_digest,
    rationale,
    requested_at: new Date().toISOString(),
    alternative_land_use_class: alternativeClass || undefined,
  });

  const validate = async () => {
    setError(''); setValidation(null);
    if (!parcelId || !targetClass || !rationale.trim()) { setError('请选择真实地块和目标用途，并填写行动理由。'); return; }
    const response = await fetch('/api/uwm/livability/s2/validate-action', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(actionBody()) });
    const payload = await response.json(); setValidation(payload);
    if (!response.ok) setError(payload.error || rows(payload.validation?.errors).join(' / ') || '动作验证失败');
  };

  const rollout = async () => {
    if (!confirmed) { setError('请先完成人工确认。'); return; }
    setLoading(true); setError('');
    try {
      const response = await fetch('/api/uwm/livability/s2/rollout', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(actionBody()) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'S2 推演失败');
      setRun(payload); pushMap(payload);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'S2 推演失败'); }
    finally { setLoading(false); }
  };

  const pushMap = (payload = run) => {
    if (!selected || !payload) return;
    const rolloutPayload = record(payload.rollout);
    const messages = rows(record(record(rolloutPayload.intervention).t2).messages);
    const layer = (name: string, geojsonData: unknown) => ({ name, type: 'geojson', geojsonData });
    window.__handleMapUpdate?.({ schema: 'map_update.v1', summary: { title: 'S2 用地性质变更推演证据图层' }, layers: [
      layer('S2 目标真实地块', { type: 'FeatureCollection', features: [selected] }),
    ], metadata: { evidence_only: true, proxy_distance_bands_m: [50, 150, 300], affected_node_ids: messages.map(message => message.target_node_id) } });
  };

  const rolloutPayload = record(run?.rollout);
  const intervention = record(rolloutPayload.intervention);
  const t1 = record(intervention.t1);
  const t2 = record(intervention.t2);
  const transition = record(record(validation?.validation).transition);

  return <section className="uwm-livability-panel">
    <div className="uwm-livability-panel-title"><GitCompare size={16} /><strong>S2 用地性质变更推演</strong><button className="secondary-button" onClick={load}><RefreshCw size={14} />刷新快照</button></div>
    <p>地块中心跨尺度世界模型：比较 no-change 基线与行动条件化轨迹。50 米、150 米、300 米仅为投影距离代理带。</p>
    {error && <div className="traditional-message error"><AlertTriangle size={15} />{error}</div>}
    <div className="traditional-three-col">
      <div className="traditional-panel">
        <h4>行动配置与人工确认</h4>
        <label>村庄<select disabled><option>{villages.join(' / ') || '加载中'}</option></select></label>
        <label>真实地块<select value={parcelId} onChange={event => { setParcelId(event.target.value); setValidation(null); setRun(null); setConfirmed(false); }}><option value="">请选择</option>{parcels.map(parcel => <option value={parcel.id} key={parcel.id}>{label(record(parcel.properties).planning_area_id)} · {label(record(parcel.properties).source_land_use_name)} · {parcel.id}</option>)}</select></label>
        <label>当前用途<input readOnly value={label(properties.current_land_use_class)} /></label>
        <label>规划用途<input readOnly value={label(properties.planned_land_use_class)} /></label>
        <label>目标用途<select value={targetClass} onChange={event => setTargetClass(event.target.value)}><option value="">请选择</option>{rows<string>(catalog.land_use_classes).map(value => <option key={value}>{value}</option>)}</select></label>
        <label>替代用途<select value={alternativeClass} onChange={event => setAlternativeClass(event.target.value)}><option value="">不设置</option>{rows<string>(catalog.land_use_classes).map(value => <option key={value}>{value}</option>)}</select></label>
        <label>行动理由<textarea value={rationale} onChange={event => setRationale(event.target.value)} /></label>
        <div><strong>数据快照</strong><p>{label(catalog.snapshot_digest)}</p></div>
        <button className="secondary-button" onClick={validate}><ShieldCheck size={14} />验证动作</button>
        <label><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />人工确认：理解该结果不是规划许可或已观测政策效果。</label>
        <button className="primary-button" disabled={loading || !confirmed} onClick={rollout}><Play size={14} />执行反事实推演</button>
      </div>
      <div className="traditional-panel">
        <h4>状态轨迹与地图</h4>
        <div className="traditional-boundary-grid"><div><span>转换状态</span><strong>{label(transition.status)}</strong></div><div><span>人工复核</span><strong>{label(record(validation?.validation).review_required)}</strong></div></div>
        <h5>t0 当前状态</h5><p>{label(properties.current_land_use_class)}</p>
        <h5>t1 直接变更</h5><p>{label(record(t1.direct_state_delta).from_land_use_class)} → {label(record(t1.direct_state_delta).to_land_use_class)}</p>
        <h5>t2 邻域适应</h5><p>{rows(t2.messages).length} 条证据消息</p>
        <h5>基线/干预差异</h5><p>{label(record(rolloutPayload.spillover_state_delta).message_count_delta)} 条消息差异</p>
        <button className="secondary-button" onClick={() => pushMap()}><Map size={14} />发送证据图层到地图</button>
      </div>
      <div className="traditional-panel">
        <h4>可审计结果</h4>
        <h5>直接状态变化</h5><pre>{JSON.stringify(rolloutPayload.direct_state_delta || {}, null, 2)}</pre>
        <h5>空间传播信号</h5><p>{rows(t2.messages).length} 条；其中村域聚合 {rows(t2.messages).filter(message => message.effect_type === 'village_land_use_structure_signal').length} 条。</p>
        <h5>村域聚合</h5><p>仅展示跨尺度代理信号，不由行政均值反推地块效果。</p>
        <h5>不可预测效果</h5><p>{rows<string>(rolloutPayload.unavailable_effects).join(' / ') || '-'}</p>
        <h5>不确定性</h5><pre>{JSON.stringify(rolloutPayload.uncertainty || {}, null, 2)}</pre>
        <h5>完整证据链</h5><p>run_id: {label(run?.run_id)} · claim: {label(record(rolloutPayload.claim_boundary).max_claim_level)}</p>
      </div>
    </div>
  </section>;
}
