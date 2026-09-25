<script lang="ts">
  import { type WorkspaceCanvas, type WorkspaceSession } from '$lib/stores/workspace.svelte';
  import CodeView from './CodeView.svelte';
  import EditableDocument from './EditableDocument.svelte';
  import EmptyState from './EmptyState.svelte';
  import Icon, { type IconName } from './Icon.svelte';
  import Quiz from './Quiz.svelte';
  import SheetView from './SheetView.svelte';
  import SlidesView from './SlidesView.svelte';
  import { type SourceRef } from './SourceChips.svelte';
  import WorkspaceHtmlView from './WorkspaceHtmlView.svelte';

  interface Props {
    canvas: WorkspaceCanvas;
    /** Citations for a turn, resolved lazily so late-loading sources appear. */
    sourcesFor: (turnIndex: number) => SourceRef[];
    onclose: () => void;
    onfollowup: (question: string) => void;
    /** Save the open item as a course artifact (turn index, item index). */
    onsave?: (turnIndex: number, itemIndex: number) => void;
  }

  let { canvas, sourcesFor, onclose, onfollowup, onsave }: Props = $props();

  const active = $derived(canvas.active);

  const kindIcons: Record<WorkspaceSession['kind'], IconName> = {
    quiz: 'list-checks',
    document: 'file-pen',
    html: 'layers',
    code: 'code',
    sheet: 'table',
    slides: 'presentation'
  };
</script>

<section
  aria-label="Workspace"
  class="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-lift"
>
  <header class="flex items-center gap-2 border-b border-line px-4 py-3">
    <Icon name="panel-right" class="h-4 w-4 text-subtle" />
    <h2 class="text-sm font-semibold text-fg">Workspace</h2>
    {#if active}
      <span class="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted">from {active.origin}</span>
    {/if}
    {#if active && onsave}
      {@const current = active}
      <button
        type="button"
        onclick={() => onsave(current.turnIndex, Number(current.id.split(':')[1] ?? 0))}
        title="Keep it in this course as an editable artifact"
        class="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-accent px-2.5 py-1 text-[12px] font-medium text-on-accent shadow-card transition-colors hover:bg-accent-hover"
      >
        <Icon name="bookmark" class="h-3.5 w-3.5" /> Save to artifacts
      </button>
    {/if}
    <button
      type="button"
      onclick={onclose}
      aria-label="Close workspace"
      class={`${active && onsave ? '' : 'ml-auto'} rounded-lg p-1.5 text-subtle transition-colors hover:bg-surface-2 hover:text-fg`}
    >
      <Icon name="x" class="h-4 w-4" />
    </button>
  </header>

  {#if canvas.tabs.length > 0}
    <div
      role="tablist"
      aria-label="Open workspace items"
      class="flex gap-1 overflow-x-auto border-b border-line bg-surface-2/50 px-2 py-1.5"
    >
      {#each canvas.tabs as tab (tab.id)}
        {@const selected = canvas.activeId === tab.id}
        <div
          role="presentation"
          class={`group flex shrink-0 items-center gap-1.5 rounded-lg py-1 pl-2.5 pr-1 text-[13px] font-medium transition-colors ${
            selected
              ? 'bg-surface text-fg shadow-card ring-1 ring-line'
              : 'text-muted hover:bg-surface/70 hover:text-fg'
          }`}
        >
          <Icon
            name={kindIcons[tab.session.kind]}
            class={`h-3.5 w-3.5 ${selected ? 'text-accent-text' : 'text-subtle'}`}
          />
          <button
            type="button"
            role="tab"
            aria-selected={selected}
            onclick={() => canvas.activate(tab.id)}
            class="max-w-40 truncate"
            title={tab.title}
          >
            {tab.title}
          </button>
          <span class="font-mono text-[10px] text-subtle">{tab.origin}</span>
          <button
            type="button"
            aria-label={`Close ${tab.title}`}
            onclick={() => canvas.close(tab.id)}
            class="rounded p-0.5 text-subtle opacity-60 transition-all hover:bg-surface-3 hover:text-fg group-hover:opacity-100"
          >
            <Icon name="x" class="h-3.5 w-3.5" />
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
        {:else if active.session.kind === 'html'}
          <WorkspaceHtmlView item={active.session.htmlItem} sources={sourcesFor(active.turnIndex)} />
        {:else if active.session.kind === 'code'}
          <CodeView item={active.session.item} sources={sourcesFor(active.turnIndex)} />
        {:else if active.session.kind === 'sheet'}
          <SheetView session={active.session} sources={sourcesFor(active.turnIndex)} />
        {:else}
          <SlidesView session={active.session} sources={sourcesFor(active.turnIndex)} />
        {/if}
      </div>
    {/if}
  {:else}
    <div class="p-5">
      <EmptyState icon="panel-right" message="Quizzes and documents the tutor generates will open here as tabs." />
    </div>
  {/if}
</section>
