"""The activation controller: stages run by rules, every choice recorded (ADR-0280).

The controller repeats one step until the pass ends: evaluate the rules in their
fixed order against the pass's working set, take the first that answers, and either
run the stage it makes due and append that stage's entry, or append the end entry
and stop (§3). It calls no model and makes no store read or write of its own; a
stage adds its decisions to the working set and never chooses what runs next.

Everything here is orchestration-local (§3): no Protocol in ``core`` describes a
stage or the controller, because nothing outside ``orchestration`` implements or
calls either, and the interface is expected to change as later milestones split
the turn loop and the drive into stages of their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Protocol

from ai_assistant.core.errors import (
    ChannelProcessingTimeoutError,
    ModelTimeoutError,
    SpeechTimeoutError,
)
from ai_assistant.core.types import (
    ControllerRule,
    ControllerStage,
    StageEntry,
    StageOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from datetime import datetime

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import Disposition, RouteOutcome

#: The classified timeouts a stage can end in (§5). Each is already the row
#: ``terminal_status`` files under ``TIMEOUT``, and the bare ``TimeoutError`` is what
#: an ``asyncio.timeout`` around a stage raises.
_TIMEOUTS = (ModelTimeoutError, ChannelProcessingTimeoutError, SpeechTimeoutError, TimeoutError)


def stage_timed_out(error: BaseException) -> bool:
    """Whether a stage's raise is classified ``timed_out`` rather than ``failed`` (§5)."""
    return isinstance(error, _TIMEOUTS)


#: The stage record's bound where nothing wires one (§6). The composition root wires
#: its own ``STAGE_RECORD_LIMIT``; this is the value a directly constructed engine or
#: admitted state takes.
DEFAULT_STAGE_RECORD_LIMIT: Final = 64


class PassFacts(Protocol):
    """The working set's decisions, as the rules read them (ADR-0280 §3, §4).

    Every member answers from a decision a stage made on the pass — or from what
    the pass was wired with — and never from whether a stage has run. A decision
    that nothing came of is still a decision: a declined route, an association that
    found no goal, a degraded composed reply.
    """

    @property
    def conversation_turn(self) -> bool:
        """The pass is a conversation turn, typed or spoken."""

    @property
    def informational_event(self) -> bool:
        """The pass is an informational event."""

    @property
    def conversation_resolved(self) -> bool:
        """The conversation the turn runs under has been resolved."""

    @property
    def routing_wired(self) -> bool:
        """The deployment wired the routing stage."""

    @property
    def route_decided(self) -> bool:
        """Routing has decided, ``declined`` or ``taken``."""

    @property
    def route_taken(self) -> bool:
        """Routing took the route."""

    @property
    def windows_decided(self) -> bool:
        """The windows stage recorded the pass's windows (ADR-0282 §3)."""

    @property
    def recall_wired(self) -> bool:
        """The deployment wired the recall stage (ADR-0281 §2)."""

    @property
    def recall_decided(self) -> bool:
        """Recall made its decision, including that it found nothing or failed."""

    @property
    def deadline_passed(self) -> bool:
        """The pass's deadline has passed (ADR-0281 §5)."""

    @property
    def understanding_wired(self) -> bool:
        """The deployment wired the understanding stage."""

    @property
    def understanding_decided(self) -> bool:
        """The understanding stage has an outcome for the input."""

    @property
    def event_summarized(self) -> bool:
        """The event summary has been produced."""

    @property
    def associated(self) -> bool:
        """Association has decided, including that it found no goal."""

    @property
    def asks_which_goal(self) -> bool:
        """The association asks which goal is meant."""

    @property
    def disambiguation_asked(self) -> bool:
        """The disambiguation question has been asked."""

    @property
    def continues_goal(self) -> bool:
        """The association continues a stored goal."""

    @property
    def reconciliation_wired(self) -> bool:
        """The deployment wired reconciliation for this pass."""

    @property
    def reconciled(self) -> bool:
        """Reconciliation has a result."""

    @property
    def turn_decided(self) -> bool:
        """``LearningLoop.respond`` returned a turn."""

    @property
    def turn_raised_question(self) -> bool:
        """The turn's planner raised a question."""

    @property
    def plan_has_steps(self) -> bool:
        """The turn's plan has at least one step."""

    @property
    def drive_decided(self) -> bool:
        """The drive has a disposition, including a withheld claim."""

    @property
    def parked(self) -> bool:
        """The driven step parked for confirmation."""

    @property
    def reply_composed(self) -> bool:
        """A composed reply is present, degraded or not."""


