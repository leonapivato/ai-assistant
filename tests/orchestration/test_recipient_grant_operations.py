"""The recorded population: the act on a ``CONFIRM`` no park holds (ADR-0235 §3, §7).

Population (b) is the whole of what
:class:`~ai_assistant.orchestration.recipient_grants.RecipientGrantOperations`
answers on its own — the offerable listing, the act, the two listings and the
revocation. Population (a) rides ``resume`` and is pinned in
``test_engine_recipient_grants.py``, over a real engine; the two are separate
modules because they are separate doors, which is ADR-0235 §3's whole argument.

**Nothing here is arranged through a lever the production path does not have.**
The trail is seeded by recording decisions into it, the store by recording grants,
and the race cases fire through the ``ActionPolicy`` seam the operation awaits —
which is what ADR-0235 §12 requires of them: "deterministic rather than
timing-dependent … and never by racing two tasks and hoping".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.errors import (
    AuditError,
    DuplicateDecisionError,
    InvalidRecipientGrantError,
    InvalidResolutionError,
    PermissionDeniedError,
    RecipientGrantError,
    UngrantableActError,
)
from ai_assistant.core.types import (
    ActionRequest,
    CanonicalDestination,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    OriginUnrecordedBinding,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    RecipientGrant,
    SpanCoverage,
)
from ai_assistant.orchestration.recipient_grants import RecipientGrantOperations
from ai_assistant.permissions import ThresholdActionPolicy
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeAuditTrail,
    FakeRecipientGrantStore,
)
from ai_assistant.testing.recipient_grants import (
    RECIPIENT_GRANT_ACCOUNT,
    RECIPIENT_GRANT_TOOL,
    recipient_grant,
    recipient_revocation_of,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ai_assistant.core.protocols import ActionPolicy, AuditTrail, RecipientGrantStore

#: The two recipients every case here is arranged over.
ALICE: Final = "alice@example.com"
BOB: Final = "bob@example.com"

#: When a confirmation was asked.
AT: Final = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

#: The instant every act here is stamped at, and the one an expiry is compared
#: against. An hour after the confirmation, so the ordering the trail enforces
#: holds without a case having to arrange it.
_ANSWERED_AT: Final = AT + timedelta(hours=1)

#: An expiry comfortably after the answer, so a case not *about* the expiry never
#: brushes ADR-0235 §1's refusal.
EXPIRES: Final = AT + timedelta(days=1)
_UNTIL: Final = EXPIRES

#: The declaration and the account every confirmation here is about, taken from the
#: shipping fakes so a case here and a consumer's own test cannot drift into two
#: subjects: coverage compares the declaration and the account **by value**, and a
#: grant established about a locally-reworded declaration covers nothing.
_TOOL: Final = RECIPIENT_GRANT_TOOL
_ACCOUNT: Final = RECIPIENT_GRANT_ACCOUNT
_ENDPOINT: Final = "test://endpoint/one"


def member(canonical: str) -> CanonicalDestination:
    """One selected-recipient member of a canonical destination set."""
    return CanonicalDestination(protocol=DestinationProtocol.SMTP, canonical=canonical)


def _span(supplied: str, index: int) -> EgressSpan:
    """One span selecting ``supplied``, canonicalised as ADR-0148 §2's SMTP rule does."""
    return EgressSpan(
        argument="to",
        index=index,
        provenance=DiscloserProvenance.SYSTEM_SELECTED,
        extent=len(supplied),
        destination=EgressDestination(
            protocol=DestinationProtocol.SMTP, supplied=supplied, canonical=supplied.lower()
        ),
    )


def binding(*supplied: str, external: bool = False) -> EgressBinding:
    """A whole binding selecting ``supplied``.

    Stated here rather than imported, because ``tests`` carries no package a third
    directory could reach a shared copy through and the two that hold one today —
    ``tests/core/test_recipient_grant.py`` and ``tests/permissions`` — are each
    scoped to their own tree. What keeps the three from drifting apart in the way
    that would matter is that all three take the *declaration* and the *account*
    from :mod:`ai_assistant.testing.recipient_grants`, which is where coverage's
    by-value comparisons actually bite.
    """
    return EgressBinding(
        spans=tuple(_span(value, index) for index, value in enumerate(supplied)),
        account=_ACCOUNT,
        transport_endpoint=_ENDPOINT,
        planned_with_external_content=external,
        coverage=SpanCoverage.NOT_COVERED,
    )


def origin_unrecorded(*supplied: str) -> OriginUnrecordedBinding:
    """The pre-ADR-0181 binding, over the members its twin above carries.

    Built directly, because ADR-0184 §4 leaves no producer that can make one: a
    request cannot carry the shape and ``from_request`` has no route to it.
    """
    return OriginUnrecordedBinding(
        spans=tuple(_span(value, index) for index, value in enumerate(supplied)),
        account=_ACCOUNT,
        transport_endpoint=_ENDPOINT,
    )


def request(bound: EgressBinding) -> ActionRequest:
    """A request carrying ``bound``, with parameters its spans describe."""
    to = [
        occurrence.destination.supplied
        for occurrence in bound.spans
        if occurrence.destination is not None
    ]
    return ActionRequest(tool=_TOOL, parameters={"to": to}, egress_binding=bound)


