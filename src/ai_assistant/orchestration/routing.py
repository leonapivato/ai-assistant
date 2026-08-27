"""The operation-routing stage: one ask, at most one of the hub's own operations.

ADR-0197 §1 puts this **first** in the request pipeline, ahead of intent
understanding. Given the user's utterance and nothing else it either names one
operation of §3's vocabulary together with the one query that operation's argument
is resolved from, or it **declines** — and a declined route is not a failure and is
not reported as one: the pass proceeds through the ordinary pipeline and the outcome
it returns carries no trace of this stage having run.

**Running first is what makes a routed ask cheap and what makes it safe.** Cheap,
because the two stages a routed ask does not need — context assembly and memory
retrieval — are the two most expensive things ``LearningLoop.respond`` does, and a
routed ask skips both along with the planner's model call. Safe, because a router
that has not yet read the store cannot be steered by what is in it: :func:`routing_prompt`
assembles the user's own utterance and a closed enum this repository owns, and
**nothing else**, so ADR-0098 §2's assembler obligation is vacuous by construction
rather than discharged by a delimiter.

**What lives here and what lives in the engine.** This module holds what is about
*routing*: the model call and its envelope and the write-only trail seam
(:class:`RoutingStage`), and the deterministic resolution and performance of a named
operation (:func:`resolve`, :func:`perform`). The engine drives them, because the two
resources a route holds — ADR-0197 §7's ceiling slot and §9's reserved ``route_id`` —
are taken in the engine's own park table under the engine's own lock, and a second
holder of either would be a second answer to the question the ceiling exists to bound.

**The stage adds no member to** ``ModelProvider`` **and no Protocol for itself**
(ADR-0197 §2). ``complete`` is the whole of what it consumes at the model seam, and
:class:`~ai_assistant.core.protocols.RoutingRecorder` is the whole of what it consumes
at the trail seam.
:class:`RoutedOperations` is not a contract: it is this module's own annotation for
the engine's own operations, which is what keeps ``resolve`` and ``perform``
testable without an engine and what makes ADR-0197 §2's third clause — "it performs
the routed operation by calling the engine's own implementation of the named
operation" — a type rather than a promise. The two contracts this decision mints are
``RoutingRecorder`` and ``RoutingTrail``, and the stage holds the write-only half of
that pair and nothing more.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, assert_never

import structlog

from ai_assistant.core.errors import ModelError, RoutingTrailError
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    MemoryKind,
    Message,
    Role,
    RoutableOperation,
    RouteOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.protocols import ModelProvider, RoutingRecorder
    from ai_assistant.core.types import (
        Belief,
        PermissionDecision,
        Question,
        RecordedInvocation,
        RoutedListing,
        RoutedOperationRecord,
        SourceGrant,
        SourceReadRecord,
        SpendTotal,
    )

_log = structlog.get_logger(__name__)

#: The envelope key naming the operation on a **route** envelope (ADR-0197 §4).
_OPERATION = "operation"

#: The envelope key naming the query a confirm-owed operation's argument is resolved
#: from. Absent where §5's lookup needs none.
_QUERY = "query"

#: The marker a **decline** envelope carries, whose value must be the JSON boolean
#: ``true`` and nothing else (ADR-0197 §4).
_NO_OPERATION = "no_operation"

#: Which record type's text field a query is matched against, per confirm-owed
#: operation. Total over the confirm-owed half of §3's vocabulary; a member added
#: under the widening rule states its own.
_MATCH_ON: Final[Mapping[RoutableOperation, str]] = {
    RoutableOperation.FORGET: "content",
    RoutableOperation.FORGET_QUESTION: "content",
    RoutableOperation.REVOKE: "source",
}

#: ADR-0197 §5's mapping from a confirm-owed operation to the **scalar identity** read
#: off the resolved candidate — "not the record itself, which no confirm-owed member's
#: signature accepts". Total over §3's confirm-owed members and exactly as §5 states
#: it: ``forget`` takes ``Belief.id``, ``forget_question`` takes ``Question.id``,
#: ``revoke`` takes ``SourceGrant.source``. A member added under §3's widening rule
#: states its own mapping in the ADR that adds it, and condition (iii) is not satisfied
#: without one.
ARGUMENT_OF: Final[Mapping[RoutableOperation, str]] = {
    RoutableOperation.FORGET: "id",
    RoutableOperation.FORGET_QUESTION: "id",
    RoutableOperation.REVOKE: "source",
}

#: Which kinds a routed ``forget``'s lookup enumerates (ADR-0201 §1): every
#: :class:`~ai_assistant.core.types.MemoryKind` **except** ``EPISODIC``. An episodic
#: record is never a candidate of that lookup, never its display subject, never the
#: record whose identity becomes the facade call's argument, and never an entry in an
#: ``AMBIGUOUS`` or ``AMBIGUOUS_TRUNCATED`` listing.
#:
#: **Why the lookup reads less than** ``forget`` **destroys.** ADR-0074 §3 captures
#: every exchange as an episode whose ``content`` quotes the user's own utterance, so
#: the record of *asking* to forget something matches the words that asked for it: a
#: repeat ask reached ``AMBIGUOUS`` over the belief and the episodes of every earlier
#: ask, and the remedy that rendering invites — say it again, differently — captured
#: another one, so the candidate set grew on every attempt and the routed door closed
#: behind the user (#1637). Excluding the kind closes that loop rather than its first
#: turn: every wording that names the belief is a subset of the sentence each earlier
#: ask quoted, so the episodes reached are not confined to this conversation.
#:
#: **Nothing about what** ``forget`` **destroys moves** (ADR-0201 §2). The exclusion
#: sits upstream of the facade call, in the resolution step the typed door does not
#: have because it is handed an id; ``AssistantEngine.forget`` still relays
#: ``MemoryStore.delete`` and still destroys an episodic record whose id it is given.
#: The lookup already read less than ``forget`` destroys — retired and expired records
#: are unnameable by phrase and destroyable by id (ADR-0073 §3, ADR-0045 §6) — and this
#: decides where that line falls rather than drawing it for the first time.
#:
#: **Derived rather than spelled out**, so a fifth ``MemoryKind`` is a candidate by
#: default rather than silently omitted by a list nobody updated. That is
#: ``interfaces.cli._DEFAULT_BELIEF_KINDS``' own rule and its own reason (ADR-0074 §6),
#: applied one seam over.
#:
#: Passed as the ``kinds`` argument of the ``MemoryStore.list_beliefs`` read behind
#: :meth:`RoutedOperations.beliefs`, so the store applies it **before** the page cut
#: (ADR-0073 §2) and an excluded record is never read into ``orchestration``, never
#: projected into a :class:`~ai_assistant.core.types.Belief`, and never discarded after
#: a page has come back (ADR-0201 §3).
FORGET_LOOKUP_KINDS: Final[tuple[MemoryKind, ...]] = tuple(
    kind for kind in MemoryKind if kind is not MemoryKind.EPISODIC
)

#: The system turn. It renders the closed vocabulary and the two legal envelope
#: shapes, and it renders **no** retrieved memory, context facet, belief, trail row,
#: tool identifier or description, and no result of any operation (ADR-0197 §4). The
#: descriptions are this repository's own words about its own operations, fixed at
#: import and identical on every turn.
_SYSTEM_PROMPT = """\
You are the operation-routing stage of an AI assistant. Decide whether the user is \
asking the assistant to perform one of its OWN operations on the user's own data, \
then reply with exactly one of the two JSON objects below — a single JSON object and \
nothing else, no prose, no code fence.

