from uuid import uuid4

from src.backend.common import artifacts_repo, provider
from src.backend.common.db import connection
from src.backend.rag import generated
from src.backend.rag.config import load_policy
from src.backend.rag.segment import segment
from src.backend.retrieval import funnel, rerank, trace
from src.backend.retrieval.config import load_rerank_policy, load_retrieval_policy
from tests.factories import insert_chunk, insert_source, make_course


def test_previous_index_remains_selectable_after_failed_replacement(client):
    course = make_course()
    source = insert_source(course.course_id)
    passage = insert_chunk(source, "The earlier variance argument is still available.")
    with connection() as conn:
        conn.execute(
            "INSERT INTO source_indexes"
            "(source_id,revision,file_hash,extraction_version,"
            "segmentation_version,semantic_used) VALUES (?, 'old', '', '1', '1', 0)",
            (source,),
        )
        conn.execute(
            "UPDATE sources SET status = 'failed' WHERE source_id = ?", (source,)
        )
        conn.commit()
        found = funnel.keyword_seam(conn, course.course_id, "variance", 10, [source])
        assert list(found) == [passage]
    visible = client.get(f"/courses/{course.course_id}/sources").json()[0]
    assert visible["status"] == "failed" and visible["has_index"]


def test_table_list_and_equation_keep_their_explanatory_text():
    samples = [
        ("The requirements are:\n\n- Independence\n\n- Finite variance", "list"),
        ("Election totals:\n\n| Group | Count |\n| A | 20 |", "table"),
        ("$$ y = mx + b $$\n\nwhere m is slope and b is the intercept.", "equation"),
    ]
    for text, kind in samples:
        result = segment(text, load_policy(), token_count=len)
        assert len(result.passages) == 1
        assert result.passages[0].kind == kind
        assert text[result.passages[0].start : result.passages[0].end] == text


def test_single_newline_text_is_split_to_the_token_target():
    """A PDF page break is one newline, so blank-line cuts never fire."""
    line = "The Hart-Celler Act capped immigration at two hundred ninety thousand. "
    text = (line * 800).strip()
    text += "\n• item one stays with its own block when the list is long enough"
    policy = load_policy()
    result = segment(text, policy, token_count=len)
    assert result.passages
    assert all(
        len(text[span.start : span.end]) <= policy.target_tokens
        for span in result.passages
        if span.kind == "passage"
    )
    assert "".join(text[span.start : span.end] for span in result.passages) == text


def test_passages_do_not_cross_page_breaks():
    page = "This page explains the treaty terms in one continuous paragraph. " * 30
    text = page + "\n" + page
    second = len(page) + 1
    policy = load_policy()
    result = segment(text, policy, token_count=len, page_breaks=(second,))
    assert all(not (span.start < second < span.end) for span in result.passages)
    assert "".join(text[span.start : span.end] for span in result.passages) == text


def test_thin_heading_is_merged_into_the_paragraph():
    paragraph = (
        "The reading then explains the community that formed after the war. " * 6
    )
    text = f"Heading\n\n\n\n{paragraph}"
    result = segment(text, load_policy(), token_count=len)
    assert result.passages
    assert all(
        sum(char.isalnum() for char in text[span.start : span.end]) >= 40
        for span in result.passages
    )
    assert "".join(text[span.start : span.end] for span in result.passages) == text


def test_thin_neighbor_does_not_take_a_candidate_slot(monkeypatch):
    course = make_course()
    source = insert_source(course.course_id)
    anchor = insert_chunk(
        source,
        "The variance formula is sigma squared.",
        chunk_index=0,
        embedding=[1, 0],
    )
    blank = insert_chunk(source, "\n\n", chunk_index=1, embedding=[1, 0])
    monkeypatch.setattr(provider, "embedding_token_count", len)
    with connection() as conn:
        result = funnel.retrieve(
            conn,
            course.course_id,
            "variance formula",
            load_retrieval_policy(),
            embedding_model="test-embed",
            source_ids=[source],
        )
    found = {candidate.chunk_id for candidate in result.candidates}
    assert anchor in found
    assert blank not in found


