"""The canonical engine fake carries ADR-0262 §6's report, and on which shapes.

:class:`~ai_assistant.testing.FakeAssistantEngine` is the double every consumer of
``AssistantEngine`` is certified against, and ADR-0026 §7 binds it to the contract
rather than to a convenience. ADR-0262 §11 gives L1 "the canonical fakes carrying the
new field" and gives **L5** the six fixed statements "on the CLI and on the browser —
**both surfaces**, since a member rendered on one and not the other is the parity
failure M4 recorded".

The two obligations meet here. §6 makes the member non-``None`` "exactly on a turn that
ended an attempt under §4", and this double runs no verification phase and ends no
attempt — so every one of the six :class:`AttemptOutcome` members a surface owes a fixed
statement for is a state **nothing this fake does can arrive at**. A lever is what makes
them reachable, and without it L5's renderer would be written, tested green against this
double, and never read the field at all. That is issue #2381's shape one member over,
and it is why the lever lands with the field rather than with its first renderer.

**``None`` is the default and is the honest value**, not a stand-in: §6 leaves the
member absent on every turn that ended no attempt, which on this double is every turn.
That is the opposite default to ADR-0264 §7's statement — which states a fact about the
pass and so must be filled in — and it is :attr:`FakeAssistantEngine.authorizations`'s
ground read one member over.
"""

from __future__ import annotations

from base64 import b64encode
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from ai_assistant.core.types import (
    ActionPlan,
    AttemptOutcome,
    AttemptReport,
    Belief,
    BeliefBand,
    CurrentContext,
    GoalBrief,
    GoalStatus,
    Ground,
    MemoryKind,
    ReadAnswerOutcome,
    RoutableOperation,
    RoutedOperation,
    RouteOutcome,
    SpokenAudio,
    SpokenAudioFormat,
    TimeOfDay,
    TurnOutcome,
    TurnResult,
)
from ai_assistant.testing import FakeAssistantEngine

PATIENT: Final = timedelta(seconds=30)
_AT: Final = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)

#: One recording, whose octets are never read: ``converse_spoken`` hears
#: :attr:`FakeAssistantEngine.spoken_transcript` and not this.
RECORDING: Final = SpokenAudio(
    content=b64encode(b"a recording").decode(), media_type=SpokenAudioFormat.WEBM_OPUS
)

#: One report, for the cases that only need *a* report rather than a particular member.
VERIFIED: Final = AttemptReport(outcome=AttemptOutcome.VERIFIED, continues=False)

#: The members ADR-0262 §4's limbs yield, which are the six §6 fixes a statement for.
#: Derived rather than transcribed — see the case that pins the derivation.
COMPARED: Final[frozenset[AttemptOutcome]] = frozenset(AttemptOutcome) - {AttemptOutcome.CANCELLED}


def _belief() -> Belief:
    """One live belief, as a routed ``forget`` resolves it."""
    return Belief(
        id="b-1",
        band=BeliefBand.ASSERTED,
        kind=MemoryKind.PREFERENCE,
        content="prefers riverside pitches",
        confidence=0.9,
        last_updated=_AT,
    )


def _scripted(**overrides: object) -> TurnOutcome:
    """A scripted outcome carrying a reply, which needs a real :class:`TurnResult`.

    ``TurnOutcome`` refuses prose beside a ``None`` ``turn`` — a recovered park
    persisted no context to compose from — so the shape a consumer actually scripts is
    this one, and the lever has to reach it.
    """
    fields: dict[str, object] = {
        "turn": TurnResult(
            utterance="book it",
            goal=GoalBrief(
                goal_id="g-1",
                outcome="book a campsite",
                outcome_ground=Ground.USER_STATED,
                status=GoalStatus.ACTIVE,
            ),
            context=CurrentContext(
                now=_AT,
                time_of_day=TimeOfDay.MORNING,
                within_working_hours=True,
                is_weekend=False,
            ),
            memories=(),
            plan=ActionPlan(id="p-1", goal_id="g-1", steps=(), created_at=_AT, targets_revision=1),
        ),
        "reply": "a scripted answer",
    }
    return TurnOutcome(**{**fields, **overrides})  # type: ignore[arg-type]  # heterogeneous test kwargs


async def test_a_turn_carries_no_report_until_one_is_scripted() -> None:
    """§6: ``None`` on every turn that ended no attempt, which is every turn here.

    A fake ends no attempt, so the absent value is what a conforming engine would return
    and the default is not a gap to be filled. Asserted first, because a lever whose
    default were a report would certify a consumer against an outcome shape claiming
    work this double never did.
    """
    engine = FakeAssistantEngine()

    outcome = await engine.converse("hello", timeout=PATIENT)

    assert outcome.reply is not None
    assert outcome.attempt_report is None


