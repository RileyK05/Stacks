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

/** Where the bridge is. An override may point only to this origin or a local bridge. */
export function resolveBridgeBase(search, origin) {
  const override = new URLSearchParams(search).get('bridge');
  const pane = new URL(origin);
  if (pane.protocol !== 'http:' && pane.protocol !== 'https:') {
    throw new Error('The Office bridge must use HTTP or HTTPS.');
  }
  const bridge = new URL(override || origin, pane);
  const hostname = bridge.hostname.toLowerCase().replace(/^\[|\]$/g, '');
  const loopback = hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1';
  if ((bridge.protocol !== 'http:' && bridge.protocol !== 'https:') ||
      bridge.username || bridge.password || bridge.search || bridge.hash ||
      (bridge.origin !== pane.origin && !loopback)) {
    throw new Error('The Office bridge must use this pane’s origin or a loopback HTTP(S) address.');
  }
  return `${bridge.origin}${bridge.pathname.replace(/\/+$/, '')}`;
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

/** The actions the pane offers, in display order. Critique is separate and Word-only. */
export const ACTIONS = [
  { id: 'explain', label: 'Explain' },
  { id: 'find', label: 'Find in my course' },
  { id: 'quiz', label: 'Quiz me' },
  { id: 'summarize', label: 'Summarize' }
];

export const FALLACY_LABELS = {
  straw_man: 'straw man',
  false_dilemma: 'false dilemma',
  hasty_generalization: 'hasty generalization',
  post_hoc: 'post hoc',
  appeal_to_authority: 'appeal to authority',
  circular: 'circular',
  slippery_slope: 'slippery slope',
  ad_hominem: 'ad hominem',
  equivocation: 'equivocation',
  unsupported_claim: 'unsupported claim',
  missing_counterargument: 'missing counterargument'
};

export const DIMENSION_LABELS = {
  requirements: 'Requirements',
  reasoning: 'Reasoning',
  evidence: 'Evidence',
  structure: 'Structure',
  craft: 'Craft',
  clarity: 'Clarity'
};

/** Essay kinds the critic accepts. The student chooses; the pane does not guess. */
export const ESSAY_GENRES = [
  ['argumentative', 'Argumentative'],
  ['analytical', 'Analytical'],
  ['research', 'Research'],
  ['comparative', 'Comparative'],
  ['creative', 'Creative'],
  ['reflective', 'Reflective'],
  ['rhetorical', 'Rhetorical']
];

/** Harshness bands. Thresholds match configs/companion.toml (30 and 75). */
export function criticBand(score) {
  if (score < 30) {
    return { id: 'rough', label: 'Rough draft', detail: 'Only a problem that would change the draft.' };
  }
  if (score < 75) {
    return {
      id: 'strong',
      label: 'Strong reviewer',
      detail: 'A weak warrant, mismatched evidence, or a dropped counterargument is in range.'
    };
  }
  return {
    id: 'severe',
    label: 'Severe',
    detail: 'Almost every supplied claim with a real gap. The wording is blunt.'
  };
}

export function latestCritique(turns) {
  if (!Array.isArray(turns)) return null;
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const critique = turns[index]?.reply?.critique;
    if (critique) return critique;
  }
  return null;
}

/** A partial latest critique can ask for sections that pass did not read. */
export function unreadAvailable(turns) {
  const critique = latestCritique(turns);
  return Boolean(critique && critique.coverage && critique.coverage.complete === false);
}

/** Critique comments on the draft. Insert and Replace stay hidden for that result. */
export function showWriteActions(result) {
  return Boolean(result) && result.action !== 'critique';
}

export function critiqueRequest(courseId, sessionId, revision, score, genre, instruction = '', selection = '', focus = 'draft') {
  return {
    course_id: courseId,
    session_id: sessionId,
    host: 'word',
    request_id: crypto.randomUUID(),
    expected_revision: revision,
    critic_score: score,
    essay_genre: genre,
    instruction: instruction ?? '',
    selection: selection ?? '',
    focus
  };
}

export async function sendCritique(fetchImpl, base, request, token) {
  return postJson(fetchImpl, `${base}/office/critique`, request, token);
}

/** A failed critique keeps the bridge's reason. It is not the graded-work refusal. */
export function critiqueError(status, detail = '') {
  if (status === 422 || status === 409) return detail || 'The critic could not review this draft.';
  return assistError(status, detail);
}

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

export async function publishDocument(fetchImpl, base, request, token) {
  return postJson(fetchImpl, `${base}/office/work-document`, request, token);
}

export async function publishPackage(fetchImpl, base, request, token) {
  return postJson(fetchImpl, `${base}/office/work-package`, request, token);
}

export async function livePolicy(fetchImpl, base, token) {
  return getJson(fetchImpl, `${base}/office/live-policy`, token);
}

export async function getWork(fetchImpl, base, courseId, sessionId, token) {
  return getJson(fetchImpl, `${base}/office/work/${sessionId}?course_id=${encodeURIComponent(courseId)}`, token);
}

export async function registerLive(fetchImpl, base, request, token) {
  return postJson(fetchImpl, `${base}/office/live`, request, token);
}

export async function pollLive(fetchImpl, base, connectionId, externalId, token) {
  return postJson(fetchImpl, `${base}/office/live/${connectionId}/poll`, { external_id: externalId }, token);
}

export async function completeLive(fetchImpl, base, connectionId, request, token) {
  return postJson(fetchImpl, `${base}/office/live/${connectionId}/complete`, request, token);
}

export async function disconnectLive(fetchImpl, base, connectionId, token) {
  const response = await fetchImpl(`${base}/office/live/${connectionId}`, { method: 'DELETE', headers: headers(token) });
  if (!response.ok) throw await failure(response);
}

/** Read the current full Office package; release Office's temporary file on every path. */
export async function wholePackage(document, maximumBytes = 20000000) {
  const file = await new Promise((resolve, reject) => {
    document.getFileAsync('compressed', { sliceSize: 65536 }, result => {
      if (result.status === 'succeeded') resolve(result.value);
      else reject(new Error(result.error?.message || 'Whole-document reading is unavailable in this host.'));
    });
  });
  try {
    if (file.size > maximumBytes) throw new Error('This document exceeds the 20 MB working-file limit.');
    const slices = [];
    let received = 0;
    for (let index = 0; index < file.sliceCount; index++) {
      const slice = await new Promise((resolve, reject) => file.getSliceAsync(index, result => {
        if (result.status === 'succeeded') resolve(result.value.data);
        else reject(new Error(result.error?.message || 'Could not read the whole document.'));
      }));
      received += slice.length;
      if (received > maximumBytes) throw new Error('This document exceeds the 20 MB working-file limit.');
      slices.push(Uint8Array.from(slice));
    }
    const bytes = new Uint8Array(received);
    let offset = 0;
    for (const slice of slices) { bytes.set(slice, offset); offset += slice.length; }
    return bytes;
  } finally {
    await new Promise(resolve => file.closeAsync(() => resolve(undefined)));
  }
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
