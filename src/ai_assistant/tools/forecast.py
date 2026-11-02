"""The forecast integration: its declaration, its provider adapter, and its forecaster.

:mod:`ai_assistant.tools.web_search`'s counterpart for ADR-0260's kind, and it carries
the same division. This module holds the **declaration**, the request shape and the
response shape ADR-0260 §6 puts "inside ``ai_assistant.tools``", and the
:class:`~ai_assistant.core.protocols.Forecaster` that drives the whole of §6's order;
:mod:`ai_assistant.tools.egress` — the module ADR-0154 §1 designates and where §6 rules
a forecast request leaves from — holds
:class:`~ai_assistant.tools.egress.HttpsEgressTransport`, which is the thing that reads
the connection record and opens a channel to the world. **Nothing here reads a secret,
holds a ``Secrets`` face or constructs a transport**, and the forecast reads no secret
anywhere: its transport is **keyless** (ADR-0344 §2:3, ADR-0325 §2:1), built with no
``Secrets`` face, so there is no credential for this module or the seam to hold.

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
rendered to no model and accepted from none, and a planner cannot name it — so the
failure mode ADR-0231 §1 is built against is unreachable rather than forbidden.

**The provider is Open-Meteo, and its documented format is the only one read here**
(ADR-0344 §2:1). The request is ADR-0344 §4's — ``GET /v1/forecast`` with the
coordinate, a fixed set of daily variables, ``timezone=auto`` and the forecaster's own
horizon, and nothing else — and the response is read under §5's table, row by row. No
setting selects the provider, its format or its connection shape (§2:4): the format is
the constants and functions below, and the keyless shape is fixed where
:func:`~ai_assistant.tools.builtin.build_forecast_integration` constructs the transport
(ADR-0325 §2:2).
"""

from __future__ import annotations

import asyncio
import json
import math
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

import structlog

from ai_assistant.core.errors import ToolBindingError, ToolError, TransportError
from ai_assistant.core.types import (
    ActionRequest,
    Attestation,
    CapabilityEffect,
    CapabilityResult,
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
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
    describe_untrusted,
)
from ai_assistant.tools.consume import consumed_call, pending_cancellations
from ai_assistant.tools.egress import (
    BoundCallChangedError,
    HttpsRedirectRefusedError,
    HttpsResponseTooLargeError,
    MalformedHttpResponseError,
)
from ai_assistant.tools.egress_declaration import DESTINATION_KEYWORD, TIER_KEYWORD
from ai_assistant.tools.http_reading import declared_instant, decoded_object
from ai_assistant.tools.invocation import expiry_failure
from ai_assistant.tools.registry import checked_timeout, revalidated_call

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.protocols import InvocationLedger
    from ai_assistant.core.types import EgressBinding, FrozenJson, ToolCall
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


#: The capability, ``read_forecast`` (ADR-0364 §8:1), renamed from ``forecast_read`` with
#: every other field of its declaration kept, its id among them.
FORECAST_READ_CAPABILITY: Final = "read_forecast"

FORECAST_READ: Final = ToolDefinition(
    id=FORECAST_READ_ID,
    capability=FORECAST_READ_CAPABILITY,
    description=(
        "Read the forecast for the next few days at a place.\n"
        "\n"
        "Give the coordinates of a place that was named, such as a city, both or neither; left "
        "out, it reads the system's configured place.\n"
        "\n"
        "outcome: done | not done | unknown | refused\n"
        "because: why, with not done, unknown or refused\n"
        "result: with done, under its R label, read for you\n"
        "evidence: what was read of the forecast for looking_for, each item marked outside\n"
        "\n"
        "It changes nothing, but what it sends leaves the system."
    ),
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.REVERSIBLE,
    side_effecting=True,
    reads=(),
    writes=(),
    discloses=(DataTier.PERSONAL,),
    cost=ToolCost(basis=CostBasis.UNKNOWN),
    idempotency=Idempotency.NONE,
    effect=CapabilityEffect.NONE,
    leaves_hub=True,
    result=CapabilityResult.MAY_CARRY_OUTSIDE_TEXT,
    outcome_can_be_unknown=True,
    safe_to_repeat=True,
    parameters_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            ORIGIN_ARGUMENT: _origin(),
            LATITUDE_ARGUMENT: {
                **_coordinate(maximum=_MAX_LATITUDE),
                "description": (
                    "The place's latitude, in degrees. Left out: the configured place's."
                ),
            },
            LONGITUDE_ARGUMENT: {
                **_coordinate(maximum=_MAX_LONGITUDE),
                "description": (
                    "The place's longitude, in degrees. Left out: the configured place's."
                ),
            },
        },
        "required": [ORIGIN_ARGUMENT],
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
- ``reads=()`` (ADR-0344 §3:7). The callable is keyless: its transport holds no
  ``Secrets`` face, reads no credential and refuses a connection record that names a
  slot (ADR-0325 §2:1, §2:3), so it reads no Tier 0 value — and ADR-0016 §1 makes every
  field of a declaration a claim, so naming ``SECRET`` here would claim a read no call
  performs.
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
# Open-Meteo's documented format (ADR-0344 §4, §5), chosen inside `tools/`.
# --------------------------------------------------------------------------- #
# ADR-0260 §5 leaves the transcription's form to the implementation and says so in
# terms: "**The form is the provider's, and each implementation pins its own**: the
# field selection, their order, the separators and the omission rule are fixed by the
# implementation that reads that provider's documented format, and are pinned by a
# test of its own." ADR-0344 §4 fixes the request and §5 the reading of the response,
# row by row; the constants below are that decision as code, and the origin is the
# only part of the request a deployment configures.
#
# **Open-Meteo carries its values as JSON numbers, and that forces nothing.** §5:2
# asks for "the octets of the value the response carried, and never a re-rendering of
# a parsed number", and a decoder can keep each number token as the text the response
# carried (ADR-0344 §5:9): :func:`_tokens` hands the decoder hooks that wrap the token's
# own text and never build a ``float``.

