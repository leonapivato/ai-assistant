"""The CLI read surface: ADR-0186 §10's second pair, clause by clause.

The direct model is ``test_cli_decisions.py``, because §10 mints "a **second pair**
mirroring §1's" and a door that differed would be a difference the contract does
not have. What is *not* mirrored is as load-bearing: this store's order is
recording order rather than ADR-0186 §2's ``decided_at`` sort (ADR-0185 §6), its
export delivers the **horizon** rather than the history (ADR-0185 §9), and its
rendering owes six outcomes with opened-ness a function of the outcome and
**undeterminable** on one of them (ADR-0185 §1).

**Driven through a scripted engine rather than the canonical fake's own trail**,
for ``test_cli_decisions.py``'s reason one store over: what is under test is the
adapter's rendering of what the operation hands back, and the order is the
*engine's* guarantee (golden rule 3). Seeding a fake trail and letting it order the
rows would make every ordering case a test of the fake. The store's own read half
is pinned in ``tests/permissions/test_reads.py``; the operations' order, refusals
and reversal are pinned in ``tests/orchestration/`` by the contract lane.

**ADR-0186 §8's bars are weak tests and that is stated rather than hidden.** No
assertion over rendered text can prove a renderer never claims a live grant or an
event; what these catch is the specific, likely regression — "remembered" beside a
completed attempt, a last-read instant beside a standing grant — and the clause
binds whether or not a test reaches it.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from io import StringIO
from typing import Final

import pytest
from pydantic import TypeAdapter
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import OversizedValueError, ReadTrailError
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    GrantScope,
    ReadOutcome,
    SourceGrant,
    SourceReadRecord,
)
from ai_assistant.interfaces import cli
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire import TransportError

#: When the seeded attempts checked their grant. Fixed, so what a case asserts is
#: the value's rendering rather than the run's clock.
_AT = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

#: Every word for what *came of* a read that ADR-0186 §8's third clause bars, read
#: one store over: a row states what was attempted, never what any use did with it
#: (ADR-0185 §10). Matched on word boundaries, because "remembering" appears in the
#: scope phrase for ``INGEST`` — which is what the read was *for*, not what
#: happened — and a substring test would fail on prose that claims nothing.
_CONSEQUENCE_WORDS: Final = ("remembered", "learned", "stored", "notified", "told")


# --- the subject -------------------------------------------------------------


def _record(  # noqa: PLR0913 — a record's own fields, each of which some case varies
    record_id: str,
    *,
    source: str = "calendar",
    use: GrantScope = GrantScope.INGEST,
    at: datetime | None = None,
    outcome: ReadOutcome = ReadOutcome.COMPLETED,
    grant: str | None = "g-1",
    produced: int = 3,
) -> SourceReadRecord:
    """One recorded attempt, built field by field.

    ``grant`` defaults to a set pointer and ``produced`` to a non-zero count, so a
    case that varies ``outcome`` alone must also state what its two construction
    invariants require — which is the point: ADR-0185 §2 refuses a ``REFUSED`` row
    citing a grant and a readingless row claiming a count, and a helper that
    silently repaired either would hide the invariant from every case below.
    """
    return SourceReadRecord(
        id=record_id,
        source=source,
        use=use,
        checked_at=at if at is not None else _AT,
        outcome=outcome,
        grant=grant,
        produced=produced,
    )


def _refused(record_id: str = "r-refused", **overrides: object) -> SourceReadRecord:
    """The row ADR-0185 §7 says the trail exists for: refused, ungranted, empty."""
    fields: dict[str, object] = {"outcome": ReadOutcome.REFUSED, "grant": None, "produced": 0}
    fields.update(overrides)
    return _record(record_id, **fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


class _ScriptedReadEngine(FakeAssistantEngine):
    """A hub whose read trail is whatever a case seeds, in the order it will answer.

    ``FakeAssistantEngine`` is otherwise untouched, so what the adapter is handed is
    the contract's own shape. The two overrides do **not** re-implement ADR-0186
    §3's local refusal of ``limit``: the CLI refuses a malformed one during Typer's
    parameter parsing, before any engine exists, and the case below asserts exactly
    that by observing that no call was ever recorded.
    """

    def __init__(self, *recorded: SourceReadRecord) -> None:
        """Create an engine over ``recorded``, in the order it will answer with."""
        super().__init__()
        #: The trail, already in the operation's order — newest recorded first,
        #: which is the engine's guarantee and not something the adapter may
        #: re-establish (golden rule 3, ADR-0185 §6).
        self.recorded: tuple[SourceReadRecord, ...] = recorded
        #: Raised instead of answering ``recent_reads``.
        self.listing_raises: BaseException | None = None
        #: Raised instead of answering ``export_reads``.
        self.export_raises: BaseException | None = None

    async def recent_reads(self, *, limit: int = DEFAULT_PAGE_SIZE) -> tuple[SourceReadRecord, ...]:
        """The first ``limit`` rows — the prefix property, held by construction."""
        self.calls.append(("recent_reads", {"limit": limit}))
        if self.listing_raises is not None:
            raise self.listing_raises
        return self.recorded[:limit]

    async def export_reads(self) -> tuple[SourceReadRecord, ...]:
        """Every row the trail still holds, in the same order."""
        self.calls.append(("export_reads", {}))
        if self.export_raises is not None:
            raise self.export_raises
        return self.recorded


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer and return it.

    **Wide enough that nothing wraps**, so a case asserting what one row's line
    carries cannot be defeated by a line break. :func:`_flat` is still what the
    prose cases assert through.
    """
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=400))
    return buffer


