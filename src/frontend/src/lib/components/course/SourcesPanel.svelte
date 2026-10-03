<script lang="ts">
  import { api } from '$lib/api/client';
  import type { paths } from '$lib/api/schema';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Select from '$lib/components/Select.svelte';
  import Spinner from '$lib/components/Spinner.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { formatBytes } from '$lib/utils/format';
  import { humanize, plural } from '$lib/utils/labels';

  type SourceView =
    paths['/courses/{course_id}/sources']['get']['responses'][200]['content']['application/json'][number];
  type UploadBody = NonNullable<
    paths['/courses/{course_id}/sources']['post']['requestBody']
  >['content']['multipart/form-data'];
  type SourceType = NonNullable<UploadBody['source_type']>;
  type SourceChoice = SourceType | 'auto';

  interface Props {
    courseId: string;
    sources: SourceView[];
    onchanged: () => Promise<void>;
  }

  interface PendingFile {
    key: string;
    filename: string;
    position: number;
    total: number;
    state: 'waiting' | 'uploading';
  }

  let { courseId, sources, onchanged }: Props = $props();

  let sourceType = $state<SourceChoice>('auto');
  let uploading = $state(false);
  let pendingFiles = $state<PendingFile[]>([]);
  let uploadError = $state<unknown>(null);
  let actionError = $state<unknown>(null);
  let dragOver = $state(false);
  /** The source with a retry / reindex / remove / type change in flight. */
  let busyId = $state<string | null>(null);
  let menuFor = $state<string | null>(null);
  let fileInput = $state<HTMLInputElement | null>(null);

  const storedTypes = [
    'syllabus',
    'slides',
    'textbook',
    'problem_set',
    'solutions',
    'notes',
    'feedback',
    'exam',
    'video',
    'audio',
    'code'
  ] as const;

  const sourceTypeOptions = [
    { value: 'auto' as const, label: 'Auto' },
    ...storedTypes.map((value) => ({ value, label: humanize(value) }))
  ];

  const stageLabel: Record<string, string> = {
    extract_text: 'Extracting',
    ocr: 'Reading scans',
    prepare_passages: 'Preparing passages',
    publish_index: 'Publishing'
  };

  function indexingLabel(stage: string | null | undefined): string {
    if (!stage) return 'Queued';
    return stageLabel[stage] ?? 'Indexing';
  }

  function coverage(source: SourceView): string {
    const parts = [formatBytes(source.size_bytes ?? 0)];
    if (source.pages_total != null) parts.push(plural(source.pages_total, 'page'));
    if (source.chunk_count > 0) parts.push(plural(source.chunk_count, 'passage'));
    if (source.pages_empty) parts.push(`${plural(source.pages_empty, 'page')} had no text`);
    if (source.pages_low_quality) {
      const verb = source.pages_low_quality === 1 ? 'was' : 'were';
      parts.push(`${plural(source.pages_low_quality, 'page')} ${verb} hard to read`);
    }
    return parts.join(' · ');
  }

  async function uploadFiles(files: File[]) {
    if (uploading || files.length === 0) return;
    uploading = true;
    uploadError = null;
    const batch: PendingFile[] = files.map((file, index) => ({
      key: `${Date.now()}-${index}-${file.name}`,
      filename: file.name,
      position: index + 1,
      total: files.length,
      state: 'waiting'
    }));
    pendingFiles = batch;
    try {
      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        const pending = batch[index];
        pendingFiles = pendingFiles.map((item) =>
          item.key === pending.key ? { ...item, state: 'uploading' } : item
        );
        const form = new FormData();
        form.append('file', file);
        if (sourceType !== 'auto') form.append('source_type', sourceType);
        try {
          await api.POST('/courses/{course_id}/sources', {
            params: { path: { course_id: courseId } },
            body: form as unknown as UploadBody
          });
          await onchanged().catch(() => undefined);
        } catch (caught) {
          // Keep going: one bad file should not drop the rest of the batch.
          uploadError = files.length > 1 ? new Error(`${file.name}: ${errorText(caught)}`) : caught;
        }
        pendingFiles = pendingFiles.filter((item) => item.key !== pending.key);
      }
    } finally {
      // Picking the same file again must fire a change event again.
      if (fileInput) fileInput.value = '';
      uploading = false;
      pendingFiles = [];
    }
  }

  function errorText(caught: unknown): string {
    return caught instanceof Error ? caught.message : 'upload failed';
  }

  function onFilePicked() {
    void uploadFiles(Array.from(fileInput?.files ?? []));
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    dragOver = false;
    void uploadFiles(Array.from(event.dataTransfer?.files ?? []));
  }

  async function requeue(sourceId: string) {
    if (busyId) return;
    busyId = sourceId;
    actionError = null;
    try {
      const { error: err } = await api.POST('/courses/{course_id}/sources/{source_id}/requeue', {
        params: { path: { course_id: courseId, source_id: sourceId } }
      });
      if (err) throw err;
      await onchanged();
    } catch (caught) {
      actionError = caught;
    } finally {
      busyId = null;
    }
  }

  async function reindex(sourceId: string) {
    if (busyId) return;
    menuFor = null;
    if (
      !(await confirmDialog({
        title: 'Re-extract and reindex?',
        message:
          'Extraction and embeddings are rebuilt from the original file. Older chats keep the citation text they already saved.',
        confirmLabel: 'Reindex'
      }))
    )
      return;
    if (busyId) return;
    busyId = sourceId;
    actionError = null;
    try {
      const { error: err } = await api.POST('/courses/{course_id}/sources/{source_id}/reindex', {
        params: { path: { course_id: courseId, source_id: sourceId } }
      });
      if (err) throw err;
      await onchanged();
      toast('Reindexing source with the latest extraction.');
    } catch (caught) {
      actionError = caught;
    } finally {
      busyId = null;
    }
  }

  async function setType(sourceId: string, next: string) {
    if (busyId) return;
    busyId = sourceId;
    actionError = null;
    try {
      const { error: err } = await api.PATCH('/courses/{course_id}/sources/{source_id}', {
        params: { path: { course_id: courseId, source_id: sourceId } },
        body: { source_type: next as SourceType }
      });
      if (err) throw err;
      await onchanged();
    } catch (caught) {
      actionError = caught;
    } finally {
      busyId = null;
    }
  }

  async function removeSource(sourceId: string, filename: string) {
    if (
      !(await confirmDialog({
        title: 'Remove this file?',
        message: `${filename} and everything derived from it (search index, citations) are deleted from this computer.`,
        confirmLabel: 'Remove',
        danger: true
      }))
    )
      return;
    if (busyId) return;
    busyId = sourceId;
    actionError = null;
    try {
      const { error: err } = await api.DELETE('/courses/{course_id}/sources/{source_id}', {
        params: { path: { course_id: courseId, source_id: sourceId } }
      });
      if (err) throw err;
      await onchanged();
      toast('File removed.');
    } catch (caught) {
      actionError = caught;
    } finally {
      busyId = null;
    }
  }

  $effect(() => {
    if (!menuFor) return;
    const close = (event: PointerEvent) => {
      if (!(event.target as Element | null)?.closest?.('[data-source-menu]')) menuFor = null;
    };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  });
