<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api/client';
  import type { paths } from '$lib/api/schema';
  import Button from '$lib/components/Button.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Monogram from '$lib/components/Monogram.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { formatBytes } from '$lib/utils/format';
  import { plural } from '$lib/utils/labels';

  type TrashedCourse =
    paths['/trash']['get']['responses'][200]['content']['application/json'][number];
  type CourseMemory =
    paths['/course-memories']['get']['responses'][200]['content']['application/json'][number];

  let trashed = $state<TrashedCourse[]>([]);
  let memories = $state<CourseMemory[]>([]);
  let loading = $state(true);
  let error = $state<unknown>(null);
  let actionError = $state<unknown>(null);
  let busyId = $state<string | null>(null);

  // Keepsakes of courses that no longer exist anywhere (purged).
  let keepsakes = $derived(
    memories.filter((memory) => !trashed.some((course) => course.course_id === memory.course_id))
  );

  onMount(() => {
    load().catch((err) => {
      error = err;
      loading = false;
    });
  });

  async function load() {
    loading = true;
    try {
      const [trashRes, memoryRes] = await Promise.all([
        api.GET('/trash'),
        api.GET('/course-memories')
      ]);
      if (trashRes.error || !trashRes.data) throw trashRes.error ?? new Error('empty response');
      trashed = trashRes.data;
      const courses = await api.GET('/courses');
      const active = new Set((courses.data ?? []).map((course) => course.course_id));
      memories = (memoryRes.data ?? []).filter((memory) => !active.has(memory.course_id));
    } finally {
      loading = false;
    }
  }

  function daysLeft(purgeAfter: string): number {
    const ms = new Date(purgeAfter).getTime() - Date.now();
    return Math.max(0, Math.ceil(ms / 86_400_000));
  }

  async function restore(course: TrashedCourse) {
    busyId = course.course_id;
    actionError = null;
    try {
      const { error: err } = await api.POST('/trash/{course_id}/restore', {
        params: { path: { course_id: course.course_id } }
      });
      if (err) throw err;
      toast(`Restored ${course.name}.`);
      await load();
    } catch (caught) {
      actionError = caught;
    } finally {
      busyId = null;
    }
  }

  async function deleteForever(course: TrashedCourse) {
    if (!(await confirmDialog({
      title: 'Delete permanently?',
      message: `${course.name} and all of its files are erased from this computer now. Only its short course-memory summary is kept.`,
      confirmLabel: 'Delete permanently',
      danger: true
    }))) return;
    busyId = course.course_id;
    actionError = null;
    try {
      const { error: err } = await api.DELETE('/trash/{course_id}', {
        params: { path: { course_id: course.course_id } }
      });
      if (err) throw err;
      toast(`Deleted ${course.name}.`);
      await load();
    } catch (caught) {
      actionError = caught;
    } finally {
      busyId = null;
    }
  }
</script>

<PageHeader
  title="Trash"
  description="Deleted courses stay here for 30 days, then they are erased. A short summary of each course is kept as a keepsake."
/>

{#if error}
  <ErrorBanner {error} />
{:else if loading}
  <Skeleton class="h-40 w-full rounded-2xl" />
{:else}
  <div class="flex flex-col gap-10">
    {#if actionError}<ErrorBanner error={actionError} />{/if}

    {#if trashed.length === 0}
      <EmptyState icon="trash" title="Trash is empty" message="Courses you delete show up here until they are erased." />
    {:else}
      <section class="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
        <ul class="divide-y divide-line">
          {#each trashed as course (course.course_id)}
            {@const left = daysLeft(course.purge_after)}
            <li class="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:px-6">
              <div class="flex min-w-0 flex-1 items-center gap-3">
                <Monogram name={course.name} />
                <div class="min-w-0">
                  <p class="truncate font-medium text-fg">{course.name}</p>
                  <p class="mt-0.5 text-xs text-subtle">
                    {plural(course.source_count, 'source')} · {formatBytes(course.stored_bytes)} ·
                    {left === 0 ? 'erased at the next cleanup' : `erased in ${plural(left, 'day')}`}
                  </p>
                </div>
              </div>
              <div class="flex shrink-0 gap-2">
                <Button variant="secondary" size="sm" loading={busyId === course.course_id} onclick={() => restore(course)}>
                  <Icon name="rotate-ccw" class="h-3.5 w-3.5" /> Restore
                </Button>
                <Button variant="ghost" size="sm" disabled={busyId === course.course_id} onclick={() => deleteForever(course)} class="text-danger-text hover:bg-danger-soft hover:text-danger-text">
                  Delete permanently
                </Button>
              </div>
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    {#if keepsakes.length > 0}
      <section>
        <h2 class="mb-1 text-[15px] font-semibold text-fg">Course memories</h2>
        <p class="mb-4 text-sm text-muted">What remains of courses that have been erased.</p>
        <div class="grid gap-4 sm:grid-cols-2">
          {#each keepsakes as memory (memory.memory_id)}
            <details class="group rounded-2xl border border-line bg-surface p-5 shadow-card">
              <summary class="flex cursor-pointer list-none items-center gap-3">
                <Monogram name={memory.name} />
                <span class="min-w-0 flex-1 truncate font-medium text-fg">{memory.name}</span>
                <Icon name="chevron-down" class="h-4 w-4 text-subtle transition-transform group-open:rotate-180" />
              </summary>
              <pre class="mt-4 max-h-72 overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-muted">{memory.summary}</pre>
            </details>
          {/each}
        </div>
      </section>
    {/if}
  </div>
{/if}
