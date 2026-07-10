import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Map, RefreshCw, Shield, Target } from 'lucide-react';

type Row = Record<string, any>;

function asArray<T = Row>(value: unknown): T[] { return Array.isArray(value) ? value as T[] : []; }
function isRecord(value: unknown): value is Row { return Boolean(value) && typeof value === 'object' && !Array.isArray(value); }
function fmtArea(value: unknown): string { const number = Number(value); return Number.isFinite(number) ? `${(number / 10000).toFixed(2)} 公顷` : '-'; }

export default function TraditionalLivabilityS7Panel() {
  const [result, setResult] = useState<Row | null>(null);
  const [unavailable, setUnavailable] = useState<Row | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/uwm/traditional-livability/s7', { credentials: 'include' });
      const data = await response.json();
      if (!response.ok || data.ready === false) { setResult(null); setUnavailable(data); return; }
      setResult(data); setUnavailable(null);
    } catch (error: unknown) {
      setResult(null); setUnavailable({ blockers: [error instanceof Error ? error.message : 's7_request_failed'] });
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);
  const funnel = isRecord(result?.candidate_filter_funnel) ? result.candidate_filter_funnel : {};
  const summary = isRecord(result?.demand_summary) ? result.demand_summary : {};
  const assumptions = isRecord(result?.assumptions) ? result.assumptions : {};
  const payload = isRecord(result?.geometry_payload) ? result.geometry_payload : {};
  const ranked = asArray<Row>(result?.ranked_candidates);
  const selected = asArray<Row>(result?.selected_sites);
  const blockers = asArray<string>(result?.production_blockers || unavailable?.blockers);

  const mapUpdate = useMemo(() => {
    const pointFeatures = (rows: Row[], color: string, label: string) => rows.filter(row => isRecord(row.centroid)).map(row => ({
      type: 'Feature', properties: { label, color, parcel_id: row.parcel_id, planning_area_id: row.planning_area_id, exclusion_reason: row.exclusion_reason },
      geometry: { type: 'Point', coordinates: [row.centroid.longitude, row.centroid.latitude] },
    }));
    const selectedRows = asArray<Row>(payload.selected_candidate_centroids);
    const demandRows = asArray<Row>(payload.demand_centroids);
    const candidateRows = asArray<Row>(payload.candidate_centroids);
    const excludedRows = asArray<Row>(payload.excluded_candidates);
    return {
      schema: 'map_update.v1', summary: { title: '福禄镇小学选址：距离代理覆盖范围' }, layers: [
        { name: '小学候选地块', type: 'geojson', geojsonData: { type: 'FeatureCollection', features: pointFeatures(candidateRows, '#2563eb', '小学候选地块') } },
        { name: '住宅用地需求代理', type: 'geojson', geojsonData: { type: 'FeatureCollection', features: pointFeatures(demandRows, '#f97316', '住宅用地面积代理') } },
        { name: '距离代理覆盖范围', type: 'geojson', geojsonData: { type: 'FeatureCollection', features: pointFeatures(selectedRows, '#059669', '距离代理覆盖范围') } },
        { name: '排除地块', type: 'geojson', geojsonData: { type: 'FeatureCollection', features: pointFeatures(excludedRows, '#94a3b8', '排除地块') } },
      ],
    };
  }, [payload]);

  const sendMap = () => {
    window.__handleMapUpdate?.(mapUpdate);
  };

  return (
    <div className="traditional-panel">
      <div className="traditional-panel-title"><Target size={15} /><strong>S7 小学选址（传统 GIS）</strong></div>
      <p>福禄镇和平村与斑竹村规划样例；需求采用住宅用地面积代理。距离代理覆盖范围采用投影平面距离，不是路网、步行时间或学校容量结论。</p>
      <button className="secondary-button" onClick={load} disabled={loading}><RefreshCw size={14} />刷新 S7</button>
      {unavailable && <div className="traditional-message error"><AlertTriangle size={15} />S7 当前不可用：{blockers.join(' / ') || '-'}</div>}
      {result && <div className="traditional-two-col">
        <div className="traditional-panel">
          <div className="traditional-kpi-grid">
            <div className="traditional-kpi"><span>距离阈值</span><strong>{assumptions.coverage_distance_m || '-'} m</strong></div>
            <div className="traditional-kpi"><span>合格候选</span><strong>{funnel.eligible_candidate_count || 0}</strong></div>
            <div className="traditional-kpi"><span>住宅用地面积代理</span><strong>{fmtArea(summary.total_proxy_area_m2)}</strong></div>
            <div className="traditional-kpi"><span>未覆盖代理面积</span><strong>{fmtArea(summary.unserved_proxy_area_m2)}</strong></div>
          </div>
          <h4>候选过滤漏斗</h4>
          <div className="traditional-boundary-grid"><div><span>排除地块</span><strong>{funnel.excluded_candidate_count || 0}</strong></div><div><span>过滤原因</span><strong>{Object.entries(isRecord(funnel.excluded_by_reason) ? funnel.excluded_by_reason : {}).map(([key, value]) => `${key}:${value}`).join(' / ') || '-'}</strong></div></div>
          <h4>候选排名</h4>
          <div className="traditional-table-wrap"><table className="traditional-table"><thead><tr><th>排名</th><th>地块</th><th>新增覆盖面积</th><th>重复覆盖面积</th></tr></thead><tbody>{ranked.slice(0, 8).map((row, index) => <tr key={`${row.planning_area_id}-${row.parcel_id}`}><td>{row.selection_round || index + 1}</td><td>{row.planning_area_id} · {row.parcel_id}</td><td>{fmtArea(row.newly_covered_proxy_area_m2)}</td><td>{fmtArea(row.repeated_coverage_proxy_area_m2)}</td></tr>)}</tbody></table></div>
          {result.recommendation_status === 'no_recommendation' && <div className="traditional-message error">candidate_policy_no_eligible_parcels：未生成候选推荐。</div>}
          <div className="traditional-boundary-grid"><div><span>生产阻塞项</span><strong>{blockers.join(' / ') || '-'}</strong></div><div><span>能力边界</span><strong>不输出学校容量、合规、道路网络可达性结论、财务或未来政策收益</strong></div></div>
        </div>
        <div className="traditional-panel">
          <h4>地图同步</h4>
          <p>将小学候选地块、住宅用地需求代理、距离代理覆盖范围和排除地块发送到地图。</p>
          <button className="primary-button" onClick={sendMap} disabled={selected.length === 0}><Map size={14} />发送距离代理覆盖范围到地图</button>
          <div className="traditional-boundary-grid"><div><span>算法</span><strong>贪心 location-allocation</strong></div><div><span>距离模型</span><strong>projected_straight_line_distance_proxy</strong></div></div>
        </div>
      </div>}
    </div>
  );
}
