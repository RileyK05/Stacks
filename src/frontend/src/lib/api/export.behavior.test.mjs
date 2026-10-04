import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { createStoreRuntime, installApiMock } from '../../../tests/helpers/storeRuntime.mjs';

let vite;
let restoreFetch;
let exportsApi;
const requests = [];

before(async () => {
  vite = await createStoreRuntime(['src/lib/api/export.ts']);
  restoreFetch = installApiMock(async (request) => {
    const pathname = new URL(request.url).pathname;
    if (pathname.endsWith('/export') && !pathname.endsWith('/export-from-message')) {
      return new Response(JSON.stringify({ path: 'default-export-folder/notes.csv', filename: 'notes.csv' }), {
        status: 200,
        headers: { 'content-type': 'application/json' }
      });
    }
    requests.push({
      url: request.url,
      body: await request.clone().json(),
      token: request.headers.get('X-App-Token')
    });
    return new Response(new Blob(['rendered bytes']), {
      status: 200,
      headers: {
        'content-type': 'application/octet-stream',
        'content-disposition': "attachment; filename*=UTF-8''Notes%20%C3%A9tude.md"
      }
    });
  });
  exportsApi = await vite.ssrLoadModule('/src/lib/api/export.ts');
});

after(async () => {
  restoreFetch?.();
  await vite?.close();
});

test('workspace export sends the original message identity and exact draft, then reads server filename and bytes', async () => {
  requests.length = 0;
  const file = await exportsApi.requestWorkspaceExport(
    { courseId: 'course-7', messageId: 'message-3', itemIndex: 2 },
    'csv',
    [['Term', 'Definition'], ['Mass', 'measure of inertia']]
  );

  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, 'http://localhost/api/courses/course-7/artifacts/export-from-message');
  assert.deepEqual(requests[0].body, {
    format: 'csv', message_id: 'message-3', item_index: 2, as_copy: false,
    draft: [['Term', 'Definition'], ['Mass', 'measure of inertia']]
  });
  assert.equal(file.filename, 'Notes étude.md');
  assert.equal(await file.blob.text(), 'rendered bytes');
});

test('saved-artifact native export downloads binary bytes rather than the JSON default-folder result', async () => {
  requests.length = 0;
  const file = await exportsApi.requestArtifactExport('course-7', 'artifact-8', 'md');
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, 'http://localhost/api/courses/course-7/artifacts/artifact-8/download');
  assert.deepEqual(requests[0].body, { format: 'md', path: null });
  assert.equal(file.filename, 'Notes étude.md');
  assert.equal(await file.blob.text(), 'rendered bytes');
});

test('native cancel is reported as no saved export and native save failures propagate', async () => {
  const file = { filename: 'notes.md', blob: new Blob(['abc']) };
  let sent;
  const canceled = await exportsApi.deliverExport(file, {
    native: true,
    saveNative: async (filename, data) => {
      sent = { filename, data };
      return null;
    }
  });
  assert.equal(canceled, null);
  assert.deepEqual(sent, { filename: 'notes.md', data: [97, 98, 99] });

  await assert.rejects(
    exportsApi.deliverExport(file, { native: true, saveNative: async () => { throw new Error('disk full'); } }),
    /disk full/
  );
});

test('browser delivery completes only after handing the returned server file to the downloader', async () => {
  const file = { filename: 'server-name.csv', blob: new Blob(['cited csv']) };
  let handedOff;
  const result = await exportsApi.deliverExport(file, {
    native: false,
    browserDownload: (download) => { handedOff = download; }
  });
  assert.equal(handedOff, file);
  assert.deepEqual(result, { path: 'server-name.csv', filename: 'server-name.csv' });
});
