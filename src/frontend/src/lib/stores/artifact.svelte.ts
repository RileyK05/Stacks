import { api } from '$lib/api/client';
import type { components } from '$lib/api/schema';
import type { IconName } from '$lib/components/Icon.svelte';

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
  doc: 'Doc',
  sheet: 'Sheet',
  slides: 'Slides',
  quiz: 'Quiz',
  flashcards: 'Flashcards',
  code: 'Code',
  chart: 'Chart'
};

export const KIND_ICONS: Record<ArtifactKind, IconName> = {
  doc: 'file-text',
  sheet: 'table',
  slides: 'presentation',
  quiz: 'list-checks',
  flashcards: 'layers',
  code: 'code',
  chart: 'trending-up'
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
  chart: [{ format: 'html', label: 'Web page (.html)' }]
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
  proposal = $state<Proposal | null>(null);
  proposing = $state(false);
  proposalError = $state<unknown>(null);
  lastRequest = $state('');
  versions = $state<VersionView[]>([]);
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(courseId: string, artifactId: string) {
    this.courseId = courseId;
    this.artifactId = artifactId;
  }

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
      this.apply(data);
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
  }

  async loadCitations(): Promise<void> {
    const { data } = await api.GET('/courses/{course_id}/artifacts/{artifact_id}/citations', {
      params: { path: this.path }
    });
    this.citations = data ?? [];
  }

  /** Mark the content (or title) changed; it saves shortly after. */
  touch(): void {
    this.dirty = true;
    this.saveError = null;
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.save(), AUTOSAVE_MS);
  }

  async flush(): Promise<void> {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.dirty) await this.save();
  }

  async save(options: { author?: 'you' | 'model'; note?: string; sources?: string[] } = {}): Promise<boolean> {
    if (!this.artifact || this.conflict) return false;
    if (this.saving) {
      // A save is in flight; try again once it lands.
      this.touch();
      return false;
    }
    const sentContent = $state.snapshot(this.content);
    const sentTitle = this.title.trim() || this.artifact.title;
    const unchanged =
      !options.sources &&
      sentTitle === this.artifact.title &&
      JSON.stringify(sentContent) === JSON.stringify(this.artifact.content);
    if (unchanged) {
      // Nothing to keep: no new version for a no-op.
      this.dirty = false;
      return true;
    }
    this.saving = true;
    try {
      const { data, error, response } = await api.PUT('/courses/{course_id}/artifacts/{artifact_id}', {
        params: { path: this.path },
        body: {
          base_version: this.artifact.version,
          title: sentTitle,
          content: sentContent,
          sources: options.sources ?? null,
          author: options.author ?? 'you',
          note: options.note ?? ''
        }
      });
      if (response.status === 409) {
        this.conflict = true;
        return false;
      }
      if (error || !data) throw error ?? new Error('unexpected empty response');
      const changedMeanwhile =
        JSON.stringify($state.snapshot(this.content)) !== JSON.stringify(sentContent) ||
        this.title.trim() !== sentTitle;
      this.artifact = data;
      if (!changedMeanwhile) this.dirty = false;
      if (options.sources) await this.loadCitations();
      return true;
    } catch (caught) {
      if ((caught as { status?: number }).status === 409) this.conflict = true;
      else this.saveError = caught;
      return false;
    } finally {
      this.saving = false;
      if (this.dirty && !this.conflict && !this.timer) this.touch();
    }
  }

  async propose(request: string, scope: EditScope | null): Promise<void> {
    await this.flush();
    this.proposing = true;
    this.proposalError = null;
    this.lastRequest = request;
    try {
      const { data, error } = await api.POST(
        '/courses/{course_id}/artifacts/{artifact_id}/propose-edit',
        { params: { path: this.path }, body: { request, scope } }
      );
      if (error || !data) throw error ?? new Error('unexpected empty response');
      this.proposal = data;
    } catch (caught) {
      this.proposalError = caught;
    } finally {
      this.proposing = false;
    }
  }

  async accept(): Promise<boolean> {
    if (!this.proposal) return false;
    const proposal = this.proposal;
    this.content = structuredClone($state.snapshot(proposal.content));
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
    const { data } = await api.GET('/courses/{course_id}/artifacts/{artifact_id}/versions', {
      params: { path: this.path }
    });
    this.versions = data ?? [];
  }

  async restore(version: number): Promise<void> {
    await this.flush();
    if (!this.artifact) return;
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
  }

  async reload(): Promise<void> {
    await this.load();
  }

  async exportTo(format: string, path: string | null): Promise<{ path: string; filename: string }> {
    await this.flush();
    const { data, error } = await api.POST('/courses/{course_id}/artifacts/{artifact_id}/export', {
      params: { path: this.path },
      body: { format, path }
    });
    if (error || !data) throw error ?? new Error('unexpected empty response');
    return data;
  }

  async remove(): Promise<void> {
    if (this.timer) clearTimeout(this.timer);
    const { error } = await api.DELETE('/courses/{course_id}/artifacts/{artifact_id}', {
      params: { path: this.path }
    });
    if (error) throw error;
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
  itemIndex: number
): Promise<ArtifactView> {
  const { data, error } = await api.POST('/courses/{course_id}/artifacts/from-message', {
    params: { path: { course_id: courseId } },
    body: { message_id: messageId, item_index: itemIndex }
  });
  if (error || !data) throw error ?? new Error('unexpected empty response');
  return data;
}
