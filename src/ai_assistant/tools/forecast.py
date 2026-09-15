"""The forecast integration: its declaration, its provider adapter, and its forecaster.

:mod:`ai_assistant.tools.web_search`'s counterpart for ADR-0260's kind, and it carries
the same division. This module holds the **declaration**, the request shape and the
response shape ADR-0260 §6 puts "inside ``ai_assistant.tools``", and the
:class:`~ai_assistant.core.protocols.Forecaster` that drives the whole of §6's order;
:mod:`ai_assistant.tools.egress` — the module ADR-0154 §1 designates and where §6 rules
a forecast request leaves from — holds
:class:`~ai_assistant.tools.egress.HttpsEgressTransport`, which is the thing that reads
the account's credential and opens a channel to the world. **Nothing here reads a
secret, holds a ``Secrets`` face or constructs a transport**; the credential is the
seam's, at the position ADR-0148 §7 puts it, and this module never holds one.

**This declaration is registered in no ``ToolRegistry``** (ADR-0260 §1), which is the
hinge ADR-0231 §5's design rests on and which this decision takes for its own reason: a
registry entry would put the capability in front of the planner, and ADR-0208 §1 —
*"A component on the turn path that wants records the supply does not hold does not
obtain them by invoking a tool"* — is then satisfied by not being a tool rather than by
a rule. ``build_default_registry`` takes no forecast argument, so the absence is a
property of the signatures rather than of a line somebody remembered not to write.

**Three arguments, and the coordinate is two of them.** ADR-0148 §8's third floor
refuses an ``ALLOW`` where a request carries no canonical destination set, and the set
is derived from spans whose argument declares a destination (ADR-0152 §3) — so
``origin`` bears ``x-egress-destination: "https"`` at the ``operational`` tier, exactly
as the search's does. The two coordinate arguments bear **no** destination and the
``personal`` tier: ADR-0146 §5 gives the tier to a field *every value of which* carries
one, and every value of a configured latitude is the owner's own place, which is what
the declaration's ``discloses=(PERSONAL,)`` claims at the other end. **They are the
request's payload and the ruling ranges over them**, which is ADR-0017 §3's "what is
transmitted is bound to what was authorised" holding at this seam as it holds at the
search's.

**No place crosses the *planning* seam, which is the seam ADR-0260 §3 is about.** The
coordinate is read from ``Settings`` by the composition root, held by the forecaster as
its own configuration, and written into a request the policy and the trail see. It is
rendered to no model and accepted from none, there is no ``ReadAsk`` field for it, and a
planner cannot name it — so the failure mode ADR-0231 §1 is built against is unreachable
rather than forbidden.

**The reference provider, and what it is for** (ADR-0260 §12, §14). The documented
format below is *this lane's* reference provider — the M33 walkthrough's forecast half
until a real one lands. ADR-0260 §14 names the intended first **real** provider,
Open-Meteo, and gates it on #2396: it needs no credential, and no connection shape in
this corpus carries an identity without one. So the reference provider is a source that
**accepts a credential and does not use it**, reached exactly as any other integration
is, and replacing the adapter is replacing the constants below and
:func:`_provider_days` in this one module.
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

import structlog

from ai_assistant.core.errors import ToolBindingError, ToolError, TransportError
from ai_assistant.core.types import (
    ActionRequest,
    Attestation,
    CostBasis,
    DataTier,
    DestinationProtocol,
    ForecastOutcome,
    ForecastRefusal,
    Idempotency,
    MemorySource,
    Provenance,
    ReportedExtent,
    Reversibility,
    RiskLevel,
    SemanticMemory,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.tools.consume import pending_cancellations
from ai_assistant.tools.egress import (
    BoundCallChangedError,
    HttpsRedirectRefusedError,
    HttpsResponseTooLargeError,
    MalformedHttpResponseError,
)
from ai_assistant.tools.egress_declaration import DESTINATION_KEYWORD, TIER_KEYWORD
from ai_assistant.tools.http_reading import declared_instant, decoded_object
from ai_assistant.tools.registry import checked_timeout, revalidated_call

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.types import EgressBinding, FrozenJson, MemoryRecord, ToolCall
    from ai_assistant.tools.egress import HttpsEgressTransport, HttpsResponse

_log = structlog.get_logger(__name__)

#: The id this declaration is registered under at the egress seam, once an account
#: exists to bind it to. One tool per connected account (ADR-0148 §6) means a
#: registered id names the account as well as the operation; this bare form names
#: neither, which is why the constant is a template rather than a registration.
FORECAST_READ_ID: Final = "forecast_read"

#: The **source instance** every record a forecast read mints is attested to
#: (ADR-0260 §4, §5; ADR-0092 §3): "the owner's forecast", and never a vendor, never
#: an origin, never a URL, never a credential and **never a place**. A constant
#: rather than a ``Settings`` field, for :data:`WEB_SEARCH_SOURCE_NAME`'s reason: a
#: field naming the source would be a vendor chosen through configuration.
#:
#: Non-blank and unchanged by ``Identifier``'s own validation — ``name.strip() ==
#: name`` — which ADR-0260 §4 requires of every ``Forecaster.name`` because §5
#: requires this value and a minted record's ``reported_by`` to be **equal**.
FORECAST_SOURCE_NAME: Final = "forecast"

#: The argument carrying the recipient, which ADR-0152 §3's keyword makes the value a
#: ruling, a grant and a confirmation all range over.
ORIGIN_ARGUMENT: Final = "origin"

#: The two arguments carrying the place this deployment configured (ADR-0260 §3,
#: §11). They bear no destination keyword — they select no recipient — and the
#: ``personal`` tier, because every value of either is the owner's own place.
LATITUDE_ARGUMENT: Final = "latitude"
LONGITUDE_ARGUMENT: Final = "longitude"

#: ADR-0260 §11's ceiling on ``forecast_max_days``: §7 makes three the figure that
#: keeps the servicing precedence true in every configuration. Stated here as well as
#: in ``Settings`` because a forecaster built directly by a test is one a bound could
#: be widened at.
_MAX_FORECAST_DAYS: Final = 3

#: The domain ``Settings`` states for a configured coordinate (ADR-0260 §11),
#: restated here for the same reason.
_MAX_LATITUDE: Final = 90.0
_MAX_LONGITUDE: Final = 180.0


def _origin() -> dict[str, FrozenJson]:
    """The origin argument's subschema, built fresh on every call.

    Built rather than shared, for ``send_email``'s and ``web_search``'s reason:
    ``core`` freezes what a ``ToolDefinition`` ends up holding, but the literal handed
    to it is an ordinary ``dict``, and a shared mapping would be reachable from
    anywhere that imported it.

    Returns:
        The subschema, owned by the caller.
    """
    return {
        "type": "string",
        DESTINATION_KEYWORD: DestinationProtocol.HTTPS.value,
        TIER_KEYWORD: DataTier.OPERATIONAL.value,
    }


def _coordinate(*, maximum: float) -> dict[str, FrozenJson]:
    """One coordinate argument's subschema, built fresh on every call.

    Args:
        maximum: The degrees this axis runs to, which is also its negative floor.

    Returns:
        The subschema, owned by the caller. It declares **no** destination keyword —
        a coordinate selects no recipient — and the ``personal`` tier, which is what
        ADR-0146 §5 gives a field every value of which carries one.
    """
    return {
        "type": "number",
        "minimum": -maximum,
        "maximum": maximum,
        TIER_KEYWORD: DataTier.PERSONAL.value,
    }


FORECAST_READ: Final = ToolDefinition(
    id=FORECAST_READ_ID,
    capability="forecast_read",
    description="Ask the configured forecast provider what it says about the days ahead.",
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
        "properties": {
            ORIGIN_ARGUMENT: _origin(),
            LATITUDE_ARGUMENT: _coordinate(maximum=_MAX_LATITUDE),
            LONGITUDE_ARGUMENT: _coordinate(maximum=_MAX_LONGITUDE),
        },
        "required": [ORIGIN_ARGUMENT, LATITUDE_ARGUMENT, LONGITUDE_ARGUMENT],
        "additionalProperties": False,
    },
)
"""The declaration ADR-0016 §1 asks for, with every safety field argued.

