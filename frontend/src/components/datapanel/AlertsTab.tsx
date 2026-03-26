import { useState, useEffect } from 'react';

interface AlertRule {
  id: number;
  name: string;
  metric_name: string;
  condition: string;
  threshold: number;
  severity: string;
  channel: string;
  enabled: boolean;
}

interface AlertEvent {
  id: number;
  rule_id: number;
  metric_name: string;
  metric_value: number;
  threshold: number;
  severity: string;
  message: string;
  created_at: string;
}

const EMPTY_RULE = { name: '', metric_name: '', condition: 'gt', threshold: 0, severity: 'warning', channel: 'webhook' };

export default function AlertsTab() {
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [history, setHistory] = useState<AlertEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ ...EMPTY_RULE });
  const [activeView, setActiveView] = useState<'rules' | 'history'>('rules');

  const fetchRules = async () => {
    try {
      const r = await fetch('/api/alert-rules', { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setRules(d.rules || []); }
    } catch { /* ignore */ }
  };

  const fetchHistory = async () => {
    try {
      const r = await fetch('/api/alert-history?limit=50', { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setHistory(d.events || []); }
    } catch { /* ignore */ }
  };

  useEffect(() => {
    Promise.all([fetchRules(), fetchHistory()]).finally(() => setLoading(false));
  }, []);

  const createRule = async () => {
    if (!form.name || !form.metric_name) return;
    try {
      const r = await fetch('/api/alert-rules', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (r.ok) { setShowForm(false); setForm({ ...EMPTY_RULE }); fetchRules(); }
    } catch { /* ignore */ }
  };

  const deleteRule = async (id: number) => {
    if (!confirm('确认删除此告警规则？')) return;
    try {
      await fetch(`/api/alert-rules/${id}`, { method: 'DELETE', credentials: 'include' });
      fetchRules();
    } catch { /* ignore */ }
  };

  const sevColor = (s: string) =>
    s === 'critical' ? '#e53935' : s === 'warning' ? '#fb8c00' : '#43a047';

  const condLabel = (c: string) =>
    ({ gt: '>', gte: '≥', lt: '<', lte: '≤', eq: '=', neq: '≠' }[c] || c);

  if (loading) return <div style={{ padding: 12 }}>加载中...</div>;

  return (
    <div style={{ padding: 12 }}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        {(['rules', 'history'] as const).map(v => (
          <button key={v} onClick={() => setActiveView(v)} style={{
            padding: '4px 12px', borderRadius: 4, cursor: 'pointer',
            background: activeView === v ? '#1a73e8' : 'white',
            color: activeView === v ? 'white' : '#333',
            border: activeView === v ? 'none' : '1px solid #ddd',
          }}>
            {v === 'rules' ? '告警规则' : '告警历史'}
          </button>
        ))}
        {activeView === 'rules' && (
          <button onClick={() => setShowForm(!showForm)} style={{
            marginLeft: 'auto', padding: '4px 12px', borderRadius: 4, border: 'none',
            background: '#1a73e8', color: 'white', cursor: 'pointer', fontSize: 12,
          }}>+ 新建规则</button>
        )}
      </div>

      {showForm && activeView === 'rules' && (
        <div style={{ border: '1px solid #e0e0e0', borderRadius: 6, padding: 12, marginBottom: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>新建告警规则</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 8 }}>
            <input placeholder="规则名称" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
              style={{ padding: '4px 8px', border: '1px solid #ddd', borderRadius: 4, fontSize: 12 }} />
            <input placeholder="指标名称 (如 quality_score)" value={form.metric_name} onChange={e => setForm({ ...form, metric_name: e.target.value })}
              style={{ padding: '4px 8px', border: '1px solid #ddd', borderRadius: 4, fontSize: 12 }} />
            <div style={{ display: 'flex', gap: 4 }}>
              <select value={form.condition} onChange={e => setForm({ ...form, condition: e.target.value })}
                style={{ padding: '4px', border: '1px solid #ddd', borderRadius: 4, fontSize: 12 }}>
                <option value="gt">&gt;</option><option value="gte">≥</option>
                <option value="lt">&lt;</option><option value="lte">≤</option>
                <option value="eq">=</option><option value="neq">≠</option>
              </select>
              <input type="number" placeholder="阈值" value={form.threshold} onChange={e => setForm({ ...form, threshold: Number(e.target.value) })}
                style={{ padding: '4px 8px', border: '1px solid #ddd', borderRadius: 4, fontSize: 12, width: 80 }} />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <select value={form.severity} onChange={e => setForm({ ...form, severity: e.target.value })}
              style={{ padding: '4px', border: '1px solid #ddd', borderRadius: 4, fontSize: 12 }}>
              <option value="info">信息</option><option value="warning">警告</option><option value="critical">严重</option>
            </select>
            <select value={form.channel} onChange={e => setForm({ ...form, channel: e.target.value })}
              style={{ padding: '4px', border: '1px solid #ddd', borderRadius: 4, fontSize: 12 }}>
              <option value="webhook">Webhook</option><option value="log">日志</option>
            </select>
            <button onClick={createRule} style={{ padding: '4px 12px', borderRadius: 4, border: 'none', background: '#43a047', color: 'white', cursor: 'pointer', fontSize: 12 }}>保存</button>
            <button onClick={() => setShowForm(false)} style={{ padding: '4px 12px', borderRadius: 4, border: '1px solid #ddd', cursor: 'pointer', fontSize: 12 }}>取消</button>
          </div>
        </div>
      )}

      {activeView === 'rules' && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead><tr style={{ background: '#f5f5f5' }}>
            <th style={{ padding: '6px 8px', textAlign: 'left' }}>名称</th>
            <th style={{ padding: '6px 8px', textAlign: 'left' }}>指标</th>
            <th style={{ padding: '6px 8px', textAlign: 'left' }}>条件</th>
            <th style={{ padding: '6px 8px', textAlign: 'left' }}>严重度</th>
            <th style={{ padding: '6px 8px', textAlign: 'left' }}>通道</th>
            <th style={{ padding: '6px 8px', textAlign: 'left' }}>状态</th>
            <th style={{ padding: '6px 8px', textAlign: 'left' }}>操作</th>
          </tr></thead>
          <tbody>{rules.map(r => (
            <tr key={r.id}>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee' }}>{r.name}</td>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee', fontFamily: 'monospace' }}>{r.metric_name}</td>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee' }}>{condLabel(r.condition)} {r.threshold}</td>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee' }}>
                <span style={{ padding: '2px 6px', borderRadius: 3, fontSize: 11, background: sevColor(r.severity), color: 'white' }}>{r.severity}</span>
              </td>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee' }}>{r.channel}</td>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee' }}>
                <span style={{ padding: '2px 6px', borderRadius: 3, fontSize: 11, background: r.enabled ? '#43a047' : '#999', color: 'white' }}>{r.enabled ? '启用' : '禁用'}</span>
              </td>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee' }}>
                <button onClick={() => deleteRule(r.id)} style={{ padding: '2px 8px', borderRadius: 3, border: '1px solid #e53935', color: '#e53935', background: 'white', cursor: 'pointer', fontSize: 11 }}>删除</button>
              </td>
            </tr>
          ))}</tbody>
        </table>
      )}

      {activeView === 'history' && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead><tr style={{ background: '#f5f5f5' }}>
            <th style={{ padding: '6px 8px', textAlign: 'left' }}>时间</th>
            <th style={{ padding: '6px 8px', textAlign: 'left' }}>指标</th>
            <th style={{ padding: '6px 8px', textAlign: 'left' }}>值</th>
            <th style={{ padding: '6px 8px', textAlign: 'left' }}>阈值</th>
            <th style={{ padding: '6px 8px', textAlign: 'left' }}>严重度</th>
            <th style={{ padding: '6px 8px', textAlign: 'left' }}>消息</th>
          </tr></thead>
          <tbody>{history.map(e => (
            <tr key={e.id}>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee', whiteSpace: 'nowrap' }}>{new Date(e.created_at).toLocaleString()}</td>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee', fontFamily: 'monospace' }}>{e.metric_name}</td>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee' }}>{e.metric_value}</td>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee' }}>{e.threshold}</td>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee' }}>
                <span style={{ padding: '2px 6px', borderRadius: 3, fontSize: 11, background: sevColor(e.severity), color: 'white' }}>{e.severity}</span>
              </td>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid #eee', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>{e.message}</td>
            </tr>
          ))}</tbody>
        </table>
      )}

      {activeView === 'rules' && rules.length === 0 && !showForm && (
        <div style={{ color: '#999', fontSize: 12, marginTop: 8 }}>暂无告警规则，点击"新建规则"创建</div>
      )}
      {activeView === 'history' && history.length === 0 && (
        <div style={{ color: '#999', fontSize: 12, marginTop: 8 }}>暂无告警记录</div>
      )}
    </div>
  );
}
