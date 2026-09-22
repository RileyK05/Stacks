<script lang="ts" generics="T extends string">
  interface Option {
    value: T;
    label: string;
  }

  interface Props {
    label?: string;
    options: Option[];
    value?: T;
    id?: string;
    disabled?: boolean;
  }

  let {
    label,
    options,
    value = $bindable(options[0]?.value as T),
    id,
    disabled = false
  }: Props = $props();

  let selectId = $derived(id ?? label?.toLowerCase().replace(/\s+/g, '-'));
</script>

<div class="flex flex-col gap-1">
  {#if label}
    <label for={selectId} class="text-sm font-medium text-slate-700">{label}</label>
  {/if}
  <select
    id={selectId}
    bind:value
    {disabled}
    class="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
  >
    {#each options as option (option.value)}
      <option value={option.value}>{option.label}</option>
    {/each}
  </select>
</div>
