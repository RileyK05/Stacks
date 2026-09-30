# Companion work sessions

Implemented 2026-09-29 as a first document-assistance baseline. The companion
helps with work in another application, using Stacks courses for evidence.
Its primary object is a work session, not a smaller copy of the course chat.

## Connections and scope

Create a session in a course and classify it as a paper, slides, practice
material, or a reference. Connect a document file, paste its text, choose a
Windows application window, or publish a snapshot from the Office task pane.
Documents and conversations persist in SQLite and travel in `.course` archives.
Refresh explicitly after editing the external document. Every reply names the
snapshot revision it used; refreshing does not retroactively rewrite replies.

The Office action shares the live Word main body, or a whole Office package
where the host supports it. Main-body reads omit headers, footnotes, comments,
and images. Packages use the existing read-only OOXML extractor. File reads
support PDF, DOCX, PPTX, XLSX, Markdown, CSV, and UTF-8 text, with a 20 MB limit.
Image-only PDFs are declined rather than represented by empty page labels.

Windows capture enumerates visible, non-minimized external windows. The student
chooses one; the reader verifies its handle, process, and title before reading.
It reads accessibility document text where exposed. Otherwise it asks the
application to render its window and uses the configured image-capable model
for OCR. It does not sweep the whole desktop or continuously observe apps.
Timeouts run in a separate hidden process; the capture helper is bundled with
the backend. Unsupported platforms use Office, files, or paste.

Accessibility and window pixels cannot prove that all off-screen pages were
read. Those captures are marked partial and their text can be inspected. This
is not yet a universal live Google Docs integration. A canvas editor may expose
little text or fail to render. A file export is the reliable fallback.

## Memory contract

Working documents are untrusted student material, not course evidence. An
incorrect assertion in a paper, a quotation, or a question inside a worksheet
must not become course knowledge or an observation about student capability.

All four session purposes save raw work only. Review, explanation, source lookup,
summary, and proposed edits write no learning observations, experiments,
teaching-effectiveness records, preferences, or practice scores. CORE preferences
may guide presentation; they are read without being inferred from the document.
Formal scored attempts continue through the separate complete-suite practice
API. A practice worksheet is not automatically an independent test attempt.

This intentionally conservative first version does not infer what is important
enough for permanent memory. Future explicit feedback or assessment events need
their own evidence contract; switching a session purpose must never implicitly
promote its contents into memory.

## Assistance and evidence

Find references returns exact stored course passages with their filename and
locator, without asking a model to invent a quote. Copying the passage is
separate from copying the response. Other actions use a fenced prompt that
separates the draft, selected passage, prior conversation, and current course
evidence. Source numbers are validated. Course-based reviews, revisions, and
explanations must cite at least one provided source. This checks references,
not the truth of every generated inference.

The entire extracted text is retained. For long documents, bounded sections
are selected by overlap with the request, including relevant material at the
end of the document. The response exposes included section numbers and whether
all captured text fit. A partial context is not a whole-document review.
Multi-pass whole-document analysis and semantic section selection remain open.

Proposed edits are shown for inspection and copying. This baseline does not
apply companion edits directly to arbitrary external applications. Existing
Office insertion controls are separate from the new connection action.
Reviews must identify exact passages from the supplied draft. Revisions must
return an exact original passage, replacement wording, and an explanation;
critique alone, invented passages, empty replacements, and unchanged wording
are rejected. A selected passage limits both actions to that passage. The
replacement can be copied separately. These checks establish what the model
is reviewing or editing, not whether every judgment is correct.

## Persistence and concurrency

Migration 009 adds `work_sessions`, immutable `work_documents` revisions, and
idempotent `work_turns`. Document updates require the expected revision. Model
calls run outside write transactions; saving rechecks the revision under the
SQLite writer lock. A changed document yields a conflict rather than an answer
silently attached to the wrong snapshot. Request IDs make confirmed retries
idempotent. Pending requests are retained locally for retry; failures do not
pretend a response was saved.

Course changes isolate drafts, selections, and visible answers. The companion
refreshes course and session metadata on focus and every ten seconds while
visible. It fetches the active session again only when its update timestamp
changes. Closing the window loses neither saved snapshots nor confirmed turns.
Unsubmitted question drafts and paste forms are not yet durable.

Deleting a work session removes its snapshots and turns. Course sources and
learning memory are independent. Course purge cascades work records. Import
remaps session and request IDs and citation links, and clears external window
identities so an archive cannot reconnect itself to an unrelated application.
Missing source mappings preserve the embedded quote but clear its live source
link and assign new snapshot IDs. The interface labels these archived passages.
Missing retrieval traces are cleared instead of inventing a trace that does
not exist. Imported replies must match their recorded document revision.

## Verification

Tests exercise persistence, conversation context, source isolation, exact
passages, all-purpose memory isolation, stale revision rejection during model
generation, request retries, Office sharing, full-file tail retrieval, archive
round trips, deletion, and unreadable PDFs. Office package tests verify every
slice is read and the temporary file closes on success and failure.

In an isolated browser fixture, an entire synthetic political-science paper was
connected, an exact course passage retrieved, and a follow-up saved. Reload
reopened both turns. Switching courses hid the paper and switching back reopened
it. The interface was inspected at the companion's native 420 by 760 starting
size. The fixture stubs generation; it is evidence of the UI flow, not model
quality. Native Windows capture and installed Office hosts require manual
verification; the available computer-use surface here cannot operate them.
The browser fixture also verified a proposed edit, copying only its replacement,
and reopening the saved edit after reload at 420 by 760.

Live local model review uses synthetic drafts and disposable data. An initial
review confused paragraph numbers with citations and was rejected; an edit
overstated "can" as "necessary." The prompt now prohibits both patterns and
checks missing source citations. An intermediate review attributed a course
claim to the student, and a revision returned only critique. Those failures
motivated the structured passage and replacement contracts in prompt version 27.

The final synthetic-draft run produced a correct anchored review and an exact
course passage. An unfocused revision selected a passage absent from the draft
and was rejected without saving a turn. A separate selected-passage revision
produced a useful replacement, but its explanation reversed what the original
claim said. All measured learning-memory tables remained empty. These are mixed
model-quality results, not a successful semantic acceptance suite. Exact passage
lookup is deterministic; generated interpretation is not guaranteed by valid
citations or exact draft anchors. Reports are in ignored
`runs/companion-review/live-work.json` and `live-selected-edit.json`.

The earlier broader evaluation passed 7 of 10 cases, with generated study
artifact failures and one output-limit error
(`runs/bakeoff/20260930T022049Z/report.json`). It exercises the existing tutor
and artifact prompts, not companion review quality. Final code validation:
685 backend tests passed, including 24 companion cases; backend lint and type
checks passed; the frontend check and production build passed; Office's 14
bridge tests and type check passed; the capture helper passed syntax parsing.
Native capture, actual Office hosts, and an installed desktop build remain
unverified.

A final prompt-version-27 grounding/refusal check passed 2 of 2 cases through
`scripts.eval_models` (`runs/bakeoff/20260930T031259Z/report.json`). This narrow
check does not supersede the broader 7-of-10 result or the companion semantic
failures above.
