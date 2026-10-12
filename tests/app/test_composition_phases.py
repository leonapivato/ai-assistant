"""The phases' thin path is wired only where the opt-in is set (ADR-0309 §2:6, §4:2).

The composition root builds a :class:`~ai_assistant.orchestration.phase_path.PhasePath`
only where ``Settings.phases_thin_path`` is set, which only a test hub does; every other
deployment's engine holds none and runs today's table. Where it is built, it reuses the
objects the root already holds — one plan store, one trail, one memory store, one story
store — and its policy holds no goal authorizations and no goal quotes (ADR-0306 §4:11).

**Nothing here opens a socket.** Every case builds the engine over a hashing embedder and
closes it; the deployment that connects a search account names an ``.invalid`` origin
(RFC 6761 §6.4) and no transport is driven.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from ai_assistant.app import build_engine
from ai_assistant.app.composition import (
    PHASES_CALL_DEADLINE,
    PHASES_ROUND_LIMIT,
    PHASES_TURN_BUDGET,
)
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import ProposedCall
from ai_assistant.orchestration.chat import CHAT_TURN_BUDGET
from ai_assistant.orchestration.phase_path import PhasePath

if TYPE_CHECKING:
    from pathlib import Path

#: The account a configured deployment names. ``.invalid`` (RFC 6761 §6.4).
CONNECTION: Final = "conn-0001"
SEARCH_ORIGIN: Final = "https://search.example.invalid"


def test_the_opt_in_is_unset_by_default() -> None:
    """ADR-0309 §2:6: unset by default, and only a test hub sets it."""
    assert Settings().phases_thin_path is False


async def test_a_deployment_without_the_opt_in_wires_no_phases(tmp_path: Path) -> None:
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        assert engine._phases is None
        assert engine._chat_turn_budget == CHAT_TURN_BUDGET
    finally:
        await engine.aclose()


async def test_the_opt_in_wires_the_path_over_the_roots_own_stores(tmp_path: Path) -> None:
    """One plan store, one trail, one memory store and one story store (§2:6)."""
    engine = build_engine(
        Settings(embedder=EmbedderKind.HASHING, phases_thin_path=True), data_dir=tmp_path
    )
    try:
        phases = engine._phases
        assert isinstance(phases, PhasePath)
        assert phases._plans is engine._plans
        assert phases._acting._plans is engine._plans
        authorizing = phases._authorizing
        assert authorizing._trail is engine._trail
        assert authorizing._memory is engine._memory
        assert authorizing._stories is engine._stories
        # ADR-0306 §4:11: the phases' policy reads no goal authorization and no quote.
        assert authorizing._policy._authorizations is None  # type: ignore[attr-defined]
        assert authorizing._policy._quotes is None  # type: ignore[attr-defined]
        assert phases._round_limit == PHASES_ROUND_LIMIT
        assert phases._round_wait == PHASES_CALL_DEADLINE
        assert engine._chat_turn_budget == PHASES_TURN_BUDGET
        # ADR-0309 §4:2: remembering is offered; the search and the booking are not
        # configured here, so neither is.
        offered = await phases._tools.offered(phases._capabilities)
        assert [str(one.capability) for one in offered] == ["remember"]
    finally:
        await engine.aclose()


async def test_a_connected_search_is_offered_without_the_origin_the_hub_fills(
    tmp_path: Path,
) -> None:
    engine = build_engine(
        Settings(
            embedder=EmbedderKind.HASHING,
            phases_thin_path=True,
            web_search_connection=CONNECTION,
            web_search_origin=SEARCH_ORIGIN,
        ),
        data_dir=tmp_path,
    )
    try:
        phases = engine._phases
        assert phases is not None
        offered = {
            str(one.capability): one for one in await phases._tools.offered(phases._capabilities)
        }
        assert set(offered) == {"web_search", "remember"}
        assert "origin" in offered["web_search"].system_supplied
        # Authorizing selects the search's own declaration, which the searcher compares
        # every call against (ADR-0029 §2).
        (selected,) = await phases._tools.find("web_search")
        assert "origin" not in selected.system_supplied
        # ADR-0247 §4: authorizing is told the search is this deployment's registered
        # one, so its calls carry `closed_loop` and reach the configured route.
        assert phases._authorizing._registered_search == frozenset({str(selected.id)})
        assert phases._authorizing._registered_forecast == frozenset()
    finally:
        await engine.aclose()


async def test_a_configured_booking_act_is_offered_with_its_endpoint_filled(
    tmp_path: Path,
) -> None:
    """ADR-0309 §4:2: the booking act, on a test hub that configured the provider whole."""
    endpoint = "https://bookings.example.invalid"
    engine = build_engine(
        Settings(
            embedder=EmbedderKind.HASHING,
            phases_thin_path=True,
            booking_connection="conn-booking-0001",
            booking_endpoint=endpoint,
            booking_available_from=date(2026, 10, 1),
            booking_available_to=date(2026, 10, 7),
            booking_price_amount=Decimal("120.00"),
            booking_price_currency="EUR",
            booking_billed_amount=Decimal("140.00"),
            booking_billed_currency="EUR",
            booking_retained_records=3,
        ),
        data_dir=tmp_path,
    )
    try:
        phases = engine._phases
        assert phases is not None
        offered = {
            str(one.capability): one for one in await phases._tools.offered(phases._capabilities)
        }
        assert set(offered) == {"book_stay", "remember"}
        assert "origin" in offered["book_stay"].system_supplied
        call = ProposedCall(call_id="c1", name="book_stay", arguments={"date": "2026-10-02"})
        filled = await phases._tools.filled(call)
        assert filled.arguments == {"date": "2026-10-02", "origin": endpoint}
    finally:
        await engine.aclose()
