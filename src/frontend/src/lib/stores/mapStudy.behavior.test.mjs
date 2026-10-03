import { createStoreRuntime, installApiMock, jsonResponse as json } from '../../../tests/helpers/storeRuntime.mjs';
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

let vite, MapStudy, restoreApi, respond;
const context = { courseId: 'course', origin: { message_id: 'message', item_index: 0 }, ready: true };
before(async () => {
  vite = await createStoreRuntime(['src/lib/stores/mapStudy.svelte.ts']);
  restoreApi = installApiMock((request) => respond(request));
  ({ MapStudy } = await vite.ssrLoadModule('/src/lib/stores/mapStudy.svelte.ts'));
});
after(async () => {
  try {
    await vite?.close();
  } finally {
    restoreApi?.();
  }
});

test('a lost quiz response retries the same request; pending and unsaved maps cannot send duplicates', async () => {
  const bodies = []; let release;
  respond = async request => {
    bodies.push(await request.json());
    if (bodies.length === 1) return new Promise(resolve => { release = () => resolve(json({ detail: 'Offline' }, 503)); });
    return json({ text: 'Saved', citations: [], model: 'fixture', quiz_id: 'quiz' });
  };
  const study = new MapStudy();
  const first = study.request(context, 'topic', 'quiz');
  await new Promise(resolve => setTimeout(resolve, 0));
  await study.request(context, 'topic', 'quiz');
  assert.equal(bodies.length, 1);
  release(); await first;
  assert.equal(study.error, 'Offline');
  await study.request(context, 'topic', 'quiz');
  assert.deepEqual(bodies[0], bodies[1]);
  assert.equal(study.result.quiz_id, 'quiz');
  await study.request({ ...context, ready: false }, 'topic', 'explain');
  assert.equal(bodies.length, 2);
});

test('a late reply cannot replace help after the visible map or topic changes', async () => {
  let release;
  respond = async () => new Promise(resolve => { release = () => resolve(json({ text: 'Old topic', citations: [], model: 'fixture' })); });
  const study = new MapStudy();
  const pending = study.request(context, 'topic', 'explain');
  await new Promise(resolve => setTimeout(resolve, 0));
  study.clear(); release(); await pending;
  assert.equal(study.result, null); assert.equal(study.error, ''); assert.equal(study.busy, false);
});
