<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import Button from '$lib/components/Button.svelte';
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

<div class="mb-8">
  <h1 class="font-display text-3xl font-medium tracking-tight text-fg">Welcome back</h1>
  <p class="mt-2 text-[15px] text-muted">Sign in to pick up where you left off.</p>
</div>

<form onsubmit={submit} class="flex flex-col gap-4">
  {#if error}<ErrorBanner {error} />{/if}
  <TextInput label="Email" type="email" bind:value={email} required autocomplete="email" placeholder="you@school.edu" />
  <div class="flex flex-col gap-1.5">
    <TextInput
      label="Password"
      type="password"
      bind:value={password}
      required
      autocomplete="current-password"
    />
    <a href="/password-reset" class="self-end text-[13px] font-medium text-muted hover:text-fg">Forgot password?</a>
  </div>
  <Button type="submit" size="lg" {loading} class="mt-1 w-full">Sign in</Button>
</form>
<p class="mt-8 text-center text-sm text-muted">
  New here? <a href="/register" class="font-medium text-accent-text hover:underline">Create an account</a>
</p>
