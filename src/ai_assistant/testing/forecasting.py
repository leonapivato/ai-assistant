"""A canonical :class:`~ai_assistant.core.protocols.Forecaster` fake (ADR-0260 §12).

The shared test double for the ``Forecaster`` contract, so a subsystem that services a
forecast read — ``orchestration``'s read servicer — can exercise every branch of its own
pipeline without a provider, a credential or a channel, and without importing the
concrete forecaster (``CLAUDE.md`` golden rule 1).

**It records what it was handed**, which is what makes an arm asserting that a call did
*not* happen possible at all: :attr:`FakeForecaster.requested` and
:attr:`FakeForecaster.read_calls` are appended **on entry**, so the absence of a row is
the absence of a call rather than the absence of a *completed* one.

It is scriptable to every state ADR-0260 §5 distinguishes, which is what a consumer needs
to drive its own disposition (§8):

* **no provider configured** — ``origin=None``, so :meth:`FakeForecaster.request` answers
  ``None``, which §4 makes "a configuration fact and never a failure";
* **days**, each carrying a content and the extent §5 makes the whole decision worth
  buying — so a consumer's evidence row has a real window to compose ``supported`` from;
  and
* a **refusal**, into any :class:`ForecastRefusal` member — so a consumer can reach each
  of §8's dispositions without a provider.
  :attr:`ForecastRefusal.DEADLINE_EXPIRED` is reachable that way *and* by holding a call
  open past its bound, which is the honest route.

**And a fourth and a fifth, which are what make the cancellation clauses testable at
all.**
:meth:`read` runs inside a
:class:`~ai_assistant.testing.cancellation.SuspendableResource`, so a suite can arm
:meth:`FakeForecaster.suspend_next` and cancel a call that has *demonstrably* arrived at
an await. Without it the clause passes vacuously: a fake that completes immediately can
only be cancelled before it starts, which exercises none of the code an implementation
would use to catch a ``CancelledError`` during a provider call and convert it into a
refusal. **The same lever is what makes ADR-0241 §1's deadline testable here**: a call
held at that suspension and *not* released outlives whatever bound its caller stated.
:meth:`FakeForecaster.suspend_next_request` is the same lever on :meth:`request`, and
it exists because ADR-0260 §13's arm (c) puts that member's cancellation limb here:
§4 lets a ``request`` answer with no await, so this fake is the only subject the
clause has.

**The two bounds are the fake's own, for the concrete forecaster's reasons** (§4).
``ForecastOutcome`` carries neither, so a suite reads them off the harness rather than off
a value: this fake mints at most :attr:`FakeForecaster.max_days` records, taken **from the
front** as §5 requires, and **drops** — never truncates — a day whose content passes its
own bound, yielding :attr:`ForecastRefusal.NO_RESULT` where that takes the last one with
it.

**`request` takes no arguments and this fake has none to take** (§3). There is no place
to script per-ask, because there is no ask: the place is the deployment's configuration
and the horizon is the forecaster's own bound.

**It performs ADR-0260 §6's three pre-execution checks**, because §6 puts them on
``read`` itself and the shared suite asserts them of every implementation — a fake
that answered a call production would refuse would let a consumer's test pass over
an exchange no deployment can have. They are written out rather than imported, for
the reason the rest of this package restates what it stands in for.

**Not a fault injector.** Everything here conforms. A consumer that needs a forecaster
which *breaks* the contract on purpose — one whose ``name`` moves between calls, one
minting a record attested to some other instant, one returning an outcome carrying both
halves — is testing a reaction to a non-conforming producer and supplies its own stub for
it. This fake must stay the thing a conforming implementation is compared against; most
of those are unconstructable anyway, which is the point of ``ForecastOutcome`` enforcing
them.
"""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from pydantic import ValidationError

from ai_assistant.core.errors import ToolBindingError
from ai_assistant.core.types import (
    ActionRequest,
    Attestation,
    CostBasis,
    DataTier,
    ForecastOutcome,
    ForecastRefusal,
    Idempotency,
    MemorySource,
    Provenance,
    ReportedExtent,
    Reversibility,
    RiskLevel,
    SemanticMemory,
    ToolCall,
    ToolCost,
    ToolDefinition,
    describe_untrusted,
)
from ai_assistant.testing.cancellation import SuspendableResource
from ai_assistant.testing.spend import countable

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.types import FrozenJson, MemoryRecord
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

#: The id this fake's declaration carries. Distinct from the production forecaster's,
#: because a fake standing in for one is not that one: a test that asserted an id would
#: otherwise pass against either and mean nothing about which was wired.
FAKE_FORECAST_ID: Final = "fake_forecast_read"

