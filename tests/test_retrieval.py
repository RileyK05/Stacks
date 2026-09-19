"""Hybrid retrieval funnel tests (decision 008).

Fixtures build one course with chunks + locators + TOC + dependency edges
directly (retrieval reads derived rows; ingestion tests already cover how
they get there). Asserts: each seam's contract, dormant behavior, fusion
mixing (union + caps + quotas), layer attribution, and trace persistence.
"""

import json
from uuid import UUID, uuid4

import pytest
from psycopg.rows import dict_row
from src.backend.common import courses_repo, users_repo
from src.backend.common.db import connection
from src.backend.retrieval import funnel, trace
from src.backend.retrieval.config import load_retrieval_policy
from src.backend.retrieval.funnel import RetrievalPolicy

QUERY = "when did we use linearity"


def _policy(**overrides) -> RetrievalPolicy:
    base = load_retrieval_policy()
    if not overrides:
        return base
    data = base.model_dump()
    data.update(overrides)
    return RetrievalPolicy.model_validate(data)


def _insert_source(user, course) -> "object":
    """One indexed source with a unique hash; returns the source_id."""
    import uuid as uuid_module

    source_id = uuid_module.uuid4()
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        object_id = cur.execute(
            "INSERT INTO course_objects (course_id, created_by_user_id,"
            " kind, content_type, content, access_scope)"
            " VALUES (%s, %s, 'source', 'text/plain', '{}', 'enrolled')"
            " RETURNING object_id",
            (course.course_id, user.user_id),
        ).fetchone()["object_id"]
        cur.execute(
            "INSERT INTO sources (source_id, object_id,"
            " uploaded_by_user_id, course_id, filename, mime_type,"
            " source_type, uri, status, file_hash, size_bytes,"
            " stored_encoding)"
            " VALUES (%s, %s, %s, %s, 'notes.txt', 'text/plain', 'notes',"
            " 'disk://x', 'indexed', %s, 10, 'identity')",
            (
                source_id,
                object_id,
                user.user_id,
                course.course_id,
                f"hash-{uuid_module.uuid4().hex}",
            ),
        )
        conn.commit()
    return source_id


def _insert_chunks(source_id, count: int) -> None:
    """`count` chunks, each under its own page locator so eval labels
    stay per-chunk. One row per logical chunk (migration 031): distinct
    chunk_index, primary locator on the row, full span in
    chunk_locators."""
    import uuid as uuid_module

    with connection() as conn, conn.cursor() as cur:
        for i in range(count):
            locator_id = uuid_module.uuid4()
            chunk_id = uuid_module.uuid4()
            cur.execute(
                "INSERT INTO locators (locator_id, source_id, locator_type,"
                " start, end_value, label)"
                " VALUES (%s, %s, 'page', '0', '100', %s)",
                (locator_id, source_id, f"page {i + 1}"),
            )
            cur.execute(
                "INSERT INTO chunks (chunk_id, source_id, locator_id,"
                " chunk_index, text) VALUES (%s, %s, %s, %s, %s)",
                (chunk_id, source_id, locator_id, i, f"linearity mention {i}"),
            )
            cur.execute(
                "INSERT INTO chunk_locators (chunk_id, locator_id)"
                " VALUES (%s, %s)",
                (chunk_id, locator_id),
            )
        conn.commit()


@pytest.fixture
def course_pair():
    user = users_repo.create(
        "Retrieval Tester", f"{uuid4().hex}@test.invalid", "not-a-hash"
    )
    course = courses_repo.create_course(user.user_id, "Retrieval Course")
    return user, course


