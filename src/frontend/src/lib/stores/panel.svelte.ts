import { OpenArtifact, type ArtifactKind, type ArtifactSummary } from '$lib/stores/artifact.svelte';

export interface ArtifactTab {
  artifactId: string;
  title: string;
  kind: ArtifactKind;
  open: OpenArtifact;
}

/**
 * The right-hand panel: a resizable, collapsible surface holding tabs for the
 * artifacts the student has popped open, beside the chat's transient
 * workspace tabs. Persisted in localStorage so a reload keeps the layout.
 */
export class PanelState {
  tabs = $state<ArtifactTab[]>([]);
  activeId = $state<string | null>(null);
  width = $state(420);
  /**
   * Whether the panel is shown, independent of how many tabs it has. This is
   * a plain flag and not `tabs.length > 0`: the toggle must be able to open
   * the empty panel (it previously set state that the layout ignored, so the
   * button did nothing with no tabs open).
   */
  visible = $state(false);

  constructor(private courseId: string, private storageKey: string) {
    this.restore();
  }

  get active(): ArtifactTab | null {
    return this.tabs.find((tab) => tab.artifactId === this.activeId) ?? null;
  }

  async openArtifact(summary: Pick<ArtifactSummary, 'artifact_id' | 'title' | 'kind'>): Promise<void> {
    const existing = this.tabs.find((tab) => tab.artifactId === summary.artifact_id);
    if (existing) {
      this.activeId = existing.artifactId;
      this.visible = true;
      this.persist();
      return;
    }
    const open = new OpenArtifact(this.courseId, summary.artifact_id);
    const tab: ArtifactTab = {
      artifactId: summary.artifact_id,
      title: summary.title,
      kind: summary.kind,
      open
    };
    this.tabs.push(tab);
    this.activeId = tab.artifactId;
    this.visible = true;
    this.persist();
    await open.load();
    tab.title = open.title || tab.title;
  }

  activate(id: string): void {
    this.activeId = id;
    this.persist();
  }

  async close(id: string): Promise<boolean> {
    const tab = this.tabs.find((item) => item.artifactId === id);
    if (tab && !(await tab.open.flush())) return false;
    tab?.open.dispose();
    this.tabs = this.tabs.filter((item) => item.artifactId !== id);
    if (this.activeId === id) {
      this.activeId = this.tabs[this.tabs.length - 1]?.artifactId ?? null;
    }
    this.persist();
    return true;
  }

  async flushAll(): Promise<boolean> {
    const results = await Promise.all(this.tabs.map((tab) => tab.open.flush()));
    return results.every(Boolean);
  }

  dispose(): void {
    for (const tab of this.tabs) tab.open.dispose();
  }

  /** Drop tabs whose artifact no longer exists (deleted elsewhere). */
  prune(existing: Set<string>): void {
    const removed = this.tabs.filter((tab) => !existing.has(tab.artifactId));
    for (const tab of removed) tab.open.dispose();
    const kept = this.tabs.filter((tab) => existing.has(tab.artifactId));
    if (kept.length === this.tabs.length) return;
    this.tabs = kept;
    if (this.activeId !== null && !existing.has(this.activeId)) {
      this.activeId = kept[kept.length - 1]?.artifactId ?? null;
    }
    this.persist();
  }

  hide(): void {
    this.visible = false;
    this.persist();
  }

  show(): void {
    this.visible = true;
    this.persist();
  }

  setWidth(value: number): void {
    this.width = value;
    this.persist();
  }

  private persist(): void {
    try {
      localStorage.setItem(
        this.storageKey,
        JSON.stringify({
          width: this.width,
          visible: this.visible,
          tabs: this.tabs.map((tab) => ({ artifactId: tab.artifactId, title: tab.title, kind: tab.kind })),
          activeId: this.activeId
        })
      );
    } catch {
      // A full or disabled localStorage is not worth failing a layout for.
    }
  }

  private restore(): void {
    try {
      const raw = localStorage.getItem(this.storageKey);
      if (!raw) return;
      const saved = JSON.parse(raw) as {
        width?: number;
        visible?: boolean;
        hidden?: boolean;
        activeId?: string | null;
        tabs?: { artifactId: string; title: string; kind: ArtifactKind }[];
      };
      if (typeof saved.width === 'number') this.width = saved.width;
      if (typeof saved.visible === 'boolean') this.visible = saved.visible;
      else if (saved.tabs && saved.tabs.length > 0 && saved.hidden !== true) {
        // Migrate the old layout: tabs present and not hidden meant shown.
        this.visible = true;
      }
      this.tabs = (saved.tabs ?? []).map((tab) => ({
        ...tab,
        open: new OpenArtifact(this.courseId, tab.artifactId)
      }));
      this.activeId = saved.activeId ?? null;
      void this.reloadTabs();
    } catch {
      // Corrupt layout state is discarded silently.
      this.tabs = [];
    }
  }

  private async reloadTabs(): Promise<void> {
    await Promise.all(this.tabs.map((tab) => tab.open.load()));
  }
}
