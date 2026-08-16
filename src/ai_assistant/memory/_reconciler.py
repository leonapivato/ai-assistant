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

**Why ``memory`` may hold a ``ModelProvider``.** Egress is a rule about which
package opens the socket. ADR-0017 §1 permits it "from ``models/`` or from a
designated integration seam inside ``tools/``", and the ``lint-imports`` contract
confining network transports names only ``ai_assistant.tools.*``. A caller holding
the ``ModelProvider`` Protocol is not itself an egress boundary; ``models/`` is.
This is the sanctioned form, and it is the first time this subsystem takes it.

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
from typing import TYPE_CHECKING, Final, Protocol

from ai_assistant.core.types import ConflictRelation, Message, Role
from ai_assistant.memory._agreement import agrees

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.protocols import ModelProvider
    from ai_assistant.core.types import MemoryRecord, MemoryUpdateProposal

#: ADR-0159 §3's bound on how many conflict-set members one ingest may ask a model
#: about, in rank order. **Not** a second ``conflict_limit``: that ceiling is 100
#: and is a circuit breaker (ADR-0079 §1), where this is a cost bound. Three is
#: where the measured distribution puts the records a proposal could plausibly
#: restate or contradict; a fourth is nearly always a topical neighbour. Its right
#: value is an empirical question ADR-0159 does not pretend to have settled, which
#: is why it reaches here from ``Settings`` rather than living as a constant.
DEFAULT_RECONCILER_MAX_CONFLICTS: Final = 3

#: How many failed decode attempts the envelope scan tolerates before giving up.
#: Keeps the scan linear on a reply that is mostly prose containing braces.
_MAX_EXTRACTION_MISSES: Final = 64

#: The reply's spelling for each relation. A closed mapping rather than
#: ``ConflictRelation(value)``, so an unknown string leaves the member unlabelled
#: instead of raising inside a component that ADR-0159 §3 forbids to raise.
_RELATIONS: Final = {relation.value: relation for relation in ConflictRelation}

_SYSTEM_PROMPT: Final = """\
You are the conflict reconciler of an AI assistant's memory. You are shown one \
PROPOSED belief and a numbered list of STORED beliefs that a similarity search \
surfaced beside it. Similarity is all that put them together: it is not evidence \
that they say the same thing, and it is not evidence that they disagree.

For each stored belief you are asked about, say how the proposed belief stands to \
THAT belief, and to that belief alone:

- "restates" — the proposed belief says what the stored belief already says. Same \
claim, whatever the wording.
- "adds" — the proposed belief says something the stored belief does not say and \
does not deny. Two different true facts about the same person or topic are this. \
So is a belief that is merely more specific, or about a different aspect.
- "contradicts" — the proposed belief and the stored belief cannot both be true of \
the same subject at the same time.

"adds" is the common answer and it is the one to reach for when you are unsure. \
Two beliefs being about the same person, the same topic or the same part of their \
life is not a reason to call either of the other two.

TIME MATTERS, and it is the mistake to avoid. Where both beliefs state when \
something happened, and those times differ, they do not contradict unless the two \
claims are incompatible AT ONE TIME. "Lost his job shortly before 21 June 2023" \
and "took a temporary job around mid-July 2023" are two true facts in sequence: \
that is "adds", not "contradicts". A state that changed is not a contradiction; a \
claim about one instant that cannot hold at that instant is.

Judge only what the two sentences say. You know nothing else about the user, and \
you may not use how similar the wordings are as evidence either way."""