#: The provider's documented request path (ADR-0344 §4:1).
_PROVIDER_PATH: Final = "/v1/forecast"

#: The five query parameters §4:1 admits, in the order the target carries them, and
#: no other. The coordinate is the ruled call's, read off the revalidated copy (§4:2);
#: the daily set, the zone and the horizon are constants of this forecaster (§4:3 to §4:5),
#: which is why no ruling ranges over them and none needs to.
_PROVIDER_LATITUDE_PARAMETER: Final = "latitude"
_PROVIDER_LONGITUDE_PARAMETER: Final = "longitude"
_PROVIDER_DAILY_PARAMETER: Final = "daily"
_PROVIDER_TIMEZONE_PARAMETER: Final = "timezone"
_PROVIDER_DAYS_PARAMETER: Final = "forecast_days"

#: ``timezone=auto`` (§4:4): the provider resolves the zone from the coordinate, and the
#: hub sends no zone of its own — not ``Settings.timezone``, which no ruling ranges over.
_PROVIDER_TIMEZONE: Final = "auto"

#: The daily variables asked for, in the order §4:3 names them and the order every
#: record transcribes them (§5:5). A constant of this code, pinned by a test, and
#: widened or narrowed by no ``Settings`` value, caller or response.
_DAILY_VARIABLES: Final = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "wind_speed_10m_max",
)

#: The one field this integration adds to the request (§4:6). Stated, so that a far end
#: content-negotiating its way to HTML is answering a request this seam did not make.
#: **There is no credential field**: the transport is keyless (§2:3), and
#: :meth:`~ai_assistant.tools.egress.HttpsEgressTransport.fetch` is handed ``None`` for
#: it, which a credentialed transport would refuse.
_PROVIDER_FIELDS: Final = (("Accept", "application/json"),)

#: The response members §5's table reads, and no other (§5:6). ``daily`` is the table,
#: ``time`` its day column, ``daily_units`` each variable's unit, and
#: ``utc_offset_seconds`` the one offset every day of the response is in (§5:4).
_DAILY_KEY: Final = "daily"
_TIME_KEY: Final = "time"
_UNITS_KEY: Final = "daily_units"
_OFFSET_KEY: Final = "utc_offset_seconds"

#: The magnitude at which an offset stops being one a day can be in (§5's row 7):
#: ``datetime.timezone`` admits strictly less than a day either way.
_OFFSET_CEILING_SECONDS: Final = 86_400

#: The one status a forecast is read out of (§5's row 2). A ``2xx`` that is not ``200``
#: — a ``204``, say — carries no representation, so it is a response no day can be read
#: from rather than a successful read of zero days; calling it the latter would report
#: ``NO_RESULT`` where the honest answer is that the provider answered something else.
#: Open-Meteo's own error object arrives under ``400``, and a ``429`` is its rate limit:
#: both are the provider's answer and both are ``PROVIDER_REFUSED``.
_PROVIDER_OK: Final = 200

#: The transcription's fixed separators (§5:5): one line per transcribed member, the
#: provider's field name and its value joined by ``": "``, and a variable's token and
#: its unit joined by a single space. **Pinned by a test**, and no byte of this system's
#: is added beyond them.
_LINE_SEPARATOR: Final = "\n"
_NAME_SEPARATOR: Final = ": "
_UNIT_SEPARATOR: Final = " "

#: The ASCII line breaks a transcription is refused for carrying inside a span. The line
#: structure is the only thing keeping the spans apart, so a break inside one would have
#: to be altered — which would stop it being verbatim — or would produce a record whose
#: lines no reader can assign to a span. Only a unit can carry one: a field name is a
#: constant here, a token is a JSON number and a date is checked against ``YYYY-MM-DD``.
_LINE_BREAKS: Final = frozenset("\n\r")

#: How long a documented date is.
_DATE_LENGTH: Final = 10

#: ADR-0038 §2a's figure for an attested producer, which ADR-0260 §5 names for this
#: one.
_ATTESTED_CONFIDENCE: Final = 0.9

#: How long one day is. The extent's upper end is its lower end plus this, which is
#: the half-open interval ADR-0117 §2 asks for — and a **fixed** 24 hours across a DST
#: change too, because Open-Meteo aggregates each day over boundaries set by the one
#: offset and ignores DST changes inside the range (ADR-0344 §5, "Why the extent is a
#: fixed 24 hours").
_ONE_DAY: Final = timedelta(days=1)


def _refused(refusal: ForecastRefusal) -> ForecastOutcome:
    """One refusal, carrying a class and nothing else (ADR-0260 §4).

    Args:
        refusal: The class.

    Returns:
        The outcome.
    """
    return ForecastOutcome(refusal=refusal)


@final
class _Token:
    """One JSON number token, as the text the response spelled it (ADR-0344 §5:2).

    What the decoder hands back in place of an ``int`` or a ``float``, so that no
    transcribed value is ever parsed to a number or re-rendered on the way to a record:
    ``17.20`` stays ``17.20`` and ``1e1`` stays ``1e1``.

    Attributes:
        text: The token's characters, exactly as the response carried them.
        integral: Whether the token is an integer token — no fraction and no exponent —
            which is the one thing §5's row 7 asks of ``utc_offset_seconds``.
    """

    __slots__ = ("integral", "text")

    def __init__(self, text: str, *, integral: bool) -> None:
        """Hold one token.

        Args:
            text: The token's characters.
            integral: Whether the decoder read it as an integer token.
        """
        self.text = text
        self.integral = integral


def _integer_token(text: str) -> _Token:
    """The decoder's ``parse_int`` hook: an integer token, kept as spelled.

    Args:
        text: The token's characters.

    Returns:
        The token.
    """
    return _Token(text, integral=True)


