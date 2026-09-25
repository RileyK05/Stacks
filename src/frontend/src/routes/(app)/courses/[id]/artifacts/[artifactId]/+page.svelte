<script lang="ts">
  import { isTauri } from '@tauri-apps/api/core';
  import { onDestroy, onMount, tick } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api/client';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Popover from '$lib/components/Popover.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Spinner from '$lib/components/Spinner.svelte';
  import ArtifactContent from '$lib/components/artifacts/ArtifactContent.svelte';
  import {
    EXPORT_FORMATS,
    KIND_ICONS,
    KIND_LABELS,
    OpenArtifact,
    type ArtifactKind,
    type EditScope
  } from '$lib/stores/artifact.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { timeAgo } from '$lib/utils/format';

  const courseId = page.params.id ?? '';
  const artifactId = page.params.artifactId ?? '';
  const open = new OpenArtifact(courseId, artifactId);

  let courseName = $state('');
  let request = $state('');
  let scopePart = $state<'all' | 'here'>('all');
  let section = $state(0);
  let slide = $state(0);
  let highlighted = $state<number | null>(null);
  let versionsOpen = $state(false);
  let exportOpen = $state(false);
  let exported = $state<{ path: string; filename: string } | null>(null);

  onMount(async () => {
    await open.load();
    const course = await api.GET('/courses/{course_id}', { params: { path: { course_id: courseId } } });
    courseName = course.data?.name ?? '';
  });

  onDestroy(() => {
    void open.flush();
  });

  const kind = $derived(open.kind);
  const scopable = $derived(kind === 'doc' || kind === 'slides');
  const scope = $derived<EditScope | null>(
    scopePart === 'here' && kind === 'doc'
      ? { part: 'section', index: section }
      : scopePart === 'here' && kind === 'slides'
        ? { part: 'slide', index: slide }
        : null
  );

  const status = $derived.by(() => {
    if (open.conflict) return { text: 'Changed in another window', tone: 'warning' as const };
    if (open.saveError) return { text: 'Not saved', tone: 'danger' as const };
    if (open.saving || open.dirty) return { text: 'Saving…', tone: 'neutral' as const };
    return { text: 'Saved', tone: 'success' as const };
  });

  const suggestions: Record<ArtifactKind, string[]> = {
    doc: ['Draft a study guide from the course', 'Make this more concise', 'Add a short summary at the top'],
    sheet: ['Make a glossary of the key terms', 'Add a column with where each is covered', 'Sort the rows by date'],
    slides: ['Draft 5 slides on the main ideas', 'Make this slide shorter', 'Add speaker notes'],
    quiz: ['Write 5 questions on the main ideas', 'Make the questions harder', 'Add explanations'],
    flashcards: ['Make 10 cards of key terms', 'Add cards for the formulas', 'Simplify the backs'],
    code: ['Explain this with comments', 'Fix any errors'],
    chart: ['Label the axes', 'Use the numbers from the course']
  };

  async function propose(event?: SubmitEvent) {
    event?.preventDefault();
    const text = request.trim();
    if (!text) return;
    await open.propose(text, scope);
    if (open.proposal) request = '';
  }

  async function accept() {
    if (await open.accept()) toast('Change applied. Undo it from Versions if you change your mind.');
  }

  async function showCitation(n: number) {
    highlighted = n;
    await tick();
    document.getElementById(`source-${n}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setTimeout(() => {
      if (highlighted === n) highlighted = null;
    }, 2200);
  }

  async function doExport(format: string, close: () => void) {
    close();
    try {
      let path: string | null = null;
      if (isTauri()) {
        const { save } = await import('@tauri-apps/plugin-dialog');
        const chosen = await save({
          title: 'Export',
          defaultPath: `${open.title || 'artifact'}.${format}`,
          filters: [{ name: format.toUpperCase(), extensions: [format] }]
        });
        if (chosen === null) return;
        path = chosen;
      }
      exported = await open.exportTo(format, path);
      toast(`Saved ${exported.filename}`);
    } catch (caught) {
      open.saveError = caught;
    }
  }

  async function reveal(path: string) {
    if (isTauri()) {
      const { revealItemInDir } = await import('@tauri-apps/plugin-opener');
      await revealItemInDir(path);
    } else {
      await api.POST('/settings/reveal', { body: { path } });
    }
  }

  async function restore(version: number, close: () => void) {
    close();
    try {
      await open.restore(version);
      toast(`Restored version ${version}.`);
    } catch (caught) {
      open.saveError = caught;
    }
  }

  async function remove() {
    const ok = await confirmDialog({
      title: `Delete "${open.title}"?`,
      message: 'The artifact and all its versions are deleted from this course.',
      confirmLabel: 'Delete',
      danger: true
    });
    if (!ok) return;
    await open.remove();
    toast('Deleted.');
    await goto(`/courses/${courseId}?tab=artifacts`);
  }
</script>

{#if open.error}
  <ErrorBanner error={open.error} />
{:else if open.loading || !open.artifact || !kind}
  <div class="flex flex-col gap-5">
    <Skeleton class="h-8 w-80" />
    <Skeleton class="h-[60vh] w-full rounded-2xl" />
  </div>
{:else}
  <div class="flex flex-col gap-5">
    <header class="flex flex-col gap-3">
      <a href={`/courses/${courseId}?tab=artifacts`} class="inline-flex items-center gap-1.5 self-start text-[13px] text-muted hover:text-fg">
        <Icon name="chevron-left" class="h-4 w-4" /> {courseName || 'Course'}
      </a>
      <div class="flex flex-wrap items-center gap-3">
        <span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent-text ring-1 ring-accent-line/50">
          <Icon name={KIND_ICONS[kind]} class="h-5 w-5" />
        </span>
        <input
          bind:value={open.title}
          oninput={() => open.touch()}
          aria-label="Title"
          maxlength={200}
          class="min-w-0 flex-1 rounded-lg border border-transparent bg-transparent px-2 py-1 font-display text-[1.6rem] font-medium tracking-tight text-fg hover:border-line focus:border-accent focus:outline-none"
        />
        <Badge tone={status.tone} dot>{status.text}</Badge>
        <span class="hidden text-xs text-subtle sm:inline">{KIND_LABELS[kind]} · v{open.artifact.version}</span>
        <div class="flex items-center gap-1">
          <Popover bind:open={versionsOpen} label="Versions" align="end" width="w-80">
            {#snippet trigger(props)}
              <Button variant="ghost" size="sm" {...props} onclick={() => { props.onclick(); if (!versionsOpen) return; void open.loadVersions(); }}>
                <Icon name="clock" class="h-4 w-4" /> Versions
              </Button>
            {/snippet}
            {#snippet children(close)}
              <ol class="max-h-80 overflow-y-auto py-1">
                {#each open.versions as version (version.version)}
                  <li class="flex items-center gap-3 px-3 py-2 hover:bg-surface-2">
                    <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-surface-3 text-[11px] font-semibold text-muted">{version.version}</span>
                    <span class="min-w-0 flex-1">
                      <span class="block truncate text-[13px] text-fg">
                        {version.note || (version.author === 'model' ? 'Edit by Stacks' : 'Your edit')}
                      </span>
                      <span class="block text-[11px] text-subtle">
                        {version.author === 'model' ? 'Stacks' : 'You'} · {timeAgo(version.created_at)}
                      </span>
                    </span>
                    {#if version.version !== open.artifact?.version}
                      <button type="button" onclick={() => restore(version.version, close)} class="rounded-md px-2 py-1 text-[12px] font-medium text-accent-text hover:bg-accent-soft">Restore</button>
                    {:else}
                      <span class="text-[11px] text-subtle">Current</span>
                    {/if}
                  </li>
                {:else}
                  <li class="px-3 py-3 text-[13px] text-subtle">Loading…</li>
                {/each}
              </ol>
            {/snippet}
          </Popover>
          <Popover bind:open={exportOpen} label="Export" align="end" width="w-56">
            {#snippet trigger(props)}
              <Button variant="ghost" size="sm" {...props}><Icon name="download" class="h-4 w-4" /> Export</Button>
            {/snippet}
            {#snippet children(close)}
              <div class="py-1">
                {#each EXPORT_FORMATS[kind] as option (option.format)}
                  <button type="button" onclick={() => doExport(option.format, close)} class="flex w-full px-3 py-2 text-left text-[13px] text-fg-soft hover:bg-surface-2">
                    {option.label}
                  </button>
                {/each}
              </div>
            {/snippet}
          </Popover>
          <Button variant="ghost" size="sm" onclick={remove} class="text-danger-text hover:bg-danger-soft hover:text-danger-text" aria-label="Delete">
            <Icon name="trash" class="h-4 w-4" />
          </Button>
        </div>
      </div>
    </header>

    {#if open.conflict}
      <div class="flex flex-wrap items-center gap-3 rounded-xl border border-warning/40 bg-warning-soft px-4 py-3 text-sm text-warning-text">
        <Icon name="alert-triangle" class="h-4 w-4" />
        <span class="flex-1">This {KIND_LABELS[kind].toLowerCase()} was saved from somewhere else since you opened it. Your latest changes here are not saved.</span>
        <Button variant="secondary" size="sm" onclick={() => open.reload()}>Load the latest</Button>
      </div>
    {/if}
    {#if open.saveError}<ErrorBanner error={open.saveError} />{/if}
    {#if exported}
      <div class="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-surface-2 px-4 py-2.5 text-sm text-muted">
        <Icon name="check" class="h-4 w-4 text-success-text" />
        <span class="min-w-0 flex-1 truncate">Saved <span class="font-medium text-fg">{exported.filename}</span></span>
        <Button variant="secondary" size="sm" onclick={() => exported && reveal(exported.path)}>Show in folder</Button>
        <Button variant="ghost" size="sm" onclick={() => (exported = null)} aria-label="Dismiss"><Icon name="x" class="h-4 w-4" /></Button>
      </div>
    {/if}

    <div class="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div class="relative min-w-0">
        {#if open.proposal}
          {@const proposal = open.proposal}
          <section class="flex flex-col gap-4 rounded-2xl border border-accent-line bg-accent-soft/30 p-4 shadow-lift">
            <div class="flex flex-wrap items-center gap-2">
              <Icon name="sparkles" class="h-4 w-4 text-accent-text" />
              <p class="text-sm font-semibold text-fg">Proposed change</p>
              <span class="truncate text-[13px] text-muted">“{open.lastRequest}” · {proposal.model}</span>
              <div class="ml-auto flex gap-2">
                <Button variant="ghost" size="sm" onclick={() => open.discard()}>Discard</Button>
                <Button size="sm" loading={open.saving} onclick={accept}><Icon name="check" class="h-4 w-4" /> Accept</Button>
              </div>
            </div>
            {#if (proposal.uncited_lines ?? 0) > 0}
              <p class="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning-soft px-3 py-2.5 text-xs leading-relaxed text-warning-text">
                <Icon name="alert-triangle" class="mt-px h-3.5 w-3.5 shrink-0" />
                <span>
                  {proposal.uncited_lines === 1 ? '1 new line isn’t' : `${proposal.uncited_lines} new lines aren’t`}
                  tied to a source in your course. Check {proposal.uncited_lines === 1 ? 'it' : 'them'} before accepting.
                </span>
              </p>
            {/if}
            <div class="grid gap-4 2xl:grid-cols-2">
              <div class="min-w-0 rounded-xl border border-line bg-surface p-4 opacity-80">
                <p class="mb-3 text-[11px] font-semibold uppercase tracking-wider text-subtle">Now</p>
                <ArtifactContent kind={kind} title={open.title} content={open.content} editable={false} />
              </div>
              <div class="min-w-0 rounded-xl border border-accent-line bg-surface p-4">
                <p class="mb-3 text-[11px] font-semibold uppercase tracking-wider text-accent-text">After</p>
                <ArtifactContent kind={kind} title={open.title} content={structuredClone($state.snapshot(proposal.content))} editable={false} />
              </div>
            </div>
          </section>
        {:else}
          <ArtifactContent
            {kind}
            title={open.title}
            content={open.content}
            onchange={() => open.touch()}
            oncite={showCitation}
            onsection={(index) => (section = index)}
            bind:currentSlide={slide}
          />
        {/if}
      </div>

      <aside class="flex flex-col gap-4 xl:sticky xl:top-5">
        <form onsubmit={propose} class="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-4 shadow-card">
          <p class="flex items-center gap-2 text-sm font-semibold text-fg">
            <Icon name="sparkles" class="h-4 w-4 text-accent-text" /> Ask Stacks
          </p>
          <textarea
            bind:value={request}
            rows="3"
            maxlength={2000}
            placeholder="What should change?"
            aria-label="What should change"
            disabled={open.proposing || !!open.proposal}
            onkeydown={(e) => e.key === 'Enter' && (e.metaKey || e.ctrlKey) && propose()}
            class="resize-none rounded-lg border border-line-strong bg-surface px-3 py-2 text-[13px] text-fg placeholder:text-subtle focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent/15 disabled:opacity-60"
          ></textarea>
          {#if scopable}
            <div class="flex rounded-lg border border-line bg-bg/40 p-0.5 text-[12px]">
              <button type="button" onclick={() => (scopePart = 'all')} class={`flex-1 rounded-md px-2 py-1 font-medium ${scopePart === 'all' ? 'bg-surface text-fg shadow-card' : 'text-muted'}`}>
                Whole {kind === 'doc' ? 'doc' : 'deck'}
              </button>
              <button type="button" onclick={() => (scopePart = 'here')} class={`flex-1 rounded-md px-2 py-1 font-medium ${scopePart === 'here' ? 'bg-surface text-fg shadow-card' : 'text-muted'}`}>
                {kind === 'doc' ? `This section (${section + 1})` : `Slide ${slide + 1}`}
              </button>
            </div>
          {/if}
          {#if open.proposalError}<ErrorBanner error={open.proposalError} />{/if}
          <Button type="submit" loading={open.proposing} disabled={!request.trim() || !!open.proposal}>
            {open.proposing ? 'Stacks is drafting…' : 'Propose a change'}
          </Button>
          {#if !request.trim() && !open.proposal}
            <div class="flex flex-wrap gap-1.5">
              {#each suggestions[kind] as suggestion (suggestion)}
                <button type="button" onclick={() => (request = suggestion)} class="rounded-full border border-line px-2.5 py-1 text-[11px] text-muted hover:border-accent-line hover:text-fg">
                  {suggestion}
                </button>
              {/each}
            </div>
          {/if}
          <p class="text-[11px] leading-relaxed text-subtle">
            You review every change before it's applied. Anything new comes from your course and is cited.
          </p>
        </form>

        <section class="rounded-2xl border border-line bg-surface shadow-card">
          <p class="flex items-center gap-2 border-b border-line px-4 py-3 text-sm font-semibold text-fg">
            <Icon name="bookmark" class="h-4 w-4 text-subtle" /> Sources
            <span class="rounded-full bg-surface-3 px-1.5 text-[11px] font-semibold text-muted">{open.citations.length}</span>
          </p>
          {#if open.citations.length === 0}
            <p class="px-4 py-3 text-[13px] leading-relaxed text-subtle">
              Nothing cited yet. What Stacks adds from your course shows up here, numbered.
            </p>
          {:else}
            <ol class="max-h-[50vh] divide-y divide-line overflow-y-auto">
              {#each open.citations as cited (cited.number)}
                <li id={`source-${cited.number}`} class={`px-4 py-3 transition-colors ${highlighted === cited.number ? 'bg-accent-soft' : ''}`}>
                  <div class="flex items-center gap-2 text-xs">
                    <span class="flex h-5 min-w-5 items-center justify-center rounded-md bg-accent-soft px-1 font-mono text-[11px] font-medium text-accent-text">{cited.number}</span>
                    {#if cited.citation}
                      <span class="truncate font-medium text-fg-soft">{cited.citation.filename}</span>
                      <span class="shrink-0 text-subtle">{cited.citation.label}</span>
                    {:else}
                      <span class="text-subtle">Source removed from the course</span>
                    {/if}
                  </div>
                  {#if cited.citation}
                    <p class="mt-1.5 line-clamp-4 border-l-2 border-line-strong pl-2.5 text-[12px] leading-relaxed text-muted">{cited.citation.text}</p>
                  {/if}
                </li>
              {/each}
            </ol>
          {/if}
        </section>
      </aside>
    </div>
  </div>
{/if}

{#if open.proposing}
  <div class="pointer-events-none fixed bottom-6 left-1/2 z-50 -translate-x-1/2 animate-rise rounded-full border border-line bg-surface px-4 py-2 text-[13px] text-muted shadow-lift">
    <Spinner class="mr-2 inline h-3.5 w-3.5" /> Stacks is drafting a change…
  </div>
{/if}
