"""The line's approval cards: the post, the edits and the tap (ADR-0361 §4, §9:3, §9:4).

Over the canonical fakes: the Bot API client, the plan store, the intake record and the
memory store. The card is posted through ``request_approval``'s runner, as acting runs it,
so the result's words and the call's delivery are read where the phases read them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    TELEGRAM_MESSAGE_LIMIT,
    ActionRequest,
    ActivationEffect,
    ApprovalGiver,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalStepAnswer,
    ApprovalTap,
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    DataTier,
    DeliveryStatus,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    RequestedCall,
    Reversibility,
    RiskLevel,
    TelegramCallback,
    TelegramFailure,
    TicketState,
    ToolCall,
    ToolCost,
    ToolDefinition,
    ToolResult,
    telegram_length,
)
from ai_assistant.orchestration.approval_calls import (
    OUTSIDE_LINE,
    ApprovalAsker,
    ApprovalCalls,
    CardFacts,
    asking,
    card_text,
)
from ai_assistant.orchestration.approvals import REQUEST_APPROVAL
from ai_assistant.orchestration.telegram import (
    APPROVE_LABEL,
    CARD_TOO_LONG_LINE,
    DENY_LABEL,
    TelegramCards,
    line_channel,
)
from ai_assistant.testing import (
    FakeMemoryStore,
    FakePlanStore,
    FakeTelegramBotClient,
    FakeTelegramIntakeRecord,
)
from ai_assistant.testing.telegram import EDIT_MESSAGE_TEXT

if TYPE_CHECKING:
    from ai_assistant.core.types import FrozenJson

pytestmark = pytest.mark.anyio

AT: Final = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
DAY: Final = timedelta(hours=24)
CHAT: Final = 424242
REFERENCE: Final = "telegram-bot"
CHANNEL: Final = line_channel(REFERENCE, CHAT)

_BOOK: Final = ToolDefinition(
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


class _Clock:
    """A wall clock a case moves."""

    def __init__(self) -> None:
        self.at = AT

    def __call__(self) -> datetime:
        return self.at


class _Rig:
    """The line's cards over the fakes, and ``request_approval``'s runner posting through them."""

    def __init__(
        self, *, plans: FakePlanStore | None = None, memory: FakeMemoryStore | None = None
    ):
        self.clock = _Clock()
        self.fake = FakeTelegramBotClient(chat_id=CHAT, first_message_id=500)
        self.intake = FakeTelegramIntakeRecord()
        self.plans = plans or FakePlanStore(now=self.clock)
        self.memory = memory or FakeMemoryStore(now=self.clock)
        self.woken = 0
        self.rests: list[float] = []
        self.cards = self.over(self.fake)
        self.runner = ApprovalCalls(plans=self.plans, expiry=DAY, now=self.clock, cards=self.cards)
        self._updates = iter(range(1, 1000))
        self._asked = iter(range(1, 1000))

    def over(self, fake: FakeTelegramBotClient) -> TelegramCards:
        """Cards over ``fake`` and this rig's stores, as a fresh process would build them."""
        cards = TelegramCards(
            client=fake,
            intake=self.intake,
            channel=CHANNEL,
            send_bound=timedelta(seconds=1),
            plans=self.plans,
            memory=self.memory,
            person=OWNER_PERSON_ID,
            now=self.clock,
            sleep=self._rest,
        )
        cards.wake_with(self._wake)
        return cards

    def _wake(self) -> None:
        self.woken += 1

    async def _rest(self, seconds: float) -> None:
        self.rests.append(seconds)

    async def ask(
        self, *, date: str = "2026-11-02", read_outside: bool = False
    ) -> tuple[ToolResult, ApprovalRequest]:
        """One ``request_approval`` call, its card posted on the line."""
        n = next(self._asked)
        arguments: dict[str, FrozenJson] = {
            "call": {"capability": "book", "arguments": {"date": date}},
            "why": "You asked me to book the table.",
        }
        request = ActionRequest(tool=REQUEST_APPROVAL, parameters=arguments)
        decision = PermissionDecision.from_request(
            request,
            PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="ruled by its call"),
            id=f"decision:{n}",
            decided_at=self.clock(),
            effect=f"effect:{n}",
        )
        effect = ActivationEffect(
            id=f"effect:{n}",
            activation_id="act-ask",
            round="round:ask",
            capability="request_approval",
            values_digest="0" * 64,
            decision_id=f"decision:{n}",
            claimed_at=self.clock(),
        )
        asker = ApprovalAsker(
            person=OWNER_PERSON_ID,
            activation_id="act-ask",
            round_id="round:ask",
            requested={f"decision:{n}": RequestedCall(tool=_BOOK, values={"date": date})},
            read_outside=read_outside,
        )
        with asking(asker):
            answer = await self.runner.run_claiming(
                ToolCall(request=request, decision=decision),
                effect,
                match=None,
                deliberate_repeat=False,
            )
        assert isinstance(answer, ToolResult)
        return answer, (await self.requests())[-1]

    async def requests(self) -> tuple[ApprovalRequest, ...]:
        return await self.plans.person_approval_requests(
            OWNER_PERSON_ID, tuple(ApprovalRequestState)
        )

    async def request(self, request_id: str) -> ApprovalRequest:
        (one,) = await self.plans.approval_requests([request_id])
        return one

    def tap(self, request: ApprovalRequest, *, approve: bool = True) -> TelegramCallback:
        """The callback a tap on one of ``request``'s buttons sends, from the owner."""
        (card,) = request.cards
        assert card.token is not None
        assert card.position is not None
        verb = "y" if approve else "n"
        update = self.fake.tap(
            next(self._updates), message_id=card.position, data=f"{card.token}:{verb}"
        )
        assert update.callback is not None
        return update.callback

    async def tapped(self, callback: TelegramCallback, update_id: int = 1) -> None:
        await self.cards.tap(callback, partial(self.intake.claim_reply, update_id))

    def shown(self, request: ApprovalRequest) -> str:
        (card,) = request.cards
        texts = dict(self.fake.messages)
        assert card.position is not None
        return texts[card.position]

    def edits(self) -> int:
        return sum(1 for one in self.fake.calls if one.method == EDIT_MESSAGE_TEXT)


