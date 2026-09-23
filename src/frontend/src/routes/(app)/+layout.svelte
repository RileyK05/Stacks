<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import Button from '$lib/components/Button.svelte';
  import Spinner from '$lib/components/Spinner.svelte';
  import { loadToken } from '$lib/auth/token';
  import { authReady, currentUser, logout } from '$lib/stores/auth.svelte';
  import { currentTheme, toggleTheme } from '$lib/stores/theme.svelte';

  let { children } = $props();

  let user = $derived(currentUser());
  let ready = $derived(authReady());
  // The course page hosts the chat + workspace split, which needs room
  // for two readable columns; every other page keeps the reading width.
  let wide = $derived(page.route.id === '/(app)/courses/[id]');

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
    <aside class="flex w-60 flex-col border-r border-slate-200 bg-white/80 backdrop-blur p-4 dark:border-slate-800 dark:bg-slate-900/80">
      <a href="/" class="mb-8 flex items-center gap-2 px-2 pt-1">
        <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">
          CA
        </span>
        <span class="text-base font-semibold tracking-tight text-slate-900 dark:text-slate-100">Course Assistant</span>
      </a>
      <nav class="flex flex-col gap-1">
        {#each navItems as item (item.href)}
          <a
            href={item.href}
            class={`flex items-center rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              page.url.pathname === item.href
                ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300'
                : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100'
            }`}
          >
            {item.label}
          </a>
        {/each}
      </nav>
      <div class="mt-auto flex flex-col gap-3 border-t border-slate-200 pt-4 dark:border-slate-800">
        <div class="px-3">
          <p class="text-sm font-medium text-slate-900 dark:text-slate-100">{user.name}</p>
          <p class="truncate text-xs text-slate-500 dark:text-slate-400">{user.email ?? ''}</p>
          <span
            class={`mt-1 inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
              user.tier === 'paid'
                ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-300'
                : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
            }`}
          >
            {user.tier}
          </span>
          {#if !user.email_verified}
            <p class="mt-2 text-xs font-medium text-amber-600 dark:text-amber-300">email not verified</p>
          {/if}
        </div>
        <Button variant="secondary" onclick={logout}>Sign out</Button>
        <button
          type="button"
          onclick={toggleTheme}
          class="flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 ring-1 ring-slate-200 transition-colors hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:ring-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-100"
          aria-label={currentTheme() === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {#if currentTheme() === 'dark'}
            <svg viewBox="0 0 20 20" fill="currentColor" class="h-4 w-4" aria-hidden="true">
              <path
                fill-rule="evenodd"
                d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z"
                clip-rule="evenodd"
              />
            </svg>
            Light mode
          {:else}
            <svg viewBox="0 0 20 20" fill="currentColor" class="h-4 w-4" aria-hidden="true">
              <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
            </svg>
            Dark mode
          {/if}
        </button>
      </div>
    </aside>
    <main class="flex-1 overflow-y-auto">
      <div class={`mx-auto px-8 py-8 ${wide ? 'max-w-7xl' : 'max-w-4xl'}`}>{@render children()}</div>
    </main>
  </div>
{:else}
  <div class="flex min-h-screen items-center justify-center"><Spinner /></div>
{/if}
