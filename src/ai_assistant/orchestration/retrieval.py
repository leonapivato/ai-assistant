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

The store keeps none of this: it does not know which band the caller will place
first, what budget each gets, or whether a band is being read at all. That is
ADR-0072 §5's placement of precedence in the consumer, held exactly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.types import BeliefBand, band_of

if TYPE_CHECKING:
    from collections.abc import Sequence

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


async def assemble_by_band(
    store: MemoryStore,
    query: str,
    *,
    limit: int,
    kinds: Sequence[MemoryKind] | None = None,
) -> list[MemoryRecord]:
    """Fill one budget of ``limit`` records band by band, highest precedence first.

    One band-scoped :meth:`~ai_assistant.core.protocols.MemoryStore.search` per
    band in :data:`BAND_PRECEDENCE`, composed in that order, stopping once the
    budget is full.

    **The budget policy, which ADR-0113 §6 leaves to this lane.** There is one
    budget, not a share per band, and each call asks for whatever remains. So a
    band that comes back short donates its remainder to the next one — the question
    §6 names as real and open — and the answer taken here is the one ADR-0072 §5's
    own sentence implies, since "fills its budget ``ASSERTED`` first, then
    ``ATTESTED``, then ``DERIVED``" describes one budget being filled in order
    rather than three budgets being filled in parallel. It also degrades in the
    right direction: on a store holding only inferences, this returns ``limit``
    inferences rather than a third of ``limit``, so precedence costs nothing when
    there is nothing to prefer.

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
    accepted.** Each call asks for what remains of the budget, so if a lower band's
    answer contains a record already held, the composition comes back one short of
    what that band could have supplied. The alternative is to over-request against
    an estimate of how many duplicates to expect, which is a headroom decision of
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

    Returns:
        Up to ``limit`` records, ordered by band precedence and, within a band, by
        the relevance the store ranked them on. Each id appears at most once, under
        the highest-precedence band that returned it.

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

    composed: list[MemoryRecord] = []
    seen: set[str] = set()
    for band in BAND_PRECEDENCE:
        remaining = limit - len(composed)
        if remaining <= 0:
            break
        found = await store.search(query, limit=remaining, kinds=wanted_kinds, bands=[band])
        # Unwrapped and nothing more: ADR-0128 §6 leaves what a consumer does with
        # ``capped`` to that consumer's own lane, and this assembler takes no policy
        # from it here. The band-scoped read it composes is already forbidden from
        # being read as evidence that a band holds nothing more (ADR-0113 §5), which
        # is a different rule about a different race and is unaffected either way.
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
            # precedence reserved for an assertion, undetectably.
            if band_of(record.provenance.source) is not band:
                continue
            seen.add(record.id)
            composed.append(record)
            if len(composed) >= limit:
                break
    return composed
