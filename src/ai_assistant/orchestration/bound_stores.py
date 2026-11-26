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
    from ai_assistant.core.protocols import MemoryStore, StoryStore
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

    def __init__(self, *, memory: MemoryStore, stories: StoryStore) -> None:
        """Hold the stores a converted stage reads.

        Args:
            memory: The memory store.
            stories: The story store.
        """
        self._memory = memory
        self._stories = stories

    def memory(self, sight: Sight) -> Bound[MemoryStore]:
        """The memory store, bound to ``sight``."""
        return self._memory.bound(sight)

    def stories(self, sight: Sight) -> Bound[StoryStore]:
        """The story store, bound to ``sight``."""
        return self._stories.bound(sight)
