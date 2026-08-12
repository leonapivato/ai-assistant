"""The upcoming-event producer: notice a start instant, conclude nothing else.

ADR-0132's decision in one object. It is a stage in `orchestration` driven by a
public operation on the concrete engine, which is in turn driven by a job on
ADR-0083 §7's scheduler whose body is that bound method and which "holds no store,
no reader and no subsystem import" — ``Engine.ingest``'s shape reused rather than
a new one (§1).

**It is not a second ingestion path** (§1). Whether a calendar entry becomes a
belief is ADR-0093's decision and the ingestion job's; whether it becomes a
candidate is ADR-0132's, and the two are independent both ways — a deployment may
run either, both or neither. So this stage holds no ``MemoryStore``, no
``MemoryWriter`` and no ``MemoryPolicy``, and it proposes no belief.

**What it may not conclude is as much of the decision as what it does** (§8). It
performs no model call and holds no ``ModelProvider`` and no ``Embedder``; it
forms no judgement about an occurrence's importance, urgency, priority or
interest; it never notices an *absence*, because "a bounded read, a truncated
file, a permission error and a genuinely deleted entry are indistinguishable from
the reading" (ADR-0093 §4); and it sets, proposes and influences no disposition,
no ``reconsider_at``, no reach level, no quiet window and no budget. It offers,
and ADR-0130 §5 and §6 decide.

**Nor does it pick.** §1: it "offers every occurrence its walk selects rather than
a chosen subset of them". A producer holding five upcoming events and a budget of
three will want to choose; choosing is the numeric priority ADR-0130 §11 declined
— "Weighed by a producer, a score is self-granted authority" — and the aggregate
is already bounded twice, by §6's budget and §7's cap, in a place the user can
tune and the producer cannot.

**And it holds no cursor** (§10). ADR-0111 §11 rules it directly for a walk of
exactly this shape: "A cursor is not the remedy for a receding window over
somebody else's data." The lead window is recomputed from the reading's own
acquisition instant on every run, so there is no accumulating backlog for a cursor
to track, and ADR-0130 §8 absorbs the repetition that buys — "A producer that
re-notices the same fact on every tick is behaving as designed."

Nothing concrete is imported: the reader, the grant seam and the notification
writer all arrive by injection and are seen only through their Protocols
(CLAUDE.md golden rule 1). ``lint-imports`` enforces that literally — no
subsystem, `orchestration` included, may import ``ai_assistant.readers``.

**Arming it is three independent acts and the recipe is not here** (§4): the
operator sets ``ASSISTANT_CALENDAR_UPCOMING_INTERVAL`` (unset, this stage never
runs), the user grants the source ``notify``, and the user raises
``upcoming_event``'s reach from ``hold``. All three are written out, with the
forms that exist and the ISO-8601 trap in the first, in
:mod:`ai_assistant.readers.calendar`'s module docstring — beside the source's own
deployment recipe, because that is where an operator connecting a calendar is
already reading and this project has no operator-facing docs tree to hold it
(#887, #981).
"""

from __future__ import annotations

import json
from datetime import timedelta
from hashlib import sha256
from typing import TYPE_CHECKING, Final

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import SourceNotGrantedError
from ai_assistant.core.types import DataTier, GrantScope, NotificationCandidate

if TYPE_CHECKING:
    from datetime import datetime

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import NotificationWriter, Reader, SourceGrants
    from ai_assistant.core.types import MemoryUpdateProposal, ReportedExtent

#: The producer's declared name (ADR-0130 §2, on ADR-0093 §7's rule for a reader's
#: identity): a stable Tier 2 constant, never derived from the source's location or
#: contents. It is in §6's key projection, which is what reserves this producer's
#: key namespace against a later producer over the same file (ADR-0132 §11).
PRODUCER: Final = "calendar-upcoming"

#: The **one** notification class every candidate carries (§7). Constant, never
#: derived from an entry's title, location or duration — a class derived from an
#: event would put Tier 1 content into a value the user tunes and a surface
#: renders — and distinct from the reader's own declared identity. One class is
#: also what makes the tuning surface usable: the user's act is "never interrupt
#: me about upcoming events", and a class per event kind would ask them to make
#: that decision repeatedly.
NOTIFICATION_CLASS: Final = "upcoming_event"

