"""What the simulated booking provider does (ADR-0273 §10's arms 5-17 and 19-21).

Every case here drives the **production** component — the declarations a composition
root registers, the binding the real seam derives, the callable the real registry
invokes, and the SQLite store that actually lives under a deployment's data directory.
None of them opens a socket, reads a clock the provider was not given or consults a
random source, which is ADR-0260 §13's standing requirement holding by construction:
the provider takes no ``OutboundTransport`` parameter at all (§3).

Arms 1, 3, 4 and 18 are in :mod:`test_booking_registration`; arms 2 and 12 are in
``tests/core/test_booking_settings.py``, where ``Settings`` is.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import pytest
from booking_harness import (
    AVAILABLE_FROM,
    BOOKING_ACT,
    BOOKING_ACT_ID,
    BOOKING_AVAILABILITY,
    BOOKING_AVAILABILITY_ID,
    CURRENCY,
    DECIDED_AT,
    ENDPOINT,
    IN_WINDOW,
    PRICE,
    REFERENCE,
    UNAVAILABLE,
    UNCERTAIN,
    Records,
    arguments,
    authorised,
    bound,
    configured,
    drive,
    entry,
    keyring,
    recorded,
    registry_for,
    seam_for,
)

from ai_assistant.core.errors import ClassifiedToolError
from ai_assistant.core.types import (
    ActionPlan,
    ActionQuote,
    ActionRequest,
    AttemptState,
    AuthorizationBasis,
    BoundKind,
    CoverageMember,
    EffectKey,
    Goal,
    GoalAttempt,
    GoalInterpretation,
    Ground,
    MemorySource,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanStep,
    Provenance,
    ProvisioningState,
    ResolutionRule,
    SecretName,
    SecretScope,
    StepExecution,
    StepFailure,
    StepOutputRef,
    StepStatus,
    StepTransition,
    ToolFailureKind,
    ToolOutcome,
    ValueBound,
    ValueResolution,
)
from ai_assistant.orchestration.charges import ChargeTest, charge_read, charge_test
from ai_assistant.orchestration.quotes import quote_read
from ai_assistant.orchestration.reconciling import ReconciliationStage
from ai_assistant.testing import FakeAuditTrail, FakePlanStore
from ai_assistant.tools.booking import (
    AVAILABLE_KEY,
    BOOKED_KEY,
    CHARGED_AMOUNT_KEY,
    CHARGED_CURRENCY_KEY,
    DATE_ARGUMENT,
    PRICE_AMOUNT_KEY,
    PRICE_CURRENCY_KEY,
    SIMULATION_KEY,
    SIMULATION_NOTICE,
    BookingStoreError,
    SqliteBookingStore,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.types import FrozenJson, ToolCall, ToolResult
    from ai_assistant.tools.builtin import SimulatedBookingIntegration

#: The intended action a quote and a charge are read against, and the plan they sit in.
_ACTION: Final = "act-1"
_PLAN: Final = "plan-1"
_STEP: Final = "step-1"

#: A bound a case reads a quote against. ADR-0254 §4's ``MONEY`` reading compares an
#: amount at the quote's own currency, byte for byte.
_UNDER_200: Final = CoverageMember(
    kind=BoundKind.MONEY,
    bound=ValueBound(
        kind=BoundKind.MONEY,
        currency=CURRENCY,
        maximum=Decimal("200"),
        maximum_exclusive=False,
    ),
    basis=AuthorizationBasis(
        act=_ACTION,
        span="up to 200 euros",
        resolution=ValueResolution(rule=ResolutionRule.AS_STATED),
    ),
)


# --------------------------------------------------------------------------- #
# arrangement
# --------------------------------------------------------------------------- #


async def _answer(
    *, day: date | str = IN_WINDOW, **configuration: object
) -> tuple[ToolResult, SimulatedBookingIntegration]:
    """Drive one availability read through the whole production path.

    Args:
        day: The day asked about.
        **configuration: Overrides for :func:`configured`.

    Returns:
        The result and the integration, so a case can read the store as well.
    """
    booking = await configured(**configuration)  # type: ignore[arg-type]  # a case varies one configured fact
    registry = registry_for(booking)
    seam = seam_for(booking, registry)
    result = await drive(registry, seam, BOOKING_AVAILABILITY, arguments(day))
    return result, booking


async def _book(
    *, day: date | str = IN_WINDOW, decision_id: str = "d-1", **configuration: object
) -> tuple[ToolResult, SimulatedBookingIntegration]:
    """Drive one booking through the whole production path.

    Args:
        day: The day being booked.
        decision_id: The decision's id, which a case varies to make two dispatches.
        **configuration: Overrides for :func:`configured`.

    Returns:
        The result and the integration.
    """
    booking = await configured(**configuration)  # type: ignore[arg-type]  # a case varies one configured fact
    registry = registry_for(booking)
    seam = seam_for(booking, registry)
    result = await drive(registry, seam, BOOKING_ACT, arguments(day), decision_id=decision_id)
    return result, booking


def _succeeded(result: ToolResult) -> Mapping[str, FrozenJson]:
    """The output of a result this case expects to have succeeded.

    ``Mapping`` and not ``dict``: ``core`` freezes what a ``ToolResult`` holds, so a
    successful output comes back as a ``FrozenDict`` — which is a ``Mapping`` and is
    deliberately not a ``dict``.
    """
    assert result.outcome is ToolOutcome.SUCCEEDED, result.failure
    assert isinstance(result.output, Mapping)
    return result.output


def _plan_step() -> PlanStep:
    """The step a quote is minted against (ADR-0267 §4 requires an intended action)."""
    return PlanStep(
        id=_STEP,
        intent="find out what the stay costs",
        capability=BOOKING_AVAILABILITY.capability,
        parameters=arguments(),
        intended_action=_ACTION,
    )


def _recorded(output: Mapping[str, FrozenJson]) -> StepExecution:
    """The step's record, as a store would have written it after a successful read."""
    return StepExecution(
        step_id=_STEP,
        status=StepStatus.SUCCEEDED,
        attempts=1,
        bound_tool=BOOKING_AVAILABILITY_ID,
        output=output,
        approval_ref="d-1",
        started_at=DECIDED_AT,
        finished_at=DECIDED_AT,
    )


