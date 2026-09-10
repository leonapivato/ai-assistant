"""The three destination-trust operations (ADR-0242 §1, §2, §4).

Every arm here drives the **production** operations object over the canonical stores,
which is §15's own bar: "over the production engine, the production servicing path and
the production renderers, and not over a restatement of the rule in a test double".

**What is deliberately not here.** The store's own two added arms — that ``record``
raises :class:`~ai_assistant.core.errors.DuplicateDestinationTrustError` on a live
duplicate and the base class on the other two grounds — are owed **at the conformance
suite** (§13) and are in ``tests/permissions/destination_trust_store_contract.py``,
because a store raising the base class there "would pass every engine test against a
different store and still make §5's *already chosen* rendering unreachable".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.errors import (
    DuplicateDestinationTrustError,
    PlanningError,
    UntrustableDestinationError,
)
from ai_assistant.core.types import (
    BoundAccount,
    CostBasis,
    DestinationProtocol,
    DestinationTrust,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    Idempotency,
    OriginUnrecordedBinding,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    SpanCoverage,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.orchestration.destination_trust import DestinationTrustOperations
from ai_assistant.testing import FakeAuditTrail, FakeDestinationTrustStore

if TYPE_CHECKING:
    from collections.abc import Sequence

_AT: Final = datetime(2026, 5, 1, 9, tzinfo=UTC)
_ACCOUNT: Final = BoundAccount(identity="work@example.com", reference="conn-0001")
_ENDPOINT: Final = "smtp://mail.example.com:587"
_DIGEST: Final = "d" * 64


def _tool() -> ToolDefinition:
    """A declaration of the shape a recorded egress ruling embeds verbatim."""
    return ToolDefinition(
        id="smtp",
        capability="send_email",
        description="Send an email.",
        risk_level=RiskLevel.LOW,
        reversibility=Reversibility.REVERSIBLE,
        side_effecting=True,
        reads=(),
        writes=(),
        discloses=(),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NATURAL,
    )


def _span() -> EgressSpan:
    """One occurrence of the payload description, naming one recipient."""
    return EgressSpan(
        argument="to",
        index=0,
        provenance=DiscloserProvenance.SYSTEM_SELECTED,
        extent=13,
        destination=EgressDestination(
            protocol=DestinationProtocol.SMTP,
            supplied="a@example.com",
            canonical="a@example.com",
        ),
    )


def _binding(*, planned: bool) -> EgressBinding:
    """A whole binding of the shape a live ``send_email`` ruling records."""
    return EgressBinding(
        spans=(_span(),),
        account=_ACCOUNT,
        transport_endpoint=_ENDPOINT,
        planned_with_external_content=planned,
        coverage=SpanCoverage.NOT_COVERED,
    )


def _legacy_binding() -> OriginUnrecordedBinding:
    """The same facts from a row recorded before ADR-0181 §3 existed.

    Constructed directly, which is the only way to reach it: ADR-0184 §4 makes
    ``AuditTrail.record`` refuse the shape and ``PermissionDecision.from_request``
    unable to produce it, so it is only ever read out of a store.
    """
    return OriginUnrecordedBinding(spans=(_span(),), account=_ACCOUNT, transport_endpoint=_ENDPOINT)


def _decision(
    decision_id: str,
    *,
    outcome: PermissionOutcome = PermissionOutcome.ALLOW,
    binding: EgressBinding | OriginUnrecordedBinding | None = None,
    at: datetime | None = None,
    resolves: str | None = None,
) -> PermissionDecision:
    """One recorded ruling, built field by field.

    Hand-constructed rather than routed through ``from_request``, because the legacy
    row above cannot be produced through the factory at all and building the two
    different ways would make a comparison between them a comparison of two builders.
    """
    return PermissionDecision(
        id=decision_id,
        ruling=PermissionRuling(outcome=outcome, reason="within policy"),
        tool=_tool(),
        parameters_digest=_DIGEST,
        decided_at=at if at is not None else _AT,
        egress_binding=binding,
        resolves=resolves,
    )


class _SeededTrail(FakeAuditTrail):
    """A trail holding exactly the rows a case seeds, refusals included.

    ``FakeAuditTrail`` is otherwise untouched, so what the operations read is the
    canonical fake's own behaviour. The seeding is a *field* rather than a sequence of
    ``record`` calls because ADR-0184 §4 makes ``record`` refuse an
    :class:`~ai_assistant.core.types.OriginUnrecordedBinding` outright — that row is only
    ever read out of a store, and reading one is exactly what ADR-0242 §1's second
    condition is about.
    """

    def __init__(self, decisions: Sequence[PermissionDecision] = ()) -> None:
        super().__init__()
        self._seeded = {decision.id: decision for decision in decisions}

    async def get(self, decision_id: str) -> PermissionDecision | None:
        """The seeded row, or whatever the trail itself holds."""
        seeded = self._seeded.get(decision_id)
        return seeded if seeded is not None else await super().get(decision_id)

    async def export(self) -> list[PermissionDecision]:
        """The seeded rows and the recorded ones, so a case can assert nothing was added."""
        return [*self._seeded.values(), *await super().export()]


def _operations(
    *decisions: PermissionDecision,
    store: FakeDestinationTrustStore | None = None,
) -> tuple[DestinationTrustOperations, FakeDestinationTrustStore, _SeededTrail]:
    """The production operations over the canonical stores, seeded with ``decisions``."""
    held = FakeDestinationTrustStore() if store is None else store
    recorded = _SeededTrail(decisions)
    ids = iter(f"t-{index}" for index in range(1, 100))
    return (
        DestinationTrustOperations(
            store=held, trail=recorded, id_factory=lambda: next(ids), clock=lambda: _AT
        ),
        held,
        recorded,
    )


# --- §1: the three availability conditions, each with nothing written --------


async def test_a_decision_the_trail_does_not_hold_is_refused() -> None:
    """§1's first condition: "the trail holds a decision with that id"."""
    operations, store, _ = _operations()

    with pytest.raises(UntrustableDestinationError, match="no decision"):
        await operations.establish_destination_trust("d-nothing")

    assert await store.export() == []


