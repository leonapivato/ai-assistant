"""ADR-0351's contract in ``core``: an input's parties, what follows from them, and the mark.

The parties each kind declares (§3:1), their shape on the trigger and its messages (§2),
§5's predicates with understanding's relay mark (§5:6-§5:9), a support's holder and
origin on a part of the input (§7), and the fields stored before the decision (§9:6).
Each case is one of §11:1's tests, or a rule the contract lane fixed beside them; each
fails on an implementation that meets only the others.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.channel_validation import (
    TASK_SCHEDULER,
    declared_input,
    message_party,
)
from ai_assistant.core.episode_encoding import project_episode
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActivationUnderstanding,
    ChannelContext,
    ChannelIdentity,
    ChannelTarget,
    ClaimedAuthor,
    EpisodeProcessingRecord,
    EpisodicMemory,
    InputPart,
    JoinedInput,
    MemorySource,
    MemorySupport,
    MemoryWriterName,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    ProposedActivationUnderstanding,
    Provenance,
    RecordedChannelTrigger,
    RecordedInputMessage,
    RecordedTextInput,
    StatementPart,
    SupportDirection,
    SupportHolder,
    SupportOrigin,
    UnderstandingOmission,
    UnderstandingProducer,
    WholeTextReply,
    canonical_parties,
    input_support_origin,
    parties_are_assistants,
    parties_are_outside,
    parties_are_persons_own,
    relay_mark_counts,
    stamped_support,
)
from ai_assistant.testing.activation import ended_pass

_AT: Final = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
_OWNER: Final = SupportHolder.person(OWNER_PERSON_ID)
_SAM: Final = SupportHolder.source("77", claimed=True)
_STATEMENT: Final = SupportHolder.statement(StatementPart.SCHEDULED_INSTRUCTION)
_UNKNOWN: Final = SupportHolder.unknown()

_CHAT: Final = ChannelIdentity(channel_type="conversation", instance_id="c-1")
_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="conn-1/42")
_EVENTS: Final = ChannelIdentity(channel_type="informational_event", instance_id="weather")
_SCHEDULE: Final = ChannelIdentity(channel_type=TASK_SCHEDULER, instance_id="schedule")

_ID: Final = "activation:held"


def _note(position: int = 1) -> RecordedInputMessage:
    return RecordedInputMessage(text="Is this right?", sent_at=_AT, position=position)


def _forward(account: int | None = 77) -> RecordedInputMessage:
    return RecordedInputMessage(
        text="Ana moved to Porto.",
        sent_at=_AT,
        position=2,
        forwarded_from=ClaimedAuthor(name="Sam", account_id=account),
    )


def _understood(version: int, *, relayed: bool) -> ActivationUnderstanding:
    return ActivationUnderstanding(
        version=version,
        recorded_at=_AT,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning="The user asks about Ana.",
        relayed=relayed,
    )


def _episode(
    target: ChannelTarget,
    *messages: RecordedInputMessage,
    marked: bool = False,
    relayed: tuple[bool, ...] = (),
    parties: tuple[SupportHolder, ...] | None = None,
) -> EpisodicMemory:
    """A frozen episode admitted on ``target``, its parties as its kind declares them.

    ``relayed`` gives one understanding version per entry, each marking the input or not;
    none means understanding was omitted. ``parties`` stands in for what admission
    declares, for a record only the upgrade or a refusal case builds.
    """
    declared, recorded = declared_input(target, messages, carries_outside_mark=marked)
    versions = tuple(_understood(n, relayed=one) for n, one in enumerate(relayed, start=1))
    return EpisodicMemory(
        id=_ID,
        content="",
        occurred_at=_AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_AT),
        processing_record=EpisodeProcessingRecord(
            activation_id="held",
            started_at=_AT,
            ended_at=_AT,
            trigger=RecordedChannelTrigger(
                target=target,
                channel=target if isinstance(target, ChannelIdentity) else None,
                payload=RecordedTextInput(text=" ".join(one.text for one in messages) or "hi"),
                context=ChannelContext(),
                reply=WholeTextReply(),
                parties=declared if parties is None else parties,
                messages=recorded if parties is None else messages,
            ),
            status=ProcessingStatus.COMPLETED,
            reason=ProcessingReason.RETURNED,
            understanding=versions,
            understanding_omitted=None if versions else UnderstandingOmission.NOT_REACHED,
            stages=ended_pass(_AT),
        ),
    )


def _processing(episode: EpisodicMemory) -> EpisodeProcessingRecord:
    assert episode.processing_record is not None
    return episode.processing_record


def _support(origin: SupportOrigin, message: int | None = None) -> MemorySupport:
    """A support a write adds on the input or one message: no holder yet (ADR-0345 §2:2)."""
    return MemorySupport(
        points_at=InputPart(episode=_ID, message=message),
        origin=origin,
        direction=SupportDirection.FOR,
        backs_as_worded=True,
        when=_AT,
        added_at=_AT,
        added_by=MemoryWriterName.REMEMBER,
    )


def _stamped(episode: EpisodicMemory, message: int | None) -> tuple[SupportOrigin, SupportHolder]:
    """The origin the part's parties give, and the holder the writer's stamp records."""
    origin = input_support_origin(_processing(episode), message)
    holder = stamped_support(_support(origin, message), episode).holder
    assert holder is not None
    return origin, holder


# --- §3: what each kind declares ---------------------------------------------------------


def test_a_forward_is_its_senders_claimed_words_and_your_note_beside_it_yours() -> None:
    """§2:6, §2:7, §3:1: each message its own party; the input the distinct ones."""
    parties, recorded = declared_input(_LINE, (_note(), _forward()))

    assert [one.party for one in recorded] == [_OWNER, _SAM]
    assert parties == (_OWNER, _SAM)
    _, (unnamed,) = declared_input(_LINE, (_forward(None),))
    assert unnamed.party == _UNKNOWN
    assert message_party("telegram", None) == _OWNER


def test_a_support_on_your_note_is_yours_and_on_the_forward_its_senders() -> None:
    """§7:1, §7:2: ``user_message`` held by you, and ``outside_input`` held by Sam, claimed."""
    episode = _episode(_LINE, _note(), _forward())

    assert _stamped(episode, 0) == (SupportOrigin.USER_MESSAGE, _OWNER)
    assert _stamped(episode, 1) == (SupportOrigin.OUTSIDE_INPUT, _SAM)
    # The input as a whole carries two parties: outside, and held by unknown.
    assert _stamped(episode, None) == (SupportOrigin.OUTSIDE_INPUT, _UNKNOWN)


def test_a_write_naming_another_origin_for_a_part_is_refused() -> None:
    """§7:2: the part's parties set its origin, so no producer calls a forward yours."""
    episode = _episode(_LINE, _note(), _forward())

    with pytest.raises(ValueError, match="takes outside_input, not user_message"):
        stamped_support(_support(SupportOrigin.USER_MESSAGE, 1), episode)
    with pytest.raises(ValueError, match="takes user_message, not outside_input"):
        stamped_support(_support(SupportOrigin.OUTSIDE_INPUT, 0), episode)
    # A holder the producer names changes nothing: the part's parties still decide.
    named = _support(SupportOrigin.USER_MESSAGE, 1).model_copy(update={"holder": _OWNER})
    with pytest.raises(ValueError, match="takes outside_input, not user_message"):
        stamped_support(named, episode)
    # §7:1, §7:5: nor does naming another person for your note.
    sams = _support(SupportOrigin.USER_MESSAGE, 0).model_copy(
        update={"holder": SupportHolder.person("sam")}
    )
    with pytest.raises(ValueError, match="does not give it"):
        stamped_support(sams, episode)


