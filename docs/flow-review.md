# User-flow review — 2026-09-29

The acceptance question is whether the application delivers the user's intended
outcome. A successful request, a valid response shape, or a green test suite is
evidence about a mechanism, not proof of the outcome.

This review follows the current path from uploaded material to an answer,
its evidence, an editable workspace item, and saved work. It supplements the
maintenance review in `code-health.md` and the actual model-output observations
in `usability-review.md`.

## What the user is promised at each step

| Step | User expectation | Current boundary or gap |
| --- | --- | --- |
| Upload and index | My material becomes usable for questions. | Successful indexing makes chunks searchable; course-knowledge extraction is explicitly skipped. It does not establish a complete concept model. |
| Ask | The app performs the requested task. | Intent routing distinguishes explanation from generation with language patterns. Valid output can still be the wrong task or incomplete work. |
| Answer and inspect sources | The cited text supports the answer. | Citation checks establish links, and quote checks establish matching words. Neither establishes that the answer follows from the passage. |
| Change selected sources | Future answers respect the chosen scope. | New retrieval is restricted; existing chat summary and recent replies remain in model context. The intended scope of prior context needs an explicit product contract. |
| Edit and save | Save keeps what I am looking at. | Fixed in this pass: saving a generated workspace now sends the student's current notes, slide text, or table rows. It previously copied the original stored model output. |
| Leave and return | Saved content reopens intact; unsaved status is honest. | The repaired save path was exercised through the actual UI, then the page was reloaded and the saved notes reopened. General autosave failure and draft recovery remain open as described in `code-health.md`. |

## A repaired flow, not just a passing helper

The verified defect crossed several individually plausible components:

1. A stored chat answer contained generated notes, slides, or a table.
2. The workspace editor updated a separate, local draft.
3. **Save to artifacts** sent only the stored message ID and item index.
4. The backend correctly copied that stored item and returned success.
5. The app displayed a save toast; reopening revealed the unedited original.

The corrected path sends the visible draft. The backend still takes the item's
kind, title, numbered source set, and provenance from the original stored answer.
It validates and compacts citations in the revised content, records student edits
as authored by the student, and preserves the original chat response.

Acceptance checks now save and reopen corrected notes, an intentionally emptied
document, an edited table with an added row, and a revised two-slide deck. They
check persisted content, source identity, author, and unchanged original history.
Invalid evidence references or attempts to change a document into another shape
are rejected without creating an artifact.

A separate browser check used a disposable database and the real interface:
open generated notes → edit → Save to artifacts → reload → open the saved notes.
The persisted editor showed **My corrected notes / Saved screen draft [1]**.
The screenshot is `runs/flow-review/reopened-notes.jpg`. Model output was seeded
for this check; no live generation, model downloads, or real course data were
used. This establishes draft persistence through the UI, not model correctness.

The sheet's edit indicator also compared concatenated rows, which missed deleting
the last row or moving text between cells. It now compares row counts and individual
cells, so those changes still offer **Revert**.

Validation: 640 backend tests passed, including six new save/reopen and invalid-draft
cases. Static checks and the frontend check and production build passed. These checks
establish the repaired persistence behavior; they do not establish generated answers'
factual correctness.

## The consequential behavior decisions

### What does selecting sources mean for an ongoing conversation?

Scenario: discuss material A, select only material B, then ask "is that still
true here?" The current system restricts new retrieval to B but retains prior
answers and the summary about A in its prompt.

- Keeping context makes the follow-up understandable, but old claims can still
  influence the next answer.
- Resetting context gives a stronger fresh-scope guarantee, but loses the
  referent of "that" and interrupts the conversation.

Recommendation: preserve the user's question and topic as context, explicitly
mark the source-scope change, and re-establish factual claims against the newly
selected sources. Do not silently treat earlier tutor answers as evidence. This
requires defining the contract before adding more routing or prompt heuristics.

### When does a generated draft become the user's saved work?

After saving, the generated workspace remains a separate ephemeral view. Saving
again creates another artifact. The persistence fix makes each copy accurate;
it does not make these views a single object.

- **Save a copy** preserves immutable chat output and permits alternative
  versions, but can produce duplicates and two editors that appear to represent
  the same work.
- **Adopt the draft as an artifact** moves the user into one persistent,
  versioned editor after the first save. The original model response can remain
  in chat as provenance, but tab identity and subsequent-save behavior must be
  coordinated.

Recommendation: adopt the saved artifact as the active editor, with **Save a
copy** as a separate explicit action. Decide this together with draft recovery.

### What is the promise behind a source-grounded answer?

The existing live-model records already demonstrate the gap. A 10/10 mechanical
evaluation produced flawed artifacts. A later syntax-valid Python example used
tuple concatenation instead of vector addition and would fail at runtime. The
records and limits are documented in `usability-review.md`; this pass did not
rerun a live model.

Retrieval, citation validity, and matching quotes cannot prove arbitrary
generated explanations, distractors, or programs correct.

- Restricting output to supported extraction makes the promise easier to check,
  but substantially reduces examples, synthesis, and practice generation.
- Allowing synthesis makes a more useful tutor, but needs explicit assumptions,
  task-specific checks, and evidence from independently reviewed real outputs.

Recommendation: distinguish direct source statements from generated examples
and reasoning. Keep source statements strict; accept generated features based
on their actual task outcomes rather than citation presence or syntax alone.
Measure false acceptance and false refusal separately.

## Acceptance scenarios to use before changing the design

The expected result is chosen independently of the implementation:

- A source says linear maps preserve addition and scalar multiplication. Ask
  whether they necessarily preserve lengths. A cited repetition of the
  definition is insufficient; the answer must not infer length preservation.
- Discuss source A, restrict to B, and ask a follow-up whose claim A supports
  but B does not. Check scope fidelity and an honest limitation, not just a
  citation from B.
- Ask for an explanation of a slide, then ask for a new slide deck. Inspect
  that the first explains and the second creates useful slides.
- Edit generated study work, save it, reload, reopen, and export. Compare the
  persisted and exported content with the exact draft the user saw.
- Fail a save during navigation, or change sources/providers during a request.
  Check which state survives and which answer is allowed to appear.
- Generate a quiz from known material, answer it independently, and review the
  answer key and explanations. A displayed score is not evidence of a correct
  key; the current quiz score is not a persisted mastery assessment.

Use deterministic tests for routing, persistence, state changes, and failures.
Use actual representative model outputs and independent ground truth for factual
and functional quality. Use installed UI checks for the final desktop/Office
journeys. Each establishes a different part of the user's promise.