_ENVELOPE: Final = """\

Reply with a single JSON object and nothing else — no prose, no code fence:

{"relations": [{"id": "<stored belief id, exactly as given>",
                "relation": "restates" | "adds" | "contradicts"}]}

Give one entry for each stored belief listed above and none for anything else. \
Omit an entry you cannot decide; an omission is a valid answer and is better than \
a guess."""


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
    """

    async def reconcile(
        self,
        proposal: MemoryUpdateProposal,
        conflicts: Sequence[MemoryRecord],
    ) -> Mapping[str, ConflictRelation]:
        """Label what can be labelled, keyed by ``MemoryRecord.id``.

        Args:
            proposal: The proposal being ingested.
            conflicts: The resolved conflict set, best-ranked first.

        Returns:
            A relation for each member a determination was made about. A member
            absent from the mapping is unlabelled, which is the absence of a
            statement rather than a fourth relation.
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
        model: ModelProvider,
        route: str,
        max_conflicts: int = DEFAULT_RECONCILER_MAX_CONFLICTS,
    ) -> None:
        """Create the reconciler.

        Args:
            model: The seam the request goes through. A ``ModelProvider`` and
                never a provider SDK — ``memory`` holds the contract, ``models/``
                opens the socket (golden rule 4, ADR-0017 §1).
            route: The ``"provider:model"`` spec this reconciler **names** rather
                than inheriting (ADR-0159 §3). It is passed on every request, so
                which model reads a pair of stored beliefs is a configured choice
                and not whatever the seam happened to default to. The composition
                root resolves ``Settings.reconciler_model``'s ``None`` into the
                configured default route before it reaches here, so this is never
                empty.
            max_conflicts: ADR-0159 §3's bound — how many members of the conflict
                set, in rank order, may be consulted about. Members beyond it are
                left unlabelled.

        Raises:
            TypeError: If ``max_conflicts`` is not an integer (``bool`` included).
            ValueError: If ``max_conflicts`` is below 1, or ``route`` is blank.
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
        self._model = model
        self._route = route
        self._max_conflicts = max_conflicts

    async def reconcile(
        self,
        proposal: MemoryUpdateProposal,
        conflicts: Sequence[MemoryRecord],
    ) -> Mapping[str, ConflictRelation]:
        """Label the conflict set, spending at most one model request.

        Args:
            proposal: The proposal being ingested.
            conflicts: The resolved conflict set, best-ranked first.

        Returns:
            The relations determined. Every member the first rung settled, plus
            every member the model was consulted about and answered readably.

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
            return labelled
        conversation = [
            Message(role=Role.SYSTEM, content=_SYSTEM_PROMPT + _ENVELOPE),
            Message(role=Role.USER, content=_render(record, consulted)),
        ]
        try:
            reply = await self._model.complete(conversation, model=self._route)
            answered = _read(reply.content, {conflict.id for conflict in consulted})
        except Exception:
            # Every failure mode collapses to the same outcome, deliberately: a
            # model error, an exhausted deadline, an unroutable request, a reply
            # that does not decode. None of them is a reason to refuse a write
            # (§6), and distinguishing them here would only invite a rule written
            # over the distinction. Nothing is logged from this subsystem's write
            # path; the observable consequence is the relations it does not hold.
            return labelled
        # The model may not overturn the certain rung, and may not speak for a
        # member nobody asked about: `_read` has already dropped ids outside
        # `consulted`, and `consulted` already excludes everything `labelled` holds.
        return labelled | answered


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
    """
    stored = "\n\n".join(
        f"STORED BELIEF {conflict.id}\nkind: {conflict.kind}\n{conflict.content}"
        for conflict in consulted
    )
    return (
        f"PROPOSED BELIEF\nkind: {record.kind}\n{record.content}\n\n"
        f"{stored}\n\n"
        f"Answer for each of the {len(consulted)} stored belief(s) above."
    )


def _read(content: str, consulted: set[str]) -> dict[str, ConflictRelation]:
    """The readable labels of one reply, restricted to ``consulted``.

    Total and silent: every malformed shape yields no entry for the member it
    concerned rather than an error, because ADR-0159 §3 forbids this path to raise
    and an unlabelled member is a ruled, safe outcome (§4, §6).
    """
    envelope = _extract_object(content)
    if envelope is None:
        return {}
    entries = envelope.get("relations")
    if not isinstance(entries, list):
        return {}
    labels: dict[str, ConflictRelation] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        record_id = entry.get("id")
        relation = _RELATIONS.get(str(entry.get("relation", "")).strip().casefold())
        if relation is None or not isinstance(record_id, str) or record_id not in consulted:
            continue
        # First answer wins. A reply naming one member twice is malformed, and
        # taking the later entry would let a trailing "contradicts" overwrite an
        # earlier "adds" — the direction that destroys a record.
        labels.setdefault(record_id, relation)
    return labels


def _extract_object(content: str) -> dict[str, object] | None:
    """Decode the JSON envelope embedded in ``content``, or ``None``.

    ADR-0071's scan, **duplicated** from ``learning.observer`` and
    ``planning.planner`` rather than shared: ``memory`` may import neither
    (golden rule 1). ADR-0077 §9.5 rules that the helper stays in the producing
    subsystem and names the *third* model-backed producer as the trigger to
    promote it; this is that third, and the promotion is a decision of its own
    reaching three subsystems, filed as an issue rather than taken inside
    ADR-0159's fence.

    Each ``{`` is tried left to right with :meth:`json.JSONDecoder.raw_decode`,
    which stops at the end of the object and ignores trailing text, so a model
    that wraps the object in prose or a code fence is tolerated. The **envelope**
    is preferred over the leftmost object: the first candidate carrying a
    ``relations`` list wins, so a decoy object in the prose ahead of it is stepped
    over. A decoded object is advanced *past*, never re-entered, so a nested object
    is part of its parent rather than a separate candidate. What must not happen is
    a producer re-deriving ADR-0047 §4 step 1's superseded first-``{``-to-last-``}``
    slice, which spans a prose brace and the envelope's closer at once (#293).
    """
    decoder = json.JSONDecoder()
    first: dict[str, object] | None = None
    misses = 0
    index = 0
    length = len(content)
    while index < length:
        if content[index] != "{":
            index += 1
            continue
        try:
            candidate, end = decoder.raw_decode(content, index)
        except ValueError, RecursionError:
            misses += 1
            if misses > _MAX_EXTRACTION_MISSES:
                break
            index += 1
            continue
        if isinstance(candidate, dict):
            if isinstance(candidate.get("relations"), list):
                return candidate
            if first is None:
                first = candidate
        index = end
    return first
