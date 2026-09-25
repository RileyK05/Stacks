import { connectBackend } from '$lib/api/backend';
import type { LayoutLoad } from './$types';

export const ssr = false;

// Runs before any page loads, so the first API request already knows the
// backend's address and carries this launch's token. The splash in
// app.html covers the wait (the backend loads its encoders on start). A
// backend that never answers is reported by the root layout itself: an
// error thrown here would have no layout left to render the error page.
export const load: LayoutLoad = async () => {
  try {
    await connectBackend();
    return { backendError: null };
  } catch (err) {
    return { backendError: err instanceof Error ? err.message : String(err) };
  }
};
