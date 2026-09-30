# Usability review — 2026-09-29

This pass reviewed generation and provider routing, retrieval and ingestion seams,
tutor task framing, structured workspace output, saved chat state, companion and
Office integration, and the evaluation harness. Three Luna agents worked on
independent areas. Existing uncommitted work was preserved. This is a review of
the implementation and selected failure paths, not a certification of every
model, operating system, or installed Office workflow.

## Verified defects fixed

- **Wrong task:** mentioning slides, notes, code, or a quiz in an explanatory
  question could trigger artifact generation. Task routing now requires a
  request for an artifact; explanatory questions stay in the answer flow.
- **Broken output presented as success:** provider output-limit termination is
  rejected explicitly. Text content blocks are supported and `<think>` output
  is filtered. Empty final answers produce an actionable service error rather
  than an unhandled tutor/chat failure.
- **Malformed artifacts:** unusable or mismatched workspace objects no longer
  expose raw JSON or a misleading success reply. Workspace fences containing
  embedded Markdown code fences parse correctly; incomplete blocks are withheld.
  Non-quiz artifacts get one repair attempt with the original evidence and the
  failed response; persistent errors or placeholder content are not presented
  as completed work.
  Python workspace artifacts are compiled for syntax only (never executed).
  Invalid syntax participates in the same repair/withhold path. This does not
  establish that a syntactically valid program computes the right result.
- **Wrong endpoint:** an unavailable saved provider choice no longer silently
  falls through to an environment-configured endpoint.
- **Retrieval failures:** malformed/non-finite reranker scores fall back to
  fused order. Malformed embedding blobs and non-finite vectors are excluded
  before similarity ranking.
- **Source selection:** selected sources are filtered before each retrieval
  seam's limit. Previously, a larger set of unselected sources could crowd out
  the selected source entirely, even with overfetching.
- **Companion/Office consistency:** Office now uses the common reranker and
  configured generation candidate limit. An explicit request to explain an
  assignment takes precedence over completion instructions in copied material.
- **Stale UI:** older chat-open requests cannot overwrite current loading/error
  state. Failed citation requests expose a retry control. Office clears prior
  answers on a new request or course change, disabling stale insertion.
- **False evaluation success:** the model bake-off exits unsuccessfully for
  failed, unresolved, or empty evaluations, not just transport errors. Cases can
  specify required/forbidden content patterns; the linearity case now requires
  both defining properties rather than accepting any text containing `[1]`.
  Reports explicitly label these as mechanical contract checks. A natural
  "I don't have information" refusal is recognized by the refusal scorer.
  New inspection logs retain actual prompts, response schemas, and raw output
  for every attempt, including repairs.

## Real-model evidence

The first actual MiniCPM5-2B run used the installed LM Studio GGUF and bundled
runtime, with a temporary database and no downloads. It loaded in 16.4 seconds;
ten cases averaged 4.18 seconds each. Nine passed the mechanical checks. The
failed case was a valid refusal with wording the scorer did not recognize.

Inspection of the passing cases found a false quiz answer about magnitude,
a code sample that did not actually apply a transformation, an unsupported
comparison row, and unsupported slide detail. This is direct evidence that the
old success score overstated practical quality, even on a tiny supplied source.
The records are in `runs/bakeoff/20260929T040013Z/` (gitignored local output).

Subsequent prompt revisions require quizzes and slides to stay small when the
evidence is sparse, unknown table values to remain unspecified, comparison rows
to have labels, and generated code to use consistent input types and state its
limitations. Intermediate runs improved quiz grounding but also exposed table
shape errors, placeholder slides, and incorrect Python list arithmetic. These
observations motivated the bounded artifact repair and placeholder rejection;
they also show why a single favorable generation is insufficient validation.

The prompt-v20 run at `runs/bakeoff/20260929T040819Z/` passed 10/10 contract
checks at 4.70 seconds per case. Its quiz was grounded, but the comparison table
was incomplete, the slide omitted the properties it purported to summarize,
and Python code had invalid syntax and incorrect vector operations. The exact
syntax defect became a regression test for the subsequent static code gate.
**These runs do not establish reliable artifact generation.** The application
now handles more concrete failures and the evaluation exposes its limits;
general factual and functional correctness remain open.

The post-syntax-gate code-only run at `runs/bakeoff/20260929T041143Z/` returned
syntactically valid Python, but inspection found tuple concatenation where
vector addition was required, and a sample tuple used as a scalar. It would
fail at runtime. This run took 16.55 seconds for the case. Static syntax
validation addresses the recorded syntax defect; it does not solve model
reasoning or replace functional evaluation against known examples.

## Checks completed

- Full Python suite: 542 passed before the final Python syntax gate; the gate
  and related paths subsequently passed 116 focused tests, including proof
  that validation does not execute generated code.
- Whole-repository Ruff and backend mypy: passed.
- Frontend Svelte check: zero errors/warnings; production build passed.
- Office add-in type check and all 12 bridge tests: passed.
- Live MiniCPM runs used existing model/runtime assets and throwaway databases,
  with no downloads or changes to the user's course database. The runtime was
  stopped after each run.

## Remaining quality limits

- Valid citation numbers establish an evidence link, not factual entailment.
  Content-pattern checks are narrow regressions, not semantic grading. A wrong
  claim can still contain the expected words and valid citations.
- Quiz quality checks are heuristics. Names/dates and answer-key consistency do
  not establish that every generated question is correct. Human review of
  real model outputs remains necessary.
- Retrieval has no calibrated minimum-relevance threshold. A populated course
  can return weak matches for an unrelated question, leaving refusal to the
  model. An arbitrary cutoff would introduce new false refusals; calibrate with
  held-out questions and known supporting passages before adding one.
- The default model's quality and latency must be judged separately from mock
  tests. Unit tests deliberately replace live generation and encoders.
- Native installer and live Office insertion were not exercised by this pass.
  Frontend compilation and Office bridge tests do not replace those checks.

## Repeatable verification

Run Python tests with a unique `--basetemp` per concurrent process: this suite
removes its temporary directory on success, so sharing it across processes can
cause unrelated tests to fail. Run Ruff, mypy, frontend check/build, and Office
check/tests. For real generation, run `python -m scripts.eval_models` against an
already-installed model; it uses a temporary database and writes inspection
records under `runs/bakeoff/`.

For product acceptance, use a representative uploaded course and check:
explain a passage from slides; ask a follow-up with a restricted source set;
ask an unrelated question; generate and inspect a quiz answer key; generate
notes containing code; recover from unavailable/empty/truncated model output;
switch chats quickly; retry citation loading; and switch Office courses before
inserting an answer. Inspect accuracy, citations, task shape, and latency.
