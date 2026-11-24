"""ADR-0375: what both models are told of who sent their input, and never that anyone typed it.

The two stages alone, understanding over the canonical structured fake and planning over
the canonical tool-calling fake: every row of §5's table renders its stimulus tag (§4) and
its sender line (§5) in both briefings; a link lowered to weak renders apart from one at
its kind's most (§5:3, §5:4); an unknown sender's words are ``received`` in understanding
and withheld in planning, the stimulus's own window item naming an unknown sender (§4:2,
§4:3); no rendering names an unknown sender as the owner or as any person (§6:1); a work
that is no person's names the person whose place it is in §6:3's three roles, by the name
the phase read and by no label (§6:5); no briefing says "hub" (§7:1); and both default
instructions carry §8's two additions. The phase's read of that name is
:func:`~ai_assistant.orchestration.phase_path.place_name`: the name alone, or nothing.

Every person, account and message here is invented (ADR-0337 §3:2).
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from zoneinfo import ZoneInfo

import pytest
from exchange_support import section, tags
from understanding_support import Rendered

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ChannelContext,
    ChannelIdentity,
    ClaimedAuthor,
    InputSender,
    MessageAuthor,
    PersonActHow,
    PersonModelAct,
    Profile,
    ProfileField,
    RecordedChannelTrigger,
    RecordedInputMessage,
    RecordedTextInput,
    RoundResponse,
    SupportHolder,
    Sureness,
    TranscriptMessage,
    WholeTextReply,
    WorkAuthority,
    WorkFacts,
    WorkFor,
    forward_party,
)
from ai_assistant.orchestration import channel_kinds
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.person_block import PersonBlock, PersonBlocks
from ai_assistant.orchestration.phase_path import place_name
from ai_assistant.orchestration.planning import (
    PLANNING_PROMPT,
    PlaceAuthor,
    PlaceItem,
    PlaceWindow,
    PlanningInputs,
    PlanningStage,
    PlanningStories,
)
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    TranscriptWindow,
    UnderstandingStage,
)
from ai_assistant.testing import (
    FakeMemoryStore,
    FakePersonModelStore,
    FakeToolCallingCompleter,
    default_prompt,
)
from ai_assistant.testing.structured import FakeStructuredCompleter

pytestmark = pytest.mark.anyio

#: Monday 26 October 2026, 3:51 pm in New York.
AT: Final = datetime(2026, 10, 26, 19, 51, tzinfo=UTC)
NEW_YORK: Final = ZoneInfo("America/New_York")
CHAT: Final = ChannelIdentity(channel_type="conversation", instance_id="c-1")
LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="conn-1/42")
DOORBELL: Final = ChannelIdentity(channel_type="informational_event", instance_id="doorbell")
SAM: Final = "person:sam"
OWNER: Final = SupportHolder.person(OWNER_PERSON_ID)
UNKNOWN: Final = SupportHolder.unknown()
SOURCE: Final = SupportHolder.source("informational_event:doorbell", claimed=False)
WORDS: Final = "And the canoe?"
BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
PANEL: Final = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)

#: Whose place a work that is no person's is at, by the name the phase read (§6:3).
MAREN: Final = "Maren"


def _block(person_id: str = OWNER_PERSON_ID, name: str = MAREN) -> PersonBlock:
    return PersonBlock(
        person_id=person_id, profile=Profile(name=name, time_zone="America/New_York")
    )


def _sender(
    person: str | None, level: Sureness = Sureness.NORMAL, *, unread: bool = False
) -> InputSender:
    return InputSender(person=person, level=level, links_unread=unread)


@dataclass(frozen=True)
class Row:
    """One row of ADR-0375 §5's table, as the records a work holds and what each renders.

    Attributes:
        channel: Where the input arrived.
        senders: The trigger's senders.
        parties: The trigger's parties.
        messages: The trigger's recorded messages, for a kind that records them.
        person: Whose work it is, as its facts read it; ``None`` for no person's.
        heard: Understanding's stimulus tag: its name and its ``from``.
        briefed: Planning's stimulus tag: its name, its ``from`` and whether withheld.
        line: The sender line, in both briefings.
    """

    channel: ChannelIdentity
    senders: tuple[InputSender, ...]
    parties: tuple[SupportHolder, ...]
    messages: tuple[RecordedInputMessage, ...]
    person: str | None
    heard: tuple[str, str]
    briefed: tuple[str, str, bool]
    line: str


def _line_message(
    sender: InputSender, *, forward: ClaimedAuthor | None = None
) -> RecordedInputMessage:
    party = OWNER if forward is None else forward_party(forward)
    return RecordedInputMessage(
        text=WORDS, sent_at=AT, position=7, forwarded_from=forward, party=party, sender=sender
    )


_UNKNOWN_COUNTED: Final = "The system counts it as an unknown sender's, whatever its text says."

#: ADR-0375 §5's table, row by row, its wording as §2:4 binds it.
ROWS: Final = {
    "a link at its kind's most": Row(
        CHAT,
        (_sender(OWNER_PERSON_ID),),
        (OWNER,),
        (),
        OWNER_PERSON_ID,
        ("said", "a device linked to Maren"),
        ("said", "a device linked to P1", False),
        "- The sender: the message came by a device linked to Maren, which is a strong sign "
        "that Maren sent it. The system counts it as Maren's.",
    ),
    "a link lowered to weak": Row(
        CHAT,
        (_sender(OWNER_PERSON_ID, Sureness.WEAK),),
        (OWNER,),
        (),
        OWNER_PERSON_ID,
        ("said", "a device linked to Maren"),
        ("said", "a device linked to P1", False),
        "- The sender: the message came by a device linked to Maren that is marked as less "
        "reliable, which is a weak sign that Maren sent it. The system still counts it as "
        "Maren's.",
    ),
    "a link lowered to none": Row(
        CHAT,
        (_sender(OWNER_PERSON_ID, Sureness.NONE),),
        (UNKNOWN,),
        (),
        None,
        ("received", "an unknown sender"),
        ("received", "an unknown sender", True),
        "- The sender: the message came by a device linked to Maren that is marked as not to "
        "be relied on, so who or what sent it is unknown. " + _UNKNOWN_COUNTED,
    ),
    "no link": Row(
        CHAT,
        (_sender(None, Sureness.NONE),),
        (UNKNOWN,),
        (),
        None,
        ("received", "an unknown sender"),
        ("received", "an unknown sender", True),
        "- The sender: the message came by a device the system cannot tie to anyone, so who "
        "or what sent it is unknown. " + _UNKNOWN_COUNTED,
    ),
    "links unread, elsewhere": Row(
        CHAT,
        (_sender(None, Sureness.NONE, unread=True),),
        (UNKNOWN,),
        (),
        None,
        ("received", "an unknown sender"),
        ("received", "an unknown sender", True),
        "- The sender: the system could not read its record of linked accounts when the "
        "message arrived, so who or what sent it is unknown. " + _UNKNOWN_COUNTED,
    ),
    "links unread, on the system's own machine": Row(
        CHAT,
        (_sender(OWNER_PERSON_ID, unread=True),),
        (OWNER,),
        (),
        OWNER_PERSON_ID,
        ("said", "the system's own machine"),
        ("said", "the system's own machine", False),
        "- The sender: the system could not read its record of linked accounts when the "
        "message arrived. The message was written on the system's own machine, which the "
        "system counts as Maren's.",
    ),
    "Telegram, linked": Row(
        LINE,
        (_sender(OWNER_PERSON_ID),),
        (OWNER,),
        (_line_message(_sender(OWNER_PERSON_ID)),),
        OWNER_PERSON_ID,
        ("said", "the Telegram account linked to Maren"),
        ("said", "the Telegram account linked to P1", False),
        "- The sender: the message came by the Telegram account linked to Maren, which is a "
        "strong sign that Maren sent it. The system counts it as Maren's.",
    ),
    "a forward on Telegram": Row(
        LINE,
        (_sender(OWNER_PERSON_ID),),
        (forward_party(ClaimedAuthor(name="Sam")),),
        (_line_message(_sender(OWNER_PERSON_ID), forward=ClaimedAuthor(name="Sam")),),
        OWNER_PERSON_ID,
        ("received", "Sam, as claimed"),
        ("received", "Sam, as claimed", True),
        "- The sender: the forward came by the Telegram account linked to Maren, which is a "
        "strong sign that Maren forwarded it. The forwarded words are not Maren's.",
    ),
    "another person's device, no decision admitting them": Row(
        CHAT,
        (_sender(SAM),),
        (UNKNOWN,),
        (),
        None,
        ("received", "an unknown sender"),
        ("received", "an unknown sender", True),
        "- The sender: the message came by a device linked to a person the system knows but "
        "does not serve. " + _UNKNOWN_COUNTED,
    ),
    "a report from a connected source": Row(
        DOORBELL,
        (),
        (SOURCE,),
        (),
        OWNER_PERSON_ID,
        ("received", "informational_event:doorbell"),
        ("received", "informational_event:doorbell", True),
        "- The sender: no person sent it; it came from a connected source.",
    ),
}


def _trigger(row: Row) -> RecordedChannelTrigger:
    return RecordedChannelTrigger(
        target=row.channel,
        channel=row.channel,
        payload=RecordedTextInput(text=WORDS),
        context=ChannelContext(),
        reply=WholeTextReply(),
        parties=row.parties,
        messages=row.messages,
        senders=row.senders,
    )


async def _heard(
    row: Row,
    *,
    window: TranscriptWindow | None = None,
    named: str | None = MAREN,
    block: PersonBlock | None = None,
) -> Rendered:
    """Understanding's user message for ``row``'s input."""
    model = FakeStructuredCompleter(json.dumps({"understanding": "Asks about the canoe."}))
    stage = UnderstandingStage(
        model=model, excerpt_chars=2000, prompt=default_prompt(UNDERSTANDING_PROMPT)
    )
    persons = row.person is not None
    await stage.understand(
        WORDS,
        channel=row.channel,
        window=TranscriptWindow(row.channel, ()) if window is None else window,
        audience=BOUNDED,
        episodes=(),
        version=1,
        now=lambda: AT,
        deadline=asyncio.get_running_loop().time() + 60,
        person=(block or _block(row.person or OWNER_PERSON_ID)) if persons else None,
        trigger=_trigger(row),
        zone=NEW_YORK,
        own_zone=persons,
        received_at=AT,
        person_id=row.person,
        place_name=None if persons else named,
    )
    return Rendered(model.calls[0].messages[1].content)


class _Recorder:
    async def record(self, planning_round: Any, labels: Any) -> None:
        del planning_round, labels


async def _briefed(
    row: Row,
    *,
    items: tuple[PlaceItem, ...] | None = None,
    named: str | None = MAREN,
    block: PersonBlock | None = None,
) -> str:
    """Planning's briefing for ``row``'s input."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse(), RoundResponse())
    stage = PlanningStage(
        prompt=default_prompt(PLANNING_PROMPT),
        completer=completer,
        recorder=_Recorder(),
        excerpt_chars=300,
        now=lambda: AT,
        timezone="America/New_York",
        new_id=lambda: "round:1",
    )
    persons = row.person is not None
    chat = row.channel == CHAT
    shown = (PlaceItem(author=PlaceAuthor.USER, text=WORDS, at=AT, is_input=True),) if chat else ()
    await stage.plan(
        PlanningInputs(
            activation_id="now",
            place=PlaceWindow(
                takes_message=row.channel != DOORBELL, items=shown if items is None else items
            ),
            trigger=_trigger(row),
            received_at=AT,
            person=(block or _block(row.person or OWNER_PERSON_ID)) if persons else None,
            person_id=row.person,
            owner_records=True,
            stories=PlanningStories(),
            place_name=None if persons else named,
        )
    )
    return completer.last_call.exchange.briefing