def confirmation(
    bound: EgressBinding, *, decision_id: str = "d-confirm", at: datetime = AT
) -> PermissionDecision:
    """A recorded ``CONFIRM`` about a call carrying ``bound``."""
    return PermissionDecision.from_request(
        request(bound),
        PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="it discloses off-device"),
        id=decision_id,
        decided_at=at,
    )


def _ids(prefix: str) -> Iterator[str]:
    """Ids that differ per call, so a second record is never a duplicate."""
    index = 0
    while True:
        index += 1
        yield f"{prefix}-{index}"


class _DecliningPolicy:
    """A policy that declines an approving answer, which ``resolve`` expressly permits.

    ``ActionPolicy.resolve``'s second obligation admits a ``DENY`` to an
    ``approved=True`` answer — a confirmation answered long after it was asked is
    the case ADR-0235 §3 names — and no shipping policy in this tree reaches it from
    a fixture, so the case needs a subject that does. Structurally implements
    :class:`~ai_assistant.core.protocols.ActionPolicy`.
    """

    async def decide(self, request: object) -> PermissionRuling:
        """Not reached: the establishing act consults ``resolve`` alone."""
        return PermissionRuling(outcome=PermissionOutcome.DENY, reason="not reached")

    async def resolve(
        self,
        confirmed: PermissionDecision,
        *,
        approved: bool,
    ) -> PermissionRuling:
        """Decline, whatever the user said."""
        return PermissionRuling(outcome=PermissionOutcome.DENY, reason="the policy declined it")


class _ResolvingPolicy:
    """A policy that records a **competing** resolution before it rules.

    ADR-0235 §12 requires §3's late failure to be reached "through a seam the test
    drives — the ``ActionPolicy`` the engine awaits in that interval is the natural
    one — and never by racing two tasks and hoping". This is that seam: the second
    answer lands **between** the availability check and the write, deterministically,
    on every run.
    """

    def __init__(self, trail: AuditTrail, competitor: PermissionDecision) -> None:
        """Hold the trail to write into and the answer to write."""
        self._trail = trail
        self._competitor = competitor
        self.recorded = False

    async def decide(self, request: object) -> PermissionRuling:
        """Not reached."""
        return PermissionRuling(outcome=PermissionOutcome.DENY, reason="not reached")

    async def resolve(
        self,
        confirmed: PermissionDecision,
        *,
        approved: bool,
    ) -> PermissionRuling:
        """Record the competing answer, then rule as an approving policy does."""
        if not self.recorded:
            self.recorded = True
            await self._trail.record(self._competitor)
        return PermissionRuling(
            outcome=PermissionOutcome.ALLOW,
            reason="the user approved the confirmation",
            authorised_by=self._competitor.resolves,
        )


class _TrailHoldingAnUnwritableRow(FakeAuditTrail):
    """A trail that *answers with* a row no producer may write (ADR-0184 §5).

    ``AuditTrail.record`` refuses a decision whose binding records no origin, and
    ``get`` "returns the row as history rather than raising" — so a row of that
    epoch reaches a reader only from a **store decoding** one, which is what this
    stands in for. Subclassed rather than written from scratch so it satisfies the
    whole Protocol and the operations hold it through their own annotation.
    """

    def __init__(self, held: PermissionDecision) -> None:
        """Hold the one undecodable-by-a-writer row this trail answers with."""
        super().__init__()
        self._held = held

    async def get(self, decision_id: str) -> PermissionDecision | None:
        """Answer with the held row, as a store reading an old epoch does."""
        return self._held if decision_id == self._held.id else await super().get(decision_id)

    async def recent(self, *, limit: int = 50) -> list[PermissionDecision]:
        """Put the held row in the window, newest first."""
        return [self._held, *await super().recent(limit=limit)][:limit]


class _TrailRefusingWrites(FakeAuditTrail):
    """A trail whose ``record`` raises, so the two propagation arms are reachable.

    ``FakeAuditTrail`` has no write-failure lever — a refusal is what its invariants
    already produce from a badly-formed record — and the arms ADR-0235 §12 owes are
    about a refusal the *operation* cannot have caused: an
    ``InvalidResolutionError`` on a ground that is not a race, and any other
    ``AuditError``. Both are arranged here rather than by contorting a record.
    """

    def __init__(self, error: AuditError) -> None:
        """Hold the error every write raises."""
        super().__init__()
        self._error = error

    async def record(self, decision: PermissionDecision) -> str:
        """Refuse resolving writes, and admit the arrangement's own seeding."""
        if decision.resolves is not None:
            raise self._error
        return await super().record(decision)


class _WrappedStore:
    """A ``RecipientGrantStore`` that delegates to the canonical fake, with one hook.

    **Composition rather than inheritance**, because
    :class:`~ai_assistant.testing.FakeRecipientGrantStore` is ``@final`` — the fake
    is the subject a conformance suite is bound to, and a subclass of it is a
    different implementation wearing its name. Structural typing is what makes a
    wrapper the right shape here: every member below forwards, and what a case
    varies is :meth:`before_record`.

    The arms that need one are the two ADR-0235 §12 states over a **refusal the
    operation cannot have caused** — a revoking ``record`` refusing while the grant
    still stands, and a competing revocation landing between the read and the write
    — neither of which the fake's own ``fail_writes`` lever can produce, since that
    one raises the base :class:`RecipientGrantError` by design.
    """

    def __init__(self, held: FakeRecipientGrantStore) -> None:
        """Wrap ``held``."""
        self.held = held

    async def before_record(self, grant: RecipientGrant) -> None:
        """Run before every append. Overridden by the cases that need a hook."""

    async def record(self, grant: RecipientGrant) -> str:
        """Run the hook, then append."""
        await self.before_record(grant)
        return await self.held.record(grant)

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


