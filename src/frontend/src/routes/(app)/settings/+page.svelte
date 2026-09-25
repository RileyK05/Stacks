<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api/client';
  import type { paths } from '$lib/api/schema';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import LocalModelCard from '$lib/components/LocalModelCard.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import TextInput from '$lib/components/TextInput.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { formatBytes } from '$lib/utils/format';

  type ProvidersView =
    paths['/settings/providers']['get']['responses'][200]['content']['application/json'];
  type Preset = ProvidersView['presets'][number];
  type TaskClass = 'interactive' | 'background' | 'bigger';
  type UsageView =
    paths['/settings/usage']['get']['responses'][200]['content']['application/json'];
  type ConnectionTest =
    paths['/settings/providers/{task_class}/test']['post']['responses'][200]['content']['application/json'];

  interface Draft {
    preset: string;
    model: string;
    baseUrl: string;
  }

  const classes: { id: TaskClass; title: string; description: string }[] = [
    {
      id: 'interactive',
      title: 'Model for answers',
      description: 'Answers your questions while you wait. A small local model is fast and free.'
    },
    {
      id: 'background',
      title: 'Model for background work',
      description:
        'Reads scanned PDFs and other slow jobs that run while you do something else. Uses the answers model unless you pick one here.'
    },
    {
      id: 'bigger',
      title: 'Bigger model',
      description:
        'Used only when you press “Ask a bigger model” under an answer: a larger local model or a cloud provider. Never used automatically.'
    }
  ];

  let overview = $state<ProvidersView | null>(null);
  let usage = $state<UsageView | null>(null);
  let loading = $state(true);
  let error = $state<unknown>(null);
  let actionError = $state<unknown>(null);
  let drafts = $state<Record<TaskClass, Draft>>({
    interactive: { preset: 'local', model: '', baseUrl: '' },
    background: { preset: '', model: '', baseUrl: '' },
    bigger: { preset: '', model: '', baseUrl: '' }
  });
  let keyDrafts = $state<Record<string, string>>({});
  let saving = $state<TaskClass | null>(null);
  let testing = $state<TaskClass | null>(null);
  let tests = $state<Partial<Record<TaskClass, ConnectionTest>>>({});
  let freeOnly = $state(true);
  let budgetDraft = $state('');
  type DataFolderView =
    paths['/settings/data']['get']['responses'][200]['content']['application/json'];
  let dataFolder = $state<DataFolderView | null>(null);
  let appVersion = $state<string | null>(null);

  const DISCLOSED_KEY = 'stacks_disclosed_providers';

  onMount(() => {
    load().catch((err) => {
      error = err;
      loading = false;
    });
  });

  async function load() {
    loading = true;
    try {
      const [providersRes, usageRes, dataRes, healthRes] = await Promise.all([
        api.GET('/settings/providers'),
        api.GET('/settings/usage'),
        api.GET('/settings/data'),
        api.GET('/health')
      ]);
      dataFolder = dataRes.data ?? null;
      appVersion = healthRes.data?.version ?? null;
      if (providersRes.error || !providersRes.data) {
        throw providersRes.error ?? new Error('empty response');
      }
      applyOverview(providersRes.data);
      usage = usageRes.data ?? null;
      budgetDraft = usage?.monthly_cloud_token_budget?.toString() ?? '';
    } finally {
      loading = false;
    }
  }

  function applyOverview(view: ProvidersView) {
    overview = view;
    for (const { id } of classes) {
      const choice = view.choices[id];
      drafts[id] = {
        preset: choice?.preset ?? (id === 'interactive' ? 'local' : ''),
        model: choice?.model ?? '',
        baseUrl: choice?.base_url ?? ''
      };
    }
  }

  async function revealData(path: string) {
    const { error: err } = await api.POST('/settings/reveal', { body: { path } });
    if (err) toast('Could not open the folder.', 'error');
  }

  function preset(name: string): Preset | undefined {
    return overview?.presets.find((candidate) => candidate.name === name);
  }

  function alreadyDisclosed(name: string): boolean {
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

  async function save(cls: TaskClass) {
    const draft = drafts[cls];
    const chosen = preset(draft.preset);
    actionError = null;
    if (!draft.preset) {
      await clear(cls);
      return;
    }
    if (chosen?.disclosure && !alreadyDisclosed(chosen.name)) {
      const ok = await confirmDialog({
        title: `Use ${chosen.label}?`,
        message:
          'Your questions and the course excerpts used to answer them will be sent to this provider. ' +
          'Everything else stays on this computer.',
        confirmLabel: 'Use it'
      });
      if (!ok) return;
      rememberDisclosed(chosen.name);
    }
    saving = cls;
    try {
      const { data, error: err } = await api.PUT('/settings/providers/{task_class}', {
        params: { path: { task_class: cls } },
        body: {
          preset: draft.preset,
          model: draft.model.trim() || null,
          base_url: draft.baseUrl.trim() || null
        }
      });
      if (err || !data) throw err ?? new Error('empty response');
      applyOverview(data);
      toast('Saved.');
    } catch (caught) {
      actionError = caught;
    } finally {
      saving = null;
    }
  }

  async function clear(cls: TaskClass) {
    saving = cls;
    try {
      const { data, error: err } = await api.DELETE('/settings/providers/{task_class}', {
        params: { path: { task_class: cls } }
      });
      if (err || !data) throw err ?? new Error('empty response');
      applyOverview(data);
    } catch (caught) {
      actionError = caught;
    } finally {
      saving = null;
    }
  }

  async function saveKey(name: string) {
    const key = keyDrafts[name]?.trim();
    if (!key) return;
    actionError = null;
    try {
      const { error: err } = await api.PUT('/settings/keys/{preset}', {
        params: { path: { preset: name } },
        body: { key }
      });
      if (err) throw err;
      keyDrafts[name] = '';
      toast('Key saved to your system keychain.');
      await load();
    } catch (caught) {
      actionError = caught;
    }
  }

  async function removeKey(name: string) {
    if (!(await confirmDialog({
      title: 'Remove this key?',
      message: 'It is deleted from your system keychain. You can add it again any time.',
      confirmLabel: 'Remove',
      danger: true
    }))) return;
    try {
      const { error: err } = await api.DELETE('/settings/keys/{preset}', {
        params: { path: { preset: name } }
      });
      if (err) throw err;
      await load();
    } catch (caught) {
      actionError = caught;
    }
  }

  async function test(cls: TaskClass) {
    testing = cls;
    try {
      const { data, error: err } = await api.POST('/settings/providers/{task_class}/test', {
        params: { path: { task_class: cls } }
      });
      if (err || !data) throw err ?? new Error('empty response');
      tests[cls] = data;
    } catch (caught) {
      actionError = caught;
    } finally {
      testing = null;
    }
  }

  function modelOptions(cls: TaskClass): string[] {
    const models = tests[cls]?.models ?? [];
    return drafts[cls].preset === 'openrouter' && freeOnly
      ? models.filter((model) => model.endsWith(':free'))
      : models;
  }

  async function saveBudget(event: SubmitEvent) {
    event.preventDefault();
    const trimmed = budgetDraft.trim();
    const budget = trimmed === '' ? null : Number(trimmed);
    if (budget !== null && (!Number.isInteger(budget) || budget < 1)) {
      actionError = new Error('The budget must be a whole number of tokens, or empty for none.');
      return;
    }
    try {
      const { data, error: err } = await api.PUT('/settings/usage/budget', {
        body: { monthly_cloud_token_budget: budget }
      });
      if (err || !data) throw err ?? new Error('empty response');
      usage = data;
      toast(budget === null ? 'Budget removed.' : 'Budget saved.');
    } catch (caught) {
      actionError = caught;
    }
  }

  function tokens(count: number): string {
    return count >= 1000 ? `${(count / 1000).toFixed(count >= 100_000 ? 0 : 1)}k` : `${count}`;
  }
</script>

{#snippet keyField(p: Preset)}
  <div class="rounded-xl border border-line bg-surface-2/50 p-4">
    <div class="flex items-center gap-2">
      <Icon name="key" class="h-4 w-4 text-subtle" />
      <p class="text-sm font-medium text-fg">{p.label} API key</p>
      {#if p.has_key}<Badge tone="success" dot>Saved</Badge>{/if}
    </div>
    <p class="mt-1 text-xs text-subtle">
      Stored in your system keychain, never in the app's files.
      {#if p.name === 'openrouter'}
        Create one at openrouter.ai → Keys. Free models (<code>:free</code>) need no credit;
        a one-time $10 purchase raises their daily limit.
      {:else if p.name === 'openai'}
        Create one at platform.openai.com → API keys, and set a monthly limit under Billing → Limits.
      {/if}
    </p>
    <div class="mt-3 flex flex-col gap-2 sm:flex-row">
      <div class="flex-1">
        <TextInput
          type="password"
          autocomplete="off"
          placeholder={p.has_key ? 'Replace the saved key' : 'Paste your key'}
          bind:value={keyDrafts[p.name]}
        />
      </div>
      <Button variant="secondary" onclick={() => saveKey(p.name)} disabled={!keyDrafts[p.name]}>
        Save key
      </Button>
      {#if p.has_key}
        <Button variant="ghost" onclick={() => removeKey(p.name)}>Remove</Button>
      {/if}
    </div>
  </div>
{/snippet}

<PageHeader
  title="Settings"
  description="Choose which model answers your questions. The local model runs on this computer; cloud models are optional."
/>

{#if error}
  <ErrorBanner {error} />
{:else if loading || !overview}
  <div class="flex flex-col gap-6">
    <Skeleton class="h-64 w-full rounded-2xl" />
    <Skeleton class="h-48 w-full rounded-2xl" />
  </div>
{:else}
  <div class="flex flex-col gap-6">
    {#if actionError}<ErrorBanner error={actionError} />{/if}

    <LocalModelCard onchange={() => void load()} />

    {#each classes as cls (cls.id)}
      {@const draft = drafts[cls.id]}
      {@const chosen = preset(draft.preset)}
      {@const resolved = overview.resolved[cls.id]}
      {@const result = tests[cls.id]}
      <Card title={cls.title} description={cls.description}>
        <div class="flex flex-col gap-4">
          <div class="flex flex-wrap items-center gap-2 text-sm">
            <span class="text-muted">In use:</span>
            {#if resolved}
              <Badge tone={resolved.is_local ? 'success' : 'info'} icon="cpu">
                {resolved.model} · {resolved.is_local ? 'on this computer' : resolved.name}
              </Badge>
            {:else}
              <Badge tone={cls.id === 'bigger' ? 'neutral' : 'warning'} dot>
                {cls.id === 'bigger' ? 'Not set' : 'Nothing configured'}
              </Badge>
            {/if}
          </div>

          <div class="grid gap-2 sm:grid-cols-2">
            {#if cls.id !== 'interactive'}
              <label class={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors ${draft.preset === '' ? 'border-accent bg-accent-soft' : 'border-line hover:border-line-strong'}`}>
                <input type="radio" class="mt-1" bind:group={drafts[cls.id].preset} value="" />
                <span>
                  {#if cls.id === 'background'}
                    <span class="block text-sm font-medium text-fg">Same as answers</span>
                    <span class="block text-xs text-subtle">Use the model chosen above.</span>
                  {:else}
                    <span class="block text-sm font-medium text-fg">None</span>
                    <span class="block text-xs text-subtle">Hide the “Ask a bigger model” button.</span>
                  {/if}
                </span>
              </label>
            {/if}
            {#each overview.presets as p (p.name)}
              <label class={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors ${draft.preset === p.name ? 'border-accent bg-accent-soft' : 'border-line hover:border-line-strong'}`}>
                <input type="radio" class="mt-1" bind:group={drafts[cls.id].preset} value={p.name} />
                <span class="min-w-0">
                  <span class="flex items-center gap-2 text-sm font-medium text-fg">
                    {p.label}
                    {#if !p.disclosure}<Badge tone="success">Private</Badge>{/if}
                  </span>
                  <span class="block text-xs text-subtle">
                    {p.disclosure ? 'Sends questions and course excerpts to this provider.' : 'Nothing leaves this computer.'}
                  </span>
                </span>
              </label>
            {/each}
          </div>

          {#if chosen}
            <div class="grid gap-3 sm:grid-cols-2">
              <div>
                <TextInput
                  label="Model"
                  list={`models-${cls.id}`}
                  placeholder={chosen.default_model || 'Pick a model (Test connection lists them)'}
                  bind:value={drafts[cls.id].model}
                />
                <datalist id={`models-${cls.id}`}>
                  {#each modelOptions(cls.id) as model (model)}<option value={model}></option>{/each}
                </datalist>
              </div>
              {#if chosen.name === 'custom'}
                <TextInput
                  label="Endpoint URL"
                  placeholder="http://127.0.0.1:11434/v1"
                  bind:value={drafts[cls.id].baseUrl}
                />
              {/if}
            </div>
            {#if chosen.requires_key || chosen.name === 'custom'}
              {@render keyField(chosen)}
            {/if}
          {/if}

          <div class="flex flex-wrap items-center gap-2">
            <Button loading={saving === cls.id} onclick={() => save(cls.id)}>Save</Button>
            <Button variant="secondary" loading={testing === cls.id} onclick={() => test(cls.id)} disabled={!resolved}>
              Test connection
            </Button>
            {#if draft.preset === 'openrouter'}
              <label class="ml-1 inline-flex items-center gap-2 text-sm text-muted">
                <input type="checkbox" bind:checked={freeOnly} /> Free models only
              </label>
            {/if}
          </div>

          {#if result}
            {#if result.ok}
              <p class="text-sm text-success-text">
                Connected · {modelOptions(cls.id).length} model{modelOptions(cls.id).length === 1 ? '' : 's'} available
                {#if modelOptions(cls.id).length > 0}— start typing in the Model field to pick one.{/if}
              </p>
            {:else}
              <p class="text-sm text-danger-text">Could not connect: {result.error}</p>
              {#if draft.preset === 'local'}
                <p class="text-xs text-subtle">
                  The local model isn't running yet — download one above and press Use,
                  or point "Custom" at Ollama or LM Studio.
                </p>
              {/if}
            {/if}
          {/if}
        </div>
      </Card>
    {/each}

    {#if usage}
      <Card
        title="Usage"
        description="Tokens used this month. Local-model calls are free; cloud calls count toward the optional budget."
      >
        <div class="flex flex-col gap-5">
          <div class="flex flex-wrap items-end gap-6">
            <div>
              <p class="text-xs uppercase tracking-wide text-subtle">Cloud tokens this month</p>
              <p class="mt-1 font-display text-2xl text-fg">
                {tokens(usage.cloud_tokens_this_month)}
                {#if usage.monthly_cloud_token_budget}
                  <span class="text-base text-subtle">/ {tokens(usage.monthly_cloud_token_budget)}</span>
                {/if}
              </p>
            </div>
            <form onsubmit={saveBudget} class="flex items-end gap-2">
              <TextInput
                label="Monthly cloud budget (tokens)"
                inputmode="numeric"
                placeholder="No limit"
                bind:value={budgetDraft}
              />
              <Button type="submit" variant="secondary">Save budget</Button>
            </form>
          </div>

          {#if usage.totals.length > 0}
            <table class="w-full text-left text-sm">
              <thead class="text-xs uppercase tracking-wide text-subtle">
                <tr>
                  <th class="pb-2 font-medium">Model</th>
                  <th class="pb-2 font-medium">Task</th>
                  <th class="pb-2 text-right font-medium">Calls</th>
                  <th class="pb-2 text-right font-medium">Tokens in / out</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-line">
                {#each usage.totals as row (`${row.provider}-${row.model}-${row.task}`)}
                  <tr>
                    <td class="py-2 text-fg">{row.model} <span class="text-subtle">· {row.provider}</span></td>
                    <td class="py-2 text-muted">{row.task.replace(/_/g, ' ')}</td>
                    <td class="py-2 text-right text-muted">{row.calls}</td>
                    <td class="py-2 text-right text-muted">{tokens(row.input_tokens)} / {tokens(row.output_tokens)}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {:else}
            <p class="text-sm text-subtle">No model calls yet this month.</p>
          {/if}
        </div>
      </Card>
    {/if}

    {#if dataFolder}
      <Card
        title="Your data"
        description="Everything the app keeps lives in one folder on this computer. Back up a single course with Export on its page."
      >
        <div class="flex flex-col gap-4">
          <div class="flex flex-wrap items-center gap-3">
            <code class="min-w-0 flex-1 truncate rounded-lg bg-surface-2 px-3 py-2 text-xs text-muted">{dataFolder.data_dir}</code>
            <Button variant="secondary" size="sm" onclick={() => dataFolder && revealData(dataFolder.data_dir)}>
              <Icon name="hard-drive" class="h-4 w-4" /> Open folder
            </Button>
          </div>
          <dl class="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            {#each [['Courses database', dataFolder.database_bytes], ['Uploaded files', dataFolder.uploads_bytes], ['Local models', dataFolder.models_bytes], ['Model runtime', dataFolder.runtime_bytes]] as [label, bytes] (label)}
              <div>
                <dt class="text-xs uppercase tracking-wide text-subtle">{label}</dt>
                <dd class="mt-0.5 text-fg">{formatBytes(Number(bytes))}</dd>
              </div>
            {/each}
          </dl>
        </div>
      </Card>
    {/if}

    {#if appVersion}
      <p class="text-center text-xs text-subtle">
        Stacks {appVersion} · MIT License ·
        <a class="underline hover:text-muted" href="https://github.com/RileyK05/Stacks">Source code</a>
      </p>
    {/if}
  </div>
{/if}