# --------------------------------------------------------------------------- #
# arm 5: the quote is read, under and over a bound
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("price", "under"),
    [("120.00", True), ("250.00", False)],
)
async def test_the_quote_mints_from_the_reads_own_output_under_and_over_a_bound(
    price: str, under: bool
) -> None:
    """Arm 5 (ADR-0267 §4, ADR-0273 §5).

    *"Once from a configuration whose price is under a stated bound and once from one
    whose price is over it, the two differing in configuration alone."* The two cases
    below differ in exactly one configured field and in nothing else — no code path, no
    argument and no declaration — which is what §5's *"without a code change"* means.

    The mint is ADR-0267 §4's own function over the **registered** ``quoted_output``, so
    what is asserted is that a real reader takes a real provider's answer.
    """
    result, _ = await _answer(price_amount=price)
    output = _succeeded(result)

    quote = quote_read(
        step=_plan_step(),
        recorded=_recorded(output),
        request=ActionRequest(tool=BOOKING_AVAILABILITY, parameters=arguments(), step_id=_STEP),
        plan=_PLAN,
    )

    assert quote is not None
    assert quote.amount == Decimal(price)
    assert quote.currency == CURRENCY
    assert quote.read_from == StepOutputRef(step=_STEP, field=PRICE_AMOUNT_KEY)
    assert (quote.amount <= Decimal("200")) is under


# --------------------------------------------------------------------------- #
# arm 6: an unavailable date, read *and* booked
# --------------------------------------------------------------------------- #


async def test_an_unavailable_day_is_answered_as_such_and_quotes_nothing() -> None:
    """Arm 6's first half (ADR-0273 §5).

    An unavailable day carries **no price keys at all**, so ADR-0267 §4's mint yields no
    quote rather than a repaired one — which is the true answer, because an unavailable
    day is quoted nothing.
    """
    result, _ = await _answer(day=UNAVAILABLE)
    output = _succeeded(result)

    assert output[DATE_ARGUMENT] == UNAVAILABLE.isoformat()
    assert output[AVAILABLE_KEY] is False
    assert PRICE_AMOUNT_KEY not in output
    assert PRICE_CURRENCY_KEY not in output
    assert (
        quote_read(
            step=_plan_step(),
            recorded=_recorded(output),
            request=ActionRequest(tool=BOOKING_AVAILABILITY, parameters=arguments(), step_id=_STEP),
            plan=_PLAN,
        )
        is None
    )


async def test_a_booking_for_an_unavailable_day_writes_nothing_and_advances_nothing() -> None:
    """Arm 6's second half — *"what stops a provider that answers* unavailable *and
    books anyway"* (ADR-0273 §2, §10 arm 6).

    The refusal is **before** the commit, so it commits none of the three: no record, no
    advance and no pruning. **The count is asserted as well as the records**, which arm
    11 makes the rule for every pre-commit refusal: *"a count advanced before a refusal
    appends nothing and still corrupts the figure"*.
    """
    result, booking = await _book(day=UNAVAILABLE)

    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.REFUSED
    assert result.output is None
    assert await booking.store.records() == ()
    assert await booking.store.commit_count() == 0


# --------------------------------------------------------------------------- #
# arm 7: the charge is readable, agreeing and disagreeing — and the finding
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("charge_amount", "charge_currency", "holds"),
    [
        ("120.00", CURRENCY, True),
        ("140.00", CURRENCY, False),
        ("120.00", "USD", False),
    ],
    ids=["agreeing", "amount-disagrees", "currency-disagrees"],
)
async def test_the_charge_reads_and_adr_0271_s_finding_fires_when_it_disagrees(
    charge_amount: str, charge_currency: str, holds: bool
) -> None:
    """Arm 7, **extended to assert ADR-0271 §3's finding** (ADR-0273 §10).

    §10's own clause: *"where the comparison has landed by the time this lane runs, the
    lane extends arm 7 to assert the finding"*. It has — ``orchestration/charges.py``
    and ``verification.classify_bound_step`` are on ``main`` — so this drives the three
    configurations through to the verification result rather than stopping at the
    reading.

    **The three differ in configuration alone**, and the last two are independently
    configurable, which is §5's requirement. **A disagreeing charge is not a provider
    whose ``quoted_output`` lies** (§2): a quote is prospective and a charge is
    retrospective, and §3 of ADR-0271 exists precisely for the case where the two
    differ. This provider offers no hold and no conditional execution **on purpose**
    (§7) — one that validated the quoted amount atomically with the act would make the
    finding undemonstrable.
    """
    result, _ = await _book(charge_amount=charge_amount, charge_currency=charge_currency)
    output = _succeeded(result)

    charge = charge_read(BOOKING_ACT, output)
    assert charge is not None
    assert charge.amount == Decimal(charge_amount)
    assert charge.currency == charge_currency

    pinned = ActionQuote(
        intended_action=_ACTION,
        arguments_digest="0" * 64,
        amount=Decimal(PRICE),
        currency=CURRENCY,
        plan=_PLAN,
        read_from=StepOutputRef(step=_STEP, field=PRICE_AMOUNT_KEY),
        read_at=DECIDED_AT,
    )
    verdict = charge_test(
        status=StepStatus.SUCCEEDED,
        definition=BOOKING_ACT,
        output=output,
        pinned=pinned,
        member=_UNDER_200,
    )

    assert verdict is (ChargeTest.HOLDS if holds else ChargeTest.FAILS)


# --------------------------------------------------------------------------- #
# arm 8: the effect key
# --------------------------------------------------------------------------- #


async def test_two_dispatches_of_one_intended_action_carry_one_effect_key() -> None:
    """Arm 8 (ADR-0259 §2).

    The key is **derived** and never minted, supplied, configured or carried as a field,
    so two calls with the same arguments under the same binding derive the *same* key —
    which is what the effect claim is keyed on, and what makes the second dispatch a
    repeat rather than a new act. The two decisions differ in id, which is what makes
    this two dispatches rather than one object compared with itself.
    """
    booking = await configured()
    registry = registry_for(booking)
    seam = seam_for(booking, registry)
    parameters = arguments()
    binding = await bound(seam, BOOKING_ACT, parameters)

    first = authorised(BOOKING_ACT, parameters, binding, decision_id="d-1")
    second = authorised(BOOKING_ACT, parameters, binding, decision_id="d-2")

    assert first.effect_key is not None
    assert isinstance(first.effect_key, EffectKey)
    assert first.effect_key == second.effect_key
    assert first.effect_key.tool_id == BOOKING_ACT_ID
    assert first.effect_key.egress_endpoint == ENDPOINT


async def test_the_reads_call_derives_no_effect_key_and_the_acts_does() -> None:
    """``effect_key`` is ``None`` *if and only if* the tool is not ``side_effecting``.

    The read performs nothing, so there is no effect to claim; the act does, so there
    is — the asymmetry ADR-0259 §2's claim rests on, over this provider's own two
    declarations.
    """
    booking = await configured()
    registry = registry_for(booking)
    seam = seam_for(booking, registry)
    parameters = arguments()

    read = authorised(
        BOOKING_AVAILABILITY, parameters, await bound(seam, BOOKING_AVAILABILITY, parameters)
    )
    act = authorised(BOOKING_ACT, parameters, await bound(seam, BOOKING_ACT, parameters))

    assert read.effect_key is None
    assert act.effect_key is not None


