"""The CLI's transcript surface: ADR-0225 §8's group, and what §6 obliges it to say.

The direct model is ``test_cli_reads.py``, and one thing is *not* mirrored, which is
the point of the module: the two obligations here are about what the surface says
**without being asked**. ADR-0225 §8 requires a surface rendering archive content to
state that what it shows is a record of what was said "and not what the assistant
believes or retrieves", and §6 requires the size report "beside every read, unasked"
— "a lane that ships the reads without the report has not shipped this section". Both
are unasked-for output, so neither is reachable by any case that only checks what a
command returns; they are asserted here on every read, empty results included.

**Driven through the canonical fakes, with a real archive behind them.** The engine
is ``FakeAssistantEngine`` holding a ``FakeTranscriptArchive``, so the order, the
matching predicate and the excerpt bound are the *archive's* guarantees arriving at
the adapter rather than a script's imitation of them (golden rule 3). What is under
test is the adapter: what it prints, what it prints unasked, what it asks before it
destroys, and which exit code it maps an outcome to. The seven operations' own
refusals and ordering are pinned in ``tests/orchestration/`` by the shared engine
contract, and the archive's predicates in ``tests/archive/``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from io import StringIO
from typing import TYPE_CHECKING, Final

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.types import ExchangeDisposition, TranscriptEntry
from ai_assistant.interfaces import cli
from ai_assistant.testing import FakeAssistantEngine, FakeTranscriptArchive

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine

#: When the seeded turns happened. Fixed, so what a case asserts is the rendering of
#: a value rather than a property of the run's clock.
_AT: Final = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

#: The sentence ADR-0225 §8 obliges every archive rendering to carry. Matched on the
#: two halves that carry the meaning rather than on the whole line, so rewording the
#: prose does not fail the case while dropping the *claim* does.
_NOTICE: Final = ("record of what was said", "Not what I believe")


def _entry(  # noqa: PLR0913 — one keyword per field of the model this builds, so a case varies exactly the one it is about
    address: str = "c1:1",
    *,
    conversation: str = "c1",
    ordinal: int = 1,
    at: datetime | None = None,
    asked: str | None = "where did I put the lease",
    replied: str | None = "in the blue folder, you said",
    disposition: ExchangeDisposition = ExchangeDisposition.NO_ACTION_NEEDED,
) -> TranscriptEntry:
    """One archived turn, with every field defaulted to something a case can vary."""
    return TranscriptEntry(
        address=address,
        conversation_id=conversation,
        ordinal=ordinal,
        occurred_at=_AT if at is None else at,
        asked=asked,
        replied=replied,
        disposition=disposition,
    )


def _engine(*entries: TranscriptEntry) -> FakeAssistantEngine:
    """The canonical fake over an archive holding ``entries``.

    The archive is the canonical fake too, so the adapter is handed what a conforming
    implementation would hand it. ``hold`` is how it is seeded because the seam the
    engine holds carries no ``append`` (ADR-0225 §10) — which is the fence working,
    not an inconvenience to route around.
    """
    engine = FakeAssistantEngine()
    engine.archive = FakeTranscriptArchive()
    engine.archive.hold(*entries)
    return engine


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer wide enough that nothing wraps."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=400))
    return buffer


def _wire(monkeypatch: pytest.MonkeyPatch, engine: AssistantEngine) -> None:
    """Point the transcript commands' startup at ``engine`` (ADR-0084 §6's seam)."""

    async def _open() -> AssistantEngine:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _open)


def _flat(rendered: str) -> str:
    """The rendering with its line wrapping removed, so a case asserts sentences."""
    return " ".join(rendered.split())


#: One ANSI SGR sequence — ``test_cli_reads.py``'s pattern, for its reason: ``--help``
#: is rendered by Typer's own console, which takes its width and colour from the
#: environment, so a phrase asserted across a wrap is absent from the string while
#: being plainly on the screen.
_SGR: Final = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _help_text(rendered: str) -> str:
    """Help output as flowing words: no colour, no borders, no wrapping."""
    return " ".join(_SGR.sub("", rendered).replace("│", " ").split())


def _run(
    output: StringIO,
    monkeypatch: pytest.MonkeyPatch,
    engine: AssistantEngine,
    argv: list[str],
    *,
    stdin: str | None = None,
) -> tuple[int, str]:
    """Run one transcript command over ``engine`` and return its code and screen."""
    _wire(monkeypatch, engine)
    result = CliRunner().invoke(cli.app, argv, input=stdin)
    return result.exit_code, _flat(output.getvalue())


# --- ADR-0225 §8: the group is its own, and it says what it is ---------------


def test_the_archive_lives_on_its_own_command_and_not_as_a_mode_of_either_neighbour() -> None:
    """§8: "their **own** command, distinct from ``beliefs`` and from ``conversations``".

    Asserted from both directions, because only the pair says what the clause means.
    ``transcript`` exists as a group of its own; and neither neighbour has grown a
    transcript mode, which is the shape §8 forbids — "no surface presents a transcript
    entry as a belief, as something the assistant holds, or as evidence for anything",
    and an ``--transcript`` flag on ``beliefs`` would be exactly that.
    """
    top = _help_text(CliRunner().invoke(cli.app, ["--help"]).output)
    assert "transcript" in top

    for neighbour in ("beliefs", "conversations"):
        rendered = _help_text(CliRunner().invoke(cli.app, [neighbour, "--help"]).output)
        assert "transcript" not in rendered.lower()


@pytest.mark.parametrize(
    "argv",
    [
        ["transcript", "search", "lease"],
        ["transcript", "conversation", "c1"],
        ["transcript", "show", "c1:1"],
        ["transcript", "export"],
    ],
)
def test_every_read_states_what_it_is_showing_without_being_asked(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    """§8: the statement is owed on **every** read, and nothing asks for it.

    Parametrised over all four rather than asserted once, because the obligation is
    on the surface rather than on one command: a lane adding a fifth rendering would
    have to add a row here, which is the cheapest way for the clause to keep binding.
    """
    code, screen = _run(output, monkeypatch, _engine(_entry()), argv)

    assert code == 0
    for phrase in _NOTICE:
        assert phrase in screen


@pytest.mark.parametrize(
    "argv",
    [
        ["transcript", "search", "nothing-matches-this"],
        ["transcript", "conversation", "c9"],
        ["transcript", "export"],
    ],
)
def test_an_empty_read_still_states_what_it_is_and_still_reports_the_size(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    """§6 and §8 over the case a "render it beside the rows" implementation misses.

    A surface that hung either on the row loop drops both the moment nothing matched
    — and an empty archive is exactly when the size figure is least interesting and
    the *habit* of printing it matters most, because §6's whole purpose is that the
    deferred cap's trigger is a figure somebody has rather than one nobody produces.
    """
    code, screen = _run(output, monkeypatch, _engine(), argv)

    assert code == 0
    assert _NOTICE[0] in screen
    assert "Archive:" in screen


# --- ADR-0225 §6: the size report, beside every read, unasked ----------------


@pytest.mark.parametrize(
    "argv",
    [
        ["transcript", "search", "lease"],
        ["transcript", "conversation", "c1"],
        ["transcript", "show", "c1:1"],
        ["transcript", "export"],
    ],
)
def test_every_read_carries_the_size_report_beside_it(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    """§6, and §13 item 17's surface half: "a rendered archive read carries the figure
    beside it without being asked".

    Nothing in the argv asks for it, which is the assertion: §6 gives the report a
    surface operation of its own precisely so a renderer cannot leave it out, and a
    CLI that offered it as a seventh command the user must think to run would be a
    figure nobody ever produces.
    """
    code, screen = _run(output, monkeypatch, _engine(_entry()), argv)

    assert code == 0
    assert "Archive:" in screen
    assert "1 turn readable" in screen


def test_the_two_size_figures_are_both_shown_and_are_never_netted(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§6: "a report that netted the two would hide exactly the growth the cap exists
    to catch".

    So both are asserted present and separately legible. They answer different
    questions — ``entries`` is what the reads would return, ``stored_bytes`` is what
    is on the disk with hidden and unreclaimed entries included — and a surface
    printing one, or a difference, would leave the trigger unmeasurable.
    """
    _, screen = _run(
        output,
        monkeypatch,
        _engine(_entry(), _entry("c1:2", ordinal=2)),
        [
            "transcript",
            "export",
        ],
    )

    assert "2 turns readable" in screen
    assert "bytes on disk" in screen


