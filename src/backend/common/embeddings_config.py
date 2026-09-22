from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field
from src.backend.common.config import PROJECT_ROOT

DEFAULT_EMBEDDINGS_PATH = PROJECT_ROOT / "configs" / "embeddings.toml"


class EmbeddingPolicy(BaseModel):
    """Embedding model contract. Versioned in configs/embeddings.toml;
    the model name is the chunk_embeddings row key, so a model swap
    orphans old rows instead of mixing vectors."""

    embeddings_config_version: str
    model: str
    dimension: int = Field(ge=1)
    query_prefix: str
    document_prefix: str
    batch_size: int = Field(ge=1)
    min_similarity: float
def load_embedding_policy(
    path: Path = DEFAULT_EMBEDDINGS_PATH,
) -> EmbeddingPolicy:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return EmbeddingPolicy.model_validate(
        {
            "embeddings_config_version": raw["version"][
                "embeddings_config_version"
            ],
            **raw["model"],
            **raw["ingest"],
            **raw["query"],
        }
    )