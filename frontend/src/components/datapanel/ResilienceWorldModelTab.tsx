import { useEffect, useState } from 'react';
import { AlertTriangle, Map, RefreshCw, Search, Shield, TriangleAlert } from 'lucide-react';

type Row = Record<string, any>;
const TARGET_NODE = '江北区|观音桥街道|653';

export default function ResilienceWorldModelTab() {
  const [overview, setOverview] = useState<Row | null>(null);
  const [gates, setGates] = useState<Row>({});
  const [nodes, setNodes] = useState<Row[]>([]);
  const [nodeId, setNodeId] = useState(TARGET_NODE);
  const [detail, setDetail] = useState<Row | null>(null);
  const [hazard, setHazard] = useState('flood');
  const [intervention, setIntervention] = useState('evacuation_route');
  const [scenario, setScenario] = useState<Row | null>(null);
  const [search, setSearch] = useState(TARGET_NODE);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const loadOverview = async () => {
    const responses = await Promise.all(['overview', 'gates'].map(name => fetch(`/api/uwm/resilience-kernel/${name}`, { credentials: 'include' })));
    const payloads = await Promise.all(responses.map(response => response.json()));
    if (responses.some(response => !response.ok)) throw new Error(payloads.find(payload => payload.error)?.error || '韧性Kernel不可用');
    setOverview(payloads[0]); setGates(payloads[1].evidence_gates || {});
  };

  const loadNodes = async (query = search) => {
    const response = await fetch(`/api/uwm/resilience-kernel/nodes?search=${encodeURIComponent(query)}&limit=100`, { credentials: 'include' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || '韧性节点检索失败');
    setNodes(Array.isArray(payload.nodes) ? payload.nodes : []);
  };

  const loadDetail = async (selected = nodeId) => {
    const response = await fetch(`/api/uwm/resilience-kernel/nodes/${encodeURIComponent(selected)}`, { credentials: 'include' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || '韧性状态读取失败');
    setDetail(payload); setScenario(null);
  };

  const initialize = async () => {
    setLoading(true); setMessage('');
    try { await Promise.all([loadOverview(), loadNodes(TARGET_NODE), loadDetail(TARGET_NODE)]); }
    catch (error) { setMessage(error instanceof Error ? error.message : '韧性Kernel不可用'); }
    finally { setLoading(false); }
  };

  const selectNode = async (selected: string) => {
    setNodeId(selected); setSearch(selected); setLoading(true); setMessage('');
    try { await loadDetail(selected); }
    catch (error) { setMessage(error instanceof Error ? error.message : '韧性状态读取失败'); }
    finally { setLoading(false); }
  };

  const checkScenario = async () => {
    setLoading(true); setMessage('');
    try {
      const response = await fetch('/api/uwm/resilience-kernel/scenario-readiness', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ node_id: nodeId, hazard_type: hazard, intervention_type: intervention }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '韧性情景审查失败');
      setScenario(payload); window.__handleMapUpdate?.(payload.map_payload);
    } catch (error) { setMessage(error instanceof Error ? error.message : '韧性情景审查失败'); }
    finally { setLoading(false); }
  };

  useEffect(() => { initialize(); }, []);
  const node = detail?.node || {};
  const network = node.network_context || {};
  const services = node.public_service_context || {};
  const emergency = node.emergency_facility_context || {};

  return <div className="traditional-livability-tab" data-testid="resilience-kernel-panel"><div className="traditional-panel">
    <div className="traditional-panel-title"><strong>韧性世界模型（需求19）</strong><button className="secondary-button" onClick={initialize} disabled={loading}><RefreshCw size={14} />刷新真实状态</button></div>
    <div className="traditional-message error"><Shield size={15} />空间邻接不是灾害传播系数；设施存在不等于应急响应能力。系统只会在灾害、暴露、传播、恢复、干预和评估证据均满足时开放动态Rollout。</div>
    {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
    <div className="traditional-kpi-grid"><div className="traditional-kpi"><span>状态节点</span><strong>{overview?.summary?.state_node_count ?? '-'}</strong></div><div className="traditional-kpi"><span>边界邻接边</span><strong>{overview?.summary?.graph_edge_count ?? '-'}</strong></div><div className="traditional-kpi"><span>证据门禁</span><strong>{overview?.summary?.evidence_gate_count ?? '-'}</strong></div><div className="traditional-kpi"><span>开放转移机制</span><strong>{overview?.summary?.open_transition_mechanism_count ?? '-'}</strong></div></div>
    <div className="traditional-form-grid">
      <label>韧性行政单元检索<div className="traditional-inline-actions"><input value={search} onChange={event => setSearch(event.target.value)} placeholder="区县、乡镇或node_id" /><button className="secondary-button" onClick={() => loadNodes()} disabled={loading}><Search size={14} />查找</button></div></label>
      <label>检索结果<select value={nodeId} onChange={event => selectNode(event.target.value)}>{!nodes.some(item => item.node_id === nodeId) && <option value={nodeId}>{nodeId}</option>}{nodes.map(item => <option key={item.node_id} value={item.node_id}>{item.node_id}</option>)}</select></label>
    </div>
    {detail && <><h4>真实韧性状态上下文</h4><div className="traditional-kpi-grid"><div className="traditional-kpi"><span>道路段</span><strong>{network.road_segment_count ?? '-'}</strong></div><div className="traditional-kpi"><span>道路长度 km</span><strong>{Number(network.road_length_km || 0).toFixed(2)}</strong></div><div className="traditional-kpi"><span>服务可达性</span><strong>{Number(network.service_accessibility_score || 0).toFixed(3)}</strong></div><div className="traditional-kpi"><span>基础服务点</span><strong>{services.service_point_count ?? '-'}</strong></div><div className="traditional-kpi"><span>应急设施观测数</span><strong>{emergency.observed_facility_count ?? '-'}</strong></div><div className="traditional-kpi"><span>响应时间可用</span><strong>{String(Boolean(emergency.response_time_claim))}</strong></div></div><button className="secondary-button" onClick={() => window.__handleMapUpdate?.(detail.map_payload)}><Map size={14} />定位真实行政单元</button></>}
    <h4>韧性情景准入审查</h4><div className="traditional-form-grid"><label>冲击类型<select value={hazard} onChange={event => setHazard(event.target.value)}><option value="flood">洪涝</option><option value="extreme_heat">极端高温</option><option value="landslide">滑坡地灾</option><option value="storm">强对流/风暴</option></select></label><label>拟议干预<select value={intervention} onChange={event => setIntervention(event.target.value)}><option value="evacuation_route">疏散路线</option><option value="emergency_facility">应急设施</option><option value="infrastructure_hardening">基础设施加固</option><option value="cooling_shelter">避暑/降温场所</option></select></label></div>
    <button className="primary-button" onClick={checkScenario} disabled={!detail || loading}>审查情景是否可推演</button>
    {scenario && <div className="traditional-message error" data-testid="resilience-scenario-blocked"><TriangleAlert size={16} /><div><strong>动态推演已阻断：证据不足</strong><br />{scenario.claim_boundary}<br /><span>缺少的最小证据：</span><ul>{(scenario.required_evidence || []).map((item: string) => <li key={item}>{item}</li>)}</ul></div></div>}
    <h4>当前证据门</h4><p>{Object.entries(gates).map(([key, value]: [string, any]) => `${key}:${value.status}`).join(' · ')}</p>
  </div></div>;
}
