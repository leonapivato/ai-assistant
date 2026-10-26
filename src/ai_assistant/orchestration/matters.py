"""One matter, one activation: what running work shares, and how the newest takes it in.

ADR-0349 §5-§7, the engine's half: who an input is from, what understanding's
in-progress section shows, the waits, and the takeover stage's one step.

**Who an input is from** (§7:5's third condition). :class:`InputStanding` is who wrote an
input, as its place's kind establishes it, whether it carries the user's authority
(ADR-0292 §5:5), and its origin (ADR-0284 §2:2). Two activations are of one standing
where both authors are established as one person and both inputs carry the same
authority and origin (:meth:`InputStanding.meets`). A forward on the line has a claimed
author, so its standing names none and meets no other.

**The person an activation is for** (§5:3). An activation whose input's author its place
establishes is that person's; one the Task Scheduler started is the person's its task is
for (:func:`person_of`). Every other activation is no person's, and shares nothing.

**The in-progress section** (§5:2-§5:10). :func:`in_progress` lists every activation
running for the viewer's person, on any place, the Task Scheduler's included, whose stop
mark is unset, other than the viewer, whose open episode
:func:`~ai_assistant.orchestration.disclosure.admitted_to_understanding` admits under the
viewer's audience; nothing to a viewer whose author is not established (§5:5). Each entry
is exactly what caused it, what it took in, in brief, read through the peer view
(:func:`~ai_assistant.core.episode_encoding.project_episode`, §6:7), and whether it has
acted, newest first. The list pull's running part is the same entries under the listing
bound (§6:2).

**Settled** (:func:`settled`, §7:12, §7:15). An activation is settled for the waits once
it has ended or its stop mark is set, or has recorded its first understanding version or
its omission and, where that version names any activation in ``continues``, the takeover
stage's decision for it. It can then absorb nothing and offer to nothing.

**The coordinator** (:class:`Matters`) holds what crosses activations while they run:
who absorbed whom and who took whose input, so the takeover stage follows them forward
(§7:4); the waits before a takeover and before an act (§7:12-§7:16), each bounded by the
waiting pass's deadline and fixed when it begins; the takeover step (§7:4-§7:8,
§7:17-§7:24), in one synchronous step; and the take or decline of an offer (§7:21-§7:23).
Nothing here is persisted: the takeover decision is the working set's (§10:4), and the
episode records only the :class:`~ai_assistant.core.types.JoinedInput` an absorption or
a take appends (§10:7).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.channel_validation import TASK_SCHEDULER
from ai_assistant.core.episode_encoding import project_episode
from ai_assistant.core.types import (
    CapabilityEffect,
    ChannelIdentity,
    EpisodicMemory,
    InputOrigin,
    JoinedInput,
)
from ai_assistant.orchestration.defects import is_defect, log_defect
from ai_assistant.orchestration.disclosure import admitted_to_understanding
from ai_assistant.orchestration.person_block import activation_person

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Sequence
    from datetime import datetime

    from ai_assistant.core.protocols import MemoryStore, PlanStore
    from ai_assistant.core.types import (
        ActivationEffect,
        ActivationStop,
        ActivationUnderstanding,
        PeerView,
        ToolDefinition,
    )
    from ai_assistant.orchestration.activation_state import ActivationState
    from ai_assistant.orchestration.disclosure import TurnSupply

__all__ = [
    "ANSWER_OFFER_CAPABILITY",
    "DEFAULT_HELD_INPUT_LIMIT",
    "DEFAULT_IN_PROGRESS_LIMIT",
    "LOOK_UP_ACTIVATION_CAPABILITY",
    "PEER_BRIEF_CHARS",
    "PEER_VIEW_CHARS",
    "STOP_ACTIVATION_CAPABILITY",
    "THE_USER",
    "Became",
    "InProgressEntry",
    "InputStanding",
    "Matters",
    "Named",
    "Offer",
    "TakeAnswer",
    "in_progress",
    "input_standing",
    "is_pure_read",
    "person_of",
    "settled",
]

_log = structlog.get_logger(__name__)

#: The one person a place's kind establishes as an author today: the hub's user, on the
#: hub chat and on the line from the configured account (ADR-0323 §4:1). The household
#: design names more (ADR-0349 §11).
THE_USER: Final = "user"

#: Planning's three calls on running work (ADR-0349 §4:6, §6:1, §7:20), whose
#: declarations and runner are :mod:`~ai_assistant.orchestration.matter_calls`'s; named
#: here, where planning may read them.
STOP_ACTIVATION_CAPABILITY: Final = "stop_activation"
LOOK_UP_ACTIVATION_CAPABILITY: Final = "look_up_activation"
ANSWER_OFFER_CAPABILITY: Final = "answer_offer"

#: ``Settings.held_input_limit``'s default (ADR-0349 §9:2), which an engine built without
#: the composition root's value takes.
DEFAULT_HELD_INPUT_LIMIT: Final = 4

#: ``Settings.in_progress_limit``'s default (§9:3).
DEFAULT_IN_PROGRESS_LIMIT: Final = 5

#: The bound on what an in-progress entry, or a wait's or an offer's entry, shows of an
#: activation's input: in brief (§5:6).
PEER_BRIEF_CHARS: Final = 300

#: The bound on each part of a peer view a finding is read through: an absorbed
#: activation's findings, a waited-on activation's finished work, a look-up and a stop
#: call's result (§6:7).
PEER_VIEW_CHARS: Final = 2000

#: How long a wait sleeps at most before it reads again what it waits for. Every change
#: it waits on wakes it at once; this bounds one a step that changes nothing it is told
#: of could leave it asleep for.
_RECHECK: Final = 0.05


@dataclass(frozen=True, slots=True)
class InputStanding:
    """Who wrote an input, as its place establishes it, and what it carries (§7:5).

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

    def meets(self, other: InputStanding) -> bool:
        """§7:5's third condition: one author, established alike, one authority, one origin.

        An author not established meets nothing.
        """
        return (
            self.author is not None
            and self.author == other.author
            and self.users_authority == other.users_authority
            and self.origin is other.origin
        )


