"""The check, run first, decides (ADR-0367 §4:5, ADR-0379 §3).

Every call the authorizer checks gets one outcome, recorded whole on its verdict (ADR-0379
§3:2), and the outcome decides as ADR-0379 §3:3's table rules, on every path the check
reaches: an ordinary call, the assistant's own records' calls, the call a
``request_approval`` asks about and ``request_approval`` itself, a ticket's call (for its
tapper, ADR-0367 §5:5), and a ``text`` call into a connection that is not one of the work's
inputs' (§4:7); a text into the input's place stays outside the check. A read of the lines
that fails, and a check that raises, each leave the call not done. A call allowed resting
on a grant the owner made carries it, and its ruling names it (§4:6). For the owner at
normal with no made line, what is decided is what was decided before the check decided,
for every tool the composed hub declares (#3678).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from structlog.testing import capture_logs
from test_authorizer import _DIAGNOSED, _call, _diagnosed_clock, _episode, _Ids, _now, _round, _tool

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.diagnostics import diagnosed_activation
from ai_assistant.core.types import (
    ANYONE_GROUP_ID,
    OWNER_PERSON_ID,
    ActionRequest,
    ActivationEffect,
    ApprovalGiver,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalTap,
    CallCheck,
    CallCheckKind,
    CheckedFor,
    CheckOutcome,
    CheckOutcomeKind,
    CheckRun,
    DataTier,
    DefaultGrant,
    DiagnosticKind,
    DiagnosticSource,
    GrantHow,
    LineMaking,
    LineParts,
    LineRemoval,
    PermissionLine,
    PermissionLineKind,
    PermissionOutcome,
    PermissionRuling,
    PlanningRound,
    ProposedCall,
    RequestedCall,
    RiskLevel,
    Sureness,
    ThingKey,
    ThingKind,
    ThingRecord,
    ToolDefinition,
)
from ai_assistant.orchestration import authorizer
from ai_assistant.orchestration.approvals import REQUEST_APPROVAL
from ai_assistant.orchestration.authorizer import (
    AuthorizingStage,
    CallToAuthorize,
    RoundAuthorization,
    RoundMessage,
    RoundToAuthorize,
    Verdict,
    WorkingRecord,
)
from ai_assistant.orchestration.permission_check import CheckSubject
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeAuditTrail,
    FakeDiagnosticSink,
    FakeEgressBinder,
    FakeMemoryStore,
    FakePermissionLineStore,
    FakePlanStore,
    FakeStoryStore,
    FakeThingRecordStore,
    FakeToolRegistry,
)
from ai_assistant.tools.send_email import EMAIL, FROM_THE_PERSONS_ACCOUNT

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from pathlib import Path

    from ai_assistant.core.protocols import ActionPolicy, PermissionLineStore, ThingRecordStore

_AT: Final = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
_NORMAL: Final = CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NORMAL)
_OWNER: Final = CheckSubject(runs=(_NORMAL,))
_INPUT: Final = "place:chat"
_LINE: Final = "telegram:line"

#: A look-up, its default grant to anyone at weak, as every look-up is declared.
_LOOKUP: Final = _tool(
    "lookup", default_grant=DefaultGrant(how=GrantHow.ALLOWED, bar=Sureness.WEAK)
)
#: A booking, its default grant at normal, as what leaves the hub is declared.
_BOOK: Final = _tool("book", default_grant=DefaultGrant(how=GrantHow.ALLOWED, bar=Sureness.NORMAL))


def _outcome(kind: CheckOutcomeKind, **carried: Any) -> CheckOutcome:
    return CheckOutcome(kind=kind, **carried)


def _ran(*runs: tuple[CheckedFor, CheckOutcome]) -> CallCheck:
    return CallCheck(
        kind=CallCheckKind.CHECKED,
        runs=tuple(CheckRun(checked_for=who, outcome=outcome) for who, outcome in runs),
    )


_NO_LINE: Final = _outcome(CheckOutcomeKind.ALLOWED_ON_NO_LINE)


class _Hub:
    """The stage over fakes, with the line store ``lines`` or none.

    The trail resolves a grant's name in the same line store (ADR-0367 §4:6), and the
    stage reads whose a thing is from ``things``, every account below the owner's.
    """

    def __init__(
        self,
        *tools: ToolDefinition,
        lines: PermissionLineStore | None = None,
        binder: FakeEgressBinder | None = None,
        diagnostics: FakeDiagnosticSink | None = None,
        things: ThingRecordStore | None = None,
        policy: ActionPolicy | None = None,
    ) -> None:
        self.trail = FakeAuditTrail(now=_now, lines=lines)
        self.memory = FakeMemoryStore(now=_now)
        self.plans = FakePlanStore()
        self.stage = AuthorizingStage(
            registry=FakeToolRegistry(tools or (_LOOKUP, _BOOK)),
            policy=FakeActionPolicy() if policy is None else policy,
            trail=self.trail,
            stories=FakeStoryStore(now=_now),
            memory=self.memory,
            binder=binder,
            plans=self.plans,
            lines=lines,
            things=things,
            now=_now,
            new_decision_id=_Ids("decision"),
            new_effect_id=_Ids("effect"),
            diagnostics=diagnostics,
        )

    async def authorize(self, given: RoundToAuthorize) -> RoundAuthorization:
        episode = _episode()
        if await self.memory.get(episode.id) is None:
            await self.memory.add(episode)
        return await self.stage.authorize(given)


async def _limit(lines: FakePermissionLineStore, action: str, thing: str | None = None) -> str:
    """The owner's limit on ``action``, made in the store; its identifier."""
    made = await lines.record_making(
        LineParts(kind=PermissionLineKind.LIMIT, who=OWNER_PERSON_ID, action=action, thing=thing),
        by=OWNER_PERSON_ID,
    )
    return str(made.line.id)


