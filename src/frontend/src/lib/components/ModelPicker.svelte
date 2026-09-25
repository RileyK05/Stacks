<script lang="ts" module>
  import type { components } from '$lib/api/schema';

  export type ModelChoice = components['schemas']['ModelChoiceView'];
</script>

<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import Popover from '$lib/components/Popover.svelte';

  type ModelOption = components['schemas']['ModelOption'];
  type Connection = components['schemas']['ConnectionView'];

  /** The "no explicit choice" row: Settings default in a chat, "Same as
      answers" / "None" in Settings. Omit it when a model must be chosen. */
  interface NullOption {
    label: string;
    description: string;
    /** What the closed picker shows while nothing is chosen. */
    current: string;
    hint?: string;
  }

  interface Props {
    options: ModelOption[];
    connections: Connection[];
    choice: ModelChoice | null;
    nullOption?: NullOption | null;
    disabled?: boolean;
    /** Full-width trigger (forms) instead of a compact chip (toolbars). */
    block?: boolean;
    align?: 'start' | 'end';
    onchange: (choice: ModelChoice | null) => void;
  }

  let {
    options,
    connections,
    choice,
    nullOption = null,
    disabled = false,
    block = false,
    align = 'end',
    onchange
  }: Props = $props();

  let open = $state(false);
  let otherOpen = $state(false);
  let otherConnection = $state('');
  let otherModel = $state('');

  const cloudConnections = $derived(connections.filter((c) => !c.builtin));
  const local = $derived(options.filter((o) => o.is_local));
  const groups = $derived.by(() => {
    const byConnection = new Map<string, ModelOption[]>();
    for (const option of options.filter((o) => !o.is_local)) {
      const list = byConnection.get(option.connection) ?? [];
      list.push(option);
      byConnection.set(option.connection, list);
    }
    return [...byConnection.entries()].map(([id, list]) => ({ id, name: list[0].connection_name, list }));
  });

  function matches(option: ModelOption): boolean {
    if (choice === null || choice.connection !== option.connection) return false;
    if (choice.model) return choice.model === option.model;
    const connection = connections.find((c) => c.id === choice?.connection);
    return option.model === connection?.effective_default_model;
  }

  const current = $derived.by(() => {
    if (choice === null) {
      return { label: nullOption?.current ?? 'Choose a model', hint: nullOption?.hint ?? '' };
    }
    const option = options.find(matches);
    const connection = connections.find((c) => c.id === choice?.connection);
    return {
      label: option?.label ?? choice.model ?? connection?.effective_default_model ?? 'Model',
      hint: choice.connection === 'local' ? 'On this computer' : (connection?.name ?? choice.connection)
    };
  });

  function pick(next: ModelChoice | null, close: () => void) {
    close();
    otherOpen = false;
    onchange(next);
  }

  function useOther(event: SubmitEvent, close: () => void) {
    event.preventDefault();
    if (!otherConnection || !otherModel.trim()) return;
    pick({ connection: otherConnection, model: otherModel.trim() }, close);
    otherModel = '';
  }

  $effect(() => {
    if (!otherConnection && cloudConnections.length > 0) otherConnection = cloudConnections[0].id;
  });
</script>

{#snippet row(option: ModelOption, close: () => void)}
  <button
    type="button"
    disabled={!option.available}
    onclick={() => pick({ connection: option.connection, model: option.model }, close)}
    class="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent"
  >
    <span class="min-w-0 flex-1">
      <span class="block truncate text-[13px] font-medium text-fg">{option.label}</span>
      {#if option.note}<span class="block text-[11px] text-subtle">{option.note}</span>{/if}
    </span>
    {#if matches(option)}<Icon name="check" class="h-4 w-4 text-accent-text" />{/if}
  </button>
{/snippet}

{#snippet heading(text: string)}
  <p class="border-t border-line px-3 pb-1 pt-2.5 text-[11px] font-semibold uppercase tracking-wider text-subtle">
    {text}
  </p>
{/snippet}

<Popover bind:open label="Choose a model" {align} width="w-80">
  {#snippet trigger(props)}
    <button
      type="button"
      {...props}
      {disabled}
      class={`items-center gap-2 rounded-lg border border-line bg-surface text-[13px] shadow-card transition-colors hover:border-line-strong disabled:opacity-60 ${
        block ? 'flex h-10 w-full px-3' : 'inline-flex max-w-64 px-2.5 py-1.5'
      }`}
    >
      <Icon name="cpu" class="h-3.5 w-3.5 shrink-0 text-accent-text" />
      <span class="truncate font-medium text-fg">{current.label}</span>
      {#if current.hint}
        <span class={`shrink-0 text-subtle ${block ? '' : 'hidden sm:inline'}`}>· {current.hint}</span>
      {/if}
      <Icon name="chevron-down" class="ml-auto h-3.5 w-3.5 shrink-0 text-subtle" />
    </button>
  {/snippet}
  {#snippet children(close)}
    <div class="max-h-[60vh] overflow-y-auto py-1">
      {#if nullOption}
        <button
          type="button"
          onclick={() => pick(null, close)}
          class="flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-surface-2"
        >
          <span class="min-w-0 flex-1">
            <span class="block text-[13px] font-medium text-fg">{nullOption.label}</span>
            <span class="block truncate text-[11px] text-subtle">{nullOption.description}</span>
          </span>
          {#if choice === null}<Icon name="check" class="h-4 w-4 text-accent-text" />{/if}
        </button>
      {/if}

      {#if local.length > 0}
        {@render heading('On this computer')}
        {#each local as option (option.model)}{@render row(option, close)}{/each}
      {/if}

      {#each groups as group (group.id)}
        {@render heading(group.name)}
        {#each group.list as option (option.model)}{@render row(option, close)}{/each}
      {/each}

      {#if cloudConnections.length > 0}
        <div class="border-t border-line px-3 py-2.5">
          {#if otherOpen}
            <form class="flex flex-col gap-2" onsubmit={(e) => useOther(e, close)}>
              <select
                bind:value={otherConnection}
                aria-label="Connection"
                class="h-8 rounded-lg border border-line-strong bg-surface px-2 text-[13px] text-fg focus:border-accent focus:outline-none"
              >
                {#each cloudConnections as connection (connection.id)}
                  <option value={connection.id}>{connection.name}</option>
                {/each}
              </select>
              <div class="flex gap-2">
                <input
                  bind:value={otherModel}
                  placeholder="Model id, e.g. gpt-5-mini"
                  aria-label="Model id"
                  class="h-8 min-w-0 flex-1 rounded-lg border border-line-strong bg-surface px-2 text-[13px] text-fg placeholder:text-subtle focus:border-accent focus:outline-none"
                />
                <button
                  type="submit"
                  class="rounded-lg bg-accent px-2.5 text-[13px] font-medium text-on-accent hover:bg-accent-hover disabled:opacity-50"
                  disabled={!otherModel.trim()}
                >
                  Use
                </button>
              </div>
            </form>
          {:else}
            <button type="button" onclick={() => (otherOpen = true)} class="text-[13px] font-medium text-accent-text hover:underline">
              Use another model…
            </button>
          {/if}
        </div>
      {/if}
    </div>
    <a
      href="/settings"
      onclick={close}
      class="flex items-center gap-2 border-t border-line bg-surface-2/50 px-3 py-2.5 text-[12px] font-medium text-muted hover:text-fg"
    >
      <Icon name="settings" class="h-3.5 w-3.5" /> Add models and connections in Settings
    </a>
  {/snippet}
</Popover>
