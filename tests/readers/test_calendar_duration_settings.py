"""The duration spellings ``readers/calendar.py``'s deployment note promises.

That note tells an operator, in terms, that every duration setting on this chain
takes "either an ISO-8601 duration or an ``HH:MM:SS`` clock string", that a clock
string is read **from the left as hours**, and that the wrong-by-a-factor-of-sixty
form is dangerous precisely because it *loads*: ``15:00`` on
``ASSISTANT_CALENDAR_READER_INTERVAL`` arms a read every fifteen **hours** and
nothing refuses it. Nothing pinned any of that. ``test_calendar_settings.py``'s
one environment-path duration case sets ``PT1H`` — a spelling in which
hours-versus-minutes cannot be got wrong — and every other ``PT`` literal under
``tests/readers/`` is a ``DURATION:`` property inside an ``.ics`` fixture rather
than a settings load.

**The claim is about the loader, so the cases load through the loader.** Each one
puts the text an operator would export into the environment and reads the field
off a real :class:`~ai_assistant.core.config.Settings`, because the subject is what
``ASSISTANT_CALENDAR_READER_INTERVAL=15:00`` does — not what
``timedelta(hours=15)`` does, which is not in doubt and is what a constructor
argument would have asserted.

**This is batch #1283's rule discharged rather than restated.** That batch's
finding was that a prose claim about behaviour goes stale silently: PR #1284
replaced a duration paragraph that had been wrong since PR #1020 (#1063), and PR
#1289 then corrected the *cadence* the replacement derived from it — an
arithmetic slip in the same paragraph, which a pinned ``timedelta`` would have
caught mechanically. The remedy the batch names for a claim worth keeping is to
**test-pin** it, and an independent reviewer raised this gap four times across two
PRs (``minor``, ``major``, ``major``, ``minor``) before it was taken. So the
figures below are asserted as durations rather than as any derived reads-per-day
rate: a derived rate is the thing that went wrong, and it is derived here by the
reader of the failure message instead.

**The refusals are asserted by pydantic's error ``type`` rather than by its
rendered string**, which is the same brittleness one level down and would fail on
a wording change that left every documented behaviour intact. The single
exception is :func:`test_a_bare_number_of_seconds_names_an_identifier_nobody_typed`,
which asserts the word ``day`` — because the note *quotes* that word to an
operator (#981) as the one thing most likely to stop them, so a release that
changed it makes the note wrong and the failure is the signal to rewrite the
paragraph, not a defect to route around.

**Placement.** A module of its own rather than more cases in
``test_calendar_settings.py``: that module's subject is ADR-0093 §7a's
configuration matrix — which states are coherent, which bounds hold — whereas
every case here is about a *spelling* reaching a field, and half of them are on
ADR-0132 §4's producer settings rather than on the reader's. #1287 named
``test_calendar_settings.py`` while the fence was elsewhere; the lane's brief
scopes the remedy to ``tests/readers/`` and leaves the file to whoever took it.

Refs #1287, #1063, #981, #1283, PR #1284, PR #1289.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.config import Settings, load_settings
from ai_assistant.core.errors import ConfigurationError

#: ``Settings.model_config``'s ``env_prefix``, in the case the loader writes it.
_PREFIX: Final = "ASSISTANT_"

#: A source for the jobs below to be armed against. Absolute and never opened —
#: existence is a run-time property under ADR-0093 §7, not a load-time one.
_SOURCE: Final = "/srv/calendars/personal.ics"

#: The interval the note's own example arms, and the one an operator copies.
_INTERVAL: Final = f"{_PREFIX}CALENDAR_READER_INTERVAL"

#: ADR-0132 §4's producer cadence — a second job over the same source, with its
#: own cross-field rule and therefore its own failure mode for one spelling.
_UPCOMING: Final = f"{_PREFIX}CALENDAR_UPCOMING_INTERVAL"

#: Every calendar duration setting a case can vary **on its own**, as
#: ``(variable, field)``. The note quantifies over "every duration setting" on this
#: chain and says the refusal is "the same for every duration setting here", so the
#: spelling cases below run over all of them rather than over the one the note's
#: example happens to arm — a promise about a set is not pinned by a case about one
#: member, and three of these use a different type alias
#: (``_DurationSetting``) from the two the note's own examples name.
#:
#: ``calendar_upcoming_interval`` is deliberately absent: it cannot be varied alone,
#: because ADR-0132 §4 ties it to the lead. It runs over the same two tables in its
#: own pair of cases below, and
#: :func:`test_the_roster_is_every_calendar_duration_setting` is what keeps the two
#: halves adding up to the whole.
_VARIED: Final = [
    pytest.param(f"{_PREFIX}CALENDAR_READER_INTERVAL", "calendar_reader_interval", id="interval"),
    pytest.param(f"{_PREFIX}CALENDAR_UPCOMING_LEAD", "calendar_upcoming_lead", id="lead"),
    pytest.param(f"{_PREFIX}CALENDAR_WINDOW_PAST", "calendar_window_past", id="window-past"),
    pytest.param(f"{_PREFIX}CALENDAR_WINDOW_FUTURE", "calendar_window_future", id="window-future"),
    pytest.param(f"{_PREFIX}CALENDAR_READ_TIMEOUT", "calendar_read_timeout", id="read-timeout"),
]

#: The spellings the note says are accepted, and what each one means. Every value
#: is inside every bound on every duration field on this chain, so a case over this
#: table observes the *parse* and never a range refusal.
_ACCEPTED: Final = [
    pytest.param("PT5M", timedelta(minutes=5), id="iso-five-minutes"),
    pytest.param("00:05:00", timedelta(minutes=5), id="clock-five-minutes"),
    pytest.param("PT15M", timedelta(minutes=15), id="iso-fifteen-minutes"),
    pytest.param("00:15:00", timedelta(minutes=15), id="clock-fifteen-minutes"),
    pytest.param("PT30S", timedelta(seconds=30), id="iso-thirty-seconds"),
    # The one the note calls out. Kept in the same table as its
    # indistinguishable-looking neighbour above, because the pair *is* the claim:
    # two strings four characters apart, sixty times apart in effect.
    pytest.param("15:00", timedelta(hours=15), id="clock-fifteen-hours"),
]

#: The spellings the note says are refused, each at the parse.
_REFUSED: Final = [
    # Two components with no hour field. The note says this is refused outright,
    # which is what makes `15:00` the dangerous one: the near-miss that fails is
    # not the near-miss that loads.
    pytest.param("5:00", id="two-component-clock"),
    # A bare number of seconds, which is the form an operator reaches for first
    # and the one the note warns about by name (#981).
    pytest.param("15", id="bare-fifteen"),
    pytest.param("300", id="bare-three-hundred"),
]


def _armed(monkeypatch: pytest.MonkeyPatch, **assignments: str) -> None:
    """Export a source plus the assignments a case is about.

    Args:
        monkeypatch: The case's own environment.
        assignments: Variable name to the text an operator would write.
    """
    monkeypatch.setenv(f"{_PREFIX}CALENDAR_READER_PATH", _SOURCE)
    for name, value in assignments.items():
        monkeypatch.setenv(name, value)


def _refusals(exc: ValidationError) -> list[str]:
    """Every error's ``type``, which is what a pydantic release keeps stable."""
    return [error["type"] for error in exc.errors()]


