"""Check that the ONNX encoders match the torch ones they replace.

    .venv/Scripts/python -m scripts.check_encoders

Needs both runtimes installed (sentence-transformers + torch, and
onnxruntime). Embeddings must be near-identical (cosine similarity ≈ 1)
so existing chunk embeddings stay valid without re-embedding; reranker
scores must agree closely and rank candidates the same way.
"""

from __future__ import annotations

import sys
import time

import numpy as np

TEXTS = [
    "A linear transformation preserves addition and scalar multiplication.",
    "Lecture attendance will make up 20% of your overall grade in the course.",
    "The first exam will be held in-class on Wednesday, September 30.",
    "Pan-ethnicity refers to the process of group formation due to common conditions.",
    "Office hours are on Tuesdays from 10:00am to 11:00am in Tarbutton 321C.",
    "Spanish-language media such as Univision and Telemundo connect many Latinos.",
    "What percentage do I need for an A-?",
    "def is_linear(f): return preserves_sums(f) and preserves_scaling(f)",
]
QUERY = "How is the final grade calculated?"


def main() -> int:
    from sentence_transformers import CrossEncoder, SentenceTransformer
    from src.backend.common.encoders import (
        GRANITE_EMBEDDING_R2,
        MS_MARCO_MINILM_L6,
        OnnxCrossEncoder,
        OnnxEmbedder,
    )

    torch_embed = SentenceTransformer(
        "ibm-granite/granite-embedding-english-r2", device="cpu"
    )
    torch_embed = torch_embed.float()
    started = time.perf_counter()
    reference = torch_embed.encode(TEXTS, normalize_embeddings=True)
    torch_seconds = time.perf_counter() - started
    onnx_embed = OnnxEmbedder(GRANITE_EMBEDDING_R2)
    started = time.perf_counter()
    candidate = onnx_embed.encode(TEXTS)
    onnx_seconds = time.perf_counter() - started
    cosines = np.sum(np.asarray(reference) * candidate, axis=1)
    print(
        f"embeddings: min cosine {cosines.min():.6f} "
        f"(torch {torch_seconds:.2f}s, onnx {onnx_seconds:.2f}s)"
    )

    torch_rerank = CrossEncoder("cross-encoder/ms-marco-MiniLM-L6-v2", device="cpu")
    pairs = [(QUERY, text) for text in TEXTS]
    ref_scores = np.asarray(torch_rerank.predict(pairs))
    onnx_scores = np.asarray(OnnxCrossEncoder(MS_MARCO_MINILM_L6).predict(pairs))
    same_order = list(np.argsort(-ref_scores)) == list(np.argsort(-onnx_scores))
    print(
        f"reranker: max score diff {np.abs(ref_scores - onnx_scores).max():.5f}, "
        f"same ranking: {same_order}"
    )
    ok = cosines.min() > 0.9999 and same_order
    print("PARITY OK" if ok else "PARITY FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