async def _grant(
    lines: FakePermissionLineStore,
    action: str,
    *,
    how: GrantHow = GrantHow.ALLOWED,
    bar: Sureness = Sureness.NORMAL,
    thing: str | None = None,
) -> str:
    """The owner's grant on ``action``, made in the store; its identifier."""
    made = await lines.record_making(
        LineParts(
            kind=PermissionLineKind.GRANT,
            who=OWNER_PERSON_ID,
            action=action,
            how=how,
            bar=bar,
            thing=thing,
        ),
        by=OWNER_PERSON_ID,
    )
    return str(made.line.id)


def _unchecked(decided: RoundAuthorization) -> RoundAuthorization:
    """``decided`` with every check taken off: what the rules after the check decided."""
    return replace(
        decided,
        verdicts=tuple(replace(one, check=None) for one in decided.verdicts),
        call_messages=tuple(replace(one, check=None) for one in decided.call_messages),
    )


def _two_calls(subject: CheckSubject = _OWNER, person: str | None = None) -> RoundToAuthorize:
    return replace(
        _round(_call("c1", "lookup", q="trains to Lyon"), _call("c2", "book", q="a table")),
        check_for=subject,
        person=person,
    )


def _at(level: Sureness) -> CheckSubject:
    return CheckSubject(runs=(CheckedFor.for_person(OWNER_PERSON_ID, level),))


#: Every reason the check gives, which planning or the record may show: none names a line
#: or a bar (ADR-0367 §3:7).
_REASONS: Final = (
    authorizer._LIMITED,
    authorizer._NOT_GRANTED,
    authorizer._CHECK_UNREAD,
    authorizer._CHECK_FAILED,
    authorizer._NO_ONE_ASKED,
    authorizer._NOT_SURE_ENOUGH,
    authorizer._THEIR_YES,
    authorizer._NO_ONES_THING,
    authorizer._SOMEONE_ELSES,
    authorizer._NOT_ASKABLE,
    authorizer._MESSAGE_NOT_ASKED,
    authorizer._TAPPED_SHORT,
    authorizer._NOT_THEIR_YES,
)


def test_no_reason_names_a_line_or_a_bar() -> None:
    """ADR-0367 §3:7: a model is told a call's outcome and never the lines behind it."""
    for reason in _REASONS:
        words = reason.lower()
        assert "line" not in words, reason
        assert all(level.value not in words.split() for level in Sureness), reason


# --- the owner at normal, with no made line: nothing changes ------------------------------


async def test_the_owner_at_normal_is_decided_as_before_and_the_check_is_recorded() -> None:
    """#3678: every call allowed, on no line; what is decided is what was decided before."""
    checking = _Hub(lines=FakePermissionLineStore(now=_now))
    plain = _Hub()

    decided = await checking.authorize(_two_calls())
    before = await plain.authorize(_two_calls())

    assert [one.check for one in decided.verdicts] == [
        _ran((_NORMAL, _NO_LINE)),
        _ran((_NORMAL, _NO_LINE)),
    ]
    assert _unchecked(decided) == before
    assert [one.check for one in before.verdicts] == [None, None]
    assert all(one.call.request.rests_on is None for one in decided.allowed)
    assert await checking.trail.export() == await plain.trail.export()


