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

from ai_assistant.core.errors import (
    AuditError,
    DuplicateDecisionError,
    InvalidResolutionError,
)
from ai_assistant.core.types import (
    CostBasis,
    PermissionDecision,
    PermissionOutcome,
    RiskLevel,
    ToolCost,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AuditTrail
    from ai_assistant.core.types import ActionRequest


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


async def _refuses(
    trail: AuditTrail,
    rejected: PermissionDecision,
    error: type[AuditError] = InvalidResolutionError,
) -> None:
    """Assert ``record`` refuses ``rejected`` **and writes nothing**.

    ADR-0021 §4 makes ``record`` atomic — the duplicate-id check, the resolution
    validation and the append are one operation — so a refusal is not a partial
    write with an exception on top. Asserting only that it raised would accept a
    store that appended an orphan or a mismatched resolution and *then* rejected
    it, leaving the trail holding a record the contract says is unrecordable and
    the confirmation it named spent.

    The whole trail is compared rather than just the rejected id, because a
    write that landed under a different id, or that mutated the referenced
    ``CONFIRM`` on its way through, is the same failure wearing a disguise.
    """
    before = await trail.export()

    with pytest.raises(error):
        await trail.record(rejected)

    assert await trail.export() == before, "a refused write must leave no trace"


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

        await _refuses(
            trail, decision("d-1", ruled=ruling(PermissionOutcome.DENY)), DuplicateDecisionError
        )

        stored = await trail.get("d-1")
        assert stored is not None
        assert stored.ruling.outcome is PermissionOutcome.CONFIRM

    async def test_two_racing_writes_of_one_id_settle_it_once(self, trail: AuditTrail) -> None:
        """Write-once must survive an interleaving, like the resolution check.

        ADR-0021 §4 makes the duplicate-id check, the resolution validation and
        the append *one* operation. Racing two resolutions covers the second
        half; without this the first half is untested, and a store that awaited
        between "is this id taken?" and the append would let two writers both
        observe a free id and both append — history rewritten by a replayed
        write, which is the property the trail exists to deny.
        """
        results = await asyncio.gather(
            trail.record(decision("d-1", ruled=ruling(PermissionOutcome.CONFIRM))),
            trail.record(decision("d-1", ruled=ruling(PermissionOutcome.DENY))),
            return_exceptions=True,
        )

        succeeded = [result for result in results if not isinstance(result, BaseException)]
        refused = [result for result in results if isinstance(result, DuplicateDecisionError)]
        assert len(succeeded) == 1, f"expected exactly one winner, got {results}"
        assert len(refused) == 1, f"the loser must be refused, got {results}"
        assert len(await trail.export()) == 1

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

        await _refuses(trail, orphan)

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

        await _refuses(trail, answer)

    async def test_a_confirmation_can_be_resolved_only_once(self, trail: AuditTrail) -> None:
        """Without this, a "no" could be followed by a "yes" until one stuck."""
        await trail.record(await _resolved(trail))
        second = decision(
            "d-answer-2",
            ruled=ruling(PermissionOutcome.DENY),
            resolves="d-confirm",
        )

        await _refuses(trail, second)

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

        await _refuses(trail, answer)

    async def test_a_resolution_may_not_predate_its_confirmation(self, trail: AuditTrail) -> None:
        """An answer timestamped before its question is chronologically false.

        Nothing else in the invariant notices, and ``recent()`` would present
        them in that order — an audit record that is internally consistent and
        wrong, which is worse than one that is obviously broken.
        """
        answer = await _resolved(trail, decided_at=AT - timedelta(seconds=1))

        await _refuses(trail, answer)

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

        await _refuses(trail, unbacked)

    # --- the execution binding (ADR-0044 §2) -----------------------------

    async def test_a_resolution_must_share_the_confirmations_execution(
        self, trail: AuditTrail
    ) -> None:
        """ADR-0044 §2a: B's answer may not resolve A's confirmation.

        Two executions of one plan, both parked on the same step, produce two
        CONFIRMs identical in tool, digest and step but differing in
        ``execution_id``. Without the added conjunct a resolution built for B
        could name A's confirmation and pass every earlier check — the
        cross-execution substitutability #253 closes at the resolution seam.
        """
        await trail.record(decision("c-a", request=action(execution_id="exec-a")))
        answer_for_b = decision(
            "r-b",
            request=action(execution_id="exec-b"),
            ruled=ruling(PermissionOutcome.ALLOW, authorised_by="c-a"),
            resolves="c-a",
        )

        await _refuses(trail, answer_for_b)

    async def test_a_concrete_binding_carries_at_most_one_resolution(
        self, trail: AuditTrail
    ) -> None:
        """ADR-0044 §2b: one step of one execution has one answer, across siblings.

        ADR-0037 §2 leaves a second unresolved CONFIRM under one binding (a
        compare-and-swap loser), and the two are the same action. The
        per-*confirmation* rule alone would let the sibling be answered the other
        way while the first stood — the #257 window. This is the per-*binding*
        rule layered on top: once the binding is decided, no sibling may be
        resolved. The refused answer names a *different* CONFIRM, so only the
        binding rule — not the ``resolves`` index — can catch it.
        """
        bind = {"execution_id": "exec-a"}  # step_id defaults to "step-1": a concrete binding
        await trail.record(decision("c-1", request=action(**bind)))
        await trail.record(decision("c-2", request=action(**bind)))
        await trail.record(
            decision(
                "r-1",
                request=action(**bind),
                ruled=ruling(PermissionOutcome.ALLOW, authorised_by="c-1"),
                resolves="c-1",
            )
        )

        sibling_answer = decision(
            "r-2",
            request=action(**bind),
            ruled=ruling(PermissionOutcome.DENY),
            resolves="c-2",
        )
        await _refuses(trail, sibling_answer)

    async def test_direct_confirmations_are_not_coupled_by_a_binding(
        self, trail: AuditTrail
    ) -> None:
        """§2b fires only for a *concrete* binding (ADR-0044 §2b).

        Two direct confirmations — no execution, no step — share the ``(None,
        None)`` non-binding, so resolving one must not decide the other. Only the
        per-confirmation rule applies, and it keeps them independent.
        """
        direct: dict[str, object] = {"step_id": None, "execution_id": None}
        await trail.record(decision("c-1", request=action(**direct)))
        await trail.record(decision("c-2", request=action(**direct)))
        await trail.record(
            decision(
                "r-1",
                request=action(**direct),
                ruled=ruling(PermissionOutcome.ALLOW, authorised_by="c-1"),
                resolves="c-1",
            )
        )

        answer_for_the_other = decision(
            "r-2",
            request=action(**direct),
            ruled=ruling(PermissionOutcome.ALLOW, authorised_by="c-2"),
            resolves="c-2",
        )
        assert await trail.record(answer_for_the_other) == "r-2"

    # --- recovering a parked confirmation (ADR-0044 §3) ------------------

    async def test_pending_confirmation_returns_the_unresolved_confirm(
        self, trail: AuditTrail
    ) -> None:
        """The recovery query: a restart finds the parked question by its binding."""
        confirmed = decision("c-1", request=action(execution_id="exec-a"))
        await trail.record(confirmed)

        found = await trail.pending_confirmation(execution_id="exec-a", step_id="step-1")

        assert found == confirmed

    async def test_pending_confirmation_is_none_for_an_unparked_binding(
        self, trail: AuditTrail
    ) -> None:
        assert await trail.pending_confirmation(execution_id="exec-a", step_id="step-1") is None

    async def test_pending_confirmation_is_none_once_the_binding_is_resolved(
        self, trail: AuditTrail
    ) -> None:
        """A resolved binding is decided, so nothing is awaiting an answer."""
        bind = {"execution_id": "exec-a"}
        await trail.record(decision("c-1", request=action(**bind)))
        await trail.record(
            decision(
                "r-1",
                request=action(**bind),
                ruled=ruling(PermissionOutcome.ALLOW, authorised_by="c-1"),
                resolves="c-1",
            )
        )

        assert await trail.pending_confirmation(execution_id="exec-a", step_id="step-1") is None

    async def test_pending_confirmation_returns_the_newest_of_several_unresolved(
        self, trail: AuditTrail
    ) -> None:
        """ADR-0037 §2's CAS loser leaves a second unresolved CONFIRM under the binding.

        They are the same action (selection is deterministic and single-candidate,
        ADR-0037 §1), so any is a correct question to re-present and the newest is
        returned deterministically — ``decided_at`` descending, ``id`` ascending.
        The query does not raise on the several.
        """
        bind = {"execution_id": "exec-a"}
        await trail.record(decision("c-old", request=action(**bind), decided_at=AT))
        await trail.record(
            decision("c-new", request=action(**bind), decided_at=AT + timedelta(hours=1))
        )

        found = await trail.pending_confirmation(execution_id="exec-a", step_id="step-1")

        assert found is not None
        assert found.id == "c-new"

    async def test_pending_confirmation_is_none_when_a_sibling_is_resolved(
        self, trail: AuditTrail
    ) -> None:
        """ADR-0044 §3 step 1 — the #257 safety, the blocker an earlier draft failed.

        Once *any* CONFIRM for the binding is resolved the binding is decided, so
        the query returns ``None`` rather than handing back a still-unresolved
        sibling orphan for the pipeline to re-answer the other way.
        """
        bind = {"execution_id": "exec-a"}
        await trail.record(decision("c-1", request=action(**bind)))
        await trail.record(decision("c-2", request=action(**bind)))  # the unresolved sibling
        await trail.record(
            decision(
                "r-1",
                request=action(**bind),
                ruled=ruling(PermissionOutcome.DENY),
                resolves="c-1",
            )
        )

        assert await trail.pending_confirmation(execution_id="exec-a", step_id="step-1") is None

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
        await _refuses(trail, answer)

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

    @pytest.mark.parametrize(
        ("attribute", "value"),
        [
            pytest.param("decided_at", datetime(2026, 7, 20, 12, 0), id="naive-timestamp"),  # noqa: DTZ001
            pytest.param("parameters_digest", "not-a-digest", id="malformed-digest"),
            pytest.param("id", "", id="blank-identifier"),
        ],
    )
    async def test_a_corrupted_decision_is_refused_rather_than_stored(
        self, trail: AuditTrail, attribute: str, value: object
    ) -> None:
        """ADR-0021 §4 asks for a *validated* snapshot, not merely a detached one.

        Detachment alone copies without checking, so an implementation that only
        deep-copies conforms to every other clause here and still accepts a
        decision corrupted past its frozen model's guard. The sharp case is a
        naive ``decided_at``: ``recent`` sorts on that field, so every later read
        would raise on comparing it against the aware values beside it — a store
        that can be put into a state where reads crash has stopped being
        readable, which is worse than refusing the write.

        Held here rather than only on the fake because it is exactly the clause
        two implementations would plausibly disagree on: nothing about a
        deep-copying store *looks* wrong until a corrupted record is in it.
        """
        await trail.record(decision("d-1"))
        corrupted = decision("d-2")
        object.__setattr__(corrupted, attribute, value)

        with pytest.raises(AuditError):
            await trail.record(corrupted)

        assert await trail.get("d-2") is None
        assert [held.id for held in await trail.export()] == ["d-1"]

    async def test_a_decision_corrupted_below_its_own_fields_is_refused(
        self, trail: AuditTrail
    ) -> None:
        """The check has to reach the nested models, not just the top level.

        A revalidation that rebuilt only the decision's own fields would accept
        an embedded ``ToolDefinition`` whose ``description`` renders as nothing —
        the visible-text rule ADR-0018 §1 imposes precisely because the trail is
        read by a human deciding what was approved — and the record would then
        say a tool was permitted without being able to say which.
        """
        corrupted = decision("d-2", ruled=ruling(PermissionOutcome.DENY))
        object.__setattr__(corrupted.tool, "description", "   ")

        with pytest.raises(AuditError):
            await trail.record(corrupted)

        assert await trail.get("d-2") is None
        assert await trail.export() == []

    async def test_detachment_survives_a_caller_supplied_subclass(self, trail: AuditTrail) -> None:
        """A caller's subclass may not become the object the trail hands back.

        ``PermissionDecision`` is a plain model, so a caller can subclass it and
        override ``model_copy`` to return ``self``. A store that snapshotted
        through ``type(decision)`` would then hold that instance and return it
        from every read, so the detachment above would stop holding without any
        of its own assertions changing — the caller keeps a live handle on an
        append-only record.

        The obligation is therefore on the *declared* type: what the trail stores
        and returns is a ``PermissionDecision``, whatever it was handed.
        """

        class _Sticky(PermissionDecision):
            def model_copy(self, **kwargs: object) -> _Sticky:
                return self

        original = decision("d-1")
        sticky = _Sticky.model_construct(**dict(original))
        await trail.record(sticky)

        stored = await trail.get("d-1")
        assert stored is not None
        object.__setattr__(stored, "parameters_digest", "rewritten")

        reread = await trail.get("d-1")
        assert reread is not None
        assert reread.parameters_digest == original.parameters_digest

    async def test_the_stored_snapshot_is_detached_from_the_caller(self, trail: AuditTrail) -> None:
        """The write-path half of ADR-0018 §4's rule.

        A store retaining the caller's object would let
        ``decision.__dict__["ruling"] = ...`` rewrite an appended entry after the
        fact, through a store whose entire premise is that entries are not
        rewritten. Detachment on queries alone closes the door and leaves the
        window open.

        Recursive, like the read path: every reachable level is rewritten here —
        the decision's own field, the embedded ``ToolDefinition``, the
        ``ToolCost`` nested inside that, and the ``PermissionRuling``. A store
        that copied the decision and the tool but kept the caller's ruling would
        otherwise pass while leaving the recorded *outcome* editable, which is
        the one field the trail exists to fix.
        """
        priced = tool(cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("5"), currency="USD"))
        held = decision("d-1", request=action(tool=priced), ruled=ruling(PermissionOutcome.DENY))
        await trail.record(held)

        object.__setattr__(held, "parameters_digest", "rewritten")
        object.__setattr__(held.tool, "risk_level", RiskLevel.CRITICAL)
        object.__setattr__(held.tool.cost, "amount", Decimal("0"))
        object.__setattr__(held.ruling, "outcome", PermissionOutcome.ALLOW)

        stored = await trail.get("d-1")
        assert stored is not None
        assert stored.parameters_digest != "rewritten"
        assert stored.tool.risk_level is RiskLevel.LOW
        assert stored.tool.cost.amount == Decimal("5")
        assert stored.ruling.outcome is PermissionOutcome.DENY

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
