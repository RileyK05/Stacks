<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { beforeNavigate, goto, replaceState } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api/client';
  import type { components, paths } from '$lib/api/schema';
  import Button from '$lib/components/Button.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon, { type IconName } from '$lib/components/Icon.svelte';
  import ModelPicker from '$lib/components/ModelPicker.svelte';
  import Monogram from '$lib/components/Monogram.svelte';
  import Popover from '$lib/components/Popover.svelte';
  import ResizableSplit from '$lib/components/ResizableSplit.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Panel from '$lib/components/course/Panel.svelte';
  import ArtifactsPanel from '$lib/components/course/ArtifactsPanel.svelte';
  import ChatList from '$lib/components/course/ChatList.svelte';
  import ChatThread from '$lib/components/course/ChatThread.svelte';
  import OfficeMenu from '$lib/components/course/OfficeMenu.svelte';
  import SourcePicker from '$lib/components/course/SourcePicker.svelte';
  import SourcesPanel from '$lib/components/course/SourcesPanel.svelte';
  import MemoryPanel from '$lib/components/course/MemoryPanel.svelte';
  import { listArtifacts, saveFromMessage, type ArtifactSummary } from '$lib/stores/artifact.svelte';
  import { CourseChats, type ModelChoice } from '$lib/stores/chat.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { PanelState } from '$lib/stores/panel.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { draftForSaving, WorkspaceCanvas } from '$lib/stores/workspace.svelte';
  import { WorkspaceDraftRecovery } from '$lib/stores/workspaceRecovery.svelte';
  import { formatBytes } from '$lib/utils/format';
  import { showCompanion } from '$lib/utils/companion';
  import { plural } from '$lib/utils/labels';

  type CourseView =
    paths['/courses/{course_id}']['get']['responses'][200]['content']['application/json'];
  type SourceView =
    paths['/courses/{course_id}/sources']['get']['responses'][200]['content']['application/json'][number];
  type ModelOption = components['schemas']['ModelOption'];
  type ConnectionView = components['schemas']['ConnectionView'];

  const courseId = page.params.id ?? '';

  let course = $state<CourseView | null>(null);
  let sources = $state<SourceView[]>([]);
  let includeGenerated = $state<boolean | null>(null);
  let generatedBusy = $state(false);

  async function loadRetrievalSettings() {
    const { data } = await api.GET('/courses/{course_id}/retrieval-settings', {
      params: { path: { course_id: courseId } }
    });
    if (data && !destroyed) includeGenerated = data.include_generated;
  }

  async function setGeneratedSearch(value: boolean) {
    if (generatedBusy) return;
    generatedBusy = true;
    try {
      const { data } = await api.PUT('/courses/{course_id}/retrieval-settings', {
        params: { path: { course_id: courseId } }, body: { include_generated: value }
      });
      if (data && !destroyed) includeGenerated = data.include_generated;
    } catch (caught) {
      toast(caught instanceof Error ? caught.message : 'Could not change study-material search.', 'error');
    } finally {
      generatedBusy = false;
    }
  }
  let loading = $state(true);
  let error = $state<unknown>(null);
  let actionError = $state<unknown>(null);

  type Tab = 'chat' | 'artifacts' | 'sources' | 'memory';
  const requestedTab = page.url.searchParams.get('tab');
  let activeTab = $state<Tab>(
    requestedTab === 'artifacts' || requestedTab === 'sources' || requestedTab === 'memory' ? requestedTab : 'chat'
  );
  let artifacts = $state<ArtifactSummary[]>([]);
  let artifactsLoading = $state(true);
  let renaming = $state(false);
  let renameValue = $state('');

  const chats = new CourseChats(courseId);
  const canvas = new WorkspaceCanvas();
  const panel = new PanelState(courseId, `stacks-panel:${courseId}`);
  let workspaceRecovery = $state<Record<string, WorkspaceDraftRecovery>>({});
  let leaving = false;

  $effect(() => {
    for (const turn of chats.turns) {
      if (!turn.messageId) continue;
      turn.workspace.forEach((session, itemIndex) => {
        const draft = draftForSaving(session);
        if (draft === null) return;
        const key = `${turn.messageId}:${itemIndex}`;
        if (workspaceRecovery[key]?.session !== session) {
          workspaceRecovery[key] = new WorkspaceDraftRecovery(courseId, turn.messageId!, itemIndex, session);
        }
        workspaceRecovery[key].observe(draft);
      });
    }
  });

  async function flushWorkspace(): Promise<boolean> {
    const results = await Promise.all(Object.values(workspaceRecovery).map((draft) => draft.flush()));
    return results.every(Boolean);
  }

  beforeNavigate((navigation) => {
    if (leaving) return;
    if (!panel.tabs.some((tab) => tab.open.dirty || tab.open.saving) && Object.values(workspaceRecovery).length === 0) return;
    if (navigation.willUnload) return;
    navigation.cancel();
    void Promise.all([panel.flushAll(), flushWorkspace()]).then(async (results) => {
      if (!results.every(Boolean)) {
        actionError = new Error('Your edits could not be saved. Keep this page open and retry, or copy them before leaving.');
        return;
      }
      if (navigation.to) {
        leaving = true;
        await goto(navigation.to.url);
      }
    }).catch((caught) => { actionError = caught; });
  });
  // One flag controls the whole right pane: the toggle must be able to open
  // it even when there is nothing in it yet.
  let rightOpen = $derived(panel.visible);
  let thread = $state<ReturnType<typeof ChatThread> | null>(null);
  let workspaceRef = $state<HTMLElement | null>(null);
  let chatsOpen = $state(false);
  let openingCompanion = $state(false);

  async function openCourseCompanion() {
    if (openingCompanion) return;
    openingCompanion = true;
    try {
      await showCompanion(courseId);
    } catch (caught) {
      toast(caught instanceof Error ? caught.message : 'Could not open the companion.', 'error');
    } finally {
      openingCompanion = false;
    }
  }

  /** What Settings would answer with, and what "Ask a bigger model" uses. */
  let defaultModel = $state<string | null>(null);
  let biggerModel = $state<string | null>(null);
  let modelOptions = $state<ModelOption[]>([]);
  let connections = $state<ConnectionView[]>([]);

  /** The default model's display name ("minicpm5-2b" → "MiniCPM5-2B"). */
  let defaultLabel = $derived(
    defaultModel === null
      ? null
      : (modelOptions.find((o) => o.is_local && o.model === defaultModel)?.label ?? defaultModel)
  );

  let anyPending = $derived(
    sources.some((source) => source.status === 'uploaded' || source.status === 'scanned')
  );
  let hasIndexed = $derived(sources.some((source) => source.status === 'indexed' || source.has_index));

  let destroyed = false;

  onMount(() => {
    load().catch((err) => {
      error = err;
      loading = false;
    });
    return () => {
      destroyed = true;
      panel.dispose();
    };
  });

  /** The header's counts and size come from the course itself: re-read them
   * after anything that adds or removes sources or artifacts. */
  async function refreshCourse() {
    try {
      const { data } = await api.GET('/courses/{course_id}', {
        params: { path: { course_id: courseId } }
      });
      if (data && !destroyed) course = data;
    } catch {
      // The counts stay as they were; the next change tries again.
    }
  }

  async function sourcesChanged() {
    await loadSources();
    void refreshCourse();
  }

  async function artifactsChanged() {
    await loadArtifacts();
    void refreshCourse();
  }

  async function load() {
    loading = true;
    error = null;
    try {
      const { data, error: err } = await api.GET('/courses/{course_id}', {
        params: { path: { course_id: courseId } }
      });
      if (err || !data) throw err ?? new Error('unexpected empty response');
      course = data;
      await Promise.all([loadSources(), chats.loadList(), loadArtifacts(), loadRetrievalSettings()]);
      void loadModels();
      const wanted = page.url.searchParams.get('chat');
      if (wanted && chats.conversations.some((c) => c.conversation_id === wanted)) {
        await chats.open(wanted);
      } else if (chats.conversations.length > 0) {
        await chats.open(chats.conversations[0].conversation_id);
      }
    } finally {
      loading = false;
    }
  }

  async function loadSources() {
    const res = await api.GET('/courses/{course_id}/sources', {
      params: { path: { course_id: courseId } }
    });
    if (res.error) throw res.error;
    sources = res.data ?? [];
    void pollSourcesUntilSettled();
  }

  async function loadArtifacts() {
    // The skeleton is only for the first load; later refreshes swap in place.
    try {
      artifacts = await listArtifacts(courseId);
      // A tab open on an artifact that was deleted has nothing left to show.
      panel.prune(new Set(artifacts.map((artifact) => artifact.artifact_id)));
      // A rename or restore elsewhere bumps the version; an open tab still on
      // the old one would report a false "changed elsewhere" on its next save.
      for (const tab of panel.tabs) {
        const fresh = artifacts.find((artifact) => artifact.artifact_id === tab.artifactId);
        const open = tab.open;
        if (fresh && open.artifact && fresh.version !== open.artifact.version && !open.dirty && !open.saving) {
          void open.reload().then(() => (tab.title = open.title || tab.title));
        }
      }
    } finally {
      artifactsLoading = false;
    }
  }

  const savingItems = new Set<string>();

  async function saveToArtifacts(turnIndex: number, itemIndex: number, asCopy = false) {
    const turn = chats.turns[turnIndex];
    const messageId = turn?.messageId;
    const session = turn?.workspace[itemIndex];
    if (!messageId || !session) return;
    const key = `${messageId}:${itemIndex}`;
    if (savingItems.has(key)) return;
    savingItems.add(key);
    const draft = draftForSaving(session);
    try {
      const saved = await saveFromMessage(courseId, messageId, itemIndex, draft, asCopy);
      artifacts = [saved, ...artifacts.filter((artifact) => artifact.artifact_id !== saved.artifact_id)];
      void refreshCourse();
      await panel.openArtifact(saved);
      await workspaceRecovery[key]?.discardSaved(draft);
      if (!panel.active?.open.error && JSON.stringify(draftForSaving(session)) === JSON.stringify(draft)) {
        canvas.close(`Q${turnIndex + 1}:${itemIndex}`);
      }
      toast(asCopy ? `Saved a copy of "${saved.title}".` : `Saved "${saved.title}". Continue editing in this artifact.`);
    } catch (caught) {
      actionError = caught;
    } finally {
      savingItems.delete(key);
    }
  }

  async function loadModels() {
    try {
      const [providersRes, optionsRes] = await Promise.all([
        api.GET('/settings/providers'),
        api.GET('/settings/model-options')
      ]);
      defaultModel = providersRes.data?.resolved.interactive?.model ?? null;
      biggerModel = providersRes.data?.resolved.bigger?.model ?? null;
      connections = providersRes.data?.connections ?? [];
      modelOptions = optionsRes.data ?? [];
    } catch {
      // The pickers fall back to "Settings default"; chatting still works.
    }
  }

  let polling = false;

  async function pollSourcesUntilSettled() {
    // Fresh uploads sit at uploaded→scanned→indexed invisibly otherwise.
    // Poll every 1.5s while anything is in flight; one loop at a time.
    if (polling) return;
    polling = true;
    let failures = 0;
    try {
      for (let attempt = 0; attempt < 600 && anyPending && !destroyed; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        if (destroyed) return;
        try {
          const res = await api.GET('/courses/{course_id}/sources', {
            params: { path: { course_id: courseId } }
          });
          failures = 0;
          if (res.data && !destroyed) sources = res.data;
        } catch {
          // A blip must not freeze the "Indexing" badges; give up after a few.
          if (++failures >= 5) return;
        }
      }
    } finally {
      polling = false;
      // Indexing changes the stored size and what the tutor can answer from.
      if (!destroyed) void refreshCourse();
    }
  }

  $effect(() => {
    // Keep the open chat in the address, so a reload comes back to it.
    const id = chats.activeId;
    if (loading || page.params.id !== courseId) return;
    const url = new URL(page.url);
    if (id) url.searchParams.set('chat', id);
    else url.searchParams.delete('chat');
    if (activeTab === 'chat') url.searchParams.delete('tab');
    else url.searchParams.set('tab', activeTab);
    if (url.search !== page.url.search) replaceState(url, page.state);
  });

  async function selectChat(id: string | null) {
    if (!(await flushWorkspace())) {
      actionError = new Error('Could not preserve your unfinished material. Retry or copy it before switching chats.');
      return;
    }
    workspaceRecovery = {};
    chatsOpen = false;
    canvas.clear();
    activeTab = 'chat';
    if (id === null) chats.startNew();
    else await chats.open(id);
  }

  async function openWorkspace(turnIndex: number) {
    const turn = chats.turns[turnIndex];
    if (!turn) return;
    const activeChat = chats.activeId;
    await chats.loadCitations(turn);
    if (destroyed || chats.activeId !== activeChat || chats.turns[turnIndex] !== turn) return;
    const savedItems = new Set<number>();
    for (let itemIndex = 0; itemIndex < turn.workspace.length; itemIndex++) {
      const saved = artifacts.find((artifact) => artifact.origin.adopted === true &&
        artifact.origin.message_id === turn.messageId && artifact.origin.item_index === itemIndex);
      if (saved) {
        savedItems.add(itemIndex);
        await panel.openArtifact(saved);
      }
    }
    canvas.openFromTurn(turnIndex, turn.workspace, savedItems);
    if (savedItems.size < turn.workspace.length) panel.activeId = null;
    panel.show();
    await tick();
    // Side by side on wide screens; stacked below on narrow ones.
    workspaceRef?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  async function setModel(choice: ModelChoice | null) {
    try {
      await chats.setModel(choice);
    } catch (caught) {
      actionError = caught;
    }
  }

  async function setSources(selected: string[] | null) {
    try {
      await chats.setSources(selected);
    } catch (caught) {
      actionError = caught;
    }
  }

  function startRename() {
    if (!course) return;
    renameValue = course.name;
    renaming = true;
  }

  let savingRename = false;

  async function saveRename(event: SubmitEvent) {
    event.preventDefault();
    const name = renameValue.trim();
    if (!name || savingRename) return;
    if (name === course?.name) {
      renaming = false;
      return;
    }
    actionError = null;
    savingRename = true;
    try {
      const { data, error: err } = await api.PATCH('/courses/{course_id}', {
        params: { path: { course_id: courseId } },
        body: { name }
      });
      if (err || !data) throw err ?? new Error('unexpected empty response');
      course = data;
      renaming = false;
    } catch (caught) {
      actionError = caught;
    } finally {
      savingRename = false;
    }
  }

  let exporting = $state(false);
  let exported = $state<{ path: string; filename: string } | null>(null);

  async function exportCourse() {
    exporting = true;
    actionError = null;
    try {
      const { data, error: err } = await api.POST('/courses/{course_id}/export', {
        params: { path: { course_id: courseId } }
      });
      if (err || !data) throw err ?? new Error('unexpected empty response');
      exported = { path: data.path, filename: data.filename };
    } catch (caught) {
      actionError = caught;
    } finally {
      exporting = false;
    }
  }

  async function reveal(path: string) {
    try {
      await api.POST('/settings/reveal', { body: { path } });
    } catch {
      toast('Could not open the folder.', 'error');
    }
  }

  async function moveToTrash() {
    if (
      !(await confirmDialog({
        title: 'Move this course to the trash?',
        message: 'You can restore it from Trash for 30 days. After that it is deleted permanently.',
        confirmLabel: 'Move to trash',
        danger: true
      }))
    )
      return;
    actionError = null;
    try {
      const { error: err } = await api.DELETE('/courses/{course_id}', {
        params: { path: { course_id: courseId } }
      });
      if (err) throw err;
      toast('Course moved to the trash.');
      await goto('/');
    } catch (caught) {
      actionError = caught;
    }
  }

  const tabs: { id: Tab; label: string; icon: IconName }[] = [
    { id: 'chat', label: 'Chat', icon: 'message-square' },
    { id: 'artifacts', label: 'Artifacts', icon: 'package' },
    { id: 'sources', label: 'Sources', icon: 'file-text' },
    { id: 'memory', label: 'Memory', icon: 'bookmark' }
  ];
</script>

<svelte:window onbeforeunload={(event) => {
  if (Object.values(workspaceRecovery).some((draft) => draft.error || draft.pendingWrites > 0)) {
    event.preventDefault();
    event.returnValue = '';
  }
}} />

{#if error}
  <ErrorBanner {error} />
{:else if loading || !course}
  <div class="flex flex-col gap-6">
    <div class="flex items-center gap-4">
      <Skeleton class="h-12 w-12 rounded-2xl" />
      <div class="flex flex-col gap-2"><Skeleton class="h-7 w-72" /><Skeleton class="h-4 w-48" /></div>
    </div>
    <Skeleton class="h-10 w-full" />
    <div class="grid gap-6 lg:grid-cols-[232px_minmax(0,1fr)]">
      <Skeleton class="hidden h-80 rounded-2xl lg:block" />
      <Skeleton class="h-80 rounded-2xl" />
    </div>
  </div>
{:else}
  <div class="flex flex-col gap-5">
    <header class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div class="flex min-w-0 items-center gap-3.5">
        <Monogram name={course.name} size="md" class="hidden sm:flex" />
        <div class="min-w-0">
          {#if renaming}
            <form onsubmit={saveRename} class="flex items-center gap-2">
              <input
                bind:value={renameValue}
                required
                maxlength={200}
                aria-label="Course name"
                onkeydown={(e) => e.key === 'Escape' && (renaming = false)}
                class="min-w-0 flex-1 rounded-lg border border-line-strong bg-surface px-3 py-1.5 font-display text-xl text-fg focus:border-accent focus:outline-none"
              />
              <Button type="submit" size="sm">Save</Button>
              <Button variant="ghost" size="sm" onclick={() => (renaming = false)}>Cancel</Button>
            </form>
          {:else}
            <h1 class="truncate font-display text-[1.6rem] font-medium leading-tight tracking-tight text-fg">
              {course.name}
            </h1>
          {/if}
          <p class="mt-1 text-[13px] text-subtle">
            {plural(course.source_count, 'source')} · {plural(chats.conversations.length, 'chat')} ·
            {plural(artifacts.length, 'artifact')} ·
            {formatBytes(course.stored_bytes ?? 0)} stored
          </p>
        </div>
      </div>
      <div class="flex shrink-0 flex-wrap items-center gap-1">
        <Button variant="secondary" size="sm" onclick={openCourseCompanion} loading={openingCompanion}>
          <Icon name="panel-right" class="h-4 w-4" /> Companion
        </Button>
        <OfficeMenu {courseId} />
        <Button variant="ghost" size="sm" onclick={startRename}>
          <Icon name="pencil" class="h-4 w-4" /> Rename
        </Button>
        <Button variant="ghost" size="sm" onclick={exportCourse} loading={exporting} title="Save this course as one .course file you can back up or share">
          <Icon name="download" class="h-4 w-4" /> Export
        </Button>
        <Button variant="ghost" size="sm" onclick={moveToTrash} class="text-danger-text hover:bg-danger-soft hover:text-danger-text">
          <Icon name="trash" class="h-4 w-4" /> Delete
        </Button>
      </div>
    </header>

    {#if actionError}<ErrorBanner error={actionError} />{/if}
    {#each Object.values(workspaceRecovery).filter((draft) => draft.error) as draft (draft.key)}
      <ErrorBanner error={new Error('Unfinished material could not be preserved on this computer. Copy your edits before closing Stacks.')} />
    {/each}
    {#if exported}
      <div class="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-surface-2 px-4 py-2.5 text-sm text-muted">
        <Icon name="check" class="h-4 w-4 text-success-text" />
        <span class="min-w-0 flex-1">Saved <span class="font-medium text-fg">{exported.filename}</span> to your Downloads folder. Open it with Import on My courses, on this or another computer.</span>
        <Button variant="secondary" size="sm" onclick={() => exported && reveal(exported.path)}>Show in folder</Button>
        <Button variant="ghost" size="sm" onclick={() => (exported = null)} aria-label="Dismiss"><Icon name="x" class="h-4 w-4" /></Button>
      </div>
    {/if}

    <div class="flex gap-1 border-b border-line" role="tablist">
      {#each tabs as { id: tab, label, icon } (tab)}
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === tab}
          onclick={() => (activeTab = tab)}
          class={`-mb-px inline-flex items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${
            activeTab === tab ? 'border-accent text-fg' : 'border-transparent text-muted hover:border-line-strong hover:text-fg'
          }`}
        >
          <Icon name={icon} class={`h-4 w-4 ${activeTab === tab ? 'text-accent-text' : 'text-subtle'}`} />
          {label}
          {#if tab === 'artifacts' && artifacts.length > 0}
            <span class="rounded-full bg-surface-3 px-1.5 text-[11px] font-semibold text-muted">{artifacts.length}</span>
          {/if}
          {#if tab === 'sources'}
            <span class="rounded-full bg-surface-3 px-1.5 text-[11px] font-semibold text-muted">{sources.length}</span>
            {#if anyPending}
              <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-warning" title="Indexing in progress"></span>
            {/if}
          {/if}
        </button>
      {/each}
    </div>

    {#if activeTab === 'chat'}
      <ResizableSplit bind:width={panel.width} collapsed={!rightOpen} stackBelow={1100}>
        {#snippet left()}
          <div class="grid items-start gap-6 lg:grid-cols-[232px_minmax(0,1fr)]">
            <aside class="sticky top-5 hidden max-h-[calc(100dvh-2.5rem)] min-h-0 flex-col lg:flex">
              <ChatList {chats} onselect={selectChat} />
            </aside>

            <section class="flex min-w-0 flex-col gap-4">
              <div class="flex flex-wrap items-center gap-2">
                <div class="lg:hidden">
                  <Popover bind:open={chatsOpen} label="Chats" width="w-72">
                    {#snippet trigger(props)}
                      <button
                        type="button"
                        {...props}
                        class="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[13px] font-medium text-fg shadow-card hover:border-line-strong"
                      >
                        <Icon name="message-square" class="h-3.5 w-3.5 text-subtle" /> Chats
                        <Icon name="chevron-down" class="h-3.5 w-3.5 text-subtle" />
                      </button>
                    {/snippet}
                    {#snippet children()}
                      <div class="max-h-[60vh] p-3">
                        <ChatList {chats} onselect={selectChat} />
                      </div>
                    {/snippet}
                  </Popover>
                </div>
                <h2 class="min-w-0 flex-1 truncate font-display text-lg font-medium tracking-tight text-fg">
                  {chats.active?.title || 'New chat'}
                </h2>
                <Button
                  variant="ghost"
                  size="sm"
                  onclick={() => (rightOpen ? panel.hide() : panel.show())}
                  title="Show or hide the side panel"
                >
                  <Icon name="panel-right" class="h-4 w-4" />
                  <span class="hidden sm:inline">Panel</span>
                </Button>
                <SourcePicker
                  {sources}
                  selected={chats.active?.source_ids ?? null}
                  disabled={chats.sending}
                  onchange={setSources}
                  {includeGenerated}
                  {generatedBusy}
                  ongeneratedchange={setGeneratedSearch}
                />
                <ModelPicker
                  options={modelOptions}
                  {connections}
                  choice={chats.active?.model_choice ?? null}
                  nullOption={{
                    label: 'Settings default',
                    description: defaultLabel ?? 'Choose one in Settings',
                    current: defaultLabel ?? 'No model set',
                    hint: 'Default'
                  }}
                  disabled={chats.sending}
                  onchange={setModel}
                />
              </div>

              <ChatThread
                bind:this={thread}
                {chats}
                {canvas}
                {biggerModel}
                hasSources={hasIndexed}
                indexing={anyPending}
                onopenworkspace={openWorkspace}
                panelVisible={rightOpen}
              />
            </section>
          </div>
        {/snippet}

        {#snippet right()}
          <div
            bind:this={workspaceRef}
            class="scroll-mt-20 lg:sticky lg:top-5 lg:h-[calc(100dvh-2.5rem)]"
          >
            <Panel
              {panel}
              {canvas}
              sourcesFor={(turnIndex) => chats.turns[turnIndex]?.citations ?? []}
              mapSourcesFor={(index) => {
                const turn = chats.turns[index];
                return turn?.chunkIds.map(id => turn.citations.find(c => c.chunk_id === id) ?? null) ?? [];
              }}
              onclose={() => panel.hide()}
              onfollowup={(text) => thread?.prefill(text)}
              {courseId}
              messageFor={(index) => chats.turns[index]?.messageId ?? null}
              onsave={saveToArtifacts}
              onartifactsaved={artifactsChanged}
            />
          </div>
        {/snippet}
      </ResizableSplit>
    {:else if activeTab === 'artifacts'}
      <ArtifactsPanel
        {courseId}
        {artifacts}
        loading={artifactsLoading}
        onchanged={artifactsChanged}
        onopen={(summary) => {
          activeTab = 'chat';
          void panel.openArtifact(summary);
        }}
      />
    {:else}
      {#if activeTab === 'memory'}
        <MemoryPanel {courseId} />
      {:else}
        <SourcesPanel {courseId} {sources} onchanged={sourcesChanged} />
      {/if}
    {/if}
  </div>
{/if}
