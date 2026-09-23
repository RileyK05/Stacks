<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api/client';
  import type { paths } from '$lib/api/schema';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import RichText from '$lib/components/RichText.svelte';
  import Select from '$lib/components/Select.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Spinner from '$lib/components/Spinner.svelte';
  import TextInput from '$lib/components/TextInput.svelte';
  import WorkspacePanel from '$lib/components/WorkspacePanel.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { itemTitle, openSession, WorkspaceCanvas, type WorkspaceSession } from '$lib/stores/workspace.svelte';
  import { formatBytes } from '$lib/utils/format';

  type CourseView =
    paths['/courses/{course_id}']['get']['responses'][200]['content']['application/json'];
  type SourceView =
    paths['/courses/{course_id}/sources']['get']['responses'][200]['content']['application/json'][number];
  type MemberView =
    paths['/courses/{course_id}/members']['get']['responses'][200]['content']['application/json'][number];
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
    citations: Citation[];
    citationsLoading: boolean;
    error: unknown;
    showSources: boolean;
  }

  const courseId = page.params.id ?? '';
  const QUESTION_MAX_LENGTH = 2000;

  let course = $state<CourseView | null>(null);
  let sources = $state<SourceView[]>([]);
  let members = $state<MemberView[]>([]);
  let loading = $state(true);
  let error = $state<unknown>(null);
  let actionError = $state<unknown>(null);

  let activeTab = $state<'ask' | 'sources' | 'members'>('ask');

  let question = $state('');
  let asking = $state(false);
  let turns = $state<Turn[]>([]);
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
  ].map((value) => ({ value: value as SourceType, label: value.replace(/_/g, ' ') }));

  let isOwner = $derived(course?.role === 'owner');
  let joinCode = $derived(course?.join_code ?? null);
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
    if (isOwner) {
      const [sourcesRes, membersRes] = await Promise.all([
        api.GET('/courses/{course_id}/sources', {
          params: { path: { course_id: courseId } }
        }),
        api.GET('/courses/{course_id}/members', {
          params: { path: { course_id: courseId } }
        })
      ]);
      if (sourcesRes.error) throw sourcesRes.error;
      if (membersRes.error) throw membersRes.error;
      sources = sourcesRes.data ?? [];
      members = membersRes.data ?? [];
    }
  }

  async function pollSourcesUntilSettled() {
    // Fresh uploads sit at uploaded→scanned→indexed invisibly otherwise
    // (the worker heartbeats; the UI just has to look). Poll every
    // 1.5s while anything is in flight; stop when all settle. No
    // polling after an error — the requeue button is the recovery path.
    for (let attempt = 0; attempt < 60 && anyPending; attempt++) {
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
    asking = true;
    const turn: Turn = {
      question,
      answer: null,
      workspace: [],
      withheld: [],
      traceId: null,
      citations: [],
      citationsLoading: false,
      error: null,
      showSources: true
    };
    turns = [...turns, turn];
    const index = turns.length - 1;
    question = '';
    try {
      const { data, error: err } = await api.POST('/courses/{course_id}/ask', {
        params: { path: { course_id: courseId } },
        body: { question: turn.question }
      });
      if (!data) throw err ?? new Error('unexpected empty response');
      turns[index].answer = data.text;
      turns[index].workspace = (data.workspace ?? []).map(openSession);
      turns[index].withheld = data.withheld ?? [];
      canvas.openFromTurn(index, turns[index].workspace);
      turns[index].traceId = data.trace_id;
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

  const starterPrompts = [
    'Summarize the main ideas so far',
    'Quiz me with a few multiple-choice questions',
    'Make me an editable study guide'
  ];

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
      void pollSourcesUntilSettled();
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
      void pollSourcesUntilSettled();
    } catch (caught) {
      actionError = caught;
    }
  }

  async function copyJoinCode() {
    if (!joinCode) return;
    await navigator.clipboard.writeText(joinCode);
    toast('Join code copied to clipboard.');
  }

  async function rotateJoinCode() {
    if (!(await confirmDialog({
      title: 'Rotate join code?',
      message: 'The current code stops working immediately. Anyone you shared it with will need the new one.',
      confirmLabel: 'Rotate'
    }))) return;
    actionError = null;
    try {
      const { data, error: err } = await api.POST('/courses/{course_id}/join-code/rotate', {
        params: { path: { course_id: courseId } }
      });
      if (err || !data) throw err ?? new Error('unexpected empty response');
      course = data;
      toast('Join code rotated.');
    } catch (caught) {
      actionError = caught;
    }
  }

  async function revoke(userId: string) {
    if (!(await confirmDialog({
      title: 'Revoke this member?',
      message: 'They lose access immediately but can re-join with the code if the course is not private.',
      confirmLabel: 'Revoke',
      danger: true
    }))) return;
    actionError = null;
    try {
      const { error: err } = await api.DELETE('/courses/{course_id}/enrollments/{user_id}', {
        params: { path: { course_id: courseId, user_id: userId } }
      });
      if (err) throw err;
      await loadExtras();
      toast('Member revoked.');
    } catch (caught) {
      actionError = caught;
    }
  }

  async function leave() {
    if (!(await confirmDialog({
      title: 'Leave this course?',
      message: 'You keep your private study history, but lose access to the course materials.',
      confirmLabel: 'Leave',
      danger: true
    }))) return;
    actionError = null;
    try {
      const { error: err } = await api.DELETE('/courses/{course_id}/enrollment', {
        params: { path: { course_id: courseId } }
      });
      if (err) throw err;
      await goto('/');
    } catch (caught) {
      actionError = caught;
    }
  }
</script>

{#if error}
  <ErrorBanner {error} />
{:else if loading || !course}
  <div class="flex flex-col gap-4">
    <Skeleton class="h-8 w-64" />
    <Skeleton class="h-40 w-full" />
    <Skeleton class="h-40 w-full" />
  </div>
{:else}
  <div class="flex flex-col gap-6">
    <div class="flex items-start justify-between">
      <div>
        <h1 class="text-2xl font-bold text-slate-900 dark:text-slate-100">{course.name}</h1>
        <p class="mt-1 text-sm text-slate-500">
          {course.visibility} · you are the {course.role} · {formatBytes(course.stored_bytes ?? 0)} stored
        </p>
      </div>
      {#if course.role === 'learner'}
        <Button variant="danger" onclick={leave}>Leave course</Button>
      {/if}
    </div>

    {#if actionError}<ErrorBanner error={actionError} />{/if}

    <div class="flex flex-wrap gap-2">
      {#each [['Probe', 'M3'], ['Progress', 'M4'], ['Artifacts', 'M5']] as [label, milestone]}
        <a
          href={`/courses/${courseId}/${label.toLowerCase()}`}
          class="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600 ring-1 ring-slate-200 transition-colors hover:text-indigo-700 hover:ring-indigo-200 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-700 dark:hover:text-indigo-300 dark:hover:ring-indigo-700"
        >
          {label}
          <span class="rounded-full bg-slate-100 px-1.5 text-[10px] text-slate-400 dark:bg-slate-800">{milestone}</span>
        </a>
      {/each}
    </div>

    <div class="flex gap-1 border-b border-slate-200 dark:border-slate-700">
      {#each [['ask', 'Ask'], ['sources', 'Sources'], ['members', 'Members']] as [tab, label]}
        {#if tab === 'ask' || isOwner}
          <button
            onclick={() => (activeTab = tab as 'ask' | 'sources' | 'members')}
            class={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab
                ? 'border-indigo-600 text-indigo-700 dark:border-indigo-400 dark:text-indigo-300'
                : 'border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200'
            }`}
          >
            {label}
            {#if tab === 'sources' && anyPending}
              <span class="ml-1 inline-block h-2 w-2 animate-pulse rounded-full bg-amber-400 align-middle"></span>
            {/if}
          </button>
        {/if}
      {/each}
    </div>

    {#if activeTab === 'ask'}
      <div class={`grid items-start gap-6 ${workspaceOpen ? 'lg:grid-cols-2' : ''}`}>
        <div class="flex min-w-0 flex-col gap-6">
          <Card>
            {#if turns.length === 0}
              <div class="flex flex-col gap-3 pb-2">
                <p class="text-sm text-slate-600 dark:text-slate-300">
                  Ask anything about this course. Answers cite the exact material they came from.
                  Ask for a quiz or a study guide and it opens in the workspace beside the chat.
                </p>
                <div class="flex flex-wrap gap-2">
                  {#each starterPrompts as starter (starter)}
                    <button
                      type="button"
                      onclick={() => askFollowUp(starter)}
                      class="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600 ring-1 ring-slate-200 transition-colors hover:text-indigo-700 hover:ring-indigo-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700 dark:hover:text-indigo-300 dark:hover:ring-indigo-700"
                    >
                      {starter}
                    </button>
                  {/each}
                </div>
              </div>
            {:else}
              <div bind:this={sessionRef} class="flex flex-col gap-5">
                {#each turns as turn, index (index)}
                  <div class="flex flex-col gap-2">
                    <div class="flex items-baseline gap-2">
                      <span class="font-mono text-xs text-indigo-600 dark:text-indigo-300">Q{index + 1}</span>
                      <p class="text-sm font-medium text-slate-900 dark:text-slate-100">{turn.question}</p>
                    </div>

                    {#if turn.error}
                      <ErrorBanner error={turn.error} />
                    {:else if turn.answer === null}
                      <div class="flex items-center gap-2 text-xs text-slate-400"><Spinner /> Thinking…</div>
                    {:else}
                      {#if turn.answer}
                        <div class="rounded-lg border border-indigo-100 bg-indigo-50/50 p-4 dark:border-indigo-900 dark:bg-indigo-950/40">
                          <RichText text={turn.answer} />
                        </div>
                      {/if}

                      {#if turn.workspace.length > 0}
                        <button
                          type="button"
                          onclick={() => openWorkspace(index)}
                          class={`flex items-center gap-2 self-start rounded-lg px-3 py-2 text-xs font-medium ring-1 transition-colors ${
                            canvas.active?.turnIndex === index
                              ? 'bg-indigo-600 text-white ring-indigo-600'
                              : 'bg-white text-indigo-700 ring-indigo-200 hover:bg-indigo-50 dark:bg-slate-900 dark:text-indigo-300 dark:ring-indigo-800 dark:hover:bg-indigo-950/50'
                          }`}
                        >
                          {canvas.active?.turnIndex === index ? 'Showing in workspace' : 'Open in workspace →'}
                          <span class="opacity-80">
                            {turn.workspace.map((session) => itemTitle(session)).join(' · ')}
                          </span>
                        </button>
                      {/if}

                      {#each turn.withheld as reason, reasonIndex (reasonIndex)}
                        <p class="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900">
                          The tutor generated something that is not shown because it could not be tied to
                          your course material: {reason}
                        </p>
                      {/each}

                      <div class="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200 dark:bg-slate-800/60 dark:ring-slate-700">
                        <button
                          class="flex w-full items-center justify-between text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400"
                          onclick={() => (turn.showSources = !turn.showSources)}
                        >
                          <span>
                            Sources used
                            {#if turn.citationsLoading}<Spinner />{/if}
                          </span>
                          <span>{turn.showSources ? '▾' : '▸'} {turn.citations.length}</span>
                        </button>

                        {#if turn.showSources && turn.citations.length > 0}
                          <ul class="mt-2 flex flex-col gap-2">
                            {#each turn.citations as citation, citeIndex (citation.chunk_id)}
                              <li class="rounded-md bg-white p-3 ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-700">
                                <div class="flex items-baseline justify-between gap-2">
                                  <span class="font-mono text-xs text-indigo-600 dark:text-indigo-300">[{citeIndex + 1}]</span>
                                  <span class="text-xs text-slate-500 dark:text-slate-400">
                                    {citation.filename} · {citation.label}
                                  </span>
                                </div>
                                {#if citation.description}
                                  <p class="mt-1 text-xs italic text-slate-500 dark:text-slate-400">{citation.description}</p>
                                {/if}
                                <p class="mt-1 text-xs leading-relaxed text-slate-600 dark:text-slate-300">{citation.text}</p>
                              </li>
                            {/each}
                          </ul>
                        {/if}

                        {#if turn.traceId && !turn.citationsLoading}
                          <p class="mt-2 font-mono text-[10px] text-slate-400">trace {turn.traceId}</p>
                        {/if}
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
            {/if}

            <form
              onsubmit={ask}
              class="mt-5 flex flex-col gap-3 border-t border-slate-200 pt-4 dark:border-slate-700"
            >
              <TextInput
                label="Question"
                bind:value={question}
                required
                maxlength={QUESTION_MAX_LENGTH}
                placeholder="Ask something, or say: quiz me on …"
              />
              <div class="flex items-center justify-between">
                <p class="text-xs text-slate-400">
                  {turns.length === 0
                    ? 'Answers cite the exact course material they came from.'
                    : `${turns.length} question${turns.length === 1 ? '' : 's'} this session (kept in this browser)`}
                </p>
                <div class="flex gap-2">
                  {#if turns.length > 0}
                    <Button variant="secondary" onclick={clearSession}>Clear session</Button>
                  {/if}
                  <Button type="submit" loading={asking}>Ask</Button>
                </div>
              </div>
            </form>
          </Card>

          {#if isOwner && joinCode}
            <Card title="Join code">
              <div class="flex items-center gap-3">
                <p class="font-mono text-lg tracking-wider text-slate-900 dark:text-slate-100">{joinCode}</p>
                <Button variant="secondary" onclick={copyJoinCode}>Copy</Button>
              </div>
              <p class="mt-1 text-sm text-slate-500">
                Anyone with this code can join while the course is not private.
              </p>
              <Button variant="secondary" onclick={rotateJoinCode} class="mt-3">
                Rotate code
              </Button>
            </Card>
          {/if}
        </div>

        {#if workspaceOpen}
          <div
            bind:this={workspaceRef}
            class="min-w-0 scroll-mt-6 lg:sticky lg:top-6 lg:h-[calc(100vh-3rem)]"
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
    {:else if activeTab === 'sources' && isOwner}
      <Card title="Sources">
        <form
          onsubmit={(e) => {
            e.preventDefault();
            const file = fileInput?.files?.[0];
            if (file) void uploadFile(file);
          }}
          class="mb-4 flex flex-col gap-3"
        >
          <div
            role="button"
            tabindex="0"
            class={`flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors ${
              dragOver ? 'border-indigo-400 bg-indigo-50 dark:border-indigo-600 dark:bg-indigo-950/50' : 'border-slate-300 hover:border-slate-400 dark:border-slate-700 dark:hover:border-slate-500'
            }`}
            ondragover={(e) => {
              e.preventDefault();
              dragOver = true;
            }}
            ondragleave={() => (dragOver = false)}
            ondrop={onDrop}
            onclick={() => fileInput?.click()}
            onkeydown={(e) => e.key === 'Enter' && fileInput?.click()}
          >
            <p class="text-sm font-medium text-slate-700 dark:text-slate-200">
              {uploading ? 'Uploading…' : 'Drop a file here, or click to browse'}
            </p>
            <p class="text-xs text-slate-500">PDF, Markdown, or plain text</p>
            <input bind:this={fileInput} type="file" class="hidden" />
          </div>
          <div class="flex flex-col gap-3 sm:flex-row sm:items-end">
            <Select label="Source type" options={sourceTypeOptions} bind:value={sourceType} />
            <Button type="submit" loading={uploading}>Upload</Button>
          </div>
        </form>
        {#if uploadError}<div class="mb-3"><ErrorBanner error={uploadError} /></div>{/if}
        {#if sources.length === 0}
          <p class="text-sm text-slate-500">No sources uploaded yet.</p>
        {:else}
          <table class="w-full text-left text-sm">
            <thead>
              <tr class="border-b border-slate-200 text-slate-500 dark:border-slate-700 dark:text-slate-400">
                <th class="py-2 pr-4 font-medium">File</th>
                <th class="py-2 pr-4 font-medium">Type</th>
                <th class="py-2 pr-4 font-medium">Status</th>
                <th class="py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {#each sources as source (source.source_id)}
                <tr class="border-b border-slate-100 dark:border-slate-800">
                  <td class="py-2 pr-4">
                    {source.filename}
                    <p class="text-xs text-slate-400">{formatBytes(source.size_bytes ?? 0)}</p>
                  </td>
                  <td class="py-2 pr-4 text-slate-500 dark:text-slate-400">{source.source_type}</td>
                  <td class="py-2 pr-4">
                    <span
                      class={source.status === 'failed'
                        ? 'text-red-600 dark:text-red-400'
                        : source.status === 'indexed'
                          ? 'text-green-700 dark:text-green-300'
                          : 'text-slate-500'}
                    >
                      {source.status === 'uploaded' || source.status === 'scanned'
                        ? 'indexing…'
                        : source.status}
                    </span>
                    {#if source.error_message}
                      <p class="text-xs text-red-500">{source.error_message}</p>
                    {/if}
                  </td>
                  <td class="py-2 text-right">
                    {#if source.status === 'failed'}
                      <Button variant="secondary" onclick={() => requeue(source.source_id)}>
                        Requeue
                      </Button>
                    {/if}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </Card>
    {:else if activeTab === 'members' && isOwner}
      <Card title="Members">
        {#if members.length === 0}
          <p class="text-sm text-slate-500">No members yet — share the join code to add learners.</p>
        {:else}
          <ul class="flex flex-col gap-2 text-sm">
            {#each members as member (member.user_id)}
              <li class="flex items-center justify-between border-b border-slate-100 py-2 dark:border-slate-800">
                <span class="font-mono text-slate-700 dark:text-slate-200">{member.user_id}</span>
                <span class="flex items-center gap-3">
                  <span class="text-slate-500 dark:text-slate-400">{member.status}</span>
                  {#if member.status === 'active'}
                    <Button variant="secondary" onclick={() => revoke(member.user_id)}>
                      Revoke
                    </Button>
                  {/if}
                </span>
              </li>
            {/each}
          </ul>
        {/if}
      </Card>
    {/if}
  </div>
{/if}
