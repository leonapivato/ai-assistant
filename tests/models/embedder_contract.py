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
is deliberately **not** run through it: its ``embed`` downloads a model on first
use, and the gate runs the whole suite — including ``integration``-marked tests —
with no network. The two ways to include it both cost more than they buy:
patching ``TextEmbedding`` out would assert properties of the patch rather than
of fastembed (a green that proves nothing), and letting it download would make
the gate network-dependent. Covering its adapter layer honestly needs an
injection seam in ``FastEmbedEmbedder`` itself — a ``models`` change, tracked as
a follow-up rather than smuggled into this testing slice. Its metadata is
asserted offline in ``tests/models/test_fastembed_embedder.py``.

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

    def test_model_id_is_a_nonblank_string(self, embedder: Embedder) -> None:
        # Vectors are tagged with this so a store can detect a model change and
        # re-embed (ADR-0006 §4); a blank tag could not distinguish two spaces.
        # Whitespace-only is as useless a tag as empty, so both are rejected.
        assert isinstance(embedder.model_id, str)
        assert embedder.model_id.strip()

    async def test_embed_returns_one_vector_per_input(self, embedder: Embedder) -> None:
        # One vector per input *occurrence*: an implementation that deduplicates
        # repeated texts would misalign a caller's records with their vectors.
        # (Blank input is deliberately absent — the Protocol does not say whether
        # an embedder must accept "", so the contract must not decide it here.)
        vectors = await embedder.embed(["zulu text", "alpha text", "zulu text"])

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

    async def test_each_vector_matches_its_own_text_regardless_of_batch(
        self, embedder: Embedder
    ) -> None:
        # Pins the position-to-text mapping *and* batch independence at once: the
        # i-th vector must be exactly what that text embeds to on its own. So an
        # implementation that permutes the batch (or lets a text's vector depend
        # on its neighbours) fails here — a store would otherwise file a record
        # under another record's vector.
        #
        # The inputs are deliberately NOT in lexical order: with a pre-sorted
        # batch, an implementation that sorts before embedding returns the same
        # thing either way and slides through untested.
        texts = ["zulu text", "alpha text", "mike text"]
        assert texts != sorted(texts), "inputs must be unsorted for this to bite"

        batched = await embedder.embed(texts)
        alone = [(await embedder.embed([text]))[0] for text in texts]

        assert batched == alone
