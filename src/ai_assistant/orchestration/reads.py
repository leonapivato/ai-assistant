"""Servicing the read a planner asked for, and the record of every turn (ADR-0226).

ADR-0226 opens one envelope beside the plan: the planner may name **at most one**
read it wanted and did not have, and *the loop* — never the planner and never a
tool — services it into the turn's supply. This module is the servicing half of
that decision (§10's "Lane B"), and it holds three things:

* :func:`service_read_request`, which turns one
  :class:`~ai_assistant.core.types.ReadRequest` into the records ADR-0226 §7
  appends to the supply as a **fourth group**, under §6's single budget of ten and
  its hop-before-query precedence — and, since ADR-0227 §3, returns which records
  the **citation hop** reached, because this is the one place the two kinds are
  distinguishable. Since ADR-0229 §1 the hop reaches the record a label **names** as
  well as that record's evidence, so the carrier holds records the fourth group does
  not, and §2 of that ADR is why the fourth group is nonetheless unmoved;
* :func:`resolve_label`, §3's whole label scheme — an ordinal into the very
  ``memories`` sequence the loop passed the planner on this call;
* :func:`resolve_entry`, ADR-0230 §2's label scheme one sequence over — an ordinal
  into the very ``SourceListing`` the loop read for this turn and projected onto
  what it passed the planner; and
* :func:`emit_read_audit`, §9's record, written **once per turn whether or not the
  trigger fired**.

**The third kind is an additive entry and not a second seam** (ADR-0230 §1). A
``LOCAL_FILE`` ask is serviced here, from the same ``ReadRequest``, under the same
budget of ten, into the same fourth group, and onto the same audit record: no second
servicing site, no second budget, no second event key. What it adds is one position
in the servicing order — ADR-0230 §7 puts the fetch **ahead of** the hop, because
this kind is capped at one record where the hop is capped at two labels and the query
at nothing — and one field on §9's record, the class a refusal resolved to.

**No filesystem address is ever composed here** (ADR-0230 §2). This module parses an
ordinal and indexes the listing it was handed; the value it passes ``Fetcher.fetch``
is a :class:`~ai_assistant.core.types.SourceListingEntry` the *fetcher* minted,
carrying the capability that fetch is verified by. No model-supplied string reaches a
filesystem call, is joined to a root, or is assembled into an entry of this module's
own — "a conforming implementation in which a model's output reaches a path is not
this decision however carefully it is bounded".

**What this module is not.** It is not a tool, is not registered, advertises no
capability and is reachable through no ``ToolRegistry`` (§5): ADR-0208 §1's rule
that "a component on the turn path that wants records the supply does not hold does
not obtain them by invoking a tool" is satisfied by a loop reading the store it
already holds. It is not the composing stage and gives that stage no collaborator
(ADR-0170 §2). And it discards no record on the ground of its class (§7): no
placement test, no withholding test, no subtraction — ADR-0204 §2's evaluation runs
once over the final supply, at the loop, *after* this module has returned.

**Failure degrades and never fails the turn** (§5). A failed **or partial** read
leaves the supply exactly as planning saw it: the records that did come back are
discarded with the rest, every count of §9's record is zero, and what represents the
partial case is the **pair** of failure fields — that the servicing failed, and that
a read it had already performed had returned records when it did. A count of
discarded records would report a yield on a turn §5 defines as having received none.

**No identifier crosses the model seam in either direction** (§3). A planner names a
*label*; this module maps it to the record that label was rendered for, by position,
and never parses an identifier out of model output. That is the observer's own
scheme applied to the supply — "a model that can write an id can write one for an
episode it never saw" — and it is what makes the widest possible abuse of the hop
"asking for something already on screen".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.correlation import current_correlation
from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import ReadKind
from ai_assistant.orchestration.conversations import BELIEF_KINDS
from ai_assistant.orchestration.retrieval import assemble_by_band

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import Fetcher, MemoryStore
    from ai_assistant.core.types import (
        FetchRefusal,
        MemoryRecord,
        ReadAsk,
        ReadRequest,
        SourceListing,
        SourceListingEntry,
    )

_log = structlog.get_logger(__name__)

#: ADR-0226 §6's budget: **ten** records the turn's supply did not already hold,
#: shared by the whole emission rather than split per kind.
#:
#: "Ten is a measured figure rather than a judged one, from three directions": the
#: replay's oracle shape is 311/349 hop questions needing exactly one belief, #1844
#: predicts "two to six records", and ten is the prompt size this system already
#: shipped — what ``EPISODIC_SUPPLEMENT_LIMIT`` carried for the whole of pilot-5.
#: It is a **second** budget and never a share of the first: §6 forbids funding it
#: by lowering ``RETRIEVAL_LIMIT`` or ``EPISODIC_SUPPLEMENT_LIMIT``, so this
#: constant may not be traded against either.
READ_BUDGET: Final = 10

#: ADR-0226 §9's fixed event key. One key for every turn — fired, not fired, not
#: reached, serviced and declined alike — because "an instrument that only records
#: its positives cannot measure a fire rate".
READ_AUDIT_EVENT: Final = "turn_read_request"

#: §3's label form, as the ADR spells it: "the ASCII string ``M`` followed by *n* in
#: decimal with no padding".
#:
#: ``[0-9]`` rather than ``\\d`` because the scheme is stated over ASCII and ``\\d``
#: admits every Unicode decimal digit — a label the renderer could not have
#: produced. The nine-digit ceiling is not a second rule: an ordinal that long is
#: past the end of any sequence a turn could pass, so it resolves to nothing either
#: way, and bounding the match keeps a model-supplied string of arbitrary length off
#: :func:`int`.
_LABEL_PATTERN: Final = re.compile(r"M[1-9][0-9]{0,8}")

#: ADR-0230 §2's label form for a file, which is §3's scheme one sequence over:
#: "the ASCII string ``F`` followed by *n* in decimal with no padding".
#:
#: ``F`` and not ``M`` because the two index different sequences — ``memories`` and
#: the turn's listing — and "a single namespace over two sequences would be a label
#: whose meaning depends on which kind quoted it". Every other property of the
#: pattern is :data:`_LABEL_PATTERN`'s and is taken for its reasons: ASCII digits
#: because the scheme is stated over ASCII, and a bounded length because an ordinal
#: that long is past the end of any listing a turn could show, so bounding the match
#: keeps a model-supplied string of arbitrary length off :func:`int`.
_ENTRY_PATTERN: Final = re.compile(r"F[1-9][0-9]{0,8}")


class TriggerOutcome(StrEnum):
    """What the trigger did on one turn (ADR-0226 §8).

    **Three-valued, and the third value is the point.** §8 makes the trigger "the
    planner's own judgement that this turn's supply did not suffice", expressed by
    emitting a request and by nothing else — so a plan carrying one is
    :attr:`FIRED` and a plan carrying none is :attr:`NOT_FIRED`. A turn on which
    planning did not return a plan at all reached no judgement about its supply, so
    it is neither: it is :attr:`NOT_REACHED`, "counted on its own, so that a
    deployment can see how many turns the instrument took no reading from rather
    than have them silently dilute the rate".
    """

    FIRED = "fired"
    NOT_FIRED = "not_fired"
    NOT_REACHED = "not_reached"


class Servicing(StrEnum):
    """What became of an emitted request (ADR-0226 §5, §9).

    :attr:`DECLINED` is §5's channel scoping and nothing else: a read request "is
    not serviced on an operation whose output channel's audience is unbounded", the
    supply stays the three groups ADR-0203 §1 narrowed, and the audit records the
    emission and that it was not serviced. A servicing that ran and *failed* is
    :attr:`SERVICED` with :attr:`ServicedRead.failed` set — the two facts are
    separate, and collapsing them would make a store outage indistinguishable from
    a spoken turn.
    """

    SERVICED = "serviced"
    DECLINED = "declined"
    NOT_ASKED = "not_asked"


class StopReason(StrEnum):
    """Why a turn stopped iterating (ADR-0228 §9).

    **A closed vocabulary of five**, and "no implementation, setting or later lane
    adds a sixth without the ADR that decides it". Four describe a turn that ran to
    its own end and the fifth describes one that did not, which is the hole §9
    fills deliberately: a second planner call that raises still writes a record, and
    none of the four successful outcomes describes it — labelling such a turn
    :attr:`SETTLED` would say the planner stopped asking when it did not, and
    :attr:`BOUND_REACHED` would say a guard fired when none did.

    **It is a stop *reason* and never a turn outcome.** The original failure
    propagates unchanged, exactly as ADR-0226 §11 item 10 requires of its own arms.

    Attributes:
        NOT_ITERATED: No revision was admissible — one of ADR-0228 §2's conditions
            (a) to (e) failed. **The default**, so a turn that ended before it
            reached a first plan carries it and says something true: it did not
            iterate. What separates that turn from one that reached a plan and found
            no revision admissible is :class:`TriggerOutcome`, **not reached**
            against **fired** or **not fired** — the same division ADR-0226 §9 draws
            between its own two defaults. No lane reads this as a claim that a first
            plan existed.
        SETTLED: The last plan carried no request. Reachable only after a revision:
            a turn whose *first* plan carried none failed §2's condition (b) and is
            :attr:`NOT_ITERATED`.
        BOUND_REACHED: ADR-0228 §3's bound of two planner calls stopped the turn
            with its planner still asking.
        BUDGET_REACHED: ADR-0228 §4's per-operation budget was spent when the check
            was made. The boundary instant is spent, not available.
        PLANNING_FAILED: A planner call after the first raised, or the turn ended
            between a servicing and the next plan's return.
    """

    NOT_ITERATED = "not_iterated"
    SETTLED = "settled"
    BOUND_REACHED = "bound_reached"
    BUDGET_REACHED = "budget_reached"
    PLANNING_FAILED = "planning_failed"


@dataclass(frozen=True, slots=True)
class ServicedRead:
    """What one servicing carried into the turn, and what §9 records of it.

    The default instance is the honest record of a turn that serviced nothing —
    every count zero and no failure — which is what a non-firing turn, a declined
    one and a turn whose planner never returned all carry.

    **One of these per servicing, in servicing order** (ADR-0228 §9). Every field
    keeps the meaning ADR-0226 §9 gives it, over its own servicing; ``kinds`` moved
    here from the turn level when the record came to account per emission, because a
    turn's two emissions may ask for different things.

    Attributes:
        kinds: The kind of each ask this servicing's request carried, in the order
            the request carries them.
        records: The fourth group, in servicing order: the fetched file's one record
            first (ADR-0230 §7), then the hop's records, then the sighted query's,
            each already deduplicated against the pre-servicing supply *and* against
            every record admitted before it (§7). Empty on a failed or partial
            servicing, which "leaves the supply as planning saw it" (§5).
        returned: How many records the servicing carried into the union **before**
            deduplication. Never a per-ask tally of what each store call handed
            back, and zero on a failed servicing — §5 discards a partial read's
            records with the rest, so nothing it fetched was returned to the turn.
        new: How many of those were new after deduplication — the fourth group's
            own length, and §8's novelty numerator.
        deduplicated: How many the deduplication removed because the union already
            held them, whether from the pre-servicing supply or from an earlier
            arrival within this same servicing.
        labels_unresolved: How many labels resolved to nothing — malformed, out of
            range, or naming a record that is no longer live (§3). **One population
            across the kinds** (ADR-0230 §9): an ``F`` label outside the turn's
            listing never reached the fetcher and counts here, exactly as an ``M``
            label outside the supply does.
        refusal: ADR-0230 §9's one added field: the class the ``LOCAL_FILE`` fetch
            resolved to, where it resolved to one, and ``None`` where the fetch
            returned a record or where this servicing carried no ``LOCAL_FILE`` ask.
            **A refusal and an unresolved label are two facts and are recorded
            separately** — "a label that resolved to nothing never reached the
            fetcher; a refusal is a label that resolved to an entry the fetcher then
            declined", and "an implementation that collapses them makes the two
            indistinguishable, and they have different causes and different fixes".
            A **member of a closed enumeration and never free text**, so there is
            nowhere in this record for a path, a name, an excerpt or a library's
            message to sit.
        truncated_kinds: Which kinds the budget cut short, in servicing order.
            Empty where it cut neither.
        failed: Whether the servicing failed. Where it did, every count above is
            zero and :attr:`records` is empty.
        failed_after_read_returned: Where it failed, whether **any read it had
            already performed had returned records** when it did. Stated over
            *reads* and not over asks, because §6's sighted query is several
            ``MemoryStore.search`` calls: "a query whose second band raises after
            its first returned is as partial as a hop that returned before a query
            raised, and a field keyed on asks would call the one-ask case a total
            failure".
    """

    kinds: tuple[ReadKind, ...] = ()
    records: tuple[MemoryRecord, ...] = ()
    returned: int = 0
    new: int = 0
    deduplicated: int = 0
    labels_unresolved: int = 0
    refusal: FetchRefusal | None = None
    truncated_kinds: tuple[ReadKind, ...] = ()
    failed: bool = False
    failed_after_read_returned: bool = False


@dataclass(slots=True)
class _Reads:
    """Whether any store read this servicing performed has returned records yet.

    §9's second failure field is stated over reads, and the sighted query is
    several of them behind one call, so this is threaded into
    :func:`~ai_assistant.orchestration.retrieval.assemble_by_band` as its page
    observer rather than inferred from what the servicing has in hand when it
    catches the failure.
    """

    returned_any: bool = False

    def note(self, count: int) -> None:
        """Record that one read returned ``count`` records.

        Args:
            count: How many records that read returned. Zero is a read that
                returned nothing, which is not what §9's field is about.
        """
        self.returned_any = self.returned_any or count > 0


@dataclass(frozen=True, slots=True)
class _HopReach:
    """What one ``CITATION_HOP`` ask reached, in the two shapes the servicing needs.

    **Two sequences and not one, because ADR-0229 §2 separates reach from supply.**
    A record a label *named* is in the pre-servicing supply by construction — §3's
    label is a position in the very sequence the loop passed the planner — so
    offering it to :class:`_Union` could only ever deduplicate it, and the sole
    effect would be one more ``returned`` and one more ``deduplicated`` on every
    serviced hop. §2 forbids exactly that: "a record named by a label is counted in
    none of the three", and ADR-0226 §8's novelty rate would otherwise report a
    constant depression that tells a reader nothing the labels do not.

    So :attr:`evidence` is what the union sees — unchanged from before ADR-0229 —
    and :attr:`expansion` is what ADR-0227 §3's carrier is built from.

    Attributes:
        expansion: ADR-0229 §3's **pre-deduplication** expansion sequence: labels in
            the order the ask names them and, for each label that resolved to a live
            record, that record **immediately followed by** its own live evidence in
            the order that record stores it.
        evidence: The candidates for ADR-0226 §7's fourth group — every named
            record's live evidence, labels in the ask's order and each record's
            evidence in stored order, and **no named record**.
        unresolved: How many labels resolved to nothing (ADR-0226 §3).
    """

    expansion: tuple[MemoryRecord, ...]
    evidence: tuple[MemoryRecord, ...]
    unresolved: int


@dataclass(slots=True)
class _Union:
    """The turn's supply under construction, and what §9 counts about it (§7).

    **The seen set is seeded from the pre-servicing supply and grows with every
    admission**, which is §7's deduplication "over the whole union and not only
    against the pre-servicing supply": a record both kinds reach enters the fourth
    group once, at the hop's position, and its second arrival "consumes no slot of
    the budget". A servicer seeding from the supply alone would satisfy the narrower
    clause and still render one record twice.
    """

    held: set[str]
    budget: int
    admitted: list[MemoryRecord] = field(default_factory=list)
    returned: int = 0
    deduplicated: int = 0

    @property
    def remaining(self) -> int:
        """How many slots of the budget are still unspent."""
        return self.budget - len(self.admitted)

    def admit(self, candidates: Sequence[MemoryRecord]) -> bool:
        """Take what fits, in order, and say whether the budget cut the rest.

        Args:
            candidates: One kind's records, in the order §6 fixes for that kind.

        Returns:
            Whether the budget stopped a candidate the deduplication had not
            already removed — that is, whether this kind was truncated.
        """
        truncated = False
        for record in candidates:
            self.returned += 1
            if record.id in self.held:
                self.deduplicated += 1
            elif self.remaining > 0:
                self.held.add(record.id)
                self.admitted.append(record)
            else:
                truncated = True
        return truncated


async def service_read_request(  # noqa: PLR0913 — the store, the emission, and one parameter per thing a kind is serviced against; §7 admits one site and this is it
    store: MemoryStore,
    request: ReadRequest,
    *,
    supply: Sequence[MemoryRecord],
    fetcher: Fetcher | None,
    listing: SourceListing | None,
    audit: TurnReadAudit,
) -> tuple[str, ...]:
    """Service one emission, once, into the fourth group (ADR-0226 §§2, 6, 7).

    **The local file is serviced first, then the citation hop, then the sighted
    query** (ADR-0230 §7, amending ADR-0226 §6's cross-kind precedence sentence in
    that one respect). §6's decision is applied and not moved — the capped read ahead
    of the uncapped one — and ADR-0230 §1 caps the fetch hardest of the three: one
    label, one file, one record, always. "Where the fetch takes its slot the hop is
    serviced with nine and the query with what remains; a fetch that refuses takes
    none." The reverse order would let a hop that reached ten records starve the one
    read the user pointed at.

    A hop's size is bounded by §2's two-label cap where a query can return the whole
    budget on every firing, so ordering the capped read ahead of the uncapped one
    "makes the union the *measured* union in the ordinary case, and gives the query up
    only where a hop genuinely reached ten records". Where the hop exhausts the budget
    the query is serviced with whatever is left, which may be nothing, and the
    truncation is recorded.

    **The budget is counted after deduplication** — ten records the turn's supply
    did not already hold — and the deduplication ranges over the whole union (§7).
    A duplicate costs the kind that returned it a slot rather than provoking a
    deeper page: that is the same answer ADR-0158 §4 and ADR-0113 §8 already give,
    since over-requesting against an estimate of duplicates is the headroom bet
    #789 owns.

    **Nothing here selects on class.** No placement test, no withholding test and no
    subtraction: "every record it returns, after §6's budget and §7's deduplication,
    enters the fourth group and reaches the turn" (§7). ADR-0204 §2's evaluation is
    the loop's, taken once over the final supply after this returns.

    **The budget is not a parameter, and that is ADR-0226 §6 rather than an
    inflexibility.** §6 fixes it at ten and rules that "no configuration, setting or
    later lane makes the count configurable without the ADR that decides it"; a
    keyword defaulted to :data:`READ_BUDGET` would be exactly such a setting,
    reachable by any caller in this package and by any later lane, so the figure is
    read from the constant here and nowhere else. §12 is where a decision to move it
    goes.

    **A refusal is not a failure, and that is the one disposition this kind adds**
    (ADR-0230 §6). A ``FetchOutcome`` carrying a refusal "adds no record, fails no
    turn, degrades no servicing and discards no other kind's records": the fetch takes
    no slot, the hop and the query are serviced exactly as they would have been, and
    §9's record carries the refusal's **class** beside the counts. That is ADR-0226
    §3's disposition for a label that resolves to nothing — "not an error, not a park,
    not a degradation of the turn" — applied to the outcome one step later, and it is
    what distinguishes it from §5's all-or-nothing failure posture below.

    **Nothing of a refusal is rendered** (ADR-0230 §6, §9). The class is a member of a
    closed enumeration and the whole of the value, so no name, no excerpt and no
    message from an extraction library exists here to reach a prompt, a reply or a
    log; and this function puts no record in the supply for a refused fetch, so there
    is nothing for the composing stage to render either.

    **A failure discards everything.** §5 makes the servicing all-or-nothing, so a
    ``MemoryStoreError`` from any read — the hop's ``get_many``, or any band of the
    query's composition — leaves the supply as planning saw it, and the record it
    writes has every count zero. **A ``Fetcher`` contributes no such failure**:
    ADR-0230 §4 rules that neither of its members raises for a source reason and adds
    no error class to ``core/errors.py``, "because there is no failure a caller would
    handle differently from a refusal it must already handle" — so the net below is
    unwidened for this kind rather than silently extended to it. Only
    ``MemoryStoreError`` is *degraded*, which is deliberately the same net
    :meth:`~ai_assistant.orchestration.loop.LearningLoop._retrieve` and
    ``_supplement`` already use: it is the failure the ``MemoryStore`` contract
    states, and widening the net here alone would claim a robustness the turn's two
    older reads do not have.

    **It writes its record rather than returning it, and that is what makes §9's
    counts honest about a servicing that never finished.** (What it *returns* is
    ADR-0227 §3's carrier, below, which a servicing that never finished has nothing
    to say about — the supply is left as planning saw it, so the empty carrier a lost
    return value would have produced is the same answer.) A cancellation is not a
    ``MemoryStoreError``: it passes through the degradation above and out of the
    turn, where ADR-0226 §9's record is emitted from a ``finally`` regardless. A
    function that reported by *returning* would leave that record saying a completed
    servicing with a zero yield — a true fire with no read under it, in §8's novelty
    denominator — and would lose the one fact §9 asks for in the same breath: whether
    a read it had already performed had returned records. The ``finally`` below
    writes the failure with the observer's own answer, so a hop that returned before
    a cancellation landed in the query is recorded as the partial servicing it was.

    **And it returns ADR-0227 §3's carrier, which the audit deliberately does not
    hold.** §3 rules that which records the citation hop reached is "recorded where
    the kind is known — at the servicer, which is the one place ``CITATION_HOP`` and
    ``SIGHTED_QUERY`` are distinguishable — and is carried from there to the render
    site as data". This function is that place. It is **not** put on
    :class:`ServicedRead` or on §9's record: that record "copies no text" and carries
    "no identifier but the correlation id", and "threading a render decision through
    it would put record identifiers on a surface whose whole discipline is that they
    are not there".

    **What the carrier holds** (ADR-0227 §3, §4; ADR-0229 §3): the **distinct** ids of
    the records the hop reached that the turn's supply holds **after** this
    servicing — ADR-0229 §3's **expansion sequence**, restricted to the records
    ADR-0227 §3 admits, under §4's deduplication with the **first** occurrence
    keeping the place. The expansion is labels in the order the ask names them and,
    for each label that resolved to a live record, that record **immediately followed
    by** its own live evidence in the order that record stores it; the relation binds
    the expansion and binds nothing after the deduplication, so a hop naming an
    episode ``E`` and a belief ``B`` citing ``E`` expands to ``E, B, E`` and carries
    ``E, B``. A record the hop reached that the supply already held is deduplicated
    out of the fourth group, keeps its position and **is** in the carrier (ADR-0227
    §1's third clause); a record ADR-0226 §6's budget cut is not in the supply at all
    and so is not, which is ADR-0227 §4's "the records it cut render nothing at all".
    A **named** record is never excluded by that test, because ADR-0226 §3's label is
    a position in the pre-servicing supply and so the record is in it by construction
    (ADR-0229 §2). It is **empty** on every turn that did not fire, whose servicing
    was declined, whose servicing failed or was partial, and whose hop resolved no
    live record — the same all-or-nothing posture §5 gives the supply.

    **The order is fixed here and the tail exclusion and the cap are not**
    (ADR-0227 §3): "the servicer fixes the order and the render site applies §1's tail
    exclusion and §4's cap, in that division and no other". This function computes no
    conversation-tail split and takes no view of what the renderer will do with what
    it names.

    Args:
        store: The store this turn already reads. The same object the retrieval
            stage read, so the hop resolves against the store the labelled records
            came from.
        request: What the planner emitted. Its validators are the authority on
            shape (ADR-0226 §4); this function assumes at most one ask of each kind
            and reads no further condition off it.
        supply: The three groups the loop passed
            :meth:`~ai_assistant.core.protocols.Planner.plan` **on this call**, in
            order. It is both §3's label space and §7's deduplication set, and it is
            the same sequence for both because §3's label *is* a position in it. It
            is **not** the ``LOCAL_FILE`` label space, which is ``listing`` below —
            "``M`` indexes ``memories``, ``F`` indexes the listing" (ADR-0230 §1).
        fetcher: The seam a ``LOCAL_FILE`` ask is answered from, or ``None`` where no
            root is configured. **Passed rather than defaulted**, so a caller states
            the absence instead of inheriting it: a defaulted seam would let a later
            call site silently service no file and read, in §9's record, exactly like
            a turn on which the planner named none.
        listing: The very ``SourceListing`` the loop read for this turn and projected
            onto what it passed the planner, or ``None`` where no fetcher is wired.
            It is ADR-0230 §2's label space **and** the authority the fetch is
            verified against — "the loop resolves a label by parsing *n* and indexing
            the very sequence it passed on this call, and fetches the entry at that
            same position of the listing it holds". Both come from this one object,
            which is what makes the projection's positional guarantee reach the fetch.
            ``None`` and an empty listing are the same case for the turn: no file is
            nameable, and every label resolves to nothing.
        audit: This turn's record. One :class:`ServicedRead` entry is appended to
            :attr:`TurnReadAudit.servicings` on every path out of this function, and
            :attr:`ServicedRead.records` is what the caller appends to the fourth
            group. A turn that services twice appends two, in servicing order
            (ADR-0228 §9).

    Returns:
        ADR-0227 §3's carrier: the distinct ids of the records this turn's citation
        hop reached that the supply holds after this servicing, in ADR-0229 §3's
        order — the expansion sequence under ADR-0227 §4's first-occurrence
        deduplication. Empty where nothing was serviced, where the servicing failed,
        and where the hop reached nothing.
    """
    reads = _Reads()
    union = _Union(held={record.id for record in supply}, budget=READ_BUDGET)
    completed: ServicedRead | None = None
    reached: tuple[str, ...] = ()
    resolved_by_hop: tuple[MemoryRecord, ...] = ()
    hop = _ask_of(request, ReadKind.CITATION_HOP)
    query = _ask_of(request, ReadKind.SIGHTED_QUERY)
    local_file = _ask_of(request, ReadKind.LOCAL_FILE)
    # `ReadAsk`'s validator makes a `SIGHTED_QUERY` ask's query non-``None`` (§4),
    # so this reads the guarantee rather than restating it as a policy: there is no
    # branch here for an ask the model refuses to construct. A `LOCAL_FILE` ask's
    # `entry` carries the same guarantee (ADR-0230 §1) and is read the same way.
    statement = None if query is None else query.query
    named = None if local_file is None else local_file.entry
    truncated: list[ReadKind] = []
    unresolved = 0
    refusal: FetchRefusal | None = None
    try:
        if named is not None:
            # ADR-0230 §7: **first**, ahead of the hop, because this kind is capped
            # at one record and the hop at two labels — "at one slot, the cheapest
            # precedence position this corpus has ever had to argue for".
            entry = resolve_entry(named, listing)
            if entry is None or fetcher is None or listing is None:
                # ADR-0230 §2: a label outside the shown set — malformed, out of
                # range, or named on a turn that showed no listing at all — "resolves
                # to nothing … discarded silently, and recorded in §9's audit as an
                # unresolved label". §9 puts it in **this** count and not beside the
                # refusal: it "never reached the fetcher", and the two facts have
                # different causes and different fixes.
                unresolved += 1
            else:
                # The entry handed back is the one this fetcher minted, carried
                # unaltered from the listing this loop holds (ADR-0230 §2, §4). No
                # path is composed, no name is joined to a root, and no entry is
                # assembled here.
                outcome = await fetcher.fetch(listing, entry)
                refusal = outcome.refusal
                if outcome.record is not None:
                    # §9's second failure field is stated over **reads** rather than
                    # over asks, and a fetch that returned a record is a read this
                    # servicing performed that returned one. So a hop raising after
                    # the file came back is recorded as the partial servicing it was.
                    reads.note(1)
                    # One slot of ADR-0226 §6's ten, counted after deduplication and
                    # drawn through the same union as every other kind — "not a
                    # share, not a second budget". The budget cannot cut it: the
                    # fetch is first and admits one record into ten empty slots, so
                    # `LOCAL_FILE` never appears in `truncated_kinds`, which is §1's
                    # cap of one showing up in the audit rather than a case elided.
                    union.admit((outcome.record,))
        if hop is not None:
            reach = await _hop_records(store, hop, supply=supply, reads=reads)
            unresolved = reach.unresolved
            resolved_by_hop = reach.expansion
            # ADR-0229 §2: the union is offered the **evidence** alone. A named
            # record is in the pre-servicing supply by construction, so admitting it
            # could only deduplicate — adding one to `returned` and one to
            # `deduplicated` on every serviced hop, for no informational gain and at
            # the cost of ADR-0226 §8's novelty rate. It spends no slot of §6's
            # budget and moves no field of §9's record.
            if union.admit(reach.evidence):
                truncated.append(ReadKind.CITATION_HOP)
        if statement is not None:
            allowed = union.remaining
            found = (
                []
                if allowed <= 0
                else await assemble_by_band(
                    store, statement, limit=allowed, kinds=BELIEF_KINDS, on_page=reads.note
                )
            )
            union.admit(found)
            # The query is asked for exactly the slots the hop left, so the budget
            # cannot stop a record it returned — what it does is shorten the ask.
            # A query given the whole budget was not truncated by it, however much
            # more the store might have held; a query given less and filling every
            # slot of it is the case §6 says the audit records.
            if allowed < READ_BUDGET and len(found) == allowed:
                truncated.append(ReadKind.SIGHTED_QUERY)
        completed = ServicedRead(
            kinds=tuple(ask.kind for ask in request.asks),
            records=tuple(union.admitted),
            returned=union.returned,
            new=len(union.admitted),
            deduplicated=union.deduplicated,
            labels_unresolved=unresolved,
            refusal=refusal,
            truncated_kinds=tuple(truncated),
        )
        # ADR-0227 §3's carrier, computed on the success path alone and over
        # `union.held` — which is seeded from the pre-servicing supply and grown by
        # every admission, so membership of it *is* "the supply holds this record
        # after servicing". A named record passes that test by construction
        # (ADR-0229 §2), so the restriction bites on truncated evidence alone.
        # `dict.fromkeys` is ADR-0227 §4's deduplication over ADR-0229 §3's
        # expansion sequence, with the first occurrence keeping the place:
        # `Provenance.evidence` carries no uniqueness constraint and nothing stops
        # one label naming what another cites, so the expansion can name one record
        # more than once — `E, B, E` deduplicates to `E, B`, which §3 rules the
        # required result rather than a case to repair.
        reached = tuple(
            identifier
            for identifier in dict.fromkeys(record.id for record in resolved_by_hop)
            if identifier in union.held
        )
    except MemoryStoreError:
        # §5's whole posture, and the archive's for the same reason ADR-0225 §2
        # gives: "a turn that answered from the supply it had is a worse turn, not
        # a broken one, and a mechanism whose whole purpose is a marginal
        # improvement in reach must never be able to take the reply down with it".
        _log.warning("read_request_degraded", stage="service_read_request", exc_info=True)
    finally:
        # One record, on every path out of this function — the completed servicing,
        # the degraded one, and the one a cancellation carried away — and the
        # failing ones carry the observer's own answer to §9's second failure
        # field. Written here rather than returned, so no path can leave the turn
        # with a record describing a servicing that did not happen.
        #
        # **The refusal rides on the failing record too, where every count is
        # zero** (ADR-0230 §9). §5's zeroed counts say a *yield* was discarded, and
        # a refusal yielded nothing there was to discard: §9 enumerates the two
        # cases in which this field is empty — "where the fetch returned a record or
        # where no ``LOCAL_FILE`` ask was made" — and a fetch that refused before
        # the hop raised is neither. Dropping it would make that turn
        # indistinguishable from one whose planner named no file at all, which is
        # the collapse §9 refuses one field over for the unresolved-label count.
        audit.servicings += (
            completed
            or ServicedRead(
                kinds=tuple(ask.kind for ask in request.asks),
                refusal=refusal,
                failed=True,
                failed_after_read_returned=reads.returned_any,
            ),
        )
    return reached


def resolve_label(label: str, supply: Sequence[MemoryRecord]) -> MemoryRecord | None:
    """Resolve one label to the record it was rendered for, or to nothing (§3).

    **The label is a position, and that is the whole of the scheme.** "The label of
    the record at 1-based index *n* of ``Planner.plan``'s ``memories`` is the ASCII
    string ``M`` followed by *n* in decimal with no padding." Both sides derive it
    from ``memories`` and neither consults the other: `planning` renders the label
    from the sequence it was given, and this function parses *n* and indexes **the
    very sequence the loop passed on this call**. No mapping, table or identifier
    crosses the two packages, which is why this function writes its own three lines
    rather than importing `planning`'s renderer — the import golden rule 1 forbids
    it, and §10 forbids any value crossing beyond ``memories`` and the ``ActionPlan``.

    **A label outside the shown set resolves to nothing**, and every way of being
    outside it lands here alike: a string that does not match the form, an *n* below
    1, and an *n* beyond the sequence's length. Each is discarded silently — not an
    error, not a park, not a degradation of the turn — and counted in §9's audit as
    dropped. The remaining case, a label whose record is no longer live, is
    ``get_many``'s and is applied by :func:`_hop_records`.

    Args:
        label: What the planner named. Model-supplied text, treated as a label and
            never as an identifier (§3).
        supply: The sequence the loop passed the planner on this call.

    Returns:
        The record at that position, or ``None``.
    """
    if _LABEL_PATTERN.fullmatch(label) is None:
        return None
    ordinal = int(label[1:])
    if ordinal > len(supply):
        return None
    return supply[ordinal - 1]


def resolve_entry(label: str, listing: SourceListing | None) -> SourceListingEntry | None:
    """Resolve one entry label to the file it names, or to nothing (ADR-0230 §2).

    **An ordinal into the listing the loop passed, and that is the whole of the
    scheme.** "The label of the entry at 1-based index *n* of the sequence the loop
    passed is the ASCII string ``F`` followed by *n* in decimal with no padding."
    Both sides derive it from the listing and neither consults the other: `planning`
    renders the label from the ``ShownFile`` sequence it was given, and this function
    parses *n* and indexes the ``SourceListing`` that sequence was projected from —
    positionally, one for one, which is what makes the two agree with no table, no
    mapping and no path crossing between the packages.

    **The listing rather than the projection, and the difference is the capability.**
    What crosses into `planning` is a :class:`~ai_assistant.core.types.ShownFile`,
    which carries no ``handle``; what a fetch is addressed by is the
    :class:`~ai_assistant.core.types.SourceListingEntry` at the same position of the
    listing `orchestration` retained. Resolving here rather than there is what lets
    the loop hand a fetcher an entry the *fetcher itself* minted while the model has
    seen nothing it could forge one from.

    **This is ADR-0226 §3's scheme one sequence over, and it is taken for §3's own
    reason.** On a filesystem the property is worth strictly more than it is over a
    store: the alternative is a path, and "a model-supplied path bounded by a
    containment check is a whole class of defect this decision can simply not have —
    ``..`` normalisation, a symlink pointing out of the root, a case-insensitive
    filesystem, a Unicode normalisation the check and the kernel disagree about". An
    ordinal cannot be *nearly* right. It is an index into a sequence, and an index
    outside the range resolves to nothing.

    **Every way of being outside the shown set lands here alike**: a string that does
    not match the form, an *n* below 1, an *n* beyond the sequence's length, and a
    turn that showed no listing at all — a deployment with no fetcher wired, or one
    whose root came back empty, which §3 makes the same case. Each is discarded
    silently — not an error, not a park, not a degradation of the turn — and counted
    in §9's audit as an unresolved label. The remaining case, an entry the fetcher can
    no longer resolve, is the fetcher's and comes back as a
    :class:`~ai_assistant.core.types.FetchRefusal`.

    Args:
        label: What the planner named. Model-supplied text, treated as a label and
            **never** as a filesystem address in any form (ADR-0230 §2): nothing here
            constructs a path, joins a fragment to a root, or hands this string to a
            filesystem call.
        listing: The listing the loop read for this turn, or ``None`` where no
            fetcher is wired — "a turn on which the loop passed no listing is a turn
            on which no file is nameable".

    Returns:
        The entry at that position of that listing, or ``None``.
    """
    if listing is None or _ENTRY_PATTERN.fullmatch(label) is None:
        return None
    ordinal = int(label[1:])
    if ordinal > len(listing.entries):
        return None
    return listing.entries[ordinal - 1]


@dataclass(slots=True)
class TurnReadAudit:
    """ADR-0226 §9's record for one turn, filled in as that turn runs.

    **Mutable, and defaulted to the truth about a turn that never got anywhere.**
    A fresh instance says the trigger was **not reached**, nothing was asked and
    nothing was serviced — which is exactly the record §8 owes a turn whose planner
    raised, or one that failed before the planner was called. The turn overwrites
    what it learns, in order, and :meth:`emit` writes whatever it holds at the
    moment the turn ends. That is why the default is not "not fired": a turn that
    never reached a judgement is in neither the fire rate's numerator nor its
    denominator, and defaulting it into the denominator would let a planner outage
    read as a collapse in the fire rate.

    **Extended, not replaced, when a turn came to plan twice** (ADR-0228 §9), which
    is what ADR-0226 §9 itself provided for: "An ADR admitting a second serviced
    emission per turn extends this record to account per emission and keeps every
    field's meaning." One record, one turn, one event key, one ``INFO`` line, emitted
    once and conditioned on nothing — every clause of §9 binds unchanged. What
    changed is that the per-servicing counts became :attr:`servicings`, a sequence
    with one entry per servicing, and that two turn-level fields were added beside
    them.

    Attributes:
        trigger: What the trigger did (§8). **Turn-level**: a turn's trigger fired
            if *any* plan that turn produced carried a request (ADR-0228 §9), which
            is what keeps the live fire rate a per-turn rate directly comparable to
            the replay's 13.6%.
        servicing: What became of an emitted request (§5). Turn-level, and it stays
            so: ADR-0226 §5's channel scoping is a property of the operation, and a
            turn whose servicing is declined never iterates (ADR-0228 §2(c)), so it
            has exactly one emission to describe.
        servicings: One entry per servicing, in servicing order (ADR-0228 §9). Empty
            on a turn that serviced nothing — a turn that did not fire, one that was
            declined, and one that never reached a plan.
        planner_calls: How many calls to ``Planner.plan`` this turn made (ADR-0228
            §9). Counted when a call is **started** rather than when it returns, so a
            turn whose second call raised reports two and its **planning failed**
            stop reason describes a call the record admits was made. Zero only where
            the turn ended before the planner was reached at all, which is the same
            turn §8 records as **not reached**.
        stop: Why the turn stopped iterating (:class:`StopReason`).
    """

    trigger: TriggerOutcome = TriggerOutcome.NOT_REACHED
    servicing: Servicing = Servicing.NOT_ASKED
    servicings: tuple[ServicedRead, ...] = ()
    planner_calls: int = 0
    stop: StopReason = StopReason.NOT_ITERATED

    def emit(self) -> None:
        """Write this turn's record — see :func:`emit_read_audit`."""
        emit_read_audit(
            trigger=self.trigger,
            servicing=self.servicing,
            servicings=self.servicings,
            planner_calls=self.planner_calls,
            stop=self.stop,
        )


def emit_read_audit(
    *,
    trigger: TriggerOutcome,
    servicing: Servicing,
    servicings: Sequence[ServicedRead] = (),
    planner_calls: int = 0,
    stop: StopReason = StopReason.NOT_ITERATED,
) -> None:
    """Write ADR-0226 §9's record for one turn, once, at ``INFO``.

    **Every turn writes one, whether or not the trigger fired**, and its emission is
    "conditioned on nothing: not on the plan being persisted, not on the turn
    completing, and not on capacity being admitted". A turn that fired and then
    failed still contributes its numerator, a turn that did not fire still
    contributes its denominator, and a turn that never reached the planner's
    judgement contributes to neither and says so.

    **Counts and kinds, and no copy.** The record does not carry the query the
    planner composed, the labels it named, any ``content`` span, any excerpt or any
    rendering: nothing bounds what a planner may put in a query — it reads the
    rendered supply — so a clause retaining the query and a clause forbidding record
    content would contradict each other on the same bytes. The ask stays durable on
    the frozen ``ActionPlan`` the planning store already keeps, and this record
    neither copies it nor points at it.

    **And no address, in any form** (ADR-0230 §9). No path, no root, no file name, no
    extension, no size, no ``modified_at``, no excerpt of an extracted text and no
    message from an extraction library appears anywhere in this event. A file name is
    the same shape of value a query is — "it is chosen by whoever named the file, it
    can carry anything a filename can carry" — so a Tier 2 event logging one would be
    a Tier 1 leak on a value this system did not mint (ADR-0004 §5). The one field
    this kind adds is a **class**: ``refusal`` is a
    :class:`~ai_assistant.core.types.FetchRefusal` member or absent, which is why
    §9's no-copy rule admits it. What keeps this record inside Tier 2 is these clauses
    and not the redaction net.

    **What the refusal rate is read from, and what it is not.** With the class beside
    the kinds, the refusal rate **per kind** is readable over a population of turns
    from this one event, exactly as the fire rate and the novelty rate are — computed
    over a population and never as a per-turn quantity, and never called a precision
    or a recall. A deployment with no root configured reads a 0% fire rate for
    ``local_file``, and that is a true statement about that configuration rather than
    a reading of a trigger: no figure for this kind is reported without saying whether
    a root was configured.

    **The only identifier is the ambient correlation id** (ADR-0119 §4), read here
    with :func:`~ai_assistant.core.correlation.current_correlation` rather than
    inherited: ``core/logging.py`` merges ``structlog``'s own contextvars and
    ``core/correlation.py`` keeps the id in a ``ContextVar`` of its own, so an
    emitter that merely logged would emit an event with no correlation field at all.
    Where it is ``None`` the field says the turn ran outside a correlated operation
    and the record is emitted regardless. There is **no plan identifier**: a pointer
    would have to be ``ActionPlan.id``, and ``Identifier`` admits any non-blank
    encodable string, so a third-party planner — or ``ModelBackedPlanner``'s own
    injectable id factory — may supply one carrying content, which in a Tier 2 event
    is a Tier 1 leak that no format test can separate from a trusted value.

    **The every-turn obligation binds this code and not a deployment's log
    configuration.** A deployment whose ``log_level`` is above ``INFO`` discards the
    event and loses the instrument with it; that is the honest cost of putting the
    record in the log rather than in a store, and §12's deferred durable surface is
    what a deployment that cannot accept it fires.

    **The counts account per servicing and the rates stay per turn** (ADR-0228 §9).
    ``servicings`` is an ordered sequence with one entry per servicing, each field of
    an entry keeping the meaning §9 gives it over its own servicing; ``trigger``,
    ``servicing``, ``planner_calls`` and ``stop`` are the turn's. **No lane divides
    emissions by turns and calls the result a fire rate** — a turn that emits twice
    is one turn, and counting emissions over turns would produce a figure above 100%
    in the limit and would move for a reason that has nothing to do with the
    planner's judgement about a first supply. The two figures this shape newly
    supports are the **iteration rate** (the share of fired turns that revised) and
    the **stop distribution**; neither is a precision, a recall or a novelty rate,
    and ADR-0226 §8's prohibition on reporting precision or recall from this record
    alone binds them too.

    **Two turn-level fields and a sequence, rather than a second event.** §9 forbids
    a second audit beside this one in terms, and the shape it prescribes — "account
    per emission" — is a sequence. The stop reason sits at the turn level rather than
    in the last entry so that the guard rates are readable without reconstructing
    them: "how often does the budget fire" is a count over one field.

    Args:
        trigger: What the trigger did (§8), over the turn.
        servicing: What became of an emitted request (§5).
        servicings: One entry per servicing, in servicing order. Empty where nothing
            was serviced.
        planner_calls: How many calls to ``Planner.plan`` the turn made (ADR-0228
            §9).
        stop: Why the turn stopped iterating (ADR-0228 §9).
    """
    _log.info(
        READ_AUDIT_EVENT,
        correlation_id=current_correlation(),
        trigger=trigger.value,
        servicing=servicing.value,
        planner_calls=planner_calls,
        stop=stop.value,
        servicings=tuple(
            {
                "kinds": tuple(kind.value for kind in read.kinds),
                "returned": read.returned,
                "new": read.new,
                "deduplicated": read.deduplicated,
                "labels_unresolved": read.labels_unresolved,
                "refusal": None if read.refusal is None else read.refusal.value,
                "truncated_kinds": tuple(kind.value for kind in read.truncated_kinds),
                "failed": read.failed,
                "failed_after_read_returned": read.failed_after_read_returned,
            }
            for read in servicings
        ),
    )


def _ask_of(request: ReadRequest, kind: ReadKind) -> ReadAsk | None:
    """The request's ask of one kind, or ``None``.

    ``ReadRequest`` admits at most one ask of each kind (ADR-0226 §4), so this
    returns the first match without deciding anything the model has not already
    refused.

    Args:
        request: The emission.
        kind: Which kind to look for.

    Returns:
        That kind's ask, or ``None`` where the request carries none.
    """
    return next((ask for ask in request.asks if ask.kind is kind), None)


async def _hop_records(
    store: MemoryStore,
    ask: ReadAsk,
    *,
    supply: Sequence[MemoryRecord],
    reads: _Reads,
) -> _HopReach:
    """Follow one ``CITATION_HOP`` ask to the records its labels reach (§2, §3).

    **A label names a destination** (ADR-0229 §1). The hop's reach is, for each
    label, the record that label resolves to **together with** that record's own
    stored ``Provenance.evidence`` — where ADR-0226 §3's "follows only … evidence"
    reached the evidence alone, which left the record the planner pointed at in no
    return value and is the defect #1960 measures. **No class, kind or field test is
    applied here**: not on ``MemoryKind``, not on ``disposition``, not on
    ``outcome``, and not on whether the evidence is empty. What a reached record
    *renders* is ADR-0227 §1's question, decided at the render site, and a second
    copy of that test here is the site ADR-0227 §3 divides away from it.

    **A keyed load and not a search.** The labels resolve in code to records the
    loop already selected; their stored ``Provenance.evidence`` is resolved through
    ``MemoryStore.get_many``, which is ADR-0208 §1's untouched keyed-load clause —
    "records the turn already names, fetched by identifier" — and is why the hop
    needs no supersession of that ADR at all.

    **One call, one snapshot, and the labelled records' own ids ride in it.** §3
    rules that "a label whose record is no longer live" resolves to nothing and
    names ``get_many``'s omission as what supplies that case, so a labelled record
    absent from the mapping is a label that resolved to nothing rather than a hop
    that proceeds from a record the store no longer holds. Batching the liveness
    check with the evidence keeps both judged against one read-time snapshot,
    which is the guarantee ``get_many`` offers and two calls would forfeit — and it
    is what ADR-0229 §7 means by "no second store call is added": the named records
    this function now returns were already in this call's result.

    **Only the named records' evidence is read** (§3): the hop follows the labelled
    record's own citations and never the citations of a record reached through it —
    "that is iteration, and it is §12's". Reaching the named record is **zero**
    levels of traversal rather than two (ADR-0229 §1), so ADR-0226 §3's prohibition
    and ADR-0228's restatement of it bind here entire and unweakened.

    Args:
        store: The store to resolve identifiers against.
        ask: The hop ask. At most two labels (:data:`~ai_assistant.core.types.MAX_HOP_LABELS`),
            followed in the order it names them.
        supply: The sequence the loop passed the planner, which is the label space.
        reads: The servicing's read observer, noted when this call returns records.

    Returns:
        What the ask reached (:class:`_HopReach`): ADR-0229 §3's expansion sequence,
        the evidence alone for ADR-0226 §7's union, and how many labels resolved to
        nothing.

    Raises:
        MemoryStoreError: If the store's read fails. The caller owns the
            degradation (§5).
    """
    labelled = [(label, resolve_label(label, supply)) for label in ask.labels]
    unresolved = sum(1 for _, record in labelled if record is None)
    found = [record for _, record in labelled if record is not None]
    if not found:
        return _HopReach(expansion=(), evidence=(), unresolved=unresolved)

    wanted: list[str] = []
    seen: set[str] = set()
    for record in found:
        for identifier in (record.id, *record.provenance.evidence):
            if identifier not in seen:
                seen.add(identifier)
                wanted.append(identifier)
    resolved = await store.get_many(wanted)
    reads.note(len(resolved))

    expansion: list[MemoryRecord] = []
    cited: list[MemoryRecord] = []
    for record in found:
        if record.id not in resolved:
            # §3's third way of resolving to nothing: the label named a record the
            # store no longer holds. It reaches **nothing** — not the named record
            # and not any evidence (ADR-0229 §4) — because honouring it from the
            # supply's own copy would read a forgotten exchange back to the user by
            # a route no forgetting mechanism watches. Counted with the malformed
            # and out-of-range labels, because from the audit's side all three are
            # one population: a label the turn could not honour.
            unresolved += 1
            continue
        evidence = [resolved[cite] for cite in record.provenance.evidence if cite in resolved]
        # ADR-0229 §3's "immediately followed by": the named record, then its own
        # live evidence. The relation binds this sequence and binds nothing after
        # it — the deduplication below is what resolves the overlap cases, and no
        # later step reorders to restore it.
        expansion.append(resolved[record.id])
        expansion += evidence
        cited += evidence
    return _HopReach(expansion=tuple(expansion), evidence=tuple(cited), unresolved=unresolved)
