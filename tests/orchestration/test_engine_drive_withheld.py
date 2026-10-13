"""ADR-0261 §7 at the engine: a refused claim ends the walk and says where the goal stands.

§14's arm 8, in the half §13 books on **L2** — "each of ``DriveWithheld``'s seven members
is produced by the state that names it, the turn **composes a reply**, and no
``Planner.plan`` call is taken on account of the refusal", together with the negative arm
("anything that is not a ``ClaimRefused`` propagates") and the arm that forces the read's
order rather than assuming it.

**Every arm here is engine-level by construction.** The class is raised inside the store,
on the ``→ RUNNING`` claim alone, and the member is decided by a read only the engine
takes — so nothing below ``AssistantEngine`` can assert either, and nothing above it can
see the refusal at all: what a surface is handed is a ``TurnOutcome`` that **returned**.

**How a refusal is produced without racing anything.** :class:`_Interposing` runs one hook
inside the store, in the same instant as the claim's compare-and-swap and before it is
applied, so the state the conjunct reads is the state the hook left. That is the sequencing
ruling's own shape — the user act is *recorded* and the walk then meets it — and it makes
every arm deterministic rather than probabilistic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ai_assistant.core.types import GoalStatus, StepStatus, StepTransition
from ai_assistant.orchestration.engine import _GOAL_WITHHELD
from ai_assistant.testing import FakePlanStore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ai_assistant.core.types import ExecutionState


class _Interposing(FakePlanStore):
    """A store that runs one hook in the same instant as the claim, before it applies.

    The hook is armed once and fires on the **first** ``→ RUNNING`` transition, which is
    this engine's one claim per turn. It runs *inside* the store call, so what the
    conjuncts then read is what it left — no sleep, no task ordering and no race.

    It also counts the claims, which is how "the claim is **not retried**" is asserted as
    a fact about the walk rather than inferred from the answer.
    """

    #: Which ``→ RUNNING`` transition the hook fires on. ``2`` is the **re-claim** a
    #: retry spends (ADR-0037 §6), which is the only instant at which an attempt can be
    #: ``ENDED`` over the step about to be claimed: ADR-0262 §4 admits an ending only
    #: where every step has settled, and ``FAILED`` is both settled and the one settled
    #: status ADR-0014 §4's graph still admits a ``→ RUNNING`` move from.
    on_claim = 1

    def __init__(self, *, now: Callable[[], Any]) -> None:
        super().__init__(now=now)
        self.before_claim: Callable[[_Interposing], Awaitable[None]] | None = None
        #: Substitutes the claim a **defective walk** would have built, applied after
        #: :attr:`before_claim` so it can read what that hook left. A correct engine
        #: never builds one, which is exactly what ADR-0261 §14 arm 8's negative list
        #: is about — *"a defect of the walk that built them"* — so presenting one is
        #: the only way to put it to the store's real refusals.
        self.mangle: Callable[[_Interposing, StepTransition], StepTransition] | None = None
        self.claims = 0

    async def commit_transition(self, transition: StepTransition) -> ExecutionState:
        if transition.to_status is StepStatus.RUNNING:
            self.claims += 1
            if self.claims == self.on_claim:
                if self.before_claim is not None:
                    hook, self.before_claim = self.before_claim, None
                    await hook(self)
                if self.mangle is not None:
                    mangle, self.mangle = self.mangle, None
                    transition = mangle(self, transition)
        return await super().commit_transition(transition)


# --- the one goal test the engine reaches by division rather than by name -----


def test_the_goal_test_the_engine_does_not_name_is_exactly_achieved() -> None:
    """The remainder ADR-0250 §1's division leaves is one member, and it is ``ACHIEVED``.

    ``Engine`` reaches ADR-0261 §7's third goal test as *"closed and not ``ABANDONED``"*
    rather than by naming ``GoalStatus.ACHIEVED``, because ADR-0249 §16 item 7's guard
    over ``src/`` reports every mention of that member and cannot tell this lane's **read**
    from A10's **write** — and ADR-0261 §12 records ADR-0249 §4 as superseded in nothing,
    so the guard is left exactly as it stands.

    **This is what keeps that spelling honest.** The division is ADR-0250 §1's and is
    stated over four members; a fifth, closed one would otherwise reach ``GOAL_ACHIEVED``
    by silence and tell a user their goal was reached. Here the remainder is pinned, so
    such a member fails this arm rather than the user.

    The member itself is produced end to end by
    :func:`test_a_re_claim_under_an_ended_attempt_is_withheld`, over a goal a real
    ``set_goal_status`` write reached.
    """
    unnamed = set(GoalStatus) - set(_GOAL_WITHHELD) - {GoalStatus.ACTIVE}

    assert unnamed == {GoalStatus.ACHIEVED}
