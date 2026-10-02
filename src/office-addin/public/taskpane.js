/**
 * Stacks task pane: the Office.js and DOM wiring around bridge.js.
 *
 * One adapter per Office app reads what the student is looking at and
 * writes an answer back through that app's own API. Office owns the
 * document and its save; the pane only ever passes text.
 */
import {
  HOSTS,
  assistError,
  assistRequest,
  bridgeHealth,
  chooseCourse,
  citationLines,
  describeRange,
  documentText,
  hostKey,
  listCourses,
  resolveBridgeBase,
  sendAssist,
  publishDocument,
  wholePackage,
  livePolicy, registerLive, pollLive, completeLive, disconnectLive, getWork
} from './bridge.js';
import { readWordDocument } from './readers/word.js';
import { readExcelDocument } from './readers/excel.js';
import { readPowerPointDocument } from './readers/powerpoint.js';
import { LivePane } from './live-pane.js';

const BRIDGE = resolveBridgeBase(window.location.search, window.location.origin);
const TOKEN = new URLSearchParams(window.location.search).get('token') || '';
// Excel selections can be whole columns; the model reads the first cells.
const MAX_ROWS = 100;
const MAX_COLUMNS = 20;

/** @type {(id: string) => any} */
const byId = (id) => document.getElementById(id);
const el = {
  status: /** @type {HTMLElement} */ (byId('status')),
  retry: /** @type {HTMLButtonElement} */ (byId('retry')),
  course: /** @type {HTMLSelectElement} */ (byId('course')),
  selection: /** @type {HTMLTextAreaElement} */ (byId('selection')),
  refresh: /** @type {HTMLButtonElement} */ (byId('refresh')),
  actions: /** @type {HTMLElement} */ (byId('actions')),
  question: /** @type {HTMLInputElement} */ (byId('question')),
  ask: /** @type {HTMLButtonElement} */ (byId('ask')),
  answerPanel: /** @type {HTMLElement} */ (byId('answer-panel')),
  result: /** @type {HTMLElement} */ (byId('result')),
  citations: /** @type {HTMLUListElement} */ (byId('citations')),
  insert: /** @type {HTMLButtonElement} */ (byId('insert')),
  replace: /** @type {HTMLButtonElement} */ (byId('replace')),
  engine: /** @type {HTMLElement} */ (byId('engine')),
  connectWork: /** @type {HTMLButtonElement} */ (byId('connect-work')),
  workPurpose: /** @type {HTMLSelectElement} */ (byId('work-purpose'))
};

let host = null;
let lastResult = null;
let busy = false;
const unsavedIdentity = `unsaved:${crypto.randomUUID()}`;
const identity = () => Office.context.document.url || unsavedIdentity;
let pollTimer = null;
let pollCycle = 0;
let pollInterval = 1000;
const readers = { word: readWordDocument, excel: readExcelDocument, powerpoint: readPowerPointDocument };
const livePane = new LivePane({
  identity,
  read: readWorkingDocument,
  poll: (id, externalId) => pollLive(fetch, BRIDGE, id, externalId, TOKEN),
  complete: (id, request) => completeLive(fetch, BRIDGE, id, request, TOKEN),
  onSnapshot: (result, binding) => {
    try { localStorage.setItem(binding.storage_key, JSON.stringify({ session_id: binding.session_id, revision: result.revision })); } catch { }
  },
  onLost: (error, disconnected) => setStatus(`${error.message}${disconnected ? ' Reconnect this document to restore live reading.' : ''}`, 'error')
});

function stopLive() {
  pollCycle++;
  clearTimeout(pollTimer);
  const binding = livePane.stop();
  if (binding) void disconnectLive(fetch, BRIDGE, binding.connection_id, TOKEN).catch(() => {});
}

async function pollConnection(cycle) {
  if (cycle !== pollCycle) return;
  await livePane.tick();
  if (cycle === pollCycle && livePane.binding) pollTimer = setTimeout(() => pollConnection(cycle), pollInterval);
}

