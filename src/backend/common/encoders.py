"""In-process encoders on ONNX Runtime (plan §5.3, Phase 5).

The embedding model and the reranker run as ONNX graphs with Hugging Face
`tokenizers` — no torch, which keeps the desktop build small. Each encoder
is pinned to an exact Hugging Face revision (the download URL names the
commit, so no file can change underneath us) and large files are verified
against their sha256 before use.

`OnnxEmbedder` reproduces the sentence-transformers pipeline the chunk
embeddings were created with (same model, CLS pooling, L2 normalization),
so switching runtimes needs no re-embedding; scripts/check_encoders.py
checks that parity against the torch implementation.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from src.backend.common.config import get_settings


@dataclass(frozen=True)
class RemoteFile:
    path: str  # path inside the repo
    sha256: str | None = None  # LFS files; small files are pinned by revision
    size_bytes: int | None = None


@dataclass(frozen=True)
class EncoderSpec:
    repo: str
    revision: str
    model: RemoteFile
    tokenizer: RemoteFile
    extra: tuple[RemoteFile, ...] = ()
    # The SentenceTransformers repo this ONNX export was converted from.
    # `scripts/check_encoders.py` loads it as the torch reference so the
    # parity check and the shipped ONNX graph cannot name different
    # models (T-21).
    source_repo: str | None = None

    def url(self, file: RemoteFile) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{file.path}"

    @property
    def files(self) -> tuple[RemoteFile, ...]:
        return (self.model, self.tokenizer, *self.extra)

    @property
    def torch_repo(self) -> str:
        return self.source_repo or self.repo


def encoder_dir(spec: EncoderSpec) -> Path:
    slug = spec.repo.replace("/", "--")
    return Path(get_settings().data_dir) / "models" / "encoders" / slug / spec.revision


def ensure_files(spec: EncoderSpec) -> Path:
    """Download (once) and verify every file of an encoder; returns its
    directory. Offline after the first run."""
    import httpx
    from src.backend.runtime.downloads import download_verified

    root = encoder_dir(spec)
    for file in spec.files:
        target = root / file.path
        if file.sha256 and file.size_bytes:
            download_verified(
                spec.url(file), target, sha256=file.sha256, size_bytes=file.size_bytes
            )
            continue
        max_bytes = 32 * 1024 * 1024
        if target.is_file() and 0 < target.stat().st_size <= max_bytes:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        try:
            with (
                httpx.stream(
                    "GET", spec.url(file), follow_redirects=True, timeout=60.0
                ) as response,
                partial.open("wb") as handle,
            ):
                response.raise_for_status()
                written = 0
                for block in response.iter_bytes(1 << 20):
                    written += len(block)
                    if written > max_bytes:
                        raise ValueError("encoder metadata exceeds the download limit")
                    handle.write(block)
            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
    return root


def _session(model_path: Path) -> Any:
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = max(1, (os.cpu_count() or 2) - 1)
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(
        str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
    )


def _tokenizer(root: Path, spec: EncoderSpec, max_length: int) -> Any:
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(str(root / spec.tokenizer.path))
    tokenizer.enable_truncation(max_length=max_length)
    pad_token = "[PAD]"
    special = root / "special_tokens_map.json"
    if special.is_file():
        value = json.loads(special.read_text(encoding="utf-8")).get("pad_token")
        pad_token = (
            value["content"] if isinstance(value, dict) else (value or pad_token)
        )
    pad_id = tokenizer.token_to_id(pad_token)
    tokenizer.enable_padding(pad_id=pad_id or 0, pad_token=pad_token)
    return tokenizer


def _feeds(session: Any, encodings: list[Any]) -> dict[str, np.ndarray]:
    available = {inp.name for inp in session.get_inputs()}
    feeds: dict[str, np.ndarray] = {
        "input_ids": np.asarray([e.ids for e in encodings], dtype=np.int64),
        "attention_mask": np.asarray(
            [e.attention_mask for e in encodings], dtype=np.int64
        ),
    }
    if "token_type_ids" in available:
        feeds["token_type_ids"] = np.asarray(
            [e.type_ids for e in encodings], dtype=np.int64
        )
    return {name: value for name, value in feeds.items() if name in available}


class OnnxEmbedder:
    """Sentence embeddings: transformer → CLS token → L2-normalize."""

    def __init__(self, spec: EncoderSpec, *, max_length: int = 8192) -> None:
        root = ensure_files(spec)
        self._session = _session(root / spec.model.path)
        self._tokenizer = _tokenizer(root, spec, max_length)
        from tokenizers import Tokenizer

        self._count_tokenizer = Tokenizer.from_str(self._tokenizer.to_str())
        self._count_tokenizer.no_truncation()
        self._count_tokenizer.no_padding()
        self._dimension: int | None = None

    def token_count(self, text: str) -> int:
        return len(self._count_tokenizer.encode(text).ids)

    def get_embedding_dimension(self) -> int:
        if self._dimension is None:
            self._dimension = int(self.encode(["dimension probe"]).shape[1])
        return self._dimension

    def encode(
        self,
        texts: list[str],
        batch_size: int = 32,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        del show_progress_bar
        batches: list[np.ndarray] = []
        for start in range(0, len(texts), batch_size):
            encodings = self._tokenizer.encode_batch(texts[start : start + batch_size])
            hidden = self._session.run(None, _feeds(self._session, encodings))[0]
            vectors = hidden[:, 0, :].astype(np.float32)
            if normalize_embeddings:
                norms = np.linalg.norm(vectors, axis=1, keepdims=True)
                vectors = vectors / np.maximum(norms, 1e-12)
            batches.append(vectors)
        return np.concatenate(batches) if batches else np.zeros((0, 0), np.float32)


class OnnxCrossEncoder:
    """Query–passage relevance scores (the model's single logit)."""

    def __init__(self, spec: EncoderSpec, *, max_length: int = 512) -> None:
        root = ensure_files(spec)
        self._session = _session(root / spec.model.path)
        self._tokenizer = _tokenizer(root, spec, max_length)

    def predict(
        self, pairs: list[tuple[str, str]], batch_size: int = 16
    ) -> list[float]:
        scores: list[float] = []
        for start in range(0, len(pairs), batch_size):
            encodings = self._tokenizer.encode_batch(pairs[start : start + batch_size])
            logits = self._session.run(None, _feeds(self._session, encodings))[0]
            scores.extend(
                float(row[0]) for row in np.asarray(logits).reshape(len(encodings), -1)
            )
        return scores


GRANITE_EMBEDDING_R2 = EncoderSpec(
    repo="onnx-community/granite-embedding-english-r2-ONNX",
    revision="2a49b9c076aa627b14bc528b36b67462808ccc23",
    model=RemoteFile(
        "onnx/model.onnx",
        "ce8cf0b24f01ef35797265b7c392da8fc0a79e532ab6972a82e4c1a90f8466cb",
        324575,
    ),
    tokenizer=RemoteFile("tokenizer.json"),
    extra=(
        RemoteFile(
            "onnx/model.onnx_data",
            "8908e322c264f4ce0618efb5405a2b044541efc8711fa770f56ca9661898cb49",
            604445696,
        ),
        RemoteFile("special_tokens_map.json"),
    ),
    source_repo="ibm-granite/granite-embedding-english-r2",
)

MS_MARCO_MINILM_L6 = EncoderSpec(
    repo="cross-encoder/ms-marco-MiniLM-L6-v2",
    revision="233902d25c440f23af6f7d6e94d2946bac0bee0a",
    model=RemoteFile(
        "onnx/model.onnx",
        "5d3e70fd0c9ff14b9b5169a51e957b7a9c74897afd0a35ce4bd318150c1d4d4a",
        91011230,
    ),
    tokenizer=RemoteFile("tokenizer.json"),
    extra=(RemoteFile("special_tokens_map.json"),),
)

# Model names as configured (configs/*.toml) → their ONNX builds.
EMBEDDING_SPECS = {"ibm-granite/granite-embedding-english-r2": GRANITE_EMBEDDING_R2}
RERANKER_SPECS = {"cross-encoder/ms-marco-MiniLM-L6-v2": MS_MARCO_MINILM_L6}
