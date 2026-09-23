<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api/client';
  import type { paths } from '$lib/api/schema';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Select from '$lib/components/Select.svelte';
  import TextInput from '$lib/components/TextInput.svelte';
  import { formatBytes } from '$lib/utils/format';

  type CourseView =
    paths['/courses']['get']['responses'][200]['content']['application/json'][number];

  type Visibility = 'private' | 'invite_only' | 'public';

  let courses = $state<CourseView[]>([]);
  let loading = $state(true);
  let error = $state<unknown>(null);
  let newName = $state('');
  let newVisibility = $state<Visibility>('private');
  let creating = $state(false);
  let createError = $state<unknown>(null);

  const visibilityOptions = [
    { value: 'private' as Visibility, label: 'Private' },
    { value: 'invite_only' as Visibility, label: 'Invite only' },
    { value: 'public' as Visibility, label: 'Public' }
  ];

  let owned = $derived(courses.filter((course) => course.role === 'owner'));
  let enrolled = $derived(courses.filter((course) => course.role !== 'owner'));

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
      const { data, error: err } = await api.GET('/courses');
      if (err || !data) throw err ?? new Error('unexpected empty response');
      courses = data;
    } finally {
      loading = false;
    }
  }

  async function createCourse(event: SubmitEvent) {
    event.preventDefault();
    creating = true;
    createError = null;
    try {
      const { data, error: err } = await api.POST('/courses', {
        body: { name: newName, visibility: newVisibility }
      });
      if (err || !data) throw err ?? new Error('unexpected empty response');
      newName = '';
      await goto(`/courses/${data.course_id}`);
    } catch (caught) {
      createError = caught;
    } finally {
      creating = false;
    }
  }
</script>

<h1 class="mb-6 text-2xl font-bold text-slate-900 dark:text-slate-100">My courses</h1>

{#if error}
  <ErrorBanner {error} />
{:else if loading}
  <p class="text-sm text-slate-500">Loading…</p>
{:else}
  <div class="flex flex-col gap-6">
    <Card title="Create a course">
      <form onsubmit={createCourse} class="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div class="flex-1">
          <TextInput label="Course name" bind:value={newName} required maxlength={200} />
        </div>
        <Select label="Visibility" options={visibilityOptions} bind:value={newVisibility} />
        <Button type="submit" loading={creating}>Create</Button>
      </form>
      {#if createError}<div class="mt-3"><ErrorBanner error={createError} /></div>{/if}
    </Card>

    <section>
      <h2 class="mb-3 text-base font-semibold text-slate-900 dark:text-slate-100">Owned</h2>
      {#if owned.length === 0}
        <EmptyState message="No courses yet — create one above." />
      {:else}
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {#each owned as course (course.course_id)}
            <a
              href={`/courses/${course.course_id}`}
              class="group block rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/80 transition-all hover:-translate-y-0.5 hover:shadow-md hover:ring-indigo-200 dark:bg-slate-900 dark:ring-slate-700/80 dark:hover:ring-indigo-700"
            >
              <p class="font-medium text-slate-900 group-hover:text-indigo-700 dark:text-slate-100 dark:group-hover:text-indigo-300">
                {course.name}
              </p>
              <p class="mt-1 text-sm text-slate-500">
                {course.visibility} · {course.source_count} source{course.source_count === 1
                  ? ''
                  : 's'} · {formatBytes(course.stored_bytes ?? 0)}
              </p>
            </a>
          {/each}
        </div>
      {/if}
    </section>

    <section>
      <h2 class="mb-3 text-base font-semibold text-slate-900 dark:text-slate-100">Enrolled</h2>
      {#if enrolled.length === 0}
        <EmptyState
          title="Not enrolled anywhere"
          message="Browse public courses under Discover, or join with a code."
        />
      {:else}
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {#each enrolled as course (course.course_id)}
            <a
              href={`/courses/${course.course_id}`}
              class="group block rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/80 transition-all hover:-translate-y-0.5 hover:shadow-md hover:ring-indigo-200 dark:bg-slate-900 dark:ring-slate-700/80 dark:hover:ring-indigo-700"
            >
              <p class="font-medium text-slate-900 group-hover:text-indigo-700 dark:text-slate-100 dark:group-hover:text-indigo-300">
                {course.name}
              </p>
              <p class="mt-1 text-sm text-slate-500">
                {course.source_count} sources · {formatBytes(course.stored_bytes ?? 0)}
              </p>
            </a>
          {/each}
        </div>
      {/if}
    </section>
  </div>
{/if}
