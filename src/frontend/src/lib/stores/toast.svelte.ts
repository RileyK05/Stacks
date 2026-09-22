let toasts = $state<{ id: number; message: string; tone: 'success' | 'error' }[]>([]);
let nextId = 0;

export function toast(message: string, tone: 'success' | 'error' = 'success'): void {
  const id = nextId++;
  toasts = [...toasts, { id, message, tone }];
  setTimeout(() => dismiss(id), 4000);
}

export function dismiss(id: number): void {
  toasts = toasts.filter((t) => t.id !== id);
}

export function currentToasts(): { id: number; message: string; tone: 'success' | 'error' }[] {
  return toasts;
}
