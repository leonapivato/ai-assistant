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

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Protocol

from ai_assistant.core.diagnostics import diagnosed_activation, failure_body, write_diagnostic
from ai_assistant.core.errors import ModelTimeoutError, SpeechTimeoutError
from ai_assistant.core.types import (
    ControllerRule,
    ControllerStage,
    DiagnosticKind,
    DiagnosticSource,
    StageEntry,
    StageOutcome,
)
from ai_assistant.orchestration.defects import is_defect, log_defect

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
    from datetime import datetime

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import DiagnosticSink
    from ai_assistant.core.types import Disposition, RouteOutcome

#: The classified timeouts a stage can end in (§5). Each is already the row
#: ``terminal_status`` files under ``TIMEOUT``, and the bare ``TimeoutError`` is what
#: an ``asyncio.timeout`` around a stage raises.
_TIMEOUTS = (ModelTimeoutError, SpeechTimeoutError, TimeoutError)


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
    def understanding_recorded(self) -> bool:
        """The understanding outcome is a recorded version (ADR-0300 §6:11)."""

    @property
    def story_links_wired(self) -> bool:
        """The deployment wired the story-links stage (ADR-0300 §6:10)."""

    @property
    def story_links_decided(self) -> bool:
        """The story-links stage made its decision, a failed one included (§6:10)."""

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

    @property
    def phases(self) -> PhaseFacts | None:
        """The phases' decisions, where the pass runs them (ADR-0309 §2:6, §3).

        ``None`` on a pass the phases do not plan, which no phase rule answers on.
        """


class PhaseFacts(Protocol):
    """The phases' part of the working set, as the phase rules read it (ADR-0309 §3).

    Each member answers from a decision a phase recorded for the latest round, a
    decision nothing came of included (ADR-0280 §3:6). "The latest round" is the last
    planning round the working set holds, whether or not its append returned (ADR-0307
    §2:4).
    """

    @property
    def recalled_again(self) -> bool:
        """Recall's second run made its decision, a failed one included (ADR-0308 §2)."""

    @property
    def recall_kept_outside(self) -> bool:
        """Either recall run kept a memory record whose source is outside (ADR-0308 §4:5)."""

    @property
    def recall_digested(self) -> bool:
        """The digesting stage decided recall's digest, a failed one included (§4:4)."""

    @property
    def rounds(self) -> int:
        """How many planning rounds the pass has run."""

    @property
    def round_limit(self) -> int:
        """The most rounds a pass runs (ADR-0307 §8:4); its value is #2589's."""

    @property
    def latest_round(self) -> str | None:
        """The latest round's id, or ``None`` before the first."""

    @property
    def latest_has_calls(self) -> bool:
        """The latest round proposed at least one call, refused ones included."""

    @property
    def latest_has_text(self) -> bool:
        """The latest round's text is not blank."""

    @property
    def latest_authorized(self) -> bool:
        """There is an authorizing decision for the latest round, whatever came of it."""

    @property
    def latest_allows(self) -> bool:
        """The latest round's authorizing decision allows a call or its message."""

    @property
    def latest_acted(self) -> bool:
        """There is an acting decision for the latest round, whatever came of it."""

    @property
    def latest_digests_due(self) -> bool:
        """A call the latest round allows declares a result that may carry outside text."""

    @property
    def latest_calls_beyond_tidy_ups(self) -> bool:
        """The latest round proposed a call other than a tidy-up, refused ones included.

        Such a round brings another once its calls have finished, whatever they brought
        back; a tidy-up never brings one (ADR-0315 §2:1, §2:2).
        """


@dataclass(frozen=True)
class Rule:
    """One row of §4's table: the rule, when it answers, and what it makes due.

    ``per`` scopes ADR-0280 §4:6's loop guard: a stage made due under a rule with
    ``per`` runs at most once for each value it answers, rather than once a pass. The
    phase rows scope it to the latest round, so each phase runs at most once per round
    and planning once per round, bounded by the round limit (ADR-0307 §11, ADR-0309
    §3:5).

    ``beside`` names a stage run side by side with the one the rule makes due, in one
    step, where ``beside_when`` answers (ADR-0309 §3:3, §7's *a rule may name a stage
    run beside the one it makes due*). Each records its own entry, due the rule.
    """

    name: ControllerRule
    answers: Callable[[PassFacts], bool]
    makes_due: ControllerStage
    per: Callable[[PassFacts], object] | None = None
    beside: ControllerStage | None = None
    beside_when: Callable[[PassFacts], bool] | None = None


