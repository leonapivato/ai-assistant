"""Per-band context assembly: ADR-0072 §5's precedence, built on ADR-0113's read.

ADR-0072 §5 rules that band precedence is applied **by the consumer assembling
context**, and refuses the cheap alternative by name: "A band-neutral top-k
followed by a post-hoc partition does not implement precedence: a flood of
low-confidence inferences can displace an assertion *below the cut*, where no
amount of downstream ordering recovers it. The consumer therefore reads per band
and composes, rather than reading once and sorting."

This module is that consumer. It was unbuildable until ADR-0113 put a band filter
on ``MemoryStore.search`` — issue #790, which ADR-0112 §5 filed after finding that
"the two reads on the contract today are complementary and neither serves
assembly: ``search`` ranks by relevance and is band-blind; ``list_beliefs`` is
band-scoped and ranks nothing".

**What lives here and what deliberately does not.** ADR-0113 §6 leaves the budget,
the number of calls and the assembly order to this lane and rules nothing about
them; what it *does* rule, and what this module owes, is §5's cross-call
obligation — deduplication by record id, keeping the higher-precedence copy. That
obligation is invisible to every store conformance case, because it is a property
of the composition rather than of any one call (ADR-0113 §7).

**ADR-0187 §4 took one aspect of the budget back**, seventeen days after this lane
took it under §6's leave. Strict precedence over one budget let a higher band's
supply exhaust it before a lower band was read at all, which is the displacement
ADR-0098 §10 addressed to #663's revisit and ADR-0183 §7 strengthened: `ATTESTED`
is the band an outsider writes into and "the quantity is theirs to choose", so an
unbounded supply reduced the system's own inferences' share of a turn to zero.
§4 rules the floor that answers it — a band is *ordered* by precedence and is not
*excluded* by it — and §4d routes the implementation here, with no `core` change
and no new `MemoryStore` member. :func:`assemble_by_band` carries it.

The store keeps none of this: it does not know which band the caller will place
first, what budget each gets, or whether a band is being read at all. That is
ADR-0072 §5's placement of precedence in the consumer, held exactly, and ADR-0187
§4's last clause restates it — the floor "grants ``MemoryStore.search`` no
weighting authority over any quantity" and is a rule about the consumer's budget
alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import BeliefBand, band_of

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import MemoryStore
    from ai_assistant.core.types import MemoryKind, MemoryRecord

#: ADR-0072 §5's precedence, highest first: "The assembler fills its budget
#: ``ASSERTED`` first, then ``ATTESTED``, then ``DERIVED``." ADR-0112 §4
#: reaffirmed it unchanged, and ADR-0113 §6 affirms it as ruled. It is a
#: module-level constant rather than an argument because it is *ratified* — a
#: caller that could reorder it could reorder precedence, which is the one thing
#: ADR-0072 §5 exists to place outside a caller's reach.
BAND_PRECEDENCE: tuple[BeliefBand, ...] = (
    BeliefBand.ASSERTED,
    BeliefBand.ATTESTED,
    BeliefBand.DERIVED,
)

#: ADR-0187 §4's floor: **one** slot, held for a band whose own read returned a
#: record the cross-call deduplication did not remove.
#:
#: **This number may not be raised here.** §4's no-larger-share clause is explicit
#: that "a proportional split, a per-band quota, a cap on any band's take, or any
#: other reservation larger than the one above is a bet on a frequency and waits
#: for the measurement ADR-0112 §7's first clause gates and #789 owns. A lane may
#: not adopt one on the strength of this section." One is not a bet: it is the only
#: reservation derivable without a measured frequency, because it is the boundary
#: between a band being represented in the turn and being absent from it, and §4's
#: case — that a band whose read returned records should not be absent — is true at
#: every frequency. Moving it to two would need a supersession of §4, not an edit
#: here.
_FLOOR_PER_BAND: Final = 1


async def assemble_by_band(
    store: MemoryStore,
    query: str,
    *,
    limit: int,
    kinds: Sequence[MemoryKind] | None = None,
    on_page: Callable[[int], None] | None = None,
) -> list[MemoryRecord]:
    """Fill one budget of ``limit`` records band by band, highest precedence first.

    One band-scoped :meth:`~ai_assistant.core.protocols.MemoryStore.search` per
    band in :data:`BAND_PRECEDENCE`, composed in that order, with ADR-0187 §4's
    floor held for every band whose own read returned something.

    **The budget policy, which ADR-0113 §6 leaves to this lane.** There is one
    budget, not a share per band. So a band that comes back short donates its
    remainder to the next one — the question §6 names as real and open — and the
    answer taken here is the one ADR-0072 §5's own sentence implies, since "fills
    its budget ``ASSERTED`` first, then ``ATTESTED``, then ``DERIVED``" describes
    one budget being filled in order rather than three budgets being filled in
    parallel. It also degrades in the right direction: on a store holding only
    inferences, this returns ``limit`` inferences rather than a third of ``limit``,
    so precedence costs nothing when there is nothing to prefer. ADR-0187's
    Consequences affirm that shape and add exactly one constraint to it.

    **ADR-0187 §4's floor, which is that constraint.** Where ``limit`` admits at
    least as many records as there are bands, no band's read is skipped or bounded
    to zero because a higher band's supply exhausted the budget, and a band whose
    own read returns a record the deduplication below does not remove holds **at
    least one** of them in the result. Precedence governs every other slot. Below
    that threshold the floor cannot be satisfied for every band at once, §4 rules
    nothing for the case and its no-larger-share clause forbids inventing a partial
    share, so the pre-ADR behaviour stands there unchanged: strict precedence,
    stopping once the budget is full.

    What the floor buys is small and §4 says so: it stops an outsider's supply
    making the assistant's own inferences *absent* from a turn (ADR-0098 §10,
    ADR-0183 §7), and it does not stop them making them few. What it costs is at
    most one slot per band below the one that would otherwise have filled the
    budget — two of thirty at today's ``RETRIEVAL_LIMIT`` — and only where those
    bands' reads return anything.

    **The shape, which §4d leaves to this lane: reserve first, and return the
    unused reserve upward.** Each band is asked for the most it could ever be
    allocated — the budget less what the bands above it are *guaranteed*, which is
    what they would hold if every band below them claimed its floor. The floors
    below are then withheld from what it is allowed to keep, so the reserve exists
    before the lower band has been read. A second pass allocates over the pages in
    hand: a band that returned nothing reserves nothing, and the slot held for it
    goes back to the highest-precedence band with a record left over. No slot is
    left empty in order to hold a reservation open (§4's second clause), and the
    number of reads stays one per band — ADR-0113 §6's leave over the number of
    calls is what §4d says covers either shape.

    **This is not the over-request §4d forecloses.** What is foreclosed is "a floor
    obtained by over-requesting against an estimate of how many records to expect
    from each band", the headroom bet ADR-0113 §8 declines without #789. No
    estimate is made here and no request exceeds the budget: a band asks for a
    quantity it could lawfully hold in full, and every record it returns beyond its
    allocation is one this composition may still commit in the same pass, to that
    same band, if a lower band's reserve goes unclaimed.

    **Where a reservation is taken from** (§4's second clause). It comes from the
    lowest-precedence band holding more than its own floor, and within that band
    from its least relevant record. That falls out of the allocation rather than
    being a separate step: giving each band in turn everything the budget allows
    after the floors below it means the last band with anything to spare is the one
    that gives, and a band's page arrives ranked, so the record it loses is the one
    the store ranked last.

    **The floor is over what each band's read returned, and over nothing else**
    (§4's third clause). ADR-0113 §5's no-snapshot residue is retained whole: a
    record a concurrent fold moves between bands may be missed exactly as before, a
    band may be unrepresented because its read raced a writer, and nothing here
    re-reads, retries or otherwise assumes a cross-call consistency the
    ``MemoryStore`` contract does not offer. A band whose only returned record was
    deduplicated away has nothing left to hold its floor with, and obliges no
    further read.

    **A consequence stated rather than discovered** (ADR-0187 §5). The floor makes a
    turn's ``planned_with_external_content`` read ``True`` *more* often, not less:
    where a full ``ASSERTED`` band would previously have exhausted the budget and
    the ``ATTESTED`` read would never have been issued, an attested record now
    reaches the selection and ADR-0181 §2's disjunction is then true of it. That is
    the fact reporting the selection more faithfully rather than a regression, and
    the disclosure noise it adds to is #1508's, which §5 rules is not this lane's.

    **Reading in precedence order is a choice with a named consequence**
    (ADR-0113 §5). A ``REINFORCE`` fold can move a record between bands at a stable
    id — ``add`` is an upsert on the caller's id and the fold takes the incoming
    provenance's source — and every move the writer permits is *up* the precedence
    order, because ``MemoryIngestor._refuse_unsafe_fold`` refuses any fold onto a
    ``USER_ASSERTED`` target and the corroboration arm keeps the target's source.
    Reading high band first, an upward move therefore lands the record in a band
    already read, so it is **missed**: absent from the later call because it is no
    longer of that band, and absent from the earlier one because it was not yet
    promoted. Reading in any other order the same move returns it **twice**.

    A miss is the better residue to buy. A duplicate spends the budget twice on one
    belief and presents it under two bands, which ADR-0072 §6 makes a presentation
    fault; a miss costs one record from a prompt that is already a lossy summary of
    the store, and the ``None`` in this window is one turn wide. The deduplication
    below is still owed and still applied, because the order argument bounds which
    residue is *likely*, not which is possible — nothing here is a transaction, and
    a concurrent writer is not obliged to respect the fold rules.

    **A deduplicated copy costs the band that returned it a slot, and that is
    accepted.** No call asks for more than the budget could give it, so if a lower
    band's answer contains a record already held, the composition comes back one
    short of what that band could have supplied. The alternative is to over-request
    against an estimate of how many duplicates to expect, which is a headroom
    decision of
    exactly the kind ADR-0113 §8 declines to make without #789's measurement. It is
    also consistent with what the read itself promises: ADR-0113 §2 refuses a
    full-page guarantee outright — "a call may return fewer than ``limit`` records
    while eligible ones exist" — so a composition that inherits that property is
    inheriting the contract rather than weakening it. The window is one turn wide
    and the case needs a fold landing between two of this function's calls.

    Args:
        store: The store to read. Read three times, with no consistency of any kind
            promised across the calls (ADR-0113 §5): there is no multi-band
            snapshot and this function does not assume one.
        query: The relevance query, passed unchanged to every band's call.
        limit: The total number of records to return across all bands.
        kinds: Restrict every call to these memory kinds, as
            :meth:`MemoryStore.search` takes them. Passed through rather than
            decided here — the caller owns which kinds belong in its prompt.
            Observed **once**, before the first read, so every band is filtered on
            the same kinds even if the caller mutates the sequence it passed.
        on_page: Called with the number of records each band's read returned,
            immediately after that read and before the next one, or ``None`` to
            observe nothing. It is how a caller that catches this function's failure
            can tell whether an *earlier* band had already returned records:
            ADR-0226 §9 states its partial-servicing field over **reads** rather
            than over asks, and this composition is several reads behind one call,
            so a caller could not otherwise distinguish "the first band raised" from
            "the second band raised after the first returned". It observes and never
            decides — nothing here reads what it returns, and it is called before
            the band filter and the deduplication below, because the fact it carries
            is about the *read* and not about what the composition kept.

    Returns:
        Up to ``limit`` records, ordered by band precedence and, within a band, by
        the relevance the store ranked them on. Each id appears at most once, under
        the highest-precedence band that returned it. Where ``limit`` is at least
        ``len(BAND_PRECEDENCE)``, every band whose read returned a record not
        deduplicated away is represented by at least one of them (ADR-0187 §4).

    Raises:
        MemoryStoreError: If any band's read fails. Deliberately not caught here:
            the caller owns what a degraded retrieval means for its turn, and
            partial composition is a policy this function does not invent (#805).
    """
    # Materialised on the first executed line, before any await, and only the copy
    # is read thereafter — ADR-0065 §3's discharge, owed here for a reason the store
    # methods' own version does not cover. Each ``search`` already snapshots
    # ``kinds`` per call (#436), so every individual call is coherent; what is not,
    # without this, is the *composition*. This function reads the caller's sequence
    # three times with two awaits in between, so a caller mutating it mid-flight
    # gets a result whose asserted band was filtered on one kind set and whose
    # derived band was filtered on another — one answer describing two versions of
    # one input, which is the incoherence ADR-0065 exists to prevent, reappearing
    # one layer above the seam that already closed it.
    wanted_kinds = None if kinds is None else tuple(kinds)
    if limit <= 0:
        return []

    # ADR-0187 §4's own condition — "where the budget admits at least as many
    # records as there are bands in ``BAND_PRECEDENCE``". Below it the floor is
    # unsatisfiable for every band at once, §4 rules nothing, and §4's
    # no-larger-share clause forbids inventing a partial one, so strict precedence
    # over one budget stands there exactly as it did before this ADR.
    floor_applies = limit >= len(BAND_PRECEDENCE)

    # Phase one: one read per band, in precedence order, deduplicated across the
    # calls. Nothing is committed to the result here — the allocation cannot be
    # decided until every band's page is in hand, because whether a band reserves
    # anything is a fact about what its *own* read returned (§4's third clause).
    pages: list[list[MemoryRecord]] = []
    seen: set[str] = set()
    # What the bands above this one are guaranteed: what they would hold if every
    # band below them claimed its floor. The budget less that is the most this band
    # could ever be allocated, so it is exactly what this band asks for — never an
    # estimate of what it will return, which is the shape §4d forecloses.
    claimed_above = 0
    for index, band in enumerate(BAND_PRECEDENCE):
        request = limit - claimed_above
        if request <= 0:
            # Unreachable while ``floor_applies``: each band is allowed to claim at
            # most ``request`` less the floors below it, so ``claimed_above`` never
            # exceeds ``limit - (len(BAND_PRECEDENCE) - index)`` and ``request`` is
            # never below the number of bands still to read. This is the sub-floor
            # path, where a full budget still ends the composition.
            break
        found = await store.search(query, limit=request, kinds=wanted_kinds, bands=[band])
        if on_page is not None:
            on_page(len(found.records))
        # ``found.capped`` is unwrapped and nothing more: ADR-0128 §6 leaves what a
        # consumer does with it to that consumer's own lane, and this assembler
        # takes no policy from it here. The band-scoped read it composes is already
        # forbidden from being read as evidence that a band holds nothing more
        # (ADR-0113 §5), which is a different rule about a different race and is
        # unaffected either way.
        page: list[MemoryRecord] = []
        for record in found.records:
            if record.id in seen:
                # ADR-0113 §5's cross-call rule. Arriving here means a fold moved
                # this record between two of these calls; the copy already held is
                # from an earlier band, which is a higher-precedence one, so it is
                # the copy that survives and it is charged to that band's budget
                # once. Resolving by arrival order instead would decide precedence
                # by loop order — the one thing ADR-0072 §5 is about.
                continue
            # A store may not return an out-of-band record (ADR-0113 §5's per-call
            # partition), so this is a conformance check rather than a filter, and
            # it is cheap enough to keep: an implementation that padded a short page
            # from another band would otherwise place an inference in the slot
            # precedence reserved for an assertion, undetectably. A record dropped
            # here was not returned by this band's read in any sense §4's floor can
            # use, so it reserves nothing.
            if band_of(record.provenance.source) is not band:
                continue
            seen.add(record.id)
            page.append(record)
        pages.append(page)
        floors_below = _FLOOR_PER_BAND * (len(BAND_PRECEDENCE) - 1 - index) if floor_applies else 0
        claimed_above += min(len(page), request - floors_below)

    # Phase two: allocate the budget over the pages in hand. Each band takes
    # everything left after the floors owed to the bands *below* it that actually
    # returned something — so precedence governs every unreserved slot (§4's first
    # clause), a band that returned nothing reserves nothing and its held slot
    # returns to the highest-precedence band with a record left over (§4's second
    # clause), and no slot is left empty to hold a reservation open.
    composed: list[MemoryRecord] = []
    used = 0
    for index, page in enumerate(pages):
        reserved_below = (
            sum(_FLOOR_PER_BAND for lower in pages[index + 1 :] if lower) if floor_applies else 0
        )
        take = min(len(page), max(0, limit - used - reserved_below))
        composed.extend(page[:take])
        used += take
    return composed