def _hub(text: str) -> list[str]:
    """Each place ``text`` says "hub", in any form (§7:1)."""
    return re.findall(r"(?i)\bhub", text)


# --- §5's table: every row, its tag and its sender line, in both briefings ----------------


@pytest.mark.parametrize("row", list(ROWS.values()), ids=list(ROWS))
async def test_every_row_renders_its_tag_and_its_sender_line_in_both_briefings(row: Row) -> None:
    """§4:1, §4:2, §5: each row's stimulus tag and sender line, understanding's and planning's.

    The sender line follows the origin's line in understanding and the person's last
    stimulus in planning (§5:1), and neither briefing says "hub" (§7:1).
    """
    heard = await _heard(row)
    (said,) = heard.tags("The stimulus")
    assert (said.name, said.attributes["from"]) == row.heard
    situation = heard.section("The situation").split("\n")
    assert situation[2].startswith("- The origin: ")
    assert situation[3] == row.line
    assert _hub(heard.content) == []

    briefing = await _briefed(row)
    (told,) = tags(section(briefing, "# The stimulus"))
    withheld = told.get("withheld") == "yes"
    assert (told.name, told.get("from"), withheld) == row.briefed
    lines = section(briefing, "## The situation").split("\n")
    assert "last stimulus" in lines[1].lower()
    assert lines[2] == row.line
    assert _hub(briefing) == []