def input_standing(*, origin: InputOrigin, established: bool) -> InputStanding:
    """The standing of an input whose authors its place's kind either establishes or not.

    Today's kinds that establish an author establish one person, the user
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


#: The effects a pure read may declare (ADR-0341 §2:1): none, or the assistant's own
#: records, which a look-up in memory or of a story declares (ADR-0306 §3:1).
_READ_EFFECTS: Final = frozenset({CapabilityEffect.NONE, CapabilityEffect.OWN_RECORDS})


def is_pure_read(tool: ToolDefinition) -> bool:
    """Whether a call under ``tool`` is a pure read (ADR-0341 §2).

    Its capability declares an empty ``writes``, declares its effect as none or as the
    assistant's own records, and declares that it does not leave the hub: a look-up in
    memory or of a story is one. A write to the hub's own records is not, even one safe
    to repeat that gets no effect record, and neither is a call that leaves the hub, a
    web search among them, nor a call in the world.

    It reads ``tool``'s declaration, the one tool selection picked for the call, and
    nothing else: never the call's name, its capability's name or its arguments (§2:2).
    """
    return not tool.writes and tool.effect in _READ_EFFECTS and not tool.leaves_hub


def person_of(state: ActivationState) -> str | None:
    """The person ``state``'s activation is for, where it is one's to share (§5:3).

    One whose input's author its place establishes is that person's; one the Task
    Scheduler started is the person's its task is for, as ADR-0350 records it. Any other
    is no person's.
    """
    standing = state.standing
    established = standing is not None and standing.author is not None
    kind = None if state.place is None else state.place.channel_type
    if not established and kind != TASK_SCHEDULER:
        return None
    return activation_person(state.trigger)


def _viewer_person(state: ActivationState) -> str | None:
    """The person a viewer is shown running work of: none where its author is not set (§5:5)."""
    standing = state.standing
    if standing is None or standing.author is None:
        return None
    return activation_person(state.trigger)


def _running(state: ActivationState) -> bool:
    """Whether the activation still runs: its end entry is not appended, no stop is set."""
    return not state.ended and not state.stopped


def _same_matter(one: ActivationState, other: ActivationState) -> bool:
    """§7:5's third condition between two activations, the same person's (§5:3)."""
    if one.standing is None or other.standing is None:
        return False
    return one.standing.meets(other.standing) and person_of(one) == person_of(other)


def settled(state: ActivationState) -> bool:
    """Whether ``state`` can no longer absorb or offer to anything (§7:12, §7:15).

    It has ended or its stop mark is set; or it has recorded its first understanding
    version or its omission, and where that version names any activation in
    ``continues``, the takeover stage's decision for it.
    """
    if state.ended or state.stopped or state.understanding_omitted is not None:
        return True
    if not state.understanding:
        return False
    first = state.understanding[0]
    return not first.continues or first.version in state.takeovers


@dataclass(frozen=True, slots=True)
class InProgressEntry:
    """One running activation, as an in-progress entry shows it (§5:6).

    Attributes:
        activation_id: The activation, which an ``R`` label or its episode's ``E`` label
            names (§5:7).
        channel: What caused it: its channel and its place.
        input: What it took in, in brief, read through the peer view; ``None`` where the
            view withholds it.
        acted: Whether it has acted (§3:5).
        origin: Who its input came from, by which a withheld input is said to be outside.
    """

    activation_id: str
    channel: ChannelIdentity
    input: str | None
    acted: bool
    origin: InputOrigin


def _brief(text: str) -> str:
    """``text`` on one line, cut to :data:`PEER_BRIEF_CHARS`."""
    flat = " ".join(text.split())
    return flat if len(flat) <= PEER_BRIEF_CHARS else f"{flat[: PEER_BRIEF_CHARS - 1]}…"


def brief_input(view: PeerView) -> str | None:
    """What a peer view shows of an activation's input, in brief, or ``None`` withheld."""
    if view.input is None:
        return None
    return _brief(" ".join((view.input.text, *(one.text for one in view.joined))))


