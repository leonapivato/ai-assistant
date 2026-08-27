"""``assistant spend``: ADR-0194 §6's rendering, clause by clause.

The direct model is ``test_cli_invocations.py``, which is ``test_cli_reads.py`` one
store over — this is a fourth read on the same trail, so a door that differed would
be a difference the contract does not have. What is *not* mirrored is what this
value adds: two absences that must not be collapsed into one, a consequence line
that follows from the **ceiling** and never from the absence of a total, and a pair
of period boundaries that must be rendered from the value's own offsets and never
from this process's zone.

**Driven through a scripted engine rather than a real ledger** for that module's
reason: what is under test is the adapter's rendering of what the operation hands
back, and both the order and the boundaries are the *producer's* guarantee (golden
rule 3). ADR-0194 §11 puts the producer obligation on the paired lane and the shared
suite; what lands here is everything the renderer is free to get wrong.

**The zone database is made unreachable in one case, deliberately.** ADR-0194 §5
carries resolved offsets rather than an IANA zone name precisely so that acceptance
and rendering do not depend on the consumer's installed ``tzdata`` — and a case that
merely used a different zone would pass against a renderer that resolved one.

Refs: ADR-0194 §5, §6, §11.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import StringIO
from typing import Final

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import SpendUndeterminedError
from ai_assistant.core.types import SpendPeriod, SpendTotal
from ai_assistant.interfaces import cli
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire.errors import HubUnavailableError

#: The instant every fixture's day opens at, so what a case asserts is the value's
#: rendering rather than the run's clock.
_AT: Final = datetime(2026, 3, 3, tzinfo=UTC)

#: Kiritimati's offset — the widest positive one in force today, and far enough from
#: UTC that a renderer using its own zone prints a different **date**, not merely a
#: different hour.
_FAR_EAST: Final = timedelta(hours=14)


def _total(  # noqa: PLR0913 — one keyword per field ADR-0194 §5 fixes on the model
    period: SpendPeriod = SpendPeriod.CALENDAR_DAY,
    *,
    start: datetime = _AT,
    end: datetime | None = None,
    offset: timedelta = timedelta(0),
    end_offset: timedelta | None = None,
    currency: str | None = "USD",
    ceiling: Decimal | None = None,
    accounted: Decimal | None = Decimal("0"),
) -> SpendTotal:
    """One period total, in the shape ADR-0194 §5 fixes."""
    return SpendTotal(
        period=period,
        period_start=start,
        period_end=end if end is not None else start + timedelta(days=1),
        start_offset=offset,
        end_offset=end_offset if end_offset is not None else offset,
        currency=currency,
        ceiling=ceiling,
        accounted=accounted,
    )


class _ScriptedSpendEngine(FakeAssistantEngine):
    """A hub whose spend read answers with whatever a case seeds.

    ``FakeAssistantEngine`` is otherwise untouched, so what the adapter is handed is
    the contract's own shape. The order is the *ledger's* guarantee and not something
    the adapter may re-establish, so a case that wants the wrong order seeds it.
    """

    def __init__(self, *totals: SpendTotal) -> None:
        """Create an engine answering with ``totals``, in that order."""
        super().__init__()
        self.totals: tuple[SpendTotal, ...] = totals
        #: Raised instead of answering.
        self.raises: BaseException | None = None

    async def spend_totals(self) -> tuple[SpendTotal, ...]:
        """Answer with the seeded pair, or raise what the case scripted."""
        self.calls.append(("spend_totals", {}))
        if self.raises is not None:
            raise self.raises
        return self.totals


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer wide enough that nothing wraps."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=400))
    return buffer


def _wire(monkeypatch: pytest.MonkeyPatch, engine: object) -> None:
    """Point the command's startup at ``engine``, at the seam every command uses."""

    async def _open() -> object:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _open)


def _flat(rendered: str) -> str:
    """The rendering with its line wrapping removed, so a case asserts sentences."""
    return " ".join(rendered.split())


def _rendered(output: StringIO, monkeypatch: pytest.MonkeyPatch, *totals: SpendTotal) -> str:
    """Run ``assistant spend`` over ``totals`` and return the flattened screen."""
    _wire(monkeypatch, _ScriptedSpendEngine(*totals))
    result = CliRunner().invoke(cli.app, ["spend"])
    assert result.exit_code == 0
    return _flat(output.getvalue())