async def test_a_second_person_once_admitted_is_named_as_the_owner_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§5's row for a second person once admitted: by name in a line, by ``P`` label in a tag.

    Admitting them is a later decision's (milestone 5); the case stands in for it by
    having ``core``'s declaration count their words as theirs.
    """

    def admitting(sender: InputSender | None) -> SupportHolder:
        if sender is not None and sender.identified and sender.person is not None:
            return SupportHolder.person(sender.person)
        return SupportHolder.unknown()

    monkeypatch.setattr(channel_kinds, "sender_party", admitting)
    row = Row(
        CHAT,
        (_sender(SAM),),
        (SupportHolder.person(SAM),),
        (),
        SAM,
        ("said", "a device linked to Sam"),
        ("said", "a device linked to P1", False),
        "- The sender: the message came by a device linked to Sam, which is a strong sign "
        "that Sam sent it. The system counts it as Sam's.",
    )
    sams = _block(SAM, "Sam")
    heard = await _heard(row, block=sams)
    (said,) = heard.tags("The stimulus")
    assert (said.name, said.attributes["from"]) == row.heard
    assert row.line in heard.section("The situation").split("\n")
    briefing = await _briefed(row, block=sams)
    (told,) = tags(section(briefing, "# The stimulus"))
    assert (told.name, told.get("from")) == row.briefed[:2]
    assert row.line in section(briefing, "## The situation").split("\n")


async def test_a_weak_link_renders_apart_from_one_at_its_kinds_most() -> None:
    """§5:3, §5:4: the same message by a link lowered to weak is told apart, in both."""
    normal, weak = ROWS["a link at its kind's most"], ROWS["a link lowered to weak"]
    strong_heard, weak_heard = await _heard(normal), await _heard(weak)
    assert strong_heard.section("The situation") != weak_heard.section("The situation")
    assert "a weak sign" in weak_heard.section("The situation")
    assert "a weak sign" not in strong_heard.section("The situation")
    strong_briefed, weak_briefed = await _briefed(normal), await _briefed(weak)
    assert section(strong_briefed, "## The situation") != section(weak_briefed, "## The situation")
    assert "marked as less reliable" in section(weak_briefed, "## The situation")


# --- §4:2, §4:3, §6:1: an unknown sender ------------------------------------------------


UNKNOWN_ROWS: Final = [
    "a link lowered to none",
    "no link",
    "links unread, elsewhere",
    "another person's device, no decision admitting them",
]


@pytest.mark.parametrize("name", UNKNOWN_ROWS)
async def test_an_unknown_senders_words_are_received_and_withheld_and_its_item_says_so(
    name: str,
) -> None:
    """§4:2: ``received`` in understanding, withheld in planning; §4:3: the window item.

    Understanding is shown the chat's own input messages, as the chat's reader brings
    them; each is attributed by the trigger's record, never by the medium's author.
    """
    row = ROWS[name]
    window = TranscriptWindow(
        CHAT,
        (),
        input_messages=(
            TranscriptMessage(
                conversation_id="c-1",
                position=3,
                author=MessageAuthor.USER,
                text=WORDS,
                written_at=AT,
                device_id="x",
                message_id="m-3",
            ),
        ),
    )
    heard = await _heard(row, window=window)
    (one,) = heard.tags("The stimulus")
    assert (one.name, one.attributes["from"], one.text) == ("received", "an unknown sender", WORDS)
    briefing = await _briefed(row)
    (told,) = tags(section(briefing, "# The stimulus"))
    assert (told.name, told.get("from"), told.get("withheld"), told.text) == (
        "received",
        "an unknown sender",
        "yes",
        None,
    )
    (item,) = tags(section(briefing, "## Stimulus origin knowledge"), "message")
    assert (item.get("from"), item.get("shown_in")) == ("an unknown sender", "the stimulus")


@pytest.mark.parametrize("name", UNKNOWN_ROWS)
async def test_no_rendering_names_an_unknown_sender_as_the_owner_or_any_person(name: str) -> None:
    """§6:1: never the owner, a person, nobody or no one's; and the reason is the sender.

    The stimulus's words and the window item are an unknown sender's, the sender line
    counts them so, and every note a work that is no person's renders gives the sender
    being unknown as its reason (§6:2).
    """
    row = ROWS[name]
    heard = await _heard(row)
    briefing = await _briefed(row)
    for text in (heard.content, briefing):
        assert "the owner" not in text
        assert "no person's" not in text
        assert "no one's" not in text
        assert "nobody" not in text
        assert "<said" not in text
        assert "The sender is unknown, so every time below is in the system's zone" in text
        assert (
            "The system does not have it: the sender is unknown, so nothing kept in mind about "
            "a person is read for this stimulus."
        ) in text
        assert (
            "The system does not have it: concurrent stimuli are shown only where the system "
            "knows who sent the stimulus."
        ) in text
    assert "- Last stimulus: the sender is unknown, so no earlier stimulus is named as theirs." in (
        heard.section("The situation")
    )
    assert "P1" not in section(briefing, "# The stimulus")


# --- §6:3 to §6:5: the person's name in a work that is no person's ------------------------


async def test_a_work_that_is_no_persons_names_the_person_in_the_three_roles() -> None:
    """§6:3: whose place, whose account an input came by, and who wrote an earlier item.

    By name in understanding and, in a tag as in a line, in planning (§6:5): no ``P``
    label names them there, since no person block says who it is.
    """
    row = ROWS["a link lowered to none"]
    earlier = TranscriptMessage(
        conversation_id="c-1",
        position=1,
        author=MessageAuthor.USER,
        text="Is the lake warm?",
        written_at=AT,
        device_id="home-pc",
        message_id="m-1",
    )
    heard = await _heard(row, window=TranscriptWindow(CHAT, (earlier,)))
    framing = heard.section("The stimulus").split("\n")[0]
    assert "a message that arrived in Maren's private chat with the system" in framing
    assert "typed" not in framing
    assert (
        "- The origin: the system's own chat, Maren's private chat with the system."
        in heard.section("The situation").split("\n")
    )
    assert "a device linked to Maren that is marked as not to be relied on" in heard.section(
        "The situation"
    )
    (item,) = heard.tags("Stimulus origin knowledge")
    assert item.attributes["from"] == MAREN

    before = PlaceItem(author=PlaceAuthor.USER, text="Is the lake warm?", at=AT)
    stimulus = PlaceItem(author=PlaceAuthor.USER, text=WORDS, at=AT, is_input=True)
    briefing = await _briefed(row, items=(before, stimulus))
    assert "a message that arrived in Maren's private chat with the system" in section(
        briefing, "# The stimulus"
    )
    assert "a device linked to Maren that is marked as not to be relied on" in section(
        briefing, "## The situation"
    )
    written = tags(section(briefing, "## Stimulus origin knowledge"), "message")
    assert [one.get("from") for one in written] == [MAREN, "an unknown sender"]


async def test_where_no_name_is_read_the_words_for_a_person_with_none_stand() -> None:
    """§6:4: a person who set no name, or a read that gave none, is named as before."""
    row = ROWS["no link"]
    heard = await _heard(row, named=None)
    assert "the owner's private chat with the system" in heard.section("The stimulus")
    assert MAREN not in heard.content


# --- §8: both instructions --------------------------------------------------------------


#: §8:1 and §8:2's two items, in draft 1's worked words.
ACCOUNT_NOT_USER: Final = (
    "Where an attribute names an account or a device, the system knows which account the item "
    "came by, not who was using it."
)
WHO_SENT: Final = "what the system knows about who or what sent the stimulus"


@pytest.mark.parametrize("prompt", [UNDERSTANDING_PROMPT, PLANNING_PROMPT], ids=str)
def test_both_instructions_carry_the_two_additions(prompt: Any) -> None:
    """§8:1, §8:2, §8:3: the situation's sender, and an account named is not its user."""
    text = default_prompt(prompt).rendered(flags={}).text
    situation = next(line for line in text.split("\n") if line.startswith("- The situation:"))
    assert WHO_SENT in situation
    assert ACCOUNT_NOT_USER in text
    assert _hub(text) == []


