<script lang="ts">
  import { untrack } from 'svelte';
  import { api } from '$lib/api/client';
  import type { components } from '$lib/api/schema';
  import Button from '$lib/components/Button.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import CritiqueCards from '$lib/components/critique/CritiqueCards.svelte';
  import CritiqueControls from '$lib/components/critique/CritiqueControls.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { latestCritique, type EssayGenre } from '$lib/utils/critique';

  type Work = components['schemas']['WorkSession'];
  type Summary = components['schemas']['WorkSummary'];
  type Ask = components['schemas']['WorkAsk'];
  type SourceLike = { source_type: string; status: string };

  let {
    courseId,
    sources,
    onsources
  }: {
    courseId: string;
    sources: SourceLike[];
    onsources: () => void;
  } = $props();

  let sessions = $state<Summary[]>([]);
  let work = $state<Work | null>(null);
  let title = $state('Essay draft');
  let connecting = $state(false);
  let pastedText = $state('');
  let documentTitle = $state('Working document');
  let selection = $state('');
  let question = $state('');
  let score = $state(50);
  let genre = $state<EssayGenre>('argumentative');
  let settingsLocked = $state(false);
  let settingsEpoch = 0;
  let busy = $state(false);
  let loading = $state(true);
  let error = $state<unknown>(null);
  let refreshIssue = $state('');
  let useSaved = $state(false);
  let documentRefreshing = $state(false);
  let fileInput = $state<HTMLInputElement | null>(null);
  let epoch = 0;

  const syllabusIndexed = $derived(
    sources.some((source) => source.source_type === 'syllabus' && source.status === 'indexed')
  );
  const currentCritique = $derived(work ? latestCritique(work.turns) : null);
  const critiqueTurns = $derived(
    (work?.turns ?? []).filter((turn) => turn.reply.critique).slice().reverse()
  );

  $effect(() => {
    if (!work || settingsLocked) return;
    score = work.critic_score;
    genre = work.essay_genre;
  });

  $effect(() => {
    const currentCourse = courseId;
    untrack(() => {
      epoch += 1;
      work = null;
      sessions = [];
      error = null;
      void load(currentCourse, epoch);
    });
  });

  function current(token: number) {
    return token === epoch && courseId !== '';
  }

  async function load(currentCourse = courseId, token = epoch) {
    loading = true;
    error = null;
    try {
      const response = await api.GET('/companion/courses/{course_id}/work', {
        params: { path: { course_id: currentCourse } }
      });
      if (!current(token) || currentCourse !== courseId) return;
      sessions = (response.data ?? []).filter((session) => session.purpose === 'paper');
      const first = sessions[0];
      if (first) await openSession(first.session_id, token);
      else loading = false;
    } catch (caught) {
      if (current(token)) {
        error = caught;
        loading = false;
      }
    }
  }

  async function openSession(id: string, token = ++epoch) {
    settingsLocked = false;
    useSaved = false;
    refreshIssue = '';
    selection = '';
    question = '';
    connecting = false;
    pastedText = '';
    error = null;
    try {
      const response = await api.GET('/companion/courses/{course_id}/work/{session_id}', {
        params: { path: { course_id: courseId, session_id: id } }
      });
      if (!current(token) || !response.data) return;
      work = response.data;
    } catch (caught) {
      if (current(token)) error = caught;
    } finally {
      if (current(token)) loading = false;
    }
  }

  async function saveSettings(nextScore = score, nextGenre = genre) {
    if (!work) {
      settingsLocked = false;
      return;
    }
    if (nextScore === work.critic_score && nextGenre === work.essay_genre) {
      settingsLocked = false;
      return;
    }
    const token = epoch;
    const id = work.session_id;
    const generation = ++settingsEpoch;
    settingsLocked = true;
    error = null;
    try {
      const response = await api.PATCH('/companion/courses/{course_id}/work/{session_id}', {
        params: { path: { course_id: courseId, session_id: id } },
        body: { critic_score: nextScore, essay_genre: nextGenre }
      });
      if (!current(token) || generation !== settingsEpoch || !response.data) return;
      work = response.data;
    } catch (caught) {
      if (current(token) && generation === settingsEpoch) error = caught;
    } finally {
      if (generation === settingsEpoch) settingsLocked = false;
    }
  }

  async function createSession() {
    if (busy || !title.trim()) return;
    const token = epoch;
    busy = true;
    error = null;
    try {
      const response = await api.POST('/companion/courses/{course_id}/work', {
        params: { path: { course_id: courseId } },
        body: { title: title.trim(), purpose: 'paper' }
      });
      if (!current(token) || !response.data) return;
      sessions = [response.data, ...sessions];
      work = response.data;
      connecting = true;
    } catch (caught) {
      if (current(token)) error = caught;
    } finally {
      busy = false;
    }
  }

  async function connectDocument(text: string, docTitle: string) {
    if (!work || busy || !text.trim()) return;
    const token = epoch;
    const id = work.session_id;
    busy = true;
    error = null;
    try {
      const response = await api.PUT('/companion/courses/{course_id}/work/{session_id}/document', {
        params: { path: { course_id: courseId, session_id: id } },
        body: {
          title: docTitle.trim() || 'Working document',
          text,
          origin: 'paste',
          coverage: 'unknown',
          warnings: [],
          external_id: '',
          expected_revision: work.revision
        }
      });
      if (current(token) && response.data) {
        work = response.data;
        connecting = false;
        pastedText = '';
        useSaved = false;
      }
    } catch (caught) {
      if (current(token)) error = caught;
    } finally {
      busy = false;
    }
  }

  async function upload(file: File) {
    if (!work || busy) return;
    const token = epoch;
    const id = work.session_id;
    busy = true;
    error = null;
    try {
      const body = new FormData();
      body.append('file', file);
      body.append('expected_revision', String(work.revision));
      const response = await api.POST('/companion/courses/{course_id}/work/{session_id}/file', {
        params: { path: { course_id: courseId, session_id: id } },
        body: body as never,
        bodySerializer: (value) => value as unknown as FormData
      });
      if (current(token) && response.data) {
        work = response.data;
        connecting = false;
        useSaved = false;
      }
    } catch (caught) {
      if (current(token)) error = caught;
    } finally {
      busy = false;
    }
  }

  async function refreshOfficeDocument(): Promise<boolean> {
    if (!work?.document || work.document.origin !== 'office' || useSaved) return true;
    const token = epoch;
    const id = work.session_id;
    const course = courseId;
    documentRefreshing = true;
    refreshIssue = '';
    try {
      const settings = await api.GET('/companion/live-policy');
      if (!current(token) || !settings.data) return false;
      const timeout = settings.data.refresh_timeout_seconds * 1000;
      const started = await api.POST('/companion/courses/{course_id}/work/{session_id}/refresh', {
        params: { path: { course_id: course, session_id: id } },
        signal: AbortSignal.timeout(timeout)
      });
      if (!current(token) || !started.data) return false;
      let result = started.data;
      const deadline = performance.now() + timeout;
      while (result.status === 'pending') {
        await new Promise((resolve) => setTimeout(resolve, settings.data!.poll_interval_ms));
        if (!current(token) || work?.session_id !== id) return false;
        if (performance.now() >= deadline) {
          throw new Error('Document refresh timed out. Retry or use the saved snapshot.');
        }
        const update = await api.GET(
          '/companion/courses/{course_id}/work/{session_id}/refresh/{request_id}',
          {
            params: { path: { course_id: course, session_id: id, request_id: result.request_id } },
            signal: AbortSignal.timeout(Math.max(1, deadline - performance.now()))
          }
        );
        if (!current(token) || !update.data) return false;
        result = update.data;
      }
      if (result.status !== 'complete') {
        throw new Error(result.error || 'Could not read the current Office document.');
      }
      const updated = await api.GET('/companion/courses/{course_id}/work/{session_id}', {
        params: { path: { course_id: course, session_id: id } }
      });
      if (current(token) && updated.data) work = updated.data;
      return Boolean(updated.data);
    } catch (caught) {
      if (current(token)) {
        refreshIssue = caught instanceof Error ? caught.message : 'Could not refresh the Office document.';
      }
      return false;
    } finally {
      if (current(token)) documentRefreshing = false;
    }
  }

  async function critique(focus: 'draft' | 'unread') {
    if (!work?.document || busy) return;
    const token = epoch;
    const id = work.session_id;
    const course = courseId;
    busy = true;
    error = null;
    try {
      await saveSettings(score, genre);
      if (!current(token) || work?.session_id !== id) return;
      if (!(await refreshOfficeDocument())) return;
      if (!current(token) || !work?.document) return;
      const request: Ask = {
        request_id: crypto.randomUUID(),
        action: 'critique',
        instruction: question.trim(),
        selection: selection.trim(),
        expected_revision: work.revision,
        critic_score: score,
        essay_genre: genre,
        focus
      };
      await api.POST('/companion/courses/{course_id}/work/{session_id}/ask', {
        params: { path: { course_id: course, session_id: id } },
        body: request
      });
      if (!current(token)) return;
      question = '';
      const response = await api.GET('/companion/courses/{course_id}/work/{session_id}', {
        params: { path: { course_id: course, session_id: id } }
      });
      if (current(token) && response.data) work = response.data;
    } catch (caught) {
      if (current(token)) error = caught;
    } finally {
      if (current(token)) busy = false;
    }
  }

  async function removeSession() {
    if (!work || busy) return;
    const id = work.session_id;
    const token = epoch;
    if (
      !(await confirmDialog({
        title: 'Delete this work session?',
        message: 'Its document snapshots and conversations will be removed. Your course sources and learning memory stay intact.',
        confirmLabel: 'Delete session',
        danger: true
      }))
    ) {
      return;
    }
    if (!current(token) || work?.session_id !== id || busy) return;
    busy = true;
    try {
      await api.DELETE('/companion/courses/{course_id}/work/{session_id}', {
        params: { path: { course_id: courseId, session_id: id } }
      });
      if (!current(token)) return;
      sessions = sessions.filter((session) => session.session_id !== id);
      work = null;
      const next = sessions[0];
      if (next) await openSession(next.session_id);
    } catch (caught) {
      if (current(token)) error = caught;
    } finally {
      busy = false;
    }
  }
