"""The episode window's pending candidates, read from the records (ADR-0329 §3:3, §6:9).

The join of a recorded ``remember`` call to the effect record that shows it done, and
which episodes are pending, driven directly over the canonical plan store. The whole
path, the digest authorizing and acting really compute included, runs in
``test_engine_phases_candidates``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import pytest
from test_planning import _episode

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActionRequest,
    ActivationEffect,
    LabelKind,
    ObservationRecord,
    ObservationState,
    PlanningLabel,
    PlanningRound,
    ProposedCall,
    QuestionPart,
    ToolOutcome,
)
from ai_assistant.orchestration.authorizer import values_digest
from ai_assistant.orchestration.candidates import done_candidates, pending_candidates
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE
from ai_assistant.testing import FakePlanStore

_AT: Final = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
_EPISODE: Final = "activation:past"
_ACTIVATION: Final = "past"
_ROUND: Final = "round:past"


def _arguments(**fields: Any) -> dict[str, Any]:
    return {
        "fact": "prefers window seats",
        "why": "travel",
        "rests_on_this_stimulus": True,
        **fields,
    }


def _round(*calls: ProposedCall) -> PlanningRound:
    return PlanningRound(id=_ROUND, recorded_at=_AT, calls=calls)


def _digest(**values: Any) -> str:
    filled = {**values, "episode": _EPISODE, "rests_on_outside_content": False}
    return values_digest(ActionRequest(tool=REMEMBER_CANDIDATE, parameters=filled))


async def _claimed(
    plans: FakePlanStore,
    digest: str,
    outcome: ToolOutcome,
    *,
    effect_id: str = "effect-1",
    part: QuestionPart | None = None,
) -> None:
    effect = ActivationEffect(
        id=effect_id,
        activation_id=_ACTIVATION,
        round=_ROUND,
        capability="remember_fact",
        values_digest=digest,
        decision_id="decision-1",
        claimed_at=_AT,
        part=part,
    )
    await plans.claim_activation_effect(effect, match=None)
    if outcome is ToolOutcome.FAILED:
        await plans.finish_activation_effect(effect_id, outcome, reason="refused")
    else:
        await plans.finish_activation_effect(effect_id, outcome)


def _window(*calls: ProposedCall, labels: tuple[PlanningLabel, ...] = ()) -> Any:
    episode = _episode(_EPISODE, rounds=(_round(*calls),))
    assert episode.processing_record is not None
    record = episode.processing_record.model_copy(update={"labels": labels})
    return episode.model_copy(update={"processing_record": record})


async def test_a_call_its_record_shows_done_is_a_pending_candidate() -> None:
    plans = FakePlanStore(now=lambda: _AT)
    await _claimed(plans, _digest(**_arguments()), ToolOutcome.SUCCEEDED)

    pending = await pending_candidates(
        plans, (_window(ProposedCall(call_id="c1", name="remember_fact", arguments=_arguments())),)
    )

    assert pending == {_EPISODE: ("prefers window seats",)}


async def test_an_effect_spending_a_question_part_shows_no_recorded_call_done() -> None:
    """§3:3: an approved run's record is that call's, not a same-valued call's of its round.

    The round's own call needed the user's yes and was not done; the approved call is
    shown in the question that asked it (§6:9), so the window shows nothing here.
    """
    plans = FakePlanStore(now=lambda: _AT)
    await _claimed(
        plans,
        _digest(**_arguments()),
        ToolOutcome.SUCCEEDED,
        part=QuestionPart(round="round:asking", part=1),
    )

    pending = await pending_candidates(
        plans, (_window(ProposedCall(call_id="c1", name="remember_fact", arguments=_arguments())),)
    )

    assert pending == {}


@pytest.mark.parametrize("outcome", [ToolOutcome.FAILED, ToolOutcome.INDETERMINATE])
async def test_a_call_not_done_is_no_candidate(outcome: ToolOutcome) -> None:
    plans = FakePlanStore(now=lambda: _AT)
    await _claimed(plans, _digest(**_arguments()), outcome)

    pending = await pending_candidates(
        plans, (_window(ProposedCall(call_id="c1", name="remember_fact", arguments=_arguments())),)
    )

    assert pending == {}


async def test_a_call_no_record_names_is_no_candidate() -> None:
    """A call refused, or still needing the user, was never claimed (§3:3)."""
    plans = FakePlanStore(now=lambda: _AT)
    await _claimed(plans, _digest(**_arguments(fact="another fact")), ToolOutcome.SUCCEEDED)

    pending = await pending_candidates(
        plans, (_window(ProposedCall(call_id="c1", name="remember_fact", arguments=_arguments())),)
    )

    assert pending == {}


async def test_a_label_is_read_with_the_episodes_own_labels() -> None:
    """ADR-0307 §5:7: the recorded call names the memory by label; the record by id."""
    plans = FakePlanStore(now=lambda: _AT)
    await _claimed(plans, _digest(**_arguments(memory="aisle")), ToolOutcome.SUCCEEDED)
    call = ProposedCall(call_id="c1", name="remember_fact", arguments=_arguments(memory="M1"))

    named = await pending_candidates(
        plans,
        (_window(call, labels=(PlanningLabel(label="M1", kind=LabelKind.MEMORY, id="aisle"),)),),
    )
    unnamed = await pending_candidates(plans, (_window(call),))
    story = ProposedCall(call_id="c1", name="remember_fact", arguments=_arguments(memory="S1"))
    wrong_kind = await pending_candidates(
        plans,
        (_window(story, labels=(PlanningLabel(label="S1", kind=LabelKind.STORY, id="aisle"),)),),
    )

    assert named == {_EPISODE: ("prefers window seats",)}
    assert unnamed == {}
    assert wrong_kind == {}


@pytest.mark.parametrize(
    ("state", "pending"),
    [
        (ObservationState.PROCESSED, False),
        (ObservationState.SKIPPED, False),
        (ObservationState.STUCK, False),
        (ObservationState.WAITING, True),
    ],
)
async def test_only_an_episode_the_observer_has_not_settled_is_pending(
    state: ObservationState, pending: bool
) -> None:
    """§16:2: processed, skipped and stuck take an episode out; waiting does not."""
    plans = FakePlanStore(now=lambda: _AT)
    await _claimed(plans, _digest(**_arguments()), ToolOutcome.SUCCEEDED)
    await plans.write_observation(
        ObservationRecord(episode=_EPISODE, state=state), expected_revision=0
    )

    found = await pending_candidates(
        plans, (_window(ProposedCall(call_id="c1", name="remember_fact", arguments=_arguments())),)
    )

    assert bool(found) is pending


class _Unreadable(FakePlanStore):
    async def observations(self, episode_ids: Any, /) -> Any:
        del episode_ids
        msg = "the plan store is down"
        raise PlanningError(msg)


async def test_an_episode_with_no_remember_call_reads_nothing() -> None:
    plans = _Unreadable(now=lambda: _AT)

    assert await pending_candidates(plans, (_window(),)) == {}


async def test_an_unreadable_plan_store_raises_for_the_caller() -> None:
    plans = _Unreadable(now=lambda: _AT)
    call = ProposedCall(call_id="c1", name="remember_fact", arguments=_arguments())

    with pytest.raises(PlanningError):
        await pending_candidates(plans, (_window(call),))


async def test_the_observer_reads_each_candidate_with_its_effect_record() -> None:
    """ADR-0329 §3:3, §9:1: the same join, keeping the record that shows it done."""
    plans = FakePlanStore(now=lambda: _AT)
    await _claimed(plans, _digest(**_arguments()), ToolOutcome.SUCCEEDED, effect_id="effect-7")
    window = _window(ProposedCall(call_id="c1", name="remember_fact", arguments=_arguments()))
    assert window.processing_record is not None

    (done,) = done_candidates(
        window.id, window.processing_record, await plans.activation_effects([_ACTIVATION])
    )

    assert (done.effect, done.round, done.fact) == ("effect-7", _ROUND, "prefers window seats")
    assert done.values["rests_on_this_stimulus"] is True
