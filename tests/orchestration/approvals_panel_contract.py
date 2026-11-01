"""Shared obligations of ``AssistantEngine``'s approvals-panel members (ADR-0361 §4:6-§4:9).

Every implementation answers the hub page's approvals panel from the one approvals
store, the plan store (§4:1), showing each request as its card shows it, by the one
renderer every surface shows a request by (§2:11), with the facts the request does not
record read from the episode of the activation that asked; and every implementation
carries out the panel's tap in the store's one step, so the first tap to land, on the
panel or on the card, wins (§4:9). The person is the owner's, whom every device admitted
under ADR-0124 carries (§4:8, ADR-0124 §5): a request for anyone else is neither shown
nor answered.

The engine and the canonical fake answer through ``orchestration.engine``'s
module-level panel reading, and the wire client through a hub serving the fake, so a
clause here holds the card's text, the lists' order and bounds and the first tap's win
against three surfaces.

A mixin, as ``person_model_contract`` is, so the engine, the canonical fake and the wire
client each bind it in the file that binds the rest of the suite.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import (
    APPROVAL_WHY_MAX_CHARS,
    OWNER_PERSON_ID,
    ActivationEffect,
    ApprovalCardState,
    ApprovalChoice,
    ApprovalGiver,
    ApprovalPanelTapAnswer,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalStepAnswer,
    ApprovalTap,
    CapabilityEffect,
    CapabilityResult,
    ChannelContext,
    ChannelIdentity,
    ControllerRule,
    CostBasis,
    DataTier,
    EpisodeProcessingRecord,
    EpisodicMemory,
    Idempotency,
    MemorySource,
    NewConversation,
    PlanningRound,
    ProcessingReason,
    ProcessingStatus,
    ProposedCall,
    Provenance,
    RecordedCall,
    RecordedChannelTrigger,
    RecordedTextInput,
    RequestedCall,
    Reversibility,
    RiskLevel,
    TicketState,
    ToolCost,
    ToolDefinition,
    UnderstandingOmission,
    WholeTextReply,
)
from ai_assistant.orchestration.approval_calls import OUTSIDE_LINE, CardFacts, card_text
from ai_assistant.testing.activation import ended_pass
from ai_assistant.testing.parties import OWNERS_WORDS

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.testing import FakeMemoryStore, FakePlanStore

#: The contract limit each subject is built at: room for a panel of a few long requests,
#: and small enough that a page of the longest ones is past it.
APPROVALS_LIMIT: Final = 64 * 1024

#: The instant each subject reads its panel and stamps its taps at, its stores clocked
#: there too. Every request below is written before it.
APPROVALS_AT: Final = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)

#: How long a request waits on its person (ADR-0361 §3:5).
DAY: Final = timedelta(hours=24)

#: A call the person is asked to approve: one that does not leave the hub, so a request
#: holds no binding.
BOOK: Final = ToolDefinition(
    id="book",
    capability="book",
    description="Book a table for a date.",
    risk_level=RiskLevel.HIGH,
    reversibility=Reversibility.RECOVERABLE,
    side_effecting=True,
    reads=(DataTier.PERSONAL,),
    writes=(DataTier.PERSONAL,),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
    effect=CapabilityEffect.WORLD,
    leaves_hub=False,
    result=CapabilityResult.NO_OUTSIDE_TEXT,
    outcome_can_be_unknown=True,
    safe_to_repeat=False,
    parameters_schema={
        "type": "object",
        "properties": {"date": {"type": "string"}},
        "required": ["date"],
    },
)

#: Where the asking work of a seeded episode came from: the hub chat.
HUB_CHAT: Final = ChannelIdentity(channel_type="conversation", instance_id="conv-1")

#: The tap the line's card makes, as AP3's reader marks it (§4:9).
CARD: Final = ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD


@dataclass(frozen=True)
class ApprovalsPanelSubject:
    """An engine and the two stores its panel reads, seeded from the test process.

    Attributes:
        engine: The subject under test, clocked at :data:`APPROVALS_AT`.
        plans: The plan store the requests are held in, the Approvals channel's content.
        memory: The memory store the asking activations' episodes are held in.
    """

    engine: AssistantEngine
    plans: FakePlanStore
    memory: FakeMemoryStore


async def hold_request(  # noqa: PLR0913 — one knob per part of a request a case varies
    plans: FakePlanStore,
    request_id: str,
    *,
    ago: timedelta = timedelta(hours=1),
    why: str = "You asked me to book the table.",
    date: str = "Friday",
    person: str = OWNER_PERSON_ID,
    activation: str = "act-ask",
) -> ApprovalRequest:
    """Write one request as ``request_approval`` writes it, ``ago`` before the subject's now.

    It holds no card: the line is not connected, or its post failed (§2:7), so the panel
    is where it is answered.
    """
    at = APPROVALS_AT - ago
    request = ApprovalRequest(
        id=request_id,
        person=person,
        activation_id=activation,
        round=f"round:{activation}",
        call=RequestedCall(tool=BOOK, values={"date": date}),
        why=why,
        written_at=at,
        expires_at=at + DAY,
    )
    effect = ActivationEffect(
        id=f"effect:{request_id}",
        activation_id=activation,
        round=f"round:{activation}",
        capability="request_approval",
        values_digest="0" * 64,
        decision_id=f"decision:{request_id}",
        claimed_at=at,
        request=request_id,
    )
    await plans.write_approval_request(request, effect, match=None)
    return request


async def hold_asking_episode(
    memory: FakeMemoryStore,
    activation: str = "act-ask",
    *,
    channel: ChannelIdentity | None = HUB_CHAT,
    marked: bool = False,
) -> None:
    """Hold the frozen episode of the activation that asked, its card's facts in it.

    Its trigger came from ``channel``, and its one round recorded one
    ``request_approval`` call, resting on outside content where ``marked``.
    """
    at = APPROVALS_AT - timedelta(hours=2)
    round_id = f"round:{activation}"
    record = EpisodeProcessingRecord(
        activation_id=activation,
        started_at=at,
        ended_at=at,
        trigger=RecordedChannelTrigger(
            target=NewConversation() if channel is None else channel,
            channel=channel,
            payload=RecordedTextInput(text="book the table for friday"),
            context=ChannelContext(),
            reply=WholeTextReply(),
            parties=OWNERS_WORDS,
        ),
        status=ProcessingStatus.COMPLETED,
        reason=ProcessingReason.RETURNED,
        understanding=(),
        understanding_omitted=UnderstandingOmission.NOT_REACHED,
        stages=ended_pass(at, ControllerRule.NOTHING_DUE),
        rounds=(
            PlanningRound(
                id=round_id,
                recorded_at=at,
                calls=(ProposedCall(call_id="c1", name="request_approval", arguments={}),),
            ),
        ),
        call_records=(
            RecordedCall(
                round=round_id,
                call_id="c1",
                capability="request_approval",
                effect=True,
                recorded_at=at,
                marked=marked,
            ),
        ),
    )
    await memory.add(
        EpisodicMemory(
            id=f"activation:{activation}",
            content="",
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=at),
            occurred_at=at,
            outcome="Asked.",
            processing_record=record,
        )
    )


async def card_tap(
    plans: FakePlanStore, request_id: str, state: ApprovalRequestState, *, ago: timedelta
) -> None:
    """Answer a request as the line's card does, ``ago`` before the subject's now."""
    step = await plans.answer_approval_request(
        request_id, state, ApprovalTap(who=CARD, at=APPROVALS_AT - ago)
    )
    assert step.answer is ApprovalStepAnswer.CHANGED


class ApprovalsPanelContract:
    """The approvals panel's members through the engine, the fake and the wire client."""

    @pytest.fixture
    def approvals_subject(self) -> ApprovalsPanelSubject:
        """Override with an implementation clocked at :data:`APPROVALS_AT`.

        Built at :data:`APPROVALS_LIMIT`, its stores clocked at the same instant.
        """
        raise NotImplementedError

    # --- the read (§4:6) ---

    async def test_a_hub_holding_no_request_shows_an_empty_panel(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        panel = await approvals_subject.engine.approvals()

        assert panel.pending == ()
        assert panel.recent == ()

    async def test_a_pending_request_is_shown_as_its_card_shows_it(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """§4:6, §2:11: the one renderer's text, with the facts read from its episode."""
        subject = approvals_subject
        request = await hold_request(subject.plans, "approval:1")
        await hold_asking_episode(subject.memory)

        panel = await subject.engine.approvals()

        (entry,) = panel.pending
        assert panel.recent == ()
        assert entry.request_id == "approval:1"
        assert entry.state is ApprovalCardState.PENDING
        assert entry.written_at == request.written_at
        assert entry.expires_at == request.expires_at
        assert entry.answered_by is None
        assert entry.text == card_text(
            request, CardFacts(origin=HUB_CHAT, read_outside=False), now=APPROVALS_AT
        )
        assert "Why: You asked me to book the table." in entry.text
        assert "Asked in the hub chat." in entry.text
        assert OUTSIDE_LINE not in entry.text
        assert entry.text.endswith("Waiting for your answer.")

    async def test_a_request_asked_after_outside_content_says_so(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """§2:11, ADR-0306 §4:5: the outside-content line, as the card shows it."""
        subject = approvals_subject
        await hold_request(subject.plans, "approval:1")
        await hold_asking_episode(subject.memory, marked=True)

        (entry,) = (await subject.engine.approvals()).pending

        assert OUTSIDE_LINE in entry.text

    async def test_a_request_whose_episode_is_not_held_is_shown_the_cautious_way(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """No episode to read: where it was asked is not recorded, and the outside line
        is shown, so the person is never told less than the card could have said."""
        subject = approvals_subject
        await hold_request(subject.plans, "approval:1")

        (entry,) = (await subject.engine.approvals()).pending

        assert "Where it was asked is not recorded." in entry.text
        assert OUTSIDE_LINE in entry.text

    async def test_pending_requests_are_shown_oldest_first(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """The oldest expires first, so it is shown first."""
        subject = approvals_subject
        await hold_request(subject.plans, "approval:new", ago=timedelta(hours=1), date="a")
        await hold_request(subject.plans, "approval:old", ago=timedelta(hours=5), date="b")

        panel = await subject.engine.approvals()

        assert [one.request_id for one in panel.pending] == ["approval:old", "approval:new"]

    async def test_answered_and_expired_requests_are_recent_the_most_recent_first(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """§4:6: the ones answered most recently, with their state; an expired one by its
        expiry, a still-pending one past it shown expired (§3:5)."""
        subject = approvals_subject
        await hold_request(subject.plans, "approval:yes", ago=timedelta(hours=6), date="a")
        await card_tap(
            subject.plans, "approval:yes", ApprovalRequestState.APPROVED, ago=timedelta(hours=5)
        )
        await hold_request(subject.plans, "approval:no", ago=timedelta(hours=6), date="b")
        await card_tap(
            subject.plans, "approval:no", ApprovalRequestState.DENIED, ago=timedelta(hours=1)
        )
        # Written 25 hours ago, so it expired an hour ago, unanswered: shown expired, as
        # no tap can approve it now, whether or not the sensor has ended it.
        await hold_request(subject.plans, "approval:late", ago=timedelta(hours=27), date="c")
        await hold_request(subject.plans, "approval:lapsed", ago=timedelta(hours=27), date="d")
        expired = await subject.plans.expire_approval_request(
            "approval:lapsed", APPROVALS_AT - timedelta(hours=3)
        )
        assert expired.answer is ApprovalStepAnswer.CHANGED

        panel = await subject.engine.approvals()

        assert panel.pending == ()
        assert [(one.request_id, one.state) for one in panel.recent] == [
            ("approval:no", ApprovalCardState.DENIED),
            ("approval:late", ApprovalCardState.EXPIRED),
            ("approval:lapsed", ApprovalCardState.EXPIRED),
            ("approval:yes", ApprovalCardState.APPROVED),
        ]
        no = panel.recent[0]
        assert no.answered_by is CARD
        assert no.answered_at == APPROVALS_AT - timedelta(hours=1)
        assert no.text.endswith("Denied.")
        assert panel.recent[1].answered_by is None
        assert panel.recent[1].text.endswith("Expired: it was not answered in time.")

    async def test_a_used_and_a_void_ticket_are_shown_as_their_cards_show_them(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """§4:5: after a yes, used or not used."""
        subject = approvals_subject
        await hold_request(subject.plans, "approval:void", ago=timedelta(hours=3))
        await card_tap(
            subject.plans, "approval:void", ApprovalRequestState.APPROVED, ago=timedelta(hours=2)
        )
        voided = await subject.plans.void_approval_ticket("approval:void")
        assert voided.request.ticket is TicketState.VOID

        (entry,) = (await subject.engine.approvals()).recent

        assert entry.state is ApprovalCardState.NOT_USED
        assert entry.text.endswith("Approved, not used.")

    async def test_another_persons_request_is_not_shown(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """§4:8: the panel is the person's own, and the hub page's person is the owner."""
        subject = approvals_subject
        await hold_request(subject.plans, "approval:theirs", person="person:guest")

        panel = await subject.engine.approvals()

        assert panel.pending == ()
        assert panel.recent == ()

    async def test_each_list_holds_at_most_the_limit(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        subject = approvals_subject
        for index in range(3):
            await hold_request(
                subject.plans,
                f"approval:p{index}",
                ago=timedelta(hours=3 - index),
                date=f"p{index}",
            )
            await hold_request(
                subject.plans, f"approval:d{index}", ago=timedelta(hours=9), date=f"d{index}"
            )
            await card_tap(
                subject.plans,
                f"approval:d{index}",
                ApprovalRequestState.DENIED,
                ago=timedelta(hours=8 - index),
            )

        panel = await subject.engine.approvals(limit=2)

        assert [one.request_id for one in panel.pending] == ["approval:p0", "approval:p1"]
        assert [one.request_id for one in panel.recent] == ["approval:d2", "approval:d1"]

    async def test_a_request_too_long_for_one_telegram_message_is_shown_whole(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """§4:4: a card too long for one message is answered on the panel, which shows it
        whole."""
        subject = approvals_subject
        why = "w" * APPROVAL_WHY_MAX_CHARS
        await hold_request(subject.plans, "approval:long", why=why, date="d" * 1000)

        (entry,) = (await subject.engine.approvals()).pending

        assert f"Why: {why}" in entry.text
        assert len(entry.text) > 4096

    async def test_a_panel_past_the_contract_limit_is_fitted_and_still_answers(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """ADR-0085 §8, §4:4: requests too long for a card, more than one answer holds.

        The panel leaves out what does not fit, the newest pending last of all after every
        recent one, and says how many wait in all, so the oldest request is shown whole
        and answered here, and the rest follow as these are answered.
        """
        subject = approvals_subject
        await hold_request(subject.plans, "approval:old-no", ago=timedelta(hours=9))
        await card_tap(
            subject.plans, "approval:old-no", ApprovalRequestState.DENIED, ago=timedelta(hours=8)
        )
        for index in range(20):
            await hold_request(
                subject.plans,
                f"approval:{index:02d}",
                why="w" * APPROVAL_WHY_MAX_CHARS,
                date=f"d{index}",
                ago=timedelta(hours=5, minutes=-index),
            )

        panel = await subject.engine.approvals()

        assert panel.pending_total == 20
        assert panel.recent == ()
        shown = [one.request_id for one in panel.pending]
        assert 1 <= len(shown) < 20
        assert shown == [f"approval:{index:02d}" for index in range(len(shown))]
        tapped = await subject.engine.tap_approval(shown[0], choice=ApprovalChoice.APPROVE)
        assert tapped.answer is ApprovalPanelTapAnswer.ANSWERED
        after = await subject.engine.approvals()
        assert after.pending_total == 19
        assert after.pending[0].request_id == "approval:01"

    async def test_the_total_counts_what_the_limit_left_out(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        subject = approvals_subject
        for index in range(3):
            await hold_request(
                subject.plans, f"approval:{index}", ago=timedelta(hours=3 - index), date=f"{index}"
            )

        panel = await subject.engine.approvals(limit=1)

        assert [one.request_id for one in panel.pending] == ["approval:0"]
        assert panel.pending_total == 3

    @pytest.mark.parametrize("limit", [-1, 2**63])
    async def test_a_limit_out_of_range_is_refused(
        self, approvals_subject: ApprovalsPanelSubject, limit: int
    ) -> None:
        with pytest.raises(ValueError, match="limit"):
            await approvals_subject.engine.approvals(limit=limit)

    async def test_a_limit_that_is_not_an_integer_is_refused(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        with pytest.raises(TypeError):
            await approvals_subject.engine.approvals(limit=True)

    # --- the tap (§4:7-§4:9) ---

    async def test_a_tap_answers_a_pending_request_as_the_hub_pages_giver(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """§4:9: marked approved, with who answered and when, and a ticket held (§5:1)."""
        subject = approvals_subject
        await hold_request(subject.plans, "approval:1")

        tapped = await subject.engine.tap_approval("approval:1", choice=ApprovalChoice.APPROVE)

        assert tapped.answer is ApprovalPanelTapAnswer.ANSWERED
        assert tapped.entry is not None
        assert tapped.entry.state is ApprovalCardState.APPROVED
        assert tapped.entry.answered_by is ApprovalGiver.USER_TAP_ON_HUB_PANEL
        assert tapped.entry.text.endswith("Approved: not used yet.")
        (held,) = await subject.plans.approval_requests(["approval:1"])
        assert held.state is ApprovalRequestState.APPROVED
        assert held.ticket is TicketState.HELD
        assert held.answer == ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=APPROVALS_AT)

    async def test_a_deny_grants_no_ticket(self, approvals_subject: ApprovalsPanelSubject) -> None:
        """§5:9."""
        subject = approvals_subject
        await hold_request(subject.plans, "approval:1")

        tapped = await subject.engine.tap_approval("approval:1", choice=ApprovalChoice.DENY)

        assert tapped.answer is ApprovalPanelTapAnswer.ANSWERED
        assert tapped.entry is not None
        assert tapped.entry.state is ApprovalCardState.DENIED
        (held,) = await subject.plans.approval_requests(["approval:1"])
        assert held.state is ApprovalRequestState.DENIED
        assert held.ticket is None

    async def test_a_request_with_no_card_is_answered_on_the_panel_alone(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """§2:7: the line not connected, or a post that failed, records no card, and the
        request is shown and answered here."""
        subject = approvals_subject
        request = await hold_request(subject.plans, "approval:1")
        assert request.cards == ()

        (entry,) = (await subject.engine.approvals()).pending
        tapped = await subject.engine.tap_approval(entry.request_id, choice=ApprovalChoice.APPROVE)

        assert tapped.answer is ApprovalPanelTapAnswer.ANSWERED
        (held,) = await subject.plans.approval_requests(["approval:1"])
        assert held.state is ApprovalRequestState.APPROVED
        assert held.cards == ()

    async def test_a_later_tap_is_answered_with_the_requests_state(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """§4:9: the first tap won; the second changes nothing."""
        subject = approvals_subject
        await hold_request(subject.plans, "approval:1")
        await subject.engine.tap_approval("approval:1", choice=ApprovalChoice.DENY)

        again = await subject.engine.tap_approval("approval:1", choice=ApprovalChoice.APPROVE)

        assert again.answer is ApprovalPanelTapAnswer.ALREADY_ANSWERED
        assert again.entry is not None
        assert again.entry.state is ApprovalCardState.DENIED
        (held,) = await subject.plans.approval_requests(["approval:1"])
        assert held.state is ApprovalRequestState.DENIED
        assert held.ticket is None

    async def test_a_tap_after_the_cards_is_answered_with_the_cards_answer(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """§4:9: the card's tap landed first, so the panel's changes nothing."""
        subject = approvals_subject
        await hold_request(subject.plans, "approval:1")
        await card_tap(
            subject.plans, "approval:1", ApprovalRequestState.APPROVED, ago=timedelta(minutes=1)
        )

        tapped = await subject.engine.tap_approval("approval:1", choice=ApprovalChoice.DENY)

        assert tapped.answer is ApprovalPanelTapAnswer.ALREADY_ANSWERED
        assert tapped.entry is not None
        assert tapped.entry.state is ApprovalCardState.APPROVED
        assert tapped.entry.answered_by is CARD
        (held,) = await subject.plans.approval_requests(["approval:1"])
        assert held.answer is not None
        assert held.answer.who is CARD

    async def test_two_taps_racing_the_panel_against_the_card_one_wins(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """§4:9: the panel's tap and the card's, in flight together; the store's one step
        lets exactly one land, and the panel says which."""
        subject = approvals_subject
        await hold_request(subject.plans, "approval:1")

        tapped, carded = await asyncio.gather(
            subject.engine.tap_approval("approval:1", choice=ApprovalChoice.APPROVE),
            subject.plans.answer_approval_request(
                "approval:1", ApprovalRequestState.DENIED, ApprovalTap(who=CARD, at=APPROVALS_AT)
            ),
        )

        (held,) = await subject.plans.approval_requests(["approval:1"])
        assert held.answer is not None
        assert tapped.entry is not None
        if tapped.answer is ApprovalPanelTapAnswer.ANSWERED:
            assert carded.answer is ApprovalStepAnswer.NOT_PENDING
            assert held.state is ApprovalRequestState.APPROVED
            assert held.answer.who is ApprovalGiver.USER_TAP_ON_HUB_PANEL
        else:
            assert tapped.answer is ApprovalPanelTapAnswer.ALREADY_ANSWERED
            assert carded.answer is ApprovalStepAnswer.CHANGED
            assert held.state is ApprovalRequestState.DENIED
            assert held.answer.who is CARD
        assert tapped.entry.state.value == held.state.value

    async def test_a_tap_past_the_expiry_changes_nothing(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """§3:5: no tap can approve a request at or after its expiry."""
        subject = approvals_subject
        await hold_request(subject.plans, "approval:1", ago=timedelta(hours=25))

        tapped = await subject.engine.tap_approval("approval:1", choice=ApprovalChoice.APPROVE)

        assert tapped.answer is ApprovalPanelTapAnswer.EXPIRED
        assert tapped.entry is not None
        assert tapped.entry.state is ApprovalCardState.EXPIRED
        (held,) = await subject.plans.approval_requests(["approval:1"])
        assert held.state is ApprovalRequestState.PENDING
        assert held.answer is None

    async def test_a_tap_on_an_expired_request_says_it_expired(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        subject = approvals_subject
        await hold_request(subject.plans, "approval:1", ago=timedelta(hours=26))
        await subject.plans.expire_approval_request("approval:1", APPROVALS_AT - timedelta(hours=1))

        tapped = await subject.engine.tap_approval("approval:1", choice=ApprovalChoice.DENY)

        assert tapped.answer is ApprovalPanelTapAnswer.EXPIRED
        assert tapped.entry is not None
        assert tapped.entry.state is ApprovalCardState.EXPIRED

    async def test_a_tap_on_no_held_request_is_unknown(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        tapped = await approvals_subject.engine.tap_approval(
            "approval:none", choice=ApprovalChoice.APPROVE
        )

        assert tapped.answer is ApprovalPanelTapAnswer.UNKNOWN
        assert tapped.entry is None

    async def test_a_tap_on_another_persons_request_changes_nothing_and_shows_nothing(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """§4:8: a tap from anyone but the request's person changes nothing."""
        subject = approvals_subject
        await hold_request(subject.plans, "approval:theirs", person="person:guest")

        tapped = await subject.engine.tap_approval("approval:theirs", choice=ApprovalChoice.APPROVE)

        assert tapped.answer is ApprovalPanelTapAnswer.UNKNOWN
        assert tapped.entry is None
        (held,) = await subject.plans.approval_requests(["approval:theirs"])
        assert held.state is ApprovalRequestState.PENDING

    async def test_the_request_id_is_normalised(
        self, approvals_subject: ApprovalsPanelSubject
    ) -> None:
        """ADR-0085 §3c: an identifier argument is stripped before it is used."""
        subject = approvals_subject
        await hold_request(subject.plans, "approval:1")

        tapped = await subject.engine.tap_approval("  approval:1 ", choice=ApprovalChoice.APPROVE)

        assert tapped.answer is ApprovalPanelTapAnswer.ANSWERED

    @pytest.mark.parametrize("request_id", ["", "   "])
    async def test_a_blank_request_id_is_refused(
        self, approvals_subject: ApprovalsPanelSubject, request_id: str
    ) -> None:
        with pytest.raises(ValueError, match="request_id"):
            await approvals_subject.engine.tap_approval(request_id, choice=ApprovalChoice.APPROVE)

    @pytest.mark.parametrize("choice", ["yes", "approved", "", None])
    async def test_a_choice_that_is_neither_approve_nor_deny_is_refused(
        self, approvals_subject: ApprovalsPanelSubject, choice: object
    ) -> None:
        subject = approvals_subject
        await hold_request(subject.plans, "approval:1")

        with pytest.raises(ValueError, match="choice"):
            await subject.engine.tap_approval("approval:1", choice=choice)  # type: ignore[arg-type]
        (held,) = await subject.plans.approval_requests(["approval:1"])
        assert held.state is ApprovalRequestState.PENDING