def _minimal(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Arguments carrying every property ``schema`` requires, each its simplest value."""
    simplest = {"string": "x", "integer": 1, "number": 1, "boolean": True, "array": []}
    arguments: dict[str, Any] = {}
    properties = schema.get("properties", {})
    for name in schema.get("required", ()):
        declared = properties.get(name, {})
        if "enum" in declared:
            arguments[name] = declared["enum"][0]
        else:
            kind = declared.get("type", "string")
            arguments[name] = simplest.get(kind if isinstance(kind, str) else kind[0], {})
    return arguments


@pytest.mark.integration
async def test_every_declared_tool_is_decided_for_the_owner_at_normal_as_before(
    tmp_path: Path,
) -> None:
    """#3678, "Nothing changes for what the owner asks": table-driven over every tool the
    composed hub declares, its own records' calls included, a call by the owner at normal
    with no made line is decided exactly as with no check at all, which is how
    ``348ff39e7`` decided it: the same verdicts, the same calls handed on, the same rulings
    recorded."""
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        phases = engine._phases
        assert phases is not None
        declared = list(await phases._tools.all_tools())
    finally:
        await engine.aclose()
    assert len(declared) > 5

    for number, tool in enumerate(declared):
        arguments = {
            key: value
            for key, value in _minimal(tool.model_dump()["parameters_schema"]).items()
            if key not in tool.system_supplied
        }
        one = replace(
            _round(_call(f"c{number}", str(tool.capability), **arguments)),
            check_for=_OWNER,
            person=OWNER_PERSON_ID,
        )
        checking = _Hub(tool, lines=FakePermissionLineStore(now=_now))
        plain = _Hub(tool)

        decided = await checking.authorize(one)
        before = await plain.authorize(one)

        assert _unchecked(decided) == before, tool.id
        assert await checking.trail.export() == await plain.trail.export(), tool.id
        (verdict,) = decided.verdicts
        assert verdict.check in {None, _ran((_NORMAL, _NO_LINE))}, tool.id


# --- not done: a limit, no grant, a check that could not run ----------------------------


async def test_a_limit_leaves_its_call_not_done_asking_no_one_and_ruling_nothing() -> None:
    """ADR-0379 §2:2, ADR-0367 §4:2: not done, with its reason, the policy never asked; the
    call beside it runs as before. The reason names no line."""
    lines = FakePermissionLineStore(now=_now)
    limit = await _limit(lines, "book")
    hub = _Hub(lines=lines)

    decided = await hub.authorize(_two_calls())

    lookup, book = decided.verdicts
    assert lookup.verdict is Verdict.ALLOWED
    assert book.check == _ran((_NORMAL, _outcome(CheckOutcomeKind.NOT_DONE_LIMIT, line=limit)))
    assert (book.verdict, book.reason, book.decision_id) == (
        Verdict.NOT_DONE,
        authorizer._LIMITED,
        None,
    )
    assert [str(one.call.request.tool.capability) for one in decided.allowed] == ["lookup"]
    assert [one.tool.capability for one in await hub.trail.export()] == ["lookup"]
    assert limit not in str(book.reason)


async def test_a_call_no_grant_covers_is_not_done() -> None:
    """ADR-0367 §4:2: a declaration with no default grant, and no made grant, fails closed."""
    bare = _BOOK.model_copy(update={"default_grant": None})
    hub = _Hub(_LOOKUP, bare, lines=FakePermissionLineStore(now=_now))

    decided = await hub.authorize(_two_calls())

    _, book = decided.verdicts
    assert book.check == _ran((_NORMAL, _outcome(CheckOutcomeKind.NOT_DONE_NO_GRANT)))
    assert (book.verdict, book.reason) == (Verdict.NOT_DONE, authorizer._NOT_GRANTED)


class _Between:
    """A line store that runs the owner's act after the round's first read, before the next.

    Over a :class:`FakePermissionLineStore`, ``held``; each read is counted, so a test sees
    the check read the lines for each call's check.
    """

    def __init__(self, act: Callable[[FakePermissionLineStore], Awaitable[object]]) -> None:
        self.held = FakePermissionLineStore(now=_now)
        self._act = act
        self.reads = 0

    async def standing(self) -> tuple[PermissionLine, ...]:
        self.reads += 1
        if self.reads == 2:  # the first call is checked; the owner acts before the second
            await self._act(self.held)
        return await self.held.standing()

    async def line(self, line_id: str) -> PermissionLine | None:
        return await self.held.line(line_id)

    async def record_making(self, parts: LineParts, *, by: str) -> LineMaking:
        return await self.held.record_making(parts, by=by)

    async def record_removal(self, line_id: str, *, by: str) -> LineRemoval:
        return await self.held.record_removal(line_id, by=by)


async def test_a_limit_made_between_two_calls_of_a_round_decides_the_later_call() -> None:
    """ADR-0376 §4:9: a making bears on the calls checked after it, in the same round; the
    call checked before it is decided as it was."""
    made: list[str] = []

    async def act(store: FakePermissionLineStore) -> None:
        made.append(await _limit(store, "lookup"))
        made.append(await _limit(store, "book"))

    lines = _Between(act)
    decided = await _Hub(lines=lines).authorize(_two_calls())

    lookup, book = decided.verdicts
    assert (lookup.verdict, lookup.check) == (Verdict.ALLOWED, _ran((_NORMAL, _NO_LINE)))
    assert book.check == _ran((_NORMAL, _outcome(CheckOutcomeKind.NOT_DONE_LIMIT, line=made[1])))
    assert book.verdict is Verdict.NOT_DONE
    assert lines.reads == 2


async def test_a_limit_removed_between_two_calls_of_a_round_no_longer_decides_the_later_call() -> (
    None
):
    """ADR-0376 §4:9: a removal bears on the calls checked after it, in the same round."""
    limits: list[str] = []

    async def act(store: FakePermissionLineStore) -> None:
        for one in limits:
            await store.record_removal(one, by=OWNER_PERSON_ID)

    lines = _Between(act)
    limits.extend([await _limit(lines.held, "lookup"), await _limit(lines.held, "book")])

    decided = await _Hub(lines=lines).authorize(_two_calls())

    lookup, book = decided.verdicts
    assert lookup.verdict is Verdict.NOT_DONE
    assert (book.verdict, book.check) == (Verdict.ALLOWED, _ran((_NORMAL, _NO_LINE)))
    assert lines.reads == 2


async def test_a_read_that_fails_mid_round_leaves_the_rest_of_the_round_not_done() -> None:
    """A read that fails after one that did not: the call before it is decided by its
    outcome, it and every later call are not done, logged once, and no further read is
    made."""

    async def act(store: FakePermissionLineStore) -> None:
        store.fail_next()

    lines = _Between(act)
    three = replace(
        _round(
            _call("c1", "lookup", q="trains to Lyon"),
            _call("c2", "book", q="a table"),
            _call("c3", "lookup", q="trains to Nice"),
        ),
        check_for=_OWNER,
    )

    with capture_logs() as logs:
        decided = await _Hub(lines=lines).authorize(three)

    unread = CallCheck(kind=CallCheckKind.LINES_UNREAD)
    assert [one.check for one in decided.verdicts] == [_ran((_NORMAL, _NO_LINE)), unread, unread]
    assert [(one.verdict, one.reason) for one in decided.verdicts[1:]] == [
        (Verdict.NOT_DONE, authorizer._CHECK_UNREAD),
        (Verdict.NOT_DONE, authorizer._CHECK_UNREAD),
    ]
    assert lines.reads == 2
    assert [one["reason"] for one in logs if one["event"] == "permission_check_unrun"] == [
        "lines_unread"
    ]


async def test_lines_that_cannot_be_read_leave_every_call_not_done() -> None:
    """ADR-0379 §3:2 recorded, and failing closed: nothing is ruled on or handed on."""
    lines = FakePermissionLineStore(now=_now)
    lines.fail_next()
    hub = _Hub(lines=lines)

    decided = await hub.authorize(_two_calls())

    unread = CallCheck(kind=CallCheckKind.LINES_UNREAD)
    assert [one.check for one in decided.verdicts] == [unread, unread]
    assert {one.verdict for one in decided.verdicts} == {Verdict.NOT_DONE}
    assert decided.allowed == ()
    assert await hub.trail.export() == []


async def test_a_check_that_raises_leaves_its_call_not_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recorded as failed, logged in codes, and failing closed."""

    def raising(*args: object, **kwargs: object) -> CallCheck:
        del args, kwargs
        msg = "a defect in the check"
        raise RuntimeError(msg)

    monkeypatch.setattr(authorizer, "checked", raising)

    with capture_logs() as logs:
        decided = await _Hub(lines=FakePermissionLineStore(now=_now)).authorize(_two_calls())

    failed = CallCheck(kind=CallCheckKind.FAILED)
    assert [one.check for one in decided.verdicts] == [failed, failed]
    assert [(one.verdict, one.reason) for one in decided.verdicts] == [
        (Verdict.NOT_DONE, authorizer._CHECK_FAILED),
        (Verdict.NOT_DONE, authorizer._CHECK_FAILED),
    ]
    assert [one["reason"] for one in logs if one["event"] == "permission_check_failed"] == [
        "defect",
        "defect",
    ]


async def test_with_no_line_store_wired_nothing_is_checked() -> None:
    """No store, no check: every verdict carries none, a stage built to test other checks."""
    decided = await _Hub().authorize(_two_calls())
    assert [one.check for one in decided.verdicts] == [None, None]


async def test_a_call_refused_before_the_check_carries_none() -> None:
    """Selection runs first (ADR-0306 §4:10): a call no tool takes never reaches the check."""
    hub = _Hub(lines=FakePermissionLineStore(now=_now))
    decided = await hub.authorize(replace(_round(_call("c1", "fly", q="x")), check_for=_OWNER))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.check is None


async def test_the_diagnostic_record_notes_the_check_in_codes() -> None:
    """ADR-0314 §4: each check a call reached, the check's included, its outcome a code."""
    sink = FakeDiagnosticSink()
    hub = _Hub(lines=FakePermissionLineStore(now=_now), diagnostics=sink)

    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_clock):
        await hub.authorize(replace(_round(_call("c1", "lookup", q="x")), check_for=_OWNER))

    (entry,) = sink.of(DiagnosticSource.AUTHORIZING, DiagnosticKind.RETURNED)
    (call,) = entry.model_dump(mode="json")["body"]["calls"]
    assert [one["check"] for one in call["checks"]] == ["selection", "check", "policy", "stand_in"]
    assert call["checks"][1] == {"check": "check", "verdict": "allowed_on_no_line", "reason": None}


