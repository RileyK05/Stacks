<script lang="ts">
  import { ESSAY_GENRES, bandFor, type EssayGenre } from '$lib/utils/critique';

  interface Props {
    score: number;
    genre: EssayGenre;
    disabled?: boolean;
    unreadAvailable?: boolean;
    onscorestart?: () => void;
    onscore?: (score: number) => void;
    onscorecommit?: (score: number) => void;
    ongenre?: (genre: EssayGenre) => void;
    oncritique?: (focus: 'draft' | 'unread') => void;
  }

  let {
    score,
    genre,
    disabled = false,
    unreadAvailable = false,
    onscorestart,
    onscore,
    onscorecommit,
    ongenre,
    oncritique
  }: Props = $props();

  const baseId = $props.id();
  const scoreId = `${baseId}-score`;
  const genreId = `${baseId}-genre`;
  const band = $derived(bandFor(score));
</script>

<div class="space-y-2">
  <div class="flex flex-col gap-1.5">
    <label for={genreId} class="text-[13px] font-medium text-fg-soft">Essay kind</label>
    <select
      id={genreId}
      {disabled}
      value={genre}
      onchange={(event) => ongenre?.(event.currentTarget.value as EssayGenre)}
      class="h-10 w-full rounded-lg border border-line-strong bg-surface px-3 text-sm text-fg shadow-card focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent/15 disabled:opacity-60"
    >
      {#each ESSAY_GENRES as option (option.value)}
        <option value={option.value}>{option.label}</option>
      {/each}
    </select>
    <p class="text-[11px] text-subtle">Change this when the draft is something else.</p>
  </div>

  <div class="flex flex-col gap-1.5">
    <label for={scoreId} class="text-[13px] font-medium text-fg-soft">
      Critic score <span class="tabular-nums text-fg">{score}</span>
      <span class="font-normal text-subtle">· {band.label}</span>
    </label>
    <input
      id={scoreId}
      type="range"
      min="10"
      max="100"
      step="1"
      {disabled}
      value={score}
      aria-valuemin={10}
      aria-valuemax={100}
      aria-valuenow={score}
      aria-valuetext="{score}, {band.label}"
      onpointerdown={() => onscorestart?.()}
      oninput={(event) => onscore?.(Number(event.currentTarget.value))}
      onchange={(event) => onscorecommit?.(Number(event.currentTarget.value))}
      class="w-full accent-accent disabled:opacity-60"
    />
    <div class="flex justify-between text-[11px] text-subtle">
      <span>10 Rough draft</span>
      <span>50 Strong</span>
      <span>100 Severe</span>
    </div>
    <p class="text-[11px] text-muted">{band.detail}</p>
  </div>

  <p class="text-[11px] text-subtle">Stacks comments on the draft and leaves the writing to you.</p>
  <p class="text-[11px] text-subtle">This session does not update learning memory.</p>

  <div class="flex flex-wrap gap-1.5">
    <button
      type="button"
      {disabled}
      onclick={() => oncritique?.('draft')}
      class="rounded-lg bg-accent px-2.5 py-1.5 text-xs font-medium text-on-accent disabled:opacity-40"
    >
      Critique essay
    </button>
    {#if unreadAvailable}
      <button
        type="button"
        {disabled}
        onclick={() => oncritique?.('unread')}
        class="rounded-lg border border-line px-2.5 py-1.5 text-xs hover:bg-surface-2 disabled:opacity-40"
      >
        Critique unread sections
      </button>
    {/if}
  </div>
</div>
