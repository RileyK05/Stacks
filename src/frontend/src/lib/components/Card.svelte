<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    title?: string;
    description?: string;
    children: Snippet;
    actions?: Snippet;
    class?: string;
  }

  let { title, description, children, actions, class: className = '' }: Props = $props();
</script>

<section class={`rounded-2xl border border-line bg-surface p-5 shadow-card sm:p-6 ${className}`}>
  {#if title || actions}
    <div class="mb-5 flex items-start justify-between gap-4">
      <div class="min-w-0">
        {#if title}<h2 class="text-[15px] font-semibold text-fg">{title}</h2>{/if}
        {#if description}<p class="mt-1 text-sm text-muted">{description}</p>{/if}
      </div>
      {#if actions}{@render actions()}{/if}
    </div>
  {/if}
  {@render children()}
</section>
