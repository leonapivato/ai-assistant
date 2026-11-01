"""A card-approved ``remember``: its confirmation names the request (ADR-0361 §5:10).

A ``remember`` run under a ticket records its candidate in the work that ran it, the
approval's own activation or the work its input joined by a take. The observer's
confirmation support points at the approval's own episode, where the yes was given, so
its place among the person's statements is when they approved; it names the request,
whose recorded call holds the statement, and the work that ran the ticket beside.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final

import pytest
from observer_support import AT, Harness, address, episode

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActionRequest,
    ActivationEffect,
    ApprovalGiver,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalTap,
    ConfirmationPart,
    EpisodicMemory,
    PlanningRound,
    ProposedCall,
    RequestedCall,
    TicketClaim,
    ToolOutcome,
)
from ai_assistant.orchestration.authorizer import values_digest
from ai_assistant.orchestration.observer.reading import EpisodeReader
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE
from ai_assistant.orchestration.support_parts import part_content, requests_to_read
from ai_assistant.testing.memories import confirmed_support, memory

_WRITTEN: Final = AT - timedelta(hours=3)
_CONTRARY: Final = AT - timedelta(hours=2)
_TAPPED: Final = AT - timedelta(hours=1)
_FACT: Final = "Prefers aisle seats."


def _values() -> dict[str, Any]:
    return {
        "fact": _FACT,
        "why": "you asked me to keep it",
        "episode": address("ask"),
        "rests_on_outside_content": False,
    }


async def _approved(harness: Harness) -> ApprovalRequest:
    """A remember asked about in ``ask``, approved by a tap, pushed to ``appr`` (§3:4)."""
    request = ApprovalRequest(
        id="approval:1",
        person=OWNER_PERSON_ID,
        activation_id="ask",
        round="r-ask",
        call=RequestedCall(tool=REMEMBER_CANDIDATE, values=_values()),
        why="You asked me to keep it.",
        written_at=_WRITTEN,
        expires_at=_WRITTEN + timedelta(hours=24),
    )
    asking = ActivationEffect(
        id="effect-ask",
        activation_id="ask",
        round="r-ask",
        capability="request_approval",
        values_digest="0" * 64,
        decision_id="decision-ask",
        claimed_at=_WRITTEN,
        request=request.id,
    )
    await harness.plans.write_approval_request(request, asking, match=None)
    await harness.plans.answer_approval_request(
        request.id,
        ApprovalRequestState.APPROVED,
        ApprovalTap(who=ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD, at=_TAPPED),
    )
    await harness.plans.mark_approval_outcome_pushed(request.id, "appr")
    (held,) = await harness.plans.approval_requests([request.id])
    return held


async def _ran(harness: Harness, request: ApprovalRequest, ran_in: str) -> None:
    """The ticket's remember, claimed under it in ``ran_in`` and done (§5:4-§5:5)."""
    effect = ActivationEffect(
        id="effect-run",
        activation_id=ran_in,
        round="r-run",
        capability="remember",
        values_digest=values_digest(ActionRequest(tool=REMEMBER_CANDIDATE, parameters=_values())),
        decision_id="decision-run",
        claimed_at=_TAPPED,
        ticket=request.id,
    )
    assert await harness.plans.claim_ticket_call(effect, match=None) is TicketClaim.CLAIMED
    await harness.plans.finish_activation_effect(effect.id, ToolOutcome.SUCCEEDED)


@pytest.mark.parametrize("ran_in", ["appr", "taker"], ids=["its-own-activation", "after-a-take"])
async def test_a_card_approved_remember_is_confirmed_at_the_approvals_episode(ran_in: str) -> None:
    """§5:10, §9:4: the approval's own episode, the request named, the work beside it; a
    contrary statement made between the request and the tap ranks below it."""
    harness = Harness()
    request = await _approved(harness)
    run = PlanningRound(
        id="r-run",
        recorded_at=_TAPPED,
        calls=(ProposedCall(call_id="c1", name="run_approved", arguments={"label": "A1"}),),
    )
    held = [
        episode("ask", at=_WRITTEN),
        episode("contrary", at=_CONTRARY, text="Actually I like window seats."),
        episode("appr", at=_TAPPED, rounds=(run,) if ran_in == "appr" else ()),
    ]
    if ran_in == "taker":
        held.append(episode("taker", at=_WRITTEN, rounds=(run,)))
    await harness.hold(*held)
    await _ran(harness, request, ran_in)

    leaving = await harness.memory.get(address(ran_in))
    assert isinstance(leaving, EpisodicMemory)
    reading = await EpisodeReader(
        memory=harness.memory, plans=harness.plans, stories=harness.stories
    ).read(leaving)

    (hint,) = [one for one in reading.hints if one.confirmation is not None]
    confirmation = hint.confirmation
    assert confirmation is not None
    assert hint.fact == _FACT
    assert confirmation.part == ConfirmationPart(
        episode=address("appr"), asking_activation="ask", request=request.id, ran_in=ran_in
    )
    assert confirmation.text == _FACT, "the statement the request's recorded call holds"
    assert confirmation.when == _TAPPED
    assert confirmation.episode == address("appr")
    assert confirmation.occurred_at > _CONTRARY, "it ranks as the newer"


async def test_the_request_form_resolves_to_the_requests_statement_or_gone() -> None:
    """§5:10: the part points at the approval's episode and its statement is the call's."""
    harness = Harness()
    request = await _approved(harness)
    part = ConfirmationPart(
        episode=address("appr"), asking_activation="ask", request=request.id, ran_in="appr"
    )
    held = episode("appr", at=_TAPPED)
    confirmed = confirmed_support(address("appr")).model_copy(update={"points_at": part})
    assert requests_to_read([memory("m-1", _FACT, confirmed)]) == (request.id,)
    resolved = part_content(
        part,
        episodes={held.id: held},
        effects={},
        carried=None,
        requests={str(request.id): request},
    )
    assert resolved == _FACT
    assert (
        part_content(part, episodes={held.id: held}, effects={}, carried=None, requests={}) is None
    ), "a request the store no longer holds is gone"
    assert part_content(part, episodes={}, effects={}, carried=None, requests={}) is None
