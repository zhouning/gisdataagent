import { useEffect, useState } from 'react';
import { AlertTriangle, Map, RefreshCw, Route, Shield } from 'lucide-react';

type Row = Record<string, any>;
const asArray = <T = Row,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];

export default function TraditionalLivabilityMobilityPanel() {
  const [overview,setOverview]=useState<Row|null>(null); const [units,setUnits]=useState<Row[]>([]); const [mapPayload,setMapPayload]=useState<Row|null>(null); const [message,setMessage]=useState(''); const [loading,setLoading]=useState(false);
  const load=async()=>{setLoading(true);setMessage('');try{const [a,b,c]=await Promise.all([fetch('/api/uwm/traditional-livability/mobility/overview',{credentials:'include'}),fetch('/api/uwm/traditional-livability/mobility/admin-units',{credentials:'include'}),fetch('/api/uwm/traditional-livability/mobility/map',{credentials:'include'})]);const [oa,ub,mc]=await Promise.all([a.json(),b.json(),c.json()]);if(!a.ok||!b.ok||!c.ok)throw new Error(oa.error||ub.error||mc.error||'需求8产品不可用');setOverview(oa);setUnits(asArray<Row>(ub.admin_units));setMapPayload(mc);}catch(error:unknown){setMessage(error instanceof Error?error.message:'需求8产品不可用');}finally{setLoading(false);}};
  useEffect(()=>{load();},[]);
  const channels=overview?.channel_readiness||{}; const channelRows=Object.entries(channels) as [string,Row][]; const ranked=[...units].filter(row=>row.accessibility_gap_rank!=null).sort((a,b)=>Number(a.accessibility_gap_rank)-Number(b.accessibility_gap_rank)).slice(0,10);
  const loadDetail=async(id:string)=>{const response=await fetch(`/api/uwm/traditional-livability/mobility/admin-units/${encodeURIComponent(id)}`,{credentials:'include'});const data=await response.json();setMessage(response.ok?`${data.admin_unit_id}：network_proxy_not_observed_walk_time=${String(data.network_proxy_not_observed_walk_time)}`:(data.error||'行政单元不存在'));};
  return <div className="traditional-panel">
    <div className="traditional-panel-title"><Route size={15}/><strong>需求8 · 出行、步行性与可达性</strong><button className="secondary-button" onClick={load} disabled={loading}><RefreshCw size={14}/>刷新</button></div>
    <p>本产品使用服务设施与道路网络代理进行当前状态诊断。network_proxy_not_observed_walk_time=true；各证据通道分别展示，不合成单一总分。</p>
    {message&&<div className="traditional-message error"><AlertTriangle size={15}/>{message}</div>}
    <div className="traditional-kpi-grid"><div className="traditional-kpi"><span>行政单元</span><strong>{overview?.summary?.admin_unit_count||'-'}</strong></div><div className="traditional-kpi"><span>道路记录</span><strong>{overview?.summary?.road_segment_count||'-'}</strong></div><div className="traditional-kpi"><span>路网关系</span><strong>{overview?.summary?.mobility_graph_edge_count||'-'}</strong></div><div className="traditional-kpi"><span>最高结论</span><strong>{overview?.claim_boundary?.max_claim_level||'-'}</strong></div></div>
    <h4>通道证据状态</h4><div className="traditional-source-grid">{channelRows.map(([name,row])=><div key={name}><span>{name}</span><strong>{row.status}</strong><small>{asArray<string>(row.blockers).join(' / ')||'-'}</small></div>)}</div>
    <div className="traditional-message error"><Shield size={15}/>public_transport / road_safety / shaded_routes / universal_accessibility / parking_pressure / cycling_routes / pedestrian_crossings 当前均为 unavailable。</div>
    <h4>可达性缺口排名</h4><div className="traditional-table-wrap"><table className="traditional-table"><thead><tr><th>排名</th><th>行政单元</th><th>可达性代理</th><th>最近服务距离</th><th>人工核查候选</th></tr></thead><tbody>{ranked.map(row=><tr key={row.admin_unit_id} onClick={()=>loadDetail(row.admin_unit_id)}><td>{row.accessibility_gap_rank}</td><td>{row.county}{row.township}</td><td>{row.service_accessibility_score??'-'}</td><td>{row.nearest_essential_service_distance_m??'-'} m</td><td>{asArray<string>(row.review_priority_reasons).join(' / ')||'-'}</td></tr>)}</tbody></table></div>
    <button className="primary-button" disabled={!mapPayload} onClick={()=>window.__handleMapUpdate?.(mapPayload)}><Map size={14}/>发送可达性代理到地图</button>
    <p>implemented表示已有数据产品；proxy_only表示网络或距离代理；unavailable表示当前没有可支持的数值。排序仅供数据核查与规划复核。</p>
  </div>;
}
