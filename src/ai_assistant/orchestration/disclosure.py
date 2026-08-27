"""ADR-0199's disclosure ruling, applied **at supply** (ADR-0200 §7).

ADR-0199 decides what may be said on a channel of unbounded audience. This module
decides nothing it decides; what it holds is the one place its rules are applied
on the spoken turn — in ``orchestration``, **inside the turn**, before the
composing stage sees anything.

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

**The withholding subtracts and adds nothing** (ADR-0199 §5). The
:class:`~ai_assistant.core.types.TurnResult` the turn produced is unchanged and is
what the outcome carries back; what this module builds is the *supply* the stage
composes from. No ``ContextProvider``, no ``MemoryStore``, no second context
assembly and no second retrieval: the stage's context and memories still reach it
from the turn and from nowhere else (ADR-0170 §2).

**An unplaced class is withheld, and that is enforced structurally rather than
remembered.** :data:`_PLACED_FACET_KINDS` is matched by **exact type**, so a third
facet landing on :class:`~ai_assistant.core.types.CurrentContext` is withheld from
an unbounded channel on the day it lands and stays withheld until the ADR
admitting it places it (ADR-0199 §3's fourth clause). A subclass of a placed facet
is a different class and is likewise unplaced — the fail-closed direction, and the
only one this module takes.

**Two things this module deliberately does not do.** It does not touch the
turn's goal, its plan or its step account: those are this system's own product
from the user's own utterance, rendered by ``composing`` from four closed
vocabularies this project owns, and they carry no recorded external origin for
ADR-0199 §2 to decide a class from. And it enforces no Tier 0 floor, because there
is nothing here to enforce it over — ADR-0199 §3's first clause forbids a Tier 0
value in any reply on any channel, and ADR-0170's composing stage is supplied
nothing that holds one (ADR-0004 §3 keeps Tier 0 in the keyring).
"""

from __future__ import annotations

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
    from ai_assistant.core.types import CurrentContext, MemoryRecord, TurnResult

__all__ = ["placed_facet_kinds", "speakable_sources", "supply_for_unbounded_audience"]

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
    turn: TurnResult, *, speakable_attested_sources: frozenset[str]
) -> tuple[TurnResult, bool]:
    """Return what the composing stage may be given, and whether anything was held back.

    Args:
        turn: What the turn produced. **Not modified** — ADR-0199 §5 keeps it
            exactly as the turn made it, and the outcome carries that one back.
        speakable_attested_sources: The ``Attestation.reported_by`` identities
            ADR-0199 §3 places as speakable on this channel — the calendar source
            ADR-0093 §7 configures, and nothing else. Supplied by the composition
            root, which is the only layer that knows which reader was built and
            what identity it carries (ADR-0190 §7's minted discriminator included).
            Empty where no calendar is configured, which withholds every attested
            record rather than guessing at a name.

    Returns:
        The supply the stage composes from, and whether ADR-0199 §3 withheld
        anything from it. The second value is what the stage is told: **that** a
        withholding occurred, and nothing about what it was.
    """
    kept = tuple(
        record
        for record in turn.memories
        if _speakable(record, speakable_attested_sources=speakable_attested_sources)
    )
    context, context_withheld = _speakable_context(turn.context)
    withheld = context_withheld or len(kept) != len(turn.memories)
    if not withheld:
        return turn, False
    # ``model_copy`` rather than a rebuilt constructor call: every value here is one
    # the turn already validated, and a hand-written constructor would silently drop
    # a member ``TurnResult`` grows later.
    return turn.model_copy(update={"memories": kept, "context": context}), True


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
        Whether it may reach the composing stage on this channel.
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
        The context the stage may be given, and whether a facet was withheld.
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

    Exposed so ``tests/orchestration/test_disclosure.py`` can assert that the set
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
