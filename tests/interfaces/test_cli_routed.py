"""The CLI's rendering of a routed pass: ADR-0197 §10, clause by clause.

**A consumer group and not a second decision** (ADR-0197 §12's last Normative). What
is under test is that this adapter renders the routed account beside the reply with
the renderer it already has for the operation, and that the two endings a user must
never confuse — ``UNRECORDED`` and ``FAILED`` — are not confusable on screen.

**Driven through** :func:`~ai_assistant.interfaces.cli._drive_turn` **over a scripted
engine**, which is the seam every other rendering case in this package uses: what a
routed pass *produces* is ``orchestration``'s and is pinned there, and seeding it
here would make each case a test of the router.

**The park cases go through the canonical fake's own** :meth:`park_routed`, because
ADR-0197 §7 makes a routed park doubly unreachable from the surface — it is never
listed by ``pending_confirmations`` and never recovered across a restart — so a lever
is the only way an adapter case can reach the resume path at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import TYPE_CHECKING, Final

import pytest
from rich.console import Console

from ai_assistant.core.types import (
    Belief,
    BeliefBand,
    GrantScope,
    MemoryKind,
    Question,
    QuestionState,
    ReadOutcome,
    RoutableOperation,
    RoutedOperation,
    RouteOutcome,
    SourceGrant,
    SourceReadRecord,
    TurnOutcome,
)
from ai_assistant.interfaces import cli
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from ai_assistant.core.types import OperationConfirmation, RoutedListing

pytestmark = pytest.mark.usefixtures("hermetic_assistant_env")

#: Fixed, so what a case asserts is a rendering rather than the run's clock.
_AT = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)

_PATIENT: Final = timedelta(seconds=30)

#: The answer a routed pass that is not a park owes (ADR-0197 §8). Present on every
#: non-park case below, because the clause this file is mostly about is that the
#: account is rendered **in addition to** it (§10) — a case carrying no reply could
#: not tell "rendered beside" from "rendered instead of".
_REPLY: Final = "Here is what I did."


# --- the subjects ------------------------------------------------------------


def _belief(record_id: str = "b-1", *, content: str = "you drink tea") -> Belief:
    """One live belief, as a routed ``forget`` would resolve it."""
    return Belief(
        id=record_id,
        band=BeliefBand.ASSERTED,
        kind=MemoryKind.PREFERENCE,
        content=content,
        confidence=0.9,
        last_updated=_AT,
    )


def _question(record_id: str = "q-1", *, content: str = "do you still cycle?") -> Question:
    """One deferred question, as a routed ``questions`` would list it."""
    return Question(
        id=record_id,
        state=QuestionState.OPEN,
        content=content,
        kind=MemoryKind.PREFERENCE,
        band=BeliefBand.DERIVED,
        rationale="you mentioned a bike",
        reason="I am not sure enough to hold it",
        retires=(),
        asked_at=_AT,
        expires_at=None,
    )


def _grant(source: str = "calendar") -> SourceGrant:
    """One live grant, as a routed ``revoke`` would resolve it."""
    return SourceGrant(id="g-1", source=source, scope=(GrantScope.INGEST,), decided_at=_AT)


def _read(record_id: str = "r-1") -> SourceReadRecord:
    """One recorded read attempt, as a routed ``recent_reads`` would list it."""
    return SourceReadRecord(
        id=record_id,
        source="calendar",
        use=GrantScope.INGEST,
        checked_at=_AT,
        outcome=ReadOutcome.COMPLETED,
        grant="g-1",
        produced=3,
    )


def _routed(
    operation: RoutableOperation,
    outcome: RouteOutcome,
    *,
    listing: RoutedListing | None = None,
    reply: str | None = _REPLY,
) -> TurnOutcome:
    """One routed pass, in the shape ADR-0197 §8 gives it.

    ``turn`` is ``None`` on every routed pass and ``step`` is never set beside
    ``routed`` — both are the type's own validators, so a case that got either wrong
    would fail at construction rather than assert against a shape the engine cannot
    produce.
    """
    return TurnOutcome(
        turn=None,
        conversation_id="c-1",
        routed=RoutedOperation(operation=operation, outcome=outcome, listing=listing),
        reply=reply,
    )


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer, wide enough that nothing wraps."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=400))
    return buffer


def _refuse_card(_card: OperationConfirmation) -> bool:
    """A routed approver for a pass that is not expected to park."""
    raise AssertionError("this turn was not expected to park a routed operation")


async def _drive(engine: FakeAssistantEngine, *, answer: bool | None = None) -> int:
    """Drive one turn and return the exit code, answering a routed card with ``answer``."""
    card: object = _refuse_card if answer is None else (lambda _c: answer)
    return await cli._drive_turn(
        engine,
        "forget that",
        timeout=_PATIENT,
        approver=lambda _c: True,
        confirm_operation=card,  # type: ignore[arg-type]  # one of two shapes per case
    )


# --- §10: the account is rendered beside the reply, never instead of it -------


async def test_a_routed_answer_is_rendered_beside_the_account(output: StringIO) -> None:
    """§10's first Normative, which is ADR-0170 §6's rule and binds for its reason.

    "An adapter renders the routed account … **in addition to** any composed reply,
    never instead of it, and never in place of it." Both are asserted on one screen,
    because a renderer that dropped either would still pass a case asserting only the
    other.
    """
    engine = FakeAssistantEngine()
    engine.turn_outcome = _routed(RoutableOperation.FORGET, RouteOutcome.PERFORMED)

    code = await _drive(engine)

    rendered = output.getvalue()
    assert _REPLY in rendered
    assert "That belief is destroyed." in rendered
    assert code == 0


async def test_a_routed_pass_is_never_reported_as_a_turn_that_planned_nothing(
    output: StringIO,
) -> None:
    """The #1404 defect one decision over (ADR-0197 §1, §8).

    A routed pass drives no plan and no step, so every branch this renderer has for a
    turn is skipped — and "No action was needed." above "That belief is destroyed."
    would be the deterministic account contradicted on its own screen, which is what
    ADR-0170 §6 exists to prevent.
    """
    engine = FakeAssistantEngine()
    engine.turn_outcome = _routed(RoutableOperation.FORGET, RouteOutcome.PERFORMED)

    await _drive(engine)

    assert "No action was needed." not in output.getvalue()


async def test_a_read_only_route_renders_the_listing_it_carried(output: StringIO) -> None:
    """§10's first Normative on "the listing where one is carried", and §12's clause
    that it is rendered "with the renderer it already has for the operation".

    Asserted through a field only the read renderer prints — the count, with the
    sentence ADR-0185 §2 obliges beside it — so a page that printed the records some
    other way would fail rather than pass on the id alone.
    """
    engine = FakeAssistantEngine()
    engine.turn_outcome = _routed(
        RoutableOperation.RECENT_READS, RouteOutcome.PERFORMED, listing=(_read(),)
    )

    await _drive(engine)

    rendered = output.getvalue()
    assert "1 read attempt(s)" in rendered
    assert "never the thing itself" in rendered


async def test_a_routed_questions_listing_uses_the_questions_renderer(
    output: StringIO,
) -> None:
    """The same clause on the arm a routed ``questions`` carries.

    ADR-0078 §8's conditional — "would be held as", never "is held" — is what is
    asserted, because it is the one thing a hand-rolled renderer would get wrong.
    """
    engine = FakeAssistantEngine()
    engine.turn_outcome = _routed(
        RoutableOperation.QUESTIONS, RouteOutcome.PERFORMED, listing=(_question(),)
    )

    await _drive(engine)

    rendered = output.getvalue()
    assert "do you still cycle?" in rendered
    assert "not held yet — I am asking first" in rendered


# --- §8 and §12: UNRECORDED and FAILED say opposite things --------------------


async def test_an_unrecorded_route_says_nothing_was_destroyed(output: StringIO) -> None:
    """ADR-0197 §8: ``UNRECORDED`` means the operation was "**never called** and
    nothing was destroyed", and §12 requires a surface that renders it like ``FAILED``
    to fail a test.

    **And it says to ask again rather than to retry** (§7): the park is already
    claimed by the time this ending is reached, so a surface offering the token again
    would be offering one that now raises ``UnknownContinuationError``.
    """
    engine = FakeAssistantEngine()
    engine.turn_outcome = _routed(RoutableOperation.FORGET, RouteOutcome.UNRECORDED)

    code = await _drive(engine)

    rendered = output.getvalue()
    assert "the belief is still held" in rendered
    assert "ask me again" in rendered
    assert "nothing to retry" in rendered
    assert code == 1, "this system failed to do what was asked (#531's rule)"


async def test_a_failed_route_does_not_claim_nothing_happened(output: StringIO) -> None:
    """ADR-0197 §8: ``FAILED`` means the operation "was **called and raised**, and the
    engine asserts nothing about whether it took effect".

    The pair with the case above is the discrimination §12 asks for: this one must not
    carry the ``UNRECORDED`` reassurance, and the one above must not carry this
    doubt.
    """
    engine = FakeAssistantEngine()
    engine.turn_outcome = _routed(RoutableOperation.FORGET, RouteOutcome.FAILED)

    code = await _drive(engine)

    rendered = output.getvalue()
    assert "Whether it took effect is not something I can tell you." in rendered
    assert "the belief is still held" not in rendered
    assert code == 1


# --- §5: an ambiguity ends the route and performs nothing ---------------------


@pytest.mark.parametrize("outcome", [RouteOutcome.AMBIGUOUS, RouteOutcome.AMBIGUOUS_TRUNCATED])
async def test_an_ambiguous_route_shows_every_candidate_and_performed_nothing(
    output: StringIO, outcome: RouteOutcome
) -> None:
    """§5: "Nothing was performed, nothing was confirmed, and the candidates ride
    ``listing``", and "no surface renders fewer candidates than the outcome carries or
    summarises in place of them".

    Both members are driven, because the two are "otherwise identical" and a renderer
    that handled only the first would leave the eighth member rendering as a fallback.
    """
    engine = FakeAssistantEngine()
    engine.turn_outcome = _routed(
        RoutableOperation.FORGET,
        outcome,
        listing=(_belief("b-1", content="you drink tea"), _belief("b-2", content="you drink chai")),
    )

    code = await _drive(engine)

    rendered = output.getvalue()
    assert "you drink tea" in rendered
    assert "you drink chai" in rendered
    assert "the belief is still held" in rendered
    assert code == 0, "an ambiguity is an answer to the request, not a failure of it"


async def test_the_truncated_member_says_there_are_more_than_it_can_show(
    output: StringIO,
) -> None:
    """§5: ``AMBIGUOUS_TRUNCATED`` "is the whole of what tells the reply the request
    matched more than can be shown", so the two must not read alike either."""
    engine = FakeAssistantEngine()
    engine.turn_outcome = _routed(
        RoutableOperation.FORGET, RouteOutcome.AMBIGUOUS_TRUNCATED, listing=(_belief(),)
    )

    await _drive(engine)

    assert "more than I can show" in output.getvalue()


