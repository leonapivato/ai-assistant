"""Shared obligations of the owner's linked accounts on ``AssistantEngine`` (ADR-0373 §2, §3).

Every implementation answers ``linked_accounts``, ``lower_link`` and
``withdraw_lowering`` from the same identity store, with the same outcomes in the order
§2:4 fixes, the same refusals before any I/O (§2:7), the owner as the maker of every
lowering (§4:3), and the listing showing what §3 names and no more. A subject is handed
to the suite holding a :class:`~ai_assistant.testing.FakeIdentityStore` with the owner's
two configured accounts linked, as a hub with the line configured opens it: the hub chat
on the hub's own machine and the line's Telegram account.

A mixin, as ``pending_candidates_contract`` is, so the engine, the canonical fake and the
wire client each bind it in the file that binds the rest of the suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core import channel_validation
from ai_assistant.core.errors import IdentityStoreError, OversizedValueError
from ai_assistant.core.types import (
    HUB_DEVICE_ID,
    OWNER_PERSON_ID,
    Account,
    LinkActHow,
    LinkedAccount,
    LowerLinkOutcome,
    LowerLinkRefusal,
    StandingLowering,
    Sureness,
    WithdrawLoweringOutcome,
)
from ai_assistant.core.types import LinkAct as _LinkAct

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.testing import FakeIdentityStore

#: The contract limit each subject is built at: room for the listing of a few links, and
#: small enough that a few dozen more are past it.
LINKS_LIMIT: Final = 4096

#: The owner's two configured accounts, linked when the store opens.
HUB_CHAT: Final = Account(kind="conversation", identifier=HUB_DEVICE_ID)
LINE: Final = Account(kind="telegram", identifier="424242")
CONFIGURED: Final = (HUB_CHAT, LINE)


@dataclass(frozen=True, slots=True)
class LinkedAccountsSubject:
    """An engine and the identity store it answers from, seeded from the test process.

    Attributes:
        engine: The subject under test.
        identities: The store its three members read and write.
    """

    engine: AssistantEngine
    identities: FakeIdentityStore


async def _link_id(subject: LinkedAccountsSubject, account: Account) -> str:
    held = await subject.identities.find_link(account)
    assert held is not None
    return held.id


async def _owners_link(subject: LinkedAccountsSubject, link_id: str) -> Any:
    owner = await subject.identities.identity(OWNER_PERSON_ID)
    assert owner is not None
    return next(one for one in owner.links if one.id == link_id)


class LinkedAccountsContract:
    """The three members through the engine, the fake and the wire client alike."""

    @pytest.fixture
    def linked_accounts_subject(self) -> LinkedAccountsSubject:
        """Override with an implementation over a store holding :data:`CONFIGURED`.

        Built at :data:`LINKS_LIMIT`.
        """
        raise NotImplementedError

    @pytest.fixture
    def linked_accounts_storeless(self) -> AssistantEngine:
        """Override with an implementation handed no identity store."""
        raise NotImplementedError

    # --- the listing (§2:2, §3) ------------------------------------------------

    async def test_every_standing_link_is_listed_with_what_section_3_names(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        """§3:1: id, identity, account, the kind's most, standing lowerings, the level."""
        subject = linked_accounts_subject
        chat, line = await _link_id(subject, HUB_CHAT), await _link_id(subject, LINE)

        listed = await subject.engine.linked_accounts()

        assert isinstance(listed, tuple)
        assert sorted(listed, key=lambda one: one.link_id) == sorted(
            (
                LinkedAccount(
                    link_id=chat,
                    person_id=OWNER_PERSON_ID,
                    account=HUB_CHAT,
                    most=Sureness.NORMAL,
                    level=Sureness.NORMAL,
                ),
                LinkedAccount(
                    link_id=line,
                    person_id=OWNER_PERSON_ID,
                    account=LINE,
                    most=Sureness.NORMAL,
                    level=Sureness.NORMAL,
                ),
            ),
            key=lambda one: one.link_id,
        )

    async def test_an_entry_carries_no_field_beyond_section_3(self) -> None:
        """§3:1, §3:3: exactly the fields named, so no act, instant or secret rides along."""
        assert set(LinkedAccount.model_fields) == {
            "link_id",
            "person_id",
            "account",
            "most",
            "lowerings",
            "level",
        }
        assert set(StandingLowering.model_fields) == {"id", "level", "by"}
        assert set(Account.model_fields) == {"kind", "identifier"}

    async def test_an_ended_link_is_not_listed(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        """§6:3: a link whose act no longer stands ties nothing, so it is not the owner's."""
        subject = linked_accounts_subject
        line = await _link_id(subject, LINE)
        await subject.identities.end_link(line)

        listed = await subject.engine.linked_accounts()

        assert [one.account for one in listed] == [HUB_CHAT]

    async def test_a_kind_with_no_declaration_shows_none_as_its_most_and_level(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        """§3: a kind with no declaration gives none (ADR-0366 §5:2)."""
        subject = linked_accounts_subject
        mail = Account(kind="mail", identifier="owner@example.org")
        made = await subject.identities.link(
            OWNER_PERSON_ID, mail, act=_LinkAct(how=LinkActHow.DEVICE, by=OWNER_PERSON_ID)
        )

        listed = {one.link_id: one for one in await subject.engine.linked_accounts()}

        assert made.record_id is not None
        shown = listed[made.record_id]
        assert (shown.most, shown.level) == (Sureness.NONE, Sureness.NONE)

    async def test_a_storeless_hub_lists_none(
        self, linked_accounts_storeless: AssistantEngine
    ) -> None:
        assert await linked_accounts_storeless.linked_accounts() == ()

    async def test_a_listing_past_the_limit_is_refused_whole(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        """§2:2: never truncated; refused with ``OversizedValueError``."""
        subject = linked_accounts_subject
        act = _LinkAct(how=LinkActHow.DEVICE, by=OWNER_PERSON_ID)
        for index in range(60):
            account = Account(kind="conversation", identifier=f"device-{index:03}")
            await subject.identities.link(OWNER_PERSON_ID, account, act=act)

        with pytest.raises(OversizedValueError):
            await subject.engine.linked_accounts()

    async def test_a_store_fault_is_raised(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        """§2:7: a store that cannot be read raises its contract's error."""
        subject = linked_accounts_subject
        subject.identities.fail_next()

        with pytest.raises(IdentityStoreError):
            await subject.engine.linked_accounts()

    # --- lowering (§2:3, §2:4) -------------------------------------------------

    async def test_a_lowering_is_recorded_by_the_owner_and_the_entry_shows_it(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        """§2:3, §3:2, §4:3: ``lowered``, made by the owner, the hub computing the level."""
        subject = linked_accounts_subject
        line = await _link_id(subject, LINE)

        result = await subject.engine.lower_link(line, level=Sureness.NONE)

        assert result.outcome is LowerLinkOutcome.LOWERED
        assert result.refusal is None
        assert result.lowering is not None
        assert result.lowering.level is Sureness.NONE
        assert result.lowering.by == OWNER_PERSON_ID
        assert result.entry is not None
        assert result.entry.link_id == line
        assert result.entry.most is Sureness.NORMAL
        assert result.entry.level is Sureness.NONE
        assert result.entry.lowerings == (result.lowering,)
        held = await _owners_link(subject, line)
        assert [(one.id, one.by, one.level) for one in held.standing_lowerings] == [
            (result.lowering.id, OWNER_PERSON_ID, Sureness.NONE)
        ]
        listed = {one.link_id: one for one in await subject.engine.linked_accounts()}
        assert listed[line] == result.entry

    async def test_a_level_given_by_its_value_is_the_level(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        subject = linked_accounts_subject
        line = await _link_id(subject, LINE)

        result = await subject.engine.lower_link(line, level="weak")  # type: ignore[arg-type]

        assert result.lowering is not None
        assert result.lowering.level is Sureness.WEAK

    async def test_a_repeated_lowering_is_unchanged_and_makes_no_second(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        """§2:4's second step: the standing lowering and the entry, nothing written."""
        subject = linked_accounts_subject
        line = await _link_id(subject, LINE)
        first = await subject.engine.lower_link(line, level=Sureness.WEAK)

        again = await subject.engine.lower_link(line, level=Sureness.WEAK)

        assert again.outcome is LowerLinkOutcome.UNCHANGED
        assert again.lowering == first.lowering
        assert again.entry == first.entry
        held = await _owners_link(subject, line)
        assert len(held.lowerings) == 1

    async def test_a_second_lowering_at_another_level_stands_beside_the_first(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        """ADR-0366 §5:3: the lowest standing lowering sets the level."""
        subject = linked_accounts_subject
        line = await _link_id(subject, LINE)
        await subject.engine.lower_link(line, level=Sureness.WEAK)

        result = await subject.engine.lower_link(line, level=Sureness.NONE)

        assert result.outcome is LowerLinkOutcome.LOWERED
        assert result.entry is not None
        assert [one.level for one in result.entry.lowerings] == [Sureness.WEAK, Sureness.NONE]
        assert result.entry.level is Sureness.NONE

    @pytest.mark.parametrize("level", [Sureness.NORMAL, Sureness.STRONG])
    async def test_a_level_not_below_the_kinds_most_is_not_a_lowering(
        self, linked_accounts_subject: LinkedAccountsSubject, level: Sureness
    ) -> None:
        """§2:4's third step: refused, nothing written."""
        subject = linked_accounts_subject
        line = await _link_id(subject, LINE)

        result = await subject.engine.lower_link(line, level=level)

        assert result.outcome is LowerLinkOutcome.REFUSED
        assert result.refusal is LowerLinkRefusal.NOT_A_LOWERING
        assert (result.lowering, result.entry) == (None, None)
        assert (await _owners_link(subject, line)).lowerings == ()

    async def test_an_unknown_link_is_refused_first(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        """§2:4's first step, ahead of ``not_a_lowering``: a level that lowers nothing."""
        subject = linked_accounts_subject

        result = await subject.engine.lower_link("link:nowhere", level=Sureness.STRONG)

        assert result.outcome is LowerLinkOutcome.REFUSED
        assert result.refusal is LowerLinkRefusal.UNKNOWN_LINK

    async def test_an_ended_link_is_an_unknown_link(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        """§6:3: an ended link ties nothing, so it is no link to the owner's identity."""
        subject = linked_accounts_subject
        line = await _link_id(subject, LINE)
        await subject.identities.end_link(line)

        result = await subject.engine.lower_link(line, level=Sureness.NONE)

        assert result.refusal is LowerLinkRefusal.UNKNOWN_LINK
        assert (await _owners_link(subject, line)).lowerings == ()

    async def test_a_link_to_another_identity_is_an_unknown_link(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        """§2:4, §4:4: only a link to the owner's identity is named."""
        subject = linked_accounts_subject
        subject.identities.hold_identity("person:other")
        other = Account(kind="telegram", identifier="777")
        made = await subject.identities.link(
            "person:other", other, act=_LinkAct(how=LinkActHow.DEVICE, by=OWNER_PERSON_ID)
        )
        assert made.record_id is not None

        result = await subject.engine.lower_link(made.record_id, level=Sureness.NONE)

        assert result.refusal is LowerLinkRefusal.UNKNOWN_LINK
        assert all(one.link_id != made.record_id for one in await subject.engine.linked_accounts())

    async def test_a_repeated_lowering_is_unchanged_once_a_later_build_lowers_the_most(
        self, linked_accounts_subject: LinkedAccountsSubject, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """§2:4, §2:5: ``unchanged`` is decided ahead of ``not_a_lowering``, and it stands.

        A later build declaring the line's most at the lowering's own level is stood in
        for by moving the declaration the running process reads: the lowering still
        stands and is still listed, and repeating it is ``unchanged``, not refused.
        """
        subject = linked_accounts_subject
        line = await _link_id(subject, LINE)
        first = await subject.engine.lower_link(line, level=Sureness.WEAK)
        monkeypatch.setattr(
            channel_validation,
            "_MOST_SURENESS",
            MappingProxyType({"conversation": Sureness.NORMAL, "telegram": Sureness.WEAK}),
        )

        again = await subject.engine.lower_link(line, level=Sureness.WEAK)

        assert again.outcome is LowerLinkOutcome.UNCHANGED
        assert again.lowering == first.lowering
        listed = {one.link_id: one for one in await subject.engine.linked_accounts()}
        assert listed[line].most is Sureness.WEAK
        assert listed[line].lowerings == (first.lowering,)
        refused = await subject.engine.lower_link(
            await _link_id(subject, HUB_CHAT), level=Sureness.NORMAL
        )
        assert refused.refusal is LowerLinkRefusal.NOT_A_LOWERING

    async def test_a_storeless_hub_names_no_link(
        self, linked_accounts_storeless: AssistantEngine
    ) -> None:
        result = await linked_accounts_storeless.lower_link("link:1", level=Sureness.NONE)

        assert result.refusal is LowerLinkRefusal.UNKNOWN_LINK

    @pytest.mark.parametrize("link_id", ["", "   "])
    async def test_a_blank_link_id_is_refused_before_any_io(
        self, linked_accounts_subject: LinkedAccountsSubject, link_id: str
    ) -> None:
        """§2:7: ``ValueError`` before any I/O, so a failing store is never reached."""
        subject = linked_accounts_subject
        subject.identities.fail_next()

        with pytest.raises(ValueError, match="link_id"):
            await subject.engine.lower_link(link_id, level=Sureness.NONE)

    @pytest.mark.parametrize("level", ["lowest", "", 0, None])
    async def test_a_level_not_one_of_the_four_is_refused_before_any_io(
        self, linked_accounts_subject: LinkedAccountsSubject, level: object
    ) -> None:
        subject = linked_accounts_subject
        line = await _link_id(subject, LINE)
        subject.identities.fail_next()

        with pytest.raises(ValueError, match="level"):
            await subject.engine.lower_link(line, level=level)  # type: ignore[arg-type]

    async def test_a_padded_link_id_names_the_link(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        """Clause 2: an identifier is stripped, as every one on the surface is."""
        subject = linked_accounts_subject
        line = await _link_id(subject, LINE)

        result = await subject.engine.lower_link(f"  {line} ", level=Sureness.NONE)

        assert result.outcome is LowerLinkOutcome.LOWERED

    async def test_a_store_fault_on_lowering_is_raised(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        subject = linked_accounts_subject
        line = await _link_id(subject, LINE)
        subject.identities.fail_next()

        with pytest.raises(IdentityStoreError):
            await subject.engine.lower_link(line, level=Sureness.NONE)

    # --- withdrawing (§2:6, §5) ------------------------------------------------

    async def test_a_withdrawal_ends_the_lowering_and_restores_the_level(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        """§2:6: ``withdrawn`` with the entry after the act; the lowering no longer shown."""
        subject = linked_accounts_subject
        line = await _link_id(subject, LINE)
        lowered = await subject.engine.lower_link(line, level=Sureness.NONE)
        assert lowered.lowering is not None

        result = await subject.engine.withdraw_lowering(lowered.lowering.id)

        assert result.outcome is WithdrawLoweringOutcome.WITHDRAWN
        assert result.entry is not None
        assert result.entry.link_id == line
        assert result.entry.lowerings == ()
        assert result.entry.level is Sureness.NORMAL
        held = await _owners_link(subject, line)
        assert held.standing_lowerings == ()
        listed = {one.link_id: one for one in await subject.engine.linked_accounts()}
        assert listed[line] == result.entry

    async def test_a_second_withdrawal_is_not_standing_and_no_error(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        subject = linked_accounts_subject
        line = await _link_id(subject, LINE)
        lowered = await subject.engine.lower_link(line, level=Sureness.WEAK)
        assert lowered.lowering is not None
        await subject.engine.withdraw_lowering(lowered.lowering.id)

        again = await subject.engine.withdraw_lowering(lowered.lowering.id)

        assert again.outcome is WithdrawLoweringOutcome.NOT_STANDING
        assert again.entry is None

    async def test_a_lowering_never_made_is_not_standing(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        result = await linked_accounts_subject.engine.withdraw_lowering("lowering:none")

        assert result.outcome is WithdrawLoweringOutcome.NOT_STANDING

    async def test_a_lowering_on_an_ended_link_is_not_standing(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        """§6:3: once its link ends, a lowering stands on no link, and nothing is written."""
        subject = linked_accounts_subject
        line = await _link_id(subject, LINE)
        lowered = await subject.engine.lower_link(line, level=Sureness.NONE)
        assert lowered.lowering is not None
        await subject.identities.end_link(line)

        result = await subject.engine.withdraw_lowering(lowered.lowering.id)

        assert result.outcome is WithdrawLoweringOutcome.NOT_STANDING
        held = await _owners_link(subject, line)
        assert [one.withdrawn_at for one in held.lowerings] == [None]

    async def test_withdrawing_one_lowering_leaves_the_other(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        subject = linked_accounts_subject
        line = await _link_id(subject, LINE)
        weak = await subject.engine.lower_link(line, level=Sureness.WEAK)
        none = await subject.engine.lower_link(line, level=Sureness.NONE)
        assert weak.lowering is not None
        assert none.lowering is not None

        result = await subject.engine.withdraw_lowering(none.lowering.id)

        assert result.entry is not None
        assert result.entry.lowerings == (weak.lowering,)
        assert result.entry.level is Sureness.WEAK

    async def test_every_link_lowered_to_none_is_still_listed_and_restored(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        """§4:5, §5:1: no level gates the members, whatever level every link stands at."""
        subject = linked_accounts_subject
        made = [
            await subject.engine.lower_link(await _link_id(subject, one), level=Sureness.NONE)
            for one in CONFIGURED
        ]

        listed = await subject.engine.linked_accounts()
        assert {one.level for one in listed} == {Sureness.NONE}
        for one in made:
            assert one.lowering is not None
            restored = await subject.engine.withdraw_lowering(one.lowering.id)
            assert restored.outcome is WithdrawLoweringOutcome.WITHDRAWN

        assert {one.level for one in await subject.engine.linked_accounts()} == {Sureness.NORMAL}

    async def test_a_storeless_hub_has_no_standing_lowering(
        self, linked_accounts_storeless: AssistantEngine
    ) -> None:
        result = await linked_accounts_storeless.withdraw_lowering("lowering:1")

        assert result.outcome is WithdrawLoweringOutcome.NOT_STANDING

    @pytest.mark.parametrize("lowering_id", ["", "\t"])
    async def test_a_blank_lowering_id_is_refused_before_any_io(
        self, linked_accounts_subject: LinkedAccountsSubject, lowering_id: str
    ) -> None:
        subject = linked_accounts_subject
        subject.identities.fail_next()

        with pytest.raises(ValueError, match="lowering_id"):
            await subject.engine.withdraw_lowering(lowering_id)

    async def test_a_store_fault_on_withdrawing_is_raised(
        self, linked_accounts_subject: LinkedAccountsSubject
    ) -> None:
        subject = linked_accounts_subject
        subject.identities.fail_next()

        with pytest.raises(IdentityStoreError):
            await subject.engine.withdraw_lowering("lowering:1")
