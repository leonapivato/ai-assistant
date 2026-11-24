"""Shared obligations of the owner's permission lines on ``AssistantEngine`` (ADR-0376 §4 to §6).

Every implementation answers ``permission_lines``, ``make_grant``, ``make_limit`` and
``remove_line`` from the same line store, against the same declared tools and the same
connections the hub holds, with the same outcomes in the order §4:5 fixes, the same
refusals before any I/O (§4:7), the owner as the maker and remover of every line (§6:3),
and the listing showing what §5 names and no more. A subject is handed to the suite with
an empty :class:`~ai_assistant.testing.FakePermissionLineStore`, the tools
:data:`DECLARED` names and the things :data:`HELD` names, as a hub with the line and one
email account configured starts.

A mixin, as ``linked_accounts_contract`` is, so the engine, the canonical fake and the wire
client each bind it in the file that binds the rest of the suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.errors import OversizedValueError, PermissionLineStoreError
from ai_assistant.core.types import (
    ANYONE_GROUP_ID,
    OWN_CHAT_CONNECTION,
    OWNER_PERSON_ID,
    GrantHow,
    MakeLineOutcome,
    MakeLineRefusal,
    PermissionLineEntry,
    PermissionLineKind,
    RemoveLineOutcome,
    Sureness,
    ThingKey,
    ThingKind,
)
from ai_assistant.orchestration.matter_calls import MATTER_CALLS
from ai_assistant.orchestration.message_tools import TEXT_CALL
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.testing import FakePermissionLineStore

#: The contract limit each subject is built at: room for the listing of a few lines, and
#: small enough that a few dozen more are past it.
LINES_LIMIT: Final = 4096

#: The tools each subject declares, as the engine's phases declare them over an invoker
#: holding none: the candidate's ``remember_fact``, the calls on running work the engine
#: always attaches, whose calls have no thing, and ``text``, whose capability ``send_text``
#: has one (ADR-0376 §2:3).
DECLARED: Final = (REMEMBER_CANDIDATE, *MATTER_CALLS, TEXT_CALL)

#: The line's place and an email account, as the start records them (ADR-0381 §2:1).
LINE_PLACE: Final = "telegram:conn-line/424242"
MAIL: Final = "account:mail-1"

#: What each subject's hub holds as it starts: the system's own chat, the line's place,
#: the schedule and the approvals, one email account and one source (ADR-0381 §2:1).
HELD: Final = (
    ThingKey(kind=ThingKind.CONNECTION, identifier=OWN_CHAT_CONNECTION),
    ThingKey(kind=ThingKind.CONNECTION, identifier=LINE_PLACE),
    ThingKey(kind=ThingKind.CONNECTION, identifier="task_scheduler:schedule"),
    ThingKey(kind=ThingKind.CONNECTION, identifier="approvals:approvals"),
    ThingKey(kind=ThingKind.CONNECTION, identifier=MAIL),
    ThingKey(kind=ThingKind.SOURCE, identifier="calendar"),
)

_TEXT: Final = str(TEXT_CALL.capability)
_REMEMBER: Final = str(REMEMBER_CANDIDATE.capability)


@dataclass(frozen=True, slots=True)
class PermissionLinesSubject:
    """An engine and the line store it answers from, seeded from the test process.

    Attributes:
        engine: The subject under test.
        lines: The store its four members read and write.
    """

    engine: AssistantEngine
    lines: FakePermissionLineStore


def _defaults() -> set[PermissionLineEntry]:
    """Each declared tool's default line, as §5:1 shows it."""
    entries: set[PermissionLineEntry] = set()
    for tool in DECLARED:
        assert tool.default_grant is not None
        entries.add(
            PermissionLineEntry(
                kind=PermissionLineKind.GRANT,
                who=ANYONE_GROUP_ID,
                action=tool.capability,
                how=tool.default_grant.how,
                bar=tool.default_grant.bar,
                tool_id=tool.id,
            )
        )
    return entries


async def _grant(engine: AssistantEngine, **parts: object) -> object:
    """``make_grant`` with the owner's grant of ``send_text`` at weak, ``parts`` changing it."""
    arguments: dict[str, object] = {
        "who": OWNER_PERSON_ID,
        "action": _TEXT,
        "how": GrantHow.ALLOWED,
        "bar": Sureness.WEAK,
    }
    arguments.update(parts)
    return await engine.make_grant(**arguments)  # type: ignore[arg-type]