# --- the command's own token (§6, §11) ---------------------------------------


def test_the_command_is_invoked_as_assistant_spend(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0194 §6 decides the token, and §11 has it driven **by** the token.

    "A command's token is the whole of its public invocation contract — a user's
    script binds to it", and a suite reaching the renderer through its Python
    function alone leaves the one thing a user binds to untested. ``spend``,
    ``spending`` and ``spend-totals`` would each satisfy a clause that only described
    the rendering.
    """
    _wire(monkeypatch, _ScriptedSpendEngine(_total(), _total(SpendPeriod.CALENDAR_MONTH)))

    result = CliRunner().invoke(cli.app, ["spend"])

    assert result.exit_code == 0
    assert "Today" in _flat(output.getvalue())


def test_the_token_appears_in_the_surfaces_own_help() -> None:
    """§11: "the token appears in the CLI's own help output"; a rename would pass otherwise."""
    result = CliRunner().invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    assert "spend" in result.output


def test_the_command_takes_no_argument_and_no_option() -> None:
    """§6 fixes it as taking neither, so an unexpected argument is refused."""
    result = CliRunner().invoke(cli.app, ["spend", "--limit", "5"])

    assert result.exit_code != 0


# --- the order, which the ledger owns and the adapter may not re-establish ---


def test_the_two_periods_are_rendered_in_the_order_they_arrived(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0194 §5's fixed order, asserted through the rendering (§11).

    The consumer group asserts the same order the shared suite pins on the producer.
    A renderer looking each entry up by its ``period``, or sorting them, would answer
    correctly here and hide a producer that returned the month first.
    """
    rendered = _rendered(
        output,
        monkeypatch,
        _total(SpendPeriod.CALENDAR_DAY, accounted=Decimal("1")),
        _total(SpendPeriod.CALENDAR_MONTH, accounted=Decimal("2")),
    )

    assert rendered.index("Today") < rendered.index("This month")


# --- ADR-0194 §5's two absences, which must not be collapsed -----------------


def test_no_currency_configured_says_so_and_states_no_total(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first absence: no currency, so no sum was attempted (§5, §6).

    A renderer collapsing §5's two absences into one message passes every other
    clause here and tells a user "no total" while their calls are being refused.
    """
    rendered = _rendered(
        output,
        monkeypatch,
        _total(currency=None, ceiling=None, accounted=None),
        _total(SpendPeriod.CALENDAR_MONTH, currency=None, ceiling=None, accounted=None),
    )

    assert "No spend currency is configured" in rendered
    assert "Not measurable" not in rendered


def test_an_indeterminate_period_with_a_ceiling_says_nothing_further_will_run(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second absence, and §6's consequence beside it.

    ``currency`` present with ``accounted=None`` means the period could not be
    measured; and where **that period's own** ceiling is present, §6 requires the
    surface to state that no further call in it will be admitted.
    """
    rendered = _rendered(
        output,
        monkeypatch,
        _total(ceiling=Decimal("10"), accounted=None),
        _total(SpendPeriod.CALENDAR_MONTH, ceiling=Decimal("100"), accounted=None),
    )

    assert "Not measurable" in rendered
    assert rendered.count("Nothing further will run") == 2
    assert "No spend currency is configured" not in rendered


def test_an_indeterminate_period_with_no_ceiling_states_no_such_consequence(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§6's hardest half, and §11 drives it as the periods **disagreeing**.

    An unpriced completion in an *earlier* day of the current month makes the month
    indeterminate and leaves the day measurable. With only the day ceiling
    configured, ADR-0194 §2 refuses nothing on the month — so §6's "no further call"
    line is **absent** there and present on a period that does carry one.

    A renderer printing that line from the absence of ``accounted`` alone tells a
    user their calls are blocked when they are not.
    """
    rendered = _rendered(
        output,
        monkeypatch,
        _total(ceiling=Decimal("10"), accounted=Decimal("3")),
        _total(SpendPeriod.CALENDAR_MONTH, ceiling=None, accounted=None),
    )

    assert "Not measurable" in rendered
    assert "Nothing further will run" not in rendered
    assert "you have set no ceiling for this period" in rendered


# --- the zero ceiling, carried the rest of the way (§11) ---------------------


def test_a_ceiling_of_zero_is_rendered_as_a_ceiling_and_never_as_none(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0194 §11: the value that makes a falsiness test visible.

    A zero ceiling is the configuration that refuses the most, so it is the one where
    a renderer saying "no ceiling" is furthest from the truth — and the bug is
    invisible at every other ceiling value.
    """
    rendered = _rendered(
        output,
        monkeypatch,
        _total(ceiling=Decimal("0"), accounted=Decimal("0")),
        _total(SpendPeriod.CALENDAR_MONTH, ceiling=Decimal("0"), accounted=Decimal("0")),
    )

    assert "of a ceiling of 0 USD" in rendered
    assert "no ceiling set" not in rendered


def test_a_zero_ceiling_on_an_indeterminate_period_still_carries_the_consequence(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§11 drives the indeterminate case at that same configuration.

    The ceiling is present, so §6 requires the line — and a producer or renderer
    testing falsiness drops it exactly here.
    """
    rendered = _rendered(
        output,
        monkeypatch,
        _total(ceiling=Decimal("0"), accounted=None),
        _total(SpendPeriod.CALENDAR_MONTH, ceiling=Decimal("0"), accounted=None),
    )

    assert rendered.count("Nothing further will run") == 2
    assert "ceiling of 0 USD" in rendered


# --- the bounds, rendered from the value's own offsets (§5, §6, §11) ---------


def test_each_bound_renders_from_its_own_offset_and_not_from_the_clients_zone(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0194 §5: the offsets are the whole of what a renderer needs.

    The value was computed in a ``+14:00`` zone, so its civil day opens on the
    **previous** UTC date. A renderer using its own configuration would print the
    UTC instant and the wrong date with it.
    """
    rendered = _rendered(
        output,
        monkeypatch,
        _total(start=datetime(2026, 3, 2, 10, 0, tzinfo=UTC), offset=_FAR_EAST),
        _total(
            SpendPeriod.CALENDAR_MONTH,
            start=datetime(2026, 2, 28, 10, 0, tzinfo=UTC),
            offset=_FAR_EAST,
        ),
    )

    assert "2026-03-03 00:00:00 +14:00" in rendered
    assert "2026-03-02 10:00:00 +00:00" not in rendered


def test_the_two_ends_of_one_period_may_carry_different_offsets(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5: two offsets rather than one, for the period containing a transition.

    "A single offset would misrender exactly the periods that rule was written to get
    right", so each bound is printed from its own.
    """
    rendered = _rendered(
        output,
        monkeypatch,
        _total(
            start=datetime(2026, 3, 28, 23, 0, tzinfo=UTC),
            end=datetime(2026, 3, 29, 22, 0, tzinfo=UTC),
            offset=timedelta(hours=1),
            end_offset=timedelta(hours=2),
        ),
        _total(SpendPeriod.CALENDAR_MONTH),
    )

    assert "2026-03-29 00:00:00 +01:00" in rendered
    assert "2026-03-30 00:00:00 +02:00" in rendered


def test_an_offset_carrying_seconds_is_rendered_unrounded(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5: "seconds included, and not rounded to a minute".

    ``Asia/Manila``'s ``-15:56:08`` is a real historical offset a ``SpendTotal`` may
    carry, and a renderer rounding it prints an offset the clock contract says was
    never in force.
    """
    manila = -timedelta(hours=15, minutes=56, seconds=8)
    rendered = _rendered(
        output,
        monkeypatch,
        _total(start=datetime(1844, 12, 31, 16, 0, tzinfo=UTC), offset=manila),
        _total(SpendPeriod.CALENDAR_MONTH),
    )

    assert "-15:56:08" in rendered


@pytest.mark.parametrize(
    ("offset", "bound", "label"),
    [
        (timedelta(microseconds=500_000), "2026-03-02 10:00:00.500000", "+00:00:00.500000"),
        (timedelta(microseconds=-500_000), "2026-03-02 09:59:59.500000", "-00:00:00.500000"),
    ],
)
def test_a_sub_second_offset_is_neither_truncated_nor_re_signed(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, offset: timedelta, bound: str, label: str
) -> None:
    """§5's "at whatever resolution it has", one resolution below the case above.

    ``SpendTotal``'s field validator accepts an offset at any ``timedelta``
    resolution, and its cross-field rule exists so that "a renderer performs exactly
    those two additions" — which is a claim that the rendering is **total** over what
    the type accepts. Reading the offset through ``total_seconds()`` was not: it
    truncated ``timedelta(microseconds=-500_000)`` to ``+00:00``, sign and all, and
    printed a boundary half a second from the one the ledger used.

    **No zone database produces such an offset**, and that is why this is a
    parametrized pair rather than a rewritten contract: what closes it is not that
    the value is expected but that the truncation was silent and its direction wrong.
    The negative arm is the one that mattered — a truncating renderer got the sign
    from a rounded zero.
    """
    rendered = _rendered(
        output,
        monkeypatch,
        _total(start=datetime(2026, 3, 2, 10, 0, tzinfo=UTC), offset=offset),
        _total(SpendPeriod.CALENDAR_MONTH),
    )

    assert bound in rendered
    assert label in rendered


def test_the_rendering_is_identical_under_two_hostile_local_zones(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5's whole reason for carrying offsets instead of an IANA zone name.

    Acceptance and rendering must not depend on the **consumer's** configuration:
    a frame carrying a zone *name* carries not the rule-set that named it, so a hub
    on one revision and a client on another disagree about the boundaries of the
    same civil day (``Asia/Gaza`` is the live example), and a test suite running
    against one installed ``tzdata`` could not have caught it.

    Driven as an **identity** between two runs under two very different local zones,
    which is what catches the shape a different-offset fixture does not: a renderer
    reaching for ``astimezone()`` with no argument resolves the *process's* zone,
    prints a plausible-looking instant, and differs between these two runs.
    """
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    time.tzset()
    first = _rendered(
        output, monkeypatch, _total(offset=_FAR_EAST), _total(SpendPeriod.CALENDAR_MONTH)
    )

    output.truncate(0)
    output.seek(0)
    monkeypatch.setenv("TZ", "Pacific/Honolulu")
    time.tzset()
    second = _rendered(
        output, monkeypatch, _total(offset=_FAR_EAST), _total(SpendPeriod.CALENDAR_MONTH)
    )

    assert first == second
    assert "+14:00" in first


def test_a_bound_at_the_edge_of_the_representable_range_still_renders(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0194 §1's clamps, on the rendering half §11 assigns to this group.

    Where a period's bound is not representable the producer clamps it, and §5's
    bound-plus-offset invariant is what makes this rendering total: the renderer
    performs exactly those two additions, so a clamped bound must still print rather
    than overflow.
    """
    latest = datetime.max.replace(tzinfo=UTC) - timedelta(hours=14)
    rendered = _rendered(
        output,
        monkeypatch,
        _total(
            start=datetime(9999, 12, 30, 10, 0, tzinfo=UTC),
            end=latest,
            offset=_FAR_EAST,
            end_offset=_FAR_EAST,
        ),
        _total(SpendPeriod.CALENDAR_MONTH, start=datetime(1, 1, 2, tzinfo=UTC), offset=-_FAR_EAST),
    )

    assert "9999-12-31 00:00:00 +14:00" in rendered
    assert "-14:00" in rendered


# --- what the surface must never say (§6) ------------------------------------


def test_no_total_is_presented_as_an_amount_billed_owed_or_charged(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§6: "No surface presents an accounted total as an amount billed, owed, or charged".

    Asserted as a claim rather than as a letter: the positive sentence the footer
    states is what makes the negatives checkable, so both halves are here.
    """
    rendered = _rendered(
        output,
        monkeypatch,
        _total(accounted=Decimal("7.5"), ceiling=Decimal("10")),
        _total(SpendPeriod.CALENDAR_MONTH, accounted=Decimal("7.5")),
    )

    assert "not a bill" in rendered
    assert "not an amount owed" in rendered
    for barred in ("billed", "charged", "invoice", "you owe"):
        assert barred not in rendered.lower(), barred


# --- the two transport failures, rendered as themselves (§6) -----------------


@pytest.mark.parametrize(
    "failure",
    [
        HubUnavailableError("no hub is listening at /tmp/hub.sock"),
        SpendUndeterminedError("the clock could not be read"),
    ],
    ids=["transport", "budget"],
)
def test_a_failure_is_reported_and_exits_non_zero(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    """Both reach the adapter and each renders as itself (ADR-0194 §6).

    They are different facts — one is "there is no hub", the other "your spend could
    not be measured" — and the command's job is to render the one it was given rather
    than to fold either into the other.
    """
    engine = _ScriptedSpendEngine()
    engine.raises = failure
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["spend"])

    assert result.exit_code != 0
    assert str(failure) in _flat(output.getvalue())
