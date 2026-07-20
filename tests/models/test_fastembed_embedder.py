"""Tests for the fastembed-backed embedder.

These stay offline in two different ways, and the difference matters:

- Against the **real** backend, only metadata is read (supported models and their
  dimensions), which ``fastembed`` resolves without a download. That is what pins
  "production construction is unchanged and really does use fastembed".
- Against a **stub** backend, the adapter itself is exercised end to end and run
  through the shared :class:`EmbedderContract` — one vector per input in batch
  order, the declared shape, finite floats, repeatability. Those are the
  properties that could regress on a fastembed version bump or a refactor of this
  module, and until the backend seam existed none of them ran in the gate.

Real embedding still downloads a model, so it is exercised when the persistent
store is wired, not here.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
from embedder_contract import EmbedderContract

from ai_assistant.core.errors import ModelError
from ai_assistant.core.protocols import Embedder
from ai_assistant.models.fastembed_embedder import (
    FastEmbedBackend,
    FastEmbedEmbedder,
    FastEmbedTextModel,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

_BGE_SMALL_DIMENSIONS = 384

_STUB_MODEL = "stub/embedding-model"
_STUB_DIMENSIONS = 16


class _StubTextModel:
    """A deterministic stand-in for a loaded fastembed model.

    Hashes tokens into buckets — not semantically meaningful, and not trying to
    be. What it has to be is *deterministic* and *batch-independent*, so the
    contract's ordering and repeatability checks bite on the adapter rather than
    on the stub's noise.

    It deliberately yields a lazy iterator of ``int`` tuples rather than a list of
    ``float`` lists: the adapter is responsible for materialising the result and
    coercing components to ``float``, and returning something already in the
    target shape would let a regression in either slide through.
    """

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def embed(self, documents: list[str]) -> Iterable[Iterable[float]]:
        self.batches.append(list(documents))
        return (self._embed_one(document) for document in documents)

    @staticmethod
    def _embed_one(text: str) -> tuple[int, ...]:
        buckets = [0] * _STUB_DIMENSIONS
        for token in text.lower().split():
            # A real digest, not a cheap character sum: distinct tokens must land
            # in distinct buckets, or two of the contract's inputs would embed
            # identically and its batch-permutation check would pass vacuously.
            # (`test_the_stub_distinguishes_the_contract_inputs` holds that.)
            digest = hashlib.sha256(token.encode()).digest()
            buckets[int.from_bytes(digest[:8], "big") % _STUB_DIMENSIONS] += 1
        return tuple(buckets)


class _StubBackend:
    """A fastembed backend that never touches the network."""

    def __init__(self, *, dimensions: int = _STUB_DIMENSIONS) -> None:
        self._dimensions = dimensions
        self.loads: list[str] = []
        self.model = _StubTextModel()

    def dimensions_by_model(self) -> Mapping[str, int]:
        return {_STUB_MODEL: self._dimensions}

    def load(self, model: str) -> FastEmbedTextModel:
        self.loads.append(model)
        return self.model


def _stub_embedder(backend: FastEmbedBackend | None = None) -> FastEmbedEmbedder:
    return FastEmbedEmbedder(model=_STUB_MODEL, backend=backend or _StubBackend())


class TestFastEmbedEmbedderContract(EmbedderContract):
    """Runs FastEmbedEmbedder's adapter layer through the shared conformance suite.

    The subject is the real ``FastEmbedEmbedder`` — only the fastembed backend
    beneath it is stubbed. So everything the suite asserts is asserted of this
    module's code.
    """

    @pytest.fixture
    def embedder(self) -> Embedder:
        return _stub_embedder()


def test_conforms_to_protocol() -> None:
    assert isinstance(FastEmbedEmbedder(), Embedder)


def test_default_model_dimensions() -> None:
    # Reads the real fastembed metadata: production construction is untouched by
    # the backend seam and still resolves its dimension from fastembed itself.
    assert FastEmbedEmbedder().dimensions == _BGE_SMALL_DIMENSIONS


def test_unknown_model_raises() -> None:
    with pytest.raises(ModelError, match="unknown fastembed model"):
        FastEmbedEmbedder(model="not-a-real-model")


def test_unknown_model_raises_against_a_stub_backend() -> None:
    with pytest.raises(ModelError, match="unknown fastembed model"):
        FastEmbedEmbedder(model="not-a-real-model", backend=_StubBackend())


@pytest.mark.parametrize("dimensions", [0, -1])
def test_non_positive_dimension_is_rejected(dimensions: int) -> None:
    # A backend reporting a useless dimension has to fail here, at construction,
    # rather than downstream in a store that sized its vector column from it.
    with pytest.raises(ModelError, match="non-positive dimension"):
        _stub_embedder(_StubBackend(dimensions=dimensions))


def test_model_id_is_the_configured_model() -> None:
    assert _stub_embedder().model_id == _STUB_MODEL


def test_construction_does_not_load_the_model() -> None:
    backend = _StubBackend()

    _stub_embedder(backend)

    assert backend.loads == []


async def test_the_model_is_loaded_once_and_reused() -> None:
    backend = _StubBackend()
    embedder = _stub_embedder(backend)

    await embedder.embed(["first"])
    await embedder.embed(["second"])

    assert backend.loads == [_STUB_MODEL]


async def test_an_empty_batch_does_not_load_the_model() -> None:
    # The short-circuit is what keeps `embed([])` free of a model download.
    backend = _StubBackend()
    embedder = _stub_embedder(backend)

    assert await embedder.embed([]) == []
    assert backend.loads == []


async def test_the_batch_reaches_the_backend_unchanged() -> None:
    backend = _StubBackend()
    embedder = _stub_embedder(backend)

    await embedder.embed(("zulu", "alpha", "zulu"))

    # A list, in the caller's order, with duplicates intact — fastembed is handed
    # exactly what the caller asked for, not a set or a sorted copy.
    assert backend.model.batches == [["zulu", "alpha", "zulu"]]


async def test_vectors_are_materialised_lists_of_floats() -> None:
    # The stub yields a lazy iterator of int tuples; the adapter owes the caller
    # a real list of lists of floats (a store indexes and re-reads them).
    embedder = _stub_embedder()

    vectors = await embedder.embed(["alpha beta"])

    assert isinstance(vectors, list)
    assert all(isinstance(vector, list) for vector in vectors)
    assert all(isinstance(value, float) for vector in vectors for value in vector)


async def test_embedding_is_exactly_deterministic_for_a_deterministic_backend() -> None:
    # The shared contract only requires repeatability within tolerance, because
    # the Protocol does not promise bit-for-bit reproducibility of a real model.
    # The adapter, though, must not add any variation of its own: given a
    # deterministic backend the output is exactly equal.
    embedder = _stub_embedder()

    first = await embedder.embed(["the user likes coffee"])
    second = await embedder.embed(["the user likes coffee"])

    assert first == second


class _BrokenMetadataBackend:
    """A backend whose offline metadata lookup fails."""

    def dimensions_by_model(self) -> Mapping[str, int]:
        raise RuntimeError("metadata is malformed")

    def load(self, model: str) -> FastEmbedTextModel:
        raise AssertionError("must not be reached")


class _FailingLoadBackend:
    """A backend that supports the model but cannot load it (no network, say)."""

    def __init__(self) -> None:
        self.load_attempts = 0

    def dimensions_by_model(self) -> Mapping[str, int]:
        return {_STUB_MODEL: _STUB_DIMENSIONS}

    def load(self, model: str) -> FastEmbedTextModel:
        self.load_attempts += 1
        raise RuntimeError("download failed")


class _FailingEmbedModel:
    """A loaded model that raises when asked to embed."""

    def embed(self, documents: list[str]) -> Iterable[Iterable[float]]:
        raise RuntimeError("inference failed")


class _FailingEmbedBackend(_StubBackend):
    """A backend that loads fine but whose model cannot embed."""

    def load(self, model: str) -> FastEmbedTextModel:
        self.loads.append(model)
        return _FailingEmbedModel()


def test_a_backend_that_cannot_report_its_models_raises_model_error() -> None:
    # Everything this package raises belongs to the AssistantError hierarchy
    # (CONTRIBUTING, "Errors"), so a caller's `except ModelError` is sufficient
    # and a backend's own exception type never leaks past this adapter.
    with pytest.raises(ModelError, match="could not report its supported models") as caught:
        FastEmbedEmbedder(model=_STUB_MODEL, backend=_BrokenMetadataBackend())

    assert isinstance(caught.value.__cause__, RuntimeError)


async def test_a_failed_load_raises_model_error() -> None:
    embedder = _stub_embedder(_FailingLoadBackend())

    with pytest.raises(ModelError, match="could not load model") as caught:
        await embedder.embed(["alpha"])

    assert isinstance(caught.value.__cause__, RuntimeError)


async def test_a_failed_load_is_retried_on_the_next_call() -> None:
    # A transient failure (network, cold cache) must not wedge the embedder into
    # permanently believing it has no model.
    backend = _FailingLoadBackend()
    embedder = _stub_embedder(backend)

    for _ in range(2):
        with pytest.raises(ModelError):
            await embedder.embed(["alpha"])

    assert backend.load_attempts == 2


async def test_a_failed_embed_raises_model_error() -> None:
    embedder = _stub_embedder(_FailingEmbedBackend())

    with pytest.raises(ModelError, match="failed to embed a batch of 1 text") as caught:
        await embedder.embed(["alpha"])

    assert isinstance(caught.value.__cause__, RuntimeError)


def test_the_stub_distinguishes_the_contract_inputs() -> None:
    # Guards the guard. The contract's batch-order check compares the i-th vector
    # of a batch against that text embedded alone; if two of its inputs embedded
    # to the *same* vector under this stub, a permuting adapter would still match
    # and the check would pass while proving nothing. So the stub owes the
    # contract distinct vectors for its distinct inputs. (An earlier version of
    # this stub summed character codes and collided "alpha" with "mike".)
    model = _StubTextModel()

    vectors = list(model.embed(["zulu text", "alpha text", "mike text", "hello world"]))

    assert len({tuple(vector) for vector in vectors}) == len(vectors)


def test_the_stub_model_is_batch_independent() -> None:
    # Guards the guard: if the stub's vectors depended on the batch, the
    # contract's batch-independence check would be asserting the stub's bug
    # rather than the adapter's correctness, and would fail for the wrong reason.
    model = _StubTextModel()

    def vectors(*texts: str) -> list[tuple[int, ...]]:
        result: Iterator[Iterable[float]] = iter(model.embed(list(texts)))
        return [tuple(int(value) for value in vector) for vector in result]

    assert vectors("zulu", "alpha") == [vectors("zulu")[0], vectors("alpha")[0]]