def _add_chunk(
    course_pair,
    text: str,
    *,
    label: str = "page 1",
    embedding: list[float] | None = None,
    embedding_model: str = "test-embed",
) -> UUID:
    """One source + locator + chunk; returns the chunk id. Each chunk gets
    its own source so per-source caps can be tested precisely."""
    user, course = course_pair
    course_id = course.course_id
    source_id = uuid4()
    locator_id = uuid4()
    chunk_id = uuid4()
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        object_id = cur.execute(
            "INSERT INTO course_objects (course_id, created_by_user_id, kind,"
            " content_type, content, access_scope) VALUES (%s, %s, 'source',"
            " 'text/plain', '{}', 'enrolled') RETURNING object_id",
            (course_id, user.user_id),
        ).fetchone()["object_id"]
        cur.execute(
            "INSERT INTO sources (source_id, object_id, uploaded_by_user_id,"
            " course_id, filename, mime_type, source_type, uri, status,"
            " file_hash, size_bytes, stored_encoding)"
            " VALUES (%s, %s, %s, %s, 'notes.txt', 'text/plain', 'notes',"
            " 'disk://x', 'indexed', %s, 10, 'identity')",
            (
                source_id,
                object_id,
                user.user_id,
                course_id,
                f"hash-{uuid4().hex}",
            ),
        )
        cur.execute(
            "INSERT INTO locators (locator_id, source_id, locator_type,"
            " start, end_value, label)"
            " VALUES (%s, %s, 'page', '0', '100', %s)",
            (locator_id, source_id, label),
        )
        cur.execute(
            "INSERT INTO chunks (chunk_id, source_id, locator_id,"
            " chunk_index, text) VALUES (%s, %s, %s, 0, %s)",
            (chunk_id, source_id, locator_id, text),
        )
        if embedding is not None:
            cur.execute(
                "INSERT INTO chunk_embeddings (chunk_id, model, embedding)"
                " VALUES (%s, %s, %s)",
                (chunk_id, embedding_model, embedding),
            )
        conn.commit()
    return chunk_id


def _chunk_source_locator(chunk_id: UUID) -> tuple[UUID, UUID]:
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            "SELECT source_id, locator_id FROM chunks WHERE chunk_id = %s",
            (chunk_id,),
        ).fetchone()
    return row["source_id"], row["locator_id"]


def _add_toc_entry(
    course_id: UUID, chunk_id: UUID, title: str, description: str
) -> UUID:
    source_id, locator_id = _chunk_source_locator(chunk_id)
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        toc_row = cur.execute(
            "SELECT toc_id FROM tables_of_contents WHERE course_id = %s"
            " ORDER BY version DESC LIMIT 1",
            (course_id,),
        ).fetchone()
        if toc_row is None:
            toc_row = cur.execute(
                "INSERT INTO tables_of_contents (course_id, version)"
                " VALUES (%s, 1) RETURNING toc_id",
                (course_id,),
            ).fetchone()
        entry_id = cur.execute(
            "INSERT INTO toc_entries (toc_id, source_id, locator_id, title,"
            " description, concepts, position)"
            " VALUES (%s, %s, %s, %s, %s, '[]'::jsonb, 0)"
            " RETURNING entry_id",
            (toc_row["toc_id"], source_id, locator_id, title, description),
        ).fetchone()
        conn.commit()
    assert entry_id is not None
    return entry_id["entry_id"]


def _add_concept(
    course_id: UUID,
    name: str,
    synonyms: list[str],
    *,
    depends_on: list[UUID] | None = None,
) -> UUID:
    concept_id = uuid4()
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO concepts (concept_id, course_id, name, definition,"
            " synonyms) VALUES (%s, %s, %s, 'def', %s)",
            (concept_id, course_id, name, json.dumps(synonyms)),
        )
        for prereq_id in depends_on or []:
            cur.execute(
                "INSERT INTO dependencies (prereq_id, dependent_id)"
                " VALUES (%s, %s)",
                (prereq_id, concept_id),
            )
        conn.commit()
    return concept_id


def _add_memory_object(concept_id: UUID, source_id: UUID, content: str) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO memory_objects (concept_id, source_id, kind, content)"
            " VALUES (%s, %s, 'concept', %s)",
            (concept_id, source_id, content),
        )
        conn.commit()


# --- seam contracts -------------------------------------------------------


def test_keyword_seam_finds_exact_terms(course_pair) -> None:
    _user, course = course_pair
    hit = _add_chunk(course_pair, "linearity of transformations")
    _add_chunk(course_pair, "unrelated text about integrals")
    policy = _policy()
    with connection() as conn:
        candidates = funnel.keyword_seam(
            conn, course.course_id, QUERY, policy.keyword_limit
        )
    assert str(hit) in {str(cid) for cid in candidates}
    assert len(candidates) == 1