# --------------------------------------------------------------------------- #
# arms 9 and 10: the durable state, both halves, and the bound
# --------------------------------------------------------------------------- #


async def test_a_booking_appends_a_record_and_advances_the_count(tmp_path: Path) -> None:
    """Arm 9 (ADR-0273 §2).

    Both halves, read back **after a restart** — the store is closed and reopened from
    the same path, which is what makes "survives a restart" a fact about the file rather
    than about an object still in memory. Without a durable effect, ``IRREVERSIBLE``
    would be a claim about nothing.
    """
    path = tmp_path / "bookings.db"
    result, booking = await _book(store_path=path)
    _succeeded(result)
    booking.store.close()

    reopened = SqliteBookingStore(path=path, retained=2)
    try:
        records = await reopened.records()
        assert len(records) == 1
        assert records[0][DATE_ARGUMENT] == IN_WINDOW.isoformat()
        assert records[0][CHARGED_AMOUNT_KEY] == PRICE
        assert await reopened.commit_count() == 1
    finally:
        reopened.close()


async def test_the_store_leaves_no_artifact_outside_the_configured_directory(
    tmp_path: Path,
) -> None:
    """Arm 9's directory half, and its purge half (ADR-0273 §2, ADR-0126).

    The store is *"an ordinary store of this deployment"* — everything it writes is
    under the directory it was given, so ``ai-assistant-purge`` destroys it with every
    other store, and a reopened store afterwards holds **no booking record and no
    count**.
    """
    directory = tmp_path
    path = directory / "bookings.db"
    _, booking = await _book(store_path=path)
    booking.store.close()

    written = {one.name for one in directory.iterdir()}
    assert written <= {"bookings.db", "bookings.db-journal", "bookings.db-wal", "bookings.db-shm"}

    for one in directory.iterdir():
        one.unlink()  # what `ai-assistant-purge` does to the whole data directory
    purged = SqliteBookingStore(path=path, retained=2)
    try:
        assert await purged.records() == ()
        assert await purged.commit_count() == 0
    finally:
        purged.close()


async def test_the_bound_prunes_records_and_the_count_still_reports_every_booking(
    tmp_path: Path,
) -> None:
    """Arm 10 — *"the arm that shows retention removing detail and not the act"* (§2).

    Four bookings past a bound of two leave two records and a count of four, **after a
    restart**. The count is what carries the act's irreversibility past the record's
    retention: a provider whose only durable artifact were a prunable record would have
    an effect that retention undoes, which is ``RECOVERABLE``, and §2 would be declaring
    something untrue as soon as the bound was crossed.
    """
    path = tmp_path / "bookings.db"
    booking = await configured(store_path=path, retained_records=2)
    registry = registry_for(booking)
    seam = seam_for(booking, registry)
    days = [date(2026, 10, day) for day in (1, 2, 3, 4)]
    for index, day in enumerate(days):
        _succeeded(
            await drive(registry, seam, BOOKING_ACT, arguments(day), decision_id=f"d-{index}")
        )
    booking.store.close()

    reopened = SqliteBookingStore(path=path, retained=2)
    try:
        records = await reopened.records()
        assert [one[DATE_ARGUMENT] for one in records] == [day.isoformat() for day in days[-2:]]
        assert await reopened.commit_count() == len(days)
    finally:
        reopened.close()


async def test_a_bound_lowered_between_runs_is_honoured_at_the_next_open(
    tmp_path: Path,
) -> None:
    """The retention-enforcement point PR #2495's ratification waived to this lane.

    §2 assigns the pruning **mechanics** to the lane, and the obligation is that the
    store never retains more records than the configured bound *whatever path it prunes
    on*. A commit-time-only prune leaves a store over-full from the moment an operator
    lowers the bound until the next booking, which may never come — so the bound is
    enforced at **open** time as well, and this is the case that shows it across a
    restart.
    """
    path = tmp_path / "bookings.db"
    booking = await configured(store_path=path, retained_records=4)
    registry = registry_for(booking)
    seam = seam_for(booking, registry)
    for index, day in enumerate(date(2026, 10, day) for day in (1, 2, 3, 4)):
        _succeeded(
            await drive(registry, seam, BOOKING_ACT, arguments(day), decision_id=f"d-{index}")
        )
    booking.store.close()

    narrowed = SqliteBookingStore(path=path, retained=1)
    try:
        records = await narrowed.records()
        assert len(records) == 1
        assert records[0][DATE_ARGUMENT] == "2026-10-04"
        assert await narrowed.commit_count() == 4
    finally:
        narrowed.close()


# --------------------------------------------------------------------------- #
# arm 11: off-schema arguments
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("key", "value"),
    [("note", "put it on the company card"), ("card", "4111111111111111")],
)
async def test_an_off_schema_argument_is_refused_and_writes_nothing(key: str, value: str) -> None:
    """Arm 11 (ADR-0273 §2).

    *"It validates a booking's arguments against the declaration's own
    ``parameters_schema`` **before it writes**, and persists only the fields that schema
    names"*, so nothing a caller supplied off-schema is ever stored. **The count is
    asserted as well as the records**, which is arm 11's own rule for every pre-commit
    refusal: *"a count advanced before a refusal appends nothing and still corrupts the
    figure"*.

    **Driven at the callable and not through ``ActionRequest``, because the ordinary
    path refuses it one layer up.** ``ActionRequest`` runs ADR-0145's backstop, so a
    request carrying a key the schema does not name is *unconstructable* — which is a
    good fact about the system and not a substitute for this one. ``parameters_schema``
    is carried but **not enforced at selection** (ADR-0016 §7), and a call built by a
    bypass reaches the seam (ADR-0029 §2, ADR-0145 §3); §2 puts the obligation on the
    provider itself, so that is where it is asserted.

    **The refusal names a count and nothing else** (ADR-0145 §7, ADR-0152 §11): a key a
    caller chose is content, and the failure ``message`` is Tier 2 text.
    """
    booking = await configured()
    registry = registry_for(booking)
    seam = seam_for(booking, registry)
    parameters = arguments(IN_WINDOW)
    binding = await bound(seam, BOOKING_ACT, parameters)

    with pytest.raises(ClassifiedToolError) as caught:
        await booking.booking.implementation.invoke_bound(
            {**parameters, key: value}, idempotency_key=None, egress_binding=binding
        )

    assert caught.value.failure.kind is ToolFailureKind.INVALID_REQUEST
    assert caught.value.effect_may_have_committed is False
    assert SIMULATION_NOTICE in caught.value.failure.message
    assert key not in caught.value.failure.message
    assert value not in caught.value.failure.message
    assert await booking.store.records() == ()
    assert await booking.store.commit_count() == 0
    assert registry is not None  # the registry is built, and the bypass still refuses


