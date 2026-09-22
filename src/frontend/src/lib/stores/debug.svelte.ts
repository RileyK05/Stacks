export type DebugEntry = {
  id: number;
  method: string;
  path: string;
  status: number; // 0 marks a fetch-level failure (server down, CORS, DNS)
  durationMs: number;
  errorKind: string | null;
  errorMessage: string | null;
  at: number;
};

const STORAGE_KEY = 'debug-panel';
const MAX_ENTRIES = 50;

let enabled = $state(
  typeof window !== 'undefined' && window.localStorage.getItem(STORAGE_KEY) === '1'
);
let entries = $state<DebugEntry[]>([]);
let nextId = 0;

export function debugEnabled(): boolean {
  return enabled;
}

export function setDebugEnabled(value: boolean): void {
  enabled = value;
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(STORAGE_KEY, value ? '1' : '0');
  }
  if (!value) entries = [];
}

export function toggleDebug(): void {
  setDebugEnabled(!enabled);
}

export function debugEntries(): DebugEntry[] {
  return entries;
}

export function logRequest(
  entry: Omit<DebugEntry, 'id' | 'at'>
): void {
  if (!enabled) return;
  entries = [...entries, { ...entry, id: nextId++, at: Date.now() }].slice(-MAX_ENTRIES);
}

export function clearDebugLog(): void {
  entries = [];
}
