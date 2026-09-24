<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    title: string;
    description?: string;
    eyebrow?: string;
    actions?: Snippet;
  }

  let { title, description, eyebrow, actions }: Props = $props();
</script>

<header class="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
  <div class="min-w-0">
    {#if eyebrow}
      <p class="mb-1.5 text-xs font-medium uppercase tracking-[0.12em] text-subtle">{eyebrow}</p>
    {/if}
    <h1 class="font-display text-[1.9rem] font-medium leading-tight tracking-tight text-fg sm:text-4xl">
      {title}
    </h1>
    {#if description}<p class="mt-2 max-w-2xl text-[15px] text-muted">{description}</p>{/if}
  </div>
  {#if actions}<div class="flex shrink-0 items-center gap-2">{@render actions()}</div>{/if}
</header>
