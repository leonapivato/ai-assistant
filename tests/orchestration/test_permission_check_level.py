"""The level a request's call needs, for a tap to answer it (ADR-0377 §3:2).

A function of the standing lines and the request's call, over the check B4 built
(:func:`~ai_assistant.orchestration.permission_check.check_call`): the least level at which
the check finds a grant covering the call for the request's person and applying there, one
that allows with approval counted; weak where that is none or no grant covers it. A
shortfall's card needs its grant's bar (ADR-0367 §5:4), the same least level (ADR-0379
§2:5). Then, for every tool the composed hub declares with no made line, the level is the
tool's default bar, never above normal, so the owner at normal answers every card as today
(#3678).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    ANYONE_GROUP_ID,
    OWNER_PERSON_ID,
    BoundAccount,
    CheckedFor,
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
    RequestedCall,
    SpanCoverage,
    Sureness,
    ToolDefinition,
)
from ai_assistant.orchestration.message_tools import TEXT_CALL
from ai_assistant.orchestration.permission_check import check_call, level_needed
from ai_assistant.tools.send_email import EMAIL

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_AT: Final = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
_A: Final = "account:conn-a"
_B: Final = "account:conn-b"
_LINE: Final = "telegram:line"


def _tool(
    capability: str = "book",
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


def _call(tool: ToolDefinition, *, binding: EgressBinding | None = None) -> RequestedCall:
    return RequestedCall.model_construct(tool=tool, values={}, binding=binding)


def _line(  # noqa: PLR0913 — one keyword per part of a line a case varies
    line_id: str,
    kind: PermissionLineKind = PermissionLineKind.GRANT,
    *,
    who: str = OWNER_PERSON_ID,
    action: str = "book",
    thing: str | None = None,
    how: GrantHow | None = GrantHow.ALLOWED,
    bar: Sureness | None = Sureness.NORMAL,
    condition: str | None = None,
    removed: bool = False,
) -> PermissionLine:
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
        made_at=_AT,
        removed_by=OWNER_PERSON_ID if removed else None,
        removed_at=_AT + timedelta(minutes=1) if removed else None,
    )


def _needed(lines: Sequence[PermissionLine], tool: ToolDefinition) -> Sureness:
    return level_needed(lines, _call(tool), person=OWNER_PERSON_ID)


_BOOK_WEAK: Final = _tool(bar=Sureness.WEAK)
_BOOK_NORMAL: Final = _tool(bar=Sureness.NORMAL)
_BOOK_NONE: Final = _tool(bar=Sureness.NONE)
_BOOK_UNDECLARED: Final = _tool(bar=None)
_BOOK_ASKS: Final = _tool(how=GrantHow.WITH_APPROVAL, bar=Sureness.NORMAL)


@pytest.mark.parametrize(
    ("tool", "lines", "needed"),
    [
        # A default line alone: its bar, and weak where that is none (§3:2).
        (_BOOK_WEAK, (), Sureness.WEAK),
        (_BOOK_NORMAL, (), Sureness.NORMAL),
        (_BOOK_NONE, (), Sureness.WEAK),
        # No grant covers it: weak.
        (_BOOK_UNDECLARED, (), Sureness.WEAK),
        # A grant that asks counts alike (§3:2's "counting one that allows with approval").
        (_BOOK_ASKS, (), Sureness.NORMAL),
        (
            _BOOK_UNDECLARED,
            (_line("g", how=GrantHow.WITH_APPROVAL, bar=Sureness.STRONG),),
            Sureness.STRONG,
        ),
        # The least of several covering grants: the shortfall's bar (ADR-0379 §2:5).
        (_BOOK_NORMAL, (_line("g", bar=Sureness.STRONG),), Sureness.NORMAL),
        (_BOOK_UNDECLARED, (_line("g", bar=Sureness.STRONG),), Sureness.STRONG),
        (_BOOK_NORMAL, (_line("g", bar=Sureness.WEAK),), Sureness.WEAK),
        # A named grant at none applies only at weak (ADR-0367 §5:2).
        (_BOOK_UNDECLARED, (_line("g", bar=Sureness.NONE),), Sureness.WEAK),
        # A grant to anyone at its bar, as a default is.
        (
            _BOOK_UNDECLARED,
            (_line("g", who=ANYONE_GROUP_ID, bar=Sureness.STRONG),),
            Sureness.STRONG,
        ),
        # A removed line is no line; a line for another action covers nothing.
        (_BOOK_UNDECLARED, (_line("g", bar=Sureness.STRONG, removed=True),), Sureness.WEAK),
        (_BOOK_UNDECLARED, (_line("g", action="other", bar=Sureness.STRONG),), Sureness.WEAK),
        # A limit decides "not done" at every level, never a level: the grants' bar stands,
        # and the ticket's check refuses its call (ADR-0379 §2:2, ADR-0367 §5:5).
        (_BOOK_NORMAL, (_line("l", PermissionLineKind.LIMIT),), Sureness.NORMAL),
        (_BOOK_UNDECLARED, (_line("l", PermissionLineKind.LIMIT),), Sureness.WEAK),
        # A grant whose condition names a connection is met by none at a tap, as the
        # ticket's check reads it.
        (_BOOK_NORMAL, (_line("g", bar=Sureness.WEAK, condition=_LINE),), Sureness.NORMAL),
    ],
)
def test_the_level_is_the_least_at_which_a_grant_covering_the_call_applies(
    tool: ToolDefinition, lines: tuple[PermissionLine, ...], needed: Sureness
) -> None:
    """ADR-0377 §3:2, ADR-0367 §5:1, §5:2, ADR-0379 §2."""
    assert _needed(lines, tool) is needed


def test_it_is_never_below_weak_whatever_the_lines_say() -> None:
    """§3:2: weak where the least level is none."""
    for lines in ((), (_line("g", who=ANYONE_GROUP_ID, bar=Sureness.NONE),)):
        assert _needed(lines, _BOOK_UNDECLARED) is Sureness.WEAK


def test_at_the_level_it_gives_the_tickets_check_lets_the_call_through() -> None:
    """§3 (its note): each card asks of a tap the level at which the check would let its
    call through, read as ADR-0367 §5:5 reads a ticket's call: and below it, it would not."""
    cases = [
        ((), _BOOK_NORMAL),
        ((_line("g", bar=Sureness.STRONG),), _BOOK_UNDECLARED),
        ((_line("g", bar=Sureness.WEAK),), _BOOK_NORMAL),
        ((), _BOOK_ASKS),
    ]
    applies = {
        CheckOutcomeKind.ALLOWED_ON_NO_LINE,
        CheckOutcomeKind.ALLOWED_ON_MADE_GRANT,
        CheckOutcomeKind.NEEDS_YES_WITH_APPROVAL,
    }
    for lines, tool in cases:
        needed = _needed(lines, tool)
        at = CheckedFor.for_person(OWNER_PERSON_ID, needed)
        below = CheckedFor.for_person(OWNER_PERSON_ID, Sureness.WEAK)
        assert check_call(lines, tool, thing=None, checked_for=at, met=None).kind in applies
        if needed > Sureness.WEAK:
            outcome = check_call(lines, tool, thing=None, checked_for=below, met=None)
            assert outcome.kind is CheckOutcomeKind.NEEDS_YES_SHORTFALL
            assert outcome.bar is needed


