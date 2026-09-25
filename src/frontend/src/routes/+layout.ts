import { captureAppToken } from '$lib/api/appToken';

export const ssr = false;

// Runs before any page loads, so the first API request already carries
// the desktop shell's per-launch token.
captureAppToken();
