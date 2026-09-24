<script lang="ts">
  import { hueFor, initials } from '$lib/utils/labels';

  interface Props {
    name: string;
    size?: 'sm' | 'md' | 'lg';
    class?: string;
  }

  let { name, size = 'md', class: className = '' }: Props = $props();

  const sizes = {
    sm: 'h-7 w-7 rounded-lg text-[11px]',
    md: 'h-10 w-10 rounded-xl text-sm',
    lg: 'h-14 w-14 rounded-2xl text-lg'
  };
</script>

<span
  class={`monogram flex shrink-0 items-center justify-center font-display font-semibold tracking-tight ${sizes[size]} ${className}`}
  style:--hue={hueFor(name)}
  aria-hidden="true">{initials(name)}</span
>