class _StoreRefusingRevocations(_WrappedStore):
    """A store that refuses a **revoking** record while the grant still stands."""

    async def before_record(self, grant: RecipientGrant) -> None:
        """Refuse a revocation, and admit a grant.

        Raises:
            InvalidRecipientGrantError: On a revoking record.
        """
        if grant.revokes is not None:
            msg = "the store refused this revoking record"
            raise InvalidRecipientGrantError(msg)


def _operations(
    *,
    trail: AuditTrail | None = None,
    store: RecipientGrantStore | None = None,
    policy: ActionPolicy | None = None,
) -> RecipientGrantOperations:
    """The operations over the three seams, at one instant."""
    return RecipientGrantOperations(
        store=FakeRecipientGrantStore(now=lambda: _ANSWERED_AT) if store is None else store,
        trail=FakeAuditTrail() if trail is None else trail,
        policy=FakeActionPolicy() if policy is None else policy,
        id_factory=lambda: next(_MINTED),
        clock=lambda: _ANSWERED_AT,
    )


#: One id stream for the module, so every record a case makes carries a distinct id
#: without a case having to arrange one.
_MINTED = _ids("minted")


async def _seeded(*decisions: PermissionDecision) -> FakeAuditTrail:
    """A trail holding ``decisions``, recorded in order as a producer would."""
    trail = FakeAuditTrail()
    for decision in decisions:
        await trail.record(decision)
    return trail


# --- §3: the offerable listing ----------------------------------------------


async def test_a_recorded_confirmation_about_an_egress_call_is_offered() -> None:
    """The row the whole decision exists for: a refused call, offered as history."""
    confirmed = confirmation(binding(ALICE))
    operations = _operations(trail=await _seeded(confirmed))

    assert await operations.grantable_decisions(limit=50) == (confirmed,)


@pytest.mark.parametrize(
    ("name", "make"),
    [
        (
            "not a CONFIRM",
            lambda: confirmation(binding(ALICE)).model_copy(
                update={"ruling": PermissionRuling(outcome=PermissionOutcome.DENY, reason="no")}
            ),
        ),
        (
            "carries a step_id",
            lambda: confirmation(binding(ALICE)).model_copy(update={"step_id": "s-1"}),
        ),
        (
            "carries an execution_id",
            lambda: confirmation(binding(ALICE)).model_copy(update={"execution_id": "x-1"}),
        ),
        (
            "expired",
            lambda: confirmation(binding(ALICE)).model_copy(
                update={"expires_at": AT + timedelta(minutes=1)}
            ),
        ),
        (
            "no binding",
            lambda: confirmation(binding(ALICE)).model_copy(update={"egress_binding": None}),
        ),
        ("planned over external content", lambda: confirmation(binding(ALICE, external=True))),
    ],
)
async def test_a_decision_failing_a_condition_is_not_offered(
    name: str,
    make: object,
) -> None:
    """Every condition decidable from the row keeps it out of the listing (§3).

    Asserted over the listing as well as over the act, because ADR-0235 §12 requires
    both: a surface must not be able to *offer* an act the operation would refuse,
    or the user meets the refusal after choosing rather than before.
    """
    excluded = make()  # type: ignore[operator]
    operations = _operations(trail=await _seeded(excluded))

    assert await operations.grantable_decisions(limit=50) == ()


async def test_a_decision_the_trail_holds_an_answer_for_is_not_offered() -> None:
    """§3's fourth condition, decided over the window (ADR-0235 §3)."""
    confirmed = confirmation(binding(ALICE))
    answered = PermissionDecision.from_confirmation(
        confirmed,
        PermissionRuling(
            outcome=PermissionOutcome.ALLOW,
            reason="already answered",
            authorised_by=confirmed.id,
        ),
        id="d-answer",
        decided_at=_ANSWERED_AT,
    )
    operations = _operations(trail=await _seeded(confirmed, answered))

    assert await operations.grantable_decisions(limit=50) == ()


async def test_a_confirmation_sharing_the_boundary_instant_is_not_offered() -> None:
    """ADR-0235 §12's window-completeness pin, and it fails the naive implementation.

    A candidate sharing the **oldest returned row's** ``decided_at`` may have a
    resolution tie-broken just outside the window, and offering it would be offering
    a confirmation the user has already answered. So it is withheld at that ``limit``
    whatever else it satisfies, and returned at a larger one — where the window is
    complete for it and the resolution question is genuinely answered.

    This fails an implementation that read the window and filtered on resolution
    alone, which is exactly the implementation a reading of §3's fourth condition
    without §3's completeness rule produces.
    """
    boundary = confirmation(binding(ALICE), decision_id="d-boundary", at=AT)
    newer = confirmation(binding(BOB), decision_id="d-newer", at=AT + timedelta(minutes=5))
    operations = _operations(trail=await _seeded(boundary, newer))

    at_the_boundary = await operations.grantable_decisions(limit=2)
    beyond_it = await operations.grantable_decisions(limit=3)

    assert [row.id for row in at_the_boundary] == ["d-newer"]
    assert [row.id for row in beyond_it] == ["d-newer", "d-boundary"]