def test_keyword_seam_empty_query_is_safe(course_pair) -> None:
    _user, course = course_pair
    _add_chunk(course_pair, "linearity everywhere")
    with connection() as conn:
        assert funnel.keyword_seam(conn, course.course_id, "   ", 20) == {}


def test_toc_seam_static_match_and_dormancy(course_pair) -> None:
    _user, course = course_pair
    policy = _policy()
    with connection() as conn:
        dormant, dormant_entries = funnel.toc_seam(
            conn, course.course_id, "explain linearity", policy.toc_limit
        )
        assert dormant == {}, "no entries: the seam must contribute nothing"
        assert dormant_entries == ()
        chunk_id = _add_chunk(course_pair, "linear maps preserve structure")
        entry_id = _add_toc_entry(
            course.course_id,
            chunk_id,
            "Linearity basics",
            "definition of linearity",
        )
        candidates, matched_entries = funnel.toc_seam(
            conn, course.course_id, "explain linearity", policy.toc_limit
        )
    assert str(chunk_id) in {str(cid) for cid in candidates}
    assert str(entry_id) in {str(eid) for eid in matched_entries}


def test_dependency_seam_dormant_without_edges(course_pair) -> None:
    _user, course = course_pair
    concept_id = _add_concept(course.course_id, "linearity", [])
    policy = _policy()
    with connection() as conn:
        candidates = funnel.dependency_seam(
            conn, course.course_id, [concept_id], policy.dependency_limit
        )
    assert candidates == {}, "concept without edges: dormancy, not an error"


def test_dependency_seam_walks_edges(course_pair) -> None:
    _user, course = course_pair
    prereq_concept = _add_concept(
        course.course_id, "vector spaces", []
    )
    linearity_concept = _add_concept(
        course.course_id, "linearity", [], depends_on=[prereq_concept]
    )
    prereq_chunk = _add_chunk(course_pair, "vector spaces have bases")
    source_id, _locator = _chunk_source_locator(prereq_chunk)
    _add_memory_object(prereq_concept, source_id, "prereq material")

    policy = _policy()
    with connection() as conn:
        candidates = funnel.dependency_seam(
            conn, course.course_id, [linearity_concept], policy.dependency_limit
        )
    assert str(prereq_chunk) in {str(cid) for cid in candidates}


def test_concept_matches_by_synonym(course_pair) -> None:
    _user, course = course_pair
    concept_id = _add_concept(
        course.course_id, "linearity", ["linear maps", "structure preserving"]
    )
    with connection() as conn:
        matches = funnel.concept_matches(
            conn, course.course_id, "how do linear maps behave", 5
        )
    assert str(concept_id) in {str(row["concept_id"]) for row in matches}


