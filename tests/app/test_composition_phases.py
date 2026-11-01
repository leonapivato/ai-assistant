"""The composition root always wires the phases (ADR-0309 §2:6, §4:2).

The switch removed the opt-in: every deployment's engine holds a
:class:`~ai_assistant.orchestration.phase_path.PhasePath`, which plans every activation.
It reuses the objects the root already holds — one plan store, one trail, one memory
store, one story store — and its policy holds no goal authorizations and no goal quotes
(ADR-0306 §4:11). Planning is offered every capability the phases' tools advertise: the
registry's, the configured search, and the assistant's own records' (ADR-0306 §2:7), the
clock apart, since planning's input carries the current time (#2942).

**Nothing here opens a socket.** Every case builds the engine over a hashing embedder and
closes it; a deployment that connects an account names an ``.invalid`` origin (RFC 6761
§6.4) and no transport is driven.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from ai_assistant.app import build_engine
from ai_assistant.app.composition import (
    PHASES_CALL_DEADLINE,
    PHASES_MEMORY_SEARCH_LIMIT,
    PHASES_ROUND_LIMIT,
    PHASES_TURN_BUDGET,
    RECALL_SECOND_RUN_CAP,
)
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    RECALLED_ITEMS_MAX,
    ProposedCall,
    ToolDefinition,
)
from ai_assistant.orchestration.acting import _Beside
from ai_assistant.orchestration.approvals import (
    APPROVAL_CAPABILITIES,
    REQUEST_APPROVAL_CAPABILITY,
)
from ai_assistant.orchestration.lookups import (
    LOOK_UP_CAPABILITIES,
    LOOK_UP_LABEL_ARGUMENTS,
    LookUps,
)
from ai_assistant.orchestration.matter_calls import MATTER_CAPABILITIES, MATTER_LABEL_ARGUMENTS
from ai_assistant.orchestration.message_tools import TEXT_CAPABILITY
from ai_assistant.orchestration.phase_path import PhasePath
from ai_assistant.orchestration.reliance import NOTE_RELIANCE_CAPABILITY, RELIANCE_LABEL_ARGUMENTS
from ai_assistant.orchestration.remembering import CANDIDATE_LABEL_ARGUMENTS
from ai_assistant.orchestration.story_calls import (
    STORY_CALL_CAPABILITIES,
    STORY_LABEL_ARGUMENTS,
    StoryCalls,
)
from ai_assistant.orchestration.task_scheduler import (
    TASK_SCHEDULER_CAPABILITIES,
    TASK_SCHEDULER_LABEL_ARGUMENTS,
)

if TYPE_CHECKING:
    from pathlib import Path

#: The account a configured deployment names. ``.invalid`` (RFC 6761 §6.4).
CONNECTION: Final = "conn-0001"
SEARCH_ORIGIN: Final = "https://search.example.invalid"


#: What every round of every activation is offered beside the tools a deployment
#: advertises (ADR-0356 §4:3): ``text``, and the Task Scheduler's calls and the calls on
#: running work, which the composition root attaches on every deployment.
_EVERY_ROUND: Final = frozenset(
    {TEXT_CAPABILITY, *TASK_SCHEDULER_CAPABILITIES, *MATTER_CAPABILITIES}
)


async def _offered(phases: PhasePath) -> tuple[ToolDefinition, ...]:
    """What planning is offered from the tools advertised: every capability, bar one.

    Every round is offered :data:`_EVERY_ROUND` too (ADR-0356 §4:3), which is held here
    and left out of what each case compares.
    """
    assert phases._capabilities is None, "no fixed list: every one advertised"
    offered = await phases._offered()
    assert {str(one.capability) for one in offered} >= _EVERY_ROUND
    return tuple(one for one in offered if str(one.capability) not in _EVERY_ROUND)


def test_the_opt_in_is_gone() -> None:
    """ADR-0309 §2:6: the switch removes it, so no setting reads it."""
    assert "phases_thin_path" not in Settings.model_fields


async def test_every_deployment_wires_the_path_over_the_roots_own_stores(  # noqa: PLR0915 — one assertion per seam the root wires
    tmp_path: Path,
) -> None:
    """One plan store, one trail, one memory store and one story store (§2:6)."""
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        phases = engine._phases
        assert isinstance(phases, PhasePath)
        assert phases._plans is engine._plans
        assert phases._acting._plans is engine._plans
        authorizing = phases._authorizing
        assert authorizing._trail is engine._trail
        assert authorizing._memory is engine._memory
        assert authorizing._stories is engine._stories
        assert phases._round_limit == PHASES_ROUND_LIMIT
        assert phases._round_wait == PHASES_CALL_DEADLINE
        # ADR-0308 §2:5, §3: the second run's provisional cap, and the one memory store
        # recall searched, which planning fetches its finds from.
        assert phases._recall_cap == RECALL_SECOND_RUN_CAP
        assert 1 <= RECALL_SECOND_RUN_CAP <= RECALLED_ITEMS_MAX
        assert phases._memory is engine._memory
        assert engine._chat_turn_budget == PHASES_TURN_BUDGET
        # ADR-0306 §2:7: every capability the tools advertise — here remembering and
        # noting reliance (ADR-0329 §3:1, §6:7); no
        # search, account or booking is configured, so none of theirs, and the clock
        # the registry holds is not offered, since planning's input carries ``now``
        # (#2942). Planning's story calls that write are offered beside them
        # (ADR-0300 §10, ADR-0303 §9), with their label arguments, and its look-ups
        # (ADR-0307 §6:6), with theirs.
        offered = await _offered(phases)
        assert {str(one.capability) for one in offered} == {
            "remember",
            NOTE_RELIANCE_CAPABILITY,
            *STORY_CALL_CAPABILITIES,
            *LOOK_UP_CAPABILITIES,
            # ADR-0361 §2:1: the Approvals channel's actuator, on every deployment.
            REQUEST_APPROVAL_CAPABILITY,
        }
        # ADR-0048 §1: the clock stays registered, and selection still finds it.
        clock = await phases._tools.find("report_current_time")
        assert [str(one.id) for one in clock] == ["current_time"]
        # ADR-0329 §3:1, §6:7: `remember` records a candidate, whose labels and the
        # reliance call's are filled like any other's.
        # ADR-0350 §4: and the Task Scheduler's, attached on every deployment, which name
        # tasks and places by label; and ADR-0349 §4:6, §6:1, §7:20's calls on running
        # work, attached by the engine, which name running work by its episode's label.
        assert phases._label_arguments == {
            **STORY_LABEL_ARGUMENTS,
            **LOOK_UP_LABEL_ARGUMENTS,
            **CANDIDATE_LABEL_ARGUMENTS,
            **RELIANCE_LABEL_ARGUMENTS,
            **TASK_SCHEDULER_LABEL_ARGUMENTS,
            **MATTER_LABEL_ARGUMENTS,
        }
        # ADR-0357 §2:4: a ``text`` call's ``via`` names a place or a platform, so the
        # phases resolve it, and the judge's label check never reads it.
        assert TEXT_CAPABILITY not in phases._label_arguments
        assert phases._task_calls is not None
        assert phases._matters is engine._matters
        # One look-ups runner behind every look-up, over the root's own memory store and
        # the story views' reads, whose scope the path opens around acting.
        look_ups = phases._look_ups
        assert isinstance(look_ups, LookUps)
        assert look_ups._memory is engine._memory
        assert look_ups._views is phases._story_reads
        assert look_ups._search_limit == PHASES_MEMORY_SEARCH_LIMIT
        # Each story call runs through acting's own-records seam, over the root's own
        # stores and the one tidy-up, so at most one run is on a story at a time
        # (ADR-0300 §5:10).
        # ADR-0361 §3:3: request_approval's runner sits outermost, attached last.
        approvals = phases._acting._own_records
        assert isinstance(approvals, _Beside)
        assert set(approvals._runners) == APPROVAL_CAPABILITIES
        # The Task Scheduler's runners sit beside the root's seam (ADR-0350 §4:3).
        seam = approvals._beside
        assert isinstance(seam, _Beside)
        assert set(seam._runners) == TASK_SCHEDULER_CAPABILITIES
        # ADR-0349 §4:7, §6:4, §7:20: and the calls on running work beside those.
        matters = seam._beside
        assert isinstance(matters, _Beside)
        assert set(matters._runners) == MATTER_CAPABILITIES
        runners = matters._beside._runners  # type: ignore[attr-defined]
        held = {id(runners[name]): runners[name] for name in STORY_CALL_CAPABILITIES}
        (story_calls,) = held.values()
        assert isinstance(story_calls, StoryCalls)
        assert all(runners[name] is look_ups for name in LOOK_UP_CAPABILITIES)
        assert story_calls._stories is engine._stories
        assert story_calls._memory is engine._memory
        assert story_calls._tidy_up is not None
        assert not hasattr(engine, "_interim_tidy_up"), "the interim run is gone (§5:8)"
        # The same runner makes the hub's check of a move or a split before authorizing
        # (ADR-0307 §5:3-§5:4).
        assert phases._story_calls is story_calls
        # The engine handed the path its tracked spawn, so shutdown drains a tidy-up.
        assert phases._spawn == engine._spawn_read
    finally:
        await engine.aclose()


async def test_a_connected_search_is_offered_without_the_origin_the_hub_fills(
    tmp_path: Path,
) -> None:
    engine = build_engine(
        Settings(
            embedder=EmbedderKind.HASHING,
            web_search_connection=CONNECTION,
            web_search_origin=SEARCH_ORIGIN,
        ),
        data_dir=tmp_path,
    )
    try:
        phases = engine._phases
        assert phases is not None
        offered = {str(one.capability): one for one in await _offered(phases)}
        assert set(offered) == {
            "web_search",
            "remember",
            NOTE_RELIANCE_CAPABILITY,
            *STORY_CALL_CAPABILITIES,
            *LOOK_UP_CAPABILITIES,
            # ADR-0361 §2:1: the Approvals channel's actuator, on every deployment.
            REQUEST_APPROVAL_CAPABILITY,
        }
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
        offered = {str(one.capability): one for one in await _offered(phases)}
        assert set(offered) == {
            "booking_availability",
            "book_stay",
            "remember",
            NOTE_RELIANCE_CAPABILITY,
            *STORY_CALL_CAPABILITIES,
            *LOOK_UP_CAPABILITIES,
            # ADR-0361 §2:1: the Approvals channel's actuator, on every deployment.
            REQUEST_APPROVAL_CAPABILITY,
        }
        # Both of the provider's capabilities name the configured endpoint, which the hub
        # fills and planning is never offered (ADR-0306 §2:10).
        for name in ("booking_availability", "book_stay"):
            assert "origin" in offered[name].system_supplied, name
            call = ProposedCall(call_id="c1", name=name, arguments={"date": "2026-10-02"})
            filled = await phases._tools.filled(call)
            assert filled.arguments == {"date": "2026-10-02", "origin": endpoint}, name
        # ADR-0361 §2:3: a request's nested call is prepared as the direct call is.
        asking = ProposedCall(
            call_id="ask-1",
            name=REQUEST_APPROVAL_CAPABILITY,
            arguments={
                "call": {"capability": "book_stay", "arguments": {"date": "2026-10-02"}},
                "why": "You asked me to book it.",
            },
        )
        prepared = await phases._filled(asking)
        assert prepared.arguments["call"] == {
            "capability": "book_stay",
            "arguments": {"date": "2026-10-02", "origin": endpoint},
        }
    finally:
        await engine.aclose()


async def test_a_connected_account_s_send_is_offered(tmp_path: Path) -> None:
    """ADR-0306 §2:7, ADR-0357 §2:5: ``email``, registered where an account is connected,
    is offered."""
    engine = build_engine(
        Settings(
            embedder=EmbedderKind.HASHING,
            send_email_connection="conn-mail-0001",
            send_email_endpoint="smtps://mail.example.invalid:465",
        ),
        data_dir=tmp_path,
    )
    try:
        phases = engine._phases
        assert phases is not None
        offered = {str(one.capability) for one in await _offered(phases)}
        assert "email" in offered
    finally:
        await engine.aclose()


async def test_planning_is_shown_the_time_in_the_configured_zone(tmp_path: Path) -> None:
    """#2964: ``Settings.timezone`` reaches planning, the one timezone source."""
    engine = build_engine(
        Settings(embedder=EmbedderKind.HASHING, timezone="America/New_York"),
        data_dir=tmp_path,
    )
    try:
        phases = engine._phases
        assert phases is not None
        assert phases._planning._zone.key == "America/New_York"
    finally:
        await engine.aclose()


async def test_planning_is_shown_utc_where_no_zone_is_configured(tmp_path: Path) -> None:
    """#2964: a deployment with no zone configured keeps UTC, the setting's default."""
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        phases = engine._phases
        assert phases is not None
        assert phases._planning._zone.key == "UTC"
    finally:
        await engine.aclose()
