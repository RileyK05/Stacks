<script lang="ts">
  import { onMount } from 'svelte';
  import type { SlidesSession } from '$lib/stores/workspace.svelte';
  import Button from './Button.svelte';
  import Icon from './Icon.svelte';
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

  const modes: [typeof mode, string][] = [
    ['view', 'Slides'],
    ['edit', 'Edit source']
  ];
</script>

<div class="flex flex-col gap-4">
  <div class="flex items-center gap-2">
    <div class="inline-flex rounded-lg bg-surface-2 p-0.5 ring-1 ring-line">
      {#each modes as [value, label] (value)}
        <button
          type="button"
          onclick={() => (mode = value)}
          class={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
            mode === value ? 'bg-surface text-fg shadow-card' : 'text-muted hover:text-fg'
          }`}
        >
          {label}
        </button>
      {/each}
    </div>
    {#if mode === 'edit' && session.edited}
      <Button variant="ghost" size="sm" onclick={() => session.revert()}>
        <Icon name="rotate-ccw" class="h-3.5 w-3.5" /> Revert
      </Button>
    {/if}
    <span class="ml-auto font-mono text-xs tabular-nums text-subtle">
      {total === 0 ? 0 : clamped + 1} / {total}
    </span>
  </div>

  {#if mode === 'edit'}
    <textarea
      bind:value={session.draft}
      rows={16}
      spellcheck={false}
      aria-label="Slide deck markdown"
      class="w-full resize-y rounded-xl border border-line-strong bg-surface p-4 font-mono text-[13px] leading-relaxed text-fg transition-[border-color,box-shadow] focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent/15"
    ></textarea>
    <p class="text-xs text-subtle">
      Markdown; a line with just --- starts a new slide. Edits stay in this browser session.
    </p>
  {:else if total > 0}
    <div
      class="flex aspect-[4/3] max-h-[28rem] flex-col justify-center overflow-y-auto rounded-xl border border-line bg-bg/40 p-8 shadow-card sm:p-10"
    >
      <RichText text={slides[clamped]} class="[&>*:first-child]:mt-0" />
    </div>
    <div class="flex items-center justify-between gap-3">
      <Button variant="secondary" size="sm" onclick={() => step(-1)} disabled={total < 2} aria-label="Previous slide">
        <Icon name="chevron-left" class="h-4 w-4" /> Prev
      </Button>
      <div class="flex items-center gap-1.5" aria-hidden="true">
        {#each slides as _, slideIndex (slideIndex)}
          <span
            class={`h-1.5 rounded-full transition-all ${slideIndex === clamped ? 'w-4 bg-accent' : 'w-1.5 bg-line-strong'}`}
          ></span>
        {/each}
      </div>
      <Button variant="secondary" size="sm" onclick={() => step(1)} disabled={total < 2} aria-label="Next slide">
        Next <Icon name="chevron-right" class="h-4 w-4" />
      </Button>
    </div>
  {/if}

  <SourceChips cited={session.item.sources} {sources} />
</div>
