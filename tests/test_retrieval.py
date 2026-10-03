"""Hybrid retrieval funnel tests (decision 008).

Fixtures build course passages, locators, vectors and similarity edges directly.
Checks cover selected sources, fusion caps/quotas, attribution and saved traces;
ingestion tests cover publication of these rows.
"""

from uuid import uuid4

import pytest
from src.backend.common.db import connection
from src.backend.retrieval import funnel, trace
from src.backend.retrieval.config import load_retrieval_policy
from src.backend.retrieval.funnel import RetrievalPolicy
from tests.factories import (
    add_chunk,
    chunk_source_locator,
    insert_chunks,
    insert_source,
    make_course,
    rename_course,
    set_source_status,
)

QUERY = "when did we use linearity"


def _policy(**overrides) -> RetrievalPolicy:
    base = load_retrieval_policy()
    if not overrides:
        return base
    data = base.model_dump()
    data.update(overrides)
    return RetrievalPolicy.model_validate(data)


@pytest.fixture
def course():
    return make_course("Retrieval Course")


# --- seam contracts -------------------------------------------------------


def test_keyword_seam_finds_exact_terms(course) -> None:
    hit = add_chunk(course.course_id, "linearity of transformations")
    add_chunk(course.course_id, "unrelated text about integrals")
    policy = _policy()
    with connection() as conn:
        candidates = funnel.keyword_seam(
            conn, course.course_id, QUERY, policy.keyword_limit
        )
    assert str(hit) in {str(cid) for cid in candidates}
    assert len(candidates) == 1


def test_keyword_seam_empty_query_is_safe(course) -> None:
    add_chunk(course.course_id, "linearity everywhere")
    with connection() as conn:
        assert funnel.keyword_seam(conn, course.course_id, "   ", 20) == {}


def test_embedding_seam_dormant_and_active(course) -> None:
    policy = _policy()
    with connection() as conn:
        dormant = funnel.embedding_seam(
            conn, course.course_id, None, "test-embed", policy.embedding_limit
        )
        assert dormant == {}
        chunk_id = add_chunk(
            course.course_id,
            "linearity of transformations",
            embedding=[1.0, 0.0],
        )
        add_chunk(
            course.course_id,
            "unrelated integrals",
            embedding=[0.0, 1.0],
        )
        active = funnel.embedding_seam(
            conn,
            course.course_id,
            [1.0, 0.1],
            "test-embed",
            policy.embedding_limit,
        )
    assert str(chunk_id) == str(next(iter(active)))


def test_embedding_seam_ignores_non_finite_query(course) -> None:
    add_chunk(course.course_id, "linearity of transformations", embedding=[1.0, 0.0])
    with connection() as conn:
        candidates = funnel.embedding_seam(
            conn,
            course.course_id,
            [float("nan"), 0.0],
            "test-embed",
            10,
        )
    assert candidates == {}


def test_source_filter_is_applied_before_candidate_limit(course) -> None:
    for _ in range(90):
        source_id = insert_source(course.course_id)
        insert_chunks(source_id, 1, "linearity linearity linearity linearity")
    selected_source = insert_source(course.course_id)
    from tests.factories import insert_chunk

    selected_chunk = insert_chunk(selected_source, "linearity")
    policy = _policy()
    with connection() as conn:
        result = funnel.retrieve(
            conn,
            course.course_id,
            "linearity",
            policy,
            source_ids=[selected_source],
        )
    assert [candidate.chunk_id for candidate in result.candidates] == [selected_chunk]


# --- fusion ---------------------------------------------------------------


def test_fuse_single_source_is_never_starved(course) -> None:
    """The #3 lesson, kept by construction: five keyword hits sharing ONE
    source all surface — with no competing source there is nothing to
    allocate against."""

    source_id = insert_source(course.course_id)
    insert_chunks(source_id, 5)
    policy = _policy(final_k=10)
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
    fused = funnel.fuse(keyword, {}, {**{}, **{}}, policy=policy)
    assert len(fused) == 5


