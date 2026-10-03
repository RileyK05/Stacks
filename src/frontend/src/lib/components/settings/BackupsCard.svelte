<script lang="ts">
  import { isTauri } from '@tauri-apps/api/core';
  import { onMount } from 'svelte';
  import { activateBackup } from '$lib/api/backend';
  import { api } from '$lib/api/client';
  import type { components } from '$lib/api/schema';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { formatBytes } from '$lib/utils/format';

  type Backup = components['schemas']['BackupInfo'];
  let overview = $state<components['schemas']['BackupOverview'] | null>(null);
  let preferences = $state<components['schemas']['BackupPreferences'] | null>(null);
  let archives = $state<Backup[]>([]);
  let busy = $state(false);
  let error = $state<unknown>(null);
  let recovered = $state<components['schemas']['RecoverView'] | null>(null);
  let activating = $state(false);
  let notice = $state('');
  let activeBackupId = $state('');
  const isTauriApp = isTauri();

  onMount(() => { void load(); });

  async function load() {
    try {
      const [status, list] = await Promise.all([api.GET('/settings/backups'), api.GET('/settings/backups/archives')]);
      if (status.error || !status.data) throw status.error ?? new Error('Could not load backup settings.');
      if (list.error || !list.data) throw list.error ?? new Error('Could not list backups.');
      overview = status.data;
      preferences = structuredClone(status.data.settings);
      archives = list.data.backups;
      error = null;
    } catch (caught) { error = caught; }
  }

  async function save() {
    if (!preferences || busy) return;
    busy = true;
    try {
      const result = await api.PUT('/settings/backups', { body: preferences });
      if (result.error || !result.data) throw result.error ?? new Error('Could not save backup settings.');
      overview = result.data;
      toast(preferences.enabled ? 'Automatic backups enabled.' : 'Automatic backups off. Existing backups are kept.');
      error = null;
    } catch (caught) { error = caught; }
    finally { busy = false; }
  }

  async function create() {
    if (busy || !preferences) return;
    busy = true;
    try {
      const updated = await api.PUT('/settings/backups', { body: preferences });
      if (updated.error) throw updated.error;
      const result = await api.POST('/settings/backups/create');
      if (result.error || !result.data) throw result.error ?? new Error('Backup failed.');
      await load();
      toast(`Backup saved (${formatBytes(result.data.size_bytes)}).`);
    } catch (caught) { error = caught; }
    finally { busy = false; }
  }

  async function recover(backupId: string) {
    if (busy) return;
    busy = true;
    try {
      const result = await api.POST('/settings/backups/recover', { body: { backup_id: backupId } });
      if (result.error || !result.data) throw result.error ?? new Error('Could not recover this backup.');
      recovered = result.data;
      activeBackupId = backupId;
      error = null;
    } catch (caught) { error = caught; }
    finally { busy = false; }
  }

  async function activate(backupId: string) {
    if (activating) return;
    activating = true;
    notice = '';
    try {
      const outcome = await activateBackup(backupId);
      notice = outcome.message;
      if (outcome.ok) {
        toast('Backup activated. Reloading…');
        // The backend restarted against the recovered library; reload so
        // every view fetches data from the new library.
        setTimeout(() => window.location.reload(), 800);
      }
    } catch (caught) { error = caught; }
    finally { activating = false; }
  }

  async function reveal(path: string) {
    try {
      const result = await api.POST('/settings/reveal', { body: { path } });
      if (result.error) throw result.error;
    } catch (caught) { error = caught; }
  }
</script>