@dataclass(frozen=True)
class Rule:
    """One row of §4's table: the rule, when it answers, and what it makes due."""

    name: ControllerRule
    answers: Callable[[PassFacts], bool]
    makes_due: ControllerStage


def _turn_asks_nothing(facts: PassFacts) -> bool:
    return facts.conversation_turn and facts.associated and not facts.asks_which_goal


#: ADR-0280 §4's table, in its order, with ADR-0281 §2's row. The first rule that
#: answers decides, and ``nothing_due`` is last and always answers, so every pass ends
#: by a rule.
ACTIVATION_RULES: Final[tuple[Rule, ...]] = (
    Rule(
        ControllerRule.CONVERSATION_UNRESOLVED,
        lambda f: f.conversation_turn and not f.conversation_resolved,
        ControllerStage.BEGIN_CONVERSATION,
    ),
    Rule(
        ControllerRule.ROUTE_UNCHECKED,
        lambda f: f.conversation_turn and f.routing_wired and not f.route_decided,
        ControllerStage.ROUTING,
    ),
    Rule(ControllerRule.ROUTE_TAKEN, lambda f: f.route_taken, ControllerStage.END),
    # ADR-0282 §3: the windows are assembled before recall, wherever understanding is.
    Rule(
        ControllerRule.WINDOWS_UNASSEMBLED,
        lambda f: f.understanding_wired and not f.windows_decided,
        ControllerStage.WINDOWS,
    ),
    # ADR-0281 §2: recall runs before understanding, and only where both are wired.
    Rule(
        ControllerRule.NOT_RECALLED,
        lambda f: f.recall_wired and f.understanding_wired and not f.recall_decided,
        ControllerStage.RECALL,
    ),
    Rule(
        ControllerRule.NOT_UNDERSTOOD,
        lambda f: f.understanding_wired and not f.understanding_decided,
        ControllerStage.UNDERSTANDING,
    ),
    Rule(
        ControllerRule.EVENT_UNSUMMARIZED,
        lambda f: (
            f.informational_event
            and not f.event_summarized
            and (f.understanding_decided or not f.understanding_wired)
        ),
        ControllerStage.EVENT_SUMMARY,
    ),
    Rule(
        ControllerRule.ASSOCIATION_DUE,
        lambda f: f.conversation_turn and not f.associated,
        ControllerStage.ASSOCIATE_GOAL,
    ),
    Rule(
        ControllerRule.DISAMBIGUATION_RAISED,
        lambda f: f.asks_which_goal and not f.disambiguation_asked,
        ControllerStage.ASK_DISAMBIGUATION,
    ),
    Rule(
        ControllerRule.CONTINUING_UNRECONCILED,
        lambda f: f.continues_goal and f.reconciliation_wired and not f.reconciled,
        ControllerStage.RECONCILE,
    ),
    Rule(
        ControllerRule.UNPLANNED,
        lambda f: _turn_asks_nothing(f) and not f.turn_decided,
        ControllerStage.TURN_LOOP,
    ),
    Rule(
        ControllerRule.PLAN_HAS_STEPS,
        lambda f: (
            f.turn_decided
            and not f.turn_raised_question
            and f.plan_has_steps
            and not f.drive_decided
        ),
        ControllerStage.DRIVE,
    ),
    Rule(
        ControllerRule.REPLY_OWED,
        lambda f: f.turn_decided and not f.parked and not f.reply_composed,
        ControllerStage.COMPOSE,
    ),
    Rule(ControllerRule.NOTHING_DUE, lambda _: True, ControllerStage.END),
)


