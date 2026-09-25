import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

const proxyTarget = process.env.API_PROXY_TARGET ?? 'http://localhost:8000';

// `tauri dev` loads this dev server (fixed port, see src-tauri/tauri.conf.json)
// and the app talks to its own backend directly. In a plain browser, next
// to `uvicorn src.backend.main:app`, the proxy forwards /api instead.
export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: proxyTarget, changeOrigin: true }
    }
  }
});
