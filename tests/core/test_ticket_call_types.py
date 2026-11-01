"""ADR-0362 §2:1-§2:2 and §3:1: a ticket's call in the person model's act and the spawn's write.

``PersonModelAct`` gains its request form beside its question form, and a spawn's write
answers a ticket's refusals as ``TicketClaim`` names them. Behaviour over a store is the
``PersonModelStore`` and ``PlanStore`` conformance suites'.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    PersonActHow,
    PersonModelAct,
    QuestionPart,
    ScheduledTaskWrite,
    TaskRefusal,
    TaskWriteAnswer,
    TicketClaim,
)

_PART = QuestionPart(round="round-1", part=1)
_EPISODE = "activation:act-approval"


def test_a_yes_names_its_question_part_or_its_request() -> None:
    """§2:1: the two forms of an act made by a yes, each with the yes's episode."""
    by_part = PersonModelAct(
        how=PersonActHow.APPROVAL, by=OWNER_PERSON_ID, approval=_PART, episode_id=_EPISODE
    )
    by_ticket = PersonModelAct(
        how=PersonActHow.APPROVAL, by=OWNER_PERSON_ID, request="q-1", episode_id=_EPISODE
    )

    assert (by_part.approval, by_part.request) == (_PART, None)
    assert (by_ticket.approval, by_ticket.request) == (None, "q-1")


@pytest.mark.parametrize(
    "fields",
    [
        {"how": PersonActHow.APPROVAL, "approval": _PART, "request": "q-1"},
        {"how": PersonActHow.APPROVAL},
        {"how": PersonActHow.PANEL, "request": "q-1"},
        {"how": PersonActHow.SUGGESTION, "request": "q-1"},
    ],
    ids=["both", "neither", "panel-with-request", "suggestion-with-request"],
)
def test_an_act_names_one_approval_exactly_when_a_yes_made_it(fields: dict[str, Any]) -> None:
    """§2:1: exactly one of the question part and the request, and only on a yes."""
    episode = None if fields["how"] is PersonActHow.PANEL else _EPISODE
    with pytest.raises(ValidationError, match="one approval"):
        PersonModelAct(by=OWNER_PERSON_ID, episode_id=episode, **fields)


@pytest.mark.parametrize("request_id", ["", "   "])
def test_a_request_is_named_by_an_identifier(request_id: str) -> None:
    with pytest.raises(ValidationError):
        PersonModelAct(
            how=PersonActHow.APPROVAL, by=OWNER_PERSON_ID, request=request_id, episode_id=_EPISODE
        )


def test_the_request_form_still_names_the_approvals_episode() -> None:
    """§2:1: on the request form, ``episode_id`` is the approval's own episode."""
    with pytest.raises(ValidationError, match="names an episode"):
        PersonModelAct(how=PersonActHow.APPROVAL, by=OWNER_PERSON_ID, request="q-1")


@pytest.mark.parametrize(
    "act",
    [
        PersonModelAct(how=PersonActHow.SEED),
        PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID),
        PersonModelAct(
            how=PersonActHow.APPROVAL, by=OWNER_PERSON_ID, approval=_PART, episode_id=_EPISODE
        ),
        PersonModelAct(how=PersonActHow.SUGGESTION, by=OWNER_PERSON_ID, episode_id=_EPISODE),
    ],
    ids=["seed", "panel", "question", "suggestion"],
)
def test_an_act_of_every_earlier_form_dumps_as_it_did(act: PersonModelAct) -> None:
    """§2:2: ``request`` is left out where unset, so the stored bytes do not move."""
    assert set(act.model_dump()) == {"how", "by", "approval", "episode_id"}
    assert "request" not in act.model_dump_json()
    assert PersonModelAct.model_validate_json(act.model_dump_json()) == act


def test_an_act_of_the_request_form_dumps_its_request() -> None:
    act = PersonModelAct(
        how=PersonActHow.APPROVAL, by=OWNER_PERSON_ID, request="q-1", episode_id=_EPISODE
    )

    assert act.model_dump()["request"] == "q-1"
    assert PersonModelAct.model_validate_json(act.model_dump_json()) == act


@pytest.mark.parametrize(
    "refused", [TicketClaim.NOT_GRANTED, TicketClaim.USED, TicketClaim.VOID, TicketClaim.EXPIRED]
)
def test_a_spawns_write_carries_a_tickets_refusal_as_its_answer_says(
    refused: TicketClaim,
) -> None:
    """§3:1: the ticket's refusal exactly where the answer is ``ticket_refused``."""
    written = ScheduledTaskWrite(answer=TaskWriteAnswer.TICKET_REFUSED, ticket=refused)

    assert (written.task, written.reason, written.ticket) == (None, None, refused)


@pytest.mark.parametrize(
    "fields",
    [
        {"answer": TaskWriteAnswer.TICKET_REFUSED},
        {"answer": TaskWriteAnswer.ALREADY_DONE, "ticket": TicketClaim.USED},
        {
            "answer": TaskWriteAnswer.REFUSED,
            "reason": TaskRefusal.PENDING_LIMIT,
            "ticket": TicketClaim.VOID,
        },
    ],
    ids=["no-refusal", "on-the-backstop", "on-a-refusal"],
)
def test_a_tickets_refusal_rides_on_its_answer_alone(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="ticket's refusal"):
        ScheduledTaskWrite(**fields)


@pytest.mark.parametrize("answer", [TicketClaim.CLAIMED, TicketClaim.ALREADY_DONE])
def test_a_tickets_refusal_is_one(answer: TicketClaim) -> None:
    """A ticket claimed is a write, and the backstop's refusal is the spawn's own."""
    with pytest.raises(ValidationError, match="not_granted, used, void or expired"):
        ScheduledTaskWrite(answer=TaskWriteAnswer.TICKET_REFUSED, ticket=answer)
