<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon, { type IconName } from './Icon.svelte';

  interface Props {
    tone?: 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info';
    icon?: IconName;
    dot?: boolean;
    class?: string;
    children: Snippet;
  }

  let { tone = 'neutral', icon, dot = false, class: className = '', children }: Props = $props();

  const tones = {
    neutral: 'bg-surface-2 text-muted ring-line',
    accent: 'bg-accent-soft text-accent-text ring-accent-line/60',
    success: 'bg-success-soft text-success-text ring-success/25',
    warning: 'bg-warning-soft text-warning-text ring-warning/30',
    danger: 'bg-danger-soft text-danger-text ring-danger/25',
    info: 'bg-info-soft text-info-text ring-info/25'
  };

  const dots = {
    neutral: 'bg-subtle',
    accent: 'bg-accent',
    success: 'bg-success',
    warning: 'bg-warning',
    danger: 'bg-danger',
    info: 'bg-info'
  };
</script>

<span
  class={`inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-full px-2 text-xs font-medium ring-1 ring-inset ${tones[tone]} ${className}`}
>
  {#if dot}<span class={`h-1.5 w-1.5 rounded-full ${dots[tone]}`}></span>{/if}
  {#if icon}<Icon name={icon} class="h-3.5 w-3.5" />{/if}
  {@render children()}
</span>
