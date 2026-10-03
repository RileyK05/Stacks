import { MemoryDrafts } from '../../../tests/helpers/memoryDrafts.mjs';
import { createStoreRuntime } from '../../../tests/helpers/storeRuntime.mjs';
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

let vite;
let WorkspaceDraftRecovery;
let DocumentSession;

before(async () => {
  vite = await createStoreRuntime(['src/lib/stores/workspaceRecovery.svelte.ts']);
  ({ WorkspaceDraftRecovery } = await vite.ssrLoadModule('/src/lib/stores/workspaceRecovery.svelte.ts'));
  ({ DocumentSession } = await vite.ssrLoadModule('/src/lib/stores/workspace.svelte.ts'));
});

after(async () => {
  await vite?.close();
});


function documentSession(text = 'original') {
  return new DocumentSession({ content: text });
}

function savedDraft(key, draft, writerId = 'previous-window') {
  return {
    key,
    courseId: 'course-1',
    artifactId: 'workspace:message-1:0',
    messageId: 'message-1',
    itemIndex: 0,
    title: 'Saved work',
    content: { draft },
    baseVersion: 1,
    kind: 'document',
    origin: {},
    sources: [],
    revision: 1,
    writerId,
    updatedAt: Date.now()
  };
}

test('restores an edited document after reload before the first Save action', async () => {
  const storage = new MemoryDrafts();
  const key = 'course-1:workspace:message-1:0:previous-window';
  storage.records.set(key, savedDraft(key, 'local draft'));
  const session = documentSession();
  const recovery = new WorkspaceDraftRecovery('course-1', 'message-1', 0, session, storage);

  await recovery.ready;

  assert.equal(session.draft, 'local draft');
  assert.equal(recovery.recovered, true);
});

test('a delayed recovery read cannot replace a newer user edit', async () => {
  const storage = new MemoryDrafts();
  let releaseRead;
  storage.readGate = new Promise((resolve) => { releaseRead = resolve; });
  const key = 'course-1:workspace:message-1:0:previous-window';
  storage.records.set(key, savedDraft(key, 'older recovered text'));
  const session = documentSession();
  const recovery = new WorkspaceDraftRecovery('course-1', 'message-1', 0, session, storage);
  session.draft = 'newer user edit';
  releaseRead();

  await recovery.ready;

  assert.equal(session.draft, 'newer user edit');
  assert.equal(recovery.recovered, false);
});

test('a failed queued persistence write is retried by flush', async () => {
  const storage = new MemoryDrafts();
  storage.failPuts = 1;
  const session = documentSession();
  const recovery = new WorkspaceDraftRecovery('course-1', 'message-1', 0, session, storage);
  await recovery.ready;
  session.draft = 'edited text';
  recovery.observe(session.draft);

  assert.equal(await recovery.flush(), false);
  assert.match(recovery.error.message, /simulated local persistence failure/);
  assert.equal(await recovery.flush(), true);
  assert.equal(storage.puts, 2);
  assert.equal(recovery.error, null);
  assert.equal([...storage.records.values()][0]?.content.draft, 'edited text');
});

test('two writers retain independent drafts for the same workspace item', async () => {
  const storage = new MemoryDrafts();
  const left = documentSession();
  const right = documentSession();
  const leftRecovery = new WorkspaceDraftRecovery('course-1', 'message-1', 0, left, storage);
  const rightRecovery = new WorkspaceDraftRecovery('course-1', 'message-1', 0, right, storage);
  await Promise.all([leftRecovery.ready, rightRecovery.ready]);
  left.draft = 'left window';
  right.draft = 'right window';
  leftRecovery.observe(left.draft);
  rightRecovery.observe(right.draft);

  assert.equal(await leftRecovery.flush(), true);
  assert.equal(await rightRecovery.flush(), true);
  assert.deepEqual(
    new Set([...storage.records.values()].map((record) => record.content.draft)),
    new Set(['left window', 'right window'])
  );
});
