<script lang="ts">
  import CodeView from '$lib/components/CodeView.svelte';
  import EditableDocument from '$lib/components/EditableDocument.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Quiz from '$lib/components/Quiz.svelte';
  import SheetView from '$lib/components/SheetView.svelte';
  import SlidesView from '$lib/components/SlidesView.svelte';
  import Spinner from '$lib/components/Spinner.svelte';
  import WorkspaceHtmlView from '$lib/components/WorkspaceHtmlView.svelte';
  import MindMapView from '$lib/components/MindMapView.svelte';
  import ArtifactContent from '$lib/components/artifacts/ArtifactContent.svelte';
  import { KIND_ICONS, type ArtifactKind } from '$lib/stores/artifact.svelte';
  import { materialSources, type CourseChats } from '$lib/stores/chat.svelte';
  import type { PanelState } from '$lib/stores/panel.svelte';
  import type { WorkspaceCanvas } from '$lib/stores/workspace.svelte';
  import type { IconName } from '$lib/components/Icon.svelte';

  interface Props {
    panel: PanelState;
    canvas: WorkspaceCanvas;
    chats: CourseChats;
    messageFor: (turnIndex: number) => string | null;
    courseId: string;
    onclose: () => void;
    onfollowup: (text: string) => void;
    onsave?: (turnIndex: number, itemIndex: number, asCopy?: boolean) => void;
    onartifactsaved?: () => void | Promise<void>;
  }

  let { panel, canvas, chats, messageFor, courseId, onclose, onfollowup, onsave, onartifactsaved }: Props = $props();

  // Workspace `[n]` markers are numbered against the full material list, but
  // loaded citations are in prose-marker order. Resolve through the turn's
  // material list so a chip never names the wrong file.
  const sourcesFor = (turnIndex: number) => materialSources(chats.turns[turnIndex]);
  const mapSourcesFor = (turnIndex: number) => sourcesFor(turnIndex);

  async function copyActiveArtifact() {
    const current = panel.active;
    if (!current) return;
    try {
      const copy = await current.open.copy();
      await onartifactsaved?.();
      await panel.openArtifact({ artifact_id: copy.artifact_id, title: copy.title, kind: copy.kind });
    } catch (caught) {
      current.open.saveError = caught;
    }
  }

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
      <div class="flex flex-col items-start gap-2 p-5 text-sm text-danger-text">
        <p>Could not open this artifact.</p>
        <button
          type="button"
          onclick={() => activeArtifact.open.reload()}
          class="rounded-lg px-2 py-1 text-xs font-medium text-muted hover:bg-surface-2 hover:text-fg"
        >
          Try again
        </button>
      </div>
    {:else if activeArtifact.open.artifact}
      <div class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
        <div class="flex items-center gap-2">
          <input
            bind:value={activeArtifact.open.title}
            oninput={() => activeArtifact.open.touch()}
            aria-label="Title"
            class="min-w-0 flex-1 rounded-lg border border-transparent bg-transparent px-1 py-0.5 font-display text-lg font-medium tracking-tight text-fg hover:border-line focus:border-accent focus:outline-none"
          />
          <button
            type="button"
            onclick={() => void copyActiveArtifact()}
            disabled={activeArtifact.open.saving || activeArtifact.open.conflict}
            class="shrink-0 rounded-md border border-line-strong px-2 py-1 text-[11px] font-medium text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-50"
          >Save a copy</button>
          {#if activeArtifact.open.conflict}
            <span class="text-[11px] text-warning-text">Changed elsewhere</span>
          {:else if activeArtifact.open.saveError}
            <span class="text-[11px] text-danger-text">Not saved</span>
            <button
              type="button"
              onclick={() => activeArtifact.open.retrySave()}
              class="text-[11px] font-medium text-accent-text hover:underline"
            >
              Retry
            </button>
          {:else if activeArtifact.open.saving || activeArtifact.open.dirty}
            <span class="text-[11px] text-subtle">Saving…</span>
          {/if}
        </div>
        {#if activeArtifact.open.conflict}
          <p class="flex flex-wrap items-center gap-2 rounded-lg border border-warning/40 bg-warning-soft px-3 py-2 text-[12px] text-warning-text">
            <span class="flex-1">This was saved from somewhere else, so your latest changes here are not saved.</span>
            <button
              type="button"
              onclick={() => activeArtifact.open.loadLatestAndDiscardDraft()}
              class="rounded-md bg-surface px-2 py-1 font-medium text-fg ring-1 ring-inset ring-line-strong hover:bg-surface-2"
            >
              Load latest and discard my draft
            </button>
          </p>
        {/if}
        {#if activeArtifact.open.recovered}
          <p class="rounded-lg border border-accent-line bg-accent-soft/40 px-3 py-2 text-[12px] text-muted">Recovered unsaved edits from this device. They remain here until the next save succeeds.</p>
        {/if}
        {#each activeArtifact.open.recoveryDrafts as draft (draft.key)}
          <div class="rounded-lg border border-warning/40 bg-warning-soft px-3 py-2 text-[12px] text-warning-text">
            {#if draft.baseVersion === activeArtifact.open.artifact.version}
              <p>A saved draft from another window is available for this artifact version.</p>
            {:else}
              <p>This saved draft is based on an older artifact version. Keep its contents available below before choosing how to continue.</p>
            {/if}
            <details class="mt-2">
              <summary class="cursor-pointer font-medium">Copy the saved draft</summary>
              <textarea readonly aria-label="Saved draft contents for copying" class="mt-2 h-28 w-full rounded border border-warning/40 bg-surface p-2 font-mono text-[11px] text-fg">{JSON.stringify(draft, null, 2)}</textarea>
            </details>
            <div class="mt-2 flex gap-2">
              <button type="button" onclick={() => activeArtifact.open.recoverSavedDraft(draft)} class="rounded bg-surface px-2 py-1 font-medium text-fg">Try this draft</button>
              <button type="button" onclick={() => activeArtifact.open.discardSavedDraft(draft)} class="rounded bg-surface px-2 py-1 font-medium text-fg">Discard this draft</button>
              <button type="button" onclick={() => activeArtifact.open.loadLatestAndDiscardDraft()} class="rounded bg-surface px-2 py-1 font-medium text-fg">Load latest and discard draft</button>
            </div>
          </div>
        {/each}
        {#if activeArtifact.open.recoveryError}
          <p role="status" class="rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-[12px] text-danger-text">Local recovery status: {activeArtifact.open.recoveryError instanceof Error ? activeArtifact.open.recoveryError.message : 'Could not persist or read this draft.'}</p>
        {/if}
        <ArtifactContent
          kind={activeArtifact.kind}
          title={activeArtifact.open.title}
          content={activeArtifact.open.content}
          mapContext={{ courseId, origin: { artifact_id: activeArtifact.artifactId, artifact_version: activeArtifact.open.artifact.version, item_index: 0 }, ready: !activeArtifact.open.dirty && !activeArtifact.open.saving && !activeArtifact.open.conflict }}
          mapSources={activeArtifact.open.citations.map(c => c.citation)}
          ongenerated={onartifactsaved}
          practice={{ courseId: activeArtifact.open.courseId, artifactId: activeArtifact.artifactId, version: activeArtifact.open.artifact.version, ready: !activeArtifact.open.dirty && !activeArtifact.open.saving && !activeArtifact.open.conflict }}
          onchange={() => activeArtifact.open.touch()}
        />
      </div>
    {/if}
  {:else if activeCanvas}
    {@const messageId = messageFor(activeCanvas.turnIndex)}
    {@const exportContext = messageId ? { courseId, messageId, itemIndex: Number(activeCanvas.id.split(':')[1] ?? 0) } : null}
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
          <button
            type="button"
            onclick={() => onsave(current.turnIndex, Number(current.id.split(':')[1] ?? 0), true)}
            class="inline-flex items-center gap-1.5 rounded-lg border border-line-strong px-2.5 py-1 text-[12px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg"
          >
            Save a copy
          </button>
        {/if}
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto p-5">
        {#if activeCanvas.session.kind === 'quiz'}
          <Quiz session={activeCanvas.session} sources={sourcesFor(activeCanvas.turnIndex)} {onfollowup} />
        {:else if activeCanvas.session.kind === 'document'}
          <EditableDocument session={activeCanvas.session} sources={sourcesFor(activeCanvas.turnIndex)} {exportContext} />
        {:else if activeCanvas.session.kind === 'html'}
          <WorkspaceHtmlView item={activeCanvas.session.htmlItem} sources={sourcesFor(activeCanvas.turnIndex)} />
        {:else if activeCanvas.session.kind === 'code'}
          <CodeView item={activeCanvas.session.item} sources={sourcesFor(activeCanvas.turnIndex)} />
        {:else if activeCanvas.session.kind === 'sheet'}
          <SheetView session={activeCanvas.session} sources={sourcesFor(activeCanvas.turnIndex)} {exportContext} />
        {:else if activeCanvas.session.kind === 'mind_map'}
          <MindMapView map={activeCanvas.session.item} sources={mapSourcesFor(activeCanvas.turnIndex)} context={messageId ? { courseId, origin: { message_id: messageId, item_index: Number(activeCanvas.id.split(':')[1] ?? 0) } } : undefined} ongenerated={onartifactsaved} />
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
