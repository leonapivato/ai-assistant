"""Milestone 23's exit, arm (b)'s second half, with the activation run through the phases.

``test_m23_forbidden_belief`` holds that a hostile instruction inside ingested content
cannot become a forbidden belief "that justifies a later send without that origin being
visible at the ruling point that admitted it" (ADR-0181 §8). Its consolidation cases run
no turn and stand as they are; the case asserting on the later send drives it through
``converse``, which retires at the cutover (ADR-0309 §5:1). Here that send is the one an
activation on the phases plans after one ingestion-and-consolidation cycle
(:mod:`phases_m23_world`): the belief the transcript wanted never committed, so what
recall keeps is the reader's ``ATTESTED`` record it would have been derived from, and
the call's origin reaches the ruling point. Nothing parks on the phases (ADR-0306
§4:8), so the fact is asserted on the recorded ruling's binding rather than on a parked
step's card.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from m23_harness import ATTACKER, INNOCENT_ASK, carried_the_injection, plant
from phases_m23_world import ask, build_phases_world

from ai_assistant.core.types import EgressBinding, EpisodicMemory, PermissionOutcome
from ai_assistant.permissions.policy import _PLANNED_OVER_EXTERNAL
from ai_assistant.tools.send_email import SEND_EMAIL_ID

if TYPE_CHECKING:
    from pathlib import Path

#: One hostile entry among two planted records, and one among ten, as the old arm.
CORPORA: Final = (2, 10)


@pytest.mark.parametrize("records", CORPORA)
async def test_the_later_send_justified_from_the_belief_needs_the_user_with_the_fact(
    tmp_path: Path, records: int
) -> None:
    """The send the belief would justify asks the user, its origin on the ruling."""
    world = build_phases_world(tmp_path, to=ATTACKER)
    plant(world.source, cycle=0, records=records, hostile=True)
    await world.ingestion.ingest()
    outcome = await world.consolidations("consolidation-0").run()
    assert carried_the_injection(world.consolidation_model), (
        "the cycle consolidated a chunk carrying none of the planted content"
    )
    assert outcome.proposed >= 1, "the ceiling was never reached, so the cycle measured nothing"
    assert outcome.committed == 0

    await world.engine.start()
    try:
        activation = await ask(world, INNOCENT_ASK)
    finally:
        await world.engine.aclose()

    episode = await world.store.get(f"activation:{activation}")
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert episode.processing_record.recall is not None
    assert any(
        item.rests_on_recorded_external_content for item in episode.processing_record.recall.items
    ), "recall kept no record resting on the planted content"
    (decision,) = [one for one in await world.trail.export() if one.tool.id == SEND_EMAIL_ID]
    assert decision.ruling.outcome is PermissionOutcome.CONFIRM
    assert isinstance(decision.egress_binding, EgressBinding)
    assert decision.egress_binding.planned_with_external_content is True
    assert _PLANNED_OVER_EXTERNAL in decision.ruling.reason
    assert world.connector.attempts == 0
