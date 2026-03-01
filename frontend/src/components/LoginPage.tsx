import { useState, useContext, FormEvent } from 'react';
import { ChainlitContext } from '@chainlit/react-client';

interface LoginPageProps {
  onLoginSuccess: () => void;
}

export default function LoginPage({ onLoginSuccess }: LoginPageProps) {
  const apiClient = useContext(ChainlitContext);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
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

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">
          <div className="login-logo-icon">G</div>
        </div>
        <h1>GIS Data Agent</h1>
        <p className="login-subtitle">AI 空间数据分析平台</p>
        <form onSubmit={handleSubmit}>
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
        <div className="login-register">
          没有账号？<a href="/register" target="_blank">点击注册</a>
        </div>
      </div>
    </div>
  );
}
