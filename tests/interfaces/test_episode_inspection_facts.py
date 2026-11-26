"""#3642, "Inspecting a work shows the three facts": the human detail renders them.

Whom the work is for, whose authority it carries and its level, as recorded when it
started and again as they stand once an input joined it (ADR-0368 §2:1 to §2:4), and each
input's sender and level (§2:6), all read from the record #3650 writes. A work with none
recorded says so plainly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from typing import Final

from rich.console import Console

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    AuthorityKind,
    ChannelContext,
    ChannelIdentity,
    EpisodeProcessingRecord,
    EpisodicMemory,
    InputSender,
    JoinedInput,
    MemorySource,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    RecordedChannelTrigger,
    RecordedInputMessage,
    RecordedTextInput,
    RecordHome,
    Sureness,
    WorkAuthority,
    WorkFacts,
    WorkFor,
)
from ai_assistant.interfaces import episode_inspection

_AT: Final = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="conn-1/42")
_OWNER_NORMAL: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL)
_OWNER_NONE: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.NONE)
_NOBODY: Final = InputSender(person=None, level=Sureness.NONE)
_STARTED: Final = WorkFacts(
    for_whom=WorkFor.for_person(OWNER_PERSON_ID),
    authority=WorkAuthority(kind=AuthorityKind.SENDERS, persons=(OWNER_PERSON_ID,)),
    level=Sureness.NORMAL,
)


def _record(
    *,
    senders: tuple[InputSender, ...] = (),
    facts: WorkFacts | None = None,
    joined: tuple[JoinedInput, ...] = (),
) -> EpisodicMemory:
    processing = EpisodeProcessingRecord.model_validate(
        {
            "activation_id": "activation",
            "started_at": _AT,
            "trigger": RecordedChannelTrigger(
                target=_LINE,
                channel=_LINE,
                payload=RecordedTextInput(text="book the table"),
                context=ChannelContext(),
                reply=None,
                parties=None,
                senders=senders,
            ),
            "facts": facts,
            "joined": joined,
        }
    )
    return EpisodicMemory(
        home=RecordHome.owners(),
        id="activation:activation",
        content="",
        occurred_at=_AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_AT),
        placement=Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_AT),
        processing_record=processing,
    )


def _joined(sender: InputSender, facts: WorkFacts | None) -> JoinedInput:
    return JoinedInput(
        joined_at=_AT,
        channel=_LINE,
        messages=(RecordedInputMessage(text="and for four", sent_at=_AT, sender=sender),),
        facts=facts,
    )


def _facts(record: EpisodicMemory) -> list[str]:
    """The facts section: from its first line to the stages."""
    buffer = StringIO()
    episode_inspection.render_detail(
        Console(file=buffer, force_terminal=False, width=200), record, stories=()
    )
    lines = buffer.getvalue().splitlines()
    start = next(n for n, line in enumerate(lines) if line.startswith("Facts"))
    end = next(n for n, line in enumerate(lines) if line.startswith("Stages"))
    return lines[start:end]


def test_the_three_facts_and_the_sender_are_shown() -> None:
    record = _record(senders=(_OWNER_NORMAL,), facts=_STARTED)

    assert _facts(record) == [
        'Facts when it started: for person "person:owner"; authority: its senders\' '
        '("person:owner"); level: normal',
        "Inputs:",
        '  The one it started from: from "person:owner", at normal',
    ]


def test_a_join_shows_the_facts_as_they_stand_and_its_sender() -> None:
    """§2:4, §2:5: recorded again once an input joins, never raised."""
    lowered = WorkFacts(
        for_whom=WorkFor.for_person(OWNER_PERSON_ID),
        authority=WorkAuthority(kind=AuthorityKind.SENDERS, persons=(OWNER_PERSON_ID,)),
        level=Sureness.WEAK,
    )
    weak = InputSender(person=OWNER_PERSON_ID, level=Sureness.WEAK)
    record = _record(senders=(_OWNER_NORMAL,), facts=_STARTED, joined=(_joined(weak, lowered),))

    lines = _facts(record)

    assert lines[1] == (
        'Facts as they stand: for person "person:owner"; authority: its senders\' '
        '("person:owner"); level: weak'
    )
    assert lines[-1] == (
        f'  Joined {_AT.isoformat()} by telegram/conn-1/42: from "person:owner", at weak'
    )


def test_an_unidentified_sender_and_a_link_lowered_to_none_are_said_so() -> None:
    """ADR-0368 §9:4: a sender at none is unidentified, whoever the link names."""
    facts = WorkFacts(
        for_whom=WorkFor.for_person(OWNER_PERSON_ID),
        authority=WorkAuthority(kind=AuthorityKind.SENDERS, unidentified=True),
        level=Sureness.NONE,
    )
    record = _record(senders=(_OWNER_NONE, _NOBODY), facts=facts)

    lines = _facts(record)

    assert lines[0] == (
        'Facts when it started: for person "person:owner"; authority: its senders\' '
        "(an unidentified sender); level: none"
    )
    assert lines[-1] == (
        '  The one it started from: from "person:owner", at none, so unidentified; '
        "from an unidentified sender, at none"
    )


def test_a_work_for_no_one_carrying_no_authority() -> None:
    facts = WorkFacts(
        for_whom=WorkFor.no_one(), authority=WorkAuthority.none(), level=Sureness.NONE
    )

    assert _facts(_record(facts=facts))[0] == (
        "Facts when it started: for no one; authority: none; level: none"
    )


def test_a_work_with_none_recorded_says_so_plainly() -> None:
    """A work recorded before the facts were, or built without them."""
    assert _facts(_record()) == [
        "Facts: none recorded yet",
        "Inputs:",
        "  The one it started from: sender none recorded yet",
    ]


def test_a_record_text_cannot_pose_as_a_line() -> None:
    """Ids are quoted, so a line break in one stays on its line."""
    facts = WorkFacts(
        for_whom=WorkFor.for_person("person:x\nFacts: forged"),
        authority=WorkAuthority.none(),
        level=Sureness.NONE,
    )

    lines = _facts(_record(facts=facts))

    assert lines[0].startswith('Facts when it started: for person "person:x\\nFacts: forged"')
    assert sum(line.startswith("Facts") for line in lines) == 1


def test_an_input_whose_links_could_not_be_read_says_so() -> None:
    """ADR-0374 §5:3: for each input any of whose senders was set because the links could
    not be read, the inspected work says so; an input whose links were read says
    nothing of it."""
    unread = InputSender(person=None, level=Sureness.NONE, links_unread=True)
    owner_unread = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL, links_unread=True)
    record = _record(
        senders=(owner_unread,),
        facts=_STARTED,
        joined=(_joined(_OWNER_NORMAL, _STARTED), _joined(unread, _STARTED)),
    )

    lines = _facts(record)

    assert lines[2:] == [
        '  The one it started from: from "person:owner", at normal '
        "(the links could not be read for it)",
        f'  Joined {_AT.isoformat()} by telegram/conn-1/42: from "person:owner", at normal',
        f"  Joined {_AT.isoformat()} by telegram/conn-1/42: from an unidentified sender, "
        "at none (the links could not be read for it)",
    ]