class PermissionLinesContract:
    """The four members through the engine, the fake and the wire client alike."""

    @pytest.fixture
    def permission_lines_subject(self) -> PermissionLinesSubject:
        """Override with an implementation over an empty store, :data:`DECLARED` and :data:`HELD`.

        Built at :data:`LINES_LIMIT`.
        """
        raise NotImplementedError

    @pytest.fixture
    def permission_lines_storeless(self) -> AssistantEngine:
        """Override with an implementation handed no line store, but :data:`DECLARED` and
        :data:`HELD`."""
        raise NotImplementedError

    # --- the listing (§4:2, §5) ------------------------------------------------

    async def test_a_hub_with_no_made_line_lists_each_declared_tools_default(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        """§4:2, §5:1, §3:1: a default line to anyone, its tool's id, and no identifier."""
        listed = await permission_lines_subject.engine.permission_lines()

        assert isinstance(listed, tuple)
        assert len(listed) == len(DECLARED)
        assert set(listed) == _defaults()

    async def test_each_made_line_is_listed_with_its_identifier_and_its_maker(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        """§5:1: a made line's parts, its identifier and its maker, beside the defaults."""
        subject = permission_lines_subject
        grant = await subject.engine.make_grant(
            who=OWNER_PERSON_ID,
            action=_TEXT,
            how=GrantHow.WITH_APPROVAL,
            bar=Sureness.NORMAL,
            thing=LINE_PLACE,
            condition=OWN_CHAT_CONNECTION,
        )
        limit = await subject.engine.make_limit(who=ANYONE_GROUP_ID, action=_REMEMBER)
        assert grant.line is not None
        assert limit.line is not None

        listed = await subject.engine.permission_lines()

        made = {one for one in listed if one.made}
        assert made == {
            PermissionLineEntry(
                kind=PermissionLineKind.GRANT,
                who=OWNER_PERSON_ID,
                action=_TEXT,
                thing=LINE_PLACE,
                how=GrantHow.WITH_APPROVAL,
                bar=Sureness.NORMAL,
                condition=OWN_CHAT_CONNECTION,
                line_id=grant.line.id,
                made_by=OWNER_PERSON_ID,
            ),
            PermissionLineEntry(
                kind=PermissionLineKind.LIMIT,
                who=ANYONE_GROUP_ID,
                action=_REMEMBER,
                line_id=limit.line.id,
                made_by=OWNER_PERSON_ID,
            ),
        }
        assert {one for one in listed if not one.made} == _defaults()

    async def test_an_entry_carries_no_field_beyond_section_5(self) -> None:
        """§5:1, §5:2: exactly the fields named, so no instant, secret or coverage rides along."""
        assert set(PermissionLineEntry.model_fields) == {
            "kind",
            "who",
            "action",
            "thing",
            "how",
            "bar",
            "condition",
            "line_id",
            "made_by",
            "tool_id",
        }

    async def test_a_removed_line_is_not_listed(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        """§4:2: each made line not removed."""
        subject = permission_lines_subject
        made = await _grant(subject.engine)
        line_id = made.line.id  # type: ignore[attr-defined]
        await subject.engine.remove_line(line_id)

        listed = await subject.engine.permission_lines()

        assert all(one.line_id != line_id for one in listed)
        assert set(listed) == _defaults()

    async def test_a_storeless_hub_lists_the_default_lines_alone(
        self, permission_lines_storeless: AssistantEngine
    ) -> None:
        assert set(await permission_lines_storeless.permission_lines()) == _defaults()

    async def test_a_listing_of_lines_past_the_limit_is_refused_whole(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        """§4:2: never truncated; refused with ``OversizedValueError``."""
        subject = permission_lines_subject
        for bar in Sureness:
            for how in GrantHow:
                for thing in (None, OWN_CHAT_CONNECTION, LINE_PLACE, MAIL):
                    await _grant(subject.engine, how=how, bar=bar, thing=thing)

        with pytest.raises(OversizedValueError):
            await subject.engine.permission_lines()

    async def test_a_store_fault_on_the_listing_is_raised(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        """§4:7: a store that cannot be read raises its contract's error."""
        subject = permission_lines_subject
        subject.lines.fail_next()

        with pytest.raises(PermissionLineStoreError):
            await subject.engine.permission_lines()

    # --- making (§4:3 to §4:5) -------------------------------------------------

    async def test_a_grant_is_made_by_the_owner_with_exactly_its_parts(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        """§4:3, §6:3: ``made``, the line as the store recorded it, made by the owner."""
        subject = permission_lines_subject

        result = await subject.engine.make_grant(
            who=ANYONE_GROUP_ID,
            action=_TEXT,
            how=GrantHow.ALLOWED,
            bar=Sureness.NORMAL,
            thing=MAIL,
            condition=LINE_PLACE,
        )

        assert result.outcome is MakeLineOutcome.MADE
        assert result.refusal is None
        assert result.line is not None
        line = result.line
        assert line.standing
        assert (line.kind, line.who, line.action, line.thing, line.how, line.bar) == (
            PermissionLineKind.GRANT,
            ANYONE_GROUP_ID,
            _TEXT,
            MAIL,
            GrantHow.ALLOWED,
            Sureness.NORMAL,
        )
        assert line.condition == LINE_PLACE
        assert line.made_by == OWNER_PERSON_ID
        assert await subject.lines.standing() == (line,)

    async def test_a_limit_is_made_by_the_owner_with_no_how_bar_or_condition(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        """§4:4, §6:3: a limit's parts are who, action and thing."""
        subject = permission_lines_subject

        result = await subject.engine.make_limit(
            who=OWNER_PERSON_ID, action=_TEXT, thing=OWN_CHAT_CONNECTION
        )

        assert result.outcome is MakeLineOutcome.MADE
        assert result.line is not None
        line = result.line
        assert (line.kind, line.who, line.action, line.thing) == (
            PermissionLineKind.LIMIT,
            OWNER_PERSON_ID,
            _TEXT,
            OWN_CHAT_CONNECTION,
        )
        assert (line.how, line.bar, line.condition) == (None, None, None)
        assert line.made_by == OWNER_PERSON_ID
        assert await subject.lines.standing() == (line,)

    async def test_a_repeated_grant_is_unchanged_and_makes_no_second(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        """§4:5's fifth step: the standing line, and nothing written."""
        subject = permission_lines_subject
        first = await _grant(subject.engine, thing=LINE_PLACE)

        again = await _grant(subject.engine, thing=LINE_PLACE)

        assert again.outcome is MakeLineOutcome.UNCHANGED  # type: ignore[attr-defined]
        assert again.line == first.line  # type: ignore[attr-defined]
        assert len(await subject.lines.standing()) == 1

    async def test_a_repeated_limit_is_unchanged_and_a_grant_of_the_same_parts_is_not_one(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        """§4:5: the same kind with exactly the same parts; a grant is not a limit."""
        subject = permission_lines_subject
        limit = await subject.engine.make_limit(who=OWNER_PERSON_ID, action=_TEXT)
        grant = await _grant(subject.engine)

        again = await subject.engine.make_limit(who=OWNER_PERSON_ID, action=_TEXT)

        assert grant.outcome is MakeLineOutcome.MADE  # type: ignore[attr-defined]
        assert again.outcome is MakeLineOutcome.UNCHANGED
        assert again.line == limit.line
        assert len(await subject.lines.standing()) == 2

    async def test_a_grant_differing_in_one_part_is_a_second_line(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        subject = permission_lines_subject
        await _grant(subject.engine)

        other = await _grant(subject.engine, bar=Sureness.NORMAL)

        assert other.outcome is MakeLineOutcome.MADE  # type: ignore[attr-defined]
        assert len(await subject.lines.standing()) == 2

    async def test_how_and_bar_given_by_their_values_are_those_values(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        result = await _grant(permission_lines_subject.engine, how="with_approval", bar="strong")

        line = result.line  # type: ignore[attr-defined]
        assert (line.how, line.bar) == (GrantHow.WITH_APPROVAL, Sureness.STRONG)

    async def test_padded_identifiers_name_what_they_name(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        """Clause 2: every identifier on the surface is stripped."""
        result = await _grant(
            permission_lines_subject.engine,
            who=f" {ANYONE_GROUP_ID} ",
            action=f"  {_TEXT}",
            thing=f"{LINE_PLACE}  ",
            condition=f" {OWN_CHAT_CONNECTION}",
        )

        line = result.line  # type: ignore[attr-defined]
        assert (line.who, line.action, line.thing, line.condition) == (
            ANYONE_GROUP_ID,
            _TEXT,
            LINE_PLACE,
            OWN_CHAT_CONNECTION,
        )

    @pytest.mark.parametrize("who", ["person:guest", "group:family", OWNER_PERSON_ID.upper()])
    async def test_a_who_neither_the_owner_nor_anyone_is_refused(
        self, permission_lines_subject: PermissionLinesSubject, who: str
    ) -> None:
        """§4:5's first refusal, before the action is weighed; nothing is written."""
        subject = permission_lines_subject

        grant = await _grant(subject.engine, who=who, action="no_such_capability")
        limit = await subject.engine.make_limit(who=who, action=_TEXT)

        for result in (grant, limit):
            assert result.outcome is MakeLineOutcome.REFUSED  # type: ignore[attr-defined]
            assert result.refusal is MakeLineRefusal.UNKNOWN_WHO  # type: ignore[attr-defined]
            assert result.line is None  # type: ignore[attr-defined]
        assert await subject.lines.standing() == ()

    @pytest.mark.parametrize("action", ["no_such_capability", "send email", "text"])
    async def test_an_action_no_declared_tool_has_is_refused(
        self, permission_lines_subject: PermissionLinesSubject, action: str
    ) -> None:
        """§4:5's second refusal, before the thing is weighed. A tool's id is no action."""
        subject = permission_lines_subject

        grant = await _grant(subject.engine, action=action, thing="no:such")
        limit = await subject.engine.make_limit(who=ANYONE_GROUP_ID, action=action)

        for result in (grant, limit):
            assert result.refusal is MakeLineRefusal.UNKNOWN_ACTION  # type: ignore[attr-defined]
        assert await subject.lines.standing() == ()

    async def test_a_thing_on_an_action_whose_calls_have_none_is_refused(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        """§4:5's third refusal, before the connection is weighed (§2:3)."""
        subject = permission_lines_subject

        grant = await _grant(subject.engine, action=_REMEMBER, thing="no:such")
        limit = await subject.engine.make_limit(
            who=OWNER_PERSON_ID, action=_REMEMBER, thing=OWN_CHAT_CONNECTION
        )

        for result in (grant, limit):
            assert result.refusal is MakeLineRefusal.NO_THING  # type: ignore[attr-defined]
        assert await subject.lines.standing() == ()

    async def test_a_condition_on_an_action_whose_calls_have_no_thing_is_made(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        """§2:6: a condition is where the work's inputs came by, not what the call acts on."""
        result = await _grant(
            permission_lines_subject.engine, action=_REMEMBER, condition=LINE_PLACE
        )

        assert result.outcome is MakeLineOutcome.MADE  # type: ignore[attr-defined]

    @pytest.mark.parametrize(
        "connection",
        [
            "telegram:conn-other/1",
            "account:mail-2",
            "task_scheduler:schedule",
            "approvals:approvals",
            "calendar",
            "conversation:abc",
            "no colon",
        ],
    )
    async def test_a_connection_the_hub_does_not_have_or_no_line_names_is_refused(
        self, permission_lines_subject: PermissionLinesSubject, connection: str
    ) -> None:
        """§4:5's fourth refusal: as a thing or a condition, on a grant or a limit (§2:4)."""
        subject = permission_lines_subject

        results = [
            await _grant(subject.engine, thing=connection),
            await _grant(subject.engine, condition=connection),
            await _grant(subject.engine, thing=OWN_CHAT_CONNECTION, condition=connection),
            await subject.engine.make_limit(who=OWNER_PERSON_ID, action=_TEXT, thing=connection),
        ]

        for result in results:
            refusal = result.refusal  # type: ignore[attr-defined]
            assert refusal is MakeLineRefusal.UNKNOWN_CONNECTION
        assert await subject.lines.standing() == ()

    async def test_a_storeless_hub_refuses_what_it_refuses_and_raises_for_a_making(
        self, permission_lines_storeless: AssistantEngine
    ) -> None:
        """§4:7: a store that cannot be written raises its error; a refusal is still one."""
        refused = await _grant(permission_lines_storeless, action="no_such_capability")

        assert refused.refusal is MakeLineRefusal.UNKNOWN_ACTION  # type: ignore[attr-defined]
        with pytest.raises(PermissionLineStoreError):
            await _grant(permission_lines_storeless)

    async def test_a_store_fault_on_a_making_is_raised(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        subject = permission_lines_subject
        subject.lines.fail_next()

        with pytest.raises(PermissionLineStoreError):
            await _grant(subject.engine)

    @pytest.mark.parametrize("name", ["who", "action", "thing", "condition"])
    @pytest.mark.parametrize("blank", ["", "   "])
    async def test_a_blank_identifier_is_refused_before_any_io(
        self, permission_lines_subject: PermissionLinesSubject, name: str, blank: str
    ) -> None:
        """§4:7: ``ValueError`` before any I/O, so a failing store is never reached."""
        subject = permission_lines_subject
        subject.lines.fail_next()

        with pytest.raises(ValueError, match=name):
            await _grant(subject.engine, **{name: blank})

    @pytest.mark.parametrize("name", ["who", "action", "thing"])
    async def test_a_blank_identifier_on_a_limit_is_refused_before_any_io(
        self, permission_lines_subject: PermissionLinesSubject, name: str
    ) -> None:
        subject = permission_lines_subject
        subject.lines.fail_next()
        arguments: dict[str, object] = {"who": OWNER_PERSON_ID, "action": _TEXT, name: " "}

        with pytest.raises(ValueError, match=name):
            await subject.engine.make_limit(**arguments)  # type: ignore[arg-type]

    @pytest.mark.parametrize("how", ["maybe", "", 0, None])
    async def test_a_how_not_one_of_its_values_is_refused_before_any_io(
        self, permission_lines_subject: PermissionLinesSubject, how: object
    ) -> None:
        subject = permission_lines_subject
        subject.lines.fail_next()

        with pytest.raises(ValueError, match="how"):
            await _grant(subject.engine, how=how)

    @pytest.mark.parametrize("bar", ["medium", "", 2, None])
    async def test_a_bar_not_one_of_the_four_is_refused_before_any_io(
        self, permission_lines_subject: PermissionLinesSubject, bar: object
    ) -> None:
        subject = permission_lines_subject
        subject.lines.fail_next()

        with pytest.raises(ValueError, match="bar"):
            await _grant(subject.engine, bar=bar)

    # --- removing (§4:6) -------------------------------------------------------

    async def test_a_removal_is_recorded_by_the_owner_and_the_line_kept(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        """§4:6, §4:8, §6:3: ``removed`` with the line as it stood; the store keeps it,
        its removal recorded by the owner."""
        subject = permission_lines_subject
        made = await _grant(subject.engine, thing=LINE_PLACE)
        line = made.line  # type: ignore[attr-defined]

        result = await subject.engine.remove_line(line.id)

        assert result.outcome is RemoveLineOutcome.REMOVED
        assert result.line == line
        assert await subject.lines.standing() == ()
        kept = await subject.lines.line(line.id)
        assert kept is not None
        assert kept.parts == line.parts
        assert (kept.made_by, kept.removed_by) == (OWNER_PERSON_ID, OWNER_PERSON_ID)
        assert not kept.standing

    async def test_a_line_removed_already_is_not_standing(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        """§4:6: not an error, and nothing written."""
        subject = permission_lines_subject
        made = await _grant(subject.engine)
        line_id = made.line.id  # type: ignore[attr-defined]
        first = await subject.engine.remove_line(line_id)

        again = await subject.engine.remove_line(line_id)

        assert first.outcome is RemoveLineOutcome.REMOVED
        assert again.outcome is RemoveLineOutcome.NOT_STANDING
        assert again.line is None
        kept = await subject.lines.line(line_id)
        assert kept is not None
        assert not kept.standing

    async def test_an_identifier_no_line_was_made_under_is_not_standing(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        """§4:6, §3:3: a tool's id names no made line, so its default is never removed."""
        subject = permission_lines_subject

        for named in ("line:999", str(TEXT_CALL.id)):
            result = await subject.engine.remove_line(named)

            assert result.outcome is RemoveLineOutcome.NOT_STANDING
        assert set(await subject.engine.permission_lines()) == _defaults()

    async def test_a_padded_line_id_names_the_line(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        subject = permission_lines_subject
        made = await _grant(subject.engine)

        result = await subject.engine.remove_line(f"  {made.line.id} ")  # type: ignore[attr-defined]

        assert result.outcome is RemoveLineOutcome.REMOVED

    async def test_a_line_made_again_after_its_removal_is_a_new_line(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        """ADR-0376 §4:8: an identifier is never reused."""
        subject = permission_lines_subject
        first = await _grant(subject.engine)
        await subject.engine.remove_line(first.line.id)  # type: ignore[attr-defined]

        again = await _grant(subject.engine)

        assert again.outcome is MakeLineOutcome.MADE  # type: ignore[attr-defined]
        assert again.line.id != first.line.id  # type: ignore[attr-defined]

    async def test_a_storeless_hub_removes_nothing(
        self, permission_lines_storeless: AssistantEngine
    ) -> None:
        result = await permission_lines_storeless.remove_line("line:1")

        assert result.outcome is RemoveLineOutcome.NOT_STANDING

    @pytest.mark.parametrize("line_id", ["", "   "])
    async def test_a_blank_line_id_is_refused_before_any_io(
        self, permission_lines_subject: PermissionLinesSubject, line_id: str
    ) -> None:
        subject = permission_lines_subject
        subject.lines.fail_next()

        with pytest.raises(ValueError, match="line_id"):
            await subject.engine.remove_line(line_id)

    async def test_a_store_fault_on_a_removal_is_raised(
        self, permission_lines_subject: PermissionLinesSubject
    ) -> None:
        subject = permission_lines_subject
        subject.lines.fail_next()

        with pytest.raises(PermissionLineStoreError):
            await subject.engine.remove_line("line:1")
