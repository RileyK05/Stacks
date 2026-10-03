import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

export function createStoreRuntime(entries) {
  return createServer({
    configFile: fileURLToPath(new URL('../../vite.config.ts', import.meta.url)),
    optimizeDeps: { entries, noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false },
    appType: 'custom'
  });
}

export function installApiMock(respond) {
  const OriginalRequest = globalThis.Request;
  const originalFetch = globalThis.fetch;
  globalThis.Request = class extends OriginalRequest {
    constructor(input, init) {
      super(typeof input === 'string' && input.startsWith('/')
        ? new URL(input, 'http://localhost') : input, init);
    }
  };
  globalThis.fetch = (request, init) => respond(request instanceof globalThis.Request
    ? request : new globalThis.Request(request, init));
  return () => {
    globalThis.Request = OriginalRequest;
    globalThis.fetch = originalFetch;
  };
}

export function jsonResponse(data, status = 200) {
  return new Response(status === 204 ? null : JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json' }
  });
}
