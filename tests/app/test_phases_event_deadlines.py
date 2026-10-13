"""An event's writes run inside its budget, through the root, on the phases.

``test_open_episode_composition`` held these over the old event path, whose deadline
raised ``ChannelProcessingTimeoutError``. ADR-0313 §4:5 makes an event the phases run
that cannot finish a result reading *couldn't finish*, and what both cases hold
survives it: an episode append whose store never answers is cut off at the
activation's deadline and the freeze still records (ADR-0286 §3:8), and an admission
insert the store never answers is cut off where the event's budget starts, at receiver
admission, leaving nothing (ADR-0274 §7, ADR-0286 §2:1).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import pytest
from phases_composition_support import SENSOR, Phased, build_phased

from ai_assistant.core.types import (
    ActivationEnding,
    ChannelInput,
    ControllerRule,
    InformationalEventResult,
    MemoryWriteMode,
    ProcessingStatus,
    TextChannelPayload,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from pathlib import Path

    from ai_assistant.core.types import ChannelResult, MemoryWrite
    from ai_assistant.orchestration.activation_state import ActivationState

pytestmark = pytest.mark.integration

#: The event's budget: long enough for admission and the first stages over the fakes.
_BUDGET: Final = timedelta(milliseconds=300)

#: How long a case waits for the call to return before it fails, rather than hangs.
_BOUND: Final = 5.0


@pytest.fixture
async def composed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Phased]:
    """The production root with the phases, over a fresh data directory, started."""
    built = build_phased(tmp_path, monkeypatch)
    await built.engine.start()
    try:
        yield built
    finally:
        await built.engine.aclose()


async def _event(composed: Phased) -> ChannelResult:
    """One event under :data:`_BUDGET`, failing rather than hanging past :data:`_BOUND`."""
    return await asyncio.wait_for(
        composed.engine.receive(
            ChannelInput(target=SENSOR, payload=TextChannelPayload(text="eco mode")),
            reply=None,
            timeout=_BUDGET,
        ),
        timeout=_BOUND,
    )


def _couldnt_finish(result: ChannelResult) -> None:
    assert isinstance(result.result, InformationalEventResult)
    assert result.result.ended is ActivationEnding.COULDNT_FINISH


async def test_an_append_runs_inside_the_activations_deadline(composed: Phased) -> None:
    """ADR-0286 §3:8: an append whose store never answers is cut off at the deadline;
    the event ends *couldn't finish*, and the freeze still records."""
    addresses: list[str] = []

    async def never(state: ActivationState, **_kwargs: object) -> None:
        assert state.episode_address is not None
        addresses.append(state.episode_address)
        await asyncio.Event().wait()

    # A test double for the bound method: the store read it makes never returns.
    composed.writer.append = never  # type: ignore[method-assign]

    result = await _event(composed)

    _couldnt_finish(result)
    episode = await composed.stored(addresses[0])
    assert episode is not None
    processing = episode.processing_record
    assert processing is not None
    assert not processing.is_open
    assert processing.status is not ProcessingStatus.COMPLETED
    assert processing.stages[-1].due is ControllerRule.STAGE_TIMED_OUT


async def test_the_admission_write_runs_inside_the_events_budget(
    composed: Phased, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0274 §7, ADR-0286 §2:1: the budget starts at receiver admission, so an
    admission insert the store never answers is cut off there, and leaves nothing."""
    addresses: list[str] = []
    original = composed.memory.write_atomic

    async def write_atomic(writes: Sequence[MemoryWrite]) -> Sequence[str]:
        if not addresses and any(
            write.mode is MemoryWriteMode.INSERT_IF_ABSENT for write in writes
        ):
            addresses.append(writes[0].record.id)
            await asyncio.Event().wait()
        return await original(writes)

    monkeypatch.setattr(composed.memory, "write_atomic", write_atomic)

    result = await _event(composed)

    _couldnt_finish(result)
    (address,) = addresses
    assert await composed.stored(address) is None
    assert not composed.writer.holds(address)
