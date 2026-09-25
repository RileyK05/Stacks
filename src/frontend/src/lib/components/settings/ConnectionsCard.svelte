<script lang="ts">
  import { api } from '$lib/api/client';
  import type { components } from '$lib/api/schema';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import TextInput from '$lib/components/TextInput.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { toast } from '$lib/stores/toast.svelte';

  type Preset = components['schemas']['PresetView'];
  type Connection = components['schemas']['ConnectionView'];
  type ConnectionTest = components['schemas']['ConnectionTest'];

  interface Props {
    presets: Preset[];
    connections: Connection[];
    onchanged: () => Promise<void>;
  }

  let { presets, connections, onchanged }: Props = $props();

  /** Where to get a key, per preset — shown when adding or editing. */
  const help: Record<string, string> = {
    openai: 'Create a key at platform.openai.com → API keys, and set a monthly limit under Billing.',
    anthropic: 'Create a key at console.anthropic.com → API keys.',
    google: 'Create a key at aistudio.google.com → Get API key.',
    openrouter:
      'Create a key at openrouter.ai → Keys. Free models (ending in :free) need no credit.',
    groq: 'Create a key at console.groq.com → API keys.',
    lmstudio: "Start LM Studio's local server (Developer tab). No key needed.",
    ollama: 'Install Ollama and pull a model; it serves on this computer. No key needed.',
    custom: 'Any server that speaks the OpenAI chat-completions API.'
  };

  const addable = $derived(presets.filter((p) => p.name !== 'local'));
  const userConnections = $derived(connections.filter((c) => !c.builtin));

  let adding = $state<Preset | null>(null);
  let form = $state({ name: '', key: '', baseUrl: '', model: '' });
  let saving = $state(false);
  let error = $state<unknown>(null);

  let editing = $state<string | null>(null);
  let edit = $state({ name: '', baseUrl: '', model: '', key: '' });
  let tests = $state<Record<string, ConnectionTest>>({});
  let testing = $state<string | null>(null);

  const DISCLOSED_KEY = 'stacks_disclosed_providers';

  function disclosed(name: string): boolean {
    try {
      return (JSON.parse(localStorage.getItem(DISCLOSED_KEY) ?? '[]') as string[]).includes(name);
    } catch {
      return false;
    }
  }

  function rememberDisclosed(name: string) {
    try {
      const seen = JSON.parse(localStorage.getItem(DISCLOSED_KEY) ?? '[]') as string[];
      localStorage.setItem(DISCLOSED_KEY, JSON.stringify([...new Set([...seen, name])]));
    } catch {
      // Storage blocked: the notice simply shows again next time.
    }
  }

  function startAdd(preset: Preset) {
    adding = preset;
    error = null;
    form = { name: preset.label, key: '', baseUrl: '', model: preset.default_model };
  }

  async function add(event: SubmitEvent) {
    event.preventDefault();
    if (!adding) return;
    const preset = adding;
    if (preset.disclosure && !disclosed(preset.name)) {
      const ok = await confirmDialog({
        title: `Use ${preset.label}?`,
        message:
          'When a chat uses this connection, your question and the course excerpts used to answer it are sent to ' +
          `${preset.label}. Everything else stays on this computer.`,
        confirmLabel: 'Add it'
      });
      if (!ok) return;
      rememberDisclosed(preset.name);
    }
    saving = true;
    error = null;
    try {
      const { error: err } = await api.POST('/settings/connections', {
        body: {
          preset: preset.name,
          name: form.name.trim() || null,
          key: form.key.trim() || null,
          base_url: form.baseUrl.trim() || null,
          default_model: form.model.trim() || null
        }
      });
      if (err) throw err;
      toast(`${form.name.trim() || preset.label} added.`);
      adding = null;
      await onchanged();
    } catch (caught) {
      error = caught;
    } finally {
      saving = false;
    }
  }

  function startEdit(connection: Connection) {
    editing = connection.id;
    edit = {
      name: connection.name,
      baseUrl: connection.base_url ?? '',
      model: connection.default_model ?? '',
      key: ''
    };
  }

  async function saveEdit(connection: Connection) {
    saving = true;
    error = null;
    try {
      const { error: err } = await api.PATCH('/settings/connections/{connection_id}', {
        params: { path: { connection_id: connection.id } },
        body: { name: edit.name.trim() || connection.name, base_url: edit.baseUrl, default_model: edit.model }
      });
      if (err) throw err;
      if (edit.key.trim()) {
        const { error: keyErr } = await api.PUT('/settings/keys/{connection_id}', {
          params: { path: { connection_id: connection.id } },
          body: { key: edit.key.trim() }
        });
        if (keyErr) throw keyErr;
      }
      editing = null;
      toast('Saved.');
      await onchanged();
    } catch (caught) {
      error = caught;
    } finally {
      saving = false;
    }
  }

  async function removeKey(connection: Connection) {
    const { error: err } = await api.DELETE('/settings/keys/{connection_id}', {
      params: { path: { connection_id: connection.id } }
    });
    if (err) error = err;
    else await onchanged();
  }

  async function remove(connection: Connection) {
    const ok = await confirmDialog({
      title: `Remove ${connection.name}?`,
      message:
        'Its key is deleted from your system keychain, and chats or settings that used it go back to the default model.',
      confirmLabel: 'Remove',
      danger: true
    });
    if (!ok) return;
    const { error: err } = await api.DELETE('/settings/connections/{connection_id}', {
      params: { path: { connection_id: connection.id } }
    });
    if (err) error = err;
    else await onchanged();
  }

  async function test(connection: Connection) {
    testing = connection.id;
    try {
      const { data, error: err } = await api.POST('/settings/connections/{connection_id}/test', {
        params: { path: { connection_id: connection.id } }
      });
      if (err || !data) throw err ?? new Error('empty response');
      tests[connection.id] = data;
    } catch (caught) {
      error = caught;
    } finally {
      testing = null;
    }
  }

  function presetOf(connection: Connection): Preset | undefined {
    return presets.find((p) => p.name === connection.preset);
  }

  function needsUrl(preset: string): boolean {
    return preset === 'custom' || preset === 'lmstudio' || preset === 'ollama';
  }
