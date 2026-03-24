import { useState, useEffect, useCallback, useRef, useMemo, Component, type ReactNode } from 'react';
import { useChatSession, useAuth, useConfig } from '@chainlit/react-client';
import { useRecoilValue } from 'recoil';
import { sessionState } from '@chainlit/react-client';
import { MapContext, AppContext } from './contexts';
import LoginPage from './components/LoginPage';
import ChatPanel from './components/ChatPanel';
import MapPanel from './components/MapPanel';
import DataPanel from './components/DataPanel';
import AdminDashboard from './components/AdminDashboard';
import UserSettings from './components/UserSettings';

/* --- Error Boundary (F-4 fix) --- */
class ErrorBoundary extends Component<{ name: string; children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: any) {
    console.error(`[ErrorBoundary:${this.props.name}]`, error, info?.componentStack);
  }
  render() {
    if (this.state.error) {
      return (
        <div className="error-boundary">
          <div className="error-boundary-icon">!</div>
          <div className="error-boundary-title">{this.props.name} 发生错误</div>
          <div className="error-boundary-msg">{this.state.error.message}</div>
          <button className="btn-secondary btn-sm" onClick={() => this.setState({ error: null })}>重试</button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  const { data: authConfig, user, isReady, isAuthenticated, setUserFromAPI, logout } = useAuth();
  const { config } = useConfig();
  const { connect, session } = useChatSession();
  const sessionRecoil = useRecoilValue(sessionState);

  // Map layer state shared between Chat and Map panels
  const [mapLayers, setMapLayers] = useState<any[]>([]);
  const [mapCenter, setMapCenter] = useState<[number, number]>([30.5, 114.3]);
  const [mapZoom, setMapZoom] = useState(5);
  const [layerControl, setLayerControl] = useState<any>(null);

  // Data panel state
  const [dataFile, setDataFile] = useState<string | null>(null);

  // Admin dashboard state
  const [showAdmin, setShowAdmin] = useState(false);

  // User settings modal state
  const [showSettings, setShowSettings] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);

  // Connect to Socket.IO once after authentication
  const hasConnected = useRef(false);
  useEffect(() => {
    if (isAuthenticated && !hasConnected.current) {
      hasConnected.current = true;
      connect({ userEnv: {} });
    }
    if (!isAuthenticated) {
      hasConnected.current = false;
    }
  }, [isAuthenticated, connect]);

  const handleLoginSuccess = useCallback(async () => {
    await setUserFromAPI();
  }, [setUserFromAPI]);

  const handleMapUpdate = useCallback((cfg: any) => {
    if (cfg.layers) setMapLayers(cfg.layers);
    if (cfg.center) setMapCenter(cfg.center);
    if (cfg.zoom) setMapZoom(cfg.zoom);
  }, []);

  // Expose handleMapUpdate globally so DataPanel tabs (e.g., WorldModelTab) can trigger map updates
  useEffect(() => {
    (window as any).__handleMapUpdate = handleMapUpdate;
    return () => { delete (window as any).__handleMapUpdate; };
  }, [handleMapUpdate]);

  const handleLayerControl = useCallback((control: any) => {
    setLayerControl({ ...control, _ts: Date.now() });
  }, []);

  const handleDataUpdate = useCallback((file: string) => {
    setDataFile(file);
  }, []);

  // --- Resizable panels ---
  const workspaceRef = useRef<HTMLDivElement>(null);
  const [chatWidth, setChatWidth] = useState(360);
  const [dataWidth, setDataWidth] = useState(340);
  const dragging = useRef<'chat' | 'data' | null>(null);

  const onResizeStart = useCallback((panel: 'chat' | 'data') => (e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = panel;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const startX = e.clientX;
    const startChat = chatWidth;
    const startData = dataWidth;

    const onMove = (ev: MouseEvent) => {
      const dx = ev.clientX - startX;
      if (dragging.current === 'chat') {
        setChatWidth(Math.max(240, Math.min(600, startChat + dx)));
      } else {
        setDataWidth(Math.max(240, Math.min(700, startData - dx)));
      }
    };
    const onUp = () => {
      dragging.current = null;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [chatWidth, dataWidth]);

  // Show loading while checking auth
  if (!isReady) {
    return (
      <div className="login-page">
        <div className="login-card">
          <div className="login-logo">
            <img src="/public/logo_light.png" alt="Data Agent" className="login-logo-img" />
          </div>
          <h1>GIS Data Agent</h1>
          <p className="login-subtitle">Loading...</p>
        </div>
      </div>
    );
  }

  // Show login if auth required and not authenticated
  if (authConfig?.requireLogin && !isAuthenticated) {
    return <LoginPage onLoginSuccess={handleLoginSuccess} />;
  }

  const displayName = user?.display_name || user?.identifier || 'User';
  const avatarLetter = (user?.identifier || 'U')[0].toUpperCase();
  const userRole = (user?.metadata as any)?.role || '';
  const isAdmin = userRole === 'admin';

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="app-logo">
          <img src="/public/logo_light.png" alt="Data Agent" className="app-logo-img" />
        </div>
        <div className="header-spacer" />
        {isAdmin && (
          <button
            className={`header-admin-btn ${showAdmin ? 'active' : ''}`}
            onClick={() => setShowAdmin(!showAdmin)}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
            </svg>
            <span>{showAdmin ? '返回工作台' : '管理后台'}</span>
          </button>
        )}
        <div className="header-user" onClick={() => setShowUserMenu(!showUserMenu)}>
          <div className="header-avatar">{avatarLetter}</div>
          <span>{displayName}</span>
          {showUserMenu && (
            <div className="user-menu" onClick={(e) => e.stopPropagation()}>
              <button onClick={() => { setShowSettings(true); setShowUserMenu(false); }}>
                账户设置
              </button>
              <button onClick={() => { logout(); window.location.href = '/'; }}>
                退出登录
              </button>
            </div>
          )}
        </div>
      </header>
      {showAdmin ? (
        <AdminDashboard onBack={() => setShowAdmin(false)} />
      ) : (
        <div className="workspace" ref={workspaceRef}
          style={{ '--chat-width': `${chatWidth}px`, '--data-width': `${dataWidth}px` } as React.CSSProperties}>
          <ErrorBoundary name="聊天面板">
            <ChatPanel onMapUpdate={handleMapUpdate} onDataUpdate={handleDataUpdate} onLayerControl={handleLayerControl} />
          </ErrorBoundary>
          <div className={`panel-resizer${dragging.current === 'chat' ? ' dragging' : ''}`}
            onMouseDown={onResizeStart('chat')} />
          <ErrorBoundary name="地图面板">
            <MapPanel layers={mapLayers} center={mapCenter} zoom={mapZoom} layerControl={layerControl} />
          </ErrorBoundary>
          <div className={`panel-resizer${dragging.current === 'data' ? ' dragging' : ''}`}
            onMouseDown={onResizeStart('data')} />
          <ErrorBoundary name="数据面板">
            <DataPanel dataFile={dataFile} userRole={userRole} />
          </ErrorBoundary>
        </div>
      )}
      {showSettings && (
        <UserSettings
          username={user?.identifier || ''}
          displayName={displayName}
          role={userRole}
          onClose={() => setShowSettings(false)}
          onDeleted={() => { window.location.href = '/'; }}
        />
      )}
    </div>
  );
}