#: The single constant confidence (§7), derived from no property of the
#: occurrence. A confidence that varied would be the producer grading the events
#: it read, which is the derived judgement §8 forbids and the score ADR-0130 §11
#: declined; the constant states the only thing the producer actually knows — the
#: source said this.
#:
#: **The figure is the attested band's**, which the calendar reader already states
#: on every proposal drawn from the same content (ADR-0093 §4). Two constants for
#: one fact would be the same content graded two ways, which is the argument §7
#: itself makes for the sensitivity a line above. It is inert either way: no
#: condition of ADR-0130 §5 reads a candidate's confidence, and §4 rules it
#: "evidence on the proposal" rather than authority.
CONFIDENCE: Final = 0.9


def _refusal(source: str) -> str:
    """The refusal message ADR-0097 §8 makes an operator-legible obligation.

    **The identity and the use, and nothing else** — the shape
    :mod:`ai_assistant.orchestration.ingestion` already uses for the same reason.
    The scheduler logs a failed job's ``str(exc)`` verbatim (ADR-0083 §7), so this
    string is the log line, and a path or an entry's text here would be Tier 1
    data in an operational log (ADR-0004 §5). A reader's identity is safe by
    construction: ADR-0093 §7 makes it *declared* rather than configured.
    """
    return (
        f"no live {GrantScope.NOTIFY.value} grant covers the {source!r} source, so "
        f"nothing was read; grant it before the upcoming-event producer can run "
        f"(ADR-0097 §5, ADR-0133 §1)"
    )


def _extent_of(proposal: MemoryUpdateProposal) -> ReportedExtent | None:
    """The occurrence's span as the proposal's attestation carries it (§3).

    ``None`` where the proposal states no position for what it read — no
    attestation at all, or an attestation declaring no extent. The producer
    computes neither endpoint and substitutes nothing: ``ReportedExtent`` rules
    that "Declaring none is always available and always safe", and ADR-0092 §3
    permits no substitute for a report the source did not make.
    """
    attestation = proposal.proposed.provenance.attestation
    return None if attestation is None else attestation.extent


def _key(sentence: str, extent: ReportedExtent) -> str:
    """The ``candidate_key`` §6 fixes: the producer, the sentence and the span.

    A SHA-256 over the producer's declared name, the occurrence's rendered
    sentence and the extent's two endpoints, **and over nothing else**. It reads
    no clock, no minted identifier and nothing derived from the run, which is what
    ADR-0130 §8 requires of a key that has to fold a re-notice on the next tick.

    **The reader's own record id is deliberately excluded.** ADR-0092 §6 rules
    that an import "proposes each record at an id it mints, opaque to the source",
    so it is fresh on every read and a key holding one would fold nothing at all.

    **The sentence is in the projection and that is a decision, not padding**
    (§6). Keying on the span alone would fold two different meetings at the same
    hour into one candidate, so the second is never offered and never told — a
    loss. Keying on both means a retitled or moved entry yields a second candidate
    — a duplicate. ADR-0093 §5 has ruled this direction already for this source:
    "the failure is duplication, not loss". Duplication is bounded by ADR-0130
    §7's cap and §6's budget; loss is bounded by nothing and is invisible.

    The encoding is ADR-0021 §1's canonical JSON — UTF-8, no incidental
    whitespace — spelled here rather than borrowed, because the digests in
    ``core.types`` hash a *model projection* and this hashes four scalars in a
    fixed order. A list rather than an object, so the order is the code's and not
    a key sort's.

    Args:
        sentence: The occurrence's rendered text, exactly as the reading carried
            it.
        extent: The occurrence's span, whose start is known present by the caller.

    Returns:
        The hex digest, which is what the candidate carries.
    """
    end = extent.extends_until
    payload = [
        PRODUCER,
        sentence,
        # `extends_from` is non-None by the caller's own check; the endpoints go in
        # as the source gave them, and an open-ended span states its `None`.
        None if extent.extends_from is None else extent.extends_from.isoformat(),
        None if end is None else end.isoformat(),
    ]
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return sha256(text.encode("utf-8")).hexdigest()


