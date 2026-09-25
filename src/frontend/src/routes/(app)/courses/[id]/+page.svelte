<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { goto, replaceState } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api/client';
  import type { components, paths } from '$lib/api/schema';
  import Button from '$lib/components/Button.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon, { type IconName } from '$lib/components/Icon.svelte';
  import ModelPicker from '$lib/components/ModelPicker.svelte';
  import Monogram from '$lib/components/Monogram.svelte';
  import Popover from '$lib/components/Popover.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import WorkspacePanel from '$lib/components/WorkspacePanel.svelte';
  import ArtifactsPanel from '$lib/components/course/ArtifactsPanel.svelte';
  import ChatList from '$lib/components/course/ChatList.svelte';
  import ChatThread from '$lib/components/course/ChatThread.svelte';
  import SourcePicker from '$lib/components/course/SourcePicker.svelte';
  import SourcesPanel from '$lib/components/course/SourcesPanel.svelte';
  import { listArtifacts, saveFromMessage, type ArtifactSummary } from '$lib/stores/artifact.svelte';
  import { CourseChats, type ModelChoice } from '$lib/stores/chat.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { WorkspaceCanvas } from '$lib/stores/workspace.svelte';
  import { formatBytes } from '$lib/utils/format';
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
  let loading = $state(true);
  let error = $state<unknown>(null);
  let actionError = $state<unknown>(null);

  type Tab = 'chat' | 'artifacts' | 'sources';
  const requestedTab = page.url.searchParams.get('tab');
  let activeTab = $state<Tab>(
    requestedTab === 'artifacts' || requestedTab === 'sources' ? requestedTab : 'chat'
  );
  let artifacts = $state<ArtifactSummary[]>([]);
  let artifactsLoading = $state(true);
  let renaming = $state(false);
  let renameValue = $state('');

  const chats = new CourseChats(courseId);
  const canvas = new WorkspaceCanvas();
  let workspaceOpen = $derived(canvas.open);
  let thread = $state<ReturnType<typeof ChatThread> | null>(null);
  let workspaceRef = $state<HTMLElement | null>(null);
  let chatsOpen = $state(false);

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
  let hasIndexed = $derived(sources.some((source) => source.status === 'indexed'));

  onMount(() => {
    load().catch((err) => {
      error = err;
      loading = false;
    });
  });

  async function load() {
    loading = true;
    error = null;
    try {
      const { data, error: err } = await api.GET('/courses/{course_id}', {
        params: { path: { course_id: courseId } }
      });
      if (err || !data) throw err ?? new Error('unexpected empty response');
      course = data;
      await Promise.all([loadSources(), chats.loadList(), loadArtifacts()]);
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
    artifactsLoading = true;
    try {
      artifacts = await listArtifacts(courseId);
    } finally {
      artifactsLoading = false;
    }
  }

  async function saveToArtifacts(turnIndex: number, itemIndex: number) {
    const messageId = chats.turns[turnIndex]?.messageId;
    if (!messageId) return;
    try {
      const saved = await saveFromMessage(courseId, messageId, itemIndex);
      artifacts = [saved, ...artifacts];
      toast(`Saved "${saved.title}" to this course's artifacts.`);
    } catch (caught) {
      actionError = caught;
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
    try {
      for (let attempt = 0; attempt < 600 && anyPending; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        if (!course) return;
        const res = await api.GET('/courses/{course_id}/sources', {
          params: { path: { course_id: courseId } }
        });
        if (res.data) sources = res.data;
      }
    } catch {
      // A failed poll just stops; the Sources tab has Retry.
    } finally {
      polling = false;
    }
  }

  $effect(() => {
    // Keep the open chat in the address, so a reload comes back to it.
    const id = chats.activeId;
    if (loading) return;
    const url = new URL(page.url);
    if (id) url.searchParams.set('chat', id);
    else url.searchParams.delete('chat');
    if (activeTab === 'chat') url.searchParams.delete('tab');
    else url.searchParams.set('tab', activeTab);
    if (url.search !== page.url.search) replaceState(url, page.state);
  });

  async function selectChat(id: string | null) {
    chatsOpen = false;
    canvas.clear();
    activeTab = 'chat';
    if (id === null) chats.startNew();
    else await chats.open(id);
  }

  async function openWorkspace(turnIndex: number) {
    canvas.openFromTurn(turnIndex, chats.turns[turnIndex].workspace);
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

  async function saveRename(event: SubmitEvent) {
    event.preventDefault();
    actionError = null;
    try {
      const { data, error: err } = await api.PATCH('/courses/{course_id}', {
        params: { path: { course_id: courseId } },
        body: { name: renameValue }
      });
      if (err || !data) throw err ?? new Error('unexpected empty response');
      course = data;
      renaming = false;
    } catch (caught) {
      actionError = caught;
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
    const { error: err } = await api.POST('/settings/reveal', { body: { path } });
    if (err) toast('Could not open the folder.', 'error');
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
    { id: 'sources', label: 'Sources', icon: 'file-text' }
  ];
</script>

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
      <div
        class={`grid items-start gap-6 ${
          workspaceOpen
            ? 'lg:grid-cols-2 2xl:grid-cols-[232px_minmax(0,1fr)_minmax(0,1fr)]'
            : 'lg:grid-cols-[232px_minmax(0,1fr)]'
        }`}
      >
        <aside
          class={`sticky top-5 max-h-[calc(100dvh-2.5rem)] min-h-0 flex-col ${
            workspaceOpen ? 'hidden 2xl:flex' : 'hidden lg:flex'
          }`}
        >
          <ChatList {chats} onselect={selectChat} />
        </aside>

        <section class={`flex min-w-0 flex-col gap-4 ${workspaceOpen ? '' : 'mx-auto w-full max-w-3xl'}`}>
          <div class="flex flex-wrap items-center gap-2">
            <div class={workspaceOpen ? '2xl:hidden' : 'lg:hidden'}>
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
            <SourcePicker
              {sources}
              selected={chats.active?.source_ids ?? null}
              disabled={chats.sending}
              onchange={setSources}
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
            onopenworkspace={openWorkspace}
          />
        </section>

        {#if workspaceOpen}
          <div bind:this={workspaceRef} class="min-w-0 scroll-mt-20 lg:sticky lg:top-5 lg:h-[calc(100dvh-2.5rem)]">
            <WorkspacePanel
              {canvas}
              sourcesFor={(turnIndex) => chats.turns[turnIndex]?.citations ?? []}
              onclose={() => canvas.hide()}
              onfollowup={(text) => thread?.prefill(text)}
              onsave={saveToArtifacts}
            />
          </div>
        {/if}
      </div>
    {:else if activeTab === 'artifacts'}
      <ArtifactsPanel {courseId} {artifacts} loading={artifactsLoading} />
    {:else}
      <SourcesPanel {courseId} {sources} onchanged={loadSources} />
    {/if}
  </div>
{/if}
