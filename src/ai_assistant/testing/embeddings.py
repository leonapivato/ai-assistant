"""A canonical, dependency-free :class:`~ai_assistant.core.protocols.Embedder` fake.

The shared test double for the ``Embedder`` contract, so a subsystem that depends
on embeddings (the vector store, orchestration, ...) can test against a real,
contract-correct embedder *without importing the models subsystem's internals*
(CLAUDE.md golden rule 1) and without loading a heavy model. It lives in
``ai_assistant.testing`` so it is importable from any test while staying out of
production code paths (``lint-imports`` forbids production modules from importing
it).

Like the production ``HashingEmbedder`` it maps text to a fixed-length vector by
hashing tokens into buckets and L2-normalising, so shared tokens yield more
similar vectors — enough for a store's similarity search to behave sensibly in a
test. It is **not** semantically meaningful; for real retrieval use
``FastEmbedEmbedder``. Beyond the contract it records every call so a test can
assert what a subsystem asked to embed; only the behaviour pinned by the shared
``Embedder`` conformance suite is part of the contract.
"""

from __future__ import annotations

import hashlib
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import Embedding

_DEFAULT_DIMENSIONS = 64


class FakeEmbedder:
    """A deterministic hashed bag-of-words ``Embedder`` test double.

    Structurally implements :class:`~ai_assistant.core.protocols.Embedder`. Each
    :meth:`embed` batch is recorded to :attr:`calls`; the returned vectors depend
    only on the input text, so batching does not change them.
    """

    def __init__(
        self, *, dimensions: int = _DEFAULT_DIMENSIONS, model_id: str | None = None
    ) -> None:
        """Create the fake embedder.

        Args:
            dimensions: The fixed length of every vector produced; must be >= 1.
            model_id: The identifier vectors are tagged with; must not be blank.
                Defaults to one that encodes the scheme and dimension, so two
                differently-sized fakes are distinguishable (ADR-0006 §4).

        Raises:
            ValueError: If ``dimensions`` is less than one (which would make the
                bucket modulo undefined), or ``model_id`` is blank — a blank tag
                cannot identify an embedding space, so allowing one would let a
                caller configure a fake that fails its own conformance suite.
        """
        if dimensions < 1:
            msg = f"dimensions must be >= 1, got {dimensions}"
            raise ValueError(msg)
        if model_id is not None and not model_id.strip():
            msg = "model_id must not be blank"
            raise ValueError(msg)
        self._dimensions = dimensions
        self._model_id = model_id if model_id is not None else f"fake-embedder-{dimensions}"
        self.calls: list[tuple[str, ...]] = []

    @property
    def model_id(self) -> str:
        """A stable identifier for this fake's (non-semantic) embedding scheme."""
        return self._model_id

    @property
    def dimensions(self) -> int:
        """The fixed length of the vectors this embedder produces."""
        return self._dimensions

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        """Record the batch and return one vector per input, in order.

        The batch is snapshotted as a tuple on record, so a caller mutating the
        passed sequence afterwards cannot reach into :attr:`calls`.
        """
        batch = tuple(texts)
        self.calls.append(batch)
        return [self._embed_one(text) for text in batch]

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

    @property
    def call_count(self) -> int:
        """How many times ``embed`` has been called."""
        return len(self.calls)

    @property
    def embedded_texts(self) -> tuple[str, ...]:
        """Every text passed to ``embed`` so far, flattened across calls, in order."""
        return tuple(text for batch in self.calls for text in batch)
