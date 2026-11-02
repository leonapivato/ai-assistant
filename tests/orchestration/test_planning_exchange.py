"""ADR-0356 §4:4-§4:6, §5: a work's exchange, held across its rounds by the planning stage.

Each round after a work's first is asked with the first round's instruction and briefing,
byte for byte, then each earlier round's response, as the completer returned it, and the
report after it: one result for each of its calls, in its order and under its ids, then
the news. These hold the stage to that over a scripted completer, and its judge to the
refusals a call whose condition does not hold comes back with.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Final

from exchange_support import news, reported, section, tag, tags
from test_planning import _AT, _call, _digest, _inputs, _stage

from ai_assistant.core.diagnostics import diagnosed_activation
from ai_assistant.core.types import (
    CallOutcomeKind,
    ChannelIdentity,
    DeliveryStatus,
    DiagnosticKind,
    DiagnosticSource,
    LabelKind,
    PlanningLabel,
    RecordedDelivery,
    RoundContinuation,
    RoundResponse,
)
from ai_assistant.orchestration.matter_calls import (
    ANSWER_OFFER,
    MATTER_LABEL_ARGUMENTS,
    STOP_ACTIVATION,
)
from ai_assistant.orchestration.planning import (
    NEWS_OPENING,
    NOTHING_NEW,
    WAITING_ROUND,
    CallOutcome,
    OfferShown,
    PlannedRound,
    PlanningInputs,
    RunningShown,
)
from ai_assistant.orchestration.stories import episode_address
from ai_assistant.testing import FakeDiagnosticSink
from ai_assistant.testing.parties import OWNERS_WORDS

_A: Final = "0b8f8f0e-2a5c-4c55-9a6c-6a2c1f0b0d11"
_B: Final = "1c9a9f1f-3b6d-4d66-8b7d-7b3d2a1c1e22"
_CHAT: Final = ChannelIdentity(channel_type="conversation", instance_id="chat-1")


def _after_now(text: str) -> str:
    """The news past its first line, which says when the report was made (ADR-0360)."""
    now, _, rest = text.partition("\n")
    assert now.startswith("Now: ")
    return rest


def _next(
    planned: PlannedRound, inputs: PlanningInputs, *outcomes: CallOutcome, **fields: Any
) -> PlanningInputs:
    """The next round's inputs: the work held, the round recorded, what came of its calls."""
    return replace(
        inputs,
        work=planned.work,
        rounds=(*inputs.rounds, planned.round),
        labels=(*inputs.labels, *planned.labels),
        outcomes=(*inputs.outcomes, *outcomes),
        **fields,
    )


# --- §5:1-§5:3: the exchange appended ---------------------------------------------------


async def test_a_later_round_hands_in_the_first_rounds_briefing_byte_for_byte() -> None:
    """§5:2, §14:9: the briefing is rendered once, and the instruction and tools with it."""
    first = RoundResponse(
        text="Looking it up.",
        calls=(_call("c1", "search_web", query="museum", looking_for="hours"),),
        continuation=RoundContinuation(model="test:planner", parts={"signed": "thinking"}),
    )
    stage, completer, _ = _stage(first, RoundResponse(text="Done."), RoundResponse())
    inputs = _inputs()

    planned = await stage.plan(inputs)
    second = _next(
        planned, inputs, CallOutcome(planned.round.id, "c1", CallOutcomeKind.NOT_DONE, reason="x")
    )
    planned_again = await stage.plan(second)
    await stage.plan(_next(planned_again, second))

    one, two, three = completer.calls
    assert two.exchange.briefing == one.exchange.briefing == three.exchange.briefing
    assert two.exchange.instruction == one.exchange.instruction == three.exchange.instruction
    assert two.tools == one.tools == three.tools
    assert [len(call.exchange.steps) for call in (one, two, three)] == [0, 1, 2]
    # §6:2: the earlier response is handed back as the completer returned it.
    assert two.exchange.steps[0].response == first
    assert three.exchange.steps[:1] == two.exchange.steps


