import { useEffect, useState } from 'react';
import { AlertTriangle, Map, RefreshCw, Search, ShieldCheck, Target } from 'lucide-react';

type Row = Record<string, any>;

const TARGET_UNIT = '涪陵区|蔺市镇|498';
const indicators = [
  ['heat_risk', '热风险', true],
  ['air_pollution_exposure', '空气污染暴露', true],
  ['service_accessibility', '服务可达性', false],
  ['equity', '公平性', false],
  ['livability', '宜居性', false],
] as const;
const profileLabels: Record<string, string> = {
  balanced: '综合平衡',
  community_service: '社区服务优先',
  environmental_comfort: '环境舒适优先',
  equitable_livability: '公平宜居优先',
};

const number = (value: unknown, digits = 6) => Number(value || 0).toFixed(digits);

export default function UwmLivabilityDemand7Panel() {
  const [overview, setOverview] = useState<Row | null>(null);
  const [search, setSearch] = useState(TARGET_UNIT);
  const [units, setUnits] = useState<Row[]>([]);
  const [unitId, setUnitId] = useState(TARGET_UNIT);
  const [detail, setDetail] = useState<Row | null>(null);
  const [profile, setProfile] = useState('community_service');
  const [horizon, setHorizon] = useState('simulator_step');
  const [plan, setPlan] = useState<Row | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  const loadOverview = async () => {
    const response = await fetch('/api/uwm/livability/demand7/overview', { credentials: 'include' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || payload.blockers?.join(' / ') || '需求7产品不可用');
    setOverview(payload);
  };

  const searchUnits = async (query = search) => {
    const response = await fetch(`/api/uwm/livability/demand7/units?search=${encodeURIComponent(query)}&limit=50`, { credentials: 'include' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || '行政单元检索失败');
    setUnits(Array.isArray(payload.units) ? payload.units : []);
  };

  const loadDetail = async (selected = unitId) => {
    const response = await fetch(`/api/uwm/livability/demand7/units/${encodeURIComponent(selected)}`, { credentials: 'include' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || '行政单元状态加载失败');
    setDetail(payload);
    setPlan(null);
  };

  const initialize = async () => {
    setLoading(true); setMessage('');
    try {
      await Promise.all([loadOverview(), searchUnits(TARGET_UNIT), loadDetail(TARGET_UNIT)]);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '需求7产品不可用');
    } finally {
      setLoading(false);
    }
  };

  const selectUnit = async (selected: string) => {
    setUnitId(selected); setSearch(selected); setLoading(true); setMessage('');
    try { await loadDetail(selected); }
    catch (error) { setMessage(error instanceof Error ? error.message : '行政单元状态加载失败'); }
    finally { setLoading(false); }
  };

  const runPlan = async () => {
    setLoading(true); setMessage(''); setPlan(null);
    try {
      const response = await fetch('/api/uwm/livability/demand7/plan', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ unit_id: unitId, target_profile: profile, horizon }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '需求7规划失败');
      setPlan(payload);
      if (payload.status === 'completed' && payload.map_payload) window.__handleMapUpdate?.(payload.map_payload);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '需求7规划失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { initialize(); }, []);
  const recommendation = plan?.recommended_action || {};
  const current = detail?.current_state || {};
  const target = plan?.peer_target || overview?.target_definition?.profile_targets?.[profile] || detail?.peer_target || {};
  const projected = recommendation.projected_state || {};

  return <div className="uwm-livability-panel" data-testid="uwm-demand7-panel">
    <div className="uwm-livability-panel-title">
      <Target size={16} /><strong>需求7 · 宜居目标与社区干预规划</strong>
      <button className="secondary-button" onClick={initialize} disabled={loading}><RefreshCw size={14} />刷新真实快照</button>
    </div>
    <p>以1,017个真实行政单元代理状态、7,932条空间边和6,817条已存动作条件转移为基础，执行目标差距诊断、空间传播和干预排序。</p>
    {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
    <div className="uwm-evidence-grid">
      <div><span>状态节点</span><strong>{overview?.counts?.state_nodes || '-'}</strong></div>
      <div><span>空间边</span><strong>{overview?.counts?.spatial_edges || '-'}</strong></div>
      <div><span>可选动作</span><strong>{overview?.counts?.available_actions || '-'}</strong></div>
      <div><span>真实回放转移</span><strong>{overview?.counts?.stored_replay_transitions || '-'}</strong></div>
    </div>

    <div className="traditional-form-grid">
      <label>行政单元检索
        <div className="traditional-inline-actions">
          <input value={search} onChange={event => setSearch(event.target.value)} placeholder="区县、乡镇或unit_id" />
          <button className="secondary-button" onClick={() => searchUnits()} disabled={loading}><Search size={14} />查找</button>
        </div>
      </label>
      <label>检索结果
        <select value={unitId} onChange={event => selectUnit(event.target.value)}>
          {!units.some(unit => unit.unit_id === unitId) && <option value={unitId}>{unitId}</option>}
          {units.map(unit => <option key={unit.unit_id} value={unit.unit_id}>{unit.unit_id} · 需求{number(unit.livability_need_score, 3)}</option>)}
        </select>
      </label>
      <label>目标画像
        <select value={profile} onChange={event => { setProfile(event.target.value); setPlan(null); }}>
          {Object.entries(profileLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <label>推演尺度
        <select value={horizon} onChange={event => { setHorizon(event.target.value); setPlan(null); }}>
          <option value="simulator_step">单步UWM动作情景</option>
          <option value="24_month">24个月预测（证据不足）</option>
          <option value="five_year">5年预测（证据不足）</option>
        </select>
      </label>
    </div>
    <button className="primary-button" onClick={runPlan} disabled={loading || !detail}>执行需求7规划</button>

    {detail && <>
      <h4>当前状态与同源观测目标</h4>
      <div className="uwm-evidence-grid">
        {indicators.map(([key, label, lowerBetter]) => <div key={key}>
          <span>{label}{lowerBetter ? '（越低越好）' : ''}</span>
          <strong>{number(current[key])} → {number(target[key])}</strong>
        </div>)}
        <div><span>动作掩码通过</span><strong>{detail.available_action_count}项</strong></div>
      </div>
    </>}

    {plan?.status === 'blocked' && <div className="traditional-message error" data-testid="demand7-blocked">
      <AlertTriangle size={16} /><div><strong>{horizon === '24_month' ? '24个月预测证据不足' : '5年预测证据不足'}</strong><br />{plan.claim_boundary}</div>
    </div>}

    {plan?.status === 'completed' && <div data-testid="demand7-result">
      <h4>UWM干预优先级结论</h4>
      <div className="traditional-message success"><ShieldCheck size={16} /><div>
        推荐：<strong>{recommendation.action_label}</strong>；加权目标差距收敛 {number(recommendation.weighted_gap_closure, 6)}；影响 {recommendation.affected_unit_count} 个单元。
      </div></div>
      <div className="uwm-evidence-grid">
        {indicators.map(([key, label]) => <div key={key}><span>{label}</span><strong>{number(current[key])} → {number(projected[key])}</strong><small>Δ {Number(recommendation.target_unit_delta?.[key] || 0) >= 0 ? '+' : ''}{number(recommendation.target_unit_delta?.[key])}</small></div>)}
      </div>
      <button className="secondary-button" onClick={() => window.__handleMapUpdate?.(plan.map_payload)}><Map size={14} />发送目标单元与溢出预览到地图</button>
      <p>证据等级：{recommendation.evidence_grade}；转移来源：真实已存 step-0 simulator replay；空间图层来自真实乡镇边界。</p>
    </div>}

    <div className="traditional-message error"><AlertTriangle size={15} />模型步不等于24个月或5年；24个月预测证据不足；5年预测证据不足。</div>
    <p><strong>证据边界：</strong>这不是政策实施效果，也不是因果效应估计。社区意见输入和观察到的干预结果尚未接入，系统不会伪造这些结论。</p>
  </div>;
}
