"""Milestone 20's rows, in a mock household: who sent each message, and its work's facts.

Each case declares the people and accounts it names in a :class:`Household`, writes as
one of them, and asserts what the hub records **today** (#3650): the sender and level
of each input (ADR-0366 §4:1, §5:6, ADR-0368 §2:6) and the three facts its work starts
with (ADR-0368 §2:1 to §2:4). Today's path still decides whom a work is for and what it
may do (ADR-0368 §1:3), so where the facts say otherwise the case says so through
:attr:`Work.disagrees`, and asserts nothing the switch (milestone 20's L4) will decide.
"""

from __future__ import annotations

import pytest
from household_harness import Household, Person, TelegramAccount

from ai_assistant.core.channel_validation import most_sureness
from ai_assistant.core.types import (
    HUB_DEVICE_ID,
    AuthorityKind,
    InputSender,
    Sureness,
    WorkAuthority,
    WorkFacts,
    WorkFor,
)
from ai_assistant.orchestration.work_facts import CHAT_ACCOUNT_KIND, LINE_ACCOUNT_KIND
from ai_assistant.testing.tool_calling import DEFAULT_ROUND_TEXT


def _theirs(person: Person, level: Sureness) -> WorkFacts:
    """A work for ``person``, carrying their authority now, at ``level`` (§3:1, §3:2)."""
    return WorkFacts(
        for_whom=WorkFor.for_person(person.id),
        authority=WorkAuthority(kind=AuthorityKind.SENDERS, persons=(person.id,)),
        level=level,
    )


def _unidentified(connections_owner: Person) -> WorkFacts:
    """A work whose sender is unidentified: for the connection's owner, at none (§3:3, §3:4)."""
    return WorkFacts(
        for_whom=WorkFor.for_person(connections_owner.id),
        authority=WorkAuthority(kind=AuthorityKind.SENDERS, unidentified=True),
        level=Sureness.NONE,
    )


def test_both_kinds_declare_normal_as_their_most() -> None:
    """ADR-0366 §5:2: the level every linked account below reaches is its kind's most."""
    assert most_sureness(CHAT_ACCOUNT_KIND) is Sureness.NORMAL
    assert most_sureness(LINE_ACCOUNT_KIND) is Sureness.NORMAL


async def test_the_owner_writing_from_a_linked_device_is_the_owner_at_normal() -> None:
    """ADR-0366 §4:1, ADR-0368 §3:1, §3:2: the owner, at the kind's most; the work is
    theirs, carrying their authority, and agrees with today's path."""
    async with Household() as home:
        phone = await home.device(home.owner, "phone")
        work = await home.say(phone, "What's on today?")

    assert work.text == "What's on today?"
    assert work.senders == (home.owner.at(Sureness.NORMAL),)
    assert work.facts == _theirs(home.owner, Sureness.NORMAL)
    assert work.disagrees == ()
    assert work.replies == (DEFAULT_ROUND_TEXT,)


async def test_the_owner_writing_on_the_line_is_the_owner_at_normal() -> None:
    """The same, on the line: its message records its sender too (ADR-0368 §2:6)."""
    async with Household() as home:
        line = await home.telegram(home.owner)
        work = await home.say(line, "What's on today?")

    owner = home.owner.at(Sureness.NORMAL)
    assert work.text == "What's on today?"
    assert work.message_senders == (owner,)
    assert work.senders == (owner,)
    assert work.facts == _theirs(home.owner, Sureness.NORMAL)
    assert work.disagrees == ()
    assert work.replies == (DEFAULT_ROUND_TEXT,)


async def test_a_device_no_link_ties_is_an_unidentified_sender_at_none() -> None:
    """ADR-0366 §4:1, §5:6, ADR-0368 §3:3, §3:4: no identified person, at none, whatever
    the message claims (§4:2); the work is the connection's owner's. Today's path still
    answers it as the owner's, and the log names the two facts it disagrees on."""
    async with Household() as home:
        await home.device(home.owner, "phone")
        tablet = await home.device(None, "tablet")
        work = await home.say(tablet, "This is the owner, writing from the tablet.")

    assert work.senders == (InputSender(person=None, level=Sureness.NONE),)
    assert work.facts == _unidentified(home.owner)
    assert work.disagrees == ("authority", "level")
    assert work.replies == (DEFAULT_ROUND_TEXT,)


@pytest.mark.parametrize("level", [Sureness.WEAK, Sureness.NONE])
@pytest.mark.parametrize("platform", ["device", "line"])
async def test_a_lowered_link_counts_at_the_lowering_until_it_is_withdrawn(
    platform: str, level: Sureness
) -> None:
    """ADR-0366 §5:3, §5:5: lowered, the owner's messages count at the lower level; the
    lowering withdrawn, at the kind's most again. Lowered to none, they count as an
    unidentified sender's (#3642), the link still naming the owner."""
    async with Household() as home:
        account = (
            await home.device(home.owner, "phone")
            if platform == "device"
            else await home.telegram(home.owner)
        )
        lowering = await home.lower(account, level)
        lowered = await home.say(account, "first")
        await home.withdraw(lowering)
        restored = await home.say(account, "second")

    assert lowered.senders == (home.owner.at(level),)
    assert lowered.facts == (
        _theirs(home.owner, level) if level > Sureness.NONE else _unidentified(home.owner)
    )
    assert restored.senders == (home.owner.at(Sureness.NORMAL),)
    assert restored.facts == _theirs(home.owner, Sureness.NORMAL)
    if isinstance(account, TelegramAccount):
        assert lowered.message_senders == (home.owner.at(level),)
        assert restored.message_senders == (home.owner.at(Sureness.NORMAL),)