@dataclass(frozen=True)
class Verdict:
    """The verdict a ``drive`` or a ``routing`` stage reached (ADR-0284 §5:1-§5:2).

    Each is ``None`` where the stage reached none: a drive whose claim was withheld,
    a routing stage that declined, a stage that raised before deciding.

    Attributes:
        step_disposition: The driven step's :class:`~ai_assistant.core.types.Disposition`.
        route_outcome: The taken route's :class:`~ai_assistant.core.types.RouteOutcome`.
    """

    step_disposition: Disposition | None = None
    route_outcome: RouteOutcome | None = None


#: A stage that reaches no verdict.
NO_VERDICT: Final = Verdict()


@dataclass(frozen=True)
class StageResult:
    """How one stage ended, and the error it carried where it did not end ``done``.

    The outcome and the verdict enter the stage's :class:`StageEntry`; the error never
    does (§5). It is carried here so the controller can end the pass and re-raise it.
    The verdict is ADR-0284 §5:2's: what a ``drive`` or a ``routing`` stage concluded,
    read off the working set once the stage returned.

    ``tolerated`` is set only by a failure-tolerant stage (ADR-0281 §5) returning a
    ``failed`` or ``timed_out`` it caught and handled, after recording its decision.
    While the pass's deadline has not passed, the controller then continues rather
    than ending the pass.
    """

    outcome: StageOutcome
    error: Exception | None = None
    tolerated: bool = False
    verdict: Verdict = NO_VERDICT


class ControllerStageRun[P](Protocol):
    """A stage as the controller runs it: a name and one method (§3)."""

    @property
    def name(self) -> ControllerStage:
        """Which stage this is."""

    async def run(self, state: P) -> StageResult:
        """Run over the pass's working set, adding its decisions there."""


@dataclass(frozen=True)
class Stage[P]:
    """An existing engine method run as a stage, its raise classified (§5).

    ``body`` runs with the same inputs and effects it has always had. A raise it
    ends in is ``timed_out`` where the error is a classified timeout and ``failed``
    otherwise; a cancellation is not an outcome and propagates.

    ``expired`` is how a stage that runs inside a deadline says it already passed:
    it answers the classified deadline error, or ``None`` while there is time. A
    stage whose deadline had passed when it was due is not entered — its body does
    no I/O at all — and yields ``timed_out`` carrying that error (§5).

    ``verdict`` is how a ``drive`` or a ``routing`` stage hands the controller the
    verdict it reached (ADR-0284 §5:2), read off the working set once the body
    ended, however it ended: the body records its decision there, and a stage that
    raised before deciding has none to read.
    """

    name: ControllerStage
    body: Callable[[P], Awaitable[None]]
    expired: Callable[[P], Exception | None] | None = None
    verdict: Callable[[P], Verdict] | None = None

    async def run(self, state: P) -> StageResult:
        """Run the body, unless its deadline already passed, and classify how it ended."""
        if self.expired is not None and (late := self.expired(state)) is not None:
            return StageResult(StageOutcome.TIMED_OUT, late)
        try:
            await self.body(state)
        except _TIMEOUTS as exc:
            return StageResult(StageOutcome.TIMED_OUT, exc, verdict=self._verdict(state))
        except Exception as exc:
            return StageResult(StageOutcome.FAILED, exc, verdict=self._verdict(state))
        return StageResult(StageOutcome.DONE, verdict=self._verdict(state))

    def _verdict(self, state: P) -> Verdict:
        return NO_VERDICT if self.verdict is None else self.verdict(state)


