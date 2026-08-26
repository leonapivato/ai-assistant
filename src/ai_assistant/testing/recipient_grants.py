"""Canonical test doubles for the recipient-grant seam (ADR-0193 §1, §14).

The shared fakes for :class:`~ai_assistant.core.protocols.RecipientGrants`,
:class:`~ai_assistant.core.protocols.RecipientGrantResolution` and
:class:`~ai_assistant.core.protocols.RecipientGrantStore`, so a component that
consults the seam — an ``ActionPolicy`` for ADR-0193 §7's lookup, an
``AuditTrail`` for §6's resolution read — can exercise every branch of its own
rule without a store on disk and without importing the permissions subsystem's
internals (``CLAUDE.md`` golden rule 1).

**Three fakes because the seam is three Protocols**, split by capability rather
than by taxonomy (ADR-0193 §1, on ADR-0097 §3's split and for its reason).
:class:`FakeRecipientGrants` is the policy's face and can create nothing and
resolve no id; :class:`FakeRecipientGrantResolution` is the trail's face and
carries one member; :class:`FakeRecipientGrantStore` records. The store fake
satisfies both narrow seams structurally, which is why the two narrow conformance
suites are bound against **it** as well as against their own fake — that turns
§1's "one concrete store satisfies all three faces" from an assertion into a
test.

**One history, three views.** All three answer from the same
:class:`_RecipientGrantLog`, which applies every invariant
:meth:`~ai_assistant.core.protocols.RecipientGrantStore.record` applies. Two
hand-written copies of "is this grant live" would be free to disagree, and the
one that disagreed would still pass its own suite — the failure ADR-0193 §1
guards when it puts liveness in the store rather than in each caller.

**The clock is injected and read once per liveness-evaluating query** (§9).
``covering`` and ``standing`` read it exactly once and evaluate every record they
consider against that one instant; ``outstanding``, ``recent`` and ``export``
read it not at all. A test that drives a clock advancing on every read is what
makes the single-read clause falsifiable, so the constructor takes one.

**Not a fault injector.** Everything here conforms. A consumer that needs a store
which *breaks* the contract on purpose supplies its own stub; these must stay the
things a conforming implementation is compared against, so a script they could
only honour by violating their own contract is refused where it is written
(``FakeSourceGrants`` makes the same trade).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from pydantic import ValidationError

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import InvalidRecipientGrantError, RecipientGrantError
from ai_assistant.core.types import (
    BoundAccount,
    CanonicalDestination,
    CostBasis,
    DataTier,
    DestinationProtocol,
    Idempotency,
    RecipientGrant,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.types import ActionRequest
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

#: When a scripted record pretends the user decided. Fixed, so ordering
#: assertions are about the values under test rather than about how fast a suite
#: runs — ``permission_builders.AT``'s reason and
#: :data:`~ai_assistant.testing.grants.DEFAULT_DECIDED_AT`'s.
#:
#: **Prefixed rather than named ``DEFAULT_…``**, and every constant and builder
#: here is: ``ai_assistant.testing`` re-exports the source-grant module's
#: ``DEFAULT_DECIDED_AT`` and ``revocation_of`` under those names already, and a
#: second seam claiming them would either shadow the first at the package surface
#: or force a consumer to remember which import won. Two grant stores that read
#: alike at a call site is exactly the confusion ADR-0097 §7 keeps apart.
RECIPIENT_GRANT_DECIDED_AT: Final = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

#: When a scripted grant stops being live. A **day** after
#: :data:`RECIPIENT_GRANT_DECIDED_AT` rather than an hour or a century: far enough that
#: :data:`RECIPIENT_GRANT_NOW` sits comfortably inside the interval and a test about
#: expiry has to say so, close enough that the two instants read as one scenario.
RECIPIENT_GRANT_EXPIRES_AT: Final = RECIPIENT_GRANT_DECIDED_AT + timedelta(days=1)

#: What the fakes' default clock reads: inside every default grant's interval, so
#: a test that does not mention liveness gets a live grant, and a test that is
#: about liveness moves this rather than the record.
RECIPIENT_GRANT_NOW: Final = RECIPIENT_GRANT_DECIDED_AT + timedelta(hours=1)

#: The declaration a scripted grant is about unless a test names another. It
#: **discloses**, because ADR-0148 §8's second clause makes a non-empty
#: ``discloses`` true of every tool registered at the egress seam — so a grant
#: over a non-disclosing declaration would be a grant covering calls that never
#: needed one, and a policy test built on it would prove nothing about the floor
#: route (b) exists to relieve (ADR-0021 §5, §6).
RECIPIENT_GRANT_TOOL: Final = ToolDefinition(
    id="send_email",
    capability="send_email",
    description="Send an email through the connected account.",
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.IRREVERSIBLE,
    side_effecting=True,
    reads=(),
    writes=(),
    discloses=(DataTier.PERSONAL,),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
)

#: The connected account a scripted grant is established against. Two facts, as
#: :class:`~ai_assistant.core.types.BoundAccount` requires: an identity the user
#: recognises and the connection record's reference, which is what stops a grant
#: covering a second connectable record holding the same identity (ADR-0193 §3).
RECIPIENT_GRANT_ACCOUNT: Final = BoundAccount(identity="work@example.com", reference="conn-0001")

#: The recipient a scripted grant names unless a test names another.
RECIPIENT_GRANT_ADDRESS: Final = "alice@example.com"


def recipient(canonical: str) -> CanonicalDestination:
    """One **selected recipient** member, under SMTP's rules.

    Exported because a consumer scripting any of these fakes must not have to
    re-derive what a member looks like, and because the two arms of
    :class:`~ai_assistant.core.types.CanonicalDestination` are the pair a test
    most easily gets wrong: a member carrying a protocol and a canonical form is
    a recipient, and one carrying an account is the service the call is made to,
    and neither ever equals the other whatever strings the two hold.

    Args:
        canonical: The canonical form, as ADR-0148 §2's canonicaliser would have
            produced it. Nothing here canonicalises — there is one canonicaliser
            and it is at the seam (ADR-0193 §3).

    Returns:
        The member.
    """
    return CanonicalDestination(protocol=DestinationProtocol.SMTP, canonical=canonical)


def account_member(account: BoundAccount = RECIPIENT_GRANT_ACCOUNT) -> CanonicalDestination:
    """The **connected account** member — ADR-0148 §2's third clause.

    It covers exactly the calls whose arguments select no recipient beyond the
    service the call is made to, and covers **no** selected recipient, whatever
    strings the two hold (ADR-0193 §3). A test asserting that pair wants this
    beside :func:`recipient`.

    Args:
        account: The account this member is.

    Returns:
        The member.
    """
    return CanonicalDestination(account=account)


def _mint(prefix: str) -> str:
    """Mint one opaque record id.

    Opaque and minted rather than derived, for the reason ADR-0092 §6 gives about
    a producer's ids: a derived id is an *address*, aimed at the same record every
    time. A test that needs a stable id supplies one.
    """
    return f"{prefix}-{uuid4().hex}"


def recipient_grant(  # noqa: PLR0913 — one knob per RecipientGrant field a suite varies
    *destinations: CanonicalDestination,
    grant_id: str | None = None,
    tool: ToolDefinition = RECIPIENT_GRANT_TOOL,
    account: BoundAccount = RECIPIENT_GRANT_ACCOUNT,
    decided_at: datetime = RECIPIENT_GRANT_DECIDED_AT,
    expires_at: datetime = RECIPIENT_GRANT_EXPIRES_AT,
    established_by: str = "d-confirm",
) -> RecipientGrant:
    """One well-formed **granting** record.

    Exported for :func:`~ai_assistant.testing.grants.source_grant`'s reason: a
    consumer scripting any of these fakes, and the policy's and trail's own tests,
    must not have to re-derive what a grant looks like. There is nothing subtle in
    the shape, but there are seven fields to line up and three of them — the
    declaration, the account and the destination set — have to match the request
    they are meant to cover *by value* or the grant covers nothing.

    **Not** :meth:`~ai_assistant.core.types.RecipientGrant.established_from`, and
    the difference is deliberate. That is the one path a **production** surface
    builds a grant through, and it takes two recorded decisions; this is an
    arrangement helper that puts a store into a state, the way
    :func:`~ai_assistant.testing.grants.source_grant` does. A test *about* the
    establishing act uses the classmethod.

    ``destinations`` are sorted here into the one canonical order the record
    requires, because an arrangement helper is not the case that clause is
    written against: a test wanting the **refusal** builds the tuple by hand and
    hands it to the constructor, which is the hand-built tuple ADR-0193 §1 is
    about.

    Args:
        destinations: The canonical destination set. Defaults to one selected
            recipient, :data:`RECIPIENT_GRANT_ADDRESS`.
        grant_id: A stable id, for a test naming the record it asserts on.
            ``None`` mints an opaque one.
        tool: The declaration this grant is about, by value.
        account: The connected account it is established against, by value.
        decided_at: When the user decided; timezone-aware.
        expires_at: When it stops being live; strictly after ``decided_at``.
        established_by: The recorded ``CONFIRM`` the establishing act rode.

    Returns:
        The grant, ready to hold or to record.
    """
    from ai_assistant.core.types import _destination_order  # noqa: PLC0415 — see below

    # Imported inside the function rather than at module scope: it is `core`'s
    # private ordering key, and this is the one place in `testing/` that needs it.
    # A module-scope import would put a private name on this module's own surface,
    # where a consumer could take it for a supported one.
    members = destinations or (recipient(RECIPIENT_GRANT_ADDRESS),)
    return RecipientGrant(
        id=grant_id if grant_id is not None else _mint("grant"),
        tool=tool,
        account=account,
        destinations=tuple(sorted(members, key=_destination_order)),
        decided_at=decided_at,
        expires_at=expires_at,
        established_by=established_by,
    )


def recipient_revocation_of(
    grant: RecipientGrant,
    *,
    grant_id: str | None = None,
    decided_at: datetime | None = None,
) -> RecipientGrant:
    """The record that revokes ``grant``, transcribing what it withdraws.

    The transcription is not a convenience: ADR-0193 §1 has the store verify that
    a revoking record carries the ``tool``, ``account``, ``destinations`` and
    ``expires_at`` of the grant it revokes, so a hand-built revocation that got
    any of them wrong is refused. Building it from the grant makes that correct by
    construction, and a test that wants the *refusal* overrides one field
    deliberately rather than by accident.

    Args:
        grant: The granting record being withdrawn.
        grant_id: A stable id for the revoking record; ``None`` mints one.
        decided_at: When the user revoked. ``None`` reuses the grant's own
            instant, which is deliberate rather than lazy: ADR-0193 §1 never
            refuses a revocation for its timestamp, so the default must not
            quietly depend on being later.

    Returns:
        The revoking record.
    """
    return RecipientGrant(
        id=grant_id if grant_id is not None else _mint("revoke"),
        tool=grant.tool,
        account=grant.account,
        destinations=grant.destinations,
        decided_at=decided_at if decided_at is not None else grant.decided_at,
        expires_at=grant.expires_at,
        revokes=grant.id,
    )


class _RecipientGrantLog:
    """The append-only history all three fakes answer from (ADR-0193 §1).

    Shared rather than written three times, because the three faces must agree
    about liveness to the letter: the store's ``record`` is what a test uses to
    arrange a state, and each narrow fake has to *be* in that same state for a
    shared suite to mean the same thing against all of them.

    Not a Protocol implementation and not exported: the fakes are.
    """

    def __init__(self, *, max_outstanding: int) -> None:
        """Create an empty history under ``max_outstanding``.

        Args:
            max_outstanding: ADR-0193 §1's ceiling on outstanding **granting**
                records. Zero is meaningful and admitted; a negative one names no
                ceiling at all.

        Raises:
            ValueError: If ``max_outstanding`` is negative.
        """
        if max_outstanding < 0:
            msg = f"max_outstanding must not be negative, got {max_outstanding}"
            raise ValueError(msg)
        self._max_outstanding = max_outstanding
        self._records: list[RecipientGrant] = []

    def append(self, grant: RecipientGrant) -> str:
        """Validate ``grant`` against every §1 invariant and append a snapshot.

        The snapshot is taken by **revalidating** rather than by copying, which is
        ADR-0193 §1's "detached, validated snapshot", and it is rebuilt from the
        instance's field state rather than from ``model_dump()`` for
        ``_GrantLog.append``'s reason: ``model_dump`` is an ordinary overridable
        method, so a subclass could return a mapping that does not describe itself
        — a one-recipient instance whose dump says two — and the store would then
        append a *wider grant than the one it was handed*. ``__dict__`` is where
        pydantic keeps validated field state, read through
        ``object.__getattribute__`` so the read itself dispatches no user code.

        **Every check and the append are one operation**, with no ``await``
        between them. That is where the atomicity ADR-0193 §1 requires is
        obtained: the ceiling in particular is the one a count read outside the
        operation gets wrong, because two writers of *different* subjects at one
        below it both see room.

        Raises:
            InvalidRecipientGrantError: If the record does not satisfy its own
                model, if its id is already recorded, if a granting record
                duplicates an outstanding grant's ``tool``, ``account`` and
                ``destinations``, if a granting record would take the outstanding
                count above the ceiling, or if it revokes and fails any of §1's
                invariants.
        """
        try:
            snapshot = RecipientGrant.model_validate(
                dict(object.__getattribute__(grant, "__dict__"))
            )
        except ValidationError as exc:
            msg = f"recipient grant {grant.id!r} is not a valid record: {exc}"
            raise InvalidRecipientGrantError(msg) from exc
        if any(held.id == snapshot.id for held in self._records):
            msg = (
                f"recipient grant {snapshot.id!r} is already recorded; the store is "
                f"append-only, so history cannot be rewritten by replaying a write"
            )
            raise InvalidRecipientGrantError(msg)
        if snapshot.revokes is None:
            self._check_not_a_duplicate_subject(snapshot)
            self._check_room(snapshot)
        else:
            self._check_revocation(snapshot)
        self._records.append(snapshot)
        return snapshot.id

    def _check_not_a_duplicate_subject(self, grant: RecipientGrant) -> None:
        """Refuse a granting record that **is** an outstanding one (ADR-0193 §1).

        Stated over ``tool``, ``account`` and ``destinations`` — and over
        **outstanding** rather than live, so no clock is read and no
        caller-supplied instant decides anything. Overlapping grants over
        *different* destination sets stay permitted and are what ``covering``'s
        precedence is for; what is refused is a second grant that is the first,
        because revoking one would leave the other standing and the user would
        have revoked nothing.

        Raises:
            InvalidRecipientGrantError: If an outstanding grant has the same
                declaration, account and destination set.
        """
        standing = next(
            (
                held
                for held in self._outstanding()
                if held.tool == grant.tool
                and held.account == grant.account
                and held.destinations == grant.destinations
            ),
            None,
        )
        if standing is not None:
            msg = (
                f"recipient grant {standing.id!r} already stands over this declaration, "
                f"account and destination set; a second is one the user could not revoke, "
                f"because revoking either would leave the other standing (ADR-0193 §1)"
            )
            raise InvalidRecipientGrantError(msg)

    def _check_room(self, grant: RecipientGrant) -> None:
        """Refuse a granting record that would breach the ceiling (ADR-0193 §1).

        Counted over **outstanding** granting records, which is a fact about two
        records and needs no clock; an expired grant therefore occupies its slot
        until it is revoked, which is the same shape the duplicate rule has and
        the price of a write path that reads no clock.

        **Nothing is evicted, narrowed or expired to make room**, and no looser
        grant is minted in its place.

        Raises:
            InvalidRecipientGrantError: If the store already holds the configured
                maximum of outstanding granting records.
        """
        held = len(self._outstanding())
        if held >= self._max_outstanding:
            msg = (
                f"the recipient-grant store holds {held} outstanding grants and admits "
                f"{self._max_outstanding}, so grant {grant.id!r} is refused; nothing is "
                f"evicted to make room, and the recourse is to revoke a grant you hold "
                f"(ADR-0193 §1)"
            )
            raise InvalidRecipientGrantError(msg)

    def _check_revocation(self, revocation: RecipientGrant) -> None:
        """Enforce ADR-0193 §1's invariant on a revoking record.

        Six refusals, and **no seventh on the timestamp**: ``decided_at`` is
        caller-supplied and this log reads no clock, so refusing a revocation that
        predates its grant would make a grant permanently unrevokable across a
        backwards clock correction — the recourse ADR-0193 §1's ceiling clause
        depends on, defeated by an invariant that was protecting nothing.

        Raises:
            InvalidRecipientGrantError: If the named grant is absent, is itself a
                revoking record, is already revoked, or if any transcribed field
                differs.
        """
        target = next((held for held in self._records if held.id == revocation.revokes), None)
        if target is None:
            msg = (
                f"recipient grant {revocation.revokes!r} is not recorded, so nothing "
                f"revokes it (ADR-0193 §1)"
            )
            raise InvalidRecipientGrantError(msg)
        if target.revokes is not None:
            msg = (
                f"record {target.id!r} is itself a revocation; only a granting record "
                f"can be revoked (ADR-0193 §1)"
            )
            raise InvalidRecipientGrantError(msg)
        if any(held.revokes == target.id for held in self._records):
            msg = (
                f"recipient grant {target.id!r} is already revoked; a grant revoked twice "
                f"is a history that says the user withdrew one thing twice (ADR-0193 §1)"
            )
            raise InvalidRecipientGrantError(msg)
        if target.tool != revocation.tool:
            msg = (
                f"revocation {revocation.id!r} transcribes a different declaration from the "
                f"one grant {target.id!r} was established about; a revoking record "
                f"transcribes what it withdraws (ADR-0193 §1)"
            )
            raise InvalidRecipientGrantError(msg)
        if target.account != revocation.account:
            msg = (
                f"revocation {revocation.id!r} names a different account from the one grant "
                f"{target.id!r} was established against (ADR-0193 §1)"
            )
            raise InvalidRecipientGrantError(msg)
        if target.destinations != revocation.destinations:
            msg = (
                f"revocation {revocation.id!r} transcribes a different destination set from "
                f"the one grant {target.id!r} names; there is no partial revocation "
                f"(ADR-0193 §1, §9)"
            )
            raise InvalidRecipientGrantError(msg)
        if target.expires_at != revocation.expires_at:
            msg = (
                f"revocation {revocation.id!r} transcribes a different expiry from grant "
                f"{target.id!r}'s (ADR-0193 §1)"
            )
            raise InvalidRecipientGrantError(msg)

    def _outstanding(self) -> list[RecipientGrant]:
        """Every **granting** record no revoking record names.

        A fact about two records, needing no clock — ADR-0097 §4's own liveness
        read on this store's subject, and the predicate ``record`` decides over
        (ADR-0193 §1).
        """
        revoked = {held.revokes for held in self._records if held.revokes is not None}
        return [held for held in self._records if held.revokes is None and held.id not in revoked]

    def _live(self, instant: datetime) -> list[RecipientGrant]:
        """Every outstanding grant live at ``instant``.

        The interval is **closed below and open above**: at or after
        ``decided_at`` and strictly before ``expires_at`` (ADR-0193 §1, §9).
        Bounded below as well as above, because without that half a future-dated
        grant would be handed to the policy and ``AuditTrail.record`` would then
        refuse the ``ALLOW`` it sourced. One ``instant`` for every record, because
        the caller read the clock once.
        """
        return [
            held for held in self._outstanding() if held.decided_at <= instant < held.expires_at
        ]

    def covering(self, request: ActionRequest, instant: datetime) -> RecipientGrant | None:
        """The live grant covering ``request``, detached, or ``None``.

        Four of ADR-0193 §3's five comparisons — liveness, tool equality by value,
        account equality by value, and containment of the request's canonical
        destination set. The fifth, ``planned_with_external_content``, is the
        policy's and is deliberately not read here: a safety rule stated in both
        places would be two statements to keep in step.

        **Containment is membership and nothing looser.** No case folding, no
        domain matching, no treating an account member as covering a recipient
        member or the reverse, and no re-canonicalising either side — each
        comparison is :class:`~ai_assistant.core.types.CanonicalDestination`'s
        own, over every field and never across protocols.

        **Precedence is total** (ADR-0193 §1): the greatest ``decided_at`` wins,
        ties broken by the least ``id`` under code-point order. Two passes over a
        stable sort rather than one composite key, because the two halves run in
        opposite directions and ``datetime`` has no negation — ``_GrantLog``'s
        shape. Overlapping grants are permitted, so a store returning the first
        match it found would give two conforming implementations different answers
        for one state.
        """
        binding = request.egress_binding
        if binding is None:
            return None
        wanted = binding.canonical_destination_set
        matching = [
            held
            for held in self._live(instant)
            if held.tool == request.tool
            and held.account == binding.account
            and all(member in held.destinations for member in wanted)
        ]
        if not matching:
            return None
        by_id = sorted(matching, key=lambda held: held.id)
        latest = sorted(by_id, key=lambda held: held.decided_at, reverse=True)[0]
        return latest.model_copy(deep=True)

    def outstanding(self, grant_id: str) -> RecipientGrant | None:
        """The outstanding granting record with ``grant_id``, detached, or ``None``.

        Reads **no clock**: an expired but unrevoked grant is returned rather than
        withheld, because expiry is not this member's question and the trail
        decides it against the decision's own ``decided_at`` (ADR-0193 §1, §6).
        A revoking record's own id answers ``None``, as an absent one does.
        """
        found = next(
            (held for held in self._outstanding() if held.id == grant_id),
            None,
        )
        return None if found is None else found.model_copy(deep=True)

    def standing(self, instant: datetime) -> list[RecipientGrant]:
        """Detached copies of every grant live at ``instant``.

        Computed from the same :meth:`_live` the per-request answer uses, which is
        the point of the log being shared: an enumeration free to compute liveness
        its own way is free to disagree with the gate, and the one that disagreed
        would still pass its own suite.

        **Complete or nothing**, whatever the ceiling now says: a store holding
        records a newly lowered ceiling would not admit is a legal state, and a
        query that hid them would be lying to the user about their own standing
        policy (ADR-0193 §1).
        """
        return [held.model_copy(deep=True) for held in self._live(instant)]

    def ordered(self) -> list[RecipientGrant]:
        """Every record by ``decided_at`` descending, ``id`` ascending.

        Two passes over a stable sort rather than one composite key, because the
        two halves run in opposite directions and ``datetime`` has no negation —
        ``FakeAuditTrail._ordered``'s shape.
        """
        by_id = sorted(self._records, key=lambda held: held.id)
        return sorted(by_id, key=lambda held: held.decided_at, reverse=True)

    def snapshots(self, limit: int | None = None) -> list[RecipientGrant]:
        """Detached copies of the newest ``limit`` records, or of all of them."""
        ordered = self.ordered()
        return [
            held.model_copy(deep=True) for held in (ordered if limit is None else ordered[:limit])
        ]

    def under(self, max_outstanding: int) -> _RecipientGrantLog:
        """A second view of **this** history under a different ceiling.

        What a durable store's reopen is, for a fake that has no file: the record
        list is the same object, so a write through either view is visible through
        both, and only the admission ceiling differs. That is the whole of what
        changes when a deployment edits ``Settings`` and restarts, and it is the
        one arrangement ADR-0193 §1's admission-not-eviction clause needs — a store
        holding records a newly lowered ceiling would not admit is a *legal* state,
        and it is unreachable through a constructor that applies the new ceiling to
        the seed.
        """
        view = _RecipientGrantLog(max_outstanding=max_outstanding)
        # One history, two admission ceilings: the list is the same object.
        view._records = self._records
        return view

    def clear(self) -> int:
        """Drop every record, returning the number removed.

        **Every** record — live, expired, revoked and revoking alike — because
        that is what the count means (ADR-0193 §9). It retains nothing: no id, no
        tombstone, no derived value, so an id held before this may be recorded
        again afterwards.
        """
        removed = len(self._records)
        self._records.clear()
        return removed


@final
class FakeRecipientGrants:
    """A query-only ``RecipientGrants`` test double (ADR-0193 §1, §7).

    Structurally implements
    :class:`~ai_assistant.core.protocols.RecipientGrants` and **nothing wider**:
    it has no ``record``, no ``outstanding``, no ``standing``, no ``recent``, no
    ``export`` and no ``clear``, so a policy's test cannot accidentally arrange
    state through the subject the policy is supposed to hold, and cannot resolve
    an id through it either. That is the point of the split being a type rather
    than a promise, modelled in the fake as well as in the contract.

    A test arranges history through :meth:`hold` or through the constructor, both
    of which apply the same invariants a real store's ``record`` does — so a
    script this fake could only honour by breaking its own contract fails where it
    was written.

    Beyond the contract it counts its calls and takes two scripts —
    :meth:`fail_covering` and its initial records. Neither is contract; only the
    behaviour pinned by the shared ``RecipientGrants`` conformance suite is. The
    call count is what ADR-0193 §14's lookup clauses are asserted over: a policy
    consulting the seam on a path the request alone settles is a policy letting a
    store failure disturb an answer that was already given.
    """

    def __init__(
        self,
        records: Sequence[RecipientGrant] = (),
        *,
        now: Callable[[], datetime] = lambda: RECIPIENT_GRANT_NOW,
        max_outstanding: int = 64,
        failure: Exception | None = None,
    ) -> None:
        """Create the fake.

        Args:
            records: The history this fake starts with, applied in order under a
                real store's invariants. Grants, revocations, or both.
            now: The clock :meth:`covering` evaluates liveness against, read
                **once** per call. Defaults to :data:`RECIPIENT_GRANT_NOW`, which sits
                inside every default grant's interval.
            max_outstanding: ADR-0193 §1's ceiling, applied to ``records``.
            failure: Scripted at construction, for a test that wants every
                ``covering`` to raise from the start; :meth:`fail_covering` is
                the same script applied later. The raised error is always a
                :class:`~ai_assistant.core.errors.RecipientGrantError` wrapping
                this as ``__cause__``, because that is what the seam may raise.

        Raises:
            InvalidRecipientGrantError: If ``records`` is not a history a
                conforming store could hold.
            ValueError: If ``max_outstanding`` is negative.
        """
        self._log = _RecipientGrantLog(max_outstanding=max_outstanding)
        self._clock = checked_clock(now, owner="FakeRecipientGrants")
        self._failure = failure
        self._calls = 0
        for record in records:
            self._log.append(record)

    @property
    def call_count(self) -> int:
        """How many times :meth:`covering` has been called."""
        return self._calls

    def hold(self, *records: RecipientGrant) -> None:
        """Add ``records`` to this fake's history.

        **Test-only, and deliberately not named ``record``.** ADR-0193 §1 removes
        the recording capability from the type a *policy* names; this is a lever
        on the fake itself, reached by the test that built it and never by the
        code under test, which only ever sees the ``RecipientGrants`` annotation.
        Nothing production can reach it either — ``lint-imports`` keeps
        ``ai_assistant.testing`` out of every shipping package.

        Args:
            records: Grants and revocations, applied in order.

        Raises:
            InvalidRecipientGrantError: If the resulting history is one no
                conforming store could hold.
        """
        for record in records:
            self._log.append(record)

    def fail_covering(self, error: Exception | None = None) -> None:
        """Arm every subsequent :meth:`covering` to raise.

        Required of this fake by ADR-0193 §14 and not decoration: §1's
        fail-closed clause is otherwise untestable, because a policy's
        ``RecipientGrantError`` branch is unreachable from any test — and an
        implementation that caught the error and carried on with the last
        successful lookup would pass every other policy test while authorising
        sends after its authorisation stopped being checkable.

        Args:
            error: The underlying fault to model, preserved as ``__cause__``.
                ``None`` models a bare store fault with no interesting cause.
        """
        self._failure = (
            error if error is not None else RuntimeError("fake: the store is unreadable")
        )

    async def covering(self, request: ActionRequest) -> RecipientGrant | None:
        """Return the live grant covering ``request``, or ``None``.

        Returns:
            A detached snapshot of the covering grant, or ``None`` when none
            covers it. Detached because this is an answer the gate rests on:
            ``frozen=True`` would not stop a caller widening ``destinations``
            through ``__dict__`` on a shared object, which is the gate defeated
            through its own answer (ADR-0193 §1).

        Raises:
            RecipientGrantError: If a failure is scripted
                (:meth:`fail_covering`), wrapping it as ``__cause__``.
        """
        self._calls += 1
        if self._failure is not None:
            msg = "fake: the recipient-grant store could not be read"
            raise RecipientGrantError(msg) from self._failure
        return self._log.covering(request, self._clock())


@final
class FakeRecipientGrantResolution:
    """A resolve-only ``RecipientGrantResolution`` test double (ADR-0193 §1, §6).

    Structurally implements
    :class:`~ai_assistant.core.protocols.RecipientGrantResolution` and **nothing
    wider**: it has no ``record``, no ``covering``, no ``standing`` and no
    ``clear``. A trail handed the whole store would be one ``record`` call away
    from authorising the row it is about to validate, and nothing about the
    resulting store would look wrong afterwards — which is why the capability is
    removed from the type the trail names, here as in the contract.

    It carries **no clock**, and that absence is the contract rather than an
    economy: outstanding is a fact about two records, so an expired but unrevoked
    grant is returned rather than withheld, and expiry is decided by
    ``AuditTrail.record`` against the decision's own ``decided_at`` (ADR-0193 §6).

    Beyond the contract it counts its calls and takes two scripts —
    :meth:`fail_outstanding` and its initial records — so ADR-0193 §14's scope
    clause is assertable: a non-resolving ``ALLOW`` with no ``egress_binding`` is
    recorded **without this seam being consulted at all**.
    """

    def __init__(
        self,
        records: Sequence[RecipientGrant] = (),
        *,
        max_outstanding: int = 64,
        failure: Exception | None = None,
    ) -> None:
        """Create the fake.

        Args:
            records: The history this fake starts with, applied in order under a
                real store's invariants.
            max_outstanding: ADR-0193 §1's ceiling, applied to ``records``.
            failure: Scripted at construction, for a test that wants every
                ``outstanding`` to raise from the start.

        Raises:
            InvalidRecipientGrantError: If ``records`` is not a history a
                conforming store could hold.
            ValueError: If ``max_outstanding`` is negative.
        """
        self._log = _RecipientGrantLog(max_outstanding=max_outstanding)
        self._failure = failure
        self._calls = 0
        for record in records:
            self._log.append(record)

    @property
    def call_count(self) -> int:
        """How many times :meth:`outstanding` has been called."""
        return self._calls

    def hold(self, *records: RecipientGrant) -> None:
        """Add ``records`` to this fake's history, under a real store's invariants.

        Args:
            records: Grants and revocations, applied in order.

        Raises:
            InvalidRecipientGrantError: If the resulting history is one no
                conforming store could hold.
        """
        for record in records:
            self._log.append(record)

    def fail_outstanding(self, error: Exception | None = None) -> None:
        """Arm every subsequent :meth:`outstanding` to raise.

        Required of this fake by ADR-0193 §14: without it the trail's
        fail-closed branch is unreachable, and an implementation that treated an
        unreadable seam as "no grant named" — or worse, as "carry on" — would
        pass every other trail test while writing rows whose authorisation was
        never checked.

        Args:
            error: The underlying fault, preserved as ``__cause__``.
        """
        self._failure = (
            error if error is not None else RuntimeError("fake: the store is unreadable")
        )

    async def outstanding(self, grant_id: str) -> RecipientGrant | None:
        """Return the outstanding granting record with ``grant_id``, or ``None``.

        Raises:
            RecipientGrantError: If a failure is scripted
                (:meth:`fail_outstanding`), wrapping it as ``__cause__``.
        """
        self._calls += 1
        if self._failure is not None:
            msg = "fake: the recipient-grant store could not be read"
            raise RecipientGrantError(msg) from self._failure
        return self._log.outstanding(grant_id)


@final
class FakeRecipientGrantStore:
    """A non-persistent, append-only ``RecipientGrantStore`` test double.

    Structurally implements
    :class:`~ai_assistant.core.protocols.RecipientGrantStore` — and therefore
    :class:`~ai_assistant.core.protocols.RecipientGrants` and
    :class:`~ai_assistant.core.protocols.RecipientGrantResolution` too, which is
    why the two narrow conformance suites are bound against this class as well as
    against their own fakes. That binding is what turns ADR-0193 §1's "one
    concrete store satisfies all three faces" from an assertion into a test.

    :meth:`record`'s checks and its append are separated by no interleaving point,
    which is how the atomicity ADR-0193 §1 requires is obtained on a single event
    loop: two concurrent grants of **different** subjects at one below the ceiling
    cannot both observe room. Every method — the two writes and the four reads —
    runs inside a :class:`~ai_assistant.testing.cancellation.SuspendableResource`,
    so the fake is a real subject for ADR-0060's cancellation clause at each of the
    lock sites a durable store would have. That does not weaken the atomicity
    argument: acquiring an uncontended :class:`asyncio.Lock` does not suspend, so
    nothing runs between the checks and the append that did not before, and under
    contention the lock serialises the pair outright.
    """

    def __init__(
        self,
        records: Sequence[RecipientGrant] = (),
        *,
        now: Callable[[], datetime] = lambda: RECIPIENT_GRANT_NOW,
        max_outstanding: int = 64,
    ) -> None:
        """Create the store.

        Args:
            records: The history it starts with, applied in order under the same
                invariants :meth:`record` applies.
            now: The clock :meth:`covering` and :meth:`standing` evaluate liveness
                against, read **once** per call.
            max_outstanding: ADR-0193 §1's ceiling on outstanding granting
                records, which a deployment reads from
                ``Settings.recipient_grant_max_outstanding``. Zero is meaningful
                and admitted: it declines the *next* grant and retracts none.

        Raises:
            InvalidRecipientGrantError: If ``records`` is not a history a
                conforming store could hold.
            ValueError: If ``max_outstanding`` is negative.
        """
        self._log = _RecipientGrantLog(max_outstanding=max_outstanding)
        self._clock = checked_clock(now, owner="FakeRecipientGrantStore")
        self._resource = SuspendableResource()
        self._read_failure: Exception | None = None
        self._write_failure: Exception | None = None
        for record in records:
            self._log.append(record)

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next call that enters the modelled resource open inside it.

        There is one modelled resource and every method enters it, so this
        suspends whichever call arrives next rather than a named operation. The
        hook the cancellation case takes (ADR-0060 §3); test-only, and not part of
        the contract.

        Returns:
            The handle to wait on and release.
        """
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log

    def fail_reads(self, error: Exception | None = None) -> None:
        """Arm every subsequent read to raise a store fault.

        Required of this fake as well as of the two narrow ones: a policy handed
        the store as its ``RecipientGrants``, or a trail handed it as its
        ``RecipientGrantResolution``, must exhibit the same fail-closed branch,
        and a capability present on only one of the faces would leave that wiring
        untestable.

        Args:
            error: The underlying fault, preserved as ``__cause__``.
        """
        self._read_failure = (
            error if error is not None else RuntimeError("fake: the store is unreadable")
        )

    def fail_writes(self, error: Exception | None = None) -> None:
        """Arm every subsequent :meth:`record` and :meth:`clear` to raise a store fault.

        A **store fault**, not a refusal: it raises
        :class:`~ai_assistant.core.errors.RecipientGrantError` rather than
        :class:`~ai_assistant.core.errors.InvalidRecipientGrantError`, because a
        refusal is what the invariants already produce from a badly-formed record
        and a caller arranging one of those builds the record instead. What this
        scripts is the other failure — "the store could not be written" — which no
        well-formed input can provoke.

        Args:
            error: The underlying fault, preserved as ``__cause__``.
        """
        self._write_failure = (
            error if error is not None else RuntimeError("fake: the store is unwritable")
        )

    def _refuse_read(self) -> None:
        """Raise the scripted read fault, if one is armed.

        Raises:
            RecipientGrantError: If :meth:`fail_reads` armed one.
        """
        if self._read_failure is not None:
            msg = "fake: the recipient-grant store could not be read"
            raise RecipientGrantError(msg) from self._read_failure

    async def record(self, grant: RecipientGrant) -> str:
        """Append ``grant`` and return its id.

        The invariant checks are *inside* the resource, not before it: a caller
        that validated against a store it no longer holds could pass a duplicate,
        a duplicate-subject or a ceiling check that the append then contradicts.
        This is where the class docstring's "no interleaving point between the
        checks and the append" is actually kept once there is a lock at all.

        Raises:
            RecipientGrantError: If a store fault is scripted (:meth:`fail_writes`).
            InvalidRecipientGrantError: If the record does not satisfy its own
                model, if its id is already recorded, if a granting record
                duplicates an outstanding grant's subject or would breach the
                ceiling, or if it revokes and fails any of ADR-0193 §1's
                invariants.
        """
        if self._write_failure is not None:
            msg = "fake: the recipient-grant store could not be written"
            raise RecipientGrantError(msg) from self._write_failure
        async with self._resource.held():
            return self._log.append(grant)

    async def covering(self, request: ActionRequest) -> RecipientGrant | None:
        """Return the live grant covering ``request``, or ``None``.

        Read inside the modelled resource, like every other method: a durable
        store would answer this from under its connection lock, so it is one of
        the lock sites ADR-0060's clause binds. The clock is read **once**, inside
        the resource, and every record considered is evaluated against that
        instant.

        Raises:
            RecipientGrantError: If a read fault is scripted (:meth:`fail_reads`).
        """
        self._refuse_read()
        async with self._resource.held():
            return self._log.covering(request, self._clock())

    async def outstanding(self, grant_id: str) -> RecipientGrant | None:
        """Return the outstanding granting record with ``grant_id``, or ``None``.

        Reads no clock, as the narrow face does not: an expired but unrevoked
        grant is returned rather than withheld.

        Raises:
            RecipientGrantError: If a read fault is scripted (:meth:`fail_reads`).
        """
        self._refuse_read()
        async with self._resource.held():
            return self._log.outstanding(grant_id)

    async def standing(self) -> list[RecipientGrant]:
        """Return every live grant, detached (ADR-0193 §1).

        Computed from the same shared log the per-request answer uses, so this
        fake cannot agree with the gate about one request and disagree about the
        set, and against **one** clock reading, so it cannot return a set true at
        no real instant.

        Raises:
            RecipientGrantError: If a read fault is scripted (:meth:`fail_reads`).
        """
        self._refuse_read()
        async with self._resource.held():
            return self._log.standing(self._clock())

    async def recent(self, *, limit: int = 50) -> list[RecipientGrant]:
        """Return up to ``limit`` records, newest first, ties broken by id.

        Raises:
            ValueError: If ``limit`` is not strictly positive.
            RecipientGrantError: If a read fault is scripted (:meth:`fail_reads`).
        """
        if limit <= 0:
            msg = f"limit must be strictly positive, got {limit}"
            raise ValueError(msg)
        self._refuse_read()
        async with self._resource.held():
            return self._log.snapshots(limit)

    async def export(self) -> list[RecipientGrant]:
        """Return **every** record, in :meth:`recent`'s order.

        Live, expired, revoked and revoking records alike: this is what
        discharges ADR-0004 §6's portability obligation for the store, so it omits
        nothing.

        Raises:
            RecipientGrantError: If a read fault is scripted (:meth:`fail_reads`).
        """
        self._refuse_read()
        async with self._resource.held():
            return self._log.snapshots()

    async def clear(self) -> int:
        """Delete every record, returning the number removed.

        The body runs inside the modelled resource for :meth:`record`'s reason and
        for one of its own: the count returned must describe the deletion that
        actually happened, and sizing the log outside the resource would let a
        concurrent ``clear`` land between the two and let both callers report
        removing the same records.

        Raises:
            RecipientGrantError: If a store fault is scripted (:meth:`fail_writes`).
        """
        if self._write_failure is not None:
            msg = "fake: the recipient-grant store could not be written"
            raise RecipientGrantError(msg) from self._write_failure
        async with self._resource.held():
            return self._log.clear()

    def reopened_at(self, max_outstanding: int) -> FakeRecipientGrantStore:
        """This store's **own history** under a different admission ceiling.

        Test-only. What a durable store does when a deployment edits
        ``Settings.recipient_grant_max_outstanding`` and restarts: the records are
        the same records, and only what the store will *admit* next has changed.
        A fake reconstructed from ``export()`` cannot model it — the seed would be
        applied under the new ceiling and refused — so a store above a newly
        lowered ceiling, which ADR-0193 §1 calls a **legal** state, would be
        unreachable from any test and the admission-not-eviction clause would have
        nothing exercising it.

        The clock and the scripted faults are **not** carried over: this is a
        restart, and a fault armed on the old object is a fault of that object.
        The clock is, because liveness is a property of the history rather than of
        the process reading it.

        Args:
            max_outstanding: The ceiling the reopened store admits under. Zero is
                meaningful and admitted.

        Returns:
            A second store over the same history.
        """
        reopened = FakeRecipientGrantStore(max_outstanding=max_outstanding)
        # One history, two views; the clock belongs to the history rather than
        # to the process reading it.
        reopened._log = self._log.under(max_outstanding)
        reopened._clock = self._clock
        return reopened


__all__ = [
    "RECIPIENT_GRANT_ACCOUNT",
    "RECIPIENT_GRANT_ADDRESS",
    "RECIPIENT_GRANT_DECIDED_AT",
    "RECIPIENT_GRANT_EXPIRES_AT",
    "RECIPIENT_GRANT_NOW",
    "RECIPIENT_GRANT_TOOL",
    "FakeRecipientGrantResolution",
    "FakeRecipientGrantStore",
    "FakeRecipientGrants",
    "account_member",
    "recipient",
    "recipient_grant",
    "recipient_revocation_of",
]
