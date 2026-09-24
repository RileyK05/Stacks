<script lang="ts">
  import { fly } from 'svelte/transition';
  import { flip } from 'svelte/animate';
  import { currentToasts, dismiss } from '$lib/stores/toast.svelte';
  import Icon from './Icon.svelte';

  let toasts = $derived(currentToasts());
</script>

<div
  class="pointer-events-none fixed inset-x-4 bottom-4 z-50 flex flex-col items-end gap-2 sm:left-auto sm:right-5 sm:w-96"
>
  {#each toasts as t (t.id)}
    <div
      animate:flip={{ duration: 200 }}
      in:fly={{ y: 12, duration: 220 }}
      out:fly={{ x: 24, duration: 180 }}
      class="pointer-events-auto flex w-full items-start gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-sm text-fg shadow-pop"
      role="status"
    >
      {#if t.tone === 'success'}
        <span class="mt-px flex h-5 w-5 items-center justify-center rounded-full bg-success-soft text-success-text">
          <Icon name="check" class="h-3.5 w-3.5" strokeWidth={2.5} />
        </span>
      {:else}
        <span class="mt-px flex h-5 w-5 items-center justify-center rounded-full bg-danger-soft text-danger-text">
          <Icon name="alert-circle" class="h-3.5 w-3.5" strokeWidth={2.5} />
        </span>
      {/if}
      <p class="min-w-0 flex-1 leading-5">{t.message}</p>
      <button
        type="button"
        onclick={() => dismiss(t.id)}
        class="-mr-1 rounded-md p-0.5 text-subtle transition-colors hover:bg-surface-2 hover:text-fg"
        aria-label="Dismiss"
      >
        <Icon name="x" class="h-4 w-4" />
      </button>
    </div>
  {/each}
</div>
