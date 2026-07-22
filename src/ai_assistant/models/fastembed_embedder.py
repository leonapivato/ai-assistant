"""The on-device default :class:`~ai_assistant.core.protocols.Embedder` (ADR-0006).

``FastEmbedEmbedder`` runs a local embedding model via ``fastembed``, so memory
content is never sent off-device merely to be indexed. This module is the only
place ``fastembed`` is imported; it is intentionally *not* re-exported from
``ai_assistant.models`` so importing that package stays cheap (importing
``fastembed`` pulls in ONNX runtime). Import this class directly when wiring the
real store.

The model is the **vendored** artifact ADR-0024 makes a build input: packaged
inside this distribution, loaded from that path with ``local_files_only=True``,
and pinned to the CPU execution provider. Nothing here fetches anything, and
there is no arbitrary-model path (ADR-0024 §6) — this class serves the one
verified model and rejects any other name before it touches a backend.

:attr:`model_id` is not the bare model name. It is the embedding-space identity
of ADR-0024 §2: the name, a digest over the shipped bytes, and a digest over the
audited behaviour-affecting versions, so a store detects re-pinned weights or an
upgraded stack as "re-embedding is required" (ADR-0006 §4) instead of ranking old
vectors against new queries.

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
import math
import threading
from typing import TYPE_CHECKING, Protocol

from fastembed import TextEmbedding

from ai_assistant.core.errors import ModelError
from ai_assistant.models.embedding_artifact import (
    EXECUTION_PROVIDERS,
    VENDORED_MODEL_NAME,
    ArtifactError,
    embedding_space_id,
    missing_files,
    packaged_artifact_dir,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from ai_assistant.core.types import Embedding


class _ContractViolationError(Exception):
    """Internal signal: the backend's result breaks the ``Embedder`` contract.

    Never escapes this module. It exists to keep two failures distinguishable
    inside one incremental loop that consumes the backend's output: an exception
    *from* the backend becomes "failed to embed", while a result that is merely
    wrong becomes its own specific ``ModelError``. Both surface to the caller as
    ``ModelError``; only the message differs.
    """


class FastEmbedTextModel(Protocol):
    """A loaded embedding model: the half of the seam that does the work.

    ``embed`` **must be safe to call concurrently from multiple threads.**
    :meth:`FastEmbedEmbedder.embed` dispatches to a worker thread, so two
    in-flight calls reach one loaded model at once; an implementation that
    reused a mutable inference buffer across calls would cross-contaminate
    their vectors. The real backend satisfies this — ONNX Runtime's
    ``InferenceSession.run`` is thread-safe — and the requirement is stated
    here so an alternative backend cannot quietly fail to.

    The embedder deliberately does not serialise inference on the caller's
    behalf: a lock here would cap embedding throughput at one thread for every
    backend, to accommodate a backend we do not have.
    """

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
        """Load a model by name from files already present on this machine."""
        ...


class _FastEmbedBackend:
    """The real backend: ``fastembed``'s ``TextEmbedding``, pointed at the vendored files."""

    def dimensions_by_model(self) -> Mapping[str, int]:
        """The vector dimension of every model ``fastembed`` supports."""
        return {
            str(model["model"]): int(model["dim"])
            for model in TextEmbedding.list_supported_models()
        }

    def load(self, model: str) -> FastEmbedTextModel:
        """Load the vendored model from the packaged artifact, offline.

        ``specific_model_path`` short-circuits ``fastembed``'s download path
        entirely, and ``local_files_only=True`` is belt to that braces. The
        artifact's presence is checked here first so an incomplete install fails
        with a message naming the cause rather than as an ONNX Runtime error
        about a file that is not there.

        Args:
            model: The model name; always the vendored one, enforced upstream.

        Returns:
            The loaded fastembed model.

        Raises:
            ModelError: If the packaged artifact is missing or incomplete.
        """
        directory = packaged_artifact_dir()
        absent = missing_files(directory)
        if absent:
            msg = (
                f"the packaged embedding model artifact is missing from {directory} "
                f"({', '.join(absent)}); it is a build input (ADR-0024) and is never "
                f"downloaded at runtime, so this installation is incomplete"
            )
            raise ModelError(msg)
        return TextEmbedding(
            model_name=model,
            specific_model_path=str(directory),
            local_files_only=True,
            providers=list(EXECUTION_PROVIDERS),
            cuda=False,
        )


