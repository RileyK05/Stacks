<script lang="ts">
  import { page } from '$app/state';
  import Button from '$lib/components/Button.svelte';
</script>

<main class="flex min-h-screen items-center justify-center bg-bg px-6">
  <div class="max-w-md text-center">
    <h1 class="font-display text-2xl font-semibold text-fg">
      {page.status === 404 ? 'Page not found' : 'Something went wrong'}
    </h1>
    <p class="mt-3 text-sm text-muted">{page.error?.message}</p>
    <div class="mt-6 flex justify-center">
      <Button onclick={() => (location.href = '/')}>My courses</Button>
    </div>
  </div>
</main>
