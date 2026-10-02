import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { proxy } from 'svelte/internal/client';
import { createServer } from 'vite';

let vite;
let OpenArtifact;
let originalRequest;
let originalFetch;
let respond;
let fetchCalls;

before(async () => {
  vite = await createServer({
    configFile: fileURLToPath(new URL('../../../vite.config.ts', import.meta.url)),
    optimizeDeps: { entries: ['src/lib/stores/artifact.svelte.ts'], noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false },
    appType: 'custom'
  });

  originalRequest = globalThis.Request;
  originalFetch = globalThis.fetch;
  globalThis.Request = class extends originalRequest {
    constructor(input, init) {
      super(typeof input === 'string' && input.startsWith('/') ? new URL(input, 'http://localhost') : input, init);
    }
  };
  fetchCalls = [];
  globalThis.fetch = async (request, init) => {
    const normalized = request instanceof globalThis.Request ? request : new globalThis.Request(request, init);
    fetchCalls.push({ method: normalized.method, path: new URL(normalized.url).pathname });
    return respond(normalized);
  };

  ({ OpenArtifact } = await vite.ssrLoadModule('/src/lib/stores/artifact.svelte.ts'));
});

after(async () => {
  await vite?.close();
  if (originalRequest) globalThis.Request = originalRequest;
  if (originalFetch) globalThis.fetch = originalFetch;
});

class MemoryDrafts {
  records = new Map();
  failPuts = 0;

  async get(key) {
    return this.records.get(key) ?? null;
  }

  async list(prefix) {
    return [...this.records.values()].filter((draft) => draft.key.startsWith(prefix));
  }

  async put(draft) {
    if (this.failPuts > 0) {
      this.failPuts -= 1;
      throw new Error('simulated local persistence failure');
    }
    this.records.set(draft.key, structuredClone(draft));
  }

  async delete(key, revision, writerId) {
    const saved = this.records.get(key);
    if (saved && (revision === undefined || (saved.revision === revision && (writerId === undefined || saved.writerId === writerId)))) {
      this.records.delete(key);
    }
  }

  async deleteArtifact(courseId, artifactId) {
    for (const [key, draft] of this.records) {
      if (draft.courseId === courseId && draft.artifactId === artifactId) this.records.delete(key);
    }
  }
}

function artifactView(version = 1, content = { markdown: 'server content' }) {
  return {
    artifact_id: 'artifact-1',
    kind: 'doc',
    title: 'Notes',
    version,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    origin: { message: { nested: ['source', { id: 4 }] } },
    content,
    sources: ['source-1']
  };
}

function jsonResponse(data, status = 200) {
  if (status === 204) return new Response(null, { status });
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json' }
  });
}

function artifactPath(request) {
  return new URL(request.url).pathname.endsWith('/courses/course-1/artifacts/artifact-1');
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

test('a failed save persists proxy-backed metadata and reloads the visible draft', async () => {
  const storage = new MemoryDrafts();
  respond = async (request) => {
    if (request.method === 'GET' && artifactPath(request)) return jsonResponse(artifactView());
    if (request.method === 'GET' && new URL(request.url).pathname.endsWith('/citations')) return jsonResponse([]);
    if (request.method === 'PUT') return jsonResponse({ detail: 'temporarily unavailable' }, 503);
    return jsonResponse({ detail: 'unexpected request' }, 404);
  };

  const open = new OpenArtifact('course-1', 'artifact-1', storage);
  await open.load();
  // Vite's SSR loader deliberately leaves $state values plain. Re-wrap the
  // live store values with the same client runtime proxy used by compiled
  // $state so this regression test exercises the browser serialization edge.
  open.artifact = proxy(open.artifact);
  open.content = proxy(open.content);
  open.pendingSave = proxy({ author: 'model', note: 'Keep source metadata', sources: ['model-source'] });
  assert.throws(() => structuredClone(open.artifact), { name: 'DataCloneError' });
  open.content.markdown = 'unsaved local edit';
  storage.failPuts = 1;
  open.touch();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.match(open.recoveryError.message, /local persistence failure/);
  await open.persistDraft();

  assert.equal(open.recoveryError, null);
  assert.equal(storage.records.size, 1);
  const saved = [...storage.records.values()][0];
  assert.deepEqual(saved.origin, artifactView().origin);
  assert.deepEqual(saved.sources, ['source-1']);
  assert.deepEqual(saved.pendingSave, {
    author: 'model',
    note: 'Keep source metadata',
    sources: ['model-source']
  });
  assert.equal(await open.flush(), false);
  assert.match(open.saveError.message, /temporarily unavailable/);

  const reopened = new OpenArtifact('course-1', 'artifact-1', storage);
  await reopened.load();

  assert.equal(reopened.recovered, true);
  assert.equal(reopened.dirty, true);
  assert.equal(reopened.content.markdown, 'unsaved local edit');
  assert.deepEqual(reopened.pendingSave, {
    author: 'model',
    note: 'Keep source metadata',
    sources: ['model-source']
  });
  open.dispose();
  reopened.dispose();
});

test('removal waits for an active save and blocks late edits from sending another save', async () => {
  const storage = new MemoryDrafts();
  const putStarted = deferred();
  const finishPut = deferred();
  let putCount = 0;
  respond = async (request) => {
    const path = new URL(request.url).pathname;
    if (request.method === 'GET' && artifactPath(request)) return jsonResponse(artifactView());
    if (request.method === 'GET' && path.endsWith('/citations')) return jsonResponse([]);
    if (request.method === 'PUT') {
      putCount += 1;
      putStarted.resolve();
      await finishPut.promise;
      return jsonResponse(artifactView(2, { markdown: 'first edit' }));
    }
    if (request.method === 'DELETE' && artifactPath(request)) return jsonResponse(null, 204);
    return jsonResponse({ detail: 'unexpected request' }, 404);
  };

  const open = new OpenArtifact('course-1', 'artifact-1', storage);
  await open.load();
  open.content.markdown = 'first edit';
  open.touch();
  const save = open.save();
  await putStarted.promise;
  const remove = open.remove();
  open.content.markdown = 'late edit during deletion';
  open.touch();
  finishPut.resolve();

  await save;
  await remove;
  await new Promise((resolve) => setTimeout(resolve, 20));

  assert.equal(putCount, 1);
  assert.equal(open.dirty, false);
  assert.equal(storage.records.size, 0);
  assert.equal(fetchCalls.filter((call) => call.method === 'DELETE').length, 1);
  open.dispose();
});
