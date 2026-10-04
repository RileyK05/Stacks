import assert from "node:assert/strict";
import test from "node:test";
import { LivePane } from "./public/live-pane.js";

const bindingA = { connection_id: "connection-a", external_id: "document-a", course_id: "course-a" };
const bindingB = { connection_id: "connection-b", external_id: "document-b", course_id: "course-b" };

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function harness(overrides = {}) {
  let externalId = bindingA.external_id;
  const calls = { read: [], poll: [], complete: [], disconnect: [], snapshots: [], lost: [] };
  const read = overrides.read ?? (async () => ({ text: "current document", coverage: "document", warnings: [] }));
  const poll = overrides.poll ?? (async () => ({ command: null }));
  const complete = overrides.complete ?? (async () => ({ status: "complete", revision: 3 }));
  const disconnect = overrides.disconnect ?? (async () => {});
  const pane = new LivePane({
    identity: () => externalId,
    read: async (policy) => {
      calls.read.push(policy);
      return read(policy);
    },
    poll: async (...args) => {
      calls.poll.push(args);
      return poll(...args);
    },
    complete: async (...args) => {
      calls.complete.push(args);
      return complete(...args);
    },
    disconnect: async (...args) => {
      calls.disconnect.push(args);
      return disconnect(...args);
    },
    onSnapshot: (...args) => calls.snapshots.push(args),
    onLost: (...args) => calls.lost.push(args),
  });
  pane.bind(bindingA);
  return {
    pane,
    calls,
    setExternalId(value) { externalId = value; },
  };
}

function commandResponse(requestId = "request-1", policy = { maxChars: 500, maxSlides: 4, maxShapes: 30 }) {
  return { command: { request_id: requestId }, policy: { reader: policy } };
}

test("polls without reading when there is no command", async () => {
  const { pane, calls } = harness();
  await pane.tick();
  assert.deepEqual(calls.poll, [[bindingA.connection_id, bindingA.external_id]]);
  assert.deepEqual(calls.read, []);
  assert.deepEqual(calls.complete, []);
});

test("reads with the command policy and completes using the exact connection and request IDs", async () => {
  const policy = { maxChars: 1200, maxSlides: 6, maxShapes: 80 };
  const { pane, calls } = harness({
    poll: async () => commandResponse("request-exact", policy),
  });
  await pane.tick();
  assert.deepEqual(calls.poll, [[bindingA.connection_id, bindingA.external_id]]);
  assert.deepEqual(calls.read, [policy]);
  assert.equal(calls.complete.length, 1);
  assert.deepEqual(calls.complete[0], [bindingA.connection_id, {
    request_id: "request-exact",
    external_id: bindingA.external_id,
    document: { text: "current document", coverage: "document", warnings: [] },
    error: "",
  }]);
  assert.deepEqual(calls.snapshots, [[{ status: "complete", revision: 3 }, bindingA]]);
});

test("sends a scoped error completion when reading fails and preserves the binding", async () => {
  const { pane, calls } = harness({
    poll: async () => commandResponse("request-read-error"),
    read: async () => { throw new Error("Host read failed"); },
  });
  await pane.tick();
  assert.deepEqual(calls.complete, [[bindingA.connection_id, {
    request_id: "request-read-error",
    external_id: bindingA.external_id,
    document: null,
    error: "Host read failed",
  }]]);
  assert.equal(pane.binding, bindingA);
  assert.deepEqual(calls.lost, []);
});

test("coalesces overlapping ticks while a poll is unresolved", async () => {
  const pollGate = deferred();
  const pollStarted = deferred();
  const { pane, calls } = harness({
    poll: async (...args) => {
      pollStarted.resolve();
      return pollGate.promise;
    },
  });
  const first = pane.tick();
  await pollStarted.promise;
  const overlapping = pane.tick();
  assert.equal(calls.poll.length, 1);
  pollGate.resolve({ command: null });
  await Promise.all([first, overlapping]);
  assert.equal(calls.poll.length, 1);
});

for (const change of ["stop", "rebind"]) {
  test(`${change} during an unresolved read prevents completion for the old binding`, async () => {
    const readGate = deferred();
    const readStarted = deferred();
    const { pane, calls } = harness({
      poll: async () => commandResponse("old-request"),
      read: async () => { readStarted.resolve(); return readGate.promise; },
    });
    const ticking = pane.tick();
    await readStarted.promise;
    if (change === "stop") pane.stop();
    else pane.bind(bindingB);
    readGate.resolve({ text: "late old text", coverage: "document", warnings: [] });
    await ticking;
    assert.deepEqual(calls.complete, []);
    assert.deepEqual(calls.snapshots, []);
    assert.equal(pane.binding, change === "stop" ? null : bindingB);
  });
}