async function readWorkingDocument(options) {
  const externalId = identity();
  const url = Office.context.document.url || '';
  const title = url ? decodeURIComponent(url.split('/').pop()).slice(0, 300) : `${HOSTS[host].name} document`;
  let result;
  try {
    result = await readers[host](options);
  } catch (error) {
    if (error.code !== 'UNSUPPORTED_HOST' || host === 'excel' || !supports('CompressedFile', '1.1')) throw error;
    const bytes = await wholePackage(Office.context.document);
    let binary = '';
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    const response = await fetch(`${BRIDGE}/office/read`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Office-Token': TOKEN },
      body: JSON.stringify({ host, kind: host, package_b64: btoa(binary) })
    });
    if (!response.ok) throw new Error('Could not read the Office package. Connect a file or screenshot in the companion.');
    const data = await response.json();
    if (!data.text?.trim()) throw new Error('This package has no readable text. Connect a screenshot or text version.');
    result = { text: data.text.slice(0, options.maxChars), coverage: 'partial', warnings: [...data.warnings.slice(0, 28), 'Office package text fallback: images and some document regions may be omitted.', ...(data.text.length > options.maxChars ? ['Text was truncated to the capture limit.'] : [])] };
  }
  if (identity() !== externalId) throw new Error('The Office document changed while reading. Connect it again.');
  return { title: title || `${HOSTS[host].name} document`, ...result, origin: 'office', external_id: externalId };
}

// --- Office adapters ------------------------------------------------------

function commonRead() {
  return new Promise((resolve, reject) => {
    Office.context.document.getSelectedDataAsync(Office.CoercionType.Text, (result) => {
      if (result.status === Office.AsyncResultStatus.Succeeded) resolve(String(result.value ?? ''));
      else reject(new Error(result.error.message));
    });
  });
}

function commonWrite(text) {
  return new Promise((resolve, reject) => {
    Office.context.document.setSelectedDataAsync(text, { coercionType: Office.CoercionType.Text }, (result) => {
      if (result.status === Office.AsyncResultStatus.Succeeded) resolve(undefined);
      else reject(new Error(result.error.message));
    });
  });
}

const supports = (set, version) => Office.context.requirements.isSetSupported(set, version);

