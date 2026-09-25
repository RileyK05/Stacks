<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import type { CourseChats } from '$lib/stores/chat.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { timeAgo } from '$lib/utils/format';

  interface Props {
    chats: CourseChats;
    onselect: (conversationId: string | null) => void;
  }

  let { chats, onselect }: Props = $props();

  let editingId = $state<string | null>(null);
  let editValue = $state('');
  let menuFor = $state<string | null>(null);

  function startRename(id: string, title: string) {
    menuFor = null;
    editingId = id;
    editValue = title;
  }

  async function saveRename(event: SubmitEvent) {
    event.preventDefault();
    const id = editingId;
    editingId = null;
    if (!id || !editValue.trim()) return;
    try {
      await chats.rename(id, editValue.trim());
    } catch {
      toast('Could not rename the chat.', 'error');
    }
  }

  async function remove(id: string, title: string) {
    menuFor = null;
    const ok = await confirmDialog({
      title: 'Delete this chat?',
      message: `"${title || 'New chat'}" and its messages are deleted. Artifacts you saved from it stay in the course.`,
      confirmLabel: 'Delete chat',
      danger: true
    });
    if (!ok) return;
    try {
      await chats.remove(id);
      if (!chats.activeId) onselect(null);
    } catch {
      toast('Could not delete the chat.', 'error');
    }
  }

  function focusOnMount(node: HTMLInputElement) {
    node.focus();
    node.select();
  }

  $effect(() => {
    if (!menuFor) return;
    const close = (event: PointerEvent) => {
      if (!(event.target as Element | null)?.closest?.('[data-chat-menu]')) menuFor = null;
    };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  });
</script>

<nav class="flex min-h-0 flex-col gap-3" aria-label="Chats">
  <button
    type="button"
    onclick={() => onselect(null)}
    class={`flex items-center gap-2.5 rounded-xl border px-3 py-2.5 text-sm font-medium transition-all ${
      chats.activeId === null
        ? 'border-accent-line bg-accent-soft text-accent-text'
        : 'border-line bg-surface text-fg shadow-card hover:border-accent-line hover:shadow-lift'
    }`}
  >
    <Icon name="square-pen" class="h-4 w-4" />
    New chat
  </button>

  <div class="flex min-h-0 flex-col gap-0.5 overflow-y-auto pr-1">
    <p class="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-subtle">Chats</p>
    {#if chats.listLoading}
      {#each [0, 1, 2] as row (row)}
        <Skeleton class="mx-2 my-1.5 h-8" />
      {/each}
    {:else if chats.conversations.length === 0}
      <p class="px-2 py-2 text-[13px] leading-relaxed text-subtle">
        Your chats appear here. Each one is saved, so you can come back to it.
      </p>
    {:else}
      {#each chats.conversations as conversation (conversation.conversation_id)}
        {@const id = conversation.conversation_id}
        {@const active = chats.activeId === id}
        <div class="group relative" data-chat-menu>
          {#if editingId === id}
            <form onsubmit={saveRename} class="px-1 py-0.5">
              <input
                bind:value={editValue}
                use:focusOnMount
                maxlength={80}
                aria-label="Chat name"
                onblur={() => (editingId = null)}
                onkeydown={(e) => e.key === 'Escape' && (editingId = null)}
                class="h-9 w-full rounded-lg border border-accent bg-surface px-2.5 text-[13px] text-fg ring-3 ring-accent/15 focus:outline-none"
              />
            </form>
          {:else}
            <button
              type="button"
              onclick={() => onselect(id)}
              aria-current={active ? 'true' : undefined}
              class={`flex w-full flex-col items-start rounded-lg px-2.5 py-2 pr-8 text-left transition-colors ${
                active ? 'bg-surface text-fg shadow-card ring-1 ring-line' : 'text-muted hover:bg-surface-2 hover:text-fg'
              }`}
            >
              <span class="w-full truncate text-[13px] font-medium">{conversation.title || 'New chat'}</span>
              <span class="text-[11px] text-subtle">{timeAgo(conversation.updated_at)}</span>
            </button>
            <button
              type="button"
              aria-label="Chat actions"
              onclick={() => (menuFor = menuFor === id ? null : id)}
              class={`absolute right-1.5 top-2 rounded-md p-1 text-subtle transition-opacity hover:bg-surface-3 hover:text-fg ${
                menuFor === id || active ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus:opacity-100'
              }`}
            >
              <Icon name="ellipsis" class="h-4 w-4" />
            </button>
            {#if menuFor === id}
              <div
                class="absolute right-1 top-9 z-30 w-40 animate-rise overflow-hidden rounded-xl border border-line bg-surface py-1 shadow-lift"
                role="menu"
              >
                <button
                  type="button"
                  role="menuitem"
                  onclick={() => startRename(id, conversation.title)}
                  class="flex w-full items-center gap-2 px-3 py-2 text-[13px] text-fg-soft hover:bg-surface-2"
                >
                  <Icon name="pencil" class="h-3.5 w-3.5 text-subtle" /> Rename
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onclick={() => remove(id, conversation.title)}
                  class="flex w-full items-center gap-2 px-3 py-2 text-[13px] text-danger-text hover:bg-danger-soft"
                >
                  <Icon name="trash" class="h-3.5 w-3.5" /> Delete
                </button>
              </div>
            {/if}
          {/if}
        </div>
      {/each}
    {/if}
  </div>
</nav>
