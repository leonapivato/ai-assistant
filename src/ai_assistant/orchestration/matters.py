"""One matter, one activation: what running work shares, and how the newest takes it in.

ADR-0349 §5-§7, the engine's half: who an input is from, what understanding's
in-progress section shows, the waits, and the takeover stage's one step.

**Who an input is from** (§7:5's third condition). :class:`InputStanding` is who handed
an input in, as its place's kind establishes it, whether it carries the user's authority
(ADR-0292 §5:5, ADR-0351 §6:1), and whose words it carries, its parties (ADR-0351 §2:1).
Two activations are of one standing where both authors are established as one person,
both carry the same authority, and both are outside, or both the person's own, or both
the assistant's: ADR-0351 §8:5's class, read over every input each holds with its relay
mark (:meth:`InputStanding.meets`). An input whose parties are ``None`` or empty meets
none. A forward on the line has the user as its author, established, who forwarded it
(ADR-0351 §4:2), and its original sender as its party, claimed, so it meets another
forward, whoever sent that, and never the user's own words.

**The relay mark** (ADR-0351 §5:6-§5:14). A running activation's inputs are read with
their relay marks: its trigger's by its latest understanding version, and each joined
input's by its own record. In the takeover step each activation is read so, one whose
trigger's input no version has yet covered by its parties alone (§5:11); in a wait, such
a one, whose understanding was not omitted, is read both as its parties give it and as
a relay mark would leave it, outside and with no authority (§8:5), so that a wait covers
every input a relay mark could bring into the waiting activation's class. An
absorption and a take record ``relayed`` on each joined input they append, where that
input is relayed in the activation it comes from (§5:14).

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

**What a reader holds** (:class:`HeldInput`, §7:12, §8:2). Every message on a place
starts its own activation once its place's start wait has passed (§8:1), and while it
waits it is no activation yet. A reader tells the coordinator of each input it holds in
its start wait (:meth:`Matters.hold`), then of the activation it admitted it as, and
lets it go once that activation has ended or nothing was taken in. So an act waits for a
correction typed just before it, not only for one whose activation has already begun.

**The coordinator** (:class:`Matters`) holds what crosses activations while they run:
who absorbed whom and who took whose input, so the takeover stage follows them forward
(§7:4); the inputs the readers hold in their start waits; the waits before a takeover
and before an act (§7:12-§7:16), each bounded by the waiting pass's deadline and fixed
when it begins; the takeover step (§7:4-§7:8, §7:17-§7:24), in one synchronous step;
and the take or decline of an offer (§7:21-§7:23).
Nothing here is persisted: the takeover decision is the working set's (§10:4), and the
episode records only the :class:`~ai_assistant.core.types.JoinedInput` an absorption or
a take appends (§10:7).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol

import structlog

from ai_assistant.core.channel_validation import APPROVALS, TASK_SCHEDULER, establishes_the_user
from ai_assistant.core.episode_encoding import project_episode
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    CapabilityEffect,
    ChannelIdentity,
    EpisodicMemory,
    JoinedInput,
    SupportHolder,
    parties_are_assistants,
    parties_are_outside,
    parties_are_persons_own,
)
from ai_assistant.orchestration.defects import is_defect, log_defect
from ai_assistant.orchestration.disclosure import admitted_to_understanding
from ai_assistant.orchestration.outside_content import holds_outside, joined_parties, relayed_by
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
    from ai_assistant.orchestration.task_scheduler import StillLive

__all__ = [
    "ANSWER_OFFER_CAPABILITY",
    "DEFAULT_HELD_INPUT_LIMIT",
    "DEFAULT_IN_PROGRESS_LIMIT",
    "LOOK_UP_ACTIVATION_CAPABILITY",
    "PEER_BRIEF_CHARS",
    "PEER_VIEW_CHARS",
    "STOP_ACTIVATION_CAPABILITY",
    "THE_USER",
    "Answered",
    "Became",
    "EntryInput",
    "HeldInput",
    "InProgressEntry",
    "InputStanding",
    "Matters",
    "Named",
    "NotAsAsked",
    "Offer",
    "SetUpRead",
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


class _Class(StrEnum):
    """ADR-0351 §8:5's class: outside, the person's own, or the assistant's (§5:1, §5:2)."""

    OUTSIDE = "outside"
    OWN = "own"
    ASSISTANTS = "assistants"


