import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/ws/socket.io': {
        target: 'ws://localhost:8000',
        ws: true,
      },
      '/api': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
      '/login': 'http://localhost:8000',
      '/logout': 'http://localhost:8000',
      '/user': 'http://localhost:8000',
      '/project': 'http://localhost:8000',
      '/set-session-cookie': 'http://localhost:8000',
      '/register': 'http://localhost:8000',
      '/public': 'http://localhost:8000',
    },
  },
});