def test_qualification_survives_reranking_and_source_selection(monkeypatch):
    course = make_course()
    source = insert_source(course.course_id)
    anchor = insert_chunk(
        source,
        "The variance formula is sigma squared.",
        chunk_index=0,
        embedding=[1, 0],
    )
    qualifier = insert_chunk(
        source,
        "However, this assumes independent samples.",
        chunk_index=1,
        embedding=[0, 1],
    )
    excluded = insert_source(course.course_id)
    insert_chunk(excluded, "variance formula", embedding=[1, 0])
    monkeypatch.setattr(provider, "embedding_token_count", len)
    with connection() as conn:
        result = funnel.retrieve(
            conn,
            course.course_id,
            "variance formula",
            load_retrieval_policy(),
            embedding_model="test-embed",
            source_ids=[source],
        )
    chosen = rerank.select_for_generation(
        "variance formula",
        result.candidates,
        load_rerank_policy().model_copy(update={"generation_k": 1}),
    )
    assert [c.chunk_id for c in chosen] == [anchor, qualifier]
    assert chosen[1].context_for == {anchor}
    assert {c.source_id for c in chosen} == {source}
    with connection() as conn:
        assert not funnel.retrieve(
            conn,
            course.course_id,
            "variance formula",
            load_retrieval_policy(),
            source_ids=[],
        ).candidates


def test_saved_material_opt_in_versions_and_original_support(client):
    course = make_course()
    a, b = [insert_source(course.course_id) for _ in range(2)]
    first = insert_chunk(a, "The transformation preserves addition.")
    second = insert_chunk(b, "It also preserves scalar multiplication.")
    artifact = artifacts_repo.create(
        course.course_id,
        kind="doc",
        title="Revision aid",
        content={"markdown": "Linearity cheat sheet [1, 2]"},
        sources=[first, second],
        author="model",
    )
    settings_url = f"/courses/{course.course_id}/retrieval-settings"
    assert client.get(settings_url).json() == {"include_generated": False}
    with connection() as conn:
        assert generated.lookup(conn, course.course_id, ["linearity"], 10, None) == []
    assert client.put(settings_url, json={"include_generated": True}).status_code == 200
    with connection() as conn:
        assert not generated.lookup(conn, course.course_id, ["linearity"], 10, [a])
        rows = generated.lookup(conn, course.course_id, ["linearity"], 10, [a, b])
        assert {r["chunk_id"] for r in rows} == {first, second}
        assert all("cheat sheet" not in r["text"] for r in rows)
        assert (
            conn.execute("SELECT count(*) AS n FROM learning_observations").fetchone()[
                "n"
            ]
            == 0
        )
    artifacts_repo.save(
        course.course_id,
        artifact.artifact_id,
        expected_version=1,
        title="Revision aid",
        content={"markdown": "Homogeneity reminder [1, 2]"},
        sources=[first, second],
        author="you",
    )
    # A student edit to a saved model artifact remains eligible as a study aid.
    # Its provenance must persist across versions, just as adoption does.
    with connection() as conn:
        assert not generated.lookup(conn, course.course_id, ["linearity"], 10, None)
        revised = generated.lookup(conn, course.course_id, ["homogeneity"], 10, None)
        assert len(revised) == 2 and all(r["generated_version"] == 2 for r in revised)
    client.delete(f"/courses/{course.course_id}")
    assert client.get(settings_url).status_code == 404


def test_generated_lookup_has_lower_weight_than_original_hits():
    course = make_course()
    source = insert_source(course.course_id)
    a = insert_chunk(source, "Original")
    b = insert_chunk(source, "Supporting original", chunk_index=1)

    def candidate(identity, layer):
        return funnel.Candidate(
            identity, source, uuid4(), 0, "Text", frozenset({layer}), 1
        )

    result = funnel.fuse(
        {a: candidate(a, funnel.KEYWORD)},
        {},
        policy=load_retrieval_policy(),
        generated_hits={b: candidate(b, funnel.GENERATED)},
    )
    assert result[0].chunk_id == a and result[0].rank > result[1].rank


