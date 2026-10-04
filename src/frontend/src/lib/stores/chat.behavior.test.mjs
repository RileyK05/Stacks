import { createStoreRuntime, installApiMock, jsonResponse } from '../../../tests/helpers/storeRuntime.mjs';
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { proxy } from 'svelte/internal/client';

let vite;
let CourseChats;
let materialSources;
let restoreApi;
let response;
let state;
let assignedRaw;
let hydratedTurn;

before(async () => {
  vite = await createStoreRuntime(['src/lib/stores/chat.svelte.ts']);
  restoreApi = installApiMock((request) => response(request));
  ({ CourseChats, materialSources } = await vite.ssrLoadModule('/src/lib/stores/chat.svelte.ts'));
});

after(async () => {
  try { await vite?.close(); } finally { restoreApi?.(); }
});

test('saved conversation citations hydrate the assigned reactive turn proxy', async () => {
  const citation = { chunk_id: 'chunk-1', source_id: 'source-1', filename: 'Lecture', label: 'page 2', text: 'Evidence' };
  response = async (request) => {
    if (new URL(request.url).pathname.endsWith('/citations')) return jsonResponse([citation]);
    return jsonResponse({ messages: [
      { role: 'user', text: 'Explain this.' },
      { role: 'assistant', message_id: 'message-1', text: 'Answer [1]', answer: {
        text: 'Answer [1]', chunk_ids: ['chunk-1'], material_chunk_ids: ['chunk-1'], trace_id: 'trace-1'
      } }
    ] });
  };
  const chats = new CourseChats('course-1');
  Object.defineProperty(chats, 'turns', {
    configurable: true,
    get: () => state,
    set: (turns) => {
      assignedRaw = turns;
      state = proxy(turns);
    }
  });
  const loadCitations = chats.loadCitations.bind(chats);
  chats.loadCitations = (turn) => {
    hydratedTurn = turn;
    return loadCitations(turn);
  };

  await chats.open('conversation-1');
  for (let tries = 0; tries < 30 && !state[0]?.citationsLoaded; tries++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }

  assert.ok(hydratedTurn);
  assert.notEqual(hydratedTurn, assignedRaw[0]);
  assert.equal(state[0].citationsLoaded, true);
  assert.deepEqual(state[0].citations, [citation]);
});

test('workspace sources resolve by material order, not prose-marker order', async () => {
  // The prose cites [2] before [1], so citations arrive in marker order
  // [m2, m1]; a workspace item citing [1] must still name material 1.
  const m1 = { chunk_id: 'chunk-1', source_id: 's1', filename: 'First', label: 'p1', text: 'a' };
  const m2 = { chunk_id: 'chunk-2', source_id: 's2', filename: 'Second', label: 'p2', text: 'b' };
  const turn = {
    materialChunkIds: ['chunk-1', 'chunk-2'],
    citations: [m2, m1],
    citationsLoaded: true
  };
  const resolved = materialSources(turn);
  assert.equal(resolved[0].filename, 'First');
  assert.equal(resolved[1].filename, 'Second');
  assert.deepEqual(materialSources(undefined), []);
});
