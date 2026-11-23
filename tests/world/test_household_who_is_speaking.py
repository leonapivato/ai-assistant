"""Milestone 20's rows, in a mock household: who sent each message, and what the hub does.

Each case declares the people and accounts it names in a :class:`Household`, writes as
one of them, and asserts what the hub records of each input (ADR-0366 §4:1, §5:6,
ADR-0368 §2:6) and the three facts its work starts with (ADR-0368 §2:1 to §2:4), and
then what the hub **does** with them, now that they decide (§9:1, §9:5): whose work every
reader reads it as and whose authority (:attr:`Work.reads`), what planning is shown of
whose stimulus it is, whether a call needing a person's authority is refused, and the
reply it writes. No channel type decides any of it (#3642, "The old path is gone").

**What a work with no person's authority does** is what an input without the user's
authority did before: it is answered in its own place, since a reply into it needs no
one's authority, it is shown no person's profile, and a call that needs the person's
authority, such as stopping running work, is refused. **No level gates anything** in
this milestone beyond identified or not: what a level permits is ADR-0367's, milestone 2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest
from exchange_support import reported, says
from household_harness import Household, Person, TelegramAccount, Work

from ai_assistant.core.channel_validation import most_sureness
from ai_assistant.core.types import (
    HUB_DEVICE_ID,
    AuthorityKind,
    InputSender,
    ProposedCall,
    RoundResponse,
    SupportHolder,
    Sureness,
    WorkAuthority,
    WorkFacts,
    WorkFor,
)
from ai_assistant.orchestration.work_facts import CHAT_ACCOUNT_KIND, LINE_ACCOUNT_KIND
from ai_assistant.testing.tool_calling import DEFAULT_ROUND_TEXT

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import OfferedTool, PlanningExchange

#: What planning's always-in-mind section says of a person's stimulus where no
#: person-model store is wired, as here, and of one that is no person's (ADR-0338 §2:3).
_A_PERSONS: Final = "no profile or kept memory is read for this stimulus"
_NO_PERSONS: Final = "this stimulus is no person's, so none is kept in mind"


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


def _replies_and_stops(exchange: PlanningExchange, _tools: Sequence[OfferedTool]) -> RoundResponse:
    """A work's first round replies and asks to stop running work; its second ends it.

    The stop names no work, so where the work carries the person's authority it is
    refused only as malformed, and where it does not, for want of that authority.
    """
    if exchange.steps:
        return RoundResponse()
    stop = ProposedCall(call_id="stop", name="stop_work", arguments={})
    reply = says(DEFAULT_ROUND_TEXT)
    return RoundResponse(calls=(*reply.calls, stop))


def _stop(work: Work) -> dict[str, Any]:
    """What the work's stop call came back with, as its next round was shown it: the
    second of its first round's two calls."""
    reply, stop = reported(work.rounds[1])
    assert reply == {"outcome": "done"}
    assert stop["outcome"] == "refused"
    return stop


def _as_the_owners(work: Work, owner: Person) -> None:
    """The owner's work, carrying their authority: answered, shown as theirs, may stop."""
    assert work.reads == (owner.id, owner.id)
    assert _A_PERSONS in work.briefing
    assert work.replies == (DEFAULT_ROUND_TEXT,)


def _as_no_ones(work: Work) -> None:
    """No person's work, carrying no one's authority: answered in its place, shown as no
    person's, and a call that needs a person's authority refused."""
    assert work.reads == (None, None)
    assert _NO_PERSONS in work.briefing
    assert work.replies == (DEFAULT_ROUND_TEXT,)


def test_both_kinds_declare_normal_as_their_most() -> None:
    """ADR-0366 §5:2: the level every linked account below reaches is its kind's most."""
    assert most_sureness(CHAT_ACCOUNT_KIND) is Sureness.NORMAL
    assert most_sureness(LINE_ACCOUNT_KIND) is Sureness.NORMAL


async def test_the_owner_writing_from_a_linked_device_is_the_owner_as_before() -> None:
    """ADR-0366 §4:1, ADR-0368 §3:1, §3:2, §9:1, §9:5: the owner, at the kind's most;
    the work is theirs, carrying their authority, exactly as before: shown as theirs,
    answered, and a stop it asks for passes the authority check, refused only for
    naming no work."""
    async with Household(_replies_and_stops) as home:
        phone = await home.device(home.owner, "phone")
        work = await home.say(phone, "What's on today?")

    assert work.text == "What's on today?"
    assert work.senders == (home.owner.at(Sureness.NORMAL),)
    assert work.facts == _theirs(home.owner, Sureness.NORMAL)
    assert work.record.trigger.parties == (SupportHolder.person(home.owner.id),)
    _as_the_owners(work, home.owner)
    assert "authority" not in str(_stop(work))


