"""The calendar context source: what it contributes, and what gates it.

Two subjects in one adapter, because they are inseparable by design — the source
ships already gated, so there is never a window in which an ungranted calendar is
readable through the situational context (ADR-0096 §5, ADR-0097 §5).

Every collaborator is a canonical fake from ``ai_assistant.testing``. Nothing here
imports a concrete reader or a concrete grant store, which ``lint-imports`` forbids
this layer outright — the arrangement ADR-0095 §3 kept both contracts in ``core``
to make possible.

**The five driver cases ADR-0097 §5 and §5a distinguish are the enumeration §10
marks normative**, and they are written here rather than as store conformance
clauses because all five are obligations on *this* adapter and no store
implementation exhibits any of them.
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import textwrap
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.context import (
    AssemblingContextProvider,
    CalendarContextSource,
    ClockContextSource,
    ContextSource,
)
from ai_assistant.core.errors import ContextError, GrantError, ReaderError, ReadTrailError
from ai_assistant.core.types import (
    CalendarFacet,
    ContextFacet,
    GrantScope,
    ReadOutcome,
    SourceGrant,
    SourceReading,
)
from ai_assistant.testing import (
    FakeReader,
    FakeSourceGrants,
    FakeSourceReadRecorder,
    source_grant,
)
from ai_assistant.testing.readers import DEFAULT_READER_NAME

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import Reader, SourceGrants

_READ_AT = datetime(2026, 3, 4, 9, 30, tzinfo=UTC)
_NOW = datetime(2026, 3, 4, 9, 31, tzinfo=UTC)
#: The instant the drivers' injected clock serves, and deliberately **not**
#: ``_READ_AT``: ADR-0185 §12 forbids deriving ``checked_at`` from
#: ``SourceReading.read_at``, so a source that reached for the reading's own stamp
#: would be indistinguishable from one that read the clock if the two agreed.
_CHECKED_AT = datetime(2026, 3, 4, 9, 29, tzinfo=UTC)


def _clock() -> datetime:
    """The clock every gated source below is wired with (ADR-0185 §12)."""
    return _CHECKED_AT


def _facet(*, source: str = DEFAULT_READER_NAME, in_progress: int = 1) -> CalendarFacet:
    """A facet stamped as ``FakeReader``'s own readings are."""
    return CalendarFacet(
        source=source,
        read_at=_READ_AT,
        entries_in_progress=in_progress,
        next_starts_at=_READ_AT + timedelta(hours=2),
        covers_until=_READ_AT + timedelta(days=7),
    )


def _reader(facet: CalendarFacet | None = None, **kwargs: object) -> FakeReader:
    """A reader whose readings carry ``facet`` and are stamped at ``_READ_AT``."""
    return FakeReader(read_at=_READ_AT, facet=facet, **kwargs)  # type: ignore[arg-type]


def _granted(source: str = DEFAULT_READER_NAME) -> FakeSourceGrants:
    return FakeSourceGrants([source_grant(source)])


def _source(
    reader: Reader,
    grants: SourceGrants,
    reads: FakeSourceReadRecorder | None = None,
) -> CalendarContextSource:
    return CalendarContextSource(
        reader=reader,
        grants=grants,
        reads=FakeSourceReadRecorder() if reads is None else reads,
        now=_clock,
    )


