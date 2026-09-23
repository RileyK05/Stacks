<script lang="ts">
  import type { HTMLInputAttributes } from 'svelte/elements';

  interface Props extends HTMLInputAttributes {
    label?: string;
    error?: string | null;
  }

  let {
    label,
    error = null,
    class: className = '',
    value = $bindable(''),
    id,
    ...rest
  }: Props = $props();

  let inputId = $derived(id ?? label?.toLowerCase().replace(/\s+/g, '-'));
</script>

<div class="flex flex-col gap-1">
  {#if label}
    <label for={inputId} class="text-sm font-medium text-slate-700 dark:text-slate-200">{label}</label>
  {/if}
  <input
    {...rest}
    id={inputId}
    bind:value
    class={`rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-900 dark:placeholder:text-slate-500 ${className}`}
  />
  {#if error}<p class="text-sm text-red-600 dark:text-red-400">{error}</p>{/if}
</div>
