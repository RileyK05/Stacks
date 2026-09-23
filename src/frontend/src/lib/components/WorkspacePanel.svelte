<script lang="ts">
  import { itemTitle, type WorkspaceSession } from '$lib/stores/workspace.svelte';
  import EditableDocument from './EditableDocument.svelte';
  import Quiz from './Quiz.svelte';
  import type { SourceRef } from './SourceChips.svelte';

  interface Props {
    sessions: WorkspaceSession[];
    sources: SourceRef[];
    /** Which chat turn produced these items, e.g. "Q3". */
    origin: string;
    onclose: () => void;
    onfollowup: (question: string) => void;
  }

  let { sessions, sources, origin, onclose, onfollowup }: Props = $props();
</script>

<section
  aria-label="Workspace"
  class="flex h-full flex-col rounded-xl bg-white shadow-sm ring-1 ring-slate-200/80 dark:bg-slate-900 dark:ring-slate-700/80"
>
  <header class="flex items-center justify-between border-b border-slate-200 px-5 py-3 dark:border-slate-700">
    <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
      Workspace
      <span class="ml-1 font-mono text-xs normal-case text-indigo-600 dark:text-indigo-300">from {origin}</span>
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

  <div class="flex flex-1 flex-col gap-5 overflow-y-auto p-5">
    {#each sessions as session, index (index)}
      <article class="flex flex-col gap-3">
        <h3 class="text-base font-semibold text-slate-900 dark:text-slate-100">{itemTitle(session)}</h3>
        {#if session.kind === 'quiz'}
          <Quiz {session} {sources} {onfollowup} />
        {:else}
          <EditableDocument {session} {sources} />
        {/if}
      </article>
    {/each}
  </div>
</section>
