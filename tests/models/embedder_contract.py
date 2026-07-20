"""Shared conformance suite for the Embedder Protocol.

Every ``Embedder`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`EmbedderContract` and
overrides the ``embedder`` fixture; the suite asserts only behaviour *universal*
to the contract — a fixed vector shape, one vector per input in batch order, a
stable ``model_id``, and repeatability within tolerance — never the retrieval
quality of any one scheme (hashed bag-of-words vs. a real semantic model), nor
guarantees a single implementation happens to make. Exact, bit-for-bit
determinism is one of the latter: the Protocol does not promise it, so an
implementation that does pins it in its own test module.

The suite embeds text, so every implementation it runs against must be able to
embed offline: the gate runs the whole suite — including ``integration``-marked
tests — with no network. ``HashingEmbedder`` and ``FakeEmbedder`` are offline by
construction. ``FastEmbedEmbedder`` is not, so it runs here through the
injectable backend seam in ``ai_assistant.models.fastembed_embedder``: the
subject is the real adapter, with a deterministic stub standing in for fastembed
beneath it (``tests/models/test_fastembed_embedder.py``). That covers the layer
that could regress — vector count, batch order, shape, finiteness — while
fastembed itself, whose ``embed`` downloads a model on first use, stays out of
the gate. Patching ``TextEmbedding`` out was rejected as the alternative: it
would assert properties of the patch rather than of the adapter.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.protocols import Embedder

if TYPE_CHECKING:
    from collections.abc import Sequence

# Vectors are compared within tolerance, never bit-for-bit. The Protocol promises
# shape, cardinality, and order — not exact reproducibility — and a real backend
# may vary in the last bits between calls or batch shapes (batching changes the
# kernel's matrix shapes, so the rounding differs). Requiring exact equality
# would fail a conforming embedder. The tolerance is far tighter than any real
# difference in *meaning*: a permuted or mismatched vector misses by orders of
# magnitude more than this, so the checks below still bite.
_REL_TOLERANCE = 1e-6
_ABS_TOLERANCE = 1e-9


def _vectors_close(actual: Sequence[float], expected: Sequence[float]) -> bool:
    """Whether two vectors agree to within float-noise tolerance."""
    return len(actual) == len(expected) and all(
        math.isclose(x, y, rel_tol=_REL_TOLERANCE, abs_tol=_ABS_TOLERANCE)
        for x, y in zip(actual, expected, strict=True)
    )


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

    async def test_model_id_is_stable(self, embedder: Embedder) -> None:
        # ADR-0006 §4 tags stored vectors with this id to detect that the store
        # was built with a different model. An id that varied between reads — or
        # that changed once the model actually loaded — would make a store
        # disown its own vectors and re-embed forever, so stability is
        # contractual (the Protocol says "a *stable* identifier"), not incidental.
        before = embedder.model_id

        assert embedder.model_id == before  # stable across repeated reads

        await embedder.embed(["some text"])

        assert embedder.model_id == before  # and unchanged by doing work

    async def test_embed_returns_one_vector_per_input(self, embedder: Embedder) -> None:
        # One vector per input *occurrence*: an implementation that deduplicates
        # repeated texts would misalign a caller's records with their vectors.
        # (Blank input is deliberately absent — the Protocol does not say whether
        # an embedder must accept "", so the contract must not decide it here.)
        vectors = await embedder.embed(["zulu text", "alpha text", "zulu text"])

        assert len(vectors) == 3

    async def test_every_vector_has_the_declared_dimensions(self, embedder: Embedder) -> None:
        vectors = await embedder.embed(["alpha beta", "gamma"])

        # Pin the count first: `all(...)` over an empty result is vacuously true,
        # so without this an embedder returning nothing would pass the shape check.
        assert len(vectors) == 2
        assert all(len(vector) == embedder.dimensions for vector in vectors)

    async def test_vector_components_are_finite_floats(self, embedder: Embedder) -> None:
        [vector] = await embedder.embed(["hello world"])

        # Likewise pin the shape: `all(...)` over an empty vector is vacuously
        # true, so an embedder returning [] would otherwise pass this check.
        assert len(vector) == embedder.dimensions
        assert all(isinstance(value, float) for value in vector)
        # Finite, not merely float-typed: inf and NaN are floats and would slip
        # past the check above (inf even compares close to itself), but they
        # poison every downstream similarity computation — inf/inf is NaN, and a
        # NaN distance makes a record unrankable against any query.
        assert all(math.isfinite(value) for value in vector)

    async def test_empty_input_returns_no_vectors(self, embedder: Embedder) -> None:
        assert await embedder.embed([]) == []

    async def test_embedding_the_same_text_twice_is_repeatable(self, embedder: Embedder) -> None:
        # Not bit-for-bit reproducibility, which the Protocol does not promise —
        # but a text must land in the same place each time, or a stored vector
        # would never match a freshly embedded query and retrieval would be
        # meaningless. An implementation that promises exact determinism pins
        # that in its own module.
        first = await embedder.embed(["the user likes coffee"])
        second = await embedder.embed(["the user likes coffee"])

        assert len(first) == len(second) == 1
        assert _vectors_close(first[0], second[0])

    async def test_each_vector_matches_its_own_text_regardless_of_batch(
        self, embedder: Embedder
    ) -> None:
        # Pins the position-to-text mapping *and* batch independence at once: the
        # i-th vector must be what that text embeds to on its own. So an
        # implementation that permutes the batch (or lets a text's vector depend
        # on its neighbours) fails here — a store would otherwise file a record
        # under another record's vector.
        #
        # The inputs are deliberately NOT in lexical order: with a pre-sorted
        # batch, an implementation that sorts before embedding returns the same
        # thing either way and slides through untested.
        #
        # Compared within tolerance, not bit-for-bit: this is the one check that
        # spans two different batch shapes, exactly where a real backend's
        # rounding may legitimately differ. A permuted vector is nowhere near
        # tolerance, so the check keeps all of its force.
        texts = ["zulu text", "alpha text", "mike text"]
        assert texts != sorted(texts), "inputs must be unsorted for this to bite"

        batched = await embedder.embed(texts)
        alone = [(await embedder.embed([text]))[0] for text in texts]

        assert len(batched) == len(texts)
        assert all(_vectors_close(b, a) for b, a in zip(batched, alone, strict=True))
