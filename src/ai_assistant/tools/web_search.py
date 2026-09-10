"""The search integration: its declaration, its provider adapter, and its searcher.

The counterpart of :mod:`ai_assistant.tools.send_email` for ADR-0231's kind, and it
carries the same division. This module holds the **declaration**, the request shape and
the response shape ADR-0231 §5 puts "inside ``ai_assistant.tools``", and the
:class:`~ai_assistant.core.protocols.WebSearcher` that drives the whole of ADR-0231
§6's order; :mod:`ai_assistant.tools.egress` — the module ADR-0154 §1 designates and
where §5 rules a ``WEB_SEARCH`` request leaves from — holds
:class:`~ai_assistant.tools.egress.WebSearchTransport`, which is the thing that reads
the account's credential and opens a channel to the world. **Nothing here reads a
secret, holds a ``Secrets`` face or constructs a transport**, exactly as nothing in
``send_email.py`` does; the credential is the seam's, at the position ADR-0148 §7 puts
it, and this module never holds one.

**This declaration is registered in no ``ToolRegistry``, and that is the hinge of
ADR-0231's whole design** (§5). The search integration is "registered at the egress
seam against a connected account, and in no ``ToolRegistry``" — so it is absent from
``ToolRegistry.capabilities()`` and ``all_tools()``, unreachable by any plan step, and
un-invocable through ``ToolInvoker``. The two halves of what "registered" has meant
since leg 12 come apart exactly here, and the half this kind needs is the seam's:
``EgressBindingSeam._registered`` performs the registry-original comparison only where
the registry holds a definition for the id, and then returns the *egress*
registration.

**Why that is worth the split.** If the search were in the registry, the planner would
see a capability, could name a plan step for it, and the turn would drive a tool whose
result is a JSON payload with no per-span provenance — ADR-0170 §5a's own reason for
saying a reply is not a tool, and ADR-0208 §1's for saying that a component wanting
records does not obtain them by invoking one. Not being in the registry means the
planner cannot name it, so the failure mode is not forbidden by a rule: it is
unreachable. **No lane registers this declaration in the default registry or in any
registry the turn path selects from** (§5), and
``tests/app/test_composition_web_search.py`` asserts the absence on a deployment with
an account connected, which is where it could be broken.

**A template and not a registration**, exactly as ``SEND_EMAIL`` is. ADR-0148 §6 binds
a registered tool to at most one connected account; what makes a registration is
binding this declaration to a specific one, which is
:class:`~ai_assistant.tools.egress_binder.EgressRegistration`'s job and
:func:`~ai_assistant.tools.builtin.build_web_search_integration`'s act.

**Two arguments, and the origin is one of them for a reason ADR-0231 §5 states.**
ADR-0148 §8's third floor refuses an ``ALLOW`` where a request carries no canonical
destination set, and the set is derived from spans whose argument declares a
destination (ADR-0152 §3). So the origin is an argument bearing
``x-egress-destination: "https"`` — which is what makes the call's recipient a value
the policy, the grant and the confirmation all range over — and its tier is
``operational``, because an origin is the operator's own configuration, is the same
value for every call, and is a field every value of which carries one tier by what the
field is for (ADR-0146 §5). The query declares **neither** keyword: it selects no
recipient, and it establishes no tier. A query span is arbitrary text however well the
composer knows what it is for, exactly as a message body is.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

import structlog

from ai_assistant.core.errors import (
    SpendCeilingError,
    SpendUndeterminedError,
    ToolBindingError,
    ToolError,
    TransportError,
)
from ai_assistant.core.types import (
    ActionRequest,
    Attestation,
    CostBasis,
    DataTier,
    DestinationProtocol,
    Idempotency,
    MemorySource,
    Provenance,
    Reversibility,
    RiskLevel,
    SearchOutcome,
    SearchRefusal,
    SemanticMemory,
    ToolCost,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.tools.admission import admitted_call
from ai_assistant.tools.consume import consumed_call, pending_cancellations
from ai_assistant.tools.egress import (
    BoundCallChangedError,
    HttpsRedirectRefusedError,
    HttpsResponseTooLargeError,
    MalformedHttpResponseError,
)
from ai_assistant.tools.egress_declaration import DESTINATION_KEYWORD, TIER_KEYWORD
from ai_assistant.tools.invocation import expiry_failure
from ai_assistant.tools.registry import checked_timeout, revalidated_call

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.protocols import InvocationLedger, SpendGate
    from ai_assistant.core.types import (
        EgressBinding,
        FrozenJson,
        MemoryRecord,
        SpendAdmissionHandle,
        ToolCall,
    )
    from ai_assistant.tools.egress import HttpsResponse, WebSearchTransport

_log = structlog.get_logger(__name__)

#: The id this declaration is registered under at the egress seam, once an account
#: exists to bind it to. One tool per connected account (ADR-0148 §6) means a
#: registered id names the account as well as the operation; this bare form names
#: neither, which is why the constant is a template rather than a registration.
WEB_SEARCH_ID: Final = "web_search"

#: The **source instance** every record a search mints is attested to
#: (ADR-0231 §10, ADR-0092 §3): "the owner's web search", and never a vendor, never
#: an origin, never a URL and never a credential. A constant rather than a
#: ``Settings`` field, because ADR-0231 §5 adds exactly four of those and every one
#: of them is a bound; a deployment wanting a second search source is §19's deferred
#: "second search provider", which needs the ADR that orders several outward sources.
#:
#: Non-blank and unchanged by ``Identifier``'s own validation — ``name.strip() ==
#: name`` — which ADR-0231 §17 requires of every ``WebSearcher.name`` because §10
#: requires this value and a minted record's ``reported_by`` to be **equal**.
WEB_SEARCH_SOURCE_NAME: Final = "web search"

#: ADR-0194 §1's magnitude bound on any amount that mechanism reads, restated here
#: for :func:`checked_search_cost` at the one site a searcher is built without going
#: through ``Settings`` (ADR-0236 §2). Strictly above, so ``1E15`` itself is refused.
_COST_AMOUNT_CEILING: Final = Decimal("1E15")

#: ADR-0194 §1's fractional-digit bound, likewise. Nine, which is what a declared
#: figure may carry and what the store's arithmetic is stated over.
_COST_AMOUNT_SCALE: Final = 9

#: ISO-4217's alphabetic form is three letters — ``ToolCost.currency``'s own rule
#: (ADR-0016 §4) and ``world_spend_currency``'s, and not a third one (ADR-0236 §2).
_CURRENCY_CODE_LENGTH: Final = 3

#: The argument carrying the recipient, which ADR-0152 §3's keyword makes the value a
#: ruling, a grant and a confirmation all range over.
ORIGIN_ARGUMENT: Final = "origin"

#: The argument carrying the one value that crosses into the request from outside
#: ``tools/`` (ADR-0231 §5): the authorised query string.
QUERY_ARGUMENT: Final = "query"


def _origin() -> dict[str, FrozenJson]:
    """The origin argument's subschema, built fresh on every call.

    Built rather than shared, for ``send_email``'s reason: ``core`` freezes what a
    ``ToolDefinition`` ends up holding, but the literal handed to it is an ordinary
    ``dict``, and a shared mapping would be reachable from anywhere that imported it.

    The keyword *names* are imported from the reader rather than spelled here, and
    each value is the enum member's own ``value`` as ADR-0152 §3 requires — so the
    producer and the seam that reads it cannot drift apart by a typo.

    Returns:
        The subschema, owned by the caller.
    """
    return {
        "type": "string",
        DESTINATION_KEYWORD: DestinationProtocol.HTTPS.value,
        TIER_KEYWORD: DataTier.OPERATIONAL.value,
    }


WEB_SEARCH: Final = ToolDefinition(
    id=WEB_SEARCH_ID,
    capability="web_search",
    description="Ask the connected search account one question and read back its results.",
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.REVERSIBLE,
    side_effecting=True,
    reads=(DataTier.SECRET,),
    writes=(),
    discloses=(DataTier.PERSONAL,),
    cost=ToolCost(basis=CostBasis.UNKNOWN),
    idempotency=Idempotency.NONE,
    parameters_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {ORIGIN_ARGUMENT: _origin(), QUERY_ARGUMENT: {"type": "string"}},
        "required": [ORIGIN_ARGUMENT, QUERY_ARGUMENT],
        "additionalProperties": False,
    },
)
"""The declaration ADR-0016 §1 asks for, with every safety field argued in ADR-0231 §5.

ADR-0016 §1: "Every field that a permission decision depends on is required … a
default is a claim", and the alternative it rejects is deriving risk from what the
integration is called. So each is stated on its own ground:

- ``discloses=(PERSONAL,)``. A query composed from the user's own words is Tier 1 and
  it leaves the device, which is what this field is for. Non-empty is what makes
  ADR-0021 §5's disclosure floor bite on every search, so none is auto-granted and the
  approver is the user. Naming ``SECRET`` would declare that this integration may
  select a Tier 0 value for a third party, which ADR-0146 §3 forbids outright.
- ``reads=(SECRET,)``. The callable reads an ``INTEGRATION``-scoped credential, which
  is Tier 0, and ADR-0148 §7 makes that read part of this call. ``reads=()`` would be
  the false claim ADR-0016 §1 names.
- ``writes=()``. The search changes nothing this system stores (ADR-0231 §16).
- ``side_effecting=True``, which a non-empty ``discloses`` makes structurally
  mandatory anyway.
- ``reversibility=REVERSIBLE``. ADR-0016 §2 scopes reversibility to "the effect on the
  system acted upon" and is explicit that disclosure is a separate axis. A search is a
  **read** of a remote index: nothing at the far end changes, so there is no effect to
  reverse. ``send_email`` is ``IRREVERSIBLE`` because a message arrived and SMTP has no
  unsend; nothing arrives here. The disclosure that cannot be withdrawn is real and is
  carried by ``discloses``, which is the axis ADR-0016 §2 assigns it to.
