"""What ADR-0260 §13's L3 arms are driven over: a real binder, a real policy, one fake.

**The subject of every arm under this heading is production**: ``service_read_request``,
:class:`~ai_assistant.orchestration.reads.ForecastServicer`, the
:class:`~ai_assistant.tools.egress_binder.EgressBindingSeam` that derives the binding,
and the :class:`~ai_assistant.permissions.ThresholdActionPolicy` that rules on it. What
is faked is the **seam beyond** them — the provider — which is
:class:`~ai_assistant.testing.FakeForecaster`, the canonical fake ADR-0260 §12 lands
beside the contract. §13's preamble governs assertions about the *forecaster*, and every
one of those is L1's; what is asserted here is what the **servicing** does with the
seam's answers.

**The real binding seam and not the canonical fake binder**, deliberately. ADR-0260 §11
puts ``forecast_reach`` on ``CarriedProvenance`` and ADR-0272 §1 makes the trail refuse a
binding carrying neither that fact nor ``closed_loop``, so a harness whose binder dropped
the field would take **no** route (c) and turn every arm below into an assertion about a
``RULING_CONFIRM``. §13's arm (m) also says its fact is "asserted over the binding
itself", which only a derived binding can answer.

**The forecast declaration is registered at the egress seam and in no ``ToolRegistry``**
(ADR-0260 §1), which is why :class:`_NoDefinitions` holds nothing: the seam's
registry-original comparison is not reached, and a harness handing it a registry holding
the declaration would arrange a state the design forbids.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, final

from ai_assistant.core.types import (
    ActionPlan,
    BoundAccount,
    CanonicalDestination,
    CostBasis,
    DestinationProtocol,
    Goal,
    GoalBrief,
    GoalInterpretation,
    Ground,
    MemorySource,
    Placement,
    Provenance,
    ProvisioningState,
    ReadAsk,
    ReadKind,
    ReadRequest,
    SecretName,
    SecretScope,
    SemanticMemory,
    ToolCost,
)
from ai_assistant.orchestration.reads import ForecastServicer
from ai_assistant.permissions import ConfiguredForecastDestination, ThresholdActionPolicy
from ai_assistant.testing import (
    DEFAULT_FORECAST_ORIGIN,
    FAKE_FORECAST_READ,
    FakeAuditTrail,
    FakeForecaster,
    FakeRecipientGrants,
)
from ai_assistant.tools.connection_store import ConnectionEntry, StoredEntry
from ai_assistant.tools.egress_binder import (
    EgressBindingSeam,
    EgressRegistration,
    RegistrationTable,
    canonical_destination,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import (
        ActionPolicy,
        AuditTrail,
        EgressBinder,
        Forecaster,
    )
    from ai_assistant.core.types import ToolDefinition

#: The instant every case in this harness runs at.
NOW: Final = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

#: The connected account this deployment's forecast integration is registered against.
FORECAST_ACCOUNT: Final = BoundAccount(identity="Example Forecast", reference="conn-forecast")

#: The credential slot the record names. A binding never carries one (ADR-0148 §6).
FORECAST_SLOT: Final = SecretName(scope=SecretScope.INTEGRATION, key="conn-forecast-r1")

#: The one member ``Settings.forecast_origin`` canonicalises to, derived through the
#: **same** function ``app/composition.py`` derives it with, so the set the ruling
#: compares against and the set the binding carries are one value computed once
#: (ADR-0260 §6, §11).
FORECAST_DESTINATION: Final[CanonicalDestination] = canonical_destination(
    DestinationProtocol.HTTPS, DEFAULT_FORECAST_ORIGIN
)

#: What a deployment that declared its per-call figure holds (ADR-0236 §1, §7).
#:
#: **Given rather than omitted, and the reason is issue #2111 one kind over**: a
#: declaration whose ``cost`` is ``UNKNOWN`` fires ``ThresholdActionPolicy``'s
#: unknown-cost floor beside every other test, which ADR-0260 §11 leaves untouched and
#: which no route discharges — so an unpriced deployment reads ``RULING_CONFIRM`` on
#: every forecast and §13's arms below would each be asserting about that floor instead
#: of about the stage they name. This is ADR-0260 §11's own configured case and not a
#: weakening: nothing is narrowed, restated or declared ``FREE`` where the figure is
#: unknown.
FORECAST_COST: Final = ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.004"), currency="USD")

#: The declaration a configured deployment's forecaster proposes and the egress seam
#: holds — built here exactly as :class:`~ai_assistant.testing.FakeForecaster` builds its
#: own, so the registration this harness writes is for the tool the fake will actually
#: propose. ``model_copy`` keeps the id, so a case that drops the cost is still bound.
FORECAST_DECLARATION: Final = FAKE_FORECAST_READ.model_copy(update={"cost": FORECAST_COST})

#: The goal a servicing on a goal turn is stated over, for ADR-0252 §14's row.
GOAL_RECORD: Final = Goal(
    id="goal-1",
    interpretation=(
        GoalInterpretation(
            revision=1,
            outcome="know what the weekend looks like",
            outcome_ground=Ground.USER_STATED,
            outcome_span="know what the weekend looks like",
            recorded_at=NOW,
            raised_by="t-1",
        ),
    ),
    provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=NOW),
    created_at=NOW,
)
GOAL: Final = GoalBrief.of(GOAL_RECORD)


def clock() -> datetime:
    """This harness's one instant."""
    return NOW


@final
class _NoDefinitions:
    """A ``RegisteredDefinitions`` face holding nothing (ADR-0260 §1).

    The state a deployment with a forecast provider configured is actually in: the
    declaration is registered at the egress seam and in **no** ``ToolRegistry``, so the
    seam's registry-original comparison is not reached.
    """

    __slots__ = ()

    def original(self, tool_id: str, /) -> None:
        """No registry holds a definition for this id.

        Args:
            tool_id: The id being looked up.
        """
        _ = tool_id