def _class_of(parties: Sequence[SupportHolder] | None, *, relayed: bool) -> _Class | None:
    """The class of an input of ``parties`` read with its relay mark; ``None`` for none.

    An input whose parties are ``None`` or empty meets the condition with no input
    (§8:5), so it has no class here, though ``None`` parties are outside (§5:1).
    """
    if not parties:
        return None
    if parties_are_outside(parties, relayed=relayed):
        return _Class.OUTSIDE
    if parties_are_persons_own(parties, relayed=relayed):
        return _Class.OWN
    if parties_are_assistants(parties, relayed=relayed):
        return _Class.ASSISTANTS
    return None


@dataclass(frozen=True, slots=True)
class InputStanding:
    """Who handed an input in, as its place establishes it, and whose words it is (§7:5).

    Its authority and its class are read with the relay mark of every input its
    activation holds (ADR-0351 §5:7, §6:5, §8:5), which :meth:`meets` is handed: the
    standing itself is what the place and the parties give, and changes with no reply.

    Attributes:
        author: The person the place's kind establishes as the input's author, or
            ``None`` where it establishes none: an event's, or an input on a place whose
            kind establishes no author.
        users_authority: Whether the input carries the user's authority as its author and
            its parties give it, before any relay mark (ADR-0292 §5:5, ADR-0351 §6:1).
        parties: Whose words the trigger's input carries (ADR-0351 §2:1), or ``None``
            where they are unknown.
    """

    author: str | None
    users_authority: bool
    parties: tuple[SupportHolder, ...] | None

    def meets(self, other: InputStanding, *, relayed: bool, other_relayed: bool) -> bool:
        """§7:5's third condition: one author, established alike, one authority, one class.

        Each side is read with ``relayed``, whether any input its activation holds is
        relayed (ADR-0351 §5:7, §8:5). An author not established meets nothing, and nor
        does an input whose parties are ``None`` or empty.
        """
        mine = _class_of(self.parties, relayed=relayed)
        return (
            self.author is not None
            and self.author == other.author
            and (self.users_authority and not relayed)
            == (other.users_authority and not other_relayed)
            and mine is not None
            and mine is _class_of(other.parties, relayed=other_relayed)
        )


def input_standing(
    *, parties: tuple[SupportHolder, ...] | None, established: bool
) -> InputStanding:
    """The standing of an input whose authors its place's kind either establishes or not.

    Today's kinds that establish an author establish one person, the user
    (:data:`THE_USER`): an input whose every message they establish as handed in by the
    user is the user's to hand in, and carries the user's authority where its parties are
    the user alone (ADR-0351 §6:1, ADR-0323 §4:7, as ADR-0321 §3:3 reads it for every
    channel). A forward on the line is handed in by the user, and its parties are its
    sender's, claimed, so it carries none (ADR-0351 §4:2, §6:2).

    Args:
        parties: Whose words the trigger's input carries, as admission recorded them.
        established: Whether the place's kind establishes the user as having handed in
            every message of the input.

    Returns:
        The input's standing.
    """
    return InputStanding(
        author=THE_USER if established else None,
        users_authority=established and parties_are_persons_own(parties),
        parties=parties,
    )


def holds_relayed(state: ActivationState) -> bool:
    """Whether any input ``state`` holds is relayed (ADR-0351 §5:11, §5:14, §8:5).

    Its trigger's, by its latest understanding version, or a joined input's, by its own
    record. A joined input whose parties are empty, an approval's, is left out (ADR-0361
    §6:6): it carries no one's words, so no relay mark on it lowers anything.
    """
    return relayed_by(state.understanding) or any(
        one.relayed and joined_parties(one) != () for one in state.joined
    )


