<script lang="ts">
  import { onMount } from 'svelte';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import {
    OFFICE_APPS,
    connectOffice,
    disconnectOffice,
    officeStatus,
    openInOffice,
    type OfficeStatus
  } from '$lib/stores/office';
  import { toast } from '$lib/stores/toast.svelte';

  let status = $state<OfficeStatus | null>(null);
  let working = $state(false);
  let error = $state('');

  onMount(refresh);

  async function refresh() {
    try {
      status = await officeStatus();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  async function run(action: () => Promise<OfficeStatus | void>) {
    working = true;
    error = '';
    try {
      const next = await action();
      if (next) status = next;
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      working = false;
    }
  }

  const connect = () =>
    run(async () => {
      const next = await connectOffice();
      toast('Office is connected. Open Word, Excel or PowerPoint and click Stacks on the Home tab.');
      return next;
    });

  async function disconnect() {
    const ok = await confirmDialog({
      title: 'Disconnect Office?',
      message:
        'The Stacks button disappears from Word, Excel and PowerPoint after they restart, and Stacks removes its local certificate (Windows asks you to confirm). Your documents are not touched.',
      confirmLabel: 'Disconnect'
    });
    if (ok) await run(disconnectOffice);
  }

  const launch = (app: (typeof OFFICE_APPS)[number]['id']) =>
    run(async () => {
      toast(await openInOffice({ app }));
      return officeStatus();
    });

  let installed = $derived(OFFICE_APPS.filter((app) => status?.apps.includes(app.id)));
</script>

<Card
  title="Microsoft Office"
  description="Use Stacks inside Word, Excel and PowerPoint: a Stacks pane beside your document answers from your course, with sources, and can insert the answer. Office keeps full control of your files."
>
  {#if !status}
    <p class="text-sm text-muted">{error || 'Checking…'}</p>
  {:else if !status.supported}
    <p class="text-sm text-muted">The Office add-in is set up automatically on Windows with Microsoft 365 or Office 2016 or later.</p>
  {:else}
    <div class="flex flex-col gap-4">
      <div class="flex flex-wrap items-center gap-3">
        {#if status.ready}
          <span class="inline-flex items-center gap-1.5 text-sm font-medium text-success-text">
            <Icon name="check" class="h-4 w-4" /> Connected
          </span>
        {:else if status.connected}
          <span class="inline-flex items-center gap-1.5 text-sm font-medium text-warning-text">
            <Icon name="alert-triangle" class="h-4 w-4" /> Needs attention
          </span>
        {:else}
          <span class="text-sm text-muted">Not connected</span>
        {/if}
        <div class="ml-auto flex flex-wrap gap-2">
          {#if !status.ready}
            <Button size="sm" onclick={connect} loading={working}>
              <Icon name="plug" class="h-4 w-4" />
              {status.connected ? 'Repair' : 'Connect Office'}
            </Button>
          {/if}
          {#if status.connected}
            <Button variant="ghost" size="sm" onclick={disconnect} disabled={working}>Disconnect</Button>
          {/if}
        </div>
      </div>

      {#if status.problems.length}
        <ul class="list-disc pl-5 text-sm text-warning-text">
          {#each status.problems as problem (problem)}<li>{problem}</li>{/each}
        </ul>
      {/if}

      {#if !status.connected}
        <p class="text-xs text-subtle">
          Connecting adds a Stacks button to the Home tab in Word, Excel and PowerPoint. Windows will ask once
          whether to trust Stacks' local certificate — choose Yes; it only works for this computer. No admin
          rights needed.
        </p>
      {/if}

      {#if installed.length}
        <div class="flex flex-wrap gap-2">
          {#each installed as app (app.id)}
            <Button variant="secondary" size="sm" onclick={() => launch(app.id)} disabled={working}>
              <Icon name={app.icon} class="h-4 w-4" /> Open {app.name}
            </Button>
          {/each}
        </div>
      {:else}
        <p class="text-xs text-subtle">Word, Excel and PowerPoint don't seem to be installed on this computer.</p>
      {/if}

      {#if status.connected}
        <p class="text-xs text-subtle">Keep Stacks open while you use it in Office — the pane talks to this app.</p>
      {/if}

      {#if error}
        <p class="text-sm text-danger-text">{error}</p>
      {/if}
    </div>
  {/if}
</Card>
