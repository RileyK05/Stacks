<script lang="ts">
  import ConfirmHost from '$lib/components/ConfirmHost.svelte';
  import DebugHost from '$lib/components/DebugHost.svelte';
  import Toaster from '$lib/components/Toaster.svelte';
  import '$lib/stores/theme.svelte';
  import '../app.css';

  let { children } = $props();
</script>

{@render children()}
<Toaster />
<ConfirmHost />
<DebugHost />