ADR-0016 §1: "Every field that a permission decision depends on is required … a
default is a claim", so each is stated on its own ground and none of them is read off
what the integration is called:

- ``discloses=(PERSONAL,)``. A coordinate the owner configured is Tier 1 and it leaves
  the device, which is what this field is for. Non-empty is what makes ADR-0021 §5's
  disclosure floor bite on every read, so none is auto-granted and the approver is the
  user — and ADR-0260 §6's route (c) is what a deployment that configured the provider
  reaches an ``ALLOW`` through, rather than a narrowed declaration. Naming ``SECRET``
  would declare that this integration may select a Tier 0 value for a third party,
  which ADR-0146 §3 forbids outright.
- ``reads=(SECRET,)``. The callable reads an ``INTEGRATION``-scoped credential, which
  is Tier 0, and ADR-0148 §7 makes that read part of this call — **including for the
  reference provider, which accepts a credential and does not use it** (ADR-0260 §12).
  ``reads=()`` would be the false claim ADR-0016 §1 names.
- ``writes=()``. A forecast read changes nothing this system stores, and ADR-0260 §11
  stores nothing it returns.
- ``side_effecting=True``, which a non-empty ``discloses`` makes structurally
  mandatory anyway.
- ``reversibility=REVERSIBLE``. ADR-0016 §2 scopes reversibility to "the effect on the
  system acted upon" and is explicit that disclosure is a separate axis. A forecast
  read is a **read** of a remote source: nothing at the far end changes, so there is no
  effect to reverse. The disclosure that cannot be withdrawn is real and is carried by
  ``discloses``.
- ``risk_level=LOW``, on ADR-0016 §2's scale of how much damage **one invocation**
  could do, and the three facts that bound it are stronger here than at the search: the
  recipient is a single origin fixed by the configured account and reachable by no
  argument a model can write; the payload is a coordinate **no model can write either**,
  since ADR-0260 §3 gives the ask no argument at all and the value comes from
  ``Settings``; and nothing anywhere changes. ``send_email`` is ``HIGH`` because "a send
  discloses to a recipient chosen per call from arguments a model produced" — both
  halves of that clause are false here.
- ``idempotency=NONE``. No provider guarantees deduplication of a forecast request, so
  ``KEYED`` would advertise a guarantee ADR-0029 §5's derived key cannot make true.
- ``cost``. ADR-0016 §4 keeps "free" and "not known" apart. This template declares
  ``UNKNOWN``; a deployment that knows its per-call figure states ADR-0260 §11's pair,
  and ADR-0236 §3 forbids declaring ``FREE`` where the figure is not known in order to
  reach an ``ALLOW``.

