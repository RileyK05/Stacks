<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { apiBase, appToken } from '$lib/api/backend';
  import {
    clearDebugLog,
    debugEntries,
    debugEnabled,
    setDebugEnabled,
    toggleDebug
  } from '$lib/stores/debug.svelte';

  let enabled = $derived(debugEnabled());
  let entries = $derived(debugEntries());
  let tab = $state<'requests' | 'state'>('requests');
  let expandedId = $state<number | null>(null);

  onMount(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === '.') {
        e.preventDefault();
        toggleDebug();
      } else if (e.key === 'Escape' && debugEnabled()) {
        setDebugEnabled(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  function methodClass(method: string): string {
    switch (method.toUpperCase()) {
      case 'GET':
        return 'text-sky-400';
      case 'POST':
        return 'text-emerald-400';
      case 'DELETE':
        return 'text-red-400';
      default:
        return 'text-amber-400';
    }
  }

  function statusClass(status: number): string {
    if (status === 0) return 'text-amber-400';
    return status < 400 ? 'text-emerald-400' : 'text-red-400';
  }

</script>

{#if enabled}
  <section
    class="fixed inset-x-0 bottom-0 z-50 flex h-72 flex-col bg-slate-900 font-mono text-xs text-slate-200 shadow-2xl"
    aria-label="Debug panel"
  >
    <header class="flex items-center gap-3 border-b border-slate-700 px-3 py-1.5">
      <span class="font-semibold text-slate-400">debug</span>
      <nav class="flex gap-1">
        {#each ['requests', 'state'] as t (t)}
          <button
            onclick={() => (tab = t as 'requests' | 'state')}
            class={`rounded px-2 py-0.5 capitalize ${tab === t ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'}`}
          >
            {t}
          </button>
        {/each}
      </nav>
      <span class="ml-auto text-slate-500">Ctrl+Shift+. toggles · Esc closes</span>
      {#if tab === 'requests'}
        <button onclick={clearDebugLog} class="text-slate-400 hover:text-slate-200">clear</button>
      {/if}
      <button
        onclick={() => setDebugEnabled(false)}
        class="text-slate-400 hover:text-slate-200"
        aria-label="Close debug panel"
      >
        ✕
      </button>
    </header>

    {#if tab === 'requests'}
      <div class="flex-1 overflow-y-auto">
        {#if entries.length === 0}
          <p class="p-3 text-slate-500">No requests logged yet.</p>
        {/if}
        {#each [...entries].reverse() as entry (entry.id)}
          <div class="border-b border-slate-800">
            <button
              class="flex w-full items-center gap-2 px-3 py-1 text-left hover:bg-slate-800"
              onclick={() => (expandedId = expandedId === entry.id ? null : entry.id)}
            >
              <span class={methodClass(entry.method)}>{entry.method}</span>
              <span class="min-w-0 flex-1 truncate">{entry.path}</span>
              <span class={statusClass(entry.status)}>
                {entry.status === 0 ? 'network' : entry.status}
              </span>
              <span class="text-slate-500">{entry.durationMs}ms</span>
              <span class="text-slate-600">
                {new Date(entry.at).toLocaleTimeString()}
              </span>
            </button>
            {#if expandedId === entry.id && (entry.errorKind || entry.errorMessage)}
              <div class="whitespace-pre-wrap break-words px-3 pb-2 pl-16 text-slate-400">
                {#if entry.errorKind}<p>kind: {entry.errorKind}</p>{/if}
                {#if entry.errorMessage}<p>{entry.errorMessage}</p>{/if}
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {:else}
      <dl class="grid flex-1 auto-rows-min grid-cols-[max-content_1fr] gap-x-4 gap-y-1 overflow-y-auto p-3">
        <dt class="text-slate-500">route</dt>
        <dd>{page.url.pathname + page.url.search}</dd>
        <dt class="text-slate-500">app token</dt>
        <dd>{appToken() ? 'present' : 'none (development)'}</dd>
        <dt class="text-slate-500">api base</dt>
        <dd>{apiBase()}</dd>
        <dt class="text-slate-500">logged requests</dt>
        <dd>{entries.length}</dd>
      </dl>
    {/if}
  </section>
{/if}
