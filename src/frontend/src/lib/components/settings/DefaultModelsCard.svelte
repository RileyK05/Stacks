<script lang="ts">
  import { api } from '$lib/api/client';
  import type { components } from '$lib/api/schema';
  import Card from '$lib/components/Card.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import ModelPicker, { type ModelChoice } from '$lib/components/ModelPicker.svelte';
  import { toast } from '$lib/stores/toast.svelte';

  type ProvidersView = components['schemas']['ProvidersView'];
  type ModelOption = components['schemas']['ModelOption'];
  type TaskClass = 'interactive' | 'background' | 'bigger';

  interface Props {
    overview: ProvidersView;
    options: ModelOption[];
    onchanged: (view: ProvidersView) => void;
  }

  let { overview, options, onchanged }: Props = $props();
  let error = $state<unknown>(null);

  const rows: { id: TaskClass; title: string; description: string }[] = [
    {
      id: 'interactive',
      title: 'Answers',
      description: 'Answers your questions while you wait. Each chat can pick another model.'
    },
    {
      id: 'background',
      title: 'Background work',
      description: 'Scanned PDFs and chat summaries: slow jobs that run while you do something else.'
    },
    {
      id: 'bigger',
      title: 'Bigger model',
      description: 'Used only when you press "Ask a bigger model" under an answer. Never automatic.'
    }
  ];

  function labelFor(model: string | null | undefined): string {
    if (!model) return '';
    return options.find((o) => o.is_local && o.model === model)?.label ?? model;
  }

  function nullOption(id: TaskClass) {
    const answers = labelFor(overview.resolved.interactive?.model);
    if (id === 'background') {
      return {
        label: 'Same as answers',
        description: answers || 'Uses the answers model',
        current: answers ? `Same as answers (${answers})` : 'Same as answers'
      };
    }
    if (id === 'bigger') {
      return { label: 'None', description: 'Hide the "Ask a bigger model" button', current: 'None' };
    }
    return null;
  }

  function choiceOf(id: TaskClass): ModelChoice | null {
    const saved = overview.choices[id];
    if (!saved) return null;
    return { connection: saved.connection ?? saved.preset ?? 'local', model: saved.model ?? null };
  }

  async function change(id: TaskClass, choice: ModelChoice | null) {
    error = null;
    try {
      const result =
        choice === null
          ? await api.DELETE('/settings/providers/{task_class}', { params: { path: { task_class: id } } })
          : await api.PUT('/settings/providers/{task_class}', {
              params: { path: { task_class: id } },
              body: { connection: choice.connection, model: choice.model ?? null }
            });
      if (result.error || !result.data) throw result.error ?? new Error('empty response');
      onchanged(result.data);
      toast('Saved.');
    } catch (caught) {
      error = caught;
    }
  }
</script>

<Card title="Default models" description="Which model does which job. Local models are free and private; connections are optional.">
  <div class="flex flex-col gap-4">
    {#if error}<ErrorBanner {error} />{/if}
    <ul class="divide-y divide-line">
      {#each rows as row (row.id)}
        {@const resolved = overview.resolved[row.id]}
        <li class="grid gap-3 py-3.5 first:pt-0 last:pb-0 sm:grid-cols-[minmax(0,1fr)_minmax(0,18rem)] sm:items-center">
          <div class="min-w-0">
            <p class="text-sm font-medium text-fg">{row.title}</p>
            <p class="mt-0.5 text-xs leading-relaxed text-subtle">{row.description}</p>
            {#if row.id === 'interactive' && !resolved}
              <p class="mt-1 text-xs text-warning-text">Nothing can answer yet: download a local model below or add a connection.</p>
            {/if}
          </div>
          <ModelPicker
            {options}
            connections={overview.connections}
            choice={choiceOf(row.id)}
            nullOption={nullOption(row.id)}
            block
            onchange={(choice) => change(row.id, choice)}
          />
        </li>
      {/each}
    </ul>
  </div>
</Card>
