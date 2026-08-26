"""The startup recovery scan: resolve steps a dead process left ``RUNNING``.

ADR-0014 §4 gives the scan its occasion and its outcome — it "scans
``active_executions()`` at startup, which presumes no executor is live for those
states", and a step still ``RUNNING`` there becomes ``INDETERMINATE``, the durable
ignorance that is never auto-retried. ADR-0192 §3 gives it a second act on the
same occasion: the trail now holds a row per invocation, and a process that died
mid-call left a **claim** open under the decision that step's ``approval_ref``
names. The scan completes every such claim ``INDETERMINATE`` and only then
commits the step out of ``RUNNING``.

**Two collaborators over one store, and the narrow one is a type rather than a
promise** (ADR-0192 §9, ADR-0029 §1). The scan reads open claims through
:class:`~ai_assistant.core.protocols.AuditTrail` — the trail ``orchestration``
already holds (ADR-0044 §3) — and writes each completion through
:class:`~ai_assistant.core.protocols.InvocationCompleter`. It is handed **no**
:class:`~ai_assistant.core.protocols.InvocationLedger`: ``claim_invocation`` is
the seam's act, and a dependency that cannot express the call is what makes "the
scan never claims" checkable instead of trusted.

**It mints no reachability fact, and #234 stays narrowed rather than closed**
(ADR-0192 §3, §9). The scan asks how far no call got: it completes **every** claim
open under the decision, because the record cannot tell one attempt's state from
another's and a `ToolInvocation` names no step. What ADR-0192 gives #234 is that
the *store* now distinguishes a cancellation before the claim from one after it;
what #234 still owns is the executor's `interrupted_outcome` classification, which
reads a declaration and not this store. Nothing here infers either from the other.

Nothing here reads an invocation row to decide a step's outcome, and nothing
reads a step to decide a row's. ADR-0192 §3 states the two records answer two
questions and are **not required to agree**, in both directions; ADR-0014 §4's
transition graph is untouched (ADR-0192 §10).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from ai_assistant.core.errors import InvalidCompletionError
from ai_assistant.core.types import (
    CostBasis,
    StepFailure,
    StepStatus,
    StepTransition,
    ToolCost,
    ToolOutcome,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AuditTrail, InvocationCompleter, PlanStore
    from ai_assistant.core.types import ExecutionState

_log = structlog.get_logger(__name__)

#: What the scan records on a step it found ``RUNNING`` with nothing executing it.
#: Authored here rather than borrowed from ``planning``'s own constant because the
#: transition travels as a :class:`~ai_assistant.core.types.StepTransition` through
#: the store's only write path, and ``kind`` is ``None`` for the reason ADR-0039 §7
#: gives: recovery has no ``ToolResult`` and never had one, so a classification here
#: would be fabricated.
_ABANDONED = (
    "the step was found running with nothing executing it, so whether the tool acted is unknown"
)

#: What a recovery completion costs, on every row the scan appends (ADR-0192 §5).
#: ``UNKNOWN`` and never a figure, and never ``ToolDefinition.cost``: the scan
#: derives its rows from no ``ToolResult`` at all, so there is no measurement to
#: carry, and a declaration copied into the field would put a number nobody
#: measured into the total §5 is built on.
_UNMEASURED = ToolCost(basis=CostBasis.UNKNOWN)


class RecoveryScan:
    """Complete what a dead process left open, then resolve the steps it left running.

    Built by the composition root with one object behind all three parameters'
    faces — the plan store, and the audit store as both trail and completer
    (ADR-0192 §9). Driven once per start from
    :meth:`~ai_assistant.orchestration.engine.Engine.start`, which is where
    ADR-0014 §4's "at startup" lands in this system.

    **Re-runnable, with no marker, generation or resume point** (ADR-0192 §3). The
    ordering is the whole of the crash protocol: a crash partway through leaves the
    step ``RUNNING``, so the next scan finds the same step and completes whatever is
    still open, and a claim already completed is no longer *open*, so no rerun ever
    attempts a second completion of one. A crash after the last completion and
    before the transition costs one scan that appends nothing.
    """

    def __init__(
        self,
        *,
        plans: PlanStore,
        trail: AuditTrail,
        completer: InvocationCompleter,
    ) -> None:
        """Wire the scan from injected contracts.

        Args:
            plans: Durable planning state — the same instance the executor commits
                through, so the steps this resolves are the ones a restarted system
                would otherwise leave ``RUNNING`` for good.
            trail: The audit trail, read **query-only** here and for one query:
                :meth:`~ai_assistant.core.protocols.AuditTrail.open_invocations`.
                ADR-0192 §2 makes this scan its only consumer.
            completer: The narrow invocation face over that **same** store. Two
                stores here would complete claims nobody appended while leaving the
                real ones open, which is why ADR-0192 §9 makes the single-instance
                wiring a composition-root obligation.
        """
        self._plans = plans
        self._trail = trail
        self._completer = completer

    async def recover(self) -> None:
        """Resolve every step a previous process left ``RUNNING``.

        Enumerates ``active_executions()`` — ADR-0014 §4's own query, whose
        precondition is that no executor is live for those states — and, for each
        ``RUNNING`` step, completes the open claims under its ``approval_ref``
        before committing its transition to ``INDETERMINATE``.

        Raises:
            AuditError: If the trail cannot be read, or a completion is refused for
                any reason other than the claim having been erased under the scan.
                A store that cannot record what happened is a startup fault, not
                something to press on past.
            PlanningError: If the store cannot be read, or rejects a transition.
        """
        for state in await self._plans.active_executions():
            await self._recover_execution(state)

    async def _recover_execution(self, state: ExecutionState) -> None:
        """Resolve each ``RUNNING`` step of one execution, one transition at a time.

        Re-derives the next ``RUNNING`` step from the state
        :meth:`~ai_assistant.core.protocols.PlanStore.commit_transition` returned
        rather than iterating the snapshot ``active_executions`` handed back: the
        store's write is compare-and-swap on ``expected_version``, and every commit
        moves the version on, so a second transition computed against the stale
        snapshot would be refused ``StaleExecutionError``.
        """
        while True:
            running = next(
                (step for step in state.steps if step.status is StepStatus.RUNNING), None
            )
            if running is None:
                return
            await self._complete_open_claims(running.approval_ref)
            state = await self._plans.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id=running.step_id,
                    to_status=StepStatus.INDETERMINATE,
                    expected_version=state.version,
                    failure=StepFailure(kind=None, message=_ABANDONED),
                )
            )

    async def _complete_open_claims(self, decision_id: str | None) -> None:
        """Complete every claim open under ``decision_id``, until none is (ADR-0192 §3).

        **Completions first, transition second, and never the other way.**
        Committing the transition first loses every claim still open at that
        moment, permanently: the step stops being ``RUNNING``, no later scan
        returns for it, and nothing else knows to look, because a
        :class:`~ai_assistant.core.types.ToolInvocation` names no step and is
        reachable from that step's ``approval_ref`` and from nowhere else.

        **Every** open claim and not one selected among them. A decision may carry
        more than one — a non-spendable authorisation admits concurrent invocations
        — and a scan holding only ``approval_ref`` cannot tell one attempt from
        another. Completing all of them is the only unambiguous act, and it is the
        true one: the process died with each of them in flight.

        **The read is a loop rather than a single pass**, because "no claim under
        that decision is still open" is read against the store at the moment of the
        transition and never against a list enumerated earlier — a scan
        transitioning from a stale enumeration would also transition over a claim
        opened between the two reads. Each pass leaves every claim it saw
        not-open — completed, or refused because it no longer exists — so the loop
        ends after one further read unless something appended a claim in between,
        which ADR-0014 §4's precondition excludes. ADR-0192 §3 states the residual
        window rather than closing it: no gate spanning two stores is available to
        ``orchestration`` under golden rule 1, and none is minted here.

        An ``approval_ref`` of ``None`` names no decision to ask about, so there is
        nothing to complete. ADR-0014 §4 rejects a ``→ RUNNING`` transition without
        one, so this is unreachable through the tracker rather than a case with its
        own behaviour.
        """
        if decision_id is None:
            return
        while claims := await self._trail.open_invocations(decision_id=decision_id):
            for claim in claims:
                try:
                    await self._completer.complete_invocation(
                        claim_id=claim.id,
                        outcome=ToolOutcome.INDETERMINATE,
                        # `None`, and never synthesised: ADR-0192 §2's transcription
                        # rule takes a kind from the `ToolResult` that carried one,
                        # and there was no result here to transcribe from.
                        failure_kind=None,
                        incurred_cost=_UNMEASURED,
                    )
                except InvalidCompletionError:
                    # `clear()` landed between the enumeration and this completion,
                    # so the claim it named no longer exists (ADR-0192 §3, §6). That
                    # is neither a fault to repair nor a reason to abandon the
                    # transition, and nothing is recreated: the user destroyed the
                    # row on purpose, and a store putting one back is the one answer
                    # §6 says no store may give. The loop re-reads and proceeds.
                    _log.info("recovery_completion_refused")
