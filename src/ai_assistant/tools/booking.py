"""The simulated booking provider: two declarations, one durable act, no wire (ADR-0273).

ADR-0273 §1's *"one integration, two declarations, absent unless a deployment
configures it whole"*, in the module of its own that section requires. It is the M33
walkthrough's booking half — a component that quotes a price, books once, charges, and
reports what it charged, behind the same declarations and the same seam a real provider
would sit behind — and it is **not** a real provider and never becomes one (§7).

**What it is for, and the one respect in which it cannot copy the forecaster.** ADR-0260
§12 built a reference provider for a *read*, and reasoned that an arm over a production
component cannot assert what no production component can produce. That reasoning
transfers whole. What does not transfer is that a forecast read **performs nothing**: a
booking **acts**, so every guarantee ADR-0255 §13 gates on has a subject only because it
acts. ADR-0273 §7 is what pays for the difference — this provider's act *"reaches no
system outside the deployment, moves no money and confers no capability in the world"*,
so it is §13's own **controlled integration** and that rule's first sentence is not
reached rather than narrowed.

**Two declarations and not one, because the money path needs both ends** (§1). The quote
is read from a step's ``output`` (ADR-0267 §4) and the charge from the acting step's own
(ADR-0271 §2), and ADR-0271 §2 forbids that *"no lane … mints an ``ActionQuote`` from a
charge"*. A single declaration that both quoted and charged would make the acting step
its own quote's producer, which is the defect #2409 names. So
:data:`BOOKING_AVAILABILITY` carries a ``quoted_output`` and no ``charged_output``, and
:data:`BOOKING_ACT` carries a ``charged_output`` and no ``quoted_output``.

**Both go in the ``ToolRegistry`` as well as the seam's table**, which is the email
integration's shape and deliberately **not** the forecast read's (§1). ADR-0260 §1 keeps
the forecast read out of every registry because *"a registry entry would put its
capability in front of the planner"*; here the opposite is the requirement, because M33
**is** the planner proposing a booking, the user confirming it and the driver dispatching
it.

**It reaches nothing.** No socket, no name resolution, no HTTP exchange, and no
``OutboundTransport`` parameter through which one could arrive (§3) — the injection route
by which the real and the fake transport both reach production code does not reach this
module at all. ``pyproject.toml``'s ``network transports are confined to the tools egress
seam`` contract names this module, so a later edit giving it a transport fails
``lint-imports`` rather than passing review.

**And it still performs ADR-0148 §6's four pre-transmit conditions whole** (§3), over a
destination nothing is transmitted to, because *"they are what a real booking provider's
safety rests on, and a walkthrough that skipped them would demonstrate a path the first
real provider does not take"*. :class:`BoundConnection` is the third statement of those
four conditions in this subsystem, beside
:class:`~ai_assistant.tools.egress.SmtpEgressTransport`'s and
:class:`~ai_assistant.tools.egress.HttpsEgressTransport`'s. It is a third copy rather
than a shared one because both of theirs are private methods interleaved with an
exchange this provider has none of, and extracting a shared one would edit the designated
egress seam (ADR-0154 §1) for a component that transmits nothing.

**Everything it answers comes from configuration** (§5). No clock, no random source, no
file it was not configured with and no network, so one configuration answers identically
on every call and across a restart — which is what makes the arms and the walkthrough
deterministic and offline in the ordinary gate.

**Every successful output says it is simulated, and so does every failure this module
classifies** (§6) — :data:`SIMULATION_NOTICE`, carried by the record whether or not any
surface renders it, and stated in both ``description``s, which is where the user meets it
at the confirmation prompt. **That field is not a mechanism**: no policy, criterion,
comparison, disposition, validator or ``ToolDefinition`` field is keyed on it, and
nothing here or anywhere else branches on it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import sqlite3
import stat
import threading
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, DecimalException
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, final

from ai_assistant.core.errors import AssistantError, ClassifiedToolError, ConnectionStoreError
from ai_assistant.core.types import (
    ChargedOutput,
    CostBasis,
    DataTier,
    DestinationProtocol,
    Idempotency,
    ProvisioningState,
    QuotedOutput,
    Reversibility,
    RiskLevel,
    StepVerification,
    ToolCost,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    VerificationKind,
    parameter_violations,
)
from ai_assistant.tools.egress_declaration import DESTINATION_KEYWORD, TIER_KEYWORD

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ai_assistant.core.protocols import Secrets
    from ai_assistant.core.types import EgressBinding, FrozenJson, SecretName
    from ai_assistant.tools.connection_store import ConnectionEntry, StoredEntry
    from ai_assistant.tools.egress_binder import ConnectionRecords, EgressRegistration


# --- the ids, the argument names and the output keys ---------------------

#: The availability read's id, registered at the seam and in the registry once a
#: deployment configures the provider. One tool per connected account (ADR-0148 §6)
#: means a registered id names the account as well as the operation; this bare form
#: names neither, which is why the constant is a template rather than a registration.
BOOKING_AVAILABILITY_ID: Final = "simulated_booking_availability"

#: The booking act's id, likewise.
BOOKING_ACT_ID: Final = "simulated_booking"

#: The argument carrying the recipient, which ADR-0152 §3's keyword makes the value a
#: ruling, a grant and a confirmation all range over. It is the configured endpoint on
#: every call, and the four conditions refuse any other (§3).
ORIGIN_ARGUMENT: Final = "origin"

#: The day being asked about, and the day being booked. It bears no destination — it
#: selects no recipient — and the ``personal`` tier, because every value of it is a day
#: of the owner's own trip (ADR-0146 §5).
DATE_ARGUMENT: Final = "date"

#: The availability answer's keys. :data:`PRICE_AMOUNT_KEY` and
#: :data:`PRICE_CURRENCY_KEY` are what :data:`BOOKING_AVAILABILITY`'s ``quoted_output``
#: names, so ADR-0267 §4's mint reads the price from them and from nothing else.
AVAILABLE_KEY: Final = "available"
PRICE_AMOUNT_KEY: Final = "price_amount"
PRICE_CURRENCY_KEY: Final = "price_currency"

#: The booking's keys. :data:`CHARGED_AMOUNT_KEY` and :data:`CHARGED_CURRENCY_KEY` are
#: what :data:`BOOKING_ACT`'s ``charged_output`` names, so ADR-0271 §2's reading takes
#: the charge from them and from nothing else.
BOOKED_KEY: Final = "booked"
CHARGED_AMOUNT_KEY: Final = "charged_amount"
CHARGED_CURRENCY_KEY: Final = "charged_currency"

#: The honesty field ADR-0273 §6 requires on **every** successful output, availability
#: answer and booking alike, and in the ``message`` of every ``ToolFailure`` this module
#: returns. **It is a statement in a record and nothing more**: §6 forbids any policy,
#: criterion, comparison, disposition, validator or ``ToolDefinition`` field to be keyed
#: on it, and nothing in this tree reads it.
SIMULATION_KEY: Final = "simulation_notice"
SIMULATION_NOTICE: Final = (
    "Simulated booking provider: no real reservation was made and no money moved."
)

#: The sentence both ``description`` values end with, so that the user meets it at the
#: confirmation prompt rather than on a page they may never open (ADR-0016 §1, §6).
_DESCRIBED_AS_SIMULATED: Final = (
    "This provider is simulated: it reaches no booking service, makes no real "
    "reservation and moves no money."
)

#: An ISO-4217 alphabetic code is exactly this long (ADR-0267 §1).
_CURRENCY_CODE_LENGTH: Final = 3

#: The one string shape a configured day may take — ISO-8601's **extended calendar
#: date**, which is also the shape :func:`_date_subschema` puts on the ``date``
#: *argument*. One rule for the configuration and the call, so the provider cannot
#: accept a spelling at one end that it refuses at the other; and the **same** rule
#: ``Settings`` states, so "the factory states the same rules at the one place a
#: provider can be built without going through ``Settings``" is true of the whole
#: domain rather than of most of it.
_CALENDAR_DAY: Final = re.compile(r"\d{4}-\d{2}-\d{2}")

#: The weakest record bound ADR-0273 §5 admits: *"a store that retains at least the
#: booking just made"*. ``0`` would prune the record its own booking had just inserted.
_MINIMUM_RETAINED_RECORDS: Final = 1

#: The **range the reader accepts**, which §5 leaves to the lane and requires to be
#: *"enforced **at the read** and never at the first prune"*. It is SQLite's own signed
#: 64-bit integer domain, because the bound reaches the store as a ``LIMIT`` parameter:
#: a larger value raises ``OverflowError`` out of the driver **at the first prune**,
#: which is exactly where §5 forbids the refusal to happen. ``Settings`` states the same
#: ceiling as its field's ``lt``; this states it at the one place a provider can be built
#: without going through ``Settings``.
_MAXIMUM_RETAINED_RECORDS: Final = 2**63


def _origin_subschema() -> dict[str, FrozenJson]:
    """The origin argument's subschema, built fresh on every call.

    Built rather than shared, for ``send_email``'s, ``web_search``'s and
    ``forecast``'s reason: ``core`` freezes what a ``ToolDefinition`` ends up
    holding, but the literal handed to it is an ordinary ``dict``, and a shared
    mapping would be reachable from anywhere that imported it.

    Returns:
        The subschema, owned by the caller.
    """
    return {
        "type": "string",
        DESTINATION_KEYWORD: DestinationProtocol.HTTPS.value,
        TIER_KEYWORD: DataTier.OPERATIONAL.value,
    }


def _date_subschema() -> dict[str, FrozenJson]:
    """The date argument's subschema, built fresh on every call.

    Returns:
        The subschema, owned by the caller. It declares **no** destination keyword — a
        date selects no recipient — and the ``personal`` tier, which is what ADR-0146
        §5 gives a field every value of which carries one.
    """
    return {
        "type": "string",
        "format": "date",
        "pattern": r"^\d{4}-\d{2}-\d{2}$",
        TIER_KEYWORD: DataTier.PERSONAL.value,
    }


def _parameters_schema() -> dict[str, FrozenJson]:
    """The schema both declarations carry, built fresh on every call.

    One schema for both, because both take exactly the recipient and the day: the
    availability read asks about a day and the act books that day, and an argument
    either could take that the other could not would be a difference with nothing
    behind it.

    Returns:
        The schema, owned by the caller.
    """
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            ORIGIN_ARGUMENT: _origin_subschema(),
            DATE_ARGUMENT: _date_subschema(),
        },
        "required": [ORIGIN_ARGUMENT, DATE_ARGUMENT],
        "additionalProperties": False,
    }


BOOKING_AVAILABILITY: Final = ToolDefinition(
    id=BOOKING_AVAILABILITY_ID,
    capability="booking_availability",
    description=(
        "Ask the configured booking provider whether a date is available and what it "
        f"would charge to book it. {_DESCRIBED_AS_SIMULATED}"
    ),
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.REVERSIBLE,
    side_effecting=False,
    reads=(DataTier.SECRET, DataTier.OPERATIONAL),
    writes=(),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NATURAL,
    quoted_output=QuotedOutput(amount=PRICE_AMOUNT_KEY, currency=PRICE_CURRENCY_KEY),
    charged_output=None,
    parameters_schema=_parameters_schema(),
)
"""The availability read's declaration, every field of which ADR-0273 §2 fixes.