# --- whom it runs for, and a call needing a yes ------------------------------------------


async def test_an_unidentified_senders_call_needing_a_yes_is_not_done() -> None:
    """ADR-0368 §7:2, §7:4: a member of anyone, at none, falls short of the look-up's weak,
    and a work that is no person's asks no one."""
    anyone = CheckSubject(runs=(CheckedFor.anyone(),))
    hub = _Hub(lines=FakePermissionLineStore(now=_now))

    decided = await hub.authorize(replace(_round(_call("c1", "lookup", q="x")), check_for=anyone))

    (verdict,) = decided.verdicts
    shortfall = _outcome(CheckOutcomeKind.NEEDS_YES_SHORTFALL, bar=Sureness.WEAK)
    assert verdict.check == _ran((CheckedFor.anyone(), shortfall))
    assert (verdict.verdict, verdict.reason) == (Verdict.NOT_DONE, authorizer._NO_ONE_ASKED)


async def test_several_senders_are_each_checked_and_done_only_where_every_one_is() -> None:
    """ADR-0368 §7:3: the owner and an unidentified sender, each at none."""
    owner_at_none = CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NONE)
    several = CheckSubject(runs=(owner_at_none, CheckedFor.anyone()))
    hub = _Hub(lines=FakePermissionLineStore(now=_now))

    decided = await hub.authorize(replace(_round(_call("c1", "lookup", q="x")), check_for=several))

    (verdict,) = decided.verdicts
    shortfall = _outcome(CheckOutcomeKind.NEEDS_YES_SHORTFALL, bar=Sureness.WEAK)
    assert verdict.check == _ran((owner_at_none, shortfall), (CheckedFor.anyone(), shortfall))
    assert verdict.verdict is Verdict.NOT_DONE


async def test_a_round_handed_no_subject_holds_no_grant() -> None:
    """ADR-0368 §7:5: a round that names no one fails closed."""
    hub = _Hub(lines=FakePermissionLineStore(now=_now))
    decided = await hub.authorize(_round(_call("c1", "lookup", q="x")))

    (verdict,) = decided.verdicts
    assert verdict.check == _ran(
        (CheckedFor.no_one(), _outcome(CheckOutcomeKind.NOT_DONE_NO_GRANT))
    )
    assert (verdict.verdict, verdict.reason) == (Verdict.NOT_DONE, authorizer._NOT_GRANTED)


async def test_a_shortfall_in_the_persons_work_needs_them() -> None:
    """ADR-0367 §5:3, ADR-0361 §2:4: the owner's work at weak falls short of the booking's
    normal: it needs the person's yes, ruled as every call is, and runs nothing."""
    hub = _Hub(lines=FakePermissionLineStore(now=_now))

    decided = await hub.authorize(_two_calls(_at(Sureness.WEAK), person=OWNER_PERSON_ID))

    lookup, book = decided.verdicts
    assert lookup.verdict is Verdict.ALLOWED
    shortfall = _outcome(CheckOutcomeKind.NEEDS_YES_SHORTFALL, bar=Sureness.NORMAL)
    weak = CheckedFor.for_person(OWNER_PERSON_ID, Sureness.WEAK)
    assert book.check == _ran((weak, shortfall))
    assert (book.verdict, book.reason) == (Verdict.NEEDS_YOU, authorizer._NOT_SURE_ENOUGH)
    assert book.decision_id is not None
    assert [str(one.call.request.tool.capability) for one in decided.allowed] == ["lookup"]


