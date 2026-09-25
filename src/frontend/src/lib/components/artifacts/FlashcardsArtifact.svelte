<script lang="ts">
  import Button from '$lib/components/Button.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import RichText from '$lib/components/RichText.svelte';
  import type { FlashcardsContent } from '$lib/stores/artifact.svelte';

  interface Props {
    deck: FlashcardsContent;
    editable?: boolean;
    onchange: () => void;
    oncite?: (n: number) => void;
  }

  let { deck, editable = true, onchange, oncite }: Props = $props();

  let mode = $state<'study' | 'edit'>('study');
  let order = $state<number[]>([]);
  let position = $state(0);
  let flipped = $state(false);
  let again = $state<Set<number>>(new Set());

  $effect(() => {
    if (order.length !== deck.cards.length) {
      order = deck.cards.map((_, i) => i);
      position = Math.min(position, Math.max(deck.cards.length - 1, 0));
    }
  });

  const card = $derived(deck.cards[order[position] ?? 0]);

  function next(knewIt: boolean) {
    const index = order[position];
    const updated = new Set(again);
    if (knewIt) updated.delete(index);
    else updated.add(index);
    again = updated;
    flipped = false;
    position = (position + 1) % Math.max(order.length, 1);
  }

  function shuffle() {
    order = [...order].sort(() => Math.random() - 0.5);
    position = 0;
    flipped = false;
  }

  function onKey(event: KeyboardEvent) {
    if (mode !== 'study' || (event.target as HTMLElement).closest('input, textarea')) return;
    if (event.key === ' ') {
      event.preventDefault();
      flipped = !flipped;
    } else if (event.key === 'ArrowRight') next(true);
    else if (event.key === 'ArrowLeft') next(false);
  }

  function addCard() {
    deck.cards.push({ front: 'Term or question', back: 'Definition or answer', sources: [] });
    onchange();
  }

  function removeCard(index: number) {
    deck.cards.splice(index, 1);
    onchange();
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="flex flex-col gap-4">
  <div class="flex flex-wrap items-center gap-2">
    <div class="flex items-center gap-1 rounded-lg border border-line bg-surface p-0.5 shadow-card">
      {#each [['study', 'Study'], ['edit', 'Edit cards']] as [value, label] (value)}
        <button
          type="button"
          onclick={() => (mode = value as 'study' | 'edit')}
          disabled={value === 'edit' && !editable}
          class={`rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${mode === value ? 'bg-accent-soft text-accent-text' : 'text-muted hover:text-fg'}`}
        >
          {label}
        </button>
      {/each}
    </div>
    {#if mode === 'study' && deck.cards.length > 1}
      <Button variant="ghost" size="sm" onclick={shuffle}><Icon name="refresh" class="h-3.5 w-3.5" /> Shuffle</Button>
      <span class="ml-auto text-xs text-subtle">{again.size} to review again</span>
    {/if}
  </div>

  {#if deck.cards.length === 0}
    <p class="rounded-xl border border-dashed border-line-strong p-6 text-center text-sm text-muted">
      No cards yet. Ask Stacks to make some from your course, or add your own.
    </p>
  {:else if mode === 'study' && card}
    <button
      type="button"
      onclick={() => (flipped = !flipped)}
      class="relative mx-auto flex aspect-[3/2] w-full max-w-xl flex-col items-center justify-center rounded-2xl border border-line bg-surface p-8 text-center shadow-lift transition-transform hover:-translate-y-0.5"
      aria-label={flipped ? 'Show the front' : 'Show the back'}
    >
      <span class="absolute left-4 top-3 text-[11px] font-semibold uppercase tracking-wider text-subtle">
        {flipped ? 'Back' : 'Front'} · {position + 1}/{order.length}
      </span>
      <RichText text={flipped ? card.back : card.front} class={flipped ? 'text-[16px]' : 'font-display text-2xl text-fg'} />
      {#if flipped && card.sources.length > 0}
        <span class="mt-3 flex gap-1">
          {#each card.sources as n (n)}
            <span role="link" tabindex="0" onclick={(e) => { e.stopPropagation(); oncite?.(n); }} onkeydown={(e) => e.key === 'Enter' && oncite?.(n)} class="rounded-md bg-accent-soft px-1.5 font-mono text-[11px] font-semibold text-accent-text">[{n}]</span>
          {/each}
        </span>
      {/if}
    </button>
    <div class="flex items-center justify-center gap-2">
      <Button variant="secondary" onclick={() => next(false)}>Again <kbd class="ml-1 text-[10px] text-subtle">←</kbd></Button>
      <Button variant="ghost" onclick={() => (flipped = !flipped)}>Flip <kbd class="ml-1 text-[10px] text-subtle">Space</kbd></Button>
      <Button onclick={() => next(true)}>Got it <kbd class="ml-1 text-[10px] opacity-70">→</kbd></Button>
    </div>
  {:else}
    <div class="flex flex-col gap-2">
      {#each deck.cards as item, index (index)}
        <div class="grid gap-2 rounded-xl border border-line bg-surface p-3 shadow-card sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <textarea bind:value={item.front} oninput={onchange} rows="2" aria-label="Front" class="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[13px] font-medium text-fg focus:border-accent focus:outline-none"></textarea>
          <textarea bind:value={item.back} oninput={onchange} rows="2" aria-label="Back" class="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[13px] text-fg-soft focus:border-accent focus:outline-none"></textarea>
          <button type="button" onclick={() => removeCard(index)} class="self-start rounded-md p-1.5 text-subtle hover:bg-danger-soft hover:text-danger-text" title="Delete card">
            <Icon name="trash" class="h-4 w-4" />
          </button>
        </div>
      {/each}
    </div>
  {/if}
  {#if mode === 'edit'}
    <Button variant="secondary" onclick={addCard} class="self-start"><Icon name="plus" class="h-4 w-4" /> Add card</Button>
  {/if}
</div>
