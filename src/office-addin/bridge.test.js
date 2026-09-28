/**
 * Tests for the Office add-in's pure logic (bridge.js).
 * No Office.js, no DOM: run with `npm test` in src/office-addin.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  ACTIONS,
  HOSTS,
  assistError,
  assistRequest,
  bridgeHealth,
  chooseCourse,
  citationLines,
  columnName,
  describeRange,
  documentText,
  hostKey,
  listCourses,
  plainText,
  resolveBridgeBase,
  sendAssist
} from './public/bridge.js';

const ORIGIN = 'https://localhost:47831';

function fakeFetch(response) {
  const calls = [];
  const impl = async (url, init) => {
    calls.push({ url, init });
    return response;
  };
  return { impl, calls };
}

function jsonResponse(body, ok = true, status = 200) {
  return { ok, status, json: async () => body };
}

test('the bridge is the pane’s own origin unless ?bridge= overrides it', () => {
  assert.equal(resolveBridgeBase('', ORIGIN), ORIGIN);
  assert.equal(resolveBridgeBase('?bridge=https://box.local:9000/', ORIGIN), 'https://box.local:9000');
});

test('Office host names map to the three supported apps', () => {
  assert.equal(hostKey('PowerPoint'), 'powerpoint');
  assert.equal(hostKey('Word'), 'word');
  assert.equal(hostKey('Excel'), 'excel');
  assert.equal(hostKey('Outlook'), null);
  assert.equal(hostKey(undefined), null);
  for (const key of ['word', 'excel', 'powerpoint']) {
    assert.ok(HOSTS[key].insert && HOSTS[key].replace && HOSTS[key].placeholder);
  }
});

test('health and courses are GETs on the bridge, with the token when set', async () => {
  const { impl, calls } = fakeFetch(jsonResponse({ app: 'Stacks', version: '0.2.0' }));
  const health = await bridgeHealth(impl, ORIGIN, 'secret');
  assert.equal(health.app, 'Stacks');
  assert.equal(calls[0].url, `${ORIGIN}/office/health`);
  assert.equal(calls[0].init.headers['X-Office-Token'], 'secret');

  const courses = fakeFetch(jsonResponse([{ course_id: 'c1', name: 'Econ', source_count: 2 }]));
  assert.equal((await listCourses(courses.impl, ORIGIN, '')).length, 1);
  assert.equal(courses.calls[0].url, `${ORIGIN}/office/courses`);
  assert.deepEqual(courses.calls[0].init.headers, {});
});

test('assist posts the action and surfaces the bridge reason on failure', async () => {
  const request = assistRequest('c1', 'explain', 'word', 'supply curves', '');
  assert.deepEqual(request, {
    course_id: 'c1',
    action: 'explain',
    host: 'word',
    context: 'supply curves',
    instruction: ''
  });
  const ok = fakeFetch(jsonResponse({ text: 'Answer [1]', citations: [] }));
  const result = await sendAssist(ok.impl, ORIGIN, request, '');
  assert.equal(result.text, 'Answer [1]');
  assert.equal(ok.calls[0].url, `${ORIGIN}/office/assist`);
  assert.equal(ok.calls[0].init.method, 'POST');
  assert.equal(JSON.parse(ok.calls[0].init.body).action, 'explain');

  const missing = fakeFetch(jsonResponse({ detail: 'nothing matches' }, false, 404));
  await assert.rejects(sendAssist(missing.impl, ORIGIN, request, ''), (error) => {
    assert.equal(error.status, 404);
    assert.equal(error.detail, 'nothing matches');
    return true;
  });
});

test('assistError explains each refusal in plain words', () => {
  assert.match(assistError(422), /graded work/);
  assert.equal(assistError(404, 'nothing here'), 'nothing here');
  assert.match(assistError(404), /Nothing in this course/);
  assert.match(assistError(503), /model/);
  assert.match(assistError(402), /budget/);
  assert.match(assistError(500), /500/);
});

test('ACTIONS are the four the bridge accepts', () => {
  assert.deepEqual(
    ACTIONS.map((action) => action.id),
    ['explain', 'find', 'quiz', 'summarize']
  );
});

test('chooseCourse prefers this document’s course, then Stacks’ suggestion, then the first', () => {
  const courses = [
    { course_id: 'a' },
    { course_id: 'b', suggested: true },
    { course_id: 'c' }
  ];
  assert.equal(chooseCourse(courses, 'c'), 'c');
  assert.equal(chooseCourse(courses, 'gone'), 'b');
  assert.equal(chooseCourse([{ course_id: 'a' }, { course_id: 'z' }], ''), 'a');
  assert.equal(chooseCourse([], 'a'), '');
});

test('plainText drops Markdown marks but keeps citations and structure', () => {
  const markdown = '## Supply\n\n**Supply** rises with *price* [1].\n\n- one `term`\n* two';
  assert.equal(plainText(markdown), 'Supply\n\nSupply rises with price [1].\n\n• one term\n• two');
});

test('documentText carries the cited sources into the document', () => {
  const result = {
    insert_text: 'Demand falls [2]. Also [1].',
    citations: [
      { number: 1, filename: 'lecture1.pdf', label: 'p. 3', text: '...' },
      { number: 2, filename: 'book.pdf', label: '', text: '...' },
      { number: 3, filename: 'unused.pdf', label: 'p. 9', text: '...' }
    ]
  };
  assert.equal(
    documentText(result),
    'Demand falls [2]. Also [1].\n\nSources:\n[1] lecture1.pdf, p. 3\n[2] book.pdf'
  );
  assert.equal(documentText({ text: 'No citations here.' }), 'No citations here.');
  assert.equal(documentText(null), '');
  assert.equal(documentText({ insert_text: '   ' }), '');
});

test('citationLines labels each citation', () => {
  assert.deepEqual(citationLines([{ number: 1, filename: 'a.pdf', label: 'p. 2', text: 'x' }]), [
    { number: 1, label: '[1] a.pdf, p. 2', text: 'x' }
  ]);
  assert.deepEqual(citationLines(undefined), []);
});

test('columnName counts like Excel', () => {
  assert.equal(columnName(0), 'A');
  assert.equal(columnName(25), 'Z');
  assert.equal(columnName(26), 'AA');
  assert.equal(columnName(27), 'AB');
  assert.equal(columnName(701), 'ZZ');
  assert.equal(columnName(702), 'AAA');
});

test('describeRange lists each non-empty cell with its formula', () => {
  const text = describeRange(
    "'Q1 data'!B7:C8",
    [
      [12, 30],
      ['', 42]
    ],
    [
      [12, '=SUM(A1:A3)'],
      ['', '=B7+C7']
    ]
  );
  assert.equal(
    text,
    "Sheet Q1 data, cells B7:C8\nB7: 12\nC7: =SUM(A1:A3) → 30\nC8: =B7+C7 → 42"
  );
  assert.equal(describeRange('Sheet1!A1', [['']], [['']]), 'Sheet Sheet1, cells A1\n(the selected cells are empty)');
  assert.match(describeRange('Sheet1!AA10:AB10', [[1, 2]], [[1, 2]], true), /AB10: 2\n\(selection truncated/);
});
