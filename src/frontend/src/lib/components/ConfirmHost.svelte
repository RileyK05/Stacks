<script lang="ts">
  import Button from '$lib/components/Button.svelte';
  import { activePrompt, settle } from '$lib/stores/confirm.svelte';

  let prompt = $derived(activePrompt());
</script>

{#if prompt}
  <div
    class="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4"
    role="presentation"
    onclick={(e) => e.target === e.currentTarget && settle(false)}
  >
    <div class="w-full max-w-sm rounded-xl bg-white p-5 shadow-xl dark:bg-slate-900" role="alertdialog" aria-modal="true">
      <h2 class="text-base font-semibold text-slate-900 dark:text-slate-100">{prompt.title}</h2>
      <p class="mt-2 text-sm text-slate-600 dark:text-slate-300">{prompt.message}</p>
      <div class="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onclick={() => settle(false)}>Cancel</Button>
        <Button variant={prompt.danger ? 'danger' : 'primary'} onclick={() => settle(true)}>
          {prompt.confirmLabel ?? 'Confirm'}
        </Button>
      </div>
    </div>
  </div>
{/if}
