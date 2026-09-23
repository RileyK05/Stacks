<script lang="ts">
  import type { QuizSession } from '$lib/stores/workspace.svelte';
  import Button from './Button.svelte';
  import SourceChips, { type SourceRef } from './SourceChips.svelte';

  interface Props {
    session: QuizSession;
    sources: SourceRef[];
    onfollowup: (question: string) => void;
  }

  let { session, sources, onfollowup }: Props = $props();

  const questions = $derived(session.quiz.questions);
  const followUp = $derived(session.submitted ? session.missedFollowUp() : null);

  function optionClass(questionIndex: number, optionIndex: number): string {
    const base = 'w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors';
    const picked = session.responses[questionIndex] === optionIndex;
    if (!session.submitted) {
      return picked
        ? `${base} cursor-pointer border-indigo-500 bg-indigo-50 text-slate-900 dark:bg-indigo-950/50 dark:text-slate-100`
        : `${base} cursor-pointer border-slate-200 bg-white text-slate-700 hover:border-indigo-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-indigo-600`;
    }
    if (optionIndex === questions[questionIndex].answer) {
      return `${base} border-emerald-500 bg-emerald-50 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200`;
    }
    if (picked) {
      return `${base} border-red-400 bg-red-50 text-red-900 dark:bg-red-950/40 dark:text-red-200`;
    }
    return `${base} border-slate-200 bg-white text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-500`;
  }
</script>

<div class="flex flex-col gap-5">
  {#each questions as question, questionIndex (questionIndex)}
    <fieldset class="flex flex-col gap-2">
      <legend class="mb-1 text-sm font-medium text-slate-900 dark:text-slate-100">
        {questionIndex + 1}. {question.prompt}
      </legend>
      {#each question.options as option, optionIndex (optionIndex)}
        <button
          type="button"
          onclick={() => session.choose(questionIndex, optionIndex)}
          disabled={session.submitted}
          aria-pressed={session.responses[questionIndex] === optionIndex}
          class={optionClass(questionIndex, optionIndex)}
        >
          <span class="mr-2 font-mono text-xs text-slate-400">{String.fromCharCode(65 + optionIndex)}.</span>
          {option}
        </button>
      {/each}
      {#if session.submitted}
        {#if question.explanation}
          <p class="mt-1 rounded-md bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600 ring-1 ring-slate-200 dark:bg-slate-800/60 dark:text-slate-300 dark:ring-slate-700">
            {question.explanation}
          </p>
        {/if}
        <SourceChips cited={question.sources} {sources} />
      {/if}
    </fieldset>
  {/each}

  <div class="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-3 dark:border-slate-700">
    {#if session.submitted}
      <p class="text-sm font-medium text-slate-900 dark:text-slate-100">
        Score: {session.score}/{questions.length}
        {session.score === questions.length ? '· perfect!' : ''}
      </p>
      <div class="flex gap-2">
        {#if followUp}
          <Button variant="secondary" onclick={() => onfollowup(followUp)}>
            Ask about what I missed
          </Button>
        {/if}
        <Button variant="secondary" onclick={() => session.reset()}>Try again</Button>
      </div>
    {:else}
      <p class="text-xs text-slate-400">
        {session.responses.filter((response) => response !== null).length}/{questions.length} answered
      </p>
      <Button onclick={() => session.submit()} disabled={!session.answeredAll}>Submit answers</Button>
    {/if}
  </div>
</div>