async def test_a_report_holds_one_result_for_each_call_in_order_then_the_news() -> None:
    """§5:3: one result per call, in the round's order and under its id; a tidy-up's says
    only that it started, since nothing waits for it (ADR-0307 §7:2)."""
    first = RoundResponse(
        calls=(
            _call("c1", "book", slot="19:00"),
            _call("c2", "search_web", query="q", looking_for="it"),
            _call("c3", "tidy_matter", matter="S1"),
        )
    )
    stage, completer, _ = _stage(first, RoundResponse())
    inputs = _inputs()
    planned = await stage.plan(inputs)
    round_id = planned.round.id

    await stage.plan(
        _next(
            planned,
            inputs,
            CallOutcome(round_id, "c1", CallOutcomeKind.DONE, result_id="r:1", result="ok"),
            CallOutcome(round_id, "c2", CallOutcomeKind.REFUSED, reason="no such thing"),
        )
    )

    report = completer.calls[1].exchange.steps[0].report
    assert [one.call_id for one in report.results] == ["c1", "c2", "c3"]
    booked, refused, tidied = reported(completer.calls[1], 0)
    assert booked == {"outcome": "done", "result": {"label": "R1", "value": "ok"}}
    # ADR-0364 §6:1: the outcome, then, with any but done, why.
    assert refused == {"outcome": "refused", "because": "no such thing"}
    assert tidied["outcome"].startswith("started")
    assert _after_now(report.news) == NOTHING_NEW


async def test_a_result_resting_on_outside_content_is_its_digests_evidence_marked() -> None:
    """§5:4: never the raw content: the digest's evidence, each item marked outside."""
    first = RoundResponse(calls=(_call("c1", "search_web", query="q", looking_for="hours"),))
    stage, completer, _ = _stage(first, RoundResponse(text="It opens at nine."))
    inputs = _inputs()
    planned = await stage.plan(inputs)

    second = await stage.plan(
        _next(
            planned,
            inputs,
            CallOutcome(
                planned.round.id, "c1", CallOutcomeKind.DONE, result_id="r:1", digested=True
            ),
            evidence=(_digest("r:1", "It opens at nine."),),
        )
    )

    (searched,) = reported(completer.calls[1], 0)
    assert searched["result"] == {
        "label": "R1",
        "value": "read for you by a digest, under evidence",
    }
    (evidence,) = searched["evidence"]
    item = tag(evidence, "evidence")
    assert item.get("source") == "R1"
    assert item.text == "It opens at nine."
    assert item.get("outside") == "yes"
    # Shown once: not again as news, and the round's notes are marked.
    assert _after_now(news(completer.calls[1], 0)) == NOTHING_NEW
    assert second.round.notes_marked
    assert second.read_outside


# --- §5:5-§5:6: the news --------------------------------------------------------------


def _offer(activation_id: str = _B) -> OfferShown:
    return OfferShown(activation_id=activation_id, input="only two bedrooms", meaning="Two.")


async def test_news_lists_an_offer_newly_open_and_one_that_closed_and_never_repeats() -> None:
    """§5:5-§5:6, §14:9: an offer opened since is news once; one that closed is named."""
    stage, completer, _ = _stage(RoundResponse(), RoundResponse(), RoundResponse(), RoundResponse())
    inputs = _inputs()
    planned = await stage.plan(inputs)

    opened = _next(planned, inputs, offers=(_offer(),))
    planned = await stage.plan(opened)
    still = _next(planned, opened)
    planned = await stage.plan(still)
    closed = _next(planned, still, offers=())
    await stage.plan(closed)

    shown = _after_now(news(completer.calls[1], 0))
    opening, _, offered = shown.partition("\n")
    assert opening == NEWS_OPENING
    offer = tag(offered, "stimulus", offered="yes")
    assert offer.held("understood")[0].text == "Two."
    label = offer.get("label")
    assert label is not None
    assert _after_now(news(completer.calls[2], 1)) == NOTHING_NEW, "never repeats what it showed"
    assert _after_now(news(completer.calls[3], 2)) == (
        f"{NEWS_OPENING}\n- The offer of {label} is no longer open."
    )
    assert tags(section(completer.calls[0].exchange.briefing, "## Concurrent stimuli")) == []