# --- what the note says a spelling means (readers/calendar.py) ---------------


@pytest.mark.parametrize(("spelling", "duration"), _ACCEPTED)
@pytest.mark.parametrize(("variable", "field"), _VARIED)
def test_each_documented_spelling_loads_to_the_duration_the_note_states(
    monkeypatch: pytest.MonkeyPatch,
    spelling: str,
    duration: timedelta,
    variable: str,
    field: str,
) -> None:
    """The note's table, asserted through the environment it describes.

    ``PT5M`` and ``00:05:00`` are both five minutes, ``PT30S`` is thirty seconds,
    and ``15:00`` is fifteen **hours** — the clock string read from the left. A
    tokenizer change that made the last of these fifteen minutes would leave the
    documented advice ("write the full ``HH:MM:SS`` and none of that arises")
    solving a problem nobody has while the real one went unmentioned.

    Crossed with every setting the claim is made about, because the claim is made
    about all of them: a regression confined to one field — an alias narrowed, a
    validator added ahead of the parse — would otherwise pass while the note went
    on promising the same behaviour for the rest. Each value here is inside every
    bound on every field in the roster, so what a case observes is the *parse* and
    never a range refusal.
    """
    _armed(monkeypatch, **{variable: spelling})

    assert getattr(Settings(), field) == duration


