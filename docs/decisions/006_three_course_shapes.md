# The three course shapes

**Status:** accepted, 2026-09-05

## Decision

Every course is in exactly one of three visibility shapes, and the whole
codebase treats these as the complete, closed set. This is a foundational
fact for all current and future development.

| Shape | Anonymous visitor | Signed-in, not enrolled | Ways to gain use access |
|---|---|---|---|
| `private` | sees nothing | sees nothing | owner invitation only |
| `invite_only` | sees nothing (no catalog listing, no code exposure) | join via code only | owner invitation or join code |
| `public` | sees the course, its published objects, and its join code | self-enroll or join code | self-enroll, join code, or owner invitation |

**Invariants that hold in every shape (unchanged by this decision):**

- Only the course owner may mutate canonical course objects and base sources,
  change visibility, rotate the join code, revoke enrollments, or list members.
- Enrollment grants use (retrieval, generation), never control.
- Learner artifacts, attempts, mastery, conversations, recommendations, and
  tutor preferences are private to the learner in every shape.
- Raw uploaded sources are enrolled-scope; no shape publishes them.

**Where each rule lives (both layers must agree; never change one alone):**

- Application policy: `src/backend/common/permissions.py`
  (`can_view_course`, `can_self_enroll`, `can_join_with_code`,
  `can_use_sources`, `can_generate_materials`, `can_manage_object`, ...).
- Database invariants: enrollment triggers in migrations 011/015 (self-service
  requires `public`; join-code enrollment requires `public` or `invite_only`;
  owner can never be enrolled), plus course-object access triggers.

## Consequences

- A new visibility value requires a deliberate decision and changes to the
  DB enum, the Python enum, the API pre-checks, and the triggers together.
- The public catalog (`/courses/public`) lists only `public` courses.
- Join-code exposure: `public` exposes the code to everyone; `invite_only`
  exposes it to the owner only; `private` exposes none.
- Visibility transitions: public -> restricted (invite_only/private) is a
  versioned lifecycle transition with learner archive grace; restricted ->
  public is a plain owner update.
- `permissions.py` is the single application-side source of truth; endpoints
  should call it rather than re-deriving checks inline.