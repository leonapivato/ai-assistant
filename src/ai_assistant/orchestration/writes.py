"""The write stage: ingest a proposal, and park the question a deferral raises.

ADR-0078 §3's coordinator. ``MemoryWriter.ingest`` does not change and does not
learn to queue — ADR-0028's Consequences ruled that out ("deferral would need a
result type that can say 'not yet' and this one cannot") and ADR-0078 agrees with
the ruling rather than working around it. So the *orchestration* write stage, which
already held the ``MemoryWriter`` by injection and now also holds the
``DeferralStore``, observes ``result.decision.kind is ASK_USER`` and enqueues.

That is ADR-0074 §9's coordinator rule applied unchanged: "the two-store sequence
belongs to a coordinator, not to either store… `orchestration` is the one place
that legitimately holds both handles by injection." Neither store may hold the
other (golden rule 1), and the sequence spans both.

**One stage, injected into every producer's stage.** ``LearningLoop.learn`` and
``ObservationStage.observe`` both reach memory through this object rather than
through a ``MemoryWriter`` handle of their own, which is the one sentence ADR-0078
§3 asks of the implementing lane: "a proposal reaches memory through the
orchestration write stage, not through a ``MemoryWriter`` handle of its own. A
producer holding the writer directly gets the ratified policy and applier and
silently loses the queue — the drop this ADR ends, restored by a wiring choice."
The *producers* themselves (``FeedbackProcessor``, ``Observer``) hold nothing:
ADR-0077 §4 already pays that half, and a deferred proposal is self-contained, so
the stage can hold it without holding anything of the producer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_assistant.core.errors import DeferralIdConflictError, DeferralStoreError
from ai_assistant.core.types import DataTier, MemoryDecisionKind

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import DeferralStore, MemoryWriter
    from ai_assistant.core.types import (
        DeferralAdmission,
        MemoryDecision,
        MemoryIngestResult,
        MemoryUpdateProposal,
    )

#: How many times an admission re-mints a colliding deferral id before giving up.
#: A minted id (``uuid4``) collides with vanishing probability, so a handful of
#: attempts is far past any real collision; the bound exists to make a
#: *pathological* id factory fail loudly rather than spin, the shape ADR-0045 §4
#: already uses for a supersession's id and ADR-0078 §2 names for a claim token's.
#: "Bounded" without an exhaustion case is a loop nobody has counted, so the
#: exhaustion is asserted rather than assumed.
_MAX_ADMISSION_ATTEMPTS = 5


def _uuid() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    """What the write stage did with one proposal (ADR-0078 §3, §7).

    A frozen ``orchestration`` dataclass rather than a ``core`` model, for
    :class:`~ai_assistant.orchestration.loop.TurnResult`'s reason (ADR-0042 §1): it
    crosses no *subsystem* boundary. It exists because a ruling and what became of
    the question that ruling raised are two facts, and ``MemoryIngestResult``
    carries only the first — growing it to carry the second would make every writer
    a queue, which ADR-0028 refused.

    Attributes:
        result: The ruling and the id written, exactly as the ``MemoryWriter``
            returned it.
        admission: What the queue did with the question, when a question was
            offered at all. ``None`` on every non-``ASK_USER`` ruling, and ``None``
            for the one ``ASK_USER`` that is never queued — a ``DataTier.SECRET``
            proposal (ADR-0078 §1). The distinction is load-bearing at the surface:
            it is what stops a user being told to go answer a question that was
            never asked (§10 item 9).
    """

    result: MemoryIngestResult
    admission: DeferralAdmission | None = None


async def admit_question(  # noqa: PLR0913 — the store, its minting seam, and `defer`'s own five
    deferrals: DeferralStore,
    *,
    id_factory: Callable[[], str],
    proposal: MemoryUpdateProposal,
    decision: MemoryDecision,
    predecessor_id: str | None = None,
    successor_to_claim: str | None = None,
) -> DeferralAdmission:
    """Park a question under a freshly minted id, re-minting on a collision.

    The coordinator mints the deferral id, as it does for a ``MemoryRecord``, and
    ADR-0078 §2 puts "retry-on-collision at the minting site" — here — because a
    physical id collision is a *caller-side minting fault* the store refuses rather
    than absorbing: absorbed into the key-idempotent path it would hand the caller
    back a different question under an id it believes it just minted.

    Shared by the ordinary write-stage admission and the answer path's successor
    admission (ADR-0078 §9), so both are bounded the same way. Both paths need it
    for the same reason and an implementation can correctly retry one and propagate
    the other, which parks nothing and loses exactly the correction the user just
    typed — so ADR-0078 §10 names both.

    Args:
        deferrals: The durable queue.
        id_factory: Mints each candidate deferral id. Injectable so a test can
            force a collision and assert the re-mint, and force an *always*
            colliding factory and assert the bounded end.
        proposal: The question's proposal — for an ordinary admission, the snapshot
            carrying the ids the policy actually ruled against (ADR-0078 §3).
        decision: The ``ASK_USER`` ruling that deferred it.
        predecessor_id: The question this one succeeds, on the re-deferral path.
        successor_to_claim: The parent's claim token, which authorises the link and
            the cap bypass.

    Returns:
        The store's admission — admitted, suppressed, or refused.

    Raises:
        DeferralStoreError: If the bound is exhausted, with **nothing persisted**;
            or as the store raises. A correction is then neither silently dropped
            nor half-written.
    """
    last: DeferralIdConflictError | None = None
    for _ in range(_MAX_ADMISSION_ATTEMPTS):
        try:
            return await deferrals.defer(
                deferral_id=id_factory(),
                proposal=proposal,
                decision=decision,
                predecessor_id=predecessor_id,
                successor_to_claim=successor_to_claim,
            )
        except DeferralIdConflictError as exc:
            last = exc
            continue
    msg = (
        f"could not mint a free deferral id for a deferred question after "
        f"{_MAX_ADMISSION_ATTEMPTS} attempts; nothing was queued"
    )
    raise DeferralStoreError(msg) from last


class MemoryWriteStage:
    """Puts one proposal through the write path, and parks what it defers.

    The stage every producer's stage writes through (module docstring). It rules on
    nothing and writes no memory itself: the injected ``MemoryWriter`` owns conflict
    resolution, the policy's ruling and the write, and this object adds exactly the
    one thing no writer may (ADR-0028) — the durable question an ``ASK_USER``
    raises.
    """

    def __init__(
        self,
        *,
        writer: MemoryWriter,
        deferrals: DeferralStore,
        id_factory: Callable[[], str] = _uuid,
    ) -> None:
        """Wire the stage from the two contracts the enqueue spans.

        **``deferrals`` must be the very instance the question surface enumerates
        from**, and ``writer`` must persist to the ``MemoryStore`` whose records a
        question's frozen conflict set names. Neither is expressible in the type
        system, so both are composition-root obligations with tests behind them
        (ADR-0078 §3, the shape ADR-0028 §4 established): a second queue holds
        questions nobody can answer, and a second store retires nothing while
        reporting success.

        Args:
            writer: The ratified memory write path — conflicts, the policy's ruling
                and persistence in one call. It holds the policy; this stage does
                not, and never inspects a ruling for anything but whether it
                deferred.
            deferrals: The durable queue a deferred question waits in.
            id_factory: Mints each question's id; injectable so a test can force a
                collision (:func:`admit_question`).
        """
        self._writer = writer
        self._deferrals = deferrals
        self._id_factory = id_factory

    async def write(self, proposal: MemoryUpdateProposal) -> WriteOutcome:
        """Ingest ``proposal``, parking the question if the policy deferred it.

        **What is enqueued is a snapshot, not the proposal this stage was handed,
        and the difference is the whole point of ADR-0078 §4.** The writer resolves
        conflicts onto its *own* copy, so the caller's proposal still carries an
        empty ``conflicts`` when ``ingest`` returns. The question is therefore built
        around a proposal whose ``conflicts`` is **exactly ``result.conflicts``** —
        the ids the policy actually ruled against. Enqueuing the untouched original
        satisfies every store and writer conformance clause and produces a question
        that shows the user no conflicting assertion, an answer whose ``retires`` is
        empty, and a re-ingest that finds that assertion outside the authority and
        **re-defers**: the user answers, and is asked again.

        **Nothing is enqueued for a ``DataTier.SECRET`` proposal** (ADR-0078 §1).
        ADR-0004 §3 is unconditional that Tier 0 content lives in the OS keyring and
        "never in a database, never in a committed file", and a durable queue is a
        file — so today's secret-tier arm is precisely what keeps such content *out*
        of storage, and persisting it here would open a gap rather than close one.
        The ruling is reported and nothing is persisted, which is what happens
        today. ``DeferredProposal``'s own validator refuses one anyway; this filter
        is the polite version of the same rule, and it is what keeps the ordinary
        path from surfacing a validation failure as an error.

        Args:
            proposal: The proposed memory update.

        Returns:
            The ruling, and what the queue did with the question it raised.

        Raises:
            MemoryStoreError: As the writer raises — including a write-producing
                ruling on secret-tier data and an uncovered fold onto an assertion
                (ADR-0078 §5b).
            UnresolvedEvidenceError: As the writer raises for a ``DERIVED``
                proposal citing a record the store does not hold.
            DeferralStoreError: If the question could not be parked. The ruling has
                already been applied — there is no ruling to un-make — so this
                surfaces rather than being swallowed: a correction the user typed is
                neither silently dropped nor half-written.
        """
        result = await self._writer.ingest(proposal)
        if result.decision.kind is not MemoryDecisionKind.ASK_USER:
            return WriteOutcome(result=result)
        if proposal.sensitivity is DataTier.SECRET:
            return WriteOutcome(result=result)
        snapshot = proposal.model_copy(update={"conflicts": result.conflicts, "confirmation": None})
        admission = await admit_question(
            self._deferrals,
            id_factory=self._id_factory,
            proposal=snapshot,
            decision=result.decision,
        )
        return WriteOutcome(result=result, admission=admission)