async def test_a_route_that_matched_nothing_performed_nothing(output: StringIO) -> None:
    """§5: "Where it resolves to **none**, the route ends in ``NOT_FOUND``, nothing is
    performed and nothing is confirmed"."""
    engine = FakeAssistantEngine()
    engine.turn_outcome = _routed(RoutableOperation.REVOKE, RouteOutcome.NOT_FOUND)

    code = await _drive(engine)

    rendered = output.getvalue()
    assert "Nothing matches that." in rendered
    assert "the grant still stands" in rendered
    assert code == 0


# --- §7: the card, the answer, and the refusal that is a ruling ---------------


async def test_a_routed_park_renders_the_forget_ceremony_before_the_answer(
    output: StringIO,
) -> None:
    """ADR-0197 §7's last clause: ADR-0073 §5's show-then-confirm "binds the routed
    ``forget`` whole, including its band-appropriate warning and its ``--yes``
    idiom, which renders before acting rather than skipping the render".

    The band warning is the half that changes with the belief, so it is what is
    asserted: a card that showed the content and dropped it would be showing less than
    the typed door does.
    """
    engine = FakeAssistantEngine()
    card = engine.park_routed("h-1", operation=RoutableOperation.FORGET, subject=(_belief(),))
    engine.turn_outcome = TurnOutcome(
        turn=None,
        conversation_id="c-1",
        routed=RoutedOperation(
            operation=RoutableOperation.FORGET,
            outcome=RouteOutcome.AWAITING_CONFIRMATION,
            confirmation=card,
        ),
        reply=None,
    )

    await _drive(engine, answer=False)

    rendered = output.getvalue()
    assert "About to forget this belief" in rendered
    assert "you drink tea" in rendered
    assert "Forgetting it is permanent" in rendered