def _covered(state: ActivationState) -> bool:
    """Whether a version covers ``state``'s trigger's input, or its understanding was omitted.

    Until then its relay mark is not known, and a wait reads it both ways (§8:5).
    """
    return bool(state.understanding) or state.understanding_omitted is not None


def _readings(state: ActivationState) -> tuple[bool, ...]:
    """The relay marks ``state`` may be read with: its own, or both where not yet known."""
    relayed = holds_relayed(state)
    return (relayed,) if relayed or _covered(state) else (False, True)


#: The kinds whose activation is for the person its record names, though no author is
#: established: a scheduled task's (ADR-0350 §6:4) and an approval's (ADR-0361 §6:1).
_FOR_A_RECORDS_PERSON: Final = frozenset({TASK_SCHEDULER, APPROVALS})

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
    Scheduler started is the person's its task is for, as ADR-0350 records it; and an
    approval's is its request's person's (ADR-0361 §6:1). Any other is no person's.
    """
    standing = state.standing
    established = standing is not None and standing.author is not None
    kind = None if state.place is None else state.place.channel_type
    if not established and kind not in _FOR_A_RECORDS_PERSON:
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


def _held_person(place: ChannelIdentity) -> str | None:
    """The person an input held on ``place`` may be from: its kind's established author.

    Today's kinds that establish an author establish the owner (ADR-0338 §2:2), as
    :func:`~ai_assistant.orchestration.person_block.activation_person` reads them.
    """
    return OWNER_PERSON_ID if establishes_the_user(place.channel_type) else None


def _same_matter(one: ActivationState, other: ActivationState, *, waiting: bool = False) -> bool:
    """§7:5's third condition between two activations, the same person's (§5:3).

    Each is read with its relay marks as it holds them now (ADR-0351 §5:11, §8:5): the
    takeover step reads each so, one whose trigger's input no version has yet covered by
    its parties alone. A wait reads such a one both ways (:func:`_readings`), and the
    condition holds where either reading meets, so that a wait covers every input a
    relay mark could bring into the waiting activation's class.
    """
    mine, theirs = one.standing, other.standing
    if mine is None or theirs is None or person_of(one) != person_of(other):
        return False
    if not waiting:
        return mine.meets(theirs, relayed=holds_relayed(one), other_relayed=holds_relayed(other))
    return any(
        mine.meets(theirs, relayed=relayed, other_relayed=other_relayed)
        for relayed in _readings(one)
        for other_relayed in _readings(other)
    )


def _may_share(one: ActivationState, other: ActivationState) -> bool:
    """Whether ``one`` is, or may yet show itself to be, of ``other``'s standing (§7:5).

    It is where its standing meets ``other``'s under any reading of its relay marks; and
    it may yet be where its pass has not set its standing, on a place whose kind
    establishes an author.
    """
    if one.standing is not None:
        return _same_matter(one, other, waiting=True)
    place = one.place
    return (
        other.standing is not None
        and place is not None
        and establishes_the_user(place.channel_type)
    )


def _waited_out(one: ActivationState, other: ActivationState) -> bool:
    """Whether a wait of ``other``'s need wait for ``one`` no longer (§7:12, §7:15).

    It has settled, or its standing, now set, shows it is not of ``other``'s under any
    reading of its relay marks (ADR-0351 §8:5).
    """
    return settled(one) or (one.standing is not None and not _same_matter(one, other, waiting=True))


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


@dataclass(eq=False, slots=True)
class HeldInput:
    """An input a reader holds in its place's start wait, until its activation ends (§7:12).

    A reader takes it from :meth:`Matters.hold` when the start wait begins, says which
    activation it admitted it as (:meth:`admitted`), and lets it go (:meth:`release`)
    once that activation has ended, or once nothing was taken in. Every message of a
    place whose kind establishes the user may be the user's own, so a held input is
    waited for as that person's until its activation shows otherwise.

    It counts the notices of the messages it holds (:meth:`noticed`). A message noticed
    while the reader read what waits may be missing from what it took in, and then
    waits in a start wait of its own: the reader says where such messages moved, and
    from which notice on (:meth:`moved_to`). So a wait that began once one of them was
    noticed waits for it there, and a wait that began before any was does not.

    Attributes:
        place: The place it was written in.
        activation_id: The activation it was admitted as, once it was.
        released: Whether the reader has let it go.
        notices: How many notices of its messages the reader has had.
        then: The held input the messages noticed after :attr:`moved_after` may have
            moved to, where any did.
        moved_after: The notices the reader had when it began the read that missed
            them; a message noticed after that may be held by :attr:`then`.
    """

    place: ChannelIdentity
    activation_id: str | None = None
    released: bool = False
    notices: int = 0
    then: HeldInput | None = None
    moved_after: int = 0
    _matters: Matters | None = field(default=None, repr=False)

    def noticed(self) -> None:
        """The reader had one more notice of a message it holds here."""
        self.notices += 1

    def admitted(self, activation_id: str) -> None:
        """The reader admitted it as ``activation_id``, whose own end now settles it."""
        self.activation_id = activation_id
        if self._matters is not None:
            self._matters.changed()

    def moved_to(self, successor: HeldInput, *, after: int) -> None:
        """What was noticed after its ``after``-th notice may now be ``successor``'s."""
        self.then = successor
        self.moved_after = after
        if self._matters is not None:
            self._matters.changed()

    def release(self) -> None:
        """The reader lets it go: its activation has ended, or nothing was taken in."""
        if self.released:
            return
        self.released = True
        if self._matters is not None:
            self._matters.let_go(self)


