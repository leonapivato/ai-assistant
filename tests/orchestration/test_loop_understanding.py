"""ADR-0249 §7 and §8 at the loop: the revision is recorded, then the plan is stamped.

The turn-shaped half of §16's L3 arms. What lives here is everything decided inside
:class:`~ai_assistant.orchestration.loop.LearningLoop` — §8's ordering (item 6, item 20),
§6's writer clause over a planner that supplies what it does not own (item 3), §7's
brief-of-the-new-revision rule across a turn's two calls, and §16 item 2's understanding
half over a continued goal. The resolution itself is ``test_interpretation.py``; the
persistence and the attempt's phases are ``test_engine_attempts.py``.

**The helpers are ``test_loop_reads``'s**, imported rather than restated, for
``test_loop_revision``'s own reason: this is the same loop over the same store shapes.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final

from test_loop_reads import _NOW, _belief, _bounded, _hop, _Journal, _loop
from test_loop_revision import _ASKED, _seeded

from ai_assistant.core.types import (
    ActionPlan,
    AttemptPhase,
    AttemptState,
    Goal,
    GoalInterpretation,
    Ground,
    MemorySource,
    PlannerOutput,
    ProposedElement,
    ProposedUnderstanding,
    Provenance,
    ReadAskOutcome,
)
from ai_assistant.orchestration.loop import ConversationalOperation

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from ai_assistant.core.types import (
        CurrentContext,
        EvidenceDigest,
        GoalBrief,
        MemoryRecord,
        ReadRequest,
        ShownFile,
    )
    from ai_assistant.orchestration.loop import RespondedTurn

#: What a planner that proposes no change returns — the value ADR-0249 §7 makes "the
#: semantically correct answer for a planner that knows nothing of this envelope".
_UNCHANGED: Final = None


class _Understanding:
    """A ``Planner`` answering each call of a turn with a scripted understanding.

    ADR-0228 §3 admits two calls per turn, so a planner steerable **per call** is what
    §16 items 3, 6 and 20 need: the arm that fails if the stamp is taken before the
    recording step is exactly a call that revises, and §7's clause that "where a call
    revised the understanding, the next receives the brief of the new revision" is a fact
    about what the *second* call was handed.

    It records the brief each call received, which is where that clause is asserted.
    """

    def __init__(
        self,
        *,
        understandings: Sequence[ProposedUnderstanding | None] = (),
        requests: Sequence[ReadRequest | None] = (),
        targets: Sequence[int | None] = (),
    ) -> None:
        """Script one planner.

        Args:
            understandings: What each call proposes, by 0-based call index. A call past
                the end proposes the **last** scripted value.
            requests: What each call emits, by the same indexing and run-off rule.
            targets: What each call's plan comes back **already carrying** in the field
                the loop owns (ADR-0249 §8) — the spoof §16 item 6 asserts is discarded.
        """
        self._understandings = understandings
        self._requests = requests
        self._targets = targets
        self.briefs: list[GoalBrief] = []

    @staticmethod
    def _at[T](script: Sequence[T], ordinal: int, default: T) -> T:
        if not script:
            return default
        return script[ordinal] if ordinal < len(script) else script[-1]

    async def plan(  # noqa: PLR0913 — the Planner Protocol's own parameter list
        self,
        goal: GoalBrief,
        *,
        utterance: str,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
        read_outcomes: Sequence[ReadAskOutcome] = (),
        evidence: Sequence[EvidenceDigest] = (),
    ) -> PlannerOutput:
        """Answer this call from the script, recording the brief it was handed."""
        del utterance, context, memories, capabilities, files, read_outcomes, evidence
        ordinal = len(self.briefs)
        self.briefs.append(goal)
        return PlannerOutput(
            plan=ActionPlan(
                id=f"{goal.goal_id}-plan-{ordinal + 1}",
                goal_id=goal.goal_id,
                steps=(),
                created_at=_NOW,
                rationale=f"call {ordinal + 1}",
                read_request=self._at(self._requests, ordinal, None),
                targets_revision=self._at(self._targets, ordinal, None),
            ),
            understanding=self._at(self._understandings, ordinal, _UNCHANGED),
        )


def _restated(outcome: str, span: str) -> ProposedUnderstanding:
    """An understanding restating the outcome on a span of this turn's own request."""
    return ProposedUnderstanding(
        outcome=outcome, outcome_ground=Ground.USER_STATED, outcome_span=span
    )


async def _turn(planner: _Understanding, *, continuing: Goal | None = None) -> RespondedTurn:
    """One ``converse`` turn over a seeded store."""
    return await _loop(await _seeded(), planner=planner).respond(
        _ASKED,
        narrow=_bounded(),
        operation=ConversationalOperation.CONVERSE,
        conversation_id="c-1",
        continuing=continuing,
    )


