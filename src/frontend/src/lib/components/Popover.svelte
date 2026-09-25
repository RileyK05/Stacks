<script lang="ts">
  import type { Snippet } from 'svelte';

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
      role="dialog"
      aria-label={label}
      class={`absolute top-full z-40 mt-2 origin-top animate-rise overflow-hidden rounded-xl border border-line bg-surface shadow-lift ${width} ${
        align === 'end' ? 'right-0' : 'left-0'
      }`}
    >
      {@render children(close)}
    </div>
  {/if}
</div>
