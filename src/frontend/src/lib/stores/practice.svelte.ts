import { api } from '$lib/api/client';
import type { components } from '$lib/api/schema';

export type PracticeQuestion = components['schemas']['PracticeQuestion'];
export type SuiteFromSaved = components['schemas']['SuiteFromSaved'];
type PracticeRun = components['schemas']['PracticeRun'];
type PracticeHelp = components['schemas']['PracticeHelp'];
type ContentFeedback = components['schemas']['ContentFeedback'];
export type FeedbackTarget = 'question' | 'hint' | 'explain';

export interface PracticeContext {
  courseId: string;
  artifactId: string;
  version: number;
  ready: boolean;
}

export class PracticeSession {
  questions = $state<PracticeQuestion[]>([]);
  responses = $state<(number | string | null)[]>([]);
  helped = $state<boolean[]>([]);
  submitted = $state(false);
  loading = $state(false);
  saving = $state(false);
  submissionPending = $state(false);
  ready = $state(false);
  error = $state('');
  practiceId = $state<string | null>(null);
  run = $state<PracticeRun | null>(null);
  evidence = $state<{ filename: string; label: string }[]>([]);
  passages = $state<string[]>([]);
  assistance = $state<(PracticeHelp | null)[]>([]);
  supportErrors = $state<string[]>([]);
  helping = $state(false);
  helpIndex = $state<number | null>(null);
  feedback = $state<ContentFeedback[]>([]);
  ratingBusy = $state(false);
  ratingError = $state('');
  protected courseId = '';
  private runId = crypto.randomUUID();
  private pending: Promise<void> | null = null;

  constructor(questions: PracticeQuestion[], practiceId: string | null = null, readonly savedOrigin: SuiteFromSaved | null = null) {
    this.questions = questions;
    this.practiceId = practiceId;
    this.responses = questions.map(() => null);
    this.helped = questions.map(() => false);
  }

  get answeredAll(): boolean {
    return (
      this.responses.length > 0 &&
      this.questions.every((question, index) => {
        const response = this.responses[index];
        if (question.format === 'short_answer') return typeof response === 'string' && response.trim().length > 0;
        return typeof response === 'number';
      })
    );
  }

  correctAnswer(index: number): number | null {
    return this.run?.correct_answers[index] ?? (this.run?.results[index] === null ? null : this.questions[index].answer);
  }

  get score(): number {
    return this.run?.results.filter((result) => result === true).length ?? 0;
  }

  choose(questionIndex: number, optionIndex: number): void {
    if (!this.submitted && !this.saving && !this.submissionPending) this.responses[questionIndex] = optionIndex;
  }

  write(questionIndex: number, text: string): void {
    if (!this.submitted && !this.saving && !this.submissionPending) this.responses[questionIndex] = text;
  }

  connect(courseId: string): Promise<void> {
    if (this.ready || this.pending) return this.pending ?? Promise.resolve();
    this.courseId = courseId;
    this.pending = this.load().finally(() => { this.pending = null; });
    return this.pending;
  }

  private async load(): Promise<void> {
    this.loading = true;
    this.error = '';
    try {
      if (!this.courseId || (!this.practiceId && !this.savedOrigin)) throw new Error('Open a saved quiz to record a practice session.');
      const result = this.practiceId
        ? await api.GET('/courses/{course_id}/practice/{suite_id}', { params: { path: { course_id: this.courseId, suite_id: this.practiceId } } })
        : await api.POST('/courses/{course_id}/practice', { params: { path: { course_id: this.courseId } }, body: this.savedOrigin! });
      if (result.error || !result.data) throw result.error ?? new Error('Could not open the practice test.');
      this.practiceId = result.data.suite.suite_id;
      this.questions = result.data.suite.questions;
      this.evidence = result.data.suite.evidence.map((source) => ({ filename: String(source.filename ?? 'Removed source'), label: String(source.label ?? '') }));
      this.passages = result.data.suite.evidence.map((source) => String(source.text ?? 'This passage is no longer available.'));
      this.feedback = result.data.feedback ?? [];
      this.assistance = this.questions.map(() => null);
      this.supportErrors = this.questions.map(() => '');
      this.responses = this.questions.map(() => null);
      this.helped = this.questions.map(() => false);
      if (result.data.latest_run) this.restore(result.data.latest_run);
      this.ready = true;
    } catch (error) {
      this.error = error instanceof Error ? error.message : 'Could not load practice history. Your answers are still here; retry.';
    } finally {
      this.loading = false;
    }
  }

