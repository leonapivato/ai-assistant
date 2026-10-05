"""The stop command at the gateway (ADR-0297 §5, §6:4; ADR-0295 §1).

The chat's stop control beside "working…" posts ``/activation/stop`` with the id the
conversation's current state named, and the gateway relays it to ``stop_activation``
and answers the :class:`~ai_assistant.core.types.ActivationStop` member as its own
value. ADR-0297 §6:4 places that control on this surface by name; the record it owes
ADR-0177 §1:1's enumeration is issue #2714.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from test_gateway_streams import Harness, _harness

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import ActivationStop
from ai_assistant.interfaces.gateway.server import _ASSISTANT_PATHS
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.types import Identifier

pytestmark = pytest.mark.integration

_PATH: Final = "/activation/stop"

#: An activation id as the current state names one (ADR-0275 §6:1's canonical UUID4).
_ACTIVATION: Final = "00000000-0000-4000-8000-000000000001"


class _Answering(FakeAssistantEngine):
    """An engine whose stop answers as scripted, and records what it was asked."""

    def __init__(self) -> None:
        super().__init__()
        self.scripted = ActivationStop.STOPPED

    async def stop_activation(self, activation_id: Identifier, /) -> ActivationStop:
        self.calls.append(("stop_activation", {"activation_id": activation_id}))
        return self.scripted


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    """A gateway over an engine whose stop answers as each case scripts."""
    async with _harness(_Answering()) as one:
        yield one


def test_the_stop_is_one_post_in_the_enumeration() -> None:
    """ADR-0297 §6:4's control, read off the table the router classifies from."""
    assert _ASSISTANT_PATHS[("POST", _PATH)] == "stop_activation"
    assert ("GET", _PATH) not in _ASSISTANT_PATHS


@pytest.mark.parametrize("member", list(ActivationStop))
async def test_the_id_is_relayed_whole_and_the_answer_is_its_own_value(
    harness: Harness, member: ActivationStop
) -> None:
    """§5:4-§5:6: every answer is an answer, none a fault, and the gateway adds nothing.

    The body carries the id the page read off the current state and nothing else; the
    engine is reached once, with that id, and its member comes back as its value.
    """
    engine = harness.engine
    assert isinstance(engine, _Answering)
    engine.scripted = member

    status, body = await harness.whole("POST", _PATH, {"activation_id": _ACTIVATION})

    assert status == 200
    assert body == {"stop": member.value}
    assert engine.calls == [("stop_activation", {"activation_id": _ACTIVATION})]


async def test_an_id_nothing_says_ran_is_the_fakes_own_answer() -> None:
    """§5:6 through the canonical fake: no running activation and no episode there."""
    async with _harness() as harness:
        status, body = await harness.whole("POST", _PATH, {"activation_id": _ACTIVATION})

        assert status == 200
        assert body == {"stop": "no_such_activation"}
        assert harness.engine.calls == [("stop_activation", {"activation_id": _ACTIVATION})]


@pytest.mark.parametrize("payload", [{}, {"activation_id": None}, {"activation_id": 7}])
async def test_a_body_without_an_id_is_refused_before_the_engine_is_reached(
    harness: Harness, payload: dict[str, object]
) -> None:
    """ADR-0168 §1's biconditional: a refusal the gateway takes reaches no engine."""
    status, _ = await harness.whole("POST", _PATH, payload)

    assert status == 400
    assert harness.engine.calls == []


async def test_a_stop_the_hub_could_not_answer_is_a_fault_not_an_answer() -> None:
    """ADR-0168 §9: a failure is never presented as one of the three answers."""

    class _Failing(FakeAssistantEngine):
        async def stop_activation(self, activation_id: Identifier, /) -> ActivationStop:
            msg = "the episode store could not be read"
            raise MemoryStoreError(msg)

    async with _harness(_Failing()) as harness:
        status, body = await harness.whole("POST", _PATH, {"activation_id": _ACTIVATION})

        assert status >= 400
        assert "stop" not in body
