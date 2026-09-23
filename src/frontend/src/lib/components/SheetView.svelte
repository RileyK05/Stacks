<script lang="ts">
  import type { SheetSession } from '$lib/stores/workspace.svelte';
  import Button from './Button.svelte';
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

<div class="flex flex-col gap-3">
  <div class="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
    <table class="w-full border-collapse text-sm">
      <thead>
        <tr>
          {#each session.item.columns as column, columnIndex (columnIndex)}
            <th
              class="border-b border-slate-200 bg-slate-50 px-3 py-2 text-left font-medium text-slate-700 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-200"
            >
              {column}
            </th>
          {/each}
          <th class="w-8 border-b border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/60"></th>
        </tr>
      </thead>
      <tbody>
        {#each session.draft as row, rowIndex (rowIndex)}
          <tr>
            {#each row as cell, columnIndex (columnIndex)}
              <td class="border-b border-slate-100 p-0 last:border-b dark:border-slate-800">
                <input
                  bind:value={session.draft[rowIndex][columnIndex]}
                  aria-label="{session.item.columns[columnIndex]}, row {rowIndex + 1}"
                  class="w-full min-w-24 bg-transparent px-3 py-2 text-slate-800 focus:bg-indigo-50 focus:outline-none dark:text-slate-200 dark:focus:bg-indigo-950/40"
                />
              </td>
            {/each}
            <td class="border-b border-slate-100 text-center dark:border-slate-800">
              <button
                type="button"
                aria-label="Remove row {rowIndex + 1}"
                onclick={() => session.removeRow(rowIndex)}
                class="px-2 text-slate-300 transition-colors hover:text-red-500 dark:text-slate-600 dark:hover:text-red-400"
              >
                ✕
              </button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  <div class="flex items-center justify-between">
    <div class="flex gap-2">
      <Button variant="secondary" onclick={() => session.addRow()}>Add row</Button>
      {#if session.edited}
        <Button variant="secondary" onclick={() => session.revert()}>Revert</Button>
      {/if}
    </div>
    <button
      type="button"
      onclick={download}
      class="text-xs text-indigo-600 transition-colors hover:text-indigo-500 dark:text-indigo-300 dark:hover:text-indigo-200"
    >
      Download .csv
    </button>
  </div>
  <p class="text-xs text-slate-400">Edits stay in this browser session — nothing is saved to your course.</p>
  <SourceChips cited={session.item.sources} {sources} />
</div>
