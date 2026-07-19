"""Shared conformance suite for the Embedder Protocol.

Every ``Embedder`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`EmbedderContract` and
overrides the ``embedder`` fixture; the suite asserts only behaviour *universal*
to the contract — a fixed vector shape, one vector per input in batch order, and
determinism — never the retrieval quality of any one scheme (hashed
bag-of-words vs. a real semantic model), which stays in the per-implementation
test modules.

The suite embeds text, so it is run against the offline embedders
(``HashingEmbedder``, ``FakeEmbedder``) in the default gate. ``FastEmbedEmbedder``
downloads a model on first embed; its embedding behaviour is exercised at
store-wiring integration time, not here (see ``tests/models/test_fastembed_embedder.py``).

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import pytest

from ai_assistant.core.protocols import Embedder


class EmbedderContract:
    """The behavioural contract every ``Embedder`` implementation must satisfy."""

    @pytest.fixture
    def embedder(self) -> Embedder:
        """Override in a subclass to supply the implementation under test."""
        raise NotImplementedError

    def test_conforms_to_protocol(self, embedder: Embedder) -> None:
        assert isinstance(embedder, Embedder)

    def test_dimensions_is_a_positive_int(self, embedder: Embedder) -> None:
        assert isinstance(embedder.dimensions, int)
        assert embedder.dimensions >= 1

    def test_model_id_is_a_nonempty_string(self, embedder: Embedder) -> None:
        # Vectors are tagged with this so a store can detect a model change and
        # re-embed (ADR-0006 §4); a blank tag could not distinguish two spaces.
        assert isinstance(embedder.model_id, str)
        assert embedder.model_id

    async def test_embed_returns_one_vector_per_input_in_order(self, embedder: Embedder) -> None:
        vectors = await embedder.embed(["first text", "second text", "third text"])

        assert len(vectors) == 3

    async def test_every_vector_has_the_declared_dimensions(self, embedder: Embedder) -> None:
        vectors = await embedder.embed(["alpha beta", "gamma"])

        assert all(len(vector) == embedder.dimensions for vector in vectors)

    async def test_vector_components_are_floats(self, embedder: Embedder) -> None:
        [vector] = await embedder.embed(["hello world"])

        assert all(isinstance(value, float) for value in vector)

    async def test_empty_input_returns_no_vectors(self, embedder: Embedder) -> None:
        assert await embedder.embed([]) == []

    async def test_embedding_is_deterministic(self, embedder: Embedder) -> None:
        first = await embedder.embed(["the user likes coffee"])
        second = await embedder.embed(["the user likes coffee"])

        assert first == second

    async def test_each_vector_is_independent_of_its_batch_neighbours(
        self, embedder: Embedder
    ) -> None:
        # A text's vector must depend only on that text, not on what it was
        # batched with — otherwise a store's vector would change with the request
        # shape. Embedding together must match embedding each alone.
        texts = ["coffee please", "spaceship rocket"]

        batched = await embedder.embed(texts)
        one_at_a_time = [(await embedder.embed([text]))[0] for text in texts]

        assert batched == one_at_a_time
