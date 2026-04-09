import { useState, useEffect } from 'react';

interface MetricsSummary {
  audit_stats: {
    total_events: number;
    active_users: number;
    events_by_action: Record<string, number>;
    events_by_status: Record<string, number>;
    daily_counts: Array<{ date: string; count: number }>;
  };
  user_count: number;
}

interface UserInfo {
  id: number;
  username: string;
  display_name: string;
  role: string;
  auth_provider: string;
  created_at: string;
}

interface AuditEntry {
  id: number;
  username: string;
  action: string;
  status: string;
  details: any;
  created_at: string;
}

interface AdminDashboardProps {
  onBack: () => void;
}

export default function AdminDashboard({ onBack }: AdminDashboardProps) {
  const [activeSection, setActiveSection] = useState<'metrics' | 'users' | 'audit' | 'system' | 'bots' | 'a2a' | 'models'>('metrics');

  return (
    <div className="admin-dashboard">
      <div className="admin-header">
        <button className="admin-back-btn" onClick={onBack}>&larr; 返回</button>
        <h2>管理后台</h2>
        <div className="admin-nav">
          <button className={activeSection === 'metrics' ? 'active' : ''}
            onClick={() => setActiveSection('metrics')}>系统指标</button>
          <button className={activeSection === 'system' ? 'active' : ''}
            onClick={() => setActiveSection('system')}>系统状态</button>
          <button className={activeSection === 'bots' ? 'active' : ''}
            onClick={() => setActiveSection('bots')}>Bot 管理</button>
          <button className={activeSection === 'a2a' ? 'active' : ''}
            onClick={() => setActiveSection('a2a')}>A2A</button>
          <button className={activeSection === 'models' ? 'active' : ''}
            onClick={() => setActiveSection('models')}>模型配置</button>
          <button className={activeSection === 'users' ? 'active' : ''}
            onClick={() => setActiveSection('users')}>用户管理</button>
          <button className={activeSection === 'audit' ? 'active' : ''}
            onClick={() => setActiveSection('audit')}>审计日志</button>
        </div>
      </div>
      <div className="admin-content">
        {activeSection === 'metrics' && <MetricsSection />}
        {activeSection === 'system' && <SystemStatusSection />}
        {activeSection === 'bots' && <BotsSection />}
        {activeSection === 'a2a' && <A2ASection />}
        {activeSection === 'models' && <ModelsSection />}
        {activeSection === 'users' && <UsersSection />}
        {activeSection === 'audit' && <AuditSection />}
      </div>
    </div>
  );
}

