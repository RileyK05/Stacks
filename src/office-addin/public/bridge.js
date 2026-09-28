/**
 * Pure logic for the Stacks Office task pane, separated from the Office.js
 * and DOM wiring (taskpane.js) so it can be unit-tested in Node:
 *
 *   npm test --prefix src/office-addin
 *
 * The pane reads what the student is looking at, asks the local Stacks
 * bridge, and hands text back to Office. Office owns the document; nothing
 * here touches an OOXML file.
 */

/** Where the bridge is. The pane is served by the Stacks backend itself
 * (same origin), so it calls its own origin; ?bridge= overrides for tests. */
export function resolveBridgeBase(search, origin) {
  const override = new URLSearchParams(search).get('bridge');
  return (override || origin).replace(/\/+$/, '');
}

/** What each Office app calls things in the pane. */
export const HOSTS = {
  word: {
    name: 'Word',
    placeholder: 'Select text in your document, or type here.',
    insert: 'Insert below',
    replace: 'Replace selection'
  },
  excel: {
    name: 'Excel',
    placeholder: 'Select cells in your workbook, or type here.',
    insert: 'Add as comment',
    replace: 'Write into cell'
  },
  powerpoint: {
    name: 'PowerPoint',
    placeholder: 'Select a slide or some text, or type here.',
    insert: 'Add to slide',
    replace: 'Replace selected text'
  }
};

/** Normalise Office's host name ("PowerPoint") to ours ("powerpoint"). */
export function hostKey(officeHost) {
  const key = String(officeHost || '').toLowerCase();
  return key in HOSTS ? key : null;
}

/** The actions the pane offers, in display order. */
export const ACTIONS = [
  { id: 'explain', label: 'Explain' },
  { id: 'find', label: 'Find in my course' },
  { id: 'quiz', label: 'Quiz me' },
  { id: 'summarize', label: 'Summarize' }
];

export async function bridgeHealth(fetchImpl, base, token) {
  return getJson(fetchImpl, `${base}/office/health`, token);
}

export async function listCourses(fetchImpl, base, token) {
  return getJson(fetchImpl, `${base}/office/courses`, token);
}

/** Build the body for POST /office/assist. */
export function assistRequest(courseId, action, host, context, instruction = '') {
  return {
    course_id: courseId,
    action,
    host,
    context: context ?? '',
    instruction: instruction ?? ''
  };
}

/** Ask Stacks to answer from the course. Throws an Error with `.status`
 * (and `.detail`, the bridge's reason) on a non-OK response. */
export async function sendAssist(fetchImpl, base, request, token) {
  return postJson(fetchImpl, `${base}/office/assist`, request, token);
}

/** A human status line for a failed request. */
export function assistError(status, detail = '') {
  if (status === 422) return 'Stacks won’t do graded work you’ll submit. Ask it to explain instead.';
  if (status === 404) return detail || 'Nothing in this course matches what you selected.';
  if (status === 503) return 'Stacks has no model ready. Open Stacks → Settings and pick or download one.';
  if (status === 402) return 'Your model budget is reached (Stacks → Settings).';
  if (status === 401) return 'Stacks refused the connection. Reconnect Office from Stacks → Settings.';
  return `Stacks could not answer (${status}).`;
}

/**
 * Pick the course to show: the one this document used last, else the one
 * Stacks opened Office from, else the first. `remembered` may be stale.
 */
export function chooseCourse(courses, remembered) {
  if (!Array.isArray(courses) || courses.length === 0) return '';
  if (remembered && courses.some((course) => course.course_id === remembered)) return remembered;
  const suggested = courses.find((course) => course.suggested);
  return (suggested ?? courses[0]).course_id;
}

/** Answer Markdown as plain document text: no emphasis marks or heading
 * hashes, bullets kept as "•". */
