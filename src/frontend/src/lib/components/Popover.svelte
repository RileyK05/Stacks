<script lang="ts">
  import { untrack, type Snippet } from 'svelte';

  interface TriggerProps {
    onclick: () => void;
    'aria-expanded': boolean;
    'aria-haspopup': 'dialog';
  }

  interface Props {
    open?: boolean;
    align?: 'start' | 'end';
    /** Tailwind width class for the panel. */
    width?: string;
    label: string;
    trigger: Snippet<[TriggerProps]>;
    children: Snippet<[() => void]>;
  }

  let {
    open = $bindable(false),
    align = 'start',
    width = 'w-72',
    label,
    trigger,
    children
  }: Props = $props();

  let root = $state<HTMLElement | null>(null);
  let panel = $state<HTMLElement | null>(null);
  /** Nudge that keeps the panel on screen when its trigger sits near an edge
   * (a toolbar that wrapped onto its own line on a narrow window). */
  let shift = $state(0);

  $effect(() => {
    if (!open || !panel) {
      shift = 0;
      return;
    }
    const rect = panel.getBoundingClientRect();
    const base = untrack(() => shift);
    const left = rect.left - base;
    const right = rect.right - base;
    const margin = 8;
    const width = document.documentElement.clientWidth;
    shift = left < margin ? margin - left : right > width - margin ? width - margin - right : 0;
  });

  function close() {
    open = false;
  }

  $effect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (root && !root.contains(event.target as Node)) close();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  });
</script>

<div bind:this={root} class="relative">
  {@render trigger({
    onclick: () => (open = !open),
    'aria-expanded': open,
    'aria-haspopup': 'dialog'
  })}
  {#if open}
    <div
      bind:this={panel}
      role="dialog"
      aria-label={label}
      style:translate={shift ? `${shift}px 0` : undefined}
      class={`absolute max-w-[calc(100vw-1rem)] top-full z-40 mt-2 origin-top animate-rise overflow-hidden rounded-xl border border-line bg-surface shadow-lift ${width} ${
        align === 'end' ? 'right-0' : 'left-0'
      }`}
    >
      {@render children(close)}
    </div>
  {/if}
</div>
