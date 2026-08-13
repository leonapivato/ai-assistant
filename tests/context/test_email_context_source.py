"""The email context source: what it contributes, and what gates it.

ADR-0140 §13's two adapter items, and both are stated there as owed *here* rather
than inherited: "the calendar's two modules are the shape to follow and are not
coverage: this is new wiring and they do not reach it". So the whole ADR-0097 §5a
lifecycle is re-run against ``EmailContextSource``, and the facet item is asserted
in **both** directions — the accepting one through the assembler, where the
subject is ``CurrentContext.email`` rather than a mapping key.

Every collaborator is a canonical fake from ``ai_assistant.testing``. Nothing here
imports a concrete reader or a concrete grant store, which ``lint-imports`` forbids
this layer outright.

**The mis-wiring cases use the real other member of the union.** The calendar's
module had to build its mismatch past ``SourceReading.facet``'s annotation with an
``object.__setattr__``, because one concrete type was all there was. There are two
now (ADR-0140 §6), so the deployment ADR-0096 §5 is actually about — a reader wired
to the adapter for the *other* source — is constructible, and it is tested in both
directions because an adapter pair can be crossed either way round.
"""

from __future__ import annotations

import ast
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
    EmailContextSource,
)
from ai_assistant.core.errors import ContextError, GrantError
from ai_assistant.core.types import (
    CalendarFacet,
    CurrentContext,
    EmailFacet,
    GrantScope,
    SourceGrant,
)
from ai_assistant.testing import (
    FakeReader,
    FakeSourceGrants,
    source_grant,
)
from ai_assistant.testing.readers import DEFAULT_READER_NAME

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import SourceGrants

_READ_AT = datetime(2026, 3, 4, 9, 30, tzinfo=UTC)
_NOW = datetime(2026, 3, 4, 9, 31, tzinfo=UTC)
_WINDOW = timedelta(days=7)
_ARRIVED = 3
"""How many messages this module's scripted facet counts — nothing turns on it."""


def _facet(*, source: str = DEFAULT_READER_NAME, arrived: int = _ARRIVED) -> EmailFacet:
    """An email facet stamped as ``FakeReader``'s own readings are."""
    return EmailFacet(
        source=source,
        read_at=_READ_AT,
        arrived_in_window=arrived,
        covers_from=_READ_AT - _WINDOW,
    )


def _calendar_facet(*, source: str = DEFAULT_READER_NAME) -> CalendarFacet:
    """The *other* member of the union, stamped for the same reading."""
    return CalendarFacet(
        source=source,
        read_at=_READ_AT,
        entries_in_progress=1,
        next_starts_at=_READ_AT + timedelta(hours=2),
        covers_until=_READ_AT + _WINDOW,
    )


def _reader(facet: EmailFacet | CalendarFacet | None = None, **kwargs: object) -> FakeReader:
    """A reader whose readings carry ``facet`` and are stamped at ``_READ_AT``."""
    return FakeReader(read_at=_READ_AT, facet=facet, **kwargs)  # type: ignore[arg-type]


def _granted(source: str = DEFAULT_READER_NAME) -> FakeSourceGrants:
    return FakeSourceGrants([source_grant(source)])


def _source(reader: FakeReader, grants: FakeSourceGrants) -> EmailContextSource:
    return EmailContextSource(reader=reader, grants=grants)


def _awaited_names(func: Callable[..., object]) -> list[str]:
    """The attribute names this function awaits, in source order.

    ADR-0097 §5a's first clause is a rule about the driver's *body*, so reading the
    awaits off it is what makes the property checkable at all: an interleaving that
    never happens to be exercised is indistinguishable at run time from one that
    cannot happen. The calendar module carries the same instrument, and it is
    duplicated rather than shared because the two modules assert it of two classes
    and a shared helper would make the second look like coverage of the first.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    found: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
            found.append((node.lineno, node.col_offset, call.func.attr))
    # Sorted by position: `ast.walk` is breadth-first, and the subject is the
    # sequence the event loop sees rather than the tree's shape.
    return [name for _, _, name in sorted(found)]


# --- the seam ---------------------------------------------------------------


def test_it_conforms_to_the_context_source_protocol() -> None:
    assert isinstance(_source(_reader(), _granted()), ContextSource)


def test_it_names_the_reader_it_holds() -> None:
    """The reader's declared identity — ``"email"`` on a real one, never the account.

    ADR-0140 §12 makes that identity declared rather than configured for exactly
    this reason: an operator reading a degradation log needs to know which source
    degraded, and the log line is Tier 2 (ADR-0093 §7).
    """
    assert _source(_reader(), _granted()).name == DEFAULT_READER_NAME


def test_it_is_not_required_so_a_fault_degrades_rather_than_aborts() -> None:
    """No ``required`` marker, so the rest of the context assembles (ADR-0026 §4).

    Read by the assembler as ``getattr(source, "required", False)``, so the
    property under test is the *absence* of the attribute.
    """
    assert not hasattr(_source(_reader(), _granted()), "required")


def test_it_cannot_record_a_grant() -> None:
    """ADR-0097 §3's capability split, at the seam a widening would happen through."""
    assert not hasattr(_granted(), "record")


