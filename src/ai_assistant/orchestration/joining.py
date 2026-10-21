"""Joining a running activation, and taking one over from another place (ADR-0332 §3, §4).

**The boundary** (§3:1-§3:2). An activation folds in new input until it commits to
something it cannot take back: acting's first call that is not a *pure read* — a call
whose capability declares :attr:`~ai_assistant.core.types.CapabilityEffect.NONE` and
does not leave the hub — or the round's message (:func:`is_pure_read`). The mark is
:attr:`~ai_assistant.orchestration.activation_state.ActivationState.committed`, set by
acting's commitment step (:meth:`~ai_assistant.orchestration.activation_state.
ActivationState.commit`), in one step with no await between the check and the mark.

**Who may join** (§3:3). An input joins the activation running on its place only where
its author is the running activation's input's author, established in the same way, and
it carries the same authority (ADR-0292 §5:5) and the same origin (ADR-0284 §2:2):
:class:`InputStanding` is that triple, which the place's own kind establishes. A forward
on the line has a claimed author, so its standing names none, and it never joins; a
user's message never joins an activation a forward started. Which input is *waiting* on
the place is the reader's to know, so §3:3's fourth condition — no earlier input on the
place is waiting — is the reader's to hold before it hands an input to the join.

**The join** (§3:6) is :meth:`~ai_assistant.orchestration.activation_state.
ActivationState.join`: taken only where the activation has not ended, neither its
committed mark nor its stop mark is set, and it has taken fewer joins than
``join_limit`` (§6:5), in one step with no await between the check and the append.

**What another place is shown** (§4:1-§4:3). :func:`visible_running` reads the running
activations of the same person on that person's other places, each with its input and
whether it has committed, under the pass's audience: one is shown only where
:func:`~ai_assistant.orchestration.disclosure.admitted_to_understanding` admits its open
episode to this pass, and never to an input whose author is not established or is
another person.

**The takeover** (§4:6) is :func:`take_over`: in one step with no await between, it
reads that the named activation still runs, has not committed and is not stopped, that
its input carries this activation's authority and origin, and that this activation has
taken fewer joins than ``join_limit``; where all of it holds it sets the other's stop
mark and committed mark and appends the other's input to this one as a
:class:`~ai_assistant.core.types.JoinedInput` naming it. A takeover counts as a join.

Everything here is orchestration-local: no Protocol in ``core`` describes it, and the
episode carries only the :class:`~ai_assistant.core.types.JoinedInput` records (§7:1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    CapabilityEffect,
    ChannelIdentity,
    InputOrigin,
    JoinedInput,
    RecordedInputMessage,
)
from ai_assistant.orchestration.disclosure import admitted_to_understanding

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime

    from ai_assistant.core.types import ToolDefinition
    from ai_assistant.orchestration.activation_state import ActivationState
    from ai_assistant.orchestration.disclosure import TurnSupply

__all__ = [
    "DEFAULT_JOIN_LIMIT",
    "THE_USER",
    "InputStanding",
    "JoiningInput",
    "RunningActivation",
    "input_standing",
    "is_pure_read",
    "join_running",
    "take_over",
    "visible_running",
]

#: ``Settings.join_limit``'s default (ADR-0332 §6:5), which an engine built without the
#: composition root's value takes.
DEFAULT_JOIN_LIMIT: Final = 3

#: The one person a place's kind establishes as an author today: the hub's user, on the
#: hub chat and on the line from the configured account (ADR-0323 §4:1). The household
#: design names more (ADR-0332 §9).
THE_USER: Final = "user"


@dataclass(frozen=True, slots=True)
class InputStanding:
    """Who wrote an input, as its place establishes it, and what it carries (§3:3).

    Attributes:
        author: The person the place's kind establishes as the input's author, or
            ``None`` where it establishes none: a forward's author is claimed (ADR-0323
            §4:10), and so is an input that takes one in, and an event's.
        users_authority: Whether the input carries the user's authority (ADR-0292
            §5:5, ADR-0321 §3:3).
        origin: Who the input came from, as admission records it (ADR-0284 §2:2).
    """

    author: str | None
    users_authority: bool
    origin: InputOrigin

    def joins(self, running: InputStanding) -> bool:
        """Whether an input of this standing may join one of ``running``'s (§3:3).

        Both authors are established and are the same person, and the two carry the
        same authority and the same origin. An author not established joins nothing.
        """
        return (
            self.author is not None
            and self.author == running.author
            and self.users_authority == running.users_authority
            and self.origin is running.origin
        )

    def same_person(self, other: InputStanding) -> bool:
        """Whether both inputs' authors are established as one person (§4:1)."""
        return self.author is not None and self.author == other.author


