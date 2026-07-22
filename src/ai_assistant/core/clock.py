"""The injected clock seam: a clock produces an aware, UTC, localizable instant.

Ten constructors across five subsystems take an injected clock. Nothing in the
type system constrains what one returns — ``datetime`` is one type for aware and
naive values — so the obligation was solved once per site, five ways and one
omission (ADR-0026's Context). This module holds the answer once: :data:`Clock`,
the named contract every seam declares, and :func:`checked_clock`, the guard that
enforces it.

**Why `core`, and why not ``core/types.py``.** ADR-0016 §2 keeps *subsystem
logic* out of ``core/types.py`` while allowing semantics **intrinsic** to a type
it defines. A guard that calls an injected callable is not a semantic of a type
at all, so it lives here (ADR-0026 §1). It does belong in `core`, which is not
behaviour-free — ``core/logging.py``'s redaction and ``core/config.py``'s
``load_settings`` are the precedent — because the whole point is that exactly one
definition exists. Golden rule 2 holds as written: nothing outside `core` and the
standard library is imported.

Two things the guard deliberately does not carry, so it stays shared rather than
becoming one subsystem's rule housed in `core`: no configured zone (§3's range is
a flat margin, never ``Settings.timezone``) and no failure policy (`core` raises
``ValueError``; each subsystem translates at its own boundary, ADR-0026 §4).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ai_assistant.core.types import UtcInstant, canonical_utc, describe_untrusted

if TYPE_CHECKING:
    from collections.abc import Callable

type Clock = Callable[[], UtcInstant]
"""A zero-argument callable returning an aware instant, in UTC and localizable.

Every injected-clock seam declares ``now: Clock`` (ADR-0026 §1). The alias
enforces nothing — Python never checks a callable's return annotation, and
``UtcInstant``'s validator only runs where pydantic validates a *field* — so
:func:`checked_clock` is what makes the obligation real. What the alias buys is
that the obligation has one place to be written and arrives at each seam's
signature, rather than being rediscovered there.