# --------------------------------------------------------------------------- #
# arm 13: the provider deduplicates nothing
# --------------------------------------------------------------------------- #


async def test_two_separately_authorised_identical_bookings_append_two_records() -> None:
    """Arm 13 — what ``Idempotency.NONE`` declares (ADR-0273 §2, ADR-0016 §4).

    *"Arm 8 shows the system's effect claim stopping a repeat; this arm shows that
    **nothing but that claim would have**"*, which is the ground §2 states for ``NONE``
    and would otherwise go unestablished. The provider offers no deduplication
    guarantee, so ``KEYED`` would be a declaration of something untrue — and would hide
    ADR-0259 §2's effect claim, the guarantee M33 exists to demonstrate, behind the
    provider's own behaviour.
    """
    booking = await configured(retained_records=4)
    registry = registry_for(booking)
    seam = seam_for(booking, registry)

    _succeeded(await drive(registry, seam, BOOKING_ACT, arguments(), decision_id="d-1"))
    _succeeded(await drive(registry, seam, BOOKING_ACT, arguments(), decision_id="d-2"))

    records = await booking.store.records()
    assert len(records) == 2
    assert {one[DATE_ARGUMENT] for one in records} == {IN_WINDOW.isoformat()}
    assert await booking.store.commit_count() == 2


# --------------------------------------------------------------------------- #
# arm 14: two concurrent bookings
# --------------------------------------------------------------------------- #


async def test_two_concurrent_bookings_leave_two_records_and_advance_the_count_by_two() -> None:
    """Arm 14 (ADR-0273 §2's serialised, failure-atomic commit).

    **The count delta is asserted and not only the records**: *"a provider that inserts
    two records behind one increment passes the record half and fails this arm"*. Two
    calls enter the provider at once; each commit is one ``BEGIN IMMEDIATE``
    transaction under one lock, so they cannot interleave.
    """
    booking = await configured(retained_records=4)
    registry = registry_for(booking)
    seam = seam_for(booking, registry)

    results = await asyncio.gather(
        drive(registry, seam, BOOKING_ACT, arguments(date(2026, 10, 1)), decision_id="d-1"),
        drive(registry, seam, BOOKING_ACT, arguments(date(2026, 10, 2)), decision_id="d-2"),
    )

    for result in results:
        _succeeded(result)
    records = await booking.store.records()
    assert len(records) == 2
    assert {one[DATE_ARGUMENT] for one in records} == {"2026-10-01", "2026-10-02"}
    assert await booking.store.commit_count() == 2


# --------------------------------------------------------------------------- #
# arms 15 and 16: the commit boundary, and every injection point inside it
# --------------------------------------------------------------------------- #


class _FaultAt(SqliteBookingStore):
    """The real store with a fault injected at one named point of the commit.

    ADR-0273 §2 makes this class *"not ``@final``"* deliberately, for
    :class:`~ai_assistant.tools.connection_store.SqliteConnectionStore`'s reason: arms 15
    and 16 require a fault **before** the commit, **between each pair of the commit's
    sub-operations**, and **at or after** the commit itself, and a subclass overriding
    one method is how a case reaches those points **against the real implementation**.
    A duck-typed double would test a second store rather than this one.

    Each override does the real work **and then** raises, so the transaction has
    genuinely reached that point when the fault falls.
    """

    def __init__(self, *, path: Path | str, retained: int, at: str) -> None:
        """Arm the fault.

        Args:
            path: The store's path.
            retained: The record bound.
            at: One of ``"before"``, ``"after-insert"``, ``"after-advance"``,
                ``"after-prune"`` or ``"at-commit"``.
        """
        # **Armed after the store has opened, and that ordering is load-bearing.**
        # ADR-0273 §2's bound is enforced on the open path as well as the commit path,
        # so a store constructed with ``_prune`` already armed would raise while it was
        # being opened rather than while it was committing — and the case would assert
        # a fault it never injected where it meant to.
        self._at = ""
        super().__init__(path=path, retained=retained)
        self._at = at

    def _insert(self, conn: sqlite3.Connection, record: str) -> None:
        if self._at == "before":
            raise sqlite3.OperationalError("disk I/O error")
        super()._insert(conn, record)
        if self._at == "after-insert":
            raise sqlite3.OperationalError("disk I/O error")

    def _advance(self, conn: sqlite3.Connection) -> None:
        super()._advance(conn)
        if self._at == "after-advance":
            raise sqlite3.OperationalError("disk I/O error")

    def _prune(self, conn: sqlite3.Connection) -> None:
        super()._prune(conn)
        if self._at == "after-prune":
            raise sqlite3.OperationalError("disk I/O error")

    def _flush(self, conn: sqlite3.Connection, *, confirmed: bool = True) -> None:
        super()._flush(conn, confirmed=confirmed)
        if self._at == "at-commit":
            raise sqlite3.OperationalError("the commit's acknowledgement was lost")


async def _commit_with_fault(
    path: Path, at: str, *, retained: int = 2, day: date = IN_WINDOW
) -> BookingStoreError:
    """Commit one record through a store armed to fail at ``at``.

    Args:
        path: Where the store lives.
        at: The injection point.
        retained: The record bound this store is opened with. It matters because the
            bound is enforced on the **open** path as well, so a store reopened with a
            smaller one prunes before it commits anything.
        day: The day the interrupted booking names.

    Returns:
        The error the store raised.
    """
    store = _FaultAt(path=path, retained=retained, at=at)
    try:
        with pytest.raises(BookingStoreError) as caught:
            await store.commit({DATE_ARGUMENT: day.isoformat()})
    finally:
        store.close()
    return caught.value


@pytest.mark.parametrize("at", ["before", "after-insert", "after-advance", "after-prune"])
async def test_a_fault_before_the_commit_leaves_nothing_and_is_a_certain_failure(
    at: str, tmp_path: Path
) -> None:
    """Arms 15 and 16's *before* side, **one case per injection point**.

    *"§2's boundary is the commit or flush and never the first sub-operation"*: a fault
    falling before it whose rollback the store confirms reports
    ``effect_may_have_committed=False``, and the store reads back **across a restart**
    with no record and no advance. Arm 19's pessimism caveat is what forbids an
    indiscriminate ``True`` here.
    """
    path = tmp_path / "bookings.db"
    error = await _commit_with_fault(path, at)

    assert error.may_have_committed is False

    reopened = SqliteBookingStore(path=path, retained=2)
    try:
        assert await reopened.records() == ()
        assert await reopened.commit_count() == 0
    finally:
        reopened.close()


