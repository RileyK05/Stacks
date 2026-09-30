import { api } from '$lib/api/client';
import type { components } from '$lib/api/schema';

export type PracticeQuestion = components['schemas']['PracticeQuestion'];
export type SuiteFromSaved = components['schemas']['SuiteFromSaved'];
type PracticeRun = components['schemas']['PracticeRun'];

export interface PracticeContext {
  courseId: string;
  artifactId: string;
  version: number;
  ready: boolean;
}

export class PracticeSession {
  questions = $state<PracticeQuestion[]>([]);
  responses = $state<(number | null)[]>([]);
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
    return this.responses.length > 0 && this.responses.every((response) => response !== null);
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
    if (!this.answeredAll || !this.ready || this.saving || !this.practiceId) return;
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
    if (this.saving || this.submissionPending) return;
    this.responses = this.questions.map(() => null);
    this.helped = this.questions.map(() => true);
    this.runId = crypto.randomUUID();
    this.submitted = false;
    this.run = null;
    this.error = '';
  }

  async challenge(index: number): Promise<void> {
    if (!this.practiceId || this.saving) return;
    this.saving = true;
    try {
      const { data, error } = await api.PATCH('/courses/{course_id}/practice/{suite_id}/questions/{index}', {
        params: { path: { course_id: this.courseId, suite_id: this.practiceId, index } },
        body: { answer: null, reason: 'Student disputed this question; exclude it pending review.' }
      });
      if (error || !data) throw error;
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
