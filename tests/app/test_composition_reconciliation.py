"""The composition root's half of ADR-0259: the pass and the check reach a deployment.

``Engine`` takes ADR-0259 §7's :class:`ReconciliationStage` as an **optional**
constructor parameter, and the reason is §11: the check reaches ``ToolInvoker.invoke``,
the façade holds no invoker, the seam is ``StepRunner``'s, and the pass *"touches
``StepRunner`` in nothing"*. So the stage is assembled **beside** the runner by this
root rather than inside the façade out of parts it happens to hold — which is golden
rule 1's "the engine receives implementations by injection" and makes the wiring this
file's own job.

**It is the whole of what makes the pass run anywhere.** Every arm of §12's 5-11
injects a stage of its own, so all of them stay green against a root that wires
``None`` — and in that deployment a goal's superseded steps stay undisposed, a recorded
``DENY`` is never applied, an attempt left ``RUNNING`` beside an ``INDETERMINATE`` step
is never repaired to ``EFFECT_UNRESOLVED``, and no uncertain effect is ever surfaced.
That is the gap #2486 records, and these are the cases that close it.

Real stores in a temp directory, as everything in ``tests/app`` is: the wiring is the
subject, and a fake wired correctly proves nothing about the production one. **Nothing
here calls a model.** The last case drives a whole turn, so the one
:class:`~ai_assistant.models.PydanticAIProvider` this root constructs is swapped for
:class:`_ScriptedProvider`, which answers each stage's envelope from the stage's own
system prompt and reaches no network.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.app import build_engine
from ai_assistant.app import composition as composition_module
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import Message, Role
from ai_assistant.orchestration.reconciling import ReconciliationStage

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ai_assistant.orchestration import Engine

pytestmark = pytest.mark.anyio


def _settings() -> Settings:
    """The shipped defaults over the offline embedder."""
    return Settings(embedder=EmbedderKind.HASHING)


def _stage_of(engine: Engine) -> ReconciliationStage:
    """The stage the root built, read off the engine it was handed to.

    Narrowed here rather than at each use, so that a root wiring ``None`` — the
    deployment #2486 describes — fails on this line with the reason in the message,
    in every case below.
    """
    stage = engine._reconciliation
    assert isinstance(stage, ReconciliationStage), "the root wires one, not None (#2486)"
    return stage


class _ScriptedProvider:
    """An offline ``ModelProvider`` that answers each stage's envelope by its prompt.

    The three stages a turn passes through before it composes each ask for one JSON
    object, and each is recognised by a phrase of its **own** system prompt rather than
    by call order — a turn that gained or lost a model call would otherwise silently
    shift the script by one and answer the planner with the associator's envelope.

    The answering stage is given no envelope: its reply is prose, and the case below
    reads its **prompt** rather than its answer.
    """

    #: Every system prompt this provider was shown, in call order.
    prompts: list[str]

    def __init__(self, spec: str) -> None:
        """Take the model spec this root resolved and ignore it.

        Args:
            spec: The ``"provider:model"`` the root asked for. Recorded nowhere: the
                arm is about the pipeline, and which route it would have taken is
                ``tests/app/test_composition_provider.py``'s subject.
        """
        self._spec = spec
        self.prompts = []

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        """Answer the stage that asked, from its own system prompt.

        Args:
            messages: The conversation, oldest first; the system prompt leads it.
            model: An override, ignored — there is no real model to switch.

        Returns:
            The assistant's reply.
        """
        system = messages[0].content
        self.prompts.append(system)
        if "state what it means" in system:
            # ADR-0276's understanding stage, which runs after routing declines and
            # before association: a reading grounded in the input alone.
            return Message(
                role=Role.ASSISTANT,
                content='{"meaning": "The user asked.", "meaning_ground": "stated"}',
            )
        if "operation-routing stage" in system:
            # ADR-0197's decline, so the turn takes its usual route and reaches the
            # reconciliation at all.
            return Message(role=Role.ASSISTANT, content='{"no_operation": true}')
        if "which of a user's existing objectives" in system:
            # ADR-0250 §4's `associates`, naming the one candidate this conversation
            # holds. Without it the turn opens a **fresh** goal, `association.goal` is
            # a goal with no residual, and the pass has nothing to repair.
            return Message(
                role=Role.ASSISTANT, content='{"verdict": "associates", "goals": ["G1"]}'
            )
        if "planning stage" in system:
            # A decline: the turn asks about an act an earlier turn started, and this
            # deployment's registry carries no capability that would check on one.
            return Message(
                role=Role.ASSISTANT,
                content=(
                    '{"rationale": "the user is asking about something already in'
                    ' motion", "steps": [], "no_capability_needed": true}'
                ),
            )
        return Message(role=Role.ASSISTANT, content="I am not sure whether that went through.")


async def test_the_root_builds_one_stage_and_hands_that_very_object_to_the_engine(
    tmp_path: Path,
) -> None:
    """Exactly one stage, and the engine holds **it** (ADR-0259 §7, #2486).

    Counted rather than merely found, for the reason
    ``test_composition_forecast.py``'s servicing case is: a root that built one stage
    and passed a second would satisfy every identity assertion below about the object
    it passed while the two disagreed about nothing — but there is no type that could
    say a *turn's* pass and the wiring are the same collaborator, so it is asserted
    here.

    **The `None` this replaces is the deployment #2486 describes**: ``Engine`` defaults
    the parameter, so a root that passed nothing would build a green tree in which no
    turn reconciles anything. That is what :func:`_stage_of` fails on, in this case and
    in every one below.
    """
    built: list[ReconciliationStage] = []

    def counted(**arguments: Any) -> ReconciliationStage:
        stage = ReconciliationStage(**arguments)
        built.append(stage)
        return stage

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(composition_module, "ReconciliationStage", counted)
        engine = build_engine(_settings(), data_dir=tmp_path)

    try:
        assert len(built) == 1, "one stage per deployment, never a second"
        assert _stage_of(engine) is built[0], "the one built is the one the engine holds"
    finally:
        await engine.aclose()


async def test_both_halves_hold_the_stores_the_runner_and_the_executor_write_through(
    tmp_path: Path,
) -> None:
    """ADR-0192 §9's wiring clause, over the pass and the check alike.

    The two halves are **deliberately two objects** (ADR-0259 §3, §4) and each is
    constructed with its own store arguments, so "the pass and the check agree with the
    runner" is four identities and not one — and each of the four fails silently.

    **The plan store must be the runner's.** Every write ADR-0259 §4 makes is a
    compare-and-swap against a version the runner also advances, so a pass over a
    second store would compute its ``expected_version`` from rows nothing else writes
    and lose every swap it attempted — with the turn carrying on, because §4 rules that
    a lost swap ends the pass and *"the turn does not fail"*. The failure would be
    perfectly silent.

    **The trail must be the runner's too.** §3's check resolves a step by the decision
    the runner recorded, and act 2 applies a ``DENY`` read through ``resolution_of``:
    over a second trail both read about a goal that never ran, and every parked step
    stays parked for ever.
    """
    engine = build_engine(_settings(), data_dir=tmp_path)
    try:
        stage = _stage_of(engine)
        runner = engine._runner
        # Collected as `object` so the identity is asserted rather than argued about:
        # the halves narrow one store to two unrelated Protocols, and one object
        # serving both seams is the claim under test.
        stores: list[object] = [stage._pass._plans, stage._check._plans]
        trails: list[object] = [stage._pass._trail, stage._check._trail]

        assert all(store is engine._plans for store in stores)
        assert all(trail is engine._trail for trail in trails)
        assert engine._plans is runner._plans, "the runner's own store, not a second one"
        assert engine._trail is runner._trail, "the runner's own trail, not a second one"
    finally:
        await engine.aclose()


async def test_the_check_acts_through_the_very_invoker_the_executor_acts_through(
    tmp_path: Path,
) -> None:
    """§3's one seam, constructed once at this root and handed to both holders.

    ADR-0259 §11 rules that the pass *"touches ``StepRunner`` in nothing"*, which binds
    this file as well as ``orchestration/``: the invoker is **not** reached for through
    the runner, it is the object this root already built and gave
    :class:`~ai_assistant.orchestration.StepExecutor` as its ``invoker``. Here that is
    one object wearing three faces (ADR-0029 §8) — the selecting ``ToolRegistry``, the
    acting ``ToolInvoker``, and the registry the runner resolves steps against — so the
    identity is asserted against both of the runner's own references.

    **It matters past tidiness.** ADR-0152 §1's registry-original comparison and
    ADR-0194's ledger are that one object's, so a check invoking through a second
    registry would rule its one read against a different table of declarations and
    charge it to a ledger nothing totals.

    **And the clock is left at the stage's default**, which ADR-0255 §9 requires to be
    monotonic. This root configures no such source — ``_utcnow`` is a wall clock, which
    §9 rules out in terms — so the default *is* the production reading, and a root that
    passed its own clock here would hand §9's gate a figure that can go backwards.
    """
    engine = build_engine(_settings(), data_dir=tmp_path)
    try:
        stage = _stage_of(engine)
        runner = engine._runner

        # Widened to ``object`` for ``test_composition_recovery.py``'s reason: the two
        # references this is compared against are *unrelated* Protocols — a
        # ``ToolInvoker`` and a ``ToolRegistry`` — so a narrowed comparison is a
        # ``comparison-overlap`` error under ``mypy --strict``. One object satisfying
        # both is precisely the claim under test, so it is asserted rather than typed
        # away.
        acting: object = runner._executor._invoker
        selecting: object = runner._registry

        assert acting is stage._check._invoker, "one invoker, two holders"
        assert selecting is stage._check._invoker, "ADR-0029 §8's one object"
        assert stage._monotonic is time.monotonic, "ADR-0255 §9's monotonic source"
    finally:
        await engine.aclose()
