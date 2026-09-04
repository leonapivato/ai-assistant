"""The two ``core`` additions the establishing act needs (ADR-0235 §4).

:meth:`~ai_assistant.core.types.PermissionDecision.from_confirmation` — the
transcribing constructor that authors the *answer* a recorded ``CONFIRM`` no park
holds gets — and :class:`~ai_assistant.core.types.RecipientGrantOutcome`, the
carrier that says what became of a standing request collected beside one.

**Both are pure**: nothing here touches a store, a clock or a seam, which is why
they are pinned in ``tests/core`` rather than beside the operations that use them.
"""

from __future__ import annotations

import inspect
from datetime import timedelta

import pytest
from pydantic import ValidationError
from test_recipient_grant import AT, EXPIRES, _binding, _confirmation

from ai_assistant.core.types import (
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    RecipientGrant,
    RecipientGrantNotEstablished,
    RecipientGrantOutcome,
)

#: The one recipient every case here is arranged over.
ALICE = "alice@example.com"

_ALLOW = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="the user approved it")


def _answer(confirmed: PermissionDecision, **overrides: object) -> PermissionDecision:
    """The resolving decision ``from_confirmation`` builds for ``confirmed``."""
    fields: dict[str, object] = {"id": "d-answer", "decided_at": AT + timedelta(minutes=1)}
    fields.update(overrides)
    return PermissionDecision.from_confirmation(confirmed, _ALLOW, **fields)  # type: ignore[arg-type]


# --- §4: the transcribing constructor ---------------------------------------


def test_it_transcribes_the_subject_and_answers_the_question() -> None:
    """Everything describing *what was ruled on* is copied by ``core``.

    The clause this pins is ADR-0235 §4's whole reason for a constructor rather
    than a hand-built record: a caller has no parameter through which to substitute
    a subject, so the answer necessarily rules on the question it names.
    """
    confirmed = _confirmation(_binding(ALICE))

    answer = _answer(confirmed)

    assert answer.tool == confirmed.tool
    assert answer.parameters_digest == confirmed.parameters_digest
    assert answer.egress_binding == confirmed.egress_binding
    assert answer.step_id == confirmed.step_id
    assert answer.execution_id == confirmed.execution_id
    assert answer.resolves == confirmed.id
    assert answer.ruling == _ALLOW
    assert answer.expires_at is None


def test_it_accepts_no_parameter_naming_a_subject() -> None:
    """ADR-0235 §12, asserted by introspection as ``established_from``'s own test is.

    §4 removes the capability rather than forbidding it (ADR-0021 §3's move): a
    parameter for ``tool``, ``parameters_digest``, ``egress_binding``, ``step_id``,
    ``execution_id`` or ``resolves`` is a parameter through which a caller could
    point the answer at a different question, and the signature is where that is
    checked because a docstring is not.
    """
    accepted = set(inspect.signature(PermissionDecision.from_confirmation).parameters)

    assert accepted == {"confirmed", "ruling", "id", "decided_at"}


def test_the_transcribed_models_are_copied_rather_than_shared() -> None:
    """ "By value" is true rather than nominal (:meth:`from_request`'s own reason).

    Pydantic passes an already-valid model instance through without copying it, so
    without the deep copy the answer would hold the *same* ``ToolDefinition`` and
    the same binding the confirmation does — and a write past either frozen model
    would rewrite what the answer is recorded as having ruled on.
    """
    confirmed = _confirmation(_binding(ALICE))

    answer = _answer(confirmed)

    assert answer.tool is not confirmed.tool
    assert answer.egress_binding is not confirmed.egress_binding
    assert answer.ruling is not _ALLOW


def test_a_confirmation_that_is_not_a_confirm_is_refused() -> None:
    """An answer to a decision nobody was shown authorises nothing (ADR-0235 §4)."""
    confirmed = _confirmation(_binding(ALICE))
    allowed = confirmed.model_copy(update={"ruling": _ALLOW})

    with pytest.raises(ValueError, match="answers a recorded CONFIRM"):
        _answer(allowed)


@pytest.mark.parametrize("field", ["step_id", "execution_id"])
def test_a_confirmation_belonging_to_a_step_is_refused(field: str) -> None:
    """The refusal that keeps this constructor off every path that executes a call.

    ADR-0235 §4: a confirmation carrying either field belongs to a step of an
    execution and its answer must be built from a *rebound* request through
    ``from_request`` (ADR-0152 §7). A confirmation carrying neither belongs to no
    step, so there is nothing to rebind and nothing to run — which is what makes
    this refusal the structural half of §3's third availability condition rather
    than a second rule to remember.
    """
    confirmed = _confirmation(_binding(ALICE)).model_copy(update={field: "x-1"})

    with pytest.raises(ValueError, match="belongs to a step of an execution"):
        _answer(confirmed)


def test_an_answer_predating_the_question_is_refused() -> None:
    """The ordering ``AuditTrail.record`` enforces, checked before the store is asked.

    ``record`` refuses a resolution whose confirmation "was decided *after* the
    resolution answering it", so a caller that built one would meet the refusal at
    the trail rather than at construction. Equal instants are admitted, which is
    the same boundary the trail admits.
    """
    confirmed = _confirmation(_binding(ALICE))

    with pytest.raises(ValueError, match="decided at or after"):
        _answer(confirmed, decided_at=AT - timedelta(seconds=1))

    assert _answer(confirmed, decided_at=AT).decided_at == AT


def test_the_answer_it_builds_establishes_a_grant() -> None:
    """The two constructors compose, which is the whole point of this one.

    ``established_from`` requires an ``answer`` that resolves *this* confirmation
    with an ``ALLOW``; ``from_confirmation`` is what authors one from a trail row,
    and this is the pair the recorded population rides.
    """
    confirmed = _confirmation(_binding(ALICE))
    answer = _answer(confirmed)

    grant = RecipientGrant.established_from(confirmed, answer, id="g-1", expires_at=EXPIRES)

    assert grant.established_by == confirmed.id
    assert grant.decided_at == answer.decided_at
    assert grant.destinations == confirmed.egress_binding.canonical_destination_set  # type: ignore[union-attr]


# --- §4: the carrier ---------------------------------------------------------


def test_the_carrier_refuses_both_arms() -> None:
    """A value saying a grant was recorded *and* why none was reports something false."""
    grant = RecipientGrant.established_from(
        _confirmation(_binding(ALICE)),
        _answer(_confirmation(_binding(ALICE))),
        id="g-1",
        expires_at=EXPIRES,
    )

    with pytest.raises(ValidationError, match="exactly one of established"):
        RecipientGrantOutcome(
            established=grant,
            not_established=RecipientGrantNotEstablished.REFUSED,
        )


def test_the_carrier_refuses_neither_arm() -> None:
    """The absent carrier already means "no act was collected", which is a different fact."""
    with pytest.raises(ValidationError, match="exactly one of established"):
        RecipientGrantOutcome()


@pytest.mark.parametrize("member", list(RecipientGrantNotEstablished))
def test_every_refusing_member_is_a_carrier_of_its_own(
    member: RecipientGrantNotEstablished,
) -> None:
    """All five of ADR-0235 §4's members are constructible on the refusing arm.

    Parameterised over the enumeration rather than over a list, so a sixth member
    added later is covered the day it lands rather than the day someone remembers.
    """
    outcome = RecipientGrantOutcome(not_established=member)

    assert outcome.established is None
    assert outcome.not_established is member
