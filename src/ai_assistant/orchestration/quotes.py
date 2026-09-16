"""Minting the price a step's own output stated, for the act it was read for (ADR-0267 §4).

ADR-0267 §11's **Q2**: *"the mint in `orchestration`"*. §8's writer clause puts it
here and nowhere else — *"`orchestration` mints every `ActionQuote`, and nothing else
does. No `ActionPolicy`, no `ToolRegistry`, no store, no reader, no interface adapter,
no tool and no model **constructs, writes or repairs** one"* — and this module is that
one place.

**The reading is total and silent** (§4). :func:`quote_read` is a pure function of the
four values §4 names — the step's own output, its own request, its own declaration and
the plan it belongs to — and it answers a quote or nothing. *"Every failure of that
reading mints nothing, and nothing is repaired, coerced, defaulted or substituted"*,
and every such failure *"raises nothing … the validator's own exception included"*: the
record's own refusals are the currency shape, the finiteness and the sign, so this
function constructs the record and reads a refusal as a reading that failed rather than
restating those three rules a second time where they could drift.

**The mint reads the step's own output, its own request and its own declaration, and
reads nothing else** (§4). Not another step's output, not a memory, not a preference,
not a ``Settings`` field, not a second call, not a model. **It never asks for a number
and never derives one**: no arithmetic over two outputs, no sum of components, no unit
conversion, no currency conversion, no rounding and no quantisation — *"a price this
system computed is a price no provider quoted"*.

**The write is where the ordering claim lives** (§4). :func:`mint_quote` reads the goal,
computes the command against the version that read observed, and hands it to
:func:`record_minted_quote`, which attempts the compare-and-swap **once**. A refused
write is **never rebased**: the minter re-reads the goal at most once and takes exactly
one of two dispositions, comparing records and never instants — a silent stop where that
action's last quote equals the one it is minting (the ambiguous retry, committed with its
answer lost), and otherwise a ``PlanningError`` that is *not* a ``StaleExecutionError``,
because that class tells a caller to re-read and retry and no re-read makes this write
land. *"A minter that loses the race is discarded and never reconciled"*, and the raise
is what keeps the loss legible instead of silent.

**The mint is not atomic with the transition that recorded the output** (§4), and
nothing here pretends otherwise. A process stopping between the two writes leaves the
step ``SUCCEEDED`` with its output and the goal without that reading; the act then
**asks** where no earlier quote names that action. **No lane reconciles a missing quote
from a stored output**, so this module is called from the step of the walk that recorded
the output and from nowhere else (:meth:`~ai_assistant.orchestration.runner.StepRunner
._execute`), and no pass over stored outputs calls it later.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from ai_assistant.core.errors import PlanningError, StaleExecutionError
from ai_assistant.core.types import (
    ActionQuote,
    ActionQuoteMinting,
    StepOutputRef,
    StepStatus,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import (
        ActionRequest,
        FrozenJson,
        PlanStep,
        StepExecution,
    )

_log = structlog.get_logger(__name__)


def quote_read(
    *,
    step: PlanStep,
    recorded: StepExecution,
    request: ActionRequest,
    plan: str,
) -> ActionQuote | None:
    """The quote this step's output states, or ``None`` where the reading fails (§4).

    **§4's four conditions and no fifth of substance.** The step is ``SUCCEEDED``; the
    plan step carries an ``intended_action`` (ADR-0265 §4); the declaration the step was
    bound to carries a ``quoted_output`` (§3); and the step's ``output`` is a JSON
    **object** carrying, at the key that declaration names as its ``amount``, a JSON
    **string** that ``Decimal`` accepts or a JSON **integer** whose ``Decimal`` is finite
    and not negative, and, at the key it names as its ``currency``, a JSON **string** of
    §1's shape.

    **And a step satisfied from an earlier act reads nothing, which is §4's own rule
    rather than a fifth condition of substance** (ADR-0259 §2). Such a step is
    ``SUCCEEDED``, names an intended action — the claim requires one — and carries an
    ``output`` copied from the holder's row and a ``finished_at`` stamped at the
    **satisfaction**, so all four conditions above hold on it while none of the facts
    they stand for does: no price was read, and the instant on the record is not one
    anybody observed a price at. §4 forbids exactly that — *"minting one from an output
    recorded earlier would state a reading nobody took at an instant nobody observed"* —
    so the record's own satisfaction mark is what refuses it. **A re-read of a price is
    a fresh dispatch and is unaffected**: it records its own output at its own instant
    and mints an appended quote like any other (§4).

    **No** ``verifies`` **is among the four and none is evaluated here** (§4). ADR-0255
    §8 reads that predicate at exactly two sites and rules that one no dependency and no
    interpretation reads *"is evaluated by nothing and imposes nothing"*; a mint
    conditioned on it would be a **third** site, and would put a plan-carried,
    model-authored predicate in the path of a quote.

    **A JSON boolean is not a JSON integer and is refused on that ground, stated because
    the implementation language will not state it** (§4): ``bool`` is a subclass of
    ``int`` in Python, so a check written as an ``int`` instance test admits ``true`` as
    ``Decimal(1)`` and mints a one-unit quote that satisfies almost any ceiling. **A JSON
    float is never a price** — ADR-0254 §4's own refusal taken at the mint, because a
    binary float rounded into a ``Decimal`` here would be an unproven comparison the
    policy could no longer see.

    ``read_at`` is **the instant the step's output was recorded** and never the mint's
    (§4), so it is the store's own ``finished_at`` for that step. A ``SUCCEEDED`` step
    carrying none states no such instant, and a reading that cannot say when the price
    was read is a reading that failed — the same silent direction as every other case
    here, rather than a clock read at the mint standing in for one.

    Args:
        step: The plan step the request serves, for its ``intended_action``.
        recorded: That step's stored record, for its status, its ``output`` and the
            instant the output was recorded.
        request: The request whose output this is, for its ``parameters_digest`` and for
            the declaration it was bound to. **Both come from one request**, which is
            what makes ``arguments_digest`` *"the ``parameters_digest`` of the
            ``ActionRequest`` whose output it was read from"* rather than a value
            computed a second way.
        plan: The plan the reading step belongs to. Carried because a step id alone
            names no place (§1).

    Returns:
        The quote, or ``None`` where any part of the reading failed. **It raises
        nothing.**
    """
    quoted = request.tool.quoted_output
    if (
        recorded.status is not StepStatus.SUCCEEDED
        # ADR-0259 §2: the output is the **holder's**, recorded by an act this step did
        # not perform, and `finished_at` is the satisfaction's instant rather than the
        # reading's. Read on the committed record, so no caller of this function can be
        # the one place the exclusion is remembered.
        or recorded.satisfied_by_execution is not None
        or step.intended_action is None
        or quoted is None
        or recorded.finished_at is None
        or not isinstance(recorded.output, Mapping)
    ):
        return None
    output: Mapping[str, FrozenJson] = recorded.output
    if quoted.amount not in output or quoted.currency not in output:
        return None
    amount = _amount_of(output[quoted.amount])
    currency = output[quoted.currency]
    # §4's own listed refusal — *"a currency that is not a JSON string"* — and the one
    # half of the currency reading that lives here. The **shape** of a string currency
    # is `ActionQuote`'s rule and is left to it below, so `"usd"` and `"EURO"` are
    # refused once rather than twice.
    if amount is None or not isinstance(currency, str):
        return None
    try:
        return ActionQuote(
            intended_action=step.intended_action,
            arguments_digest=request.parameters_digest,
            amount=amount,
            # Handed to the record as it stands. A string of any other shape —
            # `"usd"`, `"EURO"`, `"€"` — is refused by `ActionQuote`'s own validator
            # (§1), which is where that rule lives; so is a non-finite or negative
            # amount. Reading either here as well would be two statements of one rule,
            # and §4's list has every one of them mint nothing and raise nothing, "the
            # validator's own exception included".
            currency=currency,
            plan=plan,
            read_from=StepOutputRef(step=step.id, field=quoted.amount),
            read_at=recorded.finished_at,
        )
    except ValidationError:
        _log.debug(
            "quote_not_read_from_output",
            step_id=step.id,
            plan_id=plan,
            intended_action=step.intended_action,
        )
        return None


def _amount_of(value: FrozenJson) -> Decimal | None:
    """The amount a JSON value states, or ``None`` where it states none (§4).

    A JSON **string** ``Decimal`` accepts or a JSON **integer**, and nothing else. The
    ``bool`` clause runs **before** the ``int`` clause and is not an ordering accident:
    ``True`` is an ``int`` in Python and would otherwise mint ``Decimal(1)``. A JSON
    float — a ``float`` here — falls through to ``None``, as does any other type.

    Finiteness and the sign are **not** checked here: ``ActionQuote`` checks them, and
    ``Decimal("sNaN") < 0`` raises rather than answering, so the one place that
    comparison is made is the one that already orders it correctly.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if not isinstance(value, str):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


