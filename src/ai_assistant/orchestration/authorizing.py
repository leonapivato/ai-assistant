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

**The completeness condition is asked and never re-implemented** (ADR-0270 §1, §3).
ADR-0266 §7 puts condition 6's *"One implementation, in `permissions`"*, ADR-0254
§15 makes this package the only writer of an `Authorization`, and golden rule 1
forbids this package importing `permissions`. `CoverageAnswers.coverage_met` is
what joins the three: :func:`proposed_authorization` hands it the request and the
coverage the row would carry and reads the answer. It **re-implements no conjunct**
of condition 6 — it evaluates no member, takes neither of §7's two routes, selects
no governing quote, compares no arguments digest and takes no `ValueBound`
comparison — and it **records** `Authorization.quoted` from the answer, performing
no selection of its own (ADR-0270 §2, superseding ADR-0267 §7's selection limb).
Nothing here caches the answer or carries it to a dispatch: ADR-0254 §13's recheck
at `ActionPolicy.decide` is untouched and reads the current governing quote at
every dispatch as if the field were not there.

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
*"A resolution the loop cannot take is not taken, and no member is minted"*. **#2373
is closed and the mint is a lane rather than a gap**: ADR-0266 §11's **L2** carries
*"§2's act and its four refusals"* and lands it in this package, and until that lane
does, the only coverage this package has to offer is the empty one. **That
hole is now one place narrower than it was**: the coverage a proposal is taken over
is this module's *argument* rather than a literal it writes, so a minter landing at
:meth:`~ai_assistant.orchestration.runner.StepRunner._propose` reaches a writer that
already asks about what it minted. Until one does, every caller on this tree passes
an empty tuple, ADR-0254 §1's completeness condition holds only where it holds
**vacuously** — on a request carrying no user-facing argument, §20's arm 54 and arm
59's third case — and no row carries a `quoted`, the evidence route deciding nothing
about a coverage that carries no `MONEY` member. It is an authority over an
argument-free call rather than a wildcard over anything (§3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    ActionQuote,
    ActionRequest,
    Authorization,
    AuthorizationDisposition,
    AuthorizationOrigin,
    CoverageMember,
    EgressBinding,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime, timedelta

    from ai_assistant.core.protocols import CoverageAnswers
    from ai_assistant.core.types import Goal, PermissionDecision


#: The namespace every id derived from a confirmation is written under
#: (:func:`authorization_id_for`). One literal, defined once, because the writer
#: and the reader must agree on it exactly or a settlement silently finds nothing.
_DERIVED_ID_PREFIX: Final = "goal-authorization-for-confirmation:"


def detached_request(request: ActionRequest) -> ActionRequest:
    """The copy a seam is given, so it never holds the one that is written or run.

    **Two callers, one rule, and one implementation of it.**
    :meth:`~ai_assistant.orchestration.runner.StepRunner._record` hands this to
    ``ActionPolicy.decide`` before the request is bound and executed, and
    :func:`proposed_authorization` hands it to ``CoverageAnswers.coverage_met``
    before the row is written. The argument below is stated over the ruling because
    that is where it was first made; it reads identically one seam over, a row a
    collaborator substituted the subject of being an authority the user never
    granted.

    **This is what keeps ADR-0021 §3's central guarantee true at the seam.**
    ``PermissionRuling`` has no field naming a tool, a payload or a step
    precisely so a policy cannot substitute the subject of the decision it is
    answering about; the ADR calls that absence "the security property, not an
    economy", and says splitting the types "removes the capability rather than
    forbidding it". Handing ``decide`` the very object that is then bound into
    the ``PermissionDecision`` and executed hands the capability straight back:
    ``frozen=True`` refuses ``request.tool = ...`` and does nothing about
    ``request.__dict__`` (ADR-0018 §3), so a policy could rule ``ALLOW`` on a
    harmless declaration and swap in another registered one before returning.
    Everything downstream would then agree with itself — the decision, the
    ``ToolCall`` and the invoker all describe the substitute — and the tool the
    user's policy actually approved would never have run.

    **The timing is the whole of it: the copy is taken before ``decide`` is
    reached, not after it returns.** A copy taken afterwards faithfully preserves
    a substitution already made, which is the same hole one instruction later.

    A policy that keeps its copy and mutates it *later* is then harmless — it
    holds a value nothing reads — so the comparisons that follow (the subject
    check in :meth:`~ai_assistant.orchestration.runner.StepRunner._record`, and
    ``ToolCall``'s own ``authorises``) answer about the request that was really
    ruled on. **And an answerer that mutates its copy *during* the call is harmless
    for the same reason** (ADR-0270 §1's input-observation clause): what it holds is
    not what :func:`proposed_authorization` writes the row from.

    Raises:
        ValueError: If the request does not survive revalidation. Not reachable
            through a value this module has just constructed.
    """
    return ActionRequest.model_validate(request.model_dump())


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


async def proposed_authorization(  # noqa: PLR0913 — one parameter per operand of ADR-0254 §1's four conditions; collapsing any pair would hide which condition reads what
    request: ActionRequest,
    decision: PermissionDecision,
    /,
    *,
    answers: CoverageAnswers,
    coverage: tuple[CoverageMember, ...],
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
    - **the coverage would satisfy condition 6 for this request** — ADR-0266 §7's
      restatement of §1's completeness condition, **obtained from
      :meth:`~ai_assistant.core.protocols.CoverageAnswers.coverage_met` and by no
      other means** (ADR-0270 §1, §3). This function evaluates no conjunct of it and
      selects no governing quote; where the answer is met it **records** the quote
      the answer carries on the row (ADR-0270 §2). On this tree every caller passes
      an empty ``coverage``, so the condition holds only vacuously — a request
      carrying a user-facing argument proposes nothing, which is §20 arm 59's third
      case, *"a `CONFIRM` on an egress request one of whose arguments no resolution
      minted a member for → no row is written"*;
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

    **Nothing the row carries is a value another holder can still reach.** This
    function suspends once, and ``frozen=True`` refuses ``request.tool = ...`` while
    doing nothing about ``request.__dict__`` (ADR-0018 §3) — so any model still
    aliased across that await is a route to the subject substitution ADR-0021 §3
    calls *"the security property, not an economy"*: a row written for a declaration
    the answer was not about, named by a ``CONFIRM`` recorded over the original, and
    established by an approval of a question the user was shown about something else.
    :func:`detached_request` is the rule ``ActionPolicy.decide`` is already held to
    one seam over, and it reads the same here.

    **Two copies, taken before the await, and the distinction is what makes the rule
    hold.** The **writer** builds the row from ``subject`` and ``written``, its own
    copies; the **answerer** is handed a second pair it alone holds. A collaborator
    that rewrites what it was given moves nothing, and a holder that rewrites the
    caller's request — or a value *nested* inside it — moves nothing either, the
    copies being round-trips through a dump rather than new names for the same
    objects. **The quote crossing back is copied for the same reason and on the
    same ground**: ``Authorization`` stores a model field by reference, so a
    ``quoted`` the answerer retained would be a figure it could still move on a row
    ADR-0267 §7 writes once and never edits. ``retention`` is a ``timedelta``, and
    ``proposed_at`` and ``confirmation`` are read off ``decision`` here — a value is
    fixed by being read where a model is fixed only by being copied — while
    ``standing`` is consumed before the await. **The
    capability is removed rather than the reachability argued** — no holder on this
    tree races this function today, and the guarantee should not rest on that staying
    true.

    **The seam is asked at most once per proposal, and its answer outlives the call
    only as the row's ``quoted``** (ADR-0270 §3). The question is put where the
    third condition is taken, so a `CONFIRM` an earlier condition already refused
    asks nothing at all and no durable read is taken for a row that was never going
    to be written. Nothing memoises the answer, nothing hands it to a later
    `decide`, and ADR-0254 §13's recheck reads the current governing quote at every
    dispatch as if ``quoted`` were not there.

    **An unreadable seam propagates** (ADR-0270 §4). ``coverage_met`` raises
    `AuthorizationError` where `GoalQuotes.for_action` does, and this function
    converts it into neither a met answer nor an unmet one: the caller writes no row,
    `Confirmation.authorization` is absent (§11) and the one call is confirmed under
    ADR-0148 §3's route (a) — §1's own disposition for a failed completeness
    condition, reached by one further case.

    Args:
        request: The request the ruling was taken over.
        decision: The recorded `CONFIRM` the question rides. Its ``decided_at`` is
            the row's ``proposed_at`` and its ``id`` is the row's ``confirmation``.
        answers: Condition 6's one answerer (ADR-0270 §1). **The policy's third
            face and not a second implementation**: the composition root passes the
            object that already answers `ActionPolicy` under this annotation, which
            is golden rule 1 rather than an exception to it.
        coverage: The coverage the row would carry — condition 6's fourth operand,
            and what the row is written with. **This module mints none** until
            ADR-0266 §11's L2 lands the mint (module docstring), so every caller on
            this tree passes an empty tuple; it is a parameter rather than a literal
            so that the writer asks about what a minter minted rather than about
            what this function assumed.
        goal: The goal, for rung 2 of the ladder.
        retention: The deployment's turn-retention window, for rung 3.
        standing: The `ESTABLISHED` rows of that goal, live and lapsed, as
            `GoalAuthorizationStore.standing` returns them.

    Returns:
        The row to record `PROPOSED`, or ``None`` where this `CONFIRM` proposes
        none.

    Raises:
        AuthorizationError: If ``coverage_met`` does. It is not caught here.
    """
    # The writer's own copies, taken here, before the one await. Everything below
    # reads these and never the caller's values: a `str` or a `datetime` is fixed
    # by being read, and a model is fixed only by being copied, because binding a
    # name to it aliases the very object another holder can rewrite.
    subject = detached_request(request)
    written = _detached_coverage(coverage)
    goal_read = None if goal is None else goal.model_copy(deep=True)
    proposed_at = decision.decided_at
    confirmation = decision.id
    if subject.goal is None:
        return None
    binding = subject.egress_binding
    if not isinstance(binding, EgressBinding):
        return None
    superseded = _superseded(standing, subject)
    answer = await answers.coverage_met(detached_request(request), _detached_coverage(coverage))
    if not answer.met:
        return None
    # The one value that crosses back, and the answerer may still be holding it.
    # `Authorization` stores a model field by reference — `row.quoted is answer.quoted`
    # — so a quote the answerer retained and rewrote afterwards would move the figure
    # on a row ADR-0267 §7 writes **once and never edits**, and the projection would
    # render a price no proof was taken over.
    quoted = (
        None if answer.quoted is None else ActionQuote.model_validate(answer.quoted.model_dump())
    )
    expires_at = horizon(proposed_at, goal=goal_read, retention=retention)
    if expires_at is None:
        return None
    return Authorization(
        id=authorization_id_for(confirmation),
        goal=subject.goal,
        tool=subject.tool,
        account=binding.account,
        destinations=binding.canonical_destination_set,
        origin=AuthorizationOrigin.CONFIRMED,
        coverage=written,
        quoted=quoted,
        proposed_at=proposed_at,
        expires_at=expires_at,
        confirmation=confirmation,
        supersedes=superseded,
        disposition=AuthorizationDisposition.PROPOSED,
        settled_at=None,
    )


def _detached_coverage(coverage: tuple[CoverageMember, ...]) -> tuple[CoverageMember, ...]:
    """Revalidated copies of ``coverage``, for :func:`detached_request`'s reason.

    A ``CoverageMember`` is frozen and rewritable through ``__dict__`` exactly as an
    ``ActionRequest`` is, and it is the other half of condition 6's operand — so a
    member whose ``bound`` was widened while the seam was suspended would be written
    onto the row as an authority over values the user never stated. Called twice, so
    what the answerer holds and what the row carries are two objects and neither is
    the caller's.
    """
    return tuple(CoverageMember.model_validate(member.model_dump()) for member in coverage)


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
    "detached_request",
    "horizon",
    "proposed_authorization",
]
