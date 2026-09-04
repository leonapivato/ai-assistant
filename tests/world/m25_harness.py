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

**Where this arm departs from a literal reading of §9, and why** — one edge,
narrowed twice under review. The bound call is driven through the composition's
**own** registered ``SmtpEgressTransport`` (:func:`drive_a_bound_call`), so the
seam, the registration, the endpoint, the connection store and the capability are
all this deployment's. The single thing an offline gate cannot supply is the
credential: the root wires
:class:`~ai_assistant.secret_store.KeyringSecretStore`, and ADR-0125 §7 is
categorical that this seam never falls back to a file, an environment variable or
an in-memory map — so provisioning one here would either write the developer's
real OS keyring or need exactly the escape hatch that ADR refuses. That one face,
and nothing else, is displaced by :func:`arrange_the_seams_collaborators`, which
asserts the wiring it displaces before displacing it. Recorded as issue #1560
against ADR-0191 §9 rather than edited into the ADR.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from functools import partial
from types import FunctionType, MethodType, ModuleType
from typing import TYPE_CHECKING, Any, Final, cast, final

from keyring.errors import PasswordDeleteError
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
    Reversibility,
    RiskLevel,
    SpanCoverage,
    ToolCall,
    ToolCost,
    ToolDefinition,
    TransportEndpoint,
)
from ai_assistant.secret_store import KeyringSecretStore
from ai_assistant.testing import FakeByteChannel, FakeOutboundTransport
from ai_assistant.tools.egress import SmtpEgressTransport
from ai_assistant.tools.provisioning import KeyringConnectionProvisioner
from ai_assistant.tools.registry import InMemoryToolRegistry
from ai_assistant.tools.send_email import SEND_EMAIL, SendEmail

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ai_assistant.app import Composition
    from ai_assistant.core.protocols import OutboundTransport
    from ai_assistant.core.types import FrozenJson, ToolResult

# --- the deployment this arm builds -----------------------------------------

#: The account the deployment connects, and the endpoint it is configured to
#: reach. ``.invalid`` (RFC 6761 §6.4), so a case that somehow got past every
#: instrument here would fail at a resolver rather than connect. The connection
#: *reference* is not a constant: ADR-0151 §3 has the provisioning act mint it, so
#: it is whatever :func:`provision` returns.
IDENTITY: Final = "owner@example.invalid"
HOST: Final = "mail.example.invalid"
PORT: Final = 465
ENDPOINT: Final = f"smtps://{HOST}:{PORT}"
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


def settings(*, connection: str | None = None) -> Settings:
    """The deployment's configuration, as an operator would have written it.

    Args:
        connection: The connected account's reference, or ``None`` to configure no
            integration at all — ADR-0191 §3's last clause, under which a
            deployment builds no transport and hands out none.

    Returns:
        The settings :func:`build` hands the production composition root.
    """
    configured = (
        {"send_email_connection": connection, "send_email_endpoint": ENDPOINT}
        if connection is not None
        else {}
    )
    # The hashing embedder rather than the vendored on-device one: this arm asserts
    # over sockets, and loading an ONNX runtime to do it would buy nothing. It is
    # also what every other composition-root test in this tree uses.
    return Settings(embedder=EmbedderKind.HASHING, **configured)  # type: ignore[arg-type]  # a mapping of two optional str settings


