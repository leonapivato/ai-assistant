"""``request_approval``'s runner: the Approvals channel's actuator (ADR-0361 §2, §3:3).

**The write** (§2:6-§2:9, §3:3). A ``request_approval`` call authorizing allowed reaches
acting as a call whose runner claims its own effect record (ADR-0350 §3:3's shape): the
request and the call's effect record, naming the request, are written in one plan-store
step (``PlanStore.write_approval_request``), which decides the stop, §2:8's duplicate
check and the backstop. Code fills in everything the request records: the person, who is
the asking activation's; the asking activation and its round; the call, as authorizing
ruled it, with the values the hub filled in and the binding computed for it, which
:class:`ApprovalAsker` carries by the decision that allowed the call (§2:3); ``why``;
when it was written; and its expiry, the composition root's 24 hours on (§3:5).

**What comes back** (§2:7-§2:8). Done once the request is written: it holds up no round
and waits for no answer, and its result says that the request waits on the person, that
the hub page's panel shows it, and how its card went on the line. The card is AP3's
(ADR-0361 §9:3): this module holds the seam (:class:`CardPoster`) and, until a poster is
wired, the result says the card was not posted, which leaves the request on the panel
alone. A request duplicating a pending one writes nothing and comes back saying it is
already waiting, and since when.

**Who asks** (:class:`ApprovalAsker`, :func:`asking`). The phases open it around acting,
as they open the Task Scheduler's spawner (ADR-0350 §3:4), so the runner reads who calls
from the activation, never from what the call carries.

**It logs stage and code-owned reason only** (ADR-0275 §8).
"""

from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol
from uuid import uuid4

import structlog
from pydantic import ValidationError

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActivationEffectClaim,
    ApprovalRequest,
    ApprovalWriteAnswer,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.acting import Unwritten
from ai_assistant.orchestration.approvals import REQUEST_APPROVAL_CAPABILITY, WHY_ARGUMENT
from ai_assistant.orchestration.person_calls import NotDone

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from datetime import datetime, timedelta

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import ActivationEffect, RequestedCall, ToolCall
    from ai_assistant.orchestration.acting import ClaimingAnswer, OwnRecordsAnswer

__all__ = [
    "ApprovalAsker",
    "ApprovalCalls",
    "ApprovalsSeams",
    "CardOutcome",
    "CardPoster",
    "asking",
    "current_asker",
]

_log = structlog.get_logger(__name__)

_ASKER: contextvars.ContextVar[ApprovalAsker | None] = contextvars.ContextVar(
    "approval_asker", default=None
)

#: Why a call reaches the runner with no asker open: acting ran it outside the phases.
_NOT_OFFERED: Final = "request_approval runs only in an activation that is a person's"
#: Why a call reaches the runner with no ruled call held for its decision.
_UNRULED: Final = "the call to approve was not ruled on, so no request was written"
#: Why a request could not be built: its ``why`` is past its bound, or its call does not fit.
_MALFORMED: Final = "the request is malformed: why is too long, or the call does not fit"
#: Why a request could not be written: the hub's records could not be written.
_STORE_FAULT: Final = "the request could not be written: the hub's records failed"


@dataclass(frozen=True, slots=True)
class ApprovalAsker:
    """What the phases know of the activation calling ``request_approval`` (§2:5-§2:6).

    Attributes:
        person: The person the activation is for, whom the request is for.
        activation_id: The asking activation.
        round_id: The round whose calls acting runs.
        requested: The call each ``request_approval`` call of the round asks about, by
            the id of the decision that allowed it, as authorizing ruled it (§2:3).
    """

    person: str
    activation_id: str
    round_id: str
    requested: Mapping[str, RequestedCall] = field(default_factory=dict)


@contextlib.contextmanager
def asking(asker: ApprovalAsker | None) -> Iterator[None]:
    """Open ``asker`` as the activation calling ``request_approval``, around acting."""
    token = _ASKER.set(asker)
    try:
        yield
    finally:
        _ASKER.reset(token)


def current_asker() -> ApprovalAsker | None:
    """The activation calling ``request_approval``, where the phases opened one."""
    return _ASKER.get()


class CardOutcome(StrEnum):
    """How a request's card went on the line (ADR-0361 §2:7, ADR-0323 §6:2-§6:5)."""

    SENT = "sent"
    NOT_DONE = "not_done"
    UNKNOWN = "unknown"
    NOT_POSTED = "not_posted"
    """No card was posted: the line is not connected, or no poster is wired (AP3)."""


class CardPoster(Protocol):
    """Posts a request's card on the line, in the same call (ADR-0361 §4:2-§4:4).

    Orchestration-local. AP3 fills it (§9:3): the line's writer posts the card into the
    line's chat as the assistant's own message, records it with its token, and says how
    it went. Until then none is wired, and every card is *not posted*.
    """

    async def post(self, request: ApprovalRequest) -> CardOutcome:
        """Post ``request``'s card, and say how it went."""
        ...


@dataclass(frozen=True, slots=True)
class ApprovalsSeams:
    """What the composition root hands the engine for the Approvals channel (ADR-0361 §3).

    Attributes:
        expiry: How long a request waits on its person before it ends expired: the
            composition root's constant, 24 hours (§3:5), never a setting.
        recheck: The sensor's recheck interval (§3:4, ADR-0350 §12:5).
        cards: The line's card poster (AP3), or ``None``, and then no card is posted.
    """

    expiry: timedelta
    recheck: timedelta
    cards: CardPoster | None = None