The operations you may name, and nothing else:

  questions            — list the questions the assistant is waiting for an answer to
  recent_reads         — list what the assistant has read from the user's sources
  recent_invocations   — list what the assistant has done on an authorisation
  recent_decisions     — list what the permission layer has ruled
  standing_grants      — list which sources the user currently authorises
  spend_totals         — report what the assistant's actions have cost
  forget               — destroy one thing the assistant believes about the user
  revoke               — withdraw the user's grant on one source
  forget_question      — destroy one question the assistant is waiting on

Where the user is asking for one of those, reply with a ROUTE:

  {"operation": "<one name from the list above>", "query": "<what they named>"}

`query` is the user's own words for WHICH belief, source or question they mean, \
copied from their sentence: the words that NAME the thing, without the words that ask \
for the operation and without the connective that joined them — "forget that I like \
jazz" gives "I like jazz". Include it for forget, revoke and forget_question, and \
omit it for the six listing operations, which take no subject. Never invent an \
identifier; never guess a subject the user did not name.

Where the user is asking for anything else at all — a question about the world, a \
task, a conversation, or an operation not on the list — reply with a DECLINE:

  {"no_operation": true}

Declining is the ordinary answer and costs nothing: the assistant handles the \
request by its usual route.\
"""


def routing_prompt(utterance: str) -> tuple[Message, ...]:
    """Assemble the routing conversation for ``utterance`` (ADR-0197 §4).

    Two messages: this module's own fixed system turn, and the user's utterance
    verbatim. **Nothing else** — which is a structural answer to ADR-0098 §2 rather
    than an escaping one. That section binds a prompt assembler to present every span
    of external content as third-party data, non-forgeably; this prompt assembles no
    external content at all, so there is no span for an ingested instruction to occupy
    and the obligation is vacuous by construction. ADR-0098 §2's "the marking is
    derived from data the system holds … and never from inspecting the text" is
    satisfied trivially: nothing is marked because nothing external is present.

    What that does *not* claim: ingested content can still reach the utterance, by the
    ordinary route of a user reading something and repeating it. That is a person
    choosing to say a sentence, which is exactly what ADR-0098 §2 calls the user's own
    words, and ADR-0197 §7's confirmation is what stands between a sentence and a
    destructive act.

    A module-level function rather than a method, so ADR-0197 §12's byte-identity case
    can assemble the prompt for an utterance with no store, no engine and no model in
    the picture — which is what makes that case pin the clause structurally rather
    than by inspection.

    Args:
        utterance: What the user said, passed through untouched.

    Returns:
        The system turn and the user's own words, in that order.
    """
    return (
        Message(role=Role.SYSTEM, content=_SYSTEM_PROMPT),
        Message(role=Role.USER, content=utterance),
    )


@dataclass(frozen=True, slots=True)
class RoutedRoute:
    """One route the model named — an operation, and the query its argument comes from.

    Attributes:
        operation: The member of §3's closed vocabulary the utterance was routed to.
        query: The user's own words for *which* belief, source or question they meant,
            or ``None`` on a read-only member, which takes no subject. It is a
            **query** and never an identifier and never an argument value: ADR-0197 §5
            resolves the argument from it by deterministic local code reading the store
            the operation itself reads.
    """

    operation: RoutableOperation
    query: str | None


class RoutingStage:
    """Name one of the hub's own operations from one sentence, or decline (§1, §4).

    Reaches the model through the injected
    :class:`~ai_assistant.core.protocols.ModelProvider` and originates **exactly one**
    ``complete()`` call per pass. It does not loop, does not call again on a failure
    that call returns, and takes no repair round. What the injected provider does below
    that seam is not this stage's to constrain (ADR-0011 §2).

    **It holds the write-only half of §9's trail, and holds nothing wider** (ADR-0197
    §9): a :class:`~ai_assistant.core.protocols.RoutingRecorder` and never a
    :class:`~ai_assistant.core.protocols.RoutingTrail`. What that forecloses is worse
    than a cursor — a stage handed the whole trail could call ``clear`` and **erase the
    record of its own decisions** — and it is a ``mypy --strict`` failure rather than a
    review note, which is ADR-0185 §4's own standard on ADR-0097 §3's argument.

    **Everything that is not one of the two legal envelope shapes is a decline**, and
    that default is the right one rather than the lazy one. The three ways this stage
    can fail are: the model declined deliberately, the model produced something
    unusable, and the model call failed. All three mean the same thing operationally —
    *this pass has no route* — and all three have the same correct behaviour, which is
    the pipeline that ran yesterday. So this raises nothing to the caller, degrades no
    turn, sets no flag on ``TurnOutcome``, and takes no repair round.
    """

    def __init__(self, *, model: ModelProvider, recorder: RoutingRecorder) -> None:
        """Wire the stage to the model seam it routes through and the trail it writes.

        **One parameter, and no route of its own.** ADR-0197 §11 leaves "which model
        answers" undecided and §2 gives the stage no setting, so the seam it is handed
        decides — and ``complete`` is called with **no** ``model=`` override, for the
        reason ``ComposingStage`` gives: ADR-0013 §4 rules that "an explicit ``model=``
        override disables routing", so a route knob here would let the routing path
        silently leave the deployment's own fallback chain while planning stayed on it.

        Args:
            model: The injected ``ModelProvider``, supplied explicitly by the
                composition root (ADR-0028 §4). ``Engine.__init__`` receives no
                ``ModelProvider`` of its own, and reaching a concrete subsystem's
                internals to find one is what golden rule 1 forbids.
            recorder: The injected ``RoutingRecorder`` (ADR-0197 §9). **Required with no
                default**, so a composition that omits it does not type-check —
                ADR-0185 §5's posture on ADR-0097 §5's pattern, and the reason a
                deployment cannot end up routing without recording. Structural typing
                means the one ``permissions/`` store satisfies it and ``RoutingTrail``
                alike, so the composition root passes one object here and to a future
                read surface; what this stage cannot do is *name* ``recent``, ``export``
                or ``clear``.
        """
        self._model = model
        self._recorder = recorder

    async def route(self, utterance: str) -> RoutedRoute | None:
        """Name one operation and its query, or ``None`` to decline (ADR-0197 §4).

        Args:
            utterance: What the user said, passed through untouched.

        Returns:
            The route, or ``None`` where this pass has none — which is every failure
            as well as every deliberate decline.
        """
        try:
            answer = await self._model.complete(routing_prompt(utterance))
        except ModelError:
            # ADR-0011 §1's taxonomy, whole: the model is down, the route is
            # exhausted, the request was refused. Letting this propagate would fail an
            # ordinary ask that routing was never meant to touch (ADR-0197 §4).
            _log.warning("routing_declined", reason="model_error", exc_info=True)
            return None
        return _route_of(answer.content)

    async def record(self, record: RoutedOperationRecord) -> bool:
        """Append one row of §9's trail, and say whether the act it precedes may proceed.

        **The row is written before the act it precedes, always** (ADR-0197 §9), and this
        is the seam that write goes through — which is why the recorder is held here
        rather than by the engine: §9 puts the capability on the stage, so what the stage
        can reach is ``record`` and nothing else.

        The row itself is built by the caller: its ``id`` is minted from the id factory
        the engine already holds injected, and its ``decided_at`` comes from the injected
        clock (ADR-0009). The store mints nothing and reads no clock.

        **A refusal is classified here rather than raised**, because §9 gives the caller
        exactly one thing to do with it: not proceed. The pass ends in
        ``RouteOutcome.UNRECORDED``, the operation is not called, no park is registered
        and no token is minted — for a read-only member as much as for a confirm-owed
        one, which is one ordering and one failure mode rather than two.

        Args:
            record: The row to append.

        Returns:
            Whether the row landed. ``False`` is §9's refuse-to-act.
        """
        try:
            await self._recorder.record(record)
        except RoutingTrailError:
            _log.warning(
                "route_unrecorded",
                operation=record.operation.value,
                approval=record.approval.value,
                exc_info=True,
            )
            return False
        return True


def _route_of(content: str) -> RoutedRoute | None:
    """Read a route out of the model's reply, or decline (ADR-0197 §4).

    The envelope has two legal shapes and nothing else is one. A **route envelope**
    carries an ``operation`` key whose value is the ``str`` value of a
    :class:`~ai_assistant.core.types.RoutableOperation` member, and a ``query`` key
    whose value is a string with at least one non-whitespace character where §5's
    lookup needs one and which is absent otherwise. A **decline envelope** carries a
    ``no_operation`` key whose value is the JSON boolean ``true``.

    **An ``operation`` value that is not a member is not an error the user sees**: it
    is unclassified output, and the pass declines to route. The vocabulary is closed at
    the boundary, and no near-match, prefix, alias or case-fold resolves an unknown
    value onto a member — which is the opposite of ADR-0053's alias layer, and
    deliberately so: that layer exists for the planner's *open* capability vocabulary.

    Args:
        content: The model's reply, verbatim.

    Returns:
        The route, or ``None`` on a decline and on every unclassified reply alike.
    """
    try:
        envelope = json.loads(content)
    except ValueError, RecursionError:
        # ``RecursionError`` beside ``ValueError`` because the parser raises it rather
        # than a decode error on a deeply nested reply — thousands of nested arrays are
        # syntactically valid JSON and structurally unusable — and ADR-0197 §4 admits no
        # third outcome: "anything that is not one of the two legal envelope shapes … is
        # a **decline**. The routing stage raises nothing to the caller." Letting it
        # propagate would fail an ordinary ask that routing was never meant to touch,
        # which is the failure §4's decline-everything default exists to prevent. The
        # ``try`` wraps the parse alone, so no recursion failure from anywhere else is
        # swallowed here.
        _log.warning("routing_declined", reason="unparseable_reply")
        return None
    if not isinstance(envelope, dict):
        _log.warning("routing_declined", reason="not_an_envelope")
        return None
    if _declines(envelope):
        return None
    named = envelope.get(_OPERATION)
    if not isinstance(named, str):
        _log.warning("routing_declined", reason="no_operation_named")
        return None
    try:
        operation = RoutableOperation(named)
    except ValueError:
        # The vocabulary is closed at the boundary (ADR-0197 §4). The value is logged
        # by *class* rather than verbatim: it is model output, and a reply naming a
        # near-match is exactly the case a lane would otherwise be tempted to resolve.
        _log.warning("routing_declined", reason="unknown_operation")
        return None
    return _with_query(envelope, operation)


def _declines(envelope: dict[str, object]) -> bool:
    """Whether ``envelope`` carries the decline marker (ADR-0197 §4).

    The marker is the JSON boolean ``true`` **and nothing else**: ``1``, ``1.0``,
    ``"true"``, ``"yes"`` and every other truthy value are not it. The identity check is
    what makes that so — Python's ``bool`` is a subclass of ``int``, so ``True == 1``
    and ``True == 1.0``, and an equality test would silently read ``{"no_operation": 1}``
    as a decline. That is ADR-0176 §1's own reasoning, restated here because §4 requires
    the marker tested by type as well as by value.

    A decline is read **before** the operation, unlike the planner's marker, and the
    asymmetry follows from the shapes: there the marker is consulted only where
    ``steps`` is empty, because a non-empty ``steps`` is unambiguously a plan. Here an
    envelope carrying both keys is asserting two different things at once, and the
    conservative reading of "route nothing" is the one that cannot destroy anything.

    Args:
        envelope: The decoded object to test.

    Returns:
        Whether the object positively asserts that no operation is wanted.
    """
    return envelope.get(_NO_OPERATION) is True


def _with_query(envelope: dict[str, object], operation: RoutableOperation) -> RoutedRoute | None:
    """Pair ``operation`` with the query §5 needs for it, or decline (ADR-0197 §4).

    A confirm-owed member needs a ``query`` whose value is a string with at least one
    non-whitespace character; a missing or blank one is not a legal envelope and the
    pass declines rather than resolving an argument from nothing. A read-only member
    takes none, and one supplied anyway is ignored rather than refused: §5 performs
    such an operation "exactly as the promoted surface declares it", so there is
    nothing for a query to change and a refusal would turn a harmless extra key into a
    lost route.

    Args:
        envelope: The decoded route envelope.
        operation: The member it named.

    Returns:
        The route, or ``None`` where a needed query is missing or blank.
    """
    if not operation.confirm_owed:
        return RoutedRoute(operation=operation, query=None)
    query = envelope.get(_QUERY)
    if not isinstance(query, str) or not query.strip():
        _log.warning("routing_declined", reason="no_query", operation=operation.value)
        return None
    return RoutedRoute(operation=operation, query=query)


class RoutedOperations(Protocol):
    """The engine's own operations a routed pass reaches (ADR-0197 §2, §5).

    **Not a contract, and deliberately not in** ``core/protocols.py``. ADR-0197 §2 is
    explicit that the stage "adds no Protocol for itself"; this is one module's
    annotation for the object the engine hands it, which is the engine's own façade
    seen through the nine operations §3 admits plus the one listing §5's ``forget``
    lookup reads. Structural typing means the engine satisfies it without naming it,
    and what the annotation buys is that :func:`resolve` and :func:`perform` are
    testable against a double rather than only against a whole engine.

    **Every member is the engine's own implementation**, which is ADR-0197 §2's third
    clause and the reason it is stated rather than assumed: "perform the operation"
    could mean *call the façade method* or *do what the façade method does*, and only
    the first keeps one implementation of ``forget``. The second would put a second
    ``MemoryStore.delete`` call site behind a different set of preconditions, which is
    how two doors to one operation stop behaving the same way.

    :meth:`beliefs` is the one member that is not a routable operation. ``beliefs`` is
    deliberately **outside** §3's vocabulary — "what do you know about me?" is
    milestone 17's ruled exit test and is answered by the composing stage from the
    memories the turn retrieved — but §5's lookup for a routed ``forget`` still has to
    read the store that operation reads, and its candidates are
    :class:`~ai_assistant.core.types.Belief` records because that is the arm §8 gives
    the operation. The promoted ``AssistantEngine.beliefs`` answers
    :class:`~ai_assistant.core.types.BeliefSummary` rows and so cannot serve it.

    **It reads that store with** :data:`FORGET_LOOKUP_KINDS`, not whole (ADR-0201 §1).
    The store is the one ``forget`` reads, exactly as §5 said; what ADR-0201 replaces is
    the kinds enumerated from it — every ``MemoryKind`` but ``EPISODIC``, because the
    episode of an ask quotes the words that asked and so matched the query that would
    name the belief.
    """

    async def beliefs(self, *, limit: int, offset: int) -> tuple[Belief, ...]:
        """Enumerate live beliefs as §8's ``forget`` arm, for §5's lookup only."""
        ...

    async def questions(self, *, limit: int, offset: int) -> tuple[Question, ...]:
        """List the deferred questions awaiting an answer."""
        ...

    async def recent_reads(self, *, limit: int) -> tuple[SourceReadRecord, ...]:
        """List what this system read from a source, newest-recorded first."""
        ...

    async def recent_invocations(self, *, limit: int) -> tuple[RecordedInvocation, ...]:
        """List what this system did on an authorisation, newest first."""
        ...

    async def recent_decisions(self, *, limit: int) -> tuple[PermissionDecision, ...]:
        """List what the permission layer ruled, newest first."""
        ...

    async def standing_grants(self) -> tuple[SourceGrant, ...]:
        """List every source grant the user currently authorises. Unpaged."""
        ...

    async def spend_totals(self) -> tuple[SpendTotal, ...]:
        """Report what the world has cost in each period. Unpaged."""
        ...

    async def forget(self, record_id: str) -> bool:
        """Destroy the belief ``record_id`` names."""
        ...

    async def revoke(self, source: str) -> SourceGrant | None:
        """Withdraw the live grant on ``source``, or report that there was none."""
        ...

    async def forget_question(self, question_id: str) -> bool:
        """Destroy the deferred question ``question_id`` names."""
        ...


@dataclass(frozen=True, slots=True)
class Resolved:
    """§5's one-candidate case: what the card shows, and what the façade is called with.

    Attributes:
        subject: The **display subject** — the typed record, held as a one-element
            listing, which is what §7's card renders. A person judges the belief and
            not its id.
        argument: The **scalar identity** read off that record by :data:`ARGUMENT_OF`,
            which is what the façade call is made with, what the park retains and what
            §9's row records as ``subject``.
    """

    subject: RoutedListing
    argument: str


@dataclass(frozen=True, slots=True)
class Unresolved:
    """§5's other two cases: nothing found, or more than one thing found.

    Attributes:
        outcome: ``NOT_FOUND``, ``AMBIGUOUS`` or ``AMBIGUOUS_TRUNCATED``. Nothing is
            performed and nothing is confirmed on any of the three, and none of them
            writes a row (§9): the route decided nothing to do.
        listing: The candidates on the two ambiguous outcomes, bounded by
            :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`, and ``None`` on
            ``NOT_FOUND``. No surface renders fewer candidates than this carries or
            summarises in place of them.
    """

    outcome: RouteOutcome
    listing: RoutedListing | None


async def resolve(
    operations: RoutedOperations, operation: RoutableOperation, query: str
) -> Resolved | Unresolved:
    """Resolve ``operation``'s one argument from ``query`` (ADR-0197 §5).

    **A lookup, not a generation**: every candidate returned is a record that exists,
    read from the store the operation itself reads. Nothing is ranked, nothing is
    scored, and no second model call is made — "no clause of this ADR permits choosing
    among candidates by rank, recency, score, best match, or a second model call.
    Ambiguity ends the route."

    **For** ``forget`` **the store is read by kind** (ADR-0201 §1): the candidates are
    live beliefs of every ``MemoryKind`` but ``EPISODIC``, per :data:`FORGET_LOOKUP_KINDS`.
    That is not a rank and does not choose among candidates — it decides what the
    question ranges over, once and in the open, before the lookup runs. A query naming
    only episodic records therefore reaches ``NOT_FOUND``, §5's existing arm applied to a
    lookup that now finds nothing, and no surface distinguishes that from a query that
    matched nothing at all (ADR-0201 §5).

    **What the query is matched against.** Every **distinctive** term of the query — its
    words, less the run of framing it opens on and less a reference naming this
    operation's own kind of record (:func:`_wanted`) — must be one of the record's own
    words, give or take an inflection (:func:`_names`). Nothing from the body of the
    query is ever dropped, so every word the user said after the opening still has to be
    in the record. Term-wise rather than whole-span, because the router
    is asked for the user's own words and copies the sentence's connective with them, so
    ``that I drive a green estate car`` was never a contiguous substring of the belief
    ``I drive a green estate car`` and a routed forget of a belief that plainly existed
    ended in ``NOT_FOUND`` (#1647).

    The rule stays a lookup: total, order-independent, and free of rank, score, best
    match and any second model call, so the same query and store give the same candidates
    every run. It is a **wider** lookup than a substring match and not a looser one —
    every word the user said still has to be in the record, which is what keeps a negated
    query off the belief asserting the opposite — and where it names more than one record
    the route ends in ``AMBIGUOUS`` over a listing the user reads rather than choosing
    among them. Where it names one, §7's card renders that record before anything of the
    user's is destroyed, which is the guard a widened match leans on and the reason it
    may lean on it.

    **The bound and its disclosure ride the outcome rather than a count.** A lookup
    resolving to more than one candidate but no more than
    :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE` ends in ``AMBIGUOUS``; one that
    would **exceed** the bound ends in ``AMBIGUOUS_TRUNCATED`` over a listing of
    exactly the bound. The two are otherwise identical, and that eighth member exists
    because §6 gives the composing stage no count — so a single ``AMBIGUOUS`` could not
    distinguish two candidates from a hundred, and the alternative is handing the
    composer a number, which is a count of the user's own records reaching a prompt.

    **The scan is the store's own size and takes no setting of its own** (§5). It reads
    the operation's own listing a page at a time and stops the moment one more than the
    bound has matched, so the cost is bounded by the store rather than by anything this
    module invented — and a routed act is a human-paced, occasional thing.

    Args:
        operations: The engine's own operations, injected.
        operation: The confirm-owed member being resolved for.
        query: The user's own words for which record they meant.

    Returns:
        The one candidate and its scalar argument, or which of §5's other two cases the
        lookup reached.
    """
    matches = await _candidates(operations, operation, query)
    if not matches:
        return Unresolved(outcome=RouteOutcome.NOT_FOUND, listing=None)
    if len(matches) == 1:
        subject = matches[0]
        return Resolved(
            subject=(subject,),  # type: ignore[arg-type] # the arm is fixed by `operation` (§8)
            argument=str(getattr(subject, ARGUMENT_OF[operation])),
        )
    outcome = (
        RouteOutcome.AMBIGUOUS_TRUNCATED
        if len(matches) > DEFAULT_PAGE_SIZE
        else RouteOutcome.AMBIGUOUS
    )
    return Unresolved(
        outcome=outcome,
        listing=tuple(matches[:DEFAULT_PAGE_SIZE]),  # type: ignore[arg-type] # as above
    )


async def _candidates(
    operations: RoutedOperations, operation: RoutableOperation, query: str
) -> list[Belief] | list[Question] | list[SourceGrant]:
    """Every record ``query`` names, up to one more than §5's bound.

    One more, because the bound's two sides are told apart by whether the lookup would
    *exceed* it: ``DEFAULT_PAGE_SIZE`` matches is ``AMBIGUOUS`` and one more is
    ``AMBIGUOUS_TRUNCATED``, so a scan that stopped at the bound could not tell them
    apart.
    """
    field = _MATCH_ON[operation]
    wanted = _wanted(query, operation)
    ceiling = DEFAULT_PAGE_SIZE + 1
    if not wanted:
        # A query that is nothing but framing names no record, and the store is not read
        # at all. The alternative is worse than useless: every record's terms contain the
        # empty set, so "forget the thing" would resolve to whatever the store happens to
        # hold one of and park a confirmation on a record the user never named.
        return []
    if operation is RoutableOperation.REVOKE:
        # `standing_grants` is complete-or-refused and never truncated (ADR-0139 §2),
        # so there is nothing to page through and its own refusal is what a routed pass
        # reports as `FAILED`.
        grants = await operations.standing_grants()
        return [one for one in grants if _names(wanted, getattr(one, field))][:ceiling]
    if operation is RoutableOperation.FORGET:
        return await _paged(operations.beliefs, field=field, wanted=wanted, ceiling=ceiling)
    if operation is RoutableOperation.FORGET_QUESTION:
        return await _paged(operations.questions, field=field, wanted=wanted, ceiling=ceiling)
    # Unreachable: `_MATCH_ON` is total over the confirm-owed members, and a read-only
    # operation resolves no argument at all (§5). Stated as an assertion rather than
    # left to fall off the end, so a member added under §3's widening rule that forgot
    # its mapping fails here rather than silently resolving to nothing.
    raise AssertionError(_UNMAPPED.format(operation=operation.value))


async def _paged[T](
    page: _Paged[T], *, field: str, wanted: frozenset[str], ceiling: int
) -> list[T]:
    """Walk ``page`` a page at a time, collecting matches until ``ceiling`` of them.

    The offset advances by what the page **asked for** rather than by what came back,
    which is what makes the walk terminate: a store answering a short page is at its
    end, and one answering a full page has more.
    """
    found: list[T] = []
    offset = 0
    while len(found) < ceiling:
        rows = await page(limit=DEFAULT_PAGE_SIZE, offset=offset)
        found.extend(one for one in rows if _names(wanted, str(getattr(one, field))))
        if len(rows) < DEFAULT_PAGE_SIZE:
            break
        offset += DEFAULT_PAGE_SIZE
    return found[:ceiling]


class _Paged[T](Protocol):
    """One of the engine's paged listings, as :func:`_paged` walks it."""

    async def __call__(self, *, limit: int, offset: int) -> tuple[T, ...]:
        """Return one page."""
        ...


