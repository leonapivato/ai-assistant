"""ADR-0375 in a mock household: what both models are told of who sent each message.

Each case writes as someone in a :class:`Household` over the real engine, and reads what
understanding was shown (:attr:`Work.understood`) and what planning's first round was
shown (:attr:`Work.briefing`): the framing sentence says where a message arrived and no
act (§3), the stimulus's own words are ``said`` from the account they came by or
``received`` from an unknown sender (§4), the sender line says by what it came, how strong
a sign that is and whom the system counts it as (§5), a work that is no person's names the
person whose place it is by the name alone the hub read, and nothing else of their profile
(§6:3, §6:4), and nothing either model reads says "hub" (§7).

Every person, account and message here is invented (ADR-0337 §3:2).
"""

from __future__ import annotations

import re
from typing import Final

from exchange_support import section, tags
from household_harness import Household, Work
from understanding_support import Rendered

from ai_assistant.core.types import (
    HUB_DEVICE_ID,
    OWNER_PERSON_ID,
    PersonActHow,
    PersonModelAct,
    ProfileField,
    Sureness,
)
from ai_assistant.testing import FakePersonModelStore

PANEL: Final = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)

#: The owner's profile: a name, and four fields a work that is no person's never reads.
PROFILE: Final = {
    ProfileField.NAME: "Maren",
    ProfileField.ADDRESS: "Captain Fluff",
    ProfileField.LANGUAGE: "Esperanto",
    ProfileField.ASSISTANT_NAME: "Juniper",
    ProfileField.TIME_ZONE: "Asia/Tokyo",
}

_STRONG: Final = (
    "- The sender: the message came by a device linked to Maren, which is a strong sign that "
    "Maren sent it. The system counts it as Maren's."
)
_WEAK: Final = (
    "- The sender: the message came by a device linked to Maren that is marked as less "
    "reliable, which is a weak sign that Maren sent it. The system still counts it as Maren's."
)
_NO_LINK: Final = (
    "- The sender: the message came by a device the system cannot tie to anyone, so who or "
    "what sent it is unknown. The system counts it as an unknown sender's, whatever its text "
    "says."
)
_NOT_SERVED: Final = (
    "- The sender: the message came by a device linked to a person the system knows but does "
    "not serve. The system counts it as an unknown sender's, whatever its text says."
)
_MACHINE: Final = (
    "- The sender: the system could not read its record of linked accounts when the message "
    "arrived. The message was written on the system's own machine, which the system counts "
    "as Maren's."
)
_LINE: Final = (
    "- The sender: the message came by the Telegram account linked to Maren, which is a "
    "strong sign that Maren sent it. The system counts it as Maren's."
)


async def _people() -> FakePersonModelStore:
    people = FakePersonModelStore()
    for one, value in PROFILE.items():
        await people.set_field(OWNER_PERSON_ID, one, value, act=PANEL)
    return people


def _heard(work: Work) -> Rendered:
    """What understanding was shown of the work's input: its one call's user message."""
    (first, *_) = work.understood
    return Rendered(first)


def _no_hub(*texts: str) -> None:
    """ADR-0375 §7:1: nothing either model reads says "hub", in any form."""
    for text in texts:
        assert re.findall(r"(?i)\bhub", text) == []


async def test_an_unlinked_device_names_the_owner_by_name_alone_in_the_three_roles() -> None:
    """§6:3, §6:4: whose place, and who wrote an earlier item, by name; nothing else.

    The owner writes first from their linked computer, then a device no link ties writes
    in the same conversation: its work is no person's (ADR-0368 §9:5), and both models
    are told whose chat it arrived in and who wrote the earlier message by the owner's
    name alone, never their address, language, assistant's name or zone, and are told
    the words are an unknown sender's (§4:2, §5).
    """
    async with Household(people=await _people()) as home:
        mine = await home.device(home.owner, "home-pc")
        stranger = await home.device(None, "tablet")
        await home.say(mine, "Is the lake warm?")
        work = await home.say(stranger, "And the canoe?")

    assert work.reads == (None, None)
    heard = _heard(work)
    framing = heard.section("The stimulus").split("\n")[0]
    assert "a message that arrived in Maren's private chat with the system" in framing
    (words,) = heard.tags("The stimulus")
    assert (words.name, words.get("from"), words.text) == (
        "received",
        "an unknown sender",
        "And the canoe?",
    )
    situation = heard.section("The situation").split("\n")
    assert (
        situation[2] == "- The origin: the system's own chat, Maren's private chat with the system."
    )
    assert situation[3] == _NO_LINK
    assert [one.get("from") for one in heard.tags("Stimulus origin knowledge", "message")][:1] == [
        "Maren"
    ]

    briefing = work.briefing
    (told,) = tags(section(briefing, "# The stimulus"))
    assert (told.name, told.get("from"), told.get("withheld")) == (
        "received",
        "an unknown sender",
        "yes",
    )
    assert _NO_LINK in section(briefing, "## The situation").split("\n")
    written = tags(section(briefing, "## Stimulus origin knowledge"), "message")
    assert [one.get("from") for one in written] == ["Maren", "the system", "an unknown sender"]

    for text in (heard.content, briefing):
        for value in ("Captain Fluff", "Esperanto", "Juniper", "Asia/Tokyo", "the owner"):
            assert value not in text
    _no_hub(heard.content, briefing)