async def mint_quote(plans: PlanStore, *, goal_id: str, quote: ActionQuote) -> None:
    """Append ``quote`` to that goal, against the version this read observes (§4).

    **The read and the write are this one step of the walk** (§4): *"a mint is taken in
    the step of the walk that recorded the output it reads and never afterwards"*, and
    the ``expected_version`` the command carries *"is the version the goal held when it
    read it"*. Two turns of one conversation are not serialized (ADR-0255 §3), so a
    concurrent writer makes that write stale — which :func:`record_minted_quote` disposes
    of, and never by rebasing.

    **The version is read here and never held across the producing call, and that is
    §4's own refusal rather than an oversight.** *"No lane rebases a stale quote write,
    mints a sequence number, **holds a lock across the read**, adds an idempotency key or
    makes the mint atomic with the transition"* — a ``Goal.version`` carried across a
    provider call is that lock, and every unrelated write to the goal in that window
    (an evidence row, an engagement, a revision) would refuse the mint and stop the walk
    **after the act had happened**.

    **So the order the tuple records is the order of the goal reads the writes were
    computed against, and not the order the prices were read in.** §4 states that
    directly — *"**Commit order is not read order, and no clause reads it as one**: a
    minter can read ``120``, stall, and commit after another has read ``170``"* — and
    ADR-0267 §10 books the consequence by name: *"**a concurrently read price does not
    survive** … one of two simultaneous readings is lost … **Commit order is not read
    order**"*, fired by *"the decision that gives a quote a store-authored order should a
    plan ever read one price twice at once"*. A stalled minter's reading can therefore
    land last and govern a ceiling, which is the residual §6 answers at the provider's
    gate rather than here — this ADR's own title being *"no local check proves it still
    true"*.

    Raises:
        PlanningError: If the goal cannot be read or does not exist, or as
            :func:`record_minted_quote` raises it. **Never a**
            ``StaleExecutionError``: that class invites the retry §4 forbids.
    """
    goal = await plans.get_goal(goal_id)
    if goal is None:
        msg = (
            f"goal {goal_id!r} was not found, so the price this step's output stated "
            f"cannot be recorded against the act it was read for (ADR-0267 §4)"
        )
        raise PlanningError(msg)
    await record_minted_quote(
        plans,
        ActionQuoteMinting(goal_id=goal_id, quote=quote, expected_version=goal.version),
    )


