<script lang="ts">
  import Button from '$lib/components/Button.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Quiz from '$lib/components/Quiz.svelte';
  import { QuizSession } from '$lib/stores/workspace.svelte';
  import { QuizSessionScope } from '$lib/stores/quizSessionScope';
  import type { PracticeContext } from '$lib/stores/practice.svelte';
  import type { QuizContent } from '$lib/stores/artifact.svelte';
  import { autoGrowTextarea } from '$lib/actions/autoGrowTextarea';

  interface Props {
    quiz: QuizContent;
    editable?: boolean;
    onchange: () => void;
    oncite?: (n: number) => void;
    practice?: PracticeContext;
  }

  let { quiz, editable = true, onchange, practice }: Props = $props();

  let mode = $state<'take' | 'edit'>('take');

  function sessionIdentity(): string {
    return JSON.stringify([practice?.artifactId, practice?.version, quiz.questions]);
  }

  function makeSession(): QuizSession {
    return new QuizSession({
      type: 'quiz', title: 'Practice test', questions: quiz.questions.map((q) => ({ ...q, topic: q.topic ?? '', capability: q.capability ?? 'recognition' })),
    }, practice ? { artifact_id: practice.artifactId, artifact_version: practice.version, item_index: 0 } : null);
  }

  const sessionScope = new QuizSessionScope(sessionIdentity(), makeSession);
  let session = $state.raw(sessionScope.forMode('take', sessionIdentity(), makeSession));

  $effect(() => {
    const nextIdentity = sessionIdentity();
    session = sessionScope.forMode(mode, nextIdentity, makeSession);
  });

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
    if (q.answer === option) q.answer = 0;
    else if (q.answer > option) q.answer -= 1;
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
    {#if practice?.ready && quiz.questions.length}
      <Quiz {session} sources={[]} courseId={practice.courseId} />
    {:else}
      <p class="text-sm text-muted">{practice ? 'Save your changes before taking this test.' : 'Open the saved quiz to take a recorded practice test.'}</p>
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
        {#if question.stem}
          <textarea bind:value={question.stem} oninput={onchange} rows="2" aria-label="Shared stem" class="rounded-lg border border-line bg-surface-2/60 px-3 py-2 text-[13px] text-fg-soft focus:border-accent focus:outline-none"></textarea>
        {/if}
        <textarea bind:value={question.prompt} oninput={onchange} rows="2" aria-label="Question" class="rounded-lg border border-line-strong bg-surface px-3 py-2 text-[14px] text-fg focus:border-accent focus:outline-none"></textarea>
        {#if question.format === 'short_answer'}
          <textarea bind:value={question.expected} oninput={onchange} rows="3" aria-label="Expected answer" placeholder="Expected answer, shown after the student submits" class="rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-fg focus:border-accent focus:outline-none"></textarea>
          <textarea
            value={(question.points ?? []).join('\n')}
            oninput={(event) => { question.points = event.currentTarget.value.split('\n'); onchange(); }}
            rows="3"
            aria-label="Required points"
            placeholder="One required point per line"
            class="rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-fg focus:border-accent focus:outline-none"
          ></textarea>
        {/if}
        {#each question.format === 'short_answer' ? [] : question.options as _, optionIndex (optionIndex)}
          <div class="flex items-center gap-2">
            <input type="radio" name={`answer-${index}`} checked={question.answer === optionIndex} onchange={() => { question.answer = optionIndex; onchange(); }} aria-label="Correct answer" />
            <textarea bind:value={question.options[optionIndex]} oninput={onchange} use:autoGrowTextarea={question.options[optionIndex]} rows="1" aria-label={`Option ${optionIndex + 1}`} class="block h-auto min-w-0 flex-1 resize-none overflow-hidden rounded-lg border border-line bg-surface px-2.5 py-2 text-[13px] text-fg [overflow-wrap:anywhere] focus:border-accent focus:outline-none"></textarea>
            <button type="button" onclick={() => removeOption(index, optionIndex)} disabled={question.options.length <= 2} class="rounded p-1 text-subtle hover:text-danger-text disabled:opacity-30" title="Remove option">
              <Icon name="x" class="h-3.5 w-3.5" />
            </button>
          </div>
        {/each}
        {#if question.format !== 'short_answer'}
          <button type="button" onclick={() => addOption(index)} disabled={question.options.length >= 8} class="self-start text-[13px] font-medium text-accent-text hover:underline disabled:opacity-40">+ Option</button>
        {/if}
        <textarea bind:value={question.explanation} oninput={onchange} rows="2" placeholder="Explanation shown after checking" aria-label="Explanation" class="rounded-lg border border-line bg-surface-2/60 px-3 py-2 text-[13px] text-fg-soft placeholder:text-subtle focus:border-accent focus:outline-none"></textarea>
      </section>
    {/each}
    <Button variant="secondary" onclick={addQuestion} class="self-start"><Icon name="plus" class="h-4 w-4" /> Add question</Button>
  {/if}
</div>