- ``risk_level=LOW``, and ADR-0231 §5 says this is the field to press hardest on.
  ADR-0016 §2's scale is how much damage **one invocation** could do, and three facts
  bound this one: the recipient is a single origin fixed by the connected account and
  reachable by no argument a model can write; the payload is one bounded string
  composed by a model call supplied only the user's own utterance (ADR-0231 §3), so
  neither a store value nor an external span can be in it; and nothing anywhere
  changes. ``send_email`` is ``HIGH`` because "a send discloses to a recipient chosen
  per call from arguments a model produced" — the clause that makes it ``HIGH`` is
  exactly the clause that is false here. **The honest accounting is that the field was
  decided on §2's scale and then checked against what it enables, and both are
  stated**: ``LOW`` is also what keeps the disclosure floor the *only* clause standing
  between the request and an ``ALLOW``. ADR-0231 §19 records a reconsideration as a
  deferral with its consequence, so a later judgement of ``MEDIUM`` moves a decision
  rather than discovering one.
- ``idempotency=NONE``. No provider guarantees deduplication of a query, so ``KEYED``
  would advertise a guarantee ADR-0029 §5's derived key cannot make true.
- ``cost``. ADR-0016 §4 keeps "free" and "not known" apart, and ``SpendGate`` can only
  count a known figure (ADR-0231 §15). This template declares ``UNKNOWN``; a
  deployment that knows its per-call figure is ADR-0231 §5's "operator's configured
  per-call figure", and ADR-0231 §9 forbids declaring ``FREE`` where the figure is not
  known in order to reach an ``ALLOW``.

