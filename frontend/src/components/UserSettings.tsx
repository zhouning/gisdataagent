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

  // Analysis perspective state
  const [perspective, setPerspective] = useState('');
  const [perspectiveLoading, setPerspectiveLoading] = useState(false);
  const [perspectiveSaved, setPerspectiveSaved] = useState(false);
  const [perspectiveError, setPerspectiveError] = useState('');

  useEffect(() => {
    fetch('/api/user/analysis-perspective', { credentials: 'include' })
      .then(r => r.json())
      .then(data => setPerspective(data.perspective || ''))
      .catch(() => {});
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