async def test_a_policy_deny_still_refuses_a_call_the_check_has_need_a_yes() -> None:
    """ADR-0367 §4:5: a check never turns the policy's deny into anything else."""
    hub = _Hub(
        lines=FakePermissionLineStore(now=_now),
        policy=FakeActionPolicy(deny_at=RiskLevel.LOW),
    )

    decided = await hub.authorize(_two_calls(_at(Sureness.WEAK), person=OWNER_PERSON_ID))

    _, book = decided.verdicts
    assert (book.verdict, book.reason) == (Verdict.NOT_DONE, authorizer._DENIED)


async def test_a_grant_that_asks_needs_the_persons_yes_for_a_call_with_no_thing() -> None:
    """ADR-0379 §2:4, ADR-0381 §6:2: the owner's grant with approval applies at weak where
    the default falls short; a booking acts through no thing, so the person the work is for
    is asked."""
    lines = FakePermissionLineStore(now=_now)
    await _grant(lines, "book", how=GrantHow.WITH_APPROVAL, bar=Sureness.WEAK)
    hub = _Hub(lines=lines)

    decided = await hub.authorize(_two_calls(_at(Sureness.WEAK), person=OWNER_PERSON_ID))

    _, book = decided.verdicts
    weak = CheckedFor.for_person(OWNER_PERSON_ID, Sureness.WEAK)
    assert book.check == _ran((weak, _outcome(CheckOutcomeKind.NEEDS_YES_WITH_APPROVAL)))
    assert (book.verdict, book.reason) == (Verdict.NEEDS_YOU, authorizer._THEIR_YES)


def _bound_email_hub(lines: FakePermissionLineStore, things: ThingRecordStore | None) -> _Hub:
    binder = FakeEgressBinder()
    binder.register_egress(EMAIL, reference="conn-a", identity="me@example.com")
    return _Hub(EMAIL, lines=lines, binder=binder, things=things)


class _SomeoneElses:
    """A record store naming someone other than the owner, which nothing writes yet."""

    async def whose(self, key: ThingKey) -> ThingRecord | None:
        return ThingRecord.model_construct(key=key, person="person:someone", recorded_at=_AT)


@pytest.mark.parametrize(
    ("things", "verdict", "reason"),
    [
        (
            FakeThingRecordStore(
                held=(ThingKey(kind=ThingKind.CONNECTION, identifier="account:conn-a"),)
            ),
            Verdict.NEEDS_YOU,
            authorizer._THEIR_YES,
        ),
        (FakeThingRecordStore(), Verdict.NOT_DONE, authorizer._NO_ONES_THING),
        (None, Verdict.NOT_DONE, authorizer._NO_ONES_THING),
        (_SomeoneElses(), Verdict.NOT_DONE, authorizer._SOMEONE_ELSES),
    ],
    ids=["the owner's account", "no record", "no store", "someone else's"],
)
async def test_a_grant_that_asks_needs_the_yes_of_whoever_its_thing_belongs_to(
    things: Any, verdict: Verdict, reason: str
) -> None:
    """ADR-0367 §5:6, ADR-0381 §5:2, §6:1: the record names whose yes; no record, no card."""
    lines = FakePermissionLineStore(now=_now)
    await _grant(
        lines, "send_email", how=GrantHow.WITH_APPROVAL, bar=Sureness.WEAK, thing="account:conn-a"
    )
    hub = _bound_email_hub(lines, things)

    decided = await hub.authorize(
        replace(_email_round(), check_for=_at(Sureness.WEAK), person=OWNER_PERSON_ID)
    )

    (one,) = decided.verdicts
    assert (one.verdict, one.reason) == (verdict, reason)


# --- a grant the owner made: the line the call rests on -----------------------------------


async def test_an_allowed_call_rests_on_the_grant_the_owner_made_and_its_ruling_names_it() -> None:
    """ADR-0367 §4:6, ADR-0379 §4: the request carries the grant, the policy names it, the
    trail records it and its name resolves to the line's record."""
    lines = FakePermissionLineStore(now=_now)
    grant = await _grant(lines, "book", bar=Sureness.WEAK)
    hub = _Hub(lines=lines)

    decided = await hub.authorize(_two_calls(_at(Sureness.WEAK), person=OWNER_PERSON_ID))

    _, book = decided.verdicts
    weak = CheckedFor.for_person(OWNER_PERSON_ID, Sureness.WEAK)
    resting = _outcome(CheckOutcomeKind.ALLOWED_ON_MADE_GRANT, line=grant)
    assert book.check == _ran((weak, resting))
    assert book.verdict is Verdict.ALLOWED
    held = {str(one.call.request.tool.capability): one.call for one in decided.allowed}
    assert held["book"].request.rests_on == grant
    assert held["lookup"].request.rests_on is None
    assert held["book"].decision.ruling.authorised_by == grant
    assert held["lookup"].decision.ruling.authorised_by is None
    recorded = await hub.trail.get(str(book.decision_id))
    assert recorded is not None
    line = await lines.line(str(recorded.ruling.authorised_by))
    assert line is not None
    assert (line.id, line.action) == (grant, "book")


