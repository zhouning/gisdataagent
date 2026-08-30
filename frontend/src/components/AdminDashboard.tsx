import { useState, useEffect } from 'react';
import { Bell, Play, RefreshCw, RotateCcw, Save, Settings2 } from 'lucide-react';
import { usePlatformBranding } from '../platformBranding';
import NavigationSettingsSection from './NavigationSettingsSection';

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

interface SelfEvolutionCycle {
  id: number;
  triggered_by: string;
  trigger_source: string;
  mode: string;
  status: string;
  summary: Record<string, any>;
  analysis?: Record<string, any>;
  proposals?: Record<string, any>;
  safeguards?: Record<string, any>;
  report?: Record<string, any>;
  created_at: string;
}

interface SelfEvolutionReviewSummary {
  pending_count: number;
  pending_eval_candidates: number;
  pending_prompt_suggestions: number;
  pending_tool_suggestions: number;
  high_priority_count: number;
  latest_created_at?: string | null;
  oldest_created_at?: string | null;
  reminders: Array<{
    id: number;
    created_at?: string | null;
    trigger_source: string;
    triggered_by: string;
    priority: string;
    reasons: string[];
    counts: Record<string, number>;
  }>;
  recommended_actions: string[];
}

interface AdminDashboardProps {
  onBack: () => void;
}

export default function AdminDashboard({ onBack }: AdminDashboardProps) {
  const [activeSection, setActiveSection] = useState<'metrics' | 'users' | 'audit' | 'system' | 'settings' | 'navigation' | 'bots' | 'a2a' | 'models' | 'costguard' | 'selfevolution'>('metrics');

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
          <button className={activeSection === 'settings' ? 'active' : ''}
            onClick={() => setActiveSection('settings')}>系统配置</button>
          <button className={activeSection === 'navigation' ? 'active' : ''}
            onClick={() => setActiveSection('navigation')}>工作台导航</button>
          <button className={activeSection === 'bots' ? 'active' : ''}
            onClick={() => setActiveSection('bots')}>Bot 管理</button>
          <button className={activeSection === 'a2a' ? 'active' : ''}
            onClick={() => setActiveSection('a2a')}>A2A</button>
          <button className={activeSection === 'models' ? 'active' : ''}
            onClick={() => setActiveSection('models')}>模型配置</button>
          <button className={activeSection === 'costguard' ? 'active' : ''}
            onClick={() => setActiveSection('costguard')}>成本控制</button>
          <button className={activeSection === 'selfevolution' ? 'active' : ''}
            onClick={() => setActiveSection('selfevolution')}>自主进化</button>
          <button className={activeSection === 'users' ? 'active' : ''}
            onClick={() => setActiveSection('users')}>用户管理</button>
          <button className={activeSection === 'audit' ? 'active' : ''}
            onClick={() => setActiveSection('audit')}>审计日志</button>
        </div>
      </div>
      <div className="admin-content">
        {activeSection === 'metrics' && <MetricsSection />}
        {activeSection === 'system' && <SystemStatusSection />}
        {activeSection === 'settings' && <PlatformSettingsSection />}
        {activeSection === 'navigation' && <NavigationSettingsSection />}
        {activeSection === 'bots' && <BotsSection />}
        {activeSection === 'a2a' && <A2ASection />}
        {activeSection === 'models' && <ModelsSection />}
        {activeSection === 'costguard' && <CostGuardSection />}
        {activeSection === 'selfevolution' && <SelfEvolutionSection />}
        {activeSection === 'users' && <UsersSection />}
        {activeSection === 'audit' && <AuditSection />}
      </div>
    </div>
  );
}

