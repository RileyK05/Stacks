<script lang="ts">
  import { invoke, isTauri } from '@tauri-apps/api/core';
  import { onMount, tick } from 'svelte';
  import { api } from '$lib/api/client';
  import type { components, paths } from '$lib/api/schema';
  import Icon from '$lib/components/Icon.svelte';
  import RichText from '$lib/components/RichText.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { createBusyOwner } from '$lib/utils/busyOwner';

  type Course = paths['/courses']['get']['responses'][200]['content']['application/json'][number];
  type Work = components['schemas']['WorkSession'];
  type Summary = components['schemas']['WorkSummary'];
  type Document = components['schemas']['DocumentInput'];
  type Ask = components['schemas']['WorkAsk'];
  type Window = components['schemas']['CaptureWindow'];
  type Purpose = components['schemas']['WorkCreate']['purpose'];
  type Action = Ask['action'];

  let courses = $state<Course[]>([]);
  let courseId = $state('');
  let sessions = $state<Summary[]>([]);
  let work = $state<Work | null>(null);
  let question = $state('');
  let selection = $state('');
  let purpose = $state<Purpose>('paper');
  let title = $state('My paper');
  let pastedText = $state('');
  let documentTitle = $state('Working document');
  let connecting = $state(false);
  let busy = $state(false);
  const operationBusy = createBusyOwner((value) => { busy = value; });
  let loading = $state(true);
  let error = $state<unknown>(null);
  let pinned = $state(false);
  let windows = $state<Window[]>([]);
  let windowHandle = $state('');
  let pending = $state<Ask | null>(null);
  let epoch = 0;
  let disposed = false;
  let refreshing = false;
  let conversationEnd = $state<HTMLElement | null>(null);
  let fileInput = $state<HTMLInputElement | null>(null);
  let screenshotInput = $state<HTMLInputElement | null>(null);
  let documentRefreshing = $state(false);
  let refreshIssue = $state('');
  let usingSaved = $state(false);
  let composeChecked = false;
  let refreshGeneration = 0;
  let refreshPromise: Promise<boolean> | null = null;

  function resetLiveRefresh() {
    refreshGeneration++;
    refreshPromise = null; documentRefreshing = false; refreshIssue = '';
    usingSaved = false; composeChecked = false;
  }

  function composing(value: string) {
    if (value.trim() && !composeChecked && !pending && !busy) {
      void refreshDocument();
    }
  }

  async function refreshDocument(force = false): Promise<boolean> {
    if (refreshPromise) return refreshPromise;
    if (!work?.document || work.document.origin !== 'office' || pending) return true;
    if (!force && (usingSaved || composeChecked)) return usingSaved || !refreshIssue;
    const token = epoch, id = work.session_id, course = courseId;
    const generation = ++refreshGeneration;
    const valid = () => current(token) && generation === refreshGeneration && work?.session_id === id;
    composeChecked = true; usingSaved = false; refreshIssue = ''; documentRefreshing = true;
    const run = async () => {
      try {
        const settings = await api.GET('/companion/live-policy');
        if (!valid() || !settings.data) return false;
        const timeout = settings.data.refresh_timeout_seconds * 1000;
        const response = await api.POST('/companion/courses/{course_id}/work/{session_id}/refresh', {
          params: { path: { course_id: course, session_id: id } }, signal: AbortSignal.timeout(timeout)
        });
        if (!valid() || !response.data) return false;
        let result = response.data;
        const deadline = performance.now() + timeout;
        while (result.status === 'pending') {
          await new Promise(resolve => setTimeout(resolve, settings.data!.poll_interval_ms));
          if (!valid()) return false;
          if (performance.now() >= deadline) throw new Error('Document refresh timed out. Retry or use the saved snapshot.');
          const update = await api.GET('/companion/courses/{course_id}/work/{session_id}/refresh/{request_id}', {
            params: { path: { course_id: course, session_id: id, request_id: result.request_id } },
            signal: AbortSignal.timeout(Math.max(1, deadline - performance.now()))
          });
          if (!valid() || !update.data) return false;
          result = update.data;
        }
        if (result.status !== 'complete') throw new Error(result.error || 'Could not read the current Office document.');
        const updated = await api.GET('/companion/courses/{course_id}/work/{session_id}', { params: { path: { course_id: course, session_id: id } } });
        if (!valid() || !updated.data) return false;
        work = updated.data;
        if (selection && !work.document?.text.includes(selection.trim())) {
          throw new Error('The focused passage changed in the document. Update or clear that passage before asking.');
        }
        return true;
      } catch (caught) {
        if (valid()) refreshIssue = caught instanceof Error ? caught.message : String(caught);
        return false;
      } finally {
        if (valid()) { documentRefreshing = false; refreshPromise = null; }
      }
    };
    refreshPromise = run();
    return refreshPromise;
  }

  const actions: { id: Action; label: string }[] = [
    { id: 'review', label: 'Review draft' }, { id: 'find', label: 'Find references' },
    { id: 'revise', label: 'Suggest an edit' }, { id: 'explain', label: 'Explain' },
    { id: 'summarize', label: 'Summarize' }
  ];

  function readSaved(key: string): string | null {
    try { return localStorage.getItem(key); } catch { return null; }
  }
  function writeSaved(key: string, value: string): void {
    try { localStorage.setItem(key, value); } catch { }
  }
  function removeSaved(key: string): void {
    try { localStorage.removeItem(key); } catch { }
  }
  function current(token: number) { return !disposed && token === epoch; }
  const claimBusy = () => operationBusy.claim();
  const releaseBusy = (owner: number) => operationBusy.release(owner);
  const resetBusy = () => operationBusy.reset();
  function remember() {
    if (work) writeSaved(`companion-work:${courseId}`, work.session_id);
  }
  function pendingKey() { return `companion-request:${work?.session_id}`; }
  function restorePending() {
    try { pending = JSON.parse(readSaved(pendingKey()) ?? 'null'); }
    catch { pending = null; }
    if (pending && work?.turns.some(turn => turn.request_id === pending?.request_id)) {
      removeSaved(pendingKey());
      pending = null;
    }
  }

  onMount(() => {
    pinned = readSaved('companion-pinned') === 'true';
    if (isTauri()) void invoke('set_companion_pinned', { pinned }).catch(() => { pinned = false; });
    void initialize();
    const syncCourse = (event: StorageEvent) => {
      if (event.key === 'companion-course' && event.newValue && event.newValue !== courseId) {
        void changeCourse(event.newValue);
      }
    };
    const refresh = () => { if (!document.hidden) void refreshConnected(); };
    window.addEventListener('storage', syncCourse);
    window.addEventListener('focus', refresh);
    const timer = setInterval(refresh, 10000);
    return () => {
      disposed = true; epoch++;
      clearInterval(timer);
      window.removeEventListener('storage', syncCourse);
      window.removeEventListener('focus', refresh);
    };
  });

  async function initialize() {
    try {
      const response = await api.GET('/courses');
      courses = response.data ?? [];
      const wanted = readSaved('companion-course');
      await changeCourse(courses.some(c => c.course_id === wanted) ? wanted! : courses[0]?.course_id ?? '');
    } catch (caught) { error = caught; }
    finally { loading = false; }
  }

  async function changeCourse(id: string) {
    const token = ++epoch;
    resetLiveRefresh();
    courseId = id; work = null; sessions = []; question = ''; selection = ''; pending = null;
    connecting = false; pastedText = ''; resetBusy(); error = null;
    if (!id) return;
    writeSaved('companion-course', id);
    try {
      const response = await api.GET('/companion/courses/{course_id}/work', { params: { path: { course_id: id } } });
      if (!current(token)) return;
      sessions = response.data ?? [];
      const remembered = readSaved(`companion-work:${id}`);
      const chosen = sessions.find(s => s.session_id === remembered) ?? sessions[0];
      if (chosen) await openSession(chosen.session_id);
    } catch (caught) { if (current(token)) error = caught; }
  }

  async function openSession(id: string) {
    const token = ++epoch;
    resetLiveRefresh();
    work = null; question = ''; selection = ''; pending = null; error = null; resetBusy();
    connecting = false; pastedText = '';
    try {
      const response = await api.GET('/companion/courses/{course_id}/work/{session_id}', { params: { path: { course_id: courseId, session_id: id } } });
      if (!current(token)) return;
      work = response.data ?? null; remember(); restorePending();
    } catch (caught) { if (current(token)) error = caught; }
  }

  async function refreshConnected() {
    if (busy || documentRefreshing || loading || refreshing || disposed) return;
    refreshing = true;
    const token = epoch;
    try {
      const response = await api.GET('/courses');
      if (!current(token)) return;
      courses = response.data ?? [];
      if (!courses.some(c => c.course_id === courseId)) { await changeCourse(courses[0]?.course_id ?? ''); return; }
      const list = await api.GET('/companion/courses/{course_id}/work', { params: { path: { course_id: courseId } } });
      if (!current(token)) return;
      sessions = list.data ?? [];
      const latest = sessions.find(s => s.session_id === work?.session_id);
      if (work && !latest) { resetLiveRefresh(); work = null; pending = null; }
      else if (work && latest?.updated_at !== work.updated_at) {
        const response = await api.GET('/companion/courses/{course_id}/work/{session_id}', { params: { path: { course_id: courseId, session_id: work.session_id } } });
        if (current(token) && response.data && response.data.revision >= (work?.revision ?? 0)) { work = response.data; selection = ''; }
      }
    } catch (caught) { if (current(token)) error = caught; }
    finally { refreshing = false; }
  }

  async function createSession() {
    if (!title.trim() || !courseId || busy) return;
    const token = epoch, owner = claimBusy();
    error = null;
    try {
      const response = await api.POST('/companion/courses/{course_id}/work', {
        params: { path: { course_id: courseId } }, body: { title: title.trim(), purpose }
      });
      if (current(token) && response.data) {
        work = response.data; sessions = [response.data, ...sessions]; question = ''; selection = '';
        pending = null; connecting = true; remember();
      }
    } catch (caught) { if (current(token)) error = caught; }
    finally { releaseBusy(owner); }
  }

  async function connectDocument(doc: Document) {
    if (!work) return;
    const response = await api.PUT('/companion/courses/{course_id}/work/{session_id}/document', {
      params: { path: { course_id: courseId, session_id: work.session_id } },
      body: { ...doc, expected_revision: work.revision }
    });
    return response.data;
  }

  async function operation(task: () => Promise<Work | null | undefined>) {
    if (busy || pending) return;
    const token = epoch, owner = claimBusy();
    error = null;
    try {
      const updated = await task();
      if (current(token) && updated) { work = updated; connecting = false; pastedText = ''; selection = ''; resetLiveRefresh(); remember(); }
    } catch (caught) { if (current(token)) error = caught; }
    finally { releaseBusy(owner); }
  }

  async function upload(file: File) {
    await operation(async () => {
      if (!work) return;
      const body = new FormData(); body.append('file', file); body.append('expected_revision', String(work.revision));
      const response = await api.POST('/companion/courses/{course_id}/work/{session_id}/file', {
        params: { path: { course_id: courseId, session_id: work.session_id } },
        body: body as never, bodySerializer: value => value as unknown as FormData
      });
      return response.data;
    });
  }

  async function uploadScreenshot(file: File) {
    await operation(async () => {
      if (!work) return;
      const body = new FormData(); body.append('file', file); body.append('expected_revision', String(work.revision));
      const response = await api.POST('/companion/courses/{course_id}/work/{session_id}/screenshot', {
        params: { path: { course_id: courseId, session_id: work.session_id } },
        body: body as never, bodySerializer: value => value as unknown as FormData
      });
      return response.data;
    });
  }

  async function loadWindows() {
    const token = epoch; error = null;
    try {
      const response = await api.GET('/companion/windows');
      if (current(token)) { windows = response.data ?? []; windowHandle = String(windows[0]?.handle ?? ''); }
    } catch (caught) { if (current(token)) error = caught; }
  }

  async function readWindow() {
    const selected = windows.find(w => String(w.handle) === windowHandle);
    if (!selected) return;
    const targetCourse = courseId, targetSession = work?.session_id, revision = work?.revision;
    await operation(async () => {
      const capture = await api.POST('/companion/capture', { body: selected });
      if (!capture.data || targetCourse !== courseId || targetSession !== work?.session_id || revision !== work?.revision) return;
      return connectDocument(capture.data);
    });
  }

  async function ask(action: Action = 'review') {
    if (!work?.document || busy) return;
    const token = epoch, id = work.session_id, course = courseId, owner = claimBusy();
    error = null;
    try {
      if (!pending && !(await refreshDocument())) return;
      if (!current(token) || work?.session_id !== id) return;
      const request: Ask = pending ?? { request_id: crypto.randomUUID(), action, instruction: question.trim(), selection: selection.trim(), expected_revision: work.revision };
      pending = request;
      writeSaved(pendingKey(), JSON.stringify(request));
      await api.POST('/companion/courses/{course_id}/work/{session_id}/ask', { params: { path: { course_id: course, session_id: id } }, body: request });
      removeSaved(`companion-request:${id}`);
      if (!current(token)) return;
      pending = null; question = ''; resetLiveRefresh();
      const response = await api.GET('/companion/courses/{course_id}/work/{session_id}', { params: { path: { course_id: course, session_id: id } } });
      if (current(token) && response.data) {
        work = response.data;
        await tick();
        if (current(token)) conversationEnd?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    } catch (caught) { if (current(token)) error = caught; }
    finally { releaseBusy(owner); }
  }

  async function removeSession() {
    if (!work || busy) return;
    const id = work.session_id, course = courseId, token = epoch;
    if (!(await confirmDialog({ title: 'Delete this work session?', message: 'Its document snapshots and conversations will be removed. Your course sources and learning memory stay intact.', confirmLabel: 'Delete session', danger: true }))) return;
    if (!current(token) || courseId !== course || work?.session_id !== id || busy) return;
    const owner = claimBusy();
    try {
      await api.DELETE('/companion/courses/{course_id}/work/{session_id}', { params: { path: { course_id: course, session_id: id } } });
      if (current(token)) { resetLiveRefresh(); work = null; pending = null; sessions = sessions.filter(s => s.session_id !== id); }
      removeSaved(`companion-request:${id}`);
    } catch (caught) { if (current(token)) error = caught; }
    finally { releaseBusy(owner); }
  }

  async function togglePin() {
    const next = !pinned;
    try { if (isTauri()) await invoke('set_companion_pinned', { pinned: next }); pinned = next; writeSaved('companion-pinned', String(next)); }
    catch (caught) { error = caught; }
  }
  async function showLibrary() {
    try { if (isTauri()) await invoke('show_library'); else window.open('/', '_blank', 'noopener,noreferrer'); }
    catch (caught) { error = caught; }
  }
  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); }
    catch { error = new Error('Could not copy. Select the passage and copy it manually.'); }
  }
