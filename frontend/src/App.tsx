import { useState, useEffect, useCallback } from 'react';
import { useChatSession, useAuth, useConfig } from '@chainlit/react-client';
import { useRecoilValue } from 'recoil';
import { sessionState } from '@chainlit/react-client';
import LoginPage from './components/LoginPage';
import ChatPanel from './components/ChatPanel';
import MapPanel from './components/MapPanel';
import DataPanel from './components/DataPanel';

export default function App() {
  const { data: authConfig, user, isReady, isAuthenticated, setUserFromAPI } = useAuth();
  const { config } = useConfig();
  const { connect, session } = useChatSession();
  const sessionRecoil = useRecoilValue(sessionState);

  // Map layer state shared between Chat and Map panels
  const [mapLayers, setMapLayers] = useState<any[]>([]);
  const [mapCenter, setMapCenter] = useState<[number, number]>([30.5, 114.3]);
  const [mapZoom, setMapZoom] = useState(5);

  // Data panel state
  const [dataFile, setDataFile] = useState<string | null>(null);

  // Connect to Socket.IO after authentication
  useEffect(() => {
    if (isAuthenticated && !sessionRecoil?.socket?.connected) {
      connect({ userEnv: {} });
    }
  }, [isAuthenticated, connect, sessionRecoil]);

  const handleLoginSuccess = useCallback(async () => {
    await setUserFromAPI();
  }, [setUserFromAPI]);

  const handleMapUpdate = useCallback((cfg: any) => {
    if (cfg.layers) setMapLayers(cfg.layers);
    if (cfg.center) setMapCenter(cfg.center);
    if (cfg.zoom) setMapZoom(cfg.zoom);
  }, []);

  const handleDataUpdate = useCallback((file: string) => {
    setDataFile(file);
  }, []);

  // Show loading while checking auth
  if (!isReady) {
    return (
      <div className="login-page">
        <div className="login-card">
          <div className="login-logo">
            <div className="login-logo-icon">G</div>
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

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="app-logo">
          <div className="app-logo-icon">G</div>
          <span>GIS Data Agent</span>
        </div>
        <div className="header-spacer" />
        <div className="header-user">
          <div className="header-avatar">{avatarLetter}</div>
          <span>{displayName}</span>
        </div>
      </header>
      <div className="workspace">
        <ChatPanel onMapUpdate={handleMapUpdate} onDataUpdate={handleDataUpdate} />
        <MapPanel layers={mapLayers} center={mapCenter} zoom={mapZoom} />
        <DataPanel dataFile={dataFile} />
      </div>
    </div>
  );
}
