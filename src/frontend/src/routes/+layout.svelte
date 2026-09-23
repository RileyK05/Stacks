<script lang="ts">
  import { onMount } from 'svelte';
  import ConfirmHost from '$lib/components/ConfirmHost.svelte';
  import DebugHost from '$lib/components/DebugHost.svelte';
  import Toaster from '$lib/components/Toaster.svelte';
  import { refreshUser } from '$lib/stores/auth.svelte';
  import '$lib/stores/theme.svelte';
  import '../app.css';

  let { children } = $props();

  onMount(() => {
    refreshUser().catch(() => {});
  });
</script>

{@render children()}
<Toaster />
<ConfirmHost />
<DebugHost />
