import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Map, RefreshCw, Shield, Target } from 'lucide-react';

type Row = Record<string, any>;
function asArray<T = Row>(value: unknown): T[] { return Array.isArray(value) ? value as T[] : []; }
function isRecord(value: unknown): value is Row { return Boolean(value) && typeof value === 'object' && !Array.isArray(value); }
function fmtArea(value: unknown): string { const number = Number(value); return Number.isFinite(number) ? `${(number / 10000).toFixed(2)} 公顷` : '-'; }

export default function TraditionalLivabilityS7Panel() {
  const [result, setResult] = useState<Row | null>(null);
  const [gate, setGate] = useState<Row | null>(null);
  const [unavailable, setUnavailable] = useState<Row | null>(null);
  const [loading, setLoading] = useState(false);
  const [acknowledgement, setAcknowledgement] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [resultResponse, gateResponse] = await Promise.all([
        fetch('/api/uwm/traditional-livability/s7', { credentials: 'include' }),
        fetch('/api/uwm/traditional-livability/s7/demand-gate', { credentials: 'include' }),
      ]);
      const [resultPayload, gatePayload] = await Promise.all([resultResponse.json(), gateResponse.json()]);
      if (!resultResponse.ok || !gateResponse.ok) { setResult(null); setGate(gatePayload); setUnavailable(resultPayload); return; }
      setResult(resultPayload); setGate(gatePayload); setUnavailable(null);
    } catch (error: unknown) {
      setResult(null); setUnavailable({ blockers: [error instanceof Error ? error.message : 's7_request_failed'] });
    } finally { setLoading(false); }
  };

  const run = async (mode: 'authoritative' | 'conditional') => {
    setLoading(true);
    try {
      const response = await fetch('/api/uwm/traditional-livability/s7/run', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, acknowledgement: mode === 'conditional' ? acknowledgement : false }),
      });
      const payload = await response.json();
      if (!response.ok) { setUnavailable(payload); return; }
      setResult(payload); setUnavailable(null);
    } catch (error: unknown) {
      setUnavailable({ blockers: [error instanceof Error ? error.message : 's7_run_failed'] });
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);
  const funnel = isRecord(result?.candidate_filter_funnel) ? result.candidate_filter_funnel : {};
  const summary = isRecord(result?.demand_summary) ? result.demand_summary : {};
  const assumptions = isRecord(result?.assumptions) ? result.assumptions : {};
  const payload = isRecord(result?.geometry_payload) ? result.geometry_payload : {};
  const ranked = asArray<Row>(result?.ranked_candidates);
  const selected = asArray<Row>(result?.selected_sites);
  const blockers = asArray<string>(gate?.blockers || result?.production_blockers || unavailable?.blockers);
  const needConfirmed = gate?.state === 'authoritative_need_confirmed';
  const needUnresolved = gate?.state === 'need_unresolved';

  const mapUpdate = useMemo(() => {
    const pointFeatures = (sourceRows: Row[], color: string, label: string) => sourceRows.filter(row => isRecord(row.centroid)).map(row => ({
      type: 'Feature', properties: { label, color, parcel_id: row.parcel_id, planning_area_id: row.planning_area_id, exclusion_reason: row.exclusion_reason, not_a_site_recommendation: result?.not_a_site_recommendation === true },
      geometry: { type: 'Point', coordinates: [row.centroid.longitude, row.centroid.latitude] },
    }));
    return {
      schema: 'map_update.v1', summary: { title: '福禄镇小学条件式候选排序' }, layers: [
        { name: '小学候选地块', type: 'geojson', geojsonData: { type: 'FeatureCollection', features: pointFeatures(asArray<Row>(payload.candidate_centroids), '#2563eb', '小学候选地块') } },
        { name: '住宅用地需求代理', type: 'geojson', geojsonData: { type: 'FeatureCollection', features: pointFeatures(asArray<Row>(payload.demand_centroids), '#f97316', '住宅用地面积代理') } },
        { name: '距离代理覆盖范围', type: 'geojson', geojsonData: { type: 'FeatureCollection', features: pointFeatures(asArray<Row>(payload.selected_candidate_centroids), '#059669', '距离代理覆盖范围') } },
        { name: '排除地块', type: 'geojson', geojsonData: { type: 'FeatureCollection', features: pointFeatures(asArray<Row>(payload.excluded_candidates), '#94a3b8', '排除地块') } },
      ],
    };
  }, [payload, result?.not_a_site_recommendation]);

  return <div className="traditional-panel">
    <div className="traditional-panel-title"><Target size={15} /><strong>S7 小学选址（传统 GIS）</strong></div>
    <p>福禄镇和平村与斑竹村规划样例。S1需求证据与S7空间排序分开，投影直线距离不是步行时间、法定服务范围或学校容量。</p>
    <button className="secondary-button" onClick={load} disabled={loading}><RefreshCw size={14} />刷新需求证据与S7</button>
    {unavailable && <div className="traditional-message error"><AlertTriangle size={15} />{asArray<string>(unavailable.blockers).join(' / ') || unavailable.error || 'S7当前不可用'}</div>}
    <div className="traditional-two-col">
      <div className="traditional-panel">
        <h4>需求证据</h4>
        <div className="traditional-boundary-grid"><div><span>Demand Gate</span><strong>{gate?.state || '-'}</strong></div><div><span>S1类别</span><strong>{gate?.standard_class_id || '-'}</strong></div><div><span>权威缺口</span><strong>{gate?.gap?.gap_value ?? '未解析'}</strong></div><div><span>建议许可</span><strong>{needConfirmed ? '允许权威建议模式' : '不允许'}</strong></div></div>
        {needUnresolved && <div className="traditional-message error"><Shield size={15} />小学新增需求尚未被权威 S1 指标证明。以下结果仅表示假设需要新增小学时，基于住宅用地面积和投影直线距离代理的候选排序，不构成选址建议。</div>}
        <p>阻塞项：{blockers.join(' / ') || '-'}</p>
        <h4>运行模式</h4>
        <button className="primary-button" disabled={!needConfirmed || loading} onClick={() => run('authoritative')}>权威建议模式</button>
        <label><input type="checkbox" checked={acknowledgement} onChange={event => setAcknowledgement(event.target.checked)} />我确认该结果不构成选址建议</label>
        <button className="secondary-button" disabled={!needUnresolved || !acknowledgement || loading} onClick={() => run('conditional')}>条件式排序模式</button>
      </div>
      {result && <div className="traditional-panel">
        <div className="traditional-kpi-grid"><div className="traditional-kpi"><span>距离阈值</span><strong>{assumptions.coverage_distance_m || '-'} m</strong></div><div className="traditional-kpi"><span>候选数</span><strong>{ranked.length}</strong></div><div className="traditional-kpi"><span>住宅用地面积代理</span><strong>{fmtArea(summary.total_proxy_area_m2)}</strong></div><div className="traditional-kpi"><span>未覆盖代理面积</span><strong>{fmtArea(summary.unserved_proxy_area_m2)}</strong></div></div>
        <h4>{result.not_a_site_recommendation === true ? '条件式候选排名' : '权威需求门控选址结果'}</h4>
        <div className="traditional-table-wrap"><table className="traditional-table"><thead><tr><th>序号</th><th>地块</th><th>新增覆盖面积</th><th>重复覆盖面积</th><th>证据边界</th></tr></thead><tbody>{ranked.slice(0, 8).map((row, index) => <tr key={`${row.planning_area_id}-${row.parcel_id}`}><td>{row.selection_round || index + 1}</td><td>{row.planning_area_id} · {row.parcel_id}</td><td>{fmtArea(row.newly_covered_proxy_area_m2)}</td><td>{fmtArea(row.overlap_proxy_area_m2)}</td><td>{row.not_a_site_recommendation === true ? '不构成选址建议' : row.site_role || '-'}</td></tr>)}</tbody></table></div>
        <h4>候选过滤漏斗</h4><p>排除地块：{funnel.excluded_candidate_count || 0}；无合格候选状态：candidate_policy_no_eligible_parcels</p>
        <button className="primary-button" onClick={() => window.__handleMapUpdate?.(mapUpdate)} disabled={selected.length === 0}><Map size={14} />发送条件式空间证据到地图</button>
        <p>能力边界：不输出学校容量、合规、道路网络可达性、未来需求或政策收益。</p>
      </div>}
    </div>
  </div>;
}