def _awaited_names(func: Callable[..., object]) -> list[str]:
    """The attribute names this function awaits, in source order.

    ADR-0097 §5a's first clause — "No ``await`` may occur between the ``live()``
    result a driver gates on and its call to ``Reader.read()``" — is a rule about
    the driver's *body*, stated as a rule rather than bought with a mechanism
    because "it costs a line and a test". This is that test's instrument: reading
    the awaits off the source is what makes the property checkable at all, since
    an interleaving that never happens to be exercised is indistinguishable at run
    time from one that cannot happen.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    found: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
            found.append((node.lineno, node.col_offset, call.func.attr))
    # Sorted by position, because ``ast.walk`` is breadth-first: reading it in its
    # own order would assert on the tree's shape rather than on the sequence the
    # event loop actually sees, which is the whole subject.
    return [name for _, _, name in sorted(found)]


def _leaves_the_function(body: list[ast.stmt]) -> bool:
    """Whether ``body`` always leaves — its last statement raises or returns."""
    return bool(body) and isinstance(body[-1], ast.Raise | ast.Return)


def _fall_through_awaits(body: list[ast.stmt]) -> list[str]:
    """The awaited attribute names on the path that reaches the end of ``body``.

    ADR-0185 §5 put four recorder ``await``s into this driver on branches that
    **raise or return**, so a flat source-order list can no longer say what
    ADR-0097 §5a's first clause is about. This walks the statements that a single
    authorised pass actually executes: a ``try`` body counts, its handler counts
    only where the handler falls through, and an ``if`` branch counts only where it
    does not leave. What comes back is the sequence the event loop sees on the path
    where a read really happens — so "no ``await`` between the ``live()`` answer and
    ``read()``" is readable as two adjacent entries rather than argued from prose.
    """
    names: list[str] = []
    for statement in body:
        if isinstance(statement, ast.Try):
            names += _fall_through_awaits(statement.body)
            names += _fall_through_awaits(statement.orelse)
            for handler in statement.handlers:
                if not _leaves_the_function(handler.body):
                    names += _fall_through_awaits(handler.body)
            names += _fall_through_awaits(statement.finalbody)
        elif isinstance(statement, ast.If):
            if not _leaves_the_function(statement.body):
                names += _fall_through_awaits(statement.body)
            if not _leaves_the_function(statement.orelse):
                names += _fall_through_awaits(statement.orelse)
        else:
            names += _awaits_within(statement)
    return names


def _awaits_within(node: ast.stmt) -> list[str]:
    """Every awaited attribute name inside one statement, in source order."""
    found: list[tuple[int, int, str]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Await):
            continue
        call = child.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
            found.append((child.lineno, child.col_offset, call.func.attr))
    return [name for _, _, name in sorted(found)]


def _awaited_on_the_authorised_path(func: Callable[..., object]) -> list[str]:
    """The awaits one authorised, uninterrupted pass through ``func`` performs."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    definition = tree.body[0]
    assert isinstance(definition, ast.AsyncFunctionDef)
    return _fall_through_awaits(definition.body)


# --- the seam ---------------------------------------------------------------


def test_it_conforms_to_the_context_source_protocol() -> None:
    assert isinstance(_source(_reader(), _granted()), ContextSource)


def test_it_names_the_reader_it_holds() -> None:
    """The reader's declared identity, not a second constant.

    An operator reading a degradation log needs to know which *source* degraded,
    and a source identity is safe to log verbatim because ADR-0093 §7 keeps it
    "never derived from the source's location or contents" — the property
    ADR-0190 §2 carries forward unchanged, and the one that makes a minted
    discriminator admissible rather than an exception to it.
    """
    assert _source(_reader(), _granted()).name == DEFAULT_READER_NAME


def test_it_is_not_required_so_a_fault_degrades_rather_than_aborts() -> None:
    """ADR-0096 §8: no ``required`` marker, so the rest of the context assembles.

    Read by the assembler as ``getattr(source, "required", False)``, so the
    property under test is the *absence* of the attribute (ADR-0026 §4).
    """
    assert not hasattr(_source(_reader(), _granted()), "required")


def test_it_cannot_record_a_grant() -> None:
    """ADR-0097 §3's capability split, at the seam a widening would happen through.

    ``mypy --strict`` holds the static half — this source cannot *name* ``record``
    — and the narrow canonical fake models what it is actually handed.
    """
    assert not hasattr(_granted(), "record")


# --- what it contributes ----------------------------------------------------


async def test_a_granted_read_contributes_the_facet_it_carried() -> None:
    facet = _facet()

    contribution = await _source(_reader(facet), _granted()).contribute()

    assert contribution == {"calendar": facet}


async def test_a_reading_with_no_facet_contributes_nothing() -> None:
    """Valid, and the state every reading is in until the reader lane lands.

    ADR-0096 §5: "a reader whose source has no situational reading returns ``None``
    in it". The adapter contributes ``{}`` rather than ``{"calendar": None}``,
    because a contributed ``None`` would collide with the field's own default and
    say the same thing twice.
    """
    assert await _source(_reader(None), _granted()).contribute() == {}


async def test_the_contributed_facet_carries_the_readings_stamp() -> None:
    """The stamp is the only thing left saying who produced the value and when.

    The reading is gone by the time the facet reaches ``CurrentContext``, which is
    why the duplication inside ``SourceReading`` is intentional rather than
    redundant (ADR-0096 §5).
    """
    contribution = await _source(_reader(_facet()), _granted()).contribute()

    facet = contribution["calendar"]
    assert isinstance(facet, CalendarFacet)
    assert facet.source == DEFAULT_READER_NAME
    assert facet.read_at == _READ_AT


async def test_it_reads_afresh_on_every_assembly() -> None:
    """No facet is served from a cached or carried-over reading (ADR-0096 §3).

    ADR-0008 §5's "computes fresh each call — context is a point-in-time snapshot,
    not cached state" stated over the facet the snapshot now contains.
    """
    reader = _reader(_facet())
    source = _source(reader, _granted())

    await source.contribute()
    await source.contribute()

    assert reader.call_count == 2