</script>

<Card
  title="Connections"
  description="Cloud providers and model servers you can use besides the local model. Add as many as you like; each keeps its own key in your system keychain."
>
  <div class="flex flex-col gap-4">
    {#if error}<ErrorBanner {error} />{/if}

    {#if userConnections.length > 0}
      <ul class="divide-y divide-line overflow-hidden rounded-xl border border-line">
        {#each userConnections as connection (connection.id)}
          {@const result = tests[connection.id]}
          <li class="flex flex-col gap-3 px-4 py-3.5">
            <div class="flex flex-wrap items-center gap-3">
              <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-muted ring-1 ring-line">
                <Icon name={connection.disclosure ? 'globe' : 'plug'} class="h-4 w-4" />
              </span>
              <div class="min-w-0 flex-1">
                <p class="flex flex-wrap items-center gap-2 text-sm font-medium text-fg">
                  {connection.name}
                  <span class="text-xs font-normal text-subtle">{presetOf(connection)?.label}</span>
                  {#if !connection.disclosure}<Badge tone="success">On this computer</Badge>{/if}
                  {#if connection.requires_key && !connection.has_key}
                    <Badge tone="warning" dot>Needs a key</Badge>
                  {:else if connection.has_key}
                    <Badge tone="neutral" icon="key">Key saved</Badge>
                  {/if}
                </p>
                <p class="mt-0.5 truncate text-xs text-subtle">
                  {connection.effective_default_model || 'No default model'} · {connection.effective_base_url || 'No URL yet'}
                </p>
              </div>
              <div class="flex shrink-0 items-center gap-1">
                <Button variant="ghost" size="sm" loading={testing === connection.id} onclick={() => test(connection)}>Test</Button>
                <Button variant="ghost" size="sm" onclick={() => (editing === connection.id ? (editing = null) : startEdit(connection))}>
                  <Icon name="pencil" class="h-3.5 w-3.5" /> Edit
                </Button>
                <button
                  type="button"
                  onclick={() => remove(connection)}
                  aria-label={`Remove ${connection.name}`}
                  class="rounded-lg p-1.5 text-subtle transition-colors hover:bg-danger-soft hover:text-danger-text"
                >
                  <Icon name="trash" class="h-4 w-4" />
                </button>
              </div>
            </div>

            {#if result}
              <p class={`text-xs ${result.ok ? 'text-success-text' : 'text-danger-text'}`}>
                {#if result.ok}
                  Connected · {result.models?.length ?? 0} model{(result.models?.length ?? 0) === 1 ? "" : "s"} offered
                {:else}
                  Could not connect: {result.error}
                {/if}
              </p>
            {/if}

            {#if editing === connection.id}
              <div class="grid gap-3 rounded-xl border border-line bg-surface-2/50 p-4 sm:grid-cols-2">
                <TextInput label="Name" bind:value={edit.name} />
                <div>
                  <TextInput
                    label="Default model"
                    list={`models-${connection.id}`}
                    placeholder={presetOf(connection)?.default_model || 'Test lists the models it offers'}
                    bind:value={edit.model}
                  />
                  <datalist id={`models-${connection.id}`}>
                    {#each result?.models ?? [] as model (model)}<option value={model}></option>{/each}
                  </datalist>
                </div>
                {#if needsUrl(connection.preset)}
                  <TextInput label="Server URL" placeholder={presetOf(connection)?.base_url} bind:value={edit.baseUrl} />
                {/if}
                {#if connection.requires_key || connection.accepts_key}
                  <div class="flex flex-col gap-1.5">
                    <TextInput
                      label="API key"
                      type="password"
                      autocomplete="off"
                      placeholder={connection.has_key ? 'Replace the saved key' : 'Paste your key'}
                      bind:value={edit.key}
                    />
                    {#if connection.has_key}
                      <button type="button" onclick={() => removeKey(connection)} class="self-start text-xs text-muted hover:text-danger-text">
                        Remove saved key
                      </button>
                    {/if}
                  </div>
                {/if}
                <p class="text-xs text-subtle sm:col-span-2">{help[connection.preset] ?? ''}</p>
                <div class="flex gap-2 sm:col-span-2">
                  <Button size="sm" loading={saving} onclick={() => saveEdit(connection)}>Save</Button>
                  <Button variant="ghost" size="sm" onclick={() => (editing = null)}>Cancel</Button>
                </div>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}

    {#if adding}
      {@const preset = adding}
      <form onsubmit={add} class="flex flex-col gap-4 rounded-xl border border-accent-line bg-accent-soft/40 p-4">
        <div class="flex items-center gap-2">
          <p class="text-sm font-semibold text-fg">Add {preset.label}</p>
          {#if preset.disclosure}
            <Badge tone="info">Sends questions and excerpts to {preset.label}</Badge>
          {:else}
            <Badge tone="success">Nothing leaves this computer</Badge>
          {/if}
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <TextInput label="Name" placeholder={preset.label} bind:value={form.name} />
          <TextInput label="Default model" placeholder={preset.default_model || 'e.g. gpt-5-mini'} bind:value={form.model} />
          {#if needsUrl(preset.name)}
            <TextInput label="Server URL" placeholder={preset.base_url || 'http://127.0.0.1:8000/v1'} bind:value={form.baseUrl} />
          {/if}
          {#if preset.requires_key || preset.accepts_key}
            <TextInput label="API key" type="password" autocomplete="off" placeholder="Paste your key" bind:value={form.key} />
          {/if}
        </div>
        <p class="text-xs text-subtle">{help[preset.name] ?? ''} Keys go to your system keychain, never into the app's files.</p>
        <div class="flex gap-2">
          <Button type="submit" size="sm" loading={saving}>Add connection</Button>
          <Button variant="ghost" size="sm" onclick={() => (adding = null)}>Cancel</Button>
        </div>
      </form>
    {:else}
      <div>
        <p class="mb-2 text-[13px] font-medium text-fg-soft">Add a connection</p>
        <div class="flex flex-wrap gap-2">
          {#each addable as preset (preset.name)}
            <button
              type="button"
              onclick={() => startAdd(preset)}
              class="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-[13px] font-medium text-fg-soft shadow-card transition-all hover:-translate-y-px hover:border-accent-line hover:text-fg"
            >
              <Icon name={preset.disclosure ? 'globe' : 'plug'} class="h-3.5 w-3.5 text-subtle" />
              {preset.label.replace(' OpenAI-compatible endpoint', '')}
            </button>
          {/each}
        </div>
      </div>
    {/if}
  </div>
</Card>
