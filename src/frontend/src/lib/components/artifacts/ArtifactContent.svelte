<script lang="ts">
  import CodeView from '$lib/components/CodeView.svelte';
  import RichText from '$lib/components/RichText.svelte';
  import WorkspaceHtmlView from '$lib/components/WorkspaceHtmlView.svelte';
  import type {
    ArtifactKind,
    ChartContent,
    CodeContent,
    DocContent,
    FlashcardsContent,
    QuizContent,
    SheetContent,
    SlidesContent
  } from '$lib/stores/artifact.svelte';
  import DocEditor from './DocEditor.svelte';
  import FlashcardsArtifact from './FlashcardsArtifact.svelte';
  import QuizArtifact from './QuizArtifact.svelte';
  import SheetEditor from './SheetEditor.svelte';
  import SlidesEditor from './SlidesEditor.svelte';

  interface Props {
    kind: ArtifactKind;
    title: string;
    content: Record<string, unknown>;
    /** false: a read-only preview (e.g. a proposed model edit). */
    editable?: boolean;
    onchange?: () => void;
    oncite?: (n: number) => void;
    onsection?: (index: number) => void;
    currentSlide?: number;
  }

  let {
    kind,
    title,
    content,
    editable = true,
    onchange = () => {},
    oncite,
    onsection,
    currentSlide = $bindable(0)
  }: Props = $props();

  const doc = $derived(content as unknown as DocContent);
  const code = $derived(content as unknown as CodeContent);
  const chart = $derived(content as unknown as ChartContent);
</script>

{#if kind === 'doc'}
  {#if editable}
    <DocEditor
      markdown={doc.markdown}
      onchange={(markdown) => {
        doc.markdown = markdown;
        onchange();
      }}
      {oncite}
      {onsection}
    />
  {:else if doc.markdown.trim()}
    <RichText text={doc.markdown} class="text-[15px] sm:prose-base" />
  {:else}
    <p class="text-sm italic text-subtle">Empty</p>
  {/if}
{:else if kind === 'sheet'}
  <SheetEditor sheet={content as unknown as SheetContent} {editable} {onchange} />
{:else if kind === 'slides'}
  <SlidesEditor deck={content as unknown as SlidesContent} {title} {editable} bind:current={currentSlide} {onchange} />
{:else if kind === 'quiz'}
  <QuizArtifact quiz={content as unknown as QuizContent} {editable} {onchange} {oncite} />
{:else if kind === 'flashcards'}
  <FlashcardsArtifact deck={content as unknown as FlashcardsContent} {editable} {onchange} {oncite} />
{:else if kind === 'code'}
  <div class="flex flex-col gap-3">
    {#if editable}
      <div class="flex gap-2">
        <input
          bind:value={code.language}
          oninput={onchange}
          placeholder="Language (python, sql, …)"
          aria-label="Language"
          class="h-9 w-56 rounded-lg border border-line-strong bg-surface px-3 text-[13px] text-fg focus:border-accent focus:outline-none"
        />
      </div>
      <textarea
        bind:value={code.code}
        oninput={onchange}
        rows="18"
        spellcheck="false"
        aria-label="Code"
        class="rounded-xl border border-line-strong bg-surface px-4 py-3 font-mono text-[13px] leading-relaxed text-fg focus:border-accent focus:outline-none"
      ></textarea>
    {/if}
    <CodeView item={{ type: 'code', title: null, language: code.language || null, code: code.code, sources: [1] }} sources={[]} />
  </div>
{:else if kind === 'chart'}
  <div class="flex flex-col gap-3">
    <WorkspaceHtmlView item={{ type: 'html', title: null, html: chart.html, sources: [1] }} sources={[]} />
    {#if editable}
      <details class="rounded-xl border border-line bg-surface">
        <summary class="cursor-pointer px-4 py-2.5 text-[13px] font-medium text-muted">Edit the HTML</summary>
        <textarea
          bind:value={chart.html}
          oninput={onchange}
          rows="12"
          spellcheck="false"
          aria-label="Chart HTML"
          class="w-full border-t border-line bg-surface px-4 py-3 font-mono text-[12px] text-fg focus:outline-none"
        ></textarea>
      </details>
    {/if}
  </div>
{/if}
