import DOMPurify from 'dompurify';
import { marked } from 'marked';
import markedKatex from 'marked-katex-extension';

// Standard mode only treats `$...$` as math when the closing dollar is
// followed by space or punctuation. Currency is escaped as well, because
// `$15 million ... $100 million` still matches that rule.
marked.use(markedKatex({ throwOnError: false }));
marked.setOptions({ breaks: true, gfm: true });

function escapeCurrency(markdown: string): string {
  const parts = markdown.split(/(```[\s\S]*?```|`[^`\n]*`)/g);
  return parts
    .map((part, index) =>
      index % 2 === 1 ? part : part.replace(/(^|[^\\$])\$(?=\d)/g, '$1\\$')
    )
    .join('');
}

const SANITIZE_OPTIONS: Parameters<typeof DOMPurify.sanitize>[1] = {
  USE_PROFILES: { html: true, mathMl: true, svg: true },
  ADD_TAGS: ['semantics', 'annotation'],
  ADD_ATTR: ['title']
};

export interface CitationTitle {
  marker?: number;
  filename?: string;
  label?: string;
}

function escapeAttr(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;');
}

/** Give each cited `[n]` outside code the filename and page as a title. */
export function linkCitationTitles(markdown: string, sources: readonly CitationTitle[]): string {
  const titles = new Map<number, string>();
  sources.forEach((source, index) => {
    const title = [source.filename, source.label].filter(Boolean).join(', ');
    if (title) titles.set(source.marker ?? index + 1, title);
  });
  if (titles.size === 0) return markdown;
  const parts = markdown.split(/(```[\s\S]*?```|`[^`\n]*`)/g);
  return parts
    .map((part, index) => {
      if (index % 2 === 1) return part;
      return part.replace(/\[(\d+)\]/g, (match, raw: string) => {
        const title = titles.get(Number(raw));
        if (!title) return match;
        return `<abbr title="${escapeAttr(title)}">[${raw}]</abbr>`;
      });
    })
    .join('');
}

/** Markdown to HTML, including math. Sanitizing happens in `renderRichText`. */
export function renderMarkdown(text: string): string {
  if (!text.trim()) return '';
  return marked.parse(escapeCurrency(text), { async: false });
}

export function renderRichText(text: string): string {
  const html = renderMarkdown(text);
  if (!html) return '';
  return DOMPurify.sanitize(html, SANITIZE_OPTIONS);
}

/** Model-authored HTML for the workspace: sanitized only, never markdown-parsed. */
export function sanitizeHtml(html: string): string {
  if (!html.trim()) return '';
  return DOMPurify.sanitize(html, SANITIZE_OPTIONS);
}
