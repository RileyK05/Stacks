import { createStoreRuntime, installApiMock, jsonResponse as json } from '../../../tests/helpers/storeRuntime.mjs';
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

let vite, PracticeSession, restoreApi, respond;
const questions = [{ prompt: 'Which operation?', options: ['A', 'B'], answer: 0, sources: [1], explanation: '', topic: 'Operations', capability: 'recognition' }];
const suite = { suite_id: 'suite', questions, evidence: [{ filename: 'Lecture', label: 'page 2', text: 'Source passage' }] };
const hint = { help_id: 'hint-1', question_index: 0, kind: 'hint', content: { text: 'Consider the operation [1].', sources: [1] } };
const run = { run_id: 'submitted-run', answers: [0], helped: [true], results: [true], correct_answers: [0] };

before(async () => {
  vite = await createStoreRuntime(['src/lib/stores/practice.svelte.ts']);
  restoreApi = installApiMock((request) => respond(request));
  ({ PracticeSession } = await vite.ssrLoadModule('/src/lib/stores/practice.svelte.ts'));
});
after(async () => {
  try {
    await vite?.close();
  } finally {
    restoreApi?.();
  }
});

test('hint blocks submission and reset while pending, then records assistance', async () => {
  let release, submitted = 0;
  respond = async (request) => {
    if (request.method === 'GET') return json({ suite, latest_run: null, feedback: [] });
    if (request.url.endsWith('/help')) return new Promise((resolve) => { release = () => resolve(json(hint)); });
    submitted++;
    const body = await request.json();
    assert.deepEqual(body.helped, [true]);
    return json({ ...run, run_id: body.run_id });
  };
  const session = new PracticeSession(questions, 'suite');
  await session.connect('course');
  session.choose(0, 0);
  const pending = session.requestHelp(0);
  await new Promise((resolve) => setTimeout(resolve, 0));
  session.reset();
  await session.submit();
  assert.equal(submitted, 0);
  assert.deepEqual(session.responses, [0]);
  release(); await pending;
  assert.deepEqual(session.helped, [true]);
  assert.equal(session.assistance[0].help_id, 'hint-1');
  await session.submit();
  assert.equal(submitted, 1);
});

test('Explain uses restored session identity; failed help retries and feedback keeps exact target', async () => {
  let failed = true, count = 0;
  respond = async (request) => {
    if (request.method === 'GET') return json({ suite, latest_run: run, feedback: [] });
    const body = await request.json();
    if (request.url.endsWith('/help')) {
      assert.equal(body.kind, 'explain'); assert.equal(body.run_id, run.run_id);
      if (failed) { failed = false; return json({ detail: 'Model offline' }, 503); }
      return json({ ...hint, help_id: 'explain-1', kind: 'explain' });
    }
    count++; assert.equal(body.help_id, 'explain-1'); assert.equal(body.target, 'explain');
    return json([{ ...body, suite_id: 'suite', question_index: 0, updated_at: '2026-09-30' }]);
  };
  const session = new PracticeSession(questions, 'suite'); await session.connect('course');
  await session.requestHelp(0); assert.equal(session.supportErrors[0], 'Model offline');
  await session.requestHelp(0); assert.equal(session.supportErrors[0], '');
  await session.rate(0, 'explain', 'bad', 'Too long');
  assert.equal(session.rating(0, 'explain').reason, 'Too long');
  await session.rate(0, 'explain', 'good'); assert.equal(count, 2);
  assert.equal(session.rating(0, 'explain').rating, 'good');
  assert.deepEqual(session.run, run);
});