async def test_a_decision_with_no_binding_is_refused() -> None:
    """§1's second condition, on the ``None`` case.

    ``None`` means the request was not an egress call at all (ADR-0150 §1), so there is
    no destination set for the record to be over — the act has no subject rather than a
    subject it may not take.
    """
    operations, store, _ = _operations(_decision("d-1", binding=None))

    with pytest.raises(UntrustableDestinationError, match="no whole egress binding"):
        await operations.establish_destination_trust("d-1")

    assert await store.export() == []


async def test_a_decision_with_an_origin_unrecorded_binding_is_refused() -> None:
    """§1's second condition, on the shape it names by type.

    An :class:`~ai_assistant.core.types.OriginUnrecordedBinding` is a row written before
    ADR-0181 §3 existed, read out of the trail and never minted. §1 refuses it in terms —
    "never ``None``, never an ``OriginUnrecordedBinding``, never a
    ``CoverageUnrecordedBinding``" — because its ``planned_with_external_content`` is not
    on the row at all, so the third condition could not be decided over it.
    """
    operations, store, _ = _operations(_decision("d-1", binding=_legacy_binding()))

    with pytest.raises(UntrustableDestinationError, match="no whole egress binding"):
        await operations.establish_destination_trust("d-1")

    assert await store.export() == []


async def test_a_decision_planned_over_external_content_is_refused() -> None:
    """§1's third condition, and the one this act keeps of ADR-0235 §3's seven.

    "Trusting a destination a model reached *from* external content is the loop closing
    on itself": an injected page names a destination, the planner plans a call to it, the
    call is refused and recorded, and the recorded row is then offered to the user as
    something to trust. It is refused **at this operation** rather than left to the
    store, because ``DestinationTrustStore.record`` does not consult a binding and could
    not — ADR-0238 §1's five fields carry no tool, no account and no call.
    """
    operations, store, _ = _operations(
        _decision("d-1", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=True))
    )

    with pytest.raises(UntrustableDestinationError, match="recorded external content"):
        await operations.establish_destination_trust("d-1")

    assert await store.export() == []


