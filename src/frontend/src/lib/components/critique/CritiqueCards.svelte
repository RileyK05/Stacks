<script lang="ts">
  import {
    citationChips,
    coverageLine,
    dimensionLabel,
    fallacyLabel,
    passageEdited,
    stillOpen,
    type CitationChip,
    type CritiqueView,
    type PriorFindingView
  } from '$lib/utils/critique';

  let {
    critique,
    citations = []
  }: {
    critique: CritiqueView;
    citations?: CitationChip[];
  } = $props();

  const open = $derived(stillOpen(critique.prior ?? []));
  const edited = $derived(passageEdited(critique.prior ?? []));
  const findings = $derived(critique.findings ?? []);
  const grouped = $derived(open.length > 0 || edited.length > 0);
</script>

{#snippet priorCard(item: PriorFindingView, editedPassage: boolean)}
  <article class="rounded-xl border border-line bg-surface-2 p-3">
    <blockquote class="border-l-2 border-line pl-3 text-sm text-fg">{item.original}</blockquote>
    <p class="mt-2 text-sm text-muted">{item.feedback}</p>
    {#if editedPassage}
      <p class="mt-2 text-[11px] text-subtle">The quoted passage is no longer in the draft. That does not mean the problem is solved.</p>
    {/if}
  </article>
{/snippet}

<div class="space-y-3">
  <p class="text-[11px] text-muted">
    {critique.genre} · critic score {critique.critic_score} · {coverageLine(critique.coverage)}
  </p>
  {#if !critique.syllabus_in_context}
    <p class="text-[11px] text-muted">No syllabus passage was supplied for this pass, so no assignment rule was assumed.</p>
  {/if}
  {#if critique.note}
    <p class="text-sm text-fg">{critique.note}</p>
  {/if}

  {#if open.length > 0}
    <div class="space-y-2">
      <h3 class="text-xs font-semibold uppercase tracking-wide text-subtle">Still open</h3>
      {#each open as item, index (`open-${index}`)}
        {@render priorCard(item, false)}
      {/each}
    </div>
  {/if}

  {#if edited.length > 0}
    <div class="space-y-2">
      <h3 class="text-xs font-semibold uppercase tracking-wide text-subtle">Passage edited</h3>
      {#each edited as item, index (`edited-${index}`)}
        {@render priorCard(item, true)}
      {/each}
    </div>
  {/if}

  {#if findings.length > 0}
    <div class="space-y-2">
      {#if grouped}
        <h3 class="text-xs font-semibold uppercase tracking-wide text-subtle">New</h3>
      {/if}
      {#each findings as finding, index (`finding-${index}`)}
        {@const chips = citationChips(finding.feedback, citations)}
        <article class="rounded-xl border border-line bg-surface p-3">
          <div class="flex flex-wrap gap-1.5 text-[11px] font-medium">
            <span class="rounded-full bg-surface-3 px-2 py-0.5 text-muted">{dimensionLabel(finding.dimension)}</span>
            {#if fallacyLabel(finding.fallacy)}
              <span class="rounded-full bg-surface-3 px-2 py-0.5 text-fg">{fallacyLabel(finding.fallacy)}</span>
            {/if}
            <span class="rounded-full px-2 py-0.5 text-subtle">{finding.grounding === 'course' ? 'Course' : 'Draft'}</span>
          </div>
          <blockquote class="mt-2 border-l-2 border-line pl-3 text-sm text-fg">{finding.original}</blockquote>
          <p class="mt-2 text-sm text-fg">{finding.feedback}</p>
          {#if chips.length > 0}
            <div class="mt-2 flex flex-col gap-1">
              {#each chips as chip (chip.number)}
                <p class="text-xs text-accent-text">[{chip.number}] {chip.filename}{chip.label ? ` · ${chip.label}` : ''}</p>
              {/each}
            </div>
          {/if}
        </article>
      {/each}
    </div>
  {/if}
</div>
