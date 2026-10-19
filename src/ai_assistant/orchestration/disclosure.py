"""ADR-0199's disclosure ruling over recorded origin (ADR-0200 §7, ADR-0203 §1).

ADR-0199 decides what may be said on a channel of unbounded audience. This module
decides nothing it decides; what it holds is the one predicate its rules are applied
through, :func:`_speakable`, and the two audience postures a pass is minted with. The
phases apply the predicate to what an activation is given — its windows' records
(:func:`admitted_to_understanding`, ADR-0276 §4), the records recall keeps and the
records a call returns — and the activation's capture takes ADR-0204 §2's value over
the same predicate (ADR-0309 §5:10,
:class:`~ai_assistant.orchestration.supplied_records.SuppliedRecords`).

**At supply, and never as a filter over composed prose** (ADR-0199 §5). Nothing here
reads a composed answer, and nothing anywhere removes, masks, blanks or rewrites part
of one: a filter over prose is content inspection, which ADR-0199 §2 forbids as a
decision procedure and which "fails silently on the first sentence phrased in a way
the filter did not anticipate", and a composed answer with a hole cut in it is an
utterance a listener "cannot distinguish from a complete one".

**The class is decided from recorded origin, never by inspecting the words**
(ADR-0199 §2). For a record that is :attr:`~ai_assistant.core.types.MemoryBase.about_person`,
:attr:`~ai_assistant.core.types.Provenance.source` and — where the band is
``ATTESTED`` — :attr:`~ai_assistant.core.types.Attestation.reported_by`, and since
ADR-0204 §3 a **fourth** recorded field, which ADR-0217 §1 moved onto the envelope
and widened: :attr:`~ai_assistant.core.types.MemoryBase.placement`. No content is
read: not ``MemoryBase.content``, not a keyword, not a pattern, not a classifier, and
not a model asked what a passage is about.

**The fourth read is a second reason to withhold, not a fifth class placement**
(ADR-0204 §3, §11; ADR-0217 §2). ADR-0199 §3's placements are computed exactly as
they were — no class becomes speakable or unspeakable here — and a record whose
own placement does not admit this channel's audience is withheld whatever §3's
third clause would otherwise place it as. Since ADR-0217 §1 the record's reach is
narrowed by the owner's own act and by a model's proposal as well as by that
derivation, and this read is unmoved by which of the three wrote it: it is a
**conjunct**, so it can only subtract.

**The evaluation is also made on a channel whose audience is bounded, where nothing
is withheld** (ADR-0204 §2, §4). The predicate is the same on both postures; what the
posture decides is whether a record the predicate does not place is held back, never
whether the evaluation is made.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, final

from ai_assistant.core.types import (
    BeliefBand,
    DataTier,
    MemorySource,
    PlacementReach,
    band_of,
    record_attestation,
    record_band,
)
from ai_assistant.orchestration.upcoming import NOTIFICATION_CLASS, PRODUCER

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import NotificationCandidate, SuppliedRecord

__all__ = [
    "BoundedAudienceSupply",
    "TurnSupply",
    "UnboundedAudienceSupply",
    "admits_owner_placed",
    "admitted_to_understanding",
    "notification_is_speakable",
    "speakable_notification_triple",
    "speakable_sources",
]

#: The provenance sources ADR-0199 §3 places as speakable on a channel of
#: unbounded audience, where ``about_person`` is not stated. The fourth member of
#: :class:`~ai_assistant.core.types.MemorySource` — ``EXTERNAL`` — is deliberately
#: absent: it is the ``ATTESTED`` band, which §3 places only for the calendar
#: source, and a member this set does not name is withheld.
_PLACED_SOURCES: Final[frozenset[MemorySource]] = frozenset(
    {MemorySource.USER_ASSERTED, MemorySource.OBSERVED, MemorySource.INFERRED}
)

#: The bands :data:`_PLACED_SOURCES` names, which is how a memory is placed: ADR-0328
#: §12 reads ``USER_ASSERTED`` as band ``ASSERTED`` and ``OBSERVED`` and ``INFERRED``
#: as band ``DERIVED``.
_PLACED_BANDS: Final[frozenset[BeliefBand]] = frozenset(
    band_of(source) for source in _PLACED_SOURCES
)


@final
@dataclass(slots=True)
class UnboundedAudienceSupply:
    """A pass whose output channel's audience is unbounded (ADR-0199 §1, ADR-0203 §1).

    **One instance per pass, minted by the operation that declares its channel
    unbounded.** On this posture a record :func:`_speakable` does not place is held
    back from what the pass is given.

    Attributes:
        speakable_attested_sources: The ``Attestation.reported_by`` identities
            ADR-0199 §3 places as speakable on this channel — the calendar source
            ADR-0093 §7 configures, and nothing else. Supplied by the composition
            root, which is the only layer that knows which reader was built and what
            identity it carries (ADR-0190 §7's minted discriminator included). Empty
            where no calendar is configured, which withholds every attested record
            rather than guessing at a name.
    """

    speakable_attested_sources: frozenset[str]


@final
@dataclass(slots=True)
class BoundedAudienceSupply:
    """A pass whose output channel's audience is bounded (ADR-0204 §2, §4).

    The twin of :class:`UnboundedAudienceSupply`, and deliberately the *same*
    predicate: what varies by the channel's audience is whether a record the
    predicate does not place is held back, and never whether the evaluation is made.
    On this posture nothing is held back, and capture still records whether anything
    would have been (ADR-0309 §5:10).

    Attributes:
        speakable_attested_sources: The identities ADR-0199 §3 places, as
            :class:`UnboundedAudienceSupply` holds them, for the evaluation capture
            takes.
    """

    speakable_attested_sources: frozenset[str]


#: The two postures one pass's audience can take, and there are exactly two:
#: ADR-0199 §1 fixes the posture as a function of the output channel's audience
#: alone, and ADR-0204 §2 makes the *evaluation* common to both.
#:
#: **Both members are ``@final``, which makes the union closed rather than merely
#: described.** The phases read the posture off the object they were handed, so a
#: third class claiming one of these postures while behaving as the other would
#: admit records to the channel ADR-0199 §3 withholds them from. ``@final`` is what
#: stops one being written: `mypy` refuses the subclass at the point it is declared,
#: over `src/` and `tests/` alike. A genuine third posture is a new *audience*, which
#: ADR-0199 §1 puts behind its own decision.
type TurnSupply = UnboundedAudienceSupply | BoundedAudienceSupply


def admitted_to_understanding[R: SuppliedRecord](
    supply: TurnSupply, records: Sequence[R]
) -> tuple[R, ...]:
    """The stored records of the understanding stage's two windows this audience admits.

    ADR-0276 §4's one further site of ADR-0217 §2's predicate, superseding that
    clause's *no new site* half and nothing else: the same :func:`_speakable`, over
    one further sequence of records, with no second predicate, no seam, no store
    call and no second pass. It is invoked over the records alone.

    **On a channel of unbounded audience it withholds every record the predicate
    does not place**, an ``OWNER``-placed conversation tail record included, and the
    withholding is **silent**: it fires no deflection, on ADR-0217 §2's own
    composition with ADR-0210 §1 — a
    record held "only because it stands in the conversation's own recent turns is
    withheld and fires nothing". The windows are not the turn's supply, so nothing
    here moves what capture stamps.

    **On a channel of bounded audience it withholds nothing**, which is ADR-0204
    §4's posture: the posture is read off the object, so the evaluation is made on
    every pass and only the subtraction varies. A withheld record reaches no
    rendering, no label, no referent and no version, because the stage renders only
    what this returns.

    Args:
        supply: The pass's audience posture, minted by the operation that declares
            the audience.
        records: The stored records of one window, in window order.

    Returns:
        The admitted records, in the order they had.
    """
    if isinstance(supply, BoundedAudienceSupply):
        return tuple(records)
    sources = supply.speakable_attested_sources
    return tuple(
        record for record in records if _speakable(record, speakable_attested_sources=sources)
    )


def admits_owner_placed(supply: TurnSupply) -> bool:
    """Whether a record placed for the owner alone may be shown to this audience.

    ADR-0303 §3:9's test for a note, whoever wrote it: it is shown "only where a
    record placed for the owner alone may be shown to that reader". That is
    :func:`admitted_to_understanding`'s own answer for an ``OWNER``-placed record,
    read off the posture rather than off a record built to ask it: on a channel of
    bounded audience the predicate withholds nothing, and on one of unbounded
    audience :func:`_speakable` withholds every record whose reach is not
    ``ANYONE``.

    Args:
        supply: The reader's audience posture.

    Returns:
        ``True`` on a channel of bounded audience, ``False`` on one of unbounded.
    """
    return isinstance(supply, BoundedAudienceSupply)


def _speakable(record: SuppliedRecord, *, speakable_attested_sources: frozenset[str]) -> bool:
    """Whether ADR-0199 §3 places this record as speakable on an unbounded channel.

    Three field reads and no content, in the order §3 states them.

    ``about_person`` first, because it is the household clause and it decides on its
    own: ADR-0100 documents the field as "whom this belief is about, when that is
    someone other than the owner", with ``None`` read as the owner's and the owner
    never named. The person a belief is about is, in a household, exactly the person
    most likely to be in the room when it would be read aloud.

    Then the source. The three §3 places carry the owner's own beliefs — their word,
    what this system observed, what it worked out — and are what makes milestone
    19's exit test answerable at all. An ``ATTESTED`` record is placed only where its
    ``reported_by`` names a configured calendar source, which is the join ADR-0097 §1
    already keys a grant on.

    Anything else — a source no ADR has placed, an attested record from a reader
    ADR-0199 §3 does not name, an attested record with no attestation at all — is
    unplaced and therefore withheld.

    **And a fourth read, before any class placement is reached**: the record's own
    ``placement`` (ADR-0217 §1, §2, widening ADR-0204 §3's mark). A record whose
    reach does not admit this channel's audience is withheld however ADR-0199 §3's
    third clause would place its class. That is ADR-0217 §2's read rule — a record
    is emitted only if **every person who can perceive the channel's emission is a
    member of the record's placement** — reduced to today's two audiences: what an
    unbounded channel emits "reaches whoever is within range of the device with no
    act of theirs" (ADR-0199 §1), so only reach ``ANYONE`` admits them.

    **Two senses of "placement", and they are never read for each other** (ADR-0217
    §1's vocabulary clause). ADR-0199 §3 *places a class* as speakable **on a
    channel**; the field read here *places a record* **for a set of people**. This
    predicate is the conjunction of the two, and the field read is a **conjunct
    beside** §3 rather than a replacement for it: the three reads below compute §3's
    placements exactly as they always did, no class becomes speakable, and nothing
    here can add a record to a channel — only remove one. That is what keeps the
    fail-closed property of §3's fourth clause on the day the field landed, and what
    makes ADR-0217 §6's default true: a record carrying the default placement is
    placed exactly as §3 places its class.

    Args:
        record: The record being placed.
        speakable_attested_sources: The attested identities §3 places.

    Returns:
        Whether it may reach any stage of a turn on this channel (ADR-0203 §1).
    """
    if record.about_person is not None:
        return False
    if record.placement.reach is not PlacementReach.ANYONE:
        return False
    # Read through ADR-0328 §12: a source names its band, and an attestation is the
    # source details the record's band rests on.
    band = record_band(record)
    if band in _PLACED_BANDS:
        return True
    attestation = record_attestation(record)
    if band is not BeliefBand.ATTESTED or attestation is None:
        return False
    return attestation.reported_by in speakable_attested_sources


def speakable_sources() -> frozenset[MemorySource]:
    """The provenance sources ADR-0199 §3 places, for a test to pin.

    Returns:
        The placed sources.
    """
    return _PLACED_SOURCES


# --- a notification's placement on a channel of unbounded audience -----------
# ADR-0206 §3, which is the ADR ADR-0199 §3's fourth clause names — "an ADR
# admitting a delivery channel of unbounded audience places what it places on the
# whole of §2's recorded origin for a notification". The placement lives here
# beside §3's other two because it is the same ruling on a third kind of subject,
# and a reader auditing what this hub will say aloud reads one module.


#: The one triple ADR-0206 §3 places as speakable: a candidate's ``producer``, its
#: ``notification_class`` and its ``sensitivity``, in that order.
#:
#: **The producer and the class are named rather than copied**, so this set and the
#: producer it places cannot drift apart — ADR-0206 §3's argument is that the
#: placement "is exactly the set ``orchestration/upcoming.py`` produces: three
#: constants, none of them derived from an entry's title, location or duration".
#: ``tests/orchestration/test_spoken_disclosure.py`` pins the literal strings, so a
#: lane that renamed either constant fails a test rather than silently moving what
#: this hub speaks aloud.
#:
#: **The tier is stated and it is ``PERSONAL``**, which reads backwards against
#: ADR-0199 §3's own worked example of a producer whose tier varies with content.
#: ``calendar-upcoming`` is not such a producer: its sensitivity is a module
#: constant, identical on every candidate, so there is no narrower sibling whose
#: placement could be borrowed — and a candidate from this producer at any other
#: tier did not come from the producer as built and is withheld, which is the
#: fail-closed answer rather than an inversion of the example.
_PLACED_NOTIFICATION: Final[tuple[str, str, DataTier]] = (
    PRODUCER,
    NOTIFICATION_CLASS,
    DataTier.PERSONAL,
)


def notification_is_speakable(candidate: NotificationCandidate) -> bool:
    """Whether ADR-0206 §3 places this candidate as speakable into a room.

    **Decided from three recorded fields and from nothing else** (ADR-0206 §3,
    ADR-0199 §2). Not from ``summary``, ``detail``, ``references`` or
    ``confidence``; not by keyword, not by pattern, not by a classifier, and not by
    asking a model. A candidate whose ``summary`` names a subject no ADR has placed
    still renders where its triple is placed, and one whose ``summary`` is
    innocuous is still withheld where its triple is not — which is the whole point
    of keying on origin rather than on content.

    **Every other triple is withheld** (§3's second clause): the same producer and
    the same class at any other ``sensitivity``, every class of a producer ADR-0206
    does not name, and every producer that does not exist yet. Nothing here reads
    the placement as reaching a tier, a class or a producer it did not name, and no
    lane widens it by resemblance — an equality against one tuple is what makes
    that structural rather than remembered.

    **No placement names** :attr:`~ai_assistant.core.types.DataTier.SECRET`, which
    ADR-0199 §3's fifth clause forbids and which ADR-0130 §2 already refuses at
    validation, so no candidate carrying one reaches this path in any case.

    **A candidate whose producer recorded no origin has no class and is withheld**
    (ADR-0199 §2's third clause). No route reaches this function without those three
    fields, because
    :class:`~ai_assistant.core.types.NotificationCandidate` requires all three; the
    clause is honoured here so that a later producer cannot be admitted by a
    default.

    Args:
        candidate: The candidate a poll selected.

    Returns:
        Whether it may be spoken into a room.
    """
    return (
        candidate.producer,
        candidate.notification_class,
        candidate.sensitivity,
    ) == _PLACED_NOTIFICATION


def speakable_notification_triple() -> tuple[str, str, DataTier]:
    """The one triple ADR-0206 §3 places as speakable, for a test to pin.

    Exposed for the same reason :func:`speakable_sources` is: a lane that widened
    the placement, or that renamed the producer constant this set is built from,
    fails a test naming ADR-0206 §3 rather than quietly changing what this hub says
    out loud.

    Returns:
        The producer, the notification class and the sensitivity.
    """
    return _PLACED_NOTIFICATION
