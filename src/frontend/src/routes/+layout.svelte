<script lang="ts">
  import '@fontsource-variable/inter';
  import '@fontsource-variable/fraunces/opsz.css';
  import '@fontsource-variable/fraunces/opsz-italic.css';
  import '@fontsource-variable/jetbrains-mono';
  import { isTauri } from '@tauri-apps/api/core';
  import { openUrl } from '@tauri-apps/plugin-opener';
  import { onMount } from 'svelte';
  import { restartBackend } from '$lib/api/backend';
  import Button from '$lib/components/Button.svelte';
  import ConfirmHost from '$lib/components/ConfirmHost.svelte';
  import DebugHost from '$lib/components/DebugHost.svelte';
  import Toaster from '$lib/components/Toaster.svelte';
  import { cleanOrphanedRecovery } from '$lib/stores/recoveryCleanup';
  import '$lib/stores/theme.svelte';
  import '../app.css';

  let { data, children } = $props();
  let retrying = $state(false);
  let retryError = $state('');

  async function retryBackend() {
    if (retrying) return;
    retrying = true;
    retryError = '';
    try {
      if (isTauri()) await restartBackend();
      location.reload();
    } catch (error) {
      retryError = error instanceof Error ? error.message : String(error);
      retrying = false;
    }
  }

  onMount(() => {
    document.getElementById('boot-splash')?.remove();
    if (!data.backendError) void cleanOrphanedRecovery().catch(() => {});
  });

  // The app window only ever shows the app. A link out of it (a URL in an
  // answer, a provider's docs) opens in the user's browser instead of
  // replacing the app.
  function openExternally(event: MouseEvent): void {
    if (!isTauri() || event.defaultPrevented || event.button !== 0) return;
    const anchor = (event.target as Element | null)?.closest?.('a[href]');
    if (!(anchor instanceof HTMLAnchorElement)) return;
    const url = new URL(anchor.href, location.href);
    if (url.origin === location.origin || !/^https?:$/.test(url.protocol)) return;
    event.preventDefault();
    void openUrl(url.href);
  }
</script>

<svelte:document onclick={openExternally} />

{#if data.backendError}
  <main class="flex min-h-screen items-center justify-center bg-bg px-6">
    <div class="max-w-md text-center">
      <h1 class="font-display text-2xl font-semibold text-fg">Stacks couldn't start</h1>
      <p class="mt-3 text-sm text-muted">{data.backendError}</p>
      <p class="mt-3 text-sm text-muted">
        Try starting the backend again. If this keeps happening, the log file says why.
      </p>
      <div class="mt-6 flex justify-center">
        <Button disabled={retrying} onclick={retryBackend}>{retrying ? 'Starting…' : 'Try again'}</Button>
      </div>
      {#if retryError}<p class="mt-3 text-sm text-danger-text">{retryError}</p>{/if}
    </div>
  </main>
{:else}
  {@render children()}
{/if}
<Toaster />
<ConfirmHost />
<DebugHost />
