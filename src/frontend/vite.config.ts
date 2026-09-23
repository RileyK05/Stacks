import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import type { IncomingMessage } from 'node:http';
import { defineConfig, type ProxyOptions } from 'vite';

const proxyTarget = process.env.API_PROXY_TARGET ?? 'http://localhost:8000';

// API prefixes double as SPA routes (/courses/<id> is both a page and an
// endpoint). A browser navigation asks for HTML and must get the app, not
// the API — otherwise refreshing a course page shows raw JSON.
function serveAppForPageLoads(req: IncomingMessage): string | undefined {
  return req.headers.accept?.includes('text/html') ? req.url : undefined;
}

const apiProxy: ProxyOptions = {
  target: proxyTarget,
  changeOrigin: true,
  bypass: serveAppForPageLoads
};

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  server: {
    proxy: {
      '/auth': apiProxy,
      '/courses': apiProxy,
      '/course-archives': apiProxy,
      '/course-memories': apiProxy
    }
  }
});