Scoped to **wall-clock instants**. A *civil* time (a recurring "09:00
``Europe/Berlin``") and a **monotonic** clock for measuring elapsed duration are
both different contracts, which this one neither covers nor should be stretched
to (ADR-0026 §Consequences).
"""

#: The margin ADR-0026 §3 keeps clear of ``datetime.min``/``max``, so that a
#: reading survives being localized to *any* zone and not merely converted to
#: UTC. A flat day rather than the configured zone's actual offset, deliberately:
#: computing that offset at the boundary requires the very localization being
#: guarded. One day covers every offset the tz database carries, historical LMT
#: included — the widest are ``Asia/Manila``'s -15:56:08 and
#: ``America/Metlakatla``'s +15:13:42, and the widest modern one is
#: ``Pacific/Kiritimati``'s +14:00.
_LOCALIZATION_MARGIN = timedelta(days=1)

#: Inclusive bounds a valid reading, expressed in UTC, must lie within (§3).
_MIN_READING = datetime.min.replace(tzinfo=UTC) + _LOCALIZATION_MARGIN
_MAX_READING = datetime.max.replace(tzinfo=UTC) - _LOCALIZATION_MARGIN


class ClockReadingError(ValueError):
    """A clock reading that does not conform to :data:`Clock` (ADR-0026 §4).

    A ``ValueError``, as ADR-0026 §4 requires of `core` — which cannot know what
    its caller will do with the failure — and a *distinct* one, which the ADR's
    reading/invocation boundary requires of the implementation. §2 is explicit
    that an exception raised by the clock callable **itself** propagates
    unwrapped, carrying its own type and cause; a subsystem catching bare
    ``ValueError`` at its boundary would relabel a clock's own ``ValueError`` as
    a non-conforming *reading*, destroying exactly the diagnosis §2 preserves.
    Catching this type instead keeps the two apart, and costs nothing: it is a
    ``ValueError``, so a caller that only knows the ADR's promise still catches it.

    **What that separation does not, and cannot, cover.** A clock that raises
    *this* type on its own account is reported as a non-conforming reading,
    because an exception is a value any caller may raise and no producer-side
    guard can tell a forged one from its own. That residue is deliberate and it
    is small: nothing raises this type by accident — it exists for one purpose,
    in one module, and no third-party library knows it — so reaching it takes a
    first-party clock deliberately impersonating ``core``'s rejection. ADR-0030
    §3 rules that case out by name: a guard is answerable for the well-formedness
    of the value it hands on and for not composing a claim its source never made,
    not for the truth of a claim its source *did* make. A clock raising
    ``ClockReadingError("provider down")`` is claiming its own reading is
    non-conforming; the seam passes that claim on and composes nothing. The case
    the separation does cover is the one a real clock reaches by accident: a
    provider raising a plain ``ValueError``, which no longer becomes "your clock
    returned a bad reading".
    """


def _rejected(owner: str, reason: str, value: object) -> ClockReadingError:
    """Build the owner-labelled error every rejection raises.

    Args:
        owner: The caller-supplied label naming the seam that read the clock.
        reason: What the reading did wrong, as a verb phrase.
        value: The offending value, described through
            :func:`~ai_assistant.core.types.describe_untrusted`.

    Returns:
        The exception to raise; the caller attaches any cause.
    """
    return ClockReadingError(
        f"the clock injected into {owner} {reason}: {describe_untrusted(value)}"
    )


def _checked_reading(reading: object, *, owner: str) -> datetime:
    """Validate one clock reading and return it canonicalised to UTC.

    The four steps of ADR-0026 §2, as amended by ADR-0030 §4.

    1. **Not a ``datetime`` at all** is rejected first. :data:`Clock` enforces
       nothing at runtime, so ``now=lambda: None`` is a reachable wiring bug;
       unguarded it surfaces as a raw ``AttributeError`` from ``None.utcoffset``.
       This step is deliberately *not* tightened to an exact-type test
       (ADR-0030 §4): a subclass whose conversion is sound is accepted, and step
       4 is where a subclass that does not convert soundly is refused.
    2. **``utcoffset()`` returning ``None``** is rejected — naive, or a ``tzinfo``
       that is set but indeterminate. That is ADR-0023 §5's spelling of "aware",
       and issue #36's rule, applied at the producer. ``astimezone(UTC)`` on such
       a value would treat it as *host-local* and return a confidently wrong
       instant, which is exactly ADR-0023 §3's fabrication.
    3. **Outside §3's range** is rejected here rather than left to surface as an
       ``OverflowError`` from whichever ``astimezone`` reaches it first.
    4. **Convert, canonicalise, then range-check the canonical value.**
       ``astimezone`` is overridable, and pydantic never sees this value on the
       ``model_copy(update=...)`` paths, so trusting the conversion would certify
       precisely what the guard exists to stop. Canonicalising through `core`'s
       one :func:`~ai_assistant.core.types.canonical_utc` makes "in UTC" a
       property of the returned object rather than a claim it makes about itself,
       and makes this seam and ``UtcInstant`` one rule rather than two.

    **The guard is total**, because the annotation is not: a ``tzinfo`` whose
    ``utcoffset()`` raises, a comparison a hostile value refuses, and an
    ``OverflowError`` from the conversion all become the same owner-labelled
    ``ValueError`` with the original attached as its cause. A guard whose own
    failure modes bypassed the failure path it specifies would be enforcing
    nothing at exactly the inputs it exists for.

    Args:
        reading: What the clock returned. Typed ``object`` deliberately: the
            declared ``Callable[[], datetime]`` is what step 1 exists to
            disbelieve, and typing it ``datetime`` would make that step
            unreachable to the type checker.
        owner: The caller-supplied label naming the seam.

    Returns:
        A fresh base ``datetime`` in UTC, within §3's range.

    Raises:
        ClockReadingError: If the reading fails any step, labelled with ``owner``.
    """
    if not isinstance(reading, datetime):
        raise _rejected(owner, "did not return a datetime", reading)
    try:
        offset = reading.utcoffset()
    except Exception as exc:  # a tzinfo that raises rather than answering
        raise _rejected(owner, "returned a value whose tzinfo failed", reading) from exc
    if offset is None:
        raise _rejected(owner, "returned a value with no determinate UTC offset", reading)
    try:
        localizable = _MIN_READING <= reading <= _MAX_READING
    except Exception as exc:  # a value that refuses to be compared
        raise _rejected(owner, "returned a value that cannot be ordered", reading) from exc
    if not localizable:
        raise _rejected(owner, "returned an instant outside the localizable range", reading)
    try:
        # Typed `object` for the same reason `core`'s `_utc_instant` does it:
        # `astimezone` is *annotated* to return a datetime and is not obliged to,
        # so `canonical_utc`'s check has to be a real one rather than one the
        # type checker folds away as always-true.
        converted: object = reading.astimezone(UTC)
        canonical = canonical_utc(converted)
    except Exception as exc:  # incl. OverflowError near datetime.min/max
        raise _rejected(owner, "returned an instant with no UTC representation", reading) from exc
    if canonical is None:
        raise _rejected(owner, "returned a value that did not convert to UTC", converted)
    # Re-checked on the canonical value, per ADR-0030 §4: an overridden
    # `astimezone` can move the instant, and this is the value that is handed on.
    if not _MIN_READING <= canonical <= _MAX_READING:
        raise _rejected(owner, "converted to an instant outside the localizable range", canonical)
    return canonical


def checked_clock(now: Callable[[], datetime], *, owner: str) -> Clock:
    """Wrap an injected clock so every reading is aware, UTC and localizable.

    Wrapped **once, where the clock is stored** — ``self._now =
    checked_clock(now, owner=...)`` — rather than at each read, which a call site
    cannot forget. Per-call guarding is what produced the state ADR-0026 §2
    describes: ``orchestration/loop.py`` remembered and ``memory/ingest.py`` did
    not, on the same write into the same field.

    Checked **per reading, not once at construction**: a clock is a callable
    whose readings change, and a fixture that is aware on its first reading and
    naive on its third is an ordinary test double, so validating once at startup
    would certify a property the clock does not have.

    **Converting, not merely rejecting.** ADR-0023 §2 makes UTC storage mandatory
    and uniform because Python compares two aware datetimes sharing a ``tzinfo``
    by wall clock, ignoring ``fold``. Converting at the producer means every
    downstream comparison sees UTC — including the ones no `core` validator ever
    reaches, like ``SqliteMemoryStore._now_epoch``'s ``timestamp()``. Conversion
    is information-preserving (ADR-0023 §1), so nothing is fabricated.

    **The guard covers the reading, not the invocation.** An exception raised by
    ``now`` *itself* propagates unwrapped: that is the clock's own failure,
    already carrying its own type and cause, and relabelling it would destroy
    both. ``BaseException`` — a cancellation, a ``KeyboardInterrupt`` — passes
    through for the same reason. That boundary only holds downstream if the
    seams can tell the two apart, which is why a rejection is a
    :class:`ClockReadingError` and not a bare ``ValueError``: a subsystem
    catching ``ValueError`` at its boundary would translate a clock's own
    ``ValueError("provider down")`` into "your clock returned a bad reading".

    Args:
        now: The injected clock. Anything callable; the guard disbelieves the
            annotation, which is the point.
        owner: A label naming the seam, for the diagnostic. Caller-supplied
            because it is not inferable — the same fixture callable can be
            injected into two seams at once, so `core` has nothing to distinguish
            them by, and a diagnostic that cannot name which seam got the bad
            reading is the one thing this guard exists to provide.

    Returns:
        A :data:`Clock` returning ``now``'s reading, canonicalised to UTC.

    Raises:
        ClockReadingError: From the returned clock, on a non-conforming reading.
            A ``ValueError``, so ADR-0026 §4 holds as written, and a distinct one
            so a seam can translate a bad *reading* without also relabelling the
            clock's own failure.
    """

    def _read() -> datetime:
        # Deliberately outside the guard: the invocation is the clock's own.
        reading: object = now()
        return _checked_reading(reading, owner=owner)

    return _read