def _card_words(answer: ToolResult) -> str:
    assert isinstance(answer.output, Mapping)
    return str(answer.output["card"])


# --- the post (§4:2-§4:4, §2:7) ---------------------------------------------------------


async def test_a_card_is_posted_with_approve_and_deny_and_recorded_with_its_token() -> None:
    """§4:2, §4:10: one message with two buttons, the card recorded with its opaque token,
    and the call's entry holding what was sent, where and how (§4:3)."""
    rig = _Rig()

    answer, request = await rig.ask(read_outside=True)

    assert _card_words(answer).startswith("sent")
    (card,) = request.cards
    assert card.place == CHANNEL
    assert card.position == 500
    assert card.token is not None
    assert "approval" not in card.token, "the token names no record (§4:10)"
    buttons = rig.fake.buttons[500]
    assert [one.label for one in buttons] == [APPROVE_LABEL, DENY_LABEL]
    assert {one.data for one in buttons} == {f"{card.token}:y", f"{card.token}:n"}
    text = rig.shown(request)
    assert text.splitlines()[1].startswith("book")
    assert OUTSIDE_LINE in text
    assert text.endswith("Waiting for your answer.")
    delivered = rig.runner.card_delivery("decision:1")
    assert delivered is not None
    assert (delivered.words, delivered.went, delivered.status) == (
        text,
        CHANNEL,
        DeliveryStatus.SENT,
    )


async def test_a_card_too_long_for_one_message_has_no_buttons_and_points_at_the_hub_page() -> None:
    """§4:4: posted with no buttons, saying the request is answered on the hub page."""
    rig = _Rig()

    answer, request = await rig.ask(date="x" * (TELEGRAM_MESSAGE_LIMIT + 10))

    assert _card_words(answer).startswith("sent")
    (card,) = request.cards
    assert card.token is None
    assert rig.fake.buttons == {}
    text = rig.shown(request)
    assert CARD_TOO_LONG_LINE in text
    assert telegram_length(text) <= TELEGRAM_MESSAGE_LIMIT