async def test_a_routed_park_is_answered_and_the_refusal_is_a_ruling(
    output: StringIO,
) -> None:
    """§7: "A ``resume`` whose ``approved`` is ``False`` performs nothing and returns
    ``RouteOutcome.REFUSED``" — **returned, never raised**.

    So the pass ends ``0`` and reads as the answer the user gave. An adapter that
    treated the refusal as an error would report a failure for a system that did
    exactly what it was told.
    """
    engine = FakeAssistantEngine()
    card = engine.park_routed("h-1", operation=RoutableOperation.FORGET, subject=(_belief(),))
    engine.turn_outcome = TurnOutcome(
        turn=None,
        conversation_id="c-1",
        routed=RoutedOperation(
            operation=RoutableOperation.FORGET,
            outcome=RouteOutcome.AWAITING_CONFIRMATION,
            confirmation=card,
        ),
        reply=None,
    )

    code = await _drive(engine, answer=False)

    rendered = output.getvalue()
    assert "You said no" in rendered
    assert "the belief is still held" in rendered
    assert code == 0
    assert ("resume", {"approved": False}) in [
        (name, {"approved": args.get("approved")}) for name, args in engine.calls
    ]


async def test_the_card_is_shown_even_when_the_answer_is_supplied(
    output: StringIO,
) -> None:
    """ADR-0052 §4 and ADR-0073 §5, as ADR-0197 §7 binds them to a routed ``forget``:
    ``--yes`` supplies the answer and never the rendering.

    Driven with an approver that always says yes, which is exactly what ``--yes``
    installs — so a renderer that only ran on the interactive path would fail here.
    """
    engine = FakeAssistantEngine()
    card = engine.park_routed("h-1", operation=RoutableOperation.FORGET, subject=(_belief(),))
    engine.turn_outcome = TurnOutcome(
        turn=None,
        conversation_id="c-1",
        routed=RoutedOperation(
            operation=RoutableOperation.FORGET,
            outcome=RouteOutcome.AWAITING_CONFIRMATION,
            confirmation=card,
        ),
        reply=None,
    )

    await _drive(engine, answer=True)

    assert "Forgetting it is permanent" in output.getvalue()