@dataclass(frozen=True)
class TolerantStage[P]:
    """A failure-tolerant stage (ADR-0281 §5), its escaped raise classified as ``Stage``'s.

    ``body`` catches the failures it handles, records its decision in the working
    set, and returns a :class:`StageResult` marked ``tolerated``. A raise that
    escapes it is classified exactly as :class:`Stage` classifies one, and is never
    tolerated: the pass ends on ADR-0280 §5:2's fixed default. ``expired`` is as on
    :class:`Stage`, and a stage not entered because the deadline passed is not
    tolerated either.

    ``expired`` is read again once the body returns: past the deadline, **whatever
    the body returned** is ``timed_out`` carrying the deadline error, untolerated
    (ADR-0281 §5). A body can cross the deadline without the timer firing, and its
    returned outcome would otherwise let the pass continue.
    """

    name: ControllerStage
    body: Callable[[P], Awaitable[StageResult]]
    expired: Callable[[P], Exception | None] | None = None

    async def run(self, state: P) -> StageResult:
        """Run the body, unless its deadline already passed, and classify an escaped raise."""
        if self.expired is not None and (late := self.expired(state)) is not None:
            return StageResult(StageOutcome.TIMED_OUT, late)
        try:
            result = await self.body(state)
        except _TIMEOUTS as exc:
            return StageResult(StageOutcome.TIMED_OUT, exc)
        except Exception as exc:
            return StageResult(StageOutcome.FAILED, exc)
        if self.expired is not None and (late := self.expired(state)) is not None:
            return StageResult(StageOutcome.TIMED_OUT, late)
        return result


@dataclass
class StageRecord:
    """The entries a pass accumulates, readable while it runs (§6).

    Written as each stage ends and frozen by the end entry (ADR-0286 §3, §4), each
    write by :meth:`bounded`. Exactly one end entry is ever appended, and it is last.
    The controller appends to it, and so does the resume path, which the controller
    does not run (ADR-0284 §5:5).
    """

    entries: list[StageEntry] = field(default_factory=list)

    @property
    def ended(self) -> bool:
        """The pass's end entry has been appended."""
        return bool(self.entries) and self.entries[-1].stage is ControllerStage.END

    def append(self, entry: StageEntry) -> None:
        """Append one entry; nothing follows the end entry.

        Raises:
            RuntimeError: If the pass already ended.
        """
        if self.ended:
            msg = "a stage record carries exactly one end entry, last (ADR-0280 §6)"
            raise RuntimeError(msg)
        self.entries.append(entry)

    def end(self, rule: ControllerRule, at: datetime) -> None:
        """Append the end entry, due to ``rule``, at one instant."""
        self.append(
            StageEntry(
                stage=ControllerStage.END,
                due=rule,
                started_at=at,
                ended_at=at,
                outcome=StageOutcome.DONE,
            )
        )

    def bounded(
        self, limit: int, *, ending: tuple[ControllerRule, datetime] | None = None
    ) -> tuple[tuple[StageEntry, ...], int]:
        """The record as it is written, and the count of entries elided (§6).

        Where more than ``limit`` were recorded, keeps the first ``limit // 2`` and
        the last ``limit - limit // 2``, in order. The end entry is last, so it is
        never elided. ``ending`` supplies the end entry for a pass that ended before
        the controller appended one; it is ignored where one stands, and the record
        is not changed by it.

        Raises:
            ValueError: If ``limit`` is below 2, which cannot keep the first entry
                and the end entry both.
        """
        if limit < 2:  # noqa: PLR2004 — the first entry and the end entry
            msg = "the stage record keeps its first entry and its end entry (ADR-0280 §6)"
            raise ValueError(msg)
        entries = tuple(self.entries)
        if ending is not None and not self.ended:
            rule, at = ending
            entries = (
                *entries,
                StageEntry(
                    stage=ControllerStage.END,
                    due=rule,
                    started_at=at,
                    ended_at=at,
                    outcome=StageOutcome.DONE,
                ),
            )
        if len(entries) <= limit:
            return entries, 0
        head = limit // 2
        tail = limit - head
        return (*entries[:head], *entries[-tail:]), len(entries) - limit