def _fraction_token(text: str) -> _Token:
    """The decoder's ``parse_float`` hook: a token with a fraction or an exponent.

    Args:
        text: The token's characters, ``17.20`` and ``1e1`` alike.

    Returns:
        The token.
    """
    return _Token(text, integral=False)


def _no_constant(token: str) -> object:
    """The decoder's ``parse_constant`` hook: ``NaN`` and the infinities are not JSON.

    :func:`~ai_assistant.tools.http_reading.decoded_object` has already refused a body
    carrying one, so this is the guard behind that guard rather than a reachable branch.

    Args:
        token: The constant the decoder met.

    Returns:
        Nothing: this function always raises.

    Raises:
        ValueError: Always, which :func:`_tokens` answers with ``None``.
    """
    msg = f"{token!r} is not a JSON value (RFC 8259)"
    raise ValueError(msg)


def _tokens(body: bytes) -> dict[str, object] | None:
    """The body as a JSON object whose numbers are tokens, or ``None`` (§5's row 3).

    **Row 3 is judged by** :func:`~ai_assistant.tools.http_reading.decoded_object`,
    exactly as the table words it — "a body that is not a UTF-8 JSON object, as
    ``decoded_object`` reads one" — so the depth bound, the refusal of ``NaN`` and the
    UTF-8 rule are that function's and not a second copy of them. Only a body it admits
    is decoded again, with hooks that keep each number token as its text (§5:2), so the
    second decode is of a body already known to be one well-formed object.

    Args:
        body: The response's octets.

    Returns:
        The object, its numbers :class:`_Token` values, or ``None`` where row 3 holds.
    """
    if decoded_object(body) is None:
        return None
    try:
        decoded: object = json.loads(
            body.decode("utf-8"),
            parse_int=_integer_token,
            parse_float=_fraction_token,
            parse_constant=_no_constant,
        )
    except ValueError:  # pragma: no cover — `decoded_object` above admitted these octets
        return None
    return decoded if isinstance(decoded, dict) else None


def _table_admitted(decoded: Mapping[str, object]) -> bool:
    """Whether §5's row 4 leaves the response readable as a table of days.

    Row 4 refuses the response where ``daily`` is present and not an object, where
    ``daily.time`` is present and not an array, and where a requested variable's member
    is present and not an array or not of ``daily.time``'s length: the response then
    does not say which value belongs to which day, and pairing them by position would
    be this system deciding what the provider said (ADR-0344 §5, "Why a missing array
    drops days and a short one refuses the response").

    **Membership, not retrieval**, throughout: an absent member is row 6's or row 8's
    case, and a member present as ``null`` is a value the format does not admit, which
    ``dict.get`` cannot tell apart.

    Args:
        decoded: The decoded body.

    Returns:
        ``False`` where row 4 holds, ``True`` otherwise.
    """
    if _DAILY_KEY not in decoded:
        return True
    daily = decoded[_DAILY_KEY]
    if not isinstance(daily, dict):
        return False
    times = daily.get(_TIME_KEY)
    if _TIME_KEY in daily and not isinstance(times, list):
        return False
    for variable in _DAILY_VARIABLES:
        if variable not in daily:
            continue
        column = daily[variable]
        if not isinstance(column, list):
            return False
        if isinstance(times, list) and len(column) != len(times):
            return False
    return True


def _declared_offset(value: object) -> timedelta | None:
    """The one offset every day of the response is in, or ``None`` (§5's row 7).

    **This is the value ADR-0260 §5 makes the extent depend on, and there is no
    substitute**: an absent ``utc_offset_seconds``, one that is not an integer token,
    and one of a magnitude of a day or more each leave every day declaring no offset,
    and every day is dropped rather than minted with an extent this system computed from
    a clock or a timezone database of its own (ADR-0260 §5:8).

    Args:
        value: The member as decoded, or ``None`` where it is absent.

    Returns:
        The offset, or ``None``.
    """
    if not isinstance(value, _Token) or not value.integral:
        return None
    digits = value.text.removeprefix("-")
    if len(digits) > len(str(_OFFSET_CEILING_SECONDS)):
        # Refused on its length before `int` is reached: a token of thousands of
        # digits is past the ceiling on any reading, and `int` would raise on the
        # interpreter's own digit limit rather than answer.
        return None
    seconds = int(value.text)
    if abs(seconds) >= _OFFSET_CEILING_SECONDS:
        return None
    return timedelta(seconds=seconds)


def _declared_units(decoded: Mapping[str, object]) -> dict[str, str] | None:
    r"""Each requested variable's unit, as ``daily_units`` spells it, or ``None``.

    §5's row 8: a variable whose unit ``daily_units`` does not give as a string drops
    every day, because no day's transcription can carry what §5:5 says it carries. Two
    units that are strings are refused for the same reason one step on, since each is in
    **every** day's transcription: one carrying a line break would break each day's line
    structure, and one carrying a lone surrogate — JSON's ``"\ud800"`` decodes to one —
    has no UTF-8 encoding, so no record could hold it (``EncodableText``) and minting
    would raise where ADR-0260 §4 says a source reason is returned.

    Args:
        decoded: The decoded body.

    Returns:
        The units by variable, or ``None`` where every day is dropped for them.
    """
    units = decoded.get(_UNITS_KEY)
    if not isinstance(units, dict):
        return None
    declared: dict[str, str] = {}
    for variable in _DAILY_VARIABLES:
        unit = units.get(variable)
        if not isinstance(unit, str) or any(character in _LINE_BREAKS for character in unit):
            return None
        try:
            unit.encode("utf-8")
        except UnicodeEncodeError:
            return None
        declared[variable] = unit
    return declared


