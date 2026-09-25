<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import type { SheetContent } from '$lib/stores/artifact.svelte';

  interface Props {
    sheet: SheetContent;
    editable?: boolean;
    onchange: () => void;
  }

  let { sheet, editable = true, onchange }: Props = $props();

  let sortedBy = $state<{ column: number; ascending: boolean } | null>(null);

  function addRow() {
    sheet.rows.push(sheet.columns.map(() => ''));
    onchange();
  }

  function addColumn() {
    sheet.columns.push(columnName(sheet.columns.length));
    for (const row of sheet.rows) row.push('');
    onchange();
  }

  function removeRow(index: number) {
    sheet.rows.splice(index, 1);
    onchange();
  }

  function removeColumn(index: number) {
    if (sheet.columns.length === 1) return;
    sheet.columns.splice(index, 1);
    for (const row of sheet.rows) row.splice(index, 1);
    onchange();
  }

  function columnName(index: number): string {
    let name = '';
    let n = index;
    do {
      name = String.fromCharCode(65 + (n % 26)) + name;
      n = Math.floor(n / 26) - 1;
    } while (n >= 0);
    return name;
  }

  function sort(column: number) {
    const ascending = sortedBy?.column === column ? !sortedBy.ascending : true;
    const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
    sheet.rows.sort((a, b) => (ascending ? 1 : -1) * collator.compare(a[column] ?? '', b[column] ?? ''));
    sortedBy = { column, ascending };
    onchange();
  }

  function onKey(event: KeyboardEvent, row: number, column: number) {
    const target = event.currentTarget as HTMLInputElement;
    const grid = target.closest('table');
    const move = (r: number, c: number) => {
      const next = grid?.querySelector<HTMLInputElement>(`[data-cell="${r}:${c}"]`);
      if (next) {
        event.preventDefault();
        next.focus();
        next.select();
      }
    };
    if (event.key === 'Enter' && !event.shiftKey) {
      if (row === sheet.rows.length - 1 && editable) addRow();
      requestAnimationFrame(() => move(row + 1, column));
    } else if (event.key === 'ArrowDown') move(row + 1, column);
    else if (event.key === 'ArrowUp') move(row - 1, column);
  }
</script>

<div class="overflow-x-auto rounded-xl border border-line bg-surface shadow-card">
  <table class="w-full border-collapse text-[13px]">
    <thead>
      <tr class="bg-surface-2">
        <th class="w-10 border-b border-r border-line"></th>
        {#each sheet.columns as _, column (column)}
          <th class="group min-w-36 border-b border-r border-line p-0 text-left font-semibold">
            <div class="flex items-center">
              <input
                bind:value={sheet.columns[column]}
                oninput={onchange}
                readonly={!editable}
                aria-label={`Column ${column + 1} name`}
                class="h-9 min-w-0 flex-1 bg-transparent px-2.5 font-semibold text-fg focus:bg-surface focus:outline-none focus:ring-2 focus:ring-inset focus:ring-accent/40"
              />
              <button
                type="button"
                onclick={() => sort(column)}
                title="Sort by this column"
                class="mr-0.5 rounded p-1 text-subtle opacity-0 transition-opacity hover:bg-surface-3 hover:text-fg group-hover:opacity-100"
              >
                <Icon name="chevron-down" class={`h-3.5 w-3.5 ${sortedBy?.column === column && !sortedBy.ascending ? 'rotate-180' : ''}`} />
              </button>
              {#if editable && sheet.columns.length > 1}
                <button
                  type="button"
                  onclick={() => removeColumn(column)}
                  title="Delete column"
                  class="mr-1 rounded p-1 text-subtle opacity-0 transition-opacity hover:bg-danger-soft hover:text-danger-text group-hover:opacity-100"
                >
                  <Icon name="x" class="h-3.5 w-3.5" />
                </button>
              {/if}
            </div>
          </th>
        {/each}
        {#if editable}
          <th class="w-10 border-b border-line p-0">
            <button type="button" onclick={addColumn} title="Add column" class="flex h-9 w-full items-center justify-center text-subtle hover:bg-surface-3 hover:text-fg">
              <Icon name="plus" class="h-4 w-4" />
            </button>
          </th>
        {/if}
      </tr>
    </thead>
    <tbody>
      {#each sheet.rows as cells, row (row)}
        <tr class="group">
          <td class="border-b border-r border-line text-center text-[11px] text-subtle">
            <span class="group-hover:hidden">{row + 1}</span>
            {#if editable}
              <button type="button" onclick={() => removeRow(row)} title="Delete row" class="hidden w-full py-1 text-subtle hover:text-danger-text group-hover:block">
                <Icon name="x" class="mx-auto h-3.5 w-3.5" />
              </button>
            {/if}
          </td>
          {#each cells as _, column (column)}
            <td class="border-b border-r border-line p-0">
              <input
                bind:value={sheet.rows[row][column]}
                oninput={onchange}
                onkeydown={(event) => onKey(event, row, column)}
                readonly={!editable}
                data-cell={`${row}:${column}`}
                aria-label={`Row ${row + 1}, ${sheet.columns[column]}`}
                class="h-9 w-full bg-transparent px-2.5 text-fg-soft focus:bg-accent-soft/40 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-accent/40"
              />
            </td>
          {/each}
          {#if editable}<td class="border-b border-line"></td>{/if}
        </tr>
      {/each}
    </tbody>
  </table>
  {#if editable}
    <button type="button" onclick={addRow} class="flex w-full items-center gap-2 px-3 py-2 text-[13px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg">
      <Icon name="plus" class="h-3.5 w-3.5" /> Add row
    </button>
  {/if}
</div>
