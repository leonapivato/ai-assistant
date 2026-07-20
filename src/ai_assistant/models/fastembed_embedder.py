"""The on-device default :class:`~ai_assistant.core.protocols.Embedder` (ADR-0006).

``FastEmbedEmbedder`` runs a local embedding model via ``fastembed``, so memory
content is never sent off-device merely to be indexed. This module is the only
place ``fastembed`` is imported; it is intentionally *not* re-exported from
``ai_assistant.models`` so importing that package stays cheap (importing
``fastembed`` pulls in ONNX runtime). Import this class directly when wiring the
real store.

The model files are loaded lazily on first :meth:`embed` — construction and
:attr:`dimensions` stay offline, resolved from ``fastembed``'s model metadata.

## The backend seam

``fastembed`` reaches this class through one narrow seam, :class:`FastEmbedBackend`,
and the real one (:class:`_FastEmbedBackend`) is the default — production
construction is unchanged and still runs the real model. The seam exists so the
*adapter* layer above it — one vector per input in batch order, the declared
shape, the float conversion, the load-once-and-reuse of a model — can run the
shared ``EmbedderContract`` against a deterministic offline stub in the default
gate, which it otherwise could not: ``embed`` downloads a model on first use and
the gate runs with no network.

The seam is drawn at ``fastembed``'s boundary rather than by patching
``TextEmbedding`` out, because patching would assert properties of the patch
instead of properties of this adapter. What the stub covers is exactly the code
in this module; ``fastembed`` itself stays out of the gate, as it must.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Protocol

from fastembed import TextEmbedding

from ai_assistant.core.errors import ModelError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from ai_assistant.core.types import Embedding

_DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


class FastEmbedTextModel(Protocol):
    """A loaded embedding model: the half of the seam that does the work."""

    def embed(self, documents: list[str]) -> Iterable[Iterable[float]]:
        """Embed the documents, yielding one vector per document, in order."""
        ...


class FastEmbedBackend(Protocol):
    """The whole of ``fastembed`` that :class:`FastEmbedEmbedder` depends on.

    Two calls, split the way ``fastembed`` itself splits: metadata is available
    offline, loading a model is not. Keeping them apart is what lets construction
    and :attr:`FastEmbedEmbedder.dimensions` stay offline.
    """

    def dimensions_by_model(self) -> Mapping[str, int]:
        """The vector dimension of every supported model, resolved offline."""
        ...

    def load(self, model: str) -> FastEmbedTextModel:
        """Load a model by name, downloading it if it is not already cached."""
        ...


class _FastEmbedBackend:
    """The real backend: ``fastembed``'s ``TextEmbedding``."""

    def dimensions_by_model(self) -> Mapping[str, int]:
        """The vector dimension of every model ``fastembed`` supports."""
        return {
            str(model["model"]): int(model["dim"])
            for model in TextEmbedding.list_supported_models()
        }

    def load(self, model: str) -> FastEmbedTextModel:
        """Load the named model, downloading it on first use."""
        return TextEmbedding(model_name=model)


class FastEmbedEmbedder:
    """A local, on-device embedder backed by fastembed."""

    def __init__(
        self, *, model: str = _DEFAULT_MODEL, backend: FastEmbedBackend | None = None
    ) -> None:
        """Initialise the embedder without loading the model.

        Args:
            model: A fastembed model name. Its dimension is resolved from
                fastembed's offline metadata.
            backend: The fastembed surface to run against. Defaults to the real
                ``fastembed``; a test may inject a deterministic offline stub to
                exercise this adapter without a model download (see the module
                docstring).

        Raises:
            ModelError: If ``model`` is not a model the backend supports, or the
                backend reports a non-positive dimension for it — a vector length
                of zero or less cannot satisfy the ``Embedder`` contract, and
                accepting it would defer the failure to the store that sized its
                vector column from it.
        """
        self._backend = _FastEmbedBackend() if backend is None else backend
        dimensions = self._backend.dimensions_by_model().get(model)
        if dimensions is None:
            msg = f"unknown fastembed model: {model!r}"
            raise ModelError(msg)
        if dimensions < 1:
            msg = f"fastembed model {model!r} reports a non-positive dimension: {dimensions}"
            raise ModelError(msg)
        self._model_name = model
        self._dimensions = int(dimensions)
        self._model: FastEmbedTextModel | None = None
        # Guards the lazy load only. Without it two concurrent `embed` calls —
        # each in its own worker thread — can both see `_model is None` and
        # download/load the model twice.
        self._load_lock = threading.Lock()

    @property
    def model_id(self) -> str:
        """The fastembed model name, identifying the embedding space."""
        return self._model_name

    @property
    def dimensions(self) -> int:
        """The fixed length of the vectors this embedder produces."""
        return self._dimensions

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        """Embed a batch of texts, returning one vector per input, in order.

        The model is loaded on first use; the embedding itself runs in a worker
        thread so it does not block the event loop. An empty batch is answered
        without loading anything.
        """
        documents = list(texts)
        if not documents:
            return []
        return await asyncio.to_thread(self._embed_sync, documents)

    def _embed_sync(self, documents: list[str]) -> list[Embedding]:
        return [[float(value) for value in vector] for vector in self._loaded().embed(documents)]

    def _loaded(self) -> FastEmbedTextModel:
        """The model, loading it on first use and reusing it after."""
        with self._load_lock:
            if self._model is None:
                self._model = self._backend.load(self._model_name)
            return self._model
