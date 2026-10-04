import { createStoreRuntime, installApiMock, jsonResponse } from '../../../tests/helpers/storeRuntime.mjs';
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

let vite;
let QuizSession;
let QuizSessionScope;
let restoreApi;
let response;

before(async () => {
  vite = await createStoreRuntime(['src/lib/stores/workspace.svelte.ts', 'src/lib/stores/quizSessionScope.ts']);
  restoreApi = installApiMock((request) => response(request));
  ({ QuizSession } = await vite.ssrLoadModule('/src/lib/stores/workspace.svelte.ts'));
  ({ QuizSessionScope } = await vite.ssrLoadModule('/src/lib/stores/quizSessionScope.ts'));
});

after(async () => {
  try { await vite?.close(); } finally { restoreApi?.(); }
});

test('editor toggles reuse one practice suite while saved question versions get a new suite', async () => {
  const requests = [];
  response = async (request) => {
    if (request.method === 'POST') {
      const body = await request.json();
      requests.push(body);
      const question = body.artifact_version === 1
        ? { prompt: 'Old question', options: ['A', 'B'], answer: 0, sources: [1] }
        : { prompt: 'Changed question', options: ['A', 'B'], answer: 1, sources: [1] };
      return jsonResponse({ suite: { suite_id: `suite-${requests.length}`, questions: [question], evidence: [] }, latest_run: null, feedback: [] });
    }
    return jsonResponse({ detail: 'Unexpected request' }, 404);
  };

  const questionsV1 = [{ prompt: 'Old question', options: ['A', 'B'], answer: 0, sources: [1] }];
  const originV1 = { artifact_id: 'quiz-1', artifact_version: 1, item_index: 0 };
  const identityV1 = JSON.stringify(['quiz-1', 1, questionsV1]);
  const createV1 = () => new QuizSession({ type: 'quiz', title: 'Practice test', questions: questionsV1 }, originV1);
  const scope = new QuizSessionScope(identityV1, createV1);
  const first = scope.forMode('take', identityV1, createV1);
  await first.connect('course-1');
  first.choose(0, 1);

  const inEditor = scope.forMode('edit', identityV1, createV1);
  const afterToggle = scope.forMode('take', identityV1, createV1);
  await afterToggle.connect('course-1');
  assert.equal(inEditor, first);
  assert.equal(afterToggle, first);
  assert.equal(requests.length, 1);

  const questionsV2 = [{ prompt: 'Changed question', options: ['A', 'B'], answer: 1, sources: [1] }];
  const originV2 = { artifact_id: 'quiz-1', artifact_version: 2, item_index: 0 };
  const identityV2 = JSON.stringify(['quiz-1', 2, questionsV2]);
  const createV2 = () => new QuizSession({ type: 'quiz', title: 'Practice test', questions: questionsV2 }, originV2);
  assert.equal(scope.forMode('edit', identityV2, createV2), first);
  const second = scope.forMode('take', identityV2, createV2);
  await second.connect('course-1');

  assert.notEqual(second, first);
  assert.deepEqual(second.responses, [null]);
  assert.equal(second.questions[0].prompt, 'Changed question');
  assert.equal(requests.length, 2);
  assert.equal(requests[0].artifact_version, 1);
  assert.equal(requests[1].artifact_version, 2);
});
