<script lang="ts">
  import { fade, fly } from 'svelte/transition';
  import { page } from '$app/state';
  import Icon, { type IconName } from '$lib/components/Icon.svelte';
  import { currentTheme, toggleTheme } from '$lib/stores/theme.svelte';

  let { children } = $props();

  // The course page hosts the chat + workspace split, which needs room
  // for two readable columns; every other page keeps the reading width.
  let wide = $derived(page.route.id === '/(app)/courses/[id]');
  let drawerOpen = $state(false);

  const navItems: { href: string; label: string; icon: IconName }[] = [
    { href: '/', label: 'My courses', icon: 'book' },
    { href: '/trash', label: 'Trash', icon: 'trash' },
    { href: '/settings', label: 'Settings', icon: 'settings' }
  ];

  function isActive(href: string): boolean {
    const path = page.url.pathname;
    // A course page lives under "My courses" in the nav.
    if (href === '/') return path === '/' || path.startsWith('/courses/');
    return path === href || path.startsWith(`${href}/`);
  }

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
    <span class="font-display text-[17px] font-semibold tracking-tight text-fg">Stacks</span>
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

    <div class="mt-auto border-t border-line pt-3">
      <button
        type="button"
        onclick={toggleTheme}
        class="flex w-full items-center justify-center gap-2 rounded-lg px-2 py-1.5 text-[13px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg"
        aria-label={currentTheme() === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      >
        <Icon name={currentTheme() === 'dark' ? 'sun' : 'moon'} class="h-4 w-4" />
        {currentTheme() === 'dark' ? 'Light mode' : 'Dark mode'}
      </button>
    </div>
  </div>
{/snippet}

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
