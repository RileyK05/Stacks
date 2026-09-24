<script lang="ts">
  import type { DocumentSession } from '$lib/stores/workspace.svelte';
  import Button from './Button.svelte';
  import Icon from './Icon.svelte';
  import RichText from './RichText.svelte';
  import SourceChips, { type SourceRef } from './SourceChips.svelte';

  interface Props {
    session: DocumentSession;
    sources: SourceRef[];
  }

  let { session, sources }: Props = $props();

  let mode = $state<'edit' | 'preview'>('preview');

  const tabs: [typeof mode, string][] = [
    ['preview', 'Preview'],
    ['edit', 'Edit']
  ];

  function download() {
    const blob = new Blob([session.draft], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${(session.document.title ?? 'study-notes').replace(/[^\w-]+/g, '-')}.md`;
    link.click();
    URL.revokeObjectURL(url);
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
      <Button variant="secondary" size="sm" onclick={download}>
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
      Edits stay in this browser session — nothing is saved to your course.
    </p>
  {:else}
    <div class="rounded-xl border border-line bg-bg/40 px-5 py-4">
      <RichText text={session.draft} class="[&>*:first-child]:mt-0" />
    </div>
  {/if}

  <SourceChips cited={session.document.sources} {sources} />
</div>
