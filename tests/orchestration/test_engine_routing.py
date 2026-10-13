"""The engine driving ADR-0197's routing stage: the decline, the park, the row, the record.

The obligations §12 puts on the **engine** rather than on the stage or the types.
§4's envelope grammar and §5's resolution arithmetic are in ``test_routing.py``, against
the stage; §8's validators are in ``tests/core/test_routed_types.py``; the moved
``resume`` contract is in the shared ``AssistantEngineContract``, because every
implementation of that surface owes it. What is left is everything that is only true of
a whole pass: that a decline is indistinguishable from an ask routing never touched,
that the row is written **before** the act it precedes, that the two resources a route
holds are released on every path, and that the routed result never reaches a prompt —
not in this pass and not one turn later.

**The cases here are written against the wrong implementations that would pass a
weaker suite.** ADR-0197 §12 names them one by one: a sequential resume passes against a
check-then-register claim, a cooperating composer cannot distinguish a structural
never-re-read from a hopeful one, a one-turn prompt case cannot see a capture that folds
the listing into the episode, and a suite that reclaims a slot before resuming passes
against an implementation whose expiry is only ever noticed by housekeeping. Each of
those is a docstring below.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError
from test_engine import AT, PATIENT, Harness, NoStepPlanner

from ai_assistant.core.config import Settings
from ai_assistant.core.types import (
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Message,
    Provenance,
    RoutableOperation,
    RouteOutcome,
    SemanticMemory,
    TurnOutcome,
    Validity,
)
from ai_assistant.orchestration.routing import RoutingStage
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeModelProvider,
    FakeRoutingRecorder,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import RoutingRecorder

#: The belief every confirm-owed case is about, and the query that names it.
_BELIEF = "rec-preference"
_CONTENT = "the user likes jazz"
_QUERY = "jazz"

#: What the user says to reach a routed ``forget``. Asserted **verbatim** in the captured
#: episode (ADR-0197 §10), so it is spelled once — and deliberately carrying neither
#: :data:`_QUERY` nor :data:`_BELIEF`, which is what lets the cases below assert that no
#: part of the routed account reached a prompt: a sentence sharing the query's words could
#: not tell the account apart from the ask. The router is scripted, so the query need not
#: appear in the sentence at all.
#:
#: It was also the reason a repeat ask stayed unambiguous, back when §5's lookup enumerated
#: every kind and so read the episode of the previous ask beside the belief — the loop
#: ADR-0201 §1 closes, pinned on its own constants at the foot of this module.
_UTTERANCE = "please forget that preference"

# --- scaffolding -------------------------------------------------------------


def _envelope(operation: RoutableOperation, query: str | None = None) -> str:
    """One route envelope, as ADR-0197 §4 spells it."""
    body: dict[str, object] = {"operation": operation.value}
    if query is not None:
        body["query"] = query
    return json.dumps(body)


def _router(reply: str | Callable[[Sequence[Message]], str]) -> FakeModelProvider:
    """A ``ModelProvider`` the routing stage reaches, answering ``reply``."""
    return FakeModelProvider(reply=reply)


def _names(operation: RoutableOperation, query: str | None = None) -> FakeModelProvider:
    """A router that names ``operation`` on every utterance."""
    return _router(_envelope(operation, query))


class _RoutedHarness(Harness):
    """A harness whose routing stage's recorder is reachable to a case.

    ADR-0197 §9 puts the ``RoutingRecorder`` on the **stage** rather than on the façade,
    so there is nothing on ``Harness`` for a case to read the rows off. This keeps the
    object the stage was built with, which is what every §9 case asserts against.
    """

    def __init__(self, *, recorder: RoutingRecorder, **knobs: Any) -> None:
        """Build the ordinary harness, remembering the recorder its stage holds."""
        super().__init__(**knobs)
        self.recorder = recorder


def _routed_harness(
    *,
    router: FakeModelProvider | None = None,
    recorder: RoutingRecorder | None = None,
    **knobs: Any,
) -> _RoutedHarness:
    """A harness that routes a ``forget`` on :data:`_QUERY` unless told otherwise.

    The stage is built **here** rather than passed in, because ADR-0197 §9 makes the
    recorder part of the stage's own construction: a case that wants to read the rows or
    script a write failure names the recorder, and this is what puts the same object
    behind the stage and in front of the assertion.

    ``NoStepPlanner`` is the default because every *declined* case below has to show the
    ordinary pipeline running to its own answer, and a plan with no step is the cheapest
    shape that does: it produces a turn, persists its goal and plan, and composes.
    """
    held: RoutingRecorder = FakeRoutingRecorder() if recorder is None else recorder
    knobs.setdefault(
        "routing",
        RoutingStage(
            model=_names(RoutableOperation.FORGET, _QUERY) if router is None else router,
            recorder=held,
        ),
    )
    knobs.setdefault("planner", NoStepPlanner())
    return _RoutedHarness(recorder=held, **knobs)


async def _seed_belief(
    memory: FakeMemoryStore, record_id: str = _BELIEF, content: str = _CONTENT
) -> None:
    """Put one live belief in the store ADR-0197 §5's lookup reads.

    §5 resolves the argument "by deterministic local code reading the store the operation
    itself reads", so a route with nothing in that store ends in ``NOT_FOUND`` rather
    than parking — which makes seeding a precondition of every confirm-owed case rather
    than a convenience.
    """
    await memory.write_atomic(
        [
            MemoryWrite(
                record=SemanticMemory(
                    id=record_id,
                    content=content,
                    fact=content,
                    validity=Validity(),
                    provenance=Provenance(
                        source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT
                    ),
                ),
                mode=MemoryWriteMode.INSERT_IF_ABSENT,
            )
        ]
    )


async def _parked(harness: Harness) -> TurnOutcome:
    """Drive one routed ``forget`` to its park, and assert it got there."""
    outcome = await harness.engine.converse(_UTTERANCE, timeout=PATIENT)
    assert outcome.routed is not None
    assert outcome.routed.outcome is RouteOutcome.AWAITING_CONFIRMATION
    assert outcome.routed.confirmation is not None
    return outcome


def _token(outcome: TurnOutcome) -> Any:
    """The continuation a parked routed outcome is answered with."""
    assert outcome.routed is not None
    assert outcome.routed.confirmation is not None
    return outcome.routed.confirmation.token


# --- ADR-0197 §7: the park, its slot, its identity and its lifetime ----------


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="the disable sentinel"),
        pytest.param(timedelta(0), id="zero"),
        pytest.param(timedelta(seconds=-1), id="a negative duration"),
    ],
)
def test_the_routed_lifetime_is_refused_at_load_for_every_value_that_disables_it(
    value: timedelta | None,
) -> None:
    """§7: a ``_DurationSetting``, deliberately **not** a ``_NullableDuration``.

    "``None`` is not a value it accepts: it takes no part in the disable sentinel
    ``confirmation_ttl`` opts into, which is exactly the wrong default to inherit here,
    and a zero or negative duration is refused at load rather than producing a card
    unusable the instant it is rendered."
    """
    with pytest.raises(ValidationError):
        Settings(routed_confirmation_ttl=value)  # type: ignore[arg-type]  # the refusal is the subject


# --- ADR-0197 §9: the route_id reservation, which the store cannot see -------


def _cycling(*values: str) -> Callable[[], str]:
    """An id factory yielding ``values`` in turn, then repeating the cycle.

    A read-only routed pass draws exactly two ids from the engine's one factory — the
    ``route_id`` it reserves and the row's own id — so a two-value cycle gives consecutive
    passes the **same** route id and **distinct** row ids, which is the only way to ask
    whether the identity was released without also colliding the rows (a different clause,
    ``record``'s own idempotence, which would mask this one).
    """
    order = list(values)
    drawn = 0

    def mint() -> str:
        nonlocal drawn
        value = order[drawn % len(order)]
        drawn += 1
        return value

    return mint
