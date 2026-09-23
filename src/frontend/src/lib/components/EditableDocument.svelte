<script lang="ts">
  import type { DocumentSession } from '$lib/stores/workspace.svelte';
  import RichText from './RichText.svelte';
  import SourceChips, { type SourceRef } from './SourceChips.svelte';

  interface Props {
    session: DocumentSession;
    sources: SourceRef[];
  }

  let { session, sources }: Props = $props();

  let mode = $state<'edit' | 'preview'>('preview');

  const tabs: [typeof mode, string][] = [
    ['preview', 'Preview'],
    ['edit', 'Edit']
  ];

  function download() {
    const blob = new Blob([session.draft], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${(session.document.title ?? 'study-notes').replace(/[^\w-]+/g, '-')}.md`;
    link.click();
    URL.revokeObjectURL(url);
  }
</script>

<div class="flex flex-col gap-3">
  <div class="flex items-center gap-1 border-b border-slate-200 dark:border-slate-700">
    {#each tabs as [value, label] (value)}
      <button
        type="button"
        onclick={() => (mode = value)}
        class={`-mb-px border-b-2 px-3 py-1.5 text-xs font-medium transition-colors ${
          mode === value
            ? 'border-indigo-600 text-indigo-700 dark:border-indigo-400 dark:text-indigo-300'
            : 'border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200'
        }`}
      >
        {label}
      </button>
    {/each}
    <div class="ml-auto flex items-center gap-3 pb-1 text-xs">
      {#if session.edited}
        <button
          type="button"
          onclick={() => session.revert()}
          class="text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
        >
          Revert
        </button>
      {/if}
      <button
        type="button"
        onclick={download}
        class="text-indigo-600 hover:text-indigo-500 dark:text-indigo-300 dark:hover:text-indigo-200"
      >
        Download .md
      </button>
    </div>
  </div>

  {#if mode === 'edit'}
    <textarea
      bind:value={session.draft}
      rows={16}
      spellcheck={false}
      class="w-full resize-y rounded-lg border border-slate-300 bg-white p-3 font-mono text-sm leading-relaxed text-slate-800 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
    ></textarea>
    <p class="text-xs text-slate-400">
      Edits stay in this browser session — nothing is saved to your course.
    </p>
  {:else}
    <RichText text={session.draft} />
  {/if}

  <SourceChips cited={session.document.sources} {sources} />
</div>
