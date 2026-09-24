<script lang="ts">
  import { fade, scale } from 'svelte/transition';
  import Button from '$lib/components/Button.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import { activePrompt, settle } from '$lib/stores/confirm.svelte';

  let prompt = $derived(activePrompt());
</script>

<svelte:window onkeydown={(e) => prompt && e.key === 'Escape' && settle(false)} />

{#if prompt}
  <div
    class="fixed inset-0 z-40 flex items-center justify-center bg-black/35 p-4 backdrop-blur-[2px]"
    role="presentation"
    transition:fade={{ duration: 150 }}
    onclick={(e) => e.target === e.currentTarget && settle(false)}
  >
    <div
      class="w-full max-w-md rounded-2xl border border-line bg-surface p-6 shadow-pop"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
      transition:scale={{ start: 0.96, duration: 160 }}
    >
      <div class="flex gap-4">
        <span
          class={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${
            prompt.danger ? 'bg-danger-soft text-danger-text' : 'bg-accent-soft text-accent-text'
          }`}
        >
          <Icon name={prompt.danger ? 'alert-triangle' : 'info'} class="h-5 w-5" />
        </span>
        <div>
          <h2 id="confirm-title" class="text-base font-semibold text-fg">{prompt.title}</h2>
          <p class="mt-1.5 text-sm leading-relaxed text-muted">{prompt.message}</p>
        </div>
      </div>
      <div class="mt-6 flex justify-end gap-2">
        <Button variant="secondary" onclick={() => settle(false)}>Cancel</Button>
        <Button variant={prompt.danger ? 'danger' : 'primary'} onclick={() => settle(true)}>
          {prompt.confirmLabel ?? 'Confirm'}
        </Button>
      </div>
    </div>
  </div>
{/if}
