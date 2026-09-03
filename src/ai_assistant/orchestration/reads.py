"""Servicing the read a planner asked for, and the record of every turn (ADR-0226).

ADR-0226 opens one envelope beside the plan: the planner may name **at most one**
read it wanted and did not have, and *the loop* — never the planner and never a
tool — services it into the turn's supply. This module is the servicing half of
that decision (§10's "Lane B"), and it holds three things:

* :func:`service_read_request`, which turns one
  :class:`~ai_assistant.core.types.ReadRequest` into the records ADR-0226 §7
  appends to the supply as a **fourth group**, under §6's single budget of ten and
  its hop-before-query precedence — and, since ADR-0227 §3, returns which of those
  records the **citation hop** reached, because this is the one place the two kinds
  are distinguishable;
* :func:`resolve_label`, §3's whole label scheme — an ordinal into the very
  ``memories`` sequence the loop passed the planner on this call; and
* :func:`emit_read_audit`, §9's record, written **once per turn whether or not the
  trigger fired**.

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

    from ai_assistant.core.protocols import MemoryStore
    from ai_assistant.core.types import MemoryRecord, ReadAsk, ReadRequest

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


@dataclass(frozen=True, slots=True)
class ServicedRead:
    """What one servicing carried into the turn, and what §9 records of it.

    The default instance is the honest record of a turn that serviced nothing —
    every count zero and no failure — which is what a non-firing turn, a declined
    one and a turn whose planner never returned all carry.

    Attributes:
        records: The fourth group, in §6's order: the hop's records first, then the
            sighted query's, each already deduplicated against the pre-servicing
            supply *and* against every record admitted before it (§7). Empty on a
            failed or partial servicing, which "leaves the supply as planning saw
            it" (§5).
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
            range, or naming a record that is no longer live (§3).
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

    records: tuple[MemoryRecord, ...] = ()
    returned: int = 0
    new: int = 0
    deduplicated: int = 0
    labels_unresolved: int = 0
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


