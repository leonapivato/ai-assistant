"""ADR-0093 §7 and §7a's configuration: disabled by default, refused at load.

Two seams state the same rules and both are tested here, because they are reached
independently. :class:`~ai_assistant.core.config.Settings` is what a deployment
configures; ``CalendarReader.__init__`` is what a test or a second composition
root reaches directly, and ADR-0093 §10 names the constructor half explicitly —
"``Reader`` specifies no constructor and no configuration surface … so a generic
suite has nothing to over-supply. It is a concrete reader's test and a
``Settings`` test."

The defaults are duplicated across the two modules rather than imported, because
``core`` depends on nothing else in ``ai_assistant`` (golden rule 2) and the
dependency can only point one way. That duplication is exactly what
:func:`test_the_settings_defaults_are_the_readers_defaults` exists to keep from
drifting: a "bounded default" that two conforming layers disagree about is
ADR-0074 §9.3's failure with the ADR's own figures in it.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

import pytest
from hostile_values import (
    ClassRaises,
    Hostile,
    HostilePath,
    HostileZone,
    NumericName,
    Unnameable,
    UnrebuildablePath,
    impostor_of,
)
from pydantic import ValidationError

from ai_assistant.core.config import _MAX_CALENDAR_WINDOW, Settings, load_settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.readers import (
    DEFAULT_CALENDAR_MAX_BYTES,
    DEFAULT_CALENDAR_MAX_CONTENT_BYTES,
    DEFAULT_CALENDAR_MAX_ENTRIES,
    DEFAULT_CALENDAR_MAX_EXPANSION,
    DEFAULT_CALENDAR_READ_TIMEOUT,
    DEFAULT_CALENDAR_WINDOW_FUTURE,
    DEFAULT_CALENDAR_WINDOW_PAST,
    MAX_CALENDAR_WINDOW,
    CalendarReader,
)

_ABSOLUTE = Path("/srv/calendars/personal.ics")


# --- disabled by default (ADR-0093 §7) --------------------------------------


def test_the_calendar_reader_ships_disabled() -> None:
    """And the reason is not that anything technical is missing.

    "Nothing may read a user's personal files because a default said so." Naming
    the reason is what stops the default flipping the day the technical obstacle
    clears, and it places the default correctly relative to the grant question: a
    fresh install that read a calendar unasked would be making that decision by
    omission, which is the one way it must not be made (ADR-0093 §7, #629).
    """
    settings = Settings()

    assert settings.calendar_reader_path is None
    assert settings.calendar_reader_interval is None


def test_the_settings_defaults_are_the_readers_defaults() -> None:
    """The figures ADR-0093 §7a names, agreeing across the two layers that hold them."""
    settings = Settings()

    assert settings.calendar_window_past == DEFAULT_CALENDAR_WINDOW_PAST == timedelta(days=1)
    assert settings.calendar_window_future == DEFAULT_CALENDAR_WINDOW_FUTURE == timedelta(days=7)
    assert settings.calendar_max_entries == DEFAULT_CALENDAR_MAX_ENTRIES == 500
    assert settings.calendar_max_bytes == DEFAULT_CALENDAR_MAX_BYTES == 8 * 1024 * 1024
    assert settings.calendar_max_expansion == DEFAULT_CALENDAR_MAX_EXPANSION == 100_000
    assert settings.calendar_read_timeout == DEFAULT_CALENDAR_READ_TIMEOUT == timedelta(seconds=10)
    assert (
        settings.calendar_max_content_bytes == DEFAULT_CALENDAR_MAX_CONTENT_BYTES == 4 * 1024 * 1024
    )
    assert _MAX_CALENDAR_WINDOW == MAX_CALENDAR_WINDOW == timedelta(days=3650)


# --- shape at load, existence at run time (ADR-0093 §7) ---------------------


def test_a_relative_source_path_is_refused_at_load() -> None:
    with pytest.raises(ValidationError, match="absolute path"):
        Settings(calendar_reader_path=Path("calendars/personal.ics"))


def test_a_source_path_is_expanded_but_not_required_to_exist() -> None:
    """A file's existence is a property of the world at an instant, not of the config.

    A hub that refused to start because a calendar file was on an unmounted volume
    would turn an advisory source into a boot dependency, which is precisely the
    coupling ADR-0008 §4 declined for the whole context subsystem. So the run-time
    check degrades under §8 instead.

    ``~`` is expanded before the test rather than rejected with the relative paths,
    for ``data_dir``'s reason: ``Path`` does no expansion, so ``~/calendar.ics``
    would otherwise be refused for being relative — a distinction an operator has
    no way to anticipate.
    """
    assert Settings(calendar_reader_path=_ABSOLUTE).calendar_reader_path == _ABSOLUTE

    expanded = Settings(calendar_reader_path=Path("~/calendar.ics")).calendar_reader_path
    assert expanded is not None
    assert expanded.is_absolute()
    assert not str(expanded).startswith("~")


def test_an_interval_with_no_source_is_refused_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """§7a's fourth state, and the only incoherent one.

    The alternatives are all worse and all silently different: a scheduler that
    omits the requested job reports health while running nothing, one that arms it
    re-runs a failing job forever, and one that treats it as a source fault turns a
    configuration mistake into an infinite retry.
    """
    with pytest.raises(ValidationError, match="needs a source to read"):
        Settings(calendar_reader_interval=timedelta(hours=1))

    monkeypatch.setenv("ASSISTANT_CALENDAR_READER_INTERVAL", "PT1H")
    with pytest.raises(ConfigurationError, match="invalid configuration"):
        load_settings()


def test_the_three_coherent_states_load() -> None:
    """Fully disabled, facet-only (reserved), and both live (ADR-0093 §7a)."""
    assert Settings().calendar_reader_interval is None
    assert Settings(calendar_reader_path=_ABSOLUTE).calendar_reader_interval is None
    both = Settings(calendar_reader_path=_ABSOLUTE, calendar_reader_interval=timedelta(hours=6))
    assert both.calendar_reader_interval == timedelta(hours=6)


def test_disabled_is_none_and_never_zero() -> None:
    """ADR-0083 §7's convention, and its reason applies unmodified.

    The scheduler re-arms a job from its *completion*, so an interval of zero makes
    it due again the instant it finishes — and "off" and "as fast as possible" look
    identical in a config file.
    """
    with pytest.raises(ValidationError):
        Settings(calendar_reader_path=_ABSOLUTE, calendar_reader_interval=timedelta(0))


# --- the ranges §7a names (ADR-0093 §7a) ------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("calendar_window_past", timedelta(seconds=-1)),
        ("calendar_window_past", timedelta(days=3651)),
        # A window of zero width is a reader that reads nothing while reporting
        # health, which ADR-0077 §1 refused for a zero batch.
        ("calendar_window_future", timedelta(0)),
        ("calendar_window_future", timedelta(days=3651)),
        ("calendar_max_entries", 0),
        ("calendar_max_entries", 2**63),
        ("calendar_max_expansion", 0),
        ("calendar_max_expansion", 2**63),
        ("calendar_max_bytes", 0),
        ("calendar_max_content_bytes", 0),
        ("calendar_read_timeout", timedelta(0)),
    ],
)
def test_a_figure_outside_its_range_is_refused_at_load(field: str, value: object) -> None:
    """Refused at load rather than at the first run (ADR-0093 §5, ADR-0077 §1)."""
    kwargs: dict[str, Any] = {field: value}
    with pytest.raises(ValidationError):
        Settings(**kwargs)


def test_a_zero_past_window_is_coherent_and_accepted() -> None:
    """A deployment that wants only what is ahead is coherent (ADR-0093 §7a)."""
    assert Settings(calendar_window_past=timedelta(0)).calendar_window_past == timedelta(0)


# --- the constructor states the same rules (ADR-0093 §10) -------------------


def test_the_constructor_refuses_a_relative_path() -> None:
    with pytest.raises(ValueError, match="absolute path"):
        CalendarReader(Path("calendar.ics"))


def test_the_constructor_refuses_an_unknown_timezone() -> None:
    with pytest.raises(ValueError, match="unknown timezone"):
        CalendarReader(_ABSOLUTE, timezone="Mars/Olympus_Mons")


@pytest.mark.parametrize("value", [None, "/srv/calendars/personal.ics", 3, b"/srv/c.ics"])
def test_the_constructor_refuses_a_source_that_is_not_a_path(value: object) -> None:
    """The type is checked before anything is called on it (#1057).

    A ``str`` has no ``is_absolute`` and ``None`` has no attributes at all, so an
    unguarded call turned a direct caller's mistake into an ``AttributeError``
    naming a *method* rather than the ``ValueError`` naming the field. The string
    case is the one a second composition root actually writes — it is the one
    value that looks correct.
    """
    with pytest.raises(ValueError, match="must be a Path"):
        CalendarReader(value)  # type: ignore[arg-type]


#: The two ways a type can fail to name itself: the read of ``__name__`` raises, or
#: it answers with something that is not a ``str`` whose own rendering would then
#: raise (#2104). Named rather than built here — see :func:`_unnameable`.
_UNNAMEABLE: Final = ["unreadable", "not-a-str"]

#: Every duration this constructor guards, spelled as the keyword a caller passes.
_DURATION_GUARDS: Final = ["window_past", "window_future", "read_timeout"]


def _unnameable(kind: str) -> object:
    """An instance of a class that will not say what it is called.

    **Built inside the arm rather than passed to it**, which is not a style
    preference: pytest renders a failing test's arguments, and rendering *this* one
    asks the class the very question it refuses — so a regression that ought to
    show as one red assertion crashes the whole session with an ``INTERNALERROR``
    from inside pytest's own traceback formatter instead. Verified by mutation.
    """
    metaclass = Unnameable if kind == "unreadable" else NumericName
    return metaclass("Evil", (), {})()


def test_a_hostile_repr_does_not_raise_past_the_source_guard() -> None:
    """The source guard is reached by a value of *arbitrary* type, like the rest.

    ``Settings`` refuses a non-path at load and ``mypy`` refuses one at a
    type-checked call site, so what reaches here is the direct caller ADR-0093 §10
    names — for whom a refusal that raised ``RuntimeError`` would describe nothing.
    """
    with pytest.raises(ValueError, match="the calendar source must be a Path, got Hostile"):
        CalendarReader(Hostile())  # type: ignore[arg-type]


def test_a_hostile_repr_does_not_raise_past_the_zone_guard() -> None:
    """The zone guard's half of the same rule."""
    with pytest.raises(ValueError, match="the calendar timezone must be a str, got Hostile"):
        CalendarReader(_ABSOLUTE, timezone=Hostile())  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", _UNNAMEABLE)
def test_a_hostile_type_name_does_not_raise_past_the_source_guard(kind: str) -> None:
    """The half of #1978 that survives substituting ``repr``, at the source guard.

    Naming the type is a call into the refused object's *class*, so a metaclass
    that raises on ``__name__`` — or answers with a second object that raises when
    rendered — moves the wrong-exception-class escape rather than closing it. The
    integer guards were pointed at :func:`~ai_assistant.readers.calendar._type_name_of`
    by #1978's lane and these four were parked as #2104; this is that asymmetry
    closed.
    """
    expected = "the calendar source must be a Path, got an unnameable type"
    with pytest.raises(ValueError, match=expected):
        CalendarReader(_unnameable(kind))  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", _UNNAMEABLE)
def test_a_hostile_type_name_does_not_raise_past_the_zone_guard(kind: str) -> None:
    """#2104 at the zone guard."""
    expected = "the calendar timezone must be a str, got an unnameable type"
    with pytest.raises(ValueError, match=expected):
        CalendarReader(_ABSOLUTE, timezone=_unnameable(kind))  # type: ignore[arg-type]


@pytest.mark.parametrize("field", _DURATION_GUARDS)
@pytest.mark.parametrize("kind", _UNNAMEABLE)
def test_a_hostile_type_name_does_not_raise_past_a_duration_guard(field: str, kind: str) -> None:
    """#2104 at each of the three duration guards."""
    kwargs: dict[str, Any] = {field: _unnameable(kind)}
    expected = re.escape(f"calendar_{field} must be a timedelta, got an unnameable type")
    with pytest.raises(ValueError, match=expected):
        CalendarReader(_ABSOLUTE, **kwargs)


def test_a_path_subclass_cannot_lie_its_way_past_the_source_guard() -> None:
    """Proving ``isinstance`` proves nothing about the overrides (#2104).

    Both halves of this guard are reachable through an accepted subclass:
    ``is_absolute`` is the guard's own question and the subclass answers it, so a
    relative location was admitted by saying it was not one — and the refusal that
    would have reported it renders the value, which the same subclass raises from.
    Rebuilding the accepted value into a built-in ``Path`` and asking *that* is
    :func:`~ai_assistant.readers.calendar._checked_duration`'s answer for the
    durations, at the seam that had not got it (#1979).
    """
    with pytest.raises(ValueError, match=re.escape("must be an absolute path, got 'documents'")):
        CalendarReader(HostilePath("documents"))


def test_an_accepted_source_is_stored_as_a_builtin_path() -> None:
    """The rebuilt location is what is kept, not the subclass that carried it.

    Storing the caller's object would push the same overrides downstream into the
    ``os.open`` and into every message that names the source, which is
    :func:`test_an_accepted_duration_is_stored_as_a_builtin_timedelta`'s reason at
    this seam.
    """
    reader = CalendarReader(HostilePath(str(_ABSOLUTE)))

    assert type(reader._path) is type(Path("/"))
    assert reader._path == _ABSOLUTE


def test_a_str_subclass_cannot_raise_past_the_zone_refusal() -> None:
    """The zone guard's half of the subclass shape (#2104).

    ``isinstance(value, str)`` admits a subclass, and the refusal below it reports
    the zone that was not found — by rendering the value it was handed. The guard
    rebuilds through ``str.__str__``, which reads the C-level slot.
    """
    with pytest.raises(ValueError, match=re.escape("unknown timezone 'Mars/Olympus_Mons'")):
        CalendarReader(_ABSOLUTE, timezone=HostileZone("Mars/Olympus_Mons"))


def test_a_str_subclass_naming_a_real_zone_is_still_accepted() -> None:
    """Acceptance is unchanged by the rebuild: ``ZoneInfo`` keys on the characters."""
    reader = CalendarReader(_ABSOLUTE, timezone=HostileZone("Europe/Rome"))

    assert reader._zone == ZoneInfo("Europe/Rome")


def test_a_path_that_will_not_rebuild_is_refused_rather_than_raising() -> None:
    """The rebuild that closes the subclass shape is itself reachable, one level in.

    ``Path(value)`` copies what a ``PurePath`` holds by reading ``parser`` and
    ``_raw_paths``, which are ordinary Python attributes a genuine subclass can
    override to raise — the same regress ``__name__`` opened for the type refusal
    (#2104). The guard catches it and answers in its own exception class, so
    "nothing but a ``ValueError`` leaves this constructor" is true rather than
    nearly true.
    """
    expected = (
        "the calendar source must be a Path that rebuilds to a built-in one, got UnrebuildablePath"
    )
    with pytest.raises(ValueError, match=re.escape(expected)):
        CalendarReader(UnrebuildablePath(str(_ABSOLUTE)))


#: Every guard on this constructor that admits a *subclass* of what it accepts, as
#: the keyword a caller passes, the type it admits, and the refusal it states.
_ACCEPTED_TYPE_GUARDS: Final = [
    ("path", Path, "the calendar source must be a Path"),
    ("timezone", str, "the calendar timezone must be a str"),
    ("window_past", timedelta, "calendar_window_past must be a timedelta"),
    ("window_future", timedelta, "calendar_window_future must be a timedelta"),
    ("read_timeout", timedelta, "calendar_read_timeout must be a timedelta"),
]


@pytest.mark.parametrize(("field", "accepted", "refusal"), _ACCEPTED_TYPE_GUARDS)
def test_an_impostor_does_not_pass_a_type_guard(field: str, accepted: type, refusal: str) -> None:
    """The type test is put to the *real* class, never to the object (#2104).

    ``isinstance`` falls back to ``value.__class__`` when the concrete type does not
    match, so an object of an unrelated class answering that attribute passes it —
    and the operation below the test then meets something that cannot support it:
    ``str.__str__`` and ``timedelta.__sub__`` answer ``TypeError`` and ``Path(value)``
    ``AttributeError``, none of which is the exception this constructor promises.
    ``type(value)`` reads ``Py_TYPE`` and is not fooled.
    """
    kwargs: dict[str, Any] = {"path": _ABSOLUTE, field: impostor_of(accepted)}
    with pytest.raises(ValueError, match=re.escape(f"{refusal}, got Impostor")):
        CalendarReader(**kwargs)


@pytest.mark.parametrize(
    ("field", "refusal"), [(field, refusal) for field, _type, refusal in _ACCEPTED_TYPE_GUARDS]
)
def test_a_class_that_raises_does_not_take_a_type_guard_down(field: str, refusal: str) -> None:
    """:func:`test_an_impostor_does_not_pass_a_type_guard`'s other half.

    Where an impostor lies about its class, this one refuses to answer — so an
    ``isinstance`` test raises before any refusal can be built at all, which is the
    escape at its earliest possible point.
    """
    kwargs: dict[str, Any] = {"path": _ABSOLUTE, field: ClassRaises()}
    with pytest.raises(ValueError, match=re.escape(f"{refusal}, got ClassRaises")):
        CalendarReader(**kwargs)


def test_an_honest_subclass_of_each_accepted_type_is_still_admitted() -> None:
    """Asking the real class narrows what is accepted by nothing at all.

    ``issubclass(type(value), X)`` and ``isinstance(value, X)`` agree on every object
    that does not override ``__class__``, which is the whole population a caller
    legitimately passes.
    """
    reader = CalendarReader(
        HostilePath(str(_ABSOLUTE)),
        timezone=HostileZone("Europe/Rome"),
        window_past=_Forged(days=2),
    )

    assert reader._path == _ABSOLUTE
    assert reader._zone == ZoneInfo("Europe/Rome")
    assert reader._window_past == timedelta(days=2)


@pytest.mark.parametrize("field", _DURATION_GUARDS)
def test_a_hostile_repr_does_not_raise_past_a_duration_guard(field: str) -> None:
    """Nothing but a ``ValueError`` leaves this constructor, whatever it was handed.

    The duration guard is the one reached by a value of *arbitrary* type, so a
    message built with ``repr`` would let the refused object's own ``__repr__``
    raise straight past the refusal — turning the wrong-class escape this change
    fixes back into a different wrong-class escape. Every message below the guard
    may use ``repr`` freely, because by then the value is a ``timedelta``.
    """
    kwargs: dict[str, Any] = {field: Hostile()}
    with pytest.raises(ValueError, match=f"calendar_{field} must be a timedelta, got Hostile"):
        CalendarReader(_ABSOLUTE, **kwargs)


#: Each integer-guarded constructor argument, with the rule both of its refusals cite.
_INTEGER_GUARDS = [
    ("max_entries", "an int in [1, 2**63)"),
    ("max_expansion", "an int in [1, 2**63)"),
    ("max_bytes", "a positive int"),
    ("max_content_bytes", "a positive int"),
]


@pytest.mark.parametrize(("field", "domain"), _INTEGER_GUARDS)
def test_a_hostile_repr_does_not_raise_past_an_integer_guard(field: str, domain: str) -> None:
    """The duration guard's rule, at the seam that had not got it (#1978).

    These two guards conflated the type test with the range test in one condition,
    so one message served both and it was built with ``repr`` — which is right for
    a range violation and wrong for a type refusal, because only the type refusal
    is reached by a value of *arbitrary* type. Split, the type refusal names the
    type, and nothing but a ``ValueError`` leaves this constructor whatever it was
    handed.
    """
    kwargs: dict[str, Any] = {field: Hostile()}
    expected = re.escape(f"calendar_{field} must be {domain}, got Hostile")
    with pytest.raises(ValueError, match=expected):
        CalendarReader(_ABSOLUTE, **kwargs)


@pytest.mark.parametrize(("field", "domain"), _INTEGER_GUARDS)
def test_a_hostile_type_name_does_not_raise_past_an_integer_guard(field: str, domain: str) -> None:
    """The half of #1978 that survives substituting ``repr``.

    A refusal that names the type still calls into the refused object's *class*,
    so a metaclass whose ``__name__`` raises moves the wrong-exception-class
    escape rather than closing it. The read is guarded for the same reason
    :func:`~ai_assistant.core.types.fault_class_of` guards its own.
    """
    kwargs: dict[str, Any] = {field: Unnameable("Evil", (), {})()}
    expected = re.escape(f"calendar_{field} must be {domain}, got an unnameable type")
    with pytest.raises(ValueError, match=expected):
        CalendarReader(_ABSOLUTE, **kwargs)


@pytest.mark.parametrize(("field", "domain"), _INTEGER_GUARDS)
def test_a_type_name_that_is_not_a_str_does_not_reach_the_message(field: str, domain: str) -> None:
    """``__name__`` can answer with something that is not a ``str`` at all.

    Rendering *that* into the message is a second object with a second chance to
    raise, so the guard requires a built-in ``str`` rather than accepting whatever
    answered.
    """
    kwargs: dict[str, Any] = {field: NumericName("Numeric", (), {})()}
    expected = re.escape(f"calendar_{field} must be {domain}, got an unnameable type")
    with pytest.raises(ValueError, match=expected):
        CalendarReader(_ABSOLUTE, **kwargs)


@pytest.mark.parametrize(("field", "domain"), _INTEGER_GUARDS)
def test_a_flag_is_refused_by_the_type_test_and_named_as_a_bool(field: str, domain: str) -> None:
    """Where #471's rule is now written, and that it still draws the same line.

    ``bool`` is an ``int`` by inheritance, so ``max_entries=True`` passes ``mypy``
    and would load as a cap of one. The exact-type test refuses it, which is what
    lets this assertion be made at all: the refusal names ``bool`` rather than
    asking the flag to render itself as ``True``.
    """
    kwargs: dict[str, Any] = {field: True}
    expected = re.escape(f"calendar_{field} must be {domain}, got bool")
    with pytest.raises(ValueError, match=expected):
        CalendarReader(_ABSOLUTE, **kwargs)


@pytest.mark.parametrize(
    ("field", "value", "domain"),
    [
        ("max_entries", 0, "an int in [1, 2**63)"),
        ("max_expansion", 2**63, "an int in [1, 2**63)"),
        ("max_bytes", 0, "a positive int"),
        ("max_content_bytes", -1, "a positive int"),
    ],
)
def test_a_figure_out_of_range_is_still_reported_by_value(
    field: str, value: int, domain: str
) -> None:
    """The half of the split ``repr`` is *right* for, and the split does not lose it.

    ``got 0`` is what a caller needs from a range violation and ``got int`` is not,
    so the value's rendering survives below the type test — where it is safe,
    because the exact-type test has by then proved the figure a built-in ``int``.
    """
    kwargs: dict[str, Any] = {field: value}
    expected = re.escape(f"calendar_{field} must be {domain}, got {value!r}")
    with pytest.raises(ValueError, match=expected):
        CalendarReader(_ABSOLUTE, **kwargs)


@pytest.mark.parametrize("field", ["window_past", "window_future", "read_timeout"])
def test_a_lying_comparison_does_not_reach_the_range_check(field: str) -> None:
    """An object that is not a duration is refused for what it is not.

    Before the type guard, the range check asked *any* object and accepted every
    one that answered ``False`` — so an object with nothing but comparison
    operators constructed a reader.
    """

    class NotEvenADuration:
        def __lt__(self, other: object) -> bool:
            return False

        def __gt__(self, other: object) -> bool:
            return False

        def __le__(self, other: object) -> bool:
            return False

        def __ge__(self, other: object) -> bool:
            return False

    kwargs: dict[str, Any] = {field: NotEvenADuration()}
    with pytest.raises(ValueError, match=f"calendar_{field} must be a timedelta"):
        CalendarReader(_ABSOLUTE, **kwargs)


class _Forged(timedelta):
    """A duration that lies about itself in every way the guards below it ask.

    Accepted by ``isinstance``, and then answers ``False`` to every comparison, so
    it evades any range check that asks *it* whether it is in range; its
    ``__repr__`` raises, so it also evades being reported. It exists to pin that
    neither question is put to the caller's object: the guard canonicalises first
    and range-checks, reports and stores the built-in ``timedelta`` it gets back.
    """

    def __lt__(self, other: object) -> bool:
        return False

    def __gt__(self, other: object) -> bool:
        return False

    def __le__(self, other: object) -> bool:
        return False

    def __ge__(self, other: object) -> bool:
        return False

    def __eq__(self, other: object) -> bool:
        return False

    def __hash__(self) -> int:
        return 0

    def __repr__(self) -> str:
        raise RuntimeError("a hostile __repr__ must not raise past a guard")

    def __sub__(self, other: object) -> timedelta:
        return self


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("window_past", _Forged(seconds=-1)),
        ("window_past", _Forged(days=3651)),
        ("window_future", _Forged(0)),
        ("window_future", _Forged(days=3651)),
        ("read_timeout", _Forged(0)),
        ("read_timeout", _Forged(seconds=-1)),
    ],
)
def test_a_forged_duration_subclass_cannot_evade_its_bound(field: str, value: timedelta) -> None:
    """ADR-0093 §7a's bounds hold against a value that lies about being in them.

    A ``timedelta`` subclass passes ``isinstance`` — deliberately, because honest
    subclasses exist and exactness would refuse them to no purpose — so the bound
    cannot be enforced by asking the object. It is enforced by not asking it:
    ``timedelta.__sub__`` reads the C-level slots and yields a built-in
    ``timedelta``, which is what the range check, the message and the stored
    field all see. Hence a hostile ``__repr__`` here reaches the *range* message
    and still does not raise past it (#1979).
    """
    kwargs: dict[str, Any] = {field: value}
    with pytest.raises(ValueError, match=f"calendar_{field} must be"):
        CalendarReader(_ABSOLUTE, **kwargs)


