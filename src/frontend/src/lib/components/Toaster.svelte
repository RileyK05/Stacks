<script lang="ts">
  import { currentToasts, dismiss } from '$lib/stores/toast.svelte';

  let toasts = $derived(currentToasts());
</script>

<div class="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
  {#each toasts as t (t.id)}
    <div
      class={`pointer-events-auto rounded-lg p-3 text-sm shadow-lg ring-1 transition-all ${
        t.tone === 'success'
          ? 'bg-white text-slate-800 ring-slate-200'
          : 'bg-red-50 text-red-800 ring-red-200'
      }`}
      role="status"
    >
      <div class="flex items-start justify-between gap-3">
        <p>{t.message}</p>
        <button
          onclick={() => dismiss(t.id)}
          class="text-slate-400 hover:text-slate-600"
          aria-label="Dismiss"
        >
          ✕
        </button>
      </div>
    </div>
  {/each}
</div>