export function plainText(markdown) {
  return String(markdown ?? '')
    .replace(/\r\n/g, '\n')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^[ \t]*[-*+][ \t]+/gm, '• ')
    .replace(/(\*\*|__)(.+?)\1/g, '$2')
    .replace(/(^|[^*\w])\*(?!\s)([^*\n]+?)\*(?!\w)/g, '$1$2')
    .replace(/`([^`\n]+)`/g, '$1')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/**
 * What goes into the document: the answer as plain text plus the sources
 * it cites, so the citations travel with the text. Returns '' when there is
 * nothing to write.
 */
export function documentText(result) {
  const body = plainText(result?.insert_text ?? result?.text ?? '');
  if (!body) return '';
  const cited = new Set([...body.matchAll(/\[(\d+)\]/g)].map((match) => Number(match[1])));
  const sources = (Array.isArray(result?.citations) ? result.citations : [])
    .filter((citation) => cited.has(citation.number))
    .map((citation) => citationLabel(citation));
  return sources.length ? `${body}\n\nSources:\n${sources.join('\n')}` : body;
}

export function citationLabel(citation) {
  return `[${citation.number}] ${citation.filename}${citation.label ? `, ${citation.label}` : ''}`;
}

/** Citations for display, one short line each. */
export function citationLines(citations) {
  if (!Array.isArray(citations)) return [];
  return citations.map((citation) => ({
    number: citation.number,
    label: citationLabel(citation),
    text: citation.text ?? ''
  }));
}

/** Excel column letters for a zero-based index: 0 -> A, 27 -> AB. */
export function columnName(index) {
  let name = '';
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) {
    name = String.fromCharCode(65 + ((n - 1) % 26)) + name;
  }
  return name;
}

function columnIndex(letters) {
  return [...letters.toUpperCase()].reduce((total, letter) => total * 26 + letter.charCodeAt(0) - 64, 0) - 1;
}

/**
 * Describe an Excel selection for the model: the address, then one line per
 * non-empty cell with its value, and its formula where it has one. Cells
 * are addressed so the model (and the student) can refer to them.
 */
export function describeRange(address, values, formulas, truncated = false) {
  const [sheetPart, cellsPart] = String(address).includes('!')
    ? String(address).split(/!(?=[^!]*$)/)
    : ['', String(address)];
  const start = /^\$?([A-Za-z]+)\$?(\d+)/.exec(cellsPart || '') ?? ['', 'A', '1'];
  const firstColumn = columnIndex(start[1]);
  const firstRow = Number(start[2]);
  const lines = [sheetPart ? `Sheet ${sheetPart.replace(/^'|'$/g, '')}, cells ${cellsPart}` : String(address)];
  (values ?? []).forEach((row, r) => {
    row.forEach((value, c) => {
      const formula = formulas?.[r]?.[c];
      const hasFormula = typeof formula === 'string' && formula.startsWith('=');
      if (!hasFormula && (value === '' || value === null || value === undefined)) return;
      const cell = `${columnName(firstColumn + c)}${firstRow + r}`;
      lines.push(hasFormula ? `${cell}: ${formula} → ${value}` : `${cell}: ${value}`);
    });
  });
  if (lines.length === 1) lines.push('(the selected cells are empty)');
  if (truncated) lines.push('(selection truncated to its first cells)');
  return lines.join('\n');
}

async function getJson(fetchImpl, url, token) {
  const response = await fetchImpl(url, { headers: headers(token) });
  if (!response.ok) throw await failure(response);
  return response.json();
}

async function postJson(fetchImpl, url, body, token) {
  const response = await fetchImpl(url, {
    method: 'POST',
    headers: { ...headers(token), 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!response.ok) throw await failure(response);
  return response.json();
}

function headers(token) {
  return token ? { 'X-Office-Token': token } : {};
}

async function failure(response) {
  let detail = '';
  try {
    const body = await response.json();
    detail = typeof body?.detail === 'string' ? body.detail : '';
  } catch {
    detail = '';
  }
  return Object.assign(new Error(`Stacks returned ${response.status}${detail ? `: ${detail}` : ''}`), {
    status: response.status,
    detail
  });
}
