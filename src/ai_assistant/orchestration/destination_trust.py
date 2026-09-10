"""The destination-trust operations: the act, the standing listing, revocation.

ADR-0242 §2 puts **three** operations on
:class:`~ai_assistant.core.protocols.AssistantEngine` and §13 rules that the
implementing lane lands the engine members with the store's face reaching
``Engine`` from ``app/composition.py``. This module is the object that holds that
face, on :class:`~ai_assistant.orchestration.recipient_grants.RecipientGrantOperations`'
shape and for its reason: the operations must be ``AssistantEngine`` methods to be
addressable over the socket at all, ``AssistantEngine`` is provided by
`orchestration`, and the engine delegates rather than growing a store of its own.

**Three operations and not five** (ADR-0242 §2). There is no ``trustable_decisions``
read, because ADR-0242 §1's availability set is three conditions wide and
``grantable_decisions``' own rows already satisfy every one of them a user is looking
at; and there is no history read beside the standing one, because a trust record has
**no ceiling and no expiry**, so a record that is not live has been revoked and needs
no act.

**This object and ``app/composition.py`` are the only holders of a**
:class:`~ai_assistant.core.protocols.DestinationTrustStore` **face outside the one
servicing site ADR-0238 §14 wires** (ADR-0242 §2). No ``interfaces`` adapter holds
it: a surface is given records by the operations here and reads no store, which is
golden rule 3 and what ``uv run lint-imports`` keeps true.

**Destination trust and recipient grants are two vocabularies and never one**
(ADR-0242 §4). Nothing here reads, writes or consults a
:class:`~ai_assistant.core.protocols.RecipientGrantStore`, and
:mod:`ai_assistant.orchestration.recipient_grants` consults nothing here. The two
acts are separate and neither implies the other (ADR-0238 §1), so no operation here
answers the other's question, presents a trust record among grants, or offers a
control that revokes across both.

**The act records no** :class:`~ai_assistant.core.types.PermissionDecision`, **seeks
no ruling from** :class:`~ai_assistant.core.protocols.ActionPolicy` **and emits no
audit event** (ADR-0242 §11). It sends nothing, so there is no egress to rule on and
nothing for the permission trail to hold; the record itself is the audit, and
``DestinationTrustStore.export`` is what answers every stored record, revoked ones
included.

**Nothing a model steers reaches any of it** (ADR-0242 §1, ADR-0102 §8's shape). No
``ToolDefinition`` binds these operations, no plan step reaches one, and no
model-authored value becomes an argument to one: the act is a decision of the user
made while looking at a recorded call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import PlanningError, UntrustableDestinationError
from ai_assistant.core.types import (
    DestinationTrust,
    DestinationTrustRecord,
    EgressBinding,
    describe_untrusted,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from ai_assistant.core.protocols import AuditTrail, DestinationTrustStore


class DestinationTrustOperations:
    """The three destination-trust operations, over one store and the trail."""

    def __init__(
        self,
        *,
        store: DestinationTrustStore,
        trail: AuditTrail,
        id_factory: Callable[[], str],
        clock: Callable[[], datetime],
    ) -> None:
        """Wire the operations from the store, the trail, an id factory and a clock.

        Args:
            store: What the user recorded about destinations (ADR-0238 §1). The
                **wide** face, held here and by ``app/composition.py`` alone outside
                the one servicing site: a component handed it is one ``record`` call
                away from authorising the composition it is about to make.
            trail: Where the decision the act rides is read from. Read through its
                Protocol, never through a concrete, and **never written** — this act
                records no decision and seeks no ruling (ADR-0242 §11).
            id_factory: Mints the record's id, for
                :class:`~ai_assistant.orchestration.recipient_grants.RecipientGrantOperations`'
                reason: a store neither mints ids nor reads a clock, and a client
                supplying one would be minting into a write-once store.
            clock: Reads the instant of the user's act. Injected for the same reason
                and one sharper: a client's clock would backdate a user act.
                **Guarded at the moment it is stored** (ADR-0026 §2), so every
                reading below is aware, UTC and localizable.
        """
        self._store = store
        self._trail = trail
        self._id_factory = id_factory
        self._clock = checked_clock(clock, owner="DestinationTrustOperations")

    # --- the act (ADR-0242 §1) -----------------------------------------------

    async def establish_destination_trust(self, decision_id: str) -> DestinationTrustRecord:
        """Record the user's choice over a recorded decision's destinations (§1).

        The three availability conditions are checked in ADR-0242 §1's own order, so
        that where more than one fails the first is the one named and the refusal is
        deterministic across implementations. Every one of them raises
        :class:`~ai_assistant.core.errors.UntrustableDestinationError` and **writes
        nothing to any store**.

        **The destination set is transcribed from the binding by value**, from
        ``core``'s own derivation and never re-derived here: nothing in this method
        parses a host, builds a
        :class:`~ai_assistant.core.types.CanonicalDestination` or constructs a set of
        its own, and there is no parameter through which a caller could substitute
        one.

        Args:
            decision_id: The recorded decision, already validated and stripped by the
                caller (ADR-0085 §3c).

        Returns:
            The record the store accepted — the very value that was built, so the
            caller sees the id and the instant that were recorded.

        Raises:
            UntrustableDestinationError: If any of the three conditions fails.
            DuplicateDestinationTrustError: If a live record already names this
                destination set (ADR-0242 §2).
            InvalidDestinationTrustError: If the store refused the record on any other
                ground, or could not be written.
            AuditError: If the trail could not be read.
            PlanningError: If the injected clock's reading is not conforming.
        """
        decision = await self._trail.get(decision_id)
        if decision is None:
            msg = (
                f"no decision {describe_untrusted(decision_id)} is recorded, so there is no "
                f"destination set to transcribe and nothing was recorded (ADR-0242 §1)"
            )
            raise UntrustableDestinationError(msg)
        binding = decision.egress_binding
        if not isinstance(binding, EgressBinding):
            msg = (
                f"decision {decision_id!r} records no whole egress binding, so the destination "
                f"set this act would be over is not on the row; nothing was recorded "
                f"(ADR-0242 §1)"
            )
            raise UntrustableDestinationError(msg)
        if binding.planned_with_external_content:
            # §1's third condition, and the one this act keeps of ADR-0235 §3's seven.
            # Trust is what closes ADR-0238 §5's loop, so trusting a destination a model
            # reached *from* external content is the loop closing on itself — an injected
            # page names a destination, the call to it is refused and recorded, and the
            # recorded row is then offered to the user as something to trust. It is cut
            # here rather than at the store because `record` does not consult a binding
            # and could not: ADR-0238 §1's five fields carry no tool, no account and no
            # call.
            msg = (
                f"decision {decision_id!r} records a call planned over recorded external "
                f"content, and trust recorded from such a call is the loop closing on itself; "
                f"nothing was recorded (ADR-0242 §1)"
            )
            raise UntrustableDestinationError(msg)
        record = DestinationTrustRecord(
            # The id and the instant are the engine's, as `RecipientGrant`'s are
            # (ADR-0193 §1), so the record is a complete value before it reaches any
            # store and the store's duplicate refusal is a comparison rather than an
            # allocation. `trust` is `USER_CHOSEN` because ADR-0238 §1 refuses a record
            # asserting anything else at construction, and there is no argument here
            # through which a caller could ask for the other member.
            id=self._id_factory(),
            destinations=binding.canonical_destination_set,
            trust=DestinationTrust.USER_CHOSEN,
            established_at=self._now(),
        )
        await self._store.record(record)
        return record

    # --- listing and revocation (ADR-0242 §4) --------------------------------

    async def standing_destination_trust(self) -> tuple[DestinationTrustRecord, ...]:
        """Every live trust record, in the store's own order (§4).

        One read and no second one: this composes, filters, projects, enriches and
        summarises nothing, and reads no other store. **No ``limit``**, for
        ``standing_recipient_grants``' stated reason — a truncated answer to "what do
        I trust" is a false answer rather than a partial one.

        Returns:
            Every record the store holds live.

        Raises:
            InvalidDestinationTrustError: If the store could not be read.
        """
        return tuple(await self._store.live())

    async def revoke_destination_trust(self, record_id: str) -> bool:
        """Withdraw one live record, or answer that none carried that id (§4).

        Args:
            record_id: The id the standing listing renders, already validated and
                stripped by the caller.

        Returns:
            ``True`` where a live record carried the id and ``revoke`` was called for
            it, ``False`` where none did — in which case nothing was written.

        Raises:
            InvalidDestinationTrustError: If the store could not be read or written.
            PlanningError: If the injected clock's reading is not conforming.
        """
        live = await self._store.live()
        if not any(held.id == record_id for held in live):
            return False
        # **The loser of a concurrent revocation is not told a falsehood** (§4). Both
        # callers may find the record live and both call `revoke`; ADR-0238 §1 makes
        # that member prospective and idempotent, so the second changes nothing. The
        # clock is read here, after the match, so the instant recorded is the instant
        # of the act rather than of the read that preceded it. Nothing is retried and
        # no error is converted into `False`: ADR-0238 §1's unknown-id refusal is not
        # reachable after a live match, so an `InvalidDestinationTrustError` from here
        # is a store fault and propagates as one.
        await self._store.revoke(record_id, self._now())
        return True

    def _now(self) -> datetime:
        """The guarded clock's reading, as the reading stage's own error.

        ``core/errors.py`` defines no error for `orchestration`, so ADR-0026 §4 gives
        the failure to the **stage**, exactly as
        :meth:`~ai_assistant.orchestration.recipient_grants.RecipientGrantOperations._now`
        does one act over.

        Raises:
            PlanningError: If the injected clock's reading is not a conforming one —
                naive, indeterminate, or outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            msg = (
                f"the destination-trust operations' clock returned a non-conforming reading: {exc}"
            )
            raise PlanningError(msg) from exc


__all__ = ["DestinationTrustOperations"]
