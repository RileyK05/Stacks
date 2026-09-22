import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

const proxyTarget = process.env.API_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  server: {
    proxy: {
      '/auth': { target: proxyTarget, changeOrigin: true },
      '/courses': { target: proxyTarget, changeOrigin: true },
      '/course-archives': { target: proxyTarget, changeOrigin: true },
      '/course-memories': { target: proxyTarget, changeOrigin: true }
    }
  }
});