async def run_recorded[T](  # noqa: PLR0913 — where to record, which stage and why, the clock, the body, its verdict and the append
    record: Callable[[], StageRecord | None],
    stage: ControllerStage,
    due: ControllerRule,
    *,
    clock: Clock,
    body: Callable[[], Awaitable[T]],
    verdict: Callable[[T], Verdict] | None = None,
    appended: Callable[[], Awaitable[None]] | None = None,
    stopped: Callable[[], bool] | None = None,
) -> T:
    """Run one stage the controller does not run, and record it (ADR-0284 §5:4-§5:5).

    The resume path is not run by the controller; it records the stages it runs
    through the controller's own :class:`StageRecord`, on the same terms. The entry
    is appended once the body ends: ``done`` carrying the verdict ``verdict`` reads
    off what the body returned, or ``timed_out`` or ``failed`` classified as
    :class:`Stage` classifies a raise — and then the end entry, due
    ``stage_timed_out`` or ``stage_failed``, and the error re-raised. A cancellation
    is not an outcome and propagates, unrecorded, as it does under the controller.

    ``record`` is read once the body ends rather than before it starts, because the
    resume's activation is admitted at its resolution point, inside the body. Where
    it answers ``None`` — no activation was admitted — nothing is recorded, as a pass
    with no admitted activation records into nothing. A record already ended is
    left alone.

    Args:
        record: The stage record to append to, read once the body ends.
        stage: Which stage the body is.
        due: The rule that made it due.
        clock: The clock the entry's instants are read from.
        body: The stage's work.
        verdict: The verdict the body's result carries, for a ``drive`` or a
            ``routing`` stage.
        appended: Awaited once the stage's entry is appended, so the episode is
            extended as the stage ends (ADR-0286 §3, §9). It never raises but for a
            cancellation.
        stopped: Whether the activation's stop mark is set (ADR-0297 §4). A resume
            that raised once its mark is set ends with the stop's end entry rather
            than ``stage_failed`` or ``stage_timed_out``, and the error is still
            re-raised: what the resume does about it — return what it established
            where its answer was recorded, or raise — is its caller's.

    Returns:
        What the body returned.

    Raises:
        Exception: Whatever the body raised, once the entry and the end entry are
            recorded.
    """
    started_at = clock()
    try:
        result = await body()
    except Exception as exc:
        timed_out = stage_timed_out(exc)
        target = record()
        if target is not None and not target.ended:
            target.append(
                StageEntry(
                    stage=stage,
                    due=due,
                    started_at=started_at,
                    ended_at=clock(),
                    outcome=StageOutcome.TIMED_OUT if timed_out else StageOutcome.FAILED,
                )
            )
            if appended is not None:
                await appended()
            if stopped is not None and stopped():
                target.end(ControllerRule.STOPPED, clock())
            else:
                target.end(
                    ControllerRule.STAGE_TIMED_OUT if timed_out else ControllerRule.STAGE_FAILED,
                    clock(),
                )
        raise
    target = record()
    if target is not None and not target.ended:
        reached = NO_VERDICT if verdict is None else verdict(result)
        target.append(
            StageEntry(
                stage=stage,
                due=due,
                started_at=started_at,
                ended_at=clock(),
                outcome=StageOutcome.DONE,
                step_disposition=reached.step_disposition,
                route_outcome=reached.route_outcome,
            )
        )
        if appended is not None:
            await appended()
    return result


