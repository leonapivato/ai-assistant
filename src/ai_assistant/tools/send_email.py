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

**So what is this for?** ADR-0148 §11 deferred two `core` surfaces — the egress
binding (a) and the seam by which it reaches an ``ActionRequest`` (b) — and said
why: each "wants a producer in hand", ADR-0073 §4's standing test, because "the
shape it wants depends on what a real integration's canonicaliser and
description-builder need … and nothing at this seam transmits, so there is no
producer." This module was that producer. Both surfaces have since been decided —
ADR-0150 and ADR-0152 — and what the producer now owes is one **declaration**,
not a set of machinery:

- **one tool per connected account** — ADR-0148 §6's one-account clause. This
  declaration is therefore a *template* rather than a registration: a registered
  tool is one bound to a specific connected account, and binding it to one is
  :class:`~ai_assistant.tools.egress_binder.EgressBindingSeam`'s registration
  rather than this module's. That is the second, independent reason nothing here
  is registered.
- **declares its destination-bearing arguments** — in ADR-0152 §3's
  ``x-egress-destination``, on the schema below.
- **declares what each field establishes** — in ADR-0152 §3's ``x-egress-tier``,
  on the same subschemas.
- **canonicalises through the seam's per-protocol canonicaliser** —
  :mod:`ai_assistant.tools.destinations`, which owns SMTP's rules for every
  integration that speaks it, not for this one, and which the binding seam calls
  rather than this module.
- **resolves names as first-class gated calls** — ADR-0148 §5. Nothing here
  resolves anything: the arguments carry addresses, and an argument that is not
  an address is refused rather than looked up.

**Two keywords rather than five declared facts is ADR-0152 §3's result, not a
simplification of it.** This module used to carry a ``DestinationDeclaration``
(``protocol``, ``multiple``, ``required`` per recipient argument), a
``PayloadDeclaration`` (``establishes_tier``, ``multiple`` per transmitted one),
the value binding the two, and a description builder over them. ADR-0150 §4 has
since removed three of the five facts — the decomposition is the value's, the
coverage is total over the arguments, and requiredness is JSON Schema's own
``required`` — and ADR-0152 §3 puts the remaining two in the schema the
definition already carries. Keeping the old declarations beside the keywords
would be two statements of one fact in one module, which is the duplication
ADR-0150 is named against; so they are gone rather than deprecated, and the
description they built is now :class:`~ai_assistant.core.types.EgressBinding`'s
spans, derived at the seam and accepted from nobody (ADR-0152 §5).

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
    DestinationProtocol,
    Idempotency,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.tools.egress_declaration import DESTINATION_KEYWORD, TIER_KEYWORD

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import FrozenJson

#: The id this declaration would be registered under, once an account exists to
#: bind it to. One tool per connected account (ADR-0148 §6) means a registered id
#: names the account as well as the operation; this bare form names neither and is
#: why the constant is a template rather than a registration.
SEND_EMAIL_ID: Final = "send_email"


def _recipients() -> dict[str, FrozenJson]:
    """One recipient argument's subschema, built fresh on every call.

    An array of strings, marked destination-bearing and stating the tier its field
    establishes (ADR-0152 §3). ``to``, ``cc`` and ``bcc`` declare the same three
    facts, and ``to``'s ``minItems`` is added on top rather than repeated — which
    is why this is a function rather than a shared constant: ``core`` freezes what
    a ``ToolDefinition`` ends up holding, but the literal handed to it is an
    ordinary ``dict``, and one shared mapping would make ``to``'s bound reachable
    from ``cc``.

    The array form is ADR-0152 §4's **flat declaration**, one of exactly two shapes
    a destination-bearing argument may take. Not a style choice: it is what makes a
    supplied form impossible to extract from inside a structured value, so
    ADR-0150 §4's supplied-form invariant is total rather than checked.

    The keyword *names* are imported from the reader rather than spelled here, and
    each value is the enum member's own ``value`` as §3 requires — so the producer
    and the seam that reads it cannot drift apart by a typo.

    Returns:
        The subschema, owned by the caller.
    """
    return {
        "type": "array",
        "items": {"type": "string"},
        DESTINATION_KEYWORD: DestinationProtocol.SMTP.value,
        TIER_KEYWORD: DataTier.PERSONAL.value,
    }


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
            "to": {**_recipients(), "minItems": 1},
            "cc": _recipients(),
            "bcc": _recipients(),
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
refused at construction — which is also what keeps ADR-0152 §6's undescribed-key
refusal from being the only thing standing between an undeclared argument and the
wire.

**It also carries the whole egress declaration** (ADR-0152 §3). ``to``, ``cc`` and
``bcc`` each declare ``x-egress-destination: "smtp"`` and
``x-egress-tier: "personal"``; ``subject`` and ``body`` declare neither, and the
absence is the statement rather than an omission:

- **Destination-bearing.** All three select recipients, and nothing else does. No
  semantic recipient of this call is determined from a subject or a body, and an
  address appearing inside a body selects nobody — which is why the *declaration*
  is read rather than the values. ``bcc`` is marked like the other two on purpose:
  a blind copy is a recipient, and omitting it would be the mis-declaration
  ADR-0148 §2's third clause names, "a defect in the same class as a mis-declared
  ``discloses``".
- **Tier.** ADR-0146 §5's test applied field by field: a field establishes a tier
  "only where every value it can hold carries the same tier by what the field is
  for — a recipient address, an account identifier, a credential reference". A
  recipient list passes, so ``PERSONAL`` is stated; ``subject`` and ``body`` fail
  it, carrying "arbitrary text the user supplied … however well the implementation
  knows what that field is for", which is §5's round-4 repair over this exact pair
  of fields. Stating a tier for them would assert a fact nobody established.

Both keywords are unknown to draft 2020-12, which treats an unrecognised keyword
as an annotation — so this schema validates exactly as the same schema without
them, and ADR-0145 §5's one-dialect rule and §6's readability refusal are both
untouched.
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


__all__ = [
    "SEND_EMAIL",
    "SEND_EMAIL_ID",
    "SendEmail",
    "UndesignatedSeamError",
]
