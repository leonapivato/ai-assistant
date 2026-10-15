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
from typing import TYPE_CHECKING, Any, Protocol
from zoneinfo import ZoneInfo

import pytest
from permission_builders import AT, action, decision, ruling, tool
from recipient_builders import (
    ALICE,
    FORECAST_TOOL,
    SEARCH_ACCOUNT,
    SEARCH_TOOL,
    TOOL,
    binding,
    forecast_binding,
    origin_unrecorded,
    route_b_decision,
    route_c_decision,
    search_binding,
)

from ai_assistant.core.errors import (
    AuditError,
    DuplicateDecisionError,
    InvalidAuthorisationError,
    InvalidResolutionError,
)
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    Approval,
    ApprovalEnd,
    ApprovalGiven,
    ApprovalGiver,
    BoundAccount,
    CostBasis,
    CoverageUnrecordedBinding,
    EgressBinding,
    Idempotency,
    OriginUnrecordedBinding,
    PermissionDecision,
    PermissionOutcome,
    QuestionPart,
    RiskLevel,
    SpanCoverage,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
    YesToQuestion,
)
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.core.protocols import AuditTrail
    from ai_assistant.core.types import ActionRequest
    from ai_assistant.testing.cancellation import SuspendedMidWrite


#: What a failure of the cancellation case below means, in one place: every
#: assertion in it is the same invariant seen from a different side.
_RELEASED_EARLY = (
    "the cancelled call released its resource while its own work was still "
    "running, so a second caller reached it concurrently"
)


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


class _CancellationOp(Protocol):
    """One locked ``AuditTrail`` operation the ADR-0060 case drives (#370, #397).

    Each :attr:`name` selects a distinct ``async with self._lock:
    _run_to_completion(...)`` site; the suite runs the same
    cancelled-first / concurrent-second scenario against every one, so a
    regression reintroduced at any single site is caught rather than only at
    ``record``. :meth:`first` and :meth:`second` act on *independent* subjects, so
    the concurrent second succeeds whatever the cancelled first's indeterminate
    effect turns out to be.

    **Reads are operations too** (#397). ADR-0060 §3 binds any method that acquires
    the resource, and every locked read here holds the connection lock around its
    own worker-thread SQL — so a regression replacing one read's
    ``_run_to_completion`` with a bare ``to_thread`` would hand the connection to a
    concurrent caller while that read's worker still used it, and every write case
    would still pass.
    """

    name: str

    async def prepare(self, trail: AuditTrail) -> None:
        """Establish anything the operation needs before it can run."""
        ...

    def first(self, trail: AuditTrail) -> Coroutine[Any, Any, object]:
        """The call the case suspends inside the resource and then cancels."""
        ...

    def second(self, trail: AuditTrail) -> Coroutine[Any, Any, object]:
        """The concurrent call barred from the resource until the first is done."""
        ...

    async def verify(self, trail: AuditTrail) -> None:
        """Assert the resource survived: the second call is whole and reads work."""
        ...


class _RecordOp:
    """The append-only ``record`` path — ADR-0060's original subject."""

    name = "record"

    async def prepare(self, trail: AuditTrail) -> None:
        """No preconditions."""

    def first(self, trail: AuditTrail) -> Coroutine[Any, Any, object]:
        """Record the decision whose write is cancelled."""
        return trail.record(decision("cancel-1"))

    def second(self, trail: AuditTrail) -> Coroutine[Any, Any, object]:
        """Record an independent decision concurrently."""
        return trail.record(decision("cancel-2"))

    async def verify(self, trail: AuditTrail) -> None:
        """The second entry is durable; the first is absent-or-whole; reads work."""
        assert await trail.get("cancel-2") == decision("cancel-2")
        cancelled = await trail.get("cancel-1")
        assert cancelled is None or cancelled == decision("cancel-1")
        assert {entry.id for entry in await trail.export()} >= {"cancel-2"}


class _ClearOp:
    """The ``clear`` write, with a recorded entry so it does real work."""

    name = "clear"

    async def prepare(self, trail: AuditTrail) -> None:
        """A recorded decision for ``clear`` to remove."""
        await trail.record(decision("seed"))

    def first(self, trail: AuditTrail) -> Coroutine[Any, Any, object]:
        """Clear the trail — the call that is cancelled."""
        return trail.clear()

    def second(self, trail: AuditTrail) -> Coroutine[Any, Any, object]:
        """Clear again concurrently."""
        return trail.clear()

    async def verify(self, trail: AuditTrail) -> None:
        """The trail is empty and still serves reads."""
        assert await trail.export() == []


#: The two requests every read op below is seeded with and answers from, told apart
#: by their arguments.
_EXEC_A = "read-a@example.com"
_EXEC_B = "read-b@example.com"


class _ReadOp:
    """A locked ``AuditTrail`` read, driven against a trail seeded the same way (#397).

    The two calls are the *same* read against independent requests, because what
    distinguishes a read op is its lock site and both calls have to enter it.
    Nothing is asserted about the cancelled read's answer — it has none, its task
    was cancelled — so :meth:`verify` pins the state the second call had to see,
    re-read once the scenario is over.
    """

    name = ""

    async def prepare(self, trail: AuditTrail) -> None:
        """Seed an unresolved ``CONFIRM`` on one request and a resolved one on the other."""
        await trail.record(decision("c-a", request=action(parameters={"to": _EXEC_A})))
        confirmed = decision("c-b", request=action(parameters={"to": _EXEC_B}))
        await trail.record(confirmed)
        await trail.record(
            decision(
                "r-b",
                request=action(parameters={"to": _EXEC_B}),
                ruled=ruling(PermissionOutcome.ALLOW, authorised_by=confirmed.id),
                resolves=confirmed.id,
            )
        )

    def first(self, trail: AuditTrail) -> Coroutine[Any, Any, object]:
        """The read the case suspends inside the resource and then cancels."""
        raise NotImplementedError

    def second(self, trail: AuditTrail) -> Coroutine[Any, Any, object]:
        """The concurrent read barred from the resource until the first is done."""
        raise NotImplementedError

    async def verify(self, trail: AuditTrail) -> None:
        """A read cancelled mid-flight leaves the trail whole and still readable."""
        expected = decision("c-a", request=action(parameters={"to": _EXEC_A}))
        assert await trail.get("c-a") == expected
        assert {entry.id for entry in await trail.export()} == {"c-a", "c-b", "r-b"}


