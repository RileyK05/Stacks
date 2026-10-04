<script lang="ts">
  import { untrack } from 'svelte';
  import { page } from '$app/state';
  import type { QuizSession } from '$lib/stores/workspace.svelte';
  import Button from './Button.svelte';
  import Icon from './Icon.svelte';
  import SourceChips, { type SourceRef } from './SourceChips.svelte';
  import QuizFeedback from './QuizFeedback.svelte';

  interface Props {
    session: QuizSession;
    sources: (SourceRef | null)[];
    onfollowup?: (question: string) => void;
    courseId?: string;
  }

  let { session, sources, onfollowup, courseId = page.params.id ?? '' }: Props = $props();
  $effect(() => {
    const current = session;
    const course = courseId;
    untrack(() => { void current.connect(course); });
  });

  const questions = $derived(session.questions);
  const followUp = $derived(session.submitted ? session.missedFollowUp() : null);
  const answered = $derived(session.responses.filter((response) => response !== null).length);
  const assessed = $derived(session.run?.results.filter((result) => result !== null).length ?? questions.length);
  const perfect = $derived(session.submitted && assessed > 0 && session.score === assessed);

  type OptionState = 'idle' | 'picked' | 'correct' | 'wrong' | 'dim';

  function optionState(questionIndex: number, optionIndex: number): OptionState {
    const picked = session.responses[questionIndex] === optionIndex;
    if (!session.submitted) return picked ? 'picked' : 'idle';
    if (session.correctAnswer(questionIndex) === null) return 'dim';
    if (optionIndex === session.correctAnswer(questionIndex)) return 'correct';
    return picked ? 'wrong' : 'dim';
  }

  const optionStyles: Record<OptionState, string> = {
    idle: 'cursor-pointer border-line bg-surface text-fg-soft hover:border-accent-line hover:bg-surface-2/60',
    picked: 'cursor-pointer border-accent bg-accent-soft text-fg ring-1 ring-accent',
    correct: 'border-success/50 bg-success-soft text-fg',
    wrong: 'border-danger/50 bg-danger-soft text-fg',
    dim: 'border-line bg-surface text-subtle'
  };

  const letterStyles: Record<OptionState, string> = {
    idle: 'bg-surface-2 text-muted ring-1 ring-line',
    picked: 'bg-accent text-on-accent',
    correct: 'bg-success text-on-accent',
    wrong: 'bg-danger text-on-accent',
    dim: 'bg-surface-2 text-subtle ring-1 ring-line'
  };
</script>

