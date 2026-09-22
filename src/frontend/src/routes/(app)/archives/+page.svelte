<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api/client';
  import type { paths } from '$lib/api/schema';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
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
    return iso ? new Date(iso).toLocaleDateString() : '—';
  }
</script>

<h1 class="mb-6 text-2xl font-bold text-slate-900">Archives</h1>

{#if error}
  <ErrorBanner {error} />
{:else if loading}
  <p class="text-sm text-slate-500">Loading…</p>
{:else}
  <div class="flex flex-col gap-6">
    {#if actionError}<ErrorBanner error={actionError} />{/if}

    <section>
      <h2 class="mb-3 text-base font-semibold text-slate-900">Archived courses</h2>
      {#if archives.length === 0}
        <EmptyState
          title="Nothing archived"
          message="Deleted courses leave a compressed archive that expires after a retention window."
        />
      {:else}
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {#each archives as archive (archive.course_id)}
            <Card>
              <p class="font-medium text-slate-900">{archive.name}</p>
              <p class="mt-1 text-sm text-slate-500">
                archived {formatDate(archive.archived_at)} · expires
                {formatDate(archive.expires_at)}
              </p>
              <p class="mt-1 text-sm text-slate-500">
                {archive.source_count} source{archive.source_count === 1 ? '' : 's'}
              </p>
              <Button
                variant="secondary"
                class="mt-3"
                loading={copyingId === archive.course_id}
                onclick={() => copy(archive.course_id)}
              >
                Copy back
              </Button>
            </Card>
          {/each}
        </div>
      {/if}
    </section>

    <section>
      <h2 class="mb-3 text-base font-semibold text-slate-900">Course memories</h2>
      {#if memories.length === 0}
        <EmptyState
          title="No memories yet"
          message="Course memories are distilled when a course is deleted and never disappear with it."
        />
      {:else}
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {#each memories as memory (memory.memory_id)}
            <Card>
              <p class="font-medium text-slate-900">{memory.name}</p>
              <p class="mt-1 line-clamp-3 text-sm text-slate-500">{memory.summary}</p>
            </Card>
          {/each}
        </div>
      {/if}
    </section>
  </div>
{/if}