async def test_a_disclosing_call_on_a_made_grant_stops_asking_and_on_a_default_still_asks() -> None:
    """ADR-0379 §4's worked calls: only a default allows, and the floor still asks; the
    owner's grant allows, and the floor is met, its ruling naming the grant."""
    sharing = _tool(
        "book",
        id="share",
        capability="share",
        discloses=(DataTier.PERSONAL,),
        default_grant=DefaultGrant(how=GrantHow.ALLOWED, bar=Sureness.NORMAL),
    )
    one = replace(_round(_call("c1", "share", q="x")), check_for=_OWNER, person=OWNER_PERSON_ID)
    lines = FakePermissionLineStore(now=_now)

    on_default = await _Hub(sharing, lines=lines).authorize(one)
    grant = await _grant(lines, "share")
    on_grant = await _Hub(sharing, lines=lines).authorize(one)

    assert on_default.verdicts[0].verdict is Verdict.NEEDS_YOU
    assert on_grant.verdicts[0].verdict is Verdict.ALLOWED
    (ran,) = on_grant.allowed
    assert ran.call.decision.ruling.authorised_by == grant


async def test_an_email_on_a_made_grant_still_needs_approval() -> None:
    """ADR-0364 §7:5, §9:12, ADR-0379 §3: whether the policy's other rules still ask is the
    policy's, and the register's; a grant the owner made changes neither for an email."""
    lines = FakePermissionLineStore(now=_now)
    grant = await _grant(lines, "send_email", thing="account:conn-a")
    hub = _bound_email_hub(lines, None)

    decided = await hub.authorize(replace(_email_round(), person=OWNER_PERSON_ID))

    (verdict,) = decided.verdicts
    resting = _outcome(CheckOutcomeKind.ALLOWED_ON_MADE_GRANT, line=grant)
    assert verdict.check == _ran((_NORMAL, resting))
    assert verdict.verdict is Verdict.NEEDS_YOU
    assert decided.allowed == ()


# --- a text call (ADR-0367 §4:7) ----------------------------------------------------------


def _texts(
    *places: str, subject: CheckSubject = _OWNER, person: str | None = None
) -> RoundToAuthorize:
    calls = tuple(
        ProposedCall(call_id=f"t{number}", name="send_text", arguments={"words": "hello"})
        for number, _ in enumerate(places, 1)
    )
    return RoundToAuthorize(
        activation_id="act-1",
        round=PlanningRound(id="round:1", recorded_at=_AT, calls=calls),
        working=WorkingRecord(),
        input_place=_INPUT,
        call_messages=tuple(
            RoundMessage("hello", place, f"t{number}") for number, place in enumerate(places, 1)
        ),
        shown_places=(_LINE,),
        check_for=subject,
        person=person,
    )


async def test_a_text_into_the_inputs_place_stays_outside_and_another_is_decided() -> None:
    """§4:7: into the input's place, outside the check, a limit there notwithstanding; into
    another connection, checked, its thing that connection, and a limit on it refuses it."""
    lines = FakePermissionLineStore(now=_now)
    limit = await _limit(lines, "send_text", thing=_LINE)
    await _limit(lines, "send_text", thing=_INPUT)
    hub = _Hub(lines=lines)

    decided = await hub.authorize(_texts(_INPUT, _LINE))

    into_input, into_line = decided.call_messages
    assert into_input.check == CallCheck(kind=CallCheckKind.OUTSIDE)
    assert into_line.check == _ran((_NORMAL, _outcome(CheckOutcomeKind.NOT_DONE_LIMIT, line=limit)))
    assert (into_input.allowed, into_line.allowed) == (True, False)
    assert (into_line.reason, into_line.effect_id) == (authorizer._LIMITED, None)


@pytest.mark.parametrize(
    ("person", "reason"),
    [
        (OWNER_PERSON_ID, authorizer._MESSAGE_NOT_ASKED),
        (None, authorizer._NO_ONE_ASKED),
    ],
    ids=["a person's work", "no person's work"],
)
async def test_a_text_needing_a_yes_is_not_sent(person: str | None, reason: str) -> None:
    """A message is never asked about: one the check has need a yes is not sent."""
    hub = _Hub(lines=FakePermissionLineStore(now=_now))

    decided = await hub.authorize(
        _texts(_LINE, subject=CheckSubject(runs=(CheckedFor.anyone(),)), person=person)
    )

    (into_line,) = decided.call_messages
    assert (into_line.allowed, into_line.reason) == (False, reason)


async def test_the_rounds_own_message_is_no_call_and_carries_no_check() -> None:
    hub = _Hub(lines=FakePermissionLineStore(now=_now))
    decided = await hub.authorize(
        replace(_round(message=RoundMessage("hi", _INPUT)), check_for=_OWNER)
    )
    assert decided.message is not None
    assert decided.message.check is None


async def test_a_text_into_an_absorbed_inputs_place_stays_outside() -> None:
    """§4:7: a place any of the work's own inputs came from, an absorbed one's included,
    though it is neither the trigger's place nor a taken input's."""
    lines = FakePermissionLineStore(now=_now)
    await _limit(lines, "send_text", thing=_LINE)
    hub = _Hub(lines=lines)

    decided = await hub.authorize(replace(_texts(_LINE), input_places=(_INPUT, _LINE)))

    (into_line,) = decided.call_messages
    assert into_line.check == CallCheck(kind=CallCheckKind.OUTSIDE)
    assert into_line.allowed


# --- an email, request_approval and a ticket -------------------------------------------------


def _email_round() -> RoundToAuthorize:
    arguments = {
        "from": FROM_THE_PERSONS_ACCOUNT,
        "to": ["anna@example.com"],
        "subject": "Lunch",
        "words": "One o'clock?",
    }
    return replace(_round(_call("c1", "send_email", **arguments)), check_for=_OWNER)