async def test_a_fault_at_the_commit_is_reported_as_one_that_may_have_landed(
    tmp_path: Path,
) -> None:
    """Arms 15 and 16's *at or after* side (ADR-0273 §2).

    *"A booking that may have happened is never recorded as certainly failed"*: that is
    the one state from which a later plan re-books with the corpus's own machinery
    agreeing it may. The store reads back **whole** across a restart, carrying the record
    and a count equal to the number of records ever inserted.
    """
    path = tmp_path / "bookings.db"
    error = await _commit_with_fault(path, "at-commit")

    assert error.may_have_committed is True

    reopened = SqliteBookingStore(path=path, retained=2)
    try:
        records = await reopened.records()
        assert len(records) == 1
        assert await reopened.commit_count() == 1
    finally:
        reopened.close()


async def test_the_commit_reads_back_whole_after_an_interruption_mid_sequence(
    tmp_path: Path,
) -> None:
    """Arm 15's third clause: the store carries **every record that preceded it**.

    Two bookings land, a third is interrupted at the commit boundary, and the store is
    reopened: three records and a count of three, because the interrupted one committed.
    *"The count equals the number of records ever inserted"* — not the number still
    retained, which pruning lowers.
    """
    path = tmp_path / "bookings.db"
    store = SqliteBookingStore(path=path, retained=4)
    await store.commit({DATE_ARGUMENT: "2026-10-01"})
    await store.commit({DATE_ARGUMENT: "2026-10-02"})
    store.close()

    await _commit_with_fault(path, "at-commit", retained=4, day=date(2026, 10, 3))

    reopened = SqliteBookingStore(path=path, retained=4)
    try:
        records = await reopened.records()
        assert [one[DATE_ARGUMENT] for one in records] == [
            "2026-10-01",
            "2026-10-02",
            "2026-10-03",
        ]
        assert await reopened.commit_count() == 3
    finally:
        reopened.close()


async def test_a_fault_before_the_commit_completes_the_step_failed_and_not_indeterminate(
    tmp_path: Path,
) -> None:
    """Arm 16's *"keyed to the commit itself and never to the injection point"*.

    Driven through the **seam**, so what is asserted is the ``ToolOutcome`` a deployment
    would record: ``FAILED`` for a fault the store rolled back, and never
    ``INDETERMINATE``. An arm reaching ``INDETERMINATE`` through a provider that could
    not have committed *"demonstrates a pessimistic misreport rather than an uncertain
    effect"*.
    """
    path = tmp_path / "bookings.db"
    booking = await configured(store_path=path)
    booking.store.close()
    object.__setattr__(
        booking.booking.implementation, "_store", _FaultAt(path=path, retained=2, at="before")
    )
    registry = registry_for(booking)
    seam = seam_for(booking, registry)

    result = await drive(registry, seam, BOOKING_ACT, arguments())

    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert result.output is None


# --------------------------------------------------------------------------- #
# arm 17: the four conditions, one case per condition
# --------------------------------------------------------------------------- #


async def test_a_binding_naming_another_connection_refuses_the_call() -> None:
    """Arm 17, condition 1 — the reference (ADR-0148 §6).

    *"The first is the one an implementation forgets."* The reference is compared
    **before** the record is read, because the record is read *by* the registration's
    reference: without it, a binding for account B's connection is checked against
    account A's record, and where the two share an identity both record checks pass.
    """
    booking = await configured()
    registry = registry_for(booking)
    seam = seam_for(booking, registry)
    parameters = arguments()
    binding = await bound(seam, BOOKING_ACT, parameters)
    elsewhere = binding.model_copy(
        update={"account": binding.account.model_copy(update={"reference": "conn-9999"})}
    )

    result = await recorded(registry, authorised(BOOKING_ACT, parameters, elsewhere))

    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.NOT_AUTHORISED
    assert await booking.store.commit_count() == 0


async def test_a_binding_naming_another_endpoint_refuses_the_call() -> None:
    """Arm 17, condition 2 — the endpoint (ADR-0148 §6).

    Compared as **text** before it is parsed, so two spellings of one host stay two
    endpoints: a call bound to an endpoint that merely resolves the same way is a call
    nobody wrote down.
    """
    booking = await configured()
    registry = registry_for(booking)
    seam = seam_for(booking, registry)
    parameters = arguments()
    binding = await bound(seam, BOOKING_ACT, parameters)
    elsewhere = binding.model_copy(update={"transport_endpoint": "https://other.example.invalid"})

    result = await recorded(registry, authorised(BOOKING_ACT, parameters, elsewhere))

    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.NOT_AUTHORISED
    assert await booking.store.commit_count() == 0


async def test_a_connection_that_is_no_longer_connectable_refuses_the_call() -> None:
    """Arm 17, condition 3 — connectability, read **at this moment** (ADR-0148 §6).

    The seam bound the call against an ``ACTIVE`` record; by the time the callable runs
    the provisioning state has moved. *"What M33 needs to see is the binding refusing a
    re-provisioned connection, and that refusal is reachable only because they run"*
    (ADR-0273 §3).
    """
    moving = Records(entry(), entry(state=ProvisioningState.PENDING, revision=2))
    booking = await configured(records=moving)
    registry = registry_for(booking)
    seam = seam_for(booking, registry)
    parameters = arguments()
    binding = await bound(seam, BOOKING_ACT, parameters)

    result = await recorded(registry, authorised(BOOKING_ACT, parameters, binding))

    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.NOT_AUTHORISED
    assert await booking.store.commit_count() == 0


async def test_a_record_recorded_for_another_identity_refuses_the_call() -> None:
    """Arm 17, condition 4 — the recorded identity (ADR-0148 §6).

    The account currently recorded for the bound reference is not the one the ruling was
    taken over, so nothing is asked under it.
    """
    booking = await configured(records=Records(entry(identity="someone-else@example.invalid")))
    registry = registry_for(booking)
    seam = seam_for(booking, registry, records=Records(entry()))
    parameters = arguments()
    binding = await bound(seam, BOOKING_ACT, parameters)

    result = await recorded(registry, authorised(BOOKING_ACT, parameters, binding))

    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.NOT_AUTHORISED
    assert await booking.store.commit_count() == 0


