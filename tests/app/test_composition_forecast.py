"""What configuring a forecast provider buys, and what it deliberately does not.

ADR-0260 §1's whole design turns on the two halves of "registered" coming apart: the
forecast integration is registered at the egress seam, so ``EgressBinder.bind`` derives
a binding for it, and in **no** ``ToolRegistry``, so the planner never sees a
capability, cannot name a plan step, and the turn cannot drive a tool whose result is a
payload with no per-span provenance (ADR-0170 §5a, ADR-0208 §1). Every case here is one
of the ways that could be broken by a **wiring** rather than by a rule: an integration
built where none was configured, a registration that reached the wrong table, a
transport constructed unconditionally.

**Nothing here opens a socket.** Every case builds the engine over a hashing embedder
and closes it; the forecaster's transport is never driven, and the configured provider
names an ``.invalid`` origin (RFC 6761 §6.4).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.app import build_engine
from ai_assistant.app import composition as composition_module
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import CostBasis
from ai_assistant.orchestration import ForecastServicer
from ai_assistant.permissions import ConfiguredForecastDestination, ThresholdActionPolicy
from ai_assistant.tools import ForecastIntegration, build_forecast_integration
from ai_assistant.tools.egress import HttpsEgressTransport, StreamOutboundTransport
from ai_assistant.tools.egress_binder import EgressBindingSeam
from ai_assistant.tools.forecast import FORECAST_READ, FORECAST_READ_ID, ForecastEgress

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio

#: The connection a configured deployment names. ``.invalid`` (RFC 6761 §6.4).
CONNECTION: Final = "conn-forecast-0001"
FORECAST_ORIGIN: Final = "https://forecast.example.invalid"

#: The place a configured deployment reads for (ADR-0260 §3, §11).
LATITUDE: Final = 41.1579
LONGITUDE: Final = -8.6291

#: The per-call figure ADR-0236 §1 lets an operator declare, and the code it is
#: denominated in. Distinctive enough that an assertion about the wired declaration is
#: not an assertion about a coincidence.
FIGURE: Final = Decimal("0.004")
CODE: Final = "EUR"

#: ADR-0241 §3's one call deadline, which ADR-0260 §11 forbids a second of. Distinctive
#: rather than the shipped default, so an assertion that the servicing site carries it is
#: an assertion about forwarding and not about two objects agreeing on 30 seconds.
DEADLINE: Final = timedelta(seconds=17)

#: A fixed reading for the root's own clock, distinctive for the same reason: the seam
#: wraps its clock in :func:`~ai_assistant.core.clock.checked_clock`, so the wiring can be
#: asserted by what the wrapped clock *reads* but never by identity.
INSTANT: Final = datetime(2026, 9, 16, 12, 34, 56, tzinfo=UTC)


def _settings(
    *, configured: bool, priced: bool = False, deadline: timedelta | None = None
) -> Settings:
    """Settings for a deployment that has, or has not, configured a forecast provider.

    Args:
        configured: Whether to name the connection, the origin and the place.
        priced: Whether to declare ADR-0236 §1's per-call figure as well. Neither cost
            field may be set without the provider configuration, so this is only
            meaningful beside ``configured``.
        deadline: ADR-0241 §3's ``search_call_deadline``, where a case needs a
            distinctive one. ``None`` leaves the shipped default, and the field is
            independent of the forecast configuration — ADR-0260 §11 declines a figure
            of its own, so this is the only one there is.

    Returns:
        The settings.
    """
    bound: dict[str, Any] = {} if deadline is None else {"search_call_deadline": deadline}
    if not configured:
        return Settings(embedder=EmbedderKind.HASHING, **bound)
    cost: dict[str, Any] = (
        {"forecast_cost_per_call": FIGURE, "forecast_cost_currency": CODE} if priced else {}
    )
    return Settings(
        embedder=EmbedderKind.HASHING,
        forecast_connection=CONNECTION,
        forecast_origin=FORECAST_ORIGIN,
        forecast_latitude=LATITUDE,
        forecast_longitude=LONGITUDE,
        **cost,
        **bound,
    )


@pytest.mark.parametrize("configured", [True, False], ids=["configured", "unconfigured"])
async def test_the_forecast_declaration_is_absent_from_the_wired_registry(
    tmp_path: Path, *, configured: bool
) -> None:
    """ADR-0260 §1: absent from ``capabilities()`` and ``all_tools()``, configured or not.

    **The property §1 rests on, asserted where it can be broken.** A registry entry
    would put the capability in front of the planner, and the planner naming it is the
    outcome the whole design exists to make unreachable — which is what lets §1 say
    ADR-0208 §1 is "satisfied by not being a tool" rather than by a rule.

    The **configured** row is the one that could break; the unconfigured row keeps it
    from passing vacuously, since a registry that held nothing for an unrelated reason
    would read the same.
    """
    engine = build_engine(_settings(configured=configured), data_dir=tmp_path)
    try:
        registry = engine._runner._registry

        assert FORECAST_READ.capability not in await registry.capabilities()
        assert FORECAST_READ_ID not in {tool.id for tool in await registry.all_tools()}
        assert await registry.get(FORECAST_READ_ID) is None
    finally:
        await engine.aclose()


@pytest.mark.parametrize("configured", [True, False], ids=["configured", "unconfigured"])
async def test_the_registration_reaches_the_binding_seam_only_where_configured(
    tmp_path: Path, *, configured: bool
) -> None:
    """ADR-0260 §1's other half: the seam **does** hold it.

    The two halves are asserted together on purpose. Separately they are two facts that
    happen to agree; what §1's design buys is that a registry entry and a seam
    registration come from one value, so "registered but unreachable" and "reachable but
    unregistered" are both states the composition root cannot produce.
    """
    engine = build_engine(_settings(configured=configured), data_dir=tmp_path)
    try:
        binder = engine._runner._binder
        assert isinstance(binder, EgressBindingSeam)
        registration = binder._registrations.registration(FORECAST_READ_ID)

        assert (registration is not None) is configured
        if registration is not None:
            assert registration.reference == CONNECTION
            assert registration.transport_endpoint == FORECAST_ORIGIN
    finally:
        await engine.aclose()


async def test_a_deployment_that_configured_no_provider_builds_no_forecaster(
    tmp_path: Path,
) -> None:
    """ADR-0260 §12: "constructed only where a provider is configured".

    **Asserted over the builder rather than over a held reference**, because L1 wires
    the forecaster into no servicing yet — §12 gives that to L3 — so what this root
    produces today is an integration and a seam registration. A root that built one
    unconditionally would open an exchange, and with it a transport, for a deployment
    that configured nothing.
    """
    built: list[ForecastIntegration] = []

    def counted(**arguments: Any) -> ForecastIntegration:
        integration = build_forecast_integration(**arguments)
        built.append(integration)
        return integration

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(composition_module, "build_forecast_integration", counted)
        engine = build_engine(_settings(configured=False), data_dir=tmp_path)

    try:
        assert built == []
    finally:
        await engine.aclose()


async def test_a_configured_deployment_builds_one_forecaster_over_the_real_transport(
    tmp_path: Path,
) -> None:
    """The positive arm, and ADR-0191 §1's injection through it.

    One forecaster, holding the designated seam's transport over the **real**
    :class:`~ai_assistant.tools.egress.StreamOutboundTransport` — which is what makes
    "a subsystem handed no capability has no route to the world" true of the whole tree
    rather than of one argument list. The place it holds is the configured one, which is
    §3's "held by the forecaster as its own configuration".
    """
    built: list[ForecastIntegration] = []

    def counted(**arguments: Any) -> ForecastIntegration:
        integration = build_forecast_integration(**arguments)
        built.append(integration)
        return integration

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(composition_module, "build_forecast_integration", counted)
        engine = build_engine(_settings(configured=True), data_dir=tmp_path)

    try:
        (integration,) = built
        forecaster = integration.forecaster
        assert isinstance(forecaster, ForecastEgress)
        assert isinstance(forecaster._transport, HttpsEgressTransport)
        assert isinstance(forecaster._transport._exchange._transport, StreamOutboundTransport)
        assert forecaster._latitude == pytest.approx(LATITUDE)
        assert forecaster._longitude == pytest.approx(LONGITUDE)
        assert forecaster.name
    finally:
        await engine.aclose()


async def test_a_configured_root_installs_one_servicer_in_the_loop_over_the_built_forecaster(
    tmp_path: Path,
) -> None:
    """ADR-0260 §7 and §12's L3: **the built forecaster reaches the servicing site.**

    "``app/composition.py`` wires the forecaster into that one site and into nothing
    else, and no lane adds a second caller." Every other case in this module stops at
    construction and registration — they assert that a configured deployment *builds* a
    forecaster and that the seam holds its registration, and every one of them would
    stay green with ``forecast=None`` passed to :class:`LearningLoop` while every
    configured deployment reported §8's ``NOT_CONFIGURED``. That is the wiring failure
    §12 makes this root's own job, so it is asserted here, at the end of the wire.

    **The servicer is counted, not merely found.** Constructing it through a counting
    wrapper and then asserting the loop holds *that* object is what makes "one site"
    a property of this root: a second servicer over the same seams would hold a second
    forecaster reference, which is exactly what §7's "no lane adds a second caller"
    forbids, and a root that built one and installed another would fail here.

    **The seams are the root's own objects, by identity** (§6, §7): the same binder,
    the same policy — so one deployment has one set of thresholds and one
    configured-provider comparison rather than two that could disagree about which pair
    a request was at — and the same trail the runner and the ledger hold (ADR-0192 §1).

    **The clock and the id factory are asserted by reading rather than by identity**,
    because the seam wraps its clock in
    :func:`~ai_assistant.core.clock.checked_clock` (ADR-0026 §4) and the wrapper is a
    fresh closure. Patching the root's own ``_utcnow`` to a fixed instant makes the
    reading itself the evidence: a site handed some other clock reads the wall clock and
    fails.

    **The deadline is the one figure and there is no second** (ADR-0241 §3, ADR-0260
    §11): the distinctive ``search_call_deadline`` this deployment configured, which a
    root that hard-coded 30 seconds or read a forecast-only field this decision declined
    to add would not carry.
    """
    integrations: list[ForecastIntegration] = []
    servicers: list[ForecastServicer] = []

    def counted_integration(**arguments: Any) -> ForecastIntegration:
        integration = build_forecast_integration(**arguments)
        integrations.append(integration)
        return integration

    def counted_servicer(**arguments: Any) -> ForecastServicer:
        servicer = ForecastServicer(**arguments)
        servicers.append(servicer)
        return servicer

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(composition_module, "build_forecast_integration", counted_integration)
        patch.setattr(composition_module, "ForecastServicer", counted_servicer)
        patch.setattr(composition_module, "_utcnow", lambda: INSTANT)
        engine = build_engine(_settings(configured=True, deadline=DEADLINE), data_dir=tmp_path)

    try:
        (integration,) = integrations
        assert len(servicers) == 1, "exactly one servicing site, never a second caller"
        (servicer,) = servicers
        assert engine._loop._forecast is servicer, "the one built is the one the loop holds"

        assert servicer._forecaster is integration.forecaster, "the one the seam registered"
        assert servicer._binder is engine._runner._binder
        assert servicer._policy is engine._runner._policy
        assert servicer._trail is engine._runner._trail
        assert servicer._now() == INSTANT, "the root's own clock, read through the guard"
        assert servicer._id_factory is composition_module._uuid
        assert servicer._deadline == DEADLINE
    finally:
        await engine.aclose()


async def test_a_deployment_that_configured_no_provider_installs_no_servicing_site(
    tmp_path: Path,
) -> None:
    """ADR-0260 §8's ``NOT_CONFIGURED``, **stated by a caller rather than defaulted.**

    "A deployment that configured none holds no instance at all, and
    ``service_read_request`` is handed ``None``." Without this row the case above would
    pass against a root that installed a servicer unconditionally — which would open an
    exchange, and with it a transport, for a deployment that configured nothing, and
    would make ``NOT_CONFIGURED`` a state no wiring could produce.
    """
    engine = build_engine(_settings(configured=False), data_dir=tmp_path)
    try:
        assert engine._loop._forecast is None
    finally:
        await engine.aclose()


async def test_the_forecaster_and_the_seam_share_one_registration_object(
    tmp_path: Path,
) -> None:
    """One value, not two equal ones (ADR-0148 §6, ADR-0260 §6).

    The origin a ruled call is pinned against and the reference a connection record is
    read by come from the same object, so they cannot come apart — which is what makes
    the pin a property of the wiring rather than of two configurations agreeing.
    """
    built: list[ForecastIntegration] = []

    def counted(**arguments: Any) -> ForecastIntegration:
        integration = build_forecast_integration(**arguments)
        built.append(integration)
        return integration

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(composition_module, "build_forecast_integration", counted)
        engine = build_engine(_settings(configured=True), data_dir=tmp_path)

    try:
        (integration,) = built
        binder = engine._runner._binder
        assert isinstance(binder, EgressBindingSeam)
        assert binder._registrations.registration(FORECAST_READ_ID) is integration.registration
    finally:
        await engine.aclose()


async def test_the_search_and_the_forecast_registrations_sit_in_one_table(
    tmp_path: Path,
) -> None:
    """ADR-0260 §6: each kind is compared against **its own** configured pair.

    Two registrations in one table and neither reachable through the other's id, which
    is what makes "a forecast request bound to the search provider's account or origin,
    or the reverse, takes no route at all" a property of the wiring. A deployment that
    configured both is the state where a table keyed loosely would let one kind's ruling
    reach the other's origin.
    """
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        web_search_connection="conn-search-0001",
        web_search_origin="https://search.example.invalid",
        forecast_connection=CONNECTION,
        forecast_origin=FORECAST_ORIGIN,
        forecast_latitude=LATITUDE,
        forecast_longitude=LONGITUDE,
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        binder = engine._runner._binder
        assert isinstance(binder, EgressBindingSeam)
        forecast = binder._registrations.registration(FORECAST_READ_ID)
        search = binder._registrations.registration("web_search")

        assert forecast is not None
        assert search is not None
        assert forecast.transport_endpoint == FORECAST_ORIGIN
        assert search.transport_endpoint == "https://search.example.invalid"
    finally:
        await engine.aclose()


async def test_the_composition_root_forwards_the_configured_per_call_figure(
    tmp_path: Path,
) -> None:
    """ADR-0236 §1 through ADR-0260 §11: read and passed through **unchanged**.

    "Forwarding is an obligation rather than a convenience — a lane that landed the
    fields, the builder and every test while this root passed neither would leave every
    configured deployment at ``UNKNOWN`` with a green gate, which is the failure the
    decision exists to remove."
    """
    built: list[ForecastIntegration] = []

    def counted(**arguments: Any) -> ForecastIntegration:
        integration = build_forecast_integration(**arguments)
        built.append(integration)
        return integration

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(composition_module, "build_forecast_integration", counted)
        engine = build_engine(_settings(configured=True, priced=True), data_dir=tmp_path)

    try:
        (integration,) = built
        declaration = integration.forecaster._declaration
        assert declaration.cost.basis is CostBasis.PER_CALL
        assert declaration.cost.amount == FIGURE
        assert declaration.cost.currency == CODE
        # The module constant is never mutated, which is what keeps `FORECAST_READ` the
        # object a reader can compare against (ADR-0016 §1's `frozen=True` argument).
        assert FORECAST_READ.cost.basis is CostBasis.UNKNOWN
    finally:
        await engine.aclose()


async def test_a_deployment_that_declared_no_figure_is_wired_at_unknown(
    tmp_path: Path,
) -> None:
    """ADR-0236 §4's state, which is what the shipped default puts a deployment in.

    The unknown-cost floor then fires alongside the disclosure floor, which ADR-0260 §11
    keeps binding unchanged: "a deployment that wants the read to run without one states
    the provider's cost, which for a free provider is zero in the currency it states".
    """
    built: list[ForecastIntegration] = []

    def counted(**arguments: Any) -> ForecastIntegration:
        integration = build_forecast_integration(**arguments)
        built.append(integration)
        return integration

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(composition_module, "build_forecast_integration", counted)
        engine = build_engine(_settings(configured=True), data_dir=tmp_path)

    try:
        (integration,) = built
        assert integration.forecaster._declaration is FORECAST_READ
        assert FORECAST_READ.cost.basis is CostBasis.UNKNOWN
    finally:
        await engine.aclose()


async def test_half_a_forecast_configuration_is_refused_at_settings_load() -> None:
    """ADR-0260 §11: the four are one pair of pairs, refused half-set at **load**.

    Asserted here as well as in ``tests/core/test_forecast_settings.py`` because this is
    the property the composition root depends on: the branch above reads all four, so a
    deployment that named some of them would otherwise reach a builder with a place and
    no origin — and the quiet reading, starting and being inert, is the unsafe one.
    """
    with pytest.raises(ValueError, match="forecast_origin"):
        Settings(embedder=EmbedderKind.HASHING, forecast_connection=CONNECTION)

    with pytest.raises(ValueError, match="forecast_latitude"):
        Settings(
            embedder=EmbedderKind.HASHING,
            forecast_connection=CONNECTION,
            forecast_origin=FORECAST_ORIGIN,
        )


async def test_a_cost_pair_with_no_forecast_provider_is_refused_at_settings_load() -> None:
    """ADR-0236 §2 through ADR-0260 §11: a figure nothing would read.

    The composition root constructs no forecast integration at all unless the four
    fields are set, so the pair would reach no builder and no declaration — and an
    operator who set it believes their reads are priced.
    """
    with pytest.raises(ValueError, match="no forecast provider is configured"):
        Settings(
            embedder=EmbedderKind.HASHING,
            forecast_cost_per_call=FIGURE,
            forecast_cost_currency=CODE,
        )


async def test_the_policy_is_handed_the_configured_forecast_destination(tmp_path: Path) -> None:
    """ADR-0260 §12's L2: the one new constructor argument, where a root could drop it.

    "``app/composition.py`` supplying it — the one file outside ``permissions/`` this
    lane touches and the composition root's own job." A lane that landed the policy,
    the widened predicate and every arm while passing nothing would leave **every
    configured deployment taking the forecast predicate as false**, with a green gate
    and a forecast read that still asks — the same failure
    ``test_the_policy_is_handed_the_configured_search_destination`` exists for, one
    decision along.

    **Asserted against the registration the seam holds rather than against the settings
    text**, because what §6 compares is the binding's own ``account.reference`` and its
    own canonical destination set: a root that passed the right strings to the wrong
    policy, or the **search** pair into this argument, fails here.
    """
    engine = build_engine(_settings(configured=True), data_dir=tmp_path)
    try:
        binder = engine._runner._binder
        assert isinstance(binder, EgressBindingSeam)
        registration = binder._registrations.registration(FORECAST_READ_ID)
        assert registration is not None, "a configured deployment registers the forecast read"
        policy = engine._runner._policy
        assert isinstance(policy, ThresholdActionPolicy), "the production policy"

        assert policy._configured_forecast == ConfiguredForecastDestination(
            reference=registration.reference,
            destinations=frozenset(
                composition_module._forecast_destinations(registration.transport_endpoint)
            ),
        )
        # **The two pairs are not the same value**, which is what makes the crosswise
        # clause of §6 have a subject in a real deployment: this one configured a
        # forecast provider and no search account, so the search argument is `None`
        # while the forecast argument is a pair.
        assert policy._configured_search is None
    finally:
        await engine.aclose()


async def test_a_deployment_that_configured_no_forecast_provider_hands_the_policy_nothing(
    tmp_path: Path,
) -> None:
    """ADR-0260 §6's fail-closed default, and what ``forecast_reach`` already gives.

    With none of the four settings there is no registration, no forecast request is
    ever composed, and the authority §6 states has nothing to attach to — so the policy
    is handed ``None`` and takes the predicate as false for every forecast read.
    Without this row the case above would pass against a root that hard-coded a pair.
    """
    engine = build_engine(_settings(configured=False), data_dir=tmp_path)
    try:
        policy = engine._runner._policy
        assert isinstance(policy, ThresholdActionPolicy), "the production policy"
        assert policy._configured_forecast is None
    finally:
        await engine.aclose()


async def test_an_origin_with_no_canonical_form_leaves_the_forecast_pair_unbuilt() -> None:
    """The refusal is answered rather than raised, as ``_search_destinations`` answers it.

    A composition root that raised here would take the whole process down for a read the
    seam would refuse anyway. Answering the empty set instead leaves the pair ``None``,
    which is the restrictive value: no forecast read is at the configured provider, and
    a pair carrying an empty set could never equal a binding's own — which is never
    empty — so it would read as a configuration while authorising nothing.
    """
    assert composition_module._forecast_destinations("not an origin at all") == ()
    assert composition_module._forecast_destinations(None) == ()
    assert composition_module._configured_forecast(CONNECTION, ()) is None
    assert composition_module._configured_forecast(None, ()) is None