async def test_an_email_is_checked_for_the_account_it_is_bound_to() -> None:
    """ADR-0376 §2:3: its thing is the account its ``from`` names, bound to the call; a
    limit on that account refuses it, and one on another account does not reach it."""
    binder = FakeEgressBinder()
    binder.register_egress(EMAIL, reference="conn-a", identity="me@example.com")
    lines = FakePermissionLineStore(now=_now)
    limit = await _limit(lines, "send_email", thing="account:conn-a")
    other = await _limit(lines, "send_email", thing="account:conn-b")
    hub = _Hub(EMAIL, lines=lines, binder=binder)

    decided = await hub.authorize(_email_round())

    (verdict,) = decided.verdicts
    assert verdict.check == _ran((_NORMAL, _outcome(CheckOutcomeKind.NOT_DONE_LIMIT, line=limit)))
    assert (verdict.verdict, verdict.reason) == (Verdict.NOT_DONE, authorizer._LIMITED)
    assert other != limit


_BOOKING: Final = _BOOK.model_copy(update={"id": "book", "capability": "book"})


class _Policy:
    """Allows every call, so a ticket's call runs under its approval."""

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        return PermissionRuling(
            outcome=PermissionOutcome.ALLOW,
            reason="test: allowed",
            authorised_by=request.rests_on,
        )

    async def resolve(self, confirmed: object, *, approved: bool) -> PermissionRuling:
        del confirmed, approved
        raise AssertionError


def _ticket_hub(
    lines: FakePermissionLineStore, *, things: ThingRecordStore | None = None
) -> tuple[AuthorizingStage, FakePlanStore]:
    plans = FakePlanStore()
    stage = AuthorizingStage(
        registry=FakeToolRegistry((_BOOKING, REQUEST_APPROVAL)),
        policy=_Policy(),
        trail=FakeAuditTrail(now=_now, lines=lines),
        stories=FakeStoryStore(now=_now),
        memory=FakeMemoryStore(now=_now),
        plans=plans,
        lines=lines,
        things=things,
        now=_now,
        new_decision_id=_Ids("decision"),
        new_effect_id=_Ids("effect"),
    )
    return stage, plans


def _asking(subject: CheckSubject = _OWNER) -> RoundToAuthorize:
    asking = CallToAuthorize(
        ProposedCall(
            call_id="ask-1",
            name="request_approval",
            arguments={"call": {"tool": "book", "arguments": {"q": "a table"}}, "why": "Asked."},
        )
    )
    return RoundToAuthorize(
        activation_id="act-1",
        round=PlanningRound(id="round:1", recorded_at=_AT, calls=(asking.call,)),
        working=WorkingRecord(),
        calls=(asking,),
        input_place=_INPUT,
        person=OWNER_PERSON_ID,
        check_for=subject,
    )


async def test_request_approval_is_checked_as_a_call_of_its_own() -> None:
    """ADR-0379 §3:2: ``request_approval`` gets its own outcome, which its verdict records."""
    stage, _ = _ticket_hub(FakePermissionLineStore(now=_now))

    decided = await stage.authorize(_asking())

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    assert verdict.check == _ran((_NORMAL, _NO_LINE))
    (asked,) = decided.allowed
    assert asked.requested is not None


async def test_request_approval_a_limit_covers_asks_nothing() -> None:
    """ADR-0379 §3:3: a limit on ``request_approval`` itself leaves it not done."""
    lines = FakePermissionLineStore(now=_now)
    await _limit(lines, "request_approval")
    stage, _ = _ticket_hub(lines)

    decided = await stage.authorize(_asking())

    (verdict,) = decided.verdicts
    assert (verdict.verdict, verdict.reason) == (Verdict.NOT_DONE, authorizer._LIMITED)
    assert decided.allowed == ()


async def test_the_call_a_limit_refuses_is_not_asked_about() -> None:
    """ADR-0361 §2:3, ADR-0367 §4:2: the call it asks about is checked as a call made; one
    a limit covers gets no request, and planning is told not to ask."""
    lines = FakePermissionLineStore(now=_now)
    await _limit(lines, "book")
    stage, _ = _ticket_hub(lines)

    decided = await stage.authorize(_asking())

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.reason is not None
    assert authorizer._LIMITED in verdict.reason
    assert "do not ask" in verdict.reason
    assert decided.allowed == ()
    assert verdict.check == _ran((_NORMAL, _NO_LINE))


async def test_a_call_falling_short_is_asked_about() -> None:
    """ADR-0367 §5:3: a shortfall is what a request is for: the request is written."""
    stage, _ = _ticket_hub(FakePermissionLineStore(now=_now))

    decided = await stage.authorize(_asking(_at(Sureness.WEAK)))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    (asked,) = decided.allowed
    assert asked.requested is not None


async def _answered(plans: FakePlanStore, tap: ApprovalTap) -> ApprovalRequest:
    request = ApprovalRequest(
        id="approval:1",
        person=OWNER_PERSON_ID,
        activation_id="act-asker",
        round="round:ask",
        call=RequestedCall(tool=_BOOKING, values={"q": "a table"}),
        why="You asked me to book the table.",
        written_at=_AT,
        expires_at=_AT + timedelta(hours=24),
    )
    effect = ActivationEffect(
        id="effect:ask",
        activation_id="act-asker",
        round="round:ask",
        capability="request_approval",
        values_digest="0" * 64,
        decision_id="decision:ask",
        claimed_at=_AT,
        request=request.id,
    )
    await plans.write_approval_request(request, effect, match=None)
    step = await plans.answer_approval_request(request.id, ApprovalRequestState.APPROVED, tap)
    return step.request


async def _run_ticket(
    stage: AuthorizingStage, plans: FakePlanStore, tap: ApprovalTap
) -> RoundAuthorization:
    request = await _answered(plans, tap)
    running = CallToAuthorize(
        ProposedCall(call_id="run-1", name="book", arguments={"q": "a table"}),
        ticket=str(request.id),
    )
    return await stage.authorize(
        RoundToAuthorize(
            activation_id="act-holder",
            round=PlanningRound(
                id="round:1",
                recorded_at=_AT,
                calls=(ProposedCall(call_id="run-1", name="run_approved", arguments={}),),
            ),
            working=WorkingRecord(),
            calls=(running,),
            input_place="approvals:approvals",
            person=OWNER_PERSON_ID,
            tickets=frozenset({str(request.id)}),
            check_for=CheckSubject(),
        )
    )


