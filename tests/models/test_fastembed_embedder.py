"""Offline tests for the fastembed-backed embedder.

These construct the embedder and read its metadata without loading a model, so
they stay offline. Real embedding (which downloads a model) is exercised when
the persistent store is wired, not in this gate.
"""

from __future__ import annotations

import pytest

from ai_assistant.core.errors import ModelError
from ai_assistant.core.protocols import Embedder
from ai_assistant.models.fastembed_embedder import FastEmbedEmbedder

_BGE_SMALL_DIMENSIONS = 384


def test_conforms_to_protocol() -> None:
    assert isinstance(FastEmbedEmbedder(), Embedder)


def test_default_model_dimensions() -> None:
    assert FastEmbedEmbedder().dimensions == _BGE_SMALL_DIMENSIONS


def test_unknown_model_raises() -> None:
    with pytest.raises(ModelError, match="unknown fastembed model"):
        FastEmbedEmbedder(model="not-a-real-model")
