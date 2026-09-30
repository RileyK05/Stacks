<script lang="ts">
  import { onMount } from 'svelte';
  import RichText from './RichText.svelte';
  import QuizArtifact from './artifacts/QuizArtifact.svelte';
  import { MapStudy } from '$lib/stores/mapStudy.svelte';
  import { groupColor, layoutMap, mapTree, revealPath, visibleNodes, type MapContext, type MapEdge, type MapSource, type MindMapContent } from '$lib/stores/mindMap';
  import type { QuizContent } from '$lib/stores/artifact.svelte';

  interface Props { map: MindMapContent; sources?: (MapSource | null)[]; context?: MapContext; ongenerated?: () => void | Promise<void> }
  let { map, sources = [], context, ongenerated }: Props = $props();
  let expanded = $state<string[]>([]), selectedId = $state<string | null>(null), selectedEdge = $state<MapEdge | null>(null);
  let focus = $state<string | null>(null), similarities = $state(true), zoom = $state(1);
  let viewport = $state<HTMLDivElement | null>(null);
  const study = new MapStudy();
  const tree = $derived(mapTree(map)), layout = $derived(layoutMap(map));
  const visible = $derived(visibleNodes(map, expanded, focus));
  const selected = $derived(map.nodes.find((node) => node.id === selectedId));
  const activeEdges = $derived(map.edges.filter((e) => visible.has(e.source) && visible.has(e.target) && (e.kind === 'branch' || similarities)));
  const bounds = $derived.by(() => {
    const positions = [...visible].map((id) => layout.positions.get(id)!).filter(Boolean);
    if (!positions.length) return { x: 0, y: 0, width: 420, height: 180 };
    return { x: Math.min(...positions.map(p => p.x)) - 105, y: Math.min(...positions.map(p => p.y)) - 70,
      width: Math.max(420, Math.max(...positions.map(p => p.x)) - Math.min(...positions.map(p => p.x)) + 210),
      height: Math.max(180, Math.max(...positions.map(p => p.y)) - Math.min(...positions.map(p => p.y)) + 140) };
  });
  const detailSources = $derived(selectedEdge?.sources ?? selected?.sources ?? []);
  const incident = $derived(selected ? map.edges.filter(e => e.source === selected.id || e.target === selected.id) : []);
  let identity = '';
  $effect(() => {
    const next = JSON.stringify([context?.courseId, context?.origin, map]);
    if (next !== identity) { identity = next; expanded = []; selectedId = null; selectedEdge = null; focus = null; study.clear(); }
  });
  onMount(() => fit());
  function fit() { zoom = Math.max(0.25, Math.min(1, ((viewport?.clientWidth ?? 700) - 12) / bounds.width)); }
  function select(id: string) { selectedId = id; selectedEdge = null; expanded = revealPath(map, id, expanded); study.clear(); }
  function toggle(id: string) { expanded = expanded.includes(id) ? expanded.filter(n => n !== id) : [...expanded, id]; }
  function edgePath(edge: MapEdge) {
    const a = layout.positions.get(edge.source)!, b = layout.positions.get(edge.target)!;
    const x1 = a.x - bounds.x, y1 = a.y - bounds.y, x2 = b.x - bounds.x, y2 = b.y - bounds.y;
    return edge.kind === 'similarity' ? `M ${x1} ${y1} Q ${(x1+x2)/2} ${Math.min(y1,y2)-65} ${x2} ${y2}` : `M ${x1} ${y1+35} C ${x1} ${(y1+y2)/2} ${x2} ${(y1+y2)/2} ${x2} ${y2-35}`;
  }
  function edgePosition(edge: MapEdge) {
    const a = layout.positions.get(edge.source)!, b = layout.positions.get(edge.target)!;
    return { x: (a.x + b.x) / 2 - bounds.x,
      y: edge.kind === 'similarity' ? (a.y + b.y) / 4 + (Math.min(a.y, b.y) - 65) / 2 - bounds.y : (a.y + b.y) / 2 - bounds.y };
  }
  function edgeName(edge: MapEdge) {
    return `${edge.kind === 'similarity' ? 'Compare' : 'Connection'}: ${map.nodes.find(n => n.id === edge.source)?.label} and ${map.nodes.find(n => n.id === edge.target)?.label} — ${edge.label}`;
  }
  async function ask(action: 'explain' | 'quiz') {
    if (!context || !selected) return;
    await study.request(context, selected.id, action);
    if (study.result?.quiz_id) await ongenerated?.();
  }
</script>

