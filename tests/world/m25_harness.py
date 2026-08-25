"""Milestone 25's exit arm: the world it is measured in (ADR-0191 §9).

#1427 states milestone 25's exit as "a tool that tries to reach the world outside
the seam **cannot**, and the test that proves it is the fake transport, not a
grep". ``tests/tools/test_egress_seam.py`` is the grep — an excellent one, kept by
ADR-0191 §7, and not the thing being asked for. This module is the other thing: a
composition built by the **production composition root**, handed one
:class:`~ai_assistant.testing.FakeOutboundTransport` and no other transport, in
which an undesignated tool is driven at the world and the record is read.

**What the arm measures is the handout, and it says so rather than implying it.**
An undesignated tool was handed no capability, so it had none to reach. Nothing
here establishes that such a tool could not have opened a connection by some other
route — ADR-0191 §7's third clause governs what may be claimed, and the answer for
a raw ``socket`` or ``loop.sock_connect`` over one is: nothing. What closes the
distance between "the fake read zero" and "nothing left the device" is the second
instrument below, which sits on the boundary the fake does not.

**Four instruments, and every one of them owes a positive control** (ADR-0191 §9's
general clause). An assertion that a recorder saw nothing is satisfied by a
recorder nothing could ever reach, and a harness that mis-wires its own composition
passes it perfectly. So:

* the **fake transport** is shown live by driving the designated seam to a bound
  call over it and reading exactly one attempt to the configured endpoint;
* each **loop creator instrument** is calibrated by calling that creator on the
  active loop and observing its own refusal, then resetting;
* the **probe's execution marker** is asserted to have fired before its zero is
  accepted, because a probe that was never registered, was not selected, or was
  reduced to a no-op records zero for a reason that has nothing to do with the
  property being measured.

**The arm's predicate is "no creator was called", not "nothing left the device".**
A connection to ``127.0.0.1`` through ``create_connection`` leaves nothing, so an
instrument refusing every call would be refusing on the wrong ground. This arm can
hold the stricter, simpler predicate only because *its own* composition legitimately
opens no socket of any kind: the stores are SQLite files under a temporary
directory, the model seam is constructed and never called, the embedder is the
hashing one, and the transport is the fake. That is a property of this arrangement
and is not a rule about what any composition may open.

**Where this arm departs from a literal reading of §9, and why** — the one place,
narrowed after round 1. The bound call is driven through the composition's **own**
registered ``SmtpEgressTransport`` (:func:`drive_a_bound_call`), so the seam, the
registration, the endpoint and the capability are all this deployment's. What an
offline gate cannot supply is the credential: the seam reads a connection record
and a keyring entry before it opens anything, and the production root wires
:class:`~ai_assistant.secret_store.KeyringSecretStore`, which ADR-0125 §7 forbids
to fall back to a file, an environment variable or an in-memory map. So those two
collaborators — and nothing else — are displaced on the registered object by
:func:`arrange_the_seams_collaborators`, which asserts the wiring it displaces
before displacing it. Recorded as an issue against ADR-0191 §9 rather than edited
into the ADR.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, final

from pydantic import SecretStr

from ai_assistant.app import build_composition
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import TransportError
from ai_assistant.core.types import (
    ActionRequest,
    BoundAccount,
    CostBasis,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ProvisioningState,
    Reversibility,
    RiskLevel,
    SecretName,
    SecretScope,
    ToolCall,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.testing import FakeByteChannel, FakeOutboundTransport
from ai_assistant.tools.connection_store import ConnectionEntry, StoredEntry
from ai_assistant.tools.egress import SmtpEgressTransport
from ai_assistant.tools.provisioning import KeyringConnectionProvisioner
from ai_assistant.tools.registry import InMemoryToolRegistry
from ai_assistant.tools.send_email import SEND_EMAIL, SendEmail

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from ai_assistant.app import Composition
    from ai_assistant.core.protocols import OutboundTransport
    from ai_assistant.core.types import FrozenJson, ToolResult

# --- the deployment this arm builds -----------------------------------------

#: The connected account the deployment configures, and the endpoint it is
#: configured to reach. ``.invalid`` (RFC 6761 §6.4), so a case that somehow got
#: past every instrument here would fail at a resolver rather than connect.
REFERENCE: Final = "conn-m25"
IDENTITY: Final = "owner@example.invalid"
HOST: Final = "mail.example.invalid"
PORT: Final = 465
ENDPOINT: Final = f"smtps://{HOST}:{PORT}"
SLOT: Final = SecretName(scope=SecretScope.INTEGRATION, key="conn-m25-r1")
CREDENTIAL: Final = "an-app-password"

#: The recipient the bound call names, in the supplied form a user would type and
#: the canonical form the ruling fixed.
RECIPIENT_SUPPLIED: Final = "Alice@Example.Invalid"
RECIPIENT_CANONICAL: Final = "Alice@example.invalid"

#: Finite because ADR-0029 §4 gives the invocation seam no way to be called
#: without one, and long enough that nothing here races its own deadline.
TIMEOUT: Final = timedelta(seconds=30)

#: When the one decision this arm builds was taken. Fixed, because a figure that
#: moves with the wall clock is not a measurement.
DECIDED_AT: Final = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def settings(*, integration: bool = True) -> Settings:
    """The deployment's configuration, as an operator would have written it.

    Args:
        integration: Whether to configure the one egress integration. ``False`` is
            ADR-0191 §3's last clause — a deployment that configures no integration
            builds no transport and hands out none — which the arm reads as the
            absence of a handout rather than as an empty one.

    Returns:
        The settings :func:`build` hands the production composition root.
    """
    configured = (
        {"send_email_connection": REFERENCE, "send_email_endpoint": ENDPOINT} if integration else {}
    )
    # The hashing embedder rather than the vendored on-device one: this arm asserts
    # over sockets, and loading an ONNX runtime to do it would buy nothing. It is
    # also what every other composition-root test in this tree uses.
    return Settings(embedder=EmbedderKind.HASHING, **configured)  # type: ignore[arg-type]  # a mapping of two optional str settings


def build(
    tmp_path: Path, *, capability: FakeOutboundTransport, integration: bool = True
) -> Composition:
    """Build one deployment through the production composition root.

    **Through ``build_composition`` and not around it** (ADR-0191 §9). Milestone
    23's harness assembles its world by hand and says why — the root resolved its
    ``ModelProvider`` from ``Settings`` and there was no seam to hand it a fake —
    but this arm's subject *is* the wiring, so a hand-assembled mirror of the root
    would be measuring the mirror. Nothing in the build reaches a network: the
    model seam is constructed and never called, and every store is a SQLite file
    under ``tmp_path``.

    Args:
        tmp_path: Where the deployment's stores live.
        capability: The one transport in this composition, handed by the same route
            the root hands the production implementation (ADR-0191 §3).
        integration: Whether the deployment configures the egress integration.

    Returns:
        The built composition. The caller closes its engine.
    """
    return build_composition(
        settings(integration=integration), data_dir=tmp_path, transport=capability
    )


# --- instrument 1: the fake, and what the root handed it to -----------------


def the_capability_the_root_handed_out(composition: Composition) -> OutboundTransport:
    """The transport object the composition's registered seam actually holds.

    Read out of the composition rather than assumed, because "the fake is the only
    transport in it" is the premise every other assertion in this arm rests on and
    is exactly the kind of premise a mis-wired harness satisfies vacuously.

    Reaching through the private attributes of the runner, the registry binding and
    the tool is what the composition-root tests in ``tests/app`` already do for the
    same reason: the wiring obligations ADR-0042 §2 discharges here are not visible
    on any public surface, and a test that could only see the public one could not
    tell one object from two.

    Args:
        composition: The built deployment.

    Returns:
        The ``OutboundTransport`` the seam would open its channels with.
    """
    return _seam(composition)._transport


def registry(composition: Composition) -> InMemoryToolRegistry:
    """The one object this deployment uses as registry, invoker and definitions.

    Narrowed by ``isinstance`` rather than cast: ADR-0029 §8's obligation is that
    the composition root injects **one** object as both seams, and a harness that
    silently accepted something else would be measuring a deployment this root does
    not build.

    Args:
        composition: The built deployment.

    Returns:
        The registry.
    """
    tools = composition.engine._runner._registry
    assert isinstance(tools, InMemoryToolRegistry)
    return tools


def _seam(composition: Composition) -> SmtpEgressTransport:
    """The composition's own registered egress transport.

    Args:
        composition: The built deployment.

    Returns:
        The ``SmtpEgressTransport`` bound to ``send_email`` in this deployment.
    """
    binding = registry(composition)._live[SEND_EMAIL.id]
    tool = binding.implementation
    assert isinstance(tool, SendEmail)
    transport = tool._transport
    assert isinstance(transport, SmtpEgressTransport)
    return transport


async def drive_a_bound_call(composition: Composition) -> None:
    """Drive **the composition's own registered seam** to one bound call.

    The positive control for the fake (ADR-0191 §9). The object driven is the
    ``SmtpEgressTransport`` the production root constructed and registered — not a
    second one arranged beside it — so the registration it pins against, the
    endpoint it parses and the capability it opens with are all this deployment's.

    What this displaces first, and only this, is the pair of collaborators an
    offline gate cannot supply: the connection record and the ``INTEGRATION``
    keyring face. See :func:`arrange_the_seams_collaborators`, which asserts what
    was there before displacing it, so the wiring is still measured rather than
    merely assumed.

    Args:
        composition: The built deployment.
    """
    await _seam(composition).transmit(binding(), arguments())


def arrange_the_seams_collaborators(composition: Composition) -> None:
    """Give the registered seam a connection record and a credential to read.

    **The one thing in this arm that an offline gate forces.** The seam reads the
    connection record twice around a credential read (ADR-0148 §6) and refuses
    before opening a channel unless both answer, and the production root wires
    :class:`~ai_assistant.secret_store.KeyringSecretStore` — which ADR-0125 §7
    forbids to fall back to a file, an environment variable or an in-memory map.
    Provisioning a credential here would either put one in the developer's own OS
    keyring or need exactly the escape hatch that ADR is written against, so the
    two faces are displaced on the seam itself instead.

    **The wiring they displace is asserted before they displace it**, which is what
    keeps this from hiding the thing it touches: the store the seam was reading is
    the *same object* the provisioner writes through (ADR-0102 §7, ADR-0152 §10),
    and a deployment that had wired a second handle would fail here rather than
    silently pass the control.

    Args:
        composition: The built deployment.
    """
    seam = _seam(composition)
    provisioner = composition.engine._connections._provisioner
    # Narrowed to the concrete provisioner, which is itself part of the claim:
    # ADR-0151 §10 says the root wires "the one implementation", and it is reached
    # through a Protocol everywhere else.
    assert isinstance(provisioner, KeyringConnectionProvisioner)
    assert seam._records is provisioner._store

    seam._records = _Records()
    seam._secrets = _Keyring()


def channel() -> FakeByteChannel:
    """A conforming implicit-TLS endpoint's replies for one accepted message.

    Returns:
        The channel the capability serves for the positive control: greeting,
        ``EHLO``, ``AUTH``, ``MAIL FROM``, one ``RCPT TO``, ``DATA``, the accepted
        message and the ``QUIT`` farewell.
    """
    served = FakeByteChannel(secure=True)
    for reply in (
        "220 mail.example.invalid ESMTP ready",
        "250-mail.example.invalid",
        "250 AUTH PLAIN LOGIN",
        "235 2.7.0 authentication succeeded",
        "250 2.1.0 sender ok",
        "250 2.1.5 recipient ok",
        "354 end data with <CR><LF>.<CR><LF>",
        "250 2.0.0 queued as ABC123",
        "221 2.0.0 closing connection",
    ):
        served.deliver(reply.encode("ascii") + b"\r\n")
    return served


def arguments() -> Mapping[str, FrozenJson]:
    """The bound call's arguments, in the supplied form a user would have typed.

    Returns:
        One recipient, a subject and a body.
    """
    return {
        "to": [RECIPIENT_SUPPLIED],
        "subject": "the quarterly report",
        "body": "attached, as promised",
    }


def binding() -> EgressBinding:
    """The binding the ruling fixed for that call.

    Returns:
        One destination span for the recipient and one non-destination span for
        each text the payload carries, over the configured account and endpoint.
    """
    return EgressBinding(
        spans=(
            EgressSpan(
                argument="body",
                provenance=DiscloserProvenance.USER_AUTHORED,
                extent=len("attached, as promised"),
            ),
            EgressSpan(
                argument="subject",
                provenance=DiscloserProvenance.USER_AUTHORED,
                extent=len("the quarterly report"),
            ),
            EgressSpan(
                argument="to",
                index=0,
                provenance=DiscloserProvenance.USER_AUTHORED,
                extent=len(RECIPIENT_SUPPLIED),
                destination=EgressDestination(
                    protocol=DestinationProtocol.SMTP,
                    supplied=RECIPIENT_SUPPLIED,
                    canonical=RECIPIENT_CANONICAL,
                ),
            ),
        ),
        account=BoundAccount(identity=IDENTITY, reference=REFERENCE),
        transport_endpoint=ENDPOINT,
        planned_with_external_content=False,
    )


@final
class _Records:
    """A ``ConnectionRecords`` face holding one active record that never moves."""

    async def latest(self, reference: str, /) -> StoredEntry | None:
        """The reference's latest entry.

        Args:
            reference: The connection to read.

        Returns:
            The one active entry, whatever is asked for.
        """
        del reference
        return StoredEntry(
            1,
            ConnectionEntry(
                reference=REFERENCE,
                revision=1,
                identity=IDENTITY,
                state=ProvisioningState.ACTIVE,
                slot=SLOT,
            ),
        )


@final
class _Keyring:
    """A ``Secrets`` face holding the one credential the connection record names."""

    async def get(self, name: SecretName) -> SecretStr | None:
        """The credential under ``name``.

        Args:
            name: The slot to read.

        Returns:
            The credential, or ``None`` for any other slot.
        """
        return SecretStr(CREDENTIAL) if name == SLOT else None


# --- instrument 2: every off-device creator the running loop exposes --------

#: The creators this arm wraps: the two ADR-0191 §9 names as a minimum, and the
#: whole of what the running loop offers that reaches **off the device**.
OFF_DEVICE_CREATORS: Final = frozenset({"create_connection", "create_datagram_endpoint"})

#: Creators that stay **on** the device. A Unix domain socket does not leave it
#: (ADR-0084 §1), so it is not ADR-0017 §1's subject and ADR-0191 §5's exclusion of
#: local IPC governs here as everywhere else in that document. Round 3 of
#: ADR-0191's review caught the ADR itself asserting the general form against its
#: own §5.
ON_DEVICE_CREATORS: Final = frozenset({"create_unix_connection", "create_unix_server"})

#: Creators that accept an inbound connection rather than reaching for one. Half of
#: each of ADR-0124's and ADR-0174's boundaries has nothing for an *opener* to
#: govern, which is ADR-0191 §5's structural reason for leaving them out, and the
#: same reasoning excludes a listener here.
INBOUND_CREATORS: Final = frozenset({"create_unix_server", "create_server"})

#: Creators that make no socket of any kind.
LOCAL_CREATORS: Final = frozenset({"create_future", "create_task"})


@final
class LoopCreators:
    """Every off-device creator on one running loop, wrapped to record and refuse.

    The instrument the fake is not (ADR-0191 §9). Adversarial review of ADR-0191's
    first round found the hole this closes: a non-seam tool calling
    ``create_connection`` off the running loop bypasses the fake entirely, so the
    fake reads zero, the positive control reads one, and every assertion passes
    while the connection succeeded. Instrumenting ``create_connection`` alone then
    left ``create_datagram_endpoint`` open — a datagram endpoint reaches a remote
    address without ever creating a connection, so user data leaves the device with
    both records reading zero.

    **It is installed on the *active* loop and calibrated there.** An instrument is
    itself something that can be attached to nothing: wrapped on a stale loop it
    reads zero for exactly the reason a live one does, which is the vacuous zero
    this arm refuses for the fake arriving a second time in the fix for it.

    Attributes:
        calls: The creator names called, in order, each recorded before it refused.
    """

    __slots__ = ("_loop", "_originals", "calls")

    def __init__(self) -> None:
        """Wrap every off-device creator on the loop this is constructed under."""
        self._loop = asyncio.get_running_loop()
        self.calls: list[str] = []
        self._originals: dict[str, Any] = {}
        for name in sorted(OFF_DEVICE_CREATORS):
            self._originals[name] = getattr(self._loop, name)
            setattr(self._loop, name, self._wrapper(name))

    def _wrapper(self, name: str) -> Any:
        """Build the recorder that replaces ``name``.

        Args:
            name: The creator being wrapped.

        Returns:
            A coroutine function that records the call and then refuses it.
        """

        async def recorded(*args: object, **kwargs: object) -> object:
            del args, kwargs
            # Recorded **before** the refusal, so an attempt this arm's composition
            # began is on the record whether or not any byte could have left.
            self.calls.append(name)
            msg = f"this arm opens no socket; loop.{name} was recorded and refused"
            raise ConnectionRefusedError(msg)

        return recorded

    def forget(self) -> None:
        """Discard the record, keeping the wrappers in place."""
        self.calls.clear()

    def remove(self) -> None:
        """Put the loop back exactly as it was found."""
        for name, original in self._originals.items():
            setattr(self._loop, name, original)
        self._originals.clear()

    async def calibrate(self) -> list[str]:
        """Fire **each** wrapper on the active loop and observe its own refusal.

        A calibration of one creator says nothing about another creator's wrapper,
        so this returns what it demonstrated rather than a boolean: the caller
        asserts the set, and a creator whose wrapper was not installed shows up as
        a missing name instead of as a silent zero.

        Returns:
            The creator names that recorded and refused, sorted.

        Raises:
            AssertionError: If a wrapped creator did not refuse, which would mean
                the arm is measuring an instrument that is not attached.
        """
        demonstrated: list[str] = []
        for name in sorted(OFF_DEVICE_CREATORS):
            before = len(self.calls)
            try:
                await getattr(self._loop, name)(_nothing, HOST, PORT)
            except ConnectionRefusedError:
                pass
            else:  # pragma: no cover — only when an instrument is not attached.
                msg = f"loop.{name} did not refuse, so this arm is not instrumented"
                raise AssertionError(msg)
            if len(self.calls) == before + 1 and self.calls[-1] == name:
                demonstrated.append(name)
        self.forget()
        return demonstrated


def _nothing() -> None:  # pragma: no cover — a protocol factory the wrapper never calls.
    """A protocol factory the calibration passes and the wrapper never reaches."""


# --- instrument 3: the undesignated probe -----------------------------------

PROBE: Final = ToolDefinition(
    id="undesignated_probe",
    capability="reach_the_world",
    description="Try to reach the world from outside the designated egress seam.",
    # Declared honestly rather than minimised: this tool would disclose off the
    # device if it could, and a declaration that said otherwise would be the thing
    # ADR-0016 §1 refuses — "a default is a claim".
    risk_level=RiskLevel.HIGH,
    reversibility=Reversibility.IRREVERSIBLE,
    side_effecting=True,
    reads=(),
    writes=(),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
    parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
)
"""A tool that is not the designated seam and wants what the seam has.

