"""The check, run first and recorded beside today's rules, which still decide (ADR-0367 §4:5).

Every call the authorizer checks gets one outcome, recorded whole on its verdict (ADR-0379
§3:2): an ordinary call, the assistant's own records' calls, ``request_approval``, a
ticket's call (for its tapper, ADR-0367 §5:5), and a ``text`` call into a connection that
is not one of the work's inputs' (§4:7); a text into the input's place stays outside the
check. A read of the lines that fails is recorded as the check not having run, and a check
that raises as failed. In every case what is decided is what was decided before: the same
verdicts, the same calls handed on, the same rulings in the trail.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from structlog.testing import capture_logs
from test_authorizer import _DIAGNOSED, _call, _diagnosed_clock, _episode, _Ids, _now, _round, _tool

from ai_assistant.core.diagnostics import diagnosed_activation
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
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
    DefaultGrant,
    DiagnosticKind,
    DiagnosticSource,
    GrantHow,
    LineParts,
    PermissionLineKind,
    PermissionOutcome,
    PermissionRuling,
    PlanningRound,
    ProposedCall,
    RequestedCall,
    Sureness,
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
    would_decide,
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
    FakeToolRegistry,
)
from ai_assistant.tools.send_email import EMAIL, FROM_THE_PERSONS_ACCOUNT

if TYPE_CHECKING:
    from collections.abc import Iterable, MutableMapping

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
    """The stage over fakes, with the line store ``lines`` or none."""

    def __init__(
        self,
        *tools: ToolDefinition,
        lines: FakePermissionLineStore | None = None,
        binder: FakeEgressBinder | None = None,
        diagnostics: FakeDiagnosticSink | None = None,
    ) -> None:
        self.trail = FakeAuditTrail(now=_now)
        self.memory = FakeMemoryStore(now=_now)
        self.plans = FakePlanStore()
        self.stage = AuthorizingStage(
            registry=FakeToolRegistry(tools or (_LOOKUP, _BOOK)),
            policy=FakeActionPolicy(),
            trail=self.trail,
            stories=FakeStoryStore(now=_now),
            memory=self.memory,
            binder=binder,
            plans=self.plans,
            lines=lines,
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


def _unchecked(decided: RoundAuthorization) -> RoundAuthorization:
    """``decided`` with every check taken off: what today's rules decided."""
    return replace(
        decided,
        verdicts=tuple(replace(one, check=None) for one in decided.verdicts),
        call_messages=tuple(replace(one, check=None) for one in decided.call_messages),
    )


def _compared(logs: Iterable[MutableMapping[str, Any]]) -> list[MutableMapping[str, Any]]:
    return [one for one in logs if one["event"] == "permission_check_compared"]


def _two_calls() -> RoundToAuthorize:
    return replace(
        _round(_call("c1", "lookup", q="trains to Lyon"), _call("c2", "book", q="a table")),
        check_for=_OWNER,
    )


# --- recorded, and nothing changes ---------------------------------------------------------


async def test_every_call_records_the_check_and_what_is_decided_is_unchanged() -> None:
    """ADR-0379 §3:2, ADR-0367 §4:5: the outcome rides on the verdict; nothing else moves."""
    checking = _Hub(lines=FakePermissionLineStore(now=_now))
    plain = _Hub()

    with capture_logs() as logs:
        decided = await checking.authorize(_two_calls())
    before = await plain.authorize(_two_calls())

    assert [one.check for one in decided.verdicts] == [
        _ran((_NORMAL, _NO_LINE)),
        _ran((_NORMAL, _NO_LINE)),
    ]
    assert _unchecked(decided) == before
    assert [one.check for one in before.verdicts] == [None, None]
    assert await checking.trail.export() == await plain.trail.export()
    assert [
        (one["capability"], one["outcome"], one["decided"], one["differs"])
        for one in _compared(logs)
    ] == [
        ("lookup", "allowed_on_no_line", "allowed", False),
        ("book", "allowed_on_no_line", "allowed", False),
    ]