async def test_a_keyring_holding_nothing_under_the_recorded_slot_refuses_the_call() -> None:
    """The credential half of condition 3 — the slot **the record names**.

    A binding never carries a slot (ADR-0148 §6), so the provider reads under the one
    the record names and refuses where the keyring holds nothing there. The credential
    is read and **not used** (ADR-0273 §1), which is why both declarations state
    ``reads=(SECRET, …)`` — and why an empty keyring is still a refusal.
    """
    empty = await keyring(holds=None)
    booking = await configured(secrets=empty)
    registry = registry_for(booking)
    seam = seam_for(booking, registry)
    parameters = arguments()
    binding = await bound(seam, BOOKING_ACT, parameters)

    result = await recorded(registry, authorised(BOOKING_ACT, parameters, binding))

    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.NOT_AUTHORISED
    assert empty.reads == [SecretName(scope=SecretScope.INTEGRATION, key="conn-0001-r1")]
    assert await booking.store.commit_count() == 0


async def test_a_successful_call_reads_the_credential_it_does_not_use() -> None:
    """The other half of the same fact: the read happens on every call.

    ADR-0260 §12's *"accepts a credential and does not use it"* is a fact about the far
    end and changes nothing about ADR-0148 §6's conditions on this side — so
    ``reads=(SECRET, …)`` is true, and ``reads=()`` would be the silent no-reach claim
    ADR-0016 §1 makes the field required to prevent.
    """
    ring = await keyring()
    booking = await configured(secrets=ring)
    registry = registry_for(booking)
    seam = seam_for(booking, registry)

    _succeeded(await drive(registry, seam, BOOKING_ACT, arguments()))

    assert ring.reads == [SecretName(scope=SecretScope.INTEGRATION, key="conn-0001-r1")]


# --------------------------------------------------------------------------- #
# arm 19: the uncertain booking, told truthfully
# --------------------------------------------------------------------------- #


async def test_a_configured_uncertain_day_completes_indeterminate_and_the_flag_is_true(
    tmp_path: Path,
) -> None:
    """Arm 19 (ADR-0273 §4, ADR-0255 §6).

    *"The arm asserts the store afterwards: the flag the provider reported was **true of
    what it did**."* The configured day's commit **lands** and its outcome is then
    reported as unobtainable, so the record is present and the count advanced — which is
    what distinguishes an uncertain effect from the pessimistic misreport §4 rules out.

    The step completes ``INDETERMINATE`` because the declaration is ``side_effecting``
    and non-``NATURAL``, which makes ``interrupted_outcome`` ``INDETERMINATE``, and the
    provider reported ``effect_may_have_committed=True``. **This is the production
    component producing that state**, which is ADR-0260 §12's own rule applied here: an
    arm over a production component cannot assert what no production component can
    produce.
    """
    path = tmp_path / "bookings.db"
    result, booking = await _book(day=UNCERTAIN, store_path=path, indeterminate_date=UNCERTAIN)

    assert result.outcome is ToolOutcome.INDETERMINATE
    assert result.output is None
    assert result.failure is not None
    assert SIMULATION_NOTICE in result.failure.message

    records = await booking.store.records()
    assert len(records) == 1
    assert records[0][DATE_ARGUMENT] == UNCERTAIN.isoformat()
    assert await booking.store.commit_count() == 1


async def test_another_day_under_the_same_configuration_still_succeeds() -> None:
    """The uncertain day is **one** day, not a provider that always reports uncertainty.

    Stated because an implementation that reported ``True`` unconditionally would pass
    the case above and be exactly the pessimistic misreport arm 19 rules out.
    """
    result, booking = await _book(day=IN_WINDOW, indeterminate_date=UNCERTAIN)

    _succeeded(result)
    assert await booking.store.commit_count() == 1


async def test_a_failure_before_any_commit_is_failed_and_leaves_nothing() -> None:
    """Arm 19's *"separate arm"* (ADR-0273 §4, §10 arm 19).

    *"A configuration that fails **before** any commit … reports
    ``effect_may_have_committed=False``, leaving **no record and no count advance**, and
    completing ``FAILED`` rather than ``INDETERMINATE``."* The unavailable day is that
    configuration, and the contrast with the case above is the whole point: two
    outcomes, two truths, both produced by configuration alone.
    """
    result, booking = await _book(day=UNAVAILABLE, indeterminate_date=UNCERTAIN)

    assert result.outcome is ToolOutcome.FAILED
    assert await booking.store.records() == ()
    assert await booking.store.commit_count() == 0


# --------------------------------------------------------------------------- #
# arm 20: the honesty statement
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("day", [IN_WINDOW, UNAVAILABLE, AVAILABLE_FROM])
async def test_every_successful_availability_answer_carries_the_statement(day: date) -> None:
    """Arm 20's first half, over an available answer and an unavailable one (§6).

    *"Every successful output the simulated provider returns carries a field stating
    that no real reservation was made and no money moved — an availability answer and a
    booking alike."* It is carried by the record whether or not any surface renders it,
    so a trail, an export or an audit of a walkthrough is self-describing to a reader
    who was not present when the deployment was configured.
    """
    result, _ = await _answer(day=day)

    assert _succeeded(result)[SIMULATION_KEY] == SIMULATION_NOTICE


async def test_a_successful_booking_carries_the_statement() -> None:
    """Arm 20's first half at the act."""
    result, _ = await _book()
    output = _succeeded(result)

    assert output[SIMULATION_KEY] == SIMULATION_NOTICE
    assert output[BOOKED_KEY] is True
    assert output[CHARGED_AMOUNT_KEY] == PRICE
    assert output[CHARGED_CURRENCY_KEY] == CURRENCY


async def test_a_failure_this_provider_classifies_states_it_in_its_message() -> None:
    """Arm 20's second half (ADR-0273 §6, ADR-0039 §2).

    ``ToolResult`` refuses a non-``SUCCEEDED`` result carrying an ``output``, so the
    statement rides in the ``message`` — operator-facing **Tier 2** text, which admits
    it. **The obligation reaches no outcome the seam synthesised**: a deadline the seam
    completes and an escaping error it classifies carry no provider-authored text and
    are not required to.
    """
    unavailable, _ = await _book(day=UNAVAILABLE)

    assert unavailable.failure is not None
    assert SIMULATION_NOTICE in unavailable.failure.message


async def test_both_descriptions_say_the_provider_is_simulated() -> None:
    """§6's *"both declarations say it in their ``description``"*.

    ADR-0016 §1 makes ``description`` the one free-text field with two audiences — the
    model, and **the user, who is shown what they are approving**. So the statement
    reaches the user at the confirmation prompt, which is the one moment the approval
    design exists to serve, rather than on a page they may never open. *"Neither
    describes the tool as booking anything without that word."*
    """
    for definition in (BOOKING_AVAILABILITY, BOOKING_ACT):
        assert "simulated" in definition.description.lower()
        assert "no real reservation" in definition.description.lower()