test("an external identity change before polling loses the binding without reading", async () => {
  const { pane, calls, setExternalId } = harness();
  setExternalId("another-document");
  await pane.tick();
  assert.deepEqual(calls.poll, []);
  assert.deepEqual(calls.read, []);
  assert.deepEqual(calls.complete, []);
  assert.equal(pane.binding, null);
  assert.equal(calls.lost.length, 1);
  assert.equal(calls.lost[0][1], true);
});

test("an external identity change during reading prevents completion and loses the binding", async () => {
  const readGate = deferred();
  const readStarted = deferred();
  const { pane, calls, setExternalId } = harness({
    poll: async () => commandResponse("identity-changed"),
    read: async () => { readStarted.resolve(); return readGate.promise; },
  });
  const ticking = pane.tick();
  await readStarted.promise;
  setExternalId("another-document");
  readGate.resolve({ text: "wrong file", coverage: "document", warnings: [] });
  await ticking;
  assert.deepEqual(calls.complete, []);
  assert.equal(pane.binding, null);
  assert.equal(calls.lost.length, 1);
  assert.match(calls.lost[0][0].message, /changed while reading/);
  assert.equal(calls.lost[0][1], true);
});

test("a poll started before a rebind cannot read or complete its old command", async () => {
  const pollGate = deferred();
  const pollStarted = deferred();
  const { pane, calls } = harness({
    poll: async (...args) => {
      pollStarted.resolve();
      return pollGate.promise;
    },
  });
  const oldTick = pane.tick();
  await pollStarted.promise;
  pane.bind(bindingB);
  pollGate.resolve(commandResponse("stale-command"));
  await oldTick;
  assert.deepEqual(calls.read, []);
  assert.deepEqual(calls.complete, []);
  assert.equal(pane.binding, bindingB);
});

test("a failed server result is surfaced while keeping the current binding", async () => {
  const { pane, calls } = harness({
    poll: async () => commandResponse("server-failed"),
    complete: async () => ({ status: "failed", error: "Revision conflict" }),
  });
  await pane.tick();
  assert.equal(pane.binding, bindingA);
  assert.equal(calls.lost.length, 1);
  assert.equal(calls.lost[0][0].message, "Revision conflict");
  assert.equal(calls.lost[0][1], false);
  assert.deepEqual(calls.snapshots, []);
});

test("a poll network failure loses the binding", async () => {
  const { pane, calls } = harness({
    poll: async () => { throw new Error("Bridge offline"); },
  });
  await pane.tick();
  assert.equal(pane.binding, null);
  assert.equal(calls.lost.length, 1);
  assert.equal(calls.lost[0][0].message, "Bridge offline");
  assert.equal(calls.lost[0][1], true);
  assert.deepEqual(calls.read, []);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(calls.disconnect, [[bindingA.connection_id]]);
});

test("manual stop and a late poll failure disconnect the old binding only once", async () => {
  const pollGate = deferred();
  const pollStarted = deferred();
  const { pane, calls } = harness({
    poll: async () => { pollStarted.resolve(); return pollGate.promise; },
    disconnect: async () => { throw new Error("Bridge disconnected during cleanup"); },
  });
  const ticking = pane.tick();
  await pollStarted.promise;
  pane.stop();
  pane.bind(bindingB);
  await new Promise((resolve) => setImmediate(resolve));
  pollGate.reject(new Error("Poll failed after stop"));
  await ticking;
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(calls.disconnect, [[bindingA.connection_id]]);
  assert.equal(pane.binding, bindingB);
  assert.deepEqual(calls.lost, []);
});

test("a same-connection rebind cancels pending cleanup instead of deleting its fresh owner", async () => {
  const freshBinding = { ...bindingA, external_id: "document-b" };
  const { pane, calls } = harness();
  pane.stop();
  pane.bind(freshBinding);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(calls.disconnect, []);
  assert.equal(pane.binding, freshBinding);
});

test("onSnapshot only receives successful completion for the current binding", async () => {
  const completeGate = deferred();
  const completeStarted = deferred();
  const { pane, calls } = harness({
    poll: async () => commandResponse("snapshot-race"),
    complete: async (...args) => {
      calls.complete.push(args);
      completeStarted.resolve();
      return completeGate.promise;
    },
  });
  const ticking = pane.tick();
  await completeStarted.promise;
  pane.bind(bindingB);
  completeGate.resolve({ status: "complete", revision: 4 });
  await ticking;
  assert.deepEqual(calls.snapshots, []);
  assert.equal(pane.binding, bindingB);
});