def test_no_await_stands_between_the_check_and_the_read() -> None:
    """ADR-0097 §5a's first clause, read off the adapter's own body.

    **What it buys, exactly.** Awaiting a coroutine does not yield to the event
    loop — it runs that coroutine's body until *its* first suspension — so with
    nothing in between, this adapter cannot sit on a stale answer at all. A driver
    free to await anything there could hold one for arbitrarily long, which is the
    difference between a race bounded by a worker's scheduling and one bounded by
    nothing. It does not close the worker-side race, and nothing here claims it
    does (ADR-0097 §5a's boundary clause).

    The awaits are asserted **exhaustively and in order** rather than by a
    between-ness check, because a fourth await anywhere in this body is the defect
    whatever it happens to sit next to.

    **Six of the awaits here are ADR-0185 §5's recorder**, and every one of them
    sits on a branch that raises or returns — so the span this test exists to
    protect is untouched. The exhaustive list below is what fails on a seventh
    landing anywhere; the *authorised-path* list beside it is what says the two
    entries either side of the gate are still adjacent, which is the clause itself.
    """
    assert _awaited_names(CalendarContextSource.contribute) == [
        "live",
        "_record",  # UNANSWERED — the branch re-raises
        "_record",  # REFUSED — the branch returns
        "read",
        "_record",  # FAILED — the branch re-raises
        "live",
        "_record",  # UNCONFIRMED — the branch re-raises
        "_record",  # DISCARDED — the branch returns
        "_record",  # COMPLETED — before the facet is contributed (ADR-0185 §5)
    ]
    assert _awaited_on_the_authorised_path(CalendarContextSource.contribute) == [
        "live",
        "read",
        "live",
        "_record",
    ]


# --- the gate: all five cases ADR-0097 §5 and §5a distinguish ---------------


async def test_an_ungranted_source_is_not_read_at_all() -> None:
    """Case one: no live grant at the check, so nothing is opened.

    **Refuse to read, not read-and-discard.** Opening the user's calendar is the
    act the grant is about, so ``call_count == 0`` is the assertion that carries
    this — the empty contribution alone would also be true of a read-and-discard.
    """
    reader = _reader(_facet())

    contribution = await _source(reader, FakeSourceGrants()).contribute()

    assert contribution == {}
    assert reader.call_count == 0


async def test_a_grant_for_another_use_does_not_authorise_the_facet_read() -> None:
    """A use a grant does not name is not authorised by it (ADR-0097 §2).

    "You may remember my calendar, but do not look at it to answer this" is the
    inverse sentence, and this adapter has to honour it as literally as the
    ingestion stage honours the other one.
    """
    reader = _reader(_facet())
    grants = FakeSourceGrants([source_grant(DEFAULT_READER_NAME, scope=[GrantScope.INGEST])])

    assert await _source(reader, grants).contribute() == {}
    assert reader.call_count == 0


async def test_an_unanswerable_check_before_the_read_opens_nothing() -> None:
    """Case two: a ``live()`` that raises, and the error is not converted.

    It fails closed — nothing is opened — and the ``GrantError`` propagates rather
    than becoming a silent empty contribution, because a store fault and a
    withdrawn grant are different facts an operator must be able to tell apart
    (ADR-0097 §5a). Both still end at an absent facet; the assembler is what makes
    that true, which the assembly case below asserts.
    """
    reader = _reader(_facet())
    grants = _granted()
    grants.fail_live()

    with pytest.raises(GrantError):
        await _source(reader, grants).contribute()

    assert reader.call_count == 0


async def test_a_revocation_between_the_check_and_the_return_discards_the_reading() -> None:
    """Case three: the revocation wins, and no facet is contributed from the read.

    A read legitimately begun while granted takes real time, and a revocation may
    land inside it. The residual is at most one already-started read, whose bytes
    are **discarded rather than used**: nothing reaches a prompt.
    """
    reader = _reader(_facet())
    grants = _granted()
    grants.revoke_after(1)  # the gate's check passes; the re-check does not

    contribution = await _source(reader, grants).contribute()

    assert contribution == {}
    assert reader.call_count == 1  # the read really did happen


async def test_an_unanswerable_re_check_discards_the_reading_too() -> None:
    """Case four: a ``GrantError`` after the read is treated as a withdrawn grant.

    An implementation that caught the error and carried on with the *first* lookup
    would pass every other test in this module while contributing a facet after its
    authorisation stopped being checkable.
    """
    reader = _reader(_facet())
    grants = _FailsOnTheRecheck(_granted())

    with pytest.raises(GrantError):
        await _source(reader, grants).contribute()

    assert reader.call_count == 1


