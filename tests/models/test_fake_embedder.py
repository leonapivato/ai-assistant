"""The canonical FakeEmbedder passes the shared Embedder conformance suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeEmbedder`` as
a stand-in for a real embedder: it is held to the same contract as
``HashingEmbedder``. Behaviour beyond the shared contract — call recording, a
configurable id, and shared-token similarity — is pinned here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from embedder_contract import EmbedderContract

from ai_assistant.testing import FakeEmbedder

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import Embedder


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class TestFakeEmbedderContract(EmbedderContract):
    """Runs FakeEmbedder through the shared Embedder conformance suite."""

    @pytest.fixture
    def embedder(self) -> Embedder:
        return FakeEmbedder()


@pytest.mark.parametrize("dimensions", [0, -1])
def test_non_positive_dimensions_are_rejected(dimensions: int) -> None:
    with pytest.raises(ValueError, match="dimensions must be >= 1"):
        FakeEmbedder(dimensions=dimensions)


def test_default_model_id_encodes_dimensions() -> None:
    assert FakeEmbedder(dimensions=32).model_id == "fake-embedder-32"


def test_model_id_is_configurable() -> None:
    assert FakeEmbedder(model_id="custom-space").model_id == "custom-space"


async def test_shared_tokens_are_more_similar_than_disjoint() -> None:
    embedder = FakeEmbedder()

    base, overlapping, disjoint = await embedder.embed(
        ["coffee tea", "coffee milk", "spaceship rocket"]
    )

    assert _dot(base, overlapping) > _dot(base, disjoint)


async def test_records_each_embed_call() -> None:
    embedder = FakeEmbedder()

    await embedder.embed(["one", "two"])
    await embedder.embed(["three"])

    assert embedder.call_count == 2
    assert embedder.calls == [("one", "two"), ("three",)]
    assert embedder.embedded_texts == ("one", "two", "three")


async def test_recorded_calls_are_isolated_from_caller_mutation() -> None:
    embedder = FakeEmbedder()
    texts = ["coffee note"]

    await embedder.embed(texts)
    texts.append("sneaked in")  # caller keeps and mutates the list after the call

    assert embedder.calls == [("coffee note",)]  # the recorded snapshot is unaffected