def _terms(value: str) -> tuple[str, ...]:
    """``value`` as case-folded words: runs of letters and digits, apostrophes kept.

    Punctuation, underscores and whitespace are separators, so ``did the user move?``
    and ``google_calendar`` are read as the words a person would say them as. An
    apostrophe is **not** a separator, and that is load-bearing rather than tidy:
    splitting ``can't`` into ``can`` and ``t`` leaves two fragments that look like
    framing, and a query the user negated would name the belief asserting the opposite.
    A contraction is one word here, so ``can't`` is a word ``I can drive`` does not have.
    The curly apostrophe is folded onto the straight one so a keyboard cannot decide
    whether two words are the same word.

    This normalises the *comparison* and never the stored value: what the card renders
    is the record, and what the façade is called with is the identity read off it,
    neither of which passes through here.
    """
    return tuple(_WORD.findall(value.casefold().replace("\u2019", "'")))


def _wanted(query: str, operation: RoutableOperation) -> frozenset[str]:
    """The query's **distinctive** terms: its words, less the run of framing it opens on.

    **Only a leading run is dropped, and never a word from the body of the query.** That
    is the whole rule, and it is what keeps the lookup from quietly widening past what
    the user said: every word after the opening still has to be in the record, so a query
    that negates, quantifies, joins, places, dates or names somebody goes on saying so.
    "That I dislike him" keeps ``him`` and does not name the belief "I dislike her".

    What the opening may hold, and nothing else:

    - **an article**, unconditionally — ``a``, ``an``, ``the`` name nobody;
    - **a demonstrative**, only where what follows it is more framing or nothing at all.
      "That I drive a green estate car" opens on the connective the router copies out of
      the sentence; "that dog bites" opens on a word that says *which dog*, and a rule
      that dropped it would name the belief "this dog bites". A run of them is settled by
      the first word that is neither, in **one pass** rather than by looking ahead from
      each: the query is model-authored, and this walk is not the place a thousand of
      anything becomes a ``RecursionError`` or a quadratic scan;
    - **a first- or second-person pronoun or possessive**, unconditionally — the speaker
      and the assistant, which is what a copied span drags along and what differs between
      a user speaking and a belief stored about them. The third person is absent for the
      reason the demonstrative is conditional: ``her`` says whose dog it is;
    - **a reference to a record**, where the query opens on an article and a kind this
      operation resolves over (:func:`_opens_on_a_record`): "the question you asked me
      about my commute" is six words of reference and then the one word that says which.
      An asking verb inside that reference needs a person in front of it as well
      (:data:`_ASKING`), since a reference is the user or the assistant doing the asking.

    A set rather than a sequence, because the match is on which words the query names and
    never on the order it named them in: the router copies a span out of a sentence, and
    the sentence's word order is the sentence's, not the record's.

    Args:
        query: The user's own words for which record they meant.
        operation: The confirm-owed member being resolved for, which decides which record
            kinds a reference may name.

    Returns:
        The terms every candidate has to carry, empty where the query named nothing but
        framing.
    """
    terms = _terms(query)
    reference = _REFERENCE | _KINDS_OF[operation] if _opens_on_a_record(terms, operation) else None
    start = 0
    held = 0
    while start + held < len(terms):
        at = start + held
        term = terms[at]
        if reference is not None and term in reference:
            start += held + 1
            held = 0
        elif term in _ASKING and reference is not None and at > 0 and terms[at - 1] in _FRAMING:
            # "the question **you asked** me": an asking verb is a reference only in the
            # past tense and only where a person is doing the asking, who in a reference
            # is the user or the assistant. "The memory of me asking Alice" is the act
            # itself, and stripping it would leave the query naming Alice and nothing
            # else.
            start += held + 1
            held = 0
        elif term in _DEMONSTRATIVES:
            # A demonstrative is framing or subject depending on what follows it, so it is
            # *held* rather than decided, and the run of them is settled by the first word
            # that is neither.
            held += 1
        elif term in _FRAMING:
            start += held + 1
            held = 0
        else:
            break
    else:
        # The query ran out inside a run of demonstratives, so there was no subject for
        # them to introduce and they were framing after all.
        start += held
    return frozenset(terms[start:])


