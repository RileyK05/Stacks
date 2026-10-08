/** Labels and grouping for essay critique. Thresholds match configs/companion.toml. */

export const ESSAY_GENRES = [
  { value: 'argumentative', label: 'Argumentative' },
  { value: 'analytical', label: 'Analytical' },
  { value: 'research', label: 'Research' },
  { value: 'comparative', label: 'Comparative' },
  { value: 'creative', label: 'Creative' },
  { value: 'reflective', label: 'Reflective' },
  { value: 'rhetorical', label: 'Rhetorical' }
] as const;

export type EssayGenre = (typeof ESSAY_GENRES)[number]['value'];

export const DIMENSION_LABELS: Record<string, string> = {
  requirements: 'Requirements',
  reasoning: 'Reasoning',
  evidence: 'Evidence',
  structure: 'Structure',
  craft: 'Craft',
  clarity: 'Clarity'
};

export const FALLACY_LABELS: Record<string, string> = {
  straw_man: 'straw man',
  false_dilemma: 'false dilemma',
  hasty_generalization: 'hasty generalization',
  post_hoc: 'post hoc',
  appeal_to_authority: 'appeal to authority',
  circular: 'circular',
  slippery_slope: 'slippery slope',
  ad_hominem: 'ad hominem',
  equivocation: 'equivocation',
  unsupported_claim: 'unsupported claim',
  missing_counterargument: 'missing counterargument'
};

export interface CritiqueCoverage {
  complete: boolean;
  included_sections: number[];
  total_sections: number;
}

export interface CritiqueFindingView {
  original: string;
  feedback: string;
  dimension: string;
  grounding: string;
  fallacy: string;
}

export interface PriorFindingView {
  original: string;
  feedback: string;
  status: 'still_present' | 'passage_changed';
}

export interface CritiqueView {
  critic_score: number;
  genre: string;
  syllabus_in_context: boolean;
  coverage: CritiqueCoverage;
  findings?: CritiqueFindingView[];
  prior?: PriorFindingView[];
  note: string;
}

export interface CitationChip {
  number: number;
  filename: string;
  label: string;
}

const BANDS = {
  rough: {
    label: 'Rough draft',
    detail: 'Only a problem that would change the draft.'
  },
  strong: {
    label: 'Strong reviewer',
    detail: 'A weak warrant, mismatched evidence, or a dropped counterargument is in range.'
  },
  severe: {
    label: 'Severe',
    detail: 'Almost every supplied claim with a real gap. The wording is blunt.'
  }
} as const;

export function bandFor(score: number): { id: keyof typeof BANDS; label: string; detail: string } {
  const id = score < 30 ? 'rough' : score < 75 ? 'strong' : 'severe';
  return { id, ...BANDS[id] };
}

export function fallacyLabel(fallacy: string): string {
  return FALLACY_LABELS[fallacy] ?? '';
}

export function dimensionLabel(dimension: string): string {
  return DIMENSION_LABELS[dimension] ?? dimension;
}

export function coverageLine(coverage: CritiqueCoverage): string {
  if (coverage.complete) return 'All captured text was supplied for this pass.';
  const sections = coverage.included_sections.join(', ') || 'none';
  return `Partial review: sections ${sections} of ${coverage.total_sections}. This pass did not read the rest of the draft.`;
}

export function stillOpen(prior: PriorFindingView[] = []): PriorFindingView[] {
  return prior.filter((item) => item.status === 'still_present');
}

export function passageEdited(prior: PriorFindingView[] = []): PriorFindingView[] {
  return prior.filter((item) => item.status === 'passage_changed');
}

export function citationChips(feedback: string, citations: CitationChip[]): CitationChip[] {
  const numbers = new Set([...feedback.matchAll(/\[(\d+)\]/g)].map((match) => Number(match[1])));
  return citations.filter((citation) => numbers.has(citation.number));
}

export function latestCritique<T extends { reply: { critique?: CritiqueView | null } }>(
  turns: T[]
): CritiqueView | null {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const critique = turns[index]?.reply.critique;
    if (critique) return critique;
  }
  return null;
}