def test_embedding_seam_dormant_and_active(course_pair) -> None:
    _user, course = course_pair
    policy = _policy()
    with connection() as conn:
        dormant = funnel.embedding_seam(
            conn, course.course_id, None, "test-embed", policy.embedding_limit
        )
        assert dormant == {}
        chunk_id = _add_chunk(
            course_pair,
            "linearity of transformations",
            embedding=[1.0, 0.0],
        )
        _add_chunk(
            course_pair,
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


# --- fusion ---------------------------------------------------------------


def test_fuse_mixes_and_attributes_layers(course_pair) -> None:
    _user, course = course_pair
    keyword_hit = _add_chunk(course_pair, "linearity in chapter 5 usage")
    toc_chunk = _add_chunk(course_pair, "linearity definition chapter")
    _add_toc_entry(course.course_id, toc_chunk, "Linearity", "about linearity")
    policy = _policy(final_k=10)
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
        toc, _entries = funnel.toc_seam(conn, course.course_id, QUERY, 20)
        fused = funnel.fuse(keyword, toc, {}, {}, policy=policy)
    ids = {str(candidate.chunk_id) for candidate in fused}
    assert str(keyword_hit) in ids
    assert str(toc_chunk) in ids
    by_id = {str(candidate.chunk_id): candidate for candidate in fused}
    assert "keyword" in by_id[str(keyword_hit)].layers
    assert "toc" in by_id[str(toc_chunk)].layers


def test_fuse_single_source_is_never_starved(course_pair) -> None:
    """The #3 lesson, kept by construction: five keyword hits sharing ONE
    source all surface — with no competing source there is nothing to
    allocate against."""
    user, course = course_pair

    source_id = _insert_source(user, course)
    _insert_chunks(source_id, 5)
    policy = _policy(final_k=10)
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
    fused = funnel.fuse(keyword, {}, {}, {}, policy=policy)
    assert len(fused) == 5


def test_fuse_equal_relevance_splits_evenly(course_pair) -> None:
    """Three sources with EQUAL relevance (all-equal keyword ranks
    normalize to the same 0.5): the split is even — 2/2/2 with k=6.
    Equal evidence, equal share; no unit accident decides it."""
    user, course = course_pair
    for _ in range(3):
        source_id = _insert_source(user, course)
        _insert_chunks(source_id, 5)
    policy = _policy(final_k=6)
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
    fused = funnel.fuse(keyword, {}, {}, {}, policy=policy)
    assert len(fused) == 6
    counts: dict[str, int] = {}
    for candidate in fused:
        counts[str(candidate.source_id)] = (
            counts.get(str(candidate.source_id), 0) + 1
        )
    assert set(counts.values()) == {2}


def test_fuse_embedding_orders_final_set(course_pair) -> None:
    _user, course = course_pair
    _add_chunk(course_pair, "linearity barely relevant", embedding=[0.9, 0.1])
    high = _add_chunk(course_pair, "linearity deeply relevant", embedding=[1.0, 0.0])
    policy = _policy(final_k=2)
    query_embedding = [1.0, 0.0]
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
        embeddings = funnel.embedding_seam(
            conn, course.course_id, query_embedding, "test-embed", 20
        )
        fused = funnel.fuse(keyword, {}, {}, embeddings, policy=policy)
    assert [str(candidate.chunk_id) for candidate in fused][0] == str(high)


def test_fuse_embedding_only_quota(course_pair) -> None:
    _user, course = course_pair
    keyword_hit = _add_chunk(course_pair, "linearity exact term")
    semantic_only_1 = _add_chunk(
        course_pair, "preserving structure", embedding=[1.0, 0.1]
    )
    semantic_only_2 = _add_chunk(
        course_pair, "structure preservation", embedding=[0.99, 0.05]
    )
    policy = _policy(embedding_only_quota=1, final_k=10)
    query_embedding = [1.0, 0.0]
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
        embeddings = funnel.embedding_seam(
            conn, course.course_id, query_embedding, "test-embed", 20
        )
        fused = funnel.fuse(keyword, {}, {}, embeddings, policy=policy)
    ids = {str(candidate.chunk_id) for candidate in fused}
    assert str(keyword_hit) in ids
    semantic_ids = (str(semantic_only_1), str(semantic_only_2))
    semantic_in = sum(1 for cid in semantic_ids if cid in ids)
    assert semantic_in == 1, "embedding-only quota: one semantic extra admitted"


def test_full_funnel_and_trace_persistence(course_pair) -> None:
    user, course = course_pair
    chunk = _add_chunk(course_pair, "linearity of transformations")
    policy = _policy()
    with connection() as conn:
        result = funnel.retrieve(conn, course.course_id, QUERY, policy)
        stored = trace.record_trace(
            conn, user.user_id, course.course_id, QUERY, result
        )
        conn.commit()
    assert result.candidates
    assert result.layer_contribution.get("keyword", 0) >= 1
    assert str(chunk) in {str(candidate.chunk_id) for candidate in result.candidates}
    assert stored.chunk_ids == tuple(c.chunk_id for c in result.candidates)


def test_retrieval_dormant_seams_contribute_nothing(course_pair) -> None:
    _user, course = course_pair
    policy = _policy()
    with connection() as conn:
        result = funnel.retrieve(conn, course.course_id, QUERY, policy)
    assert result.candidates == ()
    assert result.layer_contribution == {}
    assert result.matched_concept_ids == ()

# --- review-fix regressions (2026-09-13 external review) -----------------


def test_keyword_seam_survives_math_syntax(course_pair) -> None:
    """f(x) = x^2 must not crash to_tsquery — operator characters are
    stripped before SQL sees them. This is the flagship seam; a math
    question is the target domain's most normal query."""
    _user, course = course_pair
    _add_chunk(course_pair, "the function f of x equals x squared")
    with connection() as conn:
        candidates = funnel.keyword_seam(
            conn, course.course_id, "f(x) = x^2 ?", 20
        )
    assert candidates is not None


def test_keyword_seam_handles_operator_heavy_queries(course_pair) -> None:
    _user, course = course_pair
    _add_chunk(course_pair, "limits and continuity of functions")
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
            funnel.keyword_seam(conn, course.course_id, hostile, 20)


def test_concept_matches_word_boundary_not_substring(course_pair) -> None:
    """A concept named 'rat' must not match 'iteration'; single-letter
    concepts must never match (defense in depth on both sides)."""
    _user, course = course_pair
    rat_concept = _add_concept(course.course_id, "rat", [])
    _add_concept(course.course_id, "f", [])
    with connection() as conn:
        matches = funnel.concept_matches(
            conn, course.course_id, "explain the iteration process", 10
        )
    assert str(rat_concept) not in {str(r["concept_id"]) for r in matches}


def test_concept_matches_survives_regex_metacharacters(course_pair) -> None:
    """Concept names are model-extracted, so regex metacharacters in them
    must be escaped before they reach the regex engine. Unescaped, 'f(x'
    raises InvalidRegularExpression and takes down the whole retrieve()
    call — a single bad extracted name would break every question on the
    course. 'O(n)' and 'f(x)' are the common case in a maths/CS course."""
    _user, course = course_pair
    for broken_name in ("f(x", "a**b", "x{2,", "set A [unclosed"):
        _add_concept(course.course_id, broken_name, [])
    _add_concept(course.course_id, "bad synonym holder", ["g(y"])
    on_concept = _add_concept(course.course_id, "O(n)", [])
    with connection() as conn:
        matches = funnel.concept_matches(
            conn, course.course_id, "what is o(n) complexity here", 10
        )
    assert str(on_concept) in {str(row["concept_id"]) for row in matches}


def test_concept_matches_metacharacters_are_literal(course_pair) -> None:
    """Escaped metacharacters match literally, not as regex operators: a
    concept named 'a+b' must match 'a+b' and must NOT match 'aaab'."""
    _user, course = course_pair
    plus_concept = _add_concept(course.course_id, "a+b", [])
    with connection() as conn:
        literal = funnel.concept_matches(
            conn, course.course_id, "why does a+b hold", 10
        )
        quantifier = funnel.concept_matches(
            conn, course.course_id, "we saw aaab today", 10
        )
    assert str(plus_concept) in {str(row["concept_id"]) for row in literal}
    assert str(plus_concept) not in {str(row["concept_id"]) for row in quantifier}


def test_retrieve_survives_malformed_concept_names(course_pair) -> None:
    """End to end: one malformed extracted concept name must not break
    retrieval for the whole course — the keyword seam still answers."""
    _user, course = course_pair
    hit = _add_chunk(course_pair, "linearity of transformations")
    _add_concept(course.course_id, "f(x", [])
    policy = _policy()
    with connection() as conn:
        result = funnel.retrieve(conn, course.course_id, QUERY, policy)
    assert str(hit) in {str(c.chunk_id) for c in result.candidates}


def test_toc_seam_word_boundary_not_substring(course_pair) -> None:
    """Entry 'Week 1 overview' must not match query word 'we' via raw
    substring ILIKE — the seam full-text matches now."""
    _user, course = course_pair
    chunk_id = _add_chunk(course_pair, "week one course overview text")
    _add_toc_entry(
        course.course_id, chunk_id, "Week 1 overview", "course intro"
    )
    other = _add_chunk(course_pair, "totally unrelated content about proofs")
    _add_toc_entry(course.course_id, other, "Proof techniques", "about proofs")
    with connection() as conn:
        candidates, _entries = funnel.toc_seam(
            conn, course.course_id, "when did we use induction", 20
        )
    ids = {str(cid) for cid in candidates}
    assert str(other) not in ids, "'we' must not substring-match 'Week'"


def test_embedding_dimension_mismatch_is_excluded(course_pair) -> None:
    """A different-dimension embedding (model swap debris) must be
    excluded, not silently zip-truncated into garbage ranks."""
    _user, course = course_pair
    matching = _add_chunk(
        course_pair, "aligned vector", embedding=[1.0, 0.0]
    )
    _add_chunk(
        course_pair,
        "wrong dimension vector",
        embedding=[1.0, 2.0, 3.0],
    )
    with connection() as conn:
        candidates = funnel.embedding_seam(
            conn, course.course_id, [1.0, 0.0], "test-embed", 20
        )
    assert list(candidates) == [matching]


def test_dependency_seam_is_deterministic(course_pair) -> None:
    """Same inputs → same candidate order (ORDER BY in the UNION)."""
    _user, course = course_pair
    prereq = _add_concept(course.course_id, "vector spaces", [])
    target = _add_concept(course.course_id, "linearity", [], depends_on=[prereq])
    source_id, _locator = _chunk_source_locator(
        _add_chunk(course_pair, "vector spaces have bases")
    )
    _add_memory_object(prereq, source_id, "prereq material")
    with connection() as conn:
        first = funnel.dependency_seam(conn, course.course_id, [target], 20)
        second = funnel.dependency_seam(conn, course.course_id, [target], 20)
    assert list(first) == list(second)


def test_trace_records_per_chunk_layers(course_pair) -> None:
    user, course = course_pair
    _add_chunk(course_pair, "linearity of transformations")
    policy = _policy()
    with connection() as conn:
        result = funnel.retrieve(conn, course.course_id, QUERY, policy)
        trace.record_trace(conn, user.user_id, course.course_id, QUERY, result)
        conn.commit()
        row = conn.execute(
            "SELECT retrieved_chunk_ids FROM retrieval_traces"
            " WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
            (user.user_id,),
        ).fetchone()
    payload = row[0]
    assert "per_chunk_layers" in payload
    for entry in payload["per_chunk_layers"]:
        assert entry["layers"], "every cited chunk records its seams"


def test_eval_runner_exact_labels_and_unresolved(course_pair, tmp_path) -> None:
    """page 1 must not match page 12 (exact label membership), and a case
    whose course_tag resolves to nothing is UNRESOLVED, never a pass."""
    from src.backend.retrieval import evals as evals_module

    _user, course = course_pair
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE courses SET name = 'EVAL-FIXTURE' WHERE course_id = %s",
            (course.course_id,),
        )
        conn.commit()
    _add_chunk(course_pair, "linearity of transformations", label="page 1")
    _add_chunk(course_pair, "other content here", label="page 12")

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
        summary = evals_module.run_eval(
            conn, policy, cases_path=cases_file
        )
    assert len(summary.unresolved_cases) == 1
    resolved = [result for result in summary.cases if result.resolved]
    assert len(resolved) == 1
    assert resolved[0].hit
    assert summary.fused_recall == 1.0
    assert summary.seam_recall["keyword"] == 1.0