class ActivationController[P: PassFacts]:
    """Run a pass's stages by §4's rules and record every choice (ADR-0280 §3)."""

    def __init__(
        self,
        *,
        stages: Sequence[ControllerStageRun[P]],
        clock: Clock,
        rules: Sequence[Rule] = ACTIVATION_RULES,
        appended: Callable[[], Awaitable[None]] | None = None,
        stopped: Callable[[], bool] | None = None,
    ) -> None:
        """Hold the stages, the clock, the rule table and what follows each entry.

        ``appended`` is awaited once each stage's entry is appended, so the episode is
        extended as the stage ends (ADR-0286 §3). It never raises but for a
        cancellation, and the end entry is not followed by it: that entry is the
        freeze's (§4).

        ``stopped`` reads the activation's stop mark (ADR-0297 §3, §4), the one thing
        the controller reads besides the pass's state; a pass with no activation to
        stop leaves it ``None``, and is never marked.
        """
        self._stages: Mapping[ControllerStage, ControllerStageRun[P]] = {
            stage.name: stage for stage in stages
        }
        self._clock = clock
        self._rules = tuple(rules)
        self._appended = appended
        self._stopped = stopped

    def _marked(self) -> bool:
        return self._stopped is not None and self._stopped()

    def _due(self, state: P) -> Rule:
        for rule in self._rules:
            if rule.answers(state):
                return rule
        msg = "no rule answered: the table ends with one that always does (ADR-0280 §4)"
        raise RuntimeError(msg)

    async def run(self, state: P, record: StageRecord) -> None:  # noqa: C901 — §3's one step, with ADR-0297 §4's two readings of the stop mark in it
        """Run the pass to its end entry.

        Ends with the rule that ended it; with ``stage_repeated`` where the first
        rule that answers names a stage this pass already ran (the M38 loop guard);
        with ``stage_failed`` or ``stage_timed_out`` where a stage did not end
        ``done``, re-raising its error — save a failure-tolerant stage's tolerated
        result while the pass's deadline has not passed, after which the rules are
        evaluated again (ADR-0281 §5); and with ``interrupted`` where the pass is
        cancelled or interrupted while the controller runs.

        **A stopped pass leaves the loop** (ADR-0297 §4). The stop mark is read before
        each evaluation of the rules and again once each stage's result is in hand,
        before the fixed default; where it is set, the loop is left without evaluating
        the rules, running a stage or appending an end entry, and the ``finally``
        appends ``stopped`` where it would append ``interrupted``. A stage that failed
        or timed out once the mark was set ends the pass with the stop's end entry, and
        its error is **not** re-raised: the stop was taken in first, so it is what
        ended the pass. No task is cancelled, and a cancellation that reaches a marked
        pass still propagates, its end entry still the stop's.

        Raises:
            Exception: The error a stage that failed or timed out carried, on a pass
                whose stop mark was not set when its result was in hand.
        """
        ran: set[ControllerStage] = set()
        try:
            while True:
                if self._marked():
                    return
                rule = self._due(state)
                stage = rule.makes_due
                if stage is ControllerStage.END:
                    record.end(rule.name, self._clock())
                    return
                if stage in ran:
                    record.end(ControllerRule.STAGE_REPEATED, self._clock())
                    return
                runner = self._stages.get(stage)
                if runner is None:
                    msg = f"rule {rule.name} made {stage} due, which this pass does not wire"
                    raise RuntimeError(msg)
                ran.add(stage)
                started_at = self._clock()
                result = await runner.run(state)
                record.append(
                    StageEntry(
                        stage=stage,
                        due=rule.name,
                        started_at=started_at,
                        ended_at=self._clock(),
                        outcome=result.outcome,
                        step_disposition=result.verdict.step_disposition,
                        route_outcome=result.verdict.route_outcome,
                    )
                )
                if self._appended is not None:
                    await self._appended()
                if self._marked():
                    return
                if result.outcome is StageOutcome.DONE:
                    continue
                if result.tolerated and not state.deadline_passed:
                    continue
                record.end(
                    ControllerRule.STAGE_TIMED_OUT
                    if result.outcome is StageOutcome.TIMED_OUT
                    else ControllerRule.STAGE_FAILED,
                    self._clock(),
                )
                assert result.error is not None  # noqa: S101 — a stage that did not end done carries its error
                raise result.error
        finally:
            if not record.ended:
                record.end(
                    ControllerRule.STOPPED if self._marked() else ControllerRule.INTERRUPTED,
                    self._clock(),
                )
