"""Tests for the deadline over the embedding seam (ADR-0118 §2, §3, §4 and §5).

The decorator is itself an ``Embedder``, so it runs through the shared conformance
suite — ADR-0118 §9 adds no case to that suite and this adds none either; the
bounded embedder is simply measured against it like every other implementation.

Containment is *not* tested here. ADR-0118 §7's third clause puts that obligation
on the implementation that dispatches, and ``test_embed_worker.py`` is where it is
pinned; a decorator observes an inner ``Embedder`` through the Protocol and has no
reach into how that implementation executes.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
from typing import TYPE_CHECKING

import pytest
from embedder_contract import EmbedderContract

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import (
    ConfigurationError,
    EmbeddingDeadlineExpiredError,
    MemoryStoreError,
    ModelError,
)
from ai_assistant.models.bounded_embedder import DEFAULT_TIMEOUT_SECONDS, BoundedEmbedder
from ai_assistant.testing import FakeEmbedder

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from ai_assistant.core.protocols import Embedder
    from ai_assistant.core.types import Embedding
    from ai_assistant.testing.cancellation import SuspendedCall

#: Long enough that no case below expires by accident. Every expiry in this module
#: is provoked with a deadline measured in milliseconds instead.
_GENEROUS_SECONDS = 30.0

#: Short enough that a call which never answers expires promptly, long enough that
#: an ordinary in-process call does not. Not a latency assertion — the calls it
#: fires against are parked indefinitely by construction.
_TINY_SECONDS = 0.05


class TestBoundedEmbedderContract(EmbedderContract):
    """Runs the bounded embedder through the shared Embedder conformance suite.

    Wrapping the canonical fake rather than a bespoke double: what the suite has to
    establish is that a *wrapped* embedder is still a conforming one, and the fake
    is already held to the same contract (``test_fake_embedder.py``).
    """

    @pytest.fixture
    def embedder(self) -> Embedder:
        return BoundedEmbedder(FakeEmbedder(), timeout_seconds=_GENEROUS_SECONDS)

    @contextlib.asynccontextmanager
    async def embedder_suspended_mid_embed(self) -> AsyncIterator[tuple[Embedder, SuspendedCall]]:
        """Suspend the inner embedder, which is the only place this one can suspend.

        The decorator adds no handoff of its own — it awaits whatever the inner
        embedder does — so the fake's modelled handoff is exactly the suspension
        point a cancellation lands on here.
        """
        inner = FakeEmbedder()
        yield BoundedEmbedder(inner, timeout_seconds=_GENEROUS_SECONDS), inner.suspend_next_embed()


class _NeverAnswers:
    """An inner ``Embedder`` whose ``embed`` suspends and does not come back."""

    def __init__(self, *, dimensions: int = 4) -> None:
        self.calls = 0
        self._dimensions = dimensions

    @property
    def model_id(self) -> str:
        return "never-answers"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        self.calls += 1
        await asyncio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover - the wait never returns


class _SwallowsItsCancellation:
    """An inner ``Embedder`` that absorbs the cancellation and answers anyway.

    ADR-0118's deadline is delivered as a cancellation, and ``models/retry.py``
    already records what an inner call that swallows one costs: the context manager
    exits quietly and hands back a result produced after the deadline had passed.
    """

    def __init__(self, *, dimensions: int = 4) -> None:
        self._dimensions = dimensions

    @property
    def model_id(self) -> str:
        return "swallows-its-cancellation"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.Event().wait()
        return [[0.0] * self._dimensions for _ in texts]


# --- delegation (ADR-0118 §2) ---------------------------------------------


def test_model_id_is_delegated_unchanged() -> None:
    # The embedding-space identity ADR-0006 §4 ranks on and ADR-0024 §2 pins. A
    # wrapper that rewrote it would make a store disown every vector it holds.
    inner = FakeEmbedder(model_id="some-space")

    assert BoundedEmbedder(inner).model_id == "some-space"


def test_dimensions_are_delegated_unchanged() -> None:
    assert BoundedEmbedder(FakeEmbedder(dimensions=64)).dimensions == 64


async def test_the_batch_reaches_the_inner_embedder_unchanged() -> None:
    inner = FakeEmbedder()
    bounded = BoundedEmbedder(inner)

    await bounded.embed(("zulu", "alpha", "zulu"))

    # In the caller's order, with duplicates intact: a wrapper that deduplicated or
    # sorted would misalign a store's records with their vectors.
    assert inner.calls == [("zulu", "alpha", "zulu")]


async def test_the_inner_vectors_are_returned_unchanged() -> None:
    inner = FakeEmbedder()
    bounded = BoundedEmbedder(inner)

    assert await bounded.embed(["alpha beta"]) == await inner.embed(["alpha beta"])


# --- the deadline (ADR-0118 §3, §4, §5) ------------------------------------


async def test_a_call_that_never_answers_expires_with_its_own_class() -> None:
    """ADR-0118 §5's first clause: the expiry names the deadline, by class."""
    bounded = BoundedEmbedder(_NeverAnswers(), timeout_seconds=_TINY_SECONDS)

    with pytest.raises(EmbeddingDeadlineExpiredError, match=r"0\.05s deadline"):
        await bounded.embed(["alpha"])