def _phases(facts: PassFacts) -> PhaseFacts:
    """The pass's phase decisions, which a phase rule reads only where the pass has them.

    Raises:
        RuntimeError: If the pass runs no phases. Every pass the controller runs is
            planned by them (ADR-0309 §2:6), so one that is not reached this table
            from a path the cutover retired.
    """
    phases = facts.phases
    if phases is None:
        msg = "the controller's rules run only on a pass the phases plan (ADR-0309 §2:6)"
        raise RuntimeError(msg)
    return phases


def _latest_round(facts: PassFacts) -> object:
    """The loop guard's scope for a phase stage: the latest round (ADR-0309 §3:5)."""
    return _phases(facts).latest_round


def _round_finished(phases: PhaseFacts) -> bool:
    """Every call of the latest round has finished, digests included (ADR-0315 §2:1).

    The round's authorizing decision is made, and where it allowed anything, the step
    that ran it, acting with its digests beside it, has ended.
    """
    return phases.latest_authorized and (phases.latest_acted or not phases.latest_allows)


def _another_round_called_for(facts: PassFacts) -> bool:
    """ADR-0315 §2: a new round is called for.

    The latest round proposed a call other than a tidy-up, and every call of it has
    finished, whatever its calls brought back (§2:1). A round whose only calls are
    tidy-ups, like a round with no calls, ends the activation after its message (§2:2,
    §2:3); the round limit ends every loop this makes (§2:4).
    """
    phases = _phases(facts)
    return phases.rounds > 0 and phases.latest_calls_beyond_tidy_ups and _round_finished(phases)


def _second_run(_: PassFacts) -> object:
    """The loop guard's scope for recall's second run (ADR-0308 §2:10).

    The first run is due under ``not_recalled``, unscoped, and the second under
    ``understood_not_recalled``, scoped here: recall runs at most once under each, so at
    most twice on a pass, and ADR-0280 §4:6's guard ends a pass that would run it a
    third time under either.
    """
    return ControllerRule.UNDERSTOOD_NOT_RECALLED


def recall_digest_due(phases: PhaseFacts) -> bool:
    """ADR-0308 §4:5: recall's digest is due.

    The second-run decision is made, either run kept a memory record whose source is
    outside, and there is no recall digest. The phase path's one ``digesting`` stage
    reads it too, to run recall's digest rather than a round's.
    """
    return phases.recalled_again and phases.recall_kept_outside and not phases.recall_digested


def _recall_digest(_: PassFacts) -> object:
    """The loop guard's scope for recall's digest (ADR-0309 §3:5).

    Digesting runs once for recall's digest, under ``recall_undigested``, and once per
    round beside acting, scoped by the round; ADR-0280 §4:6's guard ends a pass that
    would run recall's digest again.
    """
    return ControllerRule.RECALL_UNDIGESTED