async def test_an_offer_the_briefing_showed_is_no_news() -> None:
    stage, completer, _ = _stage(RoundResponse(), RoundResponse())
    inputs = _inputs(offers=(_offer(),))
    planned = await stage.plan(inputs)
    await stage.plan(_next(planned, inputs))
    concurrent = section(completer.calls[0].exchange.briefing, "## Concurrent stimuli")
    assert tag(concurrent, "stimulus", offered="yes").get("label") == "E1"
    assert _after_now(news(completer.calls[1], 0)) == NOTHING_NEW


async def test_a_message_calls_result_is_its_outcome_alone() -> None:
    """ADR-0364 §9:5: a ``send_text`` call's result is its outcome alone; its entry still
    holds what was sent, where and how (ADR-0357 §3:4)."""
    stage, completer, _ = _stage(
        RoundResponse(calls=(_call("c1", "send_text", connection="L1", words="Booked."),)),
        RoundResponse(),
    )
    inputs = _inputs()
    planned = await stage.plan(inputs)
    delivered = RecordedDelivery(words="Booked.", went=_CHAT, status=DeliveryStatus.SENT)

    await stage.plan(
        _next(
            planned,
            inputs,
            CallOutcome(planned.round.id, "c1", CallOutcomeKind.DONE, delivered=delivered),
        )
    )

    (sent,) = reported(completer.calls[1], 0)
    assert sent == {"outcome": "done"}


async def test_the_given_entry_holds_its_two_messages_only_while_the_briefing_is_alone() -> None:
    """§13:6: the given entry records the exchange as handed in; once it has steps, the two
    messages of the briefing alone are no longer the request, and are left out."""
    sink = FakeDiagnosticSink()
    stage, completer, _ = _stage(
        RoundResponse(calls=(_call("c1", "book"),)), RoundResponse(), diagnostics=sink
    )
    inputs = _inputs()

    with diagnosed_activation(_A, clock=lambda: _AT):
        planned = await stage.plan(inputs)
        await stage.plan(
            _next(planned, inputs, CallOutcome(planned.round.id, "c1", CallOutcomeKind.DONE))
        )

    first, second = (
        one.model_dump(mode="json")["body"]
        for one in sink.of(DiagnosticSource.PLANNING, DiagnosticKind.GIVEN)
    )
    assert "messages" in first
    assert "prompt" in first
    assert "messages" not in second
    assert second["exchange"] == completer.calls[1].exchange.model_dump(mode="json")


# --- §4:4-§4:6: refused, saying why --------------------------------------------------


def _matters(**fields: Any) -> PlanningInputs:
    return _inputs(
        capabilities=(STOP_ACTIVATION, ANSWER_OFFER),
        label_arguments=MATTER_LABEL_ARGUMENTS,
        labels=(
            PlanningLabel(label="E1", kind=LabelKind.EPISODE, id=episode_address(_A)),
            PlanningLabel(label="E2", kind=LabelKind.EPISODE, id=episode_address(_B)),
        ),
        **fields,
    )


async def test_a_call_whose_condition_does_not_hold_comes_back_refused_saying_why() -> None:
    """§4:4: refused before authorizing, with the reason it is given, and runs nothing."""
    stage, _, _ = _stage(RoundResponse(calls=(_call("c1", "stop_work", work="E1"),)))

    planned = await stage.plan(
        _matters(not_here={"stop_work": "a stop runs only on the user's authority"})
    )

    assert planned.calls == ()
    (refused,) = planned.refused
    assert refused.reason == "a stop runs only on the user's authority"


def _waited() -> RunningShown:
    return RunningShown(
        activation_id=_A, place=_CHAT, input="search", acted=True, parties=OWNERS_WORDS
    )


async def test_a_waiting_rounds_stop_runs_only_naming_the_work_it_waits_on() -> None:
    """§4:5, ADR-0349 §7:26: a stop naming other work comes back refused, saying why."""
    stage, _, _ = _stage(
        RoundResponse(
            calls=(
                _call("c1", "stop_work", work="E1"),
                _call("c2", "stop_work", work="E2"),
            )
        )
    )

    planned = await stage.plan(_matters(waiting=(_waited(),)))

    (allowed,) = planned.calls
    assert allowed.call.call_id == "c1"
    assert allowed.call.arguments["work"] == episode_address(_A)
    (refused,) = planned.refused
    assert (refused.call.call_id, refused.reason) == ("c2", WAITING_ROUND)