def _opens_on_a_record(terms: tuple[str, ...], operation: RoutableOperation) -> bool:
    """Whether ``terms`` opens the way a person names a record: ``the``, then its kind.

    Narrow twice over, because every word of :data:`_REFERENCE` is an ordinary word
    somewhere — ``question`` is a verb in "I question authority" and a subject in "I hate
    the question of taxes", ``about`` asserts a relationship in "I talked about Alice" —
    and a rule that stripped them wherever they turned up would resolve each of those to
    a record asserting something else.

    - **By position**: a reference is how the sentence *opens*, with the article that
      makes it a noun phrase in front of it. Past that, the subject has begun.
    - **By kind**: the kind named has to be one **this operation resolves over**
      (:data:`_KINDS_OF`). "The question of taxes" is a reference when the route is
      ``forget_question`` and is a belief's own content when the route is ``forget``, and
      the operation is the only thing in the pass that knows which.
    """
    return len(terms) > 1 and terms[0] in _ARTICLES and terms[1] in _KINDS_OF[operation]


def _names(wanted: frozenset[str], value: str) -> bool:
    """Whether ``value``'s own words carry **every** distinctive term of the query.

    The rule, whole: each term of ``wanted`` must be one of ``value``'s words, give or
    take one of :data:`_INFLECTIONS`. It is a **lookup, not a generation** (§5) — total,
    order-independent, and free of rank, score, best match and any second model call, so
    the same query and the same store give the same candidates on every run.

    **Term-wise rather than whole-span**, which is what #1647 records: the router is
    asked for the user's own words and copies the connective the sentence carried, so
    ``that I drive a green estate car`` was never a contiguous substring of the belief
    ``I drive a green estate car``, and a routed forget of a belief that plainly exists
    ended in ``NOT_FOUND``. Requiring each word instead of one span costs nothing that
    matters here and makes the framing a copied span drags along harmless.

    **A word, and not a fragment of one.** ``car`` does not name ``carpet``, and the
    tolerance stops at the closed suffix list rather than at "appears inside": a store
    holding one belief has no second candidate to be ambiguous against, so a term that
    matched part of an unrelated word would resolve to it alone and park a destructive
    confirmation on it. Degrading toward ``AMBIGUOUS`` is only a safety net where a
    second record exists to be ambiguous *with*, so it is not one, and the match is
    narrow where it can be and generous only where a person would say the two words are
    the same word.

    **Widening the match widens what may be confirmed, and that is where the remaining
    guard is.** A one-candidate resolution parks (§7) on a card carrying the typed
    record, and ADR-0073 §5's show-then-confirm binds a routed ``forget`` whole — so the
    user reads the record this resolved to before anything is destroyed, and a match this
    rule admits that the user did not mean is declined rather than performed.
    """
    return all(any(_same_word(term, word) for word in _terms(value)) for term in wanted)