def test_the_statement_is_keyed_on_by_nothing() -> None:
    """§6's *"that field is not a mechanism"*.

    *"No policy, criterion, comparison, disposition, validator or ``ToolDefinition``
    field is keyed on it, and no lane makes any behaviour conditional on it."* A
    component branching on it would be reading a provider's prose as a permission.
    Asserted over the tree: outside the module that writes it and the cases that read
    it, nothing under ``src/`` names the key at all.
    """
    from pathlib import Path  # noqa: PLC0415 — one case, one import

    source = Path(__file__).resolve().parents[2] / "src" / "ai_assistant"
    naming = sorted(
        path.relative_to(source).as_posix()
        for path in source.rglob("*.py")
        if SIMULATION_KEY in path.read_text(encoding="utf-8")
    )

    assert naming == ["tools/booking.py"]


# --------------------------------------------------------------------------- #
# arm 21: one configuration answers identically, on every call and across a restart
# --------------------------------------------------------------------------- #


class _MovingDate(date):
    """A ``date`` whose ``today`` moves a day every time it is read.

    Arm 21 is driven *"with the ambient clock and any ambient random source
    deliberately moved between the three readings"* — the waived-at-ratification item
    PR #2495 assigns to this lane. A provider consulting a clock it was not given would
    answer differently across the three readings and fail the arm; one that reads only
    its configuration cannot.

    A subclass rather than a stub, so ``date.fromisoformat`` and every ``isinstance``
    check in the module under test go on working while ``today`` moves.
    """

    _reads = 0

    @classmethod
    def today(cls) -> _MovingDate:
        """The moving reading; see the class docstring."""
        cls._reads += 1
        moved = date(2026, 1, 1) + timedelta(days=cls._reads)
        return cls(moved.year, moved.month, moved.day)


