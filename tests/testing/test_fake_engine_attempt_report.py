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
    CurrentContext,
    GoalBrief,
    GoalStatus,
    Ground,
    ReadAnswerOutcome,
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


@pytest.mark.parametrize("member", list(AttemptOutcome))
async def test_the_lever_drives_a_composed_turn_over_every_member(
    member: AttemptOutcome,
) -> None:
    """§11's L5 owes a fixed statement per member; this is what makes each reachable.

    Every member rather than the six §4's limbs yield: ``CANCELLED`` is reached by no
    limb of the comparison, but it **is** a member of the vocabulary
    :attr:`AttemptReport.outcome` is typed by, and a double that refused to be driven
    over it would decide for a consumer which values it may test its handling of.
    """
    engine = FakeAssistantEngine()
    engine.attempt_report = AttemptReport(outcome=member, continues=False)

    outcome = await engine.converse("book it", timeout=PATIENT)

    assert outcome.attempt_report == AttemptReport(outcome=member, continues=False)


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
