import { useState, useEffect } from 'react';

interface AlertRule {
  id: number;
  name: string;
  metric_name: string;
  condition: string;
  threshold: number;
  severity: string;
  channel: string;
  channel_config: Record<string, string>;
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

const METRIC_OPTIONS = [
  { value: 'qc_score', label: '质检评分' },
  { value: 'defect_count', label: '缺陷数量' },
  { value: 'sla_violation_rate', label: 'SLA违规率' },
  { value: 'review_pending_count', label: '待复核数' },
];

const EMPTY_RULE = {
  name: '', metric_name: 'qc_score', condition: 'gt',
  threshold: 0, severity: 'warning', channel: 'webhook', webhook_url: '',
};

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
    } catch { /* endpoint may not exist yet */ }
  };

  const fetchHistory = async () => {
    try {
      const r = await fetch('/api/alert-history?limit=20', { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setHistory(d.events || []); }
    } catch { /* ignore */ }
  };

  useEffect(() => {
    Promise.all([fetchRules(), fetchHistory()]).finally(() => setLoading(false));
  }, []);

  const createRule = async () => {
    if (!form.name || !form.metric_name) return;
    const body: Record<string, unknown> = {
      name: form.name, metric_name: form.metric_name,
      condition: form.condition, threshold: form.threshold,
      severity: form.severity, channel: form.channel,
    };
    if (form.channel === 'webhook' && form.webhook_url) {
      body.channel_config = { webhook_url: form.webhook_url };
    }
    try {
      const r = await fetch('/api/alert-rules', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (r.ok) { setShowForm(false); setForm({ ...EMPTY_RULE }); fetchRules(); }
    } catch { /* ignore */ }
  };

  const toggleRule = async (id: number, enabled: boolean) => {
    try {
      await fetch(`/api/alert-rules/${id}`, {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !enabled }),
      });
      fetchRules();
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
    s === 'critical' ? '#e53935' : s === 'warning' ? '#fb8c00' : '#1a73e8';

  const condLabel = (c: string) =>
    ({ gt: '>', gte: '≥', lt: '<', lte: '≤', eq: '=' }[c] || c);

  if (loading) return <div style={{ padding: 12, color: '#888' }}>加载中...</div>;

  return (
    <div style={{ padding: 12 }}>
      {/* View switcher */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 10 }}>
        {(['rules', 'history'] as const).map(v => (
          <button key={v} onClick={() => setActiveView(v)}
            style={{
              padding: '4px 12px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
              background: activeView === v ? '#1e3a5f' : '#111827',
              color: activeView === v ? '#7dd3fc' : '#888',
              border: `1px solid ${activeView === v ? '#2563eb' : '#333'}`,
            }}>
            {v === 'rules' ? '告警规则' : '告警历史'}
          </button>
        ))}
        {activeView === 'rules' && (
          <button onClick={() => setShowForm(!showForm)} style={{
            marginLeft: 'auto', padding: '4px 12px', fontSize: 12, borderRadius: 4,
            border: 'none', background: '#1a73e8', color: 'white', cursor: 'pointer',
          }}>+ 新建规则</button>
        )}
      </div>

      {/* Create rule form */}
      {showForm && activeView === 'rules' && (
        <div style={{ background: '#1a1a2e', border: '1px solid #333', borderRadius: 6, padding: 12, marginBottom: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: '#e0e0e0' }}>新建告警规则</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
            <input placeholder="规则名称" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontSize: 12 }} />
            <select value={form.metric_name} onChange={e => setForm({ ...form, metric_name: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontSize: 12 }}>
              {METRIC_OPTIONS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <select value={form.condition} onChange={e => setForm({ ...form, condition: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontSize: 12 }}>
              <option value="gt">&gt;</option><option value="lt">&lt;</option>
              <option value="gte">≥</option><option value="lte">≤</option>
              <option value="eq">=</option>
            </select>
            <input type="number" placeholder="阈值" value={form.threshold}
              onChange={e => setForm({ ...form, threshold: Number(e.target.value) })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontSize: 12, width: 80 }} />
            <select value={form.severity} onChange={e => setForm({ ...form, severity: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontSize: 12 }}>
              <option value="info">信息</option><option value="warning">警告</option><option value="critical">严重</option>
            </select>
            <select value={form.channel} onChange={e => setForm({ ...form, channel: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontSize: 12 }}>
              <option value="webhook">Webhook</option><option value="email">邮件</option>
            </select>
          </div>
          {form.channel === 'webhook' && (
            <input placeholder="Webhook URL" value={form.webhook_url}
              onChange={e => setForm({ ...form, webhook_url: e.target.value })}
              style={{ width: '100%', background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontSize: 12, marginBottom: 8, boxSizing: 'border-box' }} />
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={createRule} style={{ padding: '4px 12px', borderRadius: 4, border: 'none', background: '#43a047', color: 'white', cursor: 'pointer', fontSize: 12 }}>保存</button>
            <button onClick={() => setShowForm(false)} style={{ padding: '4px 12px', borderRadius: 4, border: '1px solid #444', color: '#aaa', background: 'transparent', cursor: 'pointer', fontSize: 12 }}>取消</button>
          </div>
        </div>
      )}

      {/* Rules table */}
      {activeView === 'rules' && (
        <div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ background: '#1f2937' }}>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>名称</th>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>指标</th>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>条件</th>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>严重度</th>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>通道</th>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>启用</th>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>操作</th>
            </tr></thead>
            <tbody>{rules.map(r => (
              <tr key={r.id}>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#ccc' }}>{r.name}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', fontFamily: 'monospace', color: '#7dd3fc' }}>{r.metric_name}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#ccc' }}>{condLabel(r.condition)} {r.threshold}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937' }}>
                  <span style={{ display: 'inline-block', padding: '2px 6px', borderRadius: 3, fontSize: 11, background: sevColor(r.severity), color: 'white' }}>{r.severity}</span>
                </td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#aaa' }}>{r.channel}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937' }}>
                  <button onClick={() => toggleRule(r.id, r.enabled)}
                    style={{ fontSize: 11, color: r.enabled ? '#10b981' : '#888', background: 'none', border: 'none', cursor: 'pointer' }}>
                    {r.enabled ? '启用' : '禁用'}
                  </button>
                </td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937' }}>
                  <button onClick={() => deleteRule(r.id)}
                    style={{ padding: '2px 8px', borderRadius: 3, border: '1px solid #e53935', color: '#e53935', background: 'transparent', cursor: 'pointer', fontSize: 11 }}>删除</button>
                </td>
              </tr>
            ))}</tbody>
          </table>
          {rules.length === 0 && !showForm && (
            <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>暂无告警规则，点击"新建规则"创建</div>
          )}
        </div>
      )}

      {/* Alert history */}
      {activeView === 'history' && (
        <div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ background: '#1f2937' }}>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>时间</th>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>指标</th>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>值</th>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>阈值</th>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>严重度</th>
              <th style={{ padding: '6px 8px', textAlign: 'left', color: '#aaa' }}>消息</th>
            </tr></thead>
            <tbody>{history.map(e => (
              <tr key={e.id}>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', whiteSpace: 'nowrap', color: '#aaa' }}>{new Date(e.created_at).toLocaleString()}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', fontFamily: 'monospace', color: '#7dd3fc' }}>{e.metric_name}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#ccc' }}>{e.metric_value}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#ccc' }}>{e.threshold}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937' }}>
                  <span style={{ display: 'inline-block', padding: '2px 6px', borderRadius: 3, fontSize: 11, background: sevColor(e.severity), color: 'white' }}>{e.severity}</span>
                </td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#ccc', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>{e.message}</td>
              </tr>
            ))}</tbody>
          </table>
          {history.length === 0 && (
            <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>暂无告警记录</div>
          )}
        </div>
      )}
    </div>
  );
}