def _same_word(term: str, word: str) -> bool:
    """Whether ``term`` and ``word`` are the same word, give or take one inflection.

    Equality, or one is the other followed by an ending of :data:`_INFLECTIONS` — which
    keeps ``like`` naming ``likes``, ``sail`` naming ``sailing`` and ``commute`` naming
    ``commutes`` while ``car`` names nothing of ``carpet``. Two guards narrow it further,
    and both exist because the pair this gets wrong ends in a confirmation card naming a
    record the user did not mean:

    - **the stem is at least :data:`_STEM` characters**, so ``ad`` does not name the
      source ``add`` and no two-letter fragment inflects into anything. A
      ``SourceGrant.source`` is an identifier rather than English, and short identifiers
      are exactly where a suffix rule invents relationships;
    - **a bare** ``d`` **needs a stem ending in** ``e`` (``move`` → ``moved``), which is
      the only shape it is an inflection of.

    **The possessive is not one of the endings**, though it looks like the same kind of
    thing: ``alex`` and ``alex's`` are not the same word but the second and a relation to
    it, so "I like Alex" would name the belief "I like Alex's dog". A query saying
    ``wife's`` still finds a record saying ``wife's`` — :func:`_terms` keeps the
    apostrophe inside the word — and one saying ``wife`` no longer reaches whatever the
    wife has.

    Deliberately not a stemmer: a stemmer is a dependency, a vocabulary and a set of
    surprises, and the tolerance this needs is the difference between the person a user
    speaks in and the person a stored belief is written in. What it does not reach —
    ``ran`` for ``run``, ``feet`` for ``foot``, ``commuting`` for ``commute`` — ends in
    ``NOT_FOUND``, the honest answer, and the user says the record's own word instead.

    **What no rule short of a dictionary closes**, stated rather than implied: a pair
    like ``bus`` and ``buss`` is spelled exactly as ``cat`` and ``cats`` are, so a rule
    that admits the plural admits the pair. Distinguishing them needs a lexicon, which
    is a dependency and a vocabulary this module would then own; what stands in its
    place is §7's confirmation, which renders the typed record before anything of the
    user's is destroyed.
    """
    if term == word:
        return True
    longer, shorter = (word, term) if len(word) > len(term) else (term, word)
    if len(shorter) < _STEM:
        return False
    return any(
        longer == shorter + ending
        for ending in _INFLECTIONS
        if ending != "d" or shorter.endswith("e")
    )


