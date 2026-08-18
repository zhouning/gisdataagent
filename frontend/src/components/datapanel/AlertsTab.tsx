import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { formatDate, formatNumber, getLocaleHeaders } from '../../i18n';

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
  { value: 'qc_score', labelKey: 'qcScore' },
  { value: 'defect_count', labelKey: 'defectCount' },
  { value: 'sla_violation_rate', labelKey: 'slaViolationRate' },
  { value: 'review_pending_count', labelKey: 'pendingReviews' },
];

const EMPTY_RULE = {
  name: '', metric_name: 'qc_score', condition: 'gt',
  threshold: 0, severity: 'warning', channel: 'webhook', webhook_url: '',
};

export default function AlertsTab() {
  const { t } = useTranslation();
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [history, setHistory] = useState<AlertEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ ...EMPTY_RULE });
  const [activeView, setActiveView] = useState<'rules' | 'history'>('rules');

  const fetchRules = async () => {
    try {
      const r = await fetch('/api/alert-rules', { credentials: 'include', headers: getLocaleHeaders() });
      if (r.ok) { const d = await r.json(); setRules(d.rules || []); }
    } catch { /* endpoint may not exist yet */ }
  };

  const fetchHistory = async () => {
    try {
      const r = await fetch('/api/alert-history?limit=20', { credentials: 'include', headers: getLocaleHeaders() });
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
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (r.ok) { setShowForm(false); setForm({ ...EMPTY_RULE }); fetchRules(); }
    } catch { /* ignore */ }
  };

  const toggleRule = async (id: number, enabled: boolean) => {
    try {
      await fetch(`/api/alert-rules/${id}`, {
        method: 'PUT', credentials: 'include',
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !enabled }),
      });
      fetchRules();
    } catch { /* ignore */ }
  };

  const deleteRule = async (id: number) => {
    if (!confirm(t('alertCenter.confirm.deleteRule'))) return;
    try {
      await fetch(`/api/alert-rules/${id}`, { method: 'DELETE', credentials: 'include', headers: getLocaleHeaders() });
      fetchRules();
    } catch { /* ignore */ }
  };

  const sevColor = (s: string) =>
    s === 'critical' ? '#e53935' : s === 'warning' ? '#fb8c00' : '#1a73e8';

  const condLabel = (c: string) =>
    ({ gt: '>', gte: '≥', lt: '<', lte: '≤', eq: '=' }[c] || c);

  const metricLabel = (metric: string) => {
    const option = METRIC_OPTIONS.find(item => item.value === metric);
    return option ? t(`alertCenter.metrics.${option.labelKey}`) : metric;
  };

  const severityLabel = (severity: string) => t(`alertCenter.severity.${severity}`, { defaultValue: severity });
  const channelLabel = (channel: string) => t(`alertCenter.channels.${channel}`, { defaultValue: channel });

  if (loading) return <div style={{ padding: 12, color: '#888' }}>{t('alertCenter.common.loading')}</div>;

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
            {t(`alertCenter.tabs.${v}`)}
          </button>
        ))}
        {activeView === 'rules' && (
          <button onClick={() => setShowForm(!showForm)} style={{
            marginInlineStart: 'auto', padding: '4px 12px', fontSize: 12, borderRadius: 4,
            border: 'none', background: '#1a73e8', color: 'white', cursor: 'pointer',
          }}>+ {t('alertCenter.actions.newRule')}</button>
        )}
      </div>

      {/* Create rule form */}
      {showForm && activeView === 'rules' && (
        <div style={{ background: '#1a1a2e', border: '1px solid #333', borderRadius: 6, padding: 12, marginBottom: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: '#e0e0e0' }}>{t('alertCenter.form.title')}</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
            <input placeholder={t('alertCenter.form.namePlaceholder')} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontSize: 12 }} />
            <select value={form.metric_name} onChange={e => setForm({ ...form, metric_name: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontSize: 12 }}>
              {METRIC_OPTIONS.map(metric => <option key={metric.value} value={metric.value}>{t(`alertCenter.metrics.${metric.labelKey}`)}</option>)}
            </select>
          </div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <select value={form.condition} onChange={e => setForm({ ...form, condition: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontSize: 12 }}>
              <option value="gt">&gt;</option><option value="lt">&lt;</option>
              <option value="gte">≥</option><option value="lte">≤</option>
              <option value="eq">=</option>
            </select>
            <input type="number" placeholder={t('alertCenter.form.thresholdPlaceholder')} value={form.threshold}
              onChange={e => setForm({ ...form, threshold: Number(e.target.value) })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontSize: 12, width: 80 }} />
            <select value={form.severity} onChange={e => setForm({ ...form, severity: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontSize: 12 }}>
              <option value="info">{t('alertCenter.severity.info')}</option><option value="warning">{t('alertCenter.severity.warning')}</option><option value="critical">{t('alertCenter.severity.critical')}</option>
            </select>
            <select value={form.channel} onChange={e => setForm({ ...form, channel: e.target.value })}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontSize: 12 }}>
              <option value="webhook">{t('alertCenter.channels.webhook')}</option><option value="email">{t('alertCenter.channels.email')}</option>
            </select>
          </div>
          {form.channel === 'webhook' && (
            <input placeholder={t('alertCenter.form.webhookPlaceholder')} value={form.webhook_url}
              onChange={e => setForm({ ...form, webhook_url: e.target.value })}
              style={{ width: '100%', background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontSize: 12, marginBottom: 8, boxSizing: 'border-box' }} />
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={createRule} style={{ padding: '4px 12px', borderRadius: 4, border: 'none', background: '#43a047', color: 'white', cursor: 'pointer', fontSize: 12 }}>{t('alertCenter.actions.save')}</button>
            <button onClick={() => setShowForm(false)} style={{ padding: '4px 12px', borderRadius: 4, border: '1px solid #444', color: '#aaa', background: 'transparent', cursor: 'pointer', fontSize: 12 }}>{t('alertCenter.actions.cancel')}</button>
          </div>
        </div>
      )}

      {/* Rules table */}
      {activeView === 'rules' && (
        <div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ background: '#1f2937' }}>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('alertCenter.table.name')}</th>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('alertCenter.table.metric')}</th>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('alertCenter.table.condition')}</th>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('alertCenter.table.severity')}</th>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('alertCenter.table.channel')}</th>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('alertCenter.table.enabled')}</th>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('alertCenter.table.actions')}</th>
            </tr></thead>
            <tbody>{rules.map(r => (
              <tr key={r.id}>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#ccc' }}>{r.name}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#7dd3fc' }}>{metricLabel(r.metric_name)}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#ccc' }}>{condLabel(r.condition)} {formatNumber(r.threshold, { maximumFractionDigits: 4 })}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937' }}>
                  <span style={{ display: 'inline-block', padding: '2px 6px', borderRadius: 3, fontSize: 11, background: sevColor(r.severity), color: 'white' }}>{severityLabel(r.severity)}</span>
                </td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#aaa' }}>{channelLabel(r.channel)}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937' }}>
                  <button onClick={() => toggleRule(r.id, r.enabled)}
                    style={{ fontSize: 11, color: r.enabled ? '#10b981' : '#888', background: 'none', border: 'none', cursor: 'pointer' }}>
                    {r.enabled ? t('alertCenter.common.enabled') : t('alertCenter.common.disabled')}
                  </button>
                </td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937' }}>
                  <button onClick={() => deleteRule(r.id)}
                    style={{ padding: '2px 8px', borderRadius: 3, border: '1px solid #e53935', color: '#e53935', background: 'transparent', cursor: 'pointer', fontSize: 11 }}>{t('alertCenter.actions.delete')}</button>
                </td>
              </tr>
            ))}</tbody>
          </table>
          {rules.length === 0 && !showForm && (
            <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>{t('alertCenter.empty.rules')}</div>
          )}
        </div>
      )}

      {/* Alert history */}
      {activeView === 'history' && (
        <div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ background: '#1f2937' }}>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('alertCenter.table.time')}</th>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('alertCenter.table.metric')}</th>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('alertCenter.table.value')}</th>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('alertCenter.table.threshold')}</th>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('alertCenter.table.severity')}</th>
              <th style={{ padding: '6px 8px', textAlign: 'start', color: '#aaa' }}>{t('alertCenter.table.message')}</th>
            </tr></thead>
            <tbody>{history.map(e => (
              <tr key={e.id}>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', whiteSpace: 'nowrap', color: '#aaa' }}>{formatDate(e.created_at, { dateStyle: 'medium', timeStyle: 'short' })}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#7dd3fc' }}>{metricLabel(e.metric_name)}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#ccc' }}>{formatNumber(e.metric_value, { maximumFractionDigits: 4 })}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#ccc' }}>{formatNumber(e.threshold, { maximumFractionDigits: 4 })}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937' }}>
                  <span style={{ display: 'inline-block', padding: '2px 6px', borderRadius: 3, fontSize: 11, background: sevColor(e.severity), color: 'white' }}>{severityLabel(e.severity)}</span>
                </td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #1f2937', color: '#ccc', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>{e.message}</td>
              </tr>
            ))}</tbody>
          </table>
          {history.length === 0 && (
            <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>{t('alertCenter.empty.history')}</div>
          )}
        </div>
      )}
    </div>
  );
}
