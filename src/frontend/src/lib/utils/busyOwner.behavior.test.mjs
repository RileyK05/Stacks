import { createStoreRuntime } from '../../../tests/helpers/storeRuntime.mjs';
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

let vite;
let createBusyOwner;

before(async () => {
  vite = await createStoreRuntime(['src/lib/utils/busyOwner.ts']);
  ({ createBusyOwner } = await vite.ssrLoadModule('/src/lib/utils/busyOwner.ts'));
});

after(async () => vite?.close());

test('a stale operation releases only its own busy state after a scope switch', () => {
  let busy = false;
  const owner = createBusyOwner((value) => { busy = value; });
  const oldOperation = owner.claim();

  owner.reset();
  assert.equal(busy, false);
  const newOperation = owner.claim();
  owner.release(oldOperation);
  assert.equal(busy, true);
  owner.release(newOperation);
  assert.equal(busy, false);

  const nextOperation = owner.claim();
  owner.release(nextOperation);
  assert.equal(busy, false);
});
