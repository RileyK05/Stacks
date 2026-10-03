<script lang="ts">
  import 'katex/dist/katex.min.css';
  import { linkCitationTitles, renderRichText, type CitationTitle } from '$lib/utils/render';

  interface Props {
    text: string;
    class?: string;
    sources?: readonly CitationTitle[];
  }

  let { text, class: className = '', sources = [] }: Props = $props();

  const html = $derived(renderRichText(linkCitationTitles(text, sources)));
</script>

<div class="prose prose-sm max-w-none break-words text-fg-soft {className}">
  {@html html}
</div>