async def test_a_grant_live_throughout_lets_the_reading_be_used() -> None:
    """Case five: the accepting case, without which the four refusals prove nothing.

    A gate that refused everything would pass all four above.
    """
    grants = _granted()

    contribution = await _source(_reader(_facet()), grants).contribute()

    assert contribution == {"calendar": _facet()}
    assert grants.call_count == 2  # checked before the read and again after it


class _FailsOnTheRecheck:
    """A ``SourceGrants`` that answers once and raises from every later ``live``.

    A thin scripted wrapper around the canonical fake: that fake is ``@final`` and
    its ``fail_live`` script arms *every* call, while the case under test needs the
    failure to arrive **between** two of them. Everything the adapter observes is
    the canonical fake's; only the moment of arming is scripted here.
    """

    def __init__(self, inner: FakeSourceGrants) -> None:
        self._inner = inner

    async def live(self, *, source: str, use: GrantScope) -> SourceGrant | None:
        """Delegate, then arm the fake so the next call raises."""
        answer = await self._inner.live(source=source, use=use)
        self._inner.fail_live()
        return answer


# --- a wiring bug is not data to reconcile ----------------------------------


class _TasksFacet(ContextFacet):
    """Stands in for the second facet type ADR-0096 §5's union is about to have."""

    open_tasks: int = 0


class _MisWiredReader:
    """A reader whose reading carries a facet this adapter is not wired for.

    The mismatch has to be built past ``SourceReading.facet``'s annotation, which
    names one concrete type today — so it is set on the constructed reading rather
    than passed to the constructor. That is the deployment ADR-0096 §5 is about,
    reachable the moment a second facet-bearing reader exists, and it is modelled
    here rather than by reaching into the canonical fake's internals.
    """

    def __init__(self) -> None:
        reading = SourceReading(source=DEFAULT_READER_NAME, read_at=_READ_AT)
        # The reading is frozen (ADR-0068), and the wrong wiring is the subject.
        object.__setattr__(
            reading,
            "facet",
            _TasksFacet(source=DEFAULT_READER_NAME, read_at=_READ_AT, open_tasks=3),
        )
        self._reading = reading

    @property
    def name(self) -> str:
        """The identity the grant covers."""
        return DEFAULT_READER_NAME

    async def read(self) -> SourceReading:
        """The mis-typed reading."""
        return self._reading


async def test_a_facet_of_the_wrong_type_is_a_wiring_bug() -> None:
    """ADR-0096 §5: a mismatch raises ``ContextError``.

    ADR-0008 §4 reserves that error for exactly this — "programmer/wiring bugs the
    assembler should not paper over". A source is constructed for a specific field,
    so it knows the type it expects, and a mismatch is a deployment wired wrongly
    rather than data to reconcile.
    """
    with pytest.raises(ContextError, match="wiring bug"):
        await _source(_MisWiredReader(), _granted()).contribute()


# --- and through the assembler, where absence is the only thing said --------


async def _assemble_with(source: CalendarContextSource) -> object:
    provider = AssemblingContextProvider(
        [ClockContextSource(now=lambda: _NOW), source],
    )
    return (await provider.assemble()).calendar


async def test_a_granted_facet_reaches_the_assembled_context() -> None:
    assert await _assemble_with(_source(_reader(_facet()), _granted())) == _facet()


@pytest.mark.parametrize(
    ("label", "grants", "reader"),
    [
        ("ungranted", FakeSourceGrants(), _reader(_facet())),
        ("no facet in the reading", _granted(), _reader(None)),
        ("the read failed", _granted(), _reader(_facet(), failure=OSError("gone"))),
    ],
)
async def test_every_absence_looks_identical_in_the_assembled_context(
    label: str, grants: FakeSourceGrants, reader: FakeReader
) -> None:
    """ADR-0096 §4 and ADR-0097 §5: ``None`` is the single absence.

    An ungranted calendar must be observationally identical to one that failed to
    read and to one that had nothing to say — because a field distinguishing them
    is a model being handed a script to ask for access, in the exact place ADR-0093
    §7 rules that configuration is not a grant.
    """
    assert await _assemble_with(_source(reader, grants)) is None, label


async def test_a_store_fault_also_leaves_the_facet_absent() -> None:
    """The optional-source degradation path, over the error the adapter propagates.

    The adapter does not convert a ``GrantError`` — that would erase the difference
    between a store fault and a withdrawn grant for whoever reads the log — and the
    assembler is what turns it into an absent facet, "as every optional-source
    fault does" (ADR-0097 §5a).
    """
    grants = _granted()
    grants.fail_live()

    assert await _assemble_with(_source(_reader(_facet()), grants)) is None