It is registered into the composition's own registry, so selection, the definition
comparison ``invoke`` performs and the execution path are all the production ones.
"""


@final
class UndesignatedProbe:
    """The probe's callable: it asks for a route, records that it asked, and fails.

    **The execution marker is the point** (ADR-0191 §9). A probe that was never
    registered, was not selected, or was reduced to a no-op records zero transport
    attempts for a reason that has nothing to do with the property being measured,
    so the arm asserts the marker fired *before* it accepts the zero.

    **It reaches for the capability and for nothing else.** It does not call
    ``asyncio.open_connection`` — that is the nets' ground (ADR-0191 §7) and would
    make this arm's second instrument fire, which is a different measurement. What
    it demonstrates is ADR-0191 §3's property from the inside: there is no
    parameter, setting, module-level instance, accessor function or registry entry
    by which a component that was not handed the capability obtains one, so a tool
    that wants one has nowhere to look.

    Attributes:
        reached_for_a_route: Whether the callable ran as far as the point it would
            have acquired a transport.
        route: What it found there. Always ``None``; kept as an attribute so the
            arm reads a record rather than trusting the sentence above.
    """

    __slots__ = ("reached_for_a_route", "route")

    def __init__(self) -> None:
        """Start having reached for nothing."""
        self.reached_for_a_route = False
        self.route: OutboundTransport | None = None

    async def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        """Try to acquire a route to the world, and fail for want of one.

        Args:
            parameters: The call's arguments, which this tool declares none of.
            idempotency_key: Unused; this tool's idempotency is ``NONE``.

        Returns:
            Never; this raises.

        Raises:
            TransportError: Always. Having been handed no capability, there is
                nothing to open a channel with.
        """
        del parameters, idempotency_key
        self.reached_for_a_route = True
        self.route = getattr(self, "_transport", None)
        if self.route is None:
            msg = "this tool was handed no outbound transport, so it has no route"
            raise TransportError(msg)
        return None  # pragma: no cover — unreachable while the property holds.


def register_probe(composition: Composition, probe: UndesignatedProbe) -> None:
    """Register ``probe`` into the composition's own registry.

    Into the composition's registry rather than a second one, because ADR-0029 §8
    makes that one object both the selecting ``ToolRegistry`` and the acting
    ``ToolInvoker`` — so a probe registered anywhere else would be invoked through
    a seam this deployment does not use.

    Args:
        composition: The built deployment.
        probe: The callable to bind to :data:`PROBE`.
    """
    registry(composition).register(PROBE, probe)


async def drive_the_probe(composition: Composition) -> ToolResult:
    """Invoke the probe through the composition's own invocation seam.

    The decision is built here rather than sought from the policy, because what is
    on test is the *handout* and not the gate: a probe the gate refused would never
    reach a callable, and the arm would be reading a zero produced by the
    permission layer instead of by the absence of a route.

    Args:
        composition: The built deployment.

    Returns:
        The invocation's result.
    """
    request = ActionRequest(tool=PROBE, parameters={}, step_id="m25-probe")
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="the arm authorised the probe"),
        id="m25-d-1",
        decided_at=DECIDED_AT,
    )
    return await registry(composition).invoke(
        ToolCall(request=request, decision=decision), timeout=TIMEOUT
    )
