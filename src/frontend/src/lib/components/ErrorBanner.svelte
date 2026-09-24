<script lang="ts">
  import { ApiError } from '$lib/api/errors';
  import Icon from './Icon.svelte';

  interface Props {
    error: unknown;
  }

  let { error }: Props = $props();

  let apiError = $derived(error instanceof ApiError ? error : null);
  let message = $derived(
    error instanceof Error ? error.message : 'something went wrong'
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
    <Icon name={icon} class="mt-0.5 h-4 w-4" />
    <div class="min-w-0">
      <p class="font-medium">{message}</p>
      {#if tone === 'refusal'}
        <p class="mt-1 opacity-85">
          The tutor only answers from your course materials — try rewording
          the question, or upload a source that covers it.
        </p>
      {/if}
      {#if apiError?.kind === 'email_unverified'}
        <p class="mt-1 opacity-85">
          Verify your email to continue — request a verification link on the
          <a href="/account" class="font-medium underline underline-offset-2">account page</a>.
        </p>
      {/if}
    </div>
  </div>
</div>
