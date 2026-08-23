"""Registering `send_email` at the designated seam, and what a registration buys.

The lane that closes #1152. ADR-0154 §1 designated
:mod:`ai_assistant.tools.egress` and §4 attested ADR-0017 §3's fourteen
conditions; ADR-0155 answered #95, which is what ADR-0154 §6's third clause made
blocking for **any** registration at the seam. What was left was the registration
itself, and these are the properties it has to have.

Four of them, and they are not the same property:

1. **Registration is a deployment fact and both halves come from one value.** The
   registry's contents and the binding seam's registration table are derived from
   the same :class:`~ai_assistant.tools.builtin.EgressIntegration`, so "registered
   but unbound" — a tool selection can reach and the seam then refuses on every
   call under ADR-0152 §8 — is unreachable rather than merely unlikely.
2. **ADR-0152 §8's partition still bites**, and now it bites in the direction that
   matters: an unconfigured deployment holds no ``send_email`` at all, and a
   deployment that somehow held the declaration without the registration is
   refused rather than answered "not an egress call".
3. **Selection reaches it** (ADR-0144), so a plan naming its capability finds it.
4. **The spine reaches the transport**: an authorised call goes registry →
   ``invoke`` → callable → transport, carrying the binding the ruling fixed and
   nothing re-derived.

**Nothing here opens a socket.** The channel is
:class:`~egress_transport_harness.ScriptedChannel` and the connector is passed, so
the one function in the tree that reaches the network is never the one called —
see :mod:`egress_transport_harness`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
from egress_transport_harness import (
    CREDENTIAL,
    ENDPOINT,
    IDENTITY,
    REFERENCE,
    SLOT,
    Records,
    ScriptedChannel,
    arguments,
    entry,
    implicit_tls_script,
    keyring,
)

from ai_assistant.core.errors import EgressBindingError, ToolBindingError
from ai_assistant.core.types import (
    ActionRequest,
    BoundAccount,
    CarriedProvenance,
    EgressBinding,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ToolCall,
    ToolOutcome,
    parameter_violations,
)
from ai_assistant.orchestration.selection import Preference, eligible_candidates, select
from ai_assistant.testing import FakeMemoryStore
from ai_assistant.tools import (
    CURRENT_TIME,
    RECALL_MEMORY,
    build_default_registry,
    build_send_email_integration,
    egress_registrations,
)
from ai_assistant.tools.egress import TransportPinError
from ai_assistant.tools.egress_binder import EgressBindingSeam
from ai_assistant.tools.send_email import SEND_EMAIL, SEND_EMAIL_ID

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from egress_transport_harness import Keyring

    from ai_assistant.core.types import FrozenJson, ToolDefinition
    from ai_assistant.tools.builtin import EgressIntegration

DECIDED_AT: Final = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)

#: Long enough that no case in this file is racing the invocation deadline, and
#: finite because ADR-0029 §4 gives the seam no way to be called without one.
TIMEOUT: Final = timedelta(seconds=30)


async def _configured(
    *, channel: ScriptedChannel | None = None, records: Records | None = None
) -> tuple[EgressIntegration, Keyring]:
    """One deployment that configured the integration, wired to a scripted endpoint.

    Args:
        channel: The byte channel the transport is handed, or ``None`` for one no
            case reaches.
        records: The connection store's scripted answers; defaults to one active
            record that never moves.

    Returns:
        The integration and the recording keyring, so a case can assert on both.
    """
    ring = await keyring()
    integration = build_send_email_integration(
        connection=REFERENCE,
        endpoint=ENDPOINT,
        records=Records(entry()) if records is None else records,
        secrets=ring,
        connect=None if channel is None else _connector(channel),
    )
    return integration, ring


def _connector(channel: ScriptedChannel) -> Callable[[object], Awaitable[ScriptedChannel]]:
    """A connector that hands back ``channel`` and never opens anything.

    Args:
        channel: The scripted endpoint every case in this file talks to.

    Returns:
        Something shaped like the transport's own connector, which is the whole
        reason that is a constructor argument.
    """

    async def connect(endpoint: object) -> ScriptedChannel:
        return channel

    return connect


def _seam(integration: EgressIntegration | None, registry: object) -> EgressBindingSeam:
    """The binding seam over the same registry and the same registration table.

    Args:
        integration: The configured integration, or ``None``.
        registry: The registry, injected as its own ``RegisteredDefinitions`` face.

    Returns:
        The seam a composition root would build for that pair.
    """
    return EgressBindingSeam(
        definitions=registry,  # type: ignore[arg-type]  # the registry is the face
        registrations=egress_registrations(integration),
        records=Records(entry()),
    )


def _authorised(parameters: Mapping[str, FrozenJson], binding: object) -> ToolCall:
    """One authorised call for ``send_email``, as the runner would have built it.

    Args:
        parameters: The call's arguments.
        binding: The binding the seam derived.

    Returns:
        The call, which is unconstructable unless the decision authorises it.
    """
    request = ActionRequest(
        tool=SEND_EMAIL,
        parameters=parameters,
        step_id="step-1",
        egress_binding=binding,  # type: ignore[arg-type]  # a case supplies None deliberately
    )
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="the user confirmed the send"),
        id="d-1",
        decided_at=DECIDED_AT,
    )
    return ToolCall(request=request, decision=decision)


# --------------------------------------------------------------------------- #
# 1. one value, both halves
# --------------------------------------------------------------------------- #


async def test_a_configured_deployment_registers_the_tool_and_binds_it_to_one_account() -> None:
    """Both halves, from one value (ADR-0148 §6, ADR-0152 §10).

    The registry holds the declaration and the seam's table holds the registration
    for the **same** id, because ``build_default_registry`` and
    ``egress_registrations`` were handed the same ``EgressIntegration``. Asserted
    together in one case on purpose: separately they are two facts that happen to
    agree, and what the design buys is that they cannot disagree.
    """
    integration, _ = await _configured()
    registry = build_default_registry(memory=FakeMemoryStore(), egress=integration)

    assert await registry.get(SEND_EMAIL_ID) == SEND_EMAIL
    assert SEND_EMAIL.capability in await registry.capabilities()

    registration = egress_registrations(integration).registration(SEND_EMAIL_ID)
    assert registration is not None
    assert registration.reference == REFERENCE
    assert registration.transport_endpoint == ENDPOINT


async def test_the_registration_the_table_holds_is_the_one_the_transport_holds() -> None:
    """One object, not two equal ones (ADR-0148 §6).

    The transport compares a binding's connection reference against *its*
    registration's before it reads a record, and the seam reads a record **by** the
    table's registration. Two equal-but-separate registrations would satisfy every
    assertion in this file and would still admit a future edit moving one without
    the other, which is exactly the pair ``_pinned`` exists to catch.
    """
    integration, _ = await _configured()

    assert egress_registrations(integration).registration(SEND_EMAIL_ID) is (
        integration.registration
    )


async def test_an_unconfigured_deployment_holds_neither_half() -> None:
    """No account, no tool, no registration (ADR-0148 §6).

    The important half is the second: an empty registration table is not an inert
    default here, it is what keeps ADR-0152 §8's mis-registration refusal
    reachable.
    """
    registry = build_default_registry(memory=FakeMemoryStore())

    assert {tool.id for tool in await registry.all_tools()} == {CURRENT_TIME.id, RECALL_MEMORY.id}
    assert egress_registrations(None).registration(SEND_EMAIL_ID) is None


def test_an_endpoint_this_seam_will_not_pin_is_refused_at_wiring_rather_than_at_a_send() -> None:
    """A misconfigured deployment fails to start, not to send (#83).

    The parse is discarded — what the transport compares per call is the text,
    before parsing (ADR-0154's condition 5) — so this is purely a fail-fast on the
    operator's configuration. The alternative is a hub that starts, accepts a turn,
    asks the user to confirm a send, and *then* discovers it cannot open the
    endpoint it was told to use.
    """
    with pytest.raises(TransportPinError, match="scheme"):
        build_send_email_integration(
            connection=REFERENCE,
            endpoint="https://mail.example.invalid",
            records=Records(entry()),
            secrets=None,  # type: ignore[arg-type]  # never reached; the parse refuses first
        )


# --------------------------------------------------------------------------- #
# 2. ADR-0152 §8's partition
# --------------------------------------------------------------------------- #


async def test_a_send_with_no_connected_account_is_refused_not_answered_none() -> None:
    """ADR-0152 §8's partition, at the boundary this lane created (#1152).

    A tool whose schema declares either §3 keyword while it is bound to no
    connected account is **mis-registered**, and the seam says so rather than
    answering that this is not an egress call — because "answering that it is not
    an egress call would silently discard a declaration its author wrote".

    This is the case the whole conditional-registration design exists to keep
    unreachable in production: it is arranged here by hand, registering the
    declaration while giving the seam an empty table, because a composition root
    cannot produce it.
    """
    registry = build_default_registry(memory=FakeMemoryStore())
    registry.register(SEND_EMAIL, _never_called)
    seam = _seam(None, registry)

    with pytest.raises(EgressBindingError, match="mis-registered"):
        await seam.bind(
            SEND_EMAIL,
            parameters=arguments(),
            provenance=CarriedProvenance(spans={}, planned_with_external_content=False),
        )


async def _never_called(parameters: object, *, idempotency_key: object) -> None:
    """A callable the case above never reaches, because the seam refuses first."""
    msg = "the seam should have refused before any callable ran"
    raise AssertionError(msg)


# --------------------------------------------------------------------------- #
# 3. selection reaches it
# --------------------------------------------------------------------------- #


async def test_selection_reaches_the_registered_tool_when_it_is_the_one_capable_candidate() -> None:
    """ADR-0144's ordering selects it, and ADR-0145's fit filter keeps it (§7).

    A registration that the selection stage could not reach would be a tool nobody
    can invoke through a plan, so this walks the two steps that stand between
    ``find`` and a ruling: eligibility over the step's arguments, then the §§2-4
    key. With one capable candidate the ordering is trivial — which is the point,
    because what is being checked is that the declaration *survives* both stages,
    not that it wins a contest.
    """
    integration, _ = await _configured()
    registry = build_default_registry(memory=FakeMemoryStore(), egress=integration)

    candidates: Sequence[ToolDefinition] = await registry.find(SEND_EMAIL.capability)
    assert [tool.id for tool in candidates] == [SEND_EMAIL_ID]

    fit = eligible_candidates(arguments(), candidates)
    assert fit.failure is None
    assert [tool.id for tool in fit.eligible] == [SEND_EMAIL_ID]

    chosen = select(fit.eligible, Preference(()))
    assert chosen.tool == SEND_EMAIL
    assert chosen.tied == ()


# --------------------------------------------------------------------------- #
# 4. the spine, to the transport
# --------------------------------------------------------------------------- #


async def test_an_authorised_call_reaches_the_transport_and_the_message_goes_out() -> None:
    """Registry to wire, through every check ADR-0029 §2 puts in the way.

    The spine this lane exists to close. ``invoke`` revalidates and detaches the
    call, compares the definition against the registry's own original, re-evaluates
    ``decision.authorises``, hands the callable the binding the decision carries,
    and the callable hands binding and arguments to the transport unchanged. What
    proves it went all the way is the octets on the scripted channel — a
    ``SUCCEEDED`` result alone would be satisfiable by a callable that returned
    without doing anything.
    """
    channel = ScriptedChannel(*implicit_tls_script())
    integration, ring = await _configured(channel=channel)
    registry = build_default_registry(memory=FakeMemoryStore(), egress=integration)
    seam = _seam(integration, registry)

    parameters = arguments()
    bound = await seam.bind(
        SEND_EMAIL,
        parameters=parameters,
        provenance=CarriedProvenance(spans={}, planned_with_external_content=False),
    )
    assert bound is not None

    result = await registry.invoke(
        _authorised(dict(bound.parameters), bound.binding), timeout=TIMEOUT
    )

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.output is None
    written = channel.written.decode()
    assert f"MAIL FROM:<{IDENTITY}>" in written
    assert "RCPT TO:<Alice@example.invalid>" in written, (
        "the canonical form the ruling fixed, not the supplied one and not a "
        "re-derivation (ADR-0148 §4)"
    )
    assert "attached, as promised" in written
    assert ring.reads == [SLOT], "the credential is read once, at the transport"
    # The credential travels inside AUTH PLAIN base64-encoded; the plaintext must
    # not appear, which is what the transport's own redaction is for.
    assert CREDENTIAL not in written


async def test_the_singular_phrasing_validates_binds_and_reaches_the_wire() -> None:
    """#1160 closed, over the **real** ``SEND_EMAIL`` and the whole chain (ADR-0157 §7).

    §7 puts this obligation on the implementing lane by name, and says why every
    other test in its list can pass while #1160 stays open: a lane could widen the
    flatness check, widen the transport, prove both against a *synthetic* tool
    declaring the third form, leave this tool's own ``to`` array-only, and ship a
    green suite over the exact call #1159 recorded as refused.

    So the subject here is ``SEND_EMAIL`` itself, and the call is the one leg 12's
    QA run measured — "send an email to X", which the planner composes as a bare
    string because it is tool-blind by design (ADR-0044 lineage) and picks the form
    the sentence's grammar suggests. Three assertions, one per stage that used to
    stop it: ADR-0145's schema validation reports **no** violation, so the step is
    no longer refused as ``step_parameters_invalid``; the seam binds it, into the
    single indexless span ADR-0150 §4 gives a string (ADR-0157 §3); and the octets
    reach the scripted endpoint.
    """
    channel = ScriptedChannel(*implicit_tls_script())
    integration, ring = await _configured(channel=channel)
    registry = build_default_registry(memory=FakeMemoryStore(), egress=integration)
    seam = _seam(integration, registry)
    parameters: Mapping[str, FrozenJson] = {
        "to": "Alice@Example.Invalid",
        "subject": "quarterly report",
        "body": "attached, as promised",
    }

    assert parameter_violations(SEND_EMAIL.parameters_schema, parameters) == ()

    bound = await seam.bind(
        SEND_EMAIL,
        parameters=parameters,
        provenance=CarriedProvenance(spans={}, planned_with_external_content=False),
    )
    assert bound is not None
    recipients = [span for span in bound.binding.spans if span.destination is not None]
    assert [span.index for span in recipients] == [None]

    result = await registry.invoke(
        _authorised(dict(bound.parameters), bound.binding), timeout=TIMEOUT
    )

    assert result.outcome is ToolOutcome.SUCCEEDED
    written = channel.written.decode()
    assert "RCPT TO:<Alice@example.invalid>" in written
    assert ring.reads == [SLOT]


async def test_a_transport_refusal_comes_back_as_a_classified_failure_not_an_escape() -> None:
    """ADR-0029 §3: the tool's failure is data, and the message quotes nothing.

    The transport refuses a binding naming an endpoint this tool is not registered
    for. ``SendEmail`` catches nothing, so the refusal escapes the callable — and
    ``run_bound_call`` classifies it ``INTERNAL`` and names only the exception's
    type, never ``str(exc)``, which is where a recipient would otherwise arrive in
    a Tier 2 failure text.
    """
    integration, ring = await _configured()
    registry = build_default_registry(memory=FakeMemoryStore(), egress=integration)
    seam = _seam(integration, registry)

    parameters = arguments()
    bound = await seam.bind(
        SEND_EMAIL,
        parameters=parameters,
        provenance=CarriedProvenance(spans={}, planned_with_external_content=False),
    )
    assert bound is not None
    moved = bound.binding.model_copy(update={"transport_endpoint": "smtps://elsewhere.invalid:465"})

    result = await registry.invoke(_authorised(dict(bound.parameters), moved), timeout=TIMEOUT)

    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert "TransportPinError" in result.failure.message
    assert "elsewhere.invalid" not in result.failure.message
    assert ring.reads == [], "a refusal decidable from the binding reads no credential"


# --------------------------------------------------------------------------- #
# 5. the invocation seam pairs the two callable shapes with the call
# --------------------------------------------------------------------------- #


async def test_an_egress_callable_reached_without_a_binding_is_refused() -> None:
    """A mis-paired registration fails closed (ADR-0148 §4, ADR-0152 §8).

    Unreachable through a correctly wired registry, which is the argument *for*
    the check: which callable a declaration binds is `tools/`-internal and
    contracted nowhere (ADR-0152 §10), so nothing else in the system would notice
    a root that paired them wrongly. A transport handed no account, no endpoint
    and no destination set has nothing to hold itself to.
    """
    integration, ring = await _configured()
    registry = build_default_registry(memory=FakeMemoryStore(), egress=integration)

    with pytest.raises(ToolBindingError, match="no egress binding"):
        await registry.invoke(_authorised(arguments(), None), timeout=TIMEOUT)

    assert ring.reads == []


async def test_an_ordinary_callable_reached_with_a_binding_is_refused() -> None:
    """The mirror image, and the more dangerous one (ADR-0148 §4).

    A ruling was taken over a canonical destination set and a payload description,
    and the callable about to run cannot see either — so nothing would hold what is
    transmitted to what was authorised. Arranged over ``current_time`` because any
    ordinary tool will do: the fault is in the pairing, not in the tool.
    """
    integration, _ = await _configured()
    registry = build_default_registry(memory=FakeMemoryStore(), egress=integration)

    # A binding with no spans, because ``current_time`` takes no arguments and
    # ADR-0150 §4 makes a span name one the call carries. The account and the
    # endpoint are the parts that matter here: they are what a ruling fixed and
    # what the callable about to run cannot see.
    request = ActionRequest(
        tool=CURRENT_TIME,
        parameters={},
        step_id="step-1",
        egress_binding=EgressBinding(
            spans=(),
            account=BoundAccount(identity=IDENTITY, reference=REFERENCE),
            transport_endpoint=ENDPOINT,
            planned_with_external_content=False,
        ),
    )
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="a clock read"),
        id="d-2",
        decided_at=DECIDED_AT,
    )

    with pytest.raises(ToolBindingError, match="takes no egress binding"):
        await registry.invoke(ToolCall(request=request, decision=decision), timeout=TIMEOUT)
