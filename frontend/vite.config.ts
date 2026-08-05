import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const backendTarget = loadEnv(mode, '.', '').VITE_PROXY_TARGET || 'http://localhost:8000';
  const ontologyTarget = process.env.VITE_ONTOLOGY_PROXY_TARGET
    || loadEnv(mode, '.', '').VITE_ONTOLOGY_PROXY_TARGET
    || backendTarget;
  const websocketTarget = backendTarget.replace(/^http/, 'ws');
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api/ontology': ontologyTarget,
        '/ws/socket.io': {
          target: websocketTarget,
          ws: true,
        },
        '/api': backendTarget,
        '/auth': backendTarget,
        '/login': backendTarget,
        '/logout': backendTarget,
        '/user': backendTarget,
        '/project': backendTarget,
        '/set-session-cookie': backendTarget,
        '/register': backendTarget,
        '/public': backendTarget,
      },
    },
  };
});
