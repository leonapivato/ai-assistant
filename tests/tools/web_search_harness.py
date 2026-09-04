"""Arranging one authorised search, and a far end that is not a network.

Shared by :mod:`test_web_search` and the composition case that asserts the search
declaration reaches no registry. What varies between those is what the provider
answered and what the connection store did under the credential read; none of it is a
property of the searcher, so the arrangement lives here and the cases stay about
ADR-0231's clauses.

**Nothing here opens a socket, and that is a property of the design rather than of
the arrangement.** :class:`~ai_assistant.tools.egress.HttpsExchange` takes the
outbound-transport capability as a **required** argument with no default (ADR-0191
§3), so an arrangement that forgot to pass one would not construct rather than
quietly reaching the network. Every response and every refusal below is served over
:class:`~ai_assistant.testing.FakeByteChannel`, and hosts are ``.invalid`` (RFC 6761
§6.4) throughout, so a case that somehow did reach a resolver would fail rather than
connect.

**The account facts are the mail harness's**, imported rather than restated: a
connection reference, an identity, a slot and a credential are what a provisioning
act writes for *any* integration, and two spellings of them would be two harnesses
that could disagree about what ADR-0148 §6 is over.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, final

from egress_transport_harness import CREDENTIAL, IDENTITY, REFERENCE, Records, entry, keyring

from ai_assistant.core.errors import SpendCeilingError, TransportError
from ai_assistant.core.types import (
    ActionRequest,
    BoundAccount,
    CarriedProvenance,
    CostBasis,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    SpanCoverage,
    SpendTotal,
    ToolCall,
    ToolCost,
)
from ai_assistant.testing import FakeAuditTrail, FakeByteChannel, FakeOutboundTransport, authorised
from ai_assistant.testing.cancellation import SuspendableResource
from ai_assistant.tools import build_web_search_integration, egress_registrations
from ai_assistant.tools.egress_binder import EgressBindingSeam
from ai_assistant.tools.web_search import WEB_SEARCH

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from egress_transport_harness import Keyring

    from ai_assistant.core.protocols import ByteChannel, SpendGate
    from ai_assistant.core.types import (
        BoundEgressCall,
        FrozenJson,
        SpendAdmissionHandle,
        TransportEndpoint,
    )
    from ai_assistant.testing.cancellation import LoopSuspension
    from ai_assistant.tools.builtin import WebSearchIntegration
    from ai_assistant.tools.egress import WebSearchTransport

#: The connected account's origin. ``.invalid`` (RFC 6761 §6.4), so a case that
#: reached a resolver would fail rather than connect.
ORIGIN: Final = "https://search.example.invalid"

#: The query one composition wrote for the turn under test.
QUERY: Final = "tallest building in porto"

#: The instant the provider's response declares, and the record every mint here is
#: attested to (ADR-0231 §10, ADR-0092 §3). Its IMF-fixdate spelling and its value,
#: kept beside each other so a case can assert on either.
DATE_FIELD: Final = "Fri, 04 Sep 2026 12:00:00 GMT"
REPORTED_AT: Final = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

#: When the one decision every call here carries was taken.
DECIDED_AT: Final = datetime(2026, 9, 4, 11, 30, tzinfo=UTC)

#: ADR-0231 §5's named defaults, which every subject here carries unless a case
#: names its own.
MAX_RESULTS: Final = 3
MAX_RESULT_CHARS: Final = 2048

#: A response bound generous enough that no case reaches it by accident. The bound's
#: own cases supply their own.
MAX_RESPONSE_BYTES: Final = 64 * 1024


@final
class _Omitted:
    """A field the provider did not send at all, as distinct from one it sent null.

    ADR-0231 §10's absence rule is total over four forms and each has to be
    expressible; ``None`` already means ``null``, so omission needs a value of its
    own.
    """

    __slots__ = ()


#: The one instance of it, passed to :func:`result` for a field to leave out.
OMITTED: Final = _Omitted()


def result(
    *,
    title: str | None | _Omitted | Any = "Torre dos Clérigos",
    url: str | None | _Omitted | Any = "https://example.invalid/clerigos",
    description: str | None | _Omitted | Any = "A baroque bell tower in Porto.",
) -> dict[str, Any]:
    """One result object, in the shape the documented response carries.

    Args:
        title: The title span — a string, ``None`` for ``null``, :data:`OMITTED` for a
            field the provider did not send, or any other JSON value for §10's
            ill-typed case.
        url: The address span, likewise.
        description: The snippet span, likewise.

    Returns:
        The object, ready for :func:`body`.
    """
    fields = {"title": title, "url": url, "description": description}
    return {name: value for name, value in fields.items() if not isinstance(value, _Omitted)}


def body(*results: Mapping[str, Any], group: bool = True) -> bytes:
    """The documented response's body, carrying ``results``.

    Args:
        results: The result objects, in the order the provider returned them.
        group: Whether to carry the group at all. ``False`` is the response a query
            that matched nothing gets, which ADR-0231 §10 reads as an empty result set
            rather than as a shape refusal.

    Returns:
        The body's octets.
    """
    payload = {"web": {"results": list(results)}} if group else {}
    return json.dumps(payload).encode("utf-8")


def response(
    *,
    status: str = "HTTP/1.1 200 OK",
    date: str | None = DATE_FIELD,
    headers: Sequence[str] = (),
    payload: bytes = b"",
) -> bytes:
    """One response's octets, framed by a content length.

    Args:
        status: The status line, without its terminator.
        date: The ``Date`` field's value, or ``None`` to send none — which is
            ADR-0231 §10's "a response that declares no instant".
        headers: Any further field lines, without their terminators.
        payload: The body.

    Returns:
        The octets a far end would send.
    """
    fields = [*([] if date is None else [f"Date: {date}"]), *headers]
    fields.append(f"Content-Length: {len(payload)}")
    head = "\r\n".join([status, *fields]) + "\r\n\r\n"
    # ``latin-1`` and not ``ascii``: RFC 9110 §5.5 admits ``obs-text`` in a field
    # value, and :class:`HttpsResponse` carries one opaquely — which is what lets a
    # case send a ``Date`` carrying a non-ASCII digit, the arm a parser that checked
    # ``isdigit`` without ``isascii`` would then read as a date.
    return head.encode("latin-1") + payload


def far_end(*octets: bytes) -> FakeByteChannel:
    """A secure channel with ``octets`` already sent by the far end.

    Args:
        octets: What the far end will answer, in order.

    Returns:
        The channel, ready to be served for an implicit-TLS endpoint.
    """
    return FakeByteChannel(secure=True).deliver(*octets)


def answering(*results: Mapping[str, Any], date: str | None = DATE_FIELD) -> FakeByteChannel:
    """A far end answering ``200`` with ``results``, in one call.

    Args:
        results: The result objects.
        date: The ``Date`` field's value, or ``None`` for a response declaring none.

    Returns:
        The channel.
    """
    return far_end(response(date=date, payload=body(*results)))


@final
class RefusingGate:
    """A ``SpendGate`` that refuses every admission (ADR-0194 §4).

    The canonical spend fakes admit unconditionally where no ceiling is configured,
    which is the contract; what ADR-0231 §18's arm 12a wants is the *refusal*, and a
    stub is the honest way to arrange one — a configured ceiling would be a second
    thing under test.

    Attributes:
        admissions: How many times an admission was sought, so a case can assert that
            the gate was consulted **before** the claim rather than not at all.
    """

    __slots__ = ("admissions",)

    def __init__(self) -> None:
        """Start having refused nothing."""
        self.admissions = 0

    async def admit_invocation(self, *, estimate: ToolCost) -> SpendAdmissionHandle:
        """Refuse, having recorded that this was asked.

        Args:
            estimate: The declared cost, which this stub does not read.

        Raises:
            SpendCeilingError: Always.
        """
        del estimate
        self.admissions += 1
        msg = "a configured ceiling would be crossed"
        raise SpendCeilingError(msg)

    def release_admission(self, handle: SpendAdmissionHandle) -> None:
        """Drop a reservation this stub never took.

        Args:
            handle: The handle, which is never one of this stub's.
        """
        del handle

    async def totals(self, *, at: datetime) -> tuple[SpendTotal, ...]:
        """The projection this stub does not keep.

        Args:
            at: The instant to project at.

        Returns:
            Nothing.
        """
        del at
        return ()


@final
class GatedTransport:
    """An ``OutboundTransport`` whose next open can be held at a suspension point.

    What ADR-0060's case needs from this searcher, and no more: a call cancelled
    before it suspends exercises none of the code that would convert a cancellation
    into a refusal, and the searcher's own suspension points are all inside the seam.

    Attributes:
        attempts: Every endpoint an open was sought for, in order.
    """

    __slots__ = ("_channels", "_resource", "attempts")

    def __init__(self, *channels: FakeByteChannel) -> None:
        """Serve ``channels``, in order.

        Args:
            channels: What each open hands back.
        """
        self._channels = list(channels)
        self._resource = SuspendableResource()
        self.attempts: list[TransportEndpoint] = []

    def suspend_next(self) -> LoopSuspension:
        """Arm the next open to suspend inside the modelled resource.

        Returns:
            The handle a suite waits on and releases.
        """
        return self._resource.suspend_next()

    async def open_channel(self, endpoint: TransportEndpoint) -> ByteChannel:
        """Hand out the next channel, suspending where one is armed.

        Args:
            endpoint: Where the caller asked to connect.

        Returns:
            The channel.

        Raises:
            TransportError: If the script is exhausted.
        """
        self.attempts.append(endpoint)
        async with self._resource.held():
            if not self._channels:
                msg = "this transport has no further channel to serve"
                raise TransportError(msg)
            return self._channels.pop(0)


@final
class InterruptingTransport:
    """An ``OutboundTransport`` whose open raises ``KeyboardInterrupt``.

    ADR-0231 §18's arm 14 wants "an exit for which ADR-0029 computes no outcome", and
    ADR-0029 §3 requires such an exception to propagate unchanged with no completion
    written. A ``BaseException`` that is not a cancellation is the only way to reach
    it, and it has to be raised *inside* the claim — which is where an open is.

    Attributes:
        attempts: Every endpoint an open was sought for, in order.
    """

    __slots__ = ("attempts",)

    def __init__(self) -> None:
        """Start having been asked for nothing."""
        self.attempts: list[TransportEndpoint] = []

    async def open_channel(self, endpoint: TransportEndpoint) -> ByteChannel:
        """Record the attempt and tear the process down.

        Args:
            endpoint: Where the caller asked to connect.

        Raises:
            KeyboardInterrupt: Always.
        """
        self.attempts.append(endpoint)
        raise KeyboardInterrupt


@dataclass(frozen=True, slots=True)
class Built:
    """One configured search integration and every double behind it.

    Attributes:
        integration: What the composition root's builder returned.
        transport: The outbound-transport capability, so a case can read the opens
            back — including the case whose whole assertion is that there were none.
        keyring: The recording ``Secrets`` face, likewise for credential reads.
        records: The connection store, whose answers a case scripts read by read.
        trail: The one object wired as ``AuditTrail``, ``InvocationLedger`` and, where
            the case did not supply its own, ``SpendGate``.
    """

    integration: WebSearchIntegration
    transport: FakeOutboundTransport | GatedTransport | InterruptingTransport
    keyring: Keyring
    records: Records
    trail: FakeAuditTrail

    @property
    def searcher(self) -> Any:
        """The ``WebSearcher`` under test.

        Returns:
            The searcher the builder constructed.
        """
        return self.integration.searcher

    @property
    def seam(self) -> WebSearchTransport:
        """The egress transport the searcher acts through.

        Returns:
            The transport, for a case that reads the registration off it.
        """
        return self.integration.searcher._transport


async def built(  # noqa: PLR0913 — one knob per double a case arranges, and each is set on its own
    *,
    channels: Sequence[FakeByteChannel] = (),
    transport: GatedTransport | InterruptingTransport | None = None,
    records: Records | None = None,
    holds: str | None = CREDENTIAL,
    gate: SpendGate | None = None,
    origin: str = ORIGIN,
    max_results: int = MAX_RESULTS,
    max_result_chars: int = MAX_RESULT_CHARS,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
    refusal: TransportError | None = None,
) -> Built:
    """One deployment that configured a search account, wired to scripted doubles.

    Args:
        channels: The far ends to serve, in order. Ignored where ``transport`` is
            supplied.
        transport: A transport of the case's own, for the two states the canonical
            fake has no arrangement for — a held open and an interrupted one.
        records: The connection store's scripted answers; defaults to one active
            record that never moves.
        holds: What the keyring holds under the record's slot, or ``None`` for a
            keyring with no entry — which is what an interrupted provisioning act
            leaves behind.
        gate: The ``SpendGate``; defaults to the trail, which admits unconditionally.
        origin: The origin the account names.
        max_results: ``Settings.search_max_results``.
        max_result_chars: ``Settings.search_max_result_chars``.
        max_response_bytes: ``Settings.search_max_response_bytes``.
        refusal: Arms the canonical transport to refuse every open with this, after
            recording the attempt.

    Returns:
        The integration and every double behind it.
    """
    ring = await keyring(holds=holds)
    trail = FakeAuditTrail()
    capability = transport
    if capability is None:
        served = FakeOutboundTransport().serve(*channels)
        if refusal is not None:
            served.refuse_with(refusal)
        capability = served  # type: ignore[assignment]  # the union is the arrangement's
    store = Records(entry()) if records is None else records
    integration = build_web_search_integration(
        connection=REFERENCE,
        origin=origin,
        records=store,
        secrets=ring,
        transport=capability,  # type: ignore[arg-type]  # each double satisfies the Protocol
        ledger=trail,
        gate=trail if gate is None else gate,
        max_results=max_results,
        max_result_chars=max_result_chars,
        max_response_bytes=max_response_bytes,
    )
    return Built(
        integration=integration,
        transport=capability,  # type: ignore[arg-type]  # likewise
        keyring=ring,
        records=store,
        trail=trail,
    )


class _NoDefinitions:
    """A ``RegisteredDefinitions`` face holding nothing (ADR-0231 §5).

    The state a deployment with a search account connected is actually in: the search
    declaration is registered at the egress seam and in **no** ``ToolRegistry``, so the
    seam's registry-original comparison "is not reached, exactly as ADR-0152 §1
    states". A harness that handed the seam a registry holding the declaration would
    be arranging a state the design forbids.
    """

    __slots__ = ()

    def original(self, tool_id: str, /) -> None:
        """No registry holds a definition for this id.

        Args:
            tool_id: The id being looked up.

        Returns:
            ``None``, always.
        """
        del tool_id


async def bound(
    subject: Built,
    *,
    origin: str = ORIGIN,
    query: str = QUERY,
    tool: Any = WEB_SEARCH,
) -> BoundEgressCall:
    """The binding ``EgressBinder`` derives for one search, over the real seam.

    Derived rather than hand-built, and that is what makes these cases about the
    searcher: an ``EgressBinding``'s spans have to cover every argument the call
    carries (ADR-0150 §4), so a hand-built one is a second derivation that can be
    wrong in ways no production path can be. This is the sequence ADR-0231 §6 puts in
    front of the searcher — ``orchestration`` builds the request, ``EgressBinder.bind``
    derives the binding whole — with the ruling and the trail left to the caller.

    Args:
        subject: The configured integration, whose registration the seam reads.
        origin: The origin argument.
        query: The query argument.
        tool: The declaration to bind against.

    Returns:
        The binding beside the detached arguments.

    Raises:
        AssertionError: If the seam answered "not an egress call", which would mean
            the declaration lost its destination keyword.
    """
    seam = EgressBindingSeam(
        definitions=_NoDefinitions(),
        registrations=egress_registrations(None, subject.integration),
        records=Records(entry()),
    )
    parameters: dict[str, FrozenJson] = {"origin": origin, "query": query}
    derived = await seam.bind(
        tool,
        parameters=parameters,
        provenance=CarriedProvenance(
            spans={}, planned_with_external_content=False, coverage=SpanCoverage.NOT_COVERED
        ),
    )
    assert derived is not None, "the search declaration carries a destination keyword"
    return derived


async def request(  # noqa: PLR0913 — one knob per thing a case varies about the request it is refusing
    subject: Built,
    *,
    origin: str = ORIGIN,
    query: str = QUERY,
    tool: Any = WEB_SEARCH,
    elsewhere: Mapping[str, Any] | None = None,
    unbound: bool = False,
) -> ActionRequest:
    """The request a servicer builds for one search (ADR-0231 §6).

    Args:
        subject: The configured integration.
        origin: The origin argument.
        query: The query argument.
        tool: The declaration carried by value.
        elsewhere: Fields to rewrite on the derived binding, for the cases about a
            call bound to another account or another endpoint. Applied to a binding
            the seam derived, so its spans stay the ones ADR-0150 §4 requires.
        unbound: Whether to carry no binding at all — ADR-0148 §8's third floor,
            restated at the one seam that could ignore it.

    Returns:
        The request.
    """
    derived = await bound(subject, origin=origin, query=query, tool=tool)
    carried = (
        derived.binding if elsewhere is None else derived.binding.model_copy(update=dict(elsewhere))
    )
    return ActionRequest(
        tool=tool,
        parameters=dict(derived.parameters),
        egress_binding=None if unbound else carried,
    )


def elsewhere_account(*, reference: str = REFERENCE, identity: str = IDENTITY) -> dict[str, Any]:
    """A rewrite of a derived binding's bound account.

    Args:
        reference: The connection the binding names.
        identity: The account identity it names.

    Returns:
        The update mapping, for :func:`request`'s ``elsewhere``.
    """
    return {"account": BoundAccount(identity=identity, reference=reference)}


async def authorised_search(
    trail: FakeAuditTrail,
    *,
    proposal: ActionRequest,
    decision_id: str = "d-search-1",
    outcome: PermissionOutcome = PermissionOutcome.ALLOW,
) -> ToolCall:
    """One authorised call, with its decision recorded in ``trail``.

    ADR-0192 §1 has the ledger require the decision it is passed to equal the one the
    store holds under that id, so a call whose authorisation was never recorded is
    refused before the send — correctly, and unhelpfully for a case about something
    else.

    Args:
        trail: The trail the searcher claims through.
        proposal: The request to authorise.
        decision_id: The decision's id.
        outcome: The ruling. Only an ``ALLOW`` constructs a ``ToolCall``.

    Returns:
        The call, which is unconstructable unless the decision authorises it.
    """
    decision = PermissionDecision.from_request(
        proposal,
        PermissionRuling(outcome=outcome, reason="the user granted this recipient"),
        id=decision_id,
        decided_at=DECIDED_AT,
    )
    return await authorised(trail, ToolCall(request=proposal, decision=decision))


def unknown_cost() -> ToolCost:
    """The declared cost every unpriced integration carries (ADR-0016 §4).

    Returns:
        An ``UNKNOWN`` basis.
    """
    return ToolCost(basis=CostBasis.UNKNOWN)
