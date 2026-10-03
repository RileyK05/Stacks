<script lang="ts">
  import hljs from 'highlight.js/lib/common';
  import { onDestroy } from 'svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import 'highlight.js/styles/github-dark.css';
  import { sanitizeHtml } from '$lib/utils/render';
  import type { WorkspaceCode } from '$lib/stores/workspace.svelte';
  import Icon from './Icon.svelte';
  import SourceChips, { type SourceRef } from './SourceChips.svelte';

  interface Props {
    item: WorkspaceCode;
    sources: SourceRef[];
  }

  let { item, sources }: Props = $props();

  let copied = $state(false);
  let copyTimer: ReturnType<typeof setTimeout> | null = null;
  onDestroy(() => { if (copyTimer) clearTimeout(copyTimer); });

  const highlighted = $derived.by(() => {
    if (item.code.length > 20_000) return '';
    try {
      if (item.language && hljs.getLanguage(item.language)) {
        return hljs.highlight(item.code, { language: item.language }).value;
      }
      return hljs.highlightAuto(item.code).value;
    } catch {
      return '';
    }
  });

  const fallback = $derived(highlighted === '');

  async function copy() {
    try {
      await navigator.clipboard.writeText(item.code);
      if (copyTimer) clearTimeout(copyTimer);
      copied = true;
      copyTimer = setTimeout(() => (copied = false), 1500);
    } catch {
      toast('Could not copy the code. Select it and copy manually.', 'error');
    }
  }
</script>

<div class="flex flex-col gap-3">
  <div class="overflow-hidden rounded-xl border border-white/10 bg-[#0d1117] shadow-lift">
    <div class="flex items-center gap-2 border-b border-white/10 px-3 py-2">
      <span class="flex gap-1.5" aria-hidden="true">
        <span class="h-2.5 w-2.5 rounded-full bg-white/15"></span>
        <span class="h-2.5 w-2.5 rounded-full bg-white/15"></span>
        <span class="h-2.5 w-2.5 rounded-full bg-white/15"></span>
      </span>
      <span class="ml-2 font-mono text-xs text-white/50">{item.language ?? 'code'}</span>
      <button
        type="button"
        onclick={copy}
        class="ml-auto inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-white/60 transition-colors hover:bg-white/10 hover:text-white"
      >
        <Icon name={copied ? 'check' : 'copy'} class="h-3.5 w-3.5" />
        {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
    {#if fallback}
      <pre class="overflow-x-auto p-4 font-mono text-[13px] leading-relaxed text-slate-200"><code>{item.code}</code
        ></pre>
    {:else}
      <pre class="overflow-x-auto p-4 font-mono text-[13px] leading-relaxed text-slate-200"><code>{@html sanitizeHtml(highlighted)}</code
        ></pre>
    {/if}
  </div>
  <SourceChips cited={item.sources} {sources} />
</div>
