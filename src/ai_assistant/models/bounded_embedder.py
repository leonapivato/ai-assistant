"""A deadline over any :class:`~ai_assistant.core.protocols.Embedder` (ADR-0118 §2).

:class:`BoundedEmbedder` *wraps* another embedder rather than extending one: it
implements ``Embedder``, delegates :attr:`~BoundedEmbedder.model_id` and
:attr:`~BoundedEmbedder.dimensions` unchanged, and bounds :meth:`embed`. That is
:class:`~ai_assistant.models.retry.RetryingProvider`'s shape, chosen here for the
reason that transfers unchanged from ``models/retry.py``: resilience "composes
with any implementation … without either side knowing about the other".

**Why the deadline is here and not in an adapter or a store.** ADR-0118 §2
enumerates and refuses the three alternatives. Inside ``FastEmbedEmbedder`` it
would bind one of two shipped implementations and re-open the hole for the next
one. At the ``MemoryStore`` seam it would bound one store's callers rather than
the seam, miss ``Reembedder``, and make a store the owner of a deadline over a
collaborator whose cost profile it cannot know. At a scheduled job's boundary it
would fire mid-chunk, which ADR-0111 §4's first clause forbids outright. Bounding
the *seam* means every caller — the store's writes, the store's ``search``, the
offline migration — is bounded by one object, and a future ``Embedder`` is bounded
on the day it is wired rather than on the day someone remembers.

**One attempt, no retry, no backoff** (ADR-0118 §3). ``RetryingProvider`` retries
because a remote provider fails transiently; an on-device ONNX runtime does not.
Against a wedged backend each retry would abandon another worker, so a retry
policy multiplies the blast radius of the one failure mode the deadline exists to
survive.

**The deadline stops the caller waiting; it does not stop the work** (ADR-0118 §7,
ADR-0029 §4, ADR-0060 §1). A deadline expressed as ``asyncio.timeout`` fires only
where the awaiting task suspends, and it cannot interrupt synchronous work. So the
containment of an abandoned worker is *not* this class's obligation and cannot be:
by the time the deadline fires, the inner implementation has already submitted its
work somewhere this decorator cannot reach. ADR-0118 §7's third clause states that
in terms, and ``ai_assistant.models._embed_worker`` is where the dispatching
implementation discharges it.

Against an inner ``embed`` that reaches no ``await`` — ``HashingEmbedder`` is the
case — the deadline is inert, and nothing is lost: that implementation is bounded
by construction under ADR-0118 §1, being local work linear in its input that waits
on nothing which can wedge.
"""

from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING

from ai_assistant.core.errors import ConfigurationError, EmbeddingDeadlineExpiredError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import Embedder
    from ai_assistant.core.types import Embedding

#: The deadline a :class:`BoundedEmbedder` applies when none is supplied — the same
#: figure :attr:`Settings.embedding_timeout_seconds` defaults to, so a construction
#: that names no deadline is bounded the way a default deployment is rather than
#: not at all.
DEFAULT_TIMEOUT_SECONDS = 30.0


