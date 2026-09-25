<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api/client';
  import type { components, paths } from '$lib/api/schema';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import LocalModelCard from '$lib/components/LocalModelCard.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import TextInput from '$lib/components/TextInput.svelte';
  import ConnectionsCard from '$lib/components/settings/ConnectionsCard.svelte';
  import DefaultModelsCard from '$lib/components/settings/DefaultModelsCard.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { formatBytes } from '$lib/utils/format';

  type ProvidersView = components['schemas']['ProvidersView'];
  type ModelOption = components['schemas']['ModelOption'];
  type UsageView =
    paths['/settings/usage']['get']['responses'][200]['content']['application/json'];
  type DataFolderView =
    paths['/settings/data']['get']['responses'][200]['content']['application/json'];

  let overview = $state<ProvidersView | null>(null);
  let options = $state<ModelOption[]>([]);
  let usage = $state<UsageView | null>(null);
  let dataFolder = $state<DataFolderView | null>(null);
  let appVersion = $state<string | null>(null);
  let loading = $state(true);
  let error = $state<unknown>(null);
  let actionError = $state<unknown>(null);
  let budgetDraft = $state('');

  onMount(() => {
    load().catch((err) => {
      error = err;
      loading = false;
    });
  });

  async function load() {
    loading = true;
    try {
      const [usageRes, dataRes, healthRes] = await Promise.all([
        api.GET('/settings/usage'),
        api.GET('/settings/data'),
        api.GET('/health'),
        refreshModels()
      ]);
      dataFolder = dataRes.data ?? null;
      appVersion = healthRes.data?.version ?? null;
      usage = usageRes.data ?? null;
      budgetDraft = usage?.monthly_cloud_token_budget?.toString() ?? '';
    } finally {
      loading = false;
    }
  }

  /** Connections, defaults and the picker's options change together. */
  async function refreshModels() {
    const [providersRes, optionsRes] = await Promise.all([
      api.GET('/settings/providers'),
      api.GET('/settings/model-options')
    ]);
    if (providersRes.error || !providersRes.data) {
      throw providersRes.error ?? new Error('empty response');
    }
    overview = providersRes.data;
    options = optionsRes.data ?? [];
  }

  async function revealData(path: string) {
    const { error: err } = await api.POST('/settings/reveal', { body: { path } });
    if (err) toast('Could not open the folder.', 'error');
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

<PageHeader
  title="Settings"
  description="Choose which models answer your questions. Local models run on this computer; connections to other providers are optional."
/>

{#if error}
  <ErrorBanner {error} />
{:else if loading || !overview}
  <div class="flex flex-col gap-6">
    <Skeleton class="h-56 w-full rounded-2xl" />
    <Skeleton class="h-64 w-full rounded-2xl" />
    <Skeleton class="h-40 w-full rounded-2xl" />
  </div>
{:else}
  <div class="flex flex-col gap-6">
    {#if actionError}<ErrorBanner error={actionError} />{/if}

    <DefaultModelsCard {overview} {options} onchanged={(view) => (overview = view)} />

    <LocalModelCard onchange={() => void refreshModels()} />

    <ConnectionsCard presets={overview.presets} connections={overview.connections} onchanged={refreshModels} />

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
              <TextInput label="Monthly cloud budget (tokens)" inputmode="numeric" placeholder="No limit" bind:value={budgetDraft} />
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
