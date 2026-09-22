<script lang="ts">
  let { children } = $props();
</script>

<div class="flex min-h-screen items-center justify-center p-4">
  <div class="w-full max-w-sm">
    <h1 class="mb-6 text-center text-2xl font-bold text-slate-900">
      Course Assistant
    </h1>
    {@render children()}
  </div>
</div>