def _resolve_dimensions(backend: FastEmbedBackend, model: str) -> int:
    """The vector width the backend reports for ``model``.

    Every way the metadata can be malformed is translated here, because the
    constructor promises ``ModelError`` and a caller's ``except ModelError``
    has to be sufficient. Reading the mapping is inside the boundary, not just
    the call that produced it: a lazy or hostile mapping can raise from
    ``get`` just as easily as from ``dimensions_by_model``, and a non-numeric
    dimension would otherwise surface as a ``TypeError`` from the comparison.

    Raises:
        ModelError: If the metadata cannot be read, ``model`` is absent from
            it, or its dimension is not a positive number.
    """
    try:
        reported = backend.dimensions_by_model().get(model)
    except Exception as exc:
        msg = "fastembed could not report its supported models"
        raise ModelError(msg) from exc
    if reported is None:
        msg = f"unknown fastembed model: {model!r}"
        raise ModelError(msg)
    # Require an actual int rather than coercing with `int()`, which is wrong in
    # both directions here: `int(1.5)` would silently accept a fractional width
    # as 1, and `int(float("inf"))` raises OverflowError straight past this
    # boundary. `bool` is excluded because `True` would otherwise pass as a
    # one-dimensional model. The Protocol already declares `Mapping[str, int]`,
    # so this only enforces what a backend has promised.
    if isinstance(reported, bool) or not isinstance(reported, int):
        msg = f"fastembed reported a non-integer dimension for {model!r}: {reported!r}"
        raise ModelError(msg)
    if reported < 1:
        msg = f"fastembed model {model!r} reports a non-positive dimension: {reported}"
        raise ModelError(msg)
    return reported


