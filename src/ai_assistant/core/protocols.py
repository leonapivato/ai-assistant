"""The contracts (Protocols) each subsystem implements.

This is the most important file for parallel, agent-driven development. Every
subsystem is defined here as a ``typing.Protocol`` — a structural interface with
no implementation. The `orchestration` engine depends only on these Protocols,
so a concrete implementation of any one subsystem can be written, reviewed,
swapped, or mocked in tests without touching the others.

Guidelines when evolving these contracts:
  * A Protocol change is a breaking change — call it out in review and record
    the decision in ``docs/adr/`` before implementing against it.
  * Prefer adding a new Protocol over widening an existing one.
  * Keep methods ``async`` where they touch I/O (models, memory, tools) so the
    whole system composes on one event loop.

Only two exemplar contracts are defined for now (``ModelProvider`` and
``MemoryStore``). The remaining subsystems declared in the architecture add
their Protocols here as they are designed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import (
        Embedding,
        MemoryDecision,
        MemoryKind,
        MemoryRecord,
        MemoryUpdateProposal,
        Message,
    )


@runtime_checkable
class ModelProvider(Protocol):
    """A model-agnostic language-model client.

    Concrete implementations (in `models`) wrap pydantic-ai so the rest of the
    system never imports a provider SDK directly. This is the seam that makes
    the assistant model-agnostic.
    """

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Message:
        """Produce the assistant's next message given the conversation so far.

        Args:
            messages: Conversation history, oldest first.
            model: Optional ``"provider:model"`` override; falls back to the
                configured default when ``None``.

        Returns:
            The assistant's reply as a :class:`~ai_assistant.core.types.Message`.
        """
        ...


@runtime_checkable
class Embedder(Protocol):
    """Turns text into dense vectors for semantic retrieval (see ADR-0006).

    A model-agnostic embedding seam, separate from :class:`ModelProvider`
    because embedding is a distinct capability a provider may not offer.

    An embedder is bound to a single model. Per-call model selection is
    intentionally omitted: vectors from different models are not comparable, so
    a store must embed everything with one model (ADR-0006 §4).
    """

    @property
    def model_id(self) -> str:
        """A stable identifier for the embedding model.

        Vectors are tagged with this so a store can detect that it was built
        with a different model and must be re-embedded (ADR-0006 §4).
        """
        ...

    @property
    def dimensions(self) -> int:
        """The fixed length of the vectors this embedder produces."""
        ...

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        """Embed a batch of texts, returning one vector per input, in order."""
        ...


@runtime_checkable
class MemoryStore(Protocol):
    """Persistent long-term memory with semantic retrieval.

    Records carry an optional ``expires_at`` retention deadline. A record past
    that deadline is treated as already forgotten: ``get`` and ``search`` never
    return it, whether or not ``purge_expired`` has reclaimed it yet (ADR-0007).
    """

    async def add(self, record: MemoryRecord) -> str:
        """Persist a record and return its id."""
        ...

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Return the record with ``record_id``, or ``None`` if absent or expired."""
        ...

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
    ) -> list[MemoryRecord]:
        """Return the records most relevant to ``query``, best first.

        Expired records are never returned.

        Args:
            query: The search text.
            limit: Maximum number of records to return.
            kinds: If given, restrict results to these memory kinds.
        """
        ...

    async def delete(self, record_id: str) -> bool:
        """Delete one record.

        Args:
            record_id: The id of the record to remove.

        Returns:
            ``True`` if a record was removed, ``False`` if none had that id.
        """
        ...

    async def clear(self) -> int:
        """Delete every record in this store, returning the number removed.

        This empties the store's own (Tier 1) rows only; it is not a
        whole-system erase (ADR-0007 §4).
        """
        ...

    async def export(self) -> list[MemoryRecord]:
        """Return a portable snapshot of all live (non-expired) records.

        The caller serialises the records to JSON (e.g. ``model_dump(mode="json")``);
        the snapshot excludes expired records and carries no embeddings (ADR-0007 §3).
        """
        ...

    async def purge_expired(self) -> int:
        """Physically remove records past their ``expires_at``.

        Returns:
            The number of expired records removed. Read methods already hide
            expired records, so this changes reclaimed space, not visibility.
        """
        ...


@runtime_checkable
class MemoryPolicy(Protocol):
    """Decides the fate of a proposed memory update — the "dispose" half.

    The model *proposes* memories; a deterministic policy implementing this
    Protocol *disposes* of them, so writes to long-term memory are reviewable
    and bounded rather than an unmediated side effect of generation.
    """

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
    ) -> MemoryDecision:
        """Rule on a proposed memory update.

        Args:
            proposal: The candidate memory and why it was proposed.
            conflicts: Existing records the proposal contradicts, already
                resolved from the store (the proposal carries their ids).

        Returns:
            The decision to accept, reject, merge, defer to the user, or store
            the proposal temporarily.
        """
        ...