def entry_of(state: ActivationState) -> InProgressEntry | None:
    """``state`` as an in-progress entry shows it, read from its episode as stored (§5:6).

    ``None`` where its episode was never written, or it was started from no place.
    """
    episode = None if state.capture is None else state.capture.written
    place = state.place
    if (
        state.activation_id is None
        or place is None
        or not isinstance(episode, EpisodicMemory)
        or episode.processing_record is None
    ):
        return None
    view = project_episode(episode, excerpt_chars=PEER_BRIEF_CHARS, effects=())
    return InProgressEntry(
        activation_id=state.activation_id,
        channel=place,
        input=brief_input(view),
        acted=state.committed,
        origin=state.trigger.origin,
    )


def in_progress(
    running: Iterable[ActivationState],
    *,
    viewer: str | None,
    person: str | None,
    supply: TurnSupply | None,
) -> list[InProgressEntry]:
    """Every activation running for ``person`` that a section would enter, newest first.

    §5:2-§5:5: each runs for that person on any place, its stop mark unset, is not
    ``viewer``, and its open episode is one ``admitted_to_understanding`` admits under
    ``supply`` where one is given. Nothing for no person.

    Args:
        running: The activations the engine holds as running.
        viewer: The activation being shown them, which is never entered.
        person: The viewer's person, or ``None`` where its author is not established.
        supply: The viewer's audience posture, or ``None`` to admit every episode.

    Returns:
        The entries, newest first, unbounded.
    """
    if person is None:
        return []
    shown: list[tuple[int, InProgressEntry]] = []
    for one in running:
        episode = None if one.capture is None else one.capture.written
        if (
            one.activation_id is None
            or one.activation_id == viewer
            or not _running(one)
            or person_of(one) != person
            or episode is None
            or (supply is not None and not admitted_to_understanding(supply, (episode,)))
        ):
            continue
        entry = entry_of(one)
        if entry is not None:
            shown.append((one.order, entry))
    shown.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in shown]