async def test_a_card_whose_post_fails_leaves_the_request_on_the_panel() -> None:
    """§2:7, §9:4: Telegram refused it, so the result says not done, no card is recorded,
    and the request waits pending, as the panel reads it."""
    rig = _Rig()
    rig.fake.fail_next(TelegramFailure.REFUSED)

    answer, request = await rig.ask()

    assert _card_words(answer).startswith("not done")
    assert request.cards == ()
    assert request.state is ApprovalRequestState.PENDING
    (pending,) = await rig.plans.person_approval_requests(
        OWNER_PERSON_ID, (ApprovalRequestState.PENDING,)
    )
    assert pending.id == request.id
    delivered = rig.runner.card_delivery("decision:1")
    assert delivered is not None
    assert delivered.status is DeliveryStatus.FAILED


async def test_a_card_on_a_line_not_connected_is_not_posted() -> None:
    """§2:7: not posted where the line is not connected, and nothing is sent."""
    rig = _Rig()
    rig.fake.disconnect()

    answer, request = await rig.ask()

    assert _card_words(answer).startswith("not posted")
    assert request.cards == ()
    assert rig.runner.card_delivery("decision:1") is None


async def test_a_card_whose_post_may_have_gone_is_unknown_and_never_sent_again() -> None:
    """ADR-0323 §6:4: unknown, never retried; the card is recorded with no position."""
    rig = _Rig()
    rig.fake.fail_next(TelegramFailure.UNKNOWN)

    answer, request = await rig.ask()

    assert _card_words(answer).startswith("unknown")
    (card,) = request.cards
    assert card.position is None
    assert len(rig.fake.calls) == 1


async def test_a_card_rate_limited_is_sent_again_as_a_send_is() -> None:
    """ADR-0323 §6:3: Telegram said it did not send it, and a retry can succeed."""
    rig = _Rig()
    rig.fake.fail_next(TelegramFailure.RATE_LIMITED, retry_after_seconds=2)

    answer, _ = await rig.ask()

    assert _card_words(answer).startswith("sent")
    assert rig.rests == [2.0]


# --- the tap (§4:7-§4:10) -----------------------------------------------------------------


async def test_a_tap_approves_answers_edits_the_card_and_wakes_the_sensor() -> None:
    """§4:9: the request is marked by the line's tap member at the tap's instant, the
    callback answered, the card edited to its state with its buttons gone, the sensor woken."""
    rig = _Rig()
    _, request = await rig.ask()
    rig.clock.at = AT + timedelta(minutes=3)

    await rig.tapped(rig.tap(request))

    held = await rig.request(str(request.id))
    assert held.state is ApprovalRequestState.APPROVED
    assert held.answer == ApprovalTap(
        who=ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD, at=AT + timedelta(minutes=3)
    )
    assert held.ticket is TicketState.HELD
    assert rig.fake.answered == (("callback-1", "Approved."),)
    assert rig.shown(held).endswith("Approved: not used yet.")
    assert rig.fake.buttons == {}
    assert rig.woken == 1, "by the tap"


async def test_a_deny_is_marked_and_answered() -> None:
    """§4:9: a deny grants no ticket (§5:9), and the card says denied."""
    rig = _Rig()
    _, request = await rig.ask()

    await rig.tapped(rig.tap(request, approve=False))

    held = await rig.request(str(request.id))
    assert held.state is ApprovalRequestState.DENIED
    assert held.ticket is None
    assert rig.fake.answered == (("callback-1", "Denied."),)
    assert rig.shown(held).endswith("Denied.")