def test_the_byte_total_is_printed_exactly_and_not_only_rounded(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§6 puts a **measurement** on the screen, so the exact count is never replaced.

    A surface that printed "1.2 MiB" alone would be reporting a figure whose next
    reading a user cannot compare against this one — which is the instrument blunted
    at the one place the ADR requires it to be sharp.
    """
    _, screen = _run(output, monkeypatch, _engine(_entry()), ["transcript", "export"])

    assert re.search(r"[\d,]+ bytes on disk", screen)


# --- ADR-0225 §7: what each read renders ------------------------------------


def test_a_search_hit_carries_its_address_so_the_entry_can_be_read_whole(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7's show-a-hit-then-read-the-entry split, at the surface that exercises it.

    "Splitting it makes the address load-bearing in the surface the user actually
    touches, which is the cheapest possible way for §3's stability to be exercised
    rather than asserted" — so a hit that did not print its address would leave the
    second act unreachable.
    """
    _, screen = _run(output, monkeypatch, _engine(_entry()), ["transcript", "search", "lease"])

    assert "c1:1" in screen
    assert "transcript show" in screen or "1 match" in screen


def test_a_shortened_excerpt_says_so_and_points_at_the_whole_turn(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7: ``elided`` is rendered rather than dropped.

    A user cannot otherwise tell a whole short turn from a window cut out of a long
    one, and the excerpt bound would read as the turn itself — which is the one way a
    bounded rendering can mislead about the thing it is bounding.
    """
    long_turn = _entry("c1:9", ordinal=9, asked="lease " + ("x" * 2000), replied="mm")
    _, screen = _run(output, monkeypatch, _engine(long_turn), ["transcript", "search", "lease"])

    assert "Shortened" in screen
    assert "transcript show" in screen


def test_reading_one_turn_shows_both_halves_whole(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7: the addressed read "elides, truncates and summarises nothing"."""
    code, screen = _run(output, monkeypatch, _engine(_entry()), ["transcript", "show", "c1:1"])

    assert code == 0
    assert "where did I put the lease" in screen
    assert "in the blue folder, you said" in screen


@pytest.mark.parametrize(
    ("absent", "expected"),
    [("asked", "You said nothing"), ("replied", "I said nothing")],
)
def test_an_absent_half_is_stated_rather_than_skipped(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, absent: str, expected: str
) -> None:
    """ADR-0225 §1: either half may be absent, and the two absences mean different things.

    A turn with no user words is one this system drove on its own — a parked step's
    resolution, whose utterance was archived at its own address — and a turn with no
    reply produced none. A renderer that skipped the empty half would show the user a
    turn they cannot place.
    """
    entry = _entry(**{absent: None})  # type: ignore[arg-type]  # one field, by name
    _, screen = _run(output, monkeypatch, _engine(entry), ["transcript", "show", "c1:1"])

    assert expected in screen


def test_the_disposition_is_rendered_so_a_parked_turn_does_not_read_as_ignored(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0225 §1's reason for carrying the field at all.

    "Without it a turn that parked reads in the transcript as a question nobody
    answered" — so a surface that carried the value and did not print it would leave
    the field doing nothing for the reader it was added for.
    """
    parked = _entry(disposition=ExchangeDisposition.STEP_AWAITING_CONFIRMATION, replied=None)
    _, screen = _run(output, monkeypatch, _engine(parked), ["transcript", "show", "c1:1"])

    assert "step_awaiting_confirmation" in screen


def test_an_unknown_address_is_reported_without_saying_which_kind_of_absence(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0225 §3 and §6: never held, evicted and destroyed look the same from here.

    ``_render_no_such_conversation``'s rule one store over: a surface that told them
    apart would report on transcripts it is meant to have evicted. The exit code is
    non-zero because the user named something and got nothing.
    """
    code, screen = _run(output, monkeypatch, _engine(_entry()), ["transcript", "show", "c9:9"])

    assert code != 0
    assert "No transcript is held" in screen
    assert "may never have existed" in screen


def test_a_conversation_is_rendered_in_the_order_the_engine_handed_over(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7: ordinal order, and the adapter re-sorts nothing (golden rule 3).

    The archive is seeded out of order so that a surface establishing the order
    itself and one relaying it cannot both pass.
    """
    engine = _engine(
        _entry("c1:3", ordinal=3, asked="third"),
        _entry("c1:1", ordinal=1, asked="first"),
        _entry("c1:2", ordinal=2, asked="second"),
    )
    _, screen = _run(output, monkeypatch, engine, ["transcript", "conversation", "c1"])

    assert screen.index("first") < screen.index("second") < screen.index("third")


# --- ADR-0085 §9 at the parse boundary --------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["transcript", "search", "lease", "--limit", "0"],
        ["transcript", "conversation", "c1", "--limit", "0"],
        ["transcript", "export", "--limit", "0"],
        ["transcript", "export", "--offset", "-1"],
    ],
)
def test_a_page_argument_the_archive_would_refuse_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    """ADR-0225 §7 and ADR-0102 §10, caught during Typer's parameter parsing.

    A ``ValueError`` is not an ``AssistantError``, so one escaping the command's own
    ``except (AssistantError, TransportError)`` boundary would be an uncaught
    traceback with no controlled exit code — the failure ADR-0042 §7 forbids. Catching
    it at the parse boundary makes it exit 2, **and no engine is built at all**, which
    is what the empty call log says.
    """
    engine = _engine(_entry())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, argv)

    assert result.exit_code == 2
    assert engine.calls == []


# --- ADR-0225 §5: the two destroys, each with its ceremony -------------------


def test_destroying_one_turn_shows_it_before_it_asks(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0073 §5's show-then-confirm, at the unit this destroy is about: one turn.

    A whole turn *is* what a person can judge at a prompt, which is why this one shows
    the content where ``forget-conversation`` shows a count.
    """
    engine = _engine(_entry())
    code, screen = _run(output, monkeypatch, engine, ["transcript", "forget", "c1:1"], stdin="n\n")

    assert code == 0
    assert "where did I put the lease" in screen
    assert "Left alone" in screen
    assert "c1:1" in engine.archive.recorded


def test_yes_supplies_the_answer_and_never_the_rendering(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0073 §5: a non-interactive approval must not destroy what was never shown.

    So ``--yes`` skips the *question* and not the display, exactly as it does on
    ``forget`` and ``forget-conversation``.
    """
    engine = _engine(_entry())
    code, screen = _run(output, monkeypatch, engine, ["transcript", "forget", "c1:1", "--yes"])

    assert code == 0
    assert "where did I put the lease" in screen
    assert "Destroyed." in screen
    assert engine.archive.recorded == {}


def test_a_turn_no_read_can_show_is_still_offered_for_destruction(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0225 §6: "a destruction is never refused on the ground that a read would
    not have shown it".

    This is the case a surface that gated its destroy on its own read gets wrong, and
    it gets it wrong in the direction ADR-0004 §6 cannot tolerate: an entry a finite
    ``transcript_archive_retention`` is hiding would be readable by nothing and
    destroyable by nothing, which is the user's right made conditional on a horizon.
    The prompt owes honesty about what it cannot show, not a refusal.
    """
    engine = _engine(_entry())
    code, screen = _run(output, monkeypatch, engine, ["transcript", "forget", "c9:9", "--yes"])

    assert "Nothing readable is held at that address" in screen
    assert "still destroys it" in screen
    assert ("forget_transcript_entry", {"address": "c9:9"}) in engine.calls
    assert code != 0  # nothing was there, which the exit code reports


def test_destroying_a_conversation_s_transcript_shows_what_is_held_and_states_the_scope(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0225 §5: show-then-confirm "at the unit the user thinks in", and no invented total.

    The page is shown and is deliberately **not** claimed to be the whole of what will
    go: the read is paged and the retention hides entries the destroy still reaches, so
    the prompt states the scope in words. A count taken from the first page would be
    read as the number about to be destroyed, which is worse than no count at all.
    """
    engine = _engine(_entry(), _entry("c1:2", ordinal=2, asked="and the keys"))
    code, screen = _run(
        output,
        monkeypatch,
        engine,
        ["transcript", "forget-conversation", "c1", "--yes"],
    )

    assert code == 0
    assert "where did I put the lease" in screen
    assert "including any not shown above" in screen
    assert "retention window is hiding" in screen
    assert "2 turn(s)" in screen
    assert engine.archive.recorded == {}


def test_a_conversation_with_nothing_readable_is_still_offered(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§6 again, at the conversation scope, and for the same reason as the address one."""
    engine = _engine(_entry())
    code, screen = _run(
        output, monkeypatch, engine, ["transcript", "forget-conversation", "c9", "--yes"]
    )

    assert "Nothing readable is held under that id" in screen
    assert ("forget_transcript_conversation", {"conversation_id": "c9"}) in engine.calls
    assert code != 0


def test_declining_the_conversation_destroy_leaves_the_transcript_alone(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal is a valid outcome and exits 0 — ``forget-conversation``'s own rule."""
    engine = _engine(_entry())
    code, screen = _run(
        output,
        monkeypatch,
        engine,
        ["transcript", "forget-conversation", "c1"],
        stdin="n\n",
    )

    assert code == 0
    assert "Left alone" in screen
    assert "c1:1" in engine.archive.recorded


def test_the_destroy_says_it_touches_no_belief(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0225 §8: nothing here presents a transcript entry as something I believe.

    The prompt is where that distinction is most likely to be missed, because the two
    commands are spelled almost alike — ``assistant forget`` destroys a belief and
    ``assistant transcript forget`` destroys a record of what was said — so the
    ceremony says which one the user is in.
    """
    _, screen = _run(
        output, monkeypatch, _engine(_entry()), ["transcript", "forget", "c1:1"], stdin="n\n"
    )

    assert "what I believe is untouched" in screen
    assert "'assistant forget' is the command for that" in screen


@pytest.mark.parametrize(
    "argv",
    [
        ["transcript", "forget", "c1:1"],
        ["transcript", "forget-conversation", "c1"],
    ],
)
def test_a_deletion_preview_is_an_archive_read_and_owes_both_obligations(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    """§6 and §8 reach the destroys' previews, because a preview *is* a rendered read.

    Both clauses are keyed on rendering rather than on a command's name — §8 binds "a
    surface rendering archive content" and §6 "every surface that renders any archive
    read" — and each ceremony reads the thing it is about and prints it. This was the
    round-1 blocker: the four reads carried both and the two previews carried neither,
    which left the rendering a user studies hardest outside the obligations, and left
    the figure absent from the moment it is most decision-relevant.

    Asserted on the **declining** path, so the case is about what was shown before the
    answer was taken rather than about anything the destruction did.
    """
    engine = _engine(_entry())

    code, screen = _run(output, monkeypatch, engine, argv, stdin="n\n")

    assert code == 0
    assert _NOTICE[0] in screen
    assert "Archive:" in screen
    assert "1 turn readable" in screen
    assert "c1:1" in engine.archive.recorded


# --- ADR-0042 §7: one error boundary ----------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["transcript", "search", "lease"],
        ["transcript", "conversation", "c1"],
        ["transcript", "show", "c1:1"],
        ["transcript", "export"],
        ["transcript", "forget", "c1:1", "--yes"],
        ["transcript", "forget-conversation", "c1", "--yes"],
    ],
)
def test_a_failing_archive_is_rendered_and_mapped_to_a_non_zero_exit(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    """Every command on this group has the one error boundary ADR-0042 §7 requires.

    Parametrised over all six because a boundary is only worth what its least-covered
    command has: a ``TranscriptArchiveError`` escaping any one of them is an uncaught
    traceback with no controlled exit code.
    """
    engine = _engine(_entry())
    engine.archive.fail()

    code, screen = _run(output, monkeypatch, engine, argv)

    assert code != 0
    assert screen  # the failure was rendered rather than raised through


# --- a break the value supplied is a continuation, and is marked (#2072) ------


def test_a_users_own_line_break_cannot_forge_a_field_of_the_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn's two halves are the one place a value's newline reaches an authored line.

    :func:`~ai_assistant.interfaces.cli._safe` replaces a value's ``\\n`` precisely so it
    cannot forge a second line (#1336), and this renderer interpolates
    :func:`~ai_assistant.interfaces.cli._safe_prose` instead — whose newlines survive,
    because a user's utterance is legitimately more than one line. So ``You:`` is one of
    the three sites on this surface where the break is the *value's*, and a user typing
    a line that looks like a field would otherwise have put a second ``Conversation:``
    under the real one.

    :func:`~ai_assistant.interfaces.cli._print` reads a break after a line's head as a
    continuation of it, wherever the break came from, so the forged field arrives behind
    the marker and reads as what it is: part of what the user said.
    """
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=200))
    forged = "  Conversation: c9"

    cli._render_transcript_entry(_entry(asked=f"where did I put the lease\n{forged}"))

    lines = buffer.getvalue().splitlines()
    assert "  You: where did I put the lease" in lines
    assert f"  {cli._CONTINUATION}{forged}" in lines
    assert forged not in lines  # it never reaches the screen as a field of the entry
    assert len([line for line in lines if line.startswith("  Conversation: ")]) == 1
