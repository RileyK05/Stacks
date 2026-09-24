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
  let enrollingId = $state<string | null>(null);

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
    enrollingId = courseId;
    try {
      const { error: err } = await api.POST('/courses/{course_id}/enroll', {
        params: { path: { course_id: courseId } }
      });
      if (err) throw err;
      await load();
    } finally {
      enrollingId = null;
    }
  }
</script>

<PageHeader title="Discover" description="Find public courses, or join a private one with a code from its owner." />

{#if error}
  <ErrorBanner {error} />
{:else if loading}
  <div class="flex flex-col gap-6">
    <Skeleton class="h-36 rounded-2xl" />
    <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {#each [0, 1, 2] as i (i)}<Skeleton class="h-40 rounded-2xl" />{/each}
    </div>
  </div>
{:else}
  <div class="flex flex-col gap-10">
    <section
      class="relative overflow-hidden rounded-2xl border border-line bg-surface p-5 shadow-card sm:p-6"
    >
      <div class="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
        <div class="flex items-start gap-4">
          <span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent-text">
            <Icon name="key" class="h-5 w-5" />
          </span>
          <div>
            <h2 class="text-[15px] font-semibold text-fg">Have a join code?</h2>
            <p class="mt-1 text-sm text-muted">Enter the code a course owner shared with you.</p>
          </div>
        </div>
        <form onsubmit={joinByCode} class="flex w-full gap-2 md:w-auto">
          <label for="join-code" class="sr-only">Join code</label>
          <input
            id="join-code"
            bind:value={joinCode}
            oninput={() => (joinCode = groupCode(joinCode))}
            placeholder="XXXX-XXXX-XXXX-XXXX"
            required
            autocomplete="off"
            spellcheck={false}
            class="h-10 min-w-0 flex-1 rounded-lg border border-line-strong bg-surface px-3 font-mono text-sm uppercase tracking-[0.08em] text-fg shadow-card transition-[border-color,box-shadow] placeholder:tracking-[0.08em] placeholder:text-subtle focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent/15 md:w-64"
          />
          <Button type="submit" loading={joining} class="h-10">Join</Button>
        </form>
      </div>
      {#if joinError}<div class="mt-4"><ErrorBanner error={joinError} /></div>{/if}
    </section>

    <section>
      <div class="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div class="flex items-baseline gap-2">
          <h2 class="text-[15px] font-semibold text-fg">Public courses</h2>
          <span class="text-sm text-subtle">{publicCourses.length}</span>
        </div>
        <div class="relative sm:w-64">
          <Icon name="search" class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle" />
          <input
            bind:value={search}
            placeholder="Filter by name…"
            aria-label="Filter courses by name"
            class="h-9 w-full rounded-lg border border-line-strong bg-surface pl-9 pr-3 text-sm text-fg shadow-card transition-[border-color,box-shadow] placeholder:text-subtle focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent/15"
          />
        </div>
      </div>
      {#if publicCourses.length === 0}
        <EmptyState icon="globe" title="No public courses yet" message="When owners make a course public, it shows up here." />
      {:else if visibleCourses.length === 0}
        <EmptyState icon="search" message={`No courses match "${search.trim()}".`} />
      {:else}
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {#each visibleCourses as course (course.course_id)}
            {@const enrolled = enrolledIds.has(course.course_id)}
            <div class="flex flex-col rounded-2xl border border-line bg-surface p-5 shadow-card">
              <div class="flex items-start justify-between gap-3">
                <Monogram name={course.name} />
                {#if enrolled}<Badge tone="success" icon="check">Enrolled</Badge>{/if}
              </div>
              <p class="mt-4 line-clamp-2 font-medium leading-snug text-fg">{course.name}</p>
              <p class="mt-1 inline-flex items-center gap-1 text-xs text-muted">
                <Icon name="file-text" class="h-3.5 w-3.5 text-subtle" />
                {plural(course.source_count, 'source')}
              </p>
              <div class="mt-auto pt-4">
                {#if enrolled}
                  <a
                    href={`/courses/${course.course_id}`}
                    class="inline-flex h-8 items-center gap-1.5 text-[13px] font-medium text-accent-text hover:underline"
                  >
                    Open course <Icon name="arrow-right" class="h-3.5 w-3.5" />
                  </a>
                {:else}
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={enrollingId === course.course_id}
                    onclick={() => enroll(course.course_id).catch((err) => (joinError = err))}
                  >
                    <Icon name="plus" class="h-3.5 w-3.5" /> Enroll
                  </Button>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      {/if}
    </section>
  </div>
{/if}