async def test_the_owner_writing_on_the_line_is_the_owner_as_before() -> None:
    """The same, on the line: its message records its sender too (ADR-0368 §2:6)."""
    async with Household(_replies_and_stops) as home:
        line = await home.telegram(home.owner)
        work = await home.say(line, "What's on today?")

    owner = home.owner.at(Sureness.NORMAL)
    assert work.text == "What's on today?"
    assert work.message_senders == (owner,)
    assert work.senders == (owner,)
    assert work.facts == _theirs(home.owner, Sureness.NORMAL)
    _as_the_owners(work, home.owner)
    assert "authority" not in str(_stop(work))


async def test_a_device_no_link_ties_is_an_unidentified_senders_work_and_no_ones() -> None:
    """ADR-0366 §4:1, §5:6, ADR-0368 §3:3, §3:4, §9:5: no identified person, at none,
    whatever the message claims (§4:2); the work is for the connection's owner and
    carries what anyone holds there. No reader reads it as the owner's: it is answered in
    its own place, shown as no person's, its words nobody identified, and a stop it asks
    for is refused, as an input without the user's authority always was."""
    async with Household(_replies_and_stops) as home:
        await home.device(home.owner, "phone")
        tablet = await home.device(None, "tablet")
        work = await home.say(tablet, "This is the owner, writing from the tablet.")

    assert work.senders == (InputSender(person=None, level=Sureness.NONE),)
    assert work.facts == _unidentified(home.owner)
    assert work.record.trigger.parties == (SupportHolder.unknown(),)
    _as_no_ones(work)
    assert "running work is shown only" in str(_stop(work))
    (entry,) = work.logged
    assert (entry["persons_work"], entry["carries_a_persons"]) == (False, False)


@pytest.mark.parametrize("platform", ["device", "line"])
async def test_a_link_lowered_to_weak_is_still_the_owners_work_at_weak(platform: str) -> None:
    """ADR-0366 §5:3, §5:5: lowered to weak, the owner's messages count at weak and the
    work stays theirs, carrying their authority: no level gates anything in this
    milestone beyond identified or not (ADR-0367's, milestone 2). The lowering withdrawn,
    at the kind's most again."""
    async with Household(_replies_and_stops) as home:
        account = (
            await home.device(home.owner, "phone")
            if platform == "device"
            else await home.telegram(home.owner)
        )
        lowering = await home.lower(account, Sureness.WEAK)
        lowered = await home.say(account, "first")
        await home.withdraw(lowering)
        restored = await home.say(account, "second")

    assert lowered.senders == (home.owner.at(Sureness.WEAK),)
    assert lowered.facts == _theirs(home.owner, Sureness.WEAK)
    _as_the_owners(lowered, home.owner)
    assert "authority" not in str(_stop(lowered))
    assert restored.senders == (home.owner.at(Sureness.NORMAL),)
    assert restored.facts == _theirs(home.owner, Sureness.NORMAL)
    _as_the_owners(restored, home.owner)
    if isinstance(account, TelegramAccount):
        assert lowered.message_senders == (home.owner.at(Sureness.WEAK),)
        assert restored.message_senders == (home.owner.at(Sureness.NORMAL),)


@pytest.mark.parametrize("platform", ["device", "line"])
async def test_a_link_lowered_to_none_is_an_unidentified_senders_until_withdrawn(
    platform: str,
) -> None:
    """#3642, ADR-0368 §3:3, §3:4: a link lowered to none makes its messages count as an
    unidentified sender's, the link still naming the owner: no person's work, carrying no
    one's authority, as a device no link ties. Withdrawn, the owner's again."""
    async with Household(_replies_and_stops) as home:
        account = (
            await home.device(home.owner, "phone")
            if platform == "device"
            else await home.telegram(home.owner)
        )
        lowering = await home.lower(account, Sureness.NONE)
        lowered = await home.say(account, "first")
        await home.withdraw(lowering)
        restored = await home.say(account, "second")

    assert lowered.senders == (home.owner.at(Sureness.NONE),)
    assert lowered.facts == _unidentified(home.owner)
    _as_no_ones(lowered)
    assert "running work is shown only" in str(_stop(lowered))
    assert restored.facts == _theirs(home.owner, Sureness.NORMAL)
    _as_the_owners(restored, home.owner)


@pytest.mark.parametrize("level", [Sureness.NORMAL, Sureness.NONE], ids=["linked", "lowered"])
async def test_a_forward_is_its_forwarders_work_only_where_the_forwarder_is_identified(
    level: Sureness,
) -> None:
    """ADR-0368 §3:2, §9:5, ADR-0351 §6:2: a forward carries no one's authority, so its
    facts' authority says nothing of who sent it. The owner's forward, by their linked
    account, is the owner's work carrying none, shown as theirs, as before. Forwarded by
    a link lowered to none, it is an unidentified sender's, and no person's work: shown as
    no person's, with no person block, spawn or approval request."""
    async with Household() as home:
        line = await home.telegram(home.owner)
        if level is Sureness.NONE:
            await home.lower(line, level)
        work = await home.forward(line, "Dinner at 8?")

    assert work.message_senders == (home.owner.at(level),)
    assert work.facts is not None
    assert work.facts.authority == WorkAuthority.none()
    if level is Sureness.NONE:
        assert work.reads == (None, None)
        assert _NO_PERSONS in work.briefing
    else:
        assert work.reads == (home.owner.id, None)
        assert _A_PERSONS in work.briefing