class BoundedEmbedder:
    """An ``Embedder`` that bounds every ``embed`` call with a deadline.

    Structurally implements
    :class:`~ai_assistant.core.protocols.Embedder`, so it stands in for the
    embedder it wraps anywhere the contract is expected.
    """

    def __init__(
        self, inner: Embedder, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        """Wrap ``inner`` with a per-call deadline.

        Args:
            inner: The embedder to delegate to.
            timeout_seconds: The deadline over one whole ``embed`` call, including
                any lazy model load the inner implementation performs inside it
                (ADR-0118 §4).

        Raises:
            ConfigurationError: If ``timeout_seconds`` is not a finite, strictly
                positive real number. ``Settings`` already refuses all three at
                load; this is the constructor's own guard on the seam a caller can
                reach directly, in :class:`~ai_assistant.models.retry.RetryPolicy`'s
                shape and for its reasons — a non-finite deadline makes
                ``asyncio.timeout`` behave unpredictably, and ``bool`` is excluded
                because ``True`` would otherwise be coerced into a one-second
                deadline that fails every cold model load.
        """
        # Type before value: `math.isfinite("30")` raises TypeError, which would
        # escape as a builtin and contradict the ConfigurationError documented here.
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool):
            msg = (
                f"timeout_seconds must be a real number, got "
                f"{type(timeout_seconds).__name__} ({timeout_seconds!r})"
            )
            raise ConfigurationError(msg)
        if not math.isfinite(timeout_seconds):
            msg = f"timeout_seconds must be a finite number, got {timeout_seconds}"
            raise ConfigurationError(msg)
        if timeout_seconds <= 0:
            msg = f"timeout_seconds must be positive, got {timeout_seconds}"
            raise ConfigurationError(msg)
        self._inner = inner
        self._timeout_seconds = float(timeout_seconds)

    @classmethod
    def from_settings(cls, inner: Embedder, settings: Settings) -> BoundedEmbedder:
        """Wrap ``inner`` with the deadline this deployment configured.

        The mapping lives here so ``embedding_timeout_seconds`` has exactly one
        interpretation, the way
        :meth:`~ai_assistant.models.retry.RetryPolicy.from_settings` gives the model
        knobs one.

        Args:
            inner: The embedder to delegate to.
            settings: Loaded application settings.

        Returns:
            The bounded embedder those settings describe.
        """
        return cls(inner, timeout_seconds=settings.embedding_timeout_seconds)

    @property
    def model_id(self) -> str:
        """The inner embedder's identity, delegated unchanged.

        A deadline is not an embedding space. Rewriting this would move every
        stored vector's tag and make the store disown its own vectors (ADR-0006 §4,
        ADR-0024 §2), which is why ADR-0118 §10 records that nothing here obligates
        either ADR.
        """
        return self._inner.model_id

    @property
    def dimensions(self) -> int:
        """The inner embedder's vector width, delegated unchanged."""
        return self._inner.dimensions

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        """Embed a batch through the inner embedder, under this seam's deadline.

        Exactly one attempt. An expired call is not retried and no backoff is
        applied (ADR-0118 §3).

        Args:
            texts: The batch to embed.

        Returns:
            One vector per input, in order — whatever the inner embedder returned.

        Raises:
            EmbeddingDeadlineExpiredError: If the call outlived the deadline. The
                worker the inner implementation started is **not** known to have
                stopped: the deadline ends the wait, not the work (ADR-0118 §7).
            Exception: Whatever the inner embedder raised, unwrapped — including a
                ``TimeoutError`` of its own. Its faults are its own vocabulary and
                this seam has nothing to add to them; re-labelling a missing model
                artifact, or a backend's own timeout, as *this* deadline expiring
                would send an operator to the wrong remedy and would destroy the
                very distinction ADR-0118 §5 exists to make.
        """
        # Bound before the `try` so the `except` arm can consult it: a
        # `TimeoutError` is only ours if this deadline actually expired.
        deadline = asyncio.timeout(self._timeout_seconds)
        cause: TimeoutError | None = None
        try:
            async with deadline:
                vectors = await self._inner.embed(texts)
            # Expiry does not always surface as an exception, and the corpus has
            # already paid for assuming it does (`models/retry.py`). `asyncio`
            # abandons a call by *cancelling* it, and an inner embedder that
            # swallows that CancelledError can still return normally — in which
            # case the context manager exits quietly and hands back vectors
            # produced after the deadline had already passed. Asking the deadline
            # whether it expired is the only way to notice.
            if not deadline.expired():
                return vectors
        except TimeoutError as exc:
            # Two different failures arrive as `TimeoutError` and conflating them
            # produces a false report, which is exactly what `models/retry.py`
            # records for the neighbouring seam: an inner `TimeoutError` raised
            # instantly would be re-labelled "did not complete within its 30s
            # deadline", with the backend's own message discarded. `retry.py` tells
            # them apart by *where* they are caught; here the deadline can be asked
            # directly, which is stronger — it stays right even for an inner
            # embedder whose `TimeoutError` arrives after our own expiry has been
            # scheduled but before it fires.
            #
            # An outer cancellation never reaches this arm at all: `asyncio.timeout`
            # leaves a cancellation it did not cause alone, which is what
            # `core/protocols.py`'s cancellation clause requires (ADR-0060 §1).
            if not deadline.expired():
                raise
            cause = exc
        msg = f"the embedding did not complete within its {self._timeout_seconds:g}s deadline"
        raise EmbeddingDeadlineExpiredError(msg) from cause
