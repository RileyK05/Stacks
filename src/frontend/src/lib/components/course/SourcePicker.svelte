<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import Popover from '$lib/components/Popover.svelte';

  interface SourceItem {
    source_id: string;
    filename: string;
    status: string;
  }

  interface Props {
    sources: SourceItem[];
    /** The chat's chosen sources; null means all of them. */
    selected: string[] | null;
    disabled?: boolean;
    onchange: (selected: string[] | null) => void;
  }

  let { sources, selected, disabled = false, onchange }: Props = $props();

  let open = $state(false);
  const usable = $derived(sources.filter((s) => s.status === 'indexed'));
  const chosen = $derived(new Set(selected ?? usable.map((s) => s.source_id)));
  const count = $derived(usable.filter((s) => chosen.has(s.source_id)).length);
  const label = $derived(
    selected === null || count === usable.length
      ? 'All sources'
      : `${count} of ${usable.length} sources`
  );

  function toggle(id: string) {
    const next = new Set(chosen);
    if (next.has(id)) {
      if (next.size === 1) return; // a chat always reads from something
      next.delete(id);
    } else {
      next.add(id);
    }
    const ids = usable.map((s) => s.source_id).filter((sid) => next.has(sid));
    onchange(ids.length === usable.length ? null : ids);
  }
</script>

<Popover bind:open label="Choose sources" align="end" width="w-80">
  {#snippet trigger(props)}
    <button
      type="button"
      {...props}
      disabled={disabled || usable.length === 0}
      title="Which of the course's sources this chat answers from"
      class={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-[13px] shadow-card transition-colors hover:border-line-strong disabled:opacity-60 ${
        selected === null ? 'border-line bg-surface text-fg' : 'border-accent-line bg-accent-soft text-accent-text'
      }`}
    >
      <Icon name="library" class="h-3.5 w-3.5 shrink-0" />
      <span class="font-medium">{label}</span>
      <Icon name="chevron-down" class="h-3.5 w-3.5 shrink-0 opacity-70" />
    </button>
  {/snippet}
  {#snippet children()}
    <div class="border-b border-line px-3 py-2.5">
      <p class="text-[13px] font-medium text-fg">Answer from</p>
      <p class="text-[12px] text-subtle">Only the checked sources are searched in this chat.</p>
    </div>
    <ul class="max-h-72 overflow-y-auto py-1">
      {#each usable as source (source.source_id)}
        {@const on = chosen.has(source.source_id)}
        <li>
          <label class="flex cursor-pointer items-center gap-2.5 px-3 py-2 hover:bg-surface-2">
            <input
              type="checkbox"
              checked={on}
              disabled={on && count === 1}
              onchange={() => toggle(source.source_id)}
              class="h-4 w-4 rounded border-line-strong accent-[var(--accent)]"
            />
            <Icon name="file-text" class="h-4 w-4 shrink-0 text-subtle" />
            <span class="min-w-0 flex-1 truncate text-[13px] text-fg-soft">{source.filename}</span>
          </label>
        </li>
      {/each}
    </ul>
    {#if selected !== null}
      <button
        type="button"
        onclick={() => onchange(null)}
        class="w-full border-t border-line px-3 py-2.5 text-left text-[13px] font-medium text-accent-text hover:bg-surface-2"
      >
        Use all sources
      </button>
    {/if}
  {/snippet}
</Popover>
