import { invoke, isTauri } from '@tauri-apps/api/core';

// Where the API lives and the secret that unlocks it.
//
// In the desktop app the Tauri shell starts the backend on a free
// 127.0.0.1 port with a per-launch secret and hands both to this window
// only (`backend_info`, src-tauri/src/backend.rs); every API request
// echoes the secret (X-App-Token), so other programs on this machine that
// can reach 127.0.0.1 still cannot drive the API.
//
// In a plain browser (`npm run dev` next to a uvicorn backend) the Vite
// proxy forwards /api on the same origin and no token is needed.

export const APP_TOKEN_HEADER = 'X-App-Token';

interface BackendInfo {
  url: string;
  token: string;
  log_dir: string | null;
}

let origin = '';
let token: string | null = null;
let connecting: Promise<void> | null = null;

/** Resolves once the backend answers. Safe to call repeatedly; a failed
 * attempt is forgotten so the next call tries again. */
export function connectBackend(): Promise<void> {
  connecting ??= (async () => {
    if (!isTauri()) return;
    const info = await invoke<BackendInfo>('backend_info');
    origin = info.url;
    token = info.token;
  })().catch((error: unknown) => {
    connecting = null;
    throw new Error(typeof error === 'string' ? error : String(error));
  });
  return connecting;
}

export function apiBase(): string {
  return `${origin}/api`;
}

export function appToken(): string | null {
  return token;
}
