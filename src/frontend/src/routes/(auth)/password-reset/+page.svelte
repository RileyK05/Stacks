<script lang="ts">
  import { page } from '$app/state';
  import { api } from '$lib/api/client';
  import Button from '$lib/components/Button.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import TextInput from '$lib/components/TextInput.svelte';

  const resetToken = page.url.searchParams.get('token');

  let email = $state('');
  let newPassword = $state('');
  let error = $state<unknown>(null);
  let notice = $state<string | null>(null);
  let loading = $state(false);

  async function requestReset(event: SubmitEvent) {
    event.preventDefault();
    loading = true;
    error = null;
    notice = null;
    try {
      const { error: err } = await api.POST('/auth/password-reset/request', {
        body: { email }
      });
      if (err) throw err;
      notice = 'If the account exists, a password reset email is on its way.';
    } catch (caught) {
      error = caught;
    } finally {
      loading = false;
    }
  }

  async function confirmReset(event: SubmitEvent) {
    event.preventDefault();
    loading = true;
    error = null;
    notice = null;
    try {
      const { error: err } = await api.POST('/auth/password-reset/confirm', {
        body: { token: resetToken ?? '', new_password: newPassword }
      });
      if (err) throw err;
      notice = 'Password updated. You can sign in with the new password.';
    } catch (caught) {
      error = caught;
    } finally {
      loading = false;
    }
  }
</script>

{#if resetToken}
  <div class="mb-8">
    <h1 class="font-display text-3xl font-medium tracking-tight text-fg">Choose a new password</h1>
    <p class="mt-2 text-[15px] text-muted">Enter a new password for your account.</p>
  </div>
  <form onsubmit={confirmReset} class="flex flex-col gap-4">
    {#if error}<ErrorBanner {error} />{/if}
    {#if notice}
      <p class="flex items-start gap-2 rounded-xl border border-success/30 bg-success-soft px-4 py-3 text-sm text-success-text">
        <Icon name="check" class="mt-0.5 h-4 w-4" />{notice}
      </p>
    {/if}
    <TextInput
      label="New password"
      type="password"
      bind:value={newPassword}
      required
      autocomplete="new-password"
    />
    <Button type="submit" size="lg" {loading} class="mt-1 w-full">Update password</Button>
  </form>
{:else}
  <div class="mb-8">
    <h1 class="font-display text-3xl font-medium tracking-tight text-fg">Reset your password</h1>
    <p class="mt-2 text-[15px] text-muted">Enter your email and we'll send you a reset link.</p>
  </div>
  <form onsubmit={requestReset} class="flex flex-col gap-4">
    {#if error}<ErrorBanner {error} />{/if}
    {#if notice}
      <p class="flex items-start gap-2 rounded-xl border border-success/30 bg-success-soft px-4 py-3 text-sm text-success-text">
        <Icon name="check" class="mt-0.5 h-4 w-4" />{notice}
      </p>
    {/if}
    <TextInput label="Email" type="email" bind:value={email} required autocomplete="email" />
    <Button type="submit" size="lg" {loading} class="mt-1 w-full">Send reset email</Button>
  </form>
{/if}
<p class="mt-8 text-center text-sm text-muted">
  <a href="/login" class="inline-flex items-center gap-1 font-medium text-accent-text hover:underline">
    <Icon name="chevron-left" class="h-4 w-4" /> Back to sign in
  </a>
</p>