async def test_a_limit_is_recorded_and_the_call_is_still_done_as_today() -> None:
    """ADR-0379 §2:2: *not done: a limit covers it*, naming the limit; today's rules still
    run the call, and the log counts the disagreement in codes alone."""
    lines = FakePermissionLineStore(now=_now)
    limit = await _limit(lines, "book")
    hub = _Hub(lines=lines)

    with capture_logs() as logs:
        decided = await hub.authorize(_two_calls())

    lookup, book = decided.verdicts
    assert lookup.check == _ran((_NORMAL, _NO_LINE))
    assert book.check == _ran((_NORMAL, _outcome(CheckOutcomeKind.NOT_DONE_LIMIT, line=limit)))
    assert book.verdict is Verdict.ALLOWED
    assert [str(one.call.request.tool.capability) for one in decided.allowed] == [
        "lookup",
        "book",
    ]
    assert all(one.call.request.rests_on is None for one in decided.allowed)
    compared = _compared(logs)[1]
    assert compared["outcome"] == "not_done_limit"
    assert (compared["decided"], compared["would_decide"], compared["differs"]) == (
        "allowed",
        "not_done",
        True,
    )
    assert compared["ran_for"] == "person"
    assert compared["check_level"] == "normal"
    assert limit not in str(logs)
    assert OWNER_PERSON_ID not in str(logs)


async def test_lines_that_cannot_be_read_record_the_check_as_not_run() -> None:
    """A failed read is the check not having run, logged once, and decides nothing."""
    lines = FakePermissionLineStore(now=_now)
    lines.fail_next()
    hub = _Hub(lines=lines)

    with capture_logs() as logs:
        decided = await hub.authorize(_two_calls())

    unread = CallCheck(kind=CallCheckKind.LINES_UNREAD)
    assert [one.check for one in decided.verdicts] == [unread, unread]
    assert _unchecked(decided) == await _Hub().authorize(_two_calls())
    assert [one["reason"] for one in logs if one["event"] == "permission_check_unrun"] == [
        "lines_unread"
    ]
    assert [one["check"] for one in _compared(logs)] == ["lines_unread", "lines_unread"]


async def test_a_check_that_raises_is_recorded_as_failed_and_decides_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The brief's rule: recorded as such, and nothing changes."""

    def raising(*args: object, **kwargs: object) -> CallCheck:
        del args, kwargs
        msg = "a defect in the check"
        raise RuntimeError(msg)

    monkeypatch.setattr(authorizer, "checked", raising)
    hub = _Hub(lines=FakePermissionLineStore(now=_now))

    with capture_logs() as logs:
        decided = await hub.authorize(_two_calls())

    failed = CallCheck(kind=CallCheckKind.FAILED)
    assert [one.check for one in decided.verdicts] == [failed, failed]
    assert _unchecked(decided) == await _Hub().authorize(_two_calls())
    assert [one["reason"] for one in logs if one["event"] == "permission_check_failed"] == [
        "defect",
        "defect",
    ]


async def test_with_no_line_store_wired_nothing_is_checked() -> None:
    """No store, no check: every verdict carries none, as before the check was built."""
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


# --- whom it runs for --------------------------------------------------------------------


async def test_an_unidentified_senders_call_is_checked_for_a_member_of_anyone() -> None:
    """ADR-0368 §7:2: at none, the look-up's default at weak falls short; in a work that is
    no person's, a call needing a yes would not be done (§7:4)."""
    hub = _Hub(lines=FakePermissionLineStore(now=_now))
    anyone = CheckSubject(runs=(CheckedFor.anyone(),))

    with capture_logs() as logs:
        decided = await hub.authorize(
            replace(_round(_call("c1", "lookup", q="x")), check_for=anyone)
        )

    (verdict,) = decided.verdicts
    shortfall = _outcome(CheckOutcomeKind.NEEDS_YES_SHORTFALL, bar=Sureness.WEAK)
    assert verdict.check == _ran((CheckedFor.anyone(), shortfall))
    assert verdict.verdict is Verdict.ALLOWED
    (compared,) = _compared(logs)
    assert (compared["ran_for"], compared["would_decide"], compared["differs"]) == (
        "anyone",
        "not_done",
        True,
    )


async def test_several_senders_record_an_outcome_for_each() -> None:
    """ADR-0368 §7:3: the owner and an unidentified sender, each at none; done only where
    allowed for every one."""
    hub = _Hub(lines=FakePermissionLineStore(now=_now))
    owner_at_none = CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NONE)
    several = CheckSubject(runs=(owner_at_none, CheckedFor.anyone()))

    decided = await hub.authorize(replace(_round(_call("c1", "lookup", q="x")), check_for=several))

    (verdict,) = decided.verdicts
    shortfall = _outcome(CheckOutcomeKind.NEEDS_YES_SHORTFALL, bar=Sureness.WEAK)
    assert verdict.check == _ran((owner_at_none, shortfall), (CheckedFor.anyone(), shortfall))


