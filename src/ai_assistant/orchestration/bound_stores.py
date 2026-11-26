"""The holder that binds stores for a pass (ADR-0383 §9:1).

A work's stages are built once by the composition root and reused by every activation,
so no stage can hold a store bound once at construction: the sight is a work's, and a
work is one activation. Each converted stage holds :class:`BoundStores` instead, and asks
it for a store **only for a sight** — the sight its pass carries
(:attr:`~ai_assistant.orchestration.activation_state.ActivationState.sight`), which no
stage makes or changes (§9:2). What comes back is the store's own
:meth:`~ai_assistant.core.protocols.MemoryStore.bound`: whether it withholds or only
counts is the store's construction (§7:10), so the holder reads no setting and takes no
mode.

:data:`Bound` marks a parameter that takes a store the holder gave: a function handed one
per call holds nothing between passes, and the named test of §9:1
(``tests/orchestration/test_no_unbound_store.py``) reads the mark as "bound", where every
other annotation naming one of the store Protocols is a holder of an unbound one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_assistant.core.protocols import (
        ConversationStore,
        MemoryStore,
        MemoryWriter,
        PersonModelStore,
        PlanStore,
        StoryStore,
    )
    from ai_assistant.core.types import Sight

__all__ = ["Bound", "BoundStores"]

#: A store a stage was handed by :class:`BoundStores` for its pass's sight (§9:1). The
#: type is the store's own Protocol: the mark is for the named test, which reads it.
type Bound[S] = S


class BoundStores:
    """The unbound stores, each given out only bound to a sight (ADR-0383 §7:1, §9:1).

    One per process, built by the composition root over the very stores every other
    reader holds, and handed to each stage converted to read through it. It holds no
    sight and no mode: each call binds anew, so one holder serves every pass at once.
    """

    def __init__(  # noqa: PLR0913 — one keyword per store §7:1 binds, and the writer
        self,
        *,
        memory: MemoryStore,
        stories: StoryStore | None = None,
        people: PersonModelStore | None = None,
        conversations: ConversationStore | None = None,
        plans: PlanStore | None = None,
        writer: MemoryWriter | None = None,
    ) -> None:
        """Hold the stores a converted stage reads, and the writer a producer writes by.

        Each but the memory store is optional, for a holder built where that store is
        not wired; asking such a holder for it is a wiring defect, and raises.

        Args:
            memory: The memory store.
            stories: The story store.
            people: The person-model store, where the person model is wired.
            conversations: The conversation store.
            plans: The plan store.
            writer: The memory write path, persisting to ``memory`` (ADR-0028 §4).
        """
        self._memory = memory
        self._stories = stories
        self._people = people
        self._conversations = conversations
        self._plans = plans
        self._writer = writer

    def memory(self, sight: Sight) -> Bound[MemoryStore]:
        """The memory store, bound to ``sight``."""
        return self._memory.bound(sight)

    def stories(self, sight: Sight) -> Bound[StoryStore]:
        """The story store, bound to ``sight``.

        Raises:
            RuntimeError: If no story store is wired to this holder.
        """
        return _wired(self._stories, "story").bound(sight)

    def people(self, sight: Sight) -> Bound[PersonModelStore]:
        """The person-model store, bound to ``sight``.

        Raises:
            RuntimeError: If no person-model store is wired to this holder.
        """
        return _wired(self._people, "person-model").bound(sight)

    def conversations(self, sight: Sight) -> Bound[ConversationStore]:
        """The conversation store, bound to ``sight``.

        Raises:
            RuntimeError: If no conversation store is wired to this holder.
        """
        return _wired(self._conversations, "conversation").bound(sight)

    def plans(self, sight: Sight) -> Bound[PlanStore]:
        """The plan store, bound to ``sight``.

        Raises:
            RuntimeError: If no plan store is wired to this holder.
        """
        return _wired(self._plans, "plan").bound(sight)

    def writer(self, sight: Sight) -> Bound[MemoryWriter]:
        """The memory write path, bound to ``sight`` (ADR-0383 §7:1, §7:6).

        Every read it makes for a write, its conflict search and its fetch of a placed
        proposal's memories included, is of the memory store bound to the same sight.

        Raises:
            RuntimeError: If no writer is wired to this holder.
        """
        return _wired(self._writer, "memory writer").bound(sight)


def _wired[S](store: S | None, name: str) -> S:
    """``store``, where one is wired; a stage asking for one that is not is a defect."""
    if store is None:
        msg = f"no {name} store is wired to the holder that binds stores for a pass"
        raise RuntimeError(msg)
    return store
