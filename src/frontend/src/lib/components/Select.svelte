<script lang="ts" generics="T extends string">
  import Icon from './Icon.svelte';

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

<div class="flex flex-col gap-1.5">
  {#if label}
    <label for={selectId} class="text-[13px] font-medium text-fg-soft">{label}</label>
  {/if}
  <div class="relative">
    <select
      id={selectId}
      bind:value
      {disabled}
      class="h-10 w-full appearance-none rounded-lg border border-line-strong bg-surface pl-3 pr-9 text-sm text-fg shadow-card transition-[border-color,box-shadow] hover:border-subtle focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent/15 disabled:opacity-60"
    >
      {#each options as option (option.value)}
        <option value={option.value}>{option.label}</option>
      {/each}
    </select>
    <Icon
      name="chevron-down"
      class="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle"
    />
  </div>
</div>