@final
class _Records:
    """A ``ConnectionRecords`` face holding one ``ACTIVE`` record for the account."""

    __slots__ = ("reads",)

    def __init__(self) -> None:
        """Record every reference read, so a case asserting none has a subject."""
        self.reads: list[str] = []

    async def latest(self, reference: str, /) -> StoredEntry | None:
        """The reference's latest entry.

        Args:
            reference: The connection to read.

        Returns:
            The one active entry where the reference is this deployment's, else
            ``None``.
        """
        self.reads.append(reference)
        if reference != FORECAST_ACCOUNT.reference:
            return None
        return StoredEntry(
            1,
            ConnectionEntry(
                reference=FORECAST_ACCOUNT.reference,
                revision=1,
                identity=FORECAST_ACCOUNT.identity,
                state=ProvisioningState.ACTIVE,
                slot=FORECAST_SLOT,
            ),
        )


def forecaster(**knobs: Any) -> FakeForecaster:
    """The canonical fake, priced as a configured deployment prices it.

    Args:
        **knobs: Whatever the case varies — a script, a refusal, a bound.

    Returns:
        The fake, carrying :data:`FORECAST_COST`'s figure in its own declaration
        unless the case says otherwise.
    """
    arguments: dict[str, Any] = {
        "reported_at": NOW,
        "cost_per_call": FORECAST_COST.amount,
        "cost_currency": FORECAST_COST.currency,
    }
    arguments.update(knobs)
    return FakeForecaster(**arguments)


def binder(declaration: ToolDefinition) -> EgressBindingSeam:
    """The **production** binding seam, holding one forecast registration.

    Args:
        declaration: The forecaster's own registered declaration, which is what
            ``Forecaster.request`` proposes and what the seam is asked to bind.

    Returns:
        The seam.
    """
    return EgressBindingSeam(
        definitions=_NoDefinitions(),
        registrations=RegistrationTable(
            (
                EgressRegistration(
                    tool_id=declaration.id,
                    reference=FORECAST_ACCOUNT.reference,
                    transport_endpoint=DEFAULT_FORECAST_ORIGIN,
                ),
            )
        ),
        records=_Records(),
    )


def configured_forecast() -> ConfiguredForecastDestination:
    """The forecast pair a composition root hands the policy (ADR-0260 §6, §12's L2)."""
    return ConfiguredForecastDestination(
        reference=FORECAST_ACCOUNT.reference,
        destinations=frozenset({FORECAST_DESTINATION}),
    )


def servicer(  # noqa: PLR0913 — one knob per contract ADR-0260 §6 names plus ADR-0241 §1's bound and the configured-pair fact; that is what this is
    *,
    seam: Forecaster | None = None,
    binding: EgressBinder | None = None,
    policy: ActionPolicy | None = None,
    trail: AuditTrail | None = None,
    configured: bool = True,
    deadline: timedelta = timedelta(seconds=30),
) -> ForecastServicer:
    """A forecast servicing over the real binder, the real policy and one fake seam.

    ``configured`` is the one knob that decides the ruling: with it the deployment holds
    ADR-0260 §6's pair and the production ``ThresholdActionPolicy`` reaches route (c)'s
    ``ALLOW``; without it the policy holds no forecast pair, the derived fact is false
    for every forecast read, and the ruling is what ``origin/main`` gives an
    unconfigured destination — §6's fail-closed direction.

    Args:
        seam: The forecaster, defaulting to :func:`forecaster`'s.
        binding: The binding seam, defaulting to the **real** one :func:`binder`
            builds. A case that needs to read the carrier ``orchestration`` wrote
            passes a recorder around it.
        policy: The policy, defaulting to the production one.
        trail: The trail, defaulting to the canonical fake.
        configured: Whether this deployment configured the pair the binding carries.
        deadline: ADR-0241 §1's bound, which ADR-0260 §11 forbids a second of.

    Returns:
        The servicer.
    """
    ids = itertools.count(1)
    return ForecastServicer(
        forecaster=forecaster() if seam is None else seam,
        binder=binder(FORECAST_DECLARATION) if binding is None else binding,
        policy=(
            ThresholdActionPolicy(
                grants=FakeRecipientGrants((), now=clock),
                configured_forecast=configured_forecast() if configured else None,
            )
            if policy is None
            else policy
        ),
        trail=FakeAuditTrail() if trail is None else trail,
        now=clock,
        id_factory=lambda: f"forecast-d-{next(ids)}",
        deadline=deadline,
    )


def forecast_request() -> ReadRequest:
    """A request asking for a forecast and nothing else (ADR-0260 §3)."""
    return ReadRequest(asks=(ReadAsk(kind=ReadKind.FORECAST_READ),))


def belief(record_id: str, content: str, **fields: Any) -> SemanticMemory:
    """A belief the turn's own retrieval selected.

    Args:
        record_id: Its id.
        content: Its content.
        **fields: Whatever the case varies on its provenance.

    Returns:
        The record.
    """
    provenance: dict[str, Any] = {
        "source": MemorySource.OBSERVED,
        "confidence": 0.6,
        "last_updated": NOW,
    }
    provenance.update(fields)
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        placement=Placement(),
        provenance=Provenance(**provenance),
    )


def plan() -> ActionPlan:
    """The plan a servicing answers, carried onto no park here (ADR-0260 §11)."""
    return ActionPlan(
        id="plan-1",
        goal_id=GOAL_RECORD.id,
        steps=(),
        created_at=NOW,
        rationale="answered over what the forecast added",
    )
