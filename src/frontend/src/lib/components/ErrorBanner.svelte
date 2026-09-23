<script lang="ts">
  import { ApiError } from '$lib/api/errors';

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
      ? 'bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/50 dark:text-amber-200 dark:ring-amber-900'
      : tone === 'busy'
        ? 'bg-sky-50 text-sky-900 ring-sky-200 dark:bg-sky-950/50 dark:text-sky-200 dark:ring-sky-900'
        : 'bg-red-50 text-red-800 ring-red-200 dark:bg-red-950/50 dark:text-red-200 dark:ring-red-900'
  );
  let icon = $derived(
    tone === 'refusal' ? '›' : tone === 'busy' ? '↻' : '!'
  );
</script>

<div class={`rounded-lg p-4 text-sm ring-1 ${styles}`}>
  <div class="flex items-start gap-3">
    <span
      class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white/70 text-xs font-bold dark:bg-slate-900/70"
      aria-hidden="true">{icon}</span
    >
    <div class="min-w-0">
      <p class="font-medium">{message}</p>
      {#if tone === 'refusal'}
        <p class="mt-1 opacity-80">
          The tutor only answers from your course materials — try rewording
          the question, or upload a source that covers it.
        </p>
      {/if}
      {#if apiError?.kind === 'email_unverified'}
        <p class="mt-1 opacity-80">
          Verify your email to continue — request a verification link on the
          <a href="/account" class="font-medium underline">account page</a>.
        </p>
      {/if}
    </div>
  </div>
</div>