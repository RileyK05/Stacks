import assert from 'node:assert/strict';
import test from 'node:test';
import {
  coalesceSave,
  flushDirtyEdits,
  matchesDraftRevision,
  saveIntentAfterSuccessfulSave,
  saveIntentForRetry
} from './artifactDrafts';

test('flush waits for an active save and sends edits made while it was pending', async () => {
  let editedRevision = 1;
  let savedRevision = 0;
  let saves = 0;
  const flushed = flushDirtyEdits(
    () => savedRevision !== editedRevision,
    () => false,
    async () => {
      const sentRevision = editedRevision;
      saves += 1;
      await Promise.resolve();
      if (saves === 1) editedRevision = 2;
      savedRevision = sentRevision;
      return true;
    }
  );

  assert.equal(await flushed, true);
  assert.equal(saves, 2);
  assert.equal(savedRevision, 2);
});

test('flush stops after a failed save and leaves the draft dirty', async () => {
  let dirty = true;
  let saves = 0;
  const flushed = await flushDirtyEdits(
    () => dirty,
    () => false,
    async () => {
      saves += 1;
      return false;
    }
  );

  assert.equal(flushed, false);
  assert.equal(dirty, true);
  assert.equal(saves, 1);
});

test('flush refuses a conflicted draft without retrying the save', async () => {
  let saves = 0;
  const flushed = await flushDirtyEdits(
    () => true,
    () => true,
    async () => {
      saves += 1;
      return true;
    }
  );

  assert.equal(flushed, false);
  assert.equal(saves, 0);
});

test('draft cleanup matches both the revision and the writer', () => {
  const draft = { revision: 4, writerId: 'window-a' };
  assert.equal(matchesDraftRevision(draft, 4, 'window-a'), true);
  assert.equal(matchesDraftRevision(draft, 4, 'window-b'), false);
  assert.equal(matchesDraftRevision(draft, 3, 'window-a'), false);
});

test('a no-op save clears its in-flight slot so later edits can save', async () => {
  let inFlight: Promise<boolean> | null = null;
  let dirty = true;
  let saves = 0;
  const save = () => coalesceSave(
    () => inFlight,
    (operation) => { inFlight = operation; },
    async () => {
      saves += 1;
      dirty = false;
      return true;
    }
  );

  assert.equal(await save(), true);
  assert.equal(inFlight, null);
  dirty = true;
  assert.equal(await flushDirtyEdits(() => dirty, () => false, save), true);
  assert.equal(saves, 2);
});

test('a failed model acceptance retry keeps its source links and model authorship', () => {
  const acceptance = { author: 'model' as const, note: 'Add citations', sources: ['source-7', 'source-9'] };
  const pending = saveIntentForRetry(null, acceptance);
  const retry = saveIntentForRetry(pending);

  assert.deepEqual(retry, acceptance);
  assert.deepEqual(saveIntentAfterSuccessfulSave(retry, false), null);
  assert.deepEqual(saveIntentAfterSuccessfulSave(retry, true), {
    author: 'you', note: '', sources: ['source-7', 'source-9']
  });
});