def _binding(reference: str) -> EgressBinding:
    return EgressBinding(
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
        account=BoundAccount(identity="work@example.com", reference=reference),
        transport_endpoint="smtp://mail.example.com:587",
        planned_with_external_content=False,
        coverage=SpanCoverage.NOT_COVERED,
    )


def test_an_emails_thing_is_read_from_its_binding() -> None:
    """ADR-0376 §2:3, §2:5: a grant whose thing is the account the call is bound to covers
    it; one naming another account does not."""
    weak_on_a = (_line("g", action="send_email", thing=_A, bar=Sureness.WEAK),)
    weak_on_b = (_line("g", action="send_email", thing=_B, bar=Sureness.WEAK),)
    on_a = _call(EMAIL, binding=_binding("conn-a"))

    assert level_needed(weak_on_a, on_a, person=OWNER_PERSON_ID) is Sureness.WEAK
    assert level_needed(weak_on_b, on_a, person=OWNER_PERSON_ID) is Sureness.NORMAL


def test_it_reads_only_its_arguments() -> None:
    """No model, no store and no clock: the same arguments, the same level."""
    lines = (_line("g", bar=Sureness.STRONG),)
    assert {_needed(lines, _BOOK_UNDECLARED) for _ in range(3)} == {Sureness.STRONG}


@pytest.mark.integration
async def test_with_no_made_line_every_declared_tool_needs_its_default_bar(
    tmp_path: Path,
) -> None:
    """#3678: nothing changes for the owner at normal. With no made line, each tool the
    composed hub declares, ``send_text`` and ``send_email`` included, needs its default's bar,
    weak or normal: never above normal, so the owner's tap at normal answers every card."""
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        phases = engine._phases
        assert phases is not None
        declared = [*await phases._tools.all_tools(), TEXT_CALL, EMAIL]
    finally:
        await engine.aclose()

    for tool in declared:
        assert tool.default_grant is not None, tool.id
        needed = level_needed((), _call(tool), person=OWNER_PERSON_ID)
        assert needed is max(tool.default_grant.bar, Sureness.WEAK), tool.id
        assert needed <= Sureness.NORMAL, tool.id