@pytest.mark.parametrize("member", sorted(COMPARED))
async def test_the_lever_drives_a_composed_turn_over_every_compared_member(
    member: AttemptOutcome,
) -> None:
    """§11's L5 owes a fixed statement per member; this is what makes each reachable.

    **The six §4's limbs yield, and not the seventh.** §6 fixes one statement per
    member and enumerates six; ``CANCELLED`` is reached by no limb, because a cancelled
    attempt is ADR-0261 §2's act and ADR-0249 §5's *"no transition leaves a terminal
    member"* keeps it out of this phase's reach. Driving a double over all seven would
    put a consumer under pressure to mint a seventh statement §6 does not authorise,
    which is the widening the case below refuses outright.
    """
    engine = FakeAssistantEngine()
    engine.attempt_report = AttemptReport(outcome=member, continues=False)

    outcome = await engine.converse("book it", timeout=PATIENT)

    assert outcome.attempt_report == AttemptReport(outcome=member, continues=False)


def test_the_six_are_every_member_but_the_one_this_phase_never_writes() -> None:
    """The roster above, derived from the enumeration rather than transcribed from it.

    Spelling the six out as literals would leave this file silently short a case when a
    later decision adds a member the comparison *does* yield — the failure ADR-0261 §3
    made real by taking ``AttemptOutcome`` from six to seven. Deriving them means such
    a member arrives parametrized, and a member this phase must not write has to be
    named here to be excluded.
    """
    assert set(AttemptOutcome) - COMPARED == {AttemptOutcome.CANCELLED}
    assert len(COMPARED) == 6, "ADR-0262 §6's six fixed statements, one per member"


async def test_the_lever_refuses_the_member_no_limb_reaches() -> None:
    """§4: *"**no lane writes ``AttemptOutcome.CANCELLED`` from this phase**"*.

    A report naming it is a state no engine reaches, so a double that let a consumer
    arrange one would certify that consumer against a shape no conforming engine
    returns — *"the looseness ADR-0026 §7 forbids"*, in
    :meth:`FakeAssistantEngine._stating`'s own words one member over. Refused rather
    than passed silently, which is
    :class:`~ai_assistant.testing.FakeToolRegistry`'s rule for the single arrangement
    mistake a consumer could plausibly make.

    **The refusal is on the arrangement and not on the type.** :class:`AttemptReport`
    still admits the member — it is handed one rather than computing one, and narrowing
    it would be this decision policing a value ADR-0261 §3 owns — which
    ``tests/core/test_attempt_report_types.py`` pins from the other side.
    """
    engine = FakeAssistantEngine()
    engine.attempt_report = AttemptReport(outcome=AttemptOutcome.CANCELLED, continues=False)

    with pytest.raises(ValueError, match="CANCELLED"):
        await engine.converse("book it", timeout=PATIENT)


async def test_the_report_rides_beside_the_reply_and_never_in_place_of_it() -> None:
    """§6: rendered **beside** the reply, which is what a surface needs both of.

    The member does not set ``reply_degraded`` and does not take the reply's place: a
    turn that ended an attempt still composed the answer it composed.
    """
    engine = FakeAssistantEngine()
    engine.attempt_report = VERIFIED

    outcome = await engine.converse("book it", timeout=PATIENT)

    assert outcome.reply is not None
    assert outcome.reply_degraded is False
    assert outcome.attempt_report == VERIFIED


async def test_a_streamed_turn_carries_it_on_the_terminal_outcome() -> None:
    """The streaming twin, which a client reads the member off exactly as it reads ``reply``.

    ADR-0262 §11 gives L5 **both** surfaces at once, and the browser reads a streamed
    turn's terminal outcome — so a double carrying the member on ``converse`` and not
    here would leave one of the two surfaces untestable, which is the parity failure §11
    names.
    """
    engine = FakeAssistantEngine()
    engine.attempt_report = VERIFIED

    outcome: TurnOutcome | None = None
    async for piece in engine.converse_streaming("book it", timeout=PATIENT):
        if isinstance(piece, TurnOutcome):
            outcome = piece

    assert outcome is not None
    assert outcome.attempt_report == VERIFIED


async def test_a_spoken_turn_carries_it_although_no_statement_is_spoken() -> None:
    """§6's statement is rendered by a surface, and ``spoken`` is not one.

    ADR-0200 §4 makes ``spoken`` the rendering of ``reply`` and of nothing else — the
    same fact ADR-0264 §12 books as a stated cost for its own statement — and that is a
    fact about the surface rather than a reason to leave the member off the outcome. A
    consumer reading a spoken turn's outcome finds it there.
    """
    engine = FakeAssistantEngine()
    engine.attempt_report = VERIFIED
    engine.spoken_transcript = "book it"

    spoken = await engine.converse_spoken(
        RECORDING, plays=(SpokenAudioFormat.WEBM_OPUS,), timeout=PATIENT
    )

    assert spoken.outcome is not None
    assert spoken.outcome.attempt_report == VERIFIED


async def test_a_pass_that_composed_no_reply_is_given_none() -> None:
    """§4's first ending condition is a **completed reply**, so a reply-less pass ends none.

    An answer to a read park that is already settled composes nothing at all — its
    ``turn`` and ``reply`` are both ``None`` — so there is no turn for a report to be
    about, and filling one in there would assert what no conforming engine could. This
    is the lever's boundary, asserted rather than left to the default's accident.
    """
    engine = FakeAssistantEngine()
    engine.attempt_report = VERIFIED
    offered = engine.park_read("h-1", query="bell tower porto")
    await engine.resume(offered.token, approved=True, timeout=PATIENT)

    settled = await engine.resume(offered.token, approved=True, timeout=PATIENT)

    assert settled.read_answer is ReadAnswerOutcome.ALREADY_SETTLED
    assert settled.reply is None
    assert settled.attempt_report is None


