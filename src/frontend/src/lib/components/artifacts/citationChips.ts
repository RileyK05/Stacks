import { Extension } from '@tiptap/core';
import { Plugin, PluginKey } from '@tiptap/pm/state';
import { Decoration, DecorationSet } from '@tiptap/pm/view';
import type { Node as PMNode } from '@tiptap/pm/model';

const CITATION = /\[(\d+(?:\s*,\s*\d+)*)\]/g;

function decorate(doc: PMNode): DecorationSet {
  const decorations: Decoration[] = [];
  doc.descendants((node, pos) => {
    if (!node.isText || !node.text) return;
    for (const match of node.text.matchAll(CITATION)) {
      const from = pos + (match.index ?? 0);
      decorations.push(
        Decoration.inline(from, from + match[0].length, {
          class: 'cite-chip',
          'data-cite': match[1].split(',')[0].trim()
        })
      );
    }
  });
  return DecorationSet.create(doc, decorations);
}

/**
 * "[n]" citations stay plain text in the document (so Markdown, exports
 * and model edits all see the same thing) but render as chips; clicking
 * one reports its number.
 */
export function citationChips(onOpen: (n: number) => void) {
  const key = new PluginKey('citationChips');
  return Extension.create({
    name: 'citationChips',
    addProseMirrorPlugins() {
      return [
        new Plugin({
          key,
          state: {
            init: (_, state) => decorate(state.doc),
            apply: (tr, old) => (tr.docChanged ? decorate(tr.doc) : old)
          },
          props: {
            decorations(state) {
              return key.getState(state) as DecorationSet;
            },
            handleClick(_view, _pos, event) {
              const target = (event.target as HTMLElement | null)?.closest?.('[data-cite]');
              if (!target) return false;
              onOpen(Number(target.getAttribute('data-cite')));
              return true;
            }
          }
        })
      ];
    }
  });
}