async def test_two_taps_racing_the_first_wins_and_the_later_is_answered_with_its_state() -> None:
    """§4:9, §9:4: Approve and Deny tapped at once; one store step lands first, and the
    other changes nothing and is answered with the request's state."""
    rig = _Rig()
    _, request = await rig.ask()
    approve, deny = rig.tap(request), rig.tap(request, approve=False)

    await asyncio.gather(rig.tapped(approve, 1), rig.tapped(deny, 2))

    held = await rig.request(str(request.id))
    answers = dict(rig.fake.answered)
    first, later = (
        ("callback-1", "callback-2")
        if held.state is ApprovalRequestState.APPROVED
        else ("callback-2", "callback-1")
    )
    assert answers[first] in {"Approved.", "Denied."}
    assert answers[later] == f"This request was already {held.state.value}."
    assert held.answer is not None


async def test_a_tap_after_the_first_is_answered_with_the_state_and_changes_nothing() -> None:
    """§4:9: the first tap won; a later one, on the other button, is answered with it."""
    rig = _Rig()
    _, request = await rig.ask()
    await rig.tapped(rig.tap(request), 1)
    answered = await rig.request(str(request.id))

    await rig.tapped(rig.tap(request, approve=False), 2)

    assert await rig.request(str(request.id)) == answered
    assert rig.fake.answered[-1] == ("callback-2", "This request was already approved.")


async def test_a_tap_after_expiry_is_answered_with_the_state_and_the_card_shows_it() -> None:
    """§3:5, §4:9: a tap at or past expiry changes nothing; it is answered so, the card
    shows the request expired, and the sensor is woken to end it."""
    rig = _Rig()
    _, request = await rig.ask()
    rig.clock.at = AT + DAY
    woken = rig.woken

    await rig.tapped(rig.tap(request))

    held = await rig.request(str(request.id))
    assert held.state is ApprovalRequestState.PENDING, "the sensor's to end"
    assert held.answer is None
    assert rig.fake.answered == (("callback-1", "This request has expired."),)
    assert rig.shown(held).endswith("Expired: it was not answered in time.")
    assert rig.fake.buttons == {}
    assert rig.woken == woken + 1


async def test_a_tap_held_already_carries_nothing_out_again() -> None:
    """§5:9: a repeated fetch of a tap the intake record holds answered changes nothing."""
    rig = _Rig()
    _, request = await rig.ask()
    callback = rig.tap(request)
    await rig.tapped(callback, 7)

    await rig.tapped(callback, 7)

    assert len(rig.fake.answered) == 1


async def test_a_tap_on_a_card_no_longer_known_changes_nothing() -> None:
    """A token no card carries finds no request; the tap is answered and nothing changes."""
    rig = _Rig()
    _, request = await rig.ask()
    update = rig.fake.tap(9, message_id=500, data="no-such-token:y")
    assert update.callback is not None

    await rig.tapped(update.callback)

    assert (await rig.request(str(request.id))).state is ApprovalRequestState.PENDING
    (answer,) = rig.fake.answered
    assert "no longer known" in answer[1]


async def test_a_tap_whose_answer_was_rate_limited_is_answered_again() -> None:
    """ADR-0323 §6:3, §13:2: each try is claimed on the intake record, as a fixed reply's."""
    rig = _Rig()
    _, request = await rig.ask()
    callback = rig.tap(request)
    rig.fake.fail_next(TelegramFailure.RATE_LIMITED, retry_after_seconds=1)

    await rig.tapped(callback)

    assert rig.fake.answered == (("callback-1", "Approved."),)


# --- the edits (§4:5) ---------------------------------------------------------------------


async def test_the_card_is_edited_on_each_state_change_and_not_when_nothing_changed() -> None:
    """§4:5: approved, and after a yes used or not used; each change edited once."""
    rig = _Rig()
    _, used = await rig.ask(date="2026-11-02")
    _, voided = await rig.ask(date="2026-11-03")
    await rig.cards.refresh()
    assert rig.edits() == 0, "nothing changed since each card was posted"
    tap = ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=AT)
    for one in (used, voided):
        step = await rig.plans.answer_approval_request(
            str(one.id), ApprovalRequestState.APPROVED, tap
        )
        assert step.answer is ApprovalStepAnswer.CHANGED

    await rig.cards.refresh()

    assert rig.shown(await rig.request(str(used.id))).endswith("Approved: not used yet.")
    await rig.plans.void_approval_ticket(str(voided.id))
    await rig.cards.refresh()
    await rig.cards.refresh()

    assert rig.shown(await rig.request(str(voided.id))).endswith("Approved, not used.")
    assert rig.edits() == 3