@dataclass(frozen=True, slots=True)
class EntryInput:
    """One input a running activation holds, as its in-progress entry shows it.

    ADR-0353 §2:6-§2:7: understanding renders one text tag per input, the trigger's
    first and then each joined input in the order it was joined, its tag and ``from``
    given by the input's parties, and an input the peer view withholds as an empty
    marker, never as its text.

    Attributes:
        brief: The input in brief, read through the peer view; ``None`` where the view
            withholds it.
        parties: Whose words it carries (ADR-0351 §2:1, §2:6), or ``None`` where they are
            unknown.
        relayed: Whether it is relayed: the trigger's input by the activation's latest
            understanding version, a joined input by its own record (ADR-0351 §5:11,
            §5:14).
    """

    brief: str | None
    parties: tuple[SupportHolder, ...] | None
    relayed: bool = False


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
        parties: Whose words its trigger's input carries (ADR-0351 §2:1), by which a
            withheld input is said to be the assistant's; ``None`` where they are unknown.
        arrived_at: When its input arrived, its episode's ``occurred_at``, the one addition
            ADR-0353 §2:5 makes to §5:6's list; ``None`` where its episode was never
            written.
        inputs: Each input it holds, the trigger's first and then each joined one in the
            order it was joined (ADR-0353 §2:6); empty where its episode was never written.
        outside: Whether any input it holds is outside (ADR-0351 §5:1, §5:7, §8:5), by
            its parties and its relay mark (ADR-0353 §2:7), by which a withheld input is
            said to be outside.
    """

    activation_id: str
    channel: ChannelIdentity
    input: str | None
    acted: bool
    parties: tuple[SupportHolder, ...] | None
    arrived_at: datetime | None = None
    inputs: tuple[EntryInput, ...] = ()
    outside: bool = False


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

    Its text is read from the episode as stored, and withheld where the activation, as
    it runs now, holds outside input (ADR-0351 §5:7, §8:5): a relay mark recorded since
    the stored episode was last written withholds what that episode would still show.
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
    trigger = state.trigger
    outside = holds_outside(trigger, state.understanding, state.joined)
    if outside:
        view = view.model_copy(update={"input": None, "joined": ()})
    # ADR-0353 §2:6: one input per text tag, the trigger's then each joined one, each as
    # the peer view shows it and with its own parties (ADR-0351 §2:6).
    joined = episode.processing_record.joined
    inputs = (
        EntryInput(
            brief=None if view.input is None else _brief(view.input.text),
            parties=trigger.parties,
            relayed=relayed_by(state.understanding),
        ),
        *(
            EntryInput(
                brief=None if index >= len(view.joined) else _brief(view.joined[index].text),
                # §2:6: a joined input's parties are its messages' distinct parties, or
                # unknown where the episode store's upgrade could not read them (§9:3).
                parties=joined_parties(one),
                relayed=one.relayed,
            )
            for index, one in enumerate(joined)
        ),
    )
    return InProgressEntry(
        activation_id=state.activation_id,
        channel=place,
        input=brief_input(view),
        acted=state.committed,
        parties=trigger.parties,
        arrived_at=episode.occurred_at,
        inputs=inputs,
        outside=outside,
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
        state: The offering activation's own state, held so that an answer after it has
            ended still reads whether it was stopped (ADR-0352 §4:2).
    """

    offering: str
    inputs: tuple[JoinedInput, ...]
    meaning: str
    decision: Named = field(repr=False)
    state: ActivationState = field(repr=False, compare=False)


