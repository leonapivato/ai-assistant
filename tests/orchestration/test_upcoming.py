"""The upcoming-event producer: the gate, the window, the key, and the silence.

ADR-0132's producer, held to its own clauses. Every collaborator is a canonical
fake from ``ai_assistant.testing``, so nothing here imports a subsystem concrete —
nor a concrete *reader*, which ``lint-imports`` forbids this layer outright
(ADR-0093 §2). The reader's own clauses are its conformance suite's and are never
re-asserted here; what is under test is the **stage**.

Two hand-rolled doubles earn their place. :class:`_RecordingWriter` is what makes
"the producer offers and decides nothing" checkable: the canonical
``FakeNotificationWriter`` is a real seam over a real store, and the assertions
below are about *what was offered*, which a store answers only after a policy has
already been allowed to drop it. And :class:`_FailingWriter` has to be scripted
because "a run that fails partway leaves what it offered offered" (§5) is a claim
about offers that really landed before the failure.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import (
    GrantError,
    NotificationStoreError,
    ReaderError,
    SourceNotGrantedError,
)
from ai_assistant.core.types import (
    DataTier,
    GrantScope,
    NotificationCondition,
    NotificationDisposition,
    NotificationDispositionKind,
    ReportedExtent,
)
from ai_assistant.orchestration import UpcomingEventStage
from ai_assistant.orchestration.upcoming import CONFIDENCE, NOTIFICATION_CLASS, PRODUCER
from ai_assistant.testing import (
    FakeReader,
    FakeSourceGrants,
    attested_proposal,
    source_grant,
)
from ai_assistant.testing.readers import DEFAULT_READER_NAME

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import NotificationWriter, Reader, SourceGrants
    from ai_assistant.core.types import (
        MemoryUpdateProposal,
        NotificationCandidate,
        SourceGrant,
    )

#: The instant every reading in this module claims it acquired its bytes.
#: Deliberately not "now": the whole of §4 turns on the producer anchoring on the
#: reading's own ``read_at``, and a fixture that used the wall clock could not tell
#: an implementation that read `read_at` from one that read a clock.
_READ_AT = datetime(2026, 6, 1, 14, 0, tzinfo=UTC)

#: The lead window every case uses unless it says otherwise. Not the shipped
#: thirty minutes, so a stage that ignored its argument and hardcoded the default
#: would be visible here.
_LEAD = timedelta(minutes=20)


class _CountingClock:
    """A ``Clock`` that records every reading and answers a fixed instant.

    Fixed rather than moving, and deliberately **later** than :data:`_READ_AT`: an
    implementation that anchored on this instead of on the reading would select a
    different set of occurrences and stamp a different ``noticed_at``, so the
    substitution is visible in the assertions rather than only in the counter.
    """

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> datetime:
        """Answer, and count that the producer asked."""
        self.calls += 1
        return _READ_AT + timedelta(minutes=13)


class _FailsOnTheRecheck:
    """A ``SourceGrants`` that answers once and raises from every later ``live``.

    A thin scripted wrapper around the canonical fake, which is ``@final`` and
    whose own ``fail_live`` script arms *every* call — while the case under test
    needs the failure to arrive **between** two of them. Everything the driver
    observes is the canonical fake's; what is scripted here is only when the arming
    happens. ``tests/orchestration/test_ingestion.py`` carries the same double for
    the same clause over the other driver.
    """

    def __init__(self, inner: FakeSourceGrants) -> None:
        self._inner = inner

    async def live(self, *, source: str, use: GrantScope) -> SourceGrant | None:
        """Delegate, then arm the fake so the next call raises."""
        answer = await self._inner.live(source=source, use=use)
        self._inner.fail_live()
        return answer


class _RecordingWriter:
    """A ``NotificationWriter`` that records what it was offered and rules ``HOLD``.

    ``HOLD`` rather than ``INTERRUPT`` deliberately: the producer must behave
    identically whatever comes back, and a fixture that returned the *interesting*
    disposition would hide a producer that branched on it — which §8 forbids
    outright ("The producer does not set, propose or influence a disposition").
    """

    def __init__(self) -> None:
        self.offered: list[NotificationCandidate] = []

    async def offer(self, candidate: NotificationCandidate) -> NotificationDisposition:
        """Record the offer and rule the untuned default."""
        self.offered.append(candidate)
        return NotificationDisposition(
            kind=NotificationDispositionKind.HOLD,
            notification_id=f"n-{len(self.offered)}",
            notification_class=candidate.notification_class,
            ruled_at=_READ_AT,
            reason=NotificationCondition.REACH_INTERRUPT,
            failed=(NotificationCondition.REACH_INTERRUPT,),
        )


class _FailingWriter(_RecordingWriter):
    """A writer that raises ``NotificationStoreError`` on its *n*-th offer."""

    def __init__(self, *, fail_on: int) -> None:
        super().__init__()
        self._fail_on = fail_on

    async def offer(self, candidate: NotificationCandidate) -> NotificationDisposition:
        """Delegate, except on the offer the script names."""
        if len(self.offered) + 1 == self._fail_on:
            msg = "the notification store is broken"
            raise NotificationStoreError(msg)
        return await super().offer(candidate)


def _occurrence(
    *,
    starts_in: timedelta,
    lasts: timedelta = timedelta(hours=1),
    summary: str = "Calendar entry",
    record_id: str | None = None,
) -> MemoryUpdateProposal:
    """One per-occurrence proposal of the shape a calendar reading carries.

    ``starts_in`` is measured from :data:`_READ_AT`, which is what every clause of
    §4 is measured from too.
    """
    start = _READ_AT + starts_in
    return attested_proposal(
        f"{summary}, {start.isoformat()}.",
        reported_by=DEFAULT_READER_NAME,
        record_id=record_id,
        extent=ReportedExtent(extends_from=start, extends_until=start + lasts),
    )


class Harness:
    """A producer over a scripted reading, granted unless a case says otherwise."""

    def __init__(
        self,
        proposals: Sequence[MemoryUpdateProposal] = (),
        *,
        reader: Reader | None = None,
        grants: SourceGrants | None = None,
        writer: NotificationWriter | None = None,
        lead: timedelta = _LEAD,
    ) -> None:
        self.reader: Reader = (
            reader if reader is not None else FakeReader(list(proposals), read_at=_READ_AT)
        )
        # Granted throughout unless a case scripts otherwise. Every case other than
        # the gate's own is about what the producer does with a reading it was
        # *permitted* to take, so an ungranted default would make them all vacuous.
        self.grants: SourceGrants = (
            grants if grants is not None else FakeSourceGrants([source_grant(self.reader.name)])
        )
        self.writer = writer if writer is not None else _RecordingWriter()
        #: Counts every reading. ADR-0132 §1 has the producer hold a clock and §4
        #: forbids it anchoring on one, so "held" and "unread" are two assertions
        #: and this is what makes the second checkable.
        self.clock = _CountingClock()
        self.stage = UpcomingEventStage(
            reader=self.reader,
            grants=self.grants,
            writer=self.writer,
            now=self.clock,
            lead=lead,
        )

    @property
    def offered(self) -> list[NotificationCandidate]:
        """What the producer actually offered."""
        assert isinstance(self.writer, _RecordingWriter)
        return self.writer.offered


# --- what it concludes (ADR-0132 §5, §6, §7) ----------------------------------


async def test_an_upcoming_occurrence_becomes_one_candidate_expiring_at_its_start() -> None:
    """§5's clause, which is the one the whole producer exists for.

    ADR-0130 §5 makes an expiry the sole route to ``INTERRUPT`` and requires it to
    be falsifiable; a calendar entry's start is falsifiable by the clock, by the
    user and by the source. **The end instant was considered and is wrong** — an
    expiry at the occurrence's end would keep a candidate actionable through a
    meeting the user is already sitting in, and would make a day-long entry
    interruptible for a day.

    The rest of the field assertions are §5's and §7's in one place, because they
    are one construction and a case per field would say the same thing six times.
    """
    starts_at = _READ_AT + timedelta(minutes=10)
    harness = Harness([_occurrence(starts_in=timedelta(minutes=10), summary="Standup")])

    assert await harness.stage.notice() == 1

    [candidate] = harness.offered
    assert candidate.expires_at == starts_at
    assert candidate.noticed_at == _READ_AT
    assert candidate.producer == PRODUCER
    assert candidate.notification_class == NOTIFICATION_CLASS
    assert candidate.confidence == CONFIDENCE
    assert candidate.sensitivity is DataTier.PERSONAL
    assert candidate.goal_id is None


async def test_the_sentence_is_the_reading_s_own_rendering_and_nothing_else() -> None:
    """§3: the producer computes no sentence and derives nothing from the facet.

    "Taking the rendered text as written rather than re-rendering it is what keeps
    the notification and the belief from disagreeing about the same entry — and
    keeps ``DESCRIPTION`` out of a durable, exportable record, which ``_render``
    already refuses for a belief and which a notification does not get a weaker
    rule about." A producer that composed its own summary would be free to reach
    for a field the reader deliberately declined to render.
    """
    proposal = _occurrence(starts_in=timedelta(minutes=5), summary="Dentist")
    harness = Harness([proposal])

    await harness.stage.notice()

    [candidate] = harness.offered
    assert candidate.summary == proposal.proposed.content
    assert candidate.detail is None


async def test_a_candidate_carries_no_record_references() -> None:
    """§5, and the answer #963 asks for in code rather than in prose.

    ADR-0130 §2 requires that "A reference is an identifier resolved through an
    existing ratified read", and this producer holds no identifier that meets it:
    the reader "mints its own id per record" (ADR-0092 §6), so the id on the
    proposal in hand is fresh on every read and, where ingestion is not running at
    all, names nothing in any store. Citing it would put a dangling identifier on a
    durable record and make a surface that tried to resolve it fail — the shape
    §2's clause exists to prevent, reached by obeying its letter.

    The proposal below carries a named record id precisely so that a producer
    which cited it would be caught rather than merely unproven.
    """
    harness = Harness([_occurrence(starts_in=timedelta(minutes=5), record_id="r-visible")])

    await harness.stage.notice()

    [candidate] = harness.offered
    assert candidate.references == ()


# --- the lead window (ADR-0132 §4) --------------------------------------------


async def test_an_occurrence_starting_exactly_at_the_read_is_not_noticed() -> None:
    """§4's lower edge is exclusive, and it is a refusal seen from the other side.

    An occurrence starting *at* ``read_at`` has an expiry that is not later than
    the instant it was noticed, and ADR-0130 §2 refuses such a candidate at
    validation: "a candidate that has already perished is not a proposal, it is a
    defect". Selecting it would make the producer offer a defect on a schedule, so
    the window's own edge is what keeps that unconstructable rather than a second
    guard downstream.
    """
    harness = Harness([_occurrence(starts_in=timedelta(0))])

    assert await harness.stage.notice() == 0
    assert harness.offered == []


async def test_an_occurrence_that_has_already_started_is_not_noticed() -> None:
    """The past half of the same edge: "this is about to happen" has perished.

    ADR-0130 §7's reading of expiry — "Expiry ends a record's interruptibility and
    its actionability" — is exactly the behaviour wanted: at 14:01 the meeting at
    14:00 is not news.
    """
    harness = Harness([_occurrence(starts_in=-timedelta(minutes=1))])

    assert await harness.stage.notice() == 0


async def test_an_occurrence_starting_exactly_at_the_lead_horizon_is_not_noticed() -> None:
    """§4's upper edge is exclusive, on ADR-0093 §7b's half-open convention.

    The reader's own window is ``[window_start, window_end)`` for the same reason,
    and a producer that closed its interval would notice one occurrence twice at
    the seam between two ticks whose spacing happened to equal the lead.
    """
    harness = Harness([_occurrence(starts_in=_LEAD)])

    assert await harness.stage.notice() == 0


async def test_only_the_occurrences_inside_the_window_are_noticed() -> None:
    """The window selects, and everything the reading carries goes through it.

    Four occurrences: one already past, one at the lower edge, one inside, one
    beyond the horizon. Exactly one is a candidate, and a producer that took the
    reading whole — or that took only its first entry — fails here.
    """
    harness = Harness(
        [
            _occurrence(starts_in=-timedelta(hours=2), summary="Yesterday's"),
            _occurrence(starts_in=timedelta(0), summary="Now"),
            _occurrence(starts_in=timedelta(minutes=15), summary="Soon"),
            _occurrence(starts_in=timedelta(hours=3), summary="Later"),
        ]
    )

    assert await harness.stage.notice() == 1
    assert "Soon" in harness.offered[0].summary


async def test_the_lead_window_is_the_configured_one_and_not_a_constant() -> None:
    """§4 names thirty minutes as the *default*; the stage reads its argument.

    ADR-0093 §5's rule is that a figure a decision names cannot be satisfied
    elsewhere, and the corresponding hazard in an implementation is a constant that
    silently ignores what an operator configured — which looks identical to working
    for any deployment that left the default alone.
    """
    proposals = [_occurrence(starts_in=timedelta(minutes=45))]

    narrow = Harness(proposals, lead=timedelta(minutes=20))
    wide = Harness(proposals, lead=timedelta(hours=1))

    assert await narrow.stage.notice() == 0
    assert await wide.stage.notice() == 1


async def test_a_lead_window_of_no_width_is_refused_at_construction() -> None:
    """``Settings`` refuses it at load; the stage refuses it where it is used.

    ``service.scheduler``'s ``Job`` restates its interval's positivity for the same
    reason: a stage built in a test or from a future configuration that reads no
    setting must not be able to hold a window that notices nothing while reporting
    a healthy pass.
    """
    with pytest.raises(ValueError, match="strictly positive"):
        UpcomingEventStage(
            reader=FakeReader([]),
            grants=FakeSourceGrants(),
            writer=_RecordingWriter(),
            now=_CountingClock(),
            lead=timedelta(0),
        )


async def test_a_lead_window_that_is_not_exactly_a_timedelta_is_refused() -> None:
    """The type check **is** the finiteness guarantee, as both siblings argue.

    ``timedelta`` is subclassable; a native one cannot hold a non-finite value
    because its constructor overflows first, and a subclass is free to answer the
    comparisons the window is decided by however it likes. ``Job.__post_init__``
    and ``core.config``'s ``_only_a_duration`` each require the exact type for
    precisely this, and the failure here is the quiet kind: a window that answers
    "inside" for everything notices the whole calendar on every tick.
    """

    class _Sneaky(timedelta):
        def __ge__(self, other: object) -> bool:
            return False

    with pytest.raises(TypeError, match="exactly a timedelta"):
        UpcomingEventStage(
            reader=FakeReader([]),
            grants=FakeSourceGrants(),
            writer=_RecordingWriter(),
            now=_CountingClock(),
            lead=_Sneaky(minutes=20),
        )


# --- what it refuses to notice (ADR-0132 §3) ----------------------------------


async def test_an_occurrence_whose_proposal_declares_no_extent_is_not_noticed() -> None:
    """§3: "The producer never substitutes an instant the source did not give."

    ``ReportedExtent`` rules that "Declaring none is always available and always
    safe", and the calendar reader really does decline one for an occurrence of no
    width — so this is a shape the live reader produces rather than a hypothetical.
    A producer that fell back on ``read_at``, or on the reading's ``as_of``, would
    be telling the user an instant nobody reported.
    """
    harness = Harness(
        [attested_proposal("Calendar entry with no span.", reported_by=DEFAULT_READER_NAME)]
    )

    assert await harness.stage.notice() == 0


async def test_an_extent_that_declares_no_start_is_not_noticed() -> None:
    """§3's second limb: an extent open at its lower end states no start instant.

    ``ReportedExtent`` admits an open end in either direction, so this is a legal
    value rather than a malformed one — and there is nothing to expire at.
    """
    harness = Harness(
        [
            attested_proposal(
                "Calendar entry ending sometime.",
                reported_by=DEFAULT_READER_NAME,
                extent=ReportedExtent(extends_until=_READ_AT + timedelta(minutes=5)),
            )
        ]
    )

    assert await harness.stage.notice() == 0


# --- the candidate key (ADR-0132 §6) ------------------------------------------


async def test_the_same_occurrence_yields_the_same_key_across_runs() -> None:
    """§6: the key reads no clock, no minted id and nothing derived from the run.

    This is what makes ADR-0130 §8's duplicate suppression work at all, and it is
    what buys §10's "no cursor": the producer re-offers on every tick and the
    chassis folds it. Two readings a day apart, with freshly minted record ids,
    must produce one key — a key holding either would fold nothing and the user
    would be told the same thing every interval.
    """
    first = Harness([_occurrence(starts_in=timedelta(minutes=10), record_id="r-1")])
    later = Harness(
        [_occurrence(starts_in=timedelta(minutes=10), record_id="r-2")],
        reader=FakeReader(
            [_occurrence(starts_in=timedelta(minutes=10), record_id="r-2")],
            read_at=_READ_AT - timedelta(minutes=5),
        ),
        lead=timedelta(hours=2),
    )

    await first.stage.notice()
    await later.stage.notice()

    assert first.offered[0].candidate_key == later.offered[0].candidate_key


async def test_two_different_entries_at_the_same_hour_are_two_candidates() -> None:
    """§6: the sentence is in the projection, and keying on the span alone loses one.

    "Keying on the span alone would fold two different meetings at the same hour
    into one candidate, so the second is never offered and never told — a loss."
    ADR-0093 §5 has already ruled this direction for this source: "the failure is
    duplication, not loss", because duplication is bounded by ADR-0130 §7's cap and
    §6's budget while loss is bounded by nothing and is invisible.
    """
    harness = Harness(
        [
            _occurrence(starts_in=timedelta(minutes=10), summary="Dentist"),
            _occurrence(starts_in=timedelta(minutes=10), summary="Standup"),
        ]
    )

    assert await harness.stage.notice() == 2

    first, second = harness.offered
    assert first.candidate_key != second.candidate_key


async def test_the_same_entry_moved_to_another_hour_is_another_candidate() -> None:
    """§6's other half, and the cost ADR-0132's Consequences concede deliberately.

    "A rewritten entry notifies twice… That is #631's shape reaching a second
    surface, and it is the direction chosen deliberately over losing an event." The
    span is in the projection, so a moved meeting is a second candidate — which is
    the behaviour, not a defect to fix here.
    """

    def entry(starts_in: timedelta, ends_in: timedelta) -> MemoryUpdateProposal:
        # **The sentence is held byte-identical while the span moves**, which the
        # ordinary fixture cannot do: a real rendering names the time, so a moved
        # entry differs in both halves of the projection at once and a key holding
        # only the sentence would pass. Pinning the text is what isolates the span.
        return attested_proposal(
            'Calendar entry "Standup".',
            reported_by=DEFAULT_READER_NAME,
            extent=ReportedExtent(
                extends_from=_READ_AT + starts_in, extends_until=_READ_AT + ends_in
            ),
        )

    # **One endpoint moves at a time**, so each is proved to be in the projection
    # on its own: a key holding the end alone would fold the first two, and one
    # holding the start alone would fold the first and the third.
    base = Harness([entry(timedelta(minutes=10), timedelta(minutes=70))])
    moved_start = Harness([entry(timedelta(minutes=15), timedelta(minutes=70))])
    moved_end = Harness([entry(timedelta(minutes=10), timedelta(minutes=130))])

    await base.stage.notice()
    await moved_start.stage.notice()
    await moved_end.stage.notice()

    keys = {
        base.offered[0].candidate_key,
        moved_start.offered[0].candidate_key,
        moved_end.offered[0].candidate_key,
    }
    assert len(keys) == 3


async def test_the_key_is_a_digest_over_those_four_values_and_nothing_else() -> None:
    """§6: "over the producer's declared name, the occurrence's rendered sentence
    and its extent's two endpoints, **and over nothing else**".

    The three cases above prove the sentence and the two endpoints are *in* the
    projection; none of them can prove what is *out* of it, and none reaches the
    producer's name at all — there is one producer in the tree, so no fixture
    distinguishes it, and §11 keys a later producer's namespace on exactly that
    value ("a later producer over the same file is a later lane with its own key
    namespace… and §6's key holds the producer's name for exactly that reason").

    So the projection is re-derived here rather than compared against a recorded
    literal. That is deliberate on both counts: a hardcoded digest would say
    nothing about *which* values went in, and importing the producer's own helper
    would make the test a tautology. The encoding is ADR-0021 §1's canonical JSON,
    restated so a change to either side is visible as a failure rather than
    absorbed.
    """
    start = _READ_AT + timedelta(minutes=10)
    end = start + timedelta(hours=1)
    sentence = 'Calendar entry "Standup", at 14:10.'
    harness = Harness(
        [
            attested_proposal(
                sentence,
                reported_by=DEFAULT_READER_NAME,
                record_id="r-not-in-the-key",
                extent=ReportedExtent(extends_from=start, extends_until=end),
            )
        ]
    )

    await harness.stage.notice()

    expected = sha256(
        json.dumps(
            [PRODUCER, sentence, start.isoformat(), end.isoformat()],
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert harness.offered[0].candidate_key == expected


async def test_a_conforming_reading_cannot_carry_a_blank_sentence() -> None:
    """Why this stage has **no** blank-summary guard, recorded as a test.

    ``NotificationCandidate.summary`` is non-blank while a ``MemoryRecord``'s
    ``content`` is not, so the obvious defensive move is to skip a proposal that
    rendered to nothing. It is declined, on ``IngestionStage``'s own posture: "No
    check stands between the reader and the writer, deliberately… re-asserting them
    here would be a second copy of a rule the seam already holds, sited where a
    reader's non-conformance would be reported as an ingestion fault rather than as
    the contract breach it is."

    The canonical fake is the evidence that the corpus already treats this as
    producer-side: ``attested_proposal`` refuses a blank rendering outright, and the
    live ``CalendarReader``'s ``_render`` falls back to "an untitled entry". A
    producer absorbing the defect would hide a broken reader behind a quiet
    calendar, which is exactly the shape ADR-0022 §4a keeps refusing.
    """
    with pytest.raises(ValueError, match="content must not be blank"):
        attested_proposal("   ", reported_by=DEFAULT_READER_NAME)


# --- the gate (ADR-0132 §2, ADR-0133 §5, ADR-0097 §5a) ------------------------


async def test_without_a_notify_grant_nothing_is_opened() -> None:
    """§2: "Where none does, nothing is opened: the source is not resolved, not
    opened and not parsed."

    **Refuse to read, not read-and-discard**, and the difference is the whole
    point: opening the user's calendar *is* the act the grant is about, and a
    design that read the file and then declined to conclude from it would already
    have done the thing it was not permitted to do — on the schedule. The
    assertion that carries this is ``call_count == 0``.
    """
    reader = FakeReader([_occurrence(starts_in=timedelta(minutes=5))], read_at=_READ_AT)
    harness = Harness(reader=reader, grants=FakeSourceGrants())

    with pytest.raises(SourceNotGrantedError):
        await harness.stage.notice()

    assert reader.call_count == 0
    assert harness.offered == []


@pytest.mark.parametrize("other", [GrantScope.FACET, GrantScope.INGEST])
async def test_a_grant_for_another_use_does_not_authorise_this_read(other: GrantScope) -> None:
    """ADR-0133 §2 rules the three members independent, and this is the site.

    "A live ``INGEST`` grant on this calendar authorises this read no more than a
    ``FACET`` one does." That independence is what makes "do not raise my calendar
    with me unprompted" a sentence the user can say while still letting the
    assistant answer questions from it — the strongest form of that sentence
    available in the corpus today.
    """
    reader = FakeReader([_occurrence(starts_in=timedelta(minutes=5))], read_at=_READ_AT)
    harness = Harness(
        reader=reader,
        grants=FakeSourceGrants([source_grant(reader.name, scope=[other])]),
    )

    with pytest.raises(SourceNotGrantedError):
        await harness.stage.notice()

    assert reader.call_count == 0


async def test_an_unanswerable_check_before_the_read_opens_nothing() -> None:
    """ADR-0097 §5a's third rule: fail closed, and propagate as itself.

    "The check failed, so carry on with what we already knew" is what an
    implementer writes when the alternative looks like losing a scheduled run; a
    missed tick costs one interval, and a read on a revocation nobody could see
    costs the property the grant exists to hold. The ``GrantError`` is propagated
    rather than converted, so an operator can tell a broken store from a user who
    has not said yes (§9).
    """
    reader = FakeReader([_occurrence(starts_in=timedelta(minutes=5))], read_at=_READ_AT)
    grants = FakeSourceGrants([source_grant(reader.name)])
    grants.fail_live()
    harness = Harness(reader=reader, grants=grants)

    with pytest.raises(GrantError):
        await harness.stage.notice()

    assert reader.call_count == 0


async def test_a_revocation_during_the_read_discards_the_reading_before_any_offer() -> None:
    """§2's discard limb, which is the one this producer has to place carefully.

    ADR-0130 §3 makes offering and persisting **one call**, so a producer that
    concluded first and re-checked afterwards would already have written the
    durable record — and ADR-0130 §6 rules that no setting change reaches a record
    already ruled. The re-check therefore lands between the read returning and the
    *first* offer, and a reading whose grant has gone yields no candidate at all
    rather than candidates that are then withdrawn.

    The read really happening is what makes this a test of the *re-check* rather
    than of the first gate.
    """
    reader = FakeReader(
        [_occurrence(starts_in=timedelta(minutes=n)) for n in (2, 5, 9)], read_at=_READ_AT
    )
    grants = FakeSourceGrants([source_grant(reader.name)])
    grants.revoke_after(1)  # the gate's check passes; the re-check does not
    harness = Harness(reader=reader, grants=grants)

    with pytest.raises(SourceNotGrantedError):
        await harness.stage.notice()

    assert reader.call_count == 1  # the read really did happen
    assert harness.offered == []  # and nothing was concluded from it


async def test_an_unanswerable_re_check_discards_the_reading_too() -> None:
    """Failing closed applies to the re-check as much as to the first check.

    A store that broke between the two would otherwise be the one window in which
    an ungranted reading reaches a durable record.
    """
    reader = FakeReader([_occurrence(starts_in=timedelta(minutes=5))], read_at=_READ_AT)
    grants = _FailsOnTheRecheck(FakeSourceGrants([source_grant(reader.name)]))
    harness = Harness(reader=reader, grants=grants)

    with pytest.raises(GrantError):
        await harness.stage.notice()

    assert reader.call_count == 1
    assert harness.offered == []


async def test_the_refusal_names_the_use_and_carries_no_path_or_entry_text() -> None:
    """ADR-0097 §8 and ADR-0004 §5: the scheduler logs ``str(exc)`` verbatim.

    So the message *is* an operational log line, and an entry's title or the
    calendar's path in it would be Tier 1 data in an operational log. The reader's
    identity is safe by construction — ADR-0093 §7 makes it declared rather than
    configured — and naming ``notify`` is what tells an operator which of the three
    grants is missing.
    """
    harness = Harness([_occurrence(starts_in=timedelta(minutes=5))], grants=FakeSourceGrants())

    with pytest.raises(SourceNotGrantedError) as caught:
        await harness.stage.notice()

    message = str(caught.value)
    assert GrantScope.NOTIFY.value in message
    assert DEFAULT_READER_NAME in message
    assert "Calendar entry" not in message


# --- failure posture and independence (ADR-0132 §5, §8, §9, §10) --------------


async def test_a_failed_read_offers_nothing_and_propagates() -> None:
    """§9: nothing is offered from a failed read, and the process is never taken down.

    A read that exceeds any of the reader's bounds is one of these — the bound is
    enforced by refusing and never by truncating (ADR-0093 §5) — and a producer
    offering candidates from the part that fitted would be noticing a subset of the
    day while reporting a full pass. The scheduler logs the class and retries at
    the next due instant.
    """
    harness = Harness(reader=FakeReader(failure=PermissionError("denied"), read_at=_READ_AT))

    with pytest.raises(ReaderError):
        await harness.stage.notice()

    assert harness.offered == []


async def test_a_calendar_with_nothing_starting_soon_is_a_successful_pass() -> None:
    """ADR-0093 §8: an empty reading is a success and never a failure signal.

    A producer that raised on "nothing to notice" would make a quiet week
    indistinguishable from a broken mount, in the direction that fills the log with
    false faults.
    """
    harness = Harness([])

    assert await harness.stage.notice() == 0


async def test_a_run_that_fails_partway_leaves_what_it_offered_offered() -> None:
    """§5: the runs are independent, and a partial pass is not a state to repair.

    "A run that fails partway leaves what it offered offered, claims nothing about
    what it did not, and is not retried other than by the next tick." That is
    ADR-0130 §8's guarantee spent rather than duplicated: a duplicate of an
    actionable record is dropped and writes nothing, so the next tick re-offers the
    first one for free.
    """
    writer = _FailingWriter(fail_on=2)
    harness = Harness(
        [_occurrence(starts_in=timedelta(minutes=n)) for n in (2, 5, 9)], writer=writer
    )

    with pytest.raises(NotificationStoreError):
        await harness.stage.notice()

    assert len(writer.offered) == 1  # the first landed; the third was never reached


async def test_every_selected_occurrence_is_offered_rather_than_a_chosen_subset() -> None:
    """§1: the producer ranks nothing and picks nothing.

    "A producer holding five upcoming events and a budget of three will want to
    pick. Picking is the numeric priority ADR-0130 §11 declined — 'Weighed by a
    producer, a score is self-granted authority' — and the aggregate is already
    bounded twice, by §6's budget and §7's cap, in a place the user can tune and
    the producer cannot."
    """
    harness = Harness(
        [_occurrence(starts_in=timedelta(minutes=n), summary=f"E{n}") for n in (1, 3, 5, 7, 9)]
    )

    assert await harness.stage.notice() == 5
    assert {candidate.confidence for candidate in harness.offered} == {CONFIDENCE}


async def test_the_producer_holds_no_state_between_runs_and_re_offers() -> None:
    """§5 and §10: no durable record of what was offered, and no cursor.

    ADR-0111 §11 rules a cursor out for a walk of exactly this shape — "A cursor is
    not the remedy for a receding window over somebody else's data" — and ADR-0130
    §8 is what makes the repetition safe: "A producer that re-notices the same fact
    on every tick is behaving as designed." A producer that suppressed its own
    re-offers would be holding the state §10 forbids, and would also lose the
    re-ruling the chassis performs when the user raises the class's reach.
    """
    harness = Harness([_occurrence(starts_in=timedelta(minutes=10))])

    assert await harness.stage.notice() == 1
    assert await harness.stage.notice() == 1

    first, second = harness.offered
    assert first == second


async def test_the_clock_it_holds_is_never_read() -> None:
    """§1 has the producer hold a clock; §4 forbids it anchoring on one.

    The two clauses are reconciled by holding it and never reading it, and this is
    what makes the second half checkable rather than a comment. §4: the instant a
    candidate was noticed "is the reading's own ``read_at`` … and never a later
    clock reading taken when the candidate was constructed or offered", and both
    the selection and ADR-0130 §2's validation are evaluated "against one instant,
    not two".

    **The counter is the weaker half of the assertion.** The injected clock answers
    thirteen minutes past the reading, so an implementation that anchored on it
    would select a different set — the occurrence at +25 leaves the window, the one
    at +5 falls behind it — and would stamp a different ``noticed_at``. Both are
    asserted, so a producer that read the clock fails on what it *concluded* and
    not only on having asked.
    """
    harness = Harness(
        [_occurrence(starts_in=timedelta(minutes=n), summary=f"E{n}") for n in (5, 15, 25)]
    )

    assert await harness.stage.notice() == 2

    assert harness.clock.calls == 0
    assert {candidate.noticed_at for candidate in harness.offered} == {_READ_AT}
    # Anchored on the reading, the window is (0, 20) and selects E5 and E15.
    # Anchored on the clock it would be (13, 33) and select E15 and E25 — the same
    # *count*, which is why the set is asserted rather than the number.
    assert {candidate.summary.split(",")[0] for candidate in harness.offered} == {"E5", "E15"}


def test_the_producer_holds_nothing_a_memory_or_a_model_would_need() -> None:
    """§1 and §8, pinned on the constructor rather than trusted to review.

    §1: "It holds no ``MemoryStore``, no ``MemoryWriter`` and no ``MemoryPolicy``,
    and it proposes no belief." §8: "It performs no model call. It holds no
    ``ModelProvider`` and no ``Embedder``, and no implementation may add one."
    Both are properties of what the object can be *given*, so the signature is
    where they are checkable — a later lane adding a store to build some
    convenience on would fail here rather than in review.
    """
    parameters = set(inspect.signature(UpcomingEventStage.__init__).parameters)

    assert parameters == {"self", "reader", "grants", "writer", "now", "lead"}
