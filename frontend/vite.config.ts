import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000';
const gwmApiProxyTarget = process.env.VITE_GWM_API_PROXY_TARGET || apiProxyTarget;

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // During an isolated local demo the new GWM API can run separately from
      // the shared application backend, without changing the default route.
      '/api/abu-dhabi/flood/gwm': gwmApiProxyTarget,
      '/ws/socket.io': {
        target: apiProxyTarget.replace(/^http/, 'ws'),
        ws: true,
      },
      '/api': apiProxyTarget,
      '/auth': apiProxyTarget,
      '/login': apiProxyTarget,
      '/logout': apiProxyTarget,
      '/user': apiProxyTarget,
      '/project': apiProxyTarget,
      '/set-session-cookie': apiProxyTarget,
      '/register': apiProxyTarget,
      '/public': apiProxyTarget,
    },
  },
});