async def test_a_round_handed_no_subject_is_checked_for_no_one() -> None:
    """A round that names no one holds no grant: it fails closed."""
    hub = _Hub(lines=FakePermissionLineStore(now=_now))
    decided = await hub.authorize(_round(_call("c1", "lookup", q="x")))

    (verdict,) = decided.verdicts
    assert verdict.check == _ran(
        (CheckedFor.no_one(), _outcome(CheckOutcomeKind.NOT_DONE_NO_GRANT))
    )


# --- a text call (ADR-0367 §4:7) ----------------------------------------------------------


def _texts(*places: str) -> RoundToAuthorize:
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
        check_for=_OWNER,
    )


async def test_a_text_into_the_inputs_place_stays_outside_and_another_is_checked() -> None:
    """§4:7: into the input's place, outside the check; into another connection, checked,
    its thing that connection, and a limit on it recorded while its place still decides."""
    lines = FakePermissionLineStore(now=_now)
    limit = await _limit(lines, "send_text", thing=_LINE)
    hub = _Hub(lines=lines)

    decided = await hub.authorize(_texts(_INPUT, _LINE))

    into_input, into_line = decided.call_messages
    assert into_input.check == CallCheck(kind=CallCheckKind.OUTSIDE)
    assert into_line.check == _ran((_NORMAL, _outcome(CheckOutcomeKind.NOT_DONE_LIMIT, line=limit)))
    assert (into_input.allowed, into_line.allowed) == (True, True)
    assert _unchecked(decided) == await _Hub().authorize(_texts(_INPUT, _LINE))


async def test_the_rounds_own_message_is_no_call_and_carries_no_check() -> None:
    hub = _Hub(lines=FakePermissionLineStore(now=_now))
    decided = await hub.authorize(
        replace(_round(message=RoundMessage("hi", _INPUT)), check_for=_OWNER)
    )
    assert decided.message is not None
    assert decided.message.check is None


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
    limit on that account is recorded, and every email still needs approval by rule."""
    binder = FakeEgressBinder()
    binder.register_egress(EMAIL, reference="conn-a", identity="me@example.com")
    lines = FakePermissionLineStore(now=_now)
    limit = await _limit(lines, "send_email", thing="account:conn-a")
    other = await _limit(lines, "send_email", thing="account:conn-b")
    hub = _Hub(EMAIL, lines=lines, binder=binder)

    decided = await hub.authorize(_email_round())

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NEEDS_YOU
    assert verdict.check == _ran((_NORMAL, _outcome(CheckOutcomeKind.NOT_DONE_LIMIT, line=limit)))
    assert other != limit


_BOOKING: Final = _BOOK.model_copy(update={"id": "book", "capability": "book"})


class _Policy:
    """Allows every call, so a ticket's call runs under its approval."""

    async def decide(self, request: object) -> PermissionRuling:
        del request
        return PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="test: allowed")

    async def resolve(self, confirmed: object, *, approved: bool) -> PermissionRuling:
        del confirmed, approved
        raise AssertionError


def _ticket_hub(lines: FakePermissionLineStore) -> tuple[AuthorizingStage, FakePlanStore]:
    plans = FakePlanStore()
    stage = AuthorizingStage(
        registry=FakeToolRegistry((_BOOKING, REQUEST_APPROVAL)),
        policy=_Policy(),
        trail=FakeAuditTrail(now=_now),
        stories=FakeStoryStore(now=_now),
        memory=FakeMemoryStore(now=_now),
        plans=plans,
        lines=lines,
        now=_now,
        new_decision_id=_Ids("decision"),
        new_effect_id=_Ids("effect"),
    )
    return stage, plans