#: The shortest word :func:`_same_word` will inflect. Below it a suffix rule is inventing
#: a relationship rather than recognising one — ``ad`` and ``add`` are not the same word,
#: and a source identifier is not English.
_STEM: Final = 3

_INFLECTIONS: Final = ("s", "es", "d", "ed", "ing")

#: One word of a record or a query: a run of letters or digits, with apostrophes kept
#: **inside** it so a contraction stays one word (``can't``, ``user's``). Underscores are
#: separators rather than word characters, so a source named ``google_calendar`` is two
#: words and a query naming ``calendar`` reaches it.
_WORD: Final = re.compile(r"[^\W_]+(?:'[^\W_]+)*")

#: The demonstratives, which open either a connective the router copied ("**that** I
#: drive a green estate car") or a subject ("**that** dog bites"). Which one they opened
#: is read off what follows them (:func:`_wanted`), never off the word alone.
_DEMONSTRATIVES: Final[frozenset[str]] = frozenset(("this", "that", "these", "those"))

#: What can stand in front of a record kind and make it a reference to a record
#: (:func:`_opens_on_a_record`): an article, or a demonstrative.
_ARTICLES: Final[frozenset[str]] = frozenset(("a", "an", "the")) | _DEMONSTRATIVES

#: The words a query **opens** with as framing rather than as subject, stripped from the
#: query side of the comparison and from that side only (#1647).
#:
#: Two classes, and each is here because one of #1647's own arms needs it: the articles,
#: which name nobody, and the **first- and second-person** pronouns and possessives, for
#: "stop reading **my** calendar" against a grant whose source is ``calendar``. Those two
#: persons are the speaker and the assistant — what a copied span drags along, and what
#: differs between a user speaking and a belief stored about them. The third person is
#: **not** here: ``her`` in "her dog likes cats" says whose dog it is, and a query that
#: lost it would name the belief "my dog likes cats".
#:
#: **They are stripped from the opening and nowhere else** (:func:`_wanted`), which is
#: what stops this set from quietly widening the lookup past what the user said. A word
#: of it in the body of a query goes on constraining the match like any other — "that I
#: dislike him" keeps its ``him`` — so the set can be read as what a copied span opens
#: with rather than as a list of words that never matter. Nothing else is dropped
#: anywhere: not a negation (``no``, and every ``n't`` form, which is why :func:`_terms`
#: keeps a contraction whole), not a quantifier, not a conjunction, not a preposition,
#: not a copula, auxiliary or modal, and not a verb of any kind. Each of those is
#: something a record asserts, and a query that lost one could name the record saying the
#: opposite of it: "I have no pets" naming "I have pets", "tea or coffee" naming "tea and
#: coffee", "I work for Acme" naming "I work with Acme", "I am a doctor" naming "I was a
#: doctor".
#:
#: The record side keeps all of its words, which is what makes the asymmetry safe: a
#: record whose own words are ``the`` and ``my`` is still matched by a query naming them,
#: because the match is tested against everything the record says.
_FRAMING: Final[frozenset[str]] = frozenset(
    word
    for group in (
        # articles
        "a an the",
        # the first and second persons, and their possessives
        "i me my mine myself we us our ours you your yours",
    )
    for word in group.split()
)

