"""Two helpers ``test_engine_attempts.py`` imports; the tests that lived here are retired.

ADR-0309 §2:6 makes the phases the only path, and every test this module held drove
the old one, so they went ahead of the switch (M43, batch #2816). What is left is
only what a surviving module still imports. When nothing does, this file goes.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ai_assistant.core.errors import ModelUnavailableError
from ai_assistant.core.types import Message, Role

if TYPE_CHECKING:
    from collections.abc import Sequence

_ANSWER = "You prefer hiking, and I have not sent anything."


def _refusing(_messages: Sequence[Message]) -> str:
    """A provider whose call raises a ``ModelError`` — §8's first closed-set member."""
    msg = "the route is exhausted"
    raise ModelUnavailableError(msg)


class _GatedProvider:
    """A ``ModelProvider`` whose completion blocks until it is released.

    Structurally implements
    :class:`~ai_assistant.core.protocols.ModelProvider`. The canonical fake answers
    synchronously, which is what makes it useless for asking whether anything is
    *waiting* on the answer.
    """

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        """Announce that composition has begun, then wait to be let go."""
        del messages, model
        self.entered.set()
        await self.release.wait()
        return Message(role=Role.ASSISTANT, content=_ANSWER)
