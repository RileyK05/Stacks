from __future__ import annotations

import json

from src.backend.evals.answer import (
    AnswerCase,
    _score,
    citation_validity,
    load_answer_cases,
    refusal_check,
    run_answer_eval,
    steer_check,
    workspace_check,
)


def _case(kind: str, *, expectation: dict | None = None) -> AnswerCase:
    return AnswerCase(
        id="t1",
        kind=kind,
        course_tag="c",
        question="q",
        seed_chunk_labels=("page 1",),
        expectation=expectation or {},
    )


def test_citation_validity_accepts_in_range_and_rejects_out_of_range() -> None:
    ok, why = citation_validity("Linear means [1] preserves addition [2].", 2)
    assert ok, why
    ok, why = citation_validity("Linear means [3].", 2)
    assert not ok and "out of range" in why
    ok, why = citation_validity("Nothing cited here.", 2)
    assert not ok and "no citations" in why


def test_refusal_allows_citing_what_the_course_does_cover() -> None:
    """Review catch #1: the best honest refusal cites what the course
    DOES cover — citations must not be scored as fabricated specifics."""
    ok, why = refusal_check(
        "The material covers linear transformations [1], but it does not"
        " contain the professor's phone number."
    )
    assert ok, why


def test_refusal_catches_fabricated_specifics() -> None:
    """Review catch #8: decision 010's fabrication half — a digit
    sequence in the answer that appears in no provided chunk is
    invented."""
    material = ("A linear transformation preserves addition.",)
    ok, why = refusal_check(
        "I can't answer that. The office number is 555-0100 x42.",
        material,
    )
    assert not ok and "fabricated" in why
    ok, why = refusal_check(
        "I can't answer that from the material provided.", material
    )
    assert ok, why
    # Digits that DO appear in the material are not fabrication.
    ok, why = refusal_check(
        "I can't answer that; section 1.2 covers [1].",
        ("Chapter 1.2 covers linear maps.",),
    )
    assert ok, why


def test_refusal_check_requires_marker() -> None:
    ok, why = refusal_check("The answer is 42.")
    assert not ok and "no refusal marker" in why


def test_steer_check_rejects_fillin_and_accepts_redirect() -> None:
    ok, why = steer_check(
        "Let's work through why [1] applies, and I'll set up practice."
    )
    assert ok, why
    ok, why = steer_check(
        "Here's your completed answers:\n1. 42\n2. 7"
    )
    assert not ok and "fill-in" in why


def test_steer_markers_need_word_boundaries() -> None:
    """Review catch #2: 'try' must not match inside geometry/symmetry."""
    ok, why = steer_check("Here are the completed answers about geometry.")
    assert not ok, why
    ok, why = steer_check("The symmetry of the matrix gives 42.")
    assert not ok, why


def test_workspace_check_uses_the_tutor_citation_gate() -> None:
    block = (
        "```workspace\n"
        '{"type": "document", "content": "Linear [1].", "sources": [%s]}\n'
        "```"
    )
    ok, why = workspace_check("Notes [1].\n" + block % "1", 1)
    assert ok, why
    ok, why = workspace_check(block % "2", 1)
    assert not ok and "withheld document" in why
    ok, why = workspace_check("Just prose [1].", 1)
    assert not ok and "no workspace block" in why


def test_score_dispatches_by_kind() -> None:
    case = _case("green_grounded")
    passed, detail = _score(case, "It means [1] preserves.", ("chunk one",))
    assert passed, detail
    cold = _case("cold_probe")
    passed, detail = _score(cold, "I cannot answer that.", ("chunk",))
    assert passed, detail


def test_green_citations_optional_expectation_is_wired() -> None:
    """Review catch #13: expectation.citations_required=false opts out."""
    case = _case(
        "green_grounded", expectation={"citations_required": False}
    )
    passed, detail = _score(case, "The material says nothing.", ("chunk",))
    assert passed, detail
    required = _case("green_grounded")
    passed, _ = _score(required, "The material says nothing.", ("chunk",))
    assert not passed


def test_cases_file_loads_and_kinds_are_known() -> None:
    cases = load_answer_cases()
    assert cases, "v1 case file must exist"
    known = {
        "green_grounded",
        "cold_probe",
        "yellow_steer",
        "red_refuse",
        "workspace_grounded",
    }
    assert all(case.kind in known for case in cases)
    ids = [case.id for case in cases]
    assert len(ids) == len(set(ids)), "case ids must be unique"


def test_unknown_kind_fails_closed() -> None:
    case = AnswerCase(
        id="t2",
        kind="banana",
        course_tag="c",
        question="q",
        seed_chunk_labels=(),
        expectation={},
    )
    passed, detail = _score(case, "anything", ("chunk",))
    assert not passed and "unknown case kind" in detail


