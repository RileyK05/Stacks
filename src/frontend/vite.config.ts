import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

const proxyTarget = process.env.API_PROXY_TARGET ?? 'http://localhost:8000';

// Dev only: the backend serves the built SPA and the API from one origin,
// so in development the Vite server forwards /api to it. The API lives
// under its own prefix, so no SPA route can collide with an endpoint.
export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  server: {
    proxy: {
      '/api': { target: proxyTarget, changeOrigin: true }
    }
  }
});