async def test_a_routed_pass_is_given_none_although_it_composed_a_reply() -> None:
    """§6: ``None`` on **a routed operation** (ADR-0197 §7), and prose does not change it.

    ADR-0197 §10's routed answer owes a reply and has one, so a lever gated on prose
    alone would attach a report to it. It must not: a routed pass "mints no goal,
    assembles no context and makes no plan" (ADR-0197 §8), so there is no attempt for a
    report to be about, and §6 names the shape in terms. The arm that fails against a
    double filling the member in wherever it finds text.
    """
    engine = FakeAssistantEngine()
    engine.attempt_report = VERIFIED
    card = engine.park_routed("h-1", operation=RoutableOperation.FORGET, subject=(_belief(),))

    outcome = await engine.resume(card.token, approved=True, timeout=PATIENT)

    assert outcome.routed is not None
    assert outcome.reply is not None
    assert outcome.attempt_report is None


async def test_a_pass_that_made_no_plan_is_given_none() -> None:
    """§6: a report is about **an attempt an ending turn compared**, and this made none.

    Every shape on which :attr:`TurnOutcome.turn` is ``None`` made no ``Planner.plan``
    call — a recovered park, a routed pass and an undecided turn — and §4's first
    ending condition is a reply such a pass never composed. Asserted through a scripted
    outcome, because that is the shape a consumer builds and the one a lever reaching
    too far would spoil.
    """
    engine = FakeAssistantEngine()
    engine.attempt_report = VERIFIED
    engine.turn_outcome = TurnOutcome(turn=None, step=None)

    outcome = await engine.converse("hello", timeout=PATIENT)

    assert outcome.turn is None
    assert outcome.attempt_report is None


async def test_a_reply_that_did_not_complete_is_given_none() -> None:
    """§4's first ending condition is a ``ComposedReply`` *"carrying text and **not
    degraded**"* (ADR-0173 §6).

    Streaming makes a shape ADR-0170 could not have — an answer that **began and did not
    finish** — which carries the text actually yielded beside ``reply_degraded`` ``True``.
    Text alone is therefore not the test: such a turn ended no attempt, so it carries no
    report, and a lever gated on prose would say it did.
    """
    engine = FakeAssistantEngine()
    engine.attempt_report = VERIFIED
    engine.turn_outcome = _scripted(reply_degraded=True)

    outcome = await engine.converse("book it", timeout=PATIENT)

    assert outcome.reply is not None
    assert outcome.reply_degraded is True
    assert outcome.attempt_report is None


async def test_a_report_scripted_onto_an_ineligible_pass_is_refused() -> None:
    """The arrangement mistake refused rather than dropped.

    A consumer that scripted a report onto a pass which ended no attempt has built an
    outcome no engine returns; dropping it silently would leave their test green against
    the outcome they believed they had built, and the shape they are actually certifying
    a surface over would be the opposite one. Refusing says which of §6's shapes it is.

    Asserted over a **routed** pass carrying its own report, which is the case the lever
    gate alone would not catch — the report is on the outcome and never passes through
    the lever at all.
    """
    engine = FakeAssistantEngine()
    engine.turn_outcome = TurnOutcome(
        turn=None,
        routed=RoutedOperation(operation=RoutableOperation.FORGET, outcome=RouteOutcome.PERFORMED),
        reply="I forgot that.",
        attempt_report=VERIFIED,
    )

    with pytest.raises(ValueError, match="ended no attempt"):
        await engine.converse("forget that", timeout=PATIENT)


async def test_a_scripted_outcome_keeps_the_report_it_carries() -> None:
    """The lever is a value for a pass this engine composed, never a rewrite of one.

    :attr:`FakeAssistantEngine.authorizations`'s discipline exactly: a caller who stated
    the member on the outcome has stated it, and overwriting that with this engine's
    attribute would silently discard the arrangement.
    """
    scripted = AttemptReport(outcome=AttemptOutcome.PARTIAL, continues=True)
    engine = FakeAssistantEngine()
    engine.attempt_report = VERIFIED
    engine.turn_outcome = _scripted(attempt_report=scripted)

    outcome = await engine.converse("book it", timeout=PATIENT)

    assert outcome.attempt_report == scripted


async def test_a_scripted_outcome_with_no_report_takes_the_lever_s() -> None:
    """And the other half: the lever is what a consumer drives a surface from.

    An outcome scripted through :attr:`turn_outcome` is the shape most consumers build,
    so a lever that only reached the synthesised turn would be one L5 could not use.
    """
    engine = FakeAssistantEngine()
    engine.attempt_report = VERIFIED
    engine.turn_outcome = _scripted()

    outcome = await engine.converse("book it", timeout=PATIENT)

    assert outcome.attempt_report == VERIFIED
