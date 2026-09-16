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
    policy = _policy(per_source_cap=99, final_k=10)
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


def test_fuse_per_source_cap(course_pair) -> None:
    """Five keyword hits sharing ONE source: per_source_cap=2 lets exactly
    2 through."""
    user, course = course_pair
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
        for i in range(5):
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
                " chunk_index, text) VALUES (%s, %s, %s, 0, %s)",
                (chunk_id, source_id, locator_id, f"linearity mention {i}"),
            )
        conn.commit()

    policy = _policy(per_source_cap=2, final_k=10)
    with connection() as conn:
        keyword = funnel.keyword_seam(conn, course.course_id, QUERY, 20)
    fused = funnel.fuse(keyword, {}, {}, {}, policy=policy)
    assert len(fused) == 2


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