async def service_read_request(
    store: MemoryStore,
    request: ReadRequest,
    *,
    supply: Sequence[MemoryRecord],
    audit: TurnReadAudit,
) -> tuple[str, ...]:
    """Service one emission, once, into the fourth group (ADR-0226 §§2, 6, 7).

    **The citation hop is serviced first and the sighted query fills what remains**
    (§6). Its size is bounded by §2's two-label cap where a query can return the
    whole budget on every firing, so ordering the capped read ahead of the uncapped
    one "makes the union the *measured* union in the ordinary case, and gives the
    query up only where a hop genuinely reached ten records". Where the hop exhausts
    the budget the query is serviced with whatever is left, which may be nothing,
    and the truncation is recorded.

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

    **A failure discards everything.** §5 makes the servicing all-or-nothing, so a
    ``MemoryStoreError`` from any read — the hop's ``get_many``, or any band of the
    query's composition — leaves the supply as planning saw it, and the record it
    writes has every count zero. Only ``MemoryStoreError`` is *degraded*, which is
    deliberately the same net
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

    **What the carrier holds** (ADR-0227 §3, §4): the **distinct** ids of the records
    the hop resolved that the turn's supply holds **after** this servicing — in
    ADR-0226 §6's order, first occurrence keeping the place. A record the hop reached
    that the supply already held is deduplicated out of the fourth group, keeps its
    position and **is** in the carrier (ADR-0227 §1's third clause); a record
    ADR-0226 §6's budget cut is not in the supply at all and so is not, which is
    ADR-0227 §4's "the records it cut render nothing at all". It is **empty** on every
    turn that did not fire, whose servicing was declined, whose servicing failed or
    was partial, and whose hop resolved no live record — the same all-or-nothing
    posture §5 gives the supply.

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
            the same sequence for both because §3's label *is* a position in it.
        audit: This turn's record. Its :attr:`TurnReadAudit.read` is written on every
            path out of this function, and :attr:`ServicedRead.records` is the fourth
            group the caller appends.

    Returns:
        ADR-0227 §3's carrier: the distinct ids of the records this turn's citation
        hop reached that the supply holds after this servicing, in ADR-0226 §6's
        order. Empty where nothing was serviced, where the servicing failed, and
        where the hop reached nothing.
    """
    reads = _Reads()
    union = _Union(held={record.id for record in supply}, budget=READ_BUDGET)
    completed: ServicedRead | None = None
    reached: tuple[str, ...] = ()
    resolved_by_hop: tuple[MemoryRecord, ...] = ()
    hop = _ask_of(request, ReadKind.CITATION_HOP)
    query = _ask_of(request, ReadKind.SIGHTED_QUERY)
    # `ReadAsk`'s validator makes a `SIGHTED_QUERY` ask's query non-``None`` (§4),
    # so this reads the guarantee rather than restating it as a policy: there is no
    # branch here for an ask the model refuses to construct.
    statement = None if query is None else query.query
    truncated: list[ReadKind] = []
    unresolved = 0
    try:
        if hop is not None:
            candidates, unresolved = await _hop_records(store, hop, supply=supply, reads=reads)
            resolved_by_hop = candidates
            if union.admit(candidates):
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
            records=tuple(union.admitted),
            returned=union.returned,
            new=len(union.admitted),
            deduplicated=union.deduplicated,
            labels_unresolved=unresolved,
            truncated_kinds=tuple(truncated),
        )
        # ADR-0227 §3's carrier, computed on the success path alone and over
        # `union.held` — which is seeded from the pre-servicing supply and grown by
        # every admission, so membership of it *is* "the supply holds this record
        # after servicing". `dict.fromkeys` is ADR-0227 §4's deduplication with the
        # first occurrence keeping ADR-0226 §6's place: `Provenance.evidence` carries
        # no uniqueness constraint and two labelled records may cite one episode, so
        # the sequence `_hop_records` returns can name one record more than once.
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
        audit.read = completed or ServicedRead(
            failed=True, failed_after_read_returned=reads.returned_any
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

    Attributes:
        trigger: What the trigger did (§8).
        servicing: What became of an emitted request (§5).
        kinds: The kind of each ask, in the order the request carries them.
        read: What the servicing carried, or the default where none ran.
    """

    trigger: TriggerOutcome = TriggerOutcome.NOT_REACHED
    servicing: Servicing = Servicing.NOT_ASKED
    kinds: tuple[ReadKind, ...] = ()
    read: ServicedRead = field(default_factory=ServicedRead)

    def emit(self) -> None:
        """Write this turn's record — see :func:`emit_read_audit`."""
        emit_read_audit(
            trigger=self.trigger,
            servicing=self.servicing,
            kinds=self.kinds,
            read=self.read,
        )


def emit_read_audit(
    *,
    trigger: TriggerOutcome,
    servicing: Servicing,
    kinds: Sequence[ReadKind] = (),
    read: ServicedRead,
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

    Args:
        trigger: What the trigger did (§8).
        servicing: What became of an emitted request (§5).
        kinds: The kind of each ask, in the order the request carries them. Empty
            where no request was emitted.
        read: What the servicing carried, or the default ``ServicedRead`` where none
            ran.
    """
    _log.info(
        READ_AUDIT_EVENT,
        correlation_id=current_correlation(),
        trigger=trigger.value,
        servicing=servicing.value,
        kinds=tuple(kind.value for kind in kinds),
        returned=read.returned,
        new=read.new,
        deduplicated=read.deduplicated,
        labels_unresolved=read.labels_unresolved,
        truncated_kinds=tuple(kind.value for kind in read.truncated_kinds),
        failed=read.failed,
        failed_after_read_returned=read.failed_after_read_returned,
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
) -> tuple[tuple[MemoryRecord, ...], int]:
    """Follow one ``CITATION_HOP`` ask to the records its labels cite (§2, §3).

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
    which is the guarantee ``get_many`` offers and two calls would forfeit.

    **Only the named records' evidence is read** (§3): the hop follows the labelled
    record's own citations and never the citations of a record reached through it —
    "that is iteration, and it is §12's".

    Args:
        store: The store to resolve identifiers against.
        ask: The hop ask. At most two labels (:data:`~ai_assistant.core.types.MAX_HOP_LABELS`),
            followed in the order it names them.
        supply: The sequence the loop passed the planner, which is the label space.
        reads: The servicing's read observer, noted when this call returns records.

    Returns:
        The cited records — labels in the ask's order, each record's evidence in the
        order that record stores it — and how many labels resolved to nothing.

    Raises:
        MemoryStoreError: If the store's read fails. The caller owns the
            degradation (§5).
    """
    labelled = [(label, resolve_label(label, supply)) for label in ask.labels]
    unresolved = sum(1 for _, record in labelled if record is None)
    found = [record for _, record in labelled if record is not None]
    if not found:
        return (), unresolved

    wanted: list[str] = []
    seen: set[str] = set()
    for record in found:
        for identifier in (record.id, *record.provenance.evidence):
            if identifier not in seen:
                seen.add(identifier)
                wanted.append(identifier)
    resolved = await store.get_many(wanted)
    reads.note(len(resolved))

    cited: list[MemoryRecord] = []
    for record in found:
        if record.id not in resolved:
            # §3's third way of resolving to nothing: the label named a record the
            # store no longer holds, so there is nothing here to follow evidence
            # *from*. Counted with the malformed and out-of-range labels, because
            # from the audit's side all three are one population: a label the turn
            # could not honour.
            unresolved += 1
            continue
        cited += [resolved[cite] for cite in record.provenance.evidence if cite in resolved]
    return tuple(cited), unresolved