async def test_an_expiry_and_a_deny_on_the_panel_are_shown_on_their_cards() -> None:
    """§4:5: expired, and denied from the other surface; the buttons go with them."""
    rig = _Rig()
    _, expiring = await rig.ask(date="2026-11-02")
    _, denied = await rig.ask(date="2026-11-03")
    await rig.plans.answer_approval_request(
        str(denied.id),
        ApprovalRequestState.DENIED,
        ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=AT),
    )
    rig.clock.at = AT + DAY
    await rig.plans.expire_approval_request(str(expiring.id), AT + DAY)

    await rig.cards.refresh()

    assert rig.shown(await rig.request(str(expiring.id))).endswith(
        "Expired: it was not answered in time."
    )
    assert rig.shown(await rig.request(str(denied.id))).endswith("Denied.")
    assert rig.fake.buttons == {}


async def test_a_failed_edit_changes_nothing_in_the_store_and_a_retryable_one_is_tried_again() -> (
    None
):
    """§4:5: an edit that fails changes nothing in the store; one Telegram may retry is
    tried again at the next read, and one it refused is not sent again."""
    rig = _Rig()
    _, request = await rig.ask()
    await rig.plans.answer_approval_request(
        str(request.id),
        ApprovalRequestState.DENIED,
        ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=AT),
    )
    before = await rig.request(str(request.id))
    rig.fake.fail_next(TelegramFailure.NOT_WRITTEN)

    await rig.cards.refresh()

    assert await rig.request(str(request.id)) == before
    assert rig.shown(before).endswith("Waiting for your answer.")
    await rig.cards.refresh()
    assert rig.shown(before).endswith("Denied.")
    await rig.cards.refresh()
    assert rig.edits() == 2


async def test_after_a_start_a_card_whose_request_changed_meanwhile_is_edited() -> None:
    """§4:5: a fresh process reads the person's recent requests once; a card whose request
    changed while the hub was down is edited, its facts read from the asking episode."""
    rig = _Rig()
    _, request = await rig.ask(read_outside=False)
    await rig.plans.answer_approval_request(
        str(request.id),
        ApprovalRequestState.APPROVED,
        ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=AT),
    )
    restarted = rig.over(rig.fake)

    await restarted.refresh()

    text = rig.shown(await rig.request(str(request.id)))
    assert text.endswith("Approved: not used yet.")
    assert OUTSIDE_LINE in text, "no episode says otherwise: the cautious reading"


async def test_a_card_posted_while_a_refresh_reads_stays_watched() -> None:
    """A card posted while the refresh's read is out is not in that read, and is still
    edited when its request changes (review round 1)."""
    rig = _Rig()
    _, first = await rig.ask(date="2026-11-02")
    reading = asyncio.Event()
    release = asyncio.Event()
    read = rig.plans.approval_requests

    async def held_read(request_ids: Sequence[str], /) -> tuple[ApprovalRequest, ...]:
        found = await read(request_ids)
        reading.set()
        await release.wait()
        return found

    rig.plans.approval_requests = held_read  # type: ignore[method-assign]  # the read held open
    refreshing = asyncio.ensure_future(rig.cards.refresh())
    await reading.wait()
    _, second = await rig.ask(date="2026-11-03")
    release.set()
    await refreshing
    rig.plans.approval_requests = read  # type: ignore[method-assign]
    await rig.plans.answer_approval_request(
        str(second.id),
        ApprovalRequestState.DENIED,
        ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=AT),
    )

    await rig.cards.refresh()

    assert rig.shown(await rig.request(str(second.id))).endswith("Denied.")
    assert first.id != second.id