  private restore(run: PracticeRun): void {
    this.run = run;
    this.responses = run.answers;
    this.helped = run.helped;
    this.submitted = true;
    this.submissionPending = false;
  }

  async submit(): Promise<void> {
    if (!this.answeredAll || !this.ready || this.saving || this.helping || !this.practiceId) return;
    this.saving = true;
    this.submissionPending = true;
    this.error = '';
    const answers = this.responses.map((pick) => pick!);
    try {
      const { data, error } = await api.POST('/courses/{course_id}/practice/{suite_id}/runs', {
        params: { path: { course_id: this.courseId, suite_id: this.practiceId } },
        body: { run_id: this.runId, answers, helped: [...this.helped] }
      });
      if (error || !data) throw error ?? new Error('Could not save the test.');
      this.restore(data);
    } catch {
      this.error = 'We could not confirm this test was saved. Your submitted answers are kept here; retry submitting.';
    } finally {
      this.saving = false;
    }
  }

  reset(): void {
    if (this.saving || this.submissionPending || this.helping || this.ratingBusy) return;
    this.responses = this.questions.map(() => null);
    // Help is tracked per attempt. The backend independently marks a repeat
    // as previously revealed, so carrying this flag forward would conflate
    // exposure with help used during this attempt.
    this.helped = this.questions.map(() => false);
    this.runId = crypto.randomUUID();
    this.submitted = false;
    this.run = null;
    this.error = '';
    this.assistance = this.questions.map(() => null);
    this.supportErrors = this.questions.map(() => '');
  }

  async requestHelp(index: number): Promise<void> {
    if (!this.ready || !this.practiceId || this.saving || this.submissionPending || this.helping) return;
    const kind = this.submitted ? 'explain' : 'hint';
    if (this.assistance[index]?.kind === kind) return;
    const runId = this.run?.run_id ?? this.runId;
    this.helping = true;
    this.helpIndex = index;
    this.supportErrors[index] = '';
    try {
      const { data, error } = await api.POST('/courses/{course_id}/practice/{suite_id}/questions/{index}/help', {
        params: { path: { course_id: this.courseId, suite_id: this.practiceId, index } },
        body: { run_id: runId, kind }
      });
      if (error || !data) throw error ?? new Error('Could not prepare help.');
      this.assistance[index] = data;
      if (kind === 'hint') this.helped[index] = true;
    } catch (error) {
      this.supportErrors[index] = error instanceof Error ? error.message :
        typeof error === 'object' && error && 'detail' in error ? String(error.detail) : 'Could not prepare help. Try again.';
    } finally {
      this.helping = false;
      this.helpIndex = null;
    }
  }

  rating(index: number, target: FeedbackTarget): ContentFeedback | undefined {
    const currentHelp = this.assistance[index];
    return this.feedback.find((f) => f.question_index === index && f.target === target &&
      (target === 'question' || f.help_id === currentHelp?.help_id));
  }

  async rate(index: number, target: FeedbackTarget, rating: 'good' | 'bad' | null, reason = ''): Promise<void> {
    if (!this.ready || !this.practiceId || this.ratingBusy) return;
    this.ratingBusy = true;
    this.ratingError = '';
    try {
      const { data, error } = await api.PUT('/courses/{course_id}/practice/{suite_id}/questions/{index}/feedback', {
        params: { path: { course_id: this.courseId, suite_id: this.practiceId, index } },
        body: { target, rating, reason, help_id: target === 'question' ? null : this.assistance[index]?.help_id ?? null }
      });
      if (error || !data) throw error;
      this.feedback = data;
    } catch {
      this.ratingError = 'Could not save content feedback. Try again.';
    } finally {
      this.ratingBusy = false;
    }
  }

  async challenge(index: number): Promise<void> {
    if (!this.practiceId || this.saving || this.helping) return;
    this.saving = true;
    try {
      const { data, error } = await api.PATCH('/courses/{course_id}/practice/{suite_id}/questions/{index}', {
        params: { path: { course_id: this.courseId, suite_id: this.practiceId, index } },
        body: { answer: null, reason: 'Student disputed this question; exclude it pending review.' }
      });
      if (error || !data) throw error;
      this.assistance[index] = null;
      if (this.run) {
        const refreshed = await api.GET('/courses/{course_id}/practice/runs/{run_id}', {
          params: { path: { course_id: this.courseId, run_id: this.run.run_id } }
        });
        if (refreshed.error || !refreshed.data?.latest_run) throw refreshed.error;
        this.restore(refreshed.data.latest_run);
      }
    } catch {
      this.error = 'Could not flag this question. Try again.';
    } finally {
      this.saving = false;
    }
  }
}