def _declared_day(text: str) -> tuple[int, int, int] | None:
    """The ``YYYY-MM-DD`` the provider named, as a year, month and day (§5's row 9).

    Written out rather than taken from :meth:`datetime.date.fromisoformat`, which
    since 3.11 also accepts ``YYYYMMDD`` and a week date: two spellings of one day
    would make the duplicate rule below compare unequal values that name the same day,
    which is exactly what ADR-0260 §5 drops a day *for*.

    Args:
        text: The value a ``time`` element carried.

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


def _named_day(element: object) -> tuple[int, int, int] | None:
    """The day one ``time`` element names, whatever else its position carries.

    **Read independently of every other drop rule, and that is the point** (§5's
    row 11). "A day the response names more than once is dropped in every one of its
    rows", so a position that names a day and is then dropped for another reason has
    still named it. A count taken over the *surviving* positions would let a complete
    position through beside an incomplete sibling naming the same day, which is the
    response describing that day twice and this system preferring one of the two.

    Args:
        element: One element of ``daily.time``.

    Returns:
        The year, month and day, or ``None`` where the position names none.
    """
    return _declared_day(element) if isinstance(element, str) else None


def _transcription(date: str, tokens: Sequence[str], units: Mapping[str, str]) -> str:
    """One day's content, in the form §5:5 fixes and this adapter pins.

    The ``time`` value, then each requested variable in the ``daily`` order with the
    provider's field name, its token as the response spelled it and its unit as
    ``daily_units`` spells it, one per line.

    Args:
        date: The ``time`` element, as the response spelled it.
        tokens: Each requested variable's token text, in ``_DAILY_VARIABLES``' order.
        units: Each requested variable's unit.

    Returns:
        The transcription.
    """
    lines = [f"{_TIME_KEY}{_NAME_SEPARATOR}{date}"]
    lines.extend(
        f"{variable}{_NAME_SEPARATOR}{token}{_UNIT_SEPARATOR}{units[variable]}"
        for variable, token in zip(_DAILY_VARIABLES, tokens, strict=True)
    )
    return _LINE_SEPARATOR.join(lines)


def _rendered_length(span: str) -> int:
    """How many characters ``span`` takes inside a ``json.dumps`` string rendering.

    Args:
        span: Text that will sit inside the transcription.

    Returns:
        Its rendered length, without the rendering's two delimiters.
    """
    return len(json.dumps(span)) - 2


def _extent_of(day: tuple[int, int, int], offset: timedelta) -> ReportedExtent | None:
    """The half-open bounds of ``day`` in the zone ``offset`` names (ADR-0260 §5).

    **Computed from the day the provider named and the offset its own response
    declared, and from nothing else** (ADR-0344 §5:4): the day's midnight at that offset
    and 24 hours later. No clock of ours, no timezone database of ours, no reader
    configuration and no place contributes a value here.

    Args:
        day: The year, month and day the provider named.
        offset: The ``utc_offset_seconds`` the response declared for every day.

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
    """One day of a response that survived rows 7 to 13 of ADR-0344 §5 (row 14's input).

    A small value rather than a tuple, so that the cap below reads what it keeps by
    name.

    Attributes:
        extent: The half-open bounds §5:4 computed for it.
        content: The transcription, verbatim.
    """

    __slots__ = ("content", "extent")

    def __init__(self, *, extent: ReportedExtent, content: str) -> None:
        """Hold one surviving day.

        Args:
            extent: Its extent.
            content: Its transcription.
        """
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

    1. ADR-0241 §1's guard on the bound, **first** — before the revalidation, before the
       connection record is read and before any channel is opened, so a value no
       deployment could pass reaches nothing.
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
    3. Inside the deadline the **caller** stated: the keyless connection's one record
       read and its refusals — a reference that is not connectable, a record naming a
       credential slot, an identity other than the bound one (ADR-0325 §2:3 to §2:5,
       ADR-0344 §3:5) — and **one** exchange, all of them
       :class:`~ai_assistant.tools.egress.HttpsEgressTransport`'s, at the seam ADR-0154
       §1 designates. No credential is read: the transport holds no ``Secrets`` face
       (ADR-0344 §3:1). Then ADR-0344 §5's reading of the response, here.

    **The invocation ledger's claim and completion, and no spend gate** (ADR-0324 §5:8).
    The weather pull transmits as ADR-0306 §5:7 decides for a call that leaves the hub:
    its attempt and its outcomes are its ``InvocationLedger`` claim and completion, as
    the searcher's are. So once the three checks above have passed, and before the
    exchange, ADR-0192's claim is appended, and a completion follows on **every exit this
    frame observes**, through the same :func:`~ai_assistant.tools.consume.consumed_call`
    the registry and the searcher use, so there is one implementation of it and not
    three. The two appends are outside the deadline, which ADR-0192 §3 leaves unbounded
    by this seam. **No spend gate**: ADR-0260 §6 names no admission, ADR-0324 §5:8 names
    only the ledger, and ``ForecastRefusal`` carries no ``SPEND_REFUSED`` member where
    ADR-0231 §17 gave ``SearchRefusal`` one. What the configured cost pair reaches is the
    **declaration** (ADR-0236 §1), which is what ADR-0236 §4's unknown-cost floor reads
    at the ruling.

    **A claim left open states that the read may have reached the provider**, the
    searcher's posture one integration along: a fault raised inside the claim — a
    connection-record read that failed, a call bound elsewhere, an invented
    cancellation — leaves it open, the honest state for a send that may have happened.

    **Every source reason is returned and none is raised** (§4). What *does* leave
    :meth:`read` is a fault that no :class:`ForecastRefusal` member names: a ``timeout``
    outside its domain, a call that does not survive revalidation, one carrying a
    definition this forecaster did not register, one its decision does not authorise,
    one bound to another account or another origin, a ledger fault on the claim, and a
    ``CancelledError`` the transport invented with nothing cancelled. Each is
    :class:`~ai_assistant.core.errors.ToolBindingError`,
    :class:`~ai_assistant.core.errors.ToolError`,
    :class:`~ai_assistant.tools.egress.TransportPinError`, one of ADR-0192's or a
    ``ValueError``.

    **One ask is one read, and the count is this class's** (§3). Exactly one exchange is
    opened on every outcome read off the wire, and **none** on the pre-transmit refusal
    against the connection record that reaches ``PROVIDER_REFUSED`` before any byte is
    transmitted. Nothing here
    retries, paginates, follows a link out of a response or re-issues with a different
    window, on any outcome.
    """

    __slots__ = (
        "_declaration",
        "_latitude",
        "_ledger",
        "_longitude",
        "_max_day_chars",
        "_max_days",
        "_name",
        "_transport",
    )

    def __init__(  # noqa: PLR0913 — the seam ADR-0260 §6 names, the ledger ADR-0324 §5:8 adds, the place §3 makes this forecaster's own, the two bounds §11 adds, the declaration §6's second check compares against and the identity §5 attests to; each is one thing this forecaster is handed rather than reaches for
        self,
        *,
        transport: HttpsEgressTransport,
        ledger: InvocationLedger,
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
                (ADR-0260 §6). It holds the registration, reads the connection record
                and opens the channel; this object holds none of the three. Keyless:
                built with no ``Secrets`` face (ADR-0344 §2:3).
            ledger: The ``InvocationLedger`` this forecaster claims and completes
                each read through (ADR-0324 §5:8, ADR-0192 §1, §3). Required, so a
                forecaster that transmits without its claim cannot be constructed.
                Never an ``AuditTrail``: the decision was recorded before this object
                was reached, and a forecaster that could record one would be deciding
                as well as acting.
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
        self._ledger = ledger
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
            ``egress_binding`` — the binding is derived by ``EgressBinder`` and
            accepted from nobody (§6).
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
                before the revalidation, before the connection record is read and
                before any channel — so a refused value reads nothing and opens nothing. The
                window it opens starts there too, so the revalidation is inside it.

        Returns:
            One outcome carrying records or a refusal.
            :attr:`~ai_assistant.core.types.ForecastRefusal.DEADLINE_EXPIRED` where
            **this** deadline fired (ADR-0241 §4): during the revalidation, where no
            claim was appended, or inside the claim, where the completion carries the
            declaration's ``interrupted_outcome``. An interruption the transport
            **absorbed** is read off this frame's own deadline and its own task rather
            than off what came back, so a transport that catches the cancellation and
            answers anyway is not recorded as having succeeded.

        Raises:
            ValueError: If ``timeout`` is not a ``timedelta`` or is not strictly
                positive (ADR-0241 §1). Refused before anything is read.
            ToolBindingError: If the call does not survive ADR-0029 §2's three checks
                (§6). The connection record is not read, no channel is opened and **no
                claim is appended** for any of them.
            AuthorisationSpentError: If the ledger refuses the claim because the
                authorisation is spent (ADR-0192 §1).
            UnrecordedAuthorisationError: If the trail holds no decision equal to this
                call's under its id, or holds one that is not an ``ALLOW``.
            AuditError: If the claim append failed with anything that is not an
                ``AssistantError``. A failure of the **completion** append is absorbed
                and reaches the operator as a diagnostic (ADR-0192 §3).
            ToolError: If the transport raised a ``CancelledError`` with **nothing
                cancelled** — ADR-0031 §2's invented cancellation, which ADR-0241 §7
                makes a fault rather than a teardown. The claim is left open.
            CancelledError: Re-raised unchanged when this call is cancelled from
                outside while suspended, and converted into neither an outcome nor a
                refusal (ADR-0060 §1); the claim is completed with the declaration's
                ``interrupted_outcome`` first. Raised **freshly** where the transport
                absorbed one, because a cancellation answered with a value is the
                absorption ADR-0060 §1 says a method never performs.
        """
        # **First, and that is ADR-0241 §1's placement**: `checked_timeout` is
        # ADR-0029 §4's own guard — one implementation of the rule, reached from every
        # seam that states it — and it returns a plain `timedelta` rebuilt from the
        # base class's fields, so a subclass whose `total_seconds` raises decides
        # nothing later.
        duration = checked_timeout(timeout)
        # **The window opens ahead of the revalidation** (ADR-0241 §1): the bound
        # covers the seam's own work, and a clock started after the checks would hand
        # the exchange a *fresh* budget. It does not cover the two ledger appends,
        # which ADR-0192 §3 leaves unbounded by this seam, so what is left of it after
        # the checks is what the exchange is handed.
        loop = asyncio.get_running_loop()
        expires_at = loop.time() + duration.total_seconds()
        checked, binding, origin, latitude, longitude = self._authorised(call)
        remaining = expires_at - loop.time()
        if remaining <= 0:
            # The window closed while this frame was revalidating. **No claim was
            # appended and no channel was opened**, so no completion is owed and none
            # is written — the searcher's before-the-claim exit, one seam over.
            return _refused(ForecastRefusal.DEADLINE_EXPIRED)

        outcome: ForecastOutcome | None = None

        async def act() -> ToolResult:
            nonlocal outcome
            outcome = await self._bounded(
                binding,
                origin=origin,
                latitude=latitude,
                longitude=longitude,
                remaining=remaining,
            )
            return _result_of(outcome, self._declaration, duration)

        # **ADR-0192's claim, the read, and a completion on every exit this frame
        # observes** (ADR-0324 §5:8): after the three checks above, so a call that is
        # not the one authorised appends no claim, and taken from the recorded decision
        # on the revalidated copy (ADR-0306 §5:7). An external cancellation is
        # completed with the declaration's `interrupted_outcome` and re-raised there.
        await consumed_call(
            ledger=self._ledger,
            definition=self._declaration,
            decision=checked.decision,
            act=act,
        )
        if outcome is None:
            # Unreachable: `consumed_call` returns only once `act` has, and `act` sets
            # the outcome before it returns. Checked rather than asserted, because what
            # would otherwise stand here is a `cast` over the value this method returns.
            msg = f"{self._declaration.id}: the read returned without an outcome"
            raise ToolError(msg)
        return outcome

    async def _bounded(
        self,
        binding: EgressBinding,
        *,
        origin: str,
        latitude: float,
        longitude: float,
        remaining: float,
    ) -> ForecastOutcome:
        """Make the one exchange inside what is left of the caller's window, and classify it.

        Inside the claim. Every exit but a raised fault is an outcome the completion is
        written from; an external cancellation is re-raised for ``consumed_call`` to
        complete with the declaration's ``interrupted_outcome``.

        Args:
            binding: The authorised binding.
            origin: The origin the ruled call carries.
            latitude: The latitude the ruled call carries.
            longitude: The longitude it carries.
            remaining: The seconds left of the caller's window, strictly positive.

        Returns:
            The outcome.

        Raises:
            ToolError: If the transport raised a ``CancelledError`` with nothing
                cancelled.
            CancelledError: Re-raised unchanged when this call is cancelled from
                outside, and raised freshly where the transport absorbed one.
        """
        entered_with = pending_cancellations()
        deadline = asyncio.timeout(remaining)
        try:
            async with deadline:
                answered = await self._asked(
                    binding, origin=origin, latitude=latitude, longitude=longitude
                )
        except asyncio.CancelledError as cancellation:
            if pending_cancellations() > entered_with:
                # An external cancellation: delivered onward unchanged (ADR-0060 §1),
                # and `consumed_call` completes the claim before it leaves.
                raise
            # ADR-0031 §2's invented cancellation — the count did not move, so nothing
            # was cancelled and this is a fault the transport raised. ADR-0241 §7 says
            # what it must *not* become: not a teardown that ends the turn, and not an
            # outcome. So it leaves as an `AssistantError`, and the claim is left open,
            # the honest state for a send that may have happened.
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

    def _authorised(self, call: ToolCall) -> tuple[ToolCall, EgressBinding, str, float, float]:
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
            The revalidated copy, whose decision the ledger claim is taken from, its
            binding and the three arguments its schema declares — each already
            narrowed, so no later frame carries a ``cast``.

        Raises:
            ToolBindingError: If the call does not survive revalidation, carries a
                definition unequal to this forecaster's registered original, is not
                authorised by its decision, or carries no egress binding. **The
                connection record is not read and no channel is opened for any of
                them.**
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
        # ADR-0364 §12:2-§12:3: the coordinates are planning's, the configured place's
        # where it named none, which the hub fills before the call is ruled on. They are
        # what the call sends, not where it goes: the origin is still pinned to the one
        # configured provider, and the ruling ranges over the coordinates it carries.
        return checked, binding, origin, latitude, longitude

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
        # ADR-0344 §4:1's target, whole: the five parameters in this order and no
        # other, the coordinate the ruled call carries, and nothing of a person, the
        # hub, the connection or its identity (§4:6).
        target = (
            f"{_PROVIDER_PATH}"
            f"?{_PROVIDER_LATITUDE_PARAMETER}={_decimal(latitude)}"
            f"&{_PROVIDER_LONGITUDE_PARAMETER}={_decimal(longitude)}"
            f"&{_PROVIDER_DAILY_PARAMETER}={','.join(_DAILY_VARIABLES)}"
            f"&{_PROVIDER_TIMEZONE_PARAMETER}={_PROVIDER_TIMEZONE}"
            f"&{_PROVIDER_DAYS_PARAMETER}={self._max_days}"
        )
        try:
            response = await self._transport.fetch(
                binding,
                origin=origin,
                target=target,
                # Keyless (ADR-0344 §2:3): no field carries a credential, and a
                # transport built with a `Secrets` face would refuse this call.
                credential_field=None,
                fields=_PROVIDER_FIELDS,
            )
        except HttpsResponseTooLargeError:
            # §5's row 1, decided by the seam while reading (ADR-0260 §11:3).
            return _refused(ForecastRefusal.RESPONSE_TOO_LARGE)
        except BoundCallChangedError:
            # The keyless connection's pre-transmit refusals against its one record
            # read (ADR-0325 §2:3 to §2:5), which ADR-0344 §3:5 maps here: a reference
            # that is not connectable, a record that names a credential slot, and an
            # identity other than the bound one — and a target the exchange will not
            # write. **None opened a channel**, which is why §13(i)'s count for this
            # outcome is zero.
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
        """Read one Open-Meteo response under ADR-0344 §5's table.

        **Rows 1 to 6 are taken in order, and the first that holds decides the read**
        (§5:1): row 1 is the seam's, decided while reading; then the status (row 2), the
        body (row 3) and the table's shape (row 4), then the declared instant (row 5),
        and only then whether the response names any day at all (row 6): shape first,
        instant second, days last.

        Args:
            response: What the seam read off the channel, under its bound.

        Returns:
            The outcome.
        """
        if response.status != _PROVIDER_OK:
            return _refused(ForecastRefusal.PROVIDER_REFUSED)
        decoded = _tokens(response.body)
        if decoded is None or not _table_admitted(decoded):
            return _refused(ForecastRefusal.PROVIDER_REFUSED)
        reported_at = declared_instant(response.headers)
        if reported_at is None:
            # ADR-0260 §5:7, ADR-0092 §3: "A response declaring **no** instant, or
            # carrying in that position a value that cannot be read as one, mints **no
            # record**". There is no substitute, and none is reached for (ADR-0344 §5:7).
            _log.info("forecast_response_declared_no_instant", tool_id=self._declaration.id)
            return _refused(ForecastRefusal.UNATTESTED)
        # Row 6. Row 4 has already refused a `daily` that is not an object and a `time`
        # that is not an array, so what fails these two tests is an absent member.
        daily = decoded.get(_DAILY_KEY)
        if not isinstance(daily, dict):
            return _refused(ForecastRefusal.NO_RESULT)
        times = daily.get(_TIME_KEY)
        if not isinstance(times, list):
            return _refused(ForecastRefusal.NO_RESULT)
        return self._minted(decoded, daily, times, reported_at=reported_at)

    def _minted(
        self,
        decoded: Mapping[str, object],
        daily: Mapping[str, object],
        times: Sequence[object],
        *,
        reported_at: datetime,
    ) -> ForecastOutcome:
        """Apply rows 7 to 13 of ADR-0344 §5's table, and mint row 14's survivors.

        **Day *i* is the *i*-th element of ``daily.time``, and its value for a variable
        is that variable's *i*-th element** (§5:3); row 4 has already refused a column of
        another length, so no value is assigned to a day by any other rule.

        - Rows 7 and 8 are facts about the whole response — the one offset, a variable's
          column and its unit — so each drops **every** day.
        - Row 11, a day named at more than one position, drops every one of its
          positions, counted over **every** position that names a day and not over the
          survivors of the other rows: a day named once by a complete position and again
          by an incomplete one has not been described *once*.
        - Rows 9, 10, 12 and 13 drop one position each.
        - Row 14 takes the **first** ``forecast_max_days`` survivors in ``daily.time``'s
          order (ADR-0260 §5:1); none surviving is ``NO_RESULT``.

        Args:
            decoded: The decoded body, read here for ``utc_offset_seconds`` and
                ``daily_units`` and for nothing else.
            daily: Its ``daily`` table.
            times: Its ``daily.time`` column.
            reported_at: The instant the response declared.

        Returns:
            The outcome: the records, or ``NO_RESULT`` where every day was dropped.
        """
        # **Counted in one pass, not one pass per position.** A response well inside
        # ``forecast_max_response_bytes`` can name thousands of days, and a membership
        # count taken per position would be quadratic — on the event loop's own thread,
        # with no ``await`` anywhere in this method for the deadline to be delivered at.
        named = [_named_day(element) for element in times]
        seen = Counter(day for day in named if day is not None)
        offset = _declared_offset(decoded.get(_OFFSET_KEY))
        units = _declared_units(decoded)
        columns = [daily.get(variable) for variable in _DAILY_VARIABLES]
        kept: list[_Day] = []
        present = [column for column in columns if isinstance(column, list)]
        if offset is not None and units is not None and len(present) == len(_DAILY_VARIABLES):
            # **The units are measured once, not once per day.** They are the same in
            # every day's transcription, and a response inside its byte bound can carry
            # a unit of a hundred thousand characters beside thousands of days: building
            # and encoding each day's transcription before measuring it would copy that
            # unit once per day — quadratic work on the event loop's own thread, where
            # the deadline cannot be delivered (adversarial review, round 1). So row 13
            # is first decided on the transcription's measure, and only a day that fits
            # is ever built.
            fixed = len(json.dumps(_transcription("", ("",) * len(_DAILY_VARIABLES), units)))
            for position, (element, day) in enumerate(zip(times, named, strict=True)):
                if len(kept) == self._max_days:
                    # Row 14 takes the first survivors; row 11 was counted over the whole
                    # response above, so nothing past here can change which they are.
                    break
                if day is None or seen[day] != 1 or not isinstance(element, str):
                    continue
                read = self._day_at(
                    position, element, day, columns=present, units=units, offset=offset, fixed=fixed
                )
                if read is not None:
                    kept.append(read)
        minted = tuple(self._record(day, reported_at) for day in kept)
        if not minted:
            return _refused(ForecastRefusal.NO_RESULT)
        return ForecastOutcome(reported_at=reported_at, records=minted)

    def _day_at(  # noqa: PLR0913 — the position, its date as spelled and as read, the three response-wide facts §5's rows 7 and 8 already judged, and their measure
        self,
        position: int,
        date: str,
        day: tuple[int, int, int],
        *,
        columns: Sequence[Sequence[object]],
        units: Mapping[str, str],
        offset: timedelta,
        fixed: int,
    ) -> _Day | None:
        """One position read into a day, or ``None`` where §5's rows 10, 12 or 13 drop it.

        **Row 11 is not applied here**, deliberately: it is a fact about the response
        rather than about one position, and :meth:`_minted` counts it over every position
        that names a day, before this is reached.

        Args:
            position: The day's index in ``daily.time``.
            date: The ``time`` element, as the response spelled it.
            day: The day it names.
            columns: Each requested variable's column, in ``_DAILY_VARIABLES``' order.
            units: Each requested variable's unit.
            offset: The one offset the response declared.
            fixed: The rendering's length for this response's transcription with the
                date and every token empty — the field names, the separators, the units
                and the two delimiters, measured once by :meth:`_minted`.

        Returns:
            The day, or ``None``.
        """
        extent = _extent_of(day, offset)
        if extent is None:
            return None
        tokens: list[str] = []
        for column in columns:
            token = column[position]
            if not isinstance(token, _Token):
                # Row 12: `null`, a boolean, a string, an array or an object, each of
                # which the format does not admit as a daily value.
                return None
            tokens.append(token.text)
        # Row 13, measured as ADR-0230 §6 measures a fetched document — on the
        # `json.dumps` rendering at its default `ensure_ascii=True`, its two delimiters
        # included, which is the rendering the prompt will carry. A ceiling on source
        # characters would admit a day six or twelve times this long while claiming to
        # admit this much (ADR-0222 §4). **That rendering escapes character by
        # character**, so its length is the skeleton's plus each inserted span's own;
        # the day is built only once that sum fits, and the built transcription is then
        # measured itself, so the rule stands on the rendering and not on the sum.
        if fixed + sum(map(_rendered_length, (date, *tokens))) > self._max_day_chars:
            return None
        content = _transcription(date, tokens, units)
        if len(json.dumps(content)) > self._max_day_chars:  # pragma: no cover — the sum is exact
            return None
        return _Day(extent=extent, content=content)

    def _record(self, day: _Day, reported_at: datetime) -> SemanticMemory:
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


