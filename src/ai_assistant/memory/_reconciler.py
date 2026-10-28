"""ADR-0159's conflict reconciler: what a fold may rest on, before any ruling.

A **conflict relation** is a statement about how a proposed record stands to one
*named* record of the conflict set (ADR-0159 §1). The conflict set itself carries
only a similarity score, and the corpus has long ruled that a score authorises
neither of the two things a policy might do with it — ADR-0038 §2 and ADR-0045 §5
that it is not contradiction, ADR-0121 §1 that it is not agreement either. What
was missing was a *relation*, and this module is what makes one.

**It is a ``memory``-internal seam and stays one** (ADR-0159 §2). No Protocol for
it goes in ``core/protocols.py``; no subsystem outside ``memory`` holds a
reconciler, constructs one or invokes one; and no component outside ``memory``
determines a relation. What is *not* internal is the relation itself: it is
contract data at the existing ``MemoryPolicy`` seam, so every implementation of
that Protocol receives one, wherever it lives. The line is between the machinery
that **makes** a relation and the value it makes.

**Two rungs of one ladder, not two designs.** ADR-0121 §1's syntactic predicate —
:func:`~ai_assistant.memory._agreement.agrees` — is itself a reconciler answer,
and it is the first rung: certain where it fires, silent everywhere else, costing
nothing. The model is consulted only about the residue a string comparison cannot
settle, which is what makes its contribution *additive*: it answers only where
certainty already failed, and it can never overturn a certain answer.

**Why ``memory`` may hold a model seam.** Egress is a rule about which package
opens the socket. ADR-0017 §1 permits it "from ``models/`` or from a designated
integration seam inside ``tools/``", and the ``lint-imports`` contract confining
network transports names only ``ai_assistant.tools.*``. A caller holding a ``core``
Protocol is not itself an egress boundary; ``models/`` is. This is the sanctioned
form. Since ADR-0354 the Protocol held is ``StructuredCompleter``: the one request
asks for :class:`ReconcilerReply` and comes back as its value or as a named failure,
so no text-JSON scan reads the reply here (§9:1, §10:1).

**Nothing here decides whether a reconciler runs.** ADR-0159 §2 puts the
invocation condition in :class:`~ai_assistant.memory.ingest.MemoryIngestor`,
because it is a *correctness* boundary — a ``DataTier.SECRET`` proposal must not
reach a model request at all, and the ruling that would have caught it runs too
late. What is left here is the reconciler's own economics: whether the request is
worth making at all, given what the first rung already settled. A mis-scoped
answer *there* is unobservable in the ruling, which is the whole reason the two
halves live in different places (§3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Final, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidatorFunctionWrapHandler,
    WrapValidator,
)
from pydantic.json_schema import SkipJsonSchema

from ai_assistant.core.prompts import PromptDeclaration
from ai_assistant.core.types import ConflictRelation, Message, Role
from ai_assistant.memory._agreement import agrees

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.prompts import PromptTemplate
    from ai_assistant.core.protocols import StructuredCompleter
    from ai_assistant.core.types import MemoryRecord, MemoryUpdateProposal

#: ADR-0159 §3's bound on how many conflict-set members one ingest may ask a model
#: about, in rank order. **Not** a second ``conflict_limit``: that ceiling is 100
#: and is a circuit breaker (ADR-0079 §1), where this is a cost bound.
#:
#: **Fifteen since ADR-0171 §1**, which partially supersedes ADR-0159 §3's default of
#: three on #1302's measurement: at three the bound explained every one of a replay's
#: 2,522 unlabelled relations, and an unlabelled member was swept into the supersede
#: widening rather than spared by it. It reaches production from ``Settings`` rather
#: than from here, and **must not disagree with it** (ADR-0171 §5) — this constant
#: serves a direct construction with no ``Settings`` in hand, and the agreement is
#: pinned by a test rather than left to a reader noticing two numbers.
DEFAULT_RECONCILER_MAX_CONFLICTS: Final = 15

#: The reply's spelling for each relation. A closed mapping rather than
#: ``ConflictRelation(value)``, so an unknown string leaves the member unlabelled
#: instead of raising inside a component that ADR-0159 §3 forbids to raise.
_RELATIONS: Final = {relation.value: relation for relation in ConflictRelation}


def _entry_or_none(value: object, handler: ValidatorFunctionWrapHandler) -> object:
    """One entry of the list as :class:`ReconcilerReplyEntry`, or ``None`` if it is not one.

    A malformed **entry** inside a readable list leaves the reply readable (ADR-0164
    §3): the request plainly reached a model that answered, so the entry is dropped
    and the rest stand. Without this, one bad entry would make the whole reply
    ``invalid`` and the call ``FAILED``, an outcome §3 does not give it. The schema
    sent still names only the entry's own shape (:class:`~pydantic.json_schema.SkipJsonSchema`
    keeps ``None`` out of it), so a model in native mode writes entries alone.
    """
    try:
        return handler(value)
    except ValidationError:
        return None


class ReconcilerReplyEntry(BaseModel):
    """One relation the reply states: a stored belief's id, and how the proposal stands.

    ``relation`` is read as a string and judged after the parse, case and surrounding
    whitespace aside, so an unknown spelling leaves that member unlabelled rather than
    refusing the reply (ADR-0354 §9:1: the checks after the parse stay as they are).
    The schema sent still lists the three spellings the prompt asks for, so a model in
    native mode writes one of them. An unnamed key is ignored, as it was before the
    move; the schema sent is closed either way (§10:2).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    relation: Annotated[
        str, Field(json_schema_extra={"enum": [relation.value for relation in ConflictRelation]})
    ]


