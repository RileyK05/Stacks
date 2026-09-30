<script lang="ts">
  import { open as openDialog } from '@tauri-apps/plugin-dialog';
  import { isTauri } from '@tauri-apps/api/core';
  import Icon from '$lib/components/Icon.svelte';
  import Popover from '$lib/components/Popover.svelte';
  import { OFFICE_APPS, OFFICE_EXTENSIONS, openInOffice, type OfficeApp } from '$lib/stores/office';
  import { toast } from '$lib/stores/toast.svelte';
  import { showCompanion } from '$lib/utils/companion';

  interface Props {
    courseId: string;
  }

  let { courseId }: Props = $props();
  let menuOpen = $state(false);
  let working = $state(false);

  async function launch(request: { app?: OfficeApp; path?: string }) {
    if (working) return;
    working = true;
    try {
      const message = await openInOffice({ ...request, course_id: courseId });
      // Opening an Office document should bring the course companion along,
      // with the same course selected. The Office pane remains available
      // from Office's Home tab as before.
      await showCompanion(courseId);
      toast(`${message} Stacks companion opened on this course.`);
      menuOpen = false;
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not open Office.', 'error');
    } finally {
      working = false;
    }
  }

  async function openFile() {
    try {
      const path = await openDialog({
        multiple: false,
        filters: [{ name: 'Word, Excel or PowerPoint', extensions: OFFICE_EXTENSIONS }]
      });
      if (typeof path === 'string') await launch({ path });
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not open the file picker.', 'error');
    }
  }
</script>

<Popover bind:open={menuOpen} label="Open in Office" align="end" width="w-80">
  {#snippet trigger(props)}
    <button
      type="button"
      {...props}
      title="Work in Word, Excel or PowerPoint with Stacks beside your document"
      class="inline-flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm font-medium text-muted hover:bg-surface-2 hover:text-fg"
    >
      <Icon name="file-pen" class="h-4 w-4" /> Open in Office
    </button>
  {/snippet}
  {#snippet children()}
    <div class="flex flex-col gap-1 p-2">
      {#if isTauri()}
        <button type="button" disabled={working} onclick={openFile} class="flex items-center gap-3 rounded-lg px-3 py-2 text-left text-sm text-fg hover:bg-surface-2 disabled:opacity-50">
          <Icon name="folder-open" class="h-4 w-4 text-subtle" /> Open a file…
        </button>
      {/if}
      {#each OFFICE_APPS as app (app.id)}
        <button type="button" disabled={working} onclick={() => launch({ app: app.id })} class="flex items-center gap-3 rounded-lg px-3 py-2 text-left text-sm text-fg hover:bg-surface-2 disabled:opacity-50">
          <Icon name={app.icon} class="h-4 w-4 text-subtle" /> {app.newLabel}
        </button>
      {/each}
      <p class="border-t border-line px-3 pt-2 text-xs text-subtle">
        The Stacks companion opens on this course. In Office, click <span class="font-medium text-muted">Stacks</span> on the Home tab to open its document pane.
        The first time, Windows asks you to trust Stacks' local certificate — choose Yes.
      </p>
    </div>
  {/snippet}
</Popover>
