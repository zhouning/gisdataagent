import { useState, useEffect } from 'react';
import { ArrowLeft, Bell, Play, RefreshCw, RotateCcw, Save, Settings2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { usePlatformBranding } from '../platformBranding';
import { formatDate, formatNumber, getLocaleHeaders } from '../i18n';
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
  const { t } = useTranslation('common');
  const [activeSection, setActiveSection] = useState<'metrics' | 'users' | 'audit' | 'system' | 'settings' | 'navigation' | 'bots' | 'a2a' | 'models' | 'costguard' | 'selfevolution'>('metrics');

  return (
    <div className="admin-dashboard">
      <div className="admin-header">
        <button className="admin-back-btn" onClick={onBack}><ArrowLeft size={15} />{t('admin.back')}</button>
        <h2>{t('admin.title')}</h2>
        <div className="admin-nav">
          <button className={activeSection === 'metrics' ? 'active' : ''}
            onClick={() => setActiveSection('metrics')}>{t('admin.sections.metrics')}</button>
          <button className={activeSection === 'system' ? 'active' : ''}
            onClick={() => setActiveSection('system')}>{t('admin.sections.system')}</button>
          <button className={activeSection === 'settings' ? 'active' : ''}
            onClick={() => setActiveSection('settings')}>{t('admin.sections.settings')}</button>
          <button className={activeSection === 'navigation' ? 'active' : ''}
            onClick={() => setActiveSection('navigation')}>{t('admin.sections.navigation')}</button>
          <button className={activeSection === 'bots' ? 'active' : ''}
            onClick={() => setActiveSection('bots')}>{t('admin.sections.bots')}</button>
          <button className={activeSection === 'a2a' ? 'active' : ''}
            onClick={() => setActiveSection('a2a')}>{t('admin.sections.a2a')}</button>
          <button className={activeSection === 'models' ? 'active' : ''}
            onClick={() => setActiveSection('models')}>{t('admin.sections.models')}</button>
          <button className={activeSection === 'costguard' ? 'active' : ''}
            onClick={() => setActiveSection('costguard')}>{t('admin.sections.costGuard')}</button>
          <button className={activeSection === 'selfevolution' ? 'active' : ''}
            onClick={() => setActiveSection('selfevolution')}>{t('admin.sections.selfEvolution')}</button>
          <button className={activeSection === 'users' ? 'active' : ''}
            onClick={() => setActiveSection('users')}>{t('admin.sections.users')}</button>
          <button className={activeSection === 'audit' ? 'active' : ''}
            onClick={() => setActiveSection('audit')}>{t('admin.sections.audit')}</button>
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
  const { t } = useTranslation('common');
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
      setMessage({ type: 'success', text: t('admin.platform.savedSuccess') });
    } catch (error) {
      setMessage({ type: 'error', text: error instanceof Error ? error.message : t('admin.platform.saveFailed') });
    } finally {
      setSaving(false);
    }
  };

  return <section className="platform-settings-section">
    <div className="admin-section-heading">
      <span><Settings2 size={18} /></span>
      <div><h3>{t('admin.platform.title')}</h3><p>{t('admin.platform.description')}</p></div>
    </div>
    <div className="platform-settings-form">
      <label>
        <span>{t('admin.platform.name')}</span>
        <input
          value={platformName}
          onChange={event => setPlatformName(event.target.value)}
          minLength={2}
          maxLength={80}
          placeholder={t('admin.platform.nameFallback')}
        />
        <small>{t('admin.platform.nameHint', { count: platformName.trim().length })}</small>
      </label>
      <label>
        <span>{t('admin.platform.subtitle')}</span>
        <input
          value={platformSubtitle}
          onChange={event => setPlatformSubtitle(event.target.value)}
          maxLength={120}
          placeholder={t('admin.platform.subtitleFallback')}
        />
        <small>{t('admin.platform.subtitleHint', { count: platformSubtitle.trim().length })}</small>
      </label>
      <div className="platform-brand-preview" aria-label={t('admin.platform.previewAria')}>
        <span>{t('admin.platform.preview')}</span>
        <strong>{platformName.trim() || t('admin.platform.nameFallback')}</strong>
        <small>{platformSubtitle.trim() || t('admin.platform.subtitleFallback')}</small>
      </div>
      <div className="platform-settings-actions">
        <button className="btn-primary" onClick={save} disabled={!changed || saving || platformName.trim().length < 2}>
          <Save size={15} />{saving ? t('admin.platform.saving') : t('admin.platform.saveConfig')}
        </button>
        <button className="btn-secondary" onClick={reset} disabled={!changed || saving}>
          <RotateCcw size={15} />{t('admin.platform.undoChanges')}
        </button>
        {message && <span className={`platform-settings-message ${message.type}`}>{message.text}</span>}
      </div>
    </div>
    {branding.updated_at && <p className="platform-settings-audit">
      {t('admin.platform.lastUpdated', {
        date: formatDate(branding.updated_at, { dateStyle: 'medium', timeStyle: 'short' }),
        user: branding.updated_by || t('admin.platform.system'),
      })}
    </p>}
  </section>;
}

