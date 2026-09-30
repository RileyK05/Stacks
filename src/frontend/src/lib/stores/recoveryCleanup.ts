import { api } from '$lib/api/client';
import { artifactDraftStorage } from './artifactDrafts';

export async function cleanOrphanedRecovery(): Promise<void> {
  const drafts = await artifactDraftStorage.list('');
  if (!drafts.length) return;
  const [courses, trash] = await Promise.all([api.GET('/courses'), api.GET('/trash')]);
  if (courses.error || trash.error || !courses.data || !trash.data) return;
  const retained = new Set([...courses.data, ...trash.data].map((course) => course.course_id));
  const active = new Set(courses.data.map((course) => course.course_id));
  for (const courseId of new Set(drafts.map((draft) => draft.courseId))) {
    if (!retained.has(courseId)) {
      await artifactDraftStorage.deleteCourse?.(courseId);
      continue;
    }
    if (!active.has(courseId)) continue;
    const saved = await api.GET('/courses/{course_id}/artifacts', { params: { path: { course_id: courseId } } });
    const conversations = await api.GET('/courses/{course_id}/conversations', { params: { path: { course_id: courseId } } });
    if (saved.error || conversations.error || !saved.data || !conversations.data) continue;
    const artifacts = new Set(saved.data.map((artifact) => artifact.artifact_id));
    const histories = await Promise.all(conversations.data.map((conversation) => api.GET('/courses/{course_id}/conversations/{conversation_id}', {
      params: { path: { course_id: courseId, conversation_id: conversation.conversation_id } }
    })));
    const messages = new Set(histories.flatMap((history) => history.data?.messages.map((message) => message.message_id) ?? []));
    for (const draft of drafts.filter((draft) => draft.courseId === courseId)) {
      if (draft.messageId ? histories.every((history) => !history.error && history.data) && !messages.has(draft.messageId) : !artifacts.has(draft.artifactId)) {
        await artifactDraftStorage.delete(draft.key, draft.revision, draft.writerId);
      }
    }
  }
}
