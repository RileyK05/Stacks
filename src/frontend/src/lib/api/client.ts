import { goto } from '$app/navigation';
import createClient, { type Middleware } from 'openapi-fetch';
import { clearToken, loadToken } from '$lib/auth/token';
import { logRequest } from '$lib/stores/debug.svelte';
import { ApiError } from './errors';
import type { paths } from './schema';

const baseUrl = (import.meta.env.PUBLIC_API_BASE as string | undefined) ?? '';

const rawClient = createClient<paths>({ baseUrl });

const startTimes = new WeakMap<Request, number>();

function requestPath(request: Request): string {
  const url = new URL(request.url);
  return url.pathname + url.search;
}

const authMiddleware: Middleware = {
  async onRequest({ request }) {
    startTimes.set(request, performance.now());
    const token = loadToken();
    if (token) request.headers.set('Authorization', `Bearer ${token}`);
    return request;
  },
  async onResponse({ request, response }) {
    const durationMs = Math.round(
      performance.now() - (startTimes.get(request) ?? performance.now())
    );
    if (response.ok) {
      logRequest({
        method: request.method,
        path: requestPath(request),
        status: response.status,
        durationMs,
        errorKind: null,
        errorMessage: null
      });
      return response;
    }
    const error = await ApiError.fromResponse(response.clone());
    logRequest({
      method: request.method,
      path: requestPath(request),
      status: response.status,
      durationMs,
      errorKind: error.kind,
      errorMessage: error.message
    });
    if (error.kind === 'unauthorized' && loadToken()) {
      // A stored token was rejected (expired or password changed) — only
      // then bounce to login, preserving where the user was headed. A bare
      // 401 (e.g. wrong password on /auth/login) must not navigate.
      clearToken();
      const here = window.location.pathname + window.location.search;
      void goto(`/login?next=${encodeURIComponent(here)}`);
    }
    throw error;
  }
};

rawClient.use(authMiddleware);

// Fetch-level failures (server down, DNS, CORS) never reach the middleware
// chain, so convert them here — every caller can rely on ApiError alone.
function wrap<Args extends unknown[], Return>(fn: (...args: Args) => Promise<Return>) {
  return async (...args: Args): Promise<Return> => {
    try {
      return await fn(...args);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      const networkError = ApiError.fromNetworkError(err);
      if (typeof args[0] === 'string') {
        const init = args[1] as { method?: string } | undefined;
        logRequest({
          method: init?.method ?? 'GET',
          path: args[0],
          status: 0,
          durationMs: 0,
          errorKind: networkError.kind,
          errorMessage: networkError.message
        });
      }
      throw networkError;
    }
  };
}

export const api = new Proxy(rawClient, {
  get(target, prop, receiver) {
    const value = Reflect.get(target, prop, receiver);
    return typeof value === 'function' ? wrap(value.bind(target)) : value;
  }
});