#: ADR-0309 §3's table, in its order, the controller's only table (§2:6, §7:1). The first
#: rule that answers decides, and ``nothing_due`` is last and always answers, so every
#: pass ends by a rule. The old path's rows are gone from it (§3:6); the members that
#: named them stay in ``ControllerRule`` until the types lane removes them.
ACTIVATION_RULES: Final[tuple[Rule, ...]] = (
    Rule(
        ControllerRule.CONVERSATION_UNRESOLVED,
        lambda f: f.conversation_turn and not f.conversation_resolved,
        ControllerStage.BEGIN_CONVERSATION,
    ),
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
    # ADR-0300 §6:11: the understanding's story links are recorded once it is a
    # recorded version, before anything the pass does with the input.
    Rule(
        ControllerRule.STORY_LINKS_UNRECORDED,
        lambda f: f.story_links_wired and f.understanding_recorded and not f.story_links_decided,
        ControllerStage.STORY_LINKS,
    ),
    # ADR-0308 §2:9: recall runs again once an understanding is recorded, where it is
    # wired, as the first run is (ADR-0281 §2:3).
    Rule(
        ControllerRule.UNDERSTOOD_NOT_RECALLED,
        lambda f: f.recall_wired and f.understanding_recorded and not _phases(f).recalled_again,
        ControllerStage.RECALL,
        per=_second_run,
    ),
    # ADR-0308 §4:5: recall's outside memory records, from both runs, go into one
    # digest once the second run has decided.
    Rule(
        ControllerRule.RECALL_UNDIGESTED,
        lambda f: recall_digest_due(_phases(f)),
        ControllerStage.DIGESTING,
        per=_recall_digest,
    ),
    # ADR-0307 §8:6: planning's first round runs once understanding has recorded and
    # recall's second run has finished, its digest recorded where one is due (ADR-0308
    # §4:6), which the two rows above settle first.
    Rule(
        ControllerRule.FIRST_ROUND_DUE,
        lambda f: f.understanding_recorded and _phases(f).rounds == 0,
        ControllerStage.PLANNING,
        per=_latest_round,
    ),
    Rule(
        ControllerRule.ROUND_UNAUTHORIZED,
        lambda f: (
            (phases := _phases(f)).rounds > 0
            and (phases.latest_has_calls or phases.latest_has_text)
            and not phases.latest_authorized
        ),
        ControllerStage.AUTHORIZING,
        per=_latest_round,
    ),
    # ADR-0309 §3:3: acting, with digesting beside it where an allowed call's result
    # may carry outside text.
    Rule(
        ControllerRule.ROUND_AUTHORIZED,
        lambda f: (
            (phases := _phases(f)).latest_authorized
            and phases.latest_allows
            and not phases.latest_acted
        ),
        ControllerStage.ACTING,
        per=_latest_round,
        beside=ControllerStage.DIGESTING,
        beside_when=lambda f: _phases(f).latest_digests_due,
    ),
    # Read before `round_due`, so a round past the limit ends the pass (§3).
    Rule(
        ControllerRule.ROUND_LIMIT_REACHED,
        lambda f: _another_round_called_for(f) and _phases(f).rounds >= _phases(f).round_limit,
        ControllerStage.END,
    ),
    Rule(
        ControllerRule.ROUND_DUE,
        _another_round_called_for,
        ControllerStage.PLANNING,
        per=_latest_round,
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

    def __init__(  # noqa: PLR0913 — the stages, the clock, the rules, the two hooks and the activation its record is written for
        self,
        *,
        stages: Sequence[ControllerStageRun[P]],
        clock: Clock,
        rules: Sequence[Rule] = ACTIVATION_RULES,
        appended: Callable[[], Awaitable[None]] | None = None,
        stopped: Callable[[], bool] | None = None,
        activation_id: str | None = None,
        diagnostics: DiagnosticSink | None = None,
    ) -> None:
        """Hold the stages, the clock, the rule table and what follows each entry.

        ``appended`` is awaited once each stage's entry is appended, so the episode is
        extended as the stage ends (ADR-0286 §3). It never raises but for a
        cancellation, and the end entry is not followed by it: that entry is the
        freeze's (§4).

        ``stopped`` reads the activation's stop mark (ADR-0297 §3, §4), the one thing
        the controller reads besides the pass's state; a pass with no activation to
        stop leaves it ``None``, and is never marked.

        ``activation_id`` is the admitted activation this pass runs, which the run
        binds for every stage as the activation diagnostic entries are written for
        (ADR-0314 §5:4); ``None`` for a pass no channel admitted, which binds nothing.
        ``diagnostics`` is the sink the controller writes its step entries through
        (§4), ``None`` where the record is off.
        """
        self._stages: Mapping[ControllerStage, ControllerStageRun[P]] = {
            stage.name: stage for stage in stages
        }
        self._clock = clock
        self._rules = tuple(rules)
        self._appended = appended
        self._stopped = stopped
        self._activation_id = activation_id
        self._diagnostics = diagnostics

    def _marked(self) -> bool:
        return self._stopped is not None and self._stopped()

    def _due(self, state: P) -> Rule:
        for rule in self._rules:
            if rule.answers(state):
                return rule
        msg = "no rule answered: the table ends with one that always does (ADR-0280 §4)"
        raise RuntimeError(msg)

    def _runner(self, rule: Rule, stage: ControllerStage) -> ControllerStageRun[P]:
        """The stage ``rule`` names, which this pass must wire.

        Raises:
            RuntimeError: If the pass does not wire it.
        """
        runner = self._stages.get(stage)
        if runner is None:
            msg = f"rule {rule.name} made {stage} due, which this pass does not wire"
            raise RuntimeError(msg)
        return runner

    def _beside(self, rule: Rule, state: P) -> ControllerStage | None:
        """The stage run beside the one ``rule`` makes due, where it answers (§3:3)."""
        if rule.beside is None or (rule.beside_when is not None and not rule.beside_when(state)):
            return None
        return rule.beside

    async def _timed(self, runner: ControllerStageRun[P], state: P) -> tuple[StageResult, datetime]:
        """Run one stage and read the clock as it ends."""
        result = await runner.run(state)
        return result, self._clock()

    async def _side_by_side(
        self, state: P, main: ControllerStageRun[P], beside: ControllerStageRun[P]
    ) -> tuple[tuple[StageResult, datetime], tuple[StageResult, datetime]]:
        """Run two stages as one step, the second beside the first (ADR-0309 §3:3-§3:4).

        The step ends when both have ended. Where the first ends in anything but
        ``done``, the second is cancelled, and its result is ``failed``: it did not
        finish, and the step ends under the fixed default for the first's outcome.
        A cancellation of the step itself cancels both and propagates.
        """
        first = asyncio.ensure_future(self._timed(main, state))
        second = asyncio.ensure_future(self._timed(beside, state))
        try:
            ran = await first
            if ran[0].outcome is not StageOutcome.DONE:
                second.cancel()
            try:
                alongside = await second
            except asyncio.CancelledError:
                task = asyncio.current_task()
                if task is not None and task.cancelling():
                    raise
                alongside = (
                    StageResult(StageOutcome.FAILED, _CancelledBeside(beside.name)),
                    self._clock(),
                )
        except BaseException:
            for task in (first, second):
                task.cancel()
            await asyncio.gather(first, second, return_exceptions=True)
            raise
        return ran, alongside

    async def run(self, state: P, record: StageRecord) -> None:
        """Run the pass to its end entry.

        Ends with the rule that ended it; with ``stage_repeated`` where the first
        rule that answers names a stage this pass already ran within the rule's
        scope (the M38 loop guard, scoped per round for the phase rows, ADR-0309
        §3:5); with ``stage_failed`` or ``stage_timed_out`` where a stage did not end
        ``done``, re-raising its error — save a failure-tolerant stage's tolerated
        result while the pass's deadline has not passed, after which the rules are
        evaluated again (ADR-0281 §5); and with ``interrupted`` where the pass is
        cancelled or interrupted while the controller runs.

        **A rule that names a stage beside the one it makes due runs both as one
        step** (ADR-0309 §3:3-§3:4). Each records its own entry, due the rule, the
        first's ahead of the second's; the step ends when both have, and where the
        first did not end ``done`` the second is cancelled and the pass ends under
        the fixed default for the first.

        **A stopped pass leaves the loop** (ADR-0297 §4). The stop mark is read before
        each evaluation of the rules and again once each step's result is in hand,
        before the fixed default; where it is set, the loop is left without evaluating
        the rules, running a stage or appending an end entry, and the ``finally``
        appends ``stopped`` where it would append ``interrupted``. A stage that failed
        or timed out once the mark was set ends the pass with the stop's end entry, and
        its error is **not** re-raised: the stop was taken in first, so it is what
        ended the pass. Where that error is a programming defect it is logged, by its
        class and frames and never its message, since nothing it would have reached
        logs it now (#2927, ADR-0314 §3:2); an expected ending logs nothing. No task is
        cancelled, and a cancellation that reaches a marked pass still propagates, its
        end entry still the stop's.

        **The run binds the activation its diagnostic entries are written for**
        (ADR-0314 §5:4), around every stage, and writes one step entry for each entry it
        appends, the end entry included (§4): the rule that answered, the stage it ran,
        when the step started and ended, and how it ended. A pass that is cancelled
        writes no end entry: nothing is awaited on the way out of a cancellation.

        Raises:
            Exception: The error a stage that failed or timed out carried, on a pass
                whose stop mark was not set when its result was in hand.
        """
        with self._diagnosed():
            await self._run(state, record)

    @contextlib.contextmanager
    def _diagnosed(self) -> Iterator[None]:
        """Bind this pass's activation for its run, where one was admitted (§5:4)."""
        if self._activation_id is None:
            yield
            return
        with diagnosed_activation(self._activation_id, clock=self._clock):
            yield

    async def _stepped(self, entry: StageEntry, error: Exception | None = None) -> None:
        """Write one step entry, as the stage record holds it (ADR-0314 §4)."""

        def body() -> dict[str, object]:
            step: dict[str, object] = entry.model_dump(mode="json")
            if error is not None:
                step["failure"] = failure_body(error)
            return step

        await write_diagnostic(
            self._diagnostics, DiagnosticSource.CONTROLLER, DiagnosticKind.STEP, body
        )

    async def _ended(self, record: StageRecord) -> None:
        """Write the end entry the record just took."""
        await self._stepped(record.entries[-1])

    def _swallowed(self, ending: tuple[ControllerStage, StageResult] | None) -> None:
        """Log the error a stop kept from being re-raised, where it is a defect (#2927).

        A stopped pass does not re-raise (ADR-0297 §4), so the error reaches nothing
        that logs it. A defect is logged as the engine logs one, by its class and frames
        and never its message (ADR-0314 §3:2); an expected ending logs nothing new.
        """
        if ending is None:
            return
        stage, result = ending
        if result.error is not None and is_defect(result.error):
            log_defect(
                "stopped_stage_failed",
                result.error,
                stage=stage.value,
                activation_id=self._activation_id,
            )

    async def _run(self, state: P, record: StageRecord) -> None:  # noqa: C901, PLR0912 — §3's one step, with ADR-0297 §4's two readings of the stop mark and ADR-0309 §3:3's step of two stages in it
        ran: set[tuple[ControllerStage, object]] = set()
        cancelled = False
        try:
            while True:
                if self._marked():
                    return
                rule = self._due(state)
                stage = rule.makes_due
                if stage is ControllerStage.END:
                    record.end(rule.name, self._clock())
                    await self._ended(record)
                    return
                scope = None if rule.per is None else rule.per(state)
                beside = self._beside(rule, state)
                keys = [(stage, scope)] + ([] if beside is None else [(beside, scope)])
                if any(key in ran for key in keys):
                    record.end(ControllerRule.STAGE_REPEATED, self._clock())
                    await self._ended(record)
                    return
                runner = self._runner(rule, stage)
                alongside = None if beside is None else self._runner(rule, beside)
                ran.update(keys)
                started_at = self._clock()
                steps: list[tuple[ControllerStage, tuple[StageResult, datetime]]]
                if alongside is None:
                    steps = [(stage, await self._timed(runner, state))]
                else:
                    ran_first, ran_beside = await self._side_by_side(state, runner, alongside)
                    steps = [(stage, ran_first), (alongside.name, ran_beside)]
                for name, (result, ended_at) in steps:
                    entry = StageEntry(
                        stage=name,
                        due=rule.name,
                        started_at=started_at,
                        ended_at=ended_at,
                        outcome=result.outcome,
                        step_disposition=result.verdict.step_disposition,
                        route_outcome=result.verdict.route_outcome,
                    )
                    record.append(entry)
                    await self._stepped(entry, result.error)
                if self._appended is not None:
                    await self._appended()
                ending = _ending(state, steps)
                if self._marked():
                    self._swallowed(ending)
                    return
                if ending is None:
                    continue
                _, failed = ending
                record.end(
                    ControllerRule.STAGE_TIMED_OUT
                    if failed.outcome is StageOutcome.TIMED_OUT
                    else ControllerRule.STAGE_FAILED,
                    self._clock(),
                )
                await self._ended(record)
                assert failed.error is not None  # noqa: S101 — a stage that did not end done carries its error
                raise failed.error
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            if not record.ended:
                record.end(
                    ControllerRule.STOPPED if self._marked() else ControllerRule.INTERRUPTED,
                    self._clock(),
                )
                if not cancelled:
                    await self._ended(record)


def _ending(
    state: PassFacts, steps: Sequence[tuple[ControllerStage, tuple[StageResult, datetime]]]
) -> tuple[ControllerStage, StageResult] | None:
    """The step's first result that ends the pass under the fixed default, and its stage.

    One that did not end ``done``, save a tolerated one while the pass's deadline has
    not passed (ADR-0281 §5); ``None`` where the pass goes on.
    """
    return next(
        (
            (name, result)
            for name, (result, _) in steps
            if result.outcome is not StageOutcome.DONE
            and not (result.tolerated and not state.deadline_passed)
        ),
        None,
    )


class _CancelledBeside(Exception):  # noqa: N818 — names what happened to the stage, and is never raised
    """The stage run beside another was cancelled because the other did not end ``done``.

    Carried on that stage's ``failed`` result and never re-raised: the stage it ran
    beside ended the pass first (ADR-0309 §3:4).
    """

    def __init__(self, stage: ControllerStage) -> None:
        super().__init__(f"{stage} was cancelled: the stage it ran beside did not end done")