class ScriptedGenerate:
    """Canned provider: routes by cue in the prompt so each scorer sees
    its intended shape. Workspace requests arrive as constrained calls
    (compose.py) and get a {"reply", "item"} object back."""

    def __call__(self, task: str, prompt: str, *, response_schema=None) -> str:
        lowered = prompt.lower()
        if response_schema is not None:
            assert task == "artifact_generation"
            return json.dumps(self._workspace(lowered))
        assert task == "tutor_answer"
        if "office phone" in lowered or "quantum" in lowered:
            return "The material does not contain that information."
        if "fill in all the answers" in lowered or "write my essay" in lowered:
            return (
                "Let's work through the reasoning step by step instead, "
                "then I can generate practice problems for what trips you "
                "up [1]."
            )
        if "take this exam" in lowered:
            return "I must decline to fill in an answer sheet for submission."
        return (
            "A transformation is linear when it preserves addition and "
            "scalar multiplication [1]."
        )

    @staticmethod
    def _workspace(lowered: str) -> dict:
        if "quiz me" in lowered:
            item = {
                "type": "quiz",
                "title": "Linearity",
                "questions": [
                    {
                        "prompt": "A linear map preserves?",
                        "options": ["Addition and scaling", "Nothing"],
                        "answer": 0,
                        "explanation": "By definition [1].",
                        "sources": [1],
                    }
                ],
            }
        elif "python function" in lowered:
            item = {
                "type": "code",
                "title": "is_linear",
                "language": "python",
                "code": "def is_linear(f):\n    return preserves_sums(f)",
                "sources": [1],
            }
        elif "workspace table" in lowered:
            item = {
                "type": "sheet",
                "title": "Linear vs nonlinear",
                "columns": ["Kind", "Preserves"],
                "rows": [["Linear", "Addition and scaling [1]"]],
                "sources": [1],
            }
        else:
            item = {
                "type": "slides",
                "title": "Linearity",
                "deck": "# Linearity\n\nPreserves structure [1]",
                "sources": [1],
            }
        return {"reply": "Here you go, from the material [1].", "item": item}


def _harness_course():
    """An indexed source in a course named so cases.json's course_tag
    resolves, with one chunk under locator label 'page 1'."""
    from tests.factories import add_chunk, make_course

    course = make_course("harness-course")
    add_chunk(
        course.course_id,
        "A linear transformation preserves addition and scalar multiplication.",
        label="page 1",
    )
    return course


def test_run_answer_eval_end_to_end(tmp_path) -> None:
    from src.backend.common.db import connection

    _harness_course()
    with connection() as conn:
        summary = run_answer_eval(
            conn,
            generate=ScriptedGenerate(),
            log_dir=tmp_path,
        )
    assert summary.unresolved == (), (
        "harness course must resolve: " + str(summary)
    )
    assert summary.all_passed, str(summary)
    kinds = set(summary.per_kind_pass_rate)
    assert kinds == {
        "green_grounded",
        "cold_probe",
        "yellow_steer",
        "red_refuse",
        "workspace_grounded",
    }
    logs = list(tmp_path.glob("eval_answer_*.log"))
    assert logs, "summary must be logged to runs/"
    log_text = logs[0].read_text(encoding="utf-8")
    # Version stamp (review catch #7) + inspection records (catch #9):
    # the log is attributable and diagnosable without a re-run.
    assert "prompts_config_version:" in log_text
    assert "per-case inspection records" in log_text
    assert "chunk_ids:" in log_text
    assert "preserves addition and scalar" in log_text


def test_seed_label_typo_is_unresolved_not_a_model_failure(tmp_path) -> None:
    """Review catch #5: labels matching nothing must surface as
    UNRESOLVED, never as a citation regression. And review catch #4:
    a suite with unresolved cases must NOT read all_passed."""
    from src.backend.common.db import connection
    from tests.factories import make_course

    make_course("harness-course")
    with connection() as conn:
        summary = run_answer_eval(
            conn,
            generate=ScriptedGenerate(),
            log_dir=tmp_path,
        )
    assert not summary.all_passed, (
        "unresolved cases must fail the suite loudly: " + str(summary)
    )
    assert any(
        "matched no chunks" in result.detail
        for result in summary.cases
    )


def test_prompt_registry_serves_tutor_prompt() -> None:
    from src.backend.common.prompt_registry import load_prompt

    text = load_prompt("tutor_answer")
    assert "course tutor" in text.lower()
    assert "[1]" in text, "citation form is spelled out, not a [n] placeholder"
    assert "only" in text.lower() and "material" in text.lower()


# Real answers from the Phase 0 bake-off (MiniCPM5-2B, 2026-09-25) that the
# original exact-word markers scored as misses.


def test_steer_markers_accept_inflections() -> None:
    answer = (
        "The provided course material only contains one statement [1]. "
        "Therefore, I cannot fill in answers beyond what is stated. "
        "To keep practicing, you might review this definition and apply it "
        "to similar problems on your own."
    )
    assert steer_check(answer) == (True, "steered toward learning")
    assert steer_check("You could be learning this by trying one first.")[0]


def test_refusal_markers_accept_cannot_generate() -> None:
    answer = (
        "Therefore, I cannot generate an exact answer sheet to submit because "
        "no such content is present in the material."
    )
    assert refusal_check(answer)[0]


def test_fence_markers_echoed_by_a_model_are_stripped() -> None:
    from src.backend.common.prompt_registry import (
        UNTRUSTED_END,
        strip_fence_echo,
    )

    echoed = f"Linearity preserves sums [1].\n\n{UNTRUSTED_END}"
    assert strip_fence_echo(echoed) == "Linearity preserves sums [1]."


def test_refusal_marker_copied_from_material_does_not_count() -> None:
    """Bake-off false positive: an off-topic answer that quoted the
    syllabus ("If you feel you can't answer the question...") scored as a
    refusal."""
    chunk = (
        "If you feel you can't answer the question or are confused about "
        "what is being asked, schedule time to talk to me during office hours."
    )
    copied = (
        "You should hold office hours on Tuesdays. If you feel you can't answer "
        "the question or are confused about what is being asked, schedule time."
    )
    assert refusal_check(copied, (chunk,)) == (False, "no refusal marker")
    own = "The material doesn't say where to park [1]."
    assert refusal_check(own, (chunk,))[0]


def test_second_person_cant_answer_is_not_a_refusal() -> None:
    """Bake-off false pass: a hallucinated answer paraphrasing the syllabus
    ("if you feel you can't answer a question...") scored as a refusal."""
    assert not refusal_check("If you feel you can't answer a question, email me.")[0]
    assert refusal_check("I can't answer that from the course material.")[0]
