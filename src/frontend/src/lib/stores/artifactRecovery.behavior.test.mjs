import { MemoryDrafts } from '../../../tests/helpers/memoryDrafts.mjs';
import { createStoreRuntime, installApiMock, jsonResponse } from '../../../tests/helpers/storeRuntime.mjs';
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { proxy } from 'svelte/internal/client';

let vite;
let OpenArtifact;
let restoreApi;
let respond;
let fetchCalls;

before(async () => {
  vite = await createStoreRuntime(['src/lib/stores/artifact.svelte.ts']);
  fetchCalls = [];
  restoreApi = installApiMock((request) => {
    fetchCalls.push({ method: request.method, path: new URL(request.url).pathname });
    return respond(request);
  });
  ({ OpenArtifact } = await vite.ssrLoadModule('/src/lib/stores/artifact.svelte.ts'));
});

after(async () => {
  try {
    await vite?.close();
  } finally {
    restoreApi?.();
  }
});


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

test('route close flushes dirty edits once before disposing the store', async () => {
  const storage = new MemoryDrafts();
  let putCount = 0;
  respond = async (request) => {
    const path = new URL(request.url).pathname;
    if (request.method === 'GET' && artifactPath(request)) return jsonResponse(artifactView());
    if (request.method === 'GET' && path.endsWith('/citations')) return jsonResponse([]);
    if (request.method === 'PUT') {
      putCount += 1;
      const body = await request.json();
      return jsonResponse(artifactView(2, body.content));
    }
    return jsonResponse({ detail: 'unexpected request' }, 404);
  };

  const open = new OpenArtifact('course-1', 'artifact-1', storage);
  await open.load();
  open.content.markdown = 'saved as the route closes';
  open.touch();
  const closing = open.flushAndDispose();
  assert.equal(open.flushAndDispose(), closing);
  assert.equal(await closing, true);
  assert.equal(putCount, 1);
  assert.equal(open.dirty, false);
  assert.equal(await open.save(), false);
});
