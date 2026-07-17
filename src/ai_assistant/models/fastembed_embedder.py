"""The on-device default :class:`~ai_assistant.core.protocols.Embedder` (ADR-0006).

``FastEmbedEmbedder`` runs a local embedding model via ``fastembed``, so memory
content is never sent off-device merely to be indexed. This module is the only
place ``fastembed`` is imported; it is intentionally *not* re-exported from
``ai_assistant.models`` so importing that package stays cheap (importing
``fastembed`` pulls in ONNX runtime). Import this class directly when wiring the
real store.

The model files are loaded lazily on first :meth:`embed` — construction and
:attr:`dimensions` stay offline, resolved from ``fastembed``'s model metadata.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastembed import TextEmbedding

from ai_assistant.core.errors import ModelError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import Embedding

_DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


class FastEmbedEmbedder:
    """A local, on-device embedder backed by fastembed."""

    def __init__(self, *, model: str = _DEFAULT_MODEL) -> None:
        """Initialise the embedder without loading the model.

        Args:
            model: A fastembed model name. Its dimension is resolved from
                fastembed's offline metadata.

        Raises:
            ModelError: If ``model`` is not a supported fastembed model.
        """
        supported = {m["model"]: m["dim"] for m in TextEmbedding.list_supported_models()}
        dimensions = supported.get(model)
        if dimensions is None:
            msg = f"unknown fastembed model: {model!r}"
            raise ModelError(msg)
        self._model_name = model
        self._dimensions = int(dimensions)
        self._model: TextEmbedding | None = None

    @property
    def dimensions(self) -> int:
        """The fixed length of the vectors this embedder produces."""
        return self._dimensions

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        """Embed a batch of texts, returning one vector per input, in order.

        The model is loaded on first use; the embedding itself runs in a worker
        thread so it does not block the event loop.
        """
        documents = list(texts)
        if not documents:
            return []
        return await asyncio.to_thread(self._embed_sync, documents)

    def _embed_sync(self, documents: list[str]) -> list[Embedding]:
        if self._model is None:
            self._model = TextEmbedding(model_name=self._model_name)
        return [[float(value) for value in vector] for vector in self._model.embed(documents)]
