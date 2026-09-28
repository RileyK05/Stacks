<script lang="ts">
  import { invoke, isTauri } from '@tauri-apps/api/core';
  import { onMount, tick } from 'svelte';
  import { api } from '$lib/api/client';
  import type { components, paths } from '$lib/api/schema';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon, { type IconName } from '$lib/components/Icon.svelte';
  import RichText from '$lib/components/RichText.svelte';
  import { toast } from '$lib/stores/toast.svelte';

  type CourseView =
    paths['/courses']['get']['responses'][200]['content']['application/json'][number];
  type AssistResult = components['schemas']['AssistResult'];
  type Action = 'explain' | 'find' | 'quiz' | 'summarize';

  interface Turn {
    id: number;
    label: string;
    answer: AssistResult | null;
    error: unknown;
  }

  const actions: { id: Action; label: string; description: string; icon: IconName }[] = [
    { id: 'explain', label: 'Explain', description: 'Make this click', icon: 'sparkles' },
    { id: 'find', label: 'Find in course', description: 'Connect it to sources', icon: 'search' },
    { id: 'quiz', label: 'Quiz me', description: 'Check my understanding', icon: 'list-checks' },
    { id: 'summarize', label: 'Summarize', description: 'Pull out the essentials', icon: 'file-text' }
  ];

  let courses = $state<CourseView[]>([]);
  let selectedCourseId = $state('');
  let context = $state('');
  let question = $state('');
  let turns = $state<Turn[]>([]);
  let loading = $state(true);
  let sending = $state(false);
  let error = $state<unknown>(null);
  let pinned = $state(false);
  let nextTurnId = 1;
  let conversationEnd = $state<HTMLElement | null>(null);

  const selectedCourse = $derived(
    courses.find((course) => course.course_id === selectedCourseId) ?? null
  );

  onMount(() => {
    pinned = localStorage.getItem('companion-pinned') === 'true';
    void initialize().catch((caught) => {
      error = caught;
      loading = false;
    });
  });

  async function initialize(): Promise<void> {
    if (isTauri()) {
      try {
        await invoke('set_companion_pinned', { pinned });
      } catch {
        pinned = false;
        localStorage.setItem('companion-pinned', 'false');
        toast('Could not restore the companion pin setting.', 'error');
      }
    }
    await loadCourses();
  }

  async function loadCourses(): Promise<void> {
    loading = true;
    error = null;
    try {
      const { data, error: requestError } = await api.GET('/courses');
      if (requestError || !data) throw requestError ?? new Error('unexpected empty response');
      courses = data;
      const remembered = localStorage.getItem('companion-course') ?? '';
      selectedCourseId = data.some((course) => course.course_id === remembered)
        ? remembered
        : (data[0]?.course_id ?? '');
    } catch (caught) {
      error = caught;
    } finally {
      loading = false;
    }
  }

  function selectCourse(courseId: string): void {
    selectedCourseId = courseId;
    localStorage.setItem('companion-course', courseId);
    turns = [];
  }

  async function togglePinned(): Promise<void> {
    const previous = pinned;
    pinned = !pinned;
    localStorage.setItem('companion-pinned', String(pinned));
    if (!isTauri()) return;
    try {
      await invoke('set_companion_pinned', { pinned });
    } catch {
      pinned = previous;
      localStorage.setItem('companion-pinned', String(previous));
      toast('Could not change the companion pin setting.', 'error');
    }
  }

  async function showLibrary(): Promise<void> {
    if (isTauri()) await invoke('show_library');
    else window.open('/', '_blank', 'noopener,noreferrer');
  }

  async function ask(action: Action, instruction = ''): Promise<void> {
    const cleanInstruction = instruction.trim();
    const cleanContext = context.trim();
    if (!selectedCourseId) {
      error = new Error('Choose a course first.');
      return;
    }
    if (!cleanInstruction && !cleanContext) {
      error = new Error('Paste what you are looking at or ask a question.');
      return;
    }

    error = null;
    sending = true;
    const actionLabel = actions.find((item) => item.id === action)?.label ?? action;
    const turn: Turn = {
      id: nextTurnId++,
      label: cleanInstruction || `${actionLabel}: ${cleanContext.slice(0, 120)}`,
      answer: null,
      error: null
    };
    turns = [...turns, turn];
    question = '';
    await tick();
    conversationEnd?.scrollIntoView({ behavior: 'smooth', block: 'end' });

    try {
      const { data, error: requestError } = await api.POST('/companion/assist', {
        body: {
          course_id: selectedCourseId,
          action,
          host: 'companion',
          context: cleanContext,
          instruction: cleanInstruction
        }
      });
      if (requestError || !data) throw requestError ?? new Error('unexpected empty response');
      updateTurn(turn.id, { answer: data });
    } catch (caught) {
      updateTurn(turn.id, { error: caught });
    } finally {
      sending = false;
      await tick();
      conversationEnd?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }

  function submitQuestion(event: SubmitEvent): void {
    event.preventDefault();
    if (!sending) void ask('explain', question);
  }

  function updateTurn(turnId: number, changes: Partial<Pick<Turn, 'answer' | 'error'>>): void {
    turns = turns.map((item) => (item.id === turnId ? { ...item, ...changes } : item));
  }

  function errorMessage(value: unknown): string {
    return value instanceof Error ? value.message : 'Something went wrong.';
  }
</script>

<svelte:head><title>Stacks Companion</title></svelte:head>

<div class="flex h-dvh flex-col overflow-hidden bg-bg">
    <header
      data-tauri-drag-region
      class="flex h-14 shrink-0 items-center gap-2 border-b border-line bg-surface px-3"
    >
      <span class="flex h-8 w-8 items-center justify-center rounded-[10px] bg-accent text-on-accent shadow-card">
        <Icon name="book" class="h-[18px] w-[18px]" />
      </span>
      <div data-tauri-drag-region class="min-w-0 flex-1">
        <p class="font-display text-[16px] font-semibold leading-tight text-fg">Stacks</p>
        <p class="truncate text-[11px] text-subtle">
          {selectedCourse ? selectedCourse.name : 'Your course companion'}
        </p>
      </div>
      <button
        type="button"
        onclick={togglePinned}
        class={`rounded-lg p-2 transition-colors ${pinned ? 'bg-accent-soft text-accent-text' : 'text-subtle hover:bg-surface-2 hover:text-fg'}`}
        aria-label={pinned ? 'Stop keeping Stacks on top' : 'Keep Stacks on top'}
        aria-pressed={pinned}
        title={pinned ? 'Pinned on top' : 'Pin on top'}
      ><Icon name="pin" class="h-4 w-4" /></button>
      <button
        type="button"
        onclick={showLibrary}
        class="rounded-lg p-2 text-subtle transition-colors hover:bg-surface-2 hover:text-fg"
        aria-label="Open full Stacks library"
        title="Open library"
      ><Icon name="panel-right" class="h-4 w-4" /></button>
    </header>

    {#if loading}
      <div class="flex flex-1 items-center justify-center text-sm text-muted">Opening your courses…</div>
    {:else if error && courses.length === 0}
      <div class="p-4"><ErrorBanner {error} /></div>
    {:else if courses.length === 0}
      <main class="flex flex-1 flex-col items-center justify-center px-7 text-center">
        <span class="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-soft text-accent-text">
          <Icon name="book" class="h-6 w-6" />
        </span>
        <h1 class="mt-4 font-display text-xl font-semibold text-fg">Start with a course</h1>
        <p class="mt-2 text-sm leading-relaxed text-muted">
          Add your syllabus, readings, slides, and notes in the Stacks library. Then this companion can answer from them wherever you work.
        </p>
        <button
          type="button"
          onclick={showLibrary}
          class="mt-5 inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-on-accent shadow-card hover:bg-accent-hover"
        >Open the library <Icon name="arrow-right" class="h-4 w-4" /></button>
      </main>
    {:else}
      <div class="flex min-h-0 flex-1 flex-col">
        <div class="shrink-0 space-y-3 border-b border-line bg-surface-2/40 p-3">
          <label class="block">
            <span class="mb-1 block text-[11px] font-semibold uppercase tracking-[0.12em] text-subtle">Course</span>
            <select
              value={selectedCourseId}
              onchange={(event) => selectCourse(event.currentTarget.value)}
              class="w-full rounded-lg border border-line-strong bg-surface px-3 py-2 text-sm text-fg shadow-card focus:border-accent focus:outline-none"
            >
              {#each courses as course (course.course_id)}
                <option value={course.course_id}>{course.name} · {course.source_count} sources</option>
              {/each}
            </select>
          </label>

          <label class="block">
            <span class="mb-1 flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.12em] text-subtle">
              <span>What I’m looking at</span>
              {#if context}<button type="button" onclick={() => (context = '')} class="normal-case tracking-normal text-muted hover:text-fg">Clear</button>{/if}
            </span>
            <textarea
              bind:value={context}
              rows="4"
              maxlength="100000"
              placeholder="Paste a selection from Word, a browser, a PDF, or anywhere else…"
              class="w-full resize-none rounded-xl border border-line bg-surface px-3 py-2.5 text-sm leading-relaxed text-fg shadow-card placeholder:text-subtle focus:border-accent focus:outline-none"
            ></textarea>
          </label>

          <div class="grid grid-cols-2 gap-2">
            {#each actions as action (action.id)}
              <button
                type="button"
                onclick={() => ask(action.id)}
                disabled={sending || !selectedCourseId || !context.trim()}
                class="group rounded-xl border border-line bg-surface p-2.5 text-left shadow-card transition-all hover:border-accent-line hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-45"
              >
                <span class="flex items-center gap-2 text-[13px] font-semibold text-fg">
                  <Icon name={action.icon} class="h-4 w-4 text-accent-text" /> {action.label}
                </span>
                <span class="mt-1 block text-[11px] text-subtle">{action.description}</span>
              </button>
            {/each}
          </div>
        </div>

        <main class="min-h-0 flex-1 overflow-y-auto px-3 py-4">
          {#if turns.length === 0}
            <div class="flex h-full min-h-40 flex-col items-center justify-center px-7 text-center">
              <Icon name="message-square" class="h-7 w-7 text-accent-text" />
              <p class="mt-3 text-sm font-medium text-fg">Ask about what you’re working on</p>
              <p class="mt-1 text-xs leading-relaxed text-muted">Stacks answers from this course and shows the passages it used.</p>
            </div>
          {:else}
            <div class="space-y-5">
              {#each turns as turn (turn.id)}
                <article class="space-y-2">
                  <div class="ml-8 rounded-2xl rounded-tr-md bg-accent px-3.5 py-2.5 text-sm leading-relaxed text-on-accent">
                    {turn.label}
                  </div>
                  {#if turn.error}
                    <div class="rounded-xl border border-info/25 bg-info-soft px-3.5 py-3 text-sm text-info-text" role="alert">
                      <p class="font-medium">{errorMessage(turn.error)}</p>
                      <button type="button" onclick={showLibrary} class="mt-2 font-semibold underline underline-offset-2">
                        Open the library and settings
                      </button>
                    </div>
                  {:else if turn.answer}
                    <div class="rounded-2xl rounded-tl-md border border-line bg-surface p-3.5 shadow-card">
                      <RichText text={turn.answer.text} />
                      {#if turn.answer.citations.length > 0}
                        <details class="mt-3 border-t border-line pt-2">
                          <summary class="cursor-pointer text-xs font-medium text-accent-text">
                            {turn.answer.citations.length} source{turn.answer.citations.length === 1 ? '' : 's'} used
                          </summary>
                          <ul class="mt-2 space-y-2">
                            {#each turn.answer.citations as citation (citation.chunk_id)}
                              <li class="rounded-lg bg-surface-2 px-2.5 py-2 text-xs leading-relaxed text-muted">
                                <p class="font-medium text-fg">[{citation.number}] {citation.filename} · {citation.label}</p>
                                <p class="mt-1 line-clamp-3">{citation.text}</p>
                              </li>
                            {/each}
                          </ul>
                        </details>
                      {/if}
                    </div>
                  {:else}
                    <div class="flex items-center gap-2 px-2 text-xs text-muted">
                      <span class="h-2 w-2 animate-pulse rounded-full bg-accent"></span> Reading your course…
                    </div>
                  {/if}
                </article>
              {/each}
              <div bind:this={conversationEnd}></div>
            </div>
          {/if}
        </main>

        <form onsubmit={submitQuestion} class="shrink-0 border-t border-line bg-surface p-3">
          {#if error}<div class="mb-2"><ErrorBanner {error} /></div>{/if}
          <div class="flex items-end gap-2 rounded-2xl border border-line-strong bg-bg p-2 shadow-card focus-within:border-accent">
            <textarea
              bind:value={question}
              rows="1"
              maxlength="2000"
              placeholder="Ask this course…"
              onkeydown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  if (!sending) void ask('explain', question);
                }
              }}
              class="max-h-28 min-h-9 flex-1 resize-none bg-transparent px-1.5 py-2 text-sm text-fg placeholder:text-subtle focus:outline-none"
            ></textarea>
            <button
              type="submit"
              disabled={sending || (!question.trim() && !context.trim())}
              class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent text-on-accent transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
              aria-label="Ask Stacks"
            ><Icon name="arrow-up" class="h-4 w-4" /></button>
          </div>
          <p class="mt-1.5 text-center text-[10px] text-subtle">Answers stay grounded in your course sources.</p>
        </form>
      </div>
    {/if}
</div>
