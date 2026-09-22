# Frontend

SvelteKit + TypeScript SPA (Svelte 5 runes, Tailwind CSS v4). Talks to the
backend **only** over its HTTP API. CSR-only (`ssr = false`,
`adapter-static`) — auth is a JWT in `localStorage`, so there is no
SSR/token complexity; the build output is a plain static bundle.

## Setup

```bash
npm install
cp .env.example .env   # see "Configuration" below
```

## Commands

```bash
npm run dev       # dev server (default http://localhost:5173)
npm run check     # svelte-check type/diagnostics — must pass
npm run build     # static SPA into build/ (fallback 200.html)
npm run preview   # serve the built bundle locally
npm run gen:api    # regenerate src/lib/api/schema.d.ts from the backend
```

## Configuration

- `.env` → `PUBLIC_API_BASE`. Empty (default) = same-origin: the Vite dev
  proxy (dev) or a reverse proxy (prod) forwards API prefixes to the
  backend. Set an absolute URL only when serving the SPA without a
  proxying web server (requires CORS on the backend, which is currently
  not configured).
- `API_PROXY_TARGET` (shell env, not `.env`) overrides the dev proxy target
  (`http://localhost:8000` by default).

## API types: generated, never hand-written

`src/lib/api/schema.d.ts` is generated from the backend's OpenAPI schema
and committed. Regenerate after any backend route/schema change:

```bash
# with the backend running (uvicorn src.backend.main:app --port 8000)
npm run gen:api
```

The backend is the single source of truth for API shapes. Use the types via
`paths` from `$lib/api/schema`, call endpoints via the typed client in
`$lib/api/client` (`api.GET('/courses')`, `api.POST(...)`), and surface
failures as `ApiError` (`$lib/api/errors`) — every thrown error from the
client is an `ApiError`, including network failures. The client injects the
Bearer token and bounces to `/login` on a rejected stored token.

## Structure

```
src/lib/api/         generated schema + typed client + ApiError
src/lib/auth/token.ts   localStorage JWT seam (the only token touchpoint)
src/lib/stores/      runes-based auth store (currentUser/login/logout)
src/lib/components/  Button, Card, TextInput, Select, Spinner, Skeleton, ErrorBanner,
                     EmptyState, Toaster, ConfirmHost
src/routes/
  (auth)/            login, register, password-reset (chromeless layout)
  (app)/             guarded shell: my courses, discover, archives, account
    courses/[id]/    course overview: ask-the-tutor session with expandable
                     cited sources, owner: dropzone upload + live indexing
                     state, join code, members; milestone stub links
      probe/         Milestone 3 placeholder
      progress/      Milestone 4 placeholder
      artifacts/     Milestone 5 placeholder
```

Global UI feedback: `toast()` (`$lib/stores/toast.svelte`) for success/error
snackbars, `confirmDialog()` (`$lib/stores/confirm.svelte`) for destructive
action prompts — both mounted once in the root layout.

## Debug panel

An operator-only debug drawer (API request log with timings/status/error
kinds, plus auth/route state) is hidden from the UI on purpose. Toggle it
with **Ctrl+Shift+.** (period); the setting persists in localStorage
(`debug-panel`) and the log clears when the panel is disabled. There is no
menu entry for it.

## Deployment

`npm run build` emits `build/` — a static SPA. Serve it from any static
server that proxies `/auth`, `/courses`, `/course-archives`, and
`/course-memories` to the uvicorn backend (same-origin keeps CORS a
non-issue). `200.html` is the SPA fallback for client-side routes.
