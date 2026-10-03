"""A model-backed judge for the semantic answer cases (B-06).

The mechanical suite cannot see whether an answer is *correct* — it checks
citations, markers, and structure. Independently reviewed cases in
`data/eval/answer/semantic_cases.json` carry a `rubric` and are scored by
asking a model to apply it, with the seeded material and the answer in
front of it. The judge is a plain callable so tests inject a scripted one
and a real bake-off run injects the configured provider.

This is deliberately a second, separate suite: a green mechanical run
never depends on a judge, and a judge score never overwrites the
deterministic one. The judge's verdict is the model's opinion, recorded
verbatim, not ground truth.
"""

from __future__ import annotations

from src.backend.common import provider
from src.backend.common.providers import ProviderChoice
from src.backend.evals.answer import AnswerCase, JudgeFn

_JUDGE_PROMPT = """\
You are grading a tutor's answer against a course passage and a rubric.
Decide whether the answer satisfies the rubric WITHOUT using outside
knowledge: an answer is only correct if the passage supports it.

Passage(s):
{material}

Question asked:
{question}

Tutor's answer:
{answer}

Rubric: {rubric}

Reply with one line: "PASS: <reason>" or "FAIL: <reason>".
"""


def make_judge(choice: ProviderChoice | None = None) -> JudgeFn:
    def judge(
        case: AnswerCase, answer_text: str, chunk_texts: tuple[str, ...]
    ) -> tuple[bool, str]:
        rubric = str(case.expectation.get("rubric", "")).strip()
        material = "\n\n".join(chunk_texts) or "(no material provided)"
        prompt = _JUDGE_PROMPT.format(
            material=material,
            question=case.question,
            answer=answer_text[:4000],
            rubric=rubric,
        )
        try:
            result = provider.generate("answer_eval_judge", prompt, choice=choice)
        except provider.ProviderUnavailableError as error:
            # Never a silent pass: an unavailable judge is a failure the
            # operator must see, not a green case.
            return False, f"judge unavailable: {error}"
        verdict = " ".join(result.text.split())
        passed = verdict.upper().startswith("PASS")
        return passed, f"judge: {verdict[:200]}"

    return judge
