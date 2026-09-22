<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    title?: string;
    children: Snippet;
    actions?: Snippet;
  }

  let { title, children, actions }: Props = $props();
</script>

<div class="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/80 transition-shadow hover:shadow-md">
  <div class="mb-4 flex items-center justify-between">
    {#if title}<h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>{/if}
    {#if actions}{@render actions()}{/if}
  </div>
  {@render children()}
</div>
