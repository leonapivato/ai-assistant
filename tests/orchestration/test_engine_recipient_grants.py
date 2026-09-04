"""The held population: the act rides ``resume`` (ADR-0235 §1, §2, §6).

Population (a) is a confirmation a park holds, so the act is an act **on work**:
the answer both authorises the call and, in the same call, may make its recipients
standing. Everything here is driven through the real engine over a real
``StepRunner`` and a real park, because the clauses under test are about *when*
things happen relative to a ruling, a record and a send — which a fake engine's
resume cannot exhibit.

The recorded population is ``test_recipient_grant_operations.py``. The two are
separate modules because ADR-0235 §3 makes them separate doors: "answering (a) is
an act on work; answering (b) is an act on a record".
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

import pytest
from test_engine import (
    AT,
    PATIENT,
    Harness,
    _external_belief,
    bound_binder,
    confirmable,
    egress_confirmable,
)

from ai_assistant.core.errors import (
    InvalidRecipientGrantError,
    RecipientGrantError,
    UngrantableActError,
)
from ai_assistant.core.types import (
    ActionRequest,
    CanonicalDestination,
    ContinuationToken,
    DestinationProtocol,
    Disposition,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    RecipientGrant,
    RecipientGrantNotEstablished,
    StepStatus,
    TurnOutcome,
)
from ai_assistant.testing import FakeActionPolicy, FakeRecipientGrantStore
from ai_assistant.testing.recipient_grants import recipient_grant

#: When the store reads the clock. Inside every grant this module establishes, so
#: a case about liveness has to move it rather than inherit an accident.
_NOW: Final = AT + timedelta(hours=1)

#: The instant the user chooses, comfortably after the answer's own — which the
#: runner stamps at :data:`AT`, so ADR-0235 §1's refusal is never brushed by a case
#: that is not about it.
_UNTIL: Final = AT + timedelta(days=1)


#: The utterance every turn here is driven with. It carries the terms
#: :func:`_external_belief`'s content carries, so the store's lexical search selects
#: that record on the one case that seeds it — and selects nothing on the rest.
_ASK: Final = "send it to the address in the invite"


def _harness(*, store: FakeRecipientGrantStore | None = None) -> Harness:
    """An engine whose one confirmable tool is bound to a connected account."""
    definition = egress_confirmable()
    return Harness(
        tools=(definition,),
        binder=bound_binder(definition),
        recipient_grants=(FakeRecipientGrantStore(now=lambda: _NOW) if store is None else store),
    )


async def _parked(harness: Harness) -> ContinuationToken:
    """Drive a turn to a parked egress confirmation and hand back its token."""
    parked = await harness.engine.converse(_ASK, timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    return parked.step.confirmation.token


async def _resolutions(harness: Harness) -> list[PermissionOutcome]:
    """The outcomes of every **resolving** decision the trail holds, oldest first."""
    return [
        row.ruling.outcome
        for row in reversed(await harness.trail.export())
        if row.resolves is not None
    ]


# --- §12: the opt-in pair ----------------------------------------------------


async def test_approving_without_asking_leaves_the_grant_store_empty() -> None:
    """ADR-0235 §12's opt-in pair, the half that is the ordinary outcome.

    ADR-0193 §2 assigns this pair to the lane landing the first establishing
    surface, on both populations: a user who approves a call and asks for nothing
    standing leaves the answer recorded and the grant store **empty**. Nothing about
    the control arrives pre-selected, and the absence is what says so.
    """
    harness = _harness()
    token = await _parked(harness)

    resumed = await harness.engine.resume(token, approved=True, timeout=PATIENT)

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    assert resumed.recipient_grant is None
    assert await harness.recipient_grants.export() == []


async def test_approving_and_asking_leaves_exactly_one_grant() -> None:
    """The other half: asking for it standing leaves **exactly one** grant.

    And the ordering pair with it (§12), asserted over the **store's contents**
    rather than over what the call returned: the grant is recorded only after
    ``AuditTrail.record`` has accepted the answer, so the answer is in the trail and
    the grant's ``established_by`` names the confirmation the answer resolved.
    """
    harness = _harness()
    token = await _parked(harness)

    resumed = await harness.engine.resume(
        token, approved=True, timeout=PATIENT, remember_recipients_until=_UNTIL
    )

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    assert await _resolutions(harness) == [PermissionOutcome.ALLOW]
    held = await harness.recipient_grants.export()
    assert len(held) == 1
    assert resumed.recipient_grant is not None
    assert resumed.recipient_grant.established == held[0]
    assert held[0].expires_at == _UNTIL
    answered = [row for row in await harness.trail.export() if row.resolves is not None]
    assert held[0].established_by == answered[0].resolves
    assert held[0].decided_at == answered[0].decided_at


# --- §2: the binding refusal, on all four shapes -----------------------------


async def test_a_confirmation_carrying_no_egress_refuses_the_act_and_stays_parked() -> None:
    """ADR-0235 §12's binding refusal, on the arm a roster would omit.

    The ``None`` arm is the one that would otherwise record an ``ALLOW`` and **send
    the call** before ``established_from`` refused a binding that is not there. So
    the assertion is that no ruling was sought, no answer recorded and nothing
    executed — and that the same token then answers the confirmation without the
    argument, which is what "the step stays durably parked and answerable" means.
    """
    harness = Harness(tools=(confirmable(),), recipient_grants=FakeRecipientGrantStore())
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    token = parked.step.confirmation.token

    with pytest.raises(UngrantableActError, match="recipients could be made standing"):
        await harness.engine.resume(
            token, approved=True, timeout=PATIENT, remember_recipients_until=_UNTIL
        )

    assert await _resolutions(harness) == []
    assert await harness.recipient_grants.export() == []
    assert len(await harness.engine.pending_confirmations()) == 1

    resumed = await harness.engine.resume(token, approved=True, timeout=PATIENT)

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED


async def test_a_confirmation_planned_over_external_content_refuses_the_act() -> None:
    """The fourth shape §2 refuses, and the one a lane would remember on its own.

    A user answering such a confirmation **may approve the call**; what they may not
    do, in that act, is make its recipients standing (ADR-0193 §2, §4). So the
    refusal is of the *act* and never of the answer, and the step is left answerable.
    """
    harness = _harness()
    await harness.memory.add(_external_belief())
    token = await _parked(harness)

    with pytest.raises(UngrantableActError, match="external content"):
        await harness.engine.resume(
            token, approved=True, timeout=PATIENT, remember_recipients_until=_UNTIL
        )

    assert await _resolutions(harness) == []
    assert await harness.recipient_grants.export() == []

    resumed = await harness.engine.resume(token, approved=True, timeout=PATIENT)

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED


# --- §1: the expiry refusal, and its scope -----------------------------------


async def test_an_expiry_at_the_answers_instant_records_nothing_and_leaves_the_park() -> None:
    """ADR-0235 §12's expiry pair on the held population.

    The refusal fires **before any ruling is sought** (§6), so the trail holds no
    answer, the step is not executed, and the same token answers it afterwards. It
    fails against an implementation that let ``RecipientGrant``'s own validator do
    the refusing — the outcome §1's clause forbids, which records the answer, sends
    the call, and only then finds there is no grant.
    """
    harness = _harness()
    token = await _parked(harness)

    with pytest.raises(UngrantableActError, match="expires strictly after"):
        await harness.engine.resume(
            token, approved=True, timeout=PATIENT, remember_recipients_until=AT
        )

    assert await _resolutions(harness) == []
    assert await harness.recipient_grants.export() == []

    resumed = await harness.engine.resume(
        token, approved=True, timeout=PATIENT, remember_recipients_until=_UNTIL
    )

    assert resumed.recipient_grant is not None
    assert resumed.recipient_grant.established is not None


async def test_an_expiry_at_the_answers_instant_beside_a_decline_records_the_deny() -> None:
    """ADR-0235 §12's scoping pair, the held half, and it is the arm a roster omits.

    §1's check is scoped to an answer that is going to be an ``ALLOW``, so an expiry
    the check would refuse is **not consulted** beside ``approved=False``: the
    ``DENY`` is recorded exactly as a ``resume`` without the argument records it,
    which is ADR-0042 §4's guarantee preserved whole. Asserted over the trail's
    contents, so it fails against an implementation that validated the expiry before
    the answer's ruling was known.
    """
    harness = _harness()
    token = await _parked(harness)

    resumed = await harness.engine.resume(
        token, approved=False, timeout=PATIENT, remember_recipients_until=AT
    )

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.DENIED
    assert await _resolutions(harness) == [PermissionOutcome.DENY]
    assert await harness.recipient_grants.export() == []
    assert resumed.recipient_grant is not None
    assert resumed.recipient_grant.not_established is RecipientGrantNotEstablished.DECLINED


# --- §2: the two non-establishing answers ------------------------------------


async def test_a_declining_answer_records_its_deny_and_establishes_nothing() -> None:
    """ADR-0235 §12's pair separating §2's two non-establishing answers.

    Supplied beside ``approved=False`` the argument establishes nothing and changes
    nothing else. The comparison is against a ``resume`` **without** the argument
    over the same arrangement, which is what makes "exactly as" an assertion rather
    than a claim.
    """
    with_argument = _harness()
    without = _harness()

    denied = await with_argument.engine.resume(
        await _parked(with_argument),
        approved=False,
        timeout=PATIENT,
        remember_recipients_until=_UNTIL,
    )
    plain = await without.engine.resume(await _parked(without), approved=False, timeout=PATIENT)

    assert denied.step is not None
    assert plain.step is not None
    assert denied.step.disposition is plain.step.disposition is Disposition.DENIED
    assert await _resolutions(with_argument) == await _resolutions(without)
    assert await with_argument.recipient_grants.export() == []
    assert denied.recipient_grant is not None
    assert denied.recipient_grant.not_established is RecipientGrantNotEstablished.DECLINED
    assert plain.recipient_grant is None


# --- §6: the ceiling on the held population ----------------------------------


def _member(canonical: str) -> CanonicalDestination:
    """One selected-recipient member, for the arrangement below."""
    return CanonicalDestination(protocol=DestinationProtocol.SMTP, canonical=canonical)


async def _at_the_ceiling() -> tuple[Harness, FakeRecipientGrantStore]:
    """A harness whose store is at its ceiling, held by an **expired** grant.

    Expired and unrevoked, so it occupies its slot and appears in no standing
    listing — which is what makes the case fail against an implementation that
    counted the live set instead, the substitution ADR-0235 §6 forbids.
    """
    store = FakeRecipientGrantStore(now=lambda: AT + timedelta(days=30), max_outstanding=1)
    await store.record(recipient_grant(_member("held@example.com"), grant_id="g-held"))
    assert await store.standing() == []
    return _harness(store=store), store


async def test_a_ceiling_refusal_executes_the_call_and_returns_its_outcome() -> None:
    """ADR-0235 §12's ceiling arm for population (a), and it is the shape §6 chose.

    ``resume`` **returns** the ``TurnOutcome`` for the call it approved and executed
    and raises nothing: by the time ``record`` is asked the egress has gone out, so a
    raise would report a failure for a call nobody can un-send while discarding the
    outcome the surface needs in order to say what that call did. The outcome carries
    ``CEILING_REACHED`` and no ``established``, over a grant store left unchanged.
    """
    harness, store = await _at_the_ceiling()
    token = await _parked(harness)

    resumed = await harness.engine.resume(
        token, approved=True, timeout=PATIENT, remember_recipients_until=_UNTIL
    )

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    assert resumed.step.state.step("step-1").status is StepStatus.SUCCEEDED  # type: ignore[union-attr]
    assert resumed.recipient_grant is not None
    assert resumed.recipient_grant.established is None
    assert resumed.recipient_grant.not_established is RecipientGrantNotEstablished.CEILING_REACHED
    assert [record.id for record in await store.export()] == ["g-held"]
    assert await _resolutions(harness) == [PermissionOutcome.ALLOW]


async def test_a_ceiling_refusal_settles_the_park_and_the_token_restates() -> None:
    """ADR-0235 §12's settlement arm on population (a).

    The park is resolved with the answer, so the same token yields ADR-0198 §1's
    **restatement** rather than a second answerable park: revoking a grant frees a
    slot but does not reopen this act. It fails against an implementation that left
    the confirmation offerable, which is the one whose surface would invite the retry
    §6 forbids it to promise.
    """
    harness, _ = await _at_the_ceiling()
    token = await _parked(harness)
    await harness.engine.resume(
        token, approved=True, timeout=PATIENT, remember_recipients_until=_UNTIL
    )

    restated = await harness.engine.resume(token, approved=True, timeout=PATIENT)

    assert restated.turn is None
    assert restated.step is not None
    assert restated.step.disposition is Disposition.EXECUTED
    assert restated.recipient_grant is None
    assert await _resolutions(harness) == [PermissionOutcome.ALLOW]


# --- §4, §11: the carrier, and the mapping by type ---------------------------


async def test_a_duplicate_subject_carries_already_standing() -> None:
    """The mapping is **by type**: the duplicate-subject refusal is its own member.

    Arranged by establishing once and then answering a second identical call, so
    what produces the refusal is the store's own duplicate-subject rule rather than
    an error a test handed in.
    """
    harness = _harness()
    first = await harness.engine.resume(
        await _parked(harness), approved=True, timeout=PATIENT, remember_recipients_until=_UNTIL
    )
    assert first.recipient_grant is not None
    assert first.recipient_grant.established is not None

    second = await harness.engine.resume(
        await _parked(harness), approved=True, timeout=PATIENT, remember_recipients_until=_UNTIL
    )

    assert second.recipient_grant is not None
    assert second.recipient_grant.not_established is RecipientGrantNotEstablished.ALREADY_STANDING
    assert len(await harness.recipient_grants.export()) == 1


async def test_a_store_fault_carries_store_unavailable_and_never_raises() -> None:
    """ADR-0235 §12's store-fault pair, the population-(a) half.

    After the step has executed, ``resume`` **returns** its ``TurnOutcome`` carrying
    ``STORE_UNAVAILABLE`` and raises nothing, and the answer stays recorded. It fails
    against an implementation that let the store fault propagate and destroy the
    outcome of an egress that had already gone out — and the member asserted is not
    ``REFUSED``, which is the misreport ADR-0235 §4 names: a surface reporting a disk
    fault as a refusal tells the user their request was declined when it was not.
    """
    store = FakeRecipientGrantStore(now=lambda: _NOW)
    harness = _harness(store=store)
    token = await _parked(harness)
    store.fail_writes(RecipientGrantError("the disk went away"))

    resumed = await harness.engine.resume(
        token, approved=True, timeout=PATIENT, remember_recipients_until=_UNTIL
    )

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    assert resumed.recipient_grant is not None
    assert resumed.recipient_grant.not_established is RecipientGrantNotEstablished.STORE_UNAVAILABLE
    assert await _resolutions(harness) == [PermissionOutcome.ALLOW]


async def test_a_grant_already_expired_at_the_read_still_carries_established() -> None:
    """ADR-0235 §12's arm that would have passed against the rejected draft.

    An expiry ADR-0193 §1 admits an **instant after the answer** records a grant that
    is already not live when ``standing_recipient_grants`` is read. The carrier says
    ``established``; the listing is empty. That is the case that makes a read-back
    indistinguishable from a ceiling refusal, and it is why §6 gives the act a
    channel of its own.
    """
    store = FakeRecipientGrantStore(now=lambda: AT + timedelta(days=30))
    harness = _harness(store=store)
    token = await _parked(harness)

    resumed = await harness.engine.resume(
        token,
        approved=True,
        timeout=PATIENT,
        remember_recipients_until=AT + timedelta(microseconds=1),
    )

    assert resumed.recipient_grant is not None
    assert resumed.recipient_grant.established is not None
    assert await harness.engine.standing_recipient_grants() == ()


# --- §4: every call that collected no act carries ``None`` -------------------


async def test_a_turn_that_collected_no_act_carries_no_carrier() -> None:
    """``recipient_grant`` is ``None`` on every ``converse`` (ADR-0235 §4)."""
    harness = _harness()

    parked = await harness.engine.converse("send it", timeout=PATIENT)

    assert parked.recipient_grant is None


async def test_a_restatement_carries_no_carrier() -> None:
    """ADR-0198 §1's restatement drives nothing, so it establishes nothing (§4).

    It adds a value to ADR-0198 §2's enumeration without changing any value that
    clause fixes: ``turn``, ``routed``, ``reply``, ``reply_degraded`` and ``step``
    carry exactly what §2 says they carry, and ``None`` is the true value of a member
    describing an act the restatement did not perform.
    """
    harness = _harness()
    token = await _parked(harness)
    await harness.engine.resume(
        token, approved=True, timeout=PATIENT, remember_recipients_until=_UNTIL
    )

    restated = await harness.engine.resume(
        token, approved=True, timeout=PATIENT, remember_recipients_until=_UNTIL
    )

    assert restated.turn is None
    assert restated.recipient_grant is None
    assert len(await harness.recipient_grants.export()) == 1


# --- §3: the two populations do not overlap ----------------------------------


async def test_a_decision_a_park_holds_is_never_offered_and_is_pending() -> None:
    """ADR-0235 §12: ``grantable_decisions`` returns **no** decision a park holds.

    Arranged over a durably parked step whose ``CONFIRM`` is unresolved, and the same
    decision is reachable through ``pending_confirmations`` — which is what makes the
    two populations disjoint rather than merely differently named. It fails against
    an implementation that filtered on ``resolves`` alone, since an unanswered park's
    confirmation has no resolution either.
    """
    harness = _harness()
    await _parked(harness)

    assert await harness.engine.grantable_decisions(limit=50) == ()
    assert len(await harness.engine.pending_confirmations()) == 1


async def test_the_engines_listings_read_the_store_it_was_given() -> None:
    """The five operations are wired to the same store the act writes to (§12).

    A composition that handed the engine a second store would pass every case above
    — they assert over ``harness.recipient_grants`` — and answer every listing with
    an empty set. This is the case that joins the two halves.
    """
    harness = _harness()
    await harness.engine.resume(
        await _parked(harness), approved=True, timeout=PATIENT, remember_recipients_until=_UNTIL
    )

    standing = await harness.engine.standing_recipient_grants()
    logged = await harness.engine.recent_recipient_grants(limit=50)

    assert len(standing) == 1
    assert [record.id for record in logged] == [standing[0].id]
    revoked = await harness.engine.revoke_recipient_grant(standing[0].id)
    assert revoked is not None
    assert await harness.engine.standing_recipient_grants() == ()


def test_the_outcome_carries_the_member_the_adr_declared() -> None:
    """``TurnOutcome`` grows exactly one field, and it defaults to ``None`` (§4)."""
    assert TurnOutcome.model_fields["recipient_grant"].default is None
    assert TurnOutcome(turn=None).recipient_grant is None


# --- §2, §4: the answer a policy declined, and the base refusal -------------


class _DecliningPolicy(FakeActionPolicy):
    """A policy that declines an approving answer, which ``resolve`` expressly permits.

    ``ActionPolicy.resolve``'s second obligation admits a ``DENY`` to an
    ``approved=True`` answer — ADR-0042 §4 guarantees only the other direction — and
    no shipping policy in this tree reaches it from a fixture. ADR-0235 §2 rules what
    happens then, so the case needs a subject that produces it.
    """

    async def resolve(
        self,
        confirmed: PermissionDecision,
        *,
        approved: bool,
    ) -> PermissionRuling:
        """Record the call as the fake does, then decline whatever the user said."""
        await super().resolve(confirmed, approved=approved)
        return PermissionRuling(outcome=PermissionOutcome.DENY, reason="the policy declined it")


class _RefusingStore:
    """A store whose ``record`` refuses with the **base** refusal class.

    ADR-0235 §4's ``REFUSED`` is "every other ``InvalidRecipientGrantError`` that
    operation can raise — the duplicate-id check and the revocation invariants —
    which no surface distinguishes". Neither is reachable from a resume over an
    empty store, so the ground is arranged here; what the case is about is that the
    carrier is read from the refusal's **type** and never from its message.

    Composition rather than inheritance, because
    :class:`~ai_assistant.testing.FakeRecipientGrantStore` is ``@final``.
    """

    def __init__(self) -> None:
        """Wrap an empty store."""
        self.held = FakeRecipientGrantStore(now=lambda: _NOW)

    async def record(self, grant: RecipientGrant) -> str:
        """Refuse, with the base class and no subclass.

        Raises:
            InvalidRecipientGrantError: Always.
        """
        msg = "the store refused this record on a ground no surface distinguishes"
        raise InvalidRecipientGrantError(msg)

    async def covering(self, request: ActionRequest) -> RecipientGrant | None:
        """Forward."""
        return await self.held.covering(request)

    async def outstanding(self, grant_id: str) -> RecipientGrant | None:
        """Forward."""
        return await self.held.outstanding(grant_id)

    async def standing(self) -> list[RecipientGrant]:
        """Forward."""
        return await self.held.standing()

    async def recent(self, *, limit: int = 50) -> list[RecipientGrant]:
        """Forward."""
        return await self.held.recent(limit=limit)

    async def export(self) -> list[RecipientGrant]:
        """Forward."""
        return await self.held.export()

    async def clear(self) -> int:
        """Forward."""
        return await self.held.clear()


async def test_a_policy_deny_on_an_approving_answer_records_it_and_carries_declined() -> None:
    """ADR-0235 §12's second non-establishing answer, and §2's clause about it.

    "Where the policy answers a ``DENY`` to an ``approved=True`` resume — which
    ``ActionPolicy.resolve``'s second obligation expressly permits — the ``DENY`` is
    recorded as it is today and **no grant is established**." The establishment fails
    with the ruling's own reason and nothing looser is minted in its place.

    ``resume`` **returns** and carries ``DECLINED``, which is the member that never
    reaches the store: the resolving ruling was not an ``ALLOW``, so
    ``RecipientGrantStore.record`` was not called at all — asserted over a store
    that would have raised had it been.
    """
    store = _RefusingStore()
    definition = egress_confirmable()
    harness = Harness(
        tools=(definition,),
        binder=bound_binder(definition),
        recipient_grants=store,
        policy=_DecliningPolicy(),
    )
    token = await _parked(harness)

    resumed = await harness.engine.resume(
        token, approved=True, timeout=PATIENT, remember_recipients_until=_UNTIL
    )

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.DENIED
    assert await _resolutions(harness) == [PermissionOutcome.DENY]
    assert resumed.recipient_grant is not None
    assert resumed.recipient_grant.not_established is RecipientGrantNotEstablished.DECLINED
    assert await store.export() == []


async def test_a_base_class_refusal_carries_refused_and_names_no_cause() -> None:
    """ADR-0235 §12's mapping test, on the arm the two discriminators leave over.

    A refusal carrying the **base** ``InvalidRecipientGrantError`` is ``REFUSED`` and
    is never guessed at: the mapping is by type, so an implementation that read a
    message, took a count of its own, or read any listing after the refusal would
    have to answer something else here.
    """
    store = _RefusingStore()
    definition = egress_confirmable()
    harness = Harness(tools=(definition,), binder=bound_binder(definition), recipient_grants=store)
    token = await _parked(harness)

    resumed = await harness.engine.resume(
        token, approved=True, timeout=PATIENT, remember_recipients_until=_UNTIL
    )

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    assert resumed.recipient_grant is not None
    assert resumed.recipient_grant.not_established is RecipientGrantNotEstablished.REFUSED
