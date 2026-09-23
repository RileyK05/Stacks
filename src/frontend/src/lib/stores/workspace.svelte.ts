import type { components } from '$lib/api/schema';

export type WorkspaceQuiz = components['schemas']['WorkspaceQuiz'];
export type WorkspaceDocument = components['schemas']['WorkspaceDocument'];
export type WorkspaceHtml = components['schemas']['WorkspaceHtml'];
export type WorkspaceCode = components['schemas']['WorkspaceCode'];
export type WorkspaceSheet = components['schemas']['WorkspaceSheet'];
export type WorkspaceSlides = components['schemas']['WorkspaceSlides'];
export type WorkspaceItem = WorkspaceQuiz | WorkspaceDocument | WorkspaceHtml | WorkspaceCode | WorkspaceSheet | WorkspaceSlides;

/**
 * Live state for one quiz in the workspace. The item itself is the
 * backend-validated payload (every question cites material — decision 009
 * gate runs server-side); this class only holds what the student does
 * with it, so switching between answers keeps their progress.
 */
export class QuizSession {
  readonly kind = 'quiz';
  readonly quiz: WorkspaceQuiz;
  responses = $state<(number | null)[]>([]);
  submitted = $state(false);

  constructor(quiz: WorkspaceQuiz) {
    this.quiz = quiz;
    this.responses = quiz.questions.map(() => null);
  }

  get answeredAll(): boolean {
    return this.responses.every((response) => response !== null);
  }

  get score(): number {
    return this.quiz.questions.filter((question, index) => this.responses[index] === question.answer)
      .length;
  }

  choose(questionIndex: number, optionIndex: number): void {
    if (!this.submitted) this.responses[questionIndex] = optionIndex;
  }

  submit(): void {
    if (this.answeredAll) this.submitted = true;
  }

  reset(): void {
    this.responses = this.quiz.questions.map(() => null);
    this.submitted = false;
  }

  /** A follow-up question for the chat about every missed question. */
  missedFollowUp(): string | null {
    const missed = this.quiz.questions.flatMap((question, index) => {
      const picked = this.responses[index];
      if (picked === null || picked === question.answer) return [];
      return [
        `"${question.prompt}" — I picked "${question.options[picked]}" but the answer is "${question.options[question.answer]}".`
      ];
    });
    if (missed.length === 0) return null;
    // One line: the chat input is single-line and would drop newlines.
    return `I got these quiz questions wrong. Help me understand why: ${missed.join(' ')}`;
  }
}

/** Live state for one editable document: the original stays intact so
 * the student can always revert to what the tutor (with citations) wrote. */
export class DocumentSession {
  readonly kind = 'document';
  readonly document: WorkspaceDocument;
  draft = $state('');

  constructor(document: WorkspaceDocument) {
    this.document = document;
    this.draft = document.content;
  }

  get edited(): boolean {
    return this.draft !== this.document.content;
  }

  revert(): void {
    this.draft = this.document.content;
  }
}

/** Rendered HTML carries no live state — the session just holds the item. */
export class HtmlSession {
  readonly kind = 'html';
  readonly htmlItem: WorkspaceHtml;

  constructor(htmlItem: WorkspaceHtml) {
    this.htmlItem = htmlItem;
  }
}

/** Code listings are read-only views — the session just holds the item. */
export class CodeSession {
  readonly kind = 'code';
  readonly item: WorkspaceCode;

  constructor(item: WorkspaceCode) {
    this.item = item;
  }
}

/** Live state for one editable sheet: the original rows stay intact so the
 * student can always revert to what the tutor (with citations) wrote. */
export class SheetSession {
  readonly kind = 'sheet';
  readonly item: WorkspaceSheet;
  draft = $state<string[][]>([]);

  constructor(item: WorkspaceSheet) {
    this.item = item;
    this.draft = item.rows.map((row) => [...row]);
  }

  get edited(): boolean {
    return this.draft.some((row, index) => row.join('') !== this.item.rows[index]?.join(''));
  }

  revert(): void {
    this.draft = this.item.rows.map((row) => [...row]);
  }