async def test_after_days_down_a_card_still_pending_at_the_stop_shows_it_expired() -> None:
    """A card pending when the hub stopped is watched after a start whatever its age, so
    the expiry the sensor records at its first look is shown (review round 1)."""
    rig = _Rig()
    _, request = await rig.ask()
    rig.clock.at = AT + timedelta(days=3)
    restarted = rig.over(rig.fake)

    await restarted.refresh()
    await rig.plans.expire_approval_request(str(request.id), rig.clock.at)
    await restarted.refresh()

    assert rig.shown(await rig.request(str(request.id))).endswith(
        "Expired: it was not answered in time."
    )
    assert rig.fake.buttons == {}


async def test_a_card_at_the_limit_whose_state_outgrows_it_shows_the_short_card() -> None:
    """§4:4-§4:5: a pending card of one full message that expires shows the card too long
    to post, with no buttons, rather than keeping its pending text (review round 1)."""
    rig = _Rig()
    probe = ApprovalRequest(
        id="approval:probe",
        person=OWNER_PERSON_ID,
        activation_id="act-ask",
        round="round:ask",
        call=RequestedCall(tool=_BOOK, values={"date": ""}),
        why="You asked me to book the table.",
        written_at=AT,
        expires_at=AT + DAY,
    )
    base = telegram_length(card_text(probe, CardFacts(origin=None, read_outside=False), now=AT))
    _, request = await rig.ask(date="x" * (TELEGRAM_MESSAGE_LIMIT - base))
    assert telegram_length(rig.shown(request)) == TELEGRAM_MESSAGE_LIMIT
    assert rig.fake.buttons, "posted whole, with its buttons"
    rig.clock.at = AT + DAY

    await rig.cards.refresh()

    text = rig.shown(request)
    assert CARD_TOO_LONG_LINE in text
    assert text.endswith("Expired: it was not answered in time.")
    assert rig.fake.buttons == {}


async def test_after_days_down_a_card_the_sensor_ended_first_is_still_put_right() -> None:
    """After a start every card is checked, whatever its age: one whose request the sensor
    expired before the line's first read is edited too (review round 2)."""
    rig = _Rig()
    _, request = await rig.ask()
    rig.clock.at = AT + timedelta(days=10)
    await rig.plans.expire_approval_request(str(request.id), rig.clock.at)
    restarted = rig.over(rig.fake)

    await restarted.refresh()

    assert rig.shown(await rig.request(str(request.id))).endswith(
        "Expired: it was not answered in time."
    )
    assert rig.fake.buttons == {}


async def test_a_starts_checks_of_settled_cards_are_made_a_few_at_each_read() -> None:
    """A start never holds the loop on a long run of edits: newest first, a few a read."""
    rig = _Rig()
    asked = [(await rig.ask(date=f"2026-11-{day:02d}"))[1] for day in range(1, 13)]
    for one in asked:
        await rig.plans.answer_approval_request(
            str(one.id),
            ApprovalRequestState.DENIED,
            ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=AT),
        )
    restarted = rig.over(rig.fake)

    await restarted.refresh()
    first = rig.edits()
    await restarted.refresh()

    assert first == 8
    assert rig.edits() == 12
    assert rig.shown(await rig.request(str(asked[-1].id))).endswith("Denied.")
    assert rig.shown(await rig.request(str(asked[0].id))).endswith("Denied.")


async def test_edits_failing_again_and_again_stay_within_a_reads_bound() -> None:
    """A read makes at most eight edits, retries included, so edits that keep failing
    never grow into a run that holds the reader's loop (review round 3)."""
    rig = _Rig()
    asked = [(await rig.ask(date=f"2026-11-{day:02d}"))[1] for day in range(1, 25)]
    for one in asked:
        await rig.plans.answer_approval_request(
            str(one.id),
            ApprovalRequestState.DENIED,
            ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=AT),
        )
    restarted = rig.over(rig.fake)
    for _ in range(100):
        rig.fake.fail_next(TelegramFailure.NOT_WRITTEN)

    made: list[int] = []
    for _ in range(4):
        before = rig.edits()
        await restarted.refresh()
        made.append(rig.edits() - before)

    assert made == [8, 8, 8, 8]
