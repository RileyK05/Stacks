<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api/client';
  import type { paths } from '$lib/api/schema';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon, { type IconName } from '$lib/components/Icon.svelte';
  import Monogram from '$lib/components/Monogram.svelte';
  import RichText from '$lib/components/RichText.svelte';
  import Select from '$lib/components/Select.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Spinner from '$lib/components/Spinner.svelte';
  import WorkspacePanel from '$lib/components/WorkspacePanel.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { itemTitle, openSession, WorkspaceCanvas, type WorkspaceSession } from '$lib/stores/workspace.svelte';
  import { formatBytes } from '$lib/utils/format';
  import { humanize, plural } from '$lib/utils/labels';

  type CourseView =
    paths['/courses/{course_id}']['get']['responses'][200]['content']['application/json'];
  type SourceView =
    paths['/courses/{course_id}/sources']['get']['responses'][200]['content']['application/json'][number];
  type Citation =
    paths['/courses/{course_id}/traces/{trace_id}/citations']['get']['responses'][200]['content']['application/json'][number];
  type SourceType = NonNullable<
    paths['/courses/{course_id}/sources']['post']['requestBody']
  >['content']['multipart/form-data']['source_type'];
  type UploadBody = NonNullable<
    paths['/courses/{course_id}/sources']['post']['requestBody']
  >['content']['multipart/form-data'];

  interface Turn {
    question: string;
    /** Chat body: the answer with workspace blocks lifted out server-side. */
    answer: string | null;
    /** Cited quizzes/documents that passed the backend gate, with live state. */
    workspace: WorkspaceSession[];
    /** Why any generated workspace block was withheld (uncited, malformed). */
    withheld: string[];
    traceId: string | null;
    /** A rate-limited cloud model handed this answer to the local model. */
    fellBackToLocal: boolean;
    /** Answered by the Settings → "Bigger model" choice, at the user's request. */
    bigger: boolean;
    model: string;
    citations: Citation[];
    citationsLoading: boolean;
    error: unknown;
    showSources: boolean;
  }

  const courseId = page.params.id ?? '';
  const QUESTION_MAX_LENGTH = 2000;

  let course = $state<CourseView | null>(null);
  let sources = $state<SourceView[]>([]);
  let loading = $state(true);
  let error = $state<unknown>(null);
  let actionError = $state<unknown>(null);

  let activeTab = $state<'ask' | 'sources'>('ask');
  let renaming = $state(false);
  let renameValue = $state('');

  let question = $state('');
  let asking = $state(false);
  let turns = $state<Turn[]>([]);
  /** The model behind "Ask a bigger model"; null hides the button. */
  let biggerModel = $state<string | null>(null);
  let sessionRef = $state<HTMLElement | null>(null);
  let workspaceRef = $state<HTMLElement | null>(null);
  /** Right-hand workspace canvas: tabs accumulate across turns. */
  const canvas = new WorkspaceCanvas();
  let workspaceOpen = $derived(canvas.open);

  let sourceType = $state<SourceType>('notes');
  let uploading = $state(false);
  let uploadError = $state<unknown>(null);
  let dragOver = $state(false);
  let fileInput = $state<HTMLInputElement | null>(null);

  const sourceTypeOptions = [
    'syllabus',
    'slides',
    'textbook',
    'problem_set',
    'solutions',
    'notes',
    'feedback',
    'exam',
    'video',
    'audio',
    'code'
  ].map((value) => ({ value: value as SourceType, label: humanize(value) }));

  let anyPending = $derived(
    sources.some((source) => source.status === 'uploaded' || source.status === 'scanned')
  );

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
      await loadExtras();
    } finally {
      loading = false;
    }
  }

  async function loadExtras() {
    if (!course) return;
    const res = await api.GET('/courses/{course_id}/sources', {
      params: { path: { course_id: courseId } }
    });
    if (res.error) throw res.error;
    sources = res.data ?? [];
    void pollSourcesUntilSettled();
    void loadBiggerModel();
  }

  async function loadBiggerModel() {
    try {
      const { data } = await api.GET('/settings/providers');
      biggerModel = data?.resolved.bigger?.model ?? null;
    } catch {
      biggerModel = null;
    }
  }

  let polling = false;

  async function pollSourcesUntilSettled() {
    // Fresh uploads sit at uploaded→scanned→indexed invisibly otherwise
    // (the worker heartbeats; the UI just has to look). Poll every
    // 1.5s while anything is in flight; stop when all settle. One loop
    // at a time. No polling after an error — Retry is the recovery path.
    if (polling) return;
    polling = true;
    try {
      await pollLoop();
    } finally {
      polling = false;
    }
  }

  async function pollLoop() {
    // A laptop may take minutes on a large PDF: poll for up to ~15 min.
    for (let attempt = 0; attempt < 600 && anyPending; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      if (!course) return;
      try {
        const res = await api.GET('/courses/{course_id}/sources', {
          params: { path: { course_id: courseId } }
        });
        if (res.data) sources = res.data;
      } catch {
        return;
      }
    }
  }

  async function ask(event: SubmitEvent) {
    event.preventDefault();
    const text = question;
    question = '';
    await submit(text, false);
  }

  async function submit(text: string, bigger: boolean) {
    asking = true;
    const turn: Turn = {
      question: text,
      answer: null,
      workspace: [],
      withheld: [],
      traceId: null,
      fellBackToLocal: false,
      bigger,
      model: '',
      citations: [],
      citationsLoading: false,
      error: null,
      showSources: true
    };
    turns = [...turns, turn];
    const index = turns.length - 1;
    try {
      const { data, error: err } = await api.POST('/courses/{course_id}/ask', {
        params: { path: { course_id: courseId } },
        body: { question: turn.question, bigger_model: bigger }
      });
      if (!data) throw err ?? new Error('unexpected empty response');
      turns[index].answer = data.text;
      turns[index].workspace = (data.workspace ?? []).map(openSession);
      turns[index].withheld = data.withheld ?? [];
      canvas.openFromTurn(index, turns[index].workspace);
      turns[index].traceId = data.trace_id;
      turns[index].fellBackToLocal = data.fell_back_to_local ?? false;
      turns[index].model = data.model ?? '';
      // Fetch the evidence behind the answer immediately (golden rule
      // 1: every answer shows its sources, right under itself).
      turns[index].citationsLoading = true;
      try {
        const cited = await api.GET('/courses/{course_id}/traces/{trace_id}/citations', {
          params: { path: { course_id: courseId, trace_id: data.trace_id } }
        });
        turns[index].citations = cited.data ?? [];
      } finally {
        turns[index].citationsLoading = false;
      }
    } catch (caught) {
      turns[index].error = caught;
    } finally {
      asking = false;
      await tick();
      sessionRef?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }

  function clearSession() {
    turns = [];
    canvas.clear();
  }

  const starterPrompts: { text: string; icon: IconName }[] = [
    { text: 'Summarize the main ideas so far', icon: 'book' },
    { text: 'Quiz me with a few multiple-choice questions', icon: 'list-checks' },
    { text: 'Make me an editable study guide', icon: 'file-pen' }
  ];

  const tabs: { id: typeof activeTab; label: string; icon: IconName }[] = [
    { id: 'ask', label: 'Ask', icon: 'sparkles' },
    { id: 'sources', label: 'Sources', icon: 'file-text' }
  ];

  const upcoming: { label: string; icon: IconName }[] = [
    { label: 'Probe', icon: 'target' },
    { label: 'Progress', icon: 'trending-up' },
    { label: 'Artifacts', icon: 'package' }
  ];

  function onFilePicked() {
    const file = fileInput?.files?.[0];
    if (file) void uploadFile(file);
  }

  async function openWorkspace(index: number) {
    canvas.openFromTurn(index, turns[index].workspace);
    await tick();
    // Side-by-side on wide screens (already visible); stacked below the
    // chat on narrow ones, where the reader has to be taken to it.
    workspaceRef?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  async function askFollowUp(text: string) {
    question = text.slice(0, QUESTION_MAX_LENGTH);
    await tick();
    const input = document.getElementById('question');
    input?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    input?.focus();
  }

  async function uploadFile(file: File) {
    uploading = true;
    uploadError = null;
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('source_type', sourceType);
      const { error: err } = await api.POST('/courses/{course_id}/sources', {
        params: { path: { course_id: courseId } },
        body: form as unknown as UploadBody
      });
      if (err) throw err;
      if (fileInput) fileInput.value = '';
      await loadExtras();
    } catch (caught) {
      uploadError = caught;
    } finally {
      uploading = false;
    }
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    dragOver = false;
    const file = event.dataTransfer?.files?.[0];
    if (file) void uploadFile(file);
  }

  async function requeue(sourceId: string) {
    actionError = null;
    try {
      const { error: err } = await api.POST('/courses/{course_id}/sources/{source_id}/requeue', {
        params: { path: { course_id: courseId, source_id: sourceId } }
      });
      if (err) throw err;
      await loadExtras();
    } catch (caught) {
      actionError = caught;
    }
  }

  async function removeSource(sourceId: string, filename: string) {
    if (!(await confirmDialog({
      title: 'Remove this file?',
      message: `${filename} and everything derived from it (search index, citations) are deleted from this computer.`,
      confirmLabel: 'Remove',
      danger: true
    }))) return;
    actionError = null;
    try {
      const { error: err } = await api.DELETE('/courses/{course_id}/sources/{source_id}', {
        params: { path: { course_id: courseId, source_id: sourceId } }
      });
      if (err) throw err;
      await loadExtras();
      toast('File removed.');
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
    if (!(await confirmDialog({
      title: 'Move this course to the trash?',
      message: 'You can restore it from Trash for 30 days. After that it is deleted permanently.',
      confirmLabel: 'Move to trash',
      danger: true
    }))) return;
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
</script>

{#if error}
  <ErrorBanner {error} />
{:else if loading || !course}
  <div class="flex flex-col gap-6">
    <div class="flex items-center gap-4">
      <Skeleton class="h-14 w-14 rounded-2xl" />
      <div class="flex flex-col gap-2"><Skeleton class="h-8 w-72" /><Skeleton class="h-4 w-48" /></div>
    </div>
    <Skeleton class="h-10 w-full" />
    <Skeleton class="h-64 w-full rounded-2xl" />
  </div>
{:else}
  <div class="flex flex-col gap-6">
    <header class="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
      <div class="flex min-w-0 items-start gap-4">
        <Monogram name={course.name} size="lg" class="hidden sm:flex" />
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
            <h1 class="font-display text-[1.75rem] font-medium leading-tight tracking-tight text-fg sm:text-[2rem]">
              {course.name}
            </h1>
          {/if}
          <div class="mt-2.5 flex flex-wrap items-center gap-2">
            <span class="text-[13px] text-subtle">
              {plural(course.source_count, 'source')} · {formatBytes(course.stored_bytes ?? 0)} stored
            </span>
          </div>
        </div>
      </div>
      <div class="flex shrink-0 flex-wrap items-center gap-1">
        {#each upcoming as item (item.label)}
          <a
            href={`/courses/${courseId}/${item.label.toLowerCase()}`}
            class="hidden items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg sm:inline-flex"
          >
            <Icon name={item.icon} class="h-4 w-4 text-subtle" />
            {item.label}
            <span class="rounded bg-surface-3 px-1 py-px text-[10px] font-semibold uppercase tracking-wide text-subtle">Soon</span>
          </a>
        {/each}
        <Button variant="ghost" size="sm" onclick={startRename}>
          <Icon name="file-pen" class="h-4 w-4" /> Rename
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
              activeTab === tab
                ? 'border-accent text-fg'
                : 'border-transparent text-muted hover:border-line-strong hover:text-fg'
            }`}
          >
            <Icon name={icon} class={`h-4 w-4 ${activeTab === tab ? 'text-accent-text' : 'text-subtle'}`} />
            {label}
            {#if tab === 'sources'}
              <span class="rounded-full bg-surface-3 px-1.5 text-[11px] font-semibold text-muted">{sources.length}</span>
              {#if anyPending}
                <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-warning" title="Indexing in progress"></span>
              {/if}
            {/if}
          </button>
        {/each}
    </div>

    {#if activeTab === 'ask'}
      <div class={`grid items-start gap-6 ${workspaceOpen ? 'lg:grid-cols-2' : ''}`}>
        <div class={`flex min-w-0 flex-col ${workspaceOpen ? '' : 'mx-auto w-full max-w-3xl'}`}>
          {#if turns.length === 0}
            <div class="flex flex-col items-center rounded-2xl border border-line bg-surface px-6 py-10 text-center shadow-card sm:px-10 sm:py-14">
              <span class="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-soft text-accent-text ring-1 ring-accent-line/50">
                <Icon name="sparkles" class="h-6 w-6" />
              </span>
              <h2 class="mt-5 font-display text-2xl font-medium tracking-tight text-fg">
                What do you want to learn?
              </h2>
              <p class="mt-2 max-w-md text-[15px] leading-relaxed text-muted">
                Answers cite the exact material they came from. Ask for a quiz or a study guide
                and it opens in the workspace beside the chat.
              </p>
              <div class="mt-8 grid w-full gap-2.5 sm:grid-cols-3">
                {#each starterPrompts as starter (starter.text)}
                  <button
                    type="button"
                    onclick={() => askFollowUp(starter.text)}
                    class="group flex flex-col items-start gap-2.5 rounded-xl border border-line bg-bg/60 p-3.5 text-left text-[13px] font-medium leading-snug text-fg-soft transition-all hover:-translate-y-px hover:border-accent-line hover:bg-surface hover:shadow-card"
                  >
                    <Icon name={starter.icon} class="h-4 w-4 text-subtle transition-colors group-hover:text-accent-text" />
                    {starter.text}
                  </button>
                {/each}
              </div>
            </div>
          {:else}
            <div class="mb-4 flex items-center justify-between text-xs text-subtle">
              <span>{plural(turns.length, 'question')} this session (kept in this browser)</span>
              <Button variant="ghost" size="sm" onclick={clearSession}>
                <Icon name="rotate-ccw" class="h-3.5 w-3.5" /> Clear session
              </Button>
            </div>
            <div bind:this={sessionRef} class="flex scroll-mb-40 flex-col gap-8">
              {#each turns as turn, index (index)}
                <article class="flex animate-rise flex-col gap-4">
                  <div class="flex justify-end">
                    <p class="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tr-md bg-accent-soft px-4 py-2.5 text-[15px] leading-relaxed text-fg">
                      {turn.question}
                    </p>
                  </div>

                  <div class="flex gap-3">
                    <span
                      class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent text-on-accent shadow-card"
                      aria-hidden="true"
                    >
                      <Icon name="sparkles" class="h-4 w-4" />
                    </span>
                    <div class="flex min-w-0 flex-1 flex-col gap-3">
                      {#if turn.error}
                        <ErrorBanner error={turn.error} />
                      {:else if turn.answer === null}
                        <div class="flex items-center gap-2.5 py-1 text-sm text-muted">
                          <span class="flex gap-1" aria-hidden="true">
                            <span class="h-1.5 w-1.5 animate-bounce rounded-full bg-accent [animation-delay:-0.3s]"></span>
                            <span class="h-1.5 w-1.5 animate-bounce rounded-full bg-accent [animation-delay:-0.15s]"></span>
                            <span class="h-1.5 w-1.5 animate-bounce rounded-full bg-accent"></span>
                          </span>
                          Reading your course material…
                        </div>
                      {:else}
                        {#if turn.answer}
                          <RichText text={turn.answer} class="prose-p:leading-relaxed text-[15px]" />
                        {/if}
                        {#if turn.fellBackToLocal}
                          <p class="inline-flex items-center gap-1.5 self-start rounded-lg bg-warning-soft px-2.5 py-1 text-xs text-warning-text">
                            <Icon name="info" class="h-3.5 w-3.5" />
                            The cloud model hit its rate limit, so the local model answered this one.
                          </p>
                        {/if}
                        {#if turn.bigger}
                          <p class="inline-flex items-center gap-1.5 self-start text-xs text-subtle">
                            <Icon name="cpu" class="h-3.5 w-3.5" /> Answered by the bigger model ({turn.model})
                          </p>
                        {:else if biggerModel && turn.answer}
                          <button
                            type="button"
                            class="inline-flex items-center gap-1.5 self-start rounded-lg px-2 py-1 text-xs font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg disabled:opacity-50"
                            disabled={asking}
                            onclick={() => submit(turn.question, true)}
                            title="Ask this question again with the bigger model chosen in Settings"
                          >
                            <Icon name="cpu" class="h-3.5 w-3.5" /> Ask a bigger model ({biggerModel})
                          </button>
                        {/if}

                        {#if turn.workspace.length > 0}
                          {@const showing = canvas.active?.turnIndex === index && workspaceOpen}
                          <button
                            type="button"
                            onclick={() => openWorkspace(index)}
                            class={`flex items-center gap-3 self-start rounded-xl border px-3 py-2.5 text-left transition-all ${
                              showing
                                ? 'border-accent-line bg-accent-soft'
                                : 'border-line bg-surface shadow-card hover:border-accent-line hover:shadow-lift'
                            }`}
                          >
                            <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-soft text-accent-text">
                              <Icon name="panel-right" class="h-4 w-4" />
                            </span>
                            <span class="min-w-0">
                              <span class="block text-[13px] font-semibold text-fg">
                                {showing ? 'Showing in workspace' : 'Open in workspace'}
                              </span>
                              <span class="block truncate text-xs text-muted">
                                {turn.workspace.map((session) => itemTitle(session)).join(' · ')}
                              </span>
                            </span>
                            {#if !showing}<Icon name="arrow-right" class="ml-1 h-4 w-4 text-subtle" />{/if}
                          </button>
                        {/if}

                        {#each turn.withheld as reason, reasonIndex (reasonIndex)}
                          <p class="flex gap-2 rounded-xl border border-warning/30 bg-warning-soft px-3 py-2.5 text-xs leading-relaxed text-warning-text">
                            <Icon name="alert-triangle" class="mt-px h-3.5 w-3.5" />
                            <span>
                              The tutor generated something that is not shown because it could not be tied to
                              your course material: {reason}
                            </span>
                          </p>
                        {/each}

                        <div class="rounded-xl border border-line bg-surface">
                          <button
                            type="button"
                            class="flex w-full items-center gap-2 px-3.5 py-2.5 text-[13px] font-medium text-muted transition-colors hover:text-fg"
                            aria-expanded={turn.showSources}
                            onclick={() => (turn.showSources = !turn.showSources)}
                          >
                            <Icon name="bookmark" class="h-4 w-4 text-subtle" />
                            {#if turn.citationsLoading}
                              Finding sources… <Spinner class="h-3.5 w-3.5" />
                            {:else}
                              Sources used
                              <span class="rounded-full bg-surface-3 px-1.5 text-[11px] font-semibold">{turn.citations.length}</span>
                            {/if}
                            <Icon
                              name="chevron-down"
                              class={`ml-auto h-4 w-4 text-subtle transition-transform ${turn.showSources ? 'rotate-180' : ''}`}
                            />
                          </button>

                          {#if turn.showSources && turn.citations.length > 0}
                            <ol class="divide-y divide-line border-t border-line">
                              {#each turn.citations as citation, citeIndex (citation.chunk_id)}
                                <li class="px-3.5 py-3">
                                  <div class="flex min-w-0 items-center gap-2 text-xs">
                                    <span class="flex h-5 min-w-5 items-center justify-center rounded-md bg-accent-soft px-1 font-mono text-[11px] font-medium text-accent-text">
                                      {citeIndex + 1}
                                    </span>
                                    <span class="truncate font-medium text-fg-soft">{citation.filename}</span>
                                    <span class="shrink-0 text-subtle">{citation.label}</span>
                                  </div>
                                  {#if citation.description}
                                    <p class="mt-1.5 text-xs italic text-muted">{citation.description}</p>
                                  {/if}
                                  <p class="mt-2 border-l-2 border-line-strong pl-3 text-[13px] leading-relaxed text-muted">
                                    {citation.text}
                                  </p>
                                </li>
                              {/each}
                            </ol>
                          {/if}

                          {#if turn.showSources && turn.traceId && !turn.citationsLoading}
                            <p class="border-t border-line px-3.5 py-2 font-mono text-[10px] text-subtle">trace {turn.traceId}</p>
                          {/if}
                        </div>
                      {/if}
                    </div>
                  </div>
                </article>
              {/each}
            </div>
          {/if}

          <form
            onsubmit={ask}
            class="sticky bottom-0 z-10 mt-6 bg-gradient-to-t from-bg from-60% to-transparent pb-4 pt-4"
          >
            <label for="question" class="sr-only">Question</label>
            <div
              class="flex items-center gap-2 rounded-2xl border border-line-strong bg-surface p-1.5 pl-4 shadow-lift transition-[border-color,box-shadow] focus-within:border-accent focus-within:ring-3 focus-within:ring-accent/15"
            >
              <input
                id="question"
                bind:value={question}
                required
                maxlength={QUESTION_MAX_LENGTH}
                autocomplete="off"
                placeholder="Ask something, or say: quiz me on …"
                class="h-10 min-w-0 flex-1 bg-transparent text-[15px] text-fg placeholder:text-subtle focus:outline-none"
              />
              <button
                type="submit"
                disabled={asking || !question.trim()}
                aria-label="Ask"
                class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent text-on-accent transition-all hover:bg-accent-hover disabled:bg-surface-3 disabled:text-subtle"
              >
                {#if asking}<Spinner />{:else}<Icon name="arrow-up" class="h-[18px] w-[18px]" strokeWidth={2.25} />{/if}
              </button>
            </div>
            <p class="mt-2 px-1 text-center text-xs text-subtle">
              Answers cite the exact course material they came from.
            </p>
          </form>
        </div>

        {#if workspaceOpen}
          <div
            bind:this={workspaceRef}
            class="min-w-0 scroll-mt-20 lg:sticky lg:top-6 lg:h-[calc(100dvh-3rem)]"
          >
            <WorkspacePanel
              {canvas}
              sourcesFor={(turnIndex) => turns[turnIndex]?.citations ?? []}
              onclose={() => canvas.hide()}
              onfollowup={askFollowUp}
            />
          </div>
        {/if}
      </div>
    {:else if activeTab === 'sources'}
      <div class="flex flex-col gap-6">
        <Card title="Add material" description="Upload a syllabus, slides, notes, problem sets — anything the tutor should answer from.">
          <div class="flex flex-col gap-4 sm:flex-row sm:items-stretch">
            <div class="sm:w-52">
              <Select label="Source type" options={sourceTypeOptions} bind:value={sourceType} />
            </div>
            <div
              role="button"
              tabindex="0"
              aria-label="Upload a file"
              class={`flex flex-1 cursor-pointer items-center gap-4 rounded-xl border-2 border-dashed px-5 py-5 transition-colors ${
                dragOver
                  ? 'border-accent bg-accent-soft'
                  : 'border-line-strong hover:border-accent-line hover:bg-surface-2/60'
              }`}
              ondragover={(e) => {
                e.preventDefault();
                dragOver = true;
              }}
              ondragleave={() => (dragOver = false)}
              ondrop={onDrop}
              onclick={() => !uploading && fileInput?.click()}
              onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && !uploading && fileInput?.click()}
            >
              <span class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-surface-2 text-muted ring-1 ring-line">
                {#if uploading}<Spinner class="h-5 w-5" />{:else}<Icon name="upload-cloud" class="h-5 w-5" />{/if}
              </span>
              <div class="min-w-0">
                <p class="text-sm font-medium text-fg">
                  {#if uploading}
                    Uploading…
                  {:else}
                    Drop a file here, or <span class="text-accent-text underline underline-offset-2">browse</span>
                  {/if}
                </p>
                <p class="mt-0.5 text-xs text-subtle">PDF, Markdown, or plain text · indexed automatically</p>
              </div>
              <input bind:this={fileInput} type="file" class="hidden" onchange={onFilePicked} />
            </div>
          </div>
          {#if uploadError}<div class="mt-4"><ErrorBanner error={uploadError} /></div>{/if}
        </Card>

        {#if sources.length === 0}
          <EmptyState icon="file-text" title="No sources yet" message="Upload course material above and the tutor will start answering from it." />
        {:else}
          <section class="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
            <div class="flex items-center justify-between border-b border-line px-5 py-3.5 sm:px-6">
              <h2 class="text-[15px] font-semibold text-fg">Materials</h2>
              <span class="text-[13px] text-subtle">{plural(sources.length, 'file')}</span>
            </div>
            <ul class="divide-y divide-line">
              {#each sources as source (source.source_id)}
                {@const pending = source.status === 'uploaded' || source.status === 'scanned'}
                <li class="flex items-center gap-4 px-5 py-3.5 sm:px-6">
                  <span
                    class={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ring-1 ${
                      source.status === 'failed' ? 'bg-danger-soft text-danger-text ring-danger/20' : 'bg-surface-2 text-muted ring-line'
                    }`}
                  >
                    <Icon name="file-text" class="h-[18px] w-[18px]" />
                  </span>
                  <div class="min-w-0 flex-1">
                    <p class="truncate text-sm font-medium text-fg">{source.filename}</p>
                    <p class="mt-0.5 text-xs text-subtle">
                      {humanize(source.source_type)} · {formatBytes(source.size_bytes ?? 0)}
                    </p>
                    {#if source.error_message}
                      <p class="mt-1 text-xs text-danger-text">{source.error_message}</p>
                    {/if}
                  </div>
                  <div class="flex shrink-0 items-center gap-2">
                    {#if source.status === 'failed'}
                      <Button variant="secondary" size="sm" onclick={() => requeue(source.source_id)}>
                        <Icon name="refresh" class="h-3.5 w-3.5" /> Retry
                      </Button>
                    {/if}
                    {#if pending}
                      <Badge tone="info"><Spinner class="h-3 w-3" /> Indexing</Badge>
                    {:else if source.status === 'indexed'}
                      <Badge tone="success" dot>Indexed</Badge>
                    {:else if source.status === 'failed'}
                      <Badge tone="danger" dot>Failed</Badge>
                    {:else}
                      <Badge>{humanize(source.status)}</Badge>
                    {/if}
                    <button
                      type="button"
                      onclick={() => removeSource(source.source_id, source.filename)}
                      class="rounded-lg p-1.5 text-subtle transition-colors hover:bg-danger-soft hover:text-danger-text"
                      aria-label={`Remove ${source.filename}`}
                    >
                      <Icon name="trash" class="h-4 w-4" />
                    </button>
                  </div>
                </li>
              {/each}
            </ul>
          </section>
        {/if}
      </div>
    {/if}
  </div>
{/if}