#: The record kinds a **reference** may name, per confirm-owed operation — the kinds that
#: operation's lookup resolves over, and no others (:func:`_opens_on_a_record`).
#:
#: Per operation rather than one list, twice over. A reference's *opening* has to name a
#: kind this route resolves over: "the question of taxes" names a deferred question when
#: the route is ``forget_question`` and is something the user believes when the route is
#: ``forget``, and a route over beliefs that stripped ``question`` would hand that query
#: to the belief "I hate taxes". And the reference's *vocabulary* is this entry alone
#: (:func:`_wanted`), never the union: "the question about grants" is a question
#: whose subject is grants, and a ``grants`` borrowed from ``revoke``'s kinds would strip
#: the query down to nothing and read no store at all.
_KINDS_OF: Final[Mapping[RoutableOperation, frozenset[str]]] = {
    RoutableOperation.FORGET: frozenset(
        (
            "belief",
            "beliefs",
            "fact",
            "facts",
            "memory",
            "memories",
            "note",
            "notes",
            "record",
            "records",
            "thing",
            "things",
        )
    ),
    RoutableOperation.FORGET_QUESTION: frozenset(("question", "questions", "thing", "things")),
    RoutableOperation.REVOKE: frozenset(
        ("source", "sources", "grant", "grants", "thing", "things")
    ),
}

