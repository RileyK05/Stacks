import { api } from '$lib/api/client';
import type { components } from '$lib/api/schema';
import type { IconName } from '$lib/components/Icon.svelte';
import {
  artifactDraftKey,
  artifactDraftStorage,
  coalesceSave,
  flushDirtyEdits,
  saveIntentAfterSuccessfulSave,
  saveIntentForRetry,
  type ArtifactDraft,
  type DraftSaveIntent,
  type DraftStorage
} from './artifactDrafts';

export type ArtifactView = components['schemas']['ArtifactView'];
export type ArtifactSummary = components['schemas']['ArtifactSummaryView'];
export type ArtifactKind = ArtifactView['kind'];
export type ArtifactCitation = components['schemas']['ArtifactCitationView'];
export type Proposal = components['schemas']['ProposalView'];
export type VersionView = components['schemas']['VersionView'];
export type EditScope = components['schemas']['EditScope'];

// Typed content per kind (mirrors src/backend/artifacts/content.py).
export interface DocContent {
  markdown: string;
}
export interface SheetContent {
  columns: string[];
  rows: string[][];
}
export interface Slide {
  title: string;
  body: string;
  notes: string;
}
export interface SlidesContent {
  slides: Slide[];
}
export interface QuizQuestion {
  prompt: string;
  options: string[];
  answer: number;
  explanation: string;
  sources: number[];
  topic?: string;
  capability?: components['schemas']['PracticeQuestion']['capability'];
}
export interface QuizContent {
  questions: QuizQuestion[];
}
export interface Flashcard {
  front: string;
  back: string;
  sources: number[];
}
export interface FlashcardsContent {
  cards: Flashcard[];
}
export interface CodeContent {
  language: string;
  code: string;
}
export interface ChartContent {
  html: string;
}

export const KIND_LABELS: Record<ArtifactKind, string> = {
  doc: 'Notes',
  sheet: 'Schedule',
  slides: 'Study deck',
  quiz: 'Quiz',
  flashcards: 'Flashcards',
  code: 'Code',
  chart: 'Chart',
  mind_map: 'Mind map'
};

export const KIND_ICONS: Record<ArtifactKind, IconName> = {
  doc: 'file-text',
  sheet: 'table',
  slides: 'presentation',
  quiz: 'list-checks',
  flashcards: 'layers',
  code: 'code',
  chart: 'trending-up',
  mind_map: 'layers'
};

export const EXPORT_FORMATS: Record<ArtifactKind, { format: string; label: string }[]> = {
  doc: [
    { format: 'docx', label: 'Word (.docx)' },
    { format: 'md', label: 'Markdown (.md)' }
  ],
  sheet: [
    { format: 'xlsx', label: 'Excel (.xlsx)' },
    { format: 'csv', label: 'CSV (.csv)' }
  ],
  slides: [
    { format: 'pptx', label: 'PowerPoint (.pptx)' },
    { format: 'md', label: 'Markdown (.md)' }
  ],
  quiz: [{ format: 'md', label: 'Markdown (.md)' }],
  flashcards: [
    { format: 'csv', label: 'CSV (.csv)' },
    { format: 'md', label: 'Markdown (.md)' }
  ],
  code: [{ format: 'txt', label: 'Source file' }],
  chart: [{ format: 'html', label: 'Web page (.html)' }],
  mind_map: [{ format: 'md', label: 'Topics and connections (.md)' }]
};

const AUTOSAVE_MS = 900;

/**
 * One open artifact: its content, autosave, citations, versions, and the
 * model-edit proposal loop. Content is edited in place; a save goes out
 * shortly after the last change, based on the version it was loaded at —
 * if another window saved first, the save is refused and `conflict` is
 * set rather than overwriting.
 */
