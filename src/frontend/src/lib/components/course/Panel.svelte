<script lang="ts">
  import CodeView from '$lib/components/CodeView.svelte';
  import EditableDocument from '$lib/components/EditableDocument.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Quiz from '$lib/components/Quiz.svelte';
  import SheetView from '$lib/components/SheetView.svelte';
  import SlidesView from '$lib/components/SlidesView.svelte';
  import Spinner from '$lib/components/Spinner.svelte';
  import WorkspaceHtmlView from '$lib/components/WorkspaceHtmlView.svelte';
  import ArtifactContent from '$lib/components/artifacts/ArtifactContent.svelte';
  import { KIND_ICONS, type ArtifactKind } from '$lib/stores/artifact.svelte';
  import type { Citation } from '$lib/stores/chat.svelte';
  import type { PanelState } from '$lib/stores/panel.svelte';
  import type { WorkspaceCanvas } from '$lib/stores/workspace.svelte';
  import type { IconName } from '$lib/components/Icon.svelte';

  interface Props {
    panel: PanelState;
    canvas: WorkspaceCanvas;
    sourcesFor: (turnIndex: number) => Citation[];
    onclose: () => void;
    onfollowup: (text: string) => void;
    onsave?: (turnIndex: number, itemIndex: number) => void;
  }

  let { panel, canvas, sourcesFor, onclose, onfollowup, onsave }: Props = $props();

  type UnifiedTab = {
    id: string;
    title: string;
    icon: IconName;
    kind: ArtifactKind | null;
    origin: string | null;
    isArtifact: boolean;
  };

  const tabs = $derived<UnifiedTab[]>([
    ...panel.tabs.map((tab) => ({
      id: `artifact:${tab.artifactId}`,
      title: tab.title,
      icon: KIND_ICONS[tab.kind],
      kind: tab.kind,
      origin: null,
      isArtifact: true
    })),
    ...canvas.tabs.map((tab) => ({
      id: `canvas:${tab.id}`,
      title: tab.title,
      icon: 'sparkles' as IconName,
      kind: null,
      origin: tab.origin,
      isArtifact: false
    }))
  ]);

  const activeTabId = $derived(
    panel.active
      ? `artifact:${panel.active.artifactId}`
      : canvas.active
        ? `canvas:${canvas.active.id}`
        : (tabs.at(-1)?.id ?? null)
  );
  const activeTab = $derived(
    tabs.find((tab) => tab.id === activeTabId) ?? tabs[0] ?? null
  );
  const activeArtifact = $derived(activeTab?.isArtifact ? panel.active : null);
  const activeCanvas = $derived(activeTab?.isArtifact ? null : canvas.active);

  function activate(id: string) {
    if (id.startsWith('artifact:')) {
      panel.activate(id.slice('artifact:'.length));
      canvas.activeId = null;
    } else {
      canvas.activate(id.slice('canvas:'.length));
      panel.activeId = null;
    }
  }

  function close(id: string) {
    if (id.startsWith('artifact:')) void panel.close(id.slice('artifact:'.length));
    else canvas.close(id.slice('canvas:'.length));
  }
</script>

<section
  aria-label="Panel"
  class="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-lift"