const adapters = {
  word: {
    async read() {
      if (!supports('WordApi', '1.3')) return commonRead();
      return Word.run(async (context) => {
        const selection = context.document.getSelection();
        selection.load('text');
        await context.sync();
        if (selection.text.trim()) return selection.text;
        // Just a cursor: use the paragraph it is in.
        const paragraph = selection.paragraphs.getFirst();
        paragraph.load('text');
        await context.sync();
        return paragraph.text;
      });
    },
    async insert(text) {
      await Word.run(async (context) => {
        let anchor = context.document.getSelection().paragraphs.getLast();
        for (const line of text.split('\n')) {
          anchor = anchor.insertParagraph(line, 'After');
          anchor.styleBuiltIn = Word.BuiltInStyleName.normal;
        }
        await context.sync();
      });
      return 'Inserted below your selection.';
    },
    async replace(text) {
      await Word.run(async (context) => {
        context.document.getSelection().insertText(text, 'Replace');
        await context.sync();
      });
      return 'Replaced your selection.';
    }
  },

  excel: {
    async read() {
      if (!supports('ExcelApi', '1.7')) return commonRead();
      return Excel.run(async (context) => {
        const selected = context.workbook.getSelectedRange();
        selected.load(['address', 'rowCount', 'columnCount']);
        await context.sync();
        const truncated = selected.rowCount > MAX_ROWS || selected.columnCount > MAX_COLUMNS;
        const range = truncated
          ? selected
              .getCell(0, 0)
              .getResizedRange(Math.min(selected.rowCount, MAX_ROWS) - 1, Math.min(selected.columnCount, MAX_COLUMNS) - 1)
          : selected;
        range.load(['address', 'values', 'formulas']);
        await context.sync();
        return describeRange(range.address, range.values, range.formulas, truncated);
      });
    },
    async insert(text) {
      return Excel.run(async (context) => {
        const cell = context.workbook.getActiveCell();
        cell.load('address');
        await context.sync();
        if (supports('ExcelApi', '1.10')) {
          try {
            context.workbook.comments.add(cell, text);
            await context.sync();
            return `Added as a comment on ${cell.address.split('!').pop()}.`;
          } catch {
            // Comments can be unavailable (e.g. a shared or protected
            // workbook); fall back to a notes sheet below.
          }
        }
        const name = 'Stacks notes';
        let sheet = context.workbook.worksheets.getItemOrNullObject(name);
        await context.sync();
        if (sheet.isNullObject) {
          sheet = context.workbook.worksheets.add(name);
          sheet.getRange('A1:B1').values = [['About', 'Stacks']];
        }
        const used = sheet.getUsedRange();
        used.load('rowCount');
        await context.sync();
        const row = used.rowCount + 1;
        sheet.getRange(`A${row}:B${row}`).values = [[cell.address, text]];
        sheet.getRange(`B${row}`).format.wrapText = true;
        await context.sync();
        return `Added to the "${name}" sheet, row ${row}.`;
      });
    },
    async replace(text) {
      await Excel.run(async (context) => {
        context.workbook.getActiveCell().values = [[text]];
        await context.sync();
      });
      return 'Written into the active cell.';
    }
  },

  powerpoint: {
    async read() {
      if (!supports('PowerPointApi', '1.5')) return commonRead();
      return PowerPoint.run(async (context) => {
        const range = context.presentation.getSelectedTextRangeOrNullObject();
        range.load('text');
        await context.sync();
        if (!range.isNullObject && range.text.trim()) return range.text;
        // No text selected: read every text box on the selected slide.
        const slides = context.presentation.getSelectedSlides();
        slides.load('items');
        await context.sync();
        if (slides.items.length === 0) return '';
        const shapes = slides.items[0].shapes;
        shapes.load('items/type');
        await context.sync();
        const texts = [];
        for (const shape of shapes.items) {
          if (!['GeometricShape', 'TextBox', 'Placeholder'].includes(shape.type)) continue;
          try {
            const text = shape.textFrame.textRange;
            text.load('text');
            await context.sync();
            if (text.text.trim()) texts.push(text.text.trim());
          } catch {
            // A placeholder without text (a picture placeholder) has no
            // text frame; skip it.
          }
        }
        return texts.join('\n\n');
      });
    },
    async insert(text) {
      if (!supports('PowerPointApi', '1.5')) {
        await commonWrite(text);
        return 'Added to the slide.';
      }
      await PowerPoint.run(async (context) => {
        const slides = context.presentation.getSelectedSlides();
        slides.load('items');
        await context.sync();
        if (slides.items.length === 0) throw new Error('Select a slide first.');
        slides.items[0].shapes.addTextBox(text, { left: 40, top: 300, width: 600, height: 200 });
        await context.sync();
      });
      return 'Added a text box to this slide — move or restyle it as you like.';
    },
    async replace(text) {
      if (supports('PowerPointApi', '1.5')) {
        const done = await PowerPoint.run(async (context) => {
          const range = context.presentation.getSelectedTextRangeOrNullObject();
          range.load('text');
          await context.sync();
          if (range.isNullObject) return false;
          range.text = text;
          await context.sync();
          return true;
        });
        if (done) return 'Replaced the selected text.';
      }
      await commonWrite(text);
      return 'Replaced the selection.';
    }
  }
};

// --- pane -----------------------------------------------------------------

function setStatus(text, tone = '') {
  el.status.textContent = text;
  el.status.dataset.tone = tone;
}

