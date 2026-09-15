"""What a surface is shown about an authorization, and the two acts on one.

ADR-0254 §11's read side: the projection a `CONFIRM` carries, the view a listing and
an announcement carry, the listing itself, and the revocation. **Everything here is a
transcription** (ADR-0178 §5, ADR-0150 §10) — the values a surface renders are read
off the durable row and are never a second derivation of them.

**The engine assembles them because an adapter may read neither a store, a trail nor
a** :class:`~ai_assistant.core.types.PermissionDecision` (ADR-0042 §6). So the store
reads, the clock reading and the goal lookup happen here, once, and what crosses to a
client is data.

**The rendering bar is enforced by the carriers rather than restated here** (ADR-0254
§11, ADR-0193 §11). :class:`~ai_assistant.core.types.AuthorizationView` has no field
for a subject digest, a :class:`~ai_assistant.core.types.BoundAccount`, an account or
connection reference, a ``confirmation``, a ``supersedes``, a resolution or a
``destinations`` set, and :class:`~ai_assistant.core.types.AuthorizationProjection`
has no field for an identifier of any kind — so this module cannot leak one by
forgetting a rule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    AuthorizationDisposition,
    AuthorizationProjection,
    AuthorizationSettlement,
    AuthorizationView,
    CoverageView,
)
from ai_assistant.orchestration.authorizing import authorization_id_for

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import GoalAuthorizationStore, PlanStore
    from ai_assistant.core.types import Authorization


def coverage_views(row: Authorization, /) -> tuple[CoverageView, ...]:
    """One :class:`CoverageView` per member of ``row``, in the record's own order.

    **Transcribed and never recomputed** (ADR-0254 §11, ADR-0178 §5): the argument,
    the fixed value or the bound, and the user's own words come off the member, and
    the order is the record's — ADR-0254 §3's comparison is per argument and reads no
    order, so nothing here sorts.

    **The span and nothing else of the basis** (§11). The act the member rests on,
    the rule that resolved it, the ``now`` that was read, the zone and the record it
    resolved to are provenance for an auditor and reach one through ``export``; *"no
    surface renders a resolution as a justification, a confidence, an assurance or a
    reason to trust the value more"*.

    Args:
        row: The record to project.

    Returns:
        A view per member, possibly empty — an act that fixed nothing is an authority
        over an argument-free call and is a wildcard over nothing (§1).
    """
    return tuple(
        CoverageView(
            argument=member.argument,
            fixed=member.fixed,
            bound=member.bound,
            span=member.basis.span,
        )
        for member in row.coverage
    )


def projection_of(row: Authorization, /) -> AuthorizationProjection:
    """What answering the question this row was proposed for would establish (§11).

    Rendered **from the proposed row**, so a restart between the question and the
    answer recovers the row and renders this same projection (ADR-0052 §1).

    Args:
        row: The ``PROPOSED`` row the question is about.

    Returns:
        The coverage the answer would establish and the instant it would expire.
    """
    return AuthorizationProjection(coverage=coverage_views(row), expires_at=row.expires_at)


def view_of(row: Authorization, /, *, goal_statement: str, live: bool) -> AuthorizationView:
    """One standing row, as a listing or an announcement renders it (§11).

    Args:
        row: The ``ESTABLISHED`` record to project.
        goal_statement: The goal's current outcome statement, read through
            :meth:`~ai_assistant.core.protocols.PlanStore.get_goal` — **the goal is
            rendered by statement and never by id** (§11).
        live: Whether the row is live at the caller's **one** clock reading (§16).

    Returns:
        The view, carrying the row's ``id`` as the revocation handle and no other
        internal value.
    """
    return AuthorizationView(
        id=row.id,
        goal_statement=goal_statement,
        tool=row.tool,
        coverage=coverage_views(row),
        expires_at=row.expires_at,
        live=live,
    )


def is_live(row: Authorization, reading: datetime, /) -> bool:
    """Whether ``row`` is live at ``reading``, by ADR-0254 §1's own predicate.

    **This is the comparison §16 assigns to the caller and not a second liveness
    seam.** ``standing`` *"evaluates no liveness, reports none and reads none: it
    returns the rows, each carrying its own ``expires_at``, and **the caller
    compares**"*, and ``live_for`` — the store's only liveness evaluation — answers a
    different question for a different consumer, the policy, keyed on a goal and a
    declaration. Two readers of one record, each with its own clock reading, is what
    §16 rules; one shared reading across a listing is what ADR-0193 §9 rules.

    **The upper end alone is not the predicate** (§1, §20 arm 71). A row is live where
    the reading is **at or after** ``settled_at`` and **strictly before**
    ``expires_at``, so a clock that has moved backwards reports *not live* rather than
    disagreeing with the trail — which refuses a backdated route-(d) ruling on the
    same two instants. **Equality at the lower end is live**; equality at the upper end
    is not, which is the half-open interval §12's expiry is stated over.

    **A row that is not ``ESTABLISHED`` is never live**, whatever the instants say: a
    proposal is a question and not an authority, and a retired row is spent (§1). The
    disposition test is first and there is no arm on which it is skipped.

    Args:
        row: The record to judge.
        reading: The caller's one clock reading, taken once for a whole listing.

    Returns:
        Whether the authority stands at that instant.
    """
    if row.disposition is not AuthorizationDisposition.ESTABLISHED:
        return False
    settled_at = row.settled_at
    if settled_at is None:  # pragma: no cover — the model pairs the two
        return False
    return settled_at <= reading < row.expires_at


class AuthorizationOperations:
    """ADR-0254 §11's two operations, and the engine's assembly of its two carriers.

    **One object because all four read the same store**, and two holders keyed by it
    could disagree about what stands — the failure ADR-0016 §7 named for two registries
    one seam over. It writes nothing but the revocation ADR-0254 §1's one edge out of
    ``ESTABLISHED`` admits: proposing, settling an answer, correcting and opening are
    :class:`~ai_assistant.orchestration.runner.StepRunner`'s, which is §15's writer
    clause.
    """

    def __init__(
        self,
        *,
        authorizations: GoalAuthorizationStore,
        plans: PlanStore,
        now: Clock,
    ) -> None:
        """Bind the two stores this surface is answered from and the clock it reads.

        Args:
            authorizations: The record store — ``standing``, ``resolve`` and ``settle``
                are the three members this surface uses, and it uses no other.
            plans: Where a goal's **statement** is read from (§11). A goal this store
                does not hold is an empty answer rather than a raise.
            now: The injected clock (ADR-0026). **Read exactly once per listing**
                (§16), because a listing reading an advancing clock per row could
                answer over a set true at no real instant (ADR-0193 §9). **Wrapped
                here**, which is where :func:`~ai_assistant.core.clock.checked_clock`
                says to put it — at the constructor that stores it — so no caller can
                install one this object then reads unguarded.
        """
        self._authorizations = authorizations
        self._plans = plans
        self._clock = checked_clock(now, owner="AuthorizationOperations")

    def _now(self) -> datetime:
        """The guarded clock's reading, as the reading stage's own error (ADR-0026 §4).

        ``core/errors.py`` defines no error for `orchestration`, so §4 gives the failure
        to the **stage**: this is
        :meth:`~ai_assistant.orchestration.recipient_grants.RecipientGrantOperations.
        _now`'s translation one seam over, and it is what makes the ``PlanningError``
        each operation's docstring declares true rather than aspirational. Without it a
        naive reading reaches the listing as a bare ``TypeError`` from an aware/naive
        comparison, and the revocation as a raw store validation failure — neither of
        which any contract here declares. Adversarial and architecture review, round 1,
        ``blocker``.

        **The guard covers the reading and not the invocation** (ADR-0026 §2). An
        exception the injected callable raises *itself* propagates unwrapped — that is
        the clock's own failure, already carrying its own type and cause — and only a
        :class:`~ai_assistant.core.clock.ClockReadingError` is translated.

        Returns:
            The reading.

        Raises:
            PlanningError: If the injected clock's reading is not a conforming one —
                naive, indeterminate, or outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            msg = f"the authorization operations' clock returned a non-conforming reading: {exc}"
            raise PlanningError(msg) from exc

    async def projection_for(self, confirmation_id: str, /) -> AuthorizationProjection | None:
        """The projection a recorded `CONFIRM` carries, or ``None`` where it proposes none.

        **Read back by the derived id and through §16's keyed** ``resolve`` (issue
        #2375), which is the mechanism
        :func:`~ai_assistant.orchestration.authorizing.authorization_id_for` exists
        for: one `CONFIRM` proposes at most one row, so the decision's id is already a
        unique name for it, and no store signature is added, no page is walked and no
        ordering is assumed. **No second mechanism is minted here** — a lookup by
        ``confirmation`` would be a ninth store signature and would need its own
        ratified decision (golden rule 5).

        **Absence is the answer where no row was proposed** (ADR-0254 §1, §11), which
        is every `CONFIRM` failing one of §1's four conditions and every one a stage
        holding no store put. It is **not** a fault: §1 already rules the outcome of
        proposing none — the answer establishes nothing and the one call is authorised
        by ADR-0148 §3's route (a).

        Args:
            confirmation_id: The recorded ``CONFIRM``'s own id.

        Returns:
            The projection, or ``None`` where the store holds no row for it.

        Raises:
            AuthorizationError: If the store could not be read.
        """
        row = await self._authorizations.resolve(authorization_id_for(confirmation_id))
        # **The derived id is a key, never the evidence that a row answers this
        # question** — `StepRunner._settle_authorization`'s own comparison, and it has to
        # be made in both places or the two halves of one mechanism disagree. The store
        # admits a row already occupying the id this `CONFIRM` derives while naming a
        # different confirmation, which `test_a_row_under_that_id_naming_another_question
        # _settles_nothing` pins: the proposal is then refused as a duplicate id, the
        # answer settles nothing, and without this the **question** would meanwhile
        # render the squatter's coverage — telling the user that answering yes
        # establishes limits nothing will establish. Reachable across a restart, where
        # the recovered confirmation is rendered from the store rather than from the
        # proposal this process made. Adversarial review, round 13, `blocker`.
        if row is None or row.confirmation != confirmation_id:
            return None
        return projection_of(row)

    async def standing_authorizations(self, goal_id: str, /) -> tuple[AuthorizationView, ...]:
        """One goal's ``ESTABLISHED`` rows, live and lapsed, projected (§11).

        **One clock reading for the whole listing** (§16), taken before the rows are
        judged, because ``standing`` evaluates no liveness and reports none.

        **One goal read and no other store** (§11). The statement comes from
        :meth:`~ai_assistant.core.protocols.PlanStore.get_goal`, and a goal that store
        does not hold is an **empty answer** rather than a raise — the rows exist, but
        a listing that rendered them with no statement would render a goal by its id,
        which §11 forbids in terms.

        Args:
            goal_id: The goal whose standing authorities to list.

        Returns:
            One view per ``ESTABLISHED`` row, in the store's own order.

        Raises:
            AuthorizationError: If the authorization store could not be read.
            PlanningError: If the plan store could not be read.
        """
        goal = await self._plans.get_goal(goal_id)
        if goal is None:
            return ()
        rows = await self._authorizations.standing(goal_id)
        # **The reading is taken after the snapshot and never before it.** A reading
        # taken first is one the snapshot can outrun: a row settled ``ESTABLISHED``
        # while ``standing`` is suspended comes back with a ``settled_at`` **after**
        # that reading, and §1's predicate then calls a live row not live — a listing
        # true at no real instant, which is the failure ADR-0193 §9's one-reading rule
        # exists to prevent, arrived at from the other side. Taking it here bounds every
        # row's ``settled_at`` below by construction. It also keeps §11's *"a goal that
        # store does not hold is an empty answer rather than a raise"* true of a
        # deployment whose clock is broken. Adversarial review, round 2, ``blocker``.
        reading = self._now()
        return tuple(
            view_of(row, goal_statement=goal.statement, live=is_live(row, reading)) for row in rows
        )

    async def revoke_authorization(self, authorization_id: str, /) -> AuthorizationSettlement:
        """Settle one row ``REVOKED``, and answer with the store's own word (§11, §16).

        **Unmapped and unrenamed.** A second three-valued vocabulary for one fact is
        the second carrier ADR-0150 is named after, so the surface renders prose from
        the member and never a word of its own. **An unknown id is a result and never a
        raise**, and ``WOULD_DUPLICATE`` is unreachable here — it is reachable only on
        a settlement **to** ``ESTABLISHED``, and this settles to ``REVOKED``.

        ``settled_at`` is this object's own clock reading, which is the instant of the
        user's act; a store neither mints ids nor reads a clock (ADR-0021 §3).

        Args:
            authorization_id: The row to withdraw.

        Returns:
            The store's settlement outcome.

        Raises:
            AuthorizationError: If the store could not be read or written.
        """
        return await self._authorizations.settle(
            authorization_id,
            to=AuthorizationDisposition.REVOKED,
            settled_at=self._now(),
        )

    def announced(
        self, opened: Sequence[Authorization], /, *, goal_statement: str
    ) -> tuple[AuthorizationView, ...]:
        """ADR-0254 §11's announcement, for the rows one turn opened without a question.

        **One view per row written, and no row is ever dropped.** §11 states the trigger
        in terms — *"The trigger is that the row was written, and the row is what the
        view is transcribed from"* — with no materiality judgement anywhere in it, so an
        authority that came into being and was **not** announced would be one the user
        holds and was never shown the handle to. An earlier draft read the goal per row
        and skipped one the plan store could not return; a concurrent deletion would then
        have left a standing authority silent. Adversarial review, round 3, ``blocker``.

        **The statement is the turn's own and is not read back.** A path-(iii) row is
        opened for the request this turn is dispatching, and ADR-0250 §3 gives a turn one
        goal — *"every turn resolves its goal before it plans"* — so every row this can
        be handed is of that goal, and the statement the caller already holds is the one
        §11 renders it by. That removes a store read from the announcement entirely,
        which is what makes *"no row is dropped"* a property of the code rather than of
        the store being up.

        **``live`` is read from the row all the same.** A path-(iii) row is written
        ``ESTABLISHED`` with ``settled_at`` equal to ``proposed_at`` and §12's ladder
        puts ``expires_at`` strictly after it, so it is live by construction — but the
        predicate is applied anyway, so an announcement cannot say *live* about a row
        this engine's own clock says has lapsed (§20 arm 71).

        **The reading is taken through this object's own guard** and not handed in. A
        caller reading its clock for us would raise
        :class:`~ai_assistant.core.clock.ClockReadingError`, which is nothing any
        contract on that path declares; ADR-0026 §4 gives the translation to the stage
        that reads, and that is here. Architecture review, round 4, ``blocker``.

        Args:
            opened: The rows this turn opened, in the order they were written.
            goal_statement: The goal's current outcome statement, as the turn holds it.

        Returns:
            One view per row, in that order, and empty where the turn opened none.

        Raises:
            PlanningError: If the injected clock's reading is not conforming.
        """
        if not opened:
            return ()
        reading = self._now()
        return tuple(
            view_of(row, goal_statement=goal_statement, live=is_live(row, reading))
            for row in opened
        )


__all__ = [
    "AuthorizationOperations",
    "coverage_views",
    "is_live",
    "projection_of",
    "view_of",
]
