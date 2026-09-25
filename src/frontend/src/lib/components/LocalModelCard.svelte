<script lang="ts">
  import { isTauri } from '@tauri-apps/api/core';
  import { onDestroy, onMount } from 'svelte';
  import { api } from '$lib/api/client';
  import type { paths } from '$lib/api/schema';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import TextInput from '$lib/components/TextInput.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { formatBytes } from '$lib/utils/format';

  type RuntimeView = paths['/runtime']['get']['responses'][200]['content']['application/json'];
  type ModelView = RuntimeView['models'][number];
  type LinkView =
    paths['/runtime/models/inspect']['post']['responses'][200]['content']['application/json'];

  interface Props {
    /** Called after the running model changes, so the page can refresh
        which model answers are routed to. */
    onchange?: () => void;
  }

  let { onchange }: Props = $props();

  let view = $state<RuntimeView | null>(null);
  let error = $state<unknown>(null);
  let busy = $state<string | null>(null);
  let timer: ReturnType<typeof setInterval> | null = null;

  let downloading = $derived(
    view?.models.some((m) => m.download?.status === 'downloading' || m.download?.status === 'verifying') ?? false
  );

  onMount(() => {
    void refresh();
  });

  onDestroy(() => {
    if (timer) clearInterval(timer);
  });

  $effect(() => {
    // Poll only while a download is in flight.
    if (downloading && !timer) {
      timer = setInterval(() => void refresh(), 1000);
    } else if (!downloading && timer) {
      clearInterval(timer);
      timer = null;
    }
  });

  async function refresh() {
    try {
      const { data, error: err } = await api.GET('/runtime');
      if (err || !data) throw err ?? new Error('empty response');
      const finished = view?.models.filter(
        (m) => m.download?.status === 'downloading' || m.download?.status === 'verifying'
      );
      view = data;
      for (const before of finished ?? []) {
        const after = data.models.find((m) => m.id === before.id);
        if (after?.download?.status === 'done') toast(`${after.label} downloaded.`);
        if (after?.download?.status === 'failed') toast(`${after.label} failed to download.`, 'error');
      }
    } catch (caught) {
      error = caught;
    }
  }

  function installed(model: ModelView): boolean {
    return model.location === 'app' || model.location === 'external' || model.location === 'external-unverified';
  }

  async function download(model: ModelView) {
    if (!model.fits) {
      const ok = await confirmDialog({
        title: `${model.label} may not fit`,
        message: `It is meant for computers with at least ${model.min_ram_gb} GB of memory; this one has ${view?.hardware.ram_gb} GB. It may run slowly or fail to start.`,
        confirmLabel: 'Download anyway'
      });
      if (!ok) return;
    }
    busy = model.id;
    try {
      const { data, error: err } = await api.POST('/runtime/models/{model_id}/download', {
        params: { path: { model_id: model.id } }
      });
      if (err || !data) throw err ?? new Error('empty response');
      view = data;
    } catch (caught) {
      error = caught;
    } finally {
      busy = null;
    }
  }

  async function cancel(model: ModelView) {
    const { data } = await api.DELETE('/runtime/models/{model_id}/download', {
      params: { path: { model_id: model.id } }
    });
    if (data) view = data;
  }

  async function start(model: ModelView) {
    busy = model.id;
    error = null;
    try {
      const { error: err } = await api.POST('/runtime/start', { body: { model_id: model.id } });
      if (err) throw err;
      // Point the answers model at the local runtime running this model.
      const { error: saveErr } = await api.PUT('/settings/providers/{task_class}', {
        params: { path: { task_class: 'interactive' } },
        body: { connection: 'local', model: model.id }
      });
      if (saveErr) throw saveErr;
      toast(`${model.label} is running on this computer.`);
      await refresh();
      onchange?.();
    } catch (caught) {
      error = caught;
    } finally {
      busy = null;
    }
  }

  async function stop() {
    busy = 'stop';
    try {
      await api.POST('/runtime/stop');
      await refresh();
      onchange?.();
    } finally {
      busy = null;
    }
  }

  async function remove(model: ModelView) {
    const inPlace = model.added_by_user && model.location !== 'app';
    if (!(await confirmDialog({
      title: inPlace ? `Remove ${model.label} from the list?` : `Delete ${model.label}?`,
      message: inPlace
        ? 'The file itself stays where it is on your computer.'
        : model.added_by_user
          ? `This frees ${formatBytes(model.size_bytes)} and removes it from your list.`
          : `This frees ${formatBytes(model.size_bytes)}. You can download it again any time.`,
      confirmLabel: inPlace ? 'Remove' : 'Delete',
      danger: true
    }))) return;
    const { data } = await api.DELETE('/runtime/models/{model_id}', {
      params: { path: { model_id: model.id } }
    });
    if (data) view = data;
    onchange?.();
  }

  function percent(model: ModelView): number {
    const d = model.download;
    return d && d.total_bytes > 0 ? Math.floor((100 * d.done_bytes) / d.total_bytes) : 0;
  }

  const tierLabel = { starter: 'Starter', standard: 'Standard', large: 'Large' } as const;

  // Adding a model: a Hugging Face link, or a .gguf file on this computer.
  let addMode = $state<'link' | 'file' | null>(null);
  let link = $state('');
  let found = $state<LinkView | null>(null);
  let pickedFile = $state('');
  let filePath = $state('');
  let adding = $state(false);
  let addError = $state<unknown>(null);

  function resetAdd(mode: 'link' | 'file' | null) {
    addMode = mode;
    link = '';
    found = null;
    pickedFile = '';
    filePath = '';
    addError = null;
  }

  async function lookUp(event: SubmitEvent) {
    event.preventDefault();
    adding = true;
    addError = null;
    found = null;
    try {
      const { data, error: err } = await api.POST('/runtime/models/inspect', {
        body: { url: link.trim() }
      });
      if (err || !data) throw err ?? new Error('empty response');
      found = data;
      pickedFile =
        data.selected ?? data.files.find((f) => /q4_k_m/i.test(f.file))?.file ?? data.files[0].file;
    } catch (caught) {
      addError = caught;
    } finally {
      adding = false;
    }
  }

  async function addModel(body: { url?: string; file?: string; path?: string }) {
    adding = true;
    addError = null;
    try {
      const { data, error: err } = await api.POST('/runtime/models', { body });
      if (err || !data) throw err ?? new Error('empty response');
      view = data;
      toast(body.path ? 'Model added.' : 'Model added; downloading now.');
      resetAdd(null);
      onchange?.();
    } catch (caught) {
      addError = caught;
    } finally {
      adding = false;
    }
  }

  async function chooseFile() {
    if (!isTauri()) return;
    const { open } = await import('@tauri-apps/plugin-dialog');
    const chosen = await open({
      multiple: false,
      directory: false,
      title: 'Choose a GGUF model file',
      filters: [{ name: 'GGUF model', extensions: ['gguf'] }]
    });
    if (typeof chosen === 'string') filePath = chosen;
  }
</script>

<Card
  title="Local model"
  description="Runs entirely on this computer — free, private, and works offline once downloaded."
>
  {#if error}<div class="mb-4"><ErrorBanner {error} /></div>{/if}
  {#if !view}
    <Skeleton class="h-40 w-full rounded-xl" />
  {:else}
    {@const running = view.server.state === 'running' ? view.models.find((m) => m.id === view?.server.model_id) : undefined}
    <div class="mb-4 flex flex-wrap items-center gap-2 text-sm">
      <Badge icon="cpu">{view.hardware.ram_gb} GB memory · {view.hardware.logical_cores} cores</Badge>
      {#if running}
        <Badge tone="success" dot>
          Running {running.label}{view.server.backend?.endsWith('-cpu') ? ' (CPU)' : ' (GPU)'}
        </Badge>
        <Button variant="ghost" size="sm" loading={busy === 'stop'} onclick={stop}>Stop</Button>
      {:else if view.server.state === 'failed'}
        <Badge tone="danger" dot>Stopped: {view.server.error}</Badge>
      {:else}
        <Badge dot>Not running</Badge>
      {/if}
    </div>

    <ul class="divide-y divide-line rounded-xl border border-line">
      {#each view.models as model (model.id)}
        {@const dl = model.download}
        {@const active = dl && (dl.status === 'downloading' || dl.status === 'verifying')}
        <li class="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center">
          <div class="min-w-0 flex-1">
            <p class="flex flex-wrap items-center gap-2 text-sm font-medium text-fg">
              {model.label}
              <Badge>{tierLabel[model.tier]}</Badge>
              {#if model.recommended}<Badge tone="accent">Recommended</Badge>{/if}
              {#if model.added_by_user}<Badge tone="info">Added</Badge>{/if}
              {#if !model.fits}<Badge tone="warning">Needs {model.min_ram_gb} GB</Badge>{/if}
            </p>
            <p class="mt-0.5 text-xs text-subtle">
              {formatBytes(model.size_bytes)} · {model.license} · {model.notes}
              {#if !model.added_by_user && (model.location === 'external' || model.location === 'external-unverified')}
                · found in another app's folder
              {/if}
            </p>
            {#if active && dl}
              <div class="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-3">
                <div class="h-full bg-accent transition-all" style={`width: ${percent(model)}%`}></div>
              </div>
              <p class="mt-1 text-xs text-subtle">
                {dl.status === 'verifying' ? 'Verifying…' : `${percent(model)}% of ${formatBytes(dl.total_bytes)}`}
              </p>
            {:else if dl?.status === 'failed'}
              <p class="mt-1 text-xs text-danger-text">Download failed: {dl.error}</p>
            {/if}
          </div>
          <div class="flex shrink-0 gap-2">
            {#if active}
              <Button variant="ghost" size="sm" onclick={() => cancel(model)}>Cancel</Button>
            {:else if installed(model)}
              {#if view.server.model_id !== model.id || view.server.state !== 'running'}
                <Button size="sm" loading={busy === model.id} onclick={() => start(model)}>
                  <Icon name="sparkles" class="h-3.5 w-3.5" /> Use
                </Button>
              {/if}
              {#if model.location === 'app' || model.added_by_user}
                <Button variant="ghost" size="sm" onclick={() => remove(model)} aria-label={`Delete ${model.label}`}>
                  <Icon name="trash" class="h-4 w-4" />
                </Button>
              {/if}
            {:else}
              <Button variant="secondary" size="sm" loading={busy === model.id} onclick={() => download(model)}>
                <Icon name="download" class="h-3.5 w-3.5" /> Download
              </Button>
              {#if model.added_by_user}
                <Button variant="ghost" size="sm" onclick={() => remove(model)} aria-label={`Remove ${model.label}`}>
                  <Icon name="trash" class="h-4 w-4" />
                </Button>
              {/if}
            {/if}
          </div>
        </li>
      {/each}
    </ul>

    <div class="mt-4 rounded-xl border border-dashed border-line-strong p-4">
      {#if addMode === null}
        <div class="flex flex-wrap items-center gap-3">
          <div class="min-w-0 flex-1">
            <p class="text-sm font-medium text-fg">Add a model</p>
            <p class="mt-0.5 text-xs text-subtle">
              Any GGUF model from Hugging Face, or a .gguf file already on this computer.
            </p>
          </div>
          <Button variant="secondary" size="sm" onclick={() => resetAdd('link')}>
            <Icon name="link" class="h-3.5 w-3.5" /> From Hugging Face
          </Button>
          <Button variant="secondary" size="sm" onclick={() => resetAdd('file')}>
            <Icon name="folder-open" class="h-3.5 w-3.5" /> From a file
          </Button>
        </div>
      {:else if addMode === 'link'}
        <form onsubmit={lookUp} class="flex flex-col gap-3">
          <p class="text-sm font-medium text-fg">Add from Hugging Face</p>
          <div class="flex flex-col gap-2 sm:flex-row">
            <div class="flex-1">
              <TextInput
                placeholder="https://huggingface.co/org/model-GGUF"
                bind:value={link}
                aria-label="Hugging Face link"
              />
            </div>
            <Button type="submit" variant="secondary" loading={adding && !found} disabled={!link.trim()}>
              Look up
            </Button>
          </div>
          {#if found}
            {@const current = found}
            <fieldset class="flex flex-col gap-1">
              <legend class="mb-1.5 text-xs text-subtle">
                Files in {current.repo}. Smaller files are faster; Q4_K_M is a good balance.
              </legend>
              {#each current.files as file (file.file)}
                <label
                  class={`flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 text-sm transition-colors ${
                    pickedFile === file.file ? 'border-accent bg-accent-soft' : 'border-line hover:border-line-strong'
                  }`}
                >
                  <input type="radio" bind:group={pickedFile} value={file.file} />
                  <span class="min-w-0 flex-1 truncate text-fg">{file.file}</span>
                  <span class="shrink-0 text-xs text-subtle">{formatBytes(file.size_bytes)}</span>
                </label>
              {/each}
            </fieldset>
            <div class="flex gap-2">
              <Button
                size="sm"
                loading={adding}
                onclick={() => addModel({ url: link.trim(), file: pickedFile })}
                disabled={!pickedFile}
              >
                <Icon name="download" class="h-3.5 w-3.5" /> Add and download
              </Button>
              <Button variant="ghost" size="sm" onclick={() => resetAdd(null)}>Cancel</Button>
            </div>
          {:else}
            <div><Button variant="ghost" size="sm" onclick={() => resetAdd(null)}>Cancel</Button></div>
          {/if}
        </form>
      {:else}
        <div class="flex flex-col gap-3">
          <p class="text-sm font-medium text-fg">Add a file from this computer</p>
          {#if isTauri()}
            <div class="flex flex-wrap items-center gap-2">
              <Button variant="secondary" size="sm" onclick={chooseFile}>
                <Icon name="folder-open" class="h-3.5 w-3.5" /> Choose a .gguf file…
              </Button>
              {#if filePath}
                <code class="min-w-0 truncate rounded bg-surface-2 px-2 py-1 text-xs text-muted">{filePath}</code>
              {/if}
            </div>
          {:else}
            <TextInput placeholder="Full path to a .gguf file" bind:value={filePath} aria-label="Path to a .gguf file" />
          {/if}
          <p class="text-xs text-subtle">
            The file stays where it is; Stacks checks it once so it knows if it changes.
          </p>
          <div class="flex gap-2">
            <Button size="sm" loading={adding} onclick={() => addModel({ path: filePath })} disabled={!filePath}>
              Add model
            </Button>
            <Button variant="ghost" size="sm" onclick={() => resetAdd(null)}>Cancel</Button>
          </div>
        </div>
      {/if}
      {#if addError}<div class="mt-3"><ErrorBanner error={addError} /></div>{/if}
      <p class="mt-3 text-[11px] leading-relaxed text-subtle">
        Stacks runs GGUF models with its bundled llama.cpp. A model with a newer architecture may
        not start yet; if so, the message says why.
      </p>
    </div>
  {/if}
</Card>
