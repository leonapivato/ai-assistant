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

**And the sixth kind is the second that leaves the machine, one stage shorter**
(ADR-0260 §7). A ``FORECAST_READ`` ask is serviced here too, under the same budget, into
the same fourth group and onto the same record — no second servicing site, no second
budget, no second audit, no second seam — and it adds one further position in the order,
**third**, between the search and the hop, and two further fields on §9's record. What is
genuinely different from a search is that there is **no compose step**: ADR-0260 §3 gives
the ask no argument at all, so the order is "bind, then rule, then record, then send",
nothing this turn produced reaches the request, and the place and the horizon are the
deployment's own configuration. The authority is ADR-0247 §2's route (c) as ADR-0260 §6
widens it — each kind compared against **its own** configured pair — and what the user is
told is ADR-0260 §10's fold, computed here and carried out as data.

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

import json
import re
from dataclasses import dataclass, field, replace
from datetime import timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.correlation import current_correlation
from ai_assistant.core.episode_encoding import admits_model_eligibility
from ai_assistant.core.errors import AssistantError, MemoryStoreError, ToolBindingError
from ai_assistant.core.types import (
    ActionRequest,
    AttemptKind,
    CarriedProvenance,
    DestinationTrust,
    EgressBinding,
    FetchRefusal,
    ForecastNotRead,
    ForecastRefusal,
    MemoryKind,
    OutboundDestination,
    OutboundReach,
    OutboundStatement,
    ParkedRead,
    ParkedReadDisposition,
    PermissionDecision,
    PermissionOutcome,
    PlacementReach,
    QueryRefusal,
    ReadAskOutcome,
    ReadKind,
    ReadOutcomeKind,
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
    from collections.abc import Callable, Collection, Mapping, Sequence
    from datetime import datetime

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        ActionPolicy,
        AuditTrail,
        EgressBinder,
        Fetcher,
        Forecaster,
        MemoryStore,
        ParkedReads,
        QueryComposer,
        WebSearcher,
    )
    from ai_assistant.core.types import (
        ActionPlan,
        BoundEgressCall,
        FrozenJsonMapping,
        GoalBrief,
        MemoryRecord,
        ReadAsk,
        ReadRequest,
        SearchOutcome,
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
    """Why a turn stopped iterating (ADR-0228 §9, ADR-0251 §7).

    **A closed vocabulary of seven**, and "no implementation, setting or later lane
    adds an eighth without the ADR that decides it". ADR-0251 §7 supersedes ADR-0228
    §9's closure at five **in that count alone**: every existing member keeps its
    name, its value and its meaning, the vocabulary is added to and never renamed,
    and the two new members are :attr:`WORKING_ALLOWANCE_REACHED` and
    :attr:`UNPRODUCTIVE`. Five describe a turn that ran to its own end and
    :attr:`PLANNING_FAILED` describes one that did not, which is the hole §9
    fills deliberately: a planner call after the first that raises still writes a
    record, and none of the successful outcomes describes it — labelling such a turn
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
        BOUND_REACHED: The **attempt's** declared planner-call allowance stopped the
            turn with its planner still asking. **The name and the value are
            ADR-0228 §3's and only the subject moves** (ADR-0251 §7): where §3
            counted a turn's two calls, §5's allowance counts the attempt's, and
            §4(f') is the comparison. An attempt whose kind declares no allowance
            never reaches this member — it does not iterate at all, and
            :attr:`NOT_ITERATED` is what says so.
        BUDGET_REACHED: ADR-0228 §4's per-operation budget was spent when the check
            was made. The boundary instant is spent, not available. **Unchanged and
            still the per-turn gate** (ADR-0251 §5): the attempt's working allowance
            is a second gate, measures a different quantity and has its own member.
        WORKING_ALLOWANCE_REACHED: The attempt's **investigation share** — its
            kind's declared working allowance less its reserve (ADR-0251 §5, §6) —
            was spent when the check was made, again with the boundary instant spent
            rather than available. **Neither a failure nor a blocker** (§9): an
            exhaustion leaves the goal ``ACTIVE``, and the attempt still plans once
            per turn the owner starts.
        UNPRODUCTIVE: The attempt had just completed its **second consecutive**
            unproductive round (ADR-0251 §7) — two rounds in a row whose every ask
            admitted no record the supply did not already hold. A productive round
            resets the run, the run is counted within one turn and nothing persists
            it. Also neither a failure nor a blocker.
        PLANNING_FAILED: A planner call after the first raised, or the turn ended
            between a servicing and the next plan's return.
    """

    NOT_ITERATED = "not_iterated"
    SETTLED = "settled"
    BOUND_REACHED = "bound_reached"
    BUDGET_REACHED = "budget_reached"
    WORKING_ALLOWANCE_REACHED = "working_allowance_reached"
    UNPRODUCTIVE = "unproductive"
    PLANNING_FAILED = "planning_failed"


class SearchDisposition(StrEnum):
    """Why a ``WEB_SEARCH`` ask did not yield records (ADR-0231 §13, ADR-0241 §4, §8).

    **A closed enumeration of exactly seventeen members, each valued by its
    lower-cased name** — ADR-0231 §13's fifteen and ADR-0241's
    :attr:`DEADLINE_EXPIRED` and :attr:`SEARCH_FAILED`, which superseded that
    closure "in that clause's count alone" and left every other clause of it
    standing. **ADR-0238 §11's** ``NOT_ADMITTED`` **is gone** (ADR-0247 §6): its only
    producer was ``admit_search`` refusing, and ADR-0247 §5 removes the
    per-conversation call budget entire — so the count moves from eighteen to
    seventeen **in that count alone**, and the remaining members, their values, the
    injectivity of every mapping into it, its no-message rule, its exclusion of
    ``SearchRefusal.NO_RESULT`` and its audit clauses stand entire. **No lane reads
    that as licence to remove an eighteenth** — and never free text: the
    shape :class:`TriggerOutcome`,
    :class:`Servicing` and :class:`StopReason` already have in this module, and
    the reason :class:`~ai_assistant.orchestration.origin.SelectionOrigin` is not
    in ``core`` either. **It lives here and not in ``core``** (§13): it crosses no
    subsystem boundary, being the servicer's own account of why a servicing did
    not yield — assembled from a composer refusal, a policy ruling, the turn's own
    read budget and a :class:`~ai_assistant.core.types.SearchRefusal` — and read by
    nothing
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

    **No longer the disposition of every search** (ADR-0247 §2, §3). A search at the
    configured provider reaches an ``ALLOW`` on ADR-0148 §3's third route — the
    deployment's own configuration, which §1 makes the owner's choosing act and
    ADR-0193's granting act at once — and §3 retires both floors that used to draw
    this row for it, the disclosure floor over ``planned_with_external_content`` and
    its coverage exception. What still draws it is a ground of its own: a per-call
    cost the deployment declared no figure for (#2111, ADR-0236), or a binding whose
    account or origin is not the configured pair, or any destination that is not this
    one. **It resolves in no turn**: no lane resumes it and none treats it as
    outstanding work, and the decision it was recorded under carries no
    ``execution_id`` and no ``step_id`` (§6), so no recovery query and no park can
    reach it.

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


#: ADR-0264 §2's partition of :class:`SearchDisposition`, **total over the seventeen
#: members the vocabulary is closed at** and written once here, beside the two mappings
#: whose discipline §2 names: "a member added without an arm fails rather than falling
#: to a default". §18's item 9a asserts it over the enum itself, so a lane that adds an
#: eighteenth member without placing it fails rather than being silently grouped.
#:
#: **Three groups and not two, because each member was read from the code that produces
#: it** (§2). This vocabulary names *the stage that produced the outcome*, and a stage is
#: not a wire fact: four members are reached from more than one producing path and the
#: paths disagree about whether anything left the machine.
#:
#: * :attr:`~ai_assistant.core.types.OutboundReach.REACHED` — a **contact**, because
#:   this system reaches the member only from octets the provider's channel had already
#:   returned. :attr:`SearchDisposition.RESPONSE_TOO_LARGE` is reached only from a reader
#:   counting octets off the channel and :attr:`SearchDisposition.UNATTESTED` only from a
#:   response that declared no instant, so both arrived.
#: * :attr:`~ai_assistant.core.types.OutboundReach.INDETERMINATE` — **nothing either
#:   way**, and the non-asserting direction is taken deliberately (§2, §12). A refused
#:   connection, an expiry of ``search_call_deadline`` and a fault raised out of
#:   ``WebSearcher.search`` are each consistent with a request that left and with one
#:   that did not; and :attr:`SearchDisposition.PROVIDER_REFUSED` is recorded **both**
#:   for a response the provider gave and this system refused **and** for an account that
#:   changed across the credential read, whose limbs "discarded the credential and wrote
#:   nothing to any channel — none was opened" (ADR-0148 §6). None of the four carries a
#:   value separating its causes.
#: * :attr:`~ai_assistant.core.types.OutboundReach.NOT_REACHED` — **no contact**, every
#:   one of them a stage before the send: no query was composed, no ruling was obtained,
#:   or the send was refused on a ceiling. :attr:`SearchDisposition.NO_BUDGET`'s own
#:   definition is that "no request is composed, no ruling is sought and no channel is
#:   opened".
#:
#: **One reading of ``_result_of``'s docstring is deliberately kept out** (§2): it also
#: groups ``RESPONSE_TOO_LARGE`` with ``TRANSPORT_FAILED`` and ``PROVIDER_REFUSED`` as
#: "calls that did not complete as calls", which is about the **invocation's** outcome
#: and not about whether bytes crossed the wire. A response too large to carry arrived;
#: a refused connection did not; a provider refusal is recorded for both.
SEARCH_CONTACTS: Final[Mapping[SearchDisposition, OutboundReach]] = MappingProxyType(
    {
        SearchDisposition.NOT_CONFIGURED: OutboundReach.NOT_REACHED,
        SearchDisposition.NO_BUDGET: OutboundReach.NOT_REACHED,
        SearchDisposition.COMPOSER_DECLINED: OutboundReach.NOT_REACHED,
        SearchDisposition.COMPOSER_UNAVAILABLE: OutboundReach.NOT_REACHED,
        SearchDisposition.COMPOSER_MALFORMED: OutboundReach.NOT_REACHED,
        SearchDisposition.COMPOSER_TOO_LONG: OutboundReach.NOT_REACHED,
        SearchDisposition.BINDING_FAILED: OutboundReach.NOT_REACHED,
        SearchDisposition.RULING_CONFIRM: OutboundReach.NOT_REACHED,
        SearchDisposition.RULING_DENY: OutboundReach.NOT_REACHED,
        SearchDisposition.RULING_UNAVAILABLE: OutboundReach.NOT_REACHED,
        SearchDisposition.SPEND_REFUSED: OutboundReach.NOT_REACHED,
        SearchDisposition.RESPONSE_TOO_LARGE: OutboundReach.REACHED,
        SearchDisposition.UNATTESTED: OutboundReach.REACHED,
        SearchDisposition.TRANSPORT_FAILED: OutboundReach.INDETERMINATE,
        SearchDisposition.DEADLINE_EXPIRED: OutboundReach.INDETERMINATE,
        SearchDisposition.SEARCH_FAILED: OutboundReach.INDETERMINATE,
        SearchDisposition.PROVIDER_REFUSED: OutboundReach.INDETERMINATE,
    }
)


def contact_of(disposition: SearchDisposition | None) -> OutboundReach:
    """What one **performed** ``WEB_SEARCH`` call established (ADR-0264 §2).

    **The caller must have performed a call.** The absent disposition is §2's
    eighteenth case — "a call that **completed and recorded no**
    ``SearchDisposition``", which is a search that reached the provider and was
    answered, records or none, because ``SearchRefusal.NO_RESULT`` maps to no
    disposition (ADR-0231 §13). A site that performed **no** call establishes
    nothing either way and does not call this: it contributes nothing to the fold,
    and a turn every one of whose sites contributed nothing is ``NOT_REACHED`` (§1).

    **It is never derived from** :class:`~ai_assistant.core.types.SearchNotServiced`
    (§2). That vocabulary is non-injective by design (ADR-0242 §8) and
    ``UNAVAILABLE`` covers both a response that arrived and was refused and a
    transport that failed, which this partition's second and third groups separate.

    **The discriminator is over the call and never over the servicing's completion**
    (§2). A response that arrived is a contact whatever the enclosing servicing's
    disposition, so this is called at the performing site and no component
    re-derives it from ``ServicedRead.disposition`` after the servicing has ended —
    an absent disposition on a *failed* servicing covers both a search that was
    answered and a servicing that raised before its search was serviced, and the
    record holds nothing that separates them.

    Args:
        disposition: What the call resolved to, or ``None`` where it completed and
            recorded none.

    Returns:
        The member of :class:`~ai_assistant.core.types.OutboundReach` §2 places this
        call in.
    """
    if disposition is None:
        return OutboundReach.REACHED
    return SEARCH_CONTACTS[disposition]


class ForecastDisposition(StrEnum):
    """Why a ``FORECAST_READ`` ask put no record into the supply (ADR-0260 §8).

    **A closed enumeration of exactly twelve members, each valued by its lower-cased
    name** — the servicing's own account of what became of the ask, beside
    :class:`SearchDisposition`, which is where ADR-0260 §8 puts it: it *"crosses no
    subsystem boundary, being the servicer's own account"*, where
    :class:`~ai_assistant.core.types.ForecastRefusal`,
    :class:`~ai_assistant.core.types.ForecastOutcome`,
    :class:`~ai_assistant.core.types.ReadOutcomeKind` and
    :class:`~ai_assistant.core.types.ForecastNotRead` each cross one and are
    ``core``'s. The vocabulary is **added to and never renamed**, and no
    implementation, setting or later lane adds a thirteenth without the ADR that
    decides it.

    **Two vocabularies and not one, which is ADR-0231's shape taken for its reason**
    (§8). The seam answers for what *it* did —
    :class:`~ai_assistant.core.types.ForecastRefusal`, six members, every one of them
    a value :meth:`~ai_assistant.core.protocols.Forecaster.read` returns — and this
    answers for the stages the seam never sees: no registration, no budget, no
    derivable binding, no ``ALLOW``.

    **A read that reached the provider and was answered records *no* member of this
    vocabulary**, records or none (§8):
    :attr:`~ai_assistant.core.types.ForecastRefusal.NO_RESULT` maps to no disposition,
    which is what §10's contact rule is computed from and is ADR-0231 §13's own
    construction one seam over.

    **A class and nothing else** (§8, ADR-0004 §5). No member carries a message, a
    ground, a provider name, a destination, a place, a coordinate, a day, a monetary
    figure, a duration, a count or a ``Settings`` field name, and no statement
    rendered for one carries any of them: ADR-0242 §9's bar binds this vocabulary as
    it binds ``SearchNotServiced``, so **these members state what became of the ask
    and never why a source ruled the way it did**. The whole value is one of them, so
    there is nowhere in ADR-0226 §9's record for one to sit.
    """

    NOT_CONFIGURED = "not_configured"
    """This deployment configured no forecast provider (ADR-0260 §8, §11).

    Both routes to it are the same fact about the same stage, exactly as
    :attr:`SearchDisposition.NOT_CONFIGURED`'s two are: no forecaster is wired into
    the loop at all, and a wired forecaster whose
    :meth:`~ai_assistant.core.protocols.Forecaster.request` answered ``None`` because
    the four-field registration is absent. A provisioning fact, and the one §10 folds
    to :attr:`~ai_assistant.core.types.ForecastNotRead.NOT_CONFIGURED` — the member
    whose statement names an **operator** setting and no user act."""

    NO_BUDGET = "no_budget"
    """Fewer than one slot of ADR-0226 §6's ten remained when the forecast was reached.

    §7: *"no request is composed, no ruling is sought and no channel is opened"*, and
    §8's classifier produces **no outcome entry at all** for the ask — ADR-0251 §2's
    precedence case 1, because *"a read the budget did not reach is not in it"*. **A
    read the budget prevented is not a read that found nothing**, and no
    implementation, carrier or audit field conflates them.

    **Reachable on the order §7 fixes**, unlike the search's member of the same name:
    the forecast is serviced third, so a file that took one slot and a search that
    took as many as nine leave it with none — which is §13's arm (f)."""

    BINDING_FAILED = "binding_failed"
    """A stage before the send refused, and no channel was opened (ADR-0260 §6, §8).

    Two producers and one member, because both are the same stage: ``EgressBinder.bind``
    refused, raised or held no registration for this declaration; and **ADR-0029 §2's
    three pre-execution checks**, which §6 makes :meth:`Forecaster.read` perform itself
    and which raise ``ToolBindingError`` *"before any credential is read and any channel
    is opened"* — a mutated call, one carrying a definition the forecaster did not
    register, and one its decision does not authorise. §6 states the recording in terms:
    such a failure *"**is recorded by the servicing as `BINDING_FAILED`**"*.

    **It is not ADR-0148 §6's pre-transmit refusal**, which is
    :attr:`PROVIDER_REFUSED` returned as a value: §6 separates them by what moved —
    these raise because *the thing about to run is not the thing that was authorised*,
    where those fire on a call that was and stayed exactly that and whose connection
    record moved beneath it.

    **No message, no exception type and no store detail** (ADR-0004 §5): a fault is an
    operator's fact and the class is the whole of what this Tier 2 event may say about
    one."""

    RULING_CONFIRM = "ruling_confirm"
    """The recorded ruling was ``CONFIRM`` (ADR-0260 §6, §8).

    **Not the ordinary ruling for this kind.** A forecast read at the configured
    forecast provider reaches an ``ALLOW`` on ADR-0247 §2's route (c) as ADR-0260 §6
    widens it, with no confirmation sought and no grant seam consulted. What still
    draws this row is a ground of its own: the per-call cost the deployment declared no
    figure for (ADR-0236 §4's unknown-cost floor, which §11 leaves untouched), a
    ``DENY``-free policy that confirms on some other threshold, or a binding whose
    account or origin is not the configured forecast pair.

    **Nothing is parked** (§11). ADR-0244's park is a ``CONFIRM`` on a **search** and
    nothing here widens it, so a forecast read ruled ``CONFIRM`` *"is recorded, is not
    made, is not parked"* and is reported under §10's
    :attr:`~ai_assistant.core.types.ForecastNotRead.AUTHORISATION_AWAITED`. No lane
    resumes it and none treats it as outstanding work."""

    RULING_DENY = "ruling_deny"
    """The recorded ruling was ``DENY`` — a policy the operator set (ADR-0260 §8)."""

    RULING_UNAVAILABLE = "ruling_unavailable"
    """``ActionPolicy`` raised, or the decision could not be recorded (ADR-0260 §8).

    :attr:`SearchDisposition.RULING_UNAVAILABLE`'s two limbs at a second seam and for
    its reasons. A trail that accepted the append and does not hand the record back is
    one that could not record the decision, so it resolves here rather than opening a
    channel on a decision nothing holds. It carries no message, no exception type and
    no store detail."""

    SPEND_REFUSED = "spend_refused"
    """A spend ceiling refused the call before it was made (ADR-0260 §8).

    **The member has no producer in this tree, and that is ADR-0260 read rather than
    an omission.** §6 enumerates what :meth:`Forecaster.read` performs and names
    neither ADR-0194 §3's admission nor ADR-0192's claim; ``tools/forecast.py`` says so
    in terms — *"No spend gate and no invocation ledger"* — and
    :class:`~ai_assistant.core.types.ForecastRefusal` carries no ``SPEND_REFUSED``
    member where ``SearchRefusal`` has one. §8 nonetheless states the vocabulary at
    twelve, §10 folds this to
    :attr:`~ai_assistant.core.types.ForecastNotRead.SPEND_EXHAUSTED` and places it on
    the no-contact side, and §13's arm (k) walks it; so it is written exactly as the
    decision states it and simply has nothing that reaches it, which is
    :attr:`~ai_assistant.core.types.SearchNotServiced.TRUST_MISSING`'s standing one
    vocabulary over. **No lane removes it** on the ground that nothing produces it."""

    TRANSPORT_FAILED = "transport_failed"
    """:attr:`~ai_assistant.core.types.ForecastRefusal.TRANSPORT_FAILED`, carried across.

    An outage — a refused connection, a TLS failure, a channel closed mid-response. It
    is **not** a slow provider, which is :attr:`DEADLINE_EXPIRED`: an operator reading
    a population cannot act on one field meaning both *"the provider is unreachable"*
    and *"the provider is slow"*."""

    DEADLINE_EXPIRED = "deadline_expired"
    """:attr:`~ai_assistant.core.types.ForecastRefusal.DEADLINE_EXPIRED`, carried across.

    The bound this site handed :meth:`Forecaster.read` expired before it answered
    (ADR-0241 §1, ADR-0260 §11). It carries no duration, no bound, no elapsed figure
    and no place: ADR-0004 §5 binds without qualification, and a duration in a per-turn
    event is a fact about the *system* ADR-0228 §10 has already refused to render.

    **It is the seam's own expiry and never an outer one** (ADR-0241 §4). A read
    cancelled from outside while suspended re-raises ``CancelledError`` and reaches no
    member of this vocabulary at all."""

    RESPONSE_TOO_LARGE = "response_too_large"
    """:attr:`~ai_assistant.core.types.ForecastRefusal.RESPONSE_TOO_LARGE`, carried across.

    The response passed ``forecast_max_response_bytes`` and was abandoned while being
    read, nothing was parsed and no record was minted (ADR-0260 §11). **It establishes
    a contact** (§10): this system reaches the member only from octets the provider's
    channel had already returned."""

    PROVIDER_REFUSED = "provider_refused"
    """:attr:`~ai_assistant.core.types.ForecastRefusal.PROVIDER_REFUSED`, carried across.

    **Two causes under one member, and no value separates them** (ADR-0260 §6): a
    response the provider gave and this system refused — a non-success status, a
    blocked origin, a body its documented format does not admit — and **ADR-0148 §6's
    pre-transmit refusal**, whose limbs discard the credential and open no channel.

    **So it establishes nothing either way** (§10), over *both* its causes, which is
    ADR-0264 §13's third arm taken at its word rather than one member read two ways at
    two seams: a site holding it cannot tell whether octets arrived, and ADR-0264 §1
    ranks silence above a false claim."""

    UNATTESTED = "unattested"
    """:attr:`~ai_assistant.core.types.ForecastRefusal.UNATTESTED`, carried across.

    The response declared no instant this system could read as one, so ADR-0260 §5
    minted nothing rather than substituting a clock of its own (ADR-0092 §3). **It
    establishes a contact** (§10), for :attr:`RESPONSE_TOO_LARGE`'s reason."""


#: ADR-0260 §8's carry-across from the forecast seam's vocabulary, **injective** for
#: :data:`SEARCH_DISPOSITIONS`' reason, over the five members that reach the servicer.
#:
#: :attr:`~ai_assistant.core.types.ForecastRefusal.NO_RESULT` is deliberately absent and
#: maps to no disposition at all: §8 rules that *"a read that reached the provider and
#: was answered records **no** disposition, records or none"*, and a completed servicing
#: whose returned count is zero is what ADR-0226 §9 already records — *"calling it a
#: disposition would double-count it"*. §13's arm (k) asserts that absence over the enum
#: itself, so a lane that adds an arm for it fails.
FORECAST_DISPOSITIONS: Final[Mapping[ForecastRefusal, ForecastDisposition]] = MappingProxyType(
    {
        ForecastRefusal.TRANSPORT_FAILED: ForecastDisposition.TRANSPORT_FAILED,
        ForecastRefusal.DEADLINE_EXPIRED: ForecastDisposition.DEADLINE_EXPIRED,
        ForecastRefusal.RESPONSE_TOO_LARGE: ForecastDisposition.RESPONSE_TOO_LARGE,
        ForecastRefusal.PROVIDER_REFUSED: ForecastDisposition.PROVIDER_REFUSED,
        ForecastRefusal.UNATTESTED: ForecastDisposition.UNATTESTED,
    }
)


#: ADR-0260 §10's establishment partition of :class:`ForecastDisposition`, **total over
#: the twelve members the vocabulary is closed at** and written once here, beside the
#: carry-across whose discipline it shares: a member added without an arm fails rather
#: than falling to a default. §13's arm (k) asserts it over the enum itself.
#:
#: * :attr:`~ai_assistant.core.types.OutboundReach.REACHED` — **a contact**, because
#:   this system reaches the member only from octets the provider's channel had already
#:   returned. :attr:`ForecastDisposition.RESPONSE_TOO_LARGE` is reached only from a
#:   reader counting octets off the channel and
#:   :attr:`ForecastDisposition.UNATTESTED` only from a response that declared no
#:   instant, so both arrived. **Either folded to ``INDETERMINATE`` would deny a contact
#:   the trail recorded**, which is what §13's arm (h) asserts them separately for.
#: * :attr:`~ai_assistant.core.types.OutboundReach.INDETERMINATE` — **nothing either
#:   way**, and the least-claiming direction taken deliberately (§10). A refused
#:   connection and an expiry of the caller's bound are each consistent with a request
#:   that left and with one that did not; and
#:   :attr:`ForecastDisposition.PROVIDER_REFUSED` is recorded **both** for a response
#:   the provider gave and this system refused **and** for ADR-0148 §6's pre-transmit
#:   refusal, which *"discards the credential and opens no channel"*. None of the three
#:   carries a value separating its causes, and §10 takes ADR-0264 §13's third arm at
#:   its word: *"an implementation reading it as a response is what this arm exists to
#:   catch"*.
#: * :attr:`~ai_assistant.core.types.OutboundReach.NOT_REACHED` — **no contact**, every
#:   one of them a stage before the send: no provider configured, no slot, no derivable
#:   binding, no ``ALLOW``, or a ceiling that refused.
#:
#: **The absence of a member is the thirteenth case and is not in this table** (§10): a
#: call that completed and recorded no disposition reached the provider and was
#: answered, which is :func:`forecast_contact_of`'s own first branch.
FORECAST_CONTACTS: Final[Mapping[ForecastDisposition, OutboundReach]] = MappingProxyType(
    {
        ForecastDisposition.NOT_CONFIGURED: OutboundReach.NOT_REACHED,
        ForecastDisposition.NO_BUDGET: OutboundReach.NOT_REACHED,
        ForecastDisposition.BINDING_FAILED: OutboundReach.NOT_REACHED,
        ForecastDisposition.RULING_CONFIRM: OutboundReach.NOT_REACHED,
        ForecastDisposition.RULING_DENY: OutboundReach.NOT_REACHED,
        ForecastDisposition.RULING_UNAVAILABLE: OutboundReach.NOT_REACHED,
        ForecastDisposition.SPEND_REFUSED: OutboundReach.NOT_REACHED,
        ForecastDisposition.RESPONSE_TOO_LARGE: OutboundReach.REACHED,
        ForecastDisposition.UNATTESTED: OutboundReach.REACHED,
        ForecastDisposition.TRANSPORT_FAILED: OutboundReach.INDETERMINATE,
        ForecastDisposition.DEADLINE_EXPIRED: OutboundReach.INDETERMINATE,
        ForecastDisposition.PROVIDER_REFUSED: OutboundReach.INDETERMINATE,
    }
)


def forecast_contact_of(disposition: ForecastDisposition | None) -> OutboundReach:
    """What one **performed** forecast call established (ADR-0260 §10, ADR-0264 §2).

    **The caller must have performed a call.** The absent disposition is §10's
    thirteenth case — *"a forecast read establishes an outbound contact where its call
    completed and recorded no ``ForecastDisposition``"*, which is a read that reached
    the provider and was answered, records or none, because
    :attr:`~ai_assistant.core.types.ForecastRefusal.NO_RESULT` maps to no disposition
    (§8). A site that performed **no** call establishes nothing either way and does not
    call this: it contributes nothing to the fold, and a turn every one of whose sites
    contributed nothing is ``NOT_REACHED`` (ADR-0264 §1).

    **The fact is never derived from**
    :class:`~ai_assistant.core.types.ForecastNotRead` (§10), which is non-injective by
    design: ``UNAVAILABLE`` covers a response that arrived and was refused *and* a
    transport that failed, which this partition's first and second groups separate. A
    site holding only the folded member cannot compute this and does not try.

    **It is computed at the performing site and no site recomputes another's** (§10).
    A response that arrived is a contact whatever the enclosing servicing's fate, so
    this is called where the call was made and never re-derived from
    :attr:`ServicedRead.forecast` after the servicing has ended — an absent disposition
    on a *failed* servicing covers both a read that was answered and a servicing that
    raised before its forecast was serviced, and the record holds nothing that
    separates them.

    Args:
        disposition: What the call resolved to, or ``None`` where it completed and
            recorded none.

    Returns:
        The member of :class:`~ai_assistant.core.types.OutboundReach` §10 places this
        call in.
    """
    if disposition is None:
        return OutboundReach.REACHED
    return FORECAST_CONTACTS[disposition]


#: ADR-0264 §2's fold order, least-claiming first, read by :func:`folded_reach`.
_REACH_RANK: Final[Mapping[OutboundReach, int]] = MappingProxyType(
    {
        OutboundReach.NOT_REACHED: 0,
        OutboundReach.INDETERMINATE: 1,
        OutboundReach.REACHED: 2,
    }
)


def folded_reach(carried: OutboundReach | None, one: OutboundReach | None) -> OutboundReach | None:
    """Fold one call's contribution into the turn's (ADR-0264 §2).

    "**The turn's value is folded from its calls,** ``REACHED`` **outranking**
    ``INDETERMINATE`` **and** ``INDETERMINATE`` **outranking** ``NOT_REACHED``."
    One call that established a contact makes the turn ``REACHED`` however many
    others did not; failing that, one that established nothing either way makes it
    ``INDETERMINATE``. **The order is the least-claiming one available**: a turn is
    never reported as having reached nothing while one of its own calls may have
    reached something.

    **Assembly accumulates and never replaces** (§6). A servicing that establishes
    no contact clears nothing an earlier one established, and a
    last-writer-wins assembly is the defect that clause names — which is why this is
    a fold rather than an assignment, on the shape :func:`earliest` already has for
    ADR-0242 §7's member.

    Args:
        carried: What the turn holds so far, or ``None`` where no site has
            contributed.
        one: What this site contributed, or ``None`` where it performed no call and
            so established nothing either way.

    Returns:
        The stronger of the two, or ``None`` where neither contributed.
    """
    if one is None:
        return carried
    if carried is None:
        return one
    return one if _REACH_RANK[one] > _REACH_RANK[carried] else carried


def outbound_statement(
    *,
    search: OutboundReach | None,
    forecast: OutboundReach | None = None,
    egress: OutboundReach | None,
    records: int,
    composes: bool,
) -> OutboundStatement | None:
    """Assemble one turn's statement, once, from the carriers §2 and §4 name (ADR-0264 §6).

    **Nothing is inferred at the assembly point** (§6). Every input is a fact some
    other site computed and carried here as data: the contact classification each
    performing site computed (§2), the admitted count each admitting site recorded (§4),
    and the executed-egress fact the component that drove the step computed — never an
    ``EgressBinding``, a ``Disposition`` or a ``StepExecution`` read here.

    **Each destination class is derived from its own seam's reach and from no other's**
    — §3 as ADR-0260 §15 amends it, written as code rather than as a rule to remember.
    ADR-0264 §3's *"from a ``WEB_SEARCH`` call and from nothing else"* stops being
    readable as a closure over the corpus the moment a second seam establishes a
    contact, which is that ADR working rather than a departure from it: §5 requires a
    later outbound seam to add its own member, and *"a member that renders is a contact
    that was established"*. So ``search`` decides
    :attr:`~ai_assistant.core.types.OutboundDestination.SEARCH_PROVIDER` and
    ``forecast`` decides
    :attr:`~ai_assistant.core.types.OutboundDestination.FORECAST_PROVIDER`, **neither
    displacing the other** — ADR-0260 §13's arm (l) is exactly that: a turn that reached
    both carries **one** statement naming **both** classes, in §5's declared order,
    because an implementation overwriting one with the other would deny a contact the
    trail recorded. ``egress`` still names no class and can only make a turn
    ``INDETERMINATE`` (§3's prohibition, which binds entire). A turn that contacted one
    class through three servicings names it once, because the classes are a set of kinds
    and never an enumeration of servicings (§4).

    **A turn that carries nothing carries** ``NOT_REACHED`` **and not** ``None``
    (§1, §7): #2365's shape is a turn that made no call at all, and leaving the member
    absent there is exactly what let a reply date its material to *"this turn's
    searches"* unremarked.

    Args:
        search: What this turn's ``WEB_SEARCH`` calls established, folded by
            :func:`folded_reach`, or ``None`` where it performed none.
        forecast: What this turn's forecast calls established, folded by
            :func:`folded_reach`, or ``None`` where it performed none (ADR-0260 §10).
            **Defaulted**, and that is the one seam where a default is honest here: a
            pass that services no read at all — a resumed park, a resolved step —
            performs no forecast call by construction, and ``None`` is what such a site
            already says about the search by passing it.
        egress: What the driven egress step established, or ``None`` where the turn
            drove none, the step carried no ``EgressBinding``, or the executor proved
            the callable was never reached (ADR-0192 §1's three windows).
        records: How many records this turn's established contacts put into its supply
            (§4). Read only where a contact was established, because §4 couples the
            two and the model refuses an uncoupled value. **One population over the
            turn**, so a turn that reached two classes states the sum of what both
            admitted and never one figure per class: the statement names a set of kinds
            and carries one count.
        composes: Whether an answer is owed on this pass — that is, whether the
            composing stage is **reached**. ``False`` on a routed park, on which
            ADR-0197 §10 rules "the composing stage is not reached", and on the two
            shapes §6 names in terms: "ADR-0170 §4 requires no composition on a pass
            whose step parked for confirmation or whose ``turn`` is ``None``". With no
            contact established, that is §7's one ``None`` case.

            **It is not a report of what the composing stage produced, and the
            difference decides a real pass.** A composition that *failed* reached the
            stage and is neither of §6's two shapes, so it carries the member it was
            given — and it must, for two reasons §7 states. The outcome carries "the
            value §6 computed, **by value, and never a second computation**", so
            re-deriving one at the capture point from what the reply turned out to be is
            the move that clause forbids; and the composing stage was handed the
            fragment for *this* value, so a second derivation would leave the assembled
            prompt and the rendered member disagreeing about one turn.

            **§7's rendering asymmetry is the surface's rule and not this one.**
            "``NOT_REACHED`` and ``INDETERMINATE`` render only on a pass that composed a
            reply … The condition is the reply's existence and never its content" binds
            **on a rendering surface**, which §11 makes lane 2's — and §13 item 10 names
            the failure it exists to catch: "one that renders ``NOT_REACHED`` with no
            reply beside it fails it too", which is a failure only a surface *handed*
            that member can commit.

    Returns:
        The statement this turn carries, or ``None`` on a pass that **neither
        established a contact nor composed a reply** (§7).
    """
    reach = folded_reach(folded_reach(search, forecast), egress) or OutboundReach.NOT_REACHED
    if reach is OutboundReach.REACHED:
        # **The classes are read off the two seams' own answers and are never inferred
        # from the fold** (§4, ADR-0260 §10). `egress` reaches no class at all (§3), so
        # a `REACHED` fold is a `REACHED` on at least one of the two below and the
        # tuple cannot be empty — which is what keeps the model's own coupling check
        # from being tripped here. The order is `OutboundDestination`'s own, stated by
        # the order of these two lines and validated again on the model, because §4
        # forbids an encounter order and ADR-0260 §10 puts `FORECAST_PROVIDER`
        # **after** `SEARCH_PROVIDER`.
        contacted = tuple(
            member
            for member, reached in (
                (OutboundDestination.SEARCH_PROVIDER, search),
                (OutboundDestination.FORECAST_PROVIDER, forecast),
            )
            if reached is OutboundReach.REACHED
        )
        return OutboundStatement(reach=reach, destinations=contacted, records=records)
    if composes:
        # §4: on `NOT_REACHED` and `INDETERMINATE` the classes are empty and the count
        # is `0` — there is no contact for a record to have entered the supply on.
        return OutboundStatement(reach=reach)
    return None


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


#: Every typed non-yield a source of this system can produce, as one annotation
#: (ADR-0251 §2). Four vocabularies: two ``orchestration``'s own and two ``core``'s.
_NonYield = (
    SearchDisposition
    | SearchRefusal
    | FetchRefusal
    | StructuredOutcome
    | ForecastDisposition
    | ForecastRefusal
)


class _NonYieldClass(StrEnum):
    """Which of ADR-0251 §2's precedence limbs one typed non-yield falls under.

    **Five limbs and not four**, because "the source answered" is a limb of its own:
    §2's precedence puts the non-yield's class ahead of the counts (limbs 2, 3 and 4)
    and the counts ahead of nothing (limbs 5, 6, 7 and 8), so a value saying *the
    source answered and here is what it returned* has to be distinguishable from a
    value saying *there is no non-yield to read*. Both send the classifier to the
    counts, and neither is a fallback: every member of every one of the four
    vocabularies is placed in :data:`_NON_YIELD_CLASSES` by name.
    """

    UNREACHED = "unreached"
    """§2's precedence case 1: the ask was not put, or the budget did not reach it.

    **No entry at all**, and never a member of
    :class:`~ai_assistant.core.types.ReadOutcomeKind`: ADR-0240 §7's clause binds
    verbatim — "A read the budget did not reach is not in it" — and telling a planner
    ``EMPTY`` about a read nobody made would be a statement about a source that was
    never asked."""

    ANSWERED = "answered"
    """The source answered; §2's limbs 5 to 8 decide from the counts alone."""

    EXPIRED = "expired"
    """§2's precedence case 2: a deadline passed (ADR-0241 §4)."""

    FAILED = "failed"
    """§2's precedence case 3: the servicing completed and the answer was a failure."""

    REFUSED = "refused"
    """§2's precedence case 4: the source decided not to answer, on a ground it owns."""


def _vocabulary_key(member: _NonYield) -> tuple[str, str]:
    """The key one typed non-yield is placed under, and why it is not the member.

    **Six ``StrEnum`` vocabularies share many member names**, and a ``StrEnum`` member
    hashes and compares as its value — so ``SearchDisposition.SPEND_REFUSED`` and
    ``SearchRefusal.SPEND_REFUSED`` are one key in any mapping keyed on the member
    itself, as are the three spellings of ``TRANSPORT_FAILED`` ADR-0260 §8 adds to.
    Today every such pair must reach the same class, and does; a table that *collapsed*
    them would make that agreement silent rather than checked, and would let a member
    added to one vocabulary tomorrow inherit a class a different vocabulary decided.
    Keying on the vocabulary's own name beside the member's makes the fifty-two
    placements fifty-two rows, so §2's "no default branch and no fallback member" is
    checkable by counting.

    Args:
        member: One member of one of the six source vocabularies.

    Returns:
        Its vocabulary's name and its own, which no two members share.
    """
    return type(member).__name__, member.name


#: ADR-0251 §2's class per typed non-yield, **stated member by member and never
#: derived from a name, a prefix or a substring**. It is the whole of the enum-facing
#: half of the classifier, and the classifier itself reads no vocabulary but this
#: mapping — so a member added to any of the six without a class here fails at import
#: rather than falling through to a default, which is §2's "no default branch and no
#: fallback member" held mechanically rather than by review.
#:
#: **Keyed by :func:`_vocabulary_key` rather than by the member**, for the collapse that
#: function records: six ``StrEnum``s sharing member names would otherwise be fewer rows
#: than the fifty-two placements this table makes.
#:
#: **ADR-0260 §8's two vocabularies are placed here member for member** (its own
#: per-member lists), and the placements agree with the search's on every shared
#: spelling: the forecast disposition vocabulary's configuration, ruling, spend and
#: attestation members are ``REFUSED`` and its failure members ``FAILED``, its
#: ``NO_BUDGET`` is ``UNREACHED`` under §2's case 1, and
#: ``ForecastRefusal.NO_RESULT`` is ``ANSWERED`` for ``SearchRefusal.NO_RESULT``'s
#: reason — §8 puts it under ``EMPTY``, which is exactly what the counts then say.
#:
#: **``SearchRefusal.RESPONSE_TOO_LARGE`` is a failure and
#: ``SearchDisposition.RESPONSE_TOO_LARGE`` is read the same way**, as are the two
#: spellings of ``PROVIDER_REFUSED``: §2 enumerates the first of each pair by name and
#: describes the class of the second — the disposition vocabulary's ruling, spend,
#: composition, configuration and attestation members are ``REFUSED`` and its failure
#: members are ``FAILED`` — and a value meaning one thing under two spellings must not
#: reach a planner under two members.
#:
#: **``SearchRefusal.NO_RESULT`` is ``ANSWERED`` and not ``EMPTY`` here.** §2 puts a
#: provider that answered with nothing under ``EMPTY``, and that is exactly what the
#: counts then say: this mapping's job is the non-yield's *class*, and a member that
#: says the source answered hands the decision to limbs 5 to 8 rather than
#: short-circuiting them. ``ServicedRead.disposition`` never carries it anyway — a
#: search that reached the provider and found nothing resolves to no disposition at
#: all — so the entry is what makes the table total rather than a live branch.
_NON_YIELD_CLASSES: Final[Mapping[tuple[str, str], _NonYieldClass]] = MappingProxyType(
    {
        # --- SearchDisposition (ADR-0231 §13, seventeen members) ----------------
        _vocabulary_key(SearchDisposition.NOT_CONFIGURED): _NonYieldClass.REFUSED,
        _vocabulary_key(SearchDisposition.NO_BUDGET): _NonYieldClass.UNREACHED,
        _vocabulary_key(SearchDisposition.COMPOSER_DECLINED): _NonYieldClass.REFUSED,
        _vocabulary_key(SearchDisposition.COMPOSER_UNAVAILABLE): _NonYieldClass.REFUSED,
        _vocabulary_key(SearchDisposition.COMPOSER_MALFORMED): _NonYieldClass.REFUSED,
        _vocabulary_key(SearchDisposition.COMPOSER_TOO_LONG): _NonYieldClass.REFUSED,
        _vocabulary_key(SearchDisposition.BINDING_FAILED): _NonYieldClass.FAILED,
        _vocabulary_key(SearchDisposition.RULING_CONFIRM): _NonYieldClass.REFUSED,
        _vocabulary_key(SearchDisposition.RULING_DENY): _NonYieldClass.REFUSED,
        _vocabulary_key(SearchDisposition.RULING_UNAVAILABLE): _NonYieldClass.REFUSED,
        _vocabulary_key(SearchDisposition.SPEND_REFUSED): _NonYieldClass.REFUSED,
        _vocabulary_key(SearchDisposition.TRANSPORT_FAILED): _NonYieldClass.FAILED,
        _vocabulary_key(SearchDisposition.DEADLINE_EXPIRED): _NonYieldClass.EXPIRED,
        _vocabulary_key(SearchDisposition.PROVIDER_REFUSED): _NonYieldClass.REFUSED,
        _vocabulary_key(SearchDisposition.RESPONSE_TOO_LARGE): _NonYieldClass.FAILED,
        _vocabulary_key(SearchDisposition.UNATTESTED): _NonYieldClass.REFUSED,
        _vocabulary_key(SearchDisposition.SEARCH_FAILED): _NonYieldClass.FAILED,
        # --- SearchRefusal (ADR-0231 §17, ADR-0241 §4, seven members) -----------
        _vocabulary_key(SearchRefusal.SPEND_REFUSED): _NonYieldClass.REFUSED,
        _vocabulary_key(SearchRefusal.TRANSPORT_FAILED): _NonYieldClass.FAILED,
        _vocabulary_key(SearchRefusal.DEADLINE_EXPIRED): _NonYieldClass.EXPIRED,
        _vocabulary_key(SearchRefusal.PROVIDER_REFUSED): _NonYieldClass.REFUSED,
        _vocabulary_key(SearchRefusal.RESPONSE_TOO_LARGE): _NonYieldClass.FAILED,
        _vocabulary_key(SearchRefusal.UNATTESTED): _NonYieldClass.REFUSED,
        _vocabulary_key(SearchRefusal.NO_RESULT): _NonYieldClass.ANSWERED,
        # --- FetchRefusal (ADR-0230 §5, five members) ---------------------------
        _vocabulary_key(FetchRefusal.NOT_FOUND): _NonYieldClass.REFUSED,
        _vocabulary_key(FetchRefusal.NOT_A_FILE): _NonYieldClass.REFUSED,
        _vocabulary_key(FetchRefusal.UNREADABLE): _NonYieldClass.FAILED,
        _vocabulary_key(FetchRefusal.TOO_LARGE): _NonYieldClass.REFUSED,
        _vocabulary_key(FetchRefusal.EXTRACTION_FAILED): _NonYieldClass.FAILED,
        # --- StructuredOutcome (ADR-0240 §10, five members) ---------------------
        _vocabulary_key(StructuredOutcome.NOT_ASKED): _NonYieldClass.UNREACHED,
        _vocabulary_key(StructuredOutcome.NO_SEPARATOR): _NonYieldClass.UNREACHED,
        _vocabulary_key(StructuredOutcome.NO_SLOT): _NonYieldClass.UNREACHED,
        _vocabulary_key(StructuredOutcome.RETURNED_NOTHING): _NonYieldClass.ANSWERED,
        _vocabulary_key(StructuredOutcome.RETURNED_RECORDS): _NonYieldClass.ANSWERED,
        # --- ForecastDisposition (ADR-0260 §8, twelve members) ------------------
        _vocabulary_key(ForecastDisposition.NOT_CONFIGURED): _NonYieldClass.REFUSED,
        _vocabulary_key(ForecastDisposition.NO_BUDGET): _NonYieldClass.UNREACHED,
        _vocabulary_key(ForecastDisposition.BINDING_FAILED): _NonYieldClass.FAILED,
        _vocabulary_key(ForecastDisposition.RULING_CONFIRM): _NonYieldClass.REFUSED,
        _vocabulary_key(ForecastDisposition.RULING_DENY): _NonYieldClass.REFUSED,
        _vocabulary_key(ForecastDisposition.RULING_UNAVAILABLE): _NonYieldClass.REFUSED,
        _vocabulary_key(ForecastDisposition.SPEND_REFUSED): _NonYieldClass.REFUSED,
        _vocabulary_key(ForecastDisposition.TRANSPORT_FAILED): _NonYieldClass.FAILED,
        _vocabulary_key(ForecastDisposition.DEADLINE_EXPIRED): _NonYieldClass.EXPIRED,
        _vocabulary_key(ForecastDisposition.RESPONSE_TOO_LARGE): _NonYieldClass.FAILED,
        _vocabulary_key(ForecastDisposition.PROVIDER_REFUSED): _NonYieldClass.REFUSED,
        _vocabulary_key(ForecastDisposition.UNATTESTED): _NonYieldClass.REFUSED,
        # --- ForecastRefusal (ADR-0260 §4, §8, six members) ---------------------
        _vocabulary_key(ForecastRefusal.TRANSPORT_FAILED): _NonYieldClass.FAILED,
        _vocabulary_key(ForecastRefusal.DEADLINE_EXPIRED): _NonYieldClass.EXPIRED,
        _vocabulary_key(ForecastRefusal.RESPONSE_TOO_LARGE): _NonYieldClass.FAILED,
        _vocabulary_key(ForecastRefusal.PROVIDER_REFUSED): _NonYieldClass.REFUSED,
        _vocabulary_key(ForecastRefusal.UNATTESTED): _NonYieldClass.REFUSED,
        _vocabulary_key(ForecastRefusal.NO_RESULT): _NonYieldClass.ANSWERED,
    }
)


#: The six vocabularies :data:`_NON_YIELD_CLASSES` must be total over, named once so
#: the import-time check and the test that pins it cannot disagree about the set.
_NON_YIELD_VOCABULARIES: Final = (
    SearchDisposition,
    SearchRefusal,
    FetchRefusal,
    StructuredOutcome,
    ForecastDisposition,
    ForecastRefusal,
)

_unplaced = sorted(
    f"{vocabulary.__name__}.{member.name}"
    for vocabulary in _NON_YIELD_VOCABULARIES
    for member in vocabulary
    if _vocabulary_key(member) not in _NON_YIELD_CLASSES
)
if _unplaced:  # pragma: no cover — an unplaceable member is a build-time defect
    _message = (
        "every typed non-yield is placed in _NON_YIELD_CLASSES by name (ADR-0251 §2's "
        f"'no default branch and no fallback member'); unplaced: {', '.join(_unplaced)}"
    )
    raise RuntimeError(_message)
del _unplaced


@dataclass(frozen=True, slots=True)
class AskFacts:
    """The four facts ADR-0251 §2's classifier decides one ask's outcome from.

    **Four facts and not an enum-to-enum table**, which is the clause this type
    exists to hold: "no source enumeration determines the answer on its own —
    ``StructuredOutcome.RETURNED_RECORDS`` describes both a read that added records
    and one whose every record deduplicated out, and a ``MemorySearchResult`` can be
    ``capped`` while still admitting records."

    **Recorded per ask, by the servicing, as each ask completes** — never recomputed
    downstream and never derived from :class:`ServicedRead`, whose counts are stated
    over the whole servicing rather than per ask.

    **Fact 1's first limb is answered by not building one of these.** "Whether the
    servicing's stage ran to its end" has two halves: a stage that did not complete
    reaches no construction site at all, and ADR-0226 §5's all-or-nothing degradation
    discards the facts the asks before it had already produced — so a servicing that
    failed or was partial carries **no** entry, which is §2's precedence case 1
    exactly. What :attr:`reached` holds is the same case's *per-ask* half: an ask that
    was emitted and put to no source, which today is a ``LOCAL_FILE`` label that
    resolved to nothing and a ``CITATION_HOP`` whose every label did.

    Attributes:
        ask: The ask the planner emitted, carried unaltered (ADR-0251 §3).
        reached: Whether this ask was put to a source at all.
        non_yield: The source's typed non-yield, where it produced one, in whichever
            of the four vocabularies that source speaks; ``None`` where it produced
            none.
        records: The records the ask returned, **before** ADR-0226 §7's deduplication
            and before §6's budget, in the order the source produced them. ADR-0252 §3
            composes one region of a ``GoalEvidence`` row's ``supported`` per member,
            "from that record's own values and never from the ask", and §1 names the
            store-resident ones on the row.
        admitted: How many it admitted, **after** it.
        certified: Whether the source certified that the answer was complete. ``False``
            where ADR-0226 §6's budget cut this kind's yield, where
            ``MemorySearchResult.capped`` was ``True`` (ADR-0128 §2), or where a
            structured read's own window ceiling bound it.
        source: The **reading's own declared identity**, where the servicing has one
            (ADR-0252 §1, ADR-0260 §9). ``None`` on every kind whose ``ReadKind``
            member is the whole of the source identity, which is the five ADR-0252 §1's
            producers write and is why that clause says ``source`` "is absent on every
            row this decision's producers write".

            **A forecast read is the one kind that has a finer one**: §9 makes it "the
            forecaster's ``name``", which ADR-0260 §4 defines as the **source
            instance** — "the owner's forecast" — and "never a vendor, never an origin,
            never a URL, never a credential and **never a place**". That is what admits
            it into a durable row at all, ADR-0252 §1 forbidding a provider name, a
            host, an address, a path, a ``Settings`` field name or a credential
            identity there; and it is what makes ADR-0252 §8's limb 3 finer than the
            kind, so two deployments' forecasters never refresh one another's rows.
    """

    ask: ReadAsk
    reached: bool
    non_yield: _NonYield | None
    records: tuple[MemoryRecord, ...]
    admitted: int
    certified: bool
    source: str | None = None

    @property
    def returned(self) -> int:
        """How many records the ask returned, **before** ADR-0226 §7's deduplication.

        **Derived and never stored beside the records**, because the two would be one
        fact with two carriers and the first implementation to disagree with itself
        would be right in one of them. ADR-0251 §2's classifier reads this; ADR-0252 §1
        persists it on the row, where it is what discloses a ``records`` tuple
        :data:`~ai_assistant.core.types.MAX_EVIDENCE_RECORDS` truncated.

        Returns:
            The count.
        """
        return len(self.records)


def classify_read_outcome(facts: AskFacts) -> ReadOutcomeKind | None:  # noqa: PLR0911 — ADR-0251 §2's precedence is eight numbered limbs evaluated in order "with no default branch and no fallback member", so one exit per limb is the decision rather than a shape to fold
    """Decide what became of one ask, or that it earns no entry (ADR-0251 §2).

    **§2's precedence, in §2's order, with no default branch and no fallback
    member.** 1 no entry at all; 2 ``EXPIRED``; 3 ``FAILED``; 4 ``REFUSED``; 5
    ``EMPTY`` where the source returned no record at all before deduplication; 6
    ``DUPLICATE`` where it returned records and admitted none after it; 7
    ``RETURNED_RECORDS`` where it admitted at least one; and 8 ``TRUNCATED``
    displacing 5, 6 and 7 — **and only those** — where completeness was not
    certified.

    **8 displaces only 5, 6 and 7, which is why it is tested after 1 to 4 and before
    them.** A cut, capped or ceiling-bound answer is ``TRUNCATED`` whether it admitted
    records, admitted only duplicates or admitted none; a refused or expired one is
    not, because those sources answered about the *ask* rather than about the yield.

    **``Servicing`` is not an input**, and deliberately: it is the stage's disposition
    for the whole request rather than an answer about one ask, so
    ``Servicing.DECLINED`` lands in case 1 by the caller never reaching this function
    and ``Servicing.SERVICED`` says nothing about any individual ask.

    **It reads no vocabulary but** :data:`_NON_YIELD_CLASSES`, so a member added to
    any source enumeration without a class is a build-time failure rather than a
    silent fifth outcome.

    Args:
        facts: The four facts, recorded by the servicing for this one ask.

    Returns:
        The member this ask reached, or ``None`` where §2's case 1 says it earns no
        entry in the planner's carrier at all.
    """
    if not facts.reached:
        return None
    classified = (
        _NonYieldClass.ANSWERED
        if facts.non_yield is None
        else _NON_YIELD_CLASSES[_vocabulary_key(facts.non_yield)]
    )
    match classified:
        case _NonYieldClass.UNREACHED:
            return None
        case _NonYieldClass.EXPIRED:
            return ReadOutcomeKind.EXPIRED
        case _NonYieldClass.FAILED:
            return ReadOutcomeKind.FAILED
        case _NonYieldClass.REFUSED:
            return ReadOutcomeKind.REFUSED
        case _NonYieldClass.ANSWERED:
            pass
    if not facts.certified:
        return ReadOutcomeKind.TRUNCATED
    if facts.returned == 0:
        return ReadOutcomeKind.EMPTY
    if facts.admitted == 0:
        return ReadOutcomeKind.DUPLICATE
    return ReadOutcomeKind.RETURNED_RECORDS


@dataclass(slots=True)
class _AskLedger:
    """ADR-0251 §2's four facts, recorded one ask at a time as a servicing runs.

    **The deltas are taken since the previous note rather than from a mark the
    caller keeps**, and that is exact rather than approximate: ADR-0226 §1 admits at
    most one ask of each kind per request, §6 services them in a fixed order, every
    admission a servicing makes is made by the ask being serviced at that moment, and
    an ask the request did not carry makes none — so the counters cannot move between
    two notes on account of anything but the ask the later note is for. It also
    removes the failure a caller-held mark invites, which is reading one counter
    before a kind and the other after it and reporting one ask's admissions against a
    neighbour's returns.

    **The truncation test is here rather than at each site**, because ADR-0226 §6's
    cut is recorded per kind in one list and the test is the same sentence for all
    five. A source that has its *own* reason to leave completeness uncertified — the
    store's candidate ceiling (ADR-0128 §2) — passes it as ``certified=False``, and
    the two grounds are ANDed: either one alone is enough to make the answer
    uncertified.

    **Nothing is classified here.** This records facts; :func:`classify_read_outcome`
    decides, and only on the success path — a servicing that failed or was partial
    leaves this ledger holding the facts of the asks it had already put and nobody
    reads them, which is ADR-0226 §5's all-or-nothing posture and §2's precedence
    case 1.

    Attributes:
        union: The turn's union under construction, whose two counters the per-ask
            figures are differenced from.
        truncated: The servicing's truncation list, read by :meth:`note`.
        facts: One record per ask noted, in servicing order.
    """

    union: _Union
    truncated: list[ReadKind]
    facts: list[AskFacts] = field(default_factory=list)
    _returned: int = 0
    _admitted: int = 0

    def note(  # noqa: PLR0913 — ADR-0251 §2's four facts, ADR-0226 §7's records and ADR-0252 §1's source identity; each is a distinct fact about one ask and none is derivable from another
        self,
        ask: ReadAsk,
        *,
        reached: bool,
        non_yield: _NonYield | None,
        certified: bool = True,
        records: Sequence[MemoryRecord] | None = None,
        source: str | None = None,
    ) -> None:
        """Record what became of one ask, and advance the mark.

        Args:
            ask: The ask the planner emitted, carried unaltered.
            reached: Whether it was put to a source at all (ADR-0226 §3's silently
                discarded label and a read the budget left no slot for are the two
                cases this is ``False`` for).
            non_yield: The source's typed non-yield, or ``None`` where it produced
                none.
            certified: Whether the source certified completeness on a ground of its
                own, ANDed here with ADR-0226 §6's budget cut for this kind.
            records: What the ask returned **before** deduplication, where that is not
                what the union was offered. ``None`` — every kind but the citation hop —
                takes the union's own delta. The hop is the exception because ADR-0229
                §2 deliberately withholds the *named* records from the union: "a record
                named by a label is counted in none of the three", so the union sees a
                hop's evidence alone and a hop that reached a live record carrying no
                citations would otherwise look like a source that returned nothing.

                **It is a sequence where it was a count, and the count is now derived
                from it** (ADR-0252 §3). What ADR-0251 §2's classifier needs is the
                figure; what a ``GoalEvidence`` row's ``supported`` is composed from is
                the records themselves, "one region per record the ask **returned**" —
                so the records are recorded and :attr:`AskFacts.returned` reads their
                length, rather than a producer keeping the two in step by hand.
            source: The reading's own declared identity, where this kind's servicing has
                one (ADR-0252 §1, ADR-0260 §9). ``None`` — every kind but the forecast
                read — leaves the row's ``source`` absent, which is what ADR-0252 §1
                says of every row its own producers write.
        """
        offered, admitted = len(self.union.offered), len(self.union.admitted)
        self.facts.append(
            AskFacts(
                ask=ask,
                reached=reached,
                non_yield=non_yield,
                records=(
                    tuple(self.union.offered[self._returned :])
                    if records is None
                    else tuple(records)
                ),
                admitted=admitted - self._admitted,
                certified=certified and ask.kind not in self.truncated,
                source=source,
            )
        )
        self._returned, self._admitted = offered, admitted


@dataclass(frozen=True, slots=True)
class AskYield:
    """One outcome entry, and what the ask it is for actually returned.

    **One value where two sequences would have to be kept parallel.** ADR-0251 §3's
    carrier tells the planner what became of an ask; ADR-0252 §14 has that same entry
    produce **exactly one** ``GoalEvidence`` row, whose ``supported`` is composed from
    the records the ask returned (§3) and whose two counts are ADR-0226 §9's. Those are
    two consumers of one classification, so they travel together: a servicing that
    returned a shorter records tuple than its outcome sequence is not constructible.

    **The entry itself is derived and never stored**, on the rule that decides every
    such pair in this module: two carriers for one fact leave the first implementation
    to disagree with itself right in one of them. What is stored is the classification
    (:attr:`outcome`) and the planner's own ask, which is all
    :class:`~ai_assistant.core.types.ReadAskOutcome` carries.

    Attributes:
        ask: The ask the planner emitted, carried back **byte for byte** (ADR-0251 §3).
        outcome: What :func:`classify_read_outcome` decided became of it (§2).
        records: What the ask returned, **before** ADR-0226 §7's deduplication, in the
            order the source produced them. Empty on every member whose source returned
            no record at all.
        admitted: How many of those the supply did not already hold, which is ADR-0226
            §9's ``new`` and ADR-0252 §1's ``admitted``.
        source: The reading's own declared identity, or ``None`` (ADR-0252 §1, ADR-0260
            §9). It travels on this value for :attr:`records`' reason: the row and the
            planner's entry are two consumers of one classification, and a source paired
            with the entry downstream would be a second authority on which reading a row
            is about.
    """

    ask: ReadAsk
    outcome: ReadOutcomeKind
    records: tuple[MemoryRecord, ...]
    admitted: int
    source: str | None = None

    @property
    def entry(self) -> ReadAskOutcome:
        """ADR-0251 §3's own entry for this ask.

        Returns:
            The frozen pair the planner's next call is handed.
        """
        return ReadAskOutcome(ask=self.ask, outcome=self.outcome)


def classified_reads(facts: Sequence[AskFacts]) -> tuple[AskYield, ...]:
    """ADR-0251 §3's carrier for one servicing, in servicing order.

    **Exactly one entry per ask the servicing reached, and every ask it reached has
    one** (§2). An ask :func:`classify_read_outcome` returns ``None`` for contributes
    nothing, which is the whole of how case 1 reaches the carrier.

    **One classification, two consumers** (ADR-0252 §14). The sequence the planner's
    next call receives and the entries a ``GoalEvidence`` row is written per are the
    same sequence, so classifying twice would be two authorities on what became of one
    ask — which is why the records ride out on the same value rather than being paired
    with it downstream.

    Args:
        facts: One record per ask this servicing emitted, in the order §6 services
            the kinds in.

    Returns:
        The yields, each carrying the planner's own ask byte for byte.
    """
    return tuple(
        AskYield(
            ask=one.ask,
            outcome=outcome,
            records=one.records,
            admitted=one.admitted,
            source=one.source,
        )
        for one in facts
        if (outcome := classify_read_outcome(one)) is not None
    )


#: The fields a re-reading of the same material moves, dropped from a record's
#: :func:`held_names` body name.
#:
#: All three answer *when this reading was taken* rather than *what this record is*.
#: ``last_updated`` is transaction time — ADR-0109 §2's "when **we** last revised the
#: belief" — ``last_confirmed_at`` is when the world last confirmed it, and
#: ``Attestation.reported_at`` is "the instant the reporting source asserts the fact was
#: current, **on that source's own clock**" (ADR-0092 §3). Two servicings of one turn
#: that read the same material twice differ in exactly these and in the minted id: a
#: ``WEB_SEARCH`` takes its three instants from the provider's declared instant
#: (ADR-0231 §10), and a provider answering the same query six seconds later declares a
#: later one for the same results. Keeping them in the name is what made ADR-0226 §7's
#: deduplication unreachable on that path (#2364).
#:
#: Nothing here is reconciled, substituted or rewritten: the held record keeps every
#: instant it arrived with, and §7's "the copy the supply already held keeps its
#: position" is what disposes of the second arrival.
_READING_INSTANTS: Final = ("last_updated", "last_confirmed_at")


def held_names(record: MemoryRecord) -> tuple[str, str]:
    """The two names one record answers to in ADR-0226 §7's deduplication.

    §7 says what is deduplicated — "A record the servicer returns that the supply
    already holds is deduplicated out, and the copy the supply already held keeps its
    position" — and names no field the sameness is decided on. It states the mischief
    instead: a servicer that seeds too narrowly "would satisfy the clause above and
    still **render one record twice and spend two of the ten on it**", and it applies
    ADR-0158 §4's rule "for its reason", which is what a prompt may not repeat. So a
    record answers to **two** names and is already held where the supply holds either.

    **The id, because a store record's id is its name.** ADR-0158 §4's own case is the
    continuity tail and a relevance read returning "records of the same store, with the
    same ids", and the store is free to hand a second read of one turn a *revised* copy
    of a record the supply already holds — ADR-0113 §5's "no cross-call read consistency
    of any kind", which ADR-0251 §7 quotes for this exact case. Same id, moved bytes:
    the body name would miss it and this one does not.

    **The body, because a record that has no durable name has nothing else to be known
    by.** A minted record's id "is minted for one turn, rendered to no model, accepted
    from none, and resolves in no store" (ADR-0231 §16, ADR-0230 §10) — so two
    servicings of one turn that search for the same thing and are handed the same
    results mint two ids that can never match, and a deduplication keyed on the id alone
    is vacuous on that path however identical the records are (#2364). The body is the
    record as this system holds it, less its minted name and less
    :data:`_READING_INSTANTS`.

    **This mints nothing and changes nothing about what a record is.** ADR-0092 §6's
    ruling stands untouched: it governs the ``id`` an ``EXTERNAL`` producer **proposes**
    a record at — "the address a record is written at, and … an instruction to replace
    whatever already lives there" — and refuses to derive one from content. Nothing
    here reaches a producer, a proposal or a store: the names are computed by the
    consumer, over the supply it is assembling, and are discarded with the turn. A
    searcher minting a content-derived id would be the ruling ADR-0092 §6 declined to
    make, which is why the deduplication and not the mint is where this is decided.

    **And it compares no ask with another.** ADR-0251 §7 forbids that under any
    spelling, and this reads neither ask: it reads the records a source handed back,
    after a read the loop refused nothing about and serviced in full.

    Args:
        record: The record to name. Read, never written.

    Returns:
        The id name and the body name, in that order. Both are namespaced, so a name of
        one sort can never be a name of the other.
    """
    body = record.model_dump(mode="json")
    body.pop("id", None)
    provenance = body.get("provenance")
    if isinstance(provenance, dict):
        for instant in _READING_INSTANTS:
            provenance.pop(instant, None)
        attestation = provenance.get("attestation")
        if isinstance(attestation, dict):
            attestation.pop("reported_at", None)
    return (
        f"id:{record.id}",
        "body:" + json.dumps(body, sort_keys=True, separators=(",", ":"), default=str),
    )


def admitted_fourth_group(
    records: Sequence[MemoryRecord], *, held: Collection[MemoryRecord]
) -> tuple[MemoryRecord, ...]:
    """ADR-0226 §6's budget and §7's deduplication, over one kind's records.

    **The one place a fourth group is built outside** :func:`service_read_request`
    (ADR-0244 §7, §8). An approved read's continuation appends the records the dispatch
    minted to a supply assembled at the instant of the resume, and ADR-0244 §7 retains
    ADR-0226 §6's budget and §7's deduplication over them unchanged: "they are
    deduplicated and admitted under ADR-0226 §6's budget of ten". A resumed turn
    performs no servicing, so :class:`_Union` has nothing else to account for there —
    what it needs is this function's two rules and not that class's counts.

    **The seen set grows with every admission**, which is §7's deduplication "over the
    whole union and not only against the pre-servicing supply": two records of one batch
    sharing a name enter once, and the second consumes no slot. A caller seeding from the
    supply alone would satisfy the narrower clause and still render one record twice.

    **It takes the held records and not their ids**, because §7's sameness is
    :func:`held_names`' two names and a caller cannot be trusted to compute them: an
    argument of ids would let a call site silently ask for the narrower test, which is
    the state #2364 records.

    **The budget is not a parameter, and that is ADR-0226 §6 rather than an
    inflexibility.** §6 fixes it at ten and rules that "no configuration, setting or
    later lane makes the count configurable without the ADR that decides it", so the
    figure is read from :data:`READ_BUDGET` here exactly as it is at the servicing site.

    Args:
        records: The candidates, in the order the kind that produced them minted them.
        held: The records the supply already holds. Read, never written.

    Returns:
        What ADR-0226 §6 and §7 admit, in the order given.
    """
    seen = {name for record in held for name in held_names(record)}
    admitted: list[MemoryRecord] = []
    for record in records:
        if len(admitted) >= READ_BUDGET:
            break
        names = held_names(record)
        if seen.intersection(names):
            continue
        seen.update(names)
        admitted.append(record)
    return tuple(admitted)


def not_serviced(  # noqa: PLR0911 — ADR-0242 §8's table has one arm per discriminated row, and collapsing them behind a mapping would hide the rows the destination's standing and a written park decide
    disposition: SearchDisposition | None,
    *,
    planned_with_external_content: bool = False,
    trust: DestinationTrust = DestinationTrust.UNCHOSEN,
    parked: bool = False,
) -> SearchNotServiced | None:
    """ADR-0242 §8's mapping as ADR-0244 §12 discriminates it, at the servicing site.

    **Total over all seventeen** :class:`SearchDisposition` **members and
    non-injective, and that is the design rather than a compromise** (ADR-0242 §8).
    ``SearchDisposition`` names *the stage that produced the outcome*, for an operator
    reading an audit; :class:`~ai_assistant.core.types.SearchNotServiced` names *the
    act that would change it*, for the user reading a reply. Two dispositions with one
    act behind them are one member, and one disposition with two acts behind it is two
    members. **No lane makes this injective**, restores a stage name to it, or reports a
    ``SearchDisposition`` value to a user.

    **The discriminating inputs are the ones the site already holds** (§7), and
    nothing here derives a value from the plan, the supply's length, the reply, the
    audit, a store read of its own or any content. ``planned_with_external_content`` is
    read off the binding the request carried; and ``trust`` is where the caller's
    destination stands, **carried here as data rather than read here**. **The fourth
    input is gone** (ADR-0247 §5, §6): ``max_calls`` was
    ``Settings.search_calls_per_conversation``, and it discriminated one row of §8's
    table whose two members are both removed, so the parameter has nothing left to
    decide and no caller holds the value. ADR-0247 §1 stops the
    servicing site taking a ``trust_of`` answer at all, so what the caller passes is
    ``USER_CHOSEN`` for the configured provider — which §1 makes the destination the
    owner chose — and the parameter keeps its type because ADR-0242 §8's table is stated
    over that vocabulary and this ADR moves no member of it.

    **A member minted by a later ADR maps to** ``UNAVAILABLE`` (§8), which is the
    least-claiming member: an unmapped disposition degrades to silence about the reason
    rather than to a wrong reason. The ``case _`` below is that rule, and the totality
    arm over the seventeen is what makes forgetting a *deliberate* mapping a test
    failure rather than a silent ``UNAVAILABLE``.

    Args:
        disposition: What this servicing's ``WEB_SEARCH`` ask resolved to, or ``None``
            where it yielded records, reached the provider and returned none, or where
            no such ask was made.
        planned_with_external_content: ADR-0181 §4's fact for the request this
            servicing built, or ``False`` where it built none — in which case no
            ``RULING_CONFIRM`` can have been recorded and the value is not read.
        trust: Where this deployment's search destination stands: ``USER_CHOSEN`` for
            the configured provider (ADR-0247 §1), or ``UNCHOSEN`` where the caller
            holds no destination to speak for — which is every caller that never built
            a request, and ``parked_reads.py``'s refusal branch, whose disposition
            reads this argument in no arm.
        parked: Whether this servicing **wrote a park** for the ``CONFIRM`` it
            recorded (ADR-0244 §12). **A fact the site holds and not a store read**:
            the site wrote the park, or its ``park`` answered ``False``, and that
            boolean is the whole of the further input. No renderer, no adapter and no
            composing stage reads ``ParkedReads`` to compute a member, and no component
            recomputes the carrier downstream.

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
        case SearchDisposition.SPEND_REFUSED:
            return SearchNotServiced.SPEND_EXHAUSTED
        case SearchDisposition.RULING_DENY:
            return SearchNotServiced.DECLINED
        case SearchDisposition.RULING_CONFIRM:
            if parked:
                # ADR-0244 §12's first row: "`RULING_CONFIRM`, any binding, any
                # `trust_of` answer, park written → `ANSWER_AWAITED`". The
                # discrimination is **obligatory rather than cosmetic**: a parked
                # decision is not one the establishing act may ride (§5's eighth
                # condition), so reporting it as `AUTHORISATION_AWAITED` would falsify
                # that member's own "asserts exactly two things, both established"
                # clause — and `TRUST_MISSING`'s and `UNAVAILABLE`'s clauses are
                # preserved by the same move.
                return SearchNotServiced.ANSWER_AWAITED
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
            # naming an act that cannot help is worse than naming none.
            #
            # **`TRUST_MISSING` is unreachable on a deployment that configured a search
            # provider, and it stays** (ADR-0247 §6, which names it and rules that "no
            # lane removes them"). The member is defined over a `trust_of` read
            # answering `UNCHOSEN`, and ADR-0247 §1 stops the servicing site taking
            # that read: every caller that reached a `RULING_CONFIRM` here is past
            # `WebSearcher.request` answering a proposal, so it holds a registration
            # and passes `USER_CHOSEN`. Removing the arm is outside the owner's ruling
            # — which named the budget and its dependents and left the choosing act
            # standing for every other destination — and #2252 is the issue §13 defers
            # it on. So the branch is written as it was and simply has no producer.
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


#: ADR-0260 §10's fold, **stated totally over the twelve dispositions** — "because a
#: fold whose domain is not enumerated is a fold two implementations will disagree
#: about" — and read by :func:`forecast_not_read`.
#:
#: **It is non-injective and that is the point** (ADR-0242 §8): :class:`ForecastDisposition`
#: names *the stage that produced the outcome*, for an operator reading an audit;
#: :class:`~ai_assistant.core.types.ForecastNotRead` names *the class of act*, for the
#: user reading a reply. **Seven dispositions the user has no act for fold onto
#: ``UNAVAILABLE``**, which names none — and §10's statement for that member names no
#: cause and no act, so the collapse costs the user nothing they could have used.
#:
#: **A contact and an ``UNAVAILABLE`` ride together where both hold** (§10): a
#: ``RESPONSE_TOO_LARGE`` and an ``UNATTESTED`` each reached the provider and yielded
#: nothing usable, which is ADR-0264 §8's both-statements rule and not an exception to
#: it. Nothing here reads :data:`FORECAST_CONTACTS` and nothing there reads this.
#:
#: **No member of this mapping is derived from a name, a prefix or a substring**, and
#: §13's arm (k) walks all twelve — "a rule stated totally and tested selectively is one
#: an implementation can leave partial while passing every other arm".
FORECAST_NOT_READ: Final[Mapping[ForecastDisposition, ForecastNotRead]] = MappingProxyType(
    {
        ForecastDisposition.NOT_CONFIGURED: ForecastNotRead.NOT_CONFIGURED,
        ForecastDisposition.RULING_CONFIRM: ForecastNotRead.AUTHORISATION_AWAITED,
        ForecastDisposition.SPEND_REFUSED: ForecastNotRead.SPEND_EXHAUSTED,
        ForecastDisposition.RULING_DENY: ForecastNotRead.DECLINED,
        ForecastDisposition.DEADLINE_EXPIRED: ForecastNotRead.INTERRUPTED,
        ForecastDisposition.NO_BUDGET: ForecastNotRead.UNAVAILABLE,
        ForecastDisposition.BINDING_FAILED: ForecastNotRead.UNAVAILABLE,
        ForecastDisposition.RULING_UNAVAILABLE: ForecastNotRead.UNAVAILABLE,
        ForecastDisposition.TRANSPORT_FAILED: ForecastNotRead.UNAVAILABLE,
        ForecastDisposition.RESPONSE_TOO_LARGE: ForecastNotRead.UNAVAILABLE,
        ForecastDisposition.PROVIDER_REFUSED: ForecastNotRead.UNAVAILABLE,
        ForecastDisposition.UNATTESTED: ForecastNotRead.UNAVAILABLE,
    }
)

_unfolded = sorted(member.name for member in ForecastDisposition if member not in FORECAST_NOT_READ)
if _unfolded:  # pragma: no cover — an unfolded member is a build-time defect
    _fold_message = (
        "ADR-0260 §10's fold is stated totally over the twelve dispositions; "
        f"unfolded: {', '.join(_unfolded)}"
    )
    raise RuntimeError(_fold_message)
del _unfolded

_unplaced_contacts = sorted(
    member.name for member in ForecastDisposition if member not in FORECAST_CONTACTS
)
if _unplaced_contacts:  # pragma: no cover — an unplaced member is a build-time defect
    _contact_message = (
        "ADR-0260 §10's establishment partition is total over the twelve dispositions; "
        f"unplaced: {', '.join(_unplaced_contacts)}"
    )
    raise RuntimeError(_contact_message)
del _unplaced_contacts


def forecast_not_read(disposition: ForecastDisposition | None) -> ForecastNotRead | None:
    """ADR-0260 §10's fold, at the servicing site (§8, ADR-0242 §8).

    **Total over the twelve and non-injective by design.** The member is read straight
    off :data:`FORECAST_NOT_READ`, which states the fold member for member; there is no
    default branch, because §10 enumerates its whole domain precisely so that two
    implementations cannot disagree about one.

    **A servicing that yielded carries no member** (§10). ``None`` in means ``None``
    out, and that absence covers exactly two states: a read the provider answered,
    records or none, and a turn that serviced no forecast read at all. **It means
    nothing else**, and in particular it is not a report that the provider answered —
    the site that needs that distinction holds :attr:`ServicedRead.forecast_serviced`
    and the contact, not this member.

    **Nothing is discriminated here** (§10). Where ADR-0242 §8's search mapping reads a
    binding's fact, a destination's standing and a written park, this reads its one
    argument: §6's route (c) leaves a forecast read no park, no grant seam and no trust
    question, so there is no second input for a row to turn on.

    Args:
        disposition: What this servicing's forecast ask resolved to, or ``None`` where
            it yielded, where the provider answered with nothing, or where no such ask
            was serviced.

    Returns:
        The member the turn would carry for it, or ``None``.
    """
    if disposition is None:
        return None
    return FORECAST_NOT_READ[disposition]


def earliest_not_read(
    held: ForecastNotRead | None, produced: ForecastNotRead | None
) -> ForecastNotRead | None:
    """Fold one servicing's member into the turn's, by ADR-0260 §10's precedence.

    **At most one member is carried per turn**, and where a revising turn serviced more
    than one forecast read the member carried is the one **earliest in
    ``ForecastNotRead``'s declared order** among them — §10 declares the members *"in
    precedence order"* and applies ADR-0242 §7's rule at this seam unchanged. **The
    order and not the encounter order decides it**, so an implementation carrying the
    last member it computed is wrong even where every individual fold is right, as is
    one assigning only while the carrier is ``None`` — which is why §13's arm (h)
    requires **both** encounter orders.

    **A later read does not clear an earlier one's member** (§10): "a turn that was
    denied and then answered still reports ``DECLINED``, because the user was told
    about a read this turn did not make and a second read does not unmake it". So a
    ``None`` here leaves ``held`` exactly as it was.

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
    order = tuple(ForecastNotRead)
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
        withheld: ADR-0238 §11's second count: how many records §3's filter kept out of
            that supply. **The definition is unchanged and is now zero on every path**
            (ADR-0246 §7). On a chosen destination ADR-0246 §1 leaves no placement
            filter at all, so the filter withholds nothing; on an ``UNCHOSEN`` one the
            whole population is withheld by §2's **trust clause** and not by the filter,
            which is the zero this tree already wrote. **No lane deletes the field**
            because §1 makes it constant — ADR-0238 §11's enumeration keeps four counts
            — and **no lane, surface or measurement reads the fall in this number as
            fewer withholdings**: a deployment that watched only it would see the system
            withholding nothing and conclude nothing was flowing.
        supplied_narrowed: ADR-0245 §7's added count, which ADR-0246 §7 keeps and
            widens: how many of the records this servicing **supplied** to the composer
            carry a reach that is not
            :attr:`~ai_assistant.core.types.PlacementReach.ANYONE` — **now over every
            setter**, an ``OWNER_ACT`` and a ``PROPOSED`` narrowing included. It is
            where the truth is once ``withheld`` is constant, and no lane adds a
            further count or a per-setter breakdown of it (ADR-0246 §7, §12). A count
            and never an identifier, on the same event under the same key at the same
            emission point as the other two (ADR-0238 §11, as ADR-0247 §6 leaves it).
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
        forecast_serviced: ADR-0260 §7's first added field: whether this servicing
            **put a ``FORECAST_READ`` ask to the forecast stage at all**. ``True`` on
            every outcome of an ask this servicing reached, ``NO_BUDGET`` and
            ``NOT_CONFIGURED`` included, **and on a servicing the forecast stage itself
            then failed or a cancellation carried away** — the mark is taken before that
            stage is awaited, which is what makes it true of a stage that then raised.
            ``False`` where the request carried no such ask and where the servicing
            raised **before** the forecast's position in §7's order.

            **Two fields and not one, because neither is derivable from the other**
            (§7). An absent :attr:`forecast` covers both a read the provider answered
            and an ask this servicing never reached, so a record holding only the
            disposition cannot tell a deployment reading a 0% yield for this kind which
            of the two it is looking at — the collapse ADR-0226 §9 refuses one field
            over for the unresolved-label count. **A boolean and never a count**: no
            day, no place, no coordinate, no origin, no account and no ``Settings``
            field name is anywhere near it, which is §9's counts-and-no-copy rule
            binding unchanged.
        forecast: ADR-0260 §7's second added field: the :class:`ForecastDisposition`
            this servicing's ``FORECAST_READ`` ask resolved to, where it resolved to
            one, and ``None`` in the two cases §8 leaves it empty — where the read
            yielded records, and where it **reached the provider and returned none**,
            which :attr:`~ai_assistant.core.types.ForecastRefusal.NO_RESULT` maps to no
            disposition precisely so that ADR-0226 §9's returned count is not
            double-counted.

            A **member of a closed enumeration and never free text**, for
            :attr:`disposition`'s reason and ADR-0004 §5's: there is nowhere here for a
            place, a coordinate, a day, an origin, a provider message, a monetary figure
            or an exception type to sit. It **rides on a failing record too**, exactly
            as :attr:`refusal` and :attr:`disposition` do: a forecast that declined
            before a later kind's read raised is neither of §8's two empty cases, and
            dropping it would report that turn as one whose planner never asked for a
            forecast.

            **No count of dropped days is beside it** (§7). Such a count is a
            *within-ask* fidelity fact, and ADR-0226 §9 refuses that class in terms —
            every count there "is taken over a servicing that completed" and is zero on
            one that failed. The honest consequence, that a response this system thinned
            is not distinguishable here from one the provider gave thin, is ADR-0260
            §14's deferral rather than a gap this record fills.
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
        outcomes: ADR-0251 §7's one added per-servicing field: the
            :class:`~ai_assistant.core.types.ReadOutcomeKind` of each ask this
            servicing **reached**, in ADR-0226 §6's servicing order — the same
            sequence, member for member, that §3's carrier hands the next planner
            call. Empty on a servicing that failed or was partial, which reaches no
            ask's outcome at all (§2's precedence case 1), and on one that reached
            none.

            **Members of a closed enumeration and never free text**, which is what
            admits it under ADR-0226 §9's counts-and-kinds rule at all: the ask
            itself is *not* here — no query, no label, no window, no axis value —
            because §9 copies no text and the ask stays durable on the frozen
            ``ActionPlan``. What the field buys is the **stop distribution's**
            companion: ADR-0251 §14 fires the revision of §5's figures off this
            record, and a distribution over stops with no account of what the reads
            returned cannot say whether a bound fired on an attempt that was
            learning or on one that was not.
    """

    kinds: tuple[ReadKind, ...] = ()
    records: tuple[MemoryRecord, ...] = ()
    returned: int = 0
    new: int = 0
    deduplicated: int = 0
    labels_unresolved: int = 0
    refusal: FetchRefusal | None = None
    disposition: SearchDisposition | None = None
    forecast_serviced: bool = False
    forecast: ForecastDisposition | None = None
    supplied: int = 0
    withheld: int = 0
    supplied_narrowed: int = 0
    structured_axes: tuple[StructuredAxis, ...] = ()
    structured: StructuredOutcome | None = None
    truncated_kinds: tuple[ReadKind, ...] = ()
    failed: bool = False
    failed_after_read_returned: bool = False
    outcomes: tuple[ReadOutcomeKind, ...] = ()


@dataclass(slots=True)
class _Capped:
    """Whether any read behind one ask refused to certify that its answer was whole.

    ADR-0251 §2's fourth fact, threaded into
    :func:`~ai_assistant.orchestration.retrieval.assemble_by_band` as its ``capped``
    observer for :class:`_Reads`' reason: a sighted query is several store calls
    behind one call, and the :class:`~ai_assistant.core.types.MemorySearchResult`
    each of them returned never leaves that function. **Sticky and never cleared** —
    one band that refused to certify is enough, exactly as ADR-0128 §2 states the
    value over one read.
    """

    seen: bool = False

    def note(self) -> None:
        """Record that one read came back ``capped``."""
        self.seen = True


@dataclass(frozen=True, slots=True)
class _Structured:
    """What one ``STRUCTURED_READ`` ask reached, in the three facts its callers need.

    Attributes:
        outcome: Which of ADR-0240 §10's five states the ask reached.
        empty: ADR-0240 §6's fact — whether the read ran and returned no record at
            all, which is the only shape §7's carrier admitted before ADR-0251.
        capped: ADR-0251 §2's fourth fact for this kind — whether the store's own
            candidate ceiling bound the read (ADR-0128 §2). **Separate from the
            budget cut**, which the servicing records in its truncation list: they
            are two different sources of the same uncertainty and either one alone
            leaves completeness uncertified.
    """

    outcome: StructuredOutcome
    empty: bool
    capped: bool = False


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
        read: Whether this ask reached the store at all — ``False`` only where **every**
            label resolved to nothing in the supply, which is the one path that returns
            before ``get_many``. It is **not** derivable from :attr:`unresolved`, and
            that is the distinction ADR-0251 §2 turns on: a label whose record the store
            no longer holds is counted here too (ADR-0229 §4), so a hop whose one label
            named a record deleted between the planning and the read leaves
            ``unresolved`` at its label count having made a completed store call that
            returned nothing. §2's case 1 is "the ask was not made"; that ask was made,
            and what it earns is ``EMPTY``.
    """

    expansion: tuple[MemoryRecord, ...]
    evidence: tuple[MemoryRecord, ...]
    unresolved: int
    read: bool