async def test_the_first_failing_condition_is_the_one_named() -> None:
    """§1: "where more than one fails the first in the order above is the one named".

    Deterministic across implementations, which is what makes reading the outcome from
    the type safe: a surface that saw a different condition named per engine would be
    reading a coincidence.
    """
    operations, _, _ = _operations()

    with pytest.raises(UntrustableDestinationError) as refused:
        await operations.establish_destination_trust("d-absent")

    assert "no decision" in str(refused.value)


# --- §1: what is *not* a condition, and why -----------------------------------


@pytest.mark.parametrize(
    "outcome", [PermissionOutcome.ALLOW, PermissionOutcome.DENY, PermissionOutcome.CONFIRM]
)
async def test_the_decisions_ruling_is_not_a_condition(outcome: PermissionOutcome) -> None:
    """§1: "The decision's **ruling** … is **not** a condition of this act".

    ADR-0235 §3's conditions over those fields exist because that act *seeks a ruling and
    records an answer*; this act seeks no ruling, records no answer, sends nothing and
    services nothing.
    """
    operations, store, _ = _operations(
        _decision("d-1", outcome=outcome, binding=_binding(planned=False))
    )

    record = await operations.establish_destination_trust("d-1")

    assert record.trust is DestinationTrust.USER_CHOSEN
    assert [held.id for held in await store.live()] == [record.id]


async def test_the_act_succeeds_on_a_decision_whose_confirmation_was_answered() -> None:
    """§15: "the ordering trap §1 exists to close".

    A user may record trust from a decision they answered a month ago — which is exactly
    what keeps the act reachable **after** the grant act has taken the row out of
    ``grantable_decisions`` (ADR-0235 §3's fourth condition). An implementation that
    reused that listing's availability set would be unreachable for every user who
    granted first, which is the order the listing's own next-step line teaches.
    """
    answered = _decision("d-1", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=False))
    resolution = _decision(
        "d-2", outcome=PermissionOutcome.ALLOW, binding=_binding(planned=False), resolves="d-1"
    )
    operations, store, _ = _operations(answered, resolution)

    record = await operations.establish_destination_trust("d-1")

    assert [held.id for held in await store.live()] == [record.id]


async def test_an_expired_decision_is_still_a_subject_of_the_act() -> None:
    """§1: ``expires_at`` is not a condition either, and no lane adds it.

    "There is no confirmation to answer once, no park to keep apart from history and no
    lifetime to be inside."
    """
    stale = _decision(
        "d-1",
        outcome=PermissionOutcome.CONFIRM,
        binding=_binding(planned=False),
        at=_AT - timedelta(days=90),
    )
    operations, store, _ = _operations(stale)

    record = await operations.establish_destination_trust("d-1")

    assert record.established_at == _AT
    assert [held.id for held in await store.live()] == [record.id]


# --- §1, §2: what the record carries, and what no caller can substitute -------


async def test_the_destination_set_is_transcribed_from_the_binding_by_value() -> None:
    """§1: the set is ``core``'s own derivation, "transcribed by value".

    No surface accepts a destination the user typed, parses a host, builds a
    ``CanonicalDestination`` or constructs a set of its own — ADR-0235 §4's clause read
    one act over, and ADR-0021 §3's move of removing the capability rather than
    forbidding it. The operation takes one argument, so there is no parameter through
    which a subject could be substituted.
    """
    binding = _binding(planned=False)
    operations, _, _ = _operations(
        _decision("d-1", outcome=PermissionOutcome.CONFIRM, binding=binding)
    )

    record = await operations.establish_destination_trust("d-1")

    assert record.destinations == binding.canonical_destination_set
    assert record.trust is DestinationTrust.USER_CHOSEN
    assert record.revoked_at is None


async def test_the_record_carries_no_expiry() -> None:
    """§2: "The record carries **no expiry**, and no surface offers one."

    "This is a real asymmetry with ``RecipientGrant`` and it is stated rather than
    smoothed over": a recipient grant ends at an instant the user chose, and destination
    trust ends when the user revokes it. §14 defers an expiring record with its trigger.
    """
    operations, _, _ = _operations(
        _decision("d-1", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=False))
    )

    record = await operations.establish_destination_trust("d-1")

    assert "expires_at" not in type(record).model_fields
    assert record.revoked_at is None