def build(
    tmp_path: Path,
    *,
    capability: FakeOutboundTransport,
    connection: str | None = None,
    backing: Backing | None = None,
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
        connection: The connected account this deployment registers ``send_email``
            against, or ``None`` for a deployment that configures no integration.
        backing: Where the root-wired keyring store reads and writes, or ``None``
            to leave it on the operating system's own. See :func:`point_the_keyring_at`.

    Returns:
        The built composition. The caller closes its engine.
    """
    composition = build_composition(
        settings(connection=connection), data_dir=tmp_path, transport=capability
    )
    if backing is not None:
        point_the_keyring_at(composition, backing)
    return composition


@final
class Backing:
    """An in-memory keyring, as ADR-0125 §11's own seam admits one.

    ``KeyringSecretStore`` takes a ``select`` "for the reason that a caller
    supplying another is how this class is driven against a backend a test
    controls (ADR-0125 §11)", and ``core``'s ``KeyringBackend`` Protocol is
    declared in this repository rather than taken from the library for exactly
    that purpose. So this is the sanctioned lever and not a way past ADR-0125 §7's
    refusal to fall back: the *selection* is replaced by a test, which §11
    provides for, rather than the refusal being defeated by a backend pretending
    to be a platform one.

    Attributes:
        entries: What is stored, by service and username.
    """

    def __init__(self) -> None:
        """Start holding nothing."""
        self.entries: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        """Return what is stored at a coordinate, or ``None``."""
        return self.entries.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        """Store a value at a coordinate, replacing whatever was there."""
        self.entries[service_name, username] = password

    def delete_password(self, service_name: str, username: str) -> None:
        """Remove the entry at a coordinate.

        Raises:
            PasswordDeleteError: If there is none, as the library's own do.
        """
        if self.entries.pop((service_name, username), None) is None:
            msg = "no entry under that coordinate"
            raise PasswordDeleteError(msg)


def point_the_keyring_at(composition: Composition, backing: Backing) -> None:
    """Give the deployment's own keyring store an in-memory backing.

    **The store is the root-wired one and stays the root-wired one**; what is
    replaced is its backend *selection*, which is the lever ADR-0125 §11 put on
    that class for a test to use. That matters for what the arm may claim: the
    credential the seam reads is the one the production provisioning act wrote,
    through the production store, under the production slot — nothing on the path
    between the composition root and ``open_channel`` is displaced.

    An earlier draft replaced the seam's ``Secrets`` face outright, which
    architecture review rightly called a different object graph.

    Args:
        composition: The built deployment.
        backing: Where its keyring reads and writes.
    """
    provisioner = composition.engine._connections._provisioner
    assert isinstance(provisioner, KeyringConnectionProvisioner)
    store = provisioner._secrets
    # Narrowed to the concrete store, which is part of the claim: the lever below
    # is that class's own (ADR-0125 §11), and a root that had wired something else
    # would fail here rather than silently accept an attribute nobody reads.
    assert isinstance(store, KeyringSecretStore)
    store._select = lambda: backing


async def provision(tmp_path: Path, backing: Backing) -> str:
    """Connect one account through the production surface, and say what it minted.

    ``Engine.connect_account`` is the shipped act (ADR-0151 §5): it mints the
    reference, writes the connection record and puts the credential in the keyring,
    all through the objects the composition root wired. The deployment it runs
    against configures no integration, because the reference it is about to mint is
    the one the *measured* deployment will be configured with — a reference cannot
    be named in configuration before the act that mints it has run (ADR-0151 §3).

    Args:
        tmp_path: The data directory both deployments share.
        backing: The in-memory keyring both deployments read.

    Returns:
        The minted connection reference.
    """
    composition = build_composition(settings(), data_dir=tmp_path, transport=None)
    point_the_keyring_at(composition, backing)
    try:
        account = await composition.engine.connect_account(
            identity=IDENTITY, credential=SecretStr(CREDENTIAL)
        )
    finally:
        await composition.engine.aclose()
    return account.reference


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


def every_tool_that_can_reach_a_transport(
    composition: Composition,
) -> dict[str, tuple[OutboundTransport, ...]]:
    """Which registered tools can reach a transport, and every route each reaches.

    **This is the handout measured over the population that exists**, rather than
    over one tool's self-report. ``the_capability_the_root_handed_out`` establishes
    that the seam holds *this* fake; what it cannot say is that nothing *else* the
    production root registered holds a transport too — and a regression that
    handed the capability to a second, undesignated tool is exactly the failure
    ADR-0191 §3 is written against. Adversarial review pressed on that gap across
    rounds 6 and 7.

    **What it cannot do, stated plainly.** The production root builds one
    integration that receives a transport; it has no general tool-construction path
    a test-authored probe could be built through, and adding one would be the
    "back door added only for tests" ADR-0191 §3 refuses. So the probe is still
    registered by this arm — and this survey is what reads whether the probe,
    sitting in the composition, can reach a route at all.

    **The walk is exhaustive rather than first-match**, which round 8 of review is
    why: a tool holding its route in a list — ``self.routes = [transport]`` — can
    open a channel with ``self.routes[0]`` while a survey that read only
    attributes, stopped at the first hit and refused to enter containers reported
    it route-free. So this follows containers as well as attributes, keeps going
    after it finds one, and carries an identity set so a cycle terminates. The
    armed probe holds its route *inside a tuple* for the same reason: the control
    exercises the traversal that the false negative lived in.

    It reads objects rather than any source text (ADR-0191 §9's last clause): a
    thing that can open a channel is a thing with an ``open_channel`` to call.

    **It is a net and not a proof, in ADR-0017 §4's exact sense, and the exit does
    not rest on it.** Reachability over a Python object graph has no complete
    reading: this one follows attributes, containers, closure cells, bound methods
    and partials, and something could still hold a route behind a computed
    property, a C extension or a weak reference. So its finding a route means
    something strong — a tool that can reach one — and its finding none means
    something weaker: nothing it can see. ADR-0191 §9's exit rests on the four
    instruments that ADR enumerates; this is a fifth, kept as defence in depth for
    the same reason §7 keeps the import contracts, and claimed no more widely.
    Rounds 8 and 9 each found a traversal shape it missed, which is the evidence
    for that labelling rather than an argument against the instrument.

    Args:
        composition: The built deployment.

    Returns:
        Tool id to the routes that tool can reach, in the order found, for every
        registered tool that can reach one. Empty where none can.
    """
    reachable: dict[str, tuple[OutboundTransport, ...]] = {}
    for tool_id, binding in registry(composition)._live.items():
        routes = routes_reachable_from(binding.implementation)
        if routes:
            reachable[tool_id] = routes
    return reachable


def routes_reachable_from(holder: object) -> tuple[OutboundTransport, ...]:
    """Every distinct route reachable from one object, which is the survey's walk.

    The survey over the registry is this applied to each binding; exposed on its
    own so the walk can be controlled directly over the shapes review has found it
    missing — a container, a closure's cell, a shared object reached down two
    branches — without registering a tool for each.

    Args:
        holder: Where to start.

    Returns:
        The routes, in the order found, folded by identity.
    """
    found: list[OutboundTransport] = []
    for route in _routes_reachable_from(holder, depth=_SURVEY_DEPTH, seen={}):
        if not any(other is route for other in found):
            found.append(route)
    return tuple(found)


@final
class RouteHolder:
    """Something this world defines that holds one thing, for the walk's controls.

    The walk reads attributes only off types this world defines (see
    :func:`_attributes_of`), so a control's holder has to be one of them rather
    than a class the test module keeps to itself.

    Attributes:
        held: Whatever it holds — another holder, a container of them, or a route.
    """

    def __init__(self, held: object) -> None:
        """Hold ``held``.

        Args:
            held: What this holder holds.
        """
        self.held = held


#: How many objects deep the survey walks from a registered tool. The longest
#: legitimate path in this composition is three — ``SendEmail`` to its
#: ``SmtpEgressTransport`` to the capability — and a container adds a level per
#: nesting, so the bound is set well above the shapes that exist rather than
#: tightly around them: a bound that just fits is a bound a regression steps over.
_SURVEY_DEPTH: Final = 8

#: What the walk will not enter, because a route is never inside one and entering
#: them turns a reading into a graph search over the standard library.
_OPAQUE: Final = (str, bytes, bytearray, memoryview, type, ModuleType)


def _routes_reachable_from(
    holder: object, *, depth: int, seen: dict[int, tuple[int, object]]
) -> Iterator[OutboundTransport]:
    """Every object reachable from ``holder`` that can open a channel.

    **The visited record keeps the budget an object was reached with**, not just
    that it was reached. A shared object first met down a long branch has little
    depth left, so its own children go unwalked; met again down a short branch it
    would have plenty, and a set-shaped guard would suppress that second visit and
    lose the route under it. Round 9 of review found that ordering dependence. The
    record also keeps a reference to each visited object, because ``id`` is unique
    only among *live* objects and a temporary could otherwise be collected and its
    address reused underneath the record.

    Args:
        holder: Where to start, which is a registered tool's callable.
        depth: How many objects deep to walk before giving up.
        seen: Identity to the greatest remaining depth it has been visited with,
            and the object itself.

    Yields:
        Each route found, which the caller folds by identity.
    """
    visited, _ = seen.get(id(holder), (-1, None))
    if depth == 0 or visited >= depth or isinstance(holder, _OPAQUE):
        return
    seen[id(holder)] = (depth, holder)
    if callable(getattr(holder, "open_channel", None)):
        yield cast("OutboundTransport", holder)
        return
    for value in _values_within(holder):
        yield from _routes_reachable_from(value, depth=depth - 1, seen=seen)


def _values_within(holder: object) -> Iterator[object]:
    """What an object holds: a container's items, a callable's captures, or attributes.

    Args:
        holder: The object to read.

    Yields:
        Each value it holds.
    """
    if isinstance(holder, Mapping):
        yield from holder.keys()
        yield from holder.values()
        return
    if isinstance(holder, (list, tuple, set, frozenset, deque)):
        yield from holder
        return
    if isinstance(holder, (FunctionType, MethodType, partial)):
        yield from _captures_of(holder)
        return
    yield from _attributes_of(holder)


def _captures_of(holder: FunctionType | MethodType | partial[object]) -> Iterator[object]:
    """What a callable carries with it, which is where a closure keeps a route.

    A registered tool may be a plain function over a captured transport — the
    registry takes any callable, structurally — and a capture lives in a cell
    rather than in an attribute, so a walk that read only attributes reported such
    a tool route-free. Round 9 of review found that shape.

    Args:
        holder: A function, a bound method, or a partial.

    Yields:
        Each object the callable carries: cell contents, default arguments, a
        bound instance, or a partial's applied arguments.
    """
    if isinstance(holder, MethodType):
        yield holder.__self__
        yield holder.__func__
        return
    if isinstance(holder, partial):
        yield holder.func
        yield from holder.args
        yield from holder.keywords.values()
        return
    for cell in holder.__closure__ or ():
        with suppress(ValueError):  # an unfilled cell holds nothing yet
            yield cell.cell_contents
    yield from holder.__defaults__ or ()
    yield from (holder.__kwdefaults__ or {}).values()


def _attributes_of(holder: object) -> Iterator[object]:
    """The attribute values held by an object this world defines.

    Bounded to this world's own types — ``ai_assistant``'s and this harness's —
    because those are what a registered tool and its collaborators are, and
    reading a logger's or a pydantic model's internals would be a graph search
    rather than a reading.

    Args:
        holder: The object to read.

    Yields:
        Each attribute value it holds, whether it keeps them in ``__dict__`` or in
        ``__slots__``.
    """
    if type(holder).__module__.split(".")[0] not in {"ai_assistant", "m25_harness"}:
        return
    names: list[str] = list(vars(holder)) if hasattr(holder, "__dict__") else []
    for kind in type(holder).__mro__:
        names.extend(getattr(kind, "__slots__", ()))
    for name in names:
        value = getattr(holder, name, None)
        if value is not None:
            yield value


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


async def drive_a_bound_call(composition: Composition, reference: str) -> None:
    """Drive **the composition's own registered seam** to one bound call.

    The positive control for the fake (ADR-0191 §9). The object driven is the
    ``SmtpEgressTransport`` the production root constructed and registered — not a
    second one arranged beside it — so the registration it pins against, the
    endpoint it parses and the capability it opens with are all this deployment's.

    **Nothing on the path is displaced.** The connection record was written by
    ``Engine.connect_account`` through the store the root wired, the credential
    was written to the keyring face the root wired, and both are read here by the
    production edges. What an offline gate supplies is only the keyring's
    *backing* — the lever ADR-0125 §11 put on ``KeyringSecretStore`` for exactly
    this — see :func:`point_the_keyring_at`.

    Args:
        composition: The built deployment.
        reference: The connected account the provisioning act minted, which the
            binding names and the seam compares against its registration.
    """
    await _seam(composition).transmit(binding(reference), arguments())


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


def binding(reference: str) -> EgressBinding:
    """The binding the ruling fixed for that call.

    Args:
        reference: The connected account the provisioning act minted.

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
        account=BoundAccount(identity=IDENTITY, reference=reference),
        transport_endpoint=ENDPOINT,
        planned_with_external_content=False,
        coverage=SpanCoverage.NOT_COVERED,
    )


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

ARMED_PROBE: Final = PROBE.model_copy(
    update={
        "id": "armed_undesignated_probe",
        "description": "The same probe, handed a route, so the detector is seen to fire.",
    }
)
"""The **positive control** for the probe instrument (ADR-0191 §9's general clause).

A reading of "this tool found no route" is satisfied by a probe that could not have
found one however it was wired, which is the vacuous zero §9 refuses for every
other instrument in this arm. So the same callable is registered a second time —
its own id, because a tool id is a security control and the registry refuses a
second definition under a used one — holding the fake, and driven in the same
composition. Adversarial review found the uncontrolled detector on round 6.
"""

#: Where the armed probe opens its channel, deliberately **not** the configured
#: endpoint. A tool holding the capability reaches an endpoint of its own choosing,
#: which is the reach ADR-0191 §3 makes scarce by handing the capability to one
#: object; a control that reused the seam's endpoint would leave that unsaid.
PROBE_ENDPOINT: Final = TransportEndpoint(host="probe.example.invalid", port=465, implicit_tls=True)


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

    **What it was handed is a required argument, and the arm passes ``None``
    explicitly.** A default would be the shape ADR-0191 §3 exists to delete — an
    object that looks injected and is not — reproduced in the instrument that
    measures §3. So the negative arm *states* that this tool is handed nothing,
    and :data:`ARMED_PROBE`'s control states the opposite in the same composition.

    Attributes:
        reached_for_a_route: Whether the callable ran as far as the point it would
            have acquired a transport.
        route: What it found there, read off what it was handed rather than
            asserted. Round 6 of adversarial review found the earlier reading —
            a ``getattr`` for an attribute ``__slots__`` made unsettable — true by
            construction, which is a detector that cannot fire.
        opened: The endpoint it reached with the route it found, or ``None`` where
            it found none. It is what makes the control a control: the probe not
            only *sees* a capability, it uses one.
    """

    __slots__ = ("_handed", "opened", "reached_for_a_route", "route")

    def __init__(self, *, route: OutboundTransport | None) -> None:
        """Start having reached for nothing, holding whatever the arm handed over.

        Args:
            route: The capability this tool was handed, kept in a container for
                the reason in the body. ``None`` is the arm's statement that it
                was handed none, and is required rather than defaulted for the
                reason in the class docstring.
        """
        # **Held inside a tuple, deliberately.** A route in a container is still
        # a route — a tool could call ``self._handed[0].open_channel(...)`` — and
        # round 8 of review found the survey reading attributes only and so
        # reporting such a tool route-free. The control has to live in the shape
        # the false negative lived in, or it controls the easy half.
        self._handed = () if route is None else (route,)
        self.reached_for_a_route = False
        self.route: OutboundTransport | None = None
        self.opened: TransportEndpoint | None = None

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
            TransportError: Where it was handed no capability — there is then
                nothing to open a channel with, which is the negative arm.
        """
        del parameters, idempotency_key
        self.reached_for_a_route = True
        self.route = self._handed[0] if self._handed else None
        if self.route is None:
            msg = "this tool was handed no outbound transport, so it has no route"
            raise TransportError(msg)
        # Handed one, it reaches an endpoint of its own choosing and the fake
        # records the attempt: the control that makes the zero above mean
        # something (ADR-0191 §9's general clause).
        channel = await self.route.open_channel(PROBE_ENDPOINT)
        await channel.close()
        self.opened = PROBE_ENDPOINT
        return None


def register_probe(
    composition: Composition, probe: UndesignatedProbe, definition: ToolDefinition = PROBE
) -> None:
    """Register ``probe`` into the composition's own registry.

    Into the composition's registry rather than a second one, because ADR-0029 §8
    makes that one object both the selecting ``ToolRegistry`` and the acting
    ``ToolInvoker`` — so a probe registered anywhere else would be invoked through
    a seam this deployment does not use.

    Args:
        composition: The built deployment.
        probe: The callable to bind to ``definition``.
        definition: Which probe this is — :data:`PROBE`, or :data:`ARMED_PROBE`
            for the control. Two ids because a tool id is a security control and
            the registry refuses a second definition under a used one.
    """
    registry(composition).register(definition, probe)


async def drive_the_probe(
    composition: Composition, definition: ToolDefinition = PROBE
) -> ToolResult:
    """Invoke the probe through the composition's own invocation seam.

    The decision is built here rather than sought from the policy, because what is
    on test is the *handout* and not the gate: a probe the gate refused would never
    reach a callable, and the arm would be reading a zero produced by the
    permission layer instead of by the absence of a route.

    It is **recorded in this deployment's own trail** before the call, because
    since ADR-0192 §1 the seam claims the authorisation through that trail and a
    decision it did not record authorises nothing. That is what the runner does in
    front of every execution, so recording it here keeps the arm on the production
    path rather than around it — and a probe refused by the consume would be
    another zero produced by something other than the absence of a route.

    Args:
        composition: The built deployment.
        definition: Which probe to drive; see :func:`register_probe`.

    Returns:
        The invocation's result.
    """
    request = ActionRequest(tool=definition, parameters={}, step_id=f"m25-{definition.id}")
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="the arm authorised the probe"),
        id=f"m25-d-{definition.id}",
        decided_at=DECIDED_AT,
    )
    await composition.engine._runner._trail.record(decision)
    return await registry(composition).invoke(
        ToolCall(request=request, decision=decision), timeout=TIMEOUT
    )
