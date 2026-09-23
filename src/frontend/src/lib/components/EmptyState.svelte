<script lang="ts">
  interface Props {
    title?: string;
    message: string;
  }

  let { title, message }: Props = $props();
</script>

<div class="rounded-lg bg-white p-10 text-center shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-700">
  {#if title}<h2 class="mb-2 text-base font-semibold text-slate-900 dark:text-slate-100">{title}</h2>{/if}
  <p class="text-sm text-slate-500">{message}</p>
</div>
