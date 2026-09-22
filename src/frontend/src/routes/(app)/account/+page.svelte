<script lang="ts">
  import { api } from '$lib/api/client';
  import Button from '$lib/components/Button.svelte';
  import Card from '$lib/components/Card.svelte';
  import ErrorBanner from '$lib/components/ErrorBanner.svelte';
  import TextInput from '$lib/components/TextInput.svelte';
  import { currentUser, refreshUser } from '$lib/stores/auth.svelte';
  import { toast } from '$lib/stores/toast.svelte';

  let user = $derived(currentUser());

  let code = $state('');
  let verifyToken = $state('');
  let busy = $state(false);
  let error = $state<unknown>(null);

  async function run(action: () => Promise<void>) {
    busy = true;
    error = null;
    try {
      await action();
    } catch (caught) {
      error = caught;
    } finally {
      busy = false;
    }
  }

  async function redeem() {
    await run(async () => {
      const { error: err } = await api.POST('/auth/support-code/redeem', {
        body: { code }
      });
      if (err) throw err;
      toast('Support code redeemed — welcome to the paid tier.');
      code = '';
      await refreshUser();
    });
  }

  async function requestVerification() {
    await run(async () => {
      const { error: err } = await api.POST('/auth/verify-email/request');
      if (err) throw err;
      toast('Verification email queued. Paste the token below once it arrives.');
    });
  }

  async function confirmVerification() {
    await run(async () => {
      const { error: err } = await api.POST('/auth/verify-email/{token}', {
        params: { path: { token: verifyToken } }
      });
      if (err) throw err;
      toast('Email verified.');
      verifyToken = '';
      await refreshUser();
    });
  }
</script>

<h1 class="mb-6 text-2xl font-bold text-slate-900">Account</h1>

{#if user}
  <div class="flex flex-col gap-6">
    <Card title="Profile">
      <dl class="grid gap-2 text-sm sm:grid-cols-2">
        <div>
          <dt class="text-slate-500">Name</dt>
          <dd class="font-medium text-slate-900">{user.name}</dd>
        </div>
        <div>
          <dt class="text-slate-500">Email</dt>
          <dd class="font-medium text-slate-900">
            {user.email ?? '—'}
            {#if user.email_verified}
              <span class="ml-1 text-green-700">(verified)</span>
            {:else}
              <span class="ml-1 text-amber-600">(not verified)</span>
            {/if}
          </dd>
        </div>
        <div>
          <dt class="text-slate-500">Tier</dt>
          <dd class="font-medium text-slate-900">{user.tier}</dd>
        </div>
        <div>
          <dt class="text-slate-500">Member since</dt>
          <dd class="font-medium text-slate-900">
            {user.created_at ? new Date(user.created_at).toLocaleDateString() : '—'}
          </dd>
        </div>
      </dl>
    </Card>

    {#if error}<ErrorBanner {error} />{/if}

    <Card title="Redeem a support code">
      <form
        onsubmit={(e) => {
          e.preventDefault();
          redeem();
        }}
        class="flex flex-col gap-3 sm:flex-row sm:items-end"
      >
        <div class="flex-1">
          <TextInput
            label="Code"
            bind:value={code}
            placeholder="XXXX-XXXX-XXXX-XXXX"
            required
          />
        </div>
        <Button type="submit" loading={busy}>Redeem</Button>
      </form>
    </Card>

    <Card title="Verify email">
      <p class="mb-3 text-sm text-slate-500">
        Uploading sources and creating courses require a verified email address.
      </p>
      <div class="flex flex-col gap-3">
        <Button variant="secondary" onclick={requestVerification} disabled={busy}>
          Send verification email
        </Button>
        <form
          onsubmit={(e) => {
            e.preventDefault();
            confirmVerification();
          }}
          class="flex flex-col gap-3 sm:flex-row sm:items-end"
        >
          <div class="flex-1">
            <TextInput label="Verification token" bind:value={verifyToken} required />
          </div>
          <Button type="submit" loading={busy}>Verify</Button>
        </form>
      </div>
    </Card>

    <Card title="Delete account">
      <p class="text-sm text-slate-500">
        Account deletion is not yet exposed in this interface. When it is, it will
        enter a 7-day grace period before anything is destroyed, and your course
        memories will survive as the keepsake record described in the project
        rules. Contact the operator to request deletion.
      </p>
    </Card>
  </div>
{/if}
