import { invoke, isTauri } from '@tauri-apps/api/core';

/** Focus the single companion window and carry the current course into it. */
export async function showCompanion(courseId?: string): Promise<void> {
  if (courseId) localStorage.setItem('companion-course', courseId);
  if (isTauri()) {
    await invoke('show_companion');
    return;
  }
  const opened = window.open(
    '/companion/',
    'stacks-companion',
    'popup=yes,width=420,height=760,resizable=yes'
  );
  if (!opened) throw new Error('Your browser blocked the companion window.');
  opened.focus();
}