>
  <div class="flex items-center gap-2 border-b border-line px-2 py-1.5">
    <div
      role="tablist"
      aria-label="Open tabs"
      class="flex min-w-0 flex-1 gap-1 overflow-x-auto"
    >
      {#each tabs as tab (tab.id)}
        {@const selected = activeTabId === tab.id}
        <div
          role="presentation"
          class={`group flex shrink-0 items-center gap-1.5 rounded-lg py-1 pl-2.5 pr-1 text-[13px] font-medium transition-colors ${
            selected
              ? 'bg-surface-2 text-fg shadow-card ring-1 ring-line'
              : 'text-muted hover:bg-surface-2/70 hover:text-fg'
          }`}
        >
          <Icon name={tab.icon} class="h-3.5 w-3.5 shrink-0" />
          <button
            type="button"
            role="tab"
            aria-selected={selected}
            onclick={() => activate(tab.id)}
            class="max-w-36 truncate"
            title={tab.title}
          >
            {tab.title}
          </button>
          {#if tab.origin}
            <span class="font-mono text-[10px] text-subtle">{tab.origin}</span>
          {/if}
          <button
            type="button"
            aria-label={`Close ${tab.title}`}
            onclick={() => close(tab.id)}
            class="rounded p-0.5 text-subtle opacity-0 transition-opacity hover:bg-surface-3 hover:text-fg group-hover:opacity-100"
          >
            <Icon name="x" class="h-3.5 w-3.5" />
          </button>
        </div>
      {/each}
    </div>
    <button
      type="button"
      onclick={onclose}
      aria-label="Hide panel"
      class="shrink-0 rounded-md p-1 text-subtle hover:bg-surface-2 hover:text-fg"
    >
      <Icon name="x" class="h-4 w-4" />
    </button>
  </div>

  {#if activeArtifact}
    {#if activeArtifact.open.loading}
      <div class="flex flex-1 items-center justify-center p-6 text-muted">
        <Spinner class="h-5 w-5" />
      </div>
    {:else if activeArtifact.open.error}
      <p class="p-5 text-sm text-danger-text">Could not open this artifact.</p>
    {:else if activeArtifact.open.artifact}
      <div class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
        <div class="flex items-center gap-2">
          <input
            bind:value={activeArtifact.open.title}
            oninput={() => activeArtifact.open.touch()}
            aria-label="Title"
            class="min-w-0 flex-1 rounded-lg border border-transparent bg-transparent px-1 py-0.5 font-display text-lg font-medium tracking-tight text-fg hover:border-line focus:border-accent focus:outline-none"
          />
          {#if activeArtifact.open.saving || activeArtifact.open.dirty}
            <span class="text-[11px] text-subtle">Saving…</span>
          {:else if activeArtifact.open.conflict}
            <span class="text-[11px] text-warning-text">Changed elsewhere</span>
          {/if}
        </div>
        {#if activeArtifact.open.conflict}
          <p class="rounded-lg border border-warning/40 bg-warning-soft px-3 py-2 text-[12px] text-warning-text">
            This was saved from somewhere else. Reload to see the latest.
          </p>
        {/if}
        <ArtifactContent
          kind={activeArtifact.kind}
          title={activeArtifact.open.title}
          content={activeArtifact.open.content}
          onchange={() => activeArtifact.open.touch()}
        />
      </div>
    {/if}
  {:else if activeCanvas}
    <div class="flex min-h-0 flex-1 flex-col">
      <div class="flex items-center gap-2 border-b border-line px-3 py-1.5">
        <span class="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted">
          from {activeCanvas.origin}
        </span>
        {#if onsave}
          {@const current = activeCanvas}
          <button
            type="button"
            onclick={() => onsave(current.turnIndex, Number(current.id.split(':')[1] ?? 0))}
            class="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-accent px-2.5 py-1 text-[12px] font-medium text-on-accent shadow-card transition-colors hover:bg-accent-hover"
          >
            <Icon name="bookmark" class="h-3.5 w-3.5" /> Save to artifacts
          </button>
        {/if}
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto p-5">
        {#if activeCanvas.session.kind === 'quiz'}
          <Quiz session={activeCanvas.session} sources={sourcesFor(activeCanvas.turnIndex)} {onfollowup} />
        {:else if activeCanvas.session.kind === 'document'}
          <EditableDocument session={activeCanvas.session} sources={sourcesFor(activeCanvas.turnIndex)} />
        {:else if activeCanvas.session.kind === 'html'}
          <WorkspaceHtmlView item={activeCanvas.session.htmlItem} sources={sourcesFor(activeCanvas.turnIndex)} />
        {:else if activeCanvas.session.kind === 'code'}
          <CodeView item={activeCanvas.session.item} sources={sourcesFor(activeCanvas.turnIndex)} />
        {:else if activeCanvas.session.kind === 'sheet'}
          <SheetView session={activeCanvas.session} sources={sourcesFor(activeCanvas.turnIndex)} />
        {:else}
          <SlidesView session={activeCanvas.session} sources={sourcesFor(activeCanvas.turnIndex)} />
        {/if}
      </div>
    </div>
  {:else}
    <div class="flex flex-1 items-center justify-center p-6 text-center text-sm text-subtle">
      Open a document from the Artifacts tab, or ask a question that makes a quiz or study guide.
    </div>
  {/if}
</section>