async def test_the_expiry_is_not_a_backend_fault_or_a_store_fault() -> None:
    """ADR-0118 §5, stated as the two negatives it is actually about.

    ``ModelError`` is what both shipped embedders raise for a backend fault and
    ``MemoryStoreError`` is what a store raises for a store fault; a discriminator
    that a caller's existing ``except`` already swallowed would discriminate
    nothing. The positive half — that it is an ``AssistantError`` — is what keeps
    an adapter's one error boundary sufficient.
    """
    bounded = BoundedEmbedder(_NeverAnswers(), timeout_seconds=_TINY_SECONDS)

    with pytest.raises(EmbeddingDeadlineExpiredError) as caught:
        await bounded.embed(["alpha"])

    assert not isinstance(caught.value, ModelError)
    assert not isinstance(caught.value, MemoryStoreError)


async def test_an_expired_call_is_not_retried() -> None:
    """ADR-0118 §3: exactly one attempt, no retry, no backoff.

    Against a wedged backend each retry would abandon another worker, so the
    mechanism meant to survive the failure would amplify it.
    """
    inner = _NeverAnswers()
    bounded = BoundedEmbedder(inner, timeout_seconds=_TINY_SECONDS)

    with pytest.raises(EmbeddingDeadlineExpiredError):
        await bounded.embed(["alpha"])

    assert inner.calls == 1


async def test_an_inner_that_swallows_the_cancellation_still_expires() -> None:
    """The arm ``deadline.expired()`` exists for, and it is not hypothetical.

    ``asyncio`` abandons a call by cancelling it, so an inner embedder that
    absorbed the cancellation would return vectors produced after the deadline had
    passed — and the context manager would exit quietly. A caller told that a
    30-second bound holds would have waited arbitrarily long for a success.
    """
    bounded = BoundedEmbedder(_SwallowsItsCancellation(), timeout_seconds=_TINY_SECONDS)

    with pytest.raises(EmbeddingDeadlineExpiredError):
        await bounded.embed(["alpha"])


async def test_an_inner_failure_propagates_unwrapped() -> None:
    """The inner embedder's vocabulary is its own, and this seam adds nothing.

    Re-labelling a missing model artifact as a deadline problem would send an
    operator to the wrong remedy — and ADR-0024 §5's message names the cause
    precisely so that does not happen.
    """
    sentinel = ModelError("the packaged embedding model artifact is missing")

    class _Failing(FakeEmbedder):
        async def embed(self, texts: Sequence[str]) -> list[Embedding]:
            raise sentinel

    with pytest.raises(ModelError) as caught:
        await BoundedEmbedder(_Failing()).embed(["alpha"])

    assert caught.value is sentinel


async def test_an_outer_cancellation_is_not_converted_into_an_expiry() -> None:
    """``core/protocols.py``'s cancellation clause (ADR-0060 §1), at this seam.

    ``asyncio.timeout`` leaves a cancellation it did not cause alone. A hub
    shutting down must not be reported as an embedding backend that wedged — the
    two have different remedies and only one of them pages anybody.
    """
    inner = FakeEmbedder()
    bounded = BoundedEmbedder(inner, timeout_seconds=_GENEROUS_SECONDS)
    suspended = inner.suspend_next_embed()

    call = asyncio.ensure_future(bounded.embed(["alpha"]))
    await suspended.reached()
    call.cancel()

    with pytest.raises(asyncio.CancelledError):
        await call


async def test_a_call_inside_the_deadline_is_untouched() -> None:
    # The bound is a ceiling on pathology, not a latency gate: an ordinary call
    # returns the inner embedder's own answer with nothing added.
    bounded = BoundedEmbedder(FakeEmbedder(), timeout_seconds=_GENEROUS_SECONDS)

    [vector] = await bounded.embed(["alpha beta"])

    assert len(vector) == bounded.dimensions
    assert all(math.isfinite(value) for value in vector)


# --- construction ----------------------------------------------------------


def test_the_default_deadline_matches_the_settings_default() -> None:
    # A construction that names no deadline is bounded the way a default
    # deployment is, rather than not at all.
    assert Settings().embedding_timeout_seconds == DEFAULT_TIMEOUT_SECONDS


def test_from_settings_reads_the_configured_deadline() -> None:
    settings = Settings(embedding_timeout_seconds=12.5)

    bounded = BoundedEmbedder.from_settings(FakeEmbedder(), settings)

    assert bounded._timeout_seconds == 12.5


@pytest.mark.parametrize(
    "value",
    [
        0,
        -1.0,
        float("inf"),
        float("nan"),
        # `True` is a float by inheritance, and a boolean deadline is a mistake
        # worth naming rather than coercing to one second — `RetryPolicy`'s own
        # words for the same hazard one seam over.
        True,
        "30",
    ],
)
def test_an_unusable_deadline_is_refused_at_construction(value: object) -> None:
    """``Settings`` refuses all of these at load; this guards the direct seam.

    ``RetryPolicy.__post_init__``'s shape and its reasons: an infinite deadline
    disables the bound silently, and a NaN one makes ``asyncio.timeout`` behave
    unpredictably.
    """
    with pytest.raises(ConfigurationError):
        BoundedEmbedder(FakeEmbedder(), timeout_seconds=value)  # type: ignore[arg-type]  # invalid input under test


def test_a_whole_number_of_seconds_is_accepted() -> None:
    # An exact `int` is how a caller writes a whole number of seconds, and
    # refusing it would make this constructor stricter than the settings model
    # that feeds it.
    assert BoundedEmbedder(FakeEmbedder(), timeout_seconds=45)._timeout_seconds == 45.0