async def test_the_rest_of_the_context_survives_a_failing_calendar() -> None:
    """The point of carrying no ``required`` marker (ADR-0008 §4, ADR-0026 §4)."""
    provider = AssemblingContextProvider(
        [
            ClockContextSource(now=lambda: _NOW),
            _source(_reader(_facet(), failure=OSError("gone")), _granted()),
        ],
    )

    context = await provider.assemble()

    assert context.now == _NOW
    assert context.calendar is None


# --- ADR-0185 §5: the attempt is recorded, before the facet is contributed ----


@pytest.mark.parametrize(
    ("outcome", "arrange"),
    [
        pytest.param(ReadOutcome.COMPLETED, "granted", id="completed"),
        pytest.param(ReadOutcome.REFUSED, "ungranted", id="refused"),
        pytest.param(ReadOutcome.UNANSWERED, "unanswerable", id="unanswered"),
        pytest.param(ReadOutcome.FAILED, "failing", id="failed"),
        pytest.param(ReadOutcome.DISCARDED, "revoked-mid-read", id="discarded"),
    ],
)
async def test_every_attempt_leaves_one_row_naming_its_outcome(
    outcome: ReadOutcome, arrange: str
) -> None:
    """ADR-0185 §1: one row per attempt, whatever became of it.

    The ``FACET`` path is the one ADR-0139 §6's Context quotes to show what was
    missing: this module's own comment used to say that a reading discarded across a
    revocation left nothing behind. The ``DISCARDED`` case below is that comment
    made false.
    """
    reader = _reader(_facet()) if arrange != "failing" else _reader(failure=OSError("gone"))
    recorder = FakeSourceReadRecorder()

    with contextlib.suppress(GrantError, ReaderError):
        await _source(reader, _arranged(arrange), recorder).contribute()

    (row,) = recorder.written
    assert row.outcome is outcome
    assert row.source == reader.name
    assert row.use is GrantScope.FACET


def _arranged(arrange: str) -> FakeSourceGrants:
    """The grant seam each of the five arrangements needs."""
    if arrange == "ungranted":
        return FakeSourceGrants()
    granted = _granted()
    if arrange == "unanswerable":
        granted.fail_live()
    elif arrange == "revoked-mid-read":
        granted.revoke_after(1)
    return granted


async def test_the_row_is_written_before_the_facet_is_contributed() -> None:
    """ADR-0185 §5's ordering clause, and its fail-closed consequence.

    "Where the recorder raises, the driver discards the reading: … no facet is
    contributed, and the ``ReadTrailError`` is reported to the driver's own failure
    posture (ADR-0008 §4 on the facet side)." So the fault reaches the assembler,
    which degrades this one source and leaves the field absent — the same end every
    optional-source fault has, which is exactly what ADR-0096 §4 requires of it.
    """
    recorder = FakeSourceReadRecorder()
    recorder.fail_record()

    with pytest.raises(ReadTrailError):
        await _source(_reader(_facet()), _granted(), recorder).contribute()

    provider = AssemblingContextProvider(
        [
            ClockContextSource(now=lambda: _NOW),
            _source(_reader(_facet()), _granted(), recorder),
        ],
    )
    context = await provider.assemble()

    assert context.calendar is None
    assert context.now == _NOW


async def test_the_recorded_instant_is_the_clock_and_never_the_reading() -> None:
    """ADR-0185 §12: ``checked_at`` is the injected clock's, read after the check.

    Never :attr:`SourceReading.read_at`, which ADR-0093 §10 captures "at the moment
    the source's bytes are acquired" — later than the instant this record is about,
    and absent altogether on a refused attempt.
    """
    recorder = FakeSourceReadRecorder()

    await _source(_reader(_facet()), _granted(), recorder).contribute()

    (row,) = recorder.written
    assert row.checked_at == _CHECKED_AT
    assert row.checked_at != _READ_AT


async def test_the_count_is_the_facet_the_reading_carried() -> None:
    """ADR-0185 §2: ``produced`` counts "its proposals, and its facet where it carried one".

    A facet-only reading is the case that would be silently zero if a driver counted
    proposals alone — and a zero on a ``COMPLETED`` row means the source had nothing,
    which is a different statement about the read.
    """
    recorder = FakeSourceReadRecorder()

    await _source(_reader(_facet(), proposals=[]), _granted(), recorder).contribute()

    (row,) = recorder.written
    assert row.produced == 1
