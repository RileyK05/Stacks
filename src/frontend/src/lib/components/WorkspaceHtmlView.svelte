<script lang="ts">
  import type { WorkspaceHtml } from '$lib/stores/workspace.svelte';
  import { sanitizeHtml } from '$lib/utils/render';
  import SourceChips, { type SourceRef } from './SourceChips.svelte';

  interface Props {
    item: WorkspaceHtml;
    sources: SourceRef[];
  }

  let { item, sources }: Props = $props();

  const html = $derived(sanitizeHtml(item.html));
</script>

<div class="flex flex-col gap-3">
  <div
    class="overflow-x-auto rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-950/40"
  >
    {@html html}
  </div>
  <SourceChips cited={item.sources} {sources} />
</div>
