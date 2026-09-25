<script lang="ts">
  import 'katex/dist/katex.min.css';
  import { Editor } from '@tiptap/core';
  import { Markdown } from '@tiptap/markdown';
  import Mathematics from '@tiptap/extension-mathematics';
  import { TableKit } from '@tiptap/extension-table';
  import { Placeholder } from '@tiptap/extensions';
  import StarterKit from '@tiptap/starter-kit';
  import { onDestroy, onMount } from 'svelte';
  import Icon from '$lib/components/Icon.svelte';
  import { citationChips } from './citationChips';

  interface Props {
    markdown: string;
    editable?: boolean;
    onchange: (markdown: string) => void;
    oncite?: (n: number) => void;
    /** Which heading section the cursor is in (for "edit this section"). */
    onsection?: (index: number) => void;
  }

  let { markdown, editable = true, onchange, oncite, onsection }: Props = $props();

  let element = $state<HTMLElement | null>(null);
  let editor = $state<Editor | null>(null);
  /** Bumped on every transaction so toolbar state re-reads the editor. */
  let tick = $state(0);
  // The editor writes Markdown in its own canonical form (list markers,
  // spacing), which can differ from what it was given. `baseline` is that
  // canonical form of the content without the student's edits, so loading
  // or re-rendering is never mistaken for an edit; `lastProp` is the last
  // content handed in from outside.
  let baseline = '';
  let lastProp = '';
  // Only the student's own input counts as an edit: loading, re-rendering
  // and content replaced from outside never save a version on their own.
  let userEditing = false;

  /** The editor escapes "[" in Markdown; citations must stay "[n]". */
  function markdownOf(current: Editor): string {
    return current.getMarkdown().replace(/\\\[(\d+(?:\s*,\s*\d+)*)\\\]/g, '[$1]');
  }

  function markUserInput() {
    userEditing = true;
  }

  onMount(() => {
    if (!element) return;
    lastProp = markdown;
    editor = new Editor({
      element,
      editable,
      extensions: [
        StarterKit.configure({ link: { openOnClick: false } }),
        Markdown,
        TableKit.configure({ table: { resizable: false } }),
        Mathematics,
        Placeholder.configure({ placeholder: 'Start writing, or ask Stacks to draft something…' }),
        citationChips((n) => oncite?.(n))
      ],
      content: markdown,
      contentType: 'markdown',
      editorProps: {
        attributes: {
          class:
            'prose prose-sm max-w-none min-h-[60vh] text-[15px] leading-relaxed text-fg-soft focus:outline-none sm:prose-base'
        }
      },
      onTransaction: ({ editor: current }) => {
        tick++;
        if (onsection) onsection(sectionAt(current));
      },
      onCreate: ({ editor: current }) => {
        baseline = markdownOf(current);
      },
      onUpdate: ({ editor: current }) => {
        // Normalisation (e.g. the trailing empty paragraph TipTap adds on
        // load) changes the document but not its Markdown: not an edit.
        const next = markdownOf(current);
        if (!userEditing || next.trim() === baseline.trim()) return;
        baseline = next;
        lastProp = next;
        onchange(next);
      }
    });
  });

  onDestroy(() => editor?.destroy());

  $effect(() => {
    // Content replaced from outside (an accepted model edit, a restore).
    if (editor && markdown !== lastProp) {
      lastProp = markdown;
      editor.commands.setContent(markdown, { contentType: 'markdown', emitUpdate: false });
      baseline = markdownOf(editor);
    }
  });

  $effect(() => {
    editor?.setEditable(editable);
  });

  /** The section the cursor is in, numbered like the backend's
      doc_sections: a doc split at its headings, text before the first
      heading being section 0 when there is any. */
  function sectionAt(current: Editor): number {
    const { from } = current.state.selection;
    let headingsBefore = 0;
    let startsWithHeading = false;
    current.state.doc.forEach((node, offset, index) => {
      if (index === 0) startsWithHeading = node.type.name === 'heading';
      if (offset < from && node.type.name === 'heading') headingsBefore++;
    });
    return Math.max(0, headingsBefore - (startsWithHeading ? 1 : 0));
  }

  type Action = {
    icon?: string;
    label: string;
    text?: string;
    active?: () => boolean;
    run: () => void;
  };

  const blocks: Action[] = [
    { label: 'Text', text: 'P', active: () => !!editor?.isActive('paragraph'), run: () => editor?.chain().focus().setParagraph().run() },
    { label: 'Heading 1', text: 'H1', active: () => !!editor?.isActive('heading', { level: 1 }), run: () => editor?.chain().focus().toggleHeading({ level: 1 }).run() },
    { label: 'Heading 2', text: 'H2', active: () => !!editor?.isActive('heading', { level: 2 }), run: () => editor?.chain().focus().toggleHeading({ level: 2 }).run() },
    { label: 'Heading 3', text: 'H3', active: () => !!editor?.isActive('heading', { level: 3 }), run: () => editor?.chain().focus().toggleHeading({ level: 3 }).run() }
  ];

  const marks: Action[] = [
    { label: 'Bold', text: 'B', active: () => !!editor?.isActive('bold'), run: () => editor?.chain().focus().toggleBold().run() },
    { label: 'Italic', text: 'I', active: () => !!editor?.isActive('italic'), run: () => editor?.chain().focus().toggleItalic().run() },
    { label: 'Strikethrough', text: 'S', active: () => !!editor?.isActive('strike'), run: () => editor?.chain().focus().toggleStrike().run() },
    { label: 'Inline code', text: '</>', active: () => !!editor?.isActive('code'), run: () => editor?.chain().focus().toggleCode().run() }
  ];

  const structures: Action[] = [
    { label: 'Bulleted list', text: '•', active: () => !!editor?.isActive('bulletList'), run: () => editor?.chain().focus().toggleBulletList().run() },
    { label: 'Numbered list', text: '1.', active: () => !!editor?.isActive('orderedList'), run: () => editor?.chain().focus().toggleOrderedList().run() },
    { label: 'Quote', text: '❝', active: () => !!editor?.isActive('blockquote'), run: () => editor?.chain().focus().toggleBlockquote().run() },
    { label: 'Code block', text: '{ }', active: () => !!editor?.isActive('codeBlock'), run: () => editor?.chain().focus().toggleCodeBlock().run() },
    { label: 'Table', text: '▦', run: () => editor?.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run() },
    {
      label: 'Math',
      text: '∑',
      run: () => {
        const latex = prompt('LaTeX, e.g. \\frac{a}{b}');
        if (latex) editor?.chain().focus().insertInlineMath({ latex }).run();
      }
    },
    { label: 'Divider', text: '—', run: () => editor?.chain().focus().setHorizontalRule().run() }
  ];