async def test_the_act_writes_no_decision_and_seeks_no_ruling() -> None:
    """§11: "The establishing act records no ``PermissionDecision`` … and emits no audit
    event."

    It sends nothing, so there is no egress to rule on and nothing for the permission
    trail to hold; **the record itself is the audit**.
    """
    seeded = _decision("d-1", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=False))
    operations, _, trail = _operations(seeded)

    await operations.establish_destination_trust("d-1")

    assert [row.id for row in await trail.export()] == ["d-1"]


async def test_a_second_act_over_one_live_set_is_refused_as_a_duplicate() -> None:
    """§2, §15: ``DuplicateDestinationTrustError`` is raised and reaches the caller.

    The one ground on which the user's recourse is *no act at all* — what they asked for
    is already true — and the discriminator exists so that a surface reads it from the
    **type** rather than by parsing a message or taking a read-back.
    """
    operations, store, _ = _operations(
        _decision("d-1", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=False)),
        _decision("d-2", outcome=PermissionOutcome.ALLOW, binding=_binding(planned=False)),
    )
    await operations.establish_destination_trust("d-1")

    with pytest.raises(DuplicateDestinationTrustError):
        await operations.establish_destination_trust("d-2")

    assert len(await store.live()) == 1


# --- §4: the listing and the revocation ---------------------------------------


async def test_the_standing_listing_is_the_stores_live_set_and_nothing_else() -> None:
    """§4: ``live``, in the store's own order, composing and filtering nothing."""
    operations, _, _ = _operations(
        _decision("d-1", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=False))
    )
    record = await operations.establish_destination_trust("d-1")

    assert await operations.standing_destination_trust() == (record,)


async def test_revoking_a_live_record_answers_true_and_takes_it_out_of_the_listing() -> None:
    """§4: ``revoke`` with the instant of the user's act, then ``True``."""
    operations, store, _ = _operations(
        _decision("d-1", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=False))
    )
    record = await operations.establish_destination_trust("d-1")

    assert await operations.revoke_destination_trust(record.id) is True
    assert await operations.standing_destination_trust() == ()
    [held] = await store.export()
    assert held.revoked_at == _AT


@pytest.mark.parametrize("known", [False, True])
async def test_revoking_an_unknown_or_already_revoked_id_answers_false_and_writes_nothing(
    known: bool,
) -> None:
    """§4, §15: ``False`` for an unknown id **and** for one already revoked.

    "``False`` is the honest answer to a caller arriving after the record is gone — by
    the time that call completes the store holds no live record with that id, which is
    exactly what ``False`` means here — and **the user's recourse succeeded**." No lane
    retries, revokes twice, or reports the loss as a fault.
    """
    operations, store, _ = _operations(
        _decision("d-1", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=False))
    )
    record = await operations.establish_destination_trust("d-1")
    if known:
        await operations.revoke_destination_trust(record.id)
    before = await store.export()

    assert await operations.revoke_destination_trust(record.id if known else "t-99") is False

    assert await store.export() == before


async def test_a_revocation_rewrites_no_recorded_decision() -> None:
    """§4: revocation is **prospective** and rewrites no recorded decision.

    "A search already ruled ``ALLOW`` stays ruled and a record already supplied to a
    composer is not retracted" (ADR-0238 §1, on ADR-0193 §9's shape).
    """
    allowed = _decision("d-9", outcome=PermissionOutcome.ALLOW, binding=_binding(planned=False))
    operations, _, trail = _operations(
        _decision("d-1", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=False)),
        allowed,
    )
    record = await operations.establish_destination_trust("d-1")

    await operations.revoke_destination_trust(record.id)

    assert await trail.get("d-9") == allowed


# --- ADR-0026: the clock the act reads ----------------------------------------


