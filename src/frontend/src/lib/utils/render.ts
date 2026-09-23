import DOMPurify from 'dompurify';
import { marked } from 'marked';
import markedKatex from 'marked-katex-extension';

marked.use(markedKatex({ throwOnError: false, nonStandard: true }));
marked.setOptions({ breaks: true, gfm: true });

const SANITIZE_OPTIONS: Parameters<typeof DOMPurify.sanitize>[1] = {
  USE_PROFILES: { html: true, mathMl: true, svg: true },
  ADD_TAGS: ['semantics', 'annotation'],
};

export function renderRichText(text: string): string {
  if (!text.trim()) return '';
  const html = marked.parse(text, { async: false });
  return DOMPurify.sanitize(html, SANITIZE_OPTIONS);
}

/** Model-authored HTML for the workspace: sanitized only, never markdown-parsed. */
export function sanitizeHtml(html: string): string {
  if (!html.trim()) return '';
  return DOMPurify.sanitize(html, SANITIZE_OPTIONS);
}