# --- the name's read (ADR-0375 §6:3, §6:4) ----------------------------------------------


def _facts(whom: str | None) -> WorkFacts:
    return WorkFacts(
        for_whom=WorkFor.no_one() if whom is None else WorkFor.for_person(whom),
        authority=WorkAuthority.none(),
        level=Sureness.NONE,
    )


async def _people(**fields: str) -> FakePersonModelStore:
    people = FakePersonModelStore()
    for key, value in fields.items():
        await people.set_field(OWNER_PERSON_ID, ProfileField(key), value, act=PANEL)
    return people


async def _read(people: FakePersonModelStore, whom: str | None) -> str | None:
    blocks = PersonBlocks(store=people, memory=FakeMemoryStore())
    return await place_name(blocks, _facts(whom), stage="understanding")


async def test_the_read_keeps_the_name_alone() -> None:
    """§6:3, §6:4: the name of the person whose place it is, and nothing else of them."""
    people = await _people(
        name=MAREN, address="Captain", language="Esperanto", assistant_name="Juniper"
    )
    read = await _read(people, OWNER_PERSON_ID)
    assert read == MAREN
    assert isinstance(read, str)


@pytest.mark.parametrize(
    ("whom", "fields", "fails"),
    [
        pytest.param(OWNER_PERSON_ID, {}, False, id="no name set"),
        pytest.param(OWNER_PERSON_ID, {"name": MAREN}, True, id="the store fails"),
        pytest.param(SAM, {"name": MAREN}, False, id="a person not served"),
        pytest.param(None, {"name": MAREN}, False, id="a work for no one"),
    ],
)
async def test_the_read_gives_none_where_no_name_may_be_shown(
    whom: str | None, fields: dict[str, str], *, fails: bool
) -> None:
    """§6:4: a store fault, a name not set, or a person the system does not serve."""
    people = await _people(**fields)
    if fails:
        people.fail_next()
    assert await _read(people, whom) is None


async def test_no_read_is_made_where_no_person_block_store_is_wired() -> None:
    """The read is the person-model store's; with none wired it reads nothing."""
    assert await place_name(None, _facts(OWNER_PERSON_ID), stage="planning") is None


def test_only_a_person_the_system_serves_is_named() -> None:
    """§5's table: the owner is served; an identity a link names that no decision admits is not."""
    assert channel_kinds.served(OWNER_PERSON_ID)
    assert not channel_kinds.served(SAM)
    assert not channel_kinds.served(None)
    assert channel_kinds.sender_unknown([_sender(SAM)])
    assert not channel_kinds.sender_unknown([_sender(OWNER_PERSON_ID, Sureness.WEAK)])