class TakeAnswer(StrEnum):
    """What an older activation's answer to an offer came to (§7:21-§7:23)."""

    TAKEN = "taken"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"
    NO_OFFER = "no_offer"


class NotAsAsked(StrEnum):
    """Why an answer call did not come to what it asked (ADR-0352 §4:2).

    Each is a fact planning is told, beside the answer's result and in the reason of each
    call its round held back, so that the round planned again knows what the answer came
    to (ADR-0349 §7:22-§7:23).
    """

    #: Withdrawn: the offering activation was stopped before the answer.
    STOPPED = "offering_stopped"
    #: Withdrawn: the offering activation ended, unstopped, before the answer.
    ENDED = "offering_ended"
    #: A take refused at ``held_input_limit``, which counts as a decline (§7:22).
    AT_LIMIT = "held_input_limit"
    #: The label names no offer open to the answering activation (§7:20).
    NO_OFFER = "no_offer"
    #: Refused before acting, by planning's own check or by authorizing.
    NOT_ALLOWED = "not_allowed"
    #: Not done for any other reason: its arguments, or the hub's records.
    NOT_DONE = "not_done"


@dataclass(frozen=True, slots=True)
class Answered:
    """What an answer to an offer came to (§7:20-§7:23).

    Attributes:
        came_to: The take, the decline, the withdrawal, or no offer at all.
        reason: A decline's reason, as the offering activation's takeover decision
            records it and its planning is shown it (§7:23); ``None`` otherwise.
        not_as_asked: Why it did not come to what the answer asked, a take to a take or
            a decline to the decline; ``None`` where it did (ADR-0352 §4:2-§4:3).
        meaning: The meaning the offer carried, as its offering activation's
            understanding recorded it (§7:19); ``None`` where no offer was open.
    """

    came_to: TakeAnswer
    reason: str | None = None
    not_as_asked: NotAsAsked | None = None
    meaning: str | None = None


#: A decline's reason where a take would hold more than ``held_input_limit`` (§7:22).
_LIMIT_REACHED: Final = "it already holds as much input as it may"
#: A decline's reason where the older ended without answering (§7:24).
_ENDED_UNANSWERED: Final = "it ended without answering"


class SetUpRead(Protocol):
    """Reads what an activation set up that is still live below it (ADR-0352 §3:1-§3:2).

    The engine's, over its Task Manager; it answers ``None`` where no Task Scheduler is
    wired, so nothing can have been set up.
    """

    def __call__(
        self,
        activation_id: str,
        /,
        *,
        person: str,
        viewer: str | None,
        supply: TurnSupply | None,
    ) -> Awaitable[StillLive | None]:
        """What ``activation_id`` set up that is still live, as ``viewer`` is shown it."""
        ...


