<script lang="ts">
  import { isTauri } from '@tauri-apps/api/core';
  import { deliverExport, requestWorkspaceExport, type ExportOrigin } from '$lib/api/export';
  import type { SheetSession } from '$lib/stores/workspace.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { autoGrowTextarea } from '$lib/actions/autoGrowTextarea';
  import Button from './Button.svelte';
  import Icon from './Icon.svelte';
  import SourceChips, { type SourceRef } from './SourceChips.svelte';

  interface Props {
    session: SheetSession;
    sources: (SourceRef | null)[];
    exportContext: ExportOrigin | null;
  }

  let { session, sources, exportContext }: Props = $props();

  let exporting = $state(false);

  async function download() {
    if (!exportContext) {
      toast('This material no longer has its original message. Reopen it before exporting.', 'error');
      return;
    }
    exporting = true;
    try {
      const file = await requestWorkspaceExport(exportContext, 'csv', session.draft.map((row) => [...row]));
      const saved = await deliverExport(file);
      if (saved) toast(isTauri() ? `Saved to ${saved.path}` : `Saved ${saved.filename}`);
    } catch (caught) {
      toast(caught instanceof Error ? caught.message : 'Could not export this sheet.', 'error');
    } finally {
      exporting = false;
    }
  }
</script>

<div class="flex flex-col gap-4">
  <div class="overflow-x-auto rounded-xl border border-line">
    <table class="w-full table-fixed border-collapse text-sm">
      <thead>
        <tr>
          {#each session.item.columns as column, columnIndex (columnIndex)}
            <th
              class="border-b border-line bg-surface-2 px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted"
            >
              {column}
            </th>
          {/each}
          <th class="w-8 border-b border-line bg-surface-2"></th>
        </tr>
      </thead>
      <tbody>
        {#each session.draft as row, rowIndex (rowIndex)}
          <tr class="group">
            {#each row as cell, columnIndex (columnIndex)}
              <td class="border-b border-r border-line p-0 last:border-r-0 group-last:border-b-0">
                <textarea
                  bind:value={session.draft[rowIndex][columnIndex]}
                  use:autoGrowTextarea={session.draft[rowIndex][columnIndex]}
                  rows="1"
                  aria-label="{session.item.columns[columnIndex]}, row {rowIndex + 1}"
                  class="block h-auto w-full min-w-0 resize-none overflow-hidden bg-transparent px-3 py-2 text-fg [overflow-wrap:anywhere] transition-colors focus:bg-accent-soft focus:outline-none"
                ></textarea>
              </td>
            {/each}
            <td class="border-b border-line text-center group-last:border-b-0">
              <button
                type="button"
                aria-label="Remove row {rowIndex + 1}"
                onclick={() => session.removeRow(rowIndex)}
                class="rounded p-1 text-subtle opacity-0 transition-all hover:text-danger-text focus:opacity-100 group-hover:opacity-100"
              >
                <Icon name="x" class="h-3.5 w-3.5" />
              </button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  <div class="flex flex-wrap items-center gap-1">
    <Button variant="secondary" size="sm" onclick={() => session.addRow()}>
      <Icon name="plus" class="h-3.5 w-3.5" /> Add row
    </Button>
    {#if session.edited}
      <Button variant="ghost" size="sm" onclick={() => session.revert()}>
        <Icon name="rotate-ccw" class="h-3.5 w-3.5" /> Revert
      </Button>
    {/if}
    <Button variant="secondary" size="sm" onclick={download} class="ml-auto" disabled={exporting}>
      <Icon name="download" class="h-3.5 w-3.5" /> .csv
    </Button>
  </div>
  <p class="text-xs text-subtle">Edits stay in this browser session until you choose Save to artifacts.</p>
  <SourceChips cited={session.item.sources} {sources} />
</div>