- ``side_effecting=False``, ``idempotency=NATURAL``, ``reversibility=REVERSIBLE`` —
  which ``_effects_are_consistent`` requires of anything not side-effecting. A read
  performs nothing, here or at the far end.
- ``risk_level=LOW``. The read *"performs nothing, discloses nothing and spends
  nothing"*, and §2 states the gap to the act's ``HIGH`` as *"the whole point of the
  field"*: **a deployment that finds the read prompting has a policy threshold to
  examine and not a declaration to edit**.
- ``reads=(SECRET, OPERATIONAL)`` — the credential the bound connection names, which
  ADR-0148 §6's conditions 2 and 3 make it read on every call **including for a
  provider that accepts it and does not use it** (ADR-0260 §12), and the configured
  availability and prices (§5). ``reads=()`` would be the silent no-reach claim
  ADR-0016 §1 makes this field required to prevent.
- ``writes=()``. A read changes nothing this system stores.
- ``discloses=()``, because nothing this provider is given leaves the device (§3).
  **§2 constrains a real provider in exactly this one respect: no lane copies this
  value into a provider that discloses.** Its stated cost is that the walkthrough
  exercises no disclosure gating, which §8 books.
- ``cost=FREE``, and **``cost`` is never the charge** (§2). Invoking this tool spends
  nothing: the provider is in-process, reaches no metered service and holds no account
  that could be billed. Nothing derives it from, defaults it from or keeps it in step
  with the configured prices.
- ``quoted_output`` names, at depth one, the key carrying the **whole price this
  provider quotes for the booking** — ``QuotedOutput.amount`` in ADR-0267 §3's own
  sense — and the key carrying its ISO-4217 code.
- ``charged_output=None``: a read charges nothing, and ADR-0271 §2's *"A declaration
  carrying ``None`` reports no charge ever"* is the true statement here.
- **No ``bounded_arguments`` member**, so no ``BoundKind.MONEY`` argument is declared
  and the owner's ``max_price`` route is not opened here (§2, §8).
- **Nothing is declared for the effect key**: it is derived at ``ToolCall.effect_key``,
  and *"Derived rather than minted, supplied, configured or carried as a field"* is
  relied on rather than restated.
"""


BOOKING_ACT: Final = ToolDefinition(
    id=BOOKING_ACT_ID,
    capability="book_stay",
    description=(
        "Book the configured booking provider's stay for a date, charging what it "
        f"charges. {_DESCRIBED_AS_SIMULATED}"
    ),
    risk_level=RiskLevel.HIGH,
    reversibility=Reversibility.IRREVERSIBLE,
    side_effecting=True,
    reads=(DataTier.SECRET, DataTier.OPERATIONAL),
    writes=(DataTier.PERSONAL, DataTier.OPERATIONAL),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
    quoted_output=None,
    charged_output=ChargedOutput(amount=CHARGED_AMOUNT_KEY, currency=CHARGED_CURRENCY_KEY),
    postconditions=(
        StepVerification(kind=VerificationKind.FIELD_EQUALS, field=BOOKED_KEY, equals=True),
    ),
    parameters_schema=_parameters_schema(),
)
"""The booking act's declaration, every field of which ADR-0273 §2 fixes.

- ``side_effecting=True``, ``reversibility=IRREVERSIBLE``, ``risk_level=HIGH``.
  ADR-0016 §2 fixes ``IRREVERSIBLE`` as *"it cannot be taken back"*, and **neither
  this tool nor anything else in this system undoes a booking**: §8 keeps
  cancellation, modification and refunds out of that decision entirely, and no other
  component is given a route to the store. The irreversibility is stated over the
  **commit count**, which no retention rule, bound or pruning decrements, rather than
  over the record the bound outlives. ``risk_level`` is **not lowered because the
  provider is simulated**: a declaration tuned to make a walkthrough quieter would
  demonstrate a confirmation path no real booking takes.
- ``idempotency=NONE`` and **no ``KEYED`` window**. ADR-0016 §4 admits ``KEYED`` only
  on a real deduplication *guarantee* and this provider offers none. ``NONE`` is also
  what makes the walkthrough worth running: under ADR-0192 §1 a ``side_effecting``
  non-``NATURAL`` authorisation is **spendable**, so ADR-0259 §2's effect claim is the
  only thing standing between a replan and a second booking.
- ``reads=(SECRET, OPERATIONAL)`` as the read's, for the read's reasons.
- ``writes=(PERSONAL, OPERATIONAL)`` — the booking record, which carries what the user
  asked, and the commit count beside it, which carries nothing of theirs.
- ``discloses=()`` (§3), ``cost=FREE`` and no ``bounded_arguments``, exactly as the
  read declares them and for the same stated reasons.
- ``charged_output`` names, at depth one, the key carrying the **whole amount that
  invocation charged** and the key carrying its ISO-4217 code (ADR-0271 §2);
  ``quoted_output=None``, because **a quote is prospective and a charge is
  retrospective**, and a single declaration doing both would make the acting step its
  own quote's producer (§1).
- **One ``postcondition``** (ADR-0253 §4), over a key of its own output, so that M33's
  verification half has a subject. §2 *"requires no more than one and requires no
  strength of it"*: the owner ruled on #2255 that verification space exists but need
  not be strong, and a predicate over one step's own output is *"not the verification
  A10 lands"*.

