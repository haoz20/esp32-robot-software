import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // Relative asset paths so `npm run build` output can be opened straight from
  // the filesystem (file://) as well as served over HTTP.
  base: './',
  server: {
    host: true, // reachable from other devices on the same WiFi as the robot
  },
});
