"""Acting's effect records: the claim's and the finish's rules, stated once (ADR-0306 §6).

ADR-0306 §5:4 has a call or a message that gets an effect record claimed by writing
that record before it runs, "in one indivisible plan-store step that also decides the
stop and §5's backstop", and §6:2 and §6:4 state what the claim and the finish refuse.
The decisions are written here rather than in each store because two statements of
one rule are two places for it to drift. Each store's job is the indivisible step the
decision is taken inside, not the decision.

The canonical fake in :mod:`ai_assistant.testing` re-implements this rather than
importing it. That is the point of a conformance suite: the shared cases are what stop
the two drifting, and a fake that imported this module would pull in the subsystem it
stands in for.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.errors import ClaimStopped, PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ActivationEffectClaim,
    Identifier,
    QuestionPart,
    ToolOutcome,
    encodable_text,
)

if TYPE_CHECKING:
    from collections.abc import Container, Iterable

_EFFECT_ID: TypeAdapter[Identifier] = TypeAdapter(Identifier)


def checked_effect_id(effect_id: object) -> str:
    """Return ``effect_id`` as the identifier a record carries, or refuse it.

    Args:
        effect_id: What the caller passed.

    Returns:
        The validated identifier.

    Raises:
        PlanningError: If the value is not an identifier.
    """
    try:
        return _EFFECT_ID.validate_python(effect_id)
    except ValidationError as exc:
        msg = f"an activation effect is named by an identifier, and {effect_id!r} is not one"
        raise PlanningError(msg) from exc


def revalidated_claim(effect: object) -> ActivationEffect:
    """Return the store's own copy of a record about to be claimed, or refuse it.

    Rebuilt through validation, so a caller that mutates its record after the call
    cannot change what the store holds, and a record corrupted past its frozen guard
    is refused here rather than written. A claimed record carries no outcome, no
    reason and no position (ADR-0306 §5:4).

    Args:
        effect: What the caller passed.

    Returns:
        The validated, detached record.

    Raises:
        PlanningError: If the value is not a valid ``ActivationEffect``, or it
            carries an outcome, a reason or a position.
    """
    if not isinstance(effect, ActivationEffect):
        msg = f"a claim writes an ActivationEffect, and {type(effect).__name__} is not one"
        raise PlanningError(msg)
    try:
        record = ActivationEffect.model_validate(effect.model_dump())
    except ValidationError as exc:
        msg = f"the activation effect to claim does not validate: {exc}"
        raise PlanningError(msg) from exc
    if record.outcome is not None or record.reason is not None or record.position is not None:
        msg = (
            f"activation effect {record.id} is claimed before it runs, so it carries no "
            f"outcome, reason or position (ADR-0306 §5:4)"
        )
        raise PlanningError(msg)
    return record


def matched_activations(match: object) -> tuple[str, ...] | None:
    """Return ``match`` as the tuple of activation ids it names, or refuse it.

    **An id with no UTF-8 encoding is refused, not matched against nothing.** A record's
    activation is an :data:`~ai_assistant.core.types.Identifier`, so no store can hold
    one for such an id; but a SQLite store cannot even bind it, and the driver's
    ``UnicodeEncodeError`` is no ``sqlite3.Error``, so it would escape the store as
    something other than the ``PlanningError`` the Protocol raises (issue #3288). Refusing
    it here, before any store's write, is what keeps every store agreeing. The message
    names the id's place and the code point, and never echoes the id, which could not be
    written down (:func:`~ai_assistant.core.types.encodable_text`).

    Args:
        match: What the caller passed as ``match``.

    Returns:
        ``None``, or the ids.

    Raises:
        PlanningError: If ``match`` is neither ``None`` nor a tuple of strings, or names
            an id with no UTF-8 encoding.
    """
    if match is None:
        return None
    if not isinstance(match, tuple) or not all(isinstance(one, str) for one in match):
        msg = "match is None or a tuple of activation ids (ADR-0306 §6:2)"
        raise PlanningError(msg)
    for index, one in enumerate(match):
        try:
            encodable_text(one)
        except ValueError as exc:
            msg = f"match names activation ids, and the one at index {index} is not: {exc}"
            raise PlanningError(msg) from exc
    return match


def requested_activations(activation_ids: object) -> tuple[str, ...]:
    """Return the activation ids a read names, refusing a bare string or a non-sequence.

    A ``str`` is itself a sequence of strings, so a caller passing one activation id
    unwrapped would otherwise read the records of each of its characters.

    **Anything but a sequence is refused, a one-shot iterable included** (issue #3295).
    The check reads every element, so a generator would be exhausted by it and the read
    would then name nothing and answer ``()`` whatever the store holds; and a value that
    is not iterable at all would escape as ``TypeError``. ``observations`` draws the same
    line (:func:`~ai_assistant.planning.observations.requested_episodes`), and every
    caller passes a list or a tuple.

    **An id with no UTF-8 encoding is refused, not answered with nothing.** A record's
    activation is an :data:`~ai_assistant.core.types.Identifier`, so no store can hold
    one for such an id; but a SQLite store cannot even bind it, and the driver's
    ``UnicodeEncodeError`` is no ``sqlite3.Error``, so it would escape the store as
    something other than the ``PlanningError`` the Protocol raises (issue #3291). Refusing
    it here, before any store's I/O, is what keeps every store agreeing. The message names
    the id's place and the code point, and never echoes the id, which could not be
    written down (:func:`~ai_assistant.core.types.encodable_text`).

    Args:
        activation_ids: What the caller passed.

    Returns:
        The ids, each once, in the order given.

    Raises:
        PlanningError: If ``activation_ids`` is a bare string, or not a sequence of
            strings, or names an id with no UTF-8 encoding.
    """
    if (
        not isinstance(activation_ids, Sequence)
        or isinstance(activation_ids, (str, bytes))
        or not all(isinstance(one, str) for one in activation_ids)
    ):
        msg = (
            "activation_effects reads a sequence of activation ids, not one string or anything else"
        )
        raise PlanningError(msg)
    for index, one in enumerate(activation_ids):
        try:
            encodable_text(one)
        except ValueError as exc:
            msg = (
                f"activation_effects reads activation ids, and the one at index {index} "
                f"is not: {exc}"
            )
            raise PlanningError(msg) from exc
    return tuple(dict.fromkeys(activation_ids))


def requested_parts(parts: object) -> tuple[QuestionPart, ...]:
    """Return the question parts a read names, each once and detached, or refuse them.

    Args:
        parts: What the caller passed.

    Returns:
        The parts, each once, in the order given.

    Raises:
        PlanningError: If ``parts`` is a string, or not a sequence of ``QuestionPart``
            values.
    """
    if (
        not isinstance(parts, Sequence)
        or isinstance(parts, (str, bytes))
        or not all(isinstance(one, QuestionPart) for one in parts)
    ):
        msg = "part_effects reads a sequence of QuestionPart values (ADR-0321 §4:9)"
        raise PlanningError(msg)
    try:
        detached = [QuestionPart.model_validate(one.model_dump()) for one in parts]
    except ValidationError as exc:
        msg = f"a question part to read does not validate: {exc}"
        raise PlanningError(msg) from exc
    return tuple(dict.fromkeys(detached))


def _counts_against(held: ActivationEffect, effect: ActivationEffect, *, deliberate: bool) -> bool:
    """Whether one held record refuses ``effect`` as already done (ADR-0306 §5:9, §5:11).

    Only a call matches a call, on its capability and its values digest. An unknown
    outcome counts as done, and so does an outcome not yet written; an effect not done
    does not count. A deliberate repeat passes a matching effect where it is done, and a
    deliberate repeat that runs under an approval, carrying a part key, passes one whose
    outcome is unknown or not yet written too (ADR-0321 §6:2).
    """
    if not (held.is_call and effect.is_call):
        return False
    if (held.capability, held.values_digest) != (effect.capability, effect.values_digest):
        return False
    if held.outcome is ToolOutcome.FAILED:
        return False
    if held.outcome is ToolOutcome.SUCCEEDED:
        return not deliberate
    return not (deliberate and effect.under_approval)


def decide_activation_claim(  # noqa: PLR0913 — the claim's three inputs and the four facts the store reads inside its step
    effect: ActivationEffect,
    *,
    match: tuple[str, ...] | None,
    deliberate_repeat: bool,
    stopped: bool,
    held_ids: Container[str],
    matched: Iterable[ActivationEffect],
    spent: bool,
) -> ActivationEffectClaim:
    """Decide one claim, inside the store's indivisible step (ADR-0306 §6:2).

    Args:
        effect: The revalidated record to claim.
        match: The activations it is matched against, or ``None``.
        deliberate_repeat: Whether planning marked the call a deliberate repeat.
        stopped: Whether the store holds a stop record for the record's activation.
        held_ids: The record ids the store holds.
        matched: The held records of the activations ``match`` names; read only where
            ``match`` is a tuple.
        spent: Whether a held record of any activation carries ``effect.part``; read
            only where the record carries one (ADR-0321 §4:9).

    Returns:
        ``CLAIMED`` where the store should write the record; ``ALREADY_USED`` or
        ``ALREADY_DONE`` where it should write nothing.

    Raises:
        ClaimStopped: If the activation was stopped.
        PlanningError: If the store already holds a record under the id.
    """
    if stopped:
        msg = (
            f"activation {effect.activation_id} was stopped, so its claim of effect "
            f"{effect.id} is refused (ADR-0306 §5:2)"
        )
        raise ClaimStopped(msg)
    if effect.id in held_ids:
        msg = f"the plan store already holds activation effect {effect.id} (ADR-0306 §6:2)"
        raise PlanningError(msg)
    if effect.part is not None and spent:
        return ActivationEffectClaim.ALREADY_USED
    if match is not None and any(
        _counts_against(held, effect, deliberate=deliberate_repeat) for held in matched
    ):
        return ActivationEffectClaim.ALREADY_DONE
    return ActivationEffectClaim.CLAIMED


def finished(
    held: ActivationEffect | None,
    effect_id: str,
    outcome: object,
    *,
    reason: object,
    position: object,
) -> ActivationEffect:
    """Return the record ``finish_activation_effect`` writes, or refuse (ADR-0306 §6:4).

    Args:
        held: The record the store holds under ``effect_id``, or ``None``.
        effect_id: The id the caller named.
        outcome: The outcome to write.
        reason: Why the effect was not done, or ``None``.
        position: Where the medium recorded a message, or ``None``.

    Returns:
        The finished record.

    Raises:
        PlanningError: If no record is held, it is already finished, the outcome is
            not a ``ToolOutcome``, the reason is blank or has no UTF-8 encoding, a
            reason rides on an outcome other than not done, or a position on anything
            but a message done.
    """
    if held is None:
        msg = f"the plan store holds no activation effect {effect_id!r} to finish"
        raise PlanningError(msg)
    if held.outcome is not None:
        msg = f"activation effect {held.id} is already finished; its outcome is written once"
        raise PlanningError(msg)
    if not isinstance(outcome, ToolOutcome):
        msg = f"an activation effect finishes with a ToolOutcome, not {outcome!r}"
        raise PlanningError(msg)
    if reason is not None and outcome is not ToolOutcome.FAILED:
        msg = f"only an effect not done carries a reason; {held.id} finished {outcome.value}"
        raise PlanningError(msg)
    if position is not None and (held.is_call or outcome is not ToolOutcome.SUCCEEDED):
        msg = f"only a message done carries a position; {held.id} cannot carry one"
        raise PlanningError(msg)
    try:
        return ActivationEffect.model_validate(
            {**held.model_dump(), "outcome": outcome, "reason": reason, "position": position}
        )
    except ValidationError as exc:
        msg = f"the finished activation effect {held.id} does not validate: {exc}"
        raise PlanningError(msg) from exc


#: The reason a message's record is written not done when its place confirmed it absent.
CONFIRMED_ABSENT: Final = "its place's medium has no record of it (ADR-0350 §8:11)"


def confirmed(
    held: ActivationEffect | None, effect_id: str, *, delivered: object, position: object
) -> ActivationEffect:
    """Return the record a place's confirmation settles, or refuse (ADR-0350 §8:11).

    A message's record whose outcome is unknown or not yet written is settled once from
    its place's confirmation: done, with the position its medium recorded it at, or not
    done. Every other change to an outcome already written is refused, as a finish
    refuses it (ADR-0306 §6:4).

    Args:
        held: The record the store holds under ``effect_id``, or ``None``.
        effect_id: The id the caller named.
        delivered: Whether the medium recorded the message.
        position: Where it recorded it, or ``None``.

    Returns:
        The settled record.

    Raises:
        PlanningError: If no record is held, it is a call, its outcome is done or not
            done, ``delivered`` is not a ``bool``, or the position does not match it.
    """
    if held is None:
        msg = f"the plan store holds no activation effect {effect_id!r} to confirm"
        raise PlanningError(msg)
    if held.is_call:
        msg = f"activation effect {held.id} is a call; only a message's delivery is confirmed"
        raise PlanningError(msg)
    if held.outcome in {ToolOutcome.SUCCEEDED, ToolOutcome.FAILED}:
        msg = f"activation effect {held.id} is already settled; its outcome is settled once"
        raise PlanningError(msg)
    if not isinstance(delivered, bool):
        msg = f"a confirmation says whether the message was recorded, not {delivered!r}"
        raise PlanningError(msg)
    if delivered != (position is not None):
        msg = "a message confirmed recorded carries its position, and one confirmed absent none"
        raise PlanningError(msg)
    try:
        return ActivationEffect.model_validate(
            {
                **held.model_dump(),
                "outcome": ToolOutcome.SUCCEEDED if delivered else ToolOutcome.FAILED,
                "reason": None if delivered else CONFIRMED_ABSENT,
                "position": position,
            }
        )
    except ValidationError as exc:
        msg = f"the confirmed activation effect {held.id} does not validate: {exc}"
        raise PlanningError(msg) from exc