class _GetOp(_ReadOp):
    """``get`` — one row by id, under the connection lock."""

    name = "get"

    def first(self, trail: AuditTrail) -> Coroutine[Any, Any, object]:
        """Read the unresolved confirmation — the call that is cancelled."""
        return trail.get("c-a")

    def second(self, trail: AuditTrail) -> Coroutine[Any, Any, object]:
        """Read the resolved one concurrently."""
        return trail.get("c-b")


class _RecentOp(_ReadOp):
    """``recent`` — the ordered page, its own lock site though it shares a reader."""

    name = "recent"

    def first(self, trail: AuditTrail) -> Coroutine[Any, Any, object]:
        """Read the newest page — the call that is cancelled."""
        return trail.recent(limit=2)

    def second(self, trail: AuditTrail) -> Coroutine[Any, Any, object]:
        """Read a narrower page concurrently."""
        return trail.recent(limit=1)


class _ExportOp(_ReadOp):
    """``export`` — the whole-trail read, its own lock site."""

    name = "export"

    def first(self, trail: AuditTrail) -> Coroutine[Any, Any, object]:
        """Export everything — the call that is cancelled."""
        return trail.export()

    def second(self, trail: AuditTrail) -> Coroutine[Any, Any, object]:
        """Export again concurrently."""
        return trail.export()


#: Every locked ``AuditTrail`` operation ADR-0060's case is run against: each is a
#: distinct lock site with its own ``_run_to_completion`` call. The writes came
#: first (#370); the reads are the same invariant on the other half of the surface
#: (#397), since ADR-0060 §3 binds any method that acquires the resource rather
#: than any method that mutates.
_CANCELLATION_OPS: tuple[Callable[[], _CancellationOp], ...] = (
    _RecordOp,
    _ClearOp,
    _GetOp,
    _RecentOp,
    _ExportOp,
)


#: The part of the question an approved call in this suite runs under (ADR-0321 §4:9).
_APPROVED_PART = QuestionPart(round="q-round", part=1)


def _approval() -> Approval:
    """The approval a yes made to part 1 of the question round ``q-round`` asked."""
    return Approval(
        who=ApprovalGiver.USER_THROUGH_HUB_CHAT,
        how=YesToQuestion(activation_id="act-asked", round="q-round"),
        covers=(_APPROVED_PART,),
        given=ApprovalGiven(activation_id="act-yes", at=AT),
        ends=ApprovalEnd.WHEN_USED,
    )


def _allowing(decision_id: str = "d-allow") -> PermissionDecision:
    """An ``ALLOW`` a claim can be admitted under (ADR-0192 §1)."""
    return decision(
        decision_id,
        request=action(tool=tool(side_effecting=True, idempotency=Idempotency.NATURAL)),
        ruled=ruling(PermissionOutcome.ALLOW),
    )


def _as_ledger(trail: AuditTrail) -> Any:
    """Read the subject as the ledger it also is (ADR-0192 §2).

    The composition root injects **one object** implementing ``AuditTrail``,
    ``InvocationLedger`` and ``InvocationCompleter`` over one store, so every
    subject of this suite has the ledger's writes on it. Untyped rather than cast
    to a union of Protocols, because what this suite is about is the trail.
    """
    return trail