class ReconcilerReply(BaseModel):
    """The reconciler's reply shape (ADR-0354 §9:1): the envelope its prompt asks for.

    The names are the prompt's, ``relations``, ``id`` and ``relation``, because the
    schema sent carries no text (§3:2) and the prompt, default or override, is what
    says what each means. A reply that does not validate as this — no ``relations``
    list, prose around the object, nothing at all — is a returned failure and the call
    is ``FAILED`` (§9:2, ADR-0164 §3). An entry in the list that is not one is
    ``None`` here, and :func:`_read` drops it.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    relations: list[
        Annotated[ReconcilerReplyEntry | SkipJsonSchema[None], WrapValidator(_entry_or_none)]
    ]


#: The reconciler's prompt (ADR-0334 §2): the system message of its one request is the
#: template ``memory_reconciler.txt`` shipped beside this module, or the owner's override
#: of it, which the composition root reads and hands the reconciler (§3:5). It names no
#: flag and no value. The rendered request, the reply's reading and both halves of the
#: bound stay here, whatever a template says (§1:3, §7:2). The reconciler writes no
#: diagnostic entry, so the version its requests sent is the one the start's line names
#: (§8:3).
#:
#: **What the instruction must say**, which binds the default and every override alike
#: (ADR-0334 §7:1), and which a promotion's review reads it against (§7:3): the three
#: relations, each a statement about the proposed belief and one named stored belief
#: (ADR-0159 §1:1); that a relation rests on what the two beliefs say and on nothing
#: else, similarity included (§1:3); and that two times which differ make no
#: contradiction unless the claims are incompatible at one time (§3:5). ADR-0159 leaves
#: the wording itself to the implementing lane. The reply's envelope — one ``relations``
#: entry per stored belief asked about, named by its id — is :class:`ReconcilerReply`,
#: the shape the request asks for (ADR-0354 §9:1). Its schema carries no text (§3:2),
#: so the template is what says what each field means, and a template that asks for
#: another shape gets replies that do not read: every member unlabelled, ``FAILED``.
MEMORY_RECONCILER_PROMPT: Final = PromptDeclaration(
    name="memory_reconciler", package="ai_assistant.memory"
)


class ReconcilerOutcome(Enum):
    """Which of its three outcomes a reconciler that **ran** took (ADR-0164 §3).

    The three are exhaustive over a reconciler that ran and a report names
    **exactly one** of them. ``reconciler_absent`` is deliberately not among them:
    no reconciler ran there, so no report was due, and the writer observes that
    about itself.

    - :attr:`ANSWERED` — the model rung completed and its answer was readable. The
      relations beside it are the labels that determination produced.
    - :attr:`FAILED` — a request was made and yielded no readable answer. The
      writer's guard counts a *non-conforming* result under the same metric key
      without any report saying so, which is why that key takes no view on whether
      a request reached a provider (§6).
    - :attr:`UNCONSULTED` — the reconciler completed without making a model request
      at all: ADR-0159 §3's other half of the one-request clause, whatever left it
      with nothing to ask about. It is **not** a claim that certainty settled the
      set — an empty conflict set reaches here too, and dominates.

    **A plain ``Enum`` and not a ``StrEnum``, deliberately.** ADR-0164 §3's
    installing-on-identity clause is about exactly the hazard a ``StrEnum`` creates:
    a bare string compares equal to a member *and hashes with it*, so a report
    carrying ``"answered"`` would read as conforming. With a plain ``Enum`` it is
    the non-member value §3 calls non-conforming, and the writer's identity test
    says so.
    """

    ANSWERED = "answered"
    FAILED = "failed"
    UNCONSULTED = "unconsulted"


@dataclass(frozen=True, slots=True)
class ReconcilerReport:
    """What a reconciler returns: the relations, and the outcome it took.

    ADR-0164 §3 requires the outcome to travel **beside** the relations rather than
    be inferred from them, and the reason is a defect that reshaped that ADR:
    :meth:`ModelBackedReconciler.reconcile` absorbs its own provider failures, so
    from the mapping alone a failed determination and a silent model are the same
    empty answer. Only this side of the seam knows which it was.

    **It crosses no contract.** ADR-0159 §2 keeps this seam inside ``memory`` — "no
    Protocol for it goes in ``core/protocols.py``" — so this type is
    ``memory``-internal and ADR-0164 §2's no-``core``-change finding is unaffected.

    **The report is read for exactly two purposes** (ADR-0164 §3): to fill the four
    proposal metric keys, and to decide whether the model rung's labels are
    installable. Nothing else reads it, no ruling reads it, and no ingest is
    refused or delayed because of it — it reaches a ruling only the way any other
    determination does, through the relations the writer therefore holds, which is
    the one route ADR-0159 §6 admits.

    Attributes:
        relations: A relation for each member a determination was made about,
            keyed by ``MemoryRecord.id``. A member absent from the mapping is
            unlabelled, which is the absence of a statement rather than a fourth
            relation.
        outcomes: The outcome taken. A conforming reconciler names **exactly one**;
            the field is a set rather than a single member because a report naming
            *none* and one naming *more than one* are both shapes ADR-0164 §3 rules
            on and both must be expressible for the writer's handling of them to be
            testable. Either is non-conforming **in whole**: nothing the report
            accompanies installs, and the proposal counts under
            ``reconciler_failed``.
    """

    relations: Mapping[str, ConflictRelation]
    outcomes: frozenset[ReconcilerOutcome]


class ConflictReconciler(Protocol):
    """Determines ADR-0159 §1 relations for members of a conflict set.

    **Deliberately not in ``core/protocols.py``** (ADR-0159 §2, and its
    Alternatives). Both sides of this seam are inside ``memory`` — the ingestor
    that invokes it and the reconciler that answers — and ``core/protocols.py`` is
    for contracts *between* subsystems. Adding one there would widen the surface
    ADR-0027 §3 puts in the review floor for an injection nobody needs.

    An implementation owes ADR-0159 §3's five clauses, and the last is the one a
    caller depends on:

    1. A member that :func:`~ai_assistant.memory._agreement.agrees` with the
       proposal is labelled ``RESTATES``, always, with no model call. The rung is
       unconditional; an implementation reaching a different answer on a pair
       ``agrees`` admits is not conforming.
    2. A model is consulted only for members that rung did not label, and only for
       the first ``max_conflicts`` members of the conflict set in rank order.
    3. A model-supplied label is installed only for a member the implementation
       **consulted the model about** — never one the reply volunteers about
       anything else, including a member that fell beyond the bound.
    4. At most **one** model request per call, covering every member consulted,
       and none at all where rung 1 settled everything.
    5. **It never raises and never refuses an ingest.** A model error, a timeout,
       an unreadable reply or an unroutable request yields *unlabelled* for every
       member it could not label. The one exception is a ``CancelledError``
       delivered from **outside**, which ADR-0060 §1 requires be delivered onward
       and which is never converted into an unlabelled member; a deadline
       ``models/`` issues against its own request is not that, and is classified
       into unlabelled like any other timeout.
    6. **It reports which outcome it took**, beside the relations (ADR-0164 §3).
       Exactly one of :class:`ReconcilerOutcome`'s three members, on every call.
       This is what the seam *gained*; the five clauses above are ADR-0159 §3's and
       are untouched by it.
    """

    async def reconcile(
        self,
        proposal: MemoryUpdateProposal,
        conflicts: Sequence[MemoryRecord],
    ) -> ReconcilerReport:
        """Label what can be labelled, and say which outcome this call took.

        Args:
            proposal: The proposal being ingested.
            conflicts: The resolved conflict set, best-ranked first.

        Returns:
            The relations determined, beside the one :class:`ReconcilerOutcome`
            this call took (ADR-0164 §3). The outcome is **reported** rather than
            inferred: an implementation that absorbs its own provider failures —
            as clause 5 obliges it to — is the only side of this seam that can tell
            a failed determination from a model with nothing to say.
        """
        ...


class ModelBackedReconciler:
    """ADR-0159 §3's two rungs: ``agrees`` first, then at most one model request.

    Structurally implements :class:`ConflictReconciler`.

    **The bound has a response half, and it is the half a test forgets** (§3).
    Asking about three members does not stop a reply naming a fourth, and the
    fourth's id is a *valid* id — it is in the conflict set — so the policy's
    ignore rule, stated over ids absent from ``conflicts``, does not reach it.
    Installed, a volunteered ``CONTRADICTS`` on a member nobody asked about would
    block a fold ADR-0159 §4(a) would otherwise make: the bound failing in the one
    direction it exists to prevent. So the filter here is stated over what was
    **consulted about**, which is a fact this object holds and the model cannot
    influence.

    **One request, not one per member, and the reason is not only cost** (§3).
    A relation is a statement about a pair, but the *set* is what disambiguates
    it: shown three records together, a labeller can see that two are a sequence
    and the third is the claim being restated, where the same three judged in
    isolation invite three independent guesses. Bundling is also what makes
    ADR-0159 §6's latency statement a statement — one request under one deadline,
    rather than up to ``max_conflicts`` of them under ``model_max_attempts``
    retries each.
    """

    def __init__(
        self,
        *,
        completer: StructuredCompleter,
        route: str,
        prompt: PromptTemplate,
        max_conflicts: int = DEFAULT_RECONCILER_MAX_CONFLICTS,
    ) -> None:
        """Create the reconciler.

        Args:
            completer: The seam the request goes through. A
                ``StructuredCompleter`` and never a provider SDK — ``memory`` holds
                the contract, ``models/`` opens the socket (golden rule 4, ADR-0017
                §1). The composition root hands it the object it handed as the
                reconciler's ``ModelProvider`` before ADR-0354, route and retry
                policy unchanged (§6:2).
            route: The ``"provider:model"`` spec this reconciler **names** rather
                than inheriting (ADR-0159 §3). It is passed on every request, so
                which model reads a pair of stored beliefs is a configured choice
                and not whatever the seam happened to default to. The composition
                root resolves ``Settings.reconciler_model``'s ``None`` into the
                configured default route before it reaches here, so this is never
                empty.
            prompt: The template of :data:`MEMORY_RECONCILER_PROMPT`, default or
                override, as the composition root read it at start (ADR-0334 §3:5).
            max_conflicts: ADR-0159 §3's bound — how many members of the conflict
                set, in rank order, may be consulted about. Members beyond it are
                left unlabelled.

        Raises:
            TypeError: If ``max_conflicts`` is not an integer (``bool`` included).
            ValueError: If ``max_conflicts`` is below 1, ``route`` is blank, or
                ``prompt`` is not a template of :data:`MEMORY_RECONCILER_PROMPT`.
                Refused at construction rather than at first use, for ADR-0022
                §4a's reason: a bound the caller got wrong should fail where it was
                set, not on the first ingest that silently labels nothing.
        """
        if isinstance(max_conflicts, bool) or not isinstance(max_conflicts, int):
            msg = f"max_conflicts must be an integer, got {max_conflicts!r}"
            raise TypeError(msg)
        if max_conflicts < 1:
            msg = f"max_conflicts must be at least 1, got {max_conflicts}"
            raise ValueError(msg)
        if not route.strip():
            msg = "route must name a 'provider:model' spec, not a blank string"
            raise ValueError(msg)
        if prompt.declaration != MEMORY_RECONCILER_PROMPT:
            msg = "the reconciler renders the memory_reconciler prompt (ADR-0334 §2)"
            raise ValueError(msg)
        self._prompt = prompt
        self._completer = completer
        self._route = route
        self._max_conflicts = max_conflicts

    async def reconcile(
        self,
        proposal: MemoryUpdateProposal,
        conflicts: Sequence[MemoryRecord],
    ) -> ReconcilerReport:
        """Label the conflict set, spending at most one model request.

        Args:
            proposal: The proposal being ingested.
            conflicts: The resolved conflict set, best-ranked first.

        Returns:
            The relations determined — every member the first rung settled, plus
            every member the model was consulted about and answered readably —
            beside the outcome this call took (ADR-0164 §3). The three are reported
            apart because they are *this object's* facts and nothing downstream can
            recover them: :attr:`~ReconcilerOutcome.UNCONSULTED` where the guard
            below never ran because no request was due,
            :attr:`~ReconcilerOutcome.FAILED` where a request was made and yielded
            no readable answer — the broad guard, and a reply returned as a failure
            (ADR-0354 §9:2), which are the same fact from two directions — and
            :attr:`~ReconcilerOutcome.ANSWERED` where it was made and read. A
            readable reply naming no relation is ``ANSWERED`` with an empty
            mapping, **not** ``UNCONSULTED``: the request happened, and a report
            denying it would make the trace say a prompt was never sent.

        Raises:
            asyncio.CancelledError: Only where one was delivered from **outside**
                this call. It is neither caught nor converted (ADR-0060 §1,
                ADR-0159 §3): a ``CancelledError`` is a ``BaseException``, so the
                broad guard below is stated over ``Exception`` and lets it past. A
                deadline ``models/`` issues against its own request surfaces as an
                ordinary error and is classified into unlabelled instead.
        """
        record = proposal.proposed
        labelled: dict[str, ConflictRelation] = {
            conflict.id: ConflictRelation.RESTATES
            for conflict in conflicts
            if agrees(conflict, record)
        }
        # The bound is over the conflict set **in rank order**, not over the
        # residue: the members past it are left unlabelled whether or not the rung
        # above reached them, which is what makes the spend a property of the set
        # the store surfaced rather than of how many restatements happened to be in
        # it (ADR-0159 §3).
        consulted = tuple(
            conflict for conflict in conflicts[: self._max_conflicts] if conflict.id not in labelled
        )
        if not consulted:
            # §3's other half of the one-request clause: no request at all where
            # the rung settled every member this call would have asked about. Most
            # ingests take this path or never reach a reconciler in the first place.
            # An **empty** conflict set arrives here too, and on the observed corpus
            # it dominates — which is why ADR-0164 §3 says this key is not a measure
            # of certainty and must be read beside ``relations_offered``.
            return _report(labelled, ReconcilerOutcome.UNCONSULTED)
        conversation = [
            Message(role=Role.SYSTEM, content=self._prompt.render()),
            Message(role=Role.USER, content=_render(record, consulted)),
        ]
        try:
            reply = await self._completer.complete_structured(
                conversation, ReconcilerReply, model=self._route
            )
            if reply.value is None:
                # A response came back and is not the shape's value (ADR-0354 §9:2).
                # `refused` lands where a raised `ModelContentFilterError` lands, the
                # guard below; `invalid`, `empty` and `cut` where a reply that does not
                # read lands, here. Both are ADR-0164 §3's "made a request that yielded
                # no readable answer", `FAILED`, and it is exactly the state a merged
                # empty mapping cannot be told apart from once it has crossed the seam.
                return _report(labelled, ReconcilerOutcome.FAILED)
            answered = _read(reply.value, {conflict.id for conflict in consulted})
        except Exception:
            # Every failure mode collapses to the same *relations*, deliberately: a
            # model error, an exhausted deadline, an unroutable request, a reply
            # that does not decode. None of them is a reason to refuse a write
            # (§6), and distinguishing them here would only invite a rule written
            # over the distinction. Nothing is logged from this subsystem's write
            # path; the observable consequence is the relations it does not hold —
            # and, since ADR-0164 §3, the outcome reported beside them, which is a
            # count and never an input to a ruling.
            return _report(labelled, ReconcilerOutcome.FAILED)
        # The model may not overturn the certain rung, and may not speak for a
        # member nobody asked about: `_read` has already dropped ids outside
        # `consulted`, and `consulted` already excludes everything `labelled` holds.
        return _report(labelled | answered, ReconcilerOutcome.ANSWERED)


def _report(
    relations: Mapping[str, ConflictRelation], outcome: ReconcilerOutcome
) -> ReconcilerReport:
    """One outcome, in the set shape the seam carries (ADR-0164 §3).

    A conforming reconciler names exactly one, and this is the only place this
    module builds a report — so "exactly one" holds by construction here rather
    than by three call sites agreeing.

    Args:
        relations: The labels this call determined.
        outcome: The one outcome it took.

    Returns:
        The report to hand the writer.
    """
    return ReconcilerReport(relations=relations, outcomes=frozenset({outcome}))


def _quoted_span(value: str) -> str:
    """Render one held string so it cannot write this assembler's own syntax.

    ADR-0098 §2 rules that a span's attribution is "not forgeable from inside the
    span", and that "an assembler that embeds a span in a syntax the serialised span
    can itself produce does not conform, whatever labels it emits". This prompt's
    syntax is line-oriented — one line per belief, opened by a ``PROPOSED BELIEF``
    or ``STORED BELIEF`` keyword — and the spans reaching it are
    :data:`~ai_assistant.core.types.EncodableText`, which validates UTF-8
    encodability and permits every newline and quotation mark in between.

    :func:`json.dumps` is the deterministic transform §2 admits, at its default
    ``ensure_ascii=True``: the result is single-line printable ASCII delimited by
    quotes the value can no longer close. The ASCII part is the clause rather than a
    preference — ``ensure_ascii=False`` emits U+2028 and U+2029 literally, which
    JSON does not escape and which :meth:`str.splitlines` treats as line boundaries,
    so a span carrying one could still open a line and forge a belief. Escaping
    every non-ASCII character closes that by construction rather than by enumerating
    the two code points known today.

    The escaping is pinned to :func:`json.dumps` by
    ``test_the_assembler_escapes_a_span_with_the_json_transform``.

    Args:
        value: The held string, verbatim as this system carries it.

    Returns:
        The quoted, escaped span to interpolate into a prompt line.
    """
    return json.dumps(value)


def _render(record: MemoryRecord, consulted: Sequence[MemoryRecord]) -> str:
    """The user turn: the proposal, then each member consulted about, by id.

    **Ids rather than positional labels**, so the filter ADR-0159 §3 requires is
    doing real work: a reply naming a beyond-bound member's own valid id is a
    shape the guard must reject, and a label scheme would make that case
    unreachable in the prompt and therefore untested in the code.

    Only ``kind`` and ``content`` are rendered. That is not economy — ADR-0159 §1
    fixes that a relation is a property of those two and of nothing else, so a
    provenance field, a band or a validity window in the prompt would be an
    invitation to derive a relation from something that cannot support one.

    **Every free-text span is escaped, and the container is one line per belief**
    (ADR-0098 §2, #1454). The block form this replaced — a ``STORED BELIEF <id>``
    line, a ``kind:`` line and the content, separated by blank lines — is a syntax an
    interpolated span could itself write, and a reader's belief reaches here on the
    ordinary ingest path: ``_may_reconcile`` fires on every admissible, unconfirmed
    ingest whatever its band (ADR-0336 §2), a reader's proposal among them. With
    :func:`_quoted_span` the span is single-line printable ASCII, so it cannot reach
    the start of a line, and each belief is one line whose keyword is the assembler's
    first token.

    ``kind`` is not escaped and does not need to be: every member of
    :data:`~ai_assistant.core.types.MemoryRecord` fixes it as a ``Literal``, so it is
    the assembler's own vocabulary rather than a span. The **id** is escaped even
    though ADR-0092 §6 obliges an ``EXTERNAL`` producer to mint one opaque to its
    source, for the reason the retired ``orchestration.composing`` gave for quoting
    this system's own output: "a span this system authored can still carry a newline, and
    §2's non-forgeability is a property of the assembler rather than a judgement
    about the span's author". ``MemoryRecord.id`` is ``EncodableText``, and a
    container whose non-forgeability rested on a producer elsewhere behaving would
    be the reasoning §2 exists to refuse. The quoting round-trips through the reply:
    an id shown as a JSON string is the same string the envelope asks the model to
    put back in a JSON field.
    """
    lines = [f"PROPOSED BELIEF ({record.kind}) {_quoted_span(record.content)}", ""]
    lines.extend(
        f"STORED BELIEF {_quoted_span(conflict.id)} ({conflict.kind}) "
        f"{_quoted_span(conflict.content)}"
        for conflict in consulted
    )
    lines.append("")
    lines.append(f"Answer for each of the {len(consulted)} stored belief(s) above.")
    return "\n".join(lines)


def _read(reply: ReconcilerReply, consulted: set[str]) -> dict[str, ConflictRelation]:
    """The labels of one readable reply, restricted to ``consulted``.

    Total and silent: every malformed entry yields no label for the member it
    concerned rather than an error, because ADR-0159 §3 forbids this path to raise
    and an unlabelled member is a ruled, safe outcome (§4, §6). These are the checks
    after the parse, unchanged by ADR-0354 (§9:1); the parse itself is the seam's,
    by §3:4's one rule, and a reply it refuses never reaches here.

    **A readable reply naming nothing is ``{}``**, which the reconciler reports as
    :attr:`~ReconcilerOutcome.ANSWERED`: a conforming "nothing to add" (ADR-0164 §3).
    A **malformed entry inside a readable list** — one :class:`ReconcilerReply` holds
    as ``None``, an unknown relation, an id nobody asked about — is dropped and leaves
    the reply readable, because the request plainly reached a model that answered.

    Args:
        reply: The reply, read as the shape.
        consulted: The ids this call asked about; anything else is dropped unread.

    Returns:
        The labels read.
    """
    labels: dict[str, ConflictRelation] = {}
    for entry in reply.relations:
        if entry is None:
            continue
        relation = _RELATIONS.get(entry.relation.strip().casefold())
        if relation is None or entry.id not in consulted:
            continue
        # First answer wins. A reply naming one member twice is malformed, and
        # taking the later entry would let a trailing "contradicts" overwrite an
        # earlier "adds" — the direction that destroys a record.
        labels.setdefault(entry.id, relation)
    return labels
