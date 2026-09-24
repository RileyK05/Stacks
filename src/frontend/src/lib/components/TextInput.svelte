<script lang="ts">
  import type { HTMLInputAttributes } from 'svelte/elements';

  interface Props extends HTMLInputAttributes {
    label?: string;
    hint?: string;
    error?: string | null;
  }

  let {
    label,
    hint,
    error = null,
    class: className = '',
    value = $bindable(''),
    id,
    ...rest
  }: Props = $props();

  let inputId = $derived(id ?? label?.toLowerCase().replace(/\s+/g, '-'));
</script>

<div class="flex flex-col gap-1.5">
  {#if label}
    <label for={inputId} class="text-[13px] font-medium text-fg-soft">{label}</label>
  {/if}
  <input
    {...rest}
    id={inputId}
    bind:value
    class={`h-10 rounded-lg border border-line-strong bg-surface px-3 text-sm text-fg shadow-card transition-[border-color,box-shadow] placeholder:text-subtle hover:border-subtle focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent/15 disabled:opacity-60 ${className}`}
  />
  {#if error}
    <p class="text-[13px] text-danger-text">{error}</p>
  {:else if hint}
    <p class="text-[13px] text-subtle">{hint}</p>
  {/if}
</div>