#: The source instance a fake forecaster names itself, which is what a minted record's
#: ``Attestation.reported_by`` carries (ADR-0260 §5). Non-blank and unchanged by
#: ``Identifier``'s own validation, which §4 requires of every ``Forecaster``.
DEFAULT_FORECAST_SOURCE_NAME: Final = "fake forecast"

#: The origin a fake forecaster's request names unless a test says otherwise. A
#: reserved-for-documentation host, so nothing here resolves anywhere real even if some
#: future consumer forgot to inject a transport.
DEFAULT_FORECAST_ORIGIN: Final = "https://forecast.example.com"

#: The place a fake forecaster is configured for unless a test says otherwise. A real
#: coordinate, so that a consumer's assertion about a request's arguments is an assertion
#: about values a deployment could hold.
DEFAULT_FORECAST_LATITUDE: Final = 41.1579
DEFAULT_FORECAST_LONGITUDE: Final = -8.6291

#: ADR-0260 §11's named defaults, so a fake constructed with no bound is bounded the way
#: a default deployment is. ``DEFAULT_MAX_FORECAST_DAYS`` is also §11's **ceiling** — §7
#: makes three the figure that keeps the servicing precedence true in every configuration
#: — and this fake refuses a larger one for that reason: a canonical fake configurable
#: into a state no deployment can be in would let a consumer's test pass over a supply
#: this system can never actually assemble.
DEFAULT_MAX_FORECAST_DAYS: Final = 3
DEFAULT_MAX_DAY_CHARS: Final = 2048

#: The instant a fake response declares unless a test names another. Fixed, because
#: ADR-0092 §3 makes it the *provider's* statement: a fake reading a clock here would be
#: the substitute ADR-0260 §5 forbids, wearing a double's clothes.
DEFAULT_FORECAST_REPORTED_AT: Final = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

#: ADR-0038 §2a's figure for an attested producer, which every one of them carries.
_ATTESTED_CONFIDENCE: Final = 0.9

#: How long one day is, which is what makes a day's extent half-open (ADR-0117 §2).
_ONE_DAY: Final = timedelta(days=1)

#: ISO-4217's alphabetic form is three letters — ``ToolCost.currency``'s own rule
#: (ADR-0016 §4), which ADR-0236 §2 says is the code's whole domain here too.
_CURRENCY_CODE_LENGTH: Final = 3

#: The degrees each axis runs to, which is also its negative floor (ADR-0260 §11).
_MAX_LATITUDE: Final = 90.0
_MAX_LONGITUDE: Final = 180.0


@dataclass(frozen=True, slots=True)
class ScriptedDay:
    """One day a fake forecaster answers with.

    A pair rather than a record, because what a consumer scripts is what the *provider*
    said: the content is the transcription §5 keeps verbatim, and the extent is the day
    that content is about as the provider declared it. Everything else a minted record
    carries — its kind, its source, its confidence, its empty axes and its attestation
    instant — is fixed by §5 and is not a knob.

    Attributes:
        content: The transcription this day's record carries, verbatim.
        extent: Where that day lies, as a half-open interval. Built by
            :func:`forecast_day` from a calendar day and the offset that day is in,
            which is how ADR-0260 §5 computes one.
    """

    content: str
    extent: ReportedExtent


def forecast_day(
    year: int,
    month: int,
    day: int,
    *,
    offset: timedelta = timedelta(0),
    content: str | None = None,
) -> ScriptedDay:
    """One scripted day, with the extent ADR-0260 §5 would compute for it.

    **From the day and the offset alone**, which is the whole of §5's rule: "computed
    from the day the provider named and the UTC offset the provider's own response
    declared for it, and from nothing else — never from a clock of ours, never from a
    timezone database of ours, never from the reader's configuration, and never from the
    place."

    Args:
        year: The year the provider named.
        month: Its month.
        day: Its day.
        offset: The UTC offset that day declared it is in. Defaults to none, which is a
            day whose bounds are UTC midnight to UTC midnight.
        content: The transcription, or ``None`` for a distinctive default naming the day
            — distinctive enough that an assertion that it reached a reply is not an
            assertion about a coincidence.

    Returns:
        The scripted day.

    Raises:
        ValueError: If the three fields name no day the calendar has, or if ``offset``
            is not one :class:`datetime.timezone` admits.
    """
    start = datetime(year, month, day, tzinfo=timezone(offset))
    spelled = f"{year:04d}-{month:02d}-{day:02d}"
    return ScriptedDay(
        content=f"{spelled}\nClear\n11.4\n19.2\n0.0" if content is None else content,
        extent=ReportedExtent(
            extends_from=start.astimezone(UTC), extends_until=(start + _ONE_DAY).astimezone(UTC)
        ),
    )


