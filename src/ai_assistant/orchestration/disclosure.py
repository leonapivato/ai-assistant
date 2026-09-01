"""ADR-0199's disclosure ruling, applied **at supply** (ADR-0200 §7, ADR-0203 §1).

ADR-0199 decides what may be said on a channel of unbounded audience. This module
decides nothing it decides; what it holds is the one place its rules are applied
on the spoken turn — in ``orchestration``, **inside the turn**, and, since
ADR-0203 §1, **before the turn plans** rather than before the composing stage sees
anything. There is exactly one site: the subtraction is applied between retrieval
and planning and nowhere else, so no stage of such a turn — planner, composing
stage, or anything rendering what either produced — is ever handed a withheld
record.

**At supply, and never as a filter over composed prose** (ADR-0199 §5). Content
withheld from the channel does not reach the composing stage among the inputs the
reply is composed from. Nothing here reads a composed answer, and nothing
anywhere removes, masks, blanks or rewrites part of one: a filter over prose is
content inspection, which ADR-0199 §2 forbids as a decision procedure and which
"fails silently on the first sentence phrased in a way the filter did not
anticipate", and a composed answer with a hole cut in it is an utterance a
listener "cannot distinguish from a complete one".

**The class is decided from recorded origin, never by inspecting the words**
(ADR-0199 §2). For a record that is :attr:`~ai_assistant.core.types.MemoryBase.about_person`,
:attr:`~ai_assistant.core.types.Provenance.source` and — where the band is
``ATTESTED`` — :attr:`~ai_assistant.core.types.Attestation.reported_by`, and since
ADR-0204 §3 a **fourth** recorded field, which ADR-0217 §1 moved onto the envelope
and widened: :attr:`~ai_assistant.core.types.MemoryBase.placement`. For a
context facet it is the facet's own **kind**. No content is read: not
``MemoryBase.content``, not a facet's rendered text, not a keyword, not a
pattern, not a classifier, and not a model asked what a passage is about.

**The fourth read is a second reason to withhold, not a fifth class placement**
(ADR-0204 §3, §11; ADR-0217 §2). ADR-0199 §3's placements are computed exactly as
they were — no class becomes speakable or unspeakable here — and a record whose
own placement does not admit this channel's audience is withheld whatever §3's
third clause would otherwise place it as. That closes the two paths #1703 and
#1708 record: a withholding turn's own question, and a bounded channel's turn
laundering a model rationale through capture into a record §3 places speakable.
Since ADR-0217 §1 the record's reach is narrowed by the owner's own act and by a
model's proposal as well as by that derivation, and this read is unmoved by which
of the three wrote it: it is a **conjunct**, so it can only subtract.

**The evaluation is also made on a channel whose audience is bounded, where
nothing is subtracted** (ADR-0204 §2, §4). :class:`BoundedAudienceSupply` runs the
same predicate over that turn's supply, discards the narrowed supply, and keeps
only the boolean — so the turn plans over everything it retrieved, exactly as
ADR-0203 §1's last clause requires, and its capture still records that such
content stood in its warrant. One predicate, in one module, two uses.

**And since ADR-0210 §1 the two uses differ in the set they range over, which is
the only thing that separates them.** ``_speakable`` is still the whole predicate
and is still applied to every record alike; what varies is which records may set
the boolean. On a channel of **unbounded** audience the boolean is
ADR-0204 §2's disjunction taken over the members of the supply that a relevance
read with this turn's own goal statement returned — ADR-0074 §5's second and
third groups, named by the read rather than by the group — together with the
turn's context facets. On a channel of **bounded** audience it is taken over the
whole supply, first group included, exactly as ADR-0204 §2 and §4 state it. The
**subtraction is not narrowed by any of that**: a record ADR-0199 §3 or ADR-0204
§3 withholds is removed wherever it stood, so what a member of the conversation's
own recent turns loses is the power to set a boolean and nothing else.

**Why the tail is taken off the evaluation rather than out of the supply**
(ADR-0210 §1). ADR-0074 §5 put the conversation's recent turns in the supply
because they are *the conversation*, not because they answered the question — its
own words call a user changing the subject mid-conversation "ordinary" and calling
the tail "best first" "a strain". A boolean whose meaning is "something bearing on
this turn was held back" cannot be set by a group whose membership does not depend
on the turn; and while it could, one deflection stamped its episode, the next
turn's tail held that episode, and the withholding was permanent on every store
(#1775).

**The read set is a membership and never a magnitude** (ADR-0210 §6). Nothing here
reads a retrieval score, a rank, a similarity threshold or any other quantity the
ranking produced, and nothing here reads content in order to decide whether a
withholding bore on the question. The test is that a relevance read returned the
record, and the ADR refuses the alternatives in terms.

**The withholding subtracts and adds nothing** (ADR-0199 §5, ADR-0203 §1). What
this module builds is the *supply the whole turn runs over*, so the
:class:`~ai_assistant.core.types.TurnResult` such a turn produces is produced over
the subtracted supply and there is no wider turn anywhere in the process. ADR-0203
§1 replaces ADR-0199 §5's "the ``TurnResult`` the turn produced is unchanged" for
exactly this case — an operation whose output channel's audience is unbounded —
and that sentence still governs every operation whose audience is bounded, where
nothing here is applied at all.

**And the half of that clause ADR-0203 §2 keeps is this module's own bound.** No
``ContextProvider``, no ``MemoryStore``, no second context assembly, no second
retrieval and no store query of any kind: this is a filter over what the turn
already assembled and retrieved, and nothing is refetched, widened, re-run or
backfilled to replace what it removed (ADR-0170 §2). It removes members and
reorders nothing, so ADR-0074 §5's three groups — the conversation's recent turns,
then the relevance-retrieved beliefs, then ADR-0158's episodic supplement — arrive
in that order still.

**An unplaced class is withheld, and that is enforced structurally rather than
remembered.** :data:`_PLACED_FACET_KINDS` is matched by **exact type**, so a third
facet landing on :class:`~ai_assistant.core.types.CurrentContext` is withheld from
an unbounded channel on the day it lands and stays withheld until the ADR
admitting it places it (ADR-0199 §3's fourth clause). A subclass of a placed facet
is a different class and is likewise unplaced — the fail-closed direction, and the
only one this module takes.

**Two things this module deliberately does not do.** It is not given the turn's
goal, and ADR-0203 §4's third clause is the reason: the goal statement is the
turn's *subject* rather than a member of the supply §1 subtracts from, and a stage
that was not given the question has no question to compose an answer to (ADR-0199
§5's third clause). The plan and the step account sit downstream of this filter and
are likewise untouched — they are this system's own product from the user's own
utterance, rendered by ``composing`` from four closed vocabularies this project
owns, and they carry no recorded external origin for ADR-0199 §2 to decide a class
from. And it enforces no Tier 0 floor, because there
is nothing here to enforce it over — ADR-0199 §3's first clause forbids a Tier 0
value in any reply on any channel, and ADR-0170's composing stage is supplied
nothing that holds one (ADR-0004 §3 keeps Tier 0 in the keyring).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    BeliefBand,
    CalendarFacet,
    ContextFacet,
    DataTier,
    EmailFacet,
    MemorySource,
    PlacementReach,
    band_of,
)
from ai_assistant.orchestration.upcoming import NOTIFICATION_CLASS, PRODUCER

if TYPE_CHECKING:
    from ai_assistant.core.types import CurrentContext, MemoryRecord, NotificationCandidate

__all__ = [
    "BoundedAudienceSupply",
    "TurnSupply",
    "UnboundedAudienceSupply",
    "notification_is_speakable",
    "placed_facet_kinds",
    "speakable_notification_triple",
    "speakable_sources",
    "supply_for_unbounded_audience",
]

#: The provenance sources ADR-0199 §3 places as speakable on a channel of
#: unbounded audience, where ``about_person`` is not stated. The fourth member of
#: :class:`~ai_assistant.core.types.MemorySource` — ``EXTERNAL`` — is deliberately
#: absent: it is the ``ATTESTED`` band, which §3 places only for the calendar
#: source, and a member this set does not name is withheld.
_PLACED_SOURCES: Final[frozenset[MemorySource]] = frozenset(
    {MemorySource.USER_ASSERTED, MemorySource.OBSERVED, MemorySource.INFERRED}
)

#: The context facet kinds ADR-0199 §3 places as speakable, each because of what it
#: actually carries: a ``CalendarFacet`` is three scalars and an instant and "carries
#: no entry text — no summary, location, description, organiser, attendee or
#: identifier"; an ``EmailFacet`` is two scalars with "no span of any message". So
#: #665's worked example — "calendar yes, email no" — has no purchase on the facets,
#: because neither discloses anything an utterance could leak.
#:
#: **Matched by exact type and not by ``isinstance``.** A subclass of a placed facet
#: is a different class, no ratified ADR has placed it, and §3's second clause
#: withholds it. That is the fail-closed direction, and it is what makes a facet
#: added without a placement a silent withholding rather than a silent disclosure.
_PLACED_FACET_KINDS: Final[frozenset[type[ContextFacet]]] = frozenset({CalendarFacet, EmailFacet})


def supply_for_unbounded_audience(
    context: CurrentContext,
    memories: tuple[MemoryRecord, ...],
    *,
    speakable_attested_sources: frozenset[str],
    retrieved_ids: frozenset[str],
) -> tuple[CurrentContext, tuple[MemoryRecord, ...], bool]:
    """Return the supply the turn may run over, and whether anything was held back.

    **The whole turn, not the composing stage alone** (ADR-0203 §1). This is applied
    between retrieval and planning, so what it returns is what the planner is given,
    what the composing stage is given, and what the ``TurnResult`` carries. It reads
    nothing but the four recorded-origin fields of a record, the exact type of a
    facet and a record's ``id``, and it makes no store call of any kind.

    **Two sets, and they are deliberately different** (ADR-0210 §1). The
    subtraction runs over the whole of ``memories``; the boolean runs over
    ``retrieved_ids``. A record ADR-0199 §3 or ADR-0204 §3 withholds is removed
    wherever it stood in ADR-0074 §5's three groups, so this function gives no
    stage a record it did not have before — what a member of the conversation's
    own recent turns loses is only the power to set the third return value.

    Args:
        context: The situational context the turn assembled. Never modified; where a
            facet is withheld a narrowed copy is returned instead.
        memories: What the turn retrieved, in ADR-0074 §5's three groups and that
            order. Never modified, and the order of what survives is the order it
            had (ADR-0203 §2).
        speakable_attested_sources: The ``Attestation.reported_by`` identities
            ADR-0199 §3 places as speakable on this channel — the calendar source
            ADR-0093 §7 configures, and nothing else. Supplied by the composition
            root, which is the only layer that knows which reader was built and
            what identity it carries (ADR-0190 §7's minted discriminator included).
            Empty where no calendar is configured, which withholds every attested
            record rather than guessing at a name.
        retrieved_ids: The ids of the records a relevance read taken with this
            turn's own goal statement returned — the belief composition's, and the
            episodic supplement's read **before** ADR-0158 §4's deduplication
            (ADR-0210 §1, :data:`~ai_assistant.orchestration.loop.SupplyFilter`).
            A *membership* and never a score, a rank or a group boundary: a record
            both the conversation tail and the supplement's read carry stands in
            ``memories`` at the tail's position alone, and it is named here because
            that read chose it. An id absent from this set is subtracted exactly as
            a present one is and sets nothing.

    Returns:
        The context and the memories the turn may run over, and whether anything
        **that this turn's relevance reads returned, or any context facet**, was
        withheld from them (ADR-0210 §1). The third value is what the composing
        stage is eventually told: **that** a withholding occurred, and nothing about
        what it was. It is also ADR-0204 §2's disjunction as ADR-0210 §1 narrows it,
        over this one evaluation and with no second pass over the supply — its first
        term because a record of that set or a facet was unplaced, and its second
        because :func:`_speakable` refuses a record whose ``placement`` is already
        narrowed (ADR-0217 §1), so a supply whose *retrieved* groups hold one
        cannot come back as "nothing was withheld". A record withheld from the
        conversation's own recent turns and from nowhere else is subtracted and
        leaves this value ``False``, which is the whole of §1.
    """
    kept: list[MemoryRecord] = []
    withheld = False
    for record in memories:
        if _speakable(record, speakable_attested_sources=speakable_attested_sources):
            kept.append(record)
        elif record.id in retrieved_ids:
            # Subtracted either way (above); this branch only decides whether the
            # removal is one the composing stage and capture are told about.
            withheld = True
    narrowed, context_withheld = _speakable_context(context)
    return narrowed, tuple(kept), withheld or context_withheld


def _withheld_over_whole_supply(
    context: CurrentContext,
    memories: tuple[MemoryRecord, ...],
    *,
    speakable_attested_sources: frozenset[str],
) -> bool:
    """ADR-0204 §2's disjunction over **every** member of a supply, unnarrowed.

    The bounded channel's evaluation, and ADR-0210 §1's last clause is why it has a
    function of its own rather than a flag: "On an operation whose output channel's
    audience is **bounded** the evaluation is exactly ADR-0204 §2's and §4's, over
    the whole supply as assembled and retrieved, first group included, with nothing
    subtracted from that turn." The predicate is
    :func:`_speakable`, identically; only the set differs, and #1708's laundering
    path runs entirely on this side, which is what makes it untouchable here.

    Args:
        context: The situational context the turn assembled. Never modified — the
            narrowed copy :func:`_speakable_context` builds is discarded, because
            nothing is subtracted from a bounded channel's turn.
        memories: What the turn retrieved, in ADR-0074 §5's three groups.
        speakable_attested_sources: The identities ADR-0199 §3 places, as
            :func:`supply_for_unbounded_audience` takes them.

    Returns:
        Whether ADR-0199 §3 would have withheld any record of that supply, or any
        context facet, from a channel of unbounded audience.
    """
    _, context_withheld = _speakable_context(context)
    return context_withheld or any(
        not _speakable(record, speakable_attested_sources=speakable_attested_sources)
        for record in memories
    )


@dataclass(slots=True)
class UnboundedAudienceSupply:
    """One turn's subtraction, and the bare fact that it happened (ADR-0203 §1, §3).

    ADR-0199 §5's third clause obliges the composing stage to be told **that** a
    withholding occurred, so that it can compose an answer stating it. Since
    ADR-0203 §1 the subtraction happens between retrieval and planning — before the
    turn exists, and several stages before that one — so the fact has to survive the
    intervening stages. This object is what carries it: applied by
    :meth:`~ai_assistant.orchestration.loop.LearningLoop.respond` as the filter
    between retrieval and planning, and read afterwards by the composer.

    **One instance per call, minted by the operation that declares its channel
    unbounded**, exactly as ``Engine._run_turn`` mints one capacity handle per turn.
    Two concurrent spoken turns therefore share nothing, and the recorded fact is a
    fact about this turn rather than about the engine.

    **It never un-records.** :attr:`withheld` is latched on rather than assigned, so
    an application that removes nothing cannot clear a withholding an earlier one
    recorded — the fail-closed direction, and the only one this module takes.

    **And since ADR-0210 §1 it records less than it removes.** The subtraction is
    unchanged and runs over the whole supply; :attr:`withheld` is set only where
    what was removed stood in what this turn's relevance reads returned, or was a
    context facet. So a stamped episode of this conversation's own recent turns is
    still taken out of everything the turn runs over — and the composing stage is
    not told, and capture writes ``False``. That is the whole of #1775's answer:
    before it, one withholding stamped the next turn's tail, and the stamp then
    propagated through the episodic record for as long as the conversation ran.

    Attributes:
        speakable_attested_sources: The identities ADR-0199 §3 places, as
            :func:`supply_for_unbounded_audience` takes them.
        withheld: Whether anything a relevance read of this turn returned, or any
            context facet, was held back from this turn's supply (ADR-0210 §1).
    """

    speakable_attested_sources: frozenset[str]
    withheld: bool = False

    def __call__(
        self,
        context: CurrentContext,
        memories: tuple[MemoryRecord, ...],
        retrieved_ids: frozenset[str],
    ) -> tuple[CurrentContext, tuple[MemoryRecord, ...]]:
        """Subtract what ADR-0199 §3 withholds, recording that it happened.

        Args:
            context: The context the turn assembled.
            memories: What the turn retrieved.
            retrieved_ids: The ids this turn's relevance reads returned, which is
                the set :attr:`withheld` is evaluated over (ADR-0210 §1). The
                subtraction below ignores it and runs over the whole supply.

        Returns:
            The context and the memories the turn may run over.
        """
        narrowed, kept, withheld = supply_for_unbounded_audience(
            context,
            memories,
            speakable_attested_sources=self.speakable_attested_sources,
            retrieved_ids=retrieved_ids,
        )
        self.withheld = self.withheld or withheld
        return narrowed, kept


@dataclass(slots=True)
class BoundedAudienceSupply:
    """One turn's evaluation on a channel whose audience is bounded (ADR-0204 §2, §4).

    The twin of :class:`UnboundedAudienceSupply`, and deliberately the *same*
    predicate: it evaluates ADR-0199 §3's withholding over what the turn assembled
    and retrieved, records whether anything would have been held back, and then hands
    the turn back **everything it was given**. What varies by the channel's audience
    is whether the subtraction is applied, and never whether the evaluation is made.

    **Nothing about the turn changes** (ADR-0204 §4). The supply it runs over, the
    plan it produces, the step that plan drives, the ``TurnResult`` it returns, the
    reply composed for it and the plan it persists are all exactly what they were
    before this class existed. What the evaluation buys is one boolean about material
    the turn was already handed, computed from fields it already carries, which its
    capture then records — because #1708's finding is not that the typed answer was
    wrong but that its *capture* becomes an input to a channel whose audience is not
    bounded.

    **Its :attr:`withheld` is read only by capture**, never by a composing stage:
    ADR-0199 §5's third clause obliges the stage to be told that a withholding
    occurred, and on this channel none did. Latched exactly as the unbounded twin's
    is, for the same fail-closed reason.

    **ADR-0210 §1 narrows the twin and leaves this class alone**, which is where the
    two now differ. Its last clause is explicit — on a bounded channel "the
    evaluation is exactly ADR-0204 §2's and §4's, over the whole supply as assembled
    and retrieved, first group included" — so a stamped episode standing only in the
    conversation's recent turns sets this boolean and would not set the twin's.
    That is not an oversight to tidy up later: #1708's laundering path runs entirely
    through this channel's captures, and a narrowing here would reopen it.

    Attributes:
        speakable_attested_sources: The identities ADR-0199 §3 places, as
            :func:`supply_for_unbounded_audience` takes them.
        withheld: Whether ADR-0199 §3 would have held anything back from this turn's
            supply — ADR-0204 §2's disjunction, over a supply nothing was taken from
            and nothing was narrowed out of (:func:`_withheld_over_whole_supply`).
    """

    speakable_attested_sources: frozenset[str]
    withheld: bool = False

    def __call__(
        self,
        context: CurrentContext,
        memories: tuple[MemoryRecord, ...],
        retrieved_ids: frozenset[str],
    ) -> tuple[CurrentContext, tuple[MemoryRecord, ...]]:
        """Evaluate what ADR-0199 §3 would withhold, and subtract none of it.

        Args:
            context: The context the turn assembled.
            memories: What the turn retrieved.
            retrieved_ids: What this turn's relevance reads returned. **Accepted
                and not read** (ADR-0210 §1's last clause): this channel's
                evaluation is ADR-0204 §2's and §4's, over the whole supply as
                assembled and retrieved. The parameter is on the seam because
                :data:`~ai_assistant.orchestration.loop.SupplyFilter` is one seam
                for both postures, and discarding it here is the narrowing being
                declined rather than forgotten.

        Returns:
            Exactly what it was given, unnarrowed and unreordered.
        """
        del retrieved_ids
        withheld = _withheld_over_whole_supply(
            context, memories, speakable_attested_sources=self.speakable_attested_sources
        )
        self.withheld = self.withheld or withheld
        return context, memories


#: The two postures one conversational operation's supply can take, and there are
#: exactly two: ADR-0199 §1 fixes the posture as a function of the output channel's
#: audience alone, and ADR-0204 §2 makes the *evaluation* common to both. A turn is
#: handed one of these between retrieval and planning
#: (:data:`~ai_assistant.orchestration.loop.SupplyFilter`), and its capture reads the
#: recorded fact off the same object afterwards.
type TurnSupply = UnboundedAudienceSupply | BoundedAudienceSupply


def _speakable(record: MemoryRecord, *, speakable_attested_sources: frozenset[str]) -> bool:
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
    provenance = record.provenance
    if provenance.source in _PLACED_SOURCES:
        return True
    attestation = provenance.attestation
    if band_of(provenance.source) is not BeliefBand.ATTESTED or attestation is None:
        return False
    return attestation.reported_by in speakable_attested_sources


def _speakable_context(context: CurrentContext) -> tuple[CurrentContext, bool]:
    """Drop every facet ADR-0199 §3 has not placed, and say whether any was dropped.

    The temporal scalars are this system's own reading of its own clock and are not
    content with a recorded origin, so they are untouched. Every *facet* member is
    tested by exact type against :data:`_PLACED_FACET_KINDS`, which is what makes an
    unplaced facet withheld by construction rather than by anyone remembering to add
    it here.

    Args:
        context: The situational context the turn assembled.

    Returns:
        The context the turn may run over, and whether a facet was withheld.
    """
    dropped: dict[str, None] = {
        name: None
        for name in type(context).model_fields
        if _is_unplaced_facet(getattr(context, name))
    }
    if not dropped:
        return context, False
    return context.model_copy(update=dropped), True


def _is_unplaced_facet(value: object) -> bool:
    """Whether ``value`` is a context facet of a kind no ratified ADR has placed."""
    return isinstance(value, ContextFacet) and type(value) not in _PLACED_FACET_KINDS


def placed_facet_kinds() -> frozenset[type[ContextFacet]]:
    """The facet kinds ADR-0199 §3 places as speakable, for a test to pin.

    Exposed so ``tests/orchestration/test_spoken_disclosure.py`` can assert that the set
    still matches §3's own list, and so a facet added to
    :class:`~ai_assistant.core.types.CurrentContext` without a placement fails a
    test rather than being quietly withheld and never noticed.

    Returns:
        The placed kinds.
    """
    return _PLACED_FACET_KINDS


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
    ADR-0199 §2). Not from ``summary``, ``detail``, ``references``, ``goal_id`` or
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

    Exposed for the same reason :func:`placed_facet_kinds` is: a lane that widened
    the placement, or that renamed the producer constant this set is built from,
    fails a test naming ADR-0206 §3 rather than quietly changing what this hub says
    out loud.

    Returns:
        The producer, the notification class and the sensitivity.
    """
    return _PLACED_NOTIFICATION
