<script lang="ts">
  import { goto } from '$app/navigation';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import TextInput from '$lib/components/TextInput.svelte';
  import { login, register } from '$lib/stores/auth.svelte';

  let name = $state('');
  let email = $state('');
  let password = $state('');
  let error = $state<unknown>(null);
  let loading = $state(false);

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    loading = true;
    error = null;
    try {
      await register(name, email, password);
      await login(email, password);
      await goto('/');
    } catch (err) {
      error = err;
    } finally {
      loading = false;
    }
  }
</script>

<Card title="Create account">
  <form onsubmit={submit} class="flex flex-col gap-4">
    {#if error}<ErrorBanner {error} />{/if}
    <TextInput label="Name" bind:value={name} required autocomplete="name" />
    <TextInput label="Email" type="email" bind:value={email} required autocomplete="email" />
    <TextInput
      label="Password"
      type="password"
      bind:value={password}
      required
      autocomplete="new-password"
    />
    <Button type="submit" {loading}>Register</Button>
  </form>
  <p class="mt-4 text-center text-sm">
    Already have an account? <a href="/login" class="text-indigo-600 hover:underline">Sign in</a>
  </p>
</Card>