function setBusy(value) {
  busy = value;
  for (const button of el.actions.querySelectorAll('button')) button.disabled = value || !el.course.value;
  el.ask.disabled = value || !el.course.value;
  el.connectWork.disabled = value || !el.course.value;
  el.course.disabled = value;
  el.workPurpose.disabled = value;
  el.refresh.disabled = value;
  el.retry.disabled = value;
  updateWriteButtons();
}

function clearAnswer() {
  lastResult = null;
  el.answerPanel.hidden = true;
  el.result.textContent = '';
  el.citations.replaceChildren();
  el.engine.textContent = '';
  updateWriteButtons();
}

function updateWriteButtons() {
  const ready = Boolean(documentText(lastResult));
  el.insert.disabled = busy || !ready;
  el.replace.disabled = busy || !ready;
}

async function refreshSelection() {
  if (!host) return;
  try {
    const text = await adapters[host].read();
    el.selection.value = text;
  } catch (error) {
    setStatus(`Could not read from ${HOSTS[host].name}: ${error.message}`, 'error');
  }
}

let selectionTimer = null;
function onSelectionChanged() {
  if (busy) return;
  clearTimeout(selectionTimer);
  selectionTimer = setTimeout(refreshSelection, 250);
}

function renderCitations(citations) {
  el.citations.replaceChildren();
  for (const line of citationLines(citations)) {
    const item = document.createElement('li');
    const label = document.createElement('span');
    label.className = 'citation-label';
    label.textContent = line.label;
    const text = document.createElement('span');
    text.className = 'citation-text';
    text.textContent = line.text;
    item.append(label, text);
    el.citations.append(item);
  }
}

async function ask(action) {
  const courseId = el.course.value;
  if (!courseId) {
    setStatus('Pick a course first.', 'error');
    return;
  }
  if (!el.selection.value.trim() && !el.question.value.trim()) {
    setStatus(`Select something in ${HOSTS[host].name}, or type a question.`, 'error');
    return;
  }
  setBusy(true);
  setStatus('Stacks is reading your course…');
  clearAnswer();
  try {
    const request = assistRequest(courseId, action, host, el.selection.value, el.question.value);
    lastResult = await sendAssist(fetch, BRIDGE, request, TOKEN);
    el.answerPanel.hidden = false;
    el.result.textContent = lastResult.text;
    renderCitations(lastResult.citations);
    el.engine.textContent = `Answered by ${lastResult.model}`;
    setStatus('Answered from your course.', 'ok');
  } catch (error) {
    setStatus(
      typeof error.status === 'number' ? assistError(error.status, error.detail) : 'Stacks is not reachable. Is the Stacks app open?',
      'error'
    );
  } finally {
    setBusy(false);
  }
}

async function write(mode) {
  const text = documentText(lastResult);
  if (!text) return;
  setBusy(true);
  try {
    const message = await adapters[host][mode](text);
    setStatus(`${message} Save as usual in ${HOSTS[host].name}.`, 'ok');
  } catch (error) {
    setStatus(`Could not write to the document: ${error.message}`, 'error');
  } finally {
    setBusy(false);
  }
}

function courseKey() {
  return `stacks.course:${Office.context.document.url || 'untitled'}`;
}

function remembered() {
  try {
    return localStorage.getItem(courseKey()) || '';
  } catch {
    return '';
  }
}

function remember(courseId) {
  try {
    localStorage.setItem(courseKey(), courseId);
  } catch {
    // Storage can be unavailable in some Office webviews; the pane then
    // falls back to the course Stacks suggests.
  }
}