def input_standing(*, origin: InputOrigin, established: bool) -> InputStanding:
    """The standing of an input whose authors its place's kind either establishes or not.

    Today's two kinds that run one activation at a time establish one person, the user
    (:data:`THE_USER`): an input whose every message they establish as the user's is the
    user's, and carries the user's authority where its origin is the user's (ADR-0323
    §4:7, as ADR-0321 §3:3 reads it for every channel).

    Args:
        origin: Who the input came from, as admission records it.
        established: Whether the place's kind establishes every message of the input as
            the user's: on the line, none a forward (ADR-0323 §4:6, §4:10).

    Returns:
        The input's standing.
    """
    return InputStanding(
        author=THE_USER if established else None,
        users_authority=established and origin is InputOrigin.USER,
        origin=origin,
    )


@dataclass(frozen=True, slots=True)
class JoiningInput:
    """An input a reader hands the join (§3:3): where it came from, and what it is.

    Attributes:
        channel: The place it came from, which is the running activation's place.
        messages: Its messages, each kept apart and dated, as a trigger's are (ADR-0323
            §5:4). At least one.
        standing: Who wrote it, as the place establishes it, and what it carries.

    Raises:
        ValueError: If it carries no message.
    """

    channel: ChannelIdentity
    messages: tuple[RecordedInputMessage, ...]
    standing: InputStanding

    def __post_init__(self) -> None:
        """An input that joins carries at least one message (§7:1)."""
        if not self.messages:
            msg = "an input that joins carries at least one message (ADR-0332 §7:1)"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class RunningActivation:
    """A running activation on another of the same person's places, as understanding sees it.

    ADR-0332 §4:1: its input, and whether it has committed. It is shown beside the window
    under an ``R`` label, which ``continues`` names (§4:4, §7:3).

    Attributes:
        activation_id: The activation, which a ``continues`` label resolves to (§7:4).
        place: The place it was started from.
        started_at: When it was admitted.
        messages: Its input: its trigger's messages, then each joined one's, in order.
        committed: Whether it has committed (§3:2), after which it cannot be taken over.
    """

    activation_id: str
    place: ChannelIdentity
    started_at: datetime
    messages: tuple[RecordedInputMessage, ...]
    committed: bool


def is_pure_read(tool: ToolDefinition) -> bool:
    """Whether a call under ``tool`` is a pure read (ADR-0332 §3:1).

    Its capability declares that it changes nothing, and it does not leave the hub. A
    write to the hub's own records is not one, even one safe to repeat that gets no
    effect record, and neither is a call that leaves the hub, a web search among them.
    """
    return tool.effect is CapabilityEffect.NONE and not tool.leaves_hub


def _running(state: ActivationState) -> bool:
    """Whether the activation still runs: its end entry is not appended, no stop is set."""
    return not state.ended and not state.stopped


