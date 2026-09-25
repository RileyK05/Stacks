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
  type SourceType = UploadBody['source_type'];

  interface Props {
    courseId: string;
    sources: SourceView[];
    onchanged: () => Promise<void>;
  }

  let { courseId, sources, onchanged }: Props = $props();

  let sourceType = $state<SourceType>('notes');
  let uploading = $state(false);
  let uploadError = $state<unknown>(null);
  let actionError = $state<unknown>(null);
  let dragOver = $state(false);
  let fileInput = $state<HTMLInputElement | null>(null);

  const sourceTypeOptions = [
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
  ].map((value) => ({ value: value as SourceType, label: humanize(value) }));

  async function uploadFile(file: File) {
    uploading = true;
    uploadError = null;
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('source_type', sourceType);
      const { error: err } = await api.POST('/courses/{course_id}/sources', {
        params: { path: { course_id: courseId } },
        body: form as unknown as UploadBody
      });
      if (err) throw err;
      if (fileInput) fileInput.value = '';
      await onchanged();
    } catch (caught) {
      uploadError = caught;
    } finally {
      uploading = false;
    }
  }

  function onFilePicked() {
    const file = fileInput?.files?.[0];
    if (file) void uploadFile(file);
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    dragOver = false;
    const file = event.dataTransfer?.files?.[0];
    if (file) void uploadFile(file);
  }

  async function requeue(sourceId: string) {
    actionError = null;
    try {
      const { error: err } = await api.POST('/courses/{course_id}/sources/{source_id}/requeue', {
        params: { path: { course_id: courseId, source_id: sourceId } }
      });
      if (err) throw err;
      await onchanged();
    } catch (caught) {
      actionError = caught;
    }
  }

  async function reindex(sourceId: string) {
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
    }
  }
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
        onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && !uploading && fileInput?.click()}
      >
        <span class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-surface-2 text-muted ring-1 ring-line">
          {#if uploading}<Spinner class="h-5 w-5" />{:else}<Icon name="upload-cloud" class="h-5 w-5" />{/if}
        </span>
        <div class="min-w-0">
          <p class="text-sm font-medium text-fg">
            {#if uploading}
              Uploading…
            {:else}
              Drop a file here, or <span class="text-accent-text underline underline-offset-2">browse</span>
            {/if}
          </p>
          <p class="mt-0.5 text-xs text-subtle">PDF, Markdown, or plain text · indexed automatically</p>
        </div>
        <input bind:this={fileInput} type="file" class="hidden" onchange={onFilePicked} />
      </div>
    </div>
    {#if uploadError}<div class="mt-4"><ErrorBanner error={uploadError} /></div>{/if}
  </Card>

  {#if actionError}<ErrorBanner error={actionError} />{/if}

  {#if sources.length === 0}
    <EmptyState icon="file-text" title="No sources yet" message="Upload course material above and the tutor will start answering from it." />
  {:else}
    <section class="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
      <div class="flex items-center justify-between border-b border-line px-5 py-3.5 sm:px-6">
        <h2 class="text-[15px] font-semibold text-fg">Materials</h2>
        <span class="text-[13px] text-subtle">{plural(sources.length, 'file')}</span>
      </div>
      <ul class="divide-y divide-line">
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
              <p class="mt-0.5 text-xs text-subtle">
                {humanize(source.source_type)} · {formatBytes(source.size_bytes ?? 0)}
              </p>
              {#if source.error_message}
                <p class="mt-1 text-xs text-danger-text">{source.error_message}</p>
              {/if}
            </div>
            <div class="flex shrink-0 items-center gap-2">
              {#if source.status === 'failed'}
                <Button variant="secondary" size="sm" onclick={() => requeue(source.source_id)}>
                  <Icon name="refresh" class="h-3.5 w-3.5" /> Retry
                </Button>
              {/if}
              {#if source.status === 'indexed'}
                <button type="button" onclick={() => reindex(source.source_id)} class="text-xs text-muted hover:text-accent-text" title="Rebuild the search index with the latest extractor">Reindex</button>
              {/if}
              {#if pending}
                <Badge tone="info"><Spinner class="h-3 w-3" /> Indexing</Badge>
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
                class="rounded-lg p-1.5 text-subtle transition-colors hover:bg-danger-soft hover:text-danger-text"
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