class Matters:
    """What crosses activations while they run, and the waits and steps over it (§5-§7).

    The engine builds one over its account of what runs, and every activation's stages
    reach it: the understanding stage for the in-progress section, the takeover stage
    for its wait and its step, acting for its wait before an act, planning for the waits
    on an older activation, and the answer call for a take or a decline.
    """

    def __init__(  # noqa: PLR0913 — the engine's account, the two stores, the stop and its read, the two limits
        self,
        *,
        running: Callable[[], Iterable[ActivationState]],
        plans: PlanStore,
        memory: MemoryStore,
        stop: Callable[[str], Awaitable[ActivationStop]],
        held_input_limit: int,
        in_progress_limit: int,
        set_up: SetUpRead | None = None,
    ) -> None:
        """Wire the coordinator.

        Args:
            running: The activations the engine holds as running.
            plans: The plan store an absorbed or handed-over activation's stop record is
                written in, and the effect records a peer view reads.
            memory: The store a peer view reads an activation's episode from.
            stop: The Task Manager's stop, which planning's stop call runs (§4:7):
                ``stop_activation``'s one implementation, which stops only the activation
                it names (ADR-0352 §2:1).
            held_input_limit: ``Settings.held_input_limit`` (§9:2).
            in_progress_limit: ``Settings.in_progress_limit`` (§9:3).
            set_up: What a stopped activation set up that is still live, which the stop
                call's result shows (ADR-0352 §3:1); ``None`` shows nothing of it.

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
        self._set_up = set_up
        self.held_input_limit = held_input_limit
        self.in_progress_limit = in_progress_limit
        # Who absorbed each absorbed activation, and who took each handed-over one's
        # input, kept while the chain they start may still reach a running activation.
        self._absorbed: dict[str, str] = {}
        self._handed: dict[str, str] = {}
        # §7:12: each input a reader holds in its start wait, until it is let go.
        self._held: list[HeldInput] = []
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

    def hold(self, place: ChannelIdentity) -> HeldInput:
        """A reader of ``place`` holds an input in its start wait (§7:12, §8:2)."""
        held = HeldInput(place=place, _matters=self)
        self._held.append(held)
        self.changed()
        return held

    def let_go(self, held: HeldInput) -> None:
        """``held`` is no longer held: every wait reads its release."""
        self._held = [one for one in self._held if one is not held]
        self.changed()

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
            parties=state.trigger.parties,
            outside=holds_outside(state.trigger, state.understanding, state.joined),
        )

    # --- the waits (§7:12-§7:16) ---

    def _newer(self, state: ActivationState) -> list[ActivationState]:
        """What an act of ``state``'s waits for, as it runs now (§7:12).

        Each activation started after it, running for the same person with its standing,
        on any place, before it has committed and after (ADR-0361 §7:2: an offer can now
        come from any place). One admitted on a place whose kind establishes its author,
        whose pass has not yet set its standing, may be such an activation, so it is
        waited for until its standing shows it is not (:func:`_waited_out`).
        """
        return [
            one
            for one in self._states()
            if one is not state
            and one.order > state.order
            and _running(one)
            and _may_share(one, state)
        ]

    def _older(self, state: ActivationState) -> list[ActivationState]:
        """What a takeover of ``state``'s waits for, as it runs now (§7:15)."""
        return [
            one
            for one in self._states()
            if one is not state
            and one.order < state.order
            and _running(one)
            and _may_share(one, state)
        ]

    def _held_newer(self, state: ActivationState) -> list[HeldInput]:
        """What an act of ``state``'s waits for of what the readers hold (§7:12).

        Each input a reader of one of its person's places holds in its start wait, before
        it has committed and after (ADR-0361 §7:2). One already admitted
        as a running activation is that activation's, which :meth:`_newer` reads, and
        ``state``'s own input is never among them.
        """
        if state.standing is None or state.standing.author is None:
            # An input whose author is not established meets none (§7:5), so no newer
            # input could absorb it or offer to it.
            return []
        person = person_of(state)
        if person is None:
            return []
        running = {one.activation_id for one in self._states()}
        return [
            one
            for one in self._held
            if not one.released
            and one.activation_id != state.activation_id
            and one.activation_id not in running
            and _held_person(one.place) == person
        ]

    def _held_out(self, held: HeldInput, seen: int, state: ActivationState) -> bool:
        """Whether a wait of ``state``'s need wait for ``held`` no longer (§7:12).

        It was let go, or the activation it was admitted as is waited out as any is. And
        where the wait began having seen, in ``seen``, a notice of a message that then
        moved (:meth:`HeldInput.moved_to`), that message was held when the wait began,
        so the held input it moved to is waited out too. One that moved never moves
        again: it was written before the read it moved to began, so that read took it.
        """
        if not self._one_held_out(held, state):
            return False
        moved = held.then
        if moved is None or seen <= held.moved_after:
            return True
        return self._one_held_out(moved, state)

    def _one_held_out(self, held: HeldInput, state: ActivationState) -> bool:
        """Whether ``held`` itself is let go, or its activation is waited out."""
        if held.released:
            return True
        admitted = held.activation_id
        if admitted is None:
            return False
        one = next((one for one in self._states() if one.activation_id == admitted), None)
        return one is not None and _waited_out(one, state)

    async def before_act(self, state: ActivationState, deadline: float) -> bool:
        """§7:12-§7:13: wait for each newer input that could absorb or offer to ``state``.

        Each newer activation of its standing, and each input a reader holds in its start
        wait (:meth:`_held_newer`). What it waits for is what runs, and what is held, when
        the wait begins, and the wait is bounded by ``deadline``.

        Returns:
            Whether each settled before the deadline.
        """
        waited = self._newer(state)
        # What each held input held when the wait began: the notices it had then.
        held = [(one, one.notices) for one in self._held_newer(state)]
        return await self._until(
            lambda: (
                all(_waited_out(one, state) for one in waited)
                and all(self._held_out(one, seen, state) for one, seen in held)
            ),
            deadline,
        )

    async def before_takeover(self, state: ActivationState, deadline: float) -> bool:
        """§7:15-§7:16: wait once for each older activation's takeover decision.

        Returns:
            Whether each settled before the deadline.
        """
        waited = self._older(state)
        return await self._until(lambda: all(_waited_out(one, state) for one in waited), deadline)

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
        on any place (ADR-0361 §7:1), is offered this activation's input, and any other is
        waited on.

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
            # ADR-0361 §6:3-§6:4: an approval's input is meant for its asking work by
            # code's link, and carries no words and no authority, so §7:5's third
            # condition is not read for it; the asking work has acted, since its request
            # was a write, so it is offered the input and never absorbed.
            linked = state.meant_for is not None and str(named) == state.meant_for
            if (
                other is None
                or other is state
                or reached in seen
                or other.order >= state.order
                or not _running(other)
                or not (linked or _same_matter(other, state))
            ):
                continue
            seen.add(reached)
            (acted if other.committed or linked else absorb).append((decision, other))
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
                # ADR-0361 §7:1: from any place, within one person.
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
                        state=state,
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
    ) -> Answered:
        """Take or decline the offer ``offering_id`` made ``older``, in one step (§7:21).

        A take appends every offered input to the older, naming the offering activation
        and stamped with when it was taken, the instant it joined the older (ADR-0332
        §3), never when the offer was made; sets that activation's stop mark and
        committed mark; and records the hand-over in both takeover decisions. Where the
        offering activation no longer runs with its stop mark unset, the offer is
        withdrawn and nothing changes; where a take would hold more than
        ``held_input_limit``, it is refused and counts as a decline.

        Returns:
            What it came to, with a decline's reason, and why it did not come to what
            was asked, where it did not: a withdrawal says whether the offering
            activation was stopped or ended (ADR-0352 §4:2).
        """
        offer = older.offers.pop(offering_id, None)
        if offer is None:
            return Answered(TakeAnswer.NO_OFFER, not_as_asked=NotAsAsked.NO_OFFER)
        offering = self.state_of(offering_id)
        if offering is None or not _running(offering):
            offer.decision.became = Became.WITHDRAWN
            self.changed()
            # Read from the offering activation's own state, which holds its stop mark
            # after it has ended, as a stop by the control most often has.
            return Answered(
                TakeAnswer.WITHDRAWN,
                not_as_asked=NotAsAsked.STOPPED if offer.state.stopped else NotAsAsked.ENDED,
                meaning=offer.meaning,
            )
        if not take:
            declined = reason.strip() if reason and reason.strip() else "no reason given"
            self._declined(older, offer, declined)
            return Answered(TakeAnswer.DECLINED, declined, meaning=offer.meaning)
        if older.inputs_held + len(offer.inputs) > self.held_input_limit:
            self._declined(older, offer, _LIMIT_REACHED)
            return Answered(
                TakeAnswer.DECLINED,
                _LIMIT_REACHED,
                not_as_asked=NotAsAsked.AT_LIMIT,
                meaning=offer.meaning,
            )
        # Read before anything changes, so nothing it reads can fail the step midway.
        inputs = _marked_now(offer.inputs, offering, taken_at=_taken_at(older))
        offering.stop()
        offering.committed = True
        offering.handed_to = older.activation_id
        offering.offered_to = None
        self._handed[offering_id] = str(older.activation_id)
        older.take_inputs(inputs, merged=(*offering.merged, offering_id))
        older.offers_untaken -= 1
        offer.decision.became = Became.TAKEN
        older.took.append(Named(offering_id, None, Became.TAKEN))
        self.changed()
        return Answered(TakeAnswer.TAKEN, meaning=offer.meaning)

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

        Internal: it stops only that activation, as every stop does (ADR-0352 §2:1). A
        record that cannot be written is logged: the marks are set, so the other
        activation runs no further stage and commits nothing. ``None`` writes it to its
        end.
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
        """The Task Manager's stop, for planning's stop call (§4:7, ADR-0352 §2:1)."""
        return await self._stop(activation_id)

    async def still_live(
        self, activation_id: str, *, viewer: ActivationState, supply: TurnSupply | None
    ) -> StillLive | None:
        """What ``activation_id`` set up that is still live, as ``viewer`` is shown it.

        ADR-0352 §3:1-§3:6, for the stop call's result: read once the stop's record is
        written, or the activation was found ended or stopped. ``None`` where nothing is
        wired to read it, or the viewer is no person's, whom running work is never shown
        (§5:5).
        """
        person = _viewer_person(viewer)
        if self._set_up is None or person is None:
            return None
        return await self._set_up(
            activation_id, person=person, viewer=viewer.activation_id, supply=supply
        )

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
    Each carries its relay mark as ``state`` holds it when this reads it (ADR-0351
    §5:14): the trigger's, by its latest understanding version, and each joined input's
    own, which it keeps.
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
            relayed=relayed_by(state.understanding),
        ),
        *(one.model_copy(update={"taken_over_from": activation_id}) for one in state.joined),
    )