@dataclass(slots=True)
class _Union:
    """The turn's supply under construction, and what §9 counts about it (§7).

    **The seen set is seeded from the pre-servicing supply and grows with every
    admission**, which is §7's deduplication "over the whole union and not only
    against the pre-servicing supply": a record both kinds reach enters the fourth
    group once, at the hop's position, and its second arrival "consumes no slot of
    the budget". A servicer seeding from the supply alone would satisfy the narrower
    clause and still render one record twice.

    **:attr:`held` holds** :func:`held_names`' **names and never bare ids** — both of
    a record's two, seeded and added together — because §7's sameness is what the
    supply already holds and a minted record has no durable name to hold it by
    (#2364). :meth:`admit` is the only writer.
    """

    held: set[str]
    budget: int
    admitted: list[MemoryRecord] = field(default_factory=list)
    #: Every record any kind offered, in the order it was offered — **before** §7's
    #: deduplication and before §6's budget, so it is the sequence ADR-0252 §3 composes
    #: one region per member of. It is kept beside :attr:`returned` rather than instead
    #: of it: that counter is what a *record* of the servicing reports (ADR-0226 §9) and
    #: this is what a *row* is composed from, and the two are the same length by
    #: construction because :meth:`admit` advances both on the same line.
    offered: list[MemoryRecord] = field(default_factory=list)
    returned: int = 0
    deduplicated: int = 0

    @property
    def remaining(self) -> int:
        """How many slots of the budget are still unspent."""
        return self.budget - len(self.admitted)

    def holds(self, record: MemoryRecord) -> bool:
        """Whether the supply holds this record, by §7's sameness (:func:`held_names`).

        The one reader of :attr:`held` outside :meth:`admit`, so that "the supply holds
        this record" is asked in exactly one way. A caller testing a bare id against the
        set would be asking the narrower question the names exist to widen.

        Args:
            record: The record to ask about. Read, never written.

        Returns:
            Whether the pre-servicing supply held it or an admission has added it.
        """
        return bool(self.held.intersection(held_names(record)))

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
            self.offered.append(record)
            self.returned += 1
            names = held_names(record)
            if self.held.intersection(names):
                self.deduplicated += 1
            elif self.remaining > 0:
                self.held.update(names)
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
    """ADR-0238 §11's counts as ADR-0247 §6 leaves them: three, written as stages complete.

    **``calls`` is gone** (ADR-0247 §6). The per-turn record's "this turn's ``calls``"
    went with the draw ADR-0247 §5 removed, which supersedes ADR-0238 §11's second
    clause **in that limb alone**: the count of records supplied to the composer,
    ADR-0246 §7's supplied-narrowed count and ADR-0245's withheld count at its zero all
    stay, as do §11's one-event rule, its one-key rule, its counts-only rule, its
    no-identifier rule and its refusal to write the destination's trust to the event.

    **Written rather than returned**, which is :class:`_Reads`'s own shape and is here
    for the same reason: a fault the searcher raised *after* the ruling unwinds past the
    call that would have returned them (ADR-0226 §5's degradation, issue #2112), and a
    record reporting that such a servicing composed over nothing would be false of one
    that did.

    Attributes:
        supplied: How many records were supplied to the composer.
        withheld: How many §3's filter kept out of that supply. **Zero on every path**
            since ADR-0246 §1 (§7): on a chosen destination the filter withholds
            nothing, and on an ``UNCHOSEN`` one the whole population is withheld by
            §2's trust clause and not by the filter. Kept as a field rather than
            deleted, because ADR-0238 §11's enumeration is four counts and removing one
            would be a change to it — and because a constant zero is itself the honest
            report of what the filter now does.
        supplied_narrowed: ADR-0245 §7's fourth count, widened by ADR-0246 §7 over
            **every** setter: how many of the records *supplied* carry a
            ``placement.reach`` that is not
            :attr:`~ai_assistant.core.types.PlacementReach.ANYONE`. It exists because
            ``withheld`` **falls** — to zero, and for the last time — so without it the
            only number that moved on a deployment's audit would show *less* withholding
            and nothing at all about the class that now flows. A per-population figure
            rather than a per-turn one (ADR-0226 §8), and a count like the other two.
    """

    supplied: int = 0
    withheld: int = 0
    supplied_narrowed: int = 0


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
        parked_read: The ``OPEN`` :class:`ParkedRead` **this servicing wrote**, or
            ``None`` where it wrote none (ADR-0244 §1, §2). Non-``None`` on exactly the
            branch that recorded a ``CONFIRM`` **and** whose ``ParkedReads.park``
            answered ``True``, which is the same boolean :attr:`not_serviced` was
            discriminated by.

            **It is carried and never re-read.** The engine assembles the turn's
            ``TurnOutcome.read_confirmation`` from it and from the recorded decision,
            so the question appears in the exchange that raised it; no render site
            reads ``ParkedReads``, and no component recomputes it downstream (ADR-0242
            §7, ADR-0244 §12).
        parked_decision: The trail's own copy of the ``CONFIRM`` that park holds the
            question of, carried beside it and for the same reason — **so that
            assembling the question costs no second store read** (ADR-0244 §1).

            "**The turn does not park, is not suspended and does not fail**": a read of
            the trail taken *after* the servicing has parked is a read that can raise
            an ``AuditError`` between the park and the reply, taking down a turn that
            had already composed its answer — which is the one thing §1 states in terms
            that parking must not do. This site holds the decision by construction, so
            the engine is handed it rather than sent back for it.

            The **enumeration** path reads the trail for a park it did not write, and
            that is a different seam: ``pending_confirmations`` is not inside a turn and
            already declares ``AuditError`` (ADR-0052 §1).
        contact: ADR-0264 §2's carrier for this servicing — what this site's
            ``WEB_SEARCH`` **call** established, computed **here at the performing
            site** by :func:`contact_of` from the outcome this site holds, and ``None``
            where no call was performed at all.

            **It is not derivable from** :attr:`disposition` (§2). An absent disposition
            is a call that completed and recorded none *and* a servicing that never
            reached its search, and this field is what tells those apart: the branch
            that answers an absent ask carries ``None`` here, and the branch whose
            provider answered ``NO_RESULT`` carries
            :attr:`~ai_assistant.core.types.OutboundReach.REACHED`.

            **A contact is established the moment a response arrived, and nothing that
            happens to the enclosing servicing afterwards unmakes it** (§2), which is
            why this rides out on the failing record's carriers exactly as
            :attr:`not_serviced` does.
        admitted: ADR-0264 §4's count for this servicing — how many records this
            call's contact put into the **turn's supply**, taken as the delta of
            ``_Union.admitted`` across the admission and so **after** ADR-0226 §7's
            deduplication and §6's budget.

            **Recorded by the site that performs the admission and never
            reconstructed** (§4), and in particular it is **not** ``len(minted)``:
            where one response carries two records under one id the supply takes one
            and this is ``1``, and where the budget cut the rest this counts what fit.
            It is also **not** :attr:`ServicedRead.supplied`, which counts what was sent
            *to* the query composer before anything left.

            Zero on every non-yield, which §4 rules never suppresses the statement.
    """

    records: tuple[MemoryRecord, ...]
    disposition: SearchDisposition | None
    not_serviced: SearchNotServiced | None = None
    parked_read: ParkedRead | None = None
    parked_decision: PermissionDecision | None = None
    contact: OutboundReach | None = None
    admitted: int = 0


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
        minted: ADR-0249 §7's carrier — the ids of the records this servicing's
            ``WEB_SEARCH`` ask **minted**, in the order §10 minted them. Empty on every
            servicing that carried no such ask and on every one whose search did not
            yield.

            **It exists because a minted id resolves in no store** (ADR-0231 §16), so a
            ``FROM_EVIDENCE`` interpretation element naming one is dropped exactly as an
            out-of-range label is: "a durable record grounded on an identifier nothing
            can retrieve states a warrant it cannot show". Nothing else can tell the
            population apart at the loop — a minted record sits in ``memories`` beside
            every other, which is the whole point of ADR-0226 §7's fourth group — so the
            fact is **supplied by the servicing that knows it** and never inferred at
            the resolution site, exactly as :attr:`hop_reached` is.

            It is **not** :attr:`SearchFooting.minted_user_chosen`, which is a different
            population for a different question: that set is ADR-0238 §2's third
            admissible **composer** population and is filled only where the destination
            is registered, while this one is every record the search minted into this
            turn's supply, whatever ADR-0238 §2 then admits to a composition.
        hop_reached: ADR-0227 §3's carrier — the **distinct** ids of the records this
            servicing's citation hop reached that the supply holds after it, in
            ADR-0229 §3's order.
        yields: ADR-0251 §3's carrier and ADR-0252 §14's production rule on one value —
            one :class:`AskYield` per ask **this servicing reached**, in the order
            ADR-0226 §6 services the kinds in, each carrying the planner's own ask byte
            for byte beside the member :func:`classify_read_outcome` reached for it and
            the records the ask returned. An ask the servicing did not reach earns no
            entry, and a servicing that failed or was partial carries **none at all** —
            ADR-0226 §5's all-or-nothing posture, which is §2's precedence case 1 for
            every ask the stage had already put, and which ADR-0252 §14 restates as "a
            servicing that did not complete produces none".
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
        parked_read: ADR-0244 §1's carrier: the ``OPEN`` park this servicing **wrote**,
            or ``None`` where it wrote none. It travels beside :attr:`not_serviced`
            because it is the same fact read the other way — the boolean that
            discriminated the member, carried as the record it was discriminated by —
            and the engine assembles the turn's ``TurnOutcome.read_confirmation`` from
            it so that the question appears in the exchange that raised it (ADR-0244
            §9).

            **Carried as data and never re-read.** No render site, adapter or composing
            stage reads ``ParkedReads``, and no component recomputes this downstream
            (ADR-0242 §7, ADR-0244 §12, §13).
        parked_decision: The trail's own copy of the ``CONFIRM`` that park holds the
            question of, carried beside it so that the engine assembles the question
            with **no store read of its own** — ADR-0244 §1's "the turn does not park,
            is not suspended and does not fail", which a trail read taken after the park
            was written could break between the park and the reply.
        contact: ADR-0264 §2's carrier: what this servicing's ``WEB_SEARCH`` **call**
            established, or ``None`` where the servicing performed no call at all — a
            request carrying no such ask, and one that raised before its search was
            serviced.

            **Computed at the performing site and never re-derived here** (§2). It
            travels beside :attr:`not_serviced` for that member's own reason and on the
            same terms — "computed at the servicing site, by the component that recorded
            the ``SearchDisposition``" — and **rides on the failing record's carriers
            too**: a servicing whose search was answered and whose later read then
            raised carries the contact its call established, because what ADR-0226 §5
            discards is the records and not the call.

            **It is not read off** :attr:`not_serviced` (§2). That vocabulary is
            non-injective and ``UNAVAILABLE`` covers both a response that arrived and
            was refused and a transport that failed, which §2's second and third groups
            separate.
        forecast_not_read: ADR-0260 §10's carrier: which **class of act** would have let
            this servicing's forecast read happen, or ``None`` where it yielded, where
            it reached the provider and found nothing, and where the request carried no
            ``FORECAST_READ`` ask. **Computed at the servicing site** by the component
            that recorded the disposition, and carried from there as data — the shape
            :attr:`not_serviced` already has one vocabulary over.

            **It rides on the failing record's carriers too**, exactly as
            :attr:`not_serviced` does: a servicing whose forecast declined before a
            later kind's read raised carries its member, and dropping it would report
            that turn as one whose planner never asked for a forecast.
        forecast_contact: ADR-0260 §10's carrier: what this servicing's forecast
            **call** established, or ``None`` where it performed none at all — a
            request carrying no such ask, and one that raised before the forecast was
            serviced.

            **Computed at the performing site and never re-derived here** (§10), and
            **never read off** :attr:`forecast_not_read`, which is non-injective: a
            ``UNAVAILABLE`` covers both a response that arrived and was refused and a
            transport that failed, which §10's first and second groups separate. It
            **rides on the failing record's carriers** for :attr:`contact`'s reason and
            in §10's own words — "nothing that happens to the enclosing servicing
            afterwards unmakes it", which is §13's arm (n).
        forecast_records: ADR-0264 §4's count for this servicing's forecast contact:
            how many records it put into the **turn's supply**, after ADR-0226 §7's
            deduplication and §6's budget.

            **Zero on a servicing that failed**, whatever its forecast admitted before
            the fault, because ADR-0226 §5 leaves the supply as planning saw it — §13's
            arm (n) asserts exactly that pairing, a contact standing beside a ``0``.
            It is a **second count and not a second population**: the turn sums it with
            :attr:`contact_records` into the one figure §4 states over the turn.
        contact_records: ADR-0264 §4's count: how many records this servicing's contact
            put into the **turn's supply**.

            **Zero on a servicing that failed**, whatever its search admitted before
            the fault, because ADR-0226 §5 leaves the supply as planning saw it — so
            nothing that servicing fetched is in the turn's supply, and §4 rules that a
            ``0`` never suppresses the statement. That is the one case in which this
            and :attr:`minted` disagree by design: `minted` is folded on every path out
            because ADR-0249 §7 asks it to be, and this is the count of what **entered**.
    """

    hop_reached: tuple[str, ...] = ()
    minted: tuple[str, ...] = ()
    forecast_not_read: ForecastNotRead | None = None
    forecast_contact: OutboundReach | None = None
    forecast_records: int = 0
    yields: tuple[AskYield, ...] = ()
    empty_read: ReadAsk | None = None
    structured_ran: bool = False
    label_filtered: bool = False
    window_filtered: bool = False
    not_serviced: SearchNotServiced | None = None
    parked_read: ParkedRead | None = None
    parked_decision: PermissionDecision | None = None
    contact: OutboundReach | None = None
    contact_records: int = 0