def test_an_accepted_duration_is_stored_as_a_builtin_timedelta() -> None:
    """The canonical value is what is kept, not the subclass that carried it.

    Storing the caller's object would push the same lie downstream into
    ``read_at + window_future``, which is the arithmetic the bound exists to keep
    representable.
    """
    reader = CalendarReader(
        _ABSOLUTE,
        window_past=_Forged(days=2),
        window_future=_Forged(days=3),
        read_timeout=_Forged(seconds=5),
    )

    for attribute, expected in (
        ("_window_past", timedelta(days=2)),
        ("_window_future", timedelta(days=3)),
        ("_read_timeout", timedelta(seconds=5)),
    ):
        stored = getattr(reader, attribute)
        assert type(stored) is timedelta
        assert stored == expected


@pytest.mark.parametrize("value", [None, 3, ZoneInfo("Europe/Rome")])
def test_the_constructor_refuses_a_timezone_that_is_not_a_str(value: object) -> None:
    """The fifth site of the same rule, and the one the ``Raises:`` clause names.

    ``ZoneInfo`` raises its own ``TypeError`` — "expected str, bytes or
    os.PathLike object, not NoneType" — which names neither this reader's field
    nor the rule. An already-resolved ``ZoneInfo`` is the plausible mistake here,
    and it is refused rather than accepted: a reader may not take its zone from a
    second source, so there is one spelling of the parameter (ADR-0026).
    """
    with pytest.raises(ValueError, match="must be a str"):
        CalendarReader(_ABSOLUTE, timezone=value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("window_past", timedelta(seconds=-1)),
        ("window_past", timedelta(days=3651)),
        ("window_future", timedelta(0)),
        ("window_future", timedelta(days=3651)),
        ("max_entries", 0),
        ("max_entries", 2**63),
        ("max_expansion", 0),
        ("max_bytes", 0),
        ("max_content_bytes", 0),
        ("read_timeout", timedelta(0)),
        # A flag is not a count, which is the rule the four layers under
        # `Settings` already state at the seam a direct caller reaches (#471).
        ("max_entries", True),
        ("max_bytes", True),
        # And a value of the wrong type is refused as a value rather than
        # escaping as an operator's `TypeError` from the comparison below it
        # (#1057). The durations are the half that had no type guard:
        # `_check_count` is exact-typed to exclude `bool`, so the integers were
        # covered by the rule they got for a different reason.
        ("window_past", None),
        ("window_past", 3600),
        ("window_future", None),
        ("window_future", 3600),
        ("read_timeout", None),
        ("read_timeout", 10),
        # `bool` is not an `int`'s problem alone: `True <= timedelta(0)` is the
        # same unsupported comparison, so the duration guard states it too.
        ("read_timeout", True),
        ("max_entries", None),
        ("max_bytes", "8388608"),
    ],
)
def test_the_constructor_refuses_a_figure_outside_its_range(field: str, value: object) -> None:
    """Refused at construction, as a ``ValueError`` naming the field it refused.

    ADR-0093 §10 puts this seam's guard here because the constructor "is a second
    seam a test or a second composition root reaches directly" — and what such a
    caller needs from a refusal is the field's name and the rule. A ``TypeError``
    reading ``'<' not supported between instances of 'NoneType' and
    'datetime.timedelta'`` names neither (#1057).
    """
    kwargs: dict[str, Any] = {field: value}
    with pytest.raises(ValueError, match=f"calendar_{field}"):
        CalendarReader(_ABSOLUTE, **kwargs)
