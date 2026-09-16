"""ADR-0260 §13's arm (h), turn-level: the field a surface reads, and the statement.

``test_forecast_servicing.py`` drives the servicing site and asserts what one servicing
**carries**; this module drives the pipeline **above** it — ``Engine.converse`` and the
``TurnOutcome`` it builds — because §10 puts the fold on ``TurnOutcome.forecast_not_read``
and ADR-0264 §6 assembles the statement at the capture point, and a lane that dropped
either forwarding would leave every servicing-level assertion passing while the user lost
both.

**The subject is production throughout**: the real ``Engine``, the real
:class:`~ai_assistant.orchestration.reads.ForecastServicer` over the real binding seam
and the real :class:`~ai_assistant.permissions.ThresholdActionPolicy`, with the canonical
fake standing only for the provider. ``forecast_servicing_harness.py`` records why the
binder is the real one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest
from forecast_servicing_harness import forecaster, servicer
from test_engine import PATIENT, Harness
from test_engine_read_envelope import _AskingPlanner

from ai_assistant.core.types import (
    ForecastNotRead,
    ForecastRefusal,
    OutboundDestination,
    OutboundReach,
    ReadAsk,
    ReadKind,
    ReadRequest,
)
from ai_assistant.testing import DEFAULT_FORECAST_DAYS

if TYPE_CHECKING:
    from ai_assistant.core.types import TurnOutcome

_UTTERANCE: Final = "what does the weekend look like"


def _asks() -> ReadRequest:
    """A request asking for a forecast and nothing else (ADR-0260 §3)."""
    return ReadRequest(asks=(ReadAsk(kind=ReadKind.FORECAST_READ),))


async def _turn(**knobs: Any) -> TurnOutcome:
    """Drive one turn through the real engine over a configured forecast deployment.

    Args:
        **knobs: Whatever the case varies on the servicing — the seam, or whether the
            deployment configured the pair at all.

    Returns:
        The outcome the capture point built.
    """
    harness = Harness(
        planner=_AskingPlanner(_asks(), rounds=1),
        forecast=servicer(**knobs),
    )
    return await harness.engine.converse(_UTTERANCE, timeout=PATIENT)


async def test_an_answered_read_carries_no_member_and_names_the_forecast_provider() -> None:
    """§13's arm (h), first case, **through to the turn**.

    "A read the provider answered carries ``forecast_not_read`` ``None`` and an outbound
    statement naming ``FORECAST_PROVIDER``." §10's ``None`` "means the servicing recorded
    no ``ForecastDisposition``, and means nothing else" — a turn that serviced no forecast
    read, and a read the provider answered — and the statement beside it is what tells
    those two apart for the user, which is the asymmetry #2268 recorded for search
    arriving at a second seam.

    The records count is ADR-0264 §4's, "how many records this turn's established
    contacts put into the turn's **supply**", so it is what the fourth group admitted and
    not what the provider returned.
    """
    outcome = await _turn()

    assert outcome.forecast_not_read is None, "the provider answered"
    statement = outcome.outbound_statement
    assert statement is not None
    assert statement.reach is OutboundReach.REACHED
    assert statement.destinations == (OutboundDestination.FORECAST_PROVIDER,)
    assert statement.records == len(DEFAULT_FORECAST_DAYS)
    assert outcome.search_not_serviced is None, "no search was asked for, so no member"


async def test_a_read_the_deployment_could_not_authorise_carries_the_member_and_no_class() -> None:
    """§13's arm (h), second case, through to the turn: the member, and **no** class.

    A deployment that configured no forecast pair takes route (c) in no case — §6's
    fail-closed direction — so the ruling is a ``CONFIRM``, which §11 parks nowhere and
    §10 folds to ``AUTHORISATION_AWAITED`` on the **no-contact** side. So the user is
    told a class of act and the turn says it reached nothing, which are two statements
    ADR-0264 §8 has ride together rather than one suppressing the other.
    """
    outcome = await _turn(configured=False)

    assert outcome.forecast_not_read is ForecastNotRead.AUTHORISATION_AWAITED
    statement = outcome.outbound_statement
    assert statement is not None
    assert statement.reach is OutboundReach.NOT_REACHED
    assert statement.destinations == ()
    assert statement.records == 0


@pytest.mark.parametrize(
    ("refusal", "member", "reach"),
    [
        (
            ForecastRefusal.UNATTESTED,
            ForecastNotRead.UNAVAILABLE,
            OutboundReach.REACHED,
        ),
        (
            ForecastRefusal.RESPONSE_TOO_LARGE,
            ForecastNotRead.UNAVAILABLE,
            OutboundReach.REACHED,
        ),
        (
            ForecastRefusal.DEADLINE_EXPIRED,
            ForecastNotRead.INTERRUPTED,
            OutboundReach.INDETERMINATE,
        ),
        (
            ForecastRefusal.TRANSPORT_FAILED,
            ForecastNotRead.UNAVAILABLE,
            OutboundReach.INDETERMINATE,
        ),
        (
            ForecastRefusal.PROVIDER_REFUSED,
            ForecastNotRead.UNAVAILABLE,
            OutboundReach.INDETERMINATE,
        ),
        (ForecastRefusal.NO_RESULT, None, OutboundReach.REACHED),
    ],
)
async def test_each_refusal_reaches_the_turn_as_its_member_and_its_reach(
    refusal: ForecastRefusal,
    member: ForecastNotRead | None,
    reach: OutboundReach,
) -> None:
    """§13's arm (h)'s remaining cases, each carried the whole way to the outcome.

    The pairs are §10's and are asserted **together**, because the two facts are
    computed from two rules over one disposition and neither is read off the other:
    ``UNATTESTED`` and ``RESPONSE_TOO_LARGE`` carry ``UNAVAILABLE`` **with** a contact —
    "either folded to ``INDETERMINATE`` would deny a contact the trail recorded" — while
    the three nothing-either-way members carry ``INDETERMINATE`` with **no** class.
    ``NO_RESULT`` is the thirteenth case: it maps to no disposition at all, so the turn
    carries no member and the contact its call established.

    **The count rides with the contact and never without it** (ADR-0264 §4): every one of
    these brought nothing into the supply, and a ``0`` "never suppresses the statement".

    Args:
        refusal: What the provider's answer resolved to.
        member: The member §10 folds it to, or ``None`` where it records no disposition.
        reach: The side of §10's partition it lands on.
    """
    outcome = await _turn(seam=forecaster(refusal=refusal))

    assert outcome.forecast_not_read is member
    statement = outcome.outbound_statement
    assert statement is not None
    assert statement.reach is reach
    assert statement.records == 0, "nothing entered the supply, and the statement stands"
    if reach is OutboundReach.REACHED:
        assert statement.destinations == (OutboundDestination.FORECAST_PROVIDER,)
    else:
        assert statement.destinations == (), "only a contact names a class (ADR-0264 §4)"


async def test_a_turn_that_asked_for_no_forecast_carries_neither_the_member_nor_a_class() -> None:
    """The control every case above rests on: ``None`` on a turn that never asked.

    §10 gives ``None`` exactly two meanings — "a turn that serviced no forecast read,
    and a read the provider answered" — so without this the first case's ``None`` would
    be evidence of nothing. The statement is what separates them: this turn reached
    nothing and says so, where the answered turn names the class it contacted.
    """
    harness = Harness(planner=_AskingPlanner(None, rounds=1), forecast=servicer())

    outcome = await harness.engine.converse(_UTTERANCE, timeout=PATIENT)

    assert outcome.forecast_not_read is None
    statement = outcome.outbound_statement
    assert statement is not None
    assert statement.reach is OutboundReach.NOT_REACHED
    assert statement.destinations == ()
