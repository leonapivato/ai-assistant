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
``ATTESTED`` — :attr:`~ai_assistant.core.types.Attestation.reported_by`. For a
context facet it is the facet's own **kind**. No content is read: not
``MemoryBase.content``, not a facet's rendered text, not a keyword, not a
pattern, not a classifier, and not a model asked what a passage is about.

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
    EmailFacet,
    MemorySource,
    band_of,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import CurrentContext, MemoryRecord

__all__ = [
    "UnboundedAudienceSupply",
    "placed_facet_kinds",
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
) -> tuple[CurrentContext, tuple[MemoryRecord, ...], bool]:
    """Return the supply the turn may run over, and whether anything was held back.

    **The whole turn, not the composing stage alone** (ADR-0203 §1). This is applied
    between retrieval and planning, so what it returns is what the planner is given,
    what the composing stage is given, and what the ``TurnResult`` carries. It reads
    nothing but the three recorded-origin fields of a record and the exact type of a
    facet, and it makes no store call of any kind.

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

    Returns:
        The context and the memories the turn may run over, and whether ADR-0199 §3
        withheld anything from them. The third value is what the composing stage is
        eventually told: **that** a withholding occurred, and nothing about what it
        was.
    """
    kept = tuple(
        record
        for record in memories
        if _speakable(record, speakable_attested_sources=speakable_attested_sources)
    )
    narrowed, context_withheld = _speakable_context(context)
    return narrowed, kept, context_withheld or len(kept) != len(memories)


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

    Attributes:
        speakable_attested_sources: The identities ADR-0199 §3 places, as
            :func:`supply_for_unbounded_audience` takes them.
        withheld: Whether anything was held back from this turn's supply.
    """

    speakable_attested_sources: frozenset[str]
    withheld: bool = False

    def __call__(
        self, context: CurrentContext, memories: tuple[MemoryRecord, ...]
    ) -> tuple[CurrentContext, tuple[MemoryRecord, ...]]:
        """Subtract what ADR-0199 §3 withholds, recording that it happened.

        Args:
            context: The context the turn assembled.
            memories: What the turn retrieved.

        Returns:
            The context and the memories the turn may run over.
        """
        narrowed, kept, withheld = supply_for_unbounded_audience(
            context, memories, speakable_attested_sources=self.speakable_attested_sources
        )
        self.withheld = self.withheld or withheld
        return narrowed, kept


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

    Args:
        record: The record being placed.
        speakable_attested_sources: The attested identities §3 places.

    Returns:
        Whether it may reach any stage of a turn on this channel (ADR-0203 §1).
    """
    if record.about_person is not None:
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
