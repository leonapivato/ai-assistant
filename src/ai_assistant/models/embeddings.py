"""A deterministic, dependency-free :class:`~ai_assistant.core.protocols.Embedder`.

``HashingEmbedder`` maps text to a fixed-length vector by hashing tokens into
buckets (a hashed bag-of-words) and L2-normalising. Its similarity therefore
reflects only *shared tokens* — it is **not** semantically meaningful. It exists
so the embedding seam and any vector store built on it can be tested and run
deterministically and offline; use ``FastEmbedEmbedder`` for real retrieval.
"""

from __future__ import annotations

import hashlib
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import Embedding

_DEFAULT_DIMENSIONS = 256


class HashingEmbedder:
    """A deterministic hashed bag-of-words embedder for tests and offline use."""

    def __init__(self, *, dimensions: int = _DEFAULT_DIMENSIONS) -> None:
        """Initialise the embedder.

        Args:
            dimensions: The length of the vectors produced.
        """
        self._dimensions = dimensions

    @property
    def model_id(self) -> str:
        """A stable identifier for this embedder's (non-semantic) scheme."""
        return f"hashing-{self._dimensions}"

    @property
    def dimensions(self) -> int:
        """The fixed length of the vectors this embedder produces."""
        return self._dimensions

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        """Embed a batch of texts, returning one vector per input, in order."""
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:8], "big") % self._dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]