function PlatformSettingsSection() {
  const { branding, saveBranding } = usePlatformBranding();
  const [platformName, setPlatformName] = useState(branding.platform_name);
  const [platformSubtitle, setPlatformSubtitle] = useState(branding.platform_subtitle);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  useEffect(() => {
    setPlatformName(branding.platform_name);
    setPlatformSubtitle(branding.platform_subtitle);
  }, [branding.platform_name, branding.platform_subtitle]);

  const changed = platformName.trim() !== branding.platform_name
    || platformSubtitle.trim() !== branding.platform_subtitle;

  const reset = () => {
    setPlatformName(branding.platform_name);
    setPlatformSubtitle(branding.platform_subtitle);
    setMessage(null);
  };

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      await saveBranding({
        platform_name: platformName,
        platform_subtitle: platformSubtitle,
      });
      setMessage({ type: 'success', text: '已保存并同步到登录页、顶部栏和浏览器标题。' });
    } catch (error) {
      setMessage({ type: 'error', text: error instanceof Error ? error.message : '保存失败' });
    } finally {
      setSaving(false);
    }
  };

  return <section className="platform-settings-section">
    <div className="admin-section-heading">
      <span><Settings2 size={18} /></span>
      <div><h3>平台品牌配置</h3><p>配置面向用户显示的平台名称，不影响内部 API、数据库对象或部署标识。</p></div>
    </div>
    <div className="platform-settings-form">
      <label>
        <span>平台名称</span>
        <input
          value={platformName}
          onChange={event => setPlatformName(event.target.value)}
          minLength={2}
          maxLength={80}
          placeholder="Geospatial Data Agent"
        />
        <small>{platformName.trim().length}/80，将显示在登录页、顶部栏和网页标题中</small>
      </label>
      <label>
        <span>平台副标题</span>
        <input
          value={platformSubtitle}
          onChange={event => setPlatformSubtitle(event.target.value)}
          maxLength={120}
          placeholder="AI-Native Geospatial Data Platform"
        />
        <small>{platformSubtitle.trim().length}/120，显示在登录页的平台名称下方</small>
      </label>
      <div className="platform-brand-preview" aria-label="品牌预览">
        <span>预览</span>
        <strong>{platformName.trim() || '平台名称'}</strong>
        <small>{platformSubtitle.trim() || '平台副标题'}</small>
      </div>
      <div className="platform-settings-actions">
        <button className="btn-primary" onClick={save} disabled={!changed || saving || platformName.trim().length < 2}>
          <Save size={15} />{saving ? '保存中' : '保存配置'}
        </button>
        <button className="btn-secondary" onClick={reset} disabled={!changed || saving}>
          <RotateCcw size={15} />撤销修改
        </button>
        {message && <span className={`platform-settings-message ${message.type}`}>{message.text}</span>}
      </div>
    </div>
    {branding.updated_at && <p className="platform-settings-audit">
      最近更新：{new Date(branding.updated_at).toLocaleString()} · {branding.updated_by || '系统'}
    </p>}
  </section>;
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
                    <option value="standard_editor">standard_editor</option>
                    <option value="standard_reviewer">standard_reviewer</option>
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
  const availableEmbeddingModels: string[] = Object.keys(config.available_embedding_models || {});

  const handleTierChange = (tier: string, model: string) => {
    setEdits(prev => ({ ...prev, [`tier_${tier}`]: model }));
  };
  const handleRouterChange = (model: string) => {
    setEdits(prev => ({ ...prev, router_model: model }));
  };
  const handleEmbeddingChange = (model: string) => {
    setEdits(prev => ({ ...prev, embedding_model: model }));
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
        } else if (key === 'embedding_model') {
          await fetch('/api/admin/embedding-config', {
            method: 'PUT', credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ embedding_model: value }),
          });
        }
      }
      setMsg('保存成功。Router 立即生效，Agent 层级需重启生效；Embedding 切换后建议执行 reindex。');
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
              <td style={{ fontWeight: 600 }}>Embedding（向量模型）</td>
              <td>
                <select
                  value={edits.embedding_model || config.embedding_model || 'nomic-embed-text-v2-moe'}
                  onChange={e => handleEmbeddingChange(e.target.value)}
                  style={{ fontSize: 12, padding: '4px 8px', borderRadius: 4, border: '1px solid #d1d5db', width: '100%' }}
                >
                  {availableEmbeddingModels.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              </td>
              <td style={{ fontSize: 11, color: '#6b7280' }}>知识库检索、NL2SQL few-shot、字段语义匹配</td>
            </tr>
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

function CostGuardSection() {
  const [config, setConfig] = useState<{ warn_threshold: number; abort_threshold: number; usd_abort: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [edits, setEdits] = useState<Record<string, number>>({});
  const [msg, setMsg] = useState('');

  const loadConfig = () => {
    fetch('/api/admin/cost-guard-config', { credentials: 'include' })
      .then(r => r.json())
      .then(data => { setConfig(data); setEdits({}); setMsg(''); })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadConfig(); }, []);

  if (loading) return <div className="admin-loading">加载中...</div>;
  if (!config) return <div className="admin-loading">无法加载成本控制配置</div>;

  const fields: { key: string; label: string; desc: string; unit: string }[] = [
    { key: 'warn_threshold', label: '警告阈值', desc: '累计 token 达到此值时发出警告', unit: 'tokens' },
    { key: 'abort_threshold', label: '中止阈值', desc: '累计 token 达到此值时强制中止 pipeline', unit: 'tokens' },
    { key: 'usd_abort', label: 'USD 上限', desc: '单次 pipeline 费用达到此值时中止（0=不限）', unit: 'USD' },
  ];

  const handleSave = async () => {
    setSaving(true);
    try {
      const resp = await fetch('/api/admin/cost-guard-config', {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(edits),
      });
      const data = await resp.json();
      if (resp.ok) { setMsg('保存成功，下次 pipeline 执行时生效'); loadConfig(); }
      else setMsg(data.error || '保存失败');
    } catch { setMsg('网络错误'); }
    finally { setSaving(false); }
  };

  const hasEdits = Object.keys(edits).length > 0;

  return (
    <div className="admin-section">
      <h3>CostGuard 成本控制</h3>
      <p style={{ color: '#888', fontSize: 13, marginBottom: 16 }}>
        控制单次 pipeline 执行的 token 消耗上限，防止异常查询导致过高费用。
      </p>
      <table className="admin-table">
        <thead><tr><th>参数</th><th>当前值</th><th>新值</th><th>说明</th></tr></thead>
        <tbody>
          {fields.map(f => (
            <tr key={f.key}>
              <td><strong>{f.label}</strong></td>
              <td>{(config as any)[f.key]} {f.unit}</td>
              <td>
                <input type="number" min={0} step={f.key === 'usd_abort' ? 0.01 : 10000}
                  style={{ width: 120 }}
                  placeholder={(config as any)[f.key]}
                  value={edits[f.key] ?? ''}
                  onChange={e => {
                    const v = parseFloat(e.target.value);
                    if (!isNaN(v)) setEdits(prev => ({ ...prev, [f.key]: v }));
                    else setEdits(prev => { const n = { ...prev }; delete n[f.key]; return n; });
                  }}
                />
              </td>
              <td style={{ color: '#888', fontSize: 12 }}>{f.desc}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 12 }}>
        <button disabled={!hasEdits || saving} onClick={handleSave}>
          {saving ? '保存中...' : '保存'}
        </button>
        {msg && <span style={{ color: msg.includes('成功') ? '#4caf50' : '#f44336', fontSize: 13 }}>{msg}</span>}
      </div>
    </div>
  );
}

function SelfEvolutionSection() {
  const [cycles, setCycles] = useState<SelfEvolutionCycle[]>([]);
  const [selected, setSelected] = useState<SelfEvolutionCycle | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [statusFilter, setStatusFilter] = useState('');
  const [limit, setLimit] = useState(30);
  const [days, setDays] = useState(7);
  const [minScore, setMinScore] = useState(0.5);
  const [includePrompts, setIncludePrompts] = useState(false);
  const [reviewing, setReviewing] = useState('');
  const [schedulerStatus, setSchedulerStatus] = useState<Record<string, any> | null>(null);
  const [schedulerBusy, setSchedulerBusy] = useState('');
  const [reviewSummary, setReviewSummary] = useState<SelfEvolutionReviewSummary | null>(null);
  const [msg, setMsg] = useState('');

  const loadCycles = () => {
    setLoading(true);
    const params = new URLSearchParams({ limit: String(limit) });
    if (statusFilter) params.set('status', statusFilter);
    fetch(`/api/self-evolution/cycles?${params.toString()}`, { credentials: 'include' })
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(data => {
        const next = data.cycles || [];
        setCycles(next);
        if (!selected && next.length) setSelected(next[0]);
      })
      .catch(() => setMsg('无法加载自主进化审计记录'))
      .finally(() => setLoading(false));
  };

  const loadSchedulerStatus = () => {
    fetch('/api/self-evolution/scheduler', { credentials: 'include' })
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(setSchedulerStatus)
      .catch(() => {});
  };

  const loadReviewSummary = () => {
    fetch('/api/self-evolution/review-summary?limit=5', { credentials: 'include' })
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(setReviewSummary)
      .catch(() => {});
  };

  useEffect(() => { loadCycles(); loadSchedulerStatus(); loadReviewSummary(); }, [statusFilter]);

  const loadCycleDetail = (id: number) => {
    fetch(`/api/self-evolution/cycles/${id}`, { credentials: 'include' })
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(setSelected)
      .catch(() => setMsg(`无法加载周期 #${id}`));
  };

  const runCycle = async () => {
    setRunning(true);
    setMsg('');
    try {
      const resp = await fetch('/api/self-evolution/run', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          limit,
          days,
          min_score: minScore,
          include_prompt_suggestions: includePrompts,
          apply: false,
          persist: true,
          trigger_source: 'ui',
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || 'run failed');
      setMsg(data.cycle_id ? `已生成候选周期 #${data.cycle_id}` : '已完成运行，未写入审计记录');
      loadCycles();
      loadReviewSummary();
      if (data.cycle_id) loadCycleDetail(data.cycle_id);
    } catch (err: any) {
      setMsg(`运行失败: ${err.message || '未知错误'}`);
    } finally {
      setRunning(false);
    }
  };

  const reviewCycle = async (action: string) => {
    if (!selected) return;
    setReviewing(action);
    setMsg('');
    try {
      const resp = await fetch(`/api/self-evolution/cycles/${selected.id}/review`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action,
          environment: 'dev',
          target_environment: 'prod',
          dataset_name: `self-evolution-cycle-${selected.id}`,
          notes: 'reviewed in admin dashboard',
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || 'review failed');
      setMsg(`审批动作完成: ${action}`);
      loadCycles();
      loadReviewSummary();
      loadCycleDetail(selected.id);
    } catch (err: any) {
      setMsg(`审批失败: ${err.message || '未知错误'}`);
    } finally {
      setReviewing('');
    }
  };

  const controlScheduler = async (action: string) => {
    setSchedulerBusy(action);
    setMsg('');
    try {
      const resp = await fetch('/api/self-evolution/scheduler', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || 'scheduler action failed');
      setSchedulerStatus(data.scheduler || data);
      if (action === 'run_once') {
        const cycleId = data.result?.cycle_id;
        setMsg(cycleId ? `调度器已生成候选周期 #${cycleId}` : '调度器运行完成');
        loadCycles();
        loadReviewSummary();
        if (cycleId) loadCycleDetail(cycleId);
      } else {
        setMsg(action === 'start' ? '调度器已启动' : '调度器已停止');
      }
    } catch (err: any) {
      setMsg(`调度器操作失败: ${err.message || '未知错误'}`);
    } finally {
      setSchedulerBusy('');
    }
  };

  const statusCounts = cycles.reduce((acc, c) => {
    acc[c.status] = (acc[c.status] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);
  const summary = selected?.summary || {};
  const proposals = selected?.proposals || selected?.report?.proposals || {};
  const actions = proposals.next_actions || [];
  const promptSuggestions = proposals.prompt_suggestions || [];
  const toolSuggestions = proposals.tool_suggestions || [];
  const evalCandidates = proposals.eval_candidates || [];
  const pendingCount = reviewSummary?.pending_count ?? statusCounts.proposed ?? 0;
  const approvals = selected?.report?.approvals || [];
  const hasPromptDevVersions = approvals.some((approval: any) =>
    (approval?.result?.created_versions || []).some((version: any) =>
      version?.version_id && !['prod', 'production'].includes(String(version.environment || '').toLowerCase())
    )
  );
  const hasProdPromptDeployment = approvals.some((approval: any) =>
    (approval?.result?.deployed_versions || []).some((version: any) =>
      ['prod', 'production'].includes(String(version.target_environment || '').toLowerCase())
    )
  );

  return (
    <div className="self-evolution-section">
      <div className="metrics-cards">
        <div className="metric-card">
          <div className="metric-value">{cycles.length}</div>
          <div className="metric-label">审计记录</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{pendingCount}</div>
          <div className="metric-label">待审候选</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{reviewSummary?.high_priority_count ?? '-'}</div>
          <div className="metric-label">高优先级提醒</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{reviewSummary?.pending_eval_candidates ?? '-'}</div>
          <div className="metric-label">待审评测候选</div>
        </div>
      </div>

      <div className={`self-evolution-review-reminder ${pendingCount ? 'has-pending' : ''}`}>
        <div className="self-evolution-reminder-head">
          <div>
            <strong><Bell size={14} /> 审批提醒</strong>
            <span>
              {pendingCount
                ? `有 ${pendingCount} 个自主进化候选等待人工复核`
                : '当前没有待审批的自主进化候选'}
            </span>
          </div>
          <button className="btn-secondary" onClick={loadReviewSummary}>
            <RefreshCw size={13} /> 刷新提醒
          </button>
        </div>
        {pendingCount > 0 && (
          <>
            <div className="self-evolution-reminder-stats">
              <span>评测候选 {reviewSummary?.pending_eval_candidates ?? 0}</span>
              <span>Prompt 建议 {reviewSummary?.pending_prompt_suggestions ?? 0}</span>
              <span>工具建议 {reviewSummary?.pending_tool_suggestions ?? 0}</span>
              {reviewSummary?.latest_created_at && (
                <span>最新 {new Date(reviewSummary.latest_created_at).toLocaleString()}</span>
              )}
            </div>
            <div className="self-evolution-reminder-list">
              {(reviewSummary?.reminders || []).map(item => (
                <button key={item.id} type="button" onClick={() => loadCycleDetail(item.id)}>
                  <strong>#{item.id}</strong>
                  <span className={`self-evolution-priority ${item.priority}`}>{item.priority}</span>
                  <span>评测 {item.counts.eval_candidates || 0}</span>
                  <span>Prompt {item.counts.prompt_suggestions || 0}</span>
                  <span>工具 {item.counts.tool_suggestions || 0}</span>
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="metrics-chart-section self-evolution-toolbar">
        <div className="self-evolution-scheduler-card">
          <div>
            <strong>调度器</strong>
            <span>
              {schedulerStatus?.active ? '运行中' : schedulerStatus?.enabled ? '已启用未运行' : '未启用'}
              {schedulerStatus?.interval_seconds ? ` · 间隔 ${Math.round(schedulerStatus.interval_seconds / 60)} 分钟` : ''}
            </span>
            <small>
              最近周期 {schedulerStatus?.last_cycle_id ? `#${schedulerStatus.last_cycle_id}` : '-'}
              {schedulerStatus?.last_run_at ? ` · ${new Date(schedulerStatus.last_run_at).toLocaleString()}` : ''}
            </small>
          </div>
          <div className="self-evolution-actions">
            <button className="btn-secondary" onClick={loadSchedulerStatus}>刷新状态</button>
            <button className="btn-secondary"
              disabled={Boolean(schedulerBusy)}
              onClick={() => controlScheduler(schedulerStatus?.active ? 'stop' : 'start')}>
              {schedulerBusy === 'start' || schedulerBusy === 'stop'
                ? '处理中'
                : schedulerStatus?.active ? '停止调度' : '启动调度'}
            </button>
            <button className="btn-primary"
              disabled={Boolean(schedulerBusy)}
              onClick={() => controlScheduler('run_once')}>
              {schedulerBusy === 'run_once' ? '运行中' : '调度器立即运行'}
            </button>
          </div>
        </div>

        <div className="self-evolution-controls">
          <label>窗口天数
            <input type="number" min={1} max={90} value={days}
              onChange={e => setDays(Math.max(1, Math.min(90, Number(e.target.value) || 7)))} />
          </label>
          <label>读取上限
            <input type="number" min={1} max={100} value={limit}
              onChange={e => setLimit(Math.max(1, Math.min(100, Number(e.target.value) || 30)))} />
          </label>
          <label>低分阈值
            <input type="number" min={0} max={1} step={0.05} value={minScore}
              onChange={e => setMinScore(Math.max(0, Math.min(1, Number(e.target.value) || 0)))} />
          </label>
          <label>状态
            <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
              <option value="">全部</option>
              <option value="proposed">proposed</option>
              <option value="applied">applied</option>
              <option value="failed">failed</option>
              <option value="dismissed">dismissed</option>
            </select>
          </label>
          <label className="self-evolution-check">
            <input type="checkbox" checked={includePrompts}
              onChange={e => setIncludePrompts(e.target.checked)} />
            生成 prompt 建议
          </label>
        </div>
        <div className="self-evolution-actions">
          <button className="btn-primary" onClick={runCycle} disabled={running}>
            <Play size={13} /> {running ? '运行中' : '运行 dry-run'}
          </button>
          <button className="btn-secondary" onClick={loadCycles} disabled={loading}>
            <RefreshCw size={13} /> 刷新
          </button>
        </div>
        {msg && <div className="self-evolution-message">{msg}</div>}
      </div>

      <div className="self-evolution-layout">
        <div className="metrics-chart-section self-evolution-list">
          <h3>进化周期</h3>
          {loading ? (
            <div className="admin-loading">加载中...</div>
          ) : (
            <div className="data-table-container">
              <table className="data-table admin-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>时间</th>
                    <th>状态</th>
                    <th>模式</th>
                    <th>触发</th>
                    <th>坏例</th>
                    <th>工具建议</th>
                    <th>评测候选</th>
                  </tr>
                </thead>
                <tbody>
                  {cycles.map(c => (
                    <tr key={c.id}
                      className={selected?.id === c.id ? 'selected-row' : ''}
                      onClick={() => loadCycleDetail(c.id)}>
                      <td>#{c.id}</td>
                      <td>{c.created_at ? new Date(c.created_at).toLocaleString() : '-'}</td>
                      <td><span className={`status-badge ${c.status}`}>{c.status}</span></td>
                      <td>{c.mode}</td>
                      <td>{c.trigger_source || '-'} / {c.triggered_by || '-'}</td>
                      <td>{c.summary?.bad_cases ?? 0}</td>
                      <td>{c.summary?.tool_suggestions ?? 0}</td>
                      <td>{c.summary?.eval_candidates ?? 0}</td>
                    </tr>
                  ))}
                  {!cycles.length && (
                    <tr><td colSpan={8} style={{ textAlign: 'center', color: '#888' }}>暂无记录</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="metrics-chart-section self-evolution-detail">
          <h3>{selected ? `周期 #${selected.id}` : '周期详情'}</h3>
          {!selected ? (
            <div className="admin-loading">选择一条记录</div>
          ) : (
            <>
              <div className="self-evolution-summary-grid">
                {Object.entries(summary).map(([k, v]) => (
                  <div key={k}>
                    <span>{k}</span>
                    <strong>{String(v)}</strong>
                  </div>
                ))}
              </div>

              <div className="self-evolution-detail-block">
                <h4>下一步动作</h4>
                {actions.length ? actions.map((a: any, idx: number) => (
                  <div key={`${a.action || idx}`} className="self-evolution-action-row">
                    <strong>{a.action || '-'}</strong>
                    <span>{a.reason || ''}</span>
                  </div>
                )) : <p>无待处理动作</p>}
              </div>

              <div className="self-evolution-detail-block">
                <h4>候选汇总</h4>
                <div className="self-evolution-pill-row">
                  <span>工具建议 {toolSuggestions.length}</span>
                  <span>Prompt 建议 {promptSuggestions.length}</span>
                  <span>评测候选 {evalCandidates.length}</span>
                </div>
              </div>

              <div className="self-evolution-detail-block">
                <h4>人工审批</h4>
                <div className="self-evolution-review-actions">
                  <button className="btn-primary"
                    disabled={!evalCandidates.length || Boolean(reviewing)}
                    onClick={() => reviewCycle('approve_eval_candidates')}>
                    {reviewing === 'approve_eval_candidates' ? '处理中' : '入库评测候选'}
                  </button>
                  <button className="btn-secondary"
                    disabled={!promptSuggestions.some((p: any) => p.suggested_prompt) || Boolean(reviewing)}
                    onClick={() => reviewCycle('approve_prompt_suggestions')}>
                    {reviewing === 'approve_prompt_suggestions' ? '处理中' : '创建 dev prompt 版本'}
                  </button>
                  <button className="btn-secondary"
                    disabled={!hasPromptDevVersions || hasProdPromptDeployment || Boolean(reviewing)}
                    onClick={() => reviewCycle('deploy_prompt_versions_to_prod')}>
                    {reviewing === 'deploy_prompt_versions_to_prod' ? '处理中' : '发布 prod prompt'}
                  </button>
                  <button className="btn-secondary btn-danger"
                    disabled={Boolean(reviewing)}
                    onClick={() => reviewCycle('dismiss')}>
                    {reviewing === 'dismiss' ? '处理中' : '驳回候选'}
                  </button>
                </div>
              </div>

              {approvals.length > 0 && (
                <div className="self-evolution-detail-block">
                  <h4>审批记录</h4>
                  {approvals.map((approval: any, idx: number) => (
                    <div key={`${approval.action || idx}-${idx}`} className="self-evolution-action-row">
                      <strong>{approval.action || '-'}</strong>
                      <span>
                        {approval.status || '-'}
                        {approval.reviewed_by ? ` / ${approval.reviewed_by}` : ''}
                        {approval.reviewed_at ? ` / ${new Date(approval.reviewed_at).toLocaleString()}` : ''}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {promptSuggestions.length > 0 && (
                <div className="self-evolution-detail-block">
                  <h4>Prompt 建议预览</h4>
                  {promptSuggestions.map((p: any, idx: number) => (
                    <details key={`${p.domain}/${p.prompt_key}/${idx}`} className="self-evolution-prompt-diff">
                      <summary>{p.domain}/{p.prompt_key}</summary>
                      <div className="self-evolution-diff-grid">
                        <div>
                          <strong>当前 prompt</strong>
                          <pre>{p.original_prompt || '未包含原文'}</pre>
                        </div>
                        <div>
                          <strong>建议 prompt</strong>
                          <pre>{p.suggested_prompt || '未生成建议文本'}</pre>
                        </div>
                      </div>
                      {p.changes?.length > 0 && (
                        <div className="self-evolution-change-list">
                          {p.changes.map((change: string, i: number) => <span key={i}>{change}</span>)}
                        </div>
                      )}
                    </details>
                  ))}
                </div>
              )}

              <details className="self-evolution-json">
                <summary>完整报告 JSON</summary>
                <pre>{JSON.stringify(selected.report || selected, null, 2)}</pre>
              </details>
            </>
          )}
        </div>
      </div>
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
