<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import Button from '$lib/components/Button.svelte';
  import Spinner from '$lib/components/Spinner.svelte';
  import { loadToken } from '$lib/auth/token';
  import { authReady, currentUser, logout } from '$lib/stores/auth.svelte';

  let { children } = $props();

  let user = $derived(currentUser());
  let ready = $derived(authReady());

  const navItems = [
    { href: '/', label: 'My courses' },
    { href: '/discover', label: 'Discover' },
    { href: '/archives', label: 'Archives' },
    { href: '/account', label: 'Account' }
  ];

  $effect(() => {
    // Only redirect when there is genuinely no credential: a transient
    // /auth/me failure (server down) must not bounce a logged-in user.
    if (ready && !user && !loadToken()) {
      const here = page.url.pathname + page.url.search;
      void goto(`/login?next=${encodeURIComponent(here)}`);
    }
  });
</script>

{#if user}
  <div class="flex min-h-screen">
    <aside class="flex w-60 flex-col border-r border-slate-200 bg-white/80 backdrop-blur p-4">
      <a href="/" class="mb-8 flex items-center gap-2 px-2 pt-1">
        <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">
          CA
        </span>
        <span class="text-base font-semibold tracking-tight text-slate-900">Course Assistant</span>
      </a>
      <nav class="flex flex-col gap-1">
        {#each navItems as item (item.href)}
          <a
            href={item.href}
            class={`flex items-center rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              page.url.pathname === item.href
                ? 'bg-indigo-50 text-indigo-700'
                : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
            }`}
          >
            {item.label}
          </a>
        {/each}
      </nav>
      <div class="mt-auto flex flex-col gap-3 border-t border-slate-200 pt-4">
        <div class="px-3">
          <p class="text-sm font-medium text-slate-900">{user.name}</p>
          <p class="truncate text-xs text-slate-500">{user.email ?? ''}</p>
          <span
            class={`mt-1 inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
              user.tier === 'paid'
                ? 'bg-indigo-100 text-indigo-700'
                : 'bg-slate-100 text-slate-600'
            }`}
          >
            {user.tier}
          </span>
          {#if !user.email_verified}
            <p class="mt-2 text-xs font-medium text-amber-600">email not verified</p>
          {/if}
        </div>
        <Button variant="secondary" onclick={logout}>Sign out</Button>
      </div>
    </aside>
    <main class="flex-1 overflow-y-auto">
      <div class="mx-auto max-w-4xl px-8 py-8">{@render children()}</div>
    </main>
  </div>
{:else}
  <div class="flex min-h-screen items-center justify-center"><Spinner /></div>
{/if}