async def test_a_non_positive_limit_is_refused_locally() -> None:
    """The bound on the trail rows read is refused rather than clamped (ADR-0186 §3)."""
    operations = _operations()

    with pytest.raises(ValueError, match="strictly positive"):
        await operations.grantable_decisions(limit=0)


# --- §3: the act -------------------------------------------------------------


async def test_the_act_records_an_answer_and_then_a_grant() -> None:
    """ADR-0235 §12's opt-in pair, the establishing half, and §6's ordering with it.

    The grant's ``established_by`` names the confirmation and its ``decided_at`` is
    the **answer's**, which is what makes "the answer is recorded before the grant
    is" checkable over the store's contents rather than over what the call returned.
    """
    confirmed = confirmation(binding(ALICE))
    trail = await _seeded(confirmed)
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    operations = _operations(trail=trail, store=store)

    grant = await operations.establish_recipient_grant(confirmed.id, expires_at=_UNTIL)

    answers = [row for row in await trail.export() if row.resolves == confirmed.id]
    assert len(answers) == 1
    assert answers[0].ruling.outcome is PermissionOutcome.ALLOW
    assert grant.established_by == confirmed.id
    assert grant.decided_at == answers[0].decided_at
    assert [held.id for held in await store.standing()] == [grant.id]


async def test_an_act_nobody_asked_for_leaves_the_store_empty() -> None:
    """ADR-0235 §12's opt-in pair, the other half: reading offers nothing standing."""
    confirmed = confirmation(binding(ALICE))
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    operations = _operations(trail=await _seeded(confirmed), store=store)

    await operations.grantable_decisions(limit=50)

    assert await store.export() == []


@pytest.mark.parametrize(
    ("expected", "make"),
    [
        ("holds no decision", lambda: None),
        (
            "was never shown",
            lambda: confirmation(binding(ALICE)).model_copy(
                update={"ruling": PermissionRuling(outcome=PermissionOutcome.DENY, reason="no")}
            ),
        ),
        (
            "step of an execution",
            lambda: confirmation(binding(ALICE)).model_copy(update={"step_id": "s-1"}),
        ),
        (
            "step of an execution",
            lambda: confirmation(binding(ALICE)).model_copy(update={"execution_id": "x-1"}),
        ),
        (
            "stopped being answerable",
            lambda: confirmation(binding(ALICE)).model_copy(
                update={"expires_at": AT + timedelta(minutes=1)}
            ),
        ),
        (
            "records no egress call",
            lambda: confirmation(binding(ALICE)).model_copy(update={"egress_binding": None}),
        ),
        ("external content", lambda: confirmation(binding(ALICE, external=True))),
    ],
)
async def test_each_availability_condition_refuses_with_the_named_type(
    expected: str, make: object
) -> None:
    """ADR-0235 §12: **each** of §3's conditions, asserting the type §3 names.

    "Not merely that something was raised, and not a type an implementation chose."
    Each arm also asserts that **no** answer and **no** grant were recorded, which is
    what makes the refusal the one the ADR describes rather than one that happened to
    fail late.
    """
    seeded = make()  # type: ignore[operator]
    trail = await _seeded(*([] if seeded is None else [seeded]))
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    operations = _operations(trail=trail, store=store)

    with pytest.raises(UngrantableActError, match=expected):
        await operations.establish_recipient_grant("d-confirm", expires_at=_UNTIL)

    assert [row for row in await trail.export() if row.resolves is not None] == []
    assert await store.export() == []


async def test_a_row_recording_no_origin_is_neither_offered_nor_ridden() -> None:
    """§3's sixth condition on the arm no producer can write (ADR-0184 §4, §5).

    An :class:`~ai_assistant.core.types.OriginUnrecordedBinding` reaches a reader by
    **one** route only — a store decoding a row from an epoch that ended — so the
    subject here is a trail that answers with such a row rather than one a case
    recorded. §3 refuses it at the **type**, before the policy is asked, because a
    row it can never ride should not be offered at all.
    """
    unwritable = confirmation(binding(ALICE)).model_copy(
        update={"egress_binding": origin_unrecorded(ALICE)}
    )
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    operations = _operations(trail=_TrailHoldingAnUnwritableRow(unwritable), store=store)

    assert await operations.grantable_decisions(limit=50) == ()
    with pytest.raises(UngrantableActError, match="records no egress call"):
        await operations.establish_recipient_grant(unwritable.id, expires_at=_UNTIL)

    assert await store.export() == []