<div class="flex flex-col gap-7">
  {#if session.error}
    <div class="rounded-lg border border-danger/40 p-3 text-sm text-danger-text" role="alert">
      <p>{session.error}</p>
      {#if !session.ready}<Button variant="secondary" onclick={() => session.connect(courseId)}>Retry loading</Button>{/if}
    </div>
  {/if}
  {#if session.loading}<p class="text-sm text-muted">Loading practice history…</p>{/if}
  {#if session.ratingError}<p class="text-sm text-danger-text" role="alert">{session.ratingError}</p>{/if}
  {#if session.submitted}
    <div
      class={`flex items-center gap-4 rounded-xl border p-4 ${
        perfect ? 'border-success/40 bg-success-soft' : 'border-line bg-surface-2/60'
      }`}
    >
      <p class="font-display text-3xl font-medium tabular-nums text-fg">
        {session.score}<span class="text-lg text-subtle">/{assessed}</span>
      </p>
      <div class="min-w-0">
        <p class="text-sm font-semibold text-fg">
          {perfect ? 'Perfect score!' : session.score === 0 ? 'Worth another look' : 'Nice work — a few to review'}
        </p>
        <p class="text-[13px] text-muted">
          Saved test session. {questions.length - assessed > 0 ? `${questions.length - assessed} flagged question(s) excluded.` : 'Answers are checked against the current key.'}
          {#if session.run?.helped.some(Boolean)}
            {session.run.helped.filter(Boolean).length} assisted answer(s); these do not count as independent practice.
          {/if}
        </p>
      </div>
    </div>
  {/if}

  {#each questions as question, questionIndex (questionIndex)}
    {@const help = session.assistance[questionIndex]}
    <fieldset class="flex min-w-0 flex-col gap-2">
      <legend class="mb-2 max-w-full">
        <span class="block text-[11px] font-semibold uppercase tracking-[0.1em] text-subtle">
          Question {questionIndex + 1} of {questions.length}
        </span>
        <span class="mt-1 block whitespace-pre-wrap text-[15px] font-medium leading-snug text-fg [overflow-wrap:anywhere]">{question.prompt}</span>
      </legend>
      {#each question.options as option, optionIndex (optionIndex)}
        {@const state = optionState(questionIndex, optionIndex)}
        <button
          type="button"
          onclick={() => session.choose(questionIndex, optionIndex)}
          disabled={session.submitted || session.saving || session.submissionPending || !session.ready}
          aria-pressed={session.responses[questionIndex] === optionIndex}
          class={`flex w-full items-start gap-3 rounded-xl border px-3 py-2.5 text-left text-sm transition-all ${optionStyles[state]}`}
        >
          <span
            class={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-xs font-semibold transition-colors ${letterStyles[state]}`}
          >
            {#if state === 'correct'}
              <Icon name="check" class="h-3.5 w-3.5" strokeWidth={3} />
            {:else if state === 'wrong'}
              <Icon name="x" class="h-3.5 w-3.5" strokeWidth={3} />
            {:else}
              {String.fromCharCode(65 + optionIndex)}
            {/if}
          </span>
          <span class="min-w-0 flex-1 whitespace-pre-wrap pt-0.5 leading-snug [overflow-wrap:anywhere]">{option}</span>
        </button>
      {/each}
      {#if session.submitted}
        {#if session.correctAnswer(questionIndex) === null}
          <p class="text-sm text-muted">This question is flagged and does not affect memory.</p>
        {/if}
        {#if question.explanation}
          <p class="mt-1 flex gap-2 rounded-lg bg-surface-2 px-3 py-2.5 text-[13px] leading-relaxed text-muted">
            <Icon name="info" class="mt-0.5 h-3.5 w-3.5 text-subtle" />
            <span class="min-w-0 whitespace-pre-wrap [overflow-wrap:anywhere]">{question.explanation}</span>
          </p>
        {/if}
        <SourceChips cited={question.sources ?? []} sources={session.evidence.length ? session.evidence : sources} />
        <button type="button" onclick={() => session.challenge(questionIndex)} disabled={session.saving || session.helping || session.correctAnswer(questionIndex) === null} class="self-start text-xs text-muted hover:underline disabled:opacity-40">Flag an incorrect or ambiguous question</button>
      {:else}
        <label class="flex gap-2 text-xs text-muted"><input type="checkbox" bind:checked={session.helped[questionIndex]} disabled={session.saving || session.submissionPending || !session.ready} /> I used help or notes</label>
      {/if}
      <Button variant="secondary" size="sm" class="self-start" onclick={() => session.requestHelp(questionIndex)} disabled={!session.ready || session.saving || session.submissionPending || session.helping || session.assistance[questionIndex]?.kind === (session.submitted ? 'explain' : 'hint')}>
        {session.helpIndex === questionIndex ? 'Preparing…' : session.submitted ? 'Explain' : 'Hint'}
      </Button>
      {#if session.supportErrors[questionIndex]}<p class="text-sm text-danger-text" role="alert">{session.supportErrors[questionIndex]}</p>{/if}
      {#if help && help.kind === (session.submitted ? 'explain' : 'hint')}
        <div class="flex flex-col gap-3 rounded-xl border border-line bg-surface-2 p-3">
          <p class="whitespace-pre-wrap text-sm leading-relaxed text-fg">{help.content.text}</p>
          {#if help.model}<p class="text-xs text-subtle">Prepared with {help.model}</p>{/if}
          {#if help.kind === 'hint'}<p class="text-xs text-muted">This answer will be recorded as assisted.</p>{/if}
          {#if help.fell_back_to_local}<p class="text-xs text-muted">Your provider was unavailable; the local model supplied this help.</p>{/if}
          <SourceChips cited={help.content.sources} sources={session.evidence} />
          {#each help.content.sources as number}
            <details class="text-xs text-muted"><summary class="cursor-pointer">Read passage [{number}] · {session.evidence[number - 1]?.label}</summary><p class="mt-2 whitespace-pre-wrap">{session.passages[number - 1] ?? 'This passage is no longer available.'}</p></details>
          {/each}
          <QuizFeedback {session} index={questionIndex} target={help.kind} />
        </div>
      {/if}
      <QuizFeedback {session} index={questionIndex} />
    </fieldset>
  {/each}

  <div class="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
    {#if session.submitted}
      <Button variant="ghost" onclick={() => session.reset()} disabled={session.saving || session.helping || session.ratingBusy}>
        <Icon name="rotate-ccw" class="h-4 w-4" /> Try again
      </Button>
      {#if followUp && onfollowup}
        <Button variant="soft" onclick={() => onfollowup(followUp)}>
          <Icon name="sparkles" class="h-4 w-4" /> Ask about what I missed
        </Button>
      {/if}
    {:else}
      <div class="flex min-w-0 flex-1 items-center gap-3">
        <div class="h-1.5 max-w-40 flex-1 overflow-hidden rounded-full bg-surface-3">
          <div
            class="h-full rounded-full bg-accent transition-[width] duration-300"
            style:width={`${(answered / Math.max(questions.length, 1)) * 100}%`}
          ></div>
        </div>
        <p class="whitespace-nowrap text-xs text-subtle">{answered}/{questions.length} answered</p>
      </div>
      <Button onclick={() => session.submit()} disabled={!session.answeredAll || !session.ready || session.saving || session.helping}>{session.saving ? 'Saving test…' : 'Submit answers'}</Button>
    {/if}
  </div>
  <p class="text-xs text-muted">Content feedback helps improve future quizzes. It does not change your scores. Flag a wrong or ambiguous question to exclude it from assessment.</p>
</div>