async def test_one_configuration_answers_identically_on_every_call_and_after_a_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Arm 21, with the ambient clock and the ambient random source moved (§5).

    *"An implementation reading a clock it was not given, or a random source, still
    returns its fixture's expected value inside a single run, passes every other arm,
    and leaves the M33 walkthrough irreproducible."* So the two ambient sources are
    **moved between the three readings**: the module's own ``date`` and ``datetime``
    names are replaced by ones that cross a day boundary on every read, and the process
    random seed is changed. The third reading is taken against a provider
    **reconstructed from the same configuration**, which is what makes this a statement
    about the configuration rather than about one object's memory.
    """
    import random  # noqa: PLC0415 — the ambient source this arm moves

    from ai_assistant.tools import booking as module  # noqa: PLC0415 — the module under test

    monkeypatch.setattr(module, "date", _MovingDate)

    path = tmp_path / "bookings.db"
    # Configured as ISO **strings**, so the patched ``date`` above is what parses them:
    # a plain ``date`` handed in would not be an instance of the subclass, and the
    # factory would refuse it — an artefact of the arrangement rather than of the
    # provider.
    first_day = AVAILABLE_FROM.isoformat()
    last_day = date(2026, 10, 7).isoformat()
    booking = await configured(store_path=path, available_from=first_day, available_to=last_day)
    registry = registry_for(booking)
    seam = seam_for(booking, registry)

    random.seed(1)
    first = _succeeded(
        await drive(registry, seam, BOOKING_AVAILABILITY, arguments(), decision_id="r-1")
    )
    random.seed(2)
    second = _succeeded(
        await drive(registry, seam, BOOKING_AVAILABILITY, arguments(), decision_id="r-2")
    )
    booking.store.close()

    random.seed(3)
    rebuilt = await configured(store_path=path, available_from=first_day, available_to=last_day)
    rebuilt_registry = registry_for(rebuilt)
    third = _succeeded(
        await drive(
            rebuilt_registry, seam_for(rebuilt, rebuilt_registry), BOOKING_AVAILABILITY, arguments()
        )
    )
    rebuilt.store.close()

    assert first == second == third
    assert _MovingDate._reads == 0, "the provider read a clock it was not given"


async def test_the_charge_does_not_vary_with_the_commit_count(tmp_path: Path) -> None:
    """Arm 21's charge half (the same waived item).

    *"The booking's ``charged_output`` is read under the same repetition so a charge
    varying with the commit count fails too."* Three bookings against one configuration
    report one charge, though the count rises under them — which is what makes the
    walkthrough's money path reproducible rather than merely deterministic-looking on
    its first run.
    """
    path = tmp_path / "bookings.db"
    booking = await configured(store_path=path, retained_records=4)
    registry = registry_for(booking)
    seam = seam_for(booking, registry)

    charges = []
    for index, day in enumerate(date(2026, 10, day) for day in (1, 2, 3)):
        output = _succeeded(
            await drive(registry, seam, BOOKING_ACT, arguments(day), decision_id=f"d-{index}")
        )
        charge = charge_read(BOOKING_ACT, output)
        assert charge is not None
        charges.append((charge.amount, charge.currency))

    assert charges == [(Decimal(PRICE), CURRENCY)] * 3
    assert await booking.store.commit_count() == 3


def test_a_step_failure_records_the_providers_own_kind() -> None:
    """``StepFailure`` keeps the tool's own classification (ADR-0039 §3).

    Stated here because ADR-0273 §6's statement rides in a ``ToolFailure.message``, and
    what a finished step keeps is that failure's ``kind`` beside the text — not a
    planning-owned mirror of it. A reader of a trail therefore sees both.
    """
    failure = StepFailure(kind=ToolFailureKind.REFUSED, message=f"no stay. {SIMULATION_NOTICE}")

    assert failure.kind is ToolFailureKind.REFUSED
    assert SIMULATION_NOTICE in failure.message


def test_the_reference_is_the_one_the_harness_configures() -> None:
    """A guard on the arrangement itself, so a renamed constant fails loudly."""
    assert REFERENCE == "conn-0001"


# --------------------------------------------------------------------------- #
# arm 19's second half: the reconciliation pass passes over it
# --------------------------------------------------------------------------- #


class _RecordingInvoker:
    """A ``ToolInvoker`` that records what it was asked to run and runs nothing.

    Arm 19 asserts that ADR-0259 §4's pass *"invokes the provider **not at all**"*, and
    that is a claim about a call which did **not** happen — only a recording subject can
    distinguish it from one whose result was discarded.
    """

    def __init__(self) -> None:
        """Start having been asked nothing."""
        self.calls: list[tuple[ToolCall, timedelta]] = []

    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam's own signature, which this double stands in for
        """Record the call and refuse to run it.

        Args:
            call: What the reconciliation asked for.
            timeout: The deadline it offered.

        Raises:
            AssertionError: Always — reaching here is the failure this arm is about.
        """
        self.calls.append((call, timeout))
        msg = "ADR-0259 §4's pass reached the provider, which arm 19 forbids"
        raise AssertionError(msg)


async def test_an_indeterminate_booking_is_passed_over_and_left_standing(
    tmp_path: Path,
) -> None:
    """Arm 19's third clause (ADR-0259 §3, §4; ADR-0273 §4).

    *"ADR-0259 §4's reconciliation pass is run over that ``INDETERMINATE`` step,
    asserting that it **invokes the provider not at all**, leaves the provider's durable
    state — the record and the count alike — **exactly as the interrupted commit left
    it**, and leaves the step standing ``INDETERMINATE``."*

    The ground is ADR-0259 §3's conjunction, and the booking fails **both** limbs: it is
    ``side_effecting`` and its decision carries an ``egress_binding``. So no
    reconciliation lookup is declared on either definition and none can be — *"no
    ``ToolDefinition`` field is added to say so"* — and the step's status remains *"the
    authoritative record of the uncertainty"* (ADR-0255 §6).

    **That pass's act 3 moves the *attempt* to ``EFFECT_UNRESOLVED``, which is its own
    repair and not a resolution of the effect**, so this case asserts the step's status
    and the store rather than the attempt's state.
    """
    path = tmp_path / "bookings.db"
    booking = await configured(store_path=path, indeterminate_date=UNCERTAIN)
    registry = registry_for(booking)
    seam = seam_for(booking, registry)
    parameters = arguments(UNCERTAIN)
    binding = await bound(seam, BOOKING_ACT, parameters)

    uncertain = await drive(registry, seam, BOOKING_ACT, parameters)
    assert uncertain.outcome is ToolOutcome.INDETERMINATE
    left_behind = await booking.store.records()
    left_count = await booking.store.commit_count()

    plans = FakePlanStore(now=lambda: DECIDED_AT)
    trail = FakeAuditTrail()
    invoker = _RecordingInvoker()
    await plans.save_goal(
        Goal(
            id="g-1",
            interpretation=(
                GoalInterpretation(
                    revision=1,
                    outcome="book the stay",
                    outcome_ground=Ground.USER_STATED,
                    outcome_span="book the stay",
                    recorded_at=DECIDED_AT,
                    raised_by="t-1",
                ),
            ),
            provenance=Provenance(
                source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=DECIDED_AT
            ),
            created_at=DECIDED_AT,
        )
    )
    step = PlanStep(
        id="s-book",
        intent="book it",
        capability=BOOKING_ACT.capability,
        parameters=parameters,
    )
    plan = ActionPlan(
        id="p-1", goal_id="g-1", steps=(step,), created_at=DECIDED_AT, targets_revision=1
    )
    await plans.save_plan(plan)
    state = await plans.start_execution(plan.id)
    await plans.open_attempt(
        GoalAttempt(
            id="a-1",
            goal_id="g-1",
            opened_at=DECIDED_AT,
            plan_ids=(plan.id,),
            execution_ids=(state.id,),
            state=AttemptState.RUNNING,
        )
    )
    request = ActionRequest(
        tool=BOOKING_ACT,
        parameters=parameters,
        goal="g-1",
        step_id=step.id,
        execution_id=state.id,
        egress_binding=binding,
    )
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="the user confirmed the booking"),
        id="d-recon",
        decided_at=DECIDED_AT,
    )
    await trail.record(decision)
    state = await plans.commit_transition(
        StepTransition(
            execution_id=state.id,
            step_id=step.id,
            to_status=StepStatus.RUNNING,
            expected_version=state.version,
            bound_tool=BOOKING_ACT.id,
            approval_ref=decision.id,
            attempt_id="a-1",
        )
    )
    state = await plans.commit_transition(
        StepTransition(
            execution_id=state.id,
            step_id=step.id,
            to_status=StepStatus.INDETERMINATE,
            expected_version=state.version,
            failure=StepFailure(message="the booking's outcome was never confirmed", kind=None),
        )
    )

    stage = ReconciliationStage(plans=plans, trail=trail, invoker=invoker, monotonic=lambda: 0.0)
    reconciled = await stage.run("g-1", remaining=stage.opened(timedelta(seconds=30)))

    assert invoker.calls == []
    assert reconciled.uncertain == (step.id,)
    assert reconciled.established == ()
    held = await plans.get_execution(state.id)
    assert held is not None
    record = held.step(step.id)
    assert record is not None
    assert record.status is StepStatus.INDETERMINATE
    assert await booking.store.records() == left_behind
    assert await booking.store.commit_count() == left_count


def test_neither_declaration_offers_a_reconciliation_lookup() -> None:
    """§4: *"no reconciliation lookup is declared on either definition and none can
    be"*.

    ADR-0259 §3's reconcilable test is *not ``side_effecting``* **and** *no
    ``egress_binding``*, and that section rules that *"no ``ToolDefinition`` field is
    added to say so: the existing declarations are that test already"*. So the absence
    is asserted over the declaration's own field set — a lane that added one would fail
    this rather than merely contradict §4.
    """
    reconciliation_fields = [
        name for name in type(BOOKING_ACT).model_fields if "reconcil" in name or "lookup" in name
    ]

    assert reconciliation_fields == []
    assert BOOKING_ACT.side_effecting is True


def test_the_module_names_no_clock_and_no_random_source() -> None:
    """Arm 21's mechanical half (ADR-0273 §5).

    *"It consults no clock it was not given, no random source, no file it was not
    configured with and no network."* The behavioural half is the case above — three
    equal readings with the ambient clock moved under them — and this is the half that
    catches a reader the three readings happened not to expose: the module's own source
    names none of these at all, so there is nothing for a later edit to reach through.

    ``date`` is imported for parsing and comparison and is deliberately not among the
    refused names; what is refused is **reading** one — ``today``, ``now``, ``utcnow``,
    ``time`` and every ``random`` entry point.
    """
    import ast  # noqa: PLC0415 — one case, one import
    from pathlib import Path  # noqa: PLC0415

    forbidden = {"today", "now", "utcnow", "monotonic", "perf_counter", "random", "urandom"}
    source = Path(__file__).resolve().parents[2] / "src" / "ai_assistant" / "tools" / "booking.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    named = {
        node.attr if isinstance(node, ast.Attribute) else node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute | ast.Name)
    }

    assert named & forbidden == set()
