<script lang="ts">
  import { isTauri } from '@tauri-apps/api/core';
  import { requestWorkspaceExport, deliverExport, type ExportOrigin } from '$lib/api/export';
  import type { DocumentSession } from '$lib/stores/workspace.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import Button from './Button.svelte';
  import Icon from './Icon.svelte';
  import RichText from './RichText.svelte';
  import SourceChips, { type SourceRef } from './SourceChips.svelte';

  interface Props {
    session: DocumentSession;
    sources: (SourceRef | null)[];
    exportContext: ExportOrigin | null;
  }

  let { session, sources, exportContext }: Props = $props();

  let mode = $state<'edit' | 'preview'>('preview');
  let exporting = $state(false);

  const tabs: [typeof mode, string][] = [
    ['preview', 'Preview'],
    ['edit', 'Edit']
  ];

  async function download() {
    if (!exportContext) {
      toast('This material no longer has its original message. Reopen it before exporting.', 'error');
      return;
    }
    exporting = true;
    try {
      const file = await requestWorkspaceExport(exportContext, 'md', session.draft);
      const saved = await deliverExport(file);
      if (saved) toast(isTauri() ? `Saved to ${saved.path}` : `Saved ${saved.filename}`);
    } catch (caught) {
      toast(caught instanceof Error ? caught.message : 'Could not export this document.', 'error');
    } finally {
      exporting = false;
    }
  }
</script>

<div class="flex flex-col gap-4">
  <div class="flex flex-wrap items-center gap-2">
    <div class="inline-flex rounded-lg bg-surface-2 p-0.5 ring-1 ring-line">
      {#each tabs as [value, label] (value)}
        <button
          type="button"
          onclick={() => (mode = value)}
          class={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
            mode === value ? 'bg-surface text-fg shadow-card' : 'text-muted hover:text-fg'
          }`}
        >
          {label}
        </button>
      {/each}
    </div>
    {#if session.edited}
      <span class="text-xs text-subtle">Edited</span>
    {/if}
    <div class="ml-auto flex items-center gap-1">
      {#if session.edited}
        <Button variant="ghost" size="sm" onclick={() => session.revert()}>
          <Icon name="rotate-ccw" class="h-3.5 w-3.5" /> Revert
        </Button>
      {/if}
      <Button variant="secondary" size="sm" onclick={download} disabled={exporting}>
        <Icon name="download" class="h-3.5 w-3.5" /> .md
      </Button>
    </div>
  </div>

  {#if mode === 'edit'}
    <textarea
      bind:value={session.draft}
      rows={16}
      spellcheck={false}
      class="w-full resize-y rounded-xl border border-line-strong bg-surface p-4 font-mono text-[13px] leading-relaxed text-fg transition-[border-color,box-shadow] focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent/15"
    ></textarea>
    <p class="text-xs text-subtle">
      Unfinished edits recover on this computer. Save to artifacts to keep editing a versioned material.
    </p>
  {:else}
    <div class="rounded-xl border border-line bg-bg/40 px-5 py-4">
      <RichText text={session.draft} class="[&>*:first-child]:mt-0" />
    </div>
  {/if}

  <SourceChips cited={session.document.sources} {sources} />
</div>
