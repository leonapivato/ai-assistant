"""Proposing a goal authorization against a `CONFIRM`, and its expiry ladder.

ADR-0254 §1's **path (i)**: the durable row is written **before the question is
put**, `PROPOSED`, and is settled by the answer — ADR-0244's ratified shape for
exactly this problem, *"a durable row carrying what is put to the user, settled by
a later answer, surviving a restart, with its deadline computed … once, at the
instant the park is written"*. ADR-0254 §11's projection is rendered from that row,
so a restart between the question and the answer changes neither the coverage nor
the instant the user was shown.

**Everything here is a total function of values in hand**, so the rules ADR-0254 §1
states about *which* `CONFIRM` proposes a row are checkable in one place rather
than spread through a dispatch path. The writer that calls them is
:class:`~ai_assistant.orchestration.runner.StepRunner`, which is ADR-0254 §15's
*"written and settled by `orchestration` and by nothing else"*.

**What is deliberately absent, and why it is a hole rather than an omission.**
ADR-0254 requires a row's `coverage` to be minted from the user's own recorded
words — a `CoverageMember` naming an argument and fixing or bounding it, on a basis
naming a recorded turn and a span of its utterance. **No clause of ADR-0254,
ADR-0256, ADR-0249, ADR-0252 or ADR-0253 says how a span is associated with an
argument key, nor how the member's shape is chosen** (issue #2373, ruled into
ADR-0266). §10's three resolutions each turn a span into a *value* and none selects
the span or names the argument; §9 clause (ii) states the property the association
must have rather than a procedure; and §9's no-model clause forecloses the planner.
So this module mints **no member at all**, which is §10's own fail-closed sentence —
*"A resolution the loop cannot take is not taken, and no member is minted"* — and
ADR-0254 §1's completeness condition therefore holds only where it holds
**vacuously**, on a request carrying no user-facing argument. That is §20's arm 54
and arm 59's third case, and it is an authority over an argument-free call rather
than a wildcard over anything (§3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    Authorization,
    AuthorizationDisposition,
    AuthorizationOrigin,
    EgressBinding,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime, timedelta

    from ai_assistant.core.types import ActionRequest, Goal, PermissionDecision


#: The namespace every id derived from a confirmation is written under
#: (:func:`authorization_id_for`). One literal, defined once, because the writer
#: and the reader must agree on it exactly or a settlement silently finds nothing.
_DERIVED_ID_PREFIX: Final = "goal-authorization-for-confirmation:"


def user_facing_arguments(request: ActionRequest, /) -> tuple[str, ...]:
    """The request's arguments that are **not** system-supplied (ADR-0254 §3).

    *"`ToolDefinition` gains one field: `system_supplied` … naming the keys of
    `parameters` the **system** fills … Every key it does not name is
    **user-facing**"*, and *"A declaration that classifies no argument
    system-supplied has every argument user-facing"*.

    The classification is read off the request's own declaration, which is the
    one embedded whole in the row a proposal would carry (ADR-0254 §1), so the
    two facts a completeness test needs cannot come apart.

    Args:
        request: The concrete request being ruled on.

    Returns:
        The user-facing keys, in the request's own iteration order.
    """
    supplied = frozenset(request.tool.system_supplied)
    return tuple(key for key in request.parameters if key not in supplied)


def horizon(
    proposed_at: datetime, *, goal: Goal | None, retention: timedelta | None
) -> datetime | None:
    """ADR-0254 §12's ladder, as ADR-0256 §1 leaves it, or ``None`` for no row.

    Taken **in order**, at the instant a path-(i) or path-(iii) row is written, and
    never on a path-(ii) correction, which transcribes the row it supersedes.

    1. **The instant the user's own act states** — ADR-0254 §12's rung 1, resolved
       by `DATE_FROM_CONTEXT` or `AS_STATED` under §9's clauses entire. **It is
       unreachable here**, because those are §10's resolutions and §10's resolutions
       are what #2373 blocks; see this module's own docstring. It is *not* skipped
       silently: on path (i) the instant this ladder does yield is put in front of
       the user by ADR-0254 §11's projection **before they answer**, which is that
       section's whole claim — *"the user reads it before answering"* — so a horizon
       taken from a lower rung is one the answer is given about. That argument is
       path (i)'s alone and does **not** carry to a path-(iii) opening act, where no
       question is put; path (iii) is blocked on #2373 in any case.
    2. **The goal's own `deadline`**, transcribed unchanged, where it is **strictly
       after** ``proposed_at``. *"an authority about that objective outliving it
       would authorise calls toward a goal whose own moment has passed."* A
       `deadline` at or before ``proposed_at`` does **not** take this rung and falls
       through, which is ADR-0256 §9's *"A stale or equal `deadline` reaches rung 3,
       not rung 2"*.
    3. **``proposed_at`` advanced by the deployment's turn-retention window**
       (ADR-0256 §1), where that window is finite. `Settings.episode_retention` is
       refused at load unless strictly positive, so the sum is strictly after
       ``proposed_at`` and ADR-0254 §1's construction refusal never fires on this
       rung. Where the addition cannot be taken at all — a reading near
       ``datetime.max`` — **no row is written** (ADR-0256 §2): *"Nothing is clamped,
       rounded, saturated or defaulted."*
    4. **No row at all**, where the window is ``None``. *"`None` is 'keep forever' …
       the deployment where this rung fires is one where a user has deliberately
       said that nothing lapses — and inventing a horizon for an authority there
       would be minting exactly the figure §12 forbids"* (ADR-0256 §3).

    **The window is read once, here, and is never recomputed** (ADR-0256 §2): a
    later change to `episode_retention` moves no row already written, and neither
    does a later edit to the goal's `deadline` (ADR-0254 §12).

    Args:
        proposed_at: The instant the row is written with, which on path (i) is the
            recorded `CONFIRM`'s own ``decided_at``.
        goal: The goal the authority is about, or ``None`` where the store no
            longer holds it — which takes rung 2 out and is not an error.
        retention: The deployment's turn-retention window, or ``None`` where it
            keeps turns forever.

    Returns:
        The instant the row expires, or ``None`` where the ladder yields none and
        no row is written.
    """
    if goal is not None and goal.deadline is not None and goal.deadline > proposed_at:
        return goal.deadline
    if retention is None:
        return None
    try:
        reached = proposed_at + retention
    except OverflowError, OSError, ValueError:
        # ADR-0256 §2's arithmetic edge. `checked_clock` admits a reading near
        # `datetime.max` (ADR-0026 §3), and the ladder's answer there is no row
        # rather than a saturated instant.
        return None
    return reached if reached > proposed_at else None


def proposed_authorization(
    request: ActionRequest,
    decision: PermissionDecision,
    /,
    *,
    goal: Goal | None,
    retention: timedelta | None,
    standing: Sequence[Authorization],
) -> Authorization | None:
    """The row this `CONFIRM` proposes, or ``None`` where it proposes none.

    ADR-0254 §1, *"which `CONFIRM` proposes a row, stated because §11's absence rule
    needs it"*. A path-(i) proposal is written where **all four** hold:

    - **the request carries a `goal`** — *"a request carrying `None` reaches route
      (d) in no case, so a row proposed against one could authorise nothing"*;
    - **the request is an egress call**, its `egress_binding` not ``None`` —
      *"every clause of this decision is scoped to one"*. A binding that records
      neither its origin nor its coverage is not one either: the row's
      `destinations` are `EgressBinding.canonical_destination_set` in that type's
      one canonical order, and a shape that cannot state the set cannot found an
      authority over it;
    - **the coverage would be complete for this request** — every user-facing
      argument named by a member. **Here that is only ever vacuous** (module
      docstring, #2373): a request carrying a user-facing argument proposes
      nothing, which is §20 arm 59's third case, *"a `CONFIRM` on an egress request
      one of whose arguments no resolution minted a member for → no row is
      written"*;
    - **and the ladder yields an `expires_at`** (:func:`horizon`).

    Failing any of the four, **no row is proposed**, `Confirmation.authorization` is
    absent (§11), and the answer establishes nothing: the `CONFIRM` is resolved and
    the one call is authorised by ADR-0148 §3's route (a), which is the path that
    exists today and is unchanged.

    **It names a standing row of that pair in `supersedes` where one exists.** §1
    permits a path-(i) proposal to name *"any `ESTABLISHED` row of the same `goal`
    and the same declaration `id`, live or expired"*, and it is what keeps the
    uniqueness rule satisfiable: approving a second row of one pair would otherwise
    answer `WOULD_DUPLICATE` and establish nothing. **The proposal retires
    nothing** — the named row is settled `SUPERSEDED` in the same write as this
    row's `ESTABLISHED` settlement, and only where it still stands `ESTABLISHED`
    then (§1's conditional-supersession clause) — so a declined widening leaves the
    predecessor exactly as it was. *"That is what renews an authority whose expiry
    has passed as well as what widens a live one."*

    **No floor of §6's is read here, and that is deliberate** (§1). Conditions 3, 4
    and 5 of route (d)'s reachability are taken over a concrete request at every
    dispatch, so a row proposed against a request whose binding carried
    `planned_with_external_content` authorises no such dispatch and may still cover
    a later request of that goal that carries none.

    Args:
        request: The request the ruling was taken over.
        decision: The recorded `CONFIRM` the question rides. Its ``decided_at`` is
            the row's ``proposed_at`` and its ``id`` is the row's ``confirmation``.
        goal: The goal, for rung 2 of the ladder.
        retention: The deployment's turn-retention window, for rung 3.
        standing: The `ESTABLISHED` rows of that goal, live and lapsed, as
            `GoalAuthorizationStore.standing` returns them.

    Returns:
        The row to record `PROPOSED`, or ``None`` where this `CONFIRM` proposes
        none.
    """
    if request.goal is None:
        return None
    binding = request.egress_binding
    if not isinstance(binding, EgressBinding):
        return None
    if user_facing_arguments(request):
        # #2373: no member can be minted, so the completeness condition can only
        # hold vacuously. This is the fail-closed direction and the ruled one --
        # the concrete call is confirmed under route (a) exactly as it is today.
        return None
    expires_at = horizon(decision.decided_at, goal=goal, retention=retention)
    if expires_at is None:
        return None
    return Authorization(
        id=authorization_id_for(decision.id),
        goal=request.goal,
        tool=request.tool,
        account=binding.account,
        destinations=binding.canonical_destination_set,
        origin=AuthorizationOrigin.CONFIRMED,
        coverage=(),
        proposed_at=decision.decided_at,
        expires_at=expires_at,
        confirmation=decision.id,
        supersedes=_superseded(standing, request),
        disposition=AuthorizationDisposition.PROPOSED,
        settled_at=None,
    )


def _superseded(standing: Sequence[Authorization], request: ActionRequest, /) -> str | None:
    """The `ESTABLISHED` row of this goal and declaration id, or ``None``.

    ADR-0254 §1 makes the uniqueness key *"the id and not the declaration by
    value"*, which is stricter than a value key and is what `live_for` rests on, so
    the row a proposal must name is found the same way. `standing` returns the
    `ESTABLISHED` rows of the goal, **live and lapsed**, and there is at most one of
    that pair — the store refuses a second.
    """
    for row in standing:
        if row.tool.id == request.tool.id:
            return row.id
    return None


def authorization_id_for(confirmation_id: str, /) -> str:
    """The id of the row a `CONFIRM` proposes, **derived from that decision's id**.

    ADR-0254 §16 closes `GoalAuthorizationStore` at eight signatures and none of
    them is a lookup by ``confirmation``, so the answer that settles a proposal has
    to find the row some other way. Reading back over `recent` was that way, and it
    carried a finite-history assumption: a proposal displaced past the page by newer
    rows of *other* goals was never settled, and the authority the user had granted
    was silently lost (issue #2375).

    **Deriving the id removes the search instead of widening it.** One `CONFIRM`
    proposes at most one row (:func:`proposed_authorization` is called once per
    recorded decision, and the trail refuses a duplicate decision id), so the
    confirmation's id is already a unique name for that row — and §16's keyed
    :meth:`~ai_assistant.core.protocols.GoalAuthorizationStore.resolve` then finds
    it exactly, at any age, with no page, no limit and no ordering assumption. No
    store signature is added, no `core` type gains a field, and ADR-0254 §1's
    *"minted by the caller that records it"* is satisfied by a caller that derives
    rather than draws: what it forbids is a **store** minting the id, and this is
    still `orchestration` naming its own row.

    **The prefix is what makes the derivation collision-free**, not a decoration.
    An `Authorization` id is an
    :data:`~ai_assistant.core.types.DurableIdentifier` — non-blank encodable text
    and nothing narrower — so a row minted by any other route could in principle
    carry any string. Namespacing every derived id under one prefix that no
    id-minting seam on this tree produces keeps the derived names disjoint from the
    drawn ones by construction rather than by probability.

    **It is not read back as a confirmation id.** The caller that resolves a row
    checks the row's own ``confirmation`` field against the answered decision
    (:meth:`~ai_assistant.orchestration.runner.StepRunner._settle`), so the id is a
    lookup key and never the evidence that one row answers one question.

    Args:
        confirmation_id: The id of the recorded `CONFIRM` the row is proposed
            against — `PermissionDecision.id`, which is also the row's
            ``confirmation``.

    Returns:
        The row's id.
    """
    return f"{_DERIVED_ID_PREFIX}{confirmation_id}"


__all__ = [
    "authorization_id_for",
    "horizon",
    "proposed_authorization",
    "user_facing_arguments",
]