#: The words that frame a reference to a record without naming its kind, stripped from
#: the start of a query beside :data:`_KINDS_OF`'s entry for the route and only where the
#: query opens on a reference (:func:`_wanted`).
#:
#: A person refers to what the assistant keeps by its kind — "the question you asked me
#: **about** my commute" — and those words are about the record's existence rather than
#: about what ``Question.content`` says. Both are ordinary words elsewhere, which is why
#: the opening admits them rather than their mere presence: ``about`` asserts a
#: relationship in "I talked about Alice".
_REFERENCE: Final[frozenset[str]] = frozenset(("about", "of"))

#: The one asking verb that is how a *question* gets referred to — "the question **you
#: asked** me about my commute", which is the form #1647 recorded the router producing.
#: Held apart from :data:`_REFERENCE` by two conditions rather than one:
#:
#: - **the form is the past tense alone.** A reference is to an asking that *happened*,
#:   which is what makes there be a record of it. The gerund is the act itself — "the
#:   memory of me asking Alice" is a memory of doing it — and stripping it leaves the
#:   query naming ``alice`` and nothing else, which resolves whatever the store says
#:   about her. ``ask`` and ``asks`` are absent for the same reason and buy nothing: no
#:   recorded phrasing uses them, and a query that says one fails closed;
#: - **somebody has to be doing the asking**, and in a reference that somebody is the
#:   user or the assistant, so the word before must be one of :data:`_FRAMING`'s.
_ASKING: Final[frozenset[str]] = frozenset(("asked",))


#: Raised where §3's vocabulary has grown a confirm-owed member and :data:`_MATCH_ON`
#: or :data:`ARGUMENT_OF` was not grown with it. A widening lane owes both, and
#: ADR-0197 §5 makes the argument mapping condition (iii) of the widening rule.
_UNMAPPED = (
    "{operation} is confirm-owed and has no lookup mapping: ADR-0197 §5 requires a "
    "member added under §3's widening rule to state its own"
)


async def perform(  # noqa: PLR0911 — one return per member of §3's closed vocabulary; collapsing them would hide the totality `assert_never` rests on
    operations: RoutedOperations, operation: RoutableOperation, argument: str | None
) -> RoutedListing | None:
    """Call the engine's own implementation of ``operation`` (ADR-0197 §2, §5).

    A read-only member is performed **exactly as the promoted surface declares it**,
    with that surface's own defaults and that surface's own bound, and routing changes
    neither: the paged members take the surface's ``DEFAULT_PAGE_SIZE`` default and
    routing gets no setting of its own, and ``standing_grants`` and ``spend_totals``
    are not paged and inherit their declared behaviour whole — including
    ``standing_grants``' "complete or refused, never truncated" (ADR-0139 §2), whose
    ``OversizedValueError`` reaches a routed pass as ``RouteOutcome.FAILED`` like any
    other raise. No clause of ADR-0197 imposes a page on a member the promoted surface
    declares unpaged, and none may: doing so would make a routed answer differ from the
    same operation's typed-door answer, which is the one thing §2's third clause exists
    to prevent.

    A confirm-owed member is called with the **scalar identity** §5's mapping read off
    the resolved candidate, and never with the record.

    Args:
        operations: The engine's own operations, injected.
        operation: The member to perform.
        argument: The scalar identity, on a confirm-owed member; ``None`` on a
            read-only one, which takes none.

    Returns:
        The read-only member's own listing, or ``None`` on a confirm-owed one — whose
        result is a ``bool`` or a withdrawn grant that §8 gives no arm and that §6
        keeps out of every prompt in any case.

    Raises:
        Exception: Whatever the operation itself raises. The caller classifies it as
            ``RouteOutcome.FAILED``; nothing is swallowed here, because "``FAILED``
            means the operation was **called and raised**, and the engine asserts
            nothing about whether it took effect".
    """
    match operation:
        case RoutableOperation.QUESTIONS:
            return await operations.questions(limit=DEFAULT_PAGE_SIZE, offset=0)
        case RoutableOperation.RECENT_READS:
            return await operations.recent_reads(limit=DEFAULT_PAGE_SIZE)
        case RoutableOperation.RECENT_INVOCATIONS:
            return await operations.recent_invocations(limit=DEFAULT_PAGE_SIZE)
        case RoutableOperation.RECENT_DECISIONS:
            return await operations.recent_decisions(limit=DEFAULT_PAGE_SIZE)
        case RoutableOperation.STANDING_GRANTS:
            return await operations.standing_grants()
        case RoutableOperation.SPEND_TOTALS:
            return await operations.spend_totals()
        case RoutableOperation.FORGET:
            await operations.forget(_required(argument, operation))
            return None
        case RoutableOperation.REVOKE:
            await operations.revoke(_required(argument, operation))
            return None
        case RoutableOperation.FORGET_QUESTION:
            await operations.forget_question(_required(argument, operation))
            return None
        case _:  # pragma: no cover — the match is exhaustive over the enum
            assert_never(operation)


def _required(argument: str | None, operation: RoutableOperation) -> str:
    """The scalar identity a confirm-owed call must have, or a defect.

    Reached only where the engine drove a confirm-owed route without resolving one,
    which is a defect in this module's caller rather than a condition a user can
    provoke: §5 ends the route on every resolution that does not produce exactly one
    candidate, so a ``None`` here means an operation was about to be performed with no
    subject at all.
    """
    if argument is None:  # pragma: no cover — a defect, not a reachable state
        msg = f"a routed {operation.value} reached the façade with no resolved subject"
        raise AssertionError(msg)
    return argument


__all__ = [
    "ARGUMENT_OF",
    "Resolved",
    "RoutedOperations",
    "RoutedRoute",
    "RoutingStage",
    "Unresolved",
    "perform",
    "resolve",
    "routing_prompt",
]
