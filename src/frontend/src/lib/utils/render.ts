import DOMPurify from 'dompurify';
import { marked } from 'marked';
import markedKatex from 'marked-katex-extension';

marked.use(markedKatex({ throwOnError: false, nonStandard: true }));
marked.setOptions({ breaks: true, gfm: true });

export function renderRichText(text: string): string {
  if (!text.trim()) return '';
  const html = marked.parse(text, { async: false });
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true, mathMl: true, svg: true },
    ADD_TAGS: ['semantics', 'annotation'],
  });
}
