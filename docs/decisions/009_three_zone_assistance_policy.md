# 009 — Three-zone assistance policy (learning over completion)

Date: 2026-09-20
Status: Ratified (operator conversation; referenced by decision 010's
answer harness and the tutor prompt's steer line)
Supersedes: the flat "No auto-solving graded work" line (project.md
principles) as the *operational* behavior contract. The principle stays;
this document makes it operational.

## Context

"Learning over completion" is easy to state and hard to draw. The honest
lines are not refusal-shaped — they are behavior choices:

- Using it to help build a slide deck you present: **not** cheating.
- Using it to check answers and understand mistakes: **not** cheating.
- Using it to fill out your entire homework: **cheating** — and, worse,
  useless to the student, who learns nothing and has no exam preparation.

A flat refusal for the third case is the wrong product answer: it punishes
the ask instead of converting the intent. A student turned away will just
use another service. The design goal is to **make the juice not worth the
squeeze**: the compliant path must be genuinely better — faster, more
useful, and compounding (every logged struggle improves later practice) —
not policed.

## Decision

**Three zones of user requests**, each with its own contract:

| Zone | Behavior | Examples |
|---|---|---|
| **Green — allow + cite** | Full capability, evidence-linked | Explain a concept; check my answer and why it's wrong; build me a deck to present; quiz me |
| **Yellow — steer, don't refuse** | Recognize the intent, redirect to the learning loop | "Fill in my homework" → walk the reasoning, show the *why*, log the struggle, offer practice problems |
| **Red — decline the artifact, keep the person** | Decline the submission-shaped artifact | "Write my essay to submit as mine"; bulk-answering a live exam |

**The yellow steer is a product feature, not a prompt trick.** The
collaborative redirect is:

1. Explain the answer to X with the citation contract (still grounded —
   "here's why this is right" cites the material it rests on).
2. Write the struggle into the student model (a normal write path).
3. Offer generated practice on that weakness (probe generation — already
   a reserved task).

The model doesn't moralize; it *converts*: homework request → explanation
+ logged weakness + practice offer. The student keeps learning; the
system gains signal; the exam gets studied for.

## Enforcement split (hard gates vs prompt contract)

**Hard-gated (code, not model discretion):**
- Every generated artifact element must carry a valid citation to real
  evidence; the renderer rejects uncited elements (same check as the
  tutor's `[n]` validation in the answer harness).
- Artifact/probe generation goes through the tier/budget gates like all
  compute; every generation lands in the trace ("what did the system
  produce for this student" is always answerable).
- The deep-read fallback ladder (future): step caps are code, not prompt.

**Prompt-contract level (steered, measured — not mechanically enforceable):**
- *Recognizing* "this is a homework-fill request" is a judgment call; no
  regex decides it. The answer harness measures it: adversarial cases
  ("here's my problem set, fill it in") score whether the model explained-
  and-redirected vs. filled vs. flatly refused. Steering quality is a
  rate, not a binary.

**Threat model — pricing, not policing.** The target is a *rate*, not
zero: a determined student can extract answers by rephrasing; the
compliant path must simply be better (accumulated context, targeted
practice, exam prep) rather than the workaround. Any added friction
should make the good path *faster*, not the bad path harder — a rule that
does both badly is a wall, and walls get routed around while annoying
honest users.

## Where the line is (ratified examples)

- Generated quizzes/excel = practice artifacts from their own materials:
  **fine**.
- Auto-solving *submitted* graded work: **declined** — but by steering to
  the learning loop first (yellow), not by pretending the question was
  unanswerable (that would be a lie the material can falsify).
- Slide decks for presenting: **green**, every slide element citing its
  evidence.

## Cross-references

- The tutor prompt (configs/prompts.toml) carries the steer line; scored
  by the answer harness's yellow_steer cases (decision 010).
- Artifact generation (Milestone 5) inherits this policy: every artifact
  element cites evidence; fill-in-shaped requests steer.
- The generated-artifact + graded-work boundary is written here so it
  cannot creep: practice artifacts fine, submission-shaped artifacts
  converted to learning, submitted-work impersonation declined.