</script>

<div class="flex flex-col gap-6">
  <Card title="Add material" description="Upload a syllabus, slides, notes, problem sets — anything the tutor should answer from.">
    <div class="flex flex-col gap-4 sm:flex-row sm:items-stretch">
      <div class="sm:w-52">
        <Select label="Source type" options={sourceTypeOptions} bind:value={sourceType} />
      </div>
      <div
        role="button"
        tabindex="0"
        aria-label="Upload a file"
        class={`flex flex-1 cursor-pointer items-center gap-4 rounded-xl border-2 border-dashed px-5 py-5 transition-colors ${
          dragOver ? 'border-accent bg-accent-soft' : 'border-line-strong hover:border-accent-line hover:bg-surface-2/60'
        }`}
        ondragover={(e) => {
          e.preventDefault();
          dragOver = true;
        }}
        ondragleave={() => (dragOver = false)}
        ondrop={onDrop}
        onclick={() => !uploading && fileInput?.click()}
        onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (!uploading) fileInput?.click(); } }}
      >
        <span class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-surface-2 text-muted ring-1 ring-line">
          {#if uploading}<Spinner class="h-5 w-5" />{:else}<Icon name="upload-cloud" class="h-5 w-5" />{/if}
        </span>
        <div class="min-w-0">
          <p class="text-sm font-medium text-fg">
            {#if uploading}
              Uploading…
            {:else}
              Drop files here, or <span class="text-accent-text underline underline-offset-2">browse</span>
            {/if}
          </p>
          <p class="mt-0.5 text-xs text-subtle">PDF, Word, PowerPoint, Excel, Markdown, or text · indexed automatically</p>
        </div>
        <input bind:this={fileInput} type="file" multiple accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.markdown,.csv,.json,.xml,.yaml,.yml" class="hidden" onchange={onFilePicked} />
      </div>
    </div>
    {#if uploadError}<div class="mt-4"><ErrorBanner error={uploadError} /></div>{/if}
  </Card>

  {#if actionError}<ErrorBanner error={actionError} />{/if}

  {#if sources.length === 0 && pendingFiles.length === 0}
    <EmptyState icon="file-text" title="No sources yet" message="Upload course material above and the tutor will start answering from it." />
  {:else}
    <section class="overflow-visible rounded-2xl border border-line bg-surface shadow-card">
      <div class="flex items-center justify-between border-b border-line px-5 py-3.5 sm:px-6">
        <h2 class="text-[15px] font-semibold text-fg">Materials</h2>
        <span class="text-[13px] text-subtle">{plural(sources.length + pendingFiles.length, 'file')}</span>
      </div>
      <ul class="divide-y divide-line">
        {#each pendingFiles as item (item.key)}
          <li class="flex items-center gap-4 px-5 py-3.5 sm:px-6">
            <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-muted ring-1 ring-line">
              <Spinner class="h-[18px] w-[18px]" />
            </span>
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm font-medium text-fg">{item.filename}</p>
              <p class="mt-0.5 text-xs text-subtle">
                {item.state === 'uploading' ? `Uploading ${item.position}/${item.total}` : 'Waiting'} · {item.filename}
              </p>
            </div>
            <Badge tone="info"><Spinner class="h-3 w-3" /> {item.state === 'uploading' ? 'Uploading' : 'Waiting'}</Badge>
          </li>
        {/each}
        {#each sources as source (source.source_id)}
          {@const pending = source.status === 'uploaded' || source.status === 'scanned'}
          <li class="flex items-center gap-4 px-5 py-3.5 sm:px-6">
            <span
              class={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ring-1 ${
                source.status === 'failed' ? 'bg-danger-soft text-danger-text ring-danger/20' : 'bg-surface-2 text-muted ring-line'
              }`}
            >
              <Icon name="file-text" class="h-[18px] w-[18px]" />
            </span>
            <div class="min-w-0 flex-1">
              <a href={`/courses/${courseId}/sources/${source.source_id}`} class="truncate text-sm font-medium text-accent-text hover:underline">{source.filename}</a>
              <p class="mt-0.5 text-xs text-subtle">{coverage(source)}</p>
              <label class="mt-1.5 flex items-center gap-2 text-xs text-subtle">
                <span class="sr-only">Type for {source.filename}</span>
                <select
                  aria-label={`Type for ${source.filename}`}
                  class="h-7 rounded-md border border-line bg-surface px-2 text-xs text-fg"
                  value={source.source_type}
                  disabled={busyId === source.source_id}
                  onchange={(event) => setType(source.source_id, event.currentTarget.value)}
                >
                  {#each storedTypes as kind (kind)}
                    <option value={kind}>{humanize(kind)}</option>
                  {/each}
                </select>
              </label>
              {#if source.error_message}
                <p class="mt-1 text-xs text-danger-text">{source.error_message}</p>
              {/if}
            </div>
            <div class="flex shrink-0 items-center gap-2">
              {#if source.status === 'failed'}
                <Button variant="secondary" size="sm" loading={busyId === source.source_id} onclick={() => requeue(source.source_id)}>
                  <Icon name="refresh" class="h-3.5 w-3.5" /> Retry
                </Button>
              {/if}
              {#if source.status === 'indexed' && source.index_stale}
                <Button variant="secondary" size="sm" loading={busyId === source.source_id} onclick={() => reindex(source.source_id)}>
                  Reindex
                </Button>
              {/if}
              {#if source.status === 'indexed' && !source.index_stale}
                <div class="relative" data-source-menu>
                  <button
                    type="button"
                    aria-label={`Actions for ${source.filename}`}
                    aria-expanded={menuFor === source.source_id}
                    onclick={() => (menuFor = menuFor === source.source_id ? null : source.source_id)}
                    class="rounded-lg p-1.5 text-subtle transition-colors hover:bg-surface-2 hover:text-fg disabled:opacity-50"
                    disabled={busyId === source.source_id}
                  >
                    <Icon name="ellipsis" class="h-4 w-4" />
                  </button>
                  {#if menuFor === source.source_id}
                    <div
                      class="absolute right-0 top-9 z-30 w-56 animate-rise overflow-hidden rounded-xl border border-line bg-surface py-1 shadow-lift"
                      role="menu"
                    >
                      <button
                        type="button"
                        role="menuitem"
                        class="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-fg-soft hover:bg-surface-2"
                        onclick={() => reindex(source.source_id)}
                      >
                        Re-extract and reindex…
                      </button>
                    </div>
                  {/if}
                </div>
              {/if}
              {#if pending}
                <Badge tone="info"><Spinner class="h-3 w-3" /> {indexingLabel(source.ingestion_stage)}</Badge>
              {:else if source.status === 'indexed'}
                <Badge tone="success" dot>Indexed</Badge>
              {:else if source.status === 'failed'}
                <Badge tone="danger" dot>Failed</Badge>
              {:else}
                <Badge>{humanize(source.status)}</Badge>
              {/if}
              <button
                type="button"
                onclick={() => removeSource(source.source_id, source.filename)}
                disabled={busyId === source.source_id}
                class="rounded-lg p-1.5 text-subtle transition-colors hover:bg-danger-soft hover:text-danger-text disabled:opacity-50"
                aria-label={`Remove ${source.filename}`}
              >
                <Icon name="trash" class="h-4 w-4" />
              </button>
            </div>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
</div>
