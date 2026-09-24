<script lang="ts">
  import type { HTMLButtonAttributes } from 'svelte/elements';
  import type { Snippet } from 'svelte';
  import Spinner from './Spinner.svelte';

  interface Props extends HTMLButtonAttributes {
    variant?: 'primary' | 'secondary' | 'ghost' | 'soft' | 'danger';
    size?: 'sm' | 'md' | 'lg';
    loading?: boolean;
    children: Snippet;
  }

  let {
    variant = 'primary',
    size = 'md',
    loading = false,
    children,
    class: className = '',
    disabled,
    type = 'button',
    ...rest
  }: Props = $props();

  const styles = {
    primary:
      'bg-accent text-on-accent shadow-card hover:bg-accent-hover active:translate-y-px disabled:opacity-50',
    secondary:
      'bg-surface text-fg ring-1 ring-inset ring-line-strong shadow-card hover:bg-surface-2 active:translate-y-px disabled:opacity-50',
    ghost: 'text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-50',
    soft: 'bg-accent-soft text-accent-text hover:ring-1 hover:ring-inset hover:ring-accent-line disabled:opacity-50',
    danger:
      'bg-danger text-on-accent shadow-card hover:brightness-110 active:translate-y-px disabled:opacity-50'
  };

  const sizes = {
    sm: 'h-8 gap-1.5 rounded-lg px-2.5 text-[13px]',
    md: 'h-9 gap-2 rounded-lg px-3.5 text-sm',
    lg: 'h-11 gap-2 rounded-xl px-5 text-[15px]'
  };
</script>

<button
  {...rest}
  {type}
  disabled={disabled || loading}
  class={`inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap font-medium transition-[background-color,color,box-shadow,transform,filter] duration-150 disabled:cursor-not-allowed ${sizes[size]} ${styles[variant]} ${className}`}
>
  {#if loading}<Spinner />{/if}
  {@render children()}
</button>