@pytest.mark.parametrize("ranks", [(2.0, 4.0), (2.0, 2.0)])
def test_fuse_preserves_candidates_for_reuse(ranks) -> None:
    source_id = uuid4()
    candidates = [
        funnel.Candidate(
            chunk_id=uuid4(),
            source_id=source_id,
            locator_id=uuid4(),
            chunk_index=index,
            text="linearity",
            layers=frozenset({funnel.KEYWORD}),
            rank=rank,
        )
        for index, rank in enumerate(ranks)
    ]
    keyword = {candidate.chunk_id: candidate for candidate in candidates}
    first = funnel.fuse(keyword, {}, {**{}, **{}}, policy=_policy())
    second = funnel.fuse(keyword, {}, {**{}, **{}}, policy=_policy())
    assert tuple(candidate.rank for candidate in candidates) == ranks
    assert first == second
    assert {candidate.chunk_id for candidate in first} == set(keyword)


def test_fuse_equal_relevance_splits_evenly(course) -> None:
    """Three sources with EQUAL relevance (all-equal keyword ranks
    normalize to the same 0.5): the split is even — 2/2/2 with k=6.
    Equal evidence, equal share; no unit accident decides it."""
    for _ in range(3):
        source_id = insert_source(course.course_id)
        insert_chunks(source_id, 5)
    policy = _policy(final_k=6)
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
    fused = funnel.fuse(keyword, {}, {**{}, **{}}, policy=policy)
    assert len(fused) == 6
    counts: dict[str, int] = {}
    for candidate in fused:
        counts[str(candidate.source_id)] = counts.get(str(candidate.source_id), 0) + 1
    assert set(counts.values()) == {2}


def test_fuse_embedding_orders_final_set(course) -> None:
    add_chunk(course.course_id, "linearity barely relevant", embedding=[0.9, 0.1])
    high = add_chunk(
        course.course_id, "linearity deeply relevant", embedding=[1.0, 0.0]
    )
    policy = _policy(final_k=2)
    query_embedding = [1.0, 0.0]
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
        embeddings = funnel.embedding_seam(
            conn, course.course_id, query_embedding, "test-embed", 20
        )
        fused = funnel.fuse(keyword, embeddings, {**{}, **{}}, policy=policy)
    assert [str(candidate.chunk_id) for candidate in fused][0] == str(high)


def test_fuse_keyword_orders_strongest_evidence_first(course) -> None:
    """Regression (2026-09-22): keyword ranks were normalized with a sign
    flip, so the HIGHEST ts_rank chunk normalized to 0.0 and sank below
    the weakest. Every seam ranks higher-is-better; the strongest keyword
    evidence must come out on top."""
    strong = add_chunk(
        course.course_id, "linearity linearity linearity linearity term rich"
    )
    weak = add_chunk(course.course_id, "a passing linearity mention")
    policy = _policy(final_k=10)
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
        fused = funnel.fuse(keyword, {}, {**{}, **{}}, policy=policy)
    ranks = {str(candidate.chunk_id): candidate.rank for candidate in fused}
    assert ranks[str(strong)] > ranks[str(weak)], (
        "highest ts_rank must normalize highest, not lowest"
    )
    assert str(fused[0].chunk_id) == str(strong)


def test_fuse_graph_orders_strongest_first(course) -> None:
    """The dependency seam's rank is arrival position negated (best at 0,
    higher is better). Normalization must keep that direction."""
    from src.backend.retrieval.funnel import Candidate as _Candidate

    best = uuid4()
    mid = uuid4()
    worst = uuid4()
    dep = frozenset({"graph"})

    def _c(chunk_id, idx, text, rank):
        return _Candidate(chunk_id, uuid4(), uuid4(), idx, text, dep, rank)

    seam = {
        best: _c(best, 0, "best", 0.0),
        mid: _c(mid, 1, "mid", -1.0),
        worst: _c(worst, 2, "worst", -2.0),
    }
    policy = _policy(final_k=10)
    fused = funnel.fuse({}, {}, {**{}, **seam}, policy=policy)
    order = [str(candidate.chunk_id) for candidate in fused]
    assert order == [str(best), str(mid), str(worst)]


def test_fuse_embedding_only_quota(course) -> None:
    keyword_hit = add_chunk(course.course_id, "linearity exact term")
    semantic_only_1 = add_chunk(
        course.course_id, "preserving structure", embedding=[1.0, 0.1]
    )
    semantic_only_2 = add_chunk(
        course.course_id, "structure preservation", embedding=[0.99, 0.05]
    )
    policy = _policy(embedding_only_quota=1, final_k=10)
    query_embedding = [1.0, 0.0]
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
        embeddings = funnel.embedding_seam(
            conn, course.course_id, query_embedding, "test-embed", 20
        )
        fused = funnel.fuse(keyword, embeddings, {**{}, **{}}, policy=policy)
    ids = {str(candidate.chunk_id) for candidate in fused}
    assert str(keyword_hit) in ids
    semantic_ids = (str(semantic_only_1), str(semantic_only_2))
    semantic_in = sum(1 for cid in semantic_ids if cid in ids)
    assert semantic_in == 1, "embedding-only quota: one semantic extra admitted"