@pytest.mark.parametrize("marked", [False, True], ids=["task", "marked-task"])
def test_a_support_on_a_task_schedulers_input_is_refused(marked: bool) -> None:
    """§3:6, §7:3: the assistant's statement, with unknown on a marked task, backs nothing."""
    episode = _episode(_SCHEDULE, marked=marked)
    assert _processing(episode).trigger.parties == (
        (_STATEMENT, _UNKNOWN) if marked else (_STATEMENT,)
    )

    with pytest.raises(ValueError, match="include the assistant's statement"):
        input_support_origin(_processing(episode), None)
    for origin in (SupportOrigin.USER_MESSAGE, SupportOrigin.OUTSIDE_INPUT):
        with pytest.raises(ValueError, match="include the assistant's statement"):
            stamped_support(_support(origin), episode)
    named = _support(SupportOrigin.OUTSIDE_INPUT).model_copy(update={"holder": _UNKNOWN})
    with pytest.raises(ValueError, match="include the assistant's statement"):
        stamped_support(named, episode)


def test_an_input_mixing_a_person_and_the_assistants_statement_alone_is_refused() -> None:
    """§3:8: refused at admission; with an outside member beside them it is outside."""
    with pytest.raises(ValidationError, match="person and the assistant's statement alone"):
        _episode(_CHAT, parties=(_OWNER, _STATEMENT))

    beside = _episode(_CHAT, parties=(_OWNER, _STATEMENT, _UNKNOWN))
    assert parties_are_outside(_processing(beside).trigger.parties)