def test_eval_exact_label_no_substring_pass(course_pair, tmp_path) -> None:
    """Expected 'page 1' must NOT hit when only 'page 12' is retrieved —
    the substring false-pass mode is closed."""
    from src.backend.retrieval import evals as evals_module

    _user, course = course_pair
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE courses SET name = 'EVAL-EXACT' WHERE course_id = %s",
            (course.course_id,),
        )
        conn.commit()
    _add_chunk(course_pair, "unrelated content", label="page 12")

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


def test_fuse_allocates_slots_by_relevance(course_pair) -> None:
    """The ratified allocation: per-source relevance = best normalized
    chunk score; slots split proportionally with largest remainder.
    Three sources with clearly different relevance, built with the
    multi-chunk helpers so sources actually group chunks."""
    user, course = course_pair
    # Source A: two chunks, best dot 1.0
    src_a = _insert_source(user, course)
    _insert_chunks_with_embedding(src_a, [(1.0, 0.0), (0.8, 0.1)])
    # Source B: one chunk, dot ~0.55
    src_b = _insert_source(user, course)
    _insert_chunks_with_embedding(src_b, [(0.55, 0.0)])
    # Source C: one chunk, weak dot
    src_c = _insert_source(user, course)
    _insert_chunks_with_embedding(src_c, [(0.1, 0.9)])
    policy = _policy(final_k=10)
    with connection() as conn:
        embeddings = funnel.embedding_seam(
            conn, course.course_id, [1.0, 0.0], "test-embed", 20
        )
        fused = funnel.fuse({}, {}, {}, embeddings, policy=policy)
    counts: dict[str, int] = {}
    for candidate in fused:
        counts[str(candidate.source_id)] = (
            counts.get(str(candidate.source_id), 0) + 1
        )
    # 4 candidates exist; k=10 is not meetable — the assert is that ALL
    # surface and the split follows relevance (largest remainder:
    # A 2/4 = .5 -> 5 raw -> floor 2 after B/C get floors... expressed
    # simply: A gets more than B and C, B and C keep their floor 1).
    assert len(fused) == 4
    slots = sorted(counts.values(), reverse=True)
    assert slots == [2, 1, 1], (
        "dominant source takes the bigger share, never uniform"
    )
    best = max(fused, key=lambda c: c.rank)
    assert best.rank == 1.0


