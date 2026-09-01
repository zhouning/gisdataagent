import React from 'react';
import ReactDOM from 'react-dom/client';
import { RecoilRoot } from 'recoil';
import { ChainlitAPI, ChainlitContext } from '@chainlit/react-client';
import './i18n';
import App from './App';
import IrrigationWorldModelDemoTab from './components/datapanel/IrrigationWorldModelDemoTab';
import { PlatformBrandingProvider } from './platformBranding';
import './styles/layout.css';

const CHAINLIT_SERVER = window.location.origin;
const apiClient = new ChainlitAPI(CHAINLIT_SERVER, 'webapp');

// v24.0: Register Service Worker for offline mode and citywide SWMM build.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
      navigator.serviceWorker.register('/public/sw.js?version=25-i18n').catch(() => {
      // Non-fatal: SW registration may fail in dev mode
    });
  });
}

const standaloneIrrigationDemo = window.location.pathname === '/odiwm-demo';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {standaloneIrrigationDemo ? <IrrigationWorldModelDemoTab /> : (
      <ChainlitContext.Provider value={apiClient}>
        <RecoilRoot>
          <PlatformBrandingProvider>
            <App />
          </PlatformBrandingProvider>
        </RecoilRoot>
      </ChainlitContext.Provider>
    )}
  </React.StrictMode>
);