def test_full_funnel_and_trace_persistence(course) -> None:
    chunk = add_chunk(course.course_id, "linearity of transformations")
    policy = _policy()
    with connection() as conn:
        result = funnel.retrieve(conn, course.course_id, QUERY, policy)
        stored = trace.record_trace(conn, course.course_id, QUERY, result)
        conn.commit()
    assert result.candidates
    assert result.layer_contribution.get("keyword", 0) >= 1
    assert str(chunk) in {str(candidate.chunk_id) for candidate in result.candidates}
    assert stored.chunk_ids == tuple(c.chunk_id for c in result.candidates)


def test_retrieval_dormant_seams_contribute_nothing(course) -> None:
    policy = _policy()
    with connection() as conn:
        result = funnel.retrieve(conn, course.course_id, QUERY, policy)
    assert result.candidates == ()
    assert result.layer_contribution == {}


# --- review-fix regressions (2026-09-13 external review) -----------------


def test_keyword_seam_survives_math_syntax(course) -> None:
    """Math notation must not crash FTS5 — operator characters are
    stripped before SQL sees them. This is the flagship seam; a math
    question is the target domain's most normal query."""
    chunk = add_chunk(course.course_id, "the function f of x equals x squared")
    with connection() as conn:
        candidates = funnel.keyword_seam(
            conn, course.course_id, "function f(x) = x^2 ?", 20
        )
    assert set(candidates) == {chunk}


def test_keyword_seam_handles_operator_heavy_queries(course) -> None:
    add_chunk(course.course_id, "limits and continuity of functions")
    with connection() as conn:
        for hostile in [
            "a & b",
            "a | b",
            "a ! b",
            "(unbalanced",
            "unbalanced)",
            "a <-> b",
            "a:b*c",
            "$$$",
            "",
            "   ",
            "x",
        ]:
            assert funnel.keyword_seam(conn, course.course_id, hostile, 20) == {}


def test_embedding_dimension_mismatch_is_excluded(course) -> None:
    """A different-dimension embedding (model swap debris) must be
    excluded, not silently zip-truncated into garbage ranks."""
    matching = add_chunk(course.course_id, "aligned vector", embedding=[1.0, 0.0])
    add_chunk(
        course.course_id,
        "wrong dimension vector",
        embedding=[1.0, 2.0, 3.0],
    )
    with connection() as conn:
        candidates = funnel.embedding_seam(
            conn, course.course_id, [1.0, 0.0], "test-embed", 20
        )
    assert list(candidates) == [matching]


def test_trace_records_per_chunk_layers(course) -> None:
    add_chunk(course.course_id, "linearity of transformations")
    policy = _policy()
    with connection() as conn:
        result = funnel.retrieve(conn, course.course_id, QUERY, policy)
        trace.record_trace(conn, course.course_id, QUERY, result)
        conn.commit()
        row = conn.execute(
            "SELECT retrieved_chunk_ids FROM retrieval_traces"
            " WHERE course_id = ? ORDER BY created_at DESC LIMIT 1",
            (course.course_id,),
        ).fetchone()
    payload = row["retrieved_chunk_ids"]
    assert "per_chunk_layers" in payload
    for entry in payload["per_chunk_layers"]:
        assert entry["layers"], "every cited chunk records its seams"


def test_eval_runner_exact_labels_and_unresolved(course, tmp_path) -> None:
    """page 1 must not match page 12 (exact label membership), and a case
    whose course_tag resolves to nothing is UNRESOLVED, never a pass."""
    from src.backend.retrieval import evals as evals_module

    rename_course(course.course_id, "EVAL-FIXTURE")
    add_chunk(course.course_id, "linearity of transformations", label="page 1")
    add_chunk(course.course_id, "other content here", label="page 12")

    cases_file = tmp_path / "cases.json"
    cases_file.write_text(
        '{"cases": ['
        '{"question": "when did we use linearity", "course_tag": "EVAL-FIXTURE",'
        ' "expected_labels": ["page 1"]},'
        '{"question": "nothing resolves", "course_tag": "NO-SUCH-COURSE",'
        ' "expected_labels": ["page 1"]}'
        "]}",
        encoding="utf-8",
    )
    policy = _policy()
    with connection() as conn:
        summary = evals_module.run_eval(conn, policy, cases_path=cases_file)
    assert len(summary.unresolved_cases) == 1
    resolved = [result for result in summary.cases if result.resolved]
    assert len(resolved) == 1
    assert resolved[0].hit
    assert summary.fused_recall == 1.0
    assert summary.seam_recall["keyword"] == 1.0