**No lane weakens any of them to make a forecast read reachable.** A ``discloses``
narrowed, a ``risk_level`` or ``reversibility`` restated for that purpose, or a ``cost``
declared ``FREE`` where the figure is unknown are each the mis-declaration ADR-0016 §1
and ADR-0148 §2 refuse.
"""


# --------------------------------------------------------------------------- #
# The reference provider's documented format, chosen inside `tools/`.
# --------------------------------------------------------------------------- #
# ADR-0260 §5 leaves the transcription's form to the implementation and says so in
# terms: "**The form is the provider's, and each implementation pins its own**: the
# field selection, their order, the separators and the omission rule are fixed by the
# implementation that reads that provider's documented format, and are pinned by a
# test of its own. There is no cross-implementation form, and no implementation
# conforms by matching another's output."
#
# **So the constants below are this lane's documented adapter for the reference
# provider**, and the origin is the only part of the request a deployment configures.
#
# **Every transcribed field is a JSON *string* in this format, and that is a decision
# §5 forces.** A record's content is "the octets of the value the response carried,
# and never a re-rendering of a parsed number", so a documented format carrying
# `19.2` as a JSON number would oblige this module to render a parsed float — the one
# thing that clause forbids. A provider stating its numbers as strings is a provider
# this system can transcribe verbatim.

#: The provider's documented request path.
_PROVIDER_PATH: Final = "/v1/forecast"

#: The parameters it documents. The coordinate is the ruled call's, read off the
#: revalidated copy; the day count is the forecaster's own bound, which ADR-0260 §3
#: makes "the forecaster's own bound, not a caller's". Asking for what will be minted
#: rather than taking a default page is what keeps the response small enough that
#: ``forecast_max_response_bytes`` stays a backstop rather than the ordinary outcome.
_PROVIDER_LATITUDE_PARAMETER: Final = "latitude"
_PROVIDER_LONGITUDE_PARAMETER: Final = "longitude"
_PROVIDER_DAYS_PARAMETER: Final = "days"

#: The field the account's credential rides in. Its *value* is supplied by the seam
#: and never by this module (ADR-0148 §7). **The reference provider accepts it and
#: does not use it** (ADR-0260 §12) — which is a fact about the far end and changes
#: nothing about this side: the credential is read under the slot the connection
#: record names, because ADR-0148 §6's third pre-transmit condition obliges it.
_PROVIDER_CREDENTIAL_FIELD: Final = "X-Forecast-Token"

#: The fields this integration wants beside the credential. Stated, so that a far end
#: content-negotiating its way to HTML is answering a request this seam did not make.
_PROVIDER_FIELDS: Final = (("Accept", "application/json"),)

#: Where the documented response carries its day list: ``{"days": [ … ]}``.
_PROVIDER_DAYS_KEY: Final = "days"

#: The day the row is about, as ``YYYY-MM-DD``, and the UTC offset that day is in, as
#: ``+HH:MM`` or ``-HH:MM`` (ADR-0260 §12: "dated days, each declaring the UTC offset
#: it is in"). **One spelling and no other**: ``Z``, a bare ``+HH`` and an offset with
#: seconds are values this documented format does not admit, and a row carrying one is
#: dropped rather than read under a rule the provider was not told to use. The pair is
#: what §5's extent is computed from, "and from nothing else — never from a clock of
#: ours, never from a timezone database of ours, never from the reader's configuration,
#: and never from the place".
_DATE_FIELD: Final = "date"
_OFFSET_FIELD: Final = "utc_offset"

#: The spans this adapter transcribes, in the fixed order §5 fixes them, joined by a
#: single newline with no other byte added. ``date`` is transcribed as well as read
#: for the extent, so a reader of the content can tell which day a record is about
#: without decoding an attestation; ``utc_offset`` is **not**, because the extent
#: already carries the position and a raw offset in prose is noise.
_TRANSCRIBED_FIELDS: Final = (
    _DATE_FIELD,
    "conditions",
    "temperature_min",
    "temperature_max",
    "precipitation",
)

#: Every field the documented format names for a day. **There is no omission rule**:
#: a row missing any of these, supplying one as ``null``, or supplying one as a type
#: this format does not admit is dropped whole (ADR-0260 §5).
_DOCUMENTED_FIELDS: Final = (_OFFSET_FIELD, *_TRANSCRIBED_FIELDS)

#: The one status a forecast is read out of. A ``2xx`` that is not ``200`` — a ``204``,
#: say — carries no representation, so it is a response no day can be read from rather
#: than a successful read of zero days; calling it the latter would report ``NO_RESULT``
#: where the honest answer is that the provider answered something else.
_PROVIDER_OK: Final = 200

#: The ASCII line breaks a day is dropped for carrying at any position in any
#: transcribed span. The line structure is the only thing keeping the spans apart, so a
#: break inside one would have to be altered — which would stop it being verbatim — or
#: would produce a record whose lines no reader can assign to a span.
_LINE_BREAKS: Final = frozenset("\n\r")

#: How long a documented date is, and how long a documented offset is.
_DATE_LENGTH: Final = 10
_OFFSET_LENGTH: Final = 6

#: ADR-0038 §2a's figure for an attested producer, which ADR-0260 §5 names for this
#: one.
_ATTESTED_CONFIDENCE: Final = 0.9

#: How long one day is. The extent's upper end is its lower end plus this, which is
#: the half-open interval ADR-0117 §2 asks for.
_ONE_DAY: Final = timedelta(days=1)


def _refused(refusal: ForecastRefusal) -> ForecastOutcome:
    """One refusal, carrying a class and nothing else (ADR-0260 §4).

    Args:
        refusal: The class.

    Returns:
        The outcome.
    """
    return ForecastOutcome(refusal=refusal)


def _provider_days(body: bytes) -> tuple[Mapping[str, FrozenJson], ...] | None:
    """The documented response's day list, or ``None`` where it is another shape.

    What the documented format admits, exactly: a UTF-8 JSON object, whose ``days``
    member — where it has one — is an array of objects.

    **An absent list is a response describing no day and not a refusal.** A provider
    with nothing to say for the coordinate omits the member, so reading that as a
    malformed shape would report a provider that answered perfectly well as one that
    answered something else — and the two are different operator facts. What is
    refused is a list of the wrong *type*, which no documented response carries.

    Args:
        body: The response's octets.

    Returns:
        The rows, in the order the provider returned them — possibly empty — or
        ``None`` where the response is not the documented shape.
    """
    decoded = decoded_object(body)
    if decoded is None:
        return None
    rows = decoded.get(_PROVIDER_DAYS_KEY)
    if rows is None:
        return ()
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return None
    return tuple(rows)


def _documented_text(row: Mapping[str, FrozenJson], field: str) -> str | None:
    """One documented field's value, or ``None`` where §5 drops the day for it.

    ADR-0260 §5's drop rule is **total over every value a well-formed response can
    carry in one of these positions**: omitted, ``null``, a string, or something else.
    The first three of those are one answer here and the fourth is the same answer,
    because this format admits no omission — "a day for which the provider omitted a
    documented field, supplied it as ``null``, or supplied a value of a type its
    documented format does not admit" is one clause and one outcome.

    Args:
        row: One day object.
        field: The provider's field name.

    Returns:
        The string, transcribed byte for byte and with its surrounding whitespace
        kept, or ``None`` where the day is dropped.
    """
    value = row.get(field)
    return value if isinstance(value, str) else None


def _declared_day(text: str) -> tuple[int, int, int] | None:
    """The ``YYYY-MM-DD`` the provider named, as a year, month and day.

    Written out rather than taken from :meth:`datetime.date.fromisoformat`, which
    since 3.11 also accepts ``YYYYMMDD`` and a week date: two spellings of one day
    would make the duplicate rule below compare unequal values that name the same day,
    which is exactly what ADR-0260 §5 drops a day *for*.

    Args:
        text: The value the ``date`` field carried.

    Returns:
        The triple, or ``None`` where the value is not this format's one spelling or
        names no day the calendar has.
    """
    if len(text) != _DATE_LENGTH or text[4] != "-" or text[7] != "-":
        return None
    fields = (text[0:4], text[5:7], text[8:10])
    if not all(field.isdigit() and field.isascii() for field in fields):
        return None
    year, month, day = (int(field) for field in fields)
    try:
        datetime(year, month, day, tzinfo=UTC)
    except ValueError:
        return None
    return year, month, day


def _declared_offset(text: str) -> timedelta | None:
    """The ``+HH:MM`` the provider declared for that day, as an offset from UTC.

    **This is the value ADR-0260 §5 makes the extent depend on, and there is no
    substitute**: "A day the provider named without declaring the offset it is in
    declares no extent", and that day is dropped rather than minted with an extent this
    system computed from a clock or a timezone database of its own.

    Args:
        text: The value the ``utc_offset`` field carried.

    Returns:
        The offset, or ``None`` where the value is not this format's one spelling or
        is not an offset :class:`datetime.timezone` admits.
    """
    if len(text) != _OFFSET_LENGTH or text[0] not in {"+", "-"} or text[3] != ":":
        return None
    fields = (text[1:3], text[4:6])
    if not all(field.isdigit() and field.isascii() for field in fields):
        return None
    hours, minutes = (int(field) for field in fields)
    magnitude = timedelta(hours=hours, minutes=minutes)
    offset = -magnitude if text[0] == "-" else magnitude
    try:
        timezone(offset)
    except ValueError:
        # `timezone` admits strictly between -24 and +24 hours; a well-formed
        # `+99:00` is a value no day is in.
        return None
    return offset


def _extent_of(day: tuple[int, int, int], offset: timedelta) -> ReportedExtent | None:
    """The half-open bounds of ``day`` in the zone ``offset`` names (ADR-0260 §5).

    **Computed from the day the provider named and the offset its own response
    declared for it, and from nothing else.** No clock of ours, no timezone database of
    ours, no reader configuration and no place contributes a value here.

    Args:
        day: The year, month and day the provider named.
        offset: The offset that day declared it is in.

    Returns:
        The extent, or ``None`` where the provider's own values would not make a
        constructible one — the fail-closed direction ADR-0252 §3 names, because an
        unbounded extent would cover every window where a declined one covers none.
    """
    year, month, number = day
    try:
        start = datetime(year, month, number, tzinfo=timezone(offset))
        return ReportedExtent(
            extends_from=start.astimezone(UTC), extends_until=(start + _ONE_DAY).astimezone(UTC)
        )
    except ValueError, OverflowError:
        # A day at the very edge of the representable range whose UTC conversion
        # overflows, and a `ReportedExtent` that would not be ordered. Both are days
        # this system declines to state a position for rather than states a wrong one.
        return None


@final
class _Day:
    """One day of a response that survived every clause of ADR-0260 §5 but the cap.

    A small value rather than a tuple, so that the duplicate pass below reads the day
    it is keying on by name.

    Attributes:
        named: The year, month and day the provider named, as the duplicate rule's
            key. Two rows naming one day are two rows about that day whatever else
            they carry.
        extent: The half-open bounds §5 computed for it.
        content: The transcription, verbatim.
    """

    __slots__ = ("content", "extent", "named")

    def __init__(
        self, *, named: tuple[int, int, int], extent: ReportedExtent, content: str
    ) -> None:
        """Hold one surviving day.

        Args:
            named: The day the provider named.
            extent: Its extent.
            content: Its transcription.
        """
        self.named = named
        self.extent = extent
        self.content = content


@final
class ForecastEgress:
    """Ask the configured forecast provider about the days ahead, and mint its answer.

    ADR-0260's ``Forecaster``. **Constructed in exactly one place, and only where a
    deployment configured a provider**:
    :func:`~ai_assistant.tools.builtin.build_forecast_integration`, the only site under
    ``src/ai_assistant``. A deployment that named no connection, no origin and no
    coordinate builds none and opens nothing.

    **It is registered at the egress seam and in no ``ToolRegistry``** (§1), so its
    declaration is absent from ``capabilities()`` and ``all_tools()``, no plan step can
    name it, and ``ToolInvoker`` cannot reach it. That is why the machinery
    ``ToolInvoker.invoke`` would have supplied is here instead, and why it is here in a
    stated order rather than in a convenient one:

    1. ADR-0241 §1's guard on the bound, **first** — before the revalidation, before any
       credential is read and before any channel is opened, so a value no deployment
       could pass reaches nothing.
    2. ADR-0029 §2's three, in its order (§6). The call is **revalidated and detached**,
       so a mutation landed after construction cannot survive into execution. The
       definition on that detached copy is compared for equality against **this
       forecaster's own registered declaration** — the authoritative original here,
       standing where ADR-0029 §2 puts the registry's, because §1 gives this integration
       an egress registration and no registry entry. And ``PermissionDecision.authorises``
       is **re-evaluated** against that same copy rather than trusted from construction,
       because ``ToolCall``'s own validator runs at construction and
       ``object.__setattr__`` defeats ``frozen=True``. Every subsequent step reads the
       revalidated copy and never the argument.
    3. Inside the deadline the **caller** stated: ADR-0148 §6's one-step credential read,
       its four pre-transmit conditions and its post-read discard, and **one** exchange
       — all of them :class:`~ai_assistant.tools.egress.HttpsEgressTransport`'s, at the
       seam ADR-0154 §1 designates. Then §5's transcription and minting, here.

    **No spend gate and no invocation ledger, and that is ADR-0260 §6 read rather than
    skipped.** That section enumerates what ``read`` performs and states that this seam
    "is likewise **not** ``ToolInvoker.invoke`` and inherits nothing written about
    ``WEB_SEARCH``"; neither ADR-0194 §3's admission nor ADR-0192's claim is named there,
    in §4's member contract, or in any of §13's fifteen arms, and ``ForecastRefusal``
    carries no ``SPEND_REFUSED`` member where ADR-0231 §17 gave ``SearchRefusal`` one.
    What the configured cost pair reaches is the **declaration** (ADR-0236 §1), which is
    what ADR-0236 §4's unknown-cost floor reads at the ruling — and §11 says exactly
    that.

    **Every source reason is returned and none is raised** (§4). What *does* leave
    :meth:`read` is a fault that no :class:`ForecastRefusal` member names: a ``timeout``
    outside its domain, a call that does not survive revalidation, one carrying a
    definition this forecaster did not register, one its decision does not authorise,
    one bound to another account or another origin, and a ``CancelledError`` the
    transport invented with nothing cancelled. Each is
    :class:`~ai_assistant.core.errors.ToolBindingError`,
    :class:`~ai_assistant.core.errors.ToolError`,
    :class:`~ai_assistant.tools.egress.TransportPinError` or a ``ValueError``, and a
    servicer degrades the turn on them exactly as ADR-0226 §5 requires it to degrade on
    anything else.

    **One ask is one read, and the count is this class's** (§3). Exactly one exchange is
    opened on every outcome read off the wire, and **none** on the ADR-0148 §6 refusal
    that reaches ``PROVIDER_REFUSED`` before any byte is transmitted. Nothing here
    retries, paginates, follows a link out of a response or re-issues with a different
    window, on any outcome.
    """

    __slots__ = (
        "_declaration",
        "_latitude",
        "_longitude",
        "_max_day_chars",
        "_max_days",
        "_name",
        "_transport",
    )

    def __init__(  # noqa: PLR0913 — the seam ADR-0260 §6 names, the place §3 makes this forecaster's own, the two bounds §11 adds, the declaration §6's second check compares against and the identity §5 attests to; each is one thing this forecaster is handed rather than reaches for
        self,
        *,
        transport: HttpsEgressTransport,
        latitude: float,
        longitude: float,
        max_days: int,
        max_day_chars: int,
        declaration: ToolDefinition = FORECAST_READ,
        name: str = FORECAST_SOURCE_NAME,
    ) -> None:
        """Bind a forecaster to the seam it acts through and the place it reads for.

        Args:
            transport: The egress seam this integration's requests leave through
                (ADR-0260 §6). It holds the registration, reads the credential and
                opens the channel; this object holds none of the three.
            latitude: ``Settings.forecast_latitude`` — the place this deployment reads
                its forecast for (§3, §11). Finite and from -90 to 90 inclusive.
            longitude: ``Settings.forecast_longitude``, likewise, from -180 to 180.
            max_days: ``Settings.forecast_max_days``. At least 1 and at most 3, §11's
                stated domain and §7's ceiling.
            max_day_chars: ``Settings.forecast_max_day_chars``. At least 1.
            declaration: This forecaster's **own registered declaration**, held by
                value and compared against for equality on every call — the untampered
                original ADR-0029 §2's second check needs and that no registry holds for
                this integration. Defaults to :data:`FORECAST_READ`, which is the one a
                composition root registers.
            name: The source instance every minted record is attested to (§5).
                Non-blank and unchanged by ``Identifier``'s own validation, checked here
                rather than at the first mint.

        **No deadline is held here** (ADR-0241 §3). The bound arrives on every
        :meth:`read` as the caller's own ``timeout``, and this class keeps no second
        copy of it: a forecaster holding one would be a forecaster able to disagree with
        its caller about the window it is running in. **And no place arrives per call**:
        the coordinate is held here, which is what ADR-0260 §3's "held by the forecaster
        as its own configuration" means and what makes a caller able to widen the read
        unconstructable rather than forbidden.

        Raises:
            ValueError: If ``name`` is blank or is a value ``Identifier`` would strip,
                if either bound is not an exact ``int`` or is outside ADR-0260 §11's
                domain for it, or if either coordinate is not a finite real number
                inside its own domain. Each is a state this forecaster could not act
                from, refused where it is configured rather than at an arbitrary later
                call.
        """
        if not name.strip() or name.strip() != name:
            msg = f"name must be non-blank and unchanged by Identifier's validation, got {name!r}"
            raise ValueError(msg)
        _checked_bound("max_days", max_days, ceiling=_MAX_FORECAST_DAYS)
        _checked_bound("max_day_chars", max_day_chars, ceiling=None)
        self._latitude = _checked_coordinate("latitude", latitude, maximum=_MAX_LATITUDE)
        self._longitude = _checked_coordinate("longitude", longitude, maximum=_MAX_LONGITUDE)
        self._transport = transport
        self._max_days = max_days
        self._max_day_chars = max_day_chars
        self._declaration = declaration
        self._name = name

    @property
    def name(self) -> str:
        """The source instance this forecaster serves (ADR-0260 §4, §5).

        Returns:
            The identity, the same string on every access and across every call: it is
            read off a slot written once at construction and by nothing since.
        """
        return self._name

    async def request(self) -> ActionRequest | None:
        """Propose the forecast read this deployment's configuration would make (§4).

        **Never ``None`` from this implementation**, and that is ADR-0260 §4's two
        clauses agreeing rather than disagreeing: ``app/composition.py`` constructs a
        forecaster only where a provider is configured, so a deployment that configured
        none holds no :class:`ForecastEgress` at all. The contract's ``None`` arm is what
        a ``Forecaster`` whose provider can be absent answers with, and the canonical
        fake is the implementation that exhibits it.

        **It reads no store, mints no identifier, opens no channel and reaches no
        authorisation conclusion** (§4, §6). The binding, the ruling, the audit record
        and the construction of the ``ToolCall`` are all the caller's.

        Returns:
            The request to rule on: this forecaster's declaration by value, exactly the
            origin and the configured coordinate as arguments, and ``None`` for
            ``step_id``, ``execution_id`` and ``egress_binding`` — a forecast decision
            has no plan step and no execution (§6), and the binding is derived by
            ``EgressBinder`` and accepted from nobody.
        """
        parameters: dict[str, FrozenJson] = {
            ORIGIN_ARGUMENT: self._transport.origin,
            LATITUDE_ARGUMENT: self._latitude,
            LONGITUDE_ARGUMENT: self._longitude,
        }
        return ActionRequest(tool=self._declaration, parameters=parameters)

    async def read(
        self,
        call: ToolCall,
        /,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1, §2); a caller wrapping this in `asyncio.timeout` cancels the forecaster mid-await and cannot classify its own expiry
    ) -> ForecastOutcome:
        """Perform the authorised forecast read, and mint what its answer describes.

        See the class docstring for the order and why it is the decision.

        Args:
            call: The authorised call. Read only through the revalidated copy this
                method makes of it, never as handed.
            timeout: The caller's bound on this call (ADR-0241 §1). Checked **first**,
                before the revalidation, before the credential read and before any
                channel — so a refused value reads nothing and opens nothing. The
                window it opens starts there too, so the revalidation is inside it.

        Returns:
            One outcome carrying records or a refusal.
            :attr:`~ai_assistant.core.types.ForecastRefusal.DEADLINE_EXPIRED` where
            **this** deadline fired (ADR-0241 §4). An interruption the transport
            **absorbed** is read off this frame's own deadline and its own task rather
            than off what came back, so a transport that catches the cancellation and
            answers anyway is not recorded as having succeeded.

        Raises:
            ValueError: If ``timeout`` is not a ``timedelta`` or is not strictly
                positive (ADR-0241 §1). Refused before anything is read.
            ToolBindingError: If the call does not survive ADR-0029 §2's three checks
                (§6). No credential is read and no channel is opened for any of them.
            ToolError: If the transport raised a ``CancelledError`` with **nothing
                cancelled** — ADR-0031 §2's invented cancellation, which ADR-0241 §7
                makes a fault rather than a teardown.
            CancelledError: Re-raised unchanged when this call is cancelled from
                outside while suspended, and converted into neither an outcome nor a
                refusal (ADR-0060 §1). Raised **freshly** where the transport absorbed
                one, because a cancellation answered with a value is the absorption
                ADR-0060 §1 says a method never performs.
        """
        # **First, and that is ADR-0241 §1's placement**: `checked_timeout` is
        # ADR-0029 §4's own guard — one implementation of the rule, reached from every
        # seam that states it — and it returns a plain `timedelta` rebuilt from the
        # base class's fields, so a subclass whose `total_seconds` raises decides
        # nothing later.
        duration = checked_timeout(timeout)
        entered_with = pending_cancellations()
        # **The window opens ahead of the revalidation** (ADR-0241 §1): the bound
        # covers the seam's own work, and a clock started after the checks would hand
        # the exchange a *fresh* budget.
        deadline = asyncio.timeout(duration.total_seconds())
        try:
            async with deadline:
                binding, origin, latitude, longitude = self._authorised(call)
                answered = await self._asked(
                    binding, origin=origin, latitude=latitude, longitude=longitude
                )
        except asyncio.CancelledError as cancellation:
            if pending_cancellations() > entered_with:
                # An external cancellation: delivered onward unchanged (ADR-0060 §1).
                raise
            # ADR-0031 §2's invented cancellation — the count did not move, so nothing
            # was cancelled and this is a fault the transport raised. ADR-0241 §7 says
            # what it must *not* become: not a teardown that ends the turn, and not an
            # outcome. So it leaves as an `AssistantError`, which is what reaches
            # ADR-0226 §5's degradation.
            msg = (
                f"{self._declaration.id}: the forecaster raised a cancellation with "
                f"nothing cancelled, so the read did not complete"
            )
            raise ToolError(msg) from cancellation
        except TimeoutError:
            # **Classification keys on whether *this* deadline fired, never on the
            # exception's type** (ADR-0241 §7). `Timeout.expired()` is the seam's own
            # state and no callable can reset it; a `TimeoutError` an upstream library
            # raised for its own reasons leaves it `False`, and that is the transport's
            # failure rather than this seam's expiry.
            #
            # **And an external cancellation outranks both classes.** A transport that
            # catches the task's own cancellation and raises a `TimeoutError` instead
            # arrives here with the count still moved, and answering it with a refusal
            # would be the absorption ADR-0060 §1 says a method never performs.
            self._deliver_absorbed(entered_with)
            return _refused(
                ForecastRefusal.DEADLINE_EXPIRED
                if deadline.expired()
                else ForecastRefusal.TRANSPORT_FAILED
            )
        except Exception:
            # **A fault the transport raised is still not evidence that nothing was
            # cancelled.** A connection reader that catches this task's
            # `CancelledError` and raises `ConnectionStoreError` instead leaves the
            # frame holding an ordinary exception, and letting it out would degrade the
            # turn under ADR-0226 §5 while the cancellation the executor asked for was
            # never delivered. `BaseException` is deliberately not caught: a process
            # being torn down is not an interruption of this call.
            self._deliver_absorbed(entered_with)
            if not deadline.expired():
                # Nothing was cancelled and this window did not close, so the fault is
                # the whole of what happened and it leaves exactly as it arrived —
                # unwrapped, unannotated and with no outcome invented for it.
                raise
            # **This deadline having fired outranks the fault.** The `Timeout` context
            # calls `uncancel` on its way out whatever the exception was, so a
            # collaborator that catches the expiry's cancellation and raises a store
            # fault instead leaves no trace in the count — but `Timeout.expired()` is
            # this seam's own state and no callable can reset it.
            return _refused(ForecastRefusal.DEADLINE_EXPIRED)
        else:
            # **The state is read from the task and the deadline rather than inferred
            # from what came back** (ADR-0029 §4). Nothing forces a transport to let an
            # interruption through: one that catches this deadline's cancellation and
            # returns a channel leaves the frame holding an answer and no exception,
            # and trusting that return would report a read that outran its bound as one
            # that did not.
            self._deliver_absorbed(entered_with)
            if deadline.expired():
                return _refused(ForecastRefusal.DEADLINE_EXPIRED)
            return answered

    def _deliver_absorbed(self, entered_with: int) -> None:
        """Deliver an interruption a collaborator swallowed, before anything else.

        **A pending external cancellation outranks every classification this seam could
        make**, on every exit — an exception a collaborator raised as well as a value it
        returned. ADR-0029 §4 keeps that on the executor and ADR-0060 §1 says a method
        never absorbs one, so a transport that catches the cancellation and then raises
        a ``TimeoutError``, and a connection reader that replaces it with a store fault,
        are the same case: the object that came back says nothing about whether this
        turn was cancelled.

        **The count and not the class** (ADR-0031 §2): it is a lifetime figure only
        ``uncancel`` lowers, so a collaborator that catches the exception cannot lower
        it, and reading it as a *delta* from a baseline taken on entry is what keeps a
        caller's earlier, unrelated cancellation from failing this call.

        Freshly raised rather than re-raised: the original was consumed inside the
        collaborator, and what matters is that the cancellation reaches the executor
        rather than being answered with a result.

        Args:
            entered_with: The count sampled before the work this is guarding.

        Raises:
            CancelledError: If a cancellation of the invoking task is still pending.
        """
        if pending_cancellations() > entered_with:
            swallowed = (
                f"{self._declaration.id}: the forecaster absorbed the cancellation of "
                f"its invoking task"
            )
            raise asyncio.CancelledError(swallowed)

    def _authorised(self, call: ToolCall) -> tuple[EgressBinding, str, float, float]:
        """Run ADR-0029 §2's three checks, and hand back what survived them (§6).

        **Inside the caller's window and before anything else** (ADR-0241 §1): the call
        is revalidated and detached, its definition is compared for equality against this
        forecaster's **own registered declaration** — the authoritative original here,
        standing where ADR-0029 §2 puts the registry's — and
        ``PermissionDecision.authorises`` is re-evaluated against that same copy. Every
        later step reads what this returns and never the argument.

        Synchronous throughout, which is what makes the ordering a fact rather than a
        convention: there is no ``await`` here for a reprovisioning, a cancellation or a
        second caller to be delivered at, so nothing observed by these checks can move
        between them and the send.

        Args:
            call: The call as handed, read only through the copy this makes of it.

        Returns:
            Its binding and the three arguments its schema declares — each already
            narrowed, so no later frame carries a ``cast``.

        Raises:
            ToolBindingError: If the call does not survive revalidation, carries a
                definition unequal to this forecaster's registered original, is not
                authorised by its decision, or carries no egress binding. **No
                credential is read and no channel is opened for any of them.**
        """
        checked = revalidated_call(call)
        if checked.request.tool != self._declaration:
            msg = (
                f"{self._declaration.id}: the definition carried by this call is not the "
                f"one this forecaster registered, so the thing about to run is not the "
                f"thing declared (ADR-0029 §2, ADR-0260 §6)"
            )
            raise ToolBindingError(msg)
        if not checked.decision.authorises(checked.request):
            msg = (
                f"{self._declaration.id}: decision {checked.decision.id!r} does not "
                f"authorise this request, so the thing about to run is not the thing "
                f"that was authorised (ADR-0029 §2, ADR-0260 §6)"
            )
            raise ToolBindingError(msg)
        binding = checked.request.egress_binding
        origin = checked.request.parameters.get(ORIGIN_ARGUMENT)
        latitude = _real(checked.request.parameters.get(LATITUDE_ARGUMENT))
        longitude = _real(checked.request.parameters.get(LONGITUDE_ARGUMENT))
        if binding is None or not isinstance(origin, str) or latitude is None or longitude is None:
            # The schema refuses a call carrying anything but the string and the two
            # numbers, and revalidation re-ran it; ADR-0148 §8's third floor refuses an
            # `ALLOW` with no binding. So this is unreachable through the seam that
            # builds one — and it is checked anyway, because what would otherwise stand
            # here is a `cast`, and the value it would assert about is the recipient.
            msg = (
                f"{self._declaration.id}: this call carries no egress binding, or its "
                f"arguments are not the origin and the coordinate its schema declares, "
                f"so there is no authorised request to make (ADR-0148 §8, ADR-0260 §6)"
            )
            raise ToolBindingError(msg)
        return binding, origin, latitude, longitude

    async def _asked(
        self, binding: EgressBinding, *, origin: str, latitude: float, longitude: float
    ) -> ForecastOutcome:
        """Make the **one** request through the seam, and read the answer under §5.

        Args:
            binding: The authorised binding, handed to the seam whole and never
                re-derived (ADR-0148 §4).
            origin: The origin the ruled call carries, which the seam compares against
                its registration before it reads anything.
            latitude: The latitude the ruled call carries.
            longitude: The longitude it carries.

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
            f"?{_PROVIDER_LATITUDE_PARAMETER}={_decimal(latitude)}"
            f"&{_PROVIDER_LONGITUDE_PARAMETER}={_decimal(longitude)}"
            f"&{_PROVIDER_DAYS_PARAMETER}={self._max_days}"
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
            return _refused(ForecastRefusal.RESPONSE_TOO_LARGE)
        except BoundCallChangedError:
            # ADR-0148 §6's four pre-transmit conditions, whose refusal ADR-0260 §6
            # names: a reference that is not connectable, a record recorded for another
            # identity, one that moved across the credential read, a slot the keyring
            # holds nothing under, and a credential no request field will carry. Every
            # one of them discarded the credential and wrote nothing to any channel —
            # **none was opened**, which is why §13(i)'s count for this outcome is zero.
            return _refused(ForecastRefusal.PROVIDER_REFUSED)
        except HttpsRedirectRefusedError, MalformedHttpResponseError, TransportError:
            # Statements about this system's own reach or about the far end's HTTP
            # framing rather than about what the provider said: a redirect it will not
            # follow — and §3 makes one a refusal and never a second request — a
            # response that is not HTTP/1.1, a channel it could not open, verify or
            # continue. What the provider *said* is `PROVIDER_REFUSED`.
            return _refused(ForecastRefusal.TRANSPORT_FAILED)
        return self._read(response)

    def _read(self, response: HttpsResponse) -> ForecastOutcome:
        """Read one documented response into records, or into the class that refuses it.

        The order is ADR-0260 §5's own: the response's **shape** is decided first, and
        only then its declared instant, which §5 states after the transcription rule.

        Args:
            response: What the seam read off the channel, under its bound.

        Returns:
            The outcome.
        """
        if response.status != _PROVIDER_OK:
            return _refused(ForecastRefusal.PROVIDER_REFUSED)
        rows = _provider_days(response.body)
        if rows is None:
            return _refused(ForecastRefusal.PROVIDER_REFUSED)
        reported_at = declared_instant(response.headers)
        if reported_at is None:
            # ADR-0260 §5, ADR-0092 §3: "A response declaring **no** instant, or
            # carrying in that position a value that cannot be read as one, mints **no
            # record**". There is no substitute, and none is reached for.
            _log.info("forecast_response_declared_no_instant", tool_id=self._declaration.id)
            return _refused(ForecastRefusal.UNATTESTED)
        return self._minted(rows, reported_at=reported_at)

    def _minted(
        self, rows: Sequence[Mapping[str, FrozenJson]], *, reported_at: datetime
    ) -> ForecastOutcome:
        """Apply §5's drop rules and mint one record per surviving day.

        **The order of the clauses is the decision** (ADR-0260 §5, §13(b-prime)):

        1. Each row is read into a day or dropped — an omitted, ``null`` or ill-typed
           documented field, an undeclared or unreadable offset, a date this format
           does not spell, a transcribed span carrying a line break, an extent the
           provider's values would not make, and a transcription over
           ``forecast_max_day_chars`` all end here.
        2. **Every row of a day the response named more than once is dropped**, over
           the whole response and **before** the cap. §13(b-prime) requires exactly this
           ordering and says why: "an implementation capping before it looks for
           duplicates mints the first row and passes every arm that keeps the duplicate
           inside the cap". It is not a deduplication — nothing is merged and no row is
           preferred — because the response has not described that day *once*.
        3. **The cap is taken over the survivors and taken from the front** (§5),
           because a cap that did not say which days it kept would let two
           implementations mint different evidence, and different goal outcomes, from
           one response.

        Args:
            rows: The documented response's day rows, in order.
            reported_at: The instant the response declared.

        Returns:
            The outcome: the records, or ``NO_RESULT`` where the response described no
            day and where §5 dropped every one it did.
        """
        read = [self._day_of(row) for row in rows]
        named = [day.named for day in read if day is not None]
        once = {day for day in named if named.count(day) == 1}
        kept = [day for day in read if day is not None and day.named in once]
        minted = tuple(self._record(day, reported_at) for day in kept[: self._max_days])
        if not minted:
            return _refused(ForecastRefusal.NO_RESULT)
        return ForecastOutcome(reported_at=reported_at, records=minted)

    def _day_of(self, row: Mapping[str, FrozenJson]) -> _Day | None:
        """One row read into a day, or ``None`` where ADR-0260 §5 drops it whole.

        Args:
            row: One day object from the documented response.

        Returns:
            The day, or ``None``.
        """
        values = {field: _documented_text(row, field) for field in _DOCUMENTED_FIELDS}
        if any(value is None for value in values.values()):
            return None
        present = {field: value for field, value in values.items() if value is not None}
        if any(
            character in _LINE_BREAKS
            for field in _TRANSCRIBED_FIELDS
            for character in present[field]
        ):
            return None
        named = _declared_day(present[_DATE_FIELD])
        offset = _declared_offset(present[_OFFSET_FIELD])
        if named is None or offset is None:
            return None
        extent = _extent_of(named, offset)
        if extent is None:
            return None
        content = "\n".join(present[field] for field in _TRANSCRIBED_FIELDS)
        if len(json.dumps(content)) > self._max_day_chars:
            # Measured as ADR-0230 §6 measures a fetched document — on the `json.dumps`
            # rendering at its default `ensure_ascii=True`, its two delimiters included,
            # which is the rendering the prompt will carry. A ceiling on source
            # characters would admit a day six or twelve times this long while claiming
            # to admit this much (ADR-0222 §4).
            return None
        return _Day(named=named, extent=extent, content=content)

    def _record(self, day: _Day, reported_at: datetime) -> MemoryRecord:
        """One ``SEMANTIC``, ``EXTERNAL``-sourced record carrying one day (§5).

        **No model is on this path**: nothing summarises, abridges, rewrites, re-ranks,
        annotates, deduplicates, interprets or classifies a value between the provider's
        response and this record.

        ``reported_by`` is this forecaster's own identity — the **source instance**, and
        never a vendor, an origin, a URL, a credential or a place (ADR-0092 §3). What is
        attested is *the provider's claim about what its forecast says for that day*,
        and the record makes **no claim that the weather will be so**.

        **``validity`` is fully open** and is never set to the day the record is about
        (§5): ADR-0045 §2 makes the envelope window an operational property, and
        ADR-0252 §3 forbids reading it as coverage on any kind. The day is carried by
        the ``Attestation``'s extent, which is the axis ADR-0117 §2 gives producer
        testimony.

        Args:
            day: The surviving day, with its extent and its transcription.
            reported_at: The instant the response declared.

        Returns:
            The record. Its id is minted here and is opaque to the source (ADR-0092 §6);
            it is rendered to no model, accepted from none, and — since ADR-0260 §11
            stores nothing — never installed.
        """
        return SemanticMemory(
            id=uuid4().hex,
            content=day.content,
            fact=day.content,
            provenance=Provenance(
                source=MemorySource.EXTERNAL,
                confidence=_ATTESTED_CONFIDENCE,
                evidence=(),
                last_updated=reported_at,
                last_confirmed_at=reported_at,
                attestation=Attestation(
                    reported_by=self._name,
                    reported_at=reported_at,
                    extent=day.extent,
                ),
                # Asserts nothing in this band (ADR-0106 §1). The externality this
                # record carries is `MemorySource.EXTERNAL`, which `band_of` places in
                # `ATTESTED`; this field is the `DERIVED` band's question.
                derived_from_external=False,
            ),
            topics=(),
            about_person=None,
        )