async def test_a_confirmation_already_answered_is_refused_before_anything_is_ruled() -> None:
    """§3's fourth condition at the check, which the seeded arm reaches (§12)."""
    confirmed = confirmation(binding(ALICE))
    answered = PermissionDecision.from_confirmation(
        confirmed,
        PermissionRuling(
            outcome=PermissionOutcome.ALLOW,
            reason="already answered",
            authorised_by=confirmed.id,
        ),
        id="d-answer",
        decided_at=_ANSWERED_AT,
    )
    trail = await _seeded(confirmed, answered)
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    operations = _operations(trail=trail, store=store)

    with pytest.raises(UngrantableActError, match="already answered"):
        await operations.establish_recipient_grant(confirmed.id, expires_at=_UNTIL)

    assert await store.export() == []


async def test_a_confirmation_answered_long_ago_is_refused_at_the_check() -> None:
    """The resolution question is answered conclusively and never over a page (§3).

    A resolution that is **not** in any recent page — a confirmation answered long
    enough ago that many decisions have been recorded since — must still refuse §3's
    fourth condition, at the check and with ``UngrantableActError``.

    It fails against an implementation that scanned a bounded window for the
    resolution: that one finds nothing at the check, seeks a ruling, has its answer
    refused by ``AuditTrail.record``, re-reads the same bounded window, finds nothing
    again, and lets an ``InvalidResolutionError`` escape — §3's refusal wearing the
    trail's type, on a decision the user is simply told is spent. The ADR's own
    account of the conversion is what a bounded scan falsifies: six of that class's
    seven grounds are closed by construction here "which is why the read finds the
    seventh and nothing else", and a scan that can miss the seventh finds neither.
    """
    confirmed = confirmation(binding(ALICE))
    answered = PermissionDecision.from_confirmation(
        confirmed,
        PermissionRuling(
            outcome=PermissionOutcome.ALLOW,
            reason="already answered",
            authorised_by=confirmed.id,
        ),
        id="d-answer",
        decided_at=_ANSWERED_AT,
    )
    later = [
        confirmation(
            binding(f"later-{index}@example.com"),
            decision_id=f"d-later-{index}",
            at=_ANSWERED_AT + timedelta(minutes=index + 1),
        )
        for index in range(300)
    ]
    trail = await _seeded(confirmed, answered, *later)
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    operations = _operations(trail=trail, store=store)

    with pytest.raises(UngrantableActError, match="already answered"):
        await operations.establish_recipient_grant(confirmed.id, expires_at=_UNTIL)

    assert await store.export() == []
    assert [row for row in await trail.export() if row.resolves == confirmed.id] == [answered]


async def test_a_resolution_recorded_during_the_act_raises_the_acts_own_type() -> None:
    """ADR-0235 §12's concurrent-resolution test, deterministic through the policy seam.

    The loser raises ``UngrantableActError`` and **not** ``InvalidResolutionError``:
    the act was not performed, nothing was recorded by this operation, nothing was
    sent, and the user-visible outcome is identical to the refusal they would have
    met a moment earlier. The winner's answer stands as the confirmation's one
    resolution, the grant store is empty, and ``grantable_decisions`` no longer
    returns the decision.

    It fails against an implementation that let the trail's refusal propagate —
    which is the implementation the seeded already-resolved arm above cannot catch,
    because that arm is refused at the check and never reaches the write.
    """
    confirmed = confirmation(binding(ALICE))
    trail = await _seeded(confirmed)
    winner = PermissionDecision.from_confirmation(
        confirmed,
        PermissionRuling(
            outcome=PermissionOutcome.ALLOW,
            reason="someone else answered first",
            authorised_by=confirmed.id,
        ),
        id="d-winner",
        decided_at=_ANSWERED_AT,
    )
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    operations = _operations(trail=trail, store=store, policy=_ResolvingPolicy(trail, winner))

    with pytest.raises(UngrantableActError, match="answered while this act"):
        await operations.establish_recipient_grant(confirmed.id, expires_at=_UNTIL)

    answers = [row for row in await trail.export() if row.resolves == confirmed.id]
    assert [row.id for row in answers] == ["d-winner"]
    assert await store.export() == []
    assert await operations.grantable_decisions(limit=50) == ()


async def test_a_resolution_error_with_no_resolution_recorded_propagates() -> None:
    """ADR-0235 §12's companion, and it is the arm a roster would omit.

    An ``InvalidResolutionError`` from ``record`` with **no** resolution of the
    confirmation recorded propagates unchanged. It fails against an implementation
    that converted the class rather than reading the trail — the one that would
    report a fault as a settled decision.

    The ground arranged here is the *subject* one: a confirmation the trail no
    longer holds under the id the answer names. That is a fault of the store rather
    than a race, and the read is what tells them apart.
    """
    confirmed = confirmation(binding(ALICE))
    trail = _TrailRefusingWrites(InvalidResolutionError("the trail refused this resolution"))
    await trail.record(confirmed)
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    operations = _operations(trail=trail, store=store)

    with pytest.raises(InvalidResolutionError):
        await operations.establish_recipient_grant(confirmed.id, expires_at=_UNTIL)

    assert await store.export() == []


async def test_another_audit_error_propagates_unchanged() -> None:
    """Every other ``AuditError`` propagates in every case (ADR-0235 §3).

    A fault is not a settled decision, and converting one into the other would hide
    it — so only the one class over the one ground is ever converted.
    """
    confirmed = confirmation(binding(ALICE))
    trail = _TrailRefusingWrites(DuplicateDecisionError("that id is already recorded"))
    await trail.record(confirmed)
    operations = _operations(trail=trail)

    with pytest.raises(DuplicateDecisionError):
        await operations.establish_recipient_grant(confirmed.id, expires_at=_UNTIL)


