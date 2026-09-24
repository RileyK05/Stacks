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
  <div class="overflow-x-auto rounded-xl border border-line bg-bg/40 p-4 text-sm text-fg-soft">
    {@html html}
  </div>
  <SourceChips cited={item.sources} {sources} />
</div>