def test_a_fifteen_hour_interval_is_hours_and_is_not_fifteen_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The headline (#1063), as a duration and never as a rate.

    Asserted twice over — what it *is* and what it is not — because the failure
    this guards is an operator reading ``15:00`` as the fifteen minutes they meant,
    and a test that only pinned ``timedelta(hours=15)`` would still pass if the
    field had been renamed out from under the note.

    **As a ``timedelta`` rather than as reads-per-day**, deliberately. PR #1289
    exists because the paragraph derived a cadence figure from this value and
    derived it wrongly; pinning the derived figure here would re-arm exactly that,
    while pinning the duration makes any restatement of the cadence checkable
    against a number the loader actually produced.
    """
    _armed(monkeypatch, **{_INTERVAL: "15:00"})

    interval = Settings().calendar_reader_interval

    assert interval == timedelta(hours=15) == timedelta(seconds=54_000)
    assert interval != timedelta(minutes=15)


# --- what it refuses, and how the refusal is classified ----------------------


@pytest.mark.parametrize("spelling", _REFUSED)
@pytest.mark.parametrize(("variable", "field"), _VARIED)
def test_a_spelling_the_note_calls_refused_is_refused_at_load(
    monkeypatch: pytest.MonkeyPatch, spelling: str, variable: str, field: str
) -> None:
    """Refused as a *parse*, which is the classification the note leans on.

    ``time_delta_parsing`` says the text never became a duration — as opposed to a
    bound or a cross-field rule, which are refusals of a value that parsed fine.
    The distinction is the note's: it tells an operator that ``15`` is rejected by
    the parser while ``15:00`` is accepted by it and only sometimes caught later,
    and those two sentences are true of different code.

    **Exactly one error**, and that is the assertion doing the work on the two
    nullable fields: their annotation is a union, so a parse that reported one error
    per member would be a different operator experience for the same mistake, and
    the note describes one.
    """
    _armed(monkeypatch, **{variable: spelling})

    with pytest.raises(ValidationError) as refusal:
        Settings()

    assert _refusals(refusal.value) == ["time_delta_parsing"]
    assert refusal.value.errors()[0]["loc"] == (field,)


def test_a_bare_number_of_seconds_names_an_identifier_nobody_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#981's message, quoted to the operator and therefore pinned.

    This is the one case here that asserts rendered text, and it is deliberate. The
    note promises an operator a "parse error naming a ``"day"`` identifier nobody
    typed" and attributes it to pydantic — so the word is a documented observable
    rather than an implementation detail, and a release that changes it makes the
    note wrong. A failure here is the signal to rewrite that sentence, not a defect
    in this chain.
    """
    _armed(monkeypatch, **{_INTERVAL: "15"})

    with pytest.raises(ValidationError, match="day"):
        Settings()


def test_a_parse_refusal_reaches_an_operator_as_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``load_settings`` is the seam a hub start actually uses (ADR-0083 §5).

    Every case above constructs ``Settings`` directly, which is where the parse
    happens; this one asserts the wrapping, so a misspelled duration is a
    stay-down deployment fault with a legible class rather than a ``ValidationError``
    escaping through the composition root.
    """
    _armed(monkeypatch, **{_INTERVAL: "5:00"})

    with pytest.raises(ConfigurationError, match="invalid configuration"):
        load_settings()


# --- the producer's interval, which needs a companion to load at all ---------


@pytest.mark.parametrize(("spelling", "duration"), _ACCEPTED)
def test_the_producer_interval_takes_the_same_spellings_under_a_coherent_lead(
    monkeypatch: pytest.MonkeyPatch, spelling: str, duration: timedelta
) -> None:
    """The sixth duration setting, held to the same table as the other five.

    It is absent from :data:`_VARIED` because it cannot be varied alone — ADR-0132
    §4 requires a strictly greater lead, so an accepted spelling only *loads* beside
    a companion — and that exclusion is exactly how a field goes quietly uncovered.
    The lead is therefore computed from the case's own value and written in the one
    spelling no case here disputes, which keeps the observation on the interval.

    Without this, the producer's coverage would be ``PT5M`` and a ``15:00`` that
    never loads: ``ASSISTANT_CALENDAR_UPCOMING_INTERVAL=00:05:00`` could start
    failing while every other case in this module stayed green, and the note
    promises the clock spelling for this setting in the same breath as for the
    reader's.
    """
    lead = f"PT{int(duration.total_seconds()) * 2}S"
    _armed(monkeypatch, **{_UPCOMING: spelling, f"{_PREFIX}CALENDAR_UPCOMING_LEAD": lead})

    settings = Settings()

    assert settings.calendar_upcoming_interval == duration
    assert settings.calendar_upcoming_lead == duration * 2


@pytest.mark.parametrize("spelling", _REFUSED)
def test_the_producer_interval_refuses_the_same_spellings(
    monkeypatch: pytest.MonkeyPatch, spelling: str
) -> None:
    """And it refuses them at the parse, with no companion needed.

    A value that never became a duration cannot reach ADR-0132 §4's rule at all —
    the model validators run after the fields, so the lead is irrelevant here and
    supplying one would only hide which clause did the refusing. That is the
    distinction the case asserts: one error, ``time_delta_parsing``, on this field.
    """
    _armed(monkeypatch, **{_UPCOMING: spelling})

    with pytest.raises(ValidationError) as refusal:
        Settings()

    assert _refusals(refusal.value) == ["time_delta_parsing"]
    assert refusal.value.errors()[0]["loc"] == ("calendar_upcoming_interval",)


# --- the coherence rule, which is a different code path (ADR-0132 §4) --------


def test_the_producer_refuses_a_fifteen_hour_interval_at_stock_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The note's second claim, and the half worth pinning most (#1063).

    ``ASSISTANT_CALENDAR_UPCOMING_INTERVAL=15:00`` parses exactly as the reader's
    does — and is then refused, because ADR-0132 §4 requires the lead to be
    **strictly greater** than the interval and the lead's default is thirty
    minutes. So the difference between "the loader catches this" and "it does not"
    is which of two settings the operator typed it on, which is the whole reason
    the note says so out loud.

    ``value_error`` rather than ``time_delta_parsing`` is the load-bearing part:
    this is a model validator refusing a value that parsed perfectly well, not the
    parser refusing the text. A future guard that rejected the *form* would make
    the note's "that is a coherence rule about the two settings, not a guard on the
    form" false while every other case in this module stayed green.
    """
    _armed(monkeypatch, **{_UPCOMING: "15:00"})

    with pytest.raises(ValidationError, match="strictly greater") as refusal:
        Settings()

    assert _refusals(refusal.value) == ["value_error"]


def test_the_same_spelling_on_the_ingestion_cadence_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The contrast the coherence case needs to mean anything.

    One text, two settings, opposite outcomes: nothing refuses fifteen hours
    between reads, because ingestion has no second setting to be incoherent with
    (ADR-0093 §7a's matrix is a path and an interval). Armed together here so the
    pair is one observation — a change that made both refuse, or both load, breaks
    this rather than leaving two independent cases each still true of one half.
    """
    _armed(monkeypatch, **{_INTERVAL: "15:00", _UPCOMING: "PT5M"})

    settings = Settings()

    assert settings.calendar_reader_interval == timedelta(hours=15)
    assert settings.calendar_upcoming_interval == timedelta(minutes=5)


def test_an_armed_producer_without_a_source_is_refused_before_the_lead_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Why the coherence case exports a path it never reads.

    ``calendar_upcoming_interval`` set with no ``calendar_reader_path`` is refused
    as an armed producer with nothing to read (ADR-0132 §4) — a different validator
    with a different message, reached first. Without this case a later reordering
    could make the coherence case above pass for the wrong reason, since both
    refusals are ``value_error`` on the model.
    """
    monkeypatch.setenv(_UPCOMING, "15:00")

    with pytest.raises(ValidationError, match="needs a source to read"):
        Settings()


# --- the roster is the whole of what "every duration setting" means ----------


def test_the_roster_is_every_calendar_duration_setting() -> None:
    """A seventh calendar duration added later fails here rather than going unpinned.

    The note's promise is universally quantified — "every duration setting takes
    either an ISO-8601 duration or an ``HH:MM:SS`` clock string" — so a module that
    pinned a hand-written list would answer that promise for as long as the list
    happened to be complete and silently stop the day it was not. The set is
    therefore read off :class:`Settings` itself and compared, which makes the
    quantifier the test's subject instead of the author's memory.

    ``calendar_upcoming_interval`` is on the right of the comparison rather than in
    the roster because it cannot be varied alone: ADR-0132 §4 requires a strictly
    greater lead, so a spelling case on it is a case about two settings. It is
    covered by :func:`test_the_producer_interval_takes_the_same_spellings_under_a_
    coherent_lead` and its refusal case, over the same two tables — named here
    rather than excluded by a predicate, which would also have swallowed a seventh.
    """
    durations = {
        name
        for name, field in Settings.model_fields.items()
        if name.startswith("calendar_") and field.annotation in (timedelta, timedelta | None)
    }
    roster = {str(case.values[1]) for case in _VARIED}

    assert roster | {"calendar_upcoming_interval"} == durations
