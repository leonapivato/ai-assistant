"""The approvals panel past the shared suite: the sensor's wake, and the card's facts.

The shared suite (``approvals_panel_contract``) holds the engine, the canonical fake and
the wire client to the panel's read and tap. What it cannot observe is what each
implementation does beside the store: the engine wakes the Approvals channel's sensor
once a tap's step has landed (ADR-0361 §3:4, §4:9), and a tap is a command, never
perceived, so it admits no activation (§4:7). And the facts a card shows beside its
request are read from the asking activation whether it still runs or has frozen, and
read the cautious way where its episode cannot be read (§2:11).
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from approvals_panel_contract import (
    APPROVALS_AT,
    HUB_CHAT,
    hold_asking_episode,
    hold_request,
)
from test_engine_contract import _wire

from ai_assistant.core.types import (
    ApprovalChoice,
    ApprovalPanelTapAnswer,
    ChannelContext,
    RecordedCall,
    RecordedChannelTrigger,
    RecordedTextInput,
    WholeTextReply,
)
from ai_assistant.orchestration.approval_calls import CardFacts
from ai_assistant.orchestration.engine import approval_card_facts, episode_card_facts
from ai_assistant.testing import FakeAssistantEngine, FakeMemoryStore, FakePlanStore
from ai_assistant.testing.parties import OWNERS_WORDS

if TYPE_CHECKING:
    from ai_assistant.core.types import ApprovalRequest
    from ai_assistant.orchestration.engine import Engine


def _engine(woken: list[None]) -> tuple[Engine, FakePlanStore]:
    plans = FakePlanStore(now=lambda: APPROVALS_AT)
    engine = _wire(
        plans=plans,
        memory=FakeMemoryStore(now=lambda: APPROVALS_AT),
        now=lambda: APPROVALS_AT,
    )
    # The sensor's wake, observed: this subject wires no Approvals channel, so the
    # engine's own would wake nothing.
    engine.approvals_changed = lambda: woken.append(None)  # type: ignore[method-assign]
    return engine, plans


async def test_a_tap_that_lands_wakes_the_sensor_and_admits_nothing() -> None:
    """§3:4, §4:7, §4:9: the sensor pushes the outcome; the tap starts no activation."""
    woken: list[None] = []
    engine, plans = _engine(woken)
    await engine.start()
    try:
        await hold_request(plans, "approval:1")

        tapped = await engine.tap_approval("approval:1", choice=ApprovalChoice.APPROVE)

        assert tapped.answer is ApprovalPanelTapAnswer.ANSWERED
        assert woken == [None]
        assert (await engine.episodes()).items == ()
    finally:
        await engine.aclose()


async def test_a_tap_past_the_expiry_wakes_the_sensor_to_end_it() -> None:
    """§3:5: the sensor ends it expired at its next look, as the line's tap has it."""
    woken: list[None] = []
    engine, plans = _engine(woken)
    await engine.start()
    try:
        await hold_request(plans, "approval:1", ago=timedelta(hours=25))

        tapped = await engine.tap_approval("approval:1", choice=ApprovalChoice.APPROVE)

        assert tapped.answer is ApprovalPanelTapAnswer.EXPIRED
        assert woken == [None]
    finally:
        await engine.aclose()


async def test_a_tap_that_changes_nothing_wakes_nothing() -> None:
    woken: list[None] = []
    engine, plans = _engine(woken)
    await engine.start()
    try:
        await hold_request(plans, "approval:1")
        await engine.tap_approval("approval:1", choice=ApprovalChoice.DENY)
        woken.clear()

        again = await engine.tap_approval("approval:1", choice=ApprovalChoice.APPROVE)
        unknown = await engine.tap_approval("approval:none", choice=ApprovalChoice.APPROVE)

        assert again.answer is ApprovalPanelTapAnswer.ALREADY_ANSWERED
        assert unknown.answer is ApprovalPanelTapAnswer.UNKNOWN
        assert woken == []
    finally:
        await engine.aclose()


async def test_the_fake_counts_the_wake_where_the_engine_runs_it() -> None:
    fake = FakeAssistantEngine()
    fake.approval_clock = lambda: APPROVALS_AT
    fake.plan_store = FakePlanStore(now=lambda: APPROVALS_AT)
    await hold_request(fake.plan_store, "approval:1")

    await fake.tap_approval("approval:1", choice=ApprovalChoice.APPROVE)
    await fake.tap_approval("approval:1", choice=ApprovalChoice.DENY)

    assert fake.approvals_woken == 1


# --- the card's facts (§2:11) ---


def _trigger() -> RecordedChannelTrigger:
    return RecordedChannelTrigger(
        target=HUB_CHAT,
        channel=HUB_CHAT,
        payload=RecordedTextInput(text="book it"),
        context=ChannelContext(),
        reply=WholeTextReply(),
        parties=OWNERS_WORDS,
    )


def _entry(round_id: str, *, marked: bool, capability: str = "request_approval") -> RecordedCall:
    return RecordedCall(
        round=round_id,
        call_id="c1",
        capability=capability,
        effect=True,
        recorded_at=APPROVALS_AT,
        marked=marked,
    )


async def _request() -> ApprovalRequest:
    return await hold_request(FakePlanStore(now=lambda: APPROVALS_AT), "approval:1")


async def test_a_running_activations_facts_are_its_trigger_and_its_rounds_entry() -> None:
    """What the engine reads where the asking work still runs: its own state."""
    request = await _request()

    unmarked = approval_card_facts(request, _trigger(), (_entry(request.round, marked=False),))
    marked = approval_card_facts(request, _trigger(), (_entry(request.round, marked=True),))

    assert unmarked == CardFacts(origin=HUB_CHAT, read_outside=False)
    assert marked == CardFacts(origin=HUB_CHAT, read_outside=True)


async def test_a_round_whose_entry_is_not_recorded_shows_the_outside_line() -> None:
    """Another round's entry, or another call's, says nothing of this request's round:
    the cautious reading, as the line's card reads an episode after a start."""
    request = await _request()

    facts = approval_card_facts(
        request,
        _trigger(),
        (_entry("round:other", marked=False), _entry(request.round, marked=False, capability="t")),
    )

    assert facts == CardFacts(origin=HUB_CHAT, read_outside=True)


async def test_an_unreadable_memory_store_shows_the_cautious_facts() -> None:
    """A store that fails still lets the panel show and answer the request."""
    request = await _request()
    memory = FakeMemoryStore(now=lambda: APPROVALS_AT, failure="the backing is down")
    await hold_asking_episode(memory)

    facts = await episode_card_facts(memory, (request,))

    assert facts == {"approval:1": CardFacts(origin=None, read_outside=True)}


async def test_a_frozen_episode_gives_its_trigger_and_its_entry() -> None:
    request = await _request()
    memory = FakeMemoryStore(now=lambda: APPROVALS_AT)
    await hold_asking_episode(memory)

    facts = await episode_card_facts(memory, (request,))

    assert facts == {"approval:1": CardFacts(origin=HUB_CHAT, read_outside=False)}
