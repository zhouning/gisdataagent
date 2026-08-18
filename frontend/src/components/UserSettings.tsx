import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { formatDate, getLocaleHeaders } from '../i18n';
import LanguageSwitcher from './LanguageSwitcher';

interface UserSettingsProps {
  username: string;
  displayName: string;
  role: string;
  onClose: () => void;
  onDeleted: () => void;
}

export default function UserSettings({ username, displayName, role, onClose, onDeleted }: UserSettingsProps) {
  const { t } = useTranslation('common');
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
    fetch('/api/user/analysis-perspective', { credentials: 'include', headers: getLocaleHeaders() })
      .then(r => r.json())
      .then(data => setPerspective(data.perspective || ''))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch('/api/user/memories', { credentials: 'include', headers: getLocaleHeaders() })
      .then(r => r.json())
      .then(data => { setMemories(data.memories || []); setMemoriesLoading(false); })
      .catch(() => setMemoriesLoading(false));
  }, []);

  const handleDelete = async () => {
    if (!password) {
      setError(t('settings.deleteConfirmPlaceholder'));
      return;
    }
    setDeleting(true);
    setError('');
    try {
      const resp = await fetch('/api/user/account', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        credentials: 'include',
        body: JSON.stringify({ password }),
      });
      const data = await resp.json();
      if (data.status === 'success') {
        onDeleted();
      } else {
        setError(data.message || t('settings.deleteFailed'));
      }
    } catch {
      setError(t('settings.networkError'));
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
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        credentials: 'include',
        body: JSON.stringify({ perspective }),
      });
      const data = await resp.json();
      if (data.status === 'success') {
        setPerspectiveSaved(true);
        setTimeout(() => setPerspectiveSaved(false), 2000);
      } else {
        setPerspectiveError(data.message || t('settings.saveFailed'));
      }
    } catch {
      setPerspectiveError(t('settings.networkError'));
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
        headers: getLocaleHeaders(),
      });
      const data = await resp.json();
      if (data.status === 'success') {
        setMemories(prev => prev.filter(m => m.id !== id));
      }
    } catch { /* silent */ }
    finally { setDeletingMemoryId(null); }
  };

  const categoryLabels: Record<string, string> = {
    data_characteristic: t('settings.dataCharacteristic'),
    analysis_conclusion: t('settings.analysisConclusion'),
    user_preference: t('settings.userPreference'),
  };

  return (
    <div className="user-settings-overlay" onClick={onClose}>
      <div className="user-settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="user-settings-header">
          <h3>{t('settings.title')}</h3>
          <button className="user-settings-close" onClick={onClose}>&times;</button>
        </div>

        <div className="user-settings-info">
          <div className="user-settings-row">
            <span className="user-settings-label">{t('settings.username')}</span>
            <span>{username}</span>
          </div>
          <div className="user-settings-row">
            <span className="user-settings-label">{t('settings.displayName')}</span>
            <span>{displayName}</span>
          </div>
          <div className="user-settings-row">
            <span className="user-settings-label">{t('settings.role')}</span>
            <span className={`type-badge ${role}`}>{role}</span>
          </div>
        </div>

        <div className="settings-language-section">
          <LanguageSwitcher />
        </div>

        <div className="perspective-section">
          <div className="perspective-title">{t('settings.perspective')}</div>
          <p className="perspective-desc">
            {t('settings.perspectiveDescription')}
          </p>
          <textarea
            className="perspective-textarea"
            placeholder={t('settings.perspectivePlaceholder')}
            value={perspective}
            onChange={(e) => setPerspective(e.target.value)}
            maxLength={2000}
            rows={4}
          />
          <div className="perspective-footer">
            <span className="perspective-count">{perspective.length}/2000</span>
            {perspectiveError && <span className="perspective-error">{perspectiveError}</span>}
            {perspectiveSaved && <span className="perspective-success">{t('settings.saved')}</span>}
            <button
              className="btn-primary btn-sm"
              onClick={handleSavePerspective}
              disabled={perspectiveLoading}
            >
              {perspectiveLoading ? t('settings.saving') : t('settings.save')}
            </button>
          </div>
        </div>

        <div className="memory-section">
          <div className="memory-title">{t('settings.smartMemory')}</div>
          <p className="memory-desc">
            {t('settings.memoryDescription')}
          </p>
          {memoriesLoading ? (
            <div className="memory-empty">{t('settings.loading')}</div>
          ) : memories.length === 0 ? (
            <div className="memory-empty">{t('settings.noMemory')}</div>
          ) : (
            <div className="memory-list">
              {memories.map(m => (
                <div key={m.id} className="memory-item">
                  <div className="memory-item-header">
                    <span className="memory-item-key">{m.key}</span>
                    <span className={`memory-category-badge ${m.value?.category || 'default'}`}>
                      {categoryLabels[m.value?.category as string] || t('settings.automatic')}
                    </span>
                  </div>
                  <div className="memory-item-value">
                    {m.value?.finding || m.description || JSON.stringify(m.value)}
                  </div>
                  <div className="memory-item-footer">
                    <span className="memory-item-time">{formatDate(m.updated_at, { dateStyle: 'medium', timeStyle: 'short' })}</span>
                    <button
                      className="memory-delete-btn"
                      onClick={() => handleDeleteMemory(m.id)}
                      disabled={deletingMemoryId === m.id}
                    >
                      {deletingMemoryId === m.id ? '...' : t('settings.delete')}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Password Change */}
        <div style={{ background: '#111827', border: '1px solid #1f2937', borderRadius: 8, padding: 16, marginBottom: 16 }}>
          <div style={{ fontWeight: 600, marginBottom: 8, color: '#e0e0e0' }}>{t('settings.changePassword')}</div>
          <div style={{ display: 'grid', gap: 8 }}>
            <input type="password" placeholder={t('settings.currentPassword')} value={oldPassword}
              onChange={e => { setOldPassword(e.target.value); setPwError(''); setPwMessage(''); }}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '6px 10px', color: '#e0e0e0' }} />
            <input type="password" placeholder={t('settings.newPassword')} value={newPassword}
              onChange={e => { setNewPassword(e.target.value); setPwError(''); setPwMessage(''); }}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '6px 10px', color: '#e0e0e0' }} />
            <input type="password" placeholder={t('settings.confirmNewPassword')} value={confirmNewPassword}
              onChange={e => { setConfirmNewPassword(e.target.value); setPwError(''); setPwMessage(''); }}
              style={{ background: '#0d1117', border: '1px solid #444', borderRadius: 4, padding: '6px 10px', color: '#e0e0e0' }} />
            {pwError && <div style={{ color: '#ef4444', fontSize: 12 }}>{pwError}</div>}
            {pwMessage && <div style={{ color: '#10b981', fontSize: 12 }}>{pwMessage}</div>}
            <button
              disabled={pwChanging || !oldPassword || !newPassword}
              onClick={async () => {
                if (newPassword !== confirmNewPassword) { setPwError(t('settings.newPasswordMismatch')); return; }
                if (newPassword.length < 6) { setPwError(t('settings.newPasswordTooShort')); return; }
                setPwChanging(true); setPwError(''); setPwMessage('');
                try {
                  const r = await fetch('/api/user/password', {
                    method: 'PUT', credentials: 'include',
                    headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
                    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
                  });
                  const d = await r.json();
                  if (r.ok) { setPwMessage(t('settings.passwordChanged')); setOldPassword(''); setNewPassword(''); setConfirmNewPassword(''); }
                  else { setPwError(d.error || d.message || t('settings.requestFailed')); }
                } catch { setPwError(t('settings.requestFailed')); }
                finally { setPwChanging(false); }
              }}
              style={{
                background: '#1e3a5f', color: '#7dd3fc', border: 'none', borderRadius: 4,
                padding: '8px 16px', cursor: 'pointer', fontSize: 13,
                opacity: (pwChanging || !oldPassword || !newPassword) ? 0.5 : 1,
              }}
            >{pwChanging ? t('settings.changing') : t('settings.change')}</button>
          </div>
        </div>

        <div className="danger-zone">
          <div className="danger-zone-title">{t('settings.dangerZone')}</div>
          <p className="danger-zone-desc">{t('settings.dangerDescription')}</p>

          {!confirmDelete ? (
            <button
              className="danger-zone-btn"
              onClick={() => setConfirmDelete(true)}
              disabled={role === 'admin'}
            >
              {role === 'admin' ? t('settings.adminCannotDelete') : t('settings.deleteAccount')}
            </button>
          ) : (
            <div className="danger-zone-confirm">
              <input
                type="password"
                placeholder={t('settings.deleteConfirmPlaceholder')}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="danger-zone-input"
              />
              {error && <div className="danger-zone-error">{error}</div>}
              <div className="danger-zone-actions">
                <button onClick={() => { setConfirmDelete(false); setPassword(''); setError(''); }}>
                  {t('settings.cancel')}
                </button>
                <button className="danger-confirm-btn" onClick={handleDelete} disabled={deleting}>
                  {deleting ? t('settings.deleting') : t('settings.confirmDelete')}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
