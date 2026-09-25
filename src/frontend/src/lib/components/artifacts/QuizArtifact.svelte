<script lang="ts">
  import Button from '$lib/components/Button.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import RichText from '$lib/components/RichText.svelte';
  import type { QuizContent } from '$lib/stores/artifact.svelte';

  interface Props {
    quiz: QuizContent;
    editable?: boolean;
    onchange: () => void;
    oncite?: (n: number) => void;
  }

  let { quiz, editable = true, onchange, oncite }: Props = $props();

  let mode = $state<'take' | 'edit'>('take');
  let picks = $state<(number | null)[]>([]);
  let checked = $state(false);

  $effect(() => {
    if (picks.length !== quiz.questions.length) picks = quiz.questions.map(() => null);
  });

  const score = $derived(
    quiz.questions.filter((q, i) => picks[i] === q.answer).length
  );
  const answeredAll = $derived(picks.length > 0 && picks.every((p) => p !== null));

  function restart() {
    picks = quiz.questions.map(() => null);
    checked = false;
  }

  function addQuestion() {
    quiz.questions.push({ prompt: 'New question', options: ['Option A', 'Option B'], answer: 0, explanation: '', sources: [] });
    onchange();
  }

  function removeQuestion(index: number) {
    quiz.questions.splice(index, 1);
    onchange();
  }

  function addOption(index: number) {
    const q = quiz.questions[index];
    if (q.options.length >= 8) return;
    q.options.push(`Option ${'ABCDEFGH'[q.options.length]}`);
    onchange();
  }

  function removeOption(index: number, option: number) {
    const q = quiz.questions[index];
    if (q.options.length <= 2) return;
    q.options.splice(option, 1);
    if (q.answer >= q.options.length) q.answer = 0;
    onchange();
  }
</script>

<div class="flex flex-col gap-4">
  <div class="flex items-center gap-1 self-start rounded-lg border border-line bg-surface p-0.5 shadow-card">
    {#each [['take', 'Take quiz'], ['edit', 'Edit questions']] as [value, label] (value)}
      <button
        type="button"
        onclick={() => (mode = value as 'take' | 'edit')}
        disabled={value === 'edit' && !editable}
        class={`rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${
          mode === value ? 'bg-accent-soft text-accent-text' : 'text-muted hover:text-fg'
        }`}
      >
        {label}
      </button>
    {/each}
  </div>

  {#if quiz.questions.length === 0}
    <p class="rounded-xl border border-dashed border-line-strong p-6 text-center text-sm text-muted">
      No questions yet. Ask Stacks to write some from your course, or add your own.
    </p>
  {/if}

  {#if mode === 'take'}
    {#each quiz.questions as question, index (index)}
      <section class="rounded-2xl border border-line bg-surface p-5 shadow-card">
        <div class="flex items-start gap-3">
          <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-[13px] font-semibold text-accent-text">{index + 1}</span>
          <div class="min-w-0 flex-1">
            <RichText text={question.prompt} class="text-[15px] font-medium text-fg" />
            <div class="mt-3 flex flex-col gap-2">
              {#each question.options as option, optionIndex (optionIndex)}
                {@const picked = picks[index] === optionIndex}
                {@const correct = checked && optionIndex === question.answer}
                {@const wrong = checked && picked && optionIndex !== question.answer}
                <button
                  type="button"
                  disabled={checked}
                  onclick={() => (picks[index] = optionIndex)}
                  class={`flex items-center gap-3 rounded-xl border px-3.5 py-2.5 text-left text-[14px] transition-all ${
                    correct
                      ? 'border-success/50 bg-success-soft text-success-text'
                      : wrong
                        ? 'border-danger/40 bg-danger-soft text-danger-text'
                        : picked
                          ? 'border-accent bg-accent-soft text-fg'
                          : 'border-line bg-bg/40 text-fg-soft hover:border-line-strong'
                  }`}
                >
                  <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-current text-[11px] font-semibold">{'ABCDEFGH'[optionIndex]}</span>
                  <span class="min-w-0 flex-1">{option}</span>
                  {#if correct}<Icon name="check" class="h-4 w-4" />{/if}
                </button>
              {/each}
            </div>
            {#if checked && question.explanation}
              <div class="mt-3 rounded-xl bg-surface-2 px-3.5 py-2.5 text-[13px] text-muted">
                <RichText text={question.explanation} />
              </div>
            {/if}
            {#if question.sources.length > 0}
              <div class="mt-2 flex gap-1">
                {#each question.sources as n (n)}
                  <button type="button" onclick={() => oncite?.(n)} class="rounded-md bg-accent-soft px-1.5 font-mono text-[11px] font-semibold text-accent-text hover:underline">[{n}]</button>
                {/each}
              </div>
            {/if}
          </div>
        </div>
      </section>
    {/each}
    {#if quiz.questions.length > 0}
      <div class="flex items-center gap-3">
        {#if checked}
          <p class="font-display text-xl text-fg">{score} / {quiz.questions.length}</p>
          <Button variant="secondary" onclick={restart}><Icon name="rotate-ccw" class="h-4 w-4" /> Try again</Button>
        {:else}
          <Button onclick={() => (checked = true)} disabled={!answeredAll}>Check answers</Button>
          {#if !answeredAll}<span class="text-xs text-subtle">Answer every question first.</span>{/if}
        {/if}
      </div>
    {/if}
  {:else}
    {#each quiz.questions as question, index (index)}
      <section class="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-5 shadow-card">
        <div class="flex items-center gap-2">
          <span class="text-xs font-semibold uppercase tracking-wide text-subtle">Question {index + 1}</span>
          <button type="button" onclick={() => removeQuestion(index)} class="ml-auto rounded-md p-1 text-subtle hover:bg-danger-soft hover:text-danger-text" title="Delete question">
            <Icon name="trash" class="h-4 w-4" />
          </button>
        </div>
        <textarea bind:value={question.prompt} oninput={onchange} rows="2" aria-label="Question" class="rounded-lg border border-line-strong bg-surface px-3 py-2 text-[14px] text-fg focus:border-accent focus:outline-none"></textarea>
        {#each question.options as _, optionIndex (optionIndex)}
          <div class="flex items-center gap-2">
            <input type="radio" name={`answer-${index}`} checked={question.answer === optionIndex} onchange={() => { question.answer = optionIndex; onchange(); }} aria-label="Correct answer" />
            <input bind:value={question.options[optionIndex]} oninput={onchange} aria-label={`Option ${optionIndex + 1}`} class="h-9 min-w-0 flex-1 rounded-lg border border-line bg-surface px-2.5 text-[13px] text-fg focus:border-accent focus:outline-none" />
            <button type="button" onclick={() => removeOption(index, optionIndex)} disabled={question.options.length <= 2} class="rounded p-1 text-subtle hover:text-danger-text disabled:opacity-30" title="Remove option">
              <Icon name="x" class="h-3.5 w-3.5" />
            </button>
          </div>
        {/each}
        <button type="button" onclick={() => addOption(index)} disabled={question.options.length >= 8} class="self-start text-[13px] font-medium text-accent-text hover:underline disabled:opacity-40">+ Option</button>
        <textarea bind:value={question.explanation} oninput={onchange} rows="2" placeholder="Explanation shown after checking" aria-label="Explanation" class="rounded-lg border border-line bg-surface-2/60 px-3 py-2 text-[13px] text-fg-soft placeholder:text-subtle focus:border-accent focus:outline-none"></textarea>
      </section>
    {/each}
    <Button variant="secondary" onclick={addQuestion} class="self-start"><Icon name="plus" class="h-4 w-4" /> Add question</Button>
  {/if}
</div>