# --- ADR-0140 §13: a granted read's facet reaches the field it was wired for -


async def test_a_granted_read_contributes_the_facet_under_email() -> None:
    """The accepting half, and the load-bearing one (ADR-0140 §13).

    Every assertion in the gate section below is a refusal or a call count, so an
    adapter that reads under a live grant and then contributes nothing — or
    contributes the facet under ``calendar`` — satisfies the whole lifecycle while
    ``CurrentContext.email`` is permanently absent.
    """
    facet = _facet()

    contribution = await _source(_reader(facet), _granted()).contribute()

    assert contribution == {"email": facet}


async def test_it_contributes_under_no_field_but_email() -> None:
    """ "And no other" (ADR-0140 §13), asserted as the key set rather than by eye.

    The wrong-key shape is the one §13 names as shipped by a lane copying the
    calendar's module and changing only the reader, so the assertion is that
    ``email`` is the *whole* of what this source claims.
    """
    contribution = await _source(_reader(_facet()), _granted()).contribute()

    assert set(contribution) == {"email"}


async def test_a_reading_with_no_facet_contributes_nothing() -> None:
    """ADR-0096 §5: a reader whose source has no situational reading returns ``None``.

    ``{}`` rather than ``{"email": None}``, because a contributed ``None`` would
    collide with the field's own default and say the same thing twice.
    """
    assert await _source(_reader(None), _granted()).contribute() == {}


async def test_the_contributed_facet_carries_the_readings_stamp() -> None:
    """The stamp is the only thing left saying who produced the value and when.

    The reading is gone by the time the facet reaches ``CurrentContext``, which is
    why the duplication inside ``SourceReading`` is intentional (ADR-0096 §5). The
    adapter lifts the facet unedited: it may not construct one, edit its instants
    or synthesise one.
    """
    contribution = await _source(_reader(_facet()), _granted()).contribute()

    facet = contribution["email"]
    assert isinstance(facet, EmailFacet)
    assert facet.source == DEFAULT_READER_NAME
    assert facet.read_at == _READ_AT
    assert facet.arrived_in_window == _ARRIVED
    assert facet.covers_from == _READ_AT - _WINDOW


async def test_it_reads_afresh_on_every_assembly() -> None:
    """No facet is served from a cached or carried-over reading (ADR-0096 §3).

    ADR-0008 §5's "computes fresh each call" stated over the facet the snapshot now
    contains — and for a count it is the whole of the value: "you have had two
    messages today" is only true of the assembly that read it.
    """
    reader = _reader(_facet())
    source = _source(reader, _granted())

    await source.contribute()
    await source.contribute()

    assert reader.call_count == 2


def test_no_await_stands_between_the_check_and_the_read() -> None:
    """ADR-0097 §5a's first clause, read off the adapter's own body.

    Awaiting a coroutine does not yield to the event loop, so with nothing in
    between this adapter cannot sit on a stale answer at all. It does not close the
    worker-side race, and nothing here claims it does (ADR-0097 §5a's boundary
    clause).

    The awaits are asserted **exhaustively and in order** rather than by a
    between-ness check, because a fourth await anywhere in this body is the defect
    whatever it happens to sit next to. It is read off ``EmailContextSource``
    rather than off the base it shares with the calendar's adapter: what ADR-0140
    §13 owes is the property of *this* driver, and a later override would be
    invisible to an assertion aimed at the base.
    """
    assert _awaited_names(EmailContextSource.contribute) == ["live", "read", "live"]


# --- the gate: all six cases ADR-0097 §5 and §5a distinguish -----------------


async def test_an_ungranted_source_is_not_read_at_all() -> None:
    """Case one: no live grant at the check, so the store is not opened.

    **Refuse to read, not read-and-discard** — ADR-0140 §9's second clause is "not
    resolved, not opened, not parsed", so ``call_count == 0`` is what carries this.
    The empty contribution alone would also be true of a read-and-discard.
    """
    reader = _reader(_facet())

    contribution = await _source(reader, FakeSourceGrants()).contribute()

    assert contribution == {}
    assert reader.call_count == 0


