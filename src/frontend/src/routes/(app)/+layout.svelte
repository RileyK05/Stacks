<script lang="ts">
  import { fade, fly } from 'svelte/transition';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import Icon, { type IconName } from '$lib/components/Icon.svelte';
  import Spinner from '$lib/components/Spinner.svelte';
  import { loadToken } from '$lib/auth/token';
  import { authReady, currentUser, logout } from '$lib/stores/auth.svelte';
  import { currentTheme, toggleTheme } from '$lib/stores/theme.svelte';
  import { initials } from '$lib/utils/labels';

  let { children } = $props();

  let user = $derived(currentUser());
  let ready = $derived(authReady());
  // The course page hosts the chat + workspace split, which needs room
  // for two readable columns; every other page keeps the reading width.
  let wide = $derived(page.route.id === '/(app)/courses/[id]');
  let drawerOpen = $state(false);

  const navItems: { href: string; label: string; icon: IconName }[] = [
    { href: '/', label: 'My courses', icon: 'book' },
    { href: '/discover', label: 'Discover', icon: 'compass' },
    { href: '/archives', label: 'Archives', icon: 'archive' },
    { href: '/account', label: 'Account', icon: 'user' }
  ];

  function isActive(href: string): boolean {
    const path = page.url.pathname;
    // A course page lives under "My courses" in the nav.
    if (href === '/') return path === '/' || path.startsWith('/courses/');
    return path === href || path.startsWith(`${href}/`);
  }

  $effect(() => {
    // Only redirect when there is genuinely no credential: a transient
    // /auth/me failure (server down) must not bounce a logged-in user.
    if (ready && !user && !loadToken()) {
      const here = page.url.pathname + page.url.search;
      void goto(`/login?next=${encodeURIComponent(here)}`);
    }
  });

  $effect(() => {
    // Close the mobile drawer whenever the route changes.
    void page.url.pathname;
    drawerOpen = false;
  });
</script>

{#snippet brand()}
  <a href="/" class="flex items-center gap-2.5">
    <span
      class="flex h-8 w-8 items-center justify-center rounded-[10px] bg-accent text-on-accent shadow-card"
    >
      <Icon name="book" class="h-[18px] w-[18px]" />
    </span>
    <span class="font-display text-[17px] font-semibold tracking-tight text-fg">Course Assistant</span>
  </a>
{/snippet}

{#snippet sidebar()}
  <div class="flex h-full flex-col px-3 py-5">
    <div class="px-2">{@render brand()}</div>

    <nav class="mt-8 flex flex-col gap-0.5" aria-label="Main">
      {#each navItems as item (item.href)}
        {@const active = isActive(item.href)}
        <a
          href={item.href}
          aria-current={active ? 'page' : undefined}
          class={`group flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors ${
            active
              ? 'bg-surface text-fg shadow-card ring-1 ring-line'
              : 'text-muted hover:bg-surface-2 hover:text-fg'
          }`}
        >
          <Icon
            name={item.icon}
            class={`h-[18px] w-[18px] ${active ? 'text-accent-text' : 'text-subtle group-hover:text-muted'}`}
          />
          {item.label}
        </a>
      {/each}
    </nav>

    {#if user}
      <div class="mt-auto flex flex-col gap-3">
        {#if !user.email_verified}
          <a
            href="/account"
            class="flex items-start gap-2.5 rounded-xl border border-warning/30 bg-warning-soft px-3 py-2.5 text-[13px] text-warning-text transition-colors hover:border-warning/60"
          >
            <Icon name="mail" class="mt-0.5 h-4 w-4" />
            <span>
              <span class="block font-medium">Verify your email</span>
              <span class="opacity-80">Needed to create courses and upload.</span>
            </span>
          </a>
        {/if}

        <div class="flex items-center gap-2.5 rounded-xl px-2 py-2">
          <span
            class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface-3 text-[13px] font-semibold text-fg-soft"
            aria-hidden="true"
          >
            {initials(user.name)}
          </span>
          <div class="min-w-0 flex-1">
            <p class="flex items-center gap-1.5 truncate text-sm font-medium text-fg">
              <span class="truncate">{user.name}</span>
              {#if user.tier === 'paid'}
                <span class="rounded bg-accent-soft px-1 text-[10px] font-semibold uppercase tracking-wide text-accent-text">Pro</span>
              {/if}
            </p>
            <p class="truncate text-xs text-subtle">{user.email ?? ''}</p>
          </div>
        </div>

        <div class="flex gap-1 border-t border-line pt-3">
          <button
            type="button"
            onclick={toggleTheme}
            class="flex flex-1 items-center justify-center gap-2 rounded-lg px-2 py-1.5 text-[13px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg"
            aria-label={currentTheme() === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            <Icon name={currentTheme() === 'dark' ? 'sun' : 'moon'} class="h-4 w-4" />
            {currentTheme() === 'dark' ? 'Light' : 'Dark'}
          </button>
          <button
            type="button"
            onclick={logout}
            class="flex flex-1 items-center justify-center gap-2 rounded-lg px-2 py-1.5 text-[13px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg"
          >
            <Icon name="log-out" class="h-4 w-4" />
            Sign out
          </button>
        </div>
      </div>
    {/if}
  </div>
{/snippet}

{#if user}
  <div class="min-h-dvh lg:grid lg:grid-cols-[252px_minmax(0,1fr)]">
    <aside class="sticky top-0 hidden h-dvh border-r border-line bg-surface-2/40 lg:block">
      {@render sidebar()}
    </aside>

    <header
      class="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-line bg-bg/85 px-4 backdrop-blur-md lg:hidden"
    >
      {@render brand()}
      <button
        type="button"
        onclick={() => (drawerOpen = true)}
        class="-mr-1.5 rounded-lg p-2 text-muted transition-colors hover:bg-surface-2 hover:text-fg"
        aria-label="Open menu"
        aria-expanded={drawerOpen}
      >
        <Icon name="menu" class="h-5 w-5" />
      </button>
    </header>

    {#if drawerOpen}
      <div
        class="fixed inset-0 z-40 bg-black/35 backdrop-blur-[2px] lg:hidden"
        role="presentation"
        transition:fade={{ duration: 150 }}
        onclick={() => (drawerOpen = false)}
      ></div>
      <aside
        class="fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] border-r border-line bg-bg shadow-pop lg:hidden"
        transition:fly={{ x: -288, duration: 220, opacity: 1 }}
      >
        <button
          type="button"
          onclick={() => (drawerOpen = false)}
          class="absolute right-3 top-4 rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-fg"
          aria-label="Close menu"
        >
          <Icon name="x" class="h-5 w-5" />
        </button>
        {@render sidebar()}
      </aside>
    {/if}

    <main class="min-w-0">
      <div class={`mx-auto px-4 pb-16 pt-6 sm:px-8 sm:pt-10 ${wide ? 'max-w-7xl' : 'max-w-5xl'}`}>
        {@render children()}
      </div>
    </main>
  </div>
{:else}
  <div class="flex min-h-dvh items-center justify-center text-subtle"><Spinner class="h-5 w-5" /></div>
{/if}