async function connect() {
  setBusy(true);
  el.retry.hidden = true;
  setStatus('Connecting to Stacks…');
  try {
    const health = await bridgeHealth(fetch, BRIDGE, TOKEN);
    const courses = await listCourses(fetch, BRIDGE, TOKEN);
    el.course.replaceChildren();
    if (courses.length === 0) {
      el.course.append(new Option('No courses yet — add one in Stacks', ''));
      setStatus(`Connected to ${health.app} ${health.version}. Add a course in Stacks to start.`);
    } else {
      for (const course of courses) {
        el.course.append(new Option(`${course.name} (${course.source_count} sources)`, course.course_id));
      }
      el.course.value = chooseCourse(courses, remembered());
      setStatus(`Connected to ${health.app} ${health.version}.`, 'ok');
    }
  } catch {
    el.course.replaceChildren(new Option('Stacks is not reachable', ''));
    clearAnswer();
    setStatus('Stacks is not reachable. Open the Stacks app, then retry.', 'error');
    el.retry.hidden = false;
  } finally {
    setBusy(false);
  }
}

async function connectWork() {
  if (busy || !el.course.value) return;
  setBusy(true);
  setStatus('Reading the whole document for your companion…');
  try {
    stopLive();
    const policy = await livePolicy(fetch, BRIDGE, TOKEN);
    pollInterval = policy.poll_interval_ms;
    const externalId = identity();
    const storageKey = `stacks.work:${el.course.value}:${externalId}`;
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(storageKey) || 'null'); } catch { }
    if (saved?.session_id) {
      try {
        const latest = await getWork(fetch, BRIDGE, el.course.value, saved.session_id, TOKEN);
        saved = latest.document?.origin === 'office' && latest.document.external_id === externalId
          ? { session_id: latest.session_id, revision: latest.revision } : null;
      } catch (error) {
        if (error.status !== 404) throw error;
        saved = null;
      }
    }
    const common = { course_id: el.course.value, purpose: el.workPurpose.value, session_id: saved?.session_id ?? null, expected_revision: saved?.revision ?? 0 };
    const document = await readWorkingDocument(policy.reader);
    const result = await publishDocument(fetch, BRIDGE, { ...common, document }, TOKEN);
    try { localStorage.setItem(storageKey, JSON.stringify({ session_id: result.session_id, revision: result.revision })); } catch { }
    const connection = await registerLive(fetch, BRIDGE, { course_id: common.course_id, session_id: result.session_id, host, external_id: externalId }, TOKEN);
    livePane.bind({ connection_id: connection.connection_id, session_id: result.session_id, external_id: externalId, storage_key: storageKey });
    void pollConnection(pollCycle);
    setStatus(`Connected to the companion. Select “${result.title}” there; typing a message refreshes this document.`, 'ok');
  } catch (error) {
    setStatus(error.detail || error.message || 'Could not connect this document. Use Connect file in the companion.', 'error');
  } finally { setBusy(false); }
}

function wire() {
  const labels = HOSTS[host];
  el.selection.placeholder = labels.placeholder;
  el.insert.textContent = labels.insert;
  el.replace.textContent = labels.replace;
  for (const button of el.actions.querySelectorAll('button')) {
    button.addEventListener('click', () => ask(button.dataset.action));
  }
  el.ask.addEventListener('click', () => ask('explain'));
  el.question.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') ask('explain');
  });
  el.connectWork.addEventListener('click', connectWork);
  el.refresh.addEventListener('click', refreshSelection);
  el.retry.addEventListener('click', connect);
  el.course.addEventListener('change', () => {
    stopLive();
    remember(el.course.value);
    clearAnswer();
    setBusy(false);
  });
  el.insert.addEventListener('click', () => write('insert'));
  el.replace.addEventListener('click', () => write('replace'));
  Office.context.document.addHandlerAsync(Office.EventType.DocumentSelectionChanged, onSelectionChanged);
  window.addEventListener('pagehide', stopLive);
}

Office.onReady(async (info) => {
  host = hostKey(info?.host);
  if (!host) {
    setStatus('Open this pane from the Stacks button in Word, Excel, or PowerPoint.', 'error');
    return;
  }
  document.body.dataset.host = host;
  wire();
  await connect();
  await refreshSelection();
});
