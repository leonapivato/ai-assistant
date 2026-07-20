"""Shared conformance suite for the AuditTrail Protocol (ADR-0021 §4).

Every ``AuditTrail`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`AuditTrailContract` and overrides the ``trail`` fixture.

The trail is an **active participant**, not a filing cabinet: it is append-only,
it validates the resolution pointer it is handed, and it detaches what it stores
and what it returns. Each of those is a property two implementations could
plausibly disagree on while both looking correct, which is what this suite is
for.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest
from permission_builders import AT, action, decision, ruling, tool

from ai_assistant.core.errors import DuplicateDecisionError, InvalidResolutionError
from ai_assistant.core.types import (
    CostBasis,
    PermissionOutcome,
    RiskLevel,
    ToolCost,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AuditTrail
    from ai_assistant.core.types import ActionRequest, PermissionDecision


async def _resolved(
    trail: AuditTrail,
    *,
    approved: bool = True,
    **overrides: object,
) -> PermissionDecision:
    """Record a ``CONFIRM`` and return the decision that would resolve it.

    Arrangement only: the returned decision is *not* recorded, so a test can
    mutate it into the shape it wants refused. ``approved`` picks the resolving
    outcome, matching what a policy would have returned.
    """
    confirmed = decision("d-confirm")
    await trail.record(confirmed)
    answer = (
        ruling(PermissionOutcome.ALLOW, authorised_by=confirmed.id)
        if approved
        else ruling(PermissionOutcome.DENY)
    )
    fields: dict[str, object] = {
        "decision_id": "d-answer",
        "resolves": confirmed.id,
        "ruled": answer,
    }
    fields.update(overrides)
    return decision(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


class AuditTrailContract:
    """Behaviour every ``AuditTrail`` implementation must exhibit."""

    @pytest.fixture
    def trail(self) -> AuditTrail:
        """Return an empty trail under test."""
        raise NotImplementedError

    # --- append-only ------------------------------------------------------

    async def test_a_recorded_decision_is_retrievable(self, trail: AuditTrail) -> None:
        recorded = decision("d-1")

        returned = await trail.record(recorded)

        assert returned == "d-1"
        assert await trail.get("d-1") == recorded

    async def test_unknown_id_reads_as_none(self, trail: AuditTrail) -> None:
        assert await trail.get("nope") is None

    async def test_recording_a_known_id_is_refused_rather_than_upserted(
        self, trail: AuditTrail
    ) -> None:
        """Write-once, deliberately unlike ``MemoryStore.add``.

        There the id is the caller's idempotency key and an upsert is right. A
        trail that upserts is one where history can be rewritten by replaying a
        write, which is the one property the trail exists to deny.
        """
        await trail.record(decision("d-1", ruled=ruling(PermissionOutcome.CONFIRM)))

        with pytest.raises(DuplicateDecisionError):
            await trail.record(decision("d-1", ruled=ruling(PermissionOutcome.DENY)))

        stored = await trail.get("d-1")
        assert stored is not None
        assert stored.ruling.outcome is PermissionOutcome.CONFIRM

    # --- the resolution invariant ----------------------------------------

    async def test_a_matching_resolution_is_accepted(self, trail: AuditTrail) -> None:
        answer = await _resolved(trail)

        assert await trail.record(answer) == "d-answer"

    async def test_a_resolution_naming_nothing_recorded_is_refused(self, trail: AuditTrail) -> None:
        orphan = decision(
            "d-answer",
            ruled=ruling(PermissionOutcome.ALLOW, authorised_by="d-nobody"),
            resolves="d-nobody",
        )

        with pytest.raises(InvalidResolutionError):
            await trail.record(orphan)

    @pytest.mark.parametrize("outcome", [PermissionOutcome.ALLOW, PermissionOutcome.DENY])
    async def test_only_a_confirmation_can_be_resolved(
        self, trail: AuditTrail, outcome: PermissionOutcome
    ) -> None:
        """Otherwise ``resolves`` mints an authorisation for a question nobody asked."""
        await trail.record(decision("d-confirm", ruled=ruling(outcome)))
        answer = decision(
            "d-answer",
            ruled=ruling(PermissionOutcome.ALLOW, authorised_by="d-confirm"),
            resolves="d-confirm",
        )

        with pytest.raises(InvalidResolutionError):
            await trail.record(answer)

    async def test_a_confirmation_can_be_resolved_only_once(self, trail: AuditTrail) -> None:
        """Without this, a "no" could be followed by a "yes" until one stuck."""
        await trail.record(await _resolved(trail))
        second = decision(
            "d-answer-2",
            ruled=ruling(PermissionOutcome.DENY),
            resolves="d-confirm",
        )

        with pytest.raises(InvalidResolutionError):
            await trail.record(second)

    async def test_two_racing_resolutions_settle_a_confirmation_once(
        self, trail: AuditTrail
    ) -> None:
        """The single-use guarantee must survive an interleaving, not assume one caller.

        ``record`` is contracted as *atomic*: the duplicate check, the validation
        and the append are one operation. Without that, two concurrent
        resolutions each observe no prior resolution, each append, and one user
        approval has authorised two executions — the failure ADR-0014 §5 answered
        with compare-and-swap on ``PlanStore``. "The system composes on one event
        loop" is precisely the setting in which an ``await`` between a check and
        a write is an interleaving point.
        """
        first = await _resolved(trail)
        second = decision("d-answer-2", ruled=ruling(PermissionOutcome.DENY), resolves="d-confirm")

        results = await asyncio.gather(
            trail.record(first), trail.record(second), return_exceptions=True
        )

        succeeded = [result for result in results if not isinstance(result, BaseException)]
        refused = [result for result in results if isinstance(result, InvalidResolutionError)]
        assert len(succeeded) == 1, f"expected exactly one winner, got {results}"
        assert len(refused) == 1, f"the loser must be refused, got {results}"

    @pytest.mark.parametrize(
        "substituted",
        [
            action(tool=tool("other-tool")),
            action(tool=tool(risk_level=RiskLevel.CRITICAL)),
            action(parameters={"to": "someone-else@example.com"}),
            action(step_id="step-2"),
        ],
        ids=["a different tool", "a tampered definition", "different arguments", "another step"],
    )
    async def test_a_resolution_must_answer_the_question_that_was_asked(
        self, trail: AuditTrail, substituted: ActionRequest
    ) -> None:
        """A bare pointer would be worse than none.

        It would let an ``ALLOW`` for tool B claim to be the user's answer to a
        ``CONFIRM`` shown for tool A — the substitution the embedded definition
        closes, reintroduced through the one path where a human was actually
        consulted. The subject is compared on tool, payload digest *and* step.
        """
        answer = await _resolved(trail, request=substituted)

        with pytest.raises(InvalidResolutionError):
            await trail.record(answer)

    async def test_a_resolution_may_not_predate_its_confirmation(self, trail: AuditTrail) -> None:
        """An answer timestamped before its question is chronologically false.

        Nothing else in the invariant notices, and ``recent()`` would present
        them in that order — an audit record that is internally consistent and
        wrong, which is worse than one that is obviously broken.
        """
        answer = await _resolved(trail, decided_at=AT - timedelta(seconds=1))

        with pytest.raises(InvalidResolutionError):
            await trail.record(answer)

    async def test_a_resolution_at_the_same_instant_is_accepted(self, trail: AuditTrail) -> None:
        """A fast confirmation at a coarse clock resolution is real.

        Refusing equal timestamps would reject correct behaviour to catch
        nothing.
        """
        answer = await _resolved(trail, decided_at=AT)

        assert await trail.record(answer) == "d-answer"

    async def test_a_resolving_allow_must_cite_the_confirmation_it_resolves(
        self, trail: AuditTrail
    ) -> None:
        """The check that makes "verified end to end" true rather than aspirational.

        Without it a resolving ``ALLOW`` could name any confirmation it liked —
        or nothing at all — while satisfying every other check, and the
        disclosure floor would be satisfiable by fabrication after all.

        (A resolving ``DENY`` carrying an authorisation is the other half of the
        rule; ``PermissionRuling`` already makes it unrepresentable, so it cannot
        be arranged here without constructing an invalid model.)
        """
        unbacked = await _resolved(trail, ruled=ruling(PermissionOutcome.ALLOW))

        with pytest.raises(InvalidResolutionError):
            await trail.record(unbacked)

    # --- ordering and bounds ---------------------------------------------

    async def test_recent_is_newest_first_with_an_id_tie_break(self, trail: AuditTrail) -> None:
        """Both halves are needed for two stores to answer the same query alike.

        "Newest first" is ambiguous between insertion order and decision time,
        which disagree whenever records are appended out of order — so these are
        recorded in a deliberately different order than they were decided. The
        ``id`` tie-break makes the order *total*, since two decisions can share
        a timestamp at any clock resolution.
        """
        await trail.record(decision("d-old", decided_at=AT - timedelta(hours=1)))
        await trail.record(decision("d-new", decided_at=AT + timedelta(hours=1)))
        await trail.record(decision("d-tie-b", decided_at=AT))
        await trail.record(decision("d-tie-a", decided_at=AT))

        found = await trail.recent()

        assert [each.id for each in found] == ["d-new", "d-tie-a", "d-tie-b", "d-old"]

    async def test_ordering_and_chronology_survive_a_dst_repeated_hour(
        self, trail: AuditTrail
    ) -> None:
        """Ordering is by *instant*, which wall-clock ordering is not.

        During a DST repeated hour, ``01:15 fold=1`` (EST) is a later instant
        than ``01:45 fold=0`` (EDT) — and Python compares two aware datetimes
        sharing a ``tzinfo`` by their naive values, ignoring ``fold``, so a
        store that kept them as given would sort the pair backwards and accept
        an answer that genuinely predates its question. ``PermissionDecision``
        normalises to UTC so this holds for every implementation, and this test
        is what stops one that re-parses a persisted offset from losing it
        again.
        """
        ny = ZoneInfo("America/New_York")
        earlier = datetime(2026, 11, 1, 1, 45, tzinfo=ny, fold=0)
        later = datetime(2026, 11, 1, 1, 15, tzinfo=ny, fold=1)

        await trail.record(decision("d-earlier", decided_at=earlier))
        await trail.record(decision("d-later", decided_at=later))

        assert [each.id for each in await trail.recent()] == ["d-later", "d-earlier"]

        answer = decision(
            "d-answer",
            ruled=ruling(PermissionOutcome.ALLOW, authorised_by="d-later"),
            resolves="d-later",
            decided_at=earlier,
        )
        with pytest.raises(InvalidResolutionError):
            await trail.record(answer)

    async def test_recent_returns_the_newest_within_the_limit(self, trail: AuditTrail) -> None:
        for index in range(5):
            await trail.record(decision(f"d-{index}", decided_at=AT + timedelta(minutes=index)))

        found = await trail.recent(limit=2)

        assert [each.id for each in found] == ["d-4", "d-3"]

    @pytest.mark.parametrize("limit", [0, -1])
    async def test_a_non_positive_limit_is_refused(self, trail: AuditTrail, limit: int) -> None:
        """Refused rather than clamped or passed through, because the natural leak is silent.

        A store issuing ``LIMIT ?`` against SQLite turns ``limit=-1`` into *no
        limit at all*, so the one call offering a bounded read of a Tier 1 store
        becomes the unbounded read it exists to avoid. Clamping is the other
        wrong answer: a caller that asked for something meaningless should learn
        that, not be served something it did not ask for.
        """
        await trail.record(decision("d-1"))

        with pytest.raises(ValueError, match="limit"):
            await trail.recent(limit=limit)

    async def test_an_empty_trail_answers_emptily(self, trail: AuditTrail) -> None:
        assert await trail.recent() == []
        assert await trail.export() == []
        assert await trail.get("d-1") is None

    # --- export and erasure ----------------------------------------------

    async def test_export_returns_every_decision(self, trail: AuditTrail) -> None:
        await trail.record(decision("d-1"))
        await trail.record(decision("d-2", decided_at=AT + timedelta(hours=1)))

        exported = await trail.export()

        assert {each.id for each in exported} == {"d-1", "d-2"}

    async def test_an_exported_decision_survives_a_json_round_trip(self, trail: AuditTrail) -> None:
        """Durability is what forces these records to be serialisable.

        A decision that could not be reloaded would make the embedded definition
        worthless across exactly the restart issue #54 is about — so the
        round-trip is a property of the design, not a hope.
        """
        priced = tool(
            cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.002"), currency="USD")
        )
        original = decision("d-1", request=action(tool=priced, parameters={"to": "a@example.com"}))
        await trail.record(original)

        exported = (await trail.export())[0]
        reloaded = type(original).model_validate(exported.model_dump(mode="json"))

        assert reloaded == original

    async def test_clear_erases_everything_and_reports_how_much(self, trail: AuditTrail) -> None:
        """The user may burn the book; there is deliberately no way to tear out a page."""
        await trail.record(decision("d-1"))
        await trail.record(decision("d-2", decided_at=AT + timedelta(hours=1)))

        removed = await trail.clear()

        assert removed == 2
        assert await trail.recent() == []
        assert await trail.get("d-1") is None

    # --- the trail owns what it holds ------------------------------------

    async def test_the_stored_snapshot_is_detached_from_the_caller(self, trail: AuditTrail) -> None:
        """The write-path half of ADR-0018 §4's rule.

        A store retaining the caller's object would let
        ``decision.__dict__["ruling"] = ...`` rewrite an appended entry after the
        fact, through a store whose entire premise is that entries are not
        rewritten. Detachment on queries alone closes the door and leaves the
        window open.
        """
        held = decision("d-1", ruled=ruling(PermissionOutcome.DENY))
        await trail.record(held)

        object.__setattr__(held.tool, "risk_level", RiskLevel.CRITICAL)
        object.__setattr__(held, "parameters_digest", "rewritten")

        stored = await trail.get("d-1")
        assert stored is not None
        assert stored.tool.risk_level is RiskLevel.LOW
        assert stored.parameters_digest != "rewritten"

    async def test_a_returned_list_is_a_detached_snapshot(self, trail: AuditTrail) -> None:
        """``recent`` and ``export`` return ``list``, and a list is mutable."""
        await trail.record(decision("d-1"))

        (await trail.recent()).clear()
        (await trail.export()).clear()

        assert [each.id for each in await trail.recent()] == ["d-1"]

    @pytest.mark.parametrize("query", ["get", "recent", "export"])
    async def test_detachment_reaches_nested_values(self, trail: AuditTrail, query: str) -> None:
        """Recursive, not top-level (ADR-0018 §3).

        A ``PermissionDecision`` reaches a ``ToolDefinition`` which reaches a
        ``ToolCost``, so a shallow copy hands back a new decision sharing the
        stored cost — and ``result.tool.cost.__dict__["amount"] = 0`` would then
        rewrite the record of what was approved through something technically
        detached.
        """
        priced = tool(cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("5"), currency="USD"))
        await trail.record(decision("d-1", request=action(tool=priced)))

        async def fetch() -> PermissionDecision:
            if query == "get":
                one = await trail.get("d-1")
                assert one is not None
                return one
            if query == "recent":
                return (await trail.recent())[0]
            return (await trail.export())[0]

        leaked = await fetch()
        object.__setattr__(leaked.tool.cost, "amount", Decimal("0"))
        object.__setattr__(leaked.ruling, "outcome", PermissionOutcome.ALLOW)

        refetched = await fetch()
        assert refetched.tool.cost.amount == Decimal("5")
        assert refetched.ruling.outcome is PermissionOutcome.CONFIRM