# --- §1: the expiry check, and its scope -------------------------------------


async def test_an_expiry_at_the_answers_instant_records_neither_answer_nor_grant() -> None:
    """ADR-0235 §12's expiry pair, over a confirmation the policy rules ``ALLOW`` on.

    It fails against an implementation that let ``RecipientGrant``'s own validator do
    the refusing, which is the outcome §1's clause forbids: that one records the
    answer and only then meets a construction refusal, leaving a decision in the
    trail, no grant, and a user told nothing they could act on.
    """
    confirmed = confirmation(binding(ALICE))
    trail = await _seeded(confirmed)
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    operations = _operations(trail=trail, store=store)

    with pytest.raises(UngrantableActError, match="expires strictly after"):
        await operations.establish_recipient_grant(confirmed.id, expires_at=_ANSWERED_AT)

    assert [row for row in await trail.export() if row.resolves is not None] == []
    assert await store.export() == []


async def test_an_expiry_after_the_answers_instant_establishes_the_grant() -> None:
    """The other half of the pair: strictly after, and the act completes."""
    confirmed = confirmation(binding(ALICE))
    operations = _operations(trail=await _seeded(confirmed))

    grant = await operations.establish_recipient_grant(
        confirmed.id, expires_at=_ANSWERED_AT + timedelta(seconds=1)
    )

    assert grant.expires_at == _ANSWERED_AT + timedelta(seconds=1)


async def test_a_declining_ruling_records_its_answer_and_never_consults_the_expiry() -> None:
    """ADR-0235 §12's scoping arm, owed **by name and not by a roster**.

    ``ActionPolicy.resolve``'s second obligation permits a ``DENY`` to an approving
    answer, and §1's expiry check is scoped to a ruling that is going to be an
    ``ALLOW``. So an expiry the check would refuse is **not consulted** here: the
    answer is recorded exactly as it would be had no expiry been supplied at all,
    and the operation raises ``PermissionDeniedError`` rather than the act's own
    refusal.

    Asserted over the **trail's contents**, so it fails against an implementation
    that validated the expiry before the policy ruled — the contradiction round 3 of
    ADR-0235's review found in an earlier draft of §1.
    """
    confirmed = confirmation(binding(ALICE))
    trail = await _seeded(confirmed)
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    operations = _operations(trail=trail, store=store, policy=_DecliningPolicy())

    with pytest.raises(PermissionDeniedError, match="settled"):
        await operations.establish_recipient_grant(confirmed.id, expires_at=_ANSWERED_AT)

    answers = [row for row in await trail.export() if row.resolves == confirmed.id]
    assert [row.ruling.outcome for row in answers] == [PermissionOutcome.DENY]
    assert await store.export() == []


async def test_a_declined_confirmation_is_settled_and_offered_no_more() -> None:
    """A confirmation has one answer, so the act cannot be offered on it again (§3)."""
    confirmed = confirmation(binding(ALICE))
    trail = await _seeded(confirmed)
    operations = _operations(trail=trail, policy=_DecliningPolicy())

    with pytest.raises(PermissionDeniedError):
        await operations.establish_recipient_grant(confirmed.id, expires_at=_UNTIL)

    assert await operations.grantable_decisions(limit=50) == ()


# --- §6: the ceiling on the recorded population ------------------------------


async def test_a_ceiling_refusal_leaves_the_answer_recorded_and_returns_no_grant() -> None:
    """ADR-0235 §12's ceiling arm for population (b).

    The act raises the store's own ``InvalidRecipientGrantError`` and returns no
    value a caller could mistake for an established grant: its return **is** the
    grant, there is no grant, and nothing was sent on account of the answer.

    Arranged over a store already holding the configured maximum of **outstanding**
    records, at least one of which is **expired**, so it fails against an
    implementation that counted the live set instead — the substitution §6 forbids.
    """
    confirmed = confirmation(binding(ALICE))
    trail = await _seeded(confirmed)
    store = FakeRecipientGrantStore(now=lambda: EXPIRES + timedelta(days=2), max_outstanding=1)
    held = recipient_grant(member(BOB), grant_id="g-held")
    await store.record(held)
    assert await store.standing() == []  # expired, and still occupying its slot
    operations = _operations(trail=trail, store=store)

    with pytest.raises(InvalidRecipientGrantError):
        await operations.establish_recipient_grant(confirmed.id, expires_at=_UNTIL)

    answers = [row for row in await trail.export() if row.resolves == confirmed.id]
    assert len(answers) == 1
    assert [record.id for record in await store.export()] == [held.id]


async def test_a_ceiling_refusal_settles_the_confirmation_for_good() -> None:
    """ADR-0235 §12's settlement arm, on the recorded population.

    Revoking a grant frees a slot but does **not** reopen this act: the answer is
    recorded, a confirmation has one answer, and §3's fourth condition then keeps the
    decision out of the listing at **any** limit. It fails against an implementation
    that left the confirmation offerable, which is the one whose surface would invite
    the retry §6 forbids it to promise.
    """
    confirmed = confirmation(binding(ALICE))
    trail = await _seeded(confirmed)
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT, max_outstanding=0)
    operations = _operations(trail=trail, store=store)

    with pytest.raises(InvalidRecipientGrantError):
        await operations.establish_recipient_grant(confirmed.id, expires_at=_UNTIL)

    assert await operations.grantable_decisions(limit=1) == ()
    assert await operations.grantable_decisions(limit=500) == ()