</script>

<div class="flex h-dvh flex-col overflow-hidden bg-bg">
  <header class="flex h-14 shrink-0 items-center gap-2 border-b border-line bg-surface px-3">
    <span class="font-display text-lg font-semibold">Stacks companion</span>
    <div class="flex-1"></div>
    <button type="button" onclick={togglePin} aria-pressed={pinned} aria-label="Keep companion on top" class="rounded-lg p-2 hover:bg-surface-2"><Icon name="pin" class="h-4 w-4" /></button>
    <button type="button" onclick={showLibrary} aria-label="Open library" class="rounded-lg p-2 hover:bg-surface-2"><Icon name="book" class="h-4 w-4" /></button>
  </header>
  <main class="min-h-0 flex-1 overflow-y-auto p-3 space-y-4">
    {#if error}<ErrorBanner {error} />{/if}
    {#if loading}<p class="text-sm text-muted">Connecting to Stacks…</p>
    {:else if courses.length === 0}<p class="text-sm text-muted">Create a course in the library to connect your work.</p><button type="button" onclick={showLibrary}>Open library</button>
    {:else}
      <label class="block text-xs text-muted">Course
        <select aria-label="Course" value={courseId} onchange={e => changeCourse(e.currentTarget.value)} class="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-sm text-fg">
          {#each courses as course}<option value={course.course_id}>{course.name} · {course.source_count} sources</option>{/each}
        </select>
      </label>
      <div class="flex items-center gap-2">
        <select aria-label="Work session" value={work?.session_id ?? ''} onchange={e => { if (e.currentTarget.value) void openSession(e.currentTarget.value); else { epoch++; resetLiveRefresh(); work = null; question = ''; selection = ''; pending = null; resetBusy(); } }} class="min-w-0 flex-1 rounded-lg border border-line bg-surface p-2 text-sm">
          <option value="">New work session</option>
          {#each sessions as session}<option value={session.session_id}>{session.title} · {session.purpose}</option>{/each}
        </select>
        <button type="button" onclick={refreshConnected} disabled={busy} aria-label="Refresh Stacks connection" class="p-2"><Icon name="refresh" class="h-4 w-4" /></button>
      </div>
      {#if !work}
        <div class="space-y-2 rounded-xl border border-line bg-surface p-3">
          <input aria-label="Session title" bind:value={title} maxlength="300" placeholder="Name this work" class="w-full rounded-lg border border-line bg-bg p-2 text-sm" />
          <label class="block text-xs text-muted">Working on
            <select aria-label="Work purpose" bind:value={purpose} class="mt-1 w-full rounded-lg border border-line bg-bg p-2 text-sm"><option value="paper">Paper or assignment draft</option><option value="slides">Slides</option><option value="practice">Practice material</option><option value="reference">Reading or reference</option></select>
          </label>
          <button type="button" onclick={createSession} disabled={busy || !title.trim()} class="rounded-lg bg-accent px-3 py-2 text-sm text-on-accent">Start work session</button>
        </div>
      {:else}
        <div class="rounded-xl border border-line bg-surface p-3 space-y-2">
          <div class="flex items-start gap-2"><div class="min-w-0 flex-1"><h1 class="font-medium truncate">{work.title}</h1><p class="text-xs text-muted">{work.purpose} · {work.document ? `Snapshot ${work.revision}` : 'No document connected'}</p></div><button type="button" onclick={removeSession} disabled={busy} aria-label="Delete work session" class="p-1 text-subtle"><Icon name="trash" class="h-4 w-4" /></button></div>
          {#if work.document}
            <p class="text-sm truncate">{work.document.title}</p>
            <p class="text-xs text-muted">{work.document.text.length.toLocaleString()} characters · {work.document.coverage === 'document' ? 'Document text' : 'Partial or unverified capture'} · {new Date(work.document.captured_at).toLocaleString()}</p>
            {#each work.document.warnings as warning}<p class="text-xs text-warning-text">{warning}</p>{/each}
            <details><summary class="cursor-pointer text-xs text-accent-text">Inspect connected text</summary><pre class="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap text-xs text-muted">{work.document.text}</pre></details>
            {#if work.document.origin === 'office'}<button type="button" onclick={() => refreshDocument(true)} disabled={busy || !!pending || documentRefreshing} class="text-xs font-medium text-accent-text">Refresh from Office</button><p class="text-xs text-muted">Keep the connected Office pane open. Starting a message reads the latest document.</p>{/if}
          {/if}
          <button type="button" onclick={() => connecting = !connecting} disabled={busy || !!pending} class="text-xs font-medium text-accent-text">{connecting ? 'Close document connection' : work.document ? 'Refresh or connect another snapshot' : 'Connect your document'}</button>
        </div>
        {#if connecting}
          <div class="space-y-3 rounded-xl border border-line bg-surface p-3">
            <p class="text-xs text-muted">Connect a document file, pasted text, or an Office pane. Office connections refresh when you start a message.</p>
            <input bind:this={fileInput} type="file" accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.csv" class="hidden" onchange={e => { const file = e.currentTarget.files?.[0]; if (file) void upload(file); e.currentTarget.value = ''; }} />
            <button type="button" onclick={() => fileInput?.click()} disabled={busy} class="rounded-lg border border-line px-3 py-2 text-sm">Connect file</button>
            <button type="button" onclick={loadWindows} disabled={busy} class="ml-2 rounded-lg border border-line px-3 py-2 text-sm">Choose window</button>
            <input bind:this={screenshotInput} type="file" accept=".png,.jpg,.jpeg" class="hidden" onchange={e => { const file = e.currentTarget.files?.[0]; if (file) void uploadScreenshot(file); e.currentTarget.value = ''; }} />
            <button type="button" onclick={() => screenshotInput?.click()} disabled={busy} class="rounded-lg border border-line px-3 py-2 text-sm">Connect screenshot</button>
            <p class="text-xs text-muted">Screenshot fallback works on Windows and Mac with an image-capable model. Only visible text in the uploaded image is captured.</p>
            {#if windows.length}
              <select aria-label="Window to read" bind:value={windowHandle} class="w-full rounded-lg border border-line bg-bg p-2 text-sm">{#each windows as window}<option value={String(window.handle)}>{window.title}</option>{/each}</select>
              <button type="button" onclick={readWindow} disabled={busy} class="rounded-lg bg-accent px-3 py-2 text-sm text-on-accent">Read selected window</button>
              <p class="text-xs text-muted">Reads application text; falls back to visible-screen OCR when needed. Off-screen pages may require a file or Office connection.</p>
            {/if}
            <details><summary class="cursor-pointer text-xs text-accent-text">Paste whole document</summary><div class="mt-2 space-y-2"><input aria-label="Document title" bind:value={documentTitle} maxlength="300" class="w-full rounded-lg border border-line bg-bg p-2 text-sm" /><textarea aria-label="Whole document text" bind:value={pastedText} rows="6" maxlength="300000" class="w-full rounded-lg border border-line bg-bg p-2 text-sm"></textarea><button type="button" disabled={busy || !pastedText.trim()} onclick={() => operation(() => connectDocument({ title: documentTitle, text: pastedText, origin: 'paste', coverage: 'unknown', warnings: [], external_id: '' }))} class="rounded-lg bg-accent px-3 py-2 text-sm text-on-accent">Connect pasted document</button></div></details>
            <p class="text-xs text-muted">In the Office task pane, use “Connect whole document to companion” and keep that pane open. For Google Docs, Sheets, and Slides, connect an exported DOCX, XLSX, PPTX, or PDF.</p>
          </div>
        {/if}
        <p class="text-[11px] text-subtle">Saved with this work session. Documents and review feedback do not update learning memory or test scores.</p>
        {#each work.turns as turn (turn.request_id)}
          <article class="space-y-2">
            <p class="ml-8 rounded-xl bg-accent p-3 text-sm text-on-accent">{turn.instruction || actions.find(a => a.id === turn.action)?.label}</p>
            <div class="rounded-xl border border-line bg-surface p-3 space-y-3">
              <RichText text={turn.reply.text} />
              <p class="text-[11px] text-muted">Based on snapshot {turn.document_revision} · {turn.reply.coverage.complete ? turn.action === 'find' ? 'Course passage lookup' : 'All captured text supplied' : `Sections ${turn.reply.coverage.included_sections.join(', ')} of ${turn.reply.coverage.total_sections} supplied`}</p>
              <button type="button" onclick={() => copy(turn.reply.text)} class="text-xs text-accent-text">Copy response</button>
              {#if turn.reply.proposed_edit}<button type="button" onclick={() => copy(turn.reply.proposed_edit!.replacement)} class="ml-3 text-xs text-accent-text">Copy proposed replacement</button>{/if}
              {#if turn.reply.citations.length}<details><summary class="cursor-pointer text-xs text-accent-text">Inspect references ({turn.reply.citations.length})</summary><div class="mt-2 space-y-3">{#each turn.reply.citations as citation}<div class="rounded-lg bg-surface-2 p-2 text-xs"><p class="font-medium">[{citation.number}] {citation.filename} · {citation.label}</p>{#if !citation.source_id}<p class="mt-1 text-muted">Archived passage · source no longer connected</p>{/if}<p class="mt-1 whitespace-pre-wrap">{citation.text}</p><button type="button" onclick={() => copy(citation.text)} class="mt-2 text-accent-text">Copy exact passage</button></div>{/each}</div></details>{/if}
            </div>
          </article>
        {/each}
        <div bind:this={conversationEnd}></div>
        {#if busy}<p class="text-sm text-muted" role="status">Working…</p>{/if}
      {/if}
    {/if}
  </main>
  {#if work?.document}
    <form onsubmit={e => { e.preventDefault(); void ask(); }} class="shrink-0 border-t border-line bg-surface p-3 space-y-2">
      {#if documentRefreshing}<p class="text-xs text-muted" role="status">Reading the current Office document…</p>{/if}
      {#if refreshIssue}<p class="text-xs text-warning-text" role="status">{refreshIssue}</p><div class="flex gap-3"><button type="button" onclick={() => refreshDocument(true)} disabled={busy || documentRefreshing || !!pending} class="text-xs text-accent-text">Retry document refresh</button><button type="button" onclick={() => { usingSaved = true; refreshIssue = ''; }} disabled={busy || documentRefreshing || !!pending} class="text-xs text-muted">Use saved snapshot {work.revision}</button></div>{/if}
      {#if usingSaved}<p class="text-xs text-warning-text">Using saved snapshot {work.revision}; newer Office changes may be missing.</p>{/if}
      {#if pending}<p class="text-xs text-warning-text">{busy ? 'Saving this request and its response…' : 'This request was not confirmed. Retry it, or clear it to ask something else.'}</p><div class="flex gap-3"><button type="button" onclick={() => ask()} disabled={busy} class="text-xs text-accent-text">Retry request</button><button type="button" disabled={busy} onclick={() => { removeSaved(pendingKey()); question = pending?.instruction ?? question; selection = ''; pending = null; }} class="text-xs text-muted">Clear pending request</button></div>{/if}
      <details><summary class="text-xs text-muted cursor-pointer">Focus on a passage</summary><textarea aria-label="Selected passage from document" maxlength="4000" bind:value={selection} oninput={e => composing(e.currentTarget.value)} disabled={busy || !!pending} rows="2" placeholder="Paste an exact passage from the connected snapshot" class="mt-2 w-full rounded-lg border border-line bg-bg p-2 text-sm"></textarea></details>
      <textarea aria-label="Ask about your work" bind:value={question} oninput={e => composing(e.currentTarget.value)} disabled={busy || !!pending} rows="2" maxlength="2000" placeholder="Find evidence for my argument, review a paragraph, suggest an edit…" class="w-full rounded-xl border border-line bg-bg p-2 text-sm"></textarea>
      <div class="flex flex-wrap gap-1.5">{#each actions as action}<button type="button" onclick={() => ask(action.id)} disabled={busy || !!pending} class="rounded-lg border border-line px-2 py-1.5 text-xs hover:bg-surface-2 disabled:opacity-40">{action.label}</button>{/each}</div>
    </form>
  {/if}
</div>
