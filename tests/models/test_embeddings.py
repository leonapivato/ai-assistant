"""Tests for the deterministic HashingEmbedder."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ai_assistant.core.protocols import Embedder
from ai_assistant.models import HashingEmbedder

if TYPE_CHECKING:
    from collections.abc import Sequence


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_conforms_to_protocol() -> None:
    assert isinstance(HashingEmbedder(), Embedder)


async def test_dimensions_and_shape() -> None:
    embedder = HashingEmbedder(dimensions=64)

    [vector] = await embedder.embed(["hello world"])

    assert embedder.dimensions == 64
    assert len(vector) == 64


async def test_is_deterministic() -> None:
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


async def test_embed_returns_one_vector_per_input() -> None:
    embedder = HashingEmbedder()

    vectors = await embedder.embed(["a", "b", "c"])

    assert len(vectors) == 3


async def test_empty_text_is_the_zero_vector() -> None:
    embedder = HashingEmbedder(dimensions=8)

    [vector] = await embedder.embed([""])

    assert all(value == 0.0 for value in vector)
