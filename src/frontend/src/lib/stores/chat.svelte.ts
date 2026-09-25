import { api } from '$lib/api/client';
import type { components } from '$lib/api/schema';
import { openSession, type WorkspaceSession } from '$lib/stores/workspace.svelte';

export type ConversationSummary = components['schemas']['ConversationSummaryView'];
export type ModelChoice = components['schemas']['ModelChoiceView'];
type MessageView = components['schemas']['MessageView'];
type AnswerView = components['schemas']['AnswerView'];
export type Citation = components['schemas']['CitationView'];

/** One question and its reply, as the chat shows them. */
export interface Turn {
  question: string;
  /** The stored reply (for saving its workspace items as artifacts). */
  messageId: string | null;
  /** Chat body (workspace blocks lifted out server-side); null while waiting. */
  answer: string | null;
  /** The material had nothing relevant: a real reply, not an error. */
  noMatch: boolean;
  workspace: WorkspaceSession[];
  withheld: string[];
  traceId: string | null;
  fellBackToLocal: boolean;
  bigger: boolean;
  model: string;
  cached: boolean;
  citations: Citation[];
  citationsLoading: boolean;
  citationsLoaded: boolean;
  error: unknown;
  showSources: boolean;
}

function emptyTurn(question: string, bigger: boolean): Turn {
  return {
    question,
    messageId: null,
    answer: null,
    noMatch: false,
    workspace: [],
    withheld: [],
    traceId: null,
    fellBackToLocal: false,
    bigger,
    model: '',
    cached: false,
    citations: [],
    citationsLoading: false,
    citationsLoaded: false,
    error: null,
    showSources: false
  };
}

function applyReply(turn: Turn, reply: MessageView): void {
  const answer: AnswerView | null | undefined = reply.answer;
  turn.messageId = reply.message_id;
  turn.noMatch = reply.no_match ?? false;
  if (!answer) {
    turn.answer = reply.text;
    return;
  }
  turn.answer = answer.text;
  turn.workspace = (answer.workspace ?? []).map(openSession);
  turn.withheld = answer.withheld ?? [];
  turn.traceId = answer.trace_id;
  turn.fellBackToLocal = answer.fell_back_to_local ?? false;
  turn.bigger = answer.bigger ?? false;
  turn.model = answer.model ?? '';
  turn.cached = answer.cached ?? false;
}

function turnsFrom(messages: MessageView[]): Turn[] {
  const turns: Turn[] = [];
  for (const message of messages) {
    if (message.role === 'user') {
      turns.push(emptyTurn(message.text, false));
    } else if (turns.length > 0) {
      applyReply(turns[turns.length - 1], message);
    }
  }
  return turns;
}

/**
 * The saved chats of one course (docs/plan-notebook.md §4.2). A new chat
 * is a draft until its first message (or its first model / source pick)
 * creates it, so opening "New chat" never leaves empty chats behind.
 */
export class CourseChats {
  readonly courseId: string;
  conversations = $state<ConversationSummary[]>([]);
  activeId = $state<string | null>(null);
  turns = $state<Turn[]>([]);
  listLoading = $state(true);
  threadLoading = $state(false);
  sending = $state(false);
  error = $state<unknown>(null);

  active = $derived(
    this.conversations.find((c) => c.conversation_id === this.activeId) ?? null
  );

  constructor(courseId: string) {
    this.courseId = courseId;
  }

  private get path() {
    return { course_id: this.courseId };
  }

  async loadList(): Promise<void> {
    this.listLoading = true;
    try {
      const { data, error } = await api.GET('/courses/{course_id}/conversations', {
        params: { path: this.path }
      });
      if (error || !data) throw error ?? new Error('unexpected empty response');
      this.conversations = data;
    } finally {
      this.listLoading = false;
    }
  }

  startNew(): void {
    this.activeId = null;
    this.turns = [];
    this.error = null;
  }

