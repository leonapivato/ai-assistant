"""The Approvals channel's requests: every step's rules, stated once (ADR-0361 §8:2).

ADR-0361 §3:1 has the plan store hold the approval requests ``request_approval`` writes,
each with its ticket (§5). Every step on them — the write with its effect claim and the
duplicate check (§2:8-§2:9), a card recorded (§4:3), a tap (§4:9), an expiry (§3:5), a
ticket made void (§5:7), an outcome marked pushed (§3:4) and a call claimed under a
ticket (§5:5) — is decided here over the whole book of requests, read inside the store's
one indivisible step. Each store's job is that step, not the decision.

**The store computes no instant** (ADR-0361 §3:5): a request's expiry is the composition
root's constant, which ``request_approval`` adds to the instant it writes; a tap and an
expiry carry the instants their callers read; and a claim is decided at the instant its
effect record was claimed at.

The canonical fake in :mod:`ai_assistant.testing` carries its own copy of these rules
rather than importing this module, and the shared ``PlanStore`` conformance suite, run
over all three stores, holds them to one book and one set of refusals.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ApprovalCard,
    ApprovalDue,
    ApprovalOutcomePush,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalRequestStep,
    ApprovalRequestWrite,
    ApprovalStepAnswer,
    ApprovalTap,
    ApprovalWriteAnswer,
    Identifier,
    NonBlankEncodableText,
    ScheduledTaskWrite,
    TaskWriteAnswer,
    TicketClaim,
    TicketState,
    UtcInstant,
    encodable_text,
)

if TYPE_CHECKING:
    from datetime import datetime

_ID: Final[TypeAdapter[str]] = TypeAdapter(Identifier)
_TEXT: Final[TypeAdapter[str]] = TypeAdapter(NonBlankEncodableText)
_INSTANT: Final[TypeAdapter[datetime]] = TypeAdapter(UtcInstant)

#: The answers a tap may give a request (ADR-0361 §4:9).
_TAP_STATES: Final = frozenset({ApprovalRequestState.APPROVED, ApprovalRequestState.DENIED})


@dataclass(slots=True)
class Book:
    """The approval requests as one store step reads them, and what it changed.

    Attributes:
        requests: Every request the store holds, by id, in the order written. A step
            replaces an entry rather than mutating the frozen record.
        changed: The ids of the requests the step wrote, new or rewritten, in order.
    """

    requests: dict[str, ApprovalRequest]
    changed: list[str] = field(default_factory=list)

    def put(self, request: ApprovalRequest) -> None:
        """Hold ``request`` under its id, new or replacing the record held, and note it."""
        self.requests[request.id] = request
        if request.id not in self.changed:
            self.changed.append(request.id)

    def held(self, request_id: str) -> ApprovalRequest:
        """The request held under ``request_id``.

        Raises:
            PlanningError: If the store holds none.
        """
        found = self.requests.get(request_id)
        if found is None:
            msg = f"the plan store holds no approval request {request_id!r}"
            raise PlanningError(msg)
        return found


def _replaced(request: ApprovalRequest, **changes: object) -> ApprovalRequest:
    """``request`` with ``changes``, revalidated as a whole record."""
    try:
        return ApprovalRequest.model_validate({**request.model_dump(), **changes})
    except ValidationError as exc:
        msg = f"the approval request {request.id} would not validate after the step: {exc}"
        raise PlanningError(msg) from exc


# --- what a caller hands in ------------------------------------------------------------


def checked_request_id(value: object, what: str = "approval request") -> str:
    """Return ``value`` as the identifier it names, or refuse it.

    Raises:
        PlanningError: If the value is not an identifier.
    """
    try:
        return _ID.validate_python(value, strict=True)
    except ValidationError as exc:
        msg = f"an {what} is named by an identifier, and {value!r} is not one"
        raise PlanningError(msg) from exc


def checked_token(value: object) -> str:
    """Return ``value`` as a card's token, or refuse it (ADR-0361 §4:10).

    Raises:
        PlanningError: If it is blank or has no UTF-8 encoding.
    """
    try:
        return _TEXT.validate_python(value, strict=True)
    except ValidationError as exc:
        msg = f"a card's token is non-blank text, not {value!r}"
        raise PlanningError(msg) from exc


def checked_person(value: object) -> str:
    """Return ``value`` as the person a request is for, or refuse it.

    Raises:
        PlanningError: If it is blank or has no UTF-8 encoding.
    """
    try:
        return _TEXT.validate_python(value, strict=True)
    except ValidationError as exc:
        msg = f"an approval request is for a person, named by non-blank text, not {value!r}"
        raise PlanningError(msg) from exc


def checked_at(value: object) -> datetime:
    """Return ``value`` as a timezone-aware instant, or refuse it.

    Raises:
        PlanningError: If it is not a timezone-aware ``datetime``.
    """
    try:
        return _INSTANT.validate_python(value, strict=True)
    except ValidationError as exc:
        msg = f"the Approvals channel compares timezone-aware instants, not {value!r}"
        raise PlanningError(msg) from exc


def requested_request_ids(ids: object) -> tuple[str, ...]:
    """Return the request ids a read names, each once in the order given, or refuse them.

    A bare string, anything but a sequence, and an id with no UTF-8 encoding, which a
    SQLite store could not bind, are refused, as every other read by ids refuses them.

    Raises:
        PlanningError: If they are not a sequence of encodable strings.
    """
    if (
        not isinstance(ids, Sequence)
        or isinstance(ids, (str, bytes))
        or not all(isinstance(one, str) for one in ids)
    ):
        msg = "a read of approval requests names a sequence of request ids"
        raise PlanningError(msg)
    for index, one in enumerate(ids):
        try:
            encodable_text(one)
        except ValueError as exc:
            msg = f"a read of approval requests names ids, and the one at {index} is not: {exc}"
            raise PlanningError(msg) from exc
    return tuple(dict.fromkeys(ids))


def requested_request_states(states: object) -> frozenset[ApprovalRequestState]:
    """Return the states a read names, or refuse them.

    Raises:
        PlanningError: If ``states`` is a string or not a sequence of states.
    """
    if (
        not isinstance(states, Sequence)
        or isinstance(states, (str, bytes))
        or not all(isinstance(one, ApprovalRequestState) for one in states)
    ):
        msg = "a read of approval requests by state names a sequence of ApprovalRequestState"
        raise PlanningError(msg)
    return frozenset(states)


def checked_new_request(request: object) -> ApprovalRequest:
    """Return the store's own copy of a request to write, or refuse it (§2:6).

    Rebuilt through validation, so a caller that mutates its value after the call cannot
    change what the store writes. A request is written pending, with no answer, ticket,
    card or pushed mark: each of those is a later step's.

    Raises:
        PlanningError: If it is not a valid ``ApprovalRequest``, or is not a fresh one.
    """
    if not isinstance(request, ApprovalRequest):
        msg = (
            f"an approval request is written from an ApprovalRequest, not {type(request).__name__}"
        )
        raise PlanningError(msg)
    try:
        copy = ApprovalRequest.model_validate(request.model_dump())
    except ValidationError as exc:
        msg = f"the approval request to write does not validate: {exc}"
        raise PlanningError(msg) from exc
    if copy.state is not ApprovalRequestState.PENDING or copy.cards or copy.pushed_to:
        msg = (
            f"approval request {copy.id} is written pending, with no card and no pushed mark; "
            f"each is a later step's (ADR-0361 §2:7, §3:4, §4:3)"
        )
        raise PlanningError(msg)
    return copy


def checked_request_effect(effect: ActivationEffect, request: ApprovalRequest) -> ActivationEffect:
    """Refuse ``request_approval``'s effect record unless it names its request (§2:9).

    ``effect`` is already revalidated as a claim. It is a call, made by the asking
    activation in the asking round, naming the request it writes.

    Raises:
        PlanningError: If it is a message's, names another request or none, or another
            activation or round than the request's.
    """
    if not effect.is_call:
        msg = f"request_approval's effect record is a call's, and {effect.id} is a message's"
        raise PlanningError(msg)
    if effect.request != request.id:
        msg = f"request_approval's effect record {effect.id} names the request it writes"
        raise PlanningError(msg)
    if (effect.activation_id, effect.round) != (request.activation_id, request.round):
        msg = (
            f"request_approval's effect record {effect.id} is the asking activation's, made "
            f"in the round that wrote the request"
        )
        raise PlanningError(msg)
    return effect


def checked_ticket_effect(effect: ActivationEffect) -> ActivationEffect:
    """Refuse a call's record claimed under a ticket unless it carries the ticket (§5:5).

    ``effect`` is already revalidated as a claim.

    Raises:
        PlanningError: If it is a message's, or names no ticket.
    """
    if not effect.is_call or effect.ticket is None:
        msg = f"a call claimed under a ticket names its request, and {effect.id} does not"
        raise PlanningError(msg)
    return effect


def checked_plain_effect(effect: ActivationEffect) -> ActivationEffect:
    """Refuse a record for an ordinary claim that carries a ticket or a request.

    A call under a ticket is claimed by ``claim_ticket_call``, which spends the ticket in
    the same step (§5:5), and ``request_approval``'s record is written with its request
    (§2:9); neither is claimed alone, or the key would be carried with no step behind it.

    Raises:
        PlanningError: If it carries a ticket or a request.
    """
    if effect.ticket is not None or effect.request is not None:
        msg = (
            f"activation effect {effect.id} carries a ticket or a request, and is claimed "
            f"with its ticket or written with its request (ADR-0361 §2:9, §5:5)"
        )
        raise PlanningError(msg)
    return effect


def checked_spawn_key(effect: ActivationEffect) -> ActivationEffect:
    """Refuse a spawn's record carrying a request; one carrying a ticket passes (§5:5).

    A spawn is the one call whose runner claims its own record that a ticket can hold,
    so its write takes a record carrying a ticket and decides and spends the ticket in
    its own step, as ``claim_ticket_call`` does (ADR-0362 §3:1, §3:3).
    ``request_approval``'s record is written with its request (§2:9), never with a task.

    Raises:
        PlanningError: If it carries a request.
    """
    if effect.request is not None:
        msg = (
            f"activation effect {effect.id} carries a request, and is written with its "
            f"request, not with a task (ADR-0361 §2:9)"
        )
        raise PlanningError(msg)
    return effect


def checked_card(card: object) -> ApprovalCard:
    """Return the store's own copy of a card, or refuse it (§4:3).

    Raises:
        PlanningError: If it is not a valid ``ApprovalCard``.
    """
    if not isinstance(card, ApprovalCard):
        msg = f"a card is recorded as an ApprovalCard, not {type(card).__name__}"
        raise PlanningError(msg)
    try:
        return ApprovalCard.model_validate(card.model_dump())
    except ValidationError as exc:
        msg = f"the card to record does not validate: {exc}"
        raise PlanningError(msg) from exc


def checked_tap(state: object, tap: object) -> tuple[ApprovalRequestState, ApprovalTap]:
    """Return a tap's answer and the tap, or refuse them (§4:9).

    Raises:
        PlanningError: If the answer is neither approved nor denied, or the tap is not
            a valid ``ApprovalTap``.
    """
    if not isinstance(state, ApprovalRequestState) or state not in _TAP_STATES:
        msg = f"a tap approves or denies a request, not {state!r}"
        raise PlanningError(msg)
    if not isinstance(tap, ApprovalTap):
        msg = f"a tap is recorded as an ApprovalTap, not {type(tap).__name__}"
        raise PlanningError(msg)
    try:
        return state, ApprovalTap.model_validate(tap.model_dump())
    except ValidationError as exc:
        msg = f"the tap does not validate: {exc}"
        raise PlanningError(msg) from exc


# --- the steps -------------------------------------------------------------------------


def decide_request_write(book: Book, request: ApprovalRequest) -> ApprovalRequestWrite | None:
    """Decide a request's write up to its effect's backstop (ADR-0361 §2:8).

    The stop and the held effect id are decided before this, as a claim decides them.
    Here: a request id the store holds is refused; and a pending request for the same
    person holding the same call — its capability, values and binding — that has not
    expired by the instant this one is written answers ``already_waiting`` with that
    request, writing nothing. ``None`` lets the step go on to the backstop.

    Raises:
        PlanningError: If the store already holds a request under the id.
    """
    if request.id in book.requests:
        msg = f"the plan store already holds approval request {request.id}"
        raise PlanningError(msg)
    waiting = next(
        (
            one
            for one in book.requests.values()
            if one.state is ApprovalRequestState.PENDING
            and one.person == request.person
            and one.expires_at > request.written_at
            and one.call.same_call(request.call)
        ),
        None,
    )
    if waiting is None:
        return None
    return ApprovalRequestWrite(answer=ApprovalWriteAnswer.ALREADY_WAITING, request=waiting)


def write_request(book: Book, request: ApprovalRequest) -> ApprovalRequestWrite:
    """Hold a request whose write passed every check, and answer ``written``."""
    book.put(request)
    return ApprovalRequestWrite(answer=ApprovalWriteAnswer.WRITTEN, request=request)


def decide_card(book: Book, request_id: str, card: ApprovalCard) -> ApprovalRequest:
    """Record one of a request's cards, in whatever state the request stands (§4:3).

    A card is recorded once the line's writer posted it, which a tap on the panel may
    already have answered, so the request's state refuses nothing here.

    Raises:
        PlanningError: If no such request is held, or the card's token is carried by a
            card of any request already (§4:10).
    """
    held = book.held(request_id)
    if card.token is not None and by_token(book.requests, card.token) is not None:
        msg = f"a card token is minted once, and approval request {request_id}'s is not new"
        raise PlanningError(msg)
    written = _replaced(held, cards=(*held.cards, card))
    book.put(written)
    return written


def decide_answer(
    book: Book, request_id: str, state: ApprovalRequestState, tap: ApprovalTap
) -> ApprovalRequestStep:
    """Answer a pending request by a tap, the first to land winning (ADR-0361 §4:9).

    A request no longer pending answers ``not_pending``, and one whose expiry has come by
    the tap's instant ``past_expiry``; each writes nothing. Otherwise it ends approved,
    with its ticket held (§5:1), or denied, with none (§5:9).

    Raises:
        PlanningError: If no such request is held, or the tap is earlier than its write.
    """
    held = book.held(request_id)
    if held.state is not ApprovalRequestState.PENDING:
        return ApprovalRequestStep(answer=ApprovalStepAnswer.NOT_PENDING, request=held)
    if tap.at >= held.expires_at:
        return ApprovalRequestStep(answer=ApprovalStepAnswer.PAST_EXPIRY, request=held)
    if tap.at < held.written_at:
        msg = f"a tap on approval request {request_id} comes after its write"
        raise PlanningError(msg)
    approved = state is ApprovalRequestState.APPROVED
    written = _replaced(
        held, state=state, answer=tap, ticket=TicketState.HELD if approved else None
    )
    book.put(written)
    return ApprovalRequestStep(answer=ApprovalStepAnswer.CHANGED, request=written)


def decide_expiry(book: Book, request_id: str, at: datetime) -> ApprovalRequestStep:
    """Expire a request at its expiry (ADR-0361 §3:5, §5:7).

    A pending request ends expired; an approved one whose ticket is still held has its
    ticket made void, since a ticket expires with its request. Any other answers
    ``not_pending`` and writes nothing.

    Raises:
        PlanningError: If no such request is held, or ``at`` is earlier than its expiry.
    """
    held = book.held(request_id)
    if at < held.expires_at:
        msg = f"approval request {request_id} expires at {held.expires_at.isoformat()}, not before"
        raise PlanningError(msg)
    if held.state is ApprovalRequestState.PENDING:
        written = _replaced(held, state=ApprovalRequestState.EXPIRED)
    elif held.ticket is TicketState.HELD:
        written = _replaced(held, ticket=TicketState.VOID)
    else:
        return ApprovalRequestStep(answer=ApprovalStepAnswer.NOT_PENDING, request=held)
    book.put(written)
    return ApprovalRequestStep(answer=ApprovalStepAnswer.CHANGED, request=written)


def decide_void(book: Book, request_id: str) -> ApprovalRequestStep:
    """Make a held ticket void, as the work holding its input ends unused (§5:7).

    Raises:
        PlanningError: If no such request is held.
    """
    held = book.held(request_id)
    if held.ticket is not TicketState.HELD:
        return ApprovalRequestStep(answer=ApprovalStepAnswer.NO_HELD_TICKET, request=held)
    written = _replaced(held, ticket=TicketState.VOID)
    book.put(written)
    return ApprovalRequestStep(answer=ApprovalStepAnswer.CHANGED, request=written)


def decide_outcome_push(book: Book, request_id: str, activation_id: str) -> ApprovalOutcomePush:
    """Mark a request's outcome pushed, naming its activation, before admission (§3:4).

    A request still pending, or whose outcome is already marked pushed, answers
    ``not_due`` and writes nothing.

    Raises:
        PlanningError: If no such request is held, or another request's outcome was
            already pushed to ``activation_id``.
    """
    held = book.held(request_id)
    if not held.outcome_due:
        return ApprovalOutcomePush.NOT_DUE
    if any(one.pushed_to == activation_id for one in book.requests.values()):
        msg = f"an approval's outcome was already pushed to activation {activation_id}"
        raise PlanningError(msg)
    book.put(_replaced(held, pushed_to=activation_id))
    return ApprovalOutcomePush.PUSHED


def decide_ticket(book: Book, effect: ActivationEffect, *, carried: bool) -> TicketClaim | None:
    """Decide a claim under a ticket up to its effect's backstop (ADR-0361 §5:3, §5:5).

    The stop and the held effect id are decided before this, as a claim decides them.
    Here, in order: a request not held, or never approved, answers ``not_granted``; a
    ticket used, or a key already carried by a record (``carried``), ``used``; a ticket
    void, ``void``; and a claim at or after the request's expiry, ``expired``. ``None``
    lets the step go on to the backstop.

    Raises:
        PlanningError: If the effect's capability is not the one the ticket's call holds.
    """
    held = book.requests.get(str(effect.ticket))
    if held is None or held.ticket is None:
        return TicketClaim.NOT_GRANTED
    if held.ticket is TicketState.USED or carried:
        return TicketClaim.USED
    if held.ticket is TicketState.VOID:
        return TicketClaim.VOID
    if effect.claimed_at >= held.expires_at:
        return TicketClaim.EXPIRED
    if effect.capability != held.call.tool.capability:
        msg = (
            f"a call claimed under request {held.id}'s ticket is the call it holds, "
            f"{held.call.tool.capability}, and {effect.id} is not (ADR-0361 §5:4)"
        )
        raise PlanningError(msg)
    return None


def spend_ticket(book: Book, effect: ActivationEffect) -> None:
    """Mark a ticket used by the effect record its claim writes, in the claim's step."""
    held = book.held(str(effect.ticket))
    book.put(_replaced(held, ticket=TicketState.USED, spent_by=effect.id))