#: What the result says of the card, by how it went (§2:7).
_CARD_WORDS: Final = {
    CardOutcome.SENT: "sent: the card is in the person's Telegram chat",
    CardOutcome.NOT_DONE: "not done: the card could not be posted, so the panel alone shows it",
    CardOutcome.UNKNOWN: "unknown: whether the card reached the line is not known",
    CardOutcome.NOT_POSTED: "not posted: no card goes to the line, so the panel alone shows it",
}


class ApprovalCalls:
    """Acting's runner for ``request_approval`` (ADR-0361 §2:6-§2:9, §3:3).

    Structurally acting's ``OwnRecordsCalls`` and its ``ClaimingOwnRecordsCalls``: the
    call runs directly against the plan store, its request and its effect record written
    in one step, and is awaited to its end.
    """

    def __init__(
        self,
        *,
        plans: PlanStore,
        expiry: timedelta,
        now: Clock,
        wake: Callable[[], None] | None = None,
        cards: CardPoster | None = None,
    ) -> None:
        """Wire the runner.

        Args:
            plans: The plan store, which holds the Approvals channel's content.
            expiry: How long a request waits on its person: the composition root's
                constant (§3:5).
            now: The clock a request's write is stamped by.
            wake: Wakes the sensor, which a written request may need to expire.
            cards: The line's card poster (AP3), or ``None``, and then no card is posted.

        Raises:
            ValueError: If ``expiry`` is not positive.
        """
        if expiry.total_seconds() <= 0:
            msg = "a request waits on its person for a positive time (ADR-0361 §3:5)"
            raise ValueError(msg)
        self._plans = plans
        self._expiry = expiry
        self._now = now
        self._wake = wake
        self._cards = cards

    async def run(self, call: ToolCall) -> OwnRecordsAnswer:
        """``request_approval`` reaches :meth:`run_claiming` alone."""
        del call
        return NotDone(reason=_UNRULED)

    async def run_claiming(  # noqa: PLR0911 — each answer the write gives is a return of its own
        self,
        call: ToolCall,
        effect: ActivationEffect,
        *,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool,
    ) -> ClaimingAnswer:
        """Write the request and the call's effect record together (§2:6-§2:9, §3:3).

        Raises:
            ClaimStopped: If the store holds a stop record for the asking activation.
        """
        asker = current_asker()
        if asker is None or asker.activation_id != effect.activation_id:
            return Unwritten(reason=_NOT_OFFERED)
        requested = asker.requested.get(str(call.decision.id))
        why = call.request.parameters.get(WHY_ARGUMENT)
        if (
            str(call.request.tool.capability) != REQUEST_APPROVAL_CAPABILITY
            or requested is None
            or not isinstance(why, str)
            or not why.strip()
        ):
            return Unwritten(reason=_UNRULED)
        written_at = self._now()
        try:
            request = ApprovalRequest(
                id=f"approval:{uuid4().hex}",
                person=asker.person,
                activation_id=asker.activation_id,
                round=asker.round_id,
                call=requested,
                why=why.strip(),
                written_at=written_at,
                expires_at=written_at + self._expiry,
            )
        except ValidationError:
            # Its bound on ``why`` (core's APPROVAL_WHY_MAX_CHARS), or a call the store
            # could not hold: nothing is written.
            return Unwritten(reason=_MALFORMED)
        try:
            answer = await self._plans.write_approval_request(
                request,
                effect.model_copy(update={"request": request.id}),
                match=match,
                deliberate_repeat=deliberate_repeat,
            )
        except PlanningError:
            _log.warning("approval_not_written", stage="acting", reason="store_failed")
            return Unwritten(reason=_STORE_FAULT)
        if answer.answer is ApprovalWriteAnswer.ALREADY_DONE:
            return ActivationEffectClaim.ALREADY_DONE
        if answer.answer is ApprovalWriteAnswer.ALREADY_WAITING:
            waiting = answer.request
            since = "" if waiting is None else f" since {_instant(waiting.written_at)}"
            _log.info("approval_not_written", stage="acting", reason="already_waiting")
            return Unwritten(
                reason=(
                    "not asked again: the same request already waits on the person"
                    f"{since}; it is on the hub page's approvals panel"
                )
            )
        written = answer.request
        assert written is not None  # noqa: S101 — the store's write answer carries it
        if self._wake is not None:
            self._wake()
        card = await self._card(written)
        _log.info("approval_written", stage="acting", card=card.value)
        return ToolResult(
            outcome=ToolOutcome.SUCCEEDED,
            output={
                "request": "written: it waits on the person's yes or no",
                "panel": "the hub page's approvals panel shows it",
                "card": _CARD_WORDS[card],
                "expires": _instant(written.expires_at),
            },
        )

    async def _card(self, request: ApprovalRequest) -> CardOutcome:
        """How the card went: the poster's answer, or *not posted* with none wired."""
        if self._cards is None:
            return CardOutcome.NOT_POSTED
        try:
            return await self._cards.post(request)
        except Exception as exc:  # a card that fails leaves the request on the panel (§2:7)
            del exc
            _log.warning("approval_card_failed", stage="acting", reason="poster_raised")
            return CardOutcome.UNKNOWN


def _instant(at: datetime) -> str:
    """An instant as the result states it: UTC, to the minute."""
    return at.strftime("%Y-%m-%d %H:%M UTC")
