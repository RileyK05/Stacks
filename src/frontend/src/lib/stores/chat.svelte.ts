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
  chunkIds: string[];
  fellBackToLocal: boolean;
  bigger: boolean;
  model: string;
  cached: boolean;
  citations: Citation[];
  citationsLoading: boolean;
  citationsLoaded: boolean;
  citationsError: unknown;
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
    chunkIds: [],
    fellBackToLocal: false,
    bigger,
    model: '',
    cached: false,
    citations: [],
    citationsLoading: false,
    citationsLoaded: false,
    citationsError: null,
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
  turn.workspace = (answer.workspace ?? []).map((item, index) => openSession(item, { message_id: reply.message_id, item_index: index }));
  turn.withheld = answer.withheld ?? [];
  turn.traceId = answer.trace_id;
  turn.chunkIds = answer.chunk_ids;
  turn.fellBackToLocal = answer.fell_back_to_local ?? false;
  turn.bigger = answer.bigger ?? false;
  turn.model = answer.model ?? '';
  turn.cached = answer.cached ?? false;
}

function turnsFrom(messages: MessageView[]): Turn[] {
  const turns: Turn[] = [];
  const answered = new Set<Turn>();
  for (const message of messages) {
    if (message.role === 'user') {
      turns.push(emptyTurn(message.text, false));
    } else if (turns.length > 0) {
      applyReply(turns[turns.length - 1], message);
      answered.add(turns[turns.length - 1]);
    }
  }
  // A saved question with no reply would otherwise show "Reading your course
  // material…" forever (and block the composer): offer to ask it again.
  for (const turn of turns) {
    if (!answered.has(turn)) {
      turn.error = new Error('This question never got an answer.');
    }
  }
  return turns;
}

/**
 * The saved chats of one course. A new chat
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
  error = $state<unknown>(null);
  private openRequest = 0;
  /** Creating the draft chat; shared so two quick actions make one chat. */
  private creating: Promise<string> | null = null;
  /** Settings changes (model, sources) go out one at a time, before any send. */
  private patching: Promise<unknown> = Promise.resolve();
  /** Questions still waiting for their reply, by chat: switching away and
   * back keeps showing them instead of dropping them from the thread. */
  private pending = new Map<string, Turn>();
  private removed = new Set<string>();

  /** Whether the open thread is waiting for a reply. */
  get sending(): boolean {
    return this.turns.some((turn) => turn.answer === null && !turn.error);
  }

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
    this.openRequest += 1;
    this.creating = null;
    this.activeId = null;
    this.turns = [];
    this.error = null;
    this.threadLoading = false;
  }

  async open(conversationId: string): Promise<void> {
    if (this.activeId === conversationId && this.turns.length > 0) return;
    const request = ++this.openRequest;
    this.creating = null;
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
      if (this.openRequest === request && this.activeId === conversationId) {
        const turns = turnsFrom(data.messages);
        const waiting = this.pending.get(conversationId);
        if (waiting) turns.push(waiting);
        this.turns = turns;
      }
    } catch (caught) {
      if (this.openRequest === request) this.error = caught;
    } finally {
      if (this.openRequest === request) this.threadLoading = false;
    }
  }

  private upsert(summary: ConversationSummary): void {
    const rest = this.conversations.filter((c) => c.conversation_id !== summary.conversation_id);
    this.conversations = [summary, ...rest].sort((a, b) =>
      a.updated_at < b.updated_at ? 1 : a.updated_at > b.updated_at ? -1 : 0
    );
  }

  /** The active chat's id, creating the draft chat if needed. */
  ensureConversation(): Promise<string> {
    if (this.activeId) return Promise.resolve(this.activeId);
    if (this.creating) return this.creating;
    const view = this.openRequest;
    const creating = (async () => {
      const { data, error } = await api.POST('/courses/{course_id}/conversations', {
        params: { path: this.path },
        body: { title: '' }
      });
      if (error || !data) throw error ?? new Error('unexpected empty response');
      this.upsert(data);
      // The student may have opened another chat while this was being made.
      if (this.openRequest === view) this.activeId = data.conversation_id;
      return data.conversation_id;
    })();
    this.creating = creating;
    const clear = () => {
      if (this.creating === creating) this.creating = null;
    };
    creating.then(clear, clear);
    return creating;
  }

  async send(question: string, bigger = false): Promise<Turn> {
    this.error = null;
    this.turns = [...this.turns, emptyTurn(question, bigger)];
    const turn = this.turns[this.turns.length - 1];
    return this.run(turn);
  }

  private async run(turn: Turn): Promise<Turn> {
    let conversationId: string | null = null;
    try {
      conversationId = await this.ensureConversation();
      this.pending.set(conversationId, turn);
      await this.patching.catch(() => undefined);
      const { data, error } = await api.POST(
        '/courses/{course_id}/conversations/{conversation_id}/messages',
        {
          params: { path: { ...this.path, conversation_id: conversationId } },
          body: { question: turn.question, bigger_model: turn.bigger }
        }
      );
      if (error || !data) throw error ?? new Error('unexpected empty response');
      applyReply(turn, data.reply);
      turn.showSources = !turn.noMatch;
      if (!this.removed.has(data.conversation.conversation_id)) this.upsert(data.conversation);
      if (!turn.noMatch) void this.loadCitations(turn);
    } catch (caught) {
      turn.error = caught;
    } finally {
      if (conversationId && this.pending.get(conversationId) === turn) {
        this.pending.delete(conversationId);
      }
    }
    return turn;
  }

  /** Ask again after an error, in place: the question is not added twice
   * (the server only stores a question together with its reply). */
  async retry(turn: Turn): Promise<Turn | null> {
    if (turn.answer !== null || !turn.error || !this.turns.includes(turn)) return null;
    turn.error = null;
    return this.run(turn);
  }

  async loadCitations(turn: Turn): Promise<void> {
    if (!turn.traceId || turn.citationsLoaded || turn.citationsLoading) return;
    turn.citationsLoading = true;
    turn.citationsError = null;
    try {
      const { data, error } = await api.GET('/courses/{course_id}/traces/{trace_id}/citations', {
        params: { path: { ...this.path, trace_id: turn.traceId } }
      });
      if (error) throw error;
      turn.citations = data ?? [];
      turn.citationsLoaded = true;
    } catch (caught) {
      turn.citationsError = caught;
    } finally {
      turn.citationsLoading = false;
    }
  }

  private patch(
    conversationId: string,
    body: components['schemas']['ConversationUpdate']
  ): Promise<void> {
    const job = this.patching
      .catch(() => undefined)
      .then(() => this.sendPatch(conversationId, body));
    this.patching = job;
    return job;
  }

  private async sendPatch(
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
    this.removed.add(conversationId);
    this.pending.delete(conversationId);
    this.conversations = this.conversations.filter((c) => c.conversation_id !== conversationId);
    if (this.activeId === conversationId) this.startNew();
  }
}
