<script lang="ts">
  import { type WorkspaceCanvas } from '$lib/stores/workspace.svelte';
  import EditableDocument from './EditableDocument.svelte';
  import EmptyState from './EmptyState.svelte';
  import Quiz from './Quiz.svelte';
  import SourceChips, { type SourceRef } from './SourceChips.svelte';
  import WorkspaceHtmlView from './WorkspaceHtmlView.svelte';

  interface Props {
    canvas: WorkspaceCanvas;
    /** Citations for a turn, resolved lazily so late-loading sources appear. */
    sourcesFor: (turnIndex: number) => SourceRef[];
    onclose: () => void;
    onfollowup: (question: string) => void;
  }

  let { canvas, sourcesFor, onclose, onfollowup }: Props = $props();

  const active = $derived(canvas.active);
</script>

<section
  aria-label="Workspace"
  class="flex h-full min-h-0 flex-col rounded-xl bg-white shadow-sm ring-1 ring-slate-200/80 dark:bg-slate-900 dark:ring-slate-700/80"
>
  <header class="flex items-center justify-between border-b border-slate-200 px-5 py-3 dark:border-slate-700">
    <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
      Workspace
      {#if active}
        <span class="ml-1 font-mono text-xs normal-case text-indigo-600 dark:text-indigo-300">
          from {active.origin}
        </span>
      {/if}
    </h2>
    <button
      type="button"
      onclick={onclose}
      aria-label="Close workspace"
      class="rounded-md px-2 py-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
    >
      ✕
    </button>
  </header>

  {#if canvas.tabs.length > 0}
    <div
      role="tablist"
      aria-label="Open workspace items"
      class="flex gap-1 overflow-x-auto border-b border-slate-200 px-3 pt-2 dark:border-slate-700"
    >
      {#each canvas.tabs as tab (tab.id)}
        <div
          role="presentation"
          class={`group flex shrink-0 items-center gap-1 rounded-t-lg border-b-2 px-3 py-1.5 text-xs font-medium transition-colors ${
            canvas.activeId === tab.id
              ? 'border-indigo-600 bg-slate-50 text-slate-900 dark:border-indigo-400 dark:bg-slate-800/60 dark:text-slate-100'
              : 'border-transparent text-slate-500 hover:bg-slate-50 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-800/40 dark:hover:text-slate-200'
          }`}
        >
          <button
            type="button"
            role="tab"
            aria-selected={canvas.activeId === tab.id}
            onclick={() => canvas.activate(tab.id)}
            class="max-w-40 truncate"
            title={tab.title}
          >
            {tab.title}
          </button>
          <span class="font-mono text-[10px] text-slate-400 dark:text-slate-500">{tab.origin}</span>
          <button
            type="button"
            aria-label={`Close ${tab.title}`}
            onclick={() => canvas.close(tab.id)}
            class="rounded px-1 text-slate-400 transition-colors hover:bg-slate-200 hover:text-slate-600 dark:hover:bg-slate-700 dark:hover:text-slate-300"
          >
            ✕
          </button>
        </div>
      {/each}
    </div>

    {#if active}
      <div class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-5">
        {#if active.session.kind === 'quiz'}
          <Quiz session={active.session} sources={sourcesFor(active.turnIndex)} {onfollowup} />
        {:else if active.session.kind === 'document'}
          <EditableDocument session={active.session} sources={sourcesFor(active.turnIndex)} />
        {:else}
          <WorkspaceHtmlView item={active.session.htmlItem} sources={sourcesFor(active.turnIndex)} />
        {/if}
      </div>
    {/if}
  {:else}
    <div class="p-5">
      <EmptyState message="Quizzes and documents the tutor generates will open here as tabs." />
    </div>
  {/if}
</section>