<div class="space-y-4">
  {#if !map.nodes.length}
    <p class="rounded-xl border border-line p-6 text-sm text-muted">This map is empty. Ask for a map of your course topics using the model-edit box below, or generate one in your course chat.</p>
  {:else}
  <p class="text-[12px] text-muted">Explore the supplied passages. Colors group topic branches; dashed links compare related ideas. Position is a guide, not a measured similarity score.</p>
  <div class="flex flex-wrap items-center gap-2 text-[12px]">
    <label class="flex items-center gap-2">Find a topic
      <select aria-label="Find a map topic" value={selectedId ?? ''} onchange={e => { focus = null; select(e.currentTarget.value); }} class="max-w-56 rounded-lg border border-line-strong bg-surface px-2 py-1.5">
        <option value="" disabled>Choose a topic…</option>
        {#each map.nodes as node (node.id)}<option value={node.id}>{node.label}</option>{/each}
      </select>
    </label>
    <label class="flex items-center gap-1.5"><input type="checkbox" bind:checked={similarities} /> Similarity links</label>
    <button type="button" onclick={() => zoom = Math.max(0.25, zoom - 0.15)} aria-label="Zoom out" class="rounded border border-line px-2 py-1">−</button>
    <span>{Math.round(zoom * 100)}%</span>
    <button type="button" onclick={() => zoom = Math.min(2, zoom + 0.15)} aria-label="Zoom in" class="rounded border border-line px-2 py-1">+</button>
    <button type="button" onclick={fit} class="rounded border border-line px-2 py-1">Fit</button>
    <button type="button" onclick={() => { focus = null; expanded = []; selectedId = null; selectedEdge = null; study.clear(); }} class="rounded border border-line px-2 py-1">Reset view</button>
    {#if focus}<button type="button" onclick={() => focus = null} class="font-medium text-accent-text">Show all topics</button>{/if}
  </div>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the graph region.) -->
  <div bind:this={viewport} class="overflow-auto rounded-xl border border-line bg-bg p-2" style="max-height: 65vh" aria-label="Interactive topic map" role="region" tabindex="0">
    <div class="relative" style:width={`${bounds.width * zoom}px`} style:height={`${bounds.height * zoom}px`}>
      <div class="absolute left-0 top-0 origin-top-left" style:width={`${bounds.width}px`} style:height={`${bounds.height}px`} style:transform={`scale(${zoom})`}>
        <svg width={bounds.width} height={bounds.height} class="absolute inset-0" aria-label="Topic connections">
          {#each activeEdges as edge (`${edge.source}:${edge.target}`)}
            <g>
              <title>{edge.label}</title>
              <path d={edgePath(edge)} fill="none" stroke={edge.kind === 'similarity' ? '#94a3b8' : groupColor(layout.positions.get(edge.source)!.root, tree.roots)} stroke-width="2" stroke-dasharray={edge.kind === 'similarity' ? '6 5' : undefined} />
            </g>
          {/each}
        </svg>
        {#each activeEdges as edge (`${edge.source}:${edge.target}`)}
          {@const point = edgePosition(edge)}
          <button type="button" class="absolute flex h-7 w-7 items-center justify-center rounded-full border border-line-strong bg-surface text-sm text-muted hover:text-fg focus-visible:ring-2 focus-visible:ring-fg"
            style:left={`${point.x - 14}px`} style:top={`${point.y - 14}px`} title={edgeName(edge)}
            aria-label={edgeName(edge)} aria-pressed={selectedEdge === edge}
            onclick={() => { selectedEdge = edge; study.clear(); }}>{edge.kind === 'similarity' ? '↔' : '⋯'}</button>
        {/each}
        {#each map.nodes.filter(node => visible.has(node.id)) as node (node.id)}
          {@const position = layout.positions.get(node.id)!}
          {@const children = tree.children.get(node.id) ?? []}
          <div class="absolute flex flex-col items-center gap-1" style:left={`${position.x - bounds.x - 80}px`} style:top={`${position.y - bounds.y - 40}px`} style:width="160px">
            <button type="button" onclick={() => select(node.id)} aria-pressed={selectedId === node.id && !selectedEdge}
              class={`map-node w-full rounded-full border-2 bg-surface px-3 py-3 text-[13px] shadow-card ${position.depth === 0 ? 'min-h-20 font-semibold' : 'min-h-16'} ${selectedId === node.id && !selectedEdge ? 'ring-2 ring-fg ring-offset-2 ring-offset-bg' : ''}`}
              style:border-color={groupColor(position.root, tree.roots)} title={node.label}>{node.label}</button>
            {#if children.length}
              <button type="button" aria-expanded={expanded.includes(node.id)} aria-label={`${expanded.includes(node.id) ? 'Collapse' : 'Expand'} ${node.label}`} onclick={() => { select(node.id); toggle(node.id); }} class="rounded-full border border-line bg-surface px-2 py-0.5 text-[11px] text-muted hover:text-fg">{expanded.includes(node.id) ? '− Collapse' : `+ ${children.length} connections`}</button>
            {/if}
          </div>
        {/each}
      </div>
    </div>
  </div>

  {#if selected || selectedEdge}
    <section class="space-y-3 rounded-xl border border-line bg-surface p-4" aria-label="Map details">
      {#if selectedEdge}
        <p class="text-[11px] font-medium uppercase tracking-wide text-subtle">{selectedEdge.kind === 'similarity' ? 'Comparison · not membership' : 'Topic connection'}</p>
        <h3 class="font-semibold">{map.nodes.find(n => n.id === selectedEdge!.source)?.label} → {map.nodes.find(n => n.id === selectedEdge!.target)?.label}</h3>
        <p class="text-sm font-medium">Suggested relationship: {selectedEdge.label}</p><blockquote class="border-l-2 border-line-strong pl-3 text-sm text-muted">{selectedEdge.explanation}</blockquote>
        <div class="flex gap-3 text-xs"><button type="button" onclick={() => select(selectedEdge!.source)} class="text-accent-text">Open first topic</button><button type="button" onclick={() => select(selectedEdge!.target)} class="text-accent-text">Open second topic</button></div>
      {:else if selected}
        <h3 class="font-semibold">{selected.label}</h3><p class="text-sm text-muted">{selected.summary}</p>
        <div class="flex flex-wrap gap-2">
          <button type="button" onclick={() => { focus = selected!.id; expanded = [...new Set([...expanded, selected!.id])]; }} class="rounded-lg border border-line px-3 py-1.5 text-xs">Focus on this topic</button>
          <button type="button" onclick={() => ask('explain')} disabled={!context || context.ready === false || study.busy} class="rounded-lg border border-line px-3 py-1.5 text-xs disabled:opacity-40">Explain this</button>
          <button type="button" onclick={() => ask('quiz')} disabled={!context || context.ready === false || study.busy} class="rounded-lg bg-accent px-3 py-1.5 text-xs text-on-accent disabled:opacity-40">Quiz me here</button>
        </div>
        {#if !context}<p class="text-xs text-subtle">Study actions become available once this map is saved.</p>{:else if context.ready === false}<p class="text-xs text-subtle">Finish saving the map before studying it.</p>{/if}
        <details><summary class="cursor-pointer text-xs font-medium">{incident.length} named connections</summary><div class="mt-2 space-y-1">{#each incident as edge}<button type="button" onclick={() => { selectedEdge = edge; study.clear(); }} class="block text-left text-xs text-accent-text">{edge.kind === 'similarity' ? 'Compare: ' : ''}{edge.label} — {map.nodes.find(n => n.id === (edge.source === selected!.id ? edge.target : edge.source))?.label}</button>{/each}</div></details>
      {/if}
      <div class="space-y-2">
        {#each [...new Set(detailSources)] as number (number)}
          {@const source = sources[number - 1]}
          <details class="rounded-lg border border-line p-2 text-xs"><summary class="cursor-pointer font-medium text-accent-text">[{number}] {source ? `${source.filename} · ${source.label}` : 'Source unavailable'}</summary>
            {#if source}<p class="mt-2 whitespace-pre-wrap leading-relaxed text-muted">{source.text}</p>{#if context}<a class="mt-2 inline-block text-accent-text hover:underline" href={`/courses/${context.courseId}/sources/${source.source_id}?chunk=${source.chunk_id}`}>Open source passage</a>{/if}{/if}
          </details>
        {/each}
      </div>
      {#if study.busy}<p role="status" class="text-sm text-muted">Preparing source-backed help…</p>{/if}
      {#if study.error}<p role="alert" class="text-sm text-danger-text">{study.error}</p>{/if}
      {#if study.result}
        {@const result = study.result}
        <div class="space-y-3 border-t border-line pt-3">
          <p class="text-[11px] text-subtle">{result.model}{result.fell_back_to_local ? ' · Used the local fallback' : ''}</p>
          {#if result.quiz && result.quiz_id && context}
            <a href={`/courses/${context.courseId}/artifacts/${result.quiz_id}`} class="text-xs text-accent-text hover:underline">Open saved practice quiz</a>
            <QuizArtifact quiz={result.quiz as unknown as QuizContent} editable={false} onchange={() => {}} practice={{ courseId: context.courseId, artifactId: result.quiz_id, version: result.quiz_version ?? 1, ready: true }} />
          {:else}<RichText text={result.text} />{/if}
          {#each result.citations as citation, index}<details class="rounded-lg border border-line p-2 text-xs"><summary class="cursor-pointer text-accent-text">[{index+1}] {citation.filename} · {citation.label}</summary><p class="mt-2 whitespace-pre-wrap text-muted">{citation.text}</p></details>{/each}
        </div>
      {/if}
    </section>
  {/if}
  {/if}
</div>

<style>
  .map-node:hover { filter: brightness(1.08); }
</style>
