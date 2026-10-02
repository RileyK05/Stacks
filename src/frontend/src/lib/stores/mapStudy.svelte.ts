import { api } from '$lib/api/client';
import type { components } from '$lib/api/schema';
import type { MapContext } from './mindMap';

export class MapStudy {
  busy = $state(false);
  error = $state('');
  result = $state<components['schemas']['MapStudyResult'] | null>(null);
  private pending: components['schemas']['MapStudyRequest'] | null = null;
  private revision = 0;

  clear() { this.revision++; this.result = null; this.error = ''; this.pending = null; this.busy = false; }

  async request(context: MapContext, nodeId: string, action: 'explain' | 'quiz') {
    if (this.busy || context.ready === false) return;
    const key = JSON.stringify(context.origin);
    const same = this.pending?.node_id === nodeId && this.pending.action === action && JSON.stringify(this.pending.origin) === key;
    const body = same ? this.pending! : { origin: context.origin, node_id: nodeId, action, request_id: crypto.randomUUID() };
    this.pending = body;
    this.busy = true; this.error = ''; this.result = null;
    const revision = ++this.revision;
    try {
      const { data, error } = await api.POST('/courses/{course_id}/mind-map/study', {
        params: { path: { course_id: context.courseId } }, body
      });
      if (revision !== this.revision) return;
      if (error || !data) throw new Error(error && 'detail' in error ? String(error.detail) : 'Could not study this topic. Try again.');
      this.result = data; this.pending = null;
    } catch (error) {
      if (revision === this.revision) this.error = error instanceof Error ? error.message : 'Could not study this topic. Try again.';
    } finally { if (revision === this.revision) this.busy = false; }
  }
}