export class OpenArtifact {
  readonly courseId: string;
  readonly artifactId: string;
  artifact = $state<ArtifactView | null>(null);
  title = $state('');
  content = $state<Record<string, unknown>>({});
  citations = $state<ArtifactCitation[]>([]);
  loading = $state(true);
  error = $state<unknown>(null);
  saving = $state(false);
  dirty = $state(false);
  conflict = $state(false);
  saveError = $state<unknown>(null);
  recoveryError = $state<unknown>(null);
  recoveryDrafts = $state<ArtifactDraft[]>([]);
  recoveryReady = $state(false);
  recovered = $state(false);
  proposal = $state<Proposal | null>(null);
  proposing = $state(false);
  proposalError = $state<unknown>(null);
  lastRequest = $state('');
  private revision = 0;
  private persistedRevision = 0;
  private readonly writerId = `writer-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  private proposalBaseVersion: number | null = null;
  private proposalBaseRevision: number | null = null;
  private recoveredFrom: ArtifactDraft | null = null;
  private pendingSave: DraftSaveIntent | null = null;
  private saveInFlight: Promise<boolean> | null = null;
  private persistenceQueue: Promise<void> = Promise.resolve();
  private destroyed = false;
  private deleting = false;
  private removed = false;
  versions = $state<VersionView[]>([]);
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(courseId: string, artifactId: string, private drafts: DraftStorage = artifactDraftStorage) {
    this.courseId = courseId;
    this.artifactId = artifactId;
    if (typeof window !== 'undefined') {
      window.addEventListener('pagehide', this.onPageHide);
      window.addEventListener('beforeunload', this.onBeforeUnload);
    }
  }

  private get draftKey() {
    return `${this.draftPrefix}${this.writerId}`;
  }

  private get draftPrefix() {
    return `${artifactDraftKey(this.courseId, this.artifactId)}:`;
  }

  private onPageHide = () => {
    if (this.dirty) void this.persistDraft();
  };

  private onBeforeUnload = (event: BeforeUnloadEvent) => {
    if (!this.dirty) return;
    void this.persistDraft();
    if (this.persistedRevision < this.revision || this.recoveryError) {
      event.preventDefault();
      event.returnValue = '';
    }
  };

  private get path() {
    return { course_id: this.courseId, artifact_id: this.artifactId };
  }

  get kind(): ArtifactKind | null {
    return this.artifact?.kind ?? null;
  }

  async load(): Promise<void> {
    this.loading = true;
    this.error = null;
    try {
      const { data, error } = await api.GET('/courses/{course_id}/artifacts/{artifact_id}', {
        params: { path: this.path }
      });
      if (error || !data) throw error ?? new Error('unexpected empty response');
      if (this.destroyed || this.removed) return;
      this.apply(data);
      this.recoveryReady = false;
      try {
        const saved = (await this.drafts.list(this.draftPrefix)).sort((a, b) => b.updatedAt - a.updatedAt);
        this.recoveryDrafts = saved;
        const resumable = saved.find((draft) => draft.baseVersion === data.version);
        if (resumable) {
          const sameAsServer = resumable.title === data.title && JSON.stringify(resumable.content) === JSON.stringify(data.content);
          if (sameAsServer) {
            await this.deleteDraft(resumable.key, resumable.revision, resumable.writerId);
            this.recoveryDrafts = this.recoveryDrafts.filter((draft) => draft.key !== resumable.key);
          } else {
            this.applyRecoveryDraft(resumable);
            this.recoveredFrom = resumable;
            this.recoveryDrafts = this.recoveryDrafts.filter((draft) => draft.key !== resumable.key);
            this.timer = setTimeout(() => void this.save(), AUTOSAVE_MS);
          }
        }
      } catch (caught) {
        this.recoveryError = caught;
      } finally {
        this.recoveryReady = true;
      }
      await this.loadCitations();
    } catch (caught) {
      this.error = caught;
    } finally {
      this.loading = false;
    }
  }

  private apply(view: ArtifactView): void {
    this.artifact = view;
    this.title = view.title;
    this.content = structuredClone($state.snapshot(view.content));
    this.dirty = false;
    this.conflict = false;
    this.saveError = null;
    this.recovered = false;
    this.recoveryDrafts = [];
    this.pendingSave = null;
    this.revision += 1;
    this.persistedRevision = this.revision;
  }

  private applyRecoveryDraft(draft: ArtifactDraft): void {
    this.title = draft.title;
    this.content = $state.snapshot(draft.content);
    this.dirty = true;
    this.conflict = false;
    this.recovered = true;
    this.recoveredFrom = draft;
    this.pendingSave = draft.pendingSave ? $state.snapshot(draft.pendingSave) : null;
    this.revision = Math.max(this.revision, draft.revision);
    this.persistedRevision = this.revision;
  }

  async loadCitations(): Promise<void> {
    // The list of cited passages is a nicety: failing to fetch it must not
    // make an artifact that loaded (or saved) fine look broken.
    try {
      const { data } = await api.GET('/courses/{course_id}/artifacts/{artifact_id}/citations', {
        params: { path: this.path }
      });
      this.citations = data ?? [];
    } catch {
      // keep the citations we already have
    }
  }

  /** Mark the content (or title) changed; it saves shortly after. */
  touch(): void {
    if (this.destroyed || this.deleting || this.removed) return;
    this.revision += 1;
    this.dirty = true;
    this.saveError = null;
    if (this.conflict) this.rememberRecoveryDraft(this.currentDraft());
    void this.persistDraft();
    if (this.timer) clearTimeout(this.timer);
    if (!this.conflict) this.timer = setTimeout(() => void this.save(), AUTOSAVE_MS);
  }

  async flush(): Promise<boolean> {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.saveInFlight) {
      const saved = await this.saveInFlight;
      if (!saved) return false;
    }
    return (await flushDirtyEdits(() => this.dirty, () => this.conflict, () => this.save())) && !this.saveError;
  }

  async save(options: { author?: 'you' | 'model'; note?: string; sources?: string[] } = {}): Promise<boolean> {
    if (!this.artifact || this.conflict || this.destroyed || this.deleting || this.removed) return false;
    const intent = saveIntentForRetry(this.pendingSave, options);
    if (Object.keys(options).length > 0) this.pendingSave = intent;
    if (intent) void this.persistDraft();
    return coalesceSave(
      () => this.saveInFlight,
      (operation) => { this.saveInFlight = operation; },
      () => this.saveOnce(intent ?? {})
    );
  }

  async retrySave(): Promise<boolean> {
    return this.save();
  }

  private async saveOnce(options: { author?: 'you' | 'model'; note?: string; sources?: string[] }): Promise<boolean> {
    const artifact = this.artifact;
    if (!artifact || this.conflict) return false;
    this.saveError = null;
    const sentContent = $state.snapshot(this.content);
    const sentTitle = this.title.trim() || artifact.title;
    const sentRevision = this.revision;
    const sentIntent = this.pendingSave ? $state.snapshot(this.pendingSave) : null;
    const unchanged =
      !options.sources &&
      sentTitle === artifact.title &&
      JSON.stringify(sentContent) === JSON.stringify(artifact.content);
    if (unchanged) {
      // Nothing to keep: no new version for a no-op.
      this.dirty = false;
      this.persistedRevision = sentRevision;
      this.pendingSave = null;
      try {
        await this.deleteDraft(this.draftKey, sentRevision, this.writerId);
      } catch (caught) {
        this.recoveryError = caught;
      }
      return true;
    }
    this.saving = true;
    try {
      const { data, error, response } = await api.PUT('/courses/{course_id}/artifacts/{artifact_id}', {
        params: { path: this.path },
        body: {
          base_version: artifact.version,
          title: sentTitle,
          content: sentContent,
          sources: options.sources ?? null,
          author: options.author ?? 'you',
          note: options.note ?? ''
        }
      });
      if (response.status === 409) {
        this.conflict = true;
        this.saveError = null;
        this.rememberRecoveryDraft(this.currentDraft());
        void this.persistDraft();
        return false;
      }
      if (error || !data) throw error ?? new Error('unexpected empty response');
      const changedMeanwhile =
        this.revision !== sentRevision;
      this.artifact = data;
      this.pendingSave = saveIntentAfterSuccessfulSave(sentIntent, changedMeanwhile);
      if (!changedMeanwhile) {
        this.dirty = false;
        this.persistedRevision = sentRevision;
        this.conflict = false;
        this.recovered = false;
        try {
          await this.deleteDraft(this.draftKey, sentRevision, this.writerId);
        } catch (caught) {
          this.recoveryError = caught;
        }
        if (this.recoveredFrom) {
          try {
            await this.deleteDraft(this.recoveredFrom.key, this.recoveredFrom.revision, this.recoveredFrom.writerId);
            this.recoveredFrom = null;
          } catch (caught) {
            this.recoveryError = caught;
          }
        }
      } else {
        this.dirty = true;
        void this.persistDraft();
      }
      if (options.sources) await this.loadCitations();
      return true;
    } catch (caught) {
      if ((caught as { status?: number }).status === 409) {
        this.conflict = true;
        this.rememberRecoveryDraft(this.currentDraft());
        void this.persistDraft();
      }
      else this.saveError = caught;
      return false;
    } finally {
      this.saving = false;
      if (this.dirty && !this.conflict && !this.saveError && !this.destroyed && !this.deleting && !this.removed) {
        if (this.timer) clearTimeout(this.timer);
        this.timer = setTimeout(() => void this.save(), AUTOSAVE_MS);
      }
    }
  }

  async propose(request: string, scope: EditScope | null): Promise<void> {
    if (!(await this.flush())) {
      this.proposalError = new Error('Save your current edits before requesting a proposal.');
      return;
    }
    if (!this.artifact) {
      this.proposalError = new Error('Wait for this artifact to finish loading before requesting a proposal.');
      return;
    }
    this.proposing = true;
    this.proposalError = null;
    this.lastRequest = request;
    this.proposalBaseVersion = this.artifact?.version ?? null;
    this.proposalBaseRevision = this.revision;
    try {
      const { data, error } = await api.POST(
        '/courses/{course_id}/artifacts/{artifact_id}/propose-edit',
        { params: { path: this.path }, body: { request, scope } }
      );
      if (error || !data) throw error ?? new Error('unexpected empty response');
      const { data: latest, error: latestError } = await api.GET('/courses/{course_id}/artifacts/{artifact_id}', {
        params: { path: this.path }
      });
      if (latestError || !latest) throw latestError ?? new Error('Could not verify the proposal version.');
      if (latest.version !== this.proposalBaseVersion || this.revision !== this.proposalBaseRevision) {
        if (latest.version !== this.proposalBaseVersion) this.conflict = true;
        this.proposalError = new Error('The artifact changed while Stacks was drafting. Save the latest version and request a new proposal.');
        return;
      }
      this.proposal = data;
    } catch (caught) {
      this.proposalError = caught;
    } finally {
      this.proposing = false;
    }
  }

  async accept(): Promise<boolean> {
    if (!this.proposal) return false;
    if (!(await this.flush())) return false;
    if (!this.artifact || this.proposalBaseVersion !== this.artifact.version || this.proposalBaseRevision !== this.revision) {
      this.proposalError = new Error('Your artifact changed after this proposal was prepared. Request a new proposal before accepting it.');
      return false;
    }
    const proposal = this.proposal;
    this.content = structuredClone($state.snapshot(proposal.content));
    this.touch();
    const ok = await this.save({
      author: 'model',
      note: this.lastRequest.slice(0, 300),
      sources: proposal.sources
    });
    if (ok) this.proposal = null;
    return ok;
  }

  discard(): void {
    this.proposal = null;
  }

  async loadVersions(): Promise<void> {
    try {
      const { data } = await api.GET('/courses/{course_id}/artifacts/{artifact_id}/versions', {
        params: { path: this.path }
      });
      this.versions = data ?? [];
    } catch (caught) {
      this.error = caught;
    }
  }

  async restore(version: number): Promise<boolean> {
    if (this.recoveryDrafts.length > 0) {
      this.saveError = new Error('Resolve the saved draft before restoring a version.');
      return false;
    }
    if (!(await this.flush()) || !this.artifact) return false;
    try {
      const { data, error } = await api.POST(
        '/courses/{course_id}/artifacts/{artifact_id}/versions/{number}/restore',
        {
          params: { path: { ...this.path, number: version } },
          body: { base_version: this.artifact.version }
        }
      );
      if (error || !data) throw error ?? new Error('unexpected empty response');
      this.apply(data);
      await Promise.all([this.loadCitations(), this.loadVersions()]);
      return true;
    } catch (caught) {
      if ((caught as { status?: number }).status === 409) {
        this.conflict = true;
        this.rememberRecoveryDraft(this.currentDraft());
        void this.persistDraft();
      } else {
        this.saveError = caught;
      }
      return false;
    }
  }

  async reload(): Promise<void> {
    this.rememberRecoveryDraft(this.recoveredFrom);
    if (this.dirty) {
      this.rememberRecoveryDraft(this.currentDraft());
      await this.persistDraft();
    }
    const existing = [...this.recoveryDrafts];
    await this.fetchLatest();
    this.recoveryDrafts = existing;
  }

  async loadLatestAndDiscardDraft(): Promise<void> {
    this.rememberRecoveryDraft(this.recoveredFrom);
    if (this.dirty) {
      this.rememberRecoveryDraft(this.currentDraft());
      await this.persistDraft();
    }
    const drafts = [...this.recoveryDrafts];
    if (!(await this.fetchLatest())) return;
    const retained: ArtifactDraft[] = [];
    for (const draft of drafts) {
      try {
        await this.deleteDraft(draft.key, draft.revision, draft.writerId);
      } catch {
        retained.push(draft);
      }
    }
    this.recoveryDrafts = retained;
    this.recoveredFrom = null;
    this.recoveryError = retained.length ? new Error('Some local drafts could not be cleared. They remain available for recovery.') : null;
  }

  async recoverSavedDraft(draft: ArtifactDraft): Promise<boolean> {
    if (!this.artifact) return false;
    if (draft.baseVersion !== this.artifact.version) {
      this.conflict = true;
      this.rememberRecoveryDraft(draft);
      this.recoveryError = new Error('This saved draft is based on an older version. Keep it here and copy its contents before resolving the conflict.');
      return false;
    }
    if (
      this.dirty &&
      (this.title !== draft.title || JSON.stringify($state.snapshot(this.content)) !== JSON.stringify(draft.content))
    ) {
      const visible = this.currentDraft();
      if (visible) {
        const copyId = `${this.writerId}-copy-${crypto.randomUUID()}`;
        const copy = { ...visible, key: `${this.draftPrefix}${copyId}`, writerId: copyId };
        try {
          await this.drafts.put(copy);
          this.rememberRecoveryDraft(copy);
        } catch (caught) {
          this.recoveryError = caught;
          return false;
        }
      }
    }
    this.applyRecoveryDraft(draft);
    this.recoveryDrafts = this.recoveryDrafts.filter((saved) => saved.key !== draft.key);
    this.recoveryError = null;
    this.touch();
    return true;
  }

  async discardSavedDraft(draft: ArtifactDraft): Promise<void> {
    try {
      await this.deleteDraft(draft.key, draft.revision, draft.writerId);
      this.recoveryDrafts = this.recoveryDrafts.filter((saved) => saved.key !== draft.key);
      this.recoveryError = null;
    } catch (caught) {
      this.recoveryError = caught;
    }
  }

  private async fetchLatest(): Promise<boolean> {
    this.loading = true;
    try {
      const { data, error } = await api.GET('/courses/{course_id}/artifacts/{artifact_id}', {
        params: { path: this.path }
      });
      if (error || !data) throw error ?? new Error('unexpected empty response');
      this.apply(data);
      this.conflict = false;
      this.saveError = null;
      await Promise.all([this.loadCitations(), this.loadVersions()]);
      return true;
    } catch (caught) {
      this.saveError = caught;
      return false;
    } finally {
      this.loading = false;
    }
  }

  async exportTo(format: string, path: string | null): Promise<{ path: string; filename: string }> {
    if (!(await this.flush())) throw new Error('Save your current edits before exporting.');
    const { data, error } = await api.POST('/courses/{course_id}/artifacts/{artifact_id}/export', {
      params: { path: this.path },
      body: { format, path }
    });
    if (error || !data) throw error ?? new Error('unexpected empty response');
    return data;
  }

  async copy(): Promise<ArtifactView> {
    if (!(await this.flush())) throw new Error('Save your current edits before making a copy.');
    if (!this.artifact) throw new Error('This artifact has not finished loading.');
    try {
      const { data, error } = await api.POST('/courses/{course_id}/artifacts/{artifact_id}/copy', {
        params: { path: this.path },
        body: { base_version: this.artifact.version }
      });
      if (error || !data) throw error ?? new Error('Could not create a copy.');
      return data;
    } catch (caught) {
      if ((caught as { status?: number }).status === 409) {
        this.conflict = true;
        this.rememberRecoveryDraft(this.currentDraft());
        void this.persistDraft();
      } else {
        this.saveError = caught;
      }
      throw caught;
    }
  }

  async remove(): Promise<void> {
    if (this.deleting || this.removed) return;
    this.deleting = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    try {
      if (this.saveInFlight) await this.saveInFlight;
      const { error } = await api.DELETE('/courses/{course_id}/artifacts/{artifact_id}', {
        params: { path: this.path }
      });
      if (error) throw error;
    } catch (caught) {
      this.deleting = false;
      throw caught;
    }
    // Nothing left to save: leaving the page must not PUT to a deleted artifact.
    this.removed = true;
    this.destroyed = true;
    this.dirty = false;
    if (typeof window !== 'undefined') {
      window.removeEventListener('pagehide', this.onPageHide);
      window.removeEventListener('beforeunload', this.onBeforeUnload);
    }
    this.persistenceQueue = this.persistenceQueue.catch(() => {}).then(() =>
      this.drafts.deleteArtifact
        ? this.drafts.deleteArtifact(this.courseId, this.artifactId)
        : this.drafts.delete(this.draftKey)
    );
    try {
      await this.persistenceQueue;
    } catch (caught) {
      this.recoveryError = caught;
    }
    this.recoveredFrom = null;
  }

  private currentDraft(): ArtifactDraft | null {
    if (!this.artifact) return null;
    return {
      key: this.draftKey,
      courseId: this.courseId,
      artifactId: this.artifactId,
      title: this.title,
      content: $state.snapshot(this.content),
      baseVersion: this.artifact.version,
      kind: this.artifact.kind,
      origin: $state.snapshot(this.artifact.origin),
      sources: [...this.artifact.sources],
      pendingSave: this.pendingSave ? $state.snapshot(this.pendingSave) : null,
      revision: this.revision,
      writerId: this.writerId,
      updatedAt: Date.now()
    };
  }

  private async deleteDraft(key = this.draftKey, revision?: number, writerId = this.writerId): Promise<void> {
    this.persistenceQueue = this.persistenceQueue.catch(() => {}).then(() => this.drafts.delete(key, revision, writerId));
    await this.persistenceQueue;
  }

  private rememberRecoveryDraft(draft: ArtifactDraft | null): void {
    if (!draft) return;
    this.recoveryDrafts = [draft, ...this.recoveryDrafts.filter((saved) => saved.key !== draft.key)];
  }

  async persistDraft(): Promise<void> {
    if (this.removed || this.deleting) return;
    try {
      const draft = this.currentDraft();
      if (!this.dirty || !draft) return;
      this.persistenceQueue = this.persistenceQueue.catch(() => {}).then(() => this.drafts.put(draft));
      await this.persistenceQueue;
      this.persistedRevision = Math.max(this.persistedRevision, draft.revision);
      this.recoveryError = null;
    } catch (caught) {
      this.recoveryError = caught;
    }
  }

  dispose(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (typeof window !== 'undefined') {
      window.removeEventListener('pagehide', this.onPageHide);
      window.removeEventListener('beforeunload', this.onBeforeUnload);
    }
    if (this.dirty && !this.removed && !this.deleting) void this.persistDraft();
  }
}

export async function listArtifacts(courseId: string): Promise<ArtifactSummary[]> {
  const { data, error } = await api.GET('/courses/{course_id}/artifacts', {
    params: { path: { course_id: courseId } }
  });
  if (error || !data) throw error ?? new Error('unexpected empty response');
  return data;
}

export async function createArtifact(
  courseId: string,
  kind: ArtifactKind,
  title = ''
): Promise<ArtifactView> {
  const { data, error } = await api.POST('/courses/{course_id}/artifacts', {
    params: { path: { course_id: courseId } },
    body: { kind, title }
  });
  if (error || !data) throw error ?? new Error('unexpected empty response');
  return data;
}

export async function saveFromMessage(
  courseId: string,
  messageId: string,
  itemIndex: number,
  draft: string | string[][] | null = null,
  asCopy = false
): Promise<ArtifactView> {
  const { data, error } = await api.POST('/courses/{course_id}/artifacts/from-message', {
    params: { path: { course_id: courseId } },
    body: { message_id: messageId, item_index: itemIndex, draft, as_copy: asCopy }
  });
  if (error || !data) throw error ?? new Error('unexpected empty response');
  return data;
}

/** Rename without touching content or sources (a new version, like a save). */
export async function renameArtifact(
  courseId: string,
  artifactId: string,
  title: string,
  baseVersion: number
): Promise<ArtifactView> {
  const { data, error } = await api.POST('/courses/{course_id}/artifacts/{artifact_id}/rename', {
    params: { path: { course_id: courseId, artifact_id: artifactId } },
    body: { base_version: baseVersion, title }
  });
  if (error || !data) throw error ?? new Error('unexpected empty response');
  return data;
}