def test_partial_citation_and_ordered_continuation(client, monkeypatch):
    course = make_course()
    source = insert_source(course.course_id)
    text = "Theorem.\n" + "Long proof step. " * 500 + "QED"
    identity = insert_chunk(source, text)
    with connection() as conn:
        locator = conn.execute(
            "SELECT locator_id FROM chunks WHERE chunk_id = ?", (identity,)
        ).fetchone()["locator_id"]
        candidate = funnel.Candidate(
            identity,
            source,
            locator,
            0,
            text,
            frozenset({funnel.EMBEDDING}),
            1,
            window_start=7000,
        )
        monkeypatch.setattr(provider, "embedding_token_count", len)
        selected = rerank.bound_passages((candidate,))
        stored = trace.record_trace(
            conn, course.course_id, "end of proof", funnel.RetrievalResult(selected)
        )
        conn.commit()
    response = client.get(
        f"/courses/{course.course_id}/traces/{stored.trace_id}/citations"
    )
    citation = response.json()[0]
    assert citation["partial"] and citation["char_start"] == 7000
    assert citation["text"] == text[7000 : citation["char_end"]]
    url = f"/courses/{course.course_id}/sources/{source}/chunks/{identity}"
    portions, start = [], 0
    while True:
        window = client.get(url, params={"start": start, "max_chars": 1024}).json()
        assert window["char_start"] == start and window["text_length"] == len(text)
        portions.append(window["text"])
        if window["next_start"] is None:
            break
        start = window["next_start"]
    assert "".join(portions) == text
    other = make_course()
    assert (
        client.get(url.replace(str(course.course_id), str(other.course_id))).status_code
        == 404
    )


def test_material_budget_bounds_multiple_long_proofs(monkeypatch):
    monkeypatch.setattr(provider, "embedding_token_count", len)
    candidates = tuple(
        funnel.Candidate(
            uuid4(),
            uuid4(),
            uuid4(),
            i,
            "proof " * 1000,
            frozenset({funnel.KEYWORD}),
            1,
        )
        for i in range(10)
    )
    selected = rerank.select_for_generation("proof", candidates)
    assert selected and all(c.partial for c in selected)
    assert (
        sum(len(c.text) for c in selected) <= load_policy().generation_material_tokens
    )


def test_office_citations_match_the_excerpt_used_by_generation(client, monkeypatch):
    from src.backend.tutor import office
    from tests.conftest import configure_test_provider

    course = make_course()
    source = insert_source(course.course_id)
    original = "Linearity preserves addition and scaling. " + "Proof step. " * 1000
    insert_chunk(source, original)
    monkeypatch.setattr(provider, "embedding_token_count", len)
    calls = configure_test_provider(
        monkeypatch, "It preserves addition and scaling [1]."
    )
    with connection() as conn:
        result = office.answer(
            conn,
            course.course_id,
            office.OfficeAction.EXPLAIN,
            host="word",
            context="linearity",
            policy=load_retrieval_policy(),
        )
        conn.commit()
    cited = result.citations[0]
    assert len(cited.text) <= load_policy().retrieved_passage_tokens
    assert original.startswith(cited.text) and cited.text in calls[0]["prompt"]
    assert "partial passage" in cited.label
    viewed = client.get(
        f"/courses/{course.course_id}/traces/{result.trace_id}/citations"
    )
    assert viewed.json()[0]["text"] == cited.text
    assert viewed.json()[0]["partial"]


def test_editing_saved_material_does_not_reload_unbounded_originals(monkeypatch):
    from src.backend.artifacts.edit import _material

    course = make_course()
    source = insert_source(course.course_id)
    original = "A long original argument. " * 500
    cited = insert_chunk(source, original)
    artifact = artifacts_repo.create(
        course.course_id,
        kind="doc",
        title="Notes",
        content={"markdown": "Original argument [1]"},
        sources=[cited],
    )
    monkeypatch.setattr(provider, "embedding_token_count", len)
    with connection() as conn:
        material, _ = _material(
            conn,
            course.course_id,
            artifact,
            artifact.content,
            "Improve this wording",
            load_retrieval_policy(),
            query_embedding=None,
            embedding_model=None,
        )
    assert material.chunk_ids == [cited]
    assert material.texts[0] == material.candidates[0].text
    assert original.startswith(material.texts[0])
    assert material.candidates[0].partial
    assert len(material.texts[0]) <= load_policy().retrieved_passage_tokens