**It classifies at ADR-0262 §3's rung 2, and §7 requires that it does**: it is
``side_effecting``, its ``reversibility`` is more severe than ``REVERSIBLE``, and its
decision carries an ``egress_binding`` — *"a reference provider classifying at rung 1
would demonstrate the wrong rung of the ladder M33 exists to exercise"*.
"""


# --- the configuration this provider answers from, and nothing else ------


class BookingConfigurationError(AssistantError):
    """A configured availability, price, charge or bound outside ADR-0273 §5's domain.

    Raised where a provider is built from a configuration the readers would not
    accept — *"refused when it is read, and no provider is built from it"*.
    ``Settings`` refuses each of these at load; this states the same rules at the one
    place a provider can be built without going through it.
    """


def _checked_amount(value: Decimal | int | str, *, field: str) -> Decimal:
    """Return ``value`` as the ``Decimal`` ADR-0267 §4's reading admits, or refuse it.

    §5's domain: *"a JSON **string** a ``Decimal`` accepts or a JSON **integer**, whose
    ``Decimal`` is **finite and not negative**"*. A JSON **float** and a JSON
    **boolean** are refused on their own ground — ``bool`` is a subclass of ``int`` in
    Python, so a check written as an ``int`` instance test admits ``true`` as
    ``Decimal(1)`` and states a one-unit price that satisfies almost any ceiling, which
    is the refusal ADR-0267 §4 states because the implementation language will not.

    The order is :func:`~ai_assistant.orchestration.charges.charge_read`'s: finiteness
    **before** the sign, because ``Decimal("sNaN") < 0`` raises rather than answering,
    and ``"NaN"``, ``"Infinity"`` and ``"-Infinity"`` are strings ``Decimal``
    **accepts**.

    Args:
        value: The configured amount.
        field: The setting's name, for the message the operator reads.

    Returns:
        The amount.

    Raises:
        BookingConfigurationError: If it is outside the domain.
    """
    if isinstance(value, bool) or not isinstance(value, Decimal | int | str):
        msg = (
            f"{field} must be a decimal string or an exact integer (ADR-0273 §5, "
            f"ADR-0267 §4); a flag and a binary float are not prices"
        )
        raise BookingConfigurationError(msg)
    try:
        amount = Decimal(value)
    except (ArithmeticError, DecimalException, ValueError) as exc:
        msg = f"{field} is not a decimal amount (ADR-0273 §5, ADR-0267 §4)"
        raise BookingConfigurationError(msg) from exc
    if not amount.is_finite():
        msg = f"{field} must be finite (ADR-0273 §5); 'NaN' and 'Infinity' are not prices"
        raise BookingConfigurationError(msg)
    if amount < 0:
        msg = f"{field} must not be negative (ADR-0273 §5)"
        raise BookingConfigurationError(msg)
    return amount


def _checked_currency(value: str, *, field: str) -> str:
    """Return ``value`` if it is ADR-0267 §1's ISO-4217 shape, or refuse it.

    **Shape and never a register**, exactly as
    :func:`~ai_assistant.orchestration.charges._iso_4217_shaped` reads one: validating
    against the live table would make a record's decoding depend on a list that changes
    when currencies are withdrawn, and silently upcasing ``"usd"`` would treat a
    lowercase code and a typo'd one differently for no reason a caller can see.

    Args:
        value: The configured code.
        field: The setting's name, for the message the operator reads.

    Returns:
        The code.

    Raises:
        BookingConfigurationError: If it is not three uppercase ASCII letters.
    """
    if (
        not isinstance(value, str)
        or len(value) != _CURRENCY_CODE_LENGTH
        or not (value.isascii() and value.isupper() and value.isalpha())
    ):
        msg = f"{field} must be three uppercase ASCII letters (ISO-4217, ADR-0267 §1)"
        raise BookingConfigurationError(msg)
    return value


def _checked_day(value: date | str, *, field: str) -> date:
    """Return ``value`` as an ISO-8601 calendar day, or refuse it.

    Args:
        value: The configured day.
        field: The setting's name, for the message the operator reads.

    Returns:
        The day.

    Raises:
        BookingConfigurationError: If it is not one.
    """
    if isinstance(value, datetime):
        # **Stated because the implementation language will not state it**, exactly as
        # the amount reader states that a flag is not a price: ``datetime`` is a
        # subclass of ``date``, so an ``isinstance`` check admits one — and a catalogue
        # built from it compares a ``datetime`` against an invocation's plain ``date``
        # and raises ``TypeError`` out of the comparison rather than answering. A day is
        # a calendar day; an instant is not one, and silently taking its date part would
        # discard a time the operator wrote.
        msg = (
            f"{field} must be an ISO-8601 calendar date and not an instant "
            f"(ADR-0273 §5); a datetime carries a time of day this provider has no "
            f"meaning for"
        )
        raise BookingConfigurationError(msg)
    if isinstance(value, date):
        return value
    # **The extended form and nothing else** (§5). ``date.fromisoformat`` also reads the
    # basic form ``20261001`` and ISO week and ordinal dates; ``Settings`` refuses each
    # of those under the shape it states, so admitting them here would make the factory
    # and the settings two different configuration domains — which is exactly what this
    # function's docstring promises they are not.
    if not isinstance(value, str) or _CALENDAR_DAY.fullmatch(value) is None:
        msg = (
            f"{field} must be a calendar date in the form 2026-10-01 (ADR-0273 §5); "
            f"the basic form and ISO week and ordinal dates are refused here as "
            f"``Settings`` refuses them"
        )
        raise BookingConfigurationError(msg)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover — a shaped string with an unreal day
        msg = f"{field} must be a real calendar date (ADR-0273 §5)"
        raise BookingConfigurationError(msg) from exc


def _checked_retained(value: int) -> int:
    """Return ``value`` if it is ADR-0273 §5's record bound, or refuse it.

    The bound is an integer ``n >= 1``. A **boolean** is refused on its own ground —
    ``bool`` being an ``int``, *"which a naive integer reader admits"* — and so is a
    float, a string and anything else that merely converts.

    Args:
        value: The configured bound.

    Returns:
        The bound.

    Raises:
        BookingConfigurationError: If it is not an exact integer inside
            ``[1, 2**63)``.
    """
    if isinstance(value, bool) or type(value) is not int:
        msg = (
            "booking_retained_records must be an exact integer (ADR-0273 §5); a flag, "
            "a float and a decimal spelling are not counts"
        )
        raise BookingConfigurationError(msg)
    if value < _MINIMUM_RETAINED_RECORDS:
        msg = (
            f"booking_retained_records must be at least {_MINIMUM_RETAINED_RECORDS} "
            f"(ADR-0273 §5): a store that retains at least the booking just made is the "
            f"weakest bound the decision admits, and 0 would prune the record its own "
            f"booking had just inserted"
        )
        raise BookingConfigurationError(msg)
    if value >= _MAXIMUM_RETAINED_RECORDS:
        msg = (
            f"booking_retained_records must be below {_MAXIMUM_RETAINED_RECORDS} "
            f"(ADR-0273 §5): the bound reaches the store as a LIMIT parameter, so a larger "
            f"value raises out of the driver at the first prune — which is where §5 "
            f"forbids the refusal to fall"
        )
        raise BookingConfigurationError(msg)
    return value


@final
@dataclass(frozen=True, slots=True)
class BookingCatalogue:
    """What a deployment configured this provider to answer (ADR-0273 §5).

    **The whole of what the provider reads.** It consults no clock it was not given,
    no random source, no file it was not configured with and no network, so one
    catalogue answers identically on every call and across a restart.

    §5 fixes no field names, no file format and no ``Settings`` shape — *"those are
    the implementing lane's"* — and fixes only what the shape must be able to say.
    These seven fields say all of it: a price **under** a stated bound and one **over**
    it are two spellings of :attr:`price_amount`; an **unavailable** date is any day
    outside ``[available_from, available_to]``; a charge that **equals** the quote, one
    whose **amount** disagrees and one whose **currency** disagrees are three spellings
    of :attr:`charge_amount` and :attr:`charge_currency`; and the ``INDETERMINATE``
    outcome §4 requires is :attr:`indeterminate_date`.

    Attributes:
        available_from: The first day this provider has a stay for, inclusive.
        available_to: The last, inclusive. A day outside the window is unavailable,
            which the read answers and the act refuses (§10 arm 6).
        price_amount: The whole price the availability read quotes, in ADR-0267 §3's
            own sense — *"the whole charge the act will make"* as the provider states
            it **at the read**.
        price_currency: That price's ISO-4217 code.
        charge_amount: The whole amount a booking charges. **Not required to equal
            :attr:`price_amount`**: ADR-0271 §2 makes a charge *retrospective*, and §3
            of that decision exists precisely for the case where the two differ. §5's
            disagreeing-charge configuration is *"not a provider whose ``quoted_output``
            lies"*; it is the case the corpus wrote a finding for.
        charge_currency: That charge's ISO-4217 code, independently configurable from
            :attr:`price_currency` for the same reason.
        retained_records: How many booking records the store keeps, beyond which the
            oldest are pruned (§2). **The commit count is not pruned** and is what
            carries the act's irreversibility past the record's retention.
        indeterminate_date: The one day whose booking **commits and then reports that
            it may have committed**, so that ADR-0255 §6's authoritative record of the
            uncertainty is driven against a production component (§4). ``None`` where
            a deployment configured none.
    """

    available_from: date
    available_to: date
    price_amount: Decimal
    price_currency: str
    charge_amount: Decimal
    charge_currency: str
    retained_records: int
    indeterminate_date: date | None = None

    @classmethod
    def checked(  # noqa: PLR0913 — one parameter per configured fact ADR-0273 §5 names
        cls,
        *,
        available_from: date | str,
        available_to: date | str,
        price_amount: Decimal | int | str,
        price_currency: str,
        charge_amount: Decimal | int | str,
        charge_currency: str,
        retained_records: int,
        indeterminate_date: date | str | None = None,
    ) -> BookingCatalogue:
        """Build a catalogue from configured values, refusing one outside §5's domains.

        **The refusal is here as well as in ``Settings``, and that is deliberate.**
        ``Settings`` refuses each shape at load, which is where a deployment meets it;
        this states the same rules at the one place a provider can be built without
        going through it, exactly as ``build_forecast_integration`` restates ADR-0260
        §11's bounds. Otherwise a deployment starts, every arm passes on its own
        fixtures, and the walkthrough's quote or charge silently yields nothing —
        ADR-0267 §4's and ADR-0271 §2's readings each *"raise nothing"* by design, so a
        bad configuration has no other place to be caught.

        Args:
            available_from: The first available day.
            available_to: The last available day.
            price_amount: The quoted price.
            price_currency: Its ISO-4217 code.
            charge_amount: The amount a booking charges.
            charge_currency: Its ISO-4217 code.
            retained_records: The §2 record bound.
            indeterminate_date: The day whose booking reports an uncertain effect.

        Returns:
            The catalogue.

        Raises:
            BookingConfigurationError: If any value is outside ADR-0273 §5's domain for
                it, or if the availability window ends before it begins.
        """
        first = _checked_day(available_from, field="booking_available_from")
        last = _checked_day(available_to, field="booking_available_to")
        if last < first:
            msg = (
                "booking_available_to is before booking_available_from, so the provider "
                "would have no available day at all (ADR-0273 §5)"
            )
            raise BookingConfigurationError(msg)
        return cls(
            available_from=first,
            available_to=last,
            price_amount=_checked_amount(price_amount, field="booking_price_amount"),
            price_currency=_checked_currency(price_currency, field="booking_price_currency"),
            charge_amount=_checked_amount(charge_amount, field="booking_billed_amount"),
            charge_currency=_checked_currency(charge_currency, field="booking_billed_currency"),
            retained_records=_checked_retained(retained_records),
            indeterminate_date=(
                None
                if indeterminate_date is None
                else _checked_day(indeterminate_date, field="booking_indeterminate_date")
            ),
        )

    def available(self, day: date) -> bool:
        """Whether this provider has a stay for ``day``.

        Args:
            day: The day asked about.

        Returns:
            Whether it falls inside the configured window, ends included.
        """
        return self.available_from <= day <= self.available_to


# --- the durable state: a bounded record set and a count that only rises --

_OWNER_ONLY: Final = stat.S_IRUSR | stat.S_IWUSR
_SIDECARS: Final = ("-journal", "-wal", "-shm")
_SCHEMA_VERSION: Final = 1
_META_SCHEMA: Final = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
_BOOKINGS_SCHEMA: Final = (
    "CREATE TABLE IF NOT EXISTS bookings("
    "sequence INTEGER PRIMARY KEY AUTOINCREMENT, record TEXT NOT NULL)"
)
_READ_META: Final = "SELECT value FROM meta WHERE key = ?"
_WRITE_META: Final = "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)"
_INSERT_BOOKING: Final = "INSERT INTO bookings(record) VALUES (?)"
_READ_BOOKINGS: Final = "SELECT record FROM bookings ORDER BY sequence ASC"
_PRUNE_BOOKINGS: Final = (
    "DELETE FROM bookings WHERE sequence NOT IN "
    "(SELECT sequence FROM bookings ORDER BY sequence DESC LIMIT ?)"
)
_SCHEMA_VERSION_KEY: Final = "schema_version"
_COMMIT_COUNT_KEY: Final = "commit_count"


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` on a worker thread and wait for it to **physically** finish.

    **The seventh copy of this helper rather than an import from a sibling**, which is
    the tree's established position rather than a fresh choice: ``memory``,
    ``planning``, ``permissions``, ``evaluation``, ``archive`` and
    ``tools/connection_store.py`` each carry their own, golden rule 1 forbids importing
    another subsystem's, and #506 and #563 already track consolidating the family. The
    one inside this subsystem is
    :func:`~ai_assistant.tools.connection_store._run_to_completion`, module-private
    there; this is that function, unchanged in substance.

    **Why the store may not simply call SQLite on the loop thread.** ``BEGIN
    IMMEDIATE`` takes the write lock, and under cross-process contention it blocks for
    the driver's default — with no busy timeout set anywhere in this family (#564). The
    system composes on **one** event loop, so a blocking call there stalls every
    unrelated task and the invocation seam's own deadline (ADR-0029 §4) along with
    them. Every other SQLite store in this tree hands off for exactly that reason.

    **The worker records its own outcome and sets a** :class:`threading.Event` **when
    it physically returns**, and this coroutine waits on *that* signal rather than on
    the cancellable state of any task — so the store's lock is held for the whole life
    of the worker even if the awaiting task, or a blanket cancellation, is cancelled.
    An absorbed cancellation takes precedence and is re-raised once the thread has
    finished: the caller's task still cancels, which is ADR-0060's delivery half, and
    what is prevented is connection reuse rather than the cancellation itself.

    **The completion wait is submitted at most once** (#697): a copy that submitted a
    fresh one per cancellation would leave every earlier one running, because nothing
    can interrupt a thread parked in ``Event.wait`` before the worker sets it.

    Args:
        fn: The synchronous call to run.
        *args: Its positional arguments.

    Returns:
        Whatever ``fn`` returned.

    Raises:
        BaseException: Whatever ``fn`` raised, relayed once the thread has finished.
        CancelledError: If the awaiting task was cancelled, re-raised after the worker
            has physically returned.
    """
    done = threading.Event()
    outcome: list[T] = []
    failure: list[BaseException] = []

    def worker() -> None:
        try:
            outcome.append(fn(*args))
        except BaseException as exc:  # relayed once the thread has finished
            failure.append(exc)
        finally:
            done.set()

    loop = asyncio.get_running_loop()
    pending: asyncio.Future[Any] = loop.run_in_executor(None, worker)
    waiting: asyncio.Future[Any] | None = None
    cancellation: asyncio.CancelledError | None = None
    while not done.is_set():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError as exc:
            cancellation = exc
            if waiting is None:
                waiting = loop.run_in_executor(None, done.wait)
            pending = waiting
    if cancellation is not None:
        raise cancellation
    if failure:
        raise failure[0]
    return outcome[0]


