# Adaptive learning baseline

Implemented 2026-09-29. This is the behavior contract for background adaptation,
complete practice tests, COURSE focus, and shared CORE preferences.

## Student experience

A generated or saved multiple-choice quiz opens a server-owned test suite.
Every question must be answered before submission. A single transaction stores
all answers, help flags, source snapshots, and observations. A retry reuses the
same submission ID; conflicting responses cannot overwrite the original attempt.
If saving cannot be confirmed, answers stay available for retry and results are
not announced as persisted. Reloading and reopening the same test restores its
latest completed session. The Memory tab can reopen any historical session.

Seeing answers changes the evidence: a retake is recorded, but previously
revealed questions cannot raise proficiency. The backend detects repetition even
if the page reloads or the student unchecks the help box. A fresh independent
problem supplies new evidence. Fingerprints ignore option order and answer keys.
They detect exact question reuse, not every semantic paraphrase.

The tutor adapts quietly. Students can optionally inspect COURSE capabilities,
tentative experiments, complete sessions, and CORE teaching observations. An
incorrect or ambiguous question can be excluded immediately, then its key
reviewed against the stored source text. Corrections re-evaluate observations
and existing CORE outcomes without rewriting original answers or suite content.
Experiments that depended on the changed key reopen for a fresh check.

Deleting a raw session retains distilled observations and their evidence.
Forgetting a capability removes its COURSE observations and associated experiments;
forgetting a teaching method removes its CORE observations. These are distinct
controls. Future practice can supply new observations. Purging a course preserves
its course-memory keepsake and shared CORE observations. Course export/import
includes suites, sessions, corrections, experiments, and distilled observations,
with remapped source/suite/run links. It does not export global CORE preferences
or count imported outcomes again toward CORE.

## COURSE estimates and practice policy

Each known topic has five separate capability records: recognition, explanation,
application, counterexample, and transfer. Untested capabilities are **Unknown**,
not 0. Multiple-choice questions tagged explanation or transfer are still
multiple-choice evidence, not proof of independent explanation or transfer.

`configs/learning.toml` versions the baseline. Scores use weighted accuracy on
fresh questions: independent evidence has weight 1, assisted evidence 0.25, and
revealed repeats have no effect on the estimate. Evidence caps limit unsupported
certainty: assisted-only success caps at 40; 1 independent item at 60; 2 at 75;
3–4 at 85; 5–7 at 95; 8 or more can reach 100. A score of 100 therefore requires
both adequate independent evidence and perfect weighted accuracy. These numbers
are provisional policy choices, not calibrated probabilities or grade predictions.
Counts, dates, answer outcomes, and source snapshots remain inspectable.

Automatic broad practice has at most two weak-area/experiment questions and one
strong-area maintenance question. Weak areas below 60 have a one-day cooldown;
areas at 90 or above become eligible for maintenance after fourteen days. Fresh
questions about other supported topics provide coverage. Explicitly requesting a
named topic overrides the automatic focus restrictions; revealed duplicates
remain filtered. The selection code enforces these limits after generation, so
a model ignoring the requested quota cannot silently drill the same weakness.
If no fresh supported questions remain, generation declines honestly.

Course focus follows the student through source changes, but selected sources
control eligibility and factual claims. Old evidence does not license facts
from an excluded source. Focus is fenced as student observations, never supplied
as authoritative course material or behavior instructions.

## CORE observations and experiments

CORE uses four fixed presentation approaches: step by step, worked examples,
analogies, and diagrams/comparisons. An explicit preference wins. Otherwise the
baseline compares fresh unassisted outcomes and periodically tries a less-tested
approach. Evidence includes the preceding teaching context when available.
Success after a method is an observation, not proof of causation; unequal
question difficulty and sparse samples remain unresolved. The library, companion,
and Office answer paths apply the presentation preference. Recorded interactive
test sessions currently live in the library and saved-artifact practice UI.

Eligible saved chat exchanges can propose up to two tentative checks. Short
ordinary questions are skipped; longer messages or expressed confusion are
eligible for background research. The researcher uses the conversation's chosen
provider, the ordinary model-call seam, and fenced student/source text. The app
requires an exact student quote and valid cited passage numbers. Chat alone never
assigns a capability score or establishes a teaching preference.

A course has at most twelve active experiments, with one per topic/capability.
They expire after forty-two days. Only a fresh unassisted answer can check one;
a successful check resolves the scheduled experiment, while a miss imposes a
one-day cooldown and three unsuccessful checks retire it. Resolving an experiment
is not declaring mastery. Correcting its supporting question reopens it. Research
failure leaves the already saved reply and practice records intact.

## Verification and remaining limits

Behavior tests cover complete sessions, reload, idempotent retries, invalid or
partial submissions, assisted versus independent success, revealed retakes,
source selection, quotas/cooldowns, maintenance, answer-key correction, experiment
reopening, cross-course CORE, deletion/purge, and portable course history. Tests
also reproduce observed model failures involving wrong answer indices and a
capability label used as the course topic. Static backend/frontend checks and the
production frontend build are required alongside these tests.

A real browser check used the actual API/UI with a disposable source and a seeded
quiz: answer one item incorrectly, submit both, reload and reopen, then score
perfectly on a revealed retake. The Memory panel retained application at 0/100,
showed the original miss and assisted success, left untested capabilities Unknown,
and kept both complete sessions. Screenshot: `runs/learning-review/memory.jpg`.
No model was involved in that persistence check.

Live MiniCPM5-2B evaluations are separate from those persistence tests. The initial
answer harness passed 9/10 mechanical checks (`runs/bakeoff/20260930T005526Z`).
Manual inspection also found list concatenation used as vector addition and a
poor comparison table despite citations. Direct new-prompt review found an
inconsistent quiz key/topic and an invalid research citation; concrete key/topic
checks were tightened and research citation bounds are enforced by schema and
validation. `runs/learning-review/live-research.json` retains synthetic outputs.
These checks do not establish general factual accuracy, scoring calibration, or
pedagogical effectiveness. Free-response assessment, semantic duplicate detection,
canonical topic linking, broader teaching preferences, and longitudinal outcome
evaluation remain future work.

Final verification: 661 backend tests passed; Ruff and mypy passed; generated API
types and Svelte diagnostics passed; production SPA built. Targeted research/
quiz checks were rerun after the final citation-bound change. The final answer
harness (`runs/bakeoff/20260930T011252Z`) again passed 9/10 mechanical checks: the
thin-source quiz was declined rather than producing the expected workspace.
Direct prompt review produced no experiment for a neutral question and retained
quoted, source-linked proposals for two expressed difficulties. It produced a
quiz with appropriate topic labels and coherent answer indices, but one item
still had several true alternatives. Research proposals also requested examples
not directly provided in the passages. These are unresolved content-quality
limitations; citation validity and JSON conformance do not resolve them. Review
or exclude questionable items before treating their outcomes as reliable evidence.