function MetricsSection() {
  const { t } = useTranslation('common');
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/admin/metrics/summary', { credentials: 'include', headers: getLocaleHeaders() })
      .then((r) => r.json())
      .then(setMetrics)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="admin-loading">{t('admin.common.loading')}</div>;
  if (!metrics) return <div className="admin-loading">{t('admin.metrics.loadFailed')}</div>;

  const stats = metrics.audit_stats || {
    total_events: 0,
    active_users: 0,
    events_by_action: {},
    events_by_status: {},
    daily_counts: [],
  };
  const pipelineActions = stats.events_by_action || {};
  const maxCount = Math.max(...Object.values(pipelineActions), 1);

  return (
    <div className="metrics-section">
      <div className="metrics-cards">
        <div className="metric-card">
          <div className="metric-value">{formatNumber(stats.total_events || 0)}</div>
          <div className="metric-label">{t('admin.metrics.totalEvents30d')}</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{formatNumber(stats.active_users || 0)}</div>
          <div className="metric-label">{t('admin.metrics.activeUsers')}</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{formatNumber(metrics.user_count || 0)}</div>
          <div className="metric-label">{t('admin.metrics.registeredUsers')}</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{formatNumber(pipelineActions['pipeline_complete'] || 0)}</div>
          <div className="metric-label">{t('admin.metrics.pipelineRuns')}</div>
        </div>
      </div>

      <div className="metrics-chart-section">
        <h3>{t('admin.metrics.eventDistribution')}</h3>
        <div className="bar-chart">
          {Object.entries(pipelineActions).slice(0, 10).map(([action, count]) => (
            <div key={action} className="bar-chart-row">
              <span className="bar-label">{action}</span>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${(count / maxCount) * 100}%` }} />
              </div>
              <span className="bar-value">{formatNumber(count)}</span>
            </div>
          ))}
        </div>
      </div>

      {stats.daily_counts && stats.daily_counts.length > 0 && (
        <div className="metrics-chart-section">
          <h3>{t('admin.metrics.dailyTrend')}</h3>
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
  const { t } = useTranslation('common');
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchUsers = () => {
    setLoading(true);
    fetch('/api/admin/users', { credentials: 'include', headers: getLocaleHeaders() })
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
      headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
      body: JSON.stringify({ role }),
    });
    if (resp.ok) fetchUsers();
  };

  const deleteUser = async (username: string) => {
    if (!confirm(t('admin.users.deleteConfirm', { username }))) return;
    const resp = await fetch(`/api/admin/users/${username}`, {
      method: 'DELETE',
      credentials: 'include',
      headers: getLocaleHeaders(),
    });
    if (resp.ok) fetchUsers();
  };

  if (loading) return <div className="admin-loading">{t('admin.common.loading')}</div>;

  const authProviderLabel = (provider: string) => t(`admin.users.authProviders.${provider}`, { defaultValue: provider });

  return (
    <div className="users-section">
      <div className="data-table-container">
        <table className="data-table admin-table">
          <thead>
            <tr>
              <th>{t('admin.users.username')}</th>
              <th>{t('admin.users.displayName')}</th>
              <th>{t('admin.users.role')}</th>
              <th>{t('admin.users.authentication')}</th>
              <th>{t('admin.users.registeredAt')}</th>
              <th>{t('admin.users.actions')}</th>
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
                    <option value="admin">{t('admin.users.roles.admin')}</option>
                    <option value="analyst">{t('admin.users.roles.analyst')}</option>
                    <option value="viewer">{t('admin.users.roles.viewer')}</option>
                    <option value="standard_editor">{t('admin.users.roles.standardEditor')}</option>
                    <option value="standard_reviewer">{t('admin.users.roles.standardReviewer')}</option>
                  </select>
                </td>
                <td>{authProviderLabel(u.auth_provider)}</td>
                <td>{u.created_at ? formatDate(u.created_at, { dateStyle: 'medium' }) : '-'}</td>
                <td>
                  <button className="delete-btn" onClick={() => deleteUser(u.username)}>{t('admin.users.delete')}</button>
                </td>
              </tr>
            ))}
            {users.length === 0 && (
              <tr><td colSpan={6} style={{ textAlign: 'center' }}>{t('admin.users.empty')}</td></tr>
            )}
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
  const { t } = useTranslation('common');
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/system/status', { credentials: 'include', headers: getLocaleHeaders() })
      .then(r => r.json())
      .then(setStatus)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="admin-loading">{t('admin.common.loading')}</div>;
  if (!status) return <div className="admin-loading">{t('admin.system.loadFailed')}</div>;

  const StatusIcon = ({ ok }: { ok: boolean }) => (
    <span style={{ color: ok ? '#16a34a' : '#dc2626', fontWeight: 700 }}>{ok ? '✓' : '✗'}</span>
  );

  return (
    <div className="metrics-section">
      <div className="metrics-cards">
        <div className="metric-card">
          <div className="metric-value"><StatusIcon ok={status.database?.status === 'ok'} /> {t('admin.system.database')}</div>
          <div className="metric-label">{status.database?.status === 'ok' ? `${formatNumber(status.database.latency_ms || 0)} ms` : t('admin.system.disconnected')}</div>
        </div>
        <div className="metric-card">
          <div className="metric-value"><StatusIcon ok={status.mcp_hub?.status === 'ok'} /> MCP Hub</div>
          <div className="metric-label">{t('admin.system.serverCount', { connected: formatNumber(status.mcp_hub?.connected || 0), total: formatNumber(status.mcp_hub?.total || 0) })}</div>
        </div>
        <div className="metric-card">
          <div className="metric-value"><StatusIcon ok={status.features?.arcpy} /> ArcPy</div>
          <div className="metric-label">{status.features?.arcpy ? t('admin.system.available') : t('admin.system.notConfigured')}</div>
        </div>
        <div className="metric-card">
          <div className="metric-value"><StatusIcon ok={status.features?.cloud_storage} /> {t('admin.system.cloudStorage')}</div>
          <div className="metric-label">{status.features?.cloud_storage ? t('admin.system.connected') : t('admin.system.notConfigured')}</div>
        </div>
      </div>

      <div className="metrics-chart-section">
        <h3>{t('admin.system.modelConfig')}</h3>
        <div className="data-table-container">
          <table className="data-table admin-table">
            <thead><tr><th>{t('admin.system.modelTier')}</th><th>{t('admin.system.currentModel')}</th></tr></thead>
            <tbody>
              {status.models && Object.entries(status.models).map(([tier, model]) => (
                <tr key={tier}><td style={{ fontWeight: 600 }}>{tier}</td><td>{model as string}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="metrics-chart-section">
        <h3>{t('admin.system.features')}</h3>
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
  const { t } = useTranslation('common');
  const [bots, setBots] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/bots/status', { credentials: 'include', headers: getLocaleHeaders() })
      .then(r => r.json())
      .then(data => setBots(data.bots || {}))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="admin-loading">{t('admin.common.loading')}</div>;
  if (!bots) return <div className="admin-loading">{t('admin.bots.loadFailed')}</div>;

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
            <div key={p.key} className="metric-card" style={{ borderInlineStart: `4px solid ${bot.configured ? p.color : '#e5e7eb'}` }}>
              <div className="metric-value">{p.icon} {t(`admin.bots.platforms.${p.key}`, { defaultValue: bot.label || p.key })}</div>
              <div className="metric-label" style={{ color: bot.configured ? '#16a34a' : '#dc2626' }}>
                {bot.configured ? `✓ ${t('admin.bots.configured')}` : `✗ ${t('admin.bots.notConfigured')}`}
              </div>
              <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>
                {t('admin.bots.environmentVariables', { configured: bot.configured_keys, total: bot.total_env_keys })}
              </div>
              {bot.missing_keys && bot.missing_keys.length > 0 && (
                <div style={{ fontSize: 10, color: '#dc2626', marginTop: 4 }}>
                  {t('admin.bots.missing', { keys: bot.missing_keys.join(', ') })}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="metrics-chart-section">
        <h3>{t('admin.common.configuration')}</h3>
        <p style={{ fontSize: 12, color: '#6b7280', lineHeight: 1.6 }}>
          {t('admin.bots.descriptionBefore')} <code>data_agent/.env</code> {t('admin.bots.descriptionAfter')}
        </p>
      </div>
    </div>
  );
}

/* ============================================================
   A2A Section
   ============================================================ */

function A2ASection() {
  const { t } = useTranslation('common');
  const [card, setCard] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch('/api/a2a/card', { credentials: 'include', headers: getLocaleHeaders() }).then(r => r.json()).catch(() => null),
      fetch('/api/a2a/status', { credentials: 'include', headers: getLocaleHeaders() }).then(r => r.json()).catch(() => null),
    ]).then(([c, s]) => {
      setCard(c);
      setStatus(s);
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="admin-loading">{t('admin.common.loading')}</div>;

  return (
    <div className="metrics-section">
      <div className="metrics-cards">
        <div className="metric-card">
          <div className="metric-value">{status?.enabled ? `✓ ${t('admin.a2a.enabled')}` : `✗ ${t('admin.a2a.disabled')}`}</div>
          <div className="metric-label">{t('admin.a2a.service')}</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{status?.uptime_seconds ? t('admin.a2a.uptimeMinutes', { count: formatNumber(Math.round(status.uptime_seconds / 60)) }) : '-'}</div>
          <div className="metric-label">{t('admin.a2a.uptime')}</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{formatNumber(card?.skills?.length || 0)}</div>
          <div className="metric-label">{t('admin.a2a.exposedSkillCount')}</div>
        </div>
      </div>

      {card?.name && (
        <div className="metrics-chart-section">
          <h3>{t('admin.a2a.agentCard')}</h3>
          <div style={{ padding: 12, background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0' }}>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>{card.name}</div>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>{card.description}</div>
            <div style={{ fontSize: 11, color: '#9ca3af' }}>
              {t('admin.a2a.protocol')}: {card.protocol_version} | Streaming: {card.capabilities?.streaming ? t('admin.common.yes') : t('admin.common.no')}
            </div>
          </div>

          <h3 style={{ marginTop: 16 }}>{t('admin.a2a.exposedSkills')}</h3>
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
        <h3>{t('admin.common.configuration')}</h3>
        <p style={{ fontSize: 12, color: '#6b7280', lineHeight: 1.6 }}>
          {t('admin.a2a.descriptionStart')} <code>A2A_ENABLED=true</code> {t('admin.a2a.descriptionEnable')}
          <code>/api/a2a/card</code> {t('admin.a2a.descriptionCard')} <code>/api/a2a/tasks/send</code> {t('admin.a2a.descriptionTasks')}
        </p>
      </div>
    </div>
  );
}

/* ============================================================
   Models Configuration Section
   ============================================================ */

function ModelsSection() {
  const { t } = useTranslation('common');
  const [config, setConfig] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [showCustom, setShowCustom] = useState(false);
  const [customForm, setCustomForm] = useState({ name: '', backend: 'litellm', api_base: '', tier: 'standard' });
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const loadConfig = () => {
    fetch('/api/admin/model-config', { credentials: 'include', headers: getLocaleHeaders() })
      .then(r => r.json())
      .then(data => { setConfig(data); setEdits({}); })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadConfig(); }, []);

  if (loading) return <div className="admin-loading">{t('admin.common.loading')}</div>;
  if (!config) return <div className="admin-loading">{t('admin.models.loadFailed')}</div>;

  const tierLabels: Record<string, string> = {
    fast: t('admin.models.tiers.fast'),
    standard: t('admin.models.tiers.standard'),
    premium: t('admin.models.tiers.premium'),
  };
  const tierUsage: Record<string, string> = {
    fast: t('admin.models.usage.fast'),
    standard: t('admin.models.usage.standard'),
    premium: t('admin.models.usage.premium'),
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
    setMessage(null);
    try {
      for (const [key, value] of Object.entries(edits)) {
        if (key.startsWith('tier_')) {
          const tier = key.replace('tier_', '');
          await fetch('/api/admin/model-config', {
            method: 'PUT', credentials: 'include',
            headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
            body: JSON.stringify({ tier, model: value }),
          });
        } else if (key === 'router_model') {
          await fetch('/api/admin/model-config', {
            method: 'PUT', credentials: 'include',
            headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
            body: JSON.stringify({ router_model: value }),
          });
        } else if (key === 'embedding_model') {
          await fetch('/api/admin/embedding-config', {
            method: 'PUT', credentials: 'include',
            headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
            body: JSON.stringify({ embedding_model: value }),
          });
        }
      }
      setMessage({ type: 'success', text: t('admin.models.saveSuccess') });
      loadConfig();
    } catch { setMessage({ type: 'error', text: t('admin.models.saveFailed') }); }
    setSaving(false);
  };

  const handleAddCustom = async () => {
    if (!customForm.name) return;
    const resp = await fetch('/api/admin/model-config/custom', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
      body: JSON.stringify(customForm),
    });
    if (resp.ok) {
      setMessage({ type: 'success', text: t('admin.models.customRegistered', { name: customForm.name }) });
      setCustomForm({ name: '', backend: 'litellm', api_base: '', tier: 'standard' });
      setShowCustom(false);
      loadConfig();
    } else {
      const err = await resp.json();
      setMessage({ type: 'error', text: t('admin.models.registerFailed', { error: err.error || t('admin.common.unknownError') }) });
    }
  };

  const hasEdits = Object.keys(edits).length > 0;

  return (
    <div>
      <h3>{t('admin.models.title')}</h3>
      <p style={{ fontSize: 12, color: '#6b7280', marginBottom: 12 }}>
        {t('admin.models.description')}
      </p>

      <div className="data-table-container">
        <table className="data-table admin-table">
          <thead>
            <tr><th>{t('admin.models.tier')}</th><th>{t('admin.models.currentModel')}</th><th>{t('admin.models.purpose')}</th></tr>
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
              <td style={{ fontWeight: 600 }}>{t('admin.models.embedding')}</td>
              <td>
                <select
                  value={edits.embedding_model || config.embedding_model || 'nomic-embed-text-v2-moe'}
                  onChange={e => handleEmbeddingChange(e.target.value)}
                  style={{ fontSize: 12, padding: '4px 8px', borderRadius: 4, border: '1px solid #d1d5db', width: '100%' }}
                >
                  {availableEmbeddingModels.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              </td>
              <td style={{ fontSize: 11, color: '#6b7280' }}>{t('admin.models.embeddingUsage')}</td>
            </tr>
            <tr>
              <td style={{ fontWeight: 600 }}>{t('admin.models.router')}</td>
              <td>
                <select
                  value={edits.router_model || config.router_model}
                  onChange={e => handleRouterChange(e.target.value)}
                  style={{ fontSize: 12, padding: '4px 8px', borderRadius: 4, border: '1px solid #d1d5db', width: '100%' }}
                >
                  {availableModels.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              </td>
              <td style={{ fontSize: 11, color: '#6b7280' }}>{t('admin.models.routerUsage')}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
        <button onClick={handleSave} disabled={!hasEdits || saving}
          style={{ padding: '6px 16px', borderRadius: 6, background: hasEdits ? '#3b82f6' : '#d1d5db',
                   color: '#fff', border: 'none', cursor: hasEdits ? 'pointer' : 'default', fontSize: 13 }}>
          {saving ? t('admin.common.saving') : t('admin.models.saveConfig')}
        </button>
        <button onClick={() => setShowCustom(!showCustom)}
          style={{ padding: '6px 16px', borderRadius: 6, background: '#f1f5f9',
                   border: '1px solid #d1d5db', cursor: 'pointer', fontSize: 13 }}>
          {showCustom ? t('admin.common.cancel') : t('admin.models.addCustom')}
        </button>
        {message && <span style={{ fontSize: 12, color: message.type === 'error' ? '#ef4444' : '#22c55e' }}>{message.text}</span>}
      </div>

      {showCustom && (
        <div style={{ marginTop: 12, padding: 12, background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 12 }}>
            <label>{t('admin.models.modelName')}
              <input value={customForm.name} onChange={e => setCustomForm(p => ({ ...p, name: e.target.value }))}
                placeholder={t('admin.models.modelNamePlaceholder')} style={{ width: '100%', padding: 4, borderRadius: 4, border: '1px solid #d1d5db' }} />
            </label>
            <label>{t('admin.models.backend')}
              <select value={customForm.backend} onChange={e => setCustomForm(p => ({ ...p, backend: e.target.value }))}
                style={{ width: '100%', padding: 4, borderRadius: 4, border: '1px solid #d1d5db' }}>
                <option value="gemini">{t('admin.models.backends.gemini')}</option>
                <option value="litellm">{t('admin.models.backends.litellm')}</option>
                <option value="lm_studio">{t('admin.models.backends.lmStudio')}</option>
              </select>
            </label>
            <label>{t('admin.models.apiBaseOptional')}
              <input value={customForm.api_base} onChange={e => setCustomForm(p => ({ ...p, api_base: e.target.value }))}
                placeholder={t('admin.models.apiBasePlaceholder')} style={{ width: '100%', padding: 4, borderRadius: 4, border: '1px solid #d1d5db' }} />
            </label>
            <label>{t('admin.models.tier')}
              <select value={customForm.tier} onChange={e => setCustomForm(p => ({ ...p, tier: e.target.value }))}
                style={{ width: '100%', padding: 4, borderRadius: 4, border: '1px solid #d1d5db' }}>
                <option value="fast">{t('admin.models.tiers.fast')}</option>
                <option value="standard">{t('admin.models.tiers.standard')}</option>
                <option value="premium">{t('admin.models.tiers.premium')}</option>
                <option value="local">{t('admin.models.tiers.local')}</option>
              </select>
            </label>
          </div>
          <button onClick={handleAddCustom} style={{ marginTop: 8, padding: '4px 12px', borderRadius: 4,
            background: '#3b82f6', color: '#fff', border: 'none', cursor: 'pointer', fontSize: 12 }}>
            {t('admin.models.registerModel')}
          </button>
        </div>
      )}
    </div>
  );
}

function CostGuardSection() {
  const { t } = useTranslation('common');
  const [config, setConfig] = useState<{ warn_threshold: number; abort_threshold: number; usd_abort: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [edits, setEdits] = useState<Record<string, number>>({});
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const loadConfig = () => {
    fetch('/api/admin/cost-guard-config', { credentials: 'include', headers: getLocaleHeaders() })
      .then(r => r.json())
      .then(data => { setConfig(data); setEdits({}); })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadConfig(); }, []);

  if (loading) return <div className="admin-loading">{t('admin.common.loading')}</div>;
  if (!config) return <div className="admin-loading">{t('admin.costGuard.loadFailed')}</div>;

  const fields: { key: string; label: string; desc: string; unit: string }[] = [
    { key: 'warn_threshold', label: t('admin.costGuard.warnThreshold'), desc: t('admin.costGuard.warnDescription'), unit: 'tokens' },
    { key: 'abort_threshold', label: t('admin.costGuard.abortThreshold'), desc: t('admin.costGuard.abortDescription'), unit: 'tokens' },
    { key: 'usd_abort', label: t('admin.costGuard.usdLimit'), desc: t('admin.costGuard.usdDescription'), unit: 'USD' },
  ];

  const handleSave = async () => {
    setSaving(true);
    try {
      const resp = await fetch('/api/admin/cost-guard-config', {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify(edits),
      });
      const data = await resp.json();
      if (resp.ok) { setMessage({ type: 'success', text: t('admin.costGuard.saveSuccess') }); loadConfig(); }
      else setMessage({ type: 'error', text: data.error || t('admin.common.saveFailed') });
    } catch { setMessage({ type: 'error', text: t('admin.common.networkError') }); }
    finally { setSaving(false); }
  };

  const hasEdits = Object.keys(edits).length > 0;

  return (
    <div className="admin-section">
      <h3>{t('admin.costGuard.title')}</h3>
      <p style={{ color: '#888', fontSize: 13, marginBottom: 16 }}>
        {t('admin.costGuard.description')}
      </p>
      <table className="admin-table">
        <thead><tr><th>{t('admin.costGuard.parameter')}</th><th>{t('admin.costGuard.currentValue')}</th><th>{t('admin.costGuard.newValue')}</th><th>{t('admin.costGuard.explanation')}</th></tr></thead>
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
          {saving ? t('admin.common.saving') : t('admin.common.save')}
        </button>
        {message && <span style={{ color: message.type === 'success' ? '#4caf50' : '#f44336', fontSize: 13 }}>{message.text}</span>}
      </div>
    </div>
  );
}

function SelfEvolutionSection() {
  const { t, i18n } = useTranslation('common');
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
    fetch(`/api/self-evolution/cycles?${params.toString()}`, { credentials: 'include', headers: getLocaleHeaders() })
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(data => {
        const next = data.cycles || [];
        setCycles(next);
        if (!selected && next.length) setSelected(next[0]);
      })
      .catch(() => setMsg(t('admin.selfEvolution.loadFailed')))
      .finally(() => setLoading(false));
  };

  const loadSchedulerStatus = () => {
    fetch('/api/self-evolution/scheduler', { credentials: 'include', headers: getLocaleHeaders() })
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(setSchedulerStatus)
      .catch(() => {});
  };

  const loadReviewSummary = () => {
    fetch('/api/self-evolution/review-summary?limit=5', { credentials: 'include', headers: getLocaleHeaders() })
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(setReviewSummary)
      .catch(() => {});
  };

  useEffect(() => { loadCycles(); loadSchedulerStatus(); loadReviewSummary(); }, [statusFilter]);
  useEffect(() => { setMsg(''); }, [i18n.resolvedLanguage]);

  const loadCycleDetail = (id: number) => {
    fetch(`/api/self-evolution/cycles/${id}`, { credentials: 'include', headers: getLocaleHeaders() })
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(setSelected)
      .catch(() => setMsg(t('admin.selfEvolution.loadCycleFailed', { id })));
  };

  const runCycle = async () => {
    setRunning(true);
    setMsg('');
    try {
      const resp = await fetch('/api/self-evolution/run', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
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
      if (!resp.ok) throw new Error(data.error || t('admin.common.unknownError'));
      setMsg(data.cycle_id
        ? t('admin.selfEvolution.candidateGenerated', { id: data.cycle_id })
        : t('admin.selfEvolution.runCompleteNoAudit'));
      loadCycles();
      loadReviewSummary();
      if (data.cycle_id) loadCycleDetail(data.cycle_id);
    } catch (err: any) {
      setMsg(t('admin.selfEvolution.runFailed', { error: err.message || t('admin.common.unknownError') }));
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
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({
          action,
          environment: 'dev',
          target_environment: 'prod',
          dataset_name: `self-evolution-cycle-${selected.id}`,
          notes: 'reviewed in admin dashboard',
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || t('admin.common.unknownError'));
      setMsg(t('admin.selfEvolution.reviewComplete', { action }));
      loadCycles();
      loadReviewSummary();
      loadCycleDetail(selected.id);
    } catch (err: any) {
      setMsg(t('admin.selfEvolution.reviewFailed', { error: err.message || t('admin.common.unknownError') }));
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
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({ action }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || t('admin.common.unknownError'));
      setSchedulerStatus(data.scheduler || data);
      if (action === 'run_once') {
        const cycleId = data.result?.cycle_id;
        setMsg(cycleId
          ? t('admin.selfEvolution.schedulerCandidateGenerated', { id: cycleId })
          : t('admin.selfEvolution.schedulerRunComplete'));
        loadCycles();
        loadReviewSummary();
        if (cycleId) loadCycleDetail(cycleId);
      } else {
        setMsg(action === 'start' ? t('admin.selfEvolution.schedulerStarted') : t('admin.selfEvolution.schedulerStopped'));
      }
    } catch (err: any) {
      setMsg(t('admin.selfEvolution.schedulerFailed', { error: err.message || t('admin.common.unknownError') }));
    } finally {
      setSchedulerBusy('');
    }
  };

  const statusCounts = cycles.reduce((acc, c) => {
    acc[c.status] = (acc[c.status] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);
  const statusLabel = (status: string) => t(`admin.selfEvolution.statuses.${status}`, { defaultValue: status });
  const approvalStatusLabel = (status: string) => t(`statusLabels.${status}`, { defaultValue: status });
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
          <div className="metric-value">{formatNumber(cycles.length)}</div>
          <div className="metric-label">{t('admin.selfEvolution.auditRecords')}</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{formatNumber(pendingCount)}</div>
          <div className="metric-label">{t('admin.selfEvolution.pendingCandidates')}</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{reviewSummary?.high_priority_count ?? '-'}</div>
          <div className="metric-label">{t('admin.selfEvolution.highPriorityAlerts')}</div>
        </div>
        <div className="metric-card">
          <div className="metric-value">{reviewSummary?.pending_eval_candidates ?? '-'}</div>
          <div className="metric-label">{t('admin.selfEvolution.pendingEvalCandidates')}</div>
        </div>
      </div>

      <div className={`self-evolution-review-reminder ${pendingCount ? 'has-pending' : ''}`}>
        <div className="self-evolution-reminder-head">
          <div>
            <strong><Bell size={14} /> {t('admin.selfEvolution.reviewReminder')}</strong>
            <span>
              {pendingCount
                ? t('admin.selfEvolution.pendingReview', { count: formatNumber(pendingCount) })
                : t('admin.selfEvolution.noPendingReview')}
            </span>
          </div>
          <button className="btn-secondary" onClick={loadReviewSummary}>
            <RefreshCw size={13} /> {t('admin.selfEvolution.refreshReminders')}
          </button>
        </div>
        {pendingCount > 0 && (
          <>
            <div className="self-evolution-reminder-stats">
              <span>{t('admin.selfEvolution.evalCandidates')} {formatNumber(reviewSummary?.pending_eval_candidates ?? 0)}</span>
              <span>{t('admin.selfEvolution.promptSuggestions')} {formatNumber(reviewSummary?.pending_prompt_suggestions ?? 0)}</span>
              <span>{t('admin.selfEvolution.toolSuggestions')} {formatNumber(reviewSummary?.pending_tool_suggestions ?? 0)}</span>
              {reviewSummary?.latest_created_at && (
                <span>{t('admin.selfEvolution.latest')} {formatDate(reviewSummary.latest_created_at, { dateStyle: 'medium', timeStyle: 'short' })}</span>
              )}
            </div>
            <div className="self-evolution-reminder-list">
              {(reviewSummary?.reminders || []).map(item => (
                <button key={item.id} type="button" onClick={() => loadCycleDetail(item.id)}>
                  <strong>#{item.id}</strong>
                  <span className={`self-evolution-priority ${item.priority}`}>{item.priority}</span>
                  <span>{t('admin.selfEvolution.evaluations')} {formatNumber(item.counts.eval_candidates || 0)}</span>
                  <span>Prompt {item.counts.prompt_suggestions || 0}</span>
                  <span>{t('admin.selfEvolution.tools')} {formatNumber(item.counts.tool_suggestions || 0)}</span>
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="metrics-chart-section self-evolution-toolbar">
        <div className="self-evolution-scheduler-card">
          <div>
            <strong>{t('admin.selfEvolution.scheduler')}</strong>
            <span>
              {schedulerStatus?.active
                ? t('admin.selfEvolution.running')
                : schedulerStatus?.enabled ? t('admin.selfEvolution.enabledIdle') : t('admin.selfEvolution.disabled')}
              {schedulerStatus?.interval_seconds
                ? ` · ${t('admin.selfEvolution.intervalMinutes', { count: formatNumber(Math.round(schedulerStatus.interval_seconds / 60)) })}`
                : ''}
            </span>
            <small>
              {t('admin.selfEvolution.lastCycle')} {schedulerStatus?.last_cycle_id ? `#${schedulerStatus.last_cycle_id}` : '-'}
              {schedulerStatus?.last_run_at ? ` · ${formatDate(schedulerStatus.last_run_at, { dateStyle: 'medium', timeStyle: 'short' })}` : ''}
            </small>
          </div>
          <div className="self-evolution-actions">
            <button className="btn-secondary" onClick={loadSchedulerStatus}>{t('admin.selfEvolution.refreshStatus')}</button>
            <button className="btn-secondary"
              disabled={Boolean(schedulerBusy)}
              onClick={() => controlScheduler(schedulerStatus?.active ? 'stop' : 'start')}>
              {schedulerBusy === 'start' || schedulerBusy === 'stop'
                ? t('admin.selfEvolution.processing')
                : schedulerStatus?.active ? t('admin.selfEvolution.stopScheduler') : t('admin.selfEvolution.startScheduler')}
            </button>
            <button className="btn-primary"
              disabled={Boolean(schedulerBusy)}
              onClick={() => controlScheduler('run_once')}>
              {schedulerBusy === 'run_once' ? t('admin.selfEvolution.running') : t('admin.selfEvolution.runSchedulerNow')}
            </button>
          </div>
        </div>

        <div className="self-evolution-controls">
          <label>{t('admin.selfEvolution.windowDays')}
            <input type="number" min={1} max={90} value={days}
              onChange={e => setDays(Math.max(1, Math.min(90, Number(e.target.value) || 7)))} />
          </label>
          <label>{t('admin.selfEvolution.readLimit')}
            <input type="number" min={1} max={100} value={limit}
              onChange={e => setLimit(Math.max(1, Math.min(100, Number(e.target.value) || 30)))} />
          </label>
          <label>{t('admin.selfEvolution.lowScoreThreshold')}
            <input type="number" min={0} max={1} step={0.05} value={minScore}
              onChange={e => setMinScore(Math.max(0, Math.min(1, Number(e.target.value) || 0)))} />
          </label>
          <label>{t('admin.selfEvolution.status')}
            <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
              <option value="">{t('admin.selfEvolution.all')}</option>
              <option value="proposed">{statusLabel('proposed')}</option>
              <option value="applied">{statusLabel('applied')}</option>
              <option value="failed">{statusLabel('failed')}</option>
              <option value="dismissed">{statusLabel('dismissed')}</option>
            </select>
          </label>
          <label className="self-evolution-check">
            <input type="checkbox" checked={includePrompts}
              onChange={e => setIncludePrompts(e.target.checked)} />
            {t('admin.selfEvolution.generatePromptSuggestions')}
          </label>
        </div>
        <div className="self-evolution-actions">
          <button className="btn-primary" onClick={runCycle} disabled={running}>
            <Play size={13} /> {running ? t('admin.selfEvolution.running') : t('admin.selfEvolution.runDryRun')}
          </button>
          <button className="btn-secondary" onClick={loadCycles} disabled={loading}>
            <RefreshCw size={13} /> {t('admin.common.refresh')}
          </button>
        </div>
        {msg && <div className="self-evolution-message">{msg}</div>}
      </div>

      <div className="self-evolution-layout">
        <div className="metrics-chart-section self-evolution-list">
          <h3>{t('admin.selfEvolution.cycles')}</h3>
          {loading ? (
            <div className="admin-loading">{t('admin.common.loading')}</div>
          ) : (
            <div className="data-table-container">
              <table className="data-table admin-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>{t('admin.selfEvolution.time')}</th>
                    <th>{t('admin.selfEvolution.status')}</th>
                    <th>{t('admin.selfEvolution.mode')}</th>
                    <th>{t('admin.selfEvolution.trigger')}</th>
                    <th>{t('admin.selfEvolution.badCases')}</th>
                    <th>{t('admin.selfEvolution.toolSuggestions')}</th>
                    <th>{t('admin.selfEvolution.evalCandidates')}</th>
                  </tr>
                </thead>
                <tbody>
                  {cycles.map(c => (
                    <tr key={c.id}
                      className={selected?.id === c.id ? 'selected-row' : ''}
                      onClick={() => loadCycleDetail(c.id)}>
                      <td>#{c.id}</td>
                      <td>{c.created_at ? formatDate(c.created_at, { dateStyle: 'medium', timeStyle: 'short' }) : '-'}</td>
                      <td><span className={`status-badge ${c.status}`}>{statusLabel(c.status)}</span></td>
                      <td>{c.mode}</td>
                      <td>{c.trigger_source || '-'} / {c.triggered_by || '-'}</td>
                      <td>{c.summary?.bad_cases ?? 0}</td>
                      <td>{c.summary?.tool_suggestions ?? 0}</td>
                      <td>{c.summary?.eval_candidates ?? 0}</td>
                    </tr>
                  ))}
                  {!cycles.length && (
                    <tr><td colSpan={8} style={{ textAlign: 'center', color: '#888' }}>{t('admin.selfEvolution.empty')}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="metrics-chart-section self-evolution-detail">
          <h3>{selected ? t('admin.selfEvolution.cycleTitle', { id: selected.id }) : t('admin.selfEvolution.cycleDetails')}</h3>
          {!selected ? (
            <div className="admin-loading">{t('admin.selfEvolution.selectRecord')}</div>
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
                <h4>{t('admin.selfEvolution.nextActions')}</h4>
                {actions.length ? actions.map((a: any, idx: number) => (
                  <div key={`${a.action || idx}`} className="self-evolution-action-row">
                    <strong>{a.action || '-'}</strong>
                    <span>{a.reason || ''}</span>
                  </div>
                )) : <p>{t('admin.selfEvolution.noPendingActions')}</p>}
              </div>

              <div className="self-evolution-detail-block">
                <h4>{t('admin.selfEvolution.candidateSummary')}</h4>
                <div className="self-evolution-pill-row">
                  <span>{t('admin.selfEvolution.toolSuggestions')} {formatNumber(toolSuggestions.length)}</span>
                  <span>{t('admin.selfEvolution.promptSuggestions')} {formatNumber(promptSuggestions.length)}</span>
                  <span>{t('admin.selfEvolution.evalCandidates')} {formatNumber(evalCandidates.length)}</span>
                </div>
              </div>

              <div className="self-evolution-detail-block">
                <h4>{t('admin.selfEvolution.humanReview')}</h4>
                <div className="self-evolution-review-actions">
                  <button className="btn-primary"
                    disabled={!evalCandidates.length || Boolean(reviewing)}
                    onClick={() => reviewCycle('approve_eval_candidates')}>
                    {reviewing === 'approve_eval_candidates' ? t('admin.selfEvolution.processing') : t('admin.selfEvolution.storeEvalCandidates')}
                  </button>
                  <button className="btn-secondary"
                    disabled={!promptSuggestions.some((p: any) => p.suggested_prompt) || Boolean(reviewing)}
                    onClick={() => reviewCycle('approve_prompt_suggestions')}>
                    {reviewing === 'approve_prompt_suggestions' ? t('admin.selfEvolution.processing') : t('admin.selfEvolution.createDevPrompt')}
                  </button>
                  <button className="btn-secondary"
                    disabled={!hasPromptDevVersions || hasProdPromptDeployment || Boolean(reviewing)}
                    onClick={() => reviewCycle('deploy_prompt_versions_to_prod')}>
                    {reviewing === 'deploy_prompt_versions_to_prod' ? t('admin.selfEvolution.processing') : t('admin.selfEvolution.deployProdPrompt')}
                  </button>
                  <button className="btn-secondary btn-danger"
                    disabled={Boolean(reviewing)}
                    onClick={() => reviewCycle('dismiss')}>
                    {reviewing === 'dismiss' ? t('admin.selfEvolution.processing') : t('admin.selfEvolution.dismissCandidate')}
                  </button>
                </div>
              </div>

              {approvals.length > 0 && (
                <div className="self-evolution-detail-block">
                  <h4>{t('admin.selfEvolution.approvalHistory')}</h4>
                  {approvals.map((approval: any, idx: number) => (
                    <div key={`${approval.action || idx}-${idx}`} className="self-evolution-action-row">
                      <strong>{approval.action || '-'}</strong>
                      <span>
                        {approval.status ? approvalStatusLabel(approval.status) : '-'}
                        {approval.reviewed_by ? ` / ${approval.reviewed_by}` : ''}
                        {approval.reviewed_at ? ` / ${formatDate(approval.reviewed_at, { dateStyle: 'medium', timeStyle: 'short' })}` : ''}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {promptSuggestions.length > 0 && (
                <div className="self-evolution-detail-block">
                  <h4>{t('admin.selfEvolution.promptPreview')}</h4>
                  {promptSuggestions.map((p: any, idx: number) => (
                    <details key={`${p.domain}/${p.prompt_key}/${idx}`} className="self-evolution-prompt-diff">
                      <summary>{p.domain}/{p.prompt_key}</summary>
                      <div className="self-evolution-diff-grid">
                        <div>
                          <strong>{t('admin.selfEvolution.currentPrompt')}</strong>
                          <pre>{p.original_prompt || t('admin.selfEvolution.originalUnavailable')}</pre>
                        </div>
                        <div>
                          <strong>{t('admin.selfEvolution.suggestedPrompt')}</strong>
                          <pre>{p.suggested_prompt || t('admin.selfEvolution.suggestionUnavailable')}</pre>
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
                <summary>{t('admin.selfEvolution.fullReportJson')}</summary>
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
  const { t } = useTranslation('common');
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(7);
  const statusLabel = (status: string) => t(`admin.audit.statuses.${status}`, { defaultValue: status });

  useEffect(() => {
    setLoading(true);
    fetch(`/api/admin/audit?days=${days}&limit=100`, { credentials: 'include', headers: getLocaleHeaders() })
      .then((r) => r.json())
      .then((data) => setEntries(data.entries || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [days]);

  if (loading) return <div className="admin-loading">{t('admin.common.loading')}</div>;

  return (
    <div className="audit-section">
      <div className="history-filter" style={{ marginBottom: 12 }}>
        {[7, 30, 90].map((d) => (
          <button key={d} className={`history-range-btn ${days === d ? 'active' : ''}`}
            onClick={() => setDays(d)}>{t('admin.audit.days', { count: formatNumber(d) })}</button>
        ))}
      </div>
      <div className="data-table-container">
        <table className="data-table admin-table">
          <thead>
            <tr>
              <th>{t('admin.audit.time')}</th>
              <th>{t('admin.audit.user')}</th>
              <th>{t('admin.audit.action')}</th>
              <th>{t('admin.audit.status')}</th>
              <th>{t('admin.audit.details')}</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <td>{e.created_at ? formatDate(e.created_at, { dateStyle: 'medium', timeStyle: 'short' }) : '-'}</td>
                <td>{e.username}</td>
                <td>{e.action}</td>
                <td><span className={`status-badge ${e.status}`}>{statusLabel(e.status)}</span></td>
                <td title={JSON.stringify(e.details)}>
                  {e.details ? JSON.stringify(e.details).slice(0, 60) : '-'}
                </td>
              </tr>
            ))}
            {entries.length === 0 && (
              <tr><td colSpan={5} style={{ textAlign: 'center' }}>{t('admin.audit.empty')}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