async def test_request_approval_is_checked_as_a_call_of_its_own() -> None:
    """ADR-0379 §3:2: ``request_approval`` gets its own outcome; the call it asks about is
    a question, not a call made, and a limit on it does not reach the request's check."""
    lines = FakePermissionLineStore(now=_now)
    await _limit(lines, "book")
    stage, _ = _ticket_hub(lines)
    asking = CallToAuthorize(
        ProposedCall(
            call_id="ask-1",
            name="request_approval",
            arguments={"call": {"tool": "book", "arguments": {"q": "a table"}}, "why": "Asked."},
        )
    )

    decided = await stage.authorize(
        RoundToAuthorize(
            activation_id="act-1",
            round=PlanningRound(id="round:1", recorded_at=_AT, calls=(asking.call,)),
            working=WorkingRecord(),
            calls=(asking,),
            input_place=_INPUT,
            check_for=_OWNER,
        )
    )

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    assert verdict.check == _ran((_NORMAL, _NO_LINE))


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


@pytest.mark.parametrize(
    ("tap_level", "expected"),
    [
        (Sureness.NORMAL, _NO_LINE),
        (Sureness.WEAK, _outcome(CheckOutcomeKind.NEEDS_YES_SHORTFALL, bar=Sureness.NORMAL)),
        (None, _outcome(CheckOutcomeKind.NEEDS_YES_SHORTFALL, bar=Sureness.NORMAL)),
    ],
    ids=["tapped-at-normal", "tapped-at-weak", "level-not-recorded"],
)
async def test_a_tickets_call_is_checked_for_its_tapper_at_the_taps_level(
    tap_level: Sureness | None, expected: CheckOutcome
) -> None:
    """ADR-0367 §5:5, ADR-0377 §4:2, §4:4: whatever the work carries, the tapper at the
    level the tap came by, none where none is recorded; the ticket still runs as today."""
    stage, plans = _ticket_hub(FakePermissionLineStore(now=_now))
    tap = ApprovalTap(
        who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=_AT, person=OWNER_PERSON_ID, level=tap_level
    )
    request = await _answered(plans, tap)
    running = CallToAuthorize(
        ProposedCall(call_id="run-1", name="book", arguments={"q": "a table"}),
        ticket=str(request.id),
    )

    decided = await stage.authorize(
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

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED, verdict.reason
    tapper = CheckedFor.for_person(OWNER_PERSON_ID, tap_level or Sureness.NONE)
    assert verdict.check == _ran((tapper, expected))


# --- what would have been decided --------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "decided", "persons_work", "would"),
    [
        (CheckOutcomeKind.ALLOWED_ON_NO_LINE, Verdict.ALLOWED, True, Verdict.ALLOWED),
        (CheckOutcomeKind.ALLOWED_ON_NO_LINE, Verdict.NOT_DONE, True, Verdict.NOT_DONE),
        (CheckOutcomeKind.NEEDS_YES_WITH_APPROVAL, Verdict.ALLOWED, True, Verdict.NEEDS_YOU),
        (CheckOutcomeKind.NEEDS_YES_WITH_APPROVAL, Verdict.ALLOWED, False, Verdict.NOT_DONE),
        (CheckOutcomeKind.NEEDS_YES_WITH_APPROVAL, Verdict.NEEDS_YOU, True, Verdict.NEEDS_YOU),
        (CheckOutcomeKind.NOT_DONE_NO_GRANT, Verdict.NEEDS_YOU, True, Verdict.NOT_DONE),
        (CheckOutcomeKind.NOT_DONE_LIMIT, Verdict.NOT_DONE, True, Verdict.NOT_DONE),
    ],
)
def test_would_decide_is_the_more_severe_of_the_two(
    outcome: CheckOutcomeKind, decided: Verdict, persons_work: bool, would: Verdict
) -> None:
    """ADR-0367 §4:5: a call runs only where every check allows it; ADR-0368 §7:4."""
    carried: dict[str, Any] = {}
    if outcome is CheckOutcomeKind.NEEDS_YES_SHORTFALL:
        carried["bar"] = Sureness.NORMAL
    made = _ran((_NORMAL, _outcome(outcome, **carried)))
    assert would_decide(made, decided, persons_work=persons_work)[0] is would


def test_a_check_that_did_not_run_would_decide_nothing_new() -> None:
    for kind in (CallCheckKind.OUTSIDE, CallCheckKind.LINES_UNREAD, CallCheckKind.FAILED):
        assert would_decide(CallCheck(kind=kind), Verdict.ALLOWED, persons_work=True) == (
            Verdict.ALLOWED,
            None,
        )