def test_an_informational_events_party_is_its_source_established() -> None:
    """§3:5, §7:4: named by its channel's identity, and its support held by it."""
    source = SupportHolder.source("informational_event:weather", claimed=False)
    episode = _episode(_EVENTS)

    assert _processing(episode).trigger.parties == (source,)
    assert _stamped(episode, None) == (SupportOrigin.OUTSIDE_INPUT, source)


def test_the_hub_chat_and_a_new_conversation_are_the_owners_words() -> None:
    """§3:1, §3:2: the one person a party names is the owner."""
    assert declared_input(_CHAT)[0] == (_OWNER,)
    assert declared_input(NewConversation())[0] == (_OWNER,)
    _, (held,) = declared_input(_CHAT, (_note(),))
    assert held.party == _OWNER


@pytest.mark.parametrize(
    ("target", "messages", "marked", "match"),
    [
        (ChannelIdentity(channel_type="door", instance_id="d"), (), False, "its input"),
        (_CHAT, (_forward(),), False, "takes in no forward"),
        (_EVENTS, (_note(),), False, "a message it takes in"),
        (_LINE, (), True, "carrying the mark"),
        (_SCHEDULE, (_note(),), False, "a message it takes in"),
    ],
    ids=["undeclared-type", "forward-on-hub-chat", "message-on-event", "mark-on-line", "task"],
)
def test_a_kind_that_declares_nothing_for_an_input_is_refused_at_admission(
    target: ChannelTarget,
    messages: tuple[RecordedInputMessage, ...],
    marked: bool,
    match: str,
) -> None:
    """§3:1: a channel type, a message, a forward or a mark with no declaration."""
    with pytest.raises(ValueError, match=match):
        declared_input(target, messages, carries_outside_mark=marked)


def test_the_trigger_carries_no_origin_and_its_class_is_read_from_its_parties() -> None:
    """§8:1, §8:2: the origin is gone; outside, the person's own and the assistant's are
    read from the parties the same declaration gives, stored nowhere."""
    assert parties_are_persons_own(declared_input(_CHAT)[0])
    assert parties_are_outside(declared_input(_LINE, (_forward(),))[0])
    assert parties_are_outside(declared_input(_EVENTS)[0])
    assert parties_are_assistants(declared_input(_SCHEDULE)[0])
    assert parties_are_outside(declared_input(_SCHEDULE, carries_outside_mark=True)[0])
    trigger = _processing(_episode(_LINE, _note(), _forward())).trigger
    assert parties_are_outside(trigger.parties)
    assert not hasattr(trigger, "origin")
    assert "origin" not in trigger.model_dump()


# --- §2: the shape ---------------------------------------------------------------------


def test_the_parties_are_carried_once_each_in_the_canonical_order() -> None:
    """§2:3: kind first, then identifier; a member named twice is refused."""
    trigger = _processing(_episode(_CHAT, parties=(_UNKNOWN, _SAM, _OWNER))).trigger
    assert trigger.parties == (_OWNER, _SAM, _UNKNOWN)
    assert canonical_parties((_UNKNOWN, _OWNER, _UNKNOWN)) == (_OWNER, _UNKNOWN)
    with pytest.raises(ValidationError, match="no member twice"):
        _episode(_CHAT, parties=(_OWNER, _OWNER))


