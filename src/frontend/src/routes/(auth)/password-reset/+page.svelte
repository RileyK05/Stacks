<script lang="ts">
  import { page } from '$app/state';
  import { api } from '$lib/api/client';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
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
  <Card title="Choose a new password">
    <form onsubmit={confirmReset} class="flex flex-col gap-4">
      {#if error}<ErrorBanner {error} />{/if}
      {#if notice}<p class="text-sm text-green-700 dark:text-green-300">{notice}</p>{/if}
      <TextInput
        label="New password"
        type="password"
        bind:value={newPassword}
        required
        autocomplete="new-password"
      />
      <Button type="submit" {loading}>Update password</Button>
    </form>
    <p class="mt-4 text-center text-sm">
      <a href="/login" class="text-indigo-600 hover:underline dark:text-indigo-300">Back to sign in</a>
    </p>
  </Card>
{:else}
  <Card title="Reset password">
    <form onsubmit={requestReset} class="flex flex-col gap-4">
      {#if error}<ErrorBanner {error} />{/if}
      {#if notice}<p class="text-sm text-green-700 dark:text-green-300">{notice}</p>{/if}
      <TextInput label="Email" type="email" bind:value={email} required autocomplete="email" />
      <Button type="submit" {loading}>Send reset email</Button>
    </form>
    <p class="mt-4 text-center text-sm">
      <a href="/login" class="text-indigo-600 hover:underline">Back to sign in</a>
    </p>
  </Card>
{/if}
