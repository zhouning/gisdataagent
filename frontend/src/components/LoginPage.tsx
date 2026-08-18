import { useState, FormEvent } from 'react';
import { BrainCircuit, Database, Workflow } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { usePlatformBranding } from '../platformBranding';
import { getLocaleHeaders } from '../i18n';
import { getPasswordLoginErrorKey, passwordLogin } from '../authClient';
import LanguageSwitcher from './LanguageSwitcher';

interface LoginPageProps {
  onLoginSuccess: () => void;
}

export default function LoginPage({ onLoginSuccess }: LoginPageProps) {
  const { t } = useTranslation('common');
  const { branding } = usePlatformBranding();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const formData = new FormData();
      formData.append('username', username);
      formData.append('password', password);
      await passwordLogin(formData);
      onLoginSuccess();
    } catch (err: unknown) {
      // Do not render Chainlit's raw detail: it is not locale-aware and may
      // leak an English or Chinese server message into the selected locale.
      setError(t(getPasswordLoginErrorKey(err)));
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');

    if (password !== confirmPassword) {
      setError(t('auth.passwordMismatch'));
      return;
    }

    setLoading(true);
    try {
      const resp = await fetch('/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({ username, password, display_name: displayName, email }),
      });
      const data = await resp.json();
      if (data.status === 'success') {
        setSuccess(data.message || t('auth.registerSuccess'));
        setPassword('');
        setConfirmPassword('');
        setTimeout(() => { setMode('login'); setSuccess(''); }, 1500);
      } else {
        setError(data.message || t('auth.registerFailed'));
      }
    } catch {
      setError(t('auth.networkError'));
    } finally {
      setLoading(false);
    }
  };

  const switchMode = (newMode: 'login' | 'register') => {
    setMode(newMode);
    setError('');
    setSuccess('');
    setPassword('');
    setConfirmPassword('');
  };

  return (
    <div className="login-page">
      {/* Left: Brand showcase */}
      <div className="login-brand">
        <div className="login-brand-content">
          <div className="login-brand-logo">
            <img src="/public/logo_light.png" alt={branding.platform_name} className="login-logo-img" />
          </div>
          <h1 className="login-brand-title">{branding.platform_name}</h1>
          <p className="login-brand-subtitle">{branding.platform_subtitle}</p>

          <div className="login-brand-stats">
            <div className="login-stat">
              <span className="login-stat-value login-stat-value--word">{t('auth.unified')}</span>
              <span className="login-stat-label">{t('auth.metadataFabric')}</span>
            </div>
            <div className="login-stat">
              <span className="login-stat-value login-stat-value--word">{t('auth.governed')}</span>
              <span className="login-stat-label">{t('auth.dataLifecycle')}</span>
            </div>
            <div className="login-stat">
              <span className="login-stat-value login-stat-value--word">{t('auth.agentic')}</span>
              <span className="login-stat-label">{t('auth.operations')}</span>
            </div>
          </div>

          <div className="login-brand-features">
            <div className="login-feature">
              <Database aria-hidden="true" />
              <span>{t('auth.unifiedMetadata')}</span>
            </div>
            <div className="login-feature">
              <Workflow aria-hidden="true" />
              <span>{t('auth.governedDataOps')}</span>
            </div>
            <div className="login-feature">
              <BrainCircuit aria-hidden="true" />
              <span>{t('auth.geospatialWorldModel')}</span>
            </div>
          </div>

          <div className="login-brand-version">{t('auth.version')}</div>
        </div>

        {/* Animated background elements */}
        <div className="login-bg-grid"></div>
        <div className="login-bg-glow"></div>
      </div>

      {/* Right: Login form */}
      <div className="login-form-side">
        <div className="login-card">
          <div className="login-language-row"><LanguageSwitcher compact /></div>
          <h2>{mode === 'login' ? t('auth.welcomeBack') : t('auth.createAccount')}</h2>
          <p className="login-subtitle">
            {mode === 'login' ? t('auth.loginSubtitle') : t('auth.registerSubtitle')}
          </p>

        {mode === 'login' ? (
          <form onSubmit={handleLogin}>
            <div className="login-field">
              <label htmlFor="username">{t('auth.username')}</label>
              <div className="login-input-wrapper">
                <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
                </svg>
                <input
                  id="username" type="text" value={username} dir="ltr"
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder={t('auth.usernamePlaceholder')} autoFocus required autoComplete="username"
                />
              </div>
            </div>
            <div className="login-field">
              <label htmlFor="password">{t('auth.password')}</label>
              <div className="login-input-wrapper">
                <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                </svg>
                <input
                  id="password" type="password" value={password} dir="ltr"
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t('auth.passwordPlaceholder')} required autoComplete="current-password"
                />
              </div>
            </div>
            <button type="submit" className="login-btn" disabled={loading}>
              {loading ? t('auth.loggingIn') : t('auth.login')}
            </button>
            {error && <div className="login-error" role="alert" aria-live="assertive">{error}</div>}
          </form>
        ) : (
          <form onSubmit={handleRegister}>
            <div className="login-field">
              <label htmlFor="reg-username">{t('auth.username')}</label>
              <div className="login-input-wrapper">
                <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
                </svg>
                <input
                  id="reg-username" type="text" value={username} dir="ltr"
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder={t('auth.usernameRule')} autoFocus required autoComplete="username"
                  pattern="[a-zA-Z0-9_]{3,30}"
                />
              </div>
            </div>
            <div className="login-field">
              <label htmlFor="reg-email">{t('auth.emailOptional')}</label>
              <div className="login-input-wrapper">
                <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/>
                </svg>
                <input
                  id="reg-email" type="email" value={email} dir="ltr"
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder={t('auth.emailPlaceholder')} autoComplete="email"
                />
              </div>
            </div>
            <div className="login-field">
              <label htmlFor="reg-display">{t('auth.displayNameOptional')}</label>
              <div className="login-input-wrapper">
                <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>
                </svg>
                <input
                  id="reg-display" type="text" value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder={t('auth.displayNamePlaceholder')} autoComplete="name"
                />
              </div>
            </div>
            <div className="login-field">
              <label htmlFor="reg-password">{t('auth.password')}</label>
              <div className="login-input-wrapper">
                <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                </svg>
                <input
                  id="reg-password" type="password" value={password} dir="ltr"
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t('auth.passwordRule')} required minLength={8} autoComplete="new-password"
                />
              </div>
            </div>
            <div className="login-field">
              <label htmlFor="reg-confirm">{t('auth.confirmPassword')}</label>
              <div className="login-input-wrapper">
                <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
                <input
                  id="reg-confirm" type="password" value={confirmPassword} dir="ltr"
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder={t('auth.confirmPasswordPlaceholder')} required autoComplete="new-password"
                />
              </div>
            </div>
            <button type="submit" className="login-btn" disabled={loading}>
              {loading ? t('auth.registering') : t('auth.register')}
            </button>
            {error && <div className="login-error" role="alert" aria-live="assertive">{error}</div>}
            {success && <div className="login-success" role="status" aria-live="polite">{success}</div>}
          </form>
        )}

        <div className="login-register">
          {mode === 'login' ? (
            <>{t('auth.noAccount')} <a href="#" onClick={(e) => { e.preventDefault(); switchMode('register'); }}>{t('auth.goRegister')}</a></>
          ) : (
            <>{t('auth.hasAccount')} <a href="#" onClick={(e) => { e.preventDefault(); switchMode('login'); }}>{t('auth.goLogin')}</a></>
          )}
        </div>
        </div>
      </div>
    </div>
  );
}
