<script lang="ts">
  import type { HTMLButtonAttributes } from 'svelte/elements';
  import type { Snippet } from 'svelte';
  import Spinner from './Spinner.svelte';

  interface Props extends HTMLButtonAttributes {
    variant?: 'primary' | 'secondary' | 'danger';
    loading?: boolean;
    children: Snippet;
  }

  let {
    variant = 'primary',
    loading = false,
    children,
    class: className = '',
    disabled,
    ...rest
  }: Props = $props();

  const styles = {
    primary: 'bg-indigo-600 text-white hover:bg-indigo-500 disabled:bg-indigo-300',
    secondary: 'bg-white text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50',
    danger: 'bg-red-600 text-white hover:bg-red-500 disabled:bg-red-300'
  };
</script>

<button
  {...rest}
  disabled={disabled || loading}
  class={`inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium disabled:cursor-not-allowed ${styles[variant]} ${className}`}
>
  {#if loading}<Spinner />{/if}
  {@render children()}
</button>