</script>

{#snippet button(action: Action)}
  {@const on = (void tick, action.active?.() ?? false)}
  <button
    type="button"
    title={action.label}
    aria-label={action.label}
    aria-pressed={on}
    onmousedown={(event) => event.preventDefault()}
    onclick={() => {
      markUserInput();
      action.run();
    }}
    class={`flex h-8 min-w-8 items-center justify-center rounded-md px-1.5 text-[13px] font-semibold transition-colors ${
      on ? 'bg-accent-soft text-accent-text' : 'text-muted hover:bg-surface-2 hover:text-fg'
    }`}
  >
    {action.text}
  </button>
{/snippet}

<div class="flex flex-col">
  {#if editable}
    <div
      class="sticky top-0 z-20 flex flex-wrap items-center gap-0.5 rounded-xl border border-line bg-surface/95 p-1 shadow-card backdrop-blur"
      role="toolbar"
      aria-label="Formatting"
    >
      {#each blocks as action (action.label)}{@render button(action)}{/each}
      <span class="mx-1 h-5 w-px bg-line"></span>
      {#each marks as action (action.label)}{@render button(action)}{/each}
      <span class="mx-1 h-5 w-px bg-line"></span>
      {#each structures as action (action.label)}{@render button(action)}{/each}
      <span class="mx-1 h-5 w-px bg-line"></span>
      <button
        type="button"
        title="Undo"
        aria-label="Undo"
        onmousedown={(event) => event.preventDefault()}
        onclick={() => {
          markUserInput();
          editor?.chain().focus().undo().run();
        }}
        class="flex h-8 w-8 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg"
      >
        <Icon name="rotate-ccw" class="h-3.5 w-3.5" />
      </button>
    </div>
  {/if}
  <div
    bind:this={element}
    class="doc-editor mt-5 px-1"
    role="presentation"
    onkeydown={markUserInput}
    onpaste={markUserInput}
    ondrop={markUserInput}
    oncut={markUserInput}
  ></div>
</div>

<style>
  :global(.doc-editor .ProseMirror p.is-editor-empty:first-child::before) {
    content: attr(data-placeholder);
    float: left;
    height: 0;
    pointer-events: none;
    color: var(--subtle);
  }
  :global(.doc-editor .cite-chip) {
    cursor: pointer;
    border-radius: 0.375rem;
    background: var(--accent-soft);
    color: var(--accent-text);
    padding: 0 0.2em;
    font-size: 0.8em;
    font-weight: 600;
    font-family: var(--font-mono);
  }
  :global(.doc-editor table) {
    border-collapse: collapse;
  }
  :global(.doc-editor td),
  :global(.doc-editor th) {
    border: 1px solid var(--line-strong);
    padding: 0.35rem 0.6rem;
    vertical-align: top;
  }
  :global(.doc-editor th) {
    background: var(--surface-2);
  }
  :global(.doc-editor .selectedCell) {
    background: var(--accent-soft);
  }
  :global(.doc-editor .tiptap-mathematics-render) {
    cursor: pointer;
  }
</style>
