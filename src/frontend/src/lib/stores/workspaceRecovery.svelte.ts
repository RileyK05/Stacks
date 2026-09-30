import { artifactDraftStorage, type ArtifactDraft, type DraftStorage } from './artifactDrafts';
import { draftForSaving, itemTitle, type WorkspaceSession } from './workspace.svelte';

export class WorkspaceDraftRecovery {
  error = $state<unknown>(null);
  loaded = $state(false);
  recovered = $state(false);
  pendingWrites = $state(0);
  private revision = 0;
  private lastSeen = '';
  private pending = Promise.resolve();
  private readonly writerId = crypto.randomUUID();
  private recoveredFrom: ArtifactDraft | null = null;
  private readonly prefix: string;
  readonly key: string;
  readonly ready: Promise<void>;

  constructor(
    readonly courseId: string,
    readonly messageId: string,
    readonly itemIndex: number,
    readonly session: WorkspaceSession,
    private storage: DraftStorage = artifactDraftStorage
  ) {
    this.prefix = `${courseId}:workspace:${messageId}:${itemIndex}:`;
    this.key = `${this.prefix}${this.writerId}`;
    this.ready = this.restore();
  }

  private async restore(): Promise<void> {
    const initial = JSON.stringify(draftForSaving(this.session));
    try {
      const saved = (await this.storage.list(this.prefix)).sort((a, b) => b.updatedAt - a.updatedAt)[0];
      if (saved && JSON.stringify(draftForSaving(this.session)) === initial) {
        const draft = saved.content.draft;
        if ((this.session.kind === 'document' || this.session.kind === 'slides') && typeof draft === 'string') {
          this.session.draft = draft;
          this.recovered = true;
          this.recoveredFrom = saved;
        } else if (this.session.kind === 'sheet' && Array.isArray(draft) && draft.every((row) => Array.isArray(row) && row.every((cell) => typeof cell === 'string'))) {
          this.session.draft = draft as string[][];
          this.recovered = true;
          this.recoveredFrom = saved;
        }
      }
    } catch (caught) {
      this.error = caught;
    } finally {
      this.loaded = true;
    }
  }

  observe(draft: string | string[][] | null): void {
    if (!this.loaded || draft === null) return;
    const fingerprint = JSON.stringify(draft);
    if (fingerprint === this.lastSeen) return;
    this.lastSeen = fingerprint;
    const revision = ++this.revision;
    const edited = 'edited' in this.session && this.session.edited;
    const value = structuredClone(draft);
    this.pendingWrites += 1;
    this.pending = this.pending.then(async () => {
      try {
        if (edited) {
          await this.storage.put({
            key: this.key, courseId: this.courseId,
            artifactId: `workspace:${this.messageId}:${this.itemIndex}`,
            messageId: this.messageId, itemIndex: this.itemIndex, writerId: this.writerId,
            title: itemTitle(this.session), content: { draft: value },
            baseVersion: 1, kind: this.session.kind,
            origin: { by: 'chat', message_id: this.messageId, item_index: this.itemIndex },
            sources: [], revision, updatedAt: Date.now()
          });
        } else {
          await this.storage.delete(this.key);
          if (this.recoveredFrom) {
            await this.storage.delete(this.recoveredFrom.key, this.recoveredFrom.revision, this.recoveredFrom.writerId);
            this.recoveredFrom = null;
          }
        }
        this.error = null;
      } catch (caught) {
        this.error = caught;
      } finally {
        this.pendingWrites -= 1;
      }
    });
  }

  async flush(): Promise<boolean> {
    await this.ready;
    if (this.error) this.lastSeen = '';
    this.observe(draftForSaving(this.session));
    await this.pending;
    return this.error === null || (!('edited' in this.session && this.session.edited) && !this.recovered);
  }

  async discardSaved(draft: string | string[][] | null): Promise<void> {
    await this.flush();
    if (JSON.stringify(draftForSaving(this.session)) !== JSON.stringify(draft)) return;
    try {
      await this.storage.delete(this.key, this.revision, this.writerId);
      if (this.recoveredFrom) {
        await this.storage.delete(this.recoveredFrom.key, this.recoveredFrom.revision, this.recoveredFrom.writerId);
        this.recoveredFrom = null;
      }
    } catch (caught) {
      this.error = caught;
    }
  }
}
