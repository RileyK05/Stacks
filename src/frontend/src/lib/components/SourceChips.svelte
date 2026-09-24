<script lang="ts" module>
  /** What a cited material number resolves to; index n-1 is citation [n]. */
  export interface SourceRef {
    filename: string;
    label: string;
  }
</script>

<script lang="ts">
  import Icon from './Icon.svelte';

  interface Props {
    cited: number[];
    sources: SourceRef[];
  }

  let { cited, sources }: Props = $props();

  const unique = $derived([...new Set(cited)].sort((a, b) => a - b));
</script>

<div class="flex flex-wrap items-center gap-1.5 text-xs">
  <span class="inline-flex items-center gap-1 text-subtle">
    <Icon name="bookmark" class="h-3.5 w-3.5" /> Based on
  </span>
  {#each unique as n (n)}
    {@const source = sources[n - 1]}
    <span
      class="inline-flex max-w-full items-center gap-1.5 rounded-full border border-line bg-surface-2 py-0.5 pl-0.5 pr-2 text-muted"
      title={source ? `${source.filename} · ${source.label}` : undefined}
    >
      <span class="flex h-4 min-w-4 items-center justify-center rounded-full bg-accent-soft px-1 font-mono text-[10px] font-medium text-accent-text">
        {n}
      </span>
      {#if source}<span class="truncate">{source.filename} · {source.label}</span>{/if}
    </span>
  {/each}
</div>