**No lane weakens any of them to make a search reachable** (ADR-0231 §9). A
``discloses`` narrowed, a ``risk_level`` or ``reversibility`` restated for that
purpose, or a ``cost`` declared ``FREE`` where the figure is unknown are each the
mis-declaration ADR-0016 §1 and ADR-0148 §2 refuse.
"""


# --------------------------------------------------------------------------- #
# The provider adapter: one documented shape, chosen inside `tools/`.
# --------------------------------------------------------------------------- #
# ADR-0231 §5 leaves "which path, which parameter names, which headers and which
# body shape a provider request takes" to the integration, states that they are
# "chosen inside `ai_assistant.tools` from the connected account's configuration
# alone", and names **no vendor**; §10 assumes a response carrying ordered results
# of a title, an address and a snippet, and a declared report instant.
#
# **So the constants below are this lane's documented adapter for one provider, the
# Brave Search API**, and the origin is the only part of the request a deployment
# configures. It is not behind a `Settings` field, and that is a judgement about what
# a *vendor* is rather than an arithmetic one: ADR-0231 §5's "This decision adds
# exactly four `Settings` fields" is a statement about what that ADR adds and closes
# nothing over `Settings` (ADR-0241, Context) — a fifth field added by a later ADR
# makes no sentence of §5 false, and ADR-0241 §3 adds one. What stays true is that a
# field naming a vendor would be this module choosing an adapter through configuration
# rather than in code. §19 defers "a second search provider" to the ADR that decides
# how several outward sources are ordered; until then, replacing the adapter is
# replacing these constants and `_provider_results`, in this one module.

#: The provider's documented request path.
_PROVIDER_PATH: Final = "/res/v1/web/search"

#: The query parameter it documents.
_PROVIDER_QUERY_PARAMETER: Final = "q"

#: The parameter by which it is asked for at most ``search_max_results`` results.
#: Asking for what will be minted rather than taking a default page is what keeps the
#: response small enough that ``search_max_response_bytes`` stays a backstop rather
#: than the ordinary outcome.
_PROVIDER_COUNT_PARAMETER: Final = "count"

#: The field the account's credential rides in. Its *value* is supplied by the seam
#: and never by this module (ADR-0231 §5, ADR-0148 §7).
_PROVIDER_CREDENTIAL_FIELD: Final = "X-Subscription-Token"

#: The fields this integration wants beside the credential. Stated, so that a far end
#: content-negotiating its way to HTML is answering a request this seam did not make.
_PROVIDER_FIELDS: Final = (("Accept", "application/json"),)

#: Where the documented response carries its result list: ``{"web": {"results": […]}}``.
_PROVIDER_GROUP_KEY: Final = "web"
_PROVIDER_RESULTS_KEY: Final = "results"

#: The three spans ADR-0231 §10 transcribes, paired with the field the documented
#: response carries each in, in the fixed order §10 fixes them.
_TITLE_FIELD: Final = "title"
_ADDRESS_FIELD: Final = "url"
_SNIPPET_FIELD: Final = "description"

#: The one status a search is read out of. A ``2xx`` that is not ``200`` — a ``204``,
#: say — carries no representation, so it is a response no result can be read from
#: rather than a successful search of zero results; calling it the latter would report
#: ``NO_RESULT`` where the honest answer is that the provider answered something else.
_PROVIDER_OK: Final = 200

#: RFC 9110 §5.6.7's ``Date`` field, lowercased as :class:`HttpsResponse` lowercases a
#: field name. See :func:`_declared_instant` for why the instant is read from here.
_DATE_FIELD: Final = "date"

#: The ASCII line breaks ADR-0231 §10 drops a result for carrying at any position in
#: any of its three spans.
_LINE_BREAKS: Final = frozenset("\n\r")

#: ADR-0038 §2a's figure for an attested producer, which ADR-0231 §10 names for this
#: one.
_ATTESTED_CONFIDENCE: Final = 0.9

#: RFC 9110 §5.6.7's IMF-fixdate day names, in the order the format numbers them.
#: Spelled rather than parsed with ``%a``, which reads the process locale.
_IMF_DAYS: Final = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

#: Its month names, likewise and for the same reason.
_IMF_MONTHS: Final = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

#: How long an IMF-fixdate is: ``Sun, 06 Nov 1994 08:49:37 GMT``.
_IMF_LENGTH: Final = 29

#: How deeply a documented response may nest. Public, so the boundary case that keeps
#: this figure honest reads it rather than restating it. The provider's answer is an object
#: holding an object holding an array of objects — four levels — so a bound two orders
#: of magnitude above that refuses nothing a documented answer carries while sitting
#: far below the depth at which ``json``'s scanner exhausts the interpreter's stack.
MAX_JSON_DEPTH: Final = 100

#: The octets that open a JSON structure, and those that close one.
_JSON_OPENERS: Final = frozenset(b"[{")
_JSON_CLOSERS: Final = frozenset(b"]}")

#: The two octets that decide where a JSON string ends, and so which brackets are
#: structure and which are a third party's words (:func:`_too_deep`).
_QUOTE: Final = ord('"')
_BACKSLASH: Final = ord("\\")

#: RFC 3986 §2.3's unreserved set, the characters a request target may carry
#: unescaped. Everything else this integration writes into one is percent-encoded
#: (:func:`_percent_encoded`).
_UNRESERVED: Final = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")

#: ADR-0231 §5's ceiling on ``search_max_results``: "§10's figure is the ceiling and
#: the setting narrows it, never widens it". Stated here as well as in ``Settings``
#: because a searcher built directly by a test is one a bound could be widened at.
_MAX_SEARCH_RESULTS: Final = 3


def _percent_encoded(value: str) -> str:
    """``value`` as a percent-encoded RFC 3986 query component.

    **Written out rather than taken from ``urllib.parse.quote``**, and not by
    preference: ADR-0147 §3 confines every network-capable standard-library package
    to the designated seam, and its import-linter contract names ``urllib`` at the
    package root — "so ``urllib.request`` and ``http.client`` are both caught by the
    name below them". A pure string function inside that package is caught with them,
    which is the guard being coarse in the safe direction rather than a defect; and
    ADR-0231 §5 puts "which parameter names … a provider request takes" inside this
    package, so moving the composition into the seam to reach the helper would move
    the wrong thing.

    **Conservative on purpose**: everything outside RFC 3986 §2.3's unreserved set is
    escaped, including the sub-delims a query component may carry unescaped. A query
    is a model completion over the user's own words, so nothing is gained by leaving
    ``&`` or ``=`` unescaped and something is lost — the parameter this integration
    composed would be two. What comes back is checked again by
    :func:`~ai_assistant.tools.egress._is_origin_form` at the seam, which is the
    authority on what a request target may be and refuses rather than encodes.

    Args:
        value: The text to escape. Encoded as UTF-8 first, so a non-ASCII character
            becomes the percent escapes of its own octets and never of a code point.

    Returns:
        The escaped text, in uppercase hexadecimal as RFC 3986 §2.1 prefers.
    """
    return "".join(
        chr(octet) if chr(octet) in _UNRESERVED else f"%{octet:02X}"
        for octet in value.encode("utf-8")
    )


def _refused(refusal: SearchRefusal) -> SearchOutcome:
    """One refusal, carrying a class and nothing else (ADR-0231 §10).

    Args:
        refusal: The class.

    Returns:
        The outcome.
    """
    return SearchOutcome(refusal=refusal)


def _declared_instant(headers: Sequence[tuple[str, str]]) -> datetime | None:
    """The instant the provider's own response declares, or ``None`` (ADR-0231 §10).

    **Where it is read from, and what makes it the provider's own statement.**
    ADR-0231 §10 obliges the implementing lane to say both, "for the provider the
    owner chose". It is RFC 9110 §5.6.7's ``Date`` field, which §6.6.1 defines as "the
    date and time at which the message was originated" — a value the origin server
    writes from its own clock, about its own act of answering, before the response
    leaves it. That is the reading §10's own prose contemplates: "An HTTPS response
    from an origin server that has a clock carries the instant it was generated." It
    is **not** the instant this system sent the request, not the instant it received
    the response, and not a value derived from either; nothing on this path reads a
    clock at all.

    **Strict IMF-fixdate, and the obsolete formats are not read.** RFC 9110 §5.6.7
    requires a sender to generate that one format and forbids it generating another,
    and ADR-0231 §10 rules that "a value carried in that position which cannot be read
    as an instant is not a declared one". So an RFC 850 or ``asctime`` spelling lands
    with a malformed one — the fail-closed direction, which mints nothing rather than
    attesting to a value read under a rule the sender was told not to use. The parse
    is written out rather than taken from ``strptime``, whose ``%a`` and ``%b`` read
    the process locale: a hub started under a non-English locale would otherwise
    refuse every well-formed date on that machine and nowhere else.

    Args:
        headers: The response's fields, names already lowercased.

    Returns:
        The instant, or ``None`` where the field is absent, appears more than once, or
        carries a value this format does not admit.
    """
    values = [value for field, value in headers if field == _DATE_FIELD]
    if len(values) != 1:
        # Two `Date` fields declare two instants, so the response declares none this
        # integration will pick between — ADR-0231 §10's "no substitute" read at the
        # one place a client could invent one by taking the first.
        return None
    value = values[0]
    if len(value) != _IMF_LENGTH:
        return None
    day, comma, rest = value[:3], value[3:5], value[5:]
    if day not in _IMF_DAYS or comma != ", ":
        return None
    stamp, space, zone = rest[:20], rest[20:21], rest[21:]
    if space != " " or zone != "GMT":
        return None
    return _imf_stamp(stamp)


def _imf_stamp(stamp: str) -> datetime | None:
    """The ``dd Mmm yyyy hh:mm:ss`` half of an IMF-fixdate, as a UTC instant.

    Args:
        stamp: Exactly twenty characters, already split out by
            :func:`_declared_instant`.

    Returns:
        The instant, or ``None`` where any field is not the fixed-width decimal the
        format states — a two-digit day, a named month, a four-digit year and three
        two-digit time fields, separated exactly as the format separates them.
    """
    separators = ((2, " "), (6, " "), (11, " "), (14, ":"), (17, ":"))
    if any(stamp[position] != character for position, character in separators):
        return None
    month = stamp[3:6]
    if month not in _IMF_MONTHS:
        return None
    fields = (stamp[0:2], stamp[7:11], stamp[12:14], stamp[15:17], stamp[18:20])
    if not all(field.isdigit() and field.isascii() for field in fields):
        return None
    day, year, hour, minute, second = (int(field) for field in fields)
    try:
        return datetime(year, _IMF_MONTHS.index(month) + 1, day, hour, minute, second, tzinfo=UTC)
    except ValueError:
        # A day the month does not have, or a time field out of range. `isdigit`
        # admits the digits; only the calendar can refuse the value, and a date that
        # names no determinate instant is one ADR-0231 §10 treats exactly as it
        # treats a malformed string.
        return None


def _decoded_object(body: bytes) -> dict[str, FrozenJson] | None:
    """The response body as a UTF-8 JSON object, or ``None`` where it is not one.

    Args:
        body: The response's octets, as the exchange read them under its bound.

    **A response the decoder cannot descend is one of the shapes, and it is refused
    here rather than left to leave.** ``json``'s scanner descends one level per open
    bracket, so a *well-formed* body nested deeply enough exhausts the interpreter's
    stack instead of failing to parse — which is reachable well inside
    ``search_max_response_bytes``' default megabyte, and is therefore a response a
    provider can actually send. ADR-0231 §17 says this member raises for no source
    reason, and a body a provider sent is exactly a source reason.

    **The guard is a bound on the nesting rather than a caught ``RecursionError``**,
    and that is the difference between refusing and hoping: a stack that has already
    overflowed is not one an ``except`` clause can be relied on to unwind, which is
    what the first attempt at this discovered. So the depth is counted off the octets
    **before** the decoder is entered, and a body past the bound is refused without
    being parsed at all — the same posture ADR-0231 §5 takes for the response bound
    one seam over, where "nothing is parsed" is what makes an over-large response
    yield no value.

    Returns:
        The object, or ``None`` where the octets are not UTF-8, are not JSON, are
        nested past :data:`MAX_JSON_DEPTH`, or are JSON that is not an object. All
        four are one operator fact — the provider answered something this integration
        does not read — so they are one answer rather than four.
    """
    if _too_deep(body):
        return None
    try:
        decoded = json.loads(body.decode("utf-8"))
    except ValueError:
        # `ValueError` and not the two concrete classes: `UnicodeDecodeError` and
        # `json.JSONDecodeError` are both subclasses of it, and naming the base keeps
        # a third `ValueError` from this one call from leaving a member that returns
        # refusals.
        return None
    return decoded if isinstance(decoded, dict) else None


def _too_deep(body: bytes) -> bool:
    r"""Whether ``body`` nests structures past what this integration will decode.

    Counted over the octets rather than over a parse, because the point is to decide it
    **before** the decoder is entered: see :func:`_decoded_object`.

    **String-aware, and that is the whole of the correctness here.** A bracket inside a
    JSON string is a character in a third party's words and not a structure — ADR-0231
    §10 transcribes such a span **verbatim** — so a counter that read one would refuse
    a result whose title happens to carry brackets, which is a drop §10 does not admit.
    And it fails in the other direction too: a ``]`` inside an earlier string would
    *decrement* the running depth, so a crafted response could carry a real nesting
    this bound was meant to catch and pass under it. Both lenses of round 3 found the
    pair, and both are the same defect.

    Only two escapes matter for finding where a string ends: ``\\`` and ``\"``, and
    treating any ``\`` as consuming the next octet handles both. **UTF-8 makes the
    scan safe over octets**: no byte of a multi-byte sequence is below ``0x80``, so
    neither ``"`` nor ``\`` nor a bracket can appear inside one.

    Args:
        body: The response's octets.

    Returns:
        Whether the running structural depth ever passes :data:`MAX_JSON_DEPTH`.
    """
    depth = 0
    in_string = False
    escaped = False
    for octet in body:
        if in_string:
            if escaped:
                escaped = False
            elif octet == _BACKSLASH:
                escaped = True
            elif octet == _QUOTE:
                in_string = False
        elif octet == _QUOTE:
            in_string = True
        elif octet in _JSON_OPENERS:
            depth += 1
            if depth > MAX_JSON_DEPTH:
                return True
        elif octet in _JSON_CLOSERS:
            depth -= 1
    return False


def _provider_results(body: bytes) -> tuple[Mapping[str, FrozenJson], ...] | None:
    """The documented response's result list, or ``None`` where it is another shape.

    ADR-0231 §10: "A response whose top-level shape is not the one the provider
    documents is refused ``PROVIDER_REFUSED`` before this clause is reached." What
    that admits, exactly: a UTF-8 JSON object, whose ``web`` member — where it has one
    — is an object, whose ``results`` member — where *it* has one — is an array of
    objects.

    **An absent group or an absent list is an empty result set and not a refusal.**
    The documented response omits the group where the query matched nothing, so
    reading that as a malformed shape would report a provider that answered perfectly
    well as one that answered something else — and the two are different operator
    facts (ADR-0231 §13). What is refused is a group or a list of the wrong *type*,
    which no documented response carries.

    Args:
        body: The response's octets.

    Returns:
        The results, in the order the provider returned them — possibly empty — or
        ``None`` where the response is not the documented shape.
    """
    decoded = _decoded_object(body)
    if decoded is None:
        return None
    group = decoded.get(_PROVIDER_GROUP_KEY)
    if group is None:
        return ()
    if not isinstance(group, dict):
        return None
    results = group.get(_PROVIDER_RESULTS_KEY)
    if results is None:
        return ()
    if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
        return None
    return tuple(results)


@final
class _IllTyped:
    """The fourth outcome of :func:`_span`, distinct from a present empty string.

    A sentinel class rather than a string or ``None``, because both of those are
    already answers that classification gives and either would collapse two of
    ADR-0231 §10's four outcomes into one.
    """

    __slots__ = ()


#: The one instance of it.
_ILL_TYPED: Final = _IllTyped()


def _span(result: Mapping[str, FrozenJson], field: str) -> str | None | _IllTyped:
    """One of ADR-0231 §10's three spans, classified into its outcomes.

    §10's rule is **total over every value a well-formed response can carry in one of
    these three positions**: omitted, ``null``, a string, or something else, and each
    of the four has exactly one outcome.

    Args:
        result: One result object.
        field: The provider's field name for the span.

    Returns:
        The string where the span is **present** — transcribed byte for byte, leading
        and trailing whitespace included; ``None`` where it is **absent** — omitted,
        ``null``, empty, or every character of it Unicode whitespace; or
        :data:`_ILL_TYPED` where the provider supplied a value that is neither a
        string nor ``null``, which drops the result whole. A non-string is dropped
        rather than called absent, because the provider did supply a value and calling
        it absent would discard a field it filled; and rather than called present,
        because there is no string to transcribe and rendering ``42`` as ``"42"``
        would be this system adding a word of its own.
    """
    if field not in result:
        return None
    value = result[field]
    if value is None:
        return None
    if not isinstance(value, str):
        return _ILL_TYPED
    return value if value.strip() else None


def _transcription(result: Mapping[str, FrozenJson], *, max_chars: int) -> str | None:
    r"""The content one result transcribes to, or ``None`` where §10 drops it.

    ADR-0231 §10's transcription in one place, in the order its clauses decide:

    1. Each of the three spans is classified (:func:`_span`). **A span the provider
       supplied as a non-string drops the result whole.**
    2. **A result whose address is absent is dropped**, since a result *is* a title, an
       address and a snippet, and transcribing two of the source's three spans would
       be this system deciding which of them mattered. An address that is present is
       transcribed rather than validated: this decision parses no result address, and
       §19 is where a fetched one is deferred.
    3. **A result any of whose present spans carries ``
    `` or ``
    `` is dropped
       whole.** Absence is decided first and this is asked only of what is present, on
       the clause's own reason: the line structure is the only thing keeping the three
       spans apart, and a span that is *absent* contributes no line for a break to
       disturb. A break inside a present span would have to be altered — which would
       stop it being verbatim — or would produce a record whose lines no reader can
       assign to a span, and dropping is the one answer that keeps both properties.
    4. The present spans are joined with a single ``
    ``, in the fixed order title,
       address, snippet, **with no other byte added**. Where the title or the snippet
       is absent its line is omitted and the remaining lines keep their order.
    5. **A content over ``search_max_result_chars`` is dropped rather than
       truncated**, measured as ADR-0230 §6 measures a fetched document — on the
       ``json.dumps`` rendering at its default ``ensure_ascii=True``, its two
       delimiters included, which is the rendering the prompt will carry. A ceiling on
       source characters would admit a result six or twelve times this long while
       claiming to admit this much (ADR-0222 §4).

    Args:
        result: One result object from the documented response.
        max_chars: ``Settings.search_max_result_chars``.

    Returns:
        The content, or ``None`` where any of the five clauses drops the result.
    """
    spans = tuple(_span(result, field) for field in (_TITLE_FIELD, _ADDRESS_FIELD, _SNIPPET_FIELD))
    if any(isinstance(span, _IllTyped) for span in spans):
        return None
    present = [span for span in spans if isinstance(span, str)]
    if not isinstance(spans[1], str):
        return None
    if any(character in _LINE_BREAKS for span in present for character in span):
        return None
    content = "\n".join(present)
    if len(json.dumps(content)) > max_chars:
        return None
    return content


def _result_of(
    outcome: SearchOutcome, definition: ToolDefinition, timeout: timedelta
) -> ToolResult:
    """The invocation result ADR-0192's completion is written from.

    **A refusal is not always a failed invocation**, and the split is what makes the
    ledger's row true. ``NO_RESULT`` and ``UNATTESTED`` are answers a provider gave:
    the call was made, it completed, and what came back is not something this system
    will carry — so the invocation ``SUCCEEDED``. ``TRANSPORT_FAILED``,
    ``PROVIDER_REFUSED`` and ``RESPONSE_TOO_LARGE`` are calls that did not complete as
    calls, so they are ``FAILED``. ``SPEND_REFUSED`` reaches no claim at all and so
    reaches this function never.

    **``DEADLINE_EXPIRED`` is neither, and that is the defect ADR-0241 §5 corrects.**
    ADR-0029 §4's rule attaches to a deadline expiry and a cancellation and to nothing
    else: the answer is the declaration's own ``interrupted_outcome``, which for
    ``WEB_SEARCH`` — ``side_effecting`` with ``idempotency`` ``NONE`` — is
    ``INDETERMINATE``. Recording ``FAILED`` would say *the call did not act* about a
    search whose query may have left the machine and may have been served and billed,
    which is the one direction ADR-0014 §4 refuses to guess in. It is read from **this
    searcher's own registered declaration** and never from ``call.request.tool``
    (ADR-0029 §4, ADR-0241 §5), and the classification is
    :func:`~ai_assistant.tools.invocation.expiry_failure` — the invocation seam's own,
    so the corpus has one statement of ADR-0029 §4's expiry shape and not two. Its
    ``incurred_cost`` is left unset, which ``consumed_call`` maps to
    :func:`~ai_assistant.tools.consume.unknown_cost`: ADR-0194 §2's estimate/reported
    boundary binds, so no lane substitutes ``web_search_cost_per_call`` for it and none
    treats an expiry as costing nothing (ADR-0241 §5).

    **The message is the seam's own and carries no content the seam did not author**
    (``ToolFailure``): a class name and a rule, never a provider's body, a status line,
    an origin or a query.

    Args:
        outcome: What the search produced.
        definition: This searcher's declaration, whose ``id`` names the integration
            and whose ``interrupted_outcome`` classifies an expiry.
        timeout: The bound the **caller** stated, which an expiry's message names
            rather than whatever remained of it (ADR-0029 §4).

    Returns:
        The result, whose ``outcome`` and ``failure`` the completion transcribes.
    """
    refusal = outcome.refusal
    if refusal is None or refusal in _COMPLETED_REFUSALS:
        return ToolResult(outcome=ToolOutcome.SUCCEEDED)
    if refusal is SearchRefusal.DEADLINE_EXPIRED:
        return expiry_failure(definition, timeout)
    return ToolResult(
        outcome=ToolOutcome.FAILED,
        failure=ToolFailure(
            kind=_FAILURE_KINDS[refusal],
            message=f"{definition.id}: the search was refused, class {refusal.value}",
        ),
    )


#: The refusals a **completed** call produced: the provider answered, and what it
#: answered is not something this system will carry.
_COMPLETED_REFUSALS: Final = frozenset({SearchRefusal.NO_RESULT, SearchRefusal.UNATTESTED})

#: How a refusal that failed the invocation is classified for ADR-0029 §3's row. A
#: response this system declined to buy is the seam's own refusal; a provider that
#: answered something else is one too, since nothing about the request was invalid;
#: and a channel that could not be opened, verified or continued is unavailability.
_FAILURE_KINDS: Final[Mapping[SearchRefusal, ToolFailureKind]] = {
    SearchRefusal.TRANSPORT_FAILED: ToolFailureKind.UNAVAILABLE,
    SearchRefusal.PROVIDER_REFUSED: ToolFailureKind.REFUSED,
    SearchRefusal.RESPONSE_TOO_LARGE: ToolFailureKind.REFUSED,
}


def _checked_bound(label: str, value: int, *, ceiling: int | None) -> None:
    """Refuse a bound outside ADR-0231 §5's stated domain for it.

    Args:
        label: The field's name, for the message.
        value: What was passed.
        ceiling: The domain's upper end, or ``None`` where it has none.

    Raises:
        ValueError: If ``value`` is not an exact ``int``, is below 1, or is above
            ``ceiling``. An **exact** ``int`` and not an ``isinstance`` match, for
            ``HttpsExchange``'s reason: ``True`` is an ``int`` by ``isinstance`` and
            would otherwise configure a bound of one while satisfying the range.
    """
    if type(value) is not int:
        msg = f"{label} is an exact int; got {value!r}"
        raise ValueError(msg)
    if value < 1:
        msg = f"{label} is an integer of at least 1; got {value}"
        raise ValueError(msg)
    if ceiling is not None and value > ceiling:
        msg = f"{label} is an integer of at most {ceiling} (ADR-0231 §5); got {value}"
        raise ValueError(msg)


def _is_countable(amount: Decimal) -> bool:
    """Report whether ``amount`` is countable under ADR-0194 §1.

    Finite; absolute value **strictly** below :data:`_COST_AMOUNT_CEILING`; and
    expressible to at most :data:`_COST_AMOUNT_SCALE` fractional digits.
    ``Decimal("1.0000000000")`` is countable, because §1's predicate is a test on
    the *value* and not on the representation.

    **A further implementation of §1's predicate, deliberately, and not a further
    source for it.** ``core.config`` carries one for the ``Settings`` field it
    validates and ``permissions.spend`` carries one for the store that runs the
    arithmetic, each stating the ADR's clause rather than each other, because
    ``core`` may import no subsystem and no subsystem may import another (golden
    rules 1 and 2). ADR-0236 §2 puts a statement here for the same structural
    reason and says so in terms — *"The domain is therefore enforced twice,
    deliberately, and the two statements are of one rule."*

    **Context-independent by construction.** Everything it reads comes from the
    amount's own ``as_tuple()``, and ``copy_abs`` rather than ``abs`` because the
    latter rounds to the ambient precision and traps under a hostile context on
    exactly the values this predicate exists to classify.

    Args:
        amount: The amount to classify.

    Returns:
        Whether ADR-0194's mechanism may read it.
    """
    if not amount.is_finite():
        return False
    _, digits, exponent = amount.as_tuple()
    if not isinstance(exponent, int):  # pragma: no cover — a finite Decimal has an int exponent
        return False
    significant = len(digits)
    while significant and digits[significant - 1] == 0:
        significant -= 1
    scale = 0 if significant == 0 else exponent + (len(digits) - significant)
    if scale < -_COST_AMOUNT_SCALE:
        return False
    return amount.copy_abs() < _COST_AMOUNT_CEILING


def checked_search_cost(amount: Decimal | None, currency: str | None) -> ToolCost | None:
    """The declared cost a configured per-call figure builds, or ``None`` for absence.

    ADR-0236 §1's rule, *"stated over building a ``ToolCost``, not over reading a
    setting"*, at the one place in production either value becomes one. ``None``
    means the pair is unset, and the caller keeps :data:`WEB_SEARCH`'s own
    ``UNKNOWN`` declaration rather than building an equal copy of it (§4).

    **`FREE` is unreachable through this function and there is no argument that
    could ask for one** (§3): the two states it returns are the whole of what a
    deployment can put the declaration's ``cost`` field in. An operator asserting
    that a search costs them nothing passes ``Decimal("0")`` with the currency
    their account is denominated in, which satisfies the ``UNKNOWN``-cost floor
    exactly as any other ``PER_CALL`` figure does.

    **This restates ADR-0236 §2's domain at the one place a searcher can be built
    without going through ``Settings``**, which is that section's marked clause:
    the domain is enforced twice, and the two statements are of one rule.

    Args:
        amount: ``Settings.web_search_cost_per_call``, or ``None``.
        currency: ``Settings.web_search_cost_currency``, or ``None``.

    Returns:
        The ``PER_CALL`` cost where both are supplied, and ``None`` where neither
        is.

    Raises:
        TypeError: If ``currency`` is supplied and is not a ``str``. The type is part
            of the domain, so a caller that ignored the annotation is refused by name
            rather than by ``len()`` raising one field along, and the canonical fake
            states the same rule (ADR-0236 §7).
        ValueError: If exactly one of the two is supplied; if ``amount`` is not an
            exact ``Decimal``, is non-finite, is negative, or is not countable
            under ADR-0194 §1; or if ``currency`` is not exactly three uppercase
            ASCII letters (ADR-0016 §4's shape, and ``world_spend_currency``'s).
    """
    if (amount is None) != (currency is None):
        supplied = "cost_per_call" if currency is None else "cost_currency"
        missing = "cost_currency" if currency is None else "cost_per_call"
        msg = (
            f"{supplied} is supplied and {missing} is not; a declared per-call cost needs "
            f"both the figure and the ISO-4217 code it is denominated in (ADR-0236 §1)"
        )
        raise ValueError(msg)
    if amount is None or currency is None:
        return None
    if type(amount) is not Decimal:
        # An exact ``Decimal`` and not an ``isinstance`` match, for ``_checked_bound``'s
        # reason: a subclass overriding comparison would satisfy the range below while
        # declaring something else entirely.
        msg = f"cost_per_call is an exact Decimal; got {amount!r}"
        raise ValueError(msg)
    if not amount.is_finite():
        msg = f"cost_per_call must be finite (ADR-0236 §2); got {amount!r}"
        raise ValueError(msg)
    if amount < 0:
        msg = f"cost_per_call must not be negative (ADR-0236 §2); got {amount!r}"
        raise ValueError(msg)
    if not _is_countable(amount):
        msg = (
            f"cost_per_call must be countable — below {_COST_AMOUNT_CEILING} and to at "
            f"most {_COST_AMOUNT_SCALE} fractional digits (ADR-0194 §1); got {amount!r}"
        )
        raise ValueError(msg)
    if type(currency) is not str:
        # Refused by name, and before the shape check below reaches ``len()``. An
        # exact ``str`` and not an ``isinstance`` match, for the amount's reason one
        # field up: a subclass overriding ``__len__`` or ``isupper`` would satisfy the
        # shape check while declaring something else. ``TypeError`` and not the
        # ``ValueError`` a malformed *code* earns, because the class states which
        # mistake was made.
        msg = f"cost_currency is a str; got {type(currency).__name__}"
        raise TypeError(msg)
    if len(currency) != _CURRENCY_CODE_LENGTH or not (
        currency.isascii() and currency.isupper() and currency.isalpha()
    ):
        msg = (
            "cost_currency must be three uppercase ASCII letters (ISO-4217, ADR-0016 §4); "
            f"got {currency!r}"
        )
        raise ValueError(msg)
    return ToolCost(basis=CostBasis.PER_CALL, amount=amount, currency=currency)


# --------------------------------------------------------------------------- #
# The searcher: ADR-0231 §6's order, in the one component that has the call.
# --------------------------------------------------------------------------- #


@final
class _UpstreamWatchingGate:
    """The injected ``SpendGate``, watched for a ``TimeoutError`` of its **own**.

    ADR-0241 §7 forbids reporting as this seam's expiry a ``TimeoutError`` an upstream
    party raised for its own reasons — and at the admission that question is not
    answerable from where the answer is needed.
    :func:`~ai_assistant.tools.admission.admitted_call` answers ADR-0029 §4's
    classification for **every** ``TimeoutError`` out of ``admit_invocation``, which is
    right at that frame: there, the deadline is the only thing that could raise one.
    But the gate is a collaborator, and one that raises Python's own ``TimeoutError``
    reaches the same branch under a bound nothing has come near.

    **So the provenance is captured where it is unambiguous, at the call itself**,
    rather than reconstructed afterwards from a clock. An earlier revision compared
    ``loop.time()`` against the window's end, and that is a heuristic with a real gap:
    a gate raising just short of the bound, plus the microseconds an unwinding costs,
    reads as an expiry the timer never delivered.

    **The discriminator is ADR-0031 §2's count and not the exception's class**, which
    is the same instrument the rest of this seam uses. When the deadline fires it
    *cancels this task*, so a gate that absorbs that cancellation and raises a
    ``TimeoutError`` of its own arrives with the count moved — the deadline really did
    fire, and the expiry is this seam's. A gate that raises with the count unmoved
    raised for its own reasons, and its refusal keeps the class the tree already gives
    it (§4).

    **It also carries the fact the caller cannot recover afterwards.**
    ``asyncio.Timeout.__aexit__`` calls ``uncancel`` on its way out **whatever** the
    exception was, so a gate that catches the deadline's cancellation and raises an
    ordinary fault instead leaves the caller with a fault and a count that never
    moved — and the expiry would be reported as ADR-0241 §8's ``SEARCH_FAILED``
    rather than as §4's own member. This object sits inside that context manager, so
    it observes the cancellation while it is still on the task.

    Attributes:
        upstream: The gate's own ``TimeoutError``, where one was raised with nothing
            cancelled. ``None`` otherwise, which is every ordinary call.
        interrupted: Whether a cancellation reached this task while the gate was
            running — this deadline's or the caller's, which
            :meth:`WebSearchEgress._deliver_absorbed` then tells apart against the
            baseline taken before the admission.
    """

    __slots__ = ("_inner", "interrupted", "upstream")

    def __init__(self, inner: SpendGate) -> None:
        """Watch ``inner`` without deciding anything for it.

        Args:
            inner: The gate this searcher was wired with. Every member delegates, and
                a refusal leaves as the gate raised it — ADR-0194 §4 makes both spend
                classes payload-free where they are raised, and nothing here catches,
                wraps or annotates one.
        """
        self._inner = inner
        self.upstream: BaseException | None = None
        self.interrupted = False

    async def admit_invocation(self, *, estimate: ToolCost) -> SpendAdmissionHandle:
        """Admit through the inner gate, noting a ``TimeoutError`` it raised itself.

        Args:
            estimate: The pinned declaration's cost, passed through unread.

        Returns:
            The inner gate's handle.

        Raises:
            BaseException: Whatever the inner gate raised, unchanged.
        """
        entered_with = pending_cancellations()
        try:
            return await self._inner.admit_invocation(estimate=estimate)
        except BaseException as raised:
            # **Read here, and that is the whole of why this wrapper exists.** This
            # frame is *inside* `admitted_call`'s `asyncio.timeout_at`, and
            # `asyncio.Timeout.__aexit__` calls `uncancel` on its way out whatever the
            # exception was — so by the time the caller sees anything, a cancellation
            # the deadline delivered has left no trace in the count at all. Observed
            # from in here it is still there.
            self.interrupted = pending_cancellations() > entered_with
            if isinstance(raised, TimeoutError) and not self.interrupted:
                # Nothing cancelled this task, so no deadline delivered anything here:
                # ADR-0031 §2's case, and ADR-0241 §7's "not this seam's expiry".
                self.upstream = raised
            raise

    def release_admission(self, handle: SpendAdmissionHandle) -> None:
        """Release through the inner gate.

        Args:
            handle: The reservation to drop. Synchronous and non-raising, which is the
                contract this delegates rather than reimplements (ADR-0194 §5).
        """
        self._inner.release_admission(handle)

    # `SpendGate` declares exactly these two members (ADR-0194 §3, §5) — an invoker
    # able to read a totals projection has acquired a permissions-owned history it
    # has no use for — so this wrapper has exactly two to delegate.


@final
class WebSearchEgress:
    """Ask one connected search account a question, and mint what it answers.

    ADR-0231's ``WebSearcher``. **Constructed in exactly one place, and only where a
    deployment configured an account**:
    :func:`~ai_assistant.tools.builtin.build_web_search_integration`, the only site
    under ``src/ai_assistant``. A deployment that named no connection and no origin
    builds none and opens nothing.

    **It is registered at the egress seam and in no ``ToolRegistry``** (§5), so its
    declaration is absent from ``capabilities()`` and ``all_tools()``, no plan step
    can name it, and ``ToolInvoker`` cannot reach it. That is why the machinery
    ``ToolInvoker.invoke`` would have supplied is here instead, and why it is here in
    a stated order rather than in a convenient one.

    **The order in :meth:`search` is the decision, not an implementation detail**, and
    every step of it is one of ADR-0231 §6's or §15's marked clauses:

    1. ADR-0029 §2's three, in its order. The call is **revalidated and detached**, so
       a mutation landed after construction cannot survive into execution. The
       definition on that detached copy is compared for equality against **this
       searcher's own registered declaration** — the authoritative original here,
       standing where ADR-0029 §2 puts the registry's, because §5 gives this
       integration an egress registration and no registry entry. And
       ``PermissionDecision.authorises`` is **re-evaluated** against that same copy
       rather than trusted from construction, because ``ToolCall``'s own validator
       runs at construction and ``object.__setattr__`` defeats ``frozen=True``. Every
       subsequent step reads the revalidated copy and never the argument.
    2. ADR-0194 §3's spend admission, over the ``ToolCost`` on that revalidated copy
       and never on the argument, **after** the three checks and **before** the ledger
       claim. A refused admission reaches no credential, no channel, no claim and no
       completion.
    3. ADR-0192's claim, the send, and a completion on **every exit this frame
       observes** — the invoker's own consume, reached through the same
       :func:`~ai_assistant.tools.consume.consumed_call` the registry uses, so there
       is one implementation of it and not two.
    4. Inside the claim, and inside the deadline the **caller** stated as
       :meth:`search`'s ``timeout`` (ADR-0241 §1): the pin, ADR-0148 §6's
       one-step credential read and its post-read discard, and the exchange — all of
       them :class:`~ai_assistant.tools.egress.WebSearchTransport`'s, at the seam
       ADR-0154 §1 designates. Then §10's transcription and minting, here.

    **A claim left open states, as its own state, that the search may have reached the
    provider, and nothing reconciles it** (§6). ``orchestration``'s recovery scan finds
    a durable ``RUNNING`` *step* and completes the open claims under its approval; a
    search decision has no step, so that scan never reaches this claim and this class
    does not teach it to. What that costs is nothing: the reconciliation exists to stop
    **two** records disagreeing, and a search produces one.

    **Every source reason is returned and none is raised** (§17). What *does* leave
    :meth:`search` is a fault that no :class:`SearchRefusal` member names: a call that
    does not survive revalidation, one carrying a definition this searcher did not
    register, one its decision does not authorise, one bound to another account or
    another origin, a ledger or trail fault, and a ``CancelledError`` the callable
    invented with nothing cancelled (ADR-0241 §7). Each is
    :class:`~ai_assistant.core.errors.ToolBindingError`,
    :class:`~ai_assistant.core.errors.ToolError`,
    :class:`~ai_assistant.tools.egress.TransportPinError` or one of ADR-0192's — the
    classes ``ToolInvoker.invoke`` raises for the same facts — and a servicer degrades
    the turn on them exactly as ADR-0226 §5 requires it to degrade on anything else,
    recording ADR-0241 §8's ``SEARCH_FAILED``.

    **The deadline is the caller's and this class holds none** (ADR-0241 §1, §3).
    :meth:`search` takes it as a required keyword with no default, so there is no
    spelling here for an unbounded call and no configured figure a searcher could
    disagree with its caller about. It covers the stages above and **not** the two
    ledger appends, which ADR-0192 §3 pins unbounded by this seam: what the bound
    buys is that the seam stops waiting on the work it owns, not a wall-clock total
    for a :meth:`search` frame.
    """

    __slots__ = (
        "_declaration",
        "_gate",
        "_ledger",
        "_max_result_chars",
        "_max_results",
        "_name",
        "_transport",
    )

    def __init__(  # noqa: PLR0913 — one parameter per collaborator ADR-0231 §6 and §15 name, plus the declaration §6's second check compares against, the identity §10 attests to and the two bounds §5 adds; each is one thing this searcher is handed rather than reaches for
        self,
        *,
        transport: WebSearchTransport,
        ledger: InvocationLedger,
        gate: SpendGate,
        max_results: int,
        max_result_chars: int,
        declaration: ToolDefinition = WEB_SEARCH,
        name: str = WEB_SEARCH_SOURCE_NAME,
    ) -> None:
        """Bind a searcher to the seams it acts through.

        Args:
            transport: The egress seam this integration's requests leave through
                (ADR-0231 §5). It holds the registration, reads the credential and
                opens the channel; this object holds none of the three.
            ledger: The ``InvocationLedger`` this searcher claims and completes
                through (ADR-0192 §1, §3). Never an ``AuditTrail``: the decision was
                recorded before this object was reached, and a searcher that could
                record one would be deciding as well as acting.
            gate: The ``SpendGate`` every call is admitted by, before the claim
                (ADR-0194 §3). Never a ``SpendLedger``: a holder able to read a totals
                projection has acquired a permissions-owned history it has no use for
                (ADR-0194 §5).
            max_results: ``Settings.search_max_results``. At least 1 and at most 3,
                ADR-0231 §5's stated domain.
            max_result_chars: ``Settings.search_max_result_chars``. At least 1.
            declaration: This searcher's **own registered declaration**, held by value
                and compared against for equality on every call — the untampered
                original ADR-0029 §2's second check needs and that no registry holds
                for this integration. Defaults to :data:`WEB_SEARCH`, which is the one
                a composition root registers.
            name: The source instance every minted record is attested to (§10).
                Non-blank and unchanged by ``Identifier``'s own validation, checked
                here rather than at the first mint.

        **No deadline is held here** (ADR-0241 §3). The bound arrives on every
        :meth:`search` as the caller's own ``timeout``, and this class keeps no
        second copy of it: a searcher holding one would be a searcher able to
        disagree with its caller about the window it is running in.

        Raises:
            ValueError: If ``name`` is blank or is a value ``Identifier`` would strip,
                or if either bound is not an exact ``int`` or is outside ADR-0231 §5's
                domain for it. Each is a state this searcher could not act from,
                refused where it is configured rather than at an arbitrary later call.
        """
        if not name.strip() or name.strip() != name:
            # ADR-0231 §17: `name` is "a value `Identifier` accepts unchanged", and
            # §10 requires it to **equal** a minted record's `reported_by`, which is
            # typed `Identifier` and strips what it accepts. A searcher named
            # " search " would otherwise satisfy every other clause and mint a record
            # no equality this ADR asserts could hold — at a mint, far from here.
            msg = f"name must be non-blank and unchanged by Identifier's validation, got {name!r}"
            raise ValueError(msg)
        _checked_bound("max_results", max_results, ceiling=_MAX_SEARCH_RESULTS)
        _checked_bound("max_result_chars", max_result_chars, ceiling=None)
        self._transport = transport
        self._ledger = ledger
        self._gate = gate
        self._max_results = max_results
        self._max_result_chars = max_result_chars
        self._declaration = declaration
        self._name = name

    @property
    def name(self) -> str:
        """The source instance this searcher serves (ADR-0231 §10, §17).

        Returns:
            The identity, the same string on every access and across every call: it is
            read off a slot written once at construction and by nothing since.
        """
        return self._name

    async def request(self, query: str, /) -> ActionRequest | None:
        """Propose the search ``query`` would make (ADR-0231 §17).

        **Never ``None`` from this implementation**, and that is ADR-0231 §17's two
        clauses agreeing rather than disagreeing: ``app/composition.py`` "constructs a
        searcher only where an account is connected", so a deployment that connected
        none holds no ``WebSearchEgress`` at all. The contract's ``None`` arm is what a
        ``WebSearcher`` whose account can be absent answers with, and the canonical
        fake is the implementation that exhibits it.

        **It reads no store, mints no identifier, opens no channel and reaches no
        authorisation conclusion.** The binding, the ruling, the audit record and the
        construction of the ``ToolCall`` are all the caller's (§6).

        Args:
            query: The query one composition wrote for this turn, carried byte for byte
                from that servicing's ``QueryOutcome.query`` (§11).

        Returns:
            The request to rule on: this searcher's declaration by value, exactly the
            origin and the query as arguments, and ``None`` for ``step_id``,
            ``execution_id`` and ``egress_binding`` — a ``WEB_SEARCH`` decision has no
            plan step and no execution (§6), and the binding is derived by
            ``EgressBinder`` and accepted from nobody (§6).
        """
        parameters: dict[str, FrozenJson] = {
            ORIGIN_ARGUMENT: self._transport.origin,
            QUERY_ARGUMENT: query,
        }
        return ActionRequest(tool=self._declaration, parameters=parameters)

    async def search(  # noqa: C901 — one branch per exit ADR-0241 §4 and §7 distinguish: this deadline's expiry, an upstream `TimeoutError`, an external cancellation and an invented one
        self,
        call: ToolCall,
        /,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1, §2); a caller wrapping this in `asyncio.timeout` cancels the searcher mid-await and cannot classify its own expiry
    ) -> SearchOutcome:
        """Perform the authorised search, and mint what its answer transcribes.

        See the class docstring for the order and why it is the decision.

        Args:
            call: The authorised call. Read only through the revalidated copy this
                method makes of it, never as handed.
            timeout: The caller's bound on this call (ADR-0241 §1). Checked
                **first**, before the revalidation, before the credential read,
                before the gate and before any channel — so a refused value reaches
                no store, appends no claim and opens nothing. The window it opens
                starts there too, so the revalidation is inside it and the admission
                is handed what is left. It covers the whole of what follows *except*
                the two ledger appends, which ADR-0192 §3 leaves unbounded by this
                seam.

        Returns:
            One outcome carrying records or a refusal.
            :attr:`~ai_assistant.core.types.SearchRefusal.DEADLINE_EXPIRED` where
            **this** deadline fired, at any of the three places it can (ADR-0241
            §4): during the revalidation and inside or immediately after the spend
            admission, where no claim was appended and no row is written, and inside
            the call, where the completion carries the declaration's
            ``interrupted_outcome`` and an ``UNKNOWN`` cost (§5). An interruption the
            callable **absorbed** is read off this frame's own deadline and its own
            task rather than off what came back, so a transport that catches the
            cancellation and answers anyway is not recorded as having succeeded.

        Raises:
            ValueError: If ``timeout`` is not a ``timedelta`` or is not strictly
                positive (ADR-0241 §1). Refused before anything is read.
            ToolError: If the searcher's own callable raised a ``CancelledError``
                with **nothing cancelled** — ADR-0031 §2's invented cancellation,
                which ADR-0241 §7 makes a fault rather than a teardown, so it
                reaches ADR-0226 §5's degradation and never ends the turn.
            ToolBindingError: If the call does not survive revalidation, carries a
                definition unequal to this searcher's registered original, is not
                authorised by its decision, or carries no egress binding. **No
                credential is read, no channel is opened, no admission is sought and
                no claim is appended for any of them.**
            TransportPinError: If the call is bound to another connection, another
                endpoint or another origin than the one this integration is registered
                for. Likewise, though inside the claim: the pin is the transport's, and
                a call bound elsewhere is a fault rather than a source reason.
            AuthorisationSpentError: If the ledger refuses the claim because the
                authorisation is spent (ADR-0192 §1).
            UnrecordedAuthorisationError: If the trail holds no decision equal to this
                call's under its id, or holds one that is not an ``ALLOW``.
            AuditError: If the claim append failed with anything that is not an
                ``AssistantError``. A failure of the **completion** append is absorbed
                and reaches the operator as a diagnostic, exactly as it is at the
                invocation seam (ADR-0192 §3).
            ConnectionStoreError: If the **first** connection-record read failed. A
                store outage asserts nothing about the call and is never converted
                (ADR-0148 §6).
            CancelledError: Re-raised unchanged when this task is cancelled from
                outside (ADR-0060, ADR-0241 §7). Never converted into
                ``DEADLINE_EXPIRED``: a cancellation this seam did not itself issue
                is not this seam's expiry.
        """
        # **First, and before the revalidation** (ADR-0241 §1): a `timeout` this
        # searcher could not run under is refused before the call is revalidated,
        # before the credential is read, before the spend gate is consulted and
        # before any channel is opened. `checked_timeout` is ADR-0029 §4's own guard
        # — one implementation of the rule, reached from both seams — and it returns
        # a plain `timedelta` rebuilt from the base class's fields, so a subclass
        # whose `total_seconds` raises decides nothing after the claim has landed.
        duration = checked_timeout(timeout)
        # **And the window opens here, ahead of the revalidation** (ADR-0241 §1): the
        # bound covers "the revalidation, ADR-0194 §3's spend admission, the credential
        # read, the channel, the response read and the transcription", so a clock
        # started after the checks would hand the admission and the callable a *fresh*
        # budget — the same defect one stage along that ADR-0194 §3 names for the
        # admission, and the reason `admitted_call` is handed what is left rather than
        # the whole of it.
        loop = asyncio.get_running_loop()
        expires_at = loop.time() + duration.total_seconds()
        checked, binding, origin, query = self._authorised(call)

        outcome: SearchOutcome | None = None

        async def act(remaining: timedelta) -> ToolResult:
            nonlocal outcome
            entered_with = pending_cancellations()
            deadline = asyncio.timeout(remaining.total_seconds())

            try:
                async with deadline:
                    outcome = await self._asked(binding, origin=origin, query=query)
            except asyncio.CancelledError as cancellation:
                if pending_cancellations() > entered_with:
                    # An external cancellation: delivered onward unchanged, and
                    # `consumed_call` completes the claim with the declaration's
                    # `interrupted_outcome` and an `UNKNOWN` cost before it leaves
                    # (ADR-0060 §1, ADR-0192 §3, ADR-0241 §7).
                    raise
                # ADR-0031 §2's invented cancellation — the count did not move, so
                # nothing was cancelled and this is a fault the callable raised.
                # ADR-0241 §7 says what it must *not* become: not a teardown that
                # ends the turn, and not an outcome. So it leaves as an
                # `AssistantError`, which is what reaches ADR-0226 §5's degradation
                # and §8's `SEARCH_FAILED`. The claim is left open, exactly as it is
                # for a `TransportPinError` raised at the same point — the honest
                # state for a send that may have happened (§6).
                msg = (
                    f"{self._declaration.id}: the searcher raised a cancellation with "
                    f"nothing cancelled, so the search did not complete"
                )
                raise ToolError(msg) from cancellation
            except TimeoutError:
                # **Classification keys on whether *this* deadline fired, never on
                # the exception's type** (ADR-0241 §7). `Timeout.expired()` is the
                # seam's own state and no callable can reset it; a `TimeoutError` an
                # upstream library raised for its own reasons leaves it `False`, and
                # that is the transport's failure rather than this seam's expiry.
                #
                # Either way the completion below still lands, because a claim is
                # owed one on every exit this frame observes (ADR-0192 §3).
                #
                # **And an external cancellation outranks both classes.** A transport
                # that catches the task's own cancellation and raises a
                # ``TimeoutError`` instead arrives here with the count still moved,
                # and answering it with a refusal would be the absorption ADR-0060 §1
                # says a method never performs.
                self._deliver_absorbed(entered_with)
                outcome = _refused(
                    SearchRefusal.DEADLINE_EXPIRED
                    if deadline.expired()
                    else SearchRefusal.TRANSPORT_FAILED
                )
            except Exception:
                # **A fault the callable raised is still not evidence that nothing was
                # cancelled.** A connection reader that catches this task's
                # `CancelledError` and raises `ConnectionStoreError` instead leaves the
                # frame holding an ordinary exception, and letting it out would degrade
                # the turn under ADR-0226 §5 while the cancellation the executor asked
                # for was never delivered. Where nothing was cancelled the fault leaves
                # exactly as it arrived — unwrapped, unannotated and with no outcome
                # invented for it (ADR-0029 §3). `BaseException` is deliberately not
                # caught: a process being torn down is not an interruption of this
                # call, and the open claim is the honest state for it (ADR-0192 §3).
                self._deliver_absorbed(entered_with)
                if not deadline.expired():
                    raise
                # **And this deadline having fired outranks the fault too.** The
                # `Timeout` context calls `uncancel` on its way out whatever the
                # exception was, so a collaborator that catches the expiry's
                # cancellation and raises a store fault instead leaves no trace in the
                # count — but `Timeout.expired()` is this seam's own state and no
                # callable can reset it. Letting the fault out would degrade the turn
                # under ADR-0226 §5 and leave the claim open, where §5 requires an
                # `INDETERMINATE` completion for a call that outran its bound. This is
                # `invoke`'s `_interruption(...) or internal_failure(...)` one seam
                # over, in the same order and for the same reason.
                outcome = _refused(SearchRefusal.DEADLINE_EXPIRED)
            else:
                # **The state is read from the task and the deadline rather than
                # inferred from what came back** (ADR-0029 §4, and `_interruption`'s
                # own clause one seam over). Nothing forces a callable to let an
                # interruption through: a transport that catches this deadline's
                # cancellation and returns a channel leaves the frame holding an
                # answer and no exception, and trusting that return would record
                # `SUCCEEDED` for a call that outran its bound — the seam's worst
                # available bug, and the one an implementation is most likely to have.
                self._deliver_absorbed(entered_with)
                if deadline.expired():
                    # `Timeout.expired()` is this seam's own state and no callable can
                    # reset it, which is what makes the deadline half tool-proof where
                    # the cancellation half above is not (ADR-0029 §4's own note).
                    outcome = _refused(SearchRefusal.DEADLINE_EXPIRED)
            return _result_of(outcome, self._declaration, duration)

        async def consume(remaining: timedelta) -> ToolResult:
            # **Before the claim, and this is the position that matters** (ADR-0192
            # §1). A gate that swallowed the caller's cancellation and then admitted
            # leaves `admitted_call` free to run this, and both `_claimed` and `act`
            # sample their own baselines *after* that absorption — so neither sees it,
            # and the search would append a claim, read a credential and open a channel
            # for a turn the executor had already cancelled. The pre-admission baseline
            # is the only one that still carries the fact, and checking it here is what
            # keeps the cancellation *above* ADR-0192 §1's placement: no claim, so no
            # completion is owed and none is written. `admitted_call`'s `finally` still
            # releases the reservation on the way out.
            self._deliver_absorbed(admitting)
            return await consumed_call(
                ledger=self._ledger,
                definition=self._declaration,
                decision=checked.decision,
                act=lambda: act(remaining),
            )

        remaining = expires_at - loop.time()
        if remaining <= 0:
            # The window closed while this frame was revalidating. `admitted_call`
            # has the same branch one stage along and for the same reason: entering
            # the next stage now would run it outside the deadline the caller set,
            # and `checked_timeout` refuses a non-positive duration rather than
            # accepting one and calling it expired. **No claim was appended and no
            # channel was opened**, so this is §5's before-the-claim exit exactly as
            # an expiry inside the admission is.
            return _refused(SearchRefusal.DEADLINE_EXPIRED)

        watched = _UpstreamWatchingGate(self._gate)
        admitting = pending_cancellations()
        try:
            await admitted_call(
                gate=watched,
                # Read off the revalidated, detached copy the checks above produced
                # and never off the argument (ADR-0194 §3, §11) — and the second check
                # has already established that copy's definition equals this
                # searcher's own registered original.
                estimate=checked.request.tool.cost,
                definition=self._declaration,
                # ADR-0194 §3: the admission is awaited **inside** this deadline and
                # `act` is handed what is left of it, so the two are one window and
                # not two (ADR-0241 §1's admission clause, and §12's Arm 12). What is
                # passed is what remains of the caller's budget after the revalidation
                # — the same arithmetic `admitted_call` then performs between the gate
                # and the callable, one stage earlier.
                timeout=timedelta(seconds=remaining),
                act=consume,
            )
        except SpendCeilingError, SpendUndeterminedError:
            # ADR-0231 §15: "A refusal by the gate is a disposition (§13) and never a
            # retry." Caught here rather than left to leave, because §17 makes every
            # `SearchRefusal` member a return value — and this is the one exit above
            # the claim that has one, so nothing was read and no row was written.
            #
            # A gate that swallowed this task's cancellation and then refused is
            # answering a cancelled turn with a value, so the cancellation goes first
            # (ADR-0060 §1). ADR-0194 §4's payload-free refusal is untouched: nothing
            # here catches, wraps or annotates one.
            #
            # **And this deadline having fired outranks the substituted refusal too**,
            # exactly as it outranks a substituted fault in the branch below and inside
            # `act` one stage down. A gate that swallows the expiry's cancellation and
            # raises a spend class instead leaves no trace in the count —
            # `asyncio.Timeout.__aexit__` calls `uncancel` on its way out whatever the
            # exception was — so `watched.interrupted`, read from inside that context,
            # is the only surviving record that the window closed. ADR-0241 §4 defines
            # the member as the bound expiring *before the search produced an answer*,
            # which is what happened, and §7 keys the classification on whether **this**
            # deadline fired. §9 grants no precedence either way: it forbids collapsing
            # two bounds or reporting one under the other's member, and answering a call
            # that in fact ran out of time with `SPEND_REFUSED` would tell an operator
            # their ceiling was crossed — a false operator fact of exactly the kind §9
            # exists to prevent. `_deliver_absorbed` has already gone first, so what is
            # left here can only be this window closing.
            self._deliver_absorbed(admitting)
            return _refused(
                SearchRefusal.DEADLINE_EXPIRED
                if watched.interrupted
                else SearchRefusal.SPEND_REFUSED
            )
        except Exception:
            # **An ordinary fault out of the admission is not evidence that nothing was
            # cancelled either.** A gate that catches the caller's cancellation and
            # raises an `AuditError` instead would otherwise reach ADR-0226 §5's
            # degradation and ADR-0241 §8's `SEARCH_FAILED`, letting a cancelled turn
            # degrade and carry on. The transport's counterpart is checked inside
            # `act`; this is the same rule at the one stage above it.
            self._deliver_absorbed(admitting)
            if not watched.interrupted:
                # Nothing interrupted the admission, so the fault is the whole of what
                # happened and it leaves exactly as it arrived — unwrapped,
                # unannotated and with no outcome invented for it (ADR-0029 §3).
                raise
            # **And this deadline having fired outranks the fault**, exactly as it does
            # inside `act` one stage below. The check above has already established
            # that the interruption was not the caller's, so it was this window
            # closing; no claim was appended for it, so no completion is owed
            # (ADR-0192 §1, ADR-0241 §5).
            return _refused(SearchRefusal.DEADLINE_EXPIRED)
        # **A `CancelledError` that reaches here is delivered onward, and this frame
        # classifies none of them.** An earlier revision branched on the count's delta
        # and got it backwards: a caller already carrying a cancellation request when
        # `search` was entered moves the count by nothing, so a cancellation the loop
        # delivered during the claim — which `_claimed` has already completed the claim
        # for and re-raised, exactly as ADR-0192 §1 requires — read as "invented" and
        # became a fault. `consume.py`'s `_driven` states the distinction in terms: a
        # cancellation the event loop **delivered** is external whatever the delta says.
        # The delta answers a question about a value a collaborator **returned**, which
        # is where `_deliver_absorbed` uses it and where it is sound; nothing here can
        # tell a delivery from an invention, so nothing here tries (ADR-0060 §1).
        self._deliver_absorbed(admitting)
        if outcome is None:
            # `admitted_call` returned without entering `act`. **No claim was appended,
            # so no completion row is written** — ADR-0192 §1's placement relied upon
            # and not moved, and inventing a row for a call that provably never ran
            # would be the opposite error to the one ADR-0241 §5 corrects. The
            # `ToolResult` that frame returned for the exit is dropped here for the
            # same reason: nothing appended a claim for it to complete.
            #
            # **And which exit it was is decided by provenance and never by a clock**
            # (ADR-0241 §7). `admitted_call` answers `expiry_failure` for *every*
            # `TimeoutError` out of `gate.admit_invocation` — including one the gate
            # raised of its own accord, which is not this deadline firing and which §7
            # forbids reporting as one. `_UpstreamWatchingGate` captures that where it
            # is unambiguous, at the call itself; see its docstring for why the
            # `Task.cancelling()` count and not a comparison against `expires_at`.
            if watched.upstream is not None:
                return _refused(SearchRefusal.TRANSPORT_FAILED)
            return _refused(SearchRefusal.DEADLINE_EXPIRED)
        return outcome

    def _deliver_absorbed(self, entered_with: int) -> None:
        """Deliver an interruption a collaborator swallowed, before anything else.

        **A pending external cancellation outranks every classification this seam
        could make**, on every exit — an exception a collaborator raised as well as a
        value it returned. ADR-0029 §4 keeps that on the executor and ADR-0060 §1 says
        a method never absorbs one, so a transport that catches the cancellation and
        then raises a ``TimeoutError``, a connection reader that replaces it with a
        store fault, and a gate that swallows it and refuses are all the same case:
        the object that came back says nothing about whether this turn was cancelled.
        This is ``_interruption``'s first clause one seam over, in one place because a
        path that forgot it is what rounds 2 and 3 each found.

        **The count and not the class** (ADR-0031 §2): it is a lifetime figure only
        ``uncancel`` lowers, so a collaborator that catches the exception cannot lower
        it, and reading it as a *delta* from a baseline taken on entry is what keeps a
        caller's earlier, unrelated cancellation from failing this call.

        Freshly raised rather than re-raised: the original was consumed inside the
        collaborator, and what matters is that the cancellation reaches the executor
        rather than being answered with a result. Where a claim is open,
        ``consumed_call`` still completes it with the declaration's
        ``interrupted_outcome`` and an ``UNKNOWN`` cost on the way past (ADR-0192 §3);
        where none was appended, none is owed (ADR-0241 §5).

        Args:
            entered_with: The count sampled before the work this is guarding.

        Raises:
            CancelledError: If a cancellation of the invoking task is still pending.
        """
        if pending_cancellations() > entered_with:
            swallowed = (
                f"{self._declaration.id}: the searcher absorbed the cancellation of "
                f"its invoking task"
            )
            raise asyncio.CancelledError(swallowed)

    def _authorised(self, call: ToolCall) -> tuple[ToolCall, EgressBinding, str, str]:
        """Run ADR-0029 §2's three checks, and hand back what survived them.

        **Inside the caller's window and before anything else** (ADR-0231 §6,
        ADR-0241 §1): the call is revalidated and detached, its definition is compared
        for equality against this searcher's **own registered declaration** — the
        authoritative original here, standing where ADR-0029 §2 puts the registry's —
        and ``PermissionDecision.authorises`` is re-evaluated against that same copy.
        Every later step reads what this returns and never the argument.

        Synchronous throughout, which is what makes the ordering a fact rather than a
        convention: there is no ``await`` here for a reprovisioning, a cancellation or
        a second caller to be delivered at, so nothing observed by these checks can
        move between them and the send.

        Args:
            call: The call as handed, read only through the copy this makes of it.

        Returns:
            The revalidated call, its binding, and the two arguments its schema
            declares — each already narrowed, so no later frame carries a ``cast``.

        Raises:
            ToolBindingError: If the call does not survive revalidation, carries a
                definition unequal to this searcher's registered original, is not
                authorised by its decision, or carries no egress binding. **No
                credential is read, no channel is opened, no admission is sought and
                no claim is appended for any of them.**
        """
        checked = revalidated_call(call)
        if checked.request.tool != self._declaration:
            msg = (
                f"{self._declaration.id}: the definition carried by this call is not the "
                f"one this searcher registered, so the thing about to run is not the "
                f"thing declared (ADR-0029 §2, ADR-0231 §6)"
            )
            raise ToolBindingError(msg)
        if not checked.decision.authorises(checked.request):
            msg = (
                f"{self._declaration.id}: decision {checked.decision.id!r} does not "
                f"authorise this request, so the thing about to run is not the thing "
                f"that was authorised (ADR-0029 §2, ADR-0231 §6)"
            )
            raise ToolBindingError(msg)
        binding = checked.request.egress_binding
        origin = checked.request.parameters.get(ORIGIN_ARGUMENT)
        query = checked.request.parameters.get(QUERY_ARGUMENT)
        if binding is None or not isinstance(origin, str) or not isinstance(query, str):
            # The schema refuses a call carrying anything but the two strings, and
            # revalidation re-ran it; ADR-0148 §8's third floor refuses an `ALLOW`
            # with no binding. So this is unreachable through the seam that builds one
            # — and it is checked anyway, because what would otherwise stand here is a
            # `cast`, and the value it would assert about is the recipient.
            msg = (
                f"{self._declaration.id}: this call carries no egress binding, or its "
                f"arguments are not the two strings its schema declares, so there is no "
                f"authorised request to make (ADR-0148 §8, ADR-0231 §5)"
            )
            raise ToolBindingError(msg)
        return checked, binding, origin, query

    async def _asked(self, binding: EgressBinding, *, origin: str, query: str) -> SearchOutcome:
        """Make the one request through the seam, and read the answer under §10.

        Args:
            binding: The authorised binding, handed to the seam whole and never
                re-derived (ADR-0148 §4).
            origin: The origin the ruled call carries, which the seam compares against
                its registration before it reads anything.
            query: The authorised query — "the one value that crosses into the request
                from outside" this package (ADR-0231 §5), encoded here into the
                parameter the provider documents.

        Returns:
            The outcome.

        Raises:
            TransportPinError: If the call is bound elsewhere.
            ConnectionStoreError: If the first record read failed.
            CancelledError: Re-raised unchanged, after the seam has released its
                channel (ADR-0060 §1).
        """
        target = (
            f"{_PROVIDER_PATH}"
            f"?{_PROVIDER_QUERY_PARAMETER}={_percent_encoded(query)}"
            f"&{_PROVIDER_COUNT_PARAMETER}={self._max_results}"
        )
        try:
            response = await self._transport.fetch(
                binding,
                origin=origin,
                target=target,
                credential_field=_PROVIDER_CREDENTIAL_FIELD,
                fields=_PROVIDER_FIELDS,
            )
        except HttpsResponseTooLargeError:
            return _refused(SearchRefusal.RESPONSE_TOO_LARGE)
        except BoundCallChangedError:
            # ADR-0148 §6's limbs, whose refusal ADR-0231 §5 names: an account that is
            # not connectable, one recorded for another identity, one that moved
            # across the credential read, a slot the keyring holds nothing under, and
            # a credential no request field will carry. Every one of them discarded
            # the credential and wrote nothing to any channel — none was opened.
            return _refused(SearchRefusal.PROVIDER_REFUSED)
        except HttpsRedirectRefusedError, MalformedHttpResponseError, TransportError:
            # Statements about this system's own reach or about the far end's HTTP
            # framing rather than about what the provider said: a redirect it will not
            # follow, a response that is not HTTP/1.1, a channel it could not open,
            # verify or continue. What the provider *said* is `PROVIDER_REFUSED`.
            return _refused(SearchRefusal.TRANSPORT_FAILED)
        return self._read(response)

    def _read(self, response: HttpsResponse) -> SearchOutcome:
        """Read one documented response into records, or into the class that refuses it.

        The order is ADR-0231 §10's own: the response's **shape** is decided first —
        "A response whose top-level shape is not the one the provider documents is
        refused ``PROVIDER_REFUSED`` before this clause is reached" — and only then its
        declared instant, which is the clause §10 states after the transcription rule.

        Args:
            response: What the seam read off the channel, under its bound.

        Returns:
            The outcome.
        """
        if response.status != _PROVIDER_OK:
            return _refused(SearchRefusal.PROVIDER_REFUSED)
        results = _provider_results(response.body)
        if results is None:
            return _refused(SearchRefusal.PROVIDER_REFUSED)
        reported_at = _declared_instant(response.headers)
        if reported_at is None:
            # ADR-0231 §10, ADR-0092 §3: "A response that declares **no** instant mints
            # **no record**", and a value that cannot be read as an instant "is not a
            # declared one". There is no substitute, and none is reached for.
            _log.info("web_search_response_declared_no_instant", tool_id=self._declaration.id)
            return _refused(SearchRefusal.UNATTESTED)
        return self._minted(results, reported_at=reported_at)

    def _minted(
        self, results: Sequence[Mapping[str, FrozenJson]], *, reported_at: datetime
    ) -> SearchOutcome:
        """Transcribe the results ADR-0231 §10 keeps, and mint one record for each.

        **Dropped results are stepped over rather than counted against the bound**: the
        walk is in the order the provider returned them and stops once
        ``search_max_results`` records exist, so a response whose first result is over
        the content bound still yields the count the operator configured where the
        provider supplied enough usable ones. That reading is §10's "at most
        ``search_max_results`` ``MemoryRecord``s, one per result the provider returned,
        in the order it returned them" — the bound is on the **records** and the order
        is on the walk. The alternative, capping the results considered and then
        dropping, satisfies the same sentence and returns fewer records than the
        operator asked for whenever a drop lands early; it is named here so that the
        choice reads as one that was made.

        Args:
            results: The documented response's results, in order.
            reported_at: The instant the response declared.

        Returns:
            The outcome: the records, or ``NO_RESULT`` where the response carried none
            and where §10 dropped every one it did.
        """
        minted: list[MemoryRecord] = []
        for result in results:
            if len(minted) == self._max_results:
                break
            content = _transcription(result, max_chars=self._max_result_chars)
            if content is not None:
                minted.append(self._record(content, reported_at))
        if not minted:
            return _refused(SearchRefusal.NO_RESULT)
        return SearchOutcome(reported_at=reported_at, records=tuple(minted))

    def _record(self, content: str, reported_at: datetime) -> MemoryRecord:
        """One ``SEMANTIC``, ``EXTERNAL``-sourced record carrying ``content``.

        **No model is on this path** (ADR-0231 §10): nothing summarises, abridges,
        rewrites, re-ranks, annotates, deduplicates or classifies a result between the
        provider's response and this record.

        ``reported_by`` is this searcher's own identity — the **source instance**, and
        never a vendor, an origin, a URL or a credential (ADR-0092 §3) — and what it
        reports is *what the provider's index returns for this query now*. The record
        makes no claim about when the words it carries were composed, by whom, or
        whether they are true.

        Args:
            content: The transcription, verbatim.
            reported_at: The instant the response declared.

        Returns:
            The record. Its id is minted here and is opaque to the source (ADR-0092
            §6); it is rendered to no model, accepted from none, and — since ADR-0231
            §16 stores nothing — never installed.
        """
        return SemanticMemory(
            id=uuid4().hex,
            content=content,
            fact=content,
            provenance=Provenance(
                source=MemorySource.EXTERNAL,
                confidence=_ATTESTED_CONFIDENCE,
                evidence=(),
                last_updated=reported_at,
                last_confirmed_at=reported_at,
                attestation=Attestation(
                    reported_by=self._name,
                    reported_at=reported_at,
                    # This producer states no position for a result in the source's own
                    # world, and a result's rank is not a half-open interval of
                    # instants (ADR-0117 §2, ADR-0231 §10).
                    extent=None,
                ),
                # Asserts nothing in this band (ADR-0106 §1). The externality this
                # record carries is `MemorySource.EXTERNAL`, which `band_of` places in
                # `ATTESTED`; this field is the `DERIVED` band's question.
                derived_from_external=False,
            ),
            topics=(),
            about_person=None,
        )


__all__ = [
    "MAX_JSON_DEPTH",
    "ORIGIN_ARGUMENT",
    "QUERY_ARGUMENT",
    "WEB_SEARCH",
    "WEB_SEARCH_ID",
    "WEB_SEARCH_SOURCE_NAME",
    "WebSearchEgress",
    "checked_search_cost",
]