def _wire(monkeypatch: pytest.MonkeyPatch, engine: object) -> None:
    """Point the read commands' startup at ``engine``.

    The seam is :func:`~ai_assistant.interfaces.cli._open_engine`, as it is for
    every other command on this surface (ADR-0084 §6).
    """

    async def _open() -> object:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _open)


def _flat(rendered: str) -> str:
    """The rendering with its line wrapping removed, so a case asserts sentences."""
    return " ".join(rendered.split())


def _listing(output: StringIO, monkeypatch: pytest.MonkeyPatch, *recorded: SourceReadRecord) -> str:
    """Run ``assistant reads`` over ``recorded`` and return the flattened screen."""
    _wire(monkeypatch, _ScriptedReadEngine(*recorded))
    result = CliRunner().invoke(cli.app, ["reads"])
    assert result.exit_code == 0
    return _flat(output.getvalue())


# --- §9/§10: the export is one faithful JSON document ------------------------


def test_the_export_re_validates_and_carries_no_annotation_of_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§9's faithful-copy clause over this store, in both directions.

    The horizon is the thing a helpful adapter would annotate here — a
    ``"complete": false`` beside the members, or a wrapper object naming the cap —
    and either would fail this re-validation outright, because the model sets
    ``extra="forbid"``. So the export would stop being an export. The *words* for
    the horizon are ``assistant export-reads``' own, which the case below asserts.
    """
    rows = (
        _record("r-1", outcome=ReadOutcome.COMPLETED),
        _refused("r-2"),
        _record("r-3", outcome=ReadOutcome.FAILED, produced=0),
    )
    _wire(monkeypatch, _ScriptedReadEngine(*rows))

    result = CliRunner().invoke(cli.app, ["export-reads"])
    assert result.exit_code == 0

    document = json.loads(result.stdout)
    assert [row["id"] for row in document] == ["r-1", "r-2", "r-3"]
    # Every member of every row, and no member of anything else: a document that
    # grew one key would re-validate only if the key were a field, and one that
    # lost a key would lose a fact the milestone says is reconstructible.
    assert set(document[0]) == {"id", "source", "use", "checked_at", "outcome", "grant", "produced"}
    assert document[1]["grant"] is None

    revalidated = TypeAdapter(tuple[SourceReadRecord, ...]).validate_python(document)
    assert revalidated == rows


def test_the_export_writes_the_document_and_nothing_else_to_standard_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§9: "one JSON document written to standard output … nothing else on that stream".

    Deliberately **without** the ``output`` fixture: what is under test is the
    stream, so the consoles are left following the runner's own ``sys.stdout`` and
    ``sys.stderr`` rather than a buffer that would make the claim true by
    construction.
    """
    _wire(monkeypatch, _ScriptedReadEngine(_record("r-1")))

    result = CliRunner().invoke(cli.app, ["export-reads"])
    assert result.exit_code == 0

    # The *whole* stream parses as one JSON document, which is the assertion §9's
    # clause reduces to: a byte of anything else on it — a heading, the horizon
    # sentence, a warning, a stray log record — makes this raise rather than merely
    # add noise.
    assert [row["id"] for row in json.loads(result.stdout)] == ["r-1"]
    assert result.stdout.endswith("]\n")
    assert result.stderr == ""


