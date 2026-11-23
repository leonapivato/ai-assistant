"""Who sent an input, and a work's three facts, as ``core`` types hold them (ADR-0368 §2).

``InputSender`` is who sent an input or a message (ADR-0366 §4:1, §5:6; ADR-0368 §2:6);
``WorkFacts`` with ``WorkFor`` and ``WorkAuthority`` are the three facts (§2:1 to §2:3).
Each value the decision names is expressible, a group, several senders, an unidentified
sender, an author in advance and no one among them, and each shape the decision rules out
is refused. The trigger, its messages and a joined input record senders as ADR-0368 §2:6
places them, and a processing record its facts and, through its joined inputs, the facts
as they stand.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    AuthorityKind,
    ChannelContext,
    ChannelIdentity,
    EpisodeProcessingRecord,
    InputSender,
    JoinedInput,
    RecordedChannelTrigger,
    RecordedInputMessage,
    RecordedTextInput,
    Sureness,
    WorkAuthority,
    WorkFacts,
    WorkFor,
    WorkForKind,
    canonical_senders,
    senders_level,
)
from ai_assistant.testing.parties import OWNERS_WORDS

_AT: Final = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="conn-1:42")
_SAM: Final = "person:sam"

_OWNER: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL)
_NO_LINK: Final = InputSender(person=None, level=Sureness.NONE)


def _message(text: str = "hello", *, sender: InputSender | None = _OWNER) -> RecordedInputMessage:
    return RecordedInputMessage(text=text, sent_at=_AT, party=OWNERS_WORDS[0], sender=sender)


def _trigger(
    *,
    messages: tuple[RecordedInputMessage, ...] = (),
    senders: tuple[InputSender, ...] = (),
) -> RecordedChannelTrigger:
    return RecordedChannelTrigger(
        target=_LINE,
        channel=_LINE,
        payload=RecordedTextInput(text="hello"),
        context=ChannelContext(),
        reply=None,
        parties=OWNERS_WORDS,
        messages=messages,
        senders=senders,
    )


# --- who sent it ----------------------------------------------------------------------


def test_a_sender_no_link_ties_is_at_none() -> None:
    """ADR-0366 §5:6: an input that arrived by no link is at none."""
    assert not _NO_LINK.identified
    with pytest.raises(ValidationError, match="at none"):
        InputSender(person=None, level=Sureness.NORMAL)


def test_identified_is_a_person_at_weak_or_above() -> None:
    """ADR-0368 §9:4: established is weak or above; a link lowered to none is not."""
    assert _OWNER.identified
    assert InputSender(person=OWNER_PERSON_ID, level=Sureness.WEAK).identified
    assert not InputSender(person=OWNER_PERSON_ID, level=Sureness.NONE).identified


def test_canonical_senders_names_each_person_once_at_their_lowest() -> None:
    """ADR-0368 §4:1: one entry per person, at the lowest level, people then no person."""
    weak = InputSender(person=OWNER_PERSON_ID, level=Sureness.WEAK)
    sam = InputSender(person=_SAM, level=Sureness.NORMAL)
    assert canonical_senders([_NO_LINK, _OWNER, sam, weak, _NO_LINK]) == (weak, sam, _NO_LINK)
    assert canonical_senders([]) == ()
    assert senders_level([_OWNER, weak]) is Sureness.WEAK
    assert senders_level([]) is None


def test_a_trigger_records_its_senders_beside_its_author() -> None:
    """ADR-0368 §2:6: on the trigger, canonical, and exactly its messages' where it
    records messages."""
    held = _trigger(messages=(_message(), _message("again")), senders=(_OWNER,))
    assert held.senders == (_OWNER,)
    assert _trigger().senders == ()
    with pytest.raises(ValidationError, match="exactly its messages"):
        _trigger(messages=(_message(),), senders=())
    with pytest.raises(ValidationError, match="each person once"):
        _trigger(senders=(_NO_LINK, _OWNER))
    with pytest.raises(ValidationError, match="all record their sender"):
        _trigger(messages=(_message(), _message(sender=None)), senders=(_OWNER,))


def test_a_trigger_with_no_messages_records_its_senders_alone() -> None:
    """The hub chat's trigger records no messages, so it carries its senders itself."""
    assert _trigger(senders=(_OWNER, _NO_LINK)).senders == (_OWNER, _NO_LINK)


def test_a_joined_input_records_its_messages_senders() -> None:
    """ADR-0368 §2:6: each message of a joined input records its sender, or none does."""
    joined = JoinedInput(joined_at=_AT, channel=_LINE, messages=(_message(),))
    assert joined.senders == (_OWNER,)
    with pytest.raises(ValidationError, match="all record their sender"):
        JoinedInput(joined_at=_AT, channel=_LINE, messages=(_message(), _message(sender=None)))


