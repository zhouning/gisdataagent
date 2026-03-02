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
  const [activeSection, setActiveSection] = useState<'metrics' | 'users' | 'audit'>('metrics');

  return (
    <div className="admin-dashboard">
      <div className="admin-header">
        <button className="admin-back-btn" onClick={onBack}>&larr; 返回</button>
        <h2>管理后台</h2>
        <div className="admin-nav">
          <button className={activeSection === 'metrics' ? 'active' : ''}
            onClick={() => setActiveSection('metrics')}>系统指标</button>
          <button className={activeSection === 'users' ? 'active' : ''}
            onClick={() => setActiveSection('users')}>用户管理</button>
          <button className={activeSection === 'audit' ? 'active' : ''}
            onClick={() => setActiveSection('audit')}>审计日志</button>
        </div>
      </div>
      <div className="admin-content">
        {activeSection === 'metrics' && <MetricsSection />}
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