def ticket_refused_write(refused: TicketClaim) -> ScheduledTaskWrite:
    """What a spawn's write answers where the ticket it ran under refused it (ADR-0362 §3:1).

    The backstop's ``already_done`` is the spawn's own answer, as on any spawn; every
    other refusal is ``ticket_refused``, naming it. Each wrote nothing.
    """
    if refused is TicketClaim.ALREADY_DONE:
        return ScheduledTaskWrite(answer=TaskWriteAnswer.ALREADY_DONE)
    return ScheduledTaskWrite(answer=TaskWriteAnswer.TICKET_REFUSED, ticket=refused)


# --- the reads -------------------------------------------------------------------------


def by_person(
    requests: dict[str, ApprovalRequest], person: str, states: frozenset[ApprovalRequestState]
) -> tuple[ApprovalRequest, ...]:
    """A person's requests in any of ``states``, in the order written (§4:6)."""
    return tuple(one for one in requests.values() if one.person == person and one.state in states)


def by_token(requests: dict[str, ApprovalRequest], token: str) -> ApprovalRequest | None:
    """The request one of whose cards carries ``token``, or ``None`` (§4:10)."""
    return next(
        (one for one in requests.values() if any(card.token == token for card in one.cards)),
        None,
    )


def due(requests: dict[str, ApprovalRequest], at: datetime) -> ApprovalDue:
    """What the sensor reads at ``at``: outcomes to push, what expires, the next expiry.

    Instants are compared in UTC, never as elapsed time.
    """
    live = [
        one
        for one in requests.values()
        if one.state is ApprovalRequestState.PENDING or one.ticket is TicketState.HELD
    ]
    later = [one.expires_at for one in live if one.expires_at > at]
    return ApprovalDue(
        outcomes=tuple(one for one in requests.values() if one.outcome_due),
        expiring=tuple(one for one in live if one.expires_at <= at),
        next_expiry_at=min(later, default=None),
    )


def pushed(requests: dict[str, ApprovalRequest]) -> tuple[ApprovalRequest, ...]:
    """Every request whose outcome is marked pushed, in the order written (§3:7)."""
    return tuple(one for one in requests.values() if one.pushed_to is not None)
