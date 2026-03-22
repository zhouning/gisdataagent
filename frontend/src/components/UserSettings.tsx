import { useState, useEffect } from 'react';

interface UserSettingsProps {
  username: string;
  displayName: string;
  role: string;
  onClose: () => void;
  onDeleted: () => void;
}

export default function UserSettings({ username, displayName, role, onClose, onDeleted }: UserSettingsProps) {
  const [password, setPassword] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState('');

  // Password change state
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmNewPassword, setConfirmNewPassword] = useState('');
  const [pwChanging, setPwChanging] = useState(false);
  const [pwMessage, setPwMessage] = useState('');
  const [pwError, setPwError] = useState('');

  // Analysis perspective state
  const [perspective, setPerspective] = useState('');
  const [perspectiveLoading, setPerspectiveLoading] = useState(false);
  const [perspectiveSaved, setPerspectiveSaved] = useState(false);
  const [perspectiveError, setPerspectiveError] = useState('');

  // Auto-extract memories state
  const [memories, setMemories] = useState<any[]>([]);
  const [memoriesLoading, setMemoriesLoading] = useState(true);
  const [deletingMemoryId, setDeletingMemoryId] = useState<number | null>(null);

  useEffect(() => {
    fetch('/api/user/analysis-perspective', { credentials: 'include' })
      .then(r => r.json())
      .then(data => setPerspective(data.perspective || ''))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch('/api/user/memories', { credentials: 'include' })
      .then(r => r.json())
      .then(data => { setMemories(data.memories || []); setMemoriesLoading(false); })
      .catch(() => setMemoriesLoading(false));
  }, []);

  const handleDelete = async () => {
    if (!password) {
      setError('请输入密码');
      return;
    }
    setDeleting(true);
    setError('');
    try {
      const resp = await fetch('/api/user/account', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ password }),
      });
      const data = await resp.json();
      if (data.status === 'success') {
        onDeleted();
      } else {
        setError(data.message || '删除失败');
      }
    } catch {
      setError('网络错误');
    } finally {
      setDeleting(false);
    }
  };

  const handleSavePerspective = async () => {
    setPerspectiveLoading(true);
    setPerspectiveError('');
    setPerspectiveSaved(false);
    try {
      const resp = await fetch('/api/user/analysis-perspective', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ perspective }),
      });
      const data = await resp.json();
      if (data.status === 'success') {
        setPerspectiveSaved(true);
        setTimeout(() => setPerspectiveSaved(false), 2000);
      } else {
        setPerspectiveError(data.message || '保存失败');
      }
    } catch {
      setPerspectiveError('网络错误');
    } finally {
      setPerspectiveLoading(false);
    }
  };

  const handleDeleteMemory = async (id: number) => {
    setDeletingMemoryId(id);
    try {
      const resp = await fetch(`/api/user/memories/${id}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      const data = await resp.json();
      if (data.status === 'success') {
        setMemories(prev => prev.filter(m => m.id !== id));
      }
    } catch { /* silent */ }
    finally { setDeletingMemoryId(null); }
  };

  const categoryLabels: Record<string, string> = {
    data_characteristic: '数据特征',
    analysis_conclusion: '分析结论',
    user_preference: '用户偏好',
  };

  return (
    <div className="user-settings-overlay" onClick={onClose}>
      <div className="user-settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="user-settings-header">
          <h3>账户设置</h3>
          <button className="user-settings-close" onClick={onClose}>&times;</button>
        </div>

        <div className="user-settings-info">
          <div className="user-settings-row">
            <span className="user-settings-label">用户名</span>
            <span>{username}</span>
          </div>
          <div className="user-settings-row">
            <span className="user-settings-label">显示名</span>
            <span>{displayName}</span>
          </div>
          <div className="user-settings-row">
            <span className="user-settings-label">角色</span>
            <span className={`type-badge ${role}`}>{role}</span>
          </div>
        </div>

        <div className="perspective-section">
          <div className="perspective-title">分析视角</div>
          <p className="perspective-desc">
            设置您的分析关注点和偏好视角，系统将在每次分析中参考这些信息。
          </p>
          <textarea
            className="perspective-textarea"
            placeholder="例如：关注生态保护区域、优先分析耕地变化趋势、重点关注城市扩张..."
            value={perspective}
            onChange={(e) => setPerspective(e.target.value)}
            maxLength={2000}
            rows={4}
          />
          <div className="perspective-footer">
            <span className="perspective-count">{perspective.length}/2000</span>
            {perspectiveError && <span className="perspective-error">{perspectiveError}</span>}
            {perspectiveSaved && <span className="perspective-success">已保存</span>}
            <button
              className="btn-primary btn-sm"
              onClick={handleSavePerspective}
              disabled={perspectiveLoading}
            >
              {perspectiveLoading ? '保存中...' : '保存'}
            </button>
          </div>
        </div>

        <div className="memory-section">
          <div className="memory-title">智能记忆</div>
          <p className="memory-desc">
            系统自动从分析结果中提取的关键发现，用于增强后续分析。
          </p>
          {memoriesLoading ? (
            <div className="memory-empty">加载中...</div>
          ) : memories.length === 0 ? (
            <div className="memory-empty">暂无自动提取的记忆，完成分析后系统将自动记录关键发现。</div>
          ) : (
            <div className="memory-list">
              {memories.map(m => (
                <div key={m.id} className="memory-item">
                  <div className="memory-item-header">
                    <span className="memory-item-key">{m.key}</span>
                    <span className={`memory-category-badge ${m.value?.category || 'default'}`}>
                      {categoryLabels[m.value?.category as string] || '自动'}
                    </span>
                  </div>
                  <div className="memory-item-value">
                    {m.value?.finding || m.description || JSON.stringify(m.value)}
                  </div>
                  <div className="memory-item-footer">
                    <span className="memory-item-time">{new Date(m.updated_at).toLocaleString()}</span>
                    <button
                      className="memory-delete-btn"
                      onClick={() => handleDeleteMemory(m.id)}
                      disabled={deletingMemoryId === m.id}
                    >
                      {deletingMemoryId === m.id ? '...' : '删除'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Password Change */}
        <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 8, padding: 16, marginBottom: 16 }}>
          <div style={{ fontWeight: 600, marginBottom: 8, color: '#e0e0e0' }}>修改密码</div>
          <div style={{ display: 'grid', gap: 8 }}>
            <input type="password" placeholder="当前密码" value={oldPassword}
              onChange={e => { setOldPassword(e.target.value); setPwError(''); setPwMessage(''); }}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '6px 10px', color: '#e0e0e0' }} />
            <input type="password" placeholder="新密码 (至少6位)" value={newPassword}
              onChange={e => { setNewPassword(e.target.value); setPwError(''); setPwMessage(''); }}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '6px 10px', color: '#e0e0e0' }} />
            <input type="password" placeholder="确认新密码" value={confirmNewPassword}
              onChange={e => { setConfirmNewPassword(e.target.value); setPwError(''); setPwMessage(''); }}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '6px 10px', color: '#e0e0e0' }} />
            {pwError && <div style={{ color: '#ef4444', fontSize: 12 }}>{pwError}</div>}
            {pwMessage && <div style={{ color: '#10b981', fontSize: 12 }}>{pwMessage}</div>}
            <button
              disabled={pwChanging || !oldPassword || !newPassword}
              onClick={async () => {
                if (newPassword !== confirmNewPassword) { setPwError('两次输入的新密码不一致'); return; }
                if (newPassword.length < 6) { setPwError('新密码至少6位'); return; }
                setPwChanging(true); setPwError(''); setPwMessage('');
                try {
                  const r = await fetch('/api/user/password', {
                    method: 'PUT', credentials: 'include',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
                  });
                  const d = await r.json();
                  if (r.ok) { setPwMessage('密码修改成功'); setOldPassword(''); setNewPassword(''); setConfirmNewPassword(''); }
                  else { setPwError(d.error || d.message || '修改失败'); }
                } catch { setPwError('请求失败'); }
                finally { setPwChanging(false); }
              }}
              style={{
                background: '#1e3a5f', color: '#7dd3fc', border: 'none', borderRadius: 4,
                padding: '8px 16px', cursor: 'pointer', fontSize: 13,
                opacity: (pwChanging || !oldPassword || !newPassword) ? 0.5 : 1,
              }}
            >{pwChanging ? '修改中...' : '修改密码'}</button>
          </div>
        </div>

        <div className="danger-zone">
          <div className="danger-zone-title">危险操作</div>
          <p className="danger-zone-desc">删除账户后，所有数据（文件、分析记录、团队数据）将被永久清除，不可恢复。</p>

          {!confirmDelete ? (
            <button
              className="danger-zone-btn"
              onClick={() => setConfirmDelete(true)}
              disabled={role === 'admin'}
            >
              {role === 'admin' ? '管理员不可自助删除' : '删除我的账户'}
            </button>
          ) : (
            <div className="danger-zone-confirm">
              <input
                type="password"
                placeholder="请输入密码以确认"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="danger-zone-input"
              />
              {error && <div className="danger-zone-error">{error}</div>}
              <div className="danger-zone-actions">
                <button onClick={() => { setConfirmDelete(false); setPassword(''); setError(''); }}>
                  取消
                </button>
                <button className="danger-confirm-btn" onClick={handleDelete} disabled={deleting}>
                  {deleting ? '删除中...' : '确认删除'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