  addRow(): void {
    this.draft.push(this.item.columns.map(() => ''));
  }

  removeRow(index: number): void {
    if (this.draft.length > 1) this.draft.splice(index, 1);
  }
}

/** Live state for one slide deck: the deck is markdown split on --- lines;
 * the draft keeps the student's edits so they survive tab switches. */
export class SlidesSession {
  readonly kind = 'slides';
  readonly item: WorkspaceSlides;
  draft = $state('');

  constructor(item: WorkspaceSlides) {
    this.item = item;
    this.draft = item.deck;
  }

  get edited(): boolean {
    return this.draft !== this.item.deck;
  }

  revert(): void {
    this.draft = this.item.deck;
  }
}

export type WorkspaceSession =
  | QuizSession
  | DocumentSession
  | HtmlSession
  | CodeSession
  | SheetSession
  | SlidesSession;

export function openSession(item: WorkspaceItem): WorkspaceSession {
  switch (item.type) {
    case 'quiz':
      return new QuizSession(item);
    case 'document':
      return new DocumentSession(item);
    case 'html':
      return new HtmlSession(item);
    case 'code':
      return new CodeSession(item);
    case 'sheet':
      return new SheetSession(item);
    case 'slides':
      return new SlidesSession(item);
  }
}

const FALLBACK_TITLES: Record<WorkspaceSession['kind'], string> = {
  quiz: 'Practice quiz',
  document: 'Study document',
  html: 'Visualization',
  code: 'Code',
  sheet: 'Spreadsheet',
  slides: 'Slides'
};

export function itemTitle(session: WorkspaceSession): string {
  const item =
    session.kind === 'quiz'
      ? session.quiz
      : session.kind === 'document'
        ? session.document
        : session.kind === 'html'
          ? session.htmlItem
          : session.item;
  return item.title ?? FALLBACK_TITLES[session.kind];
}

export interface CanvasTab {
  /** Stable key: which turn produced the item, and its position there. */
  id: string;
  /** Which chat turn produced the item, e.g. "Q3". */
  origin: string;
  title: string;
  turnIndex: number;
  session: WorkspaceSession;
}

/**
 * The right-hand workspace canvas. Tabs accumulate across turns — asking for
 * a study guide does not evict the quiz from earlier in the conversation —
 * and stay open until the student closes them or clears the chat session.
 */
export class WorkspaceCanvas {
  tabs = $state<CanvasTab[]>([]);
  activeId = $state<string | null>(null);
  /** Panel dismissed (tabs kept); the next artifact or "Open in workspace" revives it. */
  hidden = $state(false);

  get open(): boolean {
    return !this.hidden && this.tabs.length > 0;
  }

  get active(): CanvasTab | null {
    return this.tabs.find((tab) => tab.id === this.activeId) ?? null;
  }

  hasTabForTurn(turnIndex: number): boolean {
    return this.tabs.some((tab) => tab.turnIndex === turnIndex);
  }

  openFromTurn(turnIndex: number, sessions: WorkspaceSession[]): void {
    if (sessions.length === 0) return;
    const origin = `Q${turnIndex + 1}`;
    let firstNew: string | null = null;
    sessions.forEach((session, itemIndex) => {
      const id = `${origin}:${itemIndex}`;
      if (this.tabs.some((tab) => tab.id === id)) return;
      this.tabs.push({ id, origin, title: itemTitle(session), turnIndex, session });
      firstNew ??= id;
    });
    this.activeId = firstNew ?? this.tabs.find((tab) => tab.turnIndex === turnIndex)?.id ?? this.activeId;
    this.hidden = false;
  }

  activate(id: string): void {
    this.activeId = id;
  }

  close(id: string): void {
    const index = this.tabs.findIndex((tab) => tab.id === id);
    if (index === -1) return;
    this.tabs.splice(index, 1);
    if (this.activeId === id) {
      this.activeId = this.tabs[Math.min(index, this.tabs.length - 1)]?.id ?? null;
    }
  }

  hide(): void {
    this.hidden = true;
  }

  clear(): void {
    this.tabs = [];
    this.activeId = null;
    this.hidden = false;
  }
}
