// The desktop shell starts the backend with a per-launch secret and opens
// this window at `/#token=<secret>`. The secret is read once, kept for the
// window's session, and stripped from the address bar; every API request
// echoes it (X-App-Token), so other programs on this machine that can
// reach 127.0.0.1 still cannot drive the API. In development there is no
// token and the backend does not ask for one.

const STORAGE_KEY = 'course_assistant_app_token';
export const APP_TOKEN_HEADER = 'X-App-Token';

export function captureAppToken(): void {
  if (typeof window === 'undefined') return;
  const match = /(?:^#|&)token=([^&]+)/.exec(window.location.hash);
  if (!match) return;
  try {
    sessionStorage.setItem(STORAGE_KEY, decodeURIComponent(match[1]));
  } catch {
    // Storage blocked: the token only lives for this page load.
    memoryToken = decodeURIComponent(match[1]);
  }
  history.replaceState(history.state, '', window.location.pathname + window.location.search);
}

let memoryToken: string | null = null;

export function appToken(): string | null {
  if (typeof sessionStorage === 'undefined') return memoryToken;
  try {
    return sessionStorage.getItem(STORAGE_KEY) ?? memoryToken;
  } catch {
    return memoryToken;
  }
}