<Card title="Local backups" description="Keep copies of saved course work on this computer. Draft recovery stays on even when automatic backups are off.">
  {#if error}<ErrorBanner {error} />{/if}
  {#if preferences && overview}
    <form onsubmit={(event) => { event.preventDefault(); void save(); }} class="flex flex-col gap-4">
      <label class="flex items-center gap-2 text-sm text-fg"><input type="checkbox" bind:checked={preferences.enabled} disabled={busy} /> Automatic backups while Stacks is open</label>
      <div class="grid gap-4 sm:grid-cols-2">
        <label class="flex flex-col gap-1 text-sm text-muted">What to keep
          <select bind:value={preferences.tier} disabled={busy} class="rounded-lg border border-line bg-surface px-3 py-2 text-fg">
            <option value="full">Full — all saved academic data</option>
            <option value="partial">Partial — sources, materials and memory</option>
            <option value="heavy">Heavy — sources and materials</option>
          </select>
        </label>
        <label class="flex flex-col gap-1 text-sm text-muted">Compression
          <select bind:value={preferences.compression} disabled={busy} class="rounded-lg border border-line bg-surface px-3 py-2 text-fg">
            <option value="fast">Fast — less compression</option>
            <option value="balanced">Balanced</option>
            <option value="maximum">Maximum — smaller files, slower</option>
          </select>
        </label>
        <label class="flex flex-col gap-1 text-sm text-muted">Hours between backups
          <input type="number" min="1" max="720" required bind:value={preferences.interval_hours} disabled={busy} class="rounded-lg border border-line bg-surface px-3 py-2 text-fg" />
        </label>
        <label class="flex flex-col gap-1 text-sm text-muted">Number of backups to keep
          <input type="number" min="1" max="100" required bind:value={preferences.keep_count} disabled={busy} class="rounded-lg border border-line bg-surface px-3 py-2 text-fg" />
        </label>
      </div>
      <p class="text-xs leading-relaxed text-subtle">
        {#if preferences.tier === 'full'}Full includes saved chats, materials, versions, memory and source files.
        {:else if preferences.tier === 'partial'}Partial leaves out chats, companion replies and rebuildable vectors. Sources, materials and memory stay intact.
        {:else}Heavy also leaves out learning memory, practice results and teaching preferences. Sources and materials stay intact.{/if}
        Compression preserves retained content exactly. Downloads, credentials and unfinished browser drafts are separate.
        Changing these settings affects future backups. Older copies retain their original contents until rotated out.
      </p>
      <div class="flex flex-wrap gap-2">
        <Button type="submit" variant="secondary" disabled={busy}>Save settings</Button>
        <Button onclick={create} disabled={busy}>{busy ? 'Working…' : 'Back up now'}</Button>
        {#if archives.length}<Button variant="ghost" onclick={() => overview && reveal(overview.archive_dir)} disabled={busy}>Open backup folder</Button>{/if}
      </div>
    </form>
    <p class="mt-4 text-xs text-muted">Last successful backup: {overview.status.last_success_at ? new Date(overview.status.last_success_at).toLocaleString() : 'None yet'}.</p>
    {#if overview.status.last_error}<p class="mt-2 text-sm text-danger-text">Last backup failed: {overview.status.last_error}</p>{/if}
    {#if recovered}
      <div class="mt-4 rounded-lg border border-line p-3 text-sm text-muted">
        <p>Recovered files are ready in a separate folder. Your current library is still active.</p>
        <p class="mt-2 break-all">{recovered.data_dir}</p>
        <p class="mt-2">{recovered.instructions}</p>
        <div class="mt-3 flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" onclick={() => recovered && reveal(recovered.data_dir)}>Open recovered folder</Button>
          <Button size="sm" disabled={activating} onclick={() => activate(activeBackupId)}>
            {activating ? 'Activating…' : 'Activate this recovered backup'}
          </Button>
        </div>
        {#if !isTauriApp}
          <p class="mt-2 text-xs text-subtle">Activation restarts the desktop app's backend against the recovered library; it is unavailable in a browser.</p>
        {/if}
      </div>
    {/if}
    {#if notice}<p class="mt-3 rounded-lg border border-line p-3 text-sm text-muted" role="status">{notice}</p>{/if}
    <ul class="mt-4 divide-y divide-line">
      {#each archives as backup (backup.id)}
        <li class="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
          <span class="text-muted">{new Date(backup.created_at).toLocaleString()} · {backup.tier} · {formatBytes(backup.size_bytes)}</span>
          <div class="flex gap-2">
            <Button variant="ghost" size="sm" disabled={busy} onclick={() => recover(backup.id)}>Recover to folder</Button>
            {#if isTauriApp}
              <Button variant="ghost" size="sm" disabled={activating} onclick={() => activate(backup.id)}>Activate</Button>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</Card>
