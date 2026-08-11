"""ADR-0130 §9's five engine methods survive a real socket.

The shared ``AssistantEngineContract`` asserts the clauses *no type expresses*
and ADR-0130 §9 adds none to it, so nothing there drives these five. That leaves
a gap worth closing on its own terms rather than by widening the contract suite:
the notification surface is the first on this Protocol to carry a **pydantic
model as an argument** and the first to carry a *nested* model graph back, so
"does the wire round-trip it?" is a question about ADR-0087's canonical encoding
rather than about the client's five one-liners.

It is also what caught the one shape that does **not** travel.
:class:`~ai_assistant.core.types.QuietWindow` was drafted holding two
:class:`datetime.time` endpoints, and :func:`ai_assistant.wire.codec.project`
refused it — "``time`` has no canonical wire form on this surface" — which is
that module failing closed exactly as its docstring says it should. Minting a
canonical form for a time-of-day is ADR-0087's decision; the window now holds
minutes since midnight, which already has one. The case below is what stops that
regressing quietly.

Driven against a real ``AF_UNIX`` socket with
:class:`~ai_assistant.testing.FakeAssistantEngine` on the far side, exactly as
``test_client_contract.py`` does, because a test that stubbed ``_call`` would
assert the client sends what the client sends.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING

import pytest
from test_client_contract import serving

from ai_assistant.core.types import (
    ClassReach,
    DataTier,
    NotificationCandidate,
    NotificationDispositionKind,
    NotificationPreferences,
    NotificationReach,
    QuietWindow,
)
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from pathlib import Path

_AT = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def _candidate(key: str = "k1") -> NotificationCandidate:
    """One candidate for the fake engine's store to admit."""
    return NotificationCandidate(
        candidate_key=key,
        producer="a-producer",
        notification_class="calendar",
        summary="something the user did not ask for",
        detail="and a second line of it",
        noticed_at=_AT,
        expires_at=_AT + timedelta(hours=2),
        confidence=0.5,
        sensitivity=DataTier.PERSONAL,
        references=("rec-1", "rec-2"),
    )


async def _held(engine: FakeAssistantEngine, key: str = "k1") -> str:
    """Admit one candidate through the engine's own store, and name the record.

    Through the store rather than through a surface method, because there is no
    producer on this Protocol: ADR-0130 §1 gives a producer the seam of §3 and
    nothing else, and §7 makes the engine's side of it a **read**.
    """
    ruling = await engine.notification_store.admit(
        _candidate(key), policy=engine.notification_policy
    )
    assert ruling.notification_id is not None
    return ruling.notification_id


async def test_a_held_notification_round_trips_whole(tmp_path: Path) -> None:
    """Every field of the record survives the encode, including the nested candidate.

    The enumeration is the one method here that carries a *model graph* back —
    record, candidate, condition enums, an optional detail and a tuple of
    references — so an encoding that dropped or coerced any of it shows up here
    rather than in a client rendering a blank line.
    """
    backing = FakeAssistantEngine()
    record_id = await _held(backing)

    async with serving(backing, tmp_path / "hub.sock") as client:
        page = await client.notifications()

    assert [record.id for record in page] == [record_id]
    assert page[0].candidate == _candidate()
    assert page[0].kind is NotificationDispositionKind.HOLD
    assert page[0] == (await backing.notifications())[0]


async def test_the_enumeration_pages_like_every_other(tmp_path: Path) -> None:
    """ADR-0085 §3a/§9: the page-size default binds, and a bad argument is local."""
    backing = FakeAssistantEngine()
    await _held(backing, "k1")
    await _held(backing, "k2")

    async with serving(backing, tmp_path / "hub.sock") as client:
        assert len(await client.notifications(limit=1)) == 1
        assert len(await client.notifications(limit=1, offset=1)) == 1
        assert len(await client.notifications()) == 2

        with pytest.raises(ValueError, match="limit"):
            await client.notifications(limit=-1)


async def test_a_quiet_window_survives_the_canonical_encoding(tmp_path: Path) -> None:
    """The quiet windows are the shape that had to be re-spelled to travel.

    Two of them, one of which **crosses midnight** — the ordinary overnight case,
    and the one an encoding that silently normalised ``start > end`` would destroy
    while every other assertion stayed green. Written through
    :meth:`~ai_assistant.core.types.QuietWindow.between` so the case reads in the
    units a person sets a quiet window in, and asserted by equality so a
    round-trip that lost the minute would fail.
    """
    backing = FakeAssistantEngine()
    settings = NotificationPreferences(
        reaches=(ClassReach(notification_class="calendar", reach=NotificationReach.INTERRUPT),),
        quiet_windows=(
            QuietWindow.between(time(22, 0), time(7, 30)),
            QuietWindow.between(time(13, 0), time(14, 0)),
        ),
        interruption_budget=1,
        budget_window=timedelta(hours=6),
    )

    async with serving(backing, tmp_path / "hub.sock") as client:
        written = await client.set_notification_preferences(settings)
        read_back = await client.notification_preferences()

    assert written == settings
    assert read_back == settings
    assert await backing.notification_preferences() == settings


async def test_the_defaults_come_back_from_an_untouched_hub(tmp_path: Path) -> None:
    """ADR-0130 §6: an empty store is a working policy, over the wire too."""
    async with serving(FakeAssistantEngine(), tmp_path / "hub.sock") as client:
        settings = await client.notification_preferences()

    assert settings.reach_for("anything") is NotificationReach.HOLD
    assert settings.quiet_windows == ()
    assert settings.interruption_budget == 3


async def test_dismissing_and_forgetting_are_two_different_acts(tmp_path: Path) -> None:
    """§7, §9: a dismissal leaves the record readable; a delete does not.

    Asserted over the socket because it is the pair a client renders side by
    side, and a client that wired one to the other would look correct in every
    single-call test.
    """
    backing = FakeAssistantEngine()
    record_id = await _held(backing)

    async with serving(backing, tmp_path / "hub.sock") as client:
        assert await client.dismiss_notification(record_id) is True
        assert [record.id for record in await client.notifications()] == [record_id]
        assert await client.dismiss_notification(record_id) is False

        assert await client.forget_notification(record_id) is True
        assert await client.notifications() == ()
        assert await client.forget_notification(record_id) is False


async def test_a_blank_identifier_is_refused_without_a_round_trip(tmp_path: Path) -> None:
    """ADR-0085 §9: refused locally, so neither implementation is more permissive."""
    backing = FakeAssistantEngine()

    async with serving(backing, tmp_path / "hub.sock") as client:
        with pytest.raises(ValueError, match="notification_id"):
            await client.dismiss_notification("   ")
        with pytest.raises(ValueError, match="notification_id"):
            await client.forget_notification("")

    assert backing.calls == []
