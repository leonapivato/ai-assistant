"""A work's sight, as admission makes it, for the cases that read through one (ADR-0383 §6).

A case that drives a stage or a reader without the engine reads by the sight the engine's
admission would have made for its work: :func:`admitted` admits a hub chat message from
the senders named, as the chat's reader's input is admitted (``admit_channel``), so the
sight is made where §9:2 says it is, and never by the case.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ChannelInput,
    InputSender,
    NewConversation,
    Sureness,
    TextChannelPayload,
    WholeTextReply,
)
from ai_assistant.orchestration.activation_state import (
    CURRENT_ACTIVATION,
    ActivationScope,
    admit_channel,
)
from ai_assistant.orchestration.bound_stores import BoundStores
from ai_assistant.testing.memory import FakeMemoryStore
from ai_assistant.testing.parties import OWNER_SENDER

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ai_assistant.core.protocols import (
        ConversationStore,
        MemoryStore,
        PersonModelStore,
        PlanStore,
        StoryStore,
    )
    from ai_assistant.core.types import Sight
    from ai_assistant.orchestration.activation_state import ActivationState

#: The activation a case's work is admitted as.
WORK_ID: Final = "60f3c223-6a54-4b06-aab8-4fc397c3d43b"

#: The owner, by a link lowered to weak (§6's first row, lowered).
OWNER_WEAK: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.WEAK)

#: A sender no link identifies (§6's second row).
UNIDENTIFIED: Final = InputSender(person=None, level=Sureness.NONE)


def admitted(*senders: InputSender, at: datetime, activation_id: str = WORK_ID) -> ActivationState:
    """A hub chat message from ``senders``, admitted as the chat's reader's input is."""
    return admit_channel(
        ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="hello")),
        WholeTextReply(),
        clock=lambda: at,
        id_factory=lambda: activation_id,
        senders=senders,
    )


def sight_of(*senders: InputSender, at: datetime, activation_id: str = WORK_ID) -> Sight:
    """The sight admission makes for a work whose input ``senders`` sent; the owner's by
    default, at normal."""
    sight = admitted(*(senders or (OWNER_SENDER,)), at=at, activation_id=activation_id).sight
    assert sight is not None
    return sight


@contextlib.contextmanager
def in_a_work(
    *senders: InputSender, at: datetime, activation_id: str = WORK_ID
) -> Iterator[ActivationState]:
    """Run inside a work admitted from ``senders`` (the owner by default), as a stage a
    call reaches runs inside its work, which its sight is read from (ADR-0383 §7:7)."""
    state = admitted(*(senders or (OWNER_SENDER,)), at=at, activation_id=activation_id)
    token = CURRENT_ACTIVATION.set(ActivationScope(state))
    try:
        yield state
    finally:
        CURRENT_ACTIVATION.reset(token)


def holder(
    *,
    memory: MemoryStore | None = None,
    stories: StoryStore | None = None,
    people: PersonModelStore | None = None,
    conversations: ConversationStore | None = None,
    plans: PlanStore | None = None,
) -> BoundStores:
    """The holder that binds stores for a pass (ADR-0383 §9:1), over the stores named; a
    fresh fake memory store where none is."""
    return BoundStores(
        memory=FakeMemoryStore() if memory is None else memory,
        stories=stories,
        people=people,
        conversations=conversations,
        plans=plans,
    )


#: The sight admission makes for the owner's work at normal: a case that drives a stage
#: for the owner, where the sight's facts are not what it tests, reads by it.
SIGHT: Final = sight_of(at=datetime(2026, 1, 1, tzinfo=UTC))