class BookingStoreError(AssistantError):
    """The booking store could not do what it was asked.

    Attributes:
        may_have_committed: Whether the transaction may already have landed —
            ADR-0273 §2's commit boundary, read by the caller and turned into
            ``ClassifiedToolError(effect_may_have_committed=...)`` unchanged. It is
            ``False`` only where the fault fell **before** the commit or flush **and
            the rollback was confirmed**; it is ``True`` where the fault fell at or
            after the commit or flush itself, and **where the store cannot establish
            which side it fell on**, which is §2's conservative direction and arm 16's
            keyed-to-the-commit rule.
    """

    def __init__(self, message: str, *, may_have_committed: bool) -> None:
        """Record what failed and which side of the commit boundary it failed on.

        Args:
            message: Operator-facing Tier 2 text.
            may_have_committed: The boundary fact above. **Keyword-only and
                undefaulted**, for ``ClassifiedToolError``'s reason: both candidate
                defaults are wrong in a direction (ADR-0032 §2).
        """
        super().__init__(message)
        self.may_have_committed = may_have_committed


class SqliteBookingStore:
    """The provider's durable state: bounded records, and a count that only rises.

    ADR-0273 §2's *two* things, because one of them must be prunable and the other
    must not: a **booking record** carrying what the provider was asked and what it
    charged — the detail, which is the user's — and an advance of a **monotonic commit
    count**, a non-personal figure incremented on every committed booking and **never
    decremented**. Both survive a restart, and no operation of this store removes,
    amends or decrements the count.

    **The whole commit is one serialised, failure-atomic transaction, and the commit is
    all three of the record, the count and the pruning** (§2). They take effect together
    or not at all, and two commits never interleave: ``BEGIN IMMEDIATE`` takes the write
    lock up front so the read the prune depends on cannot be interleaved by another
    *process*, and an :class:`asyncio.Lock` closes the same window within one. So after
    any interruption a record is wholly present or wholly absent, the store reads back
    on the next start, and **the count equals the number of records ever inserted** —
    not the number still retained, which pruning lowers.

    **The retention bound is enforced at commit time *and* at open time**, and that is
    the waived-at-ratification item PR #2495 assigns to this lane: §2's obligation is
    that the store never retains more records than the configured bound, *whatever path
    it prunes on*. A bound lowered between two runs is exactly the case a commit-time-only
    prune leaves over-full until the next booking, which may never come.

    **It is an ordinary store of this deployment and invents no regime** (§2). It sits in
    the data directory, so ``ai-assistant-purge`` (ADR-0126, ADR-0153) destroys it with
    every other store; it owes exactly what every store's lane owes and nothing more.

    **Not ``@final``, and the exception is deliberate**, exactly as
    :class:`~ai_assistant.tools.connection_store.SqliteConnectionStore`'s is: §10's arms
    15 and 16 require a fault injected **before** the commit, **between each pair of the
    commit's sub-operations**, and **at or after** the commit itself, each asserted
    across a restart. A subclass that overrides one of :meth:`_insert`,
    :meth:`_advance`, :meth:`_prune` or :meth:`_flush` to raise is how a test reaches
    those points against the real implementation; the alternative is a duck-typed
    double, which would test a second store rather than this one. **No production
    subclass exists and none is expected.**

    **No busy timeout is set here, and that is the family's posture rather than this
    store's choice** (#564).
    """

    def __init__(self, *, path: Path | str, retained: int) -> None:
        """Open (or create) the booking store at ``path``, pruning it to its bound.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
                **Required, with no default**: durability is the whole reason this
                store exists — without it ``IRREVERSIBLE`` would be a claim about
                nothing — so a default would let the ordinary construction produce a
                store whose loss erases the act. It lives under ``Settings.data_dir``
                in a real deployment, which is the composition root's choice rather
                than this class's.
            retained: ADR-0273 §5's record bound, ``n >= 1``.

        Raises:
            BookingConfigurationError: If ``retained`` is outside §5's domain.
            BookingStoreError: If the database cannot be opened, initialised or pruned
                to its bound.
        """
        self._retained = _checked_retained(retained)
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    def __repr__(self) -> str:
        """Describe the store by its path and its bound, never by what it holds."""
        return f"{type(self).__name__}(path={self._path!r}, retained={self._retained})"

    @property
    def retained(self) -> int:
        """The record bound this store was opened with (ADR-0273 §2, §5)."""
        return self._retained

    def _setup(self) -> sqlite3.Connection:
        """Connect, create the schema, stamp the count, and prune to the bound."""
        try:
            conn = sqlite3.connect(self._path, check_same_thread=False)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # ``ValueError`` is named because a path carrying an embedded NUL raises it
            # out of the driver rather than a ``sqlite3.Error`` (#238).
            msg = f"failed to open the booking store at {self._path!r}: {exc}"
            raise BookingStoreError(msg, may_have_committed=False) from exc
        try:
            # Restricted *before* the first statement: SQLite copies the database
            # file's mode onto every rollback journal it creates, so a journal opened
            # while the file still carried the process umask is world-readable too, and
            # an interrupted write leaves it on disk holding Tier 1 pages (#489).
            self._restrict_permissions()
            with conn:  # commits on success, rolls back on any exception
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(_META_SCHEMA)
                # **Both metadata rows and the table's prior existence are read
                # *before* anything is written**, because "is this store new?" is a
                # question about the state the open found and not about the state the
                # open leaves. Reading the version first and writing it immediately —
                # which is what this used to do — made the answer to the *second*
                # question depend on the first write, so a store that had lost only its
                # version row was mistaken for a new one and its surviving count
                # overwritten.
                version = self._meta(conn, _SCHEMA_VERSION_KEY)
                count = self._meta(conn, _COMMIT_COUNT_KEY)
                established = self._table_exists(conn)
                conn.execute(_BOOKINGS_SCHEMA)
                self._initialise(conn, version=version, count=count, established=established)
                # ADR-0273 §2's bound, enforced on the open path as well as the commit
                # path, so that a bound lowered between two runs is honoured at once.
                self._prune(conn)
        except BookingStoreError:
            conn.close()
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to initialise the booking store at {self._path!r}: {exc}"
            raise BookingStoreError(msg, may_have_committed=False) from exc
        return conn

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case rather than a fault. A *symlink* under a
        sidecar's name is skipped rather than followed: ``chmod`` follows links, so
        restricting one would silently narrow a file that holds none of this store's
        data. A no-op in memory, where there is no file to restrict.

        **Duplicated from the other SQLite stores on purpose** (#506).
        """
        if self._path == ":memory:":
            return
        database = Path(self._path)
        database.chmod(_OWNER_ONLY)
        for suffix in _SIDECARS:
            sidecar = database.with_name(database.name + suffix)
            if sidecar.is_symlink():
                continue
            with contextlib.suppress(FileNotFoundError):
                sidecar.chmod(_OWNER_ONLY)

    @staticmethod
    def _meta(conn: sqlite3.Connection, key: str) -> str | None:
        """The value stored under ``key``, or ``None``.

        Args:
            conn: The store's connection.
            key: The meta key.

        Returns:
            The stored text, or ``None`` where the key is absent.

        Raises:
            BookingStoreError: If the key is stored more than once, which is a corrupt
                store rather than a value to pick from.
        """
        rows = conn.execute(_READ_META, (key,)).fetchall()
        if not rows:
            return None
        if len(rows) > 1:  # pragma: no cover — ``key`` is the table's primary key
            msg = f"the booking store at {conn!r} holds {len(rows)} {key} rows; it is corrupt"
            raise BookingStoreError(msg, may_have_committed=False)
        return str(rows[0][0])

    @staticmethod
    def _table_exists(conn: sqlite3.Connection) -> bool:
        """Whether the ``bookings`` table was already there when this open began.

        Read **before** ``CREATE TABLE IF NOT EXISTS`` runs, which is the whole point:
        afterwards the answer is always yes. A table present while **both** metadata
        rows are absent is a store whose ``meta`` was emptied, not a new one — the two
        are written in one transaction, so no interruption can produce that state.

        Args:
            conn: The store's connection.

        Returns:
            Whether the table existed.
        """
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'bookings'"
        ).fetchall()
        return bool(rows)

    def _initialise(
        self,
        conn: sqlite3.Connection,
        *,
        version: str | None,
        count: str | None,
        established: bool,
    ) -> None:
        """Stamp a genuinely new store; refuse an established one that is incomplete.

        **ADR-0273 §2's count is what carries the act's irreversibility, so a silent
        reset is the one failure this store must not have.** That clause requires the
        count to equal *"the number of records ever inserted"* and says **no** operation
        of this provider decrements it — and a store whose count row has gone missing
        cannot be reconstructed from the rows it still holds, because pruning has already
        removed some of them. Writing ``"0"`` there would therefore **decrement** the
        figure and make ``IRREVERSIBLE`` a false claim about every booking the store had
        already forgotten the detail of.

        So the stamp is conditional on the store being **genuinely new**, and **exactly
        two complete states are accepted**: no table and neither metadata row, which is
        a new store; or the table beside **both** rows, which is an established one.
        Every third shape is refused — a surviving count with its table dropped is a
        store that would report bookings it retains no record of *and no pruning
        explains*, which §2's *"both survive a restart"* forbids as squarely as a reset
        count does. Newness is decided from the whole state the open found, and the
        incomplete shape is the one that matters: any part surviving alone is a store
        somebody edited, and supplying the missing part would either reset a surviving
        count, bless a version this code never stamped, or hand back an empty record set
        beside a count that says otherwise. The rows are written in **one** transaction with the
        table, so no interruption of this code can produce an incomplete pair.

        Args:
            conn: The store's connection, inside the setup transaction.
            version: The ``schema_version`` row as the open found it, or ``None``.
            count: The ``commit_count`` row as the open found it, or ``None``.
            established: Whether the ``bookings`` table was already there.

        Raises:
            BookingStoreError: If the store is established and its metadata is
                incomplete, or if the stored version is not one this code understands.
        """
        if version is None and count is None and not established:
            conn.execute(_WRITE_META, (_SCHEMA_VERSION_KEY, str(_SCHEMA_VERSION)))
            conn.execute(_WRITE_META, (_COMMIT_COUNT_KEY, "0"))
            return
        absent = [
            what
            for what, present in (
                (_SCHEMA_VERSION_KEY, version is not None),
                (_COMMIT_COUNT_KEY, count is not None),
                ("records table", established),
            )
            if not present
        ]
        if absent:
            msg = (
                f"the booking store at {self._path!r} is an established store holding no "
                f"{' and no '.join(absent)}; its durable state is two things that survive "
                f"a restart together, the commit count only rises, and neither can be "
                f"reconstructed from what is left (ADR-0273 §2) — so the store is corrupt "
                f"and is not opened rather than repaired into one that reads empty"
            )
            raise BookingStoreError(msg, may_have_committed=False)
        if version is not None:
            # ``absent`` being empty already establishes this; the test is written out
            # so the narrowing is the code's rather than a reader's.
            self._checked_version(version)
        # **And the count is checked here as well as on every read**, so a store whose
        # figure was edited below the records it holds is refused at the restart rather
        # than at the first read — which is where an operator meets it, and before any
        # commit can write a figure lower still. The rows counted are the pre-prune
        # ones, which is the right floor: every one of them was inserted.
        self._read_count_sync(conn)

    def _checked_version(self, stored: str) -> None:
        """Refuse a labelled schema this code cannot read (ADR-0049 §1).

        Args:
            stored: The ``schema_version`` row's value.

        Raises:
            BookingStoreError: If it is not a version this code understands.
        """
        try:
            version = int(stored)
        except ValueError as exc:
            msg = (
                f"the booking store at {self._path!r} holds a non-numeric schema_version {stored!r}"
            )
            raise BookingStoreError(msg, may_have_committed=False) from exc
        if version != _SCHEMA_VERSION:
            msg = (
                f"the booking store at {self._path!r} has schema_version={version}, but "
                f"this code supports only version {_SCHEMA_VERSION}; refusing to open it "
                f"rather than read it blindly"
            )
            raise BookingStoreError(msg, may_have_committed=False)

    # --- the commit, and the boundary it is classified against -----------

    async def commit(self, record: Mapping[str, FrozenJson], *, confirmed: bool = True) -> None:
        """Insert ``record``, advance the count and prune, as one transaction (§2).

        Args:
            record: What the provider was asked and what it charged. Serialised to JSON
                and rebuilt on every read, which is how a detached snapshot is obtained
                here without a copy step to forget.
            confirmed: Whether the caller may learn the transaction's outcome.
                ``False`` is **ADR-0273 §4's configured uncertainty**: the transaction
                is committed and its outcome is then reported as unobtainable, so a
                caller's ``effect_may_have_committed=True`` is *true of what it did*
                (§10 arm 19). It is the one way this provider reaches the state §4
                requires it to be able to produce, and it is a **fault at the commit
                boundary** rather than a raise after a return — *"an arm reaching
                ``INDETERMINATE`` through a provider that could not have committed
                demonstrates a pessimistic misreport rather than an uncertain effect"*.

        Raises:
            BookingStoreError: If the transaction failed, carrying which side of the
                commit boundary it failed on; or, where ``confirmed`` is ``False``,
                after it landed, carrying ``may_have_committed=True``.
        """
        serialised = json.dumps(dict(record), sort_keys=True, separators=(",", ":"))
        async with self._lock:
            await _run_to_completion(self._commit_sync_confirmed, serialised, confirmed)

    def _commit_sync_confirmed(self, record: str, confirmed: bool) -> None:
        """:meth:`_commit_sync` with both arguments positional, for the worker.

        :func:`_run_to_completion` forwards ``*args`` and takes no keywords, so the
        keyword-only form below is reached through this one rather than by widening the
        helper every store shares.

        Args:
            record: The serialised booking record.
            confirmed: Whether the outcome of the commit may be learned (§4).
        """
        self._commit_sync(record, confirmed=confirmed)

    def _commit_sync(self, record: str, *, confirmed: bool = True) -> None:
        """Run the one transaction, classified against ADR-0273 §2's commit boundary.

        **The boundary is the commit or flush and never the first sub-operation** (arm
        16). A fault falling before it whose rollback the store **confirms** reports
        ``may_have_committed=False``; a fault at or after the commit itself reports
        ``True``; and where the rollback could not be confirmed — so the store cannot
        establish which side the fault fell on — ``True``, because §2's direction is
        that *"a booking that may have happened is never recorded as certainly
        failed"*.

        Args:
            record: The serialised booking record.
            confirmed: Whether the outcome of the commit may be learned (§4).

        Raises:
            BookingStoreError: On any backend or injected fault.
        """
        conn = self._conn
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            msg = f"failed to open the booking commit: {exc}"
            raise BookingStoreError(msg, may_have_committed=False) from exc
        try:
            # **The count is read before the record is inserted, and written after.**
            # Its floor is the retained cardinality (§2), and between the insert and the
            # increment the store is legitimately one row ahead of the figure — so a
            # read taken there would report the very inconsistency this transaction is
            # in the middle of removing. The *write* order is unchanged, which is what
            # §10 arm 16's injection points are stated over.
            count = self._read_count_sync(conn)
            self._insert(conn, record)
            self._advance(conn, count)
            self._prune(conn)
        except BaseException as exc:
            rolled_back = True
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:  # pragma: no cover — a rollback that cannot be run
                rolled_back = False
            if not isinstance(exc, Exception):
                # A cancellation is ADR-0060 §1's to propagate unchanged, after the
                # transaction is released.
                raise
            msg = f"the booking commit failed before it landed: {exc}"
            raise BookingStoreError(msg, may_have_committed=not rolled_back) from exc
        try:
            self._flush(conn, confirmed=confirmed)
        except BookingStoreError:
            raise
        except Exception as exc:
            # **At or after the boundary, so ``True``** (§2, §10 arm 16). Anything that
            # escapes from here escapes from a point at which the ``COMMIT`` may already
            # have landed, and the store cannot establish which side it fell on — which
            # is precisely the case §2's conservative direction is written for. A
            # ``BaseException`` (a cancellation) still propagates unchanged, because
            # ADR-0060 §1's clause is unconditional.
            msg = f"the booking commit's outcome could not be established: {exc}"
            raise BookingStoreError(msg, may_have_committed=True) from exc

    def _insert(self, conn: sqlite3.Connection, record: str) -> None:
        """Append the booking record. Overridden by §10 arm 16's fault injection."""
        conn.execute(_INSERT_BOOKING, (record,))

    def _advance(self, conn: sqlite3.Connection, count: int) -> None:
        """Advance the commit count by one, inside the same transaction (§2).

        **Never outside it**: §2 names *"a count incremented outside the transaction
        that inserts the record"* as not an implementation of the clause.

        Args:
            conn: The store's connection, inside the commit's transaction.
            count: The figure as it stood **before** this commit's insert, read by
                :meth:`_commit_sync` while the store was still consistent.
        """
        conn.execute(_WRITE_META, (_COMMIT_COUNT_KEY, str(count + 1)))

    def _prune(self, conn: sqlite3.Connection) -> None:
        """Drop every record past the configured bound, oldest first (§2).

        **The count is untouched**: pruning removes *detail about* bookings and never
        the fact of one, which is why §2 states the act's irreversibility over the
        count rather than over the record it outlives.
        """
        conn.execute(_PRUNE_BOOKINGS, (self._retained,))

    def _flush(self, conn: sqlite3.Connection, *, confirmed: bool = True) -> None:
        """Commit the transaction — ADR-0273 §2's boundary itself.

        A fault here is reported as one that **may** have committed, because the
        statement may have landed before the failure was observed. Overridden by §10
        arm 16's at-or-after injection.

        Args:
            conn: The store's connection, with the transaction open on it.
            confirmed: Where ``False``, the ``COMMIT`` is executed and its outcome is
                then reported as unobtainable — ADR-0273 §4's configured uncertainty,
                which is a fault **at** the boundary and not one after it.

        Raises:
            BookingStoreError: Carrying ``may_have_committed=True``, on a backend fault
                at the boundary or on §4's configured uncertainty.
        """
        try:
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            msg = f"the booking commit could not be confirmed: {exc}"
            raise BookingStoreError(msg, may_have_committed=True) from exc
        if not confirmed:
            msg = "the booking commit was made and its outcome could not be obtained (ADR-0273 §4)"
            raise BookingStoreError(msg, may_have_committed=True)

    # --- the reads -------------------------------------------------------

    async def records(self) -> tuple[Mapping[str, FrozenJson], ...]:
        """Every retained booking record, oldest first.

        Returns:
            The records, rebuilt from their stored JSON so nothing shares an object
            graph with the store.

        Raises:
            BookingStoreError: If the store could not be read.
        """
        async with self._lock:
            return await _run_to_completion(self._read_records_sync)

    async def commit_count(self) -> int:
        """How many bookings this store has ever committed (§2).

        **It only rises.** No operation of this provider removes, amends or decrements
        it, and no retention rule, bound or pruning reaches it.

        Args:
            conn: The connection to read through. Passed rather than taken from
                ``self``, because this also runs during :meth:`_setup` — before
                ``self._conn`` is assigned at all.

        Returns:
            The count.

        Raises:
            BookingStoreError: If the store could not be read.
        """
        async with self._lock:
            return await _run_to_completion(self._read_count_sync, self._conn)

    def _read_records_sync(self) -> tuple[Mapping[str, FrozenJson], ...]:
        """Every retained record, decoded, oldest first.

        **The decode happens inside this store's error boundary and not above it.** A
        row that is not a JSON object — malformed text, or a bare scalar — is a corrupt
        store, which is this layer's fault to report rather than a ``JSONDecodeError``
        escaping past its own seam (#238's rule, one store along). Callers are promised
        a mapping per record and a :class:`BookingStoreError` otherwise, and that
        promise is kept here.

        Returns:
            The records, rebuilt from their stored JSON so nothing shares an object
            graph with the store.

        Raises:
            BookingStoreError: If the store could not be read, or holds a row this
                code cannot read as a booking record.
        """
        try:
            rows = self._conn.execute(_READ_BOOKINGS).fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to read the booking store: {exc}"
            raise BookingStoreError(msg, may_have_committed=False) from exc
        decoded: list[Mapping[str, FrozenJson]] = []
        for row in rows:
            try:
                record = json.loads(str(row[0]))
            except (RecursionError, ValueError) as exc:
                # ``RecursionError`` is named beside ``ValueError`` because the decoder
                # raises it rather than a ``JSONDecodeError`` on a deeply nested
                # document — and it is **not** a ``ValueError``, so a clause naming only
                # that one lets a corrupt row escape as a raw builtin past this layer's
                # error boundary. It is a resource limit reached while reading the
                # store's own bytes, which is exactly what this promise covers.
                msg = (
                    f"the booking store at {self._path!r} holds a row that is not "
                    f"readable JSON; the store is corrupt. The row is not rendered."
                )
                raise BookingStoreError(msg, may_have_committed=False) from exc
            if not isinstance(record, dict):
                msg = (
                    f"the booking store at {self._path!r} holds a row that is not a "
                    f"booking record; the store is corrupt. The row is not rendered."
                )
                raise BookingStoreError(msg, may_have_committed=False)
            decoded.append(record)
        return tuple(decoded)

    def _read_count_sync(self, conn: sqlite3.Connection) -> int:
        """The stored commit count, as a number.

        **Parsed inside the boundary too**, for :meth:`_read_records_sync`'s reason: a
        ``commit_count`` the store cannot read as an integer is a corrupt store, not a
        ``ValueError`` for a caller to classify. A **negative** one is refused as well,
        because §2 states the figure as one that only rises.

        Args:
            conn: The connection to read through. Passed rather than taken from
                ``self``, because this also runs during :meth:`_setup` — before
                ``self._conn`` is assigned at all.

        Returns:
            The count.

        Raises:
            BookingStoreError: If the store could not be read, holds no commit count at
                all, or holds one this code cannot read.
        """
        try:
            stored = self._meta(conn, _COMMIT_COUNT_KEY)
        except sqlite3.Error as exc:
            msg = f"failed to read the booking commit count: {exc}"
            raise BookingStoreError(msg, may_have_committed=False) from exc
        if stored is None:
            # **Never ``0``** (§2). :meth:`_initialise` writes the row inside the setup
            # transaction, before any reader of this store can run, so an absent row
            # here is a row something *removed* while the store was open — and reading
            # it as zero would let the next commit write ``1`` over a count of two. That
            # is the reset the figure exists to make impossible, reached without a
            # restart, so reopen-time validation cannot catch it and this must.
            msg = (
                f"the booking store at {self._path!r} holds no commit count; the figure "
                f"only rises and cannot be reconstructed from the records still retained "
                f"(ADR-0273 §2), so the store is corrupt"
            )
            raise BookingStoreError(msg, may_have_committed=False)
        try:
            count = int(stored)
        except ValueError as exc:
            msg = (
                f"the booking store at {self._path!r} holds a non-numeric commit count "
                f"{stored!r}; the store is corrupt"
            )
            raise BookingStoreError(msg, may_have_committed=False) from exc
        if count < 0:
            msg = (
                f"the booking store at {self._path!r} holds a negative commit count "
                f"{count}; the figure only rises (ADR-0273 §2), so the store is corrupt"
            )
            raise BookingStoreError(msg, may_have_committed=False)
        # **The count is provably at least the number of rows still retained** (§2).
        # That section fixes it as *"the number of records ever inserted — not the number
        # still retained, which pruning lowers"*, so the retained cardinality is a floor
        # the figure can never be under. A count below it is corrupt whatever its sign:
        # a positive one edited downwards passes every other test here and then lets the
        # next commit write a figure lower than the bookings the store already holds.
        retained = self._retained_rows(conn)
        if count < retained:
            msg = (
                f"the booking store at {self._path!r} holds a commit count of {count} "
                f"beside {retained} retained record(s); the count is the number ever "
                f"inserted and pruning only lowers the records (ADR-0273 §2), so a count "
                f"below them is corrupt"
            )
            raise BookingStoreError(msg, may_have_committed=False)
        return count

    def _retained_rows(self, conn: sqlite3.Connection) -> int:
        """How many booking records the store still holds.

        Read for :meth:`_read_count_sync`'s floor and for nothing else. Cheap by
        construction: §5's bound is a small integer, so this counts a bounded table.

        Args:
            conn: The connection to read through, for :meth:`_read_count_sync`'s reason.

        Returns:
            The row count.

        Raises:
            BookingStoreError: If the store could not be read.
        """
        try:
            rows = conn.execute("SELECT COUNT(*) FROM bookings").fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to read the booking store: {exc}"
            raise BookingStoreError(msg, may_have_committed=False) from exc
        return int(rows[0][0]) if rows else 0

    def close(self) -> None:
        """Release the connection (ADR-0042 §2). Safe to call more than once."""
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()


# --- ADR-0148 §6's four conditions, over a destination nothing reaches ----


def _refuse(kind: ToolFailureKind, message: str, *, committed: bool = False) -> ClassifiedToolError:
    """Build a failure this provider classified itself, carrying §6's statement.

    ADR-0273 §6: *"on a failure the provider itself classifies, the statement rides in
    that failure's own message"*. ``ToolResult`` refuses a non-``SUCCEEDED`` result
    carrying an ``output``, and a ``FAILED`` or ``INDETERMINATE`` step records a
    ``failure`` and no ``output`` (ADR-0039 §2), so the ``message`` — operator-facing
    **Tier 2** text — is where the statement can ride. **The obligation reaches no
    outcome the seam synthesised**: a deadline the seam completes and an escaping error
    it classifies carry no provider-authored text and are not required to.

    **No message here interpolates an argument value.** A value is untrusted input that
    could carry Tier 1 data, and nothing this provider was handed reaches the failure
    text or a log.

    Args:
        kind: The tool's own classification, from ``ToolFailureKind`` except
            ``TIMED_OUT``, which ADR-0032 §3 reserves to the seam's own deadline.
        message: The operator-facing explanation, to which the notice is appended.
        committed: ADR-0032 §2's fact the seam rules on — whether this call's effect
            may already have landed. Keyword-only and defaulted ``False`` only because
            every refusal *before* a commit shares that answer; the commit path passes
            the store's own verdict explicitly.

    Returns:
        The error to raise.
    """
    return ClassifiedToolError(
        ToolFailure(kind=kind, message=f"{message} {SIMULATION_NOTICE}"),
        effect_may_have_committed=committed,
    )


@final
class BoundConnection:
    """ADR-0148 §6's four pre-transmit conditions, run before this provider answers.

    ADR-0273 §3 requires them *whole*, **over a destination nothing is transmitted
    to**, and says why: *"they are what a real booking provider's safety rests on, and
    a walkthrough that skipped them would demonstrate a path the first real provider
    does not take. What M33 needs to see is the binding refusing a re-provisioned
    connection, and that refusal is reachable only because they run."*

    The four, in the order they are decidable:

    1. the **connection reference** the binding carries names the record this
       registration consults — compared **before** the record is read, because the
       record is read *by* the registration's reference. Without it, a binding for
       account B's connection is checked against account A's record: where the two
       share an identity, both record checks pass;
    2. the **transport endpoint** the binding carries is the one this integration is
       configured to use, compared as text so two spellings of one host stay two
       endpoints;
    3. the bound reference is **connectable** — its record is present, ``ACTIVE`` and
       names a credential slot — and the credential is read **under the slot that
       record names**, with no ``await`` between the two; and
    4. the **account identity currently recorded** for that reference equals the
       identity the binding carries.

    A read that cannot be answered across the credential read is treated as a
    **changed** one (ADR-0148 §6's discard clause), because the credential is already
    in hand at that point.

    **The credential is read and not used** (ADR-0273 §1, ADR-0260 §12). The user
    provisioned the connection by ADR-0149 §4's explicit act, supplying an identity and
    a credential the simulated provider **accepts and does not use** — which is a fact
    about the far end and changes nothing about the conditions on this side. That read
    is why both declarations state ``reads=(SECRET, …)``.

    **This is a third statement of these conditions in this subsystem and not a
    shared one**, and the reason is mechanical: the two that exist are private methods
    of :class:`~ai_assistant.tools.egress.SmtpEgressTransport` and
    :class:`~ai_assistant.tools.egress.HttpsEgressTransport`, interleaved with an
    exchange this provider has none of, and extracting a shared one would edit the
    **designated** egress seam (ADR-0154 §1) for a component that opens nothing. The
    cost is stated rather than hidden.

    **It holds no transport and there is no parameter through which one could arrive**
    (§3), so the injection route by which the real and the fake transport both reach
    production code does not reach this provider at all.
    """

    __slots__ = ("_records", "_registration", "_secrets")

    def __init__(
        self,
        *,
        registration: EgressRegistration,
        records: ConnectionRecords,
        secrets: Secrets,
    ) -> None:
        """Bind the registration and the two faces the conditions are read through.

        Args:
            registration: This tool's registration — the connection reference and the
                configured endpoint, as the binding seam holds them. The **same
                object** the seam's table holds, so the reference a record is read by
                and the endpoint a binding is compared against cannot come apart.
            records: The connection store, read once before the credential read and
                once after it (ADR-0148 §6). The **same** store object the provisioner
                writes, so a provisioning act cannot commit a revision this path could
                not yet see.
            secrets: The ``INTEGRATION``-scoped **reading** face (ADR-0125 §8). Never a
                ``SecretStore``: a holder handed the writing face could delete the
                credential it reads.
        """
        self._registration = registration
        self._records = records
        self._secrets = secrets

    async def check(self, binding: EgressBinding, *, origin: str) -> None:
        """Run the four conditions, or refuse the call.

        Args:
            binding: The egress binding the authorising decision carries. The account
                and the endpoint are taken from here and re-derived nowhere (ADR-0148
                §4's third clause).
            origin: The origin the **ruled** call carries, read off the revalidated,
                detached arguments. Compared here rather than trusted, exactly as
                :meth:`~ai_assistant.tools.egress.HttpsEgressTransport._pinned_origin`
                compares one.

        Raises:
            ClassifiedToolError: If any condition does not hold. ``NOT_AUTHORISED``
                rather than a transport error, because this provider classifies its own
                failures and §6 puts the simulation statement in the message of each —
                and because a call bound somewhere this provider is not registered is
                not a repeat that could plausibly succeed.
        """
        self._pinned(binding, origin)
        before = await self._records.latest(self._registration.reference)
        slot = self._slot_of(before, binding)
        credential = await self._secrets.get(slot)
        self._unchanged(await self._reread(), before, binding)
        if credential is None:
            msg = (
                f"{self._registration.tool_id}: the connection record for "
                f"{self._registration.reference!r} names a credential slot the keyring "
                f"holds nothing under; re-run the provisioning act."
            )
            raise _refuse(ToolFailureKind.NOT_AUTHORISED, msg)

    def _pinned(self, binding: EgressBinding, origin: str) -> None:
        """Conditions 1 and 2, plus the ruled origin, decided before any read.

        Raises:
            ClassifiedToolError: If the binding names another connection, another
                endpoint, or an origin other than the one this integration is
                registered for.
        """
        if binding.account.reference != self._registration.reference:
            msg = (
                f"{self._registration.tool_id}: the binding names a connection this "
                f"integration is not registered for, so the record consulted would not "
                f"be the one the ruling was taken over (ADR-0148 §6). It is registered "
                f"for {self._registration.reference!r}."
            )
            raise _refuse(ToolFailureKind.NOT_AUTHORISED, msg)
        if binding.transport_endpoint != self._registration.transport_endpoint:
            msg = (
                f"{self._registration.tool_id}: the bound transport endpoint is not the "
                f"one this integration is configured to use, so the call would not be to "
                f"the service the ruling named (ADR-0148 §6)."
            )
            raise _refuse(ToolFailureKind.NOT_AUTHORISED, msg)
        if origin != self._registration.transport_endpoint:
            msg = (
                f"{self._registration.tool_id}: the origin this call was ruled on is not "
                f"the one this integration is registered for, so it would answer for a "
                f"recipient no grant covered (ADR-0148 §6, ADR-0273 §3)."
            )
            raise _refuse(ToolFailureKind.NOT_AUTHORISED, msg)

    def _slot_of(self, stored: StoredEntry | None, binding: EgressBinding) -> SecretName:
        """Conditions 3 and 4: connectability and the recorded identity.

        **Synchronous, and that is the point.** ADR-0148 §6 makes the check and the
        credential read one step — no ``await`` occurs between reading the identity,
        state and slot recorded for the bound reference and calling ``Secrets.get`` for
        **that** slot — so everything this decides has to be decidable without
        suspending.

        Args:
            stored: The record read for the bound reference, or ``None``.
            binding: The authorised binding.

        Returns:
            The slot the record names, which is never carried in the binding and is
            therefore never compared against one.

        Raises:
            ClassifiedToolError: If the reference is not connectable, or the identity
                currently recorded for it is not the bound one.
        """
        entry: ConnectionEntry | None = None if stored is None else stored.entry
        if entry is None or entry.state is not ProvisioningState.ACTIVE or entry.slot is None:
            state = "absent" if entry is None or entry.state is None else entry.state.value
            msg = (
                f"{self._registration.tool_id}: connection "
                f"{self._registration.reference!r} is not connectable — its record is "
                f"{state}. Nothing is asked under it; re-running the provisioning act is "
                f"the remedy (ADR-0148 §6)."
            )
            raise _refuse(ToolFailureKind.NOT_AUTHORISED, msg)
        if entry.identity != binding.account.identity:
            msg = (
                f"{self._registration.tool_id}: connection "
                f"{self._registration.reference!r} is recorded for a different account "
                f"than the ruling was taken over, so nothing is asked under it "
                f"(ADR-0148 §6)."
            )
            raise _refuse(ToolFailureKind.NOT_AUTHORISED, msg)
        return entry.slot

    async def _reread(self) -> StoredEntry | None:
        """Re-read the record, treating an unanswerable read as a changed one.

        The store's own failure is **not** propagated here, unlike the first read:
        ADR-0148 §6's discard clause says *"a read that cannot be answered is treated as
        a changed one"*, because the credential is already in hand at this point.

        Returns:
            The record, or ``None`` where the read found nothing or could not be
            answered.
        """
        try:
            return await self._records.latest(self._registration.reference)
        except ConnectionStoreError:
            return None

    def _unchanged(
        self, after: StoredEntry | None, before: StoredEntry | None, binding: EgressBinding
    ) -> None:
        """Refuse a record that moved across the credential read (ADR-0148 §6).

        Raises:
            ClassifiedToolError: If the record is now absent, is no longer ``ACTIVE``,
                names another identity or slot, or has a different revision.
        """
        # Named ``first``/``second`` and deliberately not ``now``: this provider reads
        # **no** clock, and §10 arm 21 asserts that mechanically over this module's own
        # names — a local called ``now`` would make that check report a clock read that
        # is not there.
        first: ConnectionEntry | None = None if before is None else before.entry
        second: ConnectionEntry | None = None if after is None else after.entry
        if (
            second is None
            or first is None
            or second.state is not ProvisioningState.ACTIVE
            or second.revision != first.revision
            or second.identity != first.identity
            or second.slot != first.slot
            or second.identity != binding.account.identity
        ):
            msg = (
                f"{self._registration.tool_id}: the connection record for "
                f"{self._registration.reference!r} moved across the credential read, so "
                f"the account this call would be made under is not the one the ruling "
                f"was taken over (ADR-0148 §6)."
            )
            raise _refuse(ToolFailureKind.NOT_AUTHORISED, msg)


# --- reading a call's arguments, against the declaration's own schema -----


def _arguments(
    definition: ToolDefinition, parameters: Mapping[str, FrozenJson]
) -> tuple[str, date]:
    """Read the origin and the day, validated against the declaration's own schema.

    ADR-0273 §2: the provider *"validates a booking's arguments against the
    declaration's own ``parameters_schema`` **before it writes**, and persists only the
    fields that schema names"*, so that nothing a caller supplied off-schema is ever
    stored. :func:`~ai_assistant.core.types.parameter_violations` is the tree's one
    statement of that evaluation (ADR-0145 §2) and is used rather than re-stated:
    ``parameters_schema`` is carried but not enforced at selection (ADR-0016 §7), so
    the callable makes its own behaviour match its own declaration.

    **The message names the count and never a key or a value** (ADR-0145 §7, ADR-0152
    §11): a key a caller chose is content, and this text is Tier 2.

    Args:
        definition: The declaration this call was bound to.
        parameters: The call's arguments, revalidated and detached by the seam.

    Returns:
        The ruled origin and the day, in that order.

    Raises:
        ClassifiedToolError: If the arguments do not satisfy the schema.
    """
    violations = parameter_violations(definition.parameters_schema, parameters)
    if violations:
        msg = (
            f"{definition.id}: this call's arguments do not satisfy the tool's own "
            f"declared schema in {len(violations)} respect(s), so nothing was asked and "
            f"nothing was written. Neither the offending keys nor their values are "
            f"rendered (ADR-0145 §7)."
        )
        raise _refuse(ToolFailureKind.INVALID_REQUEST, msg)
    origin = parameters[ORIGIN_ARGUMENT]
    day = parameters[DATE_ARGUMENT]
    if not isinstance(origin, str) or not isinstance(day, str):  # pragma: no cover — schema-refused
        msg = f"{definition.id}: this call's arguments are not the two strings it declares."
        raise _refuse(ToolFailureKind.INVALID_REQUEST, msg)
    try:
        return origin, date.fromisoformat(day)
    except ValueError as exc:
        msg = (
            f"{definition.id}: the day this call names is not an ISO-8601 calendar date, "
            f"so nothing was asked and nothing was written. The value is not rendered."
        )
        raise _refuse(ToolFailureKind.INVALID_REQUEST, msg) from exc


# --- the two callables ---------------------------------------------------


@final
class SimulatedAvailabilityRead:
    """The availability read's callable: it answers, and performs nothing.

    Structurally an
    :class:`~ai_assistant.tools.invocation.EgressToolImplementation`, so the pair is
    the shape ADR-0029 §1 registers and the binding the ruling fixed reaches it through
    the invocation seam rather than by an ambient read.

    **Every answer comes from the catalogue** (ADR-0273 §5) — no clock, no random
    source, no file it was not configured with and no network — so one configuration
    answers identically on every call and across a restart (§10 arm 21).
    """

    __slots__ = ("_catalogue", "_connection")

    def __init__(self, *, connection: BoundConnection, catalogue: BookingCatalogue) -> None:
        """Bind the four conditions and the configuration this read answers from.

        Args:
            connection: ADR-0148 §6's conditions for this registration.
            catalogue: What the deployment configured (ADR-0273 §5).
        """
        self._connection = connection
        self._catalogue = catalogue

    async def invoke_bound(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,  # noqa: ARG002 — NATURAL, so the key is always None
        egress_binding: EgressBinding,
    ) -> FrozenJson:
        """Answer whether the day is available, and at what price.

        Args:
            parameters: The call's arguments, revalidated and detached (ADR-0029 §2).
            idempotency_key: Always ``None`` — the declaration is
                ``Idempotency.NATURAL``, so no key is ever derived (ADR-0016 §4).
            egress_binding: The binding the ruling fixed.

        Returns:
            An object carrying the day, whether it is available, the quoted price and
            its currency **where it is**, and ADR-0273 §6's statement. **An unavailable
            day carries no price keys at all**, so ADR-0267 §4's mint yields no quote
            for it rather than a repaired one — which is the true answer, because an
            unavailable day is quoted nothing.

        Raises:
            ClassifiedToolError: If the arguments do not satisfy the schema, or if any
                of ADR-0148 §6's four conditions does not hold.
        """
        origin, day = _arguments(BOOKING_AVAILABILITY, parameters)
        await self._connection.check(egress_binding, origin=origin)
        if not self._catalogue.available(day):
            return {
                DATE_ARGUMENT: day.isoformat(),
                AVAILABLE_KEY: False,
                SIMULATION_KEY: SIMULATION_NOTICE,
            }
        return {
            DATE_ARGUMENT: day.isoformat(),
            AVAILABLE_KEY: True,
            PRICE_AMOUNT_KEY: str(self._catalogue.price_amount),
            PRICE_CURRENCY_KEY: self._catalogue.price_currency,
            SIMULATION_KEY: SIMULATION_NOTICE,
        }


@final
class SimulatedBookingAct:
    """The booking act's callable: it commits once, charges, and reports what it charged.

    **The durable effect is what makes ``IRREVERSIBLE`` a claim about something**
    (ADR-0273 §2). An implementation returning configured JSON and changing no state
    would satisfy every other arm while reproducing neither the double booking nor the
    failed cancellation the walkthrough exists to demonstrate.

    **Nothing fallible runs after the commit** (§2). The output is composed from values
    this object already holds — the day it was given and the charge it was configured
    with — so an escaping exception after a committed append is a defect of this class
    and not a state the clause admits. The one raise that *follows* a landed
    transaction is the store's own, **at** the commit boundary, which is §4's
    configured uncertainty and is classified as such.

    **It deduplicates nothing**, which is exactly what ``Idempotency.NONE`` declares:
    two separately authorised calls carrying identical arguments append two records.
    ADR-0259 §2's effect claim is the only thing standing between a replan and a second
    booking, and that is the guarantee M33 exists to demonstrate.
    """

    __slots__ = ("_catalogue", "_connection", "_store")

    def __init__(
        self,
        *,
        connection: BoundConnection,
        catalogue: BookingCatalogue,
        store: SqliteBookingStore,
    ) -> None:
        """Bind the conditions, the configuration and the durable state.

        Args:
            connection: ADR-0148 §6's conditions for this registration.
            catalogue: What the deployment configured (ADR-0273 §5).
            store: The provider's durable state (§2), under the deployment's data
                directory.
        """
        self._connection = connection
        self._catalogue = catalogue
        self._store = store

    async def invoke_bound(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,  # noqa: ARG002 — NONE, so no key is ever derived
        egress_binding: EgressBinding,
    ) -> FrozenJson:
        """Book the day, or refuse it before anything is written.

        The order is ADR-0273 §2's: **every** refusal decidable without writing runs
        first — the schema, the four conditions, the availability — so a booking this
        provider refuses commits none of the three, *"no record, no advance and no
        pruning"*. A provider that advanced the count and then refused would have
        falsified the very figure §2 rests the act's irreversibility on.

        Args:
            parameters: The call's arguments, revalidated and detached (ADR-0029 §2).
            idempotency_key: Always ``None`` — the declaration is ``Idempotency.NONE``,
                because this provider deduplicates nothing (ADR-0016 §4, ADR-0029 §5).
            egress_binding: The binding the ruling fixed.

        Returns:
            An object carrying the day, that it was booked, the amount charged and its
            currency, and ADR-0273 §6's statement.

        Raises:
            ClassifiedToolError: If the arguments do not satisfy the schema, if any of
                ADR-0148 §6's four conditions does not hold, if the day is unavailable —
                each ``effect_may_have_committed=False``, leaving no record and no
                advance — or if the commit failed, carrying the store's own verdict on
                which side of the boundary it failed on.
        """
        origin, day = _arguments(BOOKING_ACT, parameters)
        await self._connection.check(egress_binding, origin=origin)
        if not self._catalogue.available(day):
            msg = (
                f"{BOOKING_ACT_ID}: the configured provider has no stay for the day this "
                f"call names, so nothing was booked, no record was written and the commit "
                f"count did not move. The day is not rendered."
            )
            raise _refuse(ToolFailureKind.REFUSED, msg)
        amount = str(self._catalogue.charge_amount)
        currency = self._catalogue.charge_currency
        # **What it was asked and what it charged, and nothing else** (ADR-0273 §2).
        # *Asked* is both declared arguments — the origin as well as the day. The origin
        # equals this registration's configured endpoint on every call that gets this
        # far, because the four conditions refuse any other; but the record outlives the
        # configuration, and a deployment re-pointed between two runs would otherwise
        # leave retained records that cannot say which endpoint each booking named.
        # **And nothing else**: only keys the declaration's own ``parameters_schema``
        # names are persisted, so nothing a caller supplied off-schema is ever stored.
        record: Mapping[str, FrozenJson] = {
            ORIGIN_ARGUMENT: origin,
            DATE_ARGUMENT: day.isoformat(),
            CHARGED_AMOUNT_KEY: amount,
            CHARGED_CURRENCY_KEY: currency,
        }
        confirmed = day != self._catalogue.indeterminate_date
        try:
            await self._store.commit(record, confirmed=confirmed)
        except BookingStoreError as exc:
            msg = (
                f"{BOOKING_ACT_ID}: the booking's durable commit did not complete as "
                f"asked, so whether this deployment recorded a booking is "
                f"{'not known' if exc.may_have_committed else 'settled: it did not'}."
            )
            raise _refuse(
                ToolFailureKind.UNAVAILABLE, msg, committed=exc.may_have_committed
            ) from exc
        return {
            DATE_ARGUMENT: day.isoformat(),
            BOOKED_KEY: True,
            CHARGED_AMOUNT_KEY: amount,
            CHARGED_CURRENCY_KEY: currency,
            SIMULATION_KEY: SIMULATION_NOTICE,
        }


__all__ = [
    "AVAILABLE_KEY",
    "BOOKED_KEY",
    "BOOKING_ACT",
    "BOOKING_ACT_ID",
    "BOOKING_AVAILABILITY",
    "BOOKING_AVAILABILITY_ID",
    "CHARGED_AMOUNT_KEY",
    "CHARGED_CURRENCY_KEY",
    "DATE_ARGUMENT",
    "ORIGIN_ARGUMENT",
    "PRICE_AMOUNT_KEY",
    "PRICE_CURRENCY_KEY",
    "SIMULATION_KEY",
    "SIMULATION_NOTICE",
    "BookingCatalogue",
    "BookingConfigurationError",
    "BookingStoreError",
    "BoundConnection",
    "SimulatedAvailabilityRead",
    "SimulatedBookingAct",
    "SqliteBookingStore",
]