async def record_minted_quote(plans: PlanStore, minting: ActionQuoteMinting) -> None:
    """Attempt one compare-and-swap append, and dispose of a refusal (§4).

    **One attempt, and a refused write is never rebased.** Where the store refuses the
    command stale, this re-reads the goal **at most once** and takes exactly one of two
    dispositions, *"comparing records and never instants"*:

    - the goal's **last quote naming that action equals** the one being minted — the
      write already landed and its answer was lost, the ambiguous retry — and this
      **stops silently**, appending nothing and raising nothing. *"That is the whole of
      how a mint is idempotent and the whole of what a refused write is permitted to
      conclude."*
    - **every other outcome raises**: a different quote for that action, and no quote at
      all whether or not ``quotes_elided`` has advanced.

    **Commit order is not read order, and nothing here reads it as one** (§4). A minter
    can read ``120``, stall, and commit after another has read ``170``, so a different
    quote found after a refusal is **not** evidence of a later reading and is never
    treated as one. The loser is discarded and never reconciled.

    **The store's refusal is not propagated as itself.** ``StaleExecutionError`` tells a
    caller to re-read and retry, and **no re-read makes this write land** — the retry it
    invites is the rebase §4 forbids, and a caller obeying the class would break the
    ordering claim. **No new error class is minted** and **nothing swallows the
    failure**: the walk stops under ADR-0255's own discipline rather than dispatching
    against a reading the minter could not record.

    Raises:
        PlanningError: If the store refuses the command for any reason other than a
            stale version, or if a stale refusal resolves to anything but the mint's own
            committed write. **Never a** ``StaleExecutionError``.
    """
    try:
        await plans.record_quote(minting)
    except StaleExecutionError:
        await _after_a_stale_write(plans, minting)


async def _after_a_stale_write(plans: PlanStore, minting: ActionQuoteMinting) -> None:
    """The one re-read a refused write is allowed, and its two dispositions (§4).

    ADR-0148 §1's trade is taken here as ADR-0267 §6 takes it, and **no lane re-reads a
    second time**: the one re-read either recognises the mint's own committed write or
    raises.

    Raises:
        PlanningError: Unless the goal's last quote naming this action equals the one
            being minted.
    """
    quote = minting.quote
    goal = await plans.get_goal(minting.goal_id)
    standing = (
        None
        if goal is None
        else next(
            (
                held
                for held in reversed(goal.quotes)
                if held.intended_action == quote.intended_action
            ),
            None,
        )
    )
    if standing == quote:
        # The ambiguous retry: this very quote is what the goal's order already ends
        # with for this action, so the write landed and its answer was lost. Appending
        # again would record a reading nobody took.
        _log.debug(
            "quote_write_already_landed",
            goal_id=minting.goal_id,
            intended_action=quote.intended_action,
        )
        return
    msg = (
        f"the quote read for action {quote.intended_action!r} of goal "
        f"{minting.goal_id!r} was refused against version {minting.expected_version} "
        f"and the goal now "
        + ("holds no quote for that action" if standing is None else "holds a different one")
        + ": a refused quote write is never rebased, so this reading is discarded "
        "rather than appended out of the order it was read in (ADR-0267 §4)"
    )
    raise PlanningError(msg)