def test_eval_exact_label_no_substring_pass(course, tmp_path) -> None:
    """Expected 'page 1' must NOT hit when only 'page 12' is retrieved —
    the substring false-pass mode is closed."""
    from src.backend.retrieval import evals as evals_module

    rename_course(course.course_id, "EVAL-EXACT")
    add_chunk(course.course_id, "unrelated content", label="page 12")

    cases_file = tmp_path / "cases.json"
    cases_file.write_text(
        '{"cases": ['
        '{"question": "when did we use linearity", "course_tag": "EVAL-EXACT",'
        ' "expected_labels": ["page 1"]}'
        "]}",
        encoding="utf-8",
    )
    policy = _policy()
    with connection() as conn:
        summary = evals_module.run_eval(conn, policy, cases_path=cases_file)
    assert summary.fused_recall == 0.0
    assert not summary.cases[0].hit


def test_eval_counts_a_chunks_full_locator_span(course, tmp_path) -> None:
    from src.backend.retrieval import evals as evals_module

    chunk_id = add_chunk(course.course_id, "linearity", label="page 1")
    source_id, _ = chunk_source_locator(chunk_id)
    second_locator = uuid4()
    with connection() as conn:
        conn.execute(
            "INSERT INTO locators (locator_id, source_id, locator_type, start,"
            " end_value, label) VALUES (?, ?, 'page', '100', '200', 'page 2')",
            (second_locator, source_id),
        )
        conn.execute(
            "INSERT INTO chunk_locators (chunk_id, locator_id) VALUES (?, ?)",
            (chunk_id, second_locator),
        )
        conn.commit()

    cases_file = tmp_path / "cases.json"
    cases_file.write_text(
        '{"cases": [{"question": "linearity", "course_tag": "Retrieval Course",'
        ' "expected_labels": ["page 1", "page 2"]}]}',
        encoding="utf-8",
    )
    with connection() as conn:
        summary = evals_module.run_eval(conn, _policy(), cases_path=cases_file)
    assert summary.fused_recall == 1.0
    assert summary.seam_recall["keyword"] == 1.0
    assert summary.cases[0].retrieved_labels == ("page 1", "page 2")


def test_fuse_allocates_slots_by_relevance(course) -> None:
    """The ratified allocation: per-source relevance = best normalized
    chunk score; slots split proportionally with largest remainder.
    Three sources with clearly different relevance, built with the
    multi-chunk helpers so sources actually group chunks."""
    # Source A: two chunks, best dot 1.0
    src_a = insert_source(course.course_id)
    _insert_chunks_with_embedding(src_a, [(1.0, 0.0), (0.8, 0.1)])
    # Source B: one chunk, dot ~0.55
    src_b = insert_source(course.course_id)
    _insert_chunks_with_embedding(src_b, [(0.55, 0.0)])
    # Source C: one chunk, weak dot
    src_c = insert_source(course.course_id)
    _insert_chunks_with_embedding(src_c, [(0.1, 0.9)])
    policy = _policy(final_k=10)
    with connection() as conn:
        embeddings = funnel.embedding_seam(
            conn, course.course_id, [1.0, 0.0], "test-embed", 20
        )
        fused = funnel.fuse({}, embeddings, {**{}, **{}}, policy=policy)
    counts: dict[str, int] = {}
    for candidate in fused:
        counts[str(candidate.source_id)] = counts.get(str(candidate.source_id), 0) + 1
    # 4 candidates exist; k=10 is not meetable — the assert is that ALL
    # surface and the split follows relevance (largest remainder:
    # A 2/4 = .5 -> 5 raw -> floor 2 after B/C get floors... expressed
    # simply: A gets more than B and C, B and C keep their floor 1).
    assert len(fused) == 4
    slots = sorted(counts.values(), reverse=True)
    assert slots == [2, 1, 1], "dominant source takes the bigger share, never uniform"
    best = max(fused, key=lambda c: c.rank)
    assert best.rank == 1.0


