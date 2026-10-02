<script lang="ts">
  import type { PracticeSession, FeedbackTarget } from '$lib/stores/practice.svelte';
  import Button from './Button.svelte';

  let { session, index, target = 'question' }: { session: PracticeSession; index: number; target?: FeedbackTarget } = $props();
  const saved = $derived(session.rating(index, target));
  let reason = $state('');
  $effect(() => { reason = saved?.reason ?? ''; });
</script>

<div class="flex flex-col gap-2 text-xs">
  <div class="flex flex-wrap items-center gap-2" role="group" aria-label={`Rate ${target === 'question' ? 'question' : target === 'hint' ? 'hint' : 'explanation'} ${index + 1}`}>
    <span class="text-muted">{target === 'question' ? 'Question' : target === 'hint' ? 'Hint' : 'Explanation'}:</span>
    {#each ['good', 'bad'] as value}
      <button type="button" aria-pressed={saved?.rating === value} disabled={!session.ready || session.ratingBusy}
        onclick={() => session.rate(index, target, saved?.rating === value ? null : value as 'good' | 'bad', reason)}
        class={`rounded-full border px-3 py-1.5 disabled:opacity-40 ${saved?.rating === value ? 'border-accent bg-accent-soft text-accent-text' : 'border-line text-muted hover:text-fg'}`}>
        {value === 'good' ? 'Good content' : 'Bad content'}
      </button>
    {/each}
    {#if saved}<span class="text-muted" role="status">Feedback saved</span>{/if}
  </div>
  {#if saved}
    <details>
      <summary class="cursor-pointer text-muted">Add a reason (optional)</summary>
      <div class="mt-2 flex flex-col gap-2">
        <textarea aria-label={`Reason for ${target} feedback on question ${index + 1}`} bind:value={reason} maxlength="500" rows="2" placeholder="What worked, or what needs improving?" class="rounded-lg border border-line bg-surface p-2 text-fg"></textarea>
        <Button variant="secondary" size="sm" disabled={session.ratingBusy} onclick={() => session.rate(index, target, saved!.rating, reason)}>Save reason</Button>
      </div>
    </details>
  {/if}
</div>
