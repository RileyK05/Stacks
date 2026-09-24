<script lang="ts">
  import { api } from '$lib/api/client';
  import type { Snippet } from 'svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon, { type IconName } from '$lib/components/Icon.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import TextInput from '$lib/components/TextInput.svelte';
  import { initials } from '$lib/utils/labels';
  import { currentUser, refreshUser } from '$lib/stores/auth.svelte';
  import { toast } from '$lib/stores/toast.svelte';

  let user = $derived(currentUser());

  let code = $state('');
  let verifyToken = $state('');
  let busy = $state(false);
  let error = $state<unknown>(null);

  async function run(action: () => Promise<void>) {
    busy = true;
    error = null;
    try {
      await action();
    } catch (caught) {
      error = caught;
    } finally {
      busy = false;
    }
  }

  async function redeem() {
    await run(async () => {
      const { error: err } = await api.POST('/auth/support-code/redeem', {
        body: { code }
      });
      if (err) throw err;
      toast('Support code redeemed — welcome to the paid tier.');
      code = '';
      await refreshUser();
    });
  }

  async function requestVerification() {
    await run(async () => {
      const { error: err } = await api.POST('/auth/verify-email/request');
      if (err) throw err;
      toast('Verification email queued. Paste the token below once it arrives.');
    });
  }

  async function confirmVerification() {
    await run(async () => {
      const { error: err } = await api.POST('/auth/verify-email/{token}', {
        params: { path: { token: verifyToken } }
      });
      if (err) throw err;
      toast('Email verified.');
      verifyToken = '';
      await refreshUser();
    });
  }
</script>

{#snippet section(icon: IconName, title: string, description: string, body: Snippet)}
  <section class="grid gap-4 border-t border-line py-8 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] md:gap-10">
    <div class="flex items-start gap-3">
      <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-muted ring-1 ring-line">
        <Icon name={icon} class="h-[18px] w-[18px]" />
      </span>
      <div>
        <h2 class="text-[15px] font-semibold text-fg">{title}</h2>
        <p class="mt-1 text-sm leading-relaxed text-muted">{description}</p>
      </div>
    </div>
    <div class="min-w-0">{@render body()}</div>
  </section>
{/snippet}

<PageHeader title="Account" description="Your profile, plan, and email verification." />

{#if user}
  <div class="flex flex-col">
    <div class="mb-8 flex flex-col gap-5 rounded-2xl border border-line bg-surface p-5 shadow-card sm:flex-row sm:items-center sm:p-6">
      <span
        class="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-accent-soft font-display text-xl font-semibold text-accent-text ring-1 ring-accent-line/60"
        aria-hidden="true"
      >
        {initials(user.name)}
      </span>
      <div class="min-w-0 flex-1">
        <p class="truncate text-lg font-semibold text-fg">{user.name}</p>
        <p class="mt-0.5 flex flex-wrap items-center gap-2 text-sm text-muted">
          <span class="truncate">{user.email ?? '—'}</span>
          {#if user.email_verified}
            <Badge tone="success" icon="check">Verified</Badge>
          {:else}
            <Badge tone="warning" icon="alert-triangle">Not verified</Badge>
          {/if}
        </p>
      </div>
      <dl class="flex gap-8 sm:text-right">
        <div>
          <dt class="text-xs font-medium uppercase tracking-wide text-subtle">Plan</dt>
          <dd class="mt-1 text-sm font-semibold text-fg">{user.tier === 'paid' ? 'Paid' : 'Free'}</dd>
        </div>
        <div>
          <dt class="text-xs font-medium uppercase tracking-wide text-subtle">Member since</dt>
          <dd class="mt-1 text-sm font-semibold text-fg">
            {user.created_at
              ? new Date(user.created_at).toLocaleDateString(undefined, { month: 'short', year: 'numeric' })
              : '—'}
          </dd>
        </div>
      </dl>
    </div>

    {#if error}<div class="mb-6"><ErrorBanner {error} /></div>{/if}

    {#snippet verifyBody()}
      {#if user?.email_verified}
        <p class="flex items-center gap-2 rounded-xl border border-success/30 bg-success-soft px-4 py-3 text-sm text-success-text">
          <Icon name="check" class="h-4 w-4" /> Your email is verified.
        </p>
      {:else}
        <div class="flex flex-col gap-4">
          <div>
            <Button variant="secondary" onclick={requestVerification} disabled={busy}>
              <Icon name="mail" class="h-4 w-4" /> Send verification email
            </Button>
          </div>
          <form
            onsubmit={(e) => {
              e.preventDefault();
              confirmVerification();
            }}
            class="flex flex-col gap-3 sm:flex-row sm:items-end"
          >
            <div class="flex-1">
              <TextInput label="Verification token" bind:value={verifyToken} required />
            </div>
            <Button type="submit" loading={busy} class="h-10">Verify</Button>
          </form>
        </div>
      {/if}
    {/snippet}
    {@render section(
      'mail',
      'Verify email',
      'Uploading sources and creating courses require a verified email address. We email you a token to paste here.',
      verifyBody
    )}

    {#snippet redeemBody()}
      <form
        onsubmit={(e) => {
          e.preventDefault();
          redeem();
        }}
        class="flex flex-col gap-3 sm:flex-row sm:items-end"
      >
        <div class="flex-1">
          <TextInput
            label="Code"
            bind:value={code}
            placeholder="XXXX-XXXX-XXXX-XXXX"
            required
            class="font-mono tracking-[0.08em]"
          />
        </div>
        <Button type="submit" loading={busy} class="h-10">Redeem</Button>
      </form>
    {/snippet}
    {@render section(
      'ticket',
      'Redeem a support code',
      'Have a code from the operator? Redeem it to upgrade to the paid tier.',
      redeemBody
    )}

    {#snippet deleteBody()}
      <p class="rounded-xl border border-line bg-surface-2/60 px-4 py-3 text-sm leading-relaxed text-muted">
        Account deletion is not yet exposed in this interface. When it is, it will
        enter a 7-day grace period before anything is destroyed, and your course
        memories will survive as the keepsake record described in the project
        rules. Contact the operator to request deletion.
      </p>
    {/snippet}
    {@render section('trash', 'Delete account', 'Permanently remove your account and data.', deleteBody)}
  </div>
{/if}
