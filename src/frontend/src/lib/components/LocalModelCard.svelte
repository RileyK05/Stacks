<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { api } from '$lib/api/client';
  import type { paths } from '$lib/api/schema';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { formatBytes } from '$lib/utils/format';

  type RuntimeView = paths['/runtime']['get']['responses'][200]['content']['application/json'];
  type ModelView = RuntimeView['models'][number];

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
        body: { preset: 'local', model: model.id, base_url: null }
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
    if (!(await confirmDialog({
      title: `Delete ${model.label}?`,
      message: `This frees ${formatBytes(model.size_bytes)}. You can download it again any time.`,
      confirmLabel: 'Delete',
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
              {#if !model.fits}<Badge tone="warning">Needs {model.min_ram_gb} GB</Badge>{/if}
            </p>
            <p class="mt-0.5 text-xs text-subtle">
              {formatBytes(model.size_bytes)} · {model.license} · {model.notes}
              {#if model.location === 'external' || model.location === 'external-unverified'}
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
              {#if model.location === 'app'}
                <Button variant="ghost" size="sm" onclick={() => remove(model)} aria-label={`Delete ${model.label}`}>
                  <Icon name="trash" class="h-4 w-4" />
                </Button>
              {/if}
            {:else}
              <Button variant="secondary" size="sm" loading={busy === model.id} onclick={() => download(model)}>
                <Icon name="download" class="h-3.5 w-3.5" /> Download
              </Button>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</Card>
