<script lang="ts">
  import { untrack } from 'svelte';
  import { api } from '$lib/api/client';
  import type { components } from '$lib/api/schema';
  import Button from '$lib/components/Button.svelte';

  let { courseId }: { courseId: string } = $props();
  type Learning = components['schemas']['LearningView'];
  type SuiteState = components['schemas']['SuiteState'];
  type Method = NonNullable<components['schemas']['CoreMemory']['preferred_method']>;
  let memory = $state<Learning | null>(null);
  let detail = $state<SuiteState | null>(null);
  let error = $state('');
  let busy = $state(false);
  const methods = [
    ['step_by_step', 'Step by step'], ['worked_example', 'Worked examples'],
    ['analogy', 'Analogies'], ['visual_structure', 'Diagrams and comparisons']
  ] as const;
  $effect(() => {
    const currentCourse = courseId;
    untrack(() => { memory = null; detail = null; void load(currentCourse); });
  });

  async function load(currentCourse = courseId) {
    error = '';
    try {
      const result = await api.GET('/courses/{course_id}/learning', { params: { path: { course_id: currentCourse } } });
      if (result.error || !result.data) throw result.error;
      if (currentCourse === courseId) memory = result.data;
    } catch { if (currentCourse === courseId) error = 'Could not load memories. Try refreshing.'; }
  }

  async function perform(action: () => Promise<unknown>) {
    if (busy) return;
    busy = true;
    error = '';
    try { await action(); await load(); }
    catch { error = 'This change was not saved. Try again.'; }
    finally { busy = false; }
  }

  async function inspect(runId: string) {
    const result = await api.GET('/courses/{course_id}/practice/runs/{run_id}', { params: { path: { course_id: courseId, run_id: runId } } });
    if (result.error || !result.data) throw result.error;
    detail = result.data;
  }

  function evidenceText(record: Record<string, unknown>): string {
    const sources = Array.isArray(record.sources) ? record.sources : [];
    return sources.map((source) => `${source.filename ?? 'Removed source'} · ${source.label ?? ''}: ${source.text ?? ''}`).join('\n');
  }
</script>

