let toasts = $state<{ id: number; message: string; tone: 'success' | 'error' }[]>([]);
let nextId = 0;

export function toast(message: string, tone: 'success' | 'error' = 'success'): void {
  const id = nextId++;
  toasts = [...toasts, { id, message, tone }];
  // Errors are usually longer and need reading: keep them up longer.
  setTimeout(() => dismiss(id), tone === 'error' ? 9000 : 4000);
}

export function dismiss(id: number): void {
  toasts = toasts.filter((t) => t.id !== id);
}

export function currentToasts(): { id: number; message: string; tone: 'success' | 'error' }[] {
  return toasts;
}