async def test_a_store_fault_propagates_from_the_recorded_population() -> None:
    """ADR-0235 §12's store-fault pair, the population-(b) half.

    ``establish_recipient_grant`` raises it **unchanged**, where nothing has been
    sent and there is no outcome to destroy. It fails against an implementation that
    swallowed a fault on the population where nothing was sent.
    """
    confirmed = confirmation(binding(ALICE))
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    store.fail_writes(RecipientGrantError("the store could not be written"))
    operations = _operations(trail=await _seeded(confirmed), store=store)

    with pytest.raises(RecipientGrantError) as raised:
        await operations.establish_recipient_grant(confirmed.id, expires_at=_UNTIL)

    assert not isinstance(raised.value, InvalidRecipientGrantError)


# --- §7: the two listings and the revocation ---------------------------------


async def test_the_standing_listing_states_liveness_and_the_log_does_not() -> None:
    """ADR-0235 §7: an expired grant is in the log and in no standing listing."""
    store = FakeRecipientGrantStore(now=lambda: EXPIRES + timedelta(days=2))
    expired = recipient_grant(member(ALICE), grant_id="g-expired")
    await store.record(expired)
    operations = _operations(store=store)

    assert await operations.standing_recipient_grants() == ()
    assert [record.id for record in await operations.recent_recipient_grants(limit=50)] == [
        "g-expired"
    ]


async def test_the_log_carries_revoking_records_too() -> None:
    """A revoking record is the record of an act, which is what it is (§7)."""
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    granted = recipient_grant(member(ALICE), grant_id="g-1")
    await store.record(granted)
    await store.record(recipient_revocation_of(granted, grant_id="r-1"))
    operations = _operations(store=store)

    assert {record.id for record in await operations.recent_recipient_grants(limit=50)} == {
        "g-1",
        "r-1",
    }
    assert await operations.standing_recipient_grants() == ()


async def test_a_non_positive_log_limit_is_refused_locally() -> None:
    """``recent`` refuses a non-positive limit, and so does this (ADR-0235 §7)."""
    operations = _operations()

    with pytest.raises(ValueError, match="strictly positive"):
        await operations.recent_recipient_grants(limit=0)


async def test_revocation_appends_a_record_transcribing_the_grant() -> None:
    """The revoking record says what was withdrawn without a join (ADR-0193 §1)."""
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    granted = recipient_grant(member(ALICE), grant_id="g-1")
    await store.record(granted)
    operations = _operations(store=store)

    revoked = await operations.revoke_recipient_grant("g-1")

    assert revoked is not None
    assert revoked.revokes == "g-1"
    assert revoked.tool == granted.tool
    assert revoked.account == granted.account
    assert revoked.destinations == granted.destinations
    assert await operations.standing_recipient_grants() == ()


async def test_revoking_an_absent_grant_answers_none() -> None:
    """The store held no outstanding record with that id, which is what ``None`` means."""
    operations = _operations()

    assert await operations.revoke_recipient_grant("g-absent") is None


async def test_a_lost_revocation_race_answers_none_and_appends_nothing() -> None:
    """ADR-0235 §12's concurrent-revocation pair, deterministic like §3's.

    A second revoking record for the same grant is appended **between** this
    operation's ``outstanding`` read and its write, through a store that performs the
    competing write from inside its own ``record``. The call returns ``None`` and
    raises nothing, the store holds exactly one revoking record for that grant, and
    the grant is absent from the standing listing.

    It fails against an implementation that let the loser's refusal reach a user
    performing ADR-0193 §1's stated recourse — the one act the ceiling makes users
    perform.
    """
    granted = recipient_grant(member(ALICE), grant_id="g-1")

    class _RacingStore(_WrappedStore):
        """A store that revokes ``granted`` itself, once, the moment it is armed."""

        armed = False

        async def before_record(self, grant: RecipientGrant) -> None:
            """Let the competitor in first, once."""
            if self.armed:
                self.armed = False
                await self.held.record(recipient_revocation_of(granted, grant_id="r-winner"))

    held = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    await held.record(granted)
    store = _RacingStore(held)
    operations = _operations(store=store)
    store.armed = True

    assert await operations.revoke_recipient_grant("g-1") is None

    revoking = [record for record in await held.export() if record.revokes == "g-1"]
    assert [record.id for record in revoking] == ["r-winner"]
    assert await operations.standing_recipient_grants() == ()


async def test_a_refusal_while_the_grant_still_stands_propagates() -> None:
    """The companion arm a roster would omit (ADR-0235 §12).

    An ``InvalidRecipientGrantError`` from a revoking ``record`` while the grant
    **is** still outstanding propagates unchanged. It fails against an implementation
    that converted the class rather than re-reading the store, which would report a
    fault as a completed revocation.
    """
    held = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    await held.record(recipient_grant(member(ALICE), grant_id="g-1"))
    operations = _operations(store=_StoreRefusingRevocations(held))

    with pytest.raises(InvalidRecipientGrantError):
        await operations.revoke_recipient_grant("g-1")

    assert await held.outstanding("g-1") is not None


