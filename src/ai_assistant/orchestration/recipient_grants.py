"""The recipient-grant operations: the listings and revocation.

ADR-0235 §4 put five operations on
:class:`~ai_assistant.core.protocols.AssistantEngine`, of which ADR-0313 §5:1 took
the establishing act and its listing off the surface, and §12 rules that the
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

from typing import TYPE_CHECKING

import structlog

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    DuplicateRecipientGrantError,
    InvalidRecipientGrantError,
    PlanningError,
    RecipientGrantCeilingError,
    RecipientGrantError,
)
from ai_assistant.core.types import (
    PermissionOutcome,
    RecipientGrant,
    RecipientGrantNotEstablished,
    RecipientGrantOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from ai_assistant.core.protocols import ActionPolicy, AuditTrail, RecipientGrantStore
    from ai_assistant.orchestration.parked_reads import ParkedReadOperations
    from ai_assistant.orchestration.runner import EstablishingAnswer

_log = structlog.get_logger(__name__)


class RecipientGrantOperations:
    """The three recipient-grant operations over one store, and the old path's act."""

    def __init__(  # noqa: PLR0913 — one parameter per contract these operations are answered against; ADR-0244 §5's eighth condition adds the sixth and none is derivable from another
        self,
        *,
        store: RecipientGrantStore,
        trail: AuditTrail,
        policy: ActionPolicy,
        id_factory: Callable[[], str],
        clock: Callable[[], datetime],
        parked_reads: ParkedReadOperations | None = None,
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
                sharper: a client's clock would backdate a user act. **Guarded at
                the moment it is stored** (ADR-0026 §2), which is where
                :func:`~ai_assistant.core.clock.checked_clock` says to put it — "a
                call site cannot forget" — so every reading below is aware, UTC and
                localizable rather than checked three times or not at all.
            parked_reads: ADR-0244's parked-read operations, which is where §5's
                **eighth** availability condition is decided from, or ``None`` where
                this deployment wires no parked-read store. **Read through the
                ``ParkedReads`` contract and never from a concrete store** (golden
                rule 1), which is why the member is on that contract rather than left
                to an implementation — and why the exclusion survives a restart: the
                row does, so the read does.

                ``None`` excludes nothing, which is exactly right where no park can
                exist: ADR-0244 §18's lane order lands the store in Lane 2, and until
                it does no decision is one a park names.

        **``trail``, ``policy`` and ``parked_reads`` are no longer read.** The
        establishing act and its listing were their only readers, and both left the
        engine surface (ADR-0313 §5:1); the parameters stay until the composition root
        stops passing them.
        """
        self._store = store
        self._trail = trail
        self._policy = policy
        self._id_factory = id_factory
        self._clock = checked_clock(clock, owner="RecipientGrantOperations")
        self._parked_reads = parked_reads

    # --- the act (ADR-0235 §3) -----------------------------------------------

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
            decided_at=self._now(),
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

    def _now(self) -> datetime:
        """The guarded clock's reading, as the reading stage's own error.

        ``core/errors.py`` defines no error for `orchestration`, so ADR-0026 §4 gives
        the failure to the **stage**: this is :meth:`StepRunner._now`'s translation,
        one seam over, and it is what makes the ``PlanningError`` each operation's
        docstring declares true rather than aspirational.

        **The guard covers the reading and not the invocation** (ADR-0026 §2). An
        exception the injected callable raises *itself* propagates unwrapped —
        that is the clock's own failure, already carrying its own type and cause —
        and only a :class:`~ai_assistant.core.clock.ClockReadingError` is
        translated, which is why that class is distinct from a bare ``ValueError``.

        Raises:
            PlanningError: If the injected clock's reading is not a conforming one —
                naive, indeterminate, or outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            msg = f"the recipient-grant operations' clock returned a non-conforming reading: {exc}"
            raise PlanningError(msg) from exc


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


__all__ = [
    "RecipientGrantOperations",
    "record_the_grant",
]