</script>

<div class="flex flex-col gap-4 pb-8">
  <div>
    <h2 class="font-display text-xl text-fg">Critic</h2>
    <p class="mt-1 max-w-2xl text-sm text-muted">
      A strict pass over your own draft. Raise the critic score and revise the essay yourself between passes.
    </p>
  </div>

  {#if error}<ErrorBanner {error} />{/if}
  {#if !syllabusIndexed}
    <div class="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-surface-2 px-4 py-3 text-sm text-muted">
      <p class="min-w-0 flex-1">No indexed syllabus is marked for this course. The critic will not invent assignment rules.</p>
      <Button variant="secondary" size="sm" onclick={onsources}>Open Sources</Button>
    </div>
  {/if}

  {#if loading}
    <p class="text-sm text-muted">Loading paper sessions…</p>
  {:else}
    <div class="grid items-start gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <div class="flex flex-col gap-4">
        <div class="flex items-center gap-2">
          <select
            aria-label="Paper session"
            class="h-10 min-w-0 flex-1 rounded-lg border border-line-strong bg-surface px-3 text-sm text-fg"
            value={work?.session_id ?? ''}
            onchange={(event) => {
              const id = event.currentTarget.value;
              if (id) void openSession(id);
              else {
                epoch += 1;
                work = null;
              }
            }}
          >
            <option value="">New paper session</option>
            {#each sessions as session (session.session_id)}
              <option value={session.session_id}>{session.title}</option>
            {/each}
          </select>
          <Button variant="ghost" size="sm" onclick={() => load()}>Refresh</Button>
        </div>

        {#if !work}
          <div class="space-y-2 rounded-xl border border-line bg-surface p-3">
            <label class="block text-xs text-muted">Session name
              <input aria-label="Session title" bind:value={title} maxlength="300" class="mt-1 h-10 w-full rounded-lg border border-line bg-bg px-3 text-sm text-fg" />
            </label>
            <Button onclick={createSession} disabled={busy || !title.trim()}>Start paper session</Button>
          </div>
        {:else}
          <section class="space-y-2 rounded-xl border border-line bg-surface p-3">
            <div class="flex items-start gap-2">
              <div class="min-w-0 flex-1">
                <h3 class="truncate font-medium text-fg">{work.title}</h3>
                <p class="text-xs text-muted">
                  {work.document ? `Snapshot ${work.revision}` : 'No document connected'}
                  {#if work.document}
                    · {work.document.text.length.toLocaleString()} characters
                    · {work.document.coverage === 'document' ? 'Document text' : 'Partial or unverified capture'}
                  {/if}
                </p>
              </div>
              <Button variant="ghost" size="sm" onclick={removeSession} disabled={busy}>Delete</Button>
            </div>
            {#if work.document}
              <p class="truncate text-sm text-fg">{work.document.title}</p>
              {#each work.document.warnings as warning, index (index)}
                <p class="text-xs text-warning-text">{warning}</p>
              {/each}
              <details>
                <summary class="cursor-pointer text-xs text-accent-text">Inspect connected text</summary>
                <pre class="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap text-xs text-muted">{work.document.text}</pre>
              </details>
              {#if work.document.origin === 'office'}
                <button type="button" class="text-xs font-medium text-accent-text" disabled={busy || documentRefreshing} onclick={() => refreshOfficeDocument()}>
                  Refresh from Office
                </button>
                <p class="text-xs text-muted">Keep the connected Office pane open. Critique essay reads the latest document first.</p>
              {/if}
            {/if}
            <button type="button" class="text-xs font-medium text-accent-text" disabled={busy} onclick={() => (connecting = !connecting)}>
              {connecting ? 'Close document connection' : work.document ? 'Replace the connected draft' : 'Connect your draft'}
            </button>
          </section>

          {#if connecting}
            <div class="space-y-3 rounded-xl border border-line bg-surface p-3">
              <input
                bind:this={fileInput}
                type="file"
                accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.csv"
                class="hidden"
                onchange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  if (file) void upload(file);
                  event.currentTarget.value = '';
                }}
              />
              <Button variant="secondary" onclick={() => fileInput?.click()} disabled={busy}>Connect file</Button>
              <label class="block text-xs text-muted">Document title
                <input aria-label="Document title" bind:value={documentTitle} maxlength="300" class="mt-1 h-10 w-full rounded-lg border border-line bg-bg px-3 text-sm text-fg" />
              </label>
              <textarea aria-label="Draft text" bind:value={pastedText} rows="8" maxlength="300000" placeholder="Paste the draft" class="w-full rounded-lg border border-line bg-bg p-2 text-sm text-fg"></textarea>
              <Button onclick={() => connectDocument(pastedText, documentTitle)} disabled={busy || !pastedText.trim()}>Connect pasted draft</Button>
            </div>
          {/if}

          {#if work.document}
            {#if documentRefreshing}<p class="text-xs text-muted" role="status">Reading the current Office document…</p>{/if}
            {#if refreshIssue}
              <p class="text-xs text-warning-text" role="status">{refreshIssue}</p>
              <div class="flex gap-3">
                <button type="button" class="text-xs text-accent-text" disabled={busy} onclick={() => refreshOfficeDocument()}>Retry document refresh</button>
                <button type="button" class="text-xs text-muted" disabled={busy} onclick={() => { useSaved = true; refreshIssue = ''; }}>Use saved snapshot {work.revision}</button>
              </div>
            {/if}
            {#if useSaved}<p class="text-xs text-warning-text">Using saved snapshot {work.revision}. Newer Office changes may be missing.</p>{/if}
            <textarea aria-label="Focus on a passage" bind:value={selection} rows="2" maxlength="4000" disabled={busy} placeholder="Optional: an exact passage from the connected snapshot" class="w-full rounded-lg border border-line bg-surface p-2 text-sm text-fg"></textarea>
            <textarea aria-label="Note for the critic" bind:value={question} rows="2" maxlength="2000" disabled={busy} placeholder="Optional note, such as the claim you want pressure on" class="w-full rounded-lg border border-line bg-surface p-2 text-sm text-fg"></textarea>
            <CritiqueControls
              {score}
              {genre}
              disabled={busy || documentRefreshing}
              unreadAvailable={currentCritique !== null && !currentCritique.coverage.complete}
              onscorestart={() => (settingsLocked = true)}
              onscore={(value) => { settingsLocked = true; score = value; }}
              onscorecommit={(value) => { score = value; void saveSettings(value, genre); }}
              ongenre={(value) => { genre = value; void saveSettings(score, value); }}
              oncritique={(focus) => critique(focus)}
            />
          {/if}
        {/if}
      </div>

      <div class="flex flex-col gap-4">
        {#if critiqueTurns.length === 0}
          <p class="text-sm text-muted">No critique yet. Connect a draft, then run Critique essay.</p>
        {:else}
          {#each critiqueTurns as turn, index (turn.request_id)}
            <section class="rounded-xl border border-line bg-surface p-3">
              {#if index > 0}
                <p class="mb-2 text-[11px] text-subtle">Earlier pass · snapshot {turn.document_revision}</p>
              {:else}
                <p class="mb-2 text-[11px] text-subtle">Latest pass · snapshot {turn.document_revision}</p>
              {/if}
              {#if turn.instruction}<p class="mb-2 text-sm text-muted">{turn.instruction}</p>{/if}
              {#if turn.reply.critique}
                <CritiqueCards critique={turn.reply.critique} citations={turn.reply.citations} />
              {/if}
            </section>
          {/each}
        {/if}
      </div>
    </div>
  {/if}
</div>