def test_a_failed_export_says_so_on_standard_error_and_writes_no_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§9's stream clause on the failure path, which is where it earns its keep.

    A partial artifact that looked complete is the one outcome §9 rules out, and a
    diagnostic on standard output is how a helpful adapter produces one: the user's
    ``> reads.json`` would hold a sentence. Nothing reaches standard output at all,
    and the exit code says the command failed.
    """
    engine = _ScriptedReadEngine(_record("r-1"))
    engine.export_raises = OversizedValueError(
        "the read trail exceeds the contract limit", limit=1024, size=99999
    )
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["export-reads"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "the read trail exceeds the contract limit" in _flat(result.stderr)


def test_an_unreachable_hub_is_reported_on_standard_error_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other error boundary: the hub the export could not even reach.

    ADR-0084 §3 keeps a transport failure legible as its own thing, and §9 keeps it
    off the artifact's stream. Both hold at once, which is what the ``to_stderr``
    parameter on the shared renderer is for.
    """

    async def _refuse() -> object:
        raise TransportError("no hub is listening")

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _refuse)

    result = CliRunner().invoke(cli.app, ["export-reads"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "not reachable" in _flat(result.stderr)


def test_an_empty_trail_exports_an_empty_array(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty record is an artifact, not an error and not an absent file."""
    _wire(monkeypatch, _ScriptedReadEngine())

    result = CliRunner().invoke(cli.app, ["export-reads"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_the_export_states_the_horizon_where_the_decision_export_states_completeness() -> None:
    """ADR-0186 §10: "the two exports are not equally complete".

    "No surface presents them as though they were", and the surface that presents
    them together is this one — two commands a user reads in the same ``--help``.
    So the read export's own help says it delivers what is **still held**, names the
    dropping of the oldest, and says which of the two records this is; the decision
    export's help still claims the whole record, and that claim stays true because
    that trail prunes nothing (#108).
    """
    reads_help = _flat(CliRunner().invoke(cli.app, ["export-reads", "--help"]).stdout)
    assert "still hold" in reads_help
    assert "deleted to make room" in reads_help
    assert "horizon and not the history" in reads_help

    decisions_help = _flat(CliRunner().invoke(cli.app, ["export-decisions", "--help"]).stdout)
    assert "Every ruling" in decisions_help
    assert "horizon" not in decisions_help


def test_the_listing_names_both_reasons_it_is_not_a_record_of_every_read() -> None:
    """The two gaps, stated together where a user meets the command.

    The horizon is one (ADR-0185 §6). ADR-0185 §5a's two fault paths are the other,
    and they are the ones a surface forgets: a recorder that raised and a
    cancellation landing after the read began each leave a read that ran with **no
    row**. §10 measures the milestone's exit over attempts "driven to an outcome
    with a recorder that answered" for exactly that reason, and §5a forbids citing
    either path as licence to leave an access unrecorded — so a surface may neither
    hide them nor lean on them. What it can do is say so, which is what makes
    "every read" a phrase this command never uses about itself.
    """
    reads_help = _flat(CliRunner().invoke(cli.app, ["reads", "--help"]).stdout)

    assert "oldest attempts are dropped as it fills" in reads_help
    assert "two faults leave no row at all" in reads_help
    assert "Show the attempts I recorded" in reads_help


# --- §9/§10: the listing's bound ---------------------------------------------


@pytest.mark.parametrize("bad", ["0", "-1", "9223372036854775808", "many"])
def test_a_malformed_limit_is_refused_before_any_engine_exists(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    """ADR-0186 §3 through §10, at this surface: refused **locally and before I/O**.

    Zero is refused as well as a negative, a non-integer and ``2**63``, which is
    stricter than ADR-0085 §9's ``[0, 2**63)`` and is what ``SourceReadTrail.recent``
    itself requires — neither implementation may be silently more permissive than
    the other. Asserted by observing that the engine recorded **no call**, which is
    the only way to see "before any I/O" from outside.
    """
    engine = _ScriptedReadEngine(_record("r-1"))
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["reads", "--limit", bad])
    assert result.exit_code == 2
    assert engine.calls == []


def test_the_listing_defaults_as_the_protocol_defaults(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§9: ``--limit`` "defaulting as the Protocol defaults".

    A second default in the adapter would be a paging bound the contract never
    stated, drifting the day the Protocol's moves.
    """
    engine = _ScriptedReadEngine(_record("r-1"))
    _wire(monkeypatch, engine)

    assert CliRunner().invoke(cli.app, ["reads"]).exit_code == 0
    assert engine.calls == [("recent_reads", {"limit": DEFAULT_PAGE_SIZE})]


def test_an_explicit_limit_is_forwarded_and_bounds_the_page(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§9: ``assistant reads`` "taking ``--limit``" — the value, not just its shape.

    The refusal case and the default case together leave one hole open: a command
    that parsed ``--limit`` and then passed ``DEFAULT_PAGE_SIZE`` regardless passes
    both, and silently hands the user a page they did not ask for. So this asserts
    the *value* reaching the operation and the page it produced, over a trail with
    more rows than the bound — a full page, which is also the one that has to say it
    is one and that a full page is not the beginning of the record.
    """
    engine = _ScriptedReadEngine(_record("r-new"), _record("r-old"))
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["reads", "--limit", "1"])
    assert result.exit_code == 0
    assert engine.calls == [("recent_reads", {"limit": 1})]

    rendered = _flat(output.getvalue())
    assert "1 read attempt(s)" in rendered
    assert "r-new" in rendered
    assert "r-old" not in rendered
    assert "Showing 1. Ask for more with --limit" in rendered
    assert "there is no total count" in rendered
    assert "every attempt still held" in rendered


def test_an_empty_page_is_never_the_claim_that_nothing_was_read(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0185 §7's argument, applied to the surface that could undo it.

    "A trail of successes alone answers it only by *absence*, and an absence in this
    store is ambiguous by construction: no row could mean not read, or could mean
    the record failed, or the horizon pruned it." The whole reason refusals are
    recorded is that absence says nothing — so an empty page rendered as "nothing
    was ever read" would put back exactly the claim the store refuses to make.

    **Both reasons are asserted, not one.** The horizon is the obvious one; ADR-0185
    §5a's two fault paths — a recorder that raised, a cancellation landing after the
    read began — are the ones a surface forgets, and they are why "every read" is a
    sentence this module never writes.
    """
    rendered = _listing(output, monkeypatch)

    assert "Nothing recorded" in rendered
    assert "not a claim that nothing was ever read" in rendered
    assert "oldest attempts are dropped as it fills" in rendered
    assert "two faults leave no row at all" in rendered


# --- ADR-0185 §2: a row renders whole ----------------------------------------


def test_a_row_renders_every_one_of_the_records_seven_fields(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0186 §7's "render whole or render fewer rows", inherited by §10.

    Asserted by enumerating the record's fields rather than by naming the ones this
    case happens to check: ADR-0185 §10 says the trail must yield "the source's
    declared identity, the use, the instant its grant check resolved, its outcome,
    whether the source was opened …, the grant it ran under where there was one, and
    how many items the reading carried", and a field silently dropped from the
    rendering is a field the exit test's read half no longer reconstructs at a
    user's hands.
    """
    record = _record(
        "r-7", source="calendar", use=GrantScope.FACET, outcome=ReadOutcome.COMPLETED, produced=14
    )
    rendered = _listing(output, monkeypatch, record)

    assert "r-7" in rendered  # its own id
    assert "calendar" in rendered  # source
    assert "looking at it while answering" in rendered  # use, in words
    assert "2026-03-01 09:00:00.000000 UTC" in rendered  # checked_at, whole
    assert "completed" in rendered  # outcome
    assert "opened" in rendered  # opened-ness, a function of the outcome
    assert "g-1" in rendered  # the grant it ran under
    assert "14 item(s)" in rendered  # produced

    # And the model has no eighth field this rendering could have missed.
    assert set(SourceReadRecord.model_fields) == {
        "id",
        "source",
        "use",
        "checked_at",
        "outcome",
        "grant",
        "produced",
    }


@pytest.mark.parametrize(
    ("use", "phrase"),
    [
        (GrantScope.FACET, "looking at it while answering"),
        (GrantScope.INGEST, "durably remembering what it says"),
        (GrantScope.NOTIFY, "reading it to raise things with you unprompted"),
    ],
)
def test_each_use_renders_in_words_rather_than_as_an_enum_value(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, use: GrantScope, phrase: str
) -> None:
    """The use the *gate was asked about*, in the vocabulary the grant surface uses.

    ADR-0133 §2 makes the three uses independent and a read attempted for one at a
    time, so this names one use and never a scope. Sharing the phrasing with
    ``assistant granted`` is deliberate: a user comparing what they allowed with
    what was attempted should not have to translate between two vocabularies for
    one enum.
    """
    rendered = _listing(output, monkeypatch, _record("r-1", use=use))
    assert phrase in rendered


def test_two_attempts_a_microsecond_apart_render_as_two_instants(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No part of a value is truncated (ADR-0186 §7, inherited by §10).

    A driver checking a revoked source on a schedule writes rows close together, and
    at minute precision a page of them renders as one instant repeated — a history
    that is internally consistent and chronologically false. The record resolves to
    the microsecond, so the rendering shows the whole of it.
    """
    first = _AT.replace(microsecond=1)
    second = _AT.replace(microsecond=2)
    rendered = _listing(output, monkeypatch, _record("r-2", at=second), _record("r-1", at=first))

    assert "09:00:00.000002 UTC" in rendered
    assert "09:00:00.000001 UTC" in rendered


def test_the_page_is_rendered_in_the_operations_order_and_is_never_re_sorted(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0185 §6 at the adapter: recording order, never a sort by ``checked_at``.

    The rows are seeded with instants that **disagree** with their positions, which
    is the state this store admits by design — ``checked_at`` is caller-supplied and
    can move backwards, which is why the store keys its own prune on recording order
    instead. An adapter that "helpfully" sorted by the instant it displays would
    reorder the page away from the record, and would answer differently after a
    backwards clock correction.
    """
    rendered = _listing(
        output,
        monkeypatch,
        _record("r-newest", at=_AT.replace(hour=7)),
        _record("r-middle", at=_AT.replace(hour=11)),
        _record("r-oldest", at=_AT.replace(hour=9)),
    )

    assert [match.group() for match in re.finditer(r"r-(?:newest|middle|oldest)", rendered)] == [
        "r-newest",
        "r-middle",
        "r-oldest",
    ]


def test_a_value_carrying_markup_is_neutralised_on_render(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every value is inserted as **data** (ADR-0186 §7's last clause, ADR-0042 §4).

    Being read from an append-only store relaxes nothing, and this store relaxes it
    least of all: ADR-0185 §2 stores ``source`` **byte for byte** — "no
    implementation strips, case-folds or otherwise normalises it" — precisely so the
    trail names the source the reader is actually called. That is the value a
    renderer must not hand a terminal unescaped, and the escaping happens here
    rather than at the store for exactly that reason.
    """
    rendered = _listing(output, monkeypatch, _record("r-1", source="[red]calendar[/]"))

    assert "[red]calendar[/]" in rendered


# --- ADR-0185 §1: six outcomes, and opened-ness ------------------------------


def test_every_outcome_renders_as_its_own_thing(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All six, each distinct — enumerated because six is the whole of the enum.

    ADR-0185 §1 makes the six "mutually exclusive and total", and the two
    unanswerable outcomes are deliberately separate from their answered twins:
    "there was no live grant" and "I could not find out whether there was one" are
    different facts about the user's authorisation. A rendering that folded either
    pair would put a claim the store refuses to make in front of the user, so what
    this asserts is not that each word appears but that the **six headlines are six
    different sentences** — a mapping collapsing any two would still print six rows.

    Rendered in one listing, so the distinctness is asserted over what a user
    actually sees on one screen rather than across six independent runs.
    """
    rendered = _listing(
        output,
        monkeypatch,
        _record("r-completed", outcome=ReadOutcome.COMPLETED),
        _refused("r-refused"),
        _record("r-unanswered", outcome=ReadOutcome.UNANSWERED, grant=None, produced=0),
        _record("r-failed", outcome=ReadOutcome.FAILED, produced=0),
        _record("r-discarded", outcome=ReadOutcome.DISCARDED),
        _record("r-unconfirmed", outcome=ReadOutcome.UNCONFIRMED),
    )

    endings = {outcome: cli._read_ending(outcome) for outcome in ReadOutcome}
    assert len(set(endings.values())) == len(ReadOutcome) == 6
    assert len({ending for _word, ending in endings.values()}) == 6
    for outcome, (word, _ending) in endings.items():
        assert outcome.value in word  # the enum's own word, not an invented one
        assert outcome.value in rendered  # and it reached the screen


def test_a_failed_attempt_says_opened_ness_is_not_recorded_rather_than_guessing(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0185 §1's one undeterminable case, and neither inference is offered.

    "Whether the source was opened is **not determinable** from the record, and no
    consumer may infer it in either direction" — a reader can refuse before starting
    work at all or fail with the bytes already in hand, and ADR-0093 §8 makes both
    cross the seam as the same error. So this row must not join the four that say
    "opened" nor the two that say "not opened".
    """
    rendered = _listing(output, monkeypatch, _record("r-1", outcome=ReadOutcome.FAILED, produced=0))

    assert "whether it was opened is not recorded" in rendered
    assert "not opened:" not in rendered


def test_a_refused_attempt_is_a_row_of_its_own_naming_no_grant(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0185 §7: the row the trail exists for, legible as itself.

    "'Was this source read after I revoked it' has no answer today" — this is the
    positive one. The row states that an attempt was made, that nothing was opened,
    and that no live grant was found; the absence of a grant is itself the fact
    (§2's invariant makes ``grant`` ``None`` on exactly this outcome and
    ``UNANSWERED``), so it is rendered as a stated absence rather than as a blank.
    """
    rendered = _listing(output, monkeypatch, _refused("r-1", source="email"))

    assert "refused" in rendered
    assert "not opened" in rendered
    assert "you had allowed no live grant when I checked" in rendered
    assert "email" in rendered
    assert "0 item(s)" in rendered


def test_an_unanswered_attempt_never_says_there_was_no_live_grant(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0185 §1's fold, barred at the surface rather than only in the store.

    Both outcomes carry ``grant=None``, so one wording for the absence would put
    the claim *there was no live grant* onto the row where that is precisely what
    is not known — and would contradict the row's own ending line one line above
    it. "A store fault and a withdrawn grant are different facts and an operator
    must be able to tell them apart" (ADR-0097 §5), and the whole reason
    ``UNANSWERED`` is a member of its own is that the distinction must survive.

    Asserted over the **whole row** rather than over the ending line alone: round
    1's blocker was a row whose two lines disagreed, and a case asserting either
    line by itself would have passed while the screen said both things.
    """
    unanswered = _record("r-1", outcome=ReadOutcome.UNANSWERED, grant=None, produced=0)
    rendered = _listing(output, monkeypatch, unanswered)

    assert "could not find out whether you allowed it" in rendered
    assert "the check did not answer, so whether you allowed it is unknown" in rendered
    # Not the refused row's sentence, in any part of the row.
    assert "no live grant" not in rendered

    # And the two absences are two sentences, not one shared with a different label.
    refused_line = cli._read_grant_line(_refused("r-2"))
    assert cli._read_grant_line(unanswered) != refused_line
    assert "no live grant" in refused_line


def test_a_grant_that_no_longer_resolves_is_rendered_as_recorded(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0185 §8: an unresolvable pointer is legible history, not corruption.

    "No implementation may treat an unresolvable ``grant`` as a defect, repair it,
    or drop the row." The adapter has no way to resolve one and must not acquire
    one, so what it renders is the id as recorded, with no claim that it still
    resolves — which is the same sentence as the liveness bar, arriving on the one
    field that looks like a live reference.
    """
    rendered = _listing(output, monkeypatch, _record("r-1", grant="g-long-gone"))

    assert "g-long-gone" in rendered
    assert "it is not looked up now" in rendered


# --- ADR-0186 §8's bars, one store over --------------------------------------


def test_a_completed_attempt_claims_nothing_about_what_came_of_it(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8's third bar, transposed: a row states an attempt, never an event.

    ``COMPLETED`` means the reading was *admitted for its use* and "claims nothing
    whatever about the use itself — not that the use ran, and not that the reading
    reached it" (``ReadOutcome.COMPLETED``). ADR-0185 §5 requires the row to be
    written *before* the use runs, so an outcome defined by what followed could not
    be known when the row was written. "Remembered" beside a completed attempt is
    the specific regression this asserts against.
    """
    rendered = _listing(output, monkeypatch, _record("r-1", use=GrantScope.INGEST))

    for word in _CONSEQUENCE_WORDS:
        assert not re.search(rf"\b{word}\b", rendered), word
    assert "not what came of it" in rendered


def test_the_listing_says_a_row_is_not_a_live_permission(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8's first bar: no surface derives liveness from history.

    A row says an attempt was made — never that the source is still allowed, what
    the scope is now, or that the grant it names still exists. The sentence is
    printed rather than assumed, because the reader who most needs it is the one
    treating this list as a permissions screen, and the surface that *does* answer
    it is named so the reader has somewhere to go.
    """
    rendered = _listing(output, monkeypatch, _record("r-1"))

    assert "does not say the source is still allowed" in rendered
    assert "assistant granted" in rendered


def test_the_listing_holds_no_content_and_says_so(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0185 §2, §10: a count and never a thing, and the narrowing declared.

    "Reconstructible" deliberately "does **not** mean the content of the read, and
    no lane may report the milestone met on the strength of a trail that carries
    any." The record holds none, so the surface can hold none — and it says which of
    the two it is showing, because a bare number beside a source invites the reading
    that the items themselves are one click away.
    """
    rendered = _listing(output, monkeypatch, _record("r-1", produced=14))

    assert "14 item(s)" in rendered
    assert "never the thing itself" in rendered
    assert "holds no content at all" in rendered


def test_the_grant_surface_still_reports_no_read_and_now_names_the_one_that_does(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §6's second clause, restated by ADR-0185 §8, at the site it binds.

    "No client presents a read, a read count or a last-read instant beside a
    standing grant" — the read surface landing is exactly the moment that clause is
    at risk, because the data is now one call away. So ``assistant granted`` still
    makes no call for it and prints none, and what it gained is a *name*: ADR-0186
    §10 wrote its closing sentence as true "until the read surface lands", and the
    honest correction is to point at the surface rather than to keep saying nothing
    answers the question.

    **The pointer names the unit that surface records, which is an attempt, and
    claims no completeness for it.** Two rounds of review landed on this one
    sentence. "The record of what was read" overclaims in the direction ADR-0186 §8
    bars — a refusal is a row there, and on a failure whether anything was opened is
    not determinable at all. "The record of *every* attempt" overclaims in the other
    direction: the store prunes (ADR-0185 §6) and §5a names two faults on which a
    read runs with no row, so no surface in this module says "every". What is left
    is where attempts are recorded, which is what the sentence has to be.
    """
    cli._render_standing(
        (
            SourceGrant(
                id="g-1",
                source="calendar",
                scope=(GrantScope.INGEST,),
                decided_at=_AT,
            ),
        )
    )
    rendered = _flat(output.getvalue())

    assert "says nothing about what has actually been read" in rendered
    assert "'assistant reads' is where attempts to read one are recorded" in rendered
    assert "every attempt" not in rendered
    # No read, no count, no instant of one: the clause is about what is *shown*
    # beside a grant, and the only instant here is the grant's own. The word
    # "attempt" appears in the cross-reference and nowhere else, so what is asserted
    # is the absence of a rendered *value* rather than of a word.
    assert "item(s)" not in rendered
    assert rendered.count("attempt") == 1
    assert "last read" not in rendered


# --- the error boundary on the listing ---------------------------------------


def test_an_unreadable_trail_is_reported_and_no_row_is_invented(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The listing's boundary: a refusal is a refusal, never an empty page.

    ``ReadTrailError`` reaches the user as itself. Rendering it as "Nothing
    recorded" would be the one dishonest line available here — a store that could
    not be consulted reported as a store holding nothing — and in *this* store that
    line is worse than in its sibling, because an empty read trail is the answer to
    "was anything read after I revoked it".
    """
    engine = _ScriptedReadEngine(_record("r-1"))
    engine.listing_raises = ReadTrailError("the read trail could not be opened")
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["reads"])
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "the read trail could not be opened" in rendered
    assert "Nothing recorded" not in rendered