def _insert_chunks_with_embedding(
    source_id, embeddings: list[tuple[float, float]]
) -> None:
    from tests.factories import insert_chunk

    for i, (a, b) in enumerate(embeddings):
        insert_chunk(
            source_id,
            f"linearity chunk {i}",
            chunk_index=i,
            label=f"page {i + 1}",
            embedding=[a, b],
        )


def test_fuse_allocation_floor_and_availability(course) -> None:
    """Guardrails: a weak-but-matching source keeps at least one slot
    (the floor), and availability clamps the strong source while the
    weak one's floor is honored — built with grouped sources."""
    src_a = insert_source(course.course_id)
    _insert_chunks_with_embedding(src_a, [(1.0, 0.0)] * 7)
    src_b = insert_source(course.course_id)
    _insert_chunks_with_embedding(src_b, [(0.05, 0.95)])
    policy = _policy(final_k=10)
    with connection() as conn:
        embeddings = funnel.embedding_seam(
            conn, course.course_id, [1.0, 0.0], "test-embed", 20
        )
        fused = funnel.fuse({}, embeddings, {**{}, **{}}, policy=policy)
    counts: dict[str, int] = {}
    for candidate in fused:
        counts[str(candidate.source_id)] = counts.get(str(candidate.source_id), 0) + 1
    # 8 candidates exist; k=10 is not meetable. The asserts are the two
    # guardrails: the weak source keeps its floor slot, the strong
    # source takes all 7 of its available chunks.
    assert len(fused) == 8
    assert sorted(counts.values()) == [1, 7], (
        "strong source takes 7 (its availability), weak keeps floor 1"
    )


def test_fuse_single_source_fills_naturally(course) -> None:
    """No competition -> no allocation pressure: one source fills all of
    final_k when it has the chunks (the #3 lesson, kept by construction)."""
    source_id = insert_source(course.course_id)
    insert_chunks(source_id, 12)
    policy = _policy(final_k=10)
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
    fused = funnel.fuse(keyword, {}, {**{}, **{}}, policy=policy)
    assert len(fused) == 10


def test_fuse_multi_seam_relevance_is_cross_seam_max(course) -> None:
    """A chunk strong in keyword but mid in embeddings, against a chunk
    only-mid in embeddings: after normalization both are comparable, and
    the source whose best evidence is the keyword hit wins the bigger
    share. This is the #4 fix in action — units are normalized before
    they are compared."""
    # Source A: chunk with middling dot but exact keyword hits
    kw_chunk = add_chunk(
        course.course_id,
        "linearity when did we use linearity linearity",
        embedding=[0.4, 0.2],
        label="k1",
    )
    # Source B: chunk with stronger dot
    emb_chunk = add_chunk(
        course.course_id,
        "preserving structure",
        embedding=[0.9, 0.0],
        label="e1",
    )
    policy = _policy(final_k=2)
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
        embeddings = funnel.embedding_seam(
            conn, course.course_id, [1.0, 0.0], "test-embed", 20
        )
        fused = funnel.fuse(keyword, embeddings, {**{}, **{}}, policy=policy)
    # Both sources have exactly one chunk, so both must appear (2 slots,
    # 2 available) — the point is no crash from cross-seam comparison and
    # both are admitted rather than one seam's unit silently dominating.
    assert len(fused) == 2
    ids = {str(c.chunk_id) for c in fused}
    assert str(kw_chunk) in ids and str(emb_chunk) in ids


def test_failed_sources_are_never_citable(course) -> None:
    """Golden rule 1 guard (review catch #1): the ingestion run ledger
    deliberately survives stage failure (inspectable history), but the
    retrieval side must mirror the source lifecycle — only 'indexed'
    sources are citable. A source that died at a model stage keeps live
    chunks; seams must never surface them."""
    source_id = insert_source(course.course_id)
    insert_chunks(source_id, 3)
    policy = _policy(final_k=10)
    set_source_status(source_id, "failed")
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
        emb = funnel.embedding_seam(conn, course.course_id, None, "test-embed", 20)
    assert funnel.fuse(keyword, emb, {**{}, **{}}, policy=policy) == ()


def test_pending_sources_are_never_citable(course) -> None:
    """Same guard, other pre-indexed states: an 'uploaded' source whose
    chunks exist mid-run (the deliberate stage-commit behavior) is
    invisible until it is indexed."""
    source_id = insert_source(course.course_id)
    insert_chunks(source_id, 3)
    set_source_status(source_id, "uploaded")
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
    assert keyword == {}
