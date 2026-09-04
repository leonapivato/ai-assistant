"""The recipient-grant operations: the offerable rows, the act, the listings, revocation.

ADR-0235 §4 puts five operations on
:class:`~ai_assistant.core.protocols.AssistantEngine` and §12 rules that the
implementing lane lands "the engine implementation, including the store's whole
face reaching ``Engine`` from ``app/composition.py``". This module is the object
that holds that face, on
:class:`~ai_assistant.orchestration.grants.GrantOperations`' shape and for its
reason: the operations must be ``AssistantEngine`` methods to be addressable over
the socket at all, ``AssistantEngine`` is provided by `orchestration`, and the
engine delegates rather than growing a store of its own.

**This object is the only holder of a**
:class:`~ai_assistant.core.protocols.RecipientGrantStore` **outside the
composition root** (ADR-0193 §1, ADR-0235 §4). The policy is given the narrow
:class:`~ai_assistant.core.protocols.RecipientGrants` and the trail the narrower
:class:`~ai_assistant.core.protocols.RecipientGrantResolution`; a component handed
the whole store is one ``record`` call away from authorising the send it is ruling
on. And no ``interfaces`` adapter holds any of the three: a surface is given
records by the operations here and reads no store, which is golden rule 3.

**Recipient grants and source grants are two vocabularies and never one**
(ADR-0235 §7). Nothing here reads, writes or consults a
:class:`~ai_assistant.core.protocols.SourceGrantStore`, and
:mod:`ai_assistant.orchestration.grants` consults nothing here. The two
authorisations are kept apart at every other seam — ADR-0097 §7 forbids a source
grant from ever being cited as ``PermissionRuling.authorised_by`` — and one noun
over two records that cannot substitute for each other is how a user comes to
believe that revoking one revoked the other.

**Nothing a model steers reaches any of this** (ADR-0235 §4, ADR-0102 §8's shape).
No ``ToolDefinition`` binds these operations, no plan step reaches one, and no
model-authored value becomes an argument to one: the establishing act is a
decision of the user made while looking at a recorded call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import (
    DuplicateRecipientGrantError,
    InvalidRecipientGrantError,
    InvalidResolutionError,
    PermissionDeniedError,
    RecipientGrantCeilingError,
    RecipientGrantError,
    UngrantableActError,
)
from ai_assistant.core.types import (
    EgressBinding,
    PermissionDecision,
    PermissionOutcome,
    RecipientGrant,
    RecipientGrantNotEstablished,
    RecipientGrantOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from ai_assistant.core.protocols import ActionPolicy, AuditTrail, RecipientGrantStore
    from ai_assistant.core.types import PermissionRuling
    from ai_assistant.orchestration.runner import EstablishingAnswer

_log = structlog.get_logger(__name__)

#: How many trail rows :meth:`RecipientGrantOperations.establish_recipient_grant`
#: reads when it looks for a resolution of the confirmation it was named
#: (ADR-0235 §3's fourth condition).
#:
#: **A bound rather than an unbounded read**, because ADR-0235 §11 declines to mint
#: "a durable, filtered or indexed read of the permission trail" and ADR-0193's
#: neighbouring store makes the same refusal: the trail carries no read that
#: resolves "which decision answers this one" without a scan, and ``export`` is the
#: unbounded read of a Tier 1 store that ADR-0021 §4 keeps distinct from a listing.
#:
#: **Correctness does not rest on the window and that is the point.** ADR-0021 §1
#: and ADR-0044 §2b put the one-answer rule where it is really enforced —
#: :meth:`~ai_assistant.core.protocols.AuditTrail.record`, which refuses a
#: resolution where the trail already holds one naming the same ``CONFIRM`` — so a
#: resolution *older* than this window is caught by the append refusing, and
#: ADR-0235 §3's late-failure clause converts that refusal into the same
#: ``UngrantableActError`` the check would have raised. Nothing is recorded either
#: way. What the window buys is the ordinary case answered before a policy is
#: consulted at all.
_RESOLUTION_WINDOW: Final = 200


class RecipientGrantOperations:
    """The five recipient-grant operations, over one store, the trail and the policy."""

    def __init__(
        self,
        *,
        store: RecipientGrantStore,
        trail: AuditTrail,
        policy: ActionPolicy,
        id_factory: Callable[[], str],
        clock: Callable[[], datetime],
    ) -> None:
        """Wire the operations from the store, the trail, the policy, an id and a clock.

        Args:
            store: The append-only record of the recipients the user made standing.
                The **wide** seam, and this object is its only holder outside the
                composition root (ADR-0193 §1, ADR-0235 §4).
            trail: Where the confirmation is read from and the answer is recorded.
                Read and written through its Protocol, never through a concrete.
            policy: The gate that authors every ruling (ADR-0021 §3). This object
                composes no answer of its own: the policy rules, the trail records,
                ``core`` transcribes, and the store admits.
            id_factory: Mints each record's id — the answer's and the grant's — for
                :class:`~ai_assistant.orchestration.grants.GrantOperations`' reason:
                a store neither mints ids nor reads a clock, and a client supplying
                one would be minting into a write-once store.
            clock: Reads the instant of the call, and the instant an answer this
                object records carries. Injected for the same reason, and one
                sharper: a client's clock would backdate a user act.
        """
        self._store = store
        self._trail = trail
        self._policy = policy
        self._id_factory = id_factory
        self._clock = clock

    # --- the offerable rows (ADR-0235 §3) ------------------------------------

    async def grantable_decisions(self, *, limit: int) -> tuple[PermissionDecision, ...]:
        """Return the recorded ``CONFIRM``s an establishing act may ride.

        One window read and no second one: the availability conditions and the
        window-completeness rule are both answered from the rows
        :meth:`~ai_assistant.core.protocols.AuditTrail.recent` returned, which is
        what keeps this bounded by the same number that bounds the window (ADR-0235
        §3).

        **The clock is read exactly once** and every candidate's ``expires_at`` is
        compared against that one instant, on
        :meth:`~ai_assistant.core.protocols.RecipientGrantStore.standing`'s reason:
        a listing reading an advancing clock per row could offer one of two
        confirmations sharing an ``expires_at`` and withhold the other, which is a
        set true at no real instant.

        Args:
            limit: How many trail rows to read, already validated strictly positive
                by the caller.

        Returns:
            The offerable rows, most recent first, in the order the trail returned
            them.

        Raises:
            AuditError: If the trail could not be read.
            PlanningError: If the injected clock's reading is not conforming.
        """
        rows = await self._trail.recent(limit=limit)
        now = self._clock()
        # A resolution is at or after the confirmation it answers (`AuditTrail.record`
        # refuses one "decided *after* the resolution answering it"), so every
        # resolution of a candidate strictly newer than the oldest returned row is
        # itself inside this window. Collecting the pointers once is the whole join.
        resolved = {row.resolves for row in rows if row.resolves is not None}
        complete = len(rows) < limit
        oldest = rows[-1].decided_at if rows else None
        offerable = [
            row
            for row in rows
            if rides_an_establishing_act(row, now=now)
            and row.id not in resolved
            and (complete or oldest is None or row.decided_at > oldest)
        ]
        return tuple(offerable)

    # --- the act (ADR-0235 §3) -----------------------------------------------

    async def establish_recipient_grant(
        self, decision_id: str, *, expires_at: datetime
    ) -> RecipientGrant:
        """Answer a recorded ``CONFIRM`` no park holds, and record the grant it establishes.

        The seven availability conditions are checked in ADR-0235 §3's own order, so
        that where more than one fails the first is the one named and the refusal is
        deterministic across implementations. Every one of them raises
        :class:`~ai_assistant.core.errors.UngrantableActError` and **records
        nothing**.

        **The order of the four writes and reads is ADR-0235 §6's**: the policy
        rules, the answer is recorded, the grant is built from the two records by
        ``core``, and the store admits it. An answer the trail refuses leaves no
        grant, and a store refusal leaves the answer recorded — the trail is
        append-only and nothing retracts it.

        Args:
            decision_id: The recorded ``CONFIRM``, already validated and stripped by
                the caller (ADR-0085 §3c).
            expires_at: The instant the user chose, past which the grant ceases to
                be live.

        Returns:
            The grant the store accepted.

        Raises:
            UngrantableActError: If any of the seven conditions fails, at the check
                or late against the trail's own resolution invariant, or if the
                expiry is not strictly after the instant the answer will carry.
            PermissionDeniedError: If the policy answered other than an ``ALLOW``.
                That answer **is** recorded first.
            AuditError: If the trail could not be read, or refused the answer on a
                ground that is not a resolution recorded in the interval.
            InvalidRecipientGrantError: If the store refused the grant.
            RecipientGrantError: If the store could not be written.
            PlanningError: If the injected clock's reading is not conforming.
        """
        confirmed = await self._offerable(decision_id)
        ruling = await self._policy.resolve(confirmed.model_copy(deep=True), approved=True)
        answer = await self._record_answer(confirmed, ruling, expires_at=expires_at)
        if answer.ruling.outcome is not PermissionOutcome.ALLOW:
            # **Recorded and then refused, in that order** (ADR-0235 §3). Suppressing
            # the record would be the failure ADR-0042 §4's guarantee exists to
            # prevent, read one operation over: the policy ruled on a question the
            # user answered, and a ruling the trail never sees is a decision nobody
            # can audit. The confirmation is thereby settled, and §3's fourth
            # condition keeps the act from being offered on it again.
            msg = (
                f"the permission layer answered {answer.ruling.outcome} to this confirmation, so "
                f"no standing recipient grant was established; the answer is recorded as "
                f"decision {answer.id!r} and the confirmation is settled: {answer.ruling.reason}"
            )
            raise PermissionDeniedError(msg)
        grant = RecipientGrant.established_from(
            confirmed, answer, id=self._id_factory(), expires_at=expires_at
        )
        await self._store.record(grant)
        return grant

    async def establish_from_answer(
        self, establishing: EstablishingAnswer, *, expires_at: datetime
    ) -> RecipientGrantOutcome:
        """Perform the act a ``resume`` collected, and say what became of it.

        The population-(a) half, reached **after** the answer was recorded and the
        call executed — so nothing here raises and everything here is reported on
        the carrier (ADR-0235 §6). A raise at this point would report a failure for
        an egress nobody can un-send, and would discard the outcome the surface needs
        in order to say what that call did.

        **The three refusing members are read from the type of the refusal ``record``
        raised and from nothing else** (ADR-0235 §4, §11). No message is parsed, no
        count is taken, and no listing is read afterwards to work out which ground it
        was: a refusal carrying the base class is
        :attr:`~ai_assistant.core.types.RecipientGrantNotEstablished.REFUSED` and is
        never guessed at.

        **A store fault is not a refusal of the user's request.** A
        :class:`~ai_assistant.core.errors.RecipientGrantError` that is not an
        ``InvalidRecipientGrantError`` is caught here and rendered as
        :attr:`~ai_assistant.core.types.RecipientGrantNotEstablished.STORE_UNAVAILABLE`;
        the store wrote nothing, because ``record`` is atomic, so no grant stands
        from this act.

        Args:
            establishing: The confirmation and the recorded answer, as the runner
                read them back from the trail.
            expires_at: The instant the user chose. Strictly after the instant the
                answer carries, which the runner refused before it sought a ruling
                (ADR-0235 §1), so the constructor below cannot meet that refusal.

        Returns:
            The carrier, with exactly one arm set.
        """
        if establishing.answer.ruling.outcome is not PermissionOutcome.ALLOW:
            # The one member that never reaches the store (ADR-0235 §4): the resolving
            # ruling was not an `ALLOW`, so the answer is recorded, no grant could be
            # established from it, and `record` was not called at all.
            return RecipientGrantOutcome(not_established=RecipientGrantNotEstablished.DECLINED)
        grant = RecipientGrant.established_from(
            establishing.confirmed,
            establishing.answer,
            id=self._id_factory(),
            expires_at=expires_at,
        )
        return await record_the_grant(self._store, grant)

    def declined(self) -> RecipientGrantOutcome:
        """The carrier for an act whose answer never reached a ruling this could ride.

        A ``resume`` carrying ``remember_recipients_until`` beside
        ``approved=False`` records its ``DENY`` and calls nothing (ADR-0235 §2), so
        the store is never reached and there is no refusal to read a member off.
        Stated here rather than at the engine so that both roads to
        :attr:`~ai_assistant.core.types.RecipientGrantNotEstablished.DECLINED` — the
        declining answer and the policy ``DENY`` above — carry one value built in one
        place.
        """
        return RecipientGrantOutcome(not_established=RecipientGrantNotEstablished.DECLINED)

    # --- the listings and the revocation (ADR-0235 §7) -----------------------

    async def standing_recipient_grants(self) -> tuple[RecipientGrant, ...]:
        """Return every live grant, read from the store and from nothing else.

        Liveness is the store's, evaluated against one clock read (ADR-0193 §1, §9),
        and nothing here re-derives it: a caller that answered this by walking
        :meth:`recent_recipient_grants` would report a withdrawn grant as live the
        moment a clock moved backwards.

        **Complete or nothing**, which is the store's own obligation and the reason
        this takes no ``limit``: a truncated answer to "what do I authorise" is a
        false answer rather than a partial one.

        Raises:
            RecipientGrantError: If the store could not be read.
        """
        return tuple(await self._store.standing())

    async def recent_recipient_grants(self, *, limit: int) -> tuple[RecipientGrant, ...]:
        """Return the store's own history, newest first, granting and revoking alike.

        It evaluates **no liveness** and reads no clock: a record here says an act
        happened, never that it still stands (ADR-0235 §7).

        Args:
            limit: How many records to return, already validated strictly positive
                by the caller.

        Raises:
            RecipientGrantError: If the store could not be read.
        """
        return tuple(await self._store.recent(limit=limit))

    async def revoke_recipient_grant(self, grant_id: str) -> RecipientGrant | None:
        """Withdraw one outstanding grant, or report that there was none.

        The revoking record transcribes the outstanding record's ``tool``,
        ``account`` and ``destinations`` **by value**, so the record says what was
        withdrawn without a join and the store verifies the transcription (ADR-0193
        §1). Revocation is whole: nothing here narrows, re-scopes, extends or edits a
        grant in place.

        **A lost race returns ``None`` rather than raising** (ADR-0235 §7). Where
        ``record`` refuses the revoking record this built, the outstanding read is
        taken **again** and ``None`` is returned where the id is now absent — this
        method's own second branch reached late rather than a third outcome. The
        re-read is decisive because "this id is no longer outstanding" is
        **monotonic**: a revoked grant never becomes outstanding again, since
        re-granting an expired triple mints a *new* record with a new id. It is
        likewise the only ground that can newly become true between the read and the
        write — every other refusal of a revoking record is a stable property of the
        record this built or of a row it already read — so the error propagates
        unchanged wherever the grant is still outstanding.

        Args:
            grant_id: The id either listing renders, already validated and stripped.

        Returns:
            The revoking record that was appended, or ``None``.

        Raises:
            InvalidRecipientGrantError: If the store refused the revoking record on
                any ground other than the grant having been revoked in the interval.
            RecipientGrantError: If the store could not be read or written.
            PlanningError: If the injected clock's reading is not conforming.
        """
        outstanding = await self._store.outstanding(grant_id)
        if outstanding is None:
            return None
        record = RecipientGrant(
            id=self._id_factory(),
            tool=outstanding.tool,
            account=outstanding.account,
            destinations=outstanding.destinations,
            decided_at=self._clock(),
            expires_at=outstanding.expires_at,
            revokes=outstanding.id,
        )
        try:
            await self._store.record(record)
        except InvalidRecipientGrantError:
            if await self._store.outstanding(grant_id) is None:
                # **The user's recourse succeeded**: by the time this call completes
                # the store holds no outstanding granting record with that id, which
                # is exactly what `None` means here. ADR-0193 §1's "the recourse is
                # to revoke a grant they hold" would be undischarged by an operation
                # that failed spuriously on the one act the ceiling makes users
                # perform. Nothing is retried and no second revoking record is
                # appended.
                _log.info("recipient_grant_revocation_lost_a_race", grant_id=grant_id)
                return None
            raise
        return record

    # --- the availability check (ADR-0235 §3) --------------------------------

    async def _offerable(self, decision_id: str) -> PermissionDecision:
        """Read the named decision and refuse it unless all seven conditions hold.

        In ADR-0235 §3's stated order, so the refusal is deterministic where more
        than one fails. **No lane branches on the message.**

        Raises:
            UngrantableActError: If any condition fails.
            AuditError: If the trail could not be read.
            PlanningError: If the injected clock's reading is not conforming.
        """
        confirmed = await self._trail.get(decision_id)
        if confirmed is None:
            msg = (
                f"the permission trail holds no decision {decision_id!r}, so there is no "
                f"recorded confirmation for an establishing act to ride (ADR-0235 §3)"
            )
            raise UngrantableActError(msg)
        if confirmed.ruling.outcome is not PermissionOutcome.CONFIRM:
            msg = (
                f"decision {decision_id!r} ruled {confirmed.ruling.outcome} and was never shown "
                f"as a question, so an answer to it establishes nothing (ADR-0235 §3)"
            )
            raise UngrantableActError(msg)
        if confirmed.step_id is not None or confirmed.execution_id is not None:
            # **Structural rather than a rule to remember** (ADR-0235 §3). A
            # confirmation carrying either field belongs to a step of an execution;
            # its answer is the resuming one, which rebinds the call before it seeks
            # a ruling (ADR-0152 §7), and `resume` is the only door to it. No lane
            # reaches this operation from a park by clearing either field.
            msg = (
                f"decision {decision_id!r} belongs to a step of an execution, so a park holds "
                f"it and its answer rides resume rather than this operation (ADR-0235 §3)"
            )
            raise UngrantableActError(msg)
        resolution = await self._resolution_of(decision_id)
        if resolution is not None:
            msg = (
                f"decision {decision_id!r} was already answered by decision {resolution.id!r}; a "
                f"confirmation has one answer, so this one is spent and the next such call is "
                f"the one that may be made standing (ADR-0044 §2b, ADR-0235 §3)"
            )
            raise UngrantableActError(msg)
        now = self._clock()
        if confirmed.expires_at is not None and confirmed.expires_at <= now:
            msg = (
                f"decision {decision_id!r} stopped being answerable at "
                f"{confirmed.expires_at.isoformat()}, which is at or before "
                f"{now.isoformat()} (ADR-0059 §1, ADR-0235 §3)"
            )
            raise UngrantableActError(msg)
        binding = confirmed.egress_binding
        if not isinstance(binding, EgressBinding):
            # Stated over the binding's **type** and refused here rather than
            # inherited (ADR-0235 §3). `ActionPolicy.resolve` returns no `ALLOW` on
            # either unrecorded epoch, so the act could not complete in any case;
            # refusing before the policy is asked keeps the act from being offered on
            # a row it can never ride.
            msg = (
                f"decision {decision_id!r} records no egress call whose recipients could be "
                f"made standing, so there is no account and no destination set to transcribe "
                f"(ADR-0235 §3)"
            )
            raise UngrantableActError(msg)
        if binding.planned_with_external_content:
            # Refused **here** rather than left to the constructor, because the
            # constructor runs too late: `resolve` returns an `ALLOW` on an approved
            # confirmation carrying this, so an operation that checked nothing would
            # record the answer and only then meet `established_from`'s refusal
            # (ADR-0235 §3).
            msg = (
                f"decision {decision_id!r} records a call planned over external content; you "
                f"may approve such a call, and may not in that act make its recipients "
                f"standing (ADR-0193 §2, §4; ADR-0235 §3)"
            )
            raise UngrantableActError(msg)
        return confirmed

    async def _record_answer(
        self,
        confirmed: PermissionDecision,
        ruling: PermissionRuling,
        *,
        expires_at: datetime,
    ) -> PermissionDecision:
        """Stamp the answer, check the expiry against that instant, and append it.

        **One clock reading, used for both the comparison and the record** (ADR-0235
        §1). Two reads admit an expiry that passes the check and fails
        :meth:`~ai_assistant.core.types.RecipientGrant.established_from`'s
        constructor, which is the failure that clause exists to remove rather than
        to narrow.

        **The check is scoped to a ruling that is going to be an ``ALLOW``**, and it
        runs **after** the policy has ruled: where the ruling is anything else the
        answer is recorded exactly as it would be had no expiry been supplied at
        all, and the supplied instant is not consulted (ADR-0235 §1, §12).

        Raises:
            UngrantableActError: If the expiry is not strictly after the instant this
                answer would carry, or if a resolution of ``confirmed`` was recorded
                between the availability check and this append.
            AuditError: If the trail refused the answer on any other ground.
            PlanningError: If the injected clock's reading is not conforming.
        """
        decided_at = self._clock()
        if ruling.outcome is PermissionOutcome.ALLOW and expires_at <= decided_at:
            msg = (
                f"a standing recipient grant expires strictly after the answer that "
                f"establishes it; {expires_at.isoformat()} is at or before "
                f"{decided_at.isoformat()}, the instant this answer would carry, so nothing "
                f"was recorded and the confirmation may still be answered (ADR-0235 §1)"
            )
            raise UngrantableActError(msg)
        answer = PermissionDecision.from_confirmation(
            confirmed, ruling, id=self._id_factory(), decided_at=decided_at
        )
        try:
            await self._trail.record(answer)
        except InvalidResolutionError as exc:
            # **The fourth condition failing late** (ADR-0235 §3). A second caller
            # may resolve the same `CONFIRM` between the check above and this append,
            # and the trail's resolution invariant is where a confirmation's
            # one-answer rule is really enforced. The **read** decides it rather than
            # the class, because `InvalidResolutionError` is one class over seven
            # grounds and no lane branches on its message; six of the seven are
            # closed by construction on this operation, which is why the read finds
            # the seventh and nothing else.
            #
            # The re-read is decisive here for a reason a listing read after an act
            # would not be: the trail is append-only and write-once, so "a resolution
            # of this confirmation exists" is **monotonic** — once true it stays
            # true — and a resolution recorded during the interval is newer than
            # every row the first read returned, so it is inside any window of at
            # least one row and the window-completeness rule does not arise.
            if await self._resolution_of(confirmed.id) is None:
                # A fault is not a settled decision, and converting one into the
                # other would hide it.
                raise
            msg = (
                f"decision {confirmed.id!r} was answered while this act was being performed; a "
                f"confirmation has one answer, so this one is spent, nothing was recorded here "
                f"and the next such call is the one that may be made standing (ADR-0235 §3)"
            )
            raise UngrantableActError(msg) from exc
        return answer

    async def _resolution_of(self, decision_id: str) -> PermissionDecision | None:
        """The decision resolving ``decision_id`` within the window, or ``None``.

        A scan of :data:`_RESOLUTION_WINDOW` rows rather than an indexed read,
        because ADR-0235 §11 mints no filtered read of the trail and
        :meth:`~ai_assistant.core.protocols.AuditTrail.resolution_of` answers only
        for a decision carrying **both** an ``execution_id`` and a ``step_id``,
        which this population carries neither of (ADR-0235 §3's third condition).
        """
        rows: Sequence[PermissionDecision] = await self._trail.recent(limit=_RESOLUTION_WINDOW)
        return next((row for row in rows if row.resolves == decision_id), None)


async def record_the_grant(
    store: RecipientGrantStore, grant: RecipientGrant
) -> RecipientGrantOutcome:
    """Append ``grant`` and read the carrier off the refusal's own type (ADR-0235 §4).

    **The mapping is by type and by nothing else.** No message is parsed, no count
    is taken, and no listing is read after the refusal to work out which ground it
    was (ADR-0235 §11): a refusal carrying the base
    :class:`~ai_assistant.core.errors.InvalidRecipientGrantError` is
    :attr:`~ai_assistant.core.types.RecipientGrantNotEstablished.REFUSED` and is
    never guessed at, and a
    :class:`~ai_assistant.core.errors.RecipientGrantError` that is not a refusal at
    all is
    :attr:`~ai_assistant.core.types.RecipientGrantNotEstablished.STORE_UNAVAILABLE`
    — the store wrote nothing, because ``record`` is atomic, and a surface reporting
    a disk fault as a refusal would tell the user their request was declined when it
    was not.

    **One implementation of the mapping and never two.** The canonical fake engine
    reaches for this rather than restating it, on the reasoning ADR-0087 §7 states
    for the payload encoder: a second copy would let a consumer's tests certify
    against a hub that reports a different member for the same refusal.

    The clause order below is the subclass order, so the two discriminators are
    caught before the base class they narrow.

    Args:
        store: The store to append to.
        grant: The granting record ``established_from`` returned.

    Returns:
        The carrier, with exactly one arm set.
    """
    try:
        await store.record(grant)
    except RecipientGrantCeilingError:
        _log.info("recipient_grant_ceiling_reached", grant_id=grant.id)
        return RecipientGrantOutcome(not_established=RecipientGrantNotEstablished.CEILING_REACHED)
    except DuplicateRecipientGrantError:
        _log.info("recipient_grant_already_standing", grant_id=grant.id)
        return RecipientGrantOutcome(not_established=RecipientGrantNotEstablished.ALREADY_STANDING)
    except InvalidRecipientGrantError:
        _log.info("recipient_grant_refused", grant_id=grant.id, exc_info=True)
        return RecipientGrantOutcome(not_established=RecipientGrantNotEstablished.REFUSED)
    except RecipientGrantError:
        _log.warning("recipient_grant_store_unavailable", grant_id=grant.id, exc_info=True)
        return RecipientGrantOutcome(not_established=RecipientGrantNotEstablished.STORE_UNAVAILABLE)
    return RecipientGrantOutcome(established=grant)


def rides_an_establishing_act(decision: PermissionDecision, *, now: datetime) -> bool:
    """Whether ``decision`` meets every availability condition decidable from the row.

    ADR-0235 §3's conditions two, three, five, six and seven. The first is true of
    every row the trail returned, and the fourth is decided over the window rather
    than over one row (:meth:`RecipientGrantOperations.grantable_decisions`).

    Args:
        decision: One row of the trail's window.
        now: The one clock reading the whole window is judged against.

    Returns:
        Whether an establishing act may ride this row.
    """
    if decision.ruling.outcome is not PermissionOutcome.CONFIRM:
        return False
    if decision.step_id is not None or decision.execution_id is not None:
        return False
    if decision.expires_at is not None and decision.expires_at <= now:
        return False
    binding = decision.egress_binding
    return isinstance(binding, EgressBinding) and not binding.planned_with_external_content


__all__ = [
    "RecipientGrantOperations",
    "record_the_grant",
    "rides_an_establishing_act",
]