class Became(StrEnum):
    """What became of one activation a takeover decision names (§10:4)."""

    ABSORBED = "absorbed"
    NOT_TAKEN = "not_taken"
    OFFERED = "offered"
    TAKEN = "taken"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"
    WAITED_ON = "waited_on"


@dataclass(slots=True)
class Named:
    """One activation a takeover decision names, and what became of it (§10:4).

    Attributes:
        activation_id: The activation ``continues`` named, or, for a take recorded in
            the older's decision, the offering activation.
        reached: The activation followed forward to (§7:4), where it was another.
        became: What became of it; an offer's moves on as it is answered.
        reason: A decline's reason (§7:23), or why it was not taken.
    """

    activation_id: str
    reached: str | None
    became: Became
    reason: str | None = None


@dataclass(slots=True)
class Offer:
    """An offer open to an older activation that has acted (§7:17-§7:19).

    Attributes:
        offering: The newer activation, whose episode label names the offer.
        inputs: Every input it holds, as a take appends them, each naming it.
        meaning: The meaning its understanding version recorded, which covers them.
        decision: The entry in the offering activation's takeover decision that records
            what becomes of it.
    """

    offering: str
    inputs: tuple[JoinedInput, ...]
    meaning: str
    decision: Named = field(repr=False)


class TakeAnswer(StrEnum):
    """What an older activation's answer to an offer came to (§7:21-§7:23)."""

    TAKEN = "taken"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"
    NO_OFFER = "no_offer"


#: A decline's reason where a take would hold more than ``held_input_limit`` (§7:22).
_LIMIT_REACHED: Final = "it already holds as much input as it may"
#: A decline's reason where the older ended without answering (§7:24).
_ENDED_UNANSWERED: Final = "it ended without answering"