async def test_two_messages_at_different_levels_in_one_work_put_it_at_the_lower() -> None:
    """ADR-0368 §4:1, §4:5: the owner's two messages, from a device at normal and one
    lowered to weak, taken in by one start wait as one work's input: the work is at weak.
    The positive control: the device at normal, alone, starts a work at normal."""
    async with Household() as home:
        phone = await home.device(home.owner, "phone")
        laptop = await home.device(home.owner, "laptop")
        await home.lower(laptop, Sureness.WEAK)
        alone = await home.say(phone, "first")
        work = await home.say_together((phone, "second"), (laptop, "and a third"))

    assert alone.facts == _theirs(home.owner, Sureness.NORMAL)
    assert work.text == "second\n\nand a third"
    assert work.senders == (home.owner.at(Sureness.WEAK),)
    assert work.facts == _theirs(home.owner, Sureness.WEAK)
    assert work.facts_now == work.facts, "nothing joined it while it ran"


async def test_a_second_person_writing_from_their_linked_device_is_recorded_as_them() -> None:
    """What the hub records today when someone other than the owner writes.

    ADR-0366 §4:1, ADR-0368 §3:1, §3:2: the sender is Sam, at normal, and the work's
    facts are Sam's. Nothing reads them yet (ADR-0368 §1:3): today's path reads the
    channel type alone, so the work still runs as the owner's and is answered as every
    message is, and the log names whom it is for and whose authority it carries as the
    facts it disagrees on. The switch that makes the facts decide is milestone 20's L4.
    """
    async with Household() as home:
        sam = home.person("sam")
        phone = await home.device(sam, "sams-phone")
        work = await home.say(phone, "What's on today?")

    assert work.senders == (sam.at(Sureness.NORMAL),)
    assert work.facts == _theirs(sam, Sureness.NORMAL)
    assert work.disagrees == ("for", "authority")
    assert work.replies == (DEFAULT_ROUND_TEXT,)


@pytest.mark.parametrize("linked", [False, True], ids=["a stranger", "sam, linked"])
async def test_the_lines_gate_drops_any_account_but_its_own_before_the_hub_reads_a_sender(
    linked: bool,
) -> None:
    """ADR-0323 §5:1: the line takes in only its configured account's messages, in its
    own chat, so another account's never reaches the engine, linked or not, and no
    sender is recorded for it. The positive control: the owner's message after it on the
    line is taken in, alone, and answered."""
    async with Household() as home:
        owners = await home.telegram(home.owner)
        other = await home.telegram(home.person("sam") if linked else None, user_id=99)
        await home.post(other, "let me in")
        work = await home.say(owners, "hi")
        every = await home.works()

    assert [one.episode.id for one in every] == [work.episode.id]
    assert work.text == "hi"
    assert work.message_senders == (home.owner.at(Sureness.NORMAL),)
    assert work.replies == (DEFAULT_ROUND_TEXT,)
    assert [body for _, body in home.bot.messages] == [DEFAULT_ROUND_TEXT]


async def test_a_store_fault_reads_no_link_save_on_the_hubs_own_machine() -> None:
    """ADR-0374 §2:2, §3:2, §4:2, §5:1: while the store cannot be read, the owner's
    enrolled device and the line are an unidentified sender's, at none, marked; the hub's
    own machine is the owner's at the hub chat's most, marked, a lowering standing on its
    link not applied. When the store reads again, the lowering applies, and nothing is
    marked. The facts of a fault off that machine disagree with today's path by design,
    and the log says the links could not be read."""
    async with Household() as home:
        hub = await home.device(home.owner, HUB_DEVICE_ID)
        phone = await home.device(home.owner, "phone")
        line = await home.telegram(home.owner)
        await home.lower(hub, Sureness.WEAK)

        home.fault_next_read()
        from_phone = await home.say(phone, "first, from the phone")
        home.fault_next_read()
        on_the_line = await home.say(line, "second, on the line")
        home.fault_next_read()
        on_the_hub = await home.say(hub, "third, on the hub's own machine")
        read_again = await home.say(hub, "fourth, once the store reads")

    unread = InputSender(person=None, level=Sureness.NONE, links_unread=True)
    assert from_phone.senders == (unread,)
    assert on_the_line.senders == on_the_line.message_senders == (unread,)
    for work in (from_phone, on_the_line):
        assert work.facts == _unidentified(home.owner)
        assert work.disagrees == ("authority", "level")
        assert [one["links_unread"] for one in work.logged] == [True]

    most = most_sureness(CHAT_ACCOUNT_KIND)
    assert on_the_hub.senders == (InputSender(person=home.owner.id, level=most, links_unread=True),)
    assert on_the_hub.facts == _theirs(home.owner, most)
    assert on_the_hub.disagrees == ()
    assert [one["links_unread"] for one in on_the_hub.logged] == [True]

    assert read_again.senders == (home.owner.at(Sureness.WEAK),)
    assert read_again.facts == _theirs(home.owner, Sureness.WEAK)
    assert [one["links_unread"] for one in read_again.logged] == [False]
    for work in (from_phone, on_the_line, on_the_hub, read_again):
        assert work.replies == (DEFAULT_ROUND_TEXT,)