# --------------------------------------------------------------------------- #
# §16 item 20 / item 6 — the stamp is taken *after* the recording step         #
# --------------------------------------------------------------------------- #


async def test_a_revising_call_yields_a_plan_targeting_the_revision_it_produced() -> None:
    """§16 item 20: "an ordinary revising turn drives".

    "A planner call that receives revision 1 and returns **both** a
    ``ProposedUnderstanding`` and an actionable plan yields a plan whose
    ``targets_revision`` is the revision that call produced, not the one it received — so
    the plan is driveable, no second planner call is needed, and ADR-0228 §2's entry
    conditions are not reached. **The arm fails if the stamp is taken before the
    recording step.**"
    """
    planner = _Understanding(understandings=[_restated("lease the flat", "lease")])

    responded = await _turn(planner)

    assert len(planner.briefs) == 1, "one call: nothing licensed a second"
    assert planner.briefs[0].outcome == _ASKED, "the call *received* revision 1"
    assert responded.turn.plan.targets_revision == 2, "and the plan targets what it produced"
    record = responded.goal
    assert record is not None
    assert record.goal.revision == 2
    assert [one.revision for one in record.goal.interpretation] == [1, 2]


async def test_a_call_that_proposes_nothing_yields_a_plan_targeting_what_it_received() -> None:
    """§16 item 6's first case: revision 1 in, no understanding, a plan targeting 1.

    "``None`` means **the planner proposed no change to the understanding**", and no
    implementation reads it as an error, a degradation, or an instruction to re-plan.
    """
    planner = _Understanding()

    responded = await _turn(planner)

    assert responded.turn.plan.targets_revision == 1
    record = responded.goal
    assert record is not None
    assert len(record.goal.interpretation) == 1, "nothing was recorded"


async def test_a_value_the_planner_supplied_in_the_stamp_is_discarded() -> None:
    """§8, §16 item 6: "whatever the planner returned in that field".

    "The loop takes the field for its own: it discards any value the plan came back
    carrying", silently — not an error, not a park, not a degradation of the turn.
    """
    planner = _Understanding(understandings=[_restated("lease the flat", "lease")], targets=[97])

    responded = await _turn(planner)

    assert responded.turn.plan.targets_revision == 2, "not 97, and not a refusal"


# --------------------------------------------------------------------------- #
# §7 — the next call receives the brief of the new revision                    #
# --------------------------------------------------------------------------- #


async def test_the_second_call_of_a_revising_turn_receives_the_new_revisions_brief() -> None:
    """§7, and ADR-0228 §1's clause as ADR-0249 §14 keeps it.

    "Both calls plan for one goal under one ``goal_id``" still binds; what §1 no longer
    claims is that both calls see the same brief. A turn whose first call revised hands
    its second the brief of the **new** revision, which is the half of the owner's third
    correction §7 is the envelope for.
    """
    asking = _hop("M1")
    planner = _Understanding(
        understandings=[
            ProposedUnderstanding(
                retains_outcome=True,
                constraints=(
                    ProposedElement(text="lease", ground=Ground.USER_STATED, span="lease"),
                ),
            ),
            _UNCHANGED,
        ],
        requests=[asking, None],
    )

    responded = await _turn(planner)

    first, second = planner.briefs
    assert first.goal_id == second.goal_id, "ADR-0228 §1: one goal under one goal_id"
    assert first.constraints == (), "revision 1 carries no element at all"
    assert [one.text for one in second.constraints] == ["lease"]
    assert responded.turn.plan.targets_revision == 2, "and the driven plan targets it"


async def test_the_turns_own_brief_is_the_current_revisions() -> None:
    """§11: ``TurnResult.goal`` is the projection, and it is the goal as the turn left it.

    A widened ``Goal`` on ``TurnOutcome.turn`` would put the interpretation chain and its
    ground references on the wire; what goes instead carries the **current** outcome.
    """
    planner = _Understanding(understandings=[_restated("lease the flat", "lease")])

    responded = await _turn(planner)

    assert responded.turn.goal.outcome == "lease the flat"
    assert responded.turn.goal.outcome_ground is Ground.USER_STATED
    assert not hasattr(responded.turn.goal, "interpretation")
    assert responded.turn.utterance == _ASKED, "ADR-0248 §1: the request rides beside it"


# --------------------------------------------------------------------------- #
# §6 — the three phases this loop stamps, before any row exists to carry them  #
# --------------------------------------------------------------------------- #


