<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api/client';
  import type { components } from '$lib/api/schema';

  let { courseId, sourceId }: { courseId: string; sourceId: string } = $props();
  let graph = $state<components['schemas']['CourseGraphOut'] | null>(null);
  let unavailable = $state(false);

  onMount(() => {
    let alive = true;
    void api.GET('/courses/{course_id}/graph', {
      params: { path: { course_id: courseId }, query: { source_ids: [sourceId] } }
    }).then(({ data, error }) => {
      if (alive) {
        graph = data ?? null;
        unavailable = !!error;
      }
    }).catch(() => { if (alive) unavailable = true; });
    return () => { alive = false; };
  });
</script>

{#snippet branch(node: components['schemas']['GraphNodeOut'])}
  {#if node.kind === 'passage'}
    <li class="py-1">
      <a href={`/courses/${courseId}/sources/${sourceId}?chunk=${node.id}`}
        data-sveltekit-reload class="text-sm text-accent-text hover:underline">{node.label}</a>
      {#if graph}
        {@const related = (graph.edges ?? []).filter(edge => edge.kind === 'similar' && (edge.source === node.id || edge.target === node.id))}
        {#if related.length}
          <details class="mt-1 text-xs text-muted">
            <summary class="cursor-pointer">Related passages · suggested connections</summary>
            <ul class="pl-4">
              {#each related as edge}
                {@const target = graph.nodes?.find(item => item.id === (edge.source === node.id ? edge.target : edge.source))}
                {#if target}
                  <li><a data-sveltekit-reload href={`/courses/${courseId}/sources/${sourceId}?chunk=${target.id}`} class="hover:underline">{target.label}</a></li>
                {/if}
              {/each}
            </ul>
          </details>
        {/if}
      {/if}
    </li>
  {:else}
    <li>
      <details>
        <summary class="cursor-pointer py-1 text-sm font-medium">
          {node.label}
          {#if node.origin === 'inference'}<span class="text-xs font-normal text-muted"> · inferred heading</span>{/if}
        </summary>
        <ul class="border-l border-line pl-4">
          {#each graph?.nodes?.filter(item => item.parent_id === node.id) ?? [] as child (child.id)}
            {@render branch(child)}
          {/each}
        </ul>
      </details>
    </li>
  {/if}
{/snippet}

<details class="rounded-xl border border-line bg-surface p-4 text-fg-soft">
  <summary class="cursor-pointer text-sm font-semibold">Browse source passages</summary>
  {#if unavailable}
    <p class="mt-2 text-sm text-muted">The passage outline could not be loaded.</p>
  {:else if graph}
    <ul class="mt-2">
      {#each graph.nodes?.filter(node => !node.parent_id) ?? [] as node (node.id)}
        {@render branch(node)}
      {/each}
    </ul>
    {#if !graph.nodes?.length}<p class="mt-2 text-sm text-muted">This source has no indexed passages yet.</p>{/if}
  {:else}
    <p class="mt-2 text-sm text-muted">Loading passages…</p>
  {/if}
</details>