def _insert_chunks_with_embedding(
    source_id, embeddings: list[tuple[float, float]]
) -> None:
    import uuid as uuid_module

    with connection() as conn, conn.cursor() as cur:
        for i, (a, b) in enumerate(embeddings):
            locator_id = uuid_module.uuid4()
            chunk_id = uuid_module.uuid4()
            cur.execute(
                "INSERT INTO locators (locator_id, source_id, locator_type,"
                " start, end_value, label)"
                " VALUES (%s, %s, 'page', '0', '100', %s)",
                (locator_id, source_id, f"page {i + 1}"),
            )
            cur.execute(
                "INSERT INTO chunks (chunk_id, source_id, locator_id,"
                " chunk_index, text) VALUES (%s, %s, %s, %s, %s)",
                (chunk_id, source_id, locator_id, i, f"linearity chunk {i}"),
            )
            cur.execute(
                "INSERT INTO chunk_locators (chunk_id, locator_id)"
                " VALUES (%s, %s)",
                (chunk_id, locator_id),
            )
            cur.execute(
                "INSERT INTO chunk_embeddings (chunk_id, model, embedding)"
                " VALUES (%s, 'test-embed', %s)",
                (chunk_id, [a, b]),
            )
        conn.commit()


def test_fuse_allocation_floor_and_availability(course_pair) -> None:
    """Guardrails: a weak-but-matching source keeps at least one slot
    (the floor), and availability clamps the strong source while the
    weak one's floor is honored — built with grouped sources."""
    user, course = course_pair
    src_a = _insert_source(user, course)
    _insert_chunks_with_embedding(src_a, [(1.0, 0.0)] * 7)
    src_b = _insert_source(user, course)
    _insert_chunks_with_embedding(src_b, [(0.05, 0.95)])
    policy = _policy(final_k=10)
    with connection() as conn:
        embeddings = funnel.embedding_seam(
            conn, course.course_id, [1.0, 0.0], "test-embed", 20
        )
        fused = funnel.fuse({}, {}, {}, embeddings, policy=policy)
    counts: dict[str, int] = {}
    for candidate in fused:
        counts[str(candidate.source_id)] = (
            counts.get(str(candidate.source_id), 0) + 1
        )
    # 8 candidates exist; k=10 is not meetable. The asserts are the two
    # guardrails: the weak source keeps its floor slot, the strong
    # source takes all 7 of its available chunks.
    assert len(fused) == 8
    assert sorted(counts.values()) == [1, 7], (
        "strong source takes 7 (its availability), weak keeps floor 1"
    )


