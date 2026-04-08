/**
 * UserManageTab — 用户管理（系统管理组）
 *
 * 对接后端：
 * - GET  /api/admin/users — 用户列表
 * - PUT  /api/admin/users/{username}/role — 修改角色
 * - DELETE /api/admin/users/{username} — 删除用户
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Users, Shield, Trash2, Loader2, AlertCircle,
  UserCheck, UserX, ChevronDown,
} from 'lucide-react';

interface AppUser {
  id: number;
  username: string;
  display_name: string;
  role: string;
  auth_provider: string;
  created_at: string | null;
}

const ROLE_OPTIONS = ['admin', 'analyst', 'viewer'] as const;
const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  analyst: '分析师',
  viewer: '只读',
};

export default function UserManageTab() {
  const [users, setUsers] = useState<AppUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingRole, setEditingRole] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/admin/users', { credentials: 'include' });
      if (res.status === 403) { setError('需要管理员权限'); return; }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setUsers(data.users ?? []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadUsers(); }, [loadUsers]);

  const handleRoleChange = useCallback(async (username: string, newRole: string) => {
    setError(null);
    try {
      const res = await fetch(`/api/admin/users/${encodeURIComponent(username)}/role`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: newRole }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${res.status}`);
      }
      setUsers(prev => prev.map(u => u.username === username ? { ...u, role: newRole } : u));
      setEditingRole(null);
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  const handleDelete = useCallback(async (username: string) => {
    if (!confirm(`确定删除用户 "${username}"？此操作不可撤销。`)) return;
    setDeleting(username);
    setError(null);
    try {
      const res = await fetch(`/api/admin/users/${encodeURIComponent(username)}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${res.status}`);
      }
      setUsers(prev => prev.filter(u => u.username !== username));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setDeleting(null);
    }
  }, []);

  if (loading) {
    return <div className="tab-loading"><Loader2 size={20} className="spin" /> 加载中...</div>;
  }

  return (
    <div className="user-manage-tab">
      {error && <div className="tab-error"><AlertCircle size={14} /> {error}</div>}

      <div className="user-manage-tab__header">
        <h4><Users size={14} /> 用户列表 ({users.length})</h4>
      </div>

      {users.length === 0 ? (
        <div className="tab-empty">暂无用户数据</div>
      ) : (
        <div className="user-table">
          <div className="user-table__header">
            <span>用户名</span>
            <span>显示名</span>
            <span>角色</span>
            <span>认证方式</span>
            <span>创建时间</span>
            <span>操作</span>
          </div>
          {users.map(u => (
            <div key={u.username} className="user-table__row">
              <span className="user-table__username">
                <UserCheck size={12} /> {u.username}
              </span>
              <span>{u.display_name || '-'}</span>
              <span>
                {editingRole === u.username ? (
                  <select
                    value={u.role}
                    onChange={e => handleRoleChange(u.username, e.target.value)}
                    onBlur={() => setEditingRole(null)}
                    autoFocus
                  >
                    {ROLE_OPTIONS.map(r => (
                      <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                    ))}
                  </select>
                ) : (
                  <button
                    className={`role-badge role-${u.role}`}
                    onClick={() => setEditingRole(u.username)}
                    title="点击修改角色"
                  >
                    <Shield size={10} /> {ROLE_LABELS[u.role] ?? u.role}
                  </button>
                )}
              </span>
              <span className="auth-provider">{u.auth_provider}</span>
              <span className="created-at">
                {u.created_at ? new Date(u.created_at).toLocaleDateString('zh-CN') : '-'}
              </span>
              <span>
                <button
                  className="btn-icon danger"
                  onClick={() => handleDelete(u.username)}
                  disabled={deleting === u.username}
                  title="删除用户"
                >
                  {deleting === u.username ? <Loader2 size={12} className="spin" /> : <Trash2 size={12} />}
                </button>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
