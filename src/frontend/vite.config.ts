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
  // Crawl every route for dependencies at startup. Otherwise the first visit
  // to a lazily loaded route (the companion window, Settings) can discover a
  // new dependency, re-bundle, and answer the pages already open with 504
  // "Outdated Optimize Dep": a window stuck on the splash until restarted.
  optimizeDeps: { entries: ['src/**/*.svelte', 'src/**/*.ts', '!src/**/*.test.*'] },
  server: {
    port: 5173,
    strictPort: true,
    // The Rust shell and its build output live under src-tauri/; watching
    // them only burns time (and trips over files the compiler has locked).
    watch: { ignored: ['**/src-tauri/**'] },
    proxy: {
      '/api': { target: proxyTarget, changeOrigin: true }
    }
  }
});