function MetricsSection() {
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/admin/metrics/summary', { credentials: 'include' })
      .then((r) => r.json())
      .then(setMetrics)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="admin-loading">加载中...</div>;
  if (!metrics) return <div className="admin-loading">无法加载指标数据</div>;

  const stats = metrics.audit_stats;
  const pipelineActions = stats.events_by_action || {};
  const maxCount = Math.max(...Object.values(pipelineActions), 1);

  return (
    <div className="metrics-section">
      <div className="metrics-cards">
        <div className="metric-card">
          <div className="metric-value">{stats.total_events}</div>
          <div className="metric-label">总事件数 (30天)</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{stats.active_users}</div>
          <div className="metric-label">活跃用户</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{metrics.user_count}</div>
          <div className="metric-label">注册用户</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{pipelineActions['pipeline_complete'] || 0}</div>
          <div className="metric-label">管线执行</div>
        </div>
      </div>

      <div className="metrics-chart-section">
        <h3>事件分布</h3>
        <div className="bar-chart">
          {Object.entries(pipelineActions).slice(0, 10).map(([action, count]) => (
            <div key={action} className="bar-chart-row">
              <span className="bar-label">{action}</span>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${(count / maxCount) * 100}%` }} />
              </div>
              <span className="bar-value">{count}</span>
            </div>
          ))}
        </div>
      </div>

      {stats.daily_counts && stats.daily_counts.length > 0 && (
        <div className="metrics-chart-section">
          <h3>每日事件趋势</h3>
          <div className="daily-chart">
            {stats.daily_counts.slice(-14).map((d) => {
              const maxDaily = Math.max(...stats.daily_counts.map((x) => x.count), 1);
              return (
                <div key={d.date} className="daily-bar-col">
                  <div className="daily-bar" style={{ height: `${(d.count / maxDaily) * 100}%` }} title={`${d.date}: ${d.count}`} />
                  <span className="daily-label">{d.date.slice(5)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function UsersSection() {
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchUsers = () => {
    setLoading(true);
    fetch('/api/admin/users', { credentials: 'include' })
      .then((r) => r.json())
      .then((data) => setUsers(data.users || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchUsers(); }, []);

  const updateRole = async (username: string, role: string) => {
    const resp = await fetch(`/api/admin/users/${username}/role`, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    });
    if (resp.ok) fetchUsers();
  };

  const deleteUser = async (username: string) => {
    if (!confirm(`确定删除用户 ${username}?`)) return;
    const resp = await fetch(`/api/admin/users/${username}`, {
      method: 'DELETE',
      credentials: 'include',
    });
    if (resp.ok) fetchUsers();
  };

  if (loading) return <div className="admin-loading">加载中...</div>;

  return (
    <div className="users-section">
      <div className="data-table-container">
        <table className="data-table admin-table">
          <thead>
            <tr>
              <th>用户名</th>
              <th>显示名</th>
              <th>角色</th>
              <th>认证</th>
              <th>注册时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.username}</td>
                <td>{u.display_name || '-'}</td>
                <td>
                  <select
                    value={u.role}
                    onChange={(e) => updateRole(u.username, e.target.value)}
                    className="role-select"
                  >
                    <option value="admin">admin</option>
                    <option value="analyst">analyst</option>
                    <option value="viewer">viewer</option>
                  </select>
                </td>
                <td>{u.auth_provider}</td>
                <td>{u.created_at ? new Date(u.created_at).toLocaleDateString() : '-'}</td>
                <td>
                  <button className="delete-btn" onClick={() => deleteUser(u.username)}>删除</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ============================================================
   System Status Section
   ============================================================ */

function SystemStatusSection() {
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/system/status', { credentials: 'include' })
      .then(r => r.json())
      .then(setStatus)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="admin-loading">加载中...</div>;
  if (!status) return <div className="admin-loading">无法加载系统状态</div>;

  const StatusIcon = ({ ok }: { ok: boolean }) => (
    <span style={{ color: ok ? '#16a34a' : '#dc2626', fontWeight: 700 }}>{ok ? '✓' : '✗'}</span>
  );

  return (
    <div className="metrics-section">
      <div className="metrics-cards">
        <div className="metric-card">
          <div className="metric-value"><StatusIcon ok={status.database?.status === 'ok'} /> 数据库</div>
          <div className="metric-label">{status.database?.status === 'ok' ? `${status.database.latency_ms}ms` : '未连接'}</div>
        </div>
        <div className="metric-card">
          <div className="metric-value"><StatusIcon ok={status.mcp_hub?.status === 'ok'} /> MCP Hub</div>
          <div className="metric-label">{status.mcp_hub?.connected || 0}/{status.mcp_hub?.total || 0} 服务器</div>
        </div>
        <div className="metric-card">
          <div className="metric-value"><StatusIcon ok={status.features?.arcpy} /> ArcPy</div>
          <div className="metric-label">{status.features?.arcpy ? '可用' : '未配置'}</div>
        </div>
        <div className="metric-card">
          <div className="metric-value"><StatusIcon ok={status.features?.cloud_storage} /> 云存储</div>
          <div className="metric-label">{status.features?.cloud_storage ? '已连接' : '未配置'}</div>
        </div>
      </div>

      <div className="metrics-chart-section">
        <h3>模型配置</h3>
        <div className="data-table-container">
          <table className="data-table admin-table">
            <thead><tr><th>模型等级</th><th>当前模型</th></tr></thead>
            <tbody>
              {status.models && Object.entries(status.models).map(([tier, model]) => (
                <tr key={tier}><td style={{ fontWeight: 600 }}>{tier}</td><td>{model as string}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="metrics-chart-section">
        <h3>功能特性</h3>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {status.features && Object.entries(status.features).map(([k, v]) => (
            <span key={k} style={{
              padding: '3px 10px', borderRadius: 12, fontSize: 12, fontWeight: 500,
              background: v ? '#dcfce7' : '#fee2e2', color: v ? '#166534' : '#991b1b',
            }}>
              {k}: {v ? 'ON' : 'OFF'}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   Bots Section
   ============================================================ */

function BotsSection() {
  const [bots, setBots] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/bots/status', { credentials: 'include' })
      .then(r => r.json())
      .then(data => setBots(data.bots || {}))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="admin-loading">加载中...</div>;
  if (!bots) return <div className="admin-loading">无法加载 Bot 状态</div>;

  const platforms = [
    { key: 'wecom', icon: '💬', color: '#07c160' },
    { key: 'dingtalk', icon: '🔵', color: '#0089ff' },
    { key: 'feishu', icon: '🟣', color: '#5c6bc0' },
  ];

  return (
    <div className="metrics-section">
      <div className="metrics-cards">
        {platforms.map(p => {
          const bot = bots[p.key];
          if (!bot) return null;
          return (
            <div key={p.key} className="metric-card" style={{ borderLeft: `4px solid ${bot.configured ? p.color : '#e5e7eb'}` }}>
              <div className="metric-value">{p.icon} {bot.label}</div>
              <div className="metric-label" style={{ color: bot.configured ? '#16a34a' : '#dc2626' }}>
                {bot.configured ? '✓ 已配置' : '✗ 未配置'}
              </div>
              <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>
                环境变量: {bot.configured_keys}/{bot.total_env_keys}
              </div>
              {bot.missing_keys && bot.missing_keys.length > 0 && (
                <div style={{ fontSize: 10, color: '#dc2626', marginTop: 4 }}>
                  缺失: {bot.missing_keys.join(', ')}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="metrics-chart-section">
        <h3>配置说明</h3>
        <p style={{ fontSize: 12, color: '#6b7280', lineHeight: 1.6 }}>
          Bot 通过环境变量配置。在 <code>data_agent/.env</code> 中设置对应平台的密钥，
          重启应用后自动激活。Bot 接收用户消息 → 语义路由 → 管线执行 → 结果推送回平台。
        </p>
      </div>
    </div>
  );
}

/* ============================================================
   A2A Section
   ============================================================ */

function A2ASection() {
  const [card, setCard] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch('/api/a2a/card', { credentials: 'include' }).then(r => r.json()).catch(() => null),
      fetch('/api/a2a/status', { credentials: 'include' }).then(r => r.json()).catch(() => null),
    ]).then(([c, s]) => {
      setCard(c);
      setStatus(s);
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="admin-loading">加载中...</div>;

  return (
    <div className="metrics-section">
      <div className="metrics-cards">
        <div className="metric-card">
          <div className="metric-value">{status?.enabled ? '✓ 已启用' : '✗ 未启用'}</div>
          <div className="metric-label">A2A 服务</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{status?.uptime_seconds ? `${Math.round(status.uptime_seconds / 60)}分钟` : '-'}</div>
          <div className="metric-label">运行时间</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{card?.skills?.length || 0}</div>
          <div className="metric-label">暴露技能数</div>
        </div>
      </div>

      {card && (
        <div className="metrics-chart-section">
          <h3>Agent Card</h3>
          <div style={{ padding: 12, background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0' }}>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>{card.name}</div>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>{card.description}</div>
            <div style={{ fontSize: 11, color: '#9ca3af' }}>
              协议: {card.protocol_version} | Streaming: {card.capabilities?.streaming ? 'Yes' : 'No'}
            </div>
          </div>

          <h3 style={{ marginTop: 16 }}>暴露的技能</h3>
          {(card.skills || []).map((s: any) => (
            <div key={s.id} style={{
              padding: '8px 12px', marginBottom: 4, background: '#fff',
              border: '1px solid #e2e8f0', borderRadius: 6,
            }}>
              <div style={{ fontWeight: 500, fontSize: 13 }}>{s.name}</div>
              <div style={{ fontSize: 11, color: '#6b7280' }}>{s.description}</div>
            </div>
          ))}
        </div>
      )}

      <div className="metrics-chart-section">
        <h3>配置说明</h3>
        <p style={{ fontSize: 12, color: '#6b7280', lineHeight: 1.6 }}>
          A2A (Agent-to-Agent) 允许外部 Agent 通过标准协议发现和调用 Data Agent 的能力。
          设置 <code>A2A_ENABLED=true</code> 环境变量启用。启用后，外部 Agent 可通过
          <code>/api/a2a/card</code> 发现能力，通过 <code>/api/a2a/tasks/send</code> 提交任务。
        </p>
      </div>
    </div>
  );
}

/* ============================================================
   Models Configuration Section
   ============================================================ */

function ModelsSection() {
  const [config, setConfig] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [showCustom, setShowCustom] = useState(false);
  const [customForm, setCustomForm] = useState({ name: '', backend: 'litellm', api_base: '', tier: 'standard' });
  const [msg, setMsg] = useState('');

  const loadConfig = () => {
    fetch('/api/admin/model-config', { credentials: 'include' })
      .then(r => r.json())
      .then(data => { setConfig(data); setEdits({}); })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadConfig(); }, []);

  if (loading) return <div className="admin-loading">加载中...</div>;
  if (!config) return <div className="admin-loading">无法加载模型配置</div>;

  const tierLabels: Record<string, string> = {
    fast: 'Fast（低成本快速）',
    standard: 'Standard（平衡）',
    premium: 'Premium（复杂推理）',
  };
  const tierUsage: Record<string, string> = {
    fast: '路由器、数据探查、质量检查',
    standard: '数据处理、分析、可视化',
    premium: '治理报告、复杂推理',
  };

  const availableModels: string[] = (config.available_models || []).map((m: any) => m.name);

  const handleTierChange = (tier: string, model: string) => {
    setEdits(prev => ({ ...prev, [`tier_${tier}`]: model }));
  };
  const handleRouterChange = (model: string) => {
    setEdits(prev => ({ ...prev, router_model: model }));
  };

  const handleSave = async () => {
    setSaving(true);
    setMsg('');
    try {
      for (const [key, value] of Object.entries(edits)) {
        if (key.startsWith('tier_')) {
          const tier = key.replace('tier_', '');
          await fetch('/api/admin/model-config', {
            method: 'PUT', credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tier, model: value }),
          });
        } else if (key === 'router_model') {
          await fetch('/api/admin/model-config', {
            method: 'PUT', credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ router_model: value }),
          });
        }
      }
      setMsg('保存成功。Router 立即生效，Agent 层级需重启生效。');
      loadConfig();
    } catch { setMsg('保存失败'); }
    setSaving(false);
  };

  const handleAddCustom = async () => {
    if (!customForm.name) return;
    const resp = await fetch('/api/admin/model-config/custom', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(customForm),
    });
    if (resp.ok) {
      setMsg(`已注册自定义模型: ${customForm.name}`);
      setCustomForm({ name: '', backend: 'litellm', api_base: '', tier: 'standard' });
      setShowCustom(false);
      loadConfig();
    } else {
      const err = await resp.json();
      setMsg(`注册失败: ${err.error || '未知错误'}`);
    }
  };

  const hasEdits = Object.keys(edits).length > 0;

  return (
    <div>
      <h3>LLM 模型配置</h3>
      <p style={{ fontSize: 12, color: '#6b7280', marginBottom: 12 }}>
        配置各层级使用的 LLM 模型。支持 Gemini、Gemma、LiteLLM 兼容模型。
      </p>

      <div className="data-table-container">
        <table className="data-table admin-table">
          <thead>
            <tr><th>层级</th><th>当前模型</th><th>用途</th></tr>
          </thead>
          <tbody>
            {Object.entries(config.tiers || {}).map(([tier, info]: [string, any]) => (
              <tr key={tier}>
                <td style={{ fontWeight: 600 }}>{tierLabels[tier] || tier}</td>
                <td>
                  <select
                    value={edits[`tier_${tier}`] || info.model}
                    onChange={e => handleTierChange(tier, e.target.value)}
                    style={{ fontSize: 12, padding: '4px 8px', borderRadius: 4, border: '1px solid #d1d5db', width: '100%' }}
                  >
                    {availableModels.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                </td>
                <td style={{ fontSize: 11, color: '#6b7280' }}>{tierUsage[tier]}</td>
              </tr>
            ))}
            <tr>
              <td style={{ fontWeight: 600 }}>Router（意图路由）</td>
              <td>
                <select
                  value={edits.router_model || config.router_model}
                  onChange={e => handleRouterChange(e.target.value)}
                  style={{ fontSize: 12, padding: '4px 8px', borderRadius: 4, border: '1px solid #d1d5db', width: '100%' }}
                >
                  {availableModels.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              </td>
              <td style={{ fontSize: 11, color: '#6b7280' }}>语义意图分类</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
        <button onClick={handleSave} disabled={!hasEdits || saving}
          style={{ padding: '6px 16px', borderRadius: 6, background: hasEdits ? '#3b82f6' : '#d1d5db',
                   color: '#fff', border: 'none', cursor: hasEdits ? 'pointer' : 'default', fontSize: 13 }}>
          {saving ? '保存中...' : '保存配置'}
        </button>
        <button onClick={() => setShowCustom(!showCustom)}
          style={{ padding: '6px 16px', borderRadius: 6, background: '#f1f5f9',
                   border: '1px solid #d1d5db', cursor: 'pointer', fontSize: 13 }}>
          {showCustom ? '取消' : '添加自定义模型'}
        </button>
        {msg && <span style={{ fontSize: 12, color: msg.includes('失败') ? '#ef4444' : '#22c55e' }}>{msg}</span>}
      </div>

      {showCustom && (
        <div style={{ marginTop: 12, padding: 12, background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 12 }}>
            <label>模型名称
              <input value={customForm.name} onChange={e => setCustomForm(p => ({ ...p, name: e.target.value }))}
                placeholder="e.g. gemma-4-31b-it-vllm" style={{ width: '100%', padding: 4, borderRadius: 4, border: '1px solid #d1d5db' }} />
            </label>
            <label>Backend
              <select value={customForm.backend} onChange={e => setCustomForm(p => ({ ...p, backend: e.target.value }))}
                style={{ width: '100%', padding: 4, borderRadius: 4, border: '1px solid #d1d5db' }}>
                <option value="gemini">Gemini API</option>
                <option value="litellm">LiteLLM</option>
                <option value="lm_studio">LM Studio</option>
              </select>
            </label>
            <label>API Base URL (可选)
              <input value={customForm.api_base} onChange={e => setCustomForm(p => ({ ...p, api_base: e.target.value }))}
                placeholder="https://your-endpoint/v1" style={{ width: '100%', padding: 4, borderRadius: 4, border: '1px solid #d1d5db' }} />
            </label>
            <label>层级
              <select value={customForm.tier} onChange={e => setCustomForm(p => ({ ...p, tier: e.target.value }))}
                style={{ width: '100%', padding: 4, borderRadius: 4, border: '1px solid #d1d5db' }}>
                <option value="fast">Fast</option>
                <option value="standard">Standard</option>
                <option value="premium">Premium</option>
                <option value="local">Local</option>
              </select>
            </label>
          </div>
          <button onClick={handleAddCustom} style={{ marginTop: 8, padding: '4px 12px', borderRadius: 4,
            background: '#3b82f6', color: '#fff', border: 'none', cursor: 'pointer', fontSize: 12 }}>
            注册模型
          </button>
        </div>
      )}
    </div>
  );
}

function AuditSection() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(7);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/admin/audit?days=${days}&limit=100`, { credentials: 'include' })
      .then((r) => r.json())
      .then((data) => setEntries(data.entries || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [days]);

  if (loading) return <div className="admin-loading">加载中...</div>;

  return (
    <div className="audit-section">
      <div className="history-filter" style={{ marginBottom: 12 }}>
        {[7, 30, 90].map((d) => (
          <button key={d} className={`history-range-btn ${days === d ? 'active' : ''}`}
            onClick={() => setDays(d)}>{d}天</button>
        ))}
      </div>
      <div className="data-table-container">
        <table className="data-table admin-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>用户</th>
              <th>操作</th>
              <th>状态</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <td>{e.created_at ? new Date(e.created_at).toLocaleString() : '-'}</td>
                <td>{e.username}</td>
                <td>{e.action}</td>
                <td><span className={`status-badge ${e.status}`}>{e.status}</span></td>
                <td title={JSON.stringify(e.details)}>
                  {e.details ? JSON.stringify(e.details).slice(0, 60) : '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