def _checked_bound(label: str, value: int, *, ceiling: int | None) -> None:
    """Refuse a bound outside ADR-0260 §11's stated domain for it.

    Args:
        label: The field's name, for the message.
        value: What was passed.
        ceiling: The domain's upper end, or ``None`` where it has none.

    Raises:
        ValueError: If ``value`` is not an exact ``int``, is below 1, or is above
            ``ceiling``. An **exact** ``int`` and not an ``isinstance`` match:
            ``True`` is an ``int`` by ``isinstance`` and would otherwise configure a
            bound of one while satisfying the range.
    """
    if type(value) is not int:
        msg = f"{label} is an exact int; got {value!r}"
        raise ValueError(msg)
    if value < 1:
        msg = f"{label} is an integer of at least 1; got {value}"
        raise ValueError(msg)
    if ceiling is not None and value > ceiling:
        msg = f"{label} is an integer of at most {ceiling} (ADR-0260 §11); got {value}"
        raise ValueError(msg)


def _checked_coordinate(label: str, value: float, *, maximum: float) -> float:
    """Refuse a coordinate outside ADR-0260 §11's stated domain for it.

    **This restates ``Settings``' domain at the one place a forecaster can be built
    without going through it**, which is the posture ADR-0236 §2 takes one field pair
    over: a value that is not a place would compose a request no provider documents an
    answer for, and refusing it where the forecaster is configured is better than
    raising out of :meth:`ForecastEgress.read` at an arbitrary later call.

    Args:
        label: The field's name, for the message.
        value: What was passed.
        maximum: The degrees this axis runs to, which is also its negative floor.

    Returns:
        The value as a plain ``float``.

    Raises:
        ValueError: If ``value`` is not a real number, is not finite, or is outside
            ``[-maximum, maximum]``. A ``bool`` is refused by name: it is an ``int`` by
            ``isinstance`` and would otherwise configure a place one degree north of
            the equator while satisfying the range.
    """
    real = _real(value)
    if real is None:
        msg = f"{label} is a finite real number; got {value!r}"
        raise ValueError(msg)
    if not math.isfinite(real):
        msg = f"{label} is finite; got {value!r}"
        raise ValueError(msg)
    if not -maximum <= real <= maximum:
        msg = f"{label} is from {-maximum} to {maximum} (ADR-0260 §11); got {value!r}"
        raise ValueError(msg)
    return real