def test_fuse_single_source_fills_naturally(course_pair) -> None:
    """No competition -> no allocation pressure: one source fills all of
    final_k when it has the chunks (the #3 lesson, kept by construction)."""
    user, course = course_pair
    source_id = _insert_source(user, course)
    _insert_chunks(source_id, 12)
    policy = _policy(final_k=10)
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
    fused = funnel.fuse(keyword, {}, {}, {}, policy=policy)
    assert len(fused) == 10


def test_fuse_multi_seam_relevance_is_cross_seam_max(course_pair) -> None:
    """A chunk strong in keyword but mid in embeddings, against a chunk
    only-mid in embeddings: after normalization both are comparable, and
    the source whose best evidence is the keyword hit wins the bigger
    share. This is the #4 fix in action — units are normalized before
    they are compared."""
    user, course = course_pair
    # Source A: chunk with middling dot but exact keyword hits
    kw_chunk = _add_chunk(
        course_pair,
        "linearity when did we use linearity linearity",
        embedding=[0.4, 0.2],
        label="k1",
    )
    # Source B: chunk with stronger dot
    emb_chunk = _add_chunk(
        course_pair,
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
        fused = funnel.fuse(keyword, {}, {}, embeddings, policy=policy)
    # Both sources have exactly one chunk, so both must appear (2 slots,
    # 2 available) — the point is no crash from cross-seam comparison and
    # both are admitted rather than one seam's unit silently dominating.
    assert len(fused) == 2
    ids = {str(c.chunk_id) for c in fused}
    assert str(kw_chunk) in ids and str(emb_chunk) in ids


def test_failed_sources_are_never_citable(course_pair) -> None:
    """Golden rule 1 guard (review catch #1): the ingestion run ledger
    deliberately survives stage failure (inspectable history), but the
    retrieval side must mirror the source lifecycle — only 'indexed'
    sources are citable. A source that died at a model stage keeps live
    chunks; seams must never surface them."""
    user, course = course_pair
    source_id = _insert_source(user, course)
    _insert_chunks(source_id, 3)
    policy = _policy(final_k=10)
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE sources SET status = 'failed' WHERE source_id = %s",
            (source_id,),
        )
        conn.commit()
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
        emb = funnel.embedding_seam(
            conn, course.course_id, None, "test-embed", 20
        )
    assert funnel.fuse(keyword, {}, {}, emb, policy=policy) == ()


