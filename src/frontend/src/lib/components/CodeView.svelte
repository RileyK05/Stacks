<script lang="ts">
  import hljs from 'highlight.js/lib/common';
  import 'highlight.js/styles/github-dark.css';
  import { sanitizeHtml } from '$lib/utils/render';
  import type { WorkspaceCode } from '$lib/stores/workspace.svelte';
  import SourceChips, { type SourceRef } from './SourceChips.svelte';

  interface Props {
    item: WorkspaceCode;
    sources: SourceRef[];
  }

  let { item, sources }: Props = $props();

  let copied = $state(false);

  const highlighted = $derived.by(() => {
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
    await navigator.clipboard.writeText(item.code);
    copied = true;
    setTimeout(() => (copied = false), 1500);
  }
</script>

<div class="flex flex-col gap-3">
  <div class="overflow-hidden rounded-lg ring-1 ring-slate-700">
    <div class="flex items-center justify-between bg-slate-800 px-3 py-1.5">
      <span class="font-mono text-xs text-slate-400">{item.language ?? 'code'}</span>
      <button
        type="button"
        onclick={copy}
        class="text-xs text-slate-300 transition-colors hover:text-white"
      >
        {copied ? 'Copied!' : 'Copy'}
      </button>
    </div>
    {#if fallback}
      <pre class="overflow-x-auto bg-slate-950 p-4 text-sm text-slate-200"><code>{item.code}</code
        ></pre>
    {:else}
      <pre class="overflow-x-auto bg-slate-950 p-4 text-sm text-slate-200"><code>{@html sanitizeHtml(highlighted)}</code
        ></pre>
    {/if}
  </div>
  <SourceChips cited={item.sources} {sources} />
</div>