def join_running(
    running: Iterable[ActivationState],
    joining: JoiningInput,
    *,
    limit: int,
    at: datetime,
) -> str | None:
    """Join ``joining`` to the activation running on its place, where §3:3 allows.

    **One step with no await between** (§3:6): the activation is found, its input's
    standing compared with ``joining``'s, and :meth:`ActivationState.join` checks its
    marks and its count and appends, all before anything yields the loop.

    The place runs one activation at a time (§2:3), so at most one started from it is
    running; where more than one is, none is joined, failing closed. A place with none
    running joins nothing: the input starts the next activation there, as the reader
    takes it in (§2:4).

    Args:
        running: The activations the engine holds as running.
        joining: The input a reader brings, with its standing.
        limit: ``join_limit`` (§6:5): the most joins one activation takes.
        at: When it joins.

    Returns:
        The id of the activation it joined, which the reader marks its messages taken
        in by (§3:18); ``None`` where it joined none, and then it waits (§3:4).
    """
    on_place = [one for one in running if one.place == joining.channel and not one.ended]
    if len(on_place) != 1:
        return None
    (state,) = on_place
    if state.activation_id is None or state.standing is None:
        return None
    if not joining.standing.joins(state.standing):
        return None
    joined = JoinedInput(joined_at=at, channel=joining.channel, messages=joining.messages)
    return state.activation_id if state.join(joined, limit=limit) else None


def visible_running(
    running: Iterable[ActivationState],
    viewer: ActivationState,
    *,
    supply: TurnSupply,
) -> tuple[RunningActivation, ...]:
    """The running activations on the viewer's person's other places, as §4:1 shows them.

    Each is the same person's — both inputs' authors established as that person — runs
    from another place than the viewer's, still runs, and is admitted to this pass:
    its open episode is one :func:`admitted_to_understanding` admits under ``supply``
    (§4:2). An activation whose episode was never written is not shown, failing closed.
    Nothing is shown to a viewer whose author is not established (§4:3).

    Args:
        running: The activations the engine holds as running.
        viewer: The activation whose understanding is being shown them.
        supply: The viewer's audience posture.

    Returns:
        The activations shown, oldest first.
    """
    standing = viewer.standing
    place = viewer.place
    if standing is None or standing.author is None:
        return ()
    shown: list[RunningActivation] = []
    for one in running:
        other = one.standing
        there = one.place
        episode = None if one.capture is None else one.capture.written
        if (
            one is viewer
            or one.activation_id is None
            or one.started_at is None
            or there is None
            or there == place
            or other is None
            or not standing.same_person(other)
            or not _running(one)
            or episode is None
            or not admitted_to_understanding(supply, (episode,))
        ):
            continue
        shown.append(
            RunningActivation(
                activation_id=one.activation_id,
                place=there,
                started_at=one.started_at,
                messages=one.whole_input,
                committed=one.committed,
            )
        )
    return tuple(sorted(shown, key=lambda one: one.started_at))


def take_over(
    running: Sequence[ActivationState],
    taker: ActivationState,
    named: str,
    *,
    limit: int,
    at: datetime,
) -> bool:
    """Take over the activation ``named``, where §4:6 allows; whether it was taken.

    **One step with no await between**: the named activation is found among those
    running, and it is taken only where it still runs — not ended, its stop mark unset —
    has not committed, is the same person's, and its input carries the taker's
    authority and origin (as §3:3 requires of a join), and the taker has taken fewer
    joins than ``limit``. Then its stop mark and its committed mark are set, so it can
    neither commit nor take a join, and its whole input is appended to the taker's as a
    :class:`~ai_assistant.core.types.JoinedInput` naming it (§4:6, §3:17).

    Its stop record is the caller's to write once this returns (ADR-0297 §3:4): the mark
    is what every stage reads, and the record follows it.

    Args:
        running: The activations the engine holds as running.
        taker: The activation whose understanding named the other.
        named: The activation ``continues`` resolved to (§7:4).
        limit: ``join_limit`` (§6:5).
        at: When it is taken over.

    Returns:
        Whether it was taken over; ``False`` where nothing was stopped or appended
        (§4:8).
    """
    other = next((one for one in running if one.activation_id == named), None)
    standing = taker.standing
    if (
        other is None
        or other is taker
        or standing is None
        or other.standing is None
        or not standing.joins(other.standing)
        or not _running(other)
        or other.committed
        or not taker.can_join(limit=limit)
    ):
        return False
    place = other.place
    messages = other.whole_input
    if place is None or not messages:
        return False
    joined = JoinedInput(joined_at=at, channel=place, messages=messages, taken_over_from=named)
    # The other is marked first, then this one takes its input: both in this one step.
    other.stop()
    other.committed = True
    return taker.join(joined, limit=limit)