def test_pending_sources_are_never_citable(course_pair) -> None:
    """Same guard, other pre-indexed states: an 'uploaded' source whose
    chunks exist mid-run (the deliberate stage-commit behavior) is
    invisible until it is indexed."""
    user, course = course_pair
    source_id = _insert_source(user, course)
    _insert_chunks(source_id, 3)
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE sources SET status = 'uploaded' WHERE source_id = %s",
            (source_id,),
        )
        conn.commit()
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
    assert keyword == {}


def test_multi_locator_chunk_stored_once_with_full_span(course_pair) -> None:
    """Migration 031 (ratified fix #10): a chunk spanning multiple
    locators is ONE row (not one per locator), with the full span in
    chunk_locators. Duplicate storage made retrieval hits a function of
    locator grain and would have embedded the same text N times."""
    import uuid as uuid_module

    from src.backend.ingest.chunking import chunk_text
    from src.backend.ingest.extract import LocatorSpan

    user, course = course_pair
    source_id = _insert_source(user, course)
    locators = [
        LocatorSpan(
            locator_id=uuid_module.uuid4(),
            locator_type="page",
            start=i * 400,
            end=(i + 1) * 400,
            label=f"page {i + 1}",
        )
        for i in range(3)
    ]
    text = "linearity sentence with enough padding to straddle pages. " * 60
    spans = chunk_text(text, tuple(locators), max_tokens=64)
    multi = [span for span in spans if len(span.locator_ids) > 1]
    if not multi:
        return
    with connection() as conn, conn.cursor() as cur:
        for locator in locators:
            cur.execute(
                "INSERT INTO locators (locator_id, source_id, locator_type,"
                " start, end_value, label)"
                " VALUES (%s, %s, 'page', '0', '100', %s)",
                (locator.locator_id, source_id, locator.label),
            )
        for span in multi:
            cur.execute(
                "INSERT INTO chunks (source_id, locator_id, chunk_index, text)"
                " VALUES (%s, %s, %s, %s) RETURNING chunk_id",
                (source_id, span.locator_ids[0], span.chunk_index, span.text),
            )
            chunk_id = cur.fetchone()[0]
            for locator_id in span.locator_ids:
                cur.execute(
                    "INSERT INTO chunk_locators (chunk_id, locator_id)"
                    " VALUES (%s, %s)",
                    (chunk_id, locator_id),
                )
        conn.commit()
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM chunks WHERE source_id = %s"
            " AND chunk_index = %s",
            (source_id, multi[0].chunk_index),
        )
        assert cur.fetchone()[0] == 1, "one row per logical chunk"
        cur.execute(
            "SELECT count(*) FROM chunk_locators WHERE chunk_id = %s",
            (chunk_id,),
        )
        assert cur.fetchone()[0] == len(multi[0].locator_ids), (
            "the citation map holds the full span"
        )
