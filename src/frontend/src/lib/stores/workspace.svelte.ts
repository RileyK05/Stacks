import type { components } from '$lib/api/schema';

export type WorkspaceQuiz = components['schemas']['WorkspaceQuiz'];
export type WorkspaceDocument = components['schemas']['WorkspaceDocument'];
export type WorkspaceItem = WorkspaceQuiz | WorkspaceDocument;

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

export type WorkspaceSession = QuizSession | DocumentSession;

export function openSession(item: WorkspaceItem): WorkspaceSession {
  return item.type === 'quiz' ? new QuizSession(item) : new DocumentSession(item);
}

export function itemTitle(session: WorkspaceSession): string {
  const item = session.kind === 'quiz' ? session.quiz : session.document;
  return item.title ?? (session.kind === 'quiz' ? 'Practice quiz' : 'Study document');
}
