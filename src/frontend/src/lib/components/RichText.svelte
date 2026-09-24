<script lang="ts">
  import 'katex/dist/katex.min.css';
  import { renderRichText } from '$lib/utils/render';

  interface Props {
    text: string;
    class?: string;
  }

  let { text, class: className = '' }: Props = $props();

  const html = $derived(renderRichText(text));
</script>

<div class="prose prose-sm max-w-none text-fg-soft {className}">
  {@html html}
</div>