def _tap(level: Sureness | None, person: str | None = OWNER_PERSON_ID) -> ApprovalTap:
    return ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=_AT, person=person, level=level)


@pytest.mark.parametrize(
    ("tap_level", "expected", "verdict", "reason"),
    [
        (Sureness.NORMAL, _NO_LINE, Verdict.ALLOWED, None),
        (
            Sureness.WEAK,
            _outcome(CheckOutcomeKind.NEEDS_YES_SHORTFALL, bar=Sureness.NORMAL),
            Verdict.NOT_DONE,
            authorizer._TAPPED_SHORT,
        ),
        (
            None,
            _outcome(CheckOutcomeKind.NEEDS_YES_SHORTFALL, bar=Sureness.NORMAL),
            Verdict.NOT_DONE,
            authorizer._TAPPED_SHORT,
        ),
    ],
    ids=["tapped-at-normal", "tapped-at-weak", "level-not-recorded"],
)
async def test_a_tickets_call_runs_only_where_the_check_allows_it_for_its_tapper(
    tap_level: Sureness | None, expected: CheckOutcome, verdict: Verdict, reason: str | None
) -> None:
    """ADR-0367 §5:4, §5:5, ADR-0377 §4:2, §4:4: whatever the work carries, the tapper at
    the level the tap came by; a tap below the bar answers nothing, so nothing runs."""
    stage, plans = _ticket_hub(FakePermissionLineStore(now=_now))

    decided = await _run_ticket(stage, plans, _tap(tap_level))

    (one,) = decided.verdicts
    tapper = CheckedFor.for_person(OWNER_PERSON_ID, tap_level or Sureness.NONE)
    assert one.check == _ran((tapper, expected))
    assert (one.verdict, one.reason) == (verdict, reason)


async def test_a_tickets_call_a_limit_covers_is_not_done() -> None:
    """ADR-0367 §5:5: a yes gives no more than the tapper holds."""
    lines = FakePermissionLineStore(now=_now)
    await _limit(lines, "book")
    stage, plans = _ticket_hub(lines)

    decided = await _run_ticket(stage, plans, _tap(Sureness.NORMAL))

    (one,) = decided.verdicts
    assert (one.verdict, one.reason) == (Verdict.NOT_DONE, authorizer._LIMITED)
    assert decided.allowed == ()


@pytest.mark.parametrize(
    ("tapper", "verdict"),
    [(OWNER_PERSON_ID, Verdict.ALLOWED), (None, Verdict.NOT_DONE)],
    ids=["the request's person", "no one's tap"],
)
async def test_a_tickets_call_a_grant_asks_for_is_met_by_the_right_persons_tap(
    tapper: str | None, verdict: Verdict
) -> None:
    """ADR-0367 §5:6, ADR-0381 §6:2: a call with no thing needs the request's person's yes;
    their tap is it, and a tap no one's is not."""
    lines = FakePermissionLineStore(now=_now)
    await _grant(lines, "book", how=GrantHow.WITH_APPROVAL, bar=Sureness.NONE)
    await _grant(lines, "book", how=GrantHow.WITH_APPROVAL, bar=Sureness.WEAK)
    anyone_asks = await lines.record_making(
        LineParts(
            kind=PermissionLineKind.GRANT,
            who=ANYONE_GROUP_ID,
            action="book",
            how=GrantHow.WITH_APPROVAL,
            bar=Sureness.NONE,
        ),
        by=OWNER_PERSON_ID,
    )
    assert anyone_asks.line.id
    stage, plans = _ticket_hub(lines)

    level = Sureness.WEAK if tapper is not None else Sureness.NONE
    decided = await _run_ticket(stage, plans, _tap(level, tapper))

    (one,) = decided.verdicts
    assert one.check is not None
    assert {run.outcome.kind for run in one.check.runs} == {
        CheckOutcomeKind.NEEDS_YES_WITH_APPROVAL
    }
    assert one.verdict is verdict


async def test_a_tickets_call_resting_on_a_made_grant_names_it() -> None:
    """ADR-0367 §4:6: under a ticket too, the grant the tapper's call rests on is named."""
    lines = FakePermissionLineStore(now=_now)
    grant = await _grant(lines, "book", bar=Sureness.WEAK)
    stage, plans = _ticket_hub(lines)

    decided = await _run_ticket(stage, plans, _tap(Sureness.WEAK))

    (ran,) = decided.allowed
    assert ran.call.request.rests_on == grant
    assert ran.call.decision.ruling.authorised_by == grant


class _Raising:
    """A policy that raises once asked: a fault after the check has run."""

    async def decide(self, request: object) -> PermissionRuling:
        del request
        msg = "the policy failed"
        raise RuntimeError(msg)

    async def resolve(self, confirmed: object, *, approved: bool) -> PermissionRuling:
        del confirmed, approved
        raise AssertionError


async def test_a_check_made_before_authorizing_fails_is_kept_in_the_sink() -> None:
    """ADR-0379 §3:2: what the check made of a call it reached is written as it is made,
    so a round whose authorizing then raises still keeps it."""
    hub = _Hub(lines=FakePermissionLineStore(now=_now))
    hub.stage._policy = _Raising()
    sink: dict[str, CallCheck] = {}

    with pytest.raises(RuntimeError, match="the policy failed"):
        await hub.authorize(
            replace(_round(_call("c1", "lookup", q="x")), check_for=_OWNER, check_sink=sink)
        )

    assert sink == {"c1": _ran((_NORMAL, _NO_LINE))}