class FastEmbedEmbedder:
    """A local, on-device embedder backed by fastembed."""

    def __init__(
        self, *, model: str = VENDORED_MODEL_NAME, backend: FastEmbedBackend | None = None
    ) -> None:
        """Initialise the embedder without loading the model.

        Args:
            model: Must be the vendored model name. The parameter exists so a
                mistaken name fails loudly rather than being ignored; it is not
                a selection point.
            backend: The fastembed surface to run against. Defaults to the real
                ``fastembed``; a test may inject a deterministic offline stub to
                exercise this adapter without loading ONNX (see the module
                docstring).

        Raises:
            ModelError: If ``model`` is not the vendored model, if the backend
                cannot report its supported models or reports them malformed, if
                ``model`` is absent from them, or if the reported dimension is
                not a positive number — a vector length of zero or less cannot
                satisfy the ``Embedder`` contract, and accepting it would defer
                the failure to the store that sized its vector column from it.
        """
        # First, and before `backend` is even resolved: ADR-0024 §6 requires a
        # non-vendored name to be refused ahead of any backend load or socket,
        # because fastembed's own download path is exactly what that name would
        # re-enable — unpinned, unverified, and unidentifiable in `model_id`.
        if model != VENDORED_MODEL_NAME:
            msg = (
                f"FastEmbedEmbedder serves only the vendored model "
                f"{VENDORED_MODEL_NAME!r}, not {model!r}: the embedding model is a "
                f"build input (ADR-0024), so there is no arbitrary-model path"
            )
            raise ModelError(msg)
        self._backend = _FastEmbedBackend() if backend is None else backend
        self._model_name = model
        self._model_id = self._resolved_model_id()
        self._dimensions = _resolve_dimensions(self._backend, model)
        self._model: FastEmbedTextModel | None = None
        # Guards the lazy load only. Without it two concurrent `embed` calls —
        # each in its own worker thread — can both see `_model is None` and
        # download/load the model twice.
        self._load_lock = threading.Lock()

    @staticmethod
    def _resolved_model_id() -> str:
        """The embedding-space identity, or a ``ModelError`` explaining why not.

        Raises:
            ModelError: If the audited stack cannot be identified — which means
                the identity would be a lie, and a store tagging vectors with a
                lie is the corruption ADR-0024 §2 exists to prevent.
        """
        try:
            return embedding_space_id()
        except ArtifactError as exc:
            msg = f"could not determine the embedding space identity: {exc}"
            raise ModelError(msg) from exc

    @property
    def model_id(self) -> str:
        """The identity of the embedding space: model, shipped bytes, audited stack.

        Not the bare model name. Re-pinned weights or a bumped audited version
        move this, so a store detects that its vectors are stale (ADR-0024 §2).
        """
        return self._model_id

    @property
    def dimensions(self) -> int:
        """The fixed length of the vectors this embedder produces."""
        return self._dimensions

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        """Embed a batch of texts, returning one vector per input, in order.

        The model is loaded on first use; the embedding itself runs in a worker
        thread so it does not block the event loop.

        **An empty batch is answered before anything else** — before the
        packaged artifact is even looked for. ADR-0024 §5 requires that order:
        ``embed([])`` returns ``[]`` and stays offline whatever the state of the
        installation, so a store that indexes nothing is not made to fail by an
        artifact it never needed.

        Raises:
            ModelError: If the packaged artifact is missing or the model cannot
                otherwise be loaded, the backend fails to embed the batch, or it
                returns a result that does not satisfy the ``Embedder`` contract.
                Never by fetching and failing: nothing here reaches the network.
        """
        documents = list(texts)
        if not documents:
            return []
        return await asyncio.to_thread(self._embed_sync, documents)

    def _embed_sync(self, documents: list[str]) -> list[Embedding]:
        # `_loaded` sits outside the try so its own ModelError passes through
        # rather than being re-wrapped into a misleading "failed to embed".
        model = self._loaded()
        try:
            return self._collected(model, documents)
        except _ContractViolationError as violation:
            # Already the precise message; re-wrapping it as "failed to embed"
            # would describe a backend that raised, which this one did not.
            raise ModelError(str(violation)) from None
        except Exception as exc:
            msg = f"fastembed failed to embed a batch of {len(documents)} text(s)"
            raise ModelError(msg) from exc

    def _collected(self, model: FastEmbedTextModel, documents: list[str]) -> list[Embedding]:
        """Consume the backend's result, checking the ``Embedder`` contract as it goes.

        This adapter, not the backend, is what promises the contract. A count
        mismatch is the dangerous one: the caller zips these vectors against its
        own records, so a short batch silently files every record after the gap
        under another record's vector. A wrong dimension corrupts the store's
        vector column, and a non-finite component poisons every later similarity
        (inf/inf is NaN, and a NaN distance makes a record unrankable).

        None of these is reachable today; all three become reachable the moment
        fastembed changes behaviour under us, which is exactly when a silent
        wrong answer costs the most.

        The checking is **incremental, and that is the point**: the result is
        never fully materialised first. A backend handing back an unbounded
        iterator of vectors would otherwise hang this worker thread and grow
        memory without limit instead of raising. Consuming at most one item past
        what the contract allows — one extra vector, one extra component —
        bounds a hostile or broken injected backend to a rejection.

        Raises:
            _ContractViolationError: If the result breaks the contract.
        """
        expected_count = len(documents)
        vectors: list[Embedding] = []
        for vector in model.embed(documents):
            if len(vectors) == expected_count:
                msg = (
                    f"fastembed returned more than {expected_count} vectors "
                    f"for {expected_count} text(s)"
                )
                raise _ContractViolationError(msg)
            vectors.append(self._checked_vector(vector, len(vectors)))
        if len(vectors) != expected_count:
            msg = f"fastembed returned {len(vectors)} vectors for {expected_count} text(s)"
            raise _ContractViolationError(msg)
        return vectors

    def _checked_vector(self, vector: Iterable[float], index: int) -> Embedding:
        """One vector, coerced to floats and checked against the declared shape.

        Components are checked as they arrive for the same reason vectors are: a
        single vector backed by an unbounded component iterator is as effective a
        denial of service as an unbounded batch.

        Raises:
            _ContractViolationError: If the vector is the wrong width or holds a
                non-finite component.
        """
        values: list[float] = []
        for value in vector:
            if len(values) == self._dimensions:
                msg = (
                    f"fastembed returned a vector with more than {self._dimensions} "
                    f"components at index {index}, expected {self._dimensions}"
                )
                raise _ContractViolationError(msg)
            number = float(value)
            if not math.isfinite(number):
                msg = f"fastembed returned a non-finite component in the vector at index {index}"
                raise _ContractViolationError(msg)
            values.append(number)
        if len(values) != self._dimensions:
            msg = (
                f"fastembed returned a {len(values)}-dimensional vector at index {index}, "
                f"expected {self._dimensions}"
            )
            raise _ContractViolationError(msg)
        return values

    def _loaded(self) -> FastEmbedTextModel:
        """The model, loading it on first use and reusing it after."""
        with self._load_lock:
            if self._model is None:
                try:
                    self._model = self._backend.load(self._model_name)
                except ModelError:
                    # Already precise — "the packaged artifact is missing" names
                    # the cause, which ADR-0024 §5 requires; re-wrapping it as
                    # "could not load model" would bury it in `__cause__`.
                    raise
                except Exception as exc:
                    msg = f"fastembed could not load model {self._model_name!r}"
                    raise ModelError(msg) from exc
            return self._model
