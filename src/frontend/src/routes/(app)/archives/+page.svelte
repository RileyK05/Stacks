<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api/client';
  import type { paths } from '$lib/api/schema';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Monogram from '$lib/components/Monogram.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import { plural } from '$lib/utils/labels';
  import { toast } from '$lib/stores/toast.svelte';

  type ArchivedCourse =
    paths['/course-archives']['get']['responses'][200]['content']['application/json'][number];
  type CourseMemory =
    paths['/course-memories']['get']['responses'][200]['content']['application/json'][number];

  let archives = $state<ArchivedCourse[]>([]);
  let memories = $state<CourseMemory[]>([]);
  let loading = $state(true);
  let error = $state<unknown>(null);
  let actionError = $state<unknown>(null);
  let copyingId = $state<string | null>(null);

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
      const archivesRes = await api.GET('/course-archives');
      if (!archivesRes.data) {
        throw new Error('unexpected empty response');
      }
      archives = archivesRes.data;
      const memoriesRes = await api.GET('/course-memories');
      memories = memoriesRes.data ?? [];
    } finally {
      loading = false;
    }
  }

  async function copy(courseId: string) {
    copyingId = courseId;
    actionError = null;
    try {
      const { data, error: err } = await api.POST('/course-archives/{course_id}/copy', {
        params: { path: { course_id: courseId } },
        body: {}
      });
      if (err || !data) throw err ?? new Error('unexpected empty response');
      toast(`Copied as "${data.name}" — find it under My courses.`);
    } catch (caught) {
      actionError = caught;
    } finally {
      copyingId = null;
    }
  }

  function formatDate(iso: string | undefined): string {
    return iso
      ? new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
      : '—';
  }

  function daysLeft(iso: string): number {
    return Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);
  }
</script>

<PageHeader
  title="Archives"
  description="Deleted courses stay recoverable for a while, and what you learned is kept as a memory."
/>

{#if error}
  <ErrorBanner {error} />
{:else if loading}
  <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
    {#each [0, 1, 2] as i (i)}<Skeleton class="h-44 rounded-2xl" />{/each}
  </div>
{:else}
  <div class="flex flex-col gap-10">
    {#if actionError}<ErrorBanner error={actionError} />{/if}

    <section>
      <div class="mb-4 flex items-baseline gap-2">
        <h2 class="text-[15px] font-semibold text-fg">Archived courses</h2>
        <span class="text-sm text-subtle">{archives.length}</span>
      </div>
      {#if archives.length === 0}
        <EmptyState
          icon="archive"
          title="Nothing archived"
          message="Deleted courses leave a compressed archive that expires after a retention window."
        />
      {:else}
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {#each archives as archive (archive.course_id)}
            {@const remaining = daysLeft(archive.expires_at)}
            <div class="flex flex-col rounded-2xl border border-line bg-surface p-5 shadow-card">
              <div class="flex items-start justify-between gap-3">
                <Monogram name={archive.name} class="opacity-70 grayscale-[40%]" />
                <Badge tone={remaining <= 14 ? 'warning' : 'neutral'} icon="clock">
                  {remaining > 0 ? `${plural(remaining, 'day')} left` : 'Expiring'}
                </Badge>
              </div>
              <p class="mt-4 line-clamp-2 font-medium leading-snug text-fg">{archive.name}</p>
              <p class="mt-1 text-xs text-muted">
                {plural(archive.source_count, 'source')} · archived {formatDate(archive.archived_at)}
              </p>
              <p class="mt-0.5 text-xs text-subtle">Expires {formatDate(archive.expires_at)}</p>
              <div class="mt-auto pt-4">
                <Button
                  variant="secondary"
                  size="sm"
                  loading={copyingId === archive.course_id}
                  onclick={() => copy(archive.course_id)}
                >
                  <Icon name="copy" class="h-3.5 w-3.5" /> Copy back
                </Button>
              </div>
            </div>
          {/each}
        </div>
      {/if}
    </section>

    <section>
      <div class="mb-4 flex items-baseline gap-2">
        <h2 class="text-[15px] font-semibold text-fg">Course memories</h2>
        <span class="text-sm text-subtle">{memories.length}</span>
      </div>
      {#if memories.length === 0}
        <EmptyState
          icon="bookmark"
          title="No memories yet"
          message="Course memories are distilled when a course is deleted and never disappear with it."
        />
      {:else}
        <div class="grid gap-4 sm:grid-cols-2">
          {#each memories as memory (memory.memory_id)}
            <article class="flex flex-col rounded-2xl border border-line bg-surface p-5 shadow-card">
              <div class="flex items-center gap-3">
                <Monogram name={memory.name} size="sm" />
                <p class="min-w-0 truncate font-medium text-fg">{memory.name}</p>
              </div>
              <p class="mt-3 line-clamp-4 text-sm leading-relaxed text-muted">{memory.summary}</p>
              {#if memory.key_concepts && memory.key_concepts.length > 0}
                <div class="mt-4 flex flex-wrap gap-1.5">
                  {#each memory.key_concepts.slice(0, 6) as concept (concept)}
                    <span class="rounded-full bg-surface-2 px-2 py-0.5 text-xs text-muted ring-1 ring-inset ring-line">{concept}</span>
                  {/each}
                </div>
              {/if}
            </article>
          {/each}
        </div>
      {/if}
    </section>
  </div>
{/if}
