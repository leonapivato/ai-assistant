"""The check (ADR-0367 §4, §5; ADR-0376 §2, §3; ADR-0379 §2 to §4), as a function of its arguments.

Table-driven over ADR-0379's rules and worked calls, ADR-0376's worked lines and its rule for
when a line covers a call, and ADR-0367 §5:1 and §5:2's levels; then, for every tool the
composed hub declares, the owner at normal with no made line gets *allowed, on no line*, as
today's rules allow it (#3678, "Nothing changes for what the owner asks").
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    ANYONE_GROUP_ID,
    OWN_CHAT_CONNECTION,
    OWNER_PERSON_ID,
    BoundAccount,
    CallCheckKind,
    CheckedFor,
    CheckOutcome,
    CheckOutcomeKind,
    DataTier,
    DefaultGrant,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    GrantHow,
    PermissionLine,
    PermissionLineKind,
    SpanCoverage,
    Sureness,
    ToolDefinition,
)
from ai_assistant.orchestration.message_tools import TEXT_CALL
from ai_assistant.orchestration.permission_check import (
    CheckSubject,
    call_thing,
    check_call,
    checked,
    place_connection,
)
from ai_assistant.tools.send_email import EMAIL

if TYPE_CHECKING:
    from pathlib import Path

_AT: Final = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
_A: Final = "account:conn-a"
_B: Final = "account:conn-b"
_LINE: Final = "telegram:line"

_OWNER_AT: Final = {level: CheckedFor.for_person(OWNER_PERSON_ID, level) for level in Sureness}
_NORMAL: Final = _OWNER_AT[Sureness.NORMAL]
_WEAK: Final = _OWNER_AT[Sureness.WEAK]


def _tool(
    capability: str = "send_email",
    *,
    how: GrantHow = GrantHow.ALLOWED,
    bar: Sureness | None = Sureness.NORMAL,
) -> ToolDefinition:
    """A declaration of ``capability`` whose default grant is ``how`` at ``bar``, or none."""
    grant = None if bar is None else DefaultGrant(how=how, bar=bar)
    return ToolDefinition.model_validate(
        {
            **TEXT_CALL.model_dump(),
            "id": capability,
            "capability": capability,
            "default_grant": None if grant is None else grant.model_dump(),
        }
    )


def _line(  # noqa: PLR0913 — one keyword per part of a line a case varies
    line_id: str,
    kind: PermissionLineKind = PermissionLineKind.GRANT,
    *,
    who: str = OWNER_PERSON_ID,
    action: str = "send_email",
    thing: str | None = None,
    how: GrantHow | None = GrantHow.ALLOWED,
    bar: Sureness | None = Sureness.NORMAL,
    condition: str | None = None,
    after: int = 0,
    removed: bool = False,
) -> PermissionLine:
    """A made line, recorded ``after`` minutes past :data:`_AT`."""
    made_at = _AT + timedelta(minutes=after)
    limit = kind is PermissionLineKind.LIMIT
    return PermissionLine(
        id=line_id,
        kind=kind,
        who=who,
        action=action,
        thing=thing,
        how=None if limit else how,
        bar=None if limit else bar,
        condition=None if limit else condition,
        made_by=OWNER_PERSON_ID,
        made_at=made_at,
        removed_by=OWNER_PERSON_ID if removed else None,
        removed_at=made_at + timedelta(minutes=1) if removed else None,
    )


def _limit(line_id: str, **parts: object) -> PermissionLine:
    return _line(line_id, PermissionLineKind.LIMIT, **parts)  # type: ignore[arg-type]  # the parts a case varies


def _outcome(
    kind: CheckOutcomeKind, *, line: str | None = None, bar: Sureness | None = None
) -> CheckOutcome:
    return CheckOutcome(kind=kind, line=line, bar=bar)


_NO_LINE: Final = _outcome(CheckOutcomeKind.ALLOWED_ON_NO_LINE)
_NO_GRANT: Final = _outcome(CheckOutcomeKind.NOT_DONE_NO_GRANT)
_ASKS: Final = _outcome(CheckOutcomeKind.NEEDS_YES_WITH_APPROVAL)


def _short(bar: Sureness) -> CheckOutcome:
    return _outcome(CheckOutcomeKind.NEEDS_YES_SHORTFALL, bar=bar)


def _resting(line_id: str) -> CheckOutcome:
    return _outcome(CheckOutcomeKind.ALLOWED_ON_MADE_GRANT, line=line_id)


def _limited(line_id: str | None = None) -> CheckOutcome:
    return _outcome(CheckOutcomeKind.NOT_DONE_LIMIT, line=line_id)


#: Each case: its name, the lines, the declaration, the call's thing, whom the check runs
#: for, the connection a condition is met for, and the outcome.
_CASES: Final[
    list[
        tuple[
            str,
            tuple[PermissionLine, ...],
            ToolDefinition,
            str | None,
            CheckedFor,
            str | None,
            CheckOutcome,
        ]
    ]
] = [
    # ADR-0379 §3's three worked calls.
    ("worked: the default alone, at normal", (), _tool(), _A, _NORMAL, None, _NO_LINE),
    (
        "worked: the owner's grant beside the default, at normal",
        (_line("g1"),),
        _tool(),
        _A,
        _NORMAL,
        None,
        _resting("g1"),
    ),
    (
        "worked: at weak, the owner's limit on account A covers a call from A",
        (_limit("l1", thing=_A),),
        _tool(),
        _A,
        _WEAK,
        None,
        _limited("l1"),
    ),
    (
        "worked: at weak, a call from account B falls short of the default's normal",
        (_limit("l1", thing=_A),),
        _tool(),
        _B,
        _WEAK,
        None,
        _short(Sureness.NORMAL),
    ),
    # §2:2: a covering limit decides, whatever grants cover, at every level.
    (
        "§2:2: a limit over the owner's grant",
        (_line("g1", bar=Sureness.WEAK), _limit("l1")),
        _tool(),
        None,
        _OWNER_AT[Sureness.STRONG],
        None,
        _limited("l1"),
    ),
    # §2:3: a grant that allows decides over one that asks (§5's note).
    (
        "§2:3: the owner's grant that asks, beside a default that allows",
        (_line("g1", how=GrantHow.WITH_APPROVAL),),
        _tool(),
        None,
        _NORMAL,
        None,
        _NO_LINE,
    ),
    # §2:4, §4:2: only a grant that asks applies; a made one that asks is never named.
    (
        "§2:4: only the owner's grant that asks applies",
        (_line("g1", how=GrantHow.WITH_APPROVAL),),
        _tool(bar=None),
        None,
        _NORMAL,
        None,
        _ASKS,
    ),
    (
        "§2:4: a default that asks",
        (),
        _tool(how=GrantHow.WITH_APPROVAL, bar=Sureness.WEAK),
        None,
        _NORMAL,
        None,
        _ASKS,
    ),
    # §2:5: the least level at which a covering grant would apply, one that asks counted.
    (
        "§2:5: the least bar among covering grants",
        (_line("g1", bar=Sureness.STRONG), _line("g2", how=GrantHow.WITH_APPROVAL)),
        _tool(bar=Sureness.STRONG),
        None,
        _WEAK,
        None,
        _short(Sureness.NORMAL),
    ),
    (
        "§2:5, ADR-0367 §5:2: a named grant at none needs weak",
        (_line("g1", bar=Sureness.NONE),),
        _tool(bar=None),
        None,
        _OWNER_AT[Sureness.NONE],
        None,
        _short(Sureness.WEAK),
    ),
    # §2:6, ADR-0380 §2:2: no default and no line is no grant.
    ("§2:6: no grant covers it", (), _tool(bar=None), None, _NORMAL, None, _NO_GRANT),
    # §2:8: the earliest made, of two at one moment the identifier sorting first.
    (
        "§2:8: the line made first is named",
        (_line("g-late", after=5), _line("g-early", after=1)),
        _tool(),
        None,
        _NORMAL,
        None,
        _resting("g-early"),
    ),
    (
        "§2:8: of two made at once, the identifier sorting first",
        (_line("g-b"), _line("g-a")),
        _tool(),
        None,
        _NORMAL,
        None,
        _resting("g-a"),
    ),
    (
        "§2:8: of two limits, the earliest is named",
        (_limit("l-late", after=3), _limit("l-early")),
        _tool(),
        None,
        _NORMAL,
        None,
        _limited("l-early"),
    ),
    # §2:9: a grant that falls short beside one that applies changes nothing.
    (
        "§2:9: the owner's strong grant beside the default, at normal",
        (_line("g1", bar=Sureness.STRONG),),
        _tool(),
        None,
        _NORMAL,
        None,
        _NO_LINE,
    ),
    # ADR-0367 §5:1: a made grant applies at or above its bar.
    (
        "ADR-0367 §5:1: the owner's grant at weak, no default",
        (_line("g1", bar=Sureness.WEAK),),
        _tool(bar=None),
        None,
        _WEAK,
        None,
        _resting("g1"),
    ),
    # ADR-0376 §2:5: a line's thing.
    (
        "ADR-0376 §2:5: a grant for account A covers no call from B",
        (_line("g1", thing=_A),),
        _tool(bar=None),
        _B,
        _NORMAL,
        None,
        _NO_GRANT,
    ),
    (
        "ADR-0376 §2:5: a grant for account A covers a call from A",
        (_line("g1", thing=_A),),
        _tool(bar=None),
        _A,
        _NORMAL,
        None,
        _resting("g1"),
    ),
    (
        "ADR-0376 §2:5: a call with no thing is covered only by a line with none",
        (_line("g1", thing=_A),),
        _tool(bar=None),
        None,
        _NORMAL,
        None,
        _NO_GRANT,
    ),
    # ADR-0376 §2:6, ADR-0368 §4:2: a grant's condition is met for one connection.
    (
        "ADR-0368 §4:2: a condition met",
        (_line("g1", condition=_LINE),),
        _tool(bar=None),
        None,
        _NORMAL,
        _LINE,
        _resting("g1"),
    ),
    (
        "ADR-0368 §4:2: a condition not met, by several connections or another",
        (_line("g1", condition=_LINE),),
        _tool(bar=None),
        None,
        _NORMAL,
        None,
        _NO_GRANT,
    ),
    # ADR-0376 §2:8: a removed line, or one for another capability, covers nothing.
    (
        "a removed limit covers nothing",
        (_limit("l1", removed=True),),
        _tool(),
        None,
        _NORMAL,
        None,
        _NO_LINE,
    ),
    (
        "a line naming another capability covers nothing",
        (_limit("l1", action="send_text"),),
        _tool(),
        None,
        _NORMAL,
        None,
        _NO_LINE,
    ),
    # ADR-0368 §7:2, ADR-0367 §5:2: a member of anyone alone, at none.
    (
        "ADR-0376 §2's worked line: search_memories at weak, for an unidentified sender",
        (),
        _tool("search_memories", bar=Sureness.WEAK),
        None,
        CheckedFor.anyone(),
        None,
        _short(Sureness.WEAK),
    ),
    (
        "ADR-0368 §7:2: the owner's grant does not cover a member of anyone",
        (_line("g1", action="search_memories", bar=Sureness.NONE),),
        _tool("search_memories", bar=None),
        None,
        CheckedFor.anyone(),
        None,
        _NO_GRANT,
    ),
    (
        "ADR-0368 §7:2: a grant to anyone at none applies to a member of anyone",
        (_line("g1", who=ANYONE_GROUP_ID, action="search_memories", bar=Sureness.NONE),),
        _tool("search_memories", bar=None),
        None,
        CheckedFor.anyone(),
        None,
        _resting("g1"),
    ),
    (
        "ADR-0368 §7:2: the owner's limit does not cover a member of anyone",
        (_limit("l1", action="search_memories"),),
        _tool("search_memories", bar=Sureness.NONE),
        None,
        CheckedFor.anyone(),
        None,
        _NO_LINE,
    ),
    (
        "a limit to anyone covers the owner",
        (_limit("l1", who=ANYONE_GROUP_ID),),
        _tool(),
        None,
        _NORMAL,
        None,
        _limited("l1"),
    ),
    # ADR-0368 §7:5: a work that carries no authority holds no grant.
    (
        "ADR-0368 §7:5: no one holds no grant",
        (),
        _tool(),
        None,
        CheckedFor.no_one(),
        None,
        _NO_GRANT,
    ),
    (
        "ADR-0368 §7:5: not even a grant to anyone at none",
        (_line("g1", who=ANYONE_GROUP_ID, bar=Sureness.NONE),),
        _tool(),
        None,
        CheckedFor.no_one(),
        None,
        _NO_GRANT,
    ),
    # DO-02: the owner's limit on one account holds however sure the system is.
    (
        "DO-02: a limit on account A, at strong",
        (_limit("l1", thing=_A),),
        _tool(),
        _A,
        _OWNER_AT[Sureness.STRONG],
        None,
        _limited("l1"),
    ),
]


@pytest.mark.parametrize(
    ("lines", "tool", "thing", "checked_for", "met", "expected"),
    [case[1:] for case in _CASES],
    ids=[case[0] for case in _CASES],
)
def test_the_check_decides_by_adr_0379s_order(  # noqa: PLR0913 — one parameter per column of the table
    lines: tuple[PermissionLine, ...],
    tool: ToolDefinition,
    thing: str | None,
    checked_for: CheckedFor,
    met: str | None,
    expected: CheckOutcome,
) -> None:
    """ADR-0379 §2:1 to §2:9, §3:1, §4: exactly one outcome, carrying what it carries."""
    assert check_call(lines, tool, thing=thing, checked_for=checked_for, met=met) == expected


def test_the_check_reads_its_arguments_alone() -> None:
    """The same lines, call and person always give the same outcome, and nothing changes them."""
    lines = (_line("g1", bar=Sureness.STRONG), _limit("l1", thing=_A))
    tool = _tool()
    first = check_call(lines, tool, thing=_B, checked_for=_WEAK, met=None)
    again = check_call(lines, tool, thing=_B, checked_for=_WEAK, met=None)
    assert first == again == _short(Sureness.NORMAL)
    assert lines == (_line("g1", bar=Sureness.STRONG), _limit("l1", thing=_A))


def test_checked_runs_for_each_in_order_and_records_each_outcome() -> None:
    """ADR-0379 §3:2, ADR-0368 §7:3: one outcome for each one the check runs for."""
    subject = CheckSubject(runs=(_OWNER_AT[Sureness.NONE], CheckedFor.anyone()), met=None)

    made = checked((), _tool(bar=Sureness.WEAK), thing=None, subject=subject)

    assert made.kind is CallCheckKind.CHECKED
    assert [one.checked_for for one in made.runs] == list(subject.runs)
    assert [one.outcome for one in made.runs] == [_short(Sureness.WEAK), _short(Sureness.WEAK)]


def test_a_subject_handed_nothing_runs_for_no_one() -> None:
    """A round handed no subject holds no grant: it fails closed."""
    assert CheckSubject().runs == (CheckedFor.no_one(),)
    with pytest.raises(ValueError, match="always for one"):
        CheckSubject(runs=())


# --- a call's thing (ADR-0376 §2:3, §2:4) ------------------------------------------------

_BINDING: Final = EgressBinding(
    spans=(
        EgressSpan(
            argument="to",
            provenance=DiscloserProvenance.SYSTEM_SELECTED,
            extent=len("a@example.com"),
            tier=DataTier.PERSONAL,
            destination=EgressDestination(
                protocol=DestinationProtocol.SMTP,
                supplied="a@example.com",
                canonical="a@example.com",
            ),
        ),
    ),
    account=BoundAccount(identity="work@example.com", reference="conn-a"),
    transport_endpoint="smtp://mail.example.com:587",
    planned_with_external_content=False,
    coverage=SpanCoverage.NOT_COVERED,
)


@pytest.mark.parametrize(
    ("place", "connection"),
    [
        ("conversation:c-1", OWN_CHAT_CONNECTION),
        ("conversation:c-2", OWN_CHAT_CONNECTION),
        (_LINE, _LINE),
        ("task_scheduler:schedule", None),
        ("approvals:approvals", None),
        (None, None),
    ],
)
def test_a_text_calls_thing_is_the_connection_its_place_is_in(
    place: str | None, connection: str | None
) -> None:
    """ADR-0376 §2:3, §2:4: the own chat is one connection; the schedule is named by none."""
    assert place_connection(place) == connection
    assert call_thing("send_text", place=place) == connection


def test_an_emails_thing_is_the_account_it_is_bound_to() -> None:
    """ADR-0376 §2:3: the account ``from`` names, as the hub bound the call to it."""
    assert call_thing("send_email", binding=_BINDING) == _A
    assert call_thing("send_email") is None


@pytest.mark.parametrize(
    "capability", ["search_web", "read_forecast", "book_stay", "spawn_task", "remember_fact"]
)
def test_every_other_capabilitys_call_has_no_thing(capability: str) -> None:
    """ADR-0376 §2:3's table: none, whatever its values or binding."""
    assert call_thing(capability, binding=_BINDING, place=_LINE) is None


# --- the owner at normal, for every tool the hub declares ---------------------------------


@pytest.mark.integration
async def test_the_owner_at_normal_is_allowed_every_declared_tool_on_no_line(
    tmp_path: Path,
) -> None:
    """#3678: nothing changes for what the owner asks at normal. With no made line, every
    tool the composed hub declares, its own records' calls and ``send_text`` included,
    is *allowed, on no line* for the owner at normal, with no thing and with one."""
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        phases = engine._phases
        assert phases is not None
        declared = [*await phases._tools.all_tools(), TEXT_CALL, EMAIL]
    finally:
        await engine.aclose()

    capabilities = {str(one.capability) for one in declared}
    assert {"send_text", "send_email", "remember_fact", "request_approval"} <= capabilities
    for tool in declared:
        for thing in (None, _A, _LINE):
            outcome = check_call((), tool, thing=thing, checked_for=_NORMAL, met=None)
            assert outcome == _NO_LINE, (tool.id, thing)
        made = checked(
            (), tool, thing=None, subject=CheckSubject(runs=(_NORMAL,), met=OWN_CHAT_CONNECTION)
        )
        assert [one.outcome for one in made.runs] == [_NO_LINE], tool.id
