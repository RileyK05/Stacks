import type { IconName } from '$lib/components/Icon.svelte';

/** Display labels for backend enums — never show raw snake_case values. */

export const visibilityMeta: Record<string, { label: string; icon: IconName; hint: string }> = {
  private: { label: 'Private', icon: 'lock', hint: 'Only you' },
  invite_only: { label: 'Invite only', icon: 'users', hint: 'Anyone with the join code' },
  public: { label: 'Public', icon: 'globe', hint: 'Listed under Discover' }
};

export function visibilityLabel(value: string): string {
  return visibilityMeta[value]?.label ?? humanize(value);
}

export function humanize(value: string): string {
  const spaced = value.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

/** Stable hue (0–359) for a string, so a course keeps its color everywhere. */
export function hueFor(text: string): number {
  // FNV-1a: similar names still land on well-separated hues.
  let hash = 0x811c9dc5;
  for (const char of text) hash = Math.imul(hash ^ char.charCodeAt(0), 0x01000193) >>> 0;
  // Spread across a curated set of hues that read well as tints.
  const hues = [18, 45, 85, 145, 175, 205, 235, 265, 295, 330];
  return hues[hash % hues.length];
}

/** One or two letters for a monogram tile: "Linear Algebra" → "LA". */
export function initials(text: string): string {
  const words = text
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .split(/\s+/)
    .filter(Boolean);
  if (words.length === 0) return '?';
  const [first, second] = words;
  // Course codes read better whole: "CS 161" → "CS".
  if (second && /^\p{L}/u.test(second)) return (first[0] + second[0]).toUpperCase();
  return first.slice(0, 2).toUpperCase();
}
