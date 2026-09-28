<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    /** Left pane snippet. */
    left: Snippet;
    /** Right pane snippet. */
    right: Snippet;
    /** Right pane width in px (bindable; persisted by the caller). */
    width?: number;
    min?: number;
    max?: number;
    /** Hide the right pane entirely. */
    collapsed?: boolean;
    /** Below this width the panes stack and the divider disappears. */
    stackBelow?: number;
  }

  let {
    left,
    right,
    width = $bindable(420),
    min = 280,
    max = 960,
    collapsed = false,
    stackBelow = 1024
  }: Props = $props();

  let stacked = $state(false);
  let dragging = $state(false);
  let container = $state<HTMLElement | null>(null);

  $effect(() => {
    if (!container) return;
    const observer = new ResizeObserver(([entry]) => {
      stacked = entry.contentRect.width < stackBelow;
    });
    observer.observe(container);
    return () => observer.disconnect();
  });

  function onPointerDown(event: PointerEvent) {
    if (stacked) return;
    dragging = true;
    (event.target as Element).setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function onPointerMove(event: PointerEvent) {
    if (!dragging || !container) return;
    const rect = container.getBoundingClientRect();
    const next = rect.right - event.clientX;
    width = Math.min(max, Math.max(min, Math.round(next)));
  }

  function onPointerUp(event: PointerEvent) {
    if (!dragging) return;
    dragging = false;
    (event.target as Element).releasePointerCapture?.(event.pointerId);
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === 'ArrowLeft') width = Math.min(max, width + 24);
    else if (event.key === 'ArrowRight') width = Math.max(min, width - 24);
    else return;
    event.preventDefault();
  }
</script>

{#if stacked}
  <div bind:this={container} class="flex flex-col gap-6">
    {@render left()}
    {#if !collapsed}{@render right()}{/if}
  </div>
{:else}
  <div bind:this={container} class="flex min-h-0 items-stretch gap-0">
    <div class="min-w-0 flex-1">{@render left()}</div>
    {#if !collapsed}
      <button
        type="button"
        aria-label="Resize panel"
        onpointerdown={onPointerDown}
        onpointermove={onPointerMove}
        onpointerup={onPointerUp}
        onpointercancel={onPointerUp}
        onkeydown={onKeydown}
        class={`group relative mx-1 w-2 shrink-0 cursor-col-resize touch-none rounded-full ${dragging ? 'bg-accent/40' : ''}`}
      >
        <span
          class={`absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors ${
            dragging ? 'bg-accent' : 'bg-line group-hover:bg-accent-line'
          }`}
        ></span>
      </button>
      <div
        class="min-w-0 scroll-mt-20"
        style={`width:${width}px; flex: 0 0 ${width}px`}
      >
        {@render right()}
      </div>
    {/if}
  </div>
{/if}
