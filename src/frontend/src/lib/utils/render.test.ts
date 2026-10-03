import assert from 'node:assert/strict';
import { test } from 'node:test';
import { linkCitationTitles, renderMarkdown } from './render';

test('currency is text and real math still renders', () => {
  const money = renderMarkdown('Mexico got $15 million and Polk offered $100 million');
  assert.equal(money.includes('class="katex"'), false);
  assert.equal(money.includes('$15 million'), true);
  assert.equal(money.includes('$100 million'), true);

  const math = renderMarkdown('$x^2$');
  assert.equal(math.includes('class="katex"'), true);

  const fenced = renderMarkdown('```\nprice is $15\n```');
  assert.equal(fenced.includes('$15'), true);
  assert.equal(fenced.includes('class="katex"'), false);
});

test('a cited marker names the file and page, and code is left alone', () => {
  const linked = linkCitationTitles('See [2] and `keep [2]`.', [
    { marker: 2, filename: 'Week1.pdf', label: 'page 3' }
  ]);
  const html = renderMarkdown(linked);
  assert.equal(html.includes('title="Week1.pdf, page 3"'), true);
  assert.equal(html.includes('[2]'), true);
  assert.equal(linked.includes('`keep [2]`'), true);
});
