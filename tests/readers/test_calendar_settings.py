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

from datetime import timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
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


@pytest.fixture(autouse=True)
def _no_calendar_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's own ``.env`` out of the defaults being asserted."""
    for name in (
        "ASSISTANT_CALENDAR_READER_PATH",
        "ASSISTANT_CALENDAR_READER_INTERVAL",
        "ASSISTANT_CALENDAR_WINDOW_PAST",
        "ASSISTANT_CALENDAR_WINDOW_FUTURE",
    ):
        monkeypatch.delenv(name, raising=False)


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


@pytest.mark.parametrize("field", ["window_past", "window_future", "read_timeout"])
def test_a_hostile_repr_does_not_raise_past_a_duration_guard(field: str) -> None:
    """Nothing but a ``ValueError`` leaves this constructor, whatever it was handed.

    The duration guard is the one reached by a value of *arbitrary* type, so a
    message built with ``repr`` would let the refused object's own ``__repr__``
    raise straight past the refusal — turning the wrong-class escape this change
    fixes back into a different wrong-class escape. Every message below the guard
    may use ``repr`` freely, because by then the value is a ``timedelta``.
    """

    class Hostile:
        def __repr__(self) -> str:
            raise RuntimeError("a hostile __repr__ must not raise past a guard")

    kwargs: dict[str, Any] = {field: Hostile()}
    with pytest.raises(ValueError, match=f"calendar_{field} must be a timedelta, got Hostile"):
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
