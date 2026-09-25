<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api/client';
  import type { paths } from '$lib/api/schema';
  import Button from '$lib/components/Button.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Monogram from '$lib/components/Monogram.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import TextInput from '$lib/components/TextInput.svelte';
  import { formatBytes } from '$lib/utils/format';
  import { plural } from '$lib/utils/labels';

  type CourseView =
    paths['/courses']['get']['responses'][200]['content']['application/json'][number];

  let courses = $state<CourseView[]>([]);
  let loading = $state(true);
  let error = $state<unknown>(null);
  let newName = $state('');
  let creating = $state(false);
  let createError = $state<unknown>(null);
  let showCreate = $state(false);

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
      // First run: nothing to show yet, so lead with the create form.
      if (data.length === 0) showCreate = true;
    } finally {
      loading = false;
    }
  }

  async function createCourse(event: SubmitEvent) {
    event.preventDefault();
    creating = true;
    createError = null;
    try {
      const { data, error: err } = await api.POST('/courses', { body: { name: newName } });
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

{#snippet courseCard(course: CourseView)}
  <a
    href={`/courses/${course.course_id}`}
    class="group flex flex-col rounded-2xl border border-line bg-surface p-5 shadow-card transition-all duration-200 hover:-translate-y-0.5 hover:border-line-strong hover:shadow-lift"
  >
    <Monogram name={course.name} />
    <p class="mt-4 line-clamp-2 font-medium leading-snug text-fg">{course.name}</p>
    <div class="mt-auto flex items-center gap-3 pt-3 text-xs text-muted">
      <span class="inline-flex items-center gap-1">
        <Icon name="file-text" class="h-3.5 w-3.5 text-subtle" />
        {plural(course.source_count, 'source')}
      </span>
      <span class="inline-flex items-center gap-1">
        <Icon name="hard-drive" class="h-3.5 w-3.5 text-subtle" />
        {formatBytes(course.stored_bytes ?? 0)}
      </span>
      <Icon
        name="arrow-right"
        class="ml-auto h-4 w-4 -translate-x-1 text-subtle opacity-0 transition-all group-hover:translate-x-0 group-hover:text-accent-text group-hover:opacity-100"
      />
    </div>
  </a>
{/snippet}

<PageHeader
  title="My courses"
  description="Everything stays on this computer. Upload your materials and ask questions about them."
>
  {#snippet actions()}
    {#if !loading && !error}
      <Button onclick={() => (showCreate = !showCreate)} variant={showCreate ? 'secondary' : 'primary'}>
        <Icon name={showCreate ? 'x' : 'plus'} class="h-4 w-4" />
        {showCreate ? 'Cancel' : 'New course'}
      </Button>
    {/if}
  {/snippet}
</PageHeader>

{#if error}
  <ErrorBanner {error} />
{:else if loading}
  <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
    {#each [0, 1, 2] as i (i)}<Skeleton class="h-40 rounded-2xl" />{/each}
  </div>
{:else}
  <div class="flex flex-col gap-10">
    {#if showCreate}
      <section class="animate-rise rounded-2xl border border-line bg-surface p-5 shadow-card sm:p-6">
        <h2 class="text-[15px] font-semibold text-fg">Create a course</h2>
        <p class="mt-1 text-sm text-muted">
          Give it a name, then upload your syllabus, slides, and notes.
        </p>
        <form onsubmit={createCourse} class="mt-5 flex flex-col gap-3 sm:flex-row sm:items-end">
          <div class="flex-1">
            <TextInput
              label="Course name"
              bind:value={newName}
              required
              maxlength={200}
              placeholder="e.g. CS 161 — Operating Systems"
            />
          </div>
          <Button type="submit" loading={creating} class="h-10">Create course</Button>
        </form>
        {#if createError}<div class="mt-4"><ErrorBanner error={createError} /></div>{/if}
      </section>
    {/if}

    {#if courses.length === 0}
      <EmptyState
        icon="book"
        title="No courses yet"
        message="Create a course, upload your materials, and the tutor will answer from them."
      >
        {#if !showCreate}
          <Button variant="secondary" onclick={() => (showCreate = true)}>
            <Icon name="plus" class="h-4 w-4" /> New course
          </Button>
        {/if}
      </EmptyState>
    {:else}
      <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {#each courses as course (course.course_id)}{@render courseCard(course)}{/each}
      </div>
    {/if}
  </div>
{/if}