def _real(value: object) -> float | None:
    """``value`` as a plain ``float``, or ``None`` where it is not a real number.

    An exact ``int`` is admitted because a whole number of degrees is how an operator
    writes one, and a ``float`` subclass is normalised to a plain ``float`` so that
    nothing downstream reads an overridden comparison. A ``bool`` is refused: it is an
    ``int`` by ``isinstance`` and means a flag rather than a measurement.

    Args:
        value: The value to read.

    Returns:
        The number, or ``None``.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, float) or type(value) is int:
        return float(value)
    return None


def _decimal(value: float) -> str:
    """``value`` as a decimal this seam will write into a request target.

    ``repr`` rather than ``str(round(...))``: it is the shortest spelling that reads
    back as the same float, so the provider is asked about the coordinate the ruling
    carried rather than about a rounded neighbour of it. Every character it can produce
    for a finite float — digits, ``-``, ``.``, ``e``, ``+`` — is either RFC 3986 §2.3
    unreserved or, for ``+``, a sub-delim a query component admits; the exchange's own
    origin-form check is the authority and refuses rather than encodes.

    Args:
        value: The coordinate, already known finite by
            :func:`_checked_coordinate` at construction and by the schema at the
            ruling.

    Returns:
        Its decimal spelling.
    """
    return repr(value)


__all__ = [
    "FORECAST_READ",
    "FORECAST_READ_ID",
    "FORECAST_SOURCE_NAME",
    "LATITUDE_ARGUMENT",
    "LONGITUDE_ARGUMENT",
    "ORIGIN_ARGUMENT",
    "ForecastEgress",
]
