import createClient, { type Middleware } from 'openapi-fetch';
import { APP_TOKEN_HEADER, apiBase, appToken } from '$lib/api/backend';
import { logRequest } from '$lib/stores/debug.svelte';
import { ApiError } from './errors';
import type { paths } from './schema';

const startTimes = new WeakMap<Request, number>();

function requestPath(request: Request): string {
  const url = new URL(request.url);
  return url.pathname + url.search;
}

const appMiddleware: Middleware = {
  async onRequest({ request }) {
    startTimes.set(request, performance.now());
    const token = appToken();
    if (token) request.headers.set(APP_TOKEN_HEADER, token);
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
    throw error;
  }
};

type Client = ReturnType<typeof createClient<paths>>;

// Created on first use: the root layout connects to the backend before any
// page loads, so by then apiBase() is the desktop backend's address.
let rawClient: Client | null = null;

function client(): Client {
  if (rawClient === null) {
    rawClient = createClient<paths>({ baseUrl: apiBase() });
    rawClient.use(appMiddleware);
  }
  return rawClient;
}

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

export const api = new Proxy({} as Client, {
  get(_target, prop) {
    const target = client();
    const value = Reflect.get(target, prop, target);
    return typeof value === 'function' ? wrap(value.bind(target)) : value;
  }
});
