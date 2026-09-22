<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api/client';
  import type { paths } from '$lib/api/schema';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import TextInput from '$lib/components/TextInput.svelte';

  type CourseView =
    paths['/courses/public']['get']['responses'][200]['content']['application/json'][number];

  let publicCourses = $state<CourseView[]>([]);
  let enrolledIds = $state<Set<string>>(new Set());
  let loading = $state(true);
  let error = $state<unknown>(null);
  let joinCode = $state('');
  let joining = $state(false);
  let joinError = $state<unknown>(null);
  let search = $state('');

  let visibleCourses = $derived(
    search.trim()
      ? publicCourses.filter((course) =>
          course.name.toLowerCase().includes(search.trim().toLowerCase())
        )
      : publicCourses
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
      const publicRes = await api.GET('/courses/public');
      if (!publicRes.data) {
        throw new Error('unexpected empty response');
      }
      publicCourses = publicRes.data;
      const myRes = await api.GET('/courses');
      enrolledIds = new Set((myRes.data ?? []).map((course) => course.course_id));
    } finally {
      loading = false;
    }
  }

  function groupCode(raw: string): string {
    return raw
      .toUpperCase()
      .replace(/[^A-Z0-9]/g, '')
      .slice(0, 16)
      .replace(/(.{4})(?=.)/g, '$1-');
  }

  async function joinByCode(event: SubmitEvent) {
    event.preventDefault();
    joining = true;
    joinError = null;
    try {
      const { error: err } = await api.POST('/courses/join', {
        body: { join_code: joinCode }
      });
      if (err) throw err;
      joinCode = '';
      await load();
    } catch (caught) {
      joinError = caught;
    } finally {
      joining = false;
    }
  }

  async function enroll(courseId: string) {
    const { error: err } = await api.POST('/courses/{course_id}/enroll', {
      params: { path: { course_id: courseId } }
    });
    if (err) throw err;
    await load();
  }
</script>

<h1 class="mb-6 text-2xl font-bold text-slate-900">Discover</h1>

{#if error}
  <ErrorBanner {error} />
{:else if loading}
  <p class="text-sm text-slate-500">Loading…</p>
{:else}
  <div class="flex flex-col gap-6">
    <Card title="Join with a code">
      <form onsubmit={joinByCode} class="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div class="flex-1">
          <TextInput
            label="Join code"
            bind:value={joinCode}
            oninput={() => (joinCode = groupCode(joinCode))}
            placeholder="XXXX-XXXX-XXXX-XXXX"
            required
          />
        </div>
        <Button type="submit" loading={joining}>Join</Button>
      </form>
      {#if joinError}<div class="mt-3"><ErrorBanner error={joinError} /></div>{/if}
    </Card>

    <section>
      <div class="mb-3 flex items-center justify-between">
        <h2 class="text-base font-semibold text-slate-900">Public courses</h2>
        <input
          bind:value={search}
          placeholder="Filter by name…"
          class="rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      </div>
      {#if publicCourses.length === 0}
        <EmptyState message="No public courses yet." />
      {:else if visibleCourses.length === 0}
        <EmptyState message={`No courses match "${search.trim()}".`} />
      {:else}
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {#each visibleCourses as course (course.course_id)}
            <Card>
              <p class="font-medium text-slate-900">{course.name}</p>
              <p class="mt-1 text-sm text-slate-500">
                {course.source_count} source{course.source_count === 1 ? '' : 's'}
              </p>
              <div class="mt-3">
                {#if enrolledIds.has(course.course_id)}
                  <a href={`/courses/${course.course_id}`} class="text-sm text-indigo-600 hover:underline">
                    Open course
                  </a>
                {:else}
                  <Button
                    variant="secondary"
                    onclick={() => enroll(course.course_id).catch((err) => (joinError = err))}
                  >
                    Enroll
                  </Button>
                {/if}
              </div>
            </Card>
          {/each}
        </div>
      {/if}
    </section>
  </div>
{/if}
