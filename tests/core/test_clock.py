"""Behaviour of the injected-clock guard (ADR-0026 §§1-4, ADR-0030 §4).

``checked_clock`` is the producer-side twin of ``UtcInstant``: the same
canonicalisation rule, applied where a clock is *stored* rather than where a
field is validated. The two must not drift, which is why the hostile values are
shared (``tests/core/hostile_instants.py``) and asserted by both suites.

What is pinned here that the field seam cannot pin: the owner label, the total
failure path over the *reading*, the pass-through of a failure of the
*invocation*, per-reading rather than per-construction checking, and the
localizable range of ADR-0026 §3.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

import pytest
from hostile_instants import HOSTILE_IDS, HOSTILE_INSTANTS

from ai_assistant.core.clock import checked_clock

if TYPE_CHECKING:
    from collections.abc import Callable

    from hostile_instants import HostileInstant


def _clock(value: object) -> Callable[[], datetime]:
    """A clock returning ``value``, however little it resembles a ``datetime``."""
    return cast("Callable[[], datetime]", lambda: value)


@pytest.mark.parametrize("case", HOSTILE_INSTANTS, ids=HOSTILE_IDS)
def test_the_shared_adversarial_table_holds_at_the_clock_seam(case: HostileInstant) -> None:
    """ADR-0030 §4's shared table, asserted here and identically in ``test_utc_instant.py``.

    The list is the artifact, not this function: `core` has one canonicaliser,
    so a case added for the field seam is automatically owed by this one. A
    change to either that the other does not follow fails the gate.
    """
    case.reset()
    try:
        now = checked_clock(_clock(case.make()), owner="Seam")
        if case.accepted:
            reading = now()
            assert type(reading) is datetime
            assert reading.tzinfo is UTC
            assert reading == case.canonical
        else:
            with pytest.raises(ValueError, match="Seam"):
                now()
    finally:
        case.reset()


def test_a_clock_returning_something_that_is_not_a_datetime_is_rejected() -> None:
    """ADR-0026 §2 step 1: ``now=lambda: None`` is a reachable wiring bug.

    :data:`~ai_assistant.core.clock.Clock` enforces nothing at runtime, so the
    annotation is exactly what this step exists to disbelieve. Unguarded it
    surfaces as a raw ``AttributeError`` from ``None.utcoffset()``, several
    frames from the wiring that caused it.

    Not in the shared table deliberately: the table is about *instants*, and at a
    pydantic field this input never reaches the canonicaliser at all.
    """
    now = checked_clock(_clock(None), owner="Seam")

    with pytest.raises(ValueError, match="Seam did not return a datetime"):
        now()


def test_step_one_is_not_an_exact_type_test() -> None:
    """ADR-0030 §4: step 1 must **not** be tightened to ``type(v) is datetime``.

    A subclass whose conversion is sound is accepted (§1), and the shared table's
    one accepted case is exactly that. Tightening step 1 would refuse it here
    while the field seam still accepted it — the divergence ADR-0030 exists to
    prevent. This asserts the negative directly rather than by inference.
    """

    class _Subclass(datetime):
        pass

    reading = _Subclass(2026, 7, 21, 12, tzinfo=ZoneInfo("Europe/Berlin"))
    now = checked_clock(_clock(reading), owner="Seam")

    # Refused, but at step 4 — `astimezone` preserved the subclass — not step 1.
    with pytest.raises(ValueError, match="did not convert to UTC"):
        now()


def test_the_owner_label_names_the_seam_that_read_the_clock() -> None:
    """The one thing the guard exists to provide, and the one thing `core` cannot infer.

    The same fixture callable can be injected into two seams at once, so `core`
    has nothing to distinguish them by. A diagnostic that could not name which
    seam got the bad reading would leave the wiring bug exactly as hard to find
    as it is today.
    """
    naive = _clock(datetime(2026, 1, 2, 9))  # noqa: DTZ001 — one naive fixture, two seams
    source = checked_clock(naive, owner="ClockContextSource")
    execution = checked_clock(naive, owner="PlanExecution")

    with pytest.raises(ValueError, match="injected into ClockContextSource"):
        source()
    with pytest.raises(ValueError, match="injected into PlanExecution"):
        execution()


def test_a_conforming_clock_is_unchanged_and_canonicalised() -> None:
    """The default at all ten seams already conforms; this costs it nothing."""
    now = checked_clock(lambda: datetime(2026, 7, 21, 12, tzinfo=UTC), owner="Seam")
    reading = now()

    assert type(reading) is datetime
    assert reading.tzinfo is UTC
    assert reading == datetime(2026, 7, 21, 12, tzinfo=UTC)


def test_an_aware_non_utc_reading_is_converted_not_merely_accepted() -> None:
    """ADR-0026 §2: converting, not merely rejecting.

    Every downstream comparison then sees UTC — including the ones no `core`
    validator reaches, like ``SqliteMemoryStore._now_epoch``'s ``timestamp()``.
    Conversion is information-preserving, so nothing is fabricated.
    """
    berlin = datetime(2026, 7, 21, 14, tzinfo=ZoneInfo("Europe/Berlin"))
    reading = checked_clock(lambda: berlin, owner="Seam")()

    assert reading.tzinfo is UTC
    assert reading == berlin
    assert reading == datetime(2026, 7, 21, 12, tzinfo=UTC)


def test_the_reading_is_checked_per_call_not_once_at_construction() -> None:
    """ADR-0026 §2: a clock is a callable whose readings change.

    A fixture that is aware on its first reading and naive on its third is an
    ordinary test double, so validating once at startup would certify a property
    the clock does not have.
    """
    readings = iter(
        [
            datetime(2026, 7, 21, 12, tzinfo=UTC),
            datetime(2026, 7, 21, 13, tzinfo=UTC),
            datetime(2026, 7, 21, 14),  # noqa: DTZ001 — the third reading is the subject
        ]
    )
    now = checked_clock(lambda: next(readings), owner="Seam")

    assert now() == datetime(2026, 7, 21, 12, tzinfo=UTC)
    assert now() == datetime(2026, 7, 21, 13, tzinfo=UTC)
    with pytest.raises(ValueError, match="Seam"):
        now()


def test_a_failure_of_the_invocation_propagates_unwrapped() -> None:
    """ADR-0026 §2: the guard covers the reading, not the invocation.

    An exception raised by the clock *itself* is the clock's own failure,
    already carrying its own type and cause; relabelling it ``ValueError`` would
    destroy both.
    """

    def _broken() -> datetime:
        msg = "the clock source is down"
        raise RuntimeError(msg)

    now = checked_clock(_broken, owner="Seam")

    with pytest.raises(RuntimeError, match="the clock source is down"):
        now()


def test_a_base_exception_from_the_invocation_is_not_swallowed() -> None:
    """Cancellation and ``KeyboardInterrupt`` must pass through for the same reason."""

    def _cancelled() -> datetime:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        checked_clock(_cancelled, owner="Seam")()


def test_a_hostile_tzinfo_failure_becomes_the_owner_labelled_error() -> None:
    """The guard's own failure modes must not bypass the failure path it specifies.

    A guard that let a ``RuntimeError`` from a custom ``tzinfo`` escape would be
    enforcing nothing at exactly the inputs it exists for — and the original is
    kept as the cause rather than discarded.
    """
    from hostile_instants import RaisingOffset  # noqa: PLC0415 — local to this one case

    now = checked_clock(_clock(datetime(2026, 1, 2, 9, tzinfo=RaisingOffset())), owner="Seam")

    with pytest.raises(ValueError, match="Seam returned a value whose tzinfo failed") as caught:
        now()
    assert isinstance(caught.value.__cause__, RuntimeError)


@pytest.mark.parametrize(
    "boundary",
    [
        pytest.param(datetime.min.replace(tzinfo=UTC), id="datetime-min"),
        pytest.param(datetime.max.replace(tzinfo=UTC), id="datetime-max"),
        pytest.param(datetime.min.replace(tzinfo=UTC) + timedelta(hours=23), id="just-inside-min"),
        pytest.param(datetime.max.replace(tzinfo=UTC) - timedelta(hours=23), id="just-inside-max"),
    ],
)
def test_a_reading_outside_the_localizable_range_is_rejected(boundary: datetime) -> None:
    """ADR-0026 §3: "localizable", not merely "convertible to UTC".

    ``ClockContextSource`` localizes the reading to the configured zone to derive
    ``time_of_day``; a value that converts to UTC without overflowing can still
    overflow that *second* ``astimezone``. Rejected here rather than left to
    surface as an ``OverflowError`` from whichever localization reaches it first.
    """
    with pytest.raises(ValueError, match="outside the localizable range"):
        checked_clock(lambda: boundary, owner="Seam")()


@pytest.mark.parametrize(
    "boundary",
    [
        pytest.param(datetime.min.replace(tzinfo=UTC) + timedelta(days=1), id="min-plus-a-day"),
        pytest.param(datetime.max.replace(tzinfo=UTC) - timedelta(days=1), id="max-minus-a-day"),
    ],
)
def test_the_range_bound_is_inclusive_at_a_flat_day(boundary: datetime) -> None:
    """The margin is exactly one day, and the bound itself is valid.

    Pinned so the constant cannot drift silently: a day covers every offset the
    tz database carries, and the coarseness at the extremes is the deliberate
    price of not computing the configured zone's offset inside the guard.
    """
    assert checked_clock(lambda: boundary, owner="Seam")() == boundary


class _ConvertsOutOfRange(datetime):
    """Passes step 3 in range, and converts to a base ``datetime`` that is not.

    The only shape that can reach the post-conversion range check: step 3 already
    compares the *instant*, so a well-behaved value cannot be in range before
    conversion and out of it afterwards. An overridden ``astimezone`` can.
    """

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return datetime.min.replace(tzinfo=UTC)


def test_a_reading_that_only_leaves_the_range_after_conversion_is_rejected() -> None:
    """ADR-0030 §4: the range check is applied to the *canonical* value too.

    The value handed on is what has to be localizable, and step 4's conversion is
    overridable — so checking only the received value would certify a canonical
    instant that overflows the first ``astimezone`` a consumer performs on it.
    """
    reading = _ConvertsOutOfRange(2026, 7, 21, 12, tzinfo=UTC)

    with pytest.raises(ValueError, match="outside the localizable range"):
        checked_clock(_clock(reading), owner="Seam")()


def test_the_guard_depends_on_nothing_but_the_standard_library_and_core_types() -> None:
    """ADR-0026 §1, twice over, asserted on the module's import graph.

    *No configured zone.* The range asks "representable under **any**
    localization", a fact about ``datetime`` arithmetic that is computable from
    the type's own bounds and identical for every consumer. Had it read
    ``Settings.timezone`` it would be `context`'s rule wearing `core`'s coat, and
    it would belong in `context`.

    *Golden rule 2 as written.* `core` depends on nothing else in
    ``ai_assistant``, and the one intra-package import is the ADR-0030 §4
    direction: ``core/clock.py`` → ``core/types.py``, never the reverse.
    ``lint-imports`` polices the package boundary; this polices the module's.
    """
    import ast  # noqa: PLC0415 — the inspection is this test's subject
    import inspect  # noqa: PLC0415

    from ai_assistant.core import clock  # noqa: PLC0415

    tree = ast.parse(inspect.getsource(clock))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert modules == {
        "__future__",
        "datetime",
        "typing",
        "collections.abc",
        "ai_assistant.core.types",
    }
