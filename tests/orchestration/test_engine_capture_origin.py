"""What a captured episode records about the supply its turn ran over (ADR-0223).

ADR-0221 §6 deferred one field and ADR-0223 stamps it: capture writes the captured
episode's ``Provenance.derived_from_external`` from **the turn's own selection**,
threaded per call site and never computed at capture. This module is ADR-0223 §10's
representative-input tests 1-7, 9 and 10, each named in the case that discharges it.
Test 7 lives in ``test_composing`` beside the origin phrases it is about; test 8 is
the ``interfaces`` surface arm's and lives with that lane.

**Three properties are worth naming, because each is a distinct way to get this
wrong and none of them is caught by the others.**

- The value is a disjunction over ``rests_on_recorded_external_content``, not over
  the band, so a ``DERIVED`` record carrying the mark taints a turn exactly as an
  ``ATTESTED`` one does (test 2).
- It is computed **once per pass**, above the branch that decides whether there is a
  step to drive, so the no-step branch stamps it too and the episode's mark and the
  runner's ``SelectionOrigin`` are the same boolean rather than two that agree
  (tests 3 and 4).
- The partition is **ADR-0204 §2's and not ADR-0221 §5's**, and the two differ on
  one site by decision: a routed pass carries its own ``modality`` and a
  ``derived_from_external`` of ``False``, because ``modality`` is about the user
  material the episode renders and this field is about the supply the turn ran over
  — which a routed pass does not have (test 6).
"""

from __future__ import annotations

import json

from test_engine import AT, CAPABILITY

from ai_assistant.core.types import (
    CurrentContext,
    EpisodicMemory,
    Goal,
    GoalBrief,
    GoalInterpretation,
    Ground,
    MemorySource,
    Provenance,
    TimeOfDay,
)
from ai_assistant.planning import ModelBackedPlanner
from ai_assistant.testing import FakeModelProvider

# --- §10 test 10: the planner's prompt must not move (ADR-0285 retired the other) ---


def _episode(*, marked: bool) -> EpisodicMemory:
    """One captured episode, stamped or not, identical in every other byte."""
    return EpisodicMemory(
        id="ep-1",
        content="The user asked: send the note. The assistant planned: one step.",
        occurred_at=AT,
        outcome="Sent.",
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.9,
            last_updated=AT,
            derived_from_external=marked,
        ),
    )


def _assembled(provider: FakeModelProvider) -> str:
    """Every message this provider was ever handed, joined."""
    return "\n".join(message.content for call in provider.calls for message in call.messages)


async def test_the_planners_rendering_of_a_stamped_episode_is_byte_identical() -> None:
    """§10's test 10, first half: §4's last clause, guarded at the planner.

    §4 gives the episodic origin arm to ``orchestration/composing.py`` and to nothing
    else: "``planning/planner.py``'s and ``learning/observer.py``'s renderings gain no
    origin phrase by this ADR". Their prompts are three copies of a table that must
    not become shared (ADR-0221 §3, golden rule 1), and the way a lane accidentally
    shares one is by "fixing" the other two to match. This is the guard on that.

    Driven through the real producer's public call rather than its private renderer,
    so what is compared is the prompt a model would actually receive.
    """
    decline = json.dumps({"rationale": "nothing to do", "steps": [], "no_capability_needed": True})
    stamped = FakeModelProvider(decline)
    unstamped = FakeModelProvider(decline)
    goal = Goal(
        id="g-1",
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome="send the note",
                outcome_ground=Ground.USER_STATED,
                outcome_span="send the note",
                recorded_at=AT,
                raised_by="t-1",
            ),
        ),
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )
    context = CurrentContext(
        now=AT, time_of_day=TimeOfDay.MORNING, is_weekend=False, within_working_hours=True
    )

    for provider, marked in ((stamped, True), (unstamped, False)):
        await ModelBackedPlanner(provider).plan(
            GoalBrief.of(goal),
            utterance="a request",
            context=context,
            memories=(_episode(marked=marked),),
            capabilities=(CAPABILITY,),
        )

    assert _assembled(stamped) == _assembled(unstamped)