async def test_the_loop_stamps_the_turns_first_three_phases_in_order() -> None:
    """§6, and §16 item 1's first three of six.

    "A new attempt opens at ``UNDERSTAND``", the phase "advances in that order and never
    moves backwards", and "a phase whose work is vacuous is stamped and left in the same
    instant" — so a turn that services no read still passes through ``INVESTIGATE``. The
    three after them are the engine's and are asserted in ``test_engine_attempts``: the
    attempt is **opened in memory** here and written at ADR-0249 §11's site, so there is
    no row for these three to be observed on.
    """
    planner = _Understanding()

    responded = await _turn(planner)

    attempt = responded.attempt
    assert attempt is not None
    assert attempt.phases == (
        AttemptPhase.UNDERSTAND,
        AttemptPhase.INVESTIGATE,
        AttemptPhase.PLAN,
    )
    assert attempt.attempt.phase is AttemptPhase.PLAN, "the phase the row is written at"
    assert attempt.attempt.state is AttemptState.RUNNING
    assert attempt.attempt.effort.planner_calls == 1, "§5's ledger"


async def test_recording_a_revision_does_not_move_the_phase() -> None:
    """§6: "recording an interpretation revision does not move the phase".

    "An understanding revised during investigation advances the goal's ``version``, which
    is what §8's stale-target rule keys on, and leaves the attempt where it stood."
    """
    planner = _Understanding(understandings=[_restated("lease the flat", "lease")])

    responded = await _turn(planner)

    attempt = responded.attempt
    assert attempt is not None
    assert attempt.phases == (
        AttemptPhase.UNDERSTAND,
        AttemptPhase.INVESTIGATE,
        AttemptPhase.PLAN,
    ), "the same three as a turn that recorded nothing"


async def test_a_clock_that_goes_backwards_does_not_fail_the_turn() -> None:
    """§5: the ledger never goes negative, and a wall clock guarantees nothing.

    "Both are monotonically non-decreasing within an attempt … and no implementation
    subtracts from one." :class:`~ai_assistant.core.types.AttemptEffort` refuses a
    negative ``working`` at construction, so an adjustment backwards between the turn's
    entry and the moment the ledger is stamped would raise out of a turn that had
    already planned — losing the record of everything it did in order to avoid losing a
    duration. ADR-0009's injected clock supplies wall-clock instants and promises no
    monotonicity, which is what makes this reachable rather than theoretical.
    """
    readings = iter((_NOW, _NOW, _NOW - timedelta(seconds=1)))

    def backwards() -> datetime:
        return next(readings, _NOW - timedelta(seconds=1))

    planner = _Understanding()

    responded = await _loop(await _seeded(), planner=planner, now=backwards).respond(
        _ASKED,
        narrow=_bounded(),
        operation=ConversationalOperation.CONVERSE,
        conversation_id="c-1",
    )

    attempt = responded.attempt
    assert attempt is not None
    assert attempt.attempt.effort.working == timedelta(0), "nothing, and never negative"


# --------------------------------------------------------------------------- #
# §16 item 3 — the writer clause                                               #
# --------------------------------------------------------------------------- #


async def test_the_stamped_provenance_is_the_loops_and_the_envelope_carries_none() -> None:
    """§16 item 3: the writer clause, over the turn that exercises it.

    A planner "envelope that comes back carrying a phase, or a revision number, or a
    ``raised_by``, or a ``recorded_at``" has those values discarded — and here the
    discarding is **structural**: ``ProposedUnderstanding`` has no field any of them
    could arrive on, which is the containment L1 built. What this arm holds is the other
    half, that the values actually stamped are the loop's own and the turn is not
    degraded.
    """
    assert {"phase", "revision", "raised_by", "recorded_at"}.isdisjoint(
        ProposedUnderstanding.model_fields
    ), "no field a planner could write provenance into"
    planner = _Understanding(understandings=[_restated("lease the flat", "lease")])

    responded = await _turn(planner)

    record = responded.goal
    assert record is not None
    recorded = record.goal.interpretation[-1]
    assert recorded.revision == 2, "minted one greater than the revision it follows"
    assert recorded.recorded_at == _NOW, "this turn's own instant, from the injected clock"
    assert recorded.raised_by is not None, "§1 forbids None on a value orchestration authors"
    assert responded.turn.plan.steps == (), "and the turn ran to its end unharmed"


async def test_every_revision_one_turn_authors_names_the_same_turn() -> None:
    """§1: ``raised_by`` is "the conversation **turn** whose message caused this revision".

    One turn, one identifier — for the revision it opened the goal with and for every
    revision its planner calls then produce. A value minted per call would attribute one
    turn's revisions to two turns that never existed, and an assertion that the field is
    merely non-``None`` would not notice.
    """
    planner = _Understanding(
        understandings=[
            _restated("lease the flat", "lease"),
            _restated("lease the flat by March", "lease"),
        ],
        requests=[_hop("M1"), None],
    )

    responded = await _turn(planner)

    assert len(planner.briefs) == 2, "the turn really did make both calls"
    record = responded.goal
    assert record is not None
    raised = [one.raised_by for one in record.goal.interpretation]
    assert len(raised) == 3, "revision 1 and one per call"
    assert all(one is not None for one in raised)
    assert len(set(raised)) == 1, "one turn, one identifier"


