import { useEffect,useMemo,useState } from 'react';
import { AlertTriangle,Map,RefreshCw,Shield } from 'lucide-react';
type Row=Record<string,any>;type View='social_infrastructure'|'government_public_service';
const asArray=<T,>(v:unknown):T[]=>Array.isArray(v)?v as T[]:[];
export default function TraditionalLivabilitySocialPublicServicePanel(){
 const [view,setView]=useState<View>('social_infrastructure');const [overview,setOverview]=useState<Row|null>(null);const [facilities,setFacilities]=useState<Row[]>([]);const [admins,setAdmins]=useState<Row[]>([]);const [mapPayload,setMapPayload]=useState<Row|null>(null);const [message,setMessage]=useState('');const [loading,setLoading]=useState(false);
 const load=async()=>{setLoading(true);setMessage('');try{const suffix=`?view=${view}`;const responses=await Promise.all([fetch('/api/uwm/traditional-livability/social-public-service/overview',{credentials:'include'}),fetch('/api/uwm/traditional-livability/social-public-service/facilities'+suffix,{credentials:'include'}),fetch('/api/uwm/traditional-livability/social-public-service/admin-units'+suffix,{credentials:'include'}),fetch('/api/uwm/traditional-livability/social-public-service/map'+suffix,{credentials:'include'})]);const data=await Promise.all(responses.map(r=>r.json()));if(responses.some(r=>!r.ok))throw new Error(data.find(x=>x.error)?.error||'社会基础设施产品不可用');setOverview(data[0]);setFacilities(asArray(data[1].facilities));setAdmins(asArray(data[2].admin_units));setMapPayload(data[3]);}catch(e:unknown){setMessage(e instanceof Error?e.message:'社会基础设施产品不可用');}finally{setLoading(false)}};
 useEffect(()=>{load()},[view]);
 const ranked=useMemo(()=>[...admins].sort((a,b)=>Number(a.view?.relative_gap_rank||9999)-Number(b.view?.relative_gap_rank||9999)).slice(0,12),[admins]);const readiness=overview?.channel_readiness?.[view]||{};const unavailable=Object.entries(readiness).filter(([,r]:any)=>r.status==='unavailable').map(([name])=>name);
 return <div className="traditional-panel">
  <div className="traditional-panel-title"><strong>设施与公共服务证据产品</strong><button className="secondary-button" onClick={load} disabled={loading}><RefreshCw size={14}/>刷新</button></div>
  <div className="traditional-tag-list"><button className={view==='social_infrastructure'?'primary-button':'secondary-button'} onClick={()=>setView('social_infrastructure')}>社会基础设施（需求12）</button><button className={view==='government_public_service'?'primary-button':'secondary-button'} onClick={()=>setView('government_public_service')}>政府与公共服务（需求21）</button></div>
  <p>当前输出为已观察设施清册和 relative_evidence_gap 相对证据缺口；不把静态设施统计包装为UWM。</p>
  {message&&<div className="traditional-message error"><AlertTriangle size={15}/>{message}</div>}
  <div className="traditional-kpi-grid"><div className="traditional-kpi"><span>当前视图设施</span><strong>{facilities.length}</strong></div><div className="traditional-kpi"><span>区县单元</span><strong>{admins.length}</strong></div><div className="traditional-kpi"><span>虚构值</span><strong>{overview?.fabricated_value_count??'-'}</strong></div><div className="traditional-kpi"><span>最高结论</span><strong>{overview?.claim_boundary?.max_claim_level||'-'}</strong></div></div>
  <div className="traditional-message error"><Shield size={15}/>容量、生命周期、活跃状态、人口—容量匹配、权威服务圈和未来需求：数据未就绪。乡镇可达性未与区县设施强制连接。</div>
  <h4>不可用证据通道</h4><p>{unavailable.join(' / ')||'-'}</p>
  <h4>相对证据缺口排名</h4><div className="traditional-table-wrap"><table className="traditional-table"><thead><tr><th>排名</th><th>区县</th><th>设施数</th><th>类别数</th><th>核查原因</th></tr></thead><tbody>{ranked.map(row=><tr key={row.admin_unit_id}><td>{row.view?.relative_gap_rank}</td><td>{row.county||row.admin_unit_id}</td><td>{row.view?.facility_count}</td><td>{row.view?.category_count}</td><td>{asArray<string>(row.view?.relative_gap_reasons).join(' / ')||'-'}</td></tr>)}</tbody></table></div>
  <button className="primary-button" disabled={!mapPayload} onClick={()=>window.__handleMapUpdate?.(mapPayload)}><Map size={14}/>发送当前设施视图到地图</button>
 </div>
}
