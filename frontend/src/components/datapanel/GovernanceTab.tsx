import { useState, useEffect } from 'react';

interface QualityRule {
  id: number;
  rule_name: string;
  rule_type: string;
  standard_id: string | null;
  severity: string;
  enabled: boolean;
  owner_username: string;
  is_shared: boolean;
}

interface TrendPoint {
  asset_name: string;
  score: number;
  created_at: string;
}

interface ResourceOverview {
  total_assets: number;
  type_distribution: Record<string, number>;
  total_rules: number;
  enabled_rules: number;
  recent_scores: Array<{ asset: string; score: number; date: string }>;
}

const EMPTY_RULE = {
  rule_name: '', rule_type: 'field_check', standard_id: '',
  config: '{}', severity: 'HIGH', is_shared: false,
};

export default function GovernanceTab() {
  const [section, setSection] = useState<'rules' | 'trends' | 'overview'>('overview');
  const [rules, setRules] = useState<QualityRule[]>([]);
  const [trends, setTrends] = useState<TrendPoint[]>([]);
  const [overview, setOverview] = useState<ResourceOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ ...EMPTY_RULE });
  const [formError, setFormError] = useState('');

  const fetchRules = async () => {
    try {
      const r = await fetch('/api/quality-rules', { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setRules(d.rules || []); }
    } catch { /* ignore */ }
  };

  const fetchTrends = async () => {
    try {
      const r = await fetch('/api/quality-trends?days=30', { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setTrends(d.trends || []); }
    } catch { /* ignore */ }
  };

  const fetchOverview = async () => {
    try {
      const r = await fetch('/api/resource-overview', { credentials: 'include' });
      if (r.ok) { const d = await r.json(); setOverview(d); }
    } catch { /* ignore */ }
  };

  useEffect(() => {
    setLoading(true);
    Promise.all([fetchRules(), fetchTrends(), fetchOverview()]).finally(() => setLoading(false));
  }, []);

  const handleSaveRule = async () => {
    if (!form.rule_name) { setFormError('规则名称不能为空'); return; }
    let config = {};
    try { config = JSON.parse(form.config); } catch { setFormError('配置JSON格式错误'); return; }
    const body = { ...form, config };
    const r = await fetch('/api/quality-rules', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (r.ok) { setShowForm(false); fetchRules(); }
    else { const d = await r.json(); setFormError(d.error || '创建失败'); }
  };

  const handleDeleteRule = async (id: number) => {
    if (!confirm('确定删除此规则？')) return;
    await fetch(`/api/quality-rules/${id}`, { method: 'DELETE', credentials: 'include' });
    fetchRules();
  };

  const handleToggleRule = async (id: number, enabled: boolean) => {
    await fetch(`/api/quality-rules/${id}`, {
      method: 'PUT', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !enabled }),
    });
    fetchRules();
  };

  const sevColor = (s: string) => {
    if (s === 'CRITICAL') return '#ef4444';
    if (s === 'HIGH') return '#f59e0b';
    if (s === 'MEDIUM') return '#3b82f6';
    return '#888';
  };

  if (loading) return <div style={{ padding: 16, color: '#888' }}>加载中...</div>;

  return (
    <div style={{ padding: '8px 12px', fontSize: 13 }}>
      {/* Section switcher */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 10 }}>
        {(['overview', 'rules', 'trends'] as const).map(s => (
          <button key={s} onClick={() => setSection(s)}
            style={{
              padding: '4px 12px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
              background: section === s ? '#1e3a5f' : '#111827',
              color: section === s ? '#7dd3fc' : '#888',
              border: `1px solid ${section === s ? '#2563eb' : '#333'}`,
            }}>
            {s === 'overview' ? '资源总览' : s === 'rules' ? '质量规则' : '质量趋势'}
          </button>
        ))}
      </div>

      {/* Overview section */}
      {section === 'overview' && overview && (
        <div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 12 }}>
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#7dd3fc' }}>{overview.total_assets}</div>
              <div style={{ color: '#888', fontSize: 11 }}>数据资产</div>
            </div>
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#10b981' }}>{overview.enabled_rules}</div>
              <div style={{ color: '#888', fontSize: 11 }}>启用规则</div>
            </div>
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#f59e0b' }}>{overview.total_rules}</div>
              <div style={{ color: '#888', fontSize: 11 }}>总规则数</div>
            </div>
          </div>
          {Object.keys(overview.type_distribution).length > 0 && (
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12, marginBottom: 8 }}>
              <div style={{ fontWeight: 600, marginBottom: 6, color: '#e0e0e0' }}>资产类型分布</div>
              {Object.entries(overview.type_distribution).map(([type, count]) => (
                <div key={type} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', color: '#aaa', fontSize: 12 }}>
                  <span>{type}</span><span style={{ color: '#7dd3fc' }}>{count}</span>
                </div>
              ))}
            </div>
          )}
          {overview.recent_scores.length > 0 && (
            <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: 12 }}>
              <div style={{ fontWeight: 600, marginBottom: 6, color: '#e0e0e0' }}>最近质量评分</div>
              {overview.recent_scores.map((s, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', fontSize: 12 }}>
                  <span style={{ color: '#aaa' }}>{s.asset}</span>
                  <span style={{ color: s.score >= 80 ? '#10b981' : s.score >= 60 ? '#f59e0b' : '#ef4444', fontWeight: 600 }}>{s.score}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Rules section */}
      {section === 'rules' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontWeight: 600 }}>质量规则 ({rules.length})</span>
            <button className="btn-primary btn-sm" onClick={() => { setForm({ ...EMPTY_RULE }); setFormError(''); setShowForm(true); }}
              style={{ fontSize: 12, padding: '2px 10px' }}>+ 新增</button>
          </div>
          {showForm && (
            <div style={{ background: '#1a1a2e', border: '1px solid #333', borderRadius: 6, padding: 12, marginBottom: 10 }}>
              <div style={{ display: 'grid', gap: 8 }}>
                <input placeholder="规则名称" value={form.rule_name} onChange={e => setForm({ ...form, rule_name: e.target.value })}
                  style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
                <div style={{ display: 'flex', gap: 8 }}>
                  <select value={form.rule_type} onChange={e => setForm({ ...form, rule_type: e.target.value })}
                    style={{ flex: 1, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }}>
                    <option value="field_check">字段检查</option>
                    <option value="formula">公式校验</option>
                    <option value="topology">拓扑检查</option>
                    <option value="completeness">完整性</option>
                  </select>
                  <select value={form.severity} onChange={e => setForm({ ...form, severity: e.target.value })}
                    style={{ flex: 1, background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }}>
                    <option value="CRITICAL">严重</option>
                    <option value="HIGH">高</option>
                    <option value="MEDIUM">中</option>
                    <option value="LOW">低</option>
                  </select>
                </div>
                <input placeholder="标准ID (如 dltb_2023)" value={form.standard_id} onChange={e => setForm({ ...form, standard_id: e.target.value })}
                  style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0' }} />
                <textarea placeholder='规则配置 JSON (如 {"standard_id":"dltb_2023"})' value={form.config}
                  onChange={e => setForm({ ...form, config: e.target.value })} rows={2}
                  style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '4px 8px', color: '#e0e0e0', fontFamily: 'monospace', fontSize: 12 }} />
              </div>
              {formError && <div style={{ color: '#ef4444', fontSize: 12, marginTop: 6 }}>{formError}</div>}
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <button className="btn-primary btn-sm" onClick={handleSaveRule} style={{ fontSize: 12 }}>创建</button>
                <button className="btn-secondary btn-sm" onClick={() => setShowForm(false)} style={{ fontSize: 12 }}>取消</button>
              </div>
            </div>
          )}
          {rules.map(r => (
            <div key={r.id} style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 6, padding: '8px 12px', marginBottom: 6 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <span style={{ fontWeight: 600, color: r.enabled ? '#e0e0e0' : '#666' }}>{r.rule_name}</span>
                  <span style={{ marginLeft: 8, fontSize: 11, padding: '1px 6px', borderRadius: 3, background: '#1e3a5f', color: '#7dd3fc' }}>{r.rule_type}</span>
                  <span style={{ marginLeft: 6, fontSize: 11, color: sevColor(r.severity) }}>{r.severity}</span>
                  {r.standard_id && <span style={{ marginLeft: 6, fontSize: 11, color: '#888' }}>{r.standard_id}</span>}
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button onClick={() => handleToggleRule(r.id, r.enabled)}
                    style={{ fontSize: 11, color: r.enabled ? '#10b981' : '#888', background: 'none', border: 'none', cursor: 'pointer' }}>
                    {r.enabled ? '启用' : '禁用'}
                  </button>
                  <button onClick={() => handleDeleteRule(r.id)}
                    style={{ fontSize: 11, color: '#ef4444', background: 'none', border: 'none', cursor: 'pointer' }}>删除</button>
                </div>
              </div>
            </div>
          ))}
          {rules.length === 0 && !showForm && (
            <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>暂无质量规则</div>
          )}
        </div>
      )}

      {/* Trends section */}
      {section === 'trends' && (
        <div>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>质量趋势（近 30 天）</div>
          {trends.length === 0 ? (
            <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>暂无质量趋势数据</div>
          ) : (
            <div style={{ maxHeight: 400, overflow: 'auto' }}>
              {trends.map((t, i) => (
                <div key={i} style={{
                  background: '#111827', border: '1px solid #1f2937', borderRadius: 6,
                  padding: '8px 12px', marginBottom: 4, display: 'flex', justifyContent: 'space-between',
                }}>
                  <div>
                    <span style={{ color: '#e0e0e0', fontWeight: 600 }}>{t.asset_name}</span>
                    <span style={{ marginLeft: 8, fontSize: 11, color: '#888' }}>
                      {new Date(t.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  <span style={{
                    fontWeight: 700, fontSize: 16,
                    color: t.score >= 80 ? '#10b981' : t.score >= 60 ? '#f59e0b' : '#ef4444',
                  }}>{t.score}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
