<script lang="ts">
  import { ApiError } from '$lib/api/errors';
  import Icon from './Icon.svelte';

  interface Props {
    error: unknown;
  }

  let { error }: Props = $props();

  function describe(value: unknown): string {
    if (value instanceof Error) return value.message || 'something went wrong';
    if (typeof value === 'string' && value.trim()) return value;
    if (typeof value === 'object' && value !== null) {
      const record = value as Record<string, unknown>;
      for (const key of ['detail', 'message']) {
        if (typeof record[key] === 'string' && record[key]) return record[key] as string;
      }
    }
    return 'something went wrong';
  }

  let apiError = $derived(error instanceof ApiError ? error : null);
  let message = $derived(describe(error));
  // Provider trouble (a rejected key, a rate limit, a bad model id) is fixed in Settings.
  let settingsHint = $derived(
    apiError !== null &&
      (apiError.kind === 'unavailable' ||
        apiError.kind === 'budget' ||
        apiError.kind === 'unauthorized' ||
        (apiError.kind === 'unknown' && [400, 429, 502, 504].includes(apiError.status)))
  );
  let tone = $derived<'refusal' | 'busy' | 'error'>(
    apiError?.kind === 'not_found' ? 'refusal'
      : apiError?.kind === 'unavailable' || apiError?.kind === 'network' ? 'busy'
      : 'error'
  );
  let styles = $derived(
    tone === 'refusal'
      ? 'bg-warning-soft text-warning-text border-warning/30'
      : tone === 'busy'
        ? 'bg-info-soft text-info-text border-info/25'
        : 'bg-danger-soft text-danger-text border-danger/25'
  );
  let icon = $derived(
    tone === 'refusal' ? ('info' as const) : tone === 'busy' ? ('refresh' as const) : ('alert-circle' as const)
  );
</script>

<div class={`rounded-xl border px-4 py-3 text-sm ${styles}`} role="alert">
  <div class="flex items-start gap-3">
    <Icon name={icon} class="mt-0.5 h-4 w-4 shrink-0" />
    <div class="min-w-0 flex-1">
      <p class="whitespace-pre-line font-medium [overflow-wrap:anywhere]">{message}</p>
      {#if tone === 'refusal'}
        <p class="mt-1 opacity-85">
          It may have been deleted or moved. Go back to My courses and open it again.
        </p>
      {/if}
      {#if apiError?.kind === 'network'}
        <p class="mt-1 opacity-85">
          Stacks lost contact with its background service. If this keeps happening, quit and reopen Stacks.
        </p>
      {/if}
      {#if settingsHint}
        <p class="mt-1 opacity-85">
          Check your model and connection in
          <a href="/settings" class="font-medium underline underline-offset-2">Settings</a>.
        </p>
      {/if}
    </div>
  </div>
</div>
