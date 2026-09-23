<script lang="ts" module>
  /** What a cited material number resolves to; index n-1 is citation [n]. */
  export interface SourceRef {
    filename: string;
    label: string;
  }
</script>

<script lang="ts">
  interface Props {
    cited: number[];
    sources: SourceRef[];
  }

  let { cited, sources }: Props = $props();

  const unique = $derived([...new Set(cited)].sort((a, b) => a - b));
</script>

<div class="flex flex-wrap items-center gap-1.5 text-xs">
  <span class="text-slate-400">Based on</span>
  {#each unique as n (n)}
    {@const source = sources[n - 1]}
    <span
      class="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600 ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700"
      title={source ? `${source.filename} · ${source.label}` : undefined}
    >
      <span class="font-mono text-indigo-600 dark:text-indigo-300">[{n}]</span>
      {#if source}{source.filename} · {source.label}{/if}
    </span>
  {/each}
</div>
