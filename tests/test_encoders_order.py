"""Length-sorted batching must not reorder the embeddings it returns."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
from src.backend.common import encoders


class _Tokenizer:
    def encode_batch(self, texts: list[str]) -> list[Any]:
        width = max(len(text) for text in texts)
        return [
            SimpleNamespace(
                ids=[len(text)] * width,
                attention_mask=[1] * width,
                type_ids=[0] * width,
            )
            for text in texts
        ]


class _Session:
    def get_inputs(self) -> list[Any]:
        return [
            SimpleNamespace(name="input_ids"),
            SimpleNamespace(name="attention_mask"),
        ]

    def run(self, _outputs: Any, feeds: dict[str, np.ndarray]) -> list[np.ndarray]:
        ids = feeds["input_ids"].astype(np.float32)
        # The CLS position encodes the text's length, so order is checkable.
        hidden = np.stack([ids, np.ones_like(ids)], axis=-1)
        return [hidden]


def test_sorted_batches_return_vectors_in_input_order() -> None:
    model = encoders.OnnxEmbedder.__new__(encoders.OnnxEmbedder)
    model._session = _Session()
    model._tokenizer = _Tokenizer()
    texts = ["a" * 9, "a", "a" * 5, "a" * 3]
    vectors = model.encode(texts, batch_size=2, normalize_embeddings=False)
    assert [float(v[0]) for v in vectors] == [9.0, 1.0, 5.0, 3.0]
