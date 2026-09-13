"""The browser's goal surface, at the gateway (ADR-0250 §15, §19's M4).

§15 places this surface by name — "the command line and the browser both implement
this decision" — and ADR-0250's ``- Status:`` line records the widening against
ADR-0177 §1: "§1's thirty-operation enumeration alone, which gains ``goals``,
``withdraw_clarification`` and ``abandon_goal``", which is the route §1's third clause
fixes.

**Both halves are asserted, because either alone is weak.** The table says the
enumeration names them; the driven requests say the router really reaches the engine for
them, with the arguments the promoted surface declares and no others — and that nothing
is derived, defaulted or composed on the way (ADR-0177 §1, golden rule 3).

**Answering a clarification is not a fourth path**, and that is §11's construction
rather than an economy here: "answering is a turn and not an operation of its own, and
that is the whole reason ``converse`` gains a keyword rather than the surface gaining a
fifth verb". So the reference rides ``/ask`` and ``/ask/stream``, and the cases below
drive it there.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest
from test_gateway_streams import Harness, _harness, _values

from ai_assistant.core.types import (
    Clarification,
    ClarificationWithdrawal,
    GoalAbandonment,
    GoalStatus,
    GoalSummary,
    TurnReference,
)
from ai_assistant.interfaces.gateway.server import _ASSISTANT_PATHS

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration

GOAL_ID: Final = "goal-zzqq-7741"
QUESTION_ID: Final = "question-xxpp-9930"
OUTCOME: Final = "Book the usual campsite for the last weekend of August."
QUESTION: Final = "Which campsite do you mean — Ericeira or Melides?"
DEADLINE: Final = datetime(2026, 1, 8, 11, tzinfo=UTC)
ENGAGED: Final = datetime(2026, 1, 1, 11, tzinfo=UTC)

#: The three operations ADR-0250 puts inside ADR-0177 §1's enumeration.
_GOAL_OPERATIONS: Final = frozenset({"goals", "withdraw_clarification", "abandon_goal"})


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    """A gateway on ADR-0168 §8's and ADR-0175 §8's own figures."""
    async with _harness() as one:
        yield one


def _summary() -> GoalSummary:
    return GoalSummary(
        id=GOAL_ID,
        outcome=OUTCOME,
        status=GoalStatus.ACTIVE,
        paused=True,
        last_engaged_at=ENGAGED,
        clarification=Clarification(question_id=QUESTION_ID, text=QUESTION, expires_at=DEADLINE),
    )


def test_the_three_operations_are_in_the_enumeration_the_router_classifies_from() -> None:
    """ADR-0177 §1's enumeration, read off the one table the gateway decides from.

    ADR-0250's ``- Status:`` line is the ratified widening — "§1's thirty-operation
    enumeration alone, which gains ``goals``, ``withdraw_clarification`` and
    ``abandon_goal``" — and it adds nothing else: "§1's every-argument-the-browser-owns
    clause, its caller-owned-deadline class — **which gains no member, because none of
    the three takes a turn budget** — its ``learn``-is-unreached clause and its
    single-principal clause bind entire".

    So the deadline class is asserted as unmoved as well, over the bodies below: none of
    the three carries a ``timeout`` and none is given one.
    """
    assert set(_ASSISTANT_PATHS.values()) >= _GOAL_OPERATIONS
    assert ("POST", "/goals") in _ASSISTANT_PATHS
    assert ("POST", "/clarification/withdraw") in _ASSISTANT_PATHS
    assert ("POST", "/goal/abandon") in _ASSISTANT_PATHS


async def test_the_listing_carries_every_field_the_summary_holds(harness: Harness) -> None:
    """ADR-0250 §15's listing, rendered member by member.

    The view is an enumeration for ``_outcome_view``'s reason — what may appear on the
    page is decided in the gateway rather than by whatever ``GoalSummary`` happens to
    carry — so the roster is asserted whole rather than by presence: a member that stops
    being carried is as much a defect as one that starts being carried unreviewed.

    **``paused`` is carried and never derived**: §15 makes it the engine's, "so that two
    surfaces cannot render it differently … and no adapter derives it".
    """
    harness.engine.goal_summaries = [_summary()]
    status, body = await harness.whole("POST", "/goals", {})

    assert status == 200
    (row,) = body["goals"]
    assert set(row) == {
        "id",
        "outcome",
        "status",
        "paused",
        "last_engaged_at",
        "clarification",
    }
    assert row["id"] == GOAL_ID
    assert row["outcome"] == OUTCOME
    assert row["status"] == "active"
    assert row["paused"] is True
    assert row["last_engaged_at"] == ENGAGED.isoformat()
    assert row["clarification"] == {
        "question_id": QUESTION_ID,
        "text": QUESTION,
        "expires_at": DEADLINE.isoformat(),
    }


async def test_the_listing_is_paged_on_the_browsers_own_arguments(harness: Harness) -> None:
    """ADR-0085 §3's convention, and ADR-0177 §1's browser-owned arguments.

    The gateway "derives none of them, defaults none of them, composes no operation out
    of two, and synthesises no result from a call it did not make" — so the page it asks
    for is the page the browser named, and the answer carries no total, because §15
    makes the operation answer none on ADR-0074 §2's ground.
    """
    harness.engine.goal_summaries = [_summary(), _summary()]
    status, body = await harness.whole("POST", "/goals", {"limit": 1, "offset": 1})

    assert status == 200
    assert len(body["goals"]) == 1
    assert set(body) == {"goals"}
    assert harness.engine.calls[-1] == ("goals", {"limit": 1, "offset": 1})


async def test_a_withdrawal_relays_the_id_and_answers_the_member(harness: Harness) -> None:
    """ADR-0250 §12, relayed and rendered (golden rule 3, ADR-0042 §6).

    "It takes no reason, no free text and no deadline" — so the body carries the id and
    nothing else reaches the engine — and the answer is one member of a closed
    vocabulary, which the page renders one fixed statement for. Nothing here rules,
    records or infers: a withdrawal "records no answer, revises no interpretation and
    engages no goal".
    """
    harness.engine.withdrawal = ClarificationWithdrawal.WITHDRAWN
    status, body = await harness.whole(
        "POST", "/clarification/withdraw", {"question_id": QUESTION_ID}
    )

    assert status == 200
    assert body == {"withdrawal": "withdrawn"}
    assert harness.engine.calls[-1] == ("withdraw_clarification", {"question_id": QUESTION_ID})


async def test_an_unknown_question_is_a_result_and_never_a_refusal(harness: Harness) -> None:
    """ADR-0250 §12: "an unknown id is ``NOTHING_TO_WITHDRAW`` and **never a raise**".

    Which is ``AssistantEngineContract::test_a_refusal_is_a_result_and_not_an_exception``
    binding at this seam — so the surface answers ``200`` with the member rather than a
    fault the page would have to read as a transport failure.
    """
    harness.engine.withdrawal = ClarificationWithdrawal.NOTHING_TO_WITHDRAW
    status, body = await harness.whole(
        "POST", "/clarification/withdraw", {"question_id": "nothing-of-that-id"}
    )

    assert status == 200
    assert body == {"withdrawal": "nothing_to_withdraw"}


async def test_an_abandonment_relays_the_id_and_answers_the_member(harness: Harness) -> None:
    """ADR-0250 §12's one producer of ``ABANDONED``, reached and not re-implemented.

    This adapter is a conveyor of the act: no expiry, no silence, no timeout and no
    inference of the gateway's writes the status, and the body carries the goal's id
    and nothing else.
    """
    harness.engine.abandonment = GoalAbandonment.ABANDONED
    status, body = await harness.whole("POST", "/goal/abandon", {"goal_id": GOAL_ID})

    assert status == 200
    assert body == {"abandonment": "abandoned"}
    assert harness.engine.calls[-1] == ("abandon_goal", {"goal_id": GOAL_ID})


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/clarification/withdraw", {}),
        ("/clarification/withdraw", {"question_id": 7}),
        ("/goal/abandon", {}),
        ("/goal/abandon", {"goal_id": None}),
    ],
)
async def test_a_malformed_act_is_refused_before_the_engine_is_reached(
    harness: Harness, path: str, payload: dict[str, object]
) -> None:
    """ADR-0168 §1's biconditional: a refusal the gateway takes reaches no engine.

    The id is the whole of each body, so a body without one is the page and the gateway
    disagreeing about a shape — refused at this boundary, with the engine untouched.
    """
    status, _ = await harness.whole("POST", path, payload)

    assert status == 400
    assert harness.engine.calls == []


# --- the reference, on the two turn entries (ADR-0250 §11, §13) --------------


async def test_a_turn_carries_the_browsers_reference_whole(harness: Harness) -> None:
    """ADR-0250 §11's keyword, relayed and resolved by nothing.

    "A reference is never rendered to a model and never accepted from one. It is
    resolved by ``orchestration`` against records this system holds" — so the gateway
    reads two strings, builds the value the surface declares, and hands it over. What
    became of it comes back on the outcome.
    """
    status, _ = await harness.whole(
        "POST",
        "/ask",
        {"utterance": "the one at Melides", "reference": {"question_id": QUESTION_ID}},
    )

    assert status == 200
    assert harness.engine.calls[-1][1]["reference"] == TurnReference(question_id=QUESTION_ID)


async def test_a_goal_is_taken_up_from_the_listing_the_browser_was_shown(
    harness: Harness,
) -> None:
    """ADR-0250 §13's decision 5, at the surface that performs it.

    "A goal is resumed from another conversation by explicit reference and by that
    alone", the reference being "a ``TurnReference`` carrying a ``goal_id`` (§11),
    performed from a surface listing the user was shown (§15)".
    """
    status, _ = await harness.whole(
        "POST", "/ask", {"utterance": "make it Monday", "reference": {"goal_id": GOAL_ID}}
    )

    assert status == 200
    assert harness.engine.calls[-1][1]["reference"] == TurnReference(goal_id=GOAL_ID)


async def test_a_turn_naming_no_reference_carries_none(harness: Harness) -> None:
    """Absent is the absence and never a default, which is ``_optional_string``'s posture.

    A turn carrying no reference is the ordinary turn, and ``converse``'s keyword
    defaults to ``None`` for exactly that reason.
    """
    status, _ = await harness.whole("POST", "/ask", {"utterance": "what is on today"})

    assert status == 200
    assert harness.engine.calls[-1][1]["reference"] is None


@pytest.mark.parametrize(
    "reference",
    [
        {"question_id": QUESTION_ID, "goal_id": GOAL_ID},
        {},
        {"question_id": None, "goal_id": None},
        "question-1",
        {"question_id": 7},
        # A member the object does not declare, which is the type's own `extra="forbid"`
        # at the one seam that would otherwise strip it. Read by name and discarded, this
        # is a caller naming **both** records — the shape §11's validator exists to
        # refuse — running as an ordinary turn against the goal. Adversarial review,
        # round 1, `blocker`.
        {"goal_id": GOAL_ID, "question_idd": QUESTION_ID},
        {"question_id": QUESTION_ID, "conversation_id": "c-1"},
    ],
)
async def test_a_reference_naming_other_than_one_record_is_refused(
    harness: Harness, reference: object
) -> None:
    """ADR-0250 §11 admits exactly two shapes, and the type is the authority.

    "A model validator admits exactly two shapes: a ``question_id`` and no ``goal_id``,
    or a ``goal_id`` and no ``question_id``. A shape a caller cannot reach is better
    refused by the type than documented." The gateway does not restate that rule — it
    hands the object over and turns the refusal into this boundary's one refusal kind,
    so a page and a gateway that disagree about a shape get the answer every other
    malformed body gets, and the engine is not reached.

    **And a member the object does not declare is refused rather than ignored**, which
    is ``extra="forbid"`` reaching the one seam that would otherwise strip it: two reads
    by name would turn ``{"goal_id": "g", "question_idd": "q"}`` — a caller naming both
    records — into an ordinary turn against ``g``, reported as success. That is
    :func:`_optional_string`'s own rule: a member present and wrong is refused rather
    than read as an absence, because reading it as one "would answer a *different*
    well-formed question instead". Adversarial review, round 1, ``blocker``.
    """
    status, _ = await harness.whole("POST", "/ask", {"utterance": "either", "reference": reference})

    assert status == 400
    assert harness.engine.calls == []


async def test_the_streamed_entry_carries_the_reference_too(harness: Harness) -> None:
    """ADR-0173: ``converse_streaming`` takes "exactly ``converse``'s arguments".

    So the keyword needs no record of its own and the two entries carry it alike. A
    browser that could answer a clarification only by switching off streaming would be
    one where the gateway had chosen between the entries, which ADR-0175 §3 forbids.
    """
    reader, _, status = await harness.send(
        "POST",
        "/ask/stream",
        {"utterance": "the one at Melides", "reference": {"question_id": QUESTION_ID}},
    )
    assert status == 200
    # Read the stream to its terminal value rather than to the socket closing: the
    # gateway keeps a connection alive after a stream ends, so reading to EOF would
    # wait out the idle timeout for a fact the last value already carries.
    values = [value async for value in _values(reader)]
    assert values[-1]["kind"] == "outcome"

    streamed = [call for call in harness.engine.calls if call[0] == "converse_streaming"]
    assert streamed[-1][1]["reference"] == TurnReference(question_id=QUESTION_ID)
