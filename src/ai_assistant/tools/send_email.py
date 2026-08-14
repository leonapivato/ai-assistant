"""The first egress integration, declared in full and wired to nothing.

**This tool is not registered and cannot transmit.** It is deliberately absent
from :func:`~ai_assistant.tools.builtin.build_default_registry`, and its callable
raises :class:`UndesignatedSeamError` rather than sending anything. Both wait on
the same event: ADR-0017 §2 leaves the `tools/` egress boundary **approved and
undesignated**, and it becomes designated — and only then transmits — when every
one of §3's fourteen conditions holds in code *and* a later ADR names the module,
attests how, and records the transition. ADR-0148 supplies mechanisms for nine of
those conditions and designates nothing; its own header says so, and its
Consequences close on it: "Nothing here authorises a byte."

**So what is this for?** ADR-0148 §11 defers two `core` surfaces — the egress
binding (a) and the seam by which it reaches an ``ActionRequest`` (b) — and says
why: each "wants a producer in hand", ADR-0073 §4's standing test, because "the
shape it wants depends on what a real integration's canonicaliser and
description-builder need … and nothing at this seam transmits, so there is no
producer." This module is that producer, built to the cost ADR-0148's
Consequences state an integration owes:

- **one tool per connected account** — §6's one-account clause. This declaration
  is therefore a *template* rather than a registration: a registered tool is one
  bound to a specific connected account, and no connection record exists to bind
  it to (ADR-0125 §12 and ADR-0148 §13 leave the provisioning surface undecided,
  and §11's fourth clause forbids this lane naming its owner). That is the
  second, independent reason nothing here is registered.
- **declares its destination-bearing arguments** —
  :data:`SEND_EMAIL_DESTINATIONS`.
- **canonicalises through the seam's per-protocol canonicaliser** —
  :mod:`ai_assistant.tools.destinations`, which owns SMTP's rules for every
  integration that speaks it, not for this one.
- **resolves names as first-class gated calls** — §5. Nothing here resolves
  anything: the arguments carry addresses, and an argument that is not an address
  is refused rather than looked up.
- **produces a deterministic description of its own payload** —
  :func:`describe_send_email`.

**No credential, no connection, no client.** Nothing in this module reads a
secret, holds a ``Secrets`` face, names an endpoint or constructs a transport.
ADR-0148 §7 gates a credential read **by position** — inside a callable reached by
``ToolInvoker.invoke`` after ADR-0029 §2's three checks — and the callable here
refuses before it reaches any position at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import ToolError
from ai_assistant.core.types import (
    CostBasis,
    DataTier,
    Idempotency,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.tools.destination_arguments import (
    DestinationArgument,
    DestinationDeclaration,
)
from ai_assistant.tools.destinations import DestinationProtocol
from ai_assistant.tools.payload_description import (
    EgressToolDeclaration,
    PayloadArgument,
    PayloadDeclaration,
    describe_payload,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import FrozenJson
    from ai_assistant.tools.payload_description import (
        DiscloserProvenance,
        PayloadDescription,
        SpanRef,
    )

#: The id this declaration would be registered under, once an account exists to
#: bind it to. One tool per connected account (ADR-0148 §6) means a registered id
#: names the account as well as the operation; this bare form names neither and is
#: why the constant is a template rather than a registration.
SEND_EMAIL_ID: Final = "send_email"

SEND_EMAIL: Final = ToolDefinition(
    id=SEND_EMAIL_ID,
    capability="send_email",
    description="Send an email from a connected account to the named recipients.",
    risk_level=RiskLevel.HIGH,
    reversibility=Reversibility.IRREVERSIBLE,
    side_effecting=True,
    reads=(DataTier.SECRET,),
    writes=(),
    discloses=(DataTier.PERSONAL,),
    cost=ToolCost(basis=CostBasis.UNKNOWN),
    idempotency=Idempotency.NONE,
    parameters_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "to": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "cc": {"type": "array", "items": {"type": "string"}},
            "bcc": {"type": "array", "items": {"type": "string"}},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["to", "subject", "body"],
        "additionalProperties": False,
    },
)
"""The declaration ADR-0016 §1 asks for, with every safety field argued.

ADR-0016 §1: "Every field that a permission decision depends on is required … a
default is a claim", and the alternative it rejects is "deriving risk from the
integration's identity, or from whether the tool's name starts with ``send_``".
So each is stated here on its own ground rather than because sending mail feels
dangerous:

- ``risk_level=HIGH``. A send discloses to a recipient chosen per call from
  arguments a model produced, and the disclosure cannot be withdrawn. Not
  ``CRITICAL``: ADR-0016 §2's scale is about how much damage one invocation could
  do, and the ceiling is reserved for what this one is not — an action against the
  system's own integrity or a spend without bound.
