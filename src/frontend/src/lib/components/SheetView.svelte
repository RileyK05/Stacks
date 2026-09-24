<script lang="ts">
  import type { SheetSession } from '$lib/stores/workspace.svelte';
  import Button from './Button.svelte';
  import Icon from './Icon.svelte';
  import SourceChips, { type SourceRef } from './SourceChips.svelte';

  interface Props {
    session: SheetSession;
    sources: SourceRef[];
  }

  let { session, sources }: Props = $props();

  function download() {
    const escape = (cell: string) => (/[",\n]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell);
    const csv = [session.item.columns, ...session.draft]
      .map((row) => row.map(escape).join(','))
      .join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${(session.item.title ?? 'sheet').replace(/[^\w-]+/g, '-')}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }
</script>

<div class="flex flex-col gap-4">
  <div class="overflow-x-auto rounded-xl border border-line">
    <table class="w-full border-collapse text-sm">
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
                <input
                  bind:value={session.draft[rowIndex][columnIndex]}
                  aria-label="{session.item.columns[columnIndex]}, row {rowIndex + 1}"
                  class="w-full min-w-24 bg-transparent px-3 py-2 text-fg transition-colors focus:bg-accent-soft focus:outline-none"
                />
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
    <Button variant="secondary" size="sm" onclick={download} class="ml-auto">
      <Icon name="download" class="h-3.5 w-3.5" /> .csv
    </Button>
  </div>
  <p class="text-xs text-subtle">Edits stay in this browser session — nothing is saved to your course.</p>
  <SourceChips cited={session.item.sources} {sources} />
</div>
