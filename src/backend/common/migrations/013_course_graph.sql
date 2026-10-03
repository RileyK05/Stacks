-- Course graph (plan-notebook: "course graph and topic hierarchy").
--
-- Nodes are CHUNKS, not concepts. Chunks are already the embedded unit
-- (chunk_embeddings) and are L2-normalized at encode time, so an edge
-- weight is the real cosine similarity between two passages. There is no
-- concept embedding: a generated vector space would let items that are
-- not concepts become concepts and crowd the graph.
--
-- Concepts annotate chunks: concept_chunks is a concept's direct evidence
-- and is what makes the (previously dormant) dependency retrieval seam
-- accurate — it links a concept to chunks, not to a whole source.
--
-- Clusters are the nested family/subnode hierarchy cut from the chunk
-- similarity graph. A cluster names one core chunk (its medoid) that
-- doubles as the family's citation anchor. Cluster membership, labels,
-- and similarity edges are inference (evidence_level 'hypothesis'); the
-- table of contents remains the grounded structure where it exists.

CREATE TABLE graph_edges (
    edge_id         UUID PRIMARY KEY,
    course_id       UUID NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,
    model           TEXT NOT NULL,
    chunk_a         UUID NOT NULL REFERENCES chunks (chunk_id) ON DELETE CASCADE,
    chunk_b         UUID NOT NULL REFERENCES chunks (chunk_id) ON DELETE CASCADE,
    weight          REAL NOT NULL CHECK (weight > 0.0 AND weight <= 1.0),
    created_at      TIMESTAMP NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    CHECK (chunk_a <> chunk_b)
);
-- One undirected edge per pair, canonicalized chunk_a < chunk_b by the
-- writer. A model swap produces a separate edge set rather than mixing
-- vector spaces (same rule as chunk_embeddings).
CREATE UNIQUE INDEX idx_graph_edges_pair
    ON graph_edges (course_id, model, chunk_a, chunk_b);
CREATE INDEX idx_graph_edges_a ON graph_edges (course_id, model, chunk_a);
CREATE INDEX idx_graph_edges_b ON graph_edges (course_id, model, chunk_b);

-- A concept's direct evidence. The concept itself lives in `concepts`
-- (course knowledge, migration 001); this is the missing link to chunks.
CREATE TABLE concept_chunks (
    concept_id      UUID NOT NULL REFERENCES concepts (concept_id) ON DELETE CASCADE,
    chunk_id        UUID NOT NULL REFERENCES chunks (chunk_id) ON DELETE CASCADE,
    evidence_level  TEXT NOT NULL DEFAULT 'derived'
                    CHECK (evidence_level IN ('direct', 'derived', 'hypothesis')),
    PRIMARY KEY (concept_id, chunk_id)
);
CREATE INDEX idx_concept_chunks_chunk ON concept_chunks (chunk_id);

-- Re-extraction is idempotent: concepts dedup by normalized name within
-- a course, and a prerequisite pair is written once. (Names are stored
-- as extracted; the extractor normalizes case/whitespace when matching.)
CREATE UNIQUE INDEX idx_concepts_course_name ON concepts (course_id, name);
CREATE UNIQUE INDEX idx_dependencies_pair
    ON dependencies (prereq_id, dependent_id) WHERE prereq_id IS NOT NULL;

CREATE TABLE graph_clusters (
    cluster_id        UUID PRIMARY KEY,
    course_id         UUID NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,
    parent_cluster_id UUID REFERENCES graph_clusters (cluster_id) ON DELETE CASCADE,
    level             INTEGER NOT NULL CHECK (level >= 0),
    method            TEXT NOT NULL CHECK (method IN ('toc_preferred', 'uniform')),
    core_chunk_id     UUID REFERENCES chunks (chunk_id) ON DELETE SET NULL,
    label             TEXT,
    label_source      TEXT NOT NULL DEFAULT 'inferred'
                      CHECK (label_source IN ('toc', 'inferred')),
    algorithm         TEXT NOT NULL,
    cohesion          REAL,
    created_at        TIMESTAMP NOT NULL
                      DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
CREATE INDEX idx_graph_clusters_course ON graph_clusters (course_id, method);
CREATE INDEX idx_graph_clusters_parent ON graph_clusters (parent_cluster_id);

CREATE TABLE graph_cluster_members (
    cluster_id      UUID NOT NULL REFERENCES graph_clusters (cluster_id) ON DELETE CASCADE,
    chunk_id        UUID NOT NULL REFERENCES chunks (chunk_id) ON DELETE CASCADE,
    score           REAL NOT NULL,
    PRIMARY KEY (cluster_id, chunk_id)
);
CREATE INDEX idx_graph_cluster_members_chunk ON graph_cluster_members (chunk_id);