  async open(conversationId: string): Promise<void> {
    if (this.activeId === conversationId && this.turns.length > 0) return;
    this.activeId = conversationId;
    this.turns = [];
    this.error = null;
    this.threadLoading = true;
    try {
      const { data, error } = await api.GET(
        '/courses/{course_id}/conversations/{conversation_id}',
        { params: { path: { ...this.path, conversation_id: conversationId } } }
      );
      if (error || !data) throw error ?? new Error('unexpected empty response');
      if (this.activeId === conversationId) this.turns = turnsFrom(data.messages);
    } catch (caught) {
      this.error = caught;
    } finally {
      this.threadLoading = false;
    }
  }

  private upsert(summary: ConversationSummary): void {
    const rest = this.conversations.filter((c) => c.conversation_id !== summary.conversation_id);
    this.conversations = [summary, ...rest].sort((a, b) =>
      a.updated_at < b.updated_at ? 1 : a.updated_at > b.updated_at ? -1 : 0
    );
  }

  /** The active chat's id, creating the draft chat if needed. */
  async ensureConversation(): Promise<string> {
    if (this.activeId) return this.activeId;
    const { data, error } = await api.POST('/courses/{course_id}/conversations', {
      params: { path: this.path },
      body: { title: '' }
    });
    if (error || !data) throw error ?? new Error('unexpected empty response');
    this.upsert(data);
    this.activeId = data.conversation_id;
    return data.conversation_id;
  }

  async send(question: string, bigger = false): Promise<Turn> {
    this.sending = true;
    this.turns = [...this.turns, emptyTurn(question, bigger)];
    const turn = this.turns[this.turns.length - 1];
    try {
      const conversationId = await this.ensureConversation();
      const { data, error } = await api.POST(
        '/courses/{course_id}/conversations/{conversation_id}/messages',
        {
          params: { path: { ...this.path, conversation_id: conversationId } },
          body: { question, bigger_model: bigger }
        }
      );
      if (error || !data) throw error ?? new Error('unexpected empty response');
      applyReply(turn, data.reply);
      turn.showSources = !turn.noMatch;
      this.upsert(data.conversation);
      if (!turn.noMatch) void this.loadCitations(turn);
    } catch (caught) {
      turn.error = caught;
    } finally {
      this.sending = false;
    }
    return turn;
  }

  /** Ask again after an error: drop the failed turn and resend it. */
  async retry(turn: Turn): Promise<void> {
    this.turns = this.turns.filter((t) => t !== turn);
    await this.send(turn.question, turn.bigger);
  }

  async loadCitations(turn: Turn): Promise<void> {
    if (!turn.traceId || turn.citationsLoaded || turn.citationsLoading) return;
    turn.citationsLoading = true;
    try {
      const { data } = await api.GET('/courses/{course_id}/traces/{trace_id}/citations', {
        params: { path: { ...this.path, trace_id: turn.traceId } }
      });
      turn.citations = data ?? [];
      turn.citationsLoaded = true;
    } finally {
      turn.citationsLoading = false;
    }
  }

  private async patch(
    conversationId: string,
    body: components['schemas']['ConversationUpdate']
  ): Promise<void> {
    const { data, error } = await api.PATCH(
      '/courses/{course_id}/conversations/{conversation_id}',
      { params: { path: { ...this.path, conversation_id: conversationId } }, body }
    );
    if (error || !data) throw error ?? new Error('unexpected empty response');
    this.conversations = this.conversations.map((c) =>
      c.conversation_id === data.conversation_id ? data : c
    );
  }

  async rename(conversationId: string, title: string): Promise<void> {
    await this.patch(conversationId, { title });
  }

  async setModel(choice: ModelChoice | null): Promise<void> {
    await this.patch(await this.ensureConversation(), { model_choice: choice });
  }

  async setSources(sourceIds: string[] | null): Promise<void> {
    await this.patch(await this.ensureConversation(), { source_ids: sourceIds });
  }

  async remove(conversationId: string): Promise<void> {
    const { error } = await api.DELETE('/courses/{course_id}/conversations/{conversation_id}', {
      params: { path: { ...this.path, conversation_id: conversationId } }
    });
    if (error) throw error;
    this.conversations = this.conversations.filter((c) => c.conversation_id !== conversationId);
    if (this.activeId === conversationId) this.startNew();
  }
}