async def test_a_revoke_card_says_what_withdrawing_costs(output: StringIO) -> None:
    """§7's card clause on the arm ADR-0102 §4 gives no ceremony at the typed door.

    A routed ``revoke`` is confirm-owed anyway, and §3 says why: "what §7 guards is
    not the risk of the operation but the fact that a **model** selected it and its
    subject from a sentence". So the card exists, and it states what withdrawing does
    and does not do.
    """
    engine = FakeAssistantEngine()
    card = engine.park_routed("h-1", operation=RoutableOperation.REVOKE, subject=(_grant(),))
    engine.turn_outcome = TurnOutcome(
        turn=None,
        conversation_id="c-1",
        routed=RoutedOperation(
            operation=RoutableOperation.REVOKE,
            outcome=RouteOutcome.AWAITING_CONFIRMATION,
            confirmation=card,
        ),
        reply=None,
    )

    await _drive(engine, answer=False)

    rendered = output.getvalue()
    assert "About to withdraw the grant on one source" in rendered
    assert "calendar" in rendered
    assert "destroys nothing I have already learned from it" in rendered


async def test_a_routed_park_composes_no_answer_beside_the_question(
    output: StringIO,
) -> None:
    """§10's third Normative: on a routed park "the composing stage is not reached …
    the confirmation is what the user must answer, and prose beside it competes with
    the question".

    So nothing is rendered where a reply would go, and the assertion is over the
    *absence* of the degraded notice as well: ``reply`` ``None`` with
    ``reply_degraded`` ``False`` is a pass that owed no answer, not one that failed to
    compose one.
    """
    engine = FakeAssistantEngine()
    card = engine.park_routed("h-1", operation=RoutableOperation.FORGET, subject=(_belief(),))
    engine.turn_outcome = TurnOutcome(
        turn=None,
        conversation_id="c-1",
        routed=RoutedOperation(
            operation=RoutableOperation.FORGET,
            outcome=RouteOutcome.AWAITING_CONFIRMATION,
            confirmation=card,
        ),
        reply=None,
    )

    await _drive(engine, answer=False)

    assert "No answer could be composed" not in output.getvalue()


# --- §10's last clause: every rendered string is neutralised ------------------


async def test_a_hostile_record_reaches_the_terminal_neutralised(
    output: StringIO,
) -> None:
    """§10: "Every string an adapter renders out of a routed account is neutralised
    before display … On the CLI that is ``interfaces.cli._safe``."

    A belief's content is the user's own words and a grant's source is the identity a
    reader declared, so both are exactly the kind of value a renderer must not hand a
    terminal unescaped (ADR-0042 §4).
    """
    engine = FakeAssistantEngine()
    engine.turn_outcome = _routed(
        RoutableOperation.FORGET,
        RouteOutcome.AMBIGUOUS,
        listing=(
            _belief("b-1", content="[bold red]not a style[/]"),
            _belief("b-2", content="plain"),
        ),
    )

    await _drive(engine)

    rendered = output.getvalue()
    assert "[bold red]not a style[/]" in rendered, "rendered as text, not interpreted"
