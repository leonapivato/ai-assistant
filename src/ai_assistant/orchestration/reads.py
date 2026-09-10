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

**And the fourth kind is the first that leaves the machine** (ADR-0231 §11). A
``WEB_SEARCH`` ask is serviced here too, under the same budget, into the same fourth
group and onto the same record — "no second servicing site, no second budget, no
second audit, no second seam" — and it adds one further position in the order and one
further field. What is genuinely new is that servicing it is an **egress call**: the
query is composed from the turn's own utterance by a :class:`QueryComposer` that
holds no store (§3), the request is bound, ruled on and recorded before any channel
opens (§6), and only a recorded ``ALLOW`` reaches a
:meth:`~ai_assistant.core.protocols.WebSearcher.search` (§9). Every other outcome
declines: nothing is parked, nobody is asked, no credential is read and the budget is
untouched, which is ADR-0226 §5's posture unchanged. The send is deliberately **not**
made through ``ToolInvoker.invoke``, because taking the invoker's route would require
a registry entry and a registry entry would put a search in front of the planner —
the outcome ADR-0231 §5 exists to prevent (§6).

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
from dataclasses import dataclass, field, replace
from datetime import timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.correlation import current_correlation
from ai_assistant.core.errors import AssistantError, MemoryStoreError
from ai_assistant.core.types import (
    ActionRequest,
    CarriedProvenance,
    DestinationTrust,
    MemoryKind,
    PermissionDecision,
    PermissionOutcome,
    PlacementReach,
    QueryRefusal,
    ReadKind,
    SearchNotServiced,
    SearchRefusal,
    SearchSupply,
    SpanCoverage,
    ToolCall,
    rests_on_recorded_external_content,
)
from ai_assistant.orchestration.conversations import BELIEF_KINDS
from ai_assistant.orchestration.origin import SelectionOrigin
from ai_assistant.orchestration.retrieval import assemble_by_band

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        ActionPolicy,
        AuditTrail,
        ConversationStore,
        DestinationTrustStore,
        EgressBinder,
        Fetcher,
        MemoryStore,
        QueryComposer,
        WebSearcher,
    )
    from ai_assistant.core.types import (
        BoundEgressCall,
        CanonicalDestination,
        ConversationSearchDraw,
        FetchRefusal,
        MemoryRecord,
        ReadAsk,
        ReadRequest,
        SourceListing,
        SourceListingEntry,
        StructuredAsk,
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

#: ADR-0240 §4's population: a ``STRUCTURED_READ`` is serviced over episodic records
#: and over no other kind.
#:
#: Episodes because that is the population the envelope cannot otherwise reach and the
#: one milestone 30 is about: the sighted query's kind selection is ``BELIEF_KINDS``,
#: so no read on this envelope has ever reached an episode, and "which conversation was
#: that" is a question about episodes. Fixing the kind here rather than admitting a kind
#: axis also keeps ADR-0237 §5's own caveat off this path — ``select``'s order is keyed
#: on the write stamp for totality over a mixed result, and a read confined to episodes
#: never produces that pair.
#:
#: **The ask carries no kind axis and no band axis** (§4): those are the store's
#: partitioning vocabulary, and a planner writing one would be steering *how* the store
#: is read rather than naming what it wants.
_STRUCTURED_KINDS: Final[tuple[MemoryKind, ...]] = (MemoryKind.EPISODIC,)

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


class SearchDisposition(StrEnum):
    """Why a ``WEB_SEARCH`` ask did not yield records (ADR-0231 §13, ADR-0241 §4, §8).

    **A closed enumeration of exactly eighteen members, each valued by its
    lower-cased name** — ADR-0231 §13's fifteen, ADR-0238 §11's
    :attr:`NOT_ADMITTED`, which supersedes that closure "in that clause's count
    alone" and leaves every other clause of it standing, and ADR-0241's
    :attr:`DEADLINE_EXPIRED` and :attr:`SEARCH_FAILED`, which move ADR-0238 §11's
    count in the same narrow way. **No lane reads that as licence to add a
    nineteenth** — and never free text: the
    shape :class:`TriggerOutcome`,
    :class:`Servicing` and :class:`StopReason` already have in this module, and
    the reason :class:`~ai_assistant.orchestration.origin.SelectionOrigin` is not
    in ``core`` either. **It lives here and not in ``core``** (§13): it crosses no
    subsystem boundary, being the servicer's own account of why a servicing did
    not yield — assembled from a composer refusal, a policy ruling, a budget fact
    and a :class:`~ai_assistant.core.types.SearchRefusal` — and read by nothing
    but the event :func:`emit_read_audit` writes.
    :class:`~ai_assistant.core.types.SearchRefusal` and
    :class:`~ai_assistant.core.types.SearchOutcome` are ``core``'s, because they
    cross the ``WebSearcher`` seam; the mapping from one to the other is this
    package's and is :data:`SEARCH_DISPOSITIONS`.

    **Each member names the stage that produced it** (§9), so no stage's outcome
    is reported as another stage's and none is omitted — while two outcomes of one
    stage an operator would act on identically may share a member, which
    :attr:`NOT_CONFIGURED` is the one case of. Nine causes an operator acts on
    differently is why this is one field and not a boolean: "an unconnected
    account is a provisioning fact, an ungranted recipient is a user act waiting
    to happen, a ``DENY`` is a policy the operator set, a spend refusal is a
    ceiling, a transport failure is an outage, and a response with no declared
    instant is a provider that cannot be attested".

    **A class and nothing else.** No query text, no fragment of one, no length, no
    origin, no host, no address, no title, no snippet, no provider message, no
    exception type and no store detail is anywhere in this vocabulary, so there is
    nowhere in §9's record for one to sit (§13, ADR-0004 §5). What keeps that
    record inside Tier 2 is this clause and not the redaction net.

    **``SearchRefusal.NO_RESULT`` is deliberately not a member** (§13): a search
    that reached the provider and yielded nothing is a *completed* servicing whose
    returned count is zero, which ADR-0226 §9 already records, and calling it a
    disposition would double-count it.
    """

    NOT_CONFIGURED = "not_configured"
    """This deployment has connected no search account (§9, §13).

    Both routes to it are the same fact about the same stage: no searcher is wired
    into the loop at all, and a wired searcher whose
    :meth:`~ai_assistant.core.protocols.WebSearcher.request` answered ``None``
    because no account is connected. A provisioning fact, and the reason a 0% yield
    for this kind "is a true statement about that configuration rather than a
    reading of a trigger"."""

    NO_BUDGET = "no_budget"
    """Fewer than one slot of ADR-0226 §6's ten remained when the search was reached.

    §11: "no request is composed, no ruling is sought and no channel is opened".
    **A branch rather than an outcome the servicing order produces** — the search
    is serviced second, only the one-record local file precedes it, and at least
    nine of the ten slots therefore always remain — so an operator reading zero
    here is reading the servicing order and not a fault (§11, §18 item 7)."""

    NOT_ADMITTED = "not_admitted"
    """``ConversationStore.admit_search`` refused this servicing (ADR-0238 §8, §11).

    **The sixteenth member, and this decision adds exactly one** (ADR-0238 §11):
    "recording that a servicing did not reach a query because ``admit_search``
    refused". It collapses with no existing member — every other one names a stage
    the servicing *reached*, and a refused admission reaches none of them: §8 states
    that where it refuses, "no supply is constructed, no query is composed, no ruling
    is sought, no credential is read and no channel is opened".

    **Three grounds behind one member, and the site cannot tell them apart.**
    ``admit_search`` answers ``None`` where the stored ``calls`` have reached the
    bound, where the id names nothing, and where the conversation is stamped deleted
    (ADR-0238 §8) — and it answers the same value for each, deliberately, because a
    user deleting a conversation should not turn a running turn into an error.
    ADR-0242 §8 records the same limit in terms for the vocabulary it reads this into.

    **The zero bound is this member too, and the split is ADR-0242's and not this
    one's.** ADR-0242 §8 renders a refusal under a bound of ``0`` as
    ``SearchNotServiced.SEARCH_DISABLED`` and one under a positive bound as
    ``NOT_ADMITTED``, discriminated by "the deployment's **own configuration** — a
    ``Settings`` value the servicing site already holds". That discrimination is at
    the *rendering* level: the mapping table in that section names one
    ``SearchDisposition`` for both rows, and §8 closes this enumeration at eighteen
    with ADR-0231's fifteen, this member and ADR-0241's two. So no second member is
    minted here."""

    COMPOSER_DECLINED = "composer_declined"
    """:attr:`~ai_assistant.core.types.QueryRefusal.DECLINED`, carried across."""

    COMPOSER_UNAVAILABLE = "composer_unavailable"
    """:attr:`~ai_assistant.core.types.QueryRefusal.UNAVAILABLE`, carried across."""

    COMPOSER_MALFORMED = "composer_malformed"
    """:attr:`~ai_assistant.core.types.QueryRefusal.MALFORMED`, carried across."""

    COMPOSER_TOO_LONG = "composer_too_long"
    """:attr:`~ai_assistant.core.types.QueryRefusal.TOO_LONG`, carried across."""

    BINDING_FAILED = "binding_failed"
    """``EgressBinder.bind`` refused or raised, or the connection could not be read.

    **No message, no exception type and no store detail** (§13): a fault is an
    operator's fact and the class is the whole of what this Tier 2 event may say
    about one."""

    RULING_CONFIRM = "ruling_confirm"
    """The recorded ruling was ``CONFIRM`` (§9).

    The disposition of every search in a deployment with no standing recipient
    grant, which on ``origin/main`` today is every deployment: the query is Tier 1
    leaving the device, so ``ThresholdActionPolicy``'s disclosure floor fires and
    ADR-0148 §3's route (b) is the only route to an ``ALLOW`` (§9). **It resolves
    in no turn**: no lane resumes it and none treats it as outstanding work, and the
    decision it was recorded under carries no ``execution_id`` and no ``step_id``
    (§6), so no recovery query and no park can reach it.

    **What ADR-0235 §3 adds to that, and what it leaves alone.** That section — the
    surface ADR-0231 §19 deferred, ratified since — makes exactly this row the subject
    of ``establish_recipient_grant``: a recorded ``CONFIRM`` no park holds, with both
    of those fields unset, offered to the user **as history** so they may make the
    recipients standing. So a lane may now *list* one; what stays true is every clause
    ADR-0231 §9 states about the search itself — the turn is over, no lane resumes it,
    it is not outstanding work, and answering it establishes a grant rather than
    performing the search it was about."""

    RULING_DENY = "ruling_deny"
    """The recorded ruling was ``DENY`` (§9) — a policy the operator set."""

    RULING_UNAVAILABLE = "ruling_unavailable"
    """``ActionPolicy`` raised, or the decision could not be recorded (§13).

    Carries no message, no exception type and no store detail, for
    :attr:`BINDING_FAILED`'s reason. A trail that accepted the append and does not
    hand the record back is one that could not record the decision, so it resolves
    here rather than opening a channel on a decision nothing holds."""

    SPEND_REFUSED = "spend_refused"
    """:attr:`~ai_assistant.core.types.SearchRefusal.SPEND_REFUSED`, carried across."""

    TRANSPORT_FAILED = "transport_failed"
    """:attr:`~ai_assistant.core.types.SearchRefusal.TRANSPORT_FAILED`, carried across.

    An outage — a refused connection, a TLS failure, a channel closed mid-response,
    a refused redirect. **No longer a slow provider**: ADR-0241 §4 moves an expiry of
    the seam's own deadline out to :attr:`DEADLINE_EXPIRED`, because an operator
    reading a population cannot act on one field that means both "the provider is
    unreachable" and "the provider is slow" — the first is an outage and the second
    is a bound to size or a provider to change."""

    DEADLINE_EXPIRED = "deadline_expired"
    """:attr:`~ai_assistant.core.types.SearchRefusal.DEADLINE_EXPIRED`, carried across.

    **The seventeenth member** (ADR-0241 §4), carried one for one from the refusal so
    the mapping stays injective and ADR-0231 §13's injectivity clause binds unchanged.
    The elapsed-time bound fired: `Settings.search_call_deadline` expired before the
    search answered.

    **It carries no duration, no bound, no elapsed figure, no query and no origin.**
    ADR-0231 §13's Tier 1 clause and ADR-0004 §5 bind without qualification, and a
    duration in a per-turn event is a fact about the *system* that ADR-0228 §10 has
    already refused to render."""

    PROVIDER_REFUSED = "provider_refused"
    """:attr:`~ai_assistant.core.types.SearchRefusal.PROVIDER_REFUSED`, carried across."""

    RESPONSE_TOO_LARGE = "response_too_large"
    """:attr:`~ai_assistant.core.types.SearchRefusal.RESPONSE_TOO_LARGE`, carried across."""

    UNATTESTED = "unattested"
    """:attr:`~ai_assistant.core.types.SearchRefusal.UNATTESTED`, carried across.

    The response declared no instant this system could read as one, so §10 minted
    nothing rather than substituting a clock of its own (ADR-0092 §3)."""

    SEARCH_FAILED = "search_failed"
    """The searcher itself raised a fault after the ruling (ADR-0241 §8, issue #2112).

    **The eighteenth member, and it closes the enumeration.** A connection record it
    could not read, a ledger claim the trail refused, an authorisation already spent,
    a cancellation it invented with nothing cancelled, or any other ``AssistantError``
    escaping :meth:`~ai_assistant.core.protocols.WebSearcher.search`. Before it, the
    send was the one stage with no member — every other one names a stage the
    servicing reached — so the absence read as an omission every time someone opened
    this vocabulary.

    **One member and not a family**, on :attr:`BINDING_FAILED`'s own rule: it carries
    no message, no exception type and no store detail, so there is nowhere in a Tier 2
    event for one to sit (ADR-0231 §13, ADR-0004 §5). Splitting the send's faults into
    a store one and an authorisation one would put an exception taxonomy into a field
    §13 forbids an exception type in, and would grow every time a new fault class
    reached the seam; ADR-0241 §13 defers the split with what fires it.

    **It is a ``SearchDisposition`` member and not a ``SearchRefusal`` one** (§8).
    Every ``SearchRefusal`` member is a value ``search`` *returns*; these faults are
    raises, and converting them into returns would give the seam a value for
    conditions its caller must be free to see as exceptions.

    **ADR-0226 §5's degradation is unchanged and this is not a second mechanism**: the
    servicing still fails all-or-nothing, the supply is left as planning saw it, every
    count is zero, ``failed`` is true, and nothing raises out of the turn. The
    ``read_request_degraded`` WARNING and its ``refused_by`` class name stay exactly
    where they are — that line answers the per-occurrence question and this member
    answers the population one."""


#: §13's carry-across from the composing seam's vocabulary, **injective** so no two
#: causes are collapsed: "a decline is the composer judging, an unavailable model is
#: an outage, a malformed answer is a model defect, and an over-long one is a bound
#: the operator set", and an operator acts on each differently.
#:
#: Total over :class:`~ai_assistant.core.types.QueryRefusal`, which §18's item 9a
#: asserts over the enum itself so that a member added without an arm fails.
QUERY_DISPOSITIONS: Final[Mapping[QueryRefusal, SearchDisposition]] = MappingProxyType(
    {
        QueryRefusal.DECLINED: SearchDisposition.COMPOSER_DECLINED,
        QueryRefusal.UNAVAILABLE: SearchDisposition.COMPOSER_UNAVAILABLE,
        QueryRefusal.MALFORMED: SearchDisposition.COMPOSER_MALFORMED,
        QueryRefusal.TOO_LONG: SearchDisposition.COMPOSER_TOO_LONG,
    }
)

#: §13's carry-across from the search seam's vocabulary, **injective** for
#: :data:`QUERY_DISPOSITIONS`' reason, over the six members that reach the servicer.
#:
#: :attr:`~ai_assistant.core.types.SearchRefusal.NO_RESULT` is deliberately absent
#: and maps to no disposition at all: a search that reached the provider and yielded
#: nothing is a completed servicing whose returned count is zero, which ADR-0226 §9
#: already records, "and calling it a disposition would double-count it". §18's item
#: 9a asserts that absence over the enum itself, so a lane that adds an arm for it
#: fails.
#:
#: ADR-0241 §4's :attr:`~ai_assistant.core.types.SearchRefusal.DEADLINE_EXPIRED` is
#: carried across one for one like the rest, which is what keeps this mapping
#: injective while the refusal vocabulary gains a seventh member.
SEARCH_DISPOSITIONS: Final[Mapping[SearchRefusal, SearchDisposition]] = MappingProxyType(
    {
        SearchRefusal.SPEND_REFUSED: SearchDisposition.SPEND_REFUSED,
        SearchRefusal.TRANSPORT_FAILED: SearchDisposition.TRANSPORT_FAILED,
        SearchRefusal.DEADLINE_EXPIRED: SearchDisposition.DEADLINE_EXPIRED,
        SearchRefusal.PROVIDER_REFUSED: SearchDisposition.PROVIDER_REFUSED,
        SearchRefusal.RESPONSE_TOO_LARGE: SearchDisposition.RESPONSE_TOO_LARGE,
        SearchRefusal.UNATTESTED: SearchDisposition.UNATTESTED,
    }
)


class StructuredAxis(StrEnum):
    """Which axes one ``STRUCTURED_READ`` ask applied (ADR-0240 §10).

    **A closed enumeration and never free text.** §10 records *what was tried* and
    not what was asked for: a person label is a name, ADR-0004 §5 puts a name at
    Tier 1, and a Tier 2 event carrying one is a leak on a value this system did not
    mint. So this vocabulary names the **class** of each axis and there is nowhere in
    it for an instant, a label, a query or a count of a label's characters to sit —
    the line ADR-0230 §9 drew for a path, sharpened one axis over.

    The query is a member beside the four filter axes because it is the thing that
    decides which of ADR-0237's two reads serviced the ask (§4), so an operator
    reading this field can tell a ``search`` from a ``select`` without a second one.
    """

    WINDOW = "window"
    """The ask bounded the exchange's instant to a :class:`~ai_assistant.core.types.TimeWindow`."""

    PARTICIPANTS = "participants"
    """The ask filtered on who the episode involved."""

    TOPICS = "topics"
    """The ask filtered on what the episode was about."""

    ABOUT_PERSON = "about_person"
    """The ask filtered on whom the record is about — inert until ADR-0239 §11's
    deferral fires, and recorded anyway so that an operator can see it being asked
    for (ADR-0240 §4)."""

    QUERY = "query"
    """The ask carried a query, so it was serviced by ``MemoryStore.search`` rather
    than by ``MemoryStore.select`` (ADR-0240 §4)."""


class StructuredOutcome(StrEnum):
    """What became of a servicing's ``STRUCTURED_READ`` ask (ADR-0240 §10).

    **Five members, and no implementation collapses any two of them.** The two
    not-reached states are separate because they have different causes and different
    fixes — ADR-0230 §9's own reason for keeping an unresolved label and a refusal
    apart: "a deployment blocked for want of a separator learns that its belief
    composition is coming back empty, and one blocked for want of a slot learns that
    its earlier kinds are filling the budget".

    **Recorded over a servicing that completed and absent otherwise** (§10). Where
    the servicing failed, was partial, or was declined under ADR-0226 §5's channel
    scoping, :attr:`ServicedRead.structured` carries ``None`` — the shape ADR-0230 §9
    gave its own refusal field — and what happened is read from ADR-0226 §9's
    existing declined and failure fields beside every count it makes zero. No
    implementation records a completed-servicing outcome for a servicing that did not
    complete, and none reads an absent value as any of the five.
    """

    NOT_ASKED = "not_asked"
    """This servicing's request carried no ``STRUCTURED_READ`` ask."""

    NO_SEPARATOR = "no_separator"
    """The ask was not reached because every record of the supply was ``EPISODIC``
    when the read was reached, so its own episodes would have formed the leading run
    (ADR-0240 §5, ADR-0158 §4). **Recorded in preference to** :attr:`NO_SLOT` where
    both conditions hold: a supply with no separator blocks the read whatever the
    budget holds, where a spent budget is a fact about one turn's other asks."""

    NO_SLOT = "no_slot"
    """The ask was not reached because fewer than one slot of ADR-0226 §6's budget
    remained when the structured read came up (ADR-0240 §5). **A read the budget
    prevented is not a read that found nothing**: no store call was made, so nothing
    was certified and ADR-0240 §6's empty-read fact does not arise."""

    RETURNED_NOTHING = "returned_nothing"
    """The store call ran and returned **no record at all** — ADR-0240 §6's *empty
    structured read*, and the state that satisfies ADR-0228 §2(e)'s second branch. A
    read whose records were all deduplicated out is **not** this: the store returned
    records, and :attr:`RETURNED_RECORDS` is what that is."""

    RETURNED_RECORDS = "returned_records"
    """The store call ran and returned at least one record, whatever the union then
    did with them (ADR-0240 §6, §13 item 7)."""


def not_serviced(  # noqa: PLR0911 — ADR-0242 §8's table has one arm per discriminated row, and collapsing them behind a mapping would hide the two rows a `Settings` value and a `trust_of` answer decide
    disposition: SearchDisposition | None,
    *,
    max_calls: int,
    planned_with_external_content: bool = False,
    trust: DestinationTrust = DestinationTrust.UNCHOSEN,
) -> SearchNotServiced | None:
    """ADR-0242 §8's mapping, computed **at the servicing site** and nowhere else.

    **Total over all eighteen** :class:`SearchDisposition` **members and
    non-injective, and that is the design rather than a compromise** (ADR-0242 §8).
    ``SearchDisposition`` names *the stage that produced the outcome*, for an operator
    reading an audit; :class:`~ai_assistant.core.types.SearchNotServiced` names *the
    act that would change it*, for the user reading a reply. Two dispositions with one
    act behind them are one member, and one disposition with two acts behind it is two
    members. **No lane makes this injective**, restores a stage name to it, or reports a
    ``SearchDisposition`` value to a user.

    **The three discriminating inputs are the three the site already holds** (§7), and
    nothing here derives a value from the plan, the supply's length, the reply, the
    audit, a store read of its own or any content. ``max_calls`` is
    ``Settings.search_calls_per_conversation`` — a deployment configuration, constant
    across every turn and read from no record; ``planned_with_external_content`` is read
    off the binding the request carried; and ``trust`` is the answer ADR-0238 §5 already
    obliges the site to take at the position §5 fixes, **carried here as data rather
    than re-read**.

    **A member minted by a later ADR maps to** ``UNAVAILABLE`` (§8), which is the
    least-claiming member: an unmapped disposition degrades to silence about the reason
    rather than to a wrong reason. The ``case _`` below is that rule, and the totality
    arm over the eighteen is what makes forgetting a *deliberate* mapping a test failure
    rather than a silent ``UNAVAILABLE``.

    Args:
        disposition: What this servicing's ``WEB_SEARCH`` ask resolved to, or ``None``
            where it yielded records, reached the provider and returned none, or where
            no such ask was made.
        max_calls: ``Settings.search_calls_per_conversation``, which is the whole of
            what tells :attr:`~ai_assistant.core.types.SearchNotServiced.SEARCH_DISABLED`
            from :attr:`~ai_assistant.core.types.SearchNotServiced.NOT_ADMITTED` —
            ADR-0236 §4's move: "The two grounds are told apart from the deployment's
            **own configuration** and never from a per-turn record."
        planned_with_external_content: ADR-0181 §4's fact for the request this
            servicing built, or ``False`` where it built none — in which case no
            ``RULING_CONFIRM`` can have been recorded and the value is not read.
        trust: The build-time ``trust_of`` answer for this deployment's search
            destination, or ``UNCHOSEN`` where the servicing never reached that read.

    Returns:
        The member this turn would carry for that disposition, or ``None`` where the
        servicing yielded and there is nothing to say.
    """
    match disposition:
        case None:
            # §6: a servicing that yielded records — and one that reached the provider
            # and found nothing, which `SearchRefusal.NO_RESULT` deliberately makes no
            # disposition at all — carries no member. The assistant looked, and saying
            # it did not would be false.
            return None
        case SearchDisposition.NOT_ADMITTED:
            # §8's one configuration-discriminated row. ADR-0238 §8 makes a bound of
            # `0` mean "no search is serviced in any conversation", so a statement
            # pointing the user at a new conversation would be false there.
            return (
                SearchNotServiced.SEARCH_DISABLED
                if max_calls == 0
                else SearchNotServiced.NOT_ADMITTED
            )
        case SearchDisposition.SPEND_REFUSED:
            return SearchNotServiced.SPEND_EXHAUSTED
        case SearchDisposition.RULING_DENY:
            return SearchNotServiced.DECLINED
        case SearchDisposition.RULING_CONFIRM:
            # §8's three-row split, and the finding that shapes the whole section:
            # `RULING_CONFIRM` is recorded both where no grant covers the recipients at
            # all and where a grant stands but the closed loop is not closed. Those have
            # different acts behind them, the disposition cannot tell them apart, and an
            # explanation derived from it alone would send half of milestone 31's users
            # to the wrong command.
            if not planned_with_external_content:
                return SearchNotServiced.AUTHORISATION_AWAITED
            # **`USER_CHOSEN` here is `UNAVAILABLE` and not `TRUST_MISSING`** (§8): the
            # destination is already chosen, so the trust act is not the answer, and
            # ADR-0238 §5's recorded half is monotone so nothing established now repairs
            # it. Naming an act that cannot help is worse than naming none.
            return (
                SearchNotServiced.TRUST_MISSING
                if trust is DestinationTrust.UNCHOSEN
                else SearchNotServiced.UNAVAILABLE
            )
        case SearchDisposition.DEADLINE_EXPIRED:
            # ADR-0241 §4's member, mapped here by name rather than left to the default
            # (ADR-0242 §10). A search that was begun and stopped, which is what
            # `INTERRUPTED`'s statement says — where `SEARCH_FAILED` is the searcher
            # raising a fault the user has no act for and falls to `UNAVAILABLE` below.
            return SearchNotServiced.INTERRUPTED
        case _:
            return SearchNotServiced.UNAVAILABLE


def earliest(
    held: SearchNotServiced | None, produced: SearchNotServiced | None
) -> SearchNotServiced | None:
    """Fold one servicing's member into the turn's, by ADR-0242 §7's precedence.

    **At most one member is carried per turn**, and where a turn holds more than one
    servicing that recorded a disposition the member carried is the one **earliest in
    ADR-0242 §8's declared order** among them. **The order and not the encounter order
    decides it**: a member is never overwritten by a later servicing's, and an
    implementation carrying the last one it computed is wrong even where every
    individual mapping is right — as is one assigning only while the carrier is
    ``None``, which is why §15's Arm 2b requires *both* orders.

    **A servicing that yields records does not clear a member an earlier one produced**
    (§7). §6's eligibility is stated over the presence of a disposition, and a later
    success does not remove one — so a ``None`` here leaves ``held`` exactly as it was.

    Args:
        held: What the turn carries so far, or ``None``.
        produced: What this servicing computed, or ``None``.

    Returns:
        The one member the turn carries after this servicing.
    """
    if produced is None:
        return held
    if held is None:
        return produced
    order = tuple(SearchNotServiced)
    return min(held, produced, key=order.index)


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
        supplied: ADR-0238 §11's first count: how many records this servicing supplied
            to the composer. Zero where the destination read ``UNCHOSEN``, where no
            ``WEB_SEARCH`` ask was made, and where the servicing was not admitted.
        withheld: ADR-0238 §11's second count: how many records §3's filter — which is
            ``Placement.reach`` and no other axis — kept out of that supply.
        calls: ADR-0238 §11's third count: this conversation's ``calls`` as
            ``admit_search`` left them, and zero where no admission was granted.
            **A count and never an identifier** (§11): the conversation it is about is
            not in this record, and neither is the bound it was compared against.
        disposition: ADR-0231 §13's one added field: the
            :class:`SearchDisposition` a ``WEB_SEARCH`` ask resolved to, where it
            resolved to one, and ``None`` where the search yielded records or where
            this servicing carried no ``WEB_SEARCH`` ask. **A search that reached
            the provider and yielded nothing is neither**: that is a completed
            servicing whose returned count is zero, which ADR-0226 §9 already
            records, so :attr:`~ai_assistant.core.types.SearchRefusal.NO_RESULT`
            maps to no disposition and counting it here would double-count it.
            A **member of a closed enumeration and never free text**, for
            :attr:`refusal`'s reason and ADR-0004 §5's: there is nowhere here for a
            query, a fragment of one, its length, an origin, a host, a title, a
            snippet, a provider message or an exception type to sit. It **rides on
            a failing record too**, exactly as :attr:`refusal` does: §13 enumerates
            the two cases in which the field is empty, and a search that declined
            before a later kind's read raised is neither. **One residue is named
            rather than papered over**: where the *searcher itself* raised a fault
            after the ruling, this field is empty and :attr:`failed` is what says
            what happened, because §13's vocabulary is closed at fifteen with no
            member for a fault at that stage (issue #2112). ADR-0226 §5's
            all-or-nothing degradation is the ratified answer to such a fault, and
            it is a record an operator can read; what it is not is a *ninth cause*
            beside the eight §13 enumerates.
        structured_axes: ADR-0240 §10's first added field: which axes this
            servicing's ``STRUCTURED_READ`` ask applied, in
            :class:`~ai_assistant.core.types.StructuredAsk`'s own field order with
            the query last. **Recorded wherever such an ask was emitted** — serviced
            or lost with a servicing that failed — because it describes the *ask*,
            which is a fact of the plan, exactly as :attr:`kinds` is; empty where no
            such ask was emitted. Members of a **closed enumeration and never free
            text**, so there is nowhere here for an instant, a person label, a topic
            label or a query to sit.
        structured: ADR-0240 §10's second added field: which of five states this
            servicing's ``STRUCTURED_READ`` ask reached, or ``None`` where the
            servicing did not complete. The two answer different questions and
            neither is derivable from the other — the outcome answers *did the read
            work*, the axes answer *what was tried* — and neither can be read off the
            per-servicing counts, which are stated over the whole servicing rather
            than per ask.
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
    disposition: SearchDisposition | None = None
    supplied: int = 0
    withheld: int = 0
    calls: int = 0
    structured_axes: tuple[StructuredAxis, ...] = ()
    structured: StructuredOutcome | None = None
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


class _ServicingFailedError(Exception):
    """A seam's own fault, carried to ADR-0226 §5's one degradation site.

    **It carries the fault's class name and nothing else** (ADR-0004 §5). Not the
    exception, not a chain to it and not a message: ``core/logging.py`` renders
    through ``structlog.dev.ConsoleRenderer``, whose exception formatter is ``rich``'s
    with ``show_locals=True``, so anything reaching a rendered traceback writes the
    raising frames' locals into the log — here the turn's own utterance, the composed
    query, the request and the bound call. ``redact_sensitive`` cannot reach any of
    it: it runs *before* the renderer and over the event dict's keys, and a rendered
    traceback is neither. A class name is Tier 2 and is the whole of what an operator
    needs to tell a connection outage from a refused claim, which is
    ``ThresholdActionPolicy``'s own answer at ``recipient_grant_seam_unreadable``.

    **Not an error class and not on any contract**: it is module-private, it is
    never raised across a call this package does not make, and it adds nothing to
    ``core/errors.py`` — which ADR-0231 forbids in terms. What it does is let one
    kind's fault reach :func:`service_read_request`'s degradation without widening
    the net for the other three, whose seams raise nothing this handler does not
    already state (ADR-0230 §4 for the fetch; ``MemoryStoreError`` for the hop and
    the query).

    **Why a search needs it and the other kinds do not.** ADR-0231 §17 gives the
    ``WebSearcher`` seam the same raise-for-no-source-reason posture ``Fetcher``
    has, so a refused admission, a failed transport, an over-large response and an
    unattested one are all :class:`~ai_assistant.core.types.SearchRefusal` members.
    But the concrete searcher performs ``ToolInvoker.invoke``'s own machinery
    (ADR-0231 §6) and raises for the **faults** that machinery raises for — a
    connection record that could not be read (ADR-0148 §6's fail-closed limb), a
    ledger claim the trail refused, an authorisation already spent, a cancellation
    it invented with nothing cancelled (ADR-0241 §7). Those are not source reasons
    and have no ``SearchRefusal`` member, and ADR-0231 §17 gives the seam none for
    them: converting a raise into a return would hand the seam a value for
    conditions its caller must be free to see as exceptions (ADR-0241 §8).
    ADR-0226 §5 settles what happens to them: "a servicing failure degrades the
    turn and never fails it", all-or-nothing, "the records that did come back are
    discarded with the rest" — which is exactly the record the ``finally`` below
    writes.

    **What has changed since is the audit and not the degradation** (ADR-0241 §8,
    issue #2112). §13's vocabulary was closed with no member for a fault at the
    send; it now carries :attr:`SearchDisposition.SEARCH_FAILED`, which the
    degradation site records. This class is unaffected: it is still how the fault
    reaches that site without this frame holding the exception.

    Attributes:
        fault: The class name of the fault the seam raised.
    """

    def __init__(self, fault: str) -> None:
        """Carry one fault's class to the degradation site.

        Args:
            fault: ``type(exc).__name__`` of the fault the seam raised. A class, and
                never the exception, for the reason above.
        """
        super().__init__(fault)
        self.fault = fault


@dataclass(slots=True)
class _SearchCounts:
    """ADR-0238 §11's three counts, written as each stage completes.

    **Written rather than returned**, which is :class:`_Reads`'s own shape and is here
    for the same reason: a fault the searcher raised *after* the ruling unwinds past the
    call that would have returned them (ADR-0226 §5's degradation, issue #2112), and a
    record reporting that such a servicing admitted no call and composed over nothing
    would be false of one that did both. The durable counter has already moved by then —
    ADR-0238 §8's "an admitted call is consumed whatever the outcome" — so the audit and
    the record must agree about it.

    Attributes:
        supplied: How many records were supplied to the composer.
        withheld: How many ADR-0238 §3's filter kept out of that supply, which is
            ``Placement.reach`` and no other axis.
        calls: This conversation's ``calls`` as ``admit_search`` left them, and zero
            where no admission was granted.
    """

    supplied: int = 0
    withheld: int = 0
    calls: int = 0


@dataclass(frozen=True, slots=True)
class _Searched:
    """What one ``WEB_SEARCH`` ask produced, in the two shapes the servicing needs.

    Attributes:
        records: The records §10 minted, in the order it minted them, offered to
            :class:`_Union` exactly as every other kind's candidates are. Empty on
            every non-yield.
        disposition: §13's field for this servicing, or ``None`` where the search
            yielded records and where it reached the provider and returned none —
            the two cases §13 leaves the field empty for, once this class is only
            constructed for a servicing that carried the ask at all.
        not_serviced: ADR-0242 §7's carrier for this servicing — which **class of act**
            would have let the search happen, computed **here at the servicing site**
            from :attr:`disposition` and the three values this site already holds, and
            ``None`` exactly where :attr:`disposition` is. It is never recomputed
            downstream and never inferred at a render site (§7).

            **Two vocabularies over one event** (§8): :attr:`disposition` names the
            stage for an operator reading the audit, and this names the act for the
            user reading the reply. ADR-0242 §11 keeps this one **out** of the audit —
            a member computed for a user is not a second spelling of a fact the audit
            already records, and writing both would make the two drift.
    """

    records: tuple[MemoryRecord, ...]
    disposition: SearchDisposition | None
    not_serviced: SearchNotServiced | None = None


@dataclass(frozen=True, slots=True)
class StructuredFacts:
    """ADR-0240 §8's three facts, on their way from the servicer to the render site.

    **Three facts and they are separate.** Each is given on its own condition, any two
    or three are given together where their conditions hold together, and **none is
    inferred from another**. They travel as one value rather than as three parameters
    because they are computed at one place and read at one place, and a triple that
    could come apart between them is a triple one edit can put out of step.

    **Carried inside ``ai_assistant.orchestration``**, from the component that knows
    them to the render site, as data (§8). They add **no field to a ``core`` type**, no
    member to a Protocol, and none is inferred at the render site — not from the plan,
    not from the supply's length, not from the audit. That is ADR-0228 §10's rule and
    ADR-0227 §3's, applied to three more facts for their own reason.

    **No fact carries a window, an instant, a label, a query, a count or a kind
    name.** The temporal fact says *which instant the filter was on*, which is a
    property of the field rather than a value read off the ask, so this value is three
    booleans and has nowhere for anything else to sit.

    **The default instance is the answer for a turn with no structured read at all**,
    on which the composing stage receives nothing and the assembled prompt is
    byte-identical to what it is without this decision.

    Attributes:
        reach: Whether any structured read the turn performed applied a
            ``participants``, ``topics`` or ``about_person`` axis — the fact that such
            a read reached only records carrying a recorded value on the axes it
            filtered. It is what discharges ADR-0237 §6's third clause and ADR-0239
            §6's third clause for this consumer, and no lane reads either as
            discharged by anything else or as discharged only where a read came back
            empty. **Given whether or not the read returned records**: a read that
            returned records excluded every unlabelled record just as an empty one
            did.
        temporal: Whether any structured read the turn performed applied a window —
            the fact that such a read filtered on the instant of the *exchange* rather
            than of the event (ADR-0237 §8). A **window-only** read owes no
            :attr:`reach` fact and does owe this one: this kind reads episodes, every
            episodic record carries the ``occurred_at`` a window filters on, and
            ADR-0237 §6's obligation is about records carrying *no* value on the axes
            the read filtered.
        empty: Whether the turn's **last structured read** was empty in ADR-0240 §6's
            sense — the last read of *this kind*, not the last servicing: a later
            servicing that performed no structured read, or whose read §5 blocked,
            establishes nothing and leaves this fact where the last read that ran put
            it. Keyed on the last read where the other two range over the turn,
            because it is a fact about *the answer being composed*: a turn that
            broadened and found records has an answer and needs no note about the path
            it took there.
    """

    reach: bool = False
    temporal: bool = False
    empty: bool = False

    def __bool__(self) -> bool:
        """Whether this turn is given any of the three facts at all.

        The render site's own question — ADR-0240 §8's clause that "on a turn given
        none of the three facts the composing stage receives nothing, and the
        assembled prompt is byte-identical to what it is today" — asked once here
        rather than re-spelled as a three-way disjunction wherever it is needed.

        Returns:
            Whether any of the three facts holds.
        """
        return self.reach or self.temporal or self.empty


@dataclass(frozen=True, slots=True)
class ServicedCarriers:
    """What one servicing hands back that ADR-0226 §9's record deliberately does not.

    Four facts, of two classes, returned rather than written onto
    :class:`TurnReadAudit` for one reason stated twice: that record "copies no text"
    and carries "no identifier but the correlation id" (ADR-0226 §9), and ADR-0240
    §10 keeps every value on every axis out of it. :attr:`hop_reached` carries record
    identifiers and :attr:`empty_read` carries the planner's own composed ask, so
    neither belongs on a Tier 2 log surface whose whole discipline is that they are
    not there.

    **The default instance is the honest answer for a servicing that established
    nothing** — one that did not fire, was declined, failed, or was partial — which
    is the same all-or-nothing posture ADR-0226 §5 gives the supply.

    Attributes:
        hop_reached: ADR-0227 §3's carrier — the **distinct** ids of the records this
            servicing's citation hop reached that the supply holds after it, in
            ADR-0229 §3's order.
        empty_read: ADR-0240 §7's carrier — the ``STRUCTURED_READ`` ask this
            servicing performed that returned **no record at all**, carried back byte
            for byte as the planner emitted it, or ``None``. A read the budget did not
            reach, one the supply's shape blocked, one whose records were merely
            deduplicated out, and a servicing that failed all leave it ``None`` (§5,
            §6).
        structured_ran: Whether this servicing's ``STRUCTURED_READ`` ask reached the
            store at all — ``False`` where the request carried none, where §5's
            separator condition blocked it and where the budget left no slot. It is
            what makes ADR-0240 §8's emptiness fact a statement about **the turn's last
            structured read** rather than about its last servicing: a later servicing
            that performed no structured read establishes nothing about the store, so
            it neither sets that fact nor clears one an earlier read established.
        label_filtered: ADR-0240 §8's **reach** fact for this servicing: whether its
            structured read applied a ``participants``, ``topics`` or ``about_person``
            axis, **whether or not that read returned records**. A read that returned
            records excluded every unlabelled record just as an empty one did, so the
            obligation does not turn on the yield.
        window_filtered: ADR-0240 §8's **temporal** fact for this servicing: whether
            its structured read applied a window, again whatever it returned. A
            window-only read owes no reach fact and does owe this one — every
            episodic record carries the ``occurred_at`` a window filters on, so there
            is nothing such a read failed to reach for want of a value.
        not_serviced: ADR-0242 §7's carrier: which class of act would have let this
            servicing's search happen, or ``None`` where it yielded, where it reached
            the provider and found nothing, and where the request carried no
            ``WEB_SEARCH`` ask. **Computed at the servicing site** by the component that
            recorded the disposition, and carried from there to the composing stage as
            data — the shape ADR-0228 §10 fixes for its own fact and this class already
            has for three more.

            **It rides on the failing record's carriers too**, exactly as the
            disposition does: a servicing whose searcher raised after the ruling carries
            ``UNAVAILABLE`` here, and dropping it would report that turn as one whose
            planner never asked for a search.
    """

    hop_reached: tuple[str, ...] = ()
    empty_read: ReadAsk | None = None
    structured_ran: bool = False
    label_filtered: bool = False
    window_filtered: bool = False
    not_serviced: SearchNotServiced | None = None


@dataclass(slots=True)
class SearchFooting:
    """One conversation's ADR-0238 footing, for the turn being serviced.

    **The three facts §5's condition is decided from that live outside this turn** —
    the destination's recorded trust, the conversation's stored footing flag, and its
    call allowance — held beside the facts that live inside it: which of this turn's
    records were minted by a ``WEB_SEARCH`` servicing at a destination of recorded
    trust ``USER_CHOSEN``, and which of them are episodes of this conversation. It is
    **per turn** rather than per process, because those sets are, and because the
    conversation it is about is the turn's.

    **It is a value the loop threads, not a seam.** It names no capability, is
    registered nowhere and adds no route: ADR-0238 §14 rules that the lane "wires the
    trust store into the one servicing site and into nothing else, holds no reference
    to it in any other subsystem, and adds no second caller", and this object is what
    makes that one site reachable from the one place a turn is run.

    **Every judgement it makes about the budget is one of the four calls ADR-0238
    admits**, and it makes no other:
    :meth:`~ai_assistant.core.protocols.DestinationTrustStore.trust_of`, and
    ``ConversationStore``'s :meth:`admit_search`, :meth:`search_draw` and
    :meth:`observe_search`. The one further read it takes decides no part of the budget
    and adds no member to any Protocol: :meth:`resolve_episodes` asks ADR-0074 §9's
    ``turn_of_episode`` which conversation an episode belongs to, which is §2's
    population question and not §8's. It reads no ``Settings`` — §8 puts the bound in
    the caller's hands and this object *is* where the caller's judgement about it is
    carried — holds no clock, and mints nothing.

    Attributes:
        conversation_id: The conversation this turn runs under.
        conversations: The durable conversation index, the **same** instance the
            capture stage holds. ADR-0238 §8 puts the counter and the flag on the
            conversation record precisely so that one object's own per-conversation
            exclusion is what makes the increment atomic; a second store over the same
            rows would serialise nothing (ADR-0074 §9).
        trust: What the user recorded about destinations (ADR-0238 §1). Consulted
            twice per servicing and never cached across the composition, for the
            reason §5 states.
        destinations: The canonical destination set a search of this deployment would
            bind to, or **empty** where it connected no search account — which is not
            a special case, because ADR-0238 §1 answers ``UNCHOSEN`` for an empty
            sequence and a deployment with no account services no search anyway.
        max_calls: ``Settings.search_calls_per_conversation``, passed to
            ``admit_search`` rather than read by it (ADR-0238 §8: "every judgement
            about what a bound is stays in ``orchestration``").
    """

    conversation_id: str
    conversations: ConversationStore
    trust: DestinationTrustStore
    destinations: tuple[CanonicalDestination, ...]
    max_calls: int
    #: The ids of records **this turn's** ``WEB_SEARCH`` servicings minted at a
    #: destination of recorded trust ``USER_CHOSEN`` — ADR-0238 §2's third admissible
    #: population. It is a per-turn set because ADR-0231 §16 makes a minted id resolve
    #: in no store and no later turn reach it: "a second turn re-searches … because
    #: nothing was retained", so no id in here is ever seen again.
    #:
    #: **It is not the only recorded external span §5's third condition tolerates**, and
    #: an earlier revision of this comment said it was. What a later turn has instead is
    #: §2's own answer — "the captured episode … **that** is what resolves *find more
    #: about that* across turns" — which reaches this turn through
    #: :attr:`conversation_episodes` and not through here, and which §15 Arm 1b requires
    #: to rule ``ALLOW``. A conversation that searched yesterday is admitted by the
    #: **recorded** half having vouched for yesterday, not by this set; what stays
    #: refused is a conversation whose flag is down, which §8 makes monotone.
    minted_user_chosen: set[str] = field(default_factory=set)
    #: The ids of ADR-0238 §2's **first** population alone: "episodes of this
    #: conversation that ``orchestration`` selected into the turn's supply". The loop
    #: seeds it with the conversation tail and :meth:`resolve_episodes` adds every other
    #: episode in the supply the index says is this conversation's.
    #:
    #: **Membership is the index's fact and never the record's**, which is ADR-0074
    #: §10's own position: "conversation membership lives in this index and not as a
    #: ``conversation_id`` field on ``EpisodicMemory``, so that an episode belonging to
    #: no conversation is the *default* shape rather than a permitted exception". So it
    #: is a set the loop was handed, never a predicate over content, a stage or a stamp.
    #:
    #: Recorded apart from :attr:`selected` because :meth:`clean` tells the two
    #: populations apart and :func:`_search_supply` does not: an episode of *this*
    #: conversation is a record whose externality this conversation's own stored flag
    #: has **already** answered (§8's capture fold), and a ``MemoryRecord`` retrieval
    #: selected — §2's second population — is not, whatever it carries.
    conversation_episodes: set[str] = field(default_factory=set)
    #: The ids of the records ADR-0238 §2's **first two** populations contributed to this
    #: turn: "episodes of this conversation that ``orchestration`` selected into the
    #: turn's supply" and "the ``MemoryRecord`` values the turn's retrieval and episodic
    #: supplement selected". Written once, by the loop, from the supply it assembled
    #: before the first planner call — which is the one component that knows which stage
    #: a record came from, and the reason this is a recorded set rather than a predicate.
    #:
    #: **A stamped episode of an earlier turn is in here**, and §2 is explicit that it
    #: should be: "what a later turn has instead is the captured episode … **that** is
    #: what resolves *find more about that* across turns". Whether such an episode also
    #: prevents *closed-loop* authorisation is §5's separate question, answered by
    #: :meth:`clean` over :attr:`conversation_episodes`, and conflating the two would
    #: delete the milestone's own exit sentence in the name of enforcing it.
    selected: set[str] = field(default_factory=set)
    #: Whether this turn has already folded ``False`` onto the record. §8's early fold
    #: "writes ``False`` and nothing else, it is idempotent, and repeating it costs
    #: nothing" — so repeating it is *correct*, and this guard buys a bounded number of
    #: store writes rather than a property.
    _lowered: bool = False

    def clean(self, record: MemoryRecord, /) -> bool:
        """Whether ``record`` is one ADR-0238 §5's third condition tolerates.

        True in three cases: the record carries no recorded external span at all; the
        span it carries was minted by one of *this turn's* ``WEB_SEARCH`` servicings at
        a destination of recorded trust ``USER_CHOSEN``; or the record is an episode of
        **this conversation** the loop selected into the turn's supply (§2's first
        population, :attr:`conversation_episodes`).

        **The third case is §5's own sentence rather than an exception to it.** The
        current-turn half asks whether every recorded external span in view "was minted
        by a ``WEB_SEARCH`` servicing at a destination of recorded trust
        ``USER_CHOSEN``". For an episode of *this* conversation that question has
        already been answered — by the same predicate, the same component and the same
        data, at the capture of the turn that episode records — and the answer is the
        conversation's stored ``all_external_user_chosen`` flag, which §5's **recorded**
        half reads. So this half does not re-derive it; the recorded half carries it,
        and §5's closing paragraph is what reserves this half for the other case: "a
        turn may read a file and *then* reach the search" — a span **this** turn
        introduced, which no record vouches for yet. Where the earlier span came from
        anywhere but a chosen search the flag is already ``False`` and §8 makes it
        monotone (Arms 6e, 6f), so nothing is reopened — and what this makes reachable
        is §15 Arm 1b, the exit's cross-turn arm, which without it is refused
        (`#2205 <https://github.com/leonapivato/ai-assistant/issues/2205>`_).

        **Still blind to why a record is external** (§5). Nothing here asks what
        stamped a record: the third case is decided from *membership* — which turns the
        conversation index records as this conversation's (:meth:`resolve_episodes`) —
        and never from the cause of a stamp, which is what ADR-0223 §6 requires of any
        clause reaching ADR-0181 §5's floor. A stamped episode of some **other**
        conversation, and any ``MemoryRecord`` retrieval selected, fail this predicate
        exactly as a fetched page does, whatever their provenance says.

        **It reads a recorded fact and never content** (§5, §12): the predicate is
        ``rests_on_recorded_external_content`` over the record's own provenance and
        membership of two sets this component was handed by the one component that knows
        which stage a record came from. No model output, no query, no reply and no
        record's text contributes.

        Args:
            record: One record in view of this turn.

        Returns:
            Whether it leaves the conversation's footing intact.
        """
        return (
            not rests_on_recorded_external_content(record.provenance)
            or record.id in self.minted_user_chosen
            or record.id in self.conversation_episodes
        )

    async def resolve_episodes(self, records: Sequence[MemoryRecord], /) -> None:
        """Add every episode of **this** conversation in ``records`` to §2's first population.

        **The tail is not the population; the index is.** The loop can name the
        conversation tail without a read, because
        :meth:`~ai_assistant.orchestration.conversations.ConversationLifecycle.history`
        walked this conversation's index rows to build it — but §2's population is
        "episodes of this conversation that ``orchestration`` selected into the turn's
        supply", and ADR-0158 §3's episodic supplement selects episodes too, including
        ones that have fallen out of ADR-0074 §9's replay window. Deciding those by the
        stage they arrived through would refuse a conversation its own distant past and
        leave §15 Arm 1b unreachable for exactly the long conversation the milestone is
        about. So membership is resolved where ADR-0074 §10 puts it: ``turn_of_episode``,
        which "the store owes both directions of" precisely so that no caller infers it.

        **A read only for a record that would otherwise fail** :meth:`clean`. An episode
        carrying no recorded external span passes on the first disjunct whatever the
        index says, so asking about it would buy nothing — which is what keeps the cost
        at zero for the turns that carry nothing tainted, and bounded by the supply's
        stamped episodes otherwise.

        **Not one of ADR-0238's four store calls, and it is not a fifth budget member.**
        §8 adds three members to ``ConversationStore`` and rules that "a fourth is added
        by no lane without the ADR that decides it"; this adds none — ``turn_of_episode``
        is ADR-0074 §9's, already declared, already conformance-tested. §14's
        no-second-caller restraint is stated over the **trust** store and is untouched
        here.

        **A store fault leaves the record out**, which is the fail-closed direction: an
        episode this method could not place stays §2's second population and costs the
        conversation its footing, exactly as it does today. The turn is not failed for
        it, which is the posture :meth:`_fold` and ``ConversationLifecycle.history``
        already take toward this store.

        Args:
            records: The turn's pre-servicing supply.
        """
        for record in records:
            if record.id in self.conversation_episodes or not rests_on_recorded_external_content(
                record.provenance
            ):
                continue
            if MemoryKind(record.kind) is not MemoryKind.EPISODIC:
                continue
            try:
                turn = await self.conversations.turn_of_episode(record.id)
            except AssistantError as exc:
                # The class and nothing else, for the reason `_fold` states: this
                # frame's locals carry the conversation's id and the deployment's
                # destinations, both Tier 1 (ADR-0238 §11).
                _log.warning("search_footing_membership_degraded", error=type(exc).__name__)
                continue
            if turn is not None and turn.conversation_id == self.conversation_id:
                self.conversation_episodes.add(record.id)

    async def trusted(self) -> DestinationTrust:
        """What the store records about this deployment's search destination (§1).

        Consulted **before** the supply is built, because ADR-0238 §2 and §3 make it
        the fact that decides whether records may enter a ``SearchSupply`` at all —
        and §5 is explicit that "that earlier answer decides only *what may be composed
        over*, and no clause reads it as deciding what may be sent". The answer that
        decides the second closed-loop condition is a **separate** call taken at build
        time; see :meth:`~SearchServicer.service`.

        Returns:
            The recorded trust, ``UNCHOSEN`` where nothing is recorded. Never raises:
            ADR-0238 §1 rules the trust ``UNCHOSEN`` "where a record cannot be read",
            so the one read a policy path depends on fails *closed* by answering.
        """
        return await self.trust.trust_of(self.destinations)

    async def admit(self) -> ConversationSearchDraw | None:
        """Spend one call of this conversation's allowance, or refuse (§8).

        **One atomic step** the store owes — compare, increment, answer — and there is
        nothing outstanding afterwards to settle, release or reconcile. The draw it
        answers is deliberately **not** carried forward into §5's third condition: §5
        forbids that in terms, and :meth:`footing` is what the request is built from.

        Returns:
            The draw as it stands after the increment, or ``None`` where the bound was
            reached, the id names nothing, or the conversation is stamped deleted.
        """
        return await self.conversations.admit_search(self.conversation_id, max_calls=self.max_calls)

    async def footing(self) -> bool:
        """§5's **recorded** half, read at the moment the request is built.

        "One read and no disjunction": satisfied where ``search_draw`` answers a draw
        whose ``all_external_user_chosen`` is true, and by nothing else. ``None`` — an
        id that names nothing, or a conversation stamped deleted — fails it, which is
        the fail-closed direction and the reason §8 could delete an earlier revision's
        second limb.

        **Read here and not earlier**, and no value read earlier in the servicing is
        reused: a read taken at admission would be separated from the binding by the
        composition itself, and a fold that committed in between would be ignored by a
        request built after it. The flag is monotone, so reading it as late as possible
        is strictly the fail-closed direction.

        Returns:
            Whether the conversation's stored footing is intact.
        """
        draw = await self.conversations.search_draw(self.conversation_id)
        return draw is not None and draw.all_external_user_chosen

    async def admitted(self, records: Sequence[MemoryRecord], /) -> None:
        """§8's **early** fold: lower the flag as soon as a dirty span is admitted.

        The trigger is the admission — "the same fact §5's current-turn half is stated
        over" — and it fires **whether or not that turn ever builds a ``WEB_SEARCH``
        request**. Folding here rather than at capture puts the ``False`` on the record
        as early as the fact exists, which narrows the window §8 states from the whole
        of a turn to a single store write.

        **Only ``False`` is ever written early.** Reporting a turn *clean* stays
        capture's alone, because only capture sees the turn's final supply; an early
        true would report a turn clean before it had finished carrying things.

        **A store fault is swallowed**, exactly as ADR-0238 §8 has the store answer
        rather than raise at the two lifecycle edges: a conversation the user deleted
        mid-turn must not turn a running turn into an error, and the fold's failure
        leaves a flag that is *higher* than the truth for this conversation — which is
        the residue §8 names, bounded by the build-time read that follows it.

        Args:
            records: The records just admitted to this turn.
        """
        if self._lowered or all(self.clean(record) for record in records):
            return
        self._lowered = True
        await self._fold(all_external_user_chosen=False)

    async def observe(self, records: Sequence[MemoryRecord], /) -> None:
        """§8's capture fold, over the turn's **final** supply.

        "For every turn it captures, ``orchestration`` calls ``observe_search`` with
        whether **every** recorded external span that turn's final supply carried was
        minted by a ``WEB_SEARCH`` servicing at a destination of recorded trust
        ``USER_CHOSEN``" — computed here from records this component holds as data it
        fetched, by the same predicate and at the same instant as ADR-0223 §1's own
        value. **Capture's fold remains and is unchanged; the early one is earlier, not
        instead**, and the two agree because ``observe_search`` folds by **and**.

        Args:
            records: The turn's final supply.
        """
        await self._fold(all_external_user_chosen=all(self.clean(record) for record in records))

    async def _fold(self, *, all_external_user_chosen: bool) -> None:
        """Fold one observation onto the record, or degrade (§8).

        Raises nothing a turn can see. ``observe_search`` itself "does nothing and
        raises nothing" for an id that names nothing and for a conversation stamped
        deleted, so what this catches is a store *fault* — and a turn whose answer the
        user already has is not failed for a footing write, which is the posture
        ``ConversationLifecycle.capture`` takes for the record itself.

        Args:
            all_external_user_chosen: The value to fold in by logical **and**.
        """
        try:
            await self.conversations.observe_search(
                self.conversation_id, all_external_user_chosen=all_external_user_chosen
            )
        except AssistantError as exc:
            # **The class and nothing else**, and no traceback (ADR-0004 §5, ADR-0238
            # §11). A rendered traceback carries this frame's locals, and this frame's
            # locals are a ``SearchFooting`` — the conversation's id and the deployment's
            # destination set, both Tier 1 — so ``exc_info`` would put behind an operator
            # log exactly what §11 spent a clause keeping out of the audit event. The
            # class is what an operator acts on; the identifier is not.
            _log.warning("search_footing_fold_degraded", error=type(exc).__name__)


class SearchServicer:
    """The five contracts one ``WEB_SEARCH`` servicing is answered against (§5, §6).

    **A wiring value and not a seam.** It names no capability of its own, is
    registered nowhere, and adds no route: it is the composition root's statement
    that this deployment connected a search account, holding the objects ADR-0231
    §6 names in the order that section performs them. A deployment that connected
    none holds no instance at all, and :func:`service_read_request` is handed
    ``None`` — which is §13's :attr:`SearchDisposition.NOT_CONFIGURED`, stated by a
    caller rather than defaulted, exactly as the ``fetcher`` parameter is.

    **The one call site of ``WebSearcher.request``, and the one caller of
    ``search``** (§11). ``app/composition.py`` wires the searcher into this object
    and into nothing else, no other subsystem holds the reference, and §17's
    no-second-servicing-site clause is what keeps that true.

    **The id and the clock are the recorder's** (ADR-0021 §3, ADR-0059 §1): the
    policy is withheld both, which is what leaves ``decide`` a genuine function of
    its argument. They are **passed rather than defaulted**, so a deployment states
    the clock its audit rows are stamped from instead of inheriting one, and the
    root passes the same pair every other seam it wires reads.
    """

    def __init__(  # noqa: PLR0913 — one parameter per contract ADR-0231 §6 names, plus the recorder's id and clock and ADR-0241 §3's deadline; the two sections fix the list
        self,
        *,
        composer: QueryComposer,
        searcher: WebSearcher,
        binder: EgressBinder,
        policy: ActionPolicy,
        trail: AuditTrail,
        now: Clock,
        id_factory: Callable[[], str],
        deadline: timedelta,
    ) -> None:
        """Wire one search servicing from the contracts ADR-0231 §6 names.

        Args:
            composer: Writes the query, from the turn's own utterance and from
                nothing else (§3). Handed one positional argument, which is the
                whole of the utterance-only safety claim.
            searcher: Proposes the act and, once it is authorised, performs it
                (§17). This object is its only caller.
            binder: Derives the ``EgressBinding`` whole, before the ruling
                (ADR-0148 §1, ADR-0152 §1). It accepts no part of the binding.
            policy: Rules on the request (§9). The **same object** the step runner
                rules with, so one deployment has one set of thresholds and one
                recipient-grant seam rather than two that could disagree.
            trail: Records the ``PermissionDecision`` before any channel opens
                (§6). The same object the runner and the ledger hold, for
                ADR-0192 §1's reason: the ledger requires the decision it is passed
                to equal the one the store holds under that id.
            now: The clock the recorded decision is stamped from, guarded once
                here (ADR-0026 §4).
            id_factory: Mints the decision's id (ADR-0021 §3).
            deadline: ``Settings.search_call_deadline`` — the bound this site passes
                as ``timeout`` on **every** :meth:`WebSearcher.search` (ADR-0241 §3).
                Read by the composition root and passed here rather than read below
                ``orchestration``: the same construction ADR-0238 §12 gives the call
                ceiling, so nothing a model produced, a request carried or a result
                contained can reach the comparison, and no component raises, extends,
                resets, suspends or re-reads it on account of a turn's content.
                **Passed rather than defaulted**, for the clock's reason: a bound the
                milestone's exit is stated over may not be inherited.

        Raises:
            ValueError: If ``deadline`` is not a strictly positive ``timedelta``.
                ``Settings`` already refuses one at load; this is the guard at the
                seam a test or a dynamically-wired caller can reach directly, and it
                fires here rather than at the first search (ADR-0241 §1).
        """
        self._composer = composer
        self._searcher = searcher
        self._binder = binder
        self._policy = policy
        self._trail = trail
        self._now = checked_clock(now, owner="SearchServicer")
        self._id_factory = id_factory
        if not isinstance(deadline, timedelta) or deadline <= timedelta(0):
            msg = (
                f"deadline must be a strictly positive timedelta "
                f"(ADR-0241 §1, §3); got {deadline!r}"
            )
            raise ValueError(msg)
        self._deadline = deadline

    async def service(  # noqa: C901, PLR0911, PLR0913 — one exit per stage ADR-0231 §9 names as a decline (§13 requires the member to name the stage that produced it, so collapsing any pair would report one stage's outcome as another's), and one parameter per thing ADR-0238 §5's four conditions are decided from
        self,
        utterance: str,
        *,
        remaining: int,
        external: bool,
        footing: SearchFooting,
        in_view: Sequence[MemoryRecord],
        counts: _SearchCounts,
    ) -> _Searched:
        """Compose, bind, rule, record and send — in that order and no other (§11).

        **No channel is opened before a recorded ``ALLOW`` exists, and no query is
        composed after the ruling**: the ruling is over the request the query is
        in, which is ADR-0148 §6's determinism and ADR-0150 §4's binding read
        forward. Composing first costs the composer's model call on a turn whose
        search is then refused — a real cost, paid by every deployment with no
        grant — and the alternative costs correctness, which is not a trade this
        corpus makes. §13's disposition is what makes the cost visible.

        **Every non-``ALLOW`` declines, and declining is not failing** (§9). On a
        ``CONFIRM``, a ``DENY``, a binder that refused or raised, a policy that
        raised or a trail that could not record the decision: no channel is opened,
        no credential is read, no record is minted, the read budget is untouched,
        and this kind yields nothing. **Nothing is parked and nobody is asked** —
        ADR-0226 §5's clause binds unchanged, and a recorded ``CONFIRM`` here
        resolves in no turn: the decision carries no ``execution_id`` and no
        ``step_id`` (§6), so ``AuditTrail.pending_confirmation``'s
        ``(execution_id, step_id)`` query cannot reach it, no park holds it, and
        nothing about this turn waits on it. **ADR-0235 §3 is where such a row is
        offered to the user afterwards** — as *history*, for the establishing act,
        which is the surface ADR-0231 §19 deferred by name — and that changes nothing
        here: the servicing asked nobody, parked nothing and is over.

        **The send is not made through ``ToolInvoker.invoke``** (§6). Taking the
        invoker's route would require putting the search in a ``ToolRegistry``, and
        that would put its capability in front of the planner — the outcome §5
        exists to prevent. So the ``ToolCall`` this method constructs is handed to
        the searcher, which owns everything after it: ADR-0029 §2's three
        pre-execution checks, ADR-0194's spend admission, the credential read and
        ADR-0192's claim and completion. **This package claims nothing.**

        **What ``request`` receives is the composer's own output, byte for byte**
        (§11): nothing here repairs, extends, truncates or re-cases it, nothing
        composes a query from a supply value, a context facet, a listing, the
        utterance directly or a cached query, and where the composition refused
        there is no request at all.

        Args:
            utterance: The turn's own words, unrewritten — the only value the
                composer is supplied, and the reason ADR-0155 §3 does not reach the
                query (§4).
            remaining: How many slots of ADR-0226 §6's budget are unspent when the
                search is reached. Fewer than one composes nothing, seeks no ruling
                and opens no channel (§11).
            external: ADR-0181 §4's fact for **this** request, computed by the
                caller over the turn's pre-servicing supply and every record this
                servicing has already contributed (§11). It is written onto the
                carrier before ``bind`` and is discarded, never merged, if any
                producer emitted one.
            footing: This conversation's ADR-0238 footing. Every store call this
                method makes about the budget or the destination's trust goes through
                it, and none is made anywhere else.
            in_view: The turn's pre-servicing supply and every record this servicing
                has already contributed — **the same data, the same site and the same
                instant** ``external`` above is computed over (ADR-0238 §5). It is
                what ADR-0238 §2's supply is drawn from and what §5's current-turn
                half is decided over.
            counts: ADR-0238 §11's three counts, **written** as each stage completes
                rather than returned, so a fault the searcher raised after the ruling
                leaves behind what actually happened.

        Returns:
            The minted records, §13's disposition and ADR-0238 §11's three counts. The
            records are empty on every non-yield, and the disposition is ``None``
            exactly where the search yielded or reached the provider and returned
            nothing.
        """
        if remaining < 1:
            # §11: "Where fewer than one slot remains when the search is reached,
            # no request is composed, no ruling is sought and no channel is
            # opened". Checked before the composer is called, so the model call
            # this branch saves is genuinely not made. **Unreachable on the order
            # §11 fixes** — the search is second and only the one-record file
            # precedes it — and stated anyway, as the forward-compatibility guard
            # §11 states in terms for the lane that reorders the kinds.
            return self._not_serviced(SearchDisposition.NO_BUDGET, footing)
        # ADR-0238 §8: **admission first**, before a supply is constructed, a query
        # composed, a ruling sought, a credential read or a channel opened. It is one
        # atomic step of the conversation record — compare, increment, answer — and it
        # spends the call it admits, so there is nothing outstanding afterwards and no
        # path lowers the draw. §11's sixteenth disposition is what records the refusal.
        admitted = await footing.admit()
        if admitted is None:
            # ADR-0242 §8's one configuration-discriminated row: the same disposition
            # renders as `SEARCH_DISABLED` under a bound of `0` and `NOT_ADMITTED` under
            # a positive one, told apart from `footing.max_calls` — the deployment's own
            # `Settings` value — and never from a per-turn record.
            return self._not_serviced(SearchDisposition.NOT_ADMITTED, footing)
        counts.calls = admitted.calls
        # ADR-0238 §2: **which** supply this servicing builds is decided here, from the
        # destination's recorded trust and from the records this component holds. The
        # answer decides only what may be composed over — §5 is explicit that "no clause
        # reads it as deciding what may be sent" — so it is read again below, at the
        # instant the request is built, and this value reaches no binding.
        supply, counts.withheld = _search_supply(
            utterance,
            in_view,
            trusted=await footing.trusted() is DestinationTrust.USER_CHOSEN,
            footing=footing,
        )
        counts.supplied = len(supply.records)
        composed = await self._composer.compose(supply)
        refusal = composed.refusal
        if refusal is not None:
            # §11: "where the composition returned a `QueryRefusal` there is **no
            # request at all** — no ruling is sought, no channel is opened, and
            # §13's disposition names the refusal". The mapping is total over the
            # vocabulary and injective, so no two causes are collapsed.
            return self._not_serviced(QUERY_DISPOSITIONS[refusal], footing)
        query = composed.query
        if query is None:  # pragma: no cover — `QueryOutcome` admits no such value
            # `QueryOutcome`'s own validator refuses an outcome carrying neither a
            # query nor a refusal, so this is unconstructable for a conforming
            # value and is written for the type checker rather than for a caller.
            return self._not_serviced(SearchDisposition.COMPOSER_MALFORMED, footing)
        proposal = await self._searcher.request(query)
        if proposal is None:
            # §17: `request` "returns the `ActionRequest` for a composed query, or
            # `None` where the deployment has connected no search account". The
            # same provisioning fact a servicer holding no searcher at all reports,
            # under the same member — §13 admits one member for two outcomes of one
            # stage an operator would act on identically.
            return self._not_serviced(SearchDisposition.NOT_CONFIGURED, footing)
        # ADR-0238 §5: **the last two values obtained before the request is built**,
        # with nothing awaited between them and the `EgressBinding`'s construction —
        # which is the whole of what makes §8's boundary true, the store being unable to
        # enforce it because `admit_search` does not consult the flag.
        #
        # The current-turn half is already in hand and is not a fact another actor can
        # change under this servicing: it is computed from records this component holds
        # as data it fetched, at the same instant and over the same data as `external`.
        # The other two are read **now** — not before `admit_search`, not to decide
        # whether to search at all, and **not the draw `admit_search` itself answered**
        # — because the flag is monotone and a fold that commits during the composition
        # must be seen by a request built after it.
        current_turn = all(footing.clean(record) for record in in_view)
        recorded_footing = await footing.footing()
        trust = await footing.trusted()
        bound = await self._bound(
            proposal,
            external=external,
            coverage=SelectionOrigin.over(supply.records).coverage,
            # All four of §5's conditions, and the fourth is the admission this
            # servicing already holds rather than capacity still unspent: `admit_search`
            # spent the call it admitted, so a condition reading "the draw leaves room
            # for one more" would be false for **every** admitted request.
            closed_loop=(
                current_turn and recorded_footing and trust is DestinationTrust.USER_CHOSEN
            ),
        )
        if bound is None:
            return self._not_serviced(SearchDisposition.BINDING_FAILED, footing)
        # ADR-0152 §1: the request is built from what the seam returned and never
        # from objects held across the call, with no `await` between the two — the
        # runner's own rule at a second call site. `step_id` and `execution_id` are
        # `None` (§6): no plan step is synthesised, no `ExecutionState` and no
        # execution, and no clause written about steps is given a subject here.
        request = ActionRequest(
            tool=bound.tool, parameters=bound.parameters, egress_binding=bound.binding
        )
        recorded = await self._ruled(request)
        if recorded is None:
            return self._not_serviced(SearchDisposition.RULING_UNAVAILABLE, footing)
        outcome = recorded.ruling.outcome
        if outcome is not PermissionOutcome.ALLOW:
            # §9: the one route to an `ALLOW` is ADR-0193's standing recipient
            # grant over the provider's canonical destination set, established by a
            # recorded act of the user — the act ADR-0235 decides and no lane has
            # yet implemented, so the store is empty and
            # `ThresholdActionPolicy`'s disclosure floor fires on a `discloses`
            # that is non-empty because the query is Tier 1 leaving the device.
            #
            # **And a second, independent floor fires with it today** (issue
            # #2111): the search declaration carries `cost=UNKNOWN`, which
            # `ThresholdActionPolicy` treats as its own non-configurable `CONFIRM`
            # and which no grant discharges — §5 admits an "operator's configured
            # per-call figure" but adds no `Settings` field for one and
            # `build_web_search_integration` takes no parameter for one. So every
            # search is this branch on `origin/main` for **two** reasons, which
            # is what §13's disposition is read against and why closing either
            # alone changes nothing.
            # **ADR-0242 §7's carrier, computed here from the values this site already
            # holds and from no read of its own.** `trust` is the build-time `trust_of`
            # answer ADR-0238 §5 obliges, taken above at the position §5 fixes and
            # carried as data — no second read, no earlier read, and §5's
            # read-to-ruling window is not widened. `planned_with_external_content` is
            # read off the binding this request carried, which is what tells a first
            # refusal (`AUTHORISATION_AWAITED`) from a follow-up's (`TRUST_MISSING`);
            # the disposition alone cannot, and an explanation derived from it would
            # send half of milestone 31's users to the wrong command (§8).
            return self._not_serviced(
                SearchDisposition.RULING_DENY
                if outcome is PermissionOutcome.DENY
                else SearchDisposition.RULING_CONFIRM,
                footing,
                planned_with_external_content=bound.binding.planned_with_external_content,
                trust=trust,
            )
        # ADR-0021 §1's `authorises` runs inside `ToolCall`'s own validator, so an
        # unauthorised search is unconstructable at the type level — which is
        # `ToolInvoker.invoke`'s guarantee obtained without `ToolInvoker` (§6).
        # It cannot refuse here: `recorded` equals the decision `from_request`
        # transcribed from this very request, and the outcome above is `ALLOW`.
        result = await self._searcher.search(
            ToolCall(request=request, decision=recorded),
            # ADR-0241 §3: this site passes the bound on **every** call, from the
            # `Settings` value the composition root handed it. There is no spelling
            # for "unbounded" at the seam and none is reached for here.
            timeout=self._deadline,
        )
        search_refusal = result.refusal
        if search_refusal is not None:
            # §13: six of the seven members are carried across one for one
            # (ADR-0241 §4 adds the sixth), and `NO_RESULT` maps to **none** — a
            # search that reached the provider and yielded nothing is a completed
            # servicing whose returned count is zero, which ADR-0226 §9 already
            # records.
            return self._not_serviced(SEARCH_DISPOSITIONS.get(search_refusal), footing)
        # ADR-0238 §2's third admissible population, recorded for **this turn** alone:
        # a record minted at a destination the user chose is one a later servicing of
        # this same turn may compose over, and one §5's third condition tolerates in
        # view. ADR-0231 §16 makes the id resolve in no store and no later turn reach
        # it, so this set dies with the turn and a captured episode is never in it.
        if trust is DestinationTrust.USER_CHOSEN:
            footing.minted_user_chosen.update(record.id for record in result.records)
        return _Searched(result.records, None, None)

    @staticmethod
    def _not_serviced(
        disposition: SearchDisposition | None,
        footing: SearchFooting,
        *,
        planned_with_external_content: bool = False,
        trust: DestinationTrust = DestinationTrust.UNCHOSEN,
    ) -> _Searched:
        """One non-yield, carrying ADR-0231 §13's disposition and ADR-0242 §7's member.

        **The two are computed together, at this site, and never apart** (ADR-0242 §7).
        A branch that returned one without the other would either put a disposition in
        the audit with nothing for the user or a member in the reply with nothing in the
        audit, and the second vocabulary exists precisely because neither is derivable
        from the other downstream.

        Args:
            disposition: What this branch resolved to.
            footing: This conversation's footing, for
                ``Settings.search_calls_per_conversation`` alone — **no store call is
                made here**, and the value was handed to the footing by the composition
                root rather than read by it (ADR-0238 §8).
            planned_with_external_content: The binding's own fact, where this branch
                built a request.
            trust: The build-time ``trust_of`` answer, where this branch reached it.

        Returns:
            The empty records, the disposition and the member.
        """
        return _Searched(
            (),
            disposition,
            not_serviced(
                disposition,
                max_calls=footing.max_calls,
                planned_with_external_content=planned_with_external_content,
                trust=trust,
            ),
        )

    async def _bound(
        self,
        proposal: ActionRequest,
        *,
        external: bool,
        coverage: SpanCoverage,
        closed_loop: bool,
    ) -> BoundEgressCall | None:
        """Derive this request's binding, or answer that there is none (§6).

        **Both origin facts are stamped here, before the request reaches the seam**,
        and neither is derived from the other (ADR-0233 §4's fifth clause).
        ``planned_with_external_content`` is the caller's ``external``, computed
        over the selections §11 names. ``coverage`` is the caller's
        too, and it is **computed rather than defaulted**: ADR-0233 §5 puts the value
        on "the component that composed the call's arguments, from the membership and
        path character of what it supplied to the operations that produced them", and
        what this package supplied to the composer's model call is the turn's own
        utterance **and whatever records ADR-0238 §2 admitted to the supply**. So it is
        ``NOT_COVERED`` for a supply carrying no record — ADR-0231 §4's state,
        unchanged, and what a destination reading ``UNCHOSEN`` gets, where "the composer
        is supplied no covered content, and its output is therefore not covered content
        either" — and ``MODEL_ON_EVERY_PATH`` for one carrying any, which is exactly the
        class ADR-0238 §7's second exception to ADR-0155 §3's third clause admits: every
        covered path of a composer's output continues back through the composer's own
        model call, so ADR-0155 §3's **second** clause has no subject here either
        (ADR-0238 §7's second clause, in terms).

        **``closed_loop`` is the caller's third carried fact** (ADR-0238 §5), written by
        ``orchestration`` at the moment the request is built and by nothing else. It is
        discarded, never merged, if any producer emitted one; no model output
        contributes to it; and nothing downstream infers, defaults, repairs or
        recomputes it.

        The ``spans`` mapping is empty, which is ADR-0152 §5's named residue at a
        second call site rather than an omission: nothing in this tree records a
        span's origin, so every span the seam describes is ``SYSTEM_SELECTED``.

        **A refusal, a raise and a ``None`` are one answer here** (§9, §13). §9
        declines on "an ``EgressBinder`` that refused or raised", and a ``None``
        means the seam holds no egress registration for this declaration — which
        for the one integration §5 registers at that seam is a mis-wiring, and the
        fail-closed reading is the only one available: a search sent under no
        binding is a send to a destination no policy ruled on.

        Args:
            proposal: What ``WebSearcher.request`` returned — its ``tool`` is the
                searcher's own declaration and its ``parameters`` are exactly the
                origin and the query.
            external: ADR-0181 §4's fact for this request.
            coverage: ADR-0233 §4's fact for this request, over what was supplied to
                the composer's model call.
            closed_loop: ADR-0238 §5's fact for this request — all four conditions,
                each evaluated at its own instant by the caller.

        Returns:
            The derived binding beside the detached call, or ``None`` where the
            seam refused, raised or held no registration.
        """
        try:
            return await self._binder.bind(
                proposal.tool,
                parameters=proposal.parameters,
                provenance=CarriedProvenance(
                    spans={},
                    planned_with_external_content=external,
                    coverage=coverage,
                    closed_loop=closed_loop,
                ),
            )
        except AssistantError:
            # `EgressBindingError` for a refusal and `ConnectionStoreError` for a
            # connection that could not be read are what this seam contracts
            # (ADR-0152 §1, §9); the net is their common root because §9's clause
            # is stated over *raising* rather than over a class, and because a
            # fault at this stage is an operator's fact whose class §13 refuses to
            # copy into the record. A `CancelledError` is a `BaseException` and
            # passes through untouched (ADR-0060), and a `TypeError` from a
            # non-conforming implementation is a defect rather than a fault and
            # reaches the turn.
            return None

    async def _ruled(self, request: ActionRequest) -> PermissionDecision | None:
        """Rule on ``request`` and record the decision, or answer that neither held.

        **Every branch is recorded, including a ``DENY``** (ADR-0004 §7): a refusal
        nobody can find a trace of is the half of the trail that answers "what did
        the assistant decline to do".

        **And every branch reads back what the trail holds, not what was written.**
        The decision is what ADR-0192 §1 keys the searcher's own ledger claim on —
        "the ledger requires the decision it is passed to be equal to the decision
        the store holds under that id" — so a trail that accepted the append and
        lost it would have this method open a channel under a decision nothing
        holds. §9 declines on "an ``AuditTrail`` that could not record the
        decision", and a trail that cannot hand it back is one.

        Args:
            request: The request the query is in, carrying its whole binding
                (ADR-0148 §1).

        Returns:
            The trail's own copy of the recorded decision, or ``None`` where the
            policy raised, the append was refused, or what came back is not what was
            written.

        Raises:
            ClockReadingError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range. Not
                translated and not swallowed, for the reason stated in the body.
        """
        try:
            ruling = await self._policy.decide(request)
        except AssistantError:
            # §13's `RULING_UNAVAILABLE`, first limb: "`ActionPolicy` raised". The
            # net is `_bound`'s, for its reason.
            return None
        # One clock reading, stamping the record. `expires_at` is `None` on every
        # outcome: ADR-0059 §1's lifetime is a property of a question somebody will
        # answer, and §9 rules that a `CONFIRM` here "resolves in no turn" — so a
        # deadline would describe an answerability this decision does not have.
        #
        # **A non-conforming reading propagates untranslated** (ADR-0026 §4), which is
        # `Fetcher`'s posture at the neighbouring seam and ADR-0230 §4's reason
        # transposed: ADR-0231 adds **no** error class to `core/errors.py`, and a clock
        # this process cannot read is not one of §9's three decline causes — those are
        # a binder, a policy and a trail. Reporting it as `RULING_UNAVAILABLE` would
        # report one stage's fault under another stage's member, which §13 forbids in
        # terms. No production turn reaches here on such a clock anyway:
        # `LearningLoop._goal_from` reads the same guarded seam before the planner is
        # called and raises `PlanningError` there.
        decision = PermissionDecision.from_request(
            request, ruling, id=self._id_factory(), decided_at=self._now()
        )
        try:
            await self._trail.record(decision)
            recorded = await self._trail.get(decision.id)
        except AssistantError:
            # §13's second limb: "the decision could not be recorded" — a refused
            # append, or a read that raised. The net is `_bound`'s, for its reason.
            return None
        # Equality over the whole record and not its subject, for
        # `StepRunner._record`'s reason: comparing the tool and the digest leaves
        # the ruling unexamined, so a trail returning a same-subject record with
        # the outcome flipped would have this servicing act on an answer the policy
        # never gave — here, send a search the policy refused.
        return recorded if recorded == decision else None


def _degraded(refused_by: str) -> None:
    """Say that one servicing degraded, and say it in Tier 2 alone (ADR-0004 §5).

    **The class, and no traceback.** This line carried ``exc_info=True`` until a
    ``WEB_SEARCH`` ask put the turn's own utterance into
    :func:`service_read_request`'s frame beside the supply and the composed sighted
    query — and ``core/logging.py`` renders through ``structlog.dev.ConsoleRenderer``,
    whose exception formatter is ``rich``'s with ``show_locals=True``, so a rendered
    traceback writes a frame's locals into the log where ``redact_sensitive`` cannot
    reach them: it runs *before* the renderer and over the event dict's keys, and a
    rendered traceback is neither. What an operator needs from this line is that the
    servicing degraded and what class refused, and both are Tier 2 — which is
    ``ThresholdActionPolicy``'s own answer at ``recipient_grant_seam_unreadable``,
    one seam over.

    Args:
        refused_by: The class name of what refused. Never a message, never an
            instance and never a value it was carrying.
    """
    _log.warning("read_request_degraded", stage="service_read_request", refused_by=refused_by)


async def service_read_request(  # noqa: PLR0913, PLR0915 — the store, the emission, and one parameter per thing a kind is serviced against, and one statement per kind serviced plus ADR-0238 §8's fold after each admission; §7 admits one site and this is it
    store: MemoryStore,
    request: ReadRequest,
    *,
    supply: Sequence[MemoryRecord],
    fetcher: Fetcher | None,
    listing: SourceListing | None,
    search: SearchServicer | None,
    utterance: str,
    audit: TurnReadAudit,
    footing: SearchFooting | None = None,
) -> ServicedCarriers:
    """Service one emission, once, into the fourth group (ADR-0226 §§2, 6, 7).

    **The local file is serviced first, then the web search, then the citation hop,
    then the structured read, then the sighted query** (ADR-0240 §5, amending
    ADR-0231 §11's own amendment of ADR-0230 §7's amendment of ADR-0226 §6's
    cross-kind precedence sentence in one further respect). §6's
    decision is applied and not moved — the capped read ahead
    of the uncapped one — and ADR-0230 §1 caps the fetch hardest of the four: one
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

    **The structured read sits between the hop and the query, and ADR-0226 §6's own
    rule is what puts it there** (ADR-0240 §5). This kind has no cap of its own — its
    ``limit`` is what is left — so the capped-ahead-of-uncapped half of §6 cannot
    place it by a number; what places it is the second half of the same sentence, that
    "the sighted query fills what remains" and there can only be one residual read.
    Between two reads that take what remains, the one the planner bounded by naming a
    period and a person is the more selective by construction. Putting the query first
    would reduce this kind to the case where the belief layer returned nothing, which
    is the inversion ADR-0231 §11 refused for the search and ADR-0230 §7 for the file.

    **Two conditions can stop it before any store call, and both are tested before the
    read rather than after it** (ADR-0240 §5). Where every record of the supply as it
    stands at that moment — the pre-servicing supply and everything this servicing has
    already admitted alike — is ``EPISODIC``, the ask is not serviced at all: this
    kind returns episodes on every servicing, and ADR-0158 §4's separator rule is what
    keeps a run of them from rendering under ``planning``'s recent-turns heading, "a
    fabricated claim about continuity, produced silently". Where fewer than one slot
    of the budget remains, no store call is made either. Testing before the read is
    what keeps ADR-0226 §7's "the servicer discards no record on the ground of its
    class" untouched — a read that was never made returns no record to discard — and
    it is ADR-0158 §4's own construction, "the check is made before the read rather
    than after it, because dropping the result is the decision either way".

    **A structured read that ran and returned nothing is a fact, and three
    neighbouring states are not it** (ADR-0240 §6). The empty-read carrier is computed
    from **the store call's own result** and never from the union's admissions: a read
    whose records were all deduplicated out returned records, and a planner told
    otherwise would broaden away from records already in front of it. A read the budget
    prevented, one the separator condition blocked and a servicing that failed
    establish nothing either, and none of them reaches the carrier.

    **#2147 is not this ADR's to answer and is not answered here** (ADR-0240 §5, §14).
    The separator condition is taken for the ``STRUCTURED_READ`` alone; the same hole
    is open for a ``CITATION_HOP`` whose evidence is episodes, and closing it across
    every kind is ADR-0226 §7's question rather than one to decide inside this branch.

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
        search: The five contracts a ``WEB_SEARCH`` ask is answered against
            (ADR-0231 §5, §6), or ``None`` where this deployment connected no
            search account. **Passed rather than defaulted**, for ``fetcher``'s
            reason one kind over: a defaulted seam would let a later call site
            silently service no search and read, in §9's record, exactly like a
            turn on which the planner asked for none. ``None`` is §13's
            :attr:`SearchDisposition.NOT_CONFIGURED` and never an error.
        utterance: The turn's own words, unrewritten — **the only value the
            composer is supplied** and the whole of what a search request is
            composed from (ADR-0231 §3, §4). It is not the label space, not a
            deduplication set and not a value any other kind reads: no store value,
            supply, tail, listing, rationale or record reaches the composing seam,
            which is what keeps ADR-0155 §3 from having a subject here.
        audit: This turn's record. One :class:`ServicedRead` entry is appended to
            :attr:`TurnReadAudit.servicings` on every path out of this function, and
            :attr:`ServicedRead.records` is what the caller appends to the fourth
            group. A turn that services twice appends two, in servicing order
            (ADR-0228 §9).
        footing: This conversation's ADR-0238 footing — the destination's recorded
            trust, the conversation's stored flag and its call allowance, beside what
            **this turn** has minted at a chosen destination. It is **per turn** and
            the caller builds it, because the conversation a turn runs under is the
            caller's fact and this function is handed one turn's work. ``None``
            services no search at all, which is fail-closed: see
            :func:`_serviced_search`.

    Returns:
        :class:`ServicedCarriers`: ADR-0227 §3's hop carrier, ADR-0240 §7's empty-read
        carrier and ADR-0240 §8's two facts about what the structured read filtered
        on. The default instance — every field empty or ``False`` — is what a
        servicing that failed or was partial carries out, on §5's all-or-nothing
        posture.
    """
    reads = _Reads()
    union = _Union(held={record.id for record in supply}, budget=READ_BUDGET)
    completed: ServicedRead | None = None
    carried = ServicedCarriers()
    empty_read: ReadAsk | None = None
    resolved_by_hop: tuple[MemoryRecord, ...] = ()
    hop = _ask_of(request, ReadKind.CITATION_HOP)
    query = _ask_of(request, ReadKind.SIGHTED_QUERY)
    local_file = _ask_of(request, ReadKind.LOCAL_FILE)
    structured = _ask_of(request, ReadKind.STRUCTURED_READ)
    # `ReadAsk`'s validator makes a `STRUCTURED_READ` ask's `structure` non-``None``
    # (ADR-0240 §2), read here as the guarantee it is rather than restated as a
    # branch. The axes are computed from the ask and not from the read, because §10
    # records them "wherever a ``STRUCTURED_READ`` ask was emitted" — including on
    # the servicing that then failed, which is the record an operator most wants.
    axes = () if structured is None else _axes_of(structured)
    outcome = StructuredOutcome.NOT_ASKED if structured is None else None
    # `ReadAsk`'s validator makes a `SIGHTED_QUERY` ask's query non-``None`` (§4),
    # so this reads the guarantee rather than restating it as a policy: there is no
    # branch here for an ask the model refuses to construct. A `LOCAL_FILE` ask's
    # `entry` carries the same guarantee (ADR-0230 §1) and is read the same way.
    statement = None if query is None else query.query
    named = None if local_file is None else local_file.entry
    truncated: list[ReadKind] = []
    unresolved = 0
    refusal: FetchRefusal | None = None
    # Assigned before the `try`, because ADR-0231 §13's field rides on the failing
    # record too and a fault raised *by* the search leaves the call that would have
    # assigned it unreturned — where the honest value is the empty one §5's
    # degradation carries (issue #2112).
    searched = _Searched((), None, None)
    # **ADR-0238 §11's three counts are *written* rather than returned**, for the reason
    # `_Reads` is: a fault the searcher raised after the ruling unwinds past the call
    # that would have returned them, and a record saying a servicing admitted no call
    # and composed over nothing would be false of a servicing that did both. Each field
    # is set as its stage completes, so the failing record carries what actually
    # happened.
    counts = _SearchCounts()

    async def observed() -> None:
        """Fold ADR-0238 §8's early ``False`` over what this servicing has admitted.

        **Called after every admission and before the next read**, which is §8's own
        clause: the trigger is the admission of a disqualifying span "and it fires
        whether or not that turn ever builds a ``WEB_SEARCH`` request". Folding once at
        the end of the servicing would leave the window open across every read that
        follows — a hop, a structured read, a sighted query — which is the whole of what
        §8 narrows "from the whole of a turn to a single store write".

        Idempotent by :meth:`SearchFooting.admitted`'s own guard, so the repetition costs
        one set scan and at most one store write per turn.
        """
        if footing is not None:
            await footing.admitted(tuple(union.admitted))

    try:
        if named is not None:
            # ADR-0230 §7: **first**, ahead of the hop, because this kind is capped
            # at one record and the hop at two labels — "at one slot, the cheapest
            # precedence position this corpus has ever had to argue for".
            refusal, missed = await _serviced_file(
                named, fetcher, listing, union=union, reads=reads
            )
            unresolved += missed
            # ADR-0238 §8's early fold, **immediately** after the one kind that is
            # always `EXTERNAL` (ADR-0230 §5) admits its record. **Redundant on the order
            # ADR-0231 §11 fixes** — the search is serviced next and folds before its own
            # admission, so the file is already observed by the time any later read
            # suspends — and stated anyway, as the forward-compatibility guard §11 states
            # in terms for the lane that reorders the kinds, which is exactly the ground
            # `NO_BUDGET`'s unreachable branch is written on one member up.
            await observed()
        # ADR-0231 §11: **second**, after the one-record local file and ahead of the
        # hop and the query. ADR-0226 §6's decision is applied and not moved — the
        # capped read ahead of the uncapped one — and sorting the four kinds by their
        # caps gives one file, three results, ten via two labels, and then the
        # uncapped query. Servicing it last is the position at which the budget is
        # ordinarily gone, which would make the kind's availability a function of how
        # full the budget happened to be rather than of what the planner asked for.
        #
        # A `WEB_SEARCH` ask carries no argument at all (§1), so there is nothing to
        # read off it: its presence *is* the whole of the ask, and the query is
        # composed from the utterance alone — which is why the ask is passed whole
        # and the absence of one is answered where every other absence this kind has
        # is (:func:`_serviced_search`).
        searched = await _serviced_search(
            search,
            _ask_of(request, ReadKind.WEB_SEARCH),
            utterance,
            union=union,
            supply=supply,
            reads=reads,
            truncated=truncated,
            footing=footing,
            counts=counts,
        )
        await observed()
        if hop is not None:
            reach = await _hop_records(store, hop, supply=supply, reads=reads)
            # **Accumulated and never assigned** (ADR-0230 §9). The count is one
            # population across the kinds — "an ``F`` label outside the turn's listing
            # counts in the existing unresolved-label count" — so a request naming an
            # unresolvable file *and* a resolvable hop must report both. An assignment
            # here reported the hop's figure alone and silently erased the file's,
            # which is a turn the audit would have shown as having dropped nothing.
            unresolved += reach.unresolved
            resolved_by_hop = reach.expansion
            # ADR-0229 §2: the union is offered the **evidence** alone. A named
            # record is in the pre-servicing supply by construction, so admitting it
            # could only deduplicate — adding one to `returned` and one to
            # `deduplicated` on every serviced hop, for no informational gain and at
            # the cost of ADR-0226 §8's novelty rate. It spends no slot of §6's
            # budget and moves no field of §9's record.
            if union.admit(reach.evidence):
                truncated.append(ReadKind.CITATION_HOP)
            await observed()
        if structured is not None and structured.structure is not None:
            # ADR-0240 §5: **fourth**, after the hop and ahead of the query — the
            # position ADR-0226 §6's own rule reaches for a kind with no cap of its
            # own, since the sighted query is the read that "fills what remains" and
            # there can only be one of those.
            outcome, empty = await _serviced_structured(
                store,
                structured.structure,
                structured.query,
                union=union,
                supply=supply,
                reads=reads,
                truncated=truncated,
            )
            # ADR-0240 §7: the ask **the planner emitted**, byte for byte, and only
            # where the read ran and returned nothing. The other four outcomes
            # establish nothing about the store, so none of them reaches this
            # carrier.
            empty_read = structured if empty else None
            await observed()
        if statement is not None:
            # ADR-0226 §6: **last**, because it is the read that "fills what
            # remains" — the one uncapped kind, and the position ADR-0240 §5 sorts
            # the structured read just above.
            await _serviced_query(store, statement, union=union, reads=reads, truncated=truncated)
            await observed()
        completed = ServicedRead(
            kinds=tuple(ask.kind for ask in request.asks),
            records=tuple(union.admitted),
            returned=union.returned,
            new=len(union.admitted),
            deduplicated=union.deduplicated,
            labels_unresolved=unresolved,
            refusal=refusal,
            disposition=searched.disposition,
            # ADR-0238 §11's three, per turn and per servicing: how many records were
            # supplied to the composer, how many §3's filter withheld, and this
            # conversation's `calls` as the admission left them. **Counts only** — no
            # record id, no conversation id, no destination, no query text and no
            # fragment of one is anywhere in this record.
            supplied=counts.supplied,
            withheld=counts.withheld,
            calls=counts.calls,
            structured_axes=axes,
            # ADR-0240 §10: `None` until the branch above assigns one, and assigned
            # eagerly to `NOT_ASKED` where the request carried no such ask — so this
            # is a member on every completed servicing and `None` on no completed
            # one, which is what makes the absent value mean "the servicing did not
            # complete" and nothing else.
            structured=outcome,
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
        carried = ServicedCarriers(
            hop_reached=tuple(
                identifier
                for identifier in dict.fromkeys(record.id for record in resolved_by_hop)
                if identifier in union.held
            ),
            empty_read=empty_read,
            # ADR-0240 §8 keys the emptiness fact on the turn's last **structured
            # read**, not on its last servicing, so the loop needs to know whether this
            # servicing performed one at all — a servicing whose request carried none,
            # or whose read §5 blocked, establishes nothing and must not clear a fact an
            # earlier read established.
            structured_ran=_ran(outcome),
            # ADR-0240 §8: computed from the ask rather than from the yield, which
            # is what §8's "whether that read returned records or none" asks for —
            # and never where no store call was made, because a read that never ran
            # reached nothing and filtered nothing. Both are built here rather than
            # in the branch above so that §5's all-or-nothing posture reaches them:
            # a servicing that raised after the structured read carries none of
            # these facts out, exactly as it carries no records out.
            label_filtered=_ran(outcome)
            and bool(
                {StructuredAxis.PARTICIPANTS, StructuredAxis.TOPICS, StructuredAxis.ABOUT_PERSON}
                & set(axes)
            ),
            window_filtered=_ran(outcome) and StructuredAxis.WINDOW in axes,
        )
    except MemoryStoreError as store_fault:
        # §5's whole posture, and the archive's for the same reason ADR-0225 §2
        # gives: "a turn that answered from the supply it had is a worse turn, not
        # a broken one, and a mechanism whose whole purpose is a marginal
        # improvement in reach must never be able to take the reply down with it".
        _degraded(type(store_fault).__name__)
    except _ServicingFailedError as failed:
        # The searcher's own fault, arriving through the carrier rather than as
        # itself, so this frame never holds it (ADR-0004 §5).
        _degraded(failed.fault)
        # **And it now has a member of its own** (ADR-0241 §8, issue #2112). Until
        # that decision the field was left empty here, so a fault at the send read in
        # a population exactly like a turn whose planner never asked for a search —
        # the collapse §13's field exists to prevent. The class name stays on the
        # WARNING above, which answers the per-occurrence question; this answers the
        # population one, and it carries no message, no exception type and no store
        # detail (§8, ADR-0004 §5).
        #
        # Assigned rather than folded in: `_serviced_search` is the only raiser of
        # `_ServicingFailedError` and it raises *from inside* the servicing, so
        # `searched` still holds the initial value no stage has written to. The
        # counts are untouched — they are written through as each stage completes, so
        # what actually happened before the fault survives (ADR-0238 §11).
        searched = _Searched((), SearchDisposition.SEARCH_FAILED, SearchNotServiced.UNAVAILABLE)
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
        #
        # **And the disposition rides with it, for the identical reason**
        # (ADR-0231 §13). That section enumerates the two cases in which its field
        # is empty — where the search yielded records, and where no `WEB_SEARCH`
        # ask was made — and a search that declined before a later kind's read
        # raised is neither. Dropping it would report a turn whose search was
        # refused as one whose planner never asked for one, which is exactly the
        # collapse the field exists to prevent.
        audit.servicings += (
            completed
            or ServicedRead(
                kinds=tuple(ask.kind for ask in request.asks),
                refusal=refusal,
                disposition=searched.disposition,
                supplied=counts.supplied,
                withheld=counts.withheld,
                calls=counts.calls,
                # **The axes ride on the failing record and the outcome does not**
                # (ADR-0240 §10), and the asymmetry is the point: "an ask that was
                # emitted is an ask whichever way the servicing went, and suppressing
                # its shape on a failed turn would hide the emissions an operator most
                # wants to see", while no completed-servicing outcome is honest of a
                # servicing that did not complete.
                structured_axes=axes,
                failed=True,
                failed_after_read_returned=reads.returned_any,
            ),
        )
    # ADR-0242 §7's carrier, folded onto the servicing's carriers on **every** path out
    # of the body above — the completed servicing, the degraded one, and the one whose
    # searcher raised — because `searched` is assigned on each of them and `carried` is
    # rebuilt only on the success path. It is what the servicing computed and is never
    # recomputed here.
    return replace(carried, not_serviced=searched.not_serviced)


def _search_supply(
    utterance: str,
    in_view: Sequence[MemoryRecord],
    *,
    trusted: bool,
    footing: SearchFooting,
) -> tuple[SearchSupply, int]:
    """Build ADR-0238 §2's supply for this servicing, and count what §3 withheld.

    **One type, two admissible populations, and a recorded fact decides which**
    (ADR-0238 §2). Where the destination the servicing would bind to reads
    ``UNCHOSEN`` the supply carries the utterance and an empty ``records``, so
    ADR-0231 §3's utterance-only property holds for that destination exactly as
    ratified — and never by a judgement about the turn, the words or the records.

    **What may enter is closed to three populations** (§2): episodes of this
    conversation that ``orchestration`` selected into the turn's supply; the
    ``MemoryRecord`` values the turn's retrieval and episodic supplement selected; and
    records **this turn's own** ``WEB_SEARCH`` servicings minted at a destination of
    recorded trust ``USER_CHOSEN``. The first two are :attr:`SearchFooting.selected`,
    written by the loop from the supply it assembled — the first of them recorded a
    second time, on its own, as :attr:`SearchFooting.conversation_episodes`, because
    :meth:`SearchFooting.clean` tells the two apart and this function does not; the
    third is :attr:`SearchFooting.minted_user_chosen`. **Nothing of any other origin
    enters** —
    "no record minted at an ``UNCHOSEN`` destination, by a fetch, by a file read, by a
    reader or by any tool" — and each of those reaches the turn through a *servicing*
    rather than through the supply the planner was assembled over, so none of them is in
    either set.

    **Membership of the enumerated populations, and never cleanliness.** A stamped
    episode carries a recorded external span and is admitted here whichever conversation
    it belongs to, because §2 names it and §2's own closing paragraph makes it the thing
    that "resolves *find more about that* across turns". Whether it also costs the
    *closed-loop* condition (§5) is a separate question answered by
    :meth:`SearchFooting.clean` at the moment the request is built — and the two answers
    differ: an episode of **this** conversation leaves the footing intact (§15 Arm 1b),
    while a record of any other external origin is composed over and then **not sent**,
    rather than never composed at all.

    **§3's filter is ``Placement.reach`` and no other axis**, read exactly as ADR-0217
    §1 defines it, with no field, member, tag or band added. It is applied here so the
    count §11 owes can be taken; the *refusal* is on the type, so a lane that skipped
    this would build no supply at all rather than a permissive one.

    **No component decides exclusion by inspecting content** (§3), and nothing here
    reads a record's text, resembles it against anything, or asks a model about it.

    Args:
        utterance: The turn's own words, unrewritten.
        in_view: The turn's pre-servicing supply and every record this servicing has
            already contributed.
        trusted: Whether the destination this servicing would bind to reads
            ``USER_CHOSEN`` — the read §2 obliges, taken before the supply is built and
            deciding only what may be composed over.
        footing: This conversation's footing, for the one predicate above.

    Returns:
        The supply, and how many records §3's filter kept out of it.
    """
    if not trusted:
        return SearchSupply(utterance=utterance), 0
    admissible = [
        record
        for record in in_view
        if record.id in footing.selected or record.id in footing.minted_user_chosen
    ]
    return (
        SearchSupply(
            utterance=utterance,
            records=tuple(
                record for record in admissible if record.placement.reach is PlacementReach.ANYONE
            ),
        ),
        sum(1 for record in admissible if record.placement.reach is not PlacementReach.ANYONE),
    )


async def _serviced_search(  # noqa: PLR0913 — the seam, the ask, the composer's one input, the three things ADR-0231 §11 states this kind's budget clause over, and ADR-0238's footing; §7 admits one servicing site and this is that site's fourth kind
    search: SearchServicer | None,
    ask: ReadAsk | None,
    utterance: str,
    *,
    union: _Union,
    supply: Sequence[MemoryRecord],
    reads: _Reads,
    truncated: list[ReadKind],
    footing: SearchFooting | None,
    counts: _SearchCounts,
) -> _Searched:
    """Service one ``WEB_SEARCH`` ask into the fourth group (ADR-0231 §9, §11).

    **This kind's whole budget clause is here**, because §11 states it over this
    kind rather than over the union: "where the slots remaining when the search is
    reached are fewer than the results the provider returned, the servicer admits
    the records that fit, in the order §10 minted them, and admits no more", and
    "where fewer than one slot remains … no request is composed, no ruling is
    sought and no channel is opened". Both are branches of one arithmetic, so both
    live at one site. The union and the truncation record are the same ones every
    other kind draws on and writes to — "not a share, not a second budget" — so
    this kind is truncated exactly as the hop and the query are, and no lane grows
    the budget for it or funds it from another.

    **The origin fact is computed here, by the component that holds the records**
    (§11). It is "the disjunction of ``rests_on_recorded_external_content`` over the
    turn's pre-servicing supply and over every record this servicing has already
    contributed", evaluated at the moment the request is built, from records
    `orchestration` holds as data it fetched — a fact about an act this system
    performed, never an inference about how a model produced an argument, and never
    a value any producer emitted (ADR-0181 §4).

    **The residual is named rather than removed.** With the search serviced second,
    an ``EXTERNAL`` record a *later* inward read of this same servicing would
    contribute is not in view, so this binding can carry ``False`` where the turn's
    final supply would carry ``True``. Three things bound it: the pre-servicing
    supply is where an ``EXTERNAL`` record ordinarily comes from and is in view; the
    local file is in view too, because it is serviced first and is always
    ``EXTERNAL`` (ADR-0230 §5); and the value is monotone within a turn and across a
    conversation, because ADR-0223 §1 stamps the captured episode from the **final**
    supply. ADR-0181 §2 and ADR-0223 §7 already forbid reading a ``False`` as an
    assurance that nothing external was involved.

    **This is not ADR-0223 §2's externality value and not ADR-0204 §2's withholding
    value** (§11, ADR-0230 §7). Those two are computed once, at the loop, over the
    turn's *final* supply; this is a per-request fact at a per-request instant, and
    neither is read off the other.

    Args:
        search: The wired servicer, or ``None`` where this deployment connected no
            search account — §13's :attr:`SearchDisposition.NOT_CONFIGURED`, and
            never an error.
        ask: The emission's ``WEB_SEARCH`` ask, or ``None`` where it carried none.
            Passed whole rather than as a boolean because §1 makes its presence the
            entire content of the ask: it has no argument to read, so there is
            nothing else this function could want from it.
        utterance: The turn's own words, the composer's only input (§3, §4).
        union: The fourth group under construction. Its unspent slot count is what
            §11's two budget branches are decided on, and it is what the minted
            records are admitted into — under §7's whole-union deduplication, which
            binds a minted record as it binds any other.
        supply: The three groups the loop passed the planner on this call, which is
            half of §11's disjunction. The other half is what this servicing has
            already admitted into ``union``.
        reads: The servicing's read observer, noted when a search returns records —
            §9's second failure field is stated over *reads*, and a search that came
            back with records is a read this servicing performed that returned some.
        truncated: The servicing's truncation record, appended to where the budget
            cut this kind short. On the order §11 fixes at least nine of the ten
            slots always remain against a cap of three, so that can only happen for
            a lane that reorders the kinds or raises the file's cap — which is why
            §11 states the clause as a rule rather than as an impossibility.
        counts: ADR-0238 §11's three counts, filled in as the stages complete. Written
            through rather than returned, for :class:`_Reads`' reason.
        footing: This conversation's ADR-0238 footing, or ``None`` where the caller
            passed none. **``None`` services no search at all**, and that is
            fail-closed rather than a fallback: ADR-0238 §8 makes ``admit_search``
            the gate every search passes, so a path with no conversation to admit
            against has no admission and composes nothing. No production composition
            reaches it — ``app/composition.py`` wires the footing unconditionally —
            and the alternative, searching without spending a call, is the one thing
            §8 exists to make impossible.

    Returns:
        The minted records, §13's disposition and ADR-0238 §11's three counts. The
        disposition is ``None`` in each of the cases §13 leaves the field empty: where
        no ``WEB_SEARCH`` ask was made, where the search yielded records, and where it
        reached the provider and returned none.

    Raises:
        _ServicingFailedError: If the searcher raised a fault of its own. Carried to
            ADR-0226 §5's degradation rather than reported as a disposition, for the
            reason that class records.
    """
    if ask is None:
        # §13's second absence: "nothing where … no ``WEB_SEARCH`` ask was made".
        # Answered before the deployment is consulted, so a turn nobody asked a
        # search of reads the same on a wired deployment and an unwired one. ADR-0242
        # §6's eligibility is the disposition's presence, so this turn carries no
        # member either and its assembled prompt is byte-identical to today's.
        return _Searched((), None, None)
    if search is None:
        # ADR-0242 §8's residue: a deployment that connected no search account gives the
        # user no act, so `UNAVAILABLE` — the member that names no cause and no act.
        return _Searched((), SearchDisposition.NOT_CONFIGURED, SearchNotServiced.UNAVAILABLE)
    if footing is None:
        # **No conversation to admit against, and therefore no `Settings` bound in
        # hand.** ADR-0242 §8 discriminates this disposition on that bound alone, so
        # this branch takes the positive-bound member: it is the one that names a
        # per-conversation allowance rather than asserting that the deployment has
        # switched searching off, which nothing here establishes. No production
        # composition reaches it — `app/composition.py` wires the footing
        # unconditionally — and the branch is fail-closed rather than a fallback.
        return _Searched((), SearchDisposition.NOT_ADMITTED, SearchNotServiced.NOT_ADMITTED)
    # ADR-0238 §5's own words for what this holds: "the turn's pre-servicing supply and
    # every record this servicing has already contributed", read once here so that
    # ADR-0181 §4's fact, ADR-0238 §2's supply and §5's current-turn half are computed
    # from **one** value at **one** instant rather than from three reads that could
    # disagree.
    in_view = (*supply, *union.admitted)
    # ADR-0238 §8's **early** fold, before the admission and therefore before anything
    # is composed: the trigger is the admission of a disqualifying span to this turn,
    # and by the servicing order ADR-0231 §11 fixes the local file has already been
    # admitted by the time this kind is reached. Folding here rather than after the
    # request is built is what narrows §8's window to a single store write.
    await footing.admitted(in_view)
    try:
        found = await search.service(
            utterance,
            remaining=union.remaining,
            external=any(
                rests_on_recorded_external_content(record.provenance) for record in in_view
            ),
            footing=footing,
            in_view=in_view,
            counts=counts,
        )
    except AssistantError as exc:
        # ADR-0226 §5, and the reason :class:`_ServicingFailedError` exists.
        # ADR-0231 §9's decline list names the three stages *before* the send — a
        # binder, a policy, a trail — and each of those resolves to its own
        # disposition without raising. What reaches here is a fault the searcher
        # itself raised **after** the ruling, performing ``ToolInvoker.invoke``'s
        # machinery at §6's second route: a connection record it could not read
        # (ADR-0148 §6's fail-closed limb), a ledger claim the trail refused, an
        # authorisation already spent. §13's vocabulary is closed at fifteen with no
        # member for any of them and §17 gives the seam no ``SearchRefusal`` for them
        # either, so the ratified answer is ADR-0226 §5's all-or-nothing degradation
        # — which is what this reaches, and which leaves the supply as planning saw
        # it with every count zero.
        #
        # **``from None``, and the class name rather than the exception** (ADR-0004
        # §5): the chain this suppresses would put ``search.service``'s frames — the
        # utterance, the composed query, the request and the bound call — into any
        # rendered traceback, and every one of those is Tier 1.
        raise _ServicingFailedError(type(exc).__name__) from None
    reads.note(len(found.records))
    if union.admit(found.records):
        truncated.append(ReadKind.WEB_SEARCH)
    return found


async def _serviced_file(
    named: str,
    fetcher: Fetcher | None,
    listing: SourceListing | None,
    *,
    union: _Union,
    reads: _Reads,
) -> tuple[FetchRefusal | None, int]:
    """Service one ``LOCAL_FILE`` ask into the union (ADR-0230 §2, §7).

    **A label outside the shown set resolves to nothing** — malformed, out of range,
    or named on a turn that showed no listing at all — "discarded silently, and
    recorded in §9's audit as an unresolved label". ADR-0226 §9 puts that in the
    unresolved count and **not** beside the refusal: it "never reached the fetcher",
    and the two facts have different causes and different fixes.

    **The entry handed to the fetcher is the one that fetcher minted**, carried
    unaltered from the listing this loop holds (§2, §4). No path is composed, no name
    is joined to a root, and no entry is assembled here.

    Args:
        named: The label the planner wrote, verbatim.
        fetcher: The seam, or ``None`` where no root is configured.
        listing: The listing this turn showed, or ``None``. It is both the label space
            and the authority the fetch is verified against.
        union: The turn's union. The fetch is first and admits one record into ten
            empty slots, so the budget cannot cut it and ``LOCAL_FILE`` never appears
            in ``truncated_kinds`` — §1's cap of one showing up in the audit rather
            than a case elided.
        reads: ADR-0226 §9's second failure field's observer. A fetch that returned a
            record is a read this servicing performed that returned one, so a hop
            raising after the file came back is recorded as the partial servicing it
            was.

    Returns:
        The class the fetch resolved to, or ``None``; and ``1`` where the label
        resolved to nothing, ``0`` otherwise.
    """
    entry = resolve_entry(named, listing)
    if entry is None or fetcher is None or listing is None:
        return None, 1
    outcome = await fetcher.fetch(listing, entry)
    if outcome.record is not None:
        reads.note(1)
        # One slot of ADR-0226 §6's ten, counted after deduplication and drawn
        # through the same union as every other kind — "not a share, not a second
        # budget".
        union.admit((outcome.record,))
    return outcome.refusal, 0


async def _serviced_query(
    store: MemoryStore,
    statement: str,
    *,
    union: _Union,
    reads: _Reads,
    truncated: list[ReadKind],
) -> None:
    """Service one ``SIGHTED_QUERY`` ask into the union (ADR-0226 §2, §6).

    ``assemble_by_band`` "with the band precedence, per-band composition and kind
    selection of the retrieval stage's own read unchanged" (§2), over
    :data:`~ai_assistant.orchestration.conversations.BELIEF_KINDS` — so this kind
    reaches semantic, preference and procedural records and **no episode**, which is
    the fact ADR-0240 §1 rests its fifth member on.

    The query is asked for exactly the slots the earlier kinds left, so the budget
    cannot stop a record it returned — what it does is shorten the ask. A query given
    the whole budget was not truncated by it, however much more the store might have
    held; a query given less and filling every slot of it is the case §6 says the audit
    records.

    Args:
        store: The store this turn already reads.
        statement: The query the planner composed, passed as handed.
        union: The turn's union. Its ``remaining`` is this read's ``limit``.
        reads: ADR-0226 §9's second failure field's observer, threaded in as the page
            observer because one query is several store calls behind one call.
        truncated: The servicing's truncation list, appended to in servicing order.

    Raises:
        MemoryStoreError: Propagated from any band's read, to ADR-0226 §5's one
            degradation site.
    """
    allowed = union.remaining
    found = (
        []
        if allowed <= 0
        else await assemble_by_band(
            store, statement, limit=allowed, kinds=BELIEF_KINDS, on_page=reads.note
        )
    )
    union.admit(found)
    if allowed < READ_BUDGET and len(found) == allowed:
        truncated.append(ReadKind.SIGHTED_QUERY)


def _axes_of(ask: ReadAsk) -> tuple[StructuredAxis, ...]:
    """Which axes one ``STRUCTURED_READ`` ask applied, as ADR-0240 §10's classes.

    The four filter axes come from :meth:`~ai_assistant.core.types.StructuredAsk.applied`
    — the type's own answer to "which of these is not ``None``", so this function does
    not become a second derivation of it — and the query is appended last, because it
    is the member that says which of ADR-0237's two reads serviced the ask rather than
    a filter over stored values.

    **No value crosses.** What comes back are enumeration members; no instant, no
    label and no query text is read off the ask here or anywhere the result goes.

    Args:
        ask: The ``STRUCTURED_READ`` ask. Its ``structure`` is non-``None`` by
            ``ReadAsk``'s own validator, and a call for an ask carrying none records
            the query alone rather than raising — this function reports a shape and
            is not a second enforcement point for a condition ``core`` already keeps.

    Returns:
        The axes applied, window first and the query last. Empty only where the ask
        carried neither a structure nor a query, which ``ReadAsk`` refuses.
    """
    applied = () if ask.structure is None else ask.structure.applied()
    axes = [StructuredAxis(name) for name in applied]
    if ask.query is not None:
        axes.append(StructuredAxis.QUERY)
    return tuple(axes)


def _ran(outcome: StructuredOutcome | None) -> bool:
    """Whether a structured read actually reached the store (ADR-0240 §5, §8).

    ADR-0240 §8's two facts are about what a read **filtered on**, and a read the
    budget did not reach or the supply's shape blocked filtered on nothing: "a read the
    budget prevented is not a read that found nothing, and no implementation, carrier or
    audit field conflates them". Written once here because both facts ask it.

    Args:
        outcome: The state the ask reached, or ``None`` where the servicing had not
            got that far.

    Returns:
        Whether a store call was made for the ask.
    """
    return outcome in {StructuredOutcome.RETURNED_NOTHING, StructuredOutcome.RETURNED_RECORDS}


async def _serviced_structured(  # noqa: PLR0913 — the store, the ask's two halves, and the three things ADR-0240 §5 states this kind's budget and separator clauses over; §7 admits one servicing site and this is that site's fifth kind
    store: MemoryStore,
    structure: StructuredAsk,
    query: str | None,
    *,
    union: _Union,
    supply: Sequence[MemoryRecord],
    reads: _Reads,
    truncated: list[ReadKind],
) -> tuple[StructuredOutcome, bool]:
    """Service one ``STRUCTURED_READ`` ask into the union (ADR-0240 §4, §5, §6).

    **Two conditions are tested before any store call, and the separator wins where
    both hold** (§5, §10). A supply whose every record is ``EPISODIC`` when the read is
    reached blocks it whatever the budget holds — the records this kind returns are
    episodes by design, and without something non-``EPISODIC`` before them
    ``planning``'s leading-run split would render them under the recent-turns heading
    (ADR-0158 §4). A budget with no slot left blocks it too. Neither is a read that
    found nothing, and §6's empty-read fact arises from neither.

    **The supply the separator is tested over is the supply as it stands at this
    moment** — the pre-servicing supply *and* everything this servicing has already
    admitted — which is why a ``LOCAL_FILE`` fetch that minted an attested belief, or a
    ``WEB_SEARCH`` that minted records, is its own separator and this read is then made
    (§5).

    **The query decides which of ADR-0237's two reads answers the ask, and nothing
    else does** (§4). An ask carrying one goes to ``search`` with the query passed as
    handed; an ask carrying none goes to ``select``. The four axes are passed from the
    ``StructuredAsk`` unchanged — ``None`` for ``None``, values otherwise — so nothing
    here translates between the ask's convention and the store's, and nothing trims,
    casefolds, normalises or truncates a value on any axis.

    **``kinds`` names ``EPISODIC`` on every call and the ask carries no kind axis**
    (§4). Beliefs stay reachable exactly as they are, by the retrieval stage and by a
    ``SIGHTED_QUERY``; ``kinds`` and ``bands`` are the store's partitioning vocabulary
    and are not values a planner names.

    **Emptiness is read off the store call's own result** (§6). Not off what the union
    admitted, and not off ``ServicedRead.new``: a read whose every record the
    deduplication removed returned records, and a planner told otherwise "would broaden
    away from records already in front of it". This is the one place a plausible
    implementation gets the deduplication case wrong, and the return value below is
    what keeps it out of ADR-0240 §7's carrier.

    Args:
        store: The store this turn already reads.
        structure: The ask's four axes, already validated by
            :class:`~ai_assistant.core.types.StructuredAsk` — at least one applied, and
            no empty sequence on any of them.
        query: The query the ask carried, or ``None``. Its presence is the whole of
            what chooses between the two store members.
        union: The turn's union under construction. Its ``remaining`` is this read's
            ``limit`` — ADR-0226 §6's one budget, "not a share, not a second budget".
        supply: The three groups the loop passed the planner on this call, which is
            half of what §5's separator condition is tested over.
        reads: ADR-0226 §9's second failure field's observer.
        truncated: The servicing's truncation list, appended to in servicing order.

    Returns:
        The state this ask reached, and whether the store call returned no record at
        all — §6's *empty structured read*, which is ``False`` on every path that made
        no store call.

    Raises:
        MemoryStoreError: Propagated from the store, to ADR-0226 §5's one degradation
            site. This kind adds no error class and no second net.
    """
    if all(MemoryKind(record.kind) is MemoryKind.EPISODIC for record in (*supply, *union.admitted)):
        # ADR-0240 §5, taking ADR-0158 §4's rule for this kind: the test is made
        # **before** the read, so nothing is discarded and ADR-0226 §7's
        # discards-nothing-by-class clause is not approached. §10 records this in
        # preference to the slot outcome where both hold.
        return StructuredOutcome.NO_SEPARATOR, False
    limit = union.remaining
    if limit <= 0:
        return StructuredOutcome.NO_SLOT, False
    # The four axes are passed from the ask unchanged — `None` for `None`, and the
    # values given otherwise (ADR-0240 §2) — written out at both call sites rather
    # than unpacked from a mapping, so `mypy` checks each against ADR-0237 §1's own
    # annotation instead of taking an untyped `**` on trust.
    result = (
        await store.select(
            limit=limit,
            kinds=_STRUCTURED_KINDS,
            occurred_within=structure.window,
            participants=structure.participants,
            topics=structure.topics,
            about_person=structure.about_person,
        )
        if query is None
        else await store.search(
            query,
            limit=limit,
            kinds=_STRUCTURED_KINDS,
            occurred_within=structure.window,
            participants=structure.participants,
            topics=structure.topics,
            about_person=structure.about_person,
        )
    )
    found = result.records
    reads.note(len(found))
    union.admit(found)
    # The read is asked for exactly the slots the earlier kinds left, so the budget
    # cannot stop a record it returned — what it does is shorten the ask. A read given
    # the whole budget was not truncated by it, however much more the store might have
    # held; one given less and filling every slot of it is the case ADR-0240 §5 says
    # the audit records. This is ADR-0226 §6's own rule for the sighted query, applied
    # unchanged.
    if limit < READ_BUDGET and len(found) == limit:
        truncated.append(ReadKind.STRUCTURED_READ)
    if not found:
        return StructuredOutcome.RETURNED_NOTHING, True
    return StructuredOutcome.RETURNED_RECORDS, False


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

    **And no query, no origin and no result, in any form** (ADR-0231 §13). No query
    text, no fragment of one, no length of one, no origin, no host, no address, no
    title, no snippet and no provider message appears anywhere in this event, and a
    fault's message, exception type and store detail do not either — "a fault is an
    operator's fact and the class is the whole of what this Tier 2 event may say about
    one". The second field this kind adds is again a **class**: ``disposition`` is a
    :class:`SearchDisposition` member or absent. A deployment with no search account
    connected, or none whose recipient the user has granted, reads a 0% yield for
    ``web_search``, and that is a true statement about that configuration rather than a
    reading of a trigger — the disposition is what tells the two apart, and no figure
    for this kind is reported without saying which it is.

    **And no value on any axis, in any form** (ADR-0240 §10). No instant, no window,
    no person label, no topic label, no query, no record, no excerpt and no count of a
    label's characters appears anywhere in this event on account of a
    ``STRUCTURED_READ``. The two fields this kind adds are again **classes**:
    ``structured_axes`` is a tuple of :class:`StructuredAxis` members and
    ``structured`` a :class:`StructuredOutcome` member or absent. ADR-0004 §5's rule is
    why — "a person label is a name, chosen by whoever wrote it, and a Tier 2 event
    carrying one is a Tier 1 leak on a value this system did not mint" — and the ask
    stays durable on the frozen ``ActionPlan`` (ADR-0226 §4), which this record neither
    copies nor points at.

    **Two fields and not one, because they answer different questions and neither is
    derivable from the other** (ADR-0240 §10). The outcome answers *did the read work*,
    and it is what a deployment reads to see whether ADR-0240 §6's revision is firing
    and whether it is firing on budget-starved reads it should not be. The axes answer
    *what was tried*, and they are what makes ADR-0239's producer measurable from this
    end: before that lane lands, ADR-0240 §9's gate means the who and what axes are
    described on few turns and used on fewer; after it, the same field says whether the
    planner started using them. Neither number can be read off the other, and neither
    off the existing per-servicing counts, which are stated over the whole servicing
    rather than per ask. **The empty rate per axis set** is the figure the pair newly
    supports, computed over a population of turns and never as a per-turn quantity, and
    it is not a precision or a recall (ADR-0226 §8).

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
                "disposition": None if read.disposition is None else read.disposition.value,
                # ADR-0238 §11's three, on the one event and under the one key: no
                # second audit, no second event key and no new emission point. Counts
                # only, and the destination's recorded trust is deliberately **not**
                # here — "a durable fact about a configured account, readable from the
                # store that holds it, and a per-turn log is not where a deployment's
                # standing configuration is reported".
                "supplied": read.supplied,
                "withheld": read.withheld,
                "calls": read.calls,
                "structured_axes": tuple(axis.value for axis in read.structured_axes),
                "structured": None if read.structured is None else read.structured.value,
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
