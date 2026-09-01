import { useState, useEffect, useCallback, useRef, useMemo, Component, type ReactNode } from 'react';
import { useChatSession, useAuth, useConfig } from '@chainlit/react-client';
import { useTranslation } from 'react-i18next';
import { useRecoilValue } from 'recoil';
import { sessionState } from '@chainlit/react-client';
import { MapContext, AppContext } from './contexts';
import LoginPage from './components/LoginPage';
import ChatPanel from './components/ChatPanel';
import MapPanel from './components/MapPanel';
import DataPanel from './components/DataPanel';
import AdminDashboard from './components/AdminDashboard';
import UserSettings from './components/UserSettings';
import StandaloneOntologyPage from './components/StandaloneOntologyPage';
import LanguageSwitcher from './components/LanguageSwitcher';
import { usePlatformBranding } from './platformBranding';
import i18n, { getLocale } from './i18n';
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
          <div className="error-boundary-title">{this.props.name}: {i18n.t('app.errorOccurred')}</div>
          <div className="error-boundary-msg">{this.state.error.message}</div>
          <button className="btn-secondary btn-sm" onClick={() => this.setState({ error: null })}>{i18n.t('app.retry')}</button>
        </div>
      );
    }
    return this.props.children;
  }
}

function GisDataAgentApp() {
  const { t } = useTranslation('common');
  const { branding } = usePlatformBranding();
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
      connect({ userEnv: { locale: getLocale() } });
    }
    if (!isAuthenticated) {
      hasConnected.current = false;
    }
  }, [isAuthenticated, connect]);

  const handleLoginSuccess = useCallback(async () => {
    await setUserFromAPI();
  }, [setUserFromAPI]);

  const handleMapUpdate = useCallback((cfg: any) => {
    (window as any).__lastMapUpdate = cfg;
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

  const handleDataWidthRequest = useCallback((requestedWidth: number) => {
    if (window.matchMedia('(max-width: 1024px)').matches) return;
    const fixedChromeWidth = 58;
    const minimumMapWidth = 480;
    const minimumChatWidth = 280;
    const availableForSidePanels = window.innerWidth - fixedChromeWidth - minimumMapWidth;
    const nextChatWidth = Math.max(
      minimumChatWidth,
      Math.min(chatWidth, availableForSidePanels - requestedWidth),
    );
    const maximumDataWidth = Math.max(
      320,
      availableForSidePanels - nextChatWidth,
    );
    setChatWidth(nextChatWidth);
    setDataWidth(Math.max(320, Math.min(requestedWidth, maximumDataWidth)));
  }, [chatWidth]);

  // --- Mobile adaptive layout ---
  const [activePanel, setActivePanel] = useState<'chat' | 'map' | 'data'>('chat');
  const [isMobile, setIsMobile] = useState(() => window.matchMedia('(max-width: 1024px)').matches);

  const handleAddMapLayer = useCallback((layer: any) => {
    if (!layer || layer.type !== 'mvt' || !layer.tile_url) return;

    setMapLayers((current) => {
      const identity = layer.layer_id || layer.publication_id || layer.tile_url;
      const existingIndex = current.findIndex((candidate) => (
        candidate.layer_id === identity
        || candidate.publication_id === layer.publication_id
        || candidate.tile_url === layer.tile_url
      ));
      const nextLayer = { ...layer, visible: true };
      if (existingIndex < 0) return [...current, nextLayer];
      return current.map((candidate, index) => (
        index === existingIndex ? { ...candidate, ...nextLayer } : candidate
      ));
    });

    if (
      Array.isArray(layer.center)
      && layer.center.length === 2
      && layer.center.every((value: unknown) => Number.isFinite(Number(value)))
    ) {
      setMapCenter([Number(layer.center[0]), Number(layer.center[1])]);
    }
    if (Number.isFinite(Number(layer.zoom))) setMapZoom(Number(layer.zoom));
    setActivePanel('map');
  }, []);

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
              <img src="/public/logo_light.png" alt={branding.platform_name} className="login-logo-img" />
            </div>
            <h1 className="login-brand-title">{branding.platform_name}</h1>
            <p className="login-brand-subtitle">{t('app.loading')}</p>
          </div>
          <div className="login-bg-grid"></div>
          <div className="login-bg-glow"></div>
        </div>
        <div className="login-form-side">
          <div className="login-card">
            <div className="login-language-row"><LanguageSwitcher compact /></div>
            <h2>{t('app.loading')}</h2>
          </div>
        </div>
      </div>
    );
  }

  // Show login if auth required and not authenticated
  if (authConfig?.requireLogin && !isAuthenticated) {
    return <LoginPage onLoginSuccess={handleLoginSuccess} />;
  }

  const displayName = user?.display_name || user?.identifier || t('app.user');
  const avatarLetter = (user?.identifier || 'U')[0].toUpperCase();
  const userRole = (user?.metadata as any)?.role || '';
  const isAdmin = userRole === 'admin';

  return (
    <div className="app-container">
      {/* --- Top Status Bar (40px) --- */}
      <header className="app-header">
        <div className="app-logo">
          <img src="/public/logo_light.png" alt={branding.platform_name} className="app-logo-img" />
          <span className="app-logo-text" title={branding.platform_name}>{branding.platform_name}</span>
        </div>
        <div className="header-spacer" />
        <div className="header-status">
          <span className="status-dot" />
          <span className="status-text">{t('app.ready')}</span>
        </div>
        <LanguageSwitcher />
        {isAdmin && (
          <button
            className={`header-admin-btn ${showAdmin ? 'active' : ''}`}
            onClick={() => setShowAdmin(!showAdmin)}
            title={showAdmin ? t('nav.workbench') : t('nav.adminPanel')}
          >
            <Shield size={15} />
            <span>{showAdmin ? t('nav.workbench') : t('nav.admin')}</span>
          </button>
        )}
        <div className="header-user" onClick={() => setShowUserMenu(!showUserMenu)}>
          <div className="header-avatar">{avatarLetter}</div>
          <span>{displayName}</span>
          <ChevronDown size={14} />
          {showUserMenu && (
            <div className="user-menu" onClick={(e) => e.stopPropagation()}>
              <button onClick={() => { setShowSettings(true); setShowUserMenu(false); }}>
                <Settings size={14} /> {t('nav.accountSettings')}
              </button>
              <button onClick={() => { logout(); window.location.href = '/'; }}>
                <LogOut size={14} /> {t('nav.logout')}
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
            <button className={`nav-btn ${activePanel === 'chat' ? 'active' : ''}`} title={t('nav.chat')} onClick={() => setActivePanel('chat')}>
              <MessageSquare size={20} />
            </button>
            <button className={`nav-btn ${activePanel === 'map' ? 'active' : ''}`} title={t('nav.map')} onClick={() => setActivePanel('map')}>
              <Map size={20} />
            </button>
            <button className={`nav-btn ${activePanel === 'data' ? 'active' : ''}`} title={t('nav.data')} onClick={() => setActivePanel('data')}>
              <LayoutGrid size={20} />
            </button>
            <div className="nav-spacer" />
            <button className="nav-btn" title={t('nav.notifications')}>
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
              <ErrorBoundary name={t('nav.chat')}>
                <ChatPanel onMapUpdate={handleMapUpdate} onDataUpdate={handleDataUpdate} onLayerControl={handleLayerControl} />
              </ErrorBoundary>
            )}
            {!isMobile && (
              <div className={`panel-resizer${dragging.current === 'chat' ? ' dragging' : ''}`}
                onMouseDown={onResizeStart('chat')} />
            )}
            {(!isMobile || activePanel === 'map') && (
              <ErrorBoundary name={t('nav.mapPanel')}>
                <MapPanel layers={mapLayers} center={mapCenter} zoom={mapZoom} layerControl={layerControl} />
              </ErrorBoundary>
            )}
            {!isMobile && (
              <div className={`panel-resizer${dragging.current === 'data' ? ' dragging' : ''}`}
                onMouseDown={onResizeStart('data')} />
            )}
            {(!isMobile || activePanel === 'data') && (
              <ErrorBoundary name={t('nav.dataPanel')}>
                <DataPanel
                  dataFile={dataFile}
                  userRole={userRole}
                  username={user?.identifier || ''}
                  onRequestWidth={handleDataWidthRequest}
                  onAddMapLayer={handleAddMapLayer}
                />
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
            <span>{t('nav.conversation')}</span>
          </button>
          <button className={`mobile-tab-btn${activePanel === 'map' ? ' active' : ''}`} onClick={() => setActivePanel('map')}>
            <Map size={20} />
            <span>{t('nav.map')}</span>
          </button>
          <button className={`mobile-tab-btn${activePanel === 'data' ? ' active' : ''}`} onClick={() => setActivePanel('data')}>
            <LayoutGrid size={20} />
            <span>{t('nav.data')}</span>
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

/**
 * The CIM integration page is deliberately routed before the authenticated
 * workbench. It has its own read-only backend surface and never invokes the
 * Chainlit login flow.
 */
export default function App() {
  const pathname = window.location.pathname.replace(/\/+$/, '') || '/';
  if (pathname.endsWith('/ontology-model')) return <StandaloneOntologyPage />;
  return <GisDataAgentApp />;
}