async def test_a_link_lowered_to_weak_is_told_apart_from_one_at_its_kinds_most() -> None:
    """§5:3, §5:4: the owner's device at normal, then the same device lowered to weak."""
    async with Household(people=await _people()) as home:
        phone = await home.device(home.owner, "phone")
        normal = await home.say(phone, "What's on today?")
        await home.lower(phone, Sureness.WEAK)
        weak = await home.say(phone, "What's on tomorrow?")

    for work, line in ((normal, _STRONG), (weak, _WEAK)):
        assert work.reads[0] == OWNER_PERSON_ID
        heard = _heard(work)
        (words,) = heard.tags("The stimulus")
        assert (words.name, words.get("from")) == ("said", "a device linked to Maren")
        assert line in heard.section("The situation").split("\n")
        (told,) = tags(section(work.briefing, "# The stimulus"))
        assert (told.name, told.get("from")) == ("said", "a device linked to P1")
        assert line in section(work.briefing, "## The situation").split("\n")
        _no_hub(heard.content, work.briefing)
    assert _heard(normal).section("The situation") != _heard(weak).section("The situation")


async def test_the_systems_own_machine_names_no_link_where_the_links_could_not_be_read() -> None:
    """§4:1, §5's row: ADR-0374 §3:2's sender, its words from the system's own machine."""
    async with Household(people=await _people()) as home:
        machine = await home.device(home.owner, HUB_DEVICE_ID)
        home.fault_next_read()
        work = await home.say(machine, "Lights off.")

    heard = _heard(work)
    (words,) = heard.tags("The stimulus")
    assert (words.name, words.get("from")) == ("said", "the system's own machine")
    assert _MACHINE in heard.section("The situation").split("\n")
    assert _MACHINE in section(work.briefing, "## The situation").split("\n")
    _no_hub(heard.content, work.briefing)


async def test_the_owners_telegram_account_names_its_kind() -> None:
    """§4:1, §5's row for Telegram: the account, by the kind's noun."""
    async with Household(people=await _people()) as home:
        line = await home.telegram(home.owner)
        work = await home.say(line, "Running late.")

    heard = _heard(work)
    assert "a message that arrived in Maren's private chat with the system on Telegram" in (
        heard.section("The stimulus")
    )
    (words,) = heard.tags("The stimulus")
    assert (words.name, words.get("from")) == ("said", "the Telegram account linked to Maren")
    assert _LINE in heard.section("The situation").split("\n")
    assert _LINE in section(work.briefing, "## The situation").split("\n")
    _no_hub(heard.content, work.briefing)


async def test_a_person_the_system_knows_but_does_not_serve_is_never_named() -> None:
    """§5's row for another person's device: an unknown sender's, the person unnamed."""
    async with Household(people=await _people()) as home:
        sam = home.person("sam")
        phone = await home.device(sam, "sams-phone")
        work = await home.say(phone, "Can I borrow the canoe?")

    assert work.reads == (None, None)
    heard = _heard(work)
    (words,) = heard.tags("The stimulus")
    assert (words.name, words.get("from")) == ("received", "an unknown sender")
    assert _NOT_SERVED in heard.section("The situation").split("\n")
    assert _NOT_SERVED in section(work.briefing, "## The situation").split("\n")
    for text in (heard.content, work.briefing):
        assert "sam" not in text.lower()
    _no_hub(heard.content, work.briefing)
