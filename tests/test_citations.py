from src.backend.common.citations import cited_numbers, marker_numbers, strip_citations
from src.backend.evals.answer import citation_validity


def test_grouped_and_descending_markers_expand_without_phantom_numbers():
    assert cited_numbers("Supported [1, 3–4] and reversed [5-3].") == {
        1,
        3,
        4,
        5,
    }
    assert marker_numbers("5-3") == [5, 4, 3]
    assert 0 in cited_numbers("bad [1-1000000000]")


def test_subscripts_code_and_markdown_literals_are_not_citations():
    text = (
        "Use arr[0] and a[0], then cite D[99], linearity[1], answer[99]. "
        "Inline `arr[99]`;\n\n```py\nx = b[4]\n```"
    )
    assert cited_numbers(text) == {1, 99}
    stripped = strip_citations(text)
    assert "arr[0]" in stripped and "a[0]" in stripped and "arr[99]" in stripped
    assert "b[4]" in stripped
    assert "D[99]" not in stripped and "answer[99]" not in stripped


def test_eval_accepts_grouped_citations():
    assert citation_validity("The result follows [1, 3-4].", 4) == (
        True,
        "3 valid citations",
    )
