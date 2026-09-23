<script lang="ts">
  import { onMount } from 'svelte';
  import type { SlidesSession } from '$lib/stores/workspace.svelte';
  import Button from './Button.svelte';
  import RichText from './RichText.svelte';
  import SourceChips, { type SourceRef } from './SourceChips.svelte';

  interface Props {
    session: SlidesSession;
    sources: SourceRef[];
  }

  let { session, sources }: Props = $props();

  let current = $state(0);
  let mode = $state<'view' | 'edit'>('view');

  const slides = $derived(
    session.draft
      .split(/^---\s*$/m)
      .map((slide) => slide.trim())
      .filter((slide) => slide !== '')
  );
  const total = $derived(slides.length);
  const clamped = $derived(Math.min(current, total - 1));

  function step(delta: number) {
    current = (clamped + delta + total) % total;
  }

  function onKeydown(event: KeyboardEvent) {
    if (mode !== 'view' || total < 2) return;
    if (event.key === 'ArrowRight') step(1);
    if (event.key === 'ArrowLeft') step(-1);
  }

  onMount(() => {
    window.addEventListener('keydown', onKeydown);
    return () => window.removeEventListener('keydown', onKeydown);
  });
</script>

<div class="flex flex-col gap-3">
  <div class="flex items-center gap-1 text-xs">
    <button
      type="button"
      onclick={() => (mode = 'view')}
      class={mode === 'view'
        ? 'rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-800 ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-100 dark:ring-slate-700'
        : 'rounded-md px-2 py-1 text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200'}
    >
      Slides
    </button>
    <button
      type="button"
      onclick={() => (mode = 'edit')}
      class={mode === 'edit'
        ? 'rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-800 ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-100 dark:ring-slate-700'
        : 'rounded-md px-2 py-1 text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200'}
    >
      Edit source
    </button>
    {#if mode === 'edit' && session.edited}
      <button
        type="button"
        onclick={() => session.revert()}
        class="ml-2 text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
      >
        Revert
      </button>
    {/if}
    <span class="ml-auto font-mono text-slate-400">
      {total === 0 ? 0 : clamped + 1} / {total}
    </span>
  </div>

  {#if mode === 'edit'}
    <textarea
      bind:value={session.draft}
      rows={16}
      spellcheck={false}
      aria-label="Slide deck markdown"
      class="w-full resize-y rounded-lg border border-slate-300 bg-white p-3 font-mono text-sm leading-relaxed text-slate-800 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
    ></textarea>
    <p class="text-xs text-slate-400">
      Markdown; a line with just --- starts a new slide. Edits stay in this browser session.
    </p>
  {:else if total > 0}
    <div
      class="flex min-h-64 flex-col justify-center rounded-lg border border-slate-200 bg-white p-8 dark:border-slate-700 dark:bg-slate-950/40"
    >
      <RichText text={slides[clamped]} class="[&>*:first-child]:mt-0" />
    </div>
    <div class="flex items-center justify-between">
      <Button variant="secondary" onclick={() => step(-1)} disabled={total < 2}>← Prev</Button>
      <span class="text-xs text-slate-400">use ← → keys</span>
      <Button variant="secondary" onclick={() => step(1)} disabled={total < 2}>Next →</Button>
    </div>
  {/if}

  <SourceChips cited={session.item.sources} {sources} />
</div>