async def test_a_grant_for_another_use_does_not_authorise_the_facet_read() -> None:
    """A use a grant does not name is not authorised by it (ADR-0097 §2).

    ADR-0140 §9 makes this sentence sayable for email specifically: "a user who
    grants ``FACET`` alone gets a count and no durable belief". The inverse is the
    case here — an ``INGEST`` grant authorises the ingestion path and not this one.
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
    are **discarded rather than used**: nothing reaches a prompt. ADR-0140 §13
    calls this "the breach with the worst consequence in the document", and every
    other test here passes while it happens.
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
        await EmailContextSource(reader=reader, grants=grants).contribute()

    assert reader.call_count == 1


async def test_a_grant_live_throughout_lets_the_reading_be_used() -> None:
    """Case five: the accepting case, without which the four refusals prove nothing.

    A gate that refused everything would pass all four above.
    """
    grants = _granted()

    contribution = await _source(_reader(_facet()), grants).contribute()

    assert contribution == {"email": _facet()}
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


# --- a wiring bug is not data to reconcile, in both directions --------------


async def test_a_calendar_facet_at_the_email_adapter_is_a_wiring_bug() -> None:
    """ADR-0096 §5: a mismatch raises ``ContextError`` (ADR-0140 §13).

    §6 records this clause "acquiring a second instance here for the first time,
    which is exactly the wiring bug it was written against" — a composition root
    that hands this adapter the calendar's reader. It is a deployment wired wrongly
    rather than data to reconcile, which is what ADR-0008 §4 reserves this error
    for.
    """
    source = _source(_reader(_calendar_facet()), _granted())

    with pytest.raises(ContextError, match="wiring bug"):
        await source.contribute()


async def test_an_email_facet_at_the_calendar_adapter_is_a_wiring_bug() -> None:
    """The same crossing the other way round, which is the direction a copy makes.

    A lane copying the calendar's adapter and changing only the reader ships an
    adapter that reads *email* and files it under ``calendar``. Asserting only the
    direction above would leave that one untested, and the two adapters are the
    same object with two pairings, so the property has to hold of both.
    """
    source = CalendarContextSource(reader=_reader(_facet()), grants=_granted())

    with pytest.raises(ContextError, match="wiring bug"):
        await source.contribute()


async def test_the_wiring_bug_names_the_field_it_was_wired_for() -> None:
    """Raised **instead of** contributing, under either field (ADR-0140 §13).

    The message is what tells an operator which pairing is wrong, and it is asserted
    because a guard that raised while naming the *other* adapter's field would point
    a deployment at the wrong half of its own composition root.
    """
    source = _source(_reader(_calendar_facet()), _granted())

    with pytest.raises(ContextError) as caught:
        await source.contribute()

    assert "'email'" in str(caught.value)
    assert "CalendarFacet" in str(caught.value)


# --- and through the assembler, where the field is the subject --------------


async def _assemble_with(*sources: ContextSource) -> CurrentContext:
    provider = AssemblingContextProvider(
        [ClockContextSource(now=lambda: _NOW), *sources],
    )
    return await provider.assemble()


async def test_a_granted_facet_reaches_the_assembled_context() -> None:
    """``CurrentContext.email`` **is** that facet (ADR-0140 §13).

    The item is written about the assembled context rather than about the mapping,
    because the mapping key and the field agreeing is exactly what a wrong literal
    would break silently.
    """
    context = await _assemble_with(_source(_reader(_facet()), _granted()))

    assert context.email == _facet()


async def test_two_facet_sources_each_reach_their_own_field() -> None:
    """The two adapters compose, and neither claims the other's field.

    ``AssemblingContextProvider`` treats two sources claiming one field as a wiring
    bug and raises, so an email adapter contributing under ``calendar`` beside a
    calendar adapter fails here loudly — and, alone, would fail silently. This is
    the arrangement a hub configured for both sources runs, minus the composition
    root that builds it (ADR-0140 §13's registration item, which is a later lane's).
    """
    context = await _assemble_with(
        CalendarContextSource(reader=_reader(_calendar_facet()), grants=_granted()),
        _source(_reader(_facet()), _granted()),
    )

    assert context.calendar == _calendar_facet()
    assert context.email == _facet()


@pytest.mark.parametrize(
    ("label", "grants", "reader"),
    [
        ("ungranted", FakeSourceGrants(), _reader(_facet())),
        ("no facet in the reading", _granted(), _reader(None)),
        ("the read failed", _granted(), _reader(_facet(), failure=OSError("gone"))),
        ("the grant store could not answer", _FailsOnTheRecheck(_granted()), _reader(_facet())),
    ],
)
async def test_every_absence_looks_identical_in_the_assembled_context(
    label: str, grants: SourceGrants, reader: FakeReader
) -> None:
    """ADR-0096 §4 and ADR-0097 §5: an absent facet says nothing beyond its absence.

    An ungranted mailbox is observationally identical to one that failed to read,
    because a field saying "email is not granted" is a model being handed a script
    to ask for access. The ``GrantError`` case is here too: it propagates *from the
    adapter* — the case above asserts that — and the **assembler** is what turns it
    into an absent facet, this source carrying no ``required`` marker.

    ADR-0140 §9's fourth clause is the one this cannot show and a surface must
    honour: an absent facet says nothing about whether mail is still being fetched
    onto the box by a process outside this system.
    """
    context = await _assemble_with(EmailContextSource(reader=reader, grants=grants))

    assert context.email is None, label
    assert context.now == _NOW, label  # the rest of the context assembled