#: The refusals a **completed** call produced: the provider answered, and what it
#: answered is not something this system will carry.
_COMPLETED_REFUSALS: Final = frozenset({ForecastRefusal.NO_RESULT, ForecastRefusal.UNATTESTED})

#: How a refusal that failed the invocation is classified for ADR-0029 §3's row, as the
#: searcher classifies the same three: a channel that could not be opened or continued
#: is the world being unavailable, and a response this system declined to buy, or one a
#: forecast cannot be read from, is a refusal.
_FAILURE_KINDS: Final[Mapping[ForecastRefusal, ToolFailureKind]] = {
    ForecastRefusal.TRANSPORT_FAILED: ToolFailureKind.UNAVAILABLE,
    ForecastRefusal.PROVIDER_REFUSED: ToolFailureKind.REFUSED,
    ForecastRefusal.RESPONSE_TOO_LARGE: ToolFailureKind.REFUSED,
}


def _result_of(
    outcome: ForecastOutcome, definition: ToolDefinition, timeout: timedelta
) -> ToolResult:
    """The invocation result ADR-0192's completion is written from (ADR-0324 §5:8).

    The searcher's ``_result_of`` one integration along, for its reasons. ``NO_RESULT``
    and ``UNATTESTED`` are answers the provider gave, so the invocation ``SUCCEEDED``;
    ``TRANSPORT_FAILED``, ``PROVIDER_REFUSED`` and ``RESPONSE_TOO_LARGE`` did not complete
    as calls, so they are ``FAILED``. ``DEADLINE_EXPIRED`` is the declaration's own
    ``interrupted_outcome`` (ADR-0029 §4, ADR-0241 §5), read from **this forecaster's
    own registered declaration**, through the invocation seam's own
    :func:`~ai_assistant.tools.invocation.expiry_failure`; its cost is left unset, which
    ``consumed_call`` records as ``UNKNOWN``. The message is the seam's own: a class
    and a rule, never a provider's body, an origin or a coordinate.

    Args:
        outcome: What the read produced.
        definition: This forecaster's declaration.
        timeout: The bound the **caller** stated, which an expiry's message names.

    Returns:
        The result, whose ``outcome`` and ``failure`` the completion transcribes.
    """
    refusal = outcome.refusal
    if refusal is None or refusal in _COMPLETED_REFUSALS:
        return ToolResult(outcome=ToolOutcome.SUCCEEDED)
    if refusal is ForecastRefusal.DEADLINE_EXPIRED:
        return expiry_failure(definition, timeout)
    return ToolResult(
        outcome=ToolOutcome.FAILED,
        failure=ToolFailure(
            kind=_FAILURE_KINDS[refusal],
            message=f"{definition.id}: the forecast read was refused, class {refusal.value}",
        ),
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
        # Rendered through `describe_untrusted` for `_checked_coordinate`'s reason, one
        # function down: the type has just been refused, so the value is anything at all
        # and its `__repr__` is the caller's — a message interpolating it directly could
        # raise in place of the `ValueError` this function promises.
        msg = f"{label} is an exact int; got {describe_untrusted(value)}"
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
            the equator while satisfying the range. An exact ``int`` too large to be a
            float lands here too, as a ``ValueError`` and not the ``OverflowError``
            ``float()`` raises for it.

    **The message is built with ``describe_untrusted``, and the diagnostic must not be
    able to destroy the diagnosis.** ``repr`` of a ten-thousand-digit integer raises on
    its own account — Python's integer-to-string limit — so an ``f``-string over the
    value would replace the field-naming refusal with an unrelated ``ValueError`` from
    inside the guard that was reporting it. That is ``core``'s own rule at a second
    seam, and the value here is one a JSON body can carry.
    """
    real = _real(value)
    if real is None:
        msg = f"{label} is a finite real number; got {describe_untrusted(value)}"
        raise ValueError(msg)
    if not math.isfinite(real):
        msg = f"{label} is finite; got {describe_untrusted(value)}"
        raise ValueError(msg)
    if not -maximum <= real <= maximum:
        msg = (
            f"{label} is from {-maximum} to {maximum} (ADR-0260 §11); got "
            f"{describe_untrusted(value)}"
        )
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
        try:
            return float(value)
        except OverflowError:
            # An exact ``int`` too large to be a float — ``10**10000``, which a JSON
            # body can carry and a caller can pass. ``OverflowError`` is **not** a
            # ``ValueError``, so letting it out would break the class every caller of
            # :func:`_checked_coordinate` is told to catch, and would reach
            # :meth:`ForecastEgress._authorised` as a fault where a refusal belongs.
            return None
    return None


def _decimal(value: float) -> str:
    """``value`` as a plain decimal this seam will write into a request target.

    The digits are ``repr``'s — the shortest spelling that reads back as the same
    float, so the provider is asked about the coordinate the ruling carried rather than
    about a rounded neighbour of it — written out in positional notation rather than
    in ``repr``'s exponent form. ``repr(0.00001)`` is ``1e-05``, which Open-Meteo's
    documentation does not show it reading as a coordinate, and an exponent's ``+``
    would be read as a space by a form-encoded query reader; ``0.00001`` is the same
    value and needs neither. So the characters are digits, ``-`` and ``.`` only, each
    RFC 3986 §2.3 unreserved; the exchange's own origin-form check is the authority and
    refuses rather than encodes.

    Args:
        value: The coordinate, already known finite by
            :func:`_checked_coordinate` at construction and by the schema at the
            ruling.

    Returns:
        Its decimal spelling.
    """
    return format(Decimal(repr(value)), "f")


__all__ = [
    "FORECAST_READ",
    "FORECAST_READ_CAPABILITY",
    "FORECAST_READ_ID",
    "FORECAST_SOURCE_NAME",
    "LATITUDE_ARGUMENT",
    "LONGITUDE_ARGUMENT",
    "ORIGIN_ARGUMENT",
    "ForecastEgress",
]
