"""The read envelope where the engine decides what the turn stage is told (ADR-0226).

Three of ADR-0226 §11's tests are about what happens *above*
:meth:`~ai_assistant.orchestration.loop.LearningLoop.respond`, so they live here
rather than beside the servicer:

* **item 1** — the reply-vocabulary question answering through the hop, driven end
  to end through ``converse`` so that "the answer carries it" is the reply and not
  a seam. §11 calls this "the milestone's exit shape and the one test that fails if
  the hop is merely wired". **ADR-0227 §7 re-specifies it** and this module carries
  the re-specification: the fixture is shaped as ``Engine._capture`` writes an
  episode — the user's material in ``content`` and the composed reply in ``outcome``,
  with no disposition beside it since ADR-0287 — because "a fixture that carries in
  one field what production carries in another asserts nothing about production,
  however faithfully the rest of the path is wired". §7 requires the existing test
  **rewritten** rather than supplemented, "a second test beside a fixture that cannot
  fail is a test suite that reports two greens for one guarantee".
* **item 5**'s engine arm — ``converse_spoken`` declares its channel's audience
  unbounded (ADR-0200 §3), so its request is declined by the object the engine
  already mints rather than by a second fact it has to keep in step.
* **item 10**'s two post-plan arms — a turn rejected for capacity and a turn whose
  ``PlanStore.save_plan`` raises, both of which happen **after** the loop has
  planned and serviced, and neither of which may suppress §9's record.

Everything else §11 owes that lane is in ``test_loop_reads.py``.

**ADR-0227 §8's assertions 4, 5, 8 and 16 are here too**, for the same reason: each
is about a prompt the *engine* assembled from a supply the servicer built, so a case
that stopped at the loop would assert over a carrier nothing had rendered. §8's
assertions about the render rule itself — the tail, the ceiling, the cap, the counts
and the planner's assembler — are in ``test_composing.py``, and the carrier's own
order, deduplication and emptiness are in ``test_loop_reads.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from test_engine import NoStepPlanner

from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.testing import (
    FakeModelProvider,
    FakeStreamingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import (
        CurrentContext,
        EvidenceDigest,
        GoalBrief,
        MemoryRecord,
        PlannerOutput,
        ReadAskOutcome,
        ReadRequest,
        ShownFile,
    )


class _AskingPlanner(NoStepPlanner):
    """``NoStepPlanner`` with a scripted request beside its plan, recording its supply.

    Subclassed rather than written out so the plan is the one every other engine
    case is built on: ADR-0226 §4's field is additive, so "a planner that emits a
    request" and "a planner" differ by one field and nothing else.

    **It asks for ``rounds`` rounds and then stops asking** (ADR-0251 §4). Under
    ADR-0228 §3 a planner that always asked was called twice because the *bound* said
    so; §4 moves the count to the attempt, so what ends a turn short of its allowance
    is the planner's own judgement that its supply suffices. A case about two
    servicings therefore says two, and ADR-0228 §2(b) then fails on the third call.

    **The count is per *turn*, and a turn's first call is the one whose
    ``read_outcomes`` is empty** — ADR-0251 §3: "On a turn's **first** planner call it
    is always ``()``". A counter over the planner's whole life would have the second
    turn of a two-turn case settle on its opening call, which is not a shape any
    conforming loop produces.
    """

    def __init__(self, request: ReadRequest | None, *, rounds: int = 2) -> None:
        self._request = request
        self._rounds = rounds
        self._round = 0
        self.calls: list[tuple[MemoryRecord, ...]] = []

    async def plan(  # noqa: PLR0913 — the Planner Protocol's own parameter list; ADR-0230 §3 and ADR-0240 §7 each add one
        self,
        goal: GoalBrief,
        *,
        utterance: str,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
        read_outcomes: Sequence[ReadAskOutcome] = (),
        evidence: Sequence[EvidenceDigest] = (),
    ) -> PlannerOutput:
        self.calls.append(tuple(memories))
        self._round = 1 if not read_outcomes else self._round + 1
        produced = await super().plan(
            goal,
            utterance=utterance,
            context=context,
            memories=memories,
            capabilities=capabilities,
        )
        asked = self._request if self._round <= self._rounds else None
        return produced.model_copy(
            update={"plan": produced.plan.model_copy(update={"read_request": asked})}
        )


def _recorder() -> tuple[ComposingStage, FakeModelProvider]:
    """A real composing stage over a fake that keeps the prompt it was handed.

    ADR-0227 §7 forbids substituting "the renderer whose output the assertion is
    about", and permits a fake ``ModelProvider``: so the production
    :class:`~ai_assistant.orchestration.composing.ComposingStage` assembles the
    prompt and the fake merely records it.
    """
    model = FakeModelProvider("answer")
    return ComposingStage(model=model, streaming=FakeStreamingCompleter()), model
