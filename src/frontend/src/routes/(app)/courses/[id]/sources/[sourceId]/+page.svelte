<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { page } from '$app/state';
  import { api } from '$lib/api/client';
  import { APP_TOKEN_HEADER, apiBase, appToken } from '$lib/api/backend';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon from '$lib/components/Icon.svelte';

  const courseId = page.params.id ?? '';
  const sourceId = page.params.sourceId ?? '';
  const chunkId = page.url.searchParams.get('chunk');
  let filename = $state('Source');
  let content = $state('');
  let pageImage = $state('');
  let pageNumber = $state(1);
  let pageCount = $state(1);
  let pageLoading = $state(false);
  let passage = $state<{ text: string; label: string; description: string | null } | null>(null);
  let markedLine = $state(0);
  let error = $state<unknown>(null);
  let loading = $state(true);
  let alive = true;
  let objectUrl = '';

  const lines = $derived(content.split('\n'));

  function authorizedGet(path: string): Promise<Response> {
    const token = appToken();
    return fetch(`${apiBase()}${path}`, {
      headers: token ? { [APP_TOKEN_HEADER]: token } : undefined
    });
  }

  async function showPage(number: number) {
    pageLoading = true;
    try {
      const response = await authorizedGet(
        `/courses/${courseId}/sources/${sourceId}/pages/${number}`
      );
      if (!response.ok) throw new Error(`Could not render page ${number} (${response.status}).`);
      const bytes = await response.blob();
      if (!alive) return;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = URL.createObjectURL(bytes);
      pageImage = objectUrl;
      pageNumber = number;
      pageCount = Number(response.headers.get('X-Page-Count') ?? '1');
    } catch (caught) {
      if (alive) error = caught;
    } finally {
      if (alive) pageLoading = false;
    }
  }

  onMount(() => {
    async function load() {
      try {
        const { data: sources, error: listError } = await api.GET('/courses/{course_id}/sources', {
          params: { path: { course_id: courseId } }
        });
        if (listError) throw listError;
        const source = sources?.find((item) => item.source_id === sourceId);
        if (!source) throw new Error('Source not found in this course.');
        filename = source.filename;
        if (chunkId) {
          const { data, error: passageError } = await api.GET(
            '/courses/{course_id}/sources/{source_id}/chunks/{chunk_id}',
            { params: { path: { course_id: courseId, source_id: sourceId, chunk_id: chunkId } } }
          );
          if (passageError) throw passageError;
          passage = data ?? null;
        }
        if (source.mime_type === 'application/pdf') {
          const citedPage = Number(passage?.label.match(/^page (\d+)$/)?.[1] ?? '1');
          await showPage(citedPage);
        } else {
          const response = await authorizedGet(`/courses/${courseId}/sources/${sourceId}/content`);
          if (!response.ok) throw new Error(`Could not open source (${response.status}).`);
          const bytes = await response.arrayBuffer();
          if (!alive) return;
          try {
            content = new TextDecoder('utf-8', { fatal: true }).decode(bytes).replace(/^\uFEFF/, '');
          } catch {
            content = new TextDecoder('windows-1252').decode(bytes);
          }
          if (passage) {
            const first = passage.text.trim().slice(0, 80);
            const offset = first ? content.indexOf(first) : -1;
            if (offset >= 0) markedLine = content.slice(0, offset).split('\n').length;
            else {
              const match = passage.label.match(/^lines (\d+)/);
              if (match) markedLine = Number(match[1]);
            }
            await tick();
            document.getElementById(`line-${markedLine}`)?.scrollIntoView({ block: 'center' });
          }
        }
      } catch (caught) {
        if (alive) error = caught;
      } finally {
        if (alive) loading = false;
      }
    }
    void load();
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  });
</script>

<div class="mx-auto flex max-w-6xl flex-col gap-4 px-5 py-6">
  <a href={`/courses/${courseId}?tab=sources`} class="inline-flex items-center gap-1.5 self-start text-sm text-muted hover:text-fg">
    <Icon name="chevron-left" class="h-4 w-4" /> Back to course
  </a>
  <div>
    <h1 class="font-display text-2xl text-fg">{filename}</h1>
    {#if passage}<p class="mt-1 text-sm text-muted">Cited passage · {passage.label}</p>{/if}
  </div>
  {#if error}<ErrorBanner {error} />{/if}
  {#if loading}<p class="text-sm text-muted">Opening source…</p>{/if}
  {#if passage}
    <aside class="rounded-xl border border-accent-line bg-accent-soft p-4 text-sm leading-relaxed text-fg-soft">
      <p class="mb-2 font-semibold text-accent-text">Passage used in the answer</p>
      <p class="whitespace-pre-wrap">{passage.text}</p>
    </aside>
  {/if}
  {#if pageImage}
    <div class="flex items-center justify-center gap-4 text-sm text-muted">
      <button type="button" onclick={() => showPage(pageNumber - 1)} disabled={pageNumber <= 1 || pageLoading} class="rounded-lg border border-line px-3 py-1.5 disabled:opacity-40">Previous</button>
      <span>Page {pageNumber} of {pageCount}</span>
      <button type="button" onclick={() => showPage(pageNumber + 1)} disabled={pageNumber >= pageCount || pageLoading} class="rounded-lg border border-line px-3 py-1.5 disabled:opacity-40">Next</button>
    </div>
    <img src={pageImage} alt={`Page ${pageNumber} of ${filename}`} class="mx-auto max-h-[75vh] max-w-full rounded-xl border border-line bg-white object-contain shadow-card" />
  {:else if content}
    <div class="max-h-[75vh] overflow-auto rounded-xl border border-line bg-surface py-4 font-mono text-xs leading-6">
      {#each lines as line, index (index)}
        <div id={`line-${index + 1}`} class={`flex px-4 ${markedLine === index + 1 ? 'bg-accent-soft' : ''}`}>
          <span class="mr-5 w-10 shrink-0 select-none text-right text-subtle">{index + 1}</span>
          <span class="whitespace-pre-wrap break-words">{line || ' '}</span>
        </div>
      {/each}
    </div>
  {/if}
</div>
