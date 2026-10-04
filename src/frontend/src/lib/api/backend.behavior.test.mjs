import { createStoreRuntime, installApiMock } from '../../../tests/helpers/storeRuntime.mjs';
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

let vite;
let backend;
let api;
let restoreFetch;
let previousIsTauri;
let previousWindow;
const requests = [];
let backendInfo;
const invoked = [];
let releaseActivation;
let activationStarted;
let restartError = null;

before(async () => {
  previousIsTauri = globalThis.isTauri;
  previousWindow = globalThis.window;
  globalThis.isTauri = true;
  globalThis.window = {
    localStorage: { getItem: () => null, setItem: () => {} },
    __TAURI_INTERNALS__: {
      invoke: async (command) => {
        invoked.push(command);
        if (command === 'activate_backup') {
          activationStarted?.();
          await new Promise((resolve) => { releaseActivation = resolve; });
          throw new Error('Backup swap failed');
        }
        if (command === 'backend_info') return backendInfo;
        if (command === 'restart_backend') {
          if (restartError) throw restartError;
          return backendInfo;
        }
        throw new Error(`Unexpected command: ${command}`);
      }
    }
  };
  vite = await createStoreRuntime(['src/lib/api/client.ts']);
  restoreFetch = installApiMock(async (request) => {
    requests.push({ url: request.url, token: request.headers.get('X-App-Token') });
    return new Response('[]', { status: 200, headers: { 'content-type': 'application/json' } });
  });
  backend = await vite.ssrLoadModule('/src/lib/api/backend.ts');
  ({ api } = await vite.ssrLoadModule('/src/lib/api/client.ts'));
});

after(async () => {
  try {
    restoreFetch?.();
    if (previousIsTauri === undefined) delete globalThis.isTauri;
    else globalThis.isTauri = previousIsTauri;
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  } finally {
    await vite?.close();
  }
});

test('failed backup activation reconnects and the cached API client uses the new port and token', async () => {
  backendInfo = { url: 'http://127.0.0.1:41001', token: 'old-token', log_dir: null };
  await backend.connectBackend();
  await api.GET('/courses');
  assert.deepEqual(requests.at(-1), {
    url: 'http://127.0.0.1:41001/api/courses', token: 'old-token'
  });

  backendInfo = { url: 'http://127.0.0.1:41002', token: 'fresh-token', log_dir: null };
  const starting = new Promise((resolve) => { activationStarted = resolve; });
  const activation = backend.activateBackup('backup-1');
  await starting;
  assert.equal(backend.backendConnected(), false);
  assert.equal(backend.apiBase(), '');
  const requestCount = requests.length;
  await assert.rejects(api.GET('/courses'), /backend is reconnecting/i);
  assert.equal(requests.length, requestCount);

  releaseActivation();
  await assert.rejects(activation, /Backup swap failed/);
  await api.GET('/courses');

  assert.deepEqual(invoked, ['backend_info', 'activate_backup', 'backend_info']);
  assert.deepEqual(requests.at(-1), {
    url: 'http://127.0.0.1:41002/api/courses', token: 'fresh-token'
  });
});

test('backend restart keeps failed connections unavailable and retry adopts a fresh launch', async () => {
  restartError = new Error('Backend executable is unavailable');
  await assert.rejects(backend.restartBackend(), /executable is unavailable/);
  assert.equal(backend.backendConnected(), false);
  await assert.rejects(api.GET('/courses'), /reconnecting/i);
  restartError = null;
  backendInfo = { url: 'http://127.0.0.1:41003', token: 'restart-token', log_dir: null };
  await backend.restartBackend();
  await api.GET('/courses');
  assert.deepEqual(requests.at(-1), {
    url: 'http://127.0.0.1:41003/api/courses', token: 'restart-token'
  });
});