- ``reversibility=IRREVERSIBLE``. ADR-0016 §2 scopes reversibility to "the effect
  on the system acted upon" and is explicit that disclosure is a *separate* axis —
  a hosted calendar event is ``REVERSIBLE`` because the tool deletes it. There is
  no such move here: SMTP has no unsend, and a provider-side "recall" is a request
  to a mailbox this system does not control.
- ``side_effecting=True``, which ``discloses`` makes structurally mandatory
  anyway (``ToolDefinition._effects_are_consistent``).
- ``reads=(SECRET,)``. Honest rather than conservative: the callable reads an
  ``INTEGRATION``-scoped credential (ADR-0125 §8), which is Tier 0, and ADR-0148
  §7 makes that read part of *this* call rather than a separate gated act — "the
  decision that authorises an egress call **is** the gate on the credential read
  that call performs". A tool that read a Tier 0 value while declaring
  ``reads=()`` would be making exactly ADR-0016 §1's false claim.
- ``writes=()``. The send changes nothing this system stores. What it changes is
  outside the system, which is what ``side_effecting`` and ``discloses`` say.
- ``discloses=(PERSONAL,)``, non-empty, which ADR-0148 §8's second clause
  **requires** of a tool registered at the seam: it makes ADR-0021 §5's floor bite
  on every egress call, so no send is auto-granted and the approver is the user.
  ``PERSONAL`` and not ``SECRET``: the tiers named here are the ceiling over spans
  whose tier is *established*, and the only such spans this tool transmits are
  recipient addresses (ADR-0146 §5). A pasted credential in the body is Tier 0 and
  stays Tier 0 (ADR-0146 §1) — but it is a **user-authored free-text** span, which
  "asserts no tier" and which no gate may treat as tier-cleared (§5), so listing
  ``SECRET`` here would not describe it; it would declare that this tool may
  *select* a Tier 0 value for a third party, which ADR-0146 §3 forbids outright.
  What carries the free-text span to the user is the payload description, and
  ADR-0146 §5 is explicit that this is "containment, not prevention".
- ``cost=UNKNOWN``. ADR-0016 §4 exists to keep "free" and "not known" apart, "the
  first a fact it can add to a running total, the second an absence of information
  it must fail closed on". Which provider a connected account sends through is
  undecided (ADR-0125 §12), and some charge per message, so ``FREE`` would be a
  claim about a provisioning surface nobody has designed.
- ``idempotency=NONE``. ADR-0016 §4's guarantee is about the *upstream*, not about
  accepting a key: SMTP deduplicates nothing, so a retry is a second message.
  ``KEYED`` would advertise a guarantee ADR-0029 §5's derived key cannot make
  true, and would additionally oblige an ``idempotency_window`` describing a
  behaviour no upstream offers.
- ``latency`` is left unset. It is advisory and not a safety field, and any figure
  here would be a measurement of a transport that does not exist.

The schema is JSON Schema draft 2020-12, declared rather than assumed (ADR-0145
§5), with ``additionalProperties: false`` so an argument nobody declared is
refused at construction — which is also what keeps the payload description's
coverage check (ADR-0148 §6) from being the only thing standing between an
undeclared argument and the wire.
"""

SEND_EMAIL_DESTINATIONS: Final = DestinationDeclaration(
    tool_id=SEND_EMAIL_ID,
    arguments=(
        DestinationArgument(
            name="to", protocol=DestinationProtocol.SMTP, multiple=True, required=True
        ),
        DestinationArgument(
            name="cc", protocol=DestinationProtocol.SMTP, multiple=True, required=False
        ),
        DestinationArgument(
            name="bcc", protocol=DestinationProtocol.SMTP, multiple=True, required=False
        ),
    ),
)
"""Which arguments select recipients: all three, and nothing else.

``subject`` and ``body`` are not destination-bearing — no semantic recipient of
this call is determined from them — and an address appearing inside a body selects
nobody, which is why the declaration is read rather than the values. ``bcc`` is
declared like the other two on purpose: a blind copy is a recipient, and a
declaration that omitted it would be the mis-declaration ADR-0148 §2's third
clause names, "a defect in the same class as a mis-declared ``discloses``".
"""

SEND_EMAIL_PAYLOAD: Final = PayloadDeclaration(
    tool_id=SEND_EMAIL_ID,
    arguments=(
        PayloadArgument(name="to", establishes_tier=DataTier.PERSONAL, multiple=True),
        PayloadArgument(name="cc", establishes_tier=DataTier.PERSONAL, multiple=True),
        PayloadArgument(name="bcc", establishes_tier=DataTier.PERSONAL, multiple=True),
        PayloadArgument(name="subject", establishes_tier=None),
        PayloadArgument(name="body", establishes_tier=None),
    ),
)
"""Every argument the send transmits, and what each field establishes.

