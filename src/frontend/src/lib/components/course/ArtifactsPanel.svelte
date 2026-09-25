<script lang="ts">
  import { goto } from '$app/navigation';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import {
    KIND_ICONS,
    KIND_LABELS,
    createArtifact,
    type ArtifactKind,
    type ArtifactSummary
  } from '$lib/stores/artifact.svelte';
  import { timeAgo } from '$lib/utils/format';

  interface Props {
    courseId: string;
    artifacts: ArtifactSummary[];
    loading: boolean;
  }

  let { courseId, artifacts, loading }: Props = $props();

  let creating = $state<ArtifactKind | null>(null);
  let error = $state<unknown>(null);

  const newKinds: { kind: ArtifactKind; hint: string }[] = [
    { kind: 'doc', hint: 'Notes, study guides, summaries' },
    { kind: 'sheet', hint: 'Tables, glossaries, timelines' },
    { kind: 'slides', hint: 'A deck you can present' },
    { kind: 'quiz', hint: 'Practice questions' },
    { kind: 'flashcards', hint: 'Terms to memorise' }
  ];

  async function create(kind: ArtifactKind) {
    creating = kind;
    error = null;
    try {
      const created = await createArtifact(courseId, kind);
      await goto(`/courses/${courseId}/artifacts/${created.artifact_id}`);
    } catch (caught) {
      error = caught;
    } finally {
      creating = null;
    }
  }
</script>

<div class="flex flex-col gap-6">
  <section>
    <p class="mb-2.5 text-[13px] font-medium text-fg-soft">Create</p>
    <div class="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-5">
      {#each newKinds as item (item.kind)}
        <button
          type="button"
          onclick={() => create(item.kind)}
          disabled={creating !== null}
          class="group flex flex-col items-start gap-2 rounded-xl border border-line bg-surface p-3.5 text-left shadow-card transition-all hover:-translate-y-px hover:border-accent-line hover:shadow-lift disabled:opacity-60"
        >
          <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-soft text-accent-text">
            <Icon name={KIND_ICONS[item.kind]} class="h-4 w-4" />
          </span>
          <span class="text-sm font-semibold text-fg">{creating === item.kind ? 'Creating…' : `New ${KIND_LABELS[item.kind].toLowerCase()}`}</span>
          <span class="text-xs text-subtle">{item.hint}</span>
        </button>
      {/each}
    </div>
    {#if error}<div class="mt-3"><ErrorBanner {error} /></div>{/if}
  </section>

  <section>
    <p class="mb-2.5 text-[13px] font-medium text-fg-soft">In this course</p>
    {#if loading}
      <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {#each [0, 1, 2] as row (row)}<Skeleton class="h-28 rounded-2xl" />{/each}
      </div>
    {:else if artifacts.length === 0}
      <EmptyState
        icon="package"
        title="No artifacts yet"
        message="Create one above, or save a quiz, table or study guide from a chat. Everything you make stays in this course, with its sources."
      />
    {:else}
      <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {#each artifacts as artifact (artifact.artifact_id)}
          <a
            href={`/courses/${courseId}/artifacts/${artifact.artifact_id}`}
            class="group flex flex-col gap-3 rounded-2xl border border-line bg-surface p-4 shadow-card transition-all hover:-translate-y-px hover:border-accent-line hover:shadow-lift"
          >
            <div class="flex items-center gap-2.5">
              <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-soft text-accent-text ring-1 ring-accent-line/40">
                <Icon name={KIND_ICONS[artifact.kind]} class="h-[18px] w-[18px]" />
              </span>
              <span class="text-xs font-medium uppercase tracking-wide text-subtle">{KIND_LABELS[artifact.kind]}</span>
              {#if artifact.origin?.by === 'chat'}
                <span class="ml-auto rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted">from a chat</span>
              {/if}
            </div>
            <p class="line-clamp-2 font-display text-lg font-medium leading-snug tracking-tight text-fg">{artifact.title}</p>
            <p class="mt-auto text-xs text-subtle">Edited {timeAgo(artifact.updated_at)} · v{artifact.version}</p>
          </a>
        {/each}
      </div>
    {/if}
  </section>
</div>
