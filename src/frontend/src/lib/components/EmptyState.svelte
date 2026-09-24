<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon, { type IconName } from './Icon.svelte';

  interface Props {
    title?: string;
    message: string;
    icon?: IconName;
    children?: Snippet;
  }

  let { title, message, icon, children }: Props = $props();
</script>

<div
  class="flex flex-col items-center rounded-2xl border border-dashed border-line-strong bg-surface/50 px-6 py-10 text-center"
>
  {#if icon}
    <span class="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-surface-2 text-muted ring-1 ring-line">
      <Icon name={icon} class="h-5 w-5" />
    </span>
  {/if}
  {#if title}<h2 class="text-[15px] font-semibold text-fg">{title}</h2>{/if}
  <p class={`max-w-sm text-sm text-muted ${title ? 'mt-1' : ''}`}>{message}</p>
  {#if children}<div class="mt-4">{@render children()}</div>{/if}
</div>
