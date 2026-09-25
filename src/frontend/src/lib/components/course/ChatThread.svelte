<script lang="ts">
  import { tick } from 'svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon, { type IconName } from '$lib/components/Icon.svelte';
  import RichText from '$lib/components/RichText.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Spinner from '$lib/components/Spinner.svelte';
  import type { CourseChats, Turn } from '$lib/stores/chat.svelte';
  import { itemTitle, type WorkspaceCanvas } from '$lib/stores/workspace.svelte';

  interface Props {
    chats: CourseChats;
    canvas: WorkspaceCanvas;
    /** The model behind "Ask a bigger model"; null hides the button. */
    biggerModel: string | null;
    hasSources: boolean;
    onopenworkspace: (turnIndex: number) => void;
  }

  let { chats, canvas, biggerModel, hasSources, onopenworkspace }: Props = $props();

  const QUESTION_MAX_LENGTH = 2000;
  let question = $state('');
  let input = $state<HTMLTextAreaElement | null>(null);
  let end = $state<HTMLElement | null>(null);

  const starterPrompts: { text: string; icon: IconName }[] = [
    { text: 'Summarize the main ideas so far', icon: 'book' },
    { text: 'Quiz me with a few multiple-choice questions', icon: 'list-checks' },
    { text: 'Make me an editable study guide', icon: 'file-pen' }
  ];

  async function scrollToEnd() {
    await tick();
    end?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }

  async function send(text: string, bigger = false) {
    const trimmed = text.trim();
    if (!trimmed || chats.sending) return;
    void scrollToEnd();
    const turn = await chats.send(trimmed, bigger);
    await scrollToEnd();
    if (turn.workspace.length > 0) onopenworkspace(chats.turns.length - 1);
  }

  function submit(event: SubmitEvent) {
    event.preventDefault();
    const text = question;
    question = '';
    resize();
    void send(text);
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      input?.form?.requestSubmit();
    }
  }

  function resize() {
    if (!input) return;
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
  }

  export async function prefill(text: string) {
    question = text.slice(0, QUESTION_MAX_LENGTH);
    await tick();
    resize();
    input?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    input?.focus();
  }

  function toggleSources(turn: Turn) {
    turn.showSources = !turn.showSources;
    if (turn.showSources) void chats.loadCitations(turn);
  }

  $effect(() => {
    // A freshly opened chat starts at its latest message.
    if (!chats.threadLoading && chats.turns.length > 0) void scrollToEnd();
  });
</script>

