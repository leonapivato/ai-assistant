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

**On cancellation, this suite asserts less than the store suites do, and that is
the honest reading of the rule rather than a gap.** ``core.protocols``' clause
(ADR-0060) has two halves. The *resource* half — never release something while
the work you started is still using it — has no ``Embedder`` implementation it
can bite on: ``FastEmbedEmbedder.embed`` does hand a worker to a thread — since
ADR-0118 §7 a daemon thread it owns rather than ``asyncio.to_thread``'s pooled
one, which changes where the thread comes from and nothing about this clause — so
a cancelled ``embed()`` abandons a running thread, but that thread is the only
user of what it holds and it self-releases when it finishes. Its one lock,
``_load_lock``, is a ``threading.Lock`` taken *and*
released inside the worker, where an unwinding ``CancelledError`` on the event
loop cannot reach it, and inference then runs unlocked on the backend's
documented thread safety. There is no event-loop-held resource to hand over
early, so the "a second caller must not reach it" case the store suites turn on
would be theatre here: it would pass whatever the implementation did.

What *is* live is the propagation half, plus the consequence a caller can
actually observe — an embedder that survives a cancelled call is one that left
nothing held with nobody to release it. That is what the case below pins. If an
``Embedder`` ever acquires something the event loop releases, this is ADR-0054's
bug again and the case needs the store suites' shape.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.protocols import Embedder
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.testing.cancellation import SuspendedCall

#: Ceiling on the cancellation case's waits, so an embedder that never answers
#: fails instead of hanging the suite. A liveness bound, not a latency assertion.
_CANCELLATION_SECONDS = 5.0

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

    # --- cancellation (ADR-0060) -------------------------------------------

    #: Whether this implementation reaches no ``await`` at all inside ``embed`` —
    #: pure computation, nothing handed off, nothing to interrupt mid-flight.
    #: ``core.protocols``' clause is then vacuously satisfied. Left ``False``, the
    #: suite requires the implementation to prove it by overriding
    #: :meth:`embedder_suspended_mid_embed`, so an embedder that grows a handoff
    #: has to say something about what a cancellation does to it. Opting out is a
    #: visible declaration in the subclass, exactly as
    #: ``ContextProviderContract``'s ``serves_a_fixed_instant`` is.
    holds_nothing_across_an_await: bool = False

    def embedder_suspended_mid_embed(
        self,
    ) -> AbstractAsyncContextManager[tuple[Embedder, SuspendedCall]]:
        """Supply an embedder whose next ``embed`` stops at its worker handoff.

        Override unless :attr:`holds_nothing_across_an_await` is set. The
        suspension has to be arranged rather than raced for: a real batch resolves
        inside a single event-loop turn, so a case that merely cancels a freshly
        started task finds it already finished and asserts nothing.
        """
        raise NotImplementedError

    @pytest.mark.optional_obligation
    async def test_a_cancelled_embed_is_not_absorbed_and_strands_nothing(self) -> None:
        """``core.protocols``' cancellation clause, on the embedding path (ADR-0060).

        Two properties, and the module docstring says why they are the whole of it
        for this seam. The cancellation is delivered onward rather than turned
        into a return value; and once the abandoned work is let go, nothing was
        left held with nobody to release it — a later ``embed`` still answers.

        Note what is deliberately **absent**: the store suites require that a
        second caller *cannot* reach the resource while the cancelled call's work
        runs. That is exactly wrong here. No ``Embedder`` owns an event-loop
        resource to withhold, so a second ``embed`` overlapping an abandoned one
        is correct behaviour, and requiring otherwise would forbid the very shape
        ``FastEmbedEmbedder``'s worker handoff has. ADR-0118 §7 bounds how many
        workers an embedder may have *abandoned* at once, which is a different
        thing and deliberately admits this overlap: the bound is over callers that
        stopped waiting, not over callers that are still waiting. What the clause
        still
        forbids is the other direction — a call left holding something with
        nothing running that will release it — which is what the overlapping and
        the subsequent ``embed`` below detect, by completing at all.

        The overlapping call is how far this reaches, and it is worth being
        exact about the limit. It runs while the cancelled call's work is still
        suspended, so an embedder that released an event-loop resource early
        would serve it off state that work still holds — observable here only in
        what comes back. Proving *non-overlap* the way the store suites do needs
        a resource to observe, and no ``Embedder`` has one; the hook for it
        belongs to whichever change first gives an ``Embedder`` something the
        event loop releases (issue #378).

        **When the cancellation is delivered is likewise not asserted.** The
        clause permits a method to "defer delivery while it makes its resources
        safe", so an embedder that waited out its worker before re-raising is as
        conforming as one that raises at once. The work is therefore released
        *before* the cancellation is awaited, so both shapes pass; pinning
        promptness here would invent a guarantee the contract does not give.
        """
        if self.holds_nothing_across_an_await:
            pytest.skip("embed reaches no await, so a cancellation cannot land inside it")

        async with self.embedder_suspended_mid_embed() as (embedder, suspended):
            embedding = asyncio.ensure_future(embedder.embed(["alpha beta"]))
            overlapping = None
            try:
                await suspended.reached()
                embedding.cancel()

                # A second call issued while the abandoned work is still running.
                # ADR-0060 §5: "the moment an `Embedder` acquires something the
                # event loop releases, it is the ADR-0054 bug again" — and an
                # embedder that unwound out of such a resource would serve this
                # one off state its own cancelled worker is still using.
                #
                # `settle` is load-bearing, not decoration: `ensure_future` only
                # *schedules* the call, so without it the release below runs
                # first and the two never overlap at all.
                overlapping = asyncio.ensure_future(embedder.embed(["gamma delta"]))
                await settle()
            finally:
                suspended.release()

            # Delivered onward, never converted into a return value. Awaited only
            # after the release, because the clause allows delivery to be deferred
            # until the work is safe — see the docstring.
            async with asyncio.timeout(_CANCELLATION_SECONDS):
                with pytest.raises(asyncio.CancelledError):
                    await embedding
                [overlapped] = await overlapping

            # Nothing was stranded: the same embedder still serves the same text.
            # An implementation that unwound out of a lock it never releases would
            # hang here rather than answer, which the timeout turns into a failure.
            async with asyncio.timeout(_CANCELLATION_SECONDS):
                [vector] = await embedder.embed(["alpha beta"])
            for produced in (overlapped, vector):
                assert len(produced) == embedder.dimensions
                assert all(math.isfinite(value) for value in produced)
