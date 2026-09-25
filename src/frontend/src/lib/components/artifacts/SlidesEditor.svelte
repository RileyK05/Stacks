<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import RichText from '$lib/components/RichText.svelte';
  import type { SlidesContent } from '$lib/stores/artifact.svelte';

  interface Props {
    deck: SlidesContent;
    title: string;
    editable?: boolean;
    current?: number;
    onchange: () => void;
  }

  let { deck, title, editable = true, current = $bindable(0), onchange }: Props = $props();

  let presenting = $state(false);
  let presentIndex = $state(0);

  const slide = $derived(deck.slides[Math.min(current, deck.slides.length - 1)]);

  function add() {
    deck.slides.splice(current + 1, 0, { title: '', body: '', notes: '' });
    current += 1;
    onchange();
  }

  function remove(index: number) {
    if (deck.slides.length === 1) return;
    deck.slides.splice(index, 1);
    current = Math.min(current, deck.slides.length - 1);
    onchange();
  }

  function move(index: number, by: number) {
    const target = index + by;
    if (target < 0 || target >= deck.slides.length) return;
    const [moved] = deck.slides.splice(index, 1);
    deck.slides.splice(target, 0, moved);
    current = target;
    onchange();
  }

  function present() {
    presentIndex = current;
    presenting = true;
    void document.documentElement.requestFullscreen?.().catch(() => {});
  }

  function stopPresenting() {
    presenting = false;
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
  }

  function onPresentKey(event: KeyboardEvent) {
    if (!presenting) return;
    if (['ArrowRight', 'ArrowDown', ' ', 'PageDown'].includes(event.key)) {
      event.preventDefault();
      presentIndex = Math.min(presentIndex + 1, deck.slides.length - 1);
    } else if (['ArrowLeft', 'ArrowUp', 'PageUp'].includes(event.key)) {
      event.preventDefault();
      presentIndex = Math.max(presentIndex - 1, 0);
    } else if (event.key === 'Escape') {
      stopPresenting();
    }
  }
</script>

<svelte:window onkeydown={onPresentKey} />

<div class="grid gap-4 lg:grid-cols-[200px_minmax(0,1fr)]">
  <ol class="flex gap-2 overflow-x-auto pb-1 lg:max-h-[70vh] lg:flex-col lg:overflow-y-auto lg:pb-0">
    {#each deck.slides as item, index (index)}
      <li class="shrink-0 lg:shrink">
        <button
          type="button"
          onclick={() => (current = index)}
          class={`group flex aspect-video w-40 flex-col rounded-lg border p-2 text-left transition-all lg:w-full ${
            index === current ? 'border-accent bg-accent-soft/60 shadow-card' : 'border-line bg-surface hover:border-line-strong'
          }`}
        >
          <span class="text-[10px] font-semibold text-subtle">{index + 1}</span>
          <span class="mt-0.5 line-clamp-2 text-[11px] font-semibold text-fg">{item.title || 'Untitled slide'}</span>
          <span class="mt-0.5 line-clamp-2 text-[10px] text-muted">{item.body}</span>
        </button>
      </li>
    {/each}
    {#if editable}
      <li class="shrink-0 lg:shrink">
        <button type="button" onclick={add} class="flex aspect-video w-40 items-center justify-center gap-1.5 rounded-lg border border-dashed border-line-strong text-[12px] font-medium text-muted hover:border-accent-line hover:text-fg lg:w-full">
          <Icon name="plus" class="h-3.5 w-3.5" /> Slide
        </button>
      </li>
    {/if}
  </ol>

  {#if slide}
    <div class="flex min-w-0 flex-col gap-3">
      <div class="flex flex-wrap items-center gap-1">
        <span class="text-xs text-subtle">Slide {current + 1} of {deck.slides.length}</span>
        <div class="ml-auto flex items-center gap-1">
          {#if editable}
            <button type="button" onclick={() => move(current, -1)} disabled={current === 0} title="Move up" class="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-40">
              <Icon name="chevron-left" class="h-4 w-4 rotate-90" />
            </button>
            <button type="button" onclick={() => move(current, 1)} disabled={current === deck.slides.length - 1} title="Move down" class="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-40">
              <Icon name="chevron-right" class="h-4 w-4 rotate-90" />
            </button>
            <button type="button" onclick={() => remove(current)} disabled={deck.slides.length === 1} title="Delete slide" class="rounded-md p-1.5 text-muted hover:bg-danger-soft hover:text-danger-text disabled:opacity-40">
              <Icon name="trash" class="h-4 w-4" />
            </button>
          {/if}
          <button type="button" onclick={present} class="ml-1 inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-[13px] font-medium text-on-accent shadow-card hover:bg-accent-hover">
            <Icon name="presentation" class="h-3.5 w-3.5" /> Present
          </button>
        </div>
      </div>

      <div class="grid gap-3 xl:grid-cols-2">
        <div class="flex flex-col gap-2">
          <input
            bind:value={slide.title}
            oninput={onchange}
            readonly={!editable}
            placeholder="Slide title"
            aria-label="Slide title"
            class="h-11 rounded-lg border border-line-strong bg-surface px-3 font-display text-lg text-fg placeholder:text-subtle focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent/15"
          />
          <textarea
            bind:value={slide.body}
            oninput={onchange}
            readonly={!editable}
            rows="10"
            placeholder={'- A point\n- Another point'}
            aria-label="Slide body (Markdown)"
            class="rounded-lg border border-line-strong bg-surface px-3 py-2 font-mono text-[13px] leading-relaxed text-fg placeholder:text-subtle focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent/15"
          ></textarea>
          <textarea
            bind:value={slide.notes}
            oninput={onchange}
            readonly={!editable}
            rows="3"
            placeholder="Speaker notes"
            aria-label="Speaker notes"
            class="rounded-lg border border-line bg-surface-2/60 px-3 py-2 text-[13px] text-fg-soft placeholder:text-subtle focus:border-accent focus:outline-none"
          ></textarea>
        </div>
        <div class="flex aspect-video flex-col overflow-hidden rounded-xl border border-line bg-surface p-6 shadow-card">
          <h3 class="font-display text-2xl font-medium tracking-tight text-fg">{slide.title || 'Untitled slide'}</h3>
          <RichText text={slide.body} class="mt-3 text-[15px]" />
        </div>
      </div>
    </div>
  {/if}
</div>

{#if presenting}
  {@const shown = deck.slides[presentIndex]}
  <div class="fixed inset-0 z-[100] flex flex-col bg-bg" role="dialog" aria-label={`Presenting ${title}`}>
    <div class="flex flex-1 flex-col justify-center px-[8vw] py-[6vh]">
      <h2 class="font-display text-[clamp(2rem,5vw,4rem)] font-medium leading-tight tracking-tight text-fg">
        {shown.title}
      </h2>
      <RichText text={shown.body} class="mt-8 max-w-none text-[clamp(1.1rem,2.2vw,1.8rem)] prose-li:my-2" />
    </div>
    <div class="flex items-center justify-between border-t border-line px-6 py-3 text-sm text-subtle">
      <span>{title}</span>
      <span>{presentIndex + 1} / {deck.slides.length} · ← → to move · Esc to exit</span>
      <button type="button" onclick={stopPresenting} class="rounded-lg px-2 py-1 hover:bg-surface-2 hover:text-fg">Exit</button>
    </div>
  </div>
{/if}