class AuditTrailContract:
    """Behaviour every ``AuditTrail`` implementation must exhibit."""

    @pytest.fixture
    def trail(self) -> AuditTrail:
        """Return an empty trail under test."""
        raise NotImplementedError

    # --- ADR-0321 §7:7: nothing sets a fingerprint, and the trail refuses one ---
    #
    # ``authorised_subject`` fingerprinted the recipient grant a route-(b) ``ALLOW``
    # rested on. Recipient grants retired (§7:1), so the field stays, set by nothing,
    # and ``record`` refuses an ``ALLOW`` carrying one **whether or not it resolves**.
    # The configured-provider routes are told apart by its absence, as before.

    @pytest.mark.parametrize(
        "claimed",
        [
            pytest.param(
                route_b_decision(grant_id="g-1", subject="a" * 64),
                id="the route-(b) shape, on an email",
            ),
            pytest.param(
                route_b_decision(
                    grant_id=SEARCH_ACCOUNT.reference,
                    subject="a" * 64,
                    bound=search_binding(),
                    tool=SEARCH_TOOL,
                ),
                id="a configured-provider row carrying a digest",
            ),
            pytest.param(
                decision(
                    "d-route-b",
                    ruled=ruling(
                        PermissionOutcome.ALLOW,
                        authorised_by="g-1",
                        authorised_subject="a" * 64,
                    ),
                ),
                id="a call that is not an egress call",
            ),
        ],
    )
    async def test_a_non_resolving_allow_carrying_a_fingerprint_is_refused(
        self, trail: AuditTrail, claimed: PermissionDecision
    ) -> None:
        """§7:7: with no grant left to read, a digest claims what nothing establishes.

        Refused on every shape a standing row can take — the route-(b) shape it was
        written for, a row that is otherwise route (c)'s, and a call carrying no
        binding at all — because §7:7 states the refusal over the ``ALLOW`` and not
        over its kind, and writes nothing (ADR-0021 §4's atomicity).
        """
        await _refuses(trail, claimed, InvalidAuthorisationError)

    async def test_a_resolving_allow_carrying_a_fingerprint_is_refused(
        self, trail: AuditTrail
    ) -> None:
        """Route (a) rests on a confirmation, which is not a grant (ADR-0193 §6).

        The pairing rule ``PermissionRuling`` cannot state on its own: the type can
        refuse a digest with no pointer, and only ``record`` can see ``resolves``.
        """
        confirmed = decision("d-confirm", ruled=ruling(PermissionOutcome.CONFIRM))
        await trail.record(confirmed)

        await _refuses(
            trail,
            decision(
                "d-answer",
                ruled=ruling(
                    PermissionOutcome.ALLOW,
                    authorised_by="d-confirm",
                    authorised_subject="a" * 64,
                ),
                resolves="d-confirm",
            ),
            InvalidAuthorisationError,
        )

    async def test_a_route_a_allow_with_no_fingerprint_is_recorded_unchanged(
        self, trail: AuditTrail
    ) -> None:
        """Route (a) is unchanged, and the yes path rests on it (ADR-0321 §4:7, §9)."""
        confirmed = decision("d-confirm", ruled=ruling(PermissionOutcome.CONFIRM))
        await trail.record(confirmed)
        answered = decision(
            "d-answer",
            ruled=ruling(PermissionOutcome.ALLOW, authorised_by="d-confirm"),
            resolves="d-confirm",
        )

        assert await trail.record(answered) == "d-answer"
        assert await trail.get("d-answer") == answered

    async def test_a_decision_with_no_binding_and_no_fingerprint_is_recorded(
        self, trail: AuditTrail
    ) -> None:
        """The scope pin: no rule here is a general rule about ``authorised_by``.

        A non-resolving ``ALLOW`` whose ``egress_binding`` is ``None`` is **not an
        egress call**, so ADR-0021 §6's standing grants for other actions fall
        outside the standing-row invariant rather than needing an exception inside
        it. What §7:7 refuses is the digest, and this row carries none.
        """
        recorded = decision(
            "d-standing",
            ruled=ruling(PermissionOutcome.ALLOW, authorised_by="g-1"),
        )

        assert await trail.record(recorded) == "d-standing"

    # --- ADR-0247 §2: the configured-provider route, read off the row alone ---
    #
    # A non-resolving egress ``ALLOW`` whose ``authorised_by`` is set and which
    # carries no ``authorised_subject`` claims route (c), and is admitted from its own
    # binding with no store read, no ``Settings`` read and no clock.

    async def store_as_history(self, trail: AuditTrail, recorded: PermissionDecision) -> None:
        """Override to place ``recorded`` in ``trail`` **bypassing ``record``**.

        The suite's second factory, added for ADR-0193 §15's reason: a clause about
        what **history** reads as cannot be stated through a write path that refuses
        the shape. ADR-0247 §12's Arm D"' is asserted "over the stored row rather than
        over ``record``, because ``record`` refuses that shape going forward and the
        question here is what history reads as".

        An implementation seeds the row the way its own storage admits — a durable one
        through its own insert, the canonical fake through the objects it holds — and
        neither is asked to validate anything. The row must read back through the
        Protocol's own readers afterwards.
        """
        raise NotImplementedError

    @pytest.mark.parametrize(
        ("bound", "declaration"),
        [
            pytest.param(search_binding(), SEARCH_TOOL, id="closed_loop alone"),
            pytest.param(forecast_binding(), FORECAST_TOOL, id="forecast_reach alone"),
        ],
    )
    async def test_a_digest_free_standing_row_is_admitted_from_its_own_binding(
        self, trail: AuditTrail, bound: EgressBinding, declaration: ToolDefinition
    ) -> None:
        """§12's **Arm D**, route (c)'s half, over ADR-0272 §3's two admitted facts.

        ADR-0247 §2 as ADR-0272 §1 moves its eligibility conjunct: a non-resolving
        ``ALLOW`` carrying an ``egress_binding`` and an ``authorised_by`` with **no**
        ``authorised_subject`` is accepted **only** where **exactly one** of its
        binding's ``closed_loop`` and ``forecast_reach`` is ``True`` and its
        ``authorised_by`` equals that binding's ``account.reference``.

        **Parameterised over both one-hot states**, which is §3's own instruction for
        the pointer half: an implementation taking the pointer comparison **inside**
        the ``closed_loop`` branch would pass every other arm while recording a
        forecast row on an ``authorised_by`` the policy invented.

        The refusing row is the same shape with a pointer the binding contradicts:
        "without this the pointer is a string a policy could invent", one route over.
        """
        recorded = route_c_decision(bound=bound, tool=declaration)

        assert await trail.record(recorded) == "d-route-c"
        assert await trail.get("d-route-c") == recorded

        await _refuses(
            trail,
            route_c_decision(
                bound=bound,
                tool=declaration,
                authorised_by="conn-somewhere-else",
                decision_id="d-invented",
            ),
            InvalidAuthorisationError,
        )

    @pytest.mark.parametrize(
        ("bound", "declaration"),
        [
            pytest.param(forecast_binding(forecast_reach=False), FORECAST_TOOL, id="neither fact"),
            pytest.param(forecast_binding(closed_loop=True), FORECAST_TOOL, id="both facts"),
        ],
    )
    async def test_a_digest_free_standing_row_carrying_neither_fact_or_both_is_refused(
        self, trail: AuditTrail, bound: EgressBinding, declaration: ToolDefinition
    ) -> None:
        """ADR-0272 §3's other two arms: the exactly-one rule, from both sides.

        A binding carrying **neither** fact is of no kind route (c) covers; a binding
        carrying **both** asserts a kind route (c)'s closed two-member set does not
        contain, and admitting it would let one kind's authority be read off the
        other's. Both rows carry a pointer their binding **agrees** with, so what
        refuses them is the eligibility conjunct and not the pointer half.
        """
        await _refuses(
            trail,
            route_c_decision(bound=bound, tool=declaration),
            InvalidAuthorisationError,
        )

    async def test_a_digest_free_standing_row_whose_origin_was_never_recorded_is_refused(
        self, trail: AuditTrail
    ) -> None:
        """A binding that records no origin is refused **by name** (ADR-0184 §7).

        It carries **neither** configured-provider fact, so no lane reads an
        unrecorded origin as a configured provider (ADR-0247 §2, ADR-0272 §2).
        """
        await _refuses(
            trail,
            route_c_decision(bound=origin_unrecorded(ALICE)),
            InvalidAuthorisationError,
        )

    @pytest.mark.parametrize(
        "kind",
        ["send_email", "fetch_url", "run_tool"],
    )
    async def test_a_digest_free_standing_row_of_another_kind_is_refused(
        self, trail: AuditTrail, kind: str
    ) -> None:
        """§12's **Arm D"** — the hole the eligibility conjunct closes.

        A non-resolving ``ALLOW`` with a valid binding carrying **neither**
        configured-provider fact, ``authorised_subject`` unset and ``authorised_by``
        **equal to the binding's own ``account.reference``** is refused: an ``ALLOW``
        on an email, a fetch or a tool call rests on no standing route, and a faulty
        policy cannot reach past this enforcement by omitting a digest.
        """
        declaration = TOOL.model_copy(update={"id": kind, "capability": kind})

        await _refuses(
            trail,
            route_c_decision(bound=binding(ALICE), tool=declaration, decision_id=f"d-{kind}"),
            InvalidAuthorisationError,
        )

    async def test_the_row_adr_0193_reserves_is_classified_as_neither_route(
        self, trail: AuditTrail
    ) -> None:
        """§12's **Arm D"'**: what ADR-0193 §11's pre-implementation pointer reads as.

        A stored non-resolving egress ``ALLOW`` with ``authorised_by`` set, no
        ``authorised_subject``, and a binding carrying neither configured-provider
        fact. ADR-0247 §2 **does not give it a basis it never had**: it is read back
        unchanged, it is not re-validated, and no component reports it as a
        configuration authority.

        Asserted over the **stored** row rather than over ``record``, which refuses the
        shape going forward, and through :meth:`store_as_history`, because a suite
        cannot state a clause about history through a write path that will not write
        it.
        """
        reserved = route_c_decision(
            bound=search_binding(closed_loop=False), decision_id="d-reserved"
        )
        await self.store_as_history(trail, reserved)

        assert await trail.get("d-reserved") == reserved
        assert [held.id for held in await trail.export()] == ["d-reserved"]
        assert [held.id for held in await trail.recent()] == ["d-reserved"]

    # --- append-only ------------------------------------------------------

    # --- ADR-0321 §4:7, §4:8: a decision names the approval its call runs under -----

    async def test_a_decision_naming_an_approval_is_kept_and_read_back(
        self, trail: AuditTrail
    ) -> None:
        """§4:8: recorded and read back before anything runs, the approval with it."""
        allowed = PermissionDecision.from_request(
            action(),
            ruling(PermissionOutcome.ALLOW),
            id="d-approved",
            decided_at=AT,
            effect="e-1",
            approval=_approval(),
            approved_part=_APPROVED_PART,
        )

        await trail.record(allowed)

        read = await trail.get("d-approved")
        assert read == allowed
        assert read is not None
        assert (read.approval, read.approved_part) == (_approval(), _APPROVED_PART)

    async def test_route_a_records_the_fresh_confirm_and_its_resolution_under_one_approval(
        self, trail: AuditTrail
    ) -> None:
        """§4:7: the confirm ruled fresh in the yes's activation, and the resolving
        decision naming it, each name the approval and are kept whole."""
        confirmed = PermissionDecision.from_request(
            action(),
            ruling(PermissionOutcome.CONFIRM),
            id="d-confirm",
            decided_at=AT,
            effect="e-1",
            approval=_approval(),
            approved_part=_APPROVED_PART,
        )
        resolved = PermissionDecision.from_request(
            action(),
            ruling(PermissionOutcome.ALLOW, authorised_by="d-confirm"),
            id="d-resolve",
            decided_at=AT,
            resolves="d-confirm",
            effect="e-1",
            approval=_approval(),
            approved_part=_APPROVED_PART,
        )

        await trail.record(confirmed)
        await trail.record(resolved)

        assert await trail.get("d-confirm") == confirmed
        assert await trail.get("d-resolve") == resolved

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

    # --- one id space, both row kinds (ADR-0192 §2) ------------------------

    @pytest.mark.parametrize("complete_it", [False, True], ids=["claim", "completion"])
    async def test_recording_a_decision_under_an_invocations_id_is_refused(
        self, trail: AuditTrail, *, complete_it: bool
    ) -> None:
        """The write-once invariant binds the store from **both** sides.

        Every collision case in ``InvocationLedgerContract`` drives ids the
        *ledger* mints; none drives the one a caller chooses. Without this an
        implementation keeping decisions and invocations in separate tables
        satisfies all of them while one durable identifier names two records —
        which ``recent_invocations``' join then resolves to two different rows.

        The subject is one object satisfying ``AuditTrail`` **and**
        ``InvocationLedger`` over one store, which is what ADR-0192 §2 requires of
        an implementation, so this suite can reach the ledger's writes.
        """
        ledger = _as_ledger(trail)
        authorisation = _allowing()
        await trail.record(authorisation)
        row = await ledger.claim_invocation(decision=authorisation)
        if complete_it:
            row = await ledger.complete_invocation(
                claim_id=row.id,
                outcome=ToolOutcome.FAILED,
                incurred_cost=ToolCost(basis=CostBasis.UNKNOWN),
            )

        await _refuses(trail, decision(row.id), AuditError)

        held = [
            recorded.invocation
            for recorded in await ledger.export_invocations()
            if recorded.invocation.id == row.id
        ]
        assert held == [row], "the existing row is left exactly as it stood"
        assert await trail.get(row.id) is None

    # The **concurrent** arm of the same invariant lives in
    # ``InvocationLedgerContract``, which is where a case can inject the factory
    # that forces the collision; this suite has no hook for one, and reaching into
    # a subject's private allocator would be a case about an attribute name.

    # --- the three invocation reads (ADR-0192 §2) -------------------------
    # ADR-0192 §9 lands these members' obligations "in that Protocol's existing
    # conformance suite", which is this one: they are `AuditTrail` members, and an
    # implementation must not be able to pass its own suite while failing them.
    #
    # What is here is what an `AuditTrail` owes about a *read*. Everything needing a
    # collaborator this suite cannot inject — a clock, an identifier factory, a
    # second instance over one store — or a race, a cancellation or a consume, is
    # `InvocationLedgerContract`'s, because those are obligations of the writes and
    # of the ledger's own collaborators rather than of these three members.

    async def test_a_listed_row_carries_the_tool_its_decision_names(
        self, trail: AuditTrail
    ) -> None:
        """The identity lives on the decision, so the listing is where they are paired.

        A page can hold a completion whose claim and whose decision are not on it,
        which is why the row is served joined rather than left for a caller to look
        up (ADR-0192 §2).
        """
        ledger = _as_ledger(trail)
        authorisation = _allowing()
        await trail.record(authorisation)
        claim = await ledger.claim_invocation(decision=authorisation)

        listed = await ledger.export_invocations()

        assert [held.invocation for held in listed] == [claim]
        assert listed[0].tool == authorisation.tool.id
        assert listed[0].capability == authorisation.tool.capability
        assert listed[0].egress_call is False

    async def test_egress_call_is_true_exactly_when_the_decision_carries_a_binding(
        self, trail: AuditTrail
    ) -> None:
        """The discriminator is the binding's presence (ADR-0178 §4), not a copy of it."""
        ledger = _as_ledger(trail)
        plain = _allowing("d-plain")
        crossing = _allowing("d-egress").model_copy(
            update={
                "egress_binding": EgressBinding(
                    spans=(),
                    account=BoundAccount(identity="work@example.com", reference="conn-0001"),
                    transport_endpoint="test://endpoint/one",
                    planned_with_external_content=False,
                    coverage=SpanCoverage.NOT_COVERED,
                )
            }
        )
        await trail.record(plain)
        await trail.record(crossing)
        await ledger.claim_invocation(decision=plain)
        await ledger.claim_invocation(decision=crossing)

        by_decision = {
            held.invocation.decision_id: held for held in await ledger.export_invocations()
        }

        assert by_decision["d-plain"].egress_call is False
        assert by_decision["d-egress"].egress_call is True

    async def test_the_listings_are_ordered_newest_first_with_ties_broken_by_id(
        self, trail: AuditTrail
    ) -> None:
        """One total order, and it is stated rather than left to the store's insertion.

        Asserted as a *sort key* rather than as a fixed sequence, so the case says
        the same thing whatever the trail's clock does — which is what lets it live
        in a suite that injects no clock.
        """
        ledger = _as_ledger(trail)
        authorisation = _allowing()
        await trail.record(authorisation)
        for _ in range(3):
            claim = await ledger.claim_invocation(decision=authorisation)
            await ledger.complete_invocation(
                claim_id=claim.id,
                outcome=ToolOutcome.FAILED,
                incurred_cost=ToolCost(basis=CostBasis.UNKNOWN),
            )

        listed = [held.invocation for held in await ledger.export_invocations()]

        assert len(listed) == 6
        keys = [(-row.recorded_at.timestamp(), row.id) for row in listed]
        assert keys == sorted(keys)

    async def test_the_bounded_listing_is_a_prefix_of_the_whole_one(
        self, trail: AuditTrail
    ) -> None:
        """``recent_invocations`` bounds ``export_invocations``; it does not reorder it."""
        ledger = _as_ledger(trail)
        authorisation = _allowing()
        await trail.record(authorisation)
        for _ in range(3):
            claim = await ledger.claim_invocation(decision=authorisation)
            await ledger.complete_invocation(
                claim_id=claim.id,
                outcome=ToolOutcome.FAILED,
                incurred_cost=ToolCost(basis=CostBasis.UNKNOWN),
            )

        whole = await ledger.export_invocations()
        bounded = await ledger.recent_invocations(limit=2)

        assert bounded == whole[:2]
        assert await ledger.recent_invocations() == whole  # the default page holds all six

    async def test_the_default_page_is_bounded_at_the_stated_size(self, trail: AuditTrail) -> None:
        """``recent_invocations()`` returns a *page*, and the figure is a contract clause.

        A default written in a ``Protocol`` signature binds nobody — each
        implementation writes its own — so ADR-0085 §3a makes it normative and
        :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE` is the figure. An
        implementation returning everything passes every other case here, because
        no other one seeds more rows than the bound: this is the only case that can
        tell a page from the whole table.

        One row past the bound is what makes the assertion sharp in both directions
        — it catches the unbounded implementation and an off-by-one alike.
        """
        ledger = _as_ledger(trail)
        authorisation = _allowing()
        await trail.record(authorisation)
        for _ in range(DEFAULT_PAGE_SIZE + 1):
            await ledger.claim_invocation(decision=authorisation)

        whole = await ledger.export_invocations()
        page = await ledger.recent_invocations()

        assert len(whole) == DEFAULT_PAGE_SIZE + 1
        assert page == whole[:DEFAULT_PAGE_SIZE]

    async def test_the_open_set_reads_its_decision_as_the_type_the_signature_names(
        self, trail: AuditTrail
    ) -> None:
        """``Identifier`` strips, so ``"  d-1  "`` and ``"d-1"`` name one decision.

        An implementation looking the raw text up answers "no open claims" for a
        decision that holds one — and the recovery scan then reserves nothing,
        completes nothing, and leaves the claim open for good, which is the state
        ADR-0192 §3 exists to clear. It is the same guard the completion path puts
        on ``claim_id``, on the member that reads by decision instead.
        """
        ledger = _as_ledger(trail)
        authorisation = _allowing()
        await trail.record(authorisation)
        claim = await ledger.claim_invocation(decision=authorisation)

        assert await ledger.open_invocations(decision_id=f"  {authorisation.id}  ") == [claim]

    @pytest.mark.parametrize("limit", [0, -1], ids=["zero", "negative"])
    async def test_a_limit_that_is_not_strictly_positive_is_refused(
        self, trail: AuditTrail, limit: int
    ) -> None:
        """``recent``'s own refusal, for ``recent``'s own reason (ADR-0073 §2)."""
        with pytest.raises(ValueError, match="limit"):
            await _as_ledger(trail).recent_invocations(limit=limit)

    async def test_a_listing_hands_back_a_detached_snapshot(self, trail: AuditTrail) -> None:
        """Reading is not a way to reach into the store (ADR-0021 §4)."""
        ledger = _as_ledger(trail)
        authorisation = _allowing()
        await trail.record(authorisation)
        claim = await ledger.claim_invocation(decision=authorisation)

        listed = await ledger.export_invocations()
        listed[0].invocation.__dict__["decision_id"] = "d-tampered"

        assert (await ledger.export_invocations())[0].invocation == claim

    async def test_the_open_set_is_the_claims_no_completion_names(self, trail: AuditTrail) -> None:
        """The exact set ADR-0192 §3's recovery scan is written against.

        A completed claim has left it, an uncompleted one is in it, and the order is
        the trail's own append order — the scan acts on this answer, so "every open
        claim and nothing else" is the whole of what it may be handed.
        """
        ledger = _as_ledger(trail)
        authorisation = _allowing()
        await trail.record(authorisation)
        settled = await ledger.claim_invocation(decision=authorisation)
        await ledger.complete_invocation(
            claim_id=settled.id,
            outcome=ToolOutcome.SUCCEEDED,
            incurred_cost=ToolCost(basis=CostBasis.UNKNOWN),
        )
        first_open = await ledger.claim_invocation(decision=authorisation)
        second_open = await ledger.claim_invocation(decision=authorisation)

        assert await ledger.open_invocations(decision_id="d-allow") == [first_open, second_open]

    async def test_the_open_set_is_scoped_to_the_decision_it_names(self, trail: AuditTrail) -> None:
        """An unknown decision has none, and a claim under another one is not here."""
        ledger = _as_ledger(trail)
        mine = _allowing("d-mine")
        theirs = _allowing("d-theirs")
        await trail.record(mine)
        await trail.record(theirs)
        claim = await ledger.claim_invocation(decision=mine)
        await ledger.claim_invocation(decision=theirs)

        assert await ledger.open_invocations(decision_id="d-mine") == [claim]
        assert await ledger.open_invocations(decision_id="d-never-recorded") == []

    async def test_clear_erases_both_row_kinds(self, trail: AuditTrail) -> None:
        """One erasure over one record (ADR-0192 §6), read back through these members.

        Two erasure acts over one store would let a user destroy the executions and
        keep the rulings, which is selective erasure with an extra step. The count is
        over both kinds, so asserting emptiness alone would leave a store free to
        return the decision-only figure it returned before this ADR.
        """
        ledger = _as_ledger(trail)
        authorisation = _allowing()
        await trail.record(authorisation)
        claim = await ledger.claim_invocation(decision=authorisation)
        await ledger.complete_invocation(
            claim_id=claim.id,
            outcome=ToolOutcome.FAILED,
            incurred_cost=ToolCost(basis=CostBasis.UNKNOWN),
        )

        assert await trail.clear() == 3

        assert await trail.export() == []
        assert await ledger.export_invocations() == []
        assert await ledger.recent_invocations() == []
        assert await ledger.open_invocations(decision_id="d-allow") == []

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
        ],
        ids=["a different tool", "a tampered definition", "different arguments"],
    )
    async def test_a_resolution_must_answer_the_question_that_was_asked(
        self, trail: AuditTrail, substituted: ActionRequest
    ) -> None:
        """A bare pointer would be worse than none.

        It would let an ``ALLOW`` for tool B claim to be the user's answer to a
        ``CONFIRM`` shown for tool A — the substitution the embedded definition
        closes, reintroduced through the one path where a human was actually
        consulted. The subject is compared on tool and payload digest; no step is
        compared, since neither record carries one (ADR-0318 §6:1).
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

    async def test_identical_confirmations_are_resolved_independently(
        self, trail: AuditTrail
    ) -> None:
        """No step and no execution couples two confirmations (ADR-0318 §6:1).

        ADR-0044's per-binding rule left with the step and the execution, so two
        confirmations of one request are two questions: resolving one must not decide
        the other. Only the per-confirmation rule applies, and it keeps them
        independent.
        """
        direct: dict[str, object] = {}
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

    async def test_a_limit_wider_than_a_backing_store_can_bind_still_answers(
        self, trail: AuditTrail
    ) -> None:
        """A bound above any possible row count means "all of them", not an error.

        ``limit`` is a Python ``int`` and has no width, so ``2**63`` is a perfectly
        valid strictly-positive request. Binding one that wide into SQLite raises
        ``OverflowError`` — neither ``ValueError`` nor ``AuditError``, so it leaves
        this seam's error boundary through a hole while every other clause here
        still passes.

        Not the ``limit=-1`` case above, and the difference is the whole of why one
        is refused and this one clamped: a bound past every row serves exactly what
        was asked for, where clamping a negative would serve something the caller
        did not ask for. ``SqliteAuditTrail.recent`` is where that reasoning is
        written out, and it is the implementation this clause was a property of
        rather than of the contract until now (#679).

        **This decides nothing; the ratified Protocol already did.**
        ``AuditTrail.recent``'s ``Raises:`` names ``ValueError`` for one input and
        one only — "if ``limit`` is not strictly positive" — and rejects clamping
        *for that input*, because a caller asking for something meaningless should
        learn so. ``2**63`` is strictly positive, so serving it is what the
        contract as written already requires; anything else would be a raise the
        Protocol does not document. ``MemoryStore.list_beliefs`` shows what an
        upper refusal looks like when one is meant, and no read here has one.
        """
        await trail.record(decision("d-1"))

        assert [each.id for each in await trail.recent(limit=2**63)] == ["d-1"]

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

    @pytest.mark.parametrize("supplied", ["model", "mapping", "whole-decision"])
    async def test_a_decision_whose_binding_records_no_origin_is_refused(
        self, trail: AuditTrail, supplied: str
    ) -> None:
        """ADR-0184 §4's second clause, §10's eleventh: read such a row, never write one.

        An :class:`~ai_assistant.core.types.OriginUnrecordedBinding` represents a row
        written before ADR-0181 §3 added ``planned_with_external_content``. ADR-0184
        §5 makes a trail *return* one from its history readers, and this is the other
        half: an epoch that has ended may be read out of and never appended to.
        Without the refusal, a caller bypassing ``PermissionDecision.from_request``
        could mint a new row in that epoch — a fabrication of **history**, and harder
        to notice later than a fabricated value, since every field of it would look
        exactly like a genuine old record.

        **This is the one refusal the model cannot make for itself**, which is why it
        belongs to ``record`` rather than to ``PermissionDecision``: that shape is a
        *valid* decision, because it has to be for a stored row to decode into one at
        all. ``record`` is where the trail already enforces what a model cannot see —
        the resolution invariant, the authorisation pointer, the ordering rule — for
        ADR-0021 §4's reason: it is the boundary where the whole record is in hand.

        The subject is built by substitution rather than by a builder, deliberately:
        ADR-0184 §4 leaves **no** sanctioned path that produces one, so a suite that
        could arrange it the ordinary way would be evidence the field was widened
        somewhere it should not have been.

        **Both routes into the field are exercised, and the second is the one an
        implementation fails.** ``model_copy(update=...)`` does not validate, so a
        caller may put either a built model *or* a bare mapping there. A store that
        checks the decision it was handed rather than the snapshot it is about to
        write sees a ``dict`` for the mapping case, answers "not that shape", and then
        rebuilds the mapping into precisely that shape on its way into the row — so
        the refusal holds for the arrangement nobody would try and fails for the one a
        careless caller actually produces. Checking what will be *stored* is what
        closes both at once, and is the same reason ADR-0021 §4 asks for a validated
        snapshot rather than a copied one.

        **The third arm hands the whole decision over as a mapping**, which the same
        ordering admits: a value that is not a model reaches ``model_validate``
        untouched and comes back a decision. A store naming the refusal from what it
        was *handed* rather than from the snapshot then asks a ``dict`` for its
        ``.id`` — an ``AttributeError`` raised from inside the refusal that was about
        to be made, and outside the classes ADR-0192 §2's order admits.

        ``_refuses`` asserts the write left no trace, which matters more here than
        usual: a store that appended and *then* raised would be holding precisely the
        fabricated history this clause exists to make impossible.
        """
        members: dict[str, object] = {
            "spans": (),
            "account": BoundAccount(identity="work@example.com", reference="conn-0001"),
            "transport_endpoint": "test://endpoint/one",
        }
        binding: object = (
            OriginUnrecordedBinding(**members)  # type: ignore[arg-type]  # heterogeneous members
            if supplied == "model"
            else members
        )
        await trail.record(decision("d-1"))
        unrecorded = decision("d-2").model_copy(update={"egress_binding": binding})
        handed: Any = unrecorded
        if supplied == "whole-decision":
            handed = {**dict(unrecorded), "egress_binding": members}

        await _refuses(trail, handed, AuditError)

        assert await trail.get("d-2") is None
        assert [held.id for held in await trail.export()] == ["d-1"]

    @pytest.mark.parametrize("supplied", ["model", "mapping", "whole-decision"])
    async def test_a_decision_whose_binding_records_no_coverage_is_refused(
        self, trail: AuditTrail, supplied: str
    ) -> None:
        """ADR-0233 §14's write clause: read such a row, never write one.

        ADR-0184 §4's second clause extended **by cause** and for §4's own reason, at
        the epoch after the one above. A
        :class:`~ai_assistant.core.types.CoverageUnrecordedBinding` represents a row
        written before ADR-0233 §4 added ``coverage``; ADR-0184 §5's readers hand one
        back as history, and this is the other half — an epoch that has ended may be
        read out of and never appended to, so the shape cannot be minted into a trail
        and back-dated as history it is not.

        **The refusal is stated rather than inherited, and this suite is where that
        matters most.** Such a row *has* ``planned_with_external_content``, so it is
        **not** an ``OriginUnrecordedBinding``: an implementation that narrowed only
        against that class passes the case above and fails this one, appending a
        fabricated row from an epoch nobody is writing in.

        The three arms are the case above's, for its reasons: a built model, a bare
        mapping through ``model_copy(update=...)`` — which does not validate, so a
        store checking what it was *handed* rather than the snapshot it is about to
        *write* rebuilds the mapping into exactly the shape it just refused — and the
        whole decision handed over as a mapping, which reaches ``model_validate``
        untouched and comes back a decision.
        """
        members: dict[str, object] = {
            "spans": (),
            "account": BoundAccount(identity="work@example.com", reference="conn-0001"),
            "transport_endpoint": "test://endpoint/one",
            "planned_with_external_content": False,
        }
        binding: object = (
            CoverageUnrecordedBinding(**members)  # type: ignore[arg-type]  # heterogeneous members
            if supplied == "model"
            else members
        )
        await trail.record(decision("d-1"))
        unrecorded = decision("d-2").model_copy(update={"egress_binding": binding})
        handed: Any = unrecorded
        if supplied == "whole-decision":
            handed = {**dict(unrecorded), "egress_binding": members}

        await _refuses(trail, handed, AuditError)

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

    async def test_a_decision_carrying_a_subclass_beneath_it_is_refused(
        self, trail: AuditTrail
    ) -> None:
        """What the trail stores is what it was handed, or nothing is.

        The obligation is on the *declared* type
        (:meth:`test_detachment_survives_a_caller_supplied_subclass`), and a nested
        subclass is where that stops being free. Pydantic's default
        ``revalidate_instances="never"`` keeps a ``ToolDefinition`` subclass on
        ``PermissionDecision.tool`` through ordinary construction, so a store
        rebuilding through the declared type drops the field that subclass declares
        of its own and records a smaller thing than it was passed.

        Refused rather than trimmed, because the snapshot is not only stored: under
        ADR-0192 §1 a claim is admitted by comparing it, and a snapshot equal to a
        decision nobody held is an admission rather than a lossy record.
        """

        class _ExtendedTool(ToolDefinition):
            smuggled: str = "state the trail never saw"

        held = decision("d-1")
        carried = PermissionDecision(**{**dict(held), "tool": _ExtendedTool(**dict(held.tool))})

        with pytest.raises(AuditError):
            await trail.record(carried)

        assert await trail.get("d-1") is None
        assert await trail.export() == []

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

    # --- cancellation (ADR-0060) -------------------------------------------

    #: Whether this implementation acquires nothing whose safety outlives the
    #: coroutine — no connection, lock, spawned task, file handle or transaction
    #: that a ``CancelledError`` could unwind past. ``core.protocols``' clause is
    #: then vacuously satisfied and there is nothing for the case below to
    #: observe. Left ``False``, the suite requires the implementation to prove the
    #: invariant by overriding :meth:`trail_suspended_mid_write` — so a new
    #: durable backend that reintroduces ADR-0054's bug fails here rather than
    #: passing a suite that never looked. Opting out is a visible declaration in
    #: the subclass.
    acquires_no_shared_resource: bool = False

    #: Operations this implementation acquires no coroutine-outliving resource for,
    #: even though others do — the per-operation form of
    #: :attr:`acquires_no_shared_resource`, for a subject that takes the lock on
    #: some operations but not another. Nothing declares it: every operation on both
    #: shipped subjects enters a resource, so it is supported machinery with no
    #: current user, like an unexercised branch. It is stated hypothetically on
    #: purpose — it was once illustrated with ``FakeAuditTrail.clear``, which #396
    #: routed through the modelled resource and #504 recorded as an example that had
    #: stopped being true. Empty by default: an implementation whose every locked
    #: operation is resource-backed proves them all.
    operations_without_shared_resource: frozenset[str] = frozenset()

    def trail_suspended_mid_write(
        self,
    ) -> AbstractAsyncContextManager[SuspendedMidWrite[AuditTrail]]:
        """Supply a trail whose named locked operation can be stopped *inside* its resource.

        Override unless :attr:`acquires_no_shared_resource` is set. The suite
        cancels the call while it is suspended and then watches what a second
        caller can reach, which is the only way to tell the fixed code from the
        broken code: pre-ADR-0054 the trail raised ``CancelledError`` correctly
        and released the connection anyway, so a case that asserts only
        propagation certifies the bug (ADR-0060 §3).

        The returned :class:`SuspendedMidWrite` carries the trail, its
        :class:`ResourceLog`, and an ``arm(operation)`` lever the case calls —
        *after* its preconditions — to hold the next entry into that operation
        (#370, #397). Every distinct ``async with self._lock`` site is a separate
        place the same regression can reappear — the locked *reads* included, since
        ADR-0060 §3 binds any method that acquires the resource — so the case is run
        against each; ``arm``
        is where the implementation says how it stops a given one — a worker
        thread parked mid-SQL, a fake's single modelled resource. Returned as a
        context manager so the subject is disposed of the way that implementation
        needs.

        The :class:`ResourceLog` records each call's time *inside* the resource,
        and the case reads it once the scenario is over. It is not redundant with
        the blocked-caller check below: that one is decisive only where queueing
        is loop-bound (a fake on an ``asyncio.Lock``), while a trail whose work
        runs on an executor can leave a second call pending for reasons that have
        nothing to do with the resource. The log settles that case directly.
        """
        raise NotImplementedError

    @pytest.mark.optional_obligation
    @pytest.mark.parametrize("make_op", _CANCELLATION_OPS, ids=lambda op: op().name)
    async def test_a_cancelled_operation_holds_its_resource_until_the_work_finishes(
        self, make_op: Callable[[], _CancellationOp]
    ) -> None:
        """``core.protocols``' cancellation clause, on every locked operation (ADR-0060).

        A cancelled call must not hand the resource to the next caller while the
        work it started is still using it. The second call is what makes this a
        test of the invariant rather than of propagation: a single cancelled call
        in isolation looks identical either way. Run once per locked operation, so
        a regression reintroduced at any one lock site — not just ``record`` — is
        caught.

        **Named for an operation, not an append.** ADR-0060 §3 binds any method that
        acquires the resource; the writes were covered first (#370) and the locked
        reads are the same invariant on the other half of the surface (#397). A read
        that released the connection under cancellation while its worker still held
        it is the identical ADR-0054 hazard, and no write case can see it.

        The cancelled write's *effect* is deliberately not asserted here (the op's
        ``verify`` pins only what a caller may rely on). The clause's third
        paragraph makes it indeterminate to the caller — under ADR-0054's shield a
        write that reached ``COMMIT`` is durably written — so the two calls are
        independent subjects and what is pinned is that the second is whole and
        the trail still serves reads. That an append-only trail may hold an entry
        whose caller was cancelled is not a gap: ADR-0021 §4's guarantee is that
        nothing recorded is rewritten, and an indeterminate write is exactly the
        case the third clause names.
        """
        if self.acquires_no_shared_resource:
            pytest.skip("implementation acquires nothing whose safety outlives the coroutine")

        op = make_op()
        if op.name in self.operations_without_shared_resource:
            pytest.skip(f"{op.name} acquires nothing whose safety outlives the coroutine")

        async with self.trail_suspended_mid_write() as harness:
            trail = harness.store
            await op.prepare(trail)
            # Arm *after* the preconditions, so a fake arming its one resource
            # suspends the operation under test rather than a setup write.
            suspended = harness.arm(op.name)
            visited_before = harness.log.visits

            first = asyncio.ensure_future(op.first(trail))
            second: asyncio.Task[object] | None = None
            try:
                await suspended.reached()
                first.cancel()
                await settle()

                second = asyncio.ensure_future(op.second(trail))
                await settle()
                assert not second.done(), _RELEASED_EARLY

                # Again, because deferring one cancellation is not the contract:
                # a second delivered while the deferred wait runs must not escape
                # and unwind out of the resource either (ADR-0054's helper loops
                # on `while not done.is_set()` for exactly this).
                first.cancel()
                await settle()
                assert not second.done(), _RELEASED_EARLY
            finally:
                suspended.release()

            with pytest.raises(asyncio.CancelledError):
                await first
            assert second is not None
            await second

            # Decisive where the blocked-caller check above is not: the two calls
            # were never inside the resource at the same time. A delta, because a
            # fake's preconditions pass through the same logged resource.
            assert not harness.log.overlapped, _RELEASED_EARLY
            assert harness.log.visits - visited_before == 2, (
                "both calls should have reached the resource by now"
            )

            await op.verify(trail)
