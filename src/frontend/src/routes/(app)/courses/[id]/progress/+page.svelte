<script lang="ts">
  import { page } from '$app/state';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import Icon from '$lib/components/Icon.svelte';
</script>

<a
  href={`/courses/${page.params.id}`}
  class="mb-6 inline-flex items-center gap-1 text-sm font-medium text-muted transition-colors hover:text-fg"
>
  <Icon name="chevron-left" class="h-4 w-4" /> Back to course
</a>

<EmptyState
  icon="trending-up"
  title="Progress"
  message="Coming with Milestone 4 — adaptive study recommendations are not built yet."
/>