async def test_a_non_conforming_clock_reading_is_the_stages_own_error() -> None:
    """ADR-0026 §2, §4: guarded at the store, translated to the stage's error.

    ``core/errors.py`` defines no error for `orchestration`, so the failure belongs to
    the **stage** — ``RecipientGrantOperations``' own translation, one act over.
    """
    operations = DestinationTrustOperations(
        store=FakeDestinationTrustStore(),
        trail=_SeededTrail(
            [_decision("d-1", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=False))]
        ),
        id_factory=lambda: "t-1",
        clock=lambda: datetime(2026, 5, 1, 9),  # noqa: DTZ001 — naive on purpose
    )

    with pytest.raises(PlanningError, match="non-conforming"):
        await operations.establish_destination_trust("d-1")


# --- §9's recovery journey, and the eligibility it states at the predicate's
#     own strength -----------------------------------------------------------


async def test_a_clean_footing_is_eligible_even_where_records_were_retrieved() -> None:
    """§15: eligibility is the **recorded predicate's** strength and no higher.

    A decision whose binding carries ``planned_with_external_content`` ``False`` **is**
    an eligible subject "even where the request was planned over retrieved records —
    none of them carrying the marker". ADR-0181 §6's second clause is why: ``False`` is
    rendered as no assurance, so the statement §9 fixes does **not** say the request was
    composed from the user's own words alone — and a surface that sent a user looking
    for that narrower population "would send them past the row that qualifies".

    The predicate is the binding's own field and the act reads nothing else: there is no
    second condition here about how many records were in view, where they came from, or
    whether any were retrieved at all.
    """
    operations, store, _ = _operations(
        _decision("d-1", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=False))
    )

    record = await operations.establish_destination_trust("d-1")

    assert [held.id for held in await store.live()] == [record.id]


async def test_the_earlier_resolved_decision_is_the_subject_the_journey_ends_on() -> None:
    """§9's recovery journey, at the point where the two listings differ.

    The decision recording a ``TRUST_MISSING`` refusal carries
    ``planned_with_external_content`` ``True``, so ADR-0235 §3's seventh condition
    excludes it from ``grantable_decisions`` **and** ADR-0242 §1's third condition
    excludes it from the trust act; and the earlier decision the user granted from has
    been **resolved**, so §3's fourth condition has taken it out of that listing too.
    "``assistant remember-recipients`` can therefore be empty at exactly the moment its
    guidance is followed."

    What makes the journey end anywhere is that the act is **indifferent to a decision's
    ruling and resolution** (§1), so the earlier resolved row is still a valid subject —
    which is what ``assistant decisions``, ADR-0186 §1's bounded read of the whole
    trail, can hand back and the other listing cannot.
    """
    earlier = _decision("d-1", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=False))
    answer = _decision(
        "d-2", outcome=PermissionOutcome.ALLOW, binding=_binding(planned=False), resolves="d-1"
    )
    refusal = _decision("d-3", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=True))
    operations, store, _ = _operations(earlier, answer, refusal)

    with pytest.raises(UntrustableDestinationError, match="recorded external content"):
        await operations.establish_destination_trust("d-3")
    record = await operations.establish_destination_trust("d-1")

    assert [held.id for held in await store.live()] == [record.id]


async def test_a_trail_whose_only_decision_is_external_offers_the_act_on_nothing() -> None:
    """§9: "**The statement promises no eligible decision**", and this is the deployment.

    Where a deployment's *first* search is planned over external content — a retrieved
    record marked as resting on recorded external content is enough, and ADR-0181 §1
    keeps that class wider than a prior search — the trail's only decision is the one
    recording that refusal, and §1's third condition forbids the act on it. So a
    statement promising an available id would be false on exactly this deployment, which
    is why §9's says where to look and what to look for and asserts nothing about what is
    there. The statement's own half is asserted over the rendered bytes in
    ``tests/interfaces/test_cli_destination_trust.py``.
    """
    operations, store, _ = _operations(
        _decision("d-1", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=True))
    )

    with pytest.raises(UntrustableDestinationError, match="recorded external content"):
        await operations.establish_destination_trust("d-1")

    assert await store.export() == [], "nothing was written, and there is nothing to perform yet"
