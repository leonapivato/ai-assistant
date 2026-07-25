"""Tests for the deterministic HashingEmbedder.

Behaviour universal to the ``Embedder`` contract (shape, order, determinism) is
asserted by the shared :class:`EmbedderContract`, run here via
:class:`TestHashingEmbedderContract`. Only HashingEmbedder-specific behaviour —
constructor validation, unit norm, the zero vector, and shared-token similarity —
is pinned in this module.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pytest
from embedder_contract import EmbedderContract

from ai_assistant.models import HashingEmbedder

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import Embedder


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class TestHashingEmbedderContract(EmbedderContract):
    """Runs HashingEmbedder through the shared Embedder conformance suite."""

    @pytest.fixture
    def embedder(self) -> Embedder:
        return HashingEmbedder()


@pytest.mark.parametrize("dimensions", [0, -1])
def test_non_positive_dimensions_are_rejected(dimensions: int) -> None:
    with pytest.raises(ValueError, match="dimensions must be >= 1"):
        HashingEmbedder(dimensions=dimensions)


async def test_embedding_is_exactly_deterministic() -> None:
    # The shared contract only requires repeatability within tolerance, since the
    # Protocol does not promise bit-for-bit reproducibility. This embedder does
    # promise it — its docstring calls it deterministic, and it is pure hashing
    # arithmetic — so the stronger guarantee is pinned here rather than imposed
    # on every implementation.
    embedder = HashingEmbedder()

    first = await embedder.embed(["the user likes coffee"])
    second = await embedder.embed(["the user likes coffee"])

    assert first == second


async def test_vectors_are_unit_norm() -> None:
    embedder = HashingEmbedder()

    [vector] = await embedder.embed(["some tokens here"])

    assert math.isclose(math.sqrt(_dot(vector, vector)), 1.0, rel_tol=1e-9)


async def test_shared_tokens_are_more_similar_than_disjoint() -> None:
    embedder = HashingEmbedder()

    base, overlapping, disjoint = await embedder.embed(
        ["coffee tea", "coffee milk", "spaceship rocket"]
    )

    assert _dot(base, overlapping) > _dot(base, disjoint)


async def test_empty_text_is_the_zero_vector() -> None:
    embedder = HashingEmbedder(dimensions=8)

    [vector] = await embedder.embed([""])

    assert all(value == 0.0 for value in vector)