async def test_the_recourse_the_ceiling_names_is_an_act_a_user_can_perform() -> None:
    """ADR-0235 §12's end-to-end recourse, and naming a **second** confirmation is the point.

    A store at the ceiling whose slot is held by an **expired** grant yields that
    record from the log and none of it from the standing listing; revoking it appends
    a revoking record; and the act then succeeds on a different, still-unanswered
    confirmation — never on the one the ceiling refused, which §6 settles.
    """
    refused = confirmation(binding(ALICE), decision_id="d-refused")
    second = confirmation(binding(BOB), decision_id="d-second", at=AT + timedelta(minutes=1))
    trail = await _seeded(refused, second)
    store = FakeRecipientGrantStore(now=lambda: EXPIRES + timedelta(days=2), max_outstanding=1)
    expired = recipient_grant(member("held@example.com"), grant_id="g-expired")
    await store.record(expired)
    operations = _operations(trail=trail, store=store)

    with pytest.raises(InvalidRecipientGrantError):
        await operations.establish_recipient_grant("d-refused", expires_at=EXPIRES)

    assert await operations.standing_recipient_grants() == ()
    assert [record.id for record in await operations.recent_recipient_grants(limit=50)] == [
        "g-expired"
    ]
    assert await operations.revoke_recipient_grant("g-expired") is not None

    granted = await operations.establish_recipient_grant(
        "d-second", expires_at=EXPIRES + timedelta(days=3)
    )

    assert granted.established_by == "d-second"
    assert await operations.grantable_decisions(limit=50) == ()


# --- §4: detachment ----------------------------------------------------------


async def test_the_three_reads_return_detached_snapshots() -> None:
    """ADR-0235 §12's detachment arms, over all three reads at once.

    A caller mutating a returned record through its ``__dict__`` — which
    ``frozen=True`` does not refuse — changes nothing a later call returns. Asserted
    on the three together because the failure is one bug in one place: a read that
    handed back the store's or the trail's own object.
    """
    confirmed = confirmation(binding(ALICE))
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    granted = recipient_grant(member(ALICE), grant_id="g-1")
    await store.record(granted)
    operations = _operations(trail=await _seeded(confirmed), store=store)

    offered = await operations.grantable_decisions(limit=50)
    standing = await operations.standing_recipient_grants()
    logged = await operations.recent_recipient_grants(limit=50)
    offered[0].__dict__["id"] = "rewritten"
    standing[0].__dict__["destinations"] = ()
    logged[0].__dict__["expires_at"] = AT

    assert (await operations.grantable_decisions(limit=50))[0].id == confirmed.id
    assert (await operations.standing_recipient_grants())[0].destinations == granted.destinations
    assert (await operations.recent_recipient_grants(limit=50))[0].expires_at == granted.expires_at


# --- the arm this whole decision exists for ----------------------------------


async def test_a_grant_established_here_sources_a_route_b_allow() -> None:
    """ADR-0235 §12's end-to-end arm, against a seeded engine and with no network.

    A recorded egress ``CONFIRM`` that no park holds is offered by
    ``grantable_decisions``; ``establish_recipient_grant`` records an answer and a
    grant; and a subsequent request over the same tool, account and canonical
    destination set is ruled ``ALLOW`` on **route (b)** with ``authorised_by`` naming
    that grant.

    It is the test that would have failed on every tree before this one:
    ``RecipientGrant.established_from`` had no caller and
    ``SqliteRecipientGrantStore`` had never taken a write, so route (b) was reachable
    only from a hand-seeded store.
    """
    confirmed = confirmation(binding(ALICE))
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    operations = _operations(trail=await _seeded(confirmed), store=store)

    assert [row.id for row in await operations.grantable_decisions(limit=50)] == [confirmed.id]
    grant = await operations.establish_recipient_grant(confirmed.id, expires_at=_UNTIL)

    policy = ThresholdActionPolicy(grants=store)
    ruled = await policy.decide(request(binding(ALICE)))

    assert ruled.outcome is PermissionOutcome.ALLOW
    assert ruled.authorised_by == grant.id
    assert ruled.authorised_subject == grant.subject_digest


async def test_the_grants_destination_set_is_the_bindings_own_derived_one() -> None:
    """``core`` derives the set and this transcribes it, so no surface reorders it.

    A surface that rebuilt the tuple in the order it happened to *render* it in
    would be minting a grant this record's own validator refuses, and one that took
    the recipients off the call's arguments instead of off the binding would bypass
    ADR-0148 §2's canonicaliser. Both are closed by ``established_from`` doing the
    transcription, and this is what checks it against the binding rather than
    against a fixture's idea of what the binding holds.
    """
    confirmed = confirmation(binding(ALICE))
    operations = _operations(trail=await _seeded(confirmed))

    grant = await operations.establish_recipient_grant(confirmed.id, expires_at=_UNTIL)

    assert grant.destinations == binding(ALICE).canonical_destination_set
    assert member(ALICE) in grant.destinations
