<script lang="ts">
  import { goto } from '$app/navigation';
  import Button from '$lib/components/Button.svelte';
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

<div class="mb-8">
  <h1 class="font-display text-3xl font-medium tracking-tight text-fg">Create your account</h1>
  <p class="mt-2 text-[15px] text-muted">Build a course from your own material, or join one.</p>
</div>

<form onsubmit={submit} class="flex flex-col gap-4">
  {#if error}<ErrorBanner {error} />{/if}
  <TextInput label="Name" bind:value={name} required autocomplete="name" />
  <TextInput label="Email" type="email" bind:value={email} required autocomplete="email" placeholder="you@school.edu" />
  <TextInput
    label="Password"
    type="password"
    bind:value={password}
    required
    autocomplete="new-password"
  />
  <Button type="submit" size="lg" {loading} class="mt-1 w-full">Create account</Button>
</form>
<p class="mt-8 text-center text-sm text-muted">
  Already have an account? <a href="/login" class="font-medium text-accent-text hover:underline">Sign in</a>
</p>
