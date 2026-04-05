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
import {
  MessageSquare, Map, LayoutGrid, Settings, Bell, User, LogOut, ChevronDown, Shield,
} from 'lucide-react';

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

  // --- Mobile adaptive layout ---
  const [activePanel, setActivePanel] = useState<'chat' | 'map' | 'data'>('chat');
  const [isMobile, setIsMobile] = useState(() => window.matchMedia('(max-width: 1024px)').matches);
  useEffect(() => {
    const mql = window.matchMedia('(max-width: 1024px)');
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, []);

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
        <div className="login-brand">
          <div className="login-brand-content">
            <div className="login-brand-logo">
              <img src="/public/logo_light.png" alt="Data Agent" className="login-logo-img" />
            </div>
            <h1 className="login-brand-title">GIS Data Agent</h1>
            <p className="login-brand-subtitle">Loading...</p>
          </div>
          <div className="login-bg-grid"></div>
          <div className="login-bg-glow"></div>
        </div>
        <div className="login-form-side">
          <div className="login-card">
            <h2>Loading...</h2>
          </div>
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
      {/* --- Top Status Bar (40px) --- */}
      <header className="app-header">
        <div className="app-logo">
          <img src="/public/logo_light.png" alt="Data Agent" className="app-logo-img" />
          <span className="app-logo-text">GIS Data Agent</span>
        </div>
        <div className="header-spacer" />
        <div className="header-status">
          <span className="status-dot" />
          <span className="status-text">Ready</span>
        </div>
        {isAdmin && (
          <button
            className={`header-admin-btn ${showAdmin ? 'active' : ''}`}
            onClick={() => setShowAdmin(!showAdmin)}
            title={showAdmin ? '返回工作台' : '管理后台'}
          >
            <Shield size={15} />
            <span>{showAdmin ? '工作台' : '管理'}</span>
          </button>
        )}
        <div className="header-user" onClick={() => setShowUserMenu(!showUserMenu)}>
          <div className="header-avatar">{avatarLetter}</div>
          <span>{displayName}</span>
          <ChevronDown size={14} />
          {showUserMenu && (
            <div className="user-menu" onClick={(e) => e.stopPropagation()}>
              <button onClick={() => { setShowSettings(true); setShowUserMenu(false); }}>
                <Settings size={14} /> 账户设置
              </button>
              <button onClick={() => { logout(); window.location.href = '/'; }}>
                <LogOut size={14} /> 退出登录
              </button>
            </div>
          )}
        </div>
      </header>

      {/* --- Main Content Area --- */}
      <div className="app-body">
        {/* --- Left AppNav Icon Rail (48px) --- */}
        {!isMobile && (
          <nav className="app-nav">
            <button className={`nav-btn ${activePanel === 'chat' ? 'active' : ''}`} title="工作区" onClick={() => setActivePanel('chat')}>
              <MessageSquare size={20} />
            </button>
            <button className={`nav-btn ${activePanel === 'map' ? 'active' : ''}`} title="地图视图" onClick={() => setActivePanel('map')}>
              <Map size={20} />
            </button>
            <button className={`nav-btn ${activePanel === 'data' ? 'active' : ''}`} title="数据面板" onClick={() => setActivePanel('data')}>
              <LayoutGrid size={20} />
            </button>
            <div className="nav-spacer" />
            <button className="nav-btn" title="通知">
              <Bell size={20} />
            </button>
          </nav>
        )}

        {/* --- Workspace Panels --- */}
        {showAdmin ? (
          <AdminDashboard onBack={() => setShowAdmin(false)} />
        ) : (
          <div className="workspace" ref={workspaceRef}
            style={{ '--chat-width': `${chatWidth}px`, '--data-width': `${dataWidth}px` } as React.CSSProperties}>
            {(!isMobile || activePanel === 'chat') && (
              <ErrorBoundary name="聊天面板">
                <ChatPanel onMapUpdate={handleMapUpdate} onDataUpdate={handleDataUpdate} onLayerControl={handleLayerControl} />
              </ErrorBoundary>
            )}
            {!isMobile && (
              <div className={`panel-resizer${dragging.current === 'chat' ? ' dragging' : ''}`}
                onMouseDown={onResizeStart('chat')} />
            )}
            {(!isMobile || activePanel === 'map') && (
              <ErrorBoundary name="地图面板">
                <MapPanel layers={mapLayers} center={mapCenter} zoom={mapZoom} layerControl={layerControl} />
              </ErrorBoundary>
            )}
            {!isMobile && (
              <div className={`panel-resizer${dragging.current === 'data' ? ' dragging' : ''}`}
                onMouseDown={onResizeStart('data')} />
            )}
            {(!isMobile || activePanel === 'data') && (
              <ErrorBoundary name="数据面板">
                <DataPanel dataFile={dataFile} userRole={userRole} />
              </ErrorBoundary>
            )}
          </div>
        )}
      </div>

      {/* Mobile bottom tab bar */}
      {isMobile && !showAdmin && (
        <div className="mobile-tab-bar">
          <button className={`mobile-tab-btn${activePanel === 'chat' ? ' active' : ''}`} onClick={() => setActivePanel('chat')}>
            <MessageSquare size={20} />
            <span>对话</span>
          </button>
          <button className={`mobile-tab-btn${activePanel === 'map' ? ' active' : ''}`} onClick={() => setActivePanel('map')}>
            <Map size={20} />
            <span>地图</span>
          </button>
          <button className={`mobile-tab-btn${activePanel === 'data' ? ' active' : ''}`} onClick={() => setActivePanel('data')}>
            <LayoutGrid size={20} />
            <span>数据</span>
          </button>
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