@pytest.mark.parametrize(
    ("parties", "messages"),
    [
        ((_OWNER,), (_note().model_copy(update={"party": _OWNER}), _forward())),
        (
            (_OWNER,),
            (
                _note().model_copy(update={"party": _OWNER}),
                _forward(None).model_copy(update={"party": _UNKNOWN}),
            ),
        ),
        ((_OWNER, _SAM), (_note().model_copy(update={"party": _OWNER}),)),
        (None, (_note().model_copy(update={"party": _OWNER}),)),
    ],
    ids=["a-message-with-none", "a-party-it-lacks", "a-party-no-message-carries", "unknown"],
)
def test_the_parties_are_exactly_the_messages_parties(
    parties: tuple[SupportHolder, ...] | None, messages: tuple[RecordedInputMessage, ...]
) -> None:
    """§2:6: each message one of them, together all of them; ``None`` on every one."""
    with pytest.raises(ValidationError, match=r"ADR-0351 §2:6"):
        RecordedChannelTrigger(
            target=_LINE,
            channel=_LINE,
            payload=RecordedTextInput(text="hi"),
            context=ChannelContext(),
            reply=WholeTextReply(),
            parties=parties,
            messages=messages,
        )


def test_a_forward_carries_no_party_but_its_senders() -> None:
    """§2:7: never the owner's, whatever its name, and unknown only where the medium names none."""
    with pytest.raises(ValidationError, match="its sender, claimed"):
        RecordedInputMessage.model_validate(_forward().model_dump() | {"party": _OWNER})
    with pytest.raises(ValidationError, match="its sender, claimed"):
        RecordedInputMessage.model_validate(_forward().model_dump() | {"party": _UNKNOWN})
    assert RecordedInputMessage.model_validate(_forward().model_dump() | {"party": None})


# --- §5: what follows ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("parties", "relayed", "follows"),
    [
        ((_OWNER,), False, (False, True, False)),
        ((_OWNER,), True, (True, False, False)),
        ((_STATEMENT,), False, (False, False, True)),
        ((_STATEMENT,), True, (True, False, False)),
        ((_SAM,), False, (True, False, False)),
        ((_SAM,), True, (True, False, False)),
        ((_OWNER, _SAM), True, (True, False, False)),
        ((), False, (False, False, False)),
        ((), True, (False, False, False)),
        (None, False, (True, False, False)),
        (None, True, (True, False, False)),
    ],
    ids=[
        "yours",
        "yours-relayed",
        "the-assistants",
        "the-assistants-relayed",
        "a-forward",
        "a-forward-relayed",
        "note-and-forward-relayed",
        "no-ones",
        "no-ones-relayed",
        "unknown",
        "unknown-relayed",
    ],
)
def test_outside_the_persons_own_and_the_assistants_follow_from_the_parties(
    parties: tuple[SupportHolder, ...] | None, relayed: bool, follows: tuple[bool, bool, bool]
) -> None:
    """§5:1, §5:2, §5:7: ``None`` is outside; a mark lowers only yours or the assistant's."""
    assert (
        parties_are_outside(parties, relayed=relayed),
        parties_are_persons_own(parties, relayed=relayed),
        parties_are_assistants(parties, relayed=relayed),
    ) == follows
    assert relay_mark_counts(parties, relayed=relayed) == (
        relayed and parties in ((_OWNER,), (_STATEMENT,))
    )


def test_unknown_parties_read_as_outside_and_every_part_of_them_is_held_by_unknown() -> None:
    """§2:5, §5:1, §7:1, §7:2: ``None`` parties, and each message's party ``None``."""
    stored = _episode(_LINE, _note(), _forward()).model_dump(mode="json")
    stored["processing_record"]["trigger"]["parties"] = None
    for one in stored["processing_record"]["trigger"]["messages"]:
        one["party"] = None
    episode = EpisodicMemory.model_validate(stored)

    assert parties_are_outside(_processing(episode).trigger.parties)
    for message in (None, 0, 1):
        assert _stamped(episode, message) == (SupportOrigin.OUTSIDE_INPUT, _UNKNOWN)


# --- §5:6-§5:14: the relay mark --------------------------------------------------------