def _taken_at(older: ActivationState) -> datetime | None:
    """When a take is made, by the clock the taking activation was admitted by.

    ``None`` where the state holds no clock, or its reading failed or is no UTC instant:
    the take still runs, and its inputs keep the offer's instant.
    """
    if older.clock is None:
        return None
    try:
        reading = older.clock()
        offset = reading.utcoffset()
    except Exception:  # the take is not the clock's to fail; its inputs keep a stamp
        _log.warning("matter_take_unclocked", stage="acting", reason="clock")
        return None
    if offset is None or offset:
        _log.warning("matter_take_unclocked", stage="acting", reason="not_utc")
        return None
    return reading


def _marked_now(
    inputs: Sequence[JoinedInput], offering: ActivationState, *, taken_at: datetime | None
) -> tuple[JoinedInput, ...]:
    """An offer's inputs as the take appends them: marked and stamped as it reads them.

    The offer was made from what the offering activation held then. A relay mark is never
    dropped (ADR-0351 §5:9), so the take reads it again: the trigger's input, the first,
    is relayed where the offering activation's latest version now marks it (§5:14).

    Each input joins the older activation when the take is made, so each records
    ``taken_at`` as when it joined (ADR-0332 §3), which places it among the older's
    rounds (ADR-0356 §13's ``ProjectedJoin``); ``None`` keeps the offer's instant.
    """
    taken = tuple(
        inputs
        if taken_at is None
        else (one.model_copy(update={"joined_at": taken_at}) for one in inputs)
    )
    if not taken or taken[0].relayed or not relayed_by(offering.understanding):
        return taken
    return (taken[0].model_copy(update={"relayed": True}), *taken[1:])
