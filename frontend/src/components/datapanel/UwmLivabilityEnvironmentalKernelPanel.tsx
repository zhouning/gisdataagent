import { useEffect, useState } from 'react';
import { AlertTriangle, CloudSun, Map, RefreshCw, Shield, Clock3 } from 'lucide-react';

type Row = Record<string, any>;
const asArray = <T = Row,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];
const support = (value: unknown) => String(value || 'unavailable');

export default function UwmLivabilityEnvironmentalKernelPanel() {
  const [scene, setScene] = useState<Row | null>(null);
  const [gate, setGate] = useState<Row | null>(null);
  const [mapPayload, setMapPayload] = useState<Row | null>(null);
  const [catalog, setCatalog] = useState<Row[]>([]);
  const [nodeId, setNodeId] = useState('');
  const [replay, setReplay] = useState<Row | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true); setMessage('');
    try {
      const [sceneResponse, gateResponse, mapResponse, nodesResponse] = await Promise.all([
        fetch('/api/uwm/livability/environmental-kernel/scene', { credentials: 'include' }),
        fetch('/api/uwm/livability/environmental-kernel/evidence-gate', { credentials: 'include' }),
        fetch('/api/uwm/livability/environmental-kernel/map', { credentials: 'include' }),
        fetch('/api/uwm/livability/environmental-kernel/nodes', { credentials: 'include' }),
      ]);
      const [sceneData, gateData, mapData, nodesData] = await Promise.all([sceneResponse.json(), gateResponse.json(), mapResponse.json(), nodesResponse.json()]);
      if (!sceneResponse.ok || !gateResponse.ok || !mapResponse.ok || !nodesResponse.ok) throw new Error(sceneData.error || gateData.error || mapData.error || nodesData.error || '环境 Kernel 产品不可用');
      setScene(sceneData); setGate(gateData); setMapPayload(mapData);
      const nextCatalog = asArray<Row>(nodesData.nodes); setCatalog(nextCatalog); setNodeId(previous => previous || nextCatalog[0]?.node_id || ''); setReplay(null);
    } catch (error: unknown) { setMessage(error instanceof Error ? error.message : '环境 Kernel 产品不可用'); }
    finally { setLoading(false); }
  };

  const loadReplay = async () => {
    if (!nodeId) return;
    setLoading(true); setMessage('');
    try {
      const response = await fetch(`/api/uwm/livability/environmental-kernel/temporal-replay/${encodeURIComponent(nodeId)}`, { credentials: 'include' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'PM2.5 时序状态回放不可用');
      setReplay(payload);
    } catch (error: unknown) { setMessage(error instanceof Error ? error.message : 'PM2.5 时序状态回放不可用'); }
    finally { setLoading(false); }
  };

  const run = async () => {
    if (!scene || !acknowledged) return;
    const firstNode = asArray<Row>(scene.state?.spatial_nodes)[0];
    const response = await fetch('/api/uwm/livability/environmental-kernel/rollout', {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action_type: 'increase_tree_canopy_proxy', target_node_ids: firstNode ? [firstNode.node_id] : [], state_snapshot_digest: scene.state?.snapshot_digest }),
    });
    const payload = await response.json();
    setMessage(response.ok ? `not_a_causal_effect_estimate=${String(payload.not_a_causal_effect_estimate)}` : `证据门阻止运行：${payload.error || 'unavailable'}`);
  };

  useEffect(() => { load(); }, []);
  const blockers = asArray<string>(gate?.production_blockers);
  const nodes = asArray<Row>(scene?.state?.spatial_nodes);
  const temporal = gate?.temporal_calibration || {};
  const direct = gate?.direct_action_response || {};
  const spatial = gate?.spatial_propagation || {};
  const replayNode = replay?.node || {};
  const replayQuality = replay?.source_quality || {};

  return <div className="uwm-livability-panel">
    <div className="uwm-livability-panel-title"><CloudSun size={15} /><strong>需求11 · 环境动态 Kernel</strong><button className="secondary-button" onClick={load} disabled={loading}><RefreshCw size={14} />刷新</button></div>
    <p>观测时间范围：{scene?.scene_time_range?.start_date || '-'} 至 {scene?.scene_time_range?.end_date || '-'}。当前产品分离时间动力学、直接动作响应和空间传播；bounded_proxy 与 unavailable 不会被显示为确定收益。</p>
    {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
    <div className="uwm-evidence-grid">
      <div><span>状态节点</span><strong>{nodes.length}</strong></div><div><span>最高 claim</span><strong>{gate?.max_claim_level || '-'}</strong></div>
      <div><span>PM2.5 时间动力学</span><strong>{support(temporal.pm25?.support_level)}</strong></div><div><span>温度 时间动力学</span><strong>{support(temporal.temperature?.support_level)}</strong></div>
      <div><span>PM2.5 直接动作响应</span><strong>{support(direct.pm25?.support_level)}</strong></div><div><span>温度 直接动作响应</span><strong>{support(direct.temperature?.support_level)}</strong></div>
      <div><span>植被 空间传播</span><strong>{support(spatial.vegetation?.support_level)}</strong></div><div><span>PM2.5 空间传播</span><strong>{support(spatial.pm25?.support_level)}</strong></div>
    </div>
    <div className="traditional-message error"><Shield size={15} />生产阻塞项：{blockers.join(' / ') || '-'}</div>
    <div className="traditional-form-grid">
      <label>环境行政单元
        <select value={nodeId} onChange={event => { setNodeId(event.target.value); setReplay(null); }}>
          {catalog.map(node => <option key={node.node_id} value={node.node_id}>{node.node_id} · PM2.5 {Number(node.pm25_ugm3 || 0).toFixed(3)}</option>)}
        </select>
      </label>
    </div>
    <button className="secondary-button" disabled={!nodeId || loading} onClick={loadReplay}><Clock3 size={14} />查看7日PM2.5状态回放</button>
    {replay && <div className="uwm-evidence-grid" data-testid="environmental-temporal-replay">
      <div><span>回放记录</span><strong>{replayNode.record_count}</strong></div><div><span>首末变化</span><strong>{Number(replayNode.pm25_last_minus_first_ugm3 || 0) >= 0 ? '+' : ''}{Number(replayNode.pm25_last_minus_first_ugm3 || 0).toFixed(3)}</strong></div>
      <div><span>PM2.5最小值</span><strong>{Number(replayNode.pm25_min_ugm3 || 0).toFixed(3)}</strong></div><div><span>PM2.5最大值</span><strong>{Number(replayNode.pm25_max_ugm3 || 0).toFixed(3)}</strong></div>
      <div><span>支持等级</span><strong>{support(replayQuality.support_level)}</strong></div><div><span>数据性质</span><strong>{replayQuality.synthetic_status || '-'}</strong></div>
    </div>}
    {replay && <p>这是历史代理状态回放，不是未来日历预测，也不是干预政策效果。记录范围：{replayNode.start_timestamp} 至 {replayNode.end_timestamp}。</p>}
    <label><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} />我确认代理差异不构成因果政策效果</label>
    <div><button className="secondary-button" disabled={!acknowledged || !scene} onClick={run}>尝试受控绿地动作</button><button className="primary-button" disabled={!mapPayload} onClick={() => window.__handleMapUpdate?.(mapPayload)}><Map size={14} />发送观测状态到地图</button></div>
    <p>动作通道未校准时，绿地动作接口会被证据门阻断，不生成降温或降污染数字；not_a_causal_effect_estimate 固定为 true。</p>
  </div>;
}
