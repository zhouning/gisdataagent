import { useState, useContext, FormEvent } from 'react';
import { ChainlitContext } from '@chainlit/react-client';

interface LoginPageProps {
  onLoginSuccess: () => void;
}

export default function LoginPage({ onLoginSuccess }: LoginPageProps) {
  const apiClient = useContext(ChainlitContext);
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
      await apiClient.passwordAuth(formData);
      onLoginSuccess();
    } catch (err: any) {
      if (err?.detail) setError(err.detail);
      else if (err?.message) setError(err.message);
      else setError('登录失败，请检查用户名和密码');
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');

    if (password !== confirmPassword) {
      setError('两次输入的密码不一致');
      return;
    }

    setLoading(true);
    try {
      const resp = await fetch('/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, display_name: displayName, email }),
      });
      const data = await resp.json();
      if (data.status === 'success') {
        setSuccess(data.message || '注册成功，请登录');
        setPassword('');
        setConfirmPassword('');
        setTimeout(() => { setMode('login'); setSuccess(''); }, 1500);
      } else {
        setError(data.message || '注册失败');
      }
    } catch {
      setError('网络错误，请稍后重试');
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
      <div className="login-card">
        <div className="login-logo">
          <img src="/public/logo_light.png" alt="Data Agent" className="login-logo-img" />
        </div>
        <h1>GIS Data Agent</h1>
        <p className="login-subtitle">
          {mode === 'login' ? 'AI 空间数据分析平台' : '创建新账号'}
        </p>

        {mode === 'login' ? (
          <form onSubmit={handleLogin}>
            <div className="login-field">
              <label htmlFor="username">用户名</label>
              <div className="login-input-wrapper">
                <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
                </svg>
                <input
                  id="username" type="text" value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="输入用户名" autoFocus required
                />
              </div>
            </div>
            <div className="login-field">
              <label htmlFor="password">密码</label>
              <div className="login-input-wrapper">
                <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                </svg>
                <input
                  id="password" type="password" value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="输入密码" required
                />
              </div>
            </div>
            <button type="submit" className="login-btn" disabled={loading}>
              {loading ? '登录中...' : '登录'}
            </button>
            {error && <div className="login-error">{error}</div>}
          </form>
        ) : (
          <form onSubmit={handleRegister}>
            <div className="login-field">
              <label htmlFor="reg-username">用户名</label>
              <div className="login-input-wrapper">
                <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
                </svg>
                <input
                  id="reg-username" type="text" value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="3-30位字母、数字或下划线" autoFocus required
                  pattern="[a-zA-Z0-9_]{3,30}"
                />
              </div>
            </div>
            <div className="login-field">
              <label htmlFor="reg-email">邮箱 (可选)</label>
              <div className="login-input-wrapper">
                <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/>
                </svg>
                <input
                  id="reg-email" type="email" value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="your@email.com"
                />
              </div>
            </div>
            <div className="login-field">
              <label htmlFor="reg-display">显示名称 (可选)</label>
              <div className="login-input-wrapper">
                <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>
                </svg>
                <input
                  id="reg-display" type="text" value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="显示在界面上的名称"
                />
              </div>
            </div>
            <div className="login-field">
              <label htmlFor="reg-password">密码</label>
              <div className="login-input-wrapper">
                <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                </svg>
                <input
                  id="reg-password" type="password" value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="至少8位，含字母和数字" required minLength={8}
                />
              </div>
            </div>
            <div className="login-field">
              <label htmlFor="reg-confirm">确认密码</label>
              <div className="login-input-wrapper">
                <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
                <input
                  id="reg-confirm" type="password" value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="再次输入密码" required
                />
              </div>
            </div>
            <button type="submit" className="login-btn" disabled={loading}>
              {loading ? '注册中...' : '注册'}
            </button>
            {error && <div className="login-error">{error}</div>}
            {success && <div className="login-success">{success}</div>}
          </form>
        )}

        <div className="login-register">
          {mode === 'login' ? (
            <>没有账号？<a href="#" onClick={(e) => { e.preventDefault(); switchMode('register'); }}>点击注册</a></>
          ) : (
            <>已有账号？<a href="#" onClick={(e) => { e.preventDefault(); switchMode('login'); }}>返回登录</a></>
          )}
        </div>
      </div>
    </div>
  );
}