class UpcomingEventStage:
    """Reads the calendar on its own cadence and offers what is about to start.

    **It holds a clock and never reads one, and both halves are ADR-0132's.** §1
    enumerates the producer's collaborators as "a ``Reader``, a ``SourceGrants``, a
    clock and the ``NotificationWriter`` seam of ADR-0130 §3", so the clock is held
    — a ratified ADR is not narrowed by an implementation's judgement that one of
    its collaborators has nothing to do. §4 then rules that it may not be *read*:
    the instant a candidate was noticed "is the reading's own ``read_at`` … and
    never a later clock reading taken when the candidate was constructed or
    offered", and both the window selection and ADR-0130 §2's validation are
    anchored on that one instant — "Selection and ADR-0130 §2's validation are
    evaluated against one instant, not two".

    **The two clauses only look contradictory, and the way they are reconciled is
    a test rather than a comment.** §4 spends four paragraphs on what a second
    clock reading here would cost — "the producer offers a defect, on a schedule,
    for a window whose width is its own parse time" — so the hazard of holding one
    is a later edit reaching for it. ``tests/orchestration/test_upcoming.py`` pins
    the invariant directly: a full pass over a reading full of upcoming
    occurrences calls the injected clock **zero** times. An implementation that
    began anchoring on it fails there rather than in review, which is what makes
    the held collaborator safe instead of merely explained.
    """

    def __init__(
        self,
        *,
        reader: Reader,
        grants: SourceGrants,
        writer: NotificationWriter,
        now: Clock,
        lead: timedelta,
    ) -> None:
        """Wire the producer from its reader, its grant seam, the notification seam.

        Args:
            reader: The producer's **own** instance, given its own source and its
                own bound (ADR-0093 §1, §5), so this stage neither locates the
                source nor widens the read. **Not shared with the ingestion stage
                or the context adapter**: ADR-0093 §7's one-outstanding-worker
                reservation is per instance, and ADR-0132 §3 requires this read to
                be independent of both — "Neither may derive its answer from the
                other's reading", and a producer reading a snapshot ingestion left
                behind would inherit a cadence chosen for a different job.
            grants: The **query** seam ADR-0133 §5 gates this stage on, and never
                a ``SourceGrantStore``. Required with no default, which is
                ADR-0097 §5's third clause applied to the third use of a source:
                a stage that cannot be built without a grant seam cannot be wired
                without one, and ``mypy --strict`` is the enforcer rather than a
                reviewer's memory. Narrow by type for §3's reason — a stage handed
                the whole store is a scheduler job that can mint its own
                authorisation.
            writer: ADR-0130 §3's single seam, and the whole of what this producer
                may do with what it noticed (§1). It holds no channel, no delivery
                seam and no client connection; its only outcome is the disposition
                this returns, and it may not select one, exempt itself from §5, or
                write to the store other than through here.
            now: The hub's clock, held because §1 enumerates it among this
                producer's collaborators and **read by nothing here** because §4
                anchors every instant on the reading's own ``read_at``. Stored
                through ``checked_clock`` like every other clock seam in the tree,
                on ADR-0026 §2 and on §7's refusal to exempt a clock whose consumer
                is advisory. The class docstring carries the reconciliation and the
                test that keeps it true.
            lead: How far ahead of a start instant an occurrence is noticed (§4).
                ``Settings`` has already refused a figure that is not strictly
                positive, that outruns the reader's own forward window, or that is
                not strictly greater than this job's interval.

        Raises:
            TypeError: If ``lead`` is not exactly a ``timedelta``.
            ValueError: If it is not strictly positive.

                ``Settings`` refuses both at load; these are the same rules
                restated where the invariant is actually *used*, exactly as
                ``service.scheduler``'s ``Job`` restates its interval's. A stage
                built in a test or from a future configuration that reads no
                setting must not be able to hold a window that selects nothing
                while reporting a healthy pass.
        """
        # **The type check is what makes "finite" true**, and both siblings make the
        # argument at length: `timedelta` is subclassable, a native one cannot hold
        # a non-finite value because its constructor overflows first, and a subclass
        # is free to override the comparisons the window below is decided by. So
        # requiring the exact type *is* the guarantee, and it needs no second check
        # that could never fire on a value which passed the first
        # (`core.config`'s `_only_a_duration`, `service.scheduler`'s `Job`).
        if type(lead) is not timedelta:
            msg = (
                f"the lead window must be exactly a timedelta, got {lead!r} of type "
                f"{type(lead).__name__}; a subclass is free to answer a comparison "
                f"however it likes, and the window below is decided by two of them "
                f"(ADR-0132 §4)"
            )
            raise TypeError(msg)
        # Compared against `timedelta(0)` directly rather than through
        # `total_seconds()`, so the guard never routes a duration through a float.
        if lead <= timedelta(0):
            msg = (
                f"the lead window must be strictly positive, got {lead!r}; a window of "
                f"no width notices nothing while reporting a successful pass "
                f"(ADR-0132 §4)"
            )
            raise ValueError(msg)
        self._reader = reader
        self._grants = grants
        self._writer = writer
        # **Wrapped rather than stored raw, and ADR-0026 §7 is why it is wrapped
        # even here.** §2 requires every constructor holding a clock to store
        # `checked_clock(now, owner=...)`, and §7 refuses an exemption for a clock
        # whose consumer is advisory or absent in as many words: "A rule that
        # exempted 'advisory' clocks would oblige every future author to classify
        # their clock, with nothing checking the guess and a wrong timestamp —
        # unfalsifiable afterwards — as the failure." Nothing here reads it (§4),
        # so the guard is inert today; what it buys is that the day a clause does,
        # the reading is already held to §3's range and to ADR-0023 §5's aware.
        self._now = checked_clock(now, owner="UpcomingEventStage")
        self._lead = lead

    async def notice(self) -> int:
        """Read the source once and offer a candidate per upcoming occurrence.

        The whole operation, in §1's order: check, read, re-check, then offer. There
        is no selection step beyond §4's window and no cursor — §10.

        **Nothing is read without a live ``NOTIFY`` grant** (§2, ADR-0133 §5). The
        source is not resolved, not opened and not parsed: opening the user's
        calendar *is* the act the grant is about. No other member substitutes,
        because ADR-0133 §2 rules the three uses independent — a live ``INGEST``
        grant on this calendar authorises this read no more than a ``FACET`` one
        does — and ADR-0133 §3 rules that no grant recorded before the member
        existed acquires it.

        ADR-0097 §5a's three driver rules apply unchanged. No ``await`` stands
        between the ``live()`` answer and ``read()``; the grant is re-checked when
        ``read()`` returns and the reading is **discarded entire** if it has gone;
        and an unanswerable check fails closed. **The discard limb is the one this
        producer has to place carefully** (§2): ADR-0130 §3 makes offering and
        persisting one call, so a producer that concluded first and re-checked
        afterwards would already have written the durable record. The re-check
        therefore lands between the read returning and the *first* offer, and a
        reading whose grant has gone yields no candidate at all rather than
        candidates that are then withdrawn.

        **A revocation reaches the next read and no record already offered** (§9).
        ADR-0097 §6 is that revoking "stops the reading and does not unwrite the
        beliefs"; a notification record is the same kind of thing on the same
        reasoning, and the user's remedy is the dismissal and the per-record delete
        ADR-0130 §9 places on the store.

        **The runs are independent** (§5). A run that fails partway leaves what it
        offered offered, claims nothing about what it did not, and is not retried
        other than by the next tick. That is ADR-0130 §8's guarantee spent rather
        than duplicated: a duplicate of an actionable record is dropped and writes
        nothing, so a re-offer is free and a partial pass is not a state to repair.

        Returns:
            How many candidates were offered — never how many were *ruled*
            anything, because the disposition is ADR-0130 §5's and this producer
            neither selects nor influences one (§8). Zero is a **successful** pass
            over a calendar with nothing starting soon, and no caller may read it
            as a failure (ADR-0093 §8).

        Raises:
            SourceNotGrantedError: If no live ``NOTIFY`` grant covers this reader —
                at the check before the read, or at the re-check after it. **Never
                reported as a successful pass and never as a source failure** (§9):
                an ungranted pass reported as zero candidates is indistinguishable
                from "nothing starts in the next half hour", so a deployment whose
                grant was revoked would look healthy while noticing nothing. A
                deployment that leaves the interval set after a revocation
                therefore logs a refusal every interval, which is configuration and
                consent disagreeing out loud rather than a defect to design around.
            GrantError: If the grant store could not answer, before or after the
                read. **Propagated rather than converted**: ADR-0097 §5a's last
                clause keeps an unanswerable grant store distinguishable in the log
                from a user who has not said yes.
            ReaderError: If the read could not complete because of its source —
                missing, unreadable, malformed, over a bound, or past the reader's
                own deadline. Nothing is offered from a failed read and the process
                is never taken down; the scheduler logs it with its class and
                retries at the next due instant (§9). A read that exceeds one of
                the reader's bounds is one of these: the bound is enforced by
                refusing and never by truncating (ADR-0093 §5), and a producer
                offering candidates from the part that fitted would be noticing a
                subset of the day while reporting a full pass.
            NotificationStoreError: If the notification store could not rule or
                record.
            NotificationOutboxError: If a ruled interruption could not be handed to
                the delivery seam (ADR-0131 §3b).
            CancelledError: Re-raised unchanged from a cancelled read, so a
                shutdown that is working correctly is not logged as a source fault.
        """
        source = self._reader.name
        # The check and the start of the read are one synchronous step: nothing
        # between this `await` returning and `read()` being called may suspend.
        if await self._grants.live(source=source, use=GrantScope.NOTIFY) is None:
            raise SourceNotGrantedError(_refusal(source))
        reading = await self._reader.read()
        # The revocation that landed while the read ran wins: the reading is
        # discarded whole, before the first offer, and nothing durable records that
        # it happened (ADR-0133 §5).
        if await self._grants.live(source=source, use=GrantScope.NOTIFY) is None:
            raise SourceNotGrantedError(_refusal(source))
        offered = 0
        for proposal in reading.proposals:
            candidate = self._candidate(proposal, reading.read_at)
            if candidate is None:
                continue
            await self._writer.offer(candidate)
            offered += 1
        return offered

    def _candidate(
        self, proposal: MemoryUpdateProposal, read_at: datetime
    ) -> NotificationCandidate | None:
        """One upcoming occurrence as a candidate, or ``None`` if it is not one.

        **Both the selection and ADR-0130 §2's validation are evaluated against
        one instant, and separating them is how the defect gets in** (§4). The
        instant a candidate was noticed is the reading's own ``read_at`` — the
        acquisition instant the reader stamps once — and never a later clock
        reading taken when the candidate was constructed. Select against ``read_at``
        but stamp a clock read after parsing, and an occurrence starting in between
        is selected here and refused by ``NotificationCandidate``'s own coherence
        validator: the producer offers a defect, on a schedule, for a window whose
        width is its own parse time. Anchoring both on ``read_at`` closes it by
        construction rather than by a second guard.

        **Backdating is the objection, and ``read_at`` is what the corpus means by
        the instant of a reading.** Every value this reading carries is stamped
        with it though computed afterwards — ``CalendarFacet.entries_in_progress``
        is membership "evaluated at an instant" that is ``read_at``, and every
        proposal's ``provenance.last_updated`` is ``read_at`` — because it is "the
        moment the bytes this reading describes came into our hands" and a drifting
        anchor gives proposals describing the 10:05 file stamped 10:00. A producer
        stamping its own later clock would be the one value in the reading that
        disagreed with the reading (ADR-0093 §7b).

        **The case that objection is really about is handled by the chassis rather
        than here** (§4). An occurrence starting between ``read_at`` and the offer
        — a five-second lead on a ten-second parse — is selected here and is a
        *valid* candidate at validation, because its expiry is later than the
        instant it was noticed. It is then ruled against the **ruling** instant,
        and ADR-0130 §5's first ``DROP`` condition is "the candidate declares an
        expiry not later than the ruling instant". So it is dropped, naming expiry,
        writing no durable record. Nothing is offered late, nothing is refused as a
        defect, and this producer needs no second guard.

        Args:
            proposal: One of the reading's per-occurrence proposals.
            read_at: The reading's acquisition instant — the one anchor.

        Returns:
            The candidate, or ``None`` where this occurrence is not noticed.
        """
        extent = _extent_of(proposal)
        # §3: "An occurrence whose proposal declares no extent, or whose extent
        # declares no start, is not noticed. The producer never substitutes an
        # instant the source did not give."
        if extent is None or (start := extent.extends_from) is None:
            return None
        # §4's half-open window, `(read_at, read_at + lead)`. Written as a
        # difference rather than as `start < read_at + self._lead` so that no
        # instant is computed at all: a `datetime` sum can overflow at the
        # representable edge, where a `datetime` difference cannot — the widest
        # possible gap is far inside `timedelta`'s range. The lower edge is
        # exclusive so an occurrence starting exactly at `read_at` is not noticed,
        # which is the refusal above seen from the selecting side; the upper edge
        # is exclusive on ADR-0093 §7b's half-open convention, which the reader's
        # own window already follows.
        if start <= read_at or start - read_at >= self._lead:
            return None
        # §3: the sentence the user would be told is the belief's own rendered
        # content, taken as written rather than re-rendered. That is what keeps the
        # notification and the belief from disagreeing about the same entry, and it
        # keeps `DESCRIPTION` out of a durable, exportable record — which `_render`
        # already refuses for a belief and which a notification does not get a
        # weaker rule about.
        #
        # **No guard stands between the reading and the candidate, deliberately.**
        # `NotificationCandidate.summary` is non-blank while a `MemoryRecord`'s
        # `content` is not, so a reader emitting a blank rendering raises out of
        # here — and that is the right outcome rather than a case to skip. It is
        # `IngestionStage`'s own posture, in its words: re-asserting a producer-side
        # obligation here would be "a second copy of a rule the seam already holds,
        # sited where a reader's non-conformance would be reported as an ingestion
        # fault rather than as the contract breach it is". The `Reader` conformance
        # suite pins what a reader may emit; this stage is not a second place to
        # pin it, and absorbing the defect would hide a broken reader behind a
        # quiet calendar.
        sentence = proposal.proposed.content
        return NotificationCandidate(
            candidate_key=_key(sentence, extent),
            producer=PRODUCER,
            notification_class=NOTIFICATION_CLASS,
            summary=sentence,
            # No detail: the sentence is the whole of what this producer carries,
            # and there is no second field of the entry it is permitted to render.
            detail=None,
            noticed_at=read_at,
            # §5, and the clause this whole producer exists for: the expiry is the
            # occurrence's start, as the source reported it and as the extent
            # carries it. ADR-0130 §5 makes an expiry the sole route to `INTERRUPT`
            # and requires it to be falsifiable; a calendar entry's start is
            # falsifiable by the clock, by the user and by the source. **The end
            # instant was considered and is wrong**: an expiry at the occurrence's
            # end would keep a candidate actionable through a meeting the user is
            # already sitting in, and would make a day-long entry interruptible for
            # a day. At 14:01 the meeting at 14:00 is not news.
            expires_at=start,
            goal_id=None,
            confidence=CONFIDENCE,
            # §7: stated by the producer and never defaulted. The reader's
            # proposals over the identical content state the same tier, and a
            # notification carrying a weaker one would be the same content
            # classified two ways (ADR-0093 §4).
            sensitivity=DataTier.PERSONAL,
            # §5: **no record references**, and empty is a decision here rather
            # than an omission. ADR-0130 §2 requires that "A reference is an
            # identifier resolved through an existing ratified read", and this
            # producer holds no identifier that meets it: the reader "mints its own
            # id per record" (ADR-0093 §5, ADR-0092 §6), so the id on the proposal
            # in hand is fresh on every read and, where ingestion is not running at
            # all, names nothing in any store. Citing it would put a dangling
            # identifier on a durable record and make a surface that tried to
            # resolve it fail — the shape §2's clause exists to prevent. The
            # subject is an occurrence in a source this system does not own, which
            # is not a record this system holds (#963).
            references=(),
        )


__all__ = [
    "CONFIDENCE",
    "NOTIFICATION_CLASS",
    "PRODUCER",
    "UpcomingEventStage",
]