#: What one forecast read brings back unless a test scripts something else: three dated
#: days, each in its own declared offset, in the order a provider returned them.
DEFAULT_FORECAST_DAYS: Final = (
    forecast_day(2026, 9, 5, offset=timedelta(hours=1)),
    forecast_day(2026, 9, 6, offset=timedelta(hours=1)),
    forecast_day(2026, 9, 7, offset=timedelta(hours=1)),
)


def _origin_schema() -> dict[str, FrozenJson]:
    """The origin argument's subschema, built fresh on every call.

    The keyword names are spelled rather than imported, so that the canonical fake
    reaches into no subsystem: ADR-0152 §3 fixes both, and
    ``tests/testing/test_fake_forecaster.py`` asserts these equal the constants
    ``tools/`` reads them by, which is what stops the two spellings drifting without
    anything noticing.

    Returns:
        The subschema, owned by the caller.
    """
    return {
        "type": "string",
        "x-egress-destination": "https",
        "x-egress-tier": "operational",
    }


def _coordinate_schema(*, maximum: float) -> dict[str, FrozenJson]:
    """One coordinate argument's subschema, built fresh on every call.

    Args:
        maximum: The degrees this axis runs to, which is also its negative floor.

    Returns:
        The subschema, owned by the caller.
    """
    return {
        "type": "number",
        "minimum": -maximum,
        "maximum": maximum,
        "x-egress-tier": "personal",
    }


#: The declaration this fake's :meth:`FakeForecaster.request` carries by value. Its
#: safety fields are the production declaration's, argued in ADR-0260 §6 and ADR-0016
#: §1, because a fake ruled on more leniently than the real thing would let a consumer's
#: policy test pass for a reason no deployment enjoys.
FAKE_FORECAST_READ: Final = ToolDefinition(
    id=FAKE_FORECAST_ID,
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
            "origin": _origin_schema(),
            "latitude": _coordinate_schema(maximum=_MAX_LATITUDE),
            "longitude": _coordinate_schema(maximum=_MAX_LONGITUDE),
        },
        "required": ["origin", "latitude", "longitude"],
        "additionalProperties": False,
    },
)


def _check_bounds(max_days: int, max_day_chars: int) -> None:
    """Refuse a bound outside ADR-0260 §11's stated domain for it.

    Args:
        max_days: ``Settings.forecast_max_days``.
        max_day_chars: ``Settings.forecast_max_day_chars``.

    Raises:
        TypeError: If either is not an ``int``, ``bool`` included — the type is part of
            the domain for the concrete forecaster's reason, and the canonical fake must
            not be the looser of the two.
        ValueError: If either is below 1, or if ``max_days`` is above
            :data:`DEFAULT_MAX_FORECAST_DAYS`, which is §11's whole stated domain and
            not merely its default.
    """
    for label, bound, ceiling in (
        ("max_days", max_days, DEFAULT_MAX_FORECAST_DAYS),
        ("max_day_chars", max_day_chars, None),
    ):
        if isinstance(bound, bool) or type(bound) is not int:
            msg = f"{label} must be an integer, got {bound!r}"
            raise TypeError(msg)
        if bound < 1:
            msg = f"{label} must be at least 1, got {bound}"
            raise ValueError(msg)
        if ceiling is not None and bound > ceiling:
            msg = f"{label} must be at most {ceiling} (ADR-0260 §11), got {bound}"
            raise ValueError(msg)