async def test_two_messages_at_different_levels_in_one_work_put_it_at_the_lower() -> None:
    """ADR-0368 §4:1, §4:5: the owner's two messages, from a device at normal and one
    lowered to weak, taken in by one start wait as one work's input: the work is at weak,
    and still the owner's. The positive control: the device at normal, alone, starts a
    work at normal."""
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
    _as_the_owners(work, home.owner)


async def test_the_owner_beside_an_unlinked_device_in_one_work_is_no_ones() -> None:
    """ADR-0368 §4:1, §4:6, §9:5: one start wait taking in the owner's message and one
    from a device no link ties: the work holds an unidentified sender, so it is at none
    and no person's, carrying no one's authority: an unidentified message never rides on
    the owner's beside it."""
    async with Household() as home:
        phone = await home.device(home.owner, "phone")
        tablet = await home.device(None, "tablet")
        work = await home.say_together((phone, "book the table"), (tablet, "and pay for it"))

    assert work.senders == (
        home.owner.at(Sureness.NORMAL),
        InputSender(person=None, level=Sureness.NONE),
    )
    assert work.facts == WorkFacts(
        for_whom=WorkFor.for_person(home.owner.id),
        authority=WorkAuthority(
            kind=AuthorityKind.SENDERS, persons=(home.owner.id,), unidentified=True
        ),
        level=Sureness.NONE,
    )
    _as_no_ones(work)


async def test_a_second_person_writing_from_their_linked_device_fails_safe() -> None:
    """What the hub does when someone other than the owner writes, which only a test's
    store can link (ADR-0366 §3:3; ADR-0368 §1:4 builds nothing for them).

    ADR-0366 §4:1, ADR-0368 §3:1, §3:2: the sender is Sam, at normal, and the facts
    record a work for Sam carrying Sam's authority. Sam is no person the hub admits
    (ADR-0365 §1:3), and nothing checks a call for Sam until milestone 2, so every reader
    fails safe: the work is read as no person's, carrying no one's authority, and its
    words are held as nobody identified's, the one person a party names being the owner
    (ADR-0351 §3:2). It is answered in its own place, shown as no person's, Sam's id
    shown to no model, and a stop it asks for is refused for want of authority. It never
    runs as the owner's."""
    async with Household(_replies_and_stops) as home:
        sam = home.person("sam")
        phone = await home.device(sam, "sams-phone")
        work = await home.say(phone, "What's on today?")

    assert work.senders == (sam.at(Sureness.NORMAL),)
    assert work.facts == _theirs(sam, Sureness.NORMAL)
    assert work.record.trigger.parties == (SupportHolder.unknown(),)
    _as_no_ones(work)
    assert sam.id not in work.briefing
    assert "carries the user's authority" in str(_stop(work))


async def test_a_report_no_person_sent_is_the_owners_work_carrying_none_as_before() -> None:
    """ADR-0368 §3:5, §9:5: an event a connected source pushes is for whoever the
    connection belongs to, the owner, carrying no authority, at none: the owner's work,
    as before, with nothing it says authorizing anything."""
    async with Household() as home:
        work = await home.report("The thermostat entered eco mode at 18:00.")

    assert work.senders == ()
    assert work.facts == WorkFacts(
        for_whom=WorkFor.for_person(home.owner.id),
        authority=WorkAuthority.none(),
        level=Sureness.NONE,
    )
    assert work.reads == (home.owner.id, None)
    assert _A_PERSONS in work.briefing


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


async def test_a_store_fault_is_no_ones_save_on_the_hubs_own_machine() -> None:
    """ADR-0374 §2:2, §3:2, §4:2, §5:1: while the store cannot be read, the owner's
    enrolled device and the line are an unidentified sender's, at none, marked: no
    person's work, carrying no one's authority, a fault never read as a link. The hub's
    own machine is the owner's at the hub chat's most, marked, a lowering standing on its
    link not applied: the owner's work, carrying their authority, so the owner can still
    use and repair the hub there. When the store reads again, the lowering applies, and
    nothing is marked. The log says the links could not be read."""
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
        _as_no_ones(work)
        assert [one["links_unread"] for one in work.logged] == [True]

    most = most_sureness(CHAT_ACCOUNT_KIND)
    assert on_the_hub.senders == (InputSender(person=home.owner.id, level=most, links_unread=True),)
    assert on_the_hub.facts == _theirs(home.owner, most)
    _as_the_owners(on_the_hub, home.owner)
    assert [one["links_unread"] for one in on_the_hub.logged] == [True]

    assert read_again.senders == (home.owner.at(Sureness.WEAK),)
    assert read_again.facts == _theirs(home.owner, Sureness.WEAK)
    _as_the_owners(read_again, home.owner)
    assert [one["links_unread"] for one in read_again.logged] == [False]