<div class="flex min-w-0 flex-col">
  {#if chats.threadLoading}
    <div class="flex flex-col gap-6 py-2">
      <Skeleton class="ml-auto h-10 w-2/3 rounded-2xl" />
      <Skeleton class="h-28 w-full rounded-2xl" />
      <Skeleton class="ml-auto h-10 w-1/2 rounded-2xl" />
    </div>
  {:else if chats.error}
    <ErrorBanner error={chats.error} />
  {:else if chats.turns.length === 0}
    <div class="flex flex-col items-center rounded-2xl border border-line bg-surface px-6 py-10 text-center shadow-card sm:px-10 sm:py-14">
      <span class="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-soft text-accent-text ring-1 ring-accent-line/50">
        <Icon name="sparkles" class="h-6 w-6" />
      </span>
      <h2 class="mt-5 font-display text-2xl font-medium tracking-tight text-fg">What do you want to learn?</h2>
      <p class="mt-2 max-w-md text-[15px] leading-relaxed text-muted">
        {#if hasSources}
          Answers cite the exact material they came from. Ask for a quiz or a study guide and it
          opens in the workspace beside the chat. Every chat is saved.
        {:else}
          Add your syllabus, readings or notes under Sources first; answers come only from them.
        {/if}
      </p>
      {#if hasSources}
        <div class="mt-8 grid w-full gap-2.5 sm:grid-cols-3">
          {#each starterPrompts as starter (starter.text)}
            <button
              type="button"
              onclick={() => prefill(starter.text)}
              class="group flex flex-col items-start gap-2.5 rounded-xl border border-line bg-bg/60 p-3.5 text-left text-[13px] font-medium leading-snug text-fg-soft transition-all hover:-translate-y-px hover:border-accent-line hover:bg-surface hover:shadow-card"
            >
              <Icon name={starter.icon} class="h-4 w-4 text-subtle transition-colors group-hover:text-accent-text" />
              {starter.text}
            </button>
          {/each}
        </div>
      {/if}
    </div>
  {:else}
    <div class="flex scroll-mb-40 flex-col gap-8">
      {#each chats.turns as turn, index (index)}
        <article class="flex animate-rise flex-col gap-4">
          <div class="flex justify-end">
            <p class="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tr-md bg-accent-soft px-4 py-2.5 text-[15px] leading-relaxed text-fg">
              {turn.question}
            </p>
          </div>

          <div class="flex gap-3">
            <span class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent text-on-accent shadow-card" aria-hidden="true">
              <Icon name="sparkles" class="h-4 w-4" />
            </span>
            <div class="flex min-w-0 flex-1 flex-col gap-3">
              {#if turn.error}
                <ErrorBanner error={turn.error} />
                <button
                  type="button"
                  onclick={() => chats.retry(turn)}
                  disabled={chats.sending}
                  class="inline-flex items-center gap-1.5 self-start rounded-lg px-2 py-1 text-xs font-medium text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-50"
                >
                  <Icon name="rotate-ccw" class="h-3.5 w-3.5" /> Try again
                </button>
              {:else if turn.answer === null}
                <div class="flex items-center gap-2.5 py-1 text-sm text-muted">
                  <span class="flex gap-1" aria-hidden="true">
                    <span class="h-1.5 w-1.5 animate-bounce rounded-full bg-accent [animation-delay:-0.3s]"></span>
                    <span class="h-1.5 w-1.5 animate-bounce rounded-full bg-accent [animation-delay:-0.15s]"></span>
                    <span class="h-1.5 w-1.5 animate-bounce rounded-full bg-accent"></span>
                  </span>
                  Reading your course material…
                </div>
              {:else if turn.noMatch}
                <p class="flex items-start gap-2 rounded-xl border border-line bg-surface-2 px-3.5 py-3 text-[14px] leading-relaxed text-muted">
                  <Icon name="search" class="mt-0.5 h-4 w-4 shrink-0 text-subtle" />
                  <span>
                    Nothing in this course's material matches that question{hasSources ? '' : ' yet'}.
                    Try other words, or add the source that covers it.
                  </span>
                </p>
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
                {#if turn.cached}
                  <p class="inline-flex items-center gap-1.5 self-start text-xs text-subtle">
                    <Icon name="clock" class="h-3.5 w-3.5" /> Same answer as when you asked this before; your materials haven't changed since.
                  </p>
                {/if}
                <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
                  {#if turn.model}
                    <span class="inline-flex items-center gap-1.5 text-xs text-subtle">
                      <Icon name="cpu" class="h-3.5 w-3.5" />
                      {turn.bigger ? `Bigger model · ${turn.model}` : turn.model}
                    </span>
                  {/if}
                  {#if biggerModel && !turn.bigger && turn.answer}
                    <button
                      type="button"
                      class="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg disabled:opacity-50"
                      disabled={chats.sending}
                      onclick={() => send(turn.question, true)}
                      title="Ask this question again with the bigger model chosen in Settings"
                    >
                      <Icon name="arrow-up" class="h-3.5 w-3.5" /> Ask a bigger model ({biggerModel})
                    </button>
                  {/if}
                </div>

                {#if turn.workspace.length > 0}
                  {@const showing = canvas.active?.turnIndex === index && canvas.open}
                  <button
                    type="button"
                    onclick={() => onopenworkspace(index)}
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

                {#if turn.traceId}
                  <div class="rounded-xl border border-line bg-surface">
                    <button
                      type="button"
                      class="flex w-full items-center gap-2 px-3.5 py-2.5 text-[13px] font-medium text-muted transition-colors hover:text-fg"
                      aria-expanded={turn.showSources}
                      onclick={() => toggleSources(turn)}
                    >
                      <Icon name="bookmark" class="h-4 w-4 text-subtle" />
                      {#if turn.citationsLoading}
                        Finding sources… <Spinner class="h-3.5 w-3.5" />
                      {:else}
                        Sources used
                        {#if turn.citationsLoaded}
                          <span class="rounded-full bg-surface-3 px-1.5 text-[11px] font-semibold">{turn.citations.length}</span>
                        {/if}
                      {/if}
                      <Icon name="chevron-down" class={`ml-auto h-4 w-4 text-subtle transition-transform ${turn.showSources ? 'rotate-180' : ''}`} />
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
                  </div>
                {/if}
              {/if}
            </div>
          </div>
        </article>
      {/each}
    </div>
  {/if}
  <div bind:this={end}></div>

  <form onsubmit={submit} class="sticky bottom-0 z-10 mt-6 bg-gradient-to-t from-bg from-60% to-transparent pb-4 pt-4">
    <label for="question" class="sr-only">Question</label>
    <div class="flex items-end gap-2 rounded-2xl border border-line-strong bg-surface p-1.5 pl-4 shadow-lift transition-[border-color,box-shadow] focus-within:border-accent focus-within:ring-3 focus-within:ring-accent/15">
      <textarea
        id="question"
        bind:this={input}
        bind:value={question}
        oninput={resize}
        onkeydown={onKeydown}
        rows="1"
        maxlength={QUESTION_MAX_LENGTH}
        autocomplete="off"
        placeholder={hasSources ? 'Ask something, or say: quiz me on …' : 'Add a source first'}
        disabled={!hasSources}
        class="max-h-[200px] min-w-0 flex-1 resize-none self-center bg-transparent py-2 text-[15px] leading-relaxed text-fg placeholder:text-subtle focus:outline-none disabled:cursor-not-allowed"
      ></textarea>
      <button
        type="submit"
        disabled={chats.sending || !question.trim()}
        aria-label="Ask"
        class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent text-on-accent transition-all hover:bg-accent-hover disabled:bg-surface-3 disabled:text-subtle"
      >
        {#if chats.sending}<Spinner />{:else}<Icon name="arrow-up" class="h-[18px] w-[18px]" strokeWidth={2.25} />{/if}
      </button>
    </div>
    <p class="mt-2 px-1 text-center text-xs text-subtle">
      Answers cite the exact course material they came from · Enter to send, Shift+Enter for a new line
    </p>
  </form>
</div>
