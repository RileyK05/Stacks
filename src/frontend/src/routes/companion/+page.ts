// Ship a real entry point for the companion. Tauri's custom protocol cannot
// rely on the development server's SPA fallback for this secondary window.
export const prerender = true;
export const trailingSlash = 'always';
