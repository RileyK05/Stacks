<script lang="ts">
  import type { QuizSession } from '$lib/stores/workspace.svelte';
  import Button from './Button.svelte';
  import Icon from './Icon.svelte';
  import SourceChips, { type SourceRef } from './SourceChips.svelte';

  interface Props {
    session: QuizSession;
    sources: SourceRef[];
    onfollowup: (question: string) => void;
  }

  let { session, sources, onfollowup }: Props = $props();

  const questions = $derived(session.quiz.questions);
  const followUp = $derived(session.submitted ? session.missedFollowUp() : null);
  const answered = $derived(session.responses.filter((response) => response !== null).length);
  const perfect = $derived(session.submitted && session.score === questions.length);

  type OptionState = 'idle' | 'picked' | 'correct' | 'wrong' | 'dim';

  function optionState(questionIndex: number, optionIndex: number): OptionState {
    const picked = session.responses[questionIndex] === optionIndex;
    if (!session.submitted) return picked ? 'picked' : 'idle';
    if (optionIndex === questions[questionIndex].answer) return 'correct';
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
  {#if session.submitted}
    <div
      class={`flex items-center gap-4 rounded-xl border p-4 ${
        perfect ? 'border-success/40 bg-success-soft' : 'border-line bg-surface-2/60'
      }`}
    >
      <p class="font-display text-3xl font-medium tabular-nums text-fg">
        {session.score}<span class="text-lg text-subtle">/{questions.length}</span>
      </p>
      <div class="min-w-0">
        <p class="text-sm font-semibold text-fg">
          {perfect ? 'Perfect score!' : session.score === 0 ? 'Worth another look' : 'Nice work — a few to review'}
        </p>
        <p class="text-[13px] text-muted">
          {perfect ? 'Every answer was correct.' : 'Correct answers are highlighted below with an explanation.'}
        </p>
      </div>
    </div>
  {/if}

  {#each questions as question, questionIndex (questionIndex)}
    <fieldset class="flex flex-col gap-2">
      <legend class="mb-2">
        <span class="block text-[11px] font-semibold uppercase tracking-[0.1em] text-subtle">
          Question {questionIndex + 1} of {questions.length}
        </span>
        <span class="mt-1 block text-[15px] font-medium leading-snug text-fg">{question.prompt}</span>
      </legend>
      {#each question.options as option, optionIndex (optionIndex)}
        {@const state = optionState(questionIndex, optionIndex)}
        <button
          type="button"
          onclick={() => session.choose(questionIndex, optionIndex)}
          disabled={session.submitted}
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
          <span class="pt-0.5 leading-snug">{option}</span>
        </button>
      {/each}
      {#if session.submitted}
        {#if question.explanation}
          <p class="mt-1 flex gap-2 rounded-lg bg-surface-2 px-3 py-2.5 text-[13px] leading-relaxed text-muted">
            <Icon name="info" class="mt-0.5 h-3.5 w-3.5 text-subtle" />
            <span>{question.explanation}</span>
          </p>
        {/if}
        <SourceChips cited={question.sources} {sources} />
      {/if}
    </fieldset>
  {/each}

  <div class="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
    {#if session.submitted}
      <Button variant="ghost" onclick={() => session.reset()}>
        <Icon name="rotate-ccw" class="h-4 w-4" /> Try again
      </Button>
      {#if followUp}
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
      <Button onclick={() => session.submit()} disabled={!session.answeredAll}>Submit answers</Button>
    {/if}
  </div>
</div>
