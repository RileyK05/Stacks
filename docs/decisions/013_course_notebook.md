# 013 — Stacks is a course notebook with typed, editable artifacts

Date: 2026-09-25
Status: Ratified (owner review of `docs/plan-notebook.md`)
Amends: 011 (workspace items now persist as artifacts; its "nothing
persists" invariant is lifted, as it anticipated), 007 (the user reads a
generated memory summary, not the raw record)

## Context

With the desktop app shipped (decision 012), the owner set the product
shape: course-centred, "like NotebookLM, with hints of Notion", and
explicitly not a general assistant. The question was how chats, generated
material and the student's own work fit together.

## Decision

1. **A course is a notebook**: sources, unlimited individual chats, and
   artifacts. Chats are working sessions; memory, artifacts and course
   knowledge persist across them.
2. **Artifacts are typed and editable**: doc, sheet, slides, quiz,
   flashcards, code, chart/HTML — each with its own editor or player,
   saved with version history, exportable to Office formats. There is no
   universal page format (option B was rejected: a quiz you can't take
   and slides you can't present).
3. **The model collaborates on artifacts** through narrow, structured
   edits that the user accepts or undoes; additions from sources are
   cited and pass the citation gate.
4. **Memory is read as a generated summary**, never as the full raw
   record; the user can reset it per course or overall.
5. **Syllabus dates** are extracted with a standing "double-check with
   Canvas or your course site" note.
6. **No audio or video overviews.**
7. **K2 Horizon waits** for upstream llama.cpp support; adding a model
   from a Hugging Face GGUF link or a local file must be easy.

## Consequences

- New tables: conversations, messages, artifacts, artifact_versions,
  course_dates, the student model, user memory, connections, user models
  (plan §5).
- The `.course` format moves to version 2 to carry chats and artifacts.
- Every artifact type gets eval cases before its generation ships.