# --- the three facts --------------------------------------------------------------------


def test_whom_a_work_is_for_is_a_person_a_group_or_no_one() -> None:
    """ADR-0368 §2:1: each named by its id, and no one by none."""
    assert WorkFor.for_person(OWNER_PERSON_ID).id == OWNER_PERSON_ID
    assert WorkFor(kind=WorkForKind.GROUP, id="group:household").kind is WorkForKind.GROUP
    assert WorkFor.no_one().id is None
    with pytest.raises(ValidationError):
        WorkFor(kind=WorkForKind.PERSON)
    with pytest.raises(ValidationError):
        WorkFor(kind=WorkForKind.NO_ONE, id=OWNER_PERSON_ID)


def test_whose_authority_names_whom_its_kind_names() -> None:
    """ADR-0368 §2:2: its senders, each identified or not; one person in advance; none."""
    several = WorkAuthority(
        kind=AuthorityKind.SENDERS, persons=(OWNER_PERSON_ID, _SAM), unidentified=True
    )
    assert several.carries_a_persons
    assert WorkAuthority(kind=AuthorityKind.SENDERS, unidentified=True).carries_a_persons is False
    assert WorkAuthority(kind=AuthorityKind.IN_ADVANCE, persons=(_SAM,)).carries_a_persons
    assert not WorkAuthority.none().carries_a_persons
    for kind, persons, unidentified in (
        (AuthorityKind.SENDERS, (), False),
        (AuthorityKind.IN_ADVANCE, (), False),
        (AuthorityKind.IN_ADVANCE, (OWNER_PERSON_ID, _SAM), False),
        (AuthorityKind.IN_ADVANCE, (_SAM,), True),
        (AuthorityKind.NONE, (_SAM,), False),
        (AuthorityKind.NONE, (), True),
        (AuthorityKind.SENDERS, (_SAM, OWNER_PERSON_ID), False),
        (AuthorityKind.SENDERS, (_SAM, _SAM), False),
    ):
        with pytest.raises(ValidationError):
            WorkAuthority(kind=kind, persons=persons, unidentified=unidentified)


def test_a_work_is_at_the_level_its_senders_allow() -> None:
    """ADR-0368 §4:1, §9:4: an unidentified sender's work is at none, and one carrying only
    identified senders' authority is above it."""
    whom = WorkFor.for_person(OWNER_PERSON_ID)
    anyone = WorkAuthority(kind=AuthorityKind.SENDERS, unidentified=True)
    owners = WorkAuthority(kind=AuthorityKind.SENDERS, persons=(OWNER_PERSON_ID,))
    assert WorkFacts(for_whom=whom, authority=anyone, level=Sureness.NONE)
    assert WorkFacts(for_whom=whom, authority=owners, level=Sureness.WEAK)
    assert WorkFacts(for_whom=whom, authority=WorkAuthority.none(), level=Sureness.NORMAL)
    with pytest.raises(ValidationError, match="at none"):
        WorkFacts(for_whom=whom, authority=anyone, level=Sureness.NORMAL)
    with pytest.raises(ValidationError, match="above none"):
        WorkFacts(for_whom=whom, authority=owners, level=Sureness.NONE)


def test_the_record_keeps_the_facts_and_its_joins_the_facts_as_they_stand() -> None:
    """ADR-0368 §2:4: recorded when the work starts, and again when an input joins it."""
    started = WorkFacts(
        for_whom=WorkFor.for_person(OWNER_PERSON_ID),
        authority=WorkAuthority(kind=AuthorityKind.SENDERS, persons=(OWNER_PERSON_ID,)),
        level=Sureness.NORMAL,
    )
    lowered = started.model_copy(update={"level": Sureness.WEAK})
    trigger = _trigger(messages=(_message(),), senders=(_OWNER,))
    record = EpisodeProcessingRecord(
        activation_id="act-1", started_at=_AT, trigger=trigger, facts=started
    )
    assert record.facts_now == started
    joined = record.model_copy(
        update={
            "joined": (
                JoinedInput(joined_at=_AT, channel=_LINE, messages=(_message(),), facts=lowered),
                JoinedInput(joined_at=_AT, channel=_LINE, messages=(_message(sender=None),)),
            )
        }
    )
    assert joined.facts == started
    assert joined.facts_now == lowered
    assert (
        EpisodeProcessingRecord(activation_id="act-2", started_at=_AT, trigger=trigger).facts_now
        is None
    )