class Matters:
    """What crosses activations while they run, and the waits and steps over it (§5-§7).

    The engine builds one over its account of what runs, and every activation's stages
    reach it: the understanding stage for the in-progress section, the takeover stage
    for its wait and its step, acting for its wait before an act, planning for the waits
    on an older activation, and the answer call for a take or a decline.
    """

    def __init__(  # noqa: PLR0913 — the engine's account, the two stores, the stop, the two limits
        self,
        *,
        running: Callable[[], Iterable[ActivationState]],
        plans: PlanStore,
        memory: MemoryStore,
        stop: Callable[[str], Awaitable[ActivationStop]],
        held_input_limit: int,
        in_progress_limit: int,
    ) -> None:
        """Wire the coordinator.

        Args:
            running: The activations the engine holds as running.
            plans: The plan store an absorbed or handed-over activation's stop record is
                written in, and the effect records a peer view reads.
            memory: The store a peer view reads an activation's episode from.
            stop: The Task Manager's stop, with its cascade, which planning's stop call
                runs (§4:7): ``stop_activation``'s one implementation.
            held_input_limit: ``Settings.held_input_limit`` (§9:2).
            in_progress_limit: ``Settings.in_progress_limit`` (§9:3).

        Raises:
            ValueError: If a limit is below 1.
        """
        if held_input_limit < 1 or in_progress_limit < 1:
            msg = "held_input_limit and in_progress_limit are each at least 1 (ADR-0349 §9)"
            raise ValueError(msg)
        self._running = running
        self._plans = plans
        self._memory = memory
        self._stop = stop
        self.held_input_limit = held_input_limit
        self.in_progress_limit = in_progress_limit
        # Who absorbed each absorbed activation, and who took each handed-over one's
        # input, kept while the chain they start may still reach a running activation.
        self._absorbed: dict[str, str] = {}
        self._handed: dict[str, str] = {}
        self._changed = asyncio.Event()

    # --- what runs ---

    def _states(self) -> list[ActivationState]:
        return [one for one in self._running() if one.activation_id is not None]

    def state_of(self, activation_id: str) -> ActivationState | None:
        """The activation by that id the engine holds, where it has not ended."""
        return next(
            (one for one in self._states() if one.activation_id == activation_id and not one.ended),
            None,
        )

    def forward(self, activation_id: str) -> str:
        """Where ``activation_id`` leads, followed through absorptions and hand-overs (§7:4)."""
        seen = {activation_id}
        at = activation_id
        while (after := self._absorbed.get(at) or self._handed.get(at)) is not None:
            if after in seen:
                break
            seen.add(after)
            at = after
        return at

    def absorbed_by(self, activation_id: str) -> str | None:
        """The activation that absorbed ``activation_id``, where one did (§4:9)."""
        return self._absorbed.get(activation_id)

    def changed(self) -> None:
        """Wake every wait: something it may be waiting for has changed."""
        self._changed.set()
        self._changed = asyncio.Event()

    def ended(self, state: ActivationState) -> None:
        """``state``'s activation has ended: what it was offered is declined (§7:24).

        Each offer still open to it is declined, unanswered, and what no running
        activation can now be reached through is let go.
        """
        for offer in list(state.offers.values()):
            self._declined(state, offer, _ENDED_UNANSWERED)
        state.offers.clear()
        live = {one.activation_id for one in self._states() if not one.ended}
        for chain in (self._absorbed, self._handed):
            for key in [key for key in chain if self.forward(key) not in live]:
                del chain[key]
        self.changed()

    async def _until(self, done: Callable[[], bool], deadline: float | None) -> bool:
        """Wait until ``done`` answers, or ``deadline`` passes; whether ``done`` answered."""
        loop = asyncio.get_running_loop()
        while not done():
            event = self._changed
            left = None if deadline is None else deadline - loop.time()
            if left is not None and left <= 0:
                return False
            try:
                async with asyncio.timeout(_RECHECK if left is None else min(left, _RECHECK)):
                    await event.wait()
            except TimeoutError:
                continue
        return True

    # --- the in-progress section (§5) ---

    def in_progress(
        self, viewer: ActivationState, *, supply: TurnSupply
    ) -> tuple[tuple[InProgressEntry, ...], int]:
        """Understanding's in-progress section for ``viewer``, and how many more run (§5:10).

        At most ``in_progress_limit`` entries, newest first.
        """
        entries = in_progress(
            self._states(),
            viewer=viewer.activation_id,
            person=_viewer_person(viewer),
            supply=supply,
        )
        return tuple(entries[: self.in_progress_limit]), max(
            0, len(entries) - self.in_progress_limit
        )

    def entry(self, activation_id: str) -> InProgressEntry | None:
        """``activation_id`` as an in-progress entry shows it, while it runs (§7:19, §7:26).

        Where its episode was never written, its input is shown withheld: what is
        waited on or offered is still shown, as nothing else of it can be read.
        """
        state = self.state_of(activation_id)
        if state is None:
            return None
        entry = entry_of(state)
        if entry is not None or state.place is None:
            return entry
        return InProgressEntry(
            activation_id=activation_id,
            channel=state.place,
            input=None,
            acted=state.committed,
            origin=state.trigger.origin,
        )

    # --- the waits (§7:12-§7:16) ---

    def _newer(self, state: ActivationState) -> list[ActivationState]:
        """What an act of ``state``'s waits for, as it runs now (§7:12).

        Before it has committed, each activation started after it, running for the same
        person with its standing, on any place; after, each such activation caused by its
        own place.
        """
        return [
            one
            for one in self._states()
            if one is not state
            and one.order > state.order
            and _running(one)
            and _same_matter(one, state)
            and (not state.committed or one.place == state.place)
        ]

    def _older(self, state: ActivationState) -> list[ActivationState]:
        """What a takeover of ``state``'s waits for, as it runs now (§7:15)."""
        return [
            one
            for one in self._states()
            if one is not state
            and one.order < state.order
            and _running(one)
            and _same_matter(one, state)
        ]

    async def before_act(self, state: ActivationState, deadline: float) -> bool:
        """§7:12-§7:13: wait for each newer input that could absorb or offer to ``state``.

        What it waits for is what runs when the wait begins, and the wait is bounded by
        ``deadline``.

        Returns:
            Whether each settled before the deadline.
        """
        waited = self._newer(state)
        return await self._until(lambda: all(settled(one) for one in waited), deadline)

    async def before_takeover(self, state: ActivationState, deadline: float) -> bool:
        """§7:15-§7:16: wait once for each older activation's takeover decision.

        Returns:
            Whether each settled before the deadline.
        """
        waited = self._older(state)
        return await self._until(lambda: all(settled(one) for one in waited), deadline)

    async def offer_answered(self, state: ActivationState) -> None:
        """Wait while ``state``'s own offer is open and it is not stopped (§7:25)."""
        await self._until(lambda: state.offered_to is None or state.stopped, None)

    async def waited_ended(self, state: ActivationState) -> None:
        """Wait until each activation ``state`` waits on has ended, or it is stopped (§7:25)."""
        await self._until(lambda: state.stopped or not self.waiting_on(state), None)

    def waiting_on(self, state: ActivationState) -> tuple[str, ...]:
        """The activations ``state`` waits on that have not ended."""
        running = {one.activation_id for one in self._states() if not one.ended}
        return tuple(one for one in state.waits_on if one in running)

    # --- the takeover step (§7:4-§7:8, §7:17-§7:24) ---

    def merge(
        self,
        state: ActivationState,
        understanding: ActivationUnderstanding,
        *,
        at: datetime,
    ) -> tuple[list[Named], list[str]]:
        """The takeover stage's one step for ``understanding``'s version (§7:4).

        In one synchronous step with no await: each activation ``continues`` names is
        followed forward; those reached that started before this one, run with their
        stop mark unset, are the same person's of this standing and have not committed
        are absorbed, all or none under ``held_input_limit``; one reached that has acted,
        on this place, is offered this activation's input, and any other is waited on.

        Returns:
            The decision for the version, each activation named with what became of it,
            and the activations absorbed, whose stop records are the caller's to write.
        """
        decisions: list[Named] = []
        absorb: list[tuple[Named, ActivationState]] = []
        acted: list[tuple[Named, ActivationState]] = []
        seen: set[str] = set()
        if not _running(state):
            # ADR-0295 §2:1: a stopped activation starts nothing new, so it takes nothing in
            # and offers nothing, whatever its version names.
            return [
                Named(activation_id=str(one), reached=None, became=Became.NOT_TAKEN)
                for one in understanding.continues
            ], []
        for named in understanding.continues:
            reached = self.forward(str(named))
            decision = Named(
                activation_id=str(named),
                reached=None if reached == named else reached,
                became=Became.NOT_TAKEN,
            )
            decisions.append(decision)
            other = self.state_of(reached)
            if (
                other is None
                or other is state
                or reached in seen
                or other.order >= state.order
                or not _running(other)
                or not _same_matter(other, state)
            ):
                continue
            seen.add(reached)
            (acted if other.committed else absorb).append((decision, other))
        absorbed = self._absorbing(state, absorb, at=at)
        if not absorbed:
            for decision, _ in absorb:
                decision.reason = _LIMIT_REACHED
        for _, other in absorb:
            if other.activation_id in absorbed:
                self._inherit(state, other, decisions, acted)
        self._reached(state, understanding, acted, at=at)
        self.changed()
        return decisions, absorbed

    def _inherit(
        self,
        state: ActivationState,
        other: ActivationState,
        decisions: list[Named],
        acted: list[tuple[Named, ActivationState]],
    ) -> None:
        """§7:24: what an absorbed activation had reached is its absorber's now.

        Its open offer is withdrawn and made again from here, reached in this step as one
        ``continues`` named would be, under §7:17 and §7:22. Every activation it waited
        on, the one that declined its offer included, the absorber waits on as it was:
        no offer is made to it again. One that has ended is waited for no longer, but
        stays named, so what it finished is still shown, read fresh (§7:27).
        """
        to_id = other.offered_to
        if to_id is not None:
            to = self.state_of(to_id)
            withdrawn = None if to is None else to.offers.pop(str(other.activation_id), None)
            if withdrawn is not None:
                withdrawn.decision.became = Became.WITHDRAWN
            other.offered_to = None
            if to is None and to_id not in state.waits_on:
                state.waits_on = (*state.waits_on, to_id)
            elif to is not None and to is not state and not any(one is to for _, one in acted):
                decision = Named(activation_id=to_id, reached=None, became=Became.OFFERED)
                decisions.append(decision)
                acted.append((decision, to))
        for older_id in other.waits_on:
            if older_id in {to_id, state.activation_id}:
                continue
            if older_id not in state.waits_on:
                state.waits_on = (*state.waits_on, older_id)
            if self.state_of(older_id) is not None:
                decisions.append(
                    Named(activation_id=older_id, reached=None, became=Became.WAITED_ON)
                )

    def _absorbing(
        self,
        state: ActivationState,
        absorb: Sequence[tuple[Named, ActivationState]],
        *,
        at: datetime,
    ) -> list[str]:
        """Absorb every activation in ``absorb``, or none above the limit (§7:6-§7:7)."""
        if not absorb:
            return []
        held = state.inputs_held + sum(other.inputs_held for _, other in absorb)
        if held > self.held_input_limit:
            return []
        absorbed: list[str] = []
        for decision, other in absorb:
            inputs = held_inputs(other, at=at)
            if not inputs:
                continue
            other_id = str(other.activation_id)
            # Marked first, then its inputs taken: both in this one step.
            other.stop()
            other.committed = True
            other.absorbed_by = state.activation_id
            self._absorbed[other_id] = str(state.activation_id)
            state.take_inputs(inputs, merged=(*other.merged, other_id))
            decision.became = Became.ABSORBED
            absorbed.append(other_id)
        return absorbed

    def _reached(
        self,
        state: ActivationState,
        understanding: ActivationUnderstanding,
        acted: Sequence[tuple[Named, ActivationState]],
        *,
        at: datetime,
    ) -> None:
        """Offer to, or wait on, what the step reached that has acted (§7:17-§7:22).

        An offer is made to one activation alone: where the step reached more, or this
        activation already waits on running work it took over from an absorbed one
        (§7:24), a take by one would leave the other going on with no one to wait on it,
        so it waits on each.
        """
        if not acted:
            return
        reached = {str(one.activation_id) for _, one in acted}
        waiting = any(one not in reached for one in self.waiting_on(state))
        offering = len(acted) == 1 and not waiting
        for decision, older in acted:
            older_id = str(older.activation_id)
            if (
                offering
                and older.place is not None
                and older.place == state.place
                and older.inputs_held + older.offers_untaken < self.held_input_limit
            ):
                inputs = held_inputs(state, at=at)
                if inputs:
                    decision.became = Became.OFFERED
                    older.offers[str(state.activation_id)] = Offer(
                        offering=str(state.activation_id),
                        inputs=inputs,
                        meaning=str(understanding.meaning),
                        decision=decision,
                    )
                    older.offers_untaken += 1
                    state.offered_to = older_id
                    state.waits_on = (*state.waits_on, older_id)
                    continue
            decision.became = Became.WAITED_ON
            if older_id not in state.waits_on:
                state.waits_on = (*state.waits_on, older_id)

    # --- the answer (§7:20-§7:23) ---

    def answer(
        self,
        older: ActivationState,
        offering_id: str,
        *,
        take: bool,
        reason: str | None,
    ) -> tuple[TakeAnswer, str | None]:
        """Take or decline the offer ``offering_id`` made ``older``, in one step (§7:21).

        A take appends every offered input to the older, naming the offering activation,
        sets that activation's stop mark and committed mark, and records the hand-over in
        both takeover decisions. Where the offering activation no longer runs with its
        stop mark unset, the offer is withdrawn and nothing changes; where a take would
        hold more than ``held_input_limit``, it is refused and counts as a decline.

        Returns:
            What it came to, and, for a decline, its reason.
        """
        offer = older.offers.pop(offering_id, None)
        if offer is None:
            return TakeAnswer.NO_OFFER, None
        offering = self.state_of(offering_id)
        if offering is None or not _running(offering):
            offer.decision.became = Became.WITHDRAWN
            self.changed()
            return TakeAnswer.WITHDRAWN, None
        if not take:
            declined = reason.strip() if reason and reason.strip() else "no reason given"
            self._declined(older, offer, declined)
            return TakeAnswer.DECLINED, declined
        if older.inputs_held + len(offer.inputs) > self.held_input_limit:
            self._declined(older, offer, _LIMIT_REACHED)
            return TakeAnswer.DECLINED, _LIMIT_REACHED
        offering.stop()
        offering.committed = True
        offering.handed_to = older.activation_id
        offering.offered_to = None
        self._handed[offering_id] = str(older.activation_id)
        older.take_inputs(offer.inputs, merged=(*offering.merged, offering_id))
        older.offers_untaken -= 1
        offer.decision.became = Became.TAKEN
        older.took.append(Named(offering_id, None, Became.TAKEN))
        self.changed()
        return TakeAnswer.TAKEN, None

    def _declined(self, older: ActivationState, offer: Offer, reason: str) -> None:
        """Record a decline in the offering activation's decision; it now waits (§7:23)."""
        offer.decision.became = Became.DECLINED
        offer.decision.reason = reason
        offering = self.state_of(offer.offering)
        if offering is not None:
            offering.offered_to = None
            offering.declined = (*offering.declined, (str(older.activation_id), reason))
        self.changed()

    # --- the stops a merge makes, and the peer view ---

    async def record_stop(self, activation_id: str, *, deadline: float | None, stage: str) -> None:
        """Write a merge's stop record, after its step, inside ``deadline`` (§4:5).

        Internal: no cascade record and no walk (ADR-0350 §9:6). A record that cannot be
        written is logged: the marks are set, so the other activation runs no further
        stage and commits nothing. ``None`` writes it to its end.
        """
        try:
            async with asyncio.timeout_at(deadline):
                await self._plans.record_stop(activation_id)
        except Exception as exc:  # the marks hold it: logged, never the pass's failure
            if is_defect(exc):
                log_defect("merge_stop_unrecorded", exc, stage=stage, activation_id=activation_id)
            else:
                _log.warning("merge_stop_unrecorded", stage=stage, reason="store_failed")

    async def stop(self, activation_id: str) -> ActivationStop:
        """The Task Manager's stop, with its cascade, for planning's stop call (§4:7)."""
        return await self._stop(activation_id)

    async def peer(self, activation_id: str, *, owner_records: bool) -> PeerView | None:
        """``activation_id``'s own work through the peer view, read fresh (§6:7-§6:10).

        Its episode as stored, open or frozen, and its effect records, read now. ``None``
        where no episode with a processing record stands at its address.
        """
        address = f"activation:{activation_id}"
        record = await self._memory.get(address)
        if not isinstance(record, EpisodicMemory) or record.processing_record is None:
            return None
        effects: tuple[ActivationEffect, ...] = await self._plans.activation_effects(
            [activation_id]
        )
        return project_episode(
            record,
            excerpt_chars=PEER_VIEW_CHARS,
            owner_records=owner_records,
            effects=effects,
        )


def held_inputs(state: ActivationState, *, at: datetime) -> tuple[JoinedInput, ...]:
    """Every input ``state`` holds, each as a ``JoinedInput`` naming it (§7:7, §7:21).

    Its trigger's input, from its place, then each input it took in, in order. Empty
    where its trigger's messages were never held, which no absorption or take brings.
    """
    place = state.place
    activation_id = state.activation_id
    if place is None or activation_id is None or not state.input_messages:
        return ()
    return (
        JoinedInput(
            joined_at=at,
            channel=place,
            messages=state.input_messages,
            taken_over_from=activation_id,
        ),
        *(one.model_copy(update={"taken_over_from": activation_id}) for one in state.joined),
    )
