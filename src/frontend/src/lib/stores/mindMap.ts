import type { components } from '$lib/api/schema';

export type MapNode = components['schemas']['MapNode'];
export type MapEdge = components['schemas']['MapEdge'];
export interface MindMapContent { nodes: MapNode[]; edges: MapEdge[] }
export interface MapSource { filename: string; label: string; text: string; chunk_id: string; source_id: string }
export interface MapContext { courseId: string; origin: components['schemas']['MapOrigin']; ready?: boolean }

export function mapTree(map: MindMapContent) {
  const children = new Map(map.nodes.map((node) => [node.id, [] as string[]]));
  const parent = new Map<string, string>();
  for (const edge of map.edges) if (edge.kind === 'branch') {
    children.get(edge.source)?.push(edge.target);
    parent.set(edge.target, edge.source);
  }
  const roots = map.nodes.filter((node) => !parent.has(node.id)).map((node) => node.id);
  const rootOf = (id: string): string => {
    const seen = new Set<string>();
    while (parent.has(id) && !seen.has(id)) { seen.add(id); id = parent.get(id)!; }
    return id;
  };
  return { children, parent, roots, rootOf };
}

export function descendants(map: MindMapContent, id: string): Set<string> {
  const { children } = mapTree(map), found = new Set<string>();
  const visit = (current: string) => { if (found.has(current)) return; found.add(current); children.get(current)?.forEach(visit); };
  visit(id);
  return found;
}

export function visibleNodes(map: MindMapContent, expanded: string[], focus: string | null) {
  const { children, roots } = mapTree(map), found = new Set<string>();
  const visit = (id: string) => {
    if (found.has(id)) return;
    found.add(id);
    if (expanded.includes(id)) children.get(id)?.forEach(visit);
  };
  (focus ? [focus] : roots).forEach(visit);
  return found;
}

export function revealPath(map: MindMapContent, id: string, expanded: string[]) {
  const { parent } = mapTree(map), result = new Set(expanded);
  const seen = new Set<string>();
  while (parent.has(id) && !seen.has(id)) { seen.add(id); id = parent.get(id)!; result.add(id); }
  return [...result];
}

export function layoutMap(map: MindMapContent) {
  const tree = mapTree(map);
  const remaining = [...tree.roots], ordered: string[] = [];
  while (remaining.length) {
    if (ordered.length) {
      const last = ordered.at(-1)!;
      const score = (root: string) => map.edges.filter((e) => e.kind === 'similarity' &&
        ((tree.rootOf(e.source) === last && tree.rootOf(e.target) === root) ||
         (tree.rootOf(e.target) === last && tree.rootOf(e.source) === root))).length;
      remaining.sort((a, b) => score(b) - score(a));
    }
    ordered.push(remaining.shift()!);
  }
  const positions = new Map<string, { x: number; y: number; root: string; depth: number }>();
  let leaf = 0, maxDepth = 0;
  const visit = (id: string, root: string, depth: number): number => {
    const children = tree.children.get(id) ?? [];
    const xs = children.map((child) => visit(child, root, depth + 1));
    const x = xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 105 + leaf++ * 200;
    positions.set(id, { x, y: 80 + depth * 150, root, depth });
    maxDepth = Math.max(maxDepth, depth);
    return x;
  };
  ordered.forEach((root) => { visit(root, root, 0); leaf += 0.5; });
  return { positions, width: Math.max(420, leaf * 200 + 20), height: maxDepth * 150 + 180 };
}

export function groupColor(id: string, roots: string[] = []) {
  const index = [...roots].sort().indexOf(id);
  if (index >= 0) return `hsl(${(index * 137.508 + 210) % 360} 70% 68%)`;
  const palette = ['#60a5fa', '#a78bfa', '#34d399', '#fbbf24', '#fb7185', '#22d3ee'];
  let hash = 0;
  for (const letter of id) hash = (hash * 31 + letter.charCodeAt(0)) >>> 0;
  return palette[hash % palette.length];
}