The tier split is ADR-0146 §5's test applied field by field: "a field establishes
that tier only where every value it can hold carries the same tier by what the
field is for — a recipient address, an account identifier, a credential
reference." A recipient list passes — every value it can hold is an address, and
an address is Tier 1. ``subject`` and ``body`` fail it: they carry "arbitrary text
the user supplied … however well the implementation knows what that field is
for", which is §5's round-4 repair stated over this exact pair of fields.

All five are listed because ADR-0148 §6 requires the description to cover **every
span the call transmits**, and the schema's ``additionalProperties: false`` means
these five are all there are.
"""


SEND_EMAIL_DECLARATION: Final = EgressToolDeclaration(
    tool_id=SEND_EMAIL_ID,
    payload=SEND_EMAIL_PAYLOAD,
    recipients=SEND_EMAIL_DESTINATIONS,
)
"""The two halves bound into the one value a description is derived from.

Built at import, so the checks its construction performs — that both halves are
this tool's, and that every destination-bearing argument is covered by the
payload declaration — run when the module loads rather than when a call is
described. ADR-0016 §1's posture applied to the pair: "a tool that does not
declare its reach does not load."
"""


class UndesignatedSeamError(ToolError):
    """The call reached a callable at a seam that transmits nothing (ADR-0017 §2).

    ADR-0029's shapes want a ``(definition, callable)`` pair at registration, so a
    declaration that could not be registered without one gets this: a callable
    that refuses, names the undesignated seam, and does nothing else. It is not a
    stub for a later lane to fill in — transport lands in
    :mod:`ai_assistant.tools.egress` when a designating ADR says so, and this
    class exists so that the refusal is a typed, testable event rather than a
    ``NotImplementedError`` some caller might read as a gap.

    Raised where every ordinary invocation outcome is *returned*, deliberately.
    ADR-0029 §3's ``FAILED`` result carries a ``failure.kind.retryable`` an
    executor may act on, and a seam that has never been designated is not a tool
    failing and is not retryable — the same reasoning
    :class:`~ai_assistant.core.errors.ToolBindingError` is raised under.
    """


class SendEmail:
    """The callable half of the declaration, which refuses.

    Structurally a :class:`~ai_assistant.tools.invocation.ToolImplementation`, so
    the pair is the shape ADR-0029 §1 registers — and unregistered, so nothing can
    reach it through ``invoke``. It takes no credential, no client and no
    connection reference in its constructor, because ADR-0148 §6's binding is
    surface (a) and ADR-0125 §12 owns who could supply the rest.
    """

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],  # noqa: ARG002 — nothing is read; it refuses.
        *,
        idempotency_key: str | None,  # noqa: ARG002 — NONE, so no key is ever derived.
    ) -> FrozenJson:
        """Refuse, without reading an argument, a credential or a configuration.

        Raises:
            UndesignatedSeamError: Always. ADR-0017 §3's fourteen conditions are
                undischarged, and ADR-0148 designates nothing.
        """
        msg = (
            "send_email cannot transmit: ai_assistant.tools.egress is approved and "
            "undesignated (ADR-0017 §2), and no ADR has named it, attested §3's "
            "fourteen conditions in code, or recorded the transition"
        )
        raise UndesignatedSeamError(msg)


def describe_send_email(
    parameters: Mapping[str, FrozenJson],
    *,
    provenance: Mapping[SpanRef, DiscloserProvenance],
) -> PayloadDescription:
    """Derive this send's canonical destinations and its payload description.

    The producer's whole authorisation-time contribution in one call: the
    destinations both ways round (ADR-0148 §2) and the description that covers
    every span (§6), computed before any ``ActionRequest`` exists and with nothing
    left to fill in afterwards — which is §1's earliness, the clause "the whole of
    this ADR rests on".

    It performs no I/O, reads no clock and consults no store, so two derivations
    for one call agree (§6's determinism clause).

    Args:
        parameters: The call's arguments.
        provenance: The recorded origin of each span (ADR-0146 §2). A span absent
            from it is system-selected.

    Returns:
        The description, carrying every destination in both forms.

    Raises:
        DestinationSelectionError: If a recipient argument is absent, malformed,
            or carries a form with no canonical version.
        PayloadDescriptionError: If a span would be transmitted uncovered, or an
            argument is not text.
    """
    return describe_payload(SEND_EMAIL_DECLARATION, parameters, provenance=provenance)


__all__ = [
    "SEND_EMAIL",
    "SEND_EMAIL_DECLARATION",
    "SEND_EMAIL_DESTINATIONS",
    "SEND_EMAIL_ID",
    "SEND_EMAIL_PAYLOAD",
    "SendEmail",
    "UndesignatedSeamError",
    "describe_send_email",
]