<div class="flex flex-col gap-6 pb-8">
  <div class="flex items-start justify-between gap-3">
    <div><h2 class="font-display text-xl text-fg">Memory</h2><p class="mt-1 text-sm text-muted">The tutor adapts in the background. These records show what it has observed and what it is still checking.</p></div>
    <Button variant="secondary" onclick={() => load()}>Refresh</Button>
  </div>
  {#if error}<p role="alert" class="text-sm text-danger-text">{error}</p>{/if}
  {#if memory}
    <section class="rounded-xl border border-line p-4">
      <h3 class="font-semibold text-fg">CORE memory · across all courses</h3>
      <label class="mt-3 flex flex-wrap items-center gap-3 text-sm text-muted">Preferred teaching approach
        <select aria-label="Preferred teaching approach" disabled={busy} value={memory.core.preferred_method ?? ''} class="rounded-lg border border-line bg-surface px-2 py-1.5 text-fg"
          onchange={(event) => perform(async () => {
            const result = await api.PUT('/learning/core', { body: { preferred_method: (event.currentTarget.value || null) as Method | null } });
            if (result.error) throw result.error;
          })}>
          <option value="">Adapt from observations</option>
          {#each methods as [value, label]}<option {value}>{label}</option>{/each}
        </select>
      </label>
      <p class="mt-2 text-xs text-muted">A successful attempt after an approach is a useful observation, not proof that the approach caused it.</p>
      {#each memory.core.methods as method}
        <details class="mt-3 rounded-lg bg-surface-2 p-3">
          <summary class="cursor-pointer text-sm text-fg">{methods.find(([id]) => id === method.method)?.[1]} · {method.successes}/{method.checks} fresh checks · {method.courses} course(s)</summary>
          {#each method.evidence as record}
            <p class="mt-2 text-xs text-fg">{String(record.question)} → {String(record.selected)}</p>
            <p class="text-xs text-muted">{record.key === null ? 'Excluded from assessment' : record.selected === record.key ? 'Matched the current key' : 'Missed the current key'}{record.helped ? ' · Used help' : ''}{!record.fresh ? ' · Previously revealed' : ''}</p>
            {#if record.teaching_context && typeof record.teaching_context === 'object' && 'excerpt' in record.teaching_context}
              <p class="mt-1 whitespace-pre-wrap text-xs text-muted">Prior teaching: {String(record.teaching_context.excerpt)}</p>
            {/if}
            <pre class="mt-1 whitespace-pre-wrap font-sans text-xs text-muted">{evidenceText(record)}</pre>
          {/each}
          <button class="mt-2 text-xs text-muted hover:underline" disabled={busy} onclick={() => perform(async () => { const r = await api.DELETE('/learning/core/methods/{method}', { params: { path: { method: method.method } } }); if (r.error) throw r.error; })}>Forget these method observations</button>
        </details>
      {/each}
    </section>
    <section class="rounded-xl border border-line p-4">
      <h3 class="font-semibold text-fg">COURSE memory · demonstrated capabilities</h3>
      <p class="mt-1 text-xs text-muted">Scores are estimates supported by practice. Unchecked capabilities are unknown. Repeating revealed questions does not establish proficiency.</p>
      {#if !memory.targets.length}<p class="mt-3 text-sm text-muted">No recorded practice yet.</p>{/if}
      {#each memory.targets as target}
        <details class="mt-3 rounded-lg bg-surface-2 p-3">
          <summary class="cursor-pointer text-sm text-fg">{target.topic} · {target.capability} · {target.proficiency === null ? 'Unknown' : `${target.proficiency}/100`}</summary>
          <p class="mt-2 text-xs text-muted">{target.independent_items} independent questions · {target.observations} observations · checked {target.last_checked ? new Date(target.last_checked).toLocaleDateString() : 'not yet'}</p>
          {#each target.evidence as record}
            <p class="mt-3 text-sm text-fg">{String(record.question)} → {String(record.selected)}</p>
            <p class="text-xs text-muted">{record.correct === null ? 'Excluded from assessment' : record.correct ? 'Matched the current key' : 'Missed the current key'} · {record.fresh ? 'Fresh question' : 'Previously revealed question'}{record.helped ? ' · Used help' : ''}</p>
            <pre class="mt-1 whitespace-pre-wrap font-sans text-xs text-muted">{evidenceText(record)}</pre>
          {/each}
          <button class="mt-3 text-xs text-muted hover:underline" disabled={busy} onclick={() => perform(async () => { const r = await api.POST('/courses/{course_id}/learning/forget', { params: { path: { course_id: courseId } }, body: { topic: target.topic, capability: target.capability } }); if (r.error) throw r.error; })}>Forget this capability memory and its experiments</button>
        </details>
      {/each}
    </section>
    <section class="rounded-xl border border-line p-4">
      <h3 class="font-semibold text-fg">Experiment docket</h3>
      <p class="mt-1 text-xs text-muted">Conversation can suggest a check. It cannot establish a capability score.</p>
      {#if !memory.experiments.length}<p class="mt-3 text-sm text-muted">No tentative checks.</p>{/if}
      {#each memory.experiments as experiment}
        <details class="mt-3 rounded-lg bg-surface-2 p-3">
          <summary class="cursor-pointer text-sm text-fg">{experiment.topic} · {experiment.status}</summary>
          <p class="mt-2 text-sm text-muted">{experiment.hypothesis}</p><p class="mt-2 text-sm text-fg">Proposed check: {experiment.proposed_check}</p>
          <p class="mt-2 text-xs text-muted">Student said: {String(experiment.evidence.student_quote)} · {experiment.checks} checks · expires {new Date(experiment.expires_at).toLocaleDateString()}</p>
          <pre class="mt-1 whitespace-pre-wrap font-sans text-xs text-muted">{evidenceText(experiment.evidence)}</pre>
        </details>
      {/each}
    </section>
    <section class="rounded-xl border border-line p-4">
      <h3 class="font-semibold text-fg">Complete test sessions</h3>
      <p class="mt-1 text-xs text-muted">Deleting a session keeps its distilled learning observations. Use Forget above to remove a memory.</p>
      {#each memory.runs as run}
        <div class="mt-3 flex flex-wrap items-center gap-3 text-sm">
          <button class="text-accent-text hover:underline" onclick={() => perform(() => inspect(run.run_id))}>{new Date(run.created_at).toLocaleString()} · {run.results.filter((r) => r === true).length}/{run.results.filter((r) => r !== null).length}</button>
          <button class="text-xs text-muted hover:underline" disabled={busy} onclick={() => perform(async () => { const r = await api.DELETE('/courses/{course_id}/practice/runs/{run_id}', { params: { path: { course_id: courseId, run_id: run.run_id } } }); if (r.error) throw r.error; if (detail?.latest_run?.run_id === run.run_id) detail = null; })}>Delete session</button>
        </div>
      {/each}
      {#if detail?.latest_run}
        <div class="mt-4 border-t border-line pt-3"><h4 class="font-medium text-fg">{detail.suite.title}</h4>
          <details class="mt-2 text-xs text-muted"><summary class="cursor-pointer">Sources for this test</summary>
            {#each detail.suite.evidence as source}<p class="mt-2 font-medium">{String(source.filename ?? 'Removed source')} · {String(source.label ?? '')}</p><p class="whitespace-pre-wrap">{String(source.text ?? '')}</p>{/each}
          </details>
          {#each detail.suite.questions as question, index}
            {@const written = detail.latest_run.answers[index]}
            <div class="mt-4 text-sm">
              <p class="text-fg">{index + 1}. {question.prompt}</p>
              {#if question.format === 'short_answer'}
                <p class="whitespace-pre-wrap text-muted">Answered: {typeof written === 'string' ? written : ''}</p>
                {#if question.expected}<p class="whitespace-pre-wrap text-muted">Expected: {question.expected}</p>{/if}
                {#if detail.latest_run.results[index] === null}
                  <p class="mt-2 text-xs text-muted">Excluded from scoring.</p>
                {:else}
                  <button type="button" class="mt-2 text-xs text-muted hover:underline" disabled={busy} onclick={() => {
                    const suiteId = detail!.suite.suite_id;
                    const runId = detail!.latest_run!.run_id;
                    void perform(async () => { const r = await api.PATCH('/courses/{course_id}/practice/{suite_id}/questions/{index}', { params: { path: { course_id: courseId, suite_id: suiteId, index } }, body: { answer: null, reason: 'Student reviewed the short answer in Memory.' } }); if (r.error) throw r.error; await inspect(runId); });
                  }}>Exclude disputed question</button>
                {/if}
              {:else}
                <p class="text-muted">Answered: {(question.options ?? [])[typeof written === 'number' ? written : -1] ?? ''}</p>
                <label class="mt-2 flex flex-wrap gap-2 text-xs text-muted">Review the answer key
                  <select aria-label={`Answer key for question ${index + 1}`} disabled={busy} value={detail.latest_run.correct_answers[index] ?? -1} class="rounded border border-line bg-surface p-1 text-fg" onchange={(event) => {
                    const answer = Number(event.currentTarget.value);
                    const suiteId = detail!.suite.suite_id;
                    const runId = detail!.latest_run!.run_id;
                    void perform(async () => { const r = await api.PATCH('/courses/{course_id}/practice/{suite_id}/questions/{index}', { params: { path: { course_id: courseId, suite_id: suiteId, index } }, body: { answer: answer < 0 ? null : answer, reason: 'Student reviewed the key in Memory.' } }); if (r.error) throw r.error; await inspect(runId); });
                  }}>
                    <option value={-1}>Exclude disputed question</option>{#each question.options ?? [] as option, optionIndex}<option value={optionIndex}>{option}</option>{/each}
                  </select>
                </label>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    </section>
  {:else}<p class="text-sm text-muted">Loading memories…</p>{/if}
</div>
