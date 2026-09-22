<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import TextInput from '$lib/components/TextInput.svelte';
  import { login } from '$lib/stores/auth.svelte';

  let email = $state('');
  let password = $state('');
  let error = $state<unknown>(null);
  let loading = $state(false);

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    loading = true;
    error = null;
    try {
      await login(email, password);
      const next = page.url.searchParams.get('next');
      await goto(next && next.startsWith('/') ? next : '/');
    } catch (err) {
      error = err;
    } finally {
      loading = false;
    }
  }
</script>

<Card title="Sign in">
  <form onsubmit={submit} class="flex flex-col gap-4">
    {#if error}<ErrorBanner {error} />{/if}
    <TextInput label="Email" type="email" bind:value={email} required autocomplete="email" />
    <TextInput
      label="Password"
      type="password"
      bind:value={password}
      required
      autocomplete="current-password"
    />
    <Button type="submit" {loading}>Sign in</Button>
  </form>
  <div class="mt-4 flex justify-between text-sm">
    <a href="/password-reset" class="text-indigo-600 hover:underline">Forgot password?</a>
    <a href="/register" class="text-indigo-600 hover:underline">Create account</a>
  </div>
</Card>