def _real(value: object) -> float | None:
    """``value`` as a plain ``float``, or ``None`` where it is not a real number.

    A ``bool`` is refused: it is an ``int`` by ``isinstance`` and means a flag rather
    than a measurement. Written out rather than imported, for the reason the rest of
    this module is — the fake may not import the subsystem it stands in for.

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
            # An exact ``int`` too large to be a float. ``OverflowError`` is not a
            # ``ValueError``, so letting it out would break the class this module's
            # constructor guards promise.
            return None
    return None


def _check_coordinate(label: str, value: float, *, maximum: float) -> None:
    """Refuse a coordinate outside ADR-0260 §11's stated domain for it.

    Args:
        label: The field's name, for the message.
        value: What was given.
        maximum: The degrees this axis runs to, which is also its negative floor.

    Raises:
        TypeError: If ``value`` is not a real number, ``bool`` included.
        ValueError: If it is not finite, is an exact ``int`` too large to be a float, or
            is outside ``[-maximum, maximum]``. A fake configurable into a state no
            deployment can be in is the failure this module refuses one field along.

    **The message is built with ``describe_untrusted``**: ``repr`` of a
    ten-thousand-digit integer raises on its own account, and the diagnostic must not be
    able to destroy the diagnosis.
    """
    if isinstance(value, bool) or not isinstance(value, float | int):
        msg = f"{label} must be a real number, got {describe_untrusted(value)}"
        raise TypeError(msg)
    number = _real(value)
    if number is None or not math.isfinite(number):
        # ``None`` here is an exact ``int`` too large to be a float, which is a value
        # no coordinate has; ``isfinite`` is the NaN and infinity half.
        msg = f"{label} must be finite (ADR-0260 §11), got {describe_untrusted(value)}"
        raise ValueError(msg)
    if not -maximum <= number <= maximum:
        msg = (
            f"{label} must be from {-maximum} to {maximum} (ADR-0260 §11), got "
            f"{describe_untrusted(value)}"
        )
        raise ValueError(msg)


def _checked_cost(amount: Decimal | None, currency: str | None) -> ToolCost | None:
    """The declared cost a configured fake carries, or ``None`` for absence.

    ADR-0236 §7's parity clause at ADR-0260 §11's pair: this fake takes "the same pair,
    in the same domain, and builds its declaration the same way", and it is "refused
    every state a deployment cannot be in".

    **A ``FREE`` basis is refused by there being no parameter that could ask for one**
    (ADR-0236 §3), which is the structural form of the prohibition rather than a check.

    **The countability predicate is imported and not restated.**
    :func:`ai_assistant.testing.spend.countable` is ADR-0194 §1's predicate as this
    package already states it, and reaching for it here crosses no subsystem boundary.

    Args:
        amount: ``Settings.forecast_cost_per_call``, or ``None``.
        currency: ``Settings.forecast_cost_currency``, or ``None``.

    Returns:
        The ``PER_CALL`` cost where both are given, and ``None`` where neither is.

    Raises:
        TypeError: If ``amount`` is not an exact ``Decimal``, or if ``currency`` is given
            and is not a ``str``.
        ValueError: If exactly one of the two is given; if ``amount`` is non-finite,
            negative, or not countable under ADR-0194 §1; or if ``currency`` is not
            exactly three uppercase ASCII letters.
    """
    if (amount is None) != (currency is None):
        given = "cost_per_call" if currency is None else "cost_currency"
        missing = "cost_currency" if currency is None else "cost_per_call"
        msg = (
            f"{given} is given and {missing} is not; a declared per-call cost needs both "
            f"the figure and the ISO-4217 code it is denominated in (ADR-0236 §1)"
        )
        raise ValueError(msg)
    if amount is None or currency is None:
        return None
    if type(amount) is not Decimal:
        msg = f"cost_per_call must be a Decimal, got {amount!r}"
        raise TypeError(msg)
    if not amount.is_finite():
        msg = f"cost_per_call must be finite (ADR-0236 §2), got {amount!r}"
        raise ValueError(msg)
    if amount < 0:
        msg = f"cost_per_call must not be negative (ADR-0236 §2), got {amount!r}"
        raise ValueError(msg)
    if not countable(amount):
        msg = (
            f"cost_per_call must be countable — below 1E15 and to at most nine "
            f"fractional digits (ADR-0194 §1), got {amount!r}"
        )
        raise ValueError(msg)
    if type(currency) is not str:
        msg = f"cost_currency must be a string, got {type(currency).__name__}"
        raise TypeError(msg)
    if len(currency) != _CURRENCY_CODE_LENGTH or not (
        currency.isascii() and currency.isupper() and currency.isalpha()
    ):
        msg = f"cost_currency must be three uppercase ASCII letters (ISO-4217), got {currency!r}"
        raise ValueError(msg)
    return ToolCost(basis=CostBasis.PER_CALL, amount=amount, currency=currency)


def _check_source(name: str, origin: str | None, reported_at: datetime) -> None:
    """Refuse a source this fake could not mint an attested record for.

    Every one of these is refused **where it is configured** rather than where it would
    bite, which is the whole posture of a canonical fake: a state this fake cannot answer
    from is one that raises out of :meth:`FakeForecaster.read` at an arbitrary later call,
    and ADR-0260 §4 says only a cancellation leaves that member.

    Args:
        name: The source instance.
        origin: The configured provider's origin, or ``None`` for none.
        reported_at: The instant a scripted response declares.

    Raises:
        ValueError: If ``name`` is blank or is a value ``Identifier`` would strip — §4's
            clause, and §5 requires this value and a record's ``reported_by`` to be
            **equal**; if ``origin`` is present and blank; or if ``reported_at`` is not
            timezone-aware, which ``UtcInstant`` refuses in every field this fake puts it
            in.
    """
    if not name.strip():
        msg = f"name must be non-blank, got {name!r}"
        raise ValueError(msg)
    if name.strip() != name:
        msg = f"name must be a value Identifier accepts unchanged, got {name!r}"
        raise ValueError(msg)
    if origin is not None and not origin.strip():
        msg = f"origin must hold text, or be None entirely, got {origin!r}"
        raise ValueError(msg)
    if reported_at.tzinfo is None or reported_at.utcoffset() is None:
        msg = f"reported_at must be timezone-aware, got {reported_at!r}"
        raise ValueError(msg)


@final
class FakeForecaster:
    """A scriptable, conforming ``Forecaster`` over a fixed answer (ADR-0260 §4)."""

    def __init__(  # noqa: PLR0913 — a script, an identity, an origin, a place, a refusal, an instant, two bounds, ADR-0236 §7's cost pair and an id factory; each is one knob a consumer sets on its own
        self,
        days: Sequence[ScriptedDay] = DEFAULT_FORECAST_DAYS,
        *,
        name: str = DEFAULT_FORECAST_SOURCE_NAME,
        origin: str | None = DEFAULT_FORECAST_ORIGIN,
        latitude: float = DEFAULT_FORECAST_LATITUDE,
        longitude: float = DEFAULT_FORECAST_LONGITUDE,
        refusal: ForecastRefusal | None = None,
        reported_at: datetime = DEFAULT_FORECAST_REPORTED_AT,
        max_days: int = DEFAULT_MAX_FORECAST_DAYS,
        max_day_chars: int = DEFAULT_MAX_DAY_CHARS,
        cost_per_call: Decimal | None = None,
        cost_currency: str | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Create a forecaster over one scripted answer.

        Args:
            days: What this forecaster's provider answered with, in the order it
                returned them — one record per day, before this fake's own bound is
                applied.
            name: The source instance this forecaster names itself, and what a minted
                record's ``reported_by`` carries. Non-blank and unchanged by
                ``Identifier``'s validation, checked here rather than at the first mint.
            origin: The origin :meth:`request` names, or ``None`` for a deployment that
                configured no forecast provider — under which :meth:`request` answers
                ``None`` and :meth:`read` is unreachable, because there is no request to
                rule on.
            latitude: The place this fake is configured for (ADR-0260 §3, §11). Finite
                and inside its axis's domain.
            longitude: Likewise.
            refusal: The class every read refuses with, so a consumer can drive each
                :class:`ForecastRefusal` member without a provider. A refusal is the more
                specific instruction and wins over ``days``: a fake that silently
                preferred the records would make a consumer's refusal branch untestable
                in the one case it is easiest to write by accident.
            reported_at: The instant a scripted response declares, on the provider's own
                clock (ADR-0260 §5, ADR-0092 §3). Timezone-aware, refused at construction
                rather than at a mint. Every minted record is attested to it, which
                ``ForecastOutcome`` enforces anyway.
            max_days: ``Settings.forecast_max_days``. At most this many records are
                minted, **taken from the front** as §5 requires, whatever was scripted.
                From 1 to :data:`DEFAULT_MAX_FORECAST_DAYS`, which is §11's whole stated
                domain and not merely its default.
            max_day_chars: ``Settings.forecast_max_day_chars``, counted on the quoted
                rendering as ADR-0230 §6 counts it. A scripted content beyond it is
                **dropped** at :meth:`read`, never truncated.
            cost_per_call: ``Settings.forecast_cost_per_call`` — the operator's own
                per-call figure, which this fake's declaration then carries as a
                ``PER_CALL`` cost (ADR-0236 §1, §7). Set it with ``cost_currency`` or not
                at all.
            cost_currency: ``Settings.forecast_cost_currency``. **There is no argument of
                any name that produces a ``FREE`` basis** (ADR-0236 §3).
            id_factory: Mints each record's id. Defaults to a fresh UUID hex, and is
                injectable so a suite can assert over a value it chose.

        Raises:
            TypeError: If a bound or a coordinate is not the type its domain admits, if
                ``cost_per_call`` is not a ``Decimal``, or if ``refusal`` is not a
                :class:`ForecastRefusal` member. ``ForecastRefusal`` is a ``StrEnum``, so
                ``"no_result"`` compares equal to a member without being one, and a fake
                that took it would raise out of :meth:`read` at the call it was scripted
                for.
            ValueError: If a bound, a coordinate, ``name``, ``origin``, ``reported_at``
                or the cost pair is outside the domain ADR-0260 §11 and ADR-0236 §2 state
                for it, or if the cost pair is given while ``origin`` is ``None`` — this
                fake's shape of §2's registration-whole refusal. Each is a state this
                fake could not answer from, refused here rather than at an arbitrary
                later call.
        """
        _check_bounds(max_days, max_day_chars)
        _check_coordinate("latitude", latitude, maximum=_MAX_LATITUDE)
        _check_coordinate("longitude", longitude, maximum=_MAX_LONGITUDE)
        _check_source(name, origin, reported_at)
        if refusal is not None and type(refusal) is not ForecastRefusal:
            # `ForecastOutcome.refusal` is typed to the enum, so a plain string would
            # raise out of `read` at the call it was scripted for. `type(...) is not`
            # rather than `isinstance`, because the annotation already forbids this and
            # mypy reads an `isinstance` narrowing as unreachable: this guard is for the
            # caller who ignored it, who is the only caller who can reach it.
            msg = f"a scripted refusal must be a ForecastRefusal member, got {refusal!r}"
            raise TypeError(msg)
        cost = _checked_cost(cost_per_call, cost_currency)
        if cost is not None and origin is None:
            # ADR-0236 §2's registration-whole refusal, in the one shape this fake has
            # for it: `origin=None` **is** "a deployment that configured no provider",
            # and neither cost field may be set unless the registration is whole.
            msg = (
                "cost_per_call and cost_currency are given and origin is None; a per-call "
                "figure for a forecaster that proposes nothing is a value nothing reads "
                "(ADR-0236 §2), so give an origin as well or give neither cost field"
            )
            raise ValueError(msg)
        #: This fake's own registered declaration, built per instance exactly as
        #: `build_forecast_integration` builds the production one (ADR-0236 §1).
        self._declaration = (
            FAKE_FORECAST_READ
            if cost is None
            else FAKE_FORECAST_READ.model_copy(update={"cost": cost})
        )
        self._name = name
        self._origin = origin
        self._latitude = float(latitude)
        self._longitude = float(longitude)
        self._days = tuple(days)
        self._refusal = refusal
        self._reported_at = reported_at
        self._max_days = max_days
        self._max_day_chars = max_day_chars
        self._id_factory = id_factory
        self._resource = SuspendableResource()
        #: A resource of :meth:`request`'s own, so that a suite can hold **that** member
        #: at a point it has demonstrably reached. ADR-0260 §13's arm (c) puts
        #: ``request``'s cancellation limb over the canonical fake and says why: §4 lets
        #: a ``request`` answer from held configuration with no await, "so the contract
        #: does not oblige that member to suspend and a production arm would be
        #: asserting a suspension point no implementation owes". This fake is therefore
        #: the only place the clause has a subject, and a second resource is what keeps
        #: arming one member from holding the other.
        self._proposals = SuspendableResource()
        #: How many times this forecaster's :meth:`request` was called. Appended on
        #: entry, so a consumer asserting that a proposal was never sought has the
        #: absence of a row to assert over.
        self.requested: list[None] = []
        #: Every call this forecaster's :meth:`read` was handed, in call order. Appended
        #: on entry, so "``read`` is never reached" is the absence of a row rather than
        #: the absence of a completed one.
        self.read_calls: list[ToolCall] = []

    @property
    def name(self) -> str:
        """The configured source this forecaster serves (ADR-0260 §4, §5)."""
        return self._name

    @property
    def log(self) -> ResourceLog:
        """When each call was inside this fake's modelled resource (ADR-0060)."""
        return self._resource.log

    def suspend_next(self) -> LoopSuspension:
        """Arm the next :meth:`read` to suspend inside the modelled resource.

        Returns:
            The handle a suite waits on and releases.

        Raises:
            RuntimeError: If a suspension is already armed.
        """
        return self._resource.suspend_next()

    def suspend_next_request(self) -> LoopSuspension:
        """Arm the next :meth:`request` to suspend inside its own modelled resource.

        **The lever ADR-0260 §13's arm (c) needs**, and the only one in this repository
        that can hold a ``request``: §4 lets that member answer from held configuration
        with no await, so a production forecaster suspends in it nowhere, and a
        cancellation delivered before a call starts exercises none of the code an
        implementation would use to convert one.

        Returns:
            The handle a suite waits on and releases.

        Raises:
            RuntimeError: If a suspension is already armed.
        """
        return self._proposals.suspend_next()

    async def request(self) -> ActionRequest | None:
        """Propose the forecast read this configuration would make, or answer none.

        **No parameters, which the conformance suite checks against the runtime
        signature** (ADR-0260 §3, §4). This fake holds no store, no supply and no
        listing — there is nothing else it *could* be handed, and there is no place for
        a caller to name.

        Returns:
            The request to rule on, carrying this fake's own declaration — which is
            :data:`FAKE_FORECAST_READ` where no cost was configured and its ``PER_CALL``
            twin where one was (ADR-0236 §1) — or ``None`` where this fake was built with
            no provider configured.

        Raises:
            CancelledError: Re-raised unchanged when a call armed by
                :meth:`suspend_next_request` is cancelled from outside while suspended,
                and converted into neither a proposal nor a ``None`` (ADR-0060, ADR-0260
                §4). That suspension is this fake's own: §4 lets a ``request`` answer
                with no await, so nothing here suspends unless a suite arms it, and this
                is the only subject ADR-0260 §13's arm (c) has for the clause.
        """
        self.requested.append(None)
        async with self._proposals.held():
            if self._origin is None:
                return None
            parameters: dict[str, FrozenJson] = {
                "origin": self._origin,
                "latitude": self._latitude,
                "longitude": self._longitude,
            }
            return ActionRequest(tool=self._declaration, parameters=parameters)

    async def read(self, call: ToolCall, /, *, timeout: timedelta) -> ForecastOutcome:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1, §2); a caller wrapping this in `asyncio.timeout` cancels the forecaster mid-await and cannot classify its own expiry
        """Return the scripted answer, under ``timeout``.

        **The bound is honoured and not merely accepted** (ADR-0241 §11). A fake that
        took the parameter and ignored it would leave the suite's deadline arm running
        against the production forecaster alone — and the whole point of the parameter
        being on the *contract* is that every ``Forecaster`` this system wires is bounded
        on the day it is written, the canonical fake included. So a call held open by
        :meth:`suspend_next` past ``timeout`` comes back
        :attr:`ForecastRefusal.DEADLINE_EXPIRED`.

        Args:
            call: The authorised call. Recorded and otherwise unread: ADR-0260 §3 gives
                this kind no argument to script by, so the answer is the one this fake
                was built with.
            timeout: The caller's bound on this call (ADR-0241 §1). **Required and
                strictly positive**, checked here rather than at the suspension, so a
                consumer that passed a value no deployment could pass is refused at the
                call rather than answered.

        Returns:
            The outcome: the scripted refusal where one was given,
            :attr:`ForecastRefusal.DEADLINE_EXPIRED` where ``timeout`` expired while this
            fake was held open, :attr:`ForecastRefusal.NO_RESULT` where every scripted day
            is beyond this fake's content bound, and otherwise up to ``max_days`` records
            carrying those days **from the front**, in order.

        Raises:
            ValueError: If ``timeout`` is not a ``timedelta`` or is not strictly positive
                — ADR-0241 §1's guard, and this fake states it rather than inheriting it,
                because "there is always a bound" is a claim about every implementation.
                Refused **before** the call is recorded, so a consumer asserting that a
                refused value reached nothing has the absence of a row to assert over.
            ToolBindingError: If the call does not survive ADR-0260 §6's three
                pre-execution checks (:meth:`_authorised`). Carrying **no**
                ``ForecastRefusal``, because it is no outcome of the read: the servicing
                records ``BINDING_FAILED``, which establishes no contact.
            CancelledError: Re-raised unchanged when a call armed by
                :meth:`suspend_next` is cancelled from outside while suspended, and
                converted into neither an outcome nor a refusal (ADR-0060, ADR-0260 §4).
                **Never converted into ``DEADLINE_EXPIRED``** (ADR-0241 §7): a
                cancellation this fake did not itself issue is not its expiry.
        """
        if not isinstance(timeout, timedelta) or timeout <= timedelta(0):
            msg = f"timeout must be a strictly positive timedelta (ADR-0241 §1); got {timeout!r}"
            raise ValueError(msg)
        self.read_calls.append(call)
        try:
            async with asyncio.timeout(timeout.total_seconds()):
                # **Inside the window, and ahead of everything else** (ADR-0241 §1):
                # the bound covers "the seam's own work — the revalidation, … the
                # response read and the transcription", so a clock started after the
                # checks would hand what follows a *fresh* budget. The production
                # forecaster opens its window at the same point, which is what makes
                # this a property of the contract rather than of one implementation.
                self._authorised(call)
                return await self._answered()
        except TimeoutError:
            # This fake's own deadline, and only ever this one: nothing it awaits raises
            # a `TimeoutError` of its own accord, so there is no second condition for
            # `Timeout.expired()` to tell apart here.
            return ForecastOutcome(refusal=ForecastRefusal.DEADLINE_EXPIRED)

    def _authorised(self, call: ToolCall) -> None:
        """Run ADR-0260 §6's three pre-execution checks, as every ``read`` owes them.

        **Stated here rather than inherited, which is this module's whole posture**: a
        canonical fake that answered a call production would refuse would let a
        consumer's test pass over an exchange no deployment can have. §6 puts the three
        on ``read`` itself — "The ``ToolCall`` is **revalidated and detached** … the
        definition on that detached copy is compared for equality against the
        forecaster's own registered declaration … ``PermissionDecision.authorises`` is
        **re-evaluated** against that same detached copy" — and the shared conformance
        suite asserts them of every implementation.

        **Written out rather than imported.** ``ai_assistant.tools.registry`` holds the
        production statement of the first check, and this package may not import the
        subsystem it stands in for (``CLAUDE.md`` golden rule 1) — the same reason
        :mod:`ai_assistant.testing.invoker` restates ADR-0192's consume. The shared
        suite drives both, so a divergence is a test failure rather than a latent
        surprise.

        **It runs after the call is recorded**, which is deliberate: a refused call
        *did* reach this member, and :attr:`read_calls` answers "was ``read`` reached"
        rather than "did a read complete". The ``timeout`` guard is the one thing ahead
        of the record, because a value no deployment could pass reaches nothing at all.

        Args:
            call: The call as handed, read only through the copy this makes of it.

        Raises:
            ToolBindingError: If the call does not survive revalidation, carries a
                definition unequal to this forecaster's own, or is not authorised by
                its decision.
        """
        try:
            checked = ToolCall.model_validate(call.model_dump())
        except ValidationError as exc:
            msg = "the call did not survive revalidation, so it is not the call that was authorised"
            raise ToolBindingError(msg) from exc
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
        named = (
            checked.request.parameters.get("origin"),
            _real(checked.request.parameters.get("latitude")),
            _real(checked.request.parameters.get("longitude")),
        )
        if named != (self._origin, self._latitude, self._longitude):
            # **§3's place clause, which is every forecaster's and not the production
            # one's alone.** "The place is the deployment's own configured place, and the
            # configuration is the naming act … held by the forecaster as its own
            # configuration", and no caller widens, narrows or offsets the read
            # (ADR-0093 §10). A call carrying this fake's declaration with another
            # coordinate is *validly authorised* — its own decision was recorded over its
            # own request — so the three checks above pass it, and only this comparison
            # stands between it and a scripted answer about somewhere the deployment did
            # not choose. A fake that answered it would let a consumer's test pass over an
            # exchange no deployment can have.
            msg = (
                f"{self._declaration.id}: this call names a place this forecaster is not "
                f"configured for, so the request would ask about somewhere the "
                f"deployment did not choose (ADR-0260 §3, §6)"
            )
            raise ToolBindingError(msg)

    async def _answered(self) -> ForecastOutcome:
        """The scripted outcome, from inside the modelled resource.

        Split out of :meth:`read` so the bound wraps the suspension rather than being
        checked around it: a fake that awaited its resource outside the deadline would
        answer late and call it a success.

        Returns:
            The outcome.
        """
        async with self._resource.held():
            if self._refusal is not None:
                return ForecastOutcome(refusal=self._refusal)
            # **The drop first and the cap over what survived it**, which is §5's order
            # and not an implementation detail: "Where more days survive the drop rule
            # below than ``forecast_max_days`` admits, the records minted are the *first*
            # that many". Slicing first would let an oversized early day consume a slot
            # and yield ``NO_RESULT`` where the response described a usable later one.
            surviving = [
                day
                for day in self._days
                # ADR-0260 §5's drop, counted on the quoted rendering: the siblings are
                # still minted, and where this takes the last one the read yielded
                # nothing rather than failing.
                if len(json.dumps(day.content)) <= self._max_day_chars
            ]
            minted = tuple(self._mint(day) for day in surviving[: self._max_days])
            if not minted:
                return ForecastOutcome(refusal=ForecastRefusal.NO_RESULT)
            return ForecastOutcome(reported_at=self._reported_at, records=minted)

    def _mint(self, day: ScriptedDay) -> MemoryRecord:
        """One ``SEMANTIC``, ``EXTERNAL``-sourced record carrying one day (ADR-0260 §5).

        Args:
            day: The scripted day.

        Returns:
            The record, attested to this fake's own report instant and carrying the
            day's own extent — the field the whole decision is bought for.
        """
        return SemanticMemory(
            id=self._id_factory() if self._id_factory is not None else uuid4().hex,
            content=day.content,
            fact=day.content,
            provenance=Provenance(
                source=MemorySource.EXTERNAL,
                confidence=_ATTESTED_CONFIDENCE,
                evidence=(),
                last_updated=self._reported_at,
                last_confirmed_at=self._reported_at,
                attestation=Attestation(
                    reported_by=self._name,
                    reported_at=self._reported_at,
                    extent=day.extent,
                ),
                # Asserts nothing in this band (ADR-0106 §1): the externality this record
                # carries is `MemorySource.EXTERNAL`, which `band_of` places in
                # `ATTESTED`, and this field is the `DERIVED` band's question.
                derived_from_external=False,
            ),
            topics=(),
            about_person=None,
        )


__all__ = [
    "DEFAULT_FORECAST_DAYS",
    "DEFAULT_FORECAST_LATITUDE",
    "DEFAULT_FORECAST_LONGITUDE",
    "DEFAULT_FORECAST_ORIGIN",
    "DEFAULT_FORECAST_REPORTED_AT",
    "DEFAULT_FORECAST_SOURCE_NAME",
    "DEFAULT_MAX_DAY_CHARS",
    "DEFAULT_MAX_FORECAST_DAYS",
    "FAKE_FORECAST_ID",
    "FAKE_FORECAST_READ",
    "FakeForecaster",
    "ScriptedDay",
    "forecast_day",
]
