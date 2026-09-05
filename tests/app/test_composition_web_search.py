"""What wiring a search account buys, and what it deliberately does not (ADR-0231).

ADR-0231 §18's arm **12** — "the declaration is in no registry" — asked for exactly
this: "the composition test asserts that ``ToolRegistry.capabilities()`` and
``all_tools()`` on the wired registry hold no member of the search declaration, on a
deployment with a search account connected — the property §5 rests on, asserted where
it can be broken."

**Why that property is worth its own file.** ADR-0231 §5's whole design turns on the
two halves of "registered" coming apart: the search integration is registered at the
egress seam, so ``EgressBinder.bind`` derives a binding for it, and in **no**
``ToolRegistry``, so the planner never sees a capability, cannot name a plan step, and
the turn cannot drive a tool whose result is a payload with no per-span provenance
(ADR-0170 §5a, ADR-0208 §1). Every other case here is one of the ways that could be
broken by a wiring rather than by a rule: an integration built where none was
configured, a registration that reached the wrong table, a transport constructed
unconditionally.

**Nothing here opens a socket.** Every case builds the engine over a hashing embedder
and closes it; the searcher's transport is never driven, and the connected account
names an ``.invalid`` origin (RFC 6761 §6.4).
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.app import build_engine
from ai_assistant.app import composition as composition_module
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import CostBasis
from ai_assistant.tools import WebSearchIntegration, build_web_search_integration
from ai_assistant.tools.egress import StreamOutboundTransport, WebSearchTransport
from ai_assistant.tools.egress_binder import EgressBindingSeam
from ai_assistant.tools.web_search import WEB_SEARCH, WEB_SEARCH_ID, WebSearchEgress

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio

#: The account a configured deployment names. ``.invalid`` (RFC 6761 §6.4).
CONNECTION: Final = "conn-0001"
SEARCH_ORIGIN: Final = "https://search.example.invalid"


#: The per-call figure ADR-0236 §1 lets an operator declare, and the code it is
#: denominated in. Distinctive enough that an assertion about the wired declaration
#: is not an assertion about a coincidence.
FIGURE: Final = Decimal("0.005")
CODE: Final = "USD"


def _settings(*, configured: bool, priced: bool = False) -> Settings:
    """Settings for a deployment that has, or has not, connected a search account.

    Args:
        configured: Whether to name the connection and the origin.
        priced: Whether to declare ADR-0236 §1's per-call figure as well. Neither
            cost field may be set without the registration pair, so this is only
            meaningful beside ``configured``.

    Returns:
        The settings.
    """
    if not configured:
        return Settings(embedder=EmbedderKind.HASHING)
    cost: dict[str, Any] = (
        {"web_search_cost_per_call": FIGURE, "web_search_cost_currency": CODE} if priced else {}
    )
    return Settings(
        embedder=EmbedderKind.HASHING,
        web_search_connection=CONNECTION,
        web_search_origin=SEARCH_ORIGIN,
        **cost,
    )


@pytest.mark.parametrize("configured", [True, False], ids=["configured", "unconfigured"])
async def test_the_search_declaration_is_absent_from_the_wired_registry(
    tmp_path: Path, *, configured: bool
) -> None:
    """§18 arm 12: absent from ``capabilities()`` and ``all_tools()``, account or no.

    The **configured** row is the one the ADR asks for and the one that could break;
    the unconfigured row keeps it from passing vacuously, since a registry that held
    nothing for an unrelated reason would read the same.
    """
    engine = build_engine(_settings(configured=configured), data_dir=tmp_path)
    try:
        registry = engine._runner._registry

        assert WEB_SEARCH.capability not in await registry.capabilities()
        assert WEB_SEARCH_ID not in {tool.id for tool in await registry.all_tools()}
        assert await registry.get(WEB_SEARCH_ID) is None
    finally:
        await engine.aclose()


@pytest.mark.parametrize("configured", [True, False], ids=["configured", "unconfigured"])
async def test_the_registration_reaches_the_binding_seam_only_where_configured(
    tmp_path: Path, *, configured: bool
) -> None:
    """ADR-0231 §5's other half: the seam **does** hold it.

    The two halves are asserted together on purpose. Separately they are two facts
    that happen to agree; what §5's design buys is that a registry entry and a seam
    registration come from one value, so "registered but unreachable" and "reachable
    but unregistered" are both states the composition root cannot produce.
    """
    engine = build_engine(_settings(configured=configured), data_dir=tmp_path)
    try:
        binder = engine._runner._binder
        assert isinstance(binder, EgressBindingSeam)
        registration = binder._registrations.registration(WEB_SEARCH_ID)

        assert (registration is not None) is configured
        if registration is not None:
            assert registration.reference == CONNECTION
            assert registration.transport_endpoint == SEARCH_ORIGIN
    finally:
        await engine.aclose()


async def test_a_deployment_that_connected_no_account_builds_no_searcher(
    tmp_path: Path,
) -> None:
    """ADR-0231 §17: "constructs a searcher only where an account is connected".

    Asserted at the construction rather than inferred from an absence downstream: a
    root that built a searcher and handed it to nothing would leave every reachable
    reading unchanged while the clause was false.
    """
    built: list[WebSearchIntegration] = []

    def counted(**arguments: Any) -> WebSearchIntegration:
        integration = build_web_search_integration(**arguments)
        built.append(integration)
        return integration

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(composition_module, "build_web_search_integration", counted)
        engine = build_engine(_settings(configured=False), data_dir=tmp_path)

    try:
        assert built == []
    finally:
        await engine.aclose()


async def test_a_configured_deployment_builds_one_searcher_over_the_real_transport(
    tmp_path: Path,
) -> None:
    """ADR-0191 §1, §3: production reaches the world through an injection.

    Walked to the object the seam would open its channels with, because that is the
    only place the difference is visible: a default argument and an injected one
    produce the same type, and what ADR-0191 §3 changed is that there is exactly one
    construction site and it is the composition root.
    """
    built: list[WebSearchIntegration] = []

    def counted(**arguments: Any) -> WebSearchIntegration:
        integration = build_web_search_integration(**arguments)
        built.append(integration)
        return integration

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(composition_module, "build_web_search_integration", counted)
        engine = build_engine(_settings(configured=True), data_dir=tmp_path)

    try:
        (integration,) = built
        searcher = integration.searcher
        assert searcher.name
        seam = searcher._transport
        assert isinstance(seam, WebSearchTransport)
        assert seam.origin == SEARCH_ORIGIN
        assert isinstance(seam._exchange._transport, StreamOutboundTransport)
    finally:
        await engine.aclose()


async def test_half_a_search_registration_is_refused_at_settings_load() -> None:
    """ADR-0231 §17's whole-or-absent pair, refused where it is stated.

    Refused rather than treated as "not configured", for
    ``send_email_connection``'s reason one field pair along: an operator who set one
    variable believes the mechanism is wired, and a deployment that silently built no
    searcher would leave them believing it while every turn's search quietly did not
    happen.
    """
    with pytest.raises(ValueError, match="web_search_origin"):
        Settings(embedder=EmbedderKind.HASHING, web_search_connection=CONNECTION)

    with pytest.raises(ValueError, match="web_search_connection"):
        Settings(embedder=EmbedderKind.HASHING, web_search_origin=SEARCH_ORIGIN)


async def test_the_searcher_and_the_seam_share_one_registration_object(
    tmp_path: Path,
) -> None:
    """One value, not two equal ones (ADR-0148 §6, ADR-0231 §5).

    The origin a ruled call is pinned against and the reference a connection record is
    read by come from the same object, so they cannot come apart — which is what makes
    the pin a property of the wiring rather than of two configurations agreeing.
    """
    built: list[WebSearchIntegration] = []

    def counted(**arguments: Any) -> WebSearchIntegration:
        integration = build_web_search_integration(**arguments)
        built.append(integration)
        return integration

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(composition_module, "build_web_search_integration", counted)
        engine = build_engine(_settings(configured=True), data_dir=tmp_path)

    try:
        (integration,) = built
        binder = engine._runner._binder
        assert isinstance(binder, EgressBindingSeam)
        assert binder._registrations.registration(WEB_SEARCH_ID) is integration.registration
    finally:
        await engine.aclose()


async def test_the_searcher_reaches_the_loop_and_nothing_else(tmp_path: Path) -> None:
    """ADR-0231 §11's one-call-site clause, asserted where it can be broken.

    "``app/composition.py`` wires the searcher into that one site and into nothing
    else, no other subsystem holds the reference, and no lane adds a second caller."
    There is no type that says so — a ``WebSearcher`` is a Protocol any holder could
    satisfy the caller of — so the property is a fact about **this wiring**, asserted
    here: the object ``build_web_search_integration`` returned is the object the loop's
    servicer holds, and the loop is the only thing on the engine that holds one.

    The **policy, the binder and the trail the servicer holds are the runner's own
    objects**, which is the other half of the wiring and is asserted beside it: one
    ``ThresholdActionPolicy`` so a step's send and a turn's search are ruled under one
    set of thresholds and one ``RecipientGrants`` face (ADR-0193 §7), one binding seam
    (ADR-0152 §10), and one trail because ADR-0192 §1 requires the decision the
    searcher's ledger claim is keyed on to equal the one the store holds under that id.
    """
    built: list[WebSearchIntegration] = []

    def counted(**arguments: Any) -> WebSearchIntegration:
        integration = build_web_search_integration(**arguments)
        built.append(integration)
        return integration

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(composition_module, "build_web_search_integration", counted)
        engine = build_engine(_settings(configured=True), data_dir=tmp_path)

    try:
        (integration,) = built
        servicer = engine._loop._search
        assert servicer is not None, "a configured deployment services searches"
        assert servicer._searcher is integration.searcher, "the one the seam registered"
        assert servicer._binder is engine._runner._binder
        assert servicer._policy is engine._runner._policy
        assert servicer._trail is engine._runner._trail
    finally:
        await engine.aclose()


async def test_a_deployment_that_connected_no_account_services_no_search(
    tmp_path: Path,
) -> None:
    """ADR-0231 §13's ``NOT_CONFIGURED``, at the wiring that produces it.

    "A deployment with no search account connected … reads a 0% yield for this kind,
    and that is a true statement about that configuration rather than a reading of a
    trigger." The loop holds no servicer at all, so a ``WEB_SEARCH`` ask composes
    nothing, seeks no ruling and opens no channel — and ``None`` is the ordinary case
    rather than an error.
    """
    engine = build_engine(_settings(configured=False), data_dir=tmp_path)
    try:
        assert engine._loop._search is None
    finally:
        await engine.aclose()


async def test_the_composition_root_forwards_the_configured_per_call_figure(
    tmp_path: Path,
) -> None:
    """ADR-0236 §8 item 11, and the obligation §7's third clause exists for.

    "Over ``app/composition.py``'s own wiring, with ``Settings`` carrying the pair and
    a connected account: the declaration the built ``WebSearchIntegration`` registers
    is ``PER_CALL`` with that amount and that code."

    **Not asserted over the builder called directly**, which is what
    ``tests/tools/test_web_search_cost.py`` does — "it is exactly the assertion a
    composition root that dropped the pair would still pass". A lane that landed the
    fields, the builder and every other test while this root passed neither value
    would leave **every configured deployment at ``UNKNOWN``** with a green gate,
    which is precisely the failure the whole decision exists to remove.

    Read off the searcher the loop actually holds, rather than off the builder's
    return value, so a root that built one declaration and wired another would fail.
    """
    engine = build_engine(_settings(configured=True, priced=True), data_dir=tmp_path)
    try:
        servicer = engine._loop._search
        assert servicer is not None, "a configured deployment services searches"
        searcher = servicer._searcher
        assert isinstance(searcher, WebSearchEgress), "the production searcher, not a fake"
        declared = searcher._declaration

        assert declared.cost.basis is not CostBasis.FREE, "ADR-0236 §3: unreachable from here"
        assert declared.cost.basis is CostBasis.PER_CALL
        assert declared.cost.amount == FIGURE
        assert declared.cost.currency == CODE
    finally:
        await engine.aclose()


async def test_a_deployment_that_declared_no_figure_is_wired_at_unknown(tmp_path: Path) -> None:
    """§8 item 11's companion, which keeps the arm above from passing vacuously.

    ADR-0236 §4: "Where neither field is set the declaration's ``cost`` is
    ``ToolCost(basis=CostBasis.UNKNOWN)``" — the shipped default, and the state the
    decision makes legible rather than accidental. Without this row a root that hard
    coded a ``PER_CALL`` cost would pass the one above.
    """
    engine = build_engine(_settings(configured=True), data_dir=tmp_path)
    try:
        servicer = engine._loop._search
        assert servicer is not None
        searcher = servicer._searcher
        assert isinstance(searcher, WebSearchEgress), "the production searcher, not a fake"
        declared = searcher._declaration

        assert declared.cost.basis is CostBasis.UNKNOWN
        assert declared == WEB_SEARCH, "the template, registered unchanged"
    finally:
        await engine.aclose()


async def test_a_cost_pair_with_no_search_account_is_refused_at_settings_load() -> None:
    """ADR-0236 §2's registration-whole clause, at the wiring it protects.

    "A per-call figure for a searcher no deployment builds is a value nothing reads,
    and the quiet reading of it is the unsafe one." This root builds no
    ``WebSearchIntegration`` at all where the registration pair is absent, so the
    figure would reach no builder — refused at load instead, in
    ``_the_search_registration_is_whole_or_absent``'s own shape.

    Asserted here beside the wiring it is about as well as in
    ``tests/core/test_config.py``, for
    ``test_half_a_search_registration_is_refused_at_settings_load``'s reason one field
    pair along.
    """
    with pytest.raises(ValueError, match="web_search_connection"):
        Settings(
            embedder=EmbedderKind.HASHING,
            web_search_cost_per_call=FIGURE,
            web_search_cost_currency=CODE,
        )