@dataclass(slots=True)
class SearchFooting:
    """What this turn's ``WEB_SEARCH`` servicings are decided from, for one conversation.

    **Two facts and two per-turn sets, and the budget is gone** (ADR-0247 §5, §6).
    ADR-0238 §8's per-conversation call allowance, its stored footing flag and the three
    ``ConversationStore`` members that maintained them are removed entire, so this
    object holds no store handle, takes no store call, spends nothing and folds nothing.
    What is left is the conversation the turn runs under, whether this deployment holds
    a search registration at all, and the two record-id sets ADR-0238 §2's populations
    are built from.

    **The destination's trust is not one of them either** (ADR-0247 §1). ADR-0238 §1's
    store answered the two questions ADR-0238 §2 and §5 asked here — what may be
    composed over, and whether the request closes the loop — and §1 replaces **both**
    reads with :attr:`registered`, a fact the composition root already holds: the
    configured search provider *is* the destination the owner chose, and the
    configuration is the choosing act. The store itself is untouched and answers exactly
    as it did for every other caller.

    **It is a value the loop threads, not a seam.** It names no capability, is
    registered nowhere, adds no route and now holds no store at all.

    Attributes:
        conversation_id: The conversation this turn runs under. Read by one site —
            :meth:`SearchServicer._park`, which writes a park against it and expires an
            open one — and by nothing else.
        registered: Whether this deployment holds a search registration at all — ``True``
            where the composition root was given both ``Settings.web_search_connection``
            and ``Settings.web_search_origin``, ``False`` where it was given neither
            (``Settings`` refuses one without the other). **A plain boolean and not a
            handle**: ADR-0247 §1 puts the pair in the composition root's hands, which
            already holds it, so no value reaches below ``orchestration`` and no read is
            awaited. It decides both questions ADR-0238 gave the trust store — what may
            be composed over (§2) and whether the request closes the loop (§5, as
            ADR-0247 §4 restates it) — because §1 makes them one fact.
    """

    conversation_id: str
    registered: bool
    #: The ids of records **this turn's** ``WEB_SEARCH`` servicings minted at the
    #: destination the owner chose — ADR-0238 §2's third admissible population, whose
    #: membership ADR-0247 §1 decides from :attr:`registered` rather than from a
    #: ``trust_of`` answer. It is a per-turn set because ADR-0231 §16 makes a minted id
    #: resolve in no store and no later turn reach it: "a second turn re-searches …
    #: because nothing was retained", so no id in here is ever seen again.
    #:
    #: **It feeds the supply and nothing else now** (ADR-0247 §4, §6). ADR-0238 §5's
    #: third condition, which this set also fed, is retired with the rest of the
    #: closed-loop lineage, so what it still does is widen the *supply* of a refining
    #: second servicing of the same turn.
    minted_user_chosen: set[str] = field(default_factory=set)
    #: The ids of the records ADR-0238 §2's **first two** populations contributed to this
    #: turn: "episodes of this conversation that ``orchestration`` selected into the
    #: turn's supply" and "the ``MemoryRecord`` values the turn's retrieval and episodic
    #: supplement selected". Written once, by the loop, from the supply it assembled
    #: before the first planner call — which is the one component that knows which stage
    #: a record came from, and the reason this is a recorded set rather than a predicate.
    #:
    #: **A stamped episode of an earlier turn is in here**, and §2 is explicit that it
    #: should be: "what a later turn has instead is the captured episode … **that** is
    #: what resolves *find more about that* across turns".
    #:
    #: **It is kept although ADR-0247 §11's lane-4 enumeration names it** (ADR-0247 §3,
    #: which rules that "``SearchSupply``, its populations and its construction site are
    #: untouched — ADR-0238 §2's three populations, its single construction site and its
    #: trust clause bind entire"). This set and :attr:`minted_user_chosen` **are** those
    #: populations at the one construction site, :func:`_search_supply`; deleting them
    #: would admit into the supply every record any other servicing of the turn
    #: contributed — a fetched file, a hop record — which §2 excludes by name. What the
    #: enumeration removes is the budget, and the budget's own set,
    #: ``conversation_episodes``, goes with :meth:`clean`, which was its only reader.
    selected: set[str] = field(default_factory=set)


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
        parked_reads: ParkedReads | None,
        parked_read_ttl: timedelta,
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
            parked_reads: Where a recorded ``CONFIRM`` on this kind parks its question
                (ADR-0244 §1, §3), or ``None`` where this deployment wires no such
                store. **Passed rather than defaulted**, for ``searcher``'s reason one
                contract over: a defaulted seam would let a later call site silently
                park nothing and read, in every record this servicing writes, exactly
                like a deployment that wired one.

                ``None`` is **not an error and not a second disposition**: ADR-0244
                §1's third clause already rules what a servicing that wrote no park
                is — "the decision stands unresolved on the trail, the establishing act
                may ride it where ADR-0235 §3's conditions hold, and §12's mapping gives
                the turn the member it gives today" — and a store that refused, one that
                raised, and one that is absent are the same state to this site.
            parked_read_ttl: ``Settings.parked_read_ttl`` — the lifetime a park and the
                ``CONFIRM`` it holds the question of **both** carry (ADR-0244 §3), read
                by the composition root and passed here rather than read below
                ``orchestration``, exactly as ``deadline`` is. One clock reading at the
                ruling stamps ``decided_at``, the decision's ``expires_at`` and the
                park's two instants, which is what makes ADR-0244 §5's and §10's
                shared-deadline reasoning hold rather than approximately hold.

        Raises:
            ValueError: If ``deadline`` or ``parked_read_ttl`` is not a strictly
                positive ``timedelta``. ``Settings`` already refuses either at load;
                this is the guard at the seam a test or a dynamically-wired caller can
                reach directly, and it fires here rather than at the first search
                (ADR-0241 §1, ADR-0244 §3).
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
        self._parked_reads = parked_reads
        if not isinstance(parked_read_ttl, timedelta) or parked_read_ttl <= timedelta(0):
            msg = (
                f"parked_read_ttl must be a strictly positive timedelta "
                f"(ADR-0244 §3); got {parked_read_ttl!r}"
            )
            raise ValueError(msg)
        self._parked_read_ttl = parked_read_ttl

    async def service(  # noqa: C901, PLR0911, PLR0913 — one exit per stage ADR-0231 §9 names as a decline (§13 requires the member to name the stage that produced it, so collapsing any pair would report one stage's outcome as another's), and one parameter per thing ADR-0238 §5's four conditions are decided from
        self,
        utterance: str,
        *,
        remaining: int,
        external: bool,
        footing: SearchFooting,
        in_view: Sequence[MemoryRecord],
        counts: _SearchCounts,
        goal: GoalBrief,
        plan: ActionPlan,
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
            footing: This conversation's footing. **No store call is made through it
                at all** (ADR-0247 §5, §6): the budget it used to spend is removed, and
                the destination is decided from the registration it carries (ADR-0247
                §1). What this method reads off it is that registration, the two
                population sets ADR-0238 §2's supply is built from, and — on the park
                branch alone — the conversation's id.
            in_view: The turn's pre-servicing supply and every record this servicing
                has already contributed — **the same data, the same site and the same
                instant** ``external`` above is computed over (ADR-0238 §5). It is
                what ADR-0238 §2's supply is drawn from. It decides no part of
                ``closed_loop`` any more (ADR-0247 §4 retires §5's current-turn half).
            counts: ADR-0238 §11's three counts, **written** as each stage completes
                rather than returned, so a fault the searcher raised after the ruling
                leaves behind what actually happened.
            goal: The brief of the goal **this turn** was planned against, persisted onto a
                park so that ADR-0244 §8's continuation composes over the parked turn's
                own objective rather than fabricating one. It reaches no composer, no
                model call and no rendering of the question (ADR-0244 §2, §4, §16).
            plan: The :class:`ActionPlan` the planner returned on the call this
                servicing answers, persisted for the same reason and subject to the
                same refusals. **Re-planning at resume would be the wrong kind of
                cheap** — a model call between the user's *yes* and the read, a planner
                free to ask for a different read, and a ``TurnResult`` whose plan is not
                the plan the parked turn ran (ADR-0244 §2).

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
            return self._not_serviced(SearchDisposition.NO_BUDGET)
        # **No admission step, and nothing is spent here** (ADR-0247 §5). ADR-0238 §8's
        # compare-increment-answer against a per-conversation allowance stood at exactly
        # this position, ahead of the supply, the query, the ruling, the credential and
        # the channel; the allowance is removed and nothing replaces it. What bounds a
        # conversation's searching is named rather than assumed: ADR-0228 §4's planning
        # budget per turn, ADR-0241 §1's deadline and ADR-0231 §5's three response
        # bounds per search, ADR-0194's ceiling per money — and **per conversation,
        # nothing**, because every turn is owner-initiated.
        # ADR-0238 §2: **which** supply this servicing builds is decided here, from
        # whether this deployment's destination is one the owner chose and from the
        # records this component holds. **The fact is the registration and no longer a
        # `trust_of` read** (ADR-0247 §1): the configured provider *is* the chosen
        # destination, the configuration is the choosing act, and the composition root
        # hands that one boolean down — so this site takes no store call here, none at
        # the build-time read below, and adds no await to either.
        # `counts.withheld` is left at its zero default and is not assigned here:
        # ADR-0246 §1 leaves no placement filter to withhold anything on a chosen
        # destination, and on an unregistered deployment §2's clause empties the
        # population rather than the filter. **The field is not deleted** (ADR-0246
        # §7) — ADR-0238 §11's enumeration keeps its four counts — and the number a
        # deployment watches instead is `supplied_narrowed`.
        supply, counts.supplied_narrowed = _search_supply(
            utterance,
            in_view,
            trusted=footing.registered,
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
            return self._not_serviced(QUERY_DISPOSITIONS[refusal])
        query = composed.query
        if query is None:  # pragma: no cover — `QueryOutcome` admits no such value
            # `QueryOutcome`'s own validator refuses an outcome carrying neither a
            # query nor a refusal, so this is unconstructable for a conforming
            # value and is written for the type checker rather than for a caller.
            return self._not_serviced(SearchDisposition.COMPOSER_MALFORMED)
        proposal = await self._searcher.request(query)
        if proposal is None:
            # §17: `request` "returns the `ActionRequest` for a composed query, or
            # `None` where the deployment has connected no search account". The
            # same provisioning fact a servicer holding no searcher at all reports,
            # under the same member — §13 admits one member for two outcomes of one
            # stage an operator would act on identically.
            return self._not_serviced(SearchDisposition.NOT_CONFIGURED)
        bound = await self._bound(
            proposal,
            external=external,
            coverage=SelectionOrigin.over(supply.records).coverage,
            # **ADR-0247 §4's two conditions, and they are the kind and the
            # configuration.** The kind is this branch: `service` is reached for a
            # `WEB_SEARCH` ask alone. The registration is `footing.registered`, and
            # ADR-0231 §17 has already answered it a second way — `request` returned a
            # proposal rather than `None`, which it does only where the deployment
            # connected a search account — so the conjunct is written from the value
            # the composition root handed down and checked against the seam's own
            # answer by standing past that `None`.
            #
            # **ADR-0238 §5's third and fourth conditions are retired** (§4): the
            # lineage of this conversation's recorded external spans no longer decides
            # this, and there is no per-conversation admission left to hold — ADR-0247
            # §5 removes the budget, the flag's folds and the three store members that
            # maintained them.
            #
            # **Written here, at the position §5 fixes, with nothing awaited between it
            # and the `EgressBinding`'s construction** (§4's writer clause, which binds
            # entire): the value is a boolean this frame already holds, so there is no
            # read left for anything to commit inside.
            closed_loop=footing.registered,
        )
        if bound is None:
            return self._not_serviced(SearchDisposition.BINDING_FAILED)
        # ADR-0152 §1: the request is built from what the seam returned and never
        # from objects held across the call, with no `await` between the two — the
        # runner's own rule at a second call site. `step_id` and `execution_id` are
        # `None` (§6): no plan step is synthesised, no `ExecutionState` and no
        # execution, and no clause written about steps is given a subject here.
        #
        # **`intended_action` is `None` here for exactly that reason**, and it is
        # `goal`'s own disposition one field over. ADR-0266 §11's L2 sets it *"from
        # the `intended_action` of the plan step the request serves"*; this request
        # serves no plan step, so there is no act to name and naming one would be
        # this stage's word rather than the plan's. A request carrying `None` is met
        # by ADR-0266 §7's evidence route in no case, so no `MONEY` member is met —
        # the fail-closed direction, and the same one this site already takes for
        # `goal`.
        request = ActionRequest(
            tool=bound.tool, parameters=bound.parameters, egress_binding=bound.binding
        )
        recorded = await self._ruled(request)
        if recorded is None:
            return self._not_serviced(SearchDisposition.RULING_UNAVAILABLE)
        outcome = recorded.ruling.outcome
        if outcome is not PermissionOutcome.ALLOW:
            # **A search at the configured provider does not reach here on a lineage
            # or a coverage ground any more** (ADR-0247 §2, §3). Route (c) rules it
            # `ALLOW` on the deployment's own configuration, before the grant seam is
            # consulted at all, and §3 retires both floors that used to fire: the
            # disclosure floor over `planned_with_external_content` and its coverage
            # exception. ADR-0193's standing grant stays the route for every other
            # destination and every other kind, and for a `WEB_SEARCH` whose binding
            # is not the configured one.
            #
            # **So what still reaches this branch is an independent ground** — the
            # per-call cost the deployment declared no figure for (#2111, ADR-0236),
            # which `ThresholdActionPolicy` treats as its own non-configurable
            # `CONFIRM` and which no route discharges — or a `DENY`, or a binding the
            # comparison finds is not the configured provider's.
            #
            # **ADR-0242 §7's carrier, computed here from the values this site already
            # holds and from no read of its own.** `trust` is not read: ADR-0247 §1
            # stops the servicing site asking the trust store, and this branch is past
            # `WebSearcher.request` answering a proposal, so the deployment holds a
            # registration and §1 makes its destination the one the owner chose. The
            # value passed below says exactly that, which is why `TRUST_MISSING` is
            # unreachable from here and `UNAVAILABLE` is what a follow-up refusal
            # carries (ADR-0242 §8: naming an act that cannot help is worse than
            # naming none). `planned_with_external_content` is read off the binding
            # this request carried, which is what tells a first refusal
            # (`AUTHORISATION_AWAITED`) from a follow-up's; the disposition alone
            # cannot, and an explanation derived from it would send half of milestone
            # 31's users to the wrong command (§8).
            if outcome is PermissionOutcome.DENY:
                return self._not_serviced(
                    SearchDisposition.RULING_DENY,
                    planned_with_external_content=bound.binding.planned_with_external_content,
                    trust=DestinationTrust.USER_CHOSEN,
                )
            # **ADR-0244 §1: where a `WEB_SEARCH` servicing records a `CONFIRM`, the
            # servicing site parks the read** — one `ParkedRead` naming the recorded
            # decision, and no records into the supply. The disposition is still
            # `RULING_CONFIRM`, because ADR-0231 §13 names **the stage that produced the
            # outcome** and the stage is unchanged; what the park discriminates is what
            # the *user* is told (§12).
            #
            # **The turn does not park, is not suspended and does not fail.** This
            # returns to `service_read_request`, the remaining kinds are serviced in
            # ADR-0231 §11's fixed order, and the turn composes and answers. ADR-0226
            # §5 binds entire: what parks is the **read**.
            #
            # **Nothing is sent, opened, claimed or spent here** (§1). No channel, no
            # credential, no `ToolCall`, no ledger claim, no minted record, and
            # ADR-0194's spend admission is not reached. There is no per-conversation
            # allowance left for a park to spend or a refund to restore either
            # (ADR-0247 §5).
            park = await self._park(
                request,
                recorded,
                footing=footing,
                # ADR-0248 §3: the park carries the turn's own request, for ADR-0244
                # §2's reason for retaining the other two — §8 composes over it and
                # would otherwise fabricate it. `utterance` is this method's own
                # parameter, the value the composer was handed, which `_turn` stripped
                # once (ADR-0248 §1); nothing here re-derives it.
                utterance=utterance,
                goal=goal,
                plan=plan,
            )
            return self._not_serviced(
                SearchDisposition.RULING_CONFIRM,
                planned_with_external_content=bound.binding.planned_with_external_content,
                trust=DestinationTrust.USER_CHOSEN,
                park=park,
                # The decision this site already holds, carried so the engine assembles
                # the question without a second trail read — a read that could raise
                # **after** the park was written and take down a turn §1 says must not
                # fail.
                decision=recorded,
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
            return self._not_serviced(SEARCH_DISPOSITIONS.get(search_refusal))
        # ADR-0238 §2's third admissible population, recorded for **this turn** alone:
        # a record minted at a destination the user chose is one a later servicing of
        # this same turn may compose over. **Which destination that is, is now the
        # registration** (ADR-0247 §1), the same fact the supply clause above reads —
        # and §5's third condition, which this set also fed, is retired by §4, so what
        # it still does is widen the *supply* of a refining second servicing.
        # ADR-0231 §16 makes the id resolve in no store and no later turn reach it, so
        # this set dies with the turn and a captured episode is never in it.
        if footing.registered:
            footing.minted_user_chosen.update(record.id for record in result.records)
        # ADR-0264 §2's first group, at the site that performed the call: the call
        # completed and recorded no disposition, which is a search that reached the
        # provider and was answered. `admitted` is filled by the admission site, which
        # is `_serviced_search` — this frame has not offered the records to the union.
        return _Searched(result.records, None, None, contact=OutboundReach.REACHED)

    # --- what ADR-0244 §6 and §7 reach this object for ----------------------
    #
    # **The answer path takes the same five contracts through the same holder**
    # (ADR-0231 §5, §6; ADR-0244 §7, §16). A parked read's answer rebinds, rules,
    # records and sends, and every one of those is a seam this object already holds
    # by composition-root obligation — so the answer reaches them here rather than
    # through a second holder of the binder, the policy, the trail or the searcher.
    # That is what keeps ADR-0244 §16's "no second route, no second servicing site,
    # no second asker" true of the implementation and not only of the prose, and it
    # is why `ParkedReadOperations` holds this object instead of five contracts of
    # its own.

    async def recorded(self, decision_id: str) -> PermissionDecision | None:
        """Read one recorded decision back, or answer that the trail holds none.

        ADR-0244 §6's clause 3 reads the trail through the **same** instance this
        servicing recorded into, which is the composition-root single-instance
        obligation ADR-0192 §1 already states for the ledger: a second trail would
        answer about rows this one never wrote.

        Args:
            decision_id: The recorded ``CONFIRM`` a park names.

        Returns:
            The trail's own copy, or ``None`` where it holds no such row.

        Raises:
            AssistantError: If the trail could not be read. **Not swallowed here**:
                ADR-0244 §9 makes a *refusal* a returned member, and a trail this
                process cannot read is not a refusal of the answer — it is a fault
                the caller classifies.
        """
        return await self._trail.get(decision_id)

    async def resolution_of(self, decision_id: str) -> PermissionDecision | None:
        """The decision resolving ``decision_id``, or ``None`` — conclusively.

        ADR-0244 §6's clause 3, third conjunct. **A whole read and never a bounded
        one**, which is
        :meth:`~ai_assistant.orchestration.recipient_grants.RecipientGrantOperations._resolution_of`'s
        own reasoning at a second caller: this is a question about **one named
        decision** and has no ``limit`` to widen, so the only conclusive answer
        available on the declared contract is the whole read. A bounded scan would
        report a confirmation resolved long enough ago that its answer has scrolled
        past the window as unresolved, and the answer would then spend the park and
        consult the policy before the trail refused the second resolution.

        **The cost is stated rather than hidden**: it is a read of the whole trail on
        the path a user's answer takes, and it is taken **before the gate** so that what
        it buys is a park not spent. ADR-0244 §20 declines a durable, filtered or
        indexed read of the trail for this decision's sake, and ADR-0235 §11 carries the
        condition that would fire one.

        Args:
            decision_id: The recorded ``CONFIRM`` under test.

        Returns:
            The decision resolving it, or ``None`` where none does.

        Raises:
            AssistantError: If the trail could not be read.
        """
        rows = await self._trail.export()
        return next((row for row in rows if row.resolves == decision_id), None)

    async def rebound(
        self, confirmed: PermissionDecision, parameters: FrozenJsonMapping
    ) -> BoundEgressCall | None:
        """Derive the answer's binding afresh and refuse what the approval did not cover.

        ADR-0152 §7's ``rebind``, reached at ADR-0244 §6's clause 4: it takes from the
        approved binding nothing but each span's provenance and its
        ``planned_with_external_content``, and **refuses unless the binding it derived
        is equal to the recorded one**. **What the user was shown is what may be
        sent**: a destination, an account identity or a payload description that moved
        between the question and the answer is a refusal, not a send.

        **Order 4 before 6 is ADR-0152 §7's, not a preference** (ADR-0244 §6): the
        binding must be whole before the ruling that authorises the resumed call
        (ADR-0148 §1), so this happens *before* ``ActionPolicy.resolve`` is reached.

        Args:
            confirmed: The recorded ``CONFIRM``, whose ``egress_binding`` is what the
                derived one is checked against.
            parameters: The park's own arguments, byte for byte as the ruling was taken
                over them.

        Returns:
            The bound call, or ``None`` where the seam refused it or raised — the two
            states ADR-0244 §9 reports under one member, because a binding that cannot
            be derived and one that derives unequal are the same fact to the user:
            **the operation is not the one they were asked about**.
        """
        approved = confirmed.egress_binding
        if not isinstance(approved, EgressBinding):
            # An **unrecorded-epoch** binding, refused here rather than inherited, on
            # `RecipientGrantOperations._offerable`'s reasoning: `ActionPolicy.resolve`
            # returns no `ALLOW` over either epoch, so the answer could not complete in
            # any case, and refusing before the ruling keeps the park from being spent
            # on a question no dispatch could follow. It is unreachable on this kind —
            # ADR-0231 §5 registers the search at the egress seam and §9 declines the
            # servicing where the binder returned nothing, so a `WEB_SEARCH` `CONFIRM`
            # always carries a real binding (ADR-0244 §4) — and stated anyway, because
            # the type admits it.
            return None
        try:
            return await self._binder.rebind(
                confirmed.tool, parameters=parameters, approved=approved
            )
        except AssistantError:
            # ADR-0152 §6, §7's refusals arrive as `EgressBindingError`; the net is
            # `_bound`'s one method up, for its reason.
            return None

    async def ruled_on_answer(
        self, confirmed: PermissionDecision, *, approved: bool, at: datetime
    ) -> PermissionDecision | None:
        """Ask the policy the user's answer and record whatever it says (ADR-0244 §6).

        **Its answer is recorded whatever it is** — the second obligation ADR-0235 §3
        already relies on, and ADR-0004 §7's reason: a ruling the trail never sees is a
        decision nobody can audit. On ``approved`` ``False`` the recorded answer is the
        ``DENY`` the user asked for.

        **A refused append is never raised out of the answer** (ADR-0244 §6). Clause 5
        makes the already-resolved ground of ``InvalidResolutionError`` unreachable
        through this path — the park's one answer was taken before the append was
        attempted — so a refusal here is one of that class's other grounds, or a fault.
        The answer is **not** recorded, the park stays spent, nothing is dispatched, and
        the caller reports ``OPERATION_CHANGED``: a refusal on ``resume`` is a result.

        **The instant is the caller's and is not read again here** (ADR-0235 §1). The
        answer's ``decided_at`` is the reading ADR-0244 §6's clause 1 took, which is
        what lets an establishing act's expiry be compared against *the instant the
        answer will carry* rather than against a second reading that has since moved —
        the failure §1 exists to remove rather than to narrow.

        Args:
            confirmed: The recorded ``CONFIRM`` being answered.
            approved: The user's own answer, relayed unchanged.
            at: The instant this answer carries, taken by the caller.

        Returns:
            The resolving decision as it was recorded, or ``None`` where the trail
            refused the append or could not be read back.
        """
        ruling = await self._policy.resolve(confirmed.model_copy(deep=True), approved=approved)
        answer = PermissionDecision.from_confirmation(
            confirmed, ruling, id=self._id_factory(), decided_at=at
        )
        try:
            await self._trail.record(answer)
        except AssistantError:
            return None
        return answer

    async def dispatch(self, call: ToolCall) -> SearchOutcome:
        """Run the approved read, by ADR-0231 §6's route unchanged (ADR-0244 §7).

        **This object stays the one caller of** ``WebSearcher.search`` (ADR-0231 §11,
        §17), which is what ADR-0244 §16's "no second route, no second servicing site,
        no second asker" means for the implementation. The searcher performs ADR-0029
        §2's three pre-execution checks in order, ADR-0194's spend admission, ADR-0192's
        claim, the send and the completion — **each evaluated at the instant of the
        dispatch and not at the instant of the park**, which is the whole of what
        "re-checked" means (ADR-0244 §6).

        **``QueryComposer`` is not called and no model call precedes the send**
        (ADR-0244 §7, §16). The value the searcher is passed is the park's own
        ``parameters`` — the ones the ruling was taken over and the ones the user read
        — and ADR-0231 §11's "the only value ``WebSearcher.request`` is ever passed"
        clause is satisfied by identity: what was composed in the parked turn is what is
        sent, with no repair, extension, truncation or re-casing between them.

        **The deadline is ``Settings.search_call_deadline``, passed on every call**
        (ADR-0241 §3), exactly as :meth:`service` passes it: there is no spelling for
        "unbounded" at this seam and none is reached for here.

        Args:
            call: The :class:`ToolCall` built over the **resolving** ``ALLOW``, whose
                own validator has already run ADR-0021 §1's ``authorises`` — so an
                unauthorised search is unconstructable at the type level.

        Returns:
            What the searcher answered: the minted records, or a refusal.
        """
        return await self._searcher.search(call, timeout=self._deadline)

    @staticmethod
    def _not_serviced(
        disposition: SearchDisposition | None,
        *,
        planned_with_external_content: bool = False,
        trust: DestinationTrust = DestinationTrust.UNCHOSEN,
        park: ParkedRead | None = None,
        decision: PermissionDecision | None = None,
    ) -> _Searched:
        """One non-yield, carrying ADR-0231 §13's disposition and ADR-0242 §7's member.

        **The two are computed together, at this site, and never apart** (ADR-0242 §7).
        A branch that returned one without the other would either put a disposition in
        the audit with nothing for the user or a member in the reply with nothing in the
        audit, and the second vocabulary exists precisely because neither is derivable
        from the other downstream.

        Args:
            disposition: What this branch resolved to.
            planned_with_external_content: The binding's own fact, where this branch
                built a request.
            trust: Where this deployment's search destination stands, which every
                branch that built a request states as ``USER_CHOSEN`` (ADR-0247 §1) and
                no branch reads from a store.
            park: The park this branch wrote, or ``None`` where it wrote none. **The
                discriminator is this branch's own boolean and not a store read**
                (ADR-0242 §7, ADR-0244 §12): the site wrote the park or its ``park``
                answered ``False``, and that is the whole of the further input.

            decision: The recorded ``CONFIRM`` the park holds the question of, where
                this branch wrote one. Carried rather than re-read, so that assembling
                the question cannot raise inside a turn ADR-0244 §1 says must not fail.

        Returns:
            The empty records, the disposition, the member, the park, its decision and
            what the call established.
        """
        return _Searched(
            (),
            disposition,
            not_serviced(
                disposition,
                planned_with_external_content=planned_with_external_content,
                trust=trust,
                parked=park is not None,
            ),
            park,
            decision if park is not None else None,
            # ADR-0264 §2's third carrier, computed here with the other two and never
            # apart from them. **An absent disposition on this method is
            # ``SearchRefusal.NO_RESULT`` and nothing else** — the one branch that
            # passes `SEARCH_DISPOSITIONS.get(...)` a refusal the mapping does not
            # carry — so it is a call that completed and recorded none, which is §2's
            # eighteenth case and a contact. Every other branch reaching here named a
            # member, and :func:`contact_of` places it.
            contact=contact_of(disposition),
        )

    async def _park(  # noqa: PLR0913 — the ruled request, the recorded decision, the footing, and the three members ADR-0244 §2 and ADR-0248 §3 persist because the continuation composes over them; each is a distinct fact and none is derivable from another
        self,
        request: ActionRequest,
        recorded: PermissionDecision,
        *,
        footing: SearchFooting,
        utterance: str,
        goal: GoalBrief,
        plan: ActionPlan,
    ) -> ParkedRead | None:
        """Write the question this ``CONFIRM`` leaves standing, or answer that none was.

        **A park is written only where the store accepted it** (ADR-0244 §1). Where
        ``ParkedReads`` refused — this conversation already holds an ``OPEN`` park — or
        raised, or where this deployment wired no store at all, **no park exists**,
        nothing is outstanding, and the servicing is exactly what it is today: the
        decision stands unresolved on the trail, the establishing act may ride it where
        ADR-0235 §3's conditions hold, and ADR-0242 §8's mapping gives the turn the
        member it gave before this decision. **A lane that reported a park it did not
        write would tell the user to answer a question nothing holds**, which is the one
        failure that clause is stated to prevent — so this returns the park it wrote and
        never the park it built.

        **The record carries the four content fields and nothing else of the call**
        (ADR-0244 §2, the count widened by ADR-0248 §3): no minted record, no result, no
        snippet, no title, no address, no
        origin beyond the one ``parameters`` already states, no credential, no
        ``SecretName``, no connection reference, no ``BoundAccount`` and no binding. The
        binding, the account identity and the canonical destination set are the
        **recorded decision's**, read through ``decision_id`` at the moment a
        ``Confirmation`` is assembled (ADR-0178 §5).

        **``parameters`` are the ruling's own, byte for byte**: they are the very
        mapping of the :class:`ActionRequest` the ruling was taken over — this site's
        own value, not a rebuild and not a copy from the trail, which holds only a
        digest (ADR-0148 §6, ADR-0231 §13). So what is persisted is what the ruling was
        taken over and what the user will be shown, and ADR-0244 §6's clause 4 can
        check it back against ``parameters_digest`` at the answer.

        **The deadline is the decision's own**, which is what ADR-0244 §5's and §10's
        reasoning rests on: a park past its deadline names a decision past the same one,
        so an ``EXPIRED`` park's decision is refused by ADR-0235 §3's **fifth**
        condition rather than by §5's eighth.

        Args:
            request: The request the ruling was taken over, whose ``parameters`` are the
                origin and the composed query byte for byte.
            recorded: The trail's own copy of the ``CONFIRM`` just recorded. Its
                ``expires_at`` is this park's, and its id is what the park names.
            footing: This conversation's footing, for ``conversation_id`` alone — **no
                store call is made through it here**, and after ADR-0247 §5 it holds no
                store to make one with.
            utterance: The parked turn's own request, as the pass received it
                (ADR-0248 §1). Persisted for ADR-0244 §2's reason for persisting the
                two below — the continuation composes over it and would otherwise
                fabricate it — and read back at the resume rather than re-derived from
                the goal there.
            goal: The brief of the parked turn's goal (ADR-0249 §11).
            plan: The parked turn's plan.

        Returns:
            The park this call wrote, or ``None`` where none was written.
        """
        store = self._parked_reads
        expires_at = recorded.expires_at
        if store is None or expires_at is None:
            # No store wired, so nothing holds a question and §1's third clause is the
            # whole of what this servicing then is. `expires_at` is `None` on exactly
            # the same condition — `_ruled` stamps it only where a store is wired — so
            # the second limb is the first read from the decision rather than a second
            # state.
            return None
        # **ADR-0244 §10's third reader.** "A park whose `expires_at` is at or before
        # the clock's reading is settled `EXPIRED` at the first operation that reads it
        # — an answer, an enumeration, **or the conversation's own next servicing**."
        # This is that servicing, and without it a park nobody enumerated and nobody
        # answered would hold the conversation's one open slot past its own deadline,
        # refusing every later question for it and offering no answer to any.
        #
        # **It settles nothing else** (§6's one-gate clause): an open park that has not
        # expired is left exactly where it is, and the servicing's own `park` below is
        # then refused by §3's one-open-park rule, which is §1's third clause and not a
        # second expiry.
        await self._expire_open_park(store, footing.conversation_id, now=recorded.decided_at)
        record = ParkedRead(
            id=self._id_factory(),
            conversation_id=footing.conversation_id,
            decision_id=recorded.id,
            parameters=request.parameters,
            utterance=utterance,
            goal=goal,
            # ADR-0249 §11: an identifier that **settlement does not clear**, taken
            # off the brief this servicing was handed rather than from a second
            # source that could disagree with it. It is not a resolution guarantee —
            # a turn that parked and then ended before its persistence site leaves a
            # park whose goal the store does not hold, which is answerable exactly as
            # ADR-0248 §3's `utterance`-less park is.
            goal_id=goal.goal_id,
            plan=plan,
            parked_at=recorded.decided_at,
            expires_at=expires_at,
            disposition=ParkedReadDisposition.OPEN,
        )
        try:
            written = await store.park(record)
        except AssistantError:
            # §1: "Where `ParkedReads` refused **or raised**, no park exists". The net
            # is `_bound`'s and `_ruled`'s, for their reason: a store fault at this
            # stage is an operator's fact, the servicing declines rather than failing,
            # and ADR-0244 mints no error class for a caller to handle differently.
            _degraded(type(store).__name__)
            return None
        return record if written else None

    @staticmethod
    async def _expire_open_park(store: ParkedReads, conversation_id: str, *, now: datetime) -> None:
        """Settle this conversation's open park where its deadline has passed (§10).

        **Safe precisely because §6's clause 1 refuses to answer such a park at all**
        (ADR-0244 §6): "expiry is the one settlement no party takes for itself, and it
        can take nothing from anyone" — there is no live answerer for this settlement to
        race, which is why the servicing may take it while a `resume` may not take any
        other.

        **The clock reading is the ruling's own**, threaded from `_ruled` rather than
        read again: one reading stamps the decision, its deadline, this comparison and
        the park below, which is what ADR-0244 §3's "computed from it, once, at the
        instant the park is written" asks for.

        Args:
            store: This deployment's parked-read store.
            conversation_id: The conversation whose open park to test.
            now: The instant to compare against, ADR-0059 §1's comparison.
        """
        try:
            standing = await store.open_park(conversation_id)
            if standing is not None and standing.expires_at <= now:
                await store.settle(standing.id, disposition=ParkedReadDisposition.EXPIRED, at=now)
        except AssistantError:
            # A store fault here is §1's third clause reached one step early: no park is
            # settled, the write below is refused by the standing row, and the servicing
            # is what it is today. Reported as this stage's own Tier 2 degradation, as
            # every other store fault at this site is.
            _degraded(type(store).__name__)

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
        recomputes it. **What it now asserts is "this is the deployment's own search"**
        (ADR-0247 §4): the request's kind is ``WEB_SEARCH`` and this deployment holds a
        search registration, and no third or fourth condition survives. **It is not the
        authority by itself** — §1's comparison of the binding's account and canonical
        destination set against the configured pair is taken at the *ruling*, where the
        binding exists, and this site is offered no part of that job.

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
            closed_loop: ADR-0247 §4's fact for this request — the kind and the
                registration, both held by the caller before this call and neither
                read from a store.

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
        # One clock reading, stamping the record — and, on a `CONFIRM` this deployment
        # can park, the deadline the park and the decision **both** carry (ADR-0244 §3).
        # "`expires_at` on the `ParkedRead` and on the recorded `CONFIRM` are both
        # computed from it, once, at the instant the park is written", which is what
        # makes §5's and §10's shared-deadline reasoning hold: a park past its deadline
        # names a decision past the same one, so an `EXPIRED` park's decision is refused
        # by ADR-0235 §3's **fifth** condition rather than by §5's eighth, and does not
        # return to `grantable_decisions`.
        #
        # **`None` on every other outcome, and on every outcome of a deployment that
        # wired no `ParkedReads`** — ADR-0231 §9's own reasoning, unrepealed for the
        # case it was written about: a deadline is a property of a question somebody
        # will answer, and where nothing can hold the question there is nobody to
        # answer it. So a tree with no store behaves exactly as it does today, which is
        # what ADR-0244 §18's lane order asks of this one.
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
        decided_at = self._now()
        decision = PermissionDecision.from_request(
            request,
            ruling,
            id=self._id_factory(),
            decided_at=decided_at,
            expires_at=(
                decided_at + self._parked_read_ttl
                if self._parked_reads is not None and ruling.outcome is PermissionOutcome.CONFIRM
                else None
            ),
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


@dataclass(frozen=True, slots=True)
class _Forecast:
    """What one ``FORECAST_READ`` ask produced, in the shapes the servicing needs.

    Attributes:
        records: The records ADR-0260 §5 minted, in the order it minted them, offered
            to :class:`_Union` exactly as every other kind's candidates are. Empty on
            every non-yield.
        disposition: §8's field for this servicing, or ``None`` in the two cases §8
            leaves it empty: where the read yielded records, and where it reached the
            provider and returned none —
            :attr:`~ai_assistant.core.types.ForecastRefusal.NO_RESULT` mapping to no
            disposition at all.
        not_read: §10's carrier for this servicing — which **class of act** would have
            let the read happen, computed **here at the servicing site** from
            :attr:`disposition` alone and ``None`` exactly where that is. It is never
            recomputed downstream and never inferred at a render site.

            **Two vocabularies over one event** (§8, ADR-0242 §8): the disposition
            names the stage for an operator reading the audit, and this names the class
            for the user reading a reply. §7 keeps this one **out** of the audit — a
            member computed for a user is not a second spelling of a fact the audit
            already records, and writing both would make the two drift.
        contact: §10's carrier — what this site's forecast **call** established,
            computed here by :func:`forecast_contact_of` from the outcome this site
            holds, and ``None`` where **no call was performed at all**.

            **It is not derivable from** :attr:`disposition` (§10). An absent
            disposition is a call that completed and recorded none *and* a servicing
            that never reached its forecast, and this field is what tells those apart:
            the branch that answers an absent ask carries ``None`` here, and the branch
            whose provider answered ``NO_RESULT`` carries
            :attr:`~ai_assistant.core.types.OutboundReach.REACHED`.

            **A contact is established the moment a response arrived, and nothing that
            happens to the enclosing servicing afterwards unmakes it** (§10, quoting
            ADR-0264 §2), which is why it rides out on the failing record's carriers
            exactly as :attr:`not_read` does — §13's arm (n).
        admitted: ADR-0264 §4's count for this servicing: how many records this call's
            contact put into the **turn's supply**, taken as the delta of
            ``_Union.admitted`` across the admission and so **after** ADR-0226 §7's
            deduplication and §6's budget. **Recorded by the site that performs the
            admission and never reconstructed**, and in particular it is not
            ``len(records)``: where the budget cut the rest this counts what fit, which
            is §13's arm (f). Zero on every non-yield, which §4 rules never suppresses
            the statement.
        serviced: ADR-0260 §7's first audit field: whether this servicing **put a
            ``FORECAST_READ`` ask to the forecast stage at all**. ``True`` on every
            branch below, ``NO_BUDGET`` and ``NOT_CONFIGURED`` included, because each
            is an account of an ask this servicing reached; ``False`` where the
            request carried no such ask, and where the servicing raised before the
            forecast's position in §7's order.

            **It is not derivable from** :attr:`disposition` **and that is why §7 asks
            for two fields.** An absent disposition covers both a read the provider
            answered and an ask this servicing never reached, and an audit holding only
            the disposition cannot tell a deployment reading a 0% yield for this kind
            which of the two it is looking at — the collapse ADR-0226 §9 refuses one
            field over for the unresolved-label count.
    """

    records: tuple[MemoryRecord, ...] = ()
    disposition: ForecastDisposition | None = None
    not_read: ForecastNotRead | None = None
    contact: OutboundReach | None = None
    admitted: int = 0
    serviced: bool = False


class ForecastServicer:
    """The four contracts one ``FORECAST_READ`` servicing is answered against (ADR-0260 §6).

    **A wiring value and not a seam.** It names no capability of its own, is registered
    nowhere, and adds no route: it is the composition root's statement that this
    deployment configured a forecast provider, holding the objects §6 and §7 name in the
    order those sections perform them. A deployment that configured none holds no
    instance at all, and :func:`service_read_request` is handed ``None`` — which is §8's
    :attr:`ForecastDisposition.NOT_CONFIGURED`, stated by a caller rather than
    defaulted, exactly as the ``fetcher`` and ``search`` parameters are.

    **The one caller of** :meth:`~ai_assistant.core.protocols.Forecaster.request` **and
    of** :meth:`~ai_assistant.core.protocols.Forecaster.read` (§7). ``app/composition.py``
    wires the forecaster into this object and into nothing else, no other subsystem
    holds the reference, and §7's "no lane adds a second caller" is what keeps that
    true.

    **One stage fewer than a search, and that is the whole of the difference** (§7).
    The order is **bind, then rule, then record, then send**, with no compose step,
    because §3 gives the ask no argument to compose: no ``QueryComposer`` is held, no
    model call precedes the send, and no value of this turn's own reaches the request.

    **Nothing is parked here** (§11). ADR-0244's park is a ``CONFIRM`` on a **search**,
    this decision mints no park for a forecast read, and a ``CONFIRM`` recorded here is
    recorded, not made, not parked, and reported under §10's ``AUTHORISATION_AWAITED``.
    So this object holds no ``ParkedReads`` and takes no park lifetime.

    **The id and the clock are the recorder's** (ADR-0021 §3, ADR-0059 §1), passed
    rather than defaulted for :class:`SearchServicer`'s reason: a deployment states the
    clock its audit rows are stamped from instead of inheriting one.
    """

    def __init__(  # noqa: PLR0913 — one parameter per contract ADR-0260 §6 names, plus the recorder's id and clock and ADR-0241 §1's deadline; the two sections fix the list
        self,
        *,
        forecaster: Forecaster,
        binder: EgressBinder,
        policy: ActionPolicy,
        trail: AuditTrail,
        now: Clock,
        id_factory: Callable[[], str],
        deadline: timedelta,
    ) -> None:
        """Wire one forecast servicing from the contracts ADR-0260 §6 names.

        Args:
            forecaster: Proposes the act and, once it is authorised, performs it (§4).
                This object is its only caller.
            binder: Derives the ``EgressBinding`` whole, before the ruling (ADR-0148
                §1, ADR-0152 §1). It accepts no part of the binding.
            policy: Rules on the request (§6). The **same object** the step runner and
                the search servicing rule with, so one deployment has one set of
                thresholds and one configured-provider comparison rather than several
                that could disagree.
            trail: Records the ``PermissionDecision`` before any channel opens (§7's
                "bind, then rule, then record, then send"). The same object the runner
                and the ledger hold.
            now: The clock the recorded decision is stamped from, guarded once here
                (ADR-0026 §4).
            id_factory: Mints the decision's id (ADR-0021 §3).
            deadline: The bound this site passes as ``timeout`` on **every**
                :meth:`Forecaster.read` (ADR-0241 §1).

                **It is the one call deadline this deployment configures, and ADR-0260
                §11 forbids a second.** That section rules that "the forecast read runs
                under the deadline ADR-0241 §1 already hands the servicing" and that "a
                ``Settings`` figure of its own would be a second bound on one turn", so
                the composition root hands this seam the same figure ADR-0241 §3 hands
                the search servicing and no field is added. The corpus holds no
                servicing-wide clock to subtract a remainder from, and opening one here
                would be the second bound §11 refuses rather than the one it names.

                **Read by the composition root and passed here** rather than read below
                ``orchestration`` (ADR-0241 §3), so nothing a model produced, a request
                carried or a result contained can reach the comparison.

        Raises:
            ValueError: If ``deadline`` is not a strictly positive ``timedelta``.
                ``Settings`` already refuses it at load; this is the guard at the seam a
                test or a dynamically-wired caller can reach directly, and it fires here
                rather than at the first read (ADR-0241 §1).
        """
        self._forecaster = forecaster
        self._binder = binder
        self._policy = policy
        self._trail = trail
        self._now = checked_clock(now, owner="ForecastServicer")
        self._id_factory = id_factory
        if not isinstance(deadline, timedelta) or deadline <= timedelta(0):
            msg = (
                f"deadline must be a strictly positive timedelta "
                f"(ADR-0241 §1, ADR-0260 §11); got {deadline!r}"
            )
            raise ValueError(msg)
        self._deadline = deadline

    @property
    def name(self) -> str:
        """The configured source's own identity (ADR-0260 §4, §9).

        Read by the servicing so that a ``READ_OUTCOME`` row written for this kind
        carries §9's ``source`` — "the forecaster's ``name``, which is what makes
        ADR-0252 §8's limb 3 finer than the kind". It names the **source instance** and
        never a vendor, an origin, a URL, a credential or a place, which is what admits
        it into a durable row at all (ADR-0252 §1).

        Returns:
            What this deployment's forecaster answers to.
        """
        return self._forecaster.name

    async def service(  # noqa: PLR0911 — one exit per stage ADR-0260 §8 names as a decline; §8 requires the member to name the stage that produced it, so collapsing any pair would report one stage's outcome as another's
        self, *, remaining: int, external: bool
    ) -> _Forecast:
        """Bind, rule, record and send — in that order and no other (ADR-0260 §7).

        **No channel is opened before a recorded ``ALLOW`` exists**, and there is **no
        compose step**: §3 gives the ask no argument, so the request this method rules
        on is built from the forecaster's own proposal and from nothing this turn
        produced. That is one stage fewer than a search and is the whole of the
        difference between the two servicings.

        **Every non-``ALLOW`` declines, and declining is not failing** (§7, ADR-0226
        §5). On a ``CONFIRM``, a ``DENY``, a binder that refused or raised, a policy
        that raised or a trail that could not record the decision: no channel is opened,
        no credential is read, no record is minted, the read budget is untouched, and
        this kind yields nothing. **Nothing is parked and nobody is asked** (§11) — the
        decision carries no ``execution_id`` and no ``step_id``, so no recovery query
        and no park can reach it.

        **The send is not made through ``ToolInvoker.invoke``** (§6, §1). Taking the
        invoker's route would require a ``ToolRegistry`` entry, and a registry entry
        would put a forecast in front of the planner — the outcome the whole design
        exists to prevent. So the ``ToolCall`` this method constructs is handed to the
        forecaster, which owns everything after it: ADR-0029 §2's three pre-execution
        checks, the credential read and ADR-0148 §6's four pre-transmit conditions.
        **This package claims nothing and spends nothing**: §6 names neither ADR-0194's
        admission nor ADR-0192's claim at this seam.

        **A ``ToolBindingError`` is §8's ``BINDING_FAILED`` and not a degradation**
        (§6). That section states it in terms — a failure at any of the three checks
        "raises ``ToolBindingError`` … and **is recorded by the servicing as**
        ``BINDING_FAILED``" — and §13's arm (h) asserts the member through to the turn
        beside an ``UNAVAILABLE`` and **no** contact, "because a path recording nothing
        would leave §10's ``None`` saying the provider answered". **Every other fault
        the seam raises degrades the turn** and is carried to ADR-0226 §5's one
        degradation site by :func:`_serviced_forecast`, because §8 closes this
        vocabulary at twelve with no member for a fault at the send and §12 forbids a
        lane adding one.

        Args:
            remaining: How many slots of ADR-0226 §6's budget are unspent when the
                forecast is reached. Fewer than one composes no request, seeks no
                ruling and opens no channel (§7).
            external: ADR-0181 §4's fact for **this** request, computed by the caller
                over the turn's pre-servicing supply and every record this servicing has
                already contributed (§7). It is written onto the carrier before ``bind``
                and is discarded, never merged, if any producer emitted one.

        Returns:
            The minted records, §8's disposition, §10's folded member and §10's contact.
            The records are empty on every non-yield, and the disposition is ``None``
            exactly where the read yielded or reached the provider and returned nothing.

        Raises:
            ToolError: A fault the forecaster raised that is not one of §6's three
                pre-execution checks — caught by :func:`_serviced_forecast` and carried
                to ADR-0226 §5's degradation, never reported as a disposition.
        """
        if remaining < 1:
            # §7: "Where fewer than one slot remains when the forecast is reached, no
            # request is composed, no ruling is sought and no channel is opened".
            # Checked before the forecaster is consulted, so this branch genuinely makes
            # no call. **Reachable on the order §7 fixes**, unlike the search's branch
            # of the same name: the forecast is serviced third, behind a file capped at
            # one and a search capped at three, so a servicing that admitted ten before
            # it arrives here with nothing left.
            return self._not_serviced(ForecastDisposition.NO_BUDGET)
        proposal = await self._forecaster.request()
        if proposal is None:
            # §4: `request` "returns ``None`` where the deployment has configured no
            # forecast provider, **which is a configuration fact and never a failure**".
            # The same provisioning fact a servicer holding no forecaster at all reports,
            # under the same member — §8 admits one member for two outcomes of one stage
            # an operator would act on identically.
            return self._not_serviced(ForecastDisposition.NOT_CONFIGURED)
        bound = await self._bound(proposal, external=external)
        if bound is None:
            return self._not_serviced(ForecastDisposition.BINDING_FAILED)
        # ADR-0152 §1: the request is built from what the seam returned and never from
        # objects held across the call, with no `await` between the two. `step_id` and
        # `execution_id` are `None` (§6): no plan step is synthesised, no
        # `ExecutionState` and no execution, and no clause written about steps is given
        # a subject here.
        #
        # **`intended_action` is `None` for exactly that reason**, as it is at the
        # search's own site: this request serves no plan step, so there is no act to
        # name and naming one would be this stage's word rather than the plan's.
        request = ActionRequest(
            tool=bound.tool, parameters=bound.parameters, egress_binding=bound.binding
        )
        recorded = await self._ruled(request)
        if recorded is None:
            return self._not_serviced(ForecastDisposition.RULING_UNAVAILABLE)
        outcome = recorded.ruling.outcome
        if outcome is not PermissionOutcome.ALLOW:
            # **A forecast read at the configured forecast provider does not reach here
            # on a lineage or a coverage ground** (§6). Route (c) rules it `ALLOW` on
            # the deployment's own configuration, before the grant seam is consulted at
            # all, and §6 restates both `_only_the_disclosure_floor` limbs over the
            # generalised derived fact. **So what still reaches this branch is an
            # independent ground** — the per-call cost the deployment declared no figure
            # for (ADR-0236 §4, which §11 leaves untouched), a `DENY`, or a binding the
            # comparison finds is not the configured forecast provider's.
            #
            # **Nothing is parked either way** (§11): "a forecast read ruled `CONFIRM`
            # is recorded, is not made, is not parked, and is reported under §10's
            # `AUTHORISATION_AWAITED`". There is no `ParkedReads` on this object to
            # write one with, which is that clause held structurally.
            return self._not_serviced(
                ForecastDisposition.RULING_DENY
                if outcome is PermissionOutcome.DENY
                else ForecastDisposition.RULING_CONFIRM
            )
        # ADR-0021 §1's `authorises` runs inside `ToolCall`'s own validator, so an
        # unauthorised forecast read is unconstructable at the type level — which is
        # `ToolInvoker.invoke`'s guarantee obtained without `ToolInvoker` (§1, §6). It
        # cannot refuse here: `recorded` equals the decision `from_request` transcribed
        # from this very request, and the outcome above is `ALLOW`.
        call = ToolCall(request=request, decision=recorded)
        try:
            read = await self._forecaster.read(call, timeout=self._deadline)
        except ToolBindingError:
            # §6's three pre-execution checks, each refusing "before any credential is
            # read and any channel is opened". **The exception is not held and its
            # message is not copied** (ADR-0004 §5): what the audit gets is the class
            # §8 names, and §13's arm (h) is what pins the member, the fold and the
            # absent contact together.
            return self._not_serviced(ForecastDisposition.BINDING_FAILED)
        refusal = read.refusal
        if refusal is not None:
            # §8: five of the six members are carried across one for one, and
            # `NO_RESULT` maps to **none** — a read that reached the provider and was
            # answered is a completed servicing whose returned count is zero, which
            # ADR-0226 §9 already records.
            return self._not_serviced(FORECAST_DISPOSITIONS.get(refusal))
        # §10's thirteenth case, at the site that performed the call: the call completed
        # and recorded no disposition, which is a read that reached the provider and was
        # answered. `admitted` is filled by the admission site, which is
        # :func:`_serviced_forecast` — this frame has not offered the records to the
        # union.
        return _Forecast(read.records, None, None, contact=OutboundReach.REACHED, serviced=True)

    @staticmethod
    def _not_serviced(disposition: ForecastDisposition | None) -> _Forecast:
        """One non-yield, carrying §8's disposition, §10's member and §10's contact.

        **The three are computed together, at this site, and never apart** (§10). A
        branch that returned one without the others would either put a disposition in
        the audit with nothing for the user, or a member in the reply with nothing in
        the audit, or a contact nobody computed where the call was made — and none of
        the three is derivable from another downstream.

        Args:
            disposition: What this branch resolved to. ``None`` reaches this method from
                exactly one branch — the one that passes
                :data:`FORECAST_DISPOSITIONS` a
                :attr:`~ai_assistant.core.types.ForecastRefusal.NO_RESULT` the mapping
                does not carry — so it is a call that completed and recorded none, which
                is §10's thirteenth case and a contact.

        Returns:
            The empty records, the disposition, the folded member and what the call
            established.
        """
        return _Forecast(
            (),
            disposition,
            forecast_not_read(disposition),
            contact=forecast_contact_of(disposition),
            serviced=True,
        )

    async def _bound(self, proposal: ActionRequest, *, external: bool) -> BoundEgressCall | None:
        """Derive this request's binding, or answer that there is none (ADR-0260 §6, §11).

        **``forecast_reach`` is ``True`` on every request this method builds** (§11),
        and the clause is satisfied by position rather than by a test: it is written
        "exactly where the request's kind is a forecast read and this deployment holds a
        forecast registration, which ``orchestration`` knows because ``Forecaster.request``
        answered a proposal rather than ``None``" — and this method is reached only past
        that answer. It is written by ``orchestration`` alone, at the moment the request
        is built, from a value this frame already holds; **discarded, never merged**, if
        any producer emitted one; and no model output, request content or provider
        answer contributes to it.

        **``closed_loop`` stays ``False`` and is untouched** (§11). It keeps meaning
        "this deployment's own search" and nothing else, and ADR-0272 §1 makes the
        trail refuse a binding carrying neither of the two facts or both — so writing
        it here would make this very row unrecordable.

        **``coverage`` is ``NOT_COVERED`` and is computed rather than defaulted**
        (ADR-0233 §4, §5). That clause puts the value on "the component that composed
        the call's arguments, from the membership and path character of what it supplied
        to the operations that produced them", and this servicing supplied **nothing**
        to any model call: §3 gives the ask no argument, the parameters are the
        deployment's own configured values, and no record, utterance or completion
        reaches them. So there is no covered content on any path of this call, which is
        ADR-0231 §4's state at the neighbouring seam reached here by construction rather
        than by an empty supply.

        **``planned_with_external_content`` is the caller's ``external``** (§7,
        ADR-0181 §4) — a fact about an act this system performed, never an inference
        about how a model produced an argument.

        The ``spans`` mapping is empty, which is ADR-0152 §5's named residue at a third
        call site rather than an omission: nothing in this tree records a span's origin,
        so every span the seam describes is ``SYSTEM_SELECTED``.

        **A refusal, a raise and a ``None`` are one answer here** (§8). A forecast sent
        under no binding is a send to a destination no policy ruled on, so the
        fail-closed reading is the only one available.

        Args:
            proposal: What ``Forecaster.request`` returned — its ``tool`` is the
                forecaster's own registered declaration and its ``parameters`` are the
                arguments that declaration's schema declares.
            external: ADR-0181 §4's fact for this request.

        Returns:
            The derived binding beside the detached call, or ``None`` where the seam
            refused, raised or held no registration.
        """
        try:
            return await self._binder.bind(
                proposal.tool,
                parameters=proposal.parameters,
                provenance=CarriedProvenance(
                    spans={},
                    planned_with_external_content=external,
                    coverage=SpanCoverage.NOT_COVERED,
                    forecast_reach=True,
                ),
            )
        except AssistantError:
            # `EgressBindingError` for a refusal and `ConnectionStoreError` for a
            # connection that could not be read are what this seam contracts (ADR-0152
            # §1, §9); the net is their common root because a fault at this stage is an
            # operator's fact whose class §8 refuses to copy into the record. A
            # `CancelledError` is a `BaseException` and passes through untouched
            # (ADR-0060), and a `TypeError` from a non-conforming implementation is a
            # defect rather than a fault and reaches the turn.
            return None

    async def _ruled(self, request: ActionRequest) -> PermissionDecision | None:
        """Rule on ``request`` and record the decision, or answer that neither held.

        **Every branch is recorded, including a ``DENY``** (ADR-0004 §7), and **every
        branch reads back what the trail holds, not what was written**:
        :class:`SearchServicer`'s own reasoning at a second seam, because a trail that
        accepted the append and lost it would have this method open a channel under a
        decision nothing holds.

        **No ``expires_at`` is ever stamped** (ADR-0260 §11). A deadline is a property
        of a question somebody will answer, and this decision mints **no park** for a
        forecast read: a ``CONFIRM`` recorded here is not parked, holds no question and
        resolves in no turn, so there is nothing for a lifetime to bound.

        Args:
            request: The request carrying its whole binding (ADR-0148 §1).

        Returns:
            The trail's own copy of the recorded decision, or ``None`` where the policy
            raised, the append was refused, or what came back is not what was written.

        Raises:
            ClockReadingError: If the injected clock's reading is not a conforming one.
                Not translated and not swallowed: ADR-0260 adds **no** error class, and
                a clock this process cannot read is not one of §8's decline causes —
                reporting it as ``RULING_UNAVAILABLE`` would report one stage's fault
                under another stage's member.
        """
        try:
            ruling = await self._policy.decide(request)
        except AssistantError:
            # §8's `RULING_UNAVAILABLE`, first limb: `ActionPolicy` raised.
            return None
        decision = PermissionDecision.from_request(
            request, ruling, id=self._id_factory(), decided_at=self._now()
        )
        try:
            await self._trail.record(decision)
            recorded = await self._trail.get(decision.id)
        except AssistantError:
            # §8's second limb: the decision could not be recorded — a refused append,
            # or a read that raised.
            return None
        # Equality over the whole record and not its subject, for `StepRunner._record`'s
        # reason: comparing the tool and the digest leaves the ruling unexamined, so a
        # trail returning a same-subject record with the outcome flipped would have this
        # servicing send a read the policy refused.
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


async def service_read_request(  # noqa: PLR0913, PLR0915 — the store, the emission, and one parameter per thing a kind is serviced against, and one statement per kind serviced plus ADR-0238 §8's fold after each admission and ADR-0251 §2's one recorded fact per kind; §7 admits one site and this is it
    store: MemoryStore,
    request: ReadRequest,
    *,
    supply: Sequence[MemoryRecord],
    fetcher: Fetcher | None,
    listing: SourceListing | None,
    search: SearchServicer | None,
    forecast: ForecastServicer | None,
    utterance: str,
    audit: TurnReadAudit,
    goal: GoalBrief,
    plan: ActionPlan,
    footing: SearchFooting | None = None,
) -> ServicedCarriers:
    """Service one emission, once, into the fourth group (ADR-0226 §§2, 6, 7).

    **The local file is serviced first, then the web search, then the forecast read,
    then the citation hop, then the structured read, then the sighted query**
    (ADR-0260 §7, amending ADR-0240 §5's own amendment of ADR-0231 §11's amendment of
    ADR-0230 §7's amendment of ADR-0226 §6's cross-kind precedence sentence in one
    further respect). §6's
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
        forecast: The four contracts a ``FORECAST_READ`` ask is answered against
            (ADR-0260 §6, §7), or ``None`` where this deployment configured no
            forecast provider. **Passed rather than defaulted**, for ``search``'s
            reason one kind over: a defaulted seam would let a later call site
            silently service no forecast and read, in §9's record, exactly like a
            turn on which the planner asked for none — which is the very collapse
            ADR-0260 §7's ``forecast_serviced`` field exists to close. ``None`` is
            §8's :attr:`ForecastDisposition.NOT_CONFIGURED` and never an error.
        utterance: The turn's own words, unrewritten — **the only value the
            composer is supplied** and the whole of what a search request is
            composed from (ADR-0231 §3, §4). It is not the label space, not a
            deduplication set and not a value any other kind reads: no store value,
            supply, tail, listing, rationale or record reaches the composing seam,
            which is what keeps ADR-0155 §3 from having a subject here.
        goal: The brief of the goal this turn was planned against. It is read by **one**
            kind and only on one branch — ADR-0244 §2's park, where a ``WEB_SEARCH``
            servicing records a ``CONFIRM`` — and reaches no composer, no model call
            and no other kind's servicing.
        plan: The :class:`ActionPlan` the planner returned on the call this servicing
            answers, read on the same one branch and for the same reason. **Passed
            rather than reconstructed**: ADR-0244 §2 persists the plan the parked turn
            actually ran, because re-deriving it at resume "would put a model call
            between the user's *yes* and the read".
        audit: This turn's record. One :class:`ServicedRead` entry is appended to
            :attr:`TurnReadAudit.servicings` on every path out of this function, and
            :attr:`ServicedRead.records` is what the caller appends to the fourth
            group. A turn that services twice appends two, in servicing order
            (ADR-0228 §9).
        footing: This conversation's footing — whether this deployment holds a search
            registration, beside the two record-id sets ADR-0238 §2's supply is built
            from. It carries no store, no bound and no flag (ADR-0247 §5, §6), and what
            it decides about the destination is the registration (ADR-0247 §1). It is
            **per turn** and
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
    union = _Union(
        held={name for record in supply for name in held_names(record)}, budget=READ_BUDGET
    )
    completed: ServicedRead | None = None
    carried = ServicedCarriers()
    empty_read: ReadAsk | None = None
    resolved_by_hop: tuple[MemoryRecord, ...] = ()
    hop = _ask_of(request, ReadKind.CITATION_HOP)
    query = _ask_of(request, ReadKind.SIGHTED_QUERY)
    local_file = _ask_of(request, ReadKind.LOCAL_FILE)
    web = _ask_of(request, ReadKind.WEB_SEARCH)
    forecast_ask = _ask_of(request, ReadKind.FORECAST_READ)
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
    # ADR-0251 §2's four facts, one record per ask, noted **as each ask completes**
    # and in the order ADR-0226 §6 services the kinds in. Declared outside the `try`
    # so that a stage which did not run to its end leaves it where it stood — the
    # facts it holds are then never classified, because `carried` is only built on
    # the success path, which is §2's precedence case 1 for every ask that stage had
    # already put and is ADR-0226 §5's all-or-nothing posture reaching this carrier
    # exactly as it reaches the records.
    ledger = _AskLedger(union, truncated)
    # §2's fourth fact for the sighted query, whose per-band results never leave
    # `assemble_by_band` (see :class:`_Capped`).
    capped = _Capped()
    unresolved = 0
    refusal: FetchRefusal | None = None
    # Assigned before the `try`, because ADR-0231 §13's field rides on the failing
    # record too and a fault raised *by* the search leaves the call that would have
    # assigned it unreturned — where the honest value is the empty one §5's
    # degradation carries (issue #2112).
    #
    # **Its `contact` is `None` and that is ADR-0264 §13 item 7's third shape** (§2): a
    # servicing that raised *before* its search was serviced performed no call, so it
    # establishes nothing either way — and this is the value it carries out, which is
    # what tells it from the first shape, whose search was answered and which carries a
    # contact with `records` `0`.
    searched = _Searched((), None, None)
    # ADR-0260 §7's two audit fields and §10's two carriers ride on the failing record
    # too, for the reason the search's disposition does: a forecast that declined before
    # a later kind's read raised is neither of §8's two empty cases, and the contact its
    # call established is one "nothing that happens to the enclosing servicing
    # afterwards unmakes" (§10). Assigned before the `try` so that a servicing which
    # raised *before* the forecast's position in §7's order leaves behind the honest
    # empty value — an ask this servicing never reached, which `serviced=False` and
    # `contact=None` say together and which neither says alone.
    forecasted = _Forecast()
    # **ADR-0238 §11's three counts are *written* rather than returned**, for the reason
    # `_Reads` is: a fault the searcher raised after the ruling unwinds past the call
    # that would have returned them, and a record saying a servicing admitted no call
    # and composed over nothing would be false of a servicing that did both. Each field
    # is set as its stage completes, so the failing record carries what actually
    # happened.
    counts = _SearchCounts()

    try:
        if local_file is not None and named is not None:
            # ADR-0230 §7: **first**, ahead of the hop, because this kind is capped
            # at one record and the hop at two labels — "at one slot, the cheapest
            # precedence position this corpus has ever had to argue for".
            refusal, missed = await _serviced_file(
                named, fetcher, listing, union=union, reads=reads
            )
            unresolved += missed
            # ADR-0226 §3: a label outside the shown set "resolves to nothing …
            # discarded silently", and nothing reached the fetcher — so no source
            # decided anything about this ask and it earns no carrier entry. Telling
            # a planner the file came back `EMPTY` would be a statement about a
            # fetcher that was never called.
            ledger.note(local_file, reached=missed == 0, non_yield=refusal)
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
            web,
            utterance,
            union=union,
            supply=supply,
            reads=reads,
            truncated=truncated,
            footing=footing,
            counts=counts,
            goal=goal,
            plan=plan,
        )
        if web is not None:
            # ADR-0231 §13 leaves the disposition empty where the search yielded and
            # where it reached the provider and found nothing, so a `None` here sends
            # §2's precedence to the counts — which is where `NO_RESULT` belongs and
            # where a search whose every record deduplicated out belongs too.
            ledger.note(web, reached=True, non_yield=searched.disposition)
        # ADR-0260 §7: **third**, after the one-record local file and the search and
        # ahead of the hop, the structured read and the query. §7 fixes the position by
        # ADR-0226 §6's own rule rather than by preference — the capped read ahead of
        # the uncapped one, and "where two kinds declare the same cap the earlier-admitted
        # kind is serviced first" — so the order runs one record, then at most
        # `search_max_results`, then at most `forecast_max_days`, then ten through two
        # labels, then what remains twice over. **No configuration reorders them.**
        #
        # A `FORECAST_READ` ask carries no argument at all (§3), so there is nothing to
        # read off it: its presence *is* the whole of the ask, and the place and the
        # horizon are the deployment's own — which is why the ask is passed whole and
        # every absence this kind has is answered in :func:`_serviced_forecast`.
        # **§7's first audit field is taken before the stage is awaited, and that is the
        # whole of what makes it true of a stage that then raised.** A fault the
        # forecaster itself raises unwinds past the assignment below, and a cancellation
        # carries the frame away entirely — so a mark taken only from the returned value
        # would report an ask this servicing **put to the seam** as one it never
        # reached, which is exactly the collapse the field exists to close. It is not
        # recoverable from the disposition afterwards either: §8 closes the vocabulary
        # at twelve with no member for a fault at the send, so the degraded record
        # carries none.
        #
        # `forecast_ask is not None` is the whole condition, because the next line *is*
        # the stage: an emission carrying no such ask reaches it and is answered `False`
        # by :func:`_serviced_forecast` itself, and one carrying an ask has by here
        # reached the forecast's own position in §7's order.
        forecasted = _Forecast(serviced=forecast_ask is not None)
        forecasted = await _serviced_forecast(
            forecast,
            forecast_ask,
            union=union,
            supply=supply,
            reads=reads,
            truncated=truncated,
        )
        if forecast_ask is not None:
            # ADR-0260 §8 leaves the disposition empty where the read yielded and where
            # it reached the provider and found nothing, so a `None` here sends ADR-0251
            # §2's precedence to the counts — which is where `NO_RESULT` belongs and
            # where a read whose every record deduplicated out belongs too. **`NO_BUDGET`
            # produces no entry at all** and needs no branch here: §8's classifier entry
            # puts it under case 1, which :data:`_NON_YIELD_CLASSES` states as
            # `UNREACHED`.
            #
            # **`source` is ADR-0252 §1's field as ADR-0260 §9 fills it** — "the
            # forecaster's ``name``" — read off the wired servicer and never composed
            # here. A deployment holding none has no source to declare, and the row it
            # writes for a `NOT_CONFIGURED` ask leaves the field absent, which is what
            # ADR-0252 §1 says of every row whose kind is the whole of its source
            # identity.
            ledger.note(
                forecast_ask,
                reached=True,
                non_yield=forecasted.disposition,
                source=None if forecast is None else forecast.name,
            )
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
            # A hop whose every label resolved to nothing made no store call at all
            # (:func:`_hop_records` returns before one), so no source answered it —
            # ADR-0226 §3's silent discard, which the audit counts as an unresolved
            # label and which §2 leaves out of the carrier. A hop that resolved one
            # of two labels **did** read, and what it read is what the counts report.
            #
            # **What it read is the expansion, not the evidence** (ADR-0229 §3). The
            # union is offered the evidence alone, because ADR-0229 §2 counts a named
            # record "in none of the three" — so the union's delta answers what this ask
            # *contributed* and not what the store *returned*, and a hop reaching a live
            # record that carries no citations returned that record. Classified off the
            # union it would be `EMPTY`, which ADR-0251 §2 reserves for a source that
            # returned no record at all; it is a `DUPLICATE`, and §2 says which in terms.
            # The audit's own counters are untouched by this: they stay the union's.
            ledger.note(
                hop,
                # **The store call, not the label count** (ADR-0251 §2). A label whose
                # record the store no longer holds is counted as unresolved too
                # (ADR-0229 §4), so a hop whose one label named a record deleted between
                # the planning and the read has `unresolved == len(labels)` and a
                # *completed* store call behind it that returned nothing — which is
                # `EMPTY` and not §2's case 1, because that case is "the ask was not
                # made" and this one was.
                reached=reach.read,
                non_yield=None,
                records=reach.expansion,
            )
        if structured is not None and structured.structure is not None:
            # ADR-0240 §5: **fourth**, after the hop and ahead of the query — the
            # position ADR-0226 §6's own rule reaches for a kind with no cap of its
            # own, since the sighted query is the read that "fills what remains" and
            # there can only be one of those.
            read = await _serviced_structured(
                store,
                structured.structure,
                structured.query,
                union=union,
                supply=supply,
                reads=reads,
                truncated=truncated,
            )
            outcome, empty = read.outcome, read.empty
            # §2's three no-entry states for this kind — `NOT_ASKED`, `NO_SEPARATOR`
            # and `NO_SLOT` — are carried as the non-yield they are and classified by
            # the one table, rather than tested a second time here. `capped` is the
            # store's own candidate ceiling (ADR-0128 §2), the second of §2's two
            # independent grounds for leaving completeness uncertified.
            ledger.note(structured, reached=True, non_yield=read.outcome, certified=not read.capped)
            # ADR-0240 §7: the ask **the planner emitted**, byte for byte, and only
            # where the read ran and returned nothing. The other four outcomes
            # establish nothing about the store, so none of them reaches this
            # carrier.
            empty_read = structured if empty else None
        if query is not None and statement is not None:
            # ADR-0226 §6: **last**, because it is the read that "fills what
            # remains" — the one uncapped kind, and the position ADR-0240 §5 sorts
            # the structured read just above.
            asked = await _serviced_query(
                store, statement, union=union, reads=reads, capped=capped, truncated=truncated
            )
            # **`asked` is ADR-0251 §2's precedence case 1 for this kind**, and it is a
            # fact only the read holds: this kind is serviced **last**, so it is the one
            # the budget can leave with no slot at all — and a read the budget did not
            # reach "is not in it" (ADR-0240 §7, restated by §3). It is not derivable
            # from the truncation list, which records such a read as cut rather than as
            # unmade (ADR-0226 §6), nor from the counts, which a store that matched
            # nothing produces identically.
            #
            # ADR-0226 §6's cut is then the ledger's own test, and `capped.seen` is the
            # second ground (ADR-0128 §2), observed rather than read because this kind is
            # several store calls behind one call.
            ledger.note(query, reached=asked, non_yield=None, certified=not capped.seen)
        # ADR-0251 §3 and §7 read one classification, not two: the carrier the next
        # planner call receives and the members §9's record accounts per servicing are
        # the same sequence, so classifying twice would be two authorities on what
        # became of one ask.
        classified = classified_reads(ledger.facts)
        completed = ServicedRead(
            kinds=tuple(ask.kind for ask in request.asks),
            records=tuple(union.admitted),
            returned=union.returned,
            new=len(union.admitted),
            deduplicated=union.deduplicated,
            labels_unresolved=unresolved,
            refusal=refusal,
            disposition=searched.disposition,
            # ADR-0260 §7's two added fields, and they answer different questions:
            # whether this servicing put a `FORECAST_READ` ask to the forecast stage at
            # all, and what became of it where it has a member. **Neither is derivable
            # from the other** — an absent disposition covers both a read the provider
            # answered and an ask nothing reached — and **no value the provider returned,
            # no day, no place, no coordinate, no origin, no account and no `Settings`
            # field name** is anywhere near either, which is §9's counts-and-no-copy rule
            # binding unchanged.
            forecast_serviced=forecasted.serviced,
            forecast=forecasted.disposition,
            # ADR-0238 §11's two and ADR-0245 §7's third, per turn and per servicing:
            # how many records were supplied to the composer, how many §3's filter
            # withheld — zero on every path since ADR-0246 §1 — and how many of the
            # supplied ones carry a narrowed reach. **`calls` is gone with the budget**
            # (ADR-0247 §6), which supersedes §11's second clause in that limb alone.
            # **Counts only** — no record id, no conversation id, no destination, no
            # query text and no fragment of one is anywhere in this record.
            supplied=counts.supplied,
            withheld=counts.withheld,
            supplied_narrowed=counts.supplied_narrowed,
            structured_axes=axes,
            # ADR-0240 §10: `None` until the branch above assigns one, and assigned
            # eagerly to `NOT_ASKED` where the request carried no such ask — so this
            # is a member on every completed servicing and `None` on no completed
            # one, which is what makes the absent value mean "the servicing did not
            # complete" and nothing else.
            structured=outcome,
            truncated_kinds=tuple(truncated),
            # ADR-0251 §7: the member per ask, in servicing order — the carrier's own
            # sequence projected onto its outcomes, with the asks left behind.
            outcomes=tuple(one.outcome for one in classified),
        )
        # ADR-0227 §3's carrier, computed on the success path alone and through
        # `_Union.holds` — the union's seen set is seeded from the pre-servicing supply
        # and grown by every admission, so membership of it *is* "the supply holds this
        # record after servicing". A named record passes that test by construction
        # (ADR-0229 §2), so the restriction bites on truncated evidence alone.
        # `dict.fromkeys` is ADR-0227 §4's deduplication over ADR-0229 §3's
        # expansion sequence, with the first occurrence keeping the place:
        # `Provenance.evidence` carries no uniqueness constraint and nothing stops
        # one label naming what another cites, so the expansion can name one record
        # more than once — `E, B, E` deduplicates to `E, B`, which §3 rules the
        # required result rather than a case to repair.
        carried = ServicedCarriers(
            hop_reached=tuple(
                dict.fromkeys(record.id for record in resolved_by_hop if union.holds(record)).keys()
            ),
            empty_read=empty_read,
            # ADR-0251 §3's carrier, classified **on the success path alone** — a
            # servicing that failed or was partial carries none, which is §2's
            # precedence case 1 and ADR-0226 §5's all-or-nothing posture reaching
            # this carrier exactly as it reaches the records and the counts.
            yields=classified,
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
        # ADR-0264 §2 places `SEARCH_FAILED` in the second group: a fault raised out of
        # `WebSearcher.search` is consistent with a request that left and with one that
        # did not, so the turn says this system cannot tell rather than claiming either.
        searched = _Searched(
            (),
            SearchDisposition.SEARCH_FAILED,
            SearchNotServiced.UNAVAILABLE,
            contact=contact_of(SearchDisposition.SEARCH_FAILED),
        )
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
                # ADR-0260 §7's pair rides on the failing record for the disposition's
                # own reason: §8 enumerates the two cases in which its field is empty —
                # where the read yielded records, and where no `FORECAST_READ` ask was
                # made — and a forecast that declined before a later kind's read raised
                # is neither. `forecast_serviced` rides beside it because that is exactly
                # the turn on which the pair earns its keep: it says whether the ask was
                # reached at all, which an empty disposition on a degraded servicing
                # cannot.
                forecast_serviced=forecasted.serviced,
                forecast=forecasted.disposition,
                supplied=counts.supplied,
                withheld=counts.withheld,
                supplied_narrowed=counts.supplied_narrowed,
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
    return replace(
        carried,
        # ADR-0249 §7's carrier, folded on **every** path out of the body above for the
        # same reason the three below it are: `searched` is assigned on each of them and
        # `carried` is rebuilt only on the success path. Empty on every servicing that
        # minted nothing, which is every one that carried no `WEB_SEARCH` ask.
        minted=tuple(record.id for record in searched.records),
        not_serviced=searched.not_serviced,
        parked_read=searched.parked_read,
        parked_decision=searched.parked_decision,
        # ADR-0264 §2's carrier, folded on **every** path out for the identical reason,
        # and that is the whole of what makes the failed servicing's contact survive:
        # "a contact is established the moment a response arrived, and nothing that
        # happens to the enclosing servicing afterwards unmakes it". A servicing whose
        # search was answered and whose later `SIGHTED_QUERY` raised carries it here,
        # and one that raised *before* its search was serviced carries `None` — which is
        # the pair §2 says no site can tell apart from the ended servicing's record.
        contact=searched.contact,
        # ADR-0260 §10's two carriers, folded on **every** path out of the body above for
        # the identical reason: `forecasted` is assigned on each of them and `carried` is
        # rebuilt only on the success path. A servicing whose forecast was answered and
        # whose later read then raised carries the contact here — §13's arm (n) — and one
        # that raised *before* the forecast was serviced carries `None`, which is the pair
        # §10 says no site can tell apart from the ended servicing's record.
        forecast_not_read=forecasted.not_read,
        forecast_contact=forecasted.contact,
        # ADR-0264 §4 over ADR-0226 §5: `records` counts what entered the supply, and a
        # failed servicing entered nothing — §5 "leaves the supply as planning saw it"
        # and the caller appends `ServicedRead.records`, which the failing record leaves
        # empty. `completed` is `None` on exactly the degraded paths, so this is the
        # servicing's own all-or-nothing posture reaching the count rather than a second
        # rule about it. §4 rules that the resulting `0` never suppresses the statement.
        contact_records=searched.admitted if completed is not None else 0,
        # ADR-0264 §4 over ADR-0226 §5, exactly as above: a failed servicing entered
        # nothing, so the contact §13's arm (n) requires to survive it stands beside a
        # `0` — which §4 rules never suppresses the statement.
        forecast_records=forecasted.admitted if completed is not None else 0,
    )


def _search_supply(
    utterance: str,
    in_view: Sequence[MemoryRecord],
    *,
    trusted: bool,
    footing: SearchFooting,
) -> tuple[SearchSupply, int]:
    """Build ADR-0238 §2's supply for this servicing, and take §7's supplied-narrowed count.

    **One type, two admissible populations, and a recorded fact decides which**
    (ADR-0238 §2). Where the destination the servicing would bind to reads
    ``UNCHOSEN`` the supply carries the utterance and an empty ``records``, so
    ADR-0231 §3's utterance-only property holds for that destination exactly as
    ratified — and never by a judgement about the turn, the words or the records.

    **What may enter is closed to three populations** (§2): episodes of this
    conversation that ``orchestration`` selected into the turn's supply; the
    ``MemoryRecord`` values the turn's retrieval and episodic supplement selected; and
    records **this turn's own** ``WEB_SEARCH`` servicings minted at a destination of
    recorded trust ``USER_CHOSEN`` — which ADR-0247 §1 decides from the registration.
    The first two are :attr:`SearchFooting.selected`, written by the loop from the
    supply it assembled; the third is :attr:`SearchFooting.minted_user_chosen`. The two
    sets are the whole of the membership test below, which is why ADR-0247 §3 keeps them
    (*"``SearchSupply``, its populations and its construction site are untouched"*) while
    §11's lane-4 enumeration removes every other member of that object. **Nothing of any
    other origin enters** —
    "no record minted at an ``UNCHOSEN`` destination, by a fetch, by a file read, by a
    reader or by any tool" — and each of those reaches the turn through a *servicing*
    rather than through the supply the planner was assembled over, so none of them is in
    either set.

    **Membership of the enumerated populations, and never cleanliness.** A stamped
    episode carries a recorded external span and is admitted here whichever conversation
    it belongs to, because §2 names it and §2's own closing paragraph makes it the thing
    that "resolves *find more about that* across turns". **Whether it costs the
    *closed-loop* condition is no longer a question at all** (ADR-0247 §4): §5's
    current-turn and recorded halves are retired and the predicate that answered them is
    removed with the budget (ADR-0247 §5), so a record of any other external origin is
    composed over *and* sent, and what bounds the disclosure is the destination rather
    than the lineage.

    **§3's filter reads no placement at all, on a chosen destination** (ADR-0246 §1).
    Reach is audience control — ADR-0217 §1's denotation of a set of **people** — and
    a search provider the owner named in a recorded act is not a person this
    assistant talks to, so no record is withheld from this supply on its reach, on
    its setter, or on any combination of the two, **whatever the setter**: a
    derivation's narrowing, the owner's own act and a model's proposal are admitted
    alike. What bounds the population is the membership test above and the trust read
    below it, and nothing about the records' placements. That is what gives ADR-0238
    §2's cross-turn promise a producer: the stamped episode a later turn retrieves
    carries reach ``OWNER`` with setter ``DERIVED``, which is the record #2224 watched
    ADR-0238 §3's filter drop on every later turn while the composer declined.

    **Reach keeps its full force where a person listens** (ADR-0246 §1). ADR-0199
    §3's classes, ADR-0203 §1's subtraction and ``orchestration/disclosure.py``'s four
    reads are untouched: a record narrowed to the owner stays withheld from every
    reply and every delivery whose audience is wider, exactly as it is today. What
    ADR-0246 widens is one supply built for a party that is not a person.

    **No component decides exclusion by inspecting content** (§3), and nothing here
    reads a record's text, resembles it against anything, or asks a model about it.
    No ``about_person`` filter runs here either (ADR-0245 §2): ADR-0199 §3's classes
    place a class as speakable *on a channel* and this places a record *for a set of
    people*, and a supply exists at all only on an operation whose channel audience
    is bounded (ADR-0226 §5).

    Args:
        utterance: The turn's own words, unrewritten.
        in_view: The turn's pre-servicing supply and every record this servicing has
            already contributed.
        trusted: Whether the destination this servicing would bind to is one the
            owner chose — which ADR-0247 §1 decides from the deployment holding a
            search registration at all, in place of the ``trust_of`` read §2 used to
            oblige. Taken before the supply is built and deciding only what may be
            composed over.
        footing: This conversation's footing, for the one predicate above.

    Returns:
        The supply, and how many of the records it *supplied* carry a reach that is
        not ``ANYONE`` — ADR-0245 §7's fourth count, which ADR-0246 §7 keeps and
        widens over every setter. It is the one number that measures the class
        ADR-0246 §1 lets through, it rises on the same deployment the day that
        decision lands, and **no lane reads that rise as a defect**. There is no
        withheld count to return: ADR-0238 §11's second count is structurally zero on
        both branches below, and :class:`_SearchCounts` carries it at that value.
    """
    if not trusted:
        # ADR-0238 §2's trust clause empties the whole population — the supply carries
        # the utterance and an empty `records`, and ADR-0231 §3's utterance-only
        # property holds for that destination exactly as ratified. **The emptiness is
        # the trust clause's and not a placement filter's** (ADR-0246 §11 Arm G), which
        # is why the withheld count is zero here rather than the population's size.
        # **Unreached on a deployment that configured a provider** (ADR-0247 §1): the
        # clause's subject is now the registration, and a deployment holding none
        # services no search at all.
        return SearchSupply(utterance=utterance), 0
    supplied = tuple(
        record
        for record in in_view
        if record.id in footing.selected or record.id in footing.minted_user_chosen
    )
    return (
        SearchSupply(utterance=utterance, records=supplied),
        sum(1 for record in supplied if record.placement.reach is not PlacementReach.ANYONE),
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
    goal: GoalBrief,
    plan: ActionPlan,
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
        counts: ADR-0238 §11's counts as ADR-0247 §6 leaves them, filled in as the
            stages complete. Written through rather than returned, for
            :class:`_Reads`' reason.
        footing: This conversation's footing, or ``None`` where the caller passed
            none — which is a turn running under no conversation at all. **``None``
            services no search at all**, and that stays fail-closed after ADR-0247 §5
            removes the admission that used to be the reason: a servicing with no
            conversation can write no park (ADR-0244 §1), and letting it search anyway
            would widen what this decision says nothing about. No production
            composition reaches it — ``app/composition.py`` wires the footing
            unconditionally and every production caller of
            :meth:`~ai_assistant.orchestration.loop.PlanningLoop.respond` passes a
            conversation it has already begun.
        goal: The brief of the goal this turn was planned against, persisted onto a park where this
            servicing records a ``CONFIRM`` (ADR-0244 §2).
        plan: The plan the planner returned on the call this servicing answers,
            persisted for the same reason.

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
        # member either.
        #
        # **ADR-0264 §2: no call was performed, so this establishes nothing either
        # way and contributes nothing to the fold.** `contact` is `None` and not
        # `NOT_REACHED`: the two fold identically (§2's order), and the distinction
        # is kept because `None` is the honest statement of a site that did nothing
        # — a turn every one of whose sites contributed nothing is `NOT_REACHED` by
        # §1 and not by an arm here.
        return _Searched((), None, None)
    if search is None:
        # ADR-0242 §8's residue: a deployment that connected no search account gives the
        # user no act, so `UNAVAILABLE` — the member that names no cause and no act.
        #
        # ADR-0264 §2 places `NOT_CONFIGURED` in the third group: no channel was
        # opened, so no contact.
        return _Searched(
            (),
            SearchDisposition.NOT_CONFIGURED,
            SearchNotServiced.UNAVAILABLE,
            contact=contact_of(SearchDisposition.NOT_CONFIGURED),
        )
    if footing is None:
        # **No conversation, so no park could be written and nothing is serviced.**
        # This branch used to name ADR-0238 §8's refused admission; ADR-0247 §5 removes
        # the budget and §6 removes the disposition that named it, so what is left is
        # the deployment fact the branch above reports — this loop can service no search
        # for this turn — under the member ADR-0242 §8 reserves for an outcome the user
        # has no act for. **The disposition claims nothing more than that**: it does not
        # say the conversation's allowance ran out, because there is no allowance.
        # Unreachable in production, where `app/composition.py` wires the footing
        # unconditionally and every caller passes a conversation it has already begun,
        # and fail-closed rather than a fallback.
        return _Searched(
            (),
            SearchDisposition.NOT_CONFIGURED,
            SearchNotServiced.UNAVAILABLE,
            contact=contact_of(SearchDisposition.NOT_CONFIGURED),
        )
    # ADR-0238 §5's own words for what this holds: "the turn's pre-servicing supply and
    # every record this servicing has already contributed", read once here so that
    # ADR-0181 §4's fact and ADR-0238 §2's supply are computed from **one** value at
    # **one** instant rather than from two reads that could disagree.
    in_view = (*supply, *union.admitted)
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
            # ADR-0244 §2: the two members the continuation would otherwise fabricate,
            # handed to the one site that may write a park. They reach no composer and
            # no model call, and a servicing that records no `CONFIRM` never reads them.
            goal=goal,
            plan=plan,
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
    # ADR-0264 §4's count, taken **here, at the site that performs the admission**, and
    # never reconstructed: the delta is what the union took after ADR-0226 §7's
    # deduplication over the whole union and §6's budget, so a response carrying two
    # records under one id contributes one and a response the budget cut contributes
    # what fit. A lane reading `len(found.records)` or `ServicedRead.supplied` counts a
    # different population, and §4 refuses both by name.
    before = len(union.admitted)
    if union.admit(found.records):
        truncated.append(ReadKind.WEB_SEARCH)
    return replace(found, admitted=len(union.admitted) - before)


async def _serviced_forecast(  # noqa: PLR0913 — the seam, the ask, and the three things ADR-0260 §7 states this kind's budget and origin clauses over; §7 admits one servicing site and this is that site's third kind
    forecast: ForecastServicer | None,
    ask: ReadAsk | None,
    *,
    union: _Union,
    supply: Sequence[MemoryRecord],
    reads: _Reads,
    truncated: list[ReadKind],
) -> _Forecast:
    """Service one ``FORECAST_READ`` ask into the fourth group (ADR-0260 §7).

    **This kind's whole budget clause is here**, because §7 states it over this kind
    rather than over the union: "where the slots remaining when the forecast is reached
    are fewer than the days minted, the servicer admits the records that fit, in the
    order §5 minted them, and admits no more", and "where fewer than one slot remains …
    no request is composed, no ruling is sought and no channel is opened". Both are
    branches of one arithmetic, so both live at one site. The union and the truncation
    record are the same ones every other kind draws on and writes to — "one budget, and
    the forecast draws at most ``forecast_max_days`` slots of it", "not a share, not a
    second budget" — so this kind is truncated exactly as the search and the hop are,
    and **no lane funds it by lowering** ``RETRIEVAL_LIMIT`` **or**
    ``EPISODIC_SUPPLEMENT_LIMIT``.

    **The origin fact is computed here, by the component that holds the records** (§7).
    It is "the disjunction of ``rests_on_recorded_external_content`` over the turn's
    pre-servicing supply and over every record this servicing has already contributed",
    evaluated at the moment the request is built, from records ``orchestration`` holds
    as data it fetched — which is why the file **and the search** serviced ahead of it
    are both in view, and is what §13's arm (m) asserts: a servicing whose pre-servicing
    supply carried no external record and whose web search then contributed one builds a
    forecast binding carrying ``True``.

    **This is not ADR-0223 §2's externality value and not ADR-0204 §2's withholding
    value** (§7). Those two are computed once, at the loop, over the turn's *final*
    supply; this is a per-request fact at a per-request instant, and neither is read off
    the other.

    Args:
        forecast: The wired servicer, or ``None`` where this deployment configured no
            forecast provider — §8's :attr:`ForecastDisposition.NOT_CONFIGURED`, and
            never an error.
        ask: The emission's ``FORECAST_READ`` ask, or ``None`` where it carried none.
            Passed whole rather than as a boolean because §3 makes its presence the
            entire content of the ask: it has no argument to read, so there is nothing
            else this function could want from it.
        union: The fourth group under construction. Its unspent slot count is what §7's
            two budget branches are decided on, and it is what the minted records are
            admitted into — under ADR-0226 §7's whole-union deduplication, which binds a
            minted forecast record as it binds any other.
        supply: The three groups the loop passed the planner on this call, which is half
            of §7's disjunction. The other half is what this servicing has already
            admitted into ``union``.
        reads: The servicing's read observer, noted when a read returns records —
            ADR-0226 §9's second failure field is stated over *reads*, and a forecast
            that came back with records is a read this servicing performed that returned
            some.
        truncated: The servicing's truncation record, appended to where the budget cut
            this kind short. ADR-0251 §2's ``TRUNCATED`` then displaces ``EMPTY``,
            ``DUPLICATE`` and ``RETURNED_RECORDS`` through the one test the ledger
            applies for all six kinds.

    Returns:
        The minted records, §8's disposition, §10's folded member, §10's contact and the
        count this servicing admitted. The disposition is ``None`` in each of the cases
        §8 leaves the field empty: where no ``FORECAST_READ`` ask was made, where the
        read yielded records, and where it reached the provider and returned none.

    Raises:
        _ServicingFailedError: If the forecaster raised a fault that is **not** one of
            §6's three pre-execution checks. Carried to ADR-0226 §5's degradation rather
            than reported as a disposition, because §8 closes this vocabulary at twelve
            with no member for a fault at the send — ``SearchDisposition.SEARCH_FAILED``
            has no forecast twin, and §12 forbids a lane adding one.
    """
    if ask is None:
        # §8's second absence: no ``FORECAST_READ`` ask was made. Answered before the
        # deployment is consulted, so a turn nobody asked a forecast of reads the same
        # on a configured deployment and an unconfigured one. **`serviced` is ``False``
        # and `contact` is ``None``** — no call was performed, so this establishes
        # nothing either way and contributes nothing to the fold (§10).
        return _Forecast()
    if forecast is None:
        # §8's first route to `NOT_CONFIGURED`: no forecaster is wired into the loop at
        # all. §10 places it in the no-contact group — no channel was opened — and folds
        # it to `NOT_CONFIGURED`, whose statement names an **operator** setting.
        return _Forecast(
            (),
            ForecastDisposition.NOT_CONFIGURED,
            forecast_not_read(ForecastDisposition.NOT_CONFIGURED),
            contact=forecast_contact_of(ForecastDisposition.NOT_CONFIGURED),
            serviced=True,
        )
    # §7's own words for what this holds: "the turn's pre-servicing supply and over every
    # record this servicing has already contributed", read once here so that ADR-0181
    # §4's fact is computed from **one** value at **one** instant.
    in_view = (*supply, *union.admitted)
    try:
        read = await forecast.service(
            remaining=union.remaining,
            external=any(
                rests_on_recorded_external_content(record.provenance) for record in in_view
            ),
        )
    except AssistantError as exc:
        # ADR-0226 §5, and the reason :class:`_ServicingFailedError` exists. §6's three
        # pre-execution checks resolve to `BINDING_FAILED` inside `service` without
        # reaching here; what reaches here is a fault that is none of them — a call bound
        # to another account or another origin, a transport pin refused, a cancellation
        # the transport invented with nothing cancelled. §8 gives the vocabulary no
        # member for any of them, so the ratified answer is the all-or-nothing
        # degradation, which leaves the supply as planning saw it with every count zero.
        #
        # **``from None``, and the class name rather than the exception** (ADR-0004 §5):
        # the chain this suppresses would put `service`'s frames — the request, the
        # bound call and the decision — into any rendered traceback.
        raise _ServicingFailedError(type(exc).__name__) from None
    reads.note(len(read.records))
    # ADR-0264 §4's count, taken **here, at the site that performs the admission**, and
    # never reconstructed: the delta is what the union took after ADR-0226 §7's
    # deduplication over the whole union and §6's budget, so a response whose days the
    # budget cut contributes what fit — §13's arm (f), where nine spent slots admit
    # exactly one day and the kind is recorded as truncated.
    before = len(union.admitted)
    if union.admit(read.records):
        truncated.append(ReadKind.FORECAST_READ)
    return replace(read, admitted=len(union.admitted) - before)


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


async def _serviced_query(  # noqa: PLR0913 — the store, the query, and one parameter per thing this kind is serviced against: ADR-0226 §6's one budget, §9's read observer, ADR-0251 §2's capped observer and §6's truncation record
    store: MemoryStore,
    statement: str,
    *,
    union: _Union,
    reads: _Reads,
    capped: _Capped,
    truncated: list[ReadKind],
) -> bool:
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
        capped: ADR-0251 §2's fourth fact for this kind, threaded in as the ``capped``
            observer for the identical reason — the per-band
            :class:`~ai_assistant.core.types.MemorySearchResult` never leaves
            ``assemble_by_band``, and a band that refused to certify its answer is one
            this ask's completeness cannot be claimed over.
        truncated: The servicing's truncation list, appended to in servicing order.

    Returns:
        Whether this ask reached the store at all — ``False`` where the kinds before it
        left no slot, which ADR-0251 §2's precedence case 1 makes a read that earns no
        outcome rather than an empty one. It is **not** the same fact as the truncation
        this function also records: ADR-0226 §6 reads a cut as "the budget shortened the
        ask", and a budget of nothing did not shorten an ask, it prevented one.

    Raises:
        MemoryStoreError: Propagated from any band's read, to ADR-0226 §5's one
            degradation site.
    """
    allowed = union.remaining
    found = (
        []
        if allowed <= 0
        else await assemble_by_band(
            store,
            statement,
            limit=allowed,
            kinds=BELIEF_KINDS,
            on_page=reads.note,
            on_capped=capped.note,
        )
    )
    union.admit(found)
    if allowed < READ_BUDGET and len(found) == allowed:
        truncated.append(ReadKind.SIGHTED_QUERY)
    return allowed > 0


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
) -> _Structured:
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
        :class:`_Structured`: the state this ask reached, whether the store call
        returned no record at all — §6's *empty structured read*, which is ``False`` on
        every path that made no store call — and whether the store's own candidate
        ceiling bound the read (ADR-0128 §2, ADR-0251 §2), which is ``False`` on those
        same paths for the same reason.

    Raises:
        MemoryStoreError: Propagated from the store, to ADR-0226 §5's one degradation
            site. This kind adds no error class and no second net.
    """
    if all(MemoryKind(record.kind) is MemoryKind.EPISODIC for record in (*supply, *union.admitted)):
        # ADR-0240 §5, taking ADR-0158 §4's rule for this kind: the test is made
        # **before** the read, so nothing is discarded and ADR-0226 §7's
        # discards-nothing-by-class clause is not approached. §10 records this in
        # preference to the slot outcome where both hold.
        return _Structured(StructuredOutcome.NO_SEPARATOR, False)
    limit = union.remaining
    if limit <= 0:
        return _Structured(StructuredOutcome.NO_SLOT, False)
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
            episode_model_eligible=True,
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
            episode_model_eligible=True,
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
    # ADR-0251 §2's fourth fact, read off the store's own answer rather than
    # inferred from the yield. It is orthogonal to the budget cut above — a read
    # given the whole budget can still come back ``capped`` — and to the yield: a
    # ``capped`` read that admitted records is still one whose completeness was not
    # certified.
    if not found:
        return _Structured(StructuredOutcome.RETURNED_NOTHING, True, result.capped)
    return _Structured(StructuredOutcome.RETURNED_RECORDS, False, result.capped)


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
        attempt_kind: ADR-0251 §7's first added turn-level field: the
            :class:`~ai_assistant.core.types.AttemptKind` of the attempt this turn
            ran inside, or ``None`` where the turn that opened that attempt declared
            no operation. **Written by the loop from the ledger it holds**, never
            derived at read time and never taken from this turn's own operation
            (§5's stamping clause).
        attempt_calls_before: What the attempt's ledger held **as this turn found
            it** — zero on an attempt this turn opened. The record ADR-0251 §7 asks
            for is the attempt's *consumed* calls, and :meth:`emit` derives it as
            this plus :attr:`planner_calls`: the two counts are one quantity read at
            two scopes, and storing the sum beside its own addend would be two
            places for one figure to disagree.
        attempt_allowance: ADR-0251 §7's third: the planner-call allowance that
            attempt's kind **declares**, or ``None`` where its kind declares none —
            which is the fail-closed case §5 names, and is what makes an attempt that
            did not iterate distinguishable in the record from one that iterated to a
            bound. A count and never a duration: the reserve, the working allowance
            and the per-turn budget are not here, because ADR-0226 §9's record
            "carries no timing figure".
    """

    trigger: TriggerOutcome = TriggerOutcome.NOT_REACHED
    servicing: Servicing = Servicing.NOT_ASKED
    servicings: tuple[ServicedRead, ...] = ()
    planner_calls: int = 0
    stop: StopReason = StopReason.NOT_ITERATED
    attempt_kind: AttemptKind | None = None
    attempt_calls_before: int = 0
    attempt_allowance: int | None = None

    def emit(self) -> None:
        """Write this turn's record — see :func:`emit_read_audit`."""
        emit_read_audit(
            trigger=self.trigger,
            servicing=self.servicing,
            servicings=self.servicings,
            planner_calls=self.planner_calls,
            stop=self.stop,
            attempt_kind=self.attempt_kind,
            # **Derived at emission and charged before each call** (ADR-0251 §12):
            # `planner_calls` advances on the line before `Planner.plan` is entered,
            # so a turn whose second call raised contributes that call to the
            # attempt's consumed figure exactly as it contributes it to its own.
            attempt_planner_calls=self.attempt_calls_before + self.planner_calls,
            attempt_allowance=self.attempt_allowance,
        )


def emit_read_audit(  # noqa: PLR0913 — one keyword per field of ADR-0226 §9's record, as ADR-0228 §9 and ADR-0251 §7 each extend it; a bundle here would be a second spelling of `TurnReadAudit`
    *,
    trigger: TriggerOutcome,
    servicing: Servicing,
    servicings: Sequence[ServicedRead] = (),
    planner_calls: int = 0,
    stop: StopReason = StopReason.NOT_ITERATED,
    attempt_kind: AttemptKind | None = None,
    attempt_planner_calls: int = 0,
    attempt_allowance: int | None = None,
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

    **And no value the forecast provider returned, in any form** (ADR-0260 §7). No day,
    no place, no coordinate, no origin, no account, no provider message and no
    ``Settings`` field name appears anywhere in this event on account of a
    ``FORECAST_READ``, and **no count of the days ADR-0260 §5 dropped**: §7 refuses that
    class because every count here "is taken over a servicing that completed" and is
    zero on one that failed, so a drop count would have to be zeroed by a later ask's
    failure to obey §9 and non-zero to be worth having. The two fields this kind adds
    are a **boolean** and a **class**: ``forecast_serviced`` says whether the ask was
    put to the forecast stage at all, and ``forecast`` is a :class:`ForecastDisposition`
    member or absent. The honest consequence — that a response this system thinned is
    not distinguishable here from one the provider gave thin — is ADR-0260 §14's
    deferral rather than a gap this record fills.

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
        attempt_kind: The attempt's kind, or ``None`` (ADR-0251 §7).
        attempt_planner_calls: What the attempt's ledger holds after this turn's
            charges (ADR-0251 §7).
        attempt_allowance: What that kind declares, or ``None`` where it declares
            none (ADR-0251 §7).
    """
    _log.info(
        READ_AUDIT_EVENT,
        correlation_id=current_correlation(),
        trigger=trigger.value,
        servicing=servicing.value,
        planner_calls=planner_calls,
        stop=stop.value,
        # ADR-0251 §7's three turn-level additions, extending ADR-0226 §9's record
        # rather than replacing it: a kind, a count and a count. **The stop
        # distribution is the instrument §14 fires the revision of §5's figures
        # off**, and it is unreadable without them — a `bound_reached` says nothing
        # about whether four was the wrong figure unless the record also says which
        # allowance was in force and how much of it the attempt had consumed.
        attempt_kind=None if attempt_kind is None else attempt_kind.value,
        attempt_planner_calls=attempt_planner_calls,
        attempt_allowance=attempt_allowance,
        servicings=tuple(
            {
                "kinds": tuple(kind.value for kind in read.kinds),
                "returned": read.returned,
                "new": read.new,
                "deduplicated": read.deduplicated,
                "labels_unresolved": read.labels_unresolved,
                "refusal": None if read.refusal is None else read.refusal.value,
                "disposition": None if read.disposition is None else read.disposition.value,
                # ADR-0260 §7's two added fields, on the one event and under the one key:
                # **no second audit**, no second event key and no new emission point.
                # A boolean and a **class** — `forecast` is a `ForecastDisposition`
                # member or absent — which is what §9's no-copy rule admits, exactly as
                # it admits `refusal`, `disposition` and `structured` above. **No value
                # the provider returned, no day, no place, no coordinate, no origin, no
                # account and no `Settings` field name** is anywhere in this record on
                # account of a forecast, and **no count of dropped days**: §7 refuses
                # that class in terms and §14 defers the consequence rather than
                # glossing it.
                "forecast_serviced": read.forecast_serviced,
                "forecast": None if read.forecast is None else read.forecast.value,
                # ADR-0238 §11's two and ADR-0245 §7's third, on the one event and
                # under the one key: no second audit, no second event key and no new
                # emission point. Counts only, and the destination's recorded trust is
                # deliberately **not** here — "a durable fact about a configured
                # account, readable from the store that holds it, and a per-turn log is
                # not where a deployment's standing configuration is reported".
                #
                # `supplied_narrowed` is the one ADR-0245 §7 adds, because the decision
                # it implements makes `withheld` **fall** on a deployment that changed
                # nothing: one count restores the symmetry between what the corpus gave
                # up and what it can read back. Since ADR-0246 §1 `withheld` is zero on
                # every path and `supplied_narrowed` counts every setter, so this pair
                # is where "the last record-level exclusion is gone" is readable — and
                # §7 forbids deleting the constant one in the same breath as it forbids
                # another. **`calls` is not here at all** (ADR-0247 §6): the quantity
                # itself is removed, which is a different act from a lane dropping a
                # field §7 keeps.
                "supplied": read.supplied,
                "withheld": read.withheld,
                "supplied_narrowed": read.supplied_narrowed,
                "structured_axes": tuple(axis.value for axis in read.structured_axes),
                "structured": None if read.structured is None else read.structured.value,
                "truncated_kinds": tuple(kind.value for kind in read.truncated_kinds),
                "failed": read.failed,
                "failed_after_read_returned": read.failed_after_read_returned,
                # ADR-0251 §7's per-servicing addition: what became of each ask this
                # servicing reached, as **members** and never as the asks themselves
                # — §9's no-copy rule is what shapes the field, exactly as it shapes
                # `refusal`, `disposition` and `structured` above.
                "outcomes": tuple(outcome.value for outcome in read.outcomes),
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
    return value and is the defect #1960 measures. ADR-0275 excludes inspection-only
    episodes from both the named record and its evidence. No rendering decision
    is made from disposition, outcome, or whether evidence is empty. What a reached record
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
        # The one path that reaches no store: every label was malformed, out of range,
        # or named a position this call's supply does not hold (ADR-0226 §3). Nothing
        # was asked of anything, which is ADR-0251 §2's precedence case 1.
        return _HopReach(expansion=(), evidence=(), unresolved=unresolved, read=False)

    wanted: list[str] = []
    seen: set[str] = set()
    for record in found:
        for identifier in (record.id, *record.provenance.evidence):
            if identifier not in seen:
                seen.add(identifier)
                wanted.append(identifier)
    resolved = {
        identifier: record
        for identifier, record in (await store.get_many(wanted)).items()
        if admits_model_eligibility(record, True)
    }
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
    return _HopReach(
        expansion=tuple(expansion), evidence=tuple(cited), unresolved=unresolved, read=True
    )