# --------------------------------------------------------------------------- #
# §16 item 2 — S2's understanding half, over a goal the loop did not open      #
# --------------------------------------------------------------------------- #


def _finished() -> Goal:
    """A goal an earlier turn opened and an earlier attempt worked on.

    Its revision 1 is exactly what :meth:`LearningLoop._goal_from` mints, so the case
    asserts over the shape this system actually stores rather than over a hand-built one.
    """
    return Goal(
        id="goal-earlier",
        conversation_id="c-1",
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome="book a campsite",
                outcome_ground=Ground.USER_STATED,
                outcome_span="book a campsite",
                recorded_at=_NOW,
                raised_by="turn-earlier",
            ),
        ),
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_NOW),
        created_at=_NOW,
        last_engaged_at=_NOW,
        version=4,
    )


async def test_a_follow_up_opens_a_new_attempt_on_the_same_goal() -> None:
    """§16 item 2, and §5's "a reopened goal starts a new attempt".

    "A **new attempt** on the **same** goal, a new interpretation revision whose
    ``raised_by`` names this turn and whose changed element grounds ``USER_STATED`` on a
    span of this turn's request, and every prior revision retained unedited."

    **Which goal a turn continues is A2's** (§13) and no production caller supplies one,
    so the association is the case's here — what this lane owns is everything that
    follows from being given one.
    """
    earlier = _finished()
    planner = _Understanding(
        understandings=[
            ProposedUnderstanding(
                retains_outcome=True,
                constraints=(
                    ProposedElement(text="lease", ground=Ground.USER_STATED, span="lease"),
                ),
            )
        ]
    )

    responded = await _turn(planner, continuing=earlier)

    record = responded.goal
    assert record is not None
    assert record.goal.id == earlier.id, "the same goal"
    assert not record.opened, "§12: its revisions take record_interpretation, not save_goal"
    assert record.goal.interpretation[0] == earlier.interpretation[0], "prior revision unedited"
    (revision,) = record.revisions
    assert revision.revision == 2
    assert revision.raised_by is not None, "and it names this turn"
    assert revision.outcome == "book a campsite", "retained byte for byte"
    (constraint,) = revision.constraints
    assert constraint.ground is Ground.USER_STATED
    assert constraint.span == "lease", "a span of *this* turn's request"
    attempt = responded.attempt
    assert attempt is not None
    assert attempt.attempt.goal_id == earlier.id, "a new attempt on the same goal"
    assert attempt.attempt.id != earlier.id


async def test_a_continued_goals_expected_version_is_the_one_the_loop_received() -> None:
    """§12: the compare-and-swap token the revision was computed against.

    ``Goal.version`` "orders writes" and is the store's; the loop carries the value it
    read and advances nothing, so ``Engine`` has exactly the token
    ``record_interpretation`` must be given.
    """
    earlier = _finished()
    planner = _Understanding(understandings=[_restated("lease the flat", "lease")])

    responded = await _turn(planner, continuing=earlier)

    record = responded.goal
    assert record is not None
    assert record.goal.version == earlier.version == 4, "unmoved by the loop"


async def test_a_seeded_supply_grounds_an_element_on_the_record_the_loop_labelled() -> None:
    """§7 over a real turn: the stamped ``evidence_id`` is a record of *this* supply.

    Asserted at the loop rather than over the resolver alone, because the supply the
    label indexes into is the one the loop passed **on that call** — ADR-0226 §3's label
    space, which ADR-0228 §8 binds per call.
    """
    store = _Journal()
    await store.add(_belief("m-seed", "the lease runs to March"))
    planner = _Understanding(
        understandings=[
            ProposedUnderstanding(
                retains_outcome=True,
                conditions=(
                    ProposedElement(
                        text="the lease runs to March",
                        ground=Ground.FROM_EVIDENCE,
                        evidence_label="M1",
                    ),
                ),
            )
        ]
    )

    responded = await _loop(store, planner=planner).respond(
        _ASKED,
        narrow=_bounded(),
        operation=ConversationalOperation.CONVERSE,
        conversation_id="c-1",
    )

    record = responded.goal
    assert record is not None
    (condition,) = record.goal.interpretation[-1].conditions
    assert condition.evidence_id == "m-seed"
    assert condition.span is None, "a FROM_EVIDENCE element carries no span"
