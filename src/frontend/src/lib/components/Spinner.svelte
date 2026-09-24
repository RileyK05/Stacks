<script lang="ts">
  let { class: className = 'h-4 w-4' }: { class?: string } = $props();
</script>

<span
  class={`inline-block shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent opacity-80 ${className}`}
  aria-label="loading"
></span>
