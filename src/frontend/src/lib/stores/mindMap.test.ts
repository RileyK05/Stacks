import assert from 'node:assert/strict';
import { test } from 'node:test';
import { layoutMap, mapTree, revealPath, visibleNodes, type MindMapContent } from './mindMap';

const map: MindMapContent = {
  nodes: ['movement', 'figure', 'protest', 'separate', 'group'].map(id => ({ id, label: id, summary: id, sources: [1] })),
  edges: [
    { source: 'movement', target: 'figure', kind: 'branch', label: 'figure', explanation: 'related figure', sources: [1] },
    { source: 'movement', target: 'protest', kind: 'branch', label: 'activism', explanation: 'related event', sources: [1] },
    { source: 'separate', target: 'group', kind: 'branch', label: 'organization', explanation: 'separate group', sources: [1] },
    { source: 'movement', target: 'separate', kind: 'similarity', label: 'comparison', explanation: 'shared theme', sources: [1] }
  ]
};

test('similarity does not change branch membership, progressive expansion or focus', () => {
  const tree = mapTree(map);
  assert.deepEqual(tree.roots, ['movement', 'separate']);
  assert.equal(tree.rootOf('group'), 'separate');
  assert.deepEqual([...visibleNodes(map, [], null)], ['movement', 'separate']);
  const expanded = revealPath(map, 'figure', []);
  assert.deepEqual([...visibleNodes(map, expanded, 'movement')], ['movement', 'figure', 'protest']);
  assert.equal(visibleNodes(map, expanded, 'movement').has('group'), false);
  const layout = layoutMap(map);
  assert.ok(layout.positions.get('figure')!.y > layout.positions.get('movement')!.y);
  assert.notEqual(layout.positions.get('movement')!.root, layout.positions.get('separate')!.root);
  assert.deepEqual(layout, layoutMap(map));
});
