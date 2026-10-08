import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  bandFor,
  citationChips,
  coverageLine,
  fallacyLabel,
  latestCritique,
  passageEdited,
  stillOpen
} from './critique';

test('critic bands follow the 30 and 75 anchors', () => {
  assert.equal(bandFor(10).id, 'rough');
  assert.equal(bandFor(29).id, 'rough');
  assert.equal(bandFor(30).label, 'Strong reviewer');
  assert.equal(bandFor(74).id, 'strong');
  assert.equal(bandFor(75).id, 'severe');
  assert.equal(bandFor(100).id, 'severe');
});

test('fallacy labels stay plain language and none stays blank', () => {
  assert.equal(fallacyLabel('none'), '');
  assert.equal(fallacyLabel('straw_man'), 'straw man');
  assert.equal(fallacyLabel('missing_counterargument'), 'missing counterargument');
});

test('a pass groups quotes that remain, quotes that changed, and citation chips', () => {
  const prior = [
    { original: 'still here', feedback: 'The warrant is thin.', status: 'still_present' as const },
    { original: 'gone', feedback: 'The example does not show it.', status: 'passage_changed' as const }
  ];
  assert.deepEqual(stillOpen(prior).map((item) => item.original), ['still here']);
  assert.deepEqual(passageEdited(prior).map((item) => item.original), ['gone']);
  const chips = citationChips('The draft never uses the required reading. [2]', [
    { number: 1, filename: 'notes.pdf', label: 'page 1' },
    { number: 2, filename: 'syllabus.pdf', label: 'page 2' }
  ]);
  assert.deepEqual(chips.map((chip) => chip.filename), ['syllabus.pdf']);
});

test('coverage names a partial window and a latest critique ignores older reviews', () => {
  assert.match(coverageLine({ complete: false, included_sections: [1, 4], total_sections: 6 }), /sections 1, 4 of 6/);
  assert.match(coverageLine({ complete: true, included_sections: [1], total_sections: 1 }), /All captured text/);
  const latest = latestCritique([
    { reply: { critique: null } },
    {
      reply: {
        critique: {
          critic_score: 50,
          genre: 'argumentative',
          syllabus_in_context: false,
          coverage: { complete: true, included_sections: [1], total_sections: 1 },
          note: 'first'
        }
      }
    },
    {
      reply: {
        critique: {
          critic_score: 80,
          genre: 'creative',
          syllabus_in_context: false,
          coverage: { complete: false, included_sections: [2], total_sections: 3 },
          note: 'second'
        }
      }
    }
  ]);
  assert.equal(latest?.note, 'second');
  assert.equal(latestCritique([{ reply: {} }]), null);
});