def test_a_relayed_input_and_its_messages_are_held_by_unknown_and_an_unmarked_one_by_you() -> None:
    """§5:7, §7:6: ``outside_input`` held by unknown; unmarked, ``user_message`` held by you."""
    relayed = _episode(_LINE, _note(1), _note(2), relayed=(True,))
    for message in (None, 0, 1):
        assert _stamped(relayed, message) == (SupportOrigin.OUTSIDE_INPUT, _UNKNOWN)
    with pytest.raises(ValueError, match="takes outside_input, not user_message"):
        stamped_support(_support(SupportOrigin.USER_MESSAGE, 0), relayed)

    plain = _episode(_LINE, _note(1), _note(2), relayed=(False,))
    for message in (None, 0, 1):
        assert _stamped(plain, message) == (SupportOrigin.USER_MESSAGE, _OWNER)
    omitted = _episode(_CHAT)
    assert _stamped(omitted, None) == (SupportOrigin.USER_MESSAGE, _OWNER)


def test_the_latest_version_carries_the_relay_mark_the_holder_reads() -> None:
    """§5:11: a later version marking it is what a support on the input reads."""
    later = _episode(_CHAT, relayed=(False, True))
    assert _stamped(later, None) == (SupportOrigin.OUTSIDE_INPUT, _UNKNOWN)


def test_a_relay_mark_on_a_task_schedulers_input_leaves_its_support_refused() -> None:
    """§7:3, §7:6: the mark makes the input outside, and it still backs nothing."""
    episode = _episode(_SCHEDULE, relayed=(True,))
    assert parties_are_outside(_processing(episode).trigger.parties, relayed=True)

    with pytest.raises(ValueError, match="include the assistant's statement"):
        input_support_origin(_processing(episode), None)


def test_a_relay_mark_on_an_input_carrying_a_forward_changes_nothing() -> None:
    """§5:7: the parties already say whose the words are, so each keeps its holder."""
    episode = _episode(_LINE, _note(), _forward(), relayed=(True,))

    assert _stamped(episode, 0) == (SupportOrigin.USER_MESSAGE, _OWNER)
    assert _stamped(episode, 1) == (SupportOrigin.OUTSIDE_INPUT, _SAM)


def test_a_record_in_which_a_later_version_drops_a_relay_mark_is_refused() -> None:
    """§5:9: the mark holds for the rest of the activation."""
    with pytest.raises(ValidationError, match="never drops a relay mark"):
        _episode(_CHAT, relayed=(True, False))
    with pytest.raises(ValidationError, match="never drops a relay mark"):
        _episode(_CHAT, relayed=(False, True, False))
    assert _episode(_CHAT, relayed=(True, True))


def test_a_version_and_a_joined_input_stored_before_the_fields_mark_nothing() -> None:
    """§9:6: each validates unchanged and reads as unmarked."""
    version = _understood(1, relayed=False).model_dump(mode="json")
    del version["relayed"]
    joined = JoinedInput(
        joined_at=_AT, channel=_LINE, messages=(_note().model_copy(update={"party": _OWNER}),)
    ).model_dump(mode="json")
    del joined["relayed"]
    proposal = {"understanding": "m"}

    assert not ActivationUnderstanding.model_validate(version).relayed
    assert not JoinedInput.model_validate(joined).relayed
    assert not ProposedActivationUnderstanding.model_validate(proposal).relayed


def test_a_joined_inputs_messages_all_carry_a_party_or_none_does() -> None:
    """§2:6, §9:3: as a trigger's do."""
    with pytest.raises(ValidationError, match="all carry a party, or none does"):
        JoinedInput(
            joined_at=_AT,
            channel=_LINE,
            messages=(_note().model_copy(update={"party": _OWNER}), _note(2)),
        )
    assert JoinedInput(joined_at=_AT, channel=_LINE, messages=(_note(), _note(2)))


def test_the_projection_carries_the_parties_and_the_latest_relay_mark() -> None:
    """§8:4, §10:4: in place of the origin; the relay mark makes the input outside."""
    relayed = project_episode(_episode(_CHAT, relayed=(True,)), excerpt_chars=40)
    plain = project_episode(_episode(_CHAT, relayed=(False,)), excerpt_chars=40)

    assert (relayed.parties, relayed.relayed) == ((_OWNER,), True)
    assert (plain.parties, plain.relayed) == ((_OWNER,), False)
    assert parties_are_outside(relayed.parties, relayed=relayed.relayed)
    assert not parties_are_persons_own(relayed.parties, relayed=relayed.relayed)
    assert relayed.input is None
    assert parties_are_persons_own(plain.parties, relayed=plain.relayed)
    assert plain.input is not None